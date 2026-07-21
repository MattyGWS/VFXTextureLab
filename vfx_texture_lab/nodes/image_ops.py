from __future__ import annotations

import numpy as np

from .base import EvalContext, ImageArray


# Artist-facing spatial controls use a 512-pixel reference canvas.  The value
# shown in the Parameters panel therefore describes the familiar effect at the
# application's default preview size, while evaluation scales it with the
# current output resolution.  A value of 16 produces an 8-pixel footprint at
# 256, 16 pixels at 512, 32 pixels at 1024 and 64 pixels at 2048.
RELATIVE_PIXEL_REFERENCE = 512.0


def resolution_scale(context_or_width, height: int | None = None) -> float:
    """Return the uniform output-resolution scale relative to 512 pixels.

    Preview dimensions are derived from the document with one uniform scale, so
    the longest axis is the correct basis for square and non-square documents.
    The helper deliberately accepts both EvalContext/RenderContext-like objects
    and explicit dimensions so CPU and GPU paths share one convention.
    """
    if height is None and hasattr(context_or_width, "width"):
        width = int(getattr(context_or_width, "width"))
        height_value = int(getattr(context_or_width, "height"))
    else:
        width = int(context_or_width)
        height_value = int(height if height is not None else width)
    return max(float(max(width, height_value)), 1.0) / RELATIVE_PIXEL_REFERENCE


def relative_pixels(value: float | int, context_or_width, height: int | None = None) -> float:
    """Convert an authored relative-pixel value to current output pixels."""
    return float(value) * resolution_scale(context_or_width, height)


def relative_pixel_area(value: float | int, context_or_width, height: int | None = None) -> float:
    """Convert an authored 512-reference pixel area to current output area."""
    scale = resolution_scale(context_or_width, height)
    return float(value) * scale * scale


def empty_image(context: EvalContext, value: float = 0.0, alpha: float = 1.0) -> ImageArray:
    image = np.full((context.height, context.width, 4), value, dtype=np.float32)
    image[..., 3] = alpha
    return image


def ensure_rgba(image: ImageArray, context: EvalContext | None = None) -> ImageArray:
    array = np.asarray(image, dtype=np.float32)
    if array.ndim == 2:
        rgb = np.repeat(array[..., None], 3, axis=2)
        alpha = np.ones((*array.shape, 1), dtype=np.float32)
        return np.concatenate((rgb, alpha), axis=2)
    if array.ndim == 3 and array.shape[2] == 1:
        rgb = np.repeat(array, 3, axis=2)
        alpha = np.ones((*array.shape[:2], 1), dtype=np.float32)
        return np.concatenate((rgb, alpha), axis=2)
    if array.ndim == 3 and array.shape[2] == 3:
        alpha = np.ones((*array.shape[:2], 1), dtype=np.float32)
        return np.concatenate((array, alpha), axis=2)
    if array.ndim == 3 and array.shape[2] == 4:
        return array
    if context is not None:
        return empty_image(context)
    raise ValueError(f"Unsupported image shape: {array.shape}")


def luminance(image: ImageArray) -> np.ndarray:
    rgba = ensure_rgba(image)
    return (
        rgba[..., 0] * np.float32(0.2126)
        + rgba[..., 1] * np.float32(0.7152)
        + rgba[..., 2] * np.float32(0.0722)
    )


def grayscale_rgba(values: np.ndarray, alpha: float | np.ndarray = 1.0) -> ImageArray:
    values = np.clip(np.asarray(values, dtype=np.float32), 0.0, 1.0)
    rgb = np.repeat(values[..., None], 3, axis=2)
    if np.isscalar(alpha):
        a = np.full((*values.shape, 1), float(alpha), dtype=np.float32)
    else:
        a = np.asarray(alpha, dtype=np.float32)[..., None]
    return np.concatenate((rgb, a), axis=2)


def parse_hex_color(value: str) -> np.ndarray:
    text = value.strip().lstrip("#")
    if len(text) == 6:
        text += "ff"
    if len(text) != 8:
        return np.array([1.0, 1.0, 1.0, 1.0], dtype=np.float32)
    return np.array([int(text[i : i + 2], 16) / 255.0 for i in range(0, 8, 2)], dtype=np.float32)


def srgb_to_linear(values: np.ndarray) -> np.ndarray:
    """Convert display-sRGB channel values to linear-light graph values.

    Alpha is intentionally not handled here. Callers should convert RGB only
    and leave alpha as an ordinary linear coverage value.
    """
    source = np.clip(np.asarray(values, dtype=np.float32), 0.0, 1.0)
    return np.where(
        source <= 0.04045,
        source / 12.92,
        np.power((source + 0.055) / 1.055, 2.4),
    ).astype(np.float32, copy=False)


def linear_to_srgb(values: np.ndarray) -> np.ndarray:
    """Convert linear-light graph RGB values to display-sRGB channels.

    This is the inverse of :func:`srgb_to_linear`. Alpha and scalar data maps
    must remain untouched by callers.
    """
    source = np.clip(np.asarray(values, dtype=np.float32), 0.0, 1.0)
    return np.where(
        source <= 0.0031308,
        source * 12.92,
        1.055 * np.power(source, 1.0 / 2.4) - 0.055,
    ).astype(np.float32, copy=False)
