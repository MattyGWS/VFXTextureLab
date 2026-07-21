from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext
from vfx_texture_lab.nodes.image_ops import grayscale_rgba, srgb_to_linear


def _linear_to_srgb(values: np.ndarray) -> np.ndarray:
    values = np.clip(np.asarray(values, dtype=np.float32), 0.0, 1.0)
    return np.where(
        values <= 0.0031308,
        values * 12.92,
        1.055 * np.power(values, 1.0 / 2.4) - 0.055,
    )


def _display_bytes(image: np.ndarray, x: int) -> tuple[int, int, int]:
    rgb = _linear_to_srgb(image[0, x, :3])
    values = np.floor(rgb * 255.0 + 0.5).astype(np.uint8)
    return int(values[0]), int(values[1]), int(values[2])


def main() -> None:
    registry = build_registry()
    definition = registry.get("convert.gradient_map")
    assert definition.evaluator is not None
    context = EvalContext(width=5, height=1)
    values = np.array([[0.0, 0.25, 0.5, 0.75, 1.0]], dtype=np.float32)
    source = grayscale_rgba(values)

    black_white = {
        "stops": [
            {"position": 0.0, "color": "#000000ff"},
            {"position": 1.0, "color": "#ffffffff"},
        ]
    }
    result = definition.evaluator({"Image": source}, black_white, context)
    expected_mid = float(srgb_to_linear(np.array([0.5], dtype=np.float32))[0])
    assert abs(float(result[0, 2, 0]) - expected_mid) < 1e-6
    assert np.allclose(result[0, 2, :3], expected_mid, atol=1e-6)
    assert _display_bytes(result, 2) == (128, 128, 128)
    assert _display_bytes(result, 1) == (64, 64, 64)
    assert _display_bytes(result, 3) == (191, 191, 191)

    coloured = {
        "stops": [
            {"position": 0.0, "color": "#ff000040"},
            {"position": 0.5, "color": "#0000ff80"},
            {"position": 1.0, "color": "#00ff00c0"},
        ]
    }
    colour_result = definition.evaluator({"Image": source}, coloured, context)
    expected_quarter = srgb_to_linear(np.array([0.5, 0.0, 0.5], dtype=np.float32))
    expected_three_quarter = srgb_to_linear(np.array([0.0, 0.5, 0.5], dtype=np.float32))
    assert np.allclose(colour_result[0, 1, :3], expected_quarter, atol=1e-6)
    assert np.allclose(colour_result[0, 3, :3], expected_three_quarter, atol=1e-6)
    assert _display_bytes(colour_result, 1) == (128, 0, 128)
    assert _display_bytes(colour_result, 2) == (0, 0, 255)
    assert _display_bytes(colour_result, 3) == (0, 128, 128)
    assert abs(float(colour_result[0, 2, 3]) - (0x80 / 255.0)) < 1e-6
    assert abs(float(colour_result[0, 1, 3]) - ((0x40 + 0x80) / (2.0 * 255.0))) < 1e-6

    shader = (Path(__file__).resolve().parents[1] / "vfx_texture_lab" / "shaders" / "gradient_map.wgsl").read_text()
    assert "srgb_to_linear(display_result.rgb)" in shader
    assert "display_result.a" in shader

    print("Gradient Map colour-space test passed: editor/display ramp matches while graph output remains linear")


if __name__ == "__main__":
    main()
