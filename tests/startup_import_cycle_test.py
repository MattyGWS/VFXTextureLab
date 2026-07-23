from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parameters = (ROOT / "vfx_texture_lab" / "ui" / "parameters.py").read_text(encoding="utf-8")
    settings = (ROOT / "vfx_texture_lab" / "three_d" / "settings.py").read_text(encoding="utf-8")
    limits = (ROOT / "vfx_texture_lab" / "geometry_limits.py").read_text(encoding="utf-8")

    assert "from ..geometry_limits import AUTO_WIREFRAME_TRIANGLE_LIMIT" in parameters
    assert "from ..three_d.settings import AUTO_WIREFRAME_TRIANGLE_LIMIT" not in parameters
    assert "from ..geometry_limits import AUTO_WIREFRAME_TRIANGLE_LIMIT" in settings
    assert "AUTO_WIREFRAME_TRIANGLE_LIMIT = 250_000" in limits
    assert "PySide6" not in limits
    assert "import PySide6" not in limits
    assert "import vfx_texture_lab.three_d" not in limits
    assert "from .three_d" not in limits
    assert "from ..three_d" not in limits
    assert "import vfx_texture_lab.ui" not in limits
    assert "from .ui" not in limits
    assert "from ..ui" not in limits
    print("startup import-cycle regression test passed")


if __name__ == "__main__":
    main()
