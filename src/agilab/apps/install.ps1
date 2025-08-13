#!/usr/bin/env pwsh
# Script: install_Agi_apps.ps1
# Purpose: Install the apps (apps-only; no positional args required)
# Equivalent to install_Agi_apps.sh

#Set-StrictMode -Version Latest
#$ErrorActionPreference = "Stop"

function Write-Blue($msg)   { Write-Host $msg -ForegroundColor Blue }
function Write-Green($msg)  { Write-Host $msg -ForegroundColor Green }
function Write-Yellow($msg) { Write-Host $msg -ForegroundColor Yellow }
function Write-Red($msg)    { Write-Host $msg -ForegroundColor Red }

# --- Load environment ---
$envDir = Join-Path $env:LOCALAPPDATA "agilab"
$agiPathFile = Join-Path $envDir ".agilab-path"
$envFile = Join-Path $envDir ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match "^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$") {
            $name = $matches[1]
            $value = $matches[2] -replace "^['""]|['""]$", ""
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}

# Normalize Python version
if ($env:AGI_PYTHON_VERSION) {
    if ($env:AGI_PYTHON_VERSION -match '^([0-9]+\.[0-9]+\.[0-9]+(\+freethreaded)?)') {
        $env:AGI_PYTHON_VERSION = $matches[1]
    }
}
$env:PYTHONPATH = "$PWD" + $(if ($env:PYTHONPATH) { ":$($env:PYTHONPATH)" } else { "" })

# Installer entrypoint
$APP_INSTALL = "uv -q run -p $($env:AGI_PYTHON_VERSION) --project ../core/agi-cluster python install.py"

# Private apps list
$PRIVATE_APPS = @(
    "flight_trajectory_project"
#     "sat_trajectory_project",
#     "link_sim_project"
    # "flight_legacy_project"
)

# Destination base
if (-not $env:DEST_BASE) {
    $env:DEST_BASE = (Get-Location).Path
}
New-Item -ItemType Directory -Force -Path $env:DEST_BASE | Out-Null
Write-Yellow "Destination base: $(Resolve-Path $env:DEST_BASE)"

# --- Finder under $HOME; strip \src\agilab\apps (skip Windows-problematic folders)
function Find-ThalesAgilab {
  param([int]$MaxDepth = 5)

  # Paths to skip to avoid access prompts/slowness (Windows-specific)
  $skip = @(
    (Join-Path $HOME 'AppData'),
    (Join-Path $HOME 'OneDrive'),
    #(Join-Path HOME 'Documents'),
    #(Join-Path $HOME 'Desktop'),
    (Join-Path $HOME 'Pictures'),
    (Join-Path $HOME 'Music'),
    (Join-Path $HOME 'Videos'),
    (Join-Path $HOME 'Saved Games'),
    (Join-Path $HOME 'Contacts'),
    (Join-Path $HOME 'Searches'),
    (Join-Path $HOME 'Links'),
    (Join-Path $HOME 'Favorites'),
    (Join-Path $HOME 'NTUSER.DIR') # rare, defensive
  ) | ForEach-Object { $_.ToLowerInvariant() }

  # BFS with depth control; do not descend into reparse points or skipped paths
  $q = New-Object System.Collections.Generic.Queue[psobject]
  $q.Enqueue([pscustomobject]@{Dir = Get-Item -LiteralPath $HOME; Depth = 0})

  while ($q.Count -gt 0) {
    $node = $q.Dequeue()
    $dir  = $node.Dir
    $d    = $node.Depth

    # Check for ...\src\agilab\apps
    $appsCandidate = Join-Path $dir.FullName 'src\agilab\apps'
    if (Test-Path -LiteralPath $appsCandidate -PathType Container) {
      # return root (strip trailing segment)
      return Split-Path -Parent (Split-Path -Parent $appsCandidate)
    }

    if ($d -ge $MaxDepth) { continue }

    $children = @()
    try {
      $children = Get-ChildItem -LiteralPath $dir.FullName -Directory -Force -ErrorAction SilentlyContinue |
        Where-Object {
          # avoid reparse points (junctions/symlinks) during scan
          -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint)
        }
    } catch { continue }

    foreach ($c in $children) {
      $fp = $c.FullName.ToLowerInvariant()
      $shouldSkip = $false
      foreach ($s in $skip) {
        if ($fp -eq $s -or $fp.StartsWith($s + [IO.Path]::DirectorySeparatorChar)) { $shouldSkip = $true; break }
      }
      if ($shouldSkip) { continue }
      $q.Enqueue([pscustomobject]@{Dir = $c; Depth = $d + 1})
    }
  }

  return $null
}

$AGILAB_PUBLIC  = Get-Content $agiPathFile
$AGILAB_PRIVATE = $env:AGILAB_PRIVATE

if (-not $AGILAB_PRIVATE) {
    $AGILAB_PRIVATE = Find-ThalesAgilab -Depth 5
    if (-not $AGILAB_PRIVATE) {
        Write-Red "Error: Could not locate '*/src/agilab/apps' from `$HOME."
        exit 1
    }
}

Write-Yellow "Using AGILAB_PRIVATE: $AGILAB_PRIVATE"

$TARGET_BASE = Join-Path $AGILAB_PRIVATE "agilab/apps"
if (-not (Test-Path $TARGET_BASE)) {
    Write-Red "Error: Missing directory: $TARGET_BASE"
    exit 1
}

Write-Yellow "Link target base: $TARGET_BASE"
Write-Host ""

# Build the list of public apps
$PUBLIC_APPS = Get-ChildItem -Path $env:DEST_BASE -Directory -Filter "*_project" | ForEach-Object { $_.Name }
$INCLUDED_APPS = $PRIVATE_APPS + $PUBLIC_APPS

Write-Blue "Apps to install: $($INCLUDED_APPS -join ' ')"
Write-Host ""

# Ensure local symlinks exist
Push-Location (Join-Path $AGILAB_PRIVATE "agilab")
    Remove-Item -Force core -ErrorAction SilentlyContinue
    if (Test-Path (Join-Path $AGILAB_PUBLIC "core")) {
        $target = (Join-Path $AGILAB_PUBLIC "core")
    } elseif (Test-Path (Join-Path $AGILAB_PUBLIC "src/agilab/core")) {
        $target = (Join-Path $AGILAB_PUBLIC "src/agilab/core")
    } else {
        Write-Red "ERROR: can't find 'core' under $AGILAB_PUBLIC."
        exit 1
    }
    New-Item -ItemType Junction -Path "core" -Target $target | Out-Null
    & uv run python -c "import pathlib; p = pathlib.Path('core').resolve(); print(f'Private core -> {p}')"
Pop-Location

$status = 0
foreach ($app in $PRIVATE_APPS) {
    $app_target = Join-Path $TARGET_BASE $app
    $app_dest   = Join-Path $env:DEST_BASE $app

    if (-not (Test-Path $app_target)) {
        Write-Host "Target for $app not found: $app_target - skipping" -ForegroundColor Red
        $status = 1
        continue
    }

    if ((Test-Path $app_dest) -and (Get-Item $app_dest).LinkType) {
        Write-Blue "App '$app_dest' is a symlink. Recreating -> '$app_target'..."
        Remove-Item -Force $app_dest
        New-Item -ItemType Junction -Path $app_dest -Target $app_target | Out-Null
    } elseif (-not (Test-Path $app_dest)) {
        Write-Host "Ici 5"
        Write-Blue "App '$app_dest' does not exist. Creating symlink -> '$app_target'..."
        New-Item -ItemType Junction -Path $app_dest -Target $app_target | Out-Null
    } else {
        Write-Green "App '$app_dest' exists and is not a symlink. Leaving untouched."
    }
}

# Run installer for each app
Push-Location (Join-Path $AGILAB_PUBLIC "apps")

if (-not $env:INSTALL_TYPE) { $env:INSTALL_TYPE = "1" }

foreach ($app in $INCLUDED_APPS) {
    Write-Blue "Installing $app..."
    Write-Host "uv -q run -p $env:AGI_PYTHON_VERSION --project ../core/agi-cluster python install.py $app --apps-dir '$AGILAB_PUBLIC/apps' --install-type $env:INSTALL_TYPE"
    if (& uv -q run -p $env:AGI_PYTHON_VERSION --project ../core/agi-cluster python install.py `
        $app --apps-dir "$AGILAB_PUBLIC/apps" --install-type $env:INSTALL_TYPE) {
        Write-Green "$app successfully installed."
        Write-Green "Checking installation..."
        if (Test-Path $app) {
            Push-Location $app
            if (Test-Path "run-all-test.py") {
                & uv run -p $env:AGI_PYTHON_VERSION python run-all-test.py
            } else {
                Write-Blue "No run-all-test.py in $app, skipping tests."
            }
            Pop-Location
        } else {
            Write-Yellow "Warning: could not enter $app to run tests."
        }
    } else {
        Write-Red "$app installation failed."
        $status = 1
    }
}

Pop-Location

# Final message
if ($status -eq 0) {
    Write-Green "Installation of apps complete!"
} else {
    Write-Yellow "Installation finished with some errors (status=$status)."
}

exit $status
