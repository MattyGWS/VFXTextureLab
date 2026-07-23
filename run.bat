@echo off
setlocal
cd /d "%~dp0"
set "SCRIPT_DIR=%~dp0"
set "VENV_PYTHON=%SCRIPT_DIR%.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo VFX Texture Lab has not been set up yet.
    echo.
    echo Double-click setup.bat first, then run this file again.
    echo.
    pause
    exit /b 1
)

"%VENV_PYTHON%" -c "import sys; raise SystemExit(0 if (3, 11) ^<= sys.version_info[:2] ^< (3, 14) else 1)" >nul 2>&1
if errorlevel 1 (
    echo Warning: this .venv uses a Python version without an xatlas binary wheel.
    echo Run setup.bat once to rebuild it with Python 3.11-3.13.
    echo.
)

"%VENV_PYTHON%" -c "import wgpu" >nul 2>&1
if errorlevel 1 (
    echo Warning: wgpu-py is not installed; VFX Texture Lab will use the CPU renderer.
    echo Run setup.bat again to repair or update the test environment.
    echo.
)

"%VENV_PYTHON%" -c "import fast_simplification" >nul 2>&1
if errorlevel 1 (
    echo Warning: native high-poly simplification is not installed.
    echo Geometry Decimate will use the slower compatibility fallback.
    echo Run setup.bat again to install the new native mesh dependency.
    echo.
)

"%VENV_PYTHON%" -c "import xatlas" >nul 2>&1
if errorlevel 1 (
    echo Warning: native automatic UV unwrapping is not installed.
    echo Geometry UV Unwrap projection modes still work, but Automatic Charts requires xatlas.
    echo Run setup.bat once to rebuild with a wheel-compatible Python runtime if needed.
    echo.
)

"%VENV_PYTHON%" -m vfx_texture_lab
if errorlevel 1 (
    echo.
    echo VFX Texture Lab closed because of an error.
    echo Please send the tester output shown above.
    echo.
    pause
    exit /b 1
)
