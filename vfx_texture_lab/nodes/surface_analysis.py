from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np

from .base import EvalContext, ImageArray, NodeDefinition, ParameterSpec
from .image_ops import ensure_rgba, grayscale_rgba, luminance, resolution_scale
from .registry import NodeRegistry

_SURFACE_ACCENT = "#5f91a8"
def _height(inputs: Mapping[str, ImageArray], context: EvalContext) -> np.ndarray:
    source = inputs.get("Height")
    if source is None:
        return np.zeros((context.height, context.width), dtype=np.float32)
    return np.clip(luminance(ensure_rgba(source, context)), 0.0, 1.0).astype(np.float32, copy=False)


def _normal_components(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    source = inputs.get("Normal")
    if source is None:
        normal = np.empty((context.height, context.width, 3), dtype=np.float32)
        normal[..., 0] = 0.0
        normal[..., 1] = 0.0
        normal[..., 2] = 1.0
    else:
        normal = ensure_rgba(source, context)[..., :3].astype(np.float32, copy=False) * 2.0 - 1.0
    if str(params.get("normal_format", "OpenGL (+Y)")) == "DirectX (-Y)":
        normal = normal.copy()
        normal[..., 1] *= -1.0
    length = np.sqrt(np.sum(normal * normal, axis=2))
    inv_length = np.where(length > 1e-8, 1.0 / length, 0.0).astype(np.float32)
    nx = normal[..., 0] * inv_length
    ny = normal[..., 1] * inv_length
    nz = normal[..., 2] * inv_length
    flat = length <= 1e-8
    if np.any(flat):
        nx = nx.copy(); ny = ny.copy(); nz = nz.copy()
        nx[flat] = 0.0; ny[flat] = 0.0; nz[flat] = 1.0
    return nx, ny, nz


def _signed_output(curvature: np.ndarray, intensity: float) -> ImageArray:
    value = np.clip(0.5 + 0.5 * curvature * float(intensity), 0.0, 1.0)
    # Keep truly flat regions mathematically neutral. This is important when the
    # result is fed directly into Overlay/Linear-Light material colour work.
    value = np.where(np.abs(curvature) <= 1e-10, np.float32(0.5), value)
    return grayscale_rgba(value.astype(np.float32, copy=False))


def _central_divergence(nx: np.ndarray, ny: np.ndarray, radius: int) -> np.ndarray:
    radius = max(int(radius), 1)
    dnx = np.roll(nx, -radius, axis=1) - np.roll(nx, radius, axis=1)
    dny = np.roll(ny, -radius, axis=0) - np.roll(ny, radius, axis=0)
    return ((dnx + dny) * 0.25).astype(np.float32)


def eval_normal_curvature(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    nx, ny, _nz = _normal_components(inputs, params, context)
    radius = max(int(round(resolution_scale(context))), 1)
    curvature = _central_divergence(nx, ny, radius)
    return _signed_output(curvature, float(params.get("intensity", 1.0)))


def eval_curvature_sobel(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    nx, ny, _nz = _normal_components(inputs, params, context)
    radius = max(int(round(resolution_scale(context))), 1)

    nx_ul = np.roll(np.roll(nx, radius, axis=0), radius, axis=1)
    nx_l = np.roll(nx, radius, axis=1)
    nx_dl = np.roll(np.roll(nx, -radius, axis=0), radius, axis=1)
    nx_ur = np.roll(np.roll(nx, radius, axis=0), -radius, axis=1)
    nx_r = np.roll(nx, -radius, axis=1)
    nx_dr = np.roll(np.roll(nx, -radius, axis=0), -radius, axis=1)
    dnx = (nx_ur + 2.0 * nx_r + nx_dr - nx_ul - 2.0 * nx_l - nx_dl) * 0.125

    ny_ul = np.roll(np.roll(ny, radius, axis=0), radius, axis=1)
    ny_u = np.roll(ny, radius, axis=0)
    ny_ur = np.roll(np.roll(ny, radius, axis=0), -radius, axis=1)
    ny_dl = np.roll(np.roll(ny, -radius, axis=0), radius, axis=1)
    ny_d = np.roll(ny, -radius, axis=0)
    ny_dr = np.roll(np.roll(ny, -radius, axis=0), -radius, axis=1)
    dny = (ny_dl + 2.0 * ny_d + ny_dr - ny_ul - 2.0 * ny_u - ny_ur) * 0.125

    curvature = (dnx + dny).astype(np.float32)
    # Sobel is deliberately the broader, harder edge detector. Its documented
    # 0..1 intensity range therefore spans the useful full contrast interval.
    return _signed_output(curvature, float(params.get("intensity", 0.5)) * 2.0)


def eval_curvature_smooth(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    nx, ny, _nz = _normal_components(inputs, params, context)
    scale = resolution_scale(context)
    radii = tuple(max(int(round(base * scale)), 1) for base in (1.0, 2.0, 4.0))
    curvature = (
        _central_divergence(nx, ny, radii[0]) * np.float32(0.50)
        + _central_divergence(nx, ny, radii[1]) * np.float32(0.30)
        + _central_divergence(nx, ny, radii[2]) * np.float32(0.20)
    )
    curvature *= np.float32(2.0)
    output = str(params.get("preview_output", "Curvature"))
    if output == "Convexity":
        values = np.clip(curvature, 0.0, 1.0)
    elif output == "Concavity":
        values = np.clip(-curvature, 0.0, 1.0)
    else:
        values = np.clip(0.5 + 0.5 * curvature, 0.0, 1.0)
        values = np.where(np.abs(curvature) <= 1e-10, np.float32(0.5), values)
    return grayscale_rgba(values.astype(np.float32, copy=False))


def _quality_count(value: Any) -> int:
    text = str(value)
    if text.startswith("16"):
        return 16
    if text.startswith("8"):
        return 8
    return 4


def _sample_height(height: np.ndarray, dy: int, dx: int, boundary: str) -> np.ndarray:
    if boundary == "Seamless / Wrap":
        return np.roll(height, shift=(-dy, -dx), axis=(0, 1))
    rows, cols = height.shape
    yy = np.clip(np.arange(rows, dtype=np.int32)[:, None] + int(dy), 0, rows - 1)
    xx = np.clip(np.arange(cols, dtype=np.int32)[None, :] + int(dx), 0, cols - 1)
    return height[yy, xx]


def _sample_height_bilinear(
    height: np.ndarray, dy: float, dx: float, boundary: str
) -> np.ndarray:
    """Sample one floating-point offset without constructing a full UV grid.

    HBAO uses rotated concentric sample rings. Bilinear taps keep those rings
    smooth and avoid the duplicated integer offsets that caused visible flower
    and spoke patterns around small height features.
    """

    x0 = math.floor(float(dx))
    y0 = math.floor(float(dy))
    tx = np.float32(float(dx) - x0)
    ty = np.float32(float(dy) - y0)
    top = _sample_height(height, y0, x0, boundary) * (np.float32(1.0) - tx)
    top += _sample_height(height, y0, x0 + 1, boundary) * tx
    bottom = _sample_height(height, y0 + 1, x0, boundary) * (np.float32(1.0) - tx)
    bottom += _sample_height(height, y0 + 1, x0 + 1, boundary) * tx
    return top * (np.float32(1.0) - ty) + bottom * ty


def _minmod(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Return a slope only when both one-sided differences agree.

    A normal centred difference crosses a hard height step and invents a very
    steep tangent on the neighbouring flat pixel. HBAO then sees the opposite
    direction as an artificial blocker, creating the black one-pixel contour
    reported around Tile Sampler shapes. Minmod preserves genuine smooth ramps
    while rejecting discontinuities and local extrema.
    """

    same_direction = a * b > np.float32(0.0)
    magnitude = np.minimum(np.abs(a), np.abs(b))
    return np.where(same_direction, np.sign(a) * magnitude, np.float32(0.0)).astype(
        np.float32, copy=False
    )


def _hbao_blur_sigma(radius_pixels: float, interactive: bool) -> float:
    # HBAO is a low-frequency visibility estimate. A small reconstruction blur
    # is therefore part of the filter rather than an optional cosmetic effect.
    # Tying it to the authored search radius keeps results visually consistent
    # across texture resolutions while the cap prevents very large radii from
    # turning into an expensive full-image Gaussian.
    sigma = float(np.clip(float(radius_pixels) * 0.065, 0.65, 6.0))
    if interactive:
        sigma = min(sigma, 2.25)
    return sigma


def _joint_bilateral_pass(
    values: np.ndarray,
    height: np.ndarray,
    sigma: float,
    height_sigma: float,
    *,
    axis: int,
    boundary: str,
) -> np.ndarray:
    """Denoise AO while keeping it on the correct side of height edges.

    Nine bilinear taps give broad Gaussian reconstruction without requiring a
    radius-sized loop. Height similarity stops dark ground occlusion bleeding
    onto the top of a raised shape, unlike a plain post Gaussian blur.
    """

    sigma = max(float(sigma), 0.01)
    height_sigma = max(float(height_sigma), 1e-4)
    spacing = max(sigma * 0.65, 0.75)
    denom = np.float32(2.0 * sigma * sigma)
    height_denom = np.float32(2.0 * height_sigma * height_sigma)
    result = np.zeros_like(values, dtype=np.float32)
    weight_sum = np.zeros_like(values, dtype=np.float32)
    for tap in range(-4, 5):
        offset = float(tap) * spacing
        dy = offset if axis == 0 else 0.0
        dx = offset if axis == 1 else 0.0
        sampled_value = _sample_height_bilinear(values, dy, dx, boundary)
        sampled_height = _sample_height_bilinear(height, dy, dx, boundary)
        spatial_weight = np.float32(math.exp(-(offset * offset) / float(denom)))
        delta_height = sampled_height - height
        range_weight = np.exp(-(delta_height * delta_height) / height_denom).astype(
            np.float32, copy=False
        )
        weight = range_weight * spatial_weight
        result += sampled_value * weight
        weight_sum += weight
    return result / np.maximum(weight_sum, np.float32(1e-8))


def _reconstruct_hbao(
    values: np.ndarray,
    height: np.ndarray,
    radius_pixels: float,
    depth: float,
    context: EvalContext,
    boundary: str,
) -> np.ndarray:
    sigma = _hbao_blur_sigma(radius_pixels, context.render_mode == "interactive")
    # A low range sigma treats a genuine cliff as a boundary but still permits
    # gradual height fields and bevels to share AO smoothly.
    height_sigma = float(np.clip(0.035 + max(depth, 0.0) * 0.025, 0.035, 0.065))
    horizontal = _joint_bilateral_pass(
        values, height, sigma, height_sigma, axis=1, boundary=boundary
    )
    return _joint_bilateral_pass(
        horizontal, height, sigma, height_sigma, axis=0, boundary=boundary
    )


def eval_ambient_occlusion_hbao(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    height = _height(inputs, context)
    depth = max(float(params.get("height_depth", 0.1)), 0.0)
    radius = np.clip(float(params.get("radius", 0.15)), 0.0, 1.0)
    contrast = max(float(params.get("contrast", 1.0)), 0.0)
    direction_count = _quality_count(params.get("quality", "8 Samples"))
    radial_steps = {4: 6, 8: 7, 16: 8}[direction_count]
    if context.render_mode == "interactive":
        direction_count = min(direction_count, 4)
        radial_steps = 3
    boundary = str(params.get("boundary", "Seamless / Wrap"))

    if depth <= 1e-8 or radius <= 1e-8:
        values = np.ones_like(height, dtype=np.float32)
    else:
        radius_pixels = max(radius * 0.5 * min(context.width, context.height), 1.0)
        left = _sample_height(height, 0, -1, boundary)
        right = _sample_height(height, 0, 1, boundary)
        up = _sample_height(height, -1, 0, boundary)
        down = _sample_height(height, 1, 0, boundary)
        grad_x = _minmod(height - left, right - height)
        grad_y = _minmod(height - up, down - height)

        occlusion = np.zeros_like(height, dtype=np.float32)
        weight_sum = np.float32(0.0)
        height_scale = np.float32(depth * 0.12)
        for ring in range(radial_steps):
            # Equal-area concentric rings give the whole search disc useful
            # coverage. Rotating each ring by the golden angle prevents the
            # same radial rays from being stamped around every height feature.
            ring_fraction = math.sqrt((ring + 0.5) / radial_steps)
            distance_pixels = max(radius_pixels * ring_fraction, 0.75)
            ring_rotation = ring * 2.399963229728653
            radial_weight = np.float32(max(1.0 - ring_fraction * ring_fraction, 0.0) ** 1.5 + 0.15)
            for direction_index in range(direction_count):
                angle = (
                    math.tau * (direction_index + 0.5) / direction_count
                    + ring_rotation
                )
                dx = math.cos(angle) * distance_pixels
                dy = math.sin(angle) * distance_pixels
                du = dx / max(context.width, 1)
                dv = dy / max(context.height, 1)
                distance_uv = max(math.hypot(du, dv), 1e-6)
                sample = _sample_height_bilinear(height, dy, dx, boundary)
                tangent_height = height + grad_x * np.float32(dx) + grad_y * np.float32(dy)
                delta = np.maximum(sample - tangent_height, 0.0)
                slope = delta * height_scale / np.float32(distance_uv + 0.002)
                angular_occlusion = np.arctan(slope) * np.float32(2.0 / math.pi)
                occlusion += angular_occlusion.astype(np.float32, copy=False) * radial_weight
                weight_sum += radial_weight

        mean_occlusion = occlusion / max(float(weight_sum), 1e-8)
        # Exponential transmittance gives dense clusters rich dark contact AO
        # without clipping the full Height Depth range after its midpoint.
        values = np.exp(-mean_occlusion * np.float32(contrast * 4.0))
        values = _reconstruct_hbao(
            values, height, radius_pixels, depth, context, boundary
        )

    if bool(params.get("invert", False)):
        values = 1.0 - values
    return grayscale_rgba(np.clip(values, 0.0, 1.0).astype(np.float32, copy=False))



def _sample_height_positions(
    height: np.ndarray,
    y_position: np.ndarray,
    x_position: np.ndarray,
    boundary: str,
) -> np.ndarray:
    """Bilinear height lookup for per-pixel ray positions.

    RTAO rotates its hemisphere independently at each output pixel to avoid
    repeating spokes. Unlike HBAO's shared offsets, each pixel therefore needs
    its own floating-point sample position.
    """

    rows, cols = height.shape
    x0 = np.floor(x_position).astype(np.int32)
    y0 = np.floor(y_position).astype(np.int32)
    tx = (x_position - x0).astype(np.float32, copy=False)
    ty = (y_position - y0).astype(np.float32, copy=False)
    x1 = x0 + 1
    y1 = y0 + 1
    if boundary == "Seamless / Wrap":
        x0 %= cols; x1 %= cols; y0 %= rows; y1 %= rows
    else:
        x0 = np.clip(x0, 0, cols - 1); x1 = np.clip(x1, 0, cols - 1)
        y0 = np.clip(y0, 0, rows - 1); y1 = np.clip(y1, 0, rows - 1)
    a = height[y0, x0]
    b = height[y0, x1]
    c = height[y1, x0]
    d = height[y1, x1]
    top = a + (b - a) * tx
    bottom = c + (d - c) * tx
    return (top + (bottom - top) * ty).astype(np.float32, copy=False)


def _rtao_rotation_field(width: int, height: int) -> np.ndarray:
    """Deterministic per-pixel hemisphere rotation shared with WGSL."""

    yy, xx = np.mgrid[0:height, 0:width]
    value = xx.astype(np.uint32) + yy.astype(np.uint32) * np.uint32(0x9E3779B9)
    value ^= value >> np.uint32(16)
    value *= np.uint32(0x7FEB352D)
    value ^= value >> np.uint32(15)
    value *= np.uint32(0x846CA68B)
    value ^= value >> np.uint32(16)
    return ((value & np.uint32(0x00FFFFFF)).astype(np.float32) / np.float32(16777216.0))


def _rtao_distribution_cosine(ray_fraction: float, spread: float, distribution: str) -> float:
    maximum_angle = float(np.clip(spread, 0.0, 1.0)) * (math.pi * 0.5)
    if maximum_angle <= 1e-8:
        return 1.0
    u = float(np.clip(ray_fraction, 0.0, 1.0))
    if distribution == "Cosine Weighted":
        cos_max = math.cos(maximum_angle)
        return math.sqrt(max(1.0 - u * (1.0 - cos_max * cos_max), 0.0))
    if distribution == "Horizon Weighted":
        return math.cos(maximum_angle * (u ** 0.45))
    cos_max = math.cos(maximum_angle)
    return 1.0 - u * (1.0 - cos_max)


def _rtao_step_count(samples: int, interactive: bool) -> int:
    if interactive:
        return 8
    if samples <= 8:
        return 10
    if samples <= 16:
        return 14
    if samples <= 32:
        return 18
    return 22


def _rtao_blur_sigma(maximum_distance_pixels: float, denoise: float, interactive: bool) -> float:
    if denoise <= 1e-8:
        return 0.0
    sigma = float(np.clip(0.55 + maximum_distance_pixels * 0.035 * denoise, 0.55, 5.0))
    if interactive:
        sigma = min(sigma, 2.0)
    return sigma


def _reconstruct_rtao(
    values: np.ndarray,
    height: np.ndarray,
    maximum_distance_pixels: float,
    height_scale: float,
    denoise: float,
    context: EvalContext,
    boundary: str,
) -> np.ndarray:
    sigma = _rtao_blur_sigma(
        maximum_distance_pixels, denoise, context.render_mode == "interactive"
    )
    if sigma <= 1e-8:
        return values
    height_sigma = float(np.clip(0.018 + 0.035 / (1.0 + max(height_scale, 0.0)), 0.018, 0.053))
    horizontal = _joint_bilateral_pass(
        values, height, sigma, height_sigma, axis=1, boundary=boundary
    )
    return _joint_bilateral_pass(
        horizontal, height, sigma, height_sigma, axis=0, boundary=boundary
    )


def eval_ambient_occlusion_rtao(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    """Trace a stochastic hemisphere through a 2.5-D height field.

    This is software ray tracing rather than hardware RT. Each ray marches over
    the height texture and tests whether the authored surface rises above the
    ray. A slope-limited local tangent prevents smooth ramps and hard top edges
    from self-occluding, while per-pixel hemisphere rotation trades structured
    spokes for noise that the height-aware reconstruction can remove cleanly.
    """

    height = _height(inputs, context)
    height_scale = max(float(params.get("height_scale", 1.0)), 0.0)
    maximum_distance = float(np.clip(params.get("maximum_distance", 0.15), 0.0, 1.0))
    spread = float(np.clip(params.get("spread_angle", 1.0), 0.0, 1.0))
    requested_samples = int(np.clip(int(params.get("samples", 16)), 4, 64))
    samples = min(requested_samples, 6) if context.render_mode == "interactive" else requested_samples
    steps = _rtao_step_count(samples, context.render_mode == "interactive")
    distribution = str(params.get("distribution", "Uniform"))
    boundary = str(params.get("boundary", "Seamless / Wrap"))
    denoise = float(np.clip(params.get("denoise", 0.75), 0.0, 1.0))

    if height_scale <= 1e-8 or maximum_distance <= 1e-8 or spread <= 1e-8:
        values = np.ones_like(height, dtype=np.float32)
    else:
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
        occlusion = np.zeros_like(height, dtype=np.float32)
        golden_ratio = 0.6180339887498949
        origin_bias = np.float32(0.00025 + height_scale * 0.0005)

        for ray_index in range(samples):
            ray_fraction = (ray_index + 0.5) / samples
            cosine = float(np.clip(
                _rtao_distribution_cosine(ray_fraction, spread, distribution),
                0.0, 1.0,
            ))
            sine = math.sqrt(max(1.0 - cosine * cosine, 0.0))
            if sine <= 1e-7:
                continue
            cotangent = np.float32(cosine / max(sine, 1e-6))
            angle = (rotation + np.float32(ray_index * golden_ratio)) % np.float32(1.0)
            angle *= np.float32(math.tau)
            direction_x = np.cos(angle).astype(np.float32, copy=False)
            direction_y = np.sin(angle).astype(np.float32, copy=False)
            first_hit = np.zeros_like(height, dtype=bool)
            hit_fraction = np.ones_like(height, dtype=np.float32)

            for step_index in range(steps):
                fraction = ((step_index + 1.0) / steps) ** 1.35
                distance_pixels = np.float32(maximum_distance_pixels * fraction)
                offset_x = direction_x * distance_pixels
                offset_y = direction_y * distance_pixels
                sample = _sample_height_positions(
                    height, base_y + offset_y, base_x + offset_x, boundary
                )
                tangent_height = height + grad_x * offset_x + grad_y * offset_y
                relative_surface = (sample - tangent_height) * np.float32(height_scale)
                ray_height = np.float32((distance_pixels / minimum_dimension)) * cotangent
                newly_hit = (~first_hit) & (relative_surface > ray_height + origin_bias)
                hit_fraction[newly_hit] = np.float32(fraction)
                first_hit |= newly_hit
                if bool(np.all(first_hit)):
                    break

            # Visibility is binary for each hemisphere ray, while a gentle
            # distance term stops blockers exactly at Maximum Distance from
            # creating a hard cutoff in the final field.
            contribution = np.where(
                first_hit,
                np.float32(1.0) - np.float32(0.35) * hit_fraction,
                np.float32(0.0),
            )
            occlusion += contribution.astype(np.float32, copy=False)

        values = np.float32(1.0) - occlusion / np.float32(max(samples, 1))
        values = _reconstruct_rtao(
            values,
            height,
            maximum_distance_pixels,
            height_scale,
            denoise,
            context,
            boundary,
        )

    if bool(params.get("invert", False)):
        values = np.float32(1.0) - values
    return grayscale_rgba(np.clip(values, 0.0, 1.0).astype(np.float32, copy=False))

def register_surface_analysis_nodes(registry: NodeRegistry) -> None:
    f = ParameterSpec
    normal_format = (
        f(
            "normal_format",
            "Normal Format",
            "enum",
            "OpenGL (+Y)",
            options=("OpenGL (+Y)", "DirectX (-Y)"),
            description="Choose the green/Y convention used by the input tangent-space normal map.",
        ),
    )
    registry.register(
        NodeDefinition(
            "filter.curvature",
            "Curvature",
            "Filters/Surface Analysis",
            eval_normal_curvature,
            inputs=("Normal",),
            parameters=(
                f("intensity", "Intensity", "float", 1.0, 0.0, 10.0, 0.05, animatable=True),
                *normal_format,
            ),
            description="Extract sharp pixel-thin convex and concave detail from a tangent-space normal map. Flat areas are exactly 50% grey.",
            accent=_SURFACE_ACCENT,
            tags=("curvature", "normal", "convex", "concave", "edge", "overlay"),
            output_format="r16f",
            gpu_kernel="curvature_normal.wgsl",
            input_kinds=(("Normal", "vector"),),
            output_kinds=(("Image", "grayscale"),),
            default_image_kind="grayscale",
        )
    )
    registry.register(
        NodeDefinition(
            "filter.curvature_sobel",
            "Curvature Sobel",
            "Filters/Surface Analysis",
            eval_curvature_sobel,
            inputs=("Normal",),
            parameters=(
                f("intensity", "Intensity", "float", 1.0, 0.0, 1.0, 0.01, animatable=True),
                *normal_format,
            ),
            description="Apply a broad, hard Sobel curvature pass to a normal map for stylised highlights and edge darkening. Flat areas are exactly 50% grey.",
            accent=_SURFACE_ACCENT,
            tags=("curvature", "sobel", "normal", "stylized", "stylised", "edge", "overlay"),
            output_format="r16f",
            gpu_kernel="curvature_sobel.wgsl",
            input_kinds=(("Normal", "vector"),),
            output_kinds=(("Image", "grayscale"),),
            default_image_kind="grayscale",
        )
    )
    registry.register(
        NodeDefinition(
            "filter.curvature_smooth",
            "Curvature Smooth",
            "Filters/Surface Analysis",
            eval_curvature_smooth,
            inputs=("Normal",),
            parameters=normal_format,
            description="Build a smoother multi-scale normal-derived curvature field with separate convexity and concavity masks.",
            accent=_SURFACE_ACCENT,
            tags=("curvature", "smooth", "normal", "convexity", "concavity", "mask"),
            output_format="r16f",
            outputs=("Curvature", "Convexity", "Concavity"),
            output_name="Curvature",
            named_output_parameter="preview_output",
            named_output_values=(
                ("Curvature", "Curvature"),
                ("Convexity", "Convexity"),
                ("Concavity", "Concavity"),
            ),
            gpu_kernel="curvature_smooth.wgsl",
            input_kinds=(("Normal", "vector"),),
            output_kinds=(
                ("Curvature", "grayscale"),
                ("Convexity", "grayscale"),
                ("Concavity", "grayscale"),
            ),
            default_image_kind="grayscale",
        )
    )
    registry.register(
        NodeDefinition(
            "filter.ambient_occlusion_hbao",
            "Ambient Occlusion (HBAO)",
            "Filters/Surface Analysis",
            eval_ambient_occlusion_hbao,
            inputs=("Height",),
            parameters=(
                f(
                    "height_depth", "Height Depth", "float", 0.10, 0.0, 1.0, 0.01,
                    animatable=True,
                    description="Global vertical scale used when comparing the height field against its local tangent plane.",
                ),
                f(
                    "radius", "Radius", "float", 0.15, 0.0, 1.0, 0.01,
                    animatable=True,
                    description="Maximum horizon-search distance as a proportion of the texture.",
                ),
                f(
                    "quality", "Quality", "enum", "8 Samples",
                    options=("4 Samples", "8 Samples", "16 Samples"),
                    description="Number of horizon directions. Interactive drags temporarily use the four-sample draft path.",
                ),
                f("contrast", "Occlusion Strength", "float", 1.0, 0.0, 4.0, 0.05, animatable=True),
                f(
                    "boundary", "Boundary", "enum", "Seamless / Wrap",
                    options=("Seamless / Wrap", "Clamp"),
                    description="Wrap for tileable materials or clamp samples to the image edge.",
                ),
                f("invert", "Invert", "bool", False),
            ),
            description="Generate a fast horizon-based ambient-occlusion map from height without ray tracing. White is unoccluded and dark values mark blocked surface regions.",
            accent=_SURFACE_ACCENT,
            tags=("ambient occlusion", "ao", "hbao", "height", "horizon", "shadow", "mask"),
            output_format="r16f",
            gpu_kernel="ambient_occlusion_hbao.wgsl",
            input_kinds=(("Height", "grayscale"),),
            output_kinds=(("Image", "grayscale"),),
            default_image_kind="grayscale",
        )
    )

    registry.register(
        NodeDefinition(
            "filter.ambient_occlusion_rtao",
            "Ambient Occlusion (RTAO)",
            "Filters/Surface Analysis",
            eval_ambient_occlusion_rtao,
            inputs=("Height",),
            parameters=(
                f(
                    "height_scale", "Height Scale", "float", 1.0, 0.0, 10.0, 0.05,
                    animatable=True,
                    description="Multiplier converting the grayscale height field into vertical surface relief.",
                ),
                f(
                    "samples", "Samples", "int", 16, 4, 64, 4,
                    description="Number of hemisphere rays per pixel. More rays are smoother and substantially more expensive.",
                ),
                f(
                    "distribution", "Distribution", "enum", "Uniform",
                    options=("Uniform", "Cosine Weighted", "Horizon Weighted"),
                    description="Choose how rays are distributed between the surface normal and the horizon.",
                ),
                f(
                    "maximum_distance", "Maximum Distance", "float", 0.15, 0.0, 1.0, 0.01,
                    animatable=True,
                    description="Maximum horizontal ray travel as a proportion of the texture's shorter dimension.",
                ),
                f(
                    "spread_angle", "Spread Angle", "float", 1.0, 0.0, 1.0, 0.01,
                    animatable=True,
                    description="Hemisphere opening angle. One traces the complete upper hemisphere.",
                ),
                f(
                    "denoise", "Denoise", "float", 0.75, 0.0, 1.0, 0.01,
                    description="Height-aware reconstruction strength used to remove stochastic ray noise without crossing height edges.",
                ),
                f(
                    "boundary", "Boundary", "enum", "Seamless / Wrap",
                    options=("Seamless / Wrap", "Clamp"),
                    description="Wrap for tileable materials or clamp rays to the image edge.",
                ),
                f("invert", "Invert", "bool", False),
            ),
            description="Generate accurate ray-traced ambient occlusion from a height map using GPU software ray marching. High sample counts are intended for final-quality evaluation.",
            accent=_SURFACE_ACCENT,
            tags=("ambient occlusion", "ao", "rtao", "ray traced", "height", "shadow", "mask"),
            output_format="r16f",
            gpu_kernel="ambient_occlusion_rtao.wgsl",
            input_kinds=(("Height", "grayscale"),),
            output_kinds=(("Image", "grayscale"),),
            default_image_kind="grayscale",
        )
    )
