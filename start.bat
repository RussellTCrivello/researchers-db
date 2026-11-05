@echo off
REM ===========================================================================
REM  SIRAJ . siraj . bilingual research registry - Windows launcher
REM  Double-click this file, or run it from cmd.exe / PowerShell.
REM ===========================================================================
setlocal
cd /d "%~dp0"

REM --- 1. find a Python 3.10+ interpreter -------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo [SIRAJ] Python 3.10 or newer was not found.
  echo         Install it from https://www.python.org/downloads/windows/
  echo         and tick "Add python.exe to PATH" during setup.
  pause
  exit /b 1
)

REM --- 2. create / reuse a local virtual environment --------------------------
if not exist ".venv\Scripts\python.exe" (
  echo [SIRAJ] Creating virtual environment in .venv ...
  %PY% -m venv .venv || goto :fail
)
set "VENV_PY=.venv\Scripts\python.exe"

REM --- 3. install / refresh dependencies --------------------------------------
"%VENV_PY%" -c "import fastapi, uvicorn" >nul 2>nul
if errorlevel 1 (
  echo [SIRAJ] Installing dependencies ...
  "%VENV_PY%" -m pip install --upgrade pip >nul
  "%VENV_PY%" -m pip install -r requirements.txt || goto :fail
)

REM --- 4. start ---------------------------------------------------------------
echo [SIRAJ] Starting the registry - the browser will open shortly.
start "" http://127.0.0.1:8000
"%VENV_PY%" run.py %*
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo [SIRAJ] Something went wrong. See the messages above.
pause
exit /b 1
