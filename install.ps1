<#
  install.ps1
  Purpose: Root AGI Framework Installer (PowerShell) aligned with install.sh workflow.
#>

[CmdletBinding()]
param(
    [string]$ClusterSshCredentials,
    [string]$OpenaiApiKey,
    [string]$InstallPath = (Get-Location).Path,
    [string]$AppsRepository,
    [ValidateSet("local", "pypi", "testpypi")]
    [string]$Source = "local",
    [string]$PythonVersion,
    [switch]$Fast,
    [switch]$NoFast,
    [switch]$Yes,
    [switch]$InstallApps,
    [switch]$TestApps
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if ($Fast.IsPresent -and $NoFast.IsPresent) {
    Write-Error "Cannot specify both -Fast and -NoFast."
    exit 1
}

$script:FastMode = $Fast.IsPresent
$script:FastModeUserSet = $Fast.IsPresent -or $NoFast.IsPresent
$script:AssumeYes = $Yes.IsPresent
$script:AutoFastDefault = if ($NoFast.IsPresent -or $env:AGILAB_AUTO_FAST -eq "0") { $false } else { $true }
$script:InputIsRedirected = [Console]::IsInputRedirected
$script:ProvidedPythonVersion = if ($PSBoundParameters.ContainsKey('PythonVersion')) { $PythonVersion } else { $null }

if ($TestApps) {
    $InstallApps = $true
}

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $PSBoundParameters.ContainsKey('InstallPath')) {
    $InstallPath = $ScriptRoot
}

function Write-Info { param([string]$Message) Write-Host $Message -ForegroundColor Blue }
function Write-Success { param([string]$Message) Write-Host $Message -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "Warning: $Message" -ForegroundColor Yellow }
function Write-Failure { param([string]$Message) Write-Host $Message -ForegroundColor Red }

function Prompt-YesNo {
    param(
        [string]$Message,
        [switch]$DefaultYes
    )
    if ($script:AssumeYes) {
        Write-Info "$Message [auto-yes via -Yes]"
        return $true
    }
    if ($script:InputIsRedirected) {
        return $DefaultYes.IsPresent
    }
    $suffix = if ($DefaultYes) { "[Y/n]" } else { "[y/N]" }
    while ($true) {
        $response = Read-Host "$Message $suffix"
        if ([string]::IsNullOrWhiteSpace($response)) { return $DefaultYes.IsPresent }
        $response = $response.Trim().ToLowerInvariant()
        if ($response -in @("y", "yes")) { return $true }
        if ($response -in @("n", "no")) { return $false }
        Write-Warn "Please respond with y or n."
    }
}

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Ensure-NotAdmin {
    $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Failure "Error: This script should not be run as Administrator. Please run as a regular user."
        exit 1
    }
}

function Normalize-RepoPath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return "" }
    $p = $Path.Trim()
    if ($p -match '^[A-Za-z]:(?![\\/])') { $p = $p.Substring(0,2) + '\' + $p.Substring(2) }
    try { return [System.IO.Path]::GetFullPath($p) } catch { return $p }
}

$script:PreviousEnvMap = @{}
$script:PreviousEnvLoaded = $false

function Import-PreviousEnv {
    $envFile = Join-Path $LocalDir ".env"
    if (-not (Test-Path -LiteralPath $envFile)) { return @{} }
    $map = @{}
    Get-Content -LiteralPath $envFile | ForEach-Object {
        $line = $_.Trim()
        if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith("#")) { return }
        $pair = $line -split "=", 2
        if ($pair.Count -ne 2) { return }
        $key = $pair[0].Trim()
        $value = $pair[1].Trim()
        if ($value.StartsWith('"') -and $value.EndsWith('"')) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $map[$key] = $value
    }
    $script:PreviousEnvMap = $map
    $script:PreviousEnvLoaded = $true
    return $map
}

function Should-AutoFast {
    if (-not $script:PreviousEnvLoaded) { return $false }
    if (-not (Test-Path -LiteralPath (Join-Path $ScriptRoot ".git"))) { return $false }
    if (-not (Test-Path -LiteralPath (Join-Path $ScriptRoot "src\agilab"))) { return $false }
    if (-not (Test-Path -LiteralPath (Join-Path $ScriptRoot "src\agilab\core"))) { return $false }
    return $true
}

function Maybe-EnableAutoFast {
    if ($script:FastModeUserSet -or $script:FastMode) { return }
    if (-not $script:AutoFastDefault) {
        Write-Info "Auto fast mode disabled (AGILAB_AUTO_FAST=0 or -NoFast supplied)."
        return
    }
    if (-not (Should-AutoFast)) { return }

    $message = "Previous install detected. Enable fast mode (skip system deps, locale, offline extras)?"
    if ($script:AssumeYes -or $script:InputIsRedirected) {
        $script:FastMode = $true
        Write-Info "Fast mode enabled automatically (previous install detected)."
        return
    }
    if (Prompt-YesNo $message -DefaultYes) {
        $script:FastMode = $true
        Write-Info "Fast mode enabled (previous install detected)."
    } else {
        Write-Info "Fast mode declined; running full install."
    }
}

$CurrentPath = [System.IO.Path]::GetFullPath((Get-Location).Path)
$InstallPathNormalized = Normalize-RepoPath $InstallPath
if (-not $InstallPathNormalized) { $InstallPathNormalized = $InstallPath }
$InstallPathFull = [System.IO.Path]::GetFullPath($InstallPathNormalized)

$LocalDir = Join-Path $env:LOCALAPPDATA "agilab"
Ensure-Directory $LocalDir

$null = Import-PreviousEnv

if (-not $PSBoundParameters.ContainsKey('AppsRepository') -and $script:PreviousEnvMap.ContainsKey('APPS_REPOSITORY')) {
    $AppsRepository = $script:PreviousEnvMap['APPS_REPOSITORY']
}

$AppsRepositoryPath = if ($AppsRepository) { Normalize-RepoPath $AppsRepository } else { "" }
# New canonical var
$env:APPS_REPOSITORY = $AppsRepositoryPath
# Backward-compat for older tools that still read AGILAB_APPS_REPOSITORY
$env:AGILAB_APPS_REPOSITORY = $AppsRepositoryPath

$AgiPathFile = Join-Path $LocalDir ".agilab-path"

$LogDir = Join-Path $env:USERPROFILE "log\install_logs"
Ensure-Directory $LogDir
$LogFile = Join-Path $LogDir ("install_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

$script:AgiPythonVersion = $null
$script:AgiPythonFreeThreaded = $false

if (-not $script:ProvidedPythonVersion -and $script:PreviousEnvMap.ContainsKey('AGI_PYTHON_VERSION')) {
    $script:AgiPythonVersion = $script:PreviousEnvMap['AGI_PYTHON_VERSION']
}
if ($script:PreviousEnvMap.ContainsKey('AGI_PYTHON_FREE_THREADED')) {
    $script:AgiPythonFreeThreaded = $script:PreviousEnvMap['AGI_PYTHON_FREE_THREADED'] -eq "1"
}

$TranscriptStarted = $false

if (-not $env:UV_LINK_MODE) { $env:UV_LINK_MODE = "copy" }
$UvPreviewArgs = @("--preview-features", "extra-build-dependencies")
function Invoke-UvPreview {
    param([string[]]$Arguments)
    & uv @UvPreviewArgs @Arguments
}

function Remove-UnwantedPaths {
    Write-Info "Cleaning cached virtual environments and build artifacts..."
    Get-ChildItem -Path $CurrentPath -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $item = $_
        $name = $item.Name
        $remove = $false
        if ($item.PSIsContainer -and $name -in @(".venv", "build", "dist")) { $remove = $true }
        elseif (-not $item.PSIsContainer -and $name -eq "uv.lock") { $remove = $true }
        elseif ($name -like "*.egg-info") { $remove = $true }
        if ($remove) {
            try { Remove-Item -LiteralPath $item.FullName -Recurse -Force -ErrorAction Stop } catch {}
        }
    }
}

function Install-Dependencies {
    if ($script:FastMode) {
        Write-Warn "Fast mode: skipping system dependency checks."
        return
    }
    Write-Info "Step: Installing system dependencies..."
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Failure "uv CLI not found. Install uv (https://astral.sh/uv/) before re-running the installer."
        exit 1
    }
    Write-Info "Ensure Visual Studio Build Tools or MSVC are installed if native builds are required."
}

function Ensure-Locale {
    if ($script:FastMode) {
        Write-Warn "Fast mode: skipping locale configuration."
        return
    }
    Write-Info "Setting locale..."
    try {
        $culture = [System.Globalization.CultureInfo]::CurrentCulture
        if ($culture.Name -ne "en-US") {
            Write-Info ("Current culture is {0}; setting process locale variables to en_US.UTF-8." -f $culture.Name)
        } else {
            Write-Success "Locale en_US.UTF-8 is already active."
        }
    } catch {
        Write-Warn "Unable to determine current culture; setting locale variables for this session."
    }
    $env:LC_ALL = "en_US.UTF-8"
    $env:LANG = "en_US.UTF-8"
}

function Ensure-Uv {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Failure "uv CLI not found. Install uv (https://astral.sh/uv/) and re-run the installer."
        exit 1
    }
}

function Test-VisualStudio {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
        $vs2022 = & $vswhere -latest -version 17.0 -products * -property installationPath
        if ($vs2022) {
            Write-Success "Visual Studio 2022 detected at $vs2022"
        } else {
            Write-Warn "Visual Studio 2022 not found. Some packages may require C++ build tools."
        }
    } else {
        Write-Warn "vswhere.exe not found. Verify MSVC build tools are installed if builds fail."
    }
}

function Get-InstalledPythonSpecs {
    Invoke-UvPreview @("python", "list", "--only-installed") | ForEach-Object {
        $parts = $_ -split '\s+'
        if ($parts.Length -gt 0) { $parts[0] }
    }
}

function Get-VersionFromSpec {
    param([string]$Spec)
    if ([string]::IsNullOrWhiteSpace($Spec)) { return $null }
    $match = [regex]::Match($Spec, '([0-9]+\.[0-9]+\.[0-9]+)')
    if ($match.Success) { return $match.Groups[1].Value }
    $match = [regex]::Match($Spec, '([0-9]+\.[0-9]+)')
    if ($match.Success) { return $match.Groups[1].Value }
    return $null
}

function Resolve-PythonSpec {
    param([string]$Requested)
    if ([string]::IsNullOrWhiteSpace($Requested)) { $Requested = "3.13" }
    $pattern = [regex]::Escape($Requested)
    $installed = Get-InstalledPythonSpecs
    $match = $installed | Where-Object { $_ -match $pattern }
    if ($match) { return $match[0] }
    $available = Invoke-UvPreview @("python", "list") | ForEach-Object {
        $trim = $_.Trim()
        if ($trim) { ($trim -split '\s+')[0] } else { $null }
    } | Where-Object { $_ -and $_ -match $pattern -and $_ -notmatch "freethreaded" }
    if ($available) { return $available[0] }
    return $Requested
}

function Ensure-PythonRuntime {
    param(
        [string]$Requested,
        [switch]$SkipFreethreaded
    )
    if ([string]::IsNullOrWhiteSpace($Requested)) { $Requested = "3.13" }
    $spec = Resolve-PythonSpec $Requested
    $installedPythons = Get-InstalledPythonSpecs
    if ($installedPythons -notcontains $spec) {
        Write-Info "Installing $spec..."
        Invoke-UvPreview @("python", "install", $spec)
        $installedPythons = Get-InstalledPythonSpecs
        if ($installedPythons -contains $spec) {
            Write-Success "Python version ($spec) is now installed."
        } else {
            Write-Warn "Unable to confirm installation of $spec; continuing."
        }
    } else {
        Write-Success "Python version ($spec) is already installed."
    }

    $version = Get-VersionFromSpec $spec
    if (-not $version) { $version = $Requested }
    $script:AgiPythonVersion = $version
    $env:AGI_PYTHON_VERSION = $script:AgiPythonVersion

    if ($SkipFreethreaded) {
        $script:AgiPythonFreeThreaded = $false
        $env:AGI_PYTHON_FREE_THREADED = "0"
        Write-Warn "Fast mode: skipping freethreaded interpreter setup."
        return
    }

    $freethreadedEntry = (Invoke-UvPreview @("python", "list") | Where-Object { $_ -match [regex]::Escape($script:AgiPythonVersion) -and $_ -match "freethreaded" } | Select-Object -First 1)
    if ($freethreadedEntry) {
        $freethreadedId = ($freethreadedEntry -split '\s+')[0]
        $installedPythons = Get-InstalledPythonSpecs
        if ($installedPythons -notcontains $freethreadedId) {
            Write-Info "Installing $freethreadedId..."
            Invoke-UvPreview @("python", "install", $freethreadedId)
            Write-Success "Python version ($freethreadedId) is now installed."
        } else {
            Write-Success "Python version ($freethreadedId) is already installed."
        }
        $script:AgiPythonFreeThreaded = $true
        $env:AGI_PYTHON_FREE_THREADED = "1"
    } else {
        $script:AgiPythonFreeThreaded = $false
        $env:AGI_PYTHON_FREE_THREADED = "0"
        Write-Warn "Skipping freethreaded build for $($script:AgiPythonVersion) (not available)."
    }
}

function Select-PythonVersion {
    Write-Info "Choosing Python version..."
    $requested = $null

    if ($script:ProvidedPythonVersion) {
        $requested = $script:ProvidedPythonVersion
        Write-Info "Using Python version supplied via -PythonVersion: $requested"
    } elseif ($script:FastMode -and $script:AgiPythonVersion) {
        $requested = $script:AgiPythonVersion
        Write-Info "Fast mode: reusing Python version $requested."
    } elseif ($script:FastMode) {
        $requested = "3.13"
        Write-Info "Fast mode: defaulting to Python $requested."
    } elseif ($script:AgiPythonVersion) {
        if (Prompt-YesNo ("Reuse previously selected Python version $($script:AgiPythonVersion)?") -DefaultYes) {
            $requested = $script:AgiPythonVersion
        }
    }

    if ($requested) {
        Ensure-PythonRuntime -Requested $requested -SkipFreethreaded:$script:FastMode
        return
    }

    $requested = Read-Host "Enter Python major version [3.13]"
    if ([string]::IsNullOrWhiteSpace($requested)) {
        $requested = "3.13"
    }
    Write-Info "You selected Python version $requested"

    $availablePythonVersions = Invoke-UvPreview @("python", "list") | Where-Object { $_ -match $requested }
    if (-not $availablePythonVersions) {
        Write-Failure "No matching Python versions found for '$requested'"
        exit 1
    }

    $pythonArray = @()
    foreach ($line in $availablePythonVersions) {
        $trim = $line.Trim()
        if ($trim) { $pythonArray += $trim }
    }

    for ($i = 0; $i -lt $pythonArray.Count; $i++) {
        if ($pythonArray[$i] -match $requested) {
            Write-Success ("{0} - {1}" -f ($i + 1), $pythonArray[$i])
        } else {
            Write-Host ("{0} - {1}" -f ($i + 1), $pythonArray[$i])
        }
    }

    while ($true) {
        $selection = Read-Host "Enter the number of the Python version you want to use (default: 1)"
        if ([string]::IsNullOrWhiteSpace($selection)) { $selection = "1" }
        if ($selection -as [int]) {
            $index = [int]$selection
            if ($index -ge 1 -and $index -le $pythonArray.Count) { break }
        }
        Write-Warn "Invalid selection. Please try again."
    }

    $chosenPython = ($pythonArray[[int]$selection - 1] -split '\s+')[0]
    Ensure-PythonRuntime -Requested $chosenPython -SkipFreethreaded:$false
}

function Backup-ExistingProject {
    if ((Test-Path -LiteralPath $InstallPathFull) -and
        (Test-Path -LiteralPath (Join-Path $InstallPathFull "zip-agi.py")) -and
        (-not $InstallPathFull.Equals($CurrentPath, [System.StringComparison]::OrdinalIgnoreCase))) {
        Write-Warn "Existing project found at $InstallPathFull with zip-agi.py present."
        $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $backupFile = "${InstallPathFull}_backup_$timestamp.zip"
        Write-Warn "Creating backup: $backupFile"

        $zipper = Join-Path $InstallPathFull "zip-agi.py"
        $nodeProject = Join-Path $InstallPathFull "agilab\node"
        $backupSuccess = $false

        if (Test-Path -LiteralPath $nodeProject) {
            Invoke-UvPreview @("run", "--project", $nodeProject, "python", $zipper, "--dir2zip", $InstallPathFull, "--zipfile", $backupFile)
            if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $backupFile)) {
                $backupSuccess = $true
                Write-Success "Backup created successfully at $backupFile."
            }
        }

        if (-not $backupSuccess) {
            Write-Warn "Automatic backup failed. Creating fallback archive..."
            try {
                if (Test-Path -LiteralPath $backupFile) { Remove-Item -LiteralPath $backupFile -Force }
                Compress-Archive -LiteralPath $InstallPathFull -DestinationPath $backupFile -Force
                Write-Warn "Fallback backup created at $backupFile."
                $backupSuccess = $true
            } catch {
                Write-Failure "Failed to create backup using fallback strategy: $_"
                exit 1
            }
        }

        if ($backupSuccess) {
            Write-Warn "Removing existing project directory..."
            try {
                Remove-Item -LiteralPath $InstallPathFull -Recurse -Force
            } catch {
                Write-Failure "Failed to remove existing project directory: $_"
                exit 1
            }
        }
    } else {
        Write-Warn "No valid existing project found or install dir is same as current directory. Skipping backup."
    }
}

function Copy-ProjectFiles {
    if ($InstallPathFull.Equals($CurrentPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        Write-Info "Using current directory as install directory; no copy needed."
        return
    }
    if (-not (Test-Path -LiteralPath (Join-Path $CurrentPath "src"))) {
        Write-Failure "Source directory 'src' not found. Exiting."
        exit 1
    }
    Write-Info "Copying project files to install directory..."
    Ensure-Directory $InstallPathFull
    try {
        Get-ChildItem -Path $CurrentPath -Force | ForEach-Object {
            $item = $_
            if ($item.FullName.Equals($InstallPathFull, [System.StringComparison]::OrdinalIgnoreCase)) { return }
            Copy-Item -LiteralPath $item.FullName -Destination $InstallPathFull -Recurse -Force
        }
    } catch {
        Write-Failure "Failed to copy project files: $_"
        exit 1
    }
}

function Write-AgiPath {
    $agilabRoot = Join-Path $InstallPathFull "src\agilab"
    $agilabPath = Join-Path $env:USERPROFILE ".agilab"
    Ensure-Directory $agilabPath
    $agilabRoot | Set-Content -Encoding UTF8 -Path $AgiPathFile
    [Environment]::SetEnvironmentVariable('AGI_ROOT', $agilabRoot, [EnvironmentVariableTarget]::User)
    Write-Success "Installation root path recorded in $AgiPathFile"
}

function Update-Environment {
    $envFile = Join-Path $LocalDir ".env"
    if (Test-Path -LiteralPath $envFile) {
        Remove-Item -LiteralPath $envFile -Force
    }
    $openAiValue = if ($null -eq $OpenaiApiKey) { "" } else { $OpenaiApiKey }
    $clusterValue = if ($null -eq $ClusterSshCredentials) { "" } else { $ClusterSshCredentials }
    $pythonValue = if ($null -eq $script:AgiPythonVersion) { "" } else { $script:AgiPythonVersion }
    $freethreadedValue = if ($script:AgiPythonFreeThreaded) { "1" } else { "0" }
    $appsRepoValue = if ($env:APPS_REPOSITORY) { $env:APPS_REPOSITORY } else { "" }
    $lines = @(
        ('OPENAI_API_KEY="{0}"' -f $openAiValue),
        ('CLUSTER_CREDENTIALS="{0}"' -f $clusterValue),
        ('AGI_PYTHON_VERSION="{0}"' -f $pythonValue),
        ('AGI_PYTHON_FREE_THREADED="{0}"' -f $freethreadedValue),
        ('APPS_REPOSITORY="{0}"' -f $appsRepoValue)
    )
    $lines | Set-Content -Encoding UTF8 -Path $envFile
    Write-Success "Environment updated in $envFile"
}

function Write-EnvValues {
    $sharedEnv = Join-Path $LocalDir ".env"
    if (-not (Test-Path -LiteralPath $sharedEnv)) {
        Write-Failure "Error: $sharedEnv does not exist."
        return $false
    }

    $agilabDir = Join-Path $env:USERPROFILE ".agilab"
    Ensure-Directory $agilabDir
    $agilabEnv = Join-Path $agilabDir ".env"

    $kvMap = @{}
    if (Test-Path -LiteralPath $agilabEnv) {
        Get-Content -LiteralPath $agilabEnv | ForEach-Object {
            $line = $_.Trim()
            if ($line -eq "" -or $line.StartsWith("#")) { return }
            $pair = $line -split "=", 2
            if ($pair.Count -eq 2) {
                $kvMap[$pair[0]] = $pair[1]
            }
        }
    }

    Get-Content -LiteralPath $sharedEnv | ForEach-Object {
        $line = $_.Trim()
        if ($line -eq "" -or $line.StartsWith("#")) { return }
        $pair = $line -split "=", 2
        if ($pair.Count -eq 2) {
            $kvMap[$pair[0]] = $pair[1]
        }
    }

    $content = $kvMap.GetEnumerator() | Sort-Object Name | ForEach-Object { "{0}={1}" -f $_.Name, $_.Value }
    $content | Set-Content -LiteralPath $agilabEnv -Encoding UTF8
    Write-Success ".env file updated."
    return $true
}

function Install-Core {
    $frameworkDir = Join-Path $InstallPathFull "src\agilab\core"
    if (-not (Test-Path -LiteralPath $frameworkDir)) {
        Write-Failure "Framework directory not found at $frameworkDir"
        exit 1
    }
    Write-Info "Installing Framework..."
    Push-Location $frameworkDir
    try {
        & ".\install.ps1"
    } finally {
        Pop-Location
    }
}

function Invoke-AppPytest {
    param([string]$AppsRoot)
    if (-not (Test-Path -LiteralPath $AppsRoot)) {
        Write-Warn "Apps directory not found at $AppsRoot; skipping pytest."
        return $true
    }
    $status = $true
    Push-Location $AppsRoot
    try {
        $apps = Get-ChildItem -Directory -Filter "*_project"
        if (-not $apps) {
            Write-Warn "No app directories with '*_project' found under $AppsRoot; skipping pytest."
            return $true
        }
        foreach ($app in $apps) {
            Write-Info ("[pytest] {0}" -f $app.Name)
            Push-Location $app.FullName
            try {
                Invoke-UvPreview @("run", "--no-sync", "-p", $script:AgiPythonVersion, "--project", ".", "pytest") | Out-Host
                $exitCode = $LASTEXITCODE
                if ($exitCode -eq 0) {
                    Write-Success ("pytest succeeded for '{0}'." -f $app.Name)
                } elseif ($exitCode -eq 5) {
                    Write-Warn ("No tests collected for '{0}'." -f $app.Name)
                } else {
                    Write-Warn ("pytest failed for '{0}' (exit code {1})." -f $app.Name, $exitCode)
                    $status = $false
                }
            } finally {
                Pop-Location
            }
        }
    } finally {
        Pop-Location
    }
    return $status
}

function Install-Apps {
    param([switch]$RunPytest)
    $dir = Join-Path $InstallPathFull "src\agilab"
    if (-not (Test-Path -LiteralPath $dir)) {
        Write-Warn "Apps directory not found at $dir; skipping app install."
        return $false
    }
    Write-Info "Installing Apps..."
    $agilabPublic = Join-Path $InstallPathFull "src\agilab"
    $env:APPS_DEST_BASE = Join-Path $agilabPublic "apps"
    $env:PAGES_DEST_BASE = Join-Path $agilabPublic "apps-pages"
    Push-Location $dir
    try {
        & ".\install_apps.ps1"
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "install_apps.ps1 exited with code $LASTEXITCODE"
            return $false
        }
    } catch {
        Write-Warn "install_apps.ps1 failed: $_"
        return $false
    } finally {
        Pop-Location
        Remove-Item Env:APPS_DEST_BASE -ErrorAction SilentlyContinue
        Remove-Item Env:PAGES_DEST_BASE -ErrorAction SilentlyContinue
    }
    if ($RunPytest) {
        $appsRoot = Join-Path $agilabPublic "apps"
        if (-not (Invoke-AppPytest -AppsRoot $appsRoot)) {
            return $false
        }
    }
    return $true
}

function Install-PyCharmScript {
    $workspace = Join-Path $InstallPathFull ".idea\workspace.xml"
    if (Test-Path -LiteralPath $workspace) {
        Remove-Item -LiteralPath $workspace -Force
    }
    Write-Info "Patching PyCharm workspace.xml interpreter settings..."
    Push-Location $InstallPathFull
    try {
        Invoke-UvPreview @("run", "-p", $script:AgiPythonVersion, "python", "pycharm/setup_pycharm.py")
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "pycharm/setup_pycharm.py failed or not found; continuing."
        }
    } catch {
        Write-Warn "pycharm/setup_pycharm.py failed or not found; continuing."
    } finally {
        Pop-Location
    }
}

function Refresh-LaunchMatrix {
    if ($script:FastMode) {
        Write-Warn "Fast mode: skipping Launch Matrix refresh."
        return
    }
    $tool = Join-Path $InstallPathFull "tools\refresh_launch_matrix.py"
    if (-not (Test-Path -LiteralPath $tool)) {
        Write-Warn "tools/refresh_launch_matrix.py not found; skipping matrix refresh."
        return
    }
    Write-Info "Refreshing Launch Matrix from .idea/runConfigurations..."
    Push-Location $InstallPathFull
    try {
        Invoke-UvPreview @("run", "-p", $script:AgiPythonVersion, "python", "tools/refresh_launch_matrix.py", "--inplace")
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Launch Matrix updated in AGENTS.md."
        } else {
            Write-Warn "Launch Matrix refresh skipped (tooling not available)."
        }
    } catch {
        Write-Warn "Launch Matrix refresh skipped (tooling not available)."
    } finally {
        Pop-Location
    }
}

function Install-Enduser {
    if ($script:FastMode) {
        Write-Warn "Fast mode: skipping enduser packaging."
        return
    }
    $scriptPath = Join-Path $InstallPathFull "tools\install_enduser.ps1"
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        Write-Warn "tools/install_enduser.ps1 not found; skipping enduser packaging."
        return
    }
    if ($Source -ne "local") {
        Write-Warn "Source '$Source' not supported by install_enduser.ps1 on Windows; skipping."
        return
    }
    if (-not (Prompt-YesNo "Run enduser packaging step (may fetch Python dependencies)?" -DefaultYes)) {
        Write-Warn "Skipping enduser packaging at user request."
        return
    }
    Write-Info "Installing agilab (endusers)..."
    Push-Location (Join-Path $InstallPathFull "tools")
    try {
        & $scriptPath
        if ($LASTEXITCODE -eq 0) {
            Write-Success "agilab (enduser) installation complete."
        } else {
            Write-Warn "install_enduser.ps1 exited with code $LASTEXITCODE"
        }
    } catch {
        Write-Warn "install_enduser.ps1 failed: $_"
    } finally {
        Pop-Location
    }
}

function Install-OfflineExtra {
    if ($script:FastMode) {
        Write-Warn "Fast mode: skipping offline assistant extras."
        return
    }
    $pyver = $script:AgiPythonVersion
    if (-not $pyver) { return }
    $normalized = $pyver -replace '\+freethreaded', ''
    try {
        $versionObj = [Version]$normalized
    } catch {
        Write-Warn "Could not parse Python version '$pyver'; skipping GPT-OSS offline assistant installation."
        return
    }
    if ($versionObj.Major -gt 3 -or ($versionObj.Major -eq 3 -and $versionObj.Minor -ge 12)) {
        if (-not (Prompt-YesNo "Install offline assistant dependencies (GPT-OSS + mistral:instruct)?")) {
            Write-Warn "Skipping offline assistant packages."
            return
        }
        Write-Info "Installing offline assistant dependencies (GPT-OSS + mistral:instruct)..."
        Push-Location $InstallPathFull
        try {
            Invoke-UvPreview @("pip", "install", ".[offline]") | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Success "Offline assistant packages installed."
            } else {
                Write-Warn "Unable to install offline extras (pip install .[offline]). Install them manually when network access is available."
            }
            $ensureSpecs = @(
                "transformers>=4.57.0",
                "torch>=2.8.0",
                "accelerate>=0.34.2",
                "universal-offline-ai-chatbot>=0.1.0"
            )
            foreach ($spec in $ensureSpecs) {
                $pkg = $spec.Split(">=")[0]
                Invoke-UvPreview @("pip", "show", $pkg) | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    Invoke-UvPreview @("pip", "install", $spec) | Out-Null
                    if ($LASTEXITCODE -eq 0) {
                        Write-Success "Installed $spec for offline assistant support."
                    } else {
                        Write-Warn "Failed to install $spec. Install it manually if you plan to use the $pkg backend."
                    }
                }
            }
        } finally {
            Pop-Location
        }
    } else {
        Write-Warn "Skipping GPT-OSS offline assistant (requires Python >=3.12)."
    }
}

function Seed-MistralPdfs {
    if ($script:FastMode) {
        Write-Warn "Fast mode: skipping PDF seeding for offline assistants."
        return
    }
    Write-Info "Seeding sample PDFs for mistral:instruct (optional)..."
    $dest = Join-Path $env:USERPROFILE ".agilab\mistral_offline\data"
    Ensure-Directory $dest

    $src1 = Join-Path $InstallPathFull "src\agilab\core\agi-env\src\agi_env\resources\mistral_offline\data"
    $src2 = Join-Path $InstallPathFull "src\agilab\core\agi-env\src\agi_env\resources\.agilab\pdfs"

    $copied = $false
    foreach ($src in @($src1, $src2)) {
        if (Test-Path -LiteralPath $src) {
            Get-ChildItem -Path $src -Filter *.pdf -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
                Copy-Item -LiteralPath $_.FullName -Destination $dest -Force
                $copied = $true
            }
        }
    }

    if ($copied) {
        Write-Success "Seeded PDFs into $dest"
    } else {
        Write-Warn "No sample PDFs found in resources; skipping seeding."
    }
}

function Setup-MistralOffline {
    Write-Warn "Automatic Ollama setup is not available on Windows. Install Ollama manually and pull 'mistral:instruct' if needed."
}

Maybe-EnableAutoFast

Ensure-NotAdmin

try {
    Start-Transcript -Path $LogFile | Out-Null
    $TranscriptStarted = $true

#    Remove-UnwantedPaths

    Test-VisualStudio
    Install-Dependencies
    Ensure-Uv
    Ensure-Locale

    Select-PythonVersion
    Backup-ExistingProject
    Copy-ProjectFiles
    Write-AgiPath
    Update-Environment
    if (-not (Write-EnvValues)) {
        exit 1
    }

    Install-Core

    if ($InstallApps) {
        $appsInstalled = Install-Apps -RunPytest:$TestApps
        if (-not $appsInstalled) {
            Write-Warn "install_apps.ps1 failed; continuing with PyCharm setup."
            Install-PyCharmScript
            Refresh-LaunchMatrix
        } else {
            Install-PyCharmScript
            Refresh-LaunchMatrix
            Install-Enduser
            Install-OfflineExtra
            Seed-MistralPdfs
            Setup-MistralOffline
            Write-Success "Installation complete!"
        }
    } else {
        Write-Warn "App installation skipped (use -InstallApps to enable)."
        Install-PyCharmScript
        Refresh-LaunchMatrix
        Install-Enduser
        Install-OfflineExtra
        Seed-MistralPdfs
        Setup-MistralOffline
        Write-Success "Installation complete (apps skipped)."
    }
} finally {
    if ($TranscriptStarted) {
        try { Stop-Transcript | Out-Null } catch {}
    }
}
