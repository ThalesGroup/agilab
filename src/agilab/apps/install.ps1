<#
install.ps1 — create/refresh app symlinks pointing to thales-agilab/src/agilab/apps/<app>

Usage:
  pwsh ./install.ps1 app1 app2
  $env:INCLUDED_APPS="app1 app2"; pwsh ./install.ps1
  $apps = @("app1","app2"); pwsh ./install.ps1

Optional env:
  THALES_AGILAB_ROOT = absolute path to thales-agilab
  DEST_BASE          = where links are created (default: ".")
#>

param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$AppArgs
)

$ErrorActionPreference = "Stop"

# ------------------
# Colors (Write-Host colors to mimic .sh UX)
# ------------------
function Info([string]$msg)  { Write-Host $msg -ForegroundColor Yellow }
function Ok([string]$msg)    { Write-Host $msg -ForegroundColor Green }
function Act([string]$msg)   { Write-Host $msg -ForegroundColor Cyan }   # like BLUE
function Err([string]$msg)   { Write-Host $msg -ForegroundColor Red }

Info ("CWD: " + (Get-Location).Path)

# ------------------
# Resolve app list (priority: CLI args > INCLUDED_APPS env > $apps variable)
# ------------------
$INCLUDED_APPS = @()

if ($AppArgs -and $AppArgs.Count -gt 0) {
  $INCLUDED_APPS = $AppArgs
} elseif ($env:INCLUDED_APPS) {
  $INCLUDED_APPS = @($env:INCLUDED_APPS -split '\s+')
} elseif (Get-Variable -Name apps -Scope Script,Local,Global -ErrorAction SilentlyContinue) {
  $INCLUDED_APPS = $apps
}

if (-not $INCLUDED_APPS -or $INCLUDED_APPS.Count -eq 0) {
  Err "No apps provided. Pass apps as args, set INCLUDED_APPS env, or define an `$apps array."
  Write-Host "Example:" ( 'INCLUDED_APPS="flight_project sat_trajectory_project" pwsh ./install.ps1' )
  exit 2
}

# ------------------
# Destination base (default ".")
# ------------------
$DEST_BASE = if ($env:DEST_BASE) { $env:DEST_BASE } else { "." }
$null = New-Item -ItemType Directory -Force -Path $DEST_BASE 2>$null
Info ("Destination base: " + (Resolve-Path -LiteralPath $DEST_BASE).Path)

# ------------------
# Auto-detect thales-agilab root (walk up from script dir)
# ------------------
$ScriptDir = Split-Path -LiteralPath $PSCommandPath -Parent

function Find-ThalesAgilab {
  param([string]$StartDir)

  $d = $StartDir
  while ($true) {
    $candidate = Join-Path $d "thales-agilab\src\agilab\apps"
    if (Test-Path -LiteralPath $candidate -PathType Container) {
      return (Join-Path $d "thales-agilab")
    }
    $parent = Split-Path -LiteralPath $d -Parent
    if ([string]::IsNullOrEmpty($parent) -or $parent -eq $d) { break }
    $d = $parent
  }
  return $null
}

$THALES_AGILAB_ROOT = if ($env:THALES_AGILAB_ROOT) { $env:THALES_AGILAB_ROOT } else { $null }
if (-not $THALES_AGILAB_ROOT) {
  $THALES_AGILAB_ROOT = Find-ThalesAgilab -StartDir $ScriptDir
  if (-not $THALES_AGILAB_ROOT) {
    Err "Could not locate 'thales-agilab/src/agilab/apps' by walking up from: $ScriptDir"
    Err "Tip: set THALES_AGILAB_ROOT to an absolute path and re-run."
    exit 1
  }
}

$TARGET_BASE = Join-Path $THALES_AGILAB_ROOT "src\agilab\apps"
if (-not (Test-Path -LiteralPath $TARGET_BASE -PathType Container)) {
  Err "Missing directory: $TARGET_BASE"
  exit 1
}

Info ("Using THALES_AGILAB_ROOT: $THALES_AGILAB_ROOT")
Info ("Link target base: $TARGET_BASE")
Write-Host ""

# ------------------
# Helpers
# ------------------
function Test-IsSymlink {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { return $false }
  try {
    $item = Get-Item -LiteralPath $Path -Force
    return ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
  } catch { return $false }
}

function New-Link {
  param([string]$LinkPath, [string]$TargetPath)

  # Prefer SymbolicLink; on Windows without Developer Mode/admin, fall back to Junction for dirs
  $itemType = "SymbolicLink"
  try {
    New-Item -ItemType $itemType -Path $LinkPath -Target $TargetPath -Force | Out-Null
  } catch {
    if ($IsWindows) {
      # Try junctions for directories
      if (Test-Path -LiteralPath $TargetPath -PathType Container) {
        New-Item -ItemType Junction -Path $LinkPath -Target $TargetPath -Force | Out-Null
      } else {
        throw
      }
    } else {
      throw
    }
  }
}

# ------------------
# Create / refresh links (same UX as .sh)
# ------------------
$status = 0
foreach ($app in $INCLUDED_APPS) {
  $appTarget = Join-Path $TARGET_BASE $app
  $appDest   = Join-Path $DEST_BASE $app

  if (-not (Test-Path -LiteralPath $appTarget)) {
    Err "Target for '$app' does not exist: $appTarget — skipping."
    $status = 1
    continue
  }

  if (Test-IsSymlink -Path $appDest) {
    Act "App '$appDest' is a symlink. Recreating -> '$appTarget'..."
    Remove-Item -LiteralPath $appDest -Force
    New-Link -LinkPath $appDest -TargetPath $appTarget
  }
  elseif (-not (Test-Path -LiteralPath $appDest)) {
    Act "App '$appDest' missing. Creating symlink -> '$appTarget'..."
    New-Link -LinkPath $appDest -TargetPath $appTarget
  }
  else {
    Ok "App '$appDest' exists and is not a symlink. Leaving untouched."
  }
}

exit $status
