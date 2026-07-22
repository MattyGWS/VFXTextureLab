from __future__ import annotations

import numpy as np

from vfx_texture_lab.nodes.base import EvalContext
from vfx_texture_lab.nodes.generators import eval_color
from vfx_texture_lab.nodes.image_ops import linear_to_srgb, srgb_to_linear


def test_colour_generator_converts_picker_srgb_to_linear_once() -> None:
    display_rgba8 = np.array([0x7A, 0x74, 0x44, 0xA6], dtype=np.uint8)
    result = eval_color(
        {},
        {"color": "#7A7444A6"},
        EvalContext(width=4, height=3),
    )

    expected_rgb = srgb_to_linear(display_rgba8[:3].astype(np.float32) / np.float32(255.0))
    assert result.shape == (3, 4, 4)
    assert np.allclose(result[..., :3], expected_rgb, atol=1e-7)
    assert np.allclose(result[..., 3], display_rgba8[3] / 255.0, atol=1e-7)

    preview_rgb8 = np.rint(linear_to_srgb(result[0, 0, :3]) * 255.0).astype(np.uint8)
    assert np.array_equal(preview_rgb8, display_rgba8[:3])
