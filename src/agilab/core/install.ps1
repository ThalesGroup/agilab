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
function Set-UvLinkMode {
    $requested = if ($env:AGILAB_UV_LINK_MODE) {
        $env:AGILAB_UV_LINK_MODE
    } elseif ($env:UV_LINK_MODE) {
        $env:UV_LINK_MODE
    } else {
        "hardlink"
    }
    if ($requested -notin @("clone", "copy", "hardlink", "symlink")) {
        throw "Invalid uv link mode '$requested'. Expected one of: clone, copy, hardlink, symlink."
    }
    $env:UV_LINK_MODE = $requested
    Write-Host "uv link mode: $env:UV_LINK_MODE" -ForegroundColor Blue
}

Set-UvLinkMode

$LinkCompatibleVenvs = if ($env:AGILAB_LINK_COMPATIBLE_VENVS) { $env:AGILAB_LINK_COMPATIBLE_VENVS } else { "1" }

function Invoke-UvPreview {
    param([string[]]$MoreArgs)

    $allArgs = @()
    $allArgs += $UvPreviewArgs
    if ($MoreArgs) { $allArgs += $MoreArgs }

    & uv @allArgs
}

function Ensure-PipIfMissing {
    Invoke-UvPreview @("run", "-p", $env:AGI_PYTHON_VERSION, "python", "-c", "import pip") *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "pip already available." -ForegroundColor Green
        return
    }
    Write-Host "pip missing; bootstrapping with ensurepip..." -ForegroundColor Yellow
    Invoke-UvPreview @("run", "-p", $env:AGI_PYTHON_VERSION, "python", "-m", "ensurepip")
}

function Install-ModulePath {
    param(
        [string]$Path,
        [string[]]$ExtraInstalls = @()
    )
    Push-Location $Path
    Write-Host "uv sync -p $env:AGI_PYTHON_VERSION --dev" -ForegroundColor Blue
    Invoke-UvPreview @("sync", "-p", $env:AGI_PYTHON_VERSION, "--dev")
    Ensure-PipIfMissing
    $pipArgs = @("pip", "install", "--upgrade", "--no-deps", "-e", ".")
    foreach ($pkg in $ExtraInstalls) {
        $pipArgs += @("-e", $pkg)
    }
    Invoke-UvPreview $pipArgs

    Pop-Location
}

function Test-LinkCompatibleVenvsEnabled {
    param([string]$Value)

    if (-not $Value) {
        return $false
    }
    return ($Value.ToLowerInvariant() -notin @("0", "false", "no", "off", "disabled"))
}

function Invoke-CompatibleCoreVenvLinking {
    if (-not (Test-LinkCompatibleVenvsEnabled $LinkCompatibleVenvs)) {
        Write-Host "Compatible core venv linking disabled." -ForegroundColor Blue
        return
    }

    $coreDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
    $linker = Join-Path (Split-Path -Parent $coreDir) "venv_linker.py"
    if (-not (Test-Path -LiteralPath $linker)) {
        Write-Host "Warning: compatible venv linker not found at $linker; keeping isolated core venvs." -ForegroundColor Yellow
        return
    }

    $report = if ($env:AGILAB_VENV_LINK_REPORT) {
        $env:AGILAB_VENV_LINK_REPORT
    } else {
        Join-Path (Join-Path $envDir "agilab") "core_venv_link_report.json"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $report) | Out-Null

    Write-Host "Linking compatible core virtual environments..." -ForegroundColor Blue
    Invoke-UvPreview @(
        "run", "-p", $env:AGI_PYTHON_VERSION, "--no-project", "--with", "packaging",
        "python", $linker,
        "--apply",
        "--report", $report,
        "--root", $coreDir
    )
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Compatible core venv link report: $report" -ForegroundColor Green
    } else {
        Write-Host "Warning: compatible core venv linking failed; keeping installed core venvs." -ForegroundColor Yellow
        $global:LASTEXITCODE = 0
    }
}

Write-Host "Installing framework from $(Get-Location)..." -ForegroundColor Blue
Write-Host "Python Version: $env:AGI_PYTHON_VERSION" -ForegroundColor Blue

Write-Host "Installing agi-env..." -ForegroundColor Blue
Install-ModulePath "agi-env"

Write-Host "Installing agi-node..." -ForegroundColor Blue
Install-ModulePath "agi-node" @("../agi-env")

Write-Host "Installing agi-cluster..." -ForegroundColor Blue
Install-ModulePath "agi-cluster" @("../agi-node", "../agi-env")

Write-Host "Installing agi-core..." -ForegroundColor Blue
Install-ModulePath "agi-core" @("../agi-env", "../agi-node", "../agi-cluster")

Invoke-CompatibleCoreVenvLinking

Write-Host "Installing agilab..." -ForegroundColor Blue
Push-Location (Resolve-Path "..\..\..")
Invoke-UvPreview @("sync", "-p", $env:AGI_PYTHON_VERSION)
Invoke-UvPreview @(
    "pip", "install", "--upgrade", "--no-deps",
    "-e", "src/agilab/core/agi-env",
    "-e", "src/agilab/core/agi-node",
    "-e", "src/agilab/core/agi-cluster",
    "-e", "src/agilab/core/agi-core"
)

$previousCoverageFile = $env:COVERAGE_FILE

$env:COVERAGE_FILE = ".coverage-agilab"
Write-Host "Checking installation (agilab test suite with coverage)..." -ForegroundColor Green
Invoke-UvPreview @(
    "run", "-p", $env:AGI_PYTHON_VERSION, "--no-sync", "--preview-features", "python-upgrade",
    "-m", "pytest",
    "src/agilab/test",
    "--cov=src/agilab",
    "--cov-report=term-missing",
    "--cov-report=xml:coverage-agilab.xml"
)

$env:COVERAGE_FILE = ".coverage-agi-env"
Write-Host "Running agi-env test suite with coverage..." -ForegroundColor Blue
Invoke-UvPreview @(
    "run", "-p", $env:AGI_PYTHON_VERSION, "--no-sync", "--preview-features", "python-upgrade",
    "-m", "pytest",
    "src/agilab/core/agi-env/test",
    "--cov=src/agilab/core/agi-env/src/agi_env",
    "--cov-report=term-missing",
    "--cov-report=xml:coverage-agi-env.xml"
)

$env:COVERAGE_FILE = ".coverage-agi-core"
Write-Host "Running core test suite with coverage..." -ForegroundColor Blue
Invoke-UvPreview @(
    "run", "-p", $env:AGI_PYTHON_VERSION, "--no-sync", "--preview-features", "python-upgrade",
    "-m", "pytest",
    "src/agilab/core/test",
    "--cov=src/agilab/core",
    "--cov=src/agilab/core/agi-node/src/agi_node",
    "--cov=src/agilab/core/agi-cluster/src/agi_cluster",
    "--cov-report=term-missing",
    "--cov-report=xml:coverage-agi-core.xml"
)

Invoke-UvPreview @(
    "run", "-p", $env:AGI_PYTHON_VERSION, "--no-sync", "--preview-features", "python-upgrade",
    "-m", "coverage", "xml", "-i",
    "--include=src/agilab/core/agi-node/src/agi_node/*",
    "-o", "coverage-agi-node.xml"
)

Invoke-UvPreview @(
    "run", "-p", $env:AGI_PYTHON_VERSION, "--no-sync", "--preview-features", "python-upgrade",
    "-m", "coverage", "xml", "-i",
    "--include=src/agilab/core/agi-cluster/src/agi_cluster/*",
    "-o", "coverage-agi-cluster.xml"
)

$env:COVERAGE_FILE = $previousCoverageFile

Pop-Location
