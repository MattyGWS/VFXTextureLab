from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vfx_texture_lab.engine.evaluator import _prepare_cpu_preview_rgba8
from vfx_texture_lab.exporting import ExportOptions, prepare_export_array


def linear_to_srgb(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, 0.0, 1.0)
    return np.where(
        values <= 0.0031308,
        values * 12.92,
        1.055 * np.power(values, 1.0 / 2.4) - 0.055,
    )


def main() -> int:
    ramp = np.linspace(0.0, 1.0, 257, dtype=np.float32)
    source = np.zeros((1, ramp.size, 4), dtype=np.float32)
    source[..., 0] = ramp
    source[..., 1] = ramp
    source[..., 2] = ramp
    source[..., 3] = 1.0

    preview = _prepare_cpu_preview_rgba8(source, ramp.size, 1, "grayscale")
    linear = prepare_export_array(
        source,
        ExportOptions("PNG", 16, "Grayscale", "Red", "Linear"),
    )
    expected_linear = (linear[..., 0] * 255.0 + 0.5).astype(np.uint8)
    assert np.array_equal(preview[..., 0], expected_linear)

    normal_preview = _prepare_cpu_preview_rgba8(source, ramp.size, 1, "vector")
    normal_export = prepare_export_array(
        source,
        ExportOptions("PNG", 8, "RGB", "Luminance", "Linear"),
    )
    expected_normal = (normal_export[..., :3] * 255.0 + 0.5).astype(np.uint8)
    assert np.array_equal(normal_preview[..., :3], expected_normal)

    colour_export = prepare_export_array(
        source,
        ExportOptions("PNG", 8, "RGB", "Luminance", "sRGB"),
    )
    assert np.allclose(colour_export[..., :3], linear_to_srgb(source[..., :3]), atol=1e-6)
    assert float(colour_export[0, 128, 0]) > float(linear[0, 128, 0])

    print("Preview/export parity test passed: grayscale and normal data remain numeric; only colour receives sRGB transfer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
