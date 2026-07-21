from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.document import DocumentSettings
from vfx_texture_lab.engine import GraphEvaluator, GraphSnapshot
from vfx_texture_lab.graph import GraphScene
from vfx_texture_lab.nodes import build_registry


def make_atlas(path: Path) -> None:
    atlas = np.zeros((16, 16, 4), dtype=np.uint8)
    atlas[..., 3] = 255
    atlas[0:8, 0:8, :3] = (255, 0, 0)
    atlas[0:8, 8:16, :3] = (0, 255, 0)
    atlas[8:16, 0:8, :3] = (0, 0, 255)
    atlas[8:16, 8:16, :3] = (255, 255, 255)
    Image.fromarray(atlas, "RGBA").save(path)


def evaluate(evaluator: GraphEvaluator, scene: GraphScene, uid: str, frame: int, document: DocumentSettings):
    return evaluator.evaluate(
        uid,
        32,
        32,
        snapshot=GraphSnapshot.from_scene(scene),
        frame_number=frame,
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


def assert_imported_atlas_decode(registry) -> None:
    document = DocumentSettings(frames_per_second=16, duration_seconds=1, loop_start_frame=0, loop_end_frame=15)
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "atlas.png"
        make_atlas(path)
        scene = GraphScene(registry)
        image = scene.create_node("input.image", QPointF(-500, 0), record_undo=False)
        time = scene.create_node("signal.time", QPointF(-500, 180), record_undo=False)
        decode = scene.create_node("animation.flipbook_decode", QPointF(-100, 0), record_undo=False)
        image.parameters.update({"path": str(path), "colour_space": "Linear", "fit": "Stretch"})
        decode.parameters["layout"] = "2 × 2"
        scene.add_connection(image.output_port, decode.input_ports["Sheet"], record_undo=False)
        scene.add_connection(time.output_ports["Loop Phase"], decode.input_ports["Phase"], record_undo=False)
        assert decode.input_ports["Phase"].kind == "scalar"

        evaluator = GraphEvaluator(scene, backend_preference="cpu")
        expected = {
            0: np.array([1.0, 0.0, 0.0]),
            4: np.array([0.0, 1.0, 0.0]),
            8: np.array([0.0, 0.0, 1.0]),
            12: np.array([1.0, 1.0, 1.0]),
        }
        for frame, colour in expected.items():
            result = evaluate(evaluator, scene, decode.uid, frame, document)
            assert result.error is None, result.error
            assert np.allclose(result.image[16, 16, :3], colour, atol=2e-3)

        if evaluator.gpu_available:
            evaluator.set_backend_preference("gpu")
            result = evaluate(evaluator, scene, decode.uid, 8, document)
            assert result.error is None, result.error
            assert result.gpu_nodes >= 1
            assert not result.fallback_nodes
            assert np.allclose(result.image[16, 16, :3], expected[8], atol=2e-3)


def assert_direct_flipbook_output_decode(registry) -> None:
    document = DocumentSettings(frames_per_second=16, duration_seconds=1, loop_start_frame=0, loop_end_frame=15)
    scene = GraphScene(registry)
    time = scene.create_node("signal.time", QPointF(-700, 0), record_undo=False)
    constant = scene.create_node("generator.constant", QPointF(-450, 0), record_undo=False)
    output = scene.create_node("output.flipbook", QPointF(-150, 0), record_undo=False)
    decode = scene.create_node("animation.flipbook_decode", QPointF(180, 0), record_undo=False)
    output.parameters.update({
        "layout": "2 × 2",
        "source_range": "Document Loop",
        "sampling": "Evenly Across Range",
        "use_full_grid": True,
    })
    scene.set_parameter_socket_exposed(constant, "value", True)
    scene.add_connection(time.output_ports["Loop Phase"], constant.input_ports["@param:value"], record_undo=False)
    scene.add_connection(constant.output_port, output.input_ports["Image"], record_undo=False)
    scene.add_connection(output.output_port, decode.input_ports["Sheet"], record_undo=False)

    evaluator = GraphEvaluator(scene, backend_preference="cpu")
    observed = []
    for frame in (0, 4, 8, 12):
        result = evaluate(evaluator, scene, decode.uid, frame, document)
        assert result.error is None, result.error
        observed.append(float(result.image[0, 0, 0]))
    assert np.allclose(observed, (0.0, 0.25, 0.5, 0.75), atol=2e-4), observed

    data = scene.to_dict()
    restored = GraphScene(registry)
    restored.from_dict(data)
    restored_decode = next(node for node in restored.nodes.values() if node.definition.type_id == "animation.flipbook_decode")
    assert restored.connection_for_input(restored_decode.uid, "Sheet") is not None
    assert restored_decode.parameters["inherit_layout"] is True


def main() -> None:
    app = QApplication.instance() or QApplication([])
    registry = build_registry()
    assert registry.contains("animation.flipbook_decode")
    assert_imported_atlas_decode(registry)
    assert_direct_flipbook_output_decode(registry)
    app.processEvents()
    print(
        "Flipbook decode test passed: imported atlases, explicit Phase playback, "
        "typed Phase input, GPU decoding, direct Flipbook Generator inheritance and save/load"
    )


if __name__ == "__main__":
    main()
