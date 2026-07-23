#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "VFX Texture Lab has not been set up yet."
    echo
    echo "Run this once first:"
    echo "  bash setup.sh"
    exit 1
fi

if ! "$VENV_PYTHON" -c 'import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)' >/dev/null 2>&1; then
    echo "Warning: this .venv uses a Python version without an xatlas binary wheel."
    echo "Run setup.sh once; it will rebuild the private environment with Python 3.13"
    echo "without changing your system Python or requiring development headers."
    echo
fi

if ! "$VENV_PYTHON" -c "import wgpu" >/dev/null 2>&1; then
    echo "Warning: wgpu-py is not installed; VFX Texture Lab will use the CPU renderer."
    echo "Run setup.sh again to repair or update the test environment."
    echo
fi

if ! "$VENV_PYTHON" -c "import fast_simplification" >/dev/null 2>&1; then
    echo "Warning: native high-poly simplification is not installed."
    echo "Geometry Decimate will use the slower compatibility fallback."
    echo "Run setup.sh again to install the new native mesh dependency."
    echo
fi

if ! "$VENV_PYTHON" -c "import xatlas" >/dev/null 2>&1; then
    echo "Warning: native automatic UV unwrapping is not installed."
    echo "Geometry UV Unwrap projection modes still work, but Automatic Charts requires xatlas."
    echo "Run setup.sh once to rebuild with the wheel-compatible Python runtime if needed."
    echo
fi

exec "$VENV_PYTHON" -m vfx_texture_lab
