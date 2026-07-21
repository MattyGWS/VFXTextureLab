from __future__ import annotations

import base64
import io
from typing import Any, Mapping

import numpy as np
from PIL import Image

from .nodes.base import ImageArray

DEFAULT_CANVAS_WIDTH = 1024
DEFAULT_CANVAS_HEIGHT = 1024
DEFAULT_BACKGROUND_VALUE = 0.0


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _blank_array(width: int, height: int, background: float) -> np.ndarray:
    return np.full((max(int(height), 1), max(int(width), 1)), clamp01(background), dtype=np.float32)


def encode_canvas_array(array: np.ndarray) -> str:
    data = np.clip(np.asarray(array, dtype=np.float32), 0.0, 1.0)
    image = Image.fromarray(np.rint(data * 255.0).astype(np.uint8), mode="L")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def decode_canvas_array(data: str) -> np.ndarray:
    raw = base64.b64decode(data)
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        image = image.convert("L")
        return np.asarray(image, dtype=np.float32) / 255.0


def ensure_canvas_parameters(params: dict[str, Any] | Mapping[str, Any] | None) -> dict[str, Any]:
    base = dict(params or {})
    width = max(int(base.get("canvas_width", DEFAULT_CANVAS_WIDTH) or DEFAULT_CANVAS_WIDTH), 1)
    height = max(int(base.get("canvas_height", DEFAULT_CANVAS_HEIGHT) or DEFAULT_CANVAS_HEIGHT), 1)
    # Canvas authoring is opaque greyscale. Black is the sole clear/erase
    # value; older saved background values are retained only as harmless
    # compatibility data and normalised away on load.
    background = DEFAULT_BACKGROUND_VALUE
    base["canvas_width"] = width
    base["canvas_height"] = height
    base["background_value"] = background
    payload = str(base.get("_canvas_data", "") or "")
    if payload:
        try:
            array = decode_canvas_array(payload)
            if array.shape != (height, width):
                array = resize_canvas_array(array, width, height)
                base["_canvas_data"] = encode_canvas_array(array)
        except Exception:
            base["_canvas_data"] = encode_canvas_array(_blank_array(width, height, background))
    else:
        base["_canvas_data"] = encode_canvas_array(_blank_array(width, height, background))
    base.setdefault("_canvas_revision", 0)
    return base


def canvas_array_from_params(params: Mapping[str, Any]) -> np.ndarray:
    safe = ensure_canvas_parameters(params)
    payload = str(safe.get("_canvas_data", "") or "")
    if payload:
        try:
            return decode_canvas_array(payload)
        except Exception:
            pass
    return _blank_array(safe["canvas_width"], safe["canvas_height"], safe["background_value"])


def resize_canvas_array(array: np.ndarray, width: int, height: int) -> np.ndarray:
    width = max(int(width), 1)
    height = max(int(height), 1)
    source = np.clip(np.asarray(array, dtype=np.float32), 0.0, 1.0)
    if source.shape == (height, width):
        return source.copy()
    image = Image.fromarray(np.rint(source * 255.0).astype(np.uint8), mode="L")
    image = image.resize((width, height), Image.Resampling.BILINEAR)
    return np.asarray(image, dtype=np.float32) / 255.0


def canvas_rgba_output(array: np.ndarray) -> ImageArray:
    grayscale = np.clip(np.asarray(array, dtype=np.float32), 0.0, 1.0)
    alpha = np.ones_like(grayscale, dtype=np.float32)
    return np.stack((grayscale, grayscale, grayscale, alpha), axis=2).astype(np.float32)


def canvas_thumbnail_qimage_bytes(array: np.ndarray) -> bytes:
    image = Image.fromarray(np.rint(np.clip(array, 0.0, 1.0) * 255.0).astype(np.uint8), mode="L")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
