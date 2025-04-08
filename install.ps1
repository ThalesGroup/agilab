param(
    [Parameter(Mandatory = $true)]
    [string]$OpenaiApiKey,

    [Parameter(Mandatory = $true)]
    [string]$AgiCredentials,

    [Parameter(Mandatory = $false)]
    [string]$InstallPath = (Get-Location).Path
)

$LogDir = Join-Path $env:USERPROFILE "log\install_logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir ("install_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
Start-Transcript -Path $LogFile

Get-ChildItem -Recurse -Directory | Where-Object {
    $_.Name -match '\.venv|uv.lock|build|dist|.*egg-info'
} | Remove-Item -Recurse -Force


# ================================
# Prevent Running as Administrator
# ================================
if ([Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Error: This script should not be run as Administrator. Please run as a regular user." -ForegroundColor Red
    Stop-Transcript
    exit 1
}

# ================================
# Global Variables and Paths
# ================================
# AGI_INSTALL_PATH corresponds to $InstallPath.
$CurrentPath = (Get-Location).Path

$LocalDir = Join-Path $env:LOCALAPPDATA "agilab"
New-Item -ItemType Directory -Force -Path $LocalDir | Out-Null
$AgiPathFile = Join-Path $LocalDir ".agi-path"

$PYTHON_VERSION = "3.12"

# Define project directories (AGI_PROJECT_SRC is "$AgiDir\src")
$AgiProject = Join-Path $CurrentPath "src\agilab"
$FrameworkDir = Join-Path $AgiProject "fwk"
$AppsDir = Join-Path $AgiProject "apps"

Write-Host "Installation Directory: $InstallPath" -ForegroundColor Cyan
Write-Host "Selected user: $AgiCredentials" -ForegroundColor Yellow
Write-Host "OpenAI API Key: $OpenaiApiKey" -ForegroundColor Yellow

# ================================
# Utility Functions
# ================================

function Check-VisualStudio {
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
        $vs2022 = & $vswhere -version 17.0 -latest -products * -property installationPath

        if ($vs2022) {
            Write-Host "Visual Studio 2022 is installed at: $vs2022" -ForegroundColor Green
        } else {
            Write-Host "Visual Studio 2022 is not found." -ForegroundColor Red
            exit 1
        }
    } else {
        Write-Host "vswhere.exe not found. Cannot determine VS installation." -ForegroundColor Red
        Write-Host "Please ensure Visual Studio 2022 is installed before continuing." -ForegroundColor Green
        exit 1
    }

}

function Check-Internet {
    Write-Host "Checking internet connectivity..." -ForegroundColor Blue
    try {
        $response = Invoke-WebRequest -Uri "https://www.google.com" -Method Head -TimeoutSec 10
        if ($response.StatusCode -eq 200) {
            Write-Host "Internet connection is OK." -ForegroundColor Green
        }
    }
    catch {
        Write-Host "No internet connection detected. Abording." -ForegroundColor Red
        Stop-Transcript
        exit 1
    }
    Write-Host ""
}

function Install-Dependencies {
    Write-Host "Installing system dependencies" -ForegroundColor Blue
    Write-Host ""
    $choice = Read-Host "Do you want to install system dependencies? (y/N)"
    if ($choice -match "^[Yy]$") {
        if (-not (Get-Command "uv" -ErrorAction SilentlyContinue))
        {
            Write-Host "Installing uv..." -ForegroundColor Blue
            powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
        }
        Write-Host "NOTE: Please install required dependencies manually or via your preferred package manager on Windows." -ForegroundColor Yellow
        # Optionally, add code here to install dependencies using Chocolatey if desired.
    }
    Write-Host ""
}

function Choose-PytonVersion {
    Write-Host "Choosing Python version..." -ForegroundColor Blue

    $availablePythonVersions = uv python list | Where-Object { $_ -match $PYTHON_VERSION }
    if (-not $availablePythonVersions) {
        Write-Host "No matching Python versions found for '$PYTHON_VERSION'" -ForegroundColor Red
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

        $valid = $selection -as [int] -and $selection -ge 1 -and $selection -le $pythonArray.Count
        if (-not $valid) {
            Write-Host "Invalid selection. Please try again." -ForegroundColor Red
        }
    } while (-not $valid)

    $chosenPython = ($pythonArray[$selection - 1] -split '\s+')[0]

    $installedPythons = (uv python list --only-installed | ForEach-Object { ($_ -split '\s+')[0] })

    if ($installedPythons -notcontains $chosenPython) {
        Write-Host "Installing $chosenPython..." -ForegroundColor Yellow
        uv python install $chosenPython
        Write-Host "Python version ($chosenPython) is now installed." -ForegroundColor Green
    } else {
        Write-Host "Python version ($chosenPython) is already installed." -ForegroundColor Green
    }

    $env:PYTHON_VERSION = ($chosenPython -split '-')[1]
}


function Backup-AGIProject {
    Write-Host "Backing Up Existing AGI Project (if any)" -ForegroundColor Blue
    Write-Host ""
    if ($InstallPath -eq $CurrentPath)
    {
        Write-Host "AGI project directory is 'src'; Skipping Backup." -ForegroundColor Yellow
        return
    }
    if (Test-Path $CurrentPath) {
        if (Test-Path (Join-Path $CurrentPath "zip-agi.py")) {
            $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
            $backupFile = Join-Path $LocalDir ("{0}_{1}.zip" -f (Split-Path $AgiProject -Leaf), $timestamp)
            Write-Host "Existing AGI project found at $AgiProject. Creating backup: $backupFile" -ForegroundColor Yellow

            try {
                # Use Compress-Archive as a backup mechanism
                Compress-Archive -Path $AgiProject\* -DestinationPath $backupFile -Force
                Write-Host "Backup created successfully at $backupFile." -ForegroundColor Green
                if ((Split-Path $AgiProject -Leaf) -ne "agilab") {
                    Remove-Item -Recurse -Force $AgiProject
                    Write-Host "Existing AGI project directory removed." -ForegroundColor Green
                }
                else {
                    Write-Host "AGI project directory is 'src'; preserving it." -ForegroundColor Yellow
                }
            }
            catch {
                Write-Host "Error: Backup failed. Aborting installation." -ForegroundColor Red
                Write-Host "Details: $($_.Exception.Message)" -ForegroundColor Red
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

function Copy-ProjectFiles {
    if ($InstallPath -ne $CurrentPath) {
        if (Test-Path "$CurrentPath/src") {
            Write-Host "Copying project files to install directory..." -ForegroundColor Blue
            New-Item -ItemType Directory -Force -Path $InstallPath | Out-Null
            robocopy $CurrentPath $InstallPath /E /MIR /NFL /NDL /NJH /NJS | Out-Null
        } else {
            Write-Host "Source directory 'src' not found. Exiting." -ForegroundColor Red
            exit 1
        }
    } else {
        Write-Host "Using current directory as install directory; no copy needed." -ForegroundColor Yellow
    }
    "$InstallPath/src" | Set-Content -Encoding UTF8 -Path $AgiPathFile
    [System.Environment]::SetEnvironmentVariable('AGI_ROOT', "$InstallPath/src", [System.EnvironmentVariableTarget]::User)
    Write-Host "Installation root path has been exported as AGI_ROOT and written in $LocalDir" -ForegroundColor Green

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

    Write-Host "Environment updated in $envFile" -ForegroundColor Green
}

function Install-FrameworkApps {
    $frameworkDir = Join-Path $InstallPath "src\agilab\fwk"
    $appsDir = Join-Path $InstallPath "src\agilab\apps"

    Write-Host "Installing Framework..." -ForegroundColor Blue
    Push-Location $frameworkDir
    & "./install.ps1" $frameworkDir
    Pop-Location

    Write-Host "Installing Apps..." -ForegroundColor Blue
    Write-Host "$appsDir" -ForegroundColor Yellow
    Push-Location $appsDir
    & "./install.ps1" $appsDir "1"
    Pop-Location
}

function Write-EnvValues {
    $sharedEnv = Join-Path $env:LOCALAPPDATA "agilab\.env"
    $agilabEnv = Join-Path $env:USERPROFILE ".agilab\.env"

    if (-not (Test-Path $sharedEnv)) {
        Write-Host "Error: $sharedEnv does not exist." -ForegroundColor Red
        exit 1
    }

    # Append the shared env file content to agilab env file
    Get-Content $sharedEnv | Out-File -Append -FilePath $agilabEnv -Encoding UTF8

    Write-Host ".env file updated." -ForegroundColor Green
}

# ================================
# Main Flow
# ================================
Check-Internet
Check-VisualStudio
Install-Dependencies
Choose-PytonVersion
Backup-AGIProject
Copy-ProjectFiles
Update-Environment
Install-FrameworkApps
Write-EnvValues