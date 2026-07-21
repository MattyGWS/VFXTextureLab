from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.graph.scene import GraphScene
from vfx_texture_lab.graph.view import GraphView
from vfx_texture_lab.main_window import MainWindow
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.ui.node_preferences import NodePreferences


def main() -> None:
    app = QApplication.instance() or QApplication([])
    registry = build_registry()
    scene = GraphScene(registry)
    view = GraphView(scene, NodePreferences())
    view.resize(900, 560)
    view.show()

    worley = scene.create_node("noise.worley", QPointF(-260, 0), record_undo=False)
    levels = scene.create_node("filter.levels", QPointF(260, 0), record_undo=False)
    view.centerOn(0, 50)
    app.processEvents()

    # Double-clicking one exact output locks that socket, not merely the node.
    f2_port = worley.output_ports["F2"]
    f2_pos = view.mapFromScene(f2_port.centre_scene_pos())
    QTest.mouseDClick(
        view.viewport(), Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier, f2_pos,
    )
    app.processEvents()
    assert scene.active_node is worley
    assert scene.active_output_name == "F2"
    assert f2_port._preview_active
    assert not worley.output_ports["F1"]._preview_active
    assert view._connection_start_port is None
    assert view._temporary_connection is None

    # MainWindow's preview resolver receives the exact named output.
    harness = type("PreviewHarness", (), {})()
    harness.scene = scene
    harness.MATERIAL_NODE_TYPE = "material.pbr"
    harness.MATERIAL_NODE_TYPES = {"material.pbr", "material.blend", "material.override", "material.switch"}
    harness.TEXTURE_SET_NODE_TYPE = "output.texture_set"
    harness._graph_instance_output = MainWindow._graph_instance_output.__get__(harness)
    harness._is_material_preview_node = MainWindow._is_material_preview_node.__get__(harness)
    harness._resolve_material_node = MainWindow._resolve_material_node.__get__(harness)
    source = MainWindow._preview_source_for_node(harness, worley)
    assert source is not None
    assert source[:2] == (worley.uid, "F2")
    assert source[2] == "F2"

    # The exact active socket survives save/load using its stable output name.
    payload = scene.to_dict()
    restored = GraphScene(registry)
    restored.from_dict(payload)
    assert restored.active_node is not None
    assert restored.active_node.uid == worley.uid
    assert restored.active_output_name == "F2"
    assert restored.nodes[worley.uid].output_ports["F2"]._preview_active

    # Dragging from another socket still creates a normal wire once movement
    # crosses Qt's drag threshold; a simple socket click never opens loose-wire
    # search and double-click preview does not interfere with this gesture.
    f1_pos = view.mapFromScene(worley.output_ports["F1"].centre_scene_pos())
    input_pos = view.mapFromScene(levels.input_ports["Image"].centre_scene_pos())
    QTest.mousePress(
        view.viewport(), Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier, f1_pos,
    )
    QTest.mouseMove(view.viewport(), input_pos, 30)
    QTest.mouseRelease(
        view.viewport(), Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier, input_pos,
    )
    app.processEvents()
    connection = scene.connection_for_input(levels.uid, "Image")
    assert connection is not None
    assert connection.source_node is worley
    assert connection.output_name == "F1"
    assert scene.active_output_name == "F2"


    # A multi-output Graph Instance can explicitly preview Height without being
    # mistaken for its complete Material output. Selecting Material activates
    # the material path again.
    asset_path = ROOT / "examples" / "graph_assets" / "rock_material_generator.vfxgraph"
    asset_scene = GraphScene(registry)
    instance = asset_scene.create_graph_instance(asset_path, QPointF(), record_undo=False)
    height_port = next(
        port for port in instance.output_ports.values() if port.display_name == "Height"
    )
    material_port = next(
        port for port in instance.output_ports.values() if port.display_name == "Material"
    )
    asset_scene.set_active_output(instance, height_port.name)
    harness.scene = asset_scene
    assert not MainWindow._is_material_preview_node(harness, instance)
    height_source = MainWindow._preview_source_for_node(harness, instance)
    assert height_source is not None and height_source[1] == height_port.name
    asset_scene.set_active_output(instance, material_port.name)
    assert MainWindow._is_material_preview_node(harness, instance)

    # Node-body activation clears the exact-socket lock and uses the node's
    # primary/default output again.
    scene.set_active_node(worley, force=True)
    assert scene.active_output_name is None
    assert not any(port._preview_active for port in worley.output_ports.values())

    print(
        "output socket preview test passed: exact named-output focus, persistent socket highlight, "
        "save/load state and drag-safe wire creation"
    )


if __name__ == "__main__":
    main()
