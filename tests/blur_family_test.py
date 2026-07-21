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


def test_directional_blur_positive_angle_matches_application_convention() -> None:
    registry = build_registry()
    definition = registry.get("filter.directional_blur")
    width = height = 41
    impulse = np.zeros((height, width), dtype=np.float32)
    impulse[height // 2, width // 2] = 1.0
    source = grayscale_rgba(impulse)
    params = definition.default_parameters()
    params.update({"distance": 10.0, "angle": 45.0, "samples": 41})
    result = definition.evaluator({"Image": source}, params, EvalContext(width, height))[..., 0]

    centre = width // 2
    # Positive 45 degrees follows the same screen-space convention used by
    # Directional Warp: its blur line runs top-left to bottom-right.
    assert result[centre + 5, centre + 5] > 0.01
    assert result[centre - 5, centre - 5] > 0.01
    assert result[centre - 5, centre + 5] < 1.0e-5
    assert result[centre + 5, centre - 5] < 1.0e-5


def test_directional_blur_cpu_gpu_orientation_agreement() -> None:
    registry = build_registry()
    definition = registry.get("filter.directional_blur")
    gpu = WgpuBackend()
    if not gpu.available:
        return
    cpu = CpuBackend(gpu)
    width, height = 51, 43
    context = RenderContext(width, height, TextureFormat.R16F)
    impulse = np.zeros((height, width), dtype=np.float32)
    impulse[height // 2, width // 2] = 1.0
    source = CpuImage(
        grayscale_rgba(impulse), TextureFormat.R16F, "directional-impulse",
        frozenset({"cpu"}), "grayscale", "16-bit",
    )
    params = definition.default_parameters()
    params.update({"distance": 11.0, "angle": 37.0, "samples": 31})
    cpu_result = cpu.evaluate_node(definition, {"Image": source}, params, context, "directional-cpu")
    gpu_source = gpu.ensure_gpu(source, context)
    gpu_result = gpu.to_cpu(gpu.evaluate_node(definition, {"Image": gpu_source}, params, context, "directional-gpu"))
    difference = np.abs(cpu_result.array - gpu_result.array)
    assert float(difference.mean()) < 5.0e-4, (difference.mean(), difference.max())
    assert float(np.quantile(difference, 0.99)) < 5.0e-3, (difference.mean(), difference.max())
    gpu_values = gpu_result.array[..., 0]
    centre_x, centre_y = width // 2, height // 2
    assert gpu_values[centre_y + 5, centre_x + 7] > 0.005
    assert gpu_values[centre_y - 5, centre_x - 7] > 0.005
    assert gpu_values[centre_y - 5, centre_x + 7] < 1.0e-5
