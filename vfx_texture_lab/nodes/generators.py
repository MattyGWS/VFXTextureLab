from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Mapping

import numpy as np

from .base import EvalContext, ImageArray, NodeDefinition, ParameterSpec
from .image_ops import grayscale_rgba, parse_hex_color, srgb_to_linear
from .registry import NodeRegistry


def _uv(context: EvalContext) -> tuple[np.ndarray, np.ndarray]:
    y, x = np.mgrid[0 : context.height, 0 : context.width]
    return (
        (x.astype(np.float32) + 0.5) / context.width,
        (y.astype(np.float32) + 0.5) / context.height,
    )


def _wrapped_delta(coordinate: np.ndarray, centre: float) -> np.ndarray:
    """Shortest signed distance on a repeating 0..1 axis."""
    return np.mod(coordinate - centre + 0.5, 1.0) - 0.5


def eval_constant(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    value = float(params["value"])
    return grayscale_rgba(np.full((context.height, context.width), value, dtype=np.float32))


def eval_color(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    color = parse_hex_color(str(params["color"]))
    # Colour parameters are authored through Qt's display-sRGB picker, while
    # colour image data inside the graph is stored in linear light. Convert RGB
    # exactly once here and leave alpha as linear coverage.
    color[:3] = srgb_to_linear(color[:3])
    return np.broadcast_to(color, (context.height, context.width, 4)).copy()


def _linear_gradient_coordinate(
    params: Mapping[str, Any], context: EvalContext
) -> np.ndarray:
    u, v = _uv(context)
    angle = math.radians(float(params["angle"]))
    direction_x = math.cos(angle)
    direction_y = math.sin(angle)
    centered_u = u - 0.5
    centered_v = v - 0.5
    value = centered_u * direction_x + centered_v * direction_y + 0.5 + float(params["offset"])
    if bool(params["repeat"]):
        value = np.mod(value, 1.0)
    return np.clip(value, 0.0, 1.0).astype(np.float32)


def eval_linear_gradient(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    return grayscale_rgba(_linear_gradient_coordinate(params, context))


def eval_linear_gradient_2(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    """Smooth periodic black-white-black dome profile."""
    coordinate = _linear_gradient_coordinate(params, context)
    value = np.float32(0.5) - np.float32(0.5) * np.cos(coordinate * np.float32(math.tau))
    return grayscale_rgba(np.clip(value, 0.0, 1.0))


def eval_linear_gradient_3(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    """Linear black-white-black profile with a deliberately sharp centre ridge."""
    coordinate = _linear_gradient_coordinate(params, context)
    value = np.float32(1.0) - np.abs(coordinate * np.float32(2.0) - np.float32(1.0))
    return grayscale_rgba(np.clip(value, 0.0, 1.0))


def eval_radial_gradient(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    u, v = _uv(context)
    aspect = context.width / max(context.height, 1)
    dx = _wrapped_delta(u, float(params["center_x"])) * aspect
    dy = _wrapped_delta(v, float(params["center_y"]))
    radius = max(float(params["radius"]), 1e-4)
    value = 1.0 - np.sqrt(dx * dx + dy * dy) / radius
    value = np.clip(value, 0.0, 1.0)
    power = max(float(params["falloff"]), 0.01)
    value = np.power(value, power)
    return grayscale_rgba(value)


def _shape_local_coordinates(params: Mapping[str, Any], context: EvalContext) -> tuple[np.ndarray, np.ndarray]:
    u, v = _uv(context)
    tile_x = max(float(params.get("tile_x", 1.0)), 1.0e-4)
    tile_y = max(float(params.get("tile_y", 1.0)), 1.0e-4)
    centre_x = float(params.get("center_x", 0.5))
    centre_y = float(params.get("center_y", 0.5))
    local_x = np.mod(u * tile_x - centre_x + 0.5, 1.0) - 0.5
    local_y = np.mod(v * tile_y - centre_y + 0.5, 1.0) - 0.5
    if bool(params.get("non_square_compensation", True)):
        aspect = (context.width / max(context.height, 1)) * (tile_y / max(tile_x, 1.0e-6))
        local_x = local_x * aspect
    angle = math.radians(float(params.get("rotation", 0.0)))
    cos_angle = math.cos(angle)
    sin_angle = math.sin(angle)
    rotated_x = local_x * cos_angle + local_y * sin_angle
    rotated_y = -local_x * sin_angle + local_y * cos_angle
    scale = max(float(params.get("scale", 1.0)), 1.0e-4)
    size_x = max(float(params.get("size_x", 1.0)) * scale * 0.5, 1.0e-4)
    size_y = max(float(params.get("size_y", 1.0)) * scale * 0.5, 1.0e-4)
    return rotated_x / size_x, rotated_y / size_y




def geometric_raster_feather(params: Mapping[str, Any], context: EvalContext) -> float:
    """Return the authored/coverage feather for analytic shape rasterisation.

    Edge Softness is an artistic width in local shape space. Antialiased mode
    adds only the approximate footprint of one output pixel, keeping a
    geometrically hard edge while storing fractional boundary coverage. Missing
    rasterisation metadata belongs to legacy 0.43.3 graphs and remains binary.
    """
    authored = max(float(params.get("edge_softness", 0.0)), 0.0)
    if str(params.get("rasterization", "Pixel Exact")) != "Antialiased":
        return authored
    tile_x = max(float(params.get("tile_x", 1.0)), 1.0e-4)
    tile_y = max(float(params.get("tile_y", 1.0)), 1.0e-4)
    scale = max(float(params.get("scale", 1.0)), 1.0e-4)
    half_x = max(float(params.get("size_x", 1.0)) * scale * 0.5, 1.0e-4)
    half_y = max(float(params.get("size_y", 1.0)) * scale * 0.5, 1.0e-4)
    aspect = 1.0
    if bool(params.get("non_square_compensation", params.get("non_square_expansion", True))):
        aspect = (context.width / max(context.height, 1)) * (tile_y / max(tile_x, 1.0e-6))
    footprint_x = tile_x * abs(aspect) / max(context.width * half_x, 1.0e-6)
    footprint_y = tile_y / max(context.height * half_y, 1.0e-6)
    return max(authored, max(footprint_x, footprint_y))


def _shape_profile_from_metric(metric: np.ndarray, mode: str, feather: float, profile_width: float) -> np.ndarray:
    authored_feather = float(feather)
    profile_width = max(float(profile_width), 1.0e-5)
    if authored_feather <= 0.0:
        # Zero softness is an exact raster mask, not an almost-zero smoothstep.
        # This keeps primitive edges pixel-sharp at every authored resolution.
        coverage = (metric >= 0.0).astype(np.float32)
        if mode == "Outline":
            return (np.abs(metric) <= profile_width).astype(np.float32)
        if mode == "Linear Bevel":
            return (np.clip(metric / profile_width, 0.0, 1.0) * coverage).astype(np.float32)
        if mode == "Rounded Bevel":
            bevel = np.clip(metric / profile_width, 0.0, 1.0)
            return ((1.0 - (1.0 - bevel) * (1.0 - bevel)) * coverage).astype(np.float32)
        return coverage

    feather = max(authored_feather, 1.0e-5)
    coverage = np.clip(metric / feather + 0.5, 0.0, 1.0)
    if mode == "Outline":
        return np.clip((profile_width - np.abs(metric)) / feather + 0.5, 0.0, 1.0).astype(np.float32)
    if mode == "Linear Bevel":
        return (np.clip(metric / profile_width, 0.0, 1.0) * coverage).astype(np.float32)
    if mode == "Rounded Bevel":
        bevel = np.clip(metric / profile_width, 0.0, 1.0)
        return ((1.0 - (1.0 - bevel) * (1.0 - bevel)) * coverage).astype(np.float32)
    return coverage.astype(np.float32)


def _shape_metric_union(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.maximum(a, b)


def _shape_metric_rectangle(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return 1.0 - np.maximum(np.abs(x), np.abs(y))


def _shape_metric_rounded_rectangle(x: np.ndarray, y: np.ndarray, radius: float) -> np.ndarray:
    radius = min(max(float(radius), 0.0), 0.95)
    qx = np.abs(x) - (1.0 - radius)
    qy = np.abs(y) - (1.0 - radius)
    outside = np.sqrt(np.maximum(qx, 0.0) ** 2 + np.maximum(qy, 0.0) ** 2)
    inside = np.minimum(np.maximum(qx, qy), 0.0)
    return -(outside + inside - radius)


def _shape_metric_disc(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return 1.0 - np.sqrt(x * x + y * y)


def _shape_metric_ring(x: np.ndarray, y: np.ndarray, thickness: float) -> np.ndarray:
    thickness = min(max(float(thickness), 0.01), 0.99)
    radius = np.sqrt(x * x + y * y)
    return thickness - np.abs(radius - (1.0 - thickness))


def _shape_metric_capsule(x: np.ndarray, y: np.ndarray, length: float) -> np.ndarray:
    length = min(max(float(length), 0.0), 1.6)
    half_segment = 0.35 + length * 0.45
    radius = 0.35
    qx = np.maximum(np.abs(x) - half_segment, 0.0)
    return radius - np.sqrt(qx * qx + y * y)


def _shape_metric_triangle(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.minimum(1.0 - y, y + 1.0 - 2.0 * np.abs(x))


def _shape_metric_diamond(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return 1.0 - (np.abs(x) + np.abs(y))


def _shape_metric_hexagon(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    absolute_x = np.abs(x)
    absolute_y = np.abs(y)
    return 1.0 - np.maximum(absolute_y, absolute_x * 0.8660254 + absolute_y * 0.5)


def _shape_metric_cross(x: np.ndarray, y: np.ndarray, bar_thickness: float) -> np.ndarray:
    bar = min(max(float(bar_thickness), 0.05), 1.5)
    vertical = np.minimum(1.0 - np.abs(y), bar - np.abs(x))
    horizontal = np.minimum(1.0 - np.abs(x), bar - np.abs(y))
    return _shape_metric_union(vertical, horizontal)


def _shape_metric_x(x: np.ndarray, y: np.ndarray, bar_thickness: float) -> np.ndarray:
    c = 0.70710678
    rx = x * c + y * c
    ry = -x * c + y * c
    return _shape_metric_cross(rx, ry, bar_thickness)


def _shape_metric_crescent(x: np.ndarray, y: np.ndarray, cutout_size: float, cutout_offset_x: float, cutout_offset_y: float) -> np.ndarray:
    outer = np.sqrt(x * x + y * y) - 1.0
    inner_radius = min(max(float(cutout_size), 0.05), 1.5)
    inner = np.sqrt((x - float(cutout_offset_x)) ** 2 + (y - float(cutout_offset_y)) ** 2) - inner_radius
    return -np.maximum(outer, -inner)


def _shape_native_profile(shape: str, x: np.ndarray, y: np.ndarray, params: Mapping[str, Any]) -> np.ndarray | None:
    radius = np.sqrt(x * x + y * y)
    if shape == "Bell":
        return np.where(radius <= 1.0, np.exp(-3.5 * radius * radius), 0.0).astype(np.float32)
    if shape == "Gaussian":
        return np.where(radius <= 1.0, np.exp(-8.0 * radius * radius), 0.0).astype(np.float32)
    if shape == "Pyramid":
        return np.clip(1.0 - np.maximum(np.abs(x), np.abs(y)), 0.0, 1.0).astype(np.float32)
    if shape == "Cone":
        return np.clip(1.0 - radius, 0.0, 1.0).astype(np.float32)
    if shape == "Hemisphere":
        return np.sqrt(np.clip(1.0 - radius * radius, 0.0, 1.0)).astype(np.float32)
    if shape == "Waves":
        frequency = max(float(params.get("wave_frequency", 4.0)), 0.1)
        phase = math.radians(float(params.get("wave_phase", 0.0)))
        balance = min(max(float(params.get("wave_balance", 0.5)), 0.0), 1.0)
        value = 0.5 + 0.5 * np.sin((x + 1.0) * math.pi * frequency + phase)
        return np.clip((value - balance) / max(1.0 - balance, 1.0e-5), 0.0, 1.0).astype(np.float32)
    if shape == "Linear Gradation":
        return np.clip((x + 1.0) * 0.5, 0.0, 1.0).astype(np.float32)
    return None


def eval_shape(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    x, y = _shape_local_coordinates(params, context)
    shape = str(params.get("shape", "Rectangle"))
    native_profile = _shape_native_profile(shape, x, y, params)
    if native_profile is None:
        if shape == "Rounded Rectangle":
            metric = _shape_metric_rounded_rectangle(x, y, float(params.get("corner_radius", 0.25)))
        elif shape == "Disc":
            metric = _shape_metric_disc(x, y)
        elif shape == "Ring":
            metric = _shape_metric_ring(x, y, float(params.get("thickness", 0.2)))
        elif shape == "Capsule":
            metric = _shape_metric_capsule(x, y, float(params.get("capsule_length", 0.5)))
        elif shape == "Triangle":
            metric = _shape_metric_triangle(x, y)
        elif shape == "Diamond":
            metric = _shape_metric_diamond(x, y)
        elif shape == "Hexagon":
            metric = _shape_metric_hexagon(x, y)
        elif shape == "Cross":
            metric = _shape_metric_cross(x, y, float(params.get("bar_thickness", 0.35)))
        elif shape == "X":
            metric = _shape_metric_x(x, y, float(params.get("bar_thickness", 0.25)))
        elif shape == "Crescent":
            metric = _shape_metric_crescent(
                x,
                y,
                float(params.get("cutout_size", 0.8)),
                float(params.get("cutout_offset_x", 0.35)),
                float(params.get("cutout_offset_y", 0.0)),
            )
        else:
            metric = _shape_metric_rectangle(x, y)
        native_profile = _shape_profile_from_metric(
            metric,
            str(params.get("fill_mode", "Solid")),
            geometric_raster_feather(params, context),
            float(params.get("profile_width", 0.18)),
        )
    if bool(params.get("invert", False)):
        native_profile = 1.0 - native_profile
    return grayscale_rgba(np.clip(native_profile, 0.0, 1.0).astype(np.float32, copy=False))


def _polygon_vertices(sides: int, inner_radius: float, alternating_offset: float = 0.0) -> np.ndarray:
    sides = max(int(sides), 3)
    inner_radius = float(inner_radius)
    if inner_radius >= 0.999:
        angles = np.linspace(0.0, math.tau, sides, endpoint=False, dtype=np.float32) + math.pi * 0.5
        radii = np.ones(sides, dtype=np.float32)
    else:
        count = sides * 2
        angles = np.linspace(0.0, math.tau, count, endpoint=False, dtype=np.float32) + math.pi * 0.5
        radii = np.empty(count, dtype=np.float32)
        inner = np.clip(inner_radius + alternating_offset, 0.02, 1.0)
        radii[0::2] = 1.0
        radii[1::2] = inner
    return np.stack((np.cos(angles) * radii, np.sin(angles) * radii), axis=1).astype(np.float32)


def _signed_distance_polygon(x: np.ndarray, y: np.ndarray, vertices: np.ndarray) -> np.ndarray:
    dist2 = np.full(x.shape, np.inf, dtype=np.float32)
    inside = np.zeros(x.shape, dtype=bool)
    count = vertices.shape[0]
    for index in range(count):
        ax, ay = vertices[index - 1]
        bx, by = vertices[index]
        edge_x = bx - ax
        edge_y = by - ay
        denom = edge_x * edge_x + edge_y * edge_y + 1.0e-12
        projection = np.clip(((x - ax) * edge_x + (y - ay) * edge_y) / denom, 0.0, 1.0)
        nearest_x = ax + projection * edge_x
        nearest_y = ay + projection * edge_y
        delta_x = x - nearest_x
        delta_y = y - nearest_y
        dist2 = np.minimum(dist2, delta_x * delta_x + delta_y * delta_y)
        crossing = ((ay > y) != (by > y)) & (x < (edge_x * (y - ay) / (by - ay + 1.0e-12) + ax))
        inside ^= crossing
    distance = np.sqrt(dist2)
    return np.where(inside, -distance, distance).astype(np.float32)


def eval_polygon(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    x, y = _shape_local_coordinates(params, context)
    twist = math.radians(float(params.get("twist", 0.0)))
    if abs(twist) > 1.0e-9:
        radius = np.sqrt(x * x + y * y)
        angles = np.arctan2(y, x) + radius * twist
        x = radius * np.cos(angles)
        y = radius * np.sin(angles)
    distortion = float(params.get("radial_distortion", 0.0))
    if abs(distortion) > 1.0e-9:
        angles = np.arctan2(y, x)
        radius = np.sqrt(x * x + y * y)
        radius = radius / np.maximum(1.0 + distortion * np.cos(angles * max(int(params.get("sides", 6)), 3)), 1.0e-3)
        x = radius * np.cos(angles)
        y = radius * np.sin(angles)
    vertices = _polygon_vertices(
        int(params.get("sides", 6)),
        float(params.get("inner_radius", 1.0)),
        float(params.get("alternating_offset", 0.0)),
    )
    signed_distance = _signed_distance_polygon(x, y, vertices) - float(params.get("roundness", 0.0))
    metric = -signed_distance
    value = _shape_profile_from_metric(
        metric,
        str(params.get("fill_mode", "Solid")),
        geometric_raster_feather(params, context),
        float(params.get("profile_width", 0.18)),
    )
    if bool(params.get("invert", False)):
        value = 1.0 - value
    return grayscale_rgba(np.clip(value, 0.0, 1.0).astype(np.float32, copy=False))


def eval_polygon_burst(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    x, y = _shape_local_coordinates(params, context)
    sides = max(int(params.get("sides", 6)), 3)
    radius = np.sqrt(x * x + y * y)
    angle = np.arctan2(y, x)
    sector = math.tau / float(sides)
    twist = math.radians(float(params.get("twist", 0.0)))
    angle = angle + radius * twist
    angle = np.mod(angle + math.pi, math.tau) - math.pi
    local_angle = np.mod(angle + sector * 0.5, sector) - sector * 0.5
    explode = max(float(params.get("explode", 0.0)), 0.0)
    inner_radius = min(max(float(params.get("inner_radius", 0.0)), 0.0), 0.95)
    gap = min(max(float(params.get("slice_gap", 0.0)), 0.0), 0.98)
    r = radius - explode
    angular_limit = sector * 0.5 * (1.0 - gap)
    angular_metric = 1.0 - np.abs(local_angle) / max(angular_limit, 1.0e-5)
    radial_metric = np.minimum((r - inner_radius) / max(1.0 - inner_radius, 1.0e-5), 1.0 - r)
    metric = np.minimum(angular_metric, radial_metric)
    edge_softness = geometric_raster_feather(params, context)
    if edge_softness <= 0.0:
        mask = (metric >= 0.0).astype(np.float32)
    else:
        mask = np.clip(metric / max(edge_softness, 1.0e-5) + 0.5, 0.0, 1.0)
    mode = str(params.get("fill_mode", "Solid"))
    if mode == "Radial Gradient":
        gradient = np.clip((1.0 - r) / max(1.0 - inner_radius, 1.0e-5), 0.0, 1.0)
        value = mask * gradient
    elif mode == "Angular Gradient":
        gradient = np.clip(1.0 - np.abs(local_angle) / max(sector * 0.5, 1.0e-5), 0.0, 1.0)
        value = mask * gradient
    else:
        value = mask
    if bool(params.get("alternate_value", False)):
        slice_index = np.floor((angle + math.pi) / sector).astype(np.int32)
        value = np.where(slice_index % 2 == 0, value, value * float(params.get("alternate_strength", 0.5)))
    if bool(params.get("invert", False)):
        value = 1.0 - value
    return grayscale_rgba(np.clip(value, 0.0, 1.0).astype(np.float32, copy=False))


def eval_checker(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    u, v = _uv(context)
    scale = max(int(params["scale"]), 1)
    cells = (np.floor(u * scale) + np.floor(v * scale)).astype(np.int32)
    values = np.where(cells % 2 == 0, float(params["value_a"]), float(params["value_b"]))
    return grayscale_rgba(values)


def _tile_hash(indices_x: np.ndarray, indices_y: np.ndarray, seed: int, stream: int) -> np.ndarray:
    """Stable per-cell random values shared conceptually with the WGSL path."""
    with np.errstate(over="ignore"):
        value = (
            indices_x.astype(np.uint32) * np.uint32(0x9E3779B9)
            ^ indices_y.astype(np.uint32) * np.uint32(0x85EBCA6B)
            ^ np.uint32(seed) * np.uint32(0xC2B2AE35)
            ^ np.uint32(stream) * np.uint32(0x27D4EB2D)
        )
        value ^= value >> np.uint32(16)
        value *= np.uint32(0x7FEB352D)
        value ^= value >> np.uint32(15)
        value *= np.uint32(0x846CA68B)
        value ^= value >> np.uint32(16)
    return (value & np.uint32(0x00FFFFFF)).astype(np.float32) / np.float32(16777216.0)


def _sample_grayscale_bilinear(image: ImageArray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    source = np.asarray(image, dtype=np.float32)
    if source.ndim == 3:
        source = source[..., 0]
    height, width = source.shape[:2]
    inside = (u >= 0.0) & (u <= 1.0) & (v >= 0.0) & (v <= 1.0)
    pixel_x = np.clip(u * width - 0.5, 0.0, max(width - 1, 0))
    pixel_y = np.clip(v * height - 0.5, 0.0, max(height - 1, 0))
    x0 = np.floor(pixel_x).astype(np.int32)
    y0 = np.floor(pixel_y).astype(np.int32)
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    fx = pixel_x - x0
    fy = pixel_y - y0
    top = source[y0, x0] * (1.0 - fx) + source[y0, x1] * fx
    bottom = source[y1, x0] * (1.0 - fx) + source[y1, x1] * fx
    return np.where(inside, top * (1.0 - fy) + bottom * fy, 0.0).astype(np.float32, copy=False)


def _sample_grayscale_nearest(image: ImageArray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Point-sample a non-wrapping grayscale image.

    Tile Sampler's Pixel Exact mode must preserve the source texels rather than
    silently falling back to the bilinear path used by Antialiased placement.
    """
    source = np.asarray(image, dtype=np.float32)
    if source.ndim == 3:
        source = source[..., 0]
    height, width = source.shape[:2]
    inside = (u >= 0.0) & (u <= 1.0) & (v >= 0.0) & (v <= 1.0)
    pixel_x = np.clip(np.floor(u * width).astype(np.int32), 0, max(width - 1, 0))
    pixel_y = np.clip(np.floor(v * height).astype(np.int32), 0, max(height - 1, 0))
    return np.where(inside, source[pixel_y, pixel_x], 0.0).astype(np.float32, copy=False)


def _sample_grayscale_footprint(
    image: ImageArray,
    u: np.ndarray,
    v: np.ndarray,
    du_dx: np.ndarray,
    dv_dx: np.ndarray,
    du_dy: np.ndarray,
    dv_dy: np.ndarray,
) -> np.ndarray:
    """Filter a transformed pattern over the destination pixel footprint.

    Bilinear sampling only reconstructs between neighbouring source texels; it
    does not remove aliasing when a large input pattern is reduced to a tiny,
    rotated Tile Sampler instance. For magnification we retain bilinear
    reconstruction. For minification a bounded five-tap quincunx footprint
    captures sub-pixel coverage without globally blurring the source texture or
    requiring a full mip chain.
    """
    source = np.asarray(image, dtype=np.float32)
    if source.ndim == 3:
        source = source[..., 0]
    height, width = source.shape[:2]
    footprint_x = np.sqrt((du_dx * width) ** 2 + (dv_dx * height) ** 2)
    footprint_y = np.sqrt((du_dy * width) ** 2 + (dv_dy * height) ** 2)
    minified = np.maximum(footprint_x, footprint_y) > 1.0
    if not np.any(minified):
        return _sample_grayscale_bilinear(source, u, v)

    spread = np.float32(0.375)
    filtered = _sample_grayscale_nearest(source, u, v)
    for sx, sy in ((-spread, -spread), (spread, -spread), (-spread, spread), (spread, spread)):
        filtered += _sample_grayscale_nearest(
            source,
            u + sx * du_dx + sy * du_dy,
            v + sx * dv_dx + sy * dv_dy,
        )
    filtered *= np.float32(0.2)
    if np.all(minified):
        return filtered.astype(np.float32, copy=False)
    reconstructed = _sample_grayscale_bilinear(source, u, v)
    return np.where(minified, filtered, reconstructed).astype(np.float32, copy=False)


def _sample_channel_wrapped(source: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    source = np.asarray(source, dtype=np.float32)
    height, width = source.shape[:2]
    pixel_x = np.mod(u, 1.0) * width - 0.5
    pixel_y = np.mod(v, 1.0) * height - 0.5
    floor_x = np.floor(pixel_x).astype(np.int32)
    floor_y = np.floor(pixel_y).astype(np.int32)
    x0 = np.mod(floor_x, width)
    y0 = np.mod(floor_y, height)
    x1 = np.mod(floor_x + 1, width)
    y1 = np.mod(floor_y + 1, height)
    fx = pixel_x - floor_x
    fy = pixel_y - floor_y
    top = source[y0, x0] * (1.0 - fx) + source[y0, x1] * fx
    bottom = source[y1, x0] * (1.0 - fx) + source[y1, x1] * fx
    return (top * (1.0 - fy) + bottom * fy).astype(np.float32, copy=False)


def _sample_grayscale_wrapped(
    image: ImageArray | None, u: np.ndarray, v: np.ndarray, default: float
) -> np.ndarray | np.float32:
    if image is None:
        return np.float32(default)
    source = np.asarray(image, dtype=np.float32)
    if source.ndim == 3:
        source = source[..., 0]
    return _sample_channel_wrapped(source, u, v)


def _sample_vector_wrapped(
    image: ImageArray | None, u: np.ndarray, v: np.ndarray
) -> tuple[np.ndarray | np.float32, np.ndarray | np.float32]:
    if image is None:
        return np.float32(0.5), np.float32(0.5)
    source = np.asarray(image, dtype=np.float32)
    if source.ndim == 2:
        first = source
        second = source
    else:
        first = source[..., 0]
        second = source[..., 1] if source.shape[-1] > 1 else source[..., 0]
    return _sample_channel_wrapped(first, u, v), _sample_channel_wrapped(second, u, v)


def _tile_builtin_shape(
    pattern: str,
    local_x: np.ndarray,
    local_y: np.ndarray,
    feather: float | np.ndarray,
) -> np.ndarray:
    feather_values = np.asarray(feather, dtype=np.float32)

    def edge_coverage(edge: np.ndarray) -> np.ndarray:
        safe_feather = np.maximum(feather_values, np.float32(1.0e-12))
        softened = np.clip(edge / safe_feather + 0.5, 0.0, 1.0)
        return np.where(feather_values <= 0.0, edge >= 0.0, softened).astype(np.float32)

    if pattern == "Bell":
        radius_squared = local_x * local_x + local_y * local_y
        profile = np.exp(-3.5 * radius_squared)
        edge = 1.0 - np.sqrt(radius_squared)
        return (profile * edge_coverage(edge)).astype(np.float32)

    if pattern == "Disc":
        edge = 1.0 - np.sqrt(local_x * local_x + local_y * local_y)
    elif pattern == "Brick":
        radius = 0.12
        qx = np.abs(local_x) - (1.0 - radius)
        qy = np.abs(local_y) - (1.0 - radius)
        outside = np.sqrt(np.maximum(qx, 0.0) ** 2 + np.maximum(qy, 0.0) ** 2)
        inside = np.minimum(np.maximum(qx, qy), 0.0)
        edge = -(outside + inside - radius)
    elif pattern == "Capsule":
        qx = np.maximum(np.abs(local_x) - 0.45, 0.0)
        edge = 0.55 - np.sqrt(qx * qx + local_y * local_y)
    elif pattern == "Diamond":
        edge = 1.0 - (np.abs(local_x) + np.abs(local_y))
    elif pattern == "Hexagon":
        absolute_x = np.abs(local_x)
        absolute_y = np.abs(local_y)
        edge = 1.0 - np.maximum(absolute_y, absolute_x * 0.8660254 + absolute_y * 0.5)
    elif pattern == "Triangle":
        edge = np.minimum(1.0 - local_y, local_y + 1.0 - 2.0 * np.abs(local_x))
    else:  # Square
        edge = 1.0 - np.maximum(np.abs(local_x), np.abs(local_y))
    return edge_coverage(edge)


_TILE_PATTERN_INPUT_NAMES = (
    "Pattern Input",
    "Pattern Input 2",
    "Pattern Input 3",
    "Pattern Input 4",
)
_TILE_BUILTIN_PATTERNS = (
    "Square",
    "Disc",
    "Brick",
    "Capsule",
    "Bell",
    "Diamond",
    "Hexagon",
    "Triangle",
)


def _tile_pattern_coverage(
    pattern: str,
    selection_mode: str,
    local_x: np.ndarray,
    local_y: np.ndarray,
    pattern_inputs: tuple[ImageArray | None, ...],
    connected_indices: tuple[int, ...],
    canonical_x: np.ndarray,
    canonical_y: np.ndarray,
    x_amount: int,
    seed: int,
    distribution_values: np.ndarray,
    feather: float,
    antialiased_input: bool,
    du_dx: np.ndarray,
    dv_dx: np.ndarray,
    du_dy: np.ndarray,
    dv_dy: np.ndarray,
) -> np.ndarray:
    pattern_u = local_x * 0.5 + 0.5
    pattern_v = local_y * 0.5 + 0.5

    def sample_input(source: ImageArray) -> np.ndarray:
        if antialiased_input:
            return _sample_grayscale_footprint(source, pattern_u, pattern_v, du_dx, dv_dx, du_dy, dv_dy)
        return _sample_grayscale_nearest(source, pattern_u, pattern_v)

    if selection_mode == "Single":
        if pattern in _TILE_PATTERN_INPUT_NAMES:
            index = _TILE_PATTERN_INPUT_NAMES.index(pattern)
            source = pattern_inputs[index]
            if source is None:
                return np.zeros_like(local_x, dtype=np.float32)
            return sample_input(source)
        return _tile_builtin_shape(pattern, local_x, local_y, feather)

    if not connected_indices:
        fallback = pattern if pattern in _TILE_BUILTIN_PATTERNS else "Square"
        return _tile_builtin_shape(fallback, local_x, local_y, feather)

    count = len(connected_indices)
    if selection_mode == "Sequential Inputs":
        ordinal = np.mod(canonical_y * x_amount + canonical_x, count).astype(np.int32)
    elif selection_mode == "Distribution Map":
        ordinal = np.minimum((np.clip(distribution_values, 0.0, 0.999999) * count).astype(np.int32), count - 1)
    else:  # Random Inputs
        ordinal = np.minimum((_tile_hash(canonical_x, canonical_y, seed, 9) * count).astype(np.int32), count - 1)

    coverage = np.zeros_like(local_x, dtype=np.float32)
    for ordinal_value, input_index in enumerate(connected_indices):
        source = pattern_inputs[input_index]
        if source is None:
            continue
        sampled = sample_input(source)
        coverage = np.where(ordinal == ordinal_value, sampled, coverage)
    return coverage.astype(np.float32, copy=False)


TILE_SAMPLER_MAX_CANDIDATE_RADIUS = 64


def tile_sampler_candidate_radius(params: Mapping[str, Any]) -> int:
    """Return the conservative neighbouring-cell radius required by a tile."""
    size_x = min(max(float(params.get("size_x", 0.8)), 0.001), 8.0)
    size_y = min(max(float(params.get("size_y", 0.8)), 0.001), 8.0)
    scale = min(max(float(params.get("scale", 1.0)), 0.001), 4.0)
    scale_random = min(max(float(params.get("scale_random", 0.0)), 0.0), 1.0)
    scale_vector_strength = min(max(float(params.get("scale_vector_map_strength", 0.0)), 0.0), 1.0)
    position_random_x = min(max(float(params.get("position_random_x", 0.0)), 0.0), 1.0)
    position_random_y = min(max(float(params.get("position_random_y", 0.0)), 0.0), 1.0)
    row_offset = min(max(float(params.get("row_offset", 0.0)), 0.0), 1.0)
    displacement = min(max(float(params.get("displacement_intensity", 0.0)), 0.0), 2.0)
    vector_displacement = min(max(float(params.get("vector_displacement", 0.0)), 0.0), 2.0)
    edge_softness = min(max(float(params.get("edge_softness", 0.0)), 0.0), 0.25)
    maximum_scale = scale * (1.0 + scale_random) * (1.0 + 0.25 * scale_vector_strength)
    maximum_extent = max(size_x, size_y) * maximum_scale * 0.5 * (1.0 + edge_softness * 0.5)
    maximum_jitter = max(position_random_x, position_random_y) * 0.5
    required = max(
        int(math.ceil(
            maximum_extent * math.sqrt(2.0)
            + maximum_jitter
            + abs(row_offset)
            + displacement
            + vector_displacement
        )),
        1,
    )
    return min(required, TILE_SAMPLER_MAX_CANDIDATE_RADIUS)


def eval_tile_sampler(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    """Deterministic seamless grayscale tile placement reference renderer."""
    u, v = _uv(context)
    x_amount = max(int(params.get("x_amount", 8)), 1)
    y_amount = max(int(params.get("y_amount", 8)), 1)
    seed = int(params.get("seed", 0))
    non_square = bool(params.get("non_square_expansion", True))
    pattern = str(params.get("pattern", "Square"))
    pattern_selection = str(params.get("pattern_selection", "Single"))
    size_x = min(max(float(params.get("size_x", 0.8)), 0.001), 8.0)
    size_y = min(max(float(params.get("size_y", 0.8)), 0.001), 8.0)
    scale = min(max(float(params.get("scale", 1.0)), 0.001), 4.0)
    scale_random = min(max(float(params.get("scale_random", 0.0)), 0.0), 1.0)
    scale_map_strength = min(max(float(params.get("scale_map_strength", 0.0)), 0.0), 1.0)
    scale_vector_map_strength = min(max(float(params.get("scale_vector_map_strength", 0.0)), 0.0), 1.0)
    position_random_x = min(max(float(params.get("position_random_x", 0.0)), 0.0), 1.0)
    position_random_y = min(max(float(params.get("position_random_y", 0.0)), 0.0), 1.0)
    row_offset = min(max(float(params.get("row_offset", 0.0)), 0.0), 1.0)
    offset_mode = str(params.get("offset_mode", "Every Second Row"))
    global_offset_x = float(params.get("global_offset_x", 0.0))
    global_offset_y = float(params.get("global_offset_y", 0.0))
    displacement_intensity = min(max(float(params.get("displacement_intensity", 0.0)), 0.0), 2.0)
    displacement_angle = float(params.get("displacement_angle", 0.0))
    vector_displacement = min(max(float(params.get("vector_displacement", 0.0)), 0.0), 2.0)
    rotation = float(params.get("rotation", 0.0))
    rotation_random = min(max(float(params.get("rotation_random", 0.0)), 0.0), 180.0)
    rotation_map_multiplier = min(max(float(params.get("rotation_map_multiplier", 0.0)), -720.0), 720.0)
    mask_random = min(max(float(params.get("mask_random", 0.0)), 0.0), 1.0)
    layout_mask = str(params.get("layout_mask", "All Tiles"))
    invert_layout_mask = bool(params.get("invert_layout_mask", False))
    mask_map_threshold = min(max(float(params.get("mask_map_threshold", 0.5)), 0.0), 1.0)
    mask_map_invert = bool(params.get("mask_map_invert", False))
    luminance_random = min(max(float(params.get("luminance_random", 0.0)), 0.0), 1.0)
    opacity = min(max(float(params.get("global_opacity", 1.0)), 0.0), 1.0)
    blend_mode = str(params.get("blend_mode", "Maximum"))
    rendering_order = str(params.get("rendering_order", "Rows then Columns"))
    reverse_rendering_order = bool(params.get("reverse_rendering_order", False))
    mirror_x_random = bool(params.get("mirror_x_random", False))
    mirror_y_random = bool(params.get("mirror_y_random", False))
    background_value = min(max(float(params.get("background_value", 0.0)), 0.0), 1.0)
    edge_softness = max(float(params.get("edge_softness", 0.0)), 0.0)

    background = inputs.get("Background Input")
    if background is None:
        result = np.full((context.height, context.width), background_value, dtype=np.float32)
    else:
        result = np.asarray(background, dtype=np.float32)[..., 0].copy()

    grid_x = u * x_amount - global_offset_x
    grid_y = v * y_amount - global_offset_y
    base_x = np.floor(grid_x).astype(np.int32)
    base_y = np.floor(grid_y).astype(np.int32)
    pattern_inputs = tuple(inputs.get(name) for name in _TILE_PATTERN_INPUT_NAMES)
    connected_indices = tuple(index for index, source in enumerate(pattern_inputs) if source is not None)
    scale_map_input = inputs.get("Scale Map")
    rotation_map_input = inputs.get("Rotation Map")
    displacement_map_input = inputs.get("Displacement Map")
    vector_map_input = inputs.get("Vector Map")
    mask_map_input = inputs.get("Mask Map")
    distribution_map_input = inputs.get("Pattern Distribution Map")
    mask_map_connected = mask_map_input is not None
    displacement_cosine = math.cos(math.radians(displacement_angle))
    displacement_sine = math.sin(math.radians(displacement_angle))

    candidate_radius = tile_sampler_candidate_radius(params)
    cell_width_pixels = context.width / x_amount
    cell_height_pixels = context.height / y_amount
    pixel_basis = max(min(cell_width_pixels, cell_height_pixels), 1.0e-6)
    pixel_feather = 1.25 / max(pixel_basis * min(size_x, size_y) * scale, 1.0)
    feather = max(edge_softness, pixel_feather) if str(params.get("rasterization", "Pixel Exact")) == "Antialiased" else edge_softness

    diameter = candidate_radius * 2 + 1
    candidate_count = diameter * diameter
    candidate_indices = range(candidate_count - 1, -1, -1) if reverse_rendering_order else range(candidate_count)

    for candidate_index in candidate_indices:
        major, minor = divmod(candidate_index, diameter)
        if rendering_order == "Columns then Rows":
            offset_x = major - candidate_radius
            offset_y = minor - candidate_radius
        else:
            offset_y = major - candidate_radius
            offset_x = minor - candidate_radius

        cell_x = base_x + offset_x
        cell_y = base_y + offset_y
        canonical_x = np.mod(cell_x, x_amount).astype(np.int32)
        canonical_y = np.mod(cell_y, y_amount).astype(np.int32)

        shift_x = np.zeros_like(grid_x, dtype=np.float32)
        shift_y = np.zeros_like(grid_y, dtype=np.float32)
        if offset_mode == "Every Second Row":
            shift_x = np.where((canonical_y & 1) == 1, row_offset, 0.0).astype(np.float32)
        elif offset_mode == "Every Second Column":
            shift_y = np.where((canonical_x & 1) == 1, row_offset, 0.0).astype(np.float32)
        elif offset_mode == "Continuous Rows":
            shift_x = np.mod(canonical_y * row_offset, 1.0).astype(np.float32)
        elif offset_mode == "Continuous Columns":
            shift_y = np.mod(canonical_x * row_offset, 1.0).astype(np.float32)

        random_x = _tile_hash(canonical_x, canonical_y, seed, 1)
        random_y = _tile_hash(canonical_x, canonical_y, seed, 2)
        center_x = cell_x.astype(np.float32) + 0.5 + shift_x + (random_x - 0.5) * position_random_x
        center_y = cell_y.astype(np.float32) + 0.5 + shift_y + (random_y - 0.5) * position_random_y

        map_u = np.mod((center_x + global_offset_x) / x_amount, 1.0)
        map_v = np.mod((center_y + global_offset_y) / y_amount, 1.0)
        scale_map_value = (
            _sample_grayscale_wrapped(scale_map_input, map_u, map_v, 1.0)
            if scale_map_strength > 0.0 else np.float32(1.0)
        )
        rotation_map_value = (
            _sample_grayscale_wrapped(rotation_map_input, map_u, map_v, 0.0)
            if abs(rotation_map_multiplier) > 1.0e-9 else np.float32(0.0)
        )
        displacement_map_value = (
            _sample_grayscale_wrapped(displacement_map_input, map_u, map_v, 0.0)
            if displacement_intensity > 0.0 else np.float32(0.0)
        )
        mask_map_value = (
            _sample_grayscale_wrapped(mask_map_input, map_u, map_v, 1.0)
            if mask_map_connected else np.float32(1.0)
        )
        distribution_map_value = (
            _sample_grayscale_wrapped(distribution_map_input, map_u, map_v, 0.0)
            if pattern_selection == "Distribution Map" and connected_indices else np.float32(0.0)
        )
        if scale_vector_map_strength > 0.0 or vector_displacement > 0.0:
            vector_x, vector_y = _sample_vector_wrapped(vector_map_input, map_u, map_v)
        else:
            vector_x, vector_y = np.float32(0.5), np.float32(0.5)

        center_x = center_x + displacement_cosine * displacement_map_value * displacement_intensity
        center_y = center_y + displacement_sine * displacement_map_value * displacement_intensity
        center_x = center_x + (vector_x * 2.0 - 1.0) * vector_displacement
        center_y = center_y + (vector_y * 2.0 - 1.0) * vector_displacement

        random_scale = np.maximum(
            0.05,
            1.0 + (_tile_hash(canonical_x, canonical_y, seed, 3) * 2.0 - 1.0) * scale_random,
        )
        scalar_map_scale = (1.0 - scale_map_strength) + scale_map_strength * np.maximum(scale_map_value, 0.001)
        vector_scale_x = (1.0 - scale_vector_map_strength) + scale_vector_map_strength * (0.75 + vector_x * 0.5)
        vector_scale_y = (1.0 - scale_vector_map_strength) + scale_vector_map_strength * (0.75 + vector_y * 0.5)
        scale_value = scale * random_scale * scalar_map_scale
        half_x = np.maximum(size_x * scale_value * vector_scale_x * 0.5, 1.0e-5)
        half_y = np.maximum(size_y * scale_value * vector_scale_y * 0.5, 1.0e-5)
        local_x = (grid_x - center_x) / half_x
        local_y = (grid_y - center_y) / half_y
        if non_square:
            local_x *= cell_width_pixels / pixel_basis
            local_y *= cell_height_pixels / pixel_basis

        step_local_x = (x_amount / max(context.width, 1)) / half_x
        step_local_y = (y_amount / max(context.height, 1)) / half_y
        if non_square:
            step_local_x *= cell_width_pixels / pixel_basis
            step_local_y *= cell_height_pixels / pixel_basis

        angle = np.deg2rad(
            rotation
            + (_tile_hash(canonical_x, canonical_y, seed, 4) * 2.0 - 1.0) * rotation_random
            + rotation_map_value * rotation_map_multiplier
        )
        cosine = np.cos(angle)
        sine = np.sin(angle)
        rotated_x = cosine * local_x + sine * local_y
        rotated_y = -sine * local_x + cosine * local_y
        du_dx = 0.5 * cosine * step_local_x
        dv_dx = -0.5 * sine * step_local_x
        du_dy = 0.5 * sine * step_local_y
        dv_dy = 0.5 * cosine * step_local_y
        if mirror_x_random:
            mirror_x_sign = np.where(_tile_hash(canonical_x, canonical_y, seed, 5) >= 0.5, -1.0, 1.0).astype(np.float32)
            rotated_x *= mirror_x_sign
            du_dx *= mirror_x_sign
            du_dy *= mirror_x_sign
        if mirror_y_random:
            mirror_y_sign = np.where(_tile_hash(canonical_x, canonical_y, seed, 6) >= 0.5, -1.0, 1.0).astype(np.float32)
            rotated_y *= mirror_y_sign
            dv_dx *= mirror_y_sign
            dv_dy *= mirror_y_sign

        coverage = _tile_pattern_coverage(
            pattern,
            pattern_selection,
            rotated_x,
            rotated_y,
            pattern_inputs,
            connected_indices,
            canonical_x,
            canonical_y,
            x_amount,
            seed,
            distribution_map_value,
            feather,
            str(params.get("rasterization", "Pixel Exact")) == "Antialiased",
            du_dx,
            dv_dx,
            du_dy,
            dv_dy,
        )
        visible = _tile_hash(canonical_x, canonical_y, seed, 7) >= mask_random
        if layout_mask == "Checker":
            layout_visible = ((canonical_x + canonical_y) & 1) == 0
        elif layout_mask == "Alternate Rows":
            layout_visible = (canonical_y & 1) == 0
        elif layout_mask == "Alternate Columns":
            layout_visible = (canonical_x & 1) == 0
        else:
            layout_visible = np.ones_like(visible, dtype=bool)
        if invert_layout_mask:
            layout_visible = ~layout_visible
        visible = visible & layout_visible
        if mask_map_connected:
            map_visible = mask_map_value >= mask_map_threshold
            if mask_map_invert:
                map_visible = ~map_visible
            visible = visible & map_visible
        coverage *= visible.astype(np.float32)
        random_luminance = _tile_hash(canonical_x, canonical_y, seed, 8)
        # Luminance Random always varies downward from the untouched tile value:
        # 0.0 -> 1..1, 0.5 -> 0.5..1, 1.0 -> 0..1.
        value = (1.0 - luminance_random) + random_luminance * luminance_random
        amount = coverage * value * opacity
        if blend_mode == "Add":
            result = np.minimum(result + amount, 1.0)
        elif blend_mode == "Subtract":
            result = np.maximum(result - amount, 0.0)
        elif blend_mode == "Replace":
            alpha = np.clip(coverage * opacity, 0.0, 1.0)
            result = result * (1.0 - alpha) + value * alpha
        else:  # Maximum
            result = np.maximum(result, amount)

    return grayscale_rgba(np.clip(result, 0.0, 1.0))


_SPLATTER_PATTERN_INPUT_NAMES = (
    "Pattern Input",
    "Pattern Input 2",
    "Pattern Input 3",
    "Pattern Input 4",
)
_SPLATTER_BUILTIN_PATTERNS = _TILE_BUILTIN_PATTERNS
_SPLATTER_MAX_RINGS = 10
_SPLATTER_MAX_PATTERNS = 64
_SPLATTER_NEIGHBOUR_CANDIDATES = 6


def _splatter_hash_scalar(ring: int, pattern: int, seed: int, stream: int) -> float:
    """Scalar counterpart to ``_tile_hash`` and the public WGSL hash."""
    value = (
        (int(ring) & 0xFFFFFFFF) * 0x9E3779B9
        ^ (int(pattern) & 0xFFFFFFFF) * 0x85EBCA6B
        ^ (int(seed) & 0xFFFFFFFF) * 0xC2B2AE35
        ^ (int(stream) & 0xFFFFFFFF) * 0x27D4EB2D
    ) & 0xFFFFFFFF
    value ^= value >> 16
    value = (value * 0x7FEB352D) & 0xFFFFFFFF
    value ^= value >> 15
    value = (value * 0x846CA68B) & 0xFFFFFFFF
    value ^= value >> 16
    return float(value & 0x00FFFFFF) / 16777216.0


def _splatter_pattern_count(params: Mapping[str, Any], ring: int, *, interactive: bool = False) -> int:
    authored = min(max(int(params.get("pattern_amount", 12)), 1), _SPLATTER_MAX_PATTERNS)
    if interactive:
        authored = min(authored, 32)
    minimum = min(max(int(params.get("minimum_pattern_amount", 1)), 1), authored)
    randomness = min(max(float(params.get("pattern_amount_random", 0.0)), 0.0), 1.0)
    seed = int(params.get("seed", 0))
    reduction = _splatter_hash_scalar(ring, 0, seed, 31) * randomness * (authored - minimum)
    return min(max(int(round(authored - reduction)), minimum), authored)


def _splatter_pattern_coverage(
    authored_pattern: str,
    selection_mode: str,
    local_x: np.ndarray,
    local_y: np.ndarray,
    pattern_inputs: tuple[ImageArray | None, ...],
    connected_indices: tuple[int, ...],
    ring_index: int,
    pattern_index: np.ndarray,
    seed: int,
    feather: float,
    antialiased_input: bool,
    du_dx: np.ndarray,
    dv_dx: np.ndarray,
    du_dy: np.ndarray,
    dv_dy: np.ndarray,
) -> np.ndarray:
    pattern_u = local_x * 0.5 + 0.5
    pattern_v = local_y * 0.5 + 0.5

    def sample_input(source: ImageArray) -> np.ndarray:
        if antialiased_input:
            return _sample_grayscale_footprint(source, pattern_u, pattern_v, du_dx, dv_dx, du_dy, dv_dy)
        return _sample_grayscale_nearest(source, pattern_u, pattern_v)

    if selection_mode == "Single":
        if authored_pattern in _SPLATTER_PATTERN_INPUT_NAMES:
            source = pattern_inputs[_SPLATTER_PATTERN_INPUT_NAMES.index(authored_pattern)]
            return np.zeros_like(local_x, dtype=np.float32) if source is None else sample_input(source)
        fallback = authored_pattern if authored_pattern in _SPLATTER_BUILTIN_PATTERNS else "Square"
        return _tile_builtin_shape(fallback, local_x, local_y, feather)

    if not connected_indices:
        fallback = authored_pattern if authored_pattern in _SPLATTER_BUILTIN_PATTERNS else "Square"
        return _tile_builtin_shape(fallback, local_x, local_y, feather)

    connected_count = len(connected_indices)
    if selection_mode == "Sequential Around Ring":
        ordinal = np.mod(pattern_index, connected_count).astype(np.int32)
    elif selection_mode == "One Input per Ring":
        ordinal = np.full_like(pattern_index, ring_index % connected_count, dtype=np.int32)
    else:  # Random Inputs
        ordinal = np.minimum(
            (_tile_hash(np.full_like(pattern_index, ring_index), pattern_index, seed, 41) * connected_count).astype(np.int32),
            connected_count - 1,
        )

    coverage = np.zeros_like(local_x, dtype=np.float32)
    for ordinal_value, input_index in enumerate(connected_indices):
        source = pattern_inputs[input_index]
        if source is None:
            continue
        coverage = np.where(ordinal == ordinal_value, sample_input(source), coverage)
    return coverage.astype(np.float32, copy=False)


def eval_splatter_circular(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    """Reference renderer for deterministic grayscale concentric-ring scattering.

    Rather than testing every possible instance for every output pixel, each
    ring evaluates either all of its small pattern set or a bounded angular
    neighbourhood around the pixel. This keeps the reference implementation
    practical while matching the WGSL placement model.
    """
    u, v = _uv(context)
    aspect = context.width / max(context.height, 1)
    center_x = min(max(float(params.get("center_x", 0.5)), -2.0), 3.0)
    center_y = min(max(float(params.get("center_y", 0.5)), -2.0), 3.0)
    physical_x = (u - center_x) * aspect
    physical_y = v - center_y
    polar_angle = np.mod(np.degrees(np.arctan2(physical_y, physical_x)), 360.0)

    ring_amount = min(max(int(params.get("ring_amount", 3)), 1), _SPLATTER_MAX_RINGS)
    if context.render_mode == "interactive":
        ring_amount = min(ring_amount, 6)
    first_radius = min(max(float(params.get("first_ring_radius", 0.15)), 0.0), 2.0)
    ring_spacing = min(max(float(params.get("ring_spacing", 0.12)), -1.0), 1.0)
    radius_random = min(max(float(params.get("radius_random", 0.0)), 0.0), 1.0)
    arc_spread = min(max(float(params.get("arc_spread", 360.0)), 1.0), 360.0)
    ring_rotation = float(params.get("ring_rotation", 0.0))
    ring_rotation_offset = float(params.get("ring_rotation_offset", 0.0))
    spiral = min(max(float(params.get("spiral", 0.0)), -1.0), 1.0)
    angular_random = min(max(float(params.get("angular_random", 0.0)), 0.0), 1.0)
    orientation = str(params.get("orientation", "Face Outward"))
    authored_rotation = float(params.get("pattern_rotation", 0.0))
    rotation_random = min(max(float(params.get("rotation_random", 0.0)), 0.0), 180.0)
    rotation_by_ring = float(params.get("rotation_by_ring", 0.0))
    size_x = min(max(float(params.get("size_x", 0.12)), 0.001), 4.0)
    size_y = min(max(float(params.get("size_y", 0.12)), 0.001), 4.0)
    scale = min(max(float(params.get("scale", 1.0)), 0.001), 4.0)
    scale_random = min(max(float(params.get("scale_random", 0.0)), 0.0), 1.0)
    scale_by_ring = min(max(float(params.get("scale_by_ring", 0.0)), -1.0), 1.0)
    scale_by_pattern = min(max(float(params.get("scale_by_pattern", 0.0)), -1.0), 1.0)
    connect_patterns = bool(params.get("connect_patterns", False))
    connect_scale = min(max(float(params.get("connect_scale", 1.0)), 0.05), 4.0)
    edge_softness = min(max(float(params.get("edge_softness", 0.0)), 0.0), 0.25)
    antialiased = str(params.get("rasterization", "Antialiased")) == "Antialiased"
    pattern = str(params.get("pattern", "Disc"))
    selection_mode = str(params.get("pattern_selection", "Single"))
    seed = int(params.get("seed", 0))
    random_removal = min(max(float(params.get("random_removal", 0.0)), 0.0), 1.0)
    luminance = min(max(float(params.get("luminance", 1.0)), 0.0), 1.0)
    luminance_random = min(max(float(params.get("luminance_random", 0.0)), 0.0), 1.0)
    luminance_by_ring = min(max(float(params.get("luminance_by_ring", 0.0)), -1.0), 1.0)
    luminance_by_pattern = min(max(float(params.get("luminance_by_pattern", 0.0)), -1.0), 1.0)
    opacity = min(max(float(params.get("global_opacity", 1.0)), 0.0), 1.0)
    blend_mode = str(params.get("blend_mode", "Maximum"))
    background_value = min(max(float(params.get("background_value", 0.0)), 0.0), 1.0)

    background = inputs.get("Background Input")
    if background is None:
        result = np.full((context.height, context.width), background_value, dtype=np.float32)
    else:
        source = np.asarray(background, dtype=np.float32)
        result = source[..., 0].copy() if source.ndim == 3 else source.copy()

    pattern_inputs = tuple(inputs.get(name) for name in _SPLATTER_PATTERN_INPUT_NAMES)
    connected_indices = tuple(index for index, source in enumerate(pattern_inputs) if source is not None)
    ring_denominator = max(ring_amount - 1, 1)

    for ring_index in range(ring_amount):
        count = _splatter_pattern_count(params, ring_index, interactive=context.render_mode == "interactive")
        full_ring = arc_spread >= 359.999
        angle_step = 360.0 / count if full_ring else (arc_spread / max(count - 1, 1))
        start_angle = ring_rotation + ring_index * ring_rotation_offset
        relative_angle = np.mod(polar_angle - start_angle, 360.0)
        nearest = np.rint(relative_angle / max(angle_step, 1.0e-6)).astype(np.int32)
        if full_ring:
            nearest = np.mod(nearest, count)
        else:
            nearest = np.clip(nearest, 0, count - 1)

        if count <= _SPLATTER_NEIGHBOUR_CANDIDATES * 2 + 1:
            candidates = [np.full_like(nearest, index, dtype=np.int32) for index in range(count)]
        else:
            candidates = [np.mod(nearest + offset, count).astype(np.int32) for offset in range(-_SPLATTER_NEIGHBOUR_CANDIDATES, _SPLATTER_NEIGHBOUR_CANDIDATES + 1)]

        for pattern_index in candidates:
            pattern_t = pattern_index.astype(np.float32) / max(count - 1, 1)
            random_angle = (_tile_hash(np.full_like(pattern_index, ring_index), pattern_index, seed, 1) * 2.0 - 1.0)
            instance_angle_deg = start_angle + pattern_index.astype(np.float32) * angle_step + random_angle * angular_random * angle_step * 0.5
            instance_angle = np.deg2rad(instance_angle_deg)
            radius_basis = abs(ring_spacing) if abs(ring_spacing) > 1.0e-6 else max(first_radius, 0.1)
            random_radius = (_tile_hash(np.full_like(pattern_index, ring_index), pattern_index, seed, 2) * 2.0 - 1.0)
            instance_radius = (
                first_radius
                + ring_index * ring_spacing
                + spiral * pattern_t
                + random_radius * radius_random * radius_basis * 0.5
            )
            instance_center_x = np.cos(instance_angle) * instance_radius
            instance_center_y = np.sin(instance_angle) * instance_radius
            relative_x = physical_x - instance_center_x
            relative_y = physical_y - instance_center_y

            random_scale = np.maximum(
                0.05,
                1.0 + (_tile_hash(np.full_like(pattern_index, ring_index), pattern_index, seed, 3) * 2.0 - 1.0) * scale_random,
            )
            ring_progress = ring_index / ring_denominator
            scale_progress = np.maximum(
                0.05,
                1.0 + scale_by_ring * ring_progress + scale_by_pattern * (pattern_t * 2.0 - 1.0),
            )
            scale_value = scale * random_scale * scale_progress
            if connect_patterns:
                chord = 2.0 * np.maximum(np.abs(instance_radius), 1.0e-5) * math.sin(math.radians(angle_step) * 0.5)
                half_x = np.maximum(chord * connect_scale * scale_value * 0.5, 1.0e-5)
            else:
                half_x = np.maximum(size_x * scale_value * 0.5, 1.0e-5)
            half_y = np.maximum(size_y * scale_value * 0.5, 1.0e-5)

            if orientation == "Face Centre":
                rotation = instance_angle_deg - 90.0 + authored_rotation
            elif orientation == "Tangent":
                rotation = instance_angle_deg + authored_rotation
            elif orientation == "Fixed":
                rotation = np.full_like(instance_angle_deg, authored_rotation, dtype=np.float32)
            else:  # Face Outward
                rotation = instance_angle_deg + 90.0 + authored_rotation
            rotation = rotation + ring_index * rotation_by_ring
            rotation = rotation + (_tile_hash(np.full_like(pattern_index, ring_index), pattern_index, seed, 4) * 2.0 - 1.0) * rotation_random
            angle = np.deg2rad(rotation)
            cosine = np.cos(angle)
            sine = np.sin(angle)
            local_x = (cosine * relative_x + sine * relative_y) / half_x
            local_y = (-sine * relative_x + cosine * relative_y) / half_y

            px_step_x = aspect / max(context.width, 1)
            px_step_y = 1.0 / max(context.height, 1)
            du_dx = 0.5 * cosine * px_step_x / half_x
            dv_dx = -0.5 * sine * px_step_x / half_y
            du_dy = 0.5 * sine * px_step_y / half_x
            dv_dy = 0.5 * cosine * px_step_y / half_y
            pixel_feather = 1.25 / np.maximum(
                min(context.width, context.height) * np.minimum(half_x, half_y),
                1.0,
            )
            feather = np.maximum(edge_softness, pixel_feather) if antialiased else edge_softness
            coverage = _splatter_pattern_coverage(
                pattern,
                selection_mode,
                local_x,
                local_y,
                pattern_inputs,
                connected_indices,
                ring_index,
                pattern_index,
                seed,
                feather,
                antialiased,
                du_dx,
                dv_dx,
                du_dy,
                dv_dy,
            )
            visible = _tile_hash(np.full_like(pattern_index, ring_index), pattern_index, seed, 5) >= random_removal
            coverage *= visible.astype(np.float32)
            random_value = _tile_hash(np.full_like(pattern_index, ring_index), pattern_index, seed, 6)
            value = luminance * ((1.0 - luminance_random) + random_value * luminance_random)
            value *= np.clip(1.0 + luminance_by_ring * ring_progress + luminance_by_pattern * (pattern_t * 2.0 - 1.0), 0.0, 2.0)
            value = np.clip(value, 0.0, 1.0)
            amount = coverage * value * opacity
            if blend_mode == "Add":
                result = np.minimum(result + amount, 1.0)
            elif blend_mode == "Subtract":
                result = np.maximum(result - amount, 0.0)
            elif blend_mode == "Replace":
                alpha = np.clip(coverage * opacity, 0.0, 1.0)
                result = result * (1.0 - alpha) + value * alpha
            else:
                result = np.maximum(result, amount)

    return grayscale_rgba(np.clip(result, 0.0, 1.0))

def register_generator_nodes(registry: NodeRegistry) -> None:
    f = ParameterSpec
    definitions = [
        NodeDefinition(
            "generator.constant",
            "Constant",
            "Generators",
            eval_constant,
            parameters=(f("value", "Value", "float", 0.5, 0.0, 1.0, 0.01, animatable=True),),
            description="A uniform greyscale value.",
            accent="#8b67d8",
            tags=("gray", "flat", "value"),
            output_format="r16f",
            gpu_kernel="constant.wgsl",
        ),
        NodeDefinition(
            "generator.color",
            "Colour",
            "Generators",
            eval_color,
            parameters=(f("color", "Colour", "color", "#ffffffff"),),
            description="A uniform RGBA colour.",
            accent="#8b67d8",
            gpu_kernel="color.wgsl",
        ),
        NodeDefinition(
            "generator.linear_gradient",
            "Linear Gradient",
            "Gradients",
            eval_linear_gradient,
            parameters=(
                f("angle", "Angle", "float", 0.0, -180.0, 180.0, 1.0, animatable=True, editor="angle", unit="degrees", fine_step=1.0, coarse_step=5.0),
                f("offset", "Offset", "float", 0.0, -1.0, 1.0, 0.01, animatable=True),
                f("repeat", "Repeat", "bool", True),
            ),
            tags=("ramp", "directional", "tile"), accent="#6876df",
            output_format="r16f",
            gpu_kernel="linear_gradient.wgsl",
        ),
        NodeDefinition(
            "generator.linear_gradient_2",
            "Linear Gradient 2",
            "Gradients",
            eval_linear_gradient_2,
            parameters=(
                f("angle", "Angle", "float", 90.0, -180.0, 180.0, 1.0, animatable=True, editor="angle", unit="degrees", fine_step=1.0, coarse_step=5.0),
                f("offset", "Offset", "float", 0.0, -1.0, 1.0, 0.01, animatable=True),
                f("repeat", "Repeat", "bool", True),
            ),
            description="A smooth black-to-white-to-black directional dome gradient.",
            tags=("ramp", "directional", "smooth", "dome", "tile"), accent="#6876df",
            output_format="r16f",
            gpu_kernel="linear_gradient.wgsl",
        ),
        NodeDefinition(
            "generator.linear_gradient_3",
            "Linear Gradient 3",
            "Gradients",
            eval_linear_gradient_3,
            parameters=(
                f("angle", "Angle", "float", 90.0, -180.0, 180.0, 1.0, animatable=True, editor="angle", unit="degrees", fine_step=1.0, coarse_step=5.0),
                f("offset", "Offset", "float", 0.0, -1.0, 1.0, 0.01, animatable=True),
                f("repeat", "Repeat", "bool", True),
            ),
            description="A linear black-to-white-to-black directional gradient with a sharp centre ridge.",
            tags=("ramp", "directional", "sharp", "ridge", "tile"), accent="#6876df",
            output_format="r16f",
            gpu_kernel="linear_gradient.wgsl",
        ),
        NodeDefinition(
            "generator.radial_gradient",
            "Radial Gradient",
            "Gradients",
            eval_radial_gradient,
            parameters=(
                f("center_x", "Centre X", "float", 0.5, 0.0, 1.0, 0.01, animatable=True),
                f("center_y", "Centre Y", "float", 0.5, 0.0, 1.0, 0.01, animatable=True),
                f("radius", "Radius", "float", 0.5, 0.01, 1.5, 0.01, animatable=True),
                f("falloff", "Falloff", "float", 1.0, 0.05, 8.0, 0.05, animatable=True),
            ),
            description="A radial gradient evaluated on repeating UVs.",
            tags=("circle", "ramp", "soft", "tile"), accent="#6876df",
            output_format="r16f",
            gpu_kernel="radial_gradient.wgsl",
        ),
        NodeDefinition(
            "shape.shape",
            "Shape",
            "Shapes",
            eval_shape,
            parameters=(
                f("shape", "Shape", "enum", "Rectangle", options=("Rectangle", "Rounded Rectangle", "Disc", "Ring", "Capsule", "Triangle", "Diamond", "Hexagon", "Cross", "X", "Crescent", "Bell", "Gaussian", "Pyramid", "Cone", "Hemisphere", "Waves", "Linear Gradation"), group="Shape", group_order=10),
                f("fill_mode", "Fill Mode", "enum", "Solid", options=("Solid", "Outline", "Linear Bevel", "Rounded Bevel"), group="Shape", group_order=10, description="Used by silhouette-based shapes; profile-native shapes such as Bell, Cone and Waves have their own height profile.", visible_when=(("shape", ("Rectangle", "Rounded Rectangle", "Disc", "Ring", "Capsule", "Triangle", "Diamond", "Hexagon", "Cross", "X", "Crescent")),)),
                f("center_x", "Centre X", "float", 0.5, 0.0, 1.0, 0.01, animatable=True, group="Transform", group_order=20),
                f("center_y", "Centre Y", "float", 0.5, 0.0, 1.0, 0.01, animatable=True, group="Transform", group_order=20),
                f("size_x", "Size X", "float", 1.0, 0.01, 4.0, 0.01, animatable=True, group="Transform", group_order=20, slider_maximum=2.0),
                f("size_y", "Size Y", "float", 1.0, 0.01, 4.0, 0.01, animatable=True, group="Transform", group_order=20, slider_maximum=2.0),
                f("scale", "Scale", "float", 0.8, 0.01, 8.0, 0.01, animatable=True, group="Transform", group_order=20, slider_maximum=4.0),
                f("rotation", "Rotation", "float", 0.0, -180.0, 180.0, 1.0, animatable=True, group="Transform", group_order=20, editor="angle", unit="degrees", fine_step=1.0, coarse_step=5.0),
                f("tile_x", "Tile X", "float", 1.0, 1.0, 32.0, 1.0, animatable=True, group="Transform", group_order=20, fine_step=1.0, coarse_step=1.0),
                f("tile_y", "Tile Y", "float", 1.0, 1.0, 32.0, 1.0, animatable=True, group="Transform", group_order=20, fine_step=1.0, coarse_step=1.0),
                f("non_square_compensation", "Non-square Compensation", "bool", True, group="Transform", group_order=20),
                f("rasterization", "Edge Rasterisation", "enum", "Antialiased", options=("Antialiased", "Pixel Exact"), group="Quality", group_order=90, description="Antialiased stores one-pixel fractional coverage around hard geometry. Pixel Exact stores binary edges when Edge Softness is zero."),
                f("edge_softness", "Edge Softness", "float", 0.0, 0.0, 0.25, 0.001, animatable=True, group="Profile", group_order=30, visible_when=(("shape", ("Rectangle", "Rounded Rectangle", "Disc", "Ring", "Capsule", "Triangle", "Diamond", "Hexagon", "Cross", "X", "Crescent")),)),
                f("profile_width", "Outline / Bevel Width", "float", 0.18, 0.001, 1.5, 0.01, animatable=True, group="Profile", group_order=30, visible_when=(("fill_mode", ("Outline", "Linear Bevel", "Rounded Bevel")),)),
                f("invert", "Invert", "bool", False, group="Profile", group_order=30),
                f("corner_radius", "Corner Radius", "float", 0.25, 0.0, 0.95, 0.01, animatable=True, group="Shape-Specific", group_order=40, visible_when=(("shape", ("Rounded Rectangle",)),)),
                f("thickness", "Ring Thickness", "float", 0.2, 0.01, 0.95, 0.01, animatable=True, group="Shape-Specific", group_order=40, visible_when=(("shape", ("Ring",)),)),
                f("capsule_length", "Capsule Length", "float", 0.5, 0.0, 1.6, 0.01, animatable=True, group="Shape-Specific", group_order=40, visible_when=(("shape", ("Capsule",)),)),
                f("bar_thickness", "Cross / X Thickness", "float", 0.35, 0.05, 1.0, 0.01, animatable=True, group="Shape-Specific", group_order=40, visible_when=(("shape", ("Cross", "X")),)),
                f("cutout_size", "Crescent Cutout Size", "float", 0.8, 0.05, 1.5, 0.01, animatable=True, group="Shape-Specific", group_order=40, visible_when=(("shape", ("Crescent",)),)),
                f("cutout_offset_x", "Crescent Offset X", "float", 0.35, -1.5, 1.5, 0.01, animatable=True, group="Shape-Specific", group_order=40, slider_minimum=-1.0, slider_maximum=1.0, visible_when=(("shape", ("Crescent",)),)),
                f("cutout_offset_y", "Crescent Offset Y", "float", 0.0, -1.5, 1.5, 0.01, animatable=True, group="Shape-Specific", group_order=40, slider_minimum=-1.0, slider_maximum=1.0, visible_when=(("shape", ("Crescent",)),)),
                f("wave_frequency", "Wave Frequency", "float", 4.0, 0.1, 32.0, 0.1, animatable=True, group="Shape-Specific", group_order=40, slider_maximum=12.0, visible_when=(("shape", ("Waves",)),)),
                f("wave_phase", "Wave Phase", "float", 0.0, -180.0, 180.0, 1.0, animatable=True, group="Shape-Specific", group_order=40, editor="angle", unit="degrees", fine_step=1.0, coarse_step=5.0, visible_when=(("shape", ("Waves",)),)),
                f("wave_balance", "Wave Balance", "float", 0.5, 0.0, 1.0, 0.01, animatable=True, group="Shape-Specific", group_order=40, visible_when=(("shape", ("Waves",)),)),
            ),
            description="A consolidated procedural shape generator covering silhouette masks and profile-style primitives for Tile Sampler inputs, material masks and height construction.",
            accent="#d06b88",
            tags=("shape", "disc", "rectangle", "triangle", "hexagon", "mask", "profile", "pattern"),
            output_format="r16f",
            gpu_kernel="shape.wgsl",
        ),
        NodeDefinition(
            "shape.polygon",
            "Polygon",
            "Shapes",
            eval_polygon,
            parameters=(
                f("sides", "Sides", "int", 6, 3, 64, 1, animatable=True, group="Polygon", group_order=10, slider_maximum=16, fine_step=1, coarse_step=1),
                f("inner_radius", "Inner Radius", "float", 1.0, 0.02, 1.0, 0.01, animatable=True, group="Polygon", group_order=10, description="1.0 produces a regular polygon; lower values create star-like alternating points."),
                f("alternating_offset", "Alternating Offset", "float", 0.0, -0.8, 0.8, 0.01, animatable=True, group="Polygon", group_order=10),
                f("roundness", "Roundness", "float", 0.0, 0.0, 0.5, 0.01, animatable=True, group="Polygon", group_order=10),
                f("fill_mode", "Fill Mode", "enum", "Solid", options=("Solid", "Outline", "Linear Bevel", "Rounded Bevel"), group="Polygon", group_order=10),
                f("center_x", "Centre X", "float", 0.5, 0.0, 1.0, 0.01, animatable=True, group="Transform", group_order=20),
                f("center_y", "Centre Y", "float", 0.5, 0.0, 1.0, 0.01, animatable=True, group="Transform", group_order=20),
                f("size_x", "Size X", "float", 1.0, 0.01, 4.0, 0.01, animatable=True, group="Transform", group_order=20, slider_maximum=2.0),
                f("size_y", "Size Y", "float", 1.0, 0.01, 4.0, 0.01, animatable=True, group="Transform", group_order=20, slider_maximum=2.0),
                f("scale", "Scale", "float", 0.8, 0.01, 8.0, 0.01, animatable=True, group="Transform", group_order=20, slider_maximum=4.0),
                f("rotation", "Rotation", "float", 0.0, -180.0, 180.0, 1.0, animatable=True, group="Transform", group_order=20, editor="angle", unit="degrees", fine_step=1.0, coarse_step=5.0),
                f("tile_x", "Tile X", "float", 1.0, 1.0, 32.0, 1.0, animatable=True, group="Transform", group_order=20, fine_step=1.0, coarse_step=1.0),
                f("tile_y", "Tile Y", "float", 1.0, 1.0, 32.0, 1.0, animatable=True, group="Transform", group_order=20, fine_step=1.0, coarse_step=1.0),
                f("non_square_compensation", "Non-square Compensation", "bool", True, group="Transform", group_order=20),
                f("rasterization", "Edge Rasterisation", "enum", "Antialiased", options=("Antialiased", "Pixel Exact"), group="Quality", group_order=90, description="Antialiased stores one-pixel fractional coverage around hard geometry. Pixel Exact stores binary edges when Edge Softness is zero."),
                f("edge_softness", "Edge Softness", "float", 0.0, 0.0, 0.25, 0.001, animatable=True, group="Profile", group_order=30),
                f("profile_width", "Outline / Bevel Width", "float", 0.18, 0.001, 1.5, 0.01, animatable=True, group="Profile", group_order=30),
                f("twist", "Twist", "float", 0.0, -180.0, 180.0, 1.0, animatable=True, group="Profile", group_order=30, editor="angle", unit="degrees", fine_step=1.0, coarse_step=5.0),
                f("radial_distortion", "Radial Distortion", "float", 0.0, -0.9, 0.9, 0.01, animatable=True, group="Profile", group_order=30),
                f("invert", "Invert", "bool", False, group="Profile", group_order=30),
            ),
            description="A regular-polygon and star generator with alternating-point control, roundness, twist and bevel / outline profiles.",
            accent="#d06b88",
            tags=("polygon", "star", "shape", "badge", "burst", "mask"),
            output_format="r16f",
            gpu_kernel="polygon.wgsl",
        ),
        NodeDefinition(
            "shape.polygon_burst",
            "Polygon Burst",
            "Shapes",
            eval_polygon_burst,
            parameters=(
                f("sides", "Sides", "int", 6, 3, 64, 1, animatable=True, group="Burst", group_order=10, slider_maximum=16, fine_step=1, coarse_step=1),
                f("fill_mode", "Fill Mode", "enum", "Solid", options=("Solid", "Radial Gradient", "Angular Gradient"), group="Burst", group_order=10),
                f("explode", "Explode", "float", 0.0, 0.0, 1.5, 0.01, animatable=True, group="Burst", group_order=10),
                f("slice_gap", "Slice Gap", "float", 0.05, 0.0, 0.95, 0.01, animatable=True, group="Burst", group_order=10),
                f("inner_radius", "Inner Radius", "float", 0.0, 0.0, 0.95, 0.01, animatable=True, group="Burst", group_order=10),
                f("alternate_value", "Alternate Slice Value", "bool", False, group="Burst", group_order=10),
                f("alternate_strength", "Alternate Strength", "float", 0.5, 0.0, 1.0, 0.01, animatable=True, group="Burst", group_order=10),
                f("center_x", "Centre X", "float", 0.5, 0.0, 1.0, 0.01, animatable=True, group="Transform", group_order=20),
                f("center_y", "Centre Y", "float", 0.5, 0.0, 1.0, 0.01, animatable=True, group="Transform", group_order=20),
                f("size_x", "Size X", "float", 1.0, 0.01, 4.0, 0.01, animatable=True, group="Transform", group_order=20, slider_maximum=2.0),
                f("size_y", "Size Y", "float", 1.0, 0.01, 4.0, 0.01, animatable=True, group="Transform", group_order=20, slider_maximum=2.0),
                f("scale", "Scale", "float", 0.8, 0.01, 8.0, 0.01, animatable=True, group="Transform", group_order=20, slider_maximum=4.0),
                f("rotation", "Rotation", "float", 0.0, -180.0, 180.0, 1.0, animatable=True, group="Transform", group_order=20, editor="angle", unit="degrees", fine_step=1.0, coarse_step=5.0),
                f("tile_x", "Tile X", "float", 1.0, 1.0, 32.0, 1.0, animatable=True, group="Transform", group_order=20, fine_step=1.0, coarse_step=1.0),
                f("tile_y", "Tile Y", "float", 1.0, 1.0, 32.0, 1.0, animatable=True, group="Transform", group_order=20, fine_step=1.0, coarse_step=1.0),
                f("non_square_compensation", "Non-square Compensation", "bool", True, group="Transform", group_order=20),
                f("rasterization", "Edge Rasterisation", "enum", "Antialiased", options=("Antialiased", "Pixel Exact"), group="Quality", group_order=90, description="Antialiased stores one-pixel fractional coverage around hard geometry. Pixel Exact stores binary edges when Edge Softness is zero."),
                f("edge_softness", "Edge Softness", "float", 0.0, 0.0, 0.25, 0.001, animatable=True, group="Profile", group_order=30),
                f("twist", "Twist", "float", 0.0, -180.0, 180.0, 1.0, animatable=True, group="Profile", group_order=30, editor="angle", unit="degrees", fine_step=1.0, coarse_step=5.0),
                f("invert", "Invert", "bool", False, group="Profile", group_order=30),
            ),
            description="A radial slice / burst generator useful for segmented polygons, sunbursts, apertures, magic circles and stylised masks.",
            accent="#d06b88",
            tags=("polygon", "burst", "sunburst", "segments", "radial", "shape"),
            output_format="r16f",
            gpu_kernel="polygon_burst.wgsl",
        ),
        NodeDefinition(
            "pattern.tile_sampler",
            "Tile Sampler",
            "Patterns",
            eval_tile_sampler,
            inputs=(
                "Pattern Input",
                "Pattern Input 2",
                "Pattern Input 3",
                "Pattern Input 4",
                "Scale Map",
                "Rotation Map",
                "Displacement Map",
                "Vector Map",
                "Mask Map",
                "Pattern Distribution Map",
                "Background Input",
            ),
            parameters=(
                f("x_amount", "X Amount", "int", 8, 1, 128, 1, animatable=True, group="Distribution", group_order=10, slider_maximum=64, fine_step=1, coarse_step=5),
                f("y_amount", "Y Amount", "int", 8, 1, 128, 1, animatable=True, group="Distribution", group_order=10, slider_maximum=64, fine_step=1, coarse_step=5),
                f("non_square_expansion", "Non-square Compensation", "bool", True, group="Distribution", group_order=10, description="Keep built-in and sampled patterns visually proportional when the output or tile grid is not square."),
                f("rasterization", "Edge Rasterisation", "enum", "Antialiased", options=("Antialiased", "Pixel Exact"), group="Quality", group_order=90, description="Built-in shapes use fractional edge coverage in Antialiased mode. Connected Pattern Inputs use destination-footprint filtering when reduced or rotated; Pixel Exact point-samples their source texels."),
                f("seed", "Random Seed", "int", 0, 0, 2147483647, 1, group="Distribution", group_order=10, slider_maximum=1000, fine_step=1, coarse_step=10),
                f("pattern_selection", "Pattern Selection", "enum", "Single", options=("Single", "Random Inputs", "Sequential Inputs", "Distribution Map"), group="Pattern", group_order=20, description="Single uses the Pattern control. Other modes distribute the connected Pattern Input sockets per tile."),
                f("pattern", "Pattern", "enum", "Square", options=("Pattern Input", "Pattern Input 2", "Pattern Input 3", "Pattern Input 4", "Square", "Disc", "Brick", "Capsule", "Bell", "Diamond", "Hexagon", "Triangle"), group="Pattern", group_order=20),
                f("mirror_x_random", "Random Mirror X", "bool", False, group="Pattern", group_order=20),
                f("mirror_y_random", "Random Mirror Y", "bool", False, group="Pattern", group_order=20),
                f("edge_softness", "Edge Softness", "float", 0.0, 0.0, 0.25, 0.001, animatable=True, group="Pattern", group_order=20),
                f("size_x", "Size X", "float", 0.8, 0.01, 8.0, 0.01, animatable=True, group="Size", group_order=30, slider_maximum=4.0, fine_step=0.01, coarse_step=0.1, description="Tile width in grid cells. Values above the slider range can be typed precisely."),
                f("size_y", "Size Y", "float", 0.8, 0.01, 8.0, 0.01, animatable=True, group="Size", group_order=30, slider_maximum=4.0, fine_step=0.01, coarse_step=0.1, description="Tile height in grid cells. Values above the slider range can be typed precisely."),
                f("scale", "Scale", "float", 1.0, 0.01, 4.0, 0.01, animatable=True, group="Size", group_order=30, slider_maximum=2.0, fine_step=0.01, coarse_step=0.1, description="Uniform multiplier applied after Size X/Y. Values above the slider range can be typed precisely."),
                f("scale_random", "Scale Random", "float", 0.0, 0.0, 1.0, 0.01, animatable=True, group="Size", group_order=30),
                f("scale_map_strength", "Scale Map Strength", "float", 0.0, 0.0, 1.0, 0.01, animatable=True, group="Size", group_order=30, description="Blends from full authored scale toward the grayscale Scale Map sampled at each tile centre."),
                f("scale_vector_map_strength", "Vector Scale Strength", "float", 0.0, 0.0, 1.0, 0.01, animatable=True, group="Size", group_order=30, description="Uses Vector Map R/G to vary X/Y scale independently around a neutral value of 0.5."),
                f("position_random_x", "Position Random X", "float", 0.0, 0.0, 1.0, 0.01, animatable=True, group="Position", group_order=40),
                f("position_random_y", "Position Random Y", "float", 0.0, 0.0, 1.0, 0.01, animatable=True, group="Position", group_order=40),
                f("offset_mode", "Offset Mode", "enum", "Every Second Row", options=("Every Second Row", "Every Second Column", "Continuous Rows", "Continuous Columns"), group="Position", group_order=40, description="Choose whether the Offset Amount staggers alternating rows/columns or advances continuously across the grid."),
                f("row_offset", "Offset Amount", "float", 0.0, 0.0, 1.0, 0.01, animatable=True, group="Position", group_order=40, description="Fraction of one tile cell. 0.5 creates a classic half-tile brick stagger."),
                f("global_offset_x", "Global Offset X", "float", 0.0, -128.0, 128.0, 0.01, animatable=True, group="Position", group_order=40, slider_minimum=-4.0, slider_maximum=4.0, fine_step=0.01, coarse_step=0.25, description="Global offset measured in tile cells; larger values can be typed directly."),
                f("global_offset_y", "Global Offset Y", "float", 0.0, -128.0, 128.0, 0.01, animatable=True, group="Position", group_order=40, slider_minimum=-4.0, slider_maximum=4.0, fine_step=0.01, coarse_step=0.25, description="Global offset measured in tile cells; larger values can be typed directly."),
                f("displacement_intensity", "Displacement Map Intensity", "float", 0.0, 0.0, 2.0, 0.01, animatable=True, group="Position", group_order=40, slider_maximum=1.0, fine_step=0.01, coarse_step=0.1, description="Moves each tile in cell units using the Displacement Map sampled at its centre."),
                f("displacement_angle", "Displacement Angle", "float", 0.0, -180.0, 180.0, 1.0, animatable=True, group="Position", group_order=40, editor="angle", unit="degrees", fine_step=1.0, coarse_step=5.0),
                f("vector_displacement", "Vector Map Displacement", "float", 0.0, 0.0, 2.0, 0.01, animatable=True, group="Position", group_order=40, slider_maximum=1.0, fine_step=0.01, coarse_step=0.1, description="Uses Vector Map R/G around neutral 0.5 to offset tiles in X/Y cell units."),
                f("rotation", "Rotation", "float", 0.0, -180.0, 180.0, 1.0, animatable=True, group="Rotation", group_order=50, editor="angle", unit="degrees", fine_step=1.0, coarse_step=5.0),
                f("rotation_random", "Rotation Random Range", "float", 0.0, 0.0, 180.0, 1.0, animatable=True, group="Rotation", group_order=50, unit="degrees", fine_step=1.0, coarse_step=5.0, description="Symmetric random range: 180° varies each tile from -180° to +180°, covering every possible orientation."),
                f("rotation_map_multiplier", "Rotation Map Multiplier", "float", 0.0, -720.0, 720.0, 1.0, animatable=True, group="Rotation", group_order=50, slider_minimum=-180.0, slider_maximum=180.0, unit="degrees", fine_step=1.0, coarse_step=5.0, description="Adds grayscale-map rotation: black adds 0°, white adds the full multiplier."),
                f("layout_mask", "Layout Mask", "enum", "All Tiles", options=("All Tiles", "Checker", "Alternate Rows", "Alternate Columns"), group="Tile Selection", group_order=60, description="Select tiles by their stable grid identity before jitter, displacement or rotation."),
                f("invert_layout_mask", "Invert Layout Mask", "bool", False, group="Tile Selection", group_order=60),
                f("mask_random", "Random Removal", "float", 0.0, 0.0, 1.0, 0.01, animatable=True, group="Tile Selection", group_order=60, description="Probability that an individual tile is removed."),
                f("mask_map_threshold", "Mask Map Threshold", "float", 0.5, 0.0, 1.0, 0.01, animatable=True, group="Tile Selection", group_order=60),
                f("mask_map_invert", "Invert Mask Map", "bool", False, group="Tile Selection", group_order=60),
                f("luminance_random", "Luminance Random", "float", 0.0, 0.0, 1.0, 0.01, animatable=True, group="Value", group_order=70, description="0 keeps every tile at full luminance; 1 distributes tile values uniformly across the complete 0–1 range."),
                f("global_opacity", "Global Opacity", "float", 1.0, 0.0, 1.0, 0.01, animatable=True, group="Value", group_order=70),
                f("blend_mode", "Blend Mode", "enum", "Maximum", options=("Maximum", "Add", "Subtract", "Replace"), group="Compositing", group_order=70),
                f("background_value", "Background Value", "float", 0.0, 0.0, 1.0, 0.01, animatable=True, group="Compositing", group_order=70),
                f("rendering_order", "Rendering Order", "enum", "Rows then Columns", options=("Rows then Columns", "Columns then Rows"), group="Compositing", group_order=70, description="Controls candidate traversal for order-sensitive Replace overlaps."),
                f("reverse_rendering_order", "Reverse Rendering Order", "bool", False, group="Compositing", group_order=70),
            ),
            description="A deterministic seamless grayscale tile-placement engine with multiple pattern inputs, map-driven scale/rotation/displacement/masking, staggered layouts and order-aware overlap compositing.",
            accent="#bf8a55",
            tags=("tiles", "bricks", "scatter", "pattern", "sampler", "paving", "distribution"),
            output_format="r16f",
            gpu_kernel="tile_sampler.wgsl",
            input_kinds=(
                ("Pattern Input", "grayscale"),
                ("Pattern Input 2", "grayscale"),
                ("Pattern Input 3", "grayscale"),
                ("Pattern Input 4", "grayscale"),
                ("Scale Map", "grayscale"),
                ("Rotation Map", "grayscale"),
                ("Displacement Map", "grayscale"),
                ("Vector Map", "vector"),
                ("Mask Map", "grayscale"),
                ("Pattern Distribution Map", "grayscale"),
                ("Background Input", "grayscale"),
            ),
            output_kinds=(("Image", "grayscale"),),
            default_image_kind="grayscale",
        ),
        NodeDefinition(
            "pattern.splatter_circular",
            "Splatter Circular",
            "Patterns",
            eval_splatter_circular,
            inputs=(
                "Pattern Input",
                "Pattern Input 2",
                "Pattern Input 3",
                "Pattern Input 4",
                "Background Input",
            ),
            parameters=(
                f("pattern_amount", "Patterns per Ring", "int", 12, 1, 64, 1, animatable=True, group="Rings", group_order=10, slider_maximum=32, fine_step=1, coarse_step=4),
                f("pattern_amount_random", "Pattern Amount Random", "float", 0.0, 0.0, 1.0, 0.01, animatable=True, group="Rings", group_order=10),
                f("minimum_pattern_amount", "Minimum Pattern Amount", "int", 1, 1, 64, 1, animatable=True, group="Rings", group_order=10, slider_maximum=32, fine_step=1, coarse_step=4, description="Lower limit used when Pattern Amount Random reduces a ring. Values above the current Patterns per Ring are clamped safely."),
                f("ring_amount", "Ring Amount", "int", 3, 1, 10, 1, animatable=True, group="Rings", group_order=10, fine_step=1, coarse_step=1),
                f("first_ring_radius", "First Ring Radius", "float", 0.15, 0.0, 2.0, 0.01, animatable=True, group="Rings", group_order=10, slider_maximum=0.75, fine_step=0.005, coarse_step=0.05),
                f("ring_spacing", "Ring Spacing", "float", 0.12, -1.0, 1.0, 0.01, animatable=True, group="Rings", group_order=10, slider_minimum=-0.5, slider_maximum=0.5, fine_step=0.005, coarse_step=0.05),
                f("radius_random", "Radius Random", "float", 0.0, 0.0, 1.0, 0.01, animatable=True, group="Rings", group_order=10),
                f("arc_spread", "Arc Spread", "float", 360.0, 1.0, 360.0, 1.0, animatable=True, group="Rings", group_order=10, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0),
                f("ring_rotation", "Ring Rotation", "float", 0.0, -720.0, 720.0, 1.0, animatable=True, group="Rings", group_order=10, editor="angle", unit="degrees", angle_wrap=False, slider_minimum=-180.0, slider_maximum=180.0, fine_step=1.0, coarse_step=15.0),
                f("ring_rotation_offset", "Rotation Offset per Ring", "float", 0.0, -360.0, 360.0, 1.0, animatable=True, group="Rings", group_order=10, editor="angle", unit="degrees", fine_step=1.0, coarse_step=15.0),
                f("spiral", "Spiral Amount", "float", 0.0, -1.0, 1.0, 0.01, animatable=True, group="Rings", group_order=10, fine_step=0.005, coarse_step=0.05, description="Adds or removes radius progressively around each ring, turning closed rings into spirals."),
                f("angular_random", "Angular Random", "float", 0.0, 0.0, 1.0, 0.01, animatable=True, group="Rings", group_order=10, description="Jitters each instance by up to half of one authored angular step."),
                f("center_x", "Centre X", "float", 0.5, -2.0, 3.0, 0.01, animatable=True, group="Position", group_order=20, slider_minimum=0.0, slider_maximum=1.0),
                f("center_y", "Centre Y", "float", 0.5, -2.0, 3.0, 0.01, animatable=True, group="Position", group_order=20, slider_minimum=0.0, slider_maximum=1.0),
                f("pattern_selection", "Pattern Selection", "enum", "Single", options=("Single", "Random Inputs", "Sequential Around Ring", "One Input per Ring"), group="Pattern", group_order=30, description="Distribute connected custom pattern inputs randomly, sequentially around each ring, or one input per ring."),
                f("pattern", "Pattern", "enum", "Disc", options=("Pattern Input", "Pattern Input 2", "Pattern Input 3", "Pattern Input 4", "Square", "Disc", "Brick", "Capsule", "Bell", "Diamond", "Hexagon", "Triangle"), group="Pattern", group_order=30),
                f("orientation", "Orientation", "enum", "Face Outward", options=("Face Outward", "Face Centre", "Tangent", "Fixed"), group="Pattern", group_order=30),
                f("pattern_rotation", "Pattern Rotation", "float", 0.0, -720.0, 720.0, 1.0, animatable=True, group="Pattern", group_order=30, editor="angle", unit="degrees", angle_wrap=False, slider_minimum=-180.0, slider_maximum=180.0, fine_step=1.0, coarse_step=15.0),
                f("rotation_random", "Rotation Random Range", "float", 0.0, 0.0, 180.0, 1.0, animatable=True, group="Pattern", group_order=30, unit="degrees", fine_step=1.0, coarse_step=15.0),
                f("rotation_by_ring", "Rotation Offset per Ring", "float", 0.0, -360.0, 360.0, 1.0, animatable=True, group="Pattern", group_order=30, unit="degrees", fine_step=1.0, coarse_step=15.0),
                f("edge_softness", "Edge Softness", "float", 0.0, 0.0, 0.25, 0.001, animatable=True, group="Pattern", group_order=30),
                f("rasterization", "Edge Rasterisation", "enum", "Antialiased", options=("Antialiased", "Pixel Exact"), group="Quality", group_order=90, description="Antialiased filters reduced custom inputs over the destination footprint; Pixel Exact preserves source texels."),
                f("size_x", "Pattern Width", "float", 0.12, 0.001, 4.0, 0.01, animatable=True, group="Scale", group_order=40, slider_maximum=1.0, fine_step=0.005, coarse_step=0.05),
                f("size_y", "Pattern Height", "float", 0.12, 0.001, 4.0, 0.01, animatable=True, group="Scale", group_order=40, slider_maximum=1.0, fine_step=0.005, coarse_step=0.05),
                f("scale", "Uniform Scale", "float", 1.0, 0.001, 4.0, 0.01, animatable=True, group="Scale", group_order=40, slider_maximum=2.0, fine_step=0.005, coarse_step=0.1),
                f("scale_random", "Scale Random", "float", 0.0, 0.0, 1.0, 0.01, animatable=True, group="Scale", group_order=40),
                f("scale_by_ring", "Scale by Ring", "float", 0.0, -1.0, 1.0, 0.01, animatable=True, group="Scale", group_order=40),
                f("scale_by_pattern", "Scale Around Ring", "float", 0.0, -1.0, 1.0, 0.01, animatable=True, group="Scale", group_order=40),
                f("connect_patterns", "Connect Patterns", "bool", False, group="Scale", group_order=40, description="Derives pattern width from the chord between neighbouring instances so strips, petals and chain links meet around the ring."),
                f("connect_scale", "Connected Width", "float", 1.0, 0.05, 4.0, 0.01, animatable=True, group="Scale", group_order=40, slider_maximum=2.0, visible_when=(("connect_patterns", (True,)),)),
                f("random_removal", "Random Removal", "float", 0.0, 0.0, 1.0, 0.01, animatable=True, group="Selection", group_order=50),
                f("seed", "Random Seed", "int", 0, 0, 2147483647, 1, group="Selection", group_order=50, slider_maximum=1000, fine_step=1, coarse_step=10, is_random_seed=True),
                f("luminance", "Luminance", "float", 1.0, 0.0, 1.0, 0.01, animatable=True, group="Value", group_order=60),
                f("luminance_random", "Luminance Random", "float", 0.0, 0.0, 1.0, 0.01, animatable=True, group="Value", group_order=60),
                f("luminance_by_ring", "Luminance by Ring", "float", 0.0, -1.0, 1.0, 0.01, animatable=True, group="Value", group_order=60),
                f("luminance_by_pattern", "Luminance Around Ring", "float", 0.0, -1.0, 1.0, 0.01, animatable=True, group="Value", group_order=60),
                f("global_opacity", "Global Opacity", "float", 1.0, 0.0, 1.0, 0.01, animatable=True, group="Value", group_order=60),
                f("blend_mode", "Blend Mode", "enum", "Maximum", options=("Maximum", "Add", "Subtract", "Replace"), group="Compositing", group_order=70),
                f("background_value", "Background Value", "float", 0.0, 0.0, 1.0, 0.01, animatable=True, group="Compositing", group_order=70),
            ),
            description="A deterministic grayscale radial placement engine for concentric rings, arcs and spirals with custom patterns, progression, connected widths and direct 2D Preview editing.",
            accent="#bf8a55",
            tags=("radial", "circular", "rings", "spiral", "scatter", "splatter", "magic circle", "shockwave", "pattern"),
            output_format="r16f",
            gpu_kernel="splatter_circular.wgsl",
            input_kinds=(
                ("Pattern Input", "grayscale"),
                ("Pattern Input 2", "grayscale"),
                ("Pattern Input 3", "grayscale"),
                ("Pattern Input 4", "grayscale"),
                ("Background Input", "grayscale"),
            ),
            output_kinds=(("Image", "grayscale"),),
            default_image_kind="grayscale",
        ),
        NodeDefinition(
            "pattern.checker",
            "Checker",
            "Patterns",
            eval_checker,
            parameters=(
                f("scale", "Cells", "int", 8, 1, 128, 1, animatable=True),
                f("value_a", "Value A", "float", 0.0, 0.0, 1.0, 0.01, animatable=True),
                f("value_b", "Value B", "float", 1.0, 0.0, 1.0, 0.01, animatable=True),
            ),
            description="A seamless checker pattern.",
            accent="#bf8a55",
            tags=("grid", "tiles"),
            output_format="r16f",
            gpu_kernel="checker.wgsl",
        ),
    ]
    kinds = {
        "generator.constant": "grayscale",
        "generator.color": "color",
        "generator.linear_gradient": "grayscale",
        "generator.linear_gradient_2": "grayscale",
        "generator.linear_gradient_3": "grayscale",
        "generator.radial_gradient": "grayscale",
        "shape.shape": "grayscale",
        "shape.polygon": "grayscale",
        "shape.polygon_burst": "grayscale",
        "pattern.tile_sampler": "grayscale",
        "pattern.splatter_circular": "grayscale",
        "pattern.checker": "grayscale",
    }
    for definition in definitions:
        kind = kinds[definition.type_id]
        registry.register(replace(
            definition,
            output_kinds=tuple((name, kind) for name in definition.output_names),
            default_image_kind=kind,
        ))
