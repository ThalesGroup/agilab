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