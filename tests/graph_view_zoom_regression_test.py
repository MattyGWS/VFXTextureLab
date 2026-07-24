from __future__ import annotations

import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.graph.scene import GraphScene
from vfx_texture_lab.graph.view import GraphView
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.ui.node_preferences import NodePreferences


class _WheelEvent:
    def __init__(self, *, angle_y: int = 0, pixel_y: int = 0) -> None:
        self._angle = QPoint(0, angle_y)
        self._pixel = QPoint(0, pixel_y)
        self.accepted = False
        self.ignored = False

    def angleDelta(self) -> QPoint:
        return self._angle

    def pixelDelta(self) -> QPoint:
        return self._pixel

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.ignored = True


def _scale(view: GraphView) -> float:
    return abs(float(view.transform().m11()))


def main() -> None:
    app = QApplication.instance() or QApplication([])
    scene = GraphScene(build_registry())
    view = GraphView(scene, NodePreferences())
    view.resize(1000, 600)
    view.show()
    app.processEvents()

    # Opening a wide graph can legitimately fit below the normal interactive
    # minimum. Wheel-in must still increase the scale rather than doing nothing.
    view.setTransform(QTransform.fromScale(0.10, 0.10))
    before = _scale(view)
    event = _WheelEvent(angle_y=120)
    view.wheelEvent(event)
    assert event.accepted
    assert _scale(view) > before
    assert _scale(view) < view.MIN_ZOOM_SCALE

    # Repeated wheel-in steps must recover all the way into the normal range.
    for _index in range(8):
        view.wheelEvent(_WheelEvent(angle_y=120))
    assert _scale(view) > view.MIN_ZOOM_SCALE

    # The inverse case can be produced by fitting a tiny selection. Wheel-out
    # must recover from above the ordinary maximum as well.
    view.setTransform(QTransform.fromScale(5.0, 5.0))
    before = _scale(view)
    view.wheelEvent(_WheelEvent(angle_y=-120))
    assert _scale(view) < before
    assert _scale(view) > view.MAX_ZOOM_SCALE

    # Bounds prevent movement farther out, without creating a dead state in the
    # direction that returns toward the supported range.
    view.setTransform(QTransform.fromScale(view.MIN_ZOOM_SCALE, view.MIN_ZOOM_SCALE))
    view.wheelEvent(_WheelEvent(angle_y=-120))
    assert math.isclose(_scale(view), view.MIN_ZOOM_SCALE, rel_tol=0.0, abs_tol=1.0e-9)
    view.wheelEvent(_WheelEvent(angle_y=120))
    assert _scale(view) > view.MIN_ZOOM_SCALE

    view.setTransform(QTransform.fromScale(view.MAX_ZOOM_SCALE, view.MAX_ZOOM_SCALE))
    view.wheelEvent(_WheelEvent(angle_y=120))
    assert math.isclose(_scale(view), view.MAX_ZOOM_SCALE, rel_tol=0.0, abs_tol=1.0e-9)
    view.wheelEvent(_WheelEvent(angle_y=-120))
    assert _scale(view) < view.MAX_ZOOM_SCALE

    # Pixel-only high-resolution scroll input is supported, while a truly empty
    # event is ignored rather than being interpreted as zoom-out.
    before = _scale(view)
    view.wheelEvent(_WheelEvent(pixel_y=24))
    assert _scale(view) > before
    before = _scale(view)
    empty = _WheelEvent()
    view.wheelEvent(empty)
    assert empty.ignored
    assert math.isclose(_scale(view), before, rel_tol=0.0, abs_tol=1.0e-9)

    # Even a degenerate transform recovers to a finite, usable scale.
    view.setTransform(QTransform.fromScale(0.0, 0.0))
    view.wheelEvent(_WheelEvent(angle_y=120))
    assert math.isfinite(_scale(view))
    assert _scale(view) > 0.0

    print(
        "graph view zoom regression test passed: fitted large/tiny graphs recover "
        "in the correct wheel direction and pixel-only scrolling remains usable"
    )


if __name__ == "__main__":
    main()
