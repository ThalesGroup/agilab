# Script: install_Agi_framework.ps1
# Purpose: Install the framework

# Exit immediately if a command fails
$ErrorActionPreference = "Stop"


Write-Host "Installing framework from $(Get-Location)..." -ForegroundColor Blue

# Install env
Write-Host "Installing env..." -ForegroundColor Blue
Push-Location "env"
uv sync -p $env:PYTHON_VERSION --dev --directory (Resolve-Path "$($args[0])\env")
uv pip install -e .
Pop-Location

# Install core
Write-Host "Installing core..." -ForegroundColor Blue
Push-Location "core"
uv sync -p $env:PYTHON_VERSION --extra managers --group rapids --dev --directory (Resolve-Path "$($args[0])\core")
uv pip install -e .
Pop-Location

# Install gui
Write-Host "Installing gui..." -ForegroundColor Blue
Push-Location "gui"
uv sync -p $env:PYTHON_VERSION --dev --directory (Resolve-Path "$($args[0])\gui")
Pop-Location

Write-Host "Checking installation..." -ForegroundColor Green
uv run -p $env:PYTHON_VERSION --project "core\managers" python run-all-test.py
