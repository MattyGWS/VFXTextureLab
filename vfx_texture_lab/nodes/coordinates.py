from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Mapping

import numpy as np

from .base import EvalContext, ImageArray, NodeDefinition, ParameterSpec
from .image_ops import empty_image, ensure_rgba, luminance
from .registry import NodeRegistry
from .resampling import BOUNDARY_OPTIONS, FILTERING_OPTIONS, boundary_name, sample_image

_TRANSFORM_ACCENT = "#bd7a57"
_COORDINATE_ACCENT = "#8a6ac7"
_DISTORTION_ACCENT = "#b15e78"
_TAU = math.tau


def _input(inputs: Mapping[str, ImageArray], name: str, context: EvalContext, value: float = 0.0) -> ImageArray:
    return ensure_rgba(inputs.get(name, empty_image(context, value=value)), context)


def _uv_grid(context: EvalContext) -> tuple[np.ndarray, np.ndarray]:
    y, x = np.mgrid[0 : context.height, 0 : context.width]
    u = (x.astype(np.float32) + 0.5) / max(context.width, 1)
    v = (y.astype(np.float32) + 0.5) / max(context.height, 1)
    return u, v


def _sample_bilinear(image: ImageArray, u: np.ndarray, v: np.ndarray, *, wrap: bool) -> ImageArray:
    """Sample normalized UV coordinates with GPU-matching bilinear filtering.

    Wrapped nodes remain seamless across every border. Non-wrapped nodes use a
    transparent border rather than smearing the edge pixel into empty space.
    """
    source = ensure_rgba(image)
    height, width = source.shape[:2]
    if wrap:
        u = np.mod(u, 1.0)
        v = np.mod(v, 1.0)
        valid = None
    else:
        valid = (u >= 0.0) & (u <= 1.0) & (v >= 0.0) & (v <= 1.0)

    px = u * width - 0.5
    py = v * height - 0.5
    x0_raw = np.floor(px).astype(np.int64)
    y0_raw = np.floor(py).astype(np.int64)
    fx = (px - x0_raw)[..., None].astype(np.float32)
    fy = (py - y0_raw)[..., None].astype(np.float32)

    if wrap:
        x0 = np.mod(x0_raw, width)
        y0 = np.mod(y0_raw, height)
        x1 = np.mod(x0_raw + 1, width)
        y1 = np.mod(y0_raw + 1, height)
    else:
        x0 = np.clip(x0_raw, 0, width - 1)
        y0 = np.clip(y0_raw, 0, height - 1)
        x1 = np.clip(x0_raw + 1, 0, width - 1)
        y1 = np.clip(y0_raw + 1, 0, height - 1)

    top = source[y0, x0] * (1.0 - fx) + source[y0, x1] * fx
    bottom = source[y1, x0] * (1.0 - fx) + source[y1, x1] * fx
    result = top * (1.0 - fy) + bottom * fy
    if valid is not None:
        result = result.copy()
        result[~valid] = 0.0
    return np.nan_to_num(result, nan=0.0, posinf=1.0, neginf=0.0).astype(np.float32)


def eval_uv_gradient(_inputs: Mapping[str, ImageArray], _params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    u, v = _uv_grid(context)
    output = np.empty((context.height, context.width, 4), dtype=np.float32)
    output[..., 0] = u
    output[..., 1] = v
    output[..., 2] = 0.5
    output[..., 3] = 1.0
    return output


def eval_tile(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    u, v = _uv_grid(context)
    tiles_x = max(float(params.get("tiles_x", 2.0)), 0.001)
    tiles_y = max(float(params.get("tiles_y", 2.0)), 0.001)
    if abs(tiles_x - 1.0) <= 1.0e-12 and abs(tiles_y - 1.0) <= 1.0e-12:
        return image.copy()
    return sample_image(
        image, u * tiles_x * context.width - 0.5, v * tiles_y * context.height - 0.5,
        filtering=str(params.get("filtering", "Automatic")), boundary="Seamless / Wrap",
        data_kind=str(params.get("_resolved_kind", "grayscale")),
        footprint_x=tiles_x, footprint_y=tiles_y,
    )


def eval_offset(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    offset_x = float(params.get("offset_x", 0.0))
    offset_y = float(params.get("offset_y", 0.0))
    if abs(offset_x) <= 1.0e-12 and abs(offset_y) <= 1.0e-12:
        return image.copy()
    u, v = _uv_grid(context)
    source_u = u - offset_x
    source_v = v - offset_y
    pixel_dx = offset_x * context.width
    pixel_dy = offset_y * context.height
    pixel_aligned = abs(pixel_dx - round(pixel_dx)) <= 1.0e-7 and abs(pixel_dy - round(pixel_dy)) <= 1.0e-7
    return sample_image(
        image, source_u * context.width - 0.5, source_v * context.height - 0.5,
        filtering="Nearest" if pixel_aligned else str(params.get("filtering", "Automatic")),
        boundary=boundary_name(params, default="Seamless / Wrap", legacy_key="wrap"),
        data_kind=str(params.get("_resolved_kind", "grayscale")),
    )


def eval_rotate(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    angle_degrees = float(params.get("angle", 0.0))
    if abs(math.fmod(angle_degrees, 360.0)) <= 1.0e-12:
        return image.copy()
    u, v = _uv_grid(context)
    pixel_x = (u - 0.5) * context.width
    pixel_y = (v - 0.5) * context.height
    angle = -math.radians(angle_degrees)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    source_x = pixel_x * cosine - pixel_y * sine + (context.width - 1.0) * 0.5
    source_y = pixel_x * sine + pixel_y * cosine + (context.height - 1.0) * 0.5
    return sample_image(
        image, source_x, source_y,
        filtering=str(params.get("filtering", "Automatic")),
        boundary=boundary_name(params, default="Seamless / Wrap", legacy_key="wrap"),
        data_kind=str(params.get("_resolved_kind", "grayscale")),
    )


def eval_scale(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    u, v = _uv_grid(context)
    scale_x = max(float(params.get("scale_x", 1.0)), 0.001)
    scale_y = max(float(params.get("scale_y", 1.0)), 0.001)
    if abs(scale_x - 1.0) <= 1.0e-12 and abs(scale_y - 1.0) <= 1.0e-12:
        return image.copy()
    source_u = (u - 0.5) / scale_x + 0.5
    source_v = (v - 0.5) / scale_y + 0.5
    return sample_image(
        image, source_u * context.width - 0.5, source_v * context.height - 0.5,
        filtering=str(params.get("filtering", "Automatic")),
        boundary=boundary_name(params, default="Seamless / Wrap", legacy_key="wrap"),
        data_kind=str(params.get("_resolved_kind", "grayscale")),
        footprint_x=1.0 / scale_x, footprint_y=1.0 / scale_y,
    )


def eval_mirror(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    axis = str(params.get("axis", "Horizontal"))
    # Mirror is an exact pixel permutation, not a resampling operation. This
    # preserves alpha, masks and normal vectors bit-for-bit.
    if axis == "Horizontal":
        return np.ascontiguousarray(image[:, ::-1]).astype(np.float32, copy=False)
    if axis == "Vertical":
        return np.ascontiguousarray(image[::-1, :]).astype(np.float32, copy=False)
    return np.ascontiguousarray(image[::-1, ::-1]).astype(np.float32, copy=False)


def _aspect_delta(u: np.ndarray, v: np.ndarray, center_x: float, center_y: float, context: EvalContext) -> tuple[np.ndarray, np.ndarray, float]:
    aspect = context.width / max(context.height, 1)
    return (u - center_x) * aspect, v - center_y, aspect


def eval_swirl(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    u, v = _uv_grid(context)
    center_x = float(params.get("center_x", 0.5))
    center_y = float(params.get("center_y", 0.5))
    radius = max(float(params.get("radius", 0.5)), 1e-6)
    dx, dy, aspect = _aspect_delta(u, v, center_x, center_y, context)
    distance = np.sqrt(dx * dx + dy * dy)
    local = np.clip(1.0 - distance / radius, 0.0, 1.0)
    # Smooth falloff prevents a visible circular seam at the effect boundary.
    falloff = local * local * (3.0 - 2.0 * local)
    angle = -math.radians(float(params.get("angle", 180.0))) * falloff
    cosine = np.cos(angle)
    sine = np.sin(angle)
    source_dx = dx * cosine - dy * sine
    source_dy = dx * sine + dy * cosine
    source_u = center_x + source_dx / aspect
    source_v = center_y + source_dy
    return _sample_bilinear(image, source_u, source_v, wrap=bool(params.get("wrap", True)))


def eval_spherize(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    u, v = _uv_grid(context)
    center_x = float(params.get("center_x", 0.5))
    center_y = float(params.get("center_y", 0.5))
    radius = max(float(params.get("radius", 0.5)), 1e-6)
    amount = float(np.clip(float(params.get("amount", 0.5)), -1.0, 1.0))
    dx, dy, aspect = _aspect_delta(u, v, center_x, center_y, context)
    normalized_x = dx / radius
    normalized_y = dy / radius
    distance = np.sqrt(normalized_x * normalized_x + normalized_y * normalized_y)
    safe_distance = np.maximum(distance, 1e-8)
    bulged = distance * distance
    pinched = np.sqrt(np.maximum(distance, 0.0))
    target = np.where(amount >= 0.0, bulged, pinched)
    source_distance = distance * (1.0 - abs(amount)) + target * abs(amount)
    multiplier = np.where(distance < 1.0, source_distance / safe_distance, 1.0)
    source_u = center_x + dx * multiplier / aspect
    source_v = center_y + dy * multiplier
    return _sample_bilinear(image, source_u, source_v, wrap=bool(params.get("wrap", True)))


def eval_vector_warp(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    vector = _input(inputs, "Vector", context, 0.5)
    u, v = _uv_grid(context)
    strength = float(params.get("strength", 0.1))
    displacement_x = (vector[..., 0] * 2.0 - 1.0) * strength
    displacement_y = (vector[..., 1] * 2.0 - 1.0) * strength
    return _sample_bilinear(
        image,
        u - displacement_x,
        v - displacement_y,
        wrap=bool(params.get("wrap", True)),
    )


def eval_flow_map_distort(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    flow = _input(inputs, "Flow", context, 0.5)
    u, v = _uv_grid(context)
    strength = float(params.get("strength", 0.1))
    phase = float(params.get("phase", 0.0)) % 1.0
    displacement_x = (flow[..., 0] * 2.0 - 1.0) * strength
    displacement_y = (flow[..., 1] * 2.0 - 1.0) * strength
    phase_a = phase
    phase_b = (phase + 0.5) % 1.0
    first = _sample_bilinear(
        image, u - displacement_x * phase_a, v - displacement_y * phase_a,
        wrap=bool(params.get("wrap", True)),
    )
    second = _sample_bilinear(
        image, u - displacement_x * phase_b, v - displacement_y * phase_b,
        wrap=bool(params.get("wrap", True)),
    )
    first_weight = abs(phase * 2.0 - 1.0)
    return (second * (1.0 - first_weight) + first * first_weight).astype(np.float32)


def eval_directional_warp(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    intensity = np.clip(luminance(_input(inputs, "Intensity", context)), 0.0, 1.0)
    if bool(params.get("centered", True)):
        intensity = intensity * 2.0 - 1.0
    strength = float(params.get("strength", 0.08))
    angle = math.radians(float(params.get("angle", 0.0)))
    u, v = _uv_grid(context)
    return _sample_bilinear(
        image,
        u - math.cos(angle) * intensity * strength,
        v - math.sin(angle) * intensity * strength,
        wrap=bool(params.get("wrap", True)),
    )


def eval_cartesian_to_polar(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    """Unwrap a Cartesian/circular image into angle-by-radius polar space."""
    image = _input(inputs, "Image", context)
    angle_uv, radius_uv = _uv_grid(context)
    center_x = float(params.get("center_x", 0.5))
    center_y = float(params.get("center_y", 0.5))
    radius_scale = max(float(params.get("radius_scale", 1.0)), 1e-6)
    angle_offset = float(params.get("angle_offset", 0.0)) / 360.0
    clockwise = bool(params.get("clockwise", True))
    raw_angle = 1.0 - angle_uv if clockwise else angle_uv
    theta = (raw_angle - angle_offset - 0.5) * _TAU
    radius = radius_uv / (2.0 * radius_scale)
    aspect = context.width / max(context.height, 1)
    source_u = center_x + np.cos(theta) * radius / aspect
    source_v = center_y + np.sin(theta) * radius
    return _sample_bilinear(image, source_u, source_v, wrap=bool(params.get("wrap", True)))


def eval_polar_to_cartesian(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    """Wrap an angle-by-radius polar image around a Cartesian centre."""
    image = _input(inputs, "Image", context)
    u, v = _uv_grid(context)
    center_x = float(params.get("center_x", 0.5))
    center_y = float(params.get("center_y", 0.5))
    radius_scale = max(float(params.get("radius_scale", 1.0)), 1e-6)
    angle_offset = float(params.get("angle_offset", 0.0)) / 360.0
    dx, dy, _aspect = _aspect_delta(u, v, center_x, center_y, context)
    angle = np.arctan2(dy, dx) / _TAU + 0.5 + angle_offset
    if bool(params.get("clockwise", True)):
        angle = 1.0 - angle
    radius = np.sqrt(dx * dx + dy * dy) * 2.0 * radius_scale
    return _sample_bilinear(image, angle, radius, wrap=bool(params.get("wrap", True)))


def register_coordinate_nodes(registry: NodeRegistry) -> None:
    f = ParameterSpec
    image_preserve = dict(
        input_kinds=(("Image", "image_any"),),
        output_kinds=(("Image", "image_any"),),
        type_policy="preserve_primary",
        primary_input="Image",
    )
    wrap_parameter = lambda: f(
        "wrap", "Wrap", "bool", True,
        description="Wrap source coordinates seamlessly. Disabled coordinates outside the image become transparent.",
    )
    transform_boundary = lambda: f(
        "boundary", "Boundary", "enum", "Seamless / Wrap", options=BOUNDARY_OPTIONS,
        description="Choose transparent, clamped, mirrored or seamless sampling outside the source image.",
    )
    transform_filtering = lambda: f(
        "filtering", "Filtering", "enum", "Automatic", options=FILTERING_OPTIONS,
        description="Automatic uses bicubic magnification and area-aware minification.",
    )
    polar_parameters = (
        f("center_x", "Centre X", "float", 0.5, 0.0, 1.0, 0.01, animatable=True),
        f("center_y", "Centre Y", "float", 0.5, 0.0, 1.0, 0.01, animatable=True),
        f("radius_scale", "Radius Scale", "float", 1.0, 0.01, 4.0, 0.01, animatable=True),
        f("angle_offset", "Angle Offset", "float", 0.0, -360.0, 360.0, 1.0, animatable=True, slider_minimum=-180.0, slider_maximum=180.0, fine_step=1.0, coarse_step=5.0, editor="angle", unit="degrees"),
        f("clockwise", "Clockwise", "bool", True),
        wrap_parameter(),
    )

    definitions = [
        NodeDefinition(
            "coordinates.uv_gradient", "UV Gradient", "Coordinates", eval_uv_gradient,
            description="Generate normalized U and V coordinates in the red and green vector channels.",
            accent=_COORDINATE_ACCENT, tags=("uv", "coordinates", "vector", "gradient"),
            output_format="rgba16f", output_kinds=(("Image", "vector"),), default_image_kind="vector",
            gpu_kernel="uv_gradient.wgsl",
        ),
        NodeDefinition(
            "coordinates.cartesian_to_polar", "Cartesian to Polar", "Coordinates", eval_cartesian_to_polar,
            inputs=("Image",), parameters=polar_parameters,
            description="Unwrap a circular Cartesian image into horizontal angle and vertical radius coordinates.",
            accent=_COORDINATE_ACCENT, tags=("polar", "unwrap", "coordinates", "radial"),
            gpu_kernel="coordinate_polar.wgsl", **image_preserve,
        ),
        NodeDefinition(
            "coordinates.polar_to_cartesian", "Polar to Cartesian", "Coordinates", eval_polar_to_cartesian,
            inputs=("Image",), parameters=polar_parameters,
            description="Wrap an angle-by-radius polar image around a Cartesian centre.",
            accent=_COORDINATE_ACCENT, tags=("polar", "wrap", "coordinates", "radial", "shockwave"),
            gpu_kernel="coordinate_polar.wgsl", **image_preserve,
        ),
        NodeDefinition(
            "transform.tile", "Tile", "Transform", eval_tile, inputs=("Image",),
            parameters=(
                f("tiles_x", "Tiles X", "float", 2.0, 0.01, 100.0, 0.01, animatable=True, slider_maximum=16.0, fine_step=0.01, coarse_step=0.1),
                f("tiles_y", "Tiles Y", "float", 2.0, 0.01, 100.0, 0.01, animatable=True, slider_maximum=16.0, fine_step=0.01, coarse_step=0.1),
                transform_filtering(),
            ),
            description="Repeat an image independently across the horizontal and vertical axes.",
            accent=_TRANSFORM_ACCENT, tags=("tile", "repeat", "uv"), gpu_kernel="transform_simple.wgsl",
            **image_preserve,
        ),
        NodeDefinition(
            "transform.offset", "Offset", "Transform", eval_offset, inputs=("Image",),
            parameters=(
                f("offset_x", "Offset X", "float", 0.0, -100.0, 100.0, 0.001, animatable=True, slider_minimum=-2.0, slider_maximum=2.0, fine_step=0.01, coarse_step=0.1),
                f("offset_y", "Offset Y", "float", 0.0, -100.0, 100.0, 0.001, animatable=True, slider_minimum=-2.0, slider_maximum=2.0, fine_step=0.01, coarse_step=0.1),
                transform_boundary(),
                transform_filtering(),
            ),
            description="Move an image without also rotating or scaling it.",
            accent=_TRANSFORM_ACCENT, tags=("move", "translate", "offset", "uv"), gpu_kernel="transform_simple.wgsl",
            **image_preserve,
        ),
        NodeDefinition(
            "transform.rotate", "Rotate", "Transform", eval_rotate, inputs=("Image",),
            parameters=(
                f("angle", "Angle", "float", 0.0, -100000.0, 100000.0, 0.1, animatable=True, slider_minimum=-180.0, slider_maximum=180.0, fine_step=1.0, coarse_step=5.0, editor="angle", unit="degrees", angle_wrap=False, description="The dial and slider cover one turn; the dial accumulates and the numeric field accepts larger values for multi-turn animation."),
                transform_boundary(),
                transform_filtering(),
            ),
            description="Rotate an image around its centre.",
            accent=_TRANSFORM_ACCENT, tags=("rotate", "angle", "uv"), gpu_kernel="transform_simple.wgsl",
            **image_preserve,
        ),
        NodeDefinition(
            "transform.scale", "Scale", "Transform", eval_scale, inputs=("Image",),
            parameters=(
                f("scale_x", "Scale X", "float", 1.0, 0.01, 100.0, 0.01, animatable=True, slider_maximum=4.0, fine_step=0.01, coarse_step=0.1),
                f("scale_y", "Scale Y", "float", 1.0, 0.01, 100.0, 0.01, animatable=True, slider_maximum=4.0, fine_step=0.01, coarse_step=0.1),
                transform_boundary(),
                transform_filtering(),
            ),
            description="Scale an image independently around its centre on each axis.",
            accent=_TRANSFORM_ACCENT, tags=("scale", "resize", "uv"), gpu_kernel="transform_simple.wgsl",
            **image_preserve,
        ),
        NodeDefinition(
            "transform.mirror", "Mirror", "Transform", eval_mirror, inputs=("Image",),
            parameters=(f("axis", "Axis", "enum", "Horizontal", options=("Horizontal", "Vertical", "Both")),),
            description="Reflect an image across the selected axis.",
            accent=_TRANSFORM_ACCENT, tags=("mirror", "flip", "reflect"), gpu_kernel="transform_simple.wgsl",
            **image_preserve,
        ),
        NodeDefinition(
            "distortion.swirl", "Swirl", "Distortion", eval_swirl, inputs=("Image",),
            parameters=(
                f("angle", "Angle", "float", 180.0, -1440.0, 1440.0, 1.0, animatable=True, slider_minimum=-360.0, slider_maximum=360.0, fine_step=1.0, coarse_step=5.0, editor="angle", unit="degrees", angle_wrap=False, description="The dial shows direction and accumulates multiple turns while dragging."),
                f("radius", "Radius", "float", 0.5, 0.01, 2.0, 0.01, animatable=True),
                f("center_x", "Centre X", "float", 0.5, 0.0, 1.0, 0.01, animatable=True),
                f("center_y", "Centre Y", "float", 0.5, 0.0, 1.0, 0.01, animatable=True),
                wrap_parameter(),
            ),
            description="Twist an image around a centre with a smooth radial falloff.",
            accent=_DISTORTION_ACCENT, tags=("swirl", "twist", "vortex", "distort"), gpu_kernel="distortion_radial.wgsl",
            **image_preserve,
        ),
        NodeDefinition(
            "distortion.spherize", "Spherize", "Distortion", eval_spherize, inputs=("Image",),
            parameters=(
                f("amount", "Amount", "float", 0.5, -1.0, 1.0, 0.01, animatable=True,
                  description="Positive values bulge; negative values pinch."),
                f("radius", "Radius", "float", 0.5, 0.01, 2.0, 0.01, animatable=True),
                f("center_x", "Centre X", "float", 0.5, 0.0, 1.0, 0.01, animatable=True),
                f("center_y", "Centre Y", "float", 0.5, 0.0, 1.0, 0.01, animatable=True),
                wrap_parameter(),
            ),
            description="Bulge or pinch an image inside a circular region.",
            accent=_DISTORTION_ACCENT, tags=("spherize", "bulge", "pinch", "lens", "distort"), gpu_kernel="distortion_radial.wgsl",
            **image_preserve,
        ),
        NodeDefinition(
            "distortion.vector_warp", "Vector Warp", "Distortion", eval_vector_warp,
            inputs=("Image", "Vector"),
            parameters=(
                f("strength", "Strength", "float", 0.1, -2.0, 2.0, 0.001, animatable=True),
                wrap_parameter(),
            ),
            description="Displace an image in two dimensions using the red/green direction of a vector map.",
            accent=_DISTORTION_ACCENT, tags=("vector", "warp", "flow", "distort", "normal"),
            gpu_kernel="vector_warp.wgsl",
            input_kinds=(("Image", "image_any"), ("Vector", "vector")),
            output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image",
        ),
        NodeDefinition(
            "distortion.flow_map", "Flow Map Distort", "Distortion", eval_flow_map_distort,
            inputs=("Image", "Flow"),
            parameters=(
                f("strength", "Strength", "float", 0.1, -2.0, 2.0, 0.001, animatable=True),
                f("phase", "Phase", "float", 0.0, 0.0, 1.0, 0.001, animatable=True,
                  description="Animate from 0 to 1 for a seamlessly cross-faded flow cycle."),
                wrap_parameter(),
            ),
            description="Animate an image along a vector flow map with two-phase seamless cross-fading.",
            accent=_DISTORTION_ACCENT, tags=("flow map", "animated", "warp", "distort", "loop"),
            gpu_kernel="vector_warp.wgsl", uses_time=False,
            input_kinds=(("Image", "image_any"), ("Flow", "vector")),
            output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image",
        ),
        # Promote the previously bundled package to a native CPU/GPU node while
        # retaining its package type ID so every existing graph remains valid.
        NodeDefinition(
            "org.vfxtexturelab.directional_warp", "Directional Warp", "Distortion", eval_directional_warp,
            inputs=("Image", "Intensity"),
            parameters=(
                f("strength", "Strength", "float", 0.08, -1.0, 1.0, 0.005, animatable=True),
                f("angle", "Angle", "float", 0.0, -360.0, 360.0, 1.0, animatable=True, slider_minimum=-180.0, slider_maximum=180.0, fine_step=1.0, coarse_step=5.0, editor="angle", unit="degrees"),
                f("centered", "Centred Intensity", "bool", True,
                  description="Treat 0.5 as zero displacement; otherwise black is zero and white is full displacement."),
                wrap_parameter(),
            ),
            description="Offset an image along one chosen direction using a greyscale intensity map.",
            accent=_DISTORTION_ACCENT, tags=("warp", "distort", "offset", "direction", "flow"),
            gpu_kernel="directional_warp.wgsl",
            input_kinds=(("Image", "image_any"), ("Intensity", "grayscale")),
            output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image",
        ),
        # Old projects used this package ID for the rectangular-to-radial form.
        # It remains loadable but is hidden in favour of the two explicit nodes.
        NodeDefinition(
            "org.vfxtexturelab.polar_coordinates", "Polar Coordinates (Legacy)", "Coordinates", eval_polar_to_cartesian,
            inputs=("Image",), parameters=polar_parameters,
            description="Compatibility form of Polar to Cartesian used by projects created before 0.17.0.",
            accent=_COORDINATE_ACCENT, tags=("polar", "legacy"), gpu_kernel="coordinate_polar.wgsl",
            hidden=True, **image_preserve,
        ),
    ]

    for definition in definitions:
        registry.register(definition)
