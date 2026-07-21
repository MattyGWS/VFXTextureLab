from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PySide6.QtCore import QEventLoop, QPointF, QSettings, QTimer
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.animation_export import AnimationExportRequest, animation_sample_positions, assemble_flipbook, export_animation_frames
from vfx_texture_lab.custom_nodes import CustomNodePackageManager
from vfx_texture_lab.document import DocumentSettings
from vfx_texture_lab.engine import AsyncEvaluationController, GraphEvaluator, GraphSnapshot
from vfx_texture_lab.graph import GraphScene
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.main_window import MainWindow
from vfx_texture_lab.ui.timeline import TimelinePanel


def make_scene(registry):
    return GraphScene(registry)


def add(scene, type_id: str, x: float = 0.0, y: float = 0.0):
    return scene.create_node(type_id, QPointF(x, y), record_undo=False)


def evaluate(evaluator, scene, uid: str, frame: int, document: DocumentSettings, size: int = 48):
    return evaluator.evaluate(
        uid,
        size,
        size,
        snapshot=GraphSnapshot.from_scene(scene),
        frame_number=min(int(frame), document.last_frame),
        frame_position=float(frame),
        time_seconds=document.time_for_frame(frame),
        normalised_time=document.normalised_time_for_frame(frame),
        loop_phase=document.loop_phase_for_frame(frame),
        delta_time=1.0 / document.frames_per_second,
        duration_seconds=document.duration_seconds,
        frames_per_second=document.frames_per_second,
        document_frame_count=document.frame_count,
        loop_start_frame=document.loop_start_frame,
        loop_end_frame=document.loop_end_frame,
    )


def assert_document_timing() -> None:
    document = DocumentSettings(frames_per_second=24.0, duration_seconds=2.5, loop_start_frame=3, loop_end_frame=59)
    document.normalise()
    assert document.frame_count == 60
    assert document.last_frame == 59
    assert abs(document.time_for_frame(24) - 1.0) < 1e-8
    assert document.normalised_time_for_frame(59) == 1.0
    restored = DocumentSettings.from_dict(document.to_dict())
    assert restored.to_dict() == document.to_dict()


def assert_timeline_widget(document: DocumentSettings) -> None:
    timeline = TimelinePanel()
    timeline.set_document(document)
    timeline.set_frame(17, emit=False)
    assert timeline.frame == 17
    assert "17" not in timeline.info_label.text()  # summary stays document-level
    assert timeline.time_label.text().startswith(f"{document.time_for_frame(17):.3f}")
    timeline.set_playing(True)
    assert timeline.play_button.isChecked()
    timeline.set_playing(False)


def assert_scalar_motion_and_loop(registry, document: DocumentSettings) -> None:
    scene = make_scene(registry)
    time = add(scene, "signal.time", -600)
    noise = add(scene, "noise.fractal", -250)
    output = add(scene, "output.image", 100)
    scene.set_parameter_socket_exposed(noise, "evolution", True)
    assert "@param:evolution" in noise.input_ports
    scene.add_connection(time.output_ports["Loop Phase"], noise.input_ports["@param:evolution"], record_undo=False)
    scene.add_connection(noise.output_port, output.input_ports["Image"], record_undo=False)

    evaluator = GraphEvaluator(scene, backend_preference="cpu")
    first = evaluate(evaluator, scene, output.uid, 0, document)
    middle = evaluate(evaluator, scene, output.uid, document.last_frame // 2, document)
    last = evaluate(evaluator, scene, output.uid, document.last_frame, document)
    wrapped = evaluate(evaluator, scene, output.uid, document.frame_count, document)
    assert first.error is None and middle.error is None and last.error is None and wrapped.error is None
    assert not np.allclose(first.image, middle.image, atol=1e-4)
    assert not np.allclose(first.image, last.image, atol=2e-5), "The last cell should remain a unique frame"
    assert np.allclose(first.image, wrapped.image, atol=2e-5), "The virtual exclusive end should wrap to the first frame"
    assert middle.signal_nodes == 1


def assert_cycle_and_transform(registry, document: DocumentSettings) -> None:
    scene = make_scene(registry)
    cycle = add(scene, "signal.cycle", -700)
    math_node = add(scene, "signal.math", -500)
    transform = add(scene, "transform.basic", -200)
    checker = add(scene, "pattern.checker", -500, 180)
    output = add(scene, "output.image", 100)
    cycle.parameters["duration"] = document.duration_seconds
    math_node.parameters["operation"] = "Multiply"
    math_node.parameters["b"] = 1.0
    scene.set_parameter_socket_exposed(transform, "offset_x", True)
    scene.add_connection(cycle.output_ports["Value"], math_node.input_ports["A"], record_undo=False)
    scene.add_connection(math_node.output_ports["Value"], transform.input_ports["@param:offset_x"], record_undo=False)
    scene.add_connection(checker.output_port, transform.input_ports["Image"], record_undo=False)
    scene.add_connection(transform.output_port, output.input_ports["Image"], record_undo=False)
    evaluator = GraphEvaluator(scene, backend_preference="cpu")
    a = evaluate(evaluator, scene, output.uid, 0, document)
    b = evaluate(evaluator, scene, output.uid, document.last_frame // 3, document)
    assert a.error is None and b.error is None
    assert not np.allclose(a.image, b.image)
    assert b.signal_nodes == 2


def assert_motion_serialization(registry, document: DocumentSettings) -> None:
    scene = make_scene(registry)
    time = add(scene, "signal.time", -400)
    transform = add(scene, "transform.basic", -100)
    checker = add(scene, "pattern.checker", -400, 180)
    output = add(scene, "output.flipbook", 220)
    scene.set_parameter_socket_exposed(transform, "angle", True)
    scene.add_connection(time.output_ports["Frame"], transform.input_ports["@param:angle"], record_undo=False)
    scene.add_connection(checker.output_port, transform.input_ports["Image"], record_undo=False)
    scene.add_connection(transform.output_port, output.input_ports["Image"], record_undo=False)
    data = scene.to_dict()

    restored = make_scene(registry)
    restored.from_dict(data)
    restored_transform = next(node for node in restored.nodes.values() if node.definition.type_id == "transform.basic")
    restored_time = next(node for node in restored.nodes.values() if node.definition.type_id == "signal.time")
    restored_output = next(node for node in restored.nodes.values() if node.definition.type_id == "output.flipbook")
    assert "@param:angle" in restored_transform.input_ports
    connection = restored.connection_for_input(restored_transform.uid, "@param:angle")
    assert connection is not None
    assert connection.source_node.uid == restored_time.uid and connection.output_name == "Frame"
    result = evaluate(GraphEvaluator(restored, backend_preference="cpu"), restored, restored_output.uid, 8, document, 24)
    assert result.error is None


def assert_static_cache_is_time_independent(registry, document: DocumentSettings) -> None:
    scene = make_scene(registry)
    constant = add(scene, "generator.constant")
    output = add(scene, "output.image", 220)
    scene.add_connection(constant.output_port, output.input_ports["Image"], record_undo=False)
    evaluator = GraphEvaluator(scene, backend_preference="cpu")
    first = evaluate(evaluator, scene, output.uid, 0, document)
    second = evaluate(evaluator, scene, output.uid, min(10, document.last_frame), document)
    assert np.array_equal(first.image, second.image)
    assert second.cache_hits >= 1, "Static branches should remain cached while the timeline changes"


def assert_vector_signals(registry, document: DocumentSettings) -> None:
    scene = make_scene(registry)
    combine = add(scene, "signal.combine_vector2")
    split = add(scene, "signal.split_vector2", 220)
    combine.parameters["x"] = 0.25
    combine.parameters["y"] = 0.75
    scene.add_connection(combine.output_ports["Vector"], split.input_ports["Vector"], record_undo=False)
    evaluator = GraphEvaluator(scene, backend_preference="cpu")
    result_x = evaluate(evaluator, scene, split.uid, 0, document, 8)
    assert result_x.error is None
    # Active signal-node preview uses its first named output (X).
    assert abs(float(result_x.signal_value) - 0.25) < 1e-8
    assert split.input_ports["Vector"].kind == "vector2"
    assert combine.output_ports["Vector"].kind == "vector2"


def assert_group_scalar_interface(registry) -> None:
    scene = make_scene(registry)
    cycle = add(scene, "signal.cycle", -500)
    noise = add(scene, "noise.fractal", 0)
    output = add(scene, "output.image", 260)
    scene.set_parameter_socket_exposed(noise, "evolution", True)
    scene.add_connection(cycle.output_ports["Value"], noise.input_ports["@param:evolution"], record_undo=False)
    scene.add_connection(noise.output_port, output.input_ports["Image"], record_undo=False)
    group = scene.create_group(QPointF(-40, -70), members={noise.uid, output.uid}, record_undo=False)
    scene.toggle_group(group)
    scalar_ports = [port for port in group.input_ports.values() if port.kind == "scalar"]
    assert len(scalar_ports) == 1
    assert scalar_ports[0].display_name == "Evolution"
    assert any(port.kind in {"grayscale", "color", "vector", "image_any"} for port in group.output_ports.values())


def assert_flipbook_assembly() -> None:
    frames = []
    for value in (0.1, 0.3, 0.6, 0.9):
        frame = np.zeros((3, 5, 4), dtype=np.float32)
        frame[..., :3] = value
        frame[..., 3] = 1.0
        frames.append(frame)
    sheet = assemble_flipbook(frames, columns=2, rows=2, padding=1, background="#00000000")
    assert sheet.shape == (7, 11, 4)
    assert np.allclose(sheet[0:3, 0:5, 0], 0.1)
    assert np.allclose(sheet[0:3, 6:11, 0], 0.3)
    assert np.allclose(sheet[4:7, 0:5, 0], 0.6)
    assert np.allclose(sheet[4:7, 6:11, 0], 0.9)
    assert np.allclose(sheet[3, :, 3], 0.0)
    with tempfile.TemporaryDirectory() as temp:
        request = AnimationExportRequest(
            node_uid="flipbook", output_name="Test", mode="Flipbook", directory=Path(temp),
            base_name="test_flipbook", width=5, height=3, start_frame=0, end_frame=3,
            frame_step=1, columns=2, rows=2, padding=1, background="#00000000",
            options=__import__("vfx_texture_lab.exporting", fromlist=["ExportOptions"]).ExportOptions(
                format_name="PNG", bit_depth=8, channels="RGBA", colour_encoding="Linear"
            ),
        )
        paths = export_animation_frames(request, frames)
        assert len(paths) == 1 and paths[0].is_file()
        assert paths[0].read_bytes().startswith(b"\x89PNG")
        request.mode = "Image Sequence"
        request.base_name = "frame"
        paths = export_animation_frames(request, frames)
        assert [path.name for path in paths] == ["frame_0000.png", "frame_0001.png", "frame_0002.png", "frame_0003.png"]


def assert_public_api_v2(_registry) -> None:
    with tempfile.TemporaryDirectory() as temp:
        settings = QSettings(str(Path(temp) / "settings.ini"), QSettings.Format.IniFormat)
        manager = CustomNodePackageManager(settings)
        definitions = manager.discover(gpu_backend=None)
        polar = definitions["org.vfxtexturelab.polar_coordinates"]
        assert polar.package is not None and polar.package.api_version == 2
        assert polar.parameter_spec("angle_offset").animatable
        assert "org.vfxtexturelab.directional_warp" in definitions
        assert definitions["org.vfxtexturelab.directional_warp"].package.api_version == 2


def assert_api_v2_time_uniform(registry) -> None:
    scene = make_scene(registry)
    evaluator = GraphEvaluator(scene, backend_preference="gpu")
    if not evaluator.gpu_available:
        return
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        package = root / "animated_public_node"
        package.mkdir()
        (package / "node.toml").write_text(
            """api_version = 2
id = \"com.example.animated_public_test\"
name = \"Animated Public Test\"
version = \"1.0.0\"
category = \"Tests\"
shader = \"kernel.wgsl\"
output_format = \"rgba16f\"
output_name = \"Image\"

[animation]
uses_time = true
""",
            encoding="utf-8",
        )
        (package / "kernel.wgsl").write_text(
            """struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var output_tex: texture_storage_2d<rgba32float, write>;
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let size = vec2<u32>(u32(params.p0.x), u32(params.p0.y));
    if (gid.x >= size.x || gid.y >= size.y) { return; }
    let value = params.p0.w;
    textureStore(output_tex, vec2<i32>(gid.xy), vec4<f32>(value, value, value, 1.0));
}
""",
            encoding="utf-8",
        )
        settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
        manager = CustomNodePackageManager(settings)
        manager.add_library(root, "Motion API Test")
        definitions = manager.discover(evaluator.gpu_backend)
        definition = definitions["com.example.animated_public_test"]
        registry.register(definition)
        animated = add(scene, definition.type_id)
        output = add(scene, "output.image", 240)
        scene.add_connection(animated.output_port, output.input_ports["Image"], record_undo=False)
        document = DocumentSettings(frames_per_second=30.0, duration_seconds=2.0, loop_end_frame=59)
        document.normalise()
        first = evaluate(evaluator, scene, output.uid, 0, document, 16)
        last = evaluate(evaluator, scene, output.uid, document.last_frame, document, 16)
        assert first.error is None and last.error is None
        assert float(first.image[..., 0].mean()) < 0.01
        assert float(last.image[..., 0].mean()) > 0.99



def assert_live_playback_scheduler() -> None:
    class FakeTimer:
        def __init__(self) -> None:
            self.stops = 0

        def stop(self) -> None:
            self.stops += 1

    class Harness:
        def __init__(self) -> None:
            self._playing = True
            self._preview_in_flight = True
            self._playback_preview_pending = False
            self.preview_timer = FakeTimer()
            self.evaluated = 0

        def _active_is_flipbook(self) -> bool:
            return False

        def _evaluate_active(self) -> None:
            self.evaluated += 1

    harness = Harness()
    MainWindow._request_playback_preview(harness)
    assert harness._playback_preview_pending
    assert harness.evaluated == 0, "An in-flight playback render must not be cancelled and restarted every timer tick"

    harness._preview_in_flight = False
    MainWindow._request_playback_preview(harness)
    assert harness.evaluated == 1
    assert not harness._playback_preview_pending
    assert harness.preview_timer.stops == 1


def assert_async_flipbook_preview(registry, document: DocumentSettings) -> None:
    scene = make_scene(registry)
    time_node = add(scene, "signal.time", -500)
    noise = add(scene, "noise.fractal", -200)
    output = add(scene, "output.flipbook", 120)
    scene.set_parameter_socket_exposed(noise, "evolution", True)
    scene.add_connection(time_node.output_ports["Loop Phase"], noise.input_ports["@param:evolution"], record_undo=False)
    scene.add_connection(noise.output_port, output.input_ports["Image"], record_undo=False)

    evaluator = GraphEvaluator(scene, backend_preference="cpu")
    controller = AsyncEvaluationController(evaluator)
    loop = QEventLoop()
    completed = []
    failures = []
    controller.resultReady.connect(lambda result: (completed.append(result), loop.quit()))
    controller.evaluationFailed.connect(lambda message: (failures.append(message), loop.quit()))
    animations = [
        {
            "frame_number": frame,
            "frame_position": float(frame),
            "time_seconds": document.time_for_frame(frame),
            "normalised_time": document.normalised_time_for_frame(frame),
            "loop_phase": document.loop_phase_for_frame(frame),
            "delta_time": 1.0 / document.frames_per_second,
            "duration_seconds": document.duration_seconds,
            "frames_per_second": document.frames_per_second,
            "document_frame_count": document.frame_count,
            "loop_start_frame": document.loop_start_frame,
            "loop_end_frame": document.loop_end_frame,
        }
        for frame in (0, 10, 20, 30)
    ]
    controller.request_flipbook(
        GraphSnapshot.from_scene(scene), output.uid, 12, 8, animations,
        columns=2, rows=2, padding=1, background="#00000000",
    )
    QTimer.singleShot(10000, loop.quit)
    loop.exec()
    assert not failures, failures[0] if failures else ""
    assert completed, "Asynchronous flipbook preview did not finish"
    result = completed[0]
    assert result.error is None
    assert result.image.shape == (17, 25, 4)
    assert not np.allclose(result.image[0:8, 0:12], result.image[0:8, 13:25])


def assert_flipbook_preview_configuration(document: DocumentSettings) -> None:
    class Node:
        parameters = {
            "layout": "Custom",
            "use_full_grid": True,
            "source_range": "Custom Frame Range",
            "sampling": "Consecutive Timeline Frames",
            "columns": 4,
            "rows": 2,
            "start_frame": 0,
            "end_frame": 7,
            "frame_step": 1,
            "padding": 4,
            "background": "#11223344",
        }

    class Harness:
        pass

    harness = Harness()
    harness.document = document
    result = MainWindow._flipbook_preview_configuration(harness, Node())
    assert not isinstance(result, str)
    frames, columns, rows, cell_width, cell_height, padding, background = result
    assert frames == list(range(8))
    assert (columns, rows) == (4, 2)
    assert cell_width > 0 and cell_height > 0
    assert columns * cell_width + (columns - 1) * padding <= 1024
    assert rows * cell_height + (rows - 1) * padding <= 1024
    assert background == "#11223344"


def assert_motion_schema_migration(registry) -> None:
    scene = make_scene(registry)
    time = add(scene, "signal.time", -300)
    transform = add(scene, "transform.basic", 0)
    scene.set_parameter_socket_exposed(transform, "offset_x", True)
    scene.add_connection(time.output_ports["Document Phase"], transform.input_ports["@param:offset_x"], record_undo=False)
    data = scene.to_dict()
    data["connections"][0]["source_output"] = "Normalised"
    restored = make_scene(registry)
    restored.from_dict(data)
    restored_transform = next(node for node in restored.nodes.values() if node.definition.type_id == "transform.basic")
    connection = restored.connection_for_input(restored_transform.uid, "@param:offset_x")
    assert connection is not None and connection.output_name == "Document Phase"

    old_project = {
        "version": 5,
        "nodes": [{
            "type": "output.flipbook",
            "parameters": {"columns": 4, "rows": 4, "start_frame": 5, "end_frame": 20, "frame_step": 1},
        }],
    }
    migrated = MainWindow._migrate_project_data(old_project)
    params = migrated["nodes"][0]["parameters"]
    assert params["layout"] == "Custom"
    assert params["source_range"] == "Custom Frame Range"
    assert params["sampling"] == "Consecutive Timeline Frames"


def assert_loop_phase_and_flipbook_sampling(document: DocumentSettings) -> None:
    assert abs(document.loop_phase_for_frame(document.loop_start_frame)) < 1e-9
    assert abs(document.loop_phase_for_frame(document.loop_end_frame) - ((document.loop_frame_count - 1) / document.loop_frame_count)) < 1e-9
    assert abs(document.loop_phase_for_frame(document.loop_end_frame + 1)) < 1e-9
    samples16 = animation_sample_positions(document, source_range="Document Loop", frame_count=16)
    samples64 = animation_sample_positions(document, source_range="Document Loop", frame_count=64)
    assert len(samples16) == 16 and len(samples64) == 64
    phases16 = [document.loop_phase_for_frame(value) for value in samples16]
    assert np.allclose(phases16, [index / 16.0 for index in range(16)], atol=1e-9)
    included = animation_sample_positions(document, source_range="Document Loop", frame_count=16, include_end_frame=True)
    assert abs(document.loop_phase_for_frame(included[-1])) < 1e-9


def main() -> int:
    app = QApplication.instance() or QApplication([])
    document = DocumentSettings(frames_per_second=30.0, duration_seconds=2.0, loop_end_frame=59)
    document.normalise()
    registry = build_registry()

    for type_id in (
        "signal.time", "signal.loop_phase", "signal.cycle", "signal.wave", "signal.math", "signal.remap",
        "signal.clamp", "signal.smoothstep", "signal.curve", "signal.combine_vector2",
        "signal.split_vector2", "output.flipbook",
    ):
        assert registry.get(type_id).type_id == type_id

    assert_document_timing()
    assert_loop_phase_and_flipbook_sampling(document)
    assert_motion_schema_migration(registry)
    assert_timeline_widget(document)
    assert_live_playback_scheduler()
    assert_scalar_motion_and_loop(registry, document)
    assert_cycle_and_transform(registry, document)
    assert_motion_serialization(registry, document)
    assert_static_cache_is_time_independent(registry, document)
    assert_vector_signals(registry, document)
    assert_group_scalar_interface(registry)
    assert_flipbook_assembly()
    assert_async_flipbook_preview(registry, document)
    assert_flipbook_preview_configuration(document)
    assert_public_api_v2(registry)
    assert_api_v2_time_uniform(registry)

    print(
        "Motion test passed: document timing, timeline transport, typed scalar/vector signals, "
        "animatable parameter sockets, loopable noise evolution, animated transforms, time-aware caching, "
        "non-starving live playback, exclusive-end loop phase sampling, FPS-independent flipbook grids, "
        "full flipbook preview assembly and custom-node API v2"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
