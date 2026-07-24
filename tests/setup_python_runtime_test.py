from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_project_requires_wheel_compatible_python_and_binary_xatlas() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    setup_sh = (ROOT / "setup.sh").read_text(encoding="utf-8")
    setup_bat = (ROOT / "setup.bat").read_text(encoding="utf-8")

    assert 'requires-python = ">=3.11,<3.14"' in pyproject
    assert 'version = "0.53.0.4"' in pyproject
    assert '"$UV_BIN" python install 3.13' in setup_sh
    assert '"$UV_BIN" venv --clear --seed --python 3.13 "$VENV_DIR"' in setup_sh
    assert "--only-binary=xatlas,embreex,scipy,scikit-image" in setup_sh
    assert "--only-binary=xatlas,embreex,scipy,scikit-image" in setup_bat
    for dependency in ("trimesh", "embreex", "scipy", "scikit-image"):
        assert dependency in pyproject
    assert "import PySide6, numpy, PIL, wgpu, rendercanvas, fast_simplification, xatlas, trimesh, embreex, scipy, skimage" in setup_sh
    assert "python3-devel" not in setup_sh


@pytest.mark.skipif(os.name == "nt", reason="Linux setup branch")
def test_linux_setup_rebuilds_python_314_venv_with_managed_313(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    shutil.copy2(ROOT / "setup.sh", project / "setup.sh")

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()

    system_python = fake_bin / "python3"
    system_python.write_text(
        """#!/usr/bin/env bash
set -e
if [[ "${1:-}" == "-c" ]]; then
    code="${2:-}"
    if [[ "$code" == *"platform.python_version"* ]]; then
        echo "Python 3.14.1 (64-bit)"
    elif [[ "$code" == *"sys.version_info >= (3, 11)"* ]]; then
        exit 0
    elif [[ "$code" == *"sys.version_info[:2] < (3, 14)"* ]]; then
        exit 1
    else
        exit 0
    fi
elif [[ "${1:-}" == "-m" && "${2:-}" == "venv" ]]; then
    target="${3}"
    mkdir -p "$target/bin"
    cp "$0" "$target/bin/python"
else
    exit 0
fi
""",
        encoding="utf-8",
    )
    system_python.chmod(0o755)
    for alias in ("python", "python3.11", "python3.12", "python3.13"):
        alias_path = fake_bin / alias
        shutil.copy2(system_python, alias_path)
        alias_path.chmod(0o755)

    old_venv_python = project / ".venv" / "bin" / "python"
    old_venv_python.parent.mkdir(parents=True)
    shutil.copy2(system_python, old_venv_python)
    old_venv_python.chmod(0o755)

    # The setup helper Python installs this fake uv executable when pip is invoked.
    setup_tools_python_template = """#!/usr/bin/env bash
set -e
if [[ "${1:-}" == "-c" ]]; then
    code="${2:-}"
    if [[ "$code" == *"platform.python_version"* ]]; then
        echo "Python 3.14.1 (64-bit)"
    else
        exit 0
    fi
elif [[ "${1:-}" == "-m" && "${2:-}" == "pip" ]]; then
    uv_path="$(dirname "$0")/uv"
    cat > "$uv_path" <<'UV'
#!/usr/bin/env bash
set -e
if [[ "${1:-}" == "python" && "${2:-}" == "install" ]]; then
    exit 0
fi
if [[ "${1:-}" == "venv" ]]; then
    target="${@: -1}"
    mkdir -p "$target/bin"
    cat > "$target/bin/python" <<'PY313'
#!/usr/bin/env bash
set -e
if [[ "${1:-}" == "-c" ]]; then
    code="${2:-}"
    if [[ "$code" == *"platform.python_version"* ]]; then
        echo "Python 3.13.9 (64-bit)"
    elif [[ "$code" == *"sys.version_info[:2] < (3, 14)"* ]]; then
        exit 0
    elif [[ "$code" == *"All required Python packages"* ]]; then
        echo "All required Python packages are available."
    else
        exit 0
    fi
elif [[ "${1:-}" == "-m" && "${2:-}" == "pip" ]]; then
    exit 0
else
    exit 0
fi
PY313
    chmod +x "$target/bin/python"
    exit 0
fi
exit 1
UV
    chmod +x "$uv_path"
    exit 0
fi
exit 0
"""

    # Replace the venv-created setup helper stub after creation by intercepting cp.
    fake_cp = fake_bin / "cp"
    real_cp = shutil.which("cp")
    assert real_cp
    fake_cp.write_text(
        f"""#!/usr/bin/env bash
set -e
{real_cp} "$@"
dest="${{@: -1}}"
if [[ "$dest" == */.setup-tools/bin/python ]]; then
cat > "$dest" <<'HELPER'
{setup_tools_python_template}
HELPER
chmod +x "$dest"
fi
""",
        encoding="utf-8",
    )
    fake_cp.chmod(0o755)

    # The fake system interpreter's venv branch calls cp, allowing the helper stub above.
    env = dict(os.environ)
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
    completed = subprocess.run(
        ["bash", "setup.sh"],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Rebuilding it with" in completed.stdout
    assert "Installing a private wheel-compatible Python 3.13 runtime" in completed.stdout
    assert "Application environment: Python 3.13.9 (64-bit)" in completed.stdout
    assert (project / ".setup-tools" / "bin" / "uv").is_file()
    assert (project / ".venv" / "bin" / "python").is_file()
