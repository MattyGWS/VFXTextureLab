from __future__ import annotations

import tempfile
import time

from PySide6.QtCore import QPointF, QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.main_window import MainWindow


def pump(app: QApplication, seconds: float) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.004)


def main() -> None:
    app = QApplication.instance() or QApplication([])
    QCoreApplication.setOrganizationName("VFXTextureLabTestsAperturePlayback")
    QCoreApplication.setApplicationName("AnimationAperturePlayback")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        tempfile.mkdtemp(prefix="vfx-animation-aperture-"),
    )

    window = MainWindow()
    window.document.width = 32
    window.document.height = 32
    window.document.preview_max_dimension = 32
    window.document.frames_per_second = 12.0
    window.document.duration_seconds = 2.0
    window.document.loop_start_frame = 0
    window.document.loop_end_frame = 23
    window.document.normalise()
    window.timeline_panel.set_document(window.document)
    window.timeline_panel.set_playback_mode("Real-time")
    window.timeline_panel.set_profiler_enabled(False)

    window.scene.clear_graph(record_undo=False)
    time_node = window.scene.create_node("signal.time", QPointF(0, 0), record_undo=False)
    ridge = window.scene.create_node("noise.ridged", QPointF(220, 0), record_undo=False)
    aperture = window.scene.create_node("filter.aperture", QPointF(440, 0), record_undo=False)
    output = window.scene.create_node("output.image", QPointF(660, 0), record_undo=False)
    aperture.parameters["size"] = 2
    window.scene.set_parameter_socket_exposed(ridge, "evolution", True)
    window.scene.add_connection(
        time_node.output_ports["Loop Phase"],
        ridge.input_ports["@param:evolution"],
        record_undo=False,
    )
    window.scene.add_connection(ridge.output_port, aperture.input_ports["Image"], record_undo=False)
    window.scene.add_connection(aperture.output_port, output.input_ports["Image"], record_undo=False)
    window.scene.set_active_node(output)

    window._set_playing(True)
    pump(app, 3.0)
    assert window._playback_presented_frames >= 2, (
        "Loop Phase → Ridged Noise → Aperture must visibly update during timeline playback"
    )
    assert window._playback_last_result is not None
    assert window._playback_last_result.dynamic_nodes >= 4

    window._playing = False
    window.playback_timer.stop()
    window.playback_controller.cancel()
    window.eval_controller.cancel()
    window.material_controller.cancel()
    pump(app, 0.05)
    print("animation aperture playback test passed: late exact frames continue reaching the 2D preview")


if __name__ == "__main__":
    main()
