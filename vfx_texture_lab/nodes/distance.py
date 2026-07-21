from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Mapping

import numpy as np

from .base import EvalContext, ImageArray, NodeDefinition, ParameterSpec
from .image_ops import empty_image, ensure_rgba, grayscale_rgba, luminance, relative_pixels
from .registry import NodeRegistry

_DISTANCE_ACCENT = "#6d87c9"
_INVALID_SEED = np.int32(-1)


def _input(inputs: Mapping[str, ImageArray], context: EvalContext) -> ImageArray:
    return ensure_rgba(inputs.get("Image", empty_image(context)), context)


def _jump_steps(width: int, height: int) -> tuple[int, ...]:
    largest = max(int(width), int(height), 1)
    step = 1
    while step < largest:
        step <<= 1
    step >>= 1
    values: list[int] = []
    while step >= 1:
        values.append(step)
        step >>= 1
    # Two local refinements materially reduce the small approximation errors of
    # ordinary jump flooding around thin diagonals and tightly packed corners.
    values.extend((1, 1))
    return tuple(values)


def _shift_seed_indices(seeds: np.ndarray, dx: int, dy: int, *, wrap: bool) -> np.ndarray:
    shifted = np.roll(seeds, shift=(dy, dx), axis=(0, 1))
    if wrap:
        return shifted
    shifted = shifted.copy()
    if dy > 0:
        shifted[:dy, :] = _INVALID_SEED
    elif dy < 0:
        shifted[dy:, :] = _INVALID_SEED
    if dx > 0:
        shifted[:, :dx] = _INVALID_SEED
    elif dx < 0:
        shifted[:, dx:] = _INVALID_SEED
    return shifted


def _nearest_feature_distance(features: np.ndarray, *, wrap: bool) -> np.ndarray:
    """Return a GPU-matching jump-flood distance to the nearest true pixel.

    The seed is stored as one flat signed integer, keeping the CPU reference
    path substantially lighter than four full coordinate planes. The same jump
    sequence and neighbour order are used by the WGSL implementation.
    """
    features = np.asarray(features, dtype=bool)
    height, width = features.shape
    y, x = np.mgrid[0:height, 0:width]
    flat = (y * width + x).astype(np.int32, copy=False)
    seeds = np.where(features, flat, _INVALID_SEED).astype(np.int32, copy=False)
    pixel_x = x.astype(np.int32, copy=False)
    pixel_y = y.astype(np.int32, copy=False)

    def distance_squared(candidate: np.ndarray) -> np.ndarray:
        valid = candidate >= 0
        safe = np.where(valid, candidate, 0)
        candidate_x = safe % width
        candidate_y = safe // width
        delta_x = np.abs(candidate_x - pixel_x)
        delta_y = np.abs(candidate_y - pixel_y)
        if wrap:
            delta_x = np.minimum(delta_x, width - delta_x)
            delta_y = np.minimum(delta_y, height - delta_y)
        result = delta_x.astype(np.float32) ** 2 + delta_y.astype(np.float32) ** 2
        return np.where(valid, result, np.inf).astype(np.float32, copy=False)

    for step in _jump_steps(width, height):
        best = seeds
        best_distance = distance_squared(best)
        for offset_y, offset_x in (
            (-step, -step), (-step, 0), (-step, step),
            (0, -step),                    (0, step),
            (step, -step),  (step, 0),  (step, step),
        ):
            candidate = _shift_seed_indices(seeds, offset_x, offset_y, wrap=wrap)
            candidate_distance = distance_squared(candidate)
            replace_mask = candidate_distance < best_distance
            if np.any(replace_mask):
                best = np.where(replace_mask, candidate, best)
                best_distance = np.where(replace_mask, candidate_distance, best_distance)
        seeds = best.astype(np.int32, copy=False)

    return np.sqrt(distance_squared(seeds)).astype(np.float32, copy=False)


def signed_distance_field(
    source: ImageArray,
    *,
    threshold: float,
    input_invert: bool,
    seamless: bool,
    fallback_distance: float,
) -> np.ndarray:
    values = luminance(np.asarray(source, dtype=np.float32))
    inside = values >= float(threshold)
    if input_invert:
        inside = ~inside
    distance_to_inside = _nearest_feature_distance(inside, wrap=seamless)
    distance_to_outside = _nearest_feature_distance(~inside, wrap=seamless)
    fallback = max(float(fallback_distance), 1.0) + 0.5
    distance_to_inside = np.where(np.isfinite(distance_to_inside), distance_to_inside, fallback)
    distance_to_outside = np.where(np.isfinite(distance_to_outside), distance_to_outside, fallback)
    # Pixel-centre distance is half a pixel larger than the visible binary edge.
    inside_distance = np.maximum(distance_to_outside - 0.5, 0.0)
    outside_distance = np.maximum(distance_to_inside - 0.5, 0.0)
    return np.where(inside, inside_distance, -outside_distance).astype(np.float32, copy=False)


def _smooth_profile(value: np.ndarray, amount: float) -> np.ndarray:
    amount = min(max(float(amount), 0.0), 1.0)
    if amount <= 0.0:
        return value
    smooth = value * value * (3.0 - 2.0 * value)
    return value * (1.0 - amount) + smooth * amount


def _distance_profile(signed: np.ndarray, params: Mapping[str, Any]) -> np.ndarray:
    limit = max(float(params.get("distance", 32.0)), 1.0e-5)
    shifted = signed + float(params.get("edge_offset", 0.0))
    mode = str(params.get("mode", "Inside"))
    exponent = max(float(params.get("curve", 1.0)), 1.0e-4)
    if mode == "Outside":
        value = np.clip(-shifted / limit, 0.0, 1.0)
        value = np.power(value, exponent)
    elif mode == "Signed":
        normalised = np.clip(shifted / limit, -1.0, 1.0)
        shaped = np.sign(normalised) * np.power(np.abs(normalised), exponent)
        value = shaped * 0.5 + 0.5
    elif mode == "Absolute":
        value = np.power(np.clip(np.abs(shifted) / limit, 0.0, 1.0), exponent)
    else:
        value = np.power(np.clip(shifted / limit, 0.0, 1.0), exponent)
    value = _smooth_profile(value, float(params.get("smoothness", 0.0)))
    if bool(params.get("invert", False)):
        value = 1.0 - value
    return np.clip(value, 0.0, 1.0).astype(np.float32, copy=False)


def _bevel_curve(value: np.ndarray, profile: str) -> np.ndarray:
    value = np.clip(value, 0.0, 1.0)
    if profile == "Smooth":
        return value * value * (3.0 - 2.0 * value)
    if profile == "Rounded":
        return np.sqrt(np.clip(1.0 - (1.0 - value) ** 2, 0.0, 1.0))
    if profile == "Concave":
        return value * value
    if profile == "Convex":
        return 1.0 - (1.0 - value) ** 2
    return value


def _bevel_profile(signed: np.ndarray, params: Mapping[str, Any]) -> np.ndarray:
    width = max(float(params.get("width", 16.0)), 1.0e-5)
    shifted = signed + float(params.get("edge_offset", 0.0))
    direction = str(params.get("direction", "Inner"))
    if direction == "Outer":
        factor = np.clip(1.0 + shifted / width, 0.0, 1.0)
    elif direction == "Centered":
        factor = np.clip(0.5 + shifted / width, 0.0, 1.0)
    elif direction == "Edge Ridge":
        factor = np.clip(1.0 - np.abs(shifted) / width, 0.0, 1.0)
    else:
        factor = np.clip(shifted / width, 0.0, 1.0)
    factor = _bevel_curve(factor, str(params.get("profile", "Rounded")))
    factor = _smooth_profile(factor, float(params.get("smoothness", 0.0)))
    background = float(params.get("background", 0.0))
    height = float(params.get("height", 1.0))
    value = background + factor * (height - background)
    if bool(params.get("invert", False)):
        value = 1.0 - value
    if bool(params.get("clamp", True)):
        value = np.clip(value, 0.0, 1.0)
    return value.astype(np.float32, copy=False)


def _signed_for_node(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> np.ndarray:
    maximum = max(float(params.get("distance", params.get("width", 32.0))), 1.0)
    maximum += abs(float(params.get("edge_offset", 0.0)))
    return signed_distance_field(
        _input(inputs, context),
        threshold=float(params.get("threshold", 0.5)),
        input_invert=bool(params.get("input_invert", False)),
        seamless=str(params.get("boundary", "Seamless / Wrap")) == "Seamless / Wrap",
        fallback_distance=maximum,
    )




def _smoothstep_edges(edge0: float | np.ndarray, edge1: float | np.ndarray, value: np.ndarray) -> np.ndarray:
    denominator = np.maximum(np.asarray(edge1, dtype=np.float32) - np.asarray(edge0, dtype=np.float32), 1.0e-6)
    t = np.clip((value - edge0) / denominator, 0.0, 1.0)
    return (t * t * (3.0 - 2.0 * t)).astype(np.float32, copy=False)


def _mask_from_signed(signed: np.ndarray, amount: float, softness: float) -> np.ndarray:
    softness = max(float(softness), 0.0)
    shifted = signed + float(amount)
    if softness <= 1.0e-5:
        return (shifted >= 0.0).astype(np.float32)
    value = np.clip(shifted / softness + 0.5, 0.0, 1.0)
    value = value * value * (3.0 - 2.0 * value)
    return value.astype(np.float32, copy=False)


def _signed_from_binary(binary: np.ndarray, params: Mapping[str, Any], context: EvalContext, amount_hint: float) -> np.ndarray:
    image = grayscale_rgba(binary.astype(np.float32, copy=False))
    return signed_distance_field(
        image,
        threshold=0.5,
        input_invert=False,
        seamless=str(params.get("boundary", "Seamless / Wrap")) == "Seamless / Wrap",
        fallback_distance=max(float(amount_hint), 1.0),
    )


def _scaled_spatial_params(params: Mapping[str, Any], context: EvalContext, *names: str) -> dict[str, Any]:
    resolved = dict(params)
    for name in names:
        if name in resolved:
            resolved[name] = relative_pixels(float(resolved[name]), context)
    return resolved


def eval_expand_shrink(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    resolved = _scaled_spatial_params(params, context, "amount", "softness")
    amount = max(float(resolved.get("amount", relative_pixels(8.0, context))), 0.0)
    softness = max(float(resolved.get("softness", 0.0)), 0.0)
    operation = str(resolved.get("operation", "Expand"))
    signed = _signed_for_node(inputs, resolved, context)
    if operation == "Expand":
        value = _mask_from_signed(signed, amount, softness)
    elif operation == "Shrink":
        value = _mask_from_signed(signed, -amount, softness)
    elif operation == "Open":
        eroded = signed >= amount
        reopened = _signed_from_binary(eroded, resolved, context, amount + relative_pixels(2.0, context))
        value = _mask_from_signed(reopened, amount, softness)
    else:  # Close
        dilated = signed >= -amount
        reclosed = _signed_from_binary(dilated, resolved, context, amount + relative_pixels(2.0, context))
        value = _mask_from_signed(reclosed, -amount, softness)
    if bool(resolved.get("invert", False)):
        value = 1.0 - value
    return grayscale_rgba(np.clip(value, 0.0, 1.0).astype(np.float32, copy=False))


def eval_outline(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    resolved = _scaled_spatial_params(params, context, "width", "edge_offset", "softness")
    width = max(float(resolved.get("width", relative_pixels(8.0, context))), 1.0e-5)
    offset = float(resolved.get("edge_offset", 0.0))
    softness = max(float(resolved.get("softness", relative_pixels(0.5, context))), 1.0e-5)
    direction = str(resolved.get("direction", "Centered"))
    signed = _signed_for_node(inputs, resolved, context) + offset
    if direction == "Inner":
        near_edge = _smoothstep_edges(-softness, softness, signed)
        beyond_width = _smoothstep_edges(width - softness, width + softness, signed)
        value = near_edge * (1.0 - beyond_width)
    elif direction == "Outer":
        outside = -signed
        near_edge = _smoothstep_edges(-softness, softness, outside)
        beyond_width = _smoothstep_edges(width - softness, width + softness, outside)
        value = near_edge * (1.0 - beyond_width)
    else:
        half = width * 0.5
        value = 1.0 - _smoothstep_edges(half - softness, half + softness, np.abs(signed))
    if bool(resolved.get("invert", False)):
        value = 1.0 - value
    return grayscale_rgba(np.clip(value, 0.0, 1.0).astype(np.float32, copy=False))


def eval_distance(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    resolved = _scaled_spatial_params(params, context, "distance", "edge_offset")
    return grayscale_rgba(_distance_profile(_signed_for_node(inputs, resolved, context), resolved))


def eval_bevel(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    resolved = _scaled_spatial_params(params, context, "width", "edge_offset")
    return grayscale_rgba(_bevel_profile(_signed_for_node(inputs, resolved, context), resolved))


def _shift_scalar(values: np.ndarray, dx: int, dy: int, *, wrap: bool, fill: float) -> np.ndarray:
    # The output pixel samples the source at coord + (dx, dy), matching the
    # WGSL textureLoad path. np.roll therefore uses the opposite shift.
    shifted = np.roll(values, shift=(-dy, -dx), axis=(0, 1))
    if wrap:
        return shifted
    shifted = shifted.copy()
    if dy > 0:
        shifted[-dy:, :] = fill
    elif dy < 0:
        shifted[:-dy, :] = fill
    if dx > 0:
        shifted[:, -dx:] = fill
    elif dx < 0:
        shifted[:, :-dx] = fill
    return shifted


def _direction_offset(degrees: float) -> tuple[int, int]:
    radians = math.radians(float(degrees))
    dx = int(round(math.cos(radians)))
    dy = int(round(-math.sin(radians)))
    if dx == 0 and dy == 0:
        dx = 1
    return dx, dy


def _aperture_offsets(shape: str, vertices: int, direction: float, corner_angle: float, antialiased: bool) -> tuple[tuple[int, int], ...]:
    """Return the compact one-pixel kernels used by directional apertures."""
    offsets: set[tuple[int, int]] = {(0, 0)}
    if shape == "Line":
        dx, dy = _direction_offset(direction)
        offsets.update(((dx, dy), (-dx, -dy)))
    elif shape == "Corner":
        half = float(corner_angle) * 0.5
        first = _direction_offset(direction - half)
        second = _direction_offset(direction + half)
        offsets.update((first, second))
        combined = (max(-1, min(1, first[0] + second[0])), max(-1, min(1, first[1] + second[1])))
        if combined != (0, 0):
            offsets.add(combined)
    else:  # Asterisk
        count = max(int(vertices), 3)
        for index in range(count):
            offsets.add(_direction_offset(direction + index * 360.0 / count))
    return tuple(sorted(offsets))


def _aperture_area_offsets(
    shape: str,
    radius: int,
    vertices: int,
    direction: float,
    antialiased: bool,
) -> tuple[tuple[int, int], ...]:
    """Build a real filled disk or regular-polygon structuring element.

    The old iterative 3x3 neighbourhood used all diagonal samples every pass,
    so both Disk and Polygon converged to the same Chebyshev square. Small
    filled kernels are composited in chunks instead; Minkowski addition keeps
    their intended silhouette while avoiding one enormous radius scan.
    """
    radius = max(int(radius), 1)
    tolerance = 0.5 if antialiased else 0.05
    offsets: list[tuple[int, int]] = []
    if shape == "Disk":
        limit_squared = (float(radius) + tolerance) ** 2
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if float(dx * dx + dy * dy) <= limit_squared:
                    offsets.append((dx, dy))
        return tuple(offsets)

    count = max(min(int(vertices), 16), 3)
    circumradius = float(radius)
    apothem = circumradius * math.cos(math.pi / float(count)) + tolerance
    base_angle = math.radians(float(direction))
    edge_normals = (
        (
            math.cos(base_angle + (index + 0.5) * math.tau / float(count)),
            -math.sin(base_angle + (index + 0.5) * math.tau / float(count)),
        )
        for index in range(count)
    )
    normals = tuple(edge_normals)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if all(float(dx) * nx + float(dy) * ny <= apothem for nx, ny in normals):
                offsets.append((dx, dy))
    if (0, 0) not in offsets:
        offsets.append((0, 0))
    return tuple(offsets)


def _apply_aperture_offsets(
    current: np.ndarray,
    offsets: tuple[tuple[int, int], ...],
    *,
    erosion: bool,
    wrap: bool,
) -> np.ndarray:
    fill = 1.0 if erosion else 0.0
    candidates = [_shift_scalar(current, dx, dy, wrap=wrap, fill=fill) for dx, dy in offsets]
    if erosion:
        return np.minimum.reduce(candidates).astype(np.float32, copy=False)
    return np.maximum.reduce(candidates).astype(np.float32, copy=False)


def eval_aperture(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    source = luminance(_input(inputs, context)).astype(np.float32, copy=False)
    mode = str(params.get("mode", "Dilation"))
    shape = str(params.get("shape", "Disk"))
    size = max(int(round(relative_pixels(float(params.get("size", 8.0)), context))), 0)
    vertices = max(int(params.get("vertices", 6)), 3)
    direction = float(params.get("direction", 0.0))
    corner_angle = float(params.get("corner_angle", 90.0))
    antialiased = bool(params.get("antialiased", True))
    wrap = str(params.get("boundary", "Seamless / Wrap")) == "Seamless / Wrap"
    strength = min(max(float(params.get("strength", 1.0)), 0.0), 1.0)
    if size <= 0 or strength <= 0.0:
        return grayscale_rgba(source)

    erosion = mode == "Erosion"
    current = source.copy()
    if shape in {"Disk", "Polygon"}:
        remaining = size
        while remaining > 0:
            radius = min(4, remaining)
            offsets = _aperture_area_offsets(shape, radius, vertices, direction, antialiased)
            current = _apply_aperture_offsets(current, offsets, erosion=erosion, wrap=wrap)
            remaining -= radius
    else:
        offsets = _aperture_offsets(shape, vertices, direction, corner_angle, antialiased)
        for _pass in range(size):
            current = _apply_aperture_offsets(current, offsets, erosion=erosion, wrap=wrap)

    result = source * (1.0 - strength) + current * strength
    return grayscale_rgba(np.clip(result, 0.0, 1.0).astype(np.float32, copy=False))


def register_distance_nodes(registry: NodeRegistry) -> None:
    f = ParameterSpec
    definitions = (
        NodeDefinition(
            "filter.distance",
            "Distance",
            "Filters",
            eval_distance,
            inputs=("Image",),
            parameters=(
                f("mode", "Mode", "enum", "Inside", options=("Inside", "Outside", "Signed", "Absolute"), group="Distance", group_order=10),
                f("distance", "Maximum Distance", "float", 32.0, 0.5, 8192.0, 0.5, animatable=True, group="Distance", group_order=10, slider_maximum=256.0, fine_step=0.5, coarse_step=5.0, unit="rpx"),
                f("edge_offset", "Edge Offset", "float", 0.0, -8192.0, 8192.0, 0.5, animatable=True, group="Distance", group_order=10, slider_minimum=-128.0, slider_maximum=128.0, fine_step=0.5, coarse_step=5.0, unit="rpx", description="Shift the measured edge before generating the distance profile. Positive values expand the interior."),
                f("curve", "Curve", "float", 1.0, 0.05, 8.0, 0.01, animatable=True, group="Profile", group_order=20, slider_maximum=4.0),
                f("smoothness", "Profile Smoothness", "float", 0.0, 0.0, 1.0, 0.01, animatable=True, group="Profile", group_order=20),
                f("threshold", "Input Threshold", "float", 0.5, 0.0, 1.0, 0.01, group="Input", group_order=30),
                f("input_invert", "Invert Input", "bool", False, group="Input", group_order=30),
                f("boundary", "Boundary", "enum", "Seamless / Wrap", options=("Seamless / Wrap", "Clamp"), group="Input", group_order=30),
                f("invert", "Invert Output", "bool", False, group="Output", group_order=40),
            ),
            description="Measure seamless Euclidean distance from a thresholded mask edge. Spatial values use resolution-independent relative pixels measured at 512 pixels.",
            accent=_DISTANCE_ACCENT,
            tags=("distance", "sdf", "signed distance", "expand", "shrink", "edge", "mask"),
            output_format="r16f",
            gpu_kernel="distance.wgsl",
            input_kinds=(("Image", "grayscale"),),
            output_kinds=(("Image", "grayscale"),),
            default_image_kind="grayscale",
        ),
        NodeDefinition(
            "filter.bevel",
            "Bevel",
            "Filters",
            eval_bevel,
            inputs=("Image",),
            parameters=(
                f("direction", "Direction", "enum", "Inner", options=("Inner", "Outer", "Centered", "Edge Ridge"), group="Bevel", group_order=10),
                f("profile", "Profile", "enum", "Rounded", options=("Linear", "Smooth", "Rounded", "Concave", "Convex"), group="Bevel", group_order=10),
                f("width", "Width", "float", 16.0, 0.5, 8192.0, 0.5, animatable=True, group="Bevel", group_order=10, slider_maximum=256.0, fine_step=0.5, coarse_step=5.0, unit="rpx"),
                f("edge_offset", "Edge Offset", "float", 0.0, -8192.0, 8192.0, 0.5, animatable=True, group="Bevel", group_order=10, slider_minimum=-128.0, slider_maximum=128.0, fine_step=0.5, coarse_step=5.0, unit="rpx"),
                f("height", "Height", "float", 1.0, -4.0, 4.0, 0.01, animatable=True, group="Height", group_order=20, slider_minimum=0.0, slider_maximum=1.0),
                f("background", "Background", "float", 0.0, -4.0, 4.0, 0.01, animatable=True, group="Height", group_order=20, slider_minimum=0.0, slider_maximum=1.0),
                f("smoothness", "Profile Smoothness", "float", 0.0, 0.0, 1.0, 0.01, animatable=True, group="Height", group_order=20),
                f("threshold", "Input Threshold", "float", 0.5, 0.0, 1.0, 0.01, group="Input", group_order=30),
                f("input_invert", "Invert Input", "bool", False, group="Input", group_order=30),
                f("boundary", "Boundary", "enum", "Seamless / Wrap", options=("Seamless / Wrap", "Clamp"), group="Input", group_order=30),
                f("invert", "Invert Output", "bool", False, group="Output", group_order=40),
                f("clamp", "Clamp Output", "bool", True, group="Output", group_order=40),
            ),
            description="Turn a flat grayscale mask into a height bevel. Width and offset use resolution-independent relative pixels measured at 512 pixels.",
            accent=_DISTANCE_ACCENT,
            tags=("bevel", "height", "edge", "rounded", "chamfer", "mask"),
            output_format="r16f",
            gpu_kernel="bevel.wgsl",
            input_kinds=(("Image", "grayscale"),),
            output_kinds=(("Image", "grayscale"),),
            default_image_kind="grayscale",
        ),
        NodeDefinition(
            "filter.expand_shrink",
            "Expand / Shrink",
            "Filters",
            eval_expand_shrink,
            inputs=("Image",),
            parameters=(
                f("operation", "Operation", "enum", "Expand", options=("Expand", "Shrink", "Open", "Close"), group="Morphology", group_order=10),
                f("amount", "Amount", "float", 8.0, 0.0, 8192.0, 0.5, animatable=True, group="Morphology", group_order=10, slider_maximum=256.0, fine_step=0.5, coarse_step=5.0, unit="rpx"),
                f("softness", "Softness", "float", 0.0, 0.0, 64.0, 0.1, animatable=True, group="Morphology", group_order=10, slider_maximum=8.0, fine_step=0.1, coarse_step=1.0, unit="rpx"),
                f("threshold", "Input Threshold", "float", 0.5, 0.0, 1.0, 0.01, group="Input", group_order=30),
                f("input_invert", "Invert Input", "bool", False, group="Input", group_order=30),
                f("boundary", "Boundary", "enum", "Seamless / Wrap", options=("Seamless / Wrap", "Clamp"), group="Input", group_order=30),
                f("invert", "Invert Output", "bool", False, group="Output", group_order=40),
            ),
            description="Expand, shrink, open or close a mask using resolution-independent relative-pixel morphology.",
            accent=_DISTANCE_ACCENT,
            tags=("expand", "shrink", "dilate", "erode", "open", "close", "mask", "morphology"),
            output_format="r16f",
            gpu_kernel="expand_shrink.wgsl",
            input_kinds=(("Image", "grayscale"),),
            output_kinds=(("Image", "grayscale"),),
            default_image_kind="grayscale",
        ),
        NodeDefinition(
            "filter.outline",
            "Outline",
            "Filters",
            eval_outline,
            inputs=("Image",),
            parameters=(
                f("direction", "Direction", "enum", "Centered", options=("Inner", "Outer", "Centered"), group="Outline", group_order=10),
                f("width", "Width", "float", 8.0, 0.5, 8192.0, 0.5, animatable=True, group="Outline", group_order=10, slider_maximum=256.0, fine_step=0.5, coarse_step=5.0, unit="rpx"),
                f("edge_offset", "Edge Offset", "float", 0.0, -8192.0, 8192.0, 0.5, animatable=True, group="Outline", group_order=10, slider_minimum=-128.0, slider_maximum=128.0, fine_step=0.5, coarse_step=5.0, unit="rpx"),
                f("softness", "Softness", "float", 0.5, 0.0, 64.0, 0.1, animatable=True, group="Outline", group_order=10, slider_maximum=8.0, fine_step=0.1, coarse_step=1.0, unit="rpx"),
                f("threshold", "Input Threshold", "float", 0.5, 0.0, 1.0, 0.01, group="Input", group_order=30),
                f("input_invert", "Invert Input", "bool", False, group="Input", group_order=30),
                f("boundary", "Boundary", "enum", "Seamless / Wrap", options=("Seamless / Wrap", "Clamp"), group="Input", group_order=30),
                f("invert", "Invert Output", "bool", False, group="Output", group_order=40),
            ),
            description="Create an inner, outer or centred seamless outline whose width remains proportional at every resolution.",
            accent=_DISTANCE_ACCENT,
            tags=("outline", "stroke", "border", "edge", "mask"),
            output_format="r16f",
            gpu_kernel="outline.wgsl",
            input_kinds=(("Image", "grayscale"),),
            output_kinds=(("Image", "grayscale"),),
            default_image_kind="grayscale",
        ),
        NodeDefinition(
            "filter.aperture",
            "Aperture",
            "Filters",
            eval_aperture,
            inputs=("Image",),
            parameters=(
                f("mode", "Mode", "enum", "Dilation", options=("Dilation", "Erosion"), group="Aperture", group_order=10),
                f("size", "Size", "int", 8, 0, 256, 1, animatable=True, group="Aperture", group_order=10, slider_maximum=64, fine_step=1, coarse_step=4, unit="rpx"),
                f("shape", "Shape", "enum", "Disk", options=("Disk", "Polygon", "Asterisk", "Line", "Corner"), group="Aperture", group_order=10),
                f("vertices", "Vertices Count", "int", 6, 3, 16, 1, animatable=True, group="Shape", group_order=20, visible_when=(("shape", ("Polygon", "Asterisk")),)),
                f("corner_angle", "Corner Angle", "float", 90.0, 1.0, 179.0, 1.0, animatable=True, group="Shape", group_order=20, unit="degrees", fine_step=1.0, coarse_step=5.0, visible_when=(("shape", ("Corner",)),)),
                f("direction", "Direction", "float", 0.0, -180.0, 180.0, 1.0, animatable=True, group="Shape", group_order=20, editor="angle", unit="degrees", fine_step=1.0, coarse_step=5.0, visible_when=(("shape", ("Polygon", "Asterisk", "Line", "Corner")),)),
                f("antialiased", "Antialiased", "bool", True, group="Shape", group_order=20),
                f("strength", "Strength", "float", 1.0, 0.0, 1.0, 0.01, animatable=True, group="Output", group_order=30),
                f("boundary", "Boundary", "enum", "Seamless / Wrap", options=("Seamless / Wrap", "Clamp"), group="Output", group_order=30),
            ),
            description="Reshape grayscale heightfields through resolution-independent dilation or erosion using disk, polygon, asterisk, line or corner apertures.",
            accent=_DISTANCE_ACCENT,
            tags=("aperture", "dilate", "erode", "height", "terrain", "ridge", "bulge", "morphology"),
            output_format="r16f",
            gpu_kernel="aperture_step.wgsl",
            input_kinds=(("Image", "grayscale"),),
            output_kinds=(("Image", "grayscale"),),
            default_image_kind="grayscale",
        ),
    )
    for definition in definitions:
        registry.register(replace(definition))
