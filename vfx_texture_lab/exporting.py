from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Any

import numpy as np
from PIL import Image


@dataclass(slots=True)
class ExportOptions:
    format_name: str = "PNG"
    bit_depth: int = 8
    channels: str = "RGBA"
    source_channel: str = "Luminance"
    colour_encoding: str = "Linear"
    invert: bool = False
    flip_green: bool = False


def _linear_to_srgb(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, 0.0, 1.0)
    return np.where(values <= 0.0031308, values * 12.92, 1.055 * np.power(values, 1.0 / 2.4) - 0.055)


def _luminance(image: np.ndarray) -> np.ndarray:
    source = np.asarray(image, dtype=np.float32)
    if source.ndim == 2:
        return source
    if source.ndim != 3 or source.shape[2] < 1:
        raise ValueError(f"Invalid export image shape: {source.shape}")
    if source.shape[2] < 3:
        # One-channel template outputs are already scalar data. Two-channel
        # inputs are treated as luminance + alpha, matching common LA images.
        return source[..., 0]
    return source[..., 0] * 0.2126 + source[..., 1] * 0.7152 + source[..., 2] * 0.0722


def _export_component(source: np.ndarray, name: str) -> np.ndarray:
    if source.ndim == 2:
        return source
    if source.ndim != 3 or source.shape[2] < 1:
        raise ValueError(f"Invalid export image shape: {source.shape}")
    if name == "Luminance":
        return _luminance(source)
    index = {"Red": 0, "Green": 1, "Blue": 2, "Alpha": 3}.get(name, 0)
    if index == 3 and source.shape[2] < 4:
        # Images without an authored alpha channel are fully opaque.
        return np.ones(source.shape[:2], dtype=np.float32)
    return source[..., min(index, source.shape[2] - 1)]


def _expand_export_channels(source: np.ndarray, channels: int) -> np.ndarray:
    if source.ndim == 2:
        source = source[..., None]
    if source.ndim != 3 or source.shape[2] < 1:
        raise ValueError(f"Invalid export image shape: {source.shape}")
    if channels == 3:
        if source.shape[2] == 1:
            return np.repeat(source, 3, axis=2)
        if source.shape[2] == 2:
            return np.repeat(source[..., :1], 3, axis=2)
        return source[..., :3].copy()
    if channels == 4:
        if source.shape[2] >= 4:
            return source[..., :4].copy()
        rgb = _expand_export_channels(source, 3)
        alpha = (
            source[..., 1:2].copy()
            if source.shape[2] == 2
            else np.ones((*source.shape[:2], 1), dtype=np.float32)
        )
        return np.concatenate((rgb, alpha), axis=2)
    raise ValueError(f"Unsupported export channel count: {channels}")


def prepare_export_array(image: np.ndarray, options: ExportOptions) -> np.ndarray:
    source = np.clip(np.asarray(image, dtype=np.float32), 0.0, 1.0).copy()
    if source.ndim == 2:
        source = source[..., None]
    if options.flip_green and source.ndim == 3 and source.shape[2] >= 2:
        source[..., 1] = 1.0 - source[..., 1]
    if options.channels == "Grayscale":
        channel = _export_component(source, options.source_channel)
        output = channel[..., None]
    elif options.channels == "RGB":
        output = _expand_export_channels(source, 3)
    else:
        output = _expand_export_channels(source, 4)

    if options.invert:
        if output.shape[2] == 4:
            output[..., :3] = 1.0 - output[..., :3]
        else:
            output = 1.0 - output

    if options.colour_encoding == "sRGB":
        colour_channels = 1 if output.shape[2] == 1 else min(3, output.shape[2])
        output[..., :colour_channels] = _linear_to_srgb(output[..., :colour_channels])
    return np.clip(output, 0.0, 1.0)



def export_extension(format_name: str) -> str:
    return {"PNG": ".png", "TGA": ".tga", "R16": ".r16"}.get(str(format_name).upper(), ".png")


def scalar_channel(image: np.ndarray | None, default: float, channel: str = "Red") -> np.ndarray:
    if image is None:
        return np.asarray(default, dtype=np.float32)
    source = np.asarray(image, dtype=np.float32)
    index = {"Red": 0, "Green": 1, "Blue": 2, "Alpha": 3}.get(channel, 0)
    if source.ndim == 2:
        return source
    if source.ndim != 3:
        raise ValueError(f"Invalid packed export source: {source.shape}")
    index = min(index, source.shape[2] - 1)
    return source[..., index]


def pack_export_channels(
    width: int,
    height: int,
    *,
    red: np.ndarray | None = None,
    green: np.ndarray | None = None,
    blue: np.ndarray | None = None,
    alpha: np.ndarray | None = None,
    red_default: float = 0.0,
    green_default: float = 0.0,
    blue_default: float = 0.0,
    alpha_default: float = 1.0,
    invert_alpha: bool = False,
) -> np.ndarray:
    shape = (int(height), int(width))

    def full_or_channel(image: np.ndarray | None, default: float) -> np.ndarray:
        value = scalar_channel(image, default)
        if np.ndim(value) == 0:
            return np.full(shape, float(value), dtype=np.float32)
        value = np.asarray(value, dtype=np.float32)
        if value.shape != shape:
            raise ValueError(f"Packed source resolution {value.shape[::-1]} does not match {shape[::-1]}")
        return value

    r = full_or_channel(red, red_default)
    g = full_or_channel(green, green_default)
    b = full_or_channel(blue, blue_default)
    a = full_or_channel(alpha, alpha_default)
    if invert_alpha:
        a = 1.0 - a
    return np.clip(np.stack((r, g, b, a), axis=2), 0.0, 1.0).astype(np.float32)


def _binding_default(source_name: str, component: str, constant: float) -> float:
    if source_name == "Constant":
        return float(constant)
    from .material import MATERIAL_DEFAULT_VALUES

    values = MATERIAL_DEFAULT_VALUES.get(source_name, (0.0, 0.0, 0.0, 1.0))
    if component == "Luminance":
        return float(values[0] * 0.2126 + values[1] * 0.7152 + values[2] * 0.0722)
    index = {"Red": 0, "Green": 1, "Blue": 2, "Alpha": 3}.get(component, 0)
    return float(values[index])


def _binding_channel(image: np.ndarray, component: str) -> np.ndarray:
    source = np.asarray(image, dtype=np.float32)
    if source.ndim == 2:
        return source
    if source.ndim != 3:
        raise ValueError(f"Invalid template export source: {source.shape}")
    if component == "Luminance":
        if source.shape[2] == 1:
            return source[..., 0]
        return _luminance(source)
    index = {"Red": 0, "Green": 1, "Blue": 2, "Alpha": 3}.get(component, 0)
    index = min(index, source.shape[2] - 1)
    return source[..., index]


def pack_template_channels(
    width: int,
    height: int,
    images: Mapping[str, np.ndarray],
    bindings: tuple[tuple[str, Any], ...],
    *,
    normal_directx: bool = False,
) -> np.ndarray:
    """Compose arbitrary export-template channel bindings into one image."""
    shape = (int(height), int(width))
    output: list[np.ndarray] = []
    for _channel_name, binding in bindings:
        source_name = str(getattr(binding, "source", "Constant"))
        component = str(getattr(binding, "component", "Red"))
        image = images.get(source_name)
        if image is None:
            value = _binding_default(source_name, component, float(getattr(binding, "constant", 0.0)))
            channel = np.full(shape, value, dtype=np.float32)
        else:
            channel = np.asarray(_binding_channel(image, component), dtype=np.float32)
            if channel.shape != shape:
                raise ValueError(
                    f"Template source resolution {channel.shape[::-1]} does not match {shape[::-1]}"
                )
        should_invert = bool(getattr(binding, "invert", False))
        if bool(getattr(binding, "normal_y", False)) and normal_directx:
            should_invert = not should_invert
        if should_invert:
            channel = 1.0 - channel
        output.append(np.clip(channel, 0.0, 1.0))
    if not output:
        raise ValueError("Export template file has no active channels")
    return np.stack(output, axis=2).astype(np.float32)

def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def write_png(path: Path, image: np.ndarray, bit_depth: int, srgb: bool) -> None:
    height, width, channels = image.shape
    if channels not in (1, 3, 4):
        raise ValueError("PNG export supports grayscale, RGB or RGBA data")
    if bit_depth not in (8, 16):
        raise ValueError("PNG bit depth must be 8 or 16")
    colour_type = {1: 0, 3: 2, 4: 6}[channels]
    if bit_depth == 8:
        pixels = (image * 255.0 + 0.5).astype(np.uint8)
    else:
        pixels = (image * 65535.0 + 0.5).astype(">u2")
    rows = b"".join(b"\x00" + np.ascontiguousarray(pixels[row]).tobytes() for row in range(height))
    header = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, bit_depth, colour_type, 0, 0, 0)
    chunks = [_png_chunk(b"IHDR", ihdr)]
    if srgb:
        # Colour outputs are transfer-encoded to sRGB above and explicitly
        # tagged so colour-managed applications display them correctly.
        chunks.append(_png_chunk(b"sRGB", b"\x00"))
    # Numeric/data textures deliberately carry no sRGB or gAMA chunk.  A gAMA
    # value of 1.0 is mathematically correct for linear light, but image viewers
    # then colour-manage values such as 0.5 to a much brighter display value.
    # Normal maps, masks, height, roughness and packed channels must preserve and
    # visibly present their authored numeric bytes without a display transfer.
    chunks.append(_png_chunk(b"IDAT", zlib.compress(rows, level=6)))
    chunks.append(_png_chunk(b"IEND", b""))
    path.write_bytes(header + b"".join(chunks))


def export_image(path: Path, image: np.ndarray, options: ExportOptions) -> None:
    prepared = prepare_export_array(image, options)
    fmt = options.format_name.upper()
    if fmt == "R16":
        scalar = prepared[..., 0]
        (scalar * 65535.0 + 0.5).astype("<u2").tofile(path)
        return
    if fmt == "PNG":
        write_png(path, prepared, options.bit_depth, options.colour_encoding == "sRGB")
        return
    if fmt == "TGA":
        if options.bit_depth != 8:
            raise ValueError("TGA export is currently 8-bit")
        array = (prepared * 255.0 + 0.5).astype(np.uint8)
        if array.shape[2] == 1:
            pil = Image.fromarray(array[..., 0], mode="L")
        elif array.shape[2] == 3:
            pil = Image.fromarray(array, mode="RGB")
        else:
            pil = Image.fromarray(array, mode="RGBA")
        pil.save(path, format="TGA")
        return
    raise ValueError(f"Unsupported export format: {options.format_name}")
