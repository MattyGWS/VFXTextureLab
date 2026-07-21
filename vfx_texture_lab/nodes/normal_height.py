from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np

from .base import EvalContext, ImageArray, NodeDefinition, ParameterSpec
from .image_ops import empty_image, ensure_rgba, grayscale_rgba, luminance, resolution_scale
from .registry import NodeRegistry
from .resampling import BOUNDARY_OPTIONS, FILTERING_OPTIONS, affine_pixel_footprint, boundary_name, sample_image
from .surface_analysis import (
    _height,
    _joint_bilateral_pass,
    _minmod,
    _rtao_distribution_cosine,
    _rtao_rotation_field,
    _rtao_step_count,
    _sample_height,
    _sample_height_positions,
)

_NORMAL_ACCENT = "#5d91c7"
_FORMATS = ("OpenGL (+Y)", "DirectX (-Y)")


def _flat_normal(context: EvalContext) -> np.ndarray:
    result = np.empty((context.height, context.width, 3), dtype=np.float32)
    result[..., 0] = 0.0
    result[..., 1] = 0.0
    result[..., 2] = 1.0
    return result


def _decode_normal(
    source: ImageArray | None,
    context: EvalContext,
    normal_format: str = "OpenGL (+Y)",
) -> np.ndarray:
    if source is None:
        normal = _flat_normal(context)
    else:
        normal = ensure_rgba(source, context)[..., :3].astype(np.float32, copy=False) * 2.0 - 1.0
    if str(normal_format) == "DirectX (-Y)":
        normal = normal.copy()
        normal[..., 1] *= -1.0
    length = np.linalg.norm(normal, axis=2, keepdims=True)
    normal = normal / np.maximum(length, np.float32(1.0e-7))
    invalid = length[..., 0] <= 1.0e-7
    if np.any(invalid):
        normal = normal.copy()
        normal[invalid] = np.array((0.0, 0.0, 1.0), dtype=np.float32)
    return normal.astype(np.float32, copy=False)


def _encode_normal(normal: np.ndarray, normal_format: str = "OpenGL (+Y)") -> ImageArray:
    value = np.asarray(normal, dtype=np.float32)
    length = np.linalg.norm(value, axis=2, keepdims=True)
    value = value / np.maximum(length, np.float32(1.0e-7))
    invalid = length[..., 0] <= 1.0e-7
    if np.any(invalid):
        value = value.copy()
        value[invalid] = np.array((0.0, 0.0, 1.0), dtype=np.float32)
    if str(normal_format) == "DirectX (-Y)":
        value = value.copy()
        value[..., 1] *= -1.0
    alpha = np.ones((*value.shape[:2], 1), dtype=np.float32)
    return np.concatenate((np.clip(value * 0.5 + 0.5, 0.0, 1.0), alpha), axis=2).astype(np.float32)


def _strengthen(normal: np.ndarray, strength: float) -> np.ndarray:
    strength = max(float(strength), 0.0)
    result = normal.copy()
    result[..., :2] *= np.float32(strength)
    length = np.linalg.norm(result, axis=2, keepdims=True)
    return result / np.maximum(length, np.float32(1.0e-7))


def _mask(inputs: Mapping[str, ImageArray], context: EvalContext) -> np.ndarray:
    source = inputs.get("Mask")
    if source is None:
        return np.ones((context.height, context.width), dtype=np.float32)
    return np.clip(luminance(ensure_rgba(source, context)), 0.0, 1.0).astype(np.float32, copy=False)


def eval_normal_blend(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    normal_format = str(params.get("normal_format", "OpenGL (+Y)"))
    background = _decode_normal(inputs.get("Background"), context, normal_format)
    foreground = _decode_normal(inputs.get("Foreground"), context, normal_format)
    amount = np.clip(float(params.get("amount", 1.0)), 0.0, 1.0)
    blend = (_mask(inputs, context) * np.float32(amount))[..., None]
    result = background * (np.float32(1.0) - blend) + foreground * blend
    return _encode_normal(result, normal_format)


def _rnm(base: np.ndarray, detail: np.ndarray) -> np.ndarray:
    # Reoriented Normal Mapping. A flat detail normal is an exact identity.
    t = base + np.array((0.0, 0.0, 1.0), dtype=np.float32)
    u = detail * np.array((-1.0, -1.0, 1.0), dtype=np.float32)
    dot_tu = np.sum(t * u, axis=2, keepdims=True)
    result = t * (dot_tu / np.maximum(t[..., 2:3], np.float32(1.0e-6))) - u
    return result


def eval_normal_combine(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    normal_format = str(params.get("normal_format", "OpenGL (+Y)"))
    base = _strengthen(
        _decode_normal(inputs.get("Base"), context, normal_format),
        float(params.get("base_strength", 1.0)),
    )
    detail = _strengthen(
        _decode_normal(inputs.get("Detail"), context, normal_format),
        float(params.get("detail_strength", 1.0)),
    )
    method = str(params.get("method", "Reoriented (RNM)"))
    if method == "Whiteout":
        combined = np.stack(
            (base[..., 0] + detail[..., 0], base[..., 1] + detail[..., 1], base[..., 2] * detail[..., 2]),
            axis=2,
        )
    elif method == "UDN":
        combined = np.stack(
            (base[..., 0] + detail[..., 0], base[..., 1] + detail[..., 1], base[..., 2]),
            axis=2,
        )
    else:
        combined = _rnm(base, detail)
    amount = np.clip(float(params.get("amount", 1.0)), 0.0, 1.0)
    blend = (_mask(inputs, context) * np.float32(amount))[..., None]
    result = base * (np.float32(1.0) - blend) + combined * blend
    return _encode_normal(result, normal_format)


def eval_normal_normalize(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    normal_format = str(params.get("normal_format", "OpenGL (+Y)"))
    return _encode_normal(_decode_normal(inputs.get("Normal"), context, normal_format), normal_format)


def eval_normal_invert(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    normal_format = str(params.get("normal_format", "OpenGL (+Y)"))
    normal = _decode_normal(inputs.get("Normal"), context, normal_format).copy()
    if bool(params.get("invert_x", False)):
        normal[..., 0] *= -1.0
    if bool(params.get("invert_y", False)):
        normal[..., 1] *= -1.0
    if bool(params.get("invert_z", False)):
        normal[..., 2] *= -1.0
    return _encode_normal(normal, normal_format)


def eval_normal_vector_rotation(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    """Rotate tangent-space XY directions without moving the texture itself.

    This is intentionally distinct from Normal Transform: every texel remains at
    the same UV coordinate while its tangent-space vector is rotated around +Z.
    """
    normal_format = str(params.get("normal_format", "OpenGL (+Y)"))
    normal = _decode_normal(inputs.get("Normal"), context, normal_format).copy()
    angle = math.radians(float(params.get("angle", 0.0)))
    c = np.float32(math.cos(angle))
    s = np.float32(math.sin(angle))
    nx = normal[..., 0] * c - normal[..., 1] * s
    ny = normal[..., 0] * s + normal[..., 1] * c
    normal[..., 0] = nx
    normal[..., 1] = ny
    return _encode_normal(normal, normal_format)


def eval_directional_lighting(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    """Bake an artist-controlled directional light mask from tangent-space normals.

    Angle is measured in image space and points *toward* the light. Elevation
    lifts that direction out of the texture plane toward the viewer. Diffuse and
    highlight responses are kept separate internally, then combined into one
    grayscale mask so the node remains useful as a compact material-building
    filter rather than a scene-lighting system.
    """
    normal_format = str(params.get("normal_format", "OpenGL (+Y)"))
    normal = _decode_normal(inputs.get("Normal"), context, normal_format)

    angle = math.radians(float(params.get("angle", 45.0)))
    elevation = math.radians(min(max(float(params.get("elevation", 45.0)), 0.0), 90.0))
    horizontal = math.cos(elevation)
    light = np.array(
        (math.cos(angle) * horizontal, math.sin(angle) * horizontal, math.sin(elevation)),
        dtype=np.float32,
    )
    light /= max(float(np.linalg.norm(light)), 1.0e-7)

    ndotl = np.clip(np.sum(normal * light[None, None, :], axis=2), 0.0, 1.0)
    diffuse_power = max(float(params.get("diffuse_power", 1.0)), 0.01)
    diffuse_brightness = max(float(params.get("diffuse_brightness", 1.0)), 0.0)
    diffuse = np.power(ndotl, np.float32(diffuse_power), dtype=np.float32) * np.float32(diffuse_brightness)

    view = np.array((0.0, 0.0, 1.0), dtype=np.float32)
    half_vector = light + view
    half_vector /= max(float(np.linalg.norm(half_vector)), 1.0e-7)
    ndoth = np.clip(np.sum(normal * half_vector[None, None, :], axis=2), 0.0, 1.0)
    highlight_power = max(float(params.get("highlight_power", 16.0)), 1.0)
    highlight_brightness = max(float(params.get("highlight_brightness", 0.0)), 0.0)
    highlight = np.power(ndoth, np.float32(highlight_power), dtype=np.float32) * np.float32(highlight_brightness)

    ambient = np.float32(min(max(float(params.get("ambient", 0.0)), 0.0), 1.0))
    value = np.clip(ambient + diffuse + highlight, 0.0, 1.0)
    if bool(params.get("invert", False)):
        value = 1.0 - value
    return grayscale_rgba(value.astype(np.float32, copy=False))


def _pixel_grids(context: EvalContext) -> tuple[np.ndarray, np.ndarray]:
    yy, xx = np.mgrid[0:context.height, 0:context.width]
    return xx.astype(np.float32), yy.astype(np.float32)


def _resolved_indices(values: np.ndarray, size: int, wrap: bool) -> np.ndarray:
    if wrap:
        return np.mod(values, size).astype(np.int32)
    return np.clip(values, 0, size - 1).astype(np.int32)


def _sample_normal_bilinear(image: np.ndarray, sx: np.ndarray, sy: np.ndarray, wrap: bool) -> np.ndarray:
    height, width = image.shape[:2]
    x0f = np.floor(sx)
    y0f = np.floor(sy)
    x0 = _resolved_indices(x0f, width, wrap)
    y0 = _resolved_indices(y0f, height, wrap)
    x1 = _resolved_indices(x0f + 1.0, width, wrap)
    y1 = _resolved_indices(y0f + 1.0, height, wrap)
    tx = (sx - x0f)[..., None].astype(np.float32)
    ty = (sy - y0f)[..., None].astype(np.float32)
    top = image[y0, x0] * (1.0 - tx) + image[y0, x1] * tx
    bottom = image[y1, x0] * (1.0 - tx) + image[y1, x1] * tx
    return top * (1.0 - ty) + bottom * ty


def eval_normal_transform(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    normal_format = str(params.get("normal_format", "OpenGL (+Y)"))
    source_value = inputs.get("Normal")
    source_encoded = (
        ensure_rgba(source_value, context)
        if source_value is not None
        else _encode_normal(_flat_normal(context), normal_format)
    )
    uniform_scale = max(float(params.get("scale", 1.0)), 0.01)
    scale_x = max(float(params.get("scale_x", 1.0)) * uniform_scale, 0.01)
    scale_y = max(float(params.get("scale_y", 1.0)) * uniform_scale, 0.01)
    angle_degrees = float(params.get("angle", 0.0))
    offset_x = float(params.get("offset_x", 0.0))
    offset_y = float(params.get("offset_y", 0.0))
    boundary = boundary_name(params, default="Seamless / Wrap", legacy_key="tile")
    filtering = str(params.get("filtering", "Automatic"))

    if (abs(offset_x) <= 1.0e-12 and abs(offset_y) <= 1.0e-12
            and abs(scale_x - 1.0) <= 1.0e-12 and abs(scale_y - 1.0) <= 1.0e-12
            and abs(math.fmod(angle_degrees, 360.0)) <= 1.0e-12):
        return source_encoded.copy()

    angle = math.radians(angle_degrees)
    x, y = _pixel_grids(context)
    pixel_x = ((x + 0.5) / max(context.width, 1) - 0.5 - offset_x) * context.width
    pixel_y = ((y + 0.5) / max(context.height, 1) - 0.5 - offset_y) * context.height
    c = math.cos(-angle)
    ss = math.sin(-angle)
    source_pixel_x = (pixel_x * c - pixel_y * ss) / scale_x
    source_pixel_y = (pixel_x * ss + pixel_y * c) / scale_y
    sx = source_pixel_x + (context.width - 1.0) * 0.5
    sy = source_pixel_y + (context.height - 1.0) * 0.5
    footprint_x, footprint_y = affine_pixel_footprint(scale_x, scale_y, angle_degrees)
    sampled = sample_image(
        source_encoded, sx, sy, filtering=filtering, boundary=boundary, data_kind="vector",
        footprint_x=footprint_x, footprint_y=footprint_y,
    )
    result = _decode_normal(sampled, context, normal_format)

    # Rotate tangent-space direction with the spatial transform.
    c_out = math.cos(angle)
    s_out = math.sin(angle)
    nx = result[..., 0] * c_out - result[..., 1] * s_out
    ny = result[..., 0] * s_out + result[..., 1] * c_out
    result[..., 0] = nx
    result[..., 1] = ny
    return _encode_normal(result, normal_format)


def _normal_gradient(normal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    nz = np.maximum(np.abs(normal[..., 2]), np.float32(1.0e-4))
    return (-normal[..., 0] / nz).astype(np.float32), (-normal[..., 1] / nz).astype(np.float32)


def _frankot_chellappa(
    p: np.ndarray,
    q: np.ndarray,
    low_strength: float,
    high_strength: float,
) -> np.ndarray:
    height, width = p.shape
    p_hat = np.fft.fft2(p)
    q_hat = np.fft.fft2(q)
    fx = np.fft.fftfreq(width).astype(np.float64)[None, :]
    fy = np.fft.fftfreq(height).astype(np.float64)[:, None]
    wx = 2.0 * np.pi * fx
    wy = 2.0 * np.pi * fy
    denominator = wx * wx + wy * wy
    denominator[0, 0] = 1.0
    z_hat = (-1j * wx * p_hat - 1j * wy * q_hat) / denominator
    z_hat[0, 0] = 0.0

    radial = np.sqrt(fx * fx + fy * fy)
    low_mask = np.exp(-((radial / 0.085) ** 4.0))
    frequency_weight = low_mask * float(low_strength) + (1.0 - low_mask) * float(high_strength)
    z_hat *= frequency_weight
    return np.fft.ifft2(z_hat).real.astype(np.float32)


def eval_normal_to_height(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    normal_format = str(params.get("normal_format", "OpenGL (+Y)"))
    normal = _decode_normal(inputs.get("Normal"), context, normal_format)
    p, q = _normal_gradient(normal)
    height = _frankot_chellappa(
        p,
        q,
        np.clip(float(params.get("low_frequency", 1.0)), 0.0, 2.0),
        np.clip(float(params.get("high_frequency", 1.0)), 0.0, 2.0),
    )
    intensity = max(float(params.get("intensity", 1.0)), 0.0)
    if bool(params.get("normalize", True)):
        minimum = float(np.min(height))
        maximum = float(np.max(height))
        if maximum - minimum > 1.0e-8:
            height = (height - minimum) / np.float32(maximum - minimum)
            height = np.clip(0.5 + (height - 0.5) * np.float32(intensity), 0.0, 1.0)
        else:
            height = np.full_like(height, 0.5, dtype=np.float32)
    else:
        height *= np.float32(intensity / max(float(min(context.width, context.height)), 1.0))
        height = np.clip(0.5 + height, 0.0, 1.0)
    if bool(params.get("invert", False)):
        height = 1.0 - height
    return grayscale_rgba(np.clip(height, 0.0, 1.0).astype(np.float32, copy=False))


def _trace_visibility_and_bent(
    height: np.ndarray,
    params: Mapping[str, Any],
    context: EvalContext,
) -> tuple[np.ndarray, np.ndarray]:
    height_scale = max(float(params.get("height_scale", 1.0)), 0.0)
    maximum_distance = float(np.clip(params.get("maximum_distance", 0.15), 0.0, 1.0))
    spread = float(np.clip(params.get("spread_angle", 1.0), 0.0, 1.0))
    requested_samples = int(np.clip(int(params.get("samples", 16)), 4, 64))
    samples = min(requested_samples, 6) if context.render_mode == "interactive" else requested_samples
    steps = _rtao_step_count(samples, context.render_mode == "interactive")
    distribution = str(params.get("distribution", "Cosine Weighted"))
    boundary = str(params.get("boundary", "Seamless / Wrap"))

    if height_scale <= 1.0e-8 or maximum_distance <= 1.0e-8 or spread <= 1.0e-8:
        visibility = np.ones_like(height, dtype=np.float32)
        return visibility, _flat_normal(context)

    minimum_dimension = float(max(min(context.width, context.height), 1))
    maximum_distance_pixels = max(maximum_distance * minimum_dimension, 1.0)
    left = _sample_height(height, 0, -1, boundary)
    right = _sample_height(height, 0, 1, boundary)
    up = _sample_height(height, -1, 0, boundary)
    down = _sample_height(height, 1, 0, boundary)
    grad_x = _minmod(height - left, right - height)
    grad_y = _minmod(height - up, down - height)
    yy, xx = np.mgrid[0:context.height, 0:context.width]
    base_x = xx.astype(np.float32)
    base_y = yy.astype(np.float32)
    rotation = _rtao_rotation_field(context.width, context.height)
    visible_count = np.zeros_like(height, dtype=np.float32)
    bent = np.zeros((context.height, context.width, 3), dtype=np.float32)
    golden_ratio = 0.6180339887498949
    origin_bias = np.float32(0.00025 + height_scale * 0.0005)

    pair_count = max((samples + 1) // 2, 1)
    for ray_index in range(samples):
        pair_index = ray_index // 2
        fraction = (pair_index + 0.5) / pair_count
        cosine = float(np.clip(_rtao_distribution_cosine(fraction, spread, distribution), 0.0, 1.0))
        sine = math.sqrt(max(1.0 - cosine * cosine, 0.0))
        if sine <= 1.0e-7:
            continue
        cotangent = np.float32(cosine / max(sine, 1.0e-6))
        opposite = np.float32(0.5 if (ray_index & 1) else 0.0)
        angle = (rotation + np.float32(pair_index * golden_ratio) + opposite) % np.float32(1.0)
        angle *= np.float32(math.tau)
        direction_x = np.cos(angle).astype(np.float32, copy=False)
        direction_y = np.sin(angle).astype(np.float32, copy=False)
        hit = np.zeros_like(height, dtype=bool)
        for step_index in range(steps):
            step_fraction = ((step_index + 1.0) / steps) ** 1.35
            distance_pixels = np.float32(maximum_distance_pixels * step_fraction)
            offset_x = direction_x * distance_pixels
            offset_y = direction_y * distance_pixels
            sample = _sample_height_positions(height, base_y + offset_y, base_x + offset_x, boundary)
            tangent_height = height + grad_x * offset_x + grad_y * offset_y
            relative_surface = (sample - tangent_height) * np.float32(height_scale)
            ray_height = np.float32(distance_pixels / minimum_dimension) * cotangent
            hit |= relative_surface > ray_height + origin_bias
            if bool(np.all(hit)):
                break
        visible = (~hit).astype(np.float32)
        visible_count += visible
        bent[..., 0] += visible * direction_x * np.float32(sine)
        bent[..., 1] += visible * direction_y * np.float32(sine)
        bent[..., 2] += visible * np.float32(cosine)

    # Avoid unstable horizontal vectors when every sampled ray is blocked.
    no_visibility = visible_count <= 1.0e-6
    bent[no_visibility] = np.array((0.0, 0.0, 1.0), dtype=np.float32)
    visibility = visible_count / np.float32(max(samples, 1))
    return visibility, bent


def eval_bent_normal(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    height = _height(inputs, context)
    _visibility, bent = _trace_visibility_and_bent(height, params, context)
    denoise = np.clip(float(params.get("denoise", 0.75)), 0.0, 1.0)
    maximum_distance = np.clip(float(params.get("maximum_distance", 0.15)), 0.0, 1.0)
    height_scale = max(float(params.get("height_scale", 1.0)), 0.0)
    boundary = str(params.get("boundary", "Seamless / Wrap"))
    if denoise > 1.0e-8 and maximum_distance > 1.0e-8:
        maximum_distance_pixels = max(maximum_distance * min(context.width, context.height), 1.0)
        sigma = float(np.clip(0.55 + maximum_distance_pixels * 0.035 * denoise, 0.55, 5.0))
        if context.render_mode == "interactive":
            sigma = min(sigma, 2.0)
        height_sigma = float(np.clip(0.018 + 0.035 / (1.0 + height_scale), 0.018, 0.053))
        for channel in range(3):
            horizontal = _joint_bilateral_pass(
                bent[..., channel], height, sigma, height_sigma, axis=1, boundary=boundary
            )
            bent[..., channel] = _joint_bilateral_pass(
                horizontal, height, sigma, height_sigma, axis=0, boundary=boundary
            )
    return _encode_normal(bent, str(params.get("normal_format", "OpenGL (+Y)")))


def eval_rt_shadows(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    height = _height(inputs, context)
    height_scale = max(float(params.get("height_scale", 1.0)), 0.0)
    maximum_distance = float(np.clip(params.get("maximum_distance", 0.25), 0.0, 1.0))
    elevation = math.radians(np.clip(float(params.get("elevation", 35.0)), 0.1, 89.9))
    azimuth = math.radians(float(params.get("angle", 45.0)))
    softness = float(np.clip(params.get("softness", 0.15), 0.0, 1.0))
    requested_samples = int(np.clip(int(params.get("samples", 8)), 1, 32))
    samples = min(requested_samples, 4) if context.render_mode == "interactive" else requested_samples
    boundary = str(params.get("boundary", "Seamless / Wrap"))
    bias = max(float(params.get("bias", 0.001)), 0.0)
    strength = np.clip(float(params.get("strength", 1.0)), 0.0, 1.0)

    if height_scale <= 1.0e-8 or maximum_distance <= 1.0e-8:
        values = np.ones_like(height, dtype=np.float32)
    else:
        minimum_dimension = float(max(min(context.width, context.height), 1))
        maximum_distance_pixels = max(maximum_distance * minimum_dimension, 1.0)
        steps = 12 if context.render_mode == "interactive" else (20 if samples <= 8 else 28)
        left = _sample_height(height, 0, -1, boundary)
        right = _sample_height(height, 0, 1, boundary)
        up = _sample_height(height, -1, 0, boundary)
        down = _sample_height(height, 1, 0, boundary)
        grad_x = _minmod(height - left, right - height)
        grad_y = _minmod(height - up, down - height)
        yy, xx = np.mgrid[0:context.height, 0:context.width]
        base_x = xx.astype(np.float32)
        base_y = yy.astype(np.float32)
        lit = np.zeros_like(height, dtype=np.float32)
        golden_angle = math.pi * (3.0 - math.sqrt(5.0))
        tan_elevation = math.tan(elevation)
        origin_bias = np.float32(bias + 0.00025)

        for sample_index in range(samples):
            if samples == 1 or softness <= 1.0e-8:
                sample_azimuth = azimuth
                sample_elevation = elevation
            else:
                radius = math.sqrt((sample_index + 0.5) / samples) * softness
                phase = sample_index * golden_angle
                sample_azimuth = azimuth + math.cos(phase) * radius * 0.40
                sample_elevation = np.clip(elevation + math.sin(phase) * radius * 0.25, math.radians(0.1), math.radians(89.9))
            direction_x = np.float32(math.cos(sample_azimuth))
            direction_y = np.float32(math.sin(sample_azimuth))
            ray_slope = np.float32(math.tan(float(sample_elevation)))
            hit = np.zeros_like(height, dtype=bool)
            for step_index in range(steps):
                fraction = ((step_index + 1.0) / steps) ** 1.25
                distance_pixels = np.float32(maximum_distance_pixels * fraction)
                offset_x = direction_x * distance_pixels
                offset_y = direction_y * distance_pixels
                sample = _sample_height_positions(height, base_y + offset_y, base_x + offset_x, boundary)
                tangent_height = height + grad_x * offset_x + grad_y * offset_y
                relative_surface = (sample - tangent_height) * np.float32(height_scale)
                ray_height = np.float32(distance_pixels / minimum_dimension) * ray_slope
                hit |= relative_surface > ray_height + origin_bias
                if bool(np.all(hit)):
                    break
            lit += (~hit).astype(np.float32)
        values = lit / np.float32(max(samples, 1))
        values = np.float32(1.0) - (np.float32(1.0) - values) * np.float32(strength)
    if bool(params.get("invert", False)):
        values = 1.0 - values
    return grayscale_rgba(np.clip(values, 0.0, 1.0).astype(np.float32, copy=False))


def _format_parameter() -> ParameterSpec:
    return ParameterSpec(
        "normal_format",
        "Normal Format",
        "enum",
        "OpenGL (+Y)",
        options=_FORMATS,
        description="Convention used by the encoded tangent-space normal map.",
    )


def _ray_parameters(*, include_normal_format: bool) -> tuple[ParameterSpec, ...]:
    f = ParameterSpec
    values: list[ParameterSpec] = [
        f("height_scale", "Height Scale", "float", 1.0, 0.0, 10.0, 0.05, animatable=True),
        f("samples", "Samples", "int", 16, 4, 64, 4, description="Hemisphere rays per pixel. Interactive drags use a reduced draft count."),
        f("distribution", "Distribution", "enum", "Cosine Weighted", options=("Uniform", "Cosine Weighted", "Horizon Weighted")),
        f("maximum_distance", "Maximum Distance", "float", 0.15, 0.0, 1.0, 0.01, animatable=True),
        f("spread_angle", "Spread Angle", "float", 1.0, 0.0, 1.0, 0.01, animatable=True),
        f("denoise", "Denoise", "float", 0.75, 0.0, 1.0, 0.01, animatable=True),
        f("boundary", "Boundary", "enum", "Seamless / Wrap", options=("Seamless / Wrap", "Clamp")),
    ]
    if include_normal_format:
        values.append(_format_parameter())
    return tuple(values)


def register_normal_height_nodes(registry: NodeRegistry) -> None:
    f = ParameterSpec
    category = "Filters/Normal & Height"
    registry.register(NodeDefinition(
        "normal.blend", "Normal Blend", category, eval_normal_blend,
        inputs=("Background", "Foreground", "Mask"),
        parameters=(
            f("amount", "Amount", "float", 1.0, 0.0, 1.0, 0.01, animatable=True),
            _format_parameter(),
        ),
        description="Crossfade tangent-space normal maps through an optional mask and renormalise the result.",
        accent=_NORMAL_ACCENT, tags=("normal", "blend", "mask", "layer"), gpu_kernel="normal_blend.wgsl",
        input_kinds=(("Background", "vector"), ("Foreground", "vector"), ("Mask", "grayscale")),
        output_kinds=(("Normal", "vector"),), output_name="Normal", default_image_kind="vector",
    ))
    registry.register(NodeDefinition(
        "normal.combine", "Normal Combine", category, eval_normal_combine,
        inputs=("Base", "Detail", "Mask"),
        parameters=(
            f("method", "Method", "enum", "Reoriented (RNM)", options=("Reoriented (RNM)", "Whiteout", "UDN")),
            f("base_strength", "Base Strength", "float", 1.0, 0.0, 4.0, 0.01, animatable=True),
            f("detail_strength", "Detail Strength", "float", 1.0, 0.0, 4.0, 0.01, animatable=True),
            f("amount", "Amount", "float", 1.0, 0.0, 1.0, 0.01, animatable=True),
            _format_parameter(),
        ),
        description="Layer detail normals over a base normal using RNM, Whiteout or UDN combination.",
        accent=_NORMAL_ACCENT, tags=("normal", "combine", "rnm", "whiteout", "udn", "detail"), gpu_kernel="normal_combine.wgsl",
        input_kinds=(("Base", "vector"), ("Detail", "vector"), ("Mask", "grayscale")),
        output_kinds=(("Normal", "vector"),), output_name="Normal", default_image_kind="vector",
    ))
    registry.register(NodeDefinition(
        "normal.normalize", "Normal Normalize", category, eval_normal_normalize,
        inputs=("Normal",), parameters=(_format_parameter(),),
        description="Restore unit-length tangent-space normals and replace invalid zero vectors with a flat normal.",
        accent=_NORMAL_ACCENT, tags=("normal", "normalize", "renormalize", "repair"), gpu_kernel="normal_normalize.wgsl",
        input_kinds=(("Normal", "vector"),), output_kinds=(("Normal", "vector"),), output_name="Normal", default_image_kind="vector",
    ))
    registry.register(NodeDefinition(
        "normal.invert", "Normal Invert", category, eval_normal_invert,
        inputs=("Normal",),
        parameters=(
            f("invert_x", "Invert X / Red", "bool", False),
            f("invert_y", "Invert Y / Green", "bool", False),
            f("invert_z", "Invert Z / Blue", "bool", False),
            _format_parameter(),
        ),
        description="Invert selected tangent-space normal axes and renormalise the result.",
        accent=_NORMAL_ACCENT, tags=("normal", "invert", "flip", "green", "directx", "opengl"), gpu_kernel="normal_invert.wgsl",
        input_kinds=(("Normal", "vector"),), output_kinds=(("Normal", "vector"),), output_name="Normal", default_image_kind="vector",
    ))
    registry.register(NodeDefinition(
        "normal.vector_rotation", "Normal Vector Rotation", category, eval_normal_vector_rotation,
        inputs=("Normal",),
        parameters=(
            f("angle", "Rotation", "float", 0.0, -3600.0, 3600.0, 0.1, animatable=True, editor="angle", unit="degrees", angle_wrap=False),
            _format_parameter(),
        ),
        description="Rotate tangent-space normal directions around the surface normal without moving or resampling the texture.",
        accent=_NORMAL_ACCENT, tags=("normal", "vector", "direction", "rotation", "rotate", "tangent"), gpu_kernel="normal_vector_rotation.wgsl",
        input_kinds=(("Normal", "vector"),), output_kinds=(("Normal", "vector"),), output_name="Normal", default_image_kind="vector",
    ))
    registry.register(NodeDefinition(
        "filter.directional_lighting", "Directional Lighting", category, eval_directional_lighting,
        inputs=("Normal",),
        parameters=(
            f("angle", "Light Angle", "float", 45.0, -3600.0, 3600.0, 0.1, animatable=True, editor="angle", unit="degrees", angle_wrap=True),
            f("elevation", "Light Elevation", "float", 45.0, 0.0, 90.0, 0.1, animatable=True, unit="degrees"),
            f("diffuse_power", "Diffuse Power", "float", 1.0, 0.01, 16.0, 0.01, animatable=True),
            f("diffuse_brightness", "Diffuse Brightness", "float", 1.0, 0.0, 4.0, 0.01, animatable=True),
            f("highlight_power", "Highlight Power", "float", 16.0, 1.0, 128.0, 0.5, animatable=True),
            f("highlight_brightness", "Highlight Brightness", "float", 0.0, 0.0, 4.0, 0.01, animatable=True),
            f("ambient", "Ambient", "float", 0.0, 0.0, 1.0, 0.01, animatable=True),
            f("invert", "Invert", "bool", False),
            _format_parameter(),
        ),
        description="Convert a tangent-space normal map into an art-directed grayscale directional-lighting mask with diffuse and optional highlight response.",
        accent=_NORMAL_ACCENT, tags=("normal", "directional", "lighting", "light", "baked", "mask", "diffuse", "highlight"), gpu_kernel="directional_lighting.wgsl",
        input_kinds=(("Normal", "vector"),), output_kinds=(("Lighting", "grayscale"),), output_name="Lighting", default_image_kind="grayscale", output_format="r16f",
    ))
    registry.register(NodeDefinition(
        "normal.transform", "Normal Transform", category, eval_normal_transform,
        inputs=("Normal",),
        parameters=(
            f("offset_x", "Offset X", "float", 0.0, -10.0, 10.0, 0.01, animatable=True),
            f("offset_y", "Offset Y", "float", 0.0, -10.0, 10.0, 0.01, animatable=True),
            f("scale", "Uniform Scale", "float", 1.0, 0.01, 100.0, 0.01, animatable=True, slider_maximum=4.0),
            f("scale_x", "Scale X", "float", 1.0, 0.01, 100.0, 0.01, animatable=True, slider_maximum=4.0),
            f("scale_y", "Scale Y", "float", 1.0, 0.01, 100.0, 0.01, animatable=True, slider_maximum=4.0),
            f("angle", "Rotation", "float", 0.0, -3600.0, 3600.0, 0.1, animatable=True, editor="angle", unit="degrees", angle_wrap=False),
            f("boundary", "Boundary", "enum", "Seamless / Wrap", options=BOUNDARY_OPTIONS),
            f("filtering", "Filtering", "enum", "Automatic", options=FILTERING_OPTIONS),
            _format_parameter(),
        ),
        description="Move, stretch and rotate a normal map with high-quality typed filtering while rotating and renormalising its tangent vectors correctly.",
        accent=_NORMAL_ACCENT, tags=("normal", "transform", "rotate", "scale", "offset", "tile"), gpu_kernel="normal_transform.wgsl",
        input_kinds=(("Normal", "vector"),), output_kinds=(("Normal", "vector"),), output_name="Normal", default_image_kind="vector",
    ))
    registry.register(NodeDefinition(
        "normal.to_height", "Normal to Height", category, eval_normal_to_height,
        inputs=("Normal",),
        parameters=(
            f("intensity", "Height Intensity", "float", 1.0, 0.0, 20.0, 0.05, animatable=True),
            f("low_frequency", "Low Frequency", "float", 1.0, 0.0, 2.0, 0.01, animatable=True),
            f("high_frequency", "High Frequency", "float", 1.0, 0.0, 2.0, 0.01, animatable=True),
            f("normalize", "Normalize Output", "bool", True),
            f("invert", "Invert", "bool", False),
            _format_parameter(),
        ),
        description="Reconstruct an approximate seamless height field from tangent-space normals using a global Poisson integration. Absolute height cannot be recovered from normals alone.",
        accent=_NORMAL_ACCENT, tags=("normal", "height", "poisson", "integrate", "reconstruct"), output_format="r16f", gpu_kernel="normal_to_height_prepare.wgsl",
        input_kinds=(("Normal", "vector"),), output_kinds=(("Height", "grayscale"),), output_name="Height", default_image_kind="grayscale",
    ))
    registry.register(NodeDefinition(
        "normal.bent", "Bent Normal", category, eval_bent_normal,
        inputs=("Height",), parameters=_ray_parameters(include_normal_format=True),
        description="Trace hemisphere visibility through a height field and encode the average unoccluded direction as a bent normal.",
        accent=_NORMAL_ACCENT, tags=("bent normal", "normal", "height", "rtao", "ambient", "visibility"), gpu_kernel="bent_normal.wgsl",
        input_kinds=(("Height", "grayscale"),), output_kinds=(("Normal", "vector"),), output_name="Normal", default_image_kind="vector",
    ))
    registry.register(NodeDefinition(
        "filter.rt_shadows", "RT Shadows", category, eval_rt_shadows,
        inputs=("Height",),
        parameters=(
            f("height_scale", "Height Scale", "float", 1.0, 0.0, 10.0, 0.05, animatable=True),
            f("angle", "Light Angle", "float", 45.0, -3600.0, 3600.0, 0.1, animatable=True, editor="angle", unit="degrees", angle_wrap=True),
            f("elevation", "Light Elevation", "float", 35.0, 0.1, 89.9, 0.1, animatable=True, unit="degrees"),
            f("maximum_distance", "Maximum Distance", "float", 0.25, 0.0, 1.0, 0.01, animatable=True),
            f("softness", "Softness", "float", 0.15, 0.0, 1.0, 0.01, animatable=True),
            f("samples", "Samples", "int", 8, 1, 32, 1),
            f("bias", "Bias", "float", 0.001, 0.0, 0.05, 0.0001, animatable=True),
            f("strength", "Shadow Strength", "float", 1.0, 0.0, 1.0, 0.01, animatable=True),
            f("boundary", "Boundary", "enum", "Seamless / Wrap", options=("Seamless / Wrap", "Clamp")),
            f("invert", "Invert", "bool", False),
        ),
        description="Ray-march directional hard or soft shadows across a height field. White is lit and black is shadowed.",
        accent=_NORMAL_ACCENT, tags=("ray traced", "rt", "shadow", "height", "light", "directional"), output_format="r16f", gpu_kernel="rt_shadows.wgsl",
        input_kinds=(("Height", "grayscale"),), output_kinds=(("Shadow", "grayscale"),), output_name="Shadow", default_image_kind="grayscale",
    ))
