param(
    [Parameter(Mandatory = $true)]
    [string]$AgiCredentials,

    [Parameter(Mandatory = $true)]
    [string]$OpenaiApiKey,

    [Parameter(Mandatory = $false)]
    [string]$PythonPath = (Get-Command python).Source
)

function Execute-Installation
{
    param(
        [string]$ProjectDir,
        [string]$InstallScript,
        [string]$ProjectName
    )

    Write-Host "Installation of $ProjectName..."

    Push-Location $ProjectDir

    if (Test-Path "$InstallScript")
    {
        & "$InstallScript" -PythonPath $PythonPath
    }
    else
    {
        Write-Host "Error: Script $InstallScript not found in $ProjectDir" -ForegroundColor Red
    }

    Pop-Location
}

# Define environment variables and paths
$AgiDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Write-Host "Agi Dir: $AgiDir"
[System.Environment]::SetEnvironmentVariable('Agi_ROOT', $AgiDir, [System.EnvironmentVariableTarget]::User)

$AgiRoot = Join-Path $AgiDir 'agig'
$FrameworkDir = Join-Path $AgiRoot  'fwk'
$AppsDir = Join-Path $AgiRoot 'apps'
$FrameworkScript = Join-Path $FrameworkDir 'install.ps1'
$AppsScript = Join-Path $AppsDir 'install.ps1'

$AgiEnvFile = Join-Path $AgiDir ".agi_resources/.env"

Write-Host "Selected user: $AgiCredentials"
Write-Host "OpenAI API Key: $OpenaiApiKey"

Execute-Installation -ProjectDir $FrameworkDir -InstallScript $FrameworkScript -ProjectName "fwk"
Execute-Installation -ProjectDir $AppsDir -InstallScript $AppsScript -ProjectName "apps"

# Install user paremeters
$AgienvContent = "OPENAI_API_KEY=$openaiapiKey"
$AgienvContent | Out-File -FilePath $AgiEnvFile -Encoding ASCII -Append

$AgienvContent = "AGI_CREDENTIALS=$Agicredentials"
$AgienvContent | Out-File -FilePath $AgiEnvFile -Encoding ASCII -Append



Write-Host "Installation of fwk and apps competed!" -ForegroundColor Green