param(
    [Parameter(Mandatory = $true)]
    [string]$OpenaiApiKey,

    [Parameter(Mandatory = $true)]
    [string]$AgiCredentials,

    [Parameter(Mandatory = $false)]
    [string]$InstallPath = (Get-Location).Path,

    [Parameter(Mandatory = $false)]
    [string]$PythonPath = (Get-Command python).Source
)

function Execute-Installation {
    param(
        [string]$ProjectDir,
        [string]$InstallScript,
        [string]$ProjectName
    )

    Write-Host "Installing $ProjectName..." -ForegroundColor Cyan
    Push-Location $ProjectDir
    if (Test-Path $InstallScript) {
        & $InstallScript -PythonPath $PythonPath
    }
    else {
        Write-Host "Error: Script $InstallScript not found in $ProjectDir" -ForegroundColor Red
    }
    Pop-Location
}

# Use the provided install path, defaulting to the current directory
$AgiDir = $InstallPath
Write-Host "Installation Directory: $AgiDir" -ForegroundColor Cyan

# Set environment variable 'Agi_ROOT'
[System.Environment]::SetEnvironmentVariable('Agi_ROOT', $AgiDir, [System.EnvironmentVariableTarget]::User)

# Define project directories (aligned with the Bash script: AGI_PROJECT = "$AGI_ROOT/src")
$AgiProject = Join-Path $AgiDir 'src'
$FrameworkDir = Join-Path $AgiProject 'fwk'
$AppsDir = Join-Path $AgiProject 'apps'
$FrameworkScript = Join-Path $FrameworkDir 'install.ps1'
$AppsScript = Join-Path $AppsDir 'install.ps1'

Write-Host "Selected user: $AgiCredentials" -ForegroundColor Yellow
Write-Host "OpenAI API Key: $OpenaiApiKey" -ForegroundColor Yellow

# Execute installation scripts for framework and apps
Execute-Installation -ProjectDir $FrameworkDir -InstallScript $FrameworkScript -ProjectName "fwk"
Execute-Installation -ProjectDir $AppsDir -InstallScript $AppsScript -ProjectName "apps"

# Update the environment file with user parameters
$HomeDir = [Environment]::GetFolderPath("UserProfile")
$AgiEnvFile = Join-Path $HomeDir ".agi_resources\.env"
if (-not (Test-Path $AgiEnvFile)) {
    New-Item -ItemType File -Path $AgiEnvFile -Force | Out-Null
}

"OPENAI_API_KEY=$OpenaiApiKey" | Out-File -FilePath $AgiEnvFile -Encoding ASCII -Append
"AGI_CREDENTIALS=$AgiCredentials" | Out-File -FilePath $AgiEnvFile -Encoding ASCII -Append

Write-Host "Installation of fwk and apps completed!" -ForegroundColor Green