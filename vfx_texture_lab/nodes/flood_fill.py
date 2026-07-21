from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Mapping

import numpy as np

from .base import EvalContext, ImageArray, NodeDefinition, ParameterSpec
from .image_ops import empty_image, ensure_rgba, grayscale_rgba, luminance, relative_pixel_area, parse_hex_color
from .registry import NodeRegistry

_PACK_SCALE = np.float32(16777215.0)
_PACK_BASE = 4096
_PACK_MAX = 4095
_FLOOD_ACCENT = "#4f9f88"


def _input(inputs: Mapping[str, ImageArray], name: str, context: EvalContext, value: float = 0.0) -> ImageArray:
    return ensure_rgba(inputs.get(name, empty_image(context, value=value)), context)


def _union_find_create() -> tuple[list[int], list[int]]:
    return [], []


def _make_set(parent: list[int], rank: list[int]) -> int:
    index = len(parent)
    parent.append(index)
    rank.append(0)
    return index


def _find(parent: list[int], value: int) -> int:
    root = value
    while parent[root] != root:
        root = parent[root]
    while parent[value] != value:
        following = parent[value]
        parent[value] = root
        value = following
    return root


def _union(parent: list[int], rank: list[int], first: int, second: int) -> None:
    first_root = _find(parent, first)
    second_root = _find(parent, second)
    if first_root == second_root:
        return
    if rank[first_root] < rank[second_root]:
        first_root, second_root = second_root, first_root
    parent[second_root] = first_root
    if rank[first_root] == rank[second_root]:
        rank[first_root] += 1


def _row_runs(row: np.ndarray) -> list[tuple[int, int]]:
    padded = np.concatenate((np.array([False]), row.astype(bool, copy=False), np.array([False])))
    transitions = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(start), int(end)) for start, end in transitions.reshape(-1, 2)]


def _runs_overlap(first: tuple[int, int, int], second: tuple[int, int, int], diagonal: bool) -> bool:
    first_start, first_end, _ = first
    second_start, second_end, _ = second
    margin = 1 if diagonal else 0
    return first_start < second_end + margin and second_start < first_end + margin


def _connect_rows(
    parent: list[int],
    rank: list[int],
    previous: list[tuple[int, int, int]],
    current: list[tuple[int, int, int]],
    *,
    diagonal: bool,
) -> None:
    previous_index = 0
    current_index = 0
    margin = 1 if diagonal else 0
    while previous_index < len(previous) and current_index < len(current):
        previous_run = previous[previous_index]
        current_run = current[current_index]
        previous_start, previous_end, previous_label = previous_run
        current_start, current_end, current_label = current_run
        if previous_end + margin <= current_start:
            previous_index += 1
            continue
        if current_end + margin <= previous_start:
            current_index += 1
            continue
        _union(parent, rank, previous_label, current_label)
        if previous_end < current_end:
            previous_index += 1
        else:
            current_index += 1


def _circular_interval(occupied: np.ndarray) -> tuple[int, int, float]:
    """Return the shortest wrapped pixel interval covering occupied cells.

    The start is a pixel index, length is measured in pixels, and centre is in
    pixel-edge coordinates so dividing it by the axis size yields the same UV
    convention as ordinary non-wrapped bounding boxes.
    """
    occupied = np.asarray(occupied, dtype=bool)
    axis_size = int(occupied.size)
    indices = np.flatnonzero(occupied)
    if axis_size <= 0 or indices.size == 0:
        return 0, 0, 0.0
    if indices.size == axis_size:
        return 0, axis_size, axis_size * 0.5
    following = np.roll(indices, -1)
    gaps = (following - indices - 1) % axis_size
    gap_index = int(np.argmax(gaps))
    largest_gap = int(gaps[gap_index])
    start = int(following[gap_index] % axis_size)
    length = axis_size - largest_gap
    centre = float((start + length * 0.5) % axis_size)
    return start, length, centre


def _wrapped_uv_delta(coordinate: np.ndarray, centre: np.ndarray) -> np.ndarray:
    """Shortest signed UV delta on a repeating 0..1 axis."""
    return np.mod(coordinate - centre + 0.5, 1.0) - 0.5


def _connected_components(
    mask: np.ndarray,
    *,
    diagonal: bool,
    wrap_x: bool,
    wrap_y: bool,
    minimum_pixels: int,
) -> tuple[np.ndarray, list[dict[str, int | float | bool]]]:
    height, width = mask.shape
    parent, rank = _union_find_create()
    rows: list[list[tuple[int, int, int]]] = []
    all_runs: list[tuple[int, int, int, int]] = []

    previous: list[tuple[int, int, int]] = []
    for y in range(height):
        current: list[tuple[int, int, int]] = []
        for start, end in _row_runs(mask[y]):
            label = _make_set(parent, rank)
            current.append((start, end, label))
            all_runs.append((y, start, end, label))
        _connect_rows(parent, rank, previous, current, diagonal=diagonal)
        if wrap_x and current and current[0][0] == 0 and current[-1][1] == width:
            _union(parent, rank, current[0][2], current[-1][2])
        if wrap_x and diagonal and previous and current:
            if current[0][0] == 0 and previous[-1][1] == width:
                _union(parent, rank, current[0][2], previous[-1][2])
            if current[-1][1] == width and previous[0][0] == 0:
                _union(parent, rank, current[-1][2], previous[0][2])
        rows.append(current)
        previous = current

    if wrap_y and height > 1 and rows:
        _connect_rows(parent, rank, rows[-1], rows[0], diagonal=diagonal)
        if wrap_x and diagonal and rows[-1] and rows[0]:
            if rows[0][0][0] == 0 and rows[-1][-1][1] == width:
                _union(parent, rank, rows[0][0][2], rows[-1][-1][2])
            if rows[0][-1][1] == width and rows[-1][0][0] == 0:
                _union(parent, rank, rows[0][-1][2], rows[-1][0][2])

    aggregates: dict[int, dict[str, int | float | bool]] = {}
    for y, start, end, label in all_runs:
        root = _find(parent, label)
        component = aggregates.get(root)
        if component is None:
            component = {
                "root": root,
                "min_x": start,
                "max_x": end - 1,
                "min_y": y,
                "max_y": y,
                "pixels": end - start,
                "touch_left": start == 0,
                "touch_right": end == width,
                "touch_top": y == 0,
                "touch_bottom": y == height - 1,
            }
            aggregates[root] = component
        else:
            component["min_x"] = min(int(component["min_x"]), start)
            component["max_x"] = max(int(component["max_x"]), end - 1)
            component["min_y"] = min(int(component["min_y"]), y)
            component["max_y"] = max(int(component["max_y"]), y)
            component["pixels"] = int(component["pixels"]) + end - start
            component["touch_left"] = bool(component["touch_left"]) or start == 0
            component["touch_right"] = bool(component["touch_right"]) or end == width
            component["touch_top"] = bool(component["touch_top"]) or y == 0
            component["touch_bottom"] = bool(component["touch_bottom"]) or y == height - 1

    seam_x_roots = {
        root for root, component in aggregates.items()
        if wrap_x and bool(component["touch_left"]) and bool(component["touch_right"])
    }
    seam_y_roots = {
        root for root, component in aggregates.items()
        if wrap_y and bool(component["touch_top"]) and bool(component["touch_bottom"])
    }
    occupied_x = {root: np.zeros(width, dtype=bool) for root in seam_x_roots}
    occupied_y = {root: np.zeros(height, dtype=bool) for root in seam_y_roots}
    if occupied_x or occupied_y:
        for y, start, end, label in all_runs:
            root = _find(parent, label)
            if root in occupied_x:
                occupied_x[root][start:end] = True
            if root in occupied_y:
                occupied_y[root][y] = True

    for root, component in aggregates.items():
        if root in occupied_x:
            start_x, width_pixels, centre_x = _circular_interval(occupied_x[root])
            component["start_x"] = start_x
            component["width_pixels"] = width_pixels
            component["centre_x_pixels"] = centre_x
            component["wraps_x"] = True
        else:
            min_x = int(component["min_x"])
            max_x = int(component["max_x"])
            component["start_x"] = min_x
            component["width_pixels"] = max_x - min_x + 1
            component["centre_x_pixels"] = (min_x + max_x + 1.0) * 0.5
            component["wraps_x"] = False
        if root in occupied_y:
            start_y, height_pixels, centre_y = _circular_interval(occupied_y[root])
            component["start_y"] = start_y
            component["height_pixels"] = height_pixels
            component["centre_y_pixels"] = centre_y
            component["wraps_y"] = True
        else:
            min_y = int(component["min_y"])
            max_y = int(component["max_y"])
            component["start_y"] = min_y
            component["height_pixels"] = max_y - min_y + 1
            component["centre_y_pixels"] = (min_y + max_y + 1.0) * 0.5
            component["wraps_y"] = False

    components = [component for component in aggregates.values() if int(component["pixels"]) >= minimum_pixels]
    components.sort(
        key=lambda item: (
            int(item["start_y"]),
            int(item["start_x"]),
            int(item["height_pixels"]),
            int(item["width_pixels"]),
        )
    )
    root_to_index = {int(component["root"]): index for index, component in enumerate(components)}
    labels = np.full((height, width), -1, dtype=np.int32)
    for y, start, end, label in all_runs:
        index = root_to_index.get(_find(parent, label))
        if index is not None:
            labels[y, start:end] = index
    return labels, components


def _pack_pair(low: np.ndarray | int, high: np.ndarray | int) -> np.ndarray:
    low_array = np.asarray(low, dtype=np.uint32)
    high_array = np.asarray(high, dtype=np.uint32)
    packed = low_array + high_array * np.uint32(_PACK_BASE)
    return packed.astype(np.float32) / _PACK_SCALE


def _unpack_pair(channel: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    packed = np.rint(np.clip(channel, 0.0, 1.0) * _PACK_SCALE).astype(np.uint32)
    low = (packed % np.uint32(_PACK_BASE)).astype(np.float32)
    high = (packed // np.uint32(_PACK_BASE)).astype(np.float32)
    return low, high


def _flood_metadata(data: ImageArray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    source = np.asarray(data, dtype=np.float32)
    centre_x = source[..., 0]
    centre_y = source[..., 1]
    width_q, height_q = _unpack_pair(source[..., 2])
    index_normalised = source[..., 3]
    size_x = width_q / float(_PACK_MAX)
    size_y = height_q / float(_PACK_MAX)
    active = (width_q > 0.0) & (height_q > 0.0)
    return centre_x, centre_y, size_x, size_y, index_normalised, np.ones_like(index_normalised), active, source


def _component_hash(data: ImageArray, seed: int, stream: int = 0) -> np.ndarray:
    centre_x, centre_y, size_x, size_y, index, count, active, _ = _flood_metadata(data)
    with np.errstate(over="ignore"):
        value = (
            np.rint(centre_x * 65535.0).astype(np.uint32) * np.uint32(0x9E3779B9)
            ^ np.rint(centre_y * 65535.0).astype(np.uint32) * np.uint32(0x85EBCA6B)
            ^ np.rint(size_x * 4095.0).astype(np.uint32) * np.uint32(0xC2B2AE35)
            ^ np.rint(size_y * 4095.0).astype(np.uint32) * np.uint32(0x27D4EB2D)
            ^ np.rint(index * 16777215.0).astype(np.uint32) * np.uint32(0x165667B1)
            ^ np.uint32(seed) * np.uint32(0xA24BAED5)
            ^ np.uint32(stream) * np.uint32(0x9FB21C65)
        )
        value ^= value >> np.uint32(16)
        value *= np.uint32(0x7FEB352D)
        value ^= value >> np.uint32(15)
        value *= np.uint32(0x846CA68B)
        value ^= value >> np.uint32(16)
    random = (value & np.uint32(0x00FFFFFF)).astype(np.float32) / np.float32(16777216.0)
    return np.where(active, random, 0.0).astype(np.float32, copy=False)


def _sample_at_uv(image: ImageArray, u: np.ndarray, v: np.ndarray, *, wrap: bool = False) -> np.ndarray:
    source = np.asarray(image, dtype=np.float32)
    height, width = source.shape[:2]
    if wrap:
        u = np.mod(u, 1.0)
        v = np.mod(v, 1.0)
    else:
        u = np.clip(u, 0.0, 1.0)
        v = np.clip(v, 0.0, 1.0)
    pixel_x = u * width - 0.5
    pixel_y = v * height - 0.5
    floor_x = np.floor(pixel_x).astype(np.int32)
    floor_y = np.floor(pixel_y).astype(np.int32)
    if wrap:
        x0 = np.mod(floor_x, width)
        y0 = np.mod(floor_y, height)
        x1 = np.mod(floor_x + 1, width)
        y1 = np.mod(floor_y + 1, height)
    else:
        x0 = np.clip(floor_x, 0, width - 1)
        y0 = np.clip(floor_y, 0, height - 1)
        x1 = np.clip(floor_x + 1, 0, width - 1)
        y1 = np.clip(floor_y + 1, 0, height - 1)
    fx = (pixel_x - floor_x)[..., None]
    fy = (pixel_y - floor_y)[..., None]
    top = source[y0, x0] * (1.0 - fx) + source[y0, x1] * fx
    bottom = source[y1, x0] * (1.0 - fx) + source[y1, x1] * fx
    return (top * (1.0 - fy) + bottom * fy).astype(np.float32, copy=False)


def eval_flood_fill(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    values = luminance(_input(inputs, "Binary Mask", context))
    mask = values >= float(params.get("threshold", 0.5))
    if bool(params.get("invert", False)):
        mask = ~mask
    labels, components = _connected_components(
        mask,
        diagonal=str(params.get("connectivity", "4-way")) == "8-way",
        wrap_x=True,
        wrap_y=True,
        minimum_pixels=max(int(round(relative_pixel_area(float(params.get("minimum_pixels", 1)), context))), 1),
    )
    output = np.zeros((context.height, context.width, 4), dtype=np.float32)
    count = len(components)
    if count <= 0:
        return output
    metadata = np.zeros((count, 4), dtype=np.float32)
    index_denominator = max(count - 1, 1)
    for index, component in enumerate(components):
        width_pixels = int(component["width_pixels"])
        height_pixels = int(component["height_pixels"])
        centre_x = float(component["centre_x_pixels"]) / max(context.width, 1)
        centre_y = float(component["centre_y_pixels"]) / max(context.height, 1)
        width_q = max(1, min(_PACK_MAX, int(math.ceil(width_pixels / max(context.width, 1) * _PACK_MAX))))
        height_q = max(1, min(_PACK_MAX, int(math.ceil(height_pixels / max(context.height, 1) * _PACK_MAX))))
        metadata[index] = (
            np.float32(centre_x),
            np.float32(centre_y),
            _pack_pair(width_q, height_q),
            np.float32(index / index_denominator),
        )
    valid = (labels >= 0) & (labels < count)
    output[valid] = metadata[labels[valid]]
    return output


def eval_flood_random_grayscale(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    data = _input(inputs, "Flood Fill", context)
    value = _component_hash(data, int(params.get("seed", 0)))
    return grayscale_rgba(value)


def eval_flood_random_colour(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    data = _input(inputs, "Flood Fill", context)
    red = _component_hash(data, int(params.get("seed", 0)), 0)
    green = _component_hash(data, int(params.get("seed", 0)), 1)
    blue = _component_hash(data, int(params.get("seed", 0)), 2)
    _, _, _, _, _, _, active, _ = _flood_metadata(data)
    result = np.zeros_like(data, dtype=np.float32)
    result[..., 0] = red
    result[..., 1] = green
    result[..., 2] = blue
    result[..., 3] = np.where(active, 1.0, 0.0)
    return result


def eval_flood_to_grayscale(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    data = _input(inputs, "Flood Fill", context)
    centre_x, centre_y, _sx, _sy, _index, _count, active, _ = _flood_metadata(data)
    source = inputs.get("Value Input")
    if source is None:
        base = np.full((context.height, context.width), float(params.get("base_value", 0.5)), dtype=np.float32)
    else:
        sampled = _sample_at_uv(ensure_rgba(source, context), centre_x, centre_y)
        base = luminance(sampled)
    random = _component_hash(data, int(params.get("seed", 0))) * 2.0 - 1.0
    value = base + float(params.get("adjustment", 0.0)) + random * float(params.get("random", 0.0))
    return grayscale_rgba(np.where(active, np.clip(value, 0.0, 1.0), 0.0))


def eval_flood_to_colour(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    data = _input(inputs, "Flood Fill", context)
    centre_x, centre_y, _sx, _sy, _index, _count, active, _ = _flood_metadata(data)
    source = inputs.get("Colour Input")
    if source is None:
        colour = np.array(parse_hex_color(str(params.get("base_colour", "#ffffffff"))), dtype=np.float32)
        base = np.broadcast_to(colour, (context.height, context.width, 4)).copy()
    else:
        base = _sample_at_uv(ensure_rgba(source, context), centre_x, centre_y)
    seed = int(params.get("seed", 0))
    amount = float(params.get("colour_random", 0.0))
    random_rgb = np.stack(
        (
            _component_hash(data, seed, 3),
            _component_hash(data, seed, 4),
            _component_hash(data, seed, 5),
        ),
        axis=-1,
    ) * 2.0 - 1.0
    result = base.copy()
    result[..., :3] = np.clip(
        result[..., :3] + float(params.get("luminance_adjustment", 0.0)) + random_rgb * amount,
        0.0,
        1.0,
    )
    result[..., :3] = np.where(active[..., None], result[..., :3], 0.0)
    result[..., 3] = np.where(active, result[..., 3], 0.0)
    return result.astype(np.float32, copy=False)


def eval_flood_to_position(inputs: Mapping[str, ImageArray], _params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    data = _input(inputs, "Flood Fill", context)
    centre_x, centre_y, _sx, _sy, _index, _count, active, _ = _flood_metadata(data)
    result = np.zeros_like(data, dtype=np.float32)
    result[..., 0] = np.where(active, centre_x, 0.0)
    result[..., 1] = np.where(active, centre_y, 0.0)
    result[..., 3] = np.where(active, 1.0, 0.0)
    return result


def eval_flood_to_bbox_size(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    data = _input(inputs, "Flood Fill", context)
    _cx, _cy, size_x, size_y, _index, _count, active, _ = _flood_metadata(data)
    mode = str(params.get("output", "Max X/Y"))
    if mode == "X":
        value = size_x
    elif mode == "Y":
        value = size_y
    elif mode == "Area":
        value = size_x * size_y
    elif mode == "Min X/Y":
        value = np.minimum(size_x, size_y)
    else:
        value = np.maximum(size_x, size_y)
    return grayscale_rgba(np.where(active, value, 0.0))


def eval_flood_to_index(inputs: Mapping[str, ImageArray], _params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    data = _input(inputs, "Flood Fill", context)
    _cx, _cy, _sx, _sy, index, _count, active, _ = _flood_metadata(data)
    return grayscale_rgba(np.where(active, index, 0.0))


def eval_flood_to_gradient(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    data = _input(inputs, "Flood Fill", context)
    centre_x, centre_y, size_x, size_y, _index, _count, active, _ = _flood_metadata(data)
    y, x = np.mgrid[0 : context.height, 0 : context.width]
    u = (x.astype(np.float32) + 0.5) / max(context.width, 1)
    v = (y.astype(np.float32) + 0.5) / max(context.height, 1)
    local_x = _wrapped_uv_delta(u, centre_x) / np.maximum(size_x, 1.0 / max(context.width, 1))
    local_y = _wrapped_uv_delta(v, centre_y) / np.maximum(size_y, 1.0 / max(context.height, 1))
    seed = int(params.get("seed", 0))
    random_angle = (_component_hash(data, seed, 6) * 2.0 - 1.0) * float(params.get("angle_variation", 0.0))
    angle = np.full_like(local_x, float(params.get("angle", 0.0))) + random_angle
    angle_source = inputs.get("Angle Input")
    if angle_source is not None:
        angle_map = luminance(_sample_at_uv(ensure_rgba(angle_source, context), centre_x, centre_y))
        angle += (angle_map - 0.5) * 360.0 * float(params.get("angle_input_multiplier", 0.0))
    radians = np.radians(angle)
    slope = np.full_like(local_x, float(params.get("slope_intensity", 1.0)))
    slope_source = inputs.get("Slope Input")
    if slope_source is not None:
        slope_map = luminance(_sample_at_uv(ensure_rgba(slope_source, context), centre_x, centre_y))
        multiplier = float(params.get("slope_input_multiplier", 0.0))
        slope *= (1.0 - multiplier) + slope_map * multiplier
    flat = float(params.get("flat_value", 0.5))
    direction = local_x * np.cos(radians) + local_y * np.sin(radians)
    value = flat + direction * slope
    bbox_multiplier = float(params.get("multiply_bbox_size", 0.0))
    if bbox_multiplier > 0.0:
        factor = (1.0 - bbox_multiplier) + np.maximum(size_x, size_y) * bbox_multiplier
        value *= factor
    return grayscale_rgba(np.where(active, np.clip(value, 0.0, 1.0), 0.0))


def eval_flood_mapper(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    data = _input(inputs, "Flood Fill", context)
    pattern = inputs.get("Pattern Input")
    if pattern is None:
        return grayscale_rgba(np.zeros((context.height, context.width), dtype=np.float32))
    centre_x, centre_y, size_x, size_y, _index, _count, active, _ = _flood_metadata(data)
    y, x = np.mgrid[0 : context.height, 0 : context.width]
    u = (x.astype(np.float32) + 0.5) / max(context.width, 1)
    v = (y.astype(np.float32) + 0.5) / max(context.height, 1)
    local_x = _wrapped_uv_delta(u, centre_x) / np.maximum(size_x, 1.0 / max(context.width, 1))
    local_y = _wrapped_uv_delta(v, centre_y) / np.maximum(size_y, 1.0 / max(context.height, 1))
    seed = int(params.get("seed", 0))
    scale = max(float(params.get("scale", 1.0)), 1.0e-4)
    scale_random = (_component_hash(data, seed, 7) * 2.0 - 1.0) * float(params.get("scale_random", 0.0))
    scale_factor = np.maximum(scale * (1.0 + scale_random), 1.0e-4)
    scale_source = inputs.get("Scale Map")
    if scale_source is not None:
        scale_map = luminance(_sample_at_uv(ensure_rgba(scale_source, context), centre_x, centre_y))
        strength = float(params.get("scale_map_multiplier", 0.0))
        scale_factor *= (1.0 - strength) + scale_map * strength
    angle = np.full_like(local_x, float(params.get("rotation", 0.0)))
    angle += (_component_hash(data, seed, 8) * 2.0 - 1.0) * float(params.get("rotation_random", 0.0))
    rotation_source = inputs.get("Rotation Map")
    if rotation_source is not None:
        rotation_map = luminance(_sample_at_uv(ensure_rgba(rotation_source, context), centre_x, centre_y))
        angle += (rotation_map - 0.5) * 360.0 * float(params.get("rotation_map_multiplier", 0.0))
    radians = np.radians(angle)
    cos_angle = np.cos(radians)
    sin_angle = np.sin(radians)
    mapped_x = (local_x * cos_angle + local_y * sin_angle) / scale_factor + 0.5 + float(params.get("offset_x", 0.0))
    mapped_y = (-local_x * sin_angle + local_y * cos_angle) / scale_factor + 0.5 + float(params.get("offset_y", 0.0))
    tiling = str(params.get("tiling", "No Tiling")) == "H + V Tiling"
    sampled = _sample_at_uv(ensure_rgba(pattern, context), mapped_x, mapped_y, wrap=tiling)
    value = luminance(sampled)
    if not tiling:
        inside = (mapped_x >= 0.0) & (mapped_x <= 1.0) & (mapped_y >= 0.0) & (mapped_y <= 1.0)
        value = np.where(inside, value, float(params.get("background_value", 0.0)))
    value = value * float(params.get("luminance_range", 1.0)) + float(params.get("luminance_offset", 0.0))
    return grayscale_rgba(np.where(active, np.clip(value, 0.0, 1.0), float(params.get("background_value", 0.0))))


def register_flood_fill_nodes(registry: NodeRegistry) -> None:
    f = ParameterSpec
    definitions = [
        NodeDefinition(
            "filter.flood_fill",
            "Flood Fill",
            "Flood Fill",
            eval_flood_fill,
            inputs=("Binary Mask",),
            parameters=(
                f("threshold", "Threshold", "float", 0.5, 0.0, 1.0, 0.01, group="Detection", group_order=10),
                f("connectivity", "Connectivity", "enum", "4-way", options=("4-way", "8-way"), group="Detection", group_order=10, description="8-way joins diagonally touching pixels; 4-way requires an edge connection."),
                f("minimum_pixels", "Ignore Shapes Smaller Than", "int", 1, 1, 65536, 1, group="Detection", group_order=10, slider_maximum=256, fine_step=1, coarse_step=10, unit="rpx²", description="Resolution-independent area measured on a 512 × 512 reference image."),
                f("invert", "Invert Input", "bool", False, group="Detection", group_order=10),
            ),
            description="Identify isolated white regions in a binary mask using seamless toroidal connectivity, then encode per-island centre, wrapped bounding-box size and ordered index data for the other Flood Fill nodes.",
            accent=_FLOOD_ACCENT,
            tags=("islands", "components", "regions", "tiles", "bbox", "id"),
            output_format="rgba32f",
            gpu_kernel="flood_fill.wgsl",
            input_kinds=(("Binary Mask", "grayscale"),),
            output_kinds=(("Flood Fill", "vector"),),
            output_name="Flood Fill",
            default_image_kind="vector",
        ),
        NodeDefinition(
            "filter.flood_fill_random_grayscale",
            "Flood Fill to Random Grayscale",
            "Flood Fill",
            eval_flood_random_grayscale,
            inputs=("Flood Fill",),
            parameters=(f("seed", "Random Seed", "int", 0, 0, 2147483647, 1, slider_maximum=1000, fine_step=1, coarse_step=10),),
            description="Assign one deterministic random grayscale value to every Flood Fill island.",
            accent=_FLOOD_ACCENT,
            tags=("random", "grayscale", "island", "variation"),
            output_format="r16f",
            gpu_kernel="flood_fill_random_grayscale.wgsl",
            input_kinds=(("Flood Fill", "vector"),),
            output_kinds=(("Image", "grayscale"),),
            default_image_kind="grayscale",
        ),
        NodeDefinition(
            "filter.flood_fill_random_colour",
            "Flood Fill to Random Colour",
            "Flood Fill",
            eval_flood_random_colour,
            inputs=("Flood Fill",),
            parameters=(f("seed", "Random Seed", "int", 0, 0, 2147483647, 1, slider_maximum=1000, fine_step=1, coarse_step=10),),
            description="Assign one deterministic random RGB colour to every Flood Fill island.",
            accent=_FLOOD_ACCENT,
            tags=("random", "colour", "color", "island", "id"),
            output_format="rgba16f",
            gpu_kernel="flood_fill_random_colour.wgsl",
            input_kinds=(("Flood Fill", "vector"),),
            output_kinds=(("Image", "color"),),
            default_image_kind="color",
        ),
        NodeDefinition(
            "filter.flood_fill_to_grayscale",
            "Flood Fill to Grayscale",
            "Flood Fill",
            eval_flood_to_grayscale,
            inputs=("Flood Fill", "Value Input"),
            parameters=(
                f("base_value", "Base Value", "float", 0.5, 0.0, 1.0, 0.01, group="Value", group_order=10),
                f("adjustment", "Luminance Adjustment", "float", 0.0, -1.0, 1.0, 0.01, group="Value", group_order=10),
                f("random", "Luminance Random", "float", 0.0, 0.0, 1.0, 0.01, group="Value", group_order=10),
                f("seed", "Random Seed", "int", 0, 0, 2147483647, 1, group="Value", group_order=10, slider_maximum=1000, fine_step=1, coarse_step=10),
            ),
            description="Assign a controlled grayscale value to each island, optionally sampling the base value from another map at the island centre.",
            accent=_FLOOD_ACCENT,
            tags=("grayscale", "value", "island", "variation"),
            output_format="r16f",
            gpu_kernel="flood_fill_to_grayscale.wgsl",
            input_kinds=(("Flood Fill", "vector"), ("Value Input", "grayscale")),
            output_kinds=(("Image", "grayscale"),),
            default_image_kind="grayscale",
        ),
        NodeDefinition(
            "filter.flood_fill_to_colour",
            "Flood Fill to Colour",
            "Flood Fill",
            eval_flood_to_colour,
            inputs=("Flood Fill", "Colour Input"),
            parameters=(
                f("base_colour", "Base Colour", "color", "#ffffffff", group="Colour", group_order=10),
                f("luminance_adjustment", "Luminance Adjustment", "float", 0.0, -1.0, 1.0, 0.01, group="Colour", group_order=10),
                f("colour_random", "Colour Random", "float", 0.0, 0.0, 1.0, 0.01, group="Colour", group_order=10),
                f("seed", "Random Seed", "int", 0, 0, 2147483647, 1, group="Colour", group_order=10, slider_maximum=1000, fine_step=1, coarse_step=10),
            ),
            description="Assign a controlled colour to each island, optionally sampling its base colour from another texture at the island centre.",
            accent=_FLOOD_ACCENT,
            tags=("colour", "color", "island", "variation"),
            output_format="rgba16f",
            gpu_kernel="flood_fill_to_colour.wgsl",
            input_kinds=(("Flood Fill", "vector"), ("Colour Input", "color")),
            output_kinds=(("Image", "color"),),
            default_image_kind="color",
        ),
        NodeDefinition(
            "filter.flood_fill_to_gradient",
            "Flood Fill to Gradient",
            "Flood Fill",
            eval_flood_to_gradient,
            inputs=("Flood Fill", "Angle Input", "Slope Input"),
            parameters=(
                f("angle", "Angle", "float", 0.0, -180.0, 180.0, 1.0, group="Direction", group_order=10, editor="angle", unit="degrees", fine_step=1.0, coarse_step=5.0),
                f("angle_variation", "Angle Variation", "float", 0.0, 0.0, 180.0, 1.0, group="Direction", group_order=10, unit="degrees", fine_step=1.0, coarse_step=5.0),
                f("angle_input_multiplier", "Angle Input Multiplier", "float", 0.0, 0.0, 1.0, 0.01, group="Direction", group_order=10),
                f("seed", "Random Seed", "int", 0, 0, 2147483647, 1, group="Direction", group_order=10, slider_maximum=1000, fine_step=1, coarse_step=10),
                f("slope_intensity", "Slope Intensity", "float", 1.0, 0.0, 4.0, 0.01, group="Slope", group_order=20, slider_maximum=2.0),
                f("slope_input_multiplier", "Slope Input Multiplier", "float", 0.0, 0.0, 1.0, 0.01, group="Slope", group_order=20),
                f("multiply_bbox_size", "Multiply by Bounding Box Size", "float", 0.0, 0.0, 1.0, 0.01, group="Slope", group_order=20),
                f("flat_value", "Flat Slope Value", "float", 0.5, 0.0, 1.0, 0.01, group="Slope", group_order=20),
            ),
            description="Generate an independently oriented linear gradient inside every island, with random, angle-map and slope-map modulation.",
            accent=_FLOOD_ACCENT,
            tags=("gradient", "slope", "tilt", "height", "island"),
            output_format="r16f",
            gpu_kernel="flood_fill_to_gradient.wgsl",
            input_kinds=(("Flood Fill", "vector"), ("Angle Input", "grayscale"), ("Slope Input", "grayscale")),
            output_kinds=(("Image", "grayscale"),),
            default_image_kind="grayscale",
        ),
        NodeDefinition(
            "filter.flood_fill_to_position",
            "Flood Fill to Position",
            "Flood Fill",
            eval_flood_to_position,
            inputs=("Flood Fill",),
            description="Encode each island centre in Red and Green for downstream position-driven effects.",
            accent=_FLOOD_ACCENT,
            tags=("position", "centre", "center", "vector", "island"),
            output_format="rgba16f",
            gpu_kernel="flood_fill_to_position.wgsl",
            input_kinds=(("Flood Fill", "vector"),),
            output_kinds=(("Position", "vector"),),
            output_name="Position",
            default_image_kind="vector",
        ),
        NodeDefinition(
            "filter.flood_fill_to_bbox_size",
            "Flood Fill to BBox Size",
            "Flood Fill",
            eval_flood_to_bbox_size,
            inputs=("Flood Fill",),
            parameters=(f("output", "Output", "enum", "Max X/Y", options=("Max X/Y", "Min X/Y", "X", "Y", "Area")),),
            description="Assign every island a grayscale value based on its bounding-box dimensions relative to the canvas.",
            accent=_FLOOD_ACCENT,
            tags=("bbox", "bounding box", "size", "area", "island"),
            output_format="r16f",
            gpu_kernel="flood_fill_to_bbox_size.wgsl",
            input_kinds=(("Flood Fill", "vector"),),
            output_kinds=(("Image", "grayscale"),),
            default_image_kind="grayscale",
        ),
        NodeDefinition(
            "filter.flood_fill_to_index",
            "Flood Fill to Index",
            "Flood Fill",
            eval_flood_to_index,
            inputs=("Flood Fill",),
            description="Assign each island its top-left ordered index as a normalised 0–1 value.",
            accent=_FLOOD_ACCENT,
            tags=("index", "id", "ordered", "island", "hdr"),
            output_format="r32f",
            gpu_kernel="flood_fill_to_index.wgsl",
            input_kinds=(("Flood Fill", "vector"),),
            output_kinds=(("Image", "grayscale"),),
            default_image_kind="grayscale",
        ),
        NodeDefinition(
            "filter.flood_fill_mapper",
            "Flood Fill Mapper Grayscale",
            "Flood Fill",
            eval_flood_mapper,
            inputs=("Flood Fill", "Pattern Input", "Scale Map", "Rotation Map"),
            parameters=(
                f("tiling", "Tiling Mode", "enum", "No Tiling", options=("No Tiling", "H + V Tiling"), group="Pattern", group_order=10),
                f("scale", "Scale", "float", 1.0, 0.01, 8.0, 0.01, group="Size", group_order=20, slider_maximum=2.0),
                f("scale_random", "Scale Random", "float", 0.0, 0.0, 1.0, 0.01, group="Size", group_order=20),
                f("scale_map_multiplier", "Scale Map Multiplier", "float", 0.0, 0.0, 1.0, 0.01, group="Size", group_order=20),
                f("rotation", "Rotation", "float", 0.0, -180.0, 180.0, 1.0, group="Rotation", group_order=30, editor="angle", unit="degrees", fine_step=1.0, coarse_step=5.0),
                f("rotation_random", "Rotation Random Range", "float", 0.0, 0.0, 180.0, 1.0, group="Rotation", group_order=30, unit="degrees", fine_step=1.0, coarse_step=5.0),
                f("rotation_map_multiplier", "Rotation Map Multiplier", "float", 0.0, 0.0, 1.0, 0.01, group="Rotation", group_order=30),
                f("offset_x", "Offset X", "float", 0.0, -4.0, 4.0, 0.01, group="Position", group_order=40, slider_minimum=-1.0, slider_maximum=1.0),
                f("offset_y", "Offset Y", "float", 0.0, -4.0, 4.0, 0.01, group="Position", group_order=40, slider_minimum=-1.0, slider_maximum=1.0),
                f("luminance_range", "Luminance Range", "float", 1.0, 0.0, 2.0, 0.01, group="Value", group_order=50),
                f("luminance_offset", "Luminance Offset", "float", 0.0, -1.0, 1.0, 0.01, group="Value", group_order=50),
                f("background_value", "Background Value", "float", 0.0, 0.0, 1.0, 0.01, group="Value", group_order=50),
                f("seed", "Random Seed", "int", 0, 0, 2147483647, 1, group="Random", group_order=60, slider_maximum=1000, fine_step=1, coarse_step=10),
            ),
            description="Map a custom grayscale pattern independently into every Flood Fill island, with per-island scale and rotation variation plus optional modulation maps.",
            accent=_FLOOD_ACCENT,
            tags=("mapper", "pattern", "island", "bbox", "texture"),
            output_format="r16f",
            gpu_kernel="flood_fill_mapper.wgsl",
            input_kinds=(("Flood Fill", "vector"), ("Pattern Input", "grayscale"), ("Scale Map", "grayscale"), ("Rotation Map", "grayscale")),
            output_kinds=(("Image", "grayscale"),),
            default_image_kind="grayscale",
        ),
    ]
    for definition in definitions:
        registry.register(replace(definition))
