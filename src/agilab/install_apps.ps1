<#
  Script: install_apps.ps1
  Purpose: Mirror the behavior of install_apps.sh for Windows/PowerShell.
  Notes:
    - Uses junctions for directory links (works without admin). Falls back to copying if linking fails.
    - Respects the same env vars as the bash script: AGI_PYTHON_VERSION, APPS_REPOSITORY, APPS_DEST_BASE, PAGES_DEST_BASE.
#>

[CmdletBinding()]
param(
    [switch]$TestApps
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$DoTestApps = $TestApps.IsPresent

$ColorMap = @{
    RED    = 'Red'
    GREEN  = 'Green'
    BLUE   = 'Blue'
    YELLOW = 'Yellow'
}

function Write-Color {
    param([string]$Color, [string]$Message)
    $fg = if ($ColorMap.ContainsKey($Color)) { $ColorMap[$Color] } else { 'White' }
    Write-Host $Message -ForegroundColor $fg
}

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if ($line -eq '' -or $line.StartsWith('#')) { return }
        $kv = $line -split '=', 2
        if ($kv.Count -eq 2) {
            $k = $kv[0].Trim()
            $v = $kv[1].Trim().Trim('"')
            [Environment]::SetEnvironmentVariable($k, $v, 'Process')
        }
    }
}

function Is-Link {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    try {
        $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        return ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
    } catch { return $false }
}

function Ensure-Dir {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return }
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function New-DirLink {
    param([string]$LinkPath, [string]$TargetPath)
    if (Is-Link $LinkPath) {
        Remove-Item -LiteralPath $LinkPath -Force
    } elseif (Test-Path -LiteralPath $LinkPath) {
        # Existing non-link directory should be left untouched (matches Bash behavior)
        return
    }
    try {
        New-Item -ItemType Junction -Path $LinkPath -Target $TargetPath | Out-Null
    } catch {
        try {
            New-Item -ItemType SymbolicLink -Path $LinkPath -Target $TargetPath | Out-Null
        } catch {
            Copy-Item -Recurse -Force -LiteralPath $TargetPath -Destination $LinkPath
        }
    }
}

function Find-RepoSubdir {
    param([string]$Root, [string]$Name)
    if ([string]::IsNullOrWhiteSpace($Root)) { return "" }
    $rootPath = Resolve-PhysicalPath $Root
    if (-not $rootPath) { $rootPath = $Root }

    # Fast known-candidate checks (common layouts)
    $known = @(
        (Join-Path $rootPath $Name),
        (Join-Path (Join-Path $rootPath 'src/agilab') $Name)
    )
    foreach ($k in $known) {
        if (Test-Path -LiteralPath $k) { return (Resolve-PhysicalPath $k) }
    }

    # Fallback: recursive scan, tolerant to errors
    try {
        $candidates = Get-ChildItem -LiteralPath $rootPath -Directory -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -eq $Name }
    } catch { $candidates = @() }

    foreach ($candidate in $candidates) {
        if ($Name -eq 'apps') {
            $hasProjects = Get-ChildItem -LiteralPath $candidate.FullName -Directory -Filter '*_project' -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($hasProjects) { return (Resolve-PhysicalPath $candidate.FullName) }
        } elseif ($Name -eq 'apps-pages') {
            $hasPages = Get-ChildItem -LiteralPath $candidate.FullName -Directory -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -ne '.venv' } | Select-Object -First 1
            if ($hasPages) { return (Resolve-PhysicalPath $candidate.FullName) }
        } else {
            return (Resolve-PhysicalPath $candidate.FullName)
        }
    }
    return ""
}

function Resolve-PhysicalPath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return "" }
    try {
        return (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    } catch {
        return ""
    }
}

function ConvertTo-List {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return @() }
    return ($Value -split '[,\s;]+' | Where-Object { $_ -ne '' })
}

function Invoke-UvPreview {
    param([string[]]$UvArgs)
    & uv --preview-features extra-build-dependencies @UvArgs
    return $LASTEXITCODE
}

# ----- Load environment ------------------------------------------------------
$LocalAppData = $env:LOCALAPPDATA
$envPath = Join-Path $LocalAppData "agilab/.env"
Import-DotEnv -Path $envPath

$AGI_PYTHON_VERSION = $env:AGI_PYTHON_VERSION
if ($AGI_PYTHON_VERSION) {
    $AGI_PYTHON_VERSION = $AGI_PYTHON_VERSION -replace '^([0-9]+\.[0-9]+\.[0-9]+(\+freethreaded)?).*$', '$1'
}

$agilabPathFile = Join-Path $LocalAppData "agilab/.agilab-path"
if (-not (Test-Path -LiteralPath $agilabPathFile)) {
    Write-Color YELLOW "Warning: $agilabPathFile not found. Some paths may be unresolved."
    $AGILAB_PUBLIC = ""
} else {
    $AGILAB_PUBLIC = (Get-Content -LiteralPath $agilabPathFile -Raw).Trim()
}

# Preferred var name (with legacy fallback)
$APPS_REPOSITORY = if ($env:APPS_REPOSITORY) { $env:APPS_REPOSITORY } else { $env:AGILAB_APPS_REPOSITORY }

$PAGES_TARGET_BASE = ""
$APPS_TARGET_BASE  = ""
$SkipRepositoryPages = $true
$SkipRepositoryApps  = $true

function Fix-WindowsDrivePath {
  param([string]$Path)
  if ([string]::IsNullOrWhiteSpace($Path)) { return $Path }
  $p = $Path.Trim()
  if ($p -match '^[A-Za-z]:(?![\\/])') { $p = $p.Substring(0,2) + '\\' + $p.Substring(2) }
  return $p
}


$APPS_REPOSITORY = Fix-WindowsDrivePath $APPS_REPOSITORY

if (-not [string]::IsNullOrEmpty($APPS_REPOSITORY)) {
  $RepoRoot = Resolve-PhysicalPath $APPS_REPOSITORY
  if (-not $RepoRoot) { $RepoRoot = $APPS_REPOSITORY }
  Write-Color BLUE ("Using repository root: {0}" -f $RepoRoot)
  # Basic Windows path sanity hint: e.g. "C:Usersfoo" (missing backslashes)
  if ($APPS_REPOSITORY -match '^[A-Za-z]:(?![\\/])') {
    Write-Color YELLOW "Hint: The AppsRepository path '$APPS_REPOSITORY' looks malformed. On Windows, use backslashes and quote the path, e.g. 'C:\\Users\\me\\repo'"
  }
  $PAGES_TARGET_BASE = Find-RepoSubdir $RepoRoot 'apps-pages'
  if (-not $PAGES_TARGET_BASE) {
    Write-Color RED "Error: Could not locate an 'apps-pages' directory under $APPS_REPOSITORY"
    $cand1 = Join-Path $RepoRoot 'apps-pages'
    $cand2 = Join-Path (Join-Path $RepoRoot 'src/agilab') 'apps-pages'
    Write-Color YELLOW ("Checked: {0} and {1}" -f $cand1, $cand2)
    Write-Color YELLOW "Hint: Ensure the repository contains an 'apps-pages' folder or omit -AppsRepository to skip repository pages."
    $here = (Get-Location).Path
    if ($here -match '^[A-Za-z]:(?![\\/])') { $here = $here.Substring(0,2) + '\\' + $here.Substring(2) }
    Write-Color YELLOW ("Hint: If this is the current repo, pass -AppsRepository '{0}'" -f $here)
    exit 1
  }
  $APPS_TARGET_BASE = Find-RepoSubdir $RepoRoot 'apps'
  if (-not $APPS_TARGET_BASE) {
    Write-Color RED "Error: Could not locate an 'apps' directory under $APPS_REPOSITORY"
    $cand1 = Join-Path $RepoRoot 'apps'
    $cand2 = Join-Path (Join-Path $RepoRoot 'src/agilab') 'apps'
    Write-Color YELLOW ("Checked: {0} and {1}" -f $cand1, $cand2)
    Write-Color YELLOW "Hint: Ensure the repository contains an 'apps' folder (with '*_project' subfolders), or omit -AppsRepository to skip repository apps."
    exit 1
  }
  $SkipRepositoryPages = $false
  $SkipRepositoryApps  = $false
}

$APPS_DEST_BASE = if ($env:APPS_DEST_BASE) { $env:APPS_DEST_BASE }
    elseif (-not [string]::IsNullOrEmpty($AGILAB_PUBLIC)) { Join-Path $AGILAB_PUBLIC "apps" }
    else { Join-Path (Get-Location) "apps" }
$PAGES_DEST_BASE = if ($env:PAGES_DEST_BASE) { $env:PAGES_DEST_BASE }
    elseif (-not [string]::IsNullOrEmpty($AGILAB_PUBLIC)) { Join-Path $AGILAB_PUBLIC "apps-pages" }
    else { Join-Path (Get-Location) "apps-pages" }

Ensure-Dir $APPS_DEST_BASE
Ensure-Dir $PAGES_DEST_BASE

$AppsDestReal = Resolve-PhysicalPath $APPS_DEST_BASE
$PagesDestReal = Resolve-PhysicalPath $PAGES_DEST_BASE
$AppsTargetReal = ""
$PagesTargetReal = ""

if (-not $SkipRepositoryApps) {
    $AppsTargetReal = Resolve-PhysicalPath $APPS_TARGET_BASE
    if ($AppsDestReal -and $AppsTargetReal -and $AppsDestReal -eq $AppsTargetReal) {
        Write-Color YELLOW ("Warning: apps destination resolves inside the repository tree; skipping repository app symlink refresh to avoid self-links. (dest={0})." -f $AppsDestReal)
        $SkipRepositoryApps = $true
    }
}

if (-not $SkipRepositoryPages) {
    $PagesTargetReal = Resolve-PhysicalPath $PAGES_TARGET_BASE
    if ($PagesDestReal -and $PagesTargetReal -and $PagesDestReal -eq $PagesTargetReal) {
        Write-Color YELLOW ("Warning: pages destination resolves inside the repository tree; skipping repository page symlink refresh to avoid self-links. (dest={0})." -f $PagesDestReal)
        $SkipRepositoryPages = $true
    }
}

$repoDisplay = if ([string]::IsNullOrEmpty($APPS_REPOSITORY)) { "<none>" } else { $APPS_REPOSITORY }
$publicDisplay = if ([string]::IsNullOrEmpty($AGILAB_PUBLIC)) { "<none>" } else { $AGILAB_PUBLIC }
$appsTargetDisplay = if ([string]::IsNullOrEmpty($APPS_TARGET_BASE)) { "<none>" } else { $APPS_TARGET_BASE }
$pagesTargetDisplay = if ([string]::IsNullOrEmpty($PAGES_TARGET_BASE)) { "<none>" } else { $PAGES_TARGET_BASE }

Write-Color BLUE ("Using APPS_REPOSITORY: {0}" -f $repoDisplay)
Write-Color BLUE ("Using AGILAB_PUBLIC: {0}" -f $publicDisplay)
Write-Color BLUE ("(Apps) Destination base: {0}" -f $APPS_DEST_BASE)
Write-Color BLUE ("(Apps) Link target base: {0}" -f $appsTargetDisplay)
Write-Host ""
Write-Color BLUE ("(Pages) Destination base: {0}" -f $PAGES_DEST_BASE)
Write-Color BLUE ("(Pages) Link target base: {0}" -f $pagesTargetDisplay)
Write-Host ""

# --- Determine builtin and repository lists ----------------------------------
$builtinPages = @()
$pagesOverride = $env:BUILTIN_PAGES_OVERRIDE
if (-not [string]::IsNullOrWhiteSpace($pagesOverride)) {
    $builtinPages = ConvertTo-List $pagesOverride
    Write-Color BLUE ("(Pages) Override enabled via BUILTIN_PAGES_OVERRIDE: {0}" -f ($builtinPages -join ' '))
} elseif (-not [string]::IsNullOrWhiteSpace($env:BUILTIN_PAGES)) {
    $builtinPages = ConvertTo-List $env:BUILTIN_PAGES
    Write-Color BLUE ("(Pages) Override enabled via BUILTIN_PAGES: {0}" -f ($builtinPages -join ' '))
} elseif (Test-Path -LiteralPath $PAGES_DEST_BASE) {
    Get-ChildItem -LiteralPath $PAGES_DEST_BASE -Directory | Where-Object { $_.Name -ne '.venv' } | ForEach-Object {
        if (-not ($builtinPages -contains $_.Name)) {
            $builtinPages += $_.Name
        }
    }
}

$repositoryPages = @()
if (-not $SkipRepositoryPages -and (Test-Path -LiteralPath $PAGES_TARGET_BASE)) {
    $repositoryPages = Get-ChildItem -LiteralPath $PAGES_TARGET_BASE -Directory |
        Where-Object { $_.Name -ne '.venv' } |
        ForEach-Object { $_.Name }
}

$builtinApps = @('mycode_project', 'flight_project')
$appsOverride = $env:BUILTIN_APPS_OVERRIDE
if (-not [string]::IsNullOrWhiteSpace($appsOverride)) {
    $builtinApps = ConvertTo-List $appsOverride
    Write-Color BLUE ("(Apps) Override enabled via BUILTIN_APPS_OVERRIDE: {0}" -f ($builtinApps -join ' '))
} elseif (-not [string]::IsNullOrWhiteSpace($env:BUILTIN_APPS)) {
    $builtinApps = ConvertTo-List $env:BUILTIN_APPS
    Write-Color BLUE ("(Apps) Override enabled via BUILTIN_APPS: {0}" -f ($builtinApps -join ' '))
} elseif (Test-Path -LiteralPath $APPS_DEST_BASE) {
    Get-ChildItem -LiteralPath $APPS_DEST_BASE -Directory -Filter '*_project' | ForEach-Object {
        if (-not ($builtinApps -contains $_.Name)) {
            $builtinApps += $_.Name
        }
    }
}

$repositoryApps = @('example_app_project', 'example_app_project', 'example_app_project', 'example_app_project', 'example_app_project')
if (-not $SkipRepositoryApps) {
    $existingRepoApps = @()
    foreach ($app in $repositoryApps) {
        $candidate = Join-Path $APPS_TARGET_BASE $app
        if (Test-Path -LiteralPath $candidate) {
            $existingRepoApps += $app
        }
    }
    $repositoryApps = $existingRepoApps
} else {
    $repositoryApps = @()
}

$includedPages = if ($SkipRepositoryPages) { $builtinPages } else { $builtinPages + $repositoryPages }
$includedApps = if ($SkipRepositoryApps) { $builtinApps } else { $builtinApps + $repositoryApps }

Write-Color BLUE ("Apps to install: {0}" -f ($(if ($includedApps.Count) { $includedApps -join ' ' } else { "<none>" })))
Write-Host ""
Write-Color BLUE ("Pages to install: {0}" -f ($(if ($includedPages.Count) { $includedPages -join ' ' } else { "<none>" })))
Write-Host ""

# --- Ensure local symlinks in repository -------------------------------------
if (-not $SkipRepositoryApps) {
    $repoAgilabDir = Split-Path -Parent $APPS_TARGET_BASE
    if ($repoAgilabDir -and (Test-Path -LiteralPath $repoAgilabDir)) {
        Push-Location $repoAgilabDir
        try {
            $coreTargets = @()
            if (-not [string]::IsNullOrEmpty($AGILAB_PUBLIC)) {
                $coreTargets = @(
                    Join-Path $AGILAB_PUBLIC "core",
                    Join-Path $AGILAB_PUBLIC "src/agilab/core"
                )
            }
            $coreTarget = $coreTargets | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
            if (-not $coreTarget) {
                $firstChoice = if ($coreTargets.Count -ge 1 -and $coreTargets[0]) { $coreTargets[0] } else { Join-Path $AGILAB_PUBLIC "core" }
                $secondChoice = if ($coreTargets.Count -ge 2 -and $coreTargets[1]) { $coreTargets[1] } else { Join-Path $AGILAB_PUBLIC "src/agilab/core" }
                $publicLabel = if ([string]::IsNullOrEmpty($AGILAB_PUBLIC)) { "<unknown>" } else { $AGILAB_PUBLIC }
                Write-Color RED ("ERROR: can't find 'core' under {0}.`nTried: {1} and {2}" -f $publicLabel, $firstChoice, $secondChoice)
                exit 1
            }
            if (Test-Path -LiteralPath "core") {
                Remove-Item -LiteralPath "core" -Force -Recurse -ErrorAction SilentlyContinue
            }
            New-DirLink -LinkPath "core" -TargetPath $coreTarget
            & uv run python -c "import pathlib; p=pathlib.Path('core').resolve(); print(f'Repository core -> {p}')" | Out-Host

            $publicTemplates = if ($AGILAB_PUBLIC) { Join-Path $AGILAB_PUBLIC "apps/templates" } else { "" }
            if ($publicTemplates -and (Test-Path -LiteralPath $publicTemplates)) {
                Ensure-Dir "apps"
                $repoTemplates = Join-Path "apps" "templates"
                if (Test-Path -LiteralPath $repoTemplates) {
                    if (Is-Link $repoTemplates) {
                        Remove-Item -LiteralPath $repoTemplates -Force
                    } else {
                        Write-Color YELLOW ("Replacing repository templates directory with link -> {0}" -f $publicTemplates)
                        Remove-Item -LiteralPath $repoTemplates -Force -Recurse
                    }
                }
                if (-not (Test-Path -LiteralPath $repoTemplates)) {
                    New-DirLink -LinkPath $repoTemplates -TargetPath $publicTemplates
                    Write-Color BLUE ("Linked repository templates to {0}" -f $publicTemplates)
                }
            } elseif ($publicTemplates) {
                Write-Color YELLOW ("Warning: expected templates at {0} not found; skipping link." -f $publicTemplates)
            }
        } finally {
            Pop-Location
        }
    }
}

$status = 0

if (-not $SkipRepositoryPages) {
    foreach ($page in $repositoryPages) {
        $pageTarget = Join-Path $PAGES_TARGET_BASE $page
        $pageDest   = Join-Path $PAGES_DEST_BASE $page

        if (-not (Test-Path -LiteralPath $pageTarget)) {
            Write-Color YELLOW ("Skipping repository page '{0}': missing target {1}." -f $page, $pageTarget)
            continue
        }

        if (Is-Link $pageDest) {
            Write-Color BLUE ("Page '{0}' is a link. Recreating -> '{1}'..." -f $pageDest, $pageTarget)
            Remove-Item -LiteralPath $pageDest -Force
            New-DirLink -LinkPath $pageDest -TargetPath $pageTarget
        } elseif (-not (Test-Path -LiteralPath $pageDest)) {
            Write-Color BLUE ("Page '{0}' does not exist. Creating link -> '{1}'..." -f $pageDest, $pageTarget)
            New-DirLink -LinkPath $pageDest -TargetPath $pageTarget
        } else {
            Write-Color GREEN ("Page '{0}' exists and is not a link. Leaving untouched." -f $pageDest)
        }
    }
}

if (-not $SkipRepositoryApps) {
    foreach ($app in $repositoryApps) {
        $appTarget = Join-Path $APPS_TARGET_BASE $app
        $appDest   = Join-Path $APPS_DEST_BASE $app

        if (-not (Test-Path -LiteralPath $appTarget)) {
            Write-Color YELLOW ("Skipping repository app '{0}': missing target {1}." -f $app, $appTarget)
            continue
        }

        if (Is-Link $appDest) {
            Write-Color BLUE ("App '{0}' is a link. Recreating -> '{1}'..." -f $appDest, $appTarget)
            Remove-Item -LiteralPath $appDest -Force
            New-DirLink -LinkPath $appDest -TargetPath $appTarget
        } elseif (-not (Test-Path -LiteralPath $appDest)) {
            Write-Color BLUE ("App '{0}' does not exist. Creating link -> '{1}'..." -f $appDest, $appTarget)
            New-DirLink -LinkPath $appDest -TargetPath $appTarget
        } else {
            Write-Color GREEN ("App '{0}' exists and is not a link. Leaving untouched." -f $appDest)
        }
    }
}

# --- Install pages -----------------------------------------------------------
$appsPagesRoot = if ($AGILAB_PUBLIC) { Join-Path $AGILAB_PUBLIC "apps-pages" } else { "" }
$appsRoot = if ($AGILAB_PUBLIC) { Join-Path $AGILAB_PUBLIC "apps" } else { "" }

if (-not [string]::IsNullOrEmpty($appsPagesRoot) -and (Test-Path -LiteralPath $appsPagesRoot)) {
    Push-Location $appsPagesRoot
    foreach ($page in $includedPages) {
        Write-Color BLUE ("Installing {0}..." -f $page)
        if (-not (Test-Path -LiteralPath $page)) {
            Write-Color YELLOW ("Skipping page '{0}': directory not found." -f $page)
            $status = 1
            continue
        }
        Push-Location $page
        $exit = Invoke-UvPreview @("sync", "--project", ".", "--preview-features", "python-upgrade")
        if ($exit -ne 0) {
            Write-Color RED ("Error during 'uv sync' for page '{0}'." -f $page)
            $status = 1
        }
        Pop-Location
    }
    Pop-Location
} elseif (-not [string]::IsNullOrEmpty($appsPagesRoot)) {
    Write-Color RED ("Missing apps-pages directory under {0}" -f $AGILAB_PUBLIC)
    $status = 1
}

# --- Install apps ------------------------------------------------------------
if (-not [string]::IsNullOrEmpty($appsRoot) -and (Test-Path -LiteralPath $appsRoot)) {
    Push-Location $appsRoot
    foreach ($app in $includedApps) {
        Write-Color BLUE ("Installing {0}..." -f $app)
        $installArgs = @("-q", "run")
        if ($AGI_PYTHON_VERSION) { $installArgs += @("-p", $AGI_PYTHON_VERSION) }
        $installArgs += @("--project", "../core/cluster", "python", "install.py", (Join-Path $AGILAB_PUBLIC "apps/$app"))
        & uv @installArgs | Out-Host
        $installExit = $LASTEXITCODE
        if ($installExit -eq 0) {
            Write-Color GREEN ("{0} successfully installed." -f $app)
            Write-Color GREEN "Checking installation..."
            if (Test-Path -LiteralPath $app) {
                Push-Location $app
                if (Test-Path -LiteralPath "app_test.py") {
                    $testArgs = @("run", "--no-sync")
                    if ($AGI_PYTHON_VERSION) { $testArgs += @("-p", $AGI_PYTHON_VERSION) }
                    $testArgs += @("python", "app_test.py")
                    & uv @testArgs | Out-Host
                    if ($LASTEXITCODE -ne 0) {
                        $status = 1
                    }
                } else {
                    Write-Color BLUE ("No app_test.py in {0}, skipping tests." -f $app)
                }
                Pop-Location
            } else {
                Write-Color YELLOW ("Warning: could not enter '{0}' to run tests." -f $app)
            }
        } else {
            Write-Color RED ("{0} installation failed." -f $app)
            $status = 1
        }
    }
    Pop-Location
} elseif (-not [string]::IsNullOrEmpty($appsRoot)) {
    Write-Color RED ("Missing apps directory under {0}" -f $AGILAB_PUBLIC)
    $status = 1
}

# --- Optional pytest ---------------------------------------------------------
if ($DoTestApps) {
    Write-Color BLUE "Running pytest for installed apps..."
    if (-not [string]::IsNullOrEmpty($appsRoot) -and (Test-Path -LiteralPath $appsRoot)) {
        Push-Location $appsRoot
        foreach ($app in $includedApps) {
            if (-not (Test-Path -LiteralPath $app)) {
                Write-Color YELLOW ("Skipping pytest for '{0}': directory not found." -f $app)
                continue
            }
            Write-Color BLUE ("[pytest] {0}" -f $app)
            Push-Location $app
            $pytestArgs = @("run", "--no-sync")
            if ($AGI_PYTHON_VERSION) { $pytestArgs += @("-p", $AGI_PYTHON_VERSION) }
            $pytestArgs += @("--project", ".", "pytest")
            & uv @pytestArgs | Out-Host
            $pytestExit = $LASTEXITCODE
            switch ($pytestExit) {
                0 { Write-Color GREEN ("pytest succeeded for '{0}'." -f $app) }
                5 { Write-Color YELLOW ("No tests collected for '{0}'." -f $app) }
                default {
                    Write-Color RED ("pytest failed for '{0}' (exit code {1})." -f $app, $pytestExit)
                    $status = 1
                }
            }
            Pop-Location
        }
        Pop-Location
    } else {
        $publicLabel = if ([string]::IsNullOrEmpty($AGILAB_PUBLIC)) { "<unknown>" } else { $AGILAB_PUBLIC }
        Write-Color YELLOW ("Skipping pytest runs: apps directory not found under {0}." -f $publicLabel)
    }
}

# --- Final message -----------------------------------------------------------
if ($status -eq 0) {
    if (-not [string]::IsNullOrEmpty($APPS_REPOSITORY)) {
        $docsSourceDir = Join-Path $APPS_REPOSITORY "docs/source"
        $docsExamplesLink = Join-Path $docsSourceDir "examples"
        if (Test-Path -LiteralPath $docsSourceDir) {
            if (-not (Test-Path -LiteralPath $docsExamplesLink)) {
                try {
                    New-Item -ItemType SymbolicLink -Path $docsExamplesLink -Target "examples" | Out-Null
                } catch {
                    try {
                        $absoluteExamples = Join-Path $APPS_REPOSITORY "examples"
                        if (Test-Path -LiteralPath $absoluteExamples) {
                            New-Item -ItemType Junction -Path $docsExamplesLink -Target $absoluteExamples | Out-Null
                        }
                    } catch {
                        Write-Color YELLOW ("Warning: unable to create docs/source/examples link: {0}" -f $_.Exception.Message)
                    }
                }
            }
        }
    }
}

if ($status -eq 0) {
    Write-Color GREEN "Installation of apps complete!"
} else {
    Write-Color YELLOW ("Installation finished with some errors (status={0})." -f $status)
}
exit $status
