"""Procedural geometry graph values and mesh export helpers.

Geometry is deliberately independent from image resolution.  A graph geometry
value owns interleaved position/normal/UV vertices plus indexed triangles, which
matches the existing 3D preview renderer while remaining usable by future mesh
processing nodes and exporters.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import math
import numpy as np


@dataclass(slots=True)
class GeometryData:
    """Indexed triangle geometry with one normal and UV per vertex.

    ``vertices`` is a float32 ``N x 8`` array containing position XYZ, normal
    XYZ and UV XY.  ``indices`` is a flat uint32 triangle index array.
    """

    vertices: np.ndarray
    indices: np.ndarray
    name: str = "Geometry"

    def __post_init__(self) -> None:
        self.vertices = np.ascontiguousarray(self.vertices, dtype=np.float32).reshape(-1, 8)
        self.indices = np.ascontiguousarray(self.indices, dtype=np.uint32).reshape(-1)
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
        return GeometryData(self.vertices.copy(), self.indices.copy(), name or self.name)


def _interleaved_geometry(
    positions: np.ndarray,
    normals: np.ndarray,
    uvs: np.ndarray,
    indices: np.ndarray,
    name: str,
) -> GeometryData:
    vertices = np.concatenate((positions, normals, uvs), axis=1)
    return GeometryData(vertices, indices, name)


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
    vertices = np.concatenate((bottom.vertices, top.vertices), axis=0)
    top_indices = top.indices.astype(np.uint64, copy=False) + bottom.vertex_count
    if top_indices.size and int(top_indices.max()) > np.iinfo(np.uint32).max:
        raise ValueError("Combined geometry exceeds the uint32 index limit")
    indices = np.concatenate((bottom.indices, top_indices.astype(np.uint32)), axis=0)
    return GeometryData(vertices, indices, name)

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
    return GeometryData(vertices, indices, name)


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
            result = GeometryData(vertices, result.indices.copy(), name)
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
    return GeometryData(vertices, indices, name)


def _sample_height_bilinear(heightmap: np.ndarray, uvs: np.ndarray) -> np.ndarray:
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
    y = wrapped[:, 1] * height - 0.5
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
    sampled = _sample_height_bilinear(heightmap, vertices[:, 6:8])
    vertices[:, :3] += unit_normals * (sampled[:, None] * float(amount))
    # Displacement intentionally preserves authored normals. Terrain and VFX
    # meshes commonly receive final shading from a normal map; explicit mesh
    # normal rebuilding belongs to the Geometry Normals node.
    vertices[:, 3:6] = normals
    return GeometryData(vertices, geometry.indices.copy(), name)


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
        for uv in vertices[:, 6:8]:
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
