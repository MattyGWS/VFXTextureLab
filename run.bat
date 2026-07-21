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

"%VENV_PYTHON%" -c "import wgpu" >nul 2>&1
if errorlevel 1 (
    echo Warning: wgpu-py is not installed; VFX Texture Lab will use the CPU renderer.
    echo Run setup.bat again to repair or update the test environment.
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
