from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QDoubleSpinBox,
    QSpinBox,
    QStyle,
    QStyleOptionSpinBox,
)


class _VisibleArrowMixin:
    """Paint visible arrows and provide shared modifier-aware stepping.

    Some Qt platform/theme combinations reserve the up/down button subcontrols
    but render no visible glyphs. Keeping the native subcontrols preserves mouse
    repeat, wheel and keyboard behaviour; this mixin only makes their purpose
    visible. Numeric parameter editors can additionally supply fine/coarse
    interaction steps: Ctrl uses the fine step and Shift uses the coarse step.
    """

    _fine_interaction_step: float | int | None = None
    _coarse_interaction_step: float | int | None = None

    def setInteractionSteps(self, fine: float | int | None, coarse: float | int | None) -> None:
        self._fine_interaction_step = fine
        self._coarse_interaction_step = coarse

    def stepBy(self, steps: int) -> None:
        modifiers = QApplication.keyboardModifiers()
        chosen = None
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            chosen = self._coarse_interaction_step
        elif modifiers & Qt.KeyboardModifier.ControlModifier:
            chosen = self._fine_interaction_step
        if chosen is None or float(chosen) <= 0.0:
            super().stepBy(steps)
            return
        original = self.singleStep()
        try:
            self.setSingleStep(chosen)
            super().stepBy(steps)
        finally:
            self.setSingleStep(original)

    def _paint_spin_arrows(self) -> None:
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        style = self.style()
        up_rect = style.subControlRect(
            QStyle.ComplexControl.CC_SpinBox,
            option,
            QStyle.SubControl.SC_SpinBoxUp,
            self,
        )
        down_rect = style.subControlRect(
            QStyle.ComplexControl.CC_SpinBox,
            option,
            QStyle.SubControl.SC_SpinBoxDown,
            self,
        )
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colour = self.palette().color(self.foregroundRole())
        if not self.isEnabled():
            colour.setAlpha(90)
        else:
            colour.setAlpha(205)
        painter.setPen(QPen(colour, 1.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))

        def chevron(rect, upward: bool) -> None:
            if rect.width() < 5 or rect.height() < 4:
                return
            cx = rect.center().x()
            cy = rect.center().y()
            half = min(3.0, max(rect.width() * 0.18, 1.8))
            rise = min(2.0, max(rect.height() * 0.18, 1.2))
            if upward:
                points = (QPointF(cx - half, cy + rise), QPointF(cx, cy - rise), QPointF(cx + half, cy + rise))
            else:
                points = (QPointF(cx - half, cy - rise), QPointF(cx, cy + rise), QPointF(cx + half, cy - rise))
            painter.drawPolyline(QPolygonF(points))

        chevron(up_rect, True)
        chevron(down_rect, False)
        painter.end()


class CompactSpinBox(_VisibleArrowMixin, QSpinBox):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)
        self.setKeyboardTracking(False)
        self.setCorrectionMode(QAbstractSpinBox.CorrectionMode.CorrectToNearestValue)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        self._paint_spin_arrows()


class CompactDoubleSpinBox(_VisibleArrowMixin, QDoubleSpinBox):
    """A precise float editor that does not pad ordinary values with zeroes.

    ``decimals`` remains the maximum accepted precision. Display text trims
    redundant trailing zeroes while retaining one decimal place so artists can
    still distinguish float controls from integer controls. Keyboard tracking is
    disabled, preventing the widget from reformatting partially typed numbers.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)
        self.setKeyboardTracking(False)
        self.setCorrectionMode(QAbstractSpinBox.CorrectionMode.CorrectToNearestValue)

    def textFromValue(self, value: float) -> str:
        if not math.isfinite(value):
            return super().textFromValue(value)
        decimals = max(int(self.decimals()), 0)
        text = f"{value:.{decimals}f}" if decimals else f"{value:.0f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        if decimals > 0 and "." not in text:
            text += ".0"
        # Avoid the visually confusing negative zero produced by formatting
        # values very close to zero.
        if text in {"-0", "-0.0"}:
            text = "0.0" if decimals > 0 else "0"
        return text

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        self._paint_spin_arrows()
