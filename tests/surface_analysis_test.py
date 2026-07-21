from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext
from vfx_texture_lab.nodes.processing import eval_blend, eval_height_normal


def _rgba(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    return np.stack((values, values, values, np.ones_like(values)), axis=2)


def _flat_normal(width: int, height: int) -> np.ndarray:
    result = np.empty((height, width, 4), dtype=np.float32)
    result[..., 0] = 0.5
    result[..., 1] = 0.5
    result[..., 2] = 1.0
    result[..., 3] = 1.0
    return result


def assert_registry_contracts() -> None:
    registry = build_registry()
    height = registry.get("terrain.curvature")
    assert height.name == "Height Curvature"
    assert height.input_kind("Height") == "grayscale"
    flat_height = _rgba(np.full((31, 47), 0.42, dtype=np.float32))
    height_output = height.evaluator(
        {"Height": flat_height},
        {**height.default_parameters(), "mode": "Signed"},
        EvalContext(47, 31),
    )
    assert np.array_equal(height_output[..., 0], np.full((31, 47), 0.5, dtype=np.float32))

    curvature = registry.get("filter.curvature")
    sobel = registry.get("filter.curvature_sobel")
    smooth = registry.get("filter.curvature_smooth")
    hbao = registry.get("filter.ambient_occlusion_hbao")
    rtao = registry.get("filter.ambient_occlusion_rtao")
    assert curvature.category == sobel.category == smooth.category == hbao.category == rtao.category == "Filters/Surface Analysis"
    assert curvature.input_kind("Normal") == sobel.input_kind("Normal") == smooth.input_kind("Normal") == "vector"
    assert smooth.output_names == ("Curvature", "Convexity", "Concavity")
    assert all(smooth.output_kind(name) == "grayscale" for name in smooth.output_names)
    assert hbao.input_kind("Height") == rtao.input_kind("Height") == "grayscale"
    assert hbao.output_kind("Image") == rtao.output_kind("Image") == "grayscale"
    assert hbao.gpu_kernel == "ambient_occlusion_hbao.wgsl"
    assert rtao.gpu_kernel == "ambient_occlusion_rtao.wgsl"
    defaults = rtao.default_parameters()
    assert defaults["samples"] == 16
    assert defaults["distribution"] == "Uniform"
    assert defaults["spread_angle"] == 1.0


def assert_flat_curvature_is_overlay_neutral() -> None:
    registry = build_registry()
    context = EvalContext(73, 51)
    normal = _flat_normal(context.width, context.height)
    base = np.empty((context.height, context.width, 4), dtype=np.float32)
    y, x = np.mgrid[0:context.height, 0:context.width]
    base[..., 0] = (x + 0.5) / context.width
    base[..., 1] = (y + 0.5) / context.height
    base[..., 2] = 0.21 + 0.53 * base[..., 0]
    base[..., 3] = 1.0

    for type_id in ("filter.curvature", "filter.curvature_sobel"):
        definition = registry.get(type_id)
        output = definition.evaluator({"Normal": normal}, definition.default_parameters(), context)
        assert np.array_equal(output[..., 0], np.full((context.height, context.width), 0.5, dtype=np.float32))
        blended = eval_blend(
            {"Foreground": output, "Background": base},
            {"mode": "Overlay", "opacity": 1.0},
            context,
        )
        assert np.array_equal(blended, base), type_id

    smooth = registry.get("filter.curvature_smooth")
    signed = smooth.evaluator({"Normal": normal}, {**smooth.default_parameters(), "preview_output": "Curvature"}, context)
    convex = smooth.evaluator({"Normal": normal}, {**smooth.default_parameters(), "preview_output": "Convexity"}, context)
    concave = smooth.evaluator({"Normal": normal}, {**smooth.default_parameters(), "preview_output": "Concavity"}, context)
    assert np.array_equal(signed[..., 0], np.full((context.height, context.width), 0.5, dtype=np.float32))
    assert not np.any(convex[..., 0])
    assert not np.any(concave[..., 0])


def assert_normal_curvature_detects_convex_and_concave_detail() -> None:
    registry = build_registry()
    context = EvalContext(256, 256)
    y, x = np.mgrid[0:context.height, 0:context.width]
    u = (x.astype(np.float32) + 0.5) / context.width - 0.5
    v = (y.astype(np.float32) + 0.5) / context.height - 0.5
    bump = np.exp(-(u * u + v * v) / np.float32(2.0 * 0.08 * 0.08)).astype(np.float32)
    normal = eval_height_normal(
        {"Height": _rgba(bump)},
        {"strength": 24.0, "invert_y": False},
        context,
    )

    for type_id in ("filter.curvature", "filter.curvature_sobel"):
        definition = registry.get(type_id)
        output = definition.evaluator({"Normal": normal}, definition.default_parameters(), context)[..., 0]
        assert float(output[context.height // 2, context.width // 2]) > (0.51 if type_id == "filter.curvature" else 0.53), type_id
        assert float(np.min(output)) < 0.5, type_id

    smooth = registry.get("filter.curvature_smooth")
    signed = smooth.evaluator({"Normal": normal}, {**smooth.default_parameters(), "preview_output": "Curvature"}, context)[..., 0]
    convex = smooth.evaluator({"Normal": normal}, {**smooth.default_parameters(), "preview_output": "Convexity"}, context)[..., 0]
    concave = smooth.evaluator({"Normal": normal}, {**smooth.default_parameters(), "preview_output": "Concavity"}, context)[..., 0]
    assert float(signed[context.height // 2, context.width // 2]) > 0.53
    assert float(convex.max()) > 0.05
    assert float(concave.max()) > 0.0
    assert np.all((convex == 0.0) | (concave == 0.0))


def assert_normal_format_conversion_matches() -> None:
    registry = build_registry()
    context = EvalContext(96, 80)
    y, x = np.mgrid[0:context.height, 0:context.width]
    height = (0.5 + 0.25 * np.sin(x * 0.19) + 0.18 * np.cos(y * 0.23)).astype(np.float32)
    ogl = eval_height_normal({"Height": _rgba(height)}, {"strength": 12.0, "invert_y": False}, context)
    dx = ogl.copy(); dx[..., 1] = 1.0 - dx[..., 1]
    for type_id in ("filter.curvature", "filter.curvature_sobel", "filter.curvature_smooth"):
        definition = registry.get(type_id)
        params = definition.default_parameters()
        if type_id == "filter.curvature_smooth":
            params["preview_output"] = "Curvature"
        ogl_result = definition.evaluator({"Normal": ogl}, {**params, "normal_format": "OpenGL (+Y)"}, context)
        dx_result = definition.evaluator({"Normal": dx}, {**params, "normal_format": "DirectX (-Y)"}, context)
        assert np.allclose(ogl_result, dx_result, atol=1e-6), type_id


def assert_hbao_height_behaviour_and_draft_quality() -> None:
    registry = build_registry()
    definition = registry.get("filter.ambient_occlusion_hbao")
    context = EvalContext(128, 128)
    flat = _rgba(np.zeros((context.height, context.width), dtype=np.float32))
    flat_result = definition.evaluator({"Height": flat}, definition.default_parameters(), context)[..., 0]
    assert np.array_equal(flat_result, np.ones_like(flat_result))
    zero_radius = definition.evaluator(
        {"Height": flat}, {**definition.default_parameters(), "radius": 0.0}, context
    )[..., 0]
    assert np.array_equal(zero_radius, np.ones_like(zero_radius))

    height = np.zeros((context.height, context.width), dtype=np.float32)
    height[48:80, 48:80] = 1.0
    params = {
        **definition.default_parameters(),
        "height_depth": 0.20,
        "radius": 0.20,
        "quality": "16 Samples",
        "contrast": 1.0,
    }
    result = definition.evaluator({"Height": _rgba(height)}, params, context)[..., 0]
    assert float(result.min()) < 0.75
    assert float(result[64, 64]) > 0.99  # the flat top is not self-occluded
    assert float(result[48, 64]) > 0.99  # a hard top silhouette stays white, not black-lined
    assert 0.35 < float(result[47, 64]) < 0.8  # contact AO is present but not a clipped contour
    edge_profile = result[47:43:-1, 64]
    assert np.all(np.diff(edge_profile) >= -1e-5)  # contact darkening reconstructs smoothly outward
    assert np.isfinite(result).all()
    assert float(result.min()) >= 0.0 and float(result.max()) <= 1.0

    interactive = EvalContext(128, 128, render_mode="interactive")
    draft = definition.evaluator({"Height": _rgba(height)}, params, interactive)[..., 0]
    assert np.isfinite(draft).all()
    assert float(draft.min()) < 0.85

    inverted = definition.evaluator({"Height": _rgba(height)}, {**params, "invert": True}, context)[..., 0]
    assert np.allclose(inverted, 1.0 - result, atol=1e-7)

    # A circular blocker should produce an isotropic halo rather than visible
    # repeated spokes or flower petals from the directional sample pattern.
    yy, xx = np.mgrid[0:context.height, 0:context.width]
    disc = (((xx - 64) ** 2 + (yy - 64) ** 2) < 10 ** 2).astype(np.float32)
    disc_params = {
        **definition.default_parameters(),
        "height_depth": 0.30,
        "radius": 0.25,
        "quality": "16 Samples",
        "contrast": 1.0,
    }
    disc_result = definition.evaluator({"Height": _rgba(disc)}, disc_params, context)[..., 0]
    ring = np.asarray([
        disc_result[
            int(round(64 + np.sin(angle) * 16)),
            int(round(64 + np.cos(angle) * 16)),
        ]
        for angle in np.linspace(0.0, np.pi * 2.0, 256, endpoint=False)
    ])
    assert float(np.std(ring)) < 0.02
    ring_second_difference = np.roll(ring, -1) - 2.0 * ring + np.roll(ring, 1)
    assert float(np.std(ring_second_difference)) < 0.03

    # The top of Height Depth's authored range must remain useful rather than
    # visually saturating around its midpoint.
    depth_06 = definition.evaluator(
        {"Height": _rgba(disc)}, {**disc_params, "height_depth": 0.60}, context
    )[..., 0]
    depth_10 = definition.evaluator(
        {"Height": _rgba(disc)}, {**disc_params, "height_depth": 1.00}, context
    )[..., 0]
    depth_ring_06 = np.asarray([
        depth_06[
            int(round(64 + np.sin(angle) * 16)),
            int(round(64 + np.cos(angle) * 16)),
        ]
        for angle in np.linspace(0.0, np.pi * 2.0, 256, endpoint=False)
    ])
    depth_ring_10 = np.asarray([
        depth_10[
            int(round(64 + np.sin(angle) * 16)),
            int(round(64 + np.cos(angle) * 16)),
        ]
        for angle in np.linspace(0.0, np.pi * 2.0, 256, endpoint=False)
    ])
    assert float(np.mean(depth_ring_06 - depth_ring_10)) > 0.04



def assert_rtao_ray_traced_height_behaviour() -> None:
    registry = build_registry()
    definition = registry.get("filter.ambient_occlusion_rtao")
    context = EvalContext(96, 96)
    flat = _rgba(np.zeros((context.height, context.width), dtype=np.float32))
    defaults = definition.default_parameters()
    flat_result = definition.evaluator({"Height": flat}, defaults, context)[..., 0]
    assert np.array_equal(flat_result, np.ones_like(flat_result))

    for disabled in (
        {"height_scale": 0.0},
        {"maximum_distance": 0.0},
        {"spread_angle": 0.0},
    ):
        result = definition.evaluator({"Height": flat}, {**defaults, **disabled}, context)[..., 0]
        assert np.array_equal(result, np.ones_like(result)), disabled

    height = np.zeros((context.height, context.width), dtype=np.float32)
    height[36:60, 36:60] = 1.0
    params = {
        **defaults,
        "height_scale": 1.0,
        "samples": 24,
        "distribution": "Uniform",
        "maximum_distance": 0.25,
        "spread_angle": 1.0,
        "denoise": 0.8,
        "boundary": "Clamp",
    }
    result = definition.evaluator({"Height": _rgba(height)}, params, context)[..., 0]
    assert np.isfinite(result).all()
    assert float(result.min()) < 0.75
    assert float(result[48, 48]) > 0.99
    assert float(result[36, 48]) > 0.98  # no black line on the raised top edge
    assert float(result[35, 48]) < 0.85  # lower surface receives contact AO
    assert float(result[25, 48]) > float(result[34, 48])

    short = definition.evaluator(
        {"Height": _rgba(height)},
        {**params, "maximum_distance": 0.06},
        context,
    )[..., 0]
    long = definition.evaluator(
        {"Height": _rgba(height)},
        {**params, "maximum_distance": 0.35},
        context,
    )[..., 0]
    assert float(long[24:35, 48].mean()) < float(short[24:35, 48].mean()) - 0.02

    for distribution in ("Uniform", "Cosine Weighted", "Horizon Weighted"):
        distributed = definition.evaluator(
            {"Height": _rgba(height)}, {**params, "distribution": distribution}, context
        )[..., 0]
        assert np.isfinite(distributed).all(), distribution
        assert float(distributed.min()) < 0.9, distribution

    interactive = definition.evaluator(
        {"Height": _rgba(height)}, params,
        EvalContext(context.width, context.height, render_mode="interactive"),
    )[..., 0]
    assert np.isfinite(interactive).all()
    assert float(interactive.min()) < 0.9

    inverted = definition.evaluator(
        {"Height": _rgba(height)}, {**params, "invert": True}, context
    )[..., 0]
    assert np.allclose(inverted, 1.0 - result, atol=1e-6)

    # A smooth planar ramp should not occlude itself. The local tangent removes
    # the ramp before ray intersection, just as it does for HBAO.
    ramp = np.tile(np.linspace(0.0, 1.0, context.width, dtype=np.float32), (context.height, 1))
    ramp_result = definition.evaluator(
        {"Height": _rgba(ramp)}, {**params, "boundary": "Clamp"}, context
    )[..., 0]
    assert float(ramp_result[:, 16:-16].min()) > 0.94

def main() -> int:
    assert_registry_contracts()
    assert_flat_curvature_is_overlay_neutral()
    assert_normal_curvature_detects_convex_and_concave_detail()
    assert_normal_format_conversion_matches()
    assert_hbao_height_behaviour_and_draft_quality()
    assert_rtao_ray_traced_height_behaviour()
    print(
        "Surface analysis test passed: Height Curvature naming, normal-derived Curvature/Sobel/Smooth, exact neutral-grey Overlay behaviour, "
        "normal convention handling, split convexity/concavity outputs, fast HBAO and ray-marched RTAO are correct."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
