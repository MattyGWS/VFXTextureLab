@echo off
setlocal
cd /d "%~dp0"

set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "PYTHON_CMD="

echo VFX Texture Lab - Windows test setup
echo.

for %%V in (3.13 3.12 3.11) do (
    if not defined PYTHON_CMD (
        py -%%V -c "import struct; raise SystemExit(0 if struct.calcsize('P') == 8 else 1)" >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD=py -%%V"
    )
)

if not defined PYTHON_CMD (
    python -c "import sys, struct; raise SystemExit(0 if (3, 11) ^<= sys.version_info[:2] ^< (3, 14) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" -c "import sys, struct; raise SystemExit(0 if (3, 11) ^<= sys.version_info[:2] ^< (3, 14) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
    if errorlevel 1 (
        echo The existing .venv uses a Python version without an xatlas binary wheel.
        echo Rebuilding the private environment with Python 3.11-3.13...
        rmdir /s /q "%VENV_DIR%"
    )
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
"%VENV_PYTHON%" -m pip install --upgrade --only-binary=xatlas,embreex,scipy,scikit-image --editable "."
if errorlevel 1 goto :dependency_failed

echo.
echo Checking the installation...
"%VENV_PYTHON%" -c "import PySide6, numpy, PIL, wgpu, rendercanvas, fast_simplification, xatlas, trimesh, embreex, scipy, skimage, vfx_texture_lab; print('All required Python packages are available.')"
if errorlevel 1 goto :dependency_failed

echo.
echo Setup completed successfully.
echo You can now start VFX Texture Lab by double-clicking run.bat.
echo.
pause
exit /b 0

:python_missing
echo A 64-bit Python 3.11, 3.12 or 3.13 installation was not found.
echo.
echo xatlas currently publishes Windows wheels through Python 3.13. Install the
echo current 64-bit Python 3.13 release from python.org, then run setup.bat again.
echo This does not affect the prebuilt VFX Texture Lab Windows installer or portable ZIP.
echo.
pause
exit /b 1

:venv_failed
echo.
echo The private Python environment could not be created.
echo Make sure Python 3.11-3.13 was installed normally and then run setup.bat again.
echo.
pause
exit /b 1

:dependency_failed
echo.
echo VFX Texture Lab's dependencies could not be installed.
echo Automatic Charts and high-to-low baking require prebuilt xatlas/embreex wheels, and Geometry Remesh uses
echo prebuilt SciPy/scikit-image wheels. Setup does not attempt local native builds.
echo Check the messages above and confirm internet access.
echo.
pause
exit /b 1
