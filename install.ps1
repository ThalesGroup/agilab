[CmdletBinding()]
param(
    [string]$ClusterSshCredentials,
    [string]$OpenaiApiKey,
    [string]$InstallPath = (Get-Location).Path,
    [string]$AppsRepository,
    [ValidateSet("local", "pypi", "testpypi")]
    [string]$Source = "local",
    [switch]$InstallApps,
    [switch]$TestApps,
    [string]$AgiShareDir,
    [string]$AgiLocalDir,
    [string]$InstallAppsList,
    [switch]$NonInteractive
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$NonInteractiveMode = $NonInteractive.IsPresent

if ($TestApps) {
    $InstallApps = $true
}
if ($InstallAppsList) {
    $InstallApps = $true
}

function Write-Info { param([string]$Message) Write-Host $Message -ForegroundColor Blue }
function Write-Success { param([string]$Message) Write-Host $Message -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "Warning: $Message" -ForegroundColor Yellow }
function Write-Failure { param([string]$Message) Write-Host $Message -ForegroundColor Red }

function Check-Internet {
    Write-Info "Checking internet connectivity..."
    try {
        $null = Invoke-WebRequest -Uri "https://www.google.com" -TimeoutSec 3 -UseBasicParsing
        Write-Success "Internet connection is OK."
        $global:AGI_INTERNET_ON = 1
    } catch {
        Write-Warn "No internet connection detected."
        $global:AGI_INTERNET_ON = 0
    }
}

function Prompt-YesNo {
    param(
        [string]$Message,
        [switch]$DefaultYes
    )
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

$CurrentPath = [System.IO.Path]::GetFullPath((Get-Location).Path)
$InstallPathFull = [System.IO.Path]::GetFullPath($InstallPath)

function Normalize-RepoPath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return "" }
    $p = $Path.Trim()
    if ($p -match '^[A-Za-z]:(?![\\/])') { $p = $p.Substring(0,2) + '\\' + $p.Substring(2) }
    try { return [System.IO.Path]::GetFullPath($p) } catch { return $p }
}

function Normalize-UserPath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return "" }
    $expanded = [Environment]::ExpandEnvironmentVariables($Path.Trim())
    if ($expanded.StartsWith("~")) {
        $expanded = $expanded -replace '^~', $env:USERPROFILE
    }
    if (-not [System.IO.Path]::IsPathRooted($expanded)) {
        $expanded = Join-Path $env:USERPROFILE $expanded
    }
    try {
        $fullPath = [System.IO.Path]::GetFullPath($expanded)
        return $fullPath.Replace('\', '/')
    } catch {
        return $expanded.Replace('\', '/')
    }
}

$AppsRepositoryPath = if ($AppsRepository) { Normalize-RepoPath $AppsRepository } else { "" }
$env:APPS_REPOSITORY = $AppsRepositoryPath
$env:AGILAB_APPS_REPOSITORY = $AppsRepositoryPath

$LocalDir = Join-Path $env:LOCALAPPDATA "agilab"
Ensure-Directory $LocalDir
$AgiPathFile = Join-Path $LocalDir ".agilab-path"

$DefaultShareDir = if ($AgiShareDir) { $AgiShareDir } elseif ($env:AGI_SHARE_DIR) { $env:AGI_SHARE_DIR } else { Join-Path $env:USERPROFILE "clustershare" }
function Get-EnvValueFromFile {
    param([string]$FilePath, [string]$Key)
    if (-not (Test-Path -LiteralPath $FilePath)) { return "" }
    $line = Select-String -Path $FilePath -Pattern ("^{0}=" -f [regex]::Escape($Key)) | Select-Object -Last 1
    if ($null -eq $line) { return "" }
    $value = $line.Line.Split("=",2)[1].Trim('"')
    return $value
}
if (-not $DefaultShareDir) {
    $DefaultShareDir = Get-EnvValueFromFile (Join-Path $env:USERPROFILE ".agilab\.env") "AGI_SHARE_DIR"
}
if (-not $DefaultShareDir) {
    $DefaultShareDir = Get-EnvValueFromFile (Join-Path $InstallPathFull ".agilab\.env") "AGI_SHARE_DIR"
}
$DefaultLocalShare = if ($AgiLocalDir) { $AgiLocalDir }
    elseif ($env:AGI_LOCAL_DIR) { $env:AGI_LOCAL_DIR }
    elseif ($env:AGI_LOCAL_SHARE) { $env:AGI_LOCAL_SHARE }
    else { Join-Path $env:USERPROFILE "localshare" }

function Test-ShareMounted {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    try {
        $resolved = Resolve-Path -LiteralPath $Path -ErrorAction Stop
        return $true
    } catch {
        # For drive-letter paths, ensure the drive is present.
        $drive = [System.IO.Path]::GetPathRoot($Path)
        if ($drive -and (Get-PSDrive -Name $drive.TrimEnd('\','/') -ErrorAction SilentlyContinue)) {
            return (Test-Path -LiteralPath $Path)
        }
        # For UNC paths, a simple Test-Path is the best we can do without mounts.
        if ($Path.StartsWith("\\")) {
            return (Test-Path -LiteralPath $Path)
        }
        return $false
    }
}

function Ensure-ShareDir {
    param(
        [string]$ShareDir,
        [string]$FallbackDir,
        [switch]$NonInteractiveMode,
        [string]$ClusterCredentials
    )
    if ([string]::IsNullOrWhiteSpace($ShareDir)) {
        if ($NonInteractiveMode) {
            if (-not [string]::IsNullOrWhiteSpace($ClusterCredentials)) {
                Write-Failure "AGI_SHARE_DIR not provided and cluster credentials specified; cannot proceed in non-interactive mode."
                exit 1
            }
            $ShareDir = $FallbackDir
        } else {
            $ShareDir = Read-Host "Enter AGI_SHARE_DIR path (or press Enter to abort)"
            if ([string]::IsNullOrWhiteSpace($ShareDir)) {
                Write-Failure "AGI_SHARE_DIR not provided. Aborting."
                exit 1
            }
        }
    }

    $ShareDir = Normalize-UserPath $ShareDir
    $FallbackDir = Normalize-UserPath $FallbackDir

    if (-not [string]::IsNullOrWhiteSpace($ShareDir)) {
        Write-Info ("AGI_SHARE_DIR resolved to: {0}" -f $ShareDir)
    }

    if (Test-ShareMounted -Path $ShareDir) {
        $env:AGI_SHARE_DIR = $ShareDir
        if (-not $env:AGI_LOCAL_DIR) { $env:AGI_LOCAL_DIR = $FallbackDir }
        return
    }

    if ($NonInteractiveMode) {
        if (-not [string]::IsNullOrWhiteSpace($ClusterCredentials)) {
            Write-Failure "$ShareDir is not mounted. Cluster installs require the shared path; aborting (non-interactive)."
            exit 1
        }
        Write-Warn ("AGI_SHARE_DIR {0} unavailable; non-interactive mode: using fallback {1}." -f $ShareDir, $FallbackDir)
        Ensure-Directory $FallbackDir
        $env:AGI_LOCAL_DIR = $FallbackDir
        $env:AGI_SHARE_DIR = $FallbackDir
        return
    }

    Write-Warn "AGI_SHARE_DIR is unavailable at $ShareDir."
    Write-Host "Choose an option:" -ForegroundColor Yellow
    Write-Host "  1) Use local fallback at $FallbackDir"
    Write-Host "  2) Wait for $ShareDir to be mounted (mandatory for cluster installs; timeout 120s)"
    $choice = Read-Host "Enter 1 or 2 (default: 1)"
    if ($choice -eq "" -or $choice -eq "1") {
        Ensure-Directory $FallbackDir
        $env:AGI_LOCAL_DIR = $FallbackDir
        $env:AGI_SHARE_DIR = $FallbackDir
        Write-Success "Using local fallback AGI_LOCAL_DIR=$env:AGI_LOCAL_DIR"
    }
    elseif ($choice -eq "2") {
        Write-Info "Waiting for $ShareDir to become available (timeout 120s)..."
        $waited = 0
        while ($waited -lt 120) {
            if (Test-Path -LiteralPath $ShareDir) {
                $env:AGI_SHARE_DIR = $ShareDir
                Write-Success "$ShareDir is available. Continuing."
                return
            }
            Start-Sleep -Seconds 5
            $waited += 5
        }
        Write-Failure "$ShareDir did not appear within 120s. Aborting."
        exit 1
    }
    else {
        Write-Failure "Please mount $ShareDir and re-run the installer."
        exit 1
    }
}

$LogDir = Join-Path $env:USERPROFILE "log\install_logs"
Ensure-Directory $LogDir
$LogFile = Join-Path $LogDir ("install_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

$script:AgiPythonVersion = $null
$script:AgiPythonFreeThreaded = $false
$TranscriptStarted = $false

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
    Write-Info "Step: Installing system dependencies..."
    Write-Warn "Automatic dependency installation is disabled for restricted networks."
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Failure "uv CLI not found. Install uv (https://astral.sh/uv/) before re-running the installer."
        exit 1
    }
    Write-Warn "Ensure Visual Studio Build Tools or MSVC are installed if native builds are required."
}

$ResolvedShareDir = Normalize-UserPath $DefaultShareDir
$ResolvedLocalShare = Normalize-UserPath $DefaultLocalShare
if (-not $ResolvedLocalShare) {
    $ResolvedLocalShare = Join-Path $env:USERPROFILE "localshare"
}

if (-not $NonInteractiveMode) {
    $shareDisplay = if ($ResolvedShareDir) { $ResolvedShareDir } else { "<unset>" }
    $shareInput = Read-Host "AGI_SHARE_DIR is '$shareDisplay'. Press Enter to accept or type a new path"
    if (-not [string]::IsNullOrWhiteSpace($shareInput)) {
        $ResolvedShareDir = Normalize-UserPath $shareInput
    }
    $localDisplay = if ($ResolvedLocalShare) { $ResolvedLocalShare } else { "<unset>" }
    $localInput = Read-Host "AGI_LOCAL_DIR fallback is '$localDisplay'. Press Enter to accept or type a new path"
    if (-not [string]::IsNullOrWhiteSpace($localInput)) {
        $ResolvedLocalShare = Normalize-UserPath $localInput
    }
} elseif (-not $ResolvedShareDir) {
    $ResolvedShareDir = $ResolvedLocalShare
}

Ensure-ShareDir -ShareDir $ResolvedShareDir -FallbackDir $ResolvedLocalShare -NonInteractiveMode:$NonInteractiveMode -ClusterCredentials $ClusterSshCredentials

function Ensure-Locale {
    Write-Info "Setting locale..."
    try {
        $culture = [System.Globalization.CultureInfo]::CurrentCulture
        if ($culture.Name -ne "en-US") {
            Write-Warn ("Current culture is {0}; setting process locale variables to en_US.UTF-8." -f $culture.Name)
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

function Select-PythonVersion {
    Write-Info "Choosing Python version..."
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
    $installedPythons = Invoke-UvPreview @("python", "list", "--only-installed") | ForEach-Object { ($_ -split '\s+')[0] }

    if ($installedPythons -notcontains $chosenPython) {
        Write-Info "Installing $chosenPython..."
        Invoke-UvPreview @("python", "install", $chosenPython)
        Write-Success "Python version ($chosenPython) is now installed."
    } else {
        Write-Success "Python version ($chosenPython) is already installed."
    }

    $versionMatch = [regex]::Match($chosenPython, '([0-9]+\.[0-9]+\.[0-9]+)')
    if ($versionMatch.Success) {
        $script:AgiPythonVersion = $versionMatch.Groups[1].Value
    } else {
        $script:AgiPythonVersion = $chosenPython
    }

    $freethreadedEntry = (Invoke-UvPreview @("python", "list") | Where-Object { $_ -match "$($script:AgiPythonVersion)" -and $_ -match "freethreaded" } | Select-Object -First 1)
    if ($freethreadedEntry) {
        $freethreadedId = ($freethreadedEntry -split '\s+')[0]
        if ($installedPythons -notcontains $freethreadedId) {
            Write-Info "Installing $freethreadedId..."
            Invoke-UvPreview @("python", "install", $freethreadedId)
            Write-Success "Python version ($freethreadedId) is now installed."
        } else {
            Write-Success "Python version ($freethreadedId) is already installed."
        }
        $script:AgiPythonFreeThreaded = $true
    } else {
        $script:AgiPythonFreeThreaded = $false
        Write-Warn "Skipping freethreaded build for $($script:AgiPythonVersion) (not available)."
    }

    $env:AGI_PYTHON_VERSION = $script:AgiPythonVersion
    $env:AGI_PYTHON_FREE_THREADED = if ($script:AgiPythonFreeThreaded) { "1" } else { "0" }
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
        ('APPS_REPOSITORY="{0}"' -f $appsRepoValue.Replace('\', '/')),
        ('AGI_INTERNET_ON="{0}"' -f $AGI_INTERNET_ON),
        ('AGI_CLUSTER_SHARE="{0}"' -f $ResolvedShareDir),
        ('AGI_LOCAL_SHARE="{0}"' -f $ResolvedLocalShare)
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

function Get-BuiltinAppNames {
    $builtinRoot = Join-Path $InstallPathFull "src\agilab\apps\builtin"
    if (-not (Test-Path -LiteralPath $builtinRoot)) { return @() }
    return Get-ChildItem -LiteralPath $builtinRoot -Directory -Filter '*_project' -ErrorAction SilentlyContinue |
        ForEach-Object { $_.Name }
}

function Get-RepositoryAppNames {
    $appsRoot = Join-Path $InstallPathFull "src\agilab\apps"
    if (-not (Test-Path -LiteralPath $appsRoot)) { return @() }
    return Get-ChildItem -LiteralPath $appsRoot -Directory -Filter '*_project' -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notlike "*\apps\builtin\*" } |
        ForEach-Object { $_.Name }
}

function Get-AllAppNames {
    $all = @()
    $all += Get-RepositoryAppNames
    $all += Get-BuiltinAppNames
    return $all | Sort-Object -Unique
}

function Resolve-AppSelection {
    param([string]$Selector)
    if ([string]::IsNullOrWhiteSpace($Selector)) { return @() }
    $value = $Selector.Trim()
    $lower = $value.ToLowerInvariant()
    if ($lower -in @("all", "__agilab_all_apps__")) {
        return Get-AllAppNames
    }
    if ($lower -in @("builtin", "built-in", "__agilab_builtin_apps__")) {
        return Get-BuiltinAppNames
    }
    return ($value -split '[,\s;]+' | Where-Object { $_ -ne '' })
}

function Install-Apps {
    param(
        [switch]$RunPytest,
        [string[]]$AppFilter
    )
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
        if ($AppFilter -and $AppFilter.Count -gt 0) {
            $env:BUILTIN_APPS_OVERRIDE = ($AppFilter -join ',')
        }
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
        Remove-Item Env:BUILTIN_APPS_OVERRIDE -ErrorAction SilentlyContinue
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

function Invoke-RepositoryCoverage {
    param([string]$RepoRoot)
    if (-not $script:AgiPythonVersion) {
        Write-Warn "Python version not available; skipping repository coverage."
        return
    }
    if (-not (Test-Path -LiteralPath $RepoRoot)) {
        Write-Warn "Repository root '$RepoRoot' not found; skipping repository coverage."
        return
    }

    $corePaths = @(
        Join-Path $RepoRoot "src\agilab\core\agi-env\src",
        Join-Path $RepoRoot "src\agilab\core\agi-node\src",
        Join-Path $RepoRoot "src\agilab\core\agi-cluster\src"
    ) | Where-Object { Test-Path -LiteralPath $_ }

    $separator = [System.IO.Path]::PathSeparator
    $originalPythonPath = $env:PYTHONPATH
    $env:PYTHONPATH = (($corePaths + @($originalPythonPath)) | Where-Object { $_ -and $_.Trim() }) -join $separator

    try {
        $appsRoot = Join-Path $RepoRoot "src\agilab\apps"
        $appTestDirs = @()
        if (Test-Path -LiteralPath $appsRoot) {
            Get-ChildItem -Path $appsRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                $testDir = Join-Path $_.FullName "test"
                if (Test-Path -LiteralPath $testDir) {
                    $appTestDirs += $testDir
                }
            }
        }

        if ($appTestDirs.Count -gt 0) {
            Write-Info "Running builtin and repository app tests with coverage..."
            Push-Location $RepoRoot
            try {
                $pytestArgs = @(
                    "run", "-p", $script:AgiPythonVersion, "--no-sync", "--preview-features", "python-upgrade",
                    "pytest"
                ) + $appTestDirs + @("--maxfail=1", "--cov=src/agilab/apps", "--cov-report=term-missing", "--cov-report=xml", "--cov-append")
                Invoke-UvPreview $pytestArgs | Out-Host
                $rc = $LASTEXITCODE
                if ($rc -eq 5) {
                    Write-Warn "No tests collected for repository app suite."
                } elseif ($rc -ne 0) {
                    Write-Warn "Coverage run failed for repository app suite (exit code $rc)."
                }
            } finally {
                Pop-Location
            }
        } else {
            Write-Info "No repository app test directories detected; skipping app coverage."
        }

        $pagesRoot = Join-Path $RepoRoot "src\agilab\apps-pages"
        $pageTestDirs = @()
        if (Test-Path -LiteralPath $pagesRoot) {
            Get-ChildItem -Path $pagesRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                $testDir = Join-Path $_.FullName "test"
                if (Test-Path -LiteralPath $testDir) {
                    $pageTestDirs += $testDir
                }
            }
        }

        if ($pageTestDirs.Count -gt 0) {
            Write-Info "Running apps-pages tests with coverage..."
            Push-Location $RepoRoot
            try {
                $pytestArgs = @(
                    "run", "-p", $script:AgiPythonVersion, "--no-sync", "--preview-features", "python-upgrade",
                    "pytest"
                ) + $pageTestDirs + @("--maxfail=1", "--cov=src/agilab/apps-pages", "--cov-report=term-missing", "--cov-report=xml", "--cov-append")
                Invoke-UvPreview $pytestArgs | Out-Host
                $rc = $LASTEXITCODE
                if ($rc -eq 5) {
                    Write-Warn "No tests collected for apps-pages suite."
                } elseif ($rc -ne 0) {
                    Write-Warn "Coverage run failed for apps-pages suite (exit code $rc)."
                }
            } finally {
                Pop-Location
            }
        } else {
            Write-Info "No apps-pages test directories detected; skipping apps-pages coverage."
        }
    }
    finally {
        $env:PYTHONPATH = $originalPythonPath
    }
}

Ensure-NotAdmin

try {
    Start-Transcript -Path $LogFile | Out-Null
    $TranscriptStarted = $true

#    Remove-UnwantedPaths
    Check-Internet
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
        $customAppSelection = @()
        if ($InstallAppsList) {
            $customAppSelection = Resolve-AppSelection -Selector $InstallAppsList
            if ($customAppSelection.Count -eq 0) {
                Write-Warn ("InstallAppsList '{0}' did not match any apps; falling back to interactive selection." -f $InstallAppsList)
            }
        }
        $appsInstalled = Install-Apps -RunPytest:$TestApps -AppFilter $customAppSelection
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

    Invoke-RepositoryCoverage -RepoRoot $InstallPathFull
} finally {
    if ($TranscriptStarted) {
        try { Stop-Transcript | Out-Null } catch {}
    }
}
