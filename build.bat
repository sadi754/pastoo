@echo off
rem Builds Pastoo as a portable folder: dist\Pastoo\Pastoo.exe (+ pastoo-cli.exe),
rem dist\Pastoo-<version>-win64.zip of that folder, ready to share, and - when
rem Inno Setup 6 is installed - the installer dist\Pastoo-Setup-<version>.exe.
rem Needs the Python environment that run.bat sets up (run it once first).
setlocal
cd /d "%~dp0"
rem Only Windows' own folders on PATH: PyInstaller collects DLLs it finds there (another
rem program's copy of the C runtime could end up in the build).
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%SystemRoot%\System32\WindowsPowerShell\v1.0"

if not exist ".venv\Scripts\python.exe" (
    echo [build] Run run.bat once first - it sets up the Python environment.
    exit /b 1
)
echo [build] Running the tests ...
".venv\Scripts\python.exe" -m unittest discover -s tests -q || goto failed
echo [build] Installing the build tools ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt -r requirements-build.txt || goto failed
".venv\Scripts\python.exe" tools\prepare_build.py || goto failed
echo [build] Building Pastoo.exe (takes a minute or two) ...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --log-level WARN --distpath dist --workpath build\pyinstaller tools\pastoo.spec || goto failed
".venv\Scripts\python.exe" tools\package_zip.py || goto failed

set "ISCC="
for %%d in ("%LOCALAPPDATA%\Programs\Inno Setup 6" "%ProgramFiles(x86)%\Inno Setup 6" "%ProgramFiles%\Inno Setup 6") do (
    if exist "%%~d\ISCC.exe" set "ISCC=%%~d\ISCC.exe"
)
if not defined ISCC (
    echo [build] Inno Setup 6 not found - skipping the installer ^(winget install JRSoftware.InnoSetup^).
    goto done
)
set /p VERSION=<build\version.txt
echo [build] Building the installer ...
"%ISCC%" /Q /DAppVersion=%VERSION% installer\pastoo.iss || goto failed
echo [build] dist\Pastoo-Setup-%VERSION%.exe

:done
echo [build] Done: dist\Pastoo\Pastoo.exe
exit /b 0

:failed
echo [build] Failed - see the messages above.
exit /b 1
