from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPointF, QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.main_window import MainWindow


def pump(app: QApplication, seconds: float) -> None:
    deadline = time.perf_counter() + max(float(seconds), 0.0)
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.003)


def make_window() -> MainWindow:
    QCoreApplication.setOrganizationName("VFXTextureLabTestsFlipbookDecodePlayback")
    QCoreApplication.setApplicationName("FlipbookDecodePlaybackRegression")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        tempfile.mkdtemp(prefix="vfx-flipbook-decode-playback-"),
    )
    window = MainWindow()
    window.document.width = 64
    window.document.height = 64
    window.document.preview_max_dimension = 64
    window.document.frames_per_second = 24.0
    window.document.duration_seconds = 2.0
    window.document.loop_start_frame = 0
    window.document.loop_end_frame = 47
    window.document.normalise()
    window.timeline_panel.set_document(window.document)
    window.timeline_panel.set_playback_mode("Real-time")

    window.scene.clear_graph(record_undo=False)
    time_node = window.scene.create_node("signal.time", QPointF(-620, 0), record_undo=False)
    value = window.scene.create_node("generator.constant", QPointF(-380, 0), record_undo=False)
    generator = window.scene.create_node("output.flipbook", QPointF(-120, 0), record_undo=False)
    decoder = window.scene.create_node("animation.flipbook_decode", QPointF(180, 0), record_undo=False)

    generator.parameters.update({
        "layout": "2 × 2",
        "source_range": "Document Loop",
        "sampling": "Evenly Across Range",
        "use_full_grid": True,
    })
    window.scene.set_parameter_socket_exposed(value, "value", True)
    window.scene.add_connection(
        time_node.output_ports["Loop Phase"],
        value.input_ports["@param:value"],
        record_undo=False,
    )
    window.scene.add_connection(value.output_port, generator.input_ports["Image"], record_undo=False)
    window.scene.add_connection(generator.output_port, decoder.input_ports["Sheet"], record_undo=False)
    window.scene.set_active_node(decoder)
    return window


def main() -> None:
    app = QApplication.instance() or QApplication([])
    window = make_window()
    observed: list[float] = []
    original_present = window._present_playback_result

    def capture(result) -> None:
        image = getattr(result, "image", None)
        display = getattr(result, "display_rgba", None)
        if image is not None:
            observed.append(round(float(image[0, 0, 0]), 4))
        elif display is not None:
            observed.append(int(display[0, 0, 0]))
        original_present(result)

    window._present_playback_result = capture
    window._set_playing(True)
    pump(app, 1.25)

    assert window._playback_presented_frames >= 2, (
        "A decoder connected directly to Flipbook Generator did not present playback frames"
    )
    assert len(set(observed)) >= 2, f"Decoded playback remained static: {observed}"
    assert window.current_frame > 0
    assert not window._uses_cached_flipbook_decode_playback(), (
        "Direct Flipbook Generator decoding must use frame-ahead evaluation, not cached-atlas slicing"
    )

    window._playing = False
    window.playback_timer.stop()
    window.playback_controller.cancel()
    window.eval_controller.cancel()
    window.material_controller.cancel()
    pump(app, 0.05)
    print(
        "flipbook decode playback regression test passed: direct Flipbook Generator output "
        "uses frame-ahead evaluation and presents changing decoded cells while playing"
    )


if __name__ == "__main__":
    main()
