# install_agilab_apps.ps1 — auto-detect thales-agilab and (re)create app symlinks

# Default apps list (only *_project)
$INCLUDED_APPS = @(
    "flight_trajectory_project",
    "sat_trajectory_project",
    "link_sim_project"
    # "flight_legacy_project"
)

# Colors (ANSI)
$BLUE   = "`e[1;34m"
$GREEN  = "`e[1;32m"
$YELLOW = "`e[1;33m"
$RED    = "`e[1;31m"
$NC     = "`e[0m"

# DEST_BASE default (overridable by env)
if (-not $env:DEST_BASE -or [string]::IsNullOrWhiteSpace($env:DEST_BASE)) {
    $DEST_BASE = (Get-Location).Path
} else {
    $DEST_BASE = $env:DEST_BASE
}
if (-not (Test-Path -LiteralPath $DEST_BASE -PathType Container)) {
    New-Item -ItemType Directory -Path $DEST_BASE | Out-Null
}

Write-Host "create symlink for apps: $($INCLUDED_APPS -join ' ')"

if ($INCLUDED_APPS.Count -eq 0) {
    Write-Host "${RED}Error:${NC} No apps specified."
    exit 2
}

Write-Host "${YELLOW}Installing Apps...${NC}"
Write-Host "${YELLOW}Working directory:${NC} $(Get-Location)"
Write-Host "${YELLOW}Destination base:${NC} $((Resolve-Path $DEST_BASE).Path)"

# Normalize & filter
$destBaseName = Split-Path $DEST_BASE -Leaf
$Clean = @()

foreach ($a in $INCLUDED_APPS) {
    if ([string]::IsNullOrWhiteSpace($a)) { continue }
    $a = Split-Path $a -Leaf

    if ($a -match '^[0-9]+$') {
        Write-Host "${YELLOW}Skipping token '$a' (no '_project' suffix).${NC}"
        continue
    }
    if ($a -eq $destBaseName) {
        Write-Host "${YELLOW}Skipping token '$a' (no '_project' suffix).${NC}"
        continue
    }
    if ($a -notmatch '_project$') {
        Write-Host "${YELLOW}Skipping token '$a' (no '_project' suffix).${NC}"
        continue
    }

    $Clean += $a
}

$INCLUDED_APPS = $Clean
if ($INCLUDED_APPS.Count -eq 0) {
    Write-Host "${RED}Error:${NC} No valid app names after filtering."
    exit 2
}

Write-Host "${YELLOW}Apps to link:${NC} $($INCLUDED_APPS -join ' ')"

# Find THALES_AGILAB_ROOT
function Find-ThalesAgilab {
    param([string]$StartDir, [int]$Depth = 5)
    $hit = Get-ChildItem -LiteralPath $StartDir -Directory -Recurse -Depth $Depth -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -like "*/src/agilab/apps" -or $_.FullName -like "*\src\agilab\apps" } |
        Select-Object -First 1
    if ($hit) {
        return (Split-Path (Split-Path $hit.FullName -Parent) -Parent)
    }
    return $null
}

if (-not $env:THALES_AGILAB_ROOT -or [string]::IsNullOrWhiteSpace($env:THALES_AGILAB_ROOT)) {
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

# Create/refresh symlinks
$status = 0
foreach ($app in $INCLUDED_APPS) {
    $appTarget = Join-Path $TARGET_BASE $app
    $appDest   = Join-Path $DEST_BASE $app

    if (-not (Test-Path -LiteralPath $appTarget)) {
        Write-Host "${RED}Target for '$app' not found:${NC} $appTarget — skipping."
        $status = 1
        continue
    }

    if (Test-Path -LiteralPath $appDest -PathType Leaf -or Test-Path -LiteralPath $appDest -PathType Container) {
        if ((Get-Item $appDest).LinkType) {
            Write-Host "${BLUE}App '$appDest' is a symlink. Recreating -> '$appTarget'...${NC}"
            Remove-Item -LiteralPath $appDest -Force
            New-Item -ItemType SymbolicLink -Path $appDest -Target $appTarget | Out-Null
        } else {
            Write-Host "${GREEN}App '$appDest' exists and is not a symlink. Leaving untouched.${NC}"
        }
    } else {
        Write-Host "${BLUE}App '$appDest' does not exist. Creating symlink -> '$appTarget'...${NC}"
        New-Item -ItemType SymbolicLink -Path $appDest -Target $appTarget | Out-Null
    }
}

exit $status
