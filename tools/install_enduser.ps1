[CmdletBinding()]
param(
    [ValidateSet('local', 'pypi', 'testpypi')]
    [string]$Source = 'local',
    [string]$Version
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Ensure-Dir {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Set-PersistEnvVar {
    param(
        [Parameter(Mandatory)][string]$Key,
        [Parameter(Mandatory)][string]$Value,
        [Parameter(Mandatory)][string]$EnvFile
    )

    $dir = Split-Path -LiteralPath $EnvFile -Parent
    if ($dir) {
        Ensure-Dir $dir
    }

    $lines = @()
    if (Test-Path -LiteralPath $EnvFile) {
        $lines = Get-Content -LiteralPath $EnvFile -ErrorAction Stop
    }

    $updated = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $line = $lines[$i]
        $trimmed = $line.Trim()
        if ($trimmed.Length -eq 0 -or $trimmed.StartsWith('#')) {
            continue
        }
        $parts = $line.Split('=', 2)
        if ($parts.Count -ge 2 -and $parts[0].Trim() -eq $Key) {
            $lines[$i] = "$Key=$Value"
            $updated = $true
            break
        }
    }

    if (-not $updated) {
        $lines += "$Key=$Value"
    }

    Set-Content -LiteralPath $EnvFile -Value $lines -Encoding UTF8
}

function Invoke-Uv {
    param(
        [Parameter(Mandatory)][string[]]$Args,
        [switch]$IgnoreErrors
    )

    & uv @Args
    $exit = $LASTEXITCODE
    if (-not $IgnoreErrors -and $exit -ne 0) {
        throw "uv $($Args -join ' ') failed with exit code $exit"
    }
    return $exit
}

function Invoke-UvPreview {
    param(
        [Parameter(Mandatory)][string[]]$Args,
        [switch]$IgnoreErrors
    )

    Invoke-Uv -Args (@("--preview-features", "extra-build-dependencies") + $Args) -IgnoreErrors:$IgnoreErrors
}

function Resolve-InstallRoot {
    param([Parameter(Mandatory)][string]$Path)

    try {
        $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    } catch {
        return ""
    }

    $suffix = [System.IO.Path]::Combine("src", "agilab")
    if ($resolved.ToLower().EndsWith($suffix.ToLower())) {
        $parent = Split-Path -LiteralPath $resolved -Parent
        return Split-Path -LiteralPath $parent -Parent
    }
    return $resolved
}

function Get-VenvPython {
    param([Parameter(Mandatory)][string]$VenvRoot)

    $candidates = @(
        Join-Path $VenvRoot "Scripts/python.exe",
        Join-Path $VenvRoot "Scripts/python",
        Join-Path $VenvRoot "bin/python"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    return ""
}

function Resolve-CommonLatest {
    param([Parameter(Mandatory)][string[]]$Packages)

    $script = @'
import json
import sys
import urllib.request
from packaging.version import Version

pkgs = sys.argv[1:]

def releases(pkg):
    with urllib.request.urlopen(f"https://test.pypi.org/pypi/{pkg}/json") as r:
        data = json.load(r)
    return {v for v, files in data.get("releases", {}).items() if files}

common = None
for pkg in pkgs:
    rs = releases(pkg)
    common = rs if common is None else (common & rs)

if not common:
    sys.exit(1)

latest = str(sorted((Version(v) for v in common))[-1])
print(latest, end="")
'@

    $args = @("run", "python", "-c", $script) + $Packages
    $result = & uv @args
    if ($LASTEXITCODE -eq 0) {
        if ($result -is [System.Array]) {
            return ($result -join "`n").Trim()
        }
        return ("$result").Trim()
    }
    return ""
}

function Test-TestPyPIVersions {
    param(
        [string]$PythonExe,
        [string]$ShowScript,
        [string[]]$Packages,
        [string]$ForceVersion
    )

    if (-not (Test-Path -LiteralPath $PythonExe)) {
        Write-Warning "Skipping version verification; missing Python interpreter at $PythonExe"
        return $true
    }
    if (-not (Test-Path -LiteralPath $ShowScript)) {
        Write-Warning "Skipping version verification; show_dependencies.py not found at $ShowScript"
        return $true
    }

    $script = @'
import json
import os
import pathlib
import re
import subprocess
import sys

show_script = pathlib.Path(sys.argv[1])
packages = sys.argv[2:]
force_version = os.environ.get("FORCE_TESTPYPI_VERSION")

cmd = [sys.executable, str(show_script), "--repo", "testpypi"]
if force_version:
    cmd.extend(["--version", force_version])
cmd.extend(packages)
output = subprocess.check_output(cmd, text=True)
pattern = re.compile(r'^(ag[\w-]+) \(([^)]+)\) dependencies:', re.MULTILINE)
expected = {match.group(1).lower(): match.group(2) for match in pattern.finditer(output)}

pip_cmd = [sys.executable, "-m", "pip", "list", "--format", "json"]
installed_data = json.loads(subprocess.check_output(pip_cmd, text=True))
installed = {pkg["name"].lower(): pkg["version"] for pkg in installed_data}

mismatches = {}
for name, exp_version in expected.items():
    inst_version = installed.get(name)
    if inst_version != exp_version:
        mismatches[name] = (exp_version, inst_version)

if mismatches:
    print("[error] Version mismatch detected between TestPyPI metadata and installed packages:")
    for name, (exp_version, inst_version) in sorted(mismatches.items()):
        installed_label = inst_version if inst_version is not None else "missing"
        print(f"  {name}: expected {exp_version}, installed {installed_label}")
    sys.exit(1)

print("[info] TestPyPI agi* package versions match metadata.")
'@

    $tmp = New-TemporaryFile
    try {
        Set-Content -LiteralPath $tmp.FullName -Value $script -Encoding UTF8
        if ($ForceVersion) {
            $env:FORCE_TESTPYPI_VERSION = $ForceVersion
        } else {
            Remove-Item Env:FORCE_TESTPYPI_VERSION -ErrorAction SilentlyContinue
        }
        & $PythonExe $tmp.FullName $ShowScript @Packages
        $exitCode = $LASTEXITCODE
    } finally {
        Remove-Item -LiteralPath $tmp.FullName -ErrorAction SilentlyContinue
        if ($ForceVersion) {
            Remove-Item Env:FORCE_TESTPYPI_VERSION -ErrorAction SilentlyContinue
        }
    }
    return ($exitCode -eq 0)
}

function Install-OfflineAssistant {
    param([string]$PythonExe)

    if (-not (Test-Path -LiteralPath $PythonExe)) {
        Write-Warning "Skipping GPT-OSS install; missing interpreter at $PythonExe"
        return
    }

    $pyver = (& $PythonExe -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
    if (-not $pyver) {
        Write-Warning "Could not determine Python version; skipping GPT-OSS install"
        return
    }

    $parts = $pyver.Split('.')
    if ($parts.Count -lt 2) {
        Write-Warning "Could not parse Python version '$pyver'; skipping GPT-OSS install"
        return
    }

    $major = [int]$parts[0]
    $minor = [int]$parts[1]

    if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 12)) {
        Write-Host "Installing GPT-OSS offline assistant dependencies..."
        & $PythonExe -m pip install --upgrade "agilab[offline]" | Out-Host
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Unable to install GPT-OSS automatically. Run 'pip install agilab[offline]' manually once Python >=3.12 is available."
            return
        }
        Write-Host "GPT-OSS offline assistant base packages installed."
        foreach ($spec in @("transformers>=4.57.0", "torch>=2.8.0", "accelerate>=0.34.2")) {
            $pkg = $spec.Split(">=")[0]
            & $PythonExe -m pip show $pkg 1>$null 2>$null
            if ($LASTEXITCODE -ne 0) {
                & $PythonExe -m pip install --upgrade $spec | Out-Host
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "[info] Installed $spec for GPT-OSS backend support."
                } else {
                    Write-Warning "Failed to install $spec. Install it manually if you plan to use the $pkg backend."
                }
            }
        }
    } else {
        Write-Warning "Skipping GPT-OSS offline assistant (requires Python >=3.12; detected $pyver)."
    }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$RepoSrcDir = Join-Path (Join-Path $RepoRoot "src") "agilab"
$AgiSpace = Join-Path $HOME "agi-space"
Ensure-Dir $AgiSpace
Write-Host "Using AGI_SPACE: $AgiSpace"

$AppsRoot = Join-Path $AgiSpace "apps"
Ensure-Dir $AppsRoot

$Venv = Join-Path $AgiSpace ".venv"
$Packages = @("agilab", "agi-env", "agi-node", "agi-cluster", "agi-core")
$VersionArgSet = $PSBoundParameters.ContainsKey('Version')

$LocalShareDir = Join-Path (Join-Path (Join-Path $Home ".local") "share") "agilab"
$AgiPathFile = Join-Path $LocalShareDir ".agilab-path"
$EnvDir = Join-Path $Home ".agilab"
$EnvFile = Join-Path $EnvDir ".env"

$AgiInstallPath = ""
if (Test-Path -LiteralPath $AgiPathFile) {
    $AgiInstallPath = (Get-Content -LiteralPath $AgiPathFile -Raw).Trim()
    if ($AgiInstallPath) {
        Write-Host "agilab install path: $AgiInstallPath"
    } else {
        Write-Warning "Saved agilab install path is empty."
    }
} else {
    Write-Warning "No saved agilab install path found."
}

$AgiInstallRoot = ""
if ($Source -eq 'local') {
    if ([string]::IsNullOrWhiteSpace($AgiInstallPath) -or -not (Test-Path -LiteralPath $AgiInstallPath)) {
        if (Test-Path -LiteralPath $RepoSrcDir) {
            $AgiInstallPath = $RepoSrcDir
            Write-Host "[info] Local source auto-detected at $AgiInstallPath"
        } else {
            throw "Unable to locate local source checkout (expected $RepoSrcDir)."
        }
    } elseif ($AgiInstallPath -match '[\\/]+wenv[\\/]') {
        if (Test-Path -LiteralPath $RepoSrcDir) {
            Write-Warning "Saved local install path ($AgiInstallPath) points to a worker environment; using $RepoSrcDir instead."
            $AgiInstallPath = $RepoSrcDir
        }
    }

    if (($AgiInstallPath -ne $RepoSrcDir) -and (Test-Path -LiteralPath $RepoSrcDir)) {
        Write-Host "[info] Persisting local install path to $RepoSrcDir"
        $AgiInstallPath = $RepoSrcDir
    }

    Ensure-Dir (Split-Path -LiteralPath $AgiPathFile -Parent)
    Set-Content -LiteralPath $AgiPathFile -Value $AgiInstallPath -Encoding UTF8

    if ($AgiInstallPath -eq $RepoSrcDir) {
        $AgiInstallRoot = $RepoRoot
    } else {
        $AgiInstallRoot = Resolve-InstallRoot -Path $AgiInstallPath
        if (-not $AgiInstallRoot) {
            $AgiInstallRoot = $AgiInstallPath
        }
    }
}

Set-PersistEnvVar -Key "APPS_DIR" -Value $AppsRoot -EnvFile $EnvFile

Write-Host "===================================="
Write-Host " MODE:     $Source"
$__verDisp = "<latest>"
if (-not [string]::IsNullOrEmpty($Version)) { $__verDisp = $Version }
Write-Host " VERSION:  $($__verDisp)"
Write-Host "===================================="

$venvPython = ""
Push-Location -LiteralPath $AgiSpace
try {
    Remove-Item -LiteralPath ".venv" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath "uv.lock" -Force -ErrorAction SilentlyContinue

    if (-not (Test-Path -LiteralPath "pyproject.toml")) {
        Invoke-Uv -Args @("init", "--bare", "--no-workspace")
    }

    Invoke-UvPreview -Args @("sync")
    Invoke-UvPreview -Args @("run", "python", "-m", "ensurepip", "--upgrade") -IgnoreErrors

    $venvPython = Get-VenvPython -VenvRoot $Venv

    switch ($Source) {
        'local' {
            if ([string]::IsNullOrWhiteSpace($AgiInstallRoot) -or -not (Test-Path -LiteralPath $AgiInstallRoot)) {
                throw "Missing or invalid install path for local source: $AgiInstallPath"
            }
            if (-not (Test-Path -LiteralPath $AgiInstallPath)) {
                throw "Missing or invalid install path: $AgiInstallPath"
            }

            Push-Location -LiteralPath $AgiInstallRoot
            try {
                Invoke-Uv -Args @("build", "--wheel")
            } finally {
                Pop-Location
            }

            Write-Host "Installing packages from local source tree..."
            foreach ($pkg in $Packages) {
                $corePath = Join-Path (Join-Path $AgiInstallPath "core") $pkg
                if (Test-Path -LiteralPath $corePath) {
                    Invoke-UvPreview -Args @("pip", "install", "--upgrade", "--no-deps", $corePath)
                }
            }
            Invoke-UvPreview -Args @("pip", "install", "--upgrade", "--no-deps", $AgiInstallRoot)
        }

        'pypi' {
            Write-Host "Installing from PyPI..."
            if ([string]::IsNullOrEmpty($Version)) {
                Invoke-UvPreview -Args (@("pip", "install", "--upgrade") + $Packages)
            } else {
                $pkgArgs = foreach ($pkg in $Packages) { "$pkg==$Version" }
                Invoke-UvPreview -Args (@("pip", "install", "--upgrade") + $pkgArgs)
            }
        }

        'testpypi' {
            $indexUrl = "https://test.pypi.org/simple"
            $extraUrl = "https://pypi.org/simple"

            Invoke-UvPreview -Args @("pip", "install", "packaging")

            if ([string]::IsNullOrEmpty($Version)) {
                Write-Host "Resolving newest common TestPyPI version across: $($Packages -join ' ')"
                $attempt = 0
                while ([string]::IsNullOrEmpty($Version) -and $attempt -lt 10) {
                    $candidate = Resolve-CommonLatest -Packages $Packages
                    if ($candidate) {
                        $Version = $candidate
                        break
                    }
                    Start-Sleep -Seconds 3
                    $attempt++
                }

                if ([string]::IsNullOrEmpty($Version)) {
                    throw "ERROR: Could not find a common version for all packages on TestPyPI after retries."
                }
                Write-Host "Using version $Version for all packages"
            } else {
                Write-Host "Installing from TestPyPI (forced VERSION=$Version for all)."
            }

            $pkgListInstall = ($Packages -join ' ')
            Write-Host "Installing packages: $pkgListInstall == $Version"
            $pkgArgs = foreach ($pkg in $Packages) { "$pkg==$Version" }
            Invoke-UvPreview -Args (@("run", "python", "-m", "pip", "install", "--index", $indexUrl, "--extra-index-url", $extraUrl, "--upgrade", "--no-cache-dir") + $pkgArgs)

            $forceVersion = if ($VersionArgSet) { $Version } else { "" }
            if (-not (Test-TestPyPIVersions -PythonExe $venvPython -ShowScript (Join-Path $ScriptDir "show_dependencies.py") -Packages $Packages -ForceVersion $forceVersion)) {
                if (-not $env:AGI_INSTALL_RETRY) {
                    Write-Warning "Version mismatch detected; retrying install once..."
                    $env:AGI_INSTALL_RETRY = "1"
                    $reinvokeArgs = @("-Source", $Source)
                    if ($VersionArgSet) {
                        $reinvokeArgs += @("-Version", $Version)
                    }
                    & $PSCommandPath @reinvokeArgs
                    exit $LASTEXITCODE
                } else {
                    Write-Error "TestPyPI package versions still do not match metadata after retry.`nResolve the mismatch (e.g. wait for all packages to publish $Version) and rerun."
                    exit 1
                }
            }
        }
    }

    Install-OfflineAssistant -PythonExe $venvPython
} finally {
    Pop-Location
}

foreach ($leftover in @("agi_env", "agi-node", "agi-cluster", "agi-core")) {
    $path = Join-Path $Venv $leftover
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$venvPython = Get-VenvPython -VenvRoot $Venv

Write-Host "===================================="
Write-Host "Installed packages in agi-space/.venv:"
if ($venvPython) {
    $pipList = & $venvPython -m pip list
    if ($LASTEXITCODE -eq 0) {
        $matches = $pipList | Where-Object { $_ -match '^(agilab|agi-)' }
        if ($matches) {
            $matches | ForEach-Object { Write-Host $_ }
        } else {
            Write-Host "(No agi* packages detected.)"
        }
    } else {
        Write-Warning "Failed to list packages with pip."
    }
} else {
    Write-Warning "Python interpreter not found in $Venv; skipping package list."
}
Write-Host "===================================="



