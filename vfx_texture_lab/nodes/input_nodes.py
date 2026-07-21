from __future__ import annotations

import base64
import io
import re
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PIL import Image

from .base import EvalContext, ImageArray, NodeDefinition, ParameterSpec
from .registry import NodeRegistry
from ..canvas_node import canvas_array_from_params, canvas_rgba_output, ensure_canvas_parameters, resize_canvas_array


def _srgb_to_linear(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, 0.0, 1.0)
    return np.where(values <= 0.04045, values / 12.92, np.power((values + 0.055) / 1.055, 2.4))


def _source_bytes_or_path(params: Mapping[str, Any]):
    embedded = str(params.get("_embedded_data", ""))
    if embedded:
        return io.BytesIO(base64.b64decode(embedded))
    path = Path(str(params.get("path", ""))).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Image file not found: {path}")
    return path



_NORMAL_NAME_PATTERN = re.compile(
    r"(?:^|[._\-\s])(?:normal|normals|normalmap|normal_map|nrm|norm|nor)(?:$|[._\-\s])",
    re.IGNORECASE,
)


def _normal_filename_hint(params: Mapping[str, Any]) -> bool:
    path_text = str(params.get("path", "")).strip()
    if not path_text:
        return False
    stem = Path(path_text).stem
    padded = f"_{stem}_"
    return bool(_NORMAL_NAME_PATTERN.search(padded))


def _normal_pixel_hint(image: Image.Image) -> bool:
    """Conservatively recognise a conventional +Z tangent-space normal map."""
    try:
        sample = image.convert("RGB")
        sample.thumbnail((128, 128), Image.Resampling.BILINEAR)
        values = np.asarray(sample, dtype=np.float32) / 255.0
    except Exception:
        return False
    if values.size == 0:
        return False
    rgb = values.reshape(-1, 3)
    # Ignore almost-black/transparent-looking padding that can otherwise skew
    # unit-vector statistics on atlas textures.
    useful = np.max(rgb, axis=1) > 0.08
    if np.count_nonzero(useful) >= max(32, rgb.shape[0] // 8):
        rgb = rgb[useful]
    decoded = rgb * 2.0 - 1.0
    lengths = np.linalg.norm(decoded, axis=1)
    positive_z = float(np.mean(decoded[:, 2] > 0.05))
    plausible_length = float(np.mean((lengths > 0.65) & (lengths < 1.35)))
    mean_length_error = float(np.mean(np.abs(lengths - 1.0)))
    blue_mean = float(np.mean(rgb[:, 2]))
    blue_median = float(np.median(rgb[:, 2]))
    rg_mean = np.mean(rgb[:, :2], axis=0)
    rg_centred = bool(np.all((rg_mean > 0.28) & (rg_mean < 0.72)))
    return bool(
        positive_z >= 0.90
        and plausible_length >= 0.78
        and mean_length_error <= 0.24
        and blue_mean >= 0.56
        and blue_median >= 0.54
        and rg_centred
    )


def _detected_image_kind(image: Image.Image, params: Mapping[str, Any], native_kind: str) -> tuple[str, str]:
    if native_kind != "color":
        return native_kind, ""
    filename_hint = _normal_filename_hint(params)
    pixel_hint = _normal_pixel_hint(image)
    if filename_hint or pixel_hint:
        if filename_hint and pixel_hint:
            reason = "filename and tangent-space pixel analysis"
        elif filename_hint:
            reason = "normal-map filename"
        else:
            reason = "tangent-space pixel analysis"
        return "vector", reason
    return native_kind, ""


def _native_mode_info(image: Image.Image) -> tuple[str, str, int]:
    mode = image.mode
    if mode == "1":
        return "grayscale", "8-bit", 1
    if mode in ("L", "LA"):
        return "grayscale", "8-bit", 1 if mode == "L" else 2
    if mode.startswith("I;16"):
        return "grayscale", "16-bit", 1
    if mode == "I":
        extrema = image.getextrema()
        maximum = int(extrema[1]) if isinstance(extrema, tuple) else 65535
        return "grayscale", "16-bit" if maximum <= 65535 else "32-bit float", 1
    if mode == "F":
        return "grayscale", "32-bit float", 1
    if mode in ("RGB", "RGBA", "RGBX"):
        return "color", "8-bit", 3 if mode == "RGB" else 4
    # Palette, CMYK and other Pillow modes are converted to ordinary colour.
    return "color", "8-bit", 4


def refresh_image_metadata(params: dict[str, Any]) -> None:
    try:
        with Image.open(_source_bytes_or_path(params)) as image:
            native_kind, precision, channels = _native_mode_info(image)
            detected_kind, normal_reason = _detected_image_kind(image, params, native_kind)
            params["_native_kind"] = native_kind
            params["_detected_kind"] = detected_kind
            if normal_reason:
                params["_normal_detection"] = normal_reason
            else:
                params.pop("_normal_detection", None)
            params["_source_precision"] = precision
            params["_source_channels"] = channels
            params["_source_mode"] = image.mode
            params["_source_size"] = [int(image.width), int(image.height)]
            params.pop("_source_error", None)
    except Exception as exc:
        params["_native_kind"] = "color"
        params["_detected_kind"] = "color"
        params.setdefault("_source_precision", "8-bit")
        params.pop("_normal_detection", None)
        params["_source_error"] = str(exc)


def _normalise_native_array(image: Image.Image) -> tuple[np.ndarray, str, str, int]:
    detected_kind, precision, channels = _native_mode_info(image)
    mode = image.mode

    if mode == "1":
        scalar = np.asarray(image.convert("L"), dtype=np.float32) / 255.0
        rgba = np.stack((scalar, scalar, scalar, np.ones_like(scalar)), axis=2)
        return rgba, detected_kind, precision, channels

    if mode in ("L", "LA"):
        raw = np.asarray(image, dtype=np.float32) / 255.0
        if raw.ndim == 2:
            scalar = raw
            alpha = np.ones_like(scalar)
        else:
            scalar = raw[..., 0]
            alpha = raw[..., 1]
        return np.stack((scalar, scalar, scalar, alpha), axis=2), detected_kind, precision, channels

    if mode.startswith("I;16") or mode == "I":
        raw = np.asarray(image)
        if raw.dtype.kind in "ui":
            # Pillow commonly exposes 16-bit PNG as signed int32 mode I. Use
            # the actual range instead of destructively converting to RGBA8.
            maximum = 65535.0 if float(np.max(raw, initial=0)) <= 65535.0 else float(np.iinfo(raw.dtype).max)
            scalar = raw.astype(np.float32) / max(maximum, 1.0)
        else:
            scalar = raw.astype(np.float32)
        scalar = np.clip(scalar, 0.0, 1.0)
        return np.stack((scalar, scalar, scalar, np.ones_like(scalar)), axis=2), detected_kind, precision, channels

    if mode == "F":
        scalar = np.clip(np.asarray(image, dtype=np.float32), 0.0, 1.0)
        return np.stack((scalar, scalar, scalar, np.ones_like(scalar)), axis=2), detected_kind, precision, channels

    # Preserve native high-bit RGB arrays when Pillow exposes them. Ordinary
    # PNG/JPEG/TGA files arrive here as uint8.
    raw = np.asarray(image)
    if raw.ndim == 3 and raw.shape[2] in (3, 4) and raw.dtype == np.uint16:
        colour = raw.astype(np.float32) / 65535.0
        precision = "16-bit"
        if raw.shape[2] == 3:
            colour = np.concatenate((colour, np.ones((*colour.shape[:2], 1), dtype=np.float32)), axis=2)
        return colour, "color", precision, raw.shape[2]

    rgba = np.asarray(image.convert("RGBA"), dtype=np.float32) / 255.0
    return rgba, "color", "8-bit", 4


def _decode_source(params: Mapping[str, Any]) -> tuple[np.ndarray, str, str]:
    with Image.open(_source_bytes_or_path(params)) as image:
        image.load()
        source, native_kind, source_precision, _channels = _normalise_native_array(image)
        detected_kind, _normal_reason = _detected_image_kind(image, params, native_kind)

    selected = str(params.get("data_type", "Auto"))
    kind = {
        "Greyscale": "grayscale",
        "Colour": "color",
        "Vector / Normal": "vector",
    }.get(selected, detected_kind)

    interpretation = str(params.get("colour_space", "Auto"))
    if interpretation == "Auto":
        interpretation = "sRGB" if kind == "color" else "Linear"
    if interpretation == "sRGB" and kind == "color":
        source = source.copy()
        source[..., :3] = _srgb_to_linear(source[..., :3])

    if kind == "grayscale":
        # Explicitly convert colour files through luminance. Native single-channel
        # files are already replicated and remain exact.
        values = source[..., :3] @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        source = np.stack((values, values, values, source[..., 3]), axis=2)
    elif kind == "vector" and bool(params.get("flip_y", False)):
        source = source.copy()
        source[..., 1] = 1.0 - source[..., 1]
    return np.clip(source, 0.0, 1.0).astype(np.float32), kind, source_precision


def _sample_bilinear(source: np.ndarray, u: np.ndarray, v: np.ndarray, wrap: bool) -> np.ndarray:
    height, width, _ = source.shape
    if wrap:
        u = np.mod(u, 1.0)
        v = np.mod(v, 1.0)
    else:
        u = np.clip(u, 0.0, 1.0)
        v = np.clip(v, 0.0, 1.0)
    # Pixel-centred resampling. At matching source/document dimensions each
    # destination texel lands exactly on its corresponding source texel instead
    # of being unintentionally blended with neighbours.
    x = u * width - 0.5
    y = v * height - 0.5
    if wrap:
        x_floor = np.floor(x).astype(np.int64)
        y_floor = np.floor(y).astype(np.int64)
        tx = (x - x_floor)[..., None]
        ty = (y - y_floor)[..., None]
        x0 = np.mod(x_floor, width).astype(np.int32)
        y0 = np.mod(y_floor, height).astype(np.int32)
        x1 = (x0 + 1) % width
        y1 = (y0 + 1) % height
    else:
        x = np.clip(x, 0.0, max(width - 1, 0))
        y = np.clip(y, 0.0, max(height - 1, 0))
        x0 = np.floor(x).astype(np.int32)
        y0 = np.floor(y).astype(np.int32)
        x1 = np.minimum(x0 + 1, width - 1)
        y1 = np.minimum(y0 + 1, height - 1)
        tx = (x - x0)[..., None]
        ty = (y - y0)[..., None]
    top = source[y0, x0] * (1.0 - tx) + source[y0, x1] * tx
    bottom = source[y1, x0] * (1.0 - tx) + source[y1, x1] * tx
    return top * (1.0 - ty) + bottom * ty


def eval_image_input(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    source, _kind, _source_precision = _decode_source(params)
    source_h, source_w = source.shape[:2]
    y, x = np.mgrid[0 : context.height, 0 : context.width]
    u = (x.astype(np.float32) + 0.5) / max(context.width, 1)
    v = (y.astype(np.float32) + 0.5) / max(context.height, 1)
    fit = str(params.get("fit", "Stretch"))
    document_aspect = context.width / max(context.height, 1)
    source_aspect = source_w / max(source_h, 1)
    if fit == "Contain":
        if source_aspect > document_aspect:
            displayed_fraction = document_aspect / source_aspect
            v = (v - 0.5) / max(displayed_fraction, 1e-6) + 0.5
        else:
            displayed_fraction = source_aspect / document_aspect
            u = (u - 0.5) / max(displayed_fraction, 1e-6) + 0.5
    elif fit == "Cover":
        if source_aspect > document_aspect:
            crop_fraction = document_aspect / source_aspect
            u = (u - 0.5) * crop_fraction + 0.5
        else:
            crop_fraction = source_aspect / document_aspect
            v = (v - 0.5) * crop_fraction + 0.5

    result = _sample_bilinear(source, u, v, str(params.get("wrap", "Tile")) == "Tile")
    return np.clip(result, 0.0, 1.0).astype(np.float32)




def eval_grayscale_canvas(_inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext) -> ImageArray:
    safe = ensure_canvas_parameters(params)
    source = canvas_array_from_params(safe)
    if source.shape != (context.height, context.width):
        source = resize_canvas_array(source, context.width, context.height)
    return canvas_rgba_output(source)

def register_input_nodes(registry: NodeRegistry) -> None:
    f = ParameterSpec
    registry.register(
        NodeDefinition(
            "input.image",
            "Image Input",
            "Inputs & Outputs",
            eval_image_input,
            parameters=(
                f("path", "Image", "file", "", description="PNG, TGA, JPG, BMP, TIFF or WebP image file."),
                f("data_type", "Data type", "enum", "Auto", options=("Auto", "Greyscale", "Colour", "Vector / Normal")),
                f("colour_space", "Interpret as", "enum", "Auto", options=("Auto", "sRGB", "Linear")),
                f(
                    "flip_y", "Flip Green / Y", "bool", False,
                    description="Invert the encoded tangent-space Y channel (OpenGL ↔ DirectX).",
                    visible_when=(("data_type", ("Auto", "Vector / Normal")),),
                ),
                f("fit", "Fit", "enum", "Stretch", options=("Stretch", "Contain", "Cover")),
                f("wrap", "Outside UVs", "enum", "Tile", options=("Tile", "Clamp")),
                f("embedded", "Embed in project", "bool", False, description="Store the source file inside the .vfxgraph when saving."),
            ),
            description="Load native 8/16/32-bit texture data without destructive RGBA8 conversion.",
            accent="#d7a449",
            tags=("file", "texture", "import", "png", "tga", "16-bit", "normal map", "vector"),
            output_format="rgba16f",
            gpu_kernel=None,
            output_kinds=(("Image", "image_any"),),
            type_policy="image_input",
            default_image_kind="color",
        )
    )
    registry.register(
        NodeDefinition(
            "input.canvas",
            "Grayscale Canvas",
            "Inputs & Outputs",
            eval_grayscale_canvas,
            parameters=(
                f("canvas_width", "Canvas Width", "int", 1024, minimum=16, maximum=8192, step=1, group="Canvas", description="Native authored width for the canvas source."),
                f("canvas_height", "Canvas Height", "int", 1024, minimum=16, maximum=8192, step=1, group="Canvas", description="Native authored height for the canvas source."),
            ),
            description="Paint a native greyscale source texture directly inside the graph for masks, motes and hand-authored shapes.",
            accent="#a47ad9",
            tags=("paint", "mask", "canvas", "draw", "authoring", "input"),
            output_format="rgba16f",
            gpu_kernel=None,
            output_kinds=(("Image", "grayscale"),),
            type_policy="fixed",
            default_image_kind="grayscale",
        )
    )
