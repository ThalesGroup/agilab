param(
    [Parameter(Mandatory = $false)]
    [string]$PythonPath = (Get-Command python).Source
)

$uv = "$PythonPath -m uv"
$AgiDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$agi = Join-Path $AgiDir "fwk\agi"
$AgiEdit = Join-Path $agi "src\agi\AGILab.py"

Write-Host "$uv run --project $Agi python -m streamlit run $AgiEdit"
Push-Location $Agi
(& cmd /c "$uv run --project $Agipython -m streamlit run $AgiEdit")