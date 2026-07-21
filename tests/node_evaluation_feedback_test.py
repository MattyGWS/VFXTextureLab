from __future__ import annotations

import os
import sys
import time
import threading
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.engine.async_eval import _EvaluationWorker
from vfx_texture_lab.engine.evaluator import GraphEvaluator, GraphSnapshot, SnapshotNode
from vfx_texture_lab.engine.resources import CpuImage, GpuImage
from vfx_texture_lab.engine.formats import TextureFormat
from vfx_texture_lab.graph.scene import GraphScene
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import NodeDefinition


def _constant(inputs, parameters, context):
    del inputs, parameters
    return np.full((context.height, context.width), 0.25, dtype=np.float32)


def main() -> None:
    app = QApplication.instance() or QApplication([])

    # The evaluator announces only genuine uncached node work, with a balanced
    # active/inactive pair. A cache hit must remain visually silent.
    definition = NodeDefinition(
        "test.activity",
        "Activity Test",
        "Test",
        _constant,
        output_format="r16f",
        output_kinds=(("Image", "grayscale"),),
        default_image_kind="grayscale",
    )
    snapshot = GraphSnapshot(
        {"node": SnapshotNode("node", definition, {}, (), (), "grayscale")},
        {},
    )
    evaluator = GraphEvaluator(backend_preference="cpu")
    events: list[tuple] = []
    result = evaluator.evaluate_snapshot(
        snapshot,
        "node",
        16,
        16,
        node_activity_callback=lambda *event: events.append(event),
    )
    assert result.error is None
    assert events[0][:2] == ("node", True)
    assert events[-1][:2] == ("node", False)

    events.clear()
    result = evaluator.evaluate_snapshot(
        snapshot,
        "node",
        16,
        16,
        node_activity_callback=lambda *event: events.append(event),
    )
    assert result.error is None
    assert events == []

    # GPU-backed previews keep the output node visibly active during the final
    # queue synchronisation/readback stage. This is the gap that used to leave
    # the preview saying only "Evaluating exact preview" after an erosion bar
    # had already disappeared.
    class _Texture:
        def destroy(self):
            return

    gpu_evaluator = GraphEvaluator(backend_preference="cpu")
    gpu_evaluator._backend_for = lambda _definition: "gpu"  # type: ignore[method-assign]
    gpu_image = GpuImage(
        _Texture(), object(), 16, 16, TextureFormat.RGBA16F, "fake-gpu",
        provenance=frozenset({"gpu"}),
    )

    def fake_compute(*args, **kwargs):
        del args, kwargs
        return gpu_image, "fake-gpu"

    def fake_readback(resource, conversion_cache):
        del resource, conversion_cache
        time.sleep(0.01)
        return CpuImage(
            np.full((16, 16, 4), 0.5, dtype=np.float32),
            TextureFormat.RGBA16F, "fake-cpu", frozenset({"gpu", "cpu"}),
        )

    gpu_evaluator._compute_node = fake_compute  # type: ignore[method-assign]
    gpu_evaluator._to_cpu = fake_readback  # type: ignore[method-assign]
    gpu_events: list[tuple] = []
    gpu_result = gpu_evaluator.evaluate_snapshot(
        snapshot,
        "node",
        16,
        16,
        node_activity_callback=lambda *event: gpu_events.append(event),
    )
    assert gpu_result.error is None
    assert gpu_result.finalise_ms >= 5.0
    finalising = [event for event in gpu_events if event[1] and "Finalising Activity Test" in event[4]]
    assert finalising, gpu_events
    assert "GPU work" in finalising[-1][4]
    assert "16 × 16" in finalising[-1][4]
    assert gpu_events[-1][:2] == ("node", False)

    # Async progress painting is rate-limited while preserving start, exact
    # final progress and clear events.
    worker = _EvaluationWorker(
        7, evaluator, snapshot, "node", 16, 16, TextureFormat.RGBA16F,
        "Linear", {}, threading.Event(),
    )
    visual_events: list[tuple] = []
    worker.signals.nodeState.connect(lambda *event: visual_events.append(event))
    worker._emit_node_state("node", True, 0, 100, "Activity Test")
    for current in range(1, 100):
        worker._emit_node_state("node", True, current, 100, "Activity Test")
    worker._emit_node_state("node", True, 100, 100, "Activity Test")
    worker._emit_node_state("node", False, 0, 0, "")
    app.processEvents()
    assert len(visual_events) <= 4, visual_events
    assert visual_events[0][1:3] == ("node", True)
    assert visual_events[-2][3:5] == (100, 100)
    assert visual_events[-1][1:3] == ("node", False)

    # Graph items expose delayed, determinate and indeterminate visual states.
    scene = GraphScene(build_registry())
    node = scene.create_node("filter.levels", QPointF(), emit_change=False)
    scene.set_node_evaluation_state(node.uid, True, 3, 10, "Levels")
    assert node._eval_active
    assert np.isclose(node._evaluation_progress_fraction(), 0.3)
    assert not node._evaluation_visible()
    node._eval_started_at = time.perf_counter() - 0.25
    assert node._evaluation_visible()

    scene.set_node_evaluation_state(node.uid, True, 0, 0, "Levels")
    assert node._evaluation_progress_fraction() is None
    scene.clear_node_evaluation_states()
    assert not node._eval_active

    # Transient runtime feedback is deliberately absent from graph data.
    saved = scene.to_dict()
    serialized = str(saved)
    assert "eval_progress" not in serialized
    assert "eval_active" not in serialized

    print(
        "node evaluation feedback test passed: uncached activity events, silent cache hits, "
        "rate-limited UI updates, delayed visibility, determinate/indeterminate states, "
        "truthful GPU finalisation/readback feedback and non-serialization"
    )
    app.quit()


if __name__ == "__main__":
    main()
