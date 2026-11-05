# ===========================================================================
#  SIRAJ . siraj . bilingual research registry - PowerShell launcher
#  Usage:  .\start.ps1            (server)      .\start.ps1 init --demo
#  If script execution is blocked, run once:
#     Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
# ===========================================================================
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

$python = $null
foreach ($candidate in @("py", "python", "python3")) {
  if (Get-Command $candidate -ErrorAction SilentlyContinue) { $python = $candidate; break }
}
if (-not $python) {
  Write-Host "[SIRAJ] Python 3.10+ not found - install it from python.org and re-run." -ForegroundColor Red
  exit 1
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
  Write-Host "[SIRAJ] Creating virtual environment in .venv ..."
  & $python -m venv .venv
}
$venvPy = ".venv\Scripts\python.exe"

& $venvPy -c "import fastapi, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "[SIRAJ] Installing dependencies ..."
  & $venvPy -m pip install --upgrade pip | Out-Null
  & $venvPy -m pip install -r requirements.txt
}

Start-Process "http://127.0.0.1:8000"
& $venvPy run.py @args
