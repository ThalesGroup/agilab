# PowerShell Script: install_Agi_framework.ps1
# Purpose: Install the fwk

function Resolve-Packages {
    param (
        [string]$DirPath
    )

    $dirPath = (Resolve-Path -Path $dirPath).Path
    $AgiPath = [System.Environment]::GetEnvironmentVariable("AGI_ROOT", [System.EnvironmentVariableTarget]::User)

    $AGI_ENV="$AgiPath" + "\agi/fwk/env"
    $AGI_CORE="$AgiPath" + "\agi/fwk/core"

    Push-Location $dirPath

    if (Select-String -Path "pyproject.toml" -Pattern "agi-env") {
        (Get-Content "pyproject.toml") -replace '(^\s*agi-env\s*=\s*{[^}]*path\s*=\s*")([^"]*)(")', "`$1$AGI_ENV`$3" | Set-Content "pyproject.toml"
    }
    if (Select-String -Path "pyproject.toml" -Pattern "agi-core")
    {
        (Get-Content "pyproject.toml") -replace '(^\s*agi-core\s*=\s*{[^}]*path\s*=\s*")([^"]*)(")', "`$1$AGI_CORE`$3" | Set-Content "pyproject.toml"
    }

    Pop-Location
}

function Main {
    Write-Host "Installing framework from $(Get-Location)..."
    Write-Host "Resolving env and core path inside tomls..."

    python .\pre-install.py

    Write-Host "Installing env..."
    Push-Location "env"
    uv sync
    uv pip install -e .
    Pop-Location

    Write-Host "Installing core..."
    Push-Location "core"
    uv sync --extra managers
    uv pip install -e .
    Pop-Location

    Push-Location "gui"
    uv sync
    Pop-Location

    Write-Host "Checking installation..."
    uv run --project core/managers python run-all-test.py
}

Main