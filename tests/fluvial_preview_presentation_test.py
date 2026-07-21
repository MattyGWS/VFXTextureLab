from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.engine.evaluator import EvaluationResult
from vfx_texture_lab.main_window import MainWindow


def main() -> int:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.preview_timer.stop()
    window.material_preview_timer.stop()
    window.graph_asset_watch_timer.stop()

    image = np.zeros((32, 32, 4), dtype=np.float32)
    y, x = np.mgrid[0:32, 0:32]
    terrain = np.clip(0.2 + x / 48.0 + 0.1 * np.sin(y * 0.5), 0.0, 1.0)
    image[..., :3] = terrain[..., None]
    image[..., 3] = 1.0
    broken_display = np.zeros((16, 16, 4), dtype=np.uint8)
    broken_display[..., 3] = 255
    result = EvaluationResult(
        image=image,
        display_rgba=broken_display,
        source_width=32,
        source_height=32,
        data_kind="grayscale",
    )
    window._pending_display_size = (16, 16)
    repaired = window._validated_preview_result(result)
    assert repaired.display_rgba is not None
    assert np.any(repaired.display_rgba[..., :3])
    assert repaired.display_rgba.shape == (16, 16, 4)

    # A genuinely black graph remains black; black itself is never treated as an error.
    black_image = np.zeros_like(image)
    black_image[..., 3] = 1.0
    legitimate = replace(result, image=black_image)
    unchanged = window._validated_preview_result(legitimate)
    assert np.array_equal(unchanged.display_rgba, broken_display)

    # A valid already prepared frame is reused verbatim.
    valid = replace(result, display_rgba=repaired.display_rgba.copy())
    reused = window._validated_preview_result(valid)
    assert reused.display_rgba is valid.display_rgba

    window._document_dirty = False
    window._recovered_dirty = False
    window.scene.undo_stack.setClean()
    window._set_dirty(False)
    window.close()
    QApplication.processEvents()
    print("fluvial preview presentation test passed: mismatched black readbacks repair from the valid full result without rejecting legitimate black outputs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
