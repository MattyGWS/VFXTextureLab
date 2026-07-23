"""Manual high-to-low texture baking for photogrammetry and game assets.

The public node is intentionally backed by a versioned, map-oriented result
container rather than four hard-coded arrays.  New Substance-style bake outputs
can therefore be added without changing the manual execution/persistence model.
Core projection uses the cross-platform Embree wrapper shipped by ``embreex``;
a small NumPy reference intersector remains available for tests and tiny meshes.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Mapping

import base64
import hashlib
import json
import math
import threading
import time

import numpy as np

from .geometry import (
    GeometryData, GeometryEvalContext, GeometryEvaluationCancelled,
    UV_ORIGIN_BOTTOM_LEFT, convert_uv_origin,
)


BAKE_RESULT_VERSION = 2
BAKE_NODE_TYPE = "geometry.bake_high_to_low"
BAKE_OUTPUTS: tuple[str, ...] = (
    "Albedo",
    "Normal",
    "Height",
    "Ambient Occlusion",
    "Projection Mask",
)
BAKE_OUTPUT_KINDS: dict[str, str] = {
    "Albedo": "color",
    "Normal": "vector",
    "Height": "grayscale",
    "Ambient Occlusion": "grayscale",
    "Projection Mask": "grayscale",
}
BAKE_PARAMETER_NAMES: tuple[str, ...] = (
    "resolution",
    "supersampling",
    "padding",
    "bake_albedo",
    "bake_normal",
    "bake_height",
    "bake_ambient_occlusion",
    "projection_mode",
    "distance_mode",
    "automatic_distance_percent",
    "front_distance",
    "back_distance",
    "ray_bias_percent",
    "albedo_filter",
    "preserve_alpha",
    "normal_y",
    "height_range",
    "height_manual_min",
    "height_manual_max",
    "height_invert",
    "ao_quality",
    "ao_samples",
    "ao_distance_mode",
    "ao_distance_percent",
    "ao_distance",
    "ao_intensity",
    "ao_contrast",
)


@dataclass(slots=True)
class BakeMap:
    name: str
    kind: str
    image: np.ndarray
    precision: str = "8-bit"


@dataclass(slots=True)
class GeometryBakeResult:
    low_geometry: GeometryData
    maps: dict[str, BakeMap]
    diagnostics: dict[str, Any]

    @property
    def memory_bytes(self) -> int:
        return int(
            self.low_geometry.vertices.nbytes
            + self.low_geometry.indices.nbytes
            + sum(item.image.nbytes for item in self.maps.values())
        )


_BAKE_CACHE: "OrderedDict[str, GeometryBakeResult]" = OrderedDict()
_BAKE_CACHE_LOCK = threading.RLock()
_BAKE_CACHE_BUDGET = 1024 * 1024 * 1024
_BVH_CACHE: "OrderedDict[str, Any]" = OrderedDict()
_BVH_CACHE_LOCK = threading.RLock()
_BVH_CACHE_LIMIT = 3


def _rgba(image: np.ndarray, *, default_alpha: float = 1.0) -> np.ndarray:
    array = np.asarray(image, dtype=np.float32)
    if array.ndim == 2:
        rgb = np.repeat(array[..., None], 3, axis=2)
        return np.concatenate(
            [rgb, np.full((*array.shape, 1), default_alpha, dtype=np.float32)], axis=2
        )
    if array.ndim != 3:
        raise ValueError("Bake images must be H x W or H x W x C arrays")
    if array.shape[2] == 1:
        rgb = np.repeat(array, 3, axis=2)
        return np.concatenate(
            [rgb, np.full((*array.shape[:2], 1), default_alpha, dtype=np.float32)], axis=2
        )
    if array.shape[2] == 2:
        return np.concatenate(
            [array[..., :1], array[..., :1], array[..., :1], array[..., 1:2]], axis=2
        )
    if array.shape[2] == 3:
        return np.concatenate(
            [array, np.full((*array.shape[:2], 1), default_alpha, dtype=np.float32)], axis=2
        )
    return np.ascontiguousarray(array[..., :4], dtype=np.float32)


def default_bake_output(name: str, width: int, height: int) -> np.ndarray:
    width = max(int(width), 1)
    height = max(int(height), 1)
    if name == "Normal":
        value = np.array([0.5, 0.5, 1.0, 1.0], dtype=np.float32)
    elif name == "Height":
        value = np.array([0.5, 0.5, 0.5, 1.0], dtype=np.float32)
    elif name == "Ambient Occlusion":
        value = np.ones(4, dtype=np.float32)
    elif name == "Projection Mask":
        value = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
    else:
        value = np.array([0.18, 0.18, 0.18, 1.0], dtype=np.float32)
    return np.broadcast_to(value, (height, width, 4)).copy()


def _resize_float(image: np.ndarray, width: int, height: int) -> np.ndarray:
    image = _rgba(image)
    source_h, source_w = image.shape[:2]
    width = max(int(width), 1)
    height = max(int(height), 1)
    if source_w == width and source_h == height:
        return np.ascontiguousarray(image, dtype=np.float32)
    # Bilinear resize in linear data space.  This tiny implementation avoids a
    # Pillow colour-mode round trip and is shared by every future bake output.
    x = np.linspace(0.0, max(source_w - 1, 0), width, dtype=np.float32)
    y = np.linspace(0.0, max(source_h - 1, 0), height, dtype=np.float32)
    x0 = np.floor(x).astype(np.int32)
    y0 = np.floor(y).astype(np.int32)
    x1 = np.minimum(x0 + 1, source_w - 1)
    y1 = np.minimum(y0 + 1, source_h - 1)
    tx = (x - x0)[None, :, None]
    ty = (y - y0)[:, None, None]
    a = image[y0[:, None], x0[None, :]]
    b = image[y0[:, None], x1[None, :]]
    c = image[y1[:, None], x0[None, :]]
    d = image[y1[:, None], x1[None, :]]
    top = a * (1.0 - tx) + b * tx
    bottom = c * (1.0 - tx) + d * tx
    return np.ascontiguousarray(top * (1.0 - ty) + bottom * ty, dtype=np.float32)


def _quantise_map(item: BakeMap) -> tuple[np.ndarray, dict[str, Any]]:
    image = np.clip(np.nan_to_num(_rgba(item.image), nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)
    meta = {"name": item.name, "kind": item.kind, "precision": item.precision}
    if item.kind == "grayscale":
        channel = image[..., 0]
        if item.precision == "16-bit":
            meta["storage"] = "u16_gray"
            return np.round(channel * 65535.0).astype(np.uint16), meta
        meta["storage"] = "u8_gray"
        return np.round(channel * 255.0).astype(np.uint8), meta
    meta["storage"] = "u8_rgba"
    return np.round(image * 255.0).astype(np.uint8), meta


def _dequantise_map(array: np.ndarray, meta: Mapping[str, Any]) -> BakeMap:
    storage = str(meta.get("storage", "u8_rgba"))
    if storage == "u16_gray":
        scalar = np.asarray(array, dtype=np.float32) / 65535.0
        image = _rgba(scalar)
    elif storage == "u8_gray":
        scalar = np.asarray(array, dtype=np.float32) / 255.0
        image = _rgba(scalar)
    else:
        image = _rgba(np.asarray(array, dtype=np.float32) / 255.0)
    return BakeMap(
        str(meta.get("name", "Bake Output")),
        str(meta.get("kind", "color")),
        np.ascontiguousarray(image, dtype=np.float32),
        str(meta.get("precision", "8-bit")),
    )


def encode_bake_result(result: GeometryBakeResult) -> str:
    stream = BytesIO()
    arrays: dict[str, np.ndarray] = {
        "version": np.asarray([BAKE_RESULT_VERSION], dtype=np.int32),
        "vertices": np.asarray(result.low_geometry.vertices, dtype=np.float32),
        "indices": np.asarray(result.low_geometry.indices, dtype=np.uint32),
        "geometry_name": np.asarray([result.low_geometry.name]),
        "geometry_uv_origin": np.asarray([result.low_geometry.uv_origin]),
        "diagnostics": np.asarray([
            json.dumps(result.diagnostics, separators=(",", ":"), default=str)
        ]),
    }
    map_metadata: list[dict[str, Any]] = []
    for index, name in enumerate(sorted(result.maps)):
        packed, meta = _quantise_map(result.maps[name])
        meta["key"] = f"map_{index}"
        map_metadata.append(meta)
        arrays[f"map_{index}"] = packed
    arrays["maps"] = np.asarray([json.dumps(map_metadata, separators=(",", ":"))])
    np.savez_compressed(stream, **arrays)
    return base64.b64encode(stream.getvalue()).decode("ascii")


def decode_bake_result(encoded: str, *, cache_key: str | None = None) -> GeometryBakeResult:
    payload = str(encoded or "").strip()
    if not payload:
        raise ValueError("No completed bake result is available")
    key = str(cache_key or "").strip()
    if not key:
        key = hashlib.blake2b(
            payload.encode("ascii", errors="ignore"), digest_size=16
        ).hexdigest()
    with _BAKE_CACHE_LOCK:
        cached = _BAKE_CACHE.get(key)
        if cached is not None:
            _BAKE_CACHE.move_to_end(key)
            return cached
    try:
        raw = base64.b64decode(payload, validate=True)
        with np.load(BytesIO(raw), allow_pickle=False) as archive:
            version = int(archive["version"][0]) if "version" in archive else 0
            if version > BAKE_RESULT_VERSION:
                raise ValueError("Bake result was created by a newer VFX Texture Lab version")
            geometry = GeometryData(
                archive["vertices"], archive["indices"],
                str(archive["geometry_name"][0]) if "geometry_name" in archive else "Baked Low Geometry",
                (
                    str(archive["geometry_uv_origin"][0])
                    if "geometry_uv_origin" in archive
                    else UV_ORIGIN_BOTTOM_LEFT
                ),
            )
            diagnostics = json.loads(str(archive["diagnostics"][0])) if "diagnostics" in archive else {}
            map_meta = json.loads(str(archive["maps"][0])) if "maps" in archive else []
            maps: dict[str, BakeMap] = {}
            for meta in map_meta:
                item = _dequantise_map(archive[str(meta["key"])], meta)
                maps[item.name] = item
            result = GeometryBakeResult(geometry, maps, dict(diagnostics))
    except Exception as exc:
        raise ValueError("Saved high-to-low bake result is damaged") from exc
    with _BAKE_CACHE_LOCK:
        _BAKE_CACHE[key] = result
        _BAKE_CACHE.move_to_end(key)
        total = sum(value.memory_bytes for value in _BAKE_CACHE.values())
        while total > _BAKE_CACHE_BUDGET and len(_BAKE_CACHE) > 1:
            _old_key, old = _BAKE_CACHE.popitem(last=False)
            total -= old.memory_bytes
    return result


def decode_bake_parameters(parameters: Mapping[str, Any]) -> GeometryBakeResult:
    payload = str(parameters.get("_manual_result_data", "") or "")
    if not payload:
        raise ValueError("No completed bake result is available")
    revision = str(
        parameters.get("_manual_result_revision")
        or parameters.get("_manual_signature")
        or ""
    )
    return decode_bake_result(payload, cache_key=revision or None)


def bake_result_map_names(parameters: Mapping[str, Any]) -> frozenset[str]:
    """Return the maps contained in the last completed transactional result.

    Current unapplied checkbox values deliberately do not affect this answer: an
    Out of Date node keeps publishing the previous successful bake until the next
    run completes.
    """
    declared = parameters.get("_bake_maps", ()) or ()
    if isinstance(declared, str):
        declared = (declared,)
    names = frozenset(str(value) for value in declared if str(value))
    if names:
        return names
    payload = str(parameters.get("_manual_result_data", "") or "")
    if not payload:
        return frozenset()
    try:
        return frozenset(decode_bake_parameters(parameters).maps)
    except ValueError:
        return frozenset()


def bake_output_image(
    parameters: Mapping[str, Any], output_name: str, width: int, height: int
) -> tuple[np.ndarray, str, str]:
    """Decode one published bake socket for the ordinary image/material graph."""
    output_name = str(output_name or "Albedo")
    payload = str(parameters.get("_manual_result_data", "") or "")
    if not payload:
        kind = BAKE_OUTPUT_KINDS.get(output_name, "color")
        return default_bake_output(output_name, width, height), kind, "16-bit" if output_name == "Height" else "8-bit"
    result = decode_bake_parameters(parameters)
    item = result.maps.get(output_name)
    if item is None:
        kind = BAKE_OUTPUT_KINDS.get(output_name, "grayscale")
        return default_bake_output(output_name, width, height), kind, "16-bit" if output_name == "Height" else "8-bit"
    image = _resize_float(item.image, width, height)
    if output_name == "Normal":
        vector = image[..., :3] * 2.0 - 1.0
        length = np.linalg.norm(vector, axis=2, keepdims=True)
        vector /= np.maximum(length, 1.0e-8)
        image[..., :3] = vector * 0.5 + 0.5
        image[..., 3] = 1.0
    return image, item.kind, item.precision


def _geometry_digest(geometry: GeometryData) -> str:
    digest = hashlib.blake2b(digest_size=16)
    vertices = np.ascontiguousarray(geometry.vertices, dtype=np.float32)
    indices = np.ascontiguousarray(geometry.indices, dtype=np.uint32)
    digest.update(memoryview(vertices).cast("B"))
    digest.update(memoryview(indices).cast("B"))
    digest.update(geometry.uv_origin.encode("ascii"))
    return digest.hexdigest()


def _bake_signature(
    high: GeometryData,
    low: GeometryData,
    high_albedo: np.ndarray | None,
    cage: GeometryData | None,
    parameters: Mapping[str, Any],
) -> str:
    digest = hashlib.blake2b(digest_size=20)
    digest.update(_geometry_digest(high).encode())
    digest.update(_geometry_digest(low).encode())
    if cage is not None:
        digest.update(_geometry_digest(cage).encode())
    if high_albedo is not None:
        array = np.ascontiguousarray(high_albedo, dtype=np.float32)
        digest.update(str(array.shape).encode())
        texture_digest = hashlib.blake2b(digest_size=12)
        texture_digest.update(memoryview(array).cast("B"))
        digest.update(texture_digest.digest())
    relevant = {name: parameters.get(name) for name in BAKE_PARAMETER_NAMES}
    digest.update(json.dumps(relevant, sort_keys=True, separators=(",", ":"), default=str).encode())
    return digest.hexdigest()


def _triangle_normals(geometry: GeometryData) -> np.ndarray:
    triangles = geometry.indices.reshape(-1, 3).astype(np.int64, copy=False)
    positions = geometry.vertices[:, :3].astype(np.float64, copy=False)
    p0 = positions[triangles[:, 0]]
    p1 = positions[triangles[:, 1]]
    p2 = positions[triangles[:, 2]]
    normals = np.cross(p1 - p0, p2 - p0)
    length = np.linalg.norm(normals, axis=1, keepdims=True)
    normals /= np.maximum(length, 1.0e-20)
    return normals.astype(np.float32)


def _valid_vertex_normals(geometry: GeometryData) -> np.ndarray:
    normals = np.asarray(geometry.vertices[:, 3:6], dtype=np.float32)
    length = np.linalg.norm(normals, axis=1, keepdims=True)
    if np.any(length < 1.0e-8):
        triangles = geometry.indices.reshape(-1, 3).astype(np.int64, copy=False)
        face = _triangle_normals(geometry)
        generated = np.zeros_like(normals)
        for corner in range(3):
            np.add.at(generated, triangles[:, corner], face)
        length = np.linalg.norm(generated, axis=1, keepdims=True)
        normals = generated / np.maximum(length, 1.0e-8)
    else:
        normals = normals / np.maximum(length, 1.0e-8)
    return np.ascontiguousarray(normals, dtype=np.float32)


def _standard_uvs(geometry: GeometryData) -> np.ndarray:
    vertices = convert_uv_origin(
        geometry.vertices, geometry.uv_origin, UV_ORIGIN_BOTTOM_LEFT
    )
    return np.asarray(vertices[:, 6:8], dtype=np.float32)


def _uv_diagnostics(geometry: GeometryData) -> dict[str, int | bool]:
    uv = np.asarray(_standard_uvs(geometry), dtype=np.float64)
    triangles = geometry.indices.reshape(-1, 3).astype(np.int64, copy=False)
    if uv.size == 0 or not np.isfinite(uv).all() or len(triangles) == 0:
        return {
            "usable": False,
            "out_of_bounds_vertices": int(len(uv)),
            "zero_area_triangles": int(len(triangles)),
        }
    tri_uv = uv[triangles]
    area_twice = np.abs(
        (tri_uv[:, 1, 0] - tri_uv[:, 0, 0]) * (tri_uv[:, 2, 1] - tri_uv[:, 0, 1])
        - (tri_uv[:, 1, 1] - tri_uv[:, 0, 1]) * (tri_uv[:, 2, 0] - tri_uv[:, 0, 0])
    )
    zero_area = int(np.count_nonzero(area_twice <= 1.0e-12))
    out_of_bounds = int(np.count_nonzero(np.any((uv < -1.0e-6) | (uv > 1.000001), axis=1)))
    return {
        "usable": bool(np.any(area_twice > 1.0e-12)),
        "out_of_bounds_vertices": out_of_bounds,
        "zero_area_triangles": zero_area,
    }


@dataclass(slots=True)
class _RasterisedLow:
    triangle_ids: np.ndarray
    barycentric: np.ndarray
    overlap: np.ndarray
    valid: np.ndarray


def _rasterise_low_uv(
    low: GeometryData, width: int, height: int, context: GeometryEvalContext | None
) -> _RasterisedLow:
    triangles = low.indices.reshape(-1, 3).astype(np.int64, copy=False)
    uv = np.asarray(_standard_uvs(low), dtype=np.float64)
    positions = np.asarray(low.vertices[:, :3], dtype=np.float64)
    if uv.size == 0 or not np.isfinite(uv).all():
        raise ValueError("Low Geometry does not contain usable UV coordinates")
    owner = np.full((height, width), -1, dtype=np.int32)
    bary = np.zeros((height, width, 3), dtype=np.float32)
    overlap = np.zeros((height, width), dtype=bool)
    total = max(len(triangles), 1)
    for tri_index, tri in enumerate(triangles):
        if context is not None and tri_index % 256 == 0:
            context.progress(tri_index, total, "Rasterising low-poly UVs")
        tuv = uv[tri]
        # Texture arrays and the 2D preview use a top-left origin.
        p = np.empty((3, 2), dtype=np.float64)
        p[:, 0] = tuv[:, 0] * width
        p[:, 1] = (1.0 - tuv[:, 1]) * height
        min_x = max(int(math.floor(float(np.min(p[:, 0]) - 0.5))), 0)
        max_x = min(int(math.ceil(float(np.max(p[:, 0]) - 0.5))), width - 1)
        min_y = max(int(math.floor(float(np.min(p[:, 1]) - 0.5))), 0)
        max_y = min(int(math.ceil(float(np.max(p[:, 1]) - 0.5))), height - 1)
        if max_x < min_x or max_y < min_y:
            continue
        x0, y0 = p[0]
        x1, y1 = p[1]
        x2, y2 = p[2]
        denominator = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(denominator) < 1.0e-14:
            continue
        xs = np.arange(min_x, max_x + 1, dtype=np.float64) + 0.5
        ys = np.arange(min_y, max_y + 1, dtype=np.float64) + 0.5
        px, py = np.meshgrid(xs, ys)
        w0 = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / denominator
        w1 = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / denominator
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1.0e-7) & (w1 >= -1.0e-7) & (w2 >= -1.0e-7)
        if not np.any(inside):
            continue
        target_owner = owner[min_y:max_y + 1, min_x:max_x + 1]
        target_bary = bary[min_y:max_y + 1, min_x:max_x + 1]
        already = inside & (target_owner >= 0)
        if np.any(already):
            # Adjacent UV triangles both cover their shared raster edge. That is
            # not an overlapping island, so only flag pixels whose two source
            # triangles do not share a complete mesh edge.
            previous_ids = target_owner[already].astype(np.int64, copy=False)
            previous_corners = triangles[previous_ids]
            # OBJ import duplicates render vertices at UV and hard-normal seams.
            # Treat two triangles as ordinary neighbours when exactly two of
            # their corners match in both geometric position and UV, even if
            # the raw vertex indices differ. Three matching corners indicate a
            # duplicate/stacked triangle and remain a real overlap.
            previous_position = positions[previous_corners]
            previous_uv = uv[previous_corners]
            current_position = positions[tri]
            current_uv = uv[tri]
            position_match = np.all(
                np.isclose(
                    previous_position[:, :, None, :],
                    current_position[None, None, :, :],
                    rtol=0.0, atol=1.0e-7,
                ),
                axis=3,
            )
            uv_match = np.all(
                np.isclose(
                    previous_uv[:, :, None, :],
                    current_uv[None, None, :, :],
                    rtol=0.0, atol=1.0e-7,
                ),
                axis=3,
            )
            shared_corners = np.sum(np.any(position_match & uv_match, axis=2), axis=1)
            real_overlap = np.zeros_like(already)
            real_overlap[already] = shared_corners != 2
            overlap[min_y:max_y + 1, min_x:max_x + 1] |= real_overlap
        write = inside & (target_owner < 0)
        target_owner[write] = tri_index
        target_bary[..., 0][write] = w0[write]
        target_bary[..., 1][write] = w1[write]
        target_bary[..., 2][write] = w2[write]
    if context is not None:
        context.progress(total, total, "Low-poly UV raster ready")
    valid = owner >= 0
    if not np.any(valid):
        raise ValueError("Low Geometry UVs do not cover any pixels in the selected bake resolution")
    return _RasterisedLow(owner, bary, overlap, valid)


def _sample_low_surface(low: GeometryData, raster: _RasterisedLow) -> dict[str, np.ndarray]:
    ids = raster.triangle_ids[raster.valid].astype(np.int64, copy=False)
    weights = raster.barycentric[raster.valid].astype(np.float32, copy=False)
    triangles = low.indices.reshape(-1, 3).astype(np.int64, copy=False)
    corners = triangles[ids]
    positions = low.vertices[:, :3].astype(np.float32, copy=False)
    normals = _valid_vertex_normals(low)
    sample_positions = np.sum(positions[corners] * weights[..., None], axis=1)
    sample_normals = np.sum(normals[corners] * weights[..., None], axis=1)
    sample_normals /= np.maximum(np.linalg.norm(sample_normals, axis=1, keepdims=True), 1.0e-8)

    # Match the derivative tangent basis used by the 3D preview shader. For a
    # linearly interpolated triangle, the position/UV derivatives are constant;
    # only the smooth low normal varies per sample. This avoids a mismatch
    # between an averaged vertex tangent in the baker and the per-fragment basis
    # that displays the completed normal map. The interface remains isolated so
    # a bundled MikkTSpace backend can replace both sides together later.
    uv = _standard_uvs(low)
    tri_pos = positions[triangles]
    tri_uv = uv[triangles]
    dp1 = tri_pos[:, 1] - tri_pos[:, 0]
    dp2 = tri_pos[:, 2] - tri_pos[:, 0]
    duv1 = tri_uv[:, 1] - tri_uv[:, 0]
    duv2 = tri_uv[:, 2] - tri_uv[:, 0]
    determinant = duv1[:, 0] * duv2[:, 1] - duv1[:, 1] * duv2[:, 0]
    # The usual tangent formula divides by the UV determinant. Its magnitude
    # disappears when the basis is normalised, but its sign is essential:
    # xatlas and imported meshes may legitimately mirror individual charts.
    # Omitting that sign makes +U and +V point backwards on mirrored islands,
    # which encodes inverted red/green normal-map channels even though the bake
    # still appears self-consistent in a renderer carrying the same bug.
    uv_orientation = np.where(determinant < 0.0, -1.0, 1.0).astype(np.float32)[:, None]
    raw_tangent = (dp1 * duv2[:, 1:2] - dp2 * duv1[:, 1:2]) * uv_orientation
    raw_bitangent = (-dp1 * duv2[:, 0:1] + dp2 * duv1[:, 0:1]) * uv_orientation
    sample_tangent = raw_tangent[ids]
    sample_tangent -= sample_normals * np.sum(
        sample_tangent * sample_normals, axis=1, keepdims=True
    )
    tangent_length = np.linalg.norm(sample_tangent, axis=1, keepdims=True)
    fallback_axis = np.where(
        (np.abs(sample_normals[:, 2:3]) < 0.999),
        np.array([[0.0, 0.0, 1.0]], dtype=np.float32),
        np.array([[0.0, 1.0, 0.0]], dtype=np.float32),
    )
    fallback_tangent = np.cross(fallback_axis, sample_normals)
    fallback_tangent /= np.maximum(
        np.linalg.norm(fallback_tangent, axis=1, keepdims=True), 1.0e-8
    )
    sample_tangent = np.where(
        tangent_length > 1.0e-8,
        sample_tangent / np.maximum(tangent_length, 1.0e-8),
        fallback_tangent,
    )
    sample_raw_bitangent = raw_bitangent[ids]
    handedness = np.where(
        np.sum(
            np.cross(sample_normals, sample_tangent) * sample_raw_bitangent, axis=1
        ) < 0.0,
        -1.0,
        1.0,
    ).astype(np.float32)
    sample_bitangent = np.cross(sample_normals, sample_tangent) * handedness[:, None]
    return {
        "positions": np.ascontiguousarray(sample_positions, dtype=np.float32),
        "normals": np.ascontiguousarray(sample_normals, dtype=np.float32),
        "tangents": np.ascontiguousarray(sample_tangent, dtype=np.float32),
        "bitangents": np.ascontiguousarray(sample_bitangent, dtype=np.float32),
        "triangle_ids": ids,
        "weights": weights,
    }


class _ReferenceIntersector:
    """Small, cancellable NumPy Möller–Trumbore fallback.

    It is intentionally capped: production/high-poly baking should always use
    Embree, while unit tests and tiny generated meshes remain fully functional.
    """

    backend_name = "NumPy reference (tiny meshes)"

    def __init__(self, geometry: GeometryData) -> None:
        triangles = geometry.indices.reshape(-1, 3).astype(np.int64, copy=False)
        vertices = geometry.vertices[:, :3].astype(np.float32, copy=False)
        self.v0 = vertices[triangles[:, 0]]
        self.e1 = vertices[triangles[:, 1]] - self.v0
        self.e2 = vertices[triangles[:, 2]] - self.v0
        self.triangle_count = len(triangles)

    def first_hits(
        self,
        origins: np.ndarray,
        directions: np.ndarray,
        max_distance: float | np.ndarray,
        context: GeometryEvalContext | None = None,
        message: str = "Projecting rays",
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        ray_count = len(origins)
        if ray_count * max(self.triangle_count, 1) > 40_000_000:
            raise RuntimeError(
                "The native Embree bake backend is unavailable. Run setup.sh or setup.bat; "
                "the NumPy reference backend is limited to tiny meshes."
            )
        hit_tri = np.full(ray_count, -1, dtype=np.int32)
        hit_distance = np.full(ray_count, np.inf, dtype=np.float32)
        hit_bary = np.zeros((ray_count, 3), dtype=np.float32)
        max_values = np.broadcast_to(np.asarray(max_distance, dtype=np.float32), (ray_count,))
        ray_chunk = 128
        tri_chunk = 2048
        for start in range(0, ray_count, ray_chunk):
            if context is not None:
                context.progress(start, ray_count, message)
            end = min(start + ray_chunk, ray_count)
            o = origins[start:end]
            d = directions[start:end]
            local_best = np.full(end - start, np.inf, dtype=np.float32)
            local_tri = np.full(end - start, -1, dtype=np.int32)
            local_bary = np.zeros((end - start, 3), dtype=np.float32)
            for tri_start in range(0, self.triangle_count, tri_chunk):
                tri_end = min(tri_start + tri_chunk, self.triangle_count)
                v0 = self.v0[tri_start:tri_end]
                e1 = self.e1[tri_start:tri_end]
                e2 = self.e2[tri_start:tri_end]
                pvec = np.cross(d[:, None, :], e2[None, :, :])
                det = np.sum(e1[None, :, :] * pvec, axis=2)
                valid_det = np.abs(det) > 1.0e-8
                inv_det = np.zeros_like(det)
                inv_det[valid_det] = 1.0 / det[valid_det]
                tvec = o[:, None, :] - v0[None, :, :]
                u = np.sum(tvec * pvec, axis=2) * inv_det
                qvec = np.cross(tvec, e1[None, :, :])
                v = np.sum(d[:, None, :] * qvec, axis=2) * inv_det
                distance = np.sum(e2[None, :, :] * qvec, axis=2) * inv_det
                valid = (
                    valid_det & (u >= -1.0e-7) & (v >= -1.0e-7)
                    & ((u + v) <= 1.0000001) & (distance > 1.0e-7)
                    & (distance <= max_values[start:end, None])
                )
                candidate = np.where(valid, distance, np.inf)
                indices = np.argmin(candidate, axis=1)
                values = candidate[np.arange(end - start), indices]
                improve = values < local_best
                if np.any(improve):
                    local_best[improve] = values[improve]
                    chosen_u = u[np.arange(end - start), indices]
                    chosen_v = v[np.arange(end - start), indices]
                    local_bary[improve, 0] = 1.0 - chosen_u[improve] - chosen_v[improve]
                    local_bary[improve, 1] = chosen_u[improve]
                    local_bary[improve, 2] = chosen_v[improve]
                    local_tri[improve] = tri_start + indices[improve]
            hit_tri[start:end] = local_tri
            hit_distance[start:end] = local_best
            hit_bary[start:end] = local_bary
        if context is not None:
            context.progress(ray_count, ray_count, message)
        return hit_tri, hit_distance, hit_bary

    def any_hits(
        self,
        origins: np.ndarray,
        directions: np.ndarray,
        max_distance: float,
        context: GeometryEvalContext | None = None,
        message: str = "Baking ambient occlusion",
    ) -> np.ndarray:
        tri, _distance, _bary = self.first_hits(origins, directions, max_distance, context, message)
        return tri >= 0


class _EmbreeIntersector:
    backend_name = "Embree CPU (embreex)"

    def __init__(self, geometry: GeometryData) -> None:
        import trimesh
        from trimesh.ray.ray_pyembree import RayMeshIntersector

        mesh = trimesh.Trimesh(
            vertices=np.asarray(geometry.vertices[:, :3], dtype=np.float64),
            faces=np.asarray(geometry.indices.reshape(-1, 3), dtype=np.int64),
            process=False,
            validate=False,
        )
        self.mesh = mesh
        self.intersector = RayMeshIntersector(mesh)
        # Keep the optional trimesh helper on the instance.  The dependency is
        # imported lazily so the application can still start without Embree,
        # but method-local imports are not visible in later method calls.
        self._points_to_barycentric = trimesh.triangles.points_to_barycentric

    def first_hits(
        self,
        origins: np.ndarray,
        directions: np.ndarray,
        max_distance: float | np.ndarray,
        context: GeometryEvalContext | None = None,
        message: str = "Projecting rays",
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        origins = np.ascontiguousarray(origins, dtype=np.float64)
        directions = np.ascontiguousarray(directions, dtype=np.float64)
        ray_count = len(origins)
        hit_tri = np.full(ray_count, -1, dtype=np.int32)
        hit_distance = np.full(ray_count, np.inf, dtype=np.float32)
        hit_bary = np.zeros((ray_count, 3), dtype=np.float32)
        maximum = np.broadcast_to(np.asarray(max_distance, dtype=np.float64), (ray_count,))
        chunk = 262_144
        for start in range(0, ray_count, chunk):
            if context is not None:
                context.progress(start, ray_count, message)
            end = min(start + chunk, ray_count)
            locations, ray_ids, triangle_ids = self.intersector.intersects_location(
                origins[start:end], directions[start:end], multiple_hits=False
            )
            if len(ray_ids):
                global_ids = start + np.asarray(ray_ids, dtype=np.int64)
                locations = np.asarray(locations, dtype=np.float64)
                distance = np.sum(
                    (locations - origins[global_ids]) * directions[global_ids], axis=1
                )
                accepted = (distance > 1.0e-8) & (distance <= maximum[global_ids])
                if np.any(accepted):
                    global_ids = global_ids[accepted]
                    triangle_ids = np.asarray(triangle_ids, dtype=np.int64)[accepted]
                    locations = locations[accepted]
                    distance = distance[accepted]
                    triangles = self.mesh.triangles[triangle_ids]
                    bary = self._points_to_barycentric(triangles, locations)
                    hit_tri[global_ids] = triangle_ids.astype(np.int32)
                    hit_distance[global_ids] = distance.astype(np.float32)
                    hit_bary[global_ids] = np.asarray(bary, dtype=np.float32)
        if context is not None:
            context.progress(ray_count, ray_count, message)
        return hit_tri, hit_distance, hit_bary

    def any_hits(
        self,
        origins: np.ndarray,
        directions: np.ndarray,
        max_distance: float,
        context: GeometryEvalContext | None = None,
        message: str = "Baking ambient occlusion",
    ) -> np.ndarray:
        origins = np.ascontiguousarray(origins, dtype=np.float64)
        directions = np.ascontiguousarray(directions, dtype=np.float64)
        result = np.zeros(len(origins), dtype=bool)
        chunk = 262_144
        for start in range(0, len(origins), chunk):
            if context is not None:
                context.progress(start, len(origins), message)
            end = min(start + chunk, len(origins))
            locations, ray_ids, _tri = self.intersector.intersects_location(
                origins[start:end], directions[start:end], multiple_hits=False
            )
            if len(ray_ids):
                ray_ids = np.asarray(ray_ids, dtype=np.int64)
                distance = np.sum(
                    (np.asarray(locations, dtype=np.float64) - origins[start:end][ray_ids])
                    * directions[start:end][ray_ids], axis=1
                )
                result[start + ray_ids[distance <= float(max_distance)]] = True
        if context is not None:
            context.progress(len(origins), len(origins), message)
        return result


def _intersector_for(high: GeometryData) -> Any:
    digest = _geometry_digest(high)
    with _BVH_CACHE_LOCK:
        cached = _BVH_CACHE.get(digest)
        if cached is not None:
            _BVH_CACHE.move_to_end(digest)
            return cached
    try:
        intersector: Any = _EmbreeIntersector(high)
    except Exception:
        intersector = _ReferenceIntersector(high)
    with _BVH_CACHE_LOCK:
        _BVH_CACHE[digest] = intersector
        _BVH_CACHE.move_to_end(digest)
        while len(_BVH_CACHE) > _BVH_CACHE_LIMIT:
            _BVH_CACHE.popitem(last=False)
    return intersector


def _project_samples(
    high: GeometryData,
    low_samples: Mapping[str, np.ndarray],
    cage_samples: np.ndarray | None,
    parameters: Mapping[str, Any],
    context: GeometryEvalContext | None,
) -> dict[str, np.ndarray | str | float]:
    low_position = np.asarray(low_samples["positions"], dtype=np.float32)
    low_normal = np.asarray(low_samples["normals"], dtype=np.float32)
    high_min, high_max = high.bounds
    low_extent = np.ptp(low_position, axis=0) if len(low_position) else np.ones(3)
    bounds_min = np.minimum(high_min, np.min(low_position, axis=0))
    bounds_max = np.maximum(high_max, np.max(low_position, axis=0))
    diagonal = max(float(np.linalg.norm(bounds_max - bounds_min)), 1.0e-6)
    auto_distance = diagonal * max(float(parameters.get("automatic_distance_percent", 5.0)), 0.01) / 100.0
    if str(parameters.get("distance_mode", "Automatic")) == "Manual":
        front_distance = max(float(parameters.get("front_distance", auto_distance)), 1.0e-8)
        back_distance = max(float(parameters.get("back_distance", auto_distance)), 1.0e-8)
    else:
        # Include the maximum discrepancy between the two bounding boxes, then a
        # small safety margin.  This makes plug-and-bake work for typical scans
        # while still preventing rays crossing the whole object unnecessarily.
        box_difference = max(
            float(np.max(np.abs(high_min - np.min(low_position, axis=0)))),
            float(np.max(np.abs(high_max - np.max(low_position, axis=0)))),
        )
        front_distance = back_distance = max(auto_distance, box_difference * 1.15)
    bias = diagonal * max(float(parameters.get("ray_bias_percent", 0.01)), 0.0) / 100.0
    intersector = _intersector_for(high)
    projection_mode = str(parameters.get("projection_mode", "Bidirectional Normals"))

    if projection_mode == "Custom Cage":
        if cage_samples is None:
            raise ValueError("Projection Mode is Custom Cage, but Cage Geometry is not connected")
        vector = low_position - cage_samples
        length = np.linalg.norm(vector, axis=1)
        direction = vector / np.maximum(length[:, None], 1.0e-8)
        origin = cage_samples + direction * bias
        maximum = length + back_distance
        tri, distance, bary = intersector.first_hits(origin, direction, maximum, context, "Projecting cage rays")
        hit = tri >= 0
        signed = np.zeros(len(low_position), dtype=np.float32)
        if np.any(hit):
            hit_position = origin[hit] + direction[hit] * distance[hit, None]
            signed[hit] = np.sum((hit_position - low_position[hit]) * low_normal[hit], axis=1)
        front_hit = hit & (signed >= 0.0)
        back_hit = hit & ~front_hit
    else:
        allow_front = projection_mode != "Inward Only"
        allow_back = projection_mode != "Outward Only"
        count = len(low_position)
        front_tri = np.full(count, -1, dtype=np.int32)
        front_t = np.full(count, np.inf, dtype=np.float32)
        front_bary = np.zeros((count, 3), dtype=np.float32)
        back_tri = front_tri.copy()
        back_t = front_t.copy()
        back_bary = front_bary.copy()
        if allow_front:
            origin = low_position + low_normal * (front_distance + bias)
            front_tri, front_t, front_bary = intersector.first_hits(
                origin, -low_normal, front_distance + bias * 2.0, context, "Projecting outward rays"
            )
        if allow_back:
            origin = low_position - low_normal * (back_distance + bias)
            back_tri, back_t, back_bary = intersector.first_hits(
                origin, low_normal, back_distance + bias * 2.0, context, "Projecting inward rays"
            )
        front_signed = front_distance + bias - front_t
        back_signed = back_t - (back_distance + bias)
        front_valid = front_tri >= 0
        back_valid = back_tri >= 0
        choose_front = front_valid & (~back_valid | (np.abs(front_signed) <= np.abs(back_signed)))
        choose_back = back_valid & ~choose_front
        tri = np.where(choose_front, front_tri, back_tri).astype(np.int32)
        distance = np.where(choose_front, front_t, back_t).astype(np.float32)
        bary = np.where(choose_front[:, None], front_bary, back_bary).astype(np.float32)
        signed = np.where(choose_front, front_signed, back_signed).astype(np.float32)
        hit = choose_front | choose_back
        signed[~hit] = 0.0
        front_hit = choose_front
        back_hit = choose_back

    return {
        "triangle": tri,
        "distance": distance,
        "barycentric": bary,
        "signed_height": signed,
        "hit": hit,
        "front_hit": front_hit,
        "back_hit": back_hit,
        "backend": intersector.backend_name,
        "front_distance": float(front_distance),
        "back_distance": float(back_distance),
        "bias": float(bias),
        "diagonal": float(diagonal),
        "intersector": intersector,
    }


def _high_hit_attributes(
    high: GeometryData, projection: Mapping[str, Any]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    hit = np.asarray(projection["hit"], dtype=bool)
    triangles = high.indices.reshape(-1, 3).astype(np.int64, copy=False)
    ids = np.asarray(projection["triangle"], dtype=np.int64)[hit]
    bary = np.asarray(projection["barycentric"], dtype=np.float32)[hit]
    corners = triangles[ids]
    positions = high.vertices[:, :3].astype(np.float32, copy=False)
    normals = _valid_vertex_normals(high)
    uv = _standard_uvs(high)
    hit_positions = np.sum(positions[corners] * bary[..., None], axis=1)
    hit_normals = np.sum(normals[corners] * bary[..., None], axis=1)
    hit_normals /= np.maximum(np.linalg.norm(hit_normals, axis=1, keepdims=True), 1.0e-8)
    hit_uv = np.sum(uv[corners] * bary[..., None], axis=1)
    return hit_positions, hit_normals, hit_uv


def _sample_texture(texture: np.ndarray, uv: np.ndarray, filtering: str) -> np.ndarray:
    image = _rgba(texture)
    h, w = image.shape[:2]
    u = np.mod(uv[:, 0], 1.0)
    v = np.mod(uv[:, 1], 1.0)
    x = u * max(w - 1, 0)
    y = (1.0 - v) * max(h - 1, 0)
    if filtering == "Nearest":
        return image[np.rint(y).astype(np.int32), np.rint(x).astype(np.int32)]
    x0 = np.floor(x).astype(np.int32)
    y0 = np.floor(y).astype(np.int32)
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)
    tx = (x - x0)[:, None]
    ty = (y - y0)[:, None]
    top = image[y0, x0] * (1.0 - tx) + image[y0, x1] * tx
    bottom = image[y1, x0] * (1.0 - tx) + image[y1, x1] * tx
    return top * (1.0 - ty) + bottom * ty


def _scatter_rgba(valid: np.ndarray, values: np.ndarray, default: np.ndarray) -> np.ndarray:
    image = np.broadcast_to(np.asarray(default, dtype=np.float32), (*valid.shape, 4)).copy()
    image[valid] = values
    return image


def _padding_fill(
    image: np.ndarray, valid: np.ndarray, pixels: int, *, occupied_uv: np.ndarray | None = None
) -> np.ndarray:
    pixels = max(int(pixels), 0)
    if pixels <= 0 or not np.any(valid) or np.all(valid):
        return image
    try:
        from scipy.ndimage import distance_transform_edt
        distance, indices = distance_transform_edt(~valid, return_indices=True)
        region = (~valid) & (distance <= pixels)
        # Padding belongs outside UV islands. A projection miss inside an
        # occupied low-poly texel must remain visible (and black in Projection
        # Mask), rather than being silently painted over by a nearby hit.
        if occupied_uv is not None:
            region &= ~np.asarray(occupied_uv, dtype=bool)
        result = image.copy()
        nearest_y = indices[0][region]
        nearest_x = indices[1][region]
        result[region] = image[nearest_y, nearest_x]
        return result
    except Exception:
        return image


def _downsample(image: np.ndarray, factor: int, *, normal: bool = False) -> np.ndarray:
    factor = max(int(factor), 1)
    if factor == 1:
        return image
    h, w = image.shape[:2]
    h2 = (h // factor) * factor
    w2 = (w // factor) * factor
    image = image[:h2, :w2]
    result = image.reshape(h2 // factor, factor, w2 // factor, factor, 4).mean(axis=(1, 3))
    if normal:
        vector = result[..., :3] * 2.0 - 1.0
        vector /= np.maximum(np.linalg.norm(vector, axis=2, keepdims=True), 1.0e-8)
        result[..., :3] = vector * 0.5 + 0.5
        result[..., 3] = 1.0
    return np.ascontiguousarray(result, dtype=np.float32)


def _ao_sample_count(parameters: Mapping[str, Any]) -> int:
    quality = str(parameters.get("ao_quality", "Draft"))
    return {
        "Draft": 16,
        "Medium": 64,
        "High": 256,
    }.get(quality, max(int(parameters.get("ao_samples", 64)), 1))


def _bake_ambient_occlusion(
    hit_positions: np.ndarray,
    hit_normals: np.ndarray,
    projection: Mapping[str, Any],
    parameters: Mapping[str, Any],
    context: GeometryEvalContext | None,
) -> np.ndarray:
    count = len(hit_positions)
    if count == 0:
        return np.empty(0, dtype=np.float32)
    samples = _ao_sample_count(parameters)
    diagonal = float(projection["diagonal"])
    if str(parameters.get("ao_distance_mode", "Automatic")) == "Manual":
        maximum = max(float(parameters.get("ao_distance", diagonal * 0.1)), 1.0e-8)
    else:
        maximum = diagonal * max(float(parameters.get("ao_distance_percent", 10.0)), 0.01) / 100.0
    bias = max(float(projection["bias"]), diagonal * 1.0e-6)
    axis = np.where(
        np.abs(hit_normals[:, 2:3]) < 0.999,
        np.array([[0.0, 0.0, 1.0]], dtype=np.float32),
        np.array([[0.0, 1.0, 0.0]], dtype=np.float32),
    )
    tangent = np.cross(axis, hit_normals)
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1.0e-8)
    bitangent = np.cross(hit_normals, tangent)
    occluded = np.zeros(count, dtype=np.float32)
    intersector = projection["intersector"]
    golden = math.pi * (3.0 - math.sqrt(5.0))
    for index in range(samples):
        if context is not None:
            context.progress(index, samples, "Baking ambient occlusion")
        # Cosine-weighted deterministic hemisphere sequence.
        r = math.sqrt((index + 0.5) / samples)
        phi = index * golden
        x = r * math.cos(phi)
        y = r * math.sin(phi)
        z = math.sqrt(max(1.0 - r * r, 0.0))
        direction = tangent * x + bitangent * y + hit_normals * z
        direction /= np.maximum(np.linalg.norm(direction, axis=1, keepdims=True), 1.0e-8)
        blocked = intersector.any_hits(
            hit_positions + hit_normals * bias, direction, maximum, None,
            "Baking ambient occlusion",
        )
        occluded += blocked.astype(np.float32)
    if context is not None:
        context.progress(samples, samples, "Ambient occlusion ready")
    ao = 1.0 - occluded / float(samples)
    intensity = max(float(parameters.get("ao_intensity", 1.0)), 0.0)
    contrast = max(float(parameters.get("ao_contrast", 1.0)), 0.01)
    ao = np.clip(1.0 - (1.0 - ao) * intensity, 0.0, 1.0)
    ao = np.clip((ao - 0.5) * contrast + 0.5, 0.0, 1.0)
    return ao.astype(np.float32)


def _perform_bake(
    high: GeometryData,
    low: GeometryData,
    high_albedo: np.ndarray | None,
    cage: GeometryData | None,
    parameters: Mapping[str, Any],
    context: GeometryEvalContext | None,
) -> GeometryBakeResult:
    started = time.perf_counter()
    resolution = int(parameters.get("resolution", 1024) or 1024)
    resolution = min(max(resolution, 64), 4096)
    supersampling = int(str(parameters.get("supersampling", "1x")).lower().replace("x", "") or 1)
    supersampling = min(max(supersampling, 1), 4)
    internal = resolution * supersampling
    pixels = internal * internal
    # The current raster/projection representation keeps several dense sample
    # arrays resident at once. Cap the internal atlas honestly until the planned
    # tiled baker can make 8K output memory-bounded.
    if pixels > 16_777_216:
        raise ValueError(
            "Bake resolution and supersampling exceed the 16-million-sample safety limit "
            "(maximum 4096 internal pixels per side). Reduce Resolution or Supersampling."
        )
    estimated_working_memory = int(pixels * 160)
    if low.triangle_count <= 0 or high.triangle_count <= 0:
        raise ValueError("High and Low Geometry must both contain triangles")
    high_uv_info = _uv_diagnostics(high)
    low_uv_info = _uv_diagnostics(low)
    if bool(parameters.get("bake_albedo", True)) and high_albedo is None:
        # One-click operation remains useful: missing albedo skips that map
        # instead of preventing geometry-derived maps from baking.
        bake_albedo = False
        albedo_warning = "High Albedo is not connected; Albedo was skipped."
    elif bool(parameters.get("bake_albedo", True)) and not bool(high_uv_info["usable"]):
        bake_albedo = False
        albedo_warning = "High Geometry has no usable UV area; Albedo was skipped."
    else:
        bake_albedo = bool(parameters.get("bake_albedo", True))
        albedo_warning = ""

    if context is not None:
        context.progress(0, 100, "Validating bake inputs")
    raster_started = time.perf_counter()
    raster = _rasterise_low_uv(low, internal, internal, context)
    low_samples = _sample_low_surface(low, raster)
    raster_ms = (time.perf_counter() - raster_started) * 1000.0

    cage_samples = None
    if cage is not None and str(parameters.get("projection_mode", "Bidirectional Normals")) == "Custom Cage":
        if cage.vertex_count != low.vertex_count or cage.indices.shape != low.indices.shape or not np.array_equal(cage.indices, low.indices):
            raise ValueError("Cage Geometry must have the same vertices and triangle topology as Low Geometry")
        ids = low_samples["triangle_ids"]
        weights = low_samples["weights"]
        corners = low.indices.reshape(-1, 3).astype(np.int64, copy=False)[ids]
        cage_samples = np.sum(cage.vertices[corners, :3] * weights[..., None], axis=1).astype(np.float32)

    projection_started = time.perf_counter()
    projection = _project_samples(high, low_samples, cage_samples, parameters, context)
    projection_ms = (time.perf_counter() - projection_started) * 1000.0
    valid_uv = raster.valid
    projected = np.asarray(projection["hit"], dtype=bool)
    valid_count = int(np.count_nonzero(valid_uv))
    hit_count = int(np.count_nonzero(projected))
    if hit_count == 0:
        raise ValueError(
            "No high-poly surface was reached. Increase Automatic Distance, use Manual distances, or supply a cage."
        )

    hit_positions, hit_normals, hit_uv = _high_hit_attributes(high, projection)
    low_normals = np.asarray(low_samples["normals"], dtype=np.float32)[projected]
    low_tangents = np.asarray(low_samples["tangents"], dtype=np.float32)[projected]
    low_bitangents = np.asarray(low_samples["bitangents"], dtype=np.float32)[projected]
    map_valid = np.zeros_like(valid_uv)
    map_valid[valid_uv] = projected
    padding = max(int(parameters.get("padding", 16)), 0) * supersampling
    maps: dict[str, BakeMap] = {}
    timings: dict[str, float] = {}

    if bake_albedo:
        map_started = time.perf_counter()
        sampled = _sample_texture(
            np.asarray(high_albedo, dtype=np.float32), hit_uv,
            str(parameters.get("albedo_filter", "Bilinear")),
        )
        if not bool(parameters.get("preserve_alpha", True)):
            sampled[:, 3] = 1.0
        image = default_bake_output("Albedo", internal, internal)
        image[map_valid] = sampled
        image = _padding_fill(image, map_valid, padding, occupied_uv=valid_uv)
        image = _downsample(image, supersampling)
        maps["Albedo"] = BakeMap("Albedo", "color", image, "8-bit")
        timings["albedo_ms"] = (time.perf_counter() - map_started) * 1000.0

    if bool(parameters.get("bake_normal", True)):
        map_started = time.perf_counter()
        tangent_normal = np.stack(
            [
                np.sum(hit_normals * low_tangents, axis=1),
                np.sum(hit_normals * low_bitangents, axis=1),
                np.sum(hit_normals * low_normals, axis=1),
            ],
            axis=1,
        )
        tangent_normal /= np.maximum(np.linalg.norm(tangent_normal, axis=1, keepdims=True), 1.0e-8)
        if str(parameters.get("normal_y", "OpenGL (+Y)")) == "DirectX (-Y)":
            tangent_normal[:, 1] *= -1.0
        encoded = np.concatenate(
            [tangent_normal * 0.5 + 0.5, np.ones((hit_count, 1), dtype=np.float32)], axis=1
        )
        image = default_bake_output("Normal", internal, internal)
        image[map_valid] = encoded
        image = _padding_fill(image, map_valid, padding, occupied_uv=valid_uv)
        image = _downsample(image, supersampling, normal=True)
        maps["Normal"] = BakeMap("Normal", "vector", image, "8-bit")
        timings["normal_ms"] = (time.perf_counter() - map_started) * 1000.0

    signed = np.asarray(projection["signed_height"], dtype=np.float32)[projected]
    if bool(parameters.get("bake_height", True)):
        map_started = time.perf_counter()
        if str(parameters.get("height_range", "Automatic Symmetric")) == "Manual":
            minimum = float(parameters.get("height_manual_min", -1.0))
            maximum = float(parameters.get("height_manual_max", 1.0))
            if maximum <= minimum:
                maximum = minimum + 1.0e-6
        else:
            maximum_abs = max(float(np.max(np.abs(signed))), 1.0e-8)
            minimum, maximum = -maximum_abs, maximum_abs
        scalar = np.clip((signed - minimum) / (maximum - minimum), 0.0, 1.0)
        if bool(parameters.get("height_invert", False)):
            scalar = 1.0 - scalar
        values = np.column_stack([scalar, scalar, scalar, np.ones_like(scalar)])
        image = default_bake_output("Height", internal, internal)
        image[map_valid] = values
        image = _padding_fill(image, map_valid, padding, occupied_uv=valid_uv)
        image = _downsample(image, supersampling)
        maps["Height"] = BakeMap("Height", "grayscale", image, "16-bit")
        timings["height_ms"] = (time.perf_counter() - map_started) * 1000.0
    else:
        minimum = maximum = 0.0

    if bool(parameters.get("bake_ambient_occlusion", True)):
        map_started = time.perf_counter()
        ao = _bake_ambient_occlusion(hit_positions, hit_normals, projection, parameters, context)
        values = np.column_stack([ao, ao, ao, np.ones_like(ao)])
        image = default_bake_output("Ambient Occlusion", internal, internal)
        image[map_valid] = values
        image = _padding_fill(image, map_valid, padding, occupied_uv=valid_uv)
        image = _downsample(image, supersampling)
        maps["Ambient Occlusion"] = BakeMap("Ambient Occlusion", "grayscale", image, "8-bit")
        timings["ao_ms"] = (time.perf_counter() - map_started) * 1000.0

    mask_scalar = map_valid.astype(np.float32)
    mask = _rgba(mask_scalar)
    mask = _downsample(mask, supersampling)
    maps["Projection Mask"] = BakeMap("Projection Mask", "grayscale", mask, "8-bit")

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    valid_signed = signed[np.isfinite(signed)]
    warnings = [value for value in (albedo_warning,) if value]
    if np.any(raster.overlap):
        warnings.append("Low Geometry contains overlapping UV pixels; the first triangle was baked in those pixels.")
    diagnostics: dict[str, Any] = {
        "backend": str(projection["backend"]),
        "resolution": resolution,
        "supersampling": supersampling,
        "internal_resolution": internal,
        "maps": tuple(maps.keys()),
        "high_vertices": high.vertex_count,
        "high_triangles": high.triangle_count,
        "low_vertices": low.vertex_count,
        "low_triangles": low.triangle_count,
        "uv_pixels": valid_count,
        "hit_pixels": hit_count,
        "missed_pixels": valid_count - hit_count,
        "hit_percent": 100.0 * hit_count / max(valid_count, 1),
        "front_hits": int(np.count_nonzero(projection["front_hit"])),
        "back_hits": int(np.count_nonzero(projection["back_hit"])),
        "overlap_pixels": int(np.count_nonzero(raster.overlap)),
        "front_distance": float(projection["front_distance"]),
        "back_distance": float(projection["back_distance"]),
        "ray_bias": float(projection["bias"]),
        "height_min": float(np.min(valid_signed)) if valid_signed.size else 0.0,
        "height_max": float(np.max(valid_signed)) if valid_signed.size else 0.0,
        "height_mean": float(np.mean(valid_signed)) if valid_signed.size else 0.0,
        "height_encoded_min": float(minimum),
        "height_encoded_max": float(maximum),
        "ao_samples": _ao_sample_count(parameters) if bool(parameters.get("bake_ambient_occlusion", True)) else 0,
        "padding_pixels": int(parameters.get("padding", 16)),
        "low_uv_zero_area_triangles": int(low_uv_info["zero_area_triangles"]),
        "low_uv_out_of_bounds_vertices": int(low_uv_info["out_of_bounds_vertices"]),
        "high_uv_usable": bool(high_uv_info["usable"]),
        "estimated_working_memory_bytes": estimated_working_memory,
        "raster_ms": raster_ms,
        "projection_ms": projection_ms,
        "elapsed_ms": elapsed_ms,
        "warnings": warnings,
        **timings,
    }
    if context is not None:
        context.progress(100, 100, "Publishing baked maps")
    return GeometryBakeResult(
        low.copy(name=str(parameters.get("name", "Baked Low Geometry") or "Baked Low Geometry")),
        maps,
        diagnostics,
    )


def _preview_output(result: GeometryBakeResult, parameters: Mapping[str, Any]) -> BakeMap:
    requested = str(parameters.get("preview_output", "Albedo"))
    if requested in result.maps:
        return result.maps[requested]
    for name in ("Albedo", "Normal", "Height", "Ambient Occlusion", "Projection Mask"):
        if name in result.maps:
            return result.maps[name]
    return BakeMap("Projection Mask", "grayscale", default_bake_output("Projection Mask", 256, 256))


def _publish_preview(
    result: GeometryBakeResult, parameters: Mapping[str, Any], context: GeometryEvalContext | None
) -> None:
    if context is None or context.render_mode.startswith("final"):
        return
    selected = _preview_output(result, parameters)
    context.preview_image = np.ascontiguousarray(selected.image, dtype=np.float32)
    context.preview_kind = selected.kind
    context.preview_details = (
        f"{selected.name} · {selected.image.shape[1]} × {selected.image.shape[0]} · "
        f"{float(result.diagnostics.get('hit_percent', 0.0)):.1f}% projected"
    )
    # Full map dictionary is consumed by the 3D geometry inspection path.  Keep
    # the legacy Base Colour field populated for older preview code.
    context.preview_material_texture = (
        result.maps.get("Albedo").image if result.maps.get("Albedo") is not None else None
    )
    context.preview_material_textures = {
        channel: item.image
        for channel, item in (
            ("Base Colour", result.maps.get("Albedo")),
            ("Normal", result.maps.get("Normal")),
            ("Height", result.maps.get("Height")),
            ("Ambient Occlusion", result.maps.get("Ambient Occlusion")),
        )
        if item is not None
    }


def evaluate_manual_high_to_low_bake(
    inputs: Mapping[str, Any],
    parameters: Mapping[str, Any],
    context: GeometryEvalContext | None = None,
) -> GeometryData:
    """Execute or present the transactional high-to-low bake result."""
    payload = str(parameters.get("_manual_result_data", "") or "")
    previous = decode_bake_parameters(parameters) if payload else None
    run_serial = int(parameters.get("_manual_run_serial", 0) or 0)
    completed_serial = int(parameters.get("_manual_completed_serial", 0) or 0)
    should_execute = run_serial > completed_serial

    if should_execute:
        high = inputs.get("High Geometry")
        low = inputs.get("Low Geometry")
        if not isinstance(high, GeometryData):
            raise ValueError("High Geometry is not connected")
        if not isinstance(low, GeometryData):
            raise ValueError("Low Geometry is not connected")
        high_albedo = inputs.get("High Albedo")
        cage = inputs.get("Cage Geometry")
        try:
            result = _perform_bake(
                high, low,
                np.asarray(high_albedo, dtype=np.float32) if isinstance(high_albedo, np.ndarray) else None,
                cage if isinstance(cage, GeometryData) else None,
                parameters,
                context,
            )
            encoded = encode_bake_result(result)
            signature = _bake_signature(
                high, low,
                np.asarray(high_albedo, dtype=np.float32) if isinstance(high_albedo, np.ndarray) else None,
                cage if isinstance(cage, GeometryData) else None,
                parameters,
            )
            if context is not None:
                metadata: dict[str, Any] = {
                    "_manual_status": "Up to Date",
                    "_manual_completed_serial": run_serial,
                    "_manual_signature": signature,
                    "_manual_result_data": encoded,
                    "_manual_result_revision": hashlib.blake2b(
                        encoded.encode("ascii"), digest_size=20
                    ).hexdigest(),
                    "_manual_last_error": "",
                    "_manual_applied_parameters": {
                        name: parameters.get(name) for name in BAKE_PARAMETER_NAMES
                    },
                }
                for key, value in result.diagnostics.items():
                    metadata[f"_bake_{key}"] = value
                context.report_metadata(metadata)
            active = result
        except GeometryEvaluationCancelled:
            raise
        except Exception as exc:
            if previous is None:
                raise
            active = previous
            if context is not None:
                context.report_metadata({
                    "_manual_status": "Failed",
                    "_manual_completed_serial": run_serial,
                    "_manual_last_error": f"{type(exc).__name__}: {exc}",
                })
    elif previous is not None:
        active = previous
        if context is not None:
            context.report_metadata({
                "_manual_status": str(parameters.get("_manual_status", "Up to Date") or "Up to Date"),
                "_manual_last_error": str(parameters.get("_manual_last_error", "") or ""),
            })
    else:
        low = inputs.get("Low Geometry")
        if not isinstance(low, GeometryData):
            raise ValueError("Low Geometry is not connected")
        active = GeometryBakeResult(
            low.copy(name=str(parameters.get("name", "Baked Low Geometry") or "Baked Low Geometry")),
            {},
            {"backend": "Not run", "hit_percent": 0.0, "maps": ()},
        )
        if context is not None:
            context.report_metadata({"_manual_status": "Not Run", "_manual_last_error": ""})

    _publish_preview(active, parameters, context)
    desired_name = str(parameters.get("name", "Baked Low Geometry") or "Baked Low Geometry")
    if active.low_geometry.name != desired_name:
        return active.low_geometry.copy(name=desired_name)
    return active.low_geometry
