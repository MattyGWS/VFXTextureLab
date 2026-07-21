from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Callable, Mapping

import numpy as np

from .base import EvalContext, ImageArray, NodeDefinition, ParameterSpec
from .image_ops import grayscale_rgba
from .registry import NodeRegistry

TAU = math.tau
_NOISE_ACCENT = "#4fa6a3"


def _uv(context: EvalContext) -> tuple[np.ndarray, np.ndarray]:
    y, x = np.mgrid[0 : context.height, 0 : context.width]
    return (
        (x.astype(np.float32) + np.float32(0.5)) / np.float32(max(context.width, 1)),
        (y.astype(np.float32) + np.float32(0.5)) / np.float32(max(context.height, 1)),
    )


def _fade(value: np.ndarray | np.float32) -> np.ndarray | np.float32:
    return value * value * value * (value * (value * 6.0 - 15.0) + 10.0)


def _hash_u32(value: np.ndarray | np.uint32) -> np.ndarray:
    value = np.asarray(value, dtype=np.uint32)
    with np.errstate(over="ignore"):
        value = value ^ (value >> np.uint32(16))
        value = value * np.uint32(0x7FEB352D)
        value = value ^ (value >> np.uint32(15))
        value = value * np.uint32(0x846CA68B)
        value = value ^ (value >> np.uint32(16))
    return value.astype(np.uint32, copy=False)


def _hash3(ix: np.ndarray, iy: np.ndarray, iz: int | np.ndarray, seed: int, salt: int = 0) -> np.ndarray:
    with np.errstate(over="ignore"):
        value = (
            np.asarray(ix, dtype=np.uint32) * np.uint32(0x9E3779B1)
            ^ np.asarray(iy, dtype=np.uint32) * np.uint32(0x85EBCA77)
            ^ np.asarray(iz, dtype=np.uint32) * np.uint32(0xC2B2AE3D)
            ^ np.uint32(seed) * np.uint32(0x27D4EB2F)
            ^ np.uint32(salt) * np.uint32(0x165667B1)
        )
    return _hash_u32(value)


def _hash01(value: np.ndarray) -> np.ndarray:
    return ((value & np.uint32(0x00FFFFFF)).astype(np.float32) / np.float32(16777215.0)).astype(np.float32)


def _gradient3(ix: np.ndarray, iy: np.ndarray, iz: int, seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    h1 = _hash01(_hash3(ix, iy, iz, seed, 0))
    h2 = _hash01(_hash3(ix, iy, iz, seed, 1))
    gz = h1 * np.float32(2.0) - np.float32(1.0)
    angle = h2 * np.float32(TAU)
    radial = np.sqrt(np.maximum(np.float32(1.0) - gz * gz, np.float32(0.0)))
    return (
        (np.cos(angle) * radial).astype(np.float32),
        (np.sin(angle) * radial).astype(np.float32),
        gz.astype(np.float32),
    )


def _periodic_value_noise_3d_uv(
    u: np.ndarray,
    v: np.ndarray,
    cells_x: int,
    cells_y: int,
    seed: int,
    z: float,
    z_period: int,
) -> np.ndarray:
    cells_x = max(int(cells_x), 1)
    cells_y = max(int(cells_y), 1)
    z_period = max(int(z_period), 1)
    px = np.mod(u, 1.0) * np.float32(cells_x)
    py = np.mod(v, 1.0) * np.float32(cells_y)
    x_base = np.floor(px).astype(np.int32)
    y_base = np.floor(py).astype(np.int32)
    fx = (px - x_base).astype(np.float32)
    fy = (py - y_base).astype(np.float32)
    z_base = math.floor(z)
    fz = np.float32(z - z_base)
    tx = _fade(fx).astype(np.float32)
    ty = _fade(fy).astype(np.float32)
    tz = np.float32(_fade(fz))

    x0 = np.mod(x_base, cells_x).astype(np.uint32)
    x1 = np.mod(x_base + 1, cells_x).astype(np.uint32)
    y0 = np.mod(y_base, cells_y).astype(np.uint32)
    y1 = np.mod(y_base + 1, cells_y).astype(np.uint32)
    z0 = z_base % z_period
    z1 = (z0 + 1) % z_period

    def plane(zi: int) -> np.ndarray:
        a = _hash01(_hash3(x0, y0, zi, seed))
        b = _hash01(_hash3(x1, y0, zi, seed))
        c = _hash01(_hash3(x0, y1, zi, seed))
        d = _hash01(_hash3(x1, y1, zi, seed))
        top = a + (b - a) * tx
        bottom = c + (d - c) * tx
        return top + (bottom - top) * ty

    low = plane(z0)
    high = plane(z1)
    return (low + (high - low) * tz).astype(np.float32)


def _periodic_gradient_noise_3d_uv(
    u: np.ndarray,
    v: np.ndarray,
    cells_x: int,
    cells_y: int,
    seed: int,
    z: float,
    z_period: int,
) -> np.ndarray:
    cells_x = max(int(cells_x), 1)
    cells_y = max(int(cells_y), 1)
    z_period = max(int(z_period), 1)
    px = np.mod(u, 1.0) * np.float32(cells_x)
    py = np.mod(v, 1.0) * np.float32(cells_y)
    x_base = np.floor(px).astype(np.int32)
    y_base = np.floor(py).astype(np.int32)
    fx = (px - x_base).astype(np.float32)
    fy = (py - y_base).astype(np.float32)
    z_base = math.floor(z)
    fz = np.float32(z - z_base)
    tx = _fade(fx).astype(np.float32)
    ty = _fade(fy).astype(np.float32)
    tz = np.float32(_fade(fz))

    x_indices = (
        np.mod(x_base, cells_x).astype(np.uint32),
        np.mod(x_base + 1, cells_x).astype(np.uint32),
    )
    y_indices = (
        np.mod(y_base, cells_y).astype(np.uint32),
        np.mod(y_base + 1, cells_y).astype(np.uint32),
    )
    z_indices = (z_base % z_period, (z_base + 1) % z_period)

    layers: list[np.ndarray] = []
    for oz, zi in enumerate(z_indices):
        rows: list[np.ndarray] = []
        dz = fz - np.float32(oz)
        for oy, yi in enumerate(y_indices):
            values: list[np.ndarray] = []
            dy = fy - np.float32(oy)
            for ox, xi in enumerate(x_indices):
                dx = fx - np.float32(ox)
                gx, gy, gz = _gradient3(xi, yi, zi, seed)
                values.append(gx * dx + gy * dy + gz * dz)
            rows.append(values[0] + (values[1] - values[0]) * tx)
        layers.append(rows[0] + (rows[1] - rows[0]) * ty)
    signed = layers[0] + (layers[1] - layers[0]) * tz
    return np.clip(np.float32(0.5) + signed * np.float32(0.86), 0.0, 1.0).astype(np.float32)


def _aspect_cells(scale: float, context: EvalContext) -> tuple[int, int]:
    cells_x = max(int(round(scale)), 1)
    cells_y = max(int(round(scale * context.height / max(context.width, 1))), 1)
    return cells_x, cells_y


def _evolution_phase(value: float) -> float:
    """Return a normalised 0..1 loop phase, retaining 1 as the visible endpoint.

    Older development graphs allowed arbitrary Evolution values. Values outside
    the new range wrap cleanly so legacy graphs retain their equivalent phase.
    """
    value = float(value)
    if 0.0 <= value <= 1.0:
        return value
    return value - math.floor(value)


def _loop_z(evolution: float, cycles: float, period: int = 4) -> tuple[float, int]:
    """Map normalised Evolution onto a compact periodic temporal lattice.

    A four-cell temporal period gives organic motion without racing through
    sixteen unrelated noise layers per document loop. Loop Cycles controls how
    many times that compact path is traversed.
    """
    safe_cycles = max(float(cycles), 0.001)
    z_period = max(int(period), 1)
    return _evolution_phase(evolution) * float(z_period) * safe_cycles, z_period


def _domain_warp(
    u: np.ndarray,
    v: np.ndarray,
    context: EvalContext,
    scale: float,
    seed: int,
    evolution: float,
    cycles: float,
    amount: float,
    disorder_scale: float,
) -> tuple[np.ndarray, np.ndarray]:
    if abs(amount) <= 1e-6:
        return u, v
    warp_scale = max(disorder_scale, 1.0)
    wx, wy = _aspect_cells(warp_scale, context)
    z, z_period = _loop_z(evolution, cycles)
    field_x = _periodic_gradient_noise_3d_uv(u, v, wx, wy, seed + 181, z, z_period) * 2.0 - 1.0
    field_y = _periodic_gradient_noise_3d_uv(u, v, wx, wy, seed + 347, z, z_period) * 2.0 - 1.0
    strength = float(amount) * 0.16 / max(math.sqrt(max(scale, 1.0)), 1.0)
    return np.mod(u + field_x * strength, 1.0), np.mod(v + field_y * strength, 1.0)


def _finish(value: np.ndarray, contrast: float, balance: float, invert: bool = False) -> np.ndarray:
    result = (value - 0.5) * max(float(contrast), 0.001) + 0.5 + float(balance) * 0.5
    result = np.clip(result, 0.0, 1.0)
    if invert:
        result = 1.0 - result
    return result.astype(np.float32)


def _eval_base_noise(
    params: Mapping[str, Any], context: EvalContext, *, gradient: bool
) -> ImageArray:
    u, v = _uv(context)
    scale = max(float(params.get("scale", 8.0)), 1.0)
    seed = int(params.get("seed", 1))
    evolution = _evolution_phase(float(params.get("evolution", 0.0)))
    cycles = float(params.get("loop_cycles", 1.0))
    u, v = _domain_warp(
        u,
        v,
        context,
        scale,
        seed,
        evolution,
        cycles,
        float(params.get("disorder", 0.0)),
        float(params.get("disorder_scale", max(scale * 0.5, 1.0))),
    )
    cells_x, cells_y = _aspect_cells(scale, context)
    z, z_period = _loop_z(evolution, cycles)
    if gradient:
        value = _periodic_gradient_noise_3d_uv(u, v, cells_x, cells_y, seed, z, z_period)
    else:
        value = _periodic_value_noise_3d_uv(u, v, cells_x, cells_y, seed, z, z_period)
    return grayscale_rgba(
        _finish(
            value,
            float(params.get("contrast", 1.0)),
            float(params.get("balance", 0.0)),
            bool(params.get("invert", False)),
        )
    )


def eval_value_noise(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    return _eval_base_noise(params, context, gradient=False)


def eval_perlin_noise(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    return _eval_base_noise(params, context, gradient=True)


def _fractal_setup(params: Mapping[str, Any], context: EvalContext) -> tuple[
    np.ndarray, np.ndarray, float, int, float, float, int, float, float
]:
    u, v = _uv(context)
    scale = max(float(params.get("scale", 5.0)), 1.0)
    octaves = min(max(int(params.get("octaves", 5)), 1), 10)
    lacunarity = max(float(params.get("lacunarity", 2.0)), 1.01)
    gain = min(max(float(params.get("gain", 0.5)), 0.0), 1.0)
    seed = int(params.get("seed", 1))
    evolution = _evolution_phase(float(params.get("evolution", 0.0)))
    cycles = float(params.get("loop_cycles", 1.0))
    u, v = _domain_warp(
        u,
        v,
        context,
        scale,
        seed,
        evolution,
        cycles,
        float(params.get("disorder", 0.0)),
        float(params.get("disorder_scale", 3.0)),
    )
    return u, v, scale, octaves, lacunarity, gain, seed, evolution, cycles


def eval_fractal_noise(
    _inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    u, v, scale, octaves, lacunarity, gain, seed, evolution, cycles = _fractal_setup(params, context)
    total = np.zeros((context.height, context.width), dtype=np.float32)
    amplitude = 1.0
    amplitude_sum = 0.0
    frequency = scale
    for octave in range(octaves):
        cells_x, cells_y = _aspect_cells(frequency, context)
        z, z_period = _loop_z(evolution, cycles)
        sample = _periodic_gradient_noise_3d_uv(
            u, v, cells_x, cells_y, seed + octave * 1013, z, z_period
        )
        total += sample * np.float32(amplitude)
        amplitude_sum += amplitude
        amplitude *= gain
        frequency *= lacunarity
    total /= np.float32(max(amplitude_sum, 1e-6))
    return grayscale_rgba(_finish(
        total,
        float(params.get("contrast", 1.0)),
        float(params.get("balance", 0.0)),
        bool(params.get("invert", False)),
    ))


def eval_ridged_noise(
    _inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    """Weighted ridged multifractal with octave-to-octave ridge feedback."""
    u, v, scale, octaves, lacunarity, gain, seed, evolution, cycles = _fractal_setup(params, context)
    ridge_offset = max(float(params.get("ridge_offset", 1.0)), 0.01)
    ridge_sharpness = max(float(params.get("ridge_sharpness", 2.0)), 0.1)
    octave_weight = max(float(params.get("octave_weight", 2.0)), 0.0)
    valley_width = min(max(float(params.get("valley_width", 0.35)), 0.0), 1.0)

    total = np.zeros((context.height, context.width), dtype=np.float32)
    amplitude = 1.0
    amplitude_sum = 0.0
    feedback = np.ones_like(total, dtype=np.float32)
    frequency = scale
    for octave in range(octaves):
        cells_x, cells_y = _aspect_cells(frequency, context)
        z, z_period = _loop_z(evolution, cycles)
        base = _periodic_gradient_noise_3d_uv(
            u, v, cells_x, cells_y, seed + octave * 1013, z, z_period
        )
        signed = base * 2.0 - 1.0
        ridge = np.clip(ridge_offset - np.abs(signed) * (1.0 + valley_width), 0.0, 1.0)
        ridge = np.power(ridge, ridge_sharpness).astype(np.float32)
        weighted = ridge * feedback
        total += weighted * np.float32(amplitude)
        amplitude_sum += amplitude
        feedback = np.clip(weighted * octave_weight, 0.0, 1.0).astype(np.float32)
        amplitude *= gain
        frequency *= lacunarity
    total /= np.float32(max(amplitude_sum, 1e-6))
    return grayscale_rgba(_finish(
        total,
        float(params.get("contrast", 1.15)),
        float(params.get("balance", -0.08)),
        bool(params.get("invert", False)),
    ))


def eval_billow_noise(
    _inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    """Soft billowing masses built from paired, decorrelated gradient fields."""
    u, v, scale, octaves, lacunarity, gain, seed, evolution, cycles = _fractal_setup(params, context)
    puffiness = max(float(params.get("puffiness", 2.0)), 0.1)
    softness = min(max(float(params.get("softness", 0.55)), 0.0), 1.0)
    detail = min(max(float(params.get("detail", 0.35)), 0.0), 1.0)

    total = np.zeros((context.height, context.width), dtype=np.float32)
    amplitude = 1.0
    amplitude_sum = 0.0
    frequency = scale
    for octave in range(octaves):
        cells_x, cells_y = _aspect_cells(frequency, context)
        z, z_period = _loop_z(evolution, cycles)
        first = _periodic_gradient_noise_3d_uv(
            u, v, cells_x, cells_y, seed + octave * 1013, z, z_period
        ) * 2.0 - 1.0
        second = _periodic_gradient_noise_3d_uv(
            np.mod(u + 0.371, 1.0),
            np.mod(v + 0.619, 1.0),
            cells_x, cells_y, seed + 7919 + octave * 1237, z, z_period
        ) * 2.0 - 1.0
        combined = first * (1.0 - detail * 0.45) + second * (detail * 0.45)
        folded = np.abs(combined)
        puffed = 1.0 - np.power(np.clip(1.0 - folded, 0.0, 1.0), puffiness)
        soft = np.sqrt(np.clip(puffed, 0.0, 1.0))
        sample = puffed * (1.0 - softness) + soft * softness
        total += sample.astype(np.float32) * np.float32(amplitude)
        amplitude_sum += amplitude
        amplitude *= gain * (0.82 + detail * 0.18)
        frequency *= lacunarity
    total /= np.float32(max(amplitude_sum, 1e-6))
    return grayscale_rgba(_finish(
        total,
        float(params.get("contrast", 0.9)),
        float(params.get("balance", -0.08)),
        bool(params.get("invert", False)),
    ))


def _turbulence_warp(
    u: np.ndarray, v: np.ndarray, context: EvalContext, params: Mapping[str, Any]
) -> tuple[np.ndarray, np.ndarray]:
    seed = int(params.get("seed", 1))
    evolution = _evolution_phase(float(params.get("evolution", 0.0)))
    cycles = float(params.get("loop_cycles", 1.0))
    strength = float(params.get("warp_strength", 1.5))
    warp_scale = max(float(params.get("warp_scale", 2.0)), 1.0)
    warp_octaves = min(max(int(params.get("warp_octaves", 3)), 1), 6)
    direction = math.radians(float(params.get("flow_direction", 0.0)))
    directional_bias = min(max(float(params.get("directional_bias", 0.65)), 0.0), 1.0)

    wx = np.zeros_like(u, dtype=np.float32)
    wy = np.zeros_like(v, dtype=np.float32)
    amplitude = 1.0
    amplitude_sum = 0.0
    frequency = warp_scale
    for octave in range(warp_octaves):
        cells_x, cells_y = _aspect_cells(frequency, context)
        z, z_period = _loop_z(evolution, cycles)
        nx = _periodic_gradient_noise_3d_uv(
            u, v, cells_x, cells_y, seed + 2221 + octave * 811, z, z_period
        ) * 2.0 - 1.0
        ny = _periodic_gradient_noise_3d_uv(
            u, v, cells_x, cells_y, seed + 4447 + octave * 977, z, z_period
        ) * 2.0 - 1.0
        directed_x = math.cos(direction) * nx
        directed_y = math.sin(direction) * nx
        wx += (nx * (1.0 - directional_bias) + directed_x * directional_bias) * amplitude
        wy += (ny * (1.0 - directional_bias) + directed_y * directional_bias) * amplitude
        amplitude_sum += amplitude
        amplitude *= 0.5
        frequency *= 2.0
    wx /= np.float32(max(amplitude_sum, 1e-6))
    wy /= np.float32(max(amplitude_sum, 1e-6))
    offset = np.float32(strength * 0.12 / max(math.sqrt(max(float(params.get("scale", 4.0)), 1.0)), 1.0))
    return np.mod(u + wx * offset, 1.0), np.mod(v + wy * offset, 1.0)


def eval_turbulence_noise(
    _inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    """Multi-octave domain-warped turbulence with directional flow control."""
    u, v = _uv(context)
    u, v = _turbulence_warp(u, v, context, params)
    scale = max(float(params.get("scale", 4.0)), 1.0)
    octaves = min(max(int(params.get("octaves", 5)), 1), 10)
    lacunarity = max(float(params.get("lacunarity", 2.0)), 1.01)
    gain = min(max(float(params.get("gain", 0.5)), 0.0), 1.0)
    seed = int(params.get("seed", 1))
    evolution = _evolution_phase(float(params.get("evolution", 0.0)))
    cycles = float(params.get("loop_cycles", 1.0))
    fold = max(float(params.get("fold_sharpness", 0.68)), 0.1)

    total = np.zeros((context.height, context.width), dtype=np.float32)
    amplitude = 1.0
    amplitude_sum = 0.0
    frequency = scale
    for octave in range(octaves):
        cells_x, cells_y = _aspect_cells(frequency, context)
        z, z_period = _loop_z(evolution, cycles)
        signed = _periodic_gradient_noise_3d_uv(
            u, v, cells_x, cells_y, seed + octave * 1013, z, z_period
        ) * 2.0 - 1.0
        sample = np.power(np.clip(np.abs(signed), 0.0, 1.0), fold)
        total += sample.astype(np.float32) * np.float32(amplitude)
        amplitude_sum += amplitude
        amplitude *= gain
        frequency *= lacunarity
    total /= np.float32(max(amplitude_sum, 1e-6))
    return grayscale_rgba(_finish(
        total,
        float(params.get("contrast", 1.15)),
        float(params.get("balance", -0.05)),
        bool(params.get("invert", False)),
    ))


def _hash4(
    ix: np.ndarray,
    iy: np.ndarray,
    iz: np.ndarray,
    iw: np.ndarray,
    seed: int,
    salt: int = 0,
) -> np.ndarray:
    with np.errstate(over="ignore"):
        value = (
            np.asarray(ix, dtype=np.uint32) * np.uint32(0x9E3779B1)
            ^ np.asarray(iy, dtype=np.uint32) * np.uint32(0x85EBCA77)
            ^ np.asarray(iz, dtype=np.uint32) * np.uint32(0xC2B2AE3D)
            ^ np.asarray(iw, dtype=np.uint32) * np.uint32(0x27D4EB2F)
            ^ np.uint32(seed) * np.uint32(0x165667B1)
            ^ np.uint32(salt) * np.uint32(0xD3A2646C)
        )
    return _hash_u32(value)


def _gradient4(
    ix: np.ndarray, iy: np.ndarray, iz: np.ndarray, iw: np.ndarray, seed: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    components = [
        _hash01(_hash4(ix, iy, iz, iw, seed, salt)) * np.float32(2.0) - np.float32(1.0)
        for salt in range(4)
    ]
    length = np.sqrt(sum(component * component for component in components))
    length = np.maximum(length, np.float32(1e-6))
    return tuple((component / length).astype(np.float32) for component in components)  # type: ignore[return-value]


def _gradient_noise4(point: np.ndarray, seed: int) -> np.ndarray:
    base = np.floor(point).astype(np.int32)
    fraction = (point - base).astype(np.float32)
    t = _fade(fraction).astype(np.float32)
    x_mixed: list[np.ndarray] = []
    for ow in range(2):
        for oz in range(2):
            for oy in range(2):
                values: list[np.ndarray] = []
                for ox in range(2):
                    corner = base + np.array((ox, oy, oz, ow), dtype=np.int32)
                    gradient = _gradient4(
                        corner[..., 0].astype(np.uint32),
                        corner[..., 1].astype(np.uint32),
                        corner[..., 2].astype(np.uint32),
                        corner[..., 3].astype(np.uint32),
                        seed,
                    )
                    delta = fraction - np.array((ox, oy, oz, ow), dtype=np.float32)
                    values.append(sum(gradient[index] * delta[..., index] for index in range(4)))
                x_mixed.append(values[0] + (values[1] - values[0]) * t[..., 0])
    y_mixed = [
        x_mixed[index] + (x_mixed[index + 1] - x_mixed[index]) * t[..., 1]
        for index in range(0, 8, 2)
    ]
    z_mixed = [
        y_mixed[index] + (y_mixed[index + 1] - y_mixed[index]) * t[..., 2]
        for index in range(0, 4, 2)
    ]
    signed = z_mixed[0] + (z_mixed[1] - z_mixed[0]) * t[..., 3]
    return np.clip(0.5 + signed * 0.95, 0.0, 1.0).astype(np.float32)


def eval_simplex_noise(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    """Seamless isotropic 4D gradient noise sampled on a 2D torus.

    The result has the low directional bias artists expect from simplex-style
    noise while remaining exactly tileable for arbitrary continuous Scale.
    """
    u, v = _uv(context)
    scale = max(float(params.get("scale", 6.0)), 0.25)
    seed = int(params.get("seed", 1))
    evolution = _evolution_phase(float(params.get("evolution", 0.0)))
    cycles = float(params.get("loop_cycles", 1.0))
    angle = np.float32(TAU * evolution * cycles)
    # Start evolution at the unshifted texture and travel a closed circular path.
    shift_u = (np.cos(angle) - np.float32(1.0)) * np.float32(0.12)
    shift_v = np.sin(angle) * np.float32(0.12)
    radius = np.float32(scale / TAU)
    phase_u = np.float32(TAU) * (u + shift_u)
    phase_v = np.float32(TAU) * (v + shift_v)
    point = np.stack(
        (
            np.cos(phase_u) * radius,
            np.sin(phase_u) * radius,
            np.cos(phase_v) * radius,
            np.sin(phase_v) * radius,
        ),
        axis=-1,
    ).astype(np.float32)
    value = _gradient_noise4(point, seed)
    return grayscale_rgba(
        _finish(
            value,
            float(params.get("contrast", 1.0)),
            float(params.get("balance", 0.0)),
            bool(params.get("invert", False)),
        )
    )

def _random_layers(
    context: EvalContext, params: Mapping[str, Any], gaussian: bool
) -> np.ndarray:
    """Nearest-cell random layers used by White Noise and Gaussian's block mode."""
    scale = max(int(round(float(params.get("scale", 256.0)))), 1)
    seed = int(params.get("seed", 1))
    evolution = _evolution_phase(float(params.get("evolution", 0.0)))
    frames = max(int(params.get("loop_frames", 4)), 1)
    phase = evolution * frames
    layer0 = math.floor(phase) % frames
    layer1 = (layer0 + 1) % frames
    blend = float(_fade(np.float32(phase - math.floor(phase))))
    u, v = _uv(context)
    cx = np.floor(u * scale).astype(np.uint32)
    cy = np.floor(v * max(int(round(scale * context.height / max(context.width, 1))), 1)).astype(np.uint32)

    def layer(index: int) -> np.ndarray:
        h1 = _hash01(_hash3(cx, cy, index, seed, 0))
        if not gaussian:
            return h1
        h2 = np.maximum(_hash01(_hash3(cx, cy, index, seed, 1)), np.float32(1e-7))
        radius = np.sqrt(np.float32(-2.0) * np.log(h2))
        z = radius * np.cos(np.float32(TAU) * h1)
        mean = float(params.get("mean", 0.5))
        deviation = max(float(params.get("deviation", 0.15)), 0.0001)
        return np.clip(mean + z * deviation, 0.0, 1.0).astype(np.float32)

    a = layer(layer0)
    b = layer(layer1)
    return (a + (b - a) * np.float32(blend)).astype(np.float32)


def _gaussian_lattice_value(
    ix: np.ndarray, iy: np.ndarray, iz: int, seed: int, mean: float, deviation: float
) -> np.ndarray:
    first = np.maximum(_hash01(_hash3(ix, iy, iz, seed, 0)), np.float32(1e-7))
    second = _hash01(_hash3(ix, iy, iz, seed, 1))
    radius = np.sqrt(np.float32(-2.0) * np.log(first))
    sample = radius * np.cos(np.float32(TAU) * second)
    return np.clip(np.float32(mean) + sample * np.float32(deviation), 0.0, 1.0).astype(np.float32)


def _periodic_gaussian_field(
    u: np.ndarray,
    v: np.ndarray,
    cells_x: int,
    cells_y: int,
    seed: int,
    z: float,
    z_period: int,
    mean: float,
    deviation: float,
    smoothness: float,
) -> np.ndarray:
    cells_x = max(int(cells_x), 1)
    cells_y = max(int(cells_y), 1)
    z_period = max(int(z_period), 1)
    px = np.mod(u, 1.0) * np.float32(cells_x)
    py = np.mod(v, 1.0) * np.float32(cells_y)
    x_base = np.floor(px).astype(np.int32)
    y_base = np.floor(py).astype(np.int32)
    fx = (px - x_base).astype(np.float32)
    fy = (py - y_base).astype(np.float32)
    z_base = math.floor(z)
    fz = np.float32(z - z_base)

    smoothness = min(max(float(smoothness), 0.0), 1.0)
    hard_x = (fx >= 0.5).astype(np.float32)
    hard_y = (fy >= 0.5).astype(np.float32)
    hard_z = np.float32(1.0 if fz >= 0.5 else 0.0)
    tx = hard_x * np.float32(1.0 - smoothness) + _fade(fx).astype(np.float32) * np.float32(smoothness)
    ty = hard_y * np.float32(1.0 - smoothness) + _fade(fy).astype(np.float32) * np.float32(smoothness)
    tz = hard_z * np.float32(1.0 - smoothness) + np.float32(_fade(fz)) * np.float32(smoothness)

    x0 = np.mod(x_base, cells_x).astype(np.uint32)
    x1 = np.mod(x_base + 1, cells_x).astype(np.uint32)
    y0 = np.mod(y_base, cells_y).astype(np.uint32)
    y1 = np.mod(y_base + 1, cells_y).astype(np.uint32)
    z0 = z_base % z_period
    z1 = (z0 + 1) % z_period

    def plane(zi: int) -> np.ndarray:
        a = _gaussian_lattice_value(x0, y0, zi, seed, mean, deviation)
        b = _gaussian_lattice_value(x1, y0, zi, seed, mean, deviation)
        c = _gaussian_lattice_value(x0, y1, zi, seed, mean, deviation)
        d = _gaussian_lattice_value(x1, y1, zi, seed, mean, deviation)
        top = a + (b - a) * tx
        bottom = c + (d - c) * tx
        return top + (bottom - top) * ty

    low = plane(z0)
    high = plane(z1)
    return (low + (high - low) * tz).astype(np.float32)


def eval_white_noise(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    value = _random_layers(context, params, False)
    return grayscale_rgba(_finish(value, float(params.get("contrast", 1.0)), float(params.get("balance", 0.0)), bool(params.get("invert", False))))


def eval_gaussian_noise(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    u, v = _uv(context)
    scale = max(float(params.get("scale", 16.0)), 1.0)
    seed = int(params.get("seed", 1))
    evolution = _evolution_phase(float(params.get("evolution", 0.0)))
    loop_cycles = float(params.get("loop_cycles", 1.0))
    mean = float(params.get("mean", 0.5))
    deviation = max(float(params.get("deviation", 0.18)), 0.0001)
    smoothness = min(max(float(params.get("smoothness", 1.0)), 0.0), 1.0)
    detail = min(max(float(params.get("detail", 0.25)), 0.0), 1.0)
    u, v = _domain_warp(
        u, v, context, scale, seed, evolution, loop_cycles,
        float(params.get("disorder", 0.45)), float(params.get("disorder_scale", 4.0)),
    )
    cells_x, cells_y = _aspect_cells(scale, context)
    z, z_period = _loop_z(evolution, loop_cycles)
    first = _periodic_gaussian_field(
        u, v, cells_x, cells_y, seed, z, z_period, mean, deviation, smoothness
    )
    # Blend a torus-safe diagonal lattice to suppress the obvious square grid
    # while preserving the Gaussian value distribution and exact tiling.
    second = _periodic_gaussian_field(
        np.mod(u + v, 1.0), np.mod(u - v, 1.0),
        cells_x, cells_y, seed + 1777, z, z_period, mean, deviation, smoothness
    )
    first_weight = np.float32(0.75)
    second_weight = np.float32(0.66)
    base = np.float32(mean) + (
        (first - np.float32(mean)) * first_weight
        + (second - np.float32(mean)) * second_weight
    ) / np.float32(math.sqrt(float(first_weight * first_weight + second_weight * second_weight)))
    if detail > 1e-6:
        detail_cells_x, detail_cells_y = _aspect_cells(scale * 4.0, context)
        fine = _periodic_gaussian_field(
            u, v, detail_cells_x, detail_cells_y, seed + 3571, z, z_period,
            mean, deviation, smoothness
        )
        weight = np.float32(detail * 0.35)
        normalizer = np.float32(math.sqrt(1.0 + float(weight * weight)))
        value = np.float32(mean) + ((base - np.float32(mean)) + (fine - np.float32(mean)) * weight) / normalizer
    else:
        value = base
    value = np.clip(value, 0.0, 1.0).astype(np.float32)
    return grayscale_rgba(_finish(value, float(params.get("contrast", 1.0)), float(params.get("balance", 0.0)), bool(params.get("invert", False))))


def _metric(dx: np.ndarray, dy: np.ndarray, mode: str, exponent: float) -> np.ndarray:
    ax = np.abs(dx)
    ay = np.abs(dy)
    if mode == "Manhattan":
        return ax + ay
    if mode == "Chebyshev":
        return np.maximum(ax, ay)
    if mode == "Minkowski":
        p = max(float(exponent), 0.25)
        return np.power(np.power(ax, p) + np.power(ay, p), 1.0 / p)
    return np.sqrt(dx * dx + dy * dy)


def _cellular_fields(
    context: EvalContext,
    params: Mapping[str, Any],
    *,
    points_per_cell: int = 1,
    u: np.ndarray | None = None,
    v: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if u is None or v is None:
        u, v = _uv(context)
    scale = max(float(params.get("scale", 8.0)), 1.0)
    cells_x, cells_y = _aspect_cells(scale, context)
    point_x = np.mod(u, 1.0) * np.float32(cells_x)
    point_y = np.mod(v, 1.0) * np.float32(cells_y)
    base_x = np.floor(point_x).astype(np.int32)
    base_y = np.floor(point_y).astype(np.int32)
    seed = int(params.get("seed", 1))
    jitter = min(max(float(params.get("jitter", 1.0)), 0.0), 1.0)
    evolution = _evolution_phase(float(params.get("evolution", 0.0)))
    cycles = float(params.get("loop_cycles", 1.0))
    metric = str(params.get("distance_metric", "Euclidean"))
    exponent = float(params.get("distance_exponent", 2.0))
    f1 = np.full_like(point_x, np.float32(1e9))
    f2 = np.full_like(point_x, np.float32(1e9))
    nearest_value = np.zeros_like(point_x, dtype=np.float32)
    phase = np.float32(TAU * evolution * cycles)
    for oy in range(-1, 2):
        for ox in range(-1, 2):
            neighbour_x = base_x + ox
            neighbour_y = base_y + oy
            wrapped_x = np.mod(neighbour_x, cells_x).astype(np.uint32)
            wrapped_y = np.mod(neighbour_y, cells_y).astype(np.uint32)
            for point_index in range(max(points_per_cell, 1)):
                h_angle = _hash01(_hash3(wrapped_x, wrapped_y, point_index, seed, 3))
                h_radius = _hash01(_hash3(wrapped_x, wrapped_y, point_index, seed, 4))
                angle = h_angle * np.float32(TAU) + phase
                radius = np.float32(jitter * 0.48) * (np.float32(0.35) + np.float32(0.65) * h_radius)
                feature_x = neighbour_x.astype(np.float32) + 0.5 + np.cos(angle) * radius
                feature_y = neighbour_y.astype(np.float32) + 0.5 + np.sin(angle) * radius
                distance = _metric(feature_x - point_x, feature_y - point_y, metric, exponent).astype(np.float32)
                closer = distance < f1
                f2 = np.where(closer, f1, np.minimum(f2, distance))
                f1 = np.where(closer, distance, f1)
                cell_value = _hash01(_hash3(wrapped_x, wrapped_y, point_index, seed, 5))
                nearest_value = np.where(closer, cell_value, nearest_value)
    return f1, f2, nearest_value


def eval_voronoi_noise(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    f1, f2, cell_value = _cellular_fields(context, params)
    mode = str(params.get("output_mode", params.get("mode", "Distance")))
    if mode == "Edge":
        width = max(float(params.get("edge_width", 0.08)), 0.0)
        softness = max(float(params.get("edge_softness", 0.02)), 1e-5)
        raw = f2 - f1
        t = np.clip((raw - width) / softness, 0.0, 1.0)
        value = 1.0 - (t * t * (3.0 - 2.0 * t))
    elif mode in ("Cell Value", "Cell Random"):
        value = cell_value
    elif mode in ("F2 - F1", "F2-F1"):
        value = np.clip((f2 - f1) * 1.75, 0.0, 1.0)
    else:
        value = np.clip(f1 * 1.45, 0.0, 1.0)
    return grayscale_rgba(_finish(value, float(params.get("contrast", 1.0)), float(params.get("balance", 0.0)), bool(params.get("invert", False))))


def eval_worley_noise(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    points = min(max(int(params.get("points_per_cell", 2)), 1), 3)
    f1, f2, _cell = _cellular_fields(context, params, points_per_cell=points)
    mode = str(params.get("output_mode", "F1"))
    if mode == "F2":
        value = np.clip(f2 * 0.8, 0.0, 1.0)
    elif mode in ("F2 - F1", "F2-F1"):
        value = np.clip((f2 - f1) * 1.75, 0.0, 1.0)
    else:
        value = np.clip(f1 * 1.45, 0.0, 1.0)
    return grayscale_rgba(_finish(value, float(params.get("contrast", 1.0)), float(params.get("balance", 0.0)), bool(params.get("invert", False))))


def eval_voronoi_fractal(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    u, v = _uv(context)
    scale = max(float(params.get("scale", 3.0)), 1.0)
    octaves = min(max(int(params.get("octaves", 4)), 1), 8)
    lacunarity = max(float(params.get("lacunarity", 2.0)), 1.01)
    gain = min(max(float(params.get("gain", 0.5)), 0.0), 1.0)
    total = np.zeros((context.height, context.width), dtype=np.float32)
    amplitude = 1.0
    amplitude_sum = 0.0
    frequency = scale
    base_params = dict(params)
    for octave in range(octaves):
        base_params["scale"] = frequency
        base_params["seed"] = int(params.get("seed", 1)) + octave * 1301
        base_params["evolution"] = _evolution_phase(float(params.get("evolution", 0.0)))
        f1, f2, _cell = _cellular_fields(context, base_params, u=u, v=v)
        mode = str(params.get("fractal_mode", "Distance"))
        sample = np.clip((f2 - f1) * 1.75, 0.0, 1.0) if mode == "Edges" else np.clip(f1 * 1.45, 0.0, 1.0)
        total += sample * np.float32(amplitude)
        amplitude_sum += amplitude
        amplitude *= gain
        frequency *= lacunarity
    total /= np.float32(max(amplitude_sum, 1e-6))
    return grayscale_rgba(_finish(total, float(params.get("contrast", 1.0)), float(params.get("balance", 0.0)), bool(params.get("invert", False))))


def bundled_package_evaluator(type_id: str) -> Callable | None:
    if type_id == "org.vfxtexturelab.voronoi_noise":
        return eval_voronoi_noise
    return None


def _base_noise_parameters() -> tuple[ParameterSpec, ...]:
    f = ParameterSpec
    return (
        f("scale", "Scale", "float", 8.0, 1.0, 128.0, 1.0, animatable=True,
          description="Whole repeating cells across the texture; integer values preserve exact tiling."),
        f("seed", "Seed", "int", 1, 0, 999999, 1, animatable=True, slider_maximum=1000, fine_step=1, coarse_step=10),
        f("evolution", "Evolution", "float", 0.0, 0.0, 1.0, 0.001, animatable=True,
          description="Normalised loop phase. Connect Loop Phase directly; 0 and 1 are identical when Loop Cycles is 1."),
        f("loop_cycles", "Loop Cycles", "float", 1.0, 0.25, 16.0, 0.25, animatable=True),
        f("disorder", "Disorder", "float", 0.0, 0.0, 3.0, 0.01, animatable=True),
        f("disorder_scale", "Disorder Scale", "float", 3.0, 1.0, 64.0, 1.0, animatable=True),
        f("contrast", "Contrast", "float", 1.0, 0.05, 8.0, 0.05, animatable=True),
        f("balance", "Balance", "float", 0.0, -1.0, 1.0, 0.01, animatable=True),
        f("invert", "Invert", "bool", False),
    )


def _fractal_parameters() -> tuple[ParameterSpec, ...]:
    f = ParameterSpec
    return (
        f("scale", "Scale", "float", 4.0, 1.0, 64.0, 1.0, animatable=True),
        f("octaves", "Octaves", "int", 5, 1, 10, 1, animatable=True),
        f("lacunarity", "Lacunarity", "float", 2.0, 1.01, 4.0, 0.01, animatable=True),
        f("gain", "Gain / Roughness", "float", 0.5, 0.0, 1.0, 0.01, animatable=True),
        f("seed", "Seed", "int", 1, 0, 999999, 1, animatable=True, slider_maximum=1000, fine_step=1, coarse_step=10),
        f("evolution", "Evolution", "float", 0.0, 0.0, 1.0, 0.001, animatable=True,
          description="Normalised loop phase. Connect Loop Phase directly; 0 and 1 form one complete loop."),
        f("loop_cycles", "Loop Cycles", "float", 1.0, 0.25, 16.0, 0.25, animatable=True),
        f("disorder", "Disorder", "float", 0.0, 0.0, 3.0, 0.01, animatable=True),
        f("disorder_scale", "Disorder Scale", "float", 3.0, 1.0, 64.0, 1.0, animatable=True),
        f("contrast", "Contrast", "float", 1.0, 0.05, 8.0, 0.05, animatable=True),
        f("balance", "Balance", "float", 0.0, -1.0, 1.0, 0.01, animatable=True),
        f("invert", "Invert", "bool", False),
    )


def _ridged_parameters() -> tuple[ParameterSpec, ...]:
    f = ParameterSpec
    return (
        f("scale", "Scale", "float", 4.0, 1.0, 64.0, 1.0, animatable=True),
        f("octaves", "Octaves", "int", 6, 1, 10, 1, animatable=True),
        f("lacunarity", "Lacunarity", "float", 2.0, 1.01, 4.0, 0.01, animatable=True),
        f("gain", "Gain / Roughness", "float", 0.5, 0.0, 1.0, 0.01, animatable=True),
        f("seed", "Seed", "int", 1, 0, 999999, 1, animatable=True, slider_maximum=1000, fine_step=1, coarse_step=10),
        f("evolution", "Evolution", "float", 0.0, 0.0, 1.0, 0.001, animatable=True,
          description="Normalised loop phase. Connect Loop Phase directly; 0 and 1 form one complete loop."),
        f("loop_cycles", "Loop Cycles", "float", 1.0, 0.25, 16.0, 0.25, animatable=True),
        f("disorder", "Disorder", "float", 0.15, 0.0, 3.0, 0.01, animatable=True),
        f("disorder_scale", "Disorder Scale", "float", 3.0, 1.0, 64.0, 1.0, animatable=True),
        f("ridge_offset", "Ridge Offset", "float", 1.0, 0.25, 2.0, 0.01, animatable=True),
        f("ridge_sharpness", "Ridge Sharpness", "float", 2.2, 0.25, 8.0, 0.05, animatable=True),
        f("octave_weight", "Octave Weight", "float", 2.0, 0.0, 4.0, 0.05, animatable=True),
        f("valley_width", "Valley Width", "float", 0.35, 0.0, 1.0, 0.01, animatable=True),
        f("contrast", "Contrast", "float", 1.15, 0.05, 8.0, 0.05, animatable=True),
        f("balance", "Balance", "float", -0.08, -1.0, 1.0, 0.01, animatable=True),
        f("invert", "Invert", "bool", False),
    )


def _billow_parameters() -> tuple[ParameterSpec, ...]:
    f = ParameterSpec
    return (
        f("scale", "Scale", "float", 3.0, 1.0, 64.0, 1.0, animatable=True),
        f("octaves", "Octaves", "int", 5, 1, 10, 1, animatable=True),
        f("lacunarity", "Lacunarity", "float", 1.85, 1.01, 4.0, 0.01, animatable=True),
        f("gain", "Gain / Roughness", "float", 0.42, 0.0, 1.0, 0.01, animatable=True),
        f("seed", "Seed", "int", 1, 0, 999999, 1, animatable=True, slider_maximum=1000, fine_step=1, coarse_step=10),
        f("evolution", "Evolution", "float", 0.0, 0.0, 1.0, 0.001, animatable=True,
          description="Normalised loop phase. Connect Loop Phase directly; 0 and 1 form one complete loop."),
        f("loop_cycles", "Loop Cycles", "float", 1.0, 0.25, 16.0, 0.25, animatable=True),
        f("disorder", "Disorder", "float", 0.1, 0.0, 3.0, 0.01, animatable=True),
        f("disorder_scale", "Disorder Scale", "float", 2.0, 1.0, 64.0, 1.0, animatable=True),
        f("puffiness", "Puffiness", "float", 2.0, 0.1, 6.0, 0.05, animatable=True),
        f("softness", "Softness", "float", 0.55, 0.0, 1.0, 0.01, animatable=True),
        f("detail", "Fine Detail", "float", 0.35, 0.0, 1.0, 0.01, animatable=True),
        f("contrast", "Contrast", "float", 0.9, 0.05, 8.0, 0.05, animatable=True),
        f("balance", "Balance", "float", -0.08, -1.0, 1.0, 0.01, animatable=True),
        f("invert", "Invert", "bool", False),
    )


def _turbulence_parameters() -> tuple[ParameterSpec, ...]:
    f = ParameterSpec
    return (
        f("scale", "Detail Scale", "float", 5.0, 1.0, 64.0, 1.0, animatable=True),
        f("octaves", "Detail Octaves", "int", 5, 1, 10, 1, animatable=True),
        f("lacunarity", "Lacunarity", "float", 2.0, 1.01, 4.0, 0.01, animatable=True),
        f("gain", "Detail Gain", "float", 0.5, 0.0, 1.0, 0.01, animatable=True),
        f("seed", "Seed", "int", 1, 0, 999999, 1, animatable=True, slider_maximum=1000, fine_step=1, coarse_step=10),
        f("evolution", "Evolution", "float", 0.0, 0.0, 1.0, 0.001, animatable=True,
          description="Normalised loop phase. Connect Loop Phase directly; 0 and 1 form one complete loop."),
        f("loop_cycles", "Loop Cycles", "float", 1.0, 0.25, 16.0, 0.25, animatable=True),
        f("warp_strength", "Warp Strength", "float", 1.5, 0.0, 6.0, 0.01, animatable=True),
        f("warp_scale", "Warp Scale", "float", 2.0, 1.0, 32.0, 1.0, animatable=True),
        f("warp_octaves", "Warp Octaves", "int", 3, 1, 6, 1, animatable=True),
        f("flow_direction", "Flow Direction", "float", 0.0, -180.0, 180.0, 1.0, animatable=True, fine_step=1.0, coarse_step=5.0, editor="angle", unit="degrees"),
        f("directional_bias", "Directional Bias", "float", 0.65, 0.0, 1.0, 0.01, animatable=True),
        f("fold_sharpness", "Fold Sharpness", "float", 0.68, 0.1, 4.0, 0.01, animatable=True),
        f("contrast", "Contrast", "float", 1.15, 0.05, 8.0, 0.05, animatable=True),
        f("balance", "Balance", "float", -0.05, -1.0, 1.0, 0.01, animatable=True),
        f("invert", "Invert", "bool", False),
    )


def register_noise_nodes(registry: NodeRegistry) -> None:
    f = ParameterSpec
    definitions = [
        NodeDefinition(
            "noise.value", "Value Noise", "Noise", eval_value_noise,
            parameters=_base_noise_parameters(),
            description="Smooth periodic value noise. Deliberately retains soft cell-like character without pretending to be Perlin noise.",
            accent=_NOISE_ACCENT, tags=("value", "cells", "seamless", "loop"),
            output_format="r16f", gpu_kernel="base_noise.wgsl",
        ),
        NodeDefinition(
            "noise.perlin", "Gradient / Perlin Noise", "Noise", eval_perlin_noise,
            parameters=_base_noise_parameters(),
            description="Periodic gradient noise with organic, lattice-resistant forms and loopable evolution.",
            accent=_NOISE_ACCENT, tags=("perlin", "gradient", "organic", "seamless", "loop"),
            output_format="r16f", gpu_kernel="base_noise.wgsl",
        ),
        NodeDefinition(
            "noise.fractal", "Fractal Noise", "Noise", eval_fractal_noise,
            parameters=_fractal_parameters(),
            description="High-quality periodic gradient FBM with lacunarity, roughness, disorder and loopable evolution.",
            accent=_NOISE_ACCENT, tags=("fbm", "perlin", "cloud", "terrain", "seamless"),
            output_format="r16f", gpu_kernel="fractal_family.wgsl",
        ),
        NodeDefinition(
            "noise.simplex", "Simplex-style Noise", "Noise", eval_simplex_noise,
            parameters=(
                f("scale", "Scale", "float", 6.0, 0.25, 128.0, 0.25, animatable=True),
                f("seed", "Seed", "int", 1, 0, 999999, 1, animatable=True, slider_maximum=1000, fine_step=1, coarse_step=10),
                f("evolution", "Evolution", "float", 0.0, 0.0, 1.0, 0.001, animatable=True,
          description="Normalised loop phase. Connect Loop Phase directly; 0 and 1 form one complete loop."),
                f("loop_cycles", "Loop Cycles", "float", 1.0, 0.25, 16.0, 0.25, animatable=True),
                f("contrast", "Contrast", "float", 1.0, 0.05, 8.0, 0.05, animatable=True),
                f("balance", "Balance", "float", 0.0, -1.0, 1.0, 0.01, animatable=True),
                f("invert", "Invert", "bool", False),
            ),
            description="Isotropic simplex-style gradient noise sampled on a seamless 4D torus with circular loop motion.",
            accent=_NOISE_ACCENT, tags=("simplex", "isotropic", "organic", "seamless"),
            output_format="r16f", gpu_kernel="simplex_noise.wgsl",
        ),
        NodeDefinition(
            "noise.worley", "Worley Noise", "Noise", eval_worley_noise,
            parameters=(
                f("scale", "Scale", "float", 8.0, 1.0, 128.0, 1.0, animatable=True),
                f("seed", "Seed", "int", 1, 0, 999999, 1, animatable=True, slider_maximum=1000, fine_step=1, coarse_step=10),
                f("points_per_cell", "Points per Cell", "int", 2, 1, 3, 1, animatable=True),
                f("jitter", "Jitter", "float", 1.0, 0.0, 1.0, 0.01, animatable=True),
                f("evolution", "Evolution", "float", 0.0, 0.0, 1.0, 0.001, animatable=True,
          description="Normalised loop phase. Connect Loop Phase directly; 0 and 1 form one complete loop."),
                f("loop_cycles", "Loop Cycles", "float", 1.0, 0.25, 16.0, 0.25, animatable=True),
                f("distance_metric", "Distance Metric", "enum", "Euclidean", options=("Euclidean", "Manhattan", "Chebyshev", "Minkowski")),
                f("distance_exponent", "Minkowski Exponent", "float", 2.0, 0.25, 8.0, 0.05, animatable=True),
                f("output_mode", "Preview Output", "enum", "F1", options=("F1", "F2", "F2 - F1")),
                f("contrast", "Contrast", "float", 1.0, 0.05, 8.0, 0.05, animatable=True),
                f("balance", "Balance", "float", 0.0, -1.0, 1.0, 0.01, animatable=True),
                f("invert", "Invert", "bool", False),
            ),
            description="Multi-feature cellular noise with F1, F2 and boundary-distance outputs.",
            accent=_NOISE_ACCENT, tags=("worley", "cellular", "distance", "seamless"),
            output_format="r16f", gpu_kernel="worley_noise.wgsl",
            outputs=("F1", "F2", "F2 - F1"), output_name="F1",
            named_output_parameter="output_mode",
            named_output_values=(("F1", "F1"), ("F2", "F2"), ("F2 - F1", "F2 - F1")),
        ),
        NodeDefinition(
            "noise.white", "White Noise", "Noise", eval_white_noise,
            parameters=(
                f("scale", "Cell Resolution", "float", 256.0, 1.0, 2048.0, 1.0, animatable=True),
                f("seed", "Seed", "int", 1, 0, 999999, 1, animatable=True, slider_maximum=1000, fine_step=1, coarse_step=10),
                f("evolution", "Evolution", "float", 0.0, 0.0, 1.0, 0.001, animatable=True,
          description="Normalised loop phase. Connect Loop Phase directly; 0 and 1 form one complete loop."),
                f("loop_frames", "Evolution Steps", "int", 4, 1, 64, 1, animatable=True,
                  description="Distinct random states traversed during one 0–1 Evolution loop. Lower values animate more calmly."),
                f("contrast", "Contrast", "float", 1.0, 0.05, 8.0, 0.05, animatable=True),
                f("balance", "Balance", "float", 0.0, -1.0, 1.0, 0.01, animatable=True),
                f("invert", "Invert", "bool", False),
            ),
            description="Uniform random noise with controllable cell resolution and smoothly looped random layers.",
            accent=_NOISE_ACCENT, tags=("random", "static", "dither", "grain"),
            output_format="r16f", gpu_kernel="random_noise.wgsl",
        ),
        NodeDefinition(
            "noise.gaussian", "Gaussian Noise", "Noise", eval_gaussian_noise,
            parameters=(
                f("scale", "Scale", "float", 16.0, 1.0, 256.0, 1.0, animatable=True),
                f("seed", "Seed", "int", 1, 0, 999999, 1, animatable=True, slider_maximum=1000, fine_step=1, coarse_step=10),
                f("mean", "Mean", "float", 0.5, 0.0, 1.0, 0.01, animatable=True),
                f("deviation", "Deviation", "float", 0.18, 0.001, 1.0, 0.001, animatable=True),
                f("smoothness", "Smoothness", "float", 1.0, 0.0, 1.0, 0.01, animatable=True,
                  description="0 keeps hard random cells; 1 smoothly interpolates the Gaussian lattice."),
                f("detail", "Fine Detail", "float", 0.4, 0.0, 1.0, 0.01, animatable=True),
                f("disorder", "Disorder", "float", 0.45, 0.0, 3.0, 0.01, animatable=True),
                f("disorder_scale", "Disorder Scale", "float", 4.0, 1.0, 64.0, 1.0, animatable=True),
                f("evolution", "Evolution", "float", 0.0, 0.0, 1.0, 0.001, animatable=True,
          description="Normalised loop phase. Connect Loop Phase directly; 0 and 1 form one complete loop."),
                f("loop_cycles", "Loop Cycles", "float", 1.0, 0.25, 16.0, 0.25, animatable=True),
                f("contrast", "Contrast", "float", 1.0, 0.05, 8.0, 0.05, animatable=True),
                f("balance", "Balance", "float", 0.0, -1.0, 1.0, 0.01, animatable=True),
                f("invert", "Invert", "bool", False),
            ),
            description="Smooth normally distributed lattice noise, with optional hard-cell mode, detail, disorder and looped evolution.",
            accent=_NOISE_ACCENT, tags=("gaussian", "normal distribution", "cloud", "grain", "random"),
            output_format="r16f", gpu_kernel="gaussian_noise.wgsl",
        ),
        NodeDefinition(
            "noise.ridged", "Ridged Noise", "Noise/Fractal Variations", eval_ridged_noise,
            parameters=_ridged_parameters(),
            description="Weighted ridged multifractal with octave feedback for branching mountain crests and vein networks.",
            accent=_NOISE_ACCENT, tags=("ridge", "mountain", "terrain", "multifractal"), output_format="r16f", gpu_kernel="ridged_noise.wgsl",
        ),
        NodeDefinition(
            "noise.billow", "Billow Noise", "Noise/Fractal Variations", eval_billow_noise,
            parameters=_billow_parameters(),
            description="Soft, inflated cloud masses made from paired decorrelated fields with puffiness and softness controls.",
            accent=_NOISE_ACCENT, tags=("cloud", "billow", "smoke", "soft"), output_format="r16f", gpu_kernel="billow_noise.wgsl",
        ),
        NodeDefinition(
            "noise.turbulence", "Turbulence Noise", "Noise/Fractal Variations", eval_turbulence_noise,
            parameters=_turbulence_parameters(),
            description="Multi-octave domain-warped and directionally biased folded noise for flames, smoke and distortion.",
            accent=_NOISE_ACCENT, tags=("turbulence", "warp", "smoke", "flame", "distortion"), output_format="r16f", gpu_kernel="turbulence_noise.wgsl",
        ),
        NodeDefinition(
            "noise.voronoi_fractal", "Voronoi Fractal", "Noise/Fractal Variations", eval_voronoi_fractal,
            parameters=(
                f("scale", "Scale", "float", 3.0, 1.0, 32.0, 1.0, animatable=True),
                f("octaves", "Octaves", "int", 4, 1, 8, 1, animatable=True),
                f("lacunarity", "Lacunarity", "float", 2.0, 1.01, 4.0, 0.01, animatable=True),
                f("gain", "Gain / Roughness", "float", 0.5, 0.0, 1.0, 0.01, animatable=True),
                f("seed", "Seed", "int", 1, 0, 999999, 1, animatable=True, slider_maximum=1000, fine_step=1, coarse_step=10),
                f("jitter", "Jitter", "float", 1.0, 0.0, 1.0, 0.01, animatable=True),
                f("evolution", "Evolution", "float", 0.0, 0.0, 1.0, 0.001, animatable=True,
          description="Normalised loop phase. Connect Loop Phase directly; 0 and 1 form one complete loop."),
                f("loop_cycles", "Loop Cycles", "float", 1.0, 0.25, 16.0, 0.25, animatable=True),
                f("fractal_mode", "Mode", "enum", "Distance", options=("Distance", "Edges")),
                f("contrast", "Contrast", "float", 1.0, 0.05, 8.0, 0.05, animatable=True),
                f("balance", "Balance", "float", 0.0, -1.0, 1.0, 0.01, animatable=True),
                f("invert", "Invert", "bool", False),
            ),
            description="Layered cellular distance or edge fields with loopable point motion.",
            accent=_NOISE_ACCENT, tags=("voronoi", "cellular", "fractal", "terrain"), output_format="r16f", gpu_kernel="voronoi_fractal.wgsl",
        ),
    ]
    for definition in definitions:
        registry.register(replace(
            definition,
            output_kinds=tuple((name, "grayscale") for name in definition.output_names),
            default_image_kind="grayscale",
        ))
