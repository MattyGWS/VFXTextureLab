from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QSizePolicy

from vfx_texture_lab.engine.backends.cpu import CpuBackend
from vfx_texture_lab.engine.backends.wgpu_backend import WgpuBackend
from vfx_texture_lab.engine.formats import RenderContext, TextureFormat
from vfx_texture_lab.engine.resources import CpuImage
from vfx_texture_lab.graph.scene import GraphScene
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.ui.parameters import LevelsControl, LevelsHistogramWidget


def ramp_image(values: np.ndarray) -> CpuImage:
    values = np.asarray(values, dtype=np.float32).reshape(1, -1)
    rgba = np.empty((1, values.shape[1], 4), dtype=np.float32)
    rgba[..., 0] = values
    rgba[..., 1] = values
    rgba[..., 2] = values
    rgba[..., 3] = 1.0
    return CpuImage(rgba, TextureFormat.R16F, data_kind="grayscale", precision="16-bit")


def main() -> None:
    app = QApplication.instance() or QApplication([])
    registry = build_registry()
    definition = registry.get("filter.levels")
    names = tuple(spec.name for spec in definition.parameters)
    assert names == ("in_low", "in_high", "in_mid", "out_low", "out_high", "intermediary_clamp")

    cpu = CpuBackend()
    context = RenderContext(3, 1, TextureFormat.R16F)
    source = ramp_image(np.array([0.2, 0.5, 0.8], dtype=np.float32))
    params = {
        **definition.default_parameters(),
        "in_low": 0.2,
        "in_high": 0.8,
        "in_mid": 0.5,
        "out_low": 0.0,
        "out_high": 1.0,
        "intermediary_clamp": True,
    }
    result = cpu.evaluate_node(definition, {"Image": source}, params, context, "levels:neutral")
    assert np.allclose(result.array[0, :, 0], [0.0, 0.5, 1.0], atol=2e-5)

    # A 0.25 midpoint means the tone one quarter of the way through the input
    # range maps to middle grey.
    source_mid = ramp_image(np.array([0.35], dtype=np.float32))
    mid_context = RenderContext(1, 1, TextureFormat.R16F)
    quarter = cpu.evaluate_node(
        definition,
        {"Image": source_mid},
        {**params, "in_mid": 0.25},
        mid_context,
        "levels:quarter",
    )
    assert abs(float(quarter.array[0, 0, 0]) - 0.5) < 2e-5

    inverted = cpu.evaluate_node(
        definition,
        {"Image": source},
        {**params, "out_low": 1.0, "out_high": 0.0},
        context,
        "levels:invert",
    )
    assert np.allclose(inverted.array[0, :, 0], [1.0, 0.5, 0.0], atol=2e-5)

    # Passthrough preserves the out-of-range transformed value until the output
    # range is applied, whereas Clamp pins it to Level Out Low.
    outside = ramp_image(np.array([0.1], dtype=np.float32))
    outside_context = RenderContext(1, 1, TextureFormat.R32F)
    outside_params = {
        **definition.default_parameters(),
        "in_low": 0.2, "in_high": 0.8,
        "out_low": 0.25, "out_high": 0.75,
    }
    clamped = cpu.evaluate_node(
        definition, {"Image": outside}, {**outside_params, "intermediary_clamp": True},
        outside_context, "levels:clamped",
    )
    passthrough = cpu.evaluate_node(
        definition, {"Image": outside}, {**outside_params, "intermediary_clamp": False},
        outside_context, "levels:passthrough",
    )
    assert abs(float(clamped.array[0, 0, 0]) - 0.25) < 2e-5
    assert float(passthrough.array[0, 0, 0]) < float(clamped.array[0, 0, 0])

    # Legacy Black/White/Gamma settings migrate to the five-point model.
    scene = GraphScene(registry)
    legacy = scene.create_node(
        "filter.levels",
        QPointF(0, 0),
        parameters={"black": 0.1, "white": 0.9, "gamma": 2.0},
        record_undo=False,
    )
    assert "black" not in legacy.parameters and "gamma" not in legacy.parameters
    assert abs(float(legacy.parameters["in_low"]) - 0.1) < 1e-6
    assert abs(float(legacy.parameters["in_high"]) - 0.9) < 1e-6
    assert abs(float(legacy.parameters["in_mid"]) - 0.25) < 1e-6

    histogram = LevelsHistogramWidget(definition.default_parameters())
    histogram.resize(600, 700)
    histogram.set_histogram(np.arange(256, dtype=np.float64))
    assert histogram.height() == 230
    assert histogram.minimumHeight() == 230 and histogram.maximumHeight() == 230
    assert histogram._marker_x("in_mid") == histogram._x_for_value(0.5)

    editor = LevelsControl(
        definition.parameters,
        definition.default_parameters(),
        "grayscale",
        set(),
    )
    editor.set_histogram(np.ones(256), ready=True)
    assert editor.auto_button.isEnabled()
    assert editor.stack.count() == 2
    assert editor.stack.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Maximum

    gpu = WgpuBackend()
    if gpu.available:
        gpu_source = gpu.ensure_gpu(source, context)
        for index, local in enumerate((
            params,
            {**params, "in_mid": 0.25, "out_low": 0.12, "out_high": 0.87},
            {**params, "out_low": 1.0, "out_high": 0.0, "intermediary_clamp": False},
        )):
            cpu_result = cpu.evaluate_node(definition, {"Image": source}, local, context, "levels:cpu-gpu")
            gpu_result = gpu.to_cpu(gpu.evaluate_node(definition, {"Image": gpu_source}, local, context, f"levels:gpu:{index}"))
            assert np.allclose(cpu_result.array[..., 0], gpu_result.array[..., 0], atol=8e-4)
    else:
        print("GPU Levels comparison skipped:", gpu.info().detail)

    print(
        "Levels histogram test passed: five-point tone remapping, midpoint semantics, output inversion, "
        "intermediary clamp/passthrough, legacy migration, histogram UI and CPU/GPU agreement"
    )


if __name__ == "__main__":
    main()
