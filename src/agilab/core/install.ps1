# install_core.ps1
# Purpose: Install the core framework (PowerShell version)

$ErrorActionPreference = "Stop"

# Logging setup (simulates tee -a to log file)
$LOG_DIR = "$HOME\log\install_logs"
$LOG_FILE = "$LOG_DIR\install_core_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
if (-not (Test-Path $LOG_DIR)) { New-Item -Path $LOG_DIR -ItemType Directory | Out-Null }
Start-Transcript -Path $LOG_FILE

function Write-Blue($msg)  { Write-Host $msg -ForegroundColor Blue }
function Write-Green($msg) { Write-Host $msg -ForegroundColor Green }
function Write-Red($msg)   { Write-Host $msg -ForegroundColor Red }

Write-Blue "Installing core framework from $(Get-Location)..."

# Clean up unwanted files/directories
Get-ChildItem -Path . -Recurse -Include ".venv", "uv.lock", "build", "dist", "*egg-info" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# Run install steps
Push-Location agi-core
Invoke-Expression "uv sync --dev"
Invoke-Expression "uv build --wheel"
Pop-Location

Write-Green "Core installation complete!"

Stop-Transcript
