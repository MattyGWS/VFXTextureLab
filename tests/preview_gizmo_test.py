from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.ui.preview import PreviewCanvas, PreviewPanel, array_to_qimage


def make_canvas() -> tuple[QApplication, PreviewCanvas]:
    app = QApplication.instance() or QApplication([])
    canvas = PreviewCanvas()
    canvas.resize(720, 560)
    image = np.zeros((128, 192, 4), dtype=np.float32)
    image[..., :3] = 0.35
    image[..., 3] = 1.0
    canvas.set_image(array_to_qimage(image, "color"))
    canvas.show()
    app.processEvents()
    return app, canvas


def assert_transform_gizmo() -> None:
    app, canvas = make_canvas()
    changes: list[dict] = []
    started: list[str] = []
    finished: list[str] = []
    canvas.gizmoEditStarted.connect(started.append)
    canvas.gizmoParametersChanged.connect(lambda _uid, values: changes.append(dict(values)))
    canvas.gizmoEditFinished.connect(finished.append)
    canvas.set_gizmo_context(
        "transform-node",
        "transform.basic",
        {"offset_x": 0.0, "offset_y": 0.0, "scale": 1.0, "scale_x": 1.0, "scale_y": 1.0, "angle": 0.0},
    )
    app.processEvents()
    center = canvas._uv_to_widget(0.5, 0.5)
    hit = canvas._gizmo_hit(center)
    assert hit and hit["mode"] == "transform_move"
    canvas._begin_gizmo_drag(hit, center)
    canvas._update_gizmo_drag(canvas._uv_to_widget(0.62, 0.42))
    canvas._finish_gizmo_drag()
    assert started == ["transform-node"]
    assert finished == ["transform-node"]
    assert changes
    assert abs(float(changes[-1]["offset_x"]) - 0.12) < 0.01
    assert abs(float(changes[-1]["offset_y"]) + 0.08) < 0.01

    canvas.set_gizmo_context(
        "transform-node",
        "transform.basic",
        {"offset_x": 0.0, "offset_y": 0.0, "scale": 1.0, "scale_x": 1.0, "scale_y": 1.0, "angle": 0.0},
    )
    _center, corners, _rotation = canvas._transform_geometry()
    right_handle = canvas._transform_edge_handles(corners)["right"]
    hit = canvas._gizmo_hit(right_handle)
    assert hit and hit["mode"] == "transform_scale_axis" and hit["axis"] == "x"
    canvas._begin_gizmo_drag(hit, right_handle)
    canvas._update_gizmo_drag(canvas._uv_to_widget(0.8, 0.5))
    canvas._finish_gizmo_drag()
    assert abs(float(changes[-1]["scale_x"]) - 0.6) < 0.02
    assert "scale_y" not in changes[-1]

    # Normal Transform deliberately shares the same direct-manipulation model.
    canvas.set_gizmo_context(
        "normal-transform-node",
        "normal.transform",
        {"offset_x": 0.0, "offset_y": 0.0, "scale": 1.0, "scale_x": 1.0, "scale_y": 1.0, "angle": 30.0},
    )
    app.processEvents()
    center = canvas._uv_to_widget(0.5, 0.5)
    hit = canvas._gizmo_hit(center)
    assert hit and hit["mode"] == "transform_move"
    _center, corners, _rotation = canvas._transform_geometry()
    normal_right = canvas._transform_edge_handles(corners)["right"]
    hit = canvas._gizmo_hit(normal_right)
    assert hit and hit["mode"] == "transform_scale_axis" and hit["axis"] == "x"
    canvas.close()


def assert_clone_and_point_gizmos() -> None:
    app, canvas = make_canvas()
    canvas.set_gizmo_context(
        "clone-node",
        "transform.clone_patch",
        {"source_x": 0.2, "source_y": 0.3, "target_x": 0.7, "target_y": 0.65, "radius": 0.15},
    )
    app.processEvents()
    assert canvas._gizmo_hit(canvas._uv_to_widget(0.2, 0.3))["mode"] == "clone_source"
    assert canvas._gizmo_hit(canvas._uv_to_widget(0.7, 0.65))["mode"] == "clone_target"

    canvas.set_gizmo_context(
        "radial-node", "filter.radial_blur", {"center_x": 0.33, "center_y": 0.77}
    )
    app.processEvents()
    hit = canvas._gizmo_hit(canvas._uv_to_widget(0.33, 0.77))
    assert hit and hit["mode"] == "paired_point"
    assert hit["x_name"] == "center_x" and hit["y_name"] == "center_y"
    canvas.close()


def assert_directional_light_gizmo() -> None:
    app, canvas = make_canvas()
    changes: list[dict] = []
    canvas.gizmoParametersChanged.connect(lambda _uid, values: changes.append(dict(values)))
    canvas.set_gizmo_context(
        "light-node",
        "filter.directional_lighting",
        {"angle": 0.0, "elevation": 45.0},
    )
    app.processEvents()
    center, handle, radius = canvas._directional_light_geometry()
    hit = canvas._gizmo_hit(handle)
    assert hit and hit["mode"] == "directional_light"
    canvas._begin_gizmo_drag(hit, handle)
    canvas._update_gizmo_drag(center + QPointF(0.0, radius))
    canvas._finish_gizmo_drag()
    assert changes
    assert abs(float(changes[-1]["angle"]) - 90.0) < 0.5
    assert abs(float(changes[-1]["elevation"])) < 0.5
    canvas.close()


def assert_source_space_gizmos() -> None:
    app, canvas = make_canvas()
    params = {
        "top_left_x": 0.1,
        "top_left_y": 0.15,
        "top_right_x": 0.9,
        "top_right_y": 0.12,
        "bottom_right_x": 0.85,
        "bottom_right_y": 0.9,
        "bottom_left_x": 0.15,
        "bottom_left_y": 0.88,
    }
    canvas.set_gizmo_context("perspective", "transform.perspective", params, edit_input=False)
    app.processEvents()
    hit = canvas._gizmo_hit(canvas._uv_to_widget(0.1, 0.15))
    assert hit and hit["x_name"] == "top_left_x" and hit["y_name"] == "top_left_y"
    canvas.close()

    panel = PreviewPanel()
    panel.show()
    app.processEvents()
    panel.set_gizmo_context("perspective", "transform.perspective", params)
    assert not panel.edit_input_button.isVisible()
    assert not panel.edit_input_enabled
    panel.set_gizmo_context("crop", "transform.crop", {"left": 0.1, "right": 0.9, "top": 0.1, "bottom": 0.9})
    assert panel.edit_input_button.isVisible()
    assert not panel.edit_input_enabled
    panel.edit_input_button.setChecked(True)
    assert panel.edit_input_enabled
    panel.set_gizmo_context("transform", "transform.basic", {"scale": 1.0})
    assert not panel.edit_input_button.isVisible()
    assert not panel.edit_input_button.isChecked()
    panel.close()


def main() -> None:
    assert_transform_gizmo()
    assert_clone_and_point_gizmos()
    assert_directional_light_gizmo()
    assert_source_space_gizmos()
    print("2D Preview gizmo checks passed")


if __name__ == "__main__":
    main()
