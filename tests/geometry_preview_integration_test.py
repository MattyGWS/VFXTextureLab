from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

import numpy as np

from vfx_texture_lab.main_window import MainWindow


def main() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    plane = window.scene.create_node(
        "geometry.plane",
        QPointF(100, 500),
        parameters={"name": "Preview Card", "subdivisions_x": 4, "subdivisions_y": 2},
        record_undo=False,
    )
    output = window.scene.create_node("output.geometry", QPointF(420, 500), record_undo=False)
    assert window.scene.add_connection(
        plane.output_ports["Geometry"], output.input_ports["Geometry"], record_undo=False
    )

    window.scene.set_active_node(plane, force=True)
    app.processEvents()
    renderer = window.preview_3d_panel.canvas.renderer
    assert renderer.has_geometry_override
    assert renderer._geometry_override is not None
    assert renderer._geometry_override.vertex_count == 15
    assert window.preview_3d_panel._geometry_inspection
    assert renderer.wireframe_enabled()
    assert plane.error_message == ""

    constant = window.scene.create_node(
        "generator.constant",
        QPointF(100, 720),
        parameters={"value": 0.5},
        record_undo=False,
    )
    displace = window.scene.create_node(
        "geometry.displace",
        QPointF(420, 720),
        parameters={"amount": 2.0},
        record_undo=False,
    )
    assert window.scene.add_connection(
        plane.output_ports["Geometry"], displace.input_ports["Geometry"], record_undo=False
    )
    assert window.scene.add_connection(
        constant.output_port, displace.input_ports["Height"], record_undo=False
    )
    window.scene.set_active_node(displace, force=True)
    app.processEvents()
    assert renderer.has_geometry_override
    assert renderer._geometry_override is not None
    assert renderer._geometry_override.vertex_count == 15
    assert np.allclose(renderer._geometry_override.vertices[:, 1], 1.0)
    assert displace.error_message == ""

    # A delayed/explicit 2D dispatch must remain on the geometry path instead
    # of misclassifying the plane as a CPU/WGSL image node.
    window._evaluate_active()
    app.processEvents()
    assert displace.error_message == ""
    assert "WGSL package node" not in displace.toolTip()

    disconnected_output = window.scene.create_node(
        "output.geometry", QPointF(700, 500), record_undo=False
    )
    window.scene.set_active_node(disconnected_output, force=True)
    app.processEvents()
    assert not renderer.has_geometry_override
    assert "error" in window.preview_3d_panel._last_summary.lower()

    ordinary = next(
        node for node in window.scene.nodes.values()
        if node.definition.type_id.startswith("noise.")
    )
    window.scene.set_active_node(ordinary, force=True)
    app.processEvents()
    assert not renderer.has_geometry_override
    assert not renderer.wireframe_enabled()

    material = next(
        node for node in window.scene.nodes.values()
        if node.definition.type_id == "material.pbr"
    )
    assert window.scene.add_connection(
        displace.output_ports["Geometry"], material.input_ports["Geometry"], record_undo=False
    )
    window.scene.set_active_node(material, force=True)
    app.processEvents()
    assert renderer.has_geometry_override
    assert not window.preview_3d_panel._geometry_inspection
    assert not renderer.wireframe_enabled()

    window.preview_3d_panel.set_viewport_setting("wireframe", "Always", persist=False)
    assert renderer.wireframe_enabled()
    window.preview_3d_panel.set_viewport_setting("wireframe", "Off", persist=False)
    assert not renderer.wireframe_enabled()
    window.preview_3d_panel.set_viewport_setting("wireframe", "Auto", persist=False)

    with tempfile.TemporaryDirectory(prefix="vfxtl-geometry-export-") as directory:
        destination = Path(directory) / "preview_card.obj"
        output.parameters["_quick_export_configured"] = True
        output.parameters["_quick_export_path"] = str(destination)
        window._geometry_export(output.uid, False)
        assert destination.exists()
        exported = destination.read_text(encoding="utf-8")
        assert exported.count("\nv ") == 15
        assert exported.count("\nf ") == 16

    window.material_controller.cancel()
    window._document_dirty = False
    window._recovered_dirty = False
    window.scene.undo_stack.setClean()
    window._set_dirty(False)
    window.close()
    app.processEvents()
    print(
        "geometry preview integration test passed: focused shaded geometry, ordinary-mesh restore, "
        "Material preview override and remembered OBJ quick export"
    )


if __name__ == "__main__":
    main()
