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
from vfx_texture_lab.graph.scene import GraphScene
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.image_ops import linear_to_srgb, srgb_to_linear
from PySide6.QtWidgets import QApplication


MODES = (
    "Replace / Copy",
    "Add",
    "Subtract",
    "Multiply",
    "Divide",
    "Add Sub / Linear Light",
    "Minimum",
    "Maximum",
    "Screen",
    "Overlay",
    "Soft Light",
    "Hard Light",
    "Difference",
    "Exclusion",
    "Colour Dodge",
    "Colour Burn",
)


def expected_mode(background: np.ndarray, foreground: np.ndarray, mode: str) -> np.ndarray:
    b = background
    f = foreground
    eps = 1e-6
    if mode == "Replace / Copy":
        return f
    if mode == "Add":
        return np.clip(b + f, 0.0, 1.0)
    if mode == "Subtract":
        return np.clip(b - f, 0.0, 1.0)
    if mode == "Multiply":
        return b * f
    if mode == "Divide":
        return np.clip(b / np.maximum(f, eps), 0.0, 1.0)
    if mode == "Add Sub / Linear Light":
        return np.clip(b + 2.0 * f - 1.0, 0.0, 1.0)
    if mode == "Minimum":
        return np.minimum(b, f)
    if mode == "Maximum":
        return np.maximum(b, f)
    if mode == "Screen":
        return 1.0 - (1.0 - b) * (1.0 - f)
    if mode == "Overlay":
        return np.where(b <= 0.5, 2.0 * b * f, 1.0 - 2.0 * (1.0 - b) * (1.0 - f))
    if mode == "Soft Light":
        d = np.where(b <= 0.25, ((16.0 * b - 12.0) * b + 4.0) * b, np.sqrt(np.maximum(b, 0.0)))
        return np.where(f <= 0.5, b - (1.0 - 2.0 * f) * b * (1.0 - b), b + (2.0 * f - 1.0) * (d - b))
    if mode == "Hard Light":
        return np.where(f <= 0.5, 2.0 * b * f, 1.0 - 2.0 * (1.0 - b) * (1.0 - f))
    if mode == "Difference":
        return np.abs(b - f)
    if mode == "Exclusion":
        return b + f - 2.0 * b * f
    if mode == "Colour Dodge":
        return np.where(f >= 1.0 - eps, 1.0, np.minimum(1.0, b / np.maximum(1.0 - f, eps)))
    if mode == "Colour Burn":
        return np.where(f <= eps, 0.0, 1.0 - np.minimum(1.0, (1.0 - b) / np.maximum(f, eps)))
    raise AssertionError(mode)


def image(
    rgb: tuple[float, float, float],
    alpha: float,
    width: int = 7,
    height: int = 5,
    *,
    data_kind: str = "color",
) -> CpuImage:
    arr = np.empty((height, width, 4), dtype=np.float32)
    arr[..., :3] = np.asarray(rgb, dtype=np.float32)
    arr[..., 3] = np.float32(alpha)
    logical = TextureFormat.R16F if data_kind == "grayscale" else TextureFormat.RGBA16F
    return CpuImage(arr, logical, data_kind=data_kind, precision="16-bit")


def expected_colour_mode(background_linear: np.ndarray, foreground_linear: np.ndarray, mode: str) -> np.ndarray:
    background_display = linear_to_srgb(background_linear)
    foreground_display = linear_to_srgb(foreground_linear)
    return srgb_to_linear(expected_mode(background_display, foreground_display, mode))


def main() -> None:
    app = QApplication.instance() or QApplication([])
    registry = build_registry()
    definition = registry.get("math.blend")
    assert definition.inputs == ("Foreground", "Background", "Opacity")
    assert definition.parameters[0].options == MODES
    assert definition.parameters[0].default == "Replace / Copy"

    context = RenderContext(7, 5, TextureFormat.RGBA16F)
    background = image((0.20, 0.75, 0.40), 0.25)
    foreground = image((0.80, 0.25, 1.00), 0.85)
    opacity = image((0.50, 0.50, 0.50), 1.0)
    cpu = CpuBackend()

    for mode in MODES:
        result = cpu.evaluate_node(
            definition,
            {"Foreground": foreground, "Background": background},
            {**definition.default_parameters(), "mode": mode, "opacity": 1.0},
            context,
            f"cpu:{mode}",
        )
        expected = expected_colour_mode(background.array[0, 0, :3], foreground.array[0, 0, :3], mode)
        assert np.allclose(result.array[0, 0, :3], expected, atol=2e-6), mode
        assert abs(float(result.array[0, 0, 3]) - 0.85) < 2e-6, mode
        assert np.isfinite(result.array).all(), mode


    # Greyscale/data-map blending remains raw numeric mathematics; it must not
    # receive an sRGB transfer merely because the same node also accepts colour.
    grey_background = image((0.20, 0.20, 0.20), 1.0, data_kind="grayscale")
    grey_foreground = image((0.80, 0.80, 0.80), 1.0, data_kind="grayscale")
    for mode in MODES:
        result = cpu.evaluate_node(
            definition,
            {"Foreground": grey_foreground, "Background": grey_background},
            {**definition.default_parameters(), "mode": mode, "opacity": 1.0},
            context,
            f"cpu:grey:{mode}",
        )
        expected = expected_mode(grey_background.array[0, 0, :3], grey_foreground.array[0, 0, :3], mode)
        assert np.allclose(result.array[0, 0, :3], expected, atol=2e-6), f"greyscale {mode}"

    # A visible 50% grey colour is stored as ~0.214 in the linear-light graph.
    # It is nevertheless the exact neutral point for the four contrast modes.
    neutral_display = np.full(3, 0.5, dtype=np.float32)
    neutral_linear = tuple(float(value) for value in srgb_to_linear(neutral_display))
    neutral_colour = image(neutral_linear, 1.0)
    varied_display = np.asarray((0.14, 0.46, 0.81), dtype=np.float32)
    varied_linear = tuple(float(value) for value in srgb_to_linear(varied_display))
    varied_colour = image(varied_linear, 1.0)
    for mode in ("Overlay", "Soft Light", "Hard Light", "Add Sub / Linear Light"):
        result = cpu.evaluate_node(
            definition,
            {"Foreground": neutral_colour, "Background": varied_colour},
            {**definition.default_parameters(), "mode": mode, "opacity": 1.0},
            context,
            f"cpu:neutral:{mode}",
        )
        assert np.allclose(result.array[0, 0, :3], varied_colour.array[0, 0, :3], atol=3e-6), mode

    # The same exact numeric midpoint remains neutral for greyscale maps.
    neutral_grey = image((0.5, 0.5, 0.5), 1.0, data_kind="grayscale")
    varied_grey = image((0.17, 0.17, 0.17), 1.0, data_kind="grayscale")
    for mode in ("Overlay", "Soft Light", "Hard Light", "Add Sub / Linear Light"):
        result = cpu.evaluate_node(
            definition,
            {"Foreground": neutral_grey, "Background": varied_grey},
            {**definition.default_parameters(), "mode": mode, "opacity": 1.0},
            context,
            f"cpu:neutral-grey:{mode}",
        )
        assert np.allclose(result.array[0, 0, :3], varied_grey.array[0, 0, :3], atol=2e-6), mode

    # Node opacity and greyscale mask multiply together: 0.5 × 0.5 = 0.25.
    masked = cpu.evaluate_node(
        definition,
        {"Foreground": foreground, "Background": background, "Opacity": opacity},
        {**definition.default_parameters(), "mode": "Replace / Copy", "opacity": 0.5},
        context,
        "cpu:masked",
    )
    expected_masked = background.array[0, 0] * 0.75 + foreground.array[0, 0] * 0.25
    assert np.allclose(masked.array[0, 0], expected_masked, atol=2e-6)

    # Divide-by-zero and burn/dodge boundaries must remain finite.
    zeros = image((0.0, 0.0, 0.0), 1.0)
    ones = image((1.0, 1.0, 1.0), 1.0)
    for mode, fg in (("Divide", zeros), ("Colour Dodge", ones), ("Colour Burn", zeros)):
        result = cpu.evaluate_node(
            definition,
            {"Foreground": fg, "Background": background},
            {**definition.default_parameters(), "mode": mode},
            context,
            f"cpu:edge:{mode}",
        )
        assert np.isfinite(result.array).all(), mode


    # Older A/B connections are migrated without changing their layer meaning:
    # old A was Background and old B was Foreground.
    legacy = {
        "nodes": [
            {"uid": "bg", "type": "generator.color", "x": 0, "y": 0, "parameters": {"color": "#334455ff"}},
            {"uid": "fg", "type": "generator.color", "x": 0, "y": 100, "parameters": {"color": "#ccddeeaa"}},
            {"uid": "blend", "type": "math.blend", "x": 250, "y": 0, "parameters": {"mode": "Replace", "opacity": 1.0}},
        ],
        "groups": [],
        "connections": [
            {"source": "bg", "source_output": "Image", "target": "blend", "input": "A"},
            {"source": "fg", "source_output": "Image", "target": "blend", "input": "B"},
        ],
        "active_node": "blend",
    }
    scene = GraphScene(registry)
    scene.from_dict(legacy)
    assert scene.connection_for_input("blend", "Background").source_node.uid == "bg"
    assert scene.connection_for_input("blend", "Foreground").source_node.uid == "fg"

    gpu = WgpuBackend()
    if gpu.available:
        gpu_inputs = {
            "Foreground": gpu.ensure_gpu(foreground, context),
            "Background": gpu.ensure_gpu(background, context),
            "Opacity": gpu.ensure_gpu(opacity, context),
        }
        for mode in MODES:
            params = {**definition.default_parameters(), "mode": mode, "opacity": 0.73}
            cpu_result = cpu.evaluate_node(definition, {"Foreground": foreground, "Background": background, "Opacity": opacity}, params, context, f"cpu-gpu:{mode}")
            gpu_result = gpu.to_cpu(gpu.evaluate_node(definition, gpu_inputs, params, context, f"gpu:{mode}"))
            assert np.allclose(cpu_result.array, gpu_result.array, atol=8e-4), mode
    else:
        print("GPU blend comparisons skipped:", gpu.info().detail)

    print("Blend modes test passed: perceptual colour blending, raw greyscale math, neutral 50% grey contrast modes, Foreground/Background semantics, 16 standard modes, opacity masks, finite boundaries and CPU/GPU agreement")


if __name__ == "__main__":
    main()
