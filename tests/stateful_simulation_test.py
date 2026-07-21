from __future__ import annotations

import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.engine.evaluator import (
    EvaluationCancelled,
    GraphEvaluator,
    GraphSnapshot,
    SnapshotNode,
)
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext, NodeDefinition
from vfx_texture_lab.nodes.image_ops import grayscale_rgba
from vfx_texture_lab.ui.timeline import TimelinePanel


def animated_frame(_inputs, _params, context: EvalContext):
    value = np.full((context.height, context.width), context.frame_number / 100.0, dtype=np.float32)
    return grayscale_rgba(value)


def fixed_seed(_inputs, _params, context: EvalContext):
    values = np.zeros((context.height, context.width), dtype=np.float32)
    y0 = context.height // 3
    y1 = max(y0 + 2, context.height * 2 // 3)
    x0 = context.width // 3
    x1 = max(x0 + 2, context.width * 2 // 3)
    values[y0:y1, x0:x1] = 1.0
    return grayscale_rgba(values)


def context_kwargs(frame: int) -> dict:
    return {
        "frame_number": frame,
        "frame_position": float(frame),
        "time_seconds": frame / 30.0,
        "normalised_time": frame / 119.0,
        "loop_phase": frame / 120.0,
        "frames_per_second": 30.0,
        "document_frame_count": 120,
        "loop_start_frame": 0,
        "loop_end_frame": 119,
    }


def main() -> None:
    app = QApplication.instance() or QApplication([])
    registry = build_registry()
    assert {definition.type_id for definition in registry.all() if definition.category == "Simulation"} == {
        "simulation.frame_delay",
        "simulation.temporal_blend",
        "simulation.reaction_diffusion",
    }
    assert all(
        registry.get(type_id).is_stateful
        for type_id in (
            "simulation.frame_delay",
            "simulation.temporal_blend",
            "simulation.reaction_diffusion",
        )
    )

    animated = NodeDefinition(
        "test.animated_frame",
        "Animated Frame",
        "Test",
        animated_frame,
        output_format="r16f",
        output_kinds=(("Image", "grayscale"),),
        uses_time=True,
        hidden=True,
    )
    delay = registry.get("simulation.frame_delay")
    snapshot = GraphSnapshot(
        nodes={
            "source": SnapshotNode("source", animated, animated.default_parameters()),
            "delay": SnapshotNode("delay", delay, delay.default_parameters()),
        },
        inputs={("delay", "Image"): ("source", "Image")},
    )
    evaluator = GraphEvaluator(backend_preference="cpu")

    direct = evaluator.evaluate_snapshot(snapshot, "delay", 24, 18, **context_kwargs(10))
    assert direct.error is None, direct.error
    assert np.allclose(direct.image[..., 0], 0.09, atol=1e-6)
    assert direct.simulation_nodes == 1 and direct.simulation_steps == 11

    sequential = evaluator.evaluate_snapshot(snapshot, "delay", 24, 18, **context_kwargs(11))
    assert np.allclose(sequential.image[..., 0], 0.10, atol=1e-6)
    assert sequential.simulation_steps == 1

    backwards = evaluator.evaluate_snapshot(snapshot, "delay", 24, 18, **context_kwargs(4))
    assert np.allclose(backwards.image[..., 0], 0.03, atol=1e-6)
    assert backwards.simulation_checkpoint == 0
    assert backwards.simulation_steps == 4

    checkpoint_forward = evaluator.evaluate_snapshot(snapshot, "delay", 24, 18, **context_kwargs(32))
    assert checkpoint_forward.error is None and checkpoint_forward.simulation_steps == 28
    checkpoint_back = evaluator.evaluate_snapshot(snapshot, "delay", 24, 18, **context_kwargs(20))
    assert checkpoint_back.simulation_checkpoint == 15
    assert checkpoint_back.simulation_steps == 5
    assert np.allclose(checkpoint_back.image[..., 0], 0.19, atol=1e-6)

    evaluator.reset_simulations("delay")
    rebuilt = evaluator.evaluate_snapshot(snapshot, "delay", 24, 18, **context_kwargs(11))
    assert rebuilt.simulation_steps == 12
    assert np.allclose(rebuilt.image[..., 0], sequential.image[..., 0], atol=1e-6)

    temporal = registry.get("simulation.temporal_blend")
    temporal_params = temporal.default_parameters()
    temporal_params["persistence"] = 0.5
    temporal_snapshot = GraphSnapshot(
        nodes={
            "source": SnapshotNode("source", animated, animated.default_parameters()),
            "temporal": SnapshotNode("temporal", temporal, temporal_params),
        },
        inputs={("temporal", "Image"): ("source", "Image")},
    )
    temporal_eval = GraphEvaluator(backend_preference="cpu")
    frame0 = temporal_eval.evaluate_snapshot(temporal_snapshot, "temporal", 16, 16, **context_kwargs(0))
    frame1 = temporal_eval.evaluate_snapshot(temporal_snapshot, "temporal", 16, 16, **context_kwargs(1))
    frame2 = temporal_eval.evaluate_snapshot(temporal_snapshot, "temporal", 16, 16, **context_kwargs(2))
    assert np.allclose(frame0.image[..., 0], 0.0, atol=1e-6)
    assert np.allclose(frame1.image[..., 0], 0.005, atol=1e-6)
    assert np.allclose(frame2.image[..., 0], 0.0125, atol=1e-6)

    # Changing a simulation parameter creates a fresh branch revision rather
    # than reusing stale history.
    changed_params = dict(temporal_params)
    changed_params["persistence"] = 0.25
    changed_snapshot = GraphSnapshot(
        nodes={
            "source": SnapshotNode("source", animated, animated.default_parameters()),
            "temporal": SnapshotNode("temporal", temporal, changed_params),
        },
        inputs={("temporal", "Image"): ("source", "Image")},
    )
    changed = temporal_eval.evaluate_snapshot(changed_snapshot, "temporal", 16, 16, **context_kwargs(2))
    assert changed.simulation_steps == 3
    assert np.allclose(changed.image[..., 0], 0.016875, atol=1e-6)

    reaction = registry.get("simulation.reaction_diffusion")
    reaction_params = reaction.default_parameters()
    reaction_params["steps_per_frame"] = 2
    reaction_snapshot = GraphSnapshot(
        nodes={"reaction": SnapshotNode("reaction", reaction, reaction_params)},
        inputs={},
    )
    reaction_eval = GraphEvaluator(backend_preference="cpu")
    first = reaction_eval.evaluate_snapshot(reaction_snapshot, "reaction", 40, 32, **context_kwargs(8))
    reaction_eval.reset_simulations()
    second = reaction_eval.evaluate_snapshot(reaction_snapshot, "reaction", 40, 32, **context_kwargs(8))
    assert first.error is None and second.error is None
    assert np.allclose(first.image, second.image, atol=1e-7)
    assert float(np.max(first.image[..., 0])) > float(np.min(first.image[..., 0]))

    cancelled_calls = 0
    def cancelled() -> bool:
        nonlocal cancelled_calls
        cancelled_calls += 1
        return cancelled_calls > 20

    cancelled_eval = GraphEvaluator(backend_preference="cpu")
    try:
        cancelled_eval.evaluate_snapshot(
            temporal_snapshot, "temporal", 16, 16,
            cancel_check=cancelled,
            **context_kwargs(90),
        )
    except EvaluationCancelled:
        pass
    else:
        raise AssertionError("Long simulation replay did not honour cancellation")

    # GPU state stays resident between sequential frames when WebGPU is present.
    gpu_eval = GraphEvaluator(backend_preference="auto")
    if gpu_eval.gpu_available:
        gpu0 = gpu_eval.evaluate_snapshot(temporal_snapshot, "temporal", 16, 16, **context_kwargs(0))
        gpu1 = gpu_eval.evaluate_snapshot(temporal_snapshot, "temporal", 16, 16, **context_kwargs(1))
        assert gpu0.error is None and gpu1.error is None
        assert gpu0.backend in {"GPU", "Hybrid"} and gpu1.backend in {"GPU", "Hybrid"}
        assert np.allclose(gpu1.image, frame1.image, atol=2e-3)

        seed_definition = NodeDefinition(
            "test.fixed_seed", "Fixed Seed", "Test", fixed_seed,
            output_format="r16f", output_kinds=(("Image", "grayscale"),), hidden=True,
        )
        seeded_snapshot = GraphSnapshot(
            nodes={
                "seed": SnapshotNode("seed", seed_definition, seed_definition.default_parameters()),
                "reaction": SnapshotNode("reaction", reaction, reaction_params),
            },
            inputs={("reaction", "Seed"): ("seed", "Image")},
        )
        cpu_seeded = GraphEvaluator(backend_preference="cpu").evaluate_snapshot(
            seeded_snapshot, "reaction", 24, 24, **context_kwargs(2)
        )
        gpu_seeded = GraphEvaluator(backend_preference="auto").evaluate_snapshot(
            seeded_snapshot, "reaction", 24, 24, **context_kwargs(2)
        )
        assert cpu_seeded.error is None and gpu_seeded.error is None
        assert np.max(np.abs(cpu_seeded.image - gpu_seeded.image)) < 0.08
        assert np.mean(np.abs(cpu_seeded.image - gpu_seeded.image)) < 0.005

    panel = TimelinePanel()
    fired = []
    panel.resetSimulationsRequested.connect(lambda: fired.append(True))
    panel.reset_simulations_button.click()
    QCoreApplication.processEvents()
    assert fired == [True]
    panel.close()

    print(
        "Stateful simulation test passed: deterministic frame replay, hot sequential state, "
        "checkpoint restoration, cancellation, reset controls, CPU/GPU state and Frame Delay, "
        "Temporal Blend and Reaction Diffusion proof nodes"
    )
    app.quit()


if __name__ == "__main__":
    main()
