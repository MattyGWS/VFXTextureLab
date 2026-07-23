from __future__ import annotations

import math
import time
from typing import Any, Mapping

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, QSizeF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPolygonF, QWheelEvent
from ..theme import theme_colour

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


def _linear_to_srgb(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, 0.0, 1.0)
    return np.where(values <= 0.0031308, values * 12.92, 1.055 * np.power(values, 1.0 / 2.4) - 0.055)


def array_to_qimage(image: np.ndarray, data_kind: str = "color") -> QImage:
    display = np.clip(image, 0.0, 1.0).copy()
    if data_kind == "grayscale":
        display[..., 0:3] = display[..., 0:1]
    elif data_kind == "color":
        # The graph works in linear light. Convert only the display copy to
        # monitor sRGB; exports and downstream nodes keep untouched linear data.
        display[..., :3] = _linear_to_srgb(display[..., :3])
    elif data_kind == "vector":
        # Vector channels may use alpha as authored data (Flood Fill stores its
        # ordered island index there). Keep vector previews opaque without
        # changing the graph resource or exported values.
        display[..., 3] = 1.0
    # Vector/normal data is deliberately displayed as raw encoded 0..1 values.
    rgba = (display * 255.0 + 0.5).astype(np.uint8)
    height, width, _channels = rgba.shape
    return QImage(rgba.data, width, height, width * 4, QImage.Format.Format_RGBA8888).copy()


def rgba8_to_qimage(image: np.ndarray) -> QImage:
    rgba = np.ascontiguousarray(image, dtype=np.uint8)
    height, width, _channels = rgba.shape
    return QImage(
        rgba.data, width, height, width * 4, QImage.Format.Format_RGBA8888
    ).copy()


class PreviewCanvas(QWidget):
    zoomChanged = Signal(float)
    gizmoEditStarted = Signal(str)
    gizmoParametersChanged = Signal(str, object)
    gizmoEditFinished = Signal(str)

    MIN_ZOOM = 0.15
    MAX_ZOOM = 32.0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._image = QImage()
        self._tile_preview = False
        self._zoom = 1.0
        self._fit_mode = True
        self._manual_scale = 1.0
        self._pan = QPointF()
        self._panning = False
        self._pan_start = QPoint()
        self._gizmo_node_uid = ""
        self._gizmo_type_id = ""
        self._gizmo_parameters: dict[str, Any] = {}
        self._gizmo_edit_input = False
        self._gizmo_drag: dict[str, Any] | None = None
        self.setMinimumSize(280, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    def set_gizmo_context(
        self,
        node_uid: str | None,
        type_id: str | None,
        parameters: Mapping[str, Any] | None,
        *,
        edit_input: bool = False,
    ) -> None:
        self._gizmo_node_uid = str(node_uid or "")
        self._gizmo_type_id = str(type_id or "")
        self._gizmo_parameters = dict(parameters or {})
        self._gizmo_edit_input = bool(edit_input)
        if self._gizmo_drag is None:
            self.unsetCursor()
        self.update()

    def clear_gizmo(self) -> None:
        self.set_gizmo_context(None, None, None)

    @property
    def zoom(self) -> float:
        # Kept as a fit-relative value for compatibility with existing tests
        # and callers. The artist-facing readout uses display_scale instead.
        if self._fit_mode:
            return 1.0
        return self._manual_scale / max(self._fit_scale(), 1.0e-9)

    @property
    def display_scale(self) -> float:
        return self._display_scale()

    @property
    def tile_preview(self) -> bool:
        return self._tile_preview

    def set_image(self, image: QImage) -> None:
        was_empty = self._image.isNull()
        self._image = image
        if was_empty and not image.isNull():
            self.reset_view()
        else:
            self.zoomChanged.emit(self._display_scale())
            self.update()

    def set_tile_preview(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._tile_preview:
            return
        self._tile_preview = enabled
        self.reset_view()

    def reset_view(self) -> None:
        self._zoom = 1.0
        self._fit_mode = True
        self._pan = QPointF()
        self.zoomChanged.emit(self._display_scale())
        self.update()

    def set_one_to_one(self) -> None:
        if self._image.isNull():
            return
        self._fit_mode = False
        self._manual_scale = 1.0
        self._zoom = 1.0 / max(self._fit_scale(), 1.0e-9)
        self._pan = QPointF()
        self.zoomChanged.emit(1.0)
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._image.isNull():
            event.ignore()
            return

        old_scale = self._display_scale()
        old_origin = self._content_origin(old_scale)
        mouse = event.position()
        if old_scale <= 0.0:
            return
        content_position = (mouse - old_origin) / old_scale

        factor = 1.2 if event.angleDelta().y() > 0 else 1.0 / 1.2
        new_scale = min(128.0, max(0.01, old_scale * factor))
        if abs(new_scale - old_scale) < 1e-9:
            event.accept()
            return

        self._fit_mode = False
        self._manual_scale = new_scale
        self._zoom = new_scale / max(self._fit_scale(), 1.0e-9)
        content_size = self._content_size()
        base_origin = QPointF(
            self.width() * 0.5 - content_size.width() * new_scale * 0.5,
            self.height() * 0.5 - content_size.height() * new_scale * 0.5,
        )
        self._pan = mouse - content_position * new_scale - base_origin
        self.zoomChanged.emit(new_scale)
        self.update()
        event.accept()

    def _gizmo_rect(self) -> QRectF:
        if self._image.isNull():
            return QRectF()
        scale = self._display_scale()
        origin = self._content_origin(scale)
        tile_width = self._image.width() * scale
        tile_height = self._image.height() * scale
        if self._tile_preview:
            origin += QPointF(tile_width, tile_height)
        return QRectF(origin.x(), origin.y(), tile_width, tile_height)

    def _uv_to_widget(self, u: float, v: float) -> QPointF:
        rect = self._gizmo_rect()
        return QPointF(rect.left() + float(u) * rect.width(), rect.top() + float(v) * rect.height())

    def _widget_to_uv(self, point: QPointF) -> QPointF:
        rect = self._gizmo_rect()
        if rect.width() <= 1.0e-8 or rect.height() <= 1.0e-8:
            return QPointF()
        return QPointF(
            (point.x() - rect.left()) / rect.width(),
            (point.y() - rect.top()) / rect.height(),
        )

    @staticmethod
    def _rotate_vector(x: float, y: float, angle_degrees: float) -> tuple[float, float]:
        angle = math.radians(float(angle_degrees))
        cosine = math.cos(angle)
        sine = math.sin(angle)
        return x * cosine - y * sine, x * sine + y * cosine

    def _transform_geometry(self) -> tuple[QPointF, list[QPointF], QPointF]:
        params = self._gizmo_parameters
        center_u = 0.5 + float(params.get("offset_x", 0.0))
        center_v = 0.5 + float(params.get("offset_y", 0.0))
        uniform_scale = max(float(params.get("scale", 1.0)), 0.01)
        scale_x = max(float(params.get("scale_x", 1.0)) * uniform_scale, 0.01)
        scale_y = max(float(params.get("scale_y", 1.0)) * uniform_scale, 0.01)
        angle = float(params.get("angle", 0.0))
        center = self._uv_to_widget(center_u, center_v)
        rect = self._gizmo_rect()
        corners: list[QPointF] = []
        for local_x, local_y in ((-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)):
            # Rotation is defined in physical image pixels, not normalised UVs.
            # Using the displayed texture's pixel aspect here keeps the gizmo
            # faithful on rectangular documents as well as square ones.
            local_px_x = local_x * scale_x * rect.width()
            local_px_y = local_y * scale_y * rect.height()
            rotated_x, rotated_y = self._rotate_vector(local_px_x, local_px_y, angle)
            corners.append(center + QPointF(rotated_x, rotated_y))
        top_mid = (corners[0] + corners[1]) * 0.5
        direction = top_mid - center
        length = math.hypot(direction.x(), direction.y())
        if length <= 1.0e-6:
            rotation_handle = top_mid + QPointF(0.0, -28.0)
        else:
            rotation_handle = top_mid + direction * (28.0 / length)
        return center, corners, rotation_handle

    @staticmethod
    def _transform_edge_handles(corners: list[QPointF]) -> dict[str, QPointF]:
        return {
            "top": (corners[0] + corners[1]) * 0.5,
            "right": (corners[1] + corners[2]) * 0.5,
            "bottom": (corners[2] + corners[3]) * 0.5,
            "left": (corners[3] + corners[0]) * 0.5,
        }

    def _perspective_points(self) -> list[tuple[str, str, QPointF]]:
        params = self._gizmo_parameters
        return [
            ("top_left_x", "top_left_y", self._uv_to_widget(float(params.get("top_left_x", 0.0)), float(params.get("top_left_y", 0.0)))),
            ("top_right_x", "top_right_y", self._uv_to_widget(float(params.get("top_right_x", 1.0)), float(params.get("top_right_y", 0.0)))),
            ("bottom_right_x", "bottom_right_y", self._uv_to_widget(float(params.get("bottom_right_x", 1.0)), float(params.get("bottom_right_y", 1.0)))),
            ("bottom_left_x", "bottom_left_y", self._uv_to_widget(float(params.get("bottom_left_x", 0.0)), float(params.get("bottom_left_y", 1.0)))),
        ]

    def _crop_points(self) -> list[tuple[str, str, QPointF]]:
        params = self._gizmo_parameters
        left = float(params.get("left", 0.0))
        right = float(params.get("right", 1.0))
        top = float(params.get("top", 0.0))
        bottom = float(params.get("bottom", 1.0))
        return [
            ("left", "top", self._uv_to_widget(left, top)),
            ("right", "top", self._uv_to_widget(right, top)),
            ("right", "bottom", self._uv_to_widget(right, bottom)),
            ("left", "bottom", self._uv_to_widget(left, bottom)),
        ]

    def _splatter_geometry(self) -> tuple[QPointF, list[tuple[float, QPolygonF]], QPointF, QPointF, QPointF]:
        params = self._gizmo_parameters
        center = self._uv_to_widget(float(params.get("center_x", 0.5)), float(params.get("center_y", 0.5)))
        ring_amount = min(max(int(params.get("ring_amount", 3)), 1), 10)
        first_radius = float(params.get("first_ring_radius", 0.15))
        ring_spacing = float(params.get("ring_spacing", 0.12))
        spread = min(max(float(params.get("arc_spread", 360.0)), 1.0), 360.0)
        rotation = float(params.get("ring_rotation", 0.0))
        rotation_offset = float(params.get("ring_rotation_offset", 0.0))
        spiral = float(params.get("spiral", 0.0))
        radius_pixels = max(self._gizmo_rect().height(), 1.0)
        guides: list[tuple[float, QPolygonF]] = []
        for ring in range(ring_amount):
            points = QPolygonF()
            start = rotation + ring * rotation_offset
            samples = max(24, int(spread / 5.0) + 1)
            for index in range(samples):
                t = index / max(samples - 1, 1)
                angle = math.radians(start + spread * t)
                radius = first_radius + ring * ring_spacing + spiral * t
                points.append(center + QPointF(math.cos(angle) * radius * radius_pixels, math.sin(angle) * radius * radius_pixels))
            guides.append((first_radius + ring * ring_spacing, points))
        first_angle = math.radians(rotation)
        first_handle = center + QPointF(math.cos(first_angle) * first_radius * radius_pixels, math.sin(first_angle) * first_radius * radius_pixels)
        outer_radius = first_radius + max(ring_amount - 1, 0) * ring_spacing
        outer_handle = center + QPointF(math.cos(first_angle) * outer_radius * radius_pixels, math.sin(first_angle) * outer_radius * radius_pixels)
        rotate_angle = math.radians(rotation - 90.0)
        rotation_handle = center + QPointF(math.cos(rotate_angle) * max(abs(outer_radius), abs(first_radius), 0.08) * radius_pixels, math.sin(rotate_angle) * max(abs(outer_radius), abs(first_radius), 0.08) * radius_pixels)
        return center, guides, first_handle, outer_handle, rotation_handle

    def _directional_light_geometry(self) -> tuple[QPointF, QPointF, float]:
        rect = self._gizmo_rect()
        center = self._uv_to_widget(0.5, 0.5)
        radius = max(min(rect.width(), rect.height()) * 0.30, 24.0)
        angle = math.radians(float(self._gizmo_parameters.get("angle", 45.0)))
        elevation = math.radians(min(max(float(self._gizmo_parameters.get("elevation", 45.0)), 0.0), 90.0))
        projected = radius * math.cos(elevation)
        handle = center + QPointF(math.cos(angle) * projected, math.sin(angle) * projected)
        return center, handle, radius

    def _point_gizmo(self) -> QPointF | None:
        params = self._gizmo_parameters
        if "center_x" in params and "center_y" in params:
            return self._uv_to_widget(float(params.get("center_x", 0.5)), float(params.get("center_y", 0.5)))
        return None

    @staticmethod
    def _near(point: QPointF, target: QPointF, radius: float = 9.0) -> bool:
        return math.hypot(point.x() - target.x(), point.y() - target.y()) <= radius

    def _gizmo_hit(self, point: QPointF) -> dict[str, Any] | None:
        if not self._gizmo_node_uid or self._image.isNull():
            return None
        type_id = self._gizmo_type_id
        if type_id in {"transform.basic", "normal.transform"}:
            center, corners, rotation = self._transform_geometry()
            if self._near(point, rotation, 10.0):
                return {"mode": "transform_rotate"}
            edge_handles = self._transform_edge_handles(corners)
            for edge_name, handle in edge_handles.items():
                if self._near(point, handle, 10.0):
                    axis = "x" if edge_name in {"left", "right"} else "y"
                    return {"mode": "transform_scale_axis", "axis": axis, "edge": edge_name}
            for index, corner in enumerate(corners):
                if self._near(point, corner, 10.0):
                    return {"mode": "transform_scale_uniform", "index": index}
            if self._near(point, center, 10.0):
                return {"mode": "transform_move"}
            polygon = QPolygonF(corners)
            if polygon.containsPoint(point, Qt.FillRule.OddEvenFill):
                return {"mode": "transform_move"}
        elif type_id == "pattern.splatter_circular":
            center, _guides, first_handle, outer_handle, rotation_handle = self._splatter_geometry()
            if self._near(point, rotation_handle, 10.0):
                return {"mode": "splatter_rotation"}
            if self._near(point, outer_handle, 10.0):
                return {"mode": "splatter_outer_radius"}
            if self._near(point, first_handle, 10.0):
                return {"mode": "splatter_first_radius"}
            if self._near(point, center, 10.0):
                return {"mode": "paired_point", "x_name": "center_x", "y_name": "center_y"}
        elif type_id == "filter.directional_lighting":
            _center, handle, _radius = self._directional_light_geometry()
            if self._near(point, handle, 12.0):
                return {"mode": "directional_light"}
        elif type_id == "transform.clone_patch":
            source = self._uv_to_widget(
                float(self._gizmo_parameters.get("source_x", 0.25)),
                float(self._gizmo_parameters.get("source_y", 0.25)),
            )
            target = self._uv_to_widget(
                float(self._gizmo_parameters.get("target_x", 0.75)),
                float(self._gizmo_parameters.get("target_y", 0.75)),
            )
            radius_pixels = float(self._gizmo_parameters.get("radius", 0.12)) * min(
                self._gizmo_rect().width(), self._gizmo_rect().height()
            )
            radius_handle = target + QPointF(radius_pixels, 0.0)
            if self._near(point, source, 10.0):
                return {"mode": "clone_source"}
            if self._near(point, radius_handle, 10.0):
                return {"mode": "clone_radius"}
            if self._near(point, target, 10.0):
                return {"mode": "clone_target"}
        elif type_id == "transform.perspective":
            for x_name, y_name, handle in self._perspective_points():
                if self._near(point, handle, 10.0):
                    return {"mode": "paired_point", "x_name": x_name, "y_name": y_name}
        elif type_id == "transform.crop" and self._gizmo_edit_input:
            for x_name, y_name, handle in self._crop_points():
                if self._near(point, handle, 10.0):
                    return {"mode": "paired_point", "x_name": x_name, "y_name": y_name}
        else:
            center = self._point_gizmo()
            if center is not None and self._near(point, center, 10.0):
                return {"mode": "paired_point", "x_name": "center_x", "y_name": "center_y"}
        return None

    def _emit_gizmo_changes(self, changes: Mapping[str, Any]) -> None:
        if not changes or not self._gizmo_node_uid:
            return
        self._gizmo_parameters.update(dict(changes))
        self.gizmoParametersChanged.emit(self._gizmo_node_uid, dict(changes))
        self.update()

    def _begin_gizmo_drag(self, hit: Mapping[str, Any], point: QPointF) -> None:
        self._gizmo_drag = {
            **dict(hit),
            "start_widget": QPointF(point),
            "start_uv": self._widget_to_uv(point),
            "start_parameters": dict(self._gizmo_parameters),
        }
        if str(hit.get("mode")) == "transform_rotate":
            center, _corners, _rotation = self._transform_geometry()
            self._gizmo_drag["start_pointer_angle"] = math.degrees(
                math.atan2(point.y() - center.y(), point.x() - center.x())
            )
        if str(hit.get("mode")) == "splatter_rotation":
            center, _guides, _first, _outer, _rotation = self._splatter_geometry()
            self._gizmo_drag["start_pointer_angle"] = math.degrees(
                math.atan2(point.y() - center.y(), point.x() - center.x())
            )
        if str(hit.get("mode")) == "transform_scale_uniform":
            center, _corners, _rotation = self._transform_geometry()
            self._gizmo_drag["start_distance"] = max(
                math.hypot(point.x() - center.x(), point.y() - center.y()), 1.0e-6
            )
        self.gizmoEditStarted.emit(self._gizmo_node_uid)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _update_gizmo_drag(self, point: QPointF) -> None:
        drag = self._gizmo_drag
        if drag is None:
            return
        mode = str(drag.get("mode", ""))
        start = dict(drag.get("start_parameters", {}))
        uv = self._widget_to_uv(point)
        if mode == "transform_move":
            start_uv = drag["start_uv"]
            self._emit_gizmo_changes({
                "offset_x": float(start.get("offset_x", 0.0)) + uv.x() - start_uv.x(),
                "offset_y": float(start.get("offset_y", 0.0)) + uv.y() - start_uv.y(),
            })
        elif mode == "transform_scale_uniform":
            center_u = 0.5 + float(start.get("offset_x", 0.0))
            center_v = 0.5 + float(start.get("offset_y", 0.0))
            center = self._uv_to_widget(center_u, center_v)
            current_distance = math.hypot(point.x() - center.x(), point.y() - center.y())
            scale = float(start.get("scale", 1.0)) * current_distance / max(float(drag.get("start_distance", 1.0)), 1.0e-6)
            self._emit_gizmo_changes({"scale": min(max(scale, 0.01), 100.0)})
        elif mode == "transform_scale_axis":
            center_u = 0.5 + float(start.get("offset_x", 0.0))
            center_v = 0.5 + float(start.get("offset_y", 0.0))
            center = self._uv_to_widget(center_u, center_v)
            local_x = point.x() - center.x()
            local_y = point.y() - center.y()
            local_x, local_y = self._rotate_vector(local_x, local_y, -float(start.get("angle", 0.0)))
            uniform = max(float(start.get("scale", 1.0)), 0.01)
            rect = self._gizmo_rect()
            axis = str(drag.get("axis", "x"))
            if axis == "x":
                authored = min(max(abs(local_x) * 2.0 / max(rect.width() * uniform, 1.0e-6), 0.01), 100.0)
                self._emit_gizmo_changes({"scale_x": authored})
            else:
                authored = min(max(abs(local_y) * 2.0 / max(rect.height() * uniform, 1.0e-6), 0.01), 100.0)
                self._emit_gizmo_changes({"scale_y": authored})
        elif mode == "transform_rotate":
            center_u = 0.5 + float(start.get("offset_x", 0.0))
            center_v = 0.5 + float(start.get("offset_y", 0.0))
            center = self._uv_to_widget(center_u, center_v)
            current_angle = math.degrees(math.atan2(point.y() - center.y(), point.x() - center.x()))
            delta = current_angle - float(drag.get("start_pointer_angle", current_angle))
            while delta > 180.0:
                delta -= 360.0
            while delta < -180.0:
                delta += 360.0
            self._emit_gizmo_changes({"angle": float(start.get("angle", 0.0)) + delta})
        elif mode == "splatter_first_radius":
            center = self._uv_to_widget(float(start.get("center_x", 0.5)), float(start.get("center_y", 0.5)))
            radius = math.hypot(point.x() - center.x(), point.y() - center.y()) / max(self._gizmo_rect().height(), 1.0)
            self._emit_gizmo_changes({"first_ring_radius": min(max(radius, 0.0), 2.0)})
        elif mode == "splatter_outer_radius":
            center = self._uv_to_widget(float(start.get("center_x", 0.5)), float(start.get("center_y", 0.5)))
            outer = math.hypot(point.x() - center.x(), point.y() - center.y()) / max(self._gizmo_rect().height(), 1.0)
            rings = max(int(start.get("ring_amount", 3)), 1)
            if rings <= 1:
                self._emit_gizmo_changes({"first_ring_radius": min(max(outer, 0.0), 2.0)})
            else:
                spacing = (outer - float(start.get("first_ring_radius", 0.15))) / (rings - 1)
                self._emit_gizmo_changes({"ring_spacing": min(max(spacing, -1.0), 1.0)})
        elif mode == "splatter_rotation":
            center = self._uv_to_widget(float(start.get("center_x", 0.5)), float(start.get("center_y", 0.5)))
            current_angle = math.degrees(math.atan2(point.y() - center.y(), point.x() - center.x()))
            delta = current_angle - float(drag.get("start_pointer_angle", current_angle))
            while delta > 180.0:
                delta -= 360.0
            while delta < -180.0:
                delta += 360.0
            self._emit_gizmo_changes({"ring_rotation": float(start.get("ring_rotation", 0.0)) + delta})
        elif mode == "directional_light":
            center, _handle, radius = self._directional_light_geometry()
            dx = point.x() - center.x()
            dy = point.y() - center.y()
            distance = min(max(math.hypot(dx, dy), 0.0), radius)
            changes: dict[str, float] = {
                "elevation": math.degrees(math.acos(min(max(distance / max(radius, 1.0e-6), 0.0), 1.0)))
            }
            if distance > 1.0e-5:
                changes["angle"] = math.degrees(math.atan2(dy, dx))
            self._emit_gizmo_changes(changes)
        elif mode == "clone_source":
            self._emit_gizmo_changes({"source_x": uv.x(), "source_y": uv.y()})
        elif mode == "clone_target":
            self._emit_gizmo_changes({"target_x": uv.x(), "target_y": uv.y()})
        elif mode == "clone_radius":
            target = self._uv_to_widget(
                float(start.get("target_x", 0.75)), float(start.get("target_y", 0.75))
            )
            radius = math.hypot(point.x() - target.x(), point.y() - target.y()) / max(
                min(self._gizmo_rect().width(), self._gizmo_rect().height()), 1.0
            )
            self._emit_gizmo_changes({"radius": min(max(radius, 0.001), 1.0)})
        elif mode == "paired_point":
            self._emit_gizmo_changes({str(drag["x_name"]): uv.x(), str(drag["y_name"]): uv.y()})

    def _finish_gizmo_drag(self) -> None:
        if self._gizmo_drag is None:
            return
        self._gizmo_drag = None
        self.unsetCursor()
        if self._gizmo_node_uid:
            self.gizmoEditFinished.emit(self._gizmo_node_uid)
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            not self._image.isNull()
            and event.button() == Qt.MouseButton.LeftButton
            and (hit := self._gizmo_hit(event.position())) is not None
        ):
            self._begin_gizmo_drag(hit, event.position())
            event.accept()
            return
        if not self._image.isNull() and event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.MiddleButton,
        ):
            self._panning = True
            self._pan_start = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._gizmo_drag is not None:
            self._update_gizmo_drag(event.position())
            event.accept()
            return
        if self._panning:
            current = event.position().toPoint()
            delta = current - self._pan_start
            self._pan_start = current
            self._pan += QPointF(delta)
            self.update()
            event.accept()
            return
        hit = self._gizmo_hit(event.position())
        if hit is not None:
            mode = str(hit.get("mode", ""))
            if mode in {"transform_move", "clone_source", "clone_target", "paired_point"}:
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            elif mode in {"transform_scale_uniform", "clone_radius", "splatter_first_radius", "splatter_outer_radius"}:
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif mode == "transform_scale_axis":
                self.setCursor(
                    Qt.CursorShape.SizeHorCursor
                    if str(hit.get("axis", "x")) == "x"
                    else Qt.CursorShape.SizeVerCursor
                )
            else:
                self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._gizmo_drag is not None and event.button() == Qt.MouseButton.LeftButton:
            self._finish_gizmo_drag()
            event.accept()
            return
        if self._panning and event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.MiddleButton,
        ):
            self._panning = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    @staticmethod
    def _draw_handle(painter: QPainter, point: QPointF, *, radius: float = 5.0, filled: bool = True) -> None:
        painter.save()
        accent = QColor(theme_colour("accent_hover", "#67cbbf"))
        painter.setPen(QPen(QColor("#101318"), 3.0))
        painter.setBrush(accent if filled else Qt.BrushStyle.NoBrush)
        painter.drawEllipse(point, radius, radius)
        painter.setPen(QPen(accent, 1.5))
        painter.drawEllipse(point, radius, radius)
        painter.restore()

    def _draw_cross(self, painter: QPainter, point: QPointF, radius: float = 7.0) -> None:
        accent = QColor(theme_colour("accent_hover", "#67cbbf"))
        painter.save()
        painter.setPen(QPen(QColor("#101318"), 4.0))
        painter.drawLine(point + QPointF(-radius, 0.0), point + QPointF(radius, 0.0))
        painter.drawLine(point + QPointF(0.0, -radius), point + QPointF(0.0, radius))
        painter.setPen(QPen(accent, 1.5))
        painter.drawLine(point + QPointF(-radius, 0.0), point + QPointF(radius, 0.0))
        painter.drawLine(point + QPointF(0.0, -radius), point + QPointF(0.0, radius))
        painter.restore()

    def _draw_gizmo(self, painter: QPainter) -> None:
        if not self._gizmo_node_uid or self._image.isNull():
            return
        accent = QColor(theme_colour("accent_hover", "#67cbbf"))
        outline = QPen(QColor("#101318"), 4.0)
        guide = QPen(accent, 1.5)
        guide.setCosmetic(True)
        dashed = QPen(accent, 1.5, Qt.PenStyle.DashLine)
        dashed.setCosmetic(True)
        type_id = self._gizmo_type_id
        painter.save()
        painter.setClipRect(self.rect())
        if type_id in {"transform.basic", "normal.transform"}:
            center, corners, rotation = self._transform_geometry()
            polygon = QPolygonF(corners)
            painter.setPen(outline)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(polygon)
            painter.setPen(guide)
            painter.drawPolygon(polygon)
            top_mid = (corners[0] + corners[1]) * 0.5
            painter.setPen(outline)
            painter.drawLine(top_mid, rotation)
            painter.setPen(guide)
            painter.drawLine(top_mid, rotation)
            for corner in corners:
                self._draw_handle(painter, corner)
            for edge in self._transform_edge_handles(corners).values():
                self._draw_handle(painter, edge, radius=4.5, filled=False)
            self._draw_cross(painter, center)
            self._draw_handle(painter, rotation, radius=5.5, filled=False)
        elif type_id == "pattern.splatter_circular":
            center, guides, first_handle, outer_handle, rotation_handle = self._splatter_geometry()
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for _radius, points in guides:
                painter.setPen(outline)
                painter.drawPolyline(points)
                painter.setPen(guide)
                painter.drawPolyline(points)
            painter.setPen(outline)
            painter.drawLine(center, first_handle)
            painter.drawLine(center, outer_handle)
            painter.drawLine(center, rotation_handle)
            painter.setPen(guide)
            painter.drawLine(center, first_handle)
            painter.setPen(dashed)
            painter.drawLine(center, outer_handle)
            painter.setPen(guide)
            painter.drawLine(center, rotation_handle)
            self._draw_cross(painter, center)
            self._draw_handle(painter, first_handle, radius=4.5, filled=False)
            self._draw_handle(painter, outer_handle)
            self._draw_handle(painter, rotation_handle, radius=5.5, filled=False)
        elif type_id == "filter.directional_lighting":
            center, handle, radius = self._directional_light_geometry()
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(outline)
            painter.drawEllipse(center, radius, radius)
            painter.drawLine(center, handle)
            painter.setPen(dashed)
            painter.drawEllipse(center, radius, radius)
            painter.setPen(guide)
            painter.drawLine(center, handle)
            self._draw_cross(painter, center, 6.0)
            self._draw_handle(painter, handle, radius=6.0)
        elif type_id == "transform.clone_patch":
            source = self._uv_to_widget(
                float(self._gizmo_parameters.get("source_x", 0.25)),
                float(self._gizmo_parameters.get("source_y", 0.25)),
            )
            target = self._uv_to_widget(
                float(self._gizmo_parameters.get("target_x", 0.75)),
                float(self._gizmo_parameters.get("target_y", 0.75)),
            )
            radius_pixels = float(self._gizmo_parameters.get("radius", 0.12)) * min(
                self._gizmo_rect().width(), self._gizmo_rect().height()
            )
            painter.setPen(outline)
            painter.drawLine(source, target)
            painter.setPen(dashed)
            painter.drawLine(source, target)
            painter.setPen(outline)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(target, radius_pixels, radius_pixels)
            painter.setPen(guide)
            painter.drawEllipse(target, radius_pixels, radius_pixels)
            self._draw_cross(painter, source)
            self._draw_handle(painter, target)
            self._draw_handle(painter, target + QPointF(radius_pixels, 0.0), radius=4.5, filled=False)
        elif type_id == "transform.perspective":
            points = self._perspective_points()
            polygon = QPolygonF([entry[2] for entry in points])
            painter.setPen(outline)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(polygon)
            painter.setPen(guide)
            painter.drawPolygon(polygon)
            for _x_name, _y_name, point in points:
                self._draw_handle(painter, point)
        elif type_id == "transform.crop" and self._gizmo_edit_input:
            points = self._crop_points()
            polygon = QPolygonF([entry[2] for entry in points])
            painter.setPen(outline)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(polygon)
            painter.setPen(guide)
            painter.drawPolygon(polygon)
            for _x_name, _y_name, point in points:
                self._draw_handle(painter, point)
        else:
            point = self._point_gizmo()
            if point is not None:
                self._draw_cross(painter, point, 8.0)
                painter.setPen(guide)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(point, 11.0, 11.0)
        painter.restore()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme_colour("preview_background", "#111317")))
        if self._image.isNull():
            painter.setPen(QColor(theme_colour("text_muted", "#737b88")))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Double-click a node to preview it")
            return

        scale = self._display_scale()
        origin = self._content_origin(scale)
        content_size = self._content_size()
        content_rect = QRectF(
            origin.x(),
            origin.y(),
            content_size.width() * scale,
            content_size.height() * scale,
        )

        painter.save()
        painter.setClipRect(self.rect())
        self._draw_checkerboard(painter, content_rect)

        tiles = 3 if self._tile_preview else 1
        target_width = self._image.width() * scale
        target_height = self._image.height() * scale
        # When a low-resolution texture is enlarged, preserve exact texels with
        # nearest-neighbour sampling.  When a high-resolution texture is fitted
        # smaller than one screen pixel per texel, use filtered minification to
        # avoid aliasing/crunching while retaining the complete authored preview
        # for 100% and zoomed inspection.
        painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform,
            scale < 1.0,
        )
        for tile_y in range(tiles):
            for tile_x in range(tiles):
                target = QRectF(
                    origin.x() + tile_x * target_width,
                    origin.y() + tile_y * target_height,
                    target_width,
                    target_height,
                )
                painter.drawImage(target, self._image, QRectF(self._image.rect()))

        border = QColor(theme_colour("border_strong", "#69717e")) if self._tile_preview else QColor(theme_colour("border", "#454b56"))
        painter.setPen(QPen(border, 1.0))
        painter.drawRect(content_rect.adjusted(0.5, 0.5, -0.5, -0.5))
        if self._tile_preview:
            painter.setPen(QPen(QColor(theme_colour("border_strong", "#515966")), 1.0, Qt.PenStyle.DashLine))
            for index in (1, 2):
                x = origin.x() + index * target_width
                y = origin.y() + index * target_height
                painter.drawLine(QPointF(x, origin.y()), QPointF(x, content_rect.bottom()))
                painter.drawLine(QPointF(origin.x(), y), QPointF(content_rect.right(), y))
        self._draw_gizmo(painter)
        painter.restore()

    def _content_size(self) -> QSizeF:
        tiles = 3 if self._tile_preview else 1
        return QSizeF(self._image.width() * tiles, self._image.height() * tiles)

    def _fit_scale(self) -> float:
        if self._image.isNull():
            return 1.0
        content = self._content_size()
        available_width = max(self.width() - 24.0, 1.0)
        available_height = max(self.height() - 24.0, 1.0)
        return min(available_width / content.width(), available_height / content.height())

    def _display_scale(self) -> float:
        return self._fit_scale() if self._fit_mode else self._manual_scale

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit_mode and not self._image.isNull():
            self.zoomChanged.emit(self._display_scale())

    def _content_origin(self, scale: float) -> QPointF:
        content = self._content_size()
        return QPointF(
            self.width() * 0.5 - content.width() * scale * 0.5 + self._pan.x(),
            self.height() * 0.5 - content.height() * scale * 0.5 + self._pan.y(),
        )

    @staticmethod
    def _draw_checkerboard(painter: QPainter, rect: QRectF) -> None:
        painter.save()
        painter.setClipRect(rect, Qt.ClipOperation.IntersectClip)
        painter.fillRect(rect, QColor(theme_colour("checker_dark", "#292d34")))
        tile = 14
        left = max(int(rect.left()), 0)
        top = max(int(rect.top()), 0)
        right = min(int(rect.right()) + tile, painter.viewport().right() + tile)
        bottom = min(int(rect.bottom()) + tile, painter.viewport().bottom() + tile)
        start_x = int(rect.left()) + ((left - int(rect.left())) // tile) * tile
        start_y = int(rect.top()) + ((top - int(rect.top())) // tile) * tile
        light = QColor(theme_colour("checker_light", "#3a3e46"))
        for y in range(start_y, bottom, tile):
            for x in range(start_x, right, tile):
                grid_x = (x - int(rect.left())) // tile
                grid_y = (y - int(rect.top())) // tile
                if (grid_x + grid_y) % 2 == 0:
                    painter.fillRect(QRectF(x, y, tile, tile), light)
        painter.restore()


class PreviewPanel(QWidget):
    exportRequested = Signal()
    gizmoEditStarted = Signal(str)
    gizmoParametersChanged = Signal(str, object)
    gizmoEditFinished = Signal(str)
    editInputToggled = Signal(bool)
    uvOptionsChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._raw_image: np.ndarray | None = None
        self._prepared_rgba: np.ndarray | None = None
        self._display_image = QImage()
        self._data_kind = "color"
        self._playback_details_key = ""
        self._playback_last_metadata_update = 0.0
        self._output_precision = "16-bit"
        self._busy = False
        self._gizmo_node_uid = ""
        self._gizmo_type_id = ""
        self._gizmo_parameters: dict[str, Any] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.title = QLabel("No active node")
        self.title.setObjectName("sectionTitle")
        self.info = QLabel("Double-click a node to lock it into the preview.")
        self.info.setObjectName("muted")
        self.info.setWordWrap(False)
        self.info.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.info.setFixedHeight(self.info.fontMetrics().lineSpacing() + 6)
        self._info_full_text = self.info.text()
        self._frame_base_info = ""
        self.info.setToolTip(self._info_full_text)
        self.canvas = PreviewCanvas()

        view_controls = QHBoxLayout()
        view_controls.setSpacing(5)
        self.tile_button = QToolButton()
        self.tile_button.setText("Tile 3×3")
        self.tile_button.setCheckable(True)
        self.tile_button.setToolTip("Repeat the active output in a 3 × 3 grid to inspect its seams")
        self.tile_button.toggled.connect(self.canvas.set_tile_preview)
        self.fit_button = QToolButton()
        self.fit_button.setText("Fit")
        self.fit_button.setToolTip("Fit the complete texture inside the 2D Preview")
        self.fit_button.clicked.connect(self.canvas.reset_view)
        self.one_to_one_button = QToolButton()
        self.one_to_one_button.setText("1:1")
        self.one_to_one_button.setToolTip("Display one texture pixel as one screen pixel (100% zoom)")
        self.one_to_one_button.clicked.connect(self.canvas.set_one_to_one)
        self.edit_input_button = QToolButton()
        self.edit_input_button.setText("Edit source")
        self.edit_input_button.setCheckable(True)
        self.edit_input_button.setToolTip(
            "Show the connected source image so source-space handles can be edited directly"
        )
        self.edit_input_button.setVisible(False)
        self.edit_input_button.toggled.connect(self._edit_input_toggled)
        self.uv_buttons: dict[str, QToolButton] = {}
        for key, label, tooltip, checked in (
            ("wireframe", "Wires", "Show UV triangle wireframe", True),
            ("islands", "Islands", "Tint UV islands with distinct translucent fills", True),
            ("seams", "Seams", "Highlight UV island boundaries", True),
            ("overlaps", "Overlaps", "Highlight overlapping UV triangles in red", True),
            ("checker", "Checker", "Show a checkerboard when no Preview Texture is connected", True),
        ):
            button = QToolButton()
            button.setText(label)
            button.setCheckable(True)
            button.setChecked(checked)
            button.setToolTip(tooltip)
            button.setVisible(False)
            button.toggled.connect(lambda _checked=False: self.uvOptionsChanged.emit())
            self.uv_buttons[key] = button
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("muted")
        self.canvas.zoomChanged.connect(self._zoom_changed)
        view_controls.addWidget(self.tile_button)
        view_controls.addWidget(self.fit_button)
        view_controls.addWidget(self.one_to_one_button)
        view_controls.addWidget(self.edit_input_button)
        for button in self.uv_buttons.values():
            view_controls.addWidget(button)
        view_controls.addWidget(self.zoom_label)
        view_controls.addStretch(1)
        view_hint = QLabel("Wheel: zoom · middle-drag: pan")
        view_hint.setObjectName("muted")
        view_controls.addWidget(view_hint)

        controls = QHBoxLayout()
        controls.setSpacing(5)
        self.channel_buttons: dict[str, QToolButton] = {}
        for channel in ("R", "G", "B", "A"):
            button = QToolButton()
            button.setText(channel)
            button.setCheckable(True)
            button.setChecked(True)
            button.setToolTip(f"Toggle {channel} channel")
            button.toggled.connect(self._refresh_display)
            self.channel_buttons[channel] = button
            controls.addWidget(button)
        controls.addStretch(1)

        copy_button = QPushButton("Copy")
        save_button = QPushButton("Save image…")
        copy_button.clicked.connect(self.copy_to_clipboard)
        save_button.clicked.connect(self.exportRequested)
        controls.addWidget(copy_button)
        controls.addWidget(save_button)

        layout.addWidget(self.title)
        layout.addWidget(self.info)
        layout.addLayout(view_controls)
        layout.addWidget(self.canvas, 1)
        layout.addLayout(controls)

        self.canvas.gizmoEditStarted.connect(self.gizmoEditStarted.emit)
        self.canvas.gizmoParametersChanged.connect(self.gizmoParametersChanged.emit)
        self.canvas.gizmoEditFinished.connect(self.gizmoEditFinished.emit)

    def set_uv_mode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        for button in self.uv_buttons.values():
            button.setVisible(enabled)
        self.tile_button.setVisible(not enabled)
        for button in self.channel_buttons.values():
            button.setVisible(not enabled)

    def uv_preview_options(self) -> dict[str, bool]:
        return {key: bool(button.isChecked()) for key, button in self.uv_buttons.items()}

    @property
    def edit_input_enabled(self) -> bool:
        return self.edit_input_button.isVisible() and self.edit_input_button.isChecked()

    def set_gizmo_context(
        self,
        node_uid: str | None,
        type_id: str | None,
        parameters: Mapping[str, Any] | None,
    ) -> None:
        self._gizmo_node_uid = str(node_uid or "")
        self._gizmo_type_id = str(type_id or "")
        self._gizmo_parameters = dict(parameters or {})
        source_space = self._gizmo_type_id == "transform.crop"
        self.edit_input_button.setText("Edit crop source")
        self.edit_input_button.setToolTip(
            "Show the connected source image while positioning crop bounds; the crop result remaps those bounds to the full canvas"
        )
        self.edit_input_button.setVisible(source_space)
        if not source_space and self.edit_input_button.isChecked():
            self.edit_input_button.blockSignals(True)
            self.edit_input_button.setChecked(False)
            self.edit_input_button.blockSignals(False)
        self.canvas.set_gizmo_context(
            self._gizmo_node_uid,
            self._gizmo_type_id,
            self._gizmo_parameters,
            edit_input=self.edit_input_enabled,
        )

    def _edit_input_toggled(self, checked: bool) -> None:
        self.canvas.set_gizmo_context(
            self._gizmo_node_uid,
            self._gizmo_type_id,
            self._gizmo_parameters,
            edit_input=bool(checked),
        )
        self.editInputToggled.emit(bool(checked))

    @property
    def raw_image(self) -> np.ndarray | None:
        return self._raw_image

    @property
    def display_image(self) -> QImage:
        return self._display_image

    def recommended_render_size(self, source_width: int, source_height: int) -> tuple[int, int]:
        """Return an exact RGBA8 presentation target for the authored preview.

        ``Preview max dimension`` is an artist-facing quality setting.  The old
        path quietly reduced every completed preview to at most 1024 pixels
        before it reached the canvas, so a 2048 preview could never be inspected
        at its actual detail level and fine masks looked noticeably crunched.

        The evaluator already converts the result to compact RGBA8 display
        pixels on the GPU, so retain the complete authored preview dimensions
        here.  The canvas handles fit/zoom presentation without changing the
        texture data.
        """
        return max(int(source_width), 1), max(int(source_height), 1)

    def _set_info_text(self, message: str) -> None:
        self._info_full_text = str(message or "")
        self.info.setToolTip(self._info_full_text)
        available_width = max(self.info.width() - 4, 80)
        self.info.setText(
            self.info.fontMetrics().elidedText(
                self._info_full_text,
                Qt.TextElideMode.ElideRight,
                available_width,
            )
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, lambda: self._set_info_text(self._info_full_text))

    def set_busy(self, busy: bool, message: str | None = None) -> None:
        self._busy = bool(busy)
        if self._busy:
            self._frame_base_info = ""
            self._set_info_text(message or "Evaluating… latest edit wins")

    def show_notice(self, title: str, message: str, *, keep_image: bool = True) -> None:
        """Show an informational state without starting or clearing evaluation."""
        self._busy = False
        self._frame_base_info = ""
        self.title.setText(str(title or "Preview"))
        self._set_info_text(str(message or ""))
        if not keep_image:
            self._raw_image = None
            self._prepared_rgba = None
            self._refresh_display()

    def set_result(
        self,
        node_name: str | None,
        image: np.ndarray | None,
        error: str | None,
        width: int,
        height: int,
        precision: str = "16-bit float",
        *,
        frame_number: int | None = None,
        time_seconds: float | None = None,
        signal_value=None,
        details_override: str | None = None,
        data_kind: str = "color",
        output_precision: str | None = None,
        display_rgba: np.ndarray | None = None,
    ) -> None:
        self._busy = False
        self._playback_details_key = ""
        self._playback_last_metadata_update = 0.0
        self._raw_image = image
        self._prepared_rgba = (
            np.ascontiguousarray(display_rgba, dtype=np.uint8)
            if display_rgba is not None else None
        )
        self._data_kind = data_kind
        self.set_uv_mode(data_kind == "uv")
        self._output_precision = output_precision or precision
        self.title.setText(node_name or "No active node")
        if error:
            self._frame_base_info = ""
            self._set_info_text(f"Evaluation failed: {error}")
        elif image is not None or self._prepared_rgba is not None:
            kind_label = {"grayscale": "Greyscale", "color": "Colour", "vector": "Vector / Normal", "uv": "UV Layout"}.get(self._data_kind, self._data_kind.title())
            details = details_override or f"{width} × {height} preview · {kind_label} · {self._output_precision}"
            if signal_value is not None:
                if isinstance(signal_value, tuple):
                    readable = ", ".join(f"{float(value):.4g}" for value in signal_value)
                else:
                    readable = f"{float(signal_value):.4g}"
                details += f" · signal {readable}"
            self._frame_base_info = details
            if frame_number is not None and time_seconds is not None:
                details += f" · frame {frame_number} · {time_seconds:.3f} s"
            self._set_info_text(details)
        else:
            self._frame_base_info = ""
            self._set_info_text("Double-click a node to lock it into the preview.")
        self._refresh_display()

    def update_frame_metadata(self, frame_number: int, time_seconds: float) -> None:
        """Advance timeline text without rebuilding or uploading the preview image."""
        if not self._frame_base_info:
            return
        self._set_info_text(
            f"{self._frame_base_info} · frame {int(frame_number)} · {float(time_seconds):.3f} s"
        )

    def set_prepared_playback_frame(
        self,
        display_rgba: np.ndarray,
        *,
        node_name: str,
        width: int,
        height: int,
        frame_number: int,
        time_seconds: float,
        details: str,
    ) -> None:
        """Swap one already prepared RGBA8 animation frame with minimal UI work.

        Material playback already performs colour conversion in its worker. This
        path avoids rebuilding title/detail chrome and re-running the general
        result presentation code for every frame; only the image is replaced at
        full cadence, while textual frame metadata updates at a lighter rate.
        """
        self._busy = False
        self._raw_image = None
        self._prepared_rgba = np.ascontiguousarray(display_rgba, dtype=np.uint8)
        self._data_kind = "color"

        details_key = f"{node_name}|{int(width)}|{int(height)}|{details}"
        if details_key != self._playback_details_key:
            self._playback_details_key = details_key
            self.title.setText(str(node_name or "Material · Base Colour"))
            self._frame_base_info = str(details or f"{int(width)} × {int(height)} live material playback")
            self._set_info_text(
                f"{self._frame_base_info} · frame {int(frame_number)} · {float(time_seconds):.3f} s"
            )
            self._playback_last_metadata_update = time.perf_counter()
        else:
            now = time.perf_counter()
            if (now - self._playback_last_metadata_update) >= 0.10:
                self._playback_last_metadata_update = now
                self.update_frame_metadata(frame_number, time_seconds)

        # The common playback case has all channels visible. Avoid a temporary
        # filtered copy there; channel-isolation still follows the ordinary path.
        if all(button.isChecked() for button in self.channel_buttons.values()):
            self._display_image = rgba8_to_qimage(self._prepared_rgba)
            self.canvas.set_image(self._display_image)
        else:
            self._refresh_display()

    def _refresh_display(self) -> None:
        if self._prepared_rgba is not None:
            filtered = self._prepared_rgba.copy()
            for index, channel in enumerate(("R", "G", "B")):
                if not self.channel_buttons[channel].isChecked():
                    filtered[..., index] = 0
            if not self.channel_buttons["A"].isChecked():
                filtered[..., 3] = 255
            self._display_image = rgba8_to_qimage(filtered)
            self.canvas.set_image(self._display_image)
            return
        if self._raw_image is None:
            self._display_image = QImage()
            self.canvas.set_image(self._display_image)
            return
        filtered = self._raw_image.copy()
        for index, channel in enumerate(("R", "G", "B")):
            if not self.channel_buttons[channel].isChecked():
                filtered[..., index] = 0.0
        if not self.channel_buttons["A"].isChecked():
            filtered[..., 3] = 1.0
        self._display_image = array_to_qimage(filtered, self._data_kind)
        self.canvas.set_image(self._display_image)

    def _zoom_changed(self, zoom: float) -> None:
        percent = max(float(zoom), 0.0) * 100.0
        if abs(percent - round(percent)) < 0.005:
            text = f"{round(percent):.0f}%"
        else:
            text = f"{percent:.2f}".rstrip("0").rstrip(".") + "%"
        self.zoom_label.setText(text)

    def copy_to_clipboard(self) -> None:
        if self._display_image.isNull():
            return
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setImage(self._display_image)
