"""Procedural geometry graph values and mesh export helpers.

Geometry is deliberately independent from image resolution.  A graph geometry
value owns interleaved position/normal/UV vertices plus indexed triangles, which
matches the existing 3D preview renderer while remaining usable by future mesh
processing nodes and exporters.
"""

from __future__ import annotations

from array import array
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping

import base64
import binascii
import hashlib
import io
import math
import threading
import numpy as np


UV_ORIGIN_TOP_LEFT = "top-left"
UV_ORIGIN_BOTTOM_LEFT = "bottom-left"


def normalise_uv_origin(value: str | None) -> str:
    text = str(value or UV_ORIGIN_TOP_LEFT).strip().casefold().replace("_", "-")
    if text in {"bottom-left", "bottomleft", "v-up", "standard", "obj"}:
        return UV_ORIGIN_BOTTOM_LEFT
    return UV_ORIGIN_TOP_LEFT


def convert_uv_origin(vertices: np.ndarray, source: str, target: str) -> np.ndarray:
    """Return vertices expressed in the requested UV vertical-origin convention."""
    source_origin = normalise_uv_origin(source)
    target_origin = normalise_uv_origin(target)
    values = np.asarray(vertices, dtype=np.float32)
    if source_origin == target_origin:
        return values
    converted = np.ascontiguousarray(values.copy(), dtype=np.float32)
    converted[:, 7] = 1.0 - converted[:, 7]
    return converted


@dataclass(slots=True)
class GeometryData:
    """Indexed triangle geometry with one normal and UV per vertex.

    ``vertices`` is a float32 ``N x 8`` array containing position XYZ, normal
    XYZ and UV XY.  ``indices`` is a flat uint32 triangle index array.
    """

    vertices: np.ndarray
    indices: np.ndarray
    name: str = "Geometry"
    uv_origin: str = UV_ORIGIN_TOP_LEFT

    def __post_init__(self) -> None:
        self.vertices = np.ascontiguousarray(self.vertices, dtype=np.float32).reshape(-1, 8)
        self.indices = np.ascontiguousarray(self.indices, dtype=np.uint32).reshape(-1)
        self.uv_origin = normalise_uv_origin(self.uv_origin)
        if self.indices.size % 3:
            raise ValueError("Geometry indices must describe triangles")
        if self.indices.size and int(self.indices.max()) >= self.vertices.shape[0]:
            raise ValueError("Geometry index references a missing vertex")
        if not np.isfinite(self.vertices).all():
            raise ValueError("Geometry vertices contain non-finite values")

    @property
    def vertex_count(self) -> int:
        return int(self.vertices.shape[0])

    @property
    def triangle_count(self) -> int:
        return int(self.indices.size // 3)

    @property
    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        if not self.vertex_count:
            zero = np.zeros(3, dtype=np.float32)
            return zero.copy(), zero.copy()
        positions = self.vertices[:, :3]
        return positions.min(axis=0), positions.max(axis=0)

    def copy(self, *, name: str | None = None) -> "GeometryData":
        return GeometryData(
            self.vertices.copy(), self.indices.copy(), name or self.name, self.uv_origin
        )

    def vertices_with_uv_origin(self, target: str) -> np.ndarray:
        return convert_uv_origin(self.vertices, self.uv_origin, target)


class GeometryEvaluationCancelled(RuntimeError):
    """Raised when a background geometry request has been superseded."""


@dataclass(slots=True)
class GeometryEvalContext:
    """Cooperative callbacks available to expensive geometry evaluators."""

    node_uid: str = ""
    node_name: str = "Geometry"
    cancel_check: Callable[[], bool] | None = None
    progress_callback: Callable[[int, int, str], None] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    width: int = 1024
    height: int = 1024
    preview_options: dict[str, Any] = field(default_factory=dict)
    preview_image: np.ndarray | None = None
    preview_material_texture: np.ndarray | None = None
    preview_material_textures: dict[str, np.ndarray] = field(default_factory=dict)
    preview_details: str = ""
    preview_kind: str = ""
    render_mode: str = "preview_3d"

    def checkpoint(self) -> None:
        if self.cancel_check is not None and self.cancel_check():
            raise GeometryEvaluationCancelled(f"{self.node_name} evaluation was cancelled")

    def progress(self, current: int, total: int, message: str) -> None:
        self.checkpoint()
        if self.progress_callback is not None:
            self.progress_callback(int(current), int(total), str(message or self.node_name))

    def report_metadata(self, values: Mapping[str, Any]) -> None:
        self.metadata.update(dict(values))




_OBJ_CACHE: "OrderedDict[tuple[Any, ...], tuple[GeometryData, dict[str, Any], int]]" = OrderedDict()
_OBJ_CACHE_LOCK = threading.RLock()
_OBJ_CACHE_BUDGET = 768 * 1024 * 1024
_DEFERRED_METADATA_BYTES = 32 * 1024 * 1024


def _mesh_source_bytes_or_path(parameters: Mapping[str, Any]):
    encoded = str(parameters.get("_embedded_data", "") or "").strip()
    if encoded:
        try:
            return io.BytesIO(base64.b64decode(encoded, validate=True))
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Embedded OBJ data is damaged") from exc
    path = Path(str(parameters.get("path", "") or "")).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"OBJ source not found: {path}")
    return path


def _mesh_source_cache_key(parameters: Mapping[str, Any]) -> tuple[tuple[Any, ...], int]:
    encoded = str(parameters.get("_embedded_data", "") or "").strip()
    if encoded:
        digest = hashlib.blake2b(encoded.encode("ascii", errors="ignore"), digest_size=16).hexdigest()
        estimated = (len(encoded) * 3) // 4
        return ("embedded", digest, len(encoded)), estimated
    path = Path(str(parameters.get("path", "") or "")).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"OBJ source not found: {path}")
    stat = path.stat()
    return ("path", str(path.resolve()), int(stat.st_mtime_ns), int(stat.st_size)), int(stat.st_size)


def _obj_cache_get(key: tuple[Any, ...]) -> tuple[GeometryData, dict[str, Any]] | None:
    with _OBJ_CACHE_LOCK:
        value = _OBJ_CACHE.get(key)
        if value is None:
            return None
        _OBJ_CACHE.move_to_end(key)
        geometry, metadata, _bytes_used = value
        return GeometryData(geometry.vertices, geometry.indices, geometry.name, geometry.uv_origin), dict(metadata)


def _obj_cache_put(key: tuple[Any, ...], geometry: GeometryData, metadata: Mapping[str, Any]) -> None:
    bytes_used = int(geometry.vertices.nbytes + geometry.indices.nbytes)
    with _OBJ_CACHE_LOCK:
        _OBJ_CACHE[key] = (geometry, dict(metadata), bytes_used)
        _OBJ_CACHE.move_to_end(key)
        total = sum(item[2] for item in _OBJ_CACHE.values())
        while total > _OBJ_CACHE_BUDGET and len(_OBJ_CACHE) > 1:
            _old_key, old = _OBJ_CACHE.popitem(last=False)
            total -= old[2]


def _obj_index(value: str, count: int, label: str, line_number: int) -> int:
    try:
        raw = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid OBJ {label} index on line {line_number}") from exc
    if raw == 0:
        raise ValueError(f"OBJ {label} index 0 is invalid on line {line_number}")
    resolved = raw - 1 if raw > 0 else count + raw
    if resolved < 0 or resolved >= count:
        raise ValueError(f"OBJ {label} index {raw} is out of range on line {line_number}")
    return resolved


def _parse_obj_lines(
    lines,
    *,
    fallback_name: str = "Imported Mesh",
    total_bytes: int = 0,
    context: GeometryEvalContext | None = None,
) -> tuple[GeometryData, dict[str, Any]]:
    """Stream a Wavefront OBJ into compact arrays.

    The previous importer decoded the whole file, retained every polygon corner
    in Python tuples, and then constructed the output in a second pass. That was
    tolerable for small assets but multiplied memory use for photogrammetry
    scans. This parser creates interleaved seam vertices and triangles as lines
    arrive, keeping peak memory much closer to the final mesh size.
    """

    positions = array("f")
    texcoords = array("f")
    normals = array("f")
    output_positions = array("f")
    output_uvs = array("f")
    output_normals = array("f")
    output_position_indices = array("I")
    output_indices = array("I")
    vertex_map: dict[tuple[int, int | None, int | None], int] = {}
    object_names: list[str] = []
    object_name_set: set[str] = set()
    has_uvs = True
    has_normals = True
    triangle_count = 0
    bytes_seen = 0

    def position_value(index: int) -> tuple[float, float, float]:
        offset = index * 3
        return positions[offset], positions[offset + 1], positions[offset + 2]

    def uv_value(index: int | None) -> tuple[float, float]:
        if index is None:
            return 0.0, 0.0
        offset = index * 2
        return texcoords[offset], texcoords[offset + 1]

    def normal_value(index: int | None) -> tuple[float, float, float]:
        if index is None:
            return 0.0, 0.0, 0.0
        offset = index * 3
        return normals[offset], normals[offset + 1], normals[offset + 2]

    for line_number, raw_line in enumerate(lines, 1):
        if context is not None and (line_number & 8191) == 0:
            context.checkpoint()
            if total_bytes > 0:
                # Character count is an intentionally cheap approximation; OBJ
                # numeric syntax is overwhelmingly ASCII.
                context.progress(min(bytes_seen, total_bytes), total_bytes, "Importing OBJ mesh")
            else:
                context.progress(line_number, 0, "Importing OBJ mesh")
        bytes_seen += len(raw_line)
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        keyword = parts[0].casefold()
        values = parts[1:]
        if keyword == "v":
            if len(values) < 3:
                raise ValueError(f"OBJ vertex on line {line_number} has fewer than three coordinates")
            try:
                positions.extend((float(values[0]), float(values[1]), float(values[2])))
            except ValueError as exc:
                raise ValueError(f"Invalid OBJ vertex on line {line_number}") from exc
        elif keyword == "vt":
            if len(values) < 2:
                raise ValueError(f"OBJ texture coordinate on line {line_number} has fewer than two values")
            try:
                texcoords.extend((float(values[0]), float(values[1])))
            except ValueError as exc:
                raise ValueError(f"Invalid OBJ texture coordinate on line {line_number}") from exc
        elif keyword == "vn":
            if len(values) < 3:
                raise ValueError(f"OBJ normal on line {line_number} has fewer than three coordinates")
            try:
                normals.extend((float(values[0]), float(values[1]), float(values[2])))
            except ValueError as exc:
                raise ValueError(f"Invalid OBJ normal on line {line_number}") from exc
        elif keyword in {"o", "g"} and values:
            name = " ".join(values).strip()
            if name and name not in object_name_set:
                object_name_set.add(name)
                object_names.append(name)
        elif keyword == "f":
            if len(values) < 3:
                raise ValueError(f"OBJ face on line {line_number} has fewer than three corners")
            corners: list[tuple[int, int | None, int | None]] = []
            position_count = len(positions) // 3
            uv_count = len(texcoords) // 2
            normal_count = len(normals) // 3
            for token in values:
                fields = token.split("/")
                if not fields or not fields[0]:
                    raise ValueError(f"OBJ face corner on line {line_number} has no position index")
                position_index = _obj_index(fields[0], position_count, "position", line_number)
                uv_index = None
                normal_index = None
                if len(fields) > 1 and fields[1]:
                    uv_index = _obj_index(fields[1], uv_count, "UV", line_number)
                else:
                    has_uvs = False
                if len(fields) > 2 and fields[2]:
                    normal_index = _obj_index(fields[2], normal_count, "normal", line_number)
                else:
                    has_normals = False
                corners.append((position_index, uv_index, normal_index))

            for fan_index in range(1, len(corners) - 1):
                triangle_count += 1
                if triangle_count > 5_000_000:
                    raise ValueError("OBJ exceeds the five-million-triangle import safety limit")
                for corner in (corners[0], corners[fan_index], corners[fan_index + 1]):
                    output_index = vertex_map.get(corner)
                    if output_index is None:
                        output_index = len(output_position_indices)
                        vertex_map[corner] = output_index
                        position_index, uv_index, normal_index = corner
                        output_positions.extend(position_value(position_index))
                        output_position_indices.append(position_index)
                        output_uvs.extend(uv_value(uv_index))
                        output_normals.extend(normal_value(normal_index))
                    output_indices.append(output_index)

    if context is not None:
        context.checkpoint()
    if not positions:
        raise ValueError("OBJ contains no vertex positions")
    if not output_indices:
        raise ValueError("OBJ contains no polygon faces")

    positions_array = np.frombuffer(output_positions, dtype=np.float32).reshape(-1, 3)
    uvs_array = np.frombuffer(output_uvs, dtype=np.float32).reshape(-1, 2)
    indices_array = np.frombuffer(output_indices, dtype=np.uint32)

    if has_normals:
        normals_array = np.frombuffer(output_normals, dtype=np.float32).reshape(-1, 3).copy()
        lengths = np.linalg.norm(normals_array, axis=1, keepdims=True)
        normals_array /= np.maximum(lengths, 1.0e-8)
    else:
        if context is not None:
            context.progress(1, 3, "Generating smooth import normals")
        original_position_count = len(positions) // 3
        position_accum = np.zeros((original_position_count, 3), dtype=np.float64)
        tri_indices = indices_array.reshape(-1, 3)
        points = positions_array[tri_indices]
        face_normals = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0]).astype(np.float64)
        position_ids = np.frombuffer(output_position_indices, dtype=np.uint32).astype(np.int64, copy=False)
        triangle_position_ids = position_ids[tri_indices]
        np.add.at(position_accum, triangle_position_ids[:, 0], face_normals)
        np.add.at(position_accum, triangle_position_ids[:, 1], face_normals)
        np.add.at(position_accum, triangle_position_ids[:, 2], face_normals)
        lengths = np.linalg.norm(position_accum, axis=1, keepdims=True)
        smooth = position_accum / np.maximum(lengths, 1.0e-12)
        smooth[lengths[:, 0] <= 1.0e-12] = np.asarray((0.0, 1.0, 0.0), dtype=np.float64)
        normals_array = smooth[position_ids].astype(np.float32)

    mesh_name = object_names[0] if object_names else str(fallback_name or "Imported Mesh")
    geometry = _interleaved_geometry(
        positions_array,
        normals_array,
        uvs_array,
        indices_array,
        mesh_name,
        uv_origin=UV_ORIGIN_BOTTOM_LEFT,
    )
    if context is not None:
        context.progress(2, 3, "Diagnosing imported mesh topology")
    from .mesh_processing import diagnose_mesh

    diagnostics = diagnose_mesh(
        geometry.vertices,
        geometry.indices,
        cancel_check=context.cancel_check if context is not None else None,
    )
    metadata = {
        "vertex_count": geometry.vertex_count,
        "triangle_count": geometry.triangle_count,
        "has_uvs": bool(has_uvs),
        "has_normals": bool(has_normals),
        "object_count": max(len(object_names), 1),
        "name": mesh_name,
        **diagnostics.as_metadata(),
    }
    if context is not None:
        context.progress(3, 3, "OBJ import complete")
    return geometry, metadata


def _parse_obj_text(
    text: str,
    *,
    fallback_name: str = "Imported Mesh",
    context: GeometryEvalContext | None = None,
) -> tuple[GeometryData, dict[str, Any]]:
    return _parse_obj_lines(
        io.StringIO(text),
        fallback_name=fallback_name,
        total_bytes=len(text),
        context=context,
    )


def load_obj_geometry(
    parameters: Mapping[str, Any],
    context: GeometryEvalContext | None = None,
) -> tuple[GeometryData, dict[str, Any]]:
    key, source_bytes = _mesh_source_cache_key(parameters)
    cached = _obj_cache_get(key)
    if cached is not None:
        if context is not None:
            context.progress(1, 1, "Reusing cached OBJ geometry")
        return cached

    source = _mesh_source_bytes_or_path(parameters)
    if isinstance(source, Path):
        fallback_name = source.stem
        # Numeric OBJ data is ASCII. Replacement decoding only affects unusual
        # object/group names and lets legacy local encodings stream safely.
        with source.open("r", encoding="utf-8-sig", errors="replace", newline=None) as handle:
            geometry, metadata = _parse_obj_lines(
                handle,
                fallback_name=fallback_name,
                total_bytes=source_bytes,
                context=context,
            )
    else:
        fallback_name = Path(str(parameters.get("_embedded_name", "") or "Imported Mesh")).stem
        wrapper = io.TextIOWrapper(source, encoding="utf-8-sig", errors="replace", newline=None)
        try:
            geometry, metadata = _parse_obj_lines(
                wrapper,
                fallback_name=fallback_name,
                total_bytes=source_bytes,
                context=context,
            )
        finally:
            wrapper.detach()
    _obj_cache_put(key, geometry, metadata)
    return GeometryData(geometry.vertices, geometry.indices, geometry.name, geometry.uv_origin), dict(metadata)


def _mesh_metadata_parameters(metadata: Mapping[str, Any]) -> dict[str, Any]:
    names = (
        "vertex_count", "triangle_count", "has_uvs", "has_normals", "object_count",
        "name", "unique_position_count", "boundary_edges", "non_manifold_edges",
        "degenerate_triangles", "duplicate_triangles", "connected_components",
        "uv_seam_vertices", "hard_normal_seam_vertices", "memory_bytes",
        "closed_manifold",
    )
    return {
        f"_source_{name}": metadata[name]
        for name in names
        if name in metadata
    }


def refresh_mesh_metadata(parameters: MutableMapping[str, Any] | dict[str, Any]) -> None:
    """Refresh Mesh Input information without blocking on giant scan files."""

    try:
        _key, source_bytes = _mesh_source_cache_key(parameters)
        parameters["_source_file_bytes"] = int(source_bytes)
        if source_bytes >= _DEFERRED_METADATA_BYTES:
            parameters["_source_pending"] = True
            parameters.pop("_source_error", None)
            return
        _geometry, metadata = load_obj_geometry(parameters)
        parameters.update(_mesh_metadata_parameters(metadata))
        parameters["_source_pending"] = False
        parameters.pop("_source_error", None)
    except Exception as exc:
        for key in tuple(parameters):
            if key.startswith("_source_") and key not in {"_source_mode", "_source_path"}:
                parameters.pop(key, None)
        parameters["_source_error"] = str(exc)


def evaluate_mesh_input_geometry(
    _inputs: Mapping[str, GeometryData],
    parameters: Mapping[str, Any],
    context: GeometryEvalContext | None = None,
) -> GeometryData:
    geometry, metadata = load_obj_geometry(parameters, context=context)
    if context is not None:
        context.report_metadata(_mesh_metadata_parameters(metadata))
        context.report_metadata({"_source_pending": False, "_source_error": ""})
    requested_name = str(parameters.get("name", "") or "").strip()
    if requested_name:
        geometry.name = requested_name
    return geometry


def _interleaved_geometry(
    positions: np.ndarray,
    normals: np.ndarray,
    uvs: np.ndarray,
    indices: np.ndarray,
    name: str,
    *,
    uv_origin: str = UV_ORIGIN_TOP_LEFT,
) -> GeometryData:
    vertices = np.concatenate((positions, normals, uvs), axis=1)
    return GeometryData(vertices, indices, name, uv_origin)


def _shift_to_positive_bounds(positions: np.ndarray) -> np.ndarray:
    minimum = positions.min(axis=0, keepdims=True)
    return positions - minimum


def _apply_uv_tiles(uvs: np.ndarray, tiles_u: int, tiles_v: int) -> np.ndarray:
    tiles_u = min(max(int(tiles_u), 1), 256)
    tiles_v = min(max(int(tiles_v), 1), 256)
    scaled = np.asarray(uvs, dtype=np.float32).copy()
    scaled[:, 0] *= float(tiles_u)
    scaled[:, 1] *= float(tiles_v)
    return scaled


def _apply_origin_offset(positions: np.ndarray, origin_x: float, origin_y: float, origin_z: float) -> np.ndarray:
    adjusted = np.asarray(positions, dtype=np.float32).copy()
    minimum = adjusted.min(axis=0)
    maximum = adjusted.max(axis=0)
    extents = maximum - minimum
    pivot = minimum + extents * np.asarray((
        (min(max(float(origin_x), -1.0), 1.0) + 1.0) * 0.5,
        (min(max(float(origin_y), -1.0), 1.0) + 1.0) * 0.5,
        (min(max(float(origin_z), -1.0), 1.0) + 1.0) * 0.5,
    ), dtype=np.float32)
    adjusted -= pivot
    return adjusted


def _euler_rotation_matrix(rotation_x: float, rotation_y: float, rotation_z: float) -> np.ndarray:
    """Return a right-handed XYZ Euler rotation matrix in degrees.

    Vertices are first rotated around local X, then Y, then Z.  Geometry is
    translated to its selected origin before this matrix is applied, so zero is
    the stable pivot for preview and export.
    """

    x = math.radians(float(rotation_x) % 360.0)
    y = math.radians(float(rotation_y) % 360.0)
    z = math.radians(float(rotation_z) % 360.0)
    sx, cx = math.sin(x), math.cos(x)
    sy, cy = math.sin(y), math.cos(y)
    sz, cz = math.sin(z), math.cos(z)
    rotate_x = np.asarray(
        ((1.0, 0.0, 0.0), (0.0, cx, -sx), (0.0, sx, cx)),
        dtype=np.float32,
    )
    rotate_y = np.asarray(
        ((cy, 0.0, sy), (0.0, 1.0, 0.0), (-sy, 0.0, cy)),
        dtype=np.float32,
    )
    rotate_z = np.asarray(
        ((cz, -sz, 0.0), (sz, cz, 0.0), (0.0, 0.0, 1.0)),
        dtype=np.float32,
    )
    return rotate_z @ rotate_y @ rotate_x


def _apply_rotation(
    positions: np.ndarray,
    normals: np.ndarray,
    rotation_x: float,
    rotation_y: float,
    rotation_z: float,
) -> tuple[np.ndarray, np.ndarray]:
    matrix = _euler_rotation_matrix(rotation_x, rotation_y, rotation_z)
    rotated_positions = np.asarray(positions, dtype=np.float32) @ matrix.T
    rotated_normals = np.asarray(normals, dtype=np.float32) @ matrix.T
    lengths = np.linalg.norm(rotated_normals, axis=1, keepdims=True)
    rotated_normals = rotated_normals / np.maximum(lengths, 1.0e-8)
    return rotated_positions, rotated_normals


def _finalise_geometry(
    positions: np.ndarray,
    normals: np.ndarray,
    uvs: np.ndarray,
    indices: np.ndarray,
    name: str,
    *,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
    origin_z: float = 0.0,
    rotation_x: float = 0.0,
    rotation_y: float = 0.0,
    rotation_z: float = 0.0,
    uv_tiles_u: int = 1,
    uv_tiles_v: int = 1,
) -> GeometryData:
    pivoted_positions = _apply_origin_offset(positions, origin_x, origin_y, origin_z)
    rotated_positions, rotated_normals = _apply_rotation(
        pivoted_positions,
        np.asarray(normals, dtype=np.float32),
        rotation_x,
        rotation_y,
        rotation_z,
    )
    return _interleaved_geometry(
        rotated_positions,
        rotated_normals,
        _apply_uv_tiles(np.asarray(uvs, dtype=np.float32), uv_tiles_u, uv_tiles_v),
        np.asarray(indices, dtype=np.uint32),
        name,
    )


def _append_patch(
    positions: list[list[float]],
    normals: list[list[float]],
    uvs: list[list[float]],
    indices: list[int],
    bottom_left: tuple[float, float, float],
    bottom_right: tuple[float, float, float],
    top_left: tuple[float, float, float],
    top_right: tuple[float, float, float],
    normal: tuple[float, float, float],
    subdivisions_u: int,
    subdivisions_v: int,
) -> None:
    subdivisions_u = max(int(subdivisions_u), 1)
    subdivisions_v = max(int(subdivisions_v), 1)
    start = len(positions)
    bl = np.asarray(bottom_left, dtype=np.float32)
    br = np.asarray(bottom_right, dtype=np.float32)
    tl = np.asarray(top_left, dtype=np.float32)
    tr = np.asarray(top_right, dtype=np.float32)
    normal_value = [float(normal[0]), float(normal[1]), float(normal[2])]
    row = subdivisions_u + 1
    for v_index in range(subdivisions_v + 1):
        v = v_index / subdivisions_v
        left = bl * (1.0 - v) + tl * v
        right = br * (1.0 - v) + tr * v
        for u_index in range(subdivisions_u + 1):
            u = u_index / subdivisions_u
            point = left * (1.0 - u) + right * u
            positions.append([float(point[0]), float(point[1]), float(point[2])])
            normals.append(normal_value)
            uvs.append([float(u), 1.0 - float(v)])
    for y in range(subdivisions_v):
        for x in range(subdivisions_u):
            a = start + y * row + x
            b = a + 1
            c = a + row
            d = c + 1
            indices.extend((a, b, c, b, d, c))


def _rotation_matrix_for_axis(orientation: str) -> np.ndarray:
    orientation = str(orientation or "Axis Y")
    if orientation == "Axis X":
        return np.asarray(
            (
                (0.0, 1.0, 0.0),
                (-1.0, 0.0, 0.0),
                (0.0, 0.0, 1.0),
            ),
            dtype=np.float32,
        )
    if orientation == "Axis Z":
        return np.asarray(
            (
                (1.0, 0.0, 0.0),
                (0.0, 0.0, -1.0),
                (0.0, 1.0, 0.0),
            ),
            dtype=np.float32,
        )
    return np.eye(3, dtype=np.float32)


def plane_geometry(
    width: float = 2.0,
    height: float = 2.0,
    subdivisions_x: int = 16,
    subdivisions_y: int = 16,
    orientation: str = "Horizontal (XZ)",
    *,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
    origin_z: float = 0.0,
    rotation_x: float = 0.0,
    rotation_y: float = 0.0,
    rotation_z: float = 0.0,
    uv_tiles_u: int = 1,
    uv_tiles_v: int = 1,
    name: str = "Geometry Plane",
) -> GeometryData:
    """Create a centred UV-mapped subdivided plane.

    UVs always span 0–1.  Triangle winding and normals face the positive axis
    implied by the selected orientation.
    """

    width = max(float(width), 1.0e-6)
    height = max(float(height), 1.0e-6)
    subdivisions_x = min(max(int(subdivisions_x), 1), 512)
    subdivisions_y = min(max(int(subdivisions_y), 1), 512)

    columns = subdivisions_x + 1
    rows = subdivisions_y + 1
    u = np.linspace(0.0, 1.0, columns, dtype=np.float32)
    v = np.linspace(0.0, 1.0, rows, dtype=np.float32)
    uu, vv = np.meshgrid(u, v)
    x = (uu - 0.5) * width
    y = (0.5 - vv) * height
    zeros = np.zeros_like(x)

    orientation = str(orientation or "Horizontal (XZ)")
    if orientation == "Vertical (XY)":
        positions = np.stack((x, y, zeros), axis=2)
        normals = np.zeros_like(positions)
        normals[..., 2] = 1.0
    elif orientation == "Vertical (YZ)":
        positions = np.stack((zeros, y, x), axis=2)
        normals = np.zeros_like(positions)
        normals[..., 0] = 1.0
    else:
        # Match the existing terrain-plane convention: +Y normal, U left/right,
        # and V top/bottom while world Z runs away from the viewer.
        positions = np.stack((x, zeros, y), axis=2)
        normals = np.zeros_like(positions)
        normals[..., 1] = 1.0
    uvs = np.stack((uu, vv), axis=2).reshape(-1, 2)
    positions = positions.reshape(-1, 3)
    normals = normals.reshape(-1, 3)

    row = np.arange(subdivisions_y, dtype=np.uint32)[:, None] * columns
    col = np.arange(subdivisions_x, dtype=np.uint32)[None, :]
    top_left = row + col
    top_right = top_left + 1
    bottom_left = top_left + columns
    bottom_right = bottom_left + 1
    if orientation == "Vertical (XY)":
        # Reverse winding so the front face agrees with the declared +Z normals.
        triangles = (top_left, bottom_left, top_right, top_right, bottom_left, bottom_right)
    else:
        triangles = (top_left, top_right, bottom_left, top_right, bottom_right, bottom_left)
    indices = np.stack(triangles, axis=2).reshape(-1)
    return _finalise_geometry(
        positions,
        normals,
        uvs,
        indices,
        name,
        origin_x=origin_x,
        origin_y=origin_y,
        origin_z=origin_z,
        rotation_x=rotation_x,
        rotation_y=rotation_y,
        rotation_z=rotation_z,
        uv_tiles_u=uv_tiles_u,
        uv_tiles_v=uv_tiles_v,
    )


def box_geometry(
    width: float = 2.0,
    height: float = 2.0,
    depth: float = 2.0,
    subdivisions_x: int = 1,
    subdivisions_y: int = 1,
    subdivisions_z: int = 1,
    *,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
    origin_z: float = 0.0,
    rotation_x: float = 0.0,
    rotation_y: float = 0.0,
    rotation_z: float = 0.0,
    uv_tiles_u: int = 1,
    uv_tiles_v: int = 1,
    name: str = "Geometry Box",
) -> GeometryData:
    """Create a UV-mapped box with hard edges and one 0–1 UV island per face."""

    width = max(float(width), 1.0e-6)
    height = max(float(height), 1.0e-6)
    depth = max(float(depth), 1.0e-6)
    subdivisions_x = min(max(int(subdivisions_x), 1), 256)
    subdivisions_y = min(max(int(subdivisions_y), 1), 256)
    subdivisions_z = min(max(int(subdivisions_z), 1), 256)

    hx = width * 0.5
    hy = height * 0.5
    hz = depth * 0.5

    positions: list[list[float]] = []
    normals: list[list[float]] = []
    uvs: list[list[float]] = []
    indices: list[int] = []

    # Front/back use X/Y tessellation.
    _append_patch(
        positions,
        normals,
        uvs,
        indices,
        (-hx, -hy, hz),
        (hx, -hy, hz),
        (-hx, hy, hz),
        (hx, hy, hz),
        (0.0, 0.0, 1.0),
        subdivisions_x,
        subdivisions_y,
    )
    _append_patch(
        positions,
        normals,
        uvs,
        indices,
        (hx, -hy, -hz),
        (-hx, -hy, -hz),
        (hx, hy, -hz),
        (-hx, hy, -hz),
        (0.0, 0.0, -1.0),
        subdivisions_x,
        subdivisions_y,
    )
    # Left/right use Z/Y tessellation.
    _append_patch(
        positions,
        normals,
        uvs,
        indices,
        (hx, -hy, hz),
        (hx, -hy, -hz),
        (hx, hy, hz),
        (hx, hy, -hz),
        (1.0, 0.0, 0.0),
        subdivisions_z,
        subdivisions_y,
    )
    _append_patch(
        positions,
        normals,
        uvs,
        indices,
        (-hx, -hy, -hz),
        (-hx, -hy, hz),
        (-hx, hy, -hz),
        (-hx, hy, hz),
        (-1.0, 0.0, 0.0),
        subdivisions_z,
        subdivisions_y,
    )
    # Top/bottom use X/Z tessellation.
    _append_patch(
        positions,
        normals,
        uvs,
        indices,
        (-hx, hy, hz),
        (hx, hy, hz),
        (-hx, hy, -hz),
        (hx, hy, -hz),
        (0.0, 1.0, 0.0),
        subdivisions_x,
        subdivisions_z,
    )
    _append_patch(
        positions,
        normals,
        uvs,
        indices,
        (-hx, -hy, -hz),
        (hx, -hy, -hz),
        (-hx, -hy, hz),
        (hx, -hy, hz),
        (0.0, -1.0, 0.0),
        subdivisions_x,
        subdivisions_z,
    )

    return _finalise_geometry(
        np.asarray(positions, dtype=np.float32),
        np.asarray(normals, dtype=np.float32),
        np.asarray(uvs, dtype=np.float32),
        np.asarray(indices, dtype=np.uint32),
        name,
        origin_x=origin_x,
        origin_y=origin_y,
        origin_z=origin_z,
        rotation_x=rotation_x,
        rotation_y=rotation_y,
        rotation_z=rotation_z,
        uv_tiles_u=uv_tiles_u,
        uv_tiles_v=uv_tiles_v,
    )


def cylinder_geometry(
    radius: float = 1.0,
    height: float = 2.0,
    radial_segments: int = 32,
    height_segments: int = 1,
    *,
    top_radius_offset: float = 0.0,
    bottom_radius_offset: float = 0.0,
    caps: bool = True,
    cap_segments: int = 1,
    smooth_sides: bool = True,
    orientation: str = "Axis Y",
    origin_x: float = 0.0,
    origin_y: float = 0.0,
    origin_z: float = 0.0,
    rotation_x: float = 0.0,
    rotation_y: float = 0.0,
    rotation_z: float = 0.0,
    uv_tiles_u: int = 1,
    uv_tiles_v: int = 1,
    name: str = "Geometry Cylinder",
) -> GeometryData:
    """Create a UV-mapped cylinder, cone or frustum with an explicit wall seam.

    ``top_radius_offset`` and ``bottom_radius_offset`` are added to the main
    radius.  Final radii are clamped at zero, so a sufficiently negative offset
    forms a true cone tip without producing negative/inverted rings.
    """

    radius = max(float(radius), 1.0e-6)
    height = max(float(height), 1.0e-6)
    radial_segments = min(max(int(radial_segments), 3), 512)
    height_segments = min(max(int(height_segments), 1), 512)
    cap_segments = min(max(int(cap_segments), 1), 128)
    bottom_radius = max(radius + float(bottom_radius_offset), 0.0)
    top_radius = max(radius + float(top_radius_offset), 0.0)
    if bottom_radius <= 1.0e-8 and top_radius <= 1.0e-8:
        raise ValueError("Cylinder top and bottom radii cannot both collapse to zero")

    positions: list[list[float]] = []
    normals: list[list[float]] = []
    uvs: list[list[float]] = []
    indices: list[int] = []

    row = radial_segments + 1
    half_height = height * 0.5
    radius_slope = (top_radius - bottom_radius) / height
    radial_normal_scale = 1.0 / max(math.sqrt(1.0 + radius_slope * radius_slope), 1.0e-8)
    normal_y = -radius_slope * radial_normal_scale
    tip_epsilon = 1.0e-8

    def ring_radius(y_index: int) -> float:
        amount = y_index / height_segments
        return bottom_radius * (1.0 - amount) + top_radius * amount

    if smooth_sides:
        ring_starts: list[int] = []
        ring_radii: list[float] = []
        for y_index in range(height_segments + 1):
            y_amount = y_index / height_segments
            y = -half_height + y_amount * height
            current_radius = ring_radius(y_index)
            ring_starts.append(len(positions))
            ring_radii.append(current_radius)
            for x_index in range(radial_segments + 1):
                u = x_index / radial_segments
                angle = u * math.tau
                sin_angle = math.sin(angle)
                cos_angle = math.cos(angle)
                positions.append([current_radius * sin_angle, y, current_radius * cos_angle])
                normals.append([
                    sin_angle * radial_normal_scale,
                    normal_y,
                    cos_angle * radial_normal_scale,
                ])
                uvs.append([u, 1.0 - y_amount])
        for y_index in range(height_segments):
            lower = ring_starts[y_index]
            upper = ring_starts[y_index + 1]
            lower_tip = ring_radii[y_index] <= tip_epsilon
            upper_tip = ring_radii[y_index + 1] <= tip_epsilon
            for x_index in range(radial_segments):
                a = lower + x_index
                b = a + 1
                c = upper + x_index
                d = c + 1
                if lower_tip and not upper_tip:
                    indices.extend((b, d, c))
                elif upper_tip and not lower_tip:
                    indices.extend((a, b, c))
                elif not lower_tip and not upper_tip:
                    indices.extend((a, b, c, b, d, c))
    else:
        for segment in range(radial_segments):
            start_angle = (segment / radial_segments) * math.tau
            end_angle = ((segment + 1) / radial_segments) * math.tau
            middle_angle = (start_angle + end_angle) * 0.5
            sin_start = math.sin(start_angle)
            cos_start = math.cos(start_angle)
            sin_end = math.sin(end_angle)
            cos_end = math.cos(end_angle)
            face_normal = [
                math.sin(middle_angle) * radial_normal_scale,
                normal_y,
                math.cos(middle_angle) * radial_normal_scale,
            ]
            start = len(positions)
            strip_radii: list[float] = []
            for y_index in range(height_segments + 1):
                y_amount = y_index / height_segments
                y = -half_height + y_amount * height
                current_radius = ring_radius(y_index)
                strip_radii.append(current_radius)
                positions.append([current_radius * sin_start, y, current_radius * cos_start])
                normals.append(face_normal)
                uvs.append([segment / radial_segments, 1.0 - y_amount])
                positions.append([current_radius * sin_end, y, current_radius * cos_end])
                normals.append(face_normal)
                uvs.append([(segment + 1) / radial_segments, 1.0 - y_amount])
            strip_row = 2
            for y_index in range(height_segments):
                a = start + y_index * strip_row
                b = a + 1
                c = a + strip_row
                d = c + 1
                lower_tip = strip_radii[y_index] <= tip_epsilon
                upper_tip = strip_radii[y_index + 1] <= tip_epsilon
                if lower_tip and not upper_tip:
                    indices.extend((b, d, c))
                elif upper_tip and not lower_tip:
                    indices.extend((a, b, c))
                elif not lower_tip and not upper_tip:
                    indices.extend((a, b, c, b, d, c))

    def append_cap(cap_normal_y: float, cap_radius: float) -> None:
        if cap_radius <= tip_epsilon:
            return
        start = len(positions)
        y = half_height if cap_normal_y > 0.0 else -half_height
        positions.append([0.0, y, 0.0])
        normals.append([0.0, cap_normal_y, 0.0])
        uvs.append([0.5, 0.5])
        ring_starts: list[int] = []
        for ring in range(1, cap_segments + 1):
            fraction = ring / cap_segments
            ring_starts.append(len(positions))
            ring_radius_value = cap_radius * fraction
            for x_index in range(radial_segments + 1):
                u = x_index / radial_segments
                angle = u * math.tau
                sin_angle = math.sin(angle)
                cos_angle = math.cos(angle)
                positions.append([ring_radius_value * sin_angle, y, ring_radius_value * cos_angle])
                normals.append([0.0, cap_normal_y, 0.0])
                uvs.append([0.5 + 0.5 * sin_angle * fraction, 0.5 - 0.5 * cos_angle * fraction])
        first_ring = ring_starts[0]
        for x_index in range(radial_segments):
            current = first_ring + x_index
            following = current + 1
            if cap_normal_y > 0.0:
                indices.extend((start, current, following))
            else:
                indices.extend((start, following, current))
        for ring in range(cap_segments - 1):
            inner = ring_starts[ring]
            outer = ring_starts[ring + 1]
            for x_index in range(radial_segments):
                a = inner + x_index
                b = outer + x_index
                c = a + 1
                d = b + 1
                if cap_normal_y > 0.0:
                    indices.extend((a, b, c, c, b, d))
                else:
                    indices.extend((a, c, b, c, d, b))

    if caps:
        append_cap(-1.0, bottom_radius)
        append_cap(1.0, top_radius)

    position_array = np.asarray(positions, dtype=np.float32)
    normal_array = np.asarray(normals, dtype=np.float32)
    rotation = _rotation_matrix_for_axis(orientation)
    position_array = position_array @ rotation.T
    normal_array = normal_array @ rotation.T
    return _finalise_geometry(
        position_array,
        normal_array,
        np.asarray(uvs, dtype=np.float32),
        np.asarray(indices, dtype=np.uint32),
        name,
        origin_x=origin_x,
        origin_y=origin_y,
        origin_z=origin_z,
        rotation_x=rotation_x,
        rotation_y=rotation_y,
        rotation_z=rotation_z,
        uv_tiles_u=uv_tiles_u,
        uv_tiles_v=uv_tiles_v,
    )


def disc_ring_geometry(
    outer_radius: float = 1.0,
    inner_radius: float = 0.0,
    radial_segments: int = 64,
    ring_segments: int = 1,
    arc_start: float = 0.0,
    arc_spread: float = 360.0,
    uv_mode: str = "Planar",
    orientation: str = "Axis Y",
    *,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
    origin_z: float = 0.0,
    rotation_x: float = 0.0,
    rotation_y: float = 0.0,
    rotation_z: float = 0.0,
    uv_tiles_u: int = 1,
    uv_tiles_v: int = 1,
    name: str = "Geometry Disc / Ring",
) -> GeometryData:
    """Generate a planar disc, annulus or partial arc with clean UVs.

    ``inner_radius == 0`` creates a disc using a non-degenerate centre fan.
    Positive inner radii create a ring.  Planar UVs map the complete outer
    circle into 0-1, while Radial Strip maps U around the arc and V from inner
    to outer radius for scrolling shockwave and portal materials.
    """

    outer_radius = max(float(outer_radius), 1.0e-6)
    inner_radius = min(max(float(inner_radius), 0.0), max(outer_radius - 1.0e-6, 0.0))
    radial_segments = min(max(int(radial_segments), 3), 1024)
    ring_segments = min(max(int(ring_segments), 1), 512)
    arc_start = float(arc_start)
    arc_spread = min(max(float(arc_spread), 0.001), 360.0)
    uv_mode = str(uv_mode or "Planar")

    positions: list[list[float]] = []
    normals: list[list[float]] = []
    uvs: list[list[float]] = []
    indices: list[int] = []
    columns = radial_segments + 1

    def append_ring(radius: float, radial_amount: float) -> int:
        start = len(positions)
        for segment in range(columns):
            u = segment / radial_segments
            angle = math.radians(arc_start + arc_spread * u)
            sin_angle = math.sin(angle)
            cos_angle = math.cos(angle)
            x = radius * sin_angle
            z = radius * cos_angle
            positions.append([x, 0.0, z])
            normals.append([0.0, 1.0, 0.0])
            if uv_mode == "Radial Strip":
                uvs.append([u, 1.0 - radial_amount])
            else:
                uvs.append([
                    0.5 + 0.5 * (x / outer_radius),
                    0.5 - 0.5 * (z / outer_radius),
                ])
        return start

    ring_starts: list[int] = []
    if inner_radius <= 1.0e-7:
        # Start with the first real ring. A separate centre vertex per angular
        # segment avoids the collapsed quads produced by a duplicated centre
        # ring and permits continuous Radial Strip U coordinates.
        for ring in range(1, ring_segments + 1):
            amount = ring / ring_segments
            ring_starts.append(append_ring(outer_radius * amount, amount))
        first_ring = ring_starts[0]
        for segment in range(radial_segments):
            u_mid = (segment + 0.5) / radial_segments
            centre = len(positions)
            positions.append([0.0, 0.0, 0.0])
            normals.append([0.0, 1.0, 0.0])
            if uv_mode == "Radial Strip":
                uvs.append([u_mid, 1.0])
            else:
                uvs.append([0.5, 0.5])
            indices.extend((centre, first_ring + segment, first_ring + segment + 1))
    else:
        for ring in range(ring_segments + 1):
            amount = ring / ring_segments
            radius = inner_radius + (outer_radius - inner_radius) * amount
            ring_starts.append(append_ring(radius, amount))

    for ring in range(len(ring_starts) - 1):
        inner = ring_starts[ring]
        outer = ring_starts[ring + 1]
        for segment in range(radial_segments):
            a = inner + segment
            b = a + 1
            c = outer + segment
            d = c + 1
            indices.extend((a, c, b, b, c, d))

    position_array = np.asarray(positions, dtype=np.float32)
    normal_array = np.asarray(normals, dtype=np.float32)
    base_rotation = _rotation_matrix_for_axis(orientation)
    position_array = position_array @ base_rotation.T
    normal_array = normal_array @ base_rotation.T
    return _finalise_geometry(
        position_array,
        normal_array,
        np.asarray(uvs, dtype=np.float32),
        np.asarray(indices, dtype=np.uint32),
        name,
        origin_x=origin_x,
        origin_y=origin_y,
        origin_z=origin_z,
        rotation_x=rotation_x,
        rotation_y=rotation_y,
        rotation_z=rotation_z,
        uv_tiles_u=uv_tiles_u,
        uv_tiles_v=uv_tiles_v,
    )



def ribbon_geometry(
    length: float = 4.0,
    width_start: float = 1.0,
    width_end: float = 1.0,
    length_segments: int = 16,
    width_segments: int = 1,
    orientation: str = "Horizontal (XZ)",
    *,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
    origin_z: float = 0.0,
    rotation_x: float = 0.0,
    rotation_y: float = 0.0,
    rotation_z: float = 0.0,
    uv_tiles_u: int = 1,
    uv_tiles_v: int = 1,
    name: str = "Geometry Ribbon",
) -> GeometryData:
    """Generate a straight tapered ribbon with predictable scrolling UVs.

    U runs across the ribbon width and V runs from Width Start to Width End.
    The three base orientations mirror Geometry Plane conventions so origin,
    rotation and downstream deformation behave consistently across generators.
    """

    length = max(float(length), 1.0e-6)
    width_start = max(float(width_start), 0.0)
    width_end = max(float(width_end), 0.0)
    if width_start <= 1.0e-8 and width_end <= 1.0e-8:
        raise ValueError("Geometry Ribbon requires Width Start or Width End above zero")
    length_segments = min(max(int(length_segments), 1), 2048)
    width_segments = min(max(int(width_segments), 1), 256)

    columns = width_segments + 1
    rows = length_segments + 1
    u_values = np.linspace(0.0, 1.0, columns, dtype=np.float32)
    v_values = np.linspace(0.0, 1.0, rows, dtype=np.float32)
    positions = np.empty((rows, columns, 3), dtype=np.float32)
    normals = np.zeros_like(positions)
    uvs = np.empty((rows, columns, 2), dtype=np.float32)
    orientation = str(orientation or "Horizontal (XZ)")

    for row, v in enumerate(v_values):
        width = width_start * (1.0 - float(v)) + width_end * float(v)
        across = (u_values - 0.5) * width
        along = (0.5 - float(v)) * length
        if orientation == "Vertical (XY)":
            positions[row, :, 0] = across
            positions[row, :, 1] = along
            positions[row, :, 2] = 0.0
            normals[row, :, 2] = 1.0
        elif orientation == "Vertical (YZ)":
            positions[row, :, 0] = 0.0
            positions[row, :, 1] = along
            positions[row, :, 2] = across
            normals[row, :, 0] = 1.0
        else:
            positions[row, :, 0] = across
            positions[row, :, 1] = 0.0
            positions[row, :, 2] = along
            normals[row, :, 1] = 1.0
        uvs[row, :, 0] = u_values
        uvs[row, :, 1] = float(v)

    indices: list[int] = []
    for row in range(length_segments):
        for column in range(width_segments):
            a = row * columns + column
            b = a + 1
            c = a + columns
            d = c + 1
            collapsed_start = row == 0 and width_start <= 1.0e-8
            collapsed_end = row + 1 == length_segments and width_end <= 1.0e-8
            if orientation == "Vertical (XY)":
                first = (a, c, b)
                second = (b, c, d)
            else:
                first = (a, b, c)
                second = (b, d, c)
            # At a zero-width end, one triangle of each final quad collapses.
            # Keep only the valid fan triangle while retaining separate UV-tip
            # vertices for each width segment.
            if collapsed_start:
                indices.extend(second)
            elif collapsed_end:
                indices.extend(first)
            else:
                indices.extend((*first, *second))

    return _finalise_geometry(
        positions.reshape(-1, 3),
        normals.reshape(-1, 3),
        uvs.reshape(-1, 2),
        np.asarray(indices, dtype=np.uint32),
        name,
        origin_x=origin_x,
        origin_y=origin_y,
        origin_z=origin_z,
        rotation_x=rotation_x,
        rotation_y=rotation_y,
        rotation_z=rotation_z,
        uv_tiles_u=uv_tiles_u,
        uv_tiles_v=uv_tiles_v,
    )


def _axis_vector(axis: str) -> np.ndarray:
    value = str(axis or "Axis Y")
    if value == "Axis X":
        return np.asarray((1.0, 0.0, 0.0), dtype=np.float32)
    if value == "Axis Z":
        return np.asarray((0.0, 0.0, 1.0), dtype=np.float32)
    return np.asarray((0.0, 1.0, 0.0), dtype=np.float32)


def _rotate_about_axis(
    vectors: np.ndarray,
    axis: np.ndarray,
    angles: np.ndarray | float,
) -> np.ndarray:
    """Rotate one or many vectors around one unit axis using Rodrigues' formula."""

    values = np.asarray(vectors, dtype=np.float32)
    unit_axis = np.asarray(axis, dtype=np.float32)
    unit_axis /= max(float(np.linalg.norm(unit_axis)), 1.0e-8)
    theta = np.asarray(angles, dtype=np.float32)
    if theta.ndim == 0:
        theta = np.full((values.shape[0],), float(theta), dtype=np.float32)
    theta = theta.reshape(-1, 1)
    cosine = np.cos(theta)
    sine = np.sin(theta)
    cross = np.cross(np.broadcast_to(unit_axis, values.shape), values)
    projection = values @ unit_axis
    return (
        values * cosine
        + cross * sine
        + projection[:, None] * unit_axis[None, :] * (1.0 - cosine)
    ).astype(np.float32, copy=False)


def _geometry_pivot(positions: np.ndarray, pivot_mode: str) -> np.ndarray:
    if str(pivot_mode or "Current Origin") == "Bounds Centre" and positions.size:
        return ((positions.min(axis=0) + positions.max(axis=0)) * 0.5).astype(np.float32)
    return np.zeros(3, dtype=np.float32)


def _normalised_range(start: float, end: float) -> tuple[float, float]:
    first = min(max(float(start), 0.0), 1.0)
    second = min(max(float(end), 0.0), 1.0)
    if second < first:
        first, second = second, first
    if second - first < 1.0e-5:
        second = min(first + 1.0e-5, 1.0)
        if second - first < 1.0e-5:
            first = max(0.0, second - 1.0e-5)
    return first, second


def bend_geometry(
    geometry: GeometryData,
    *,
    amount: float = 90.0,
    deformation_axis: str = "Axis Z",
    direction: float = 0.0,
    pivot_mode: str = "Current Origin",
    range_start: float = 0.0,
    range_end: float = 1.0,
    clamp_outside: bool = True,
    name: str = "Bent Geometry",
) -> GeometryData:
    """Bend a mesh into a circular arc along one selected bounds axis.

    ``direction`` rotates the bend plane around the deformation axis.  When
    Clamp Outside Range is enabled, geometry beyond the selected section
    continues rigidly along the start/end tangents instead of introducing a
    positional discontinuity.
    """

    if not isinstance(geometry, GeometryData):
        raise TypeError("Geometry Bend requires a connected Geometry input")
    vertices = geometry.vertices.copy()
    if not vertices.size or abs(float(amount)) <= 1.0e-8:
        return GeometryData(vertices, geometry.indices.copy(), name, geometry.uv_origin)

    positions = vertices[:, :3]
    normals = vertices[:, 3:6]
    longitudinal = _axis_vector(deformation_axis)
    if str(deformation_axis or "Axis Z") == "Axis X":
        base_radial = np.asarray((0.0, 1.0, 0.0), dtype=np.float32)
    else:
        base_radial = np.asarray((1.0, 0.0, 0.0), dtype=np.float32)
    radial = _rotate_about_axis(
        base_radial.reshape(1, 3), longitudinal, math.radians(float(direction))
    )[0]
    radial /= max(float(np.linalg.norm(radial)), 1.0e-8)
    binormal = np.cross(longitudinal, radial).astype(np.float32)
    binormal /= max(float(np.linalg.norm(binormal)), 1.0e-8)

    pivot = _geometry_pivot(positions, pivot_mode)
    relative = positions - pivot
    coordinate = relative @ longitudinal
    radial_coordinate = relative @ radial
    binormal_coordinate = relative @ binormal
    minimum = float(coordinate.min())
    maximum = float(coordinate.max())
    extent = maximum - minimum
    if extent <= 1.0e-8:
        return GeometryData(vertices, geometry.indices.copy(), name, geometry.uv_origin)

    start_amount, end_amount = _normalised_range(range_start, range_end)
    start = minimum + extent * start_amount
    end = minimum + extent * end_amount
    section_length = max(end - start, 1.0e-8)
    total_angle = math.radians(float(amount))
    curvature = total_angle / section_length
    if abs(curvature) <= 1.0e-10:
        return GeometryData(vertices, geometry.indices.copy(), name, geometry.uv_origin)

    local = coordinate - start
    if clamp_outside:
        bent_local = np.clip(local, 0.0, section_length)
    else:
        bent_local = local
    theta = bent_local * curvature
    radius = 1.0 / curvature
    sine = np.sin(theta)
    cosine = np.cos(theta)
    long_out = start + (radius - radial_coordinate) * sine
    radial_out = radius * (1.0 - cosine) + radial_coordinate * cosine

    if clamp_outside:
        before = np.minimum(local, 0.0)
        after = np.maximum(local - section_length, 0.0)
        long_out += before + after * math.cos(total_angle)
        radial_out += after * math.sin(total_angle)

    vertices[:, :3] = (
        pivot
        + long_out[:, None] * longitudinal[None, :]
        + radial_out[:, None] * radial[None, :]
        + binormal_coordinate[:, None] * binormal[None, :]
    )
    vertices[:, 3:6] = _normalised(
        _rotate_about_axis(normals, binormal, theta), fallback=normals
    )
    return GeometryData(vertices, geometry.indices.copy(), name, geometry.uv_origin)


def twist_geometry(
    geometry: GeometryData,
    *,
    amount: float = 180.0,
    axis: str = "Axis Z",
    pivot_mode: str = "Current Origin",
    range_start: float = 0.0,
    range_end: float = 1.0,
    clamp_outside: bool = True,
    name: str = "Twisted Geometry",
) -> GeometryData:
    """Twist positions and normals around a selected origin/bounds axis."""

    if not isinstance(geometry, GeometryData):
        raise TypeError("Geometry Twist requires a connected Geometry input")
    vertices = geometry.vertices.copy()
    if not vertices.size or abs(float(amount)) <= 1.0e-8:
        return GeometryData(vertices, geometry.indices.copy(), name, geometry.uv_origin)
    positions = vertices[:, :3]
    normals = vertices[:, 3:6]
    twist_axis = _axis_vector(axis)
    pivot = _geometry_pivot(positions, pivot_mode)
    relative = positions - pivot
    coordinate = relative @ twist_axis
    minimum = float(coordinate.min())
    maximum = float(coordinate.max())
    extent = maximum - minimum
    if extent <= 1.0e-8:
        return GeometryData(vertices, geometry.indices.copy(), name, geometry.uv_origin)

    start_amount, end_amount = _normalised_range(range_start, range_end)
    start = minimum + extent * start_amount
    end = minimum + extent * end_amount
    section_length = max(end - start, 1.0e-8)
    factor = (coordinate - start) / section_length
    if clamp_outside:
        factor = np.clip(factor, 0.0, 1.0)
    angles = factor * math.radians(float(amount))

    parallel = coordinate[:, None] * twist_axis[None, :]
    radial = relative - parallel
    vertices[:, :3] = pivot + parallel + _rotate_about_axis(radial, twist_axis, angles)
    vertices[:, 3:6] = _normalised(
        _rotate_about_axis(normals, twist_axis, angles), fallback=normals
    )
    return GeometryData(vertices, geometry.indices.copy(), name, geometry.uv_origin)


def uv_transform_geometry(
    geometry: GeometryData,
    *,
    scale_u: float = 1.0,
    scale_v: float = 1.0,
    offset_u: float = 0.0,
    offset_v: float = 0.0,
    rotation: float = 0.0,
    pivot_u: float = 0.5,
    pivot_v: float = 0.5,
    flip_u: bool = False,
    flip_v: bool = False,
    swap_uv: bool = False,
    name: str = "UV Transformed Geometry",
) -> GeometryData:
    """Transform mesh UV coordinates without changing topology or positions."""

    if not isinstance(geometry, GeometryData):
        raise TypeError("Geometry UV Transform requires a connected Geometry input")
    vertices = geometry.vertices.copy()
    uv = vertices[:, 6:8].copy()
    if swap_uv:
        uv = uv[:, ::-1]
    pivot = np.asarray((float(pivot_u), float(pivot_v)), dtype=np.float32)
    centred = uv - pivot
    if flip_u:
        centred[:, 0] *= -1.0
    if flip_v:
        centred[:, 1] *= -1.0
    centred *= np.asarray((float(scale_u), float(scale_v)), dtype=np.float32)
    angle = math.radians(float(rotation) % 360.0)
    sine = math.sin(angle)
    cosine = math.cos(angle)
    matrix = np.asarray(((cosine, -sine), (sine, cosine)), dtype=np.float32)
    vertices[:, 6:8] = (
        centred @ matrix.T
        + pivot
        + np.asarray((float(offset_u), float(offset_v)), dtype=np.float32)
    )
    return GeometryData(vertices, geometry.indices.copy(), name, geometry.uv_origin)


def _drop_degenerate_triangles(indices: np.ndarray, positions: np.ndarray) -> np.ndarray:
    triangles = np.asarray(indices, dtype=np.uint32).reshape(-1, 3)
    if not triangles.size:
        return triangles.reshape(-1)
    distinct = (
        (triangles[:, 0] != triangles[:, 1])
        & (triangles[:, 1] != triangles[:, 2])
        & (triangles[:, 2] != triangles[:, 0])
    )
    p0 = positions[triangles[:, 0]]
    p1 = positions[triangles[:, 1]]
    p2 = positions[triangles[:, 2]]
    cross = np.cross(p1 - p0, p2 - p0)
    bounds_extent = positions.max(axis=0) - positions.min(axis=0) if positions.size else np.zeros(3)
    scale = max(float(np.linalg.norm(bounds_extent)), 1.0)
    valid_area = np.einsum("ij,ij->i", cross, cross) > (scale * scale * 1.0e-12) ** 2
    return np.ascontiguousarray(triangles[distinct & valid_area].reshape(-1), dtype=np.uint32)


def _vertex_merge_keys(
    vertices: np.ndarray,
    weld_distance: float,
    preserve_uv_seams: bool,
    preserve_hard_edges: bool,
) -> np.ndarray:
    position = vertices[:, :3]
    if weld_distance > 0.0:
        position_key = np.rint(position / weld_distance).astype(np.int64)
    else:
        position_key = position.view(np.uint32).astype(np.int64)
    parts = [position_key]
    if preserve_hard_edges:
        parts.append(vertices[:, 3:6].view(np.uint32).astype(np.int64))
    if preserve_uv_seams:
        parts.append(vertices[:, 6:8].view(np.uint32).astype(np.int64))
    return np.ascontiguousarray(np.concatenate(parts, axis=1), dtype=np.int64)


def clean_weld_geometry(
    geometry: GeometryData,
    *,
    remove_degenerate: bool = True,
    remove_unused: bool = True,
    merge_vertices: bool = True,
    weld_distance: float = 0.0,
    preserve_uv_seams: bool = True,
    preserve_hard_edges: bool = True,
    name: str = "Cleaned Geometry",
) -> GeometryData:
    """Clean topology and optionally merge compatible vertices.

    Exact duplicates are merged when Weld Distance is zero. Positive distances
    use a deterministic spatial quantisation and average merged attributes.
    Including UVs and normals in the merge key preserves seams and hard edges.
    """

    if not isinstance(geometry, GeometryData):
        raise TypeError("Geometry Clean / Weld requires a connected Geometry input")
    vertices = geometry.vertices.copy()
    indices = geometry.indices.copy()
    if remove_degenerate and indices.size:
        indices = _drop_degenerate_triangles(indices, vertices[:, :3])

    if merge_vertices and vertices.shape[0]:
        distance = max(float(weld_distance), 0.0)
        keys = _vertex_merge_keys(
            vertices, distance, bool(preserve_uv_seams), bool(preserve_hard_edges)
        )
        packed = keys.view(np.dtype((np.void, keys.dtype.itemsize * keys.shape[1]))).reshape(-1)
        _, first_indices, inverse = np.unique(
            packed, return_index=True, return_inverse=True
        )
        group_count = int(inverse.max()) + 1 if inverse.size else 0
        counts = np.bincount(inverse, minlength=group_count).astype(np.float32)
        merged = np.empty((group_count, 8), dtype=np.float32)
        for component in range(8):
            merged[:, component] = np.bincount(
                inverse, weights=vertices[:, component], minlength=group_count
            ) / np.maximum(counts, 1.0)
        merged[:, 3:6] = _normalised(
            merged[:, 3:6], fallback=vertices[first_indices, 3:6]
        )
        vertices = merged
        indices = inverse[indices].astype(np.uint32, copy=False)
        if remove_degenerate and indices.size:
            indices = _drop_degenerate_triangles(indices, vertices[:, :3])

    if remove_unused and vertices.shape[0]:
        if indices.size:
            used = np.unique(indices)
            remap = np.full((vertices.shape[0],), -1, dtype=np.int64)
            remap[used] = np.arange(used.size, dtype=np.int64)
            vertices = vertices[used]
            indices = remap[indices].astype(np.uint32, copy=False)
        else:
            vertices = np.empty((0, 8), dtype=np.float32)
            indices = np.empty((0,), dtype=np.uint32)

    return GeometryData(vertices, indices, name, geometry.uv_origin)


def combine_geometry(
    bottom: GeometryData,
    top: GeometryData,
    *,
    name: str = "Combined Geometry",
) -> GeometryData:
    """Combine two meshes in the bottom mesh's coordinate/pivot space.

    Geometry values already store vertices relative to their pivot at the world
    origin.  Concatenating the top vertices without an additional translation
    therefore retains their authored position while making the bottom input's
    origin the shared exported pivot.
    """

    if not isinstance(bottom, GeometryData) or not isinstance(top, GeometryData):
        raise TypeError("Geometry Combine requires connected Bottom and Top Geometry inputs")
    top_vertices = convert_uv_origin(top.vertices, top.uv_origin, bottom.uv_origin)
    vertices = np.concatenate((bottom.vertices, top_vertices), axis=0)
    top_indices = top.indices.astype(np.uint64, copy=False) + bottom.vertex_count
    if top_indices.size and int(top_indices.max()) > np.iinfo(np.uint32).max:
        raise ValueError("Combined geometry exceeds the uint32 index limit")
    indices = np.concatenate((bottom.indices, top_indices.astype(np.uint32)), axis=0)
    return GeometryData(vertices, indices, name, bottom.uv_origin)

def transform_geometry(
    geometry: GeometryData,
    *,
    translate_x: float = 0.0,
    translate_y: float = 0.0,
    translate_z: float = 0.0,
    rotation_x: float = 0.0,
    rotation_y: float = 0.0,
    rotation_z: float = 0.0,
    uniform_scale: float = 1.0,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    scale_z: float = 1.0,
    pivot_mode: str = "Current Origin",
    name: str = "Transformed Geometry",
) -> GeometryData:
    """Apply scale, XYZ rotation and translation to any geometry value."""

    if not isinstance(geometry, GeometryData):
        raise TypeError("Geometry Transform requires a connected Geometry input")
    vertices = geometry.vertices.copy()
    positions = vertices[:, :3]
    normals = vertices[:, 3:6]
    if str(pivot_mode or "Current Origin") == "Bounds Centre" and positions.size:
        pivot = (positions.min(axis=0) + positions.max(axis=0)) * 0.5
    else:
        pivot = np.zeros(3, dtype=np.float32)

    uniform = float(uniform_scale)
    scale = np.asarray((float(scale_x), float(scale_y), float(scale_z)), dtype=np.float32) * uniform
    safe_scale = np.where(
        np.abs(scale) < 1.0e-8,
        np.copysign(1.0e-8, np.where(scale == 0.0, 1.0, scale)),
        scale,
    )
    rotation = _euler_rotation_matrix(rotation_x, rotation_y, rotation_z)
    centred = positions - pivot
    transformed = (centred * scale) @ rotation.T
    transformed += pivot + np.asarray((translate_x, translate_y, translate_z), dtype=np.float32)

    transformed_normals = (normals / safe_scale) @ rotation.T
    lengths = np.linalg.norm(transformed_normals, axis=1, keepdims=True)
    missing = lengths[:, 0] <= 1.0e-8
    transformed_normals /= np.maximum(lengths, 1.0e-8)
    if np.any(missing):
        fallback = normals @ rotation.T
        fallback /= np.maximum(np.linalg.norm(fallback, axis=1, keepdims=True), 1.0e-8)
        transformed_normals[missing] = fallback[missing]

    indices = geometry.indices.copy()
    if float(np.prod(scale)) < 0.0:
        triangles = indices.reshape(-1, 3).copy()
        triangles[:, [1, 2]] = triangles[:, [2, 1]]
        indices = triangles.reshape(-1)
    vertices[:, :3] = transformed
    vertices[:, 3:6] = transformed_normals
    return GeometryData(vertices, indices, name, geometry.uv_origin)


def _normalised(values: np.ndarray, fallback: np.ndarray | None = None) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    lengths = np.linalg.norm(values, axis=1, keepdims=True)
    result = values / np.maximum(lengths, 1.0e-8)
    if fallback is not None:
        missing = lengths[:, 0] <= 1.0e-8
        if np.any(missing):
            fallback_values = np.asarray(fallback, dtype=np.float32)
            fallback_values = fallback_values / np.maximum(
                np.linalg.norm(fallback_values, axis=1, keepdims=True), 1.0e-8
            )
            result[missing] = fallback_values[missing]
    return result


def _triangle_face_data(positions: np.ndarray, indices: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    triangles = np.asarray(indices, dtype=np.uint32).reshape(-1, 3)
    p0 = positions[triangles[:, 0]]
    p1 = positions[triangles[:, 1]]
    p2 = positions[triangles[:, 2]]
    raw = np.cross(p1 - p0, p2 - p0)
    return raw, _normalised(raw)


def _position_groups(positions: np.ndarray, decimals: int = 6) -> tuple[np.ndarray, np.ndarray]:
    return np.unique(
        np.round(np.asarray(positions, dtype=np.float32), decimals),
        axis=0,
        return_inverse=True,
    )


def _smooth_vertex_normals(positions: np.ndarray, indices: np.ndarray) -> np.ndarray:
    unique_positions, groups = _position_groups(positions)
    accumulated = np.zeros((unique_positions.shape[0], 3), dtype=np.float32)
    raw_faces, _unit_faces = _triangle_face_data(positions, indices)
    triangles = np.asarray(indices, dtype=np.uint32).reshape(-1, 3)
    for corner in range(3):
        np.add.at(accumulated, groups[triangles[:, corner]], raw_faces)
    group_normals = _normalised(accumulated)
    return group_normals[groups]


def _relax_geometry_positions(
    positions: np.ndarray,
    indices: np.ndarray,
    amount: float = 0.5,
) -> np.ndarray:
    """Laplacian relaxation over welded geometric position groups."""

    unique_positions, groups = _position_groups(positions)
    triangles = np.asarray(indices, dtype=np.uint32).reshape(-1, 3)
    neighbours: list[set[int]] = [set() for _ in range(unique_positions.shape[0])]
    edge_counts: dict[tuple[int, int], int] = {}
    for triangle in triangles:
        group_triangle = groups[triangle]
        for a, b in ((0, 1), (1, 2), (2, 0)):
            ga = int(group_triangle[a])
            gb = int(group_triangle[b])
            if ga == gb:
                continue
            neighbours[ga].add(gb)
            neighbours[gb].add(ga)
            edge = (min(ga, gb), max(ga, gb))
            edge_counts[edge] = edge_counts.get(edge, 0) + 1
    boundary: set[int] = set()
    for (a, b), count in edge_counts.items():
        if count == 1:
            boundary.add(a)
            boundary.add(b)
    relaxed = unique_positions.copy()
    factor = min(max(float(amount), 0.0), 1.0)
    for index, adjacent in enumerate(neighbours):
        if index in boundary or not adjacent:
            continue
        average = unique_positions[np.fromiter(adjacent, dtype=np.int64)].mean(axis=0)
        relaxed[index] = unique_positions[index] * (1.0 - factor) + average * factor
    return relaxed[groups]


def _subdivide_once(geometry: GeometryData) -> GeometryData:
    source_vertices = geometry.vertices
    source_indices = geometry.indices.reshape(-1, 3)
    vertices: list[np.ndarray] = [row.copy() for row in source_vertices]
    edge_midpoints: dict[tuple[int, int], int] = {}

    def midpoint(a: int, b: int) -> int:
        key = (min(a, b), max(a, b))
        cached = edge_midpoints.get(key)
        if cached is not None:
            return cached
        va = source_vertices[a]
        vb = source_vertices[b]
        value = (va + vb) * 0.5
        summed_normal = va[3:6] + vb[3:6]
        length = float(np.linalg.norm(summed_normal))
        value[3:6] = summed_normal / length if length > 1.0e-8 else va[3:6]
        index = len(vertices)
        vertices.append(value.astype(np.float32, copy=False))
        edge_midpoints[key] = index
        return index

    indices: list[int] = []
    for a_raw, b_raw, c_raw in source_indices:
        a, b, c = int(a_raw), int(b_raw), int(c_raw)
        ab = midpoint(a, b)
        bc = midpoint(b, c)
        ca = midpoint(c, a)
        indices.extend((a, ab, ca, ab, b, bc, ca, bc, c, ab, bc, ca))
    return GeometryData(
        np.asarray(vertices, dtype=np.float32),
        np.asarray(indices, dtype=np.uint32),
        geometry.name,
        geometry.uv_origin,
    )


def subdivide_geometry(
    geometry: GeometryData,
    levels: int = 1,
    *,
    smooth_surface: bool = False,
    name: str = "Subdivided Geometry",
) -> GeometryData:
    """Split every triangle into four, optionally relaxing the surface."""

    if not isinstance(geometry, GeometryData):
        raise TypeError("Geometry Subdivide requires a connected Geometry input")
    levels = min(max(int(levels), 0), 6)
    projected_triangles = geometry.triangle_count * (4 ** levels)
    if projected_triangles > 2_000_000:
        raise ValueError(
            f"Geometry Subdivide would create {projected_triangles:,} triangles; "
            "reduce Levels or the input mesh density"
        )
    result = geometry.copy(name=name)
    for _level in range(levels):
        result = _subdivide_once(result)
        if smooth_surface:
            vertices = result.vertices.copy()
            vertices[:, :3] = _relax_geometry_positions(vertices[:, :3], result.indices, 0.5)
            vertices[:, 3:6] = _smooth_vertex_normals(vertices[:, :3], result.indices)
            result = GeometryData(vertices, result.indices.copy(), name, result.uv_origin)
    result.name = name
    return result



def _triangle_rows_without_duplicates(indices: np.ndarray) -> np.ndarray:
    """Drop repeated triangles while retaining the first triangle's winding."""

    triangles = np.asarray(indices, dtype=np.uint32).reshape(-1, 3)
    if not triangles.size:
        return np.empty((0,), dtype=np.uint32)
    canonical = np.sort(triangles, axis=1)
    packed = np.ascontiguousarray(canonical).view(
        np.dtype((np.void, canonical.dtype.itemsize * canonical.shape[1]))
    ).reshape(-1)
    _, first = np.unique(packed, return_index=True)
    first.sort()
    return np.ascontiguousarray(triangles[first].reshape(-1), dtype=np.uint32)


def _decimation_face_data(
    vertices: np.ndarray, indices: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    triangles = np.asarray(indices, dtype=np.uint32).reshape(-1, 3)
    positions = vertices[:, :3]
    p0 = positions[triangles[:, 0]]
    p1 = positions[triangles[:, 1]]
    p2 = positions[triangles[:, 2]]
    raw_normals = np.cross(p1 - p0, p2 - p0)
    lengths = np.linalg.norm(raw_normals, axis=1)
    unit_normals = raw_normals / np.maximum(lengths[:, None], 1.0e-12)
    planes = np.concatenate(
        (unit_normals, -np.einsum("ij,ij->i", unit_normals, p0)[:, None]), axis=1
    )
    return triangles, positions, raw_normals, lengths, unit_normals, planes


def _decimation_edges(
    triangles: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    triangle_count = triangles.shape[0]
    occurrences = np.concatenate(
        (triangles[:, (0, 1)], triangles[:, (1, 2)], triangles[:, (2, 0)]), axis=0
    ).astype(np.uint32, copy=False)
    occurrence_faces = np.tile(np.arange(triangle_count, dtype=np.int64), 3)
    occurrences = np.sort(occurrences, axis=1)
    edges, first, inverse, counts = np.unique(
        occurrences, axis=0, return_index=True, return_inverse=True, return_counts=True
    )
    return edges, counts, first, inverse, occurrence_faces


def _decimation_quadrics(
    vertices: np.ndarray,
    triangles: np.ndarray,
    planes: np.ndarray,
    edges: np.ndarray,
    edge_counts: np.ndarray,
    edge_first: np.ndarray,
    occurrence_faces: np.ndarray,
) -> np.ndarray:
    quadrics = np.zeros((vertices.shape[0], 4, 4), dtype=np.float64)
    face_quadrics = planes[:, :, None] * planes[:, None, :]
    for corner in range(3):
        np.add.at(quadrics, triangles[:, corner], face_quadrics)

    # Standard boundary quadrics keep open silhouettes and disconnected UV or
    # hard-normal islands from shrinking inwards too aggressively. Imported OBJ
    # seams already use duplicated vertices, so their edges naturally appear as
    # boundaries to this indexed topology.
    boundary_indices = np.flatnonzero(edge_counts == 1)
    if boundary_indices.size:
        positions = vertices[:, :3].astype(np.float64, copy=False)
        boundary_edges = edges[boundary_indices]
        boundary_faces = occurrence_faces[edge_first[boundary_indices]]
        edge_vectors = positions[boundary_edges[:, 1]] - positions[boundary_edges[:, 0]]
        face_normals = planes[boundary_faces, :3]
        boundary_normals = np.cross(edge_vectors, face_normals)
        boundary_lengths = np.linalg.norm(boundary_normals, axis=1)
        valid = boundary_lengths > 1.0e-12
        boundary_normals[valid] /= boundary_lengths[valid, None]
        boundary_planes = np.zeros((boundary_edges.shape[0], 4), dtype=np.float64)
        boundary_planes[:, :3] = boundary_normals
        boundary_planes[:, 3] = -np.einsum(
            "ij,ij->i", boundary_normals, positions[boundary_edges[:, 0]]
        )
        boundary_quadrics = boundary_planes[:, :, None] * boundary_planes[:, None, :]
        boundary_quadrics *= 16.0
        for endpoint in range(2):
            np.add.at(quadrics, boundary_edges[:, endpoint], boundary_quadrics)
    return quadrics


def _decimation_candidates(
    vertices: np.ndarray,
    indices: np.ndarray,
) -> tuple[
    np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray
]:
    triangles, positions, raw_normals, face_lengths, _unit_normals, planes = (
        _decimation_face_data(vertices, indices)
    )
    edges, edge_counts, edge_first, _edge_inverse, occurrence_faces = _decimation_edges(
        triangles
    )
    manifold = edge_counts <= 2
    edges = edges[manifold]
    edge_counts = edge_counts[manifold]
    edge_first = edge_first[manifold]
    quadrics = _decimation_quadrics(
        vertices,
        triangles,
        planes,
        edges,
        edge_counts,
        edge_first,
        occurrence_faces,
    )

    p0 = positions[edges[:, 0]].astype(np.float64, copy=False)
    p1 = positions[edges[:, 1]].astype(np.float64, copy=False)
    edge_vectors = p1 - p0
    edge_length_squared = np.einsum("ij,ij->i", edge_vectors, edge_vectors)
    combined = quadrics[edges[:, 0]] + quadrics[edges[:, 1]]

    solved = (p0 + p1) * 0.5
    matrices = combined[:, :3, :3]
    offsets = combined[:, :3, 3]
    determinants = np.linalg.det(matrices)
    stable = np.abs(determinants) > 1.0e-12
    if np.any(stable):
        try:
            solved[stable] = np.linalg.solve(matrices[stable], -offsets[stable, :, None])[:, :, 0]
        except np.linalg.LinAlgError:
            # Individual singular matrices can still sneak through the
            # determinant threshold on badly scaled meshes. Midpoints are a
            # safe deterministic fallback.
            pass

    # Keep the replacement on the original edge. It is less aggressive than
    # unconstrained QEM but avoids surprising spikes and makes UV/normal
    # interpolation well defined.
    amount = np.einsum("ij,ij->i", solved - p0, edge_vectors) / np.maximum(
        edge_length_squared, 1.0e-20
    )
    amount = np.clip(amount, 0.0, 1.0)
    replacement = p0 + edge_vectors * amount[:, None]
    homogeneous = np.concatenate(
        (replacement, np.ones((replacement.shape[0], 1), dtype=np.float64)), axis=1
    )
    costs = np.einsum("ni,nij,nj->n", homogeneous, combined, homogeneous)

    # Stable tie-breaking favours short edges. Attribute terms are deliberately
    # gentle: UV and hard-normal seams are already disconnected in GeometryData,
    # while this discourages needless collapse across rapid variation inside an
    # otherwise connected island.
    extent = positions.max(axis=0) - positions.min(axis=0) if positions.size else np.ones(3)
    scale_squared = max(float(np.dot(extent, extent)), 1.0)
    normal_dot = np.einsum(
        "ij,ij->i", vertices[edges[:, 0], 3:6], vertices[edges[:, 1], 3:6]
    )
    uv_delta = vertices[edges[:, 1], 6:8] - vertices[edges[:, 0], 6:8]
    costs += np.maximum(0.0, 1.0 - normal_dot) * scale_squared * 1.0e-5
    costs += np.einsum("ij,ij->i", uv_delta, uv_delta) * scale_squared * 1.0e-7
    costs += edge_length_squared * 1.0e-12
    return (
        triangles,
        raw_normals,
        face_lengths,
        edges,
        edge_counts,
        amount.astype(np.float32),
        costs,
    )


def _vertex_face_lists(triangles: np.ndarray, vertex_count: int) -> list[list[int]]:
    result: list[list[int]] = [[] for _ in range(vertex_count)]
    for face_index, triangle in enumerate(triangles):
        result[int(triangle[0])].append(face_index)
        result[int(triangle[1])].append(face_index)
        result[int(triangle[2])].append(face_index)
    return result


def _collapse_preserves_faces(
    u: int,
    v: int,
    replacement: np.ndarray,
    triangles: np.ndarray,
    positions: np.ndarray,
    raw_normals: np.ndarray,
    face_lengths: np.ndarray,
    vertex_faces: list[list[int]],
    minimum_area_twice: float,
) -> bool:
    # Validate every surviving face touched by the collapse in one small NumPy
    # batch.  The previous implementation performed dozens of tiny np.cross /
    # np.linalg calls and recomputed whole-mesh bounds for every candidate,
    # which dominated high-poly decimation time.
    affected = set(vertex_faces[u])
    affected.update(vertex_faces[v])
    if not affected:
        return False
    face_indices = np.fromiter(affected, dtype=np.int64)
    local_triangles = triangles[face_indices]
    has_u = np.any(local_triangles == u, axis=1)
    has_v = np.any(local_triangles == v, axis=1)
    surviving = ~(has_u & has_v)
    if not np.any(surviving):
        return True
    face_indices = face_indices[surviving]
    local_triangles = local_triangles[surviving]
    points = positions[local_triangles].copy()
    replacement_mask = (local_triangles == u) | (local_triangles == v)
    points[replacement_mask] = replacement
    new_normals = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    new_lengths = np.linalg.norm(new_normals, axis=1)
    if np.any(new_lengths <= minimum_area_twice):
        return False
    old_lengths = np.maximum(face_lengths[face_indices], minimum_area_twice)
    alignment = np.einsum('ij,ij->i', new_normals, raw_normals[face_indices])
    return bool(np.all(alignment > old_lengths * new_lengths * 0.05))


def _apply_decimation_batch(
    vertices: np.ndarray,
    triangles: np.ndarray,
    selections: list[tuple[int, int, float, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray]:
    updated = vertices.copy()
    remap = np.arange(vertices.shape[0], dtype=np.uint32)
    for keep, remove, amount, replacement in selections:
        value = updated[keep].copy()
        value[:3] = replacement
        normal = (
            updated[keep, 3:6] * (1.0 - amount)
            + updated[remove, 3:6] * amount
        )
        length = float(np.linalg.norm(normal))
        if length > 1.0e-8:
            value[3:6] = normal / length
        value[6:8] = (
            updated[keep, 6:8] * (1.0 - amount)
            + updated[remove, 6:8] * amount
        )
        updated[keep] = value
        remap[remove] = keep

    rebuilt = remap[triangles]
    distinct = (
        (rebuilt[:, 0] != rebuilt[:, 1])
        & (rebuilt[:, 1] != rebuilt[:, 2])
        & (rebuilt[:, 2] != rebuilt[:, 0])
    )
    rebuilt = rebuilt[distinct]
    rebuilt_flat = _drop_degenerate_triangles(rebuilt.reshape(-1), updated[:, :3])
    rebuilt_flat = _triangle_rows_without_duplicates(rebuilt_flat)
    rebuilt = rebuilt_flat.reshape(-1, 3)
    if not rebuilt.size:
        return np.empty((0, 8), dtype=np.float32), np.empty((0,), dtype=np.uint32)
    used = np.unique(rebuilt)
    compact = np.full((updated.shape[0],), -1, dtype=np.int64)
    compact[used] = np.arange(used.size, dtype=np.int64)
    return (
        np.ascontiguousarray(updated[used], dtype=np.float32),
        np.ascontiguousarray(compact[rebuilt].reshape(-1), dtype=np.uint32),
    )


def _decimate_geometry_python(
    geometry: GeometryData,
    percentage: float = 100.0,
    *,
    name: str = "Decimated Geometry",
    context: GeometryEvalContext | None = None,
) -> GeometryData:
    """Reduce triangle count with constrained quadric edge collapses.

    ``percentage`` is the target percentage of input triangles to retain. UV
    seams and hard-normal splits are represented by disconnected indexed
    vertices and therefore remain protected boundaries automatically.
    """

    if not isinstance(geometry, GeometryData):
        raise TypeError("Geometry Decimate requires a connected Geometry input")
    percentage = min(max(float(percentage), 1.0), 100.0)
    if percentage >= 99.999 or geometry.triangle_count <= 1:
        return geometry.copy(name=name)

    cleaned = clean_weld_geometry(
        geometry,
        remove_degenerate=True,
        remove_unused=True,
        merge_vertices=False,
        name=name,
    )
    original_triangles = cleaned.triangle_count
    if original_triangles <= 1:
        return cleaned
    target = max(1, int(round(original_triangles * percentage / 100.0)))
    vertices = cleaned.vertices.copy()
    indices = cleaned.indices.copy()

    # Rebuilding candidates in moderate independent batches keeps the pure
    # NumPy/Python implementation deterministic without maintaining a fragile
    # mutable half-edge heap. Each accepted collapse is topology checked.
    for _pass in range(96):
        if context is not None:
            context.progress(_pass, 96, "Python fallback mesh simplification")
        current = int(indices.size // 3)
        if current <= target or vertices.shape[0] < 3:
            break
        (
            triangles,
            raw_normals,
            face_lengths,
            edges,
            edge_counts,
            amounts,
            costs,
        ) = _decimation_candidates(vertices, indices)
        if not edges.size:
            break
        order = np.argsort(costs, kind="stable")
        vertex_faces = _vertex_face_lists(triangles, vertices.shape[0])
        boundary_edges = edges[edge_counts == 1]
        boundary_vertex = np.zeros((vertices.shape[0],), dtype=bool)
        if boundary_edges.size:
            boundary_vertex[boundary_edges.reshape(-1)] = True
        boundary_keys = {
            (int(edge[0]), int(edge[1])) for edge in boundary_edges
        }
        neighbour_cache: dict[int, set[int]] = {}

        def neighbours(vertex: int) -> set[int]:
            cached = neighbour_cache.get(vertex)
            if cached is not None:
                return cached
            values: set[int] = set()
            for face_index in vertex_faces[vertex]:
                values.update(int(item) for item in triangles[face_index])
            values.discard(vertex)
            neighbour_cache[vertex] = values
            return values

        selected = np.zeros((vertices.shape[0],), dtype=bool)
        selections: list[tuple[int, int, float, np.ndarray]] = []
        reduction_left = current - target
        max_batch = min(4096, max(1, reduction_left))
        positions = vertices[:, :3]
        mesh_scale = max(float(np.linalg.norm(positions.max(axis=0) - positions.min(axis=0))), 1.0)
        minimum_area_twice = mesh_scale * mesh_scale * 1.0e-12
        for edge_index in order:
            u = int(edges[edge_index, 0])
            v = int(edges[edge_index, 1])
            if selected[u] or selected[v]:
                continue
            removed_faces = int(edge_counts[edge_index])
            if removed_faces > reduction_left:
                continue
            u_boundary = bool(boundary_vertex[u])
            v_boundary = bool(boundary_vertex[v])
            if u_boundary != v_boundary:
                continue
            if u_boundary and (u, v) not in boundary_keys:
                continue
            # The link condition prevents bow-ties and non-manifold collapses.
            if len(neighbours(u).intersection(neighbours(v))) != removed_faces:
                continue
            amount = float(amounts[edge_index])
            replacement = (
                positions[u].astype(np.float64) * (1.0 - amount)
                + positions[v].astype(np.float64) * amount
            ).astype(np.float32)
            if not _collapse_preserves_faces(
                u,
                v,
                replacement,
                triangles,
                positions,
                raw_normals,
                face_lengths,
                vertex_faces,
                minimum_area_twice,
            ):
                continue
            selections.append((u, v, amount, replacement))
            selected[u] = True
            selected[v] = True
            reduction_left -= removed_faces
            if reduction_left <= 0 or len(selections) >= max_batch:
                break
        if not selections:
            break
        candidate_vertices, candidate_indices = _apply_decimation_batch(
            vertices, triangles, selections
        )
        if candidate_indices.size // 3 < target:
            # Independent collapses can occasionally remove duplicate triangles
            # in addition to their directly incident faces. Trim the batch so
            # Percentage never jumps below the requested target.
            low = 1
            high = len(selections)
            best: tuple[np.ndarray, np.ndarray] | None = None
            while low <= high:
                middle = (low + high) // 2
                trial = _apply_decimation_batch(vertices, triangles, selections[:middle])
                if trial[1].size // 3 >= target:
                    best = trial
                    low = middle + 1
                else:
                    high = middle - 1
            if best is None:
                break
            candidate_vertices, candidate_indices = best
        vertices, indices = candidate_vertices, candidate_indices
        if indices.size < 3:
            break

    if indices.size < 3:
        # A valid GeometryData can be empty, but a 1% decimation control is much
        # more useful when it always leaves at least one visible triangle.
        return cleaned.copy(name=name)
    result = GeometryData(vertices, indices, name, geometry.uv_origin)
    if context is not None:
        context.progress(96, 96, "Python fallback mesh simplification complete")
    return result


def decimate_geometry(
    geometry: GeometryData,
    percentage: float = 100.0,
    *,
    name: str = "Decimated Geometry",
    context: GeometryEvalContext | None = None,
) -> GeometryData:
    """Reduce a mesh with native QEM and crack-free attribute reconstruction.

    Attribute seams are welded only for geometric topology, then UV and hard
    normal splits are restored at identical output positions. This avoids the
    visible gaps produced when each side of an imported UV seam is simplified
    independently. A cancellable NumPy implementation remains as a compatibility
    fallback when the native wheel is unavailable.
    """

    if not isinstance(geometry, GeometryData):
        raise TypeError("Geometry Decimate requires a connected Geometry input")
    percentage = min(max(float(percentage), 1.0), 100.0)
    if percentage >= 99.999 or geometry.triangle_count <= 1:
        result = geometry.copy(name=name)
        if context is not None:
            context.report_metadata({
                "_output_vertex_count": result.vertex_count,
                "_output_triangle_count": result.triangle_count,
                "_decimation_backend": "Pass-through",
            })
        return result

    target = max(1, int(round(geometry.triangle_count * percentage / 100.0)))
    native_warning = ""
    try:
        from .mesh_processing import (
            NativeSimplificationCancelled,
            NativeSimplificationUnavailable,
            native_decimate,
        )

        vertices, indices, diagnostics, backend, pass_count = native_decimate(
            geometry.vertices,
            geometry.indices,
            target,
            aggression=3.0,
            cancel_check=context.cancel_check if context is not None else None,
            progress_callback=(
                (lambda current, total, message: context.progress(current, total, message))
                if context is not None
                else None
            ),
        )
        result = GeometryData(vertices, indices, name, geometry.uv_origin)
        if context is not None:
            context.report_metadata({
                **diagnostics.as_metadata(prefix="_output_"),
                "_decimation_backend": backend,
                "_decimation_warning": "",
                "_decimation_target_triangles": target,
                "_decimation_pass_count": pass_count,
                "_decimation_target_reached": result.triangle_count <= target,
            })
        return result
    except GeometryEvaluationCancelled:
        raise
    except Exception as exc:
        # A missing native wheel is expected only when an existing tester venv
        # has not rerun setup. Topology rejection and third-party library errors
        # also fall back safely instead of losing the user's graph preview.
        if exc.__class__.__name__ == "NativeSimplificationCancelled":
            raise GeometryEvaluationCancelled(str(exc)) from exc
        native_warning = str(exc)

    result = _decimate_geometry_python(
        geometry,
        percentage,
        name=name,
        context=context,
    )
    if context is not None:
        from .mesh_processing import diagnose_mesh

        diagnostics = diagnose_mesh(
            result.vertices,
            result.indices,
            cancel_check=context.cancel_check,
        )
        context.report_metadata({
            **diagnostics.as_metadata(prefix="_output_"),
            "_decimation_backend": "Python compatibility fallback",
            "_decimation_warning": native_warning,
            "_decimation_target_triangles": target,
        })
    return result


def _midpoint_matches(
    midpoint: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
    *,
    position_tolerance: float,
    uv_tolerance: float,
) -> bool:
    expected_position = (a[:3] + b[:3]) * 0.5
    if float(np.linalg.norm(midpoint[:3] - expected_position)) > position_tolerance:
        return False
    expected_uv = (a[6:8] + b[6:8]) * 0.5
    if float(np.linalg.norm(midpoint[6:8] - expected_uv)) > uv_tolerance:
        return False
    return True


def _unsubdivide_once(geometry: GeometryData, *, name: str) -> GeometryData | None:
    triangles = geometry.indices.reshape(-1, 3)
    if triangles.shape[0] < 4 or triangles.shape[0] % 4:
        return None

    # Geometry Subdivide writes a stable four-triangle patch for every source
    # triangle. Recognising that signature makes the inverse exact even after
    # smooth relaxation or later position deformations, because those operations
    # do not destroy the authored topology order.
    ordered_originals: list[tuple[int, int, int]] = []
    ordered_match = True
    for start in range(0, triangles.shape[0], 4):
        first, second, third, centre = triangles[start : start + 4]
        a, ab, ca = (int(first[0]), int(first[1]), int(first[2]))
        if int(second[0]) != ab:
            ordered_match = False
            break
        b, bc = int(second[1]), int(second[2])
        if tuple(int(value) for value in third[:2]) != (ca, bc):
            ordered_match = False
            break
        c = int(third[2])
        if tuple(int(value) for value in centre) != (ab, bc, ca):
            ordered_match = False
            break
        if len({a, b, c, ab, bc, ca}) != 6:
            ordered_match = False
            break
        ordered_originals.append((a, b, c))
    if ordered_match and ordered_originals:
        rebuilt = np.asarray(ordered_originals, dtype=np.uint32)
        used = np.unique(rebuilt)
        remap = np.full((geometry.vertex_count,), -1, dtype=np.int64)
        remap[used] = np.arange(used.size, dtype=np.int64)
        return GeometryData(
            np.ascontiguousarray(geometry.vertices[used], dtype=np.float32),
            np.ascontiguousarray(remap[rebuilt].reshape(-1), dtype=np.uint32),
            name,
            geometry.uv_origin,
        )
    edge_map: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for face_index, triangle in enumerate(triangles):
        a, b, c = (int(triangle[0]), int(triangle[1]), int(triangle[2]))
        for u, v, opposite in ((a, b, c), (b, c, a), (c, a, b)):
            key = (min(u, v), max(u, v))
            edge_map.setdefault(key, []).append((face_index, opposite))

    positions = geometry.vertices[:, :3]
    extent = positions.max(axis=0) - positions.min(axis=0) if positions.size else np.ones(3)
    position_tolerance = max(float(np.linalg.norm(extent)) * 2.0e-5, 1.0e-7)
    uv_tolerance = 2.0e-5
    patches: list[tuple[set[int], tuple[int, int, int]]] = []
    vertices = geometry.vertices

    for centre_index, triangle in enumerate(triangles):
        x, y, z = (int(triangle[0]), int(triangle[1]), int(triangle[2]))
        opposite_vertices: list[int] = []
        corner_faces: list[int] = []
        valid = True
        for u, v in ((x, y), (y, z), (z, x)):
            adjacent = edge_map.get((min(u, v), max(u, v)), ())
            if len(adjacent) != 2:
                valid = False
                break
            other = adjacent[0] if adjacent[1][0] == centre_index else adjacent[1]
            if other[0] == centre_index:
                valid = False
                break
            corner_faces.append(int(other[0]))
            opposite_vertices.append(int(other[1]))
        if not valid:
            continue
        # Across central edges x-y, y-z and z-x sit original vertices b, c and a.
        b, c, a = opposite_vertices
        if len({a, b, c, x, y, z}) != 6:
            continue
        if len(set(corner_faces)) != 3:
            continue
        if not _midpoint_matches(
            vertices[x], vertices[a], vertices[b],
            position_tolerance=position_tolerance, uv_tolerance=uv_tolerance,
        ):
            continue
        if not _midpoint_matches(
            vertices[y], vertices[b], vertices[c],
            position_tolerance=position_tolerance, uv_tolerance=uv_tolerance,
        ):
            continue
        if not _midpoint_matches(
            vertices[z], vertices[c], vertices[a],
            position_tolerance=position_tolerance, uv_tolerance=uv_tolerance,
        ):
            continue
        patches.append(({centre_index, *corner_faces}, (a, b, c)))

    if not patches:
        return None
    face_owners = np.zeros((triangles.shape[0],), dtype=np.int32)
    for faces, _original in patches:
        for face_index in faces:
            face_owners[face_index] += 1
    selected_patches = [
        patch for patch in patches if all(face_owners[index] == 1 for index in patch[0])
    ]
    covered: set[int] = set()
    originals: list[tuple[int, int, int]] = []
    for faces, original in selected_patches:
        if covered.intersection(faces):
            continue
        covered.update(faces)
        originals.append(original)
    if len(covered) != triangles.shape[0] or len(originals) * 4 != triangles.shape[0]:
        return None

    rebuilt = np.asarray(originals, dtype=np.uint32)
    used = np.unique(rebuilt)
    remap = np.full((geometry.vertex_count,), -1, dtype=np.int64)
    remap[used] = np.arange(used.size, dtype=np.int64)
    return GeometryData(
        np.ascontiguousarray(vertices[used], dtype=np.float32),
        np.ascontiguousarray(remap[rebuilt].reshape(-1), dtype=np.uint32),
        name,
        geometry.uv_origin,
    )



def _cluster_grid_axis(values: np.ndarray, tolerance: float) -> tuple[np.ndarray, np.ndarray]:
    """Cluster nearly equal UV coordinates and return centres plus per-value bins."""

    order = np.argsort(values, kind="stable")
    bins = np.empty(values.shape[0], dtype=np.int32)
    centres: list[float] = []
    members: list[int] = []
    current: list[float] = []
    for raw_index in order:
        index = int(raw_index)
        value = float(values[index])
        if current and abs(value - float(np.mean(current))) > tolerance:
            centre_index = len(centres)
            centres.append(float(np.mean(current)))
            bins[np.asarray(members, dtype=np.int64)] = centre_index
            current = []
            members = []
        current.append(value)
        members.append(index)
    if current:
        centre_index = len(centres)
        centres.append(float(np.mean(current)))
        bins[np.asarray(members, dtype=np.int64)] = centre_index
    return np.asarray(centres, dtype=np.float64), bins


def _triangle_components(triangles: np.ndarray, vertex_count: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """Return topology islands as (vertex ids, face ids)."""

    parent = np.arange(vertex_count, dtype=np.int64)
    rank = np.zeros(vertex_count, dtype=np.int8)

    def find(value: int) -> int:
        root = value
        while int(parent[root]) != root:
            root = int(parent[root])
        while int(parent[value]) != value:
            following = int(parent[value])
            parent[value] = root
            value = following
        return root

    def union(first: int, second: int) -> None:
        a = find(first)
        b = find(second)
        if a == b:
            return
        if rank[a] < rank[b]:
            a, b = b, a
        parent[b] = a
        if rank[a] == rank[b]:
            rank[a] += 1

    for triangle in triangles:
        a, b, c = (int(triangle[0]), int(triangle[1]), int(triangle[2]))
        union(a, b)
        union(a, c)

    face_groups: dict[int, list[int]] = {}
    vertex_groups: dict[int, set[int]] = {}
    for face_index, triangle in enumerate(triangles):
        root = find(int(triangle[0]))
        face_groups.setdefault(root, []).append(face_index)
        vertex_groups.setdefault(root, set()).update(int(value) for value in triangle)
    return [
        (
            np.asarray(sorted(vertex_groups[root]), dtype=np.int64),
            np.asarray(face_groups[root], dtype=np.int64),
        )
        for root in face_groups
    ]


def _structured_uv_unsubdivide_once(
    geometry: GeometryData,
    *,
    name: str,
) -> GeometryData | None:
    """Reduce regular triangulated UV grids by keeping alternate rows/columns.

    Plane, Box and Ribbon generators create regular UV lattices rather than the
    four-triangle midpoint pattern emitted by Geometry Subdivide.  A true
    topological un-subdivide can still be performed on those lattices, including
    after position-only deformation, by using UVs to recover rows and columns.
    """

    triangles = geometry.indices.reshape(-1, 3)
    if not triangles.size:
        return None
    vertices = geometry.vertices
    components = _triangle_components(triangles, geometry.vertex_count)
    output_vertices: list[np.ndarray] = []
    output_indices: list[np.ndarray] = []
    reduced_any = False

    for vertex_ids, face_ids in components:
        local_uvs = vertices[vertex_ids, 6:8].astype(np.float64, copy=False)
        span = np.ptp(local_uvs, axis=0)
        tolerance_u = max(float(span[0]) * 1.0e-5, 1.0e-6)
        tolerance_v = max(float(span[1]) * 1.0e-5, 1.0e-6)
        u_values, u_bins = _cluster_grid_axis(local_uvs[:, 0], tolerance_u)
        v_values, v_bins = _cluster_grid_axis(local_uvs[:, 1], tolerance_v)
        columns = int(u_values.size)
        rows = int(v_values.size)
        if columns < 2 or rows < 2 or columns * rows != vertex_ids.size:
            return None

        grid = np.full((rows, columns), -1, dtype=np.int64)
        for local_index, global_index in enumerate(vertex_ids):
            row = int(v_bins[local_index])
            column = int(u_bins[local_index])
            if grid[row, column] >= 0:
                return None
            grid[row, column] = int(global_index)
        if np.any(grid < 0):
            return None

        # Confirm that every source triangle is local to one UV-grid cell. This
        # prevents arbitrary meshes with coincident UV coordinates from being
        # mistaken for a structured generator lattice.
        inverse = {int(global_index): local_index for local_index, global_index in enumerate(vertex_ids)}
        for face_index in face_ids:
            triangle = triangles[int(face_index)]
            local = np.asarray([inverse[int(value)] for value in triangle], dtype=np.int64)
            face_u = u_bins[local]
            face_v = v_bins[local]
            if int(face_u.max() - face_u.min()) > 1 or int(face_v.max() - face_v.min()) > 1:
                return None

        selected_u = list(range(0, columns, 2))
        selected_v = list(range(0, rows, 2))
        if selected_u[-1] != columns - 1:
            selected_u.append(columns - 1)
        if selected_v[-1] != rows - 1:
            selected_v.append(rows - 1)
        if len(selected_u) == columns and len(selected_v) == rows:
            return None
        reduced_any = True

        component_triangles: list[int] = []
        for row_index in range(len(selected_v) - 1):
            top = selected_v[row_index]
            bottom = selected_v[row_index + 1]
            for column_index in range(len(selected_u) - 1):
                left = selected_u[column_index]
                right = selected_u[column_index + 1]
                a = int(grid[top, left])
                b = int(grid[top, right])
                c = int(grid[bottom, left])
                d = int(grid[bottom, right])
                pa, pb, pc = vertices[[a, b, c], :3]
                normal = np.cross(pb - pa, pc - pa)
                authored = vertices[[a, b, c, d], 3:6].sum(axis=0)
                if float(np.dot(normal, authored)) >= 0.0:
                    component_triangles.extend((a, b, c, b, d, c))
                else:
                    component_triangles.extend((a, c, b, b, c, d))

        component_indices = np.asarray(component_triangles, dtype=np.uint32)
        component_indices = _drop_degenerate_triangles(component_indices, vertices[:, :3])
        if component_indices.size < 3:
            return None
        used = np.unique(component_indices)
        remap = np.full((geometry.vertex_count,), -1, dtype=np.int64)
        remap[used] = np.arange(used.size, dtype=np.int64)
        base = sum(chunk.shape[0] for chunk in output_vertices)
        output_vertices.append(np.ascontiguousarray(vertices[used], dtype=np.float32))
        output_indices.append(
            np.ascontiguousarray(remap[component_indices].astype(np.uint32) + base, dtype=np.uint32)
        )

    if not reduced_any or not output_indices:
        return None
    return GeometryData(
        np.ascontiguousarray(np.concatenate(output_vertices, axis=0), dtype=np.float32),
        np.ascontiguousarray(np.concatenate(output_indices), dtype=np.uint32),
        name,
        geometry.uv_origin,
    )

def unsubdivide_geometry(
    geometry: GeometryData,
    iterations: int = 1,
    *,
    name: str = "Un-Subdivided Geometry",
) -> GeometryData:
    """Reverse compatible subdivision or structured UV-grid topology.

    Geometry Subdivide lineage is restored exactly. Regular UV lattices from
    Plane, Box and Ribbon generators can also be reduced by alternate rows and
    columns. Arbitrary imported scans do not retain an earlier control mesh and
    should be simplified with Geometry Decimate instead.
    """

    if not isinstance(geometry, GeometryData):
        raise TypeError("Geometry Un-Subdivide requires a connected Geometry input")
    iterations = min(max(int(iterations), 1), 6)
    result = geometry.copy(name=name)
    completed = 0
    mode: str | None = None
    for _iteration in range(iterations):
        rebuilt = None
        if mode != "grid":
            rebuilt = _unsubdivide_once(result, name=name)
            if rebuilt is not None:
                mode = "midpoint"
            elif mode == "midpoint":
                # Once a Geometry Subdivide lineage has been reversed, stop at
                # its original authored mesh rather than unexpectedly applying
                # a second grid-reduction algorithm to that source mesh.
                break
        if rebuilt is None and mode in {None, "grid"}:
            rebuilt = _structured_uv_unsubdivide_once(result, name=name)
            if rebuilt is not None:
                mode = "grid"
        if rebuilt is None:
            break
        result = rebuilt
        completed += 1
    if completed == 0:
        raise ValueError(
            "Geometry Un-Subdivide could not find compatible midpoint subdivision topology or regular UV-grid topology. "
            "It works after Geometry Subdivide and on structured Plane, Box and Ribbon grids. "
            "Arbitrary imported or scanned meshes do not retain an earlier control mesh; use Geometry Decimate for those."
        )
    result.name = name
    return result

def normals_geometry(
    geometry: GeometryData,
    mode: str = "Smooth",
    smoothing_angle: float = 60.0,
    *,
    flip_normals: bool = False,
    reverse_winding: bool = False,
    name: str = "Geometry Normals",
) -> GeometryData:
    """Rebuild mesh normals as smooth, angle-limited or flat normals."""

    if not isinstance(geometry, GeometryData):
        raise TypeError("Geometry Normals requires a connected Geometry input")
    indices = geometry.indices.copy()
    if reverse_winding:
        triangles = indices.reshape(-1, 3).copy()
        triangles[:, [1, 2]] = triangles[:, [2, 1]]
        indices = triangles.reshape(-1)

    positions = geometry.vertices[:, :3]
    mode = str(mode or "Smooth")
    if mode == "Smooth":
        vertices = geometry.vertices.copy()
        vertices[:, 3:6] = _smooth_vertex_normals(positions, indices)
    else:
        triangles = indices.reshape(-1, 3)
        raw_faces, unit_faces = _triangle_face_data(positions, indices)
        position_keys, groups = _position_groups(positions)
        incident: list[list[int]] = [[] for _ in range(position_keys.shape[0])]
        for face_index, triangle in enumerate(triangles):
            for vertex_index in triangle:
                incident[int(groups[int(vertex_index)])].append(face_index)
        threshold = math.cos(math.radians(min(max(float(smoothing_angle), 0.0), 180.0)))
        rebuilt_vertices: list[np.ndarray] = []
        rebuilt_indices: list[int] = []
        for face_index, triangle in enumerate(triangles):
            face_normal = unit_faces[face_index]
            for raw_vertex in triangle:
                vertex_index = int(raw_vertex)
                value = geometry.vertices[vertex_index].copy()
                if mode == "Flat":
                    normal = face_normal
                else:
                    nearby = incident[int(groups[vertex_index])]
                    selected = [
                        neighbour
                        for neighbour in nearby
                        if float(np.dot(face_normal, unit_faces[neighbour])) >= threshold - 1.0e-6
                    ]
                    summed = raw_faces[selected].sum(axis=0) if selected else raw_faces[face_index]
                    length = float(np.linalg.norm(summed))
                    normal = summed / length if length > 1.0e-8 else face_normal
                value[3:6] = normal
                rebuilt_indices.append(len(rebuilt_vertices))
                rebuilt_vertices.append(value)
        vertices = np.asarray(rebuilt_vertices, dtype=np.float32)
        indices = np.asarray(rebuilt_indices, dtype=np.uint32)

    if flip_normals:
        vertices[:, 3:6] *= -1.0
    return GeometryData(vertices, indices, name, geometry.uv_origin)


def _sample_height_bilinear(
    heightmap: np.ndarray, uvs: np.ndarray, uv_origin: str = UV_ORIGIN_TOP_LEFT
) -> np.ndarray:
    image = np.asarray(heightmap, dtype=np.float32)
    if image.ndim == 3:
        if image.shape[2] < 1:
            raise ValueError("Height input has no channels")
        image = image[..., 0]
    if image.ndim != 2 or image.shape[0] < 1 or image.shape[1] < 1:
        raise ValueError(f"Height input must be a grayscale image, got {image.shape}")
    height, width = image.shape
    uv = np.asarray(uvs, dtype=np.float32)
    # Geometry UVs may intentionally exceed 0-1 because generators support
    # integer tiling. Repeat sampling keeps those seams exact.
    wrapped = uv - np.floor(uv)
    x = wrapped[:, 0] * width - 0.5
    sample_v = wrapped[:, 1]
    if normalise_uv_origin(uv_origin) == UV_ORIGIN_BOTTOM_LEFT:
        sample_v = 1.0 - sample_v
    y = sample_v * height - 0.5
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    tx = (x - x0).astype(np.float32)
    ty = (y - y0).astype(np.float32)
    x0 %= width
    y0 %= height
    x1 = (x0 + 1) % width
    y1 = (y0 + 1) % height
    a = image[y0, x0]
    b = image[y0, x1]
    c = image[y1, x0]
    d = image[y1, x1]
    top_row = a * (1.0 - tx) + b * tx
    bottom_row = c * (1.0 - tx) + d * tx
    return np.ascontiguousarray(top_row * (1.0 - ty) + bottom_row * ty, dtype=np.float32)


def displace_geometry(
    geometry: GeometryData,
    heightmap: np.ndarray,
    amount: float = 1.0,
    *,
    name: str = "Displaced Geometry",
) -> GeometryData:
    """Displace vertices along their stored normals using a grayscale heightmap."""

    if not isinstance(geometry, GeometryData):
        raise TypeError("Geometry Displace requires a connected Geometry input")
    vertices = geometry.vertices.copy()
    normals = vertices[:, 3:6]
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    unit_normals = normals / np.maximum(lengths, 1.0e-8)
    sampled = _sample_height_bilinear(heightmap, vertices[:, 6:8], geometry.uv_origin)
    vertices[:, :3] += unit_normals * (sampled[:, None] * float(amount))
    # Displacement intentionally preserves authored normals. Terrain and VFX
    # meshes commonly receive final shading from a normal map; explicit mesh
    # normal rebuilding belongs to the Geometry Normals node.
    vertices[:, 3:6] = normals
    return GeometryData(vertices, geometry.indices.copy(), name, geometry.uv_origin)



def evaluate_ribbon_geometry(
    _inputs: Mapping[str, Any], parameters: Mapping[str, Any]
) -> GeometryData:
    return ribbon_geometry(
        length=float(parameters.get("length", 4.0)),
        width_start=float(parameters.get("width_start", 1.0)),
        width_end=float(parameters.get("width_end", 1.0)),
        length_segments=int(parameters.get("length_segments", 16)),
        width_segments=int(parameters.get("width_segments", 1)),
        orientation=str(parameters.get("orientation", "Horizontal (XZ)")),
        origin_x=float(parameters.get("origin_x", 0.0)),
        origin_y=float(parameters.get("origin_y", 0.0)),
        origin_z=float(parameters.get("origin_z", 0.0)),
        rotation_x=float(parameters.get("rotation_x", 0.0)),
        rotation_y=float(parameters.get("rotation_y", 0.0)),
        rotation_z=float(parameters.get("rotation_z", 0.0)),
        uv_tiles_u=int(parameters.get("uv_tiles_u", 1)),
        uv_tiles_v=int(parameters.get("uv_tiles_v", 1)),
        name=str(parameters.get("name", "Geometry Ribbon") or "Geometry Ribbon"),
    )


def evaluate_bend_geometry(
    inputs: Mapping[str, Any], parameters: Mapping[str, Any]
) -> GeometryData:
    geometry = inputs.get("Geometry")
    if not isinstance(geometry, GeometryData):
        raise ValueError("Geometry is not connected")
    return bend_geometry(
        geometry,
        amount=float(parameters.get("amount", 90.0)),
        deformation_axis=str(parameters.get("deformation_axis", "Axis Z")),
        direction=float(parameters.get("direction", 0.0)),
        pivot_mode=str(parameters.get("pivot_mode", "Current Origin")),
        range_start=float(parameters.get("range_start", 0.0)),
        range_end=float(parameters.get("range_end", 1.0)),
        clamp_outside=bool(parameters.get("clamp_outside", True)),
        name=str(parameters.get("name", "Bent Geometry") or "Bent Geometry"),
    )


def evaluate_twist_geometry(
    inputs: Mapping[str, Any], parameters: Mapping[str, Any]
) -> GeometryData:
    geometry = inputs.get("Geometry")
    if not isinstance(geometry, GeometryData):
        raise ValueError("Geometry is not connected")
    return twist_geometry(
        geometry,
        amount=float(parameters.get("amount", 180.0)),
        axis=str(parameters.get("axis", "Axis Z")),
        pivot_mode=str(parameters.get("pivot_mode", "Current Origin")),
        range_start=float(parameters.get("range_start", 0.0)),
        range_end=float(parameters.get("range_end", 1.0)),
        clamp_outside=bool(parameters.get("clamp_outside", True)),
        name=str(parameters.get("name", "Twisted Geometry") or "Twisted Geometry"),
    )


def evaluate_uv_transform_geometry(
    inputs: Mapping[str, Any], parameters: Mapping[str, Any]
) -> GeometryData:
    geometry = inputs.get("Geometry")
    if not isinstance(geometry, GeometryData):
        raise ValueError("Geometry is not connected")
    return uv_transform_geometry(
        geometry,
        scale_u=float(parameters.get("scale_u", 1.0)),
        scale_v=float(parameters.get("scale_v", 1.0)),
        offset_u=float(parameters.get("offset_u", 0.0)),
        offset_v=float(parameters.get("offset_v", 0.0)),
        rotation=float(parameters.get("rotation", 0.0)),
        pivot_u=float(parameters.get("pivot_u", 0.5)),
        pivot_v=float(parameters.get("pivot_v", 0.5)),
        flip_u=bool(parameters.get("flip_u", False)),
        flip_v=bool(parameters.get("flip_v", False)),
        swap_uv=bool(parameters.get("swap_uv", False)),
        name=str(parameters.get("name", "UV Transformed Geometry") or "UV Transformed Geometry"),
    )


def evaluate_clean_weld_geometry(
    inputs: Mapping[str, Any], parameters: Mapping[str, Any]
) -> GeometryData:
    geometry = inputs.get("Geometry")
    if not isinstance(geometry, GeometryData):
        raise ValueError("Geometry is not connected")
    return clean_weld_geometry(
        geometry,
        remove_degenerate=bool(parameters.get("remove_degenerate", True)),
        remove_unused=bool(parameters.get("remove_unused", True)),
        merge_vertices=bool(parameters.get("merge_vertices", True)),
        weld_distance=float(parameters.get("weld_distance", 0.0)),
        preserve_uv_seams=bool(parameters.get("preserve_uv_seams", True)),
        preserve_hard_edges=bool(parameters.get("preserve_hard_edges", True)),
        name=str(parameters.get("name", "Cleaned Geometry") or "Cleaned Geometry"),
    )


def evaluate_disc_ring_geometry(
    _inputs: Mapping[str, Any], parameters: Mapping[str, Any]
) -> GeometryData:
    return disc_ring_geometry(
        outer_radius=float(parameters.get("outer_radius", 1.0)),
        inner_radius=float(parameters.get("inner_radius", 0.0)),
        radial_segments=int(parameters.get("radial_segments", 64)),
        ring_segments=int(parameters.get("ring_segments", 1)),
        arc_start=float(parameters.get("arc_start", 0.0)),
        arc_spread=float(parameters.get("arc_spread", 360.0)),
        uv_mode=str(parameters.get("uv_mode", "Planar")),
        orientation=str(parameters.get("orientation", "Axis Y")),
        origin_x=float(parameters.get("origin_x", 0.0)),
        origin_y=float(parameters.get("origin_y", 0.0)),
        origin_z=float(parameters.get("origin_z", 0.0)),
        rotation_x=float(parameters.get("rotation_x", 0.0)),
        rotation_y=float(parameters.get("rotation_y", 0.0)),
        rotation_z=float(parameters.get("rotation_z", 0.0)),
        uv_tiles_u=int(parameters.get("uv_tiles_u", 1)),
        uv_tiles_v=int(parameters.get("uv_tiles_v", 1)),
        name=str(parameters.get("name", "Geometry Disc / Ring") or "Geometry Disc / Ring"),
    )


def evaluate_transform_geometry(
    inputs: Mapping[str, Any], parameters: Mapping[str, Any]
) -> GeometryData:
    geometry = inputs.get("Geometry")
    if not isinstance(geometry, GeometryData):
        raise ValueError("Geometry is not connected")
    return transform_geometry(
        geometry,
        translate_x=float(parameters.get("translate_x", 0.0)),
        translate_y=float(parameters.get("translate_y", 0.0)),
        translate_z=float(parameters.get("translate_z", 0.0)),
        rotation_x=float(parameters.get("rotation_x", 0.0)),
        rotation_y=float(parameters.get("rotation_y", 0.0)),
        rotation_z=float(parameters.get("rotation_z", 0.0)),
        uniform_scale=float(parameters.get("uniform_scale", 1.0)),
        scale_x=float(parameters.get("scale_x", 1.0)),
        scale_y=float(parameters.get("scale_y", 1.0)),
        scale_z=float(parameters.get("scale_z", 1.0)),
        pivot_mode=str(parameters.get("pivot_mode", "Current Origin")),
        name=str(parameters.get("name", "Transformed Geometry") or "Transformed Geometry"),
    )


def evaluate_subdivide_geometry(
    inputs: Mapping[str, Any], parameters: Mapping[str, Any]
) -> GeometryData:
    geometry = inputs.get("Geometry")
    if not isinstance(geometry, GeometryData):
        raise ValueError("Geometry is not connected")
    return subdivide_geometry(
        geometry,
        levels=int(parameters.get("levels", 1)),
        smooth_surface=bool(parameters.get("smooth_surface", False)),
        name=str(parameters.get("name", "Subdivided Geometry") or "Subdivided Geometry"),
    )



def evaluate_decimate_geometry(
    inputs: Mapping[str, Any],
    parameters: Mapping[str, Any],
    context: GeometryEvalContext | None = None,
) -> GeometryData:
    geometry = inputs.get("Geometry")
    if not isinstance(geometry, GeometryData):
        raise ValueError("Geometry is not connected")
    return decimate_geometry(
        geometry,
        percentage=float(parameters.get("percentage", 100.0)),
        name=str(parameters.get("name", "Decimated Geometry") or "Decimated Geometry"),
        context=context,
    )


def evaluate_unsubdivide_geometry(
    inputs: Mapping[str, Any], parameters: Mapping[str, Any]
) -> GeometryData:
    geometry = inputs.get("Geometry")
    if not isinstance(geometry, GeometryData):
        raise ValueError("Geometry is not connected")
    return unsubdivide_geometry(
        geometry,
        iterations=int(parameters.get("iterations", 1)),
        name=str(parameters.get("name", "Un-Subdivided Geometry") or "Un-Subdivided Geometry"),
    )

def evaluate_normals_geometry(
    inputs: Mapping[str, Any], parameters: Mapping[str, Any]
) -> GeometryData:
    geometry = inputs.get("Geometry")
    if not isinstance(geometry, GeometryData):
        raise ValueError("Geometry is not connected")
    return normals_geometry(
        geometry,
        mode=str(parameters.get("mode", "Smooth")),
        smoothing_angle=float(parameters.get("smoothing_angle", 60.0)),
        flip_normals=bool(parameters.get("flip_normals", False)),
        reverse_winding=bool(parameters.get("reverse_winding", False)),
        name=str(parameters.get("name", "Geometry Normals") or "Geometry Normals"),
    )


def evaluate_plane_geometry(
    _inputs: Mapping[str, GeometryData], parameters: Mapping[str, Any]
) -> GeometryData:
    return plane_geometry(
        width=float(parameters.get("width", 2.0)),
        height=float(parameters.get("height", 2.0)),
        subdivisions_x=int(parameters.get("subdivisions_x", 16)),
        subdivisions_y=int(parameters.get("subdivisions_y", 16)),
        orientation=str(parameters.get("orientation", "Horizontal (XZ)")),
        origin_x=float(parameters.get("origin_x", 0.0)),
        origin_y=float(parameters.get("origin_y", 0.0)),
        origin_z=float(parameters.get("origin_z", 0.0)),
        rotation_x=float(parameters.get("rotation_x", 0.0)),
        rotation_y=float(parameters.get("rotation_y", 0.0)),
        rotation_z=float(parameters.get("rotation_z", 0.0)),
        uv_tiles_u=int(parameters.get("uv_tiles_u", 1)),
        uv_tiles_v=int(parameters.get("uv_tiles_v", 1)),
        name=str(parameters.get("name", "Geometry Plane") or "Geometry Plane"),
    )


def evaluate_box_geometry(
    _inputs: Mapping[str, GeometryData], parameters: Mapping[str, Any]
) -> GeometryData:
    return box_geometry(
        width=float(parameters.get("width", 2.0)),
        height=float(parameters.get("height", 2.0)),
        depth=float(parameters.get("depth", 2.0)),
        subdivisions_x=int(parameters.get("subdivisions_x", 1)),
        subdivisions_y=int(parameters.get("subdivisions_y", 1)),
        subdivisions_z=int(parameters.get("subdivisions_z", 1)),
        origin_x=float(parameters.get("origin_x", 0.0)),
        origin_y=float(parameters.get("origin_y", 0.0)),
        origin_z=float(parameters.get("origin_z", 0.0)),
        rotation_x=float(parameters.get("rotation_x", 0.0)),
        rotation_y=float(parameters.get("rotation_y", 0.0)),
        rotation_z=float(parameters.get("rotation_z", 0.0)),
        uv_tiles_u=int(parameters.get("uv_tiles_u", 1)),
        uv_tiles_v=int(parameters.get("uv_tiles_v", 1)),
        name=str(parameters.get("name", "Geometry Box") or "Geometry Box"),
    )


def evaluate_cylinder_geometry(
    _inputs: Mapping[str, GeometryData], parameters: Mapping[str, Any]
) -> GeometryData:
    return cylinder_geometry(
        radius=float(parameters.get("radius", 1.0)),
        height=float(parameters.get("height", 2.0)),
        radial_segments=int(parameters.get("radial_segments", 32)),
        height_segments=int(parameters.get("height_segments", 1)),
        top_radius_offset=float(parameters.get("top_radius_offset", 0.0)),
        bottom_radius_offset=float(parameters.get("bottom_radius_offset", 0.0)),
        caps=bool(parameters.get("caps", True)),
        cap_segments=int(parameters.get("cap_segments", 1)),
        smooth_sides=bool(parameters.get("smooth_sides", True)),
        orientation=str(parameters.get("orientation", "Axis Y")),
        origin_x=float(parameters.get("origin_x", 0.0)),
        origin_y=float(parameters.get("origin_y", 0.0)),
        origin_z=float(parameters.get("origin_z", 0.0)),
        rotation_x=float(parameters.get("rotation_x", 0.0)),
        rotation_y=float(parameters.get("rotation_y", 0.0)),
        rotation_z=float(parameters.get("rotation_z", 0.0)),
        uv_tiles_u=int(parameters.get("uv_tiles_u", 1)),
        uv_tiles_v=int(parameters.get("uv_tiles_v", 1)),
        name=str(parameters.get("name", "Geometry Cylinder") or "Geometry Cylinder"),
    )


def evaluate_combine_geometry(
    inputs: Mapping[str, Any], parameters: Mapping[str, Any]
) -> GeometryData:
    bottom = inputs.get("Bottom Geometry")
    top = inputs.get("Top Geometry")
    if not isinstance(bottom, GeometryData):
        raise ValueError("Bottom Geometry is not connected")
    if not isinstance(top, GeometryData):
        raise ValueError("Top Geometry is not connected")
    return combine_geometry(
        bottom,
        top,
        name=str(parameters.get("name", "Combined Geometry") or "Combined Geometry"),
    )


def evaluate_displace_geometry(
    inputs: Mapping[str, Any], parameters: Mapping[str, Any]
) -> GeometryData:
    geometry = inputs.get("Geometry")
    heightmap = inputs.get("Height")
    if not isinstance(geometry, GeometryData):
        raise ValueError("Geometry is not connected")
    if heightmap is None:
        raise ValueError("Height is not connected")
    return displace_geometry(
        geometry,
        np.asarray(heightmap, dtype=np.float32),
        amount=float(parameters.get("amount", 1.0)),
        name=str(parameters.get("name", "Displaced Geometry") or "Displaced Geometry"),
    )


def export_obj(
    geometry: GeometryData,
    path: str | Path,
    *,
    include_uvs: bool = True,
    include_normals: bool = True,
    flip_v: bool = False,
) -> Path:
    """Write a standards-compatible indexed Wavefront OBJ mesh."""

    destination = Path(path).expanduser()
    if destination.suffix.lower() != ".obj":
        destination = destination.with_suffix(".obj")
    destination.parent.mkdir(parents=True, exist_ok=True)

    vertices = geometry.vertices
    object_name = str(geometry.name or destination.stem).replace("\r", " ").replace("\n", " ").strip()
    lines = [
        "# Exported by VFX Texture Lab",
        f"o {object_name or destination.stem}",
    ]
    for position in vertices[:, :3]:
        lines.append(f"v {position[0]:.9g} {position[1]:.9g} {position[2]:.9g}")
    if include_uvs:
        standard_vertices = convert_uv_origin(
            vertices, geometry.uv_origin, UV_ORIGIN_BOTTOM_LEFT
        )
        for uv in standard_vertices[:, 6:8]:
            v = 1.0 - float(uv[1]) if flip_v else float(uv[1])
            lines.append(f"vt {float(uv[0]):.9g} {v:.9g}")
    if include_normals:
        for normal in vertices[:, 3:6]:
            lines.append(f"vn {normal[0]:.9g} {normal[1]:.9g} {normal[2]:.9g}")

    indices = geometry.indices.reshape(-1, 3)
    for triangle in indices:
        refs: list[str] = []
        for raw_index in triangle:
            index = int(raw_index) + 1
            if include_uvs and include_normals:
                refs.append(f"{index}/{index}/{index}")
            elif include_uvs:
                refs.append(f"{index}/{index}")
            elif include_normals:
                refs.append(f"{index}//{index}")
            else:
                refs.append(str(index))
        lines.append("f " + " ".join(refs))

    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination
