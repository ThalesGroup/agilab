# install_Agi_framework.ps1
# Purpose: Install the framework

# Stop execution if any command fails
$ErrorActionPreference = "Stop"

# Load environment variables from .env
$envDir = $env:LOCALAPPDATA
$envFile = Join-Path $envDir "agilab\.env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*#') { return } # Skip comments
        if ($_ -match '^\s*$') { return } # Skip empty lines
        $parts = $_ -split '=', 2
        if ($parts.Count -eq 2) {
            $name = $parts[0].Trim()
            $value = $parts[1].Trim()
            Set-Item -Path "Env:$name" -Value $value
        }
    }
} else {
    Write-Host "Environment file not found: $envFile" -ForegroundColor Red
    exit 1
}

# Clean up AGI_PYTHON_VERSION
$env:AGI_PYTHON_VERSION = $env:AGI_PYTHON_VERSION -replace '^([0-9]+\.[0-9]+\.[0-9]+(\+freethreaded)?).*','$1'

$UvPreviewArgs = @("--preview-features", "extra-build-dependencies")
function Invoke-UvPreview {
    param([string[]]$MoreArgs)

    $allArgs = @()
    $allArgs += $UvPreviewArgs
    if ($MoreArgs) { $allArgs += $MoreArgs }

    & uv @allArgs
}

function Install-ModulePath {
    param(
        [string]$Path,
        [string[]]$ExtraInstalls = @()
    )
    Push-Location $Path
    Write-Host "uv sync -p $env:AGI_PYTHON_VERSION --dev" -ForegroundColor Blue
    Invoke-UvPreview @("sync", "-p", $env:AGI_PYTHON_VERSION, "--dev")
    Invoke-UvPreview @("run", "-p", $env:AGI_PYTHON_VERSION, "python", "-m", "ensurepip")
    Invoke-UvPreview @("pip", "install", "-e", ".")
    foreach ($pkg in $ExtraInstalls) {
        Invoke-UvPreview @("pip", "install", "-e", $pkg)
    }

    Invoke-UvPreview @("pip", "show", "pydantic") | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $repoRoot = (Resolve-Path "..\..\..").Path
        $localWheel = Get-ChildItem -LiteralPath $repoRoot -Recurse -Filter "pydantic-2.12.3*.whl" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($localWheel) {
            Invoke-UvPreview @("pip", "install", "--force-reinstall", "--no-index", "--find-links", $localWheel.Directory.FullName, "pydantic==2.12.3")
        } else {
            Invoke-UvPreview @("pip", "install", "--force-reinstall", "pydantic==2.12.3")
        }
    }

    Pop-Location
}

Write-Host "Installing framework from $(Get-Location)..." -ForegroundColor Blue
Write-Host "Python Version: $env:AGI_PYTHON_VERSION" -ForegroundColor Blue

Write-Host "Installing agi-env..." -ForegroundColor Blue
Install-ModulePath "agi-env"

Write-Host "Installing agi-node..." -ForegroundColor Blue
Install-ModulePath "agi-node" @("../agi-env")

Write-Host "Installing agi-cluster..." -ForegroundColor Blue
Install-ModulePath "agi-cluster" @("../agi-node", "../agi-env")

Write-Host "Installing agilab..." -ForegroundColor Blue
Push-Location (Resolve-Path "..\..\..")
Invoke-UvPreview @("sync", "-p", $env:AGI_PYTHON_VERSION)
Invoke-UvPreview @("pip", "install", "-e", "src/agilab/core/agi-env")
Invoke-UvPreview @("pip", "install", "-e", "src/agilab/core/agi-node")
Invoke-UvPreview @("pip", "install", "-e", "src/agilab/core/agi-cluster")
Invoke-UvPreview @("pip", "install", "-e", "src/agilab/core/agi-core")
Pop-Location

Write-Host "Checking installation..." -ForegroundColor Green
Invoke-UvPreview @("run", "--project", ".\agi-cluster", "-p", $env:AGI_PYTHON_VERSION, "--no-sync", "python", "-m", "pytest")
