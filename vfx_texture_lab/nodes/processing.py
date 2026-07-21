from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Mapping

import numpy as np
from PIL import Image, ImageFilter

from .base import EvalContext, ImageArray, NodeDefinition, ParameterSpec
from .image_ops import empty_image, ensure_rgba, grayscale_rgba, linear_to_srgb, luminance, parse_hex_color, relative_pixels, resolution_scale, srgb_to_linear
from ..flipbook import flipbook_frame_selection, flipbook_grid
from ..material import SURFACE_MODES
from .registry import NodeRegistry
from .resampling import BOUNDARY_OPTIONS, FILTERING_OPTIONS, affine_pixel_footprint, boundary_name, estimate_coordinate_footprint, sample_image


def _input(inputs: Mapping[str, ImageArray], name: str, context: EvalContext, value: float = 0.0) -> ImageArray:
    return ensure_rgba(inputs.get(name, empty_image(context, value=value)), context)


def eval_invert(inputs: Mapping[str, ImageArray], _params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    result = image.copy()
    result[..., :3] = 1.0 - result[..., :3]
    return result


def _levels_curve(values: np.ndarray, in_low: float, in_high: float, in_mid: float, clamp_intermediate: bool) -> np.ndarray:
    """Apply Substance-style input Levels mapping to normalized values.

    ``in_mid`` is a normalized midpoint inside the selected input range. A
    value of 0.5 is neutral; moving it changes which relative input tone maps
    to middle grey without changing the low/high endpoints.

    Passthrough mode preserves values outside the input range with a linear
    extension. That keeps float pipelines finite while allowing values below 0
    or above 1 to survive the intermediary stage.
    """
    span = max(float(in_high) - float(in_low), 1e-6)
    normalized = (values - float(in_low)) / span
    mid_normalized = np.clip(float(in_mid), 1e-5, 1.0 - 1e-5)
    exponent = np.log(0.5) / np.log(mid_normalized)

    if clamp_intermediate:
        normalized = np.clip(normalized, 0.0, 1.0)
        return np.power(normalized, exponent)

    inside = np.clip(normalized, 0.0, 1.0)
    curved = np.power(inside, exponent)
    return np.where(normalized < 0.0, normalized, np.where(normalized > 1.0, normalized, curved))


def eval_levels(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    in_low = float(params.get("in_low", params.get("black", 0.0)))
    in_high = float(params.get("in_high", params.get("white", 1.0)))
    in_mid = float(params.get("in_mid", 0.5))
    out_low = float(params.get("out_low", 0.0))
    out_high = float(params.get("out_high", 1.0))
    clamp_intermediate = bool(params.get("intermediary_clamp", True))

    # Keep the input handles ordered. Inversion belongs to the output handles,
    # matching the quick Invert action used by Substance Designer.
    in_high = max(in_high, in_low + 1e-6)
    in_mid = min(max(in_mid, 1e-5), 1.0 - 1e-5)

    result = image.copy()
    shaped = _levels_curve(result[..., :3], in_low, in_high, in_mid, clamp_intermediate)
    result[..., :3] = out_low + shaped * (out_high - out_low)
    return np.nan_to_num(result, nan=0.0, posinf=1.0, neginf=0.0).astype(np.float32)


def eval_threshold(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    value = luminance(_input(inputs, "Image", context))
    threshold = float(params["threshold"])
    softness = float(params["softness"])
    if softness <= 1e-5:
        output = (value >= threshold).astype(np.float32)
    else:
        output = np.clip((value - threshold) / softness + 0.5, 0.0, 1.0)
        output = output * output * (3.0 - 2.0 * output)
    return grayscale_rgba(output)


def eval_histogram_range(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    """Compress a greyscale input into a movable output range.

    Range 1 is identity.  As Range approaches zero the output collapses to
    Position, while Position moves any unused range between black and white.
    """
    values = np.clip(luminance(_input(inputs, "Image", context)), 0.0, 1.0)
    amount = np.clip(float(params.get("range", 1.0)), 0.0, 1.0)
    position = np.clip(float(params.get("position", 0.5)), 0.0, 1.0)
    low = (1.0 - amount) * position
    return grayscale_rgba(low + values * amount)


def eval_histogram_shift(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    """Circularly shift greyscale values through the 0-1 range."""
    values = np.clip(luminance(_input(inputs, "Image", context)), 0.0, 1.0)
    position = float(params.get("position", 0.0)) % 1.0
    if position <= 1e-8:
        shifted = values
    else:
        shifted = np.mod(values + position, 1.0)
    return grayscale_rgba(shifted)


def eval_histogram_scan(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    """Grow/shrink a mask using Substance-style Position and Contrast."""
    values = np.clip(luminance(_input(inputs, "Image", context)), 0.0, 1.0)
    position = np.clip(float(params.get("position", 0.5)), 0.0, 1.0)
    contrast = np.clip(float(params.get("contrast", 0.5)), 0.0, 1.0)
    edge0 = 1.0 - position
    width = max(1.0 - contrast, 1e-6)
    t = np.clip((values - edge0) / width, 0.0, 1.0)
    output = t * t * (3.0 - 2.0 * t)
    return grayscale_rgba(output)


def eval_histogram_select(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    """Select a soft value band around Position.

    Range describes the full selected width. Contrast tightens the transition
    without moving its centre, which makes the node useful for isolating height
    strata and narrow tonal regions.
    """
    values = np.clip(luminance(_input(inputs, "Image", context)), 0.0, 1.0)
    position = np.clip(float(params.get("position", 0.5)), 0.0, 1.0)
    selected_range = np.clip(float(params.get("range", 0.25)), 0.0, 1.0)
    contrast = np.clip(float(params.get("contrast", 0.5)), 0.0, 1.0)
    half_range = selected_range * 0.5
    # At zero contrast the falloff can span half the value domain. At full
    # contrast only a numerically stable one-value transition remains.
    softness = max((1.0 - contrast) * 0.5, 1.0e-6)
    distance = np.abs(values - position)
    inner = max(half_range - softness * 0.5, 0.0)
    outer = half_range + softness * 0.5
    t = np.clip((distance - inner) / max(outer - inner, 1.0e-6), 0.0, 1.0)
    falloff = t * t * (3.0 - 2.0 * t)
    return grayscale_rgba(1.0 - falloff)


def _preserve_alpha(image: ImageArray, rgb: np.ndarray) -> ImageArray:
    result = image.copy()
    result[..., :3] = np.asarray(rgb, dtype=np.float32)
    return np.nan_to_num(result, nan=0.0, posinf=1.0, neginf=0.0).astype(np.float32)


def eval_brightness(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    return _preserve_alpha(image, image[..., :3] + float(params.get("brightness", 0.0)))


def eval_contrast(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    amount = np.clip(float(params.get("contrast", 0.0)), -1.0, 1.0)
    pivot = float(params.get("pivot", 0.5))
    factor = float(2.0 ** (amount * 3.0))
    return _preserve_alpha(image, (image[..., :3] - pivot) * factor + pivot)


def eval_exposure(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    multiplier = float(2.0 ** float(params.get("exposure", 0.0)))
    return _preserve_alpha(image, image[..., :3] * multiplier)


def eval_gamma(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    gamma = max(float(params.get("gamma", 1.0)), 1e-5)
    return _preserve_alpha(image, np.power(np.maximum(image[..., :3], 0.0), 1.0 / gamma))


def eval_posterize(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    steps = max(int(params.get("steps", 8)), 2)
    scale = float(steps - 1)
    rgb = np.rint(np.clip(image[..., :3], 0.0, 1.0) * scale) / scale
    return _preserve_alpha(image, rgb)


def eval_image_clamp(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    a = float(params.get("minimum", 0.0))
    b = float(params.get("maximum", 1.0))
    low, high = (a, b) if a <= b else (b, a)
    return _preserve_alpha(image, np.clip(image[..., :3], low, high))


def _rgb_to_hsl(rgb: np.ndarray) -> np.ndarray:
    rgb = np.clip(np.asarray(rgb, dtype=np.float32), 0.0, 1.0)
    maximum = np.max(rgb, axis=2)
    minimum = np.min(rgb, axis=2)
    delta = maximum - minimum
    lightness = (maximum + minimum) * 0.5
    denominator = 1.0 - np.abs(2.0 * lightness - 1.0)
    saturation = np.where(delta > 1e-7, delta / np.maximum(denominator, 1e-7), 0.0)

    hue = np.zeros_like(maximum)
    mask = delta > 1e-7
    red = mask & (maximum == rgb[..., 0])
    green = mask & (maximum == rgb[..., 1])
    blue = mask & (maximum == rgb[..., 2])
    hue[red] = np.mod((rgb[..., 1][red] - rgb[..., 2][red]) / delta[red], 6.0)
    hue[green] = ((rgb[..., 2][green] - rgb[..., 0][green]) / delta[green]) + 2.0
    hue[blue] = ((rgb[..., 0][blue] - rgb[..., 1][blue]) / delta[blue]) + 4.0
    hue = np.mod(hue / 6.0, 1.0)
    return np.stack((hue, np.clip(saturation, 0.0, 1.0), np.clip(lightness, 0.0, 1.0)), axis=2)


def _hsl_to_rgb(hsl: np.ndarray) -> np.ndarray:
    hsl = np.asarray(hsl, dtype=np.float32)
    hue = np.mod(hsl[..., 0], 1.0)
    saturation = np.clip(hsl[..., 1], 0.0, 1.0)
    lightness = np.clip(hsl[..., 2], 0.0, 1.0)
    chroma = (1.0 - np.abs(2.0 * lightness - 1.0)) * saturation
    h6 = hue * 6.0
    x = chroma * (1.0 - np.abs(np.mod(h6, 2.0) - 1.0))
    zero = np.zeros_like(chroma)
    sector = np.floor(h6).astype(np.int32) % 6
    r = np.select((sector == 0, sector == 1, sector == 2, sector == 3, sector == 4, sector == 5), (chroma, x, zero, zero, x, chroma), default=zero)
    g = np.select((sector == 0, sector == 1, sector == 2, sector == 3, sector == 4, sector == 5), (x, chroma, chroma, x, zero, zero), default=zero)
    b = np.select((sector == 0, sector == 1, sector == 2, sector == 3, sector == 4, sector == 5), (zero, zero, x, chroma, chroma, x), default=zero)
    match = lightness - chroma * 0.5
    return np.stack((r + match, g + match, b + match), axis=2).astype(np.float32)


def eval_hue_shift(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Colour", context)
    hsl = _rgb_to_hsl(image[..., :3])
    hsl[..., 0] = np.mod(hsl[..., 0] + float(params.get("degrees", 0.0)) / 360.0, 1.0)
    return _preserve_alpha(image, _hsl_to_rgb(hsl))


def eval_saturation(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Colour", context)
    hsl = _rgb_to_hsl(image[..., :3])
    hsl[..., 1] = np.clip(hsl[..., 1] * float(params.get("saturation", 1.0)), 0.0, 1.0)
    return _preserve_alpha(image, _hsl_to_rgb(hsl))


def eval_lightness(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Colour", context)
    hsl = _rgb_to_hsl(image[..., :3])
    hsl[..., 2] = np.clip(hsl[..., 2] + float(params.get("lightness", 0.0)), 0.0, 1.0)
    return _preserve_alpha(image, _hsl_to_rgb(hsl))


def _normalise_curve_points(raw: Any) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    if isinstance(raw, list):
        for item in raw[:8]:
            if not isinstance(item, Mapping):
                continue
            try:
                points.append((np.clip(float(item.get("x", 0.0)), 0.0, 1.0), np.clip(float(item.get("y", 0.0)), 0.0, 1.0)))
            except (TypeError, ValueError):
                pass
    if len(points) < 2:
        points = [(0.0, 0.0), (1.0, 1.0)]
    points.sort(key=lambda point: point[0])
    # Duplicate X positions make a response curve ambiguous; retain the last.
    deduplicated: list[tuple[float, float]] = []
    for point in points:
        if deduplicated and abs(point[0] - deduplicated[-1][0]) < 1e-6:
            deduplicated[-1] = point
        else:
            deduplicated.append(point)
    return deduplicated if len(deduplicated) >= 2 else [(0.0, 0.0), (1.0, 1.0)]


def eval_image_curve(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    points = _normalise_curve_points(params.get("points"))
    values = np.clip(image[..., :3], 0.0, 1.0)
    output = np.full_like(values, points[0][1])
    smooth = str(params.get("interpolation", "Smooth")) == "Smooth"
    output[values >= points[-1][0]] = points[-1][1]
    for index in range(len(points) - 1):
        x0, y0 = points[index]
        x1, y1 = points[index + 1]
        mask = (values >= x0) & (values <= x1)
        t = np.clip((values - x0) / max(x1 - x0, 1e-6), 0.0, 1.0)
        if smooth:
            previous = points[max(index - 1, 0)]
            following = points[min(index + 2, len(points) - 1)]
            slope0 = (y1 - previous[1]) / max(x1 - previous[0], 1e-6)
            slope1 = (following[1] - y0) / max(following[0] - x0, 1e-6)
            t2 = t * t
            t3 = t2 * t
            h00 = 2.0 * t3 - 3.0 * t2 + 1.0
            h10 = t3 - 2.0 * t2 + t
            h01 = -2.0 * t3 + 3.0 * t2
            h11 = t3 - t2
            segment = h00 * y0 + h10 * (x1 - x0) * slope0 + h01 * y1 + h11 * (x1 - x0) * slope1
        else:
            segment = y0 + (y1 - y0) * t
        output = np.where(mask, np.clip(segment, 0.0, 1.0), output)
    return _preserve_alpha(image, output)


def _to_pillow_rgba(image: ImageArray) -> Image.Image:
    data = (np.clip(image, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    return Image.fromarray(data, mode="RGBA")


def eval_blur(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    radius = relative_pixels(float(params["radius"]), context)
    if radius <= 0.01:
        return image.copy()

    # Pillow does not expose the boundary rule directly. Pad explicitly, blur
    # the padded image, then crop back so tileable textures can wrap while
    # photographs can clamp without borrowing detail from the opposite edge.
    padding = max(1, int(math.ceil(radius * 3.0)))
    boundary = str(params.get("boundary", "Seamless / Wrap"))
    pad_mode = "wrap" if boundary == "Seamless / Wrap" else "edge"
    padded = np.pad(image, ((padding, padding), (padding, padding), (0, 0)), mode=pad_mode)
    blurred = _to_pillow_rgba(padded).filter(ImageFilter.GaussianBlur(radius=radius))
    result = np.asarray(blurred, dtype=np.float32) / 255.0
    return result[padding : padding + context.height, padding : padding + context.width].copy()




def eval_highpass(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    """Extract detail above the authored Gaussian radius around neutral grey."""
    image = _input(inputs, "Image", context)
    radius = max(float(params.get("radius", 16.0)), 0.0)
    if radius <= 0.001:
        result = np.full_like(image, 0.5, dtype=np.float32)
        result[..., 3] = image[..., 3]
        return result

    resolved_kind = str(params.get("_resolved_kind", "grayscale"))
    working = image.copy()
    if resolved_kind == "color":
        working[..., :3] = linear_to_srgb(np.clip(working[..., :3], 0.0, 1.0))
    blurred = eval_blur(
        {"Image": working},
        {"radius": radius, "boundary": str(params.get("boundary", "Clamp"))},
        context,
    )
    detail = np.clip(working[..., :3] - blurred[..., :3] + 0.5, 0.0, 1.0)
    if resolved_kind == "color":
        detail = srgb_to_linear(detail)
    result = image.copy()
    result[..., :3] = detail
    return result.astype(np.float32, copy=False)


def _sample_clamp_bilinear(image: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    sample_x = np.clip(x, 0.0, max(width - 1.0, 0.0))
    sample_y = np.clip(y, 0.0, max(height - 1.0, 0.0))
    x0 = np.floor(sample_x).astype(np.int32)
    y0 = np.floor(sample_y).astype(np.int32)
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    tx = (sample_x - x0).astype(np.float32)
    ty = (sample_y - y0).astype(np.float32)
    a = image[y0, x0]
    b = image[y0, x1]
    c = image[y1, x0]
    d = image[y1, x1]
    if image.ndim == 2:
        return ((a * (1.0 - tx) + b * tx) * (1.0 - ty) + (c * (1.0 - tx) + d * tx) * ty).astype(np.float32)
    tx3 = tx[..., None]
    ty3 = ty[..., None]
    return ((a * (1.0 - tx3) + b * tx3) * (1.0 - ty3) + (c * (1.0 - tx3) + d * tx3) * ty3).astype(np.float32)


def _sample_clamp_nearest(image: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    sx = np.clip(np.rint(x).astype(np.int32), 0, width - 1)
    sy = np.clip(np.rint(y).astype(np.int32), 0, height - 1)
    return image[sy, sx].copy()


def eval_edge_detect(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    kind = str(params.get("_resolved_kind", "grayscale"))
    if kind == "color":
        working = linear_to_srgb(np.clip(image[..., :3], 0.0, 1.0))
        values: np.ndarray = (
            working[..., 0] * np.float32(0.2126)
            + working[..., 1] * np.float32(0.7152)
            + working[..., 2] * np.float32(0.0722)
        )
    elif kind == "vector":
        normal = image[..., :3] * 2.0 - 1.0
        length = np.linalg.norm(normal, axis=2, keepdims=True)
        values = normal / np.maximum(length, 1.0e-6)
    else:
        values = luminance(image)
    radius = float(max(int(round(relative_pixels(float(params.get("width", 1.0)), context))), 1))
    grid_x, grid_y = _pixel_grids(context)
    tl = _sample_clamp_bilinear(values, grid_x - radius, grid_y - radius)
    tc = _sample_clamp_bilinear(values, grid_x, grid_y - radius)
    tr = _sample_clamp_bilinear(values, grid_x + radius, grid_y - radius)
    ml = _sample_clamp_bilinear(values, grid_x - radius, grid_y)
    mr = _sample_clamp_bilinear(values, grid_x + radius, grid_y)
    bl = _sample_clamp_bilinear(values, grid_x - radius, grid_y + radius)
    bc = _sample_clamp_bilinear(values, grid_x, grid_y + radius)
    br = _sample_clamp_bilinear(values, grid_x + radius, grid_y + radius)
    if str(params.get("method", "Scharr")) == "Sobel":
        side, centre = 1.0, 2.0
        normaliser = 4.0
    else:
        side, centre = 3.0, 10.0
        normaliser = 16.0
    gx = (-side * tl - centre * ml - side * bl + side * tr + centre * mr + side * br) / normaliser
    gy = (-side * tl - centre * tc - side * tr + side * bl + centre * bc + side * br) / normaliser
    if kind == "vector":
        magnitude = np.sqrt(np.sum(gx * gx + gy * gy, axis=2)) * 0.5
    else:
        magnitude = np.sqrt(gx * gx + gy * gy)
    magnitude *= max(float(params.get("intensity", 1.0)), 0.0)
    output = np.clip(magnitude, 0.0, 1.0)
    if bool(params.get("invert", False)):
        output = 1.0 - output
    return grayscale_rgba(output)


def eval_fxaa(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    """Apply an FXAA-style edge search in the image's perceptual working space.

    Colour images are inspected and filtered in display-sRGB, scalar images
    retain their raw values, and vector/normal images are decoded before
    filtering and renormalised afterwards. The implementation follows the
    classic FXAA directional search: diagonal luminance gradients establish an
    edge direction, fractional taps span that edge, and the wider estimate is
    rejected when it would cross outside the local luminance range.
    """
    image = _input(inputs, "Image", context)
    kind = str(params.get("_resolved_kind", "grayscale"))
    working = image.copy()
    if kind == "color":
        working[..., :3] = linear_to_srgb(np.clip(working[..., :3], 0.0, 1.0))
    elif kind == "vector":
        decoded = working[..., :3] * 2.0 - 1.0
        length = np.linalg.norm(decoded, axis=2, keepdims=True)
        working[..., :3] = decoded / np.maximum(length, 1.0e-6)

    def working_luma(samples: np.ndarray) -> np.ndarray:
        if kind == "vector":
            return np.clip(samples[..., 2] * 0.5 + 0.5, 0.0, 1.0)
        return (
            samples[..., 0] * np.float32(0.2126)
            + samples[..., 1] * np.float32(0.7152)
            + samples[..., 2] * np.float32(0.0722)
        ).astype(np.float32, copy=False)

    grid_x, grid_y = _pixel_grids(context)
    centre = working_luma(working)
    nw = working_luma(_sample_clamp_bilinear(working, grid_x - 1.0, grid_y - 1.0))
    ne = working_luma(_sample_clamp_bilinear(working, grid_x + 1.0, grid_y - 1.0))
    sw = working_luma(_sample_clamp_bilinear(working, grid_x - 1.0, grid_y + 1.0))
    se = working_luma(_sample_clamp_bilinear(working, grid_x + 1.0, grid_y + 1.0))
    north = working_luma(_sample_clamp_bilinear(working, grid_x, grid_y - 1.0))
    south = working_luma(_sample_clamp_bilinear(working, grid_x, grid_y + 1.0))
    west = working_luma(_sample_clamp_bilinear(working, grid_x - 1.0, grid_y))
    east = working_luma(_sample_clamp_bilinear(working, grid_x + 1.0, grid_y))

    local_min = np.minimum.reduce((centre, north, south, west, east, nw, ne, sw, se))
    local_max = np.maximum.reduce((centre, north, south, west, east, nw, ne, sw, se))
    contrast = local_max - local_min
    threshold = max(float(params.get("edge_threshold", 0.0312)), 0.0)
    relative_threshold = max(float(params.get("relative_threshold", 0.125)), 0.0)
    active = contrast >= np.maximum(threshold, local_max * relative_threshold)

    direction_x = -((nw + ne) - (sw + se))
    direction_y = (nw + sw) - (ne + se)
    diagonal_average = (nw + ne + sw + se) * np.float32(0.25)
    quality = str(params.get("quality", "Medium"))
    if quality == "High":
        span, reduce_mul, reduce_min = 12.0, 1.0 / 8.0, 1.0 / 128.0
    elif quality == "Low":
        span, reduce_mul, reduce_min = 4.0, 1.0 / 4.0, 1.0 / 64.0
    else:
        span, reduce_mul, reduce_min = 8.0, 1.0 / 8.0, 1.0 / 128.0
    direction_reduce = np.maximum(diagonal_average * np.float32(reduce_mul), np.float32(reduce_min))
    reciprocal_min = 1.0 / (np.minimum(np.abs(direction_x), np.abs(direction_y)) + direction_reduce)
    direction_x = np.clip(direction_x * reciprocal_min, -span, span)
    direction_y = np.clip(direction_y * reciprocal_min, -span, span)

    sample_a = _sample_clamp_bilinear(
        working, grid_x + direction_x * (1.0 / 3.0 - 0.5), grid_y + direction_y * (1.0 / 3.0 - 0.5)
    )
    sample_b = _sample_clamp_bilinear(
        working, grid_x + direction_x * (2.0 / 3.0 - 0.5), grid_y + direction_y * (2.0 / 3.0 - 0.5)
    )
    narrow = (sample_a + sample_b) * np.float32(0.5)
    if quality == "Low":
        candidate = narrow
    else:
        outer_a = _sample_clamp_bilinear(working, grid_x - direction_x * 0.5, grid_y - direction_y * 0.5)
        outer_b = _sample_clamp_bilinear(working, grid_x + direction_x * 0.5, grid_y + direction_y * 0.5)
        wide = narrow * np.float32(0.5) + (outer_a + outer_b) * np.float32(0.25)
        wide_luma = working_luma(wide)
        candidate = np.where(((wide_luma < local_min) | (wide_luma > local_max))[..., None], narrow, wide)

    subpixel = np.clip(float(params.get("subpixel", 0.75)), 0.0, 1.0)
    edge_strength = np.clip(contrast / np.maximum(local_max, 1.0e-6), 0.0, 1.0)
    blend = np.where(active, edge_strength * subpixel, 0.0)[..., None]
    result = working * (1.0 - blend) + candidate * blend

    if kind == "vector":
        normal = result[..., :3]
        length = np.linalg.norm(normal, axis=2, keepdims=True)
        result[..., :3] = normal / np.maximum(length, 1.0e-6) * 0.5 + 0.5
    elif kind == "color":
        result[..., :3] = srgb_to_linear(np.clip(result[..., :3], 0.0, 1.0))
    if bool(params.get("preserve_alpha", True)):
        result[..., 3] = image[..., 3]
    return np.clip(result, 0.0, 1.0).astype(np.float32)


def _crop_coordinates(
    context: EvalContext,
    left: float,
    top: float,
    right: float,
    bottom: float,
) -> tuple[np.ndarray, np.ndarray]:
    grid_x, grid_y = _pixel_grids(context)
    u = (grid_x + 0.5) / max(context.width, 1)
    v = (grid_y + 0.5) / max(context.height, 1)
    span_x = max(right - left, 1.0e-6)
    span_y = max(bottom - top, 1.0e-6)
    return (left + u * span_x) * context.width - 0.5, (top + v * span_y) * context.height - 0.5


def _normalise_vector_pixels(result: np.ndarray) -> np.ndarray:
    normal = result[..., :3] * 2.0 - 1.0
    length = np.linalg.norm(normal, axis=2, keepdims=True)
    result[..., :3] = normal / np.maximum(length, 1.0e-6) * 0.5 + 0.5
    return result


def eval_crop(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    left = np.clip(float(params.get("left", 0.0)), 0.0, 1.0)
    right = np.clip(float(params.get("right", 1.0)), 0.0, 1.0)
    top = np.clip(float(params.get("top", 0.0)), 0.0, 1.0)
    bottom = np.clip(float(params.get("bottom", 1.0)), 0.0, 1.0)
    if right < left:
        left, right = right, left
    if bottom < top:
        top, bottom = bottom, top
    # An exact full-frame crop is an identity operation, avoiding needless
    # interpolation and preserving masks/IDs bit-for-bit.
    if left == 0.0 and top == 0.0 and right == 1.0 and bottom == 1.0:
        return image.copy()
    sx, sy = _crop_coordinates(context, left, top, right, bottom)
    span_x = max((right - left), 1.0e-6)
    span_y = max((bottom - top), 1.0e-6)
    return sample_image(
        image, sx, sy,
        filtering=str(params.get("filtering", "Automatic")),
        boundary="Clamp",
        data_kind=str(params.get("_resolved_kind", "grayscale")),
        footprint_x=span_x, footprint_y=span_y,
    )


def _auto_crop_bounds(image: np.ndarray, params: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    use_alpha = bool(params.get("use_alpha", False))
    threshold = np.clip(float(params.get("threshold", 0.001)), 0.0, 1.0)
    values = image[..., 3] if use_alpha else luminance(image)
    ys, xs = np.nonzero(values > threshold)
    if xs.size == 0 or ys.size == 0:
        return None
    height, width = image.shape[:2]
    padding = np.clip(float(params.get("padding", 0.0)), 0.0, 0.5)
    left = max(float(xs.min()) / width - padding, 0.0)
    right = min(float(xs.max() + 1) / width + padding, 1.0)
    top = max(float(ys.min()) / height - padding, 0.0)
    bottom = min(float(ys.max() + 1) / height + padding, 1.0)
    return left, top, right, bottom


def _auto_crop_sample(
    image: np.ndarray,
    params: Mapping[str, Any],
    context: EvalContext,
    bounds: tuple[float, float, float, float] | None,
) -> ImageArray:
    if bounds is None:
        return np.zeros_like(image, dtype=np.float32)
    left, top, right, bottom = bounds
    mode = str(params.get("mode", "Fit (Keep Ratio)"))
    if mode == "Crop Square":
        width = right - left
        height = bottom - top
        side = min(max(width, height), 1.0)
        cx = (left + right) * 0.5
        cy = (top + bottom) * 0.5
        left = min(max(cx - side * 0.5, 0.0), 1.0 - side)
        top = min(max(cy - side * 0.5, 0.0), 1.0 - side)
        right, bottom = left + side, top + side
    if mode in {"Crop Square", "Fill (Stretch)"}:
        sx, sy = _crop_coordinates(context, left, top, right, bottom)
        valid = np.ones((context.height, context.width), dtype=bool)
    elif mode == "Crop Auto":
        # Centre the detected content without changing its pixel scale. This is
        # the useful fixed-canvas equivalent of an automatic crop: sprites and
        # isolated shapes move to the middle, but their authored size remains.
        grid_x, grid_y = _pixel_grids(context)
        box_center_x = (left + right) * 0.5 * context.width - 0.5
        box_center_y = (top + bottom) * 0.5 * context.height - 0.5
        output_center_x = (context.width - 1.0) * 0.5
        output_center_y = (context.height - 1.0) * 0.5
        sx = grid_x + (box_center_x - output_center_x)
        sy = grid_y + (box_center_y - output_center_y)
        valid = (sx >= 0.0) & (sx <= context.width - 1.0) & (sy >= 0.0) & (sy <= context.height - 1.0)
    else:
        # Fit the detected box uniformly into the output while preserving its
        # source aspect ratio. Empty bars remain transparent/black.
        box_px_w = max((right - left) * context.width, 1.0)
        box_px_h = max((bottom - top) * context.height, 1.0)
        scale = min(context.width / box_px_w, context.height / box_px_h)
        shown_w = box_px_w * scale
        shown_h = box_px_h * scale
        grid_x, grid_y = _pixel_grids(context)
        u = (grid_x + 0.5 - (context.width - shown_w) * 0.5) / max(shown_w, 1.0)
        v = (grid_y + 0.5 - (context.height - shown_h) * 0.5) / max(shown_h, 1.0)
        valid = (u >= 0.0) & (u <= 1.0) & (v >= 0.0) & (v <= 1.0)
        sx = (left + u * (right - left)) * context.width - 0.5
        sy = (top + v * (bottom - top)) * context.height - 0.5
    filtering = str(params.get("filtering", "Automatic"))
    footprint_x, footprint_y = estimate_coordinate_footprint(sx, sy)
    result = sample_image(
        image, sx, sy, filtering=filtering, boundary="Clamp",
        data_kind=str(params.get("_resolved_kind", "grayscale")),
        footprint_x=footprint_x, footprint_y=footprint_y,
    )
    if not np.all(valid):
        result = result.copy()
        result[~valid] = 0.0
    return np.clip(result, 0.0, 1.0).astype(np.float32)


def eval_auto_crop(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    return _auto_crop_sample(image, params, context, _auto_crop_bounds(image, params))


def _sample_wrap(image: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    wrapped_x = np.mod(x, width)
    wrapped_y = np.mod(y, height)
    x0 = np.floor(wrapped_x).astype(np.int32)
    y0 = np.floor(wrapped_y).astype(np.int32)
    x0 = np.clip(x0, 0, width - 1)
    y0 = np.clip(y0, 0, height - 1)
    x1 = (x0 + 1) % width
    y1 = (y0 + 1) % height
    tx = (wrapped_x - x0).astype(np.float32)
    ty = (wrapped_y - y0).astype(np.float32)
    a = image[y0, x0]
    b = image[y0, x1]
    c = image[y1, x0]
    d = image[y1, x1]
    if image.ndim == 2:
        ab = a * (1.0 - tx) + b * tx
        cd = c * (1.0 - tx) + d * tx
        return (ab * (1.0 - ty) + cd * ty).astype(np.float32, copy=False)
    tx = tx[..., None]
    ty = ty[..., None]
    ab = a * (1.0 - tx) + b * tx
    cd = c * (1.0 - tx) + d * tx
    return (ab * (1.0 - ty) + cd * ty).astype(np.float32, copy=False)


def _pixel_grids(context: EvalContext) -> tuple[np.ndarray, np.ndarray]:
    x = np.tile(np.arange(context.width, dtype=np.float32)[None, :], (context.height, 1))
    y = np.tile(np.arange(context.height, dtype=np.float32)[:, None], (1, context.width))
    return x, y


def eval_directional_blur(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    radius = max(relative_pixels(float(params.get("distance", 16.0)), context), 0.0)
    samples = max(int(params.get("samples", 16)), 1)
    if context.render_mode == "interactive":
        samples = min(samples, 8)
    if radius <= 0.01 or samples <= 1:
        return image.copy()
    angle = math.radians(float(params.get("angle", 0.0)))
    dx = math.cos(angle) * radius
    dy = math.sin(angle) * radius
    grid_x, grid_y = _pixel_grids(context)
    result = np.zeros_like(image, dtype=np.float32)
    for index in range(samples):
        t = 0.0 if samples == 1 else (index / (samples - 1) - 0.5) * 2.0
        result += _sample_wrap(image, grid_x + dx * t, grid_y + dy * t)
    return np.clip(result / float(samples), 0.0, 1.0).astype(np.float32, copy=False)


def eval_radial_blur(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    amount = abs(float(params.get("amount", 20.0)))
    samples = max(int(params.get("samples", 16)), 1)
    if context.render_mode == "interactive":
        samples = min(samples, 8)
    if amount <= 0.01 or samples <= 1:
        return image.copy()
    center_x = float(params.get("center_x", 0.5)) * context.width
    center_y = float(params.get("center_y", 0.5)) * context.height
    amount_rad = math.radians(amount)
    grid_x, grid_y = _pixel_grids(context)
    dx = grid_x - center_x
    dy = grid_y - center_y
    result = np.zeros_like(image, dtype=np.float32)
    for index in range(samples):
        t = 0.0 if samples == 1 else (index / (samples - 1) - 0.5)
        angle = amount_rad * t
        cos_angle = math.cos(angle)
        sin_angle = math.sin(angle)
        sample_x = center_x + dx * cos_angle - dy * sin_angle
        sample_y = center_y + dx * sin_angle + dy * cos_angle
        result += _sample_wrap(image, sample_x, sample_y)
    return np.clip(result / float(samples), 0.0, 1.0).astype(np.float32, copy=False)




def eval_anisotropic_blur(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    radius = max(relative_pixels(float(params.get("intensity", 16.0)), context), 0.0)
    samples = max(int(params.get("samples", 12)), 1)
    if context.render_mode == "interactive":
        samples = min(samples, 8)
    anisotropy = min(max(float(params.get("anisotropy", 0.75)), 0.0), 1.0)
    if radius <= 0.01 or samples <= 1:
        return image.copy()
    angle = math.radians(float(params.get("angle", 0.0)))
    major = np.array([math.cos(angle), math.sin(angle)], dtype=np.float32)
    minor = np.array([-major[1], major[0]], dtype=np.float32)
    major_radius = radius
    minor_radius = radius * (1.0 - 0.9 * anisotropy)
    grid_x, grid_y = _pixel_grids(context)
    result = np.zeros_like(image, dtype=np.float32)
    total_weight = 0.0
    minor_steps = max(1, int(round(1 + (1.0 - anisotropy) * 0.5 * samples)))
    major_steps = max(2, samples)
    for mi in range(minor_steps):
        v = 0.0 if minor_steps == 1 else (mi / (minor_steps - 1) - 0.5) * 2.0
        minor_offset_x = minor[0] * minor_radius * v
        minor_offset_y = minor[1] * minor_radius * v
        minor_weight = 1.0 - abs(v) * 0.5
        for mj in range(major_steps):
            u = 0.0 if major_steps == 1 else (mj / (major_steps - 1) - 0.5) * 2.0
            sample_x = grid_x + major[0] * major_radius * u + minor_offset_x
            sample_y = grid_y + major[1] * major_radius * u + minor_offset_y
            weight = minor_weight * (1.0 - abs(u) * 0.35)
            result += _sample_wrap(image, sample_x, sample_y) * np.float32(weight)
            total_weight += weight
    return np.clip(result / max(total_weight, 1.0e-6), 0.0, 1.0).astype(np.float32, copy=False)


def eval_zoom_blur(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    amount = max(relative_pixels(float(params.get("amount", 16.0)), context), 0.0)
    samples = max(int(params.get("samples", 16)), 1)
    if context.render_mode == "interactive":
        samples = min(samples, 8)
    if amount <= 0.01 or samples <= 1:
        return image.copy()
    center_x = float(params.get("center_x", 0.5)) * context.width
    center_y = float(params.get("center_y", 0.5)) * context.height
    grid_x, grid_y = _pixel_grids(context)
    delta_x = grid_x - center_x
    delta_y = grid_y - center_y
    length = np.sqrt(delta_x * delta_x + delta_y * delta_y)
    dir_x = np.divide(delta_x, np.maximum(length, 1.0e-6), out=np.zeros_like(delta_x), where=length > 1.0e-6)
    dir_y = np.divide(delta_y, np.maximum(length, 1.0e-6), out=np.zeros_like(delta_y), where=length > 1.0e-6)
    result = np.zeros_like(image, dtype=np.float32)
    for index in range(samples):
        t = 0.0 if samples == 1 else (index / (samples - 1) - 0.5) * 2.0
        offset = amount * t
        result += _sample_wrap(image, grid_x + dir_x * offset, grid_y + dir_y * offset)
    return np.clip(result / float(samples), 0.0, 1.0).astype(np.float32, copy=False)

def eval_non_uniform_blur_grayscale(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    source = luminance(_input(inputs, "Image", context))
    blur_map_input = inputs.get("Blur Map")
    blur_map = luminance(ensure_rgba(blur_map_input, context)) if blur_map_input is not None else np.ones((context.height, context.width), dtype=np.float32)
    radius = max(relative_pixels(float(params.get("radius", 16.0)), context), 0.0)
    samples = max(int(params.get("samples", 12)), 1)
    if context.render_mode == "interactive":
        samples = min(samples, 6)
    if radius <= 0.01 or samples <= 1:
        return grayscale_rgba(source)
    amount = np.clip(blur_map, 0.0, 1.0) * radius
    grid_x, grid_y = _pixel_grids(context)
    result = source.copy().astype(np.float32)
    count = 1.0
    for index in range(samples):
        angle = (index / float(samples)) * math.tau
        offset_x = np.float32(math.cos(angle)) * amount
        offset_y = np.float32(math.sin(angle)) * amount
        result += _sample_wrap(source, grid_x + offset_x, grid_y + offset_y)
        count += 1.0
    return grayscale_rgba(np.clip(result / count, 0.0, 1.0).astype(np.float32, copy=False))


def eval_slope_blur_grayscale(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    source = luminance(_input(inputs, "Image", context))
    slope_input = inputs.get("Slope")
    slope = luminance(ensure_rgba(slope_input, context)) if slope_input is not None else source
    intensity = relative_pixels(float(params.get("intensity", 8.0)), context)
    samples = max(int(params.get("samples", 8)), 1)
    if context.render_mode == "interactive":
        samples = min(samples, 6)
    mode = str(params.get("mode", "Blur"))
    if abs(intensity) <= 0.01 or samples <= 1:
        return grayscale_rgba(source)
    slope = slope.astype(np.float32, copy=False)
    grad_x = (np.roll(slope, -1, axis=1) - np.roll(slope, 1, axis=1)) * 0.5
    grad_y = (np.roll(slope, -1, axis=0) - np.roll(slope, 1, axis=0)) * 0.5
    length = np.sqrt(grad_x * grad_x + grad_y * grad_y)
    dir_x = np.divide(grad_x, np.maximum(length, 1.0e-6), out=np.zeros_like(grad_x), where=length > 1.0e-6)
    dir_y = np.divide(grad_y, np.maximum(length, 1.0e-6), out=np.zeros_like(grad_y), where=length > 1.0e-6)
    grid_x, grid_y = _pixel_grids(context)
    if mode == "Min":
        result = source.copy().astype(np.float32)
        reducer = np.minimum
    elif mode == "Max":
        result = source.copy().astype(np.float32)
        reducer = np.maximum
    else:
        result = source.copy().astype(np.float32)
        reducer = None
        total = 1.0
    for step in range(1, samples + 1):
        distance = intensity * (step / float(samples))
        sample = _sample_wrap(source, grid_x + dir_x * distance, grid_y + dir_y * distance)
        if reducer is None:
            result += sample
            total += 1.0
        else:
            result = reducer(result, sample)
    if reducer is None:
        result = result / total
    return grayscale_rgba(np.clip(result, 0.0, 1.0).astype(np.float32, copy=False))

def eval_blend(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    """Blend Foreground over Background using standard separable blend modes.

    Colour inputs are stored as linear-light graph values, while familiar
    texture-authoring blend modes are defined over perceptual/display channel
    values. Each colour input is therefore converted to display-sRGB for the
    blend calculation and the colour result is converted back to linear light.
    Greyscale and vector/data inputs remain raw numeric values. This makes a
    visible 50% grey exactly neutral for Overlay, Soft Light, Hard Light and
    Linear Light without compromising scalar-map mathematics.

    The blend mode is calculated first, then the result is mixed over the
    Background using the node opacity multiplied by the optional greyscale
    Opacity mask. Alpha remains a straightforward Background→Foreground mix;
    blend mathematics only affects RGB/data channels.
    """
    background = _input(inputs, "Background", context)
    foreground = _input(inputs, "Foreground", context)
    mask_source = inputs.get("Opacity")
    mask = (
        ensure_rgba(mask_source)[..., 0]
        if mask_source is not None
        else np.ones((context.height, context.width), dtype=np.float32)
    )
    opacity = np.clip(float(params["opacity"]) * mask, 0.0, 1.0)[..., None]
    mode = str(params["mode"])

    background_kind = str(params.get("_background_kind", "grayscale"))
    foreground_kind = str(params.get("_foreground_kind", "grayscale"))
    output_kind = str(params.get("_output_kind", "color" if "color" in (background_kind, foreground_kind) else background_kind))

    background_linear = np.clip(background[..., :3], 0.0, 1.0)
    foreground_linear = np.clip(foreground[..., :3], 0.0, 1.0)
    b = linear_to_srgb(background_linear) if background_kind == "color" else background_linear
    f = linear_to_srgb(foreground_linear) if foreground_kind == "color" else foreground_linear
    eps = np.float32(1e-6)

    if mode == "Replace / Copy":
        mixed = f
    elif mode == "Add":
        mixed = np.clip(b + f, 0.0, 1.0)
    elif mode == "Subtract":
        mixed = np.clip(b - f, 0.0, 1.0)
    elif mode == "Multiply":
        mixed = b * f
    elif mode == "Divide":
        mixed = np.clip(b / np.maximum(f, eps), 0.0, 1.0)
    elif mode == "Add Sub / Linear Light":
        mixed = np.clip(b + 2.0 * f - 1.0, 0.0, 1.0)
    elif mode == "Minimum":
        mixed = np.minimum(b, f)
    elif mode == "Maximum":
        mixed = np.maximum(b, f)
    elif mode == "Screen":
        mixed = 1.0 - (1.0 - b) * (1.0 - f)
    elif mode == "Overlay":
        mixed = np.where(b <= 0.5, 2.0 * b * f, 1.0 - 2.0 * (1.0 - b) * (1.0 - f))
    elif mode == "Soft Light":
        d = np.where(b <= 0.25, ((16.0 * b - 12.0) * b + 4.0) * b, np.sqrt(np.maximum(b, 0.0)))
        mixed = np.where(
            f <= 0.5,
            b - (1.0 - 2.0 * f) * b * (1.0 - b),
            b + (2.0 * f - 1.0) * (d - b),
        )
    elif mode == "Hard Light":
        mixed = np.where(f <= 0.5, 2.0 * b * f, 1.0 - 2.0 * (1.0 - b) * (1.0 - f))
    elif mode == "Difference":
        mixed = np.abs(b - f)
    elif mode == "Exclusion":
        mixed = b + f - 2.0 * b * f
    elif mode == "Colour Dodge":
        mixed = np.where(f >= 1.0 - eps, 1.0, np.minimum(1.0, b / np.maximum(1.0 - f, eps)))
    elif mode == "Colour Burn":
        mixed = np.where(f <= eps, 0.0, 1.0 - np.minimum(1.0, (1.0 - b) / np.maximum(f, eps)))
    else:
        mixed = f

    mixed = np.clip(mixed, 0.0, 1.0)
    if output_kind == "color":
        mixed_graph = srgb_to_linear(mixed)
        background_graph = (
            background_linear
            if background_kind == "color"
            else srgb_to_linear(background_linear)
        )
    else:
        mixed_graph = mixed
        background_graph = background_linear

    result = background.copy()
    result[..., :3] = background_graph * (1.0 - opacity) + mixed_graph * opacity
    result[..., 3] = background[..., 3] * (1.0 - opacity[..., 0]) + foreground[..., 3] * opacity[..., 0]
    return np.nan_to_num(np.clip(result, 0.0, 1.0), nan=0.0, posinf=1.0, neginf=0.0).astype(np.float32)


def _normalise_gradient_stops(raw: Any) -> list[dict[str, Any]]:
    fallback = [{"position": 0.0, "color": "#000000ff"}, {"position": 1.0, "color": "#ffffffff"}]
    if not isinstance(raw, list):
        return fallback
    stops: list[dict[str, Any]] = []
    for entry in raw[:8]:
        if not isinstance(entry, Mapping):
            continue
        try:
            position = min(max(float(entry.get("position", 0.0)), 0.0), 1.0)
            color = str(entry.get("color", "#ffffffff"))
            parse_hex_color(color)
        except (TypeError, ValueError):
            continue
        stops.append({"position": position, "color": color})
    if not stops:
        return fallback
    stops.sort(key=lambda item: item["position"])
    if len(stops) == 1:
        stops.append({"position": 1.0, "color": stops[0]["color"]})
    return stops




def eval_color_to_grayscale(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Colour", context)
    method = str(params.get("method", "Luminance"))
    if method == "Average":
        values = np.mean(image[..., :3], axis=2)
    elif method == "Maximum":
        values = np.max(image[..., :3], axis=2)
    elif method == "Red":
        values = image[..., 0]
    elif method == "Green":
        values = image[..., 1]
    elif method == "Blue":
        values = image[..., 2]
    else:
        values = luminance(image)
    return grayscale_rgba(np.clip(values, 0.0, 1.0))

def eval_gradient_map(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    value = np.clip(luminance(_input(inputs, "Image", context)), 0.0, 1.0)
    stops = _normalise_gradient_stops(params.get("stops"))
    output = np.empty((context.height, context.width, 4), dtype=np.float32)
    positions = np.array([float(stop["position"]) for stop in stops], dtype=np.float32)
    display_colors = np.stack([parse_hex_color(str(stop["color"])) for stop in stops], axis=0)

    # The colour picker and inline ramp describe display-sRGB colours. Interpolate
    # those display components so the generated ramp visually matches the editor,
    # then convert only RGB into linear light for the graph. The 2D preview and
    # sRGB exports convert it back for display; downstream nodes retain linear data.
    display_rgb = np.empty((context.height, context.width, 3), dtype=np.float32)
    for channel in range(3):
        display_rgb[..., channel] = np.interp(value, positions, display_colors[:, channel])
    output[..., :3] = srgb_to_linear(display_rgb)
    output[..., 3] = np.interp(value, positions, display_colors[:, 3])
    return np.clip(output, 0.0, 1.0).astype(np.float32)



def eval_auto_levels(inputs: Mapping[str, ImageArray], _params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    values = luminance(image)
    low = float(np.min(values))
    high = float(np.max(values))
    if high - low < 1e-7:
        result = np.zeros_like(image)
        result[..., 3] = image[..., 3]
        return result.astype(np.float32)
    result = image.copy()
    result[..., :3] = np.clip((result[..., :3] - low) / (high - low), 0.0, 1.0)
    return result.astype(np.float32)

def eval_height_normal(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    height = luminance(_input(inputs, "Height", context))
    strength = float(params["strength"]) * resolution_scale(context)
    invert_y = bool(params["invert_y"])
    # Central differences with np.roll preserve wrapping at all four borders.
    dx = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) * 0.5
    dy = (np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)) * 0.5
    nx = -dx * strength
    ny = (-dy if not invert_y else dy) * strength
    nz = np.ones_like(height)
    length = np.sqrt(nx * nx + ny * ny + nz * nz)
    normal = np.stack((nx / length, ny / length, nz / length), axis=2)
    normal = normal * 0.5 + 0.5
    alpha = np.ones((*height.shape, 1), dtype=np.float32)
    return np.concatenate((normal.astype(np.float32), alpha), axis=2)


def eval_channel_pack(inputs: Mapping[str, ImageArray], _params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    red = luminance(_input(inputs, "Red", context, 0.0))
    green = luminance(_input(inputs, "Green", context, 0.0))
    blue = luminance(_input(inputs, "Blue", context, 0.0))
    alpha_source = inputs.get("Alpha")
    alpha = luminance(ensure_rgba(alpha_source)) if alpha_source is not None else np.ones_like(red)
    return np.stack((red, green, blue, alpha), axis=2).astype(np.float32)


def eval_extract_channel(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    channel = str(params["channel"])
    index = {"Red": 0, "Green": 1, "Blue": 2, "Alpha": 3, "Luminance": -1}[channel]
    values = luminance(image) if index == -1 else image[..., index]
    return grayscale_rgba(values)


def eval_transform(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    uniform_scale = max(float(params.get("scale", 1.0)), 0.01)
    scale_x = max(float(params.get("scale_x", 1.0)) * uniform_scale, 0.01)
    scale_y = max(float(params.get("scale_y", 1.0)) * uniform_scale, 0.01)
    angle_degrees = float(params.get("angle", 0.0))
    offset_x = float(params.get("offset_x", 0.0))
    offset_y = float(params.get("offset_y", 0.0))
    boundary = boundary_name(params, default="Seamless / Wrap", legacy_key="tile")
    filtering = str(params.get("filtering", "Automatic"))

    # Exact identity must not soften or shift the image, regardless of the
    # selected high-quality filter.
    if (abs(offset_x) <= 1.0e-12 and abs(offset_y) <= 1.0e-12
            and abs(scale_x - 1.0) <= 1.0e-12 and abs(scale_y - 1.0) <= 1.0e-12
            and abs(math.fmod(angle_degrees, 360.0)) <= 1.0e-12):
        return image.copy()

    y, x = np.mgrid[0:context.height, 0:context.width]
    # Rotate in physical pixel space so rectangular documents do not squash or
    # stretch the transformed image. Offsets and scale remain normalised to the
    # complete canvas, matching the Inspector and 2D Preview gizmo.
    pixel_x = ((x.astype(np.float32) + 0.5) / max(context.width, 1) - 0.5 - offset_x) * context.width
    pixel_y = ((y.astype(np.float32) + 0.5) / max(context.height, 1) - 0.5 - offset_y) * context.height
    angle = math.radians(angle_degrees)
    cos_a = math.cos(-angle)
    sin_a = math.sin(-angle)
    source_pixel_x = (pixel_x * cos_a - pixel_y * sin_a) / scale_x
    source_pixel_y = (pixel_x * sin_a + pixel_y * cos_a) / scale_y
    sx = source_pixel_x + (context.width - 1.0) * 0.5
    sy = source_pixel_y + (context.height - 1.0) * 0.5
    footprint_x, footprint_y = affine_pixel_footprint(scale_x, scale_y, angle_degrees)
    return sample_image(
        image, sx, sy, filtering=filtering, boundary=boundary,
        data_kind=str(params.get("_resolved_kind", "grayscale")),
        footprint_x=footprint_x, footprint_y=footprint_y,
    )


def _safe_transform_offset(params: Mapping[str, Any], context: EvalContext) -> tuple[float, float]:
    if str(params.get("offset_mode", "Manual")) == "Random":
        seed = int(params.get("random_seed", 0)) & 0xFFFFFFFF
        # Small deterministic integer hash; deliberately independent of Python's
        # salted hash so projects reproduce on every machine.
        def unit(value: int) -> float:
            value = (value ^ 61) ^ (value >> 16)
            value = (value + (value << 3)) & 0xFFFFFFFF
            value ^= value >> 4
            value = (value * 0x27D4EB2D) & 0xFFFFFFFF
            value ^= value >> 15
            return float(value & 0x00FFFFFF) / float(0x01000000)
        ox, oy = unit(seed), unit(seed ^ 0x9E3779B9)
    else:
        ox = float(params.get("offset_x", 0.0))
        oy = float(params.get("offset_y", 0.0))
    # Safe Transform offsets are pixel snapped in source space, preserving
    # sharpness for tiny translations.
    return (round(ox * max(context.width, 1)) / max(context.width, 1),
            round(oy * max(context.height, 1)) / max(context.height, 1))


def _safe_lattice(tile_count: int, angle_degrees: float) -> tuple[int, int]:
    """Choose a periodic integer basis near the requested tile/rotation."""
    requested = math.radians(angle_degrees)
    best = (max(tile_count, 1), 0)
    best_score = float("inf")
    radius = max(int(tile_count), 1)
    limit = max(radius + 2, 3)
    for a in range(-limit, limit + 1):
        for b in range(-limit, limit + 1):
            if a == 0 and b == 0:
                continue
            length = math.hypot(a, b)
            if length < 0.5:
                continue
            angle = math.atan2(b, a)
            delta = abs(math.atan2(math.sin(angle - requested), math.cos(angle - requested)))
            score = delta * 4.0 + abs(length - radius) / max(radius, 1)
            if score < best_score:
                best_score = score
                best = (a, b)
    return best


def eval_safe_transform(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    image = _input(inputs, "Image", context)
    tiles = int(np.clip(int(params.get("tiles", 1)), 1, 16))
    angle_degrees = float(params.get("angle", 0.0))
    safe_rotation = bool(params.get("tile_safe_rotation", True))
    offset_x, offset_y = _safe_transform_offset(params, context)
    y, x = np.mgrid[0:context.height, 0:context.width]
    u = (x.astype(np.float32) + 0.5) / max(context.width, 1) - 0.5
    v = (y.astype(np.float32) + 0.5) / max(context.height, 1) - 0.5
    if safe_rotation:
        a, b = _safe_lattice(tiles, -angle_degrees)
        source_u = a * u - b * v + 0.5 - offset_x
        source_v = b * u + a * v + 0.5 - offset_y
        footprint = max(math.hypot(a, b), 1.0)
    else:
        angle = math.radians(angle_degrees)
        c, ss = math.cos(-angle), math.sin(-angle)
        source_u = (u * c - v * ss) * tiles + 0.5 - offset_x
        source_v = (u * ss + v * c) * tiles + 0.5 - offset_y
        footprint = float(tiles)

    symmetry = str(params.get("symmetry", "None"))
    if symmetry in {"X", "X + Y"}:
        source_u = 1.0 - np.abs((np.mod(source_u, 1.0) * 2.0) - 1.0)
    if symmetry in {"Y", "X + Y"}:
        source_v = 1.0 - np.abs((np.mod(source_v, 1.0) * 2.0) - 1.0)

    mip_level = int(np.clip(int(params.get("mipmap_level", 0)), 0, 10))
    mip_mode = str(params.get("mipmap_mode", "Automatic"))
    manual_factor = float(2 ** mip_level) if mip_mode == "Manual" else 1.0
    identity_basis = (
        (safe_rotation and a == 1 and b == 0)
        or (not safe_rotation and tiles == 1 and abs(math.fmod(angle_degrees, 360.0)) <= 1.0e-12)
    )
    if (identity_basis and abs(offset_x) <= 1.0e-12 and abs(offset_y) <= 1.0e-12
            and symmetry == "None" and manual_factor == 1.0):
        return image.copy()
    sx = source_u * context.width - 0.5
    sy = source_v * context.height - 0.5
    return sample_image(
        image, sx, sy, filtering=str(params.get("filtering", "Automatic")),
        boundary="Seamless / Wrap", data_kind=str(params.get("_resolved_kind", "grayscale")),
        footprint_x=footprint * manual_factor, footprint_y=footprint * manual_factor,
    )



def _flipbook_grid(params: Mapping[str, Any]) -> tuple[int, int]:
    return flipbook_grid(params)


def flipbook_frame_index(params: Mapping[str, Any], context: EvalContext, *, inherited_count: int | None = None) -> tuple[int, int]:
    selection = flipbook_frame_selection(params, context, inherited_count=inherited_count)
    return selection.atlas_index, selection.frame_count


def _sample_flipbook_cell(source: np.ndarray, context: EvalContext, params: Mapping[str, Any]) -> ImageArray:
    source = ensure_rgba(source, context)
    source_height, source_width = source.shape[:2]
    columns, rows = flipbook_grid(params)
    selection = flipbook_frame_selection(params, context)
    frame_index = selection.atlas_index
    order = str(params.get("order", "Left to Right, Top to Bottom"))
    if order == "Top to Bottom, Left to Right":
        column = frame_index // rows
        row = frame_index % rows
    else:
        row = frame_index // columns
        column = frame_index % columns
    column = min(max(column, 0), columns - 1)
    row = min(max(row, 0), rows - 1)

    padding = max(int(params.get("padding", 0)), 0)
    cell_width = max((source_width - max(columns - 1, 0) * padding) / columns, 1.0)
    cell_height = max((source_height - max(rows - 1, 0) * padding) / rows, 1.0)
    origin_x = column * (cell_width + padding)
    origin_y = row * (cell_height + padding)

    y, x = np.mgrid[0:context.height, 0:context.width]
    u = (x.astype(np.float32) + 0.5) / max(context.width, 1)
    v = (y.astype(np.float32) + 0.5) / max(context.height, 1)
    sx = origin_x + u * max(cell_width - 1.0, 0.0)
    sy = origin_y + v * max(cell_height - 1.0, 0.0)
    x0 = np.floor(sx).astype(np.int32)
    y0 = np.floor(sy).astype(np.int32)
    x1 = np.minimum(x0 + 1, int(math.ceil(origin_x + cell_width - 1.0)))
    y1 = np.minimum(y0 + 1, int(math.ceil(origin_y + cell_height - 1.0)))
    x0 = np.clip(x0, 0, source_width - 1)
    x1 = np.clip(x1, 0, source_width - 1)
    y0 = np.clip(y0, 0, source_height - 1)
    y1 = np.clip(y1, 0, source_height - 1)
    tx = (sx - x0)[..., None]
    ty = (sy - y0)[..., None]
    top = source[y0, x0] * (1.0 - tx) + source[y0, x1] * tx
    bottom = source[y1, x0] * (1.0 - tx) + source[y1, x1] * tx
    return np.clip(top * (1.0 - ty) + bottom * ty, 0.0, 1.0).astype(np.float32)


def eval_flipbook_decode(inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    sheet = _input(inputs, "Sheet", context)
    return _sample_flipbook_cell(sheet, context, params)

def eval_output(inputs: Mapping[str, ImageArray], _params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    return _input(inputs, "Image", context)


def eval_reinterpret_image(inputs: Mapping[str, ImageArray], _params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    """Change semantic image type without altering encoded channel values."""
    return _input(inputs, "Image", context)


def eval_material_preview(inputs: Mapping[str, ImageArray], _params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    """Preview the base-colour branch of a material definition in 2D."""
    return _input(inputs, "Base Colour", context, value=0.32)


def register_processing_nodes(registry: NodeRegistry) -> None:
    f = ParameterSpec
    definitions = [
        NodeDefinition(
            "filter.invert", "Invert", "Filters", eval_invert, inputs=("Image",),
            description="Invert RGB while preserving alpha and seamless edges.", accent="#6e8ed7",
            gpu_kernel="invert.wgsl",
        ),
        NodeDefinition(
            "filter.levels", "Levels", "Filters", eval_levels, inputs=("Image",),
            parameters=(
                f(
                    "in_low", "Level In Low", "float", 0.0, 0.0, 1.0, 0.001,
                    description="Input values at or below this point become full black before output remapping.",
                    animatable=True,
                ),
                f(
                    "in_high", "Level In High", "float", 1.0, 0.0, 1.0, 0.001,
                    description="Input values at or above this point become full white before output remapping.",
                    animatable=True,
                ),
                f(
                    "in_mid", "Level In Mid", "float", 0.5, 0.0, 1.0, 0.001,
                    description="The input tone that should become middle grey (0.5).",
                    animatable=True,
                ),
                f(
                    "out_low", "Level Out Low", "float", 0.0, 0.0, 1.0, 0.001,
                    description="Output value produced by full black after the input remap.",
                    animatable=True,
                ),
                f(
                    "out_high", "Level Out High", "float", 1.0, 0.0, 1.0, 0.001,
                    description="Output value produced by full white after the input remap.",
                    animatable=True,
                ),
                f(
                    "intermediary_clamp", "Intermediary Clamp", "bool", True,
                    description="Clamp the transformed input to 0–1 before applying the output range.",
                ),
            ),
            description=(
                "Remap shadows, midtones and highlights with a live input histogram. "
                "Use Auto Level for a one-time range fit; unlike Auto Levels, it does not keep adapting."
            ),
            tags=("contrast", "remap", "histogram", "tones"), accent="#6e8ed7",
            gpu_kernel="levels.wgsl",
        ),
        NodeDefinition(
            "filter.histogram_range", "Histogram Range", "Filters", eval_histogram_range, inputs=("Image",),
            parameters=(
                f("range", "Range", "float", 1.0, 0.0, 1.0, 0.001, description="Width of the resulting value range.", animatable=True),
                f("position", "Position", "float", 0.5, 0.0, 1.0, 0.001, description="Where the reduced range sits between black and white.", animatable=True),
            ),
            description="Compress a greyscale input into a smaller movable range, with a live input histogram.",
            tags=("histogram", "range", "compress", "values"), accent="#6e8ed7",
            output_format="r16f", gpu_kernel="histogram_range.wgsl",
        ),
        NodeDefinition(
            "filter.histogram_shift", "Histogram Shift", "Filters", eval_histogram_shift, inputs=("Image",),
            parameters=(
                f("position", "Position", "float", 0.0, 0.0, 1.0, 0.001, description="Circular offset through the 0–1 value range; 1 is the same as 0.", animatable=True),
            ),
            description="Shift all greyscale values together and wrap them around the 0–1 range.",
            tags=("histogram", "shift", "offset", "wrap"), accent="#6e8ed7",
            output_format="r16f", gpu_kernel="histogram_shift.wgsl",
        ),
        NodeDefinition(
            "filter.histogram_scan", "Histogram Scan", "Filters", eval_histogram_scan, inputs=("Image",),
            parameters=(
                f("position", "Position", "float", 0.5, 0.0, 1.0, 0.001, description="Grow or shrink the selected white region.", animatable=True),
                f("contrast", "Contrast", "float", 0.5, 0.0, 1.0, 0.001, description="Hardness of the transition; 1 produces a hard edge.", animatable=True),
            ),
            description="Grow, shrink and harden greyscale masks using Position and Contrast.",
            tags=("histogram", "scan", "mask", "grow", "shrink"), accent="#6e8ed7",
            output_format="r16f", gpu_kernel="histogram_scan.wgsl",
        ),
        NodeDefinition(
            "filter.histogram_select", "Histogram Select", "Filters", eval_histogram_select, inputs=("Image",),
            parameters=(
                f("position", "Position", "float", 0.5, 0.0, 1.0, 0.001, description="Middle value of the selected tonal band.", animatable=True),
                f("range", "Range", "float", 0.25, 0.0, 1.0, 0.001, description="Full width of the selected value range.", animatable=True),
                f("contrast", "Contrast", "float", 0.5, 0.0, 1.0, 0.001, description="Tightens the selection falloff without moving its centre.", animatable=True),
            ),
            description="Select a value band around Position, with adjustable width and falloff.",
            tags=("histogram", "select", "range", "band", "mask", "height"), accent="#6e8ed7",
            output_format="r16f", gpu_kernel="histogram_select.wgsl",
        ),
        NodeDefinition(
            "filter.brightness", "Brightness", "Filters", eval_brightness, inputs=("Image",),
            parameters=(f("brightness", "Brightness", "float", 0.0, -1.0, 1.0, 0.001, animatable=True),),
            description="Add a uniform offset to the image values.",
            tags=("brighten", "darken", "offset"), accent="#6e8ed7", gpu_kernel="adjust_scalar.wgsl",
        ),
        NodeDefinition(
            "filter.contrast", "Contrast", "Filters", eval_contrast, inputs=("Image",),
            parameters=(
                f("contrast", "Contrast", "float", 0.0, -1.0, 1.0, 0.001, description="Negative values flatten contrast; positive values expand it.", animatable=True),
                f("pivot", "Pivot", "float", 0.5, 0.0, 1.0, 0.001, description="Value around which contrast expands or contracts.", animatable=True),
            ),
            description="Expand or compress values around a chosen pivot.",
            tags=("contrast", "pivot", "tones"), accent="#6e8ed7", gpu_kernel="adjust_scalar.wgsl",
        ),
        NodeDefinition(
            "filter.exposure", "Exposure", "Filters", eval_exposure, inputs=("Image",),
            parameters=(f("exposure", "Exposure (stops)", "float", 0.0, -10.0, 10.0, 0.01, animatable=True),),
            description="Multiply image values in photographic stops; each +1 doubles the value.",
            tags=("exposure", "stops", "multiply", "hdr"), accent="#6e8ed7", gpu_kernel="adjust_scalar.wgsl",
        ),
        NodeDefinition(
            "filter.gamma", "Gamma", "Filters", eval_gamma, inputs=("Image",),
            parameters=(f("gamma", "Gamma", "float", 1.0, 0.01, 10.0, 0.001, animatable=True),),
            description="Apply a dedicated gamma curve without the other controls of Levels.",
            tags=("gamma", "midtone", "power"), accent="#6e8ed7", gpu_kernel="adjust_scalar.wgsl",
        ),
        NodeDefinition(
            "filter.posterize", "Posterize", "Filters", eval_posterize, inputs=("Image",),
            parameters=(f("steps", "Steps", "int", 8, 2, 256, 1, animatable=True),),
            description="Reduce continuous values to a fixed number of evenly spaced levels.",
            tags=("posterize", "steps", "bands", "quantize"), accent="#6e8ed7", gpu_kernel="adjust_scalar.wgsl",
        ),
        NodeDefinition(
            "filter.clamp", "Clamp", "Filters", eval_image_clamp, inputs=("Image",),
            parameters=(
                f("minimum", "Minimum", "float", 0.0, 0.0, 1.0, 0.001, animatable=True),
                f("maximum", "Maximum", "float", 1.0, 0.0, 1.0, 0.001, animatable=True),
            ),
            description="Restrict image values to a chosen minimum and maximum.",
            tags=("clamp", "limit", "range"), accent="#6e8ed7", gpu_kernel="adjust_scalar.wgsl",
        ),
        NodeDefinition(
            "filter.hue_shift", "Hue Shift", "Filters", eval_hue_shift, inputs=("Colour",),
            parameters=(f("degrees", "Hue Shift", "float", 0.0, -360.0, 360.0, 0.1, description="Rotate hue around the colour wheel in degrees.", animatable=True, slider_minimum=-180.0, slider_maximum=180.0, fine_step=1.0, coarse_step=5.0, unit="degrees"),),
            description="Rotate hue while preserving HSL saturation and lightness.",
            tags=("hsl", "hue", "colour", "color"), accent="#6e8ed7", gpu_kernel="hsl_adjust.wgsl",
        ),
        NodeDefinition(
            "filter.saturation", "Saturation", "Filters", eval_saturation, inputs=("Colour",),
            parameters=(f("saturation", "Saturation", "float", 1.0, 0.0, 2.0, 0.001, description="0 removes colour; 1 is unchanged; 2 doubles HSL saturation.", animatable=True),),
            description="Adjust only HSL saturation.",
            tags=("hsl", "saturation", "colour", "color"), accent="#6e8ed7", gpu_kernel="hsl_adjust.wgsl",
        ),
        NodeDefinition(
            "filter.lightness", "Lightness", "Filters", eval_lightness, inputs=("Colour",),
            parameters=(f("lightness", "Lightness", "float", 0.0, -1.0, 1.0, 0.001, description="Add to the HSL lightness channel.", animatable=True),),
            description="Adjust only HSL lightness, separately from Brightness and Exposure.",
            tags=("hsl", "lightness", "colour", "color"), accent="#6e8ed7", gpu_kernel="hsl_adjust.wgsl",
        ),
        NodeDefinition(
            "filter.curve", "Tone Curve", "Filters", eval_image_curve, inputs=("Image",),
            parameters=(
                f("points", "Curve", "curve", [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]),
                f("interpolation", "Interpolation", "enum", "Smooth", options=("Linear", "Smooth")),
            ),
            description="Remap image values through an inline editable tone curve.",
            tags=("curve", "response", "tone", "remap"), accent="#6e8ed7", gpu_kernel="image_curve.wgsl",
        ),
        NodeDefinition(
            "filter.auto_levels", "Auto Levels", "Filters", eval_auto_levels, inputs=("Image",),
            description="Automatically remap the image luminance range to 0–1. Uses global image statistics.",
            tags=("normalize", "contrast", "range"), accent="#6e8ed7",
            output_format="rgba16f", gpu_kernel="auto_levels.wgsl",
        ),
        NodeDefinition(
            "filter.highpass", "Highpass", "Filters", eval_highpass, inputs=("Image",),
            parameters=(
                f("radius", "Radius", "float", 16.0, 0.0, 64.0, 0.1, animatable=True, unit="rpx",
                  description="Resolution-independent frequency separation radius. Larger values remove broader lighting variation."),
                f("boundary", "Boundary", "enum", "Clamp", options=("Clamp", "Seamless / Wrap"),
                  description="Clamp photographs at their borders or wrap already-tileable textures."),
            ),
            description="Extract fine detail around neutral grey for texture cleanup, sharpening and lighting removal.",
            tags=("high pass", "detail", "frequency", "sharpen", "photo", "lighting"), accent="#6e8ed7",
            gpu_kernel="highpass_combine.wgsl",
        ),
        NodeDefinition(
            "filter.edge_detect", "Edge Detect", "Filters", eval_edge_detect, inputs=("Image",),
            parameters=(
                f("method", "Method", "enum", "Scharr", options=("Scharr", "Sobel")),
                f("width", "Width", "float", 1.0, 0.25, 16.0, 0.05, animatable=True,
                  description="Sampling distance, scaled consistently with graph resolution."),
                f("intensity", "Intensity", "float", 1.0, 0.0, 16.0, 0.01, animatable=True),
                f("invert", "Invert", "bool", False),
            ),
            description="Extract luminance edges using Scharr or Sobel derivatives.",
            tags=("edge", "sobel", "scharr", "outline", "gradient"), accent="#6e8ed7",
            output_format="r16f", gpu_kernel="edge_detect.wgsl",
        ),
        NodeDefinition(
            "filter.fxaa", "FXAA", "Filters", eval_fxaa, inputs=("Image",),
            parameters=(
                f("quality", "Quality", "enum", "Medium", options=("Low", "Medium", "High")),
                f("edge_threshold", "Edge Threshold", "float", 0.0312, 0.0, 0.5, 0.0001, animatable=True,
                  description="Absolute local contrast required before anti-aliasing is applied."),
                f("relative_threshold", "Relative Threshold", "float", 0.125, 0.0, 1.0, 0.001, animatable=True),
                f("subpixel", "Subpixel", "float", 0.75, 0.0, 1.0, 0.001, animatable=True),
                f("preserve_alpha", "Preserve Alpha", "bool", True),
            ),
            description="Fast post-process anti-aliasing for greyscale, colour and renormalised normal/vector images.",
            tags=("anti alias", "antialias", "fxaa", "jagged", "edge"), accent="#6e8ed7",
            gpu_kernel="fxaa.wgsl",
        ),
        NodeDefinition(
            "filter.threshold", "Threshold", "Filters", eval_threshold, inputs=("Image",),
            parameters=(
                f("threshold", "Threshold", "float", 0.5, 0.0, 1.0, 0.01, animatable=True),
                f("softness", "Softness", "float", 0.0, 0.0, 1.0, 0.005, animatable=True),
            ),
            tags=("mask", "binary", "step"), accent="#6e8ed7",
            output_format="r16f",
            gpu_kernel="threshold.wgsl",
        ),
        NodeDefinition(
            "filter.blur", "Gaussian Blur", "Filters", eval_blur, inputs=("Image",),
            parameters=(f("radius", "Radius", "float", 4.0, 0.0, 42.0, 0.25, animatable=True, unit="rpx", description="Resolution-independent pixels measured at a 512-pixel reference; scales automatically with preview and export resolution."),),
            description="A wrap-aware Gaussian blur for seamless textures.",
            tags=("soften", "tile", "seamless"), accent="#6e8ed7",
            gpu_kernel="gaussian_blur.wgsl",
        ),
        NodeDefinition(
            "filter.directional_blur", "Directional Blur", "Filters", eval_directional_blur, inputs=("Image",),
            parameters=(
                f("distance", "Distance", "float", 16.0, 0.0, 8192.0, 0.5, animatable=True, slider_maximum=256.0, fine_step=0.5, coarse_step=5.0, unit="rpx"),
                f("angle", "Angle", "float", 0.0, -180.0, 180.0, 1.0, animatable=True, editor="angle", unit="degrees", fine_step=1.0, coarse_step=5.0),
                f("samples", "Samples", "int", 16, 2, 128, 1, slider_maximum=32, fine_step=1, coarse_step=4),
            ),
            description="Blur along a single direction using seamless wrapped sampling. Distance uses resolution-independent relative pixels.",
            tags=("blur", "directional", "motion", "streak", "seamless"), accent="#6e8ed7",
            output_format="rgba16f",
            gpu_kernel="directional_blur.wgsl",
        ),
        NodeDefinition(
            "filter.radial_blur", "Radial Blur", "Filters", eval_radial_blur, inputs=("Image",),
            parameters=(
                f("amount", "Amount", "float", 20.0, 0.0, 360.0, 1.0, animatable=True, slider_maximum=90.0, fine_step=1.0, coarse_step=5.0, unit="degrees"),
                f("center_x", "Centre X", "float", 0.5, 0.0, 1.0, 0.01, animatable=True),
                f("center_y", "Centre Y", "float", 0.5, 0.0, 1.0, 0.01, animatable=True),
                f("samples", "Samples", "int", 16, 2, 128, 1, slider_maximum=32, fine_step=1, coarse_step=4),
            ),
            description="Spin-blur an image around a configurable centre while preserving seamless tiling.",
            tags=("blur", "radial", "spin", "vfx", "seamless"), accent="#6e8ed7",
            output_format="rgba16f",
            gpu_kernel="radial_blur.wgsl",
        ),
        NodeDefinition(
            "filter.zoom_blur", "Zoom Blur", "Filters", eval_zoom_blur, inputs=("Image",),
            parameters=(
                f("amount", "Amount", "float", 16.0, 0.0, 8192.0, 0.5, animatable=True, slider_maximum=256.0, fine_step=0.5, coarse_step=5.0, unit="rpx"),
                f("center_x", "Centre X", "float", 0.5, 0.0, 1.0, 0.01, animatable=True),
                f("center_y", "Centre Y", "float", 0.5, 0.0, 1.0, 0.01, animatable=True),
                f("samples", "Samples", "int", 16, 2, 128, 1, slider_maximum=32, fine_step=1, coarse_step=4),
            ),
            description="Blur radially outward and inward from a centre point along each pixel's local ray direction. Amount uses resolution-independent relative pixels.",
            tags=("blur", "zoom", "radial", "outward", "seamless", "vfx"), accent="#6e8ed7",
            output_format="rgba16f",
            gpu_kernel="zoom_blur.wgsl",
        ),
        NodeDefinition(
            "filter.anisotropic_blur", "Anisotropic Blur", "Filters", eval_anisotropic_blur, inputs=("Image",),
            parameters=(
                f("intensity", "Intensity", "float", 16.0, 0.0, 8192.0, 0.5, animatable=True, slider_maximum=256.0, fine_step=0.5, coarse_step=5.0, unit="rpx"),
                f("anisotropy", "Anisotropy", "float", 0.75, 0.0, 1.0, 0.01, animatable=True),
                f("angle", "Angle", "float", 0.0, -180.0, 180.0, 1.0, animatable=True, editor="angle", unit="degrees", fine_step=1.0, coarse_step=5.0),
                f("samples", "Samples", "int", 12, 2, 128, 1, slider_maximum=32, fine_step=1, coarse_step=4),
            ),
            description="Apply an oriented elliptical blur with controllable anisotropy and direction. Intensity uses resolution-independent relative pixels.",
            tags=("blur", "anisotropic", "directional", "elliptical", "seamless"), accent="#6e8ed7",
            output_format="rgba16f",
            gpu_kernel="anisotropic_blur.wgsl",
        ),
        NodeDefinition(
            "filter.non_uniform_blur_grayscale", "Non-uniform Blur Grayscale", "Filters", eval_non_uniform_blur_grayscale, inputs=("Image", "Blur Map"),
            parameters=(
                f("radius", "Radius", "float", 16.0, 0.0, 8192.0, 0.5, animatable=True, slider_maximum=256.0, fine_step=0.5, coarse_step=5.0, unit="rpx"),
                f("samples", "Samples", "int", 12, 2, 128, 1, slider_maximum=32, fine_step=1, coarse_step=4),
            ),
            description="Apply a grayscale blur whose local radius is modulated per pixel by an optional Blur Map. Radius uses resolution-independent relative pixels.",
            tags=("blur", "non-uniform", "grayscale", "height", "mask"), accent="#6e8ed7",
            output_format="r16f",
            gpu_kernel="non_uniform_blur_grayscale.wgsl",
        ),
        NodeDefinition(
            "filter.slope_blur_grayscale", "Slope Blur Grayscale", "Filters", eval_slope_blur_grayscale, inputs=("Image", "Slope"),
            parameters=(
                f("mode", "Mode", "enum", "Blur", options=("Blur", "Min", "Max")),
                f("intensity", "Intensity", "float", 8.0, -8192.0, 8192.0, 0.5, animatable=True, slider_minimum=-128.0, slider_maximum=128.0, fine_step=0.5, coarse_step=5.0, unit="rpx"),
                f("samples", "Samples", "int", 8, 2, 128, 1, slider_maximum=32, fine_step=1, coarse_step=4),
            ),
            description="Blur a grayscale image along the local gradient direction of a second grayscale slope input. Intensity uses resolution-independent relative pixels.",
            tags=("blur", "slope blur", "grayscale", "height", "mask", "erosion"), accent="#6e8ed7",
            output_format="r16f",
            gpu_kernel="slope_blur_grayscale.wgsl",
        ),
        NodeDefinition(
            "transform.crop", "Crop", "Transform", eval_crop, inputs=("Image",),
            parameters=(
                f("left", "Left", "float", 0.0, 0.0, 1.0, 0.001, animatable=True, group="Crop Bounds", group_order=0),
                f("right", "Right", "float", 1.0, 0.0, 1.0, 0.001, animatable=True, group="Crop Bounds", group_order=0),
                f("top", "Top", "float", 0.0, 0.0, 1.0, 0.001, animatable=True, group="Crop Bounds", group_order=0),
                f("bottom", "Bottom", "float", 1.0, 0.0, 1.0, 0.001, animatable=True, group="Crop Bounds", group_order=0),
                f("filtering", "Filtering", "enum", "Automatic", options=FILTERING_OPTIONS, group="Sampling", group_order=10),
            ),
            description="Crop a normalised rectangular region and remap it to the full output canvas.",
            tags=("crop", "frame", "scan", "photo", "region"), accent="#5cb8a8",
            gpu_kernel="crop.wgsl",
        ),
        NodeDefinition(
            "transform.auto_crop", "Auto Crop", "Transform", eval_auto_crop, inputs=("Image",),
            parameters=(
                f("mode", "Mode", "enum", "Fit (Keep Ratio)", options=("Crop Square", "Crop Auto", "Fit (Keep Ratio)", "Fill (Stretch)"), group="Crop", group_order=0),
                f("use_alpha", "Use Alpha", "bool", False, description="Use alpha instead of luminance to find content bounds.", group="Detection", group_order=10),
                f("threshold", "Threshold", "float", 0.001, 0.0, 1.0, 0.001, animatable=True, description="Pixels above this value define the content box.", group="Detection", group_order=10),
                f("padding", "Padding", "float", 0.0, 0.0, 0.5, 0.001, animatable=True, description="Normalised padding added around detected content.", group="Detection", group_order=10),
                f("filtering", "Filtering", "enum", "Automatic", options=FILTERING_OPTIONS, group="Sampling", group_order=20),
            ),
            description="Detect non-black or alpha content, then crop, fit or stretch it into the output canvas.",
            tags=("auto crop", "bounds", "fit", "centre", "scan", "sprite"), accent="#5cb8a8",
            gpu_kernel="auto_crop.wgsl",
        ),
        NodeDefinition(
            "transform.basic", "Transform 2D", "Transform", eval_transform, inputs=("Image",),
            parameters=(
                f("offset_x", "Offset X", "float", 0.0, -100.0, 100.0, 0.001, animatable=True, slider_minimum=-2.0, slider_maximum=2.0, fine_step=0.01, coarse_step=0.1, group="Transform", group_order=0),
                f("offset_y", "Offset Y", "float", 0.0, -100.0, 100.0, 0.001, animatable=True, slider_minimum=-2.0, slider_maximum=2.0, fine_step=0.01, coarse_step=0.1, group="Transform", group_order=0),
                f("scale", "Uniform Scale", "float", 1.0, 0.01, 100.0, 0.01, animatable=True, slider_maximum=4.0, fine_step=0.01, coarse_step=0.1, group="Scale / Stretch", group_order=10),
                f("scale_x", "Scale X", "float", 1.0, 0.01, 100.0, 0.01, animatable=True, slider_maximum=4.0, fine_step=0.01, coarse_step=0.1, group="Scale / Stretch", group_order=10),
                f("scale_y", "Scale Y", "float", 1.0, 0.01, 100.0, 0.01, animatable=True, slider_maximum=4.0, fine_step=0.01, coarse_step=0.1, group="Scale / Stretch", group_order=10),
                f("angle", "Angle", "float", 0.0, -100000.0, 100000.0, 0.1, animatable=True, slider_minimum=-180.0, slider_maximum=180.0, fine_step=1.0, coarse_step=5.0, editor="angle", unit="degrees", angle_wrap=False, description="The dial and slider cover one turn; the dial accumulates and the numeric field accepts larger values for multi-turn animation.", group="Transform", group_order=0),
                f("boundary", "Boundary", "enum", "Seamless / Wrap", options=BOUNDARY_OPTIONS, group="Sampling", group_order=20),
                f("filtering", "Filtering", "enum", "Automatic", options=FILTERING_OPTIONS, group="Sampling", group_order=20),
            ),
            description="Move, rotate, uniformly scale, stretch or squash an image with typed high-quality resampling. The 2D Preview exposes centre, corner, edge and rotation handles.",
            accent="#bd7a57", tags=("move", "rotate", "scale", "stretch", "squash", "tile", "bicubic"),
            gpu_kernel="transform_2d.wgsl",
        ),
        NodeDefinition(
            "transform.safe", "Safe Transform", "Transform", eval_safe_transform, inputs=("Image",),
            parameters=(
                f("tiles", "Tile", "int", 1, 1, 16, 1, animatable=True, group="Transform", group_order=0,
                  description="Integer repetition count used by the periodic transform."),
                f("offset_mode", "Offset Mode", "enum", "Manual", options=("Manual", "Random"), group="Offset", group_order=10),
                f("offset_x", "Offset X", "float", 0.0, -100.0, 100.0, 0.001, animatable=True, slider_minimum=-1.0, slider_maximum=1.0, fine_step=0.01, coarse_step=0.1, group="Offset", group_order=10, visible_when=(("offset_mode", ("Manual",)),)),
                f("offset_y", "Offset Y", "float", 0.0, -100.0, 100.0, 0.001, animatable=True, slider_minimum=-1.0, slider_maximum=1.0, fine_step=0.01, coarse_step=0.1, group="Offset", group_order=10, visible_when=(("offset_mode", ("Manual",)),)),
                f("random_seed", "Random Seed", "int", 0, 0, 2147483647, 1, animatable=True, is_random_seed=True, group="Offset", group_order=10, visible_when=(("offset_mode", ("Random",)),)),
                f("angle", "Rotation", "float", 0.0, -100000.0, 100000.0, 0.1, animatable=True, slider_minimum=-180.0, slider_maximum=180.0, fine_step=1.0, coarse_step=5.0, editor="angle", unit="degrees", angle_wrap=False, group="Transform", group_order=0),
                f("tile_safe_rotation", "Tile Safe Rotation", "bool", True, group="Transform", group_order=0,
                  description="Snap rotation to a nearby integer lattice direction so opposite output borders remain periodic."),
                f("symmetry", "Symmetry", "enum", "None", options=("None", "X", "Y", "X + Y"), group="Transform", group_order=0),
                f("filtering", "Filtering", "enum", "Automatic", options=FILTERING_OPTIONS, group="Sampling", group_order=20),
                f("mipmap_mode", "Mipmap Mode", "enum", "Automatic", options=("Automatic", "Manual"), group="Sampling", group_order=20),
                f("mipmap_level", "Mipmap Level", "int", 0, 0, 10, 1, group="Sampling", group_order=20, visible_when=(("mipmap_mode", ("Manual",)),),
                  description="Additional area-prefilter level used when manually reducing high-frequency detail."),
            ),
            description="Tiling-safe transform with pixel-snapped offsets, integer-lattice rotation, symmetry and detail-aware filtering.",
            accent="#bd7a57", tags=("safe transform", "tile safe", "sharp", "periodic", "noise", "mipmap"),
            gpu_kernel="safe_transform.wgsl",
        ),
        NodeDefinition(
            "math.blend", "Blend", "Math", eval_blend, inputs=("Foreground", "Background", "Opacity"),
            parameters=(
                f(
                    "mode", "Mode", "enum", "Replace / Copy",
                    options=(
                        "Replace / Copy",
                        "Add",
                        "Subtract",
                        "Multiply",
                        "Divide",
                        "Add Sub / Linear Light",
                        "Minimum",
                        "Maximum",
                        "Screen",
                        "Overlay",
                        "Soft Light",
                        "Hard Light",
                        "Difference",
                        "Exclusion",
                        "Colour Dodge",
                        "Colour Burn",
                    ),
                ),
                f("opacity", "Opacity", "float", 1.0, 0.0, 1.0, 0.01, animatable=True),
            ),
            description=(
                "Blend Foreground over Background. Colour textures use familiar perceptual/sRGB blend mathematics; "
                "greyscale and vector data remain raw numeric values. Opacity is multiplied by the optional greyscale mask."
            ),
            accent="#a977c5",
            tags=(
                "mix", "combine", "copy", "replace", "add", "subtract", "multiply", "divide",
                "overlay", "screen", "soft light", "hard light", "difference", "dodge", "burn",
            ),
            gpu_kernel="blend.wgsl",
        ),
        NodeDefinition(
            "convert.color_to_grayscale", "Colour to Greyscale", "Conversion", eval_color_to_grayscale, inputs=("Colour",),
            parameters=(f("method", "Method", "enum", "Luminance", options=("Luminance", "Average", "Maximum", "Red", "Green", "Blue")),),
            description="Explicitly convert a colour texture into greyscale data.",
            accent="#699f70", tags=("colour", "grayscale", "luminance", "convert"),
            output_format="r16f", gpu_kernel="color_to_grayscale.wgsl",
        ),
        NodeDefinition(
            "convert.gradient_map", "Gradient Map", "Conversion", eval_gradient_map, inputs=("Image",),
            parameters=(
                f("stops", "Gradient", "gradient", [
                    {"position": 0.0, "color": "#000000ff"},
                    {"position": 1.0, "color": "#ffffffff"},
                ]),
            ),
            description="Map greyscale values through a display-sRGB colour ramp and output linear-light colour for downstream processing.",
            accent="#699f70", tags=("colourise", "albedo", "emissive"),
            gpu_kernel="gradient_map.wgsl",
        ),
        NodeDefinition(
            "convert.color_to_vector", "Colour to Vector / Normal", "Conversion", eval_reinterpret_image, inputs=("Image",),
            description="Reinterpret existing colour channels as linear vector/normal data without changing their values.",
            accent="#699f70", tags=("reinterpret", "normal map", "vector", "colour", "type"),
            gpu_kernel="image_output.wgsl",
        ),
        NodeDefinition(
            "convert.vector_to_color", "Vector / Normal to Colour", "Conversion", eval_reinterpret_image, inputs=("Image",),
            description="Reinterpret encoded vector/normal channels as colour data without changing their values.",
            accent="#699f70", tags=("reinterpret", "normal map", "vector", "colour", "type"),
            gpu_kernel="image_output.wgsl",
        ),
        NodeDefinition(
            "convert.height_normal", "Height to Normal", "Conversion", eval_height_normal, inputs=("Height",),
            parameters=(
                f("strength", "Strength", "float", 8.0, 0.0, 100.0, 0.25, animatable=True),
                f("invert_y", "Invert Green/Y", "bool", False),
            ),
            description="Convert height to a seamless tangent-space normal map.",
            accent="#699f70", tags=("normal map", "bump", "tile"),
            gpu_kernel="height_to_normal.wgsl",
        ),
        NodeDefinition(
            "convert.extract_channel", "Extract Channels", "Channels", eval_extract_channel, inputs=("Image",),
            parameters=(f("channel", "Preview channel", "enum", "Red", options=("Red", "Green", "Blue", "Alpha")),),
            accent="#4f9e91", tags=("rgba", "split"),
            output_format="r16f", outputs=("R", "G", "B", "A"),
            gpu_kernel="extract_channel.wgsl",
        ),
        NodeDefinition(
            "convert.channel_pack", "Channel Pack", "Channels", eval_channel_pack,
            inputs=("Red", "Green", "Blue", "Alpha"),
            parameters=(
                f("output_data_type", "Output data type", "enum", "Colour", options=("Colour", "Vector / Normal")),
            ),
            description="Pack four greyscale inputs into RGBA and explicitly declare whether the result is colour or vector/normal data.", accent="#4f9e91",
            tags=("rgba", "orm", "mask packing", "normal map", "vector"),
            gpu_kernel="channel_pack.wgsl",
        ),

        NodeDefinition(
            "animation.flipbook_decode", "Flipbook Decode", "Animation", eval_flipbook_decode,
            inputs=("Sheet", "Phase"),
            input_kinds=(("Sheet", "image"), ("Phase", "scalar")),
            parameters=(
                f("inherit_layout", "Inherit Flipbook Generator", "bool", True, description="When connected directly to Flipbook Generator, inherit its frame range and layout metadata."),
                f("playback_mode", "Playback", "enum", "Source FPS", options=("Source FPS", "Fit to Document Loop", "One Cell per Timeline Frame"), description="A connected Phase socket overrides this setting."),
                f("source_fps", "Source FPS", "float", 30.0, 0.1, 240.0, 0.1, description="Playback rate of an imported flipbook atlas."),
                f("layout", "Layout", "enum", "4 × 4", options=("2 × 2", "4 × 4", "8 × 8", "Custom")),
                f("columns", "Custom columns", "int", 4, 1, 64, 1),
                f("rows", "Custom rows", "int", 4, 1, 64, 1),
                f("use_full_grid", "Use full grid", "bool", True),
                f("frame_count", "Frame count", "int", 16, 1, 4096, 1),
                f("start_frame", "Start cell", "int", 0, 0, 4095, 1),
                f("order", "Playback order", "enum", "Left to Right, Top to Bottom", options=("Left to Right, Top to Bottom", "Top to Bottom, Left to Right")),
                f("padding", "Cell padding", "int", 0, 0, 64, 1),
                f("phase_offset", "Phase offset", "float", 0.0, -1000.0, 1000.0, 0.01, animatable=True),
                f("reverse", "Reverse", "bool", False),
                f("ping_pong", "Ping-pong", "bool", False),
            ),
            description="Decode and animate a flipbook atlas. Imported sheets play at Source FPS by default; a connected Phase input takes control.",
            accent="#d05e91", tags=("sheet decode", "sprite sheet", "atlas", "animation", "preview"),
            output_format="rgba16f", gpu_kernel="flipbook_decode.wgsl", uses_time=True,
        ),
        NodeDefinition(
            "material.pbr", "Material", "Materials", None,
            inputs=(
                "Base Colour", "Emissive", "Normal", "Height", "Ambient Occlusion",
                "Metallic", "Roughness", "Specular Level", "Opacity", "Geometry",
            ),
            parameters=(
                f(
                    "name", "Material name", "string", "Material",
                    description="Name shown in the Material node and 3D Preview panel.", group="Material", group_order=0,
                ),
                f(
                    "surface_mode", "Surface mode", "enum", "Opaque", options=SURFACE_MODES,
                    description="How opacity is interpreted by the preview material.", group="Material", group_order=0,
                ),
                f(
                    "cutout_threshold", "Cutout threshold", "float", 0.5, 0.0, 1.0, 0.01,
                    description="Pixels below this opacity are discarded in Alpha Cutout mode.",
                    group="Material", group_order=0,
                    visible_when=(("surface_mode", ("Alpha Cutout",)),),
                ),
                f(
                    "two_sided", "Two-sided", "bool", False,
                    description="Render both sides of preview geometry.", group="Material", group_order=0,
                ),
                f(
                    "emissive_intensity", "Emissive intensity", "float", 1.0, 0.0, 100.0, 0.05,
                    description="Multiplier applied to the Emissive input.", group="Material", group_order=0,
                ),
                f(
                    "normal_strength", "Normal / slope strength", "float", 1.0, 0.0, 20.0, 0.05,
                    description="Strength shared by connected normals and height-derived slope normals.",
                    group="Normals", group_order=10,
                ),
                f(
                    "normal_y", "Normal Y convention", "enum", "OpenGL (+Y)",
                    options=("OpenGL (+Y)", "DirectX (-Y)"), group="Normals", group_order=10,
                ),
                f(
                    "derive_normals", "Derive normals from height", "bool", True,
                    description="Use local height slope for shading in addition to any connected normal map.",
                    group="Normals", group_order=10,
                ),
            ),
            description=(
                "Define a reusable PBR material once, preview it in 3D, and feed one or more Texture Set Output nodes. "
                "An optional Geometry input overrides the viewport preview mesh for this material; displacement, lighting, background and preview-quality controls remain in the viewport."
            ),
            accent="#b06ee8", tags=("material", "pbr", "terrain", "displacement", "preview"),
            output_name="Material",
            output_kinds=(("Material", "material"),),
        ),
        NodeDefinition(
            "material.blend", "Material Blend", "Materials", None,
            inputs=("Background Material", "Foreground Material", "Mask"),
            input_kinds=(("Background Material", "material"), ("Foreground Material", "material"), ("Mask", "grayscale")),
            parameters=(
                f("name", "Material name", "string", "Material Blend", group="Material", group_order=0),
                f("amount", "Amount", "float", 1.0, 0.0, 1.0, 0.01, animatable=True, group="Blend", group_order=10,
                  description="Overall foreground coverage after the connected mask."),
                f("invert_mask", "Invert Mask", "bool", False, group="Blend", group_order=10),
                f("blend_method", "Blend Method", "enum", "Standard", options=("Standard", "Height Aware"), group="Blend", group_order=10),
                f("use_foreground_opacity", "Use Foreground Opacity as Coverage", "bool", False, group="Blend", group_order=10,
                  description="Multiply layer coverage by the foreground material's Opacity channel."),
                f("height_influence", "Height Influence", "float", 0.5, 0.0, 2.0, 0.01, animatable=True,
                  group="Height-Aware Blend", group_order=20, visible_when=(("blend_method", ("Height Aware",)),)),
                f("transition_softness", "Transition Softness", "float", 0.10, 0.001, 0.5, 0.001, animatable=True,
                  group="Height-Aware Blend", group_order=20, visible_when=(("blend_method", ("Height Aware",)),)),
                f("height_bias", "Height Bias", "float", 0.0, -1.0, 1.0, 0.01, animatable=True,
                  group="Height-Aware Blend", group_order=20, visible_when=(("blend_method", ("Height Aware",)),),
                  description="Positive values favour the foreground; negative values favour the background."),
                f("settings_source", "Material Settings Source", "enum", "Background", options=("Background", "Foreground"),
                  group="Material", group_order=0),
                f("normal_handling", "Normal Handling", "enum", "Crossfade", options=("Crossfade", "Combine Detail"),
                  group="Advanced Channels", group_order=90),
                f("height_handling", "Height Handling", "enum", "Blend",
                  options=("Blend", "Add Foreground Detail", "Maximum", "Minimum"), group="Advanced Channels", group_order=90),
                f("emissive_handling", "Emissive Handling", "enum", "Blend", options=("Blend", "Add"),
                  group="Advanced Channels", group_order=90),
            ),
            description=(
                "Layer complete PBR materials through one mask. Standard blending is predictable; Height Aware blending "
                "lets relative surface height interlock material boundaries without unpacking nine texture wires."
            ),
            accent="#b06ee8", tags=("material", "layer", "blend", "height blend", "pbr"),
            output_name="Material", output_kinds=(("Material", "material"),),
        ),
        NodeDefinition(
            "material.override", "Material Override", "Materials", None,
            inputs=(
                "Material", "Mask", "Base Colour", "Emissive", "Normal", "Height", "Ambient Occlusion",
                "Metallic", "Roughness", "Specular Level", "Opacity",
            ),
            input_kinds=(
                ("Material", "material"), ("Mask", "grayscale"), ("Base Colour", "color"), ("Emissive", "color"),
                ("Normal", "vector"), ("Height", "grayscale"), ("Ambient Occlusion", "grayscale"),
                ("Metallic", "grayscale"), ("Roughness", "grayscale"), ("Specular Level", "grayscale"),
                ("Opacity", "grayscale"),
            ),
            parameters=(
                f("name", "Material name", "string", "Material Override", group="Material", group_order=0),
                f("amount", "Amount", "float", 1.0, 0.0, 1.0, 0.01, animatable=True, group="Override", group_order=10),
                f("invert_mask", "Invert Mask", "bool", False, group="Override", group_order=10),
                f("normal_handling", "Normal Handling", "enum", "Replace", options=("Replace", "Combine Detail"),
                  group="Channel Handling", group_order=20),
                f("height_handling", "Height Handling", "enum", "Replace", options=("Replace", "Add", "Maximum", "Minimum"),
                  group="Channel Handling", group_order=20),
                f("emissive_handling", "Emissive Handling", "enum", "Replace", options=("Replace", "Add"),
                  group="Channel Handling", group_order=20),
                f("remove_base_colour", "Remove Base Colour", "bool", False, group="Remove Channels", group_order=80),
                f("remove_emissive", "Remove Emissive", "bool", False, group="Remove Channels", group_order=80),
                f("remove_normal", "Remove Normal", "bool", False, group="Remove Channels", group_order=80),
                f("remove_height", "Remove Height", "bool", False, group="Remove Channels", group_order=80),
                f("remove_ambient_occlusion", "Remove Ambient Occlusion", "bool", False, group="Remove Channels", group_order=80),
                f("remove_metallic", "Remove Metallic", "bool", False, group="Remove Channels", group_order=80),
                f("remove_roughness", "Remove Roughness", "bool", False, group="Remove Channels", group_order=80),
                f("remove_specular_level", "Remove Specular Level", "bool", False, group="Remove Channels", group_order=80),
                f("remove_opacity", "Remove Opacity", "bool", False, group="Remove Channels", group_order=80),
                f("override_material_settings", "Override Material Settings", "bool", False, group="Material Settings", group_order=90),
                f("surface_mode", "Surface mode", "enum", "Opaque", options=SURFACE_MODES, group="Material Settings", group_order=90,
                  visible_when=(("override_material_settings", (True,)),)),
                f("cutout_threshold", "Cutout threshold", "float", 0.5, 0.0, 1.0, 0.01, group="Material Settings", group_order=90,
                  visible_when=(("override_material_settings", (True,)), ("surface_mode", ("Alpha Cutout",)))),
                f("two_sided", "Two-sided", "bool", False, group="Material Settings", group_order=90,
                  visible_when=(("override_material_settings", (True,)),)),
                f("emissive_intensity", "Emissive intensity", "float", 1.0, 0.0, 100.0, 0.05, group="Material Settings", group_order=90,
                  visible_when=(("override_material_settings", (True,)),)),
                f("normal_strength", "Normal / slope strength", "float", 1.0, 0.0, 20.0, 0.05, group="Material Settings", group_order=90,
                  visible_when=(("override_material_settings", (True,)),)),
                f("normal_y", "Normal Y convention", "enum", "OpenGL (+Y)", options=("OpenGL (+Y)", "DirectX (-Y)"),
                  group="Material Settings", group_order=90, visible_when=(("override_material_settings", (True,)),)),
                f("derive_normals", "Derive normals from height", "bool", True, group="Material Settings", group_order=90,
                  visible_when=(("override_material_settings", (True,)),)),
            ),
            description=(
                "Replace, combine or remove selected channels while preserving every untouched part of a complete material. "
                "A connected mask affects only channels that are actually overridden."
            ),
            accent="#b06ee8", tags=("material", "override", "replace", "channels", "pbr"),
            output_name="Material", output_kinds=(("Material", "material"),),
        ),
        NodeDefinition(
            "material.channels", "Material Channels", "Materials", None,
            inputs=("Material",), input_kinds=(("Material", "material"),),
            outputs=(
                "Base Colour", "Emissive", "Normal", "Height", "Ambient Occlusion",
                "Metallic", "Roughness", "Specular Level", "Opacity",
            ),
            output_kinds=(
                ("Base Colour", "color"), ("Emissive", "color"), ("Normal", "vector"), ("Height", "grayscale"),
                ("Ambient Occlusion", "grayscale"), ("Metallic", "grayscale"), ("Roughness", "grayscale"),
                ("Specular Level", "grayscale"), ("Opacity", "grayscale"),
            ),
            description=(
                "Expose authored channels from a complete material only where they are needed. Missing channels resolve to "
                "their semantic defaults, while unused outputs perform no work."
            ),
            accent="#b06ee8", tags=("material", "channels", "breakout", "split", "unpack", "pbr"),
            default_image_kind="color",
        ),
        NodeDefinition(
            "material.switch", "Material Switch", "Materials", None,
            inputs=("Material A", "Material B", "Selection"),
            input_kinds=(("Material A", "material"), ("Material B", "material"), ("Selection", "scalar")),
            parameters=(
                f("selected_material", "Selected Material", "enum", "A", options=("A", "B"), group="Switch", group_order=10),
                f("threshold", "Threshold", "float", 0.5, -1000000.0, 1000000.0, 0.01, animatable=True,
                  group="Switch", group_order=10, slider_minimum=0.0, slider_maximum=1.0,
                  description="A connected Selection signal chooses B at or above this value and A below it."),
            ),
            description=(
                "Select one complete material without crossfading. The unselected branch is not evaluated, including when "
                "Selection is driven by an animated scalar signal."
            ),
            accent="#b06ee8", tags=("material", "switch", "select", "branch", "pbr"),
            output_name="Material", output_kinds=(("Material", "material"),),
        ),
        NodeDefinition(
            "output.image", "Single Image Output", "Inputs & Outputs", eval_output, inputs=("Image",),
            parameters=(
                f("name", "Output name", "string", "Output", group="Output", group_order=0),
                f("export_enabled", "Include in batch export", "bool", True, group="Output", group_order=0),
                f("export_filename", "File name", "string", "{output}", description="Supports {output}, {width} and {height} tokens.", group="Output", group_order=0),
                f("export_preset", "Export preset", "enum", "Auto from data type", options=("Auto from data type", "Colour / sRGB", "Linear Data", "Normal Map (OpenGL +Y)", "Normal Map (DirectX -Y)", "Custom"), group="Encoding", group_order=10,
                  description="Auto follows the connected semantic type. Colour is sRGB encoded; Greyscale, Vector/Normal and packed data preserve linear numeric values."),
                f("export_format", "Format", "enum", "PNG", options=("PNG", "TGA", "R16"), group="Encoding", group_order=10, visible_when=(("export_preset", ("Custom",)),)),
                f("export_bit_depth", "Bit depth", "enum", "8", options=("8", "16"), group="Encoding", group_order=10, visible_when=(("export_preset", ("Custom",)),)),
                f("export_channels", "Channels", "enum", "Auto", options=("Auto", "Grayscale", "RGB", "RGBA"), group="Encoding", group_order=10, visible_when=(("export_preset", ("Custom",)),)),
                f("export_source_channel", "Grayscale source", "enum", "Luminance", options=("Luminance", "Red", "Green", "Blue", "Alpha"), group="Encoding", group_order=10, visible_when=(("export_preset", ("Custom",)), ("export_channels", ("Grayscale",)))),
                f("export_encoding", "Colour encoding", "enum", "Auto", options=("Auto", "Linear", "sRGB"), group="Encoding", group_order=10, visible_when=(("export_preset", ("Custom",)),),
                  description="sRGB applies the display transfer and embeds sRGB metadata. Linear preserves numeric channels and writes no colour-profile chunk."),
                f("export_flip_green", "Flip Green / Y", "bool", False, group="Encoding", group_order=10, visible_when=(("export_preset", ("Custom",)),)),
                f("export_invert", "Invert colour / value", "bool", False, group="Encoding", group_order=10, visible_when=(("export_preset", ("Custom",)),)),
                f("export_resolution", "Resolution", "enum", "Document", options=("Document", "256 × 256", "512 × 512", "1024 × 1024", "2048 × 2048", "4096 × 4096", "8192 × 8192", "Custom"), group="Resolution", group_order=20),
                f("export_width", "Custom width", "int", 1024, 1, 16384, 1, group="Resolution", group_order=20, visible_when=(("export_resolution", ("Custom",)),)),
                f("export_height", "Custom height", "int", 1024, 1, 16384, 1, group="Resolution", group_order=20, visible_when=(("export_resolution", ("Custom",)),)),
            ),
            description="A named single-image export endpoint with its own format, colour handling, file-name template and resolution.", accent="#d7a449",
            tags=("export", "final", "png", "tga", "normal map"),
            gpu_kernel="image_output.wgsl",
        ),
        NodeDefinition(
            "output.texture_set", "Texture Set Output", "Inputs & Outputs", None,
            inputs=("Material",),
            input_kinds=(("Material", "material"),),
            parameters=(
                f("name", "Texture set name", "string", "Material", group="Output", group_order=0),
                f("export_enabled", "Include in batch export", "bool", True, group="Output", group_order=0),
                f("export_filename", "File name", "string", "{set}_{map}", description="Supports {set}, {map}, {width} and {height} tokens.", group="Output", group_order=0),
                f("export_preset", "Export template", "enum", "Generic PBR Separate", options=("Generic PBR Separate", "Unreal ORM", "Unity HDRP Mask Map", "Godot ORM", "VFX RGBA Masks", "Custom Template"), description="Choose a built-in production layout or customise the exact output files and RGBA channel assignments.", group="Packing", group_order=10),
                f("normal_convention", "Normal convention", "enum", "OpenGL (+Y)", options=("OpenGL (+Y)", "DirectX (-Y)"), description="Flips the exported Green/Y channel when DirectX is selected.", group="Packing", group_order=10),
                f("texture_format", "Image format", "enum", "PNG", options=("PNG", "TGA"), description="TGA exports are always 8-bit; PNG supports the selected colour and scalar depths.", group="Packing", group_order=10),
                f("colour_bit_depth", "Colour bit depth", "enum", "8", options=("8", "16"), group="Packing", group_order=10),
                f("data_bit_depth", "Scalar-map bit depth", "enum", "16", options=("8", "16"), group="Packing", group_order=10),
                f("height_format", "Height format", "enum", "PNG 16-bit", options=("PNG 16-bit", "Raw R16"), group="Packing", group_order=10),
                f("export_resolution", "Resolution", "enum", "Document", options=("Document", "256 × 256", "512 × 512", "1024 × 1024", "2048 × 2048", "4096 × 4096", "8192 × 8192", "Custom"), group="Resolution", group_order=20),
                f("export_width", "Custom width", "int", 1024, 1, 16384, 1, group="Resolution", group_order=20, visible_when=(("export_resolution", ("Custom",)),)),
                f("export_height", "Custom height", "int", 1024, 1, 16384, 1, group="Resolution", group_order=20, visible_when=(("export_resolution", ("Custom",)),)),
            ),
            description="Export a complete PBR texture set through reusable, editable file and channel-packing templates.",
            accent="#c7863c", tags=("export", "material", "pbr", "orm", "unity", "unreal", "texture set"), terminal=True,
        ),
        NodeDefinition(
            "output.flipbook", "Flipbook Generator", "Animation", eval_output, inputs=("Image",),
            parameters=(
                f("name", "Output name", "string", "Flipbook"),
                f("layout", "Layout", "enum", "8 × 8", options=("2 × 2", "4 × 4", "8 × 8", "Custom")),
                f("columns", "Custom columns", "int", 8, 1, 64, 1),
                f("rows", "Custom rows", "int", 8, 1, 64, 1),
                f("use_full_grid", "Use full grid", "bool", True),
                f("frame_count", "Frame count", "int", 64, 1, 4096, 1),
                f("source_range", "Source range", "enum", "Document Loop", options=("Document Loop", "Entire Document", "Custom Frame Range")),
                f("sampling", "Sampling", "enum", "Evenly Across Range", options=("Evenly Across Range", "Consecutive Timeline Frames")),
                f("include_end_frame", "Include loop endpoint", "bool", False),
                f("start_frame", "Custom start frame", "int", 0, 0, 100000, 1),
                f("end_frame", "Custom end frame", "int", 63, 0, 100000, 1),
                f("frame_step", "Consecutive frame step", "int", 1, 1, 1000, 1),
                f("padding", "Cell padding", "int", 0, 0, 64, 1),
                f("background", "Background", "color", "#00000000"),
            ),
            description="Sample a timeline range independently of FPS and assemble a flipbook atlas that can be previewed or exported through Single Image Output.",
            accent="#e07d4f", tags=("animation", "sprite sheet", "sequence", "loop"),
            gpu_kernel="image_output.wgsl",
        ),
    ]
    typed: dict[str, dict[str, Any]] = {
        "filter.invert": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
        "filter.levels": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
        "filter.histogram_range": dict(input_kinds=(("Image", "grayscale"),), output_kinds=(("Image", "grayscale"),), default_image_kind="grayscale"),
        "filter.histogram_shift": dict(input_kinds=(("Image", "grayscale"),), output_kinds=(("Image", "grayscale"),), default_image_kind="grayscale"),
        "filter.histogram_scan": dict(input_kinds=(("Image", "grayscale"),), output_kinds=(("Image", "grayscale"),), default_image_kind="grayscale"),
        "filter.histogram_select": dict(input_kinds=(("Image", "grayscale"),), output_kinds=(("Image", "grayscale"),), default_image_kind="grayscale"),
        "filter.brightness": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
        "filter.contrast": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
        "filter.exposure": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
        "filter.gamma": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
        "filter.posterize": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
        "filter.clamp": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
        "filter.hue_shift": dict(input_kinds=(("Colour", "color"),), output_kinds=(("Image", "color"),), default_image_kind="color"),
        "filter.saturation": dict(input_kinds=(("Colour", "color"),), output_kinds=(("Image", "color"),), default_image_kind="color"),
        "filter.lightness": dict(input_kinds=(("Colour", "color"),), output_kinds=(("Image", "color"),), default_image_kind="color"),
        "filter.curve": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
        "filter.auto_levels": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
        "filter.highpass": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
        "filter.edge_detect": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "grayscale"),), type_policy="accept_any_input", default_image_kind="grayscale"),
        "filter.fxaa": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
        "filter.threshold": dict(input_kinds=(("Image", "grayscale"),), output_kinds=(("Image", "grayscale"),), default_image_kind="grayscale"),
        "filter.blur": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
        "filter.directional_blur": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
        "filter.radial_blur": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
        "filter.zoom_blur": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
        "filter.anisotropic_blur": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
        "filter.non_uniform_blur_grayscale": dict(input_kinds=(("Image", "grayscale"), ("Blur Map", "grayscale")), output_kinds=(("Image", "grayscale"),), default_image_kind="grayscale"),
        "filter.slope_blur_grayscale": dict(input_kinds=(("Image", "grayscale"), ("Slope", "grayscale")), output_kinds=(("Image", "grayscale"),), default_image_kind="grayscale"),
        "transform.crop": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
        "transform.auto_crop": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
        "transform.basic": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
        "transform.safe": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
        "math.blend": dict(input_kinds=(("Foreground", "image_any"), ("Background", "image_any"), ("Opacity", "grayscale")), output_kinds=(("Image", "image_any"),), type_policy="blend_match", default_image_kind="grayscale"),
        "convert.color_to_grayscale": dict(input_kinds=(("Colour", "color"),), output_kinds=(("Image", "grayscale"),), default_image_kind="grayscale"),
        "convert.color_to_vector": dict(input_kinds=(("Image", "color"),), output_kinds=(("Image", "vector"),), default_image_kind="vector"),
        "convert.vector_to_color": dict(input_kinds=(("Image", "vector"),), output_kinds=(("Image", "color"),), default_image_kind="color"),
        "convert.gradient_map": dict(input_kinds=(("Image", "grayscale"),), output_kinds=(("Image", "color"),), default_image_kind="color"),
        "convert.height_normal": dict(input_kinds=(("Height", "grayscale"),), output_kinds=(("Image", "vector"),), default_image_kind="vector"),
        "convert.extract_channel": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("R", "grayscale"), ("G", "grayscale"), ("B", "grayscale"), ("A", "grayscale")), type_policy="accept_any_input", default_image_kind="grayscale"),
        "convert.channel_pack": dict(input_kinds=(("Red", "grayscale"), ("Green", "grayscale"), ("Blue", "grayscale"), ("Alpha", "grayscale")), output_kinds=(("Image", "image_any"),), type_policy="parameter_output", default_image_kind="color"),
        "animation.flipbook_decode": dict(input_kinds=(("Sheet", "image_any"), ("Phase", "scalar")), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Sheet", default_image_kind="color"),
        "material.pbr": dict(
            input_kinds=(("Base Colour", "color"), ("Emissive", "color"), ("Normal", "vector"), ("Height", "grayscale"),
                         ("Ambient Occlusion", "grayscale"), ("Metallic", "grayscale"), ("Roughness", "grayscale"),
                         ("Specular Level", "grayscale"), ("Opacity", "grayscale"), ("Geometry", "geometry")),
            output_kinds=(("Material", "material"),),
            default_image_kind="color"
        ),
        "output.image": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
        "output.texture_set": dict(
            input_kinds=(("Material", "material"),),
            default_image_kind="color",
        ),
        "output.flipbook": dict(input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),), type_policy="preserve_primary", primary_input="Image"),
    }
    for definition in definitions:
        registry.register(replace(definition, **typed.get(definition.type_id, {})))
