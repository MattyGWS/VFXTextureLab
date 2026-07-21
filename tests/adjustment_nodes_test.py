from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QSizePolicy

from vfx_texture_lab.engine.backends.cpu import CpuBackend
from vfx_texture_lab.engine.backends.wgpu_backend import WgpuBackend
from vfx_texture_lab.engine.formats import RenderContext, TextureFormat
from vfx_texture_lab.engine.resources import CpuImage
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext
from vfx_texture_lab.ui.parameters import AdjustmentHistogramWidget, HistogramAdjustmentControl


NEW_IDS = (
    "filter.histogram_range",
    "filter.histogram_shift",
    "filter.histogram_scan",
    "filter.brightness",
    "filter.contrast",
    "filter.exposure",
    "filter.gamma",
    "filter.posterize",
    "filter.clamp",
    "filter.hue_shift",
    "filter.saturation",
    "filter.lightness",
    "filter.curve",
)


def grayscale(values: list[float]) -> np.ndarray:
    data = np.asarray(values, dtype=np.float32)
    return np.stack((data, data, data, np.ones_like(data)), axis=1)[None, ...]


def run(definition, image: np.ndarray, params: dict | None = None, input_name: str = "Image") -> np.ndarray:
    context = EvalContext(image.shape[1], image.shape[0])
    values = definition.default_parameters()
    if params:
        values.update(params)
    assert definition.evaluator is not None
    return definition.evaluator({input_name: image}, values, context)


def main() -> None:
    app = QApplication.instance() or QApplication([])
    registry = build_registry()
    for type_id in NEW_IDS:
        assert registry.contains(type_id), type_id

    ramp = grayscale([0.0, 0.25, 0.5, 0.75, 1.0])

    range_node = registry.get("filter.histogram_range")
    ranged = run(range_node, ramp, {"range": 0.5, "position": 0.5})
    assert np.allclose(ranged[0, :, 0], [0.25, 0.375, 0.5, 0.625, 0.75], atol=1e-6)

    shift_node = registry.get("filter.histogram_shift")
    shifted = run(shift_node, ramp, {"position": 0.25})
    assert np.allclose(shifted[0, :, 0], [0.25, 0.5, 0.75, 0.0, 0.25], atol=1e-6)

    scan_node = registry.get("filter.histogram_scan")
    hard_scan = run(scan_node, ramp, {"position": 0.5, "contrast": 1.0})
    assert np.allclose(hard_scan[0, :, 0], [0.0, 0.0, 0.0, 1.0, 1.0], atol=1e-5)
    zero_scan = run(scan_node, ramp, {"position": 0.0, "contrast": 0.5})
    assert np.max(zero_scan[..., 0]) == 0.0

    brightness = run(registry.get("filter.brightness"), ramp, {"brightness": 0.2})
    assert np.allclose(brightness[0, :, 0], [0.2, 0.45, 0.7, 0.95, 1.2], atol=1e-6)

    contrast = run(registry.get("filter.contrast"), grayscale([0.25, 0.5, 0.75]), {"contrast": 1.0 / 3.0, "pivot": 0.5})
    assert np.allclose(contrast[0, :, 0], [0.0, 0.5, 1.0], atol=1e-6)

    exposure = run(registry.get("filter.exposure"), grayscale([0.125, 0.25, 0.5]), {"exposure": 1.0})
    assert np.allclose(exposure[0, :, 0], [0.25, 0.5, 1.0], atol=1e-6)

    gamma = run(registry.get("filter.gamma"), grayscale([0.0, 0.25, 1.0]), {"gamma": 2.0})
    assert np.allclose(gamma[0, :, 0], [0.0, 0.5, 1.0], atol=1e-6)

    posterized = run(registry.get("filter.posterize"), grayscale([0.1, 0.4, 0.6, 0.9]), {"steps": 2})
    assert np.allclose(posterized[0, :, 0], [0.0, 0.0, 1.0, 1.0], atol=1e-6)

    clamped = run(registry.get("filter.clamp"), ramp, {"minimum": 0.25, "maximum": 0.75})
    assert np.allclose(clamped[0, :, 0], [0.25, 0.25, 0.5, 0.75, 0.75], atol=1e-6)

    colours = np.asarray([[[1.0, 0.0, 0.0, 1.0], [0.3, 0.6, 0.9, 1.0]]], dtype=np.float32)
    hue = run(registry.get("filter.hue_shift"), colours, {"degrees": 120.0}, "Colour")
    assert np.allclose(hue[0, 0, :3], [0.0, 1.0, 0.0], atol=2e-5)

    desaturated = run(registry.get("filter.saturation"), colours, {"saturation": 0.0}, "Colour")
    assert np.allclose(desaturated[..., 0], desaturated[..., 1], atol=1e-6)
    assert np.allclose(desaturated[..., 1], desaturated[..., 2], atol=1e-6)

    unchanged_lightness = run(registry.get("filter.lightness"), colours, {"lightness": 0.0}, "Colour")
    assert np.allclose(unchanged_lightness, colours, atol=2e-5)

    curve_node = registry.get("filter.curve")
    neutral_curve = run(curve_node, ramp)
    assert np.allclose(neutral_curve, ramp, atol=1e-6)
    inverted_curve = run(
        curve_node,
        ramp,
        {
            "points": [{"x": 0.0, "y": 1.0}, {"x": 1.0, "y": 0.0}],
            "interpolation": "Smooth",
        },
    )
    assert np.allclose(inverted_curve[0, :, 0], [1.0, 0.75, 0.5, 0.25, 0.0], atol=1e-6)

    for type_id in ("filter.histogram_range", "filter.histogram_shift", "filter.histogram_scan"):
        definition = registry.get(type_id)
        assert definition.output_kind("Image") == "grayscale"
    for type_id in ("filter.hue_shift", "filter.saturation", "filter.lightness"):
        definition = registry.get(type_id)
        assert definition.input_kind("Colour") == "color"
        assert definition.output_kind("Image") == "color"

    histogram_widget = AdjustmentHistogramWidget("range", {"range": 0.5, "position": 0.5})
    histogram_widget.resize(640, 900)
    histogram_widget.set_histogram(np.arange(256, dtype=np.float64))
    assert histogram_widget.height() == 230
    assert histogram_widget.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed
    range_control = HistogramAdjustmentControl(
        "range",
        range_node.parameters,
        range_node.default_parameters(),
        set(),
    )
    range_control.set_histogram(np.ones(256, dtype=np.float64))
    assert range_control.histogram.height() == 230
    assert set(range_control.number_controls) == {"range", "position"}

    cpu = CpuBackend()
    gpu = WgpuBackend()
    if gpu.available:
        grey_values = np.linspace(0.1, 0.8, 17, dtype=np.float32)
        grey_rgba = np.stack((grey_values, grey_values, grey_values, np.ones_like(grey_values)), axis=1)[None, ...]
        grey_resource = CpuImage(grey_rgba, TextureFormat.R16F, "adjustments:grey", data_kind="grayscale", precision="16-bit")
        colour_values = np.asarray(
            [[[0.12, 0.34, 0.72, 1.0], [0.86, 0.22, 0.18, 1.0], [0.25, 0.75, 0.40, 1.0]]],
            dtype=np.float32,
        )
        colour_resource = CpuImage(colour_values, TextureFormat.RGBA16F, "adjustments:colour", data_kind="color", precision="16-bit")
        cases = {
            "filter.histogram_range": ({"range": 0.62, "position": 0.35}, grey_resource, "Image"),
            "filter.histogram_shift": ({"position": 0.22}, grey_resource, "Image"),
            "filter.histogram_scan": ({"position": 0.65, "contrast": 0.45}, grey_resource, "Image"),
            "filter.brightness": ({"brightness": 0.1}, grey_resource, "Image"),
            "filter.contrast": ({"contrast": 0.15, "pivot": 0.45}, grey_resource, "Image"),
            "filter.exposure": ({"exposure": -0.5}, grey_resource, "Image"),
            "filter.gamma": ({"gamma": 1.7}, grey_resource, "Image"),
            "filter.posterize": ({"steps": 6}, grey_resource, "Image"),
            "filter.clamp": ({"minimum": 0.2, "maximum": 0.7}, grey_resource, "Image"),
            "filter.hue_shift": ({"degrees": 73.0}, colour_resource, "Colour"),
            "filter.saturation": ({"saturation": 0.65}, colour_resource, "Colour"),
            "filter.lightness": ({"lightness": 0.08}, colour_resource, "Colour"),
            "filter.curve": ({
                "points": [{"x": 0.0, "y": 0.0}, {"x": 0.4, "y": 0.25}, {"x": 1.0, "y": 1.0}],
                "interpolation": "Smooth",
            }, grey_resource, "Image"),
        }
        for index, (type_id, (local, source, input_name)) in enumerate(cases.items()):
            definition = registry.get(type_id)
            context = RenderContext(source.array.shape[1], source.array.shape[0], source.logical_format)
            parameters = definition.default_parameters()
            parameters.update(local)
            cpu_result = cpu.evaluate_node(definition, {input_name: source}, parameters, context, f"adjustments:cpu:{index}")
            gpu_source = gpu.ensure_gpu(source, context)
            gpu_result = gpu.to_cpu(
                gpu.evaluate_node(definition, {input_name: gpu_source}, parameters, context, f"adjustments:gpu:{index}")
            )
            channels = 1 if source.data_kind == "grayscale" or definition.output_kind("Image") == "grayscale" else 3
            assert np.allclose(cpu_result.array[..., :channels], gpu_result.array[..., :channels], atol=1.5e-3), type_id
    else:
        print("GPU adjustment comparison skipped:", gpu.info().detail)

    backend_source = Path("vfx_texture_lab/engine/backends/wgpu_backend.py").read_text(encoding="utf-8")
    for type_id in NEW_IDS:
        assert type_id in backend_source
    for shader in (
        "histogram_range.wgsl",
        "histogram_shift.wgsl",
        "histogram_scan.wgsl",
        "adjust_scalar.wgsl",
        "hsl_adjust.wgsl",
        "image_curve.wgsl",
    ):
        assert Path("vfx_texture_lab/shaders", shader).is_file()

    print("Adjustment node test passed: 13 dedicated nodes, neutral defaults, expected CPU behaviour and GPU registrations")


if __name__ == "__main__":
    main()
