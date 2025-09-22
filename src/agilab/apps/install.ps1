#requires -Version 5.1
<#
.SYNOPSIS
    install_Agi_apps.ps1
.DESCRIPTION
    Installe les apps (apps-only ; aucun argument positionnel requis).
#>

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$PSNativeCommandUseErrorActionPreference = $true

function Write-Info    ($msg) { Write-Host $msg -ForegroundColor Blue }
function Write-Ok      ($msg) { Write-Host $msg -ForegroundColor Green }
function Write-WarnMsg ($msg) { Write-Host $msg -ForegroundColor Yellow }
function Write-ErrMsg  ($msg) { Write-Host $msg -ForegroundColor Red }

# --- Charger .env -------------------------------------------------------------
$configFolder = Join-Path $env:LOCALAPPDATA "agilab"
$envFile   = Join-Path $configFolder ".env"
if (Test-Path -LiteralPath $envFile) {
    Get-Content -LiteralPath $envFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#')) { return }
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
            $k = $Matches[1]
            $v = $Matches[2].Trim()
            if ($v -match '^(?:"(.*)"|''(.*)'')$') {
                $v = $Matches[1]; if (-not $v) { $v = $Matches[2] }
            }
            Set-Item -Path Env:$k -Value $v
        }
    }
}

# Normaliser AGI_PYTHON_VERSION -> X.Y.Z ou X.Y.Z+freethreaded
$agiPyRaw = $env:AGI_PYTHON_VERSION
if ($agiPyRaw) {
    $m = [regex]::Match($agiPyRaw, '^([0-9]+\.[0-9]+\.[0-9]+(?:\+freethreaded)?)')
    if ($m.Success) { $env:AGI_PYTHON_VERSION = $m.Groups[1].Value }
}

# --- Chemins publics/privés ---------------------------------------------------
$agilabPublicPathFile = Join-Path $configFolder  ".agilab-path"
if (-not (Test-Path -LiteralPath $agilabPublicPathFile)) {
    Write-ErrMsg "Error: Missing file: $agilabPublicPathFile"
    exit 1
}
$AGILAB_PUBLIC  = (Get-Content -LiteralPath $agilabPublicPathFile -Raw).Trim()
$AGILAB_PRIVATE = $env:AGILAB_PRIVATE

# Déterminer TARGET_BASE
$TARGET_BASE = ""
if ($AGILAB_PRIVATE) {
    $TARGET_BASE = Join-Path "$AGILAB_PRIVATE" "src/agilab/apps"
    if (-not (Test-Path -LiteralPath $TARGET_BASE)) {
        Write-ErrMsg "Error: Missing directory: $TARGET_BASE"
        exit 1
    }
}

$INSTALL_TYPE = if ($env:INSTALL_TYPE) { $env:INSTALL_TYPE } else { "1" }

# Export PYTHONPATH (prepend cwd)
$pwdPath = (Get-Location).Path
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$pwdPath$([IO.Path]::PathSeparator)$($env:PYTHONPATH)"
} else {
    $env:PYTHONPATH = $pwdPath
}

# --- Destination (base) -------------------------------------------------------
$DEST_BASE = if ($env:DEST_BASE) { $env:DEST_BASE } else { (Get-Location).Path }
New-Item -ItemType Directory -Path $DEST_BASE -Force | Out-Null
Write-WarnMsg ("Destination base: {0}" -f (Resolve-Path -LiteralPath $DEST_BASE))
Write-WarnMsg ("Using AGILAB_PRIVATE: {0}" -f ($(if ($AGILAB_PRIVATE) { $AGILAB_PRIVATE } else { "" })))
Write-WarnMsg ("Link target base: {0}`n" -f $TARGET_BASE)

# --- Liste d'apps privées -----------------------------------------------------
$PRIVATE_APPS = @(
    'flight_trajectory_project',
    'sat_trajectory_project',
    'link_sim_project',
    'sb3_trainer_project'
)

# --- Apps publiques locales (*_project) --------------------------------------
$PUBLIC_APPS = @()
if (Test-Path -LiteralPath $DEST_BASE) {
    $PUBLIC_APPS = Get-ChildItem -LiteralPath $DEST_BASE -Directory -Filter '*_project' |
                   Select-Object -ExpandProperty Name
}

# Merge privé + public
if ([string]::IsNullOrEmpty($AGILAB_PRIVATE)) {
    $INCLUDED_APPS = @($PUBLIC_APPS)
} else {
    $INCLUDED_APPS = @($PRIVATE_APPS + $PUBLIC_APPS)
}
if ($INCLUDED_APPS.Count -eq 0) { $INCLUDED_APPS = @() }

Write-Info ("Apps to install: {0}`n" -f ($(if ($INCLUDED_APPS.Count) { $INCLUDED_APPS -join ' ' } else { '<none>' })))

# --- Helpers liens ------------------------------------------------------------
function Test-IsSymlink([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    try {
        $item = Get-Item -LiteralPath $Path -Force
        return [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
    } catch { return $false }
}

function New-DirLink([string]$Path, [string]$Target) {
    try {
        New-Item -ItemType SymbolicLink -Path $Path -Target $Target -Force | Out-Null
    } catch {
        if ($IsWindows) {
            New-Item -ItemType Junction -Path $Path -Target $Target -Force | Out-Null
        } else {
            throw
        }
    }
}

# --- Lien "core" côté privé ---------------------------------------------------
$status = 0
if (-not [string]::IsNullOrEmpty($AGILAB_PRIVATE)) {
    Push-Location (Join-Path $AGILAB_PRIVATE "src/agilab")
    try {
        $corePath = Join-Path (Get-Location).Path "core"
        if (Test-Path -LiteralPath $corePath) {
            Remove-Item -LiteralPath $corePath -Recurse -Force -ErrorAction SilentlyContinue
        }

        $candidate1 = Join-Path $AGILAB_PUBLIC "core"
        $candidate2 = Join-Path $AGILAB_PUBLIC "src/agilab/core"
        if     (Test-Path -LiteralPath $candidate1) { $target = $candidate1 }
        elseif (Test-Path -LiteralPath $candidate2) { $target = $candidate2 }
        else {
            Write-ErrMsg ("ERROR: can't find 'core' under `\$AGILAB_PUBLIC ({0}).`nTried: \$AGILAB_PUBLIC/core and \$AGILAB_PUBLIC/src/agilab/core" -f $AGILAB_PUBLIC)
            exit 1
        }

        New-DirLink -Path $corePath -Target $target

        $py = "import pathlib; p=pathlib.Path('core').resolve(); print('Private core -> {}'.format(p))"
        & uv run -p $env:AGI_PYTHON_VERSION python -c $py | ForEach-Object { Write-Host $_ }
    } finally {
        Pop-Location
    }

    # --- Liens d'apps privées dans DEST_BASE -------------------------------------

    foreach ($app in $PRIVATE_APPS) {
        $app_target = Join-Path $TARGET_BASE $app
        $app_dest   = Join-Path $DEST_BASE   $app

        if (-not (Test-Path -LiteralPath $app_target)) {
            Write-ErrMsg ("Target for '{0}' not found: {1} - skipping." -f $app, $app_target)
            $status = 1
            continue
        }

        if (Test-IsSymlink $app_dest) {
            Write-Info ("App '{0}' is a symlink. Recreating -> '{1}'..." -f $app_dest, $app_target)
            Remove-Item -LiteralPath $app_dest -Force
            New-DirLink -Path $app_dest -Target $app_target
        } elseif (-not (Test-Path -LiteralPath $app_dest)) {
            Write-Info ("App '{0}' does not exist. Creating symlink -> '{1}'..." -f $app_dest, $app_target)
            New-DirLink -Path $app_dest -Target $app_target
        } else {
            Write-Ok ("App '{0}' exists and is not a symlink. Leaving untouched." -f $app_dest)
        }
    }

}

# --- Installer chaque app -----------------------------------------------------
Push-Location (Join-Path $AGILAB_PUBLIC "apps")
try {
    foreach ($app in $INCLUDED_APPS) {
        Write-Info ("Installing {0}..." -f $app)

        $installArgs = @(
            '-q','run','-p', $env:AGI_PYTHON_VERSION,
            '--project','../core/cluster',
            'python','install.py', (Join-Path $AGILAB_PUBLIC ("apps/{0}" -f $app)),
            '--install-type', "$INSTALL_TYPE"
        )
        & uv @installArgs | ForEach-Object { $_ } | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Ok ("OK '{0}' successfully installed." -f $app)
            Write-Ok ("Checking installation...")

            Push-Location $app
            try {
                if (Test-Path -LiteralPath 'app_test.py') {
                    & uv run -p $env:AGI_PYTHON_VERSION python 'app_test.py'
                } else {
                    Write-Info ("No app_test.py in {0}, skipping tests." -f $app)
                }
            } finally {
                Pop-Location
            }
        } else {
            Write-ErrMsg ("X '{0}' installation failed." -f $app)
            $status = 1
        }
    }
} finally {
    Pop-Location
}

# --- Message final ------------------------------------------------------------
if ($status -eq 0) {
    Write-Ok "Installation of apps complete!"
} else {
    Write-WarnMsg ("Installation finished with some errors (status={0})." -f $status)
}

exit $status
