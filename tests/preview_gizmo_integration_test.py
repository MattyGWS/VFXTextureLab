from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

root = Path(tempfile.mkdtemp(prefix="vfx-preview-gizmo-"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["XDG_CONFIG_HOME"] = str(root / "config")
os.environ["XDG_DATA_HOME"] = str(root / "data")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.engine import GraphSnapshot
from vfx_texture_lab.main_window import MainWindow


def connect(window: MainWindow, source, output: str, target, input_name: str) -> None:
    connection = window.scene.add_connection(
        source.output_ports[output], target.input_ports[input_name], record_undo=False
    )
    assert connection is not None


def main() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.periodic_autosave_timer.stop()
    window.graph_asset_watch_timer.stop()
    window.preview_timer.stop()
    window.material_preview_timer.stop()
    window.show()
    app.processEvents()

    source = window.scene.create_node(
        "generator.linear_gradient", QPointF(-300, 0), record_undo=False
    )
    source_uid = source.uid
    transform = window.scene.create_node(
        "transform.basic", QPointF(0, 0), record_undo=False
    )
    connect(window, source, "Image", transform, "Image")
    window.scene.set_active_node(transform)
    app.processEvents()
    assert window.preview_panel.canvas._gizmo_type_id == "transform.basic"

    window.scene.undo_stack.clear()
    window.scene.undo_stack.setClean()
    window._preview_gizmo_started(transform.uid)
    window._preview_gizmo_changed(transform.uid, {"offset_x": 0.2, "offset_y": -0.1})
    window._preview_gizmo_changed(transform.uid, {"offset_x": 0.35, "scale": 1.4, "scale_x": 0.7, "scale_y": 1.2})
    window._preview_gizmo_finished(transform.uid)
    window.preview_timer.stop()
    assert abs(float(transform.parameters["offset_x"]) - 0.35) < 1.0e-6
    assert abs(float(transform.parameters["offset_y"]) + 0.1) < 1.0e-6
    assert abs(float(transform.parameters["scale"]) - 1.4) < 1.0e-6
    assert abs(float(transform.parameters["scale_x"]) - 0.7) < 1.0e-6
    assert abs(float(transform.parameters["scale_y"]) - 1.2) < 1.0e-6
    assert window.scene.undo_stack.count() == 1
    window.scene.undo_stack.undo()
    transform = window.scene.nodes[transform.uid]
    source = window.scene.nodes[source_uid]
    assert abs(float(transform.parameters["offset_x"])) < 1.0e-6
    assert abs(float(transform.parameters["offset_y"])) < 1.0e-6
    assert abs(float(transform.parameters["scale"]) - 1.0) < 1.0e-6
    assert abs(float(transform.parameters["scale_x"]) - 1.0) < 1.0e-6
    assert abs(float(transform.parameters["scale_y"]) - 1.0) < 1.0e-6

    perspective = window.scene.create_node(
        "transform.perspective", QPointF(300, 0), record_undo=False
    )
    connect(window, source, "Image", perspective, "Image")
    window.scene.set_active_node(perspective)
    app.processEvents()
    assert not window.preview_panel.edit_input_button.isVisible()
    snapshot = GraphSnapshot.from_scene(window.scene)
    normal_source = window._preview_source_for_node(perspective, snapshot)
    assert normal_source is not None and normal_source[0] == perspective.uid
    assert window.preview_panel.canvas._gizmo_type_id == "transform.perspective"
    assert not window.preview_panel.canvas._gizmo_edit_input

    window.close()
    app.processEvents()
    print("2D Preview gizmo integration checks passed")


if __name__ == "__main__":
    main()
