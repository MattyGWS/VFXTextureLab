from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vfx_texture_lab.nodes import build_registry


def function_block(source: str, name: str) -> str:
    start = source.index(f"    def {name}(")
    next_def = source.find("\n    def ", start + 8)
    return source[start:] if next_def < 0 else source[start:next_def]


def main() -> None:
    registry = build_registry()
    material = registry.get("material.pbr")
    texture_set = registry.get("output.texture_set")
    flipbook = registry.get("output.flipbook")
    image_output = registry.get("output.image")

    assert material.output_names == ("Material",)
    assert material.output_kind("Material") == "material"
    assert texture_set.inputs == ("Material",)
    assert texture_set.input_kind("Material") == "material"
    assert texture_set.terminal
    assert flipbook.name == "Flipbook Generator" and flipbook.category == "Animation"
    assert image_output.name == "Single Image Output"

    main_window = (ROOT / "vfx_texture_lab/main_window.py").read_text()
    parameters = (ROOT / "vfx_texture_lab/ui/parameters.py").read_text()
    library = (ROOT / "vfx_texture_lab/ui/library.py").read_text()
    export_dialog = (ROOT / "vfx_texture_lab/ui/export_dialog.py").read_text()
    graph_items = (ROOT / "vfx_texture_lab/graph/items.py").read_text()
    graph_scene = (ROOT / "vfx_texture_lab/graph/scene.py").read_text()

    starter = function_block(main_window, "_create_starter_graph")
    assert 'QPointF(300, -80)' in starter
    assert 'QPointF(620, 15)' in starter
    assert 'QPointF(-450, 250)' in starter
    assert 'QPointF(-210, 250)' in starter
    assert 'QPointF(30, 250)' in starter
    assert 'self.scene.set_active_node(material_output)' in starter

    schedule = function_block(main_window, "_schedule_preview")
    dispatch = function_block(main_window, "_dispatch_pending_preview")
    assert "_find_3d_output()" not in schedule
    assert "_find_3d_output()" not in dispatch
    assert "force=True" in graph_items
    assert "if force:" in graph_scene

    assert "textureSetQuickExportRequested = Signal(str, bool)" in parameters
    assert 'QPushButton("Quick Export"' in parameters
    assert 'node.definition.type_id in {"output.image", "output.texture_set"}' in parameters
    assert 'QPushButton("Configure Export…"' in parameters
    assert '"_quick_export_directory"' in main_window
    assert '"_quick_export_collision"' in main_window
    assert '"_quick_export_open_folder"' in main_window
    assert 'export/open_folder_when_complete' in main_window
    assert "default_open_folder" in export_dialog

    assert '"★ Favourites"' in library
    assert "if not text and favourites" in library
    assert "add_builtin(favourite_category" in library

    print(
        "material/export workflow polish test passed: clean starter layout, dual Material preview routing, "
        "Single Image/Texture Set Quick Export, remembered folder preference and Node Library favourites shelf"
    )


if __name__ == "__main__":
    main()
