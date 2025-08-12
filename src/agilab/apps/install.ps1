#!/usr/bin/env pwsh
# install_agilab_apps.ps1 — auto-detect thales-agilab and (re)create app links on Windows
# Requires PowerShell 7+ for best results (but works on 5.1 too)

$ErrorActionPreference = 'Stop'

# --- Colors helpers
function Info($msg){ Write-Host $msg -ForegroundColor Yellow }
function Ok($msg){ Write-Host $msg -ForegroundColor Green }
function Warn($msg){ Write-Host $msg -ForegroundColor DarkYellow }
function Err($msg){ Write-Host $msg -ForegroundColor Red }

# --- Default app list (only *_project)
$IncludedApps = @(
  'flight_trajectory_project',
  'sat_trajectory_project',
  'link_sim_project'
  # 'flight_legacy_project'
)

# --- DEST_BASE default (overridable by env)
$DestBase = if ($env:DEST_BASE) { $env:DEST_BASE } else { (Get-Location).Path }
New-Item -ItemType Directory -Force -Path $DestBase | Out-Null

Write-Host "create symlink for apps: $($IncludedApps -join ' ')"

if (-not $IncludedApps -or $IncludedApps.Count -eq 0) {
  Err "Error: No apps specified."; exit 2
}

Info "Installing Apps..."
Info ("Working directory: {0}" -f (Get-Location))
Info ("Destination base: {0}" -f (Resolve-Path $DestBase))

# --- Normalize & filter: only keep *_project; skip numbers & token equal to dest basename
$destBaseName = Split-Path -Leaf $DestBase
$clean = @()
foreach ($a in $IncludedApps) {
  if ([string]::IsNullOrWhiteSpace($a)) { continue }
  $a = $a -replace '\\','/'      # normalize slashes
  $a = ($a -split '/')[ -1 ]     # keep last segment
  if ([string]::IsNullOrWhiteSpace($a)) { continue }

  if ($a -match '^[0-9]+$') {
    Warn "Skipping token '$a' (no '_project' suffix)."
    continue
  }
  if ($a -eq $destBaseName) {
    Warn "Skipping token '$a' (no '_project' suffix)."
    continue
  }
  if ($a -notmatch '_project$') {
    Warn "Skipping token '$a' (no '_project' suffix)."
    continue
  }
  $clean += $a
}

$IncludedApps = @($clean)
if ($IncludedApps.Count -eq 0) {
  Err "Error: No valid app names after filtering."; exit 2
}

Info ("Apps to link: {0}" -f ($IncludedApps -join ' '))

# --- Finder under $HOME; strip \src\agilab\apps (skip Windows-problematic folders)
function Find-ThalesAgilab {
  param([int]$MaxDepth = 5)

  $home = [Environment]::GetFolderPath('UserProfile')
  # Paths to skip to avoid access prompts/slowness (Windows-specific)
  $skip = @(
    (Join-Path $home 'AppData'),
    (Join-Path $home 'OneDrive'),
    #(Join-Path $home 'Documents'),
    (Join-Path $home 'Desktop'),
    (Join-Path $home 'Pictures'),
    (Join-Path $home 'Music'),
    (Join-Path $home 'Videos'),
    (Join-Path $home 'Saved Games'),
    (Join-Path $home 'Contacts'),
    (Join-Path $home 'Searches'),
    (Join-Path $home 'Links'),
    (Join-Path $home 'Favorites'),
    (Join-Path $home 'NTUSER.DIR') # rare, defensive
  ) | ForEach-Object { $_.ToLowerInvariant() }

  # BFS with depth control; do not descend into reparse points or skipped paths
  $q = New-Object System.Collections.Generic.Queue[psobject]
  $q.Enqueue([pscustomobject]@{Dir = Get-Item -LiteralPath $home; Depth = 0})

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

# Honor THALES_AGILAB_ROOT env if provided, else discover
$THALES_AGILAB_ROOT = $env:THALES_AGILAB_ROOT
if ([string]::IsNullOrWhiteSpace($THALES_AGILAB_ROOT)) {
  $THALES_AGILAB_ROOT = Find-ThalesAgilab -MaxDepth 5
  if (-not $THALES_AGILAB_ROOT) {
    Err "Error: Could not locate '*\src\agilab\apps' under HOME."; exit 1
  }
}

$TARGET_BASE = Join-Path $THALES_AGILAB_ROOT 'src\agilab\apps'
if (-not (Test-Path -LiteralPath $TARGET_BASE -PathType Container)) {
  Err "Error: Missing directory: $TARGET_BASE"; exit 1
}

Info ("Using THALES_AGILAB_ROOT: {0}" -f $THALES_AGILAB_ROOT)
Info ("Link target base: {0}" -f $TARGET_BASE)
Write-Host ""

# --- Create / refresh links
$status = 0

function New-Link {
  param([string]$Path, [string]$Target)

  # Try symbolic link first (works if Dev Mode enabled or elevated)
  try {
    New-Item -ItemType SymbolicLink -Path $Path -Target $Target -Force -ErrorAction Stop | Out-Null
    return "symlink"
  } catch {
    # Fallback to junction for directories
    try {
      New-Item -ItemType Junction -Path $Path -Target $Target -Force -ErrorAction Stop | Out-Null
      return "junction"
    } catch {
      throw
    }
  }
}

foreach ($app in $IncludedApps) {
  $appTarget = Join-Path $TARGET_BASE $app
  $appDest   = Join-Path $DestBase $app

  if (-not (Test-Path -LiteralPath $appTarget)) {
    Err ("Target for '{0}' not found: {1} — skipping." -f $app, $appTarget)
    $status = 1
    continue
  }

  $destExists = Test-Path -LiteralPath $appDest
  $isReparse  = $false
  if ($destExists) {
    try {
      $itm = Get-Item -LiteralPath $appDest -Force -ErrorAction Stop
      $isReparse = [bool]($itm.Attributes -band [IO.FileAttributes]::ReparsePoint)
    } catch {
      $isReparse = $false
    }
  }

  if ($isReparse) {
    Info ("App '{0}' is a link. Recreating -> '{1}'..." -f $appDest, $appTarget)
    Remove-Item -LiteralPath $appDest -Force
    try {
      $kind = New-Link -Path $appDest -Target $appTarget
      Ok ("Recreated $kind: {0} -> {1}" -f $appDest, $appTarget)
    } catch {
      Err ("Failed to recreate link for {0}: {1}" -f $app, $_.Exception.Message)
      $status = 1
    }
  } elseif (-not $destExists) {
    Info ("App '{0}' does not exist. Creating link -> '{1}'..." -f $appDest, $appTarget)
    try {
      $kind = New-Link -Path $appDest -Target $appTarget
      Ok ("Created $kind: {0} -> {1}" -f $appDest, $appTarget)
    } catch {
      Err ("Failed to create link for {0}: {1}" -f $app, $_.Exception.Message)
      $status = 1
    }
  } else {
    Ok ("App '{0}' exists and is not a link. Leaving untouched." -f $appDest)
  }
}

exit $status
