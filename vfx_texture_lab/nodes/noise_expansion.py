from __future__ import annotations

"""Artist-facing procedural noises introduced in VFX Texture Lab 0.47.0.

The generators deliberately share low-level periodic noise and feature-placement
primitives, but each public node owns a distinct construction and parameter set.
They are inspired by the kinds of reusable noises found in Substance Designer,
Material Maker and IlluGen; none attempts to reproduce a proprietary graph.
"""

import math
from dataclasses import replace
from typing import Any, Mapping

import numpy as np

from .base import EvalContext, ImageArray, NodeDefinition, ParameterSpec
from .image_ops import grayscale_rgba
from .noise import (
    TAU,
    _aspect_cells,
    _domain_warp,
    _evolution_phase,
    _finish,
    _hash01,
    _hash3,
    _loop_z,
    _periodic_gradient_noise_3d_uv,
    _periodic_value_noise_3d_uv,
    _uv,
)
from .registry import NodeRegistry

_NOISE_ACCENT = "#4fa6a3"


def _smoothstep(edge0: float | np.ndarray, edge1: float | np.ndarray, value: np.ndarray) -> np.ndarray:
    denominator = np.asarray(edge1, dtype=np.float32) - np.asarray(edge0, dtype=np.float32)
    denominator = np.where(np.abs(denominator) < 1e-7, np.float32(1e-7), denominator)
    t = np.clip((value - edge0) / denominator, 0.0, 1.0).astype(np.float32)
    return (t * t * (3.0 - 2.0 * t)).astype(np.float32)


def _directional_disorder(
    u: np.ndarray,
    v: np.ndarray,
    context: EvalContext,
    *,
    scale: float,
    seed: int,
    evolution: float,
    cycles: float,
    amount: float,
    disorder_scale: float,
    anisotropy: float,
    angle_degrees: float,
) -> tuple[np.ndarray, np.ndarray]:
    if abs(amount) <= 1e-7:
        return u, v
    cells_x, cells_y = _aspect_cells(max(disorder_scale, 1.0), context)
    z, z_period = _loop_z(evolution, cycles)
    first = _periodic_gradient_noise_3d_uv(u, v, cells_x, cells_y, seed + 411, z, z_period) * 2.0 - 1.0
    second = _periodic_gradient_noise_3d_uv(u, v, cells_x, cells_y, seed + 977, z, z_period) * 2.0 - 1.0
    angle = math.radians(angle_degrees)
    direction_x, direction_y = math.cos(angle), math.sin(angle)
    anisotropy = min(max(float(anisotropy), 0.0), 1.0)
    isotropic_x = first
    isotropic_y = second
    directional_x = first * np.float32(direction_x)
    directional_y = first * np.float32(direction_y)
    displacement_x = isotropic_x * np.float32(1.0 - anisotropy) + directional_x * np.float32(anisotropy)
    displacement_y = isotropic_y * np.float32(1.0 - anisotropy) + directional_y * np.float32(anisotropy)
    strength = np.float32(float(amount) * 0.16 / max(math.sqrt(max(scale, 1.0)), 1.0))
    return np.mod(u + displacement_x * strength, 1.0), np.mod(v + displacement_y * strength, 1.0)


def _cloud_disorder(
    u: np.ndarray,
    v: np.ndarray,
    context: EvalContext,
    *,
    scale: float,
    seed: int,
    evolution: float,
    cycles: float,
    amount: float,
    disorder_scale: float,
    anisotropy: float,
    angle_degrees: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply a deliberately gentle value-noise warp for cloud generators.

    Gradient-noise displacement makes coherent curls and closed contour loops,
    which is useful for turbulence but was the wrong visual primitive for the
    Clouds family.  Smooth value fields keep the broad vapour structure while
    still allowing animated disorder and directional bias.
    """
    if abs(amount) <= 1e-7:
        return u, v
    cells_x, cells_y = _aspect_cells(max(disorder_scale, 1.0), context)
    z, z_period = _loop_z(evolution, cycles)
    first = _periodic_value_noise_3d_uv(u, v, cells_x, cells_y, seed + 411, z, z_period) * 2.0 - 1.0
    second = _periodic_value_noise_3d_uv(u, v, cells_x, cells_y, seed + 977, z, z_period) * 2.0 - 1.0
    angle = math.radians(angle_degrees)
    direction_x, direction_y = math.cos(angle), math.sin(angle)
    anisotropy = min(max(float(anisotropy), 0.0), 1.0)
    displacement_x = first * np.float32(1.0 - anisotropy) + first * np.float32(direction_x * anisotropy)
    displacement_y = second * np.float32(1.0 - anisotropy) + first * np.float32(direction_y * anisotropy)
    strength = np.float32(float(amount) * 0.08 / max(math.sqrt(max(scale, 1.0)), 1.0))
    return np.mod(u + displacement_x * strength, 1.0), np.mod(v + displacement_y * strength, 1.0)


def _value_fractal_field(
    u: np.ndarray,
    v: np.ndarray,
    context: EvalContext,
    *,
    scale: float,
    octaves: int,
    roughness: float,
    seed: int,
    evolution: float,
    cycles: float,
    lacunarity: float = 2.0,
) -> np.ndarray:
    """Periodic value-noise FBM used by the cloud family.

    Unlike the older gradient/turbulence combinations, this octave sum has no
    absolute-value fold that can reveal ridges, rings or cellular contours.
    """
    octaves = min(max(int(octaves), 1), 10)
    roughness = min(max(float(roughness), 0.0), 1.0)
    total = np.zeros((context.height, context.width), dtype=np.float32)
    weight_sum = 0.0
    amplitude = 1.0
    frequency = max(float(scale), 1.0)
    z, z_period = _loop_z(evolution, cycles)
    for octave in range(octaves):
        cells_x, cells_y = _aspect_cells(frequency, context)
        sample = _periodic_value_noise_3d_uv(
            u, v, cells_x, cells_y, seed + octave * 1301, z, z_period
        )
        total += sample.astype(np.float32) * np.float32(amplitude)
        weight_sum += amplitude
        amplitude *= roughness
        frequency *= max(float(lacunarity), 1.01)
    if weight_sum <= 1e-8:
        return np.zeros_like(total)
    return (total / np.float32(weight_sum)).astype(np.float32)


def _fractal_field(
    u: np.ndarray,
    v: np.ndarray,
    context: EvalContext,
    *,
    scale: float,
    octaves: int,
    roughness: float,
    seed: int,
    evolution: float,
    cycles: float,
    mode: str = "fbm",
    lacunarity: float = 2.0,
) -> np.ndarray:
    octaves = min(max(int(octaves), 1), 10)
    roughness = min(max(float(roughness), 0.0), 1.0)
    total = np.zeros((context.height, context.width), dtype=np.float32)
    weight_sum = 0.0
    amplitude = 1.0
    frequency = max(float(scale), 1.0)
    z, z_period = _loop_z(evolution, cycles)
    for octave in range(octaves):
        cells_x, cells_y = _aspect_cells(frequency, context)
        base = _periodic_gradient_noise_3d_uv(
            u, v, cells_x, cells_y, seed + octave * 1301, z, z_period
        )
        signed = base * np.float32(2.0) - np.float32(1.0)
        if mode == "billow":
            sample = np.float32(1.0) - np.abs(signed)
        elif mode == "turbulence":
            sample = np.abs(signed)
        elif mode == "ridged":
            ridge = np.float32(1.0) - np.abs(signed)
            sample = ridge * ridge
        else:
            sample = base
        total += sample.astype(np.float32) * np.float32(amplitude)
        weight_sum += amplitude
        amplitude *= roughness
        frequency *= max(float(lacunarity), 1.01)
    if weight_sum <= 1e-8:
        return np.zeros_like(total)
    return (total / np.float32(weight_sum)).astype(np.float32)


def _common_finish(value: np.ndarray, params: Mapping[str, Any]) -> ImageArray:
    return grayscale_rgba(
        _finish(
            value,
            float(params.get("contrast", 1.0)),
            float(params.get("balance", 0.0)),
            bool(params.get("invert", False)),
        )
    )


def _prepare_uv(params: Mapping[str, Any], context: EvalContext) -> tuple[np.ndarray, np.ndarray, float, int, float, float]:
    u, v = _uv(context)
    scale = max(float(params.get("scale", 6.0)), 1.0)
    seed = int(params.get("seed", 1))
    evolution = _evolution_phase(float(params.get("evolution", 0.0)))
    cycles = max(float(params.get("loop_cycles", 1.0)), 0.001)
    u, v = _directional_disorder(
        u,
        v,
        context,
        scale=scale,
        seed=seed,
        evolution=evolution,
        cycles=cycles,
        amount=float(params.get("disorder", 0.0)),
        disorder_scale=float(params.get("disorder_scale", max(scale * 0.5, 1.0))),
        anisotropy=float(params.get("disorder_anisotropy", 0.0)),
        angle_degrees=float(params.get("disorder_angle", 0.0)),
    )
    return u, v, scale, seed, evolution, cycles


def _prepare_cloud_uv(
    params: Mapping[str, Any], context: EvalContext
) -> tuple[np.ndarray, np.ndarray, float, int, float, float]:
    u, v = _uv(context)
    scale = max(float(params.get("scale", 6.0)), 1.0)
    seed = int(params.get("seed", 1))
    evolution = _evolution_phase(float(params.get("evolution", 0.0)))
    cycles = max(float(params.get("loop_cycles", 1.0)), 0.001)
    u, v = _cloud_disorder(
        u,
        v,
        context,
        scale=scale,
        seed=seed,
        evolution=evolution,
        cycles=cycles,
        amount=float(params.get("disorder", 0.0)),
        disorder_scale=float(params.get("disorder_scale", max(scale * 0.5, 1.0))),
        anisotropy=float(params.get("disorder_anisotropy", 0.0)),
        angle_degrees=float(params.get("disorder_angle", 0.0)),
    )
    return u, v, scale, seed, evolution, cycles


def eval_clouds_1(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    u, v, scale, seed, evolution, cycles = _prepare_cloud_uv(params, context)
    octaves = int(params.get("octaves", 6))
    roughness = min(max(float(params.get("roughness", 0.62)), 0.0), 1.0)
    softness = min(max(float(params.get("softness", 0.42)), 0.0), 1.0)
    gain = 0.34 + 0.38 * roughness
    broad = _value_fractal_field(
        u, v, context, scale=scale, octaves=octaves, roughness=gain,
        seed=seed, evolution=evolution, cycles=cycles
    )
    middle = _value_fractal_field(
        u, v, context, scale=scale * 2.15, octaves=max(octaves - 1, 1),
        roughness=gain * 0.88, seed=seed + 3701, evolution=evolution, cycles=cycles
    )
    fine = _value_fractal_field(
        u, v, context, scale=scale * 4.2, octaves=max(octaves - 2, 1),
        roughness=gain * 0.74, seed=seed + 9103, evolution=evolution, cycles=cycles
    )
    raw = broad * np.float32(0.48) + middle * np.float32(0.35) + fine * np.float32(0.20)
    gamma = np.float32(0.78 - 0.32 * softness)
    shaped = np.power(np.clip(raw, 0.0, 1.0), gamma).astype(np.float32)
    internal_contrast = np.float32(1.45 + 0.58 * (1.0 - softness))
    value = np.clip((shaped - np.float32(0.5)) * internal_contrast + np.float32(0.39), 0.0, 1.0)
    return _common_finish(value.astype(np.float32), params)


def eval_clouds_2(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    u, v, scale, seed, evolution, cycles = _prepare_cloud_uv(params, context)
    octaves = int(params.get("octaves", 5))
    roughness = min(max(float(params.get("roughness", 0.45)), 0.0), 1.0)
    puffiness = max(float(params.get("puffiness", 1.8)), 0.25)
    gain = 0.28 + 0.42 * roughness
    low = _value_fractal_field(
        u, v, context, scale=scale * 0.75, octaves=octaves, roughness=gain,
        seed=seed, evolution=evolution, cycles=cycles
    )
    middle = _value_fractal_field(
        u, v, context, scale=scale * 1.75, octaves=max(octaves - 1, 1),
        roughness=gain * 0.94, seed=seed + 3701, evolution=evolution, cycles=cycles
    )
    fine = _value_fractal_field(
        u, v, context, scale=scale * 3.75, octaves=max(octaves - 2, 1),
        roughness=gain * 0.80, seed=seed + 9103, evolution=evolution, cycles=cycles
    )
    raw = low * np.float32(0.62) + middle * np.float32(0.31) + fine * np.float32(0.07)
    gamma = np.float32(np.clip(0.88 - 0.18 * puffiness, 0.42, 1.10))
    shaped = np.power(np.clip(raw, 0.0, 1.0), gamma).astype(np.float32)
    internal_contrast = np.float32(1.20 + 0.14 * puffiness)
    value = np.clip((shaped - np.float32(0.5)) * internal_contrast + np.float32(0.425), 0.0, 1.0)
    return _common_finish(value.astype(np.float32), params)


def eval_clouds_3(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    u, v, scale, seed, evolution, cycles = _prepare_cloud_uv(params, context)
    octaves = int(params.get("octaves", 6))
    roughness = min(max(float(params.get("roughness", 0.58)), 0.0), 1.0)
    erosion = min(max(float(params.get("erosion", 0.38)), 0.0), 1.0)
    detail = min(max(float(params.get("detail", 0.65)), 0.0), 1.0)
    gain = 0.36 + 0.42 * roughness
    body = _value_fractal_field(
        u, v, context, scale=scale, octaves=octaves, roughness=gain,
        seed=seed, evolution=evolution, cycles=cycles
    )
    middle = _value_fractal_field(
        u, v, context, scale=scale * 2.35, octaves=max(octaves - 1, 1),
        roughness=gain * 0.90, seed=seed + 3701, evolution=evolution, cycles=cycles
    )
    fine = _value_fractal_field(
        u, v, context, scale=scale * 5.0, octaves=max(octaves - 2, 1),
        roughness=gain * 0.75, seed=seed + 9103, evolution=evolution, cycles=cycles
    )
    raw = (body * np.float32(0.64) + middle * np.float32(0.26) + fine * np.float32(0.10 * detail))
    raw /= np.float32(0.90 + 0.10 * detail)
    broken = raw * (np.float32(0.82) + middle * np.float32(0.36))
    raw = raw * np.float32(1.0 - erosion * 0.45) + broken * np.float32(erosion * 0.45)
    internal_contrast = np.float32(1.25 + 0.92 * erosion)
    value = np.clip((raw - np.float32(0.5)) * internal_contrast + np.float32(0.427), 0.0, 1.0)
    return _common_finish(value.astype(np.float32), params)


def _cell_spots(
    u: np.ndarray,
    v: np.ndarray,
    context: EvalContext,
    *,
    scale: float,
    seed: int,
    evolution: float,
    cycles: float,
    points_per_cell: int,
    size: float,
    softness: float,
    elliptical: float = 0.0,
    angle_degrees: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    cells_x, cells_y = _aspect_cells(scale, context)
    point_x = np.mod(u, 1.0) * np.float32(cells_x)
    point_y = np.mod(v, 1.0) * np.float32(cells_y)
    base_x = np.floor(point_x).astype(np.int32)
    base_y = np.floor(point_y).astype(np.int32)
    profile = np.zeros_like(point_x, dtype=np.float32)
    signed_profile = np.zeros_like(point_x, dtype=np.float32)
    nearest = np.full_like(point_x, np.float32(1e9))
    phase = np.float32(TAU * evolution * cycles)
    points_per_cell = min(max(int(points_per_cell), 1), 3)
    radius = max(float(size), 0.01) * 0.48
    edge = max(float(softness), 0.001) * radius + 0.002
    global_angle = math.radians(angle_degrees)
    for oy in range(-1, 2):
        for ox in range(-1, 2):
            neighbour_x = base_x + ox
            neighbour_y = base_y + oy
            wrapped_x = np.mod(neighbour_x, cells_x).astype(np.uint32)
            wrapped_y = np.mod(neighbour_y, cells_y).astype(np.uint32)
            for point_index in range(points_per_cell):
                hx = _hash01(_hash3(wrapped_x, wrapped_y, point_index, seed, 13))
                hy = _hash01(_hash3(wrapped_x, wrapped_y, point_index, seed, 17))
                hr = _hash01(_hash3(wrapped_x, wrapped_y, point_index, seed, 19))
                hp = _hash01(_hash3(wrapped_x, wrapped_y, point_index, seed, 23))
                ha = _hash01(_hash3(wrapped_x, wrapped_y, point_index, seed, 29))
                centre_x = neighbour_x.astype(np.float32) + np.float32(0.15) + hx * np.float32(0.7)
                centre_y = neighbour_y.astype(np.float32) + np.float32(0.15) + hy * np.float32(0.7)
                local_angle = (
                    np.float32(global_angle)
                    + ha * np.float32(TAU)
                    + np.sin(phase + hp * np.float32(TAU)).astype(np.float32) * np.float32(0.22)
                )
                ca, sa = np.cos(local_angle).astype(np.float32), np.sin(local_angle).astype(np.float32)
                dx = point_x - centre_x
                dy = point_y - centre_y
                local_x = ca * dx + sa * dy
                local_y = -sa * dx + ca * dy
                stretch = np.float32(1.0 + elliptical * (0.35 + 1.65 * hr))
                distance = np.sqrt((local_x / stretch) ** 2 + (local_y * stretch) ** 2).astype(np.float32)
                local_radius = np.float32(radius) * (np.float32(0.65) + hr * np.float32(0.7))
                spot = np.float32(1.0) - _smoothstep(local_radius - edge, local_radius + edge, distance)
                profile = np.maximum(profile, spot)
                signed = spot * np.where(hp >= 0.5, np.float32(1.0), np.float32(-1.0))
                stronger = np.abs(signed) > np.abs(signed_profile)
                signed_profile = np.where(stronger, signed, signed_profile)
                nearest = np.minimum(nearest, distance / np.maximum(local_radius, np.float32(1e-5)))
    return profile.astype(np.float32), signed_profile.astype(np.float32), nearest.astype(np.float32)


def _sparse_spot_field(
    u: np.ndarray,
    v: np.ndarray,
    context: EvalContext,
    *,
    scale: float,
    seed: int,
    evolution: float,
    cycles: float,
    points_per_cell: int,
    radius: float,
    probability: float = 1.0,
    ellipticity: float = 0.0,
) -> np.ndarray:
    """Periodic sparse-convolution spot noise.

    Each lattice cell contributes a small set of randomly positioned, signed
    Gaussian kernels.  Summing kernels instead of interpolating lattice values
    creates actual deposits/specks rather than another cloudy FBM field.
    """
    cells_x, cells_y = _aspect_cells(max(float(scale), 1.0), context)
    point_x = np.mod(u, 1.0) * np.float32(cells_x)
    point_y = np.mod(v, 1.0) * np.float32(cells_y)
    base_x = np.floor(point_x).astype(np.int32)
    base_y = np.floor(point_y).astype(np.int32)
    result = np.zeros_like(point_x, dtype=np.float32)
    point_count = min(max(int(points_per_cell), 1), 3)
    ellipticity = min(max(float(ellipticity), 0.0), 1.0)
    # The Gaussian kernels are smoothly compacted before truncation.  A 5x5
    # neighbourhood is required for the largest BnW Spots kernels; the old
    # 3x3 search omitted still-visible tails and produced cell-aligned gradient
    # discontinuities that became obvious after Height to Normal.
    for oy in range(-2, 3):
        for ox in range(-2, 3):
            neighbour_x = base_x + ox
            neighbour_y = base_y + oy
            wrapped_x = np.mod(neighbour_x, cells_x).astype(np.uint32)
            wrapped_y = np.mod(neighbour_y, cells_y).astype(np.uint32)
            for point_index in range(point_count):
                hx = _hash01(_hash3(wrapped_x, wrapped_y, point_index, seed, 101))
                hy = _hash01(_hash3(wrapped_x, wrapped_y, point_index, seed, 103))
                hr = _hash01(_hash3(wrapped_x, wrapped_y, point_index, seed, 107))
                hs = _hash01(_hash3(wrapped_x, wrapped_y, point_index, seed, 109))
                ha = _hash01(_hash3(wrapped_x, wrapped_y, point_index, seed, 127))
                hd = _hash01(_hash3(wrapped_x, wrapped_y, point_index, seed, 131))
                centre_x = neighbour_x.astype(np.float32) + np.float32(0.1) + hx * np.float32(0.8)
                centre_y = neighbour_y.astype(np.float32) + np.float32(0.1) + hy * np.float32(0.8)
                angle = ha * np.float32(TAU)
                ca = np.cos(angle).astype(np.float32)
                sa = np.sin(angle).astype(np.float32)
                dx = point_x - centre_x
                dy = point_y - centre_y
                local_x = ca * dx + sa * dy
                local_y = -sa * dx + ca * dy
                stretch = np.float32(1.0) + np.float32(ellipticity) * (
                    np.float32(0.25) + np.float32(1.25) * hr
                )
                distance_squared = (local_x / stretch) ** 2 + (local_y * stretch) ** 2
                sigma = np.float32(max(float(radius), 0.01)) * (
                    np.float32(0.55) + np.float32(0.90) * hr
                )
                distance = np.sqrt(distance_squared).astype(np.float32)
                kernel = np.exp(
                    -distance_squared / np.maximum(np.float32(2.0) * sigma * sigma, np.float32(1e-6))
                ).astype(np.float32)
                # Gaussian kernels have infinite support.  Fade their tails to
                # zero continuously before the finite neighbour search ends so
                # both values and first derivatives remain stable across cells.
                support_fade = np.float32(1.0) - _smoothstep(
                    np.float32(1.05), np.float32(1.45), distance
                )
                kernel *= support_fade
                sign = np.where(hs >= np.float32(0.5), np.float32(1.0), np.float32(-1.0))
                amplitude = sign * (np.float32(0.55) + np.float32(0.90) * ha)
                active = (hd <= np.float32(np.clip(probability, 0.0, 1.0))).astype(np.float32)
                result += kernel * amplitude * active
    return result.astype(np.float32)


def eval_bnw_spots_1(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    u, v, scale, seed, evolution, cycles = _prepare_uv(params, context)
    roughness = min(max(float(params.get("roughness", 0.72)), 0.0), 1.0)
    grain = min(max(float(params.get("grain", 0.72)), 0.0), 1.0)
    broad = _sparse_spot_field(
        u, v, context, scale=scale * 0.75, seed=seed, evolution=evolution, cycles=cycles,
        points_per_cell=3, radius=0.34, probability=0.82, ellipticity=0.18,
    )
    middle = _sparse_spot_field(
        u, v, context, scale=scale * 2.8, seed=seed + 4099, evolution=evolution, cycles=cycles,
        points_per_cell=3, radius=0.25, probability=0.68, ellipticity=0.12,
    )
    fine = _sparse_spot_field(
        u, v, context, scale=scale * 8.4, seed=seed + 8191, evolution=evolution, cycles=cycles,
        points_per_cell=2, radius=0.20, probability=0.48, ellipticity=0.08,
    )
    impulse_sum = (
        broad * np.float32(0.60)
        + middle * np.float32(0.38 + 0.35 * roughness)
        + fine * np.float32(0.18 + 0.45 * grain)
    )
    value = np.float32(0.440) + np.float32(0.36) * np.tanh(impulse_sum * np.float32(0.82))
    return _common_finish(np.clip(value, 0.0, 1.0).astype(np.float32), params)


def eval_bnw_spots_2(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    u, v, scale, seed, evolution, cycles = _prepare_uv(params, context)
    roughness = min(max(float(params.get("roughness", 0.58)), 0.0), 1.0)
    grain = min(max(float(params.get("grain", 0.62)), 0.0), 1.0)
    broad = _sparse_spot_field(
        u, v, context, scale=scale * 0.48, seed=seed, evolution=evolution, cycles=cycles,
        points_per_cell=2, radius=0.44, probability=0.72, ellipticity=0.22,
    )
    middle = _sparse_spot_field(
        u, v, context, scale=scale * 1.85, seed=seed + 4099, evolution=evolution, cycles=cycles,
        points_per_cell=3, radius=0.27, probability=0.58, ellipticity=0.12,
    )
    speckles = _sparse_spot_field(
        u, v, context, scale=scale * 9.5, seed=seed + 8191, evolution=evolution, cycles=cycles,
        points_per_cell=2, radius=0.18, probability=0.36, ellipticity=0.04,
    )
    impulse_sum = (
        broad * np.float32(0.48)
        + middle * np.float32(0.25 + 0.28 * roughness)
        + speckles * np.float32(0.36 + 0.70 * grain)
    )
    value = np.float32(0.442) + np.float32(0.40) * np.tanh(impulse_sum * np.float32(0.70))
    return _common_finish(np.clip(value, 0.0, 1.0).astype(np.float32), params)


def eval_bnw_spots_3(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    u, v, scale, seed, evolution, cycles = _prepare_uv(params, context)
    roughness = min(max(float(params.get("roughness", 0.50)), 0.0), 1.0)
    grain = min(max(float(params.get("grain", 0.50)), 0.0), 1.0)
    broad = _sparse_spot_field(
        u, v, context, scale=scale, seed=seed, evolution=evolution, cycles=cycles,
        points_per_cell=2, radius=0.43, probability=0.76, ellipticity=0.18,
    )
    middle = _sparse_spot_field(
        u, v, context, scale=scale * 2.25, seed=seed + 4099, evolution=evolution, cycles=cycles,
        points_per_cell=3, radius=0.38, probability=0.62, ellipticity=0.10,
    )
    fine = _sparse_spot_field(
        u, v, context, scale=scale * 7.0, seed=seed + 8191, evolution=evolution, cycles=cycles,
        points_per_cell=2, radius=0.24, probability=0.38, ellipticity=0.05,
    )
    impulse_sum = (
        broad * np.float32(0.55)
        + middle * np.float32(0.32 + 0.28 * roughness)
        + fine * np.float32(0.14 + 0.30 * grain)
    )
    value = np.float32(0.505) + np.float32(0.30) * np.tanh(impulse_sum * np.float32(0.68))
    return _common_finish(np.clip(value, 0.0, 1.0).astype(np.float32), params)


def _cellular_fields_simple(
    u: np.ndarray,
    v: np.ndarray,
    context: EvalContext,
    *,
    scale: float,
    seed: int,
    jitter: float,
    evolution: float,
    cycles: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    cells_x, cells_y = _aspect_cells(scale, context)
    point_x = np.mod(u, 1.0) * np.float32(cells_x)
    point_y = np.mod(v, 1.0) * np.float32(cells_y)
    base_x = np.floor(point_x).astype(np.int32)
    base_y = np.floor(point_y).astype(np.int32)
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
            h_angle = _hash01(_hash3(wrapped_x, wrapped_y, 0, seed, 3))
            h_radius = _hash01(_hash3(wrapped_x, wrapped_y, 0, seed, 4))
            angle = h_angle * np.float32(TAU) + phase
            radius = np.float32(np.clip(jitter, 0.0, 1.0) * 0.48) * (np.float32(0.35) + np.float32(0.65) * h_radius)
            feature_x = neighbour_x.astype(np.float32) + np.float32(0.5) + np.cos(angle) * radius
            feature_y = neighbour_y.astype(np.float32) + np.float32(0.5) + np.sin(angle) * radius
            distance = np.sqrt((feature_x - point_x) ** 2 + (feature_y - point_y) ** 2).astype(np.float32)
            closer = distance < f1
            f2 = np.where(closer, f1, np.minimum(f2, distance))
            f1 = np.where(closer, distance, f1)
            cell_value = _hash01(_hash3(wrapped_x, wrapped_y, 0, seed, 5))
            nearest_value = np.where(closer, cell_value, nearest_value)
    return f1, f2, nearest_value




def _crystal_voronoi_distance(
    u: np.ndarray,
    v: np.ndarray,
    *,
    cells_x: int,
    cells_y: int,
    seed: int,
    evolution: float,
    cycles: float,
) -> np.ndarray:
    """Periodic fully-randomised Voronoi distance for Crystal 1.

    Crystal 1 follows the compact two-Voronoi construction used by Material
    Maker: two independent distance fields are curved with sqrt(1-A^2), then
    their relative difference forms the dark faceted crystal pattern.
    """
    cells_x = min(max(int(cells_x), 1), 256)
    cells_y = min(max(int(cells_y), 1), 256)
    point_x = np.mod(u, 1.0) * np.float32(cells_x)
    point_y = np.mod(v, 1.0) * np.float32(cells_y)
    base_x = np.floor(point_x).astype(np.int32)
    base_y = np.floor(point_y).astype(np.int32)
    nearest = np.full_like(point_x, np.float32(1e9))
    phase = np.float32(TAU * evolution * cycles)
    for oy in range(-1, 2):
        for ox in range(-1, 2):
            neighbour_x = base_x + ox
            neighbour_y = base_y + oy
            wrapped_x = np.mod(neighbour_x, cells_x).astype(np.uint32)
            wrapped_y = np.mod(neighbour_y, cells_y).astype(np.uint32)
            h_angle = _hash01(_hash3(wrapped_x, wrapped_y, 0, seed, 3))
            h_radius = _hash01(_hash3(wrapped_x, wrapped_y, 0, seed, 4))
            angle = h_angle * np.float32(TAU) + phase
            radius = np.float32(0.48) * (np.float32(0.35) + np.float32(0.65) * h_radius)
            feature_x = neighbour_x.astype(np.float32) + np.float32(0.5) + np.cos(angle) * radius
            feature_y = neighbour_y.astype(np.float32) + np.float32(0.5) + np.sin(angle) * radius
            distance = np.sqrt((feature_x - point_x) ** 2 + (feature_y - point_y) ** 2).astype(np.float32)
            nearest = np.minimum(nearest, distance)
    return nearest.astype(np.float32)


def _lattice_direction(angle_degrees: float) -> tuple[int, int]:
    """Quantise an artist angle to a small periodic integer direction."""
    angle = math.radians(float(angle_degrees))
    x = int(round(math.cos(angle) * 3.0))
    y = int(round(math.sin(angle) * 3.0))
    if x == 0 and y == 0:
        x = 1
    divisor = math.gcd(abs(x), abs(y)) or 1
    return x // divisor, y // divisor


def _crease_crystal_field(
    u: np.ndarray,
    v: np.ndarray,
    context: EvalContext,
    *,
    fold_count: int,
    band_count: int,
    seed: int,
    disorder: float,
    sharpness: float,
    angle_degrees: float,
    evolution: float,
    cycles: float,
    phase_offset: float = 0.0,
) -> np.ndarray:
    """Continuous triangular fold field used by Crystal 2.

    Irregular periodic fold lines define vertical/diagonal strips.  Each strip
    is split into triangles and interpolated as planar facets, producing long
    cloth-like crystalline creases without stamped segments or FBM.
    """
    fold_count = min(max(int(fold_count), 2), 48)
    band_count = min(max(int(band_count), 2), 24)
    direction_x, direction_y = _lattice_direction(angle_degrees)
    across_x, across_y = -direction_y, direction_x
    across = np.mod(u * np.float32(across_x) + v * np.float32(across_y), 1.0)
    along = np.mod(u * np.float32(direction_x) + v * np.float32(direction_y), 1.0)
    z, z_period = _loop_z(evolution, cycles)
    warp_cells_x, warp_cells_y = _aspect_cells(max(float(fold_count) * 0.32, 2.0), context)
    warp = _periodic_value_noise_3d_uv(
        u, v, warp_cells_x, warp_cells_y, seed + 777, z, z_period
    ) * np.float32(2.0) - np.float32(1.0)
    disorder = np.float32(np.clip(disorder, 0.0, 1.0))
    fold_coord = (
        np.mod(across + warp * disorder * np.float32(0.075), 1.0)
        * np.float32(fold_count)
        + np.float32(phase_offset)
    )
    base = np.floor(fold_coord).astype(np.int32)
    left_position = np.full_like(fold_coord, np.float32(-1e9))
    right_position = np.full_like(fold_coord, np.float32(1e9))
    left_index = np.zeros_like(base)
    right_index = np.zeros_like(base)
    phase = np.float32(TAU * evolution)
    zeros = np.zeros_like(base, dtype=np.uint32)
    for offset in range(-2, 3):
        index = base + offset
        wrapped = np.mod(index, fold_count).astype(np.uint32)
        position_hash = _hash01(_hash3(wrapped, zeros, 0, seed, 31))
        motion_hash = _hash01(_hash3(wrapped, zeros, 0, seed, 37))
        position = (
            index.astype(np.float32)
            + np.float32(0.5)
            + (position_hash - np.float32(0.5)) * disorder * np.float32(0.72)
            + np.sin(phase + motion_hash * np.float32(TAU)) * disorder * np.float32(0.045)
        )
        better_left = (position <= fold_coord) & (position > left_position)
        left_position = np.where(better_left, position, left_position)
        left_index = np.where(better_left, index, left_index)
        better_right = (position > fold_coord) & (position < right_position)
        right_position = np.where(better_right, position, right_position)
        right_index = np.where(better_right, index, right_index)

    local_x = np.clip(
        (fold_coord - left_position) / np.maximum(right_position - left_position, np.float32(1e-5)),
        0.0,
        1.0,
    ).astype(np.float32)
    band_coord = along * np.float32(band_count)
    band_base = np.floor(band_coord).astype(np.int32)
    local_y = (band_coord - band_base).astype(np.float32)

    def corner(line_index: np.ndarray, band_index: np.ndarray, salt: int) -> np.ndarray:
        wrapped_line = np.mod(line_index, fold_count).astype(np.uint32)
        wrapped_band = np.mod(band_index, band_count).astype(np.uint32)
        hashed = _hash01(_hash3(wrapped_line, wrapped_band, 0, seed, salt))
        return (np.float32(0.5) + np.float32(0.36) * np.sin(hashed * np.float32(TAU) + phase)).astype(np.float32)

    c00 = corner(left_index, band_base, 41)
    c10 = corner(right_index, band_base, 41)
    c01 = corner(left_index, band_base + 1, 41)
    c11 = corner(right_index, band_base + 1, 41)
    first_triangle = c00 + local_x * (c10 - c00) + local_y * (c01 - c00)
    second_triangle = c11 + (np.float32(1.0) - local_x) * (c01 - c11) + (
        np.float32(1.0) - local_y
    ) * (c10 - c11)
    triangular = np.where(local_x + local_y <= np.float32(1.0), first_triangle, second_triangle)
    smooth_x = local_x * local_x * (np.float32(3.0) - np.float32(2.0) * local_x)
    smooth_y = local_y * local_y * (np.float32(3.0) - np.float32(2.0) * local_y)
    bilinear = (
        (c00 * (np.float32(1.0) - smooth_x) + c10 * smooth_x) * (np.float32(1.0) - smooth_y)
        + (c01 * (np.float32(1.0) - smooth_x) + c11 * smooth_x) * smooth_y
    )
    smoothing = np.float32(np.clip(0.16 / max(float(sharpness), 0.1), 0.0, 0.65))
    return (triangular * (np.float32(1.0) - smoothing) + bilinear * smoothing).astype(np.float32)

def eval_crystal_1(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    u, v = _uv(context)
    legacy_scale = max(float(params.get("scale", 16.0)), 1.0)
    scale_x = min(max(int(round(float(params.get("scale_x", legacy_scale)))), 1), 256)
    scale_y = min(max(int(round(float(params.get("scale_y", legacy_scale)))), 1), 256)
    seed = int(params.get("seed", 1))
    evolution = _evolution_phase(float(params.get("evolution", 0.0)))
    cycles = max(float(params.get("loop_cycles", 1.0)), 0.001)

    first_distance = _crystal_voronoi_distance(
        u, v, cells_x=scale_x, cells_y=scale_y, seed=seed,
        evolution=evolution, cycles=cycles,
    )
    second_distance = _crystal_voronoi_distance(
        u, v, cells_x=scale_x, cells_y=scale_y, seed=seed + 101,
        evolution=evolution, cycles=cycles,
    )

    # Material Maker's public Crystal graph curves both Voronoi distances with
    # sqrt(1-A^2), then divides their absolute min/max difference by the
    # larger curved field and scales the result.  The 0.88 distance
    # normalisation matches its Voronoi output range while retaining our own
    # deterministic periodic feature placement.
    first = np.sqrt(np.clip(
        np.float32(1.0) - np.square(np.clip(first_distance * np.float32(0.88), 0.0, 1.0)),
        0.0, 1.0,
    )).astype(np.float32)
    second = np.sqrt(np.clip(
        np.float32(1.0) - np.square(np.clip(second_distance * np.float32(0.88), 0.0, 1.0)),
        0.0, 1.0,
    )).astype(np.float32)
    low = np.minimum(first, second)
    high = np.maximum(first, second)
    value = np.clip(
        (high - low) / np.maximum(high, np.float32(1e-6)) * np.float32(1.45),
        0.0, 1.0,
    ).astype(np.float32)
    return _common_finish(value, params)


def eval_crystal_2(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    u, v = _uv(context)
    scale = min(max(float(params.get("scale", 6.0)), 1.0), 16.0)
    seed = int(params.get("seed", 1))
    evolution = _evolution_phase(float(params.get("evolution", 0.0)))
    cycles = max(float(params.get("loop_cycles", 1.0)), 0.001)
    disorder = min(max(float(params.get("jitter", 0.72)), 0.0), 1.0)
    sharpness = max(float(params.get("facet_sharpness", 1.0)), 0.1)
    strength = min(max(float(params.get("edge_weight", 0.62)), 0.0), 1.0)
    angle = float(params.get("angle", 90.0))
    primary_folds = max(int(round(scale * 1.7)), 3)
    primary_bands = max(int(round(scale * 0.75)), 2)
    primary = _crease_crystal_field(
        u, v, context, fold_count=primary_folds, band_count=primary_bands,
        seed=seed, disorder=disorder, sharpness=sharpness,
        angle_degrees=angle, evolution=evolution, cycles=cycles,
    )
    secondary = _crease_crystal_field(
        u, v, context, fold_count=max(int(round(scale * 2.6)), 4),
        band_count=max(primary_bands + 1, 3), seed=seed + 97,
        disorder=disorder * 0.88, sharpness=sharpness * 1.08,
        angle_degrees=angle, evolution=evolution, cycles=cycles, phase_offset=0.37,
    )
    tertiary = _crease_crystal_field(
        u, v, context, fold_count=max(int(round(scale * 1.2)), 3),
        band_count=max(primary_bands - 1, 2), seed=seed + 211,
        disorder=disorder * 0.72, sharpness=sharpness * 0.82,
        angle_degrees=angle, evolution=evolution, cycles=cycles, phase_offset=0.13,
    )
    value = (
        np.float32(0.5)
        + (primary - np.float32(0.5)) * np.float32(0.58)
        + (secondary - np.float32(0.5)) * np.float32(0.30)
        + (tertiary - np.float32(0.5)) * np.float32(0.12)
    )
    value = np.clip(
        np.float32(0.5) + (value - np.float32(0.5)) * np.float32(0.50 + 0.50 * strength),
        0.0, 1.0,
    )
    return _common_finish(value.astype(np.float32), params)


def eval_fractal_sum(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    u, v = _uv(context)
    seed = int(params.get("seed", 1))
    evolution = _evolution_phase(float(params.get("evolution", 0.0)))
    cycles = max(float(params.get("loop_cycles", 1.0)), 0.001)
    minimum = min(max(int(params.get("min_level", 0)), 0), 9)
    maximum = min(max(int(params.get("max_level", 7)), minimum), 10)
    roughness = min(max(float(params.get("roughness", 0.58)), 0.0), 1.0)
    u, v = _domain_warp(
        u, v, context, max(2.0 ** minimum, 1.0), seed, evolution, cycles,
        float(params.get("disorder", 0.0)), float(params.get("disorder_scale", 3.0)),
    )
    total = np.zeros((context.height, context.width), dtype=np.float32)
    weight_sum = 0.0
    amplitude = 1.0
    z, z_period = _loop_z(evolution, cycles)
    for level in range(minimum, maximum + 1):
        frequency = float(2 ** level)
        cells_x, cells_y = _aspect_cells(frequency, context)
        base = _periodic_gradient_noise_3d_uv(u, v, cells_x, cells_y, seed + level * 1423, z, z_period)
        total += base * np.float32(amplitude)
        weight_sum += amplitude
        amplitude *= roughness
    value = total / np.float32(max(weight_sum, 1e-6))
    opacity = min(max(float(params.get("global_opacity", 1.0)), 0.0), 2.0)
    value = np.clip(np.float32(0.5) + (value - np.float32(0.5)) * np.float32(opacity), 0.0, 1.0)
    return _common_finish(value.astype(np.float32), params)


def _segment_field(
    u: np.ndarray,
    v: np.ndarray,
    context: EvalContext,
    *,
    scale: float,
    seed: int,
    evolution: float,
    cycles: float,
    density: int,
    length: float,
    width: float,
    softness: float,
    angle_degrees: float,
    angle_random: float,
    luminance_random: float,
    jitter: float,
    taper: float,
) -> np.ndarray:
    cells_x, cells_y = _aspect_cells(scale, context)
    point_x = np.mod(u, 1.0) * np.float32(cells_x)
    point_y = np.mod(v, 1.0) * np.float32(cells_y)
    base_x = np.floor(point_x).astype(np.int32)
    base_y = np.floor(point_y).astype(np.int32)
    value = np.zeros_like(point_x, dtype=np.float32)
    base_angle = math.radians(angle_degrees)
    density = min(max(int(density), 1), 3)
    phase = float(TAU * evolution * cycles)
    for oy in range(-1, 2):
        for ox in range(-1, 2):
            neighbour_x = base_x + ox
            neighbour_y = base_y + oy
            wrapped_x = np.mod(neighbour_x, cells_x).astype(np.uint32)
            wrapped_y = np.mod(neighbour_y, cells_y).astype(np.uint32)
            for point_index in range(density):
                hx = _hash01(_hash3(wrapped_x, wrapped_y, point_index, seed, 41))
                hy = _hash01(_hash3(wrapped_x, wrapped_y, point_index, seed, 43))
                ha = _hash01(_hash3(wrapped_x, wrapped_y, point_index, seed, 47))
                hl = _hash01(_hash3(wrapped_x, wrapped_y, point_index, seed, 53))
                hw = _hash01(_hash3(wrapped_x, wrapped_y, point_index, seed, 59))
                hv = _hash01(_hash3(wrapped_x, wrapped_y, point_index, seed, 61))
                centre_x = neighbour_x.astype(np.float32) + np.float32(0.5) + (hx - np.float32(0.5)) * np.float32(jitter)
                centre_y = neighbour_y.astype(np.float32) + np.float32(0.5) + (hy - np.float32(0.5)) * np.float32(jitter)
                angle_random_radians = np.float32(math.radians(angle_random))
                angle = (
                    np.float32(base_angle)
                    + (ha - np.float32(0.5)) * angle_random_radians
                    + np.sin(np.float32(phase) + hl * np.float32(TAU)).astype(np.float32)
                    * angle_random_radians * np.float32(0.08)
                )
                direction_x = np.cos(angle).astype(np.float32)
                direction_y = np.sin(angle).astype(np.float32)
                delta_x = point_x - centre_x
                delta_y = point_y - centre_y
                half_length = np.float32(max(length, 0.02) * (0.65 + 0.7 * hl) * 0.5)
                along = delta_x * direction_x + delta_y * direction_y
                clamped_along = np.clip(along, -half_length, half_length)
                closest_x = delta_x - direction_x * clamped_along
                closest_y = delta_y - direction_y * clamped_along
                distance = np.sqrt(closest_x * closest_x + closest_y * closest_y).astype(np.float32)
                local_width = np.float32(max(width, 0.002) * (0.7 + 0.6 * hw))
                edge = local_width * np.float32(max(softness, 0.001) * 1.5 + 0.05)
                strand = np.float32(1.0) - _smoothstep(local_width - edge, local_width + edge, distance)
                if taper > 0.0:
                    endpoint = np.clip(np.float32(1.0) - np.abs(along) / np.maximum(half_length, np.float32(1e-5)), 0.0, 1.0)
                    strand *= np.power(endpoint, np.float32(0.35 + taper * 1.65))
                luminance = np.float32(1.0) - hv * np.float32(np.clip(luminance_random, 0.0, 1.0))
                value = np.maximum(value, strand * luminance)
    return value.astype(np.float32)


def _anisotropic_value_noise(
    u: np.ndarray,
    v: np.ndarray,
    *,
    scale_x: int,
    scale_y: int,
    seed: int,
    evolution: float,
    cycles: float,
    smoothness: float,
    interpolation: float,
) -> np.ndarray:
    """Periodic value noise stretched into directional strips.

    This is intentionally not a strand/shape scatter.  It is an anisotropic
    value-noise lattice: only a handful of value changes occur along X while
    many more occur along Y, producing the long horizontal strips used by the
    established Anisotropic Noise generators in Designer and Material Maker.

    ``smoothness`` controls how much of each X cell is spent fading between
    neighbouring values.  ``interpolation`` blends linear and Hermite fades.
    Y always fades across the complete cell so adjacent strips transition
    continuously rather than exposing hard horizontal steps.
    """
    scale_x = max(int(scale_x), 1)
    scale_y = max(int(scale_y), 1)
    smoothness = min(max(float(smoothness), 0.0), 1.0)
    interpolation = min(max(float(interpolation), 0.0), 1.0)

    px = np.mod(u, 1.0) * np.float32(scale_x)
    py = np.mod(v, 1.0) * np.float32(scale_y)
    x_base = np.floor(px).astype(np.int32)
    y_base = np.floor(py).astype(np.int32)
    fx = (px - x_base).astype(np.float32)
    fy = (py - y_base).astype(np.float32)

    # At Smoothness 0 the X transition is a crisp midpoint change.  At 1 it
    # spans the full cell.  Keeping this separate from the interpolation curve
    # gives both controls a clear, non-overlapping job.
    transition_width = np.float32(max(smoothness, 0.001))
    transition_start = np.float32(0.5) - transition_width * np.float32(0.5)
    x_local = np.clip((fx - transition_start) / transition_width, 0.0, 1.0).astype(np.float32)
    x_hermite = (x_local * x_local * (np.float32(3.0) - np.float32(2.0) * x_local)).astype(np.float32)
    tx = (x_local + (x_hermite - x_local) * np.float32(interpolation)).astype(np.float32)

    y_hermite = (fy * fy * (np.float32(3.0) - np.float32(2.0) * fy)).astype(np.float32)
    ty = (fy + (y_hermite - fy) * np.float32(interpolation)).astype(np.float32)

    z, z_period = _loop_z(evolution, cycles)
    z_base = math.floor(z)
    fz = np.float32(z - z_base)
    z_hermite = fz * fz * (np.float32(3.0) - np.float32(2.0) * fz)
    tz = np.float32(fz + (z_hermite - fz) * np.float32(interpolation))

    x0 = np.mod(x_base, scale_x).astype(np.uint32)
    x1 = np.mod(x_base + 1, scale_x).astype(np.uint32)
    y0 = np.mod(y_base, scale_y).astype(np.uint32)
    y1 = np.mod(y_base + 1, scale_y).astype(np.uint32)
    z0 = z_base % max(z_period, 1)
    z1 = (z0 + 1) % max(z_period, 1)

    def plane(zi: int) -> np.ndarray:
        a = _hash01(_hash3(x0, y0, zi, seed, 1701))
        b = _hash01(_hash3(x1, y0, zi, seed, 1701))
        c = _hash01(_hash3(x0, y1, zi, seed, 1701))
        d = _hash01(_hash3(x1, y1, zi, seed, 1701))
        top = a + (b - a) * tx
        bottom = c + (d - c) * tx
        return (top + (bottom - top) * ty).astype(np.float32)

    low = plane(z0)
    high = plane(z1)
    return (low + (high - low) * tz).astype(np.float32)


def eval_anisotropic_noise(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    u, v = _uv(context)
    value = _anisotropic_value_noise(
        u,
        v,
        scale_x=int(params.get("scale_x", 5)),
        scale_y=int(params.get("scale_y", 34)),
        seed=int(params.get("seed", 1)),
        evolution=_evolution_phase(float(params.get("evolution", 0.0))),
        cycles=max(float(params.get("loop_cycles", 1.0)), 0.001),
        smoothness=float(params.get("smoothness", 1.0)),
        interpolation=float(params.get("interpolation", 1.0)),
    )
    return grayscale_rgba(value)


def eval_fibres(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    u, v, scale, seed, evolution, cycles = _prepare_uv(params, context)
    value = _segment_field(
        u, v, context, scale=scale, seed=seed, evolution=evolution, cycles=cycles,
        density=int(params.get("density", 2)), length=float(params.get("length", 1.65)),
        width=float(params.get("width", 0.045)), softness=float(params.get("softness", 0.25)),
        angle_degrees=float(params.get("angle", 0.0)), angle_random=float(params.get("angle_random", 18.0)),
        luminance_random=float(params.get("luminance_random", 0.4)), jitter=0.95, taper=0.35,
    )
    return _common_finish(value, params)


def eval_messy_fibres(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    u, v, scale, seed, evolution, cycles = _prepare_uv(params, context)
    # A second, stronger warp keeps this family visibly distinct from orderly fibres.
    u, v = _directional_disorder(
        u, v, context, scale=scale, seed=seed + 2281, evolution=evolution, cycles=cycles,
        amount=float(params.get("messiness", 1.15)), disorder_scale=float(params.get("messiness_scale", 5.0)),
        anisotropy=0.35, angle_degrees=float(params.get("angle", 0.0)),
    )
    value = _segment_field(
        u, v, context, scale=scale, seed=seed, evolution=evolution, cycles=cycles,
        density=int(params.get("density", 2)), length=float(params.get("length", 1.25)),
        width=float(params.get("width", 0.055)), softness=float(params.get("softness", 0.32)),
        angle_degrees=float(params.get("angle", 0.0)), angle_random=float(params.get("angle_random", 105.0)),
        luminance_random=float(params.get("luminance_random", 0.72)), jitter=1.0, taper=0.55,
    )
    breakup = _fractal_field(u, v, context, scale=scale * 1.8, octaves=3, roughness=0.55, seed=seed + 6343, evolution=evolution, cycles=cycles)
    breakage = min(max(float(params.get("breakage", 0.38)), 0.0), 1.0)
    value *= np.clip(np.float32(1.0) - np.float32(breakage) * (np.float32(1.0) - breakup) * np.float32(1.35), 0.0, 1.0)
    return _common_finish(value.astype(np.float32), params)


def eval_moisture_noise(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    # Adobe describes this family as discs of varying hardness and size which
    # add to or subtract from a neutral grey field.  The old implementation
    # selected the strongest disc per pixel, exposing Voronoi-like ownership
    # boundaries.  This reconstruction instead sums several periodic sparse
    # deposit layers over a broad dampness mask.
    u, v, scale, seed, evolution, cycles = _prepare_cloud_uv(params, context)
    pool_size = min(max(float(params.get("pool_size", 1.0)), 0.35), 2.5)
    fine_detail = min(max(float(params.get("fine_detail", 0.65)), 0.0), 1.0)
    patchiness = min(max(float(params.get("patchiness", 0.72)), 0.0), 1.0)
    root_size = math.sqrt(pool_size)

    broad = _sparse_spot_field(
        u, v, context,
        scale=max(scale * 0.58 / root_size, 1.0),
        seed=seed, evolution=evolution, cycles=cycles,
        points_per_cell=3, radius=0.50 * root_size, probability=0.92, ellipticity=0.12,
    )
    middle = _sparse_spot_field(
        u, v, context,
        scale=max(scale * 2.20 / root_size, 1.0),
        seed=seed + 2671, evolution=evolution, cycles=cycles,
        points_per_cell=3, radius=0.29 * root_size, probability=0.75, ellipticity=0.10,
    )
    fine = _sparse_spot_field(
        u, v, context,
        scale=max(scale * 9.5, 1.0),
        seed=seed + 8111, evolution=evolution, cycles=cycles,
        points_per_cell=3, radius=0.18, probability=0.48, ellipticity=0.03,
    )
    micro = _sparse_spot_field(
        u, v, context,
        scale=max(scale * 18.0, 1.0),
        seed=seed + 12347, evolution=evolution, cycles=cycles,
        points_per_cell=2, radius=0.14, probability=0.28, ellipticity=0.0,
    )
    patch = _value_fractal_field(
        u, v, context,
        scale=max(scale * 0.30 / root_size, 1.0), octaves=4, roughness=0.55,
        seed=seed + 991, evolution=evolution, cycles=cycles,
    )

    broad_field = (
        broad * np.float32(0.38)
        + middle * np.float32(0.28)
        + (patch - np.float32(0.5)) * np.float32(0.18 + 0.47 * patchiness)
    )
    speckles = (
        fine * np.float32(0.018 + 0.057 * fine_detail)
        + micro * np.float32(0.010 + 0.040 * fine_detail)
    )
    value = np.float32(0.55) + np.float32(0.38) * np.tanh(broad_field * np.float32(0.85)) + speckles
    return _common_finish(np.clip(value, 0.0, 1.0).astype(np.float32), params)


def eval_fur(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    u, v, scale, seed, evolution, cycles = _prepare_uv(params, context)
    value = _segment_field(
        u, v, context, scale=scale, seed=seed, evolution=evolution, cycles=cycles,
        density=int(params.get("density", 3)), length=float(params.get("length", 0.62)),
        width=float(params.get("width", 0.026)), softness=float(params.get("softness", 0.2)),
        angle_degrees=float(params.get("angle", -90.0)), angle_random=float(params.get("angle_random", 24.0)),
        luminance_random=float(params.get("luminance_random", 0.58)), jitter=1.0, taper=0.95,
    )
    undercoat = _segment_field(
        u, v, context, scale=scale * 0.62, seed=seed + 9511, evolution=evolution, cycles=cycles,
        density=2, length=float(params.get("length", 0.62)) * 0.72,
        width=float(params.get("width", 0.026)) * 1.5, softness=0.55,
        angle_degrees=float(params.get("angle", -90.0)), angle_random=float(params.get("angle_random", 24.0)) * 1.4,
        luminance_random=0.8, jitter=1.0, taper=0.8,
    )
    value = np.maximum(value, undercoat * np.float32(0.42))
    return _common_finish(value.astype(np.float32), params)


def _seed_parameter() -> ParameterSpec:
    return ParameterSpec(
        "seed", "Seed", "int", 1, 0, 999999, 1, animatable=True,
        slider_maximum=1000, fine_step=1, coarse_step=10, is_random_seed=True,
    )


def _evolution_parameters() -> tuple[ParameterSpec, ...]:
    f = ParameterSpec
    return (
        f("evolution", "Evolution", "float", 0.0, 0.0, 1.0, 0.001, animatable=True,
          description="Normalised loop phase. Connect Loop Phase directly; 0 and 1 form one complete loop."),
        f("loop_cycles", "Loop Cycles", "float", 1.0, 0.25, 16.0, 0.25, animatable=True),
    )


def _disorder_parameters(*, amount: float = 0.3, scale: float = 3.0) -> tuple[ParameterSpec, ...]:
    f = ParameterSpec
    return (
        f("disorder", "Disorder", "float", amount, 0.0, 3.0, 0.01, animatable=True),
        f("disorder_scale", "Disorder Scale", "float", scale, 1.0, 64.0, 1.0, animatable=True),
        f("disorder_anisotropy", "Disorder Anisotropy", "float", 0.0, 0.0, 1.0, 0.01, animatable=True),
        f("disorder_angle", "Disorder Angle", "float", 0.0, -180.0, 180.0, 1.0, animatable=True, editor="angle", unit="degrees"),
    )


def _finish_parameters(*, contrast: float = 1.0, balance: float = 0.0) -> tuple[ParameterSpec, ...]:
    f = ParameterSpec
    return (
        f("contrast", "Contrast", "float", contrast, 0.05, 8.0, 0.05, animatable=True),
        f("balance", "Balance", "float", balance, -1.0, 1.0, 0.01, animatable=True),
        f("invert", "Invert", "bool", False),
    )


def _cloud_parameters(variant: int) -> tuple[ParameterSpec, ...]:
    f = ParameterSpec
    defaults = {
        1: (6.0, 6, 0.62),
        2: (4.0, 5, 0.45),
        3: (5.0, 6, 0.58),
    }[variant]
    specific: tuple[ParameterSpec, ...]
    if variant == 1:
        specific = (f("softness", "Softness", "float", 0.42, 0.0, 1.0, 0.01, animatable=True),)
    elif variant == 2:
        specific = (f("puffiness", "Puffiness", "float", 1.8, 0.25, 4.0, 0.01, animatable=True),)
    else:
        specific = (
            f("erosion", "Erosion", "float", 0.38, 0.0, 1.0, 0.01, animatable=True),
            f("detail", "Fine Detail", "float", 0.65, 0.0, 1.0, 0.01, animatable=True),
        )
    return (
        f("scale", "Scale", "float", defaults[0], 1.0, 64.0, 1.0, animatable=True),
        f("octaves", "Octaves", "int", defaults[1], 1, 10, 1, animatable=True),
        f("roughness", "Roughness", "float", defaults[2], 0.0, 1.0, 0.01, animatable=True),
        *specific,
        _seed_parameter(),
        *_evolution_parameters(),
        *_disorder_parameters(amount=0.35 if variant != 1 else 0.2, scale=3.0),
        *_finish_parameters(contrast=1.05 if variant == 3 else 1.0, balance=-0.04 if variant == 2 else 0.0),
    )


def _spot_parameters(variant: int) -> tuple[ParameterSpec, ...]:
    f = ParameterSpec
    defaults = {1: (5.0, 0.72, 0.72), 2: (6.0, 0.58, 0.62), 3: (4.0, 0.50, 0.50)}[variant]
    return (
        f("scale", "Scale", "float", defaults[0], 1.0, 128.0, 1.0, animatable=True),
        f("roughness", "Roughness", "float", defaults[1], 0.0, 1.0, 0.01, animatable=True),
        f("grain", "Fine Grain", "float", defaults[2], 0.0, 1.0, 0.01, animatable=True),
        _seed_parameter(),
        *_evolution_parameters(),
        *_disorder_parameters(amount=0.28, scale=4.0),
        *_finish_parameters(contrast=1.18 if variant == 1 else 1.08),
    )

def _structured_parameters(kind: str) -> tuple[ParameterSpec, ...]:
    f = ParameterSpec
    if kind == "anisotropic":
        return (
            f("scale_x", "Scale X", "int", 5, 1, 128, 1, animatable=True),
            f("scale_y", "Scale Y", "int", 34, 1, 256, 1, animatable=True),
            f("smoothness", "Smoothness", "float", 1.0, 0.0, 1.0, 0.01, animatable=True),
            f("interpolation", "Interpolation", "float", 1.0, 0.0, 1.0, 0.01, animatable=True),
            _seed_parameter(),
            *_evolution_parameters(),
        )
    defaults = {
        "fibres": (28.0, 2, 1.65, 0.045, 0.25, 0.0, 18.0, 0.4),
        "messy": (18.0, 2, 1.45, 0.08, 0.32, 0.0, 105.0, 0.68),
        "fur": (24.0, 3, 0.85, 0.05, 0.22, -90.0, 24.0, 0.52),
    }[kind]
    common: tuple[ParameterSpec, ...] = (
        f("scale", "Scale", "float", defaults[0], 1.0, 128.0, 1.0, animatable=True),
        f("density", "Density", "int", defaults[1], 1, 3, 1, animatable=True),
        f("length", "Length", "float", defaults[2], 0.05, 3.0, 0.01, animatable=True),
        f("width", "Width", "float", defaults[3], 0.002, 0.4, 0.002, animatable=True),
        f("softness", "Softness", "float", defaults[4], 0.0, 1.0, 0.01, animatable=True),
        f("angle", "Angle", "float", defaults[5], -180.0, 180.0, 1.0, animatable=True, editor="angle", unit="degrees"),
        f("angle_random", "Angle Random", "float", defaults[6], 0.0, 180.0, 1.0, animatable=True),
        f("luminance_random", "Luminance Random", "float", defaults[7], 0.0, 1.0, 0.01, animatable=True),
    )
    extra: tuple[ParameterSpec, ...] = ()
    if kind == "messy":
        extra = (
            f("messiness", "Messiness", "float", 1.15, 0.0, 3.0, 0.01, animatable=True),
            f("messiness_scale", "Messiness Scale", "float", 5.0, 1.0, 64.0, 1.0, animatable=True),
            f("breakage", "Breakage", "float", 0.38, 0.0, 1.0, 0.01, animatable=True),
        )
    return (*common, *extra, _seed_parameter(), *_evolution_parameters(), *_disorder_parameters(amount=0.15 if kind == "fibres" else 0.35, scale=5.0), *_finish_parameters(contrast=1.15 if kind == "fur" else 1.0, balance=-0.15 if kind in {"fibres", "messy", "fur"} else 0.0))


def register_foundational_noise_nodes(registry: NodeRegistry) -> None:
    f = ParameterSpec
    definitions = [
        NodeDefinition("noise.clouds_1", "Clouds 1", "Noise/Foundational", eval_clouds_1, parameters=_cloud_parameters(1), description="Fine layered cloud noise with dense wispy multi-scale structure.", accent=_NOISE_ACCENT, tags=("clouds", "smoke", "soft", "organic"), output_format="r16f", gpu_kernel="foundational_noise.wgsl"),
        NodeDefinition("noise.clouds_2", "Clouds 2", "Noise/Foundational", eval_clouds_2, parameters=_cloud_parameters(2), description="Broad soft cloud masses with low-frequency vapour and restrained detail.", accent=_NOISE_ACCENT, tags=("clouds", "vapour", "smoke", "soft"), output_format="r16f", gpu_kernel="foundational_noise.wgsl"),
        NodeDefinition("noise.clouds_3", "Clouds 3", "Noise/Foundational", eval_clouds_3, parameters=_cloud_parameters(3), description="Dense rough cloud noise with dark mottling and fine breakup.", accent=_NOISE_ACCENT, tags=("clouds", "mottled", "rough", "storm"), output_format="r16f", gpu_kernel="foundational_noise.wgsl"),
        NodeDefinition("noise.bnw_spots_1", "BnW Spots 1", "Noise/Foundational", eval_bnw_spots_1, parameters=_spot_parameters(1), description="High-contrast multiscale black and white deposits built from sparse signed spots.", accent=_NOISE_ACCENT, tags=("black white", "spots", "cells", "mask"), output_format="r16f", gpu_kernel="foundational_noise.wgsl"),
        NodeDefinition("noise.bnw_spots_2", "BnW Spots 2", "Noise/Foundational", eval_bnw_spots_2, parameters=_spot_parameters(2), description="Broad mottling covered with dense fine black and white speckles.", accent=_NOISE_ACCENT, tags=("black white", "spots", "clustered", "organic"), output_format="r16f", gpu_kernel="foundational_noise.wgsl"),
        NodeDefinition("noise.bnw_spots_3", "BnW Spots 3", "Noise/Foundational", eval_bnw_spots_3, parameters=_spot_parameters(3), description="Broad soft black and white spot fields with restrained granular detail.", accent=_NOISE_ACCENT, tags=("black white", "spots", "mottle", "rough"), output_format="r16f", gpu_kernel="foundational_noise.wgsl"),
        NodeDefinition("noise.crystal_1", "Crystal 1", "Noise/Foundational", eval_crystal_1, parameters=(f("scale_x", "Scale X", "float", 16.0, 1.0, 256.0, 1.0, animatable=True), f("scale_y", "Scale Y", "float", 16.0, 1.0, 256.0, 1.0, animatable=True), _seed_parameter(), *_evolution_parameters(), *_finish_parameters()), description="Dark faceted crystal pattern produced by combining two independently randomised Voronoi distance fields.", accent=_NOISE_ACCENT, tags=("crystal", "facets", "mineral", "dual voronoi"), output_format="r16f", gpu_kernel="foundational_noise.wgsl"),
        NodeDefinition("noise.crystal_2", "Crystal 2", "Noise/Foundational", eval_crystal_2, parameters=(f("scale", "Scale", "float", 6.0, 1.0, 16.0, 1.0, animatable=True), f("jitter", "Disorder", "float", 0.72, 0.0, 1.0, 0.01, animatable=True), f("facet_sharpness", "Fold Sharpness", "float", 1.0, 0.25, 3.0, 0.01, animatable=True), f("edge_weight", "Fold Strength", "float", 0.62, 0.0, 1.0, 0.01, animatable=True), f("angle", "Fold Direction", "float", 90.0, -180.0, 180.0, 1.0, animatable=True, editor="angle", unit="degrees"), _seed_parameter(), *_evolution_parameters(), *_finish_parameters()), description="Long angular triangular fold planes for cloth creases, marble and crystalline surfaces.", accent=_NOISE_ACCENT, tags=("crystal", "crease", "cloth", "marble"), output_format="r16f", gpu_kernel="foundational_noise.wgsl"),
        NodeDefinition("noise.fractal_sum", "Fractal Sum", "Noise/Foundational", eval_fractal_sum, parameters=(f("roughness", "Roughness", "float", 0.58, 0.0, 1.0, 0.01, animatable=True), f("min_level", "Minimum Level", "int", 0, 0, 9, 1, animatable=True), f("max_level", "Maximum Level", "int", 7, 0, 10, 1, animatable=True), f("global_opacity", "Global Opacity", "float", 1.55, 0.0, 2.0, 0.01, animatable=True), _seed_parameter(), *_evolution_parameters(), f("disorder", "Disorder", "float", 0.15, 0.0, 3.0, 0.01, animatable=True), f("disorder_scale", "Disorder Scale", "float", 3.0, 1.0, 64.0, 1.0, animatable=True), *_finish_parameters()), description="Customisable octave sum with minimum/maximum frequency levels and roughness balance.", accent=_NOISE_ACCENT, tags=("fractal sum", "fbm", "octaves", "detail"), output_format="r16f", gpu_kernel="foundational_noise.wgsl"),
        NodeDefinition("noise.anisotropic", "Anisotropic Noise", "Noise/Structured", eval_anisotropic_noise, parameters=_structured_parameters("anisotropic"), description="Anisotropic value noise: a stack of long random strips with controllable X/Y subdivisions, fade width and interpolation.", accent=_NOISE_ACCENT, tags=("anisotropic", "directional", "strips", "value noise", "brushed"), output_format="r16f", gpu_kernel="foundational_noise.wgsl"),
        NodeDefinition("noise.fibres", "Fibres", "Noise/Structured", eval_fibres, parameters=_structured_parameters("fibres"), description="Orderly elongated fibres with density, length, width and directional variation.", accent=_NOISE_ACCENT, tags=("fibres", "fabric", "threads", "hair"), output_format="r16f", gpu_kernel="foundational_noise.wgsl"),
        NodeDefinition("noise.messy_fibres", "Messy Fibres", "Noise/Structured", eval_messy_fibres, parameters=_structured_parameters("messy"), description="Warped, broken and strongly varied fibres for rough cloth and organic wear.", accent=_NOISE_ACCENT, tags=("messy fibres", "fabric", "threads", "wear"), output_format="r16f", gpu_kernel="foundational_noise.wgsl"),
        NodeDefinition(
            "noise.moisture", "Moisture Noise", "Noise/Structured", eval_moisture_noise,
            parameters=(
                f("scale", "Scale", "float", 8.0, 1.0, 128.0, 1.0, animatable=True),
                f("pool_size", "Pool Size", "float", 1.0, 0.35, 2.5, 0.01, animatable=True),
                f("fine_detail", "Fine Detail", "float", 0.65, 0.0, 1.0, 0.01, animatable=True),
                f("patchiness", "Patchiness", "float", 0.72, 0.0, 1.0, 0.01, animatable=True),
                f("disorder", "Disorder", "float", 0.28, 0.0, 2.0, 0.01, animatable=True),
                _seed_parameter(), *_evolution_parameters(), *_finish_parameters(contrast=1.0, balance=0.0),
            ),
            description="Soft positive and negative moisture deposits layered over broad damp patches and fine condensation specks.",
            accent=_NOISE_ACCENT, tags=("moisture", "wet", "condensation", "stains", "organic"),
            output_format="r16f", gpu_kernel="foundational_noise.wgsl",
        ),
        NodeDefinition("noise.fur", "Fur", "Noise/Structured", eval_fur, parameters=_structured_parameters("fur"), description="Dense tapered hair strokes with an irregular undercoat for fur and short fibres.", accent=_NOISE_ACCENT, tags=("fur", "hair", "fibres", "animal"), output_format="r16f", gpu_kernel="foundational_noise.wgsl"),
    ]
    for definition in definitions:
        registry.register(replace(
            definition,
            output_kinds=((definition.output_name, "grayscale"),),
            default_image_kind="grayscale",
        ))
