# install.ps1
# Purpose: Root/Main AGI Framework Installer (PowerShell version)

$ErrorActionPreference = "Stop"

# Logging setup
$LOG_DIR = "$HOME\log\install_logs"
$LOG_FILE = "$LOG_DIR\install_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
if (-not (Test-Path $LOG_DIR)) { New-Item -Path $LOG_DIR -ItemType Directory | Out-Null }
Start-Transcript -Path $LOG_FILE

function Write-Blue($msg)  { Write-Host $msg -ForegroundColor Blue }
function Write-Green($msg) { Write-Host $msg -ForegroundColor Green }
function Write-Yellow($msg) { Write-Host $msg -ForegroundColor Yellow }
function Write-Red($msg)   { Write-Host $msg -ForegroundColor Red }

# Prevent running as administrator/root
If (([Security.Principal.WindowsIdentity]::GetCurrent()).Groups -match "S-1-5-32-544") {
    Write-Red "Error: This script should not be run as Administrator. Please run as a regular user."
    Stop-Transcript
    exit 1
}

# Remove unwanted files/directories
Get-ChildItem -Path . -Recurse -Include ".venv", "uv.lock", "build", "dist", "*egg-info" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# Argument parsing (simulate bash style)
param (
    [string]$cluster_credentials,
    [string]$openai_api_key,
    [string]$install_path = (Get-Location)
)
if (-not $cluster_credentials -or -not $openai_api_key) {
    Write-Red "Usage: .\install.ps1 -cluster_credentials <user[:password]> -openai_api_key <api-key> [-install_path <path>]"
    Stop-Transcript
    exit 1
}

# Ask for python version
$PYTHON_VERSION = Read-Host "Enter Python version [3.13]"
if (-not $PYTHON_VERSION) { $PYTHON_VERSION = "3.13" }
Write-Host "You selected Python version $PYTHON_VERSION"

# Check internet
Write-Blue "Checking internet connectivity..."
try {
    Invoke-WebRequest "https://www.google.com" -UseBasicParsing -ErrorAction Stop | Out-Null
    Write-Green "Internet connection is OK."
} catch {
    Write-Red "No internet connection detected. Aborting."
    Stop-Transcript
    exit 1
}

# Set locale (Windows: skip, but can inform user)
Write-Blue "Setting locale..."
Write-Yellow "Locale setting for en_US.UTF-8 skipped (Windows manages locale differently)."

# Install dependencies: ask user
$confirm = Read-Host "Do you want to install system dependencies? (y/N)"
if ($confirm -match "^[Yy]$") {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Green "Installing uv..."
        Invoke-WebRequest -Uri "https://astral.sh/uv/install.ps1" -OutFile "$env:TEMP\uv_install.ps1"
        & "$env:TEMP\uv_install.ps1"
    }
    # (Add Windows dependency install steps here if any)
    Write-Yellow "On Windows, dependencies may need to be installed manually."
} else {
    Write-Yellow "Skipping dependency installation."
}

# Install core
Write-Blue "Installing core framework..."
Push-Location "src\agilab\core"
& .\install.ps1
Pop-Location

# Install apps
Write-Blue "Installing apps..."
Push-Location "src\agilab\apps"
& .\install.ps1
Pop-Location

Write-Green "Installation complete!"
Stop-Transcript

    Write-Host ".env file updated." -ForegroundColor Green
}