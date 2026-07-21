from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Mapping

import numpy as np

from .base import EvalContext, ImageArray, NodeDefinition, ParameterSpec
from .image_ops import empty_image, ensure_rgba, grayscale_rgba, luminance, resolution_scale
from .registry import NodeRegistry

_TERRAIN_ACCENT = "#7e9f55"
_DIRECTIONS_4 = ((-1, 0), (1, 0), (0, -1), (0, 1))
_DIRECTIONS_8 = _DIRECTIONS_4 + ((-1, -1), (-1, 1), (1, -1), (1, 1))


def _input(inputs: Mapping[str, ImageArray], name: str, context: EvalContext, value: float = 0.0) -> ImageArray:
    return ensure_rgba(inputs.get(name, empty_image(context, value=value)), context)


def _height(inputs: Mapping[str, ImageArray], name: str, context: EvalContext, value: float = 0.0) -> np.ndarray:
    return np.clip(luminance(_input(inputs, name, context, value)), 0.0, 1.0).astype(np.float32, copy=False)


def _smoothstep(edge0: float, edge1: float, value: np.ndarray) -> np.ndarray:
    if abs(edge1 - edge0) < 1e-9:
        return (value >= edge1).astype(np.float32)
    x = np.clip((value - edge0) / (edge1 - edge0), 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _terrace_hash_u32(value: np.ndarray | np.uint32) -> np.ndarray:
    """Small deterministic integer hash shared conceptually with the WGSL path."""
    hashed = np.asarray(value, dtype=np.uint32).copy()
    with np.errstate(over="ignore"):
        hashed ^= hashed >> np.uint32(16)
        hashed *= np.uint32(0x7FEB352D)
        hashed ^= hashed >> np.uint32(15)
        hashed *= np.uint32(0x846CA68B)
        hashed ^= hashed >> np.uint32(16)
    return hashed


def _terrace_hash01(index: int, seed: int) -> float:
    key = np.uint32(((int(index) * 0x9E3779B9) ^ (int(seed) * 0x85EBCA6B)) & 0xFFFFFFFF)
    return float(_terrace_hash_u32(key)) / float(0xFFFFFFFF)


def _terrace_interval_boundaries(
    steps: int,
    spacing_variation: float,
    distribution: float,
    seed: int,
) -> np.ndarray:
    interval_count = max(int(steps) - 1, 1)
    variation = float(np.clip(spacing_variation, 0.0, 1.0))
    bias = float(np.clip(distribution, -1.0, 1.0))
    weights = np.empty(interval_count, dtype=np.float64)
    for index in range(interval_count):
        position = (index + 0.5) / interval_count
        trend = 2.0 ** (bias * (position * 2.0 - 1.0))
        jitter = 1.0 + (_terrace_hash01(index, seed) * 2.0 - 1.0) * variation * 0.9
        weights[index] = max(trend * jitter, 0.08)
    boundaries = np.concatenate(([0.0], np.cumsum(weights)))
    boundaries /= max(float(boundaries[-1]), 1e-12)
    boundaries[-1] = 1.0
    return boundaries.astype(np.float32)


def _terrace_breakup_noise(context: EvalContext, scale: float, seed: int) -> np.ndarray:
    cells = max(int(round(float(scale))), 1)
    y, x = np.mgrid[0:context.height, 0:context.width]
    px = ((x.astype(np.float32) + 0.5) / max(context.width, 1)) * cells
    py = ((y.astype(np.float32) + 0.5) / max(context.height, 1)) * cells
    x0 = np.floor(px).astype(np.int32)
    y0 = np.floor(py).astype(np.int32)
    fx = px - np.floor(px)
    fy = py - np.floor(py)
    sx = fx * fx * (3.0 - 2.0 * fx)
    sy = fy * fy * (3.0 - 2.0 * fy)

    def corner(ix: np.ndarray, iy: np.ndarray) -> np.ndarray:
        wrapped_x = np.mod(ix, cells).astype(np.uint32)
        wrapped_y = np.mod(iy, cells).astype(np.uint32)
        with np.errstate(over="ignore"):
            key = (
                wrapped_x * np.uint32(0x9E3779B9)
                ^ wrapped_y * np.uint32(0x85EBCA6B)
                ^ np.uint32(int(seed) & 0xFFFFFFFF)
            )
        return _terrace_hash_u32(key).astype(np.float32) / np.float32(0xFFFFFFFF)

    a = corner(x0, y0)
    b = corner(x0 + 1, y0)
    c = corner(x0, y0 + 1)
    d = corner(x0 + 1, y0 + 1)
    top = a * (1.0 - sx) + b * sx
    bottom = c * (1.0 - sx) + d * sx
    return (top * (1.0 - sy) + bottom * sy).astype(np.float32)


def _neighbour(height: np.ndarray, dy: int, dx: int, mode: str) -> tuple[np.ndarray, np.ndarray]:
    if mode == "Seamless / Wrap":
        return np.roll(height, shift=(-dy, -dx), axis=(0, 1)), np.ones(height.shape, dtype=bool)
    rows, cols = height.shape
    y = np.arange(rows)[:, None] + dy
    x = np.arange(cols)[None, :] + dx
    valid = (y >= 0) & (y < rows) & (x >= 0) & (x < cols)
    if mode == "Closed":
        yy = np.clip(y, 0, rows - 1)
        xx = np.clip(x, 0, cols - 1)
        return height[yy, xx], valid
    # Drain: outside terrain has zero height, allowing material to leave.
    yy = np.clip(y, 0, rows - 1)
    xx = np.clip(x, 0, cols - 1)
    result = height[yy, xx].copy()
    result[~valid] = 0.0
    return result, valid


def _incoming_shift(values: np.ndarray, dy: int, dx: int, mode: str) -> np.ndarray:
    if mode == "Seamless / Wrap":
        return np.roll(values, shift=(dy, dx), axis=(0, 1))
    output = np.zeros_like(values)
    rows, cols = values.shape
    src_y0 = max(0, -dy); src_y1 = min(rows, rows - dy)
    src_x0 = max(0, -dx); src_x1 = min(cols, cols - dx)
    dst_y0 = src_y0 + dy; dst_y1 = src_y1 + dy
    dst_x0 = src_x0 + dx; dst_x1 = src_x1 + dx
    if src_y1 > src_y0 and src_x1 > src_x0:
        output[dst_y0:dst_y1, dst_x0:dst_x1] = values[src_y0:src_y1, src_x0:src_x1]
    return output


def eval_slope(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    h = _height(inputs, "Height", context)
    dx = (np.roll(h, -1, axis=1) - np.roll(h, 1, axis=1)) * 0.5 * context.width
    dy = (np.roll(h, -1, axis=0) - np.roll(h, 1, axis=0)) * 0.5 * context.height
    scale = max(float(params.get("height_scale", 1.0)), 1e-6)
    angle = np.arctan(np.sqrt(dx * dx + dy * dy) * scale) / (math.pi * 0.5)
    result = np.clip((angle - 0.5) * float(params.get("contrast", 1.0)) + 0.5, 0.0, 1.0)
    if bool(params.get("invert", False)):
        result = 1.0 - result
    return grayscale_rgba(result.astype(np.float32))


def eval_curvature(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    h = _height(inputs, "Height", context)
    lap = (
        np.roll(h, 1, axis=0) + np.roll(h, -1, axis=0)
        + np.roll(h, 1, axis=1) + np.roll(h, -1, axis=1)
        - h * 4.0
    )
    value = lap * float(params.get("strength", 8.0)) * resolution_scale(context) ** 2
    mode = str(params.get("mode", "Signed"))
    if mode == "Convex":
        result = np.maximum(-value, 0.0)
    elif mode == "Concave":
        result = np.maximum(value, 0.0)
    elif mode == "Absolute":
        result = np.abs(value)
    else:
        result = value * 0.5 + 0.5
    result = np.clip((result - 0.5) * float(params.get("contrast", 1.0)) + 0.5, 0.0, 1.0)
    if bool(params.get("invert", False)):
        result = 1.0 - result
    return grayscale_rgba(result.astype(np.float32))


def eval_terrace(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    h = _height(inputs, "Height", context)
    steps = max(int(params.get("steps", 8)), 2)
    offset = float(params.get("offset", 0.0))
    spacing_variation = np.clip(float(params.get("spacing_variation", 0.18)), 0.0, 1.0)
    distribution = np.clip(float(params.get("height_distribution", 0.0)), -1.0, 1.0)
    smoothness = np.clip(float(params.get("smoothness", 0.16)), 0.0, 1.0)
    plateau_slope = np.clip(float(params.get("plateau_slope", 0.06)), 0.0, 1.0)
    strength = np.clip(float(params.get("strength", 1.0)), 0.0, 1.0)
    seed = int(params.get("seed", 1))
    boundary_breakup = np.clip(float(params.get("boundary_breakup", 0.10)), 0.0, 1.5)
    breakup_scale = max(float(params.get("breakup_scale", 4.0)), 1.0)
    variation_influence = np.clip(float(params.get("variation_influence", 0.5)), 0.0, 2.0)

    interval_count = max(steps - 1, 1)
    boundaries = _terrace_interval_boundaries(steps, spacing_variation, distribution, seed)
    procedural = (
        _terrace_breakup_noise(context, breakup_scale, seed)
        if boundary_breakup > 1e-6
        else np.full_like(h, 0.5)
    )
    variation = _height(inputs, "Variation", context, 0.5) if "Variation" in inputs else np.full_like(h, 0.5)
    phase_shift = (
        (procedural * 2.0 - 1.0) * boundary_breakup
        + (variation * 2.0 - 1.0) * variation_influence
    )
    sample_height = np.clip(h + (offset + phase_shift) / interval_count, 0.0, 1.0)

    interval_index = np.searchsorted(boundaries[1:], sample_height, side="right")
    interval_index = np.clip(interval_index, 0, interval_count - 1)
    lower = boundaries[interval_index]
    upper = boundaries[interval_index + 1]
    local_height = np.clip((sample_height - lower) / np.maximum(upper - lower, 1e-8), 0.0, 1.0)
    if smoothness <= 1e-6:
        edge_profile = np.zeros_like(local_height)
    else:
        edge_profile = _smoothstep(1.0 - smoothness, 1.0, local_height)
    profile = edge_profile * (1.0 - plateau_slope) + local_height * plateau_slope
    terraced = np.clip(lower + (upper - lower) * profile, 0.0, 1.0)

    mask = _height(inputs, "Mask", context, 1.0) if "Mask" in inputs else np.ones_like(h)
    if bool(params.get("invert_mask", False)):
        mask = 1.0 - mask
    influence = np.clip(strength * mask, 0.0, 1.0)
    result = h * (1.0 - influence) + terraced * influence
    return grayscale_rgba(result.astype(np.float32))


def eval_height_combine(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    a = _height(inputs, "A", context)
    b = _height(inputs, "B", context)
    mask = _height(inputs, "Mask", context, 1.0) if "Mask" in inputs else np.ones_like(a)
    mode = str(params.get("mode", "Maximum"))
    if mode == "Add":
        combined = a + b
    elif mode == "Subtract":
        combined = a - b
    elif mode == "Multiply":
        combined = a * b
    elif mode == "Minimum":
        combined = np.minimum(a, b)
    elif mode == "Average":
        combined = (a + b) * 0.5
    elif mode == "Difference":
        combined = np.abs(a - b)
    else:
        combined = np.maximum(a, b)
    opacity = np.clip(float(params.get("opacity", 1.0)) * mask, 0.0, 1.0)
    result = a * (1.0 - opacity) + combined * opacity
    if bool(params.get("clamp", True)):
        result = np.clip(result, 0.0, 1.0)
    return grayscale_rgba(result.astype(np.float32))


def eval_height_blend(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    base = _height(inputs, "Base", context)
    layer = _height(inputs, "Layer", context)
    mask = _height(inputs, "Mask", context, 1.0) if "Mask" in inputs else np.ones_like(base)
    offset = float(params.get("height_offset", 0.0))
    transition = max(float(params.get("transition", 0.1)), 1e-6)
    bias = float(params.get("bias", 0.0))
    dominance = (layer + offset - base + bias) / transition
    height_weight = np.clip(dominance * 0.5 + 0.5, 0.0, 1.0)
    height_weight = height_weight * height_weight * (3.0 - 2.0 * height_weight)
    weight = np.clip(mask * float(params.get("opacity", 1.0)) * height_weight, 0.0, 1.0)
    result = base * (1.0 - weight) + layer * weight
    return grayscale_rgba(np.clip(result, 0.0, 1.0).astype(np.float32))


def _thermal_iterations(params: Mapping[str, Any], context: EvalContext) -> int:
    mode = str(params.get("quality", "Automatic"))
    preview = max(int(params.get("preview_iterations", 28)), 0)
    final = max(int(params.get("final_iterations", 140)), 0)
    selected = preview if mode == "Preview" else final if mode == "Final" else (
        final if context.render_mode == "final" else preview
    )
    # Continuous parameter drags use a bounded draft solve. The exact authored
    # Preview/Final count is evaluated immediately after release.
    if context.render_mode == "interactive":
        return min(selected, 8)
    return selected


def _thermal_variation(
    source: np.ndarray,
    boundary: str,
    seed: int,
    scale: float,
) -> np.ndarray:
    """Terrain-anchored fracture variation used to break uniform talus bands.

    The field is derived from the source height rather than absolute pixel
    coordinates.  Moving a seamless terrain therefore moves its weathering
    pattern with it, avoiding texture-space streaks and preserving tiling.
    """
    scale = np.clip(float(scale), 0.0, 1.0)
    broad = source.astype(np.float32, copy=True)
    for _ in range(1 + int(round(scale * 4.0))):
        broad = _terrain_blur(broad, 0.58, boundary)
    left, _ = _neighbour(broad, 0, -1, boundary)
    right, _ = _neighbour(broad, 0, 1, boundary)
    up, _ = _neighbour(broad, -1, 0, boundary)
    down, _ = _neighbour(broad, 1, 0, boundary)
    gx = right - left
    gy = down - up
    detail = source - broad
    phase = (
        broad * (3.0 + 7.0 * scale)
        + detail * (9.0 + 15.0 * scale)
        + (gx - gy) * (5.0 + 9.0 * scale)
        + float(seed) * 0.173
    )
    value = 0.55 + 0.30 * np.sin(phase * math.tau) + 0.15 * np.cos((phase * 0.47 + gx + gy) * math.tau)
    return np.clip(value, 0.0, 1.0).astype(np.float32)


def eval_thermal_erosion(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    """Talus/weathering erosion with multi-direction material transport.

    The earlier implementation moved every unstable texel toward only its
    steepest neighbour. That was fast, but tended to form directional streaks
    and unnaturally uniform slopes. This solve distributes loose material among
    every downslope neighbour in proportion to slope excess, producing broader
    talus fans and more natural cliff-foot deposition while preserving volume.
    """
    height = _height(inputs, "Height", context).copy()
    original = height.copy()
    hardness = _height(inputs, "Hardness", context, 0.0) if "Hardness" in inputs else np.zeros_like(height)
    iterations = _thermal_iterations(params, context)
    boundary = str(params.get("boundary", "Seamless / Wrap"))
    directions = _DIRECTIONS_8 if str(params.get("neighbourhood", "8 Neighbours")) == "8 Neighbours" else _DIRECTIONS_4
    angle = math.radians(np.clip(float(params.get("talus_angle", 34.0)), 0.0, 89.0))
    height_scale = max(float(params.get("height_scale", 1.0)), 1e-6)
    base_talus = math.tan(angle) / max(min(context.width, context.height), 1) / height_scale
    weathering = np.clip(float(params.get("erosion_strength", 0.42)), 0.0, 1.0)
    mobility = np.clip(float(params.get("talus_mobility", 0.65)), 0.0, 1.0)
    rock_resistance = np.clip(float(params.get("rock_resistance", 0.12)), 0.0, 1.0)
    max_transfer = max(float(params.get("max_transfer", 0.025)), 0.0)
    fracture_strength = np.clip(float(params.get("fracture_strength", 0.16)), 0.0, 1.0)
    fracture_scale = np.clip(float(params.get("fracture_scale", 0.35)), 0.0, 1.0)
    shape_protection = np.clip(float(params.get("shape_protection", 0.08)), 0.0, 1.0)
    seed = int(params.get("seed", 1))
    variation = _thermal_variation(original, boundary, seed, fracture_scale)
    production = (1.0 - fracture_strength) + fracture_strength * variation
    erodibility = np.clip(1.0 - hardness, 0.0, 1.0) * (1.0 - rock_resistance) * production
    erosion_total = np.zeros_like(height)
    deposition_total = np.zeros_like(height)

    for _iteration in range(iterations):
        excesses: list[np.ndarray] = []
        valids: list[np.ndarray] = []
        for index, (dy, dx) in enumerate(directions):
            neighbour, valid = _neighbour(height, dy, dx, boundary)
            distance = math.sqrt(2.0) if index >= 4 else 1.0
            excess = np.maximum(height - neighbour - base_talus * distance, 0.0)
            if boundary == "Closed":
                excess = np.where(valid, excess, 0.0)
            excesses.append(excess.astype(np.float32, copy=False))
            valids.append(valid)

        stack = np.stack(excesses, axis=0)
        total_excess = np.sum(stack, axis=0)
        transfer_fraction = weathering * (0.28 + 0.72 * mobility)
        total_outflow = total_excess * transfer_fraction * erodibility
        total_outflow = np.minimum(total_outflow, max_transfer * (0.20 + 0.80 * mobility))
        total_outflow = np.minimum(total_outflow, np.maximum(height, 0.0) * 0.45)
        weights = np.divide(
            stack,
            np.maximum(total_excess[None, ...], 1e-12),
            out=np.zeros_like(stack),
            where=total_excess[None, ...] > 1e-12,
        )

        incoming = np.zeros_like(height)
        for index, (dy, dx) in enumerate(directions):
            sent = total_outflow * weights[index]
            if boundary == "Closed":
                sent = np.where(valids[index], sent, 0.0)
            incoming += _incoming_shift(sent, dy, dx, boundary)

        height = np.clip(height - total_outflow + incoming, 0.0, 1.0)
        if shape_protection > 1e-8 and iterations > 0:
            # Shape Protection is intentionally gentle: at 1.0 it restores at
            # most about one quarter of the source displacement over the solve.
            preserve = shape_protection * 0.25 / iterations
            height = np.clip(height + (original - height) * preserve * (1.0 - hardness), 0.0, 1.0)
        erosion_total += total_outflow
        deposition_total += incoming

    output = str(params.get("preview_output", "Eroded Height"))
    if output == "Erosion":
        result = erosion_total
    elif output == "Deposition":
        result = deposition_total
    else:
        result = height
    if output != "Eroded Height":
        scale = max(float(params.get("mask_gain", 8.0)), 0.0)
        result = np.clip(result * scale, 0.0, 1.0)
    return grayscale_rgba(np.nan_to_num(result, nan=0.0, posinf=1.0, neginf=0.0).astype(np.float32))



def _terrain_iterations(params: Mapping[str, Any], context: EvalContext, *, preview_default: int, final_default: int) -> int:
    mode = str(params.get("quality", "Automatic"))
    preview = max(int(params.get("preview_iterations", preview_default)), 0)
    final = max(int(params.get("final_iterations", final_default)), 0)
    selected = preview if mode == "Preview" else final if mode == "Final" else (
        final if context.render_mode == "final" else preview
    )
    if context.render_mode == "interactive":
        return min(selected, 16)
    return selected


def _flow_drops(surface: np.ndarray, boundary: str) -> tuple[list[np.ndarray], list[np.ndarray]]:
    drops: list[np.ndarray] = []
    valids: list[np.ndarray] = []
    for dy, dx in _DIRECTIONS_4:
        neighbour, valid = _neighbour(surface, dy, dx, boundary)
        drop = np.maximum(surface - neighbour, 0.0)
        if boundary == "Closed":
            drop = np.where(valid, drop, 0.0)
        drops.append(drop.astype(np.float32, copy=False))
        valids.append(valid)
    return drops, valids


def _flow_fluxes(
    surface: np.ndarray,
    water: np.ndarray,
    boundary: str,
    flow_strength: float,
    gravity: float,
    viscosity: float,
) -> tuple[list[np.ndarray], np.ndarray, np.ndarray]:
    drops, _valids = _flow_drops(surface, boundary)
    total_drop = np.maximum(sum(drops), 1e-8)
    mobility = np.clip(flow_strength * (1.0 - viscosity), 0.0, 1.0)
    total = np.minimum(water, (total_drop * max(gravity, 0.0) + water * 0.08) * mobility)
    flows = [(drop / total_drop * total).astype(np.float32) for drop in drops]
    incoming = np.zeros_like(water)
    for flow, (dy, dx) in zip(flows, _DIRECTIONS_4):
        incoming += _incoming_shift(flow, dy, dx, boundary)
    return flows, total.astype(np.float32), incoming.astype(np.float32)


def _spatial_variation(context: EvalContext, seed: int) -> np.ndarray:
    y, x = np.mgrid[0:context.height, 0:context.width]
    phase = x.astype(np.float32) * 12.9898 + y.astype(np.float32) * 78.233 + float(seed) * 37.719
    return np.mod(np.sin(phase) * 43758.5453, 1.0).astype(np.float32)



def _terrain_blur(values: np.ndarray, amount: float, boundary: str) -> np.ndarray:
    """Small boundary-aware low-pass used only for drainage routing.

    The authored height is not blurred directly.  A smoother routing surface
    prevents tiny procedural pits from becoming one-pixel drainage basins.
    """
    amount = np.clip(float(amount), 0.0, 1.0)
    if amount <= 1e-8:
        return values.astype(np.float32, copy=False)
    passes = max(1, int(round(1.0 + amount * 4.0)))
    result = values.astype(np.float32, copy=True)
    for _ in range(passes):
        total = result * 4.0
        weight = np.full(result.shape, 4.0, dtype=np.float32)
        for dy, dx in _DIRECTIONS_4:
            neighbour, valid = _neighbour(result, dy, dx, boundary)
            if boundary == "Closed":
                total += np.where(valid, neighbour, 0.0)
                weight += valid.astype(np.float32)
            else:
                total += neighbour
                weight += 1.0
        smooth = total / np.maximum(weight, 1.0)
        result = result * (1.0 - amount) + smooth * amount
    return result.astype(np.float32, copy=False)


def _fluvial_rain_variation(context: EvalContext, seed: int) -> np.ndarray:
    """Low-frequency, periodic rain variation.

    The previous solver used independent random values per pixel, which
    stamped high-frequency noise into every erosion iteration.  This field is
    intentionally broad and seamless, so it changes drainage emphasis without
    creating a noisy erosion texture.
    """
    y, x = np.mgrid[0:context.height, 0:context.width]
    u = (x.astype(np.float32) + 0.5) / max(context.width, 1)
    v = (y.astype(np.float32) + 0.5) / max(context.height, 1)
    phase = float(seed) * 0.137
    value = (
        0.5
        + 0.22 * np.sin((u * 2.0 + phase) * math.tau)
        + 0.18 * np.cos((v * 3.0 - phase * 0.7) * math.tau)
        + 0.10 * np.sin(((u + v) * 4.0 + phase * 0.3) * math.tau)
    )
    return np.clip(value, 0.0, 1.0).astype(np.float32)


def _fluvial_counts(params: Mapping[str, Any], context: EvalContext) -> tuple[int, int]:
    mode = str(params.get("quality", "Automatic"))
    preview_erosion = max(int(params.get("preview_iterations", 12)), 0)
    final_erosion = max(int(params.get("final_iterations", 40)), 0)
    preview_drainage = max(int(params.get("preview_drainage_iterations", 56)), 1)
    final_drainage = max(int(params.get("final_drainage_iterations", 112)), 1)
    if mode == "Preview":
        erosion, drainage = preview_erosion, preview_drainage
    elif mode == "Final":
        erosion, drainage = final_erosion, final_drainage
    elif context.render_mode == "final":
        erosion, drainage = final_erosion, final_drainage
    else:
        erosion, drainage = preview_erosion, preview_drainage
    if context.render_mode == "interactive":
        return min(erosion, 4), min(drainage, 24)
    return min(erosion, 512), min(drainage, 2048)


def _fluvial_feature_radius(context: EvalContext, erosion_scale: float) -> int:
    """Return a resolution-aware drainage sampling radius.

    Erosion Scale is an artistic macro/micro control rather than a raw pixel
    radius.  The radius grows with document resolution so the same graph keeps
    broadly similar valley proportions at 512 px, 2K and export resolutions.
    """
    scale = np.clip(float(erosion_scale), 0.0, 1.0)
    resolution_factor = max(min(context.width, context.height) / 512.0, 0.75)
    reference_radius = 1.0 + scale * 4.0 * resolution_factor
    return max(1, min(32, int(round(reference_radius))))


def _fluvial_route(
    height: np.ndarray,
    boundary: str,
    terrain_smoothing: float,
    depression_handling: float,
    height_scale: float,
    feature_radius: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    route = _terrain_blur(height, terrain_smoothing, boundary)
    radius = max(int(feature_radius), 1)
    drops: list[np.ndarray] = []
    neighbours: list[np.ndarray] = []
    valids: list[np.ndarray] = []
    for index, (dy, dx) in enumerate(_DIRECTIONS_8):
        neighbour, valid = _neighbour(route, dy * radius, dx * radius, boundary)
        distance = (math.sqrt(2.0) if index >= 4 else 1.0) * radius
        drop = (route - neighbour) / distance
        if boundary == "Closed":
            drop = np.where(valid, drop, -1e9)
        drops.append(drop.astype(np.float32, copy=False))
        neighbours.append(neighbour)
        valids.append(valid)
    stack = np.stack(drops, axis=0)
    target = np.argmax(stack, axis=0).astype(np.int16)
    steepest = np.max(stack, axis=0)

    # A controlled spill direction lets shallow procedural pits join a drainage
    # basin instead of repeatedly eroding in place. Depression Handling 0 keeps
    # genuinely closed basins unchanged.
    pits = steepest <= 1e-8
    if depression_handling > 1e-8:
        neighbour_stack = np.stack(neighbours, axis=0)
        if boundary == "Closed":
            for index, valid in enumerate(valids):
                neighbour_stack[index] = np.where(valid, neighbour_stack[index], np.inf)
        lowest = np.argmin(neighbour_stack, axis=0).astype(np.int16)
        target = np.where(pits, lowest, target).astype(np.int16)
        steepest = np.where(pits, depression_handling * 0.00025 / radius, steepest)

    dx = np.zeros_like(height, dtype=np.float32)
    dy = np.zeros_like(height, dtype=np.float32)
    for index, (oy, ox) in enumerate(_DIRECTIONS_8):
        selected = target == index
        dx[selected] = float(ox)
        dy[selected] = float(oy)
    length = np.sqrt(dx * dx + dy * dy)
    np.divide(dx, length, out=dx, where=length > 1e-8)
    np.divide(dy, length, out=dy, where=length > 1e-8)
    return target, np.maximum(steepest * height_scale, 0.0).astype(np.float32), dx, dy


def _fluvial_accumulation(
    source: np.ndarray,
    target: np.ndarray,
    boundary: str,
    retention: float,
    iterations: int,
) -> np.ndarray:
    accumulation = source.astype(np.float32, copy=True)
    retention = np.clip(float(retention), 0.0, 0.9995)
    # A closed/wrapped drainage loop with high retention can otherwise grow to
    # infinity over many passes.  The display/erosion response is already fully
    # saturated long before this cap, so clamping only removes undefined values.
    max_accumulation = np.float32(1_000_000.0)
    for _ in range(max(iterations, 1)):
        incoming = np.zeros_like(accumulation)
        for index, (dy, dx) in enumerate(_DIRECTIONS_8):
            sent = np.where(target == index, accumulation * retention, 0.0)
            incoming += _incoming_shift(sent, dy, dx, boundary)
        accumulation = np.minimum(source + incoming, max_accumulation)
        accumulation = np.nan_to_num(accumulation, nan=0.0, posinf=max_accumulation, neginf=0.0)
    return accumulation.astype(np.float32, copy=False)


def _fluvial_widen_field(
    channel: np.ndarray,
    boundary: str,
    radius: int,
    widening: float,
    sediment_spread: float,
) -> np.ndarray:
    """Expand channels into smooth, scale-aware valley and floodplain masks.

    A pure maximum dilation creates star-shaped banks and a plain blur makes
    river centres disappear.  Combining a retained channel core, a softened
    local field and a sparse broad ring produces a stable V-to-U valley profile
    without an expensive distance transform.
    """
    widening = np.clip(float(widening), 0.0, 1.0)
    spread = np.clip(float(sediment_spread), 0.0, 1.0)
    if widening <= 1e-8 and spread <= 1e-8:
        return channel.astype(np.float32, copy=False)
    radius = max(int(radius), 1)

    local = channel.astype(np.float32, copy=True)
    for _ in range(min(5, 1 + radius // 2)):
        local = _terrain_blur(local, 0.72, boundary)
    local_profile = np.sqrt(np.clip(local, 0.0, 1.0))

    neighbourhood = [channel]
    for dy, dx in _DIRECTIONS_8:
        neighbour, valid = _neighbour(channel, dy * radius, dx * radius, boundary)
        if boundary == "Closed":
            neighbour = np.where(valid, neighbour, channel)
        neighbourhood.append(neighbour)
    stack = np.stack(neighbourhood, axis=0)
    broad_average = np.mean(stack, axis=0)
    broad_maximum = np.max(stack, axis=0)
    broad_profile = np.sqrt(np.clip(broad_average, 0.0, 1.0)) * 0.65 + broad_maximum * 0.35

    expanded = np.maximum(channel, local_profile * 0.72 + broad_profile * 0.28)
    valley = channel * (1.0 - widening) + expanded * widening
    if spread > 1e-8:
        floodplain = _terrain_blur(valley, 0.45 + 0.40 * spread, boundary)
        floodplain = np.sqrt(np.clip(floodplain, 0.0, 1.0))
        valley = valley * (1.0 - 0.45 * spread) + np.maximum(valley, floodplain * 0.78) * (0.45 * spread)
    return np.clip(valley, 0.0, 1.0).astype(np.float32)


def _fluvial_simulation(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> dict[str, np.ndarray]:
    height = _height(inputs, "Height", context).copy()
    original = height.copy()
    rainfall_mask = _height(inputs, "Rainfall Mask", context, 1.0) if "Rainfall Mask" in inputs else np.ones_like(height)
    hardness = _height(inputs, "Hardness", context, 0.0) if "Hardness" in inputs else np.zeros_like(height)

    erosion_iterations, drainage_iterations = _fluvial_counts(params, context)
    boundary = str(params.get("boundary", "Seamless / Wrap"))
    rainfall = max(float(params.get("rainfall", 0.62)), 0.0)
    rain_variation = np.clip(float(params.get("rain_variation", 0.10)), 0.0, 1.0)
    flow_retention = np.clip(float(params.get("flow_retention", 0.955)), 0.0, 0.9995)
    terrain_smoothing = np.clip(float(params.get("terrain_smoothing", 0.58)), 0.0, 1.0)
    depression_handling = np.clip(float(params.get("depression_handling", 0.45)), 0.0, 1.0)
    duration = max(float(params.get("erosion_duration", 1.10)), 0.0)
    erosion_scale = np.clip(float(params.get("erosion_scale", 0.35)), 0.0, 1.0)
    channel_depth = max(float(params.get("channel_depth", 0.27)), 0.0)
    channel_width = np.clip(float(params.get("channel_width", 0.075)), 0.001, 0.5)
    tributary_density = np.clip(float(params.get("tributary_density", 0.30)), 0.0, 1.0)
    headwater_detail = np.clip(float(params.get("headwater_detail", 0.18)), 0.0, 1.0)
    valley_widening = np.clip(float(params.get("valley_widening", 0.38)), 0.0, 1.0)
    bank_erosion = np.clip(float(params.get("bank_erosion", 0.22)), 0.0, 1.0)
    deposition_amount = np.clip(float(params.get("deposition", 0.14)), 0.0, 1.0)
    sediment_spread = np.clip(float(params.get("sediment_spread", 0.42)), 0.0, 1.0)
    sediment_transport = np.clip(float(params.get("sediment_transport", 0.62)), 0.0, 1.0)
    shape_protection = np.clip(float(params.get("terrain_uplift", 0.08)), 0.0, 1.0)
    bank_stabilisation = np.clip(float(params.get("post_thermal_smoothing", 0.12)), 0.0, 1.0)
    rock_resistance = np.clip(float(params.get("rock_resistance", 0.12)), 0.0, 1.0)
    drainage_exponent = max(float(params.get("drainage_exponent", 1.35)), 0.05)
    slope_exponent = max(float(params.get("slope_exponent", 0.72)), 0.05)
    height_scale = max(float(params.get("height_scale", 1.0)), 1e-6)
    max_erosion_step = max(float(params.get("max_erosion_step", 0.020)), 0.0)
    flow_gain = max(float(params.get("flow_gain", 0.012)), 1e-6)
    seed = int(params.get("seed", 1))
    feature_radius = _fluvial_feature_radius(context, erosion_scale)

    variation = _fluvial_rain_variation(context, seed)
    source = np.clip(rainfall_mask, 0.0, 1.0) * rainfall
    source *= (1.0 - rain_variation) + rain_variation * variation
    source = np.nan_to_num(source, nan=0.0, posinf=1_000_000.0, neginf=0.0).astype(np.float32, copy=False)

    erosion_total = np.zeros_like(height)
    deposition_total = np.zeros_like(height)
    channel_total = np.zeros_like(height)
    wetness = np.zeros_like(height)
    final_accumulation = source.copy()
    final_dx = np.zeros_like(height)
    final_dy = np.zeros_like(height)

    if rainfall <= 1e-12 or duration <= 1e-12:
        erosion_iterations = 0

    cycles = max(erosion_iterations, 1)
    for cycle in range(cycles):
        target, slope, direction_x, direction_y = _fluvial_route(
            height, boundary, terrain_smoothing, depression_handling, height_scale, feature_radius
        )
        accumulation = _fluvial_accumulation(source, target, boundary, flow_retention, drainage_iterations)
        final_accumulation = accumulation
        final_dx = direction_x
        final_dy = direction_y
        if cycle >= erosion_iterations:
            continue

        flow = 1.0 - np.exp(-np.maximum(accumulation, 0.0) * flow_gain)
        threshold = (1.0 - tributary_density) * 0.58 + tributary_density * 0.12
        channel = _smoothstep(threshold, threshold + channel_width, flow)
        slope_normalised = 1.0 - np.exp(-np.maximum(slope, 0.0) * 45.0)
        headwaters = (
            _smoothstep(threshold * 0.35, threshold, flow)
            * (1.0 - channel)
            * slope_normalised
            * headwater_detail
        )
        channel = np.clip(channel + headwaters, 0.0, 1.0)
        widened = _fluvial_widen_field(channel, boundary, feature_radius, valley_widening, sediment_spread)

        step_scale = duration / max(erosion_iterations, 1)
        softness = np.clip(1.0 - hardness, 0.0, 1.0) * (1.0 - rock_resistance)
        incision_profile = channel * (1.0 - 0.35 * valley_widening) + widened * (0.35 * valley_widening)
        incision = (
            step_scale
            * channel_depth
            * np.power(incision_profile, drainage_exponent)
            * np.power(slope_normalised + 0.06, slope_exponent)
            * softness
        )
        bank_mask = np.maximum(widened - channel * 0.30, 0.0)
        bank_cut = (
            step_scale
            * channel_depth
            * bank_erosion
            * bank_mask
            * (0.20 + 0.80 * slope_normalised)
            * softness
        )
        erosion_step = np.minimum(incision + bank_cut, max_erosion_step)
        erosion_step = np.minimum(erosion_step, np.maximum(height, 0.0))

        # High transport carries sediment farther before settling; low transport
        # creates broader near-channel deposits. This is an artistic form of a
        # sediment-capacity response rather than a separate fluid simulation.
        low_energy = np.power(np.clip(1.0 - slope_normalised, 0.0, 1.0), 1.2 + 3.8 * sediment_transport)
        deposit_field = widened * (1.0 - 0.35 * sediment_transport) + np.maximum(widened - channel, 0.0) * (0.35 * sediment_transport)
        deposition_step = (
            step_scale
            * deposition_amount
            * deposit_field
            * low_energy
            * (0.10 + 0.90 * flow)
            * softness
        )
        deposition_step = np.minimum(deposition_step, max_erosion_step * 0.6)

        height = np.clip(height - erosion_step + deposition_step, 0.0, 1.0)
        if bank_stabilisation > 1e-8:
            smooth = _terrain_blur(height, 0.45, boundary)
            active = (slope_normalised > 0.24) & (widened > 0.02)
            thermal_mix = bank_stabilisation * softness * (0.25 + 0.75 * widened)
            height = np.where(active, height * (1.0 - thermal_mix) + smooth * thermal_mix, height)
        if shape_protection > 1e-8:
            preserve = shape_protection * 0.25 / max(erosion_iterations, 1)
            height = np.clip(height + (original - height) * preserve * (1.0 - hardness), 0.0, 1.0)

        height = np.nan_to_num(height, nan=0.0, posinf=1.0, neginf=0.0)
        erosion_step = np.nan_to_num(erosion_step, nan=0.0, posinf=max_erosion_step, neginf=0.0)
        deposition_step = np.nan_to_num(deposition_step, nan=0.0, posinf=max_erosion_step, neginf=0.0)
        erosion_total += erosion_step
        deposition_total += deposition_step
        channel_total = np.maximum(channel_total, channel)
        wetness = np.maximum(wetness * 0.98, flow)

    direction = np.empty((context.height, context.width, 4), dtype=np.float32)
    direction[..., 0] = final_dx * 0.5 + 0.5
    direction[..., 1] = final_dy * 0.5 + 0.5
    direction[..., 2] = 0.5
    direction[..., 3] = 1.0
    flow_display = 1.0 - np.exp(-np.maximum(final_accumulation, 0.0) * flow_gain)
    sediment = np.maximum(erosion_total - deposition_total, 0.0)
    runoff = np.clip(flow_display * rainfall_mask, 0.0, 1.0)

    fields = {
        "Eroded Height": height,
        "Erosion": erosion_total,
        "Deposition": deposition_total,
        "Flow Accumulation": flow_display,
        "Channel Mask": channel_total,
        "Water": runoff,
        "Sediment": sediment,
        "Wetness": wetness,
    }
    for name, values in fields.items():
        fields[name] = np.nan_to_num(values, nan=0.0, posinf=1.0, neginf=0.0).astype(np.float32)
    direction = np.nan_to_num(direction, nan=0.5, posinf=1.0, neginf=0.0).astype(np.float32)
    fields["Flow Direction"] = direction
    return fields

def eval_hydraulic_erosion(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    fields = _fluvial_simulation(inputs, params, context)
    output = str(params.get("preview_output", "Eroded Height"))
    result = fields.get(output, fields["Eroded Height"])
    if result.ndim == 3:
        return result.astype(np.float32, copy=False)
    if output != "Eroded Height":
        gain_name = {
            "Flow Accumulation": "flow_display_gain",
            "Channel Mask": "channel_gain",
            "Water": "water_gain",
            "Sediment": "sediment_gain",
            "Wetness": "wetness_gain",
        }.get(output, "mask_gain")
        result = np.clip(result * max(float(params.get(gain_name, 1.0)), 0.0), 0.0, 1.0)
    result = np.nan_to_num(result, nan=0.0, posinf=1.0, neginf=0.0)
    return grayscale_rgba(result.astype(np.float32))

def eval_flow_direction(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    height = _height(inputs, "Height", context)
    strength = max(float(params.get("strength", 1.0)), 0.0)
    gx = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) * 0.5 * strength
    gy = (np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)) * 0.5 * strength
    length = np.sqrt(gx * gx + gy * gy)
    dx = np.zeros_like(gx, dtype=np.float32)
    dy = np.zeros_like(gy, dtype=np.float32)
    np.divide(-gx, length, out=dx, where=length > 1e-8)
    np.divide(-gy, length, out=dy, where=length > 1e-8)
    out = np.empty((context.height, context.width, 4), dtype=np.float32)
    out[..., 0] = dx * 0.5 + 0.5
    out[..., 1] = dy * 0.5 + 0.5
    out[..., 2] = 0.5
    out[..., 3] = 1.0
    return out


def eval_flow_accumulation(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    height = _height(inputs, "Height", context)
    source = _height(inputs, "Rainfall Mask", context, 1.0) if "Rainfall Mask" in inputs else np.ones_like(height)
    boundary = str(params.get("boundary", "Seamless / Wrap"))
    iterations = min(_terrain_iterations(params, context, preview_default=32, final_default=128), 1000)
    retention = np.clip(float(params.get("retention", 0.94)), 0.0, 0.999)
    min_slope = max(float(params.get("minimum_slope", 0.0001)), 0.0)
    accum = source.astype(np.float32).copy()
    directions = _DIRECTIONS_8 if str(params.get("neighbourhood", "8 Neighbours")) == "8 Neighbours" else _DIRECTIONS_4
    for _ in range(iterations):
        diffs = []
        valids = []
        for direction_index, (dy, dx) in enumerate(directions):
            neighbour, valid = _neighbour(height, dy, dx, boundary)
            distance = math.sqrt(2.0) if direction_index >= 4 else 1.0
            drop = (height - neighbour) / distance
            if boundary == "Closed":
                drop = np.where(valid, drop, -1e9)
            diffs.append(drop)
            valids.append(valid)
        stack = np.stack(diffs, axis=0)
        target = np.argmax(stack, axis=0)
        steepest = np.max(stack, axis=0)
        sent = np.where(steepest > min_slope, accum * retention, 0.0)
        incoming = np.zeros_like(accum)
        for index, (dy, dx) in enumerate(directions):
            incoming += _incoming_shift(np.where(target == index, sent, 0.0), dy, dx, boundary)
        accum = source + incoming
    gain = max(float(params.get("gain", 1.0)), 0.001)
    value = 1.0 - np.exp(-np.maximum(accum - source, 0.0) * gain)
    value = np.clip(value, 0.0, 1.0)
    if bool(params.get("invert", False)):
        value = 1.0 - value
    return grayscale_rgba(value.astype(np.float32))

def register_terrain_nodes(registry: NodeRegistry) -> None:
    f = ParameterSpec
    definitions = [
        NodeDefinition(
            "terrain.slope", "Slope", "Terrain/Analysis", eval_slope,
            inputs=("Height",),
            parameters=(
                f("height_scale", "Height Scale", "float", 1.0, 0.001, 100.0, 0.01, animatable=True),
                f("contrast", "Contrast", "float", 1.0, 0.05, 8.0, 0.05, animatable=True),
                f("invert", "Invert", "bool", False),
            ),
            description="Measure terrain steepness as a greyscale slope mask.", accent=_TERRAIN_ACCENT,
            tags=("terrain", "slope", "mask", "steepness"), output_format="r16f", gpu_kernel="terrain_slope.wgsl",
            input_kinds=(("Height", "grayscale"),), output_kinds=(("Image", "grayscale"),), default_image_kind="grayscale",
        ),
        NodeDefinition(
            "terrain.curvature", "Height Curvature", "Terrain/Analysis", eval_curvature,
            inputs=("Height",),
            parameters=(
                f("mode", "Mode", "enum", "Signed", options=("Signed", "Convex", "Concave", "Absolute")),
                f("strength", "Strength", "float", 4.0, 0.01, 256.0, 0.1, animatable=True),
                f("contrast", "Contrast", "float", 1.0, 0.05, 8.0, 0.05, animatable=True),
                f("invert", "Invert", "bool", False),
            ),
            description="Extract convex ridges, concave valleys or signed curvature directly from a height field. Signed flat areas are exactly 50% grey.", accent=_TERRAIN_ACCENT,
            tags=("terrain", "height curvature", "curvature", "convex", "concave", "mask"), output_format="r16f", gpu_kernel="terrain_curvature.wgsl",
            input_kinds=(("Height", "grayscale"),), output_kinds=(("Image", "grayscale"),), default_image_kind="grayscale",
        ),
        NodeDefinition(
            "terrain.terrace", "Terrace", "Terrain/Shaping", eval_terrace,
            inputs=("Height", "Mask", "Variation"),
            parameters=(
                f("steps", "Terrace Count", "int", 8, 2, 128, 1, animatable=True, group="Terrace Layout", group_order=10, slider_maximum=32, description="Number of distinct elevation shelves."),
                f("offset", "Terrace Offset", "float", 0.0, -128.0, 128.0, 0.01, animatable=True, group="Terrace Layout", group_order=10, slider_minimum=-4.0, slider_maximum=4.0, description="Slides the terrace pattern vertically in terrace-step units."),
                f("spacing_variation", "Step Spacing Variation", "float", 0.18, 0.0, 1.0, 0.01, animatable=True, group="Terrace Layout", group_order=10, description="Varies the vertical distance between successive shelves. Change the seed for a different arrangement."),
                f("height_distribution", "Elevation Distribution", "float", 0.0, -1.0, 1.0, 0.01, animatable=True, group="Terrace Layout", group_order=10, description="Negative values concentrate steps in lowlands; positive values concentrate them toward peaks."),
                f("seed", "Layout Seed", "int", 1, 0, 999999, 1, animatable=True, slider_maximum=1000, fine_step=1, coarse_step=10, group="Terrace Layout", group_order=10),

                f("smoothness", "Edge Smoothness", "float", 0.16, 0.0, 1.0, 0.01, animatable=True, group="Terrace Profile", group_order=20, description="Widens the transition between one shelf and the next."),
                f("plateau_slope", "Plateau Slope", "float", 0.06, 0.0, 1.0, 0.01, animatable=True, group="Terrace Profile", group_order=20, description="Adds a gentle grade across shelves so they do not read as perfectly flat threshold bands."),
                f("strength", "Terrace Strength", "float", 1.0, 0.0, 1.0, 0.01, animatable=True, group="Terrace Profile", group_order=20),

                f("boundary_breakup", "Boundary Breakup", "float", 0.10, 0.0, 1.5, 0.01, animatable=True, slider_maximum=1.0, group="Shape Breakup", group_order=30, description="Procedurally pushes terrace boundaries forward and backward to avoid perfect contour rings."),
                f("breakup_scale", "Breakup Scale", "float", 4.0, 1.0, 64.0, 1.0, animatable=True, fine_step=1.0, coarse_step=4.0, group="Shape Breakup", group_order=30, description="Size of the broad procedural breakup pattern. Integer scales remain seamless."),
                f("variation_influence", "Variation Input Influence", "float", 0.5, 0.0, 2.0, 0.01, animatable=True, slider_maximum=1.0, group="Shape Breakup", group_order=30, description="Uses the optional Variation input to locally offset terrace boundaries. Mid-grey is neutral."),

                f("invert_mask", "Invert Mask", "bool", False, group="Mask", group_order=40, description="Black normally preserves the source height and white applies the terrace effect."),
            ),
            description="Build irregular geological shelves with non-uniform elevation spacing, sloped plateaus, maskable coverage and controllable boundary breakup.", accent=_TERRAIN_ACCENT,
            tags=("terrain", "terrace", "steps", "plateau", "strata", "mask", "breakup"), output_format="r16f", gpu_kernel="terrain_terrace.wgsl",
            input_kinds=(("Height", "grayscale"), ("Mask", "grayscale"), ("Variation", "grayscale")), output_kinds=(("Image", "grayscale"),), default_image_kind="grayscale",
        ),
        NodeDefinition(
            "terrain.height_combine", "Height Combine", "Terrain/Combine", eval_height_combine,
            inputs=("A", "B", "Mask"),
            parameters=(
                f("mode", "Mode", "enum", "Maximum", options=("Add", "Subtract", "Multiply", "Maximum", "Minimum", "Average", "Difference")),
                f("opacity", "Opacity", "float", 1.0, 0.0, 1.0, 0.01, animatable=True),
                f("clamp", "Clamp 0–1", "bool", True),
            ),
            description="Combine two heightfields with terrain-oriented maths and an optional mask.", accent=_TERRAIN_ACCENT,
            tags=("terrain", "height", "combine", "maximum", "mask"), output_format="r16f", gpu_kernel="terrain_height_combine.wgsl",
            input_kinds=(("A", "grayscale"), ("B", "grayscale"), ("Mask", "grayscale")), output_kinds=(("Image", "grayscale"),), default_image_kind="grayscale",
        ),
        NodeDefinition(
            "terrain.height_blend", "Height Blend", "Terrain/Combine", eval_height_blend,
            inputs=("Base", "Layer", "Mask"),
            parameters=(
                f("height_offset", "Layer Height Offset", "float", 0.0, -1.0, 1.0, 0.01, animatable=True),
                f("transition", "Transition Width", "float", 0.1, 0.001, 1.0, 0.001, animatable=True),
                f("bias", "Blend Bias", "float", 0.0, -1.0, 1.0, 0.01, animatable=True),
                f("opacity", "Opacity", "float", 1.0, 0.0, 1.0, 0.01, animatable=True),
            ),
            description="Blend a terrain layer according to relative height rather than plain opacity alone.", accent=_TERRAIN_ACCENT,
            tags=("terrain", "height blend", "layer", "strata"), output_format="r16f", gpu_kernel="terrain_height_blend.wgsl",
            input_kinds=(("Base", "grayscale"), ("Layer", "grayscale"), ("Mask", "grayscale")), output_kinds=(("Image", "grayscale"),), default_image_kind="grayscale",
        ),
        NodeDefinition(
            "terrain.flow_direction", "Flow Direction", "Terrain/Analysis", eval_flow_direction,
            inputs=("Height",),
            parameters=(
                f("strength", "Direction Strength", "float", 1.0, 0.001, 100.0, 0.01, animatable=True),
            ),
            description="Encode the steepest downhill direction as a blue vector field.", accent="#4f86b5",
            tags=("terrain", "flow", "direction", "vector", "river"), output_format="rgba16f", gpu_kernel="terrain_flow_direction.wgsl",
            input_kinds=(("Height", "grayscale"),), output_kinds=(("Vector", "vector"),), output_name="Vector", default_image_kind="vector",
        ),
        NodeDefinition(
            "terrain.flow_accumulation", "Flow Accumulation", "Terrain/Analysis", eval_flow_accumulation,
            inputs=("Height", "Rainfall Mask"),
            parameters=(
                f("quality", "Iteration Quality", "enum", "Automatic", options=("Automatic", "Preview", "Final")),
                f("preview_iterations", "Preview Iterations", "int", 32, 1, 500, 1),
                f("final_iterations", "Final Iterations", "int", 128, 1, 2000, 1),
                f("retention", "Upstream Retention", "float", 0.94, 0.0, 0.999, 0.001, animatable=True),
                f("minimum_slope", "Minimum Slope", "float", 0.0001, 0.0, 0.1, 0.0001, animatable=True),
                f("neighbourhood", "Neighbourhood", "enum", "8 Neighbours", options=("4 Neighbours", "8 Neighbours")),
                f("boundary", "Boundary", "enum", "Seamless / Wrap", options=("Seamless / Wrap", "Closed", "Drain")),
                f("gain", "Display Gain", "float", 1.0, 0.001, 100.0, 0.01, animatable=True),
                f("invert", "Invert", "bool", False),
            ),
            description="Accumulate upstream drainage to reveal tributaries, channels and river catchments.", accent="#4f86b5",
            tags=("terrain", "flow", "accumulation", "drainage", "river", "catchment"), output_format="r16f", gpu_kernel="terrain_flow_accum_step.wgsl",
            input_kinds=(("Height", "grayscale"), ("Rainfall Mask", "grayscale")), output_kinds=(("Image", "grayscale"),), default_image_kind="grayscale",
        ),
        NodeDefinition(
            "terrain.hydraulic_erosion", "Fluvial Erosion", "Terrain/Erosion", eval_hydraulic_erosion,
            inputs=("Height", "Rainfall Mask", "Hardness"),
            parameters=(
                f("erosion_duration", "Erosion Duration", "float", 1.10, 0.0, 8.0, 0.01, animatable=True, group="Character", group_order=10, slider_maximum=3.0, description="Overall geological time. Raise this before reaching for the advanced solver controls."),
                f("erosion_scale", "Erosion Scale", "float", 0.35, 0.0, 1.0, 0.01, animatable=True, group="Character", group_order=10, description="Moves the drainage solve from fine gullies toward broader valleys while remaining resolution-aware."),
                f("channel_depth", "Downcutting", "float", 0.27, 0.0, 2.0, 0.01, animatable=True, group="Character", group_order=10, slider_maximum=0.8, description="How strongly established rivers cut into bedrock."),
                f("valley_widening", "Channel Widening", "float", 0.38, 0.0, 1.0, 0.01, animatable=True, group="Character", group_order=10, description="Expands narrow channels into valleys and floodplains without changing the drainage hierarchy."),
                f("tributary_density", "Tributary Density", "float", 0.30, 0.0, 1.0, 0.01, animatable=True, group="Character", group_order=10, description="Lower values keep only major rivers; higher values reveal smaller tributaries."),
                f("terrain_uplift", "Shape Protection", "float", 0.08, 0.0, 1.0, 0.01, animatable=True, group="Character", group_order=10, description="Gently preserves the source macroform while allowing channels and deposits to develop."),

                f("rainfall", "Rainfall", "float", 0.62, 0.0, 4.0, 0.01, animatable=True, group="Water & Drainage", group_order=20, slider_maximum=2.0),
                f("rain_variation", "Rain Variation", "float", 0.10, 0.0, 1.0, 0.01, animatable=True, group="Water & Drainage", group_order=20, description="Broad terrain-wide variation; no per-pixel rain noise is injected."),
                f("flow_retention", "Flow Retention", "float", 0.955, 0.0, 0.9995, 0.0005, animatable=True, group="Water & Drainage", group_order=20, slider_minimum=0.80, description="How much upstream water survives each drainage step. High values build long connected river systems."),
                f("terrain_smoothing", "Drainage Smoothing", "float", 0.58, 0.0, 1.0, 0.01, animatable=True, group="Water & Drainage", group_order=20, description="Smooths only the hidden routing surface so tiny pits do not become isolated basins."),
                f("depression_handling", "Depression Handling", "float", 0.45, 0.0, 1.0, 0.01, animatable=True, group="Water & Drainage", group_order=20, description="Lets shallow basins find a controlled spill direction. Set to zero to preserve closed depressions."),

                f("channel_width", "Channel Softness", "float", 0.075, 0.001, 0.5, 0.001, animatable=True, group="Sediment & Banks", group_order=30, slider_maximum=0.25, description="Softens the transition between active channels and surrounding terrain."),
                f("headwater_detail", "Headwater Detail", "float", 0.18, 0.0, 1.0, 0.01, animatable=True, group="Sediment & Banks", group_order=30, description="Adds fine incisions on steep upper slopes without filling the whole terrain with noise."),
                f("bank_erosion", "Bank Erosion", "float", 0.22, 0.0, 1.0, 0.01, animatable=True, group="Sediment & Banks", group_order=30, description="Controls lateral cutting along the widened channel field."),
                f("deposition", "Deposition", "float", 0.14, 0.0, 1.0, 0.01, animatable=True, group="Sediment & Banks", group_order=30, description="Builds alluvial material where flow loses energy."),
                f("sediment_transport", "Sediment Transport", "float", 0.62, 0.0, 1.0, 0.01, animatable=True, group="Sediment & Banks", group_order=30, description="Higher values carry sediment farther before it settles; lower values deposit nearer the source."),
                f("sediment_spread", "Sediment Spread", "float", 0.42, 0.0, 1.0, 0.01, animatable=True, group="Sediment & Banks", group_order=30, description="Broadens valley-floor and floodplain deposition."),
                f("post_thermal_smoothing", "Bank Stabilisation", "float", 0.12, 0.0, 1.0, 0.01, animatable=True, group="Sediment & Banks", group_order=30, description="Applies a restrained talus-like relaxation only around active valleys and steep banks."),

                f("rock_resistance", "Rock Resistance", "float", 0.12, 0.0, 1.0, 0.01, animatable=True, group="Material", group_order=40, description="Global bedrock resistance. The Hardness input can still vary resistance spatially."),
                f("height_scale", "Terrain Height Scale", "float", 1.0, 0.001, 100.0, 0.01, animatable=True, group="Material", group_order=40, slider_maximum=8.0, description="Interprets the vertical scale of the heightfield when measuring slopes."),

                f("quality", "Iteration Quality", "enum", "Automatic", options=("Automatic", "Preview", "Final"), group="Quality", group_order=80, description="Automatic uses Preview settings in live views and Final settings for export. Slider drags use a lightweight draft then resolve exactly on release."),
                f("preview_iterations", "Preview Erosion Passes", "int", 12, 0, 128, 1, group="Quality", group_order=80),
                f("final_iterations", "Final Erosion Passes", "int", 40, 0, 256, 1, group="Quality", group_order=80),
                f("preview_drainage_iterations", "Preview Drainage Passes", "int", 56, 1, 512, 1, group="Quality", group_order=80),
                f("final_drainage_iterations", "Final Drainage Passes", "int", 112, 1, 1024, 1, group="Quality", group_order=80),

                f("drainage_exponent", "Drainage Response", "float", 1.35, 0.05, 4.0, 0.01, animatable=True, group="Advanced", group_order=90),
                f("slope_exponent", "Slope Response", "float", 0.72, 0.05, 4.0, 0.01, animatable=True, group="Advanced", group_order=90),
                f("max_erosion_step", "Maximum Erosion / Pass", "float", 0.020, 0.00001, 0.25, 0.0001, animatable=True, group="Advanced", group_order=90, slider_maximum=0.08, description="Safety limit for a single solve pass; normally leave this at its default."),
                f("flow_gain", "Flow Response", "float", 0.012, 0.00001, 1.0, 0.0001, animatable=True, group="Advanced", group_order=90, slider_maximum=0.08),
                f("boundary", "Boundary", "enum", "Seamless / Wrap", options=("Seamless / Wrap", "Closed", "Drain"), group="Advanced", group_order=90),
                f("seed", "Rain Seed", "int", 1, 0, 999999, 1, animatable=True, slider_maximum=1000, fine_step=1, coarse_step=10, group="Advanced", group_order=90),

                f("mask_gain", "Erosion / Deposition Gain", "float", 8.0, 0.01, 512.0, 0.1, animatable=True, group="Outputs", group_order=100),
                f("flow_display_gain", "Flow Display Gain", "float", 1.0, 0.01, 32.0, 0.01, animatable=True, group="Outputs", group_order=100),
                f("channel_gain", "Channel Display Gain", "float", 1.0, 0.01, 32.0, 0.01, animatable=True, group="Outputs", group_order=100),
                f("water_gain", "Water Gain", "float", 1.0, 0.01, 64.0, 0.01, animatable=True, group="Outputs", group_order=100),
                f("sediment_gain", "Sediment Gain", "float", 8.0, 0.01, 512.0, 0.1, animatable=True, group="Outputs", group_order=100),
                f("wetness_gain", "Wetness Gain", "float", 1.0, 0.01, 64.0, 0.01, animatable=True, group="Outputs", group_order=100),
                f("preview_output", "Preview Output", "enum", "Eroded Height", options=("Eroded Height", "Erosion", "Deposition", "Flow Accumulation", "Channel Mask", "Water", "Sediment", "Wetness", "Flow Direction"), group="Outputs", group_order=100),
            ),
            description="Resolution-aware stream-power erosion with connected drainage, controllable valley scale, bank relaxation and sediment transport. White Hardness protects terrain.", accent="#477e9f",
            tags=("terrain", "erosion", "fluvial", "hydraulic", "river", "drainage", "valley", "channel"), output_format="r16f",
            outputs=("Eroded Height", "Erosion", "Deposition", "Flow Accumulation", "Channel Mask", "Water", "Sediment", "Wetness", "Flow Direction"), output_name="Eroded Height",
            named_output_parameter="preview_output", named_output_values=(("Eroded Height", "Eroded Height"), ("Erosion", "Erosion"), ("Deposition", "Deposition"), ("Flow Accumulation", "Flow Accumulation"), ("Channel Mask", "Channel Mask"), ("Water", "Water"), ("Sediment", "Sediment"), ("Wetness", "Wetness"), ("Flow Direction", "Flow Direction")),
            gpu_kernel="terrain_fluvial_erode.wgsl",
            input_kinds=(("Height", "grayscale"), ("Rainfall Mask", "grayscale"), ("Hardness", "grayscale")),
            output_kinds=(("Eroded Height", "grayscale"), ("Erosion", "grayscale"), ("Deposition", "grayscale"), ("Flow Accumulation", "grayscale"), ("Channel Mask", "grayscale"), ("Water", "grayscale"), ("Sediment", "grayscale"), ("Wetness", "grayscale"), ("Flow Direction", "vector")),
            default_image_kind="grayscale",
        ),
        NodeDefinition(
            "terrain.thermal_erosion", "Thermal Erosion", "Terrain/Erosion", eval_thermal_erosion,
            inputs=("Height", "Hardness"),
            parameters=(
                f("talus_angle", "Repose Angle", "float", 34.0, 0.0, 89.0, 0.1, animatable=True, fine_step=0.5, coarse_step=5.0, unit="degrees", group="Character", group_order=10, description="The stable slope angle of loose material. Natural talus commonly begins around the mid-30-degree range."),
                f("erosion_strength", "Weathering", "float", 0.42, 0.0, 1.0, 0.01, animatable=True, group="Character", group_order=10, description="How readily unstable rock is converted into movable talus."),
                f("talus_mobility", "Talus Mobility", "float", 0.65, 0.0, 1.0, 0.01, animatable=True, group="Character", group_order=10, description="How freely loose material spreads across all available downslope directions."),
                f("shape_protection", "Shape Protection", "float", 0.08, 0.0, 1.0, 0.01, animatable=True, group="Character", group_order=10, description="Preserves broad source forms while still allowing cliffs and scree slopes to relax."),
                f("height_scale", "Terrain Height Scale", "float", 1.0, 0.001, 100.0, 0.01, animatable=True, group="Character", group_order=10, slider_maximum=8.0),

                f("rock_resistance", "Rock Resistance", "float", 0.12, 0.0, 1.0, 0.01, animatable=True, group="Material", group_order=20, description="Global resistance to weathering. The Hardness input can vary this spatially."),
                f("fracture_strength", "Fracture Variation", "float", 0.16, 0.0, 1.0, 0.01, animatable=True, group="Material", group_order=20, description="Breaks up uniform talus bands using a terrain-anchored weathering pattern."),
                f("fracture_scale", "Fracture Scale", "float", 0.35, 0.0, 1.0, 0.01, animatable=True, group="Material", group_order=20),
                f("seed", "Fracture Seed", "int", 1, 0, 999999, 1, animatable=True, slider_maximum=1000, fine_step=1, coarse_step=10, group="Material", group_order=20),

                f("quality", "Iteration Quality", "enum", "Automatic", options=("Automatic", "Preview", "Final"), group="Quality", group_order=80, description="Automatic uses Preview settings in live views and Final settings for export. Slider drags use a lightweight draft then resolve exactly on release."),
                f("preview_iterations", "Preview Iterations", "int", 28, 0, 500, 1, group="Quality", group_order=80),
                f("final_iterations", "Final Iterations", "int", 140, 0, 2000, 1, group="Quality", group_order=80),
                f("max_transfer", "Talus Step Limit", "float", 0.025, 0.00001, 0.5, 0.0001, animatable=True, group="Advanced", group_order=90, slider_maximum=0.10, description="Caps material moved in one iteration to keep steep terrain stable."),
                f("neighbourhood", "Neighbourhood", "enum", "8 Neighbours", options=("4 Neighbours", "8 Neighbours"), group="Advanced", group_order=90),
                f("boundary", "Boundary", "enum", "Seamless / Wrap", options=("Seamless / Wrap", "Closed", "Drain"), group="Advanced", group_order=90),

                f("mask_gain", "Mask Gain", "float", 8.0, 0.01, 512.0, 0.1, animatable=True, group="Outputs", group_order=100),
                f("preview_output", "Preview Output", "enum", "Eroded Height", options=("Eroded Height", "Erosion", "Deposition"), group="Outputs", group_order=100),
            ),
            description="Multi-direction talus and weathering erosion with repose-angle control, terrain-anchored fracture variation and natural scree deposition. White Hardness protects terrain.", accent="#9a7a4e",
            tags=("terrain", "erosion", "thermal", "talus", "deposition", "scree"), output_format="r16f",
            outputs=("Eroded Height", "Erosion", "Deposition"), output_name="Eroded Height",
            named_output_parameter="preview_output", named_output_values=(("Eroded Height", "Eroded Height"), ("Erosion", "Erosion"), ("Deposition", "Deposition")),
            gpu_kernel="terrain_thermal_step.wgsl",
            input_kinds=(("Height", "grayscale"), ("Hardness", "grayscale")),
            output_kinds=(("Eroded Height", "grayscale"), ("Erosion", "grayscale"), ("Deposition", "grayscale")),
            default_image_kind="grayscale",
        ),
    ]
    for definition in definitions:
        registry.register(definition)
