@echo off
rem Pastoo app: prepares the Python environment on first run, then starts the app.
rem   run.bat              tray icon + window
rem   run.bat --minimized  start in the tray only
rem   run.bat --debug      with log messages in this terminal
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [Pastoo] First run: creating a private Python environment in .venv ...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if errorlevel 1 (
        echo [Pastoo] Could not create .venv - is Python 3.10 or newer installed?
        pause
        exit /b 1
    )
)

rem Install packages only when requirements.txt has changed since the last install.
fc /b requirements.txt ".venv\requirements.installed" >nul 2>&1
if errorlevel 1 (
    echo [Pastoo] Installing Python packages ...
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
    if errorlevel 1 (
        echo [Pastoo] Package installation failed - see the messages above.
        pause
        exit /b 1
    )
    copy /y requirements.txt ".venv\requirements.installed" >nul
)

if /i "%~1"=="--debug" goto terminal
start "" ".venv\Scripts\pythonw.exe" -m pastoo %*
exit /b 0

:terminal
".venv\Scripts\python.exe" -m pastoo %*
