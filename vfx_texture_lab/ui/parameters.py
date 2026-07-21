from __future__ import annotations

from dataclasses import replace
import math
from functools import partial
from typing import Callable

import numpy as np

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..document import GraphAssetMetadata
from ..export_templates import CUSTOM_TEMPLATE_NAME, effective_export_template, template_summary
from ..graph_asset_thumbnails import thumbnail_pixmap
from ..graph.items import GroupFrameItem, NodeItem
from ..histogram import (
    HISTOGRAM_INTERNAL_BINS,
    compute_histogram_distribution,
    stratified_image_sample,
)
from ..engine import AsyncEvaluationController, GraphSnapshot
from ..nodes.base import ParameterSpec, is_image_kind
from .spinboxes import CompactDoubleSpinBox, CompactSpinBox
from .visual_editor_foundation import PALETTE, VisualEditorCanvas


class AngleDial(QWidget):
    """Compact reusable direction dial for degree-based parameters.

    Dragging around the centre accumulates angular deltas, so parameters that
    legitimately support several turns (Rotate and Swirl) are not restricted to
    one revolution. The indicator itself always displays the normalised current
    direction. Ctrl and Shift use the same fine/coarse snapping metadata as the
    neighbouring slider and spin box.
    """

    valueEdited = Signal(float)
    editStarted = Signal()
    editFinished = Signal()

    def __init__(
        self,
        value: float,
        minimum: float,
        maximum: float,
        default: float,
        normal_step: float,
        fine_step: float,
        coarse_step: float,
        wrap: bool,
        wrap_minimum: float,
        wrap_maximum: float,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.minimum = float(minimum)
        self.maximum = float(maximum)
        self.default = float(default)
        self.normal_step = max(float(normal_step), 1.0e-9)
        self.fine_step = max(float(fine_step), 1.0e-9)
        self.coarse_step = max(float(coarse_step), self.fine_step)
        self.wrap = bool(wrap)
        self.wrap_minimum = max(float(wrap_minimum), self.minimum)
        self.wrap_maximum = min(float(wrap_maximum), self.maximum)
        if self.wrap_maximum <= self.wrap_minimum:
            self.wrap_minimum = self.minimum
            self.wrap_maximum = self.maximum
        self.value = min(max(float(value), self.minimum), self.maximum)
        self._dragging = False
        self._last_pointer_angle: float | None = None
        self._drag_value: float | None = None
        self.setFixedSize(58, 58)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(
            "Drag around the dial to change direction. Ctrl snaps to the fine step; "
            "Shift snaps to the coarse step. Double-click resets the value."
        )

    def _pointer_angle(self, point: QPointF) -> float | None:
        centre = QPointF(self.width() * 0.5, self.height() * 0.5)
        dx = float(point.x() - centre.x())
        dy = float(point.y() - centre.y())
        if dx * dx + dy * dy < 9.0:
            return None
        # Screen-space Y increases downwards, making positive values rotate
        # clockwise, matching the visible direction used by texture UVs.
        return math.degrees(math.atan2(dy, dx))

    @staticmethod
    def _wrapped_delta(current: float, previous: float) -> float:
        return (float(current) - float(previous) + 180.0) % 360.0 - 180.0

    def _interaction_step(self, modifiers: Qt.KeyboardModifier) -> float | None:
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            return self.coarse_step
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            return self.fine_step
        return None

    def _snap(self, value: float, modifiers: Qt.KeyboardModifier) -> float:
        increment = self._interaction_step(modifiers)
        if increment is None or increment <= 0.0:
            return value
        return round(value / increment) * increment

    def _set_user_value(self, value: float, modifiers: Qt.KeyboardModifier) -> None:
        value = self._snap(float(value), modifiers)
        if self.wrap:
            period = self.wrap_maximum - self.wrap_minimum
            value = (value - self.wrap_minimum) % period + self.wrap_minimum
        value = min(max(value, self.minimum), self.maximum)
        if math.isclose(value, self.value, rel_tol=0.0, abs_tol=1.0e-9):
            return
        self.value = value
        self.update()
        self.valueEdited.emit(value)

    def set_value(self, value: float) -> None:
        value = min(max(float(value), self.minimum), self.maximum)
        if math.isclose(value, self.value, rel_tol=0.0, abs_tol=1.0e-9):
            return
        self.value = value
        self.update()

    def _value_for_pointer_angle(self, angle: float) -> float:
        """Map a clicked direction to the authored range.

        Wrapped controls use the dial direction directly. Multi-turn controls
        choose the equivalent angle nearest the current authored value, so a
        click repositions the hand without unexpectedly discarding accumulated
        revolutions.
        """
        angle = float(angle)
        if self.wrap:
            period = self.wrap_maximum - self.wrap_minimum
            return (angle - self.wrap_minimum) % period + self.wrap_minimum
        turns = round((self.value - angle) / 360.0)
        return angle + turns * 360.0

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        angle = self._pointer_angle(event.position())
        if angle is None:
            return
        self._dragging = True
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.editStarted.emit()
        # A dial behaves like a physical control: clicking a direction moves the
        # hand there immediately, then subsequent motion continues smoothly.
        self._drag_value = self._value_for_pointer_angle(angle)
        self._set_user_value(self._drag_value, event.modifiers())
        self._last_pointer_angle = angle
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._dragging or self._last_pointer_angle is None:
            super().mouseMoveEvent(event)
            return
        angle = self._pointer_angle(event.position())
        if angle is None:
            return
        delta = self._wrapped_delta(angle, self._last_pointer_angle)
        self._last_pointer_angle = angle
        self._drag_value = (self._drag_value if self._drag_value is not None else self.value) + delta
        self._set_user_value(self._drag_value, event.modifiers())
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._last_pointer_angle = None
            self._drag_value = None
            self.editFinished.emit()
            self.clearFocus()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.editStarted.emit()
            self._set_user_value(self.default, event.modifiers())
            self.editFinished.emit()
            self.clearFocus()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event) -> None:
        steps = event.angleDelta().y() / 120.0
        if abs(steps) < 1.0e-9:
            event.ignore()
            return
        modifiers = event.modifiers()
        increment = self._interaction_step(modifiers) or self.normal_step
        self.editStarted.emit()
        self._set_user_value(self.value + steps * increment, modifiers)
        self.editFinished.emit()
        self.clearFocus()
        event.accept()

    def keyPressEvent(self, event) -> None:
        direction = 0
        if event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Up):
            direction = 1
        elif event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Down):
            direction = -1
        if direction:
            modifiers = event.modifiers()
            increment = self._interaction_step(modifiers) or self.normal_step
            self.editStarted.emit()
            self._set_user_value(self.value + direction * increment, modifiers)
            self.editFinished.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        centre = QPointF(self.width() * 0.5, self.height() * 0.5)
        radius = min(self.width(), self.height()) * 0.5 - 5.0

        fill = palette.window().color()
        fill = fill.lighter(112)
        border = palette.mid().color()
        foreground = palette.text().color()
        accent = palette.highlight().color()
        if not self.isEnabled():
            fill.setAlpha(100)
            border.setAlpha(90)
            foreground.setAlpha(90)
            accent.setAlpha(90)

        painter.setPen(QPen(border, 1.4))
        painter.setBrush(fill)
        painter.drawEllipse(centre, radius, radius)

        tick_pen = QPen(border, 1.0)
        painter.setPen(tick_pen)
        for degrees in (0.0, 90.0, 180.0, 270.0):
            radians = math.radians(degrees)
            outer = QPointF(centre.x() + math.cos(radians) * (radius - 1.0), centre.y() + math.sin(radians) * (radius - 1.0))
            inner = QPointF(centre.x() + math.cos(radians) * (radius - 5.0), centre.y() + math.sin(radians) * (radius - 5.0))
            painter.drawLine(inner, outer)

        radians = math.radians(self.value % 360.0)
        endpoint = QPointF(
            centre.x() + math.cos(radians) * (radius - 8.0),
            centre.y() + math.sin(radians) * (radius - 8.0),
        )
        painter.setPen(QPen(accent, 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(centre, endpoint)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawEllipse(centre, 3.2, 3.2)
        painter.setBrush(foreground)
        painter.drawEllipse(endpoint, 2.3, 2.3)

        if self.hasFocus():
            focus = QColor(accent)
            focus.setAlpha(170)
            painter.setPen(QPen(focus, 1.2, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(centre, radius + 2.0, radius + 2.0)
        painter.end()


class NumberControl(QWidget):
    editStarted = Signal()
    editFinished = Signal()

    def __init__(self, spec: ParameterSpec, value, changed, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        self.is_int = spec.kind == "int"
        hard_minimum = spec.minimum if spec.minimum is not None else 0
        hard_maximum = spec.maximum if spec.maximum is not None else 100
        self.minimum = float(hard_minimum)
        self.maximum = float(hard_maximum)
        slider_minimum = spec.slider_minimum if spec.slider_minimum is not None else hard_minimum
        slider_maximum = spec.slider_maximum if spec.slider_maximum is not None else hard_maximum
        self.slider_minimum = max(float(slider_minimum), self.minimum)
        self.slider_maximum = min(float(slider_maximum), self.maximum)
        if self.slider_maximum <= self.slider_minimum:
            self.slider_minimum = self.minimum
            self.slider_maximum = self.maximum

        normal_step = float(spec.step or (1 if self.is_int else 0.01))
        self.fine_step = float(spec.fine_step if spec.fine_step is not None else normal_step)
        self.coarse_step = float(spec.coarse_step if spec.coarse_step is not None else self.fine_step * 5.0)

        self.dial: AngleDial | None = None
        if str(spec.editor).strip().lower() == "angle":
            self.dial = AngleDial(
                float(value),
                self.minimum,
                self.maximum,
                float(spec.default),
                normal_step,
                self.fine_step,
                self.coarse_step,
                bool(spec.angle_wrap),
                self.slider_minimum,
                self.slider_maximum,
                self,
            )
            self.dial.valueEdited.connect(self._dial_changed)
            self.dial.editStarted.connect(self.editStarted.emit)
            self.dial.editFinished.connect(self.editFinished.emit)
            layout.addWidget(self.dial)

        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.steps = 1000
        self.slider.setRange(0, self.steps)

        if self.is_int:
            self.spin = CompactSpinBox(self)
            self.spin.setRange(int(hard_minimum), int(hard_maximum))
            self.spin.setSingleStep(max(int(spec.step or 1), 1))
            self.spin.setInteractionSteps(max(int(round(self.fine_step)), 1), max(int(round(self.coarse_step)), 1))
            self.spin.setValue(int(value))
        else:
            self.spin = CompactDoubleSpinBox(self)
            self.spin.setRange(float(hard_minimum), float(hard_maximum))
            self.spin.setSingleStep(normal_step)
            self.spin.setInteractionSteps(self.fine_step, self.coarse_step)
            self.spin.setDecimals(4)
            self.spin.setValue(float(value))
        unit = str(spec.unit).strip().lower()
        if unit in {"degree", "degrees", "deg", "°"}:
            self.spin.setSuffix("°")
        elif spec.unit:
            self.spin.setSuffix(f" {spec.unit}")
        self.spin.setMinimumWidth(104)
        self._set_slider_from_value(float(value))

        self._changed = changed
        self.slider.valueChanged.connect(self._slider_changed)
        self.slider.sliderPressed.connect(self.editStarted.emit)
        self.slider.sliderReleased.connect(self.editFinished.emit)
        self.spin.valueChanged.connect(self._spin_changed)

        layout.addWidget(self.slider, 1)
        layout.addWidget(self.spin)

    def _set_slider_from_value(self, value: float) -> None:
        span = max(self.slider_maximum - self.slider_minimum, 1e-9)
        normalised = (value - self.slider_minimum) / span
        self.slider.blockSignals(True)
        self.slider.setValue(round(max(0.0, min(1.0, normalised)) * self.steps))
        self.slider.blockSignals(False)

    def _snap_for_modifiers(self, value: float, modifiers: Qt.KeyboardModifier) -> float:
        increment = None
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            increment = self.coarse_step
        elif modifiers & Qt.KeyboardModifier.ControlModifier:
            increment = self.fine_step
        if increment is not None and increment > 0.0:
            value = round(value / increment) * increment
        if self.is_int:
            value = round(value)
        return min(max(float(value), self.minimum), self.maximum)

    def _sync_value_widgets(self, value: float, *, slider: bool = True) -> None:
        numeric = int(round(value)) if self.is_int else float(value)
        self.spin.blockSignals(True)
        self.spin.setValue(numeric)
        self.spin.blockSignals(False)
        if slider:
            self._set_slider_from_value(float(numeric))
        if self.dial is not None:
            self.dial.set_value(float(numeric))

    def _slider_changed(self, slider_value: int) -> None:
        value = self.slider_minimum + (slider_value / self.steps) * (self.slider_maximum - self.slider_minimum)
        value = self._snap_for_modifiers(value, QApplication.keyboardModifiers())
        self._sync_value_widgets(value)
        self._changed(int(round(value)) if self.is_int else value)

    def _spin_changed(self, value) -> None:
        numeric = int(value) if self.is_int else float(value)
        self._set_slider_from_value(float(numeric))
        if self.dial is not None:
            self.dial.set_value(float(numeric))
        self._changed(numeric)

    def _dial_changed(self, value: float) -> None:
        numeric = int(round(value)) if self.is_int else float(value)
        self._sync_value_widgets(float(numeric))
        self._changed(numeric)

    def set_value(self, value) -> None:
        """Update every control without reporting a user edit."""
        numeric = int(round(float(value))) if self.is_int else float(value)
        self._sync_value_widgets(float(numeric))


class ParameterGroupWidget(QWidget):
    """Compact collapsible section used by node parameter panels."""

    def __init__(self, title: str, *, expanded: bool = True, parent=None) -> None:
        super().__init__(parent)
        self._expanded = bool(expanded)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 2, 0, 2)
        outer.setSpacing(4)

        self.header = QToolButton(self)
        self.header.setObjectName("parameterGroupHeader")
        self.header.setText(str(title))
        self.header.setCheckable(True)
        self.header.setChecked(self._expanded)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setArrowType(Qt.ArrowType.DownArrow if self._expanded else Qt.ArrowType.RightArrow)
        self.header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.header.toggled.connect(self._set_expanded)
        outer.addWidget(self.header)

        self.body = QFrame(self)
        self.body.setObjectName("parameterGroupBody")
        self.form = QFormLayout(self.body)
        self.form.setContentsMargins(10, 7, 4, 8)
        self.form.setHorizontalSpacing(10)
        self.form.setVerticalSpacing(8)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.body.setVisible(self._expanded)
        outer.addWidget(self.body)

    def _set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self.header.setArrowType(Qt.ArrowType.DownArrow if self._expanded else Qt.ArrowType.RightArrow)
        self.body.setVisible(self._expanded)

    def addRow(self, *args) -> None:
        self.form.addRow(*args)



class ColourControl(QPushButton):
    def __init__(self, value: str, changed, parent=None) -> None:
        super().__init__(parent)
        self.value = value
        self.changed = changed
        self.clicked.connect(self.choose_colour)
        self._refresh()

    def _as_qcolor(self) -> QColor:
        text = self.value.strip().lstrip("#")
        if len(text) == 6:
            text += "ff"
        if len(text) != 8:
            text = "ffffffff"
        return QColor(f"#{text[6:8]}{text[0:6]}")

    def _refresh(self) -> None:
        color = self._as_qcolor()
        self.setText(self.value.upper())
        text = "#111111" if color.lightnessF() > 0.55 else "#ffffff"
        self.setStyleSheet(f"QPushButton {{ background: {color.name()}; color: {text}; font-weight: 600; }}")

    def choose_colour(self) -> None:
        color = QColorDialog.getColor(
            self._as_qcolor(),
            self.window(),
            "Choose colour",
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if not color.isValid():
            return
        qt_value = color.name(QColor.NameFormat.HexArgb).lstrip("#")
        self.value = f"#{qt_value[2:]}{qt_value[:2]}"
        self._refresh()
        self.changed(self.value)


class GradientRampWidget(VisualEditorCanvas):
    """Inline multi-stop editor used by Gradient Map and future ramps.

    Stops remain ordinary dictionaries so the graph format stays readable.  The
    interaction, sizing, selection, keyboard nudging and debounced publishing
    are supplied by :class:`VisualEditorCanvas`.
    """

    stopsChanged = Signal()
    selectionChanged = Signal()
    editColourRequested = Signal()

    MAX_STOPS = 8
    DEFAULT_STOPS = (
        {"position": 0.0, "color": "#000000ff"},
        {"position": 1.0, "color": "#ffffffff"},
    )

    def __init__(self, stops: list[dict], parent=None) -> None:
        super().__init__(editor_height=118, debounce_ms=38, parent=parent)
        normalised = self._normalise_stops(stops)
        if isinstance(stops, list):
            stops[:] = normalised
            self.stops = stops
        else:
            self.stops = normalised
        self.selected_stop: dict | None = self.stops[0] if self.stops else None
        self.hovered_stop: dict | None = None
        self._dragging = False
        self.valueEdited.connect(lambda _value: self.stopsChanged.emit())
        self.setToolTip(
            "Drag colour stops to reposition them. Double-click the ramp to add a stop; "
            "double-click a stop to edit its colour. Delete removes the selected stop."
        )

    @classmethod
    def _normalise_stops(cls, raw: object) -> list[dict]:
        result: list[dict] = []
        if isinstance(raw, list):
            for item in raw[: cls.MAX_STOPS]:
                if not isinstance(item, dict):
                    continue
                try:
                    position = min(max(float(item.get("position", 0.0)), 0.0), 1.0)
                except (TypeError, ValueError):
                    continue
                result.append({"position": position, "color": str(item.get("color", "#ffffffff"))})
        if len(result) < 2:
            result = [dict(item) for item in cls.DEFAULT_STOPS]
        result.sort(key=lambda item: float(item.get("position", 0.0)))
        return result

    @staticmethod
    def _qcolor(value: str) -> QColor:
        text = str(value).strip().lstrip("#")
        if len(text) == 6:
            text += "ff"
        if len(text) != 8:
            text = "ffffffff"
        return QColor(f"#{text[6:8]}{text[:6]}")

    @staticmethod
    def _rgba_text(colour: QColor) -> str:
        argb = colour.name(QColor.NameFormat.HexArgb).lstrip("#")
        return f"#{argb[2:]}{argb[:2]}"

    def current_value(self) -> list[dict]:
        return [dict(item) for item in self.stops]

    def gradient_rect(self) -> QRectF:
        return QRectF(18.0, 16.0, max(float(self.width()) - 36.0, 1.0), 54.0)

    def marker_position(self, stop: dict) -> QPointF:
        rect = self.gradient_rect()
        position = min(max(float(stop.get("position", 0.0)), 0.0), 1.0)
        return QPointF(rect.left() + position * rect.width(), rect.bottom() + 17.0)

    def _stop_at(self, point: QPointF) -> dict | None:
        best: tuple[float, dict] | None = None
        rect = self.gradient_rect()
        if point.y() < rect.top() - 7.0 or point.y() > rect.bottom() + 36.0:
            return None
        for stop in self.stops:
            marker = self.marker_position(stop)
            # Deliberately larger than the visible marker for comfortable use.
            distance = abs(point.x() - marker.x())
            if distance <= 13.0 and (best is None or distance < best[0]):
                best = (distance, stop)
        return best[1] if best else None

    def _position_from_x(self, x: float) -> float:
        rect = self.gradient_rect()
        return min(max((x - rect.left()) / max(rect.width(), 1.0), 0.0), 1.0)

    def _interpolated_colour(self, position: float) -> str:
        ordered = sorted(self.stops, key=lambda item: float(item.get("position", 0.0)))
        if not ordered:
            return "#ffffffff"
        if position <= float(ordered[0].get("position", 0.0)):
            return str(ordered[0].get("color", "#ffffffff"))
        if position >= float(ordered[-1].get("position", 1.0)):
            return str(ordered[-1].get("color", "#ffffffff"))
        for left, right in zip(ordered, ordered[1:]):
            left_pos = float(left.get("position", 0.0))
            right_pos = float(right.get("position", 1.0))
            if left_pos <= position <= right_pos:
                amount = (position - left_pos) / max(right_pos - left_pos, 1e-8)
                a = self._qcolor(str(left.get("color", "#ffffffff")))
                b = self._qcolor(str(right.get("color", "#ffffffff")))
                mixed = QColor.fromRgbF(
                    a.redF() + (b.redF() - a.redF()) * amount,
                    a.greenF() + (b.greenF() - a.greenF()) * amount,
                    a.blueF() + (b.blueF() - a.blueF()) * amount,
                    a.alphaF() + (b.alphaF() - a.alphaF()) * amount,
                )
                return self._rgba_text(mixed)
        return "#ffffffff"

    def _publish(self, *, immediate: bool = False) -> None:
        self.update()
        self.queue_edited_value(self.current_value(), immediate=immediate)

    def add_stop_at(self, position: float) -> bool:
        if len(self.stops) >= self.MAX_STOPS:
            return False
        position = min(max(float(position), 0.0), 1.0)
        stop = {"position": position, "color": self._interpolated_colour(position)}
        self.stops.append(stop)
        self.stops.sort(key=lambda item: float(item.get("position", 0.0)))
        self.selected_stop = stop
        self._publish(immediate=True)
        self.selectionChanged.emit()
        return True

    def add_stop_in_largest_gap(self) -> bool:
        ordered = sorted(float(stop.get("position", 0.0)) for stop in self.stops)
        gaps = [
            (ordered[index + 1] - ordered[index], ordered[index], ordered[index + 1])
            for index in range(len(ordered) - 1)
        ]
        position = (max(gaps)[1] + max(gaps)[2]) * 0.5 if gaps else 0.5
        return self.add_stop_at(position)

    def remove_selected(self) -> bool:
        if self.selected_stop is None or len(self.stops) <= 2:
            return False
        try:
            index = self.stops.index(self.selected_stop)
        except ValueError:
            return False
        self.stops.pop(index)
        self.selected_stop = self.stops[min(index, len(self.stops) - 1)]
        self._publish(immediate=True)
        self.selectionChanged.emit()
        return True

    def set_selected_position(self, position: float, *, immediate: bool = True) -> None:
        if self.selected_stop is None:
            return
        position = min(max(float(position), 0.0), 1.0)
        if abs(float(self.selected_stop.get("position", 0.0)) - position) < 1e-12:
            return
        self.selected_stop["position"] = position
        self.stops.sort(key=lambda item: float(item.get("position", 0.0)))
        self._publish(immediate=immediate)
        self.selectionChanged.emit()

    def set_selected_colour(self, value: str) -> None:
        if self.selected_stop is None or str(self.selected_stop.get("color", "")) == str(value):
            return
        self.selected_stop["color"] = str(value)
        self._publish(immediate=True)
        self.selectionChanged.emit()

    def can_reset(self) -> bool:
        return True

    def reset_to_default(self) -> None:
        self.stops[:] = [dict(item) for item in self.DEFAULT_STOPS]
        self.selected_stop = self.stops[0]
        self.hovered_stop = None
        self._publish(immediate=True)
        self.selectionChanged.emit()

    def populate_context_menu(self, menu) -> None:
        add = menu.addAction("Add Stop")
        add.setEnabled(len(self.stops) < self.MAX_STOPS)
        add.triggered.connect(self.add_stop_in_largest_gap)
        edit = menu.addAction("Edit Selected Colour…")
        edit.setEnabled(self.selected_stop is not None)
        edit.triggered.connect(self.editColourRequested.emit)
        remove = menu.addAction("Remove Selected Stop")
        remove.setEnabled(self.selected_stop is not None and len(self.stops) > 2)
        remove.triggered.connect(self.remove_selected)
        menu.addSeparator()
        super().populate_context_menu(menu)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.gradient_rect()

        self.draw_checkerboard(painter, rect)
        gradient = QLinearGradient(rect.left(), 0.0, rect.right(), 0.0)
        for stop in sorted(self.stops, key=lambda item: float(item.get("position", 0.0))):
            gradient.setColorAt(
                min(max(float(stop.get("position", 0.0)), 0.0), 1.0),
                self._qcolor(str(stop.get("color", "#ffffffff"))),
            )
        painter.fillRect(rect, gradient)
        self.draw_frame(painter, rect)

        for stop in self.stops:
            marker = self.marker_position(stop)
            selected = stop is self.selected_stop
            hovered = stop is self.hovered_stop
            fill = self._qcolor(str(stop.get("color", "#ffffffff")))
            triangle = self.triangle(marker.x(), rect.bottom() + 3.0, upward=True, size=7.0)
            border = QColor(PALETTE.selected_border if selected or hovered else PALETTE.background_alt)
            painter.setPen(QPen(border, 2.0 if selected else 1.0))
            painter.setBrush(fill)
            painter.drawPolygon(triangle)
            painter.drawEllipse(QPointF(marker.x(), rect.bottom() + 23.0), 6.0, 6.0)
            if selected:
                painter.setPen(QPen(QColor(PALETTE.selected), 1.0, Qt.PenStyle.DashLine))
                painter.drawLine(QPointF(marker.x(), rect.top()), QPointF(marker.x(), rect.bottom()))

        painter.setPen(QColor(PALETTE.text))
        painter.drawText(QPointF(rect.left(), rect.bottom() + 42.0), "0")
        painter.drawText(QPointF(rect.right() - 8.0, rect.bottom() + 42.0), "1")

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        stop = self._stop_at(event.position())
        if stop is not None:
            self.selected_stop = stop
            self._dragging = True
            self.begin_interaction()
            self.update()
            self.selectionChanged.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging and self.selected_stop is not None:
            self.set_selected_position(self._position_from_x(event.position().x()), immediate=False)
            event.accept()
            return
        hovered = self._stop_at(event.position())
        if hovered is not self.hovered_stop:
            self.hovered_stop = hovered
            self.update()
        self.setCursor(Qt.CursorShape.SizeHorCursor if hovered is not None else Qt.CursorShape.CrossCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.end_interaction()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        stop = self._stop_at(event.position())
        if stop is not None:
            self.selected_stop = stop
            self.update()
            self.selectionChanged.emit()
            self.editColourRequested.emit()
            event.accept()
            return
        if self.gradient_rect().adjusted(0.0, -5.0, 0.0, 5.0).contains(event.position()):
            self.add_stop_at(self._position_from_x(event.position().x()))
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.selected_stop is not None:
            # The visual editor owns deletion whenever one of its stops is
            # selected.  Consume the key even when the final two required
            # stops cannot be removed; never let it fall through to graph-node
            # deletion.
            self.remove_selected()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right) and self.selected_stop is not None:
            direction = -1.0 if event.key() == Qt.Key.Key_Left else 1.0
            step = self.keyboard_step(event)
            self.set_selected_position(float(self.selected_stop.get("position", 0.0)) + direction * step)
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.selected_stop is not None:
            self.editColourRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class GradientEditorDialog(QDialog):
    """Compatibility wrapper for third-party code that opened the old dialog.

    VFX Texture Lab itself now uses :class:`GradientControl` inline.  Keeping a
    small dialog wrapper avoids breaking extensions that imported this class.
    """

    def __init__(self, stops: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit gradient")
        self.resize(620, 300)
        layout = QVBoxLayout(self)
        self.control = GradientControl(stops, lambda value: setattr(self, "stops", value), self)
        self.stops = self.control.value
        layout.addWidget(self.control)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class GradientControl(QWidget):
    """Full inline gradient editor with the same toolbar model as curves."""

    editStarted = Signal()
    editFinished = Signal()

    def __init__(self, value, changed, parent=None) -> None:
        super().__init__(parent)
        self.changed = changed
        self.value = GradientRampWidget._normalise_stops(value)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(5)
        heading = QLabel("Gradient")
        heading.setObjectName("muted")
        self.add_button = QPushButton("Add")
        self.remove_button = QPushButton("Remove")
        self.reset_button = QPushButton("Reset")
        self.add_button.setToolTip("Add a colour stop in the largest empty span.")
        self.remove_button.setToolTip("Remove the selected stop. At least two stops are retained.")
        self.reset_button.setToolTip("Restore a neutral black-to-white gradient.")
        toolbar.addWidget(heading, 1)
        toolbar.addWidget(self.add_button)
        toolbar.addWidget(self.remove_button)
        toolbar.addWidget(self.reset_button)
        layout.addLayout(toolbar)

        self.ramp = GradientRampWidget(self.value, self)
        self.value = self.ramp.stops
        layout.addWidget(self.ramp)

        exact = QHBoxLayout()
        exact.setSpacing(6)
        self.position = CompactDoubleSpinBox()
        self.position.setRange(0.0, 1.0)
        self.position.setDecimals(4)
        self.position.setSingleStep(0.01)
        self.position.setKeyboardTracking(False)
        self.colour = ColourControl("#ffffffff", self._colour_changed)
        exact.addWidget(QLabel("Position"))
        exact.addWidget(self.position, 1)
        exact.addWidget(QLabel("Colour"))
        exact.addWidget(self.colour, 1)
        layout.addLayout(exact)

        hint = QLabel("Drag stops directly. Double-click the ramp to add; Delete removes the selected stop.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.ramp.stopsChanged.connect(self._stops_changed)
        self.ramp.selectionChanged.connect(self._selection_changed)
        self.ramp.editColourRequested.connect(self.colour.choose_colour)
        self.ramp.interactionStarted.connect(self.editStarted.emit)
        self.ramp.interactionFinished.connect(self.editFinished.emit)
        self.add_button.clicked.connect(lambda _checked=False: self.ramp.add_stop_in_largest_gap())
        self.remove_button.clicked.connect(lambda _checked=False: self.ramp.remove_selected())
        self.reset_button.clicked.connect(lambda _checked=False: self.ramp.reset_to_default())
        self.position.valueChanged.connect(self._position_changed)
        self._selection_changed()

    def _stops_changed(self) -> None:
        self.value = self.ramp.current_value()
        self.changed([dict(item) for item in self.value])
        self._selection_changed()

    def _selection_changed(self) -> None:
        stop = self.ramp.selected_stop
        enabled = stop is not None
        self.position.setEnabled(enabled)
        self.colour.setEnabled(enabled)
        self.remove_button.setEnabled(enabled and len(self.ramp.stops) > 2)
        self.add_button.setEnabled(len(self.ramp.stops) < self.ramp.MAX_STOPS)
        if stop is None:
            return
        self.position.blockSignals(True)
        self.position.setValue(float(stop.get("position", 0.0)))
        self.position.blockSignals(False)
        self.colour.value = str(stop.get("color", "#ffffffff"))
        self.colour._refresh()

    def _position_changed(self, value: float) -> None:
        self.ramp.set_selected_position(value)

    def _colour_changed(self, value: str) -> None:
        self.ramp.set_selected_colour(value)


class CurveGraphWidget(VisualEditorCanvas):
    """Inline, Substance-style response-curve editor.

    Tone curves use a fixed 0-1 domain and range. Animation curves retain the
    wider numeric behaviour of the original node and automatically frame all
    authored points while keeping 0-1 visible as a useful reference.
    """

    pointsChanged = Signal(object)
    selectionChanged = Signal(int)

    MAX_POINTS = 8
    MIN_X_SEPARATION = 1e-4

    def __init__(
        self,
        points: list[dict],
        interpolation: str = "Smooth",
        *,
        role: str = "tone",
        parent=None,
    ) -> None:
        super().__init__(editor_height=250, debounce_ms=38, supports_grid=True, parent=parent)
        self.role = "animation" if role == "animation" else "tone"
        self.interpolation = "Linear" if interpolation == "Linear" else "Smooth"
        self.points = self._normalise_points(points)
        self.selected_index = 0
        self.hovered_index = -1
        self._dragging = False
        self._drag_view: tuple[float, float, float, float] | None = None
        self.valueEdited.connect(self.pointsChanged.emit)
        self.setToolTip(
            "Drag points to reshape the curve. Double-click empty space to add a point. "
            "Select a point and press Delete to remove it."
        )

    def _normalise_points(self, raw: object) -> list[dict[str, float]]:
        result: list[dict[str, float]] = []
        if isinstance(raw, list):
            for item in raw[: self.MAX_POINTS]:
                if not isinstance(item, dict):
                    continue
                try:
                    x = float(item.get("x", 0.0))
                    y = float(item.get("y", 0.0))
                except (TypeError, ValueError):
                    continue
                if not np.isfinite(x) or not np.isfinite(y):
                    continue
                if self.role == "tone":
                    x = min(max(x, 0.0), 1.0)
                    y = min(max(y, 0.0), 1.0)
                result.append({"x": x, "y": y})
        if len(result) < 2:
            result = [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]
        result.sort(key=lambda item: float(item["x"]))
        # Keep duplicate X values editable and unambiguous.
        for index in range(1, len(result)):
            minimum = float(result[index - 1]["x"]) + self.MIN_X_SEPARATION
            if float(result[index]["x"]) < minimum:
                result[index]["x"] = minimum
        if self.role == "tone" and result[-1]["x"] > 1.0:
            shift = result[-1]["x"] - 1.0
            for point in result:
                point["x"] = min(max(float(point["x"]) - shift, 0.0), 1.0)
        return result

    def plot_rect(self) -> QRectF:
        return QRectF(34.0, 12.0, max(float(self.width()) - 48.0, 1.0), max(float(self.height()) - 39.0, 1.0))

    def view_bounds(self) -> tuple[float, float, float, float]:
        if self._drag_view is not None:
            return self._drag_view
        if self.role == "tone":
            return (0.0, 1.0, 0.0, 1.0)
        xs = [0.0, 1.0, *(float(point["x"]) for point in self.points)]
        ys = [0.0, 1.0, *(float(point["y"]) for point in self.points)]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        x_span = max(x_max - x_min, 1.0)
        y_span = max(y_max - y_min, 1.0)
        return (
            x_min - x_span * 0.08,
            x_max + x_span * 0.08,
            y_min - y_span * 0.08,
            y_max + y_span * 0.08,
        )

    def data_to_screen(self, x: float, y: float) -> QPointF:
        rect = self.plot_rect()
        x_min, x_max, y_min, y_max = self.view_bounds()
        px = rect.left() + (x - x_min) / max(x_max - x_min, 1e-12) * rect.width()
        py = rect.bottom() - (y - y_min) / max(y_max - y_min, 1e-12) * rect.height()
        return QPointF(px, py)

    def screen_to_data(self, point: QPointF) -> tuple[float, float]:
        rect = self.plot_rect()
        x_min, x_max, y_min, y_max = self.view_bounds()
        nx = min(max((point.x() - rect.left()) / max(rect.width(), 1.0), 0.0), 1.0)
        ny = min(max((rect.bottom() - point.y()) / max(rect.height(), 1.0), 0.0), 1.0)
        return (x_min + nx * (x_max - x_min), y_min + ny * (y_max - y_min))

    def _segment_value(self, index: int, x: float) -> float:
        a = self.points[index]
        b = self.points[index + 1]
        x0, y0 = float(a["x"]), float(a["y"])
        x1, y1 = float(b["x"]), float(b["y"])
        t = min(max((x - x0) / max(x1 - x0, 1e-12), 0.0), 1.0)
        if self.interpolation == "Linear":
            return y0 + (y1 - y0) * t
        if self.role == "animation":
            smooth_t = t * t * (3.0 - 2.0 * t)
            return y0 + (y1 - y0) * smooth_t
        previous = self.points[max(index - 1, 0)]
        following = self.points[min(index + 2, len(self.points) - 1)]
        slope0 = (y1 - float(previous["y"])) / max(x1 - float(previous["x"]), 1e-12)
        slope1 = (float(following["y"]) - y0) / max(float(following["x"]) - x0, 1e-12)
        t2 = t * t
        t3 = t2 * t
        h00 = 2.0 * t3 - 3.0 * t2 + 1.0
        h10 = t3 - 2.0 * t2 + t
        h01 = -2.0 * t3 + 3.0 * t2
        h11 = t3 - t2
        value = h00 * y0 + h10 * (x1 - x0) * slope0 + h01 * y1 + h11 * (x1 - x0) * slope1
        return min(max(value, 0.0), 1.0) if self.role == "tone" else value

    def evaluate(self, x: float) -> float:
        if x <= float(self.points[0]["x"]):
            return float(self.points[0]["y"])
        if x >= float(self.points[-1]["x"]):
            return float(self.points[-1]["y"])
        for index in range(len(self.points) - 1):
            if float(self.points[index]["x"]) <= x <= float(self.points[index + 1]["x"]):
                return self._segment_value(index, x)
        return x

    def _point_at(self, position: QPointF) -> int:
        candidates: list[tuple[float, int]] = []
        for index, point in enumerate(self.points):
            screen = self.data_to_screen(float(point["x"]), float(point["y"]))
            distance = ((screen.x() - position.x()) ** 2 + (screen.y() - position.y()) ** 2) ** 0.5
            if distance <= 13.0:
                candidates.append((distance, index))
        if not candidates:
            return -1
        candidates.sort(key=lambda item: item[0])
        closest = candidates[0][0]
        tied = [index for distance, index in candidates if abs(distance - closest) <= 1.0]
        if len(tied) > 1 and self.selected_index in tied:
            selected_position = tied.index(self.selected_index)
            return tied[(selected_position + 1) % len(tied)]
        return tied[0]

    def _emit_points(self, *, immediate: bool | None = None) -> None:
        if immediate is None:
            immediate = not self.interaction_active
        self.queue_edited_value([dict(point) for point in self.points], immediate=immediate)
        self.update()

    def select_index(self, index: int) -> None:
        if not self.points:
            self.selected_index = -1
        else:
            self.selected_index = min(max(int(index), 0), len(self.points) - 1)
        self.selectionChanged.emit(self.selected_index)
        self.update()

    def selected_point(self) -> dict[str, float] | None:
        if 0 <= self.selected_index < len(self.points):
            return self.points[self.selected_index]
        return None

    def set_selected_point(self, x: float, y: float, *, emit: bool = True) -> None:
        if not 0 <= self.selected_index < len(self.points):
            return
        if self.role == "tone":
            x = min(max(float(x), 0.0), 1.0)
            y = min(max(float(y), 0.0), 1.0)
        else:
            x = min(max(float(x), -1000.0), 1000.0)
            y = min(max(float(y), -1000.0), 1000.0)
        if self.selected_index > 0:
            x = max(x, float(self.points[self.selected_index - 1]["x"]) + self.MIN_X_SEPARATION)
        if self.selected_index < len(self.points) - 1:
            x = min(x, float(self.points[self.selected_index + 1]["x"]) - self.MIN_X_SEPARATION)
        point = self.points[self.selected_index]
        if abs(float(point["x"]) - x) < 1e-12 and abs(float(point["y"]) - y) < 1e-12:
            return
        point["x"] = x
        point["y"] = y
        if emit:
            self._emit_points()
        else:
            self.update()
        self.selectionChanged.emit(self.selected_index)

    def add_point(self, x: float, y: float | None = None) -> bool:
        if len(self.points) >= self.MAX_POINTS:
            return False
        if self.role == "tone":
            x = min(max(float(x), 0.0), 1.0)
        else:
            x = min(max(float(x), -1000.0), 1000.0)
        if any(abs(float(point["x"]) - x) < self.MIN_X_SEPARATION for point in self.points):
            return False
        value = self.evaluate(x) if y is None else float(y)
        if self.role == "tone":
            value = min(max(value, 0.0), 1.0)
        self.points.append({"x": x, "y": value})
        self.points.sort(key=lambda item: float(item["x"]))
        self.selected_index = next(index for index, point in enumerate(self.points) if point["x"] == x)
        self._emit_points()
        self.selectionChanged.emit(self.selected_index)
        return True

    def add_point_in_largest_gap(self) -> bool:
        ordered = sorted(self.points, key=lambda item: float(item["x"]))
        gaps = [
            (float(right["x"]) - float(left["x"]), float(left["x"]), float(right["x"]))
            for left, right in zip(ordered, ordered[1:])
        ]
        if gaps:
            _size, left, right = max(gaps)
            x = (left + right) * 0.5
        else:
            x = 0.5
        return self.add_point(x)

    def remove_selected(self) -> bool:
        if len(self.points) <= 2 or not 0 <= self.selected_index < len(self.points):
            return False
        self.points.pop(self.selected_index)
        self.selected_index = min(self.selected_index, len(self.points) - 1)
        self._emit_points()
        self.selectionChanged.emit(self.selected_index)
        return True

    def reset(self) -> None:
        self.points = [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]
        self.selected_index = 0
        self._emit_points()
        self.selectionChanged.emit(self.selected_index)

    def set_interpolation(self, interpolation: str) -> None:
        self.interpolation = "Linear" if interpolation == "Linear" else "Smooth"
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.plot_rect()
        self.draw_editor_background(painter, rect)
        if self.grid_visible:
            self.draw_grid(painter, rect, divisions=4)

        x_min, x_max, y_min, y_max = self.view_bounds()
        axis_pen = QPen(QColor("#4a525f"), 1.0)
        painter.setPen(axis_pen)
        if x_min <= 0.0 <= x_max:
            zero_x = self.data_to_screen(0.0, y_min).x()
            painter.drawLine(QPointF(zero_x, rect.top()), QPointF(zero_x, rect.bottom()))
        if y_min <= 0.0 <= y_max:
            zero_y = self.data_to_screen(x_min, 0.0).y()
            painter.drawLine(QPointF(rect.left(), zero_y), QPointF(rect.right(), zero_y))

        self.draw_frame(painter, rect)

        # Neutral y=x guide, clipped to the visible graph area.
        painter.save()
        painter.setClipRect(rect)
        painter.setPen(QPen(QColor("#3c434e"), 1.0, Qt.PenStyle.DashLine))
        painter.drawLine(self.data_to_screen(x_min, x_min), self.data_to_screen(x_max, x_max))

        curve = QPainterPath()
        samples = max(int(rect.width()), 64)
        for index in range(samples + 1):
            x = x_min + (x_max - x_min) * index / samples
            screen = self.data_to_screen(x, self.evaluate(x))
            if index == 0:
                curve.moveTo(screen)
            else:
                curve.lineTo(screen)
        painter.setPen(QPen(QColor("#d4d9e1"), 2.0))
        painter.drawPath(curve)
        painter.restore()

        for index, point in enumerate(self.points):
            position = self.data_to_screen(float(point["x"]), float(point["y"]))
            self.draw_square_handle(
                painter,
                position,
                selected=index == self.selected_index,
                hovered=index == self.hovered_index,
                size=8.0,
            )

        painter.setPen(QColor("#8e97a5"))
        painter.drawText(QPointF(rect.left(), rect.bottom() + 17.0), f"{x_min:.3g}")
        right_label = f"{x_max:.3g}"
        width = painter.fontMetrics().horizontalAdvance(right_label)
        painter.drawText(QPointF(rect.right() - width, rect.bottom() + 17.0), right_label)
        top_label = f"{y_max:.3g}"
        painter.drawText(QPointF(rect.left() - painter.fontMetrics().horizontalAdvance(top_label) - 7.0, rect.top() + 5.0), top_label)
        bottom_label = f"{y_min:.3g}"
        painter.drawText(QPointF(rect.left() - painter.fontMetrics().horizontalAdvance(bottom_label) - 7.0, rect.bottom()), bottom_label)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        index = self._point_at(event.position())
        if index >= 0:
            self.select_index(index)
            self._dragging = True
            self._drag_view = self.view_bounds()
            self.begin_interaction()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            x, y = self.screen_to_data(event.position())
            self.set_selected_point(x, y)
            event.accept()
            return
        index = self._point_at(event.position())
        if index != self.hovered_index:
            self.hovered_index = index
            self.update()
        self.setCursor(Qt.CursorShape.SizeAllCursor if index >= 0 else Qt.CursorShape.CrossCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self._drag_view = None
            self.end_interaction()
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.plot_rect().contains(event.position()):
            x, y = self.screen_to_data(event.position())
            self.add_point(x, y)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def can_reset(self) -> bool:
        return True

    def reset_to_default(self) -> None:
        self.reset()

    def populate_context_menu(self, menu) -> None:
        add = menu.addAction("Add Point")
        add.setEnabled(len(self.points) < self.MAX_POINTS)
        add.triggered.connect(self.add_point_in_largest_gap)
        remove = menu.addAction("Remove Selected Point")
        remove.setEnabled(0 <= self.selected_index < len(self.points) and len(self.points) > 2)
        remove.triggered.connect(self.remove_selected)
        menu.addSeparator()
        super().populate_context_menu(menu)

    def keyPressEvent(self, event) -> None:
        if (
            event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
            and 0 <= self.selected_index < len(self.points)
        ):
            # Once a curve point is selected, Delete/Backspace belongs to the
            # curve editor.  Endpoints/minimum-point constraints may reject the
            # removal, but the key must still not bubble up and delete the node.
            self.remove_selected()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            point = self.selected_point()
            if point is not None:
                step = self.keyboard_step(event)
                dx = (-step if event.key() == Qt.Key.Key_Left else step if event.key() == Qt.Key.Key_Right else 0.0)
                dy = (step if event.key() == Qt.Key.Key_Up else -step if event.key() == Qt.Key.Key_Down else 0.0)
                self.set_selected_point(float(point["x"]) + dx, float(point["y"]) + dy)
                event.accept()
                return
        super().keyPressEvent(event)


class CurveControl(QWidget):
    """Full inline editor shared by Tone Curve and Animation Curve nodes."""

    editStarted = Signal()
    editFinished = Signal()

    def __init__(
        self,
        value,
        changed,
        interpolation: str = "Smooth",
        interpolation_changed=None,
        *,
        role: str = "tone",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.role = role
        self.changed = changed
        self._has_interpolation_callback = interpolation_changed is not None
        self.interpolation_changed = interpolation_changed or (lambda _value: None)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(5)
        self.interpolation = QComboBox()
        self.interpolation.addItems(("Smooth", "Linear"))
        self.interpolation.setCurrentText("Linear" if interpolation == "Linear" else "Smooth")
        self.interpolation.setToolTip("Choose how the curve travels between authored points.")
        self.interpolation.setEnabled(self._has_interpolation_callback)
        self.grid_button = QToolButton()
        self.grid_button.setText("Grid")
        self.grid_button.setCheckable(True)
        self.grid_button.setChecked(True)
        self.grid_button.setToolTip("Show or hide the curve grid.")
        self.add_button = QPushButton("Add")
        self.remove_button = QPushButton("Remove")
        self.reset_button = QPushButton("Reset")
        self.add_button.setToolTip("Add a point in the largest empty span.")
        self.remove_button.setToolTip("Remove the selected point. At least two points are retained.")
        self.reset_button.setToolTip("Restore the neutral diagonal curve.")
        toolbar.addWidget(self.interpolation, 1)
        toolbar.addWidget(self.grid_button)
        toolbar.addWidget(self.add_button)
        toolbar.addWidget(self.remove_button)
        toolbar.addWidget(self.reset_button)
        layout.addLayout(toolbar)

        self.graph = CurveGraphWidget(
            value if isinstance(value, list) else [],
            self.interpolation.currentText(),
            role=role,
            parent=self,
        )
        layout.addWidget(self.graph)

        coordinate_row = QHBoxLayout()
        coordinate_row.setSpacing(6)
        self.x = CompactDoubleSpinBox()
        self.y = CompactDoubleSpinBox()
        minimum, maximum = (0.0, 1.0) if role == "tone" else (-1000.0, 1000.0)
        for control in (self.x, self.y):
            control.setRange(minimum, maximum)
            control.setDecimals(4)
            control.setSingleStep(0.01)
            control.setKeyboardTracking(False)
        coordinate_row.addWidget(QLabel("Input X"))
        coordinate_row.addWidget(self.x, 1)
        coordinate_row.addWidget(QLabel("Output Y"))
        coordinate_row.addWidget(self.y, 1)
        layout.addLayout(coordinate_row)

        hint = QLabel("Drag points directly. Double-click to add; Delete removes the selected point. Maximum 8 points.")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        layout.addWidget(hint)

        self.graph.pointsChanged.connect(self._points_changed)
        self.graph.selectionChanged.connect(self._selection_changed)
        self.graph.interactionStarted.connect(self.editStarted.emit)
        self.graph.interactionFinished.connect(self.editFinished.emit)
        self.graph.gridVisibilityChanged.connect(self.grid_button.setChecked)
        self.grid_button.toggled.connect(self.graph.set_grid_visible)
        self.interpolation.currentTextChanged.connect(self._interpolation_changed)
        self.add_button.clicked.connect(lambda _checked=False: self.graph.add_point_in_largest_gap())
        self.remove_button.clicked.connect(lambda _checked=False: self.graph.remove_selected())
        self.reset_button.clicked.connect(lambda _checked=False: self.graph.reset())
        self.x.valueChanged.connect(self._coordinate_changed)
        self.y.valueChanged.connect(self._coordinate_changed)
        self._selection_changed(self.graph.selected_index)

    def _points_changed(self, points: list[dict]) -> None:
        self.changed([dict(point) for point in points])
        self._selection_changed(self.graph.selected_index)

    def _selection_changed(self, _index: int) -> None:
        point = self.graph.selected_point()
        enabled = point is not None
        self.x.setEnabled(enabled)
        self.y.setEnabled(enabled)
        self.remove_button.setEnabled(enabled and len(self.graph.points) > 2)
        self.add_button.setEnabled(len(self.graph.points) < self.graph.MAX_POINTS)
        if point is None:
            return
        self.x.blockSignals(True)
        self.y.blockSignals(True)
        self.x.setValue(float(point["x"]))
        self.y.setValue(float(point["y"]))
        self.x.blockSignals(False)
        self.y.blockSignals(False)

    def _coordinate_changed(self) -> None:
        self.graph.set_selected_point(self.x.value(), self.y.value())

    def _interpolation_changed(self, interpolation: str) -> None:
        self.graph.set_interpolation(interpolation)
        self.interpolation_changed(interpolation)


class FileControl(QWidget):
    def __init__(self, value: str, changed, reloaded, parent=None, *, file_kind: str = "image") -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.edit = QLineEdit(str(value), self)
        self.file_kind = file_kind
        self.edit.setPlaceholderText("Choose a glTF / GLB mesh…" if file_kind == "mesh" else "Choose an image file…")
        self.edit.editingFinished.connect(lambda: changed(self.edit.text().strip()))
        browse = QPushButton("Browse…", self)
        browse.clicked.connect(self._browse)
        reload_button = QPushButton("Reload", self)
        reload_button.clicked.connect(lambda: reloaded(self.edit.text().strip()))
        self._changed = changed
        layout.addWidget(self.edit, 1)
        layout.addWidget(browse)
        layout.addWidget(reload_button)

    def _browse(self) -> None:
        if self.file_kind == "mesh":
            title = "Choose preview mesh"
            filters = "glTF 2.0 meshes (*.gltf *.glb);;All files (*)"
        else:
            title = "Choose image"
            filters = "Images (*.png *.tga *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;All files (*)"
        filename, _ = QFileDialog.getOpenFileName(
            self,
            title,
            self.edit.text(),
            filters,
        )
        if filename:
            self.edit.setText(filename)
            self._changed(filename)



class LevelsHistogramWidget(VisualEditorCanvas):
    """Live histogram with the five conventional Levels handles.

    The three upper handles define the input remap. The middle handle is stored
    as a normalized position between input low/high, matching the neutral 0.5
    midpoint used by Substance-style Levels interfaces. The two lower handles
    define the output range and may cross for inversion.
    """

    levelsChanged = Signal(object)

    def __init__(self, values: dict[str, object], parent=None) -> None:
        super().__init__(editor_height=230, debounce_ms=38, parent=parent)
        self.values = dict(values)
        self.histogram = np.zeros(HISTOGRAM_INTERNAL_BINS, dtype=np.float64)
        self.histogram_underflow = 0
        self.histogram_overflow = 0
        self.status_text = "Evaluating input histogram…"
        self._dragged: str | None = None
        self.selected_marker: str | None = "in_mid"
        self.hovered_marker: str | None = None
        self.valueEdited.connect(self.levelsChanged.emit)
        self.setToolTip(
            "Drag the five handles directly. Left/Right nudges the selected handle; "
            "hold Shift for fine movement."
        )

    def set_values(self, values: dict[str, object]) -> None:
        self.values.update(values)
        self.update()

    def set_histogram(
        self,
        histogram: np.ndarray | None,
        status: str = "",
        *,
        underflow: int = 0,
        overflow: int = 0,
    ) -> None:
        self.histogram = self.normalise_histogram(histogram)
        self.histogram_underflow = max(int(underflow), 0)
        self.histogram_overflow = max(int(overflow), 0)
        self.status_text = status
        self.update()

    def _plot_rect(self) -> QRectF:
        return QRectF(26.0, 31.0, max(float(self.width()) - 52.0, 80.0), max(float(self.height()) - 76.0, 90.0))

    def _x_for_value(self, value: float) -> float:
        rect = self._plot_rect()
        return rect.left() + min(max(float(value), 0.0), 1.0) * rect.width()

    def _input_mid_x(self) -> float:
        low = float(self.values.get("in_low", 0.0))
        high = float(self.values.get("in_high", 1.0))
        mid = float(self.values.get("in_mid", 0.5))
        return self._x_for_value(low + mid * max(high - low, 0.0))

    def _marker_x(self, name: str) -> float:
        if name == "in_mid":
            return self._input_mid_x()
        return self._x_for_value(float(self.values.get(name, 0.0)))

    def _marker_at(self, point: QPointF) -> str | None:
        rect = self._plot_rect()
        candidates: list[tuple[float, str]] = []
        if point.y() <= rect.top() + 17.0:
            for name in ("in_low", "in_mid", "in_high"):
                candidates.append((abs(point.x() - self._marker_x(name)), name))
        if point.y() >= rect.bottom() - 8.0:
            for name in ("out_low", "out_high"):
                candidates.append((abs(point.x() - self._marker_x(name)), name))
        if not candidates:
            return None
        distance, name = min(candidates)
        return name if distance <= 13.0 else None

    def _value_from_x(self, x: float) -> float:
        rect = self._plot_rect()
        return min(max((float(x) - rect.left()) / max(rect.width(), 1.0), 0.0), 1.0)

    def _apply_drag(self, name: str, x: float) -> None:
        value = self._value_from_x(x)
        low = float(self.values.get("in_low", 0.0))
        high = float(self.values.get("in_high", 1.0))
        if name == "in_low":
            value = min(value, high - 0.001)
        elif name == "in_high":
            value = max(value, low + 0.001)
        elif name == "in_mid":
            value = (value - low) / max(high - low, 1e-6)
            value = min(max(value, 0.001), 0.999)
        self.values[name] = value
        self.selected_marker = name
        self.update()
        self.queue_edited_value(dict(self.values), immediate=not self.interaction_active)

    @staticmethod
    def _triangle(x: float, y: float, upward: bool) -> QPolygonF:
        if upward:
            return QPolygonF([QPointF(x, y), QPointF(x - 7.0, y + 11.0), QPointF(x + 7.0, y + 11.0)])
        return QPolygonF([QPointF(x, y), QPointF(x - 7.0, y - 11.0), QPointF(x + 7.0, y - 11.0)])

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self._plot_rect()
        self.draw_editor_background(painter, rect, neutral_ramp=True)
        self.draw_histogram(
            painter, rect, self.histogram, status_text=self.status_text,
            underflow=self.histogram_underflow, overflow=self.histogram_overflow,
        )

        # Shade the input values which will be clamped away.
        in_low_x = self._marker_x("in_low")
        in_high_x = self._marker_x("in_high")
        painter.fillRect(QRectF(rect.left(), rect.top(), max(in_low_x - rect.left(), 0.0), rect.height()), QColor(8, 10, 12, 95))
        painter.fillRect(QRectF(in_high_x, rect.top(), max(rect.right() - in_high_x, 0.0), rect.height()), QColor(8, 10, 12, 95))
        self.draw_frame(painter, rect)

        marker_colours = {
            "in_low": QColor("#111318"),
            "in_mid": QColor("#8f96a1"),
            "in_high": QColor("#f4f5f7"),
            "out_low": QColor("#111318"),
            "out_high": QColor("#f4f5f7"),
        }
        for name in ("in_low", "in_mid", "in_high"):
            x = self._marker_x(name)
            active = name == self.selected_marker
            hovered = name == self.hovered_marker
            painter.setPen(QPen(QColor(PALETTE.selected if active else PALETTE.hover if hovered else "#e3e6eb"), 2.0 if active else 1.0))
            painter.setBrush(marker_colours[name])
            painter.drawPolygon(self.triangle(x, rect.top() - 2.0, upward=True, size=7.0))
        for name in ("out_low", "out_high"):
            x = self._marker_x(name)
            active = name == self.selected_marker
            hovered = name == self.hovered_marker
            painter.setPen(QPen(QColor(PALETTE.selected if active else PALETTE.hover if hovered else "#e3e6eb"), 2.0 if active else 1.0))
            painter.setBrush(marker_colours[name])
            painter.drawPolygon(self.triangle(x, rect.bottom() + 2.0, upward=False, size=7.0))

        painter.setPen(QColor("#89919c"))
        painter.drawText(QPointF(rect.left(), rect.bottom() + 28.0), "0")
        painter.drawText(QPointF(rect.right() - 8.0, rect.bottom() + 28.0), "1")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._dragged = self._marker_at(event.position())
            if self._dragged is not None:
                self.selected_marker = self._dragged
                self.begin_interaction()
                self._apply_drag(self._dragged, event.position().x())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragged is not None:
            self._apply_drag(self._dragged, event.position().x())
            event.accept()
            return
        marker = self._marker_at(event.position())
        if marker != self.hovered_marker:
            self.hovered_marker = marker
            self.update()
        self.setCursor(Qt.CursorShape.SizeHorCursor if marker else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragged is not None:
            self._dragged = None
            self.end_interaction()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def can_reset(self) -> bool:
        return True

    def reset_to_default(self) -> None:
        self.values.update({
            "in_low": 0.0,
            "in_high": 1.0,
            "in_mid": 0.5,
            "out_low": 0.0,
            "out_high": 1.0,
            "intermediary_clamp": True,
        })
        self.selected_marker = "in_mid"
        self.update()
        self.queue_edited_value(dict(self.values), immediate=True)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right) and self.selected_marker is not None:
            step = self.keyboard_step(event)
            direction = -1.0 if event.key() == Qt.Key.Key_Left else 1.0
            current_x = self._marker_x(self.selected_marker)
            rect = self._plot_rect()
            self._apply_drag(self.selected_marker, current_x + direction * step * rect.width())
            event.accept()
            return
        super().keyPressEvent(event)


class LevelsControl(QWidget):
    """Histogram/sliders editor for the Levels node."""

    valuesChanged = Signal(object)
    autoLevelRequested = Signal(str)
    channelChanged = Signal(str)
    invertRequested = Signal()
    socketToggled = Signal(str, bool)
    viewModeChanged = Signal(str)
    editStarted = Signal()
    editFinished = Signal()

    PARAMETER_NAMES = ("in_low", "in_high", "in_mid", "out_low", "out_high")

    def __init__(
        self,
        specs: tuple[ParameterSpec, ...],
        values: dict[str, object],
        data_kind: str,
        exposed_inputs: set[str],
        *,
        channel: str = "Luminance",
        view_mode: str = "histogram",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.specs = {spec.name: spec for spec in specs}
        self.values = dict(values)
        self.number_controls: dict[str, NumberControl] = {}
        self.view_mode = view_mode

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        self.channel = QComboBox()
        channels = ["Luminance"]
        if data_kind in ("color", "vector"):
            channels += ["Red", "Green", "Blue", "Alpha"]
        self.channel.addItems(channels)
        self.channel.setCurrentText(channel if channel in channels else "Luminance")
        self.channel.currentTextChanged.connect(self.channelChanged.emit)
        self.channel.setToolTip("Choose which input channel is displayed and used by the one-shot Auto Level action.")
        toolbar.addWidget(self.channel, 1)

        self.auto_button = QPushButton("Auto Level")
        self.auto_button.setToolTip("Set Level In Low/High once from the current input histogram.")
        self.auto_button.clicked.connect(lambda: self.autoLevelRequested.emit(self.channel.currentText()))
        self.auto_button.setEnabled(False)
        toolbar.addWidget(self.auto_button)

        invert = QPushButton("Invert")
        invert.setToolTip("Swap Level Out Low and Level Out High.")
        invert.clicked.connect(self.invertRequested.emit)
        toolbar.addWidget(invert)

        self.reset_button = QPushButton("Reset")
        self.reset_button.setToolTip("Restore neutral Levels values.")
        self.reset_button.clicked.connect(self._reset_values)
        toolbar.addWidget(self.reset_button)

        self.toggle = QPushButton()
        self.toggle.clicked.connect(self._toggle_view)
        toolbar.addWidget(self.toggle)
        layout.addLayout(toolbar)

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.histogram = LevelsHistogramWidget(self.values)
        self.histogram.levelsChanged.connect(self._histogram_changed)
        self.histogram.interactionStarted.connect(self.editStarted.emit)
        self.histogram.interactionFinished.connect(self.editFinished.emit)
        self.stack.addWidget(self.histogram)

        sliders = QWidget()
        slider_form = QFormLayout(sliders)
        slider_form.setContentsMargins(0, 0, 0, 0)
        slider_form.setHorizontalSpacing(10)
        slider_form.setVerticalSpacing(9)
        for name in self.PARAMETER_NAMES:
            spec = self.specs[name]
            control = NumberControl(spec, self.values.get(name, spec.default), lambda value, n=name: self._number_changed(n, value))
            self.number_controls[name] = control
            row = QWidget(sliders)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(5)
            row_layout.addWidget(control, 1)
            socket = QToolButton(row)
            socket.setText("◇")
            socket.setCheckable(True)
            socket.setChecked(name in exposed_inputs)
            socket.setToolTip("Expose this value as a scalar animation input socket")
            socket.toggled.connect(lambda checked, n=name: self.socketToggled.emit(n, checked))
            row_layout.addWidget(socket)
            slider_form.addRow(spec.label, row)
        self.stack.addWidget(sliders)
        layout.addWidget(self.stack)

        clamp_row = QHBoxLayout()
        clamp_row.addWidget(QLabel("Intermediary Clamp"))
        self.clamp = QComboBox()
        self.clamp.addItems(("Clamp", "Passthrough"))
        self.clamp.setCurrentText("Clamp" if bool(self.values.get("intermediary_clamp", True)) else "Passthrough")
        self.clamp.setToolTip("Clamp the transformed input to 0–1 before applying Level Out Low/High.")
        self.clamp.currentTextChanged.connect(self._clamp_changed)
        clamp_row.addWidget(self.clamp, 1)
        layout.addLayout(clamp_row)

        hint = QLabel("Top handles: input low, midpoint and high. Bottom handles: output low and high.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self._apply_view_mode()

    def _reset_values(self) -> None:
        self.values.update({
            "in_low": 0.0,
            "in_high": 1.0,
            "in_mid": 0.5,
            "out_low": 0.0,
            "out_high": 1.0,
            "intermediary_clamp": True,
        })
        self._emit_values()
        self.clamp.blockSignals(True)
        self.clamp.setCurrentText("Clamp")
        self.clamp.blockSignals(False)

    def _toggle_view(self) -> None:
        self.view_mode = "sliders" if self.view_mode == "histogram" else "histogram"
        self._apply_view_mode()
        self.viewModeChanged.emit(self.view_mode)

    def _apply_view_mode(self) -> None:
        histogram = self.view_mode == "histogram"
        self.stack.setCurrentIndex(0 if histogram else 1)
        self.toggle.setText("Sliders" if histogram else "Histogram")
        self.toggle.setToolTip("Switch to precise value sliders" if histogram else "Switch to the interactive histogram")

    def _normalise_input_values(self) -> None:
        low = min(max(float(self.values.get("in_low", 0.0)), 0.0), 0.999)
        high = min(max(float(self.values.get("in_high", 1.0)), low + 0.001), 1.0)
        mid = min(max(float(self.values.get("in_mid", 0.5)), 0.001), 0.999)
        self.values.update({"in_low": low, "in_high": high, "in_mid": mid})

    def _emit_values(self) -> None:
        self._normalise_input_values()
        self._sync_controls()
        self.valuesChanged.emit(dict(self.values))

    def _number_changed(self, name: str, value: float) -> None:
        self.values[name] = float(value)
        self._emit_values()

    def _histogram_changed(self, values: dict[str, object]) -> None:
        self.values.update(values)
        self._emit_values()
        self.clamp.blockSignals(True)
        self.clamp.setCurrentText("Clamp" if bool(self.values.get("intermediary_clamp", True)) else "Passthrough")
        self.clamp.blockSignals(False)

    def _clamp_changed(self, text: str) -> None:
        self.values["intermediary_clamp"] = text == "Clamp"
        self.valuesChanged.emit(dict(self.values))

    def _sync_controls(self) -> None:
        self.histogram.set_values(self.values)
        for name, control in self.number_controls.items():
            control.set_value(self.values.get(name, self.specs[name].default))

    def set_values(self, values: dict[str, object]) -> None:
        self.values.update(values)
        self._normalise_input_values()
        self._sync_controls()
        self.clamp.blockSignals(True)
        self.clamp.setCurrentText("Clamp" if bool(self.values.get("intermediary_clamp", True)) else "Passthrough")
        self.clamp.blockSignals(False)

    def set_histogram(
        self,
        histogram: np.ndarray | None,
        *,
        ready: bool,
        message: str = "",
        underflow: int = 0,
        overflow: int = 0,
    ) -> None:
        self.histogram.set_histogram(
            histogram, message, underflow=underflow, overflow=overflow
        )
        self.auto_button.setEnabled(bool(ready))


class AdjustmentHistogramWidget(VisualEditorCanvas):
    """Interactive histogram canvas shared by Range, Shift, Scan and Select.

    The actual node operations remain separate.  This editor only translates
    their visible guide handles into each node's own parameters.
    """

    valuesChanged = Signal(object)
    selectionChanged = Signal(int)

    def __init__(self, mode: str, values: dict[str, object], parent=None) -> None:
        super().__init__(editor_height=230, debounce_ms=38, parent=parent)
        self.mode = str(mode)
        self.values = dict(values)
        self.histogram = np.zeros(HISTOGRAM_INTERNAL_BINS, dtype=np.float64)
        self.histogram_underflow = 0
        self.histogram_overflow = 0
        self.status_text = "Evaluating input histogram…"
        self.selected_guide = 0
        self.hovered_guide = -1
        self._dragging = False
        self.valueEdited.connect(self.valuesChanged.emit)
        self.setToolTip(
            "Drag the histogram guides directly. Left/Right nudges the selected guide; "
            "hold Shift for fine movement."
        )

    def set_values(self, values: dict[str, object]) -> None:
        self.values.update(values)
        self.update()

    def set_histogram(
        self,
        histogram: np.ndarray | None,
        message: str = "",
        *,
        underflow: int = 0,
        overflow: int = 0,
    ) -> None:
        self.histogram = self.normalise_histogram(histogram)
        self.histogram_underflow = max(int(underflow), 0)
        self.histogram_overflow = max(int(overflow), 0)
        self.status_text = str(message)
        self.update()

    def _plot_rect(self) -> QRectF:
        return QRectF(18.0, 18.0, max(float(self.width()) - 36.0, 1.0), max(float(self.height()) - 56.0, 1.0))

    def _x(self, value: float) -> float:
        rect = self._plot_rect()
        return rect.left() + min(max(float(value), 0.0), 1.0) * rect.width()

    def _value_from_x(self, x: float) -> float:
        rect = self._plot_rect()
        return min(max((float(x) - rect.left()) / max(rect.width(), 1.0), 0.0), 1.0)

    def _guides(self) -> tuple[list[float], tuple[float, float] | None, str]:
        if self.mode == "range":
            amount = min(max(float(self.values.get("range", 1.0)), 0.0), 1.0)
            position = min(max(float(self.values.get("position", 0.5)), 0.0), 1.0)
            low = (1.0 - amount) * position
            high = low + amount
            return [low, high], (low, high), "Output range"
        if self.mode == "shift":
            position = float(self.values.get("position", 0.0)) % 1.0
            return [position], None, "Circular shift"
        position = min(max(float(self.values.get("position", 0.5)), 0.0), 1.0)
        contrast = min(max(float(self.values.get("contrast", 0.5)), 0.0), 1.0)
        if self.mode == "select":
            selected_range = min(max(float(self.values.get("range", 0.25)), 0.0), 1.0)
            half = selected_range * 0.5
            low = max(position - half, 0.0)
            high = min(position + half, 1.0)
            return [low, position, high], (low, high), "Selected value range"
        low = 1.0 - position
        high = min(low + max(1.0 - contrast, 1e-6), 1.0)
        return [low, high], (low, high), "Scan transition"

    def _guide_at(self, point: QPointF) -> int:
        rect = self._plot_rect()
        if point.y() < rect.top() - 15.0 or point.y() > rect.bottom() + 8.0:
            return -1
        guides, _active_range, _label = self._guides()
        best = -1
        distance = 14.0
        for index, guide in enumerate(guides):
            candidate = abs(point.x() - self._x(guide))
            if candidate <= distance:
                distance = candidate
                best = index
        return best

    def _publish(self, *, immediate: bool | None = None) -> None:
        if immediate is None:
            immediate = not self.interaction_active
        self.update()
        self.queue_edited_value(dict(self.values), immediate=immediate)

    def _apply_guide(self, index: int, value: float, *, immediate: bool | None = None) -> None:
        value = min(max(float(value), 0.0), 1.0)
        guides, _active_range, _label = self._guides()
        if not guides:
            return
        index = min(max(int(index), 0), len(guides) - 1)
        if self.mode == "shift":
            self.values["position"] = value
        elif self.mode == "range":
            low, high = guides[0], guides[1]
            if index == 0:
                low = min(value, high - 0.001)
            else:
                high = max(value, low + 0.001)
            amount = min(max(high - low, 0.0), 1.0)
            unused = max(1.0 - amount, 0.0)
            position = 0.5 if unused <= 1e-9 else min(max(low / unused, 0.0), 1.0)
            self.values.update({"range": amount, "position": position})
        elif self.mode == "select":
            position = min(max(float(self.values.get("position", 0.5)), 0.0), 1.0)
            if index == 1:
                half = min(max(float(self.values.get("range", 0.25)), 0.0), 1.0) * 0.5
                self.values["position"] = min(max(value, half), 1.0 - half) if half <= 0.5 else 0.5
            else:
                self.values["range"] = min(max(abs(value - position) * 2.0, 0.0), 1.0)
        else:
            low, high = guides[0], guides[1]
            if index == 0:
                low = min(value, high - 0.001)
                self.values["position"] = 1.0 - low
            else:
                high = max(value, low + 0.001)
                self.values["contrast"] = min(max(1.0 - (high - low), 0.0), 1.0)
        self.selected_guide = index
        self._publish(immediate=immediate)
        self.selectionChanged.emit(index)

    def can_reset(self) -> bool:
        return True

    def reset_to_default(self) -> None:
        if self.mode == "range":
            self.values.update({"range": 1.0, "position": 0.5})
        elif self.mode == "shift":
            self.values.update({"position": 0.0})
        elif self.mode == "select":
            self.values.update({"position": 0.5, "range": 0.25, "contrast": 0.5})
        else:
            self.values.update({"position": 0.5, "contrast": 0.5})
        self.selected_guide = 0
        self._publish(immediate=True)
        self.selectionChanged.emit(0)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self._plot_rect()
        self.draw_editor_background(painter, rect, neutral_ramp=True)
        self.draw_histogram(
            painter, rect, self.histogram, status_text=self.status_text,
            underflow=self.histogram_underflow, overflow=self.histogram_overflow,
        )

        guides, active_range, label = self._guides()
        if active_range is not None:
            left = self._x(active_range[0])
            right = self._x(active_range[1])
            painter.fillRect(QRectF(rect.left(), rect.top(), max(left - rect.left(), 0.0), rect.height()), QColor(8, 10, 12, 90))
            painter.fillRect(QRectF(right, rect.top(), max(rect.right() - right, 0.0), rect.height()), QColor(8, 10, 12, 90))
        self.draw_frame(painter, rect)

        for index, value in enumerate(guides):
            x = self._x(value)
            selected = index == self.selected_guide
            hovered = index == self.hovered_guide
            border = QColor(PALETTE.selected if selected else PALETTE.hover if hovered else "#e3e6eb")
            painter.setPen(QPen(border, 2.0 if selected else 1.0))
            painter.setBrush(QColor("#f4f5f7") if index else QColor("#111318"))
            painter.drawPolygon(self.triangle(x, rect.top() - 2.0, upward=True, size=7.0))
            painter.setPen(QPen(QColor(PALETTE.curve), 1.0, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(x, rect.top() + 11.0), QPointF(x, rect.bottom()))

        painter.setPen(QColor(PALETTE.text))
        painter.drawText(QPointF(rect.left(), rect.bottom() + 28.0), "0")
        painter.drawText(QPointF(rect.right() - 8.0, rect.bottom() + 28.0), "1")
        painter.drawText(QRectF(rect.left(), rect.bottom() + 12.0, rect.width(), 18.0), Qt.AlignmentFlag.AlignCenter, label)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            guide = self._guide_at(event.position())
            if guide >= 0:
                self.selected_guide = guide
                self._dragging = True
                self.begin_interaction()
                self._apply_guide(guide, self._value_from_x(event.position().x()), immediate=False)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._apply_guide(self.selected_guide, self._value_from_x(event.position().x()), immediate=False)
            event.accept()
            return
        hovered = self._guide_at(event.position())
        if hovered != self.hovered_guide:
            self.hovered_guide = hovered
            self.update()
        self.setCursor(Qt.CursorShape.SizeHorCursor if hovered >= 0 else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.end_interaction()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            guides, _active, _label = self._guides()
            if guides:
                index = min(max(self.selected_guide, 0), len(guides) - 1)
                direction = -1.0 if event.key() == Qt.Key.Key_Left else 1.0
                self._apply_guide(index, guides[index] + direction * self.keyboard_step(event))
                event.accept()
                return
        super().keyPressEvent(event)


class HistogramAdjustmentControl(QWidget):
    """Live histogram plus precise controls for Range, Shift and Scan."""

    valuesChanged = Signal(object)
    socketToggled = Signal(str, bool)
    editStarted = Signal()
    editFinished = Signal()

    def __init__(
        self,
        mode: str,
        specs: tuple[ParameterSpec, ...],
        values: dict[str, object],
        exposed_inputs: set[str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.mode = str(mode)
        self.specs = {spec.name: spec for spec in specs}
        self.values = dict(values)
        self.number_controls: dict[str, NumberControl] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(5)
        heading = QLabel("Input Histogram")
        heading.setObjectName("muted")
        self.reset_button = QPushButton("Reset")
        self.reset_button.setToolTip("Restore this histogram adjustment's neutral defaults.")
        toolbar.addWidget(heading, 1)
        toolbar.addWidget(self.reset_button)
        layout.addLayout(toolbar)

        self.histogram = AdjustmentHistogramWidget(self.mode, self.values, self)
        layout.addWidget(self.histogram)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(9)
        for spec in specs:
            control = NumberControl(spec, self.values.get(spec.name, spec.default), lambda value, name=spec.name: self._number_changed(name, value))
            self.number_controls[spec.name] = control
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(5)
            row_layout.addWidget(control, 1)
            if spec.animatable:
                socket = QToolButton()
                socket.setText("◇")
                socket.setCheckable(True)
                socket.setChecked(spec.name in exposed_inputs)
                socket.setToolTip("Expose this value as a scalar animation input socket")
                socket.toggled.connect(lambda checked, name=spec.name: self.socketToggled.emit(name, checked))
                row_layout.addWidget(socket)
            form.addRow(spec.label, row)
        layout.addLayout(form)

        hints = {
            "range": "Drag either range edge, or use Range and Position precisely below.",
            "shift": "Drag the guide to shift values; values passing white wrap to black.",
            "scan": "Drag the lower/upper transition guides, or edit Position and Contrast precisely.",
            "select": "Drag the centre or either range edge; use Contrast below to tighten the falloff.",
        }
        hint = QLabel(hints.get(self.mode, ""))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.histogram.valuesChanged.connect(self._histogram_changed)
        self.histogram.interactionStarted.connect(self.editStarted.emit)
        self.histogram.interactionFinished.connect(self.editFinished.emit)
        self.reset_button.clicked.connect(lambda _checked=False: self.histogram.reset_to_default())

    def _number_changed(self, name: str, value: float) -> None:
        spec = self.specs[name]
        self.values[name] = int(round(value)) if spec.kind == "int" else float(value)
        self.histogram.set_values(self.values)
        self.valuesChanged.emit(dict(self.values))

    def _histogram_changed(self, values: dict[str, object]) -> None:
        self.values.update(values)
        for name, control in self.number_controls.items():
            control.set_value(self.values.get(name, self.specs[name].default))
        self.valuesChanged.emit(dict(self.values))

    def set_values(self, values: dict[str, object]) -> None:
        self.values.update(values)
        self.histogram.set_values(self.values)
        for name, control in self.number_controls.items():
            control.set_value(self.values.get(name, self.specs[name].default))

    def set_histogram(
        self,
        histogram: np.ndarray | None,
        message: str = "",
        *,
        underflow: int = 0,
        overflow: int = 0,
    ) -> None:
        self.histogram.set_histogram(
            histogram, message, underflow=underflow, overflow=overflow
        )


class GraphAssetParameterDialog(QDialog):
    """Edit the public presentation of one exposed graph-asset parameter."""

    def __init__(
        self, *, name: str, description: str, group: str, order: int,
        published: bool = True, parent=None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Graph Asset Parameter")
        self.resize(430, 300)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(str(name), self)
        self.group_edit = QLineEdit(str(group), self)
        self.order_spin = QSpinBox(self)
        self.order_spin.setRange(0, 9999)
        self.order_spin.setValue(int(order))
        self.description_edit = QTextEdit(self)
        self.description_edit.setPlainText(str(description))
        self.description_edit.setPlaceholderText("Tooltip shown on Graph Instance nodes")
        self.description_edit.setMinimumHeight(100)
        form.addRow("Public name", self.name_edit)
        form.addRow("Parameter group", self.group_edit)
        form.addRow("Interface order", self.order_spin)
        form.addRow("Description", self.description_edit)
        self.published_check = QCheckBox("Publish on Graph Instance nodes", self)
        self.published_check.setChecked(bool(published))
        self.published_check.setToolTip(
            "When enabled, this unconnected exposed parameter appears in the Parameters panel "
            "of a nested Graph Instance. Internally connected parameters remain private."
        )
        form.addRow("Graph asset", self.published_check)
        layout.addLayout(form)
        hint = QLabel(
            "The hidden interface ID stays stable when these labels change, so existing instances keep their values.",
            self,
        )
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        layout.addWidget(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def metadata(self) -> dict[str, object]:
        return {
            "name": self.name_edit.text().strip(),
            "description": self.description_edit.toPlainText().strip(),
            "group": self.group_edit.text().strip(),
            "order": self.order_spin.value(),
            "published": self.published_check.isChecked(),
        }


class GraphPropertiesWidget(QWidget):
    """Contextual editor for document-level graph asset properties."""

    KIND_LABELS = {
        "grayscale": "Greyscale",
        "color": "Colour",
        "vector": "Vector / Normal",
        "scalar": "Signal",
        "material": "Material",
        "geometry": "Geometry",
        "any": "Any",
        "image_any": "Image",
    }

    def __init__(
        self,
        metadata: GraphAssetMetadata,
        *,
        display_name: str,
        source_path: str,
        interface: dict,
        on_change: Callable[[str, object], None],
        on_new_identity: Callable[[], None],
        portability: dict[str, int] | None = None,
        on_export_self_contained: Callable[[], object] | None = None,
        on_export_package: Callable[[], object] | None = None,
        on_capture_thumbnail_2d: Callable[[], object] | None = None,
        on_capture_thumbnail_3d: Callable[[], object] | None = None,
        on_import_thumbnail: Callable[[], object] | None = None,
        on_clear_thumbnail: Callable[[], object] | None = None,
        on_title_change: Callable[[str], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.metadata = metadata
        self.on_change = on_change
        self.on_new_identity = on_new_identity
        self.portability = dict(portability or {})
        self.on_export_self_contained = on_export_self_contained
        self.on_export_package = on_export_package
        self.on_capture_thumbnail_2d = on_capture_thumbnail_2d
        self.on_capture_thumbnail_3d = on_capture_thumbnail_3d
        self.on_import_thumbnail = on_import_thumbnail
        self.on_clear_thumbnail = on_clear_thumbnail
        self.on_title_change = on_title_change

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(5)

        graph = ParameterGroupWidget("Graph", expanded=True, parent=self)
        self.name_edit = QLineEdit(metadata.name, graph.body)
        self.name_edit.setPlaceholderText("Graph asset name")
        self.description_edit = QTextEdit(graph.body)
        self.description_edit.setPlainText(metadata.description)
        self.description_edit.setPlaceholderText("Describe what this graph creates and how it is intended to be used")
        self.description_edit.setMinimumHeight(90)
        self.category_edit = QLineEdit(metadata.category, graph.body)
        self.category_edit.setPlaceholderText("Graph Assets")
        self.tags_edit = QLineEdit(", ".join(metadata.tags), graph.body)
        self.tags_edit.setPlaceholderText("terrain, rock, stylised")
        self.author_edit = QLineEdit(metadata.author, graph.body)
        self.version_edit = QLineEdit(metadata.version, graph.body)
        self.version_edit.setPlaceholderText("1.0.0")
        graph.addRow("Name", self.name_edit)
        graph.addRow("Description", self.description_edit)
        graph.addRow("Category", self.category_edit)
        graph.addRow("Tags", self.tags_edit)
        graph.addRow("Author", self.author_edit)
        graph.addRow("Version", self.version_edit)
        outer.addWidget(graph)

        thumbnail_group = ParameterGroupWidget("Thumbnail", expanded=True, parent=self)
        self.thumbnail_label = QLabel(thumbnail_group.body)
        self.thumbnail_label.setFixedSize(220, 220)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setObjectName("assetThumbnail")
        preview_pixmap = thumbnail_pixmap(metadata.thumbnail_png, 220)
        if preview_pixmap.isNull():
            self.thumbnail_label.setText("No graph thumbnail\n\nCapture the current preview or import an image.")
        else:
            self.thumbnail_label.setPixmap(preview_pixmap)
        thumbnail_group.addRow(self.thumbnail_label)
        source_names = {"2d": "2D Preview", "3d": "3D Preview", "imported": "Imported image"}
        source_text = source_names.get(metadata.thumbnail_source, "None")
        self.thumbnail_source_label = QLabel(source_text, thumbnail_group.body)
        self.thumbnail_source_label.setObjectName("muted")
        thumbnail_group.addRow("Source", self.thumbnail_source_label)
        thumbnail_buttons = QWidget(thumbnail_group.body)
        thumbnail_buttons_layout = QHBoxLayout(thumbnail_buttons)
        thumbnail_buttons_layout.setContentsMargins(0, 0, 0, 0)
        thumbnail_buttons_layout.setSpacing(5)
        capture_2d = QPushButton("Capture 2D", thumbnail_buttons)
        capture_2d.setToolTip("Use the current 2D Output image as this graph asset's 256 × 256 thumbnail")
        capture_2d.setEnabled(self.on_capture_thumbnail_2d is not None)
        if self.on_capture_thumbnail_2d is not None:
            capture_2d.clicked.connect(lambda: self.on_capture_thumbnail_2d())
        capture_3d = QPushButton("Capture 3D", thumbnail_buttons)
        capture_3d.setToolTip("Use the current 3D Preview viewport as this graph asset's thumbnail")
        capture_3d.setEnabled(self.on_capture_thumbnail_3d is not None)
        if self.on_capture_thumbnail_3d is not None:
            capture_3d.clicked.connect(lambda: self.on_capture_thumbnail_3d())
        thumbnail_buttons_layout.addWidget(capture_2d)
        thumbnail_buttons_layout.addWidget(capture_3d)
        thumbnail_group.addRow(thumbnail_buttons)
        thumbnail_file_buttons = QWidget(thumbnail_group.body)
        thumbnail_file_layout = QHBoxLayout(thumbnail_file_buttons)
        thumbnail_file_layout.setContentsMargins(0, 0, 0, 0)
        thumbnail_file_layout.setSpacing(5)
        import_button = QPushButton("Import Image…", thumbnail_file_buttons)
        import_button.setEnabled(self.on_import_thumbnail is not None)
        if self.on_import_thumbnail is not None:
            import_button.clicked.connect(lambda: self.on_import_thumbnail())
        clear_button = QPushButton("Clear", thumbnail_file_buttons)
        clear_button.setEnabled(bool(metadata.thumbnail_png) and self.on_clear_thumbnail is not None)
        if self.on_clear_thumbnail is not None:
            clear_button.clicked.connect(lambda: self.on_clear_thumbnail())
        thumbnail_file_layout.addWidget(import_button)
        thumbnail_file_layout.addWidget(clear_button)
        thumbnail_group.addRow(thumbnail_file_buttons)
        thumbnail_help = QLabel(
            "The thumbnail is stored as a small PNG inside the .vfxgraph, so the library can display it without evaluating the asset.",
            thumbnail_group.body,
        )
        thumbnail_help.setWordWrap(True)
        thumbnail_help.setObjectName("muted")
        thumbnail_group.addRow(thumbnail_help)
        outer.addWidget(thumbnail_group)

        identity = ParameterGroupWidget("Asset Identity", expanded=False, parent=self)
        asset_id_row = QWidget(identity.body)
        asset_id_layout = QHBoxLayout(asset_id_row)
        asset_id_layout.setContentsMargins(0, 0, 0, 0)
        asset_id_layout.setSpacing(5)
        self.asset_id_label = QLabel(metadata.asset_id, asset_id_row)
        self.asset_id_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.asset_id_label.setWordWrap(True)
        regenerate = QToolButton(asset_id_row)
        regenerate.setText("New…")
        regenerate.setToolTip("Generate a new identity so this graph is treated as an unrelated asset")
        regenerate.clicked.connect(lambda: self.on_new_identity())
        asset_id_layout.addWidget(self.asset_id_label, 1)
        asset_id_layout.addWidget(regenerate)
        identity.addRow("Asset ID", asset_id_row)
        created = QLabel(metadata.created_with or "Unknown", identity.body)
        created.setObjectName("muted")
        identity.addRow("Created with", created)
        format_version = QLabel("VFX graph format 18", identity.body)
        format_version.setObjectName("muted")
        identity.addRow("Format", format_version)
        source = QLabel(source_path or "Not saved", identity.body)
        source.setWordWrap(True)
        source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        source.setToolTip(source_path)
        identity.addRow("Source file", source)
        status = QLabel("Saved graph" if source_path else "Unsaved graph", identity.body)
        status.setObjectName("muted")
        identity.addRow("State", status)
        outer.addWidget(identity)

        published = ParameterGroupWidget("Published Interface", expanded=True, parent=self)
        inputs = [entry for entry in interface.get("inputs", ()) if isinstance(entry, dict)]
        outputs = [entry for entry in interface.get("outputs", ()) if isinstance(entry, dict)]
        parameters = [entry for entry in interface.get("parameters", ()) if isinstance(entry, dict)]
        published.addRow("Graph Inputs", self._interface_label(inputs, empty="None", parent=published.body))
        published.addRow("Graph Outputs", self._interface_label(outputs, empty="None", parent=published.body, show_primary=True))
        published.addRow("Exposed Parameters", self._parameter_label(parameters, parent=published.body))
        primary = next((entry for entry in outputs if bool(entry.get("primary_preview"))), None)
        primary_label = QLabel(str(primary.get("name")) if primary else "None", published.body)
        primary_label.setObjectName("muted" if primary is None else "")
        published.addRow("Primary output", primary_label)
        warnings = list(interface.get("warnings", ()) or [])
        if not outputs:
            warnings.append("No connected Graph Output nodes. This graph cannot be used as a Graph Instance yet.")
        if warnings:
            warning = QLabel("\n".join(f"• {text}" for text in warnings), published.body)
            warning.setWordWrap(True)
            warning.setObjectName("warningText")
            published.addRow(warning)
        else:
            ready = QLabel("Interface ready for nested Graph Instances.", published.body)
            ready.setWordWrap(True)
            ready.setObjectName("muted")
            published.addRow(ready)
        outer.addWidget(published)

        portability_group = ParameterGroupWidget("Portability & Recovery", expanded=True, parent=self)
        linked_graphs = int(self.portability.get("linked_graphs", 0))
        embedded_graphs = int(self.portability.get("embedded_graphs", 0))
        cached_graphs = int(self.portability.get("cached_graphs", 0))
        external_images = int(self.portability.get("external_images", 0))
        embedded_images = int(self.portability.get("embedded_images", 0))
        graph_count = linked_graphs + embedded_graphs
        image_count = external_images + embedded_images
        portability_group.addRow("Nested graphs", QLabel(
            f"{graph_count} · {linked_graphs} linked · {embedded_graphs} embedded",
            portability_group.body,
        ))
        portability_group.addRow("Images", QLabel(
            f"{image_count} · {external_images} external · {embedded_images} embedded",
            portability_group.body,
        ))
        cache_label = QLabel(
            f"{cached_graphs} last-known-good revision{'s' if cached_graphs != 1 else ''} available",
            portability_group.body,
        )
        cache_label.setObjectName("muted")
        portability_group.addRow("Recovery cache", cache_label)
        explanation = QLabel(
            "A self-contained export embeds every reachable Graph Instance and Image Input into one portable .vfxgraph. "
            "It uses current open child revisions and can recover missing linked graphs from their last-known-good cache.",
            portability_group.body,
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("muted")
        portability_group.addRow(explanation)
        export_button = QPushButton("Export Self-Contained Graph…", portability_group.body)
        export_button.setEnabled(self.on_export_self_contained is not None)
        if self.on_export_self_contained is not None:
            export_button.clicked.connect(lambda: self.on_export_self_contained())
        portability_group.addRow(export_button)
        package_button = QPushButton("Export VFX Package…", portability_group.body)
        package_button.setToolTip(
            "Create a validated .vfxpackage archive that can be opened, extracted or installed into another VFX Texture Lab library"
        )
        package_button.setEnabled(self.on_export_package is not None)
        if self.on_export_package is not None:
            package_button.clicked.connect(lambda: self.on_export_package())
        portability_group.addRow(package_button)
        outer.addWidget(portability_group)
        outer.addStretch(1)

        self.name_edit.editingFinished.connect(lambda: self._commit_text("name", self.name_edit.text()))
        self.category_edit.editingFinished.connect(lambda: self._commit_text("category", self.category_edit.text()))
        self.tags_edit.editingFinished.connect(self._commit_tags)
        self.author_edit.editingFinished.connect(lambda: self._commit_text("author", self.author_edit.text()))
        self.version_edit.editingFinished.connect(lambda: self._commit_text("version", self.version_edit.text()))
        self._description_timer = QTimer(self)
        self._description_timer.setSingleShot(True)
        self._description_timer.setInterval(300)
        self._description_timer.timeout.connect(
            lambda: self._commit_text("description", self.description_edit.toPlainText(), strip=False)
        )
        self.description_edit.textChanged.connect(self._description_timer.start)

    def _commit_text(self, field: str, value: str, *, strip: bool = True) -> None:
        text = str(value)
        if strip:
            text = text.strip()
        if field == "name" and not text:
            text = "Untitled Graph"
            self.name_edit.setText(text)
        elif field == "category" and not text:
            text = "Graph Assets"
            self.category_edit.setText(text)
        elif field == "version" and not text:
            text = "1.0.0"
            self.version_edit.setText(text)
        if getattr(self.metadata, field) == text:
            return
        setattr(self.metadata, field, text)
        self.on_change(field, text)
        if field == "name" and self.on_title_change is not None:
            self.on_title_change(text)

    def _commit_tags(self) -> None:
        values = [value.strip() for value in self.tags_edit.text().split(",") if value.strip()]
        seen: set[str] = set()
        tags: list[str] = []
        for value in values:
            key = value.casefold()
            if key not in seen:
                seen.add(key)
                tags.append(value)
        if self.metadata.tags == tags:
            return
        self.metadata.tags = tags
        self.tags_edit.setText(", ".join(tags))
        self.on_change("tags", tags)

    @classmethod
    def _interface_label(
        cls, entries: list[dict], *, empty: str, parent: QWidget, show_primary: bool = False
    ) -> QLabel:
        lines: list[str] = []
        for entry in entries:
            name = str(entry.get("name") or entry.get("port") or "Unnamed")
            kind = cls.KIND_LABELS.get(str(entry.get("kind", "any")), str(entry.get("kind", "Any")).title())
            suffix = " · Primary" if show_primary and bool(entry.get("primary_preview")) else ""
            lines.append(f"{name} — {kind}{suffix}")
        label = QLabel("\n".join(lines) if lines else empty, parent)
        label.setWordWrap(True)
        if not lines:
            label.setObjectName("muted")
        return label

    @staticmethod
    def _parameter_label(entries: list[dict], *, parent: QWidget) -> QLabel:
        lines = [
            f"{str(entry.get('name') or entry.get('parameter') or 'Unnamed')} — {str(entry.get('group') or 'Parameters')}"
            for entry in entries
        ]
        label = QLabel("\n".join(lines) if lines else "None", parent)
        label.setWordWrap(True)
        if not lines:
            label.setObjectName("muted")
        return label


class ParametersPanel(QWidget):
    saveGroupRequested = Signal(object)
    openUserLibraryRequested = Signal()
    textureSetQuickExportRequested = Signal(str, bool)
    geometryExportRequested = Signal(str, bool)
    exportTemplateEditRequested = Signal(str)
    interactiveEditStarted = Signal(str)
    interactiveEditFinished = Signal(str)
    histogramActivityChanged = Signal(bool, str)

    CURVE_NODES = {
        "filter.curve": "tone",
        "signal.curve": "animation",
    }

    HISTOGRAM_ADJUSTMENTS = {
        "filter.histogram_range": "range",
        "filter.histogram_shift": "shift",
        "filter.histogram_scan": "scan",
        "filter.histogram_select": "select",
    }

    def __init__(
        self,
        scene,
        parent=None,
        *,
        evaluator=None,
        document_provider: Callable[[], object] | None = None,
        animation_context_provider: Callable[[], dict] | None = None,
    ) -> None:
        super().__init__(parent)
        self.scene = scene
        self.evaluator = evaluator
        self.document_provider = document_provider
        self.animation_context_provider = animation_context_provider
        self.item: NodeItem | GroupFrameItem | None = None
        self._context_kind = "none"
        self._graph_context_uid: str | None = None
        self._external_widget: QWidget | None = None
        self._external_release: Callable[[QWidget], None] | None = None
        self._building = False
        self._levels_control: LevelsControl | None = None
        self._levels_histogram_stats: tuple[float, float] | None = None
        self._levels_channels: dict[str, str] = {}
        self._levels_views: dict[str, str] = {}
        self._levels_histogram_uid: str | None = None
        self._adjustment_histogram_control: HistogramAdjustmentControl | None = None
        self._adjustment_histogram_uid: str | None = None
        self._visual_edit_depth = 0
        self._visual_edit_node_uid: str | None = None
        self._histogram_interaction_depth = 0
        self._levels_histogram_request_key: tuple | None = None
        self._levels_histogram_completed_key: tuple | None = None
        self._adjustment_histogram_request_key: tuple | None = None
        self._adjustment_histogram_completed_key: tuple | None = None
        self._levels_histogram_cache: dict[tuple, tuple[np.ndarray, float, float, int, int]] = {}
        self._adjustment_histogram_cache: dict[tuple, tuple[np.ndarray, int, int]] = {}
        self._parameter_group_states: dict[tuple[str, str], bool] = {}

        self._levels_histogram_timer = QTimer(self)
        self._levels_histogram_timer.setSingleShot(True)
        self._levels_histogram_timer.setInterval(140)
        self._levels_histogram_timer.timeout.connect(self._request_levels_histogram)
        self._levels_histogram_controller = (
            AsyncEvaluationController(self.evaluator, self) if self.evaluator is not None else None
        )
        if self._levels_histogram_controller is not None:
            self._levels_histogram_controller.resultReady.connect(self._levels_histogram_ready)
            self._levels_histogram_controller.evaluationFailed.connect(self._levels_histogram_failed)
        self.scene.graphChanged.connect(self._schedule_levels_histogram)

        self._adjustment_histogram_timer = QTimer(self)
        self._adjustment_histogram_timer.setSingleShot(True)
        self._adjustment_histogram_timer.setInterval(140)
        self._adjustment_histogram_timer.timeout.connect(self._request_adjustment_histogram)
        self._adjustment_histogram_controller = (
            AsyncEvaluationController(self.evaluator, self) if self.evaluator is not None else None
        )
        if self._adjustment_histogram_controller is not None:
            self._adjustment_histogram_controller.resultReady.connect(self._adjustment_histogram_ready)
            self._adjustment_histogram_controller.evaluationFailed.connect(self._adjustment_histogram_failed)
        self.scene.graphChanged.connect(self._schedule_adjustment_histogram)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(7)

        self.title = QLabel("Nothing selected")
        self.title.setObjectName("sectionTitle")
        self.description = QLabel(
            "Single-click a node to edit its parameters. The preview remains locked to the last double-clicked node."
        )
        self.description.setObjectName("muted")
        self.description.setWordWrap(True)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        self.form.setContentsMargins(4, 8, 4, 8)
        self.form.setHorizontalSpacing(10)
        self.form.setVerticalSpacing(10)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.scroll.setWidget(self.form_host)

        outer.addWidget(self.title)
        outer.addWidget(self.description)
        outer.addWidget(self.scroll, 1)

    def set_node(self, item: NodeItem | GroupFrameItem | None) -> None:
        self.set_item(item)

    def set_scene(self, scene) -> None:
        if scene is self.scene:
            return
        try:
            self.scene.graphChanged.disconnect(self._schedule_levels_histogram)
        except (TypeError, RuntimeError):
            pass
        try:
            self.scene.graphChanged.disconnect(self._schedule_adjustment_histogram)
        except (TypeError, RuntimeError):
            pass
        if self._levels_histogram_controller is not None:
            self._levels_histogram_controller.cancel()
        if self._adjustment_histogram_controller is not None:
            self._adjustment_histogram_controller.cancel()
        self.scene = scene
        self.scene.graphChanged.connect(self._schedule_levels_histogram)
        self.scene.graphChanged.connect(self._schedule_adjustment_histogram)
        self._levels_histogram_cache.clear()
        self._adjustment_histogram_cache.clear()
        self.set_item(None)

    def _release_external_widget(self) -> None:
        widget = self._external_widget
        callback = self._external_release
        self._external_widget = None
        self._external_release = None
        if widget is None:
            return
        if callback is not None:
            callback(widget)
        else:
            widget.hide()
            widget.setParent(None)

    def show_external_widget(
        self,
        title: str,
        description: str,
        widget: QWidget,
        *,
        release_callback: Callable[[QWidget], None] | None = None,
    ) -> None:
        """Inspect a persistent non-node editor in the Inspector dock."""
        self.set_item(None)
        self.item = None
        self._building = True
        old_host = self.form_host
        old_host.hide()
        new_host = QWidget(self.scroll.viewport())
        new_host.hide()
        new_form = QFormLayout(new_host)
        new_form.setContentsMargins(4, 8, 4, 8)
        new_form.setHorizontalSpacing(10)
        new_form.setVerticalSpacing(10)
        new_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.form_host = new_host
        self.form = new_form
        try:
            self._context_kind = "external"
            self._graph_context_uid = None
            self.title.setText(str(title))
            self.description.setText(str(description))
            widget.setParent(new_host)
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            widget.show()
            new_form.addRow(widget)
            self._external_widget = widget
            self._external_release = release_callback
            detached = self.scroll.takeWidget()
            self.scroll.setWidget(new_host)
            self.scroll.verticalScrollBar().setValue(0)
            new_host.show()
            if detached is not None and detached is not new_host:
                detached.hide()
                detached.deleteLater()
        except Exception:
            self._external_widget = None
            self._external_release = None
            if release_callback is not None:
                release_callback(widget)
            else:
                widget.hide()
                widget.setParent(None)
            new_host.hide()
            new_host.deleteLater()
            self.form_host = old_host
            self.form = old_host.layout()
            old_host.show()
            raise
        finally:
            self._building = False

    def show_graph_properties(
        self,
        session_uid: str,
        metadata: GraphAssetMetadata,
        *,
        display_name: str,
        source_path: str,
        interface: dict,
        on_change: Callable[[str, object], None],
        on_new_identity: Callable[[], None],
        portability: dict[str, int] | None = None,
        on_export_self_contained: Callable[[], object] | None = None,
        on_export_package: Callable[[], object] | None = None,
        on_capture_thumbnail_2d: Callable[[], object] | None = None,
        on_capture_thumbnail_3d: Callable[[], object] | None = None,
        on_import_thumbnail: Callable[[], object] | None = None,
        on_clear_thumbnail: Callable[[], object] | None = None,
    ) -> None:
        widget = GraphPropertiesWidget(
            metadata,
            display_name=display_name,
            source_path=source_path,
            interface=interface,
            on_change=on_change,
            on_new_identity=on_new_identity,
            portability=portability,
            on_export_self_contained=on_export_self_contained,
            on_export_package=on_export_package,
            on_capture_thumbnail_2d=on_capture_thumbnail_2d,
            on_capture_thumbnail_3d=on_capture_thumbnail_3d,
            on_import_thumbnail=on_import_thumbnail,
            on_clear_thumbnail=on_clear_thumbnail,
            on_title_change=lambda value: self.title.setText(str(value)),
        )
        self.show_external_widget(
            metadata.name or display_name,
            "Graph properties, published interface and portable-project information for this document.",
            widget,
            release_callback=lambda target: target.deleteLater(),
        )
        self._context_kind = "graph"
        self._graph_context_uid = str(session_uid)

    def is_showing_graph(self, session_uid: str) -> bool:
        return self._context_kind == "graph" and self._graph_context_uid == str(session_uid)

    def set_item(self, item: NodeItem | GroupFrameItem | None) -> None:
        self._release_external_widget()
        self._finish_visual_edits()
        self.item = item
        self._context_kind = "node" if item is not None else "none"
        self._graph_context_uid = None
        self._levels_control = None
        self._levels_histogram_stats = None
        self._adjustment_histogram_control = None
        self._levels_histogram_request_key = None
        self._levels_histogram_completed_key = None
        self._adjustment_histogram_request_key = None
        self._adjustment_histogram_completed_key = None
        if self._levels_histogram_controller is not None:
            self._levels_histogram_controller.cancel()
        if self._adjustment_histogram_controller is not None:
            self._adjustment_histogram_controller.cancel()
        self.histogramActivityChanged.emit(False, "")
        self._levels_histogram_timer.stop()
        self._adjustment_histogram_timer.stop()
        self._building = True
        old_host = self.form_host
        old_host.hide()
        # Build a complete replacement while hidden, then swap it into the
        # scroll area atomically. Repeatedly removing visible QFormLayout rows
        # can briefly expose freshly-created child widgets as native top-level
        # windows on some X11/Qt combinations, producing a tiny application-icon
        # flash whenever selection changes.
        new_host = QWidget(self.scroll.viewport())
        new_host.hide()
        new_form = QFormLayout(new_host)
        new_form.setContentsMargins(4, 8, 4, 8)
        new_form.setHorizontalSpacing(10)
        new_form.setVerticalSpacing(10)
        new_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.form_host = new_host
        self.form = new_form
        try:
            if item is None:
                self.title.setText("Nothing selected")
                self.description.setText(
                    "Single-click a node or group to edit it. The 2D preview remains locked to the last double-clicked node."
                )
            elif isinstance(item, GroupFrameItem):
                self._build_group(item)
            else:
                self._build_node(item)
        except Exception:
            # Keep the previous parameter page usable if a custom or built-in
            # editor fails during construction.  The exception is re-raised so
            # development builds still report the underlying problem.
            new_host.hide()
            new_host.deleteLater()
            self.form_host = old_host
            self.form = old_host.layout()
            old_host.show()
            raise
        else:
            detached = self.scroll.takeWidget()
            self.scroll.setWidget(new_host)
            self.scroll.verticalScrollBar().setValue(0)
            new_host.show()
            if detached is not None and detached is not new_host:
                detached.hide()
                detached.deleteLater()
        finally:
            self._building = False

    def _section(self, text: str) -> None:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("separator")
        heading = QLabel(text)
        heading.setObjectName("sectionTitle")
        self.form.addRow(line)
        self.form.addRow(heading)

    @staticmethod
    def _is_base_parameter(spec: ParameterSpec) -> bool:
        return spec.name.strip().lower() in {"seed", "random_seed", "randomseed"}

    @staticmethod
    def _parameter_group_name(spec: ParameterSpec) -> str:
        if spec.group.strip():
            return spec.group.strip()
        name = spec.name.strip().lower()
        label = spec.label.strip().lower()
        combined = f"{name} {label}"
        if (
            name in {
                "scale", "scale_x", "scale_y", "rotation", "angle", "offset_x", "offset_y",
                "center_x", "center_y", "pivot_x", "pivot_y", "translate_x", "translate_y",
                "position_x", "position_y",
            }
            or name.startswith("transform_")
        ):
            return "Transform"
        if name in {"evolution", "loop_cycles", "loop_phase", "phase", "time_scale", "animation_speed"}:
            return "Animation"
        if (
            name in {"wrap", "tile", "boundary", "outside_uvs", "tile_preview", "tiling_mode"}
            or name.startswith("tiles_")
            or "tiling" in combined
            or "boundary" in combined
        ):
            return "Tiling / Boundaries"
        if (
            name == "quality"
            or "iterations" in name
            or "passes" in name
            or "samples" in name
            or "substeps" in name
            or "drainage" in name
            or name.startswith("preview_")
            or name.startswith("final_")
        ):
            return "Quality"
        if name in {"preview_output", "output", "invert", "normalise", "normalize", "clamp_output"} or name.endswith("_output"):
            return "Output"
        return "Parameters"

    @staticmethod
    def _parameter_group_sort_key(title: str, specs: list[ParameterSpec]) -> tuple[int, int, str]:
        preferred = {
            "Parameters": 20,
            "Transform": 30,
            "Animation": 40,
            "Tiling / Boundaries": 50,
            "Quality": 70,
            "Output": 80,
            "Advanced": 90,
        }
        explicit = min((int(spec.group_order) for spec in specs), default=100)
        return preferred.get(title, explicit), explicit, title.casefold()

    def _new_parameter_group(self, node: NodeItem, title: str, *, expanded: bool = True) -> ParameterGroupWidget:
        key = (node.definition.type_id, str(title))
        state = self._parameter_group_states.get(key, bool(expanded))
        group = ParameterGroupWidget(title, expanded=state, parent=self.form_host)
        group.header.toggled.connect(lambda checked, k=key: self._parameter_group_states.__setitem__(k, bool(checked)))
        return group

    @staticmethod
    def _spec_is_visible(node: NodeItem, spec: ParameterSpec) -> bool:
        for controller_name, allowed_values in spec.visible_when:
            controller = node.parameters.get(controller_name)
            if controller not in allowed_values:
                return False
        if node.definition.type_id == "input.image" and spec.name == "flip_y":
            selected = str(node.parameters.get("data_type", "Auto"))
            if selected == "Auto":
                return str(node.parameters.get("_detected_kind", "color")) == "vector"
            return selected == "Vector / Normal"
        return True

    def _add_spec_row(self, target, node: NodeItem, spec: ParameterSpec) -> None:
        value = node.parameters.get(spec.name, spec.default)
        callback = partial(self._node_parameter_changed, node, spec)
        parent_widget = target.body if isinstance(target, ParameterGroupWidget) else self.form_host
        control = self._control_for_spec(spec, value, callback, node=node, parent=parent_widget)
        control.setToolTip(spec.description)
        if spec.kind == "gradient":
            target.addRow(control)
            return
        is_angle = str(spec.editor).strip().lower() == "angle"
        if spec.animatable and spec.kind in ("float", "int"):
            row = QWidget(parent_widget)
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(5)
            if is_angle:
                # Angle controls span the form instead of inheriting the width
                # of the longest label in their group. This keeps every dial at
                # the same natural left-hand position even beside labels such as
                # "Rotation Random Range" in Tile Sampler.
                label = QLabel(spec.label, row)
                label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
                layout.addWidget(label)
            layout.addWidget(control, 1)
            socket = QToolButton(row)
            socket.setText("◇")
            socket.setCheckable(True)
            socket.setChecked(spec.name in node.exposed_parameter_inputs)
            socket.setToolTip("Expose this parameter as a scalar animation input socket")
            socket.toggled.connect(
                lambda checked, n=node, name=spec.name: self._set_parameter_socket(n, name, checked)
            )
            layout.addWidget(socket)
            if spec.graph_asset_publishable and spec.name in node.exposed_parameter_inputs:
                metadata = QToolButton(row)
                metadata.setText("…")
                metadata.setToolTip(
                    "Edit graph-asset publication, public name, tooltip, group and order"
                )
                metadata.clicked.connect(
                    lambda _checked=False, n=node, s=spec: self._edit_graph_asset_parameter(n, s)
                )
                layout.addWidget(metadata)
            if is_angle:
                target.addRow(row)
            else:
                target.addRow(spec.label, row)
        elif is_angle:
            row = QWidget(parent_widget)
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(5)
            label = QLabel(spec.label, row)
            label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            layout.addWidget(label)
            layout.addWidget(control, 1)
            target.addRow(row)
        else:
            target.addRow(spec.label, control)

    def _build_node(self, node: NodeItem) -> None:
        self.title.setText(node.definition.name)
        self.description.setText(node.definition.description or node.definition.category)

        if node.definition.type_id == "graph.instance":
            info = self._new_parameter_group(node, "Graph Asset", expanded=True)
            mode = QLabel(str(node.parameters.get("_asset_mode", "Linked")), info.body)
            mode.setObjectName("muted")
            info.addRow("Mode", mode)
            status = QLabel(str(node.parameters.get("_asset_status", "Linked")), info.body)
            status.setObjectName("muted")
            info.addRow("Status", status)
            source_text = str(node.parameters.get("_asset_path", "")).strip()
            source = QLabel(source_text or "Embedded in this project", info.body)
            source.setWordWrap(True)
            source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            source.setToolTip(source_text)
            info.addRow("Source", source)
            interface = node.parameters.get("_asset_interface", {})
            outputs = ", ".join(str(entry.get("name", "Output")) for entry in interface.get("outputs", ()) if isinstance(entry, dict))
            output_label = QLabel(outputs or "No published outputs", info.body)
            output_label.setWordWrap(True)
            info.addRow("Outputs", output_label)
            cached = node.parameters.get("_asset_cached_graph")
            cached_state = QLabel(
                "Available · can restore or embed" if isinstance(cached, dict) else "Unavailable",
                info.body,
            )
            cached_state.setObjectName("muted")
            info.addRow("Recovery cache", cached_state)
            original_name = str(node.parameters.get("_asset_original_name", "") or "").strip()
            if original_name:
                original = QLabel(original_name, info.body)
                original.setObjectName("muted")
                info.addRow("Original source", original)
            hint = QLabel("Right-click the node to open, reload, embed, relink matching instances or restore its cached revision.", info.body)
            hint.setWordWrap(True)
            hint.setObjectName("muted")
            info.addRow(hint)
            self.form.addRow(info)

        has_image_output = any(is_image_kind(node.definition.output_kind(name)) for name in node.definition.output_names)
        base_specs = [
            spec for spec in node.definition.parameters
            if self._is_base_parameter(spec) and self._spec_is_visible(node, spec)
        ]
        if has_image_output or base_specs:
            base = self._new_parameter_group(node, "Base Settings", expanded=True)
            for spec in base_specs:
                self._add_spec_row(base, node, spec)

            if has_image_output:
                kind_names = {"grayscale": "Greyscale", "color": "Colour", "vector": "Vector / Normal"}
                kind = QLabel(kind_names.get(node.resolved_image_kind, node.resolved_image_kind.title()), base.body)
                kind.setObjectName("muted")
                base.addRow("Data type", kind)

                precision = QComboBox(base.body)
                if node.definition.type_id in {"filter.flood_fill", "filter.flood_fill_to_index"}:
                    precision.addItem("32-bit float")
                    precision.setCurrentText("32-bit float")
                    precision.setEnabled(False)
                    precision.setToolTip(
                        "Flood Fill metadata and ordered indices require exact 32-bit float storage."
                    )
                else:
                    precision.addItems(("Inherit", "8-bit", "16-bit", "32-bit float"))
                    precision.setCurrentText(str(node.parameters.get("_precision", "Inherit")))
                    precision.setToolTip(
                        "Inherit uses the highest connected input precision. Generators use the document default (16-bit unless changed)."
                    )
                    precision.currentTextChanged.connect(
                        lambda value, n=node: self.scene.change_node_parameter(n, "_precision", value, label="Change Output Precision")
                    )
                base.addRow("Output precision", precision)
            self.form.addRow(base)

        if node.definition.type_id == "input.image":
            source_group = self._new_parameter_group(node, "Source Information", expanded=True)
            size = node.parameters.get("_source_size", [])
            size_text = f"{size[0]} × {size[1]}" if isinstance(size, list) and len(size) == 2 else "Unknown"
            detected_kind = str(node.parameters.get("_detected_kind", "unknown"))
            detected = {"color": "Colour", "grayscale": "Greyscale", "vector": "Vector / Normal"}.get(
                detected_kind, detected_kind.replace("color", "colour").title()
            )
            mode = str(node.parameters.get("_source_mode", "Unknown"))
            source_precision = str(node.parameters.get("_source_precision", "Unknown"))
            channels = str(node.parameters.get("_source_channels", "?") )
            normal_reason = str(node.parameters.get("_normal_detection", "")).strip()
            detection_text = f"detected {detected}"
            if normal_reason:
                detection_text += f" ({normal_reason})"
            source = QLabel(f"{size_text} · {mode} · {channels} channel(s) · {source_precision} · {detection_text}")
            source.setObjectName("muted")
            source.setWordWrap(True)
            source_group.addRow("Detected source", source)
            if node.parameters.get("_source_error"):
                error = QLabel(str(node.parameters["_source_error"]))
                error.setStyleSheet("color:#ef7785;")
                error.setWordWrap(True)
                source_group.addRow("Source error", error)
            self.form.addRow(source_group)

        if node.definition.type_id == "input.canvas":
            canvas_group = self._new_parameter_group(node, "Canvas", expanded=True)
            width = int(node.parameters.get("canvas_width", 1024) or 1024)
            height = int(node.parameters.get("canvas_height", 1024) or 1024)
            summary = QLabel(
                f"Native canvas: {width} × {height}.\nPaint directly in the Canvas Editor dock. Copying this node duplicates its embedded image data."
            )
            summary.setObjectName("muted")
            summary.setWordWrap(True)
            canvas_group.addRow("Summary", summary)
            button = QPushButton("Open Canvas Editor", canvas_group.body)
            button.clicked.connect(lambda: self._open_canvas_editor())
            canvas_group.addRow("Editor", button)
            self.form.addRow(canvas_group)
            return

        if node.definition.type_id == "filter.levels":
            group = self._new_parameter_group(node, "Levels", expanded=True)
            self.form.addRow(group)
            self._build_levels_node(node, group)
            return
        if node.definition.type_id in self.HISTOGRAM_ADJUSTMENTS:
            group = self._new_parameter_group(node, node.definition.name, expanded=True)
            self.form.addRow(group)
            self._build_histogram_adjustment_node(node, group)
            return
        if node.definition.type_id in self.CURVE_NODES:
            group = self._new_parameter_group(node, node.definition.name, expanded=True)
            self.form.addRow(group)
            self._build_curve_node(node, group)
            return

        remaining = [
            spec for spec in node.definition.parameters
            if not self._is_base_parameter(spec) and self._spec_is_visible(node, spec)
        ]
        if not remaining:
            if not has_image_output and not base_specs:
                label = QLabel("This node has no editable parameters.")
                label.setObjectName("muted")
                self.form.addRow(label)
            return

        grouped: dict[str, list[ParameterSpec]] = {}
        for spec in remaining:
            grouped.setdefault(self._parameter_group_name(spec), []).append(spec)
        for title, specs in sorted(grouped.items(), key=lambda item: self._parameter_group_sort_key(item[0], item[1])):
            group = self._new_parameter_group(node, title, expanded=title not in {"Quality", "Advanced"})
            for spec in specs:
                self._add_spec_row(group, node, spec)
            self.form.addRow(group)

        if node.definition.type_id == "output.texture_set":
            template = effective_export_template(node.parameters)
            template_group = self._new_parameter_group(node, "Template Editor", expanded=True)
            summary = QLabel(template_summary(template), template_group.body)
            summary.setObjectName("muted")
            summary.setWordWrap(True)
            template_group.addRow("Current layout", summary)

            customise = QPushButton(
                "Edit Custom Template…" if str(node.parameters.get("export_preset", "")) == CUSTOM_TEMPLATE_NAME
                else "Customise Template…",
                template_group.body,
            )
            customise.setToolTip(
                "Edit the exact output files, formats, bit depths and R/G/B/A source assignments. "
                "Saving creates a graph-local Custom Template without changing the built-in presets."
            )
            customise.clicked.connect(
                lambda _checked=False, uid=node.uid: self.exportTemplateEditRequested.emit(uid)
            )
            template_group.addRow("Channel packing", customise)
            self.form.addRow(template_group)

        if node.definition.type_id in {"output.image", "output.texture_set"}:
            quick_group = self._new_parameter_group(node, "Quick Export", expanded=True)
            directory = str(node.parameters.get("_quick_export_directory", "")).strip()
            configured = bool(node.parameters.get("_quick_export_configured", False) and directory)
            destination = QLabel(directory if configured else "Not configured — the first Quick Export opens Export Outputs.", quick_group.body)
            destination.setObjectName("muted")
            destination.setWordWrap(True)
            quick_group.addRow("Destination", destination)
            profile_name = str(node.parameters.get("_quick_export_profile_name", "")).strip()
            if configured:
                profile = QLabel(profile_name or "Current Output Settings", quick_group.body)
                profile.setObjectName("muted")
                profile.setWordWrap(True)
                quick_group.addRow("Profile set", profile)

            open_folder = QCheckBox("Open folder when complete", quick_group.body)
            open_folder.setChecked(bool(node.parameters.get("_quick_export_open_folder", False)))
            open_folder.toggled.connect(
                lambda checked, n=node: self.scene.change_node_parameter(
                    n,
                    "_quick_export_open_folder",
                    bool(checked),
                    label="Change Quick Export Folder Behaviour",
                )
            )
            quick_group.addRow("After export", open_folder)

            buttons = QWidget(quick_group.body)
            button_layout = QHBoxLayout(buttons)
            button_layout.setContentsMargins(0, 0, 0, 0)
            button_layout.setSpacing(6)
            quick = QPushButton("Quick Export", buttons)
            output_kind = "Texture Set Output" if node.definition.type_id == "output.texture_set" else "Single Image Output"
            quick.setToolTip(
                f"Export this {output_kind} immediately using its remembered profile set and destination. The first use opens Export Outputs for setup."
            )
            configure = QPushButton("Configure Export…", buttons)
            quick.clicked.connect(
                lambda _checked=False, uid=node.uid: self.textureSetQuickExportRequested.emit(uid, False)
            )
            configure.clicked.connect(
                lambda _checked=False, uid=node.uid: self.textureSetQuickExportRequested.emit(uid, True)
            )
            button_layout.addWidget(quick)
            button_layout.addWidget(configure)
            quick_group.addRow(buttons)
            self.form.addRow(quick_group)

        if node.definition.type_id == "output.geometry":
            quick_group = self._new_parameter_group(node, "Mesh Export", expanded=True)
            destination = str(node.parameters.get("_quick_export_path", "")).strip()
            configured = bool(node.parameters.get("_quick_export_configured", False) and destination)
            destination_label = QLabel(
                destination if configured else "Not configured — Export Geometry… chooses an OBJ destination.",
                quick_group.body,
            )
            destination_label.setObjectName("muted")
            destination_label.setWordWrap(True)
            quick_group.addRow("Destination", destination_label)

            buttons = QWidget(quick_group.body)
            button_layout = QHBoxLayout(buttons)
            button_layout.setContentsMargins(0, 0, 0, 0)
            button_layout.setSpacing(6)
            quick = QPushButton("Quick Export", buttons)
            quick.setEnabled(configured)
            quick.setToolTip("Overwrite the remembered OBJ destination using the current connected geometry.")
            configure = QPushButton("Export Geometry…", buttons)
            configure.setToolTip("Choose an OBJ destination and export the connected procedural mesh.")
            quick.clicked.connect(
                lambda _checked=False, uid=node.uid: self.geometryExportRequested.emit(uid, False)
            )
            configure.clicked.connect(
                lambda _checked=False, uid=node.uid: self.geometryExportRequested.emit(uid, True)
            )
            button_layout.addWidget(quick)
            button_layout.addWidget(configure)
            quick_group.addRow(buttons)
            self.form.addRow(quick_group)

    def _build_curve_node(self, node: NodeItem, target=None) -> None:
        points_spec = node.definition.parameter_spec("points")
        interpolation_spec = node.definition.parameter_spec("interpolation")
        if points_spec is None or interpolation_spec is None:
            return
        role = self.CURVE_NODES.get(node.definition.type_id, "tone")
        editor = CurveControl(
            node.parameters.get("points", points_spec.default),
            partial(self._node_parameter_changed, node, points_spec),
            str(node.parameters.get("interpolation", interpolation_spec.default)),
            partial(self._node_parameter_changed, node, interpolation_spec),
            role=role,
            parent=self,
        )
        editor.setToolTip(points_spec.description)
        editor.editStarted.connect(lambda n=node, label=points_spec.label: self._begin_visual_edit(n, f"Edit {label}"))
        editor.editFinished.connect(lambda n=node: self._end_visual_edit(n))
        (target if target is not None else self.form).addRow(editor)

    def _build_levels_node(self, node: NodeItem, target=None) -> None:
        channel = self._levels_channels.get(node.uid, "Luminance")
        view_mode = self._levels_views.get(node.uid, "histogram")
        parent_widget = target.body if isinstance(target, ParameterGroupWidget) else self.form_host
        control = LevelsControl(
            node.definition.parameters,
            dict(node.parameters),
            node.resolved_image_kind,
            set(node.exposed_parameter_inputs),
            channel=channel,
            view_mode=view_mode,
            parent=parent_widget,
        )
        self._levels_control = control
        control.valuesChanged.connect(lambda values, n=node: self._apply_levels_values(n, values))
        control.autoLevelRequested.connect(lambda selected, n=node: self._auto_level(n, selected))
        control.invertRequested.connect(lambda n=node: self._invert_levels(n))
        control.channelChanged.connect(lambda selected, n=node: self._levels_channel_changed(n, selected))
        control.viewModeChanged.connect(lambda mode, uid=node.uid: self._levels_views.__setitem__(uid, mode))
        control.socketToggled.connect(lambda name, checked, n=node: self._set_parameter_socket(n, name, checked))
        control.editStarted.connect(lambda n=node: self._begin_visual_edit(n, "Edit Levels"))
        control.editFinished.connect(lambda n=node: self._end_visual_edit(n))
        (target if target is not None else self.form).addRow(control)
        self._schedule_levels_histogram()

    def _build_histogram_adjustment_node(self, node: NodeItem, target=None) -> None:
        mode = self.HISTOGRAM_ADJUSTMENTS[node.definition.type_id]
        control = HistogramAdjustmentControl(
            mode,
            node.definition.parameters,
            dict(node.parameters),
            set(node.exposed_parameter_inputs),
            parent=self,
        )
        self._adjustment_histogram_control = control
        control.valuesChanged.connect(lambda values, n=node: self._apply_histogram_adjustment_values(n, values))
        control.socketToggled.connect(lambda name, checked, n=node: self._set_parameter_socket(n, name, checked))
        control.editStarted.connect(lambda n=node: self._begin_visual_edit(n, f"Edit {n.definition.name}"))
        control.editFinished.connect(lambda n=node: self._end_visual_edit(n))
        (target if target is not None else self.form).addRow(control)
        self._schedule_adjustment_histogram()

    def _apply_histogram_adjustment_values(self, node: NodeItem, values: dict[str, object]) -> None:
        if self._building:
            return
        names = {spec.name for spec in node.definition.parameters}
        changed = {name: value for name, value in values.items() if name in names and node.parameters.get(name) != value}
        if not changed:
            return
        merge_key = f"node:{node.uid}:histogram-adjustment"
        self.scene.begin_user_action(f"Change {node.definition.name}", merge_key=merge_key)
        try:
            node.parameters.update(changed)
            self.scene._touch()
        finally:
            self.scene.end_user_action(merge_key=merge_key)
        self._notify_visual_preview(node)

    @staticmethod
    def _histogram_source_reference(snapshot: GraphSnapshot, node: NodeItem) -> tuple[str, str] | None:
        input_name = node.definition.inputs[0] if node.definition.inputs else "Image"
        raw = snapshot.inputs.get((node.uid, input_name))
        if raw is None:
            return None
        if isinstance(raw, str):
            return raw, "Image"
        if isinstance(raw, (tuple, list)) and raw:
            return str(raw[0]), str(raw[1]) if len(raw) > 1 else "Image"
        return None

    def _histogram_request_spec(self, node: NodeItem, discriminator: str) -> tuple | None:
        if self.evaluator is None or self.document_provider is None:
            return None
        document = self.document_provider()
        if document is None:
            return None
        snapshot = GraphSnapshot.from_scene(self.scene)
        source_ref = self._histogram_source_reference(snapshot, node)
        if source_ref is None:
            return None
        source_uid, output_name = source_ref
        if source_uid not in snapshot.nodes:
            return None
        width, height = document.preview_size()
        animation = self.animation_context_provider() if self.animation_context_provider is not None else {}
        revision = self.evaluator.branch_revision(snapshot, source_uid)
        animation_key = tuple(sorted((str(key), repr(value)) for key, value in animation.items()))
        key = (
            node.uid,
            source_uid,
            output_name,
            revision,
            max(int(width), 1),
            max(int(height), 1),
            str(document.texture_precision),
            str(document.colour_space),
            animation_key,
            str(discriminator),
        )
        return key, snapshot, source_uid, output_name, max(int(width), 1), max(int(height), 1), document, animation

    @staticmethod
    def _histogram_sample(image: np.ndarray, maximum_dimension: int = 512) -> np.ndarray:
        return stratified_image_sample(image, maximum_dimension)

    @staticmethod
    def _remember_histogram(cache: dict, key: tuple, value, limit: int = 12) -> None:
        cache.pop(key, None)
        cache[key] = value
        while len(cache) > max(int(limit), 1):
            cache.pop(next(iter(cache)))

    def _histogram_interaction_started(self, node_uid: str) -> None:
        self._histogram_interaction_depth += 1
        if not isinstance(self.item, NodeItem) or self.item.uid != str(node_uid):
            return
        self._levels_histogram_timer.stop()
        self._adjustment_histogram_timer.stop()
        if self._levels_histogram_controller is not None:
            self._levels_histogram_controller.cancel()
        if self._adjustment_histogram_controller is not None:
            self._adjustment_histogram_controller.cancel()
        self._levels_histogram_request_key = None
        self._adjustment_histogram_request_key = None
        self.histogramActivityChanged.emit(False, "")

    def _histogram_interaction_finished(self, node_uid: str) -> None:
        del node_uid
        self._histogram_interaction_depth = max(self._histogram_interaction_depth - 1, 0)
        if self._histogram_interaction_depth:
            return
        self._schedule_levels_histogram()
        self._schedule_adjustment_histogram()

    def _interactive_edit_started(self, node_uid: str) -> None:
        self._histogram_interaction_started(node_uid)
        self.interactiveEditStarted.emit(str(node_uid))

    def _interactive_edit_finished(self, node_uid: str) -> None:
        self._histogram_interaction_finished(node_uid)
        self.interactiveEditFinished.emit(str(node_uid))

    def _schedule_adjustment_histogram(self) -> None:
        if self._histogram_interaction_depth > 0:
            return
        node = self.item
        if not isinstance(node, NodeItem) or node.definition.type_id not in self.HISTOGRAM_ADJUSTMENTS:
            return
        if self._adjustment_histogram_controller is None or self.document_provider is None:
            return
        spec = self._histogram_request_spec(node, node.definition.type_id)
        key = spec[0] if spec is not None else None
        if key is not None and key in {self._adjustment_histogram_request_key, self._adjustment_histogram_completed_key}:
            return
        if key is not None and key in self._adjustment_histogram_cache:
            histogram, underflow, overflow = self._adjustment_histogram_cache[key]
            self._adjustment_histogram_completed_key = key
            if self._adjustment_histogram_control is not None:
                self._adjustment_histogram_control.set_histogram(
                    histogram, underflow=underflow, overflow=overflow
                )
            return
        self._adjustment_histogram_timer.start()

    def _request_adjustment_histogram(self) -> None:
        node = self.item
        if self._histogram_interaction_depth > 0:
            return
        if not isinstance(node, NodeItem) or node.definition.type_id not in self.HISTOGRAM_ADJUSTMENTS:
            return
        if self._adjustment_histogram_controller is None:
            return
        spec = self._histogram_request_spec(node, node.definition.type_id)
        if spec is None:
            self._adjustment_histogram_controller.cancel()
            self._adjustment_histogram_request_key = None
            self.histogramActivityChanged.emit(False, "")
            if self._adjustment_histogram_control is not None:
                empty = np.zeros(HISTOGRAM_INTERNAL_BINS, dtype=np.float64)
                empty[0] = 1.0
                self._adjustment_histogram_control.set_histogram(empty)
            return
        key, snapshot, source_uid, output_name, width, height, document, animation = spec
        if key in {self._adjustment_histogram_request_key, self._adjustment_histogram_completed_key}:
            return
        cached = self._adjustment_histogram_cache.get(key)
        if cached is not None:
            histogram, underflow, overflow = cached
            self._adjustment_histogram_completed_key = key
            self._adjustment_histogram_request_key = None
            self.histogramActivityChanged.emit(False, "")
            if self._adjustment_histogram_control is not None:
                self._adjustment_histogram_control.set_histogram(
                    histogram, underflow=underflow, overflow=overflow
                )
            return
        self._adjustment_histogram_request_key = key
        self._adjustment_histogram_uid = node.uid
        if self._adjustment_histogram_control is not None:
            self._adjustment_histogram_control.set_histogram(None, "Evaluating cached input histogram…")
        source_name = snapshot.nodes[source_uid].definition.name
        self.histogramActivityChanged.emit(
            True,
            f"{node.definition.name} input histogram — reusing {source_name} at {width} × {height}",
        )
        self._adjustment_histogram_controller.request(
            snapshot,
            source_uid,
            width,
            height,
            precision=document.texture_precision,
            colour_space=document.colour_space,
            render_mode="histogram",
            output_name=output_name,
            **animation,
        )

    def _adjustment_histogram_ready(self, result) -> None:
        node = self.item
        control = self._adjustment_histogram_control
        if (
            not isinstance(node, NodeItem)
            or node.definition.type_id not in self.HISTOGRAM_ADJUSTMENTS
            or control is None
            or node.uid != self._adjustment_histogram_uid
        ):
            return
        if result.error or result.image is None:
            self._adjustment_histogram_request_key = None
            self.histogramActivityChanged.emit(False, "")
            control.set_histogram(None, result.error or "Histogram unavailable")
            return
        image = self._histogram_sample(result.image)
        values = image[..., 0] if result.data_kind == "grayscale" else image[..., :3] @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        finite = np.asarray(values[np.isfinite(values)], dtype=np.float32)
        if finite.size == 0:
            self._adjustment_histogram_request_key = None
            self.histogramActivityChanged.emit(False, "")
            control.set_histogram(None, "No finite input values")
            return
        distribution = compute_histogram_distribution(finite)
        histogram = distribution.counts
        completed_key = self._adjustment_histogram_request_key
        self._adjustment_histogram_completed_key = completed_key
        self._adjustment_histogram_request_key = None
        if completed_key is not None:
            self._remember_histogram(
                self._adjustment_histogram_cache,
                completed_key,
                (histogram.copy(), distribution.underflow, distribution.overflow),
            )
        self.histogramActivityChanged.emit(False, "")
        control.set_histogram(
            histogram,
            underflow=distribution.underflow,
            overflow=distribution.overflow,
        )

    def _adjustment_histogram_failed(self, message: str) -> None:
        self._adjustment_histogram_request_key = None
        self.histogramActivityChanged.emit(False, "")
        if self._adjustment_histogram_control is not None:
            self._adjustment_histogram_control.set_histogram(None, message)

    def _apply_levels_values(self, node: NodeItem, values: dict[str, object], *, label: str = "Change Levels") -> None:
        if self._building:
            return
        changed = {
            name: values[name]
            for name in ("in_low", "in_high", "in_mid", "out_low", "out_high", "intermediary_clamp")
            if name in values and node.parameters.get(name) != values[name]
        }
        if not changed:
            return
        merge_key = f"node:{node.uid}:levels"
        self.scene.begin_user_action(label, merge_key=merge_key)
        try:
            node.parameters.update(changed)
            self.scene._touch()
        finally:
            self.scene.end_user_action(merge_key=merge_key)
        self._notify_visual_preview(node)

    def _invert_levels(self, node: NodeItem) -> None:
        values = dict(node.parameters)
        values["out_low"], values["out_high"] = (
            float(values.get("out_high", 1.0)),
            float(values.get("out_low", 0.0)),
        )
        self._apply_levels_values(node, values, label="Invert Levels")
        if self._levels_control is not None and self.item is node:
            self._levels_control.set_values(values)

    def _auto_level(self, node: NodeItem, _channel: str) -> None:
        if self._levels_histogram_stats is None:
            self._schedule_levels_histogram()
            return
        low, high = self._levels_histogram_stats
        if high - low < 1e-6:
            low, high = 0.0, 1.0
        values = dict(node.parameters)
        values["in_low"] = min(max(float(low), 0.0), 0.999)
        values["in_high"] = min(max(float(high), values["in_low"] + 0.001), 1.0)
        # Deliberately leave Level In Mid untouched. Adobe's Auto Level quick
        # action only sets input low/high, making this a one-shot operation
        # distinct from the continuously adapting Auto Levels node.
        self._apply_levels_values(node, values, label="Auto Level")
        if self._levels_control is not None and self.item is node:
            self._levels_control.set_values(values)

    def _levels_channel_changed(self, node: NodeItem, channel: str) -> None:
        self._levels_channels[node.uid] = str(channel)
        self._levels_histogram_stats = None
        if self._levels_control is not None:
            self._levels_control.set_histogram(None, ready=False, message="Evaluating input histogram…")
        self._schedule_levels_histogram()

    def _schedule_levels_histogram(self) -> None:
        if self._histogram_interaction_depth > 0:
            return
        node = self.item
        if not isinstance(node, NodeItem) or node.definition.type_id != "filter.levels":
            return
        if self._levels_histogram_controller is None or self.document_provider is None:
            return
        channel = self._levels_channels.get(node.uid, "Luminance")
        spec = self._histogram_request_spec(node, f"levels:{channel}")
        key = spec[0] if spec is not None else None
        if key is not None and key in {self._levels_histogram_request_key, self._levels_histogram_completed_key}:
            return
        if key is not None and key in self._levels_histogram_cache:
            histogram, low, high, underflow, overflow = self._levels_histogram_cache[key]
            self._levels_histogram_stats = (low, high)
            self._levels_histogram_completed_key = key
            if self._levels_control is not None:
                self._levels_control.set_histogram(
                    histogram, ready=True, underflow=underflow, overflow=overflow
                )
            return
        self._levels_histogram_timer.start()

    def _request_levels_histogram(self) -> None:
        node = self.item
        if self._histogram_interaction_depth > 0:
            return
        if not isinstance(node, NodeItem) or node.definition.type_id != "filter.levels":
            return
        if self._levels_histogram_controller is None:
            return
        channel = self._levels_channels.get(node.uid, "Luminance")
        spec = self._histogram_request_spec(node, f"levels:{channel}")
        if spec is None:
            self._levels_histogram_controller.cancel()
            self._levels_histogram_request_key = None
            self.histogramActivityChanged.emit(False, "")
            empty = np.zeros(HISTOGRAM_INTERNAL_BINS, dtype=np.float64)
            empty[0] = 1.0
            self._levels_histogram_stats = (0.0, 0.0)
            if self._levels_control is not None:
                self._levels_control.set_histogram(empty, ready=True)
            return
        key, snapshot, source_uid, output_name, width, height, document, animation = spec
        if key in {self._levels_histogram_request_key, self._levels_histogram_completed_key}:
            return
        cached = self._levels_histogram_cache.get(key)
        if cached is not None:
            histogram, low, high, underflow, overflow = cached
            self._levels_histogram_stats = (low, high)
            self._levels_histogram_completed_key = key
            self._levels_histogram_request_key = None
            self.histogramActivityChanged.emit(False, "")
            if self._levels_control is not None:
                self._levels_control.set_histogram(
                    histogram, ready=True, underflow=underflow, overflow=overflow
                )
            return
        self._levels_histogram_request_key = key
        self._levels_histogram_uid = node.uid
        if self._levels_control is not None:
            self._levels_control.set_histogram(None, ready=False, message="Evaluating cached input histogram…")
        source_name = snapshot.nodes[source_uid].definition.name
        self.histogramActivityChanged.emit(
            True,
            f"Levels input histogram — reusing {source_name} at {width} × {height}",
        )
        self._levels_histogram_controller.request(
            snapshot,
            source_uid,
            width,
            height,
            precision=document.texture_precision,
            colour_space=document.colour_space,
            render_mode="histogram",
            output_name=output_name,
            **animation,
        )

    def _levels_histogram_ready(self, result) -> None:
        node = self.item
        control = self._levels_control
        if (
            not isinstance(node, NodeItem)
            or node.definition.type_id != "filter.levels"
            or control is None
            or node.uid != self._levels_histogram_uid
        ):
            return
        if result.error or result.image is None:
            self._levels_histogram_request_key = None
            self.histogramActivityChanged.emit(False, "")
            control.set_histogram(None, ready=False, message=result.error or "Histogram unavailable")
            return
        image = self._histogram_sample(result.image)
        channel = self._levels_channels.get(node.uid, control.channel.currentText())
        if channel == "Red":
            values = image[..., 0]
        elif channel == "Green":
            values = image[..., 1]
        elif channel == "Blue":
            values = image[..., 2]
        elif channel == "Alpha":
            values = image[..., 3]
        elif result.data_kind == "grayscale":
            values = image[..., 0]
        else:
            values = image[..., :3] @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        finite = np.asarray(values[np.isfinite(values)], dtype=np.float32)
        if finite.size == 0:
            self._levels_histogram_stats = None
            self._levels_histogram_request_key = None
            self.histogramActivityChanged.emit(False, "")
            control.set_histogram(None, ready=False, message="No finite input values")
            return
        distribution = compute_histogram_distribution(finite)
        histogram = distribution.counts
        low = distribution.clipped_minimum
        high = distribution.clipped_maximum
        self._levels_histogram_stats = (low, high)
        completed_key = self._levels_histogram_request_key
        self._levels_histogram_completed_key = completed_key
        self._levels_histogram_request_key = None
        if completed_key is not None:
            self._remember_histogram(
                self._levels_histogram_cache,
                completed_key,
                (
                    histogram.copy(), low, high,
                    distribution.underflow, distribution.overflow,
                ),
            )
        self.histogramActivityChanged.emit(False, "")
        control.set_histogram(
            histogram,
            ready=True,
            underflow=distribution.underflow,
            overflow=distribution.overflow,
        )

    def _levels_histogram_failed(self, message: str) -> None:
        self._levels_histogram_request_key = None
        self.histogramActivityChanged.emit(False, "")
        if self._levels_control is not None:
            self._levels_control.set_histogram(None, ready=False, message=message)

    def _build_group(self, group: GroupFrameItem) -> None:
        self.title.setText(group.name)
        self.description.setText(
            "Resizable comment frame, non-destructive collapsed node, and reusable user-library asset."
        )

        name = QLineEdit(group.name)
        name.textEdited.connect(lambda value: self.scene.set_group_property(group, "name", value))
        self.form.addRow("Group name", name)

        category = QLineEdit(group.category)
        category.setPlaceholderText("User or User/Distortion")
        category.textEdited.connect(lambda value: self.scene.set_group_property(group, "category", value or "User"))
        self.form.addRow("Library category", category)

        note = QTextEdit()
        note.setPlainText(group.description)
        note.setPlaceholderText("Describe what this group does…")
        note.setMaximumHeight(105)
        note.textChanged.connect(lambda: self.scene.set_group_property(group, "description", note.toPlainText()))
        self.form.addRow("Description", note)

        collapsed = QCheckBox("Show as a single group node")
        collapsed.setChecked(group.collapsed)
        collapsed.toggled.connect(lambda value: self._set_group_collapsed(group, value))
        self.form.addRow("Collapsed", collapsed)

        info = QLabel(
            f"{len(group.members)} internal node{'s' if len(group.members) != 1 else ''}  ·  "
            f"{len(group.input_ports)} input{'s' if len(group.input_ports) != 1 else ''}  ·  "
            f"{len(group.output_ports)} output{'s' if len(group.output_ports) != 1 else ''}"
        )
        info.setObjectName("muted")
        self.form.addRow(info)

        self._section("Group Inputs")
        self._build_group_interface(group, "input")
        self._section("Group Outputs")
        self._build_group_interface(group, "output")

        exposed_entries = []
        for index, entry in enumerate(group.exposed_parameters):
            node = self.scene.nodes.get(str(entry.get("node", "")))
            if node is None:
                continue
            spec = next((s for s in node.definition.parameters if s.name == entry.get("parameter")), None)
            if spec is None:
                continue
            exposed_entries.append((index, entry, node, spec))

        if exposed_entries:
            self._section("Exposed Parameters")
            for index, entry, node, spec in exposed_entries:
                alias = str(entry.get("name") or f"{node.definition.name} · {spec.label}")
                alias_edit = QLineEdit(alias)
                alias_edit.textEdited.connect(
                    lambda value, i=index: self.scene.set_exposed_parameter_alias(group, i, value)
                )
                self.form.addRow("Label", alias_edit)
                value = node.parameters.get(spec.name, spec.default)
                callback = partial(self._node_parameter_changed, node, spec)
                if spec.kind == "curve" and node.definition.type_id in self.CURVE_NODES:
                    interpolation_spec = node.definition.parameter_spec("interpolation")
                    interpolation_value = (
                        str(node.parameters.get("interpolation", interpolation_spec.default))
                        if interpolation_spec is not None else "Smooth"
                    )
                    interpolation_callback = (
                        partial(self._node_parameter_changed, node, interpolation_spec)
                        if interpolation_spec is not None else None
                    )
                    control = CurveControl(
                        value,
                        callback,
                        interpolation_value,
                        interpolation_callback,
                        role=self.CURVE_NODES[node.definition.type_id],
                        parent=self,
                    )
                    control.editStarted.connect(lambda n=node, label=spec.label: self._begin_visual_edit(n, f"Edit {label}"))
                    control.editFinished.connect(lambda n=node: self._end_visual_edit(n))
                else:
                    control = self._control_for_spec(spec, value, callback, node=node)
                self.form.addRow(alias, control)

        self._section("Choose Exposed Parameters")
        available = 0
        exposed_keys = {
            (str(entry.get("node", "")), str(entry.get("parameter", "")))
            for entry in group.exposed_parameters
        }
        for node_uid in sorted(group.members, key=lambda uid: self.scene.nodes[uid].definition.name if uid in self.scene.nodes else uid):
            node = self.scene.nodes.get(node_uid)
            if node is None:
                continue
            for spec in node.definition.parameters:
                available += 1
                key = (node.uid, spec.name)
                checkbox = QCheckBox(f"{node.definition.name} · {spec.label}")
                checkbox.setChecked(key in exposed_keys)
                checkbox.toggled.connect(
                    lambda checked, n=node.uid, p=spec.name, label=f"{node.definition.name} · {spec.label}":
                    self._toggle_exposed_parameter(group, n, p, checked, label)
                )
                self.form.addRow(checkbox)
        if not available:
            label = QLabel("The nodes in this group have no editable parameters to expose.")
            label.setObjectName("muted")
            label.setWordWrap(True)
            self.form.addRow(label)

        self._section("Reusable User Node")
        save = QPushButton("Save / Update in User Library…")
        save.clicked.connect(lambda: self.saveGroupRequested.emit(group))
        save.setEnabled(bool(group.members))
        open_folder = QPushButton("Open User Node Folder")
        open_folder.clicked.connect(self.openUserLibraryRequested.emit)
        self.form.addRow(save)
        self.form.addRow(open_folder)

        hint = QLabel(
            "Collapsed ports are generated from the group boundary: unused internal inputs become group inputs, and terminal internal nodes become outputs."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        self.form.addRow(hint)

    def _build_group_interface(self, group: GroupFrameItem, kind: str) -> None:
        collection = group.interface_inputs if kind == "input" else group.interface_outputs
        if not collection:
            label = QLabel(
                "No available boundary inputs." if kind == "input" else "No available terminal outputs."
            )
            label.setObjectName("muted")
            self.form.addRow(label)
            return

        for index, entry in enumerate(collection):
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(5)

            enabled = QCheckBox()
            enabled.setChecked(bool(entry.get("enabled", True)))
            forced = self.scene.group_interface_is_forced(group, kind, entry)
            enabled.setEnabled(not forced)
            enabled.setToolTip(
                "This port is required by an existing external connection."
                if forced
                else "Show this port on the collapsed group node."
            )
            enabled.toggled.connect(
                lambda checked, i=index, k=kind: self._set_interface_enabled(group, k, i, checked)
            )

            alias = QLineEdit(str(entry.get("name", "")))
            alias.setToolTip("Public port name shown on the collapsed group node.")
            alias.textEdited.connect(
                lambda value, i=index, k=kind: self.scene.set_group_interface_alias(group, k, i, value)
            )

            up = QPushButton("↑")
            down = QPushButton("↓")
            up.setFixedWidth(28)
            down.setFixedWidth(28)
            up.setEnabled(index > 0)
            down.setEnabled(index < len(collection) - 1)
            up.setToolTip("Move this port up.")
            down.setToolTip("Move this port down.")
            up.clicked.connect(lambda _checked=False, i=index, k=kind: self._move_interface(group, k, i, -1))
            down.clicked.connect(lambda _checked=False, i=index, k=kind: self._move_interface(group, k, i, 1))

            layout.addWidget(enabled)
            layout.addWidget(alias, 1)
            layout.addWidget(up)
            layout.addWidget(down)

            node = self.scene.nodes.get(str(entry.get("node", "")))
            internal = node.definition.name if node is not None else "Missing node"
            if kind == "input":
                internal += f" · {entry.get('input', '')}"
            self.form.addRow(internal, row)

    def _set_interface_enabled(
        self,
        group: GroupFrameItem,
        kind: str,
        index: int,
        enabled: bool,
    ) -> None:
        if self._building:
            return
        self.scene.set_group_interface_enabled(group, kind, index, enabled)
        current = self.scene.groups.get(group.uid)
        if current is not None:
            QTimer.singleShot(0, lambda: self.set_item(current))

    def _move_interface(
        self,
        group: GroupFrameItem,
        kind: str,
        index: int,
        direction: int,
    ) -> None:
        self.scene.move_group_interface(group, kind, index, direction)
        current = self.scene.groups.get(group.uid)
        if current is not None:
            QTimer.singleShot(0, lambda: self.set_item(current))

    def _set_group_collapsed(self, group: GroupFrameItem, value: bool) -> None:
        if self._building or group.collapsed == value:
            return
        self.scene.toggle_group(group)
        current = self.scene.groups.get(group.uid)
        if current is not None:
            QTimer.singleShot(0, lambda: self.set_item(current))

    def _toggle_exposed_parameter(
        self,
        group: GroupFrameItem,
        node_uid: str,
        parameter_name: str,
        checked: bool,
        label: str,
    ) -> None:
        if self._building:
            return
        self.scene.set_group_parameter_exposed(group, node_uid, parameter_name, checked, label)
        current = self.scene.groups.get(group.uid)
        if current is not None:
            QTimer.singleShot(0, lambda: self.set_item(current))

    def _begin_visual_edit(self, node: NodeItem, label: str) -> None:
        if self._building:
            return
        if self._visual_edit_depth and self._visual_edit_node_uid != node.uid:
            self._finish_visual_edits()
        if self._visual_edit_depth == 0:
            self.scene.begin_user_action(label)
            self._visual_edit_node_uid = node.uid
            self._interactive_edit_started(node.uid)
        self._visual_edit_depth += 1

    def _end_visual_edit(self, node: NodeItem) -> None:
        if self._visual_edit_depth <= 0:
            return
        if self._visual_edit_node_uid not in (None, node.uid):
            self._finish_visual_edits()
            return
        self._visual_edit_depth -= 1
        if self._visual_edit_depth == 0:
            self._visual_edit_node_uid = None
            self.scene.end_user_action()
            self._interactive_edit_finished(node.uid)

    def _finish_visual_edits(self) -> None:
        if self._visual_edit_depth <= 0:
            self._visual_edit_depth = 0
            self._visual_edit_node_uid = None
            return
        node_uid = self._visual_edit_node_uid
        self._visual_edit_depth = 0
        self._visual_edit_node_uid = None
        self.scene.end_user_action()
        if node_uid:
            self._interactive_edit_finished(node_uid)

    def _notify_visual_preview(self, node: NodeItem) -> None:
        # Visual canvases already debounce drag updates.  While their outer undo
        # transaction is open, emit a preview refresh without closing it so one
        # drag remains one undo step.
        if self._visual_edit_depth > 0 and self._visual_edit_node_uid == node.uid:
            self.scene.graphChanged.emit()

    def _control_for_spec(
        self,
        spec: ParameterSpec,
        value,
        callback,
        *,
        node: NodeItem | None = None,
        parent: QWidget | None = None,
    ) -> QWidget:
        if spec.kind in ("float", "int"):
            control = NumberControl(spec, value, callback, parent)
            if node is not None:
                control.editStarted.connect(lambda uid=node.uid: self._interactive_edit_started(uid))
                control.editFinished.connect(lambda uid=node.uid: self._interactive_edit_finished(uid))
            return control
        if spec.kind == "bool":
            control = QCheckBox(parent)
            control.setChecked(bool(value))
            control.toggled.connect(callback)
            return control
        if spec.kind == "enum":
            control = QComboBox(parent)
            control.addItems(spec.options)
            control.setCurrentText(str(value))
            control.currentTextChanged.connect(callback)
            return control
        if spec.kind == "portal_channel":
            control = QComboBox(parent)
            control.addItem("Unassigned", "")
            sends = []
            if hasattr(self.scene, "portal_sends"):
                sends = sorted(
                    self.scene.portal_sends(),
                    key=lambda candidate: str(candidate.parameters.get("channel_name", "Channel")).casefold(),
                )
            for sender in sends:
                label = str(sender.parameters.get("channel_name", "Channel")).strip() or "Channel"
                control.addItem(label, sender.uid)
            wanted = str(value or "")
            found = False
            for index in range(control.count()):
                if str(control.itemData(index) or "") == wanted:
                    control.setCurrentIndex(index)
                    found = True
                    break
            if wanted and not found:
                cached = str(node.parameters.get("channel_name", "Missing channel")) if node is not None else "Missing channel"
                control.addItem(f"Missing · {cached}", wanted)
                control.setCurrentIndex(control.count() - 1)
            control.currentIndexChanged.connect(
                lambda index, combo=control: callback(str(combo.itemData(index) or ""))
            )
            return control
        if spec.kind == "color":
            return ColourControl(str(value), callback, parent)
        if spec.kind == "gradient":
            control = GradientControl(value, callback, parent)
            if node is not None:
                control.editStarted.connect(lambda n=node, label=spec.label: self._begin_visual_edit(n, f"Edit {label}"))
                control.editFinished.connect(lambda n=node: self._end_visual_edit(n))
            return control
        if spec.kind == "curve":
            control = CurveControl(value, callback, parent=parent)
            if node is not None:
                control.editStarted.connect(lambda n=node, label=spec.label: self._begin_visual_edit(n, f"Edit {label}"))
                control.editFinished.connect(lambda n=node: self._end_visual_edit(n))
            return control
        if spec.kind == "string":
            control = QLineEdit(str(value), parent)
            control.editingFinished.connect(lambda: callback(control.text()))
            return control
        if spec.kind in ("file", "mesh_file"):
            return FileControl(
                str(value),
                callback,
                lambda path: self._reload_file_parameter(self.item, spec, path),
                parent=parent,
                file_kind="mesh" if spec.kind == "mesh_file" else "image",
            )
        return QLabel(str(value), parent)

    def _open_canvas_editor(self) -> None:
        window = self.window()
        dock = getattr(window, "canvas_dock", None)
        if dock is not None:
            dock.show()
            dock.raise_()

    def _set_parameter_socket(self, node: NodeItem, parameter_name: str, exposed: bool) -> None:
        if self._building:
            return
        self.scene.set_parameter_socket_exposed(node, parameter_name, exposed)
        current = self.scene.nodes.get(node.uid)
        if current is not None:
            QTimer.singleShot(0, lambda: self.set_item(current))

    def _set_parameter_asset_published(
        self, node: NodeItem, parameter_name: str, published: bool
    ) -> None:
        if self._building:
            return
        self.scene.set_parameter_asset_published(node, parameter_name, published)
        current = self.scene.nodes.get(node.uid)
        if current is not None:
            QTimer.singleShot(0, lambda: self.set_item(current))

    def _edit_graph_asset_parameter(self, node: NodeItem, spec: ParameterSpec) -> None:
        current_all = node.parameters.get("_graph_asset_parameter_meta", {})
        current = dict(current_all.get(spec.name, {})) if isinstance(current_all, dict) else {}
        unpublished = {
            str(name) for name in node.parameters.get("_graph_asset_unpublished_inputs", ())
        }
        dialog = GraphAssetParameterDialog(
            name=str(current.get("name") or spec.label),
            description=str(current.get("description") or spec.description),
            group=str(current.get("group") or spec.group or self._parameter_group_name(spec)),
            order=int(current.get("order", spec.group_order)),
            published=spec.name not in unpublished,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.scene.set_parameter_asset_metadata(node, spec.name, dialog.metadata())
        current_node = self.scene.nodes.get(node.uid)
        if current_node is not None:
            QTimer.singleShot(0, lambda: self.set_item(current_node))

    def _node_parameter_changed(self, node: NodeItem, spec: ParameterSpec, value) -> None:
        if self._building:
            return
        self.scene.change_node_parameter(node, spec.name, value, label=f"Change {spec.label}")
        self._notify_visual_preview(node)
        changes_parameter_layout = any(
            any(controller_name == spec.name for controller_name, _allowed in candidate.visible_when)
            for candidate in node.definition.parameters
        )
        changes_resolved_type = (
            (node.definition.type_id == "input.image" and spec.name == "data_type")
            or (node.definition.type_id == "convert.channel_pack" and spec.name == "output_data_type")
            or (node.definition.type_id == "graph.send" and spec.name == "channel_name")
            or (node.definition.type_id == "graph.receive" and spec.name == "sender_uid")
        )
        if changes_parameter_layout or changes_resolved_type:
            scroll_value = self.scroll.verticalScrollBar().value()
            current = self.scene.nodes.get(node.uid)
            if current is not None:
                self.set_item(current)
                QTimer.singleShot(0, lambda value=scroll_value: self.scroll.verticalScrollBar().setValue(value))

    def _reload_file_parameter(self, item, spec: ParameterSpec, path: str) -> None:
        if self._building or not isinstance(item, NodeItem):
            return
        import time
        self.scene.begin_user_action(f"Reload {spec.label}")
        try:
            item.parameters[spec.name] = path
            item.parameters["_reload_token"] = time.time_ns()
            if item.definition.type_id == "input.image":
                try:
                    from ..nodes.input_nodes import refresh_image_metadata
                    refresh_image_metadata(item.parameters)
                    self.scene._resolve_dynamic_types()
                    self.scene._refresh_all_groups()
                except Exception:
                    pass
            self.scene._touch()
        finally:
            self.scene.end_user_action()
        current = self.scene.nodes.get(item.uid)
        if current is not None:
            QTimer.singleShot(0, lambda current=current: self.set_item(current))
