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
from vfx_texture_lab.nodes.image_ops import srgb_to_linear
from vfx_texture_lab.nodes.base import EvalContext


NODE_IDS = (
    "filter.histogram_select",
    "filter.highpass",
    "filter.edge_detect",
    "filter.fxaa",
    "transform.crop",
    "transform.auto_crop",
)


def rgba(values: np.ndarray, alpha: np.ndarray | float = 1.0) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    if values.ndim == 2:
        rgb = np.repeat(values[..., None], 3, axis=2)
    else:
        rgb = values[..., :3]
    if np.isscalar(alpha):
        a = np.full((*rgb.shape[:2], 1), float(alpha), dtype=np.float32)
    else:
        a = np.asarray(alpha, dtype=np.float32)[..., None]
    return np.concatenate((rgb, a), axis=2).astype(np.float32)


def cpu_eval(registry, type_id: str, image: np.ndarray, params: dict, *, kind: str = "grayscale") -> np.ndarray:
    definition = registry.get(type_id)
    values = definition.default_parameters()
    values.update(params)
    values["_resolved_kind"] = kind
    return definition.evaluator({"Image": image}, values, EvalContext(image.shape[1], image.shape[0]))


def assert_registry(registry) -> None:
    for type_id in NODE_IDS:
        definition = registry.get(type_id)
        assert definition.gpu_kernel
        assert definition.evaluator is not None
    assert registry.search("histogram select")[0].type_id == "filter.histogram_select"
    assert any(item.type_id == "filter.highpass" for item in registry.search("photo detail"))
    assert any(item.type_id == "filter.fxaa" for item in registry.search("anti alias"))
    assert any(item.type_id == "transform.auto_crop" for item in registry.search("auto crop"))


def assert_histogram_select(registry) -> None:
    gradient = np.tile(np.linspace(0.0, 1.0, 257, dtype=np.float32)[None, :], (8, 1))
    image = rgba(gradient)
    result = cpu_eval(registry, "filter.histogram_select", image, {"position": 0.4, "range": 0.2, "contrast": 0.8})[..., 0]
    centre = int(round(0.4 * 256))
    assert result[:, centre].mean() > 0.99
    assert result[:, 0].mean() < 0.01
    assert result[:, -1].mean() < 0.01
    narrow = cpu_eval(registry, "filter.histogram_select", image, {"position": 0.5, "range": 0.1, "contrast": 0.9})[..., 0]
    broad = cpu_eval(registry, "filter.histogram_select", image, {"position": 0.5, "range": 0.6, "contrast": 0.9})[..., 0]
    assert np.count_nonzero(broad > 0.5) > np.count_nonzero(narrow > 0.5) * 4


def assert_highpass(registry) -> None:
    flat = rgba(np.full((64, 64), 0.37, dtype=np.float32))
    neutral = cpu_eval(registry, "filter.highpass", flat, {"radius": 12.0})
    assert np.allclose(neutral[..., :3], 0.5, atol=1.0 / 255.0 + 1.0e-6)
    display_colour = np.array([0.18, 0.52, 0.83], dtype=np.float32)
    linear_colour = srgb_to_linear(display_colour)
    colour_flat = np.empty((64, 64, 4), dtype=np.float32)
    colour_flat[..., :3] = linear_colour
    colour_flat[..., 3] = 1.0
    colour_neutral = cpu_eval(registry, "filter.highpass", colour_flat, {"radius": 12.0}, kind="color")
    expected_midpoint = float(srgb_to_linear(np.array([0.5], dtype=np.float32))[0])
    assert np.allclose(colour_neutral[..., :3], expected_midpoint, atol=1.0 / 255.0 + 1.0e-5)
    y, x = np.mgrid[0:64, 0:64]
    broad = (x / 63.0 * 0.6 + 0.2).astype(np.float32)
    detail = (((x + y) % 2) * 0.08 - 0.04).astype(np.float32)
    image = rgba(np.clip(broad + detail, 0.0, 1.0))
    result = cpu_eval(registry, "filter.highpass", image, {"radius": 10.0})[..., 0]
    assert abs(float(result.mean()) - 0.5) < 0.04
    # Clamp is the safe default for photographs; wrapping remains available
    # for already tileable sources and must create a measurably different edge.
    step = np.zeros((64, 64), dtype=np.float32)
    step[:, :8] = 1.0
    clamped = cpu_eval(registry, "filter.highpass", rgba(step), {"radius": 8.0, "boundary": "Clamp"})[..., 0]
    wrapped = cpu_eval(registry, "filter.highpass", rgba(step), {"radius": 8.0, "boundary": "Seamless / Wrap"})[..., 0]
    assert float(np.abs(clamped[:, -1] - 0.5).mean()) < 0.01
    assert float(np.abs(wrapped[:, -1] - 0.5).mean()) > 0.02


def assert_edge_detect(registry) -> None:
    flat = rgba(np.full((64, 64), 0.5, dtype=np.float32))
    assert float(cpu_eval(registry, "filter.edge_detect", flat, {})[..., 0].max()) < 1.0e-6
    mask = np.zeros((64, 64), dtype=np.float32)
    mask[16:48, 18:46] = 1.0
    edges = cpu_eval(registry, "filter.edge_detect", rgba(mask), {"method": "Scharr", "width": 1.0, "intensity": 2.0})[..., 0]
    assert edges[16, 32] > 0.5
    assert edges[32, 18] > 0.5
    assert edges[32, 32] < 0.01
    assert edges[4, 4] < 0.01

    normal = np.zeros((64, 64, 4), dtype=np.float32)
    normal[..., :3] = np.array([0.5, 0.5, 1.0], dtype=np.float32)
    normal[..., 3] = 1.0
    normal[:, 32:, :3] = np.array([0.85, 0.5, 0.85], dtype=np.float32)
    vector_edges = cpu_eval(
        registry, "filter.edge_detect", normal,
        {"method": "Scharr", "width": 1.0, "intensity": 2.0}, kind="vector",
    )[..., 0]
    assert vector_edges[:, 31:33].mean() > 0.25
    assert vector_edges[:, :20].max() < 0.01


def assert_fxaa(registry) -> None:
    y, x = np.mgrid[0:96, 0:96]
    diagonal = (x > y + ((y // 8) % 2)).astype(np.float32)
    image = rgba(diagonal)
    result = cpu_eval(
        registry, "filter.fxaa", image,
        {"quality": "High", "edge_threshold": 0.01, "relative_threshold": 0.02, "subpixel": 1.0},
    )[..., 0]
    assert np.count_nonzero((result > 0.01) & (result < 0.99)) > 50
    assert result[5, 90] > 0.99
    assert result[90, 5] < 0.01

    normal = np.zeros((48, 48, 4), dtype=np.float32)
    normal[..., :3] = np.array([0.5, 0.5, 1.0], dtype=np.float32)
    normal[..., 3] = 1.0
    normal[:, 24:, :3] = np.array([0.8, 0.5, 0.9], dtype=np.float32)
    filtered = cpu_eval(
        registry, "filter.fxaa", normal,
        {"quality": "High", "edge_threshold": 0.0, "relative_threshold": 0.0, "subpixel": 1.0}, kind="vector",
    )
    decoded = filtered[..., :3] * 2.0 - 1.0
    lengths = np.linalg.norm(decoded, axis=2)
    assert np.allclose(lengths, 1.0, atol=2.0e-4)


def assert_crop(registry) -> None:
    height, width = 80, 100
    y, x = np.mgrid[0:height, 0:width]
    source = np.stack((x / (width - 1), y / (height - 1), np.zeros_like(x, dtype=np.float32)), axis=2).astype(np.float32)
    image = rgba(source)
    result = cpu_eval(
        registry, "transform.crop", image,
        {"left": 0.25, "right": 0.75, "top": 0.2, "bottom": 0.8, "filtering": "Bilinear"}, kind="color",
    )
    centre = result[height // 2, width // 2, :2]
    assert np.allclose(centre, (0.5, 0.5), atol=0.02)
    assert abs(float(result[0, 0, 0]) - 0.25) < 0.02
    assert abs(float(result[-1, -1, 1]) - 0.8) < 0.02


def content_bounds(values: np.ndarray, threshold: float = 0.5) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(values > threshold)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def assert_auto_crop(registry) -> None:
    mask = np.zeros((80, 100), dtype=np.float32)
    mask[8:28, 10:50] = 1.0
    image = rgba(mask)
    centred = cpu_eval(
        registry, "transform.auto_crop", image,
        {"mode": "Crop Auto", "threshold": 0.1, "padding": 0.0, "filtering": "Nearest"},
    )[..., 0]
    c_left, c_top, c_right, c_bottom = content_bounds(centred)
    assert abs((c_left + c_right) * 0.5 - 49.5) <= 1.0
    assert abs((c_top + c_bottom) * 0.5 - 39.5) <= 1.0
    assert 39 <= (c_right - c_left + 1) <= 41
    assert 19 <= (c_bottom - c_top + 1) <= 21

    fitted = cpu_eval(
        registry, "transform.auto_crop", image,
        {"mode": "Fit (Keep Ratio)", "threshold": 0.1, "padding": 0.0, "filtering": "Nearest"},
    )[..., 0]
    left, top, right, bottom = content_bounds(fitted)
    assert abs((left + right) * 0.5 - 49.5) <= 1.0
    assert abs((top + bottom) * 0.5 - 39.5) <= 1.0
    assert (right - left + 1) == 100
    assert 48 <= (bottom - top + 1) <= 52

    stretched = cpu_eval(
        registry, "transform.auto_crop", image,
        {"mode": "Fill (Stretch)", "threshold": 0.1, "padding": 0.0, "filtering": "Nearest"},
    )[..., 0]
    assert float(stretched.mean()) > 0.98

    transparent = np.zeros((64, 64, 4), dtype=np.float32)
    transparent[20:40, 8:24, 3] = 1.0
    alpha_crop = cpu_eval(
        registry, "transform.auto_crop", transparent,
        {"mode": "Fill (Stretch)", "use_alpha": True, "threshold": 0.1, "filtering": "Nearest"}, kind="color",
    )
    assert float(alpha_crop[..., 3].mean()) > 0.98


def assert_gpu_custom_cases(registry) -> None:
    gpu = WgpuBackend()
    if not gpu.available:
        print("Immediate essentials GPU checks skipped:", gpu.info().detail)
        return
    cpu = CpuBackend(gpu)
    context = RenderContext(72, 56, TextureFormat.RGBA16F)
    y, x = np.mgrid[0:context.height, 0:context.width]
    values = np.zeros((context.height, context.width), dtype=np.float32)
    values[7:31, 11:43] = 0.25 + 0.75 * ((x[7:31, 11:43] + y[7:31, 11:43]) % 2)
    image = rgba(values)
    resource = CpuImage(image, TextureFormat.RGBA16F, "essentials-source", frozenset({"cpu"}), "color", "16-bit")
    cases = {
        "filter.histogram_select": {"position": 0.7, "range": 0.35, "contrast": 0.65},
        "filter.highpass": {"radius": 5.0},
        "filter.edge_detect": {"method": "Sobel", "width": 3.0, "intensity": 1.7},
        "filter.fxaa": {"quality": "High", "edge_threshold": 0.01, "relative_threshold": 0.05, "subpixel": 0.9},
        "transform.crop": {"left": 0.12, "right": 0.78, "top": 0.08, "bottom": 0.72, "filtering": "Bilinear"},
        "transform.auto_crop": {"mode": "Fit (Keep Ratio)", "threshold": 0.1, "padding": 0.03, "filtering": "Bilinear"},
    }
    for type_id, authored in cases.items():
        definition = registry.get(type_id)
        params = definition.default_parameters()
        params.update(authored)
        params["_resolved_kind"] = "color"
        cpu_result = cpu.evaluate_node(definition, {"Image": resource}, params, context, f"cpu:{type_id}")
        gpu_source = gpu.ensure_gpu(resource, context)
        gpu_result = gpu.to_cpu(gpu.evaluate_node(definition, {"Image": gpu_source}, params, context, f"gpu:{type_id}"))
        difference = np.abs(cpu_result.array - gpu_result.array)
        if type_id == "filter.highpass":
            assert float(difference.mean()) < 0.012, (type_id, difference.mean(), difference.max())
            assert float(difference.max()) < 0.15, (type_id, difference.mean(), difference.max())
        elif type_id == "filter.fxaa":
            # FXAA deliberately contains an edge/no-edge threshold. Half-float
            # upload quantisation can flip that decision at a very small number
            # of checkerboard boundary pixels, while the image-wide result and
            # more than 99.5% of samples remain tightly aligned.
            assert float(difference.mean()) < 0.001, (type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.995)) < 0.002, (type_id, difference.mean(), difference.max())
            assert float(difference.max()) < 0.25, (type_id, difference.mean(), difference.max())
        else:
            assert float(difference.mean()) < 0.002, (type_id, difference.mean(), difference.max())
            assert float(difference.max()) < 0.04, (type_id, difference.mean(), difference.max())

    # Exercise the no-resize Crop Auto GPU branch separately from the Fit mode
    # used in the table above.
    definition = registry.get("transform.auto_crop")
    params = definition.default_parameters()
    params.update({"mode": "Crop Auto", "threshold": 0.1, "padding": 0.0, "filtering": "Nearest"})
    params["_resolved_kind"] = "color"
    cpu_result = cpu.evaluate_node(definition, {"Image": resource}, params, context, "cpu:auto-centre")
    gpu_source = gpu.ensure_gpu(resource, context)
    gpu_result = gpu.to_cpu(gpu.evaluate_node(definition, {"Image": gpu_source}, params, context, "gpu:auto-centre"))
    difference = np.abs(cpu_result.array - gpu_result.array)
    assert float(difference.mean()) < 0.002, (difference.mean(), difference.max())
    assert float(difference.max()) < 0.04, (difference.mean(), difference.max())


def main() -> int:
    registry = build_registry()
    assert_registry(registry)
    assert_histogram_select(registry)
    assert_highpass(registry)
    assert_edge_detect(registry)
    assert_fxaa(registry)
    assert_crop(registry)
    assert_auto_crop(registry)
    assert_gpu_custom_cases(registry)
    print("Immediate essentials test passed: Histogram Select, Highpass, Edge Detect, FXAA, Crop and Auto Crop")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
