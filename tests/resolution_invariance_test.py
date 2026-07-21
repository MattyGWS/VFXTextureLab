from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext
from vfx_texture_lab.nodes.image_ops import resolution_scale


def _resize(image: np.ndarray, size: int) -> np.ndarray:
    channels = []
    for index in range(image.shape[2]):
        source = Image.fromarray(np.asarray(image[..., index], dtype=np.float32), mode="F")
        channels.append(np.asarray(source.resize((size, size), Image.Resampling.BILINEAR), dtype=np.float32))
    return np.stack(channels, axis=2)


def _shape(registry, size: int) -> np.ndarray:
    definition = registry.get("shape.shape")
    params = definition.default_parameters()
    params.update({
        "shape": "Disc",
        "size_x": 0.46,
        "size_y": 0.46,
        "edge_softness": 0.02,
        "center_x": 0.43,
        "center_y": 0.57,
    })
    return definition.evaluator({}, params, EvalContext(size, size))


def _compare(low: np.ndarray, high: np.ndarray, *, mean_limit: float, p99_limit: float) -> None:
    reduced = _resize(high, low.shape[0])
    difference = np.abs(low[..., :3] - reduced[..., :3])
    assert float(difference.mean()) < mean_limit, (difference.mean(), np.quantile(difference, 0.99))
    assert float(np.quantile(difference, 0.99)) < p99_limit, (difference.mean(), np.quantile(difference, 0.99))


def main() -> int:
    registry = build_registry()
    low_size = 128
    high_size = 512
    assert abs(resolution_scale(EvalContext(low_size, low_size)) * 4.0 - resolution_scale(EvalContext(high_size, high_size))) < 1e-9

    # Normalised generators must preserve their authored proportions.
    low_shape = _shape(registry, low_size)
    high_shape = _shape(registry, high_size)
    low_area = float(np.mean(low_shape[..., 0] > 0.5))
    high_area = float(np.mean(high_shape[..., 0] > 0.5))
    assert abs(low_area - high_area) < 0.006, (low_area, high_area)
    _compare(low_shape, high_shape, mean_limit=0.004, p99_limit=0.08)

    cases = (
        ("filter.directional_blur", {"distance": 24.0, "angle": 31.0, "samples": 8}, "Image", 0.004, 0.08),
        ("filter.zoom_blur", {"amount": 24.0, "samples": 8}, "Image", 0.004, 0.08),
        ("filter.anisotropic_blur", {"intensity": 24.0, "anisotropy": 0.55, "angle": -28.0, "samples": 6}, "Image", 0.004, 0.08),
        ("filter.non_uniform_blur_grayscale", {"radius": 20.0, "samples": 6}, "Image", 0.005, 0.10),
        ("filter.distance", {"distance": 24.0}, "Image", 0.006, 0.12),
        ("filter.bevel", {"width": 16.0}, "Image", 0.008, 0.16),
        ("filter.outline", {"width": 10.0, "softness": 1.0}, "Image", 0.012, 0.38),
        ("filter.aperture", {"size": 4}, "Image", 0.008, 0.16),
        ("convert.height_normal", {"strength": 8.0}, "Height", 0.006, 0.14),
        ("terrain.curvature", {"strength": 8.0}, "Height", 0.010, 0.22),
    )
    for type_id, overrides, input_name, mean_limit, p99_limit in cases:
        definition = registry.get(type_id)
        outputs = []
        for size in (low_size, high_size):
            params = definition.default_parameters()
            params.update(overrides)
            source = _shape(registry, size)
            outputs.append(definition.evaluator({input_name: source}, params, EvalContext(size, size)))
        _compare(outputs[0], outputs[1], mean_limit=mean_limit, p99_limit=p99_limit)

    # Every artist-facing pixel-space parameter now declares relative units.
    relative_parameters = {
        "filter.blur": ("radius",),
        "filter.directional_blur": ("distance",),
        "filter.zoom_blur": ("amount",),
        "filter.anisotropic_blur": ("intensity",),
        "filter.non_uniform_blur_grayscale": ("radius",),
        "filter.slope_blur_grayscale": ("intensity",),
        "filter.distance": ("distance", "edge_offset"),
        "filter.bevel": ("width", "edge_offset"),
        "filter.expand_shrink": ("amount", "softness"),
        "filter.outline": ("width", "edge_offset", "softness"),
        "filter.aperture": ("size",),
    }
    for type_id, names in relative_parameters.items():
        specs = {spec.name: spec for spec in registry.get(type_id).parameters}
        for name in names:
            assert specs[name].unit == "rpx", (type_id, name, specs[name].unit)

    print("Resolution invariance test passed: generators, spatial filters, morphology, normals and curvature preserve their authored look across 4x resolution changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
