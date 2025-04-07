# PowerShell script: install_spyd_apps.ps1
# Purpose: Install the spyd-apps
param(
    [Parameter(Mandatory = $true)]
    [string]$AppsDir,

    [Parameter(Mandatory = $true)]
    [string]$InstallType
)


$ErrorActionPreference = "Stop"

# List only the apps that you want to install
$INCLUDED_APPS = @(
    "my-code-project",
    "flight-project"
)

function Main {
    Write-Output "Retrieving all apps..."
    Write-Output "$AppsDir"

    foreach ($app in $INCLUDED_APPS) {
        Write-Output "Installing $app..."

        uv run -p $env:PYTHON_VERSION --project ../fwk/core/managers python install.py $app --apps-dir $AppsDir --install-type $InstallType
        if ($LASTEXITCODE  -eq 0) {
            Write-Output "'$app' successfully installed."
        } else {
            Write-Output "'$app' installation failed."
            exit 1
        }
    }

    Write-Host "Installation of spyd-apps complete!"
}

Main