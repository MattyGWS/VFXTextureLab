from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..canvas_node import canvas_array_from_params, encode_canvas_array, ensure_canvas_parameters, resize_canvas_array
from ..graph.items import NodeItem
from ..graph.scene import GraphScene
from ..theme import theme_colour


@dataclass
class _ToolState:
    name: str = "Paint"
    value: float = 1.0
    size: int = 36
    softness: float = 0.65
    opacity: float = 1.0


@dataclass(frozen=True)
class _CanvasSnapshot:
    data: str
    width: int
    height: int


class CanvasPaintWidget(QWidget):
    strokeStarted = Signal()
    strokeUpdated = Signal()
    strokeFinished = Signal()
    zoomChanged = Signal(float)

    MIN_ZOOM = 0.15
    MAX_ZOOM = 32.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(260)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.image = np.zeros((256, 256), dtype=np.float32)
        self._tool = _ToolState()
        self._background_value = 0.0
        self._display_rect = QRectF()
        self._zoom = 1.0
        self._pan = QPointF()
        self._panning = False
        self._pan_start = QPoint()
        self._drawing = False
        self._last_image_pos: tuple[float, float] | None = None
        self._shape_start: tuple[float, float] | None = None
        self._shape_end: tuple[float, float] | None = None

    def set_canvas(
        self,
        array: np.ndarray,
        *,
        background_value: float = 0.0,
        reset_view: bool = False,
    ) -> None:
        self.image = np.clip(np.asarray(array, dtype=np.float32), 0.0, 1.0).copy()
        self._background_value = float(background_value)
        self._drawing = False
        self._last_image_pos = None
        self._shape_start = None
        self._shape_end = None
        if reset_view:
            self.reset_view()
        else:
            self.update()

    def set_tool_state(self, state: _ToolState) -> None:
        self._tool = state
        self.update()

    def sizeHint(self):
        return super().sizeHint()

    def _image_qimage(self) -> QImage:
        h, w = self.image.shape
        rgb = np.repeat(np.rint(self.image[..., None] * 255.0).astype(np.uint8), 3, axis=2)
        qimage = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format.Format_RGB888)
        return qimage.copy()

    def _target_rect(self) -> QRectF:
        h, w = self.image.shape
        outer = self.rect().adjusted(10, 10, -10, -10)
        if w <= 0 or h <= 0 or outer.width() <= 0 or outer.height() <= 0:
            return QRectF()
        fit_scale = min(outer.width() / w, outer.height() / h)
        scale = fit_scale * self._zoom
        width = w * scale
        height = h * scale
        x = outer.x() + (outer.width() - width) * 0.5 + self._pan.x()
        y = outer.y() + (outer.height() - height) * 0.5 + self._pan.y()
        self._display_rect = QRectF(x, y, width, height)
        return self._display_rect

    def reset_view(self) -> None:
        self._zoom = 1.0
        self._pan = QPointF()
        self.zoomChanged.emit(self._zoom)
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:
        old_rect = self._target_rect()
        if old_rect.isNull() or event.angleDelta().y() == 0:
            event.ignore()
            return

        mouse = event.position()
        image_position = QPointF(
            (mouse.x() - old_rect.x()) / max(old_rect.width(), 1e-6),
            (mouse.y() - old_rect.y()) / max(old_rect.height(), 1e-6),
        )
        factor = 1.2 if event.angleDelta().y() > 0 else 1.0 / 1.2
        new_zoom = min(self.MAX_ZOOM, max(self.MIN_ZOOM, self._zoom * factor))
        if abs(new_zoom - self._zoom) < 1e-9:
            event.accept()
            return

        self._zoom = new_zoom
        new_rect = self._target_rect()
        anchored = QPointF(
            new_rect.x() + image_position.x() * new_rect.width(),
            new_rect.y() + image_position.y() * new_rect.height(),
        )
        self._pan += mouse - anchored
        self.zoomChanged.emit(self._zoom)
        self.update()
        event.accept()

    def _event_to_image(self, pos) -> tuple[float, float] | None:
        rect = self._target_rect()
        if rect.isNull() or not rect.contains(QPointF(pos)):
            return None
        h, w = self.image.shape
        u = (pos.x() - rect.x()) / max(rect.width(), 1e-6)
        v = (pos.y() - rect.y()) / max(rect.height(), 1e-6)
        x = np.clip(u * w, 0.0, max(w - 1, 0))
        y = np.clip(v * h, 0.0, max(h - 1, 0))
        return float(x), float(y)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#13161d"))
        rect = self._target_rect()
        if rect.isNull():
            return
        painter.fillRect(rect, QColor("#0d1016"))
        image = self._image_qimage()
        painter.drawImage(rect, image)
        painter.setPen(QPen(QColor("#5a6270"), 1.0))
        painter.drawRect(rect)
        if self._shape_start is not None and self._shape_end is not None and self._tool.name in {"Line", "Rectangle", "Ellipse"}:
            sx, sy = self._shape_start
            ex, ey = self._shape_end
            h, w = self.image.shape
            def img_to_widget(x: float, y: float) -> QPointF:
                return QPointF(rect.x() + (x / max(w, 1)) * rect.width(), rect.y() + (y / max(h, 1)) * rect.height())
            p0 = img_to_widget(sx, sy)
            p1 = img_to_widget(ex, ey)
            painter.setPen(QPen(QColor("#f1f4fb"), 1.5, Qt.PenStyle.DashLine))
            if self._tool.name == "Line":
                painter.drawLine(p0, p1)
            else:
                preview_rect = QRectF(min(p0.x(), p1.x()), min(p0.y(), p1.y()), abs(p1.x() - p0.x()), abs(p1.y() - p0.y()))
                if self._tool.name == "Rectangle":
                    painter.drawRect(preview_rect)
                else:
                    painter.drawEllipse(preview_rect)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        pos = self._event_to_image(event.position())
        if pos is None:
            return
        self._drawing = True
        self._last_image_pos = pos
        self.strokeStarted.emit()
        if self._tool.name in {"Line", "Rectangle", "Ellipse"}:
            self._shape_start = pos
            self._shape_end = pos
        else:
            self._stamp_or_smudge(pos, pos)
        self.update()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._panning:
            current = event.position().toPoint()
            delta = current - self._pan_start
            self._pan_start = current
            self._pan += QPointF(delta)
            self.update()
            event.accept()
            return
        pos = self._event_to_image(event.position())
        if not self._drawing or pos is None:
            return super().mouseMoveEvent(event)
        if self._tool.name in {"Line", "Rectangle", "Ellipse"}:
            self._shape_end = pos
        else:
            last = self._last_image_pos or pos
            self._stamp_or_smudge(last, pos)
            self._last_image_pos = pos
            self.strokeUpdated.emit()
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._panning and event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.unsetCursor()
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton or not self._drawing:
            return super().mouseReleaseEvent(event)
        pos = self._event_to_image(event.position()) or self._last_image_pos
        if self._tool.name in {"Line", "Rectangle", "Ellipse"} and self._shape_start is not None and pos is not None:
            self._shape_end = pos
            self._apply_shape(self._shape_start, self._shape_end)
            self.strokeUpdated.emit()
        self._drawing = False
        self._last_image_pos = None
        self._shape_start = None
        self._shape_end = None
        self.strokeFinished.emit()
        self.update()
        event.accept()

    def _stamp_or_smudge(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        x0, y0 = start
        x1, y1 = end
        distance = max(abs(x1 - x0), abs(y1 - y0))
        steps = max(int(distance / max(self._tool.size * 0.18, 1.0)), 1)
        for index in range(steps + 1):
            t = index / max(steps, 1)
            x = x0 + (x1 - x0) * t
            y = y0 + (y1 - y0) * t
            if self._tool.name == "Smudge":
                self._smudge_stamp(x, y, x0, y0)
            else:
                self._brush_stamp(x, y, erase=self._tool.name == "Erase")
            x0, y0 = x, y

    def _brush_stamp(self, x: float, y: float, *, erase: bool = False) -> None:
        radius = max(float(self._tool.size) * 0.5, 0.5)
        height, width = self.image.shape
        xmin = max(int(np.floor(x - radius - 1)), 0)
        xmax = min(int(np.ceil(x + radius + 1)), width)
        ymin = max(int(np.floor(y - radius - 1)), 0)
        ymax = min(int(np.ceil(y + radius + 1)), height)
        if xmin >= xmax or ymin >= ymax:
            return
        yy, xx = np.mgrid[ymin:ymax, xmin:xmax]
        dist = np.sqrt((xx - x) ** 2 + (yy - y) ** 2)
        softness = np.clip(float(self._tool.softness), 0.0, 1.0)
        inner = radius * (1.0 - softness)
        outer = radius
        if outer <= inner + 1e-6:
            mask = (dist <= outer).astype(np.float32)
        else:
            mask = np.clip((outer - dist) / max(outer - inner, 1e-6), 0.0, 1.0)
            mask[dist <= inner] = 1.0
        alpha = mask * np.clip(float(self._tool.opacity), 0.0, 1.0)
        region = self.image[ymin:ymax, xmin:xmax]
        value = self._background_value if erase else np.clip(float(self._tool.value), 0.0, 1.0)
        self.image[ymin:ymax, xmin:xmax] = region * (1.0 - alpha) + value * alpha

    def _smudge_stamp(self, x: float, y: float, source_x: float, source_y: float) -> None:
        radius = max(float(self._tool.size) * 0.5, 1.0)
        height, width = self.image.shape
        xmin = max(int(np.floor(x - radius - 1)), 0)
        xmax = min(int(np.ceil(x + radius + 1)), width)
        ymin = max(int(np.floor(y - radius - 1)), 0)
        ymax = min(int(np.ceil(y + radius + 1)), height)
        if xmin >= xmax or ymin >= ymax:
            return
        sxmin = max(int(np.floor(source_x - radius - 1)), 0)
        symin = max(int(np.floor(source_y - radius - 1)), 0)
        sxmax = min(sxmin + (xmax - xmin), width)
        symax = min(symin + (ymax - ymin), height)
        patch = self.image[symin:symax, sxmin:sxmax].copy()
        if patch.size == 0:
            return
        region = self.image[ymin:ymin + patch.shape[0], xmin:xmin + patch.shape[1]]
        yy, xx = np.mgrid[0:patch.shape[0], 0:patch.shape[1]]
        cy = patch.shape[0] * 0.5
        cx = patch.shape[1] * 0.5
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        mask = np.clip((radius - dist) / max(radius, 1e-6), 0.0, 1.0)
        alpha = mask * np.clip(float(self._tool.opacity), 0.0, 1.0)
        self.image[ymin:ymin + patch.shape[0], xmin:xmin + patch.shape[1]] = region * (1.0 - alpha) + patch * alpha

    def _apply_shape(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        if self._tool.name == "Line":
            self._stamp_or_smudge(start, end)
            return
        x0, y0 = start
        x1, y1 = end
        xmin = int(np.floor(min(x0, x1)))
        xmax = int(np.ceil(max(x0, x1))) + 1
        ymin = int(np.floor(min(y0, y1)))
        ymax = int(np.ceil(max(y0, y1))) + 1
        height, width = self.image.shape
        xmin = max(xmin, 0)
        ymin = max(ymin, 0)
        xmax = min(xmax, width)
        ymax = min(ymax, height)
        if xmin >= xmax or ymin >= ymax:
            return
        yy, xx = np.mgrid[ymin:ymax, xmin:xmax]
        if self._tool.name == "Rectangle":
            mask = np.ones((ymax - ymin, xmax - xmin), dtype=np.float32)
        else:
            cx = (xmin + xmax - 1) * 0.5
            cy = (ymin + ymax - 1) * 0.5
            rx = max((xmax - xmin) * 0.5, 1.0)
            ry = max((ymax - ymin) * 0.5, 1.0)
            mask = (((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1.0).astype(np.float32)
        alpha = mask * np.clip(float(self._tool.opacity), 0.0, 1.0)
        value = np.clip(float(self._tool.value), 0.0, 1.0)
        region = self.image[ymin:ymax, xmin:xmax]
        self.image[ymin:ymax, xmin:xmax] = region * (1.0 - alpha) + value * alpha


class CanvasPanel(QWidget):
    canvasChanged = Signal()
    createCanvasRequested = Signal()

    CANVAS_SIZES = (256, 512, 1024, 2048, 4096, 8192)
    TOOL_NAMES = ("Paint", "Erase", "Smudge", "Line", "Rectangle", "Ellipse")

    def __init__(self, scene: GraphScene, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.scene = scene
        self.node: NodeItem | None = None
        self._tool = _ToolState()
        self._committing_stroke = False
        self._stroke_before: _CanvasSnapshot | None = None
        self._history_by_node: dict[str, list[_CanvasSnapshot]] = {}
        self._history_index_by_node: dict[str, int] = {}
        self._history_limit = 32
        self._commit_timer = QTimer(self)
        self._commit_timer.setSingleShot(True)
        self._commit_timer.setInterval(120)
        self._commit_timer.timeout.connect(self._commit_preview_update)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.pages = QStackedWidget(self)
        layout.addWidget(self.pages)

        self.empty_page = QWidget(self.pages)
        empty_layout = QVBoxLayout(self.empty_page)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.addStretch(1)
        empty_title = QLabel("No Canvas node selected", self.empty_page)
        empty_title.setObjectName("sectionTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_title)
        empty_message = QLabel(
            "Select a Grayscale Canvas node in the graph, or create one to begin painting.",
            self.empty_page,
        )
        empty_message.setObjectName("muted")
        empty_message.setWordWrap(True)
        empty_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_message)
        self.create_canvas_button = QPushButton("Create Grayscale Canvas Node", self.empty_page)
        self.create_canvas_button.setMinimumWidth(220)
        self.create_canvas_button.clicked.connect(self.createCanvasRequested.emit)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.create_canvas_button)
        button_row.addStretch(1)
        empty_layout.addLayout(button_row)
        empty_layout.addStretch(1)
        self.pages.addWidget(self.empty_page)

        self.editor_page = QWidget(self.pages)
        editor_layout = QVBoxLayout(self.editor_page)
        editor_layout.setContentsMargins(8, 8, 8, 8)
        editor_layout.setSpacing(8)

        self.info = QLabel("Grayscale Canvas")
        self.info.setWordWrap(True)
        editor_layout.addWidget(self.info)

        view_row = QHBoxLayout()
        view_row.setSpacing(5)
        self.fit_button = QToolButton(self.editor_page)
        self.fit_button.setText("Fit")
        self.fit_button.setToolTip("Reset canvas zoom and pan")
        self.zoom_label = QLabel("100%", self.editor_page)
        self.zoom_label.setObjectName("muted")
        view_row.addWidget(self.fit_button)
        view_row.addWidget(self.zoom_label)
        view_row.addStretch(1)
        view_hint = QLabel("Wheel: zoom · middle-drag: pan", self.editor_page)
        view_hint.setObjectName("muted")
        view_row.addWidget(view_hint)
        editor_layout.addLayout(view_row)

        canvas_row = QHBoxLayout()
        canvas_row.setSpacing(6)
        tool_column = QVBoxLayout()
        tool_column.setSpacing(4)
        tool_column.setContentsMargins(0, 0, 0, 0)
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_buttons: dict[str, QToolButton] = {}
        for name in self.TOOL_NAMES:
            button = QToolButton(self.editor_page)
            button.setCheckable(True)
            button.setChecked(name == self._tool.name)
            button.setFixedSize(38, 38)
            button.setIcon(_tool_icon(name))
            button.setIconSize(QSize(21, 21))
            button.setToolTip(name)
            button.setAccessibleName(name)
            button.clicked.connect(lambda checked=False, tool_name=name: self._tool_changed(tool_name))
            self.tool_group.addButton(button)
            self.tool_buttons[name] = button
            tool_column.addWidget(button)
        tool_column.addStretch(1)
        canvas_row.addLayout(tool_column)

        self.paint_widget = CanvasPaintWidget(self.editor_page)
        self.paint_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.paint_widget.strokeStarted.connect(self._stroke_started)
        self.paint_widget.strokeUpdated.connect(self._stroke_updated)
        self.paint_widget.strokeFinished.connect(self._stroke_finished)
        self.paint_widget.zoomChanged.connect(self._zoom_changed)
        self.fit_button.clicked.connect(self.paint_widget.reset_view)
        canvas_row.addWidget(self.paint_widget, 1)
        editor_layout.addLayout(canvas_row, 1)

        controls = QFrame(self.editor_page)
        form = QFormLayout(controls)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)

        self.value_spin = QDoubleSpinBox(controls)
        self.value_spin.setRange(0.0, 1.0)
        self.value_spin.setDecimals(3)
        self.value_spin.setSingleStep(0.05)
        self.value_spin.setValue(self._tool.value)
        self.value_spin.valueChanged.connect(lambda value: self._set_tool_attr("value", float(value)))
        form.addRow("Value", self.value_spin)

        self.size_spin = QSpinBox(controls)
        self.size_spin.setRange(1, 512)
        self.size_spin.setValue(self._tool.size)
        self.size_spin.valueChanged.connect(lambda value: self._set_tool_attr("size", int(value)))
        form.addRow("Brush Size", self.size_spin)

        self.softness_spin = QDoubleSpinBox(controls)
        self.softness_spin.setRange(0.0, 1.0)
        self.softness_spin.setDecimals(2)
        self.softness_spin.setSingleStep(0.05)
        self.softness_spin.setValue(self._tool.softness)
        self.softness_spin.valueChanged.connect(lambda value: self._set_tool_attr("softness", float(value)))
        form.addRow("Softness", self.softness_spin)

        self.opacity_spin = QDoubleSpinBox(controls)
        self.opacity_spin.setRange(0.0, 1.0)
        self.opacity_spin.setDecimals(2)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setValue(self._tool.opacity)
        self.opacity_spin.valueChanged.connect(lambda value: self._set_tool_attr("opacity", float(value)))
        form.addRow("Opacity", self.opacity_spin)

        size_row = QHBoxLayout()
        self.size_combo = QComboBox(controls)
        self.resize_button = QPushButton("Resize", controls)
        self.resize_button.clicked.connect(self._resize_canvas)
        size_row.addWidget(self.size_combo, 1)
        size_row.addWidget(self.resize_button)
        form.addRow("Native Size", _wrap_layout(size_row))

        action_row = QHBoxLayout()
        self.clear_button = QPushButton("Clear to Black", controls)
        self.clear_button.clicked.connect(self._clear_canvas)
        action_row.addWidget(self.clear_button)
        self.refresh_button = QPushButton("Reload From Node", controls)
        self.refresh_button.clicked.connect(self._reload_current_canvas)
        action_row.addWidget(self.refresh_button)
        action_row.addStretch(1)
        form.addRow("Actions", _wrap_layout(action_row))
        editor_layout.addWidget(controls)

        self.pages.addWidget(self.editor_page)
        self.pages.setCurrentWidget(self.empty_page)
        self._apply_tool_state()

    def refresh_theme(self) -> None:
        for name, button in self.tool_buttons.items():
            button.setIcon(_tool_icon(name))

    def set_scene(self, scene: GraphScene) -> None:
        if scene is self.scene:
            return
        self._commit_timer.stop()
        self.scene = scene
        self.set_item(None)

    def set_item(self, item) -> None:
        node = item if isinstance(item, NodeItem) and item.definition.type_id == "input.canvas" else None
        self.node = node
        live_uids = set(self.scene.nodes)
        for uid in tuple(self._history_by_node):
            if uid not in live_uids:
                self._history_by_node.pop(uid, None)
                self._history_index_by_node.pop(uid, None)
        if node is None:
            self._commit_timer.stop()
            self._committing_stroke = False
            self._stroke_before = None
            self.pages.setCurrentWidget(self.empty_page)
            return
        self._reload_current_canvas()
        self._ensure_history_matches_node()

    def _reload_current_canvas(self) -> None:
        if self.node is None:
            return
        params = ensure_canvas_parameters({**self.node.parameters, "background_value": 0.0})
        params["background_value"] = 0.0
        self.node.parameters.update(params)
        array = canvas_array_from_params(params)
        width = int(params.get("canvas_width", array.shape[1]))
        height = int(params.get("canvas_height", array.shape[0]))
        self._set_size_options(width, height)
        self.paint_widget.set_canvas(array, background_value=0.0, reset_view=True)
        self.info.setText(
            f"{self.node.definition.name} · native {array.shape[1]} × {array.shape[0]} greyscale source. Copying this node duplicates its embedded image data; deleting the node removes it from the graph file."
        )
        self.pages.setCurrentWidget(self.editor_page)

    def _set_size_options(self, width: int, height: int) -> None:
        current = (max(int(width), 1), max(int(height), 1))
        self.size_combo.blockSignals(True)
        self.size_combo.clear()
        standard_sizes = [(size, size) for size in self.CANVAS_SIZES]
        if current not in standard_sizes:
            self.size_combo.addItem(f"Current: {current[0]} × {current[1]}", current)
        for size in self.CANVAS_SIZES:
            self.size_combo.addItem(f"{size} × {size}", (size, size))
        for index in range(self.size_combo.count()):
            data = self.size_combo.itemData(index)
            if isinstance(data, (tuple, list)) and tuple(data) == current:
                self.size_combo.setCurrentIndex(index)
                break
        self.size_combo.blockSignals(False)

    def _capture_snapshot(self) -> _CanvasSnapshot | None:
        if self.node is None:
            return None
        return _CanvasSnapshot(
            data=encode_canvas_array(self.paint_widget.image),
            width=int(self.paint_widget.image.shape[1]),
            height=int(self.paint_widget.image.shape[0]),
        )

    def _node_snapshot(self) -> _CanvasSnapshot | None:
        if self.node is None:
            return None
        params = ensure_canvas_parameters({**self.node.parameters, "background_value": 0.0})
        return _CanvasSnapshot(
            data=str(params.get("_canvas_data", "")),
            width=int(params.get("canvas_width", 1024)),
            height=int(params.get("canvas_height", 1024)),
        )

    def _ensure_history_matches_node(self) -> None:
        if self.node is None:
            return
        current = self._node_snapshot()
        if current is None:
            return
        history = self._history_by_node.get(self.node.uid)
        index = self._history_index_by_node.get(self.node.uid, -1)
        if history is None or not (0 <= index < len(history)) or history[index] != current:
            self._history_by_node[self.node.uid] = [current]
            self._history_index_by_node[self.node.uid] = 0

    def _push_history(self, before: _CanvasSnapshot | None, after: _CanvasSnapshot | None) -> None:
        if self.node is None or before is None or after is None or before == after:
            return
        uid = self.node.uid
        history = list(self._history_by_node.get(uid, [before]))
        index = int(self._history_index_by_node.get(uid, len(history) - 1))
        history = history[: max(index + 1, 0)]
        if not history or history[-1] != before:
            history.append(before)
        history.append(after)
        if len(history) > self._history_limit:
            overflow = len(history) - self._history_limit
            history = history[overflow:]
        self._history_by_node[uid] = history
        self._history_index_by_node[uid] = len(history) - 1

    def can_undo_canvas(self) -> bool:
        if self.node is None:
            return False
        return self._history_index_by_node.get(self.node.uid, 0) > 0

    def can_redo_canvas(self) -> bool:
        if self.node is None:
            return False
        history = self._history_by_node.get(self.node.uid, ())
        return self._history_index_by_node.get(self.node.uid, 0) < len(history) - 1

    def undo_canvas(self) -> bool:
        if not self.can_undo_canvas() or self.node is None:
            return False
        uid = self.node.uid
        index = self._history_index_by_node[uid] - 1
        self._history_index_by_node[uid] = index
        self._apply_snapshot(self._history_by_node[uid][index])
        self.paint_widget.setFocus(Qt.FocusReason.ShortcutFocusReason)
        return True

    def redo_canvas(self) -> bool:
        if not self.can_redo_canvas() or self.node is None:
            return False
        uid = self.node.uid
        index = self._history_index_by_node[uid] + 1
        self._history_index_by_node[uid] = index
        self._apply_snapshot(self._history_by_node[uid][index])
        self.paint_widget.setFocus(Qt.FocusReason.ShortcutFocusReason)
        return True

    def _apply_snapshot(self, snapshot: _CanvasSnapshot) -> None:
        if self.node is None:
            return
        from ..canvas_node import decode_canvas_array

        image = decode_canvas_array(snapshot.data)
        size_changed = image.shape != self.paint_widget.image.shape
        self._set_size_options(snapshot.width, snapshot.height)
        self.paint_widget.set_canvas(image, background_value=0.0, reset_view=size_changed)
        self.node.parameters["canvas_width"] = snapshot.width
        self.node.parameters["canvas_height"] = snapshot.height
        self.node.parameters["background_value"] = 0.0
        self.node.parameters["_canvas_data"] = snapshot.data
        self.node.parameters["_canvas_revision"] = time.time_ns()
        self.scene._touch()
        self.canvasChanged.emit()

    def _tool_changed(self, text: str) -> None:
        self._tool.name = str(text)
        self._apply_tool_state()

    def _zoom_changed(self, zoom: float) -> None:
        self.zoom_label.setText(f"{max(float(zoom), 0.0) * 100.0:.0f}%")

    def _set_tool_attr(self, name: str, value) -> None:
        setattr(self._tool, name, value)
        self._apply_tool_state()

    def _apply_tool_state(self) -> None:
        self.paint_widget.set_tool_state(self._tool)

    def _stroke_started(self) -> None:
        if self.node is None:
            return
        self._ensure_history_matches_node()
        self._stroke_before = self._capture_snapshot()
        self._committing_stroke = True
        self._commit_preview_update()

    def _stroke_updated(self) -> None:
        if not self._committing_stroke:
            return
        self._commit_timer.start()

    def _stroke_finished(self) -> None:
        if self.node is None or not self._committing_stroke:
            return
        self._commit_timer.stop()
        self._commit_preview_update()
        after = self._capture_snapshot()
        self._push_history(self._stroke_before, after)
        self._stroke_before = None
        self._committing_stroke = False

    def _commit_preview_update(self) -> None:
        if self.node is None:
            return
        self.node.parameters["canvas_width"] = int(self.paint_widget.image.shape[1])
        self.node.parameters["canvas_height"] = int(self.paint_widget.image.shape[0])
        self.node.parameters["background_value"] = 0.0
        self.node.parameters["_canvas_data"] = encode_canvas_array(self.paint_widget.image)
        self.node.parameters["_canvas_revision"] = time.time_ns()
        self.scene._touch()
        self.canvasChanged.emit()
        # Live preview while a stroke is open should update downstream nodes
        # without closing the enclosing undo step.
        if self._committing_stroke:
            self.scene.graphChanged.emit()

    def _resize_canvas(self) -> None:
        if self.node is None:
            return
        before = self._capture_snapshot()
        selected = self.size_combo.currentData()
        if not isinstance(selected, (tuple, list)) or len(selected) != 2:
            return
        width = int(selected[0])
        height = int(selected[1])
        current = self.paint_widget.image
        resized = resize_canvas_array(current, width, height)
        self.paint_widget.set_canvas(resized, background_value=0.0, reset_view=True)
        self._commit_preview_update()
        self._push_history(before, self._capture_snapshot())
        self.paint_widget.setFocus(Qt.FocusReason.OtherFocusReason)

    def _clear_canvas(self) -> None:
        if self.node is None:
            return
        before = self._capture_snapshot()
        height, width = self.paint_widget.image.shape
        self.paint_widget.set_canvas(np.zeros((height, width), dtype=np.float32), background_value=0.0)
        self._commit_preview_update()
        self._push_history(before, self._capture_snapshot())
        self.paint_widget.setFocus(Qt.FocusReason.OtherFocusReason)


def _wrap_layout(layout: QHBoxLayout) -> QWidget:
    wrapper = QWidget()
    wrapper.setLayout(layout)
    return wrapper


def _tool_icon(name: str) -> QIcon:
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(
        QColor(theme_colour("text", "#d6dbe5")),
        2.0,
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    )
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if name == "Paint":
        painter.drawLine(QPointF(6.0, 18.0), QPointF(17.0, 7.0))
        painter.drawEllipse(QPointF(18.2, 5.8), 2.3, 2.3)
        painter.drawLine(QPointF(5.0, 19.0), QPointF(9.0, 18.0))
    elif name == "Erase":
        path = QPainterPath()
        path.moveTo(6.0, 16.0)
        path.lineTo(13.0, 7.0)
        path.lineTo(19.0, 12.0)
        path.lineTo(12.0, 20.0)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(QPointF(5.0, 20.0), QPointF(18.0, 20.0))
    elif name == "Smudge":
        path = QPainterPath(QPointF(5.0, 8.0))
        path.cubicTo(10.0, 4.0, 12.0, 12.0, 18.0, 8.0)
        path.moveTo(5.0, 13.0)
        path.cubicTo(10.0, 9.0, 12.0, 17.0, 19.0, 13.0)
        path.moveTo(6.0, 18.0)
        path.cubicTo(10.0, 15.0, 13.0, 21.0, 18.0, 17.0)
        painter.drawPath(path)
    elif name == "Line":
        painter.drawLine(QPointF(5.0, 19.0), QPointF(19.0, 5.0))
    elif name == "Rectangle":
        painter.drawRect(QRectF(5.0, 6.0, 14.0, 12.0))
    elif name == "Ellipse":
        painter.drawEllipse(QRectF(5.0, 6.0, 14.0, 12.0))

    painter.end()
    return QIcon(pixmap)
