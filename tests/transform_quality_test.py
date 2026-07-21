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
from vfx_texture_lab.graph import GraphScene
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.processing import _safe_lattice
from vfx_texture_lab.nodes.resampling import BOUNDARY_OPTIONS, FILTERING_OPTIONS
from PySide6.QtWidgets import QApplication


def rgba(values: np.ndarray, alpha: np.ndarray | float = 1.0) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    if values.ndim == 2:
        rgb = np.repeat(values[..., None], 3, axis=2)
    else:
        rgb = values[..., :3]
    if np.isscalar(alpha):
        a = np.full(rgb.shape[:2], float(alpha), dtype=np.float32)
    else:
        a = np.asarray(alpha, dtype=np.float32)
    return np.concatenate((rgb, a[..., None]), axis=2).astype(np.float32)


def resource(array: np.ndarray, kind: str, key: str = "transform-quality") -> CpuImage:
    return CpuImage(
        np.ascontiguousarray(array, dtype=np.float32),
        TextureFormat.RGBA16F,
        key,
        data_kind=kind,
        precision="16-bit",
    )


def evaluate(cpu: CpuBackend, definition, source: CpuImage, context: RenderContext, overrides: dict, key: str):
    params = definition.default_parameters()
    params.update(overrides)
    return cpu.evaluate_node(definition, {"Image": source}, params, context, key)


def assert_registry(registry) -> None:
    safe = registry.get("transform.safe")
    assert safe.name == "Safe Transform"
    safe_params = {item.name: item for item in safe.parameters}
    assert safe_params["tiles"].maximum == 16
    assert safe_params["tile_safe_rotation"].default is True
    assert tuple(safe_params["filtering"].options) == FILTERING_OPTIONS

    for type_id in (
        "transform.basic", "transform.crop", "transform.auto_crop", "transform.safe",
        "transform.tile", "transform.offset", "transform.rotate", "transform.scale",
        "transform.clone_patch", "transform.perspective", "transform.atlas_splitter",
        "normal.transform",
    ):
        definition = registry.get(type_id)
        specs = {item.name: item for item in definition.parameters}
        assert "filtering" in specs, type_id
        assert tuple(specs["filtering"].options) == FILTERING_OPTIONS, type_id

    for type_id in ("transform.basic", "transform.offset", "transform.rotate", "transform.scale", "normal.transform"):
        specs = {item.name: item for item in registry.get(type_id).parameters}
        assert "boundary" in specs, type_id
        assert tuple(specs["boundary"].options) == BOUNDARY_OPTIONS, type_id


def assert_identity_and_pixel_alignment(registry, cpu: CpuBackend) -> None:
    h, w = 37, 53
    rng = np.random.default_rng(124)
    image = rng.random((h, w, 4), dtype=np.float32)
    image[..., 3] = 1.0
    source = resource(image, "color", "identity")
    context = RenderContext(w, h, TextureFormat.RGBA16F)
    cases = (
        ("transform.basic", {}),
        ("transform.safe", {}),
        ("transform.crop", {}),
        ("transform.perspective", {}),
        ("transform.tile", {"tiles_x": 1.0, "tiles_y": 1.0}),
        ("transform.offset", {"offset_x": 0.0, "offset_y": 0.0}),
        ("transform.rotate", {"angle": 360.0}),
        ("transform.scale", {"scale_x": 1.0, "scale_y": 1.0}),
    )
    for index, (type_id, overrides) in enumerate(cases):
        result = evaluate(cpu, registry.get(type_id), source, context, overrides, f"identity:{index}")
        assert np.array_equal(result.array, image), type_id

    shifted = evaluate(
        cpu, registry.get("transform.offset"), source, context,
        {"offset_x": 3.0 / w, "offset_y": -2.0 / h, "boundary": "Seamless / Wrap", "filtering": "Automatic"},
        "integer-offset",
    )
    assert np.array_equal(shifted.array, np.roll(image, shift=(-2, 3), axis=(0, 1)))



def assert_rectangular_pixel_space(registry, cpu: CpuBackend) -> None:
    """Rotation must preserve physical distances on non-square canvases."""
    h, w = 61, 121
    center_x = w // 2
    center_y = h // 2
    distance = 20
    image = np.zeros((h, w), dtype=np.float32)
    image[center_y - 1:center_y + 2, center_x + distance - 1:center_x + distance + 2] = 1.0
    source = resource(rgba(image), "grayscale", "rectangular-rotation")
    context = RenderContext(w, h, TextureFormat.RGBA16F)
    for index, type_id in enumerate(("transform.basic", "transform.rotate")):
        result = evaluate(
            cpu, registry.get(type_id), source, context,
            {"angle": 90.0, "boundary": "Transparent", "filtering": "Nearest"},
            f"rectangular-rotation:{index}",
        ).array[..., 0]
        ys, xs = np.nonzero(result > 0.5)
        assert xs.size > 0, type_id
        centroid_x = float(xs.mean())
        centroid_y = float(ys.mean())
        assert abs(centroid_x - center_x) <= 1.0, (type_id, centroid_x, centroid_y)
        assert abs(abs(centroid_y - center_y) - distance) <= 1.0, (type_id, centroid_x, centroid_y)


def assert_shared_shader_include() -> None:
    shader_root = Path(__file__).resolve().parents[1] / "vfx_texture_lab" / "shaders"
    for name in (
        "transform_2d.wgsl", "transform_simple.wgsl", "crop.wgsl",
        "auto_crop.wgsl", "clone_patch.wgsl", "perspective_transform.wgsl",
        "normal_transform.wgsl", "safe_transform.wgsl",
    ):
        text = (shader_root / name).read_text(encoding="utf-8")
        assert '// @include "resampling_common.wgsl"' in text, name

def assert_premultiplied_alpha(registry, cpu: CpuBackend) -> None:
    h = w = 96
    image = np.zeros((h, w, 4), dtype=np.float32)
    # Deliberately poison fully transparent pixels with green. Straight-alpha
    # interpolation would create a green fringe around the red cutout.
    image[..., 1] = 1.0
    image[24:72, 26:70, :3] = (1.0, 0.0, 0.0)
    image[24:72, 26:70, 3] = 1.0
    source = resource(image, "color", "alpha")
    context = RenderContext(w, h, TextureFormat.RGBA16F)
    result = evaluate(
        cpu, registry.get("transform.basic"), source, context,
        {"angle": 17.0, "boundary": "Transparent", "filtering": "Bicubic"},
        "alpha-rotate",
    ).array
    partial = (result[..., 3] > 0.02) & (result[..., 3] < 0.98)
    assert np.count_nonzero(partial) > 20
    assert float(np.quantile(result[..., 0][partial], 0.05)) > 0.97
    assert float(np.quantile(result[..., 1][partial], 0.95)) < 0.03


def assert_filtering_and_minification(registry, cpu: CpuBackend) -> None:
    h = w = 128
    y, x = np.mgrid[0:h, 0:w]
    checker = ((x + y) & 1).astype(np.float32)
    source = resource(rgba(checker), "grayscale", "checker")
    context = RenderContext(w, h, TextureFormat.RGBA16F)
    nearest = evaluate(
        cpu, registry.get("transform.basic"), source, context,
        {"scale": 0.19, "boundary": "Seamless / Wrap", "filtering": "Nearest"},
        "checker-nearest",
    ).array[..., 0]
    automatic = evaluate(
        cpu, registry.get("transform.basic"), source, context,
        {"scale": 0.19, "boundary": "Seamless / Wrap", "filtering": "Automatic"},
        "checker-auto",
    ).array[..., 0]
    # Area-aware Automatic filtering must suppress high-frequency aliasing.
    assert float(np.std(automatic)) < float(np.std(nearest)) * 0.72
    assert abs(float(np.mean(automatic)) - 0.5) < 0.08

    step = np.zeros((h, w), dtype=np.float32)
    step[:, w // 2 :] = 1.0
    step_source = resource(rgba(step), "grayscale", "step")
    nearest_step = evaluate(
        cpu, registry.get("transform.rotate"), step_source, context,
        {"angle": 13.0, "boundary": "Clamp", "filtering": "Nearest"}, "step-nearest",
    ).array[..., 0]
    bicubic_step = evaluate(
        cpu, registry.get("transform.rotate"), step_source, context,
        {"angle": 13.0, "boundary": "Clamp", "filtering": "Bicubic"}, "step-bicubic",
    ).array[..., 0]
    assert set(np.unique(nearest_step)).issubset({0.0, 1.0})
    assert np.count_nonzero((bicubic_step > 0.02) & (bicubic_step < 0.98)) > 0


def assert_boundaries(registry, cpu: CpuBackend) -> None:
    h, w = 9, 11
    y, x = np.mgrid[0:h, 0:w]
    values = (x + y * w).astype(np.float32) / float(h * w - 1)
    source = resource(rgba(values), "grayscale", "boundaries")
    context = RenderContext(w, h, TextureFormat.RGBA16F)
    offset = {"offset_x": 2.0 / w, "offset_y": 0.0, "filtering": "Nearest"}
    transparent = evaluate(cpu, registry.get("transform.offset"), source, context, {**offset, "boundary": "Transparent"}, "boundary-transparent").array[..., 0]
    clamp = evaluate(cpu, registry.get("transform.offset"), source, context, {**offset, "boundary": "Clamp"}, "boundary-clamp").array[..., 0]
    wrap = evaluate(cpu, registry.get("transform.offset"), source, context, {**offset, "boundary": "Seamless / Wrap"}, "boundary-wrap").array[..., 0]
    mirror = evaluate(cpu, registry.get("transform.offset"), source, context, {**offset, "boundary": "Mirror"}, "boundary-mirror").array[..., 0]
    assert np.allclose(transparent[:, :2], 0.0)
    assert np.allclose(clamp[:, :2], values[:, :1])
    assert np.allclose(wrap[:, :2], values[:, -2:])
    assert np.allclose(mirror[:, 0], values[:, 1])
    assert np.allclose(mirror[:, 1], values[:, 0])


def assert_vectors(registry, cpu: CpuBackend) -> None:
    h = w = 96
    y, x = np.mgrid[0:h, 0:w]
    nx = 0.55 * np.sin((x + 0.5) / w * np.pi * 2.0)
    ny = 0.55 * np.cos((y + 0.5) / h * np.pi * 2.0)
    nz = np.sqrt(np.maximum(1.0 - nx * nx - ny * ny, 1.0e-5))
    image = np.stack((nx, ny, nz), axis=2) * 0.5 + 0.5
    image = np.concatenate((image.astype(np.float32), np.ones((h, w, 1), dtype=np.float32)), axis=2)
    source = resource(image, "vector", "normal")
    context = RenderContext(w, h, TextureFormat.RGBA16F)
    result = evaluate(
        cpu, registry.get("normal.transform"), source, context,
        {"angle": 27.0, "scale_x": 0.63, "scale_y": 1.24, "boundary": "Mirror", "filtering": "Bicubic"},
        "normal-transform",
    ).array
    vectors = result[..., :3] * 2.0 - 1.0
    lengths = np.linalg.norm(vectors, axis=2)
    assert float(np.max(np.abs(lengths - 1.0))) < 2.0e-5


def assert_safe_transform(registry, cpu: CpuBackend) -> None:
    # Integer lattice bases are the reason Safe Transform can preserve periodic
    # boundaries under rotation. Requested angles need not themselves be exact
    # lattice directions.
    for tiles, angle in ((1, 0.0), (2, 29.0), (4, -51.0), (7, 83.0)):
        a, b = _safe_lattice(tiles, -angle)
        assert isinstance(a, int) and isinstance(b, int)
        assert a != 0 or b != 0

    h = w = 128
    y, x = np.mgrid[0:h, 0:w]
    u = (x + 0.5) / w
    v = (y + 0.5) / h
    periodic = 0.5 + 0.23 * np.sin(2.0 * np.pi * u) + 0.19 * np.cos(2.0 * np.pi * v)
    source = resource(rgba(np.clip(periodic, 0.0, 1.0)), "grayscale", "periodic")
    context = RenderContext(w, h, TextureFormat.RGBA16F)
    result = evaluate(
        cpu, registry.get("transform.safe"), source, context,
        {"tiles": 3, "angle": 31.0, "tile_safe_rotation": True, "filtering": "Automatic"},
        "safe-periodic",
    ).array[..., 0]
    # Compare the seam jump to ordinary adjacent-pixel derivatives. A periodic
    # transform should not create an exceptional discontinuity at either edge.
    dx = np.abs(np.diff(result, axis=1))
    dy = np.abs(np.diff(result, axis=0))
    seam_x = np.abs(result[:, 0] - result[:, -1])
    seam_y = np.abs(result[0, :] - result[-1, :])
    assert float(np.quantile(seam_x, 0.95)) <= float(np.quantile(dx, 0.99)) * 1.7 + 1e-4
    assert float(np.quantile(seam_y, 0.95)) <= float(np.quantile(dy, 0.99)) * 1.7 + 1e-4

    # Pixel-snapped offsets must remain exact under Nearest filtering.
    shifted = evaluate(
        cpu, registry.get("transform.safe"), source, context,
        {"offset_x": 3.2 / w, "offset_y": -1.7 / h, "filtering": "Nearest"},
        "safe-snapped-offset",
    ).array[..., 0]
    expected = np.roll(source.array[..., 0], shift=(-2, 3), axis=(0, 1))
    assert np.array_equal(shifted, expected)


def assert_migration(registry) -> None:
    payload = {
        "version": 17,
        "nodes": [
            {"uid": "basic", "type": "transform.basic", "x": 0, "y": 0, "parameters": {"tile": False, "filtering": "Auto"}},
            {"uid": "rotate", "type": "transform.rotate", "x": 100, "y": 0, "parameters": {"wrap": True}},
            {"uid": "normal", "type": "normal.transform", "x": 200, "y": 0, "parameters": {"tile": True}},
        ],
        "groups": [], "connections": [], "active_node": "basic",
    }
    scene = GraphScene(registry)
    scene.from_dict(payload)
    assert scene.nodes["basic"].parameters["boundary"] == "Transparent"
    assert scene.nodes["basic"].parameters["filtering"] == "Automatic"
    assert "tile" not in scene.nodes["basic"].parameters
    assert scene.nodes["rotate"].parameters["boundary"] == "Seamless / Wrap"
    assert "wrap" not in scene.nodes["rotate"].parameters
    assert scene.nodes["normal"].parameters["boundary"] == "Seamless / Wrap"


def assert_gpu(registry, gpu: WgpuBackend, cpu: CpuBackend) -> None:
    if not gpu.available:
        print("Transform Quality GPU checks skipped:", gpu.info().detail)
        return
    h, w = 61, 79
    y, x = np.mgrid[0:h, 0:w]
    colour = np.zeros((h, w, 4), dtype=np.float32)
    colour[..., 0] = (x + 0.5) / w
    colour[..., 1] = (y + 0.5) / h
    colour[..., 2] = 0.5 + 0.25 * np.sin((x * 0.27) + (y * 0.19))
    colour[..., 3] = np.clip((x - 4) / 11.0, 0.0, 1.0)
    source = resource(colour, "color", "gpu-colour")
    context = RenderContext(w, h, TextureFormat.RGBA16F)
    cases = (
        ("transform.basic", {"offset_x": 0.08, "offset_y": -0.13, "scale_x": 0.72, "scale_y": 1.18, "angle": 23.0, "boundary": "Mirror", "filtering": "Bicubic"}),
        ("transform.safe", {"tiles": 3, "angle": 37.0, "tile_safe_rotation": True, "symmetry": "X", "filtering": "Automatic"}),
        ("transform.tile", {"tiles_x": 2.4, "tiles_y": 1.7, "filtering": "Automatic"}),
        ("transform.offset", {"offset_x": -0.17, "offset_y": 0.11, "boundary": "Seamless / Wrap", "filtering": "Bilinear"}),
        ("transform.rotate", {"angle": -41.0, "boundary": "Clamp", "filtering": "Bicubic"}),
        ("transform.scale", {"scale_x": 0.43, "scale_y": 1.34, "boundary": "Transparent", "filtering": "Automatic"}),
        ("transform.crop", {"left": 0.13, "right": 0.81, "top": 0.07, "bottom": 0.93, "filtering": "Bicubic"}),
        ("transform.perspective", {"top_left_x": 0.08, "top_left_y": 0.04, "top_right_x": 0.91, "top_right_y": 0.12, "bottom_right_x": 0.98, "bottom_right_y": 0.94, "filtering": "Automatic"}),
    )
    gpu_source = gpu.ensure_gpu(source, context)
    for index, (type_id, overrides) in enumerate(cases):
        definition = registry.get(type_id)
        params = definition.default_parameters()
        params.update(overrides)
        cpu_result = cpu.evaluate_node(definition, {"Image": source}, params, context, f"transform-quality:cpu:{index}")
        gpu_result = gpu.to_cpu(gpu.evaluate_node(definition, {"Image": gpu_source}, params, context, f"transform-quality:gpu:{index}"))
        difference = np.abs(cpu_result.array - gpu_result.array)
        assert float(np.mean(difference)) < 0.004, (type_id, difference.mean(), difference.max())
        assert float(np.quantile(difference, 0.99)) < 0.012, (type_id, difference.mean(), difference.max())


def main() -> None:
    app = QApplication.instance() or QApplication([])
    registry = build_registry()
    gpu = WgpuBackend()
    cpu = CpuBackend(gpu)
    assert_registry(registry)
    assert_identity_and_pixel_alignment(registry, cpu)
    assert_rectangular_pixel_space(registry, cpu)
    assert_shared_shader_include()
    assert_premultiplied_alpha(registry, cpu)
    assert_filtering_and_minification(registry, cpu)
    assert_boundaries(registry, cpu)
    assert_vectors(registry, cpu)
    assert_safe_transform(registry, cpu)
    assert_migration(registry)
    assert_gpu(registry, gpu, cpu)
    print("Transform Quality checks passed: shared pixel centres, typed alpha/vector filtering, adaptive minification, four boundary modes, exact identity/pixel moves, legacy migration and distinct tiling-safe transforms")


if __name__ == "__main__":
    main()
