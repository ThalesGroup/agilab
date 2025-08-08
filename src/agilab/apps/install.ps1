<#
install.ps1 — auto-detect thales-agilab and (re)create app symlinks
Aligned with Bash: default apps present, args/env/$apps override defaults.

Inputs (override defaults):
  - Args: pwsh ./install.ps1 app1 app2
  - Env : $env:INCLUDED_APPS="app1 app2"; pwsh ./install.ps1
  - Var : $apps = @("app1","app2"); pwsh ./install.ps1

Required env:
  - DEST_BASE : where symlinks should be created

Optional env:
  - THALES_AGILAB_ROOT : repo root override

Note: Uses PowerShell 7+ (for Get-ChildItem -Depth). Ask if you need PS 5.1 fallback.
#>

param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$AppArgs
)

$ErrorActionPreference = "Stop"

# ------------------
# Colors
# ------------------
function Info([string]$msg)  { Write-Host $msg -ForegroundColor Yellow }
function Ok([string]$msg)    { Write-Host $msg -ForegroundColor Green }
function Act([string]$msg)   { Write-Host $msg -ForegroundColor Cyan }   # Bash BLUE
function Err([string]$msg)   { Write-Host $msg -ForegroundColor Red }

# ------------------
# Default apps (same as Bash)
# ------------------
$INCLUDED_APPS = @(
  "mycode_project",
  "flight_project",
  "flight_trajectory",
  "sat_trajectory",
  "link_sim"
  # flight_legacy (commented out in Bash)
)

# ------------------
# Override order: args > env INCLUDED_APPS > $apps variable
# ------------------
if ($AppArgs -and $AppArgs.Count -gt 0) {
  $INCLUDED_APPS = $AppArgs
}
elseif ($env:INCLUDED_APPS) {
  $INCLUDED_APPS = @($env:INCLUDED_APPS -split '\s+')
}
elseif (Get-Variable -Name apps -Scope Script,Local,Global -ErrorAction SilentlyContinue) {
  $INCLUDED_APPS = $apps
}

# Fail if now empty (shouldn’t be, but mirrors Bash behavior)
if (-not $INCLUDED_APPS -or $INCLUDED_APPS.Count -eq 0) {
  Err "Error: No apps specified."
  Write-Host "Usage: pwsh ./install.ps1 app1 app2 ..."
  Write-Host "   or: `$env:INCLUDED_APPS=`"app1 app2`" pwsh ./install.ps1"
  Write-Host "   or: `$apps = @('app1','app2'); pwsh ./install.ps1"
  exit 2
}

# --- Normalize & validate (basename, skip empties, skip pure numbers) ---
$cleanApps = @()
foreach ($a in $INCLUDED_APPS) {
  if (-not $a) { continue }
  $tok = $a.Trim()
  if ($tok -eq "") { continue }

  if ($tok -match "[/\\]") {
    try { $tok = Split-Path -Leaf $tok } catch { }
  }
  if ($tok -eq "") { continue }

  if ($tok -match '^[0-9]+$') {
    Info "Skipping token '$tok' (pure number)."
    continue
  }

  $cleanApps += $tok
}
$INCLUDED_APPS = $cleanApps

if (-not $INCLUDED_APPS -or $INCLUDED_APPS.Count -eq 0) {
  Err "Error: No valid app names after normalization."
  exit 2
}

Info ("Apps to link: " + ($INCLUDED_APPS -join ' '))

# ------------------
# DEST_BASE must be set (no default, like Bash)
# ------------------
if (-not $env:DEST_BASE -or $env:DEST_BASE.Trim() -eq "") {
  Err "Error: DEST_BASE is not set."
  Write-Host "Set DEST_BASE to the folder where symlinks should be created."
  exit 2
}
$DEST_BASE = $env:DEST_BASE
$null = New-Item -ItemType Directory -Force -Path $DEST_BASE 2>$null

Info "Installing Apps..."
Info ("Working directory: " + (Get-Location).Path)
Info ("Destination base: " + (Resolve-Path -LiteralPath $DEST_BASE).Path)

# ------------------
# Finder: search under $HOME (depth-limited) for */src/agilab/apps, strip suffix
# ------------------
function Find-ThalesAgilab {
  param([string]$StartDir, [int]$Depth = 5)

  $hit = Get-ChildItem -LiteralPath $StartDir -Directory -Recurse -Depth $Depth -ErrorAction SilentlyContinue |
         Where-Object { $_.FullName -match '([/\\])src\1agilab\1apps$' } |
         Select-Object -First 1

  if ($hit) {
    $pattern = [IO.Path]::Combine('src','agilab','apps')
    $root = $hit.FullName -replace [regex]::Escape($pattern) + '$', ''
    return $root
  }
  return $null
}

$THALES_AGILAB_ROOT = $env:THALES_AGILAB_ROOT
if (-not $THALES_AGILAB_ROOT) {
  $THALES_AGILAB_ROOT = Find-ThalesAgilab -StartDir $HOME -Depth 5
  if (-not $THALES_AGILAB_ROOT) {
    Err "Error: Could not locate '*/src/agilab/apps' starting from $HOME."
    Info "Hint: `$env:THALES_AGILAB_ROOT = '/absolute/path/to/thales-agilab' and re-run."
    exit 1
  }
}

$TARGET_BASE = Join-Path $THALES_AGILAB_ROOT "src/agilab/apps"
if (-not (Test-Path -LiteralPath $TARGET_BASE -PathType Container)) {
  Err "Error: Missing directory: $TARGET_BASE"
  exit 1
}

Info ("Using THALES_AGILAB_ROOT: $THALES_AGILAB_ROOT")
Info ("Link target base: $TARGET_BASE")
Write-Host ""

# ------------------
# Symlink helpers (mirror Bash)
# ------------------
function Test-IsSymlink {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { return $false }
  try {
    $item = Get-Item -LiteralPath $Path -Force
    return ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
  } catch { return $false }
}

function New-Link {
  param([string]$LinkPath, [string]$TargetPath)
  $type = "SymbolicLink"
  try {
    New-Item -ItemType $type -Path $LinkPath -Target $TargetPath -Force | Out-Null
  } catch {
    if ($IsWindows -and (Test-Path -LiteralPath $TargetPath -PathType Container)) {
      New-Item -ItemType Junction -Path $LinkPath -Target $TargetPath -Force | Out-Null
    } else {
      throw
    }
  }
}

# ------------------
# Create / refresh links
# ------------------
$status = 0
foreach ($app in $INCLUDED_APPS) {
  $appTarget = Join-Path $TARGET_BASE $app
  $appDest   = Join-Path $DEST_BASE $app

  if (-not (Test-Path -LiteralPath $appTarget)) {
    Err "Target for '$app' not found: $appTarget — skipping."
    $status = 1
    continue
  }

  if (Test-IsSymlink -Path $appDest) {
    Act "App '$appDest' is a symlink. Recreating -> '$appTarget'..."
    Remove-Item -LiteralPath $appDest -Force
    New-Link -LinkPath $appDest -TargetPath $appTarget
  }
  elseif (-not (Test-Path -LiteralPath $appDest)) {
    Act "App '$appDest' does not exist. Creating symlink -> '$appTarget'..."
    New-Link -LinkPath $appDest -TargetPath $appTarget
  }
  else {
    Ok "App '$appDest' exists and is not a symlink. Leaving untouched."
  }
}

exit $status
