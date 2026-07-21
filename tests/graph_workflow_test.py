from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QPainterPath
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.engine import GraphEvaluator
from vfx_texture_lab.graph.items import RerouteItem
from vfx_texture_lab.graph.scene import GraphScene
from vfx_texture_lab.graph.view import GraphView
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.ui.node_preferences import NodePreferences


def main() -> None:
    app = QApplication.instance() or QApplication([])
    registry = build_registry()

    # Reroutes are graph infrastructure, not library clutter.
    assert registry.contains("graph.reroute")
    assert all(definition.type_id != "graph.reroute" for definition in registry.all())
    assert any(
        definition.type_id == "graph.reroute"
        for definition in registry.all(include_hidden=True)
    )

    scene = GraphScene(registry)
    noise = scene.create_node("noise.fractal", QPointF(-320, 0), emit_change=False)
    levels = scene.create_node("filter.levels", QPointF(240, 0), emit_change=False)
    original = scene.add_connection(
        noise.output_port, levels.input_ports["Image"], emit_change=False
    )
    assert original is not None

    reroute = scene.insert_reroute_on_connection(original, QPointF(20, 55))
    assert isinstance(reroute, RerouteItem)
    assert reroute.reroute_kind == "grayscale"
    assert len(scene.connections) == 2

    evaluator = GraphEvaluator(scene, backend_preference="cpu")
    routed = evaluator.evaluate(levels.uid, 64, 64)
    assert routed.error is None

    # The same reroute infrastructure preserves scalar animation signals.
    time_node = scene.create_node("signal.time", QPointF(-320, 220), emit_change=False)
    signal_reroute = scene.create_reroute(
        QPointF(20, 220), "scalar", record_undo=False
    )
    assert scene.add_connection(
        time_node.output_ports["Seconds"],
        signal_reroute.input_ports["Input"],
        emit_change=False,
    ) is not None
    signal_result = evaluator.evaluate(
        signal_reroute.uid, 8, 8, time_seconds=2.75, frame_number=82
    )
    assert signal_result.error is None
    assert np.isclose(float(signal_result.signal_value), 2.75)

    # Bypass is a true graph pass-through rather than a visual-only flag.
    scene.toggle_node_bypass(levels)
    assert levels.bypassed
    bypassed = evaluator.evaluate(levels.uid, 64, 64)
    source = evaluator.evaluate(noise.uid, 64, 64)
    assert bypassed.error is None
    assert np.allclose(bypassed.image, source.image, atol=1e-6)

    # Drag/drop insertion replaces one wire with two links in a single graph edit.
    target_wire = next(connection for connection in scene.connections if connection.target_node is levels)
    gamma = scene.insert_node_on_connection(
        "filter.gamma", QPointF(340, 80), target_wire
    )
    assert gamma is not None
    assert scene.connection_for_input(gamma.uid, "Image") is not None
    assert scene.connection_for_input(levels.uid, "Image").source_node is gamma

    # Loose-connection creation picks a compatible endpoint automatically.
    brightness = scene.create_node_connected(
        "filter.brightness", QPointF(650, 80), gamma.output_port
    )
    assert brightness is not None
    assert scene.connection_for_input(brightness.uid, "Image") is not None

    # Alignment and distribution operate on ordinary nodes and reroutes alike.
    scene.clearSelection()
    for item in (noise, reroute, gamma, levels):
        item.setSelected(True)
    assert scene.arrange_selected("top")
    tops = [item.sceneBoundingRect().top() for item in (noise, reroute, gamma, levels)]
    assert max(tops) - min(tops) < 1e-6
    assert scene.distribute_selected("horizontal")

    # Reroute type and bypass state survive graph serialization.
    payload = scene.to_dict()
    assert payload["version"] == 18
    restored = GraphScene(registry)
    restored.from_dict(payload)
    restored_reroutes = [item for item in restored.nodes.values() if isinstance(item, RerouteItem)]
    assert {item.reroute_kind for item in restored_reroutes} >= {"grayscale", "scalar"}
    assert restored.nodes[levels.uid].bypassed

    # The wire-cut model removes every intersected connection in one action.
    cut_scene = GraphScene(registry)
    left = cut_scene.create_node("noise.fractal", QPointF(-300, 0), emit_change=False)
    right = cut_scene.create_node("filter.levels", QPointF(240, 0), emit_change=False)
    wire = cut_scene.add_connection(left.output_port, right.input_ports["Image"], emit_change=False)
    assert wire is not None
    midpoint = wire.path().pointAtPercent(0.5)
    knife = QPainterPath(QPointF(midpoint.x(), midpoint.y() - 50))
    knife.lineTo(QPointF(midpoint.x(), midpoint.y() + 50))
    hits = cut_scene.connections_intersecting_path(knife)
    assert wire in hits
    assert cut_scene.cut_connections(hits) == 1
    assert not cut_scene.connections

    # Exercise the visible gestures off-screen: double-click reroute, bypass icon,
    # X-drag wire cutting, and edge panning while a connection is held.
    ui_scene = GraphScene(registry)
    view = GraphView(ui_scene, NodePreferences())
    view.resize(1000, 600)
    view.show()
    ui_left = ui_scene.create_node("noise.fractal", QPointF(-300, 0), emit_change=False)
    ui_right = ui_scene.create_node("filter.levels", QPointF(220, 0), emit_change=False)
    ui_wire = ui_scene.add_connection(
        ui_left.output_port, ui_right.input_ports["Image"], emit_change=False
    )
    assert ui_wire is not None
    view.centerOn(0, 50)
    app.processEvents()

    wire_mid = view.mapFromScene(ui_wire.path().pointAtPercent(0.5))
    QTest.mouseDClick(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        wire_mid,
    )
    app.processEvents()
    assert any(isinstance(item, RerouteItem) for item in ui_scene.nodes.values())

    bypass_pos = view.mapFromScene(
        ui_right.mapToScene(ui_right.bypass_button_rect().center())
    )
    QTest.mouseClick(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        bypass_pos,
    )
    app.processEvents()
    assert ui_right.bypassed

    cut_wire = next(connection for connection in ui_scene.connections if connection.target_node is ui_right)
    cut_mid = view.mapFromScene(cut_wire.path().pointAtPercent(0.5))
    QTest.keyPress(view, Qt.Key.Key_X)
    QTest.mousePress(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        cut_mid + QPoint(0, -35),
    )
    QTest.mouseMove(view.viewport(), cut_mid + QPoint(0, 35), 30)
    QTest.mouseRelease(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        cut_mid + QPoint(0, 35),
    )
    QTest.keyRelease(view, Qt.Key.Key_X)
    app.processEvents()
    assert all(connection.target_node is not ui_right for connection in ui_scene.connections)

    pan_scene = GraphScene(registry)
    pan_view = GraphView(pan_scene, NodePreferences())
    pan_view.resize(800, 500)
    pan_view.show()
    pan_node = pan_scene.create_node("noise.fractal", QPointF(0, 0), emit_change=False)
    pan_view.centerOn(100, 50)
    app.processEvents()
    port_pos = pan_view.mapFromScene(pan_node.output_port.centre_scene_pos())
    edge = QPoint(pan_view.viewport().rect().right() - 2, pan_view.viewport().rect().center().y())
    QTest.mousePress(
        pan_view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        port_pos,
    )
    QTest.mouseMove(pan_view.viewport(), edge, 20)
    app.processEvents()
    before = pan_view.horizontalScrollBar().value()
    QTest.qWait(120)
    app.processEvents()
    after = pan_view.horizontalScrollBar().value()
    pan_view._end_temporary_connection()
    assert after > before

    print(
        "graph workflow test passed: typed reroutes, loose-port creation, wire insertion, "
        "wire cutting, alignment/distribution, true bypass and edge auto-pan"
    )


if __name__ == "__main__":
    main()
