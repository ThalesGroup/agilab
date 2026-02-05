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
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = '1'
if (-not $env:PYTHONIOENCODING) { $env:PYTHONIOENCODING = 'utf-8' }
$env:PYTHONUNBUFFERED = '1'

$DoTestApps = $TestApps.IsPresent

$StartTime = Get-Date

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
            $v = $kv[1].Trim().Trim('"').Trim("'")
            if ($k.StartsWith("PYTHON")) { return }
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
        Remove-Link -Path $LinkPath
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
        (Join-PathSafe $rootPath $Name),
        (Join-PathSafe (Join-PathSafe $rootPath 'src/agilab') $Name)
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

function Normalize-PathInput {
    param([object]$Value)
    if ($null -eq $Value) { return "" }
    if ($Value -is [string]) { return $Value }
    if ($Value -is [System.IO.FileSystemInfo]) { return $Value.FullName }
    if ($Value -is [object[]]) {
        $first = $Value | Where-Object { $_ } | Select-Object -First 1
        if ($null -ne $first) { return ($first.ToString()) }
        return ""
    }
    try { return ($Value.ToString()) } catch { return "" }
}

function Join-PathSafe {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true, Position=0)] [object]$Path,
        [Parameter(Mandatory=$true, Position=1)] [object]$ChildPath,
        [Parameter(ValueFromRemainingArguments=$true, Position=2)] [object[]]$AdditionalChildPath
    )
    $p  = Normalize-PathInput $Path
    $cp = Normalize-PathInput $ChildPath
    $rest = @()
    foreach ($a in $AdditionalChildPath) {
        $s = Normalize-PathInput $a
        if ($s) { $rest += [string]$s }
    }
    if (-not $p) { $p = '' }
    if (-not $cp) { $cp = '' }

    # Build the path iteratively for compatibility with Windows PowerShell 5.1
    $combined = Join-Path -Path ([string]$p) -ChildPath ([string]$cp)
    foreach ($seg in $rest) {
        $combined = Join-Path -Path $combined -ChildPath $seg
    }
    return $combined
}

function Resolve-AppDirectoryName {
    param(
        [string]$AppsRoot,
        [string]$AppName
    )
    if ([string]::IsNullOrWhiteSpace($AppsRoot) -or [string]::IsNullOrWhiteSpace($AppName)) {
        return $null
    }
    $normalizedRoot = Normalize-PathInput $AppsRoot
    $candidates = @($AppName)
    if (-not $AppName.EndsWith("_project", [System.StringComparison]::OrdinalIgnoreCase)) {
        $candidates += ("{0}_project" -f $AppName)
    }
    foreach ($candidate in $candidates) {
        $candidatePath = Join-PathSafe $normalizedRoot $candidate
        if (Test-Path -LiteralPath $candidatePath) {
            return $candidate
        }
    }
    return $null
}

function Remove-Link {
    param([Parameter(Mandatory=$true)][string]$Path)
    if (-not (Is-Link $Path)) { return }
    try {
        & cmd.exe /c rmdir "$Path" | Out-Null
    } catch {
        try {
            Remove-Item -LiteralPath $Path -Force -Confirm:$false
        } catch { }
    }
}

function ConvertTo-List {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return @() }
    return ($Value -split '[,\\s;]+' | Where-Object { $_ -ne '' })
}

function Invoke-UvPreview {
    param([string[]]$UvArgs)
    uv @UvArgs
    return $LASTEXITCODE
}

function Invoke-Uv {
    param([string[]]$UvArgs)
    uv @UvArgs
    return $LASTEXITCODE
}

function Add-Unique {
    param(
        [ref]$List,
        [string[]]$Items
    )
    $current = @($List.Value)
    foreach ($item in $Items) {
        if ([string]::IsNullOrWhiteSpace($item)) { continue }
        if (-not ($current -contains $item)) {
            $current += $item
        }
    }
    $List.Value = $current
}

# ----- Load environment ------------------------------------------------------
$LocalAppData = $env:LOCALAPPDATA
if (-not $LocalAppData) { $LocalAppData = Join-Path $HOME ".local/share" }
$envPath = Join-PathSafe $env:USERPROFILE ".agilab/.env"
Import-DotEnv -Path $envPath

Write-Color YELLOW "DEBUG: AGI_PYTHON_VERSION=$env:AGI_PYTHON_VERSION"
Write-Color YELLOW "DEBUG: APPS_REPOSITORY=$env:APPS_REPOSITORY"

$AGI_PYTHON_VERSION = $env:AGI_PYTHON_VERSION
if ($AGI_PYTHON_VERSION) {
    $AGI_PYTHON_VERSION = $AGI_PYTHON_VERSION -replace '^([0-9]+\\.[0-9]+\\.[0-9]+(\\+freethreaded)?).*$', '$1'
}

$agilabPathFile = Join-PathSafe $LocalAppData "agilab/.agilab-path"
if (-not (Test-Path -LiteralPath $agilabPathFile)) {
    Write-Color YELLOW "Warning: $agilabPathFile not found. Some paths may be unresolved."
    $AGILAB_PATH = ""
} else {
    $AGILAB_PATH = (Get-Content -LiteralPath $agilabPathFile -Raw).Trim()
}

# Preferred var names
$APPS_REPOSITORY   = $env:APPS_REPOSITORY
$AGILAB_REPOSITORY = if ($env:AGILAB_REPOSITORY) { $env:AGILAB_REPOSITORY } else { $AGILAB_PATH }

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


$AGILAB_REPOSITORY    = Normalize-PathInput $AGILAB_REPOSITORY
$APPS_REPOSITORY  = Normalize-PathInput $APPS_REPOSITORY
$AGILAB_REPOSITORY    = Fix-WindowsDrivePath $AGILAB_REPOSITORY
$APPS_REPOSITORY  = Fix-WindowsDrivePath $APPS_REPOSITORY

if (-not [string]::IsNullOrEmpty($APPS_REPOSITORY)) {
  $RepoRoot = Resolve-PhysicalPath $APPS_REPOSITORY
  if (-not $RepoRoot) { $RepoRoot = $APPS_REPOSITORY }
  Write-Color BLUE ("Using repository root: {0}" -f $RepoRoot)
  # Basic Windows path sanity hint: e.g. "C:Usersfoo" (missing backslashes)
  if ($APPS_REPOSITORY -match '^[A-Za-z]:(?![\\/])') {
    Write-Color YELLOW "Hint: The AppsRepository path '$APPS_REPOSITORY' looks malformed. On Windows, use backslashes and quote the path, e.g. 'C:\\Users\\me\\repo'"
  }
  $pagesCandidate = Find-RepoSubdir $RepoRoot 'apps-pages'
  if ($pagesCandidate) {
    $PAGES_TARGET_BASE = [string](Normalize-PathInput $pagesCandidate)
    $SkipRepositoryPages = $false
  } else {
    Write-Color BLUE "apps-pages not present under $APPS_REPOSITORY; repository pages will be skipped."
  }
  $appsCandidate = Find-RepoSubdir $RepoRoot 'apps'
  if ($appsCandidate) {
    $APPS_TARGET_BASE = [string](Normalize-PathInput $appsCandidate)
    $SkipRepositoryApps = $false
  } else {
    Write-Color BLUE "apps not present under $APPS_REPOSITORY; repository apps will be skipped."
  }
  if ($SkipRepositoryApps -and $SkipRepositoryPages) {
    $cand1 = Join-PathSafe $RepoRoot 'apps-pages'
    $cand2 = Join-PathSafe (Join-PathSafe $RepoRoot 'src/agilab') 'apps-pages'
    $cand3 = Join-PathSafe $RepoRoot 'apps'
    $cand4 = Join-PathSafe (Join-PathSafe $RepoRoot 'src/agilab') 'apps'
    Write-Color RED "Neither 'apps' nor 'apps-pages' directories were found under $APPS_REPOSITORY."
    Write-Color YELLOW ("Checked: {0}, {1}, {2}, {3}" -f $cand1, $cand2, $cand3, $cand4)
    Write-Color YELLOW "Provide at least one of the directories or omit -AppsRepository to fall back to built-in content."
    exit 1
  }
}

$APPS_DEST_BASE = if ($env:APPS_DEST_BASE) { $env:APPS_DEST_BASE }
    elseif (-not [string]::IsNullOrEmpty($AGILAB_REPOSITORY)) { Join-PathSafe ([string](Normalize-PathInput $AGILAB_REPOSITORY)) "apps" }
    else { Join-PathSafe (Get-Location) "apps" }
$PAGES_DEST_BASE = if ($env:PAGES_DEST_BASE) { $env:PAGES_DEST_BASE }
    elseif (-not [string]::IsNullOrEmpty($AGILAB_REPOSITORY)) { Join-PathSafe ([string](Normalize-PathInput $AGILAB_REPOSITORY)) "apps-pages" }
    else { Join-PathSafe (Get-Location) "apps-pages" }

$APPS_DEST_BASE  = [string](Normalize-PathInput $APPS_DEST_BASE)
$PAGES_DEST_BASE = [string](Normalize-PathInput $PAGES_DEST_BASE)

Ensure-Dir $APPS_DEST_BASE
Ensure-Dir $PAGES_DEST_BASE
Ensure-Dir (Join-PathSafe $APPS_DEST_BASE "builtin")

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

$repoDisplay = if ([string]::IsNullOrEmpty($APPS_REPOSITORY)) { "<none>" } else { [string]$APPS_REPOSITORY }
$publicDisplay = if ([string]::IsNullOrEmpty($AGILAB_REPOSITORY)) { "<none>" } else { [string]$AGILAB_REPOSITORY }
$appsTargetDisplay = if ([string]::IsNullOrEmpty($APPS_TARGET_BASE)) { "<none>" } else { $APPS_TARGET_BASE }
$pagesTargetDisplay = if ([string]::IsNullOrEmpty($PAGES_TARGET_BASE)) { "<none>" } else { $PAGES_TARGET_BASE }

Write-Color BLUE ("Using APPS_REPOSITORY: {0}" -f $repoDisplay)
Write-Color BLUE ("Using AGILAB_REPOSITORY: {0}" -f $publicDisplay)
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

$DefaultAppsOrder = @(
    'flight_project',
    'flight_clone_project',
    'flight_legacy_project',
    'flight_trajectory_project',
    'flowsynth_project',
    'ilp_project',
    'link_sim_project',
    'mycode_project',
    'network_sim_project',
    'rssi_predictor_project',
    'sat_trajectory_project',
    'satcom_sim_project',
    'sb3_trainer_project'
)

$DefaultSelectedApps = @(
    'flight_trajectory_project',
    'ilp_project',
    'link_sim_project',
    'network_sim_project',
    'sat_trajectory_project',
    'sb3_trainer_project'
)

$BuiltinSkipByDefault = @()
$AllAppsSentinel = if ($env:INSTALL_ALL_SENTINEL) { [string]$env:INSTALL_ALL_SENTINEL } else { '__AGILAB_ALL_APPS__' }
$BuiltinOnlySentinel = if ($env:INSTALL_BUILTIN_SENTINEL) { [string]$env:INSTALL_BUILTIN_SENTINEL } else { '__AGILAB_BUILTIN_APPS__' }

function Order-ByPreference {
    param(
        [string[]]$Items,
        [string[]]$Preferred
    )
    $ordered = New-Object System.Collections.Generic.List[string]
    foreach ($p in $Preferred) {
        if ($Items -contains $p -and -not $ordered.Contains($p)) {
            [void]$ordered.Add($p)
        }
    }
    foreach ($i in $Items) {
        if (-not $ordered.Contains($i)) {
            [void]$ordered.Add($i)
        }
    }
    return [string[]]$ordered.ToArray()
}

$builtinApps = @('mycode_project', 'flight_project')
$appsOverride = $env:BUILTIN_APPS_OVERRIDE
$promptForApps = $true
$forceAllApps = $false
$forceBuiltinOnly = $false
if (-not [string]::IsNullOrWhiteSpace($appsOverride)) {
    if ($appsOverride -eq $AllAppsSentinel) {
        $forceAllApps = $true
        $promptForApps = $false
        Write-Color BLUE "(Apps) Full install requested via BUILTIN_APPS_OVERRIDE; installing every available app."
    } elseif ($appsOverride -eq $BuiltinOnlySentinel) {
        $forceBuiltinOnly = $true
        $promptForApps = $false
        Write-Color BLUE "(Apps) Built-in install requested; repository apps will be skipped."
    } else {
        $builtinApps = ConvertTo-List $appsOverride
        Write-Color BLUE ("(Apps) Override enabled via BUILTIN_APPS_OVERRIDE: {0}" -f ($builtinApps -join ' '))
        $promptForApps = $false
    }
} elseif (-not [string]::IsNullOrWhiteSpace($env:BUILTIN_APPS)) {
    $appsEnv = [string]$env:BUILTIN_APPS
    if ($appsEnv -eq $AllAppsSentinel) {
        $forceAllApps = $true
        $promptForApps = $false
        Write-Color BLUE "(Apps) Full install requested (--install-apps all); installing every available app."
    } elseif ($appsEnv -eq $BuiltinOnlySentinel) {
        $forceBuiltinOnly = $true
        $promptForApps = $false
        Write-Color BLUE "(Apps) Built-in install requested (--install-apps builtin); repository apps will be skipped."
    } else {
        $builtinApps = ConvertTo-List $appsEnv
        Write-Color BLUE ("(Apps) Override enabled via BUILTIN_APPS: {0}" -f ($builtinApps -join ' '))
        $promptForApps = $false
    }
} elseif (Test-Path -LiteralPath $APPS_DEST_BASE) {
    $builtinRoot = Join-PathSafe $APPS_DEST_BASE "builtin"
    if (-not (Test-Path -LiteralPath $builtinRoot)) { $builtinRoot = $APPS_DEST_BASE }
    Get-ChildItem -LiteralPath $builtinRoot -Directory -Filter '*_project' | ForEach-Object {
        if (-not ($builtinApps -contains $_.Name)) {
            $builtinApps += $_.Name
        }
    }
}

$repositoryApps = @()
if ($forceBuiltinOnly) {
    $SkipRepositoryApps = $true
} 
if (-not $SkipRepositoryApps -and (Test-Path -LiteralPath $APPS_TARGET_BASE)) {
    $repositoryApps = Get-ChildItem -LiteralPath $APPS_TARGET_BASE -Directory -Filter '*_project' | ForEach-Object { $_.Name }
}

$includedPages = if ($SkipRepositoryPages) { $builtinPages } else { $builtinPages + $repositoryPages }
$allApps = @()
Add-Unique ([ref]$allApps) $builtinApps
Add-Unique ([ref]$allApps) $repositoryApps
$allApps = Order-ByPreference -Items $allApps -Preferred $DefaultAppsOrder

if ($forceAllApps) {
    $includedApps = $allApps
    $promptForApps = $false
} elseif (-not $promptForApps) {
    $includedApps = $builtinApps | Select-Object -Unique
} else {
    $selectedBuiltinApps = @()
    foreach ($a in $builtinApps) {
        if (-not ($BuiltinSkipByDefault -contains $a)) { $selectedBuiltinApps += $a }
    }
    $selectedRepoApps = @()
    foreach ($a in $repositoryApps) {
        if ($DefaultSelectedApps -contains $a) { $selectedRepoApps += $a }
    }
    $includedApps = @()
    Add-Unique ([ref]$includedApps) $selectedBuiltinApps
    Add-Unique ([ref]$includedApps) $selectedRepoApps
    $includedApps = Order-ByPreference -Items $includedApps -Preferred $DefaultAppsOrder
}

$includedPages = $includedPages | Select-Object -Unique
$includedApps  = $includedApps  | Select-Object -Unique

$interactiveSession = $true
if ([Console]::IsInputRedirected) { $interactiveSession = $false }
if ($Host.Name -eq 'ServerRemoteHost') { $interactiveSession = $false }

if ($allApps.Count -gt 0 -and $promptForApps) {
    if ($interactiveSession) {
        Write-Color BLUE "Available apps:"
        for ($idx = 0; $idx -lt $allApps.Count; $idx++) {
            $app = $allApps[$idx]
            $marker = if ($includedApps -contains $app) { "[x]" } else { "[ ]" }
            Write-Host ("  {0,2}) {1} {2}" -f ($idx + 1), $marker, $app)
        }
        $selection = Read-Host "Numbers/ranges (1 3-5, blank = defaults)"
        if (-not [string]::IsNullOrWhiteSpace($selection)) {
            $tokens = $selection -split '[,\s]+' | Where-Object { $_ -ne '' }
            $picked = New-Object System.Collections.Generic.List[string]
            foreach ($token in $tokens) {
                if ($token -match '^(?<start>\d+)-(?<end>\d+)$') {
                    $start = [int]$Matches['start']
                    $end = [int]$Matches['end']
                    if ($end -lt $start) {
                        Write-Color YELLOW ("Ignoring invalid range: {0}" -f $token)
                        continue
                    }
                    for ($num = $start; $num -le $end; $num++) {
                        $i = $num - 1
                        if ($i -ge 0 -and $i -lt $allApps.Count) {
                            $value = $allApps[$i]
                            if (-not $picked.Contains($value)) {
                                [void]$picked.Add($value)
                            }
                        } else {
                            Write-Color YELLOW ("Ignoring out-of-range selection: {0}" -f $num)
                        }
                    }
                } elseif ($token -match '^\d+$') {
                    $i = [int]$token - 1
                    if ($i -ge 0 -and $i -lt $allApps.Count) {
                        $value = $allApps[$i]
                        if (-not $picked.Contains($value)) {
                            [void]$picked.Add($value)
                        }
                    } else {
                        Write-Color YELLOW ("Ignoring out-of-range selection: {0}" -f $token)
                    }
                } else {
                    Write-Color YELLOW ("Ignoring invalid selection: {0}" -f $token)
                }
            }
            if ($picked.Count -gt 0) {
                $includedApps = [string[]]$picked.ToArray()
            } else {
                Write-Color YELLOW "No valid selections detected; keeping defaults."
            }
        }
    } else {
        Write-Color YELLOW ("Non-interactive session detected; installing default apps: {0}." -f ($includedApps -join ' '))
    }
}

$allPages = @()
Add-Unique ([ref]$allPages) $builtinPages
Add-Unique ([ref]$allPages) $repositoryPages

$allApps = Order-ByPreference -Items $allApps -Preferred $DefaultAppsOrder

$filteredPages = @()
foreach ($page in $allPages) {
    if (-not ($includedPages -contains $page)) {
        $filteredPages += $page
    }
}
$filteredApps = @()
foreach ($app in $allApps) {
    if (-not ($includedApps -contains $app)) {
        $filteredApps += $app
    }
}

if ($includedPages.Count) {
    Write-Color BLUE ("Pages selected for install: {0}" -f ($includedPages -join ' '))
} else {
    Write-Color YELLOW "No pages selected for install."
}
if ($filteredPages.Count) {
    Write-Color YELLOW ("Pages filtered out: {0}" -f ($filteredPages -join ' '))
}
if ($includedApps.Count) {
    Write-Color BLUE ("Apps selected for install: {0}" -f ($includedApps -join ' '))
} else {
    Write-Color YELLOW "No apps selected for install."
}
if ($filteredApps.Count) {
    Write-Color YELLOW ("Apps filtered out: {0}" -f ($filteredApps -join ' '))
}
Write-Host ""

# --- Ensure local symlinks in repository -------------------------------------
if (-not $SkipRepositoryApps) {
    $repoAgilabDir = Split-Path -Parent $APPS_TARGET_BASE
    if ($repoAgilabDir -and (Test-Path -LiteralPath $repoAgilabDir)) {
        Push-Location $repoAgilabDir
        try {
            Write-Host -ForegroundColor Red $AGILAB_REPOSITORY
            $coreTargets = @()
            if (-not [string]::IsNullOrEmpty($AGILAB_REPOSITORY)) {
                $coreTargets = @(
                    (Join-PathSafe $AGILAB_REPOSITORY "core"),
                    (Join-PathSafe $AGILAB_REPOSITORY "src/agilab/core")
                )
            }
            $coreTarget = $coreTargets | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
            if (-not $coreTarget) {
                Write-Color YELLOW "Warning: can't find 'core' to link."
            } else {
                if (Test-Path -LiteralPath "core") {
                    Remove-Item -LiteralPath "core" -Force -Recurse -Confirm:$false -ErrorAction SilentlyContinue
                }
                New-DirLink -LinkPath "core" -TargetPath ([string](Normalize-PathInput $coreTarget))
                uv --preview-features extra-build-dependencies run python -c "import pathlib; p=pathlib.Path('core').resolve(); print(f'Repository core -> {p}')"
            }

            $publicTemplates = if ($AGILAB_REPOSITORY) { Join-PathSafe $AGILAB_REPOSITORY "apps/templates" } else { "" }
            if ($publicTemplates -and (Test-Path -LiteralPath $publicTemplates)) {
                Ensure-Dir "apps"
                $repoTemplates = Join-PathSafe "apps" "templates"
                if (Test-Path -LiteralPath $repoTemplates) {
                    if (Is-Link $repoTemplates) {
                        Remove-Link -Path $repoTemplates
                    } else {
                        Write-Color YELLOW ("Replacing repository templates directory with link -> {0}" -f $publicTemplates)
                        Remove-Item -LiteralPath $repoTemplates -Force -Recurse -Confirm:$false
                    }
                }
                if (-not (Test-Path -LiteralPath $repoTemplates)) {
                    New-DirLink -LinkPath $repoTemplates -TargetPath $publicTemplates
                    Write-Color BLUE ("Linked repository templates to {0}" -f $publicTemplates)
                }
            }
        } finally {
            Pop-Location
        }
    }
}

$status = 0

if (-not $SkipRepositoryPages) {
    foreach ($page in $repositoryPages) {
        $pageTarget = Join-PathSafe $PAGES_TARGET_BASE $page
        $pageDest   = Join-PathSafe $PAGES_DEST_BASE $page

        if (-not (Test-Path -LiteralPath $pageTarget)) {
            Write-Color YELLOW ("Skipping repository page '{0}': missing target {1}." -f $page, $pageTarget)
            continue
        }

        if (Is-Link $pageDest) {
            Write-Color BLUE ("Page '{0}' is a link. Recreating -> '{1}'..." -f $pageDest, $pageTarget)
            Remove-Link -Path $pageDest
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
        $appTarget = Join-PathSafe $APPS_TARGET_BASE $app
        $appDest   = Join-PathSafe $APPS_DEST_BASE $app

        if (-not (Test-Path -LiteralPath $appTarget)) {
            Write-Color YELLOW ("Skipping repository app '{0}': missing target {1}." -f $app, $appTarget)
            continue
        }

        if (Is-Link $appDest) {
            Write-Color BLUE ("App '{0}' is a link. Recreating -> '{1}'..." -f $appDest, $appTarget)
            Remove-Link -Path $appDest
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
$appsPagesRoot = if ($AGILAB_REPOSITORY) { Join-PathSafe ([string](Normalize-PathInput $AGILAB_REPOSITORY)) "apps-pages" } else { "" }
$appsRoot      = if ($AGILAB_REPOSITORY) { Join-PathSafe ([string](Normalize-PathInput $AGILAB_REPOSITORY)) "apps" } else { "" }

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
    Write-Color RED ("Missing apps-pages directory under {0}" -f $AGILAB_REPOSITORY)
    $status = 1
}

# --- Install apps ------------------------------------------------------------
if (-not [string]::IsNullOrEmpty($appsRoot) -and (Test-Path -LiteralPath $appsRoot)) {
    Push-Location $appsRoot
    foreach ($app in $includedApps) {
        $appDirName = Resolve-AppDirectoryName -AppsRoot $appsRoot -AppName $app
        if (-not $appDirName) {
            Write-Color YELLOW ("Skipping '{0}': directory not found under {1}." -f $app, $appsRoot)
            $status = 1
            continue
        }

        Write-Color BLUE ("Installing $appDirName...")

        $fullAppPath = Join-PathSafe $appsRoot $appDirName
        $fullAppPath = (Resolve-Path -LiteralPath $fullAppPath).Path

        $installArgs = @("run")
        if ($AGI_PYTHON_VERSION) { $installArgs += @("-p", $AGI_PYTHON_VERSION) }

        # Passage explicite des arguments
        $installArgs += @(
            "--project",
            "../core/agi-cluster",
            "python",
            "install.py",
            $fullAppPath
        )

        Write-Color BLUE ("DEBUG: Running command: uv " + ($installArgs -join " "))
#         $installExit = Invoke-UvPreview $installArgs
        uv --preview-features extra-build-dependencies run --project ../core/agi-cluster python ./install.py $fullAppPath
        $installExit = $LASTEXITCODE
        if ($installExit -eq 0) {
            Write-Color GREEN ("{0} successfully installed." -f $appDirName)
            if ($DoTestApps) {
                Write-Color GREEN "Checking installation..."
                if (Test-Path -LiteralPath $appDirName) {
                    Push-Location $appDirName
                    if (Test-Path -LiteralPath "app_test.py") {
                        uv --preview-features extra-build-dependencies run --no-sync python app_test.py
                        $testExit = $LASTEXITCODE
                        if ($testExit -ne 0) {
                            $status = 1
                        }
                    } else {
                        Write-Color BLUE ("No app_test.py in {0}, skipping tests." -f $appDirName)
                    }
                    Pop-Location
                } else {
                    Write-Color YELLOW ("Warning: could not enter '{0}' to run tests." -f $appDirName)
                }
            }
        } else {
            Write-Color RED ("{0} installation failed with exit code {1}." -f $appDirName, $installExit)
            $status = 1
        }
    }
    Pop-Location
} elseif (-not [string]::IsNullOrEmpty($appsRoot)) {
    Write-Color RED ("Missing apps directory under {0}" -f $AGILAB_REPOSITORY)
    $status = 1
}

# --- Optional pytest ---------------------------------------------------------
if ($DoTestApps) {
    Write-Color BLUE "Running pytest for installed apps..."
    if (-not [string]::IsNullOrEmpty($appsRoot) -and (Test-Path -LiteralPath $appsRoot)) {
        Push-Location $appsRoot
        foreach ($app in $includedApps) {
            $appDirName = Resolve-AppDirectoryName -AppsRoot $appsRoot -AppName $app
            if (-not $appDirName) {
                Write-Color YELLOW ("Skipping pytest for '{0}': directory not found." -f $app)
                continue
            }
            Write-Color BLUE ("[pytest] {0}" -f $appDirName)
            Push-Location $appDirName
            $pytestArgs = @("run", "--no-sync")
            if ($AGI_PYTHON_VERSION) { $pytestArgs += @("-p", $AGI_PYTHON_VERSION) }
            $pytestArgs += @("--project", ".", "pytest")
            $pytestExit = Invoke-UvPreview @($pytestArgs)
            switch ($pytestExit) {
                0 { Write-Color GREEN ("pytest succeeded for '{0}'." -f $appDirName) }
                5 { Write-Color YELLOW ("No tests collected for '{0}'." -f $appDirName) }
                default {
                    Write-Color RED ("pytest failed for '{0}' (exit code {1})." -f $appDirName, $pytestExit)
                    $status = 1
                }
            }
            Pop-Location
        }
        Pop-Location
    }
}

# --- Final message -----------------------------------------------------------
if ($status -eq 0) {
    if (-not [string]::IsNullOrEmpty($APPS_REPOSITORY)) {
        $docsSourceDir = Join-PathSafe $APPS_REPOSITORY "docs/source"
        $docsExamplesLink = Join-PathSafe $docsSourceDir "examples"
        if (Test-Path -LiteralPath $docsSourceDir) {
            if (-not (Test-Path -LiteralPath $docsExamplesLink)) {
                try {
                    New-Item -ItemType SymbolicLink -Path $docsExamplesLink -Target "examples" | Out-Null
                } catch {
                    try {
                        $absoluteExamples = Join-PathSafe $APPS_REPOSITORY "examples"
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
