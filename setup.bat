@echo off
setlocal
cd /d "%~dp0"

set "SCRIPT_DIR=%~dp0"
set "VENV_PYTHON=%SCRIPT_DIR%.venv\Scripts\python.exe"
set "PYTHON_CMD="

echo VFX Texture Lab - Windows test setup
echo.

py -3 -c "import sys, struct; raise SystemExit(0 if sys.version_info.major == 3 and sys.version_info.minor in range(11, 100) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py -3"

if not defined PYTHON_CMD (
    python -c "import sys, struct; raise SystemExit(0 if sys.version_info.major == 3 and sys.version_info.minor in range(11, 100) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD goto :python_missing

%PYTHON_CMD% --version

if not exist "%VENV_PYTHON%" (
    echo.
    echo Creating the private Python environment...
    %PYTHON_CMD% -m venv ".venv"
    if errorlevel 1 goto :venv_failed
) else (
    echo Reusing the existing .venv environment.
)

echo.
echo Updating the installer tools...
"%VENV_PYTHON%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :dependency_failed

echo.
echo Installing or updating VFX Texture Lab and its dependencies...
"%VENV_PYTHON%" -m pip install --upgrade --editable "."
if errorlevel 1 goto :dependency_failed

echo.
echo Checking the installation...
"%VENV_PYTHON%" -c "import PySide6, numpy, PIL, wgpu, rendercanvas, vfx_texture_lab; print('All required Python packages are available.')"
if errorlevel 1 goto :dependency_failed

echo.
echo Setup completed successfully.
echo You can now start VFX Texture Lab by double-clicking run.bat.
echo.
pause
exit /b 0

:python_missing
echo A 64-bit Python 3.11 or newer installation was not found.
echo.
echo Install the current 64-bit Python 3 release from python.org.
echo During installation, enable "Add python.exe to PATH" and install the Python launcher.
echo Then run setup.bat again.
echo.
pause
exit /b 1

:venv_failed
echo.
echo The private Python environment could not be created.
echo Make sure Python was installed normally and then run setup.bat again.
echo.
pause
exit /b 1

:dependency_failed
echo.
echo VFX Texture Lab's dependencies could not be installed.
echo Check the messages above. An internet connection is required during setup.
echo.
pause
exit /b 1
