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

if ! "$VENV_PYTHON" -c "import wgpu" >/dev/null 2>&1; then
    echo "Warning: wgpu-py is not installed; VFX Texture Lab will use the CPU renderer."
    echo "Run setup.sh again to repair or update the test environment."
    echo
fi

exec "$VENV_PYTHON" -m vfx_texture_lab
