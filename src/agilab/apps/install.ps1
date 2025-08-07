# install_apps.ps1
# Purpose: Install the apps (PowerShell version)

$ErrorActionPreference = "Stop"

# Load environment variables from .env (simulate 'source')
$envFile = "$HOME\.local\share\agilab\.env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$') {
            $name, $val = $matches[1], $matches[2].Trim("'""")
            [System.Environment]::SetEnvironmentVariable($name, $val)
        }
    }
}
$AGI_PYTHON_VERSION = $env:AGI_PYTHON_VERSION
if ($AGI_PYTHON_VERSION -match '^(\d+\.\d+\.\d+(\+freethreaded)?)') {
    $AGI_PYTHON_VERSION = $matches[1]
    $env:AGI_PYTHON_VERSION = $AGI_PYTHON_VERSION
}

# App install command
$APP_INSTALL = "uv -q run -p $AGI_PYTHON_VERSION --project ../core/cluster python install.py"

# List of included apps
$INCLUDED_APPS = @(
    "mycode_project",
    "flight_project",
    "sat_trajectory_project",
    "flight_trajectory_project",
    "link_sim_project"
    # "flight_legacy_project" # Commented out in original
)

function Write-Blue($msg)  { Write-Host $msg -ForegroundColor Blue }
function Write-Green($msg) { Write-Host $msg -ForegroundColor Green }
function Write-Red($msg)   { Write-Host $msg -ForegroundColor Red }

Write-Blue "Retrieving all apps..."
Write-Host (Get-Location)

# Ensure all INCLUDED_APPS exist, create symlinks if missing (simulated for Windows)
foreach ($app in $INCLUDED_APPS) {
    $app_path = Join-Path -Path "." -ChildPath $app
    $target_path = "..\..\..\..\thales-agilab\src\agilab\apps\$app"
    if (-not (Test-Path $app_path -PathType Container)) {
        Write-Blue "App '$app_path' does not exist. Creating symlink to '$target_path'..."
        # Symlink or junction on Windows (use mklink /J or New-Item)
        try {
            New-Item -ItemType Junction -Path $app_path -Target $target_path | Out-Null
        } catch {
            Write-Red "Failed to create symlink for $app_path"
        }
    }
}

# Find apps (subdirs) to install
$apps = @()
$parentDir = $args[0]
if (-not $parentDir) { $parentDir = "." }
foreach ($dir in Get-ChildItem -Path $parentDir -Directory) {
    $dir_name = $dir.Name
    if ($INCLUDED_APPS -contains $dir_name -and $dir_name -like "*_project") {
        $apps += $dir_name
    }
}

Write-Blue "Apps to install: $($apps -join ", ")"

Push-Location ../apps
foreach ($app in $apps) {
    Write-Blue "Installing $app..."
    $cmd = "$APP_INSTALL $app --apps-dir $(Get-Location) --install-type $($args[1])"
    $ok = $false
    try {
        Invoke-Expression $cmd
        $ok = $true
    } catch {
        Write-Red "✗ '$app' installation failed."
        Exit 1
    }
    if ($ok) {
        Write-Green "✓ '$app' successfully installed."
        Write-Green "Checking installation..."
        Push-Location $app
        if (Test-Path "run-all-test.py") {
            Invoke-Expression "uv run -p $AGI_PYTHON_VERSION python run-all-test.py"
        } else {
            Write-Blue "No run-all-test.py in $app, skipping tests."
        }
        Pop-Location
    }
}
Pop-Location

Write-Green "Installation of apps complete!"

# Patch PyCharm interpreter settings in workspace.xml
Write-Blue "Patching PyCharm workspace.xml interpreter settings..."
Invoke-Expression "uv run python patch_workspace.py"
