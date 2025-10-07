# install.ps1
# Purpose: Root/Main AGI Framework Installer (PowerShell version)
# Argument parsing (simulate bash style)
param(
    [Parameter(Mandatory = $false)]
    [switch]$offline,

    [Parameter(Mandatory = $false)]
    [string]$openai_api_key,

    [Parameter(Mandatory = $false)]
    [string]$cluster_credentials = "",

    [Parameter(Mandatory = $false)]
    [string]$install_path = (Get-Location).Path
)

function Write-Blue($msg)  { Write-Host $msg -ForegroundColor Blue }
function Write-Green($msg) { Write-Host $msg -ForegroundColor Green }
function Write-Yellow($msg) { Write-Host $msg -ForegroundColor Yellow }
function Write-Red($msg)   { Write-Host $msg -ForegroundColor Red }

$ErrorActionPreference = "Stop"

function Test-VisualStudio {
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
        $vs2022 = & $vswhere -version 17.0 -latest -products * -property installationPath

        if ($vs2022) {
            Write-Green "Visual Studio 2022 is installed at: $vs2022"
        } else {
            Write-Red "Visual Studio 2022 is not found."
            exit 1
        }
    } else {
        Write-Red "vswhere.exe not found. Cannot determine VS installation."
        Write-Red "Please ensure Visual Studio 2022 is installed before continuing."
        exit 1
    }
}

function Test-Internet {
    Write-Blue "Testing internet connectivity..."
    try {
        $response = Invoke-WebRequest -Uri "https://www.google.com" -Method Head -TimeoutSec 10
        if ($response.StatusCode -eq 200) {
            Write-Green "Internet connection is OK."
        }
    }
    catch {
        Write-Red "No internet connection detected. Abording."
        Stop-Transcript
        exit 1
    }
    Write-Host ""
}

function Install-Dependencies {
    Write-Blue "Installing system dependencies"
    Write-Host ""
    $choice = Read-Host "Do you want to install system dependencies? (y/N)"
    if ($choice -match "^[Yy]$") {
        if (-not (Get-Command "uv" -ErrorAction SilentlyContinue))
        {
            Write-Blue "Installing uv..."
            powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
        }
        Write-Yellow "NOTE: Please install required dependencies manually or via your preferred package manager on Windows."
        # Optionally, add code here to install dependencies using Chocolatey if desired.
    }
    Write-Host ""
}

function Select-PythonVersion {
    # Choosing Python version...
    Write-Host "Choosing Python version..." -ForegroundColor Blue

    $PYTHON_VERSION = Read-Host -Prompt "Enter Python major version [3.13]"
    if ([string]::IsNullOrWhiteSpace($PYTHON_VERSION)) {
        $PYTHON_VERSION = "3.13"
    }

    Write-Host "You selected Python version $PYTHON_VERSION"


    $availablePythonVersions = uv python list | Where-Object { $_ -match $PYTHON_VERSION }
    if (-not $availablePythonVersions) {
        Write-Red "No matching Python versions found for '$PYTHON_VERSION'"
        exit 1
    }

    $pythonArray = @()
    foreach ($line in $availablePythonVersions) {
        $pythonArray += $line
    }

    for ($i = 0; $i -lt $pythonArray.Count; $i++) {
        if ($pythonArray[$i] -match $PYTHON_VERSION) {
            Write-Host "$($i + 1) - $($pythonArray[$i])" -ForegroundColor Green
        } else {
            Write-Host "$($i + 1) - $($pythonArray[$i])"
        }
    }

    do {
        $selection = Read-Host "Enter the number of the Python version you want to use (default: 1)"
        if ([string]::IsNullOrWhiteSpace($selection)) {
            $selection = 1
        }

        $valid = [int]$selection -ge 1 -and [int]$selection -le $pythonArray.Count
        if (-not $valid) {
            Write-Red "Invalid selection. Please try again."
        }
    } while (-not $valid)

    $chosenPython = ($pythonArray[$selection - 1] -split '\s+')[0]

    $installedPythons = (uv python list --only-installed | ForEach-Object { ($_ -split '\s+')[0] })

    if ($installedPythons -notcontains $chosenPython) {
        Write-Blue "Installing $chosenPython..."
        uv python install $chosenPython
        Write-Green "Python version ($chosenPython) is now installed."
    } else {
        Write-Green "Python version ($chosenPython) is already installed."
    }

    $env:PYTHON_VERSION = ($chosenPython -split '-')[1]
}


function Backup-AGIProject {
    Write-Blue "Backing Up Existing AGI Project (if any)"
    Write-Host ""
    if ($install_path -eq $CurrentPath)
    {
        Write-Yellow "AGI project directory is 'src'; Skipping Backup."
        return
    }
    if (Test-Path $CurrentPath) {
        if (Test-Path (Join-Path $CurrentPath "zip-agi.py")) {
            $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
            $backupFile = Join-Path $LocalDir ("{0}_{1}.zip" -f (Split-Path $AgiProject -Leaf), $timestamp)
            Write-Blue "Existing AGI project found at $AgiProject. Creating backup: $backupFile"

            try {
                # Use Compress-Archive as a backup mechanism
                Compress-Archive -Path $AgiProject\* -DestinationPath $backupFile -Force
                Write-Green "Backup created successfully at $backupFile."
                if ((Split-Path $AgiProject -Leaf) -ne "agi") {
                    Remove-Item -Recurse -Force $AgiProject
                    Write-Green "Existing AGI project directory removed."
                }
                else {
                    Write-Yellow "AGI project directory is 'src'; preserving it."
                }
            }
            catch {
                Write-Red "Error: Backup failed. Aborting installation."
                Write-Red "Details: $($_.Exception.Message)"
                Stop-Transcript
                exit 1
            }
        }
        else {
            Write-Yellow "Existing AGI project found at $AgiProject but no zip-agi.py found. Skipping backup."
        }
    }
    else {
        Write-Yellow "No existing AGI project found at $AgiProject. Skipping backup."
    }
    Write-Host ""
}

function Copy-ProjectFiles {
    Write-Blue $install_path
    Write-Blue $AgiPathFile
    Write-Blue $CurrentPath

    if ($install_path -ne $CurrentPath) {
        if (Test-Path "$CurrentPath/src") {
            Write-Blue "Copying project files to install directory..."
            New-Item -ItemType Directory -Force -Path $install_path | Out-Null
            robocopy $CurrentPath $install_path /E /MIR /NFL /NDL /NJH /NJS | Out-Null
        } else {
            Write-Red "Source directory 'src' not found. Exiting."
            exit 1
        }
    } else {
        Write-Yellow "Using current directory as install directory; no copy needed."
    }
    "$install_path/src/agilab" | Set-Content -Encoding UTF8 -Path $AgiPathFile
    [System.Environment]::SetEnvironmentVariable('AGI_ROOT', "$install_path/src/agilab", [System.EnvironmentVariableTarget]::User)
    Write-Green "Installation root path has been exported as AGI_ROOT and written in $LocalDir"

}

function Update-Environment {
    $envFile = Join-Path $LocalDir ".env"

    if (Test-Path $envFile) {
        Remove-Item $envFile
    }

    @"
OPENAI_API_KEY="$OpenaiApiKey"
CLUSTER_CREDENTIALS="$AgiCredentials"
AGI_PYTHON_VERSION="$env:PYTHON_VERSION"
"@ | Set-Content -Encoding UTF8 -Path $envFile

    Write-Green "Environment updated in $envFile"
}

function Install-Core {
    $frameworkDir = Join-Path $install_path "src\agilab\core"

    Write-Blue "Installing Framework..."
    Write-Blue $frameworkDir
    Push-Location $frameworkDir
    if ($Offline) {
        & "./install.ps1" -$AgiProject $frameworkDir -Offline
    } else {
        & "./install.ps1" -$AgiProject $frameworkDir
    }

    Pop-Location
}

function Install-Apps-Views {
    $dir = Join-Path $install_path "src\agilab"

    Write-Blue "Installing Apps and Views..."
    Push-Location $dir
    Write-Host $PWD
    & "./install_apps_views.ps1"
    Pop-Location
}


function Write-EnvValues {
    $sharedDir = $env:LOCALAPPDATA
    $sharedEnv = Join-Path $sharedDir "agilab\.env"
    $sharedPath = Join-Path $sharedDir "agilab\.agilab-path"
    $agilabEnv = Join-Path $env:USERPROFILE ".agilab\.env"

    if (-not (Test-Path $sharedEnv)) {
        Write-Host "Error: $sharedEnv does not exist." -ForegroundColor Red
        exit 1
    }
    # Append the shared env file content to agilab env file
    $path = Get-Content $sharedPath
    if (($path -like "A:*" -or $path -like "*MyApp*") -and ($username -like "T0*"))
    {
        $userDir = [Environment]::GetFolderPath('UserProfile')
        $agilabEnv = Join-Path $userDir "MyApp/.agilab/.env"
    }

    Get-Content $sharedEnv | Out-File -Append -FilePath $agilabEnv -Encoding UTF8

    Write-Host ".env file updated." -ForegroundColor Green
}

function Install-PyCharmScript {
    rm -f .idea/workspace.xml
    Write-Host "Patching PyCharm workspace.xml interpreter settings..." -ForegroundColor Blue
    uv run -p $env:PYTHON_VERSION python pycharm/setup_pycharm.py
    if ($LastExitCode -ne 0) {
        Write-Host "Pycharm/setup_pycharm.py failed or not found; continuing..." -ForegroundColor Yellow
    }
}

# Main Flow

# Prevent Running as Administrator
if ([Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Red "Error: This script should not be run as Administrator. Please run as a regular user."
    Stop-Transcript
    exit 1
}

# ================================
# Global Variables and Paths
# ================================
# AGI_INSTALL_PATH corresponds to $install_path.
$CurrentPath = (Get-Location).Path

$LocalDir = Join-Path $env:LOCALAPPDATA "agilab"
New-Item -ItemType Directory -Force -Path $LocalDir | Out-Null
$AgiPathFile = Join-Path $LocalDir ".agilab-path"

$PYTHON_VERSION = "3.13"

# Define project directories (AGI_PROJECT_SRC is "$AgiDir\src")
$AgiProject = Join-Path $CurrentPath "src/agilab"

$AppsDir = Join-Path $AgiProject "apps"

$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$username = $currentUser.Split('\')[-1]


Write-Blue "Installation Directory: $install_path"

if (-not $offline) {
    $missingVars = @()

    if (-not $openai_api_key) { $missingVars += "openai_api_key" }
    if (-not $cluster_credentials) { $missingVars += "cluster_credentials" }

    if ($missingVars.Count -gt 0) {
        Write-Red ("{0} {1} required when not in offline mode." -f ($missingVars -join " and "),
                   $(if ($missingVars.Count -gt 1) { "are" } else { "is" }))
        Stop-Transcript
        exit 1
    }
}

$LogDir = Join-Path $env:USERPROFILE "log\install_logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir ("install_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
Start-Transcript -Path $LogFile

# Get-ChildItem -Recurse -Directory | Where-Object {
#     $_.Name -match '\.venv|uv.lock|build|dist|.*egg-info'
# } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

if (-not $Offline)
{
    Test-Internet
}
Test-VisualStudio
if (-not $Offline)
{
    Install-Dependencies
}
Select-PythonVersion
Backup-AGIProject
Copy-ProjectFiles
Update-Environment
Install-Core
Write-EnvValues
Install-Apps-Views
Install-PyCharmScript