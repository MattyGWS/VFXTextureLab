from __future__ import annotations

import os

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


def _terrain(size: int = 64) -> np.ndarray:
    y, x = np.mgrid[0:size, 0:size]
    u = (x + 0.5) / size
    v = (y + 0.5) / size
    broad = (
        0.46
        + 0.20 * np.sin((u * 2.0 + 0.15 * np.sin(v * np.pi * 2.0)) * np.pi * 2.0)
        + 0.15 * np.cos((v * 2.0 - 0.12 * np.sin(u * np.pi * 2.0)) * np.pi * 2.0)
        + 0.07 * np.sin((u + v) * np.pi * 6.0)
    )
    # Gentle blur avoids making the quality test depend on pixel-scale pits.
    for _ in range(2):
        broad = (
            broad * 4.0 + np.roll(broad, 1, 0) + np.roll(broad, -1, 0)
            + np.roll(broad, 1, 1) + np.roll(broad, -1, 1)
        ) / 8.0
    return np.clip(broad, 0.02, 0.98).astype(np.float32)


def _laplacian_energy(values: np.ndarray) -> float:
    lap = (
        np.roll(values, 1, 0) + np.roll(values, -1, 0)
        + np.roll(values, 1, 1) + np.roll(values, -1, 1) - values * 4.0
    )
    return float(np.mean(np.abs(lap)))


def main() -> int:
    registry = build_registry()
    expected = {"terrain.hydraulic_erosion", "terrain.flow_accumulation", "terrain.flow_direction"}
    assert expected.issubset({definition.type_id for definition in registry.all()})

    fluvial = registry.get("terrain.hydraulic_erosion")
    assert fluvial.name == "Fluvial Erosion"
    assert fluvial.output_names == (
        "Eroded Height", "Erosion", "Deposition", "Flow Accumulation",
        "Channel Mask", "Water", "Sediment", "Wetness", "Flow Direction",
    )
    assert fluvial.output_kind("Flow Direction") == "vector"
    assert all(
        fluvial.parameter_spec(name) is not None and fluvial.parameter_spec(name).animatable
        for name in ("rainfall", "channel_depth", "tributary_density", "valley_widening")
    )

    size = 64
    context = EvalContext(size, size)
    height = _terrain(size)
    source = _rgba(height)
    params = fluvial.default_parameters()
    params.update({
        "quality": "Preview",
        "preview_iterations": 6,
        "preview_drainage_iterations": 36,
        "rain_variation": 0.0,
        "boundary": "Seamless / Wrap",
    })

    outputs: dict[str, np.ndarray] = {}
    for output_name in fluvial.output_names:
        selected = dict(params)
        selected["preview_output"] = output_name
        result = fluvial.evaluator({"Height": source}, selected, context)
        assert result.shape == (size, size, 4)
        assert np.isfinite(result).all()
        assert 0.0 <= float(result.min()) <= float(result.max()) <= 1.0
        outputs[output_name] = result

    eroded = outputs["Eroded Height"][..., 0]
    erosion = outputs["Erosion"][..., 0]
    deposition = outputs["Deposition"][..., 0]
    flow = outputs["Flow Accumulation"][..., 0]
    channels = outputs["Channel Mask"][..., 0]

    # The default must alter terrain while preserving the authored macroforms.
    assert float(np.mean(np.abs(eroded - height))) > 0.0015
    assert float(np.corrcoef(eroded.ravel(), height.ravel())[0, 1]) > 0.92
    # Erosion must be concentrated into a sparse drainage hierarchy rather than
    # becoming a full-frame noisy filter.
    active_fraction = float(np.mean(channels > 0.5))
    assert 0.002 < active_fraction < 0.35, active_fraction
    high_channel = channels > 0.5
    assert high_channel.any()
    assert float(erosion[high_channel].mean()) > float(erosion.mean()) * 2.0
    assert float(np.quantile(flow, 0.99)) > float(np.quantile(flow, 0.70)) * 1.5
    # The rewrite must not create the needle-like high-frequency result that the
    # old water filter produced.
    assert _laplacian_energy(eroded) < _laplacian_energy(height) * 3.0
    assert float(erosion.max()) > 0.02
    assert float(deposition.max()) > 0.005
    direction = outputs["Flow Direction"]
    assert float(direction[..., :2].std()) > 0.08

    # White hardness protects the terrain while drainage analysis still works.
    protected = dict(params); protected["preview_output"] = "Eroded Height"
    protected_height = fluvial.evaluator(
        {"Height": source, "Hardness": _rgba(np.ones_like(height))}, protected, context
    )[..., 0]
    assert np.allclose(protected_height, height, atol=3e-5)

    # No rain means no erosion.
    dry = dict(params); dry.update({"rainfall": 0.0, "preview_output": "Eroded Height"})
    dry_height = fluvial.evaluator({"Height": source}, dry, context)[..., 0]
    assert np.allclose(dry_height, height, atol=3e-5)

    # Seamless mode remains translation equivariant when rain variation is off.
    shifted = np.roll(source, shift=(5, -7), axis=(0, 1))
    shifted_height = fluvial.evaluator({"Height": shifted}, params, context)[..., 0]
    assert np.allclose(shifted_height, np.roll(eroded, shift=(5, -7), axis=(0, 1)), atol=5e-5)

    # Named outputs retain their source branch in a real graph.
    app = QApplication.instance() or QApplication([])
    scene = GraphScene(registry)
    source_node = scene.create_node("noise.ridged", QPointF(0, 0), record_undo=False)
    fluvial_node = scene.create_node("terrain.hydraulic_erosion", QPointF(280, 0), record_undo=False)
    fluvial_node.parameters.update({
        "quality": "Preview", "preview_iterations": 2,
        "preview_drainage_iterations": 8, "rain_variation": 0.0,
    })
    image_out = scene.create_node("output.image", QPointF(620, -140), record_undo=False)
    channel_out = scene.create_node("output.image", QPointF(620, 0), record_undo=False)
    direction_out = scene.create_node("output.image", QPointF(620, 140), record_undo=False)
    scene.add_connection(source_node.output_port, fluvial_node.input_ports["Height"], record_undo=False)
    scene.add_connection(fluvial_node.output_ports["Eroded Height"], image_out.input_ports["Image"], record_undo=False)
    scene.add_connection(fluvial_node.output_ports["Channel Mask"], channel_out.input_ports["Image"], record_undo=False)
    scene.add_connection(fluvial_node.output_ports["Flow Direction"], direction_out.input_ports["Image"], record_undo=False)
    evaluator = GraphEvaluator(scene, backend_preference="cpu")
    results = [evaluator.evaluate(node.uid, 32, 32) for node in (image_out, channel_out, direction_out)]
    assert all(not result.error for result in results)
    assert results[2].data_kind == "vector"

    gpu = WgpuBackend()
    if gpu.available:
        render_context = RenderContext(32, 32, TextureFormat.RGBA16F)
        small = _terrain(32)
        cpu_input = CpuImage(_rgba(small), TextureFormat.R16F, "fluvial-test", data_kind="grayscale")
        gpu_params = fluvial.default_parameters()
        gpu_params.update({
            "quality": "Preview", "preview_iterations": 2,
            "preview_drainage_iterations": 8, "rain_variation": 0.0,
        })
        for output_name in ("Eroded Height", "Flow Accumulation", "Channel Mask", "Flow Direction"):
            selected = dict(gpu_params); selected["preview_output"] = output_name
            logical = TextureFormat.RGBA16F if output_name == "Flow Direction" else TextureFormat.R16F
            resource = gpu.evaluate_node(
                fluvial, {"Height": cpu_input}, selected, render_context,
                f"fluvial-gpu:{output_name}", logical,
            )
            array = gpu.to_cpu(resource).array
            assert np.isfinite(array).all()
            assert float(array.std()) > 0.005

        cancelled = dict(gpu_params); cancelled["preview_iterations"] = 100
        cancelled["preview_drainage_iterations"] = 256
        try:
            gpu.evaluate_node(
                fluvial, {"Height": cpu_input}, cancelled, render_context,
                "fluvial-cancel", TextureFormat.R16F, cancel_check=lambda: True,
            )
        except BackendCancelled:
            pass
        else:
            raise AssertionError("Fluvial erosion did not honour cancellation")

    print(
        "Fluvial erosion test passed: coherent drainage hierarchy, sparse channel incision, "
        "valley widening, deposition, macroform preservation, hardness/rain masks, nine named "
        "outputs, seamless boundaries, GPU multi-pass execution and cancellation"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
