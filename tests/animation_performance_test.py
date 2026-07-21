from __future__ import annotations

import tempfile
import time
from types import SimpleNamespace

from PySide6.QtCore import QPointF, QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.main_window import MainWindow


def _pump(app: QApplication, seconds: float) -> None:
    deadline = time.perf_counter() + max(float(seconds), 0.0)
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.003)


def _window(app: QApplication, name: str, mode: str) -> MainWindow:
    QCoreApplication.setOrganizationName(f"VFXTextureLabTests{name}")
    QCoreApplication.setApplicationName(f"AnimationPerformance{name}")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        tempfile.mkdtemp(prefix="vfx-animation-performance-"),
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
    window.timeline_panel.set_playback_mode(mode)
    window.timeline_panel.set_profiler_enabled(True)

    window.scene.clear_graph(record_undo=False)
    checker = window.scene.create_node("pattern.checker", QPointF(0, 120), record_undo=False)
    time_node = window.scene.create_node("signal.time", QPointF(0, 0), record_undo=False)
    transform = window.scene.create_node("transform.basic", QPointF(260, 0), record_undo=False)
    output = window.scene.create_node("output.image", QPointF(520, 0), record_undo=False)
    window.scene.set_parameter_socket_exposed(transform, "offset_x", True)
    window.scene.add_connection(checker.output_port, transform.input_ports["Image"], record_undo=False)
    window.scene.add_connection(
        time_node.output_ports["Document Phase"],
        transform.input_ports["@param:offset_x"],
        record_undo=False,
    )
    window.scene.add_connection(transform.output_port, output.input_ports["Image"], record_undo=False)
    window.scene.set_active_node(output)
    return window




def _static_window(app: QApplication, name: str, mode: str) -> MainWindow:
    QCoreApplication.setOrganizationName(f"VFXTextureLabTests{name}")
    QCoreApplication.setApplicationName(f"AnimationPerformance{name}")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        tempfile.mkdtemp(prefix="vfx-animation-static-"),
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
    window.timeline_panel.set_playback_mode(mode)
    window.timeline_panel.set_profiler_enabled(True)

    window.scene.clear_graph(record_undo=False)
    checker = window.scene.create_node("pattern.checker", QPointF(0, 0), record_undo=False)
    output = window.scene.create_node("output.image", QPointF(260, 0), record_undo=False)
    window.scene.add_connection(checker.output_port, output.input_ports["Image"], record_undo=False)
    window.scene.set_active_node(output)
    return window

def _shutdown(window: MainWindow, app: QApplication) -> None:
    window._playing = False
    window.playback_timer.stop()
    window.playback_controller.cancel()
    window.eval_controller.cancel()
    window.material_controller.cancel()
    _pump(app, 0.05)


def assert_realtime_buffering(app: QApplication) -> None:
    window = _window(app, "Realtime", "Real-time")
    window._set_playing(True)
    _pump(app, 1.5)
    assert window._playback_presented_frames >= 2
    assert len(window._playback_buffer) <= window._playback_buffer_limit
    result = window._playback_last_result
    assert result is not None
    assert result.dynamic_nodes >= 2, "Time-dependent descendants were not classified as dynamic"
    assert result.static_nodes >= 1, "Static upstream content should remain separately cacheable"
    profiler = window.timeline_panel.performance_label.text()
    assert "buffered" in profiler and "Time-dependent" in profiler and "GPU cache" in profiler
    _shutdown(window, app)


def assert_every_frame_mode(app: QApplication) -> None:
    window = _window(app, "EveryFrame", "Every frame")
    window._set_playing(True)
    _pump(app, 1.2)
    assert window._playback_presented_frames >= 2
    assert window._playback_dropped_frames == 0
    # Every-frame mode advances only after a completed exact frame arrives.
    assert window.current_frame == window._playback_presented_frames
    _shutdown(window, app)






def assert_static_branch_reuse(app: QApplication) -> None:
    window = _static_window(app, "StaticBranch", "Real-time")
    window._set_playing(True)
    _pump(app, 0.9)
    result = window._playback_static_result
    assert result is not None, "Static playback branch was not detected"
    assert result.dynamic_nodes == 0
    assert window._playback_static_uploaded
    assert window.current_frame > 0
    assert not window._playback_render_in_flight
    assert not window._playback_buffer
    assert f"frame {window.current_frame}" in window.preview_panel._info_full_text
    assert window._playback_presented_frames >= 2
    _shutdown(window, app)

def assert_profiler_off_skips_traces(app: QApplication) -> None:
    window = _window(app, "NoProfiler", "Real-time")
    window.timeline_panel.set_profiler_enabled(False)
    window._set_playing(True)
    _pump(app, 1.0)
    result = window._playback_last_result
    assert result is not None
    assert result.node_traces == (), "Playback should avoid detailed trace construction while the profiler is disabled"
    assert result.dynamic_nodes >= 2 and result.static_nodes >= 1
    _shutdown(window, app)





def assert_late_realtime_frame_is_presented(_app: QApplication) -> None:
    class Value:
        def __init__(self, value: int) -> None:
            self._value = value

        def value(self) -> int:
            return self._value

    class Timeline:
        loop_start = Value(0)
        loop_end = Value(47)
        loop_enabled = True
        playback_mode_name = "Real-time"

        @staticmethod
        def set_frame(_frame: int, *, emit: bool = False) -> None:
            del emit

    class Harness:
        _playback_frame_after = MainWindow._playback_frame_after
        _playback_frame_is_ahead = MainWindow._playback_frame_is_ahead
        _trim_playback_buffer = MainWindow._trim_playback_buffer
        _playback_frame_ready = MainWindow._playback_frame_ready

        def __init__(self) -> None:
            self.timeline_panel = Timeline()
            self._playing = True
            self.current_frame = 8
            self._playback_render_in_flight = True
            self._playback_render_frame = 1
            self._playback_waiting_target = None
            self._playback_prefetch_depth = 3
            self._playback_buffer_limit = 4
            self._playback_buffer = __import__("collections").OrderedDict()
            self._playback_static_result = None
            self._playback_static_uploaded = False
            self.presented: list[int] = []

        def _present_playback_result(self, result) -> None:
            self.presented.append(int(result.frame_number))

        @staticmethod
        def _queue_playback_prefetch() -> None:
            return

        def _present_static_playback_frame(self, _frame: int) -> None:
            raise AssertionError("Dynamic regression result must not use static playback")

    harness = Harness()
    harness._playback_frame_ready(SimpleNamespace(frame_number=1, dynamic_nodes=3))
    assert harness.presented == [1], "A completed frame behind the wall-clock playhead must still reach the 2D preview"
    assert 1 not in harness._playback_buffer

    future = harness._playback_frame_after(harness.current_frame)
    assert future is not None
    harness.presented.clear()
    harness._playback_render_in_flight = True
    harness._playback_render_frame = future
    harness._playback_frame_ready(SimpleNamespace(frame_number=future, dynamic_nodes=3))
    assert not harness.presented
    assert future in harness._playback_buffer



def assert_material_playback_reuses_static_channels(app: QApplication) -> None:
    QCoreApplication.setOrganizationName("VFXTextureLabTestsMaterialPlayback")
    QCoreApplication.setApplicationName("AnimationPerformanceMaterialPlayback")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        tempfile.mkdtemp(prefix="vfx-animation-material-"),
    )
    window = MainWindow()
    window.document.width = 128
    window.document.height = 128
    window.document.preview_max_dimension = 128
    window.document.frames_per_second = 24.0
    window.document.duration_seconds = 2.0
    window.document.loop_start_frame = 0
    window.document.loop_end_frame = 47
    window.document.normalise()
    window.timeline_panel.set_document(window.document)
    window.timeline_panel.set_playback_mode("Real-time")
    window.timeline_panel.set_profiler_enabled(True)
    window.preview_3d_panel.set_viewport_setting("texture_resolution", "512", persist=False)

    window.scene.clear_graph(record_undo=False)
    checker = window.scene.create_node("pattern.checker", QPointF(0, 140), record_undo=False)
    time_node = window.scene.create_node("signal.time", QPointF(0, 0), record_undo=False)
    transform = window.scene.create_node("transform.basic", QPointF(240, 120), record_undo=False)
    gradient = window.scene.create_node("convert.gradient_map", QPointF(470, 120), record_undo=False)
    roughness = window.scene.create_node(
        "generator.constant", QPointF(470, 280), parameters={"value": 0.63}, record_undo=False
    )
    metallic = window.scene.create_node(
        "generator.constant", QPointF(470, 380), parameters={"value": 0.18}, record_undo=False
    )
    geometry = window.scene.create_node(
        "geometry.box", QPointF(470, 500), parameters={"subdivisions_x": 4, "subdivisions_y": 4, "subdivisions_z": 4},
        record_undo=False,
    )
    material = window.scene.create_node("material.pbr", QPointF(760, 180), record_undo=False)
    window.scene.set_parameter_socket_exposed(transform, "offset_x", True)
    assert window.scene.add_connection(checker.output_port, transform.input_ports["Image"], record_undo=False)
    assert window.scene.add_connection(
        time_node.output_ports["Document Phase"], transform.input_ports["@param:offset_x"], record_undo=False
    )
    assert window.scene.add_connection(transform.output_port, gradient.input_ports["Image"], record_undo=False)
    assert window.scene.add_connection(gradient.output_port, material.input_ports["Base Colour"], record_undo=False)
    assert window.scene.add_connection(roughness.output_port, material.input_ports["Roughness"], record_undo=False)
    assert window.scene.add_connection(metallic.output_port, material.input_ports["Metallic"], record_undo=False)
    assert window.scene.add_connection(geometry.output_ports["Geometry"], material.input_ports["Geometry"], record_undo=False)
    window.scene.set_active_node(material)
    QApplication.processEvents()

    if not window.preview_3d_panel.available:
        _shutdown(window, app)
        return

    window._set_playing(True)
    _pump(app, 0.9)

    # Switching away from a live Material must invalidate both the worker and
    # any completed frame waiting in the separate 3D presentation cadence.
    # Returning starts a fresh serialised stream at a power-of-two live tier.
    epoch_before_switch = window._material_playback_epoch
    window.scene.set_active_node(checker, force=True)
    _pump(app, 0.15)
    assert window._material_playback_epoch > epoch_before_switch
    assert window._material_playback_pending_result is None
    assert window._material_playback_focus_uid is None

    epoch_after_leave = window._material_playback_epoch
    window.scene.set_active_node(material, force=True)
    _pump(app, 1.0)
    assert window._material_playback_epoch > epoch_after_leave
    assert window._material_playback_focus_uid == material.uid
    assert window._material_playback_live_max in {128, 256}
    assert window._material_playback_live_max != 192
    if window._material_playback_pending_result is not None:
        assert window._material_playback_pending_result[2] == window._material_playback_epoch

    result = window._playback_last_result
    assert result is not None, "Material playback never presented a frame"
    assert window._playback_presented_frames >= 2
    assert window._material_playback_2d_presented_frames >= window._playback_presented_frames
    assert window._material_playback_last_2d_frame >= 0
    assert not window._playback_render_in_flight, "Material focus should not run the separate 2D playback evaluator"
    assert "Base Colour" in result.dynamic_channels
    assert result.static_cache_hits >= 2, "Static Roughness/Metallic maps were not reused across frames"
    assert result.textures["Roughness"].shape == (1, 1, 4)
    assert result.textures["Metallic"].shape == (1, 1, 4)
    assert window.preview_3d_panel.canvas.renderer._geometry_override is not None
    assert "live material playback" in window.preview_panel._info_full_text
    _shutdown(window, app)

def main() -> None:
    app = QApplication.instance() or QApplication([])
    assert_realtime_buffering(app)
    assert_every_frame_mode(app)
    assert_static_branch_reuse(app)
    assert_profiler_off_skips_traces(app)
    assert_late_realtime_frame_is_presented(app)
    assert_material_playback_reuses_static_channels(app)
    print(
        "animation performance test passed: exact frame-ahead buffering, real-time/every-frame playback, "
        "time-dependent branch diagnostics, late-frame presentation, static-frame reuse, "
        "single-stream Material playback and compact profiler telemetry"
    )


if __name__ == "__main__":
    main()
