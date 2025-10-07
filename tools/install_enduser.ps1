$cwd = Get-Location

# Create dist target directory
$targetDist = Join-Path $cwd "..\agi-pypi"
[System.IO.Directory]::CreateDirectory("$targetDist") | Out-Null

# Remove old files
Remove-Item -Force "$targetDist\*.whl","$targetDist\*.gz","$targetDist\uv.lock","$targetDist\pyproject.toml" -ErrorAction SilentlyContinue
Remove-Item -Force -Recurse "$targetDist\.venv" -ErrorAction SilentlyContinue
Remove-Item -Force -Recurse dist,build -ErrorAction SilentlyContinue

# Build sdist
uv build --sdist
Move-Item dist\*.gz $targetDist

# Build wheels from subdirectories
$subdirs = @("agilab/core/env", "agilab/core/cluster", "agilab/core/node", "agilab/gui")

foreach ($dir in $subdirs) {
    $srcDir = Join-Path $cwd "src\agilab\$dir"
    Push-Location $srcDir

    Remove-Item -Recurse -Force dist,build -ErrorAction SilentlyContinue
    uv build --wheel
    Move-Item dist\*.whl $targetDist

    Pop-Location
}

# Initialize and install in agi-pypi folder
Push-Location $targetDist
Remove-Item -Recurse -Force .venv,uv.lock -ErrorAction SilentlyContinue

if (-not (Test-Path "pyproject.toml")) {
    uv init --bare
}

$packages = Get-ChildItem *.whl, *.gz | ForEach-Object { $_.FullName }
uv add $packages
Pop-Location
