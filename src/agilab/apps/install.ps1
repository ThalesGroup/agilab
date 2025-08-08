<#
install.ps1 — auto-detect thales-agilab and (re)create app symlinks
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
function Act([string]$msg)   { Write-Host $msg -ForegroundColor Cyan }
function Err([string]$msg)   { Write-Host $msg -ForegroundColor Red }

# ------------------
# Resolve INCLUDED_APPS (args > env > $apps var)
# ------------------
$INCLUDED_APPS = @()

if ($AppArgs -and $AppArgs.Count -gt 0) {
  $INCLUDED_APPS = $AppArgs
}
elseif ($env:INCLUDED_APPS) {
  $INCLUDED_APPS = @($env:INCLUDED_APPS -split '\s+')
}
elseif (Get-Variable -Name apps -Scope Script,Local,Global -ErrorAction SilentlyContinue) {
  $INCLUDED_APPS = $apps
}

if (-not $INCLUDED_APPS -or $INCLUDED_APPS.Count -eq 0) {
  Err "No apps provided."
  Write-Host "Usage: pwsh ./install.ps1 app1 app2 ..."
  Write-Host "   or: `$env:INCLUDED_APPS=`"app1 app2`" pwsh ./install.ps1"
  Write-Host "   or: `$apps = @('app1','app2'); pwsh ./install.ps1"
  exit 2
}

# --- Validate app names ---
$cleanApps = @()
foreach ($a in $INCLUDED_APPS) {
  if (-not $a -or $a.Trim() -eq "") { continue }
  if ($a -match "[/\\]") {
    Err "Invalid app name '$a' (looks like a path)."
    Write-Host "Please pass folder names only (e.g., 'flight_project'), not full paths."
    exit 2
  }
  $cleanApps += $a
}
$INCLUDED_APPS = $cleanApps
if ($INCLUDED_APPS.Count -eq 0) {
  Err "No valid app names after validation."
  exit 2
}

# ------------------
# Destination base
# ------------------
$DEST_BASE = if ($env:DEST_BASE) { $env:DEST_BASE } else { "." }
$null = New-Item -ItemType Directory -Force -Path $DEST_BASE 2>$null

Info ("Working directory: " + (Get-Location).Path)
Info ("Destination base: " + (Resolve-Path -LiteralPath $DEST_BASE).Path)

# ------------------
# Finder: search under $HOME for */src/agilab/apps (depth-limited)
# Strip suffix to get repo root
# ------------------
function Find-ThalesAgilab {
  param([string]$StartDir, [int]$Depth = 5)

  $hit = Get-ChildItem -LiteralPath $StartDir -Directory -Recurse -Depth $Depth -ErrorAction SilentlyContinue |
         Where-Object { $_.FullName -like "*\src\agilab\apps" -or $_.FullName -like "*/src/agilab/apps" } |
         Select-Object -First 1

  if ($hit) {
    # Strip the trailing /src/agilab/apps
    $pattern = [IO.Path]::Combine('src','agilab','apps')
    $root = $hit.FullName -replace [regex]::Escape($pattern) + '$', ''
    return $root
  }
  return $null
}

$THALES_AGILAB_ROOT = if ($env:THALES_AGILAB_ROOT) { $env:THALES_AGILAB_ROOT } else { $null }
if (-not $THALES_AGILAB_ROOT) {
  $THALES_AGILAB_ROOT = Find-ThalesAgilab -StartDir $HOME -Depth 5
  if (-not $THALES_AGILAB_ROOT) {
    Err "Could not locate '*\src\agilab\apps' starting from: $HOME"
    Err "Hint: `$env:THALES_AGILAB_ROOT = 'C:\path\to\thales-agilab' (or /Users/jpm/PycharmProjects/thales-agilab) and re-run."
    exit 1
  }
}

$TARGET_BASE = Join-Path $THALES_AGILAB_ROOT "src/agilab/apps"
if (-not (Test-Path -LiteralPath $TARGET_BASE -PathType Container)) {
  Err "Missing directory: $TARGET_BASE"
  exit 1
}

Info ("Using THALES_AGILAB_ROOT: $THALES_AGILAB_ROOT")
Info ("Link target base: $TARGET_BASE")
Write-Host ""

# ------------------
# Symlink helpers
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
