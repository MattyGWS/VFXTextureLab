from __future__ import annotations

import math
import time
import uuid
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPainterPathStroker, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QGraphicsPathItem

from ..nodes.base import NodeDefinition, is_image_kind, normalise_port_kind
from ..theme import theme_colour

if TYPE_CHECKING:
    from .scene import GraphScene


class PortItem(QGraphicsObject):
    RADIUS = 6.0

    def __init__(
        self, owner, name: str, is_output: bool, *, kind: str = "image", display_name: str | None = None
    ) -> None:
        super().__init__(owner)
        self.owner = owner
        self.name = name
        self.display_name = display_name or name
        self.declared_kind = normalise_port_kind(kind)
        self.kind = self.declared_kind
        self.is_output = is_output
        self._invalid = False
        self._snap_target = False
        self._preview_active = False
        self.setAcceptHoverEvents(True)
        self._hovered = False
        self.setZValue(5)

    def boundingRect(self) -> QRectF:
        # Leave enough paint bounds for the persistent output-preview ring and
        # the temporary socket-snap halo; otherwise Qt clips their outer edge.
        r = self.RADIUS + 6
        return QRectF(-r, -r, r * 2, r * 2)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        del option, widget
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = {
            "grayscale": ("#8d939d", "#d9dde4"),
            "color": ("#d7a449", "#ffe1a0"),
            "vector": ("#4d8fd5", "#9bcaff"),
            "material": ("#b06ee8", "#ddb6ff"),
            "geometry": ("#d2684a", "#ffb09a"),
            "scalar": ("#55b879", "#9ff0b7"),
            "vector2": ("#45aa89", "#8ee8c5"),
            "vector3": ("#3c9b7c", "#82dab5"),
            "image_any": ("#7e8290", "#c9ccd5"),
        }
        if self._invalid:
            normal = hovered = "#ef5565"
        else:
            normal, hovered = palette.get(self.kind, palette["image_any"])
        fill = QColor(hovered if self._hovered else normal)
        if self._preview_active and self.is_output:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(theme_colour("node_active", "#7786ff")), 2.4))
            painter.drawEllipse(QPointF(0, 0), self.RADIUS + 4.5, self.RADIUS + 4.5)
        if self._snap_target and not self._invalid:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(theme_colour("progress", "#ff9d36")), 2.2))
            painter.drawEllipse(QPointF(0, 0), self.RADIUS + 3.0, self.RADIUS + 3.0)
        painter.setBrush(fill)
        painter.setPen(QPen(QColor(theme_colour("graph_background", "#17191d")), 2.0))
        painter.drawEllipse(QPointF(0, 0), self.RADIUS, self.RADIUS)


    def set_kind(self, kind: str) -> None:
        kind = normalise_port_kind(kind)
        if kind != self.kind:
            self.kind = kind
            self.update()

    def set_invalid(self, invalid: bool) -> None:
        invalid = bool(invalid)
        if invalid != self._invalid:
            self._invalid = invalid
            self.update()

    def set_snap_target(self, active: bool) -> None:
        active = bool(active)
        if active != self._snap_target:
            self._snap_target = active
            self.update()

    def set_preview_active(self, active: bool) -> None:
        active = bool(active)
        if active != self._preview_active:
            self._preview_active = active
            self.update()

    def hoverEnterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def centre_scene_pos(self) -> QPointF:
        return self.mapToScene(QPointF(0, 0))


class GroupPortItem(PortItem):
    """A visible collapsed-group port that resolves to an internal real port."""

    def __init__(
        self,
        owner: "GroupFrameItem",
        name: str,
        is_output: bool,
        endpoint_node_uid: str,
        endpoint_input_name: str | None = None,
        *,
        kind: str = "image",
    ) -> None:
        super().__init__(owner, name, is_output, kind=kind)
        self.endpoint_node_uid = endpoint_node_uid
        self.endpoint_input_name = endpoint_input_name


class NodeItem(QGraphicsObject):
    WIDTH = 210.0
    HEADER_HEIGHT = 38.0
    PORT_ROW_HEIGHT = 25.0
    MIN_HEIGHT = 78.0
    DOCK_WIDTH = 132.0
    DOCK_HEIGHT = 23.0
    THUMBNAIL_SIZE = 128.0
    THUMBNAIL_MARGIN_TOP = 10.0
    THUMBNAIL_MARGIN_BOTTOM = 10.0
    THUMBNAIL_FRAME_PADDING = 3.0
    THUMBNAIL_VISUAL_KINDS = {"grayscale", "color", "vector", "material", "scalar"}

    def __init__(
        self,
        definition: NodeDefinition,
        uid: str | None = None,
        parameters: dict | None = None,
        group_uid: str | None = None,
    ) -> None:
        super().__init__()
        self.definition = definition
        self.uid = uid or uuid.uuid4().hex
        self.group_uid = group_uid
        self.parameters = definition.default_parameters()
        if parameters:
            self.parameters.update(parameters)

        # Evolution was an unrestricted development parameter before 0.17.6.
        # Noise nodes now expose a true normalised loop phase; wrap legacy
        # values to their equivalent phase while retaining the visible 1.0 end.
        if definition.category.startswith("Noise") and "evolution" in self.parameters:
            try:
                legacy_evolution = float(self.parameters["evolution"])
                if legacy_evolution < 0.0 or legacy_evolution > 1.0:
                    self.parameters["evolution"] = legacy_evolution - math.floor(legacy_evolution)
            except (TypeError, ValueError):
                self.parameters["evolution"] = 0.0
        self.resolved_image_kind = normalise_port_kind(
            str(self.parameters.get("_resolved_kind", definition.default_image_kind))
        )
        if self.resolved_image_kind not in ("grayscale", "color", "vector"):
            self.resolved_image_kind = definition.default_image_kind
        self.parameters["_resolved_kind"] = self.resolved_image_kind
        self.docked_to_uid: str | None = None
        self.undocked_position = QPointF()
        self.active = False
        self.error_message = ""
        self._bypass_hovered = False
        self._thumbnail_hovered = False
        self.thumbnail_enabled = False
        self.thumbnail_output_name: str | None = None
        self.thumbnail_state = "not_evaluated"
        self.thumbnail_message = "Not evaluated"
        self.thumbnail_image: QImage | None = None
        self.thumbnail_signal_value: float | tuple | None = None
        self.thumbnail_cache_key: str | None = None
        self._eval_active = False
        self._eval_progress_current = 0
        self._eval_progress_target = 0
        self._eval_message = ""
        self._eval_started_at = 0.0
        self._eval_pulse_phase = 0.0
        self._eval_timer: QTimer | None = None
        exposed = self.parameters.get("_exposed_inputs", [])
        self.exposed_parameter_inputs: set[str] = {str(name) for name in exposed if str(name)}
        self.input_ports: dict[str, PortItem] = {}
        self.output_ports: dict[str, PortItem] = {
            name: PortItem(
                self, name, True, kind=definition.output_kind(name),
                display_name=definition.output_label(name),
            )
            for name in definition.output_names
        }
        for name, port in self.output_ports.items():
            port.set_kind(self._effective_kind(definition.output_kind(name)))
        self.output_port: PortItem | None = next(iter(self.output_ports.values()), None)

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self.setAcceptHoverEvents(True)
        self.setToolTip(definition.missing_reason or definition.description)

        self._rebuild_input_ports()
        self._position_ports()

    def _effective_kind(self, declared_kind: str) -> str:
        declared = normalise_port_kind(declared_kind)
        return self.resolved_image_kind if declared == "image_any" else declared

    def _effective_input_kind(self, declared_kind: str) -> str:
        declared = normalise_port_kind(declared_kind)
        if declared == "image_any" and self.definition.type_policy == "accept_any_input":
            return "image_any"
        return self._effective_kind(declared)

    def set_resolved_image_kind(self, kind: str) -> bool:
        kind = normalise_port_kind(kind)
        if kind not in ("grayscale", "color", "vector"):
            return False
        if kind == self.resolved_image_kind:
            return False
        self.resolved_image_kind = kind
        self.parameters["_resolved_kind"] = kind
        for name, port in self.input_ports.items():
            port.set_kind(self._effective_input_kind(self.definition.input_kind(name)))
        for name, port in self.output_ports.items():
            port.set_kind(self._effective_kind(self.definition.output_kind(name)))
        self.update()
        return True

    def replace_definition(self, definition: NodeDefinition) -> None:
        """Replace a dynamic node definition while preserving the node object.

        Graph Instance interfaces can change when their linked source graph is
        reloaded.  Connections are detached and restored by GraphScene around
        this call; the node itself keeps its UID, position, selection and active
        state.
        """
        self.prepareGeometryChange()
        scene = self.scene()
        for port in (*self.input_ports.values(), *self.output_ports.values()):
            port.setParentItem(None)
            if scene is not None and port.scene() is scene:
                scene.removeItem(port)
            port.deleteLater()
        self.definition = definition
        self.setToolTip(definition.missing_reason or definition.description)
        exposed = self.parameters.get("_exposed_inputs", ())
        self.exposed_parameter_inputs = {str(name) for name in exposed if str(name)}
        self.input_ports = {}
        self.output_ports = {
            name: PortItem(
                self, name, True, kind=definition.output_kind(name),
                display_name=definition.output_label(name),
            )
            for name in definition.output_names
        }
        for name, port in self.output_ports.items():
            port.set_kind(self._effective_kind(definition.output_kind(name)))
        self.output_port = next(iter(self.output_ports.values()), None)
        if self.thumbnail_output_name not in self.thumbnail_output_names():
            self.thumbnail_output_name = self.resolved_thumbnail_output()
            self.thumbnail_cache_key = None
            self.thumbnail_state = "stale" if self.thumbnail_image is not None else "not_evaluated"
        self._rebuild_input_ports()
        self._position_ports()
        self.update()

    def set_port_kind(self, name: str, kind: str, *, output: bool) -> bool:
        ports = self.output_ports if output else self.input_ports
        port = ports.get(name)
        if port is None:
            return False
        kind = normalise_port_kind(kind)
        changed = kind != port.kind or kind != port.declared_kind
        if changed:
            port.declared_kind = kind
            port.set_kind(kind)
            self.update()
        return changed

    def refresh_port_labels(self) -> None:
        for name, port in self.input_ports.items():
            port.display_name = self.definition.input_label(name)
        for name, port in self.output_ports.items():
            port.display_name = self.definition.output_label(name)
        self.prepareGeometryChange()
        self._position_ports()
        self.update()

    def output_data_kind(self, output_name: str | None = None) -> str:
        if not self.definition.output_names:
            return "image_any"
        name = output_name or self.definition.output_names[0]
        port = self.output_ports.get(name)
        if port is not None and normalise_port_kind(self.definition.output_kind(name)) == "any":
            return normalise_port_kind(port.kind)
        return self._effective_kind(self.definition.output_kind(name))

    @staticmethod
    def parameter_port_name(parameter_name: str) -> str:
        return f"@param:{parameter_name}"

    @staticmethod
    def parameter_name_from_port(port_name: str) -> str | None:
        prefix = "@param:"
        return port_name[len(prefix):] if port_name.startswith(prefix) else None

    def _rebuild_input_ports(self) -> None:
        for input_name in self.definition.inputs:
            if input_name not in self.input_ports:
                declared = self.definition.input_kind(input_name)
                self.input_ports[input_name] = PortItem(
                    self, input_name, False, kind=declared,
                    display_name=self.definition.input_label(input_name),
                )
                self.input_ports[input_name].set_kind(self._effective_input_kind(declared))
        for parameter_name in sorted(self.exposed_parameter_inputs):
            spec = self.definition.parameter_spec(parameter_name)
            if spec is None or not spec.animatable:
                continue
            port_name = self.parameter_port_name(parameter_name)
            if port_name not in self.input_ports:
                self.input_ports[port_name] = PortItem(
                    self, port_name, False, kind="scalar", display_name=spec.label
                )

    @property
    def is_docked(self) -> bool:
        return bool(self.docked_to_uid)

    @property
    def width(self) -> float:
        return self.DOCK_WIDTH if self.is_docked else float(self.__class__.WIDTH)

    def thumbnail_output_names(self) -> list[str]:
        return [
            name for name in self.definition.output_names
            if normalise_port_kind(self.output_data_kind(name)) in self.THUMBNAIL_VISUAL_KINDS
        ]

    def supports_thumbnail(self) -> bool:
        return bool(self.thumbnail_output_names()) and not isinstance(self, RerouteItem)

    @property
    def thumbnail_visible(self) -> bool:
        return bool(self.thumbnail_enabled and not self.is_docked and self.supports_thumbnail())

    @property
    def thumbnail_extra_height(self) -> float:
        if not self.thumbnail_visible:
            return 0.0
        return self.THUMBNAIL_MARGIN_TOP + self.THUMBNAIL_SIZE + self.THUMBNAIL_MARGIN_BOTTOM

    def resolved_thumbnail_output(self) -> str | None:
        names = self.thumbnail_output_names()
        if not names:
            return None
        if self.thumbnail_output_name in names:
            return self.thumbnail_output_name
        return names[0]

    @property
    def height(self) -> float:
        if self.is_docked:
            return self.DOCK_HEIGHT
        rows = max(len(self.input_ports), len(self.output_ports), 1)
        return max(
            self.MIN_HEIGHT,
            self.HEADER_HEIGHT + self.thumbnail_extra_height + rows * self.PORT_ROW_HEIGHT + 15.0,
        )

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.width, self.height)

    def set_docked(self, parent_uid: str | None, *, undocked_position: QPointF | None = None) -> None:
        parent_uid = str(parent_uid or "") or None
        if parent_uid == self.docked_to_uid and undocked_position is None:
            return
        self.prepareGeometryChange()
        if parent_uid is not None and self.docked_to_uid is None:
            self.undocked_position = QPointF(undocked_position if undocked_position is not None else self.pos())
        elif undocked_position is not None:
            self.undocked_position = QPointF(undocked_position)
        self.docked_to_uid = parent_uid
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, parent_uid is None)
        self._position_ports()
        self.update()

    def _position_ports(self) -> None:
        if self.is_docked:
            centre = self.DOCK_HEIGHT * 0.5
            for port in self.input_ports.values():
                port.setPos(0.0, centre)
            for port in self.output_ports.values():
                port.setPos(self.DOCK_WIDTH, centre)
            return
        offset = self.thumbnail_extra_height
        for index, port in enumerate(self.input_ports.values()):
            port.setPos(0, self.HEADER_HEIGHT + offset + 17 + index * self.PORT_ROW_HEIGHT)
        for index, port in enumerate(self.output_ports.values()):
            port.setPos(self.width, self.HEADER_HEIGHT + offset + 17 + index * self.PORT_ROW_HEIGHT)

    @property
    def bypassed(self) -> bool:
        return bool(self.parameters.get("_bypassed", False))

    def thumbnail_button_rect(self) -> QRectF:
        return QRectF(self.width - 34.0, 8.0, 22.0, 22.0)

    def bypass_button_rect(self) -> QRectF:
        offset = 62.0 if self.supports_thumbnail() else 34.0
        return QRectF(self.width - offset, 8.0, 22.0, 22.0)

    def thumbnail_rect(self) -> QRectF:
        x = (self.width - self.THUMBNAIL_SIZE) * 0.5
        y = self.HEADER_HEIGHT + self.THUMBNAIL_MARGIN_TOP
        return QRectF(x, y, self.THUMBNAIL_SIZE, self.THUMBNAIL_SIZE)

    def set_thumbnail_enabled(self, enabled: bool) -> bool:
        enabled = bool(enabled and self.supports_thumbnail())
        if enabled == self.thumbnail_enabled:
            return False
        self.prepareGeometryChange()
        self.thumbnail_enabled = enabled
        if enabled and self.thumbnail_output_name not in self.thumbnail_output_names():
            self.thumbnail_output_name = self.resolved_thumbnail_output()
        if not enabled:
            self.thumbnail_state = "not_evaluated"
            self.thumbnail_message = "Not evaluated"
            self.thumbnail_cache_key = None
        self._position_ports()
        self.update()
        return True

    def set_thumbnail_output(self, output_name: str | None) -> bool:
        output_name = str(output_name or "") or None
        if output_name not in self.thumbnail_output_names():
            output_name = self.resolved_thumbnail_output()
        if output_name == self.thumbnail_output_name:
            return False
        self.thumbnail_output_name = output_name
        self.thumbnail_cache_key = None
        self.thumbnail_state = "stale" if self.thumbnail_image is not None else "not_evaluated"
        self.thumbnail_message = "Updating…" if self.thumbnail_image is not None else "Not evaluated"
        self.update()
        return True

    def clear_thumbnail_result(self, *, keep_image: bool = True, state: str = "stale", message: str = "Updating…") -> None:
        if not keep_image:
            self.thumbnail_image = None
            self.thumbnail_signal_value = None
        self.thumbnail_cache_key = None
        self.thumbnail_state = str(state)
        self.thumbnail_message = str(message)
        self.update()

    def set_thumbnail_status(self, state: str, message: str | None = None) -> None:
        self.thumbnail_state = str(state)
        self.thumbnail_message = str(message or state.replace("_", " ").title())
        self.update()

    def set_thumbnail_rgba(self, rgba, *, cache_key: str | None = None) -> None:
        try:
            height, width = int(rgba.shape[0]), int(rgba.shape[1])
            image = QImage(
                rgba.data, width, height, int(rgba.strides[0]), QImage.Format.Format_RGBA8888
            ).copy()
        except Exception:
            self.set_thumbnail_status("error", "Preview unavailable")
            return
        self.thumbnail_image = image
        self.thumbnail_signal_value = None
        self.thumbnail_cache_key = str(cache_key or "") or None
        self.thumbnail_state = "ready"
        self.thumbnail_message = ""
        self.update()

    def set_thumbnail_signal(self, value, *, cache_key: str | None = None) -> None:
        self.thumbnail_signal_value = value
        self.thumbnail_image = None
        self.thumbnail_cache_key = str(cache_key or "") or None
        self.thumbnail_state = "ready"
        self.thumbnail_message = ""
        self.update()

    def _is_bypassable(self) -> bool:
        scene = self.scene()
        return bool(scene is not None and hasattr(scene, "node_is_bypassable") and scene.node_is_bypassable(self))

    def _ensure_eval_timer(self) -> None:
        if self._eval_timer is not None:
            return
        self._eval_timer = QTimer(self)
        self._eval_timer.setInterval(60)
        self._eval_timer.timeout.connect(self._advance_eval_pulse)

    def _advance_eval_pulse(self) -> None:
        if not self._eval_active:
            if self._eval_timer is not None:
                self._eval_timer.stop()
            return
        self._eval_pulse_phase = (self._eval_pulse_phase + 0.11) % 1.0
        self.update()

    def set_evaluation_state(
        self,
        active: bool,
        current: int = 0,
        target: int = 0,
        message: str | None = None,
    ) -> None:
        active = bool(active)
        if active and not self._eval_active:
            self._eval_started_at = time.perf_counter()
            self._eval_pulse_phase = 0.0
            self._ensure_eval_timer()
            if self._eval_timer is not None:
                self._eval_timer.start()
        elif not active and self._eval_timer is not None:
            self._eval_timer.stop()
        self._eval_active = active
        self._eval_progress_current = max(int(current), 0)
        self._eval_progress_target = max(int(target), 0)
        self._eval_message = str(message or "")
        if self._eval_active and self._eval_message:
            base_tooltip = self.error_message or self.definition.missing_reason or self.definition.description
            self.setToolTip(f"{base_tooltip}\n\n{self._eval_message}")
        else:
            self.setToolTip(self.error_message or self.definition.missing_reason or self.definition.description)
        self.update()

    def _evaluation_visible(self) -> bool:
        return self._eval_active and (time.perf_counter() - self._eval_started_at) >= 0.18

    def _evaluation_progress_fraction(self) -> float | None:
        if self._eval_progress_target <= 0:
            return None
        return max(0.0, min(self._eval_progress_current / float(self._eval_progress_target), 1.0))

    def paint(self, painter: QPainter, option, widget=None) -> None:
        del option, widget
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = self.boundingRect()

        if self.is_docked:
            if self.error_message or self.definition.missing:
                border = QColor(theme_colour("error", "#ff6678"))
            elif self.isSelected():
                border = QColor(theme_colour("node_selected", "#d5dbff"))
            elif self.active:
                border = QColor(theme_colour("node_active", "#7786ff"))
            else:
                border = QColor(theme_colour("node_border", "#383e48"))
            header = QColor(self.definition.accent)
            if self.bypassed:
                header = header.darker(175)
            painter.setBrush(header)
            painter.setPen(QPen(border, 2.0 if self.isSelected() or self.active else 1.2, Qt.PenStyle.DashLine if self.bypassed else Qt.PenStyle.SolidLine))
            painter.drawRoundedRect(bounds, 4.0, 4.0)
            font = painter.font()
            font.setBold(True)
            font.setPointSizeF(max(font.pointSizeF() - 0.5, 7.0))
            painter.setFont(font)
            painter.setPen(QColor(theme_colour("text_inverse", "#f4f1ff")))
            metrics = painter.fontMetrics()
            title = metrics.elidedText(self.definition.name, Qt.TextElideMode.ElideRight, int(self.width - 24.0))
            painter.drawText(QRectF(12.0, 0.0, self.width - 24.0, self.height), Qt.AlignmentFlag.AlignCenter, title)
            if self._evaluation_visible():
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(theme_colour("progress", "#ff9d36")), 2.0))
                painter.drawRoundedRect(bounds.adjusted(1.5, 1.5, -1.5, -1.5), 4.0, 4.0)
            return

        if self.error_message or self.definition.missing:
            border = QColor(theme_colour("error", "#ff6678"))
            border_width = 2.6
        elif self.isSelected():
            border = QColor(theme_colour("node_selected", "#d5dbff"))
            border_width = 2.3
        elif self.active:
            border = QColor(theme_colour("node_active", "#7786ff"))
            border_width = 2.5
        else:
            border = QColor(theme_colour("node_border", "#383e48"))
            border_width = 1.2

        body_colour = QColor(theme_colour("node_body_bypassed", "#191c21") if self.bypassed else theme_colour("node_body", "#22262c"))
        header_colour = QColor(self.definition.accent)
        if self.bypassed:
            header_colour = header_colour.darker(175)
        painter.setBrush(body_colour)
        painter.setPen(
            QPen(
                border,
                border_width,
                Qt.PenStyle.DashLine if self.bypassed else Qt.PenStyle.SolidLine,
            )
        )
        painter.drawRoundedRect(bounds, 8, 8)

        header_path = QPainterPath()
        header_path.addRoundedRect(QRectF(0, 0, self.width, self.HEADER_HEIGHT + 7), 8, 8)
        painter.fillPath(header_path, header_colour)
        painter.fillRect(QRectF(0, self.HEADER_HEIGHT - 6, self.width, 13), header_colour)

        header_text = QColor("#1d2127") if header_colour.lightnessF() > 0.68 else QColor("#ffffff")
        painter.setPen(header_text)
        title_font = painter.font()
        title_font.setBold(True)
        painter.setFont(title_font)
        action_left = self.width - 12.0
        if self.supports_thumbnail():
            action_left = min(action_left, self.thumbnail_button_rect().left())
        if self._is_bypassable():
            action_left = min(action_left, self.bypass_button_rect().left())
        error_present = bool(self.error_message or self.definition.missing)
        icon_count = int(self.definition.is_stateful) + int(error_present)
        title_right = action_left - icon_count * 25.0 - 7.0
        painter.drawText(
            QRectF(13, 0, max(title_right - 13.0, 20.0), self.HEADER_HEIGHT),
            Qt.AlignmentFlag.AlignVCenter,
            self.definition.name,
        )
        icon_x = action_left - 14.0
        if error_present:
            painter.setBrush(QColor(theme_colour("error", "#c8394d")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(icon_x, self.HEADER_HEIGHT * 0.5), 9, 9)
            painter.setPen(QColor(theme_colour("text_inverse", "#ffffff")))
            badge_font = painter.font()
            badge_font.setBold(True)
            painter.setFont(badge_font)
            painter.drawText(
                QRectF(icon_x - 9, 0, 18, self.HEADER_HEIGHT),
                Qt.AlignmentFlag.AlignCenter,
                "!",
            )
            painter.setFont(title_font)
            icon_x -= 25.0
        if self.definition.is_stateful:
            state_x = icon_x
            painter.setBrush(QColor(20, 22, 28, 100))
            painter.setPen(QPen(QColor(theme_colour("text_inverse", "#eee8ff")), 1.2))
            painter.drawEllipse(QPointF(state_x, self.HEADER_HEIGHT * 0.5), 8.5, 8.5)
            state_font = painter.font()
            state_font.setBold(True)
            state_font.setPointSizeF(max(state_font.pointSizeF() - 1.0, 7.0))
            painter.setFont(state_font)
            painter.drawText(
                QRectF(state_x - 8.5, 0, 17, self.HEADER_HEIGHT),
                Qt.AlignmentFlag.AlignCenter,
                "↻",
            )
            painter.setFont(title_font)

        if self.thumbnail_visible:
            thumb_rect = self.thumbnail_rect()
            frame_rect = thumb_rect.adjusted(
                -self.THUMBNAIL_FRAME_PADDING,
                -self.THUMBNAIL_FRAME_PADDING,
                self.THUMBNAIL_FRAME_PADDING,
                self.THUMBNAIL_FRAME_PADDING,
            )
            painter.setBrush(QColor(theme_colour("graph_background", "#17191d")))
            painter.setPen(QPen(QColor(theme_colour("node_border", "#383e48")), 1.0))
            painter.drawRoundedRect(frame_rect, 4.0, 4.0)
            if self.thumbnail_image is not None:
                painter.drawImage(thumb_rect, self.thumbnail_image)
            else:
                tile = 16.0
                dark = QColor(theme_colour("node_body_bypassed", "#191c21"))
                light = QColor(theme_colour("node_body", "#22262c")).lighter(112)
                row = 0
                y = thumb_rect.top()
                while y < thumb_rect.bottom():
                    column = 0
                    x = thumb_rect.left()
                    while x < thumb_rect.right():
                        painter.fillRect(
                            QRectF(x, y, min(tile, thumb_rect.right() - x), min(tile, thumb_rect.bottom() - y)),
                            light if (row + column) % 2 == 0 else dark,
                        )
                        x += tile
                        column += 1
                    y += tile
                    row += 1
            if self.thumbnail_signal_value is not None and self.thumbnail_state == "ready":
                painter.fillRect(thumb_rect, QColor(12, 15, 18, 185))
                painter.setPen(QColor(theme_colour("node_text", "#c5cad3")))
                signal_font = painter.font()
                signal_font.setBold(True)
                signal_font.setPointSizeF(max(signal_font.pointSizeF() + 1.0, 9.0))
                painter.setFont(signal_font)
                value = self.thumbnail_signal_value
                if isinstance(value, tuple):
                    text = ", ".join(f"{float(item):.3g}" for item in value)
                else:
                    try:
                        text = f"{float(value):.4g}"
                    except (TypeError, ValueError):
                        text = str(value)
                painter.drawText(thumb_rect.adjusted(6, 6, -6, -6), Qt.AlignmentFlag.AlignCenter, text)
            elif self.thumbnail_state != "ready":
                painter.fillRect(thumb_rect, QColor(12, 15, 18, 150 if self.thumbnail_image is not None else 105))
                painter.setPen(QColor(theme_colour("node_text_muted", "#9097a3")))
                status_font = painter.font()
                status_font.setBold(self.thumbnail_state == "error")
                status_font.setPointSizeF(max(status_font.pointSizeF() - 1.0, 7.0))
                painter.setFont(status_font)
                painter.drawText(
                    thumb_rect.adjusted(8, 8, -8, -8),
                    Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                    self.thumbnail_message or "Not evaluated",
                )

        body_font = painter.font()
        body_font.setBold(False)
        painter.setFont(body_font)
        painter.setPen(QColor(theme_colour("node_text_muted", "#9097a3") if self.bypassed else theme_colour("node_text", "#c5cad3")))
        port_offset = self.thumbnail_extra_height
        for index, port in enumerate(self.input_ports.values()):
            y = self.HEADER_HEIGHT + port_offset + 7 + index * self.PORT_ROW_HEIGHT
            painter.drawText(
                QRectF(13, y, self.width - 26, self.PORT_ROW_HEIGHT),
                Qt.AlignmentFlag.AlignVCenter,
                port.display_name,
            )
        for index, port in enumerate(self.output_ports.values()):
            y = self.HEADER_HEIGHT + port_offset + 7 + index * self.PORT_ROW_HEIGHT
            painter.drawText(
                QRectF(13, y, self.width - 26, self.PORT_ROW_HEIGHT),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                port.display_name,
            )

        if not self.input_ports and len(self.output_ports) == 1:
            painter.setPen(QColor(theme_colour("node_text_muted", "#7f8795")))
            painter.drawText(
                QRectF(13, self.HEADER_HEIGHT + port_offset + 5, self.width - 26, self.height - self.HEADER_HEIGHT - port_offset - 8),
                Qt.AlignmentFlag.AlignVCenter,
                self.definition.category,
            )

        if self._evaluation_visible():
            pulse = 0.5 + 0.5 * math.sin(self._eval_pulse_phase * math.tau)
            glow_colour = QColor(QColor(theme_colour("progress", "#ff9d36")).red(), QColor(theme_colour("progress", "#ff9d36")).green(), QColor(theme_colour("progress", "#ff9d36")).blue(), int(105 + 70 * pulse))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(glow_colour, 2.4))
            painter.drawRoundedRect(bounds.adjusted(1.5, 1.5, -1.5, -1.5), 7, 7)

            bar_rect = QRectF(12.0, self.height - 12.0, self.width - 24.0, 6.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(18, 20, 24, 220))
            painter.drawRoundedRect(bar_rect, 3, 3)
            fraction = self._evaluation_progress_fraction()
            painter.setBrush(QColor(theme_colour("progress", "#ff9d36")))
            if fraction is None:
                chunk_width = max(bar_rect.width() * 0.28, 18.0)
                travel = max(bar_rect.width() - chunk_width, 1.0)
                offset = travel * self._eval_pulse_phase
                painter.drawRoundedRect(QRectF(bar_rect.x() + offset, bar_rect.y(), chunk_width, bar_rect.height()), 3, 3)
            else:
                painter.drawRoundedRect(QRectF(bar_rect.x(), bar_rect.y(), max(bar_rect.width() * fraction, 8.0 if fraction > 0.0 else 0.0), bar_rect.height()), 3, 3)

        if self.supports_thumbnail():
            rect = self.thumbnail_button_rect()
            painter.setBrush(QColor(255, 255, 255, 22 if self._thumbnail_hovered else 10))
            painter.setPen(QPen(QColor(255, 255, 255, 45), 1.0))
            painter.drawRoundedRect(rect, 5, 5)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#ffffff" if self._thumbnail_hovered else "#d6dae2"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            centre = rect.center()
            direction = -1.0 if self.thumbnail_visible else 1.0
            painter.drawLine(QPointF(centre.x() - 5.0, centre.y() - 2.5 * direction), QPointF(centre.x(), centre.y() + 2.5 * direction))
            painter.drawLine(QPointF(centre.x(), centre.y() + 2.5 * direction), QPointF(centre.x() + 5.0, centre.y() - 2.5 * direction))

        if self._is_bypassable():
            rect = self.bypass_button_rect()
            colour = QColor(
                "#ffffff"
                if self._bypass_hovered
                else ("#83e39b" if not self.bypassed else "#a0a6b0")
            )
            painter.setBrush(QColor(255, 255, 255, 22 if self._bypass_hovered else 10))
            painter.setPen(QPen(QColor(255, 255, 255, 45), 1.0))
            painter.drawRoundedRect(rect, 5, 5)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(
                QPen(colour, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            )
            centre = rect.center()
            painter.drawArc(
                QRectF(centre.x() - 6, centre.y() - 5, 12, 12),
                35 * 16,
                290 * 16,
            )
            painter.drawLine(
                QPointF(centre.x(), centre.y() - 7),
                QPointF(centre.x(), centre.y() + 1),
            )

    def set_error(self, message: str | None) -> None:
        self.error_message = str(message or "")
        tooltip = self.error_message or self.definition.description
        self.setToolTip(tooltip)
        self.update()

    def set_active(self, active: bool) -> None:
        if self.active != active:
            self.active = active
            self.update()

    def set_active_output(self, output_name: str | None) -> None:
        selected = str(output_name or "")
        for name, port in self.output_ports.items():
            port.set_preview_active(bool(selected and name == selected))

    def mousePressEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not self.is_docked
            and self.supports_thumbnail()
            and self.thumbnail_button_rect().contains(event.pos())
        ):
            scene = self.scene()
            if scene is not None and hasattr(scene, "toggle_node_thumbnail"):
                scene.toggle_node_thumbnail(self)
            event.accept()
            return
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not self.is_docked
            and self._is_bypassable()
            and self.bypass_button_rect().contains(event.pos())
        ):
            scene = self.scene()
            if scene is not None and hasattr(scene, "toggle_node_bypass"):
                scene.toggle_node_bypass(self)
            event.accept()
            return
        super().mousePressEvent(event)

    def hoverMoveEvent(self, event) -> None:
        thumbnail_hovered = (
            not self.is_docked and self.supports_thumbnail()
            and self.thumbnail_button_rect().contains(event.pos())
        )
        bypass_hovered = (
            not self.is_docked and self._is_bypassable()
            and self.bypass_button_rect().contains(event.pos())
        )
        changed = thumbnail_hovered != self._thumbnail_hovered or bypass_hovered != self._bypass_hovered
        self._thumbnail_hovered = thumbnail_hovered
        self._bypass_hovered = bypass_hovered
        if changed:
            self.setCursor(
                Qt.CursorShape.PointingHandCursor
                if thumbnail_hovered or bypass_hovered else Qt.CursorShape.ArrowCursor
            )
            self.update()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        if self._bypass_hovered or self._thumbnail_hovered:
            self._bypass_hovered = False
            self._thumbnail_hovered = False
            self.unsetCursor()
            self.update()
        super().hoverLeaveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        scene = self.scene()
        if scene is not None and hasattr(scene, "set_active_node"):
            scene.set_active_node(self, force=True)
        event.accept()

    def itemChange(self, change, value):
        result = super().itemChange(change, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            scene = self.scene()
            if scene is not None and hasattr(scene, "node_moved"):
                scene.node_moved(self)
        return result


class PortalNodeItem(NodeItem):
    WIDTH = 176.0
    MIN_HEIGHT = 70.0
    PORTAL_KINDS = {"image_any", "grayscale", "color", "vector", "material", "geometry", "scalar", "vector2", "vector3"}

    def __init__(self, definition: NodeDefinition, uid: str | None = None, parameters: dict | None = None, group_uid: str | None = None) -> None:
        super().__init__(definition, uid=uid, parameters=parameters, group_uid=group_uid)
        self.portal_kind = normalise_port_kind(str(self.parameters.get("_portal_kind", "image_any")))
        if self.portal_kind not in self.PORTAL_KINDS:
            self.portal_kind = "image_any"
        self.parameters["_portal_kind"] = self.portal_kind
        if self.definition.type_id == "graph.receive":
            hidden = self.input_ports.get("Input")
            if hidden is not None:
                hidden.setVisible(False)
        self.set_portal_kind(self.portal_kind)
        self._position_ports()

    def supports_thumbnail(self) -> bool:
        # Portals are intentionally compact structural aliases. Preview the
        # sending or receiving image node instead of expanding the portal.
        return False

    @property
    def height(self) -> float:
        return self.DOCK_HEIGHT if self.is_docked else self.MIN_HEIGHT

    def _position_ports(self) -> None:
        if self.is_docked:
            super()._position_ports()
            return
        centre = self.height * 0.5
        for port in self.input_ports.values():
            port.setPos(0.0, centre)
        for port in self.output_ports.values():
            port.setPos(self.width, centre)

    def set_portal_kind(self, kind: str) -> bool:
        kind = normalise_port_kind(kind)
        if kind not in self.PORTAL_KINDS:
            kind = "image_any"
        changed = kind != getattr(self, "portal_kind", "image_any")
        self.portal_kind = kind
        self.parameters["_portal_kind"] = kind
        for port in self.input_ports.values():
            port.set_kind(kind)
        for port in self.output_ports.values():
            port.set_kind(kind)
        if changed:
            self.update()
        return changed

    def set_port_kind(self, name: str, kind: str, *, output: bool) -> bool:
        ports = self.output_ports if output else self.input_ports
        port = ports.get(name)
        if port is None:
            return False
        kind = normalise_port_kind(kind)
        changed = kind != port.kind or kind != port.declared_kind
        if changed:
            port.declared_kind = kind
            port.set_kind(kind)
            self.update()
        return changed

    def refresh_port_labels(self) -> None:
        for name, port in self.input_ports.items():
            port.display_name = self.definition.input_label(name)
        for name, port in self.output_ports.items():
            port.display_name = self.definition.output_label(name)
        self.prepareGeometryChange()
        self._position_ports()
        self.update()

    def output_data_kind(self, output_name: str | None = None) -> str:
        del output_name
        return self.portal_kind

    def set_resolved_image_kind(self, kind: str) -> bool:
        if normalise_port_kind(kind) in self.PORTAL_KINDS:
            return self.set_portal_kind(kind)
        return False

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if self.is_docked:
            del option, widget
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            bounds = self.boundingRect()
            border = QColor(
                theme_colour("error", "#ff6678")
                if self.error_message
                else theme_colour("node_selected", "#d5dbff")
                if self.isSelected()
                else theme_colour("node_active", "#7786ff")
                if self.active
                else theme_colour("node_border", "#383e48")
            )
            painter.setBrush(QColor(self.definition.accent))
            painter.setPen(QPen(border, 2.0 if self.isSelected() or self.active else 1.2))
            painter.drawRoundedRect(bounds, 4.0, 4.0)
            channel = str(self.parameters.get("channel_name", "")).strip()
            scene = self.scene()
            if self.definition.type_id == "graph.receive" and scene is not None and hasattr(scene, "portal_display_name"):
                channel = scene.portal_display_name(self) or channel
            label = f"{self.definition.name}: {channel or 'Unassigned'}"
            font = painter.font()
            font.setBold(True)
            font.setPointSizeF(max(font.pointSizeF() - 0.5, 7.0))
            painter.setFont(font)
            painter.setPen(QColor(theme_colour("text_inverse", "#f4f1ff")))
            label = painter.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, int(self.width - 22.0))
            painter.drawText(QRectF(11.0, 0.0, self.width - 22.0, self.height), Qt.AlignmentFlag.AlignCenter, label)
            return
        del option, widget
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = self.boundingRect()
        if self.error_message:
            border = QColor(theme_colour("error", "#ff6678"))
        elif self.isSelected():
            border = QColor(theme_colour("node_selected", "#d5dbff"))
        elif self.active:
            border = QColor(theme_colour("node_active", "#7786ff"))
        else:
            border = QColor(theme_colour("node_border", "#383e48"))
        painter.setBrush(QColor(theme_colour("node_body", "#22262c")))
        painter.setPen(QPen(border, 2.2 if self.isSelected() or self.active else 1.2))
        painter.drawRoundedRect(bounds, 7.0, 7.0)
        painter.setBrush(QColor(self.definition.accent))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(0.0, 0.0, self.width, 30.0), 7.0, 7.0)
        painter.drawRect(QRectF(0.0, 22.0, self.width, 8.0))
        title_font = painter.font()
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(theme_colour("text_inverse", "#f4f1ff")))
        painter.drawText(QRectF(10.0, 0.0, self.width - 20.0, 30.0), Qt.AlignmentFlag.AlignCenter, self.definition.name)
        channel = str(self.parameters.get("channel_name", "")).strip()
        if self.definition.type_id == "graph.receive":
            scene = self.scene()
            if scene is not None and hasattr(scene, "portal_display_name"):
                channel = scene.portal_display_name(self) or channel
        channel = channel or "Unassigned"
        body_font = painter.font()
        body_font.setBold(False)
        painter.setFont(body_font)
        painter.setPen(QColor(theme_colour("node_text", "#c5cad3")))
        painter.drawText(QRectF(12.0, 31.0, self.width - 24.0, self.height - 31.0), Qt.AlignmentFlag.AlignCenter, channel)



class RerouteItem(NodeItem):
    DIAMETER = 28.0
    VALID_KINDS = {"grayscale", "color", "vector", "material", "geometry", "scalar", "vector2", "vector3"}

    def __init__(
        self,
        definition: NodeDefinition,
        uid: str | None = None,
        parameters: dict | None = None,
        group_uid: str | None = None,
    ) -> None:
        super().__init__(definition, uid=uid, parameters=parameters, group_uid=group_uid)
        kind = normalise_port_kind(str(self.parameters.get("_reroute_kind", "grayscale")))
        if kind not in self.VALID_KINDS:
            kind = "grayscale"
        self.reroute_kind = kind
        self.parameters["_reroute_kind"] = kind
        self.resolved_image_kind = kind
        self.parameters["_resolved_kind"] = kind
        for port in (*self.input_ports.values(), *self.output_ports.values()):
            port.declared_kind = kind
            port.set_kind(kind)
        self.setToolTip(
            f"{kind.replace('_', ' ').title()} reroute · double-click a wire to add another"
        )
        self._position_ports()

    @property
    def height(self) -> float:
        return self.DIAMETER

    @property
    def bypassed(self) -> bool:
        return False

    def boundingRect(self) -> QRectF:
        return QRectF(0.0, 0.0, self.DIAMETER, self.DIAMETER)

    def _position_ports(self) -> None:
        centre = self.DIAMETER * 0.5
        for port in self.input_ports.values():
            port.setPos(0.0, centre)
        for port in self.output_ports.values():
            port.setPos(self.DIAMETER, centre)

    def set_resolved_image_kind(self, kind: str) -> bool:
        del kind
        return False

    def set_port_kind(self, name: str, kind: str, *, output: bool) -> bool:
        ports = self.output_ports if output else self.input_ports
        port = ports.get(name)
        if port is None:
            return False
        kind = normalise_port_kind(kind)
        changed = kind != port.kind or kind != port.declared_kind
        if changed:
            port.declared_kind = kind
            port.set_kind(kind)
            self.update()
        return changed

    def refresh_port_labels(self) -> None:
        for name, port in self.input_ports.items():
            port.display_name = self.definition.input_label(name)
        for name, port in self.output_ports.items():
            port.display_name = self.definition.output_label(name)
        self.prepareGeometryChange()
        self._position_ports()
        self.update()

    def output_data_kind(self, output_name: str | None = None) -> str:
        del output_name
        return self.reroute_kind

    def _is_bypassable(self) -> bool:
        return False

    def paint(self, painter: QPainter, option, widget=None) -> None:
        del option, widget
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        centre = QPointF(self.DIAMETER * 0.5, self.DIAMETER * 0.5)
        outer = 10.0 if self.isSelected() else 8.5
        painter.setBrush(QColor(theme_colour("node_body", "#2a2f37")))
        painter.setPen(
            QPen(
                QColor(
                    theme_colour("node_selected", "#d5dbff")
                    if self.isSelected()
                    else theme_colour("border_strong", "#59616e")
                ),
                2.2 if self.isSelected() else 1.5,
            )
        )
        painter.drawEllipse(centre, outer, outer)
        palette = {
            "grayscale": "#8d939d",
            "color": "#d7a449",
            "vector": "#4d8fd5",
            "material": "#b06ee8",
            "geometry": "#d2684a",
            "scalar": "#55b879",
            "vector2": "#45aa89",
            "vector3": "#3c9b7c",
        }
        painter.setBrush(QColor(palette.get(self.reroute_kind, "#8d939d")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(centre, 4.0, 4.0)


class GroupFrameItem(QGraphicsObject):
    TITLE_HEIGHT = 42.0
    MIN_WIDTH = 280.0
    MIN_HEIGHT = 180.0
    COLLAPSED_WIDTH = 245.0
    PORT_ROW_HEIGHT = 24.0
    RESIZE_HANDLE = 18.0

    def __init__(
        self,
        *,
        uid: str | None = None,
        name: str = "Group",
        description: str = "",
        category: str = "User",
        width: float = 520.0,
        height: float = 320.0,
        collapsed: bool = False,
        members: set[str] | None = None,
        exposed_parameters: list[dict] | None = None,
        interface_inputs: list[dict] | None = None,
        interface_outputs: list[dict] | None = None,
    ) -> None:
        super().__init__()
        self.uid = uid or uuid.uuid4().hex
        self.name = name
        self.description = description
        self.category = category or "User"
        self.frame_width = max(float(width), self.MIN_WIDTH)
        self.frame_height = max(float(height), self.MIN_HEIGHT)
        self.collapsed = bool(collapsed)
        self.members: set[str] = set(members or ())
        self.exposed_parameters: list[dict] = list(exposed_parameters or [])
        self.interface_inputs: list[dict] = list(interface_inputs or [])
        self.interface_outputs: list[dict] = list(interface_outputs or [])
        self.input_ports: dict[str, GroupPortItem] = {}
        self.output_ports: dict[str, GroupPortItem] = {}
        self._resizing = False
        self._resize_start_scene = QPointF()
        self._resize_start_size = (self.frame_width, self.frame_height)
        self._last_pos = QPointF()

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(0 if self.collapsed else -8)
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)

    @property
    def collapsed_height(self) -> float:
        rows = max(len(self.input_ports), len(self.output_ports), 1)
        return max(88.0, self.TITLE_HEIGHT + 15.0 + rows * self.PORT_ROW_HEIGHT)

    def boundingRect(self) -> QRectF:
        if self.collapsed:
            return QRectF(0, 0, self.COLLAPSED_WIDTH, self.collapsed_height)
        return QRectF(0, 0, self.frame_width, self.frame_height)

    def shape(self) -> QPainterPath:
        """Only the title bar moves an expanded group.

        The transparent body deliberately does not participate in hit-testing,
        so clicking and rubber-band dragging inside a frame behaves exactly like
        empty graph canvas. The resize handle remains interactive. Collapsed
        groups continue to behave like ordinary nodes across their full body.
        """
        path = QPainterPath()
        bounds = self.boundingRect()
        if self.collapsed:
            path.addRoundedRect(bounds, 9.0, 9.0)
            return path
        path.addRect(QRectF(0, 0, self.frame_width, self.TITLE_HEIGHT))
        path.addRect(
            QRectF(
                self.frame_width - self.RESIZE_HANDLE,
                self.frame_height - self.RESIZE_HANDLE,
                self.RESIZE_HANDLE,
                self.RESIZE_HANDLE,
            )
        )
        return path

    def content_scene_rect(self) -> QRectF:
        local = QRectF(5, self.TITLE_HEIGHT, self.frame_width - 10, self.frame_height - self.TITLE_HEIGHT - 5)
        mapped = self.mapRectToScene(local)
        return mapped if isinstance(mapped, QRectF) else mapped.boundingRect()

    def contains_node(self, node: NodeItem) -> bool:
        return self.content_scene_rect().contains(node.sceneBoundingRect().center())

    def _clear_ports(self) -> None:
        for port in [*self.input_ports.values(), *self.output_ports.values()]:
            port.setParentItem(None)
            scene = port.scene()
            if scene is not None:
                scene.removeItem(port)
        self.input_ports.clear()
        self.output_ports.clear()

    @staticmethod
    def _unique_label(base: str, used: set[str]) -> str:
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base} {suffix}"
            suffix += 1
        used.add(candidate)
        return candidate

    def rebuild_ports(self, scene: "GraphScene") -> None:
        self.prepareGeometryChange()
        self._clear_ports()
        member_nodes = [scene.nodes[uid] for uid in self.members if uid in scene.nodes]
        internal_connections = [
            connection
            for connection in scene.connections
            if connection.source_node.uid in self.members and connection.target_node.uid in self.members
        ]
        internally_driven = {(connection.target_node.uid, connection.input_name) for connection in internal_connections}
        internal_sources = {(connection.source_node.uid, connection.output_name) for connection in internal_connections}
        external_inputs = {
            (connection.target_node.uid, connection.input_name)
            for connection in scene.connections
            if connection.target_node.uid in self.members and connection.source_node.uid not in self.members
        }
        external_outputs = {
            (connection.source_node.uid, connection.output_name)
            for connection in scene.connections
            if connection.source_node.uid in self.members and connection.target_node.uid not in self.members
        }

        used_input_labels: set[str] = set()
        input_candidates: list[dict] = []
        duplicate_input_names = {
            input_name
            for node in member_nodes
            for input_name in node.input_ports
            if sum(1 for candidate in member_nodes if input_name in candidate.input_ports) > 1
        }
        for node in sorted(member_nodes, key=lambda candidate: (candidate.pos().x(), candidate.pos().y(), candidate.definition.name)):
            for input_name in node.input_ports:
                if (node.uid, input_name) in internally_driven:
                    continue
                display_name = node.input_ports[input_name].display_name
                base = f"{node.definition.name} · {display_name}" if input_name in duplicate_input_names else display_name
                input_candidates.append(
                    {
                        "node": node.uid,
                        "input": input_name,
                        "default_name": self._unique_label(base, used_input_labels),
                        "forced": (node.uid, input_name) in external_inputs,
                    }
                )

        used_output_labels: set[str] = set()
        output_candidates: list[dict] = []
        for node in sorted(member_nodes, key=lambda candidate: (candidate.pos().x(), candidate.pos().y(), candidate.definition.name)):
            for output_name in node.definition.output_names:
                key = (node.uid, output_name)
                if key in internal_sources and key not in external_outputs:
                    continue
                base = node.definition.name if len(node.definition.output_names) == 1 else f"{node.definition.name} · {output_name}"
                output_candidates.append({
                    "node": node.uid, "output": output_name,
                    "default_name": self._unique_label(base, used_output_labels),
                    "forced": key in external_outputs,
                })

        existing_inputs = {
            (str(entry.get("node", "")), str(entry.get("input", ""))): entry
            for entry in self.interface_inputs
        }
        synced_inputs: list[dict] = []
        candidate_input_map = {(entry["node"], entry["input"]): entry for entry in input_candidates}
        for old in self.interface_inputs:
            key = (str(old.get("node", "")), str(old.get("input", "")))
            candidate = candidate_input_map.pop(key, None)
            if candidate is None:
                continue
            synced_inputs.append(
                {
                    "node": candidate["node"],
                    "input": candidate["input"],
                    "name": str(old.get("name") or candidate["default_name"]),
                    "enabled": bool(old.get("enabled", True)) or bool(candidate["forced"]),
                }
            )
        for candidate in input_candidates:
            key = (candidate["node"], candidate["input"])
            if key in existing_inputs:
                continue
            synced_inputs.append(
                {
                    "node": candidate["node"],
                    "input": candidate["input"],
                    "name": candidate["default_name"],
                    "enabled": True,
                }
            )
        self.interface_inputs = synced_inputs

        existing_outputs = {(str(entry.get("node", "")), str(entry.get("output", "Image"))): entry for entry in self.interface_outputs}
        synced_outputs: list[dict] = []
        candidate_output_map = {(entry["node"], entry["output"]): entry for entry in output_candidates}
        for old in self.interface_outputs:
            key = (str(old.get("node", "")), str(old.get("output", "Image")))
            candidate = candidate_output_map.pop(key, None)
            if candidate is None:
                continue
            synced_outputs.append(
                {
                    "node": candidate["node"],
                    "output": candidate["output"],
                    "name": str(old.get("name") or candidate["default_name"]),
                    "enabled": bool(old.get("enabled", True)) or bool(candidate["forced"]),
                }
            )
        for candidate in output_candidates:
            if (candidate["node"], candidate["output"]) in existing_outputs:
                continue
            synced_outputs.append(
                {
                    "node": candidate["node"],
                    "output": candidate["output"],
                    "name": candidate["default_name"],
                    "enabled": True,
                }
            )
        self.interface_outputs = synced_outputs

        visible_inputs = [entry for entry in self.interface_inputs if bool(entry.get("enabled", True))]
        visible_outputs = [entry for entry in self.interface_outputs if bool(entry.get("enabled", True))]
        for index, entry in enumerate(visible_inputs):
            node_uid = str(entry["node"])
            input_name = str(entry["input"])
            key = f"{node_uid}:{input_name}"
            internal = scene.nodes.get(node_uid)
            kind = internal.input_ports[input_name].kind if internal is not None and input_name in internal.input_ports else "image"
            port = GroupPortItem(self, str(entry.get("name") or input_name), False, node_uid, input_name, kind=kind)
            port.setPos(0, self.TITLE_HEIGHT + 18 + index * self.PORT_ROW_HEIGHT)
            port.setVisible(self.collapsed)
            self.input_ports[key] = port

        for index, entry in enumerate(visible_outputs):
            node_uid = str(entry["node"]); output_name = str(entry.get("output", "Image"))
            key = f"{node_uid}:{output_name}"
            internal = scene.nodes.get(node_uid)
            kind = internal.output_ports[output_name].kind if internal is not None and output_name in internal.output_ports else "image"
            port = GroupPortItem(self, str(entry.get("name") or output_name), True, node_uid, output_name, kind=kind)
            port.setPos(self.COLLAPSED_WIDTH, self.TITLE_HEIGHT + 18 + index * self.PORT_ROW_HEIGHT)
            port.setVisible(self.collapsed)
            self.output_ports[key] = port
        self.update()

    def proxy_input(self, node_uid: str, input_name: str) -> GroupPortItem | None:
        return self.input_ports.get(f"{node_uid}:{input_name}")

    def proxy_output(self, node_uid: str, output_name: str = "Image") -> GroupPortItem | None:
        return self.output_ports.get(f"{node_uid}:{output_name}") or self.output_ports.get(f"{node_uid}:Image")

    def set_collapsed(self, collapsed: bool) -> None:
        if self.collapsed == collapsed:
            return
        self.prepareGeometryChange()
        self.collapsed = collapsed
        self.setZValue(0 if collapsed else -8)
        for port in [*self.input_ports.values(), *self.output_ports.values()]:
            port.setVisible(collapsed)
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        del option, widget
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = self.boundingRect()
        selected = self.isSelected()
        border = QColor(theme_colour("node_selected", "#b9c3ff")) if selected else QColor(theme_colour("border_strong", "#59637b"))
        border_width = 2.2 if selected else 1.4

        if self.collapsed:
            painter.setBrush(QColor(theme_colour("node_body", "#242930")))
            painter.setPen(QPen(border, border_width))
            painter.drawRoundedRect(bounds, 9, 9)
            header = QColor(theme_colour("accent", "#596a98"))
            path = QPainterPath()
            path.addRoundedRect(QRectF(0, 0, bounds.width(), self.TITLE_HEIGHT + 7), 9, 9)
            painter.fillPath(path, header)
            painter.fillRect(QRectF(0, self.TITLE_HEIGHT - 6, bounds.width(), 13), header)
            painter.setPen(QColor("#1d2127") if header.lightnessF() > 0.68 else QColor("#ffffff"))
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(
                QRectF(13, 0, bounds.width() - 26, self.TITLE_HEIGHT),
                Qt.AlignmentFlag.AlignVCenter,
                self.name,
            )
            font.setBold(False)
            painter.setFont(font)
            painter.setPen(QColor(theme_colour("node_text", "#c8ced9")))
            for index, port in enumerate(self.input_ports.values()):
                y = self.TITLE_HEIGHT + 6 + index * self.PORT_ROW_HEIGHT
                painter.drawText(QRectF(13, y, bounds.width() * 0.55, self.PORT_ROW_HEIGHT), Qt.AlignmentFlag.AlignVCenter, port.name)
            for index, port in enumerate(self.output_ports.values()):
                y = self.TITLE_HEIGHT + 6 + index * self.PORT_ROW_HEIGHT
                painter.drawText(
                    QRectF(bounds.width() * 0.45, y, bounds.width() * 0.55 - 13, self.PORT_ROW_HEIGHT),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                    port.name,
                )
            return

        group_fill = QColor(theme_colour("accent", "#596a98")); group_fill.setAlpha(38)
        painter.setBrush(group_fill)
        painter.setPen(QPen(border, border_width, Qt.PenStyle.SolidLine))
        painter.drawRoundedRect(bounds, 8, 8)
        group_header = QColor(theme_colour("accent", "#596a98")); group_header.setAlpha(185)
        painter.fillRect(QRectF(0, 0, bounds.width(), self.TITLE_HEIGHT), group_header)

        painter.setPen(QColor("#1d2127") if group_header.lightnessF() > 0.68 else QColor("#ffffff"))
        font = painter.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() + 0.5)
        painter.setFont(font)
        painter.drawText(QRectF(12, 0, bounds.width() - 24, 25), Qt.AlignmentFlag.AlignVCenter, self.name)
        if self.description:
            font.setBold(False)
            font.setPointSizeF(max(8.0, font.pointSizeF() - 1.0))
            painter.setFont(font)
            painter.setPen(QColor(theme_colour("node_text", "#bdc5d8")))
            painter.drawText(
                QRectF(12, 20, bounds.width() - 24, 20),
                Qt.AlignmentFlag.AlignVCenter,
                self.description.replace("\n", " ")[:140],
            )

        handle = QRectF(bounds.right() - self.RESIZE_HANDLE, bounds.bottom() - self.RESIZE_HANDLE, self.RESIZE_HANDLE, self.RESIZE_HANDLE)
        painter.setPen(QPen(QColor(theme_colour("border_strong", "#8d98b8")), 1.2))
        for offset in (5, 9, 13):
            painter.drawLine(
                QPointF(handle.right() - offset, handle.bottom()),
                QPointF(handle.right(), handle.bottom() - offset),
            )

    def _in_resize_handle(self, local_pos: QPointF) -> bool:
        if self.collapsed:
            return False
        return (
            local_pos.x() >= self.frame_width - self.RESIZE_HANDLE
            and local_pos.y() >= self.frame_height - self.RESIZE_HANDLE
        )

    def hoverMoveEvent(self, event) -> None:
        if self._in_resize_handle(event.pos()):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            self.unsetCursor()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._in_resize_handle(event.pos()):
            self._resizing = True
            self._resize_start_scene = event.scenePos()
            self._resize_start_size = (self.frame_width, self.frame_height)
            scene = self.scene()
            if scene is not None and hasattr(scene, "begin_user_action"):
                scene.begin_user_action("Resize Group")
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._resizing:
            delta = event.scenePos() - self._resize_start_scene
            self.prepareGeometryChange()
            self.frame_width = max(self.MIN_WIDTH, self._resize_start_size[0] + delta.x())
            self.frame_height = max(self.MIN_HEIGHT, self._resize_start_size[1] + delta.y())
            self.update()
            scene = self.scene()
            if scene is not None and hasattr(scene, "group_resized"):
                scene.group_resized(self)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._resizing and event.button() == Qt.MouseButton.LeftButton:
            self._resizing = False
            scene = self.scene()
            if scene is not None and hasattr(scene, "end_user_action"):
                scene.end_user_action()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        scene = self.scene()
        if scene is not None and hasattr(scene, "toggle_group"):
            scene.toggle_group(self)
        event.accept()

    def itemChange(self, change, value):
        result = super().itemChange(change, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            scene = self.scene()
            new_pos = self.pos()
            delta = new_pos - self._last_pos
            self._last_pos = QPointF(new_pos)
            if scene is not None and hasattr(scene, "group_moved") and not delta.isNull():
                scene.group_moved(self, delta)
        return result


class ConnectionItem(QGraphicsPathItem):
    def __init__(self, source_port: PortItem, target_port: PortItem) -> None:
        super().__init__()
        self.source_port = source_port
        self.target_port = target_port
        self.source_node = source_port.owner
        self.target_node = target_port.owner
        self.input_name = target_port.name
        self.output_name = source_port.name
        self._insert_candidate = False
        self._cut_candidate = False
        self._evaluation_flow = False
        self._evaluation_phase = 0.0
        self._broken = False
        self.setZValue(-2)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.update_path()

    def update_path(self) -> None:
        scene = self.scene()
        source_port = self.source_port
        target_port = self.target_port
        visible = True
        if scene is not None and hasattr(scene, "visual_ports_for_connection"):
            source_port, target_port, visible = scene.visual_ports_for_connection(self)
        self.setVisible(visible)
        if not visible or source_port is None or target_port is None:
            return
        start = source_port.centre_scene_pos()
        end = target_port.centre_scene_pos()
        distance = max(abs(end.x() - start.x()) * 0.5, 65.0)
        path = QPainterPath(start)
        path.cubicTo(start.x() + distance, start.y(), end.x() - distance, end.y(), end.x(), end.y())
        self.setPath(path)

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(14.0)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        return stroker.createStroke(self.path())

    def set_insert_candidate(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled != self._insert_candidate:
            self._insert_candidate = enabled
            self.update()

    def set_cut_candidate(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled != self._cut_candidate:
            self._cut_candidate = enabled
            self.update()

    def set_evaluation_flow(self, active: bool, phase: float | None = None) -> None:
        changed = self._evaluation_flow != bool(active)
        self._evaluation_flow = bool(active)
        if phase is not None:
            phase = float(phase) % 1.0
            changed = changed or abs(phase - self._evaluation_phase) > 1e-6
            self._evaluation_phase = phase
        if changed:
            self.update()

    @property
    def broken(self) -> bool:
        return self._broken

    def set_broken(self, broken: bool) -> None:
        broken = bool(broken)
        if broken != self._broken:
            self._broken = broken
            self.setToolTip(
                "Connection retained but inactive because the Receive channel type no longer matches this input."
                if broken else ""
            )
            self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        scene = self.scene()
        if scene is not None and hasattr(scene, "insert_reroute_on_connection"):
            scene.insert_reroute_on_connection(self, event.scenePos())
        event.accept()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        del option, widget
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = {
            "grayscale": ("#858b94", "#e0e3e8"),
            "color": ("#c99a42", "#ffe0a0"),
            "vector": ("#4384c7", "#9bcaff"),
            "material": ("#9d60d6", "#ddb6ff"),
            "geometry": ("#b9563d", "#ffb09a"),
            "scalar": ("#45a96c", "#9ff0b7"),
            "vector2": ("#3e9f82", "#8ee8c5"),
            "vector3": ("#388f75", "#82dab5"),
            "image_any": ("#747987", "#c9ccd5"),
        }
        normal, selected = palette.get(self.source_port.kind, palette["image_any"])
        if self._broken:
            colour = QColor("#ef5565")
            width = 3.2
        elif self._cut_candidate:
            colour = QColor("#ff5b6d")
            width = 4.4
        elif self._insert_candidate:
            colour = QColor("#77c8ff")
            width = 4.4
        else:
            colour = QColor(selected if self.isSelected() else normal)
            width = 3.0
        style = Qt.PenStyle.DashLine if self._broken else Qt.PenStyle.SolidLine
        painter.setPen(QPen(colour, width, style, Qt.PenCapStyle.RoundCap))
        painter.drawPath(self.path())
        if self._evaluation_flow:
            flow_pen = QPen(
                QColor(theme_colour("progress", "#ff9d36")),
                2.3,
                Qt.PenStyle.CustomDashLine,
                Qt.PenCapStyle.RoundCap,
            )
            flow_pen.setDashPattern([4.0, 5.5])
            flow_pen.setDashOffset(-self._evaluation_phase * 18.0)
            painter.setPen(flow_pen)
            painter.drawPath(self.path())

