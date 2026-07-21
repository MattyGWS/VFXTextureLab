from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..histogram import HISTOGRAM_INTERNAL_BINS, aggregate_histogram

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QMenu, QSizePolicy, QWidget


@dataclass(frozen=True)
class VisualEditorPalette:
    """Shared colours and dimensions for graphical parameter editors.

    The editor family deliberately uses one small palette instead of embedding
    slightly different greys and hit sizes in every node-specific widget.  It
    keeps histogram, curve and gradient controls visually related while still
    allowing each editor to draw its own data.
    """

    background: str = "#171b20"
    background_alt: str = "#11151a"
    frame: str = "#59616d"
    grid: str = "#303640"
    axis: str = "#4a525f"
    text: str = "#89919c"
    muted: str = "#8d95a2"
    curve: str = "#d4d9e1"
    histogram_fill: str = "#89919b"
    histogram_line: str = "#b8bec7"
    selected: str = "#8da7e8"
    hover: str = "#c4d2f5"
    handle: str = "#aeb5c0"
    handle_border: str = "#555e6b"
    selected_border: str = "#f2f4f7"


PALETTE = VisualEditorPalette()


class VisualEditorCanvas(QWidget):
    """Common interaction and rendering foundation for visual parameters.

    Subclasses keep ownership of their actual value model.  This base provides:

    * predictable fixed-height sizing;
    * mouse capture for uninterrupted drags;
    * a debounced live-edit signal and a guaranteed final flush;
    * interaction boundaries used by the graph undo transaction system;
    * shared context-menu hooks and grid state;
    * consistent keyboard step sizes and drawing helpers.
    """

    valueEdited = Signal(object)
    interactionStarted = Signal()
    interactionFinished = Signal()
    gridVisibilityChanged = Signal(bool)

    def __init__(
        self,
        *,
        editor_height: int,
        debounce_ms: int = 38,
        supports_grid: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._supports_grid = bool(supports_grid)
        self._grid_visible = True
        self._interaction_active = False
        self._pending_value: Any = None
        self._has_pending_value = False
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(max(int(debounce_ms), 0))
        self._debounce_timer.timeout.connect(self.flush_edited_value)

        self.setFixedHeight(int(editor_height))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ------------------------------------------------------------------
    # Shared edit lifecycle
    # ------------------------------------------------------------------
    @property
    def interaction_active(self) -> bool:
        return self._interaction_active

    @property
    def grid_visible(self) -> bool:
        return self._grid_visible

    def set_grid_visible(self, visible: bool) -> None:
        visible = bool(visible)
        if self._grid_visible == visible:
            return
        self._grid_visible = visible
        self.gridVisibilityChanged.emit(visible)
        self.update()

    def begin_interaction(self) -> None:
        if self._interaction_active:
            return
        self._interaction_active = True
        # QWidget already receives an implicit mouse grab after a press, but an
        # explicit grab makes editor drags dependable across child boundaries.
        if self.isVisible():
            try:
                self.grabMouse()
            except RuntimeError:
                pass
        self.interactionStarted.emit()

    def queue_edited_value(self, value: Any, *, immediate: bool = False) -> None:
        self._pending_value = deepcopy(value)
        self._has_pending_value = True
        if immediate or not self._interaction_active or self._debounce_timer.interval() <= 0:
            self.flush_edited_value()
            return
        if not self._debounce_timer.isActive():
            self._debounce_timer.start()

    def flush_edited_value(self) -> None:
        if not self._has_pending_value:
            return
        value = self._pending_value
        self._pending_value = None
        self._has_pending_value = False
        self._debounce_timer.stop()
        self.valueEdited.emit(value)

    def end_interaction(self) -> None:
        if not self._interaction_active:
            return
        # Always publish the exact final handle position before closing the undo
        # transaction, even when the debounce timer has not fired yet.
        self.flush_edited_value()
        self._interaction_active = False
        try:
            if self.mouseGrabber() is self:
                self.releaseMouse()
        except RuntimeError:
            pass
        self.interactionFinished.emit()

    def cancel_interaction(self) -> None:
        """Close a drag safely if the editor is rebuilt or loses focus."""
        self.end_interaction()

    @staticmethod
    def keyboard_step(event, *, normal: float = 0.01, fine: float = 0.001, coarse: float = 0.1) -> float:
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            return float(fine)
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            return float(coarse)
        return float(normal)

    # ------------------------------------------------------------------
    # Shared context menu
    # ------------------------------------------------------------------
    def can_reset(self) -> bool:
        return False

    def reset_to_default(self) -> None:
        pass

    def populate_context_menu(self, menu: QMenu) -> None:
        if self.can_reset():
            reset = menu.addAction("Reset")
            reset.triggered.connect(self.reset_to_default)
        if self._supports_grid:
            grid = menu.addAction("Show Grid")
            grid.setCheckable(True)
            grid.setChecked(self._grid_visible)
            grid.toggled.connect(self.set_grid_visible)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        self.populate_context_menu(menu)
        if menu.actions():
            menu.exec(event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    def hideEvent(self, event) -> None:
        self.cancel_interaction()
        super().hideEvent(event)

    # ------------------------------------------------------------------
    # Shared rendering helpers
    # ------------------------------------------------------------------
    @staticmethod
    def draw_editor_background(
        painter: QPainter,
        rect: QRectF,
        *,
        neutral_ramp: bool = False,
    ) -> None:
        painter.fillRect(rect, QColor(PALETTE.background))
        if neutral_ramp:
            ramp = QLinearGradient(rect.left(), 0.0, rect.right(), 0.0)
            ramp.setColorAt(0.0, QColor(12, 14, 17, 160))
            ramp.setColorAt(1.0, QColor(245, 247, 250, 52))
            painter.fillRect(rect, ramp)

    @staticmethod
    def draw_frame(painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QPen(QColor(PALETTE.frame), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

    @staticmethod
    def draw_grid(painter: QPainter, rect: QRectF, *, divisions: int = 4) -> None:
        if divisions <= 1:
            return
        painter.setPen(QPen(QColor(PALETTE.grid), 1.0))
        for index in range(1, divisions):
            amount = index / float(divisions)
            x = rect.left() + rect.width() * amount
            y = rect.top() + rect.height() * amount
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

    @staticmethod
    def draw_checkerboard(painter: QPainter, rect: QRectF, *, square: int = 8) -> None:
        top = int(rect.top())
        left = int(rect.left())
        right = int(rect.right()) + 1
        bottom = int(rect.bottom()) + 1
        for y in range(top, bottom, square):
            for x in range(left, right, square):
                light = ((x - left) // square + (y - top) // square) % 2 == 0
                painter.fillRect(x, y, square, square, QColor("#343942" if light else "#252a31"))

    @staticmethod
    def normalise_histogram(
        histogram: np.ndarray | None,
        bins: int | None = None,
    ) -> np.ndarray:
        target = HISTOGRAM_INTERNAL_BINS if bins is None else max(int(bins), 1)
        if histogram is None:
            return np.zeros(target, dtype=np.float64)
        data = np.maximum(np.asarray(histogram, dtype=np.float64).reshape(-1), 0.0)
        if data.size == 0:
            return np.zeros(target, dtype=np.float64)
        if bins is not None and data.size != target:
            return aggregate_histogram(data, target)
        return np.ascontiguousarray(data, dtype=np.float64)

    @staticmethod
    def draw_histogram(
        painter: QPainter,
        rect: QRectF,
        histogram: np.ndarray,
        *,
        status_text: str = "",
        underflow: int = 0,
        overflow: int = 0,
    ) -> None:
        data = np.maximum(np.asarray(histogram, dtype=np.float64).reshape(-1), 0.0)
        target_bins = max(min(int(rect.width()), data.size), 1) if data.size else 1
        display = aggregate_histogram(data, target_bins) if data.size else data
        maximum = float(np.max(display)) if display.size else 0.0
        if maximum <= 0.0:
            if status_text:
                painter.setPen(QColor(PALETTE.muted))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, status_text)
        else:
            # A conventional linear-frequency histogram: vertical height is
            # directly proportional to pixel population.  Half-bin padding and
            # a stepped silhouette make the graph return cleanly to zero at
            # both range boundaries instead of drawing vertical endpoint walls.
            heights = display / maximum
            half_bin_padding = max(rect.width() / max(display.size, 1) * 0.5, 0.75)
            inner = rect.adjusted(half_bin_padding, 0.0, -half_bin_padding, 0.0)
            bin_width = inner.width() / max(display.size, 1)
            path = QPainterPath(QPointF(rect.left(), rect.bottom()))
            path.lineTo(inner.left(), rect.bottom())
            for index, amount in enumerate(heights):
                left = inner.left() + index * bin_width
                right = inner.left() + (index + 1) * bin_width
                y = rect.bottom() - float(amount) * rect.height()
                path.lineTo(left, y)
                path.lineTo(right, y)
            path.lineTo(inner.right(), rect.bottom())
            path.lineTo(rect.right(), rect.bottom())
            path.closeSubpath()
            painter.fillPath(path, QColor(PALETTE.histogram_fill))
            painter.setPen(QPen(QColor(PALETTE.histogram_line), 1.0))
            painter.drawPath(path)

        # Out-of-range pixels are deliberately not stuffed into the endpoint
        # bins.  Small edge ticks disclose their presence without distorting the
        # 0..1 distribution used for Levels decisions.
        indicator = QColor(PALETTE.selected)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(indicator)
        if int(underflow) > 0:
            painter.drawRect(QRectF(rect.left(), rect.top(), 2.5, rect.height()))
        if int(overflow) > 0:
            painter.drawRect(QRectF(rect.right() - 2.5, rect.top(), 2.5, rect.height()))

    @staticmethod
    def triangle(x: float, y: float, *, upward: bool, size: float = 7.0) -> QPolygonF:
        depth = size * 1.57
        if upward:
            return QPolygonF(
                [QPointF(x, y), QPointF(x - size, y + depth), QPointF(x + size, y + depth)]
            )
        return QPolygonF(
            [QPointF(x, y), QPointF(x - size, y - depth), QPointF(x + size, y - depth)]
        )

    @staticmethod
    def draw_square_handle(
        painter: QPainter,
        centre: QPointF,
        *,
        selected: bool = False,
        hovered: bool = False,
        size: float = 8.0,
    ) -> None:
        if selected:
            fill = QColor(PALETTE.selected)
            border = QColor(PALETTE.selected_border)
            draw_size = size + 2.0
        elif hovered:
            fill = QColor(PALETTE.hover)
            border = QColor(PALETTE.selected_border)
            draw_size = size + 1.0
        else:
            fill = QColor(PALETTE.handle)
            border = QColor(PALETTE.handle_border)
            draw_size = size
        rect = QRectF(
            centre.x() - draw_size * 0.5,
            centre.y() - draw_size * 0.5,
            draw_size,
            draw_size,
        )
        painter.fillRect(rect, fill)
        painter.setPen(QPen(border, 1.0))
        painter.drawRect(rect)


__all__ = ["PALETTE", "VisualEditorCanvas", "VisualEditorPalette"]
