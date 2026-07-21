from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from vfx_texture_lab.engine.evaluator import GraphEvaluator, GraphSnapshot, SnapshotNode
from vfx_texture_lab.nodes import build_registry


def _snapshot(type_ids: list[str], parameter_updates: list[dict] | None = None, *, kind: str = "grayscale") -> tuple[GraphSnapshot, str]:
    registry = build_registry()
    updates = parameter_updates or [{} for _ in type_ids]
    nodes: dict[str, SnapshotNode] = {}
    inputs: dict[tuple[str, str], tuple[str, str]] = {}
    uids = [f"node-{index}" for index in range(len(type_ids))]
    for index, (uid, type_id) in enumerate(zip(uids, type_ids)):
        definition = registry.get(type_id)
        parameters = definition.default_parameters()
        parameters.update(updates[index])
        nodes[uid] = SnapshotNode(
            uid,
            definition,
            parameters,
            tuple(definition.inputs),
            (),
            kind,
        )
        if index:
            inputs[(uid, "Image")] = (uids[index - 1], "Image")
    return GraphSnapshot(nodes, inputs), uids[-1]


def _evaluate_without_fusion(snapshot: GraphSnapshot, target_uid: str, width: int = 96, height: int = 80):
    evaluator = GraphEvaluator(backend_preference="gpu")
    evaluator._fusion_plan = types.MethodType(lambda self, graph, order: ({}, {}), evaluator)
    return evaluator.evaluate_snapshot(snapshot, target_uid, width, height)


def test_grayscale_adjustment_chain_fuses_without_changing_result() -> None:
    snapshot, target = _snapshot(
        [
            "shape.shape",
            "filter.histogram_range",
            "filter.histogram_shift",
            "filter.histogram_scan",
            "filter.brightness",
            "filter.levels",
            "filter.clamp",
        ],
        [
            {"shape": "Disc", "scale": 0.73, "edge_softness": 0.021},
            {"range": 0.74, "position": 0.27},
            {"position": 0.13},
            {"position": 0.61, "contrast": 0.44},
            {"brightness": 0.08},
            {"in_low": 0.02, "in_high": 0.94, "in_mid": 0.47, "out_low": 0.03, "out_high": 0.98},
            {"minimum": 0.05, "maximum": 0.93},
        ],
    )
    fused_evaluator = GraphEvaluator(backend_preference="gpu")
    if not fused_evaluator.gpu_available:
        return
    reference = _evaluate_without_fusion(snapshot, target)
    fused = fused_evaluator.evaluate_snapshot(snapshot, target, 96, 80)
    assert reference.error is None, reference.error
    assert fused.error is None, fused.error
    assert fused.fused_nodes == 6
    assert fused.fused_passes == 1
    assert fused.gpu_nodes == 2  # Shape plus one fused adjustment pass.
    assert reference.gpu_nodes == 7
    assert np.allclose(reference.image, fused.image, atol=2.0e-7, rtol=0.0)
    fused_traces = [trace for trace in fused.node_traces if trace.type_id == "internal.fused_adjustments"]
    assert len(fused_traces) == 1
    assert "Histogram Range" in fused_traces[0].details
    assert "Clamp" in fused_traces[0].details


def test_long_chain_is_split_into_bounded_fused_passes() -> None:
    type_ids = ["shape.shape"] + ["filter.brightness"] * 10
    updates = [{"shape": "Disc"}] + [{"brightness": 0.01 * (index + 1)} for index in range(10)]
    snapshot, target = _snapshot(type_ids, updates)
    evaluator = GraphEvaluator(backend_preference="gpu")
    if not evaluator.gpu_available:
        return
    result = evaluator.evaluate_snapshot(snapshot, target, 64, 64)
    assert result.error is None, result.error
    assert result.fused_nodes == 10
    assert result.fused_passes == 2
    assert result.gpu_nodes == 3  # Shape plus two bounded fusion passes.


def test_colour_chains_remain_unfused_until_rgba16_rounding_is_exact() -> None:
    snapshot, target = _snapshot(
        ["generator.color", "filter.brightness", "filter.contrast"],
        [
            {"color": "#5d89c7ff"},
            {"brightness": 0.1},
            {"contrast": 0.2, "pivot": 0.43},
        ],
        kind="color",
    )
    evaluator = GraphEvaluator(backend_preference="gpu")
    if not evaluator.gpu_available:
        return
    result = evaluator.evaluate_snapshot(snapshot, target, 32, 32)
    assert result.error is None, result.error
    assert result.fused_nodes == 0
    assert result.fused_passes == 0
    assert result.gpu_nodes == 3


def test_branching_prevents_fusion_across_shared_intermediate() -> None:
    registry = build_registry()
    shape = registry.get("shape.shape")
    brightness = registry.get("filter.brightness")
    gamma = registry.get("filter.gamma")
    clamp = registry.get("filter.clamp")
    blend = registry.get("math.blend")
    nodes = {
        "shape": SnapshotNode("shape", shape, shape.default_parameters(), tuple(shape.inputs), (), "grayscale"),
        "bright": SnapshotNode("bright", brightness, brightness.default_parameters(), tuple(brightness.inputs), (), "grayscale"),
        "gamma": SnapshotNode("gamma", gamma, gamma.default_parameters(), tuple(gamma.inputs), (), "grayscale"),
        "clamp": SnapshotNode("clamp", clamp, clamp.default_parameters(), tuple(clamp.inputs), (), "grayscale"),
        "blend": SnapshotNode("blend", blend, blend.default_parameters(), tuple(blend.inputs), (), "grayscale"),
    }
    inputs = {
        ("bright", "Image"): ("shape", "Image"),
        ("gamma", "Image"): ("bright", "Image"),
        ("clamp", "Image"): ("bright", "Image"),
        ("blend", "Foreground"): ("gamma", "Image"),
        ("blend", "Background"): ("clamp", "Image"),
    }
    evaluator = GraphEvaluator(backend_preference="gpu")
    if not evaluator.gpu_available:
        return
    result = evaluator.evaluate_snapshot(GraphSnapshot(nodes, inputs), "blend", 48, 48)
    assert result.error is None, result.error
    assert result.fused_nodes == 0
    assert result.fused_passes == 0
