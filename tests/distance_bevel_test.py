from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from vfx_texture_lab.engine.backends.cpu import CpuBackend
from vfx_texture_lab.engine.backends.wgpu_backend import WgpuBackend
from vfx_texture_lab.engine.formats import RenderContext, TextureFormat
from vfx_texture_lab.engine.resources import CpuImage
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext
from vfx_texture_lab.nodes.image_ops import grayscale_rgba


NODE_IDS = {"filter.distance", "filter.bevel"}


def test_registry_contract() -> None:
    registry = build_registry()
    assert NODE_IDS <= {definition.type_id for definition in registry.all()}
    distance = registry.get("filter.distance")
    bevel = registry.get("filter.bevel")
    assert distance.gpu_kernel == "distance.wgsl"
    assert bevel.gpu_kernel == "bevel.wgsl"
    assert distance.input_kind("Image") == "grayscale"
    assert bevel.output_kind("Image") == "grayscale"
    assert {spec.group for spec in distance.parameters} >= {"Distance", "Profile", "Input", "Output"}
    assert {spec.group for spec in bevel.parameters} >= {"Bevel", "Height", "Input", "Output"}


def _wrapped_mask(width: int, height: int) -> np.ndarray:
    mask = np.zeros((height, width), dtype=np.float32)
    mask[6:height - 6, :5] = 1.0
    mask[6:height - 6, -5:] = 1.0
    mask[height // 2 - 5:height // 2 + 5, width // 2 - 8:width // 2 + 8] = 1.0
    return mask


def test_distance_modes_and_toroidal_seam() -> None:
    registry = build_registry()
    definition = registry.get("filter.distance")
    width, height = 48, 36
    source = grayscale_rgba(_wrapped_mask(width, height))
    context = EvalContext(width, height)

    params = definition.default_parameters()
    params.update({"distance": 12.0, "mode": "Inside"})
    inside = definition.evaluator({"Image": source}, params, context)[..., 0]
    assert np.isfinite(inside).all()
    # Opposite pieces of the wrapped bar are one continuous region; the border
    # itself is the middle of the bar, not an artificial zero-distance seam.
    assert inside[height // 2, 0] > inside[height // 2, 4]
    assert np.allclose(inside[:, :5], inside[:, -5:][:, ::-1], atol=1.0e-6)

    params["mode"] = "Outside"
    outside = definition.evaluator({"Image": source}, params, context)[..., 0]
    assert np.all(outside[source[..., 0] > 0.5] == 0.0)
    assert float(outside[source[..., 0] < 0.5].max()) > 0.25

    params["mode"] = "Signed"
    signed = definition.evaluator({"Image": source}, params, context)[..., 0]
    assert float(signed[source[..., 0] > 0.5].min()) >= 0.5
    assert float(signed[source[..., 0] < 0.5].max()) <= 0.5

    params["mode"] = "Absolute"
    absolute = definition.evaluator({"Image": source}, params, context)[..., 0]
    assert float(absolute.max()) > 0.25
    assert float(absolute.min()) <= 1.0 / 12.0


def test_bevel_profiles_and_directions() -> None:
    registry = build_registry()
    definition = registry.get("filter.bevel")
    width = height = 64
    mask = np.zeros((height, width), dtype=np.float32)
    mask[16:48, 16:48] = 1.0
    source = grayscale_rgba(mask)
    context = EvalContext(width, height)

    profiles = ("Linear", "Smooth", "Rounded", "Concave", "Convex")
    results = []
    for profile in profiles:
        params = definition.default_parameters()
        params.update({"profile": profile, "width": 10.0, "direction": "Inner"})
        result = definition.evaluator({"Image": source}, params, context)[..., 0]
        assert np.isfinite(result).all()
        assert result[32, 32] > 0.99
        assert result[15, 32] == 0.0
        results.append(result)
    assert any(not np.allclose(results[0], candidate) for candidate in results[1:])

    for direction in ("Outer", "Centered", "Edge Ridge"):
        params = definition.default_parameters()
        params.update({"direction": direction, "width": 8.0})
        result = definition.evaluator({"Image": source}, params, context)[..., 0]
        assert np.isfinite(result).all()
        assert float(result.max()) > 0.9
    ridge_params = definition.default_parameters()
    ridge_params.update({"direction": "Edge Ridge", "width": 8.0})
    ridge = definition.evaluator({"Image": source}, ridge_params, context)[..., 0]
    assert ridge[16, 32] > ridge[32, 32]


def test_empty_and_full_masks_remain_finite() -> None:
    registry = build_registry()
    context = EvalContext(40, 32)
    for fill in (0.0, 1.0):
        source = grayscale_rgba(np.full((context.height, context.width), fill, dtype=np.float32))
        for type_id in NODE_IDS:
            definition = registry.get(type_id)
            result = definition.evaluator({"Image": source}, definition.default_parameters(), context)
            assert np.isfinite(result).all(), (type_id, fill)
            assert float(result[..., 0].min()) >= 0.0
            assert float(result[..., 0].max()) <= 1.0


def test_cpu_gpu_agreement() -> None:
    registry = build_registry()
    gpu = WgpuBackend()
    if not gpu.available:
        return
    cpu = CpuBackend(gpu)
    width, height = 73, 57
    y, x = np.mgrid[0:height, 0:width]
    mask = (((x - 18) ** 2 + (y - 21) ** 2) < 13 ** 2) | (x < 4) | (x >= width - 4)
    source_array = grayscale_rgba(mask.astype(np.float32))
    source = CpuImage(source_array, TextureFormat.R16F, "distance-mask", frozenset({"cpu"}), "grayscale", "16-bit")
    context = RenderContext(width, height, TextureFormat.R16F)

    cases = (
        ("filter.distance", {"mode": "Signed", "distance": 19.0, "edge_offset": 2.5, "curve": 1.4, "smoothness": 0.35}),
        ("filter.bevel", {"direction": "Centered", "profile": "Concave", "width": 11.0, "edge_offset": -1.0, "smoothness": 0.2}),
        ("filter.bevel", {"direction": "Edge Ridge", "profile": "Rounded", "width": 7.0}),
    )
    for type_id, overrides in cases:
        definition = registry.get(type_id)
        params = definition.default_parameters()
        params.update(overrides)
        cpu_result = cpu.evaluate_node(definition, {"Image": source}, params, context, f"cpu:{type_id}:{overrides}")
        gpu_source = gpu.ensure_gpu(source, context)
        gpu_result = gpu.to_cpu(gpu.evaluate_node(definition, {"Image": gpu_source}, params, context, f"gpu:{type_id}:{overrides}"))
        difference = np.abs(cpu_result.array - gpu_result.array)
        # Wrapped jump-flood ties can select another equally close seed at a
        # handful of seam pixels; profile shaping can amplify those isolated
        # values while the image-wide field remains equivalent.
        mean_limit = 0.001 if type_id == "filter.bevel" else 2.0e-4
        max_limit = 0.4 if type_id == "filter.bevel" else 0.1
        assert float(difference.mean()) < mean_limit, (type_id, difference.mean(), difference.max())
        assert float(difference.max()) < max_limit, (type_id, difference.mean(), difference.max())
