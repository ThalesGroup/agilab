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

# Install agi-env
Write-Host "Installing agi-env..." -ForegroundColor Blue
Push-Location "agi-env"
uv sync -p $env:PYTHON_VERSION --dev --directory (Resolve-Path "$($FrameworkDir)\agi-env")
uv pip install -e .
Pop-Location

# Install agi-cluster
Write-Host "Installing agi-cluster..." -ForegroundColor Blue
Push-Location "core"

Push-Location "agi-cluster"
if ($Offline) {
    uv sync -p $env:PYTHON_VERSION --extra managers --dev --directory (Resolve-Path "$($FrameworkDir)\agi-cluster")
} else {
    uv sync -p $env:PYTHON_VERSION --config-file uv_config.toml --extra managers --dev --directory (Resolve-Path "$($FrameworkDir)\agi-cluster")
}
uv pip install -e .
Pop-Location

Write-Host "Installing agi-node..." -ForegroundColor Blue
Push-Location "agi-node"
if ($Offline) {
    uv sync -p $env:PYTHON_VERSION --extra managers --dev --directory (Resolve-Path "$($FrameworkDir)\agi-node")
} else {
    uv sync -p $env:PYTHON_VERSION --config-file uv_config.toml --extra managers --dev --directory (Resolve-Path "$($FrameworkDir)\agi-node")
}
uv pip install -e .
Pop-Location

Pop-Location

# Install agilab
Write-Host "Installing agilab..." -ForegroundColor Blue

uv sync -p $env:PYTHON_VERSION --dev --directory (Resolve-Path "$FrameworkDir")



