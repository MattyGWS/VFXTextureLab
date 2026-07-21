#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

printf '%s\n' "VFX Texture Lab - Linux test setup" ""

if command -v python3 >/dev/null 2>&1; then
    SYSTEM_PYTHON="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
    SYSTEM_PYTHON="$(command -v python)"
else
    echo "Python 3 was not found."
    echo
    echo "Fedora:        sudo dnf install python3 python3-pip"
    echo "Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
    exit 1
fi

if ! "$SYSTEM_PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    echo "VFX Texture Lab requires Python 3.11 or newer."
    echo "Found: $($SYSTEM_PYTHON --version 2>&1)"
    exit 1
fi

echo "Using $($SYSTEM_PYTHON --version 2>&1)"

VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"
if [[ ! -x "$VENV_PYTHON" ]]; then
    echo
    echo "Creating the private Python environment..."
    if ! "$SYSTEM_PYTHON" -m venv "$SCRIPT_DIR/.venv"; then
        echo
        echo "Python could not create a virtual environment."
        echo "On Ubuntu or Debian, install it with:"
        echo "  sudo apt install python3-venv python3-pip"
        echo "On Fedora, install it with:"
        echo "  sudo dnf install python3 python3-pip"
        exit 1
    fi
else
    echo "Reusing the existing .venv environment."
fi

echo
echo "Updating the installer tools..."
"$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel

echo
echo "Installing or updating VFX Texture Lab and its dependencies..."
"$VENV_PYTHON" -m pip install --upgrade --editable "$SCRIPT_DIR"

echo
echo "Checking the installation..."
"$VENV_PYTHON" -c 'import PySide6, numpy, PIL, wgpu, rendercanvas, vfx_texture_lab; print("All required Python packages are available.")'

chmod +x "$SCRIPT_DIR/run.sh" "$SCRIPT_DIR/setup.sh" 2>/dev/null || true

echo
echo "Setup completed successfully."
echo "Start VFX Texture Lab with:"
echo "  ./run.sh"
