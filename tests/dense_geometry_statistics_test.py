from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    limits = (ROOT / "vfx_texture_lab" / "geometry_limits.py").read_text(encoding="utf-8")
    settings = (ROOT / "vfx_texture_lab" / "three_d" / "settings.py").read_text(encoding="utf-8")
    renderer = (ROOT / "vfx_texture_lab" / "three_d" / "renderer.py").read_text(encoding="utf-8")
    parameters = (ROOT / "vfx_texture_lab" / "ui" / "parameters.py").read_text(encoding="utf-8")
    geometry_graph = (ROOT / "vfx_texture_lab" / "geometry_graph.py").read_text(encoding="utf-8")
    preview_cache = (ROOT / "vfx_texture_lab" / "preview_cache.py").read_text(encoding="utf-8")
    main_window = (ROOT / "vfx_texture_lab" / "main_window.py").read_text(encoding="utf-8")

    assert "AUTO_WIREFRAME_TRIANGLE_LIMIT = 250_000" in limits
    assert "from ..geometry_limits import AUTO_WIREFRAME_TRIANGLE_LIMIT" in settings
    assert "from .settings import (" in renderer
    assert "AUTO_WIREFRAME_TRIANGLE_LIMIT" in renderer
    assert "Geometry Statistics" in parameters
    assert "Auto wireframe is intentionally hidden" in parameters
    assert "set 3D Preview → Wireframe to Always" in parameters
    assert "_geometry_output_vertex_count" in geometry_graph
    assert "_geometry_input_triangle_count" in geometry_graph
    assert "node_metadata: dict[str, dict[str, Any]] | None" in preview_cache
    assert "cached_metadata" in main_window
    print("dense geometry statistics regression test passed")


if __name__ == "__main__":
    main()
