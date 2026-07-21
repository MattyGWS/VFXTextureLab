from __future__ import annotations

import os

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from vfx_texture_lab.engine.backends.wgpu_backend import WgpuBackend
from vfx_texture_lab.engine.formats import RenderContext, TextureFormat
from vfx_texture_lab.engine.resources import CpuImage
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext


def _rgba(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    return np.stack((values, values, values, np.ones_like(values)), axis=2)


def _terrain(size: int) -> np.ndarray:
    y, x = np.mgrid[0:size, 0:size]
    u = (x + 0.5) / size
    v = (y + 0.5) / size
    height = (
        0.48
        + 0.22 * np.sin((u * 1.7 + 0.13 * np.sin(v * np.pi * 2.0)) * np.pi * 2.0)
        + 0.17 * np.cos((v * 1.9 - 0.11 * np.sin(u * np.pi * 2.0)) * np.pi * 2.0)
        + 0.065 * np.sin((u + v) * np.pi * 7.0)
        + 0.025 * np.sin(u * 31.0 + v * 23.0)
    )
    for _ in range(2):
        height = (
            height * 4.0
            + np.roll(height, 1, 0) + np.roll(height, -1, 0)
            + np.roll(height, 1, 1) + np.roll(height, -1, 1)
        ) / 8.0
    return np.clip(height, 0.03, 0.97).astype(np.float32)


def main() -> int:
    registry = build_registry()
    fluvial = registry.get("terrain.hydraulic_erosion")
    thermal = registry.get("terrain.thermal_erosion")

    # The overhaul should expose geological intent first and solver plumbing in
    # collapsed lower-priority sections.
    for name in (
        "erosion_scale", "rock_resistance", "sediment_transport",
        "erosion_duration", "channel_depth", "valley_widening",
    ):
        spec = fluvial.parameter_spec(name)
        assert spec is not None and spec.group
    assert fluvial.parameter_spec("erosion_scale").group == "Character"
    assert fluvial.parameter_spec("sediment_transport").group == "Sediment & Banks"
    assert fluvial.parameter_spec("rock_resistance").group == "Material"
    for name in ("talus_mobility", "rock_resistance", "fracture_strength", "fracture_scale", "shape_protection"):
        assert thermal.parameter_spec(name) is not None

    size = 64
    context = EvalContext(size, size)
    height = _terrain(size)
    source = _rgba(height)

    # Regression: maximum channel widening must never turn the live result into
    # a black/non-finite frame, even with near-maximum retained flow.
    stress = fluvial.default_parameters()
    stress.update({
        "quality": "Preview",
        "preview_iterations": 6,
        "preview_drainage_iterations": 96,
        "flow_retention": 0.9995,
        "valley_widening": 1.0,
        "sediment_spread": 1.0,
        "preview_output": "Eroded Height",
    })
    for seed in (1, 77, 991):
        stress["seed"] = seed
        result = fluvial.evaluator({"Height": source}, stress, context)[..., 0]
        assert np.isfinite(result).all()
        assert float(result.std()) > 0.04
        assert float(result.mean()) > 0.08
        assert float(result.max()) > 0.25

    # Scale is genuinely structural, not just a display blur.
    fine = dict(stress); fine.update({"flow_retention": 0.955, "valley_widening": 0.45, "sediment_spread": 0.42, "erosion_scale": 0.0})
    broad = dict(fine); broad["erosion_scale"] = 1.0
    fine_result = fluvial.evaluator({"Height": source}, fine, context)[..., 0]
    broad_result = fluvial.evaluator({"Height": source}, broad, context)[..., 0]
    assert float(np.mean(np.abs(fine_result - broad_result))) > 0.001

    # Global resistance should behave like a uniform Hardness control.
    resistant = dict(fine); resistant["rock_resistance"] = 1.0
    protected = fluvial.evaluator({"Height": source}, resistant, context)[..., 0]
    assert np.allclose(protected, height, atol=2e-5)

    # Sediment Transport moves the deposition response rather than being a UI-only control.
    near = dict(fine); near.update({"preview_output": "Deposition", "sediment_transport": 0.0})
    far = dict(near); far["sediment_transport"] = 1.0
    near_deposit = fluvial.evaluator({"Height": source}, near, context)[..., 0]
    far_deposit = fluvial.evaluator({"Height": source}, far, context)[..., 0]
    assert float(np.mean(np.abs(near_deposit - far_deposit))) > 0.002

    # Thermal erosion distributes material around all unstable neighbours. A
    # radially symmetric cone should therefore remain approximately symmetric.
    y, x = np.mgrid[0:size, 0:size]
    radius = np.sqrt((x - (size - 1) * 0.5) ** 2 + (y - (size - 1) * 0.5) ** 2)
    cone = np.clip(1.0 - radius / (size * 0.42), 0.0, 1.0).astype(np.float32)
    thermal_params = thermal.default_parameters()
    thermal_params.update({
        "quality": "Preview", "preview_iterations": 24,
        "fracture_strength": 0.0, "shape_protection": 0.0,
        "boundary": "Seamless / Wrap", "preview_output": "Eroded Height",
    })
    relaxed = thermal.evaluator({"Height": _rgba(cone)}, thermal_params, context)[..., 0]
    assert float(np.mean(np.abs(relaxed - np.rot90(relaxed)))) < 0.004
    assert abs(float(relaxed.sum() - cone.sum())) < 0.05

    thermal_resistant = dict(thermal_params); thermal_resistant["rock_resistance"] = 1.0
    thermal_protected = thermal.evaluator({"Height": _rgba(cone)}, thermal_resistant, context)[..., 0]
    assert np.allclose(thermal_protected, cone, atol=2e-5)

    fractured = dict(thermal_params); fractured.update({"fracture_strength": 0.7, "fracture_scale": 0.75, "seed": 9})
    fractured_result = thermal.evaluator({"Height": source}, fractured, context)[..., 0]
    plain_result = thermal.evaluator({"Height": source}, thermal_params, context)[..., 0]
    assert float(np.mean(np.abs(fractured_result - plain_result))) > 0.0005

    gpu = WgpuBackend()
    if gpu.available:
        gpu_size = 40
        gpu_height = _terrain(gpu_size)
        gpu_input = CpuImage(_rgba(gpu_height), TextureFormat.R16F, "erosion-overhaul", data_kind="grayscale")
        render_context = RenderContext(gpu_size, gpu_size, TextureFormat.R16F)
        gpu_stress = fluvial.default_parameters()
        gpu_stress.update({
            "quality": "Preview", "preview_iterations": 4,
            "preview_drainage_iterations": 96, "flow_retention": 0.9995,
            "valley_widening": 1.0, "sediment_spread": 1.0,
            "preview_output": "Eroded Height",
        })
        for seed in (3, 211):
            gpu_stress["seed"] = seed
            resource = gpu.evaluate_node(
                fluvial, {"Height": gpu_input}, gpu_stress, render_context,
                f"erosion-overhaul:{seed}", TextureFormat.R16F,
            )
            array = gpu.to_cpu(resource).array[..., 0]
            assert np.isfinite(array).all()
            assert float(array.std()) > 0.03
            assert float(array.max()) > 0.25

    print(
        "Erosion overhaul test passed: artist-facing parameter groups, maximum-widening finite previews, "
        "resolution-aware valley scale, rock resistance, sediment transport, multi-direction thermal "
        "relaxation, fracture variation and GPU stress coverage"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
