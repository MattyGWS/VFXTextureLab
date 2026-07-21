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


NODE_IDS = {"filter.expand_shrink", "filter.outline", "filter.aperture"}


def _mask(width: int, height: int) -> np.ndarray:
    y, x = np.mgrid[0:height, 0:width]
    return ((((x - width * 0.35) ** 2 + (y - height * 0.5) ** 2) < (min(width, height) * 0.22) ** 2) | (x < 3) | (x >= width - 3)).astype(np.float32)


def test_registry_and_gpu_contract() -> None:
    registry = build_registry()
    assert NODE_IDS <= {definition.type_id for definition in registry.all()}
    assert registry.get("filter.expand_shrink").gpu_kernel == "expand_shrink.wgsl"
    assert registry.get("filter.outline").gpu_kernel == "outline.wgsl"
    aperture = registry.get("filter.aperture")
    assert aperture.gpu_kernel == "aperture_step.wgsl"
    assert aperture.input_kind("Image") == "grayscale"
    assert {spec.default for spec in aperture.parameters if spec.name == "shape"} == {"Disk"}


def test_expand_shrink_open_close_and_outline() -> None:
    registry = build_registry()
    context = EvalContext(72, 56)
    source = grayscale_rgba(_mask(context.width, context.height))
    morphology = registry.get("filter.expand_shrink")
    means: dict[str, float] = {}
    for operation in ("Expand", "Shrink", "Open", "Close"):
        params = morphology.default_parameters()
        params.update({"operation": operation, "amount": 5.0, "softness": 0.5})
        result = morphology.evaluator({"Image": source}, params, context)[..., 0]
        assert np.isfinite(result).all()
        means[operation] = float(result.mean())
    assert means["Expand"] > float(source[..., 0].mean())
    assert means["Shrink"] < float(source[..., 0].mean())

    outline = registry.get("filter.outline")
    for direction in ("Inner", "Outer", "Centered"):
        params = outline.default_parameters()
        params.update({"direction": direction, "width": 7.0, "softness": 0.75})
        result = outline.evaluator({"Image": source}, params, context)[..., 0]
        assert np.isfinite(result).all()
        assert float(result.max()) > 0.95
        assert float(result.mean()) < 0.4




def test_aperture_disk_and_polygon_use_distinct_filled_footprints() -> None:
    registry = build_registry()
    definition = registry.get("filter.aperture")
    width = height = 41
    impulse = np.zeros((height, width), dtype=np.float32)
    impulse[height // 2, width // 2] = 1.0
    source = grayscale_rgba(impulse)
    context = EvalContext(width, height)

    results: dict[tuple[str, int], np.ndarray] = {}
    for shape, vertices in (("Disk", 6), ("Polygon", 3), ("Polygon", 4), ("Polygon", 6), ("Polygon", 8)):
        params = definition.default_parameters()
        params.update({
            "mode": "Dilation", "shape": shape, "size": 8,
            "vertices": vertices, "antialiased": False, "boundary": "Clamp",
        })
        results[(shape, vertices)] = definition.evaluator({"Image": source}, params, context)[..., 0] > 0.5

    disk = results[("Disk", 6)]
    assert not disk[12, 12] and not disk[12, 28] and not disk[28, 12] and not disk[28, 28]
    assert int(disk.sum()) < 17 * 17  # It must not be a square footprint.
    assert not np.array_equal(results[("Polygon", 3)], results[("Polygon", 4)])
    assert not np.array_equal(results[("Polygon", 4)], results[("Polygon", 6)])
    assert not np.array_equal(results[("Polygon", 6)], results[("Polygon", 8)])

def test_aperture_reshapes_grayscale_height_not_only_binary_masks() -> None:
    registry = build_registry()
    definition = registry.get("filter.aperture")
    width, height = 80, 60
    y, x = np.mgrid[0:height, 0:width]
    values = np.clip(0.45 + 0.22 * np.sin(x / 5.0) + 0.18 * np.cos(y / 7.0), 0.0, 1.0).astype(np.float32)
    source = grayscale_rgba(values)
    context = EvalContext(width, height)

    dilation_params = definition.default_parameters()
    dilation_params.update({"mode": "Dilation", "shape": "Disk", "size": 5})
    dilation = definition.evaluator({"Image": source}, dilation_params, context)[..., 0]
    erosion_params = definition.default_parameters()
    erosion_params.update({"mode": "Erosion", "shape": "Line", "size": 5, "direction": 35.0})
    erosion = definition.evaluator({"Image": source}, erosion_params, context)[..., 0]
    assert float(dilation.mean()) > float(values.mean())
    assert float(erosion.mean()) < float(values.mean())
    assert np.count_nonzero((dilation > 0.0) & (dilation < 1.0)) > width * height // 2
    assert np.count_nonzero((erosion > 0.0) & (erosion < 1.0)) > width * height // 2


def test_cpu_gpu_agreement() -> None:
    registry = build_registry()
    gpu = WgpuBackend()
    if not gpu.available:
        return
    cpu = CpuBackend(gpu)
    width, height = 67, 53
    context = RenderContext(width, height, TextureFormat.R16F)
    source_array = grayscale_rgba(_mask(width, height))
    source = CpuImage(source_array, TextureFormat.R16F, "morph-source", frozenset({"cpu"}), "grayscale", "16-bit")

    cases = (
        ("filter.expand_shrink", {"operation": "Expand", "amount": 7.0, "softness": 1.0}),
        ("filter.expand_shrink", {"operation": "Shrink", "amount": 4.0}),
        ("filter.expand_shrink", {"operation": "Open", "amount": 3.0}),
        ("filter.expand_shrink", {"operation": "Close", "amount": 3.0}),
        ("filter.outline", {"direction": "Inner", "width": 8.0, "softness": 1.0}),
        ("filter.outline", {"direction": "Centered", "width": 9.0}),
    )
    for index, (type_id, overrides) in enumerate(cases):
        definition = registry.get(type_id)
        params = definition.default_parameters()
        params.update(overrides)
        cpu_result = cpu.evaluate_node(definition, {"Image": source}, params, context, f"morph-cpu:{index}")
        gpu_source = gpu.ensure_gpu(source, context)
        gpu_result = gpu.to_cpu(gpu.evaluate_node(definition, {"Image": gpu_source}, params, context, f"morph-gpu:{index}"))
        difference = np.abs(cpu_result.array - gpu_result.array)
        if type_id == "filter.expand_shrink" and overrides.get("operation") in {"Open", "Close"}:
            # The second wrapped jump-flood pass can choose a different equal-
            # distance seed at a few seam pixels while producing the same mask.
            assert float(difference.mean()) < 0.02, (type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.98)) < 0.05, (type_id, difference.mean(), difference.max())
        elif type_id == "filter.outline":
            assert float(difference.mean()) < 0.005, (type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.99)) < 0.02, (type_id, difference.mean(), difference.max())
        else:
            assert float(difference.max()) < 2.0e-3, (type_id, difference.mean(), difference.max())

    y, x = np.mgrid[0:height, 0:width]
    height_values = np.clip(0.42 + 0.27 * np.sin(x / 6.0) + 0.19 * np.cos(y / 8.0), 0.0, 1.0).astype(np.float32)
    height_source = CpuImage(grayscale_rgba(height_values), TextureFormat.R16F, "aperture-source", frozenset({"cpu"}), "grayscale", "16-bit")
    aperture = registry.get("filter.aperture")
    aperture_cases = (
        {"mode": "Dilation", "shape": "Disk", "size": 4},
        {"mode": "Erosion", "shape": "Line", "size": 5, "direction": 35.0},
        {"mode": "Dilation", "shape": "Polygon", "size": 3, "vertices": 5, "direction": 12.0},
        {"mode": "Dilation", "shape": "Asterisk", "size": 3, "vertices": 7, "direction": 18.0},
        {"mode": "Dilation", "shape": "Corner", "size": 3, "direction": 20.0, "corner_angle": 70.0},
        {"mode": "Erosion", "shape": "Disk", "size": 3, "strength": 0.45},
    )
    for index, overrides in enumerate(aperture_cases):
        params = aperture.default_parameters()
        params.update(overrides)
        cpu_result = cpu.evaluate_node(aperture, {"Image": height_source}, params, context, f"aperture-cpu:{index}")
        gpu_source = gpu.ensure_gpu(height_source, context)
        gpu_result = gpu.to_cpu(gpu.evaluate_node(aperture, {"Image": gpu_source}, params, context, f"aperture-gpu:{index}"))
        difference = np.abs(cpu_result.array - gpu_result.array)
        assert float(difference.max()) < 2.0e-3, (overrides, difference.mean(), difference.max())
