# PowerShell script: install_spyd_apps.ps1
# Purpose: Install the spyd-apps

$ErrorActionPreference = "Stop"


# List only the apps that you want to install
$INCLUDED_APPS = @(
    "my-code-project",
    "flight-project"
)

function Resolve-Packages {
    param (
        [string]$dirPath
    )
    Write-Host "Resolving packages"
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
        (Get-Content "pyproject.toml") -replace '(^\*agi-core\s*=\s*{[^}]*path\s*=\s*")([^"]*)(")', "`$1$AGI_CORE`$3" | Set-Content "pyproject.toml"
    }

    Pop-Location
}

function Contains-Element {
    param (
        [string]$element,
        [string[]]$array
    )
    return $array -contains $element
}

function Main {
    Write-Output "Retrieving all apps..."

    foreach ($app in $INCLUDED_APPS) {
        Write-Output "Installing $app..."
        Resolve-Packages -dirPath $app

        uv run --project ../fwk/core python install.py $app
        if ($LASTEXITCODE  -eq 0) {
            Write-Output "'$app' successfully installed."
        } else {
            Write-Output "'$app' installation failed."
            exit 1
        }
    }

    Write-Host "Installation of spyd-apps complete!"
}

Main