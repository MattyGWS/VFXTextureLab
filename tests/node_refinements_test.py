from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.engine.evaluator import GraphEvaluator
from vfx_texture_lab.graph.scene import GraphScene
from vfx_texture_lab.nodes.registry import build_registry
from vfx_texture_lab.ui.parameters import GradientRampWidget


def assert_auto_levels_is_neutral_greyscale(registry) -> None:
    scene = GraphScene(registry)
    gradient = scene.create_node("generator.linear_gradient", QPointF(0, 0), record_undo=False)
    auto = scene.create_node("filter.auto_levels", QPointF(260, 0), record_undo=False)
    scene.add_connection(gradient.output_port, auto.input_ports["Image"], record_undo=False)

    cpu = GraphEvaluator(scene, backend_preference="cpu").evaluate(auto.uid, 64, 32)
    assert cpu.error is None, cpu.error
    assert np.max(np.abs(cpu.image[..., 0] - cpu.image[..., 1])) < 1e-6
    assert np.max(np.abs(cpu.image[..., 1] - cpu.image[..., 2])) < 1e-6
    assert float(cpu.image[..., 0].min()) <= 0.01
    assert float(cpu.image[..., 0].max()) >= 0.99

    gpu_evaluator = GraphEvaluator(scene, backend_preference="gpu")
    if gpu_evaluator.gpu_available:
        gpu = gpu_evaluator.evaluate(auto.uid, 64, 32)
        assert gpu.error is None, gpu.error
        assert np.max(np.abs(gpu.image[..., 0] - gpu.image[..., 1])) < 2e-3
        assert np.max(np.abs(gpu.image[..., 1] - gpu.image[..., 2])) < 2e-3
        assert float(gpu.image[..., 0].min()) <= 0.02
        assert float(gpu.image[..., 0].max()) >= 0.98


def assert_io_category_is_flat(registry) -> None:
    expected = "Inputs & Outputs"
    assert registry.get("input.image").category == expected
    assert registry.get("output.image").category == expected
    assert "/" not in expected


def assert_gradient_ramp_interactions(app: QApplication) -> None:
    stops = [
        {"position": 0.0, "color": "#000000ff"},
        {"position": 1.0, "color": "#ffffffff"},
    ]
    ramp = GradientRampWidget(stops)
    ramp.resize(600, 92)
    ramp.show()
    app.processEvents()

    rect = ramp.gradient_rect()
    quarter = QPoint(round(rect.left() + rect.width() * 0.25), round(rect.center().y()))
    QTest.mouseDClick(ramp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, quarter)
    app.processEvents()
    assert len(stops) == 3
    assert ramp.selected_stop is not None
    assert abs(float(ramp.selected_stop["position"]) - 0.25) < 0.02
    # The automatically inserted colour should be interpolated, not hard-coded.
    assert str(ramp.selected_stop["color"]).lower() not in {"#000000ff", "#ffffffff"}

    start = ramp.marker_position(ramp.selected_stop).toPoint()
    target = QPoint(round(rect.left() + rect.width() * 0.72), start.y())
    QTest.mousePress(ramp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(ramp, target, 30)
    QTest.mouseRelease(ramp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, target)
    app.processEvents()
    assert abs(float(ramp.selected_stop["position"]) - 0.72) < 0.03

    colour_spy = QSignalSpy(ramp.editColourRequested)
    marker = ramp.marker_position(ramp.selected_stop).toPoint()
    QTest.mouseDClick(ramp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, marker)
    app.processEvents()
    assert colour_spy.count() == 1

    ramp.setFocus()
    QTest.keyClick(ramp, Qt.Key.Key_Delete)
    app.processEvents()
    assert len(stops) == 2
    ramp.close()


def main() -> None:
    app = QApplication.instance() or QApplication([])
    registry = build_registry()
    assert_auto_levels_is_neutral_greyscale(registry)
    assert_io_category_is_flat(registry)
    assert_gradient_ramp_interactions(app)
    print(
        "Node refinements test passed: neutral Auto Levels, flat Inputs & Outputs category, "
        "and direct add/select/drag/edit/delete gradient-stop interactions"
    )


if __name__ == "__main__":
    main()
