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

# Install core
Write-Host "Installing core..." -ForegroundColor Blue
Push-Location "core"
if ($Offline) {
    uv sync -p $env:PYTHON_VERSION --extra managers --dev --directory (Resolve-Path "$($FrameworkDir)\core")
} else {
    uv sync -p $env:PYTHON_VERSION --config-file uv_config.toml --extra managers --dev --directory (Resolve-Path "$($FrameworkDir)\core")
}
uv pip install -e .
Pop-Location

# Install gui
Write-Host "Installing gui..." -ForegroundColor Blue
Push-Location "gui"
uv sync -p $env:PYTHON_VERSION --dev --directory (Resolve-Path "$($FrameworkDir)\gui")
Pop-Location

# Write-Host "Checking installation..." -ForegroundColor Green
# uv run -p $env:PYTHON_VERSION --project "core" python run-all-test.py
# if ($LASTEXITCODE -ne 0) {
#     Write-Host "Tests failed with exit code $LASTEXITCODE" -ForegroundColor Red
#     exit $LASTEXITCODE
# }
