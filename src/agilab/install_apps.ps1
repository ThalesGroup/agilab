<#
  Script: install_apps_pages.ps1
  Purpose: Mirror the behavior of install_apps_pages.sh for Windows/PowerShell
  Notes:
    - Uses junctions for directory links (works without admin). Falls back to copying if linking fails.
    - Respects the same env vars as the bash script: AGI_PYTHON_VERSION, APPS_REPOSITORY, APPS_DEST_BASE, PAGES_DEST_BASE.
#>

#----- Strict mode / setup -----------------------------------------------------
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Colors
$C = @{
  RED    = "RED"
  GREEN  = "`GREEN"
  BLUE   = "`BLUE"
  YELLOW = "`YELLOW"
}
function Write-Color([string]$Color, [string]$Msg) {
  Write-Host $Msg -ForegroundColor  $C[$Color]
}

#----- Helpers ----------------------------------------------------------------
function Import-DotEnv([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) { return }
  Get-Content -LiteralPath $Path | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq '' -or $line.StartsWith('#')) { return }
    $kv = $line -split '=', 2
    if ($kv.Count -eq 2) {
      $k = $kv[0].Trim()
      $v = $kv[1].Trim().Trim('"')
      # Set in process env so child processes (uv/python) see it
      [Environment]::SetEnvironmentVariable($k, $v, 'Process')
    }
  }
}

function Is-Link([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) { return $false }
  try {
    $itm = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    return ($itm.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
  } catch { return $false }
}

function Ensure-Dir([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) {
    New-Item -ItemType Directory -Path $Path | Out-Null
  }
}

function New-DirLink([string]$LinkPath, [string]$TargetPath) {
  # Prefer junction (works without admin). If it exists as link, recreate; if non-link dir, leave.
  if (Is-Link $LinkPath) { Remove-Item -LiteralPath $LinkPath -Force }
  elseif (Test-Path -LiteralPath $LinkPath) {
    # Exists and is not a link -> leave untouched (parity with bash)
    return
  }
  try {
    New-Item -ItemType Junction -Path $LinkPath -Target $TargetPath | Out-Null
  } catch {
    # Fallback: try symbolic link (may require admin / developer mode)
    try {
      New-Item -ItemType SymbolicLink -Path $LinkPath -Target $TargetPath | Out-Null
    } catch {
      # Last resort: copy (best effort)
      Copy-Item -Recurse -Force -LiteralPath $TargetPath -Destination $LinkPath
    }
  }
}

function Find-RepoSubdir([string]$Root, [string]$Name) {
  if ([string]::IsNullOrEmpty($Root)) { return "" }
  try {
    $candidates = Get-ChildItem -LiteralPath $Root -Directory -Recurse -ErrorAction Stop |
      Where-Object { $_.Name -eq $Name }
  } catch {
    return ""
  }
  foreach ($candidate in $candidates) {
    if ($Name -eq 'apps') {
      $hasProjects = Get-ChildItem -LiteralPath $candidate.FullName -Directory -Filter '*_project' -ErrorAction SilentlyContinue | Select-Object -First 1
      if ($hasProjects) { return $candidate.FullName }
    } elseif ($Name -eq 'apps-pages') {
      $hasPages = Get-ChildItem -LiteralPath $candidate.FullName -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne '.venv' } | Select-Object -First 1
      if ($hasPages) { return $candidate.FullName }
    } else {
      return $candidate.FullName
    }
  }
  return ""
}

$UvPreviewArgs = @("--preview-features", "extra-build-dependencies")
function Invoke-UvPreview {
  param([string[]]$Args)
  & uv @UvPreviewArgs @Args
}

#----- Load env + normalize Python version ------------------------------------
$APPDATA = $env:LOCALAPPDATA
$envPath = Join-Path $APPDATA "agilab/.env"
Import-DotEnv -Path $envPath

# Normalize AGI_PYTHON_VERSION to e.g. 3.11.9 or 3.13.0+freethreaded
$AGI_PYTHON_VERSION = $env:AGI_PYTHON_VERSION
if ($AGI_PYTHON_VERSION) {
  $AGI_PYTHON_VERSION = $AGI_PYTHON_VERSION -replace '^([0-9]+\.[0-9]+\.[0-9]+(\+freethreaded)?).*$', '$1'
}

$agilabPathFile = Join-Path $APPDATA "agilab/.agilab-path"
if (-not (Test-Path -LiteralPath $agilabPathFile)) {
  Write-Color YELLOW "Warning: $agilabPathFile not found. Some paths may be unresolved."
  $AGILAB_PUBLIC = ""
} else {
  $AGILAB_PUBLIC = (Get-Content -LiteralPath $agilabPathFile -Raw).Trim()
}

$APPS_REPOSITORY = $env:APPS_REPOSITORY

$PAGES_TARGET_BASE = ""
$APPS_TARGET_BASE  = ""
$SkipRepositoryPages = $true
$SkipRepositoryApps  = $true

if (-not [string]::IsNullOrEmpty($APPS_REPOSITORY)) {
  $PAGES_TARGET_BASE = Find-RepoSubdir $APPS_REPOSITORY 'apps-pages'
  if (-not $PAGES_TARGET_BASE) {
    Write-Color RED "Error: Could not locate an 'apps-pages' directory under $APPS_REPOSITORY"
    exit 1
  }
  $APPS_TARGET_BASE = Find-RepoSubdir $APPS_REPOSITORY 'apps'
  if (-not $APPS_TARGET_BASE) {
    Write-Color RED "Error: Could not locate an 'apps' directory under $APPS_REPOSITORY"
    exit 1
  }
  $SkipRepositoryPages = $false
  $SkipRepositoryApps  = $false
}


# Destination base (defaults to current dir)
$APPS_DEST_BASE  = if ($env:APPS_DEST_BASE)  { $env:APPS_DEST_BASE }  else { Join-Path (Get-Location) "apps" }
$PAGES_DEST_BASE = if ($env:PAGES_DEST_BASE) { $env:PAGES_DEST_BASE } else { Join-Path (Get-Location) "apps-pages" }

Ensure-Dir $APPS_DEST_BASE
Ensure-Dir $PAGES_DEST_BASE

Write-Color BLUE "Using APPS_REPOSITORY: $APPS_REPOSITORY"
Write-Color BLUE "Using AGILAB_PUBLIC: $AGILAB_PUBLIC"

Write-Color BLUE "(Apps) Destination base: $APPS_DEST_BASE"
Write-Color BLUE "(Apps) Link target base: $APPS_TARGET_BASE"
Write-Color BLUE "(Pages) Destination base: $PAGES_DEST_BASE"
Write-Color BLUE "(Pages) Link target base: $PAGES_TARGET_BASE`n"

# --- App/Page lists (merge repository + public) ------------------------------
$REPOSITORY_PAGES = @()
if (-not $SkipRepositoryPages -and (Test-Path -LiteralPath $PAGES_TARGET_BASE)) {
  $REPOSITORY_PAGES = Get-ChildItem -LiteralPath $PAGES_TARGET_BASE -Directory |
    Where-Object { $_.Name -ne ".venv" } | ForEach-Object { $_.Name }
}

$REPOSITORY_APPS = @()
if (-not $SkipRepositoryApps -and (Test-Path -LiteralPath $APPS_TARGET_BASE)) {
  $REPOSITORY_APPS = Get-ChildItem -LiteralPath $APPS_TARGET_BASE -Directory -Filter "*_project" |
    ForEach-Object { $_.Name }
}

$BUILTIN_PAGES = @()
if (Test-Path -LiteralPath $PAGES_DEST_BASE) {
  $BUILTIN_PAGES = Get-ChildItem -LiteralPath $PAGES_DEST_BASE -Directory |
    Where-Object { $_.Name -ne ".venv" } | ForEach-Object { $_.Name }
}

$BUILTIN_APPS = @()
if (Test-Path -LiteralPath $APPS_DEST_BASE) {
  $BUILTIN_APPS = Get-ChildItem -LiteralPath $APPS_DEST_BASE -Directory -Filter "*_project" |
    ForEach-Object { $_.Name }
}

if ($SkipRepositoryPages) {
  $INCLUDED_PAGES = @($BUILTIN_PAGES)
} else {
  $INCLUDED_PAGES = @($REPOSITORY_PAGES + $BUILTIN_PAGES)
}

if ($SkipRepositoryApps) {
  $INCLUDED_APPS = @($BUILTIN_APPS)
} else {
  $INCLUDED_APPS  = @($REPOSITORY_APPS + $BUILTIN_APPS)
}

Write-Color BLUE ("Apps to install: " + ($(if ($INCLUDED_APPS.Count) { $INCLUDED_APPS -join ' ' } else { "<none>" })))
Write-Color BLUE ("Pages to install: " + ($(if ($INCLUDED_PAGES.Count) { $INCLUDED_PAGES -join ' ' } else { "<none>" })) + "`n")

# --- Ensure local links in DEST_BASE -----------------------------------------
if (-not $SkipRepositoryApps) {
  $repoAgilabPath = if ($APPS_TARGET_BASE) { Split-Path -Parent $APPS_TARGET_BASE } else { "" }
  if (Test-Path -LiteralPath $repoAgilabPath) {
    Push-Location $repoAgilabPath
    if (Test-Path -LiteralPath "core") { Remove-Item -LiteralPath "core" -Force -Recurse -ErrorAction SilentlyContinue }
    $target = if (Test-Path (Join-Path $AGILAB_PUBLIC "core")) {
      Join-Path $AGILAB_PUBLIC "core"
  } elseif (Test-Path (Join-Path $AGILAB_PUBLIC "src/agilab/core")) {
    Join-Path $AGILAB_PUBLIC "src/agilab/core"
  } else {
    Write-Color RED "ERROR: can't find 'core' under `$AGILAB_PUBLIC ($AGILAB_PUBLIC).`nTried: `$AGILAB_PUBLIC/core and `$AGILAB_PUBLIC/src/agilab/core"
    exit 1
  }
  New-DirLink -LinkPath "core" -TargetPath $target
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
  } else {
    if ($publicTemplates) {
      Write-Color YELLOW ("Warning: expected templates at {0} not found; skipping link." -f $publicTemplates)
    }
  }
    Pop-Location
  }
}

$status = 0
if (-not $SkipRepositoryPages){
  foreach ($page in $REPOSITORY_PAGES) {
    $page_target = Join-Path $PAGES_TARGET_BASE $page
    $page_dest   = Join-Path $PAGES_DEST_BASE $page
    if (-not (Test-Path -LiteralPath $page_target)) {
      Write-Color RED "Target for '$page' not found: $page_target — skipping."
      $global:status = 1; continue
    }
    if (Is-Link $page_dest) {
      Write-Color BLUE "Page '$page_dest' is a link. Recreating -> '$page_target'..."
      Remove-Item -LiteralPath $page_dest -Force
      New-DirLink -LinkPath $page_dest -TargetPath $page_target
    } elseif (-not (Test-Path -LiteralPath $page_dest)) {
      Write-Color BLUE "Page '$page_dest' does not exist. Creating link -> '$page_target'..."
      New-DirLink -LinkPath $page_dest -TargetPath $page_target
    } else {
      Write-Color GREEN "Page '$page_dest' exists and is not a link. Leaving untouched."
    }
  }

  foreach ($app in $REPOSITORY_APPS) {
    $app_target = Join-Path $APPS_TARGET_BASE $app
    $app_dest   = Join-Path $APPS_DEST_BASE $app
    if (-not (Test-Path -LiteralPath $app_target)) {
      Write-Color RED "Target for '$app' not found: $app_target — skipping."
      $global:status = 1; continue
    }
    if (Is-Link $app_dest) {
      Write-Color BLUE "App '$app_dest' is a link. Recreating -> '$app_target'..."
      Remove-Item -LiteralPath $app_dest -Force
      New-DirLink -LinkPath $app_dest -TargetPath $app_target
    } elseif (-not (Test-Path -LiteralPath $app_dest)) {
      Write-Color BLUE "App '$app_dest' does not exist. Creating link -> '$app_target'..."
      New-DirLink -LinkPath $app_dest -TargetPath $app_target
    } else {
      Write-Color GREEN "App '$app_dest' exists and is not a link. Leaving untouched."
    }
  }
}

# --- Install pages ------------------------------------------------------------
if (-not [string]::IsNullOrEmpty($AGILAB_PUBLIC)) {
  Push-Location (Join-Path $AGILAB_PUBLIC "apps-pages")
  foreach ($page in $INCLUDED_PAGES) {
    Write-Color BLUE "Installing $page..."
    Push-Location $page
    Invoke-UvPreview @("sync", "--project", ".", "--preview-features", "python-upgrade") | Out-Host
    if ($LASTEXITCODE -ne 0) {
      Write-Color RED "Error during 'uv sync' for page '$page'."
      $status = 1
    }
    Pop-Location
  }
  Pop-Location

  # --- Install apps -----------------------------------------------------------
  Push-Location (Join-Path $AGILAB_PUBLIC "apps")
  foreach ($app in $INCLUDED_APPS) {
    Write-Color BLUE "Installing $app..."
    & uv -q run -p $AGI_PYTHON_VERSION --project ../core/cluster python install.py (Join-Path $AGILAB_PUBLIC "apps/$app") | Out-Host
    if ($LASTEXITCODE -eq 0) {
      Write-Color GREEN "$app successfully installed."
      Write-Color GREEN "Checking installation..."
      if (Test-Path -LiteralPath $app) {
        Push-Location $app
        if (Test-Path -LiteralPath "app_test.py") {
          & uv run -p $AGI_PYTHON_VERSION python app_test.py | Out-Host
          if ($LASTEXITCODE -ne 0) { 
            $status = 1
          }
        } else {
          Write-Color BLUE "No app_test.py in $app, skipping tests."
        }
        Pop-Location
      } else {
        Write-Color YELLOW "Warning: could not enter '$app' to run tests."
      }
    } else {
      Write-Color RED "$app installation failed."
      $status = 1
    }
  }
  Pop-Location
}

# --- Final message ------------------------------------------------------------
if ($status -eq 0) {
  Write-Color GREEN "Installation of apps complete!"
} else {
  Write-Color YELLOW "Installation finished with some errors (status=$status)."
}
exit $status
