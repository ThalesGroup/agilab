# Script: install_Agi_framework.ps1
# Purpose: Install the framework
param(
    [Parameter(Mandatory = $true)]
    [string]$FrameworkDir,
    [Parameter(Mandatory = $false)]
    [switch]$Offline
)

# Exit immediately if a command fails
$ErrorActionPreference = "Stop"


Write-Host "Installing framework from $(Get-Location)..." -ForegroundColor Blue

# Install env
Write-Host "Installing env..." -ForegroundColor Blue
Push-Location "env"
uv sync -p $env:PYTHON_VERSION --dev --directory (Resolve-Path "$($FrameworkDir)\env")
uv pip install -e .
Pop-Location

# Install cluster
Write-Host "Installing cluster..." -ForegroundColor Blue
Push-Location "cluster"

Push-Location "cluster"
if ($Offline) {
    uv sync -p $env:PYTHON_VERSION --extra managers --dev --directory (Resolve-Path "$($FrameworkDir)\cluster")
} else {
    uv sync -p $env:PYTHON_VERSION --config-file uv_config.toml --extra managers --dev --directory (Resolve-Path "$($FrameworkDir)\cluster")
}
uv pip install -e .
Pop-Location

Write-Host "Installing node..." -ForegroundColor Blue
Push-Location "node"
if ($Offline) {
    uv sync -p $env:PYTHON_VERSION --extra managers --dev --directory (Resolve-Path "$($FrameworkDir)\node")
} else {
    uv sync -p $env:PYTHON_VERSION --config-file uv_config.toml --extra managers --dev --directory (Resolve-Path "$($FrameworkDir)\node")
}
uv pip install -e .
Pop-Location

Pop-Location

# Install gui
Write-Host "Installing gui..." -ForegroundColor Blue
Push-Location "gui"
uv sync -p $env:PYTHON_VERSION --dev --directory (Resolve-Path "$($FrameworkDir)\gui")
Pop-Location


