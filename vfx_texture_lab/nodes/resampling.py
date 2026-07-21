from __future__ import annotations

"""Shared CPU reference resampling for transform-family nodes.

Coordinates are expressed in source pixel space with pixel centres at integer
locations.  The same convention is used by the WGSL transform shaders:
``uv * size - 0.5`` maps a normalised UV to pixel coordinates.
"""

from typing import Any

import numpy as np

from .image_ops import ensure_rgba

FILTERING_OPTIONS = ("Automatic", "Nearest", "Bilinear", "Bicubic")
BOUNDARY_OPTIONS = ("Transparent", "Clamp", "Seamless / Wrap", "Mirror")


def _boundary_name(value: Any, *, legacy_wrap: bool | None = None) -> str:
    text = str(value or "").strip()
    if legacy_wrap is not None:
        return "Seamless / Wrap" if legacy_wrap else "Transparent"
    if text in BOUNDARY_OPTIONS:
        return text
    aliases = {
        "Wrap": "Seamless / Wrap",
        "Tile": "Seamless / Wrap",
        "Seamless": "Seamless / Wrap",
        "None": "Transparent",
    }
    return aliases.get(text, "Transparent")


def boundary_name(params: dict | Any, *, default: str = "Transparent", legacy_key: str | None = None) -> str:
    try:
        value = params.get("boundary", default)
        legacy = None if legacy_key is None or legacy_key not in params else bool(params.get(legacy_key))
    except AttributeError:
        value, legacy = params, None
    return _boundary_name(value, legacy_wrap=legacy)


def filtering_name(value: Any, *, default: str = "Automatic") -> str:
    text = str(value or default)
    return text if text in FILTERING_OPTIONS else default


def _mirror_indices(index: np.ndarray, size: int) -> np.ndarray:
    if size <= 1:
        return np.zeros_like(index, dtype=np.int64)
    period = 2 * size
    value = np.mod(index, period)
    return np.where(value < size, value, period - 1 - value).astype(np.int64)


def _resolve_indices(index: np.ndarray, size: int, boundary: str) -> tuple[np.ndarray, np.ndarray | None]:
    raw = np.asarray(index, dtype=np.int64)
    if boundary == "Seamless / Wrap":
        return np.mod(raw, size).astype(np.int64), None
    if boundary == "Mirror":
        return _mirror_indices(raw, size), None
    valid = (raw >= 0) & (raw < size) if boundary == "Transparent" else None
    return np.clip(raw, 0, max(size - 1, 0)).astype(np.int64), valid


def _prepare_working(image: np.ndarray, data_kind: str) -> np.ndarray:
    source = ensure_rgba(image).astype(np.float32, copy=False)
    if data_kind == "vector":
        working = source.copy()
        working[..., :3] = source[..., :3] * np.float32(2.0) - np.float32(1.0)
        return working
    if data_kind == "color":
        # Filtering straight RGB next to transparent pixels creates dark/bright
        # fringes.  Interpolate premultiplied linear-light colour and coverage.
        working = source.copy()
        working[..., :3] *= working[..., 3:4]
        return working
    return source


def _finish_working(result: np.ndarray, data_kind: str) -> np.ndarray:
    output = np.asarray(result, dtype=np.float32).copy()
    if data_kind == "vector":
        normal = output[..., :3]
        length = np.linalg.norm(normal, axis=2, keepdims=True)
        normal = normal / np.maximum(length, np.float32(1.0e-7))
        invalid = length[..., 0] <= 1.0e-7
        if np.any(invalid):
            normal[invalid] = np.array((0.0, 0.0, 1.0), dtype=np.float32)
        output[..., :3] = normal * np.float32(0.5) + np.float32(0.5)
    elif data_kind == "color":
        alpha = output[..., 3:4]
        output[..., :3] = np.where(alpha > 1.0e-7, output[..., :3] / np.maximum(alpha, 1.0e-7), 0.0)
    return np.nan_to_num(output, nan=0.0, posinf=1.0, neginf=0.0).astype(np.float32, copy=False)


def _gather(source: np.ndarray, x: np.ndarray, y: np.ndarray, boundary: str, fill_value: np.ndarray) -> np.ndarray:
    height, width = source.shape[:2]
    ix, valid_x = _resolve_indices(x, width, boundary)
    iy, valid_y = _resolve_indices(y, height, boundary)
    result = source[iy, ix]
    if boundary == "Transparent":
        valid = valid_x & valid_y
        if not np.all(valid):
            result = result.copy()
            result[~valid] = fill_value
    return result


def _nearest(source: np.ndarray, sx: np.ndarray, sy: np.ndarray, boundary: str, fill_value: np.ndarray) -> np.ndarray:
    return _gather(source, np.floor(sx + 0.5).astype(np.int64), np.floor(sy + 0.5).astype(np.int64), boundary, fill_value)


def _bilinear(source: np.ndarray, sx: np.ndarray, sy: np.ndarray, boundary: str, fill_value: np.ndarray) -> np.ndarray:
    x0f = np.floor(sx)
    y0f = np.floor(sy)
    x0 = x0f.astype(np.int64)
    y0 = y0f.astype(np.int64)
    tx = (sx - x0f)[..., None].astype(np.float32)
    ty = (sy - y0f)[..., None].astype(np.float32)
    a = _gather(source, x0, y0, boundary, fill_value)
    b = _gather(source, x0 + 1, y0, boundary, fill_value)
    c = _gather(source, x0, y0 + 1, boundary, fill_value)
    d = _gather(source, x0 + 1, y0 + 1, boundary, fill_value)
    return (a * (1.0 - tx) + b * tx) * (1.0 - ty) + (c * (1.0 - tx) + d * tx) * ty


def _cubic_weight(distance: np.ndarray) -> np.ndarray:
    """Mitchell-Netravali cubic (B=C=1/3), a balanced production default."""
    x = np.abs(np.asarray(distance, dtype=np.float32))
    x2 = x * x
    x3 = x2 * x
    first = ((7.0 * x3) - (12.0 * x2) + (16.0 / 3.0)) / 6.0
    second = ((-7.0 / 3.0 * x3) + (12.0 * x2) - (20.0 * x) + (32.0 / 3.0)) / 6.0
    return np.where(x < 1.0, first, np.where(x < 2.0, second, 0.0)).astype(np.float32)


def _bicubic(source: np.ndarray, sx: np.ndarray, sy: np.ndarray, boundary: str, fill_value: np.ndarray) -> np.ndarray:
    xbase = np.floor(sx).astype(np.int64)
    ybase = np.floor(sy).astype(np.int64)
    result = np.zeros((*sx.shape, source.shape[2]), dtype=np.float32)
    total = np.zeros((*sx.shape, 1), dtype=np.float32)
    for oy in (-1, 0, 1, 2):
        wy = _cubic_weight(sy - (ybase + oy))[..., None]
        for ox in (-1, 0, 1, 2):
            weight = wy * _cubic_weight(sx - (xbase + ox))[..., None]
            result += _gather(source, xbase + ox, ybase + oy, boundary, fill_value) * weight
            total += weight
    return result / np.maximum(total, np.float32(1.0e-7))


def _footprint_array(value: float | np.ndarray | None, shape: tuple[int, ...]) -> np.ndarray:
    if value is None:
        return np.ones(shape, dtype=np.float32)
    array = np.asarray(value, dtype=np.float32)
    if array.size == 0:
        return np.ones(shape, dtype=np.float32)
    if array.ndim == 0:
        return np.full(shape, max(float(array), 1.0), dtype=np.float32)
    return np.maximum(np.broadcast_to(array, shape), np.float32(1.0)).astype(np.float32, copy=False)


def _area_taps(
    source: np.ndarray,
    sx: np.ndarray,
    sy: np.ndarray,
    boundary: str,
    fill_value: np.ndarray,
    footprint_x: np.ndarray,
    footprint_y: np.ndarray,
    grid: tuple[float, ...],
) -> np.ndarray:
    sampled = np.zeros((*sx.shape, source.shape[2]), dtype=np.float32)
    spread_x = np.minimum(footprint_x, np.float32(8.0))
    spread_y = np.minimum(footprint_y, np.float32(8.0))
    count = 0
    for oy in grid:
        for ox in grid:
            sampled += _bilinear(
                source,
                sx + np.float32(ox) * spread_x,
                sy + np.float32(oy) * spread_y,
                boundary,
                fill_value,
            )
            count += 1
    return sampled / np.float32(max(count, 1))


def sample_image(
    image: np.ndarray,
    sx: np.ndarray,
    sy: np.ndarray,
    *,
    filtering: str = "Automatic",
    boundary: str = "Transparent",
    data_kind: str = "grayscale",
    footprint_x: float | np.ndarray | None = None,
    footprint_y: float | np.ndarray | None = None,
) -> np.ndarray:
    """Sample a typed image using one shared transform convention.

    ``footprint_x/y`` describe the approximate source-pixel footprint of one
    output pixel. Automatic filtering follows the local footprint per pixel,
    matching the WGSL implementation: cubic near unity, four area-aware taps
    for ordinary minification, and nine taps for stronger reduction.
    """
    mode = filtering_name(filtering)
    boundary = _boundary_name(boundary)
    source = _prepare_working(image, str(data_kind))
    fill_value = (
        np.array((0.0, 0.0, 1.0, 0.0), dtype=np.float32)
        if str(data_kind) == "vector" else np.zeros(4, dtype=np.float32)
    )
    sx = np.asarray(sx, dtype=np.float32)
    sy = np.asarray(sy, dtype=np.float32)

    if mode == "Nearest":
        sampled = _nearest(source, sx, sy, boundary, fill_value)
    elif mode == "Bilinear":
        sampled = _bilinear(source, sx, sy, boundary, fill_value)
    elif mode == "Bicubic":
        sampled = _bicubic(source, sx, sy, boundary, fill_value)
    else:
        fx = _footprint_array(footprint_x, sx.shape)
        fy = _footprint_array(footprint_y, sx.shape)
        footprint = np.maximum(fx, fy)
        low = footprint <= np.float32(1.05)
        medium = (footprint > np.float32(1.05)) & (footprint <= np.float32(2.5))
        high = footprint > np.float32(2.5)
        if bool(np.all(low)):
            sampled = _bicubic(source, sx, sy, boundary, fill_value)
        elif bool(np.all(medium)):
            sampled = _area_taps(source, sx, sy, boundary, fill_value, fx, fy, (-0.25, 0.25))
        elif bool(np.all(high)):
            sampled = _area_taps(source, sx, sy, boundary, fill_value, fx, fy, (-1.0 / 3.0, 0.0, 1.0 / 3.0))
        else:
            sampled = np.zeros((*sx.shape, source.shape[2]), dtype=np.float32)
            if np.any(low):
                cubic = _bicubic(source, sx, sy, boundary, fill_value)
                sampled[low] = cubic[low]
            if np.any(medium):
                four = _area_taps(source, sx, sy, boundary, fill_value, fx, fy, (-0.25, 0.25))
                sampled[medium] = four[medium]
            if np.any(high):
                nine = _area_taps(source, sx, sy, boundary, fill_value, fx, fy, (-1.0 / 3.0, 0.0, 1.0 / 3.0))
                sampled[high] = nine[high]
    return np.clip(_finish_working(sampled, str(data_kind)), 0.0, 1.0).astype(np.float32, copy=False)



def affine_pixel_footprint(scale_x: float, scale_y: float, angle_degrees: float) -> tuple[float, float]:
    """Return source-pixel footprints for a pixel-space affine transform.

    Scaling is expressed along the transform's local axes and rotation happens
    in physical pixel space.  The returned lengths describe where one output
    pixel lands in source pixels along output X and Y.
    """
    sx = max(float(scale_x), 1.0e-6)
    sy = max(float(scale_y), 1.0e-6)
    angle = np.deg2rad(float(angle_degrees))
    c = float(np.cos(angle))
    s = float(np.sin(angle))
    footprint_x = float(np.hypot(c / sx, s / sy))
    footprint_y = float(np.hypot(s / sx, c / sy))
    return max(footprint_x, 1.0), max(footprint_y, 1.0)

def estimate_coordinate_footprint(sx: np.ndarray, sy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Estimate local source-pixel footprint for projective/nonlinear maps."""
    sx = np.asarray(sx, dtype=np.float32)
    sy = np.asarray(sy, dtype=np.float32)
    dsx_dx = np.gradient(sx, axis=1)
    dsy_dx = np.gradient(sy, axis=1)
    dsx_dy = np.gradient(sx, axis=0)
    dsy_dy = np.gradient(sy, axis=0)
    footprint_x = np.sqrt(dsx_dx * dsx_dx + dsy_dx * dsy_dx)
    footprint_y = np.sqrt(dsx_dy * dsx_dy + dsy_dy * dsy_dy)
    return footprint_x.astype(np.float32), footprint_y.astype(np.float32)
