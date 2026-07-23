#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

printf '%s\n' "VFX Texture Lab - Linux test setup" ""

python_is_usable() {
    local python_exe="$1"
    "$python_exe" -c '
import struct, sys
ok = sys.version_info >= (3, 11) and struct.calcsize("P") == 8
raise SystemExit(0 if ok else 1)
' >/dev/null 2>&1
}

python_has_native_uv_wheel() {
    local python_exe="$1"
    "$python_exe" -c '
import struct, sys
ok = (3, 11) <= sys.version_info[:2] < (3, 14) and struct.calcsize("P") == 8
raise SystemExit(0 if ok else 1)
' >/dev/null 2>&1
}

python_label() {
    "$1" -c 'import platform, struct; print(f"Python {platform.python_version()} ({struct.calcsize("P") * 8}-bit)")'
}

find_bootstrap_python() {
    local candidate
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            candidate="$(command -v "$candidate")"
            if python_is_usable "$candidate"; then
                printf '%s\n' "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

find_wheel_python() {
    local candidate resolved
    for candidate in python3.13 python3.12 python3.11 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            resolved="$(command -v "$candidate")"
            if python_has_native_uv_wheel "$resolved"; then
                printf '%s\n' "$resolved"
                return 0
            fi
        fi
    done
    return 1
}

BOOTSTRAP_PYTHON="$(find_bootstrap_python || true)"
if [[ -z "$BOOTSTRAP_PYTHON" ]]; then
    echo "A 64-bit Python 3.11 or newer installation was not found."
    echo
    echo "Fedora:        sudo dnf install python3 python3-pip"
    echo "Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
    exit 1
fi

echo "System interpreter: $(python_label "$BOOTSTRAP_PYTHON")"

VENV_DIR="$SCRIPT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
SETUP_PYTHON=""

if [[ -x "$VENV_PYTHON" ]]; then
    if python_has_native_uv_wheel "$VENV_PYTHON"; then
        echo "Reusing the existing .venv environment ($(python_label "$VENV_PYTHON"))."
    else
        echo
        echo "The existing .venv uses $(python_label "$VENV_PYTHON")."
        echo "xatlas currently provides Linux wheels through CPython 3.13, so this"
        echo "environment would try to compile xatlas from source. Rebuilding it with"
        echo "a managed Python 3.13 environment instead."
        rm -rf "$VENV_DIR"
    fi
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
    SETUP_PYTHON="$(find_wheel_python || true)"
    if [[ -n "$SETUP_PYTHON" ]]; then
        echo
        echo "Creating the private Python environment with $(python_label "$SETUP_PYTHON")..."
        if ! "$SETUP_PYTHON" -m venv "$VENV_DIR"; then
            echo
            echo "Python could not create a virtual environment."
            echo "On Ubuntu or Debian, install the matching python3-venv package."
            echo "On Fedora, install python3 and python3-pip."
            exit 1
        fi
    else
        SETUP_TOOLS_DIR="$SCRIPT_DIR/.setup-tools"
        SETUP_TOOLS_PYTHON="$SETUP_TOOLS_DIR/bin/python"
        UV_BIN="$SETUP_TOOLS_DIR/bin/uv"

        echo
        echo "No installed Python 3.11-3.13 interpreter was found."
        echo "Preparing a private setup helper so Python 3.13 can be installed without"
        echo "changing the system Python or requiring compiler/development packages..."

        if [[ ! -x "$UV_BIN" ]]; then
            rm -rf "$SETUP_TOOLS_DIR"
            if ! "$BOOTSTRAP_PYTHON" -m venv "$SETUP_TOOLS_DIR"; then
                echo
                echo "Python could not create the setup helper environment."
                echo "On Ubuntu or Debian, install python3-venv and python3-pip."
                echo "On Fedora, install python3 and python3-pip."
                exit 1
            fi
            "$SETUP_TOOLS_PYTHON" -m pip install --upgrade pip uv
        fi

        echo
        echo "Installing a private wheel-compatible Python 3.13 runtime..."
        "$UV_BIN" python install 3.13
        "$UV_BIN" venv --clear --seed --python 3.13 "$VENV_DIR"
    fi
fi

if [[ ! -x "$VENV_PYTHON" ]] || ! python_has_native_uv_wheel "$VENV_PYTHON"; then
    echo
    echo "Setup could not create a supported Python 3.11-3.13 environment."
    exit 1
fi

echo
echo "Application environment: $(python_label "$VENV_PYTHON")"

echo
echo "Updating the installer tools..."
"$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel

echo
echo "Installing or updating VFX Texture Lab and its dependencies..."
if ! "$VENV_PYTHON" -m pip install --upgrade --only-binary=xatlas,embreex,scipy,scikit-image --editable "$SCRIPT_DIR"; then
    echo
    echo "VFX Texture Lab's dependencies could not be installed."
    echo "Automatic Charts and high-to-low baking require xatlas/embreex binary wheels, and Geometry Remesh uses"
    echo "prebuilt SciPy/scikit-image wheels. Setup deliberately avoids slow and fragile"
    echo "local native builds. On Linux x86-64, rerunning this setup with an internet"
    echo "connection should use the Python 3.13 wheels automatically."
    exit 1
fi

echo
echo "Checking the installation..."
"$VENV_PYTHON" -c 'import PySide6, numpy, PIL, wgpu, rendercanvas, fast_simplification, xatlas, trimesh, embreex, scipy, skimage, vfx_texture_lab; print("All required Python packages are available.")'

chmod +x "$SCRIPT_DIR/run.sh" "$SCRIPT_DIR/setup.sh" 2>/dev/null || true

echo
echo "Setup completed successfully."
echo "Start VFX Texture Lab with:"
echo "  ./run.sh"
