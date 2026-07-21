from __future__ import annotations

import numpy as np

from vfx_texture_lab.engine.backends.wgpu_backend import WgpuBackend
from vfx_texture_lab.engine.formats import RenderContext, TextureFormat
from vfx_texture_lab.engine.resources import CpuImage
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext


def _rgba(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    return np.stack((values, values, values, np.ones_like(values)), axis=2)


def _terrain(size: int = 128) -> np.ndarray:
    y, x = np.mgrid[0:size, 0:size]
    u = (x + 0.5) / size
    v = (y + 0.5) / size
    value = (
        0.5
        + 0.30 * np.sin(u * np.pi * 2.0)
        + 0.13 * np.cos(v * np.pi * 4.0)
        + 0.05 * np.sin((u + v) * np.pi * 8.0)
    )
    return np.clip(value, 0.0, 1.0).astype(np.float32)


def main() -> int:
    definition = build_registry().get("terrain.terrace")
    assert definition.inputs == ("Height", "Mask", "Variation")
    params = definition.default_parameters()
    expected_parameters = {
        "spacing_variation", "height_distribution", "seed", "plateau_slope",
        "boundary_breakup", "breakup_scale", "variation_influence", "invert_mask",
    }
    assert expected_parameters.issubset(params)

    size = 128
    context = EvalContext(size, size)
    height = _terrain(size)
    source = _rgba(height)

    # Hard shelves remain a finite set of global elevations even when their
    # boundaries are broken up spatially.
    hard_params = dict(params)
    hard_params.update({"steps": 9, "smoothness": 0.0, "plateau_slope": 0.0})
    hard = definition.evaluator({"Height": source}, hard_params, context)[..., 0]
    assert len(np.unique(np.round(hard, 5))) <= 9

    # Spacing variation and seed alter the elevation layout deterministically.
    uniform_params = dict(hard_params)
    uniform_params.update({"spacing_variation": 0.0, "boundary_breakup": 0.0})
    uniform = definition.evaluator({"Height": source}, uniform_params, context)[..., 0]
    varied_params = dict(uniform_params)
    varied_params.update({"spacing_variation": 0.8, "seed": 17})
    varied = definition.evaluator({"Height": source}, varied_params, context)[..., 0]
    assert float(np.mean(np.abs(varied - uniform))) > 0.015
    assert np.array_equal(varied, definition.evaluator({"Height": source}, varied_params, context)[..., 0])
    second_seed = dict(varied_params); second_seed["seed"] = 23
    varied_second = definition.evaluator({"Height": source}, second_seed, context)[..., 0]
    assert float(np.mean(np.abs(varied_second - varied))) > 0.01

    # Elevation distribution should move terrace density between lowlands and peaks.
    lower_bias_params = dict(uniform_params); lower_bias_params["height_distribution"] = -1.0
    upper_bias_params = dict(uniform_params); upper_bias_params["height_distribution"] = 1.0
    lower_bias = definition.evaluator({"Height": source}, lower_bias_params, context)[..., 0]
    upper_bias = definition.evaluator({"Height": source}, upper_bias_params, context)[..., 0]
    assert float(np.mean(np.abs(lower_bias - upper_bias))) > 0.02

    # The mask blends against the untouched source. Black protects, white applies,
    # and inversion swaps those regions.
    mask = np.zeros_like(height)
    mask[:, size // 2:] = 1.0
    masked = definition.evaluator({"Height": source, "Mask": _rgba(mask)}, params, context)[..., 0]
    full = definition.evaluator({"Height": source}, params, context)[..., 0]
    assert np.allclose(masked[:, :size // 2], height[:, :size // 2], atol=1e-6)
    assert np.allclose(masked[:, size // 2:], full[:, size // 2:], atol=1e-6)
    inverted_params = dict(params); inverted_params["invert_mask"] = True
    inverted = definition.evaluator({"Height": source, "Mask": _rgba(mask)}, inverted_params, context)[..., 0]
    assert np.allclose(inverted[:, size // 2:], height[:, size // 2:], atol=1e-6)
    assert np.allclose(inverted[:, :size // 2], full[:, :size // 2], atol=1e-6)

    # A variation map locally moves boundaries. Mid-grey is neutral.
    y, x = np.mgrid[0:size, 0:size]
    variation = np.clip(0.5 + 0.5 * np.sin(x / size * np.pi * 8.0), 0.0, 1.0).astype(np.float32)
    breakup_params = dict(uniform_params)
    breakup_params.update({"variation_influence": 1.0, "smoothness": 0.08, "plateau_slope": 0.02})
    neutral = definition.evaluator(
        {"Height": source, "Variation": _rgba(np.full_like(height, 0.5))}, breakup_params, context
    )[..., 0]
    mapped = definition.evaluator({"Height": source, "Variation": _rgba(variation)}, breakup_params, context)[..., 0]
    assert float(np.mean(np.abs(mapped - neutral))) > 0.02

    # Plateau slope makes shelves less threshold-like without removing the step edges.
    flat_params = dict(params); flat_params.update({"plateau_slope": 0.0, "smoothness": 0.10})
    sloped_params = dict(flat_params); sloped_params["plateau_slope"] = 0.35
    flat = definition.evaluator({"Height": source}, flat_params, context)[..., 0]
    sloped = definition.evaluator({"Height": source}, sloped_params, context)[..., 0]
    assert float(np.mean(np.abs(sloped - flat))) > 0.01
    assert float(np.mean(np.abs(sloped - height))) < float(np.mean(np.abs(flat - height)))

    # Two differently seeded terrace nodes provide genuinely distinct layers for blending.
    layer_a_params = dict(params); layer_a_params.update({"seed": 3, "spacing_variation": 0.65})
    layer_b_params = dict(params); layer_b_params.update({"seed": 91, "spacing_variation": 0.65, "height_distribution": 0.35})
    layer_a = definition.evaluator({"Height": source}, layer_a_params, context)[..., 0]
    layer_b = definition.evaluator({"Height": source}, layer_b_params, context)[..., 0]
    blended = (layer_a + layer_b) * 0.5
    assert float(np.mean(np.abs(layer_a - layer_b))) > 0.02
    assert float(np.mean(np.abs(blended - layer_a))) > 0.01
    assert float(np.mean(np.abs(blended - layer_b))) > 0.01

    # GPU output should remain close to the CPU reference with all three inputs active.
    gpu = WgpuBackend()
    if gpu.available:
        gpu_size = 64
        gpu_height = _terrain(gpu_size)
        gpu_mask = np.zeros_like(gpu_height); gpu_mask[:, gpu_size // 4:] = 1.0
        gy, gx = np.mgrid[0:gpu_size, 0:gpu_size]
        gpu_variation = np.clip(0.5 + 0.5 * np.sin((gx + gy) / gpu_size * np.pi * 6.0), 0.0, 1.0).astype(np.float32)
        gpu_params = dict(params)
        gpu_params.update({
            "steps": 11, "spacing_variation": 0.7, "height_distribution": -0.25,
            "seed": 37, "boundary_breakup": 0.45, "breakup_scale": 7.0,
            "variation_influence": 0.8, "smoothness": 0.22, "plateau_slope": 0.12,
        })
        cpu = definition.evaluator(
            {"Height": _rgba(gpu_height), "Mask": _rgba(gpu_mask), "Variation": _rgba(gpu_variation)},
            gpu_params,
            EvalContext(gpu_size, gpu_size),
        )[..., 0]
        render_context = RenderContext(gpu_size, gpu_size, TextureFormat.RGBA16F)
        resources = {
            "Height": CpuImage(_rgba(gpu_height), TextureFormat.R16F, "terrace-height", data_kind="grayscale"),
            "Mask": CpuImage(_rgba(gpu_mask), TextureFormat.R16F, "terrace-mask", data_kind="grayscale"),
            "Variation": CpuImage(_rgba(gpu_variation), TextureFormat.R16F, "terrace-variation", data_kind="grayscale"),
        }
        result = gpu.evaluate_node(
            definition, resources, gpu_params, render_context, "terrace-overhaul-gpu", TextureFormat.R16F,
        )
        gpu_array = gpu.to_cpu(result).array[..., 0]
        difference = np.abs(cpu - gpu_array)
        assert float(difference.mean()) < 0.005
        assert float(difference.max()) < 0.08

    print(
        "Terrace overhaul test passed: irregular spacing, elevation distribution, seeds, masks, "
        "variation maps, boundary breakup, plateau slope, blendable layers and GPU parity"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
