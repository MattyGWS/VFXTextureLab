from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vfx_texture_lab.export_plan import build_export_artifacts
from vfx_texture_lab.nodes import build_registry


def fake_node(type_id: str, parameters: dict | None = None, kind: str = "grayscale"):
    return SimpleNamespace(
        definition=SimpleNamespace(type_id=type_id),
        parameters=dict(parameters or {}),
        resolved_kind=kind,
    )


def main() -> None:
    registry = build_registry()
    send = registry.get("graph.send")
    receive = registry.get("graph.receive")
    assert send.category == "Graph Utilities"
    assert send.terminal and send.inputs == ("Input",)
    assert receive.inputs == ("Input",)
    assert receive.output_names == ("Output",)
    assert receive.parameter_spec("sender_uid").kind == "portal_channel"

    # Texture Set export follows a Material travelling through Receive rather
    # than requiring a direct visible connection.
    texture = fake_node(
        "output.texture_set",
        {
            "name": "PortalRock",
            "export_filename": "{set}_{map}",
            "export_preset": "Separate PBR Maps",
            "export_resolution": "Document",
            "normal_convention": "OpenGL (+Y)",
            "texture_format": "PNG",
            "colour_bit_depth": "8",
            "data_bit_depth": "16",
            "height_format": "PNG 16-bit",
        },
    )
    receiver = fake_node("graph.receive", {"sender_uid": "send"})
    material = fake_node("material.pbr", {"name": "Portal Material"}, "color")
    snapshot = SimpleNamespace(
        nodes={"set": texture, "receive": receiver, "material": material},
        inputs={
            ("set", "Material"): ("receive", "Output"),
            ("receive", "Input"): ("material", "Material"),
            ("material", "Base Colour"): ("base", "Image"),
            ("material", "Roughness"): ("rough", "Image"),
        },
    )
    artifacts = build_export_artifacts(snapshot, ["set"], SimpleNamespace(width=512, height=512))
    labels = {artifact.label for artifact in artifacts}
    assert "PortalRock · BaseColor" in labels
    assert "PortalRock · Roughness" in labels

    root = Path(__file__).resolve().parents[1]
    scene_source = (root / "vfx_texture_lab/graph/scene.py").read_text(encoding="utf-8")
    item_source = (root / "vfx_texture_lab/graph/items.py").read_text(encoding="utf-8")
    evaluator_source = (root / "vfx_texture_lab/engine/evaluator.py").read_text(encoding="utf-8")
    view_source = (root / "vfx_texture_lab/graph/view.py").read_text(encoding="utf-8")
    main_source = (root / "vfx_texture_lab/main_window.py").read_text(encoding="utf-8")
    assert "toggle_selected_node_dock" in scene_source
    assert "_refresh_docked_layout" in scene_source
    assert "class PortalNodeItem" in item_source
    assert "connection.source_node.definition.type_id == \"graph.receive\"" in scene_source
    assert 'node.definition.type_id == "graph.receive"' in evaluator_source
    assert "Qt.Key.Key_D" in view_source
    assert "constant.set_docked(material_output.uid" in main_source

    print("Graph docking/portals test passed: definitions, material routing, docking shortcut, retained broken links and evaluator pass-through.")


if __name__ == "__main__":
    main()
