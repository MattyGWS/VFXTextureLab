from __future__ import annotations

import os
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.engine import GraphEvaluator
from vfx_texture_lab.engine.backends.base import BackendCancelled
from vfx_texture_lab.engine.backends.wgpu_backend import WgpuBackend
from vfx_texture_lab.engine.formats import RenderContext, TextureFormat
from vfx_texture_lab.engine.resources import CpuImage
from vfx_texture_lab.graph.scene import GraphScene
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext


def _rgba(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    return np.stack((values, values, values, np.ones_like(values)), axis=2)


def _terrain(size: int = 72) -> np.ndarray:
    y, x = np.mgrid[0:size, 0:size]
    u = (x + 0.5) / size
    v = (y + 0.5) / size
    value = (
        0.42
        + 0.22 * np.sin(u * np.pi * 4.0)
        + 0.16 * np.cos(v * np.pi * 6.0)
        + 0.10 * np.sin((u + v) * np.pi * 10.0)
    )
    return np.clip(value, 0.0, 1.0).astype(np.float32)


def main() -> int:
    registry = build_registry()
    expected = {
        "terrain.slope",
        "terrain.curvature",
        "terrain.terrace",
        "terrain.height_combine",
        "terrain.height_blend",
        "terrain.thermal_erosion",
    }
    assert expected.issubset({definition.type_id for definition in registry.all()})

    context = EvalContext(72, 72)
    height = _terrain(72)
    source = _rgba(height)

    slope = registry.get("terrain.slope")
    slope_out = slope.evaluator({"Height": source}, slope.default_parameters(), context)[..., 0]
    assert float(slope_out.std()) > 0.08
    assert 0.0 <= float(slope_out.min()) <= float(slope_out.max()) <= 1.0

    curvature = registry.get("terrain.curvature")
    curvature_modes = []
    for mode in ("Signed", "Convex", "Concave", "Absolute"):
        params = curvature.default_parameters(); params["mode"] = mode
        params["strength"] = float(params["strength"]) / ((context.width / 512.0) ** 2)
        curvature_modes.append(curvature.evaluator({"Height": source}, params, context)[..., 0])
    assert float(np.mean(np.abs(curvature_modes[1] - curvature_modes[2]))) > 0.03

    terrace = registry.get("terrain.terrace")
    terrace_params = terrace.default_parameters(); terrace_params.update({"steps": 7, "smoothness": 0.0, "plateau_slope": 0.0})
    terrace_out = terrace.evaluator({"Height": source}, terrace_params, context)[..., 0]
    assert len(np.unique(np.round(terrace_out, 5))) <= 8

    combine = registry.get("terrain.height_combine")
    combine_params = combine.default_parameters(); combine_params["mode"] = "Maximum"
    combined = combine.evaluator({"A": source, "B": _rgba(1.0 - height)}, combine_params, context)[..., 0]
    assert np.allclose(combined, np.maximum(height, 1.0 - height), atol=1e-6)

    blend = registry.get("terrain.height_blend")
    blend_params = blend.default_parameters(); blend_params.update({"transition": 0.04, "opacity": 1.0})
    blended = blend.evaluator({"Base": source, "Layer": _rgba(1.0 - height)}, blend_params, context)[..., 0]
    assert float(np.mean(np.abs(blended - height))) > 0.08

    thermal = registry.get("terrain.thermal_erosion")
    thermal_params = thermal.default_parameters()
    thermal_params.update({
        "quality": "Preview",
        "preview_iterations": 12,
        "erosion_strength": 0.22,
        "max_transfer": 0.012,
        "boundary": "Seamless / Wrap",
    })
    thermal_params["preview_output"] = "Eroded Height"
    eroded = thermal.evaluator({"Height": source}, thermal_params, context)[..., 0]
    assert float(np.mean(np.abs(eroded - height))) > 0.002
    assert abs(float(eroded.sum() - height.sum())) < 0.02

    thermal_params["preview_output"] = "Erosion"
    erosion = thermal.evaluator({"Height": source}, thermal_params, context)[..., 0]
    thermal_params["preview_output"] = "Deposition"
    deposition = thermal.evaluator({"Height": source}, thermal_params, context)[..., 0]
    assert float(erosion.max()) > 0.01 and float(deposition.max()) > 0.01
    assert float(erosion.mean()) > 0.001 and float(deposition.mean()) > 0.001

    # White hardness must protect the terrain completely.
    thermal_params["preview_output"] = "Eroded Height"
    protected = thermal.evaluator(
        {"Height": source, "Hardness": _rgba(np.ones_like(height))}, thermal_params, context
    )[..., 0]
    assert np.allclose(protected, height, atol=1e-6)

    # Seamless boundary behaviour must be translation equivariant.
    shifted_source = np.roll(source, shift=(7, -11), axis=(0, 1))
    shifted_result = thermal.evaluator({"Height": shifted_source}, thermal_params, context)[..., 0]
    assert np.allclose(shifted_result, np.roll(eroded, shift=(7, -11), axis=(0, 1)), atol=2e-5)

    # Multi-output processor sockets must retain the original input branch.
    app = QApplication.instance() or QApplication([])
    scene = GraphScene(registry)
    source_node = scene.create_node("noise.ridged", QPointF(0, 0), record_undo=False)
    erosion_node = scene.create_node("terrain.thermal_erosion", QPointF(260, 0), record_undo=False)
    erosion_node.parameters.update({"quality": "Preview", "preview_iterations": 4})
    outputs = [
        scene.create_node("output.image", QPointF(560, y), record_undo=False)
        for y in (-120, 0, 120)
    ]
    scene.add_connection(source_node.output_port, erosion_node.input_ports["Height"], record_undo=False)
    for output_node, output_name in zip(outputs, thermal.output_names):
        scene.add_connection(erosion_node.output_ports[output_name], output_node.input_ports["Image"], record_undo=False)
    evaluator = GraphEvaluator(scene, backend_preference="cpu")
    results = [evaluator.evaluate(node.uid, 48, 48) for node in outputs]
    assert all(not result.error for result in results)
    assert float(np.mean(np.abs(results[0].image - results[1].image))) > 0.02
    assert float(np.mean(np.abs(results[1].image - results[2].image))) > 0.005

    # GPU execution should stay GPU-resident and visually match the CPU path.
    gpu = WgpuBackend()
    if gpu.available:
        render_context = RenderContext(48, 48, TextureFormat.RGBA16F)
        small = _terrain(48); small_rgba = _rgba(small)
        cpu_params = thermal.default_parameters(); cpu_params.update({
            "quality": "Preview", "preview_iterations": 5,
            "erosion_strength": 0.18, "max_transfer": 0.008,
        })
        cpu_result = thermal.evaluator({"Height": small_rgba}, cpu_params, EvalContext(48, 48))[..., 0]
        gpu_input = CpuImage(small_rgba, TextureFormat.R16F, "terrain-test", data_kind="grayscale")
        gpu_result = gpu.to_cpu(gpu.evaluate_node(
            thermal, {"Height": gpu_input}, cpu_params, render_context,
            "terrain-test-gpu", TextureFormat.R16F,
        )).array[..., 0]
        difference = np.abs(cpu_result - gpu_result)
        assert float(difference.mean()) < 0.025
        assert abs(float(gpu_result.sum() - small.sum())) < 4.0

        cancelled_params = dict(cpu_params)
        cancelled_params["preview_iterations"] = 500
        try:
            gpu.evaluate_node(
                thermal, {"Height": gpu_input}, cancelled_params, render_context,
                "terrain-test-cancel", TextureFormat.R16F, cancel_check=lambda: True,
            )
        except BackendCancelled:
            pass
        else:
            raise AssertionError("Thermal erosion did not honour backend cancellation")

    print(
        "Terrain foundation test passed: slope, curvature, terrace, height combine/blend, "
        "multi-pass thermal erosion, hardness masks, seamless boundaries, named outputs and GPU execution"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
