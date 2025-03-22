param(
    [Parameter(Mandatory = $true)]
    [string]$OpenaiApiKey,

    [Parameter(Mandatory = $true)]
    [string]$AgiCredentials,

    [Parameter(Mandatory = $false)]
    [string]$InstallPath = (Get-Location).Path,

    [Parameter(Mandatory = $false)]
    [string]$PythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
)

# ================================
# Prevent Running as Administrator
# ================================
if ([Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Error: This script should not be run as Administrator. Please run as a regular user." -ForegroundColor Red
    exit 1
}

# ================================
# Logging Setup
# ================================
$LogDir = Join-Path $env:USERPROFILE "log\install_logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir ("install_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
Start-Transcript -Path $LogFile

Write-Host "========================================" -ForegroundColor Blue
Write-Host "Installation started at $(Get-Date)" -ForegroundColor Blue
Write-Host "Log file: $LogFile" -ForegroundColor Blue
Write-Host "========================================" -ForegroundColor Blue
Write-Host ""

# ================================
# Global Variables and Paths
# ================================
# AGI_INSTALL_PATH corresponds to $InstallPath.
$AgiDir = $InstallPath
# Set Agi_ROOT environment variable for the user
[System.Environment]::SetEnvironmentVariable('Agi_ROOT', $AgiDir, [System.EnvironmentVariableTarget]::User)

# Define project directories (AGI_PROJECT_SRC is "$AgiDir\src")
$AgiProject = Join-Path $AgiDir "src"
$FrameworkDir = Join-Path $AgiProject "fwk"
$AppsDir = Join-Path $AgiProject "apps"

Write-Host "Installation Directory: $AgiDir" -ForegroundColor Cyan
Write-Host "Selected user: $AgiCredentials" -ForegroundColor Yellow
Write-Host "OpenAI API Key: $OpenaiApiKey" -ForegroundColor Yellow

# ================================
# Utility Functions
# ================================

function Check-Internet {
    Write-Host "========================================" -ForegroundColor Blue
    Write-Host "Step 1: Checking Internet Connectivity" -ForegroundColor Blue
    Write-Host "========================================" -ForegroundColor Blue
    try {
        $response = Invoke-WebRequest -Uri "https://www.google.com" -Method Head -TimeoutSec 10
        if ($response.StatusCode -eq 200) {
            Write-Host "Internet connection is active." -ForegroundColor Green
        }
    }
    catch {
        Write-Host "Error: No internet connection detected. Aborting installation." -ForegroundColor Red
        Stop-Transcript
        exit 1
    }
    Write-Host ""
}

function Install-Dependencies {
    Write-Host "========================================" -ForegroundColor Blue
    Write-Host "Step 2: Installing System Dependencies" -ForegroundColor Blue
    Write-Host "========================================" -ForegroundColor Blue
    Write-Host ""
    $choice = Read-Host "Do you want to install system dependencies? (y/N)"
    if ($choice -match "^[Yy]$") {
        Write-Host "NOTE: Please install required dependencies manually or via your preferred package manager on Windows." -ForegroundColor Yellow
        # Optionally, add code here to install dependencies using Chocolatey if desired.
    }
    Write-Host ""
}

function Backup-AGIProject {
    Write-Host "========================================" -ForegroundColor Blue
    Write-Host "Step 3: Backing Up Existing AGI Project (if any)" -ForegroundColor Blue
    Write-Host "========================================" -ForegroundColor Blue
    Write-Host ""
    if (Test-Path $AgiProject) {
        if (Test-Path (Join-Path $AgiProject "zip-agi.py")) {
            $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
            $backupFile = Join-Path $AgiDir ("agilib_{0}_{1}.zip" -f (Split-Path $AgiProject -Leaf), $timestamp)
            Write-Host "Existing AGI project found at $AgiProject. Creating backup: $backupFile" -ForegroundColor Yellow

            try {
                # Use Compress-Archive as a backup mechanism
                Compress-Archive -Path $AgiProject\* -DestinationPath $backupFile -Force
                Write-Host "Backup created successfully at $backupFile." -ForegroundColor Green
                if ((Split-Path $AgiProject -Leaf) -ne "src") {
                    Remove-Item -Recurse -Force $AgiProject
                    Write-Host "Existing AGI project directory removed." -ForegroundColor Green
                }
                else {
                    Write-Host "AGI project directory is 'src'; preserving it." -ForegroundColor Yellow
                }
            }
            catch {
                Write-Host "Error: Backup failed. Aborting installation." -ForegroundColor Red
                Stop-Transcript
                exit 1
            }
        }
        else {
            Write-Host "Existing AGI project found at $AgiProject but no zip-agi.py found. Skipping backup." -ForegroundColor Yellow
        }
    }
    else {
        Write-Host "No existing AGI project found at $AgiProject. Skipping backup." -ForegroundColor Yellow
    }
    Write-Host ""
}

function Copy-AGIProject {
    Write-Host "========================================" -ForegroundColor Blue
    Write-Host "Step 4: Copying AGI Project Files" -ForegroundColor Blue
    Write-Host "========================================" -ForegroundColor Blue
    Write-Host ""
    if (Test-Path ".\src") {
        Write-Host "Copying AGI project source from .\src to $AgiProject..." -ForegroundColor Yellow
        if (-not (Test-Path $AgiProject)) {
            New-Item -ItemType Directory -Path $AgiProject | Out-Null
        }
        try {
            Copy-Item -Path ".\src\*" -Destination $AgiProject -Recurse -Force
            Write-Host "AGI project files copied successfully to $AgiProject." -ForegroundColor Green
        }
        catch {
            Write-Host "Error: Failed to copy AGI project files to $AgiProject." -ForegroundColor Red
            Stop-Transcript
            exit 1
        }
    }
    else {
        Write-Host "Error: AGI project source (.\src directory) not found. Exiting." -ForegroundColor Red
        Stop-Transcript
        exit 1
    }
    Write-Host ""
}

function Update-EnvFile {
    $HomeDir = [Environment]::GetFolderPath("UserProfile")
    $AgiEnvFile = Join-Path $HomeDir ".agi_resources\.env"
    if (-not (Test-Path (Split-Path $AgiEnvFile))) {
        New-Item -ItemType Directory -Path (Split-Path $AgiEnvFile) -Force | Out-Null
    }
    if (-not (Test-Path $AgiEnvFile)) {
        New-Item -ItemType File -Path $AgiEnvFile -Force | Out-Null
    }
    # Append the environment variables (avoid duplicates)
    if (-not (Select-String -Path $AgiEnvFile -Pattern "OPENAI_API_KEY=" -Quiet)) {
        "OPENAI_API_KEY=$OpenaiApiKey" | Out-File -FilePath $AgiEnvFile -Encoding ASCII -Append
    }
    if (-not (Select-String -Path $AgiEnvFile -Pattern "AGI_CREDENTIALS=" -Quiet)) {
        "AGI_CREDENTIALS=$AgiCredentials" | Out-File -FilePath $AgiEnvFile -Encoding ASCII -Append
    }
    if (-not (Select-String -Path $AgiEnvFile -Pattern "PYTHON_PATH=" -Quiet)) {
        "PYTHON_PATH=$PythonPath" | Out-File -FilePath $AgiEnvFile -Encoding ASCII -Append
    }
    Write-Host "Environment variables updated in $AgiEnvFile." -ForegroundColor Green
    Write-Host ""
}

function Execute-Installation {
    param(
        [string]$ProjectDir,
        [string]$InstallScript,
        [string]$ProjectName
    )
    Write-Host "========================================" -ForegroundColor Blue
    Write-Host "Installing $ProjectName..." -ForegroundColor Blue
    Write-Host "========================================" -ForegroundColor Blue
    Push-Location $ProjectDir
    if (Test-Path $InstallScript) {
        # Pass PythonPath parameter to the child script if needed.
        & $InstallScript -PythonPath $PythonPath
    }
    else {
        Write-Host "Error: Script $InstallScript not found in $ProjectDir" -ForegroundColor Red
    }
    Pop-Location
    Write-Host ""
}

# ================================
# Main Flow
# ================================
Check-Internet
Install-Dependencies
Backup-AGIProject
Copy-AGIProject
Update-EnvFile

# Define installation script paths for framework and apps
$FrameworkScript = Join-Path $FrameworkDir "install.ps1"
$AppsScript = Join-Path $AppsDir "install.ps1"

# Execute installation scripts for framework and apps
Execute-Installation -ProjectDir $FrameworkDir -InstallScript $FrameworkScript -ProjectName "Framework"
Execute-Installation -ProjectDir $AppsDir -InstallScript $AppsScript -ProjectName "Apps"

# Starting AGILAB (assuming agilab.ps1 exists at the root of the install directory)
$AgilabScript = Join-Path $AgiDir "agilab.ps1"
if (Test-Path $AgilabScript) {
    Write-Host "Starting AGILAB from $AgiDir" -ForegroundColor Green
    & $AgilabScript -OpenaiApiKey $OpenaiApiKey
    if ($LASTEXITCODE -eq 0) {
        Write-Host "AGILAB started successfully." -ForegroundColor Green
    }
    else {
        Write-Host "Error: Failed to start AGILAB." -ForegroundColor Red
        Stop-Transcript
        exit 1
    }
}
else {
    Write-Host "Error: AGILAB startup script not found at $AgilabScript" -ForegroundColor Red
    Stop-Transcript
    exit 1
}

Stop-Transcript