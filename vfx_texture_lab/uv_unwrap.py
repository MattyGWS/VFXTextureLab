"""Manual UV unwrapping, persistent derived-mesh caches and UV previews.

The automatic path uses the compiled xatlas bindings when available.  Projection
modes remain dependency-free so a saved graph can still present its previous
successful result even when a native wheel is temporarily unavailable.
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

import numpy as np
from PIL import Image, ImageDraw

from .geometry import (
    GeometryData, GeometryEvalContext, GeometryEvaluationCancelled,
    UV_ORIGIN_BOTTOM_LEFT, convert_uv_origin,
)


_CACHE_LOCK = threading.RLock()
_RESULT_CACHE: "OrderedDict[str, UVUnwrapResult]" = OrderedDict()
_RESULT_CACHE_BUDGET = 512 * 1024 * 1024
UV_OVERLAP_ANALYSIS_TRIANGLE_LIMIT = 50_000
UV_PREVIEW_TRIANGLE_LIMIT = 50_000


@dataclass(slots=True)
class UVUnwrapResult:
    geometry: GeometryData
    chart_ids: np.ndarray
    diagnostics: dict[str, Any]

    @property
    def memory_bytes(self) -> int:
        return int(
            self.geometry.vertices.nbytes
            + self.geometry.indices.nbytes
            + self.chart_ids.nbytes
        )


def _normalise(vectors: np.ndarray) -> np.ndarray:
    values = np.asarray(vectors, dtype=np.float32)
    lengths = np.linalg.norm(values, axis=1, keepdims=True)
    return values / np.maximum(lengths, 1.0e-8)


def geometry_signature(
    geometry: GeometryData,
    parameters: Mapping[str, Any],
    parameter_names: tuple[str, ...],
) -> str:
    """Stable signature for the geometry and settings that affect an unwrap."""

    digest = hashlib.blake2b(digest_size=20)
    # Positions and normals always affect the published geometry. Existing UVs
    # additionally affect Automatic Charts when seam preservation is enabled,
    # so a UV-only upstream edit must not be mistaken for an unchanged source.
    include_source_uvs = bool(
        str(parameters.get("mode", "Automatic Charts")) == "Automatic Charts"
        and parameters.get("preserve_existing_seams", True)
    )
    attribute_count = 8 if include_source_uvs else 6
    digest.update(
        np.ascontiguousarray(
            geometry.vertices[:, :attribute_count], dtype=np.float32
        ).tobytes()
    )
    digest.update(np.ascontiguousarray(geometry.indices, dtype=np.uint32).tobytes())
    digest.update(geometry.uv_origin.encode("ascii"))
    relevant = {name: parameters.get(name) for name in parameter_names}
    digest.update(json.dumps(relevant, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8"))
    return digest.hexdigest()


def encode_result(result: UVUnwrapResult) -> str:
    """Serialize a completed unwrap without losing per-triangle diagnostics.

    Large NumPy arrays are stored as arrays in the compressed archive rather
    than being stringified into the JSON metadata.  This matters for overlap
    highlighting after a graph has been closed and reopened.
    """

    stream = BytesIO()
    diagnostics = {
        str(key): value
        for key, value in result.diagnostics.items()
        if key != "overlap_mask"
    }
    overlap_mask = np.asarray(
        result.diagnostics.get(
            "overlap_mask",
            np.zeros(result.geometry.triangle_count, dtype=bool),
        ),
        dtype=np.uint8,
    ).reshape(-1)
    np.savez_compressed(
        stream,
        vertices=np.asarray(result.geometry.vertices, dtype=np.float32),
        indices=np.asarray(result.geometry.indices, dtype=np.uint32),
        chart_ids=np.asarray(result.chart_ids, dtype=np.int32),
        overlap_mask=overlap_mask,
        name=np.asarray([result.geometry.name]),
        uv_origin=np.asarray([result.geometry.uv_origin]),
        diagnostics=np.asarray([json.dumps(diagnostics, separators=(",", ":"), default=str)]),
    )
    return base64.b64encode(stream.getvalue()).decode("ascii")


def decode_result(encoded: str) -> UVUnwrapResult:
    payload = str(encoded or "").strip()
    if not payload:
        raise ValueError("No saved UV result is available")
    cache_key = hashlib.blake2b(payload.encode("ascii", errors="ignore"), digest_size=16).hexdigest()
    with _CACHE_LOCK:
        cached = _RESULT_CACHE.get(cache_key)
        if cached is not None:
            _RESULT_CACHE.move_to_end(cache_key)
            return cached
    try:
        raw = base64.b64decode(payload, validate=True)
        with np.load(BytesIO(raw), allow_pickle=False) as archive:
            name = str(archive["name"][0]) if "name" in archive else "UV Unwrapped Geometry"
            diagnostics_raw = str(archive["diagnostics"][0]) if "diagnostics" in archive else "{}"
            uv_origin = (
                str(archive["uv_origin"][0])
                if "uv_origin" in archive
                else UV_ORIGIN_BOTTOM_LEFT
            )
            geometry = GeometryData(archive["vertices"], archive["indices"], name, uv_origin)
            diagnostics = dict(json.loads(diagnostics_raw))
            if "overlap_mask" in archive:
                diagnostics["overlap_mask"] = np.ascontiguousarray(
                    archive["overlap_mask"], dtype=np.uint8
                ).reshape(-1).astype(bool, copy=False)
            else:
                # Compatibility with early 0.52.0 development payloads.
                diagnostics["overlap_mask"] = np.zeros(
                    geometry.triangle_count, dtype=bool
                )
            result = UVUnwrapResult(
                geometry,
                np.ascontiguousarray(archive["chart_ids"], dtype=np.int32).reshape(-1),
                diagnostics,
            )
    except Exception as exc:
        raise ValueError("Saved UV unwrap result is damaged") from exc
    with _CACHE_LOCK:
        _RESULT_CACHE[cache_key] = result
        _RESULT_CACHE.move_to_end(cache_key)
        total = sum(item.memory_bytes for item in _RESULT_CACHE.values())
        while total > _RESULT_CACHE_BUDGET and len(_RESULT_CACHE) > 1:
            _key, old = _RESULT_CACHE.popitem(last=False)
            total -= old.memory_bytes
    return result


def _compact_vertices(
    source: GeometryData,
    corner_uvs: np.ndarray,
    triangle_chart_ids: np.ndarray,
    *,
    name: str,
) -> UVUnwrapResult:
    """Rebuild vertices at UV seams while preserving authored normals."""

    triangles = source.indices.reshape(-1, 3)
    corner_uvs = np.asarray(corner_uvs, dtype=np.float32).reshape(-1, 3, 2)
    if corner_uvs.shape[0] != triangles.shape[0]:
        raise ValueError("UV corner data does not match the triangle count")
    flat_source = triangles.reshape(-1)
    flat_uv = corner_uvs.reshape(-1, 2)
    # Exact enough for deterministic projection output while not merging a wrap seam.
    quantized = np.round(flat_uv.astype(np.float64), 7)
    keys = np.empty(flat_source.size, dtype=[("source", np.uint32), ("u", np.float64), ("v", np.float64)])
    keys["source"] = flat_source
    keys["u"] = quantized[:, 0]
    keys["v"] = quantized[:, 1]
    unique, first, inverse = np.unique(keys, return_index=True, return_inverse=True)
    del unique
    vertices = source.vertices[flat_source[first]].copy()
    vertices[:, 6:8] = flat_uv[first]
    indices = np.ascontiguousarray(inverse.astype(np.uint32), dtype=np.uint32)
    geometry = GeometryData(vertices, indices, name, UV_ORIGIN_BOTTOM_LEFT)
    return UVUnwrapResult(
        geometry,
        np.ascontiguousarray(triangle_chart_ids, dtype=np.int32).reshape(-1),
        {},
    )


def _axis_normalised(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    low = values.min(axis=0)
    high = values.max(axis=0)
    span = np.maximum(high - low, 1.0e-8)
    return (values - low) / span


def _planar_projection(source: GeometryData, *, name: str) -> UVUnwrapResult:
    positions = source.vertices[:, :3]
    extent = np.ptp(positions, axis=0)
    drop_axis = int(np.argmin(extent))
    axes = [axis for axis in range(3) if axis != drop_axis]
    uv = _axis_normalised(positions[:, axes])
    triangles = source.indices.reshape(-1, 3)
    return _compact_vertices(
        source,
        uv[triangles],
        np.zeros(source.triangle_count, dtype=np.int32),
        name=name,
    )


def _box_projection(source: GeometryData, *, name: str, padding_fraction: float = 0.02) -> UVUnwrapResult:
    positions = source.vertices[:, :3]
    normalised = _axis_normalised(positions)
    triangles = source.indices.reshape(-1, 3)
    p0, p1, p2 = (positions[triangles[:, i]] for i in range(3))
    face_normals = _normalise(np.cross(p1 - p0, p2 - p0))
    dominant = np.argmax(np.abs(face_normals), axis=1)
    positive = face_normals[np.arange(face_normals.shape[0]), dominant] >= 0.0
    face_ids = dominant * 2 + positive.astype(np.int32)
    # Six deterministic cells in a 3 x 2 atlas.
    cells = ((0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1))
    corner_uvs = np.empty((triangles.shape[0], 3, 2), dtype=np.float32)
    pad = min(max(float(padding_fraction), 0.0), 0.15)
    for tri_index, (triangle, face_id) in enumerate(zip(triangles, face_ids, strict=False)):
        axis = int(face_id // 2)
        sign_positive = bool(face_id % 2)
        if axis == 0:
            local = normalised[triangle][:, (2, 1)]
            if sign_positive:
                local[:, 0] = 1.0 - local[:, 0]
        elif axis == 1:
            local = normalised[triangle][:, (0, 2)]
            if not sign_positive:
                local[:, 0] = 1.0 - local[:, 0]
        else:
            local = normalised[triangle][:, (0, 1)]
            if sign_positive:
                local[:, 0] = 1.0 - local[:, 0]
        local = pad + local * (1.0 - pad * 2.0)
        cell_x, cell_y = cells[int(face_id)]
        corner_uvs[tri_index, :, 0] = (local[:, 0] + cell_x) / 3.0
        corner_uvs[tri_index, :, 1] = (local[:, 1] + cell_y) / 2.0
    return _compact_vertices(source, corner_uvs, face_ids, name=name)


def _unit_axis(value: np.ndarray) -> np.ndarray:
    axis = np.asarray(value, dtype=np.float64).reshape(3)
    length = float(np.linalg.norm(axis))
    if not math.isfinite(length) or length <= 1.0e-10:
        raise ValueError("Cannot construct a UV projection axis from a zero-length vector")
    axis = axis / length
    # Eigenvectors have an arbitrary sign. Canonicalise it so projection output
    # remains deterministic across NumPy/platform implementations.
    major = int(np.argmax(np.abs(axis)))
    if axis[major] < 0.0:
        axis = -axis
    return axis


def _projection_basis(axis: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    axis = _unit_axis(axis)
    reference = np.zeros(3, dtype=np.float64)
    reference[int(np.argmin(np.abs(axis)))] = 1.0
    radial_u = np.cross(axis, reference)
    radial_u = radial_u / max(float(np.linalg.norm(radial_u)), 1.0e-10)
    radial_v = np.cross(axis, radial_u)
    radial_v = radial_v / max(float(np.linalg.norm(radial_v)), 1.0e-10)
    return radial_u, radial_v


def _candidate_cylinder_axes(positions: np.ndarray, face_normals: np.ndarray, face_areas: np.ndarray) -> list[np.ndarray]:
    candidates: list[np.ndarray] = [
        np.asarray((1.0, 0.0, 0.0), dtype=np.float64),
        np.asarray((0.0, 1.0, 0.0), dtype=np.float64),
        np.asarray((0.0, 0.0, 1.0), dtype=np.float64),
    ]
    centred = np.asarray(positions, dtype=np.float64) - np.mean(positions, axis=0, dtype=np.float64)
    try:
        _values, vectors = np.linalg.eigh(centred.T @ centred)
        candidates.extend(vectors[:, index] for index in range(3))
    except np.linalg.LinAlgError:
        pass
    try:
        weights = np.asarray(face_areas, dtype=np.float64).reshape(-1, 1)
        normal_covariance = (np.asarray(face_normals, dtype=np.float64) * weights).T @ np.asarray(face_normals, dtype=np.float64)
        _values, vectors = np.linalg.eigh(normal_covariance)
        candidates.extend(vectors[:, index] for index in range(3))
    except np.linalg.LinAlgError:
        pass

    unique: list[np.ndarray] = []
    for candidate in candidates:
        try:
            axis = _unit_axis(candidate)
        except ValueError:
            continue
        if any(abs(float(np.dot(axis, previous))) > 0.9995 for previous in unique):
            continue
        unique.append(axis)
    return unique


def _infer_cylinder_axis(positions: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """Infer a cylinder/frustum axis without relying on world orientation.

    A good cylinder axis makes most face normals either nearly perpendicular
    (the wall) or nearly parallel (the caps), and gives wall-face centres a
    roughly constant radial distance.  Evaluating covariance-derived axes as
    well as world axes keeps this stable for rotated imported geometry.
    """

    positions64 = np.asarray(positions, dtype=np.float64)
    p0, p1, p2 = (positions64[triangles[:, index]] for index in range(3))
    crosses = np.cross(p1 - p0, p2 - p0)
    double_areas = np.linalg.norm(crosses, axis=1)
    valid = double_areas > 1.0e-12
    if not np.any(valid):
        extent = np.ptp(positions64, axis=0)
        return np.eye(3, dtype=np.float64)[int(np.argmax(extent))]
    face_normals = np.zeros_like(crosses)
    face_normals[valid] = crosses[valid] / double_areas[valid, None]
    face_areas = np.maximum(double_areas * 0.5, 1.0e-12)
    centres = (p0 + p1 + p2) / 3.0
    centre = np.mean(positions64, axis=0, dtype=np.float64)
    total_weight = max(float(np.sum(face_areas)), 1.0e-12)

    best_axis: np.ndarray | None = None
    best_score = float("inf")
    for axis in _candidate_cylinder_axes(positions64, face_normals, face_areas):
        alignment = np.abs(face_normals @ axis)
        # Ideal wall/cap normals sit at the two ends of this range. Penalise
        # diagonal faces rather than requiring caps, so open cylinders work.
        bimodal = float(np.sum(face_areas * (alignment * (1.0 - alignment)) ** 2) / total_weight)
        side = alignment < 0.55
        if np.count_nonzero(side) >= 3:
            relative = centres[side] - centre
            axial = (relative @ axis)[:, None] * axis[None, :]
            radii = np.linalg.norm(relative - axial, axis=1)
            weights = face_areas[side]
            weight_sum = max(float(np.sum(weights)), 1.0e-12)
            mean_radius = float(np.sum(weights * radii) / weight_sum)
            radial_variance = float(np.sum(weights * (radii - mean_radius) ** 2) / weight_sum)
            radial_cv = math.sqrt(max(radial_variance, 0.0)) / max(mean_radius, 1.0e-8)
        else:
            radial_cv = 1.0
        side_fraction = float(np.sum(face_areas[alignment < 0.45]) / total_weight)
        side_penalty = max(0.0, 0.25 - side_fraction)
        score = bimodal + radial_cv * 0.12 + side_penalty * 0.2
        if score < best_score:
            best_score = score
            best_axis = axis
    if best_axis is None:
        extent = np.ptp(positions64, axis=0)
        best_axis = np.eye(3, dtype=np.float64)[int(np.argmax(extent))]
    return _unit_axis(best_axis)


def _preferred_angular_seam(
    angles: np.ndarray,
    positions: np.ndarray,
    source_uvs: np.ndarray,
    radial_distance: np.ndarray,
) -> float:
    """Choose a seam already present in the source when possible.

    Generated/imported meshes often duplicate a geometric vertex at U=0/1.
    Reusing that split avoids cutting through a wall face. Otherwise use one
    endpoint of the largest angular gap so the new cut introduces the least
    distortion possible for a deterministic projection fallback.
    """

    rounded = np.round(np.asarray(positions, dtype=np.float64), 7)
    try:
        _unique, inverse, counts = np.unique(rounded, axis=0, return_inverse=True, return_counts=True)
        candidates: list[float] = []
        for group in np.flatnonzero(counts > 1):
            members = np.flatnonzero(inverse == group)
            if members.size < 2 or float(np.max(radial_distance[members])) <= 1.0e-8:
                continue
            group_uv = np.asarray(source_uvs[members, 0], dtype=np.float64)
            if np.all(np.isfinite(group_uv)) and float(np.ptp(group_uv)) > 0.5:
                candidates.extend(float(angles[index]) for index in members)
        if candidates:
            return float(math.atan2(np.mean(np.sin(candidates)), np.mean(np.cos(candidates))))
    except (ValueError, MemoryError):
        pass

    wrapped = np.mod(np.asarray(angles, dtype=np.float64), math.tau)
    unique = np.unique(np.round(wrapped, 10))
    if unique.size <= 1:
        return float(unique[0]) if unique.size else 0.0
    ordered = np.sort(unique)
    gaps = np.diff(np.concatenate((ordered, ordered[:1] + math.tau)))
    gap_index = int(np.argmax(gaps))
    # Put the seam on an existing angular vertex line, not through the middle
    # of a face. UV corner duplication then handles the wrap cleanly.
    return float(ordered[(gap_index + 1) % ordered.size])


def _split_wrapped_u(base_u: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    corner_u = np.asarray(base_u[triangles], dtype=np.float64).copy()
    wrapping = np.ptp(corner_u, axis=1) > 0.5
    if np.any(wrapping):
        wrapped_values = corner_u[wrapping]
        low = wrapped_values < 0.5
        wrapped_values[low] += 1.0
        # The seam is selected on an existing vertex line. Values just above
        # one therefore represent that same line on the right edge of the UV
        # square and can be clamped without folding a triangle across the map.
        corner_u[wrapping] = np.minimum(wrapped_values, 1.0)
    return np.asarray(corner_u, dtype=np.float32)


def _cylindrical_projection(source: GeometryData, *, name: str, padding_fraction: float = 0.02) -> UVUnwrapResult:
    positions = np.asarray(source.vertices[:, :3], dtype=np.float64)
    triangles = source.indices.reshape(-1, 3)
    axis = _infer_cylinder_axis(positions, triangles)
    radial_u, radial_v = _projection_basis(axis)
    centre = (positions.min(axis=0) + positions.max(axis=0)) * 0.5
    relative = positions - centre
    axial_values = relative @ axis
    radial_coordinates = np.stack((relative @ radial_u, relative @ radial_v), axis=1)
    radial_distance = np.linalg.norm(radial_coordinates, axis=1)
    angles = np.arctan2(radial_coordinates[:, 1], radial_coordinates[:, 0])
    seam = _preferred_angular_seam(
        angles,
        positions,
        np.asarray(source.vertices[:, 6:8], dtype=np.float32),
        radial_distance,
    )
    base_u = np.mod(angles - seam, math.tau) / math.tau
    base_u[np.isclose(base_u, 1.0, atol=1.0e-7)] = 0.0
    corner_u = _split_wrapped_u(base_u, triangles)
    axial_min = float(np.min(axial_values))
    axial_span = max(float(np.max(axial_values)) - axial_min, 1.0e-8)
    v = np.asarray((axial_values - axial_min) / axial_span, dtype=np.float32)

    p0, p1, p2 = (positions[triangles[:, index]] for index in range(3))
    face_normals = _normalise(np.cross(p1 - p0, p2 - p0))
    axial_alignment = np.asarray(face_normals, dtype=np.float64) @ axis
    cap = np.abs(axial_alignment) > 0.72
    top = axial_alignment >= 0.0
    chart_ids = np.where(cap, np.where(top, 1, 2), 0).astype(np.int32)
    corner_uvs = np.empty((triangles.shape[0], 3, 2), dtype=np.float32)
    pad = min(max(float(padding_fraction), 0.0), 0.15)
    radial_scale = max(float(np.max(radial_distance)), 1.0e-8)
    radial_norm = np.asarray(radial_coordinates / (radial_scale * 2.0) + 0.5, dtype=np.float32)
    for tri_index, triangle in enumerate(triangles):
        chart = int(chart_ids[tri_index])
        if chart == 0:
            local = np.stack((corner_u[tri_index], v[triangle]), axis=1)
            local = pad + local * (1.0 - pad * 2.0)
            corner_uvs[tri_index, :, 0] = local[:, 0]
            corner_uvs[tri_index, :, 1] = 0.36 + local[:, 1] * 0.64
        else:
            local = radial_norm[triangle].copy()
            local = pad + local * (1.0 - pad * 2.0)
            x_offset = 0.0 if chart == 1 else 0.5
            corner_uvs[tri_index, :, 0] = x_offset + local[:, 0] * 0.5
            corner_uvs[tri_index, :, 1] = local[:, 1] * 0.34
    return _compact_vertices(source, corner_uvs, chart_ids, name=name)


def _spherical_projection(source: GeometryData, *, name: str) -> UVUnwrapResult:
    positions = np.asarray(source.vertices[:, :3], dtype=np.float64)
    centre = (positions.min(axis=0) + positions.max(axis=0)) * 0.5
    direction = _normalise(positions - centre)
    angles = np.arctan2(direction[:, 2], direction[:, 0])
    radial_distance = np.linalg.norm(direction[:, (0, 2)], axis=1)
    seam = _preferred_angular_seam(
        angles,
        positions,
        np.asarray(source.vertices[:, 6:8], dtype=np.float32),
        radial_distance,
    )
    base_u = np.mod(angles - seam, math.tau) / math.tau
    base_u[np.isclose(base_u, 1.0, atol=1.0e-7)] = 0.0
    v = np.arccos(np.clip(direction[:, 1], -1.0, 1.0)) / math.pi
    triangles = source.indices.reshape(-1, 3)
    corner_u = _split_wrapped_u(base_u, triangles)
    corner_uvs = np.stack((corner_u, v[triangles]), axis=2)
    return _compact_vertices(
        source,
        corner_uvs,
        np.zeros(source.triangle_count, dtype=np.int32),
        name=name,
    )

def _automatic_xatlas(
    source: GeometryData,
    parameters: Mapping[str, Any],
    context: GeometryEvalContext | None,
    *,
    name: str,
) -> UVUnwrapResult:
    try:
        import xatlas  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Automatic Charts requires the native xatlas package. Run setup.sh or setup.bat from 0.52.1; Linux setup automatically uses a wheel-compatible Python 3.13 runtime when the system Python is newer."
        ) from exc

    if context is not None:
        context.progress(4, 100, "Preparing mesh for xatlas")
    positions = np.ascontiguousarray(source.vertices[:, :3], dtype=np.float32)
    normals = np.ascontiguousarray(source.vertices[:, 3:6], dtype=np.float32)
    faces = np.ascontiguousarray(source.indices.reshape(-1, 3), dtype=np.uint32)

    preserve = bool(parameters.get("preserve_existing_seams", True))
    if not preserve:
        unique_positions, inverse = np.unique(np.round(positions, 7), axis=0, return_inverse=True)
        faces = np.ascontiguousarray(inverse[faces], dtype=np.uint32)
        grouped_normals = np.zeros((unique_positions.shape[0], 3), dtype=np.float32)
        np.add.at(grouped_normals, inverse, normals)
        positions = np.ascontiguousarray(unique_positions, dtype=np.float32)
        normals = _normalise(grouped_normals)

    atlas = xatlas.Atlas()
    source_vertices_standard = convert_uv_origin(
        source.vertices, source.uv_origin, UV_ORIGIN_BOTTOM_LEFT
    )
    source_uvs = np.ascontiguousarray(source_vertices_standard[:, 6:8], dtype=np.float32)
    usable_input_uvs = bool(
        preserve
        and source_uvs.size
        and np.all(np.isfinite(source_uvs))
        and np.any(np.ptp(source_uvs, axis=0) > 1.0e-7)
    )
    try:
        if usable_input_uvs:
            atlas.add_mesh(positions, faces, normals, source_uvs)
        else:
            atlas.add_mesh(positions, faces, normals)
    except TypeError:
        atlas.add_mesh(positions, faces)
        usable_input_uvs = False

    chart_options = xatlas.ChartOptions()
    angle = min(max(float(parameters.get("chart_angle", 66.0)), 1.0), 180.0)
    # xatlas exposes weights rather than a direct angle threshold. Map the
    # artist-facing angle to a stable seam preference while retaining its robust
    # default chart-growth heuristic.
    chart_options.normal_deviation_weight = float(0.01 + (180.0 - angle) / 179.0 * 4.0)
    chart_options.normal_seam_weight = 4.0
    chart_options.texture_seam_weight = 0.5 if preserve else 0.0
    chart_options.use_input_mesh_uvs = usable_input_uvs
    chart_options.max_iterations = int(min(max(int(parameters.get("chart_iterations", 2)), 1), 8))
    chart_options.fix_winding = True

    pack_options = xatlas.PackOptions()
    resolution = int(parameters.get("pack_resolution", 2048))
    pack_options.resolution = min(max(resolution, 64), 16384)
    pack_options.padding = min(max(int(parameters.get("island_padding", 8)), 0), 256)
    pack_options.bilinear = True
    pack_options.blockAlign = False
    pack_options.bruteForce = bool(parameters.get("quality_pack", False))
    pack_options.rotate_charts = bool(parameters.get("rotate_islands", True))
    pack_options.rotate_charts_to_axis = bool(parameters.get("rotate_islands", True))

    if context is not None:
        context.progress(12, 100, "Generating UV charts and packing atlas")
        context.checkpoint()
    atlas.generate(chart_options=chart_options, pack_options=pack_options)
    if context is not None:
        context.checkpoint()
        context.progress(84, 100, "Reconstructing UV seams")

    vmapping, output_faces, uvs = atlas[0]
    vmapping = np.ascontiguousarray(vmapping, dtype=np.uint32).reshape(-1)
    output_faces = np.ascontiguousarray(output_faces, dtype=np.uint32).reshape(-1, 3)
    uvs = np.ascontiguousarray(uvs, dtype=np.float32).reshape(-1, 2)

    vertex_atlases = np.zeros(vmapping.size, dtype=np.int32)
    vertex_charts = np.zeros(vmapping.size, dtype=np.int32)
    try:
        assignment = getattr(atlas, "get_mesh_vertex_assignment", None)
        if assignment is None:
            assignment = getattr(atlas, "get_mesh_vertex_assignement")
        assigned_atlases, assigned_charts = assignment(0)
        vertex_atlases = np.asarray(assigned_atlases, dtype=np.int32).reshape(-1)
        vertex_charts = np.asarray(assigned_charts, dtype=np.int32).reshape(-1)
        if vertex_atlases.size != vmapping.size or vertex_charts.size != vmapping.size:
            raise ValueError("xatlas vertex assignment size does not match its output mesh")
    except Exception:
        vertex_atlases = np.zeros(vmapping.size, dtype=np.int32)
        vertex_charts = np.zeros(vmapping.size, dtype=np.int32)

    page_count = max(
        int(getattr(atlas, "atlas_count", 1) or 1),
        int(vertex_atlases.max()) + 1 if vertex_atlases.size else 1,
    )
    page_columns = max(int(math.ceil(math.sqrt(page_count))), 1)
    page_rows = max(int(math.ceil(page_count / page_columns)), 1)
    if page_count > 1:
        # xatlas may emit several atlas pages for a very dense or tightly
        # constrained pack. VFX Texture Lab exposes one conventional UV set, so
        # arrange those pages in a deterministic near-square super-atlas rather
        # than allowing their 0..1 coordinates to overlap.
        page_x = vertex_atlases % page_columns
        page_y = vertex_atlases // page_columns
        uvs[:, 0] = (uvs[:, 0] + page_x.astype(np.float32)) / float(page_columns)
        uvs[:, 1] = (uvs[:, 1] + page_y.astype(np.float32)) / float(page_rows)

    if preserve:
        vertices = source.vertices[vmapping].copy()
    else:
        vertices = np.zeros((vmapping.size, 8), dtype=np.float32)
        vertices[:, :3] = positions[vmapping]
        vertices[:, 3:6] = normals[vmapping]
    vertices[:, 6:8] = uvs
    geometry = GeometryData(vertices, output_faces.reshape(-1), name, UV_ORIGIN_BOTTOM_LEFT)

    chart_stride = int(vertex_charts.max()) + 1 if vertex_charts.size else 1
    combined_vertex_charts = vertex_charts + vertex_atlases * max(chart_stride, 1)
    chart_ids = combined_vertex_charts[output_faces[:, 0]]

    base_width = int(getattr(atlas, "width", pack_options.resolution) or pack_options.resolution)
    base_height = int(getattr(atlas, "height", pack_options.resolution) or pack_options.resolution)
    utilizations: list[float] = []
    for page in range(page_count):
        try:
            utilizations.append(float(atlas.get_utilization(page)))
        except Exception:
            if page == 0:
                utilizations.append(float(getattr(atlas, "utilization", 0.0) or 0.0))
    utilization = float(sum(utilizations) / len(utilizations)) if utilizations else 0.0
    if page_count > 1:
        # Diagnostics describe the conventional single UV set exposed by this
        # node, not each xatlas page in isolation. Account for any deliberately
        # empty cell in the near-square super-atlas (for example page 4 of a
        # three-page 2 x 2 layout) so reported coverage is never overstated.
        utilization *= float(page_count) / float(page_columns * page_rows)

    return UVUnwrapResult(
        geometry,
        np.ascontiguousarray(chart_ids, dtype=np.int32),
        {
            "backend": "Native xatlas",
            "atlas_width": base_width * page_columns,
            "atlas_height": base_height * page_rows,
            "atlas_page_count": page_count,
            "utilization": utilization,
        },
    )


def _triangle_area_2d(triangles: np.ndarray) -> np.ndarray:
    a = triangles[:, 1] - triangles[:, 0]
    b = triangles[:, 2] - triangles[:, 0]
    return np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) * 0.5


def _polygon_clip(subject: list[np.ndarray], clip: np.ndarray) -> list[np.ndarray]:
    def inside(point: np.ndarray, a: np.ndarray, b: np.ndarray, orientation: float) -> bool:
        cross = (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])
        return cross * orientation >= -1.0e-10

    def intersection(s: np.ndarray, e: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        ds = e - s
        dc = b - a
        denom = ds[0] * dc[1] - ds[1] * dc[0]
        if abs(float(denom)) < 1.0e-12:
            return e
        t = ((a[0] - s[0]) * dc[1] - (a[1] - s[1]) * dc[0]) / denom
        return s + ds * t

    output = subject
    edge_a = clip[1] - clip[0]
    edge_b = clip[2] - clip[0]
    orientation = 1.0 if edge_a[0] * edge_b[1] - edge_a[1] * edge_b[0] >= 0.0 else -1.0
    for index in range(3):
        input_list = output
        output = []
        if not input_list:
            break
        a = clip[index]
        b = clip[(index + 1) % 3]
        s = input_list[-1]
        for e in input_list:
            e_inside = inside(e, a, b, orientation)
            s_inside = inside(s, a, b, orientation)
            if e_inside:
                if not s_inside:
                    output.append(intersection(s, e, a, b))
                output.append(e)
            elif s_inside:
                output.append(intersection(s, e, a, b))
            s = e
    return output


def _polygon_area(points: list[np.ndarray]) -> float:
    if len(points) < 3:
        return 0.0
    array = np.asarray(points, dtype=np.float64)
    return abs(float(np.dot(array[:, 0], np.roll(array[:, 1], -1)) - np.dot(array[:, 1], np.roll(array[:, 0], -1)))) * 0.5


def overlapping_triangles(geometry: GeometryData, *, max_pair_tests: int = 250_000) -> np.ndarray:
    triangles = geometry.vertices[geometry.indices.reshape(-1, 3), 6:8].astype(np.float64, copy=False)
    count = triangles.shape[0]
    if count <= 1:
        return np.zeros(count, dtype=bool)
    mins = triangles.min(axis=1)
    maxs = triangles.max(axis=1)
    grid_size = 64
    buckets: dict[tuple[int, int], list[int]] = {}
    for index in range(count):
        low = np.floor(np.clip(mins[index], 0.0, 1.0) * grid_size).astype(int)
        high = np.floor(np.clip(maxs[index], 0.0, 1.0) * grid_size).astype(int)
        low = np.clip(low, 0, grid_size - 1)
        high = np.clip(high, 0, grid_size - 1)
        for y in range(int(low[1]), int(high[1]) + 1):
            for x in range(int(low[0]), int(high[0]) + 1):
                buckets.setdefault((x, y), []).append(index)
    overlap = np.zeros(count, dtype=bool)
    tested: set[tuple[int, int]] = set()
    tests = 0
    source_triangles = geometry.indices.reshape(-1, 3)
    for bucket in buckets.values():
        if len(bucket) < 2:
            continue
        for i_pos in range(len(bucket) - 1):
            a_index = bucket[i_pos]
            for b_index in bucket[i_pos + 1:]:
                pair = (a_index, b_index) if a_index < b_index else (b_index, a_index)
                if pair in tested:
                    continue
                tested.add(pair)
                tests += 1
                if tests > max_pair_tests:
                    return overlap
                # Adjacent mesh triangles are allowed to meet at a UV edge or vertex.
                if np.intersect1d(source_triangles[a_index], source_triangles[b_index]).size >= 2:
                    continue
                if np.any(maxs[a_index] < mins[b_index]) or np.any(maxs[b_index] < mins[a_index]):
                    continue
                polygon = _polygon_clip([p.copy() for p in triangles[a_index]], triangles[b_index])
                if _polygon_area(polygon) > 1.0e-9:
                    overlap[a_index] = True
                    overlap[b_index] = True
    return overlap


def diagnose_uv(result: UVUnwrapResult, *, context: GeometryEvalContext | None = None) -> dict[str, Any]:
    geometry = result.geometry
    if context is not None:
        context.progress(88, 100, "Analysing UV layout")
    triangles = geometry.vertices[geometry.indices.reshape(-1, 3), 6:8]
    areas = _triangle_area_2d(triangles)
    out_of_bounds = np.any((geometry.vertices[:, 6:8] < -1.0e-6) | (geometry.vertices[:, 6:8] > 1.0 + 1.0e-6), axis=1)
    analysis_limited = geometry.triangle_count > UV_OVERLAP_ANALYSIS_TRIANGLE_LIMIT
    overlaps = (
        np.zeros(geometry.triangle_count, dtype=bool)
        if analysis_limited
        else overlapping_triangles(geometry)
    )
    # Rasterized union area gives a stable, artist-friendly atlas coverage
    # estimate. Native xatlas reports its own utilization; for extremely dense
    # existing UV sets sample deterministically so inspection never becomes a
    # million-iteration Python task.
    native_utilization = float(result.diagnostics.get("utilization", 0.0) or 0.0)
    coverage_estimated = False
    if native_utilization > 0.0:
        coverage = min(max(native_utilization, 0.0), 1.0)
    else:
        resolution = 256
        mask = Image.new("L", (resolution, resolution), 0)
        draw = ImageDraw.Draw(mask)
        if triangles.shape[0] > UV_OVERLAP_ANALYSIS_TRIANGLE_LIMIT:
            sample_indices = np.linspace(
                0, triangles.shape[0] - 1, UV_OVERLAP_ANALYSIS_TRIANGLE_LIMIT, dtype=np.int64
            )
            coverage_triangles = triangles[np.unique(sample_indices)]
            coverage_estimated = True
        else:
            coverage_triangles = triangles
        for tri in coverage_triangles:
            points = [(float(p[0]) * (resolution - 1), (1.0 - float(p[1])) * (resolution - 1)) for p in tri]
            draw.polygon(points, fill=255)
        coverage = float(np.count_nonzero(np.asarray(mask))) / float(resolution * resolution)
    island_count = int(np.unique(result.chart_ids).size) if result.chart_ids.size else 0
    diagnostics = dict(result.diagnostics)
    diagnostics.update({
        "island_count": island_count,
        "coverage": coverage,
        "overlap_triangle_count": int(np.count_nonzero(overlaps)),
        "zero_area_triangle_count": int(np.count_nonzero(areas <= 1.0e-10)),
        "out_of_bounds_vertex_count": int(np.count_nonzero(out_of_bounds)),
        "overlap_analysis_limited": bool(analysis_limited),
        "coverage_estimated": bool(coverage_estimated),
        "preview_sampled": bool(geometry.triangle_count > UV_PREVIEW_TRIANGLE_LIMIT),
        "preview_triangle_count": int(min(geometry.triangle_count, UV_PREVIEW_TRIANGLE_LIMIT)),
        "overlap_mask": overlaps,
    })
    return diagnostics


def unwrap_geometry(
    source: GeometryData,
    parameters: Mapping[str, Any],
    context: GeometryEvalContext | None = None,
) -> UVUnwrapResult:
    if not isinstance(source, GeometryData):
        raise TypeError("Geometry UV Unwrap requires a connected Geometry input")
    if source.triangle_count < 1:
        raise ValueError("Geometry UV Unwrap requires at least one triangle")
    mode = str(parameters.get("mode", "Automatic Charts"))
    name = str(parameters.get("name", "UV Unwrapped Geometry") or "UV Unwrapped Geometry")
    padding = float(parameters.get("island_padding", 8)) / max(float(parameters.get("pack_resolution", 2048)), 64.0)
    if mode == "Automatic Charts":
        result = _automatic_xatlas(source, parameters, context, name=name)
    elif mode == "Box Projection":
        result = _box_projection(source, name=name, padding_fraction=padding)
        result.diagnostics["backend"] = "Box projection"
    elif mode == "Planar Projection":
        result = _planar_projection(source, name=name)
        result.diagnostics["backend"] = "Planar projection"
    elif mode == "Cylindrical Projection":
        result = _cylindrical_projection(source, name=name, padding_fraction=padding)
        result.diagnostics["backend"] = "Cylindrical projection"
    elif mode == "Spherical Projection":
        result = _spherical_projection(source, name=name)
        result.diagnostics["backend"] = "Spherical projection"
    else:
        raise ValueError(f"Unknown UV unwrap mode: {mode}")
    result.diagnostics = diagnose_uv(result, context=context)
    if context is not None:
        context.progress(100, 100, "UV unwrap complete")
    return result


def _to_rgba8(image: np.ndarray, width: int, height: int) -> np.ndarray:
    values = np.asarray(image)
    if values.ndim == 2:
        values = values[..., None]
    if values.ndim != 3:
        raise ValueError("Preview texture has an unsupported shape")
    if values.shape[2] == 1:
        values = np.repeat(values, 3, axis=2)
    if values.shape[2] == 2:
        values = np.concatenate((values, np.zeros_like(values[..., :1])), axis=2)
    if values.shape[2] == 3:
        values = np.concatenate((values, np.ones_like(values[..., :1])), axis=2)
    rgba = values[..., :4].astype(np.float32, copy=False)
    if np.issubdtype(values.dtype, np.integer):
        rgba = rgba / float(np.iinfo(values.dtype).max)
    rgba = np.clip(rgba, 0.0, 1.0).copy()
    rgb = rgba[..., :3]
    rgba[..., :3] = np.where(
        rgb <= 0.0031308,
        rgb * 12.92,
        1.055 * np.power(rgb, 1.0 / 2.4) - 0.055,
    )
    rgba8 = (rgba * 255.0 + 0.5).astype(np.uint8)
    pil = Image.fromarray(rgba8, "RGBA").resize((width, height), Image.Resampling.BILINEAR)
    return np.asarray(pil).copy()


_UV_CHECKER_TEXTURE: np.ndarray | None = None


def uv_checker_texture() -> np.ndarray:
    """Return a shared neutral checker used for textureless 3D UV inspection.

    The 2D UV view already falls back to a checkerboard when no Preview
    Texture is connected.  Publishing a small linear-colour texture here gives
    the 3D mesh the same useful distortion reference without changing the
    authored geometry or making the unwrap result stale.
    """

    global _UV_CHECKER_TEXTURE
    if _UV_CHECKER_TEXTURE is None:
        size = 128
        cells = 16
        cell = max(size // cells, 1)
        yy, xx = np.indices((size, size), dtype=np.int32)
        mask = ((xx // cell) + (yy // cell)) % 2 == 0
        checker = np.empty((size, size, 4), dtype=np.float32)
        checker[..., :3] = np.where(mask[..., None], 0.32, 0.12)
        checker[..., 3] = 1.0
        checker = np.ascontiguousarray(checker)
        checker.setflags(write=False)
        _UV_CHECKER_TEXTURE = checker
    return _UV_CHECKER_TEXTURE


def existing_uv_result(geometry: GeometryData, *, backend: str = "Existing UVs") -> UVUnwrapResult:
    """Build preview/diagnostic data for geometry whose UVs already exist."""

    result = UVUnwrapResult(
        geometry,
        np.zeros(geometry.triangle_count, dtype=np.int32),
        {"backend": str(backend)},
    )
    result.diagnostics = diagnose_uv(result)
    return result


def render_uv_preview(
    result: UVUnwrapResult,
    preview_texture: np.ndarray | None,
    *,
    width: int = 1024,
    height: int = 1024,
    options: Mapping[str, Any] | None = None,
) -> np.ndarray:
    options = dict(options or {})
    width = min(max(int(width), 128), 4096)
    height = min(max(int(height), 128), 4096)
    checker = bool(options.get("checker", True))
    show_wireframe = bool(options.get("wireframe", True))
    show_islands = bool(options.get("islands", True))
    show_overlaps = bool(options.get("overlaps", True))
    show_seams = bool(options.get("seams", True))

    if preview_texture is not None:
        rgba = _to_rgba8(preview_texture, width, height)
        canvas = Image.fromarray(rgba, "RGBA")
    else:
        canvas = Image.new("RGBA", (width, height), (25, 27, 31, 255))
        if checker:
            draw = ImageDraw.Draw(canvas)
            cell = max(min(width, height) // 16, 8)
            for y in range(0, height, cell):
                for x in range(0, width, cell):
                    value = 46 if ((x // cell) + (y // cell)) % 2 == 0 else 62
                    draw.rectangle((x, y, x + cell, y + cell), fill=(value, value, value, 255))

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    triangles = result.geometry.indices.reshape(-1, 3)
    preview_vertices = convert_uv_origin(
        result.geometry.vertices, result.geometry.uv_origin, UV_ORIGIN_BOTTOM_LEFT
    )
    uvs = preview_vertices[:, 6:8]
    overlaps = np.asarray(result.diagnostics.get("overlap_mask", np.zeros(triangles.shape[0], dtype=bool)), dtype=bool)
    palette = (
        (67, 166, 214, 55), (218, 132, 75, 55), (113, 194, 118, 55),
        (177, 117, 210, 55), (229, 193, 83, 55), (88, 190, 176, 55),
    )
    preview_sampled = triangles.shape[0] > UV_PREVIEW_TRIANGLE_LIMIT
    if preview_sampled:
        draw_indices = np.unique(np.linspace(
            0, triangles.shape[0] - 1, UV_PREVIEW_TRIANGLE_LIMIT, dtype=np.int64
        ))
        # Boundary detection on a sparse triangle sample would incorrectly
        # classify omitted neighbours as seams, so dense previews keep wires and
        # island/overlap fills but omit the misleading seam pass.
        show_seams = False
    else:
        draw_indices = np.arange(triangles.shape[0], dtype=np.int64)
    result.diagnostics["preview_sampled"] = bool(preview_sampled)
    result.diagnostics["preview_triangle_count"] = int(draw_indices.size)

    edge_counts: dict[tuple[int, int], int] = {}
    for tri_index in draw_indices:
        triangle = triangles[int(tri_index)]
        points = [
            (float(uvs[int(vertex), 0]) * (width - 1), (1.0 - float(uvs[int(vertex), 1])) * (height - 1))
            for vertex in triangle
        ]
        chart = int(result.chart_ids[tri_index]) if tri_index < result.chart_ids.size else 0
        if show_islands:
            draw.polygon(points, fill=palette[chart % len(palette)])
        if show_overlaps and tri_index < overlaps.size and bool(overlaps[tri_index]):
            draw.polygon(points, fill=(245, 63, 75, 120))
        if show_wireframe:
            draw.line(points + [points[0]], fill=(238, 240, 244, 205), width=1)
        if show_seams:
            for a, b in ((0, 1), (1, 2), (2, 0)):
                edge = tuple(sorted((int(triangle[a]), int(triangle[b]))))
                edge_counts[edge] = edge_counts.get(edge, 0) + 1
    if show_seams:
        for tri_index in draw_indices:
            triangle = triangles[int(tri_index)]
            for a, b in ((0, 1), (1, 2), (2, 0)):
                edge = tuple(sorted((int(triangle[a]), int(triangle[b]))))
                if edge_counts.get(edge, 0) != 1:
                    continue
                pa = (float(uvs[edge[0], 0]) * (width - 1), (1.0 - float(uvs[edge[0], 1])) * (height - 1))
                pb = (float(uvs[edge[1], 0]) * (width - 1), (1.0 - float(uvs[edge[1], 1])) * (height - 1))
                draw.line((pa, pb), fill=(64, 224, 238, 255), width=2)
    # 0..1 atlas border.
    draw.rectangle((0, 0, width - 1, height - 1), outline=(133, 143, 157, 255), width=2)
    return np.asarray(Image.alpha_composite(canvas, overlay), dtype=np.uint8).copy()


UNWRAP_SIGNATURE_PARAMETERS = (
    "mode",
    "chart_angle",
    "chart_iterations",
    "island_padding",
    "pack_resolution",
    "rotate_islands",
    "preserve_existing_seams",
    "quality_pack",
)


def evaluate_manual_uv_unwrap(
    inputs: Mapping[str, Any],
    parameters: Mapping[str, Any],
    context: GeometryEvalContext | None = None,
) -> GeometryData:
    source = inputs.get("Geometry")
    if not isinstance(source, GeometryData):
        raise TypeError("Geometry UV Unwrap requires a connected Geometry input")
    preview_texture = inputs.get("Preview Texture")
    run_serial = int(parameters.get("_manual_run_serial", 0) or 0)
    completed_serial = int(parameters.get("_manual_completed_serial", 0) or 0)
    payload = str(parameters.get("_manual_result_data", "") or "")
    stored_signature = str(parameters.get("_manual_signature", "") or "")
    current_signature = geometry_signature(source, parameters, UNWRAP_SIGNATURE_PARAMETERS)
    previous: UVUnwrapResult | None = None
    if payload:
        previous = decode_result(payload)

    should_execute = run_serial > completed_serial
    if should_execute:
        try:
            if context is not None:
                context.progress(0, 100, "Starting manual UV unwrap")
            result = unwrap_geometry(source, parameters, context)
            encoded = encode_result(result)
            diagnostics = {key: value for key, value in result.diagnostics.items() if key != "overlap_mask"}
            if context is not None:
                context.report_metadata({
                    "_manual_status": "Up to Date",
                    "_manual_completed_serial": run_serial,
                    "_manual_signature": current_signature,
                    "_manual_result_data": encoded,
                    "_manual_result_revision": hashlib.blake2b(
                        encoded.encode("ascii"), digest_size=20
                    ).hexdigest(),
                    "_manual_last_error": "",
                    "_manual_applied_parameters": {
                        name: parameters.get(name) for name in UNWRAP_SIGNATURE_PARAMETERS
                    },
                    "_uv_backend": diagnostics.get("backend", "Unknown"),
                    "_uv_island_count": int(diagnostics.get("island_count", 0)),
                    "_uv_coverage": float(diagnostics.get("coverage", 0.0)),
                    "_uv_overlap_triangle_count": int(diagnostics.get("overlap_triangle_count", 0)),
                    "_uv_zero_area_triangle_count": int(diagnostics.get("zero_area_triangle_count", 0)),
                    "_uv_out_of_bounds_vertex_count": int(diagnostics.get("out_of_bounds_vertex_count", 0)),
                    "_uv_atlas_width": int(diagnostics.get("atlas_width", parameters.get("pack_resolution", 2048))),
                    "_uv_atlas_height": int(diagnostics.get("atlas_height", parameters.get("pack_resolution", 2048))),
                    "_uv_utilization": float(diagnostics.get("utilization", 0.0)),
                    "_uv_atlas_page_count": int(diagnostics.get("atlas_page_count", 1)),
                    "_uv_overlap_analysis_limited": bool(diagnostics.get("overlap_analysis_limited", False)),
                    "_uv_coverage_estimated": bool(diagnostics.get("coverage_estimated", False)),
                    "_uv_preview_sampled": bool(diagnostics.get("preview_sampled", False)),
                    "_uv_preview_triangle_count": int(diagnostics.get("preview_triangle_count", result.geometry.triangle_count)),
                })
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
                    "_manual_last_error": f"{type(exc).__name__}: {exc}",
                    "_manual_completed_serial": run_serial,
                })
    elif previous is not None:
        active = previous
        status = "Up to Date" if stored_signature == current_signature else "Out of Date"
        if context is not None:
            context.report_metadata({
                "_manual_status": status,
                "_manual_last_error": "",
            })
    else:
        active = UVUnwrapResult(
            source.copy(name=str(parameters.get("name", "UV Unwrapped Geometry"))),
            np.zeros(source.triangle_count, dtype=np.int32),
            {"backend": "Not run", "island_count": 0, "coverage": 0.0, "overlap_mask": np.zeros(source.triangle_count, dtype=bool)},
        )
        if context is not None:
            context.report_metadata({
                "_manual_status": "Not Run",
                "_manual_last_error": "",
            })

    if context is not None and not str(getattr(context, "render_mode", "")).startswith("final"):
        if isinstance(preview_texture, np.ndarray):
            # This is presentation-only: the same texture shown beneath the UV
            # atlas is also applied as Base Colour on the unwrapped mesh. It is
            # deliberately excluded from the unwrap signature and persistent
            # geometry payload, so swapping it never requests another unwrap.
            context.preview_material_texture = np.ascontiguousarray(preview_texture)
        else:
            # Match the 2D UV view's useful textureless fallback in 3D.  This is
            # a shared presentation texture only; it is not encoded into the
            # manual result and never participates in the unwrap signature.
            context.preview_material_texture = uv_checker_texture()
        preview_options = dict(getattr(context, "preview_options", {}) or {})
        context.preview_image = render_uv_preview(
            active,
            preview_texture if isinstance(preview_texture, np.ndarray) else None,
            width=max(int(getattr(context, "width", 1024)), 128),
            height=max(int(getattr(context, "height", 1024)), 128),
            options=preview_options,
        )
        diagnostics = active.diagnostics
        context.preview_details = (
            f"UV layout · {int(diagnostics.get('island_count', 0)):,} islands · "
            f"{float(diagnostics.get('coverage', 0.0)) * 100.0}% coverage · "
            f"{int(diagnostics.get('overlap_triangle_count', 0)):,} overlap triangles"
        )
        if diagnostics.get("overlap_analysis_limited"):
            context.preview_details += " · dense overlap analysis limited"
        if diagnostics.get("preview_sampled"):
            context.preview_details += (
                f" · showing {int(diagnostics.get('preview_triangle_count', 0)):,} sampled triangles"
            )
        context.preview_kind = "uv"
    desired_name = str(parameters.get("name", "UV Unwrapped Geometry") or "UV Unwrapped Geometry")
    if active.geometry.name != desired_name:
        # Renaming is cheap presentation metadata, not an unwrap setting. Apply
        # it to the current output without making artists rerun charting merely
        # to update the geometry label.
        return active.geometry.copy(name=desired_name)
    return active.geometry
