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
$BLUE   = "`e[1;34m"
$GREEN  = "`e[1;32m"
$YELLOW = "`e[1;33m"
$RED    = "`e[1;31m"
$NC     = "`e[0m"

Write-Host "${YELLOW}Installing Apps...${NC}"

# Resolve INCLUDED_APPS: Args > Env > default list
if ($args.Count -gt 0) {
    $INCLUDED_APPS = $args
} elseif ($env:INCLUDED_APPS) {
    $INCLUDED_APPS = $env:INCLUDED_APPS -split "\s+"
} elseif ($apps) {
    $INCLUDED_APPS = $apps
} else {
    $INCLUDED_APPS = @(
        "mycode_project",
        "flight_project",
        "sat_trajectory_project",
        "flight_trajectory_project",
        "link_sim_project",
        "flight_legacy_project"
    )
}

if (-not $INCLUDED_APPS -or $INCLUDED_APPS.Count -eq 0) {
    Write-Host "${RED}Error:${NC} No apps specified."
    exit 2
}

# Destination base check
if (-not $env:DEST_BASE) {
    Write-Host "${RED}Error:${NC} DEST_BASE is not set."
    exit 2
}
$DEST_BASE = $env:DEST_BASE
if (-not (Test-Path -LiteralPath $DEST_BASE -PathType Container)) {
    New-Item -ItemType Directory -Path $DEST_BASE | Out-Null
}

Write-Host "${YELLOW}Working directory:${NC} $(Get-Location)"
Write-Host "${YELLOW}Destination base:${NC} $((Resolve-Path $DEST_BASE).Path)"

# Normalize & validate: only keep *_project
$CleanApps = @()
foreach ($a in $INCLUDED_APPS) {
    if ([string]::IsNullOrWhiteSpace($a)) { continue }

    # Normalize path to basename
    $a = $a -replace "\\", "/"
    $a = Split-Path $a -Leaf
    if ([string]::IsNullOrWhiteSpace($a)) { continue }

    # Only keep if ends with _project
    if ($a -notmatch "_project$") {
        Write-Host "${YELLOW}Skipping token '$a' (no '_project' suffix).${NC}"
        continue
    }

    $CleanApps += $a
}

$INCLUDED_APPS = $CleanApps
if ($INCLUDED_APPS.Count -eq 0) {
    Write-Host "${RED}Error:${NC} No valid app names after filtering."
    exit 2
}

Write-Host "${YELLOW}Apps to link:${NC} $($INCLUDED_APPS -join ' ')"

# Finder: search under $HOME for */src/agilab/apps
function Find-ThalesAgilab {
    param([string]$StartDir, [int]$Depth = 5)
    try {
        $hit = Get-ChildItem -LiteralPath $StartDir -Directory -Recurse -Depth $Depth -ErrorAction SilentlyContinue |
               Where-Object { $_.FullName -match "[/\\]src[/\\]agilab[/\\]apps$" } |
               Select-Object -First 1
        if ($hit) {
            return (Split-Path (Split-Path $hit.FullName -Parent) -Parent)
        }
    } catch { }
    return $null
}

if (-not $env:THALES_AGILAB_ROOT) {
    $THALES_AGILAB_ROOT = Find-ThalesAgilab -StartDir $HOME -Depth 5
    if (-not $THALES_AGILAB_ROOT) {
        Write-Host "${RED}Error:${NC} Could not locate '*/src/agilab/apps' from $HOME."
        exit 1
    }
} else {
    $THALES_AGILAB_ROOT = $env:THALES_AGILAB_ROOT
}

$TARGET_BASE = Join-Path $THALES_AGILAB_ROOT "src/agilab/apps"
if (-not (Test-Path -LiteralPath $TARGET_BASE -PathType Container)) {
    Write-Host "${RED}Error:${NC} Missing directory: $TARGET_BASE"
    exit 1
}

Write-Host "${YELLOW}Using THALES_AGILAB_ROOT:${NC} $THALES_AGILAB_ROOT"
Write-Host "${YELLOW}Link target base:${NC} $TARGET_BASE"
Write-Host ""

# Create / refresh symlinks
foreach ($app in $INCLUDED_APPS) {
    $appTarget = Join-Path $TARGET_BASE $app
    $appDest   = Join-Path $DEST_BASE $app

    if (-not (Test-Path -LiteralPath $appTarget)) {
        Write-Host "${RED}Target for '$app' not found:${NC} $appTarget — skipping."
        continue
    }

    if ((Test-Path -LiteralPath $appDest) -and (Get-Item $appDest).LinkType) {
        Write-Host "${BLUE}App '$appDest' is a symlink. Recreating -> '$appTarget'...${NC}"
        Remove-Item $appDest -Force
        New-Item -ItemType SymbolicLink -Path $appDest -Target $appTarget | Out-Null
    } elseif (-not (Test-Path -LiteralPath $appDest)) {
        Write-Host "${BLUE}App '$appDest' does not exist. Creating symlink -> '$appTarget'...${NC}"
        New-Item -ItemType SymbolicLink -Path $appDest -Target $appTarget | Out-Null
    } else {
        Write-Host "${GREEN}App '$appDest' exists and is not a symlink. Leaving untouched.${NC}"
    }
}
