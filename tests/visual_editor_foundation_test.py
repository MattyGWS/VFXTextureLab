from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QWidget

from vfx_texture_lab.graph.scene import GraphScene
from vfx_texture_lab.main_window import MainWindow
from vfx_texture_lab.nodes.registry import build_registry
from vfx_texture_lab.ui.parameters import (
    AdjustmentHistogramWidget,
    CurveControl,
    CurveGraphWidget,
    GradientControl,
    GradientRampWidget,
    HistogramAdjustmentControl,
    LevelsControl,
    LevelsHistogramWidget,
    ParametersPanel,
)
from vfx_texture_lab.ui.visual_editor_foundation import PALETTE, VisualEditorCanvas



def assert_graph_delete_shortcut_is_canvas_scoped() -> None:
    source = inspect.getsource(MainWindow._build_actions)
    assert "self.delete_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)" in source
    assert "self.graph_view.addAction(self.delete_action)" in source

def assert_shared_foundation() -> None:
    for editor_type in (CurveGraphWidget, GradientRampWidget, LevelsHistogramWidget, AdjustmentHistogramWidget):
        assert issubclass(editor_type, VisualEditorCanvas)
    assert PALETTE.background.startswith("#")

    curve = CurveGraphWidget([{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}])
    gradient = GradientRampWidget([
        {"position": 0.0, "color": "#000000ff"},
        {"position": 1.0, "color": "#ffffffff"},
    ])
    levels = LevelsHistogramWidget({
        "in_low": 0.0, "in_high": 1.0, "in_mid": 0.5,
        "out_low": 0.0, "out_high": 1.0,
    })
    adjustment = AdjustmentHistogramWidget("range", {"range": 1.0, "position": 0.5})

    assert curve.height() == 250
    assert gradient.height() == 118
    assert levels.height() == 230
    assert adjustment.height() == 230


def assert_keyboard_nudging(app: QApplication) -> None:
    curve = CurveGraphWidget([{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}])
    curve.show()
    curve.setFocus()
    QTest.keyClick(curve, Qt.Key.Key_Right)
    QTest.keyClick(curve, Qt.Key.Key_Up, Qt.KeyboardModifier.ShiftModifier)
    app.processEvents()
    point = curve.selected_point()
    assert point is not None
    assert abs(float(point["x"]) - 0.01) < 1e-6
    assert abs(float(point["y"]) - 0.001) < 1e-6

    stops = [
        {"position": 0.0, "color": "#000000ff"},
        {"position": 1.0, "color": "#ffffffff"},
    ]
    gradient = GradientRampWidget(stops)
    gradient.show()
    gradient.setFocus()
    QTest.keyClick(gradient, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    app.processEvents()
    assert abs(float(gradient.selected_stop["position"]) - 0.001) < 1e-6

    levels = LevelsHistogramWidget({
        "in_low": 0.0, "in_high": 1.0, "in_mid": 0.5,
        "out_low": 0.0, "out_high": 1.0,
    })
    levels.show()
    levels.setFocus()
    QTest.keyClick(levels, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    app.processEvents()
    assert abs(float(levels.values["in_mid"]) - 0.501) < 0.0001

    adjustment = AdjustmentHistogramWidget("shift", {"position": 0.0})
    adjustment.show()
    adjustment.setFocus()
    QTest.keyClick(adjustment, Qt.Key.Key_Right)
    app.processEvents()
    assert abs(float(adjustment.values["position"]) - 0.01) < 1e-6

    for widget in (curve, gradient, levels, adjustment):
        widget.close()



def assert_delete_is_owned_by_visual_editor(app: QApplication) -> None:
    curve = CurveGraphWidget([
        {"x": 0.0, "y": 0.0},
        {"x": 0.5, "y": 0.65},
        {"x": 1.0, "y": 1.0},
    ])
    curve.selected_index = 1
    curve.show()
    curve.setFocus()
    QTest.keyClick(curve, Qt.Key.Key_Delete)
    app.processEvents()
    assert len(curve.points) == 2

    # The required final two points cannot be removed, but Delete remains
    # consumed by the editor instead of being allowed to reach graph deletion.
    QTest.keyClick(curve, Qt.Key.Key_Delete)
    app.processEvents()
    assert len(curve.points) == 2

    gradient = GradientRampWidget([
        {"position": 0.0, "color": "#000000ff"},
        {"position": 0.5, "color": "#ff0000ff"},
        {"position": 1.0, "color": "#ffffffff"},
    ])
    gradient.selected_stop = gradient.stops[1]
    gradient.show()
    gradient.setFocus()
    QTest.keyClick(gradient, Qt.Key.Key_Delete)
    app.processEvents()
    assert len(gradient.stops) == 2

    QTest.keyClick(gradient, Qt.Key.Key_Backspace)
    app.processEvents()
    assert len(gradient.stops) == 2

    curve.close()
    gradient.close()

def assert_debounced_final_flush(app: QApplication) -> None:
    graph = CurveGraphWidget([{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}])
    spy = QSignalSpy(graph.pointsChanged)
    graph.begin_interaction()
    graph.set_selected_point(0.05, 0.1)
    graph.set_selected_point(0.10, 0.2)
    assert spy.count() == 0
    graph.end_interaction()
    app.processEvents()
    assert spy.count() == 1
    payload = spy.at(0)[0]
    assert abs(float(payload[0]["x"]) - 0.10) < 1e-6
    assert abs(float(payload[0]["y"]) - 0.20) < 1e-6


def assert_inline_gradient_control() -> None:
    seen: list[list[dict]] = []
    control = GradientControl(
        [{"position": 0.0, "color": "#000000ff"}, {"position": 1.0, "color": "#ffffffff"}],
        lambda value: seen.append(value),
    )
    assert isinstance(control, QWidget)
    assert control.ramp.parent() is control
    assert control.add_button.text() == "Add"
    assert control.reset_button.text() == "Reset"
    control.ramp.add_stop_at(0.5)
    assert seen and len(seen[-1]) == 3


def assert_drag_is_one_undo_step(app: QApplication) -> None:
    scene = GraphScene(build_registry())
    panel = ParametersPanel(scene)
    panel.resize(520, 760)
    panel.show()
    node = scene.create_node("filter.curve", QPointF(0.0, 0.0), record_undo=False)
    panel.set_item(node)
    app.processEvents()
    control = panel.findChild(CurveControl)
    assert control is not None

    # Multiple live publications during one drag remain inside one outer graph
    # transaction.  A second drag intentionally creates a second undo command.
    control.graph.begin_interaction()
    control.graph.set_selected_point(0.08, 0.15)
    QTest.qWait(50)
    control.graph.set_selected_point(0.16, 0.25)
    QTest.qWait(50)
    control.graph.end_interaction()
    app.processEvents()
    assert scene.undo_stack.count() == 1
    assert scene.undo_stack.text(0) == "Edit Curve"

    control.graph.begin_interaction()
    control.graph.set_selected_point(0.22, 0.35)
    control.graph.end_interaction()
    app.processEvents()
    assert scene.undo_stack.count() == 2

    scene.undo_stack.undo()
    app.processEvents()
    restored = scene.nodes[node.uid]
    assert abs(float(restored.parameters["points"][0]["x"]) - 0.16) < 1e-6
    assert abs(float(restored.parameters["points"][0]["y"]) - 0.25) < 1e-6
    panel.close()



def assert_every_editor_drag_is_transactional(app: QApplication) -> None:
    cases = [
        (
            "convert.gradient_map",
            GradientControl,
            lambda control: (
                control.ramp.begin_interaction(),
                control.ramp.set_selected_position(0.18, immediate=False),
                control.ramp.set_selected_position(0.26, immediate=False),
                control.ramp.end_interaction(),
            ),
        ),
        (
            "filter.levels",
            LevelsControl,
            lambda control: (
                control.histogram.begin_interaction(),
                control.histogram._apply_drag("in_mid", control.histogram._x_for_value(0.62)),
                control.histogram._apply_drag("in_mid", control.histogram._x_for_value(0.68)),
                control.histogram.end_interaction(),
            ),
        ),
        (
            "filter.histogram_range",
            HistogramAdjustmentControl,
            lambda control: (
                control.histogram.begin_interaction(),
                control.histogram._apply_guide(0, 0.12, immediate=False),
                control.histogram._apply_guide(0, 0.18, immediate=False),
                control.histogram.end_interaction(),
            ),
        ),
    ]
    for type_id, control_type, perform in cases:
        scene = GraphScene(build_registry())
        panel = ParametersPanel(scene)
        panel.resize(520, 760)
        panel.show()
        node = scene.create_node(type_id, QPointF(0.0, 0.0), record_undo=False)
        panel.set_item(node)
        app.processEvents()
        control = panel.findChild(control_type)
        assert control is not None
        perform(control)
        app.processEvents()
        assert scene.undo_stack.count() == 1, type_id
        panel.close()

def main() -> None:
    app = QApplication.instance() or QApplication([])
    assert_graph_delete_shortcut_is_canvas_scoped()
    assert_shared_foundation()
    assert_keyboard_nudging(app)
    assert_delete_is_owned_by_visual_editor(app)
    assert_debounced_final_flush(app)
    assert_inline_gradient_control()
    assert_drag_is_one_undo_step(app)
    assert_every_editor_drag_is_transactional(app)
    print(
        "visual editor foundation test passed: shared canvases, fixed sizing, inline gradient, "
        "keyboard precision, editor-local deletion, debounced final values and one-command drag undo"
    )


if __name__ == "__main__":
    main()
