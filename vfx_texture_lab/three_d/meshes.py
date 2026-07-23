from __future__ import annotations

import base64
import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(slots=True)
class MeshData:
    """Interleaved position/normal/UV mesh data used by the 3D preview."""

    vertices: np.ndarray  # float32, N x 8: position.xyz, normal.xyz, uv.xy
    indices: np.ndarray  # uint32 triangles
    name: str = "Mesh"
    cache_key: str = ""
    uv_origin: str = "top-left"

    def __post_init__(self) -> None:
        self.vertices = np.ascontiguousarray(self.vertices, dtype=np.float32).reshape(-1, 8)
        self.indices = np.ascontiguousarray(self.indices, dtype=np.uint32).reshape(-1)
        value = str(self.uv_origin or "top-left").strip().casefold().replace("_", "-")
        self.uv_origin = "bottom-left" if value in {"bottom-left", "bottomleft", "v-up", "standard", "obj"} else "top-left"
        if self.indices.size % 3:
            raise ValueError("Mesh indices must describe triangles")

    @property
    def vertex_count(self) -> int:
        return int(self.vertices.shape[0])

    @property
    def triangle_count(self) -> int:
        return int(self.indices.size // 3)


def terrain_grid(subdivisions: int = 256, *, name: str = "Terrain Plane") -> MeshData:
    subdivisions = min(max(int(subdivisions), 1), 1024)
    size = subdivisions + 1
    u = np.linspace(0.0, 1.0, size, dtype=np.float32)
    v = np.linspace(0.0, 1.0, size, dtype=np.float32)
    uu, vv = np.meshgrid(u, v)
    positions = np.stack((uu * 2.0 - 1.0, np.zeros_like(uu), 1.0 - vv * 2.0), axis=2)
    normals = np.zeros_like(positions)
    normals[..., 1] = 1.0
    uvs = np.stack((uu, vv), axis=2)
    vertices = np.concatenate((positions, normals, uvs), axis=2).reshape(-1, 8)

    a = np.arange(subdivisions * subdivisions, dtype=np.uint32).reshape(subdivisions, subdivisions)
    row = np.arange(subdivisions, dtype=np.uint32)[:, None] * size
    col = np.arange(subdivisions, dtype=np.uint32)[None, :]
    top_left = row + col
    top_right = top_left + 1
    bottom_left = top_left + size
    bottom_right = bottom_left + 1
    # Counter-clockwise when viewed from +Y.
    indices = np.stack(
        (
            top_left,
            top_right,
            bottom_left,
            top_right,
            bottom_right,
            bottom_left,
        ),
        axis=2,
    ).reshape(-1)
    return MeshData(vertices, indices, name)


def cube_mesh(subdivisions: int = 1) -> MeshData:
    """Create a smooth-shaded, UV-mapped cube with optional face tessellation."""
    subdivisions = min(max(int(subdivisions), 1), 128)
    # Separate vertices per face preserve conventional UVs. Normals are then
    # smoothed from the final positions so the preview defaults to smooth
    # shading instead of hard-edged faceting.
    faces = [
        ((0, 0, 1), [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]),
        ((0, 0, -1), [(1, -1, -1), (-1, -1, -1), (-1, 1, -1), (1, 1, -1)]),
        ((1, 0, 0), [(1, -1, 1), (1, -1, -1), (1, 1, -1), (1, 1, 1)]),
        ((-1, 0, 0), [(-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1)]),
        ((0, 1, 0), [(-1, 1, 1), (1, 1, 1), (1, 1, -1), (-1, 1, -1)]),
        ((0, -1, 0), [(-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)]),
    ]
    vertices: list[list[float]] = []
    indices: list[int] = []
    for normal, points in faces:
        start = len(vertices)
        p0, p1, p2, p3 = (np.asarray(point, dtype=np.float32) for point in points)
        row = subdivisions + 1
        for y in range(row):
            v = y / subdivisions
            left = p0 * (1.0 - v) + p3 * v
            right = p1 * (1.0 - v) + p2 * v
            for x in range(row):
                u = x / subdivisions
                point = (left * (1.0 - u) + right * u) * 0.65
                smooth_normal = point / max(float(np.linalg.norm(point)), 1.0e-8)
                vertices.append([*point, *smooth_normal, u, 1.0 - v])
        for y in range(subdivisions):
            for x in range(subdivisions):
                a = start + y * row + x
                b = a + row
                indices.extend((a, a + 1, b, a + 1, b + 1, b))
    return MeshData(np.asarray(vertices, dtype=np.float32), np.asarray(indices, dtype=np.uint32), "Cube")



def rounded_cube_mesh(subdivisions: int = 24, *, bevel_radius: float = 0.22) -> MeshData:
    """Create a UV-mapped rounded box with flat faces and smoothly bevelled edges."""
    subdivisions = min(max(int(subdivisions), 2), 128)
    radius = min(max(float(bevel_radius), 0.02), 0.48)
    inner = 1.0 - radius
    scale = 0.78
    faces = [
        ([( -1, -1,  1), ( 1, -1,  1), ( 1,  1,  1), (-1,  1,  1)]),
        ([(  1, -1, -1), (-1, -1, -1), (-1,  1, -1), ( 1,  1, -1)]),
        ([(  1, -1,  1), ( 1, -1, -1), ( 1,  1, -1), ( 1,  1,  1)]),
        ([(-1, -1, -1), (-1, -1,  1), (-1,  1,  1), (-1,  1, -1)]),
        ([(-1,  1,  1), ( 1,  1,  1), ( 1,  1, -1), (-1,  1, -1)]),
        ([(-1, -1, -1), ( 1, -1, -1), ( 1, -1,  1), (-1, -1,  1)]),
    ]
    vertices: list[list[float]] = []
    indices: list[int] = []
    row = subdivisions + 1
    for points in faces:
        start = len(vertices)
        p0, p1, p2, p3 = (np.asarray(point, dtype=np.float32) for point in points)
        for y in range(row):
            v = y / subdivisions
            left = p0 * (1.0 - v) + p3 * v
            right = p1 * (1.0 - v) + p2 * v
            for x in range(row):
                u = x / subdivisions
                cube_point = left * (1.0 - u) + right * u
                core = np.clip(cube_point, -inner, inner)
                delta = cube_point - core
                length = max(float(np.linalg.norm(delta)), 1.0e-8)
                normal = delta / length
                point = (core + normal * radius) * scale
                vertices.append([*point, *normal, u, 1.0 - v])
        for y in range(subdivisions):
            for x in range(subdivisions):
                a = start + y * row + x
                b = a + row
                indices.extend((a, a + 1, b, a + 1, b + 1, b))
    return MeshData(np.asarray(vertices, dtype=np.float32), np.asarray(indices, dtype=np.uint32), "Rounded Cube")


def rounded_cylinder_mesh(longitudes: int = 96, bevel_segments: int = 12) -> MeshData:
    """Create an evenly tessellated rounded cylinder with fully curved ends.

    The preview shape is a short cylindrical wall joined to shallow elliptical
    domes.  Unlike the former implementation there are no planar cap discs, so
    height displacement can flow continuously over the complete surface.  The
    profile is resampled by arc length to keep triangles comparatively even.
    """
    longitudes = min(max(int(longitudes), 12), 512)
    cap_segments = min(max(int(bevel_segments), 3), 96)

    outer_radius = 0.72
    wall_half_height = 0.54
    dome_height = 0.28

    def ellipse_point(theta: float, top: bool) -> tuple[float, float, float, float]:
        radius = outer_radius * math.cos(theta)
        y_offset = dome_height * math.sin(theta)
        y = wall_half_height + y_offset if top else -wall_half_height - y_offset
        # Gradient of (r/a)^2 + (y/b)^2 = 1 gives the geometric normal.
        radial = math.cos(theta) / max(outer_radius, 1.0e-8)
        vertical = math.sin(theta) / max(dome_height, 1.0e-8)
        if not top:
            vertical = -vertical
        length = max(math.hypot(radial, vertical), 1.0e-8)
        return radius, y, radial / length, vertical / length

    def resampled_cap(top: bool) -> list[tuple[float, float, float, float]]:
        # Oversample the ellipse, then choose equal arc-length locations.  This
        # avoids dense shoulder rings and sparse pole rings when displaced.
        samples = max(cap_segments * 32, 128)
        raw = [ellipse_point((0.5 * math.pi) * (i / samples), top) for i in range(samples + 1)]
        cumulative = [0.0]
        for previous, current in zip(raw, raw[1:]):
            cumulative.append(cumulative[-1] + math.hypot(current[0] - previous[0], current[1] - previous[1]))
        total = cumulative[-1]
        chosen: list[tuple[float, float, float, float]] = []
        cursor = 0
        # Exclude the pole itself; it is represented by one fan vertex so the
        # UV seam does not create a row of coincident displaced vertices.
        for segment in range(cap_segments):
            target = total * (segment / cap_segments)
            while cursor + 1 < len(cumulative) and cumulative[cursor + 1] < target:
                cursor += 1
            if cursor + 1 >= len(raw):
                chosen.append(raw[-2])
                continue
            span = max(cumulative[cursor + 1] - cumulative[cursor], 1.0e-8)
            amount = (target - cumulative[cursor]) / span
            a = raw[cursor]
            b = raw[cursor + 1]
            value = tuple(a[index] * (1.0 - amount) + b[index] * amount for index in range(4))
            normal_length = max(math.hypot(value[2], value[3]), 1.0e-8)
            chosen.append((value[0], value[1], value[2] / normal_length, value[3] / normal_length))
        return chosen

    lower_cap = list(reversed(resampled_cap(False)))
    upper_cap = resampled_cap(True)

    # Match wall-ring spacing to the cap edge length so displacement sees a
    # broadly uniform tessellation over the complete mesh.
    cap_arc = 0.0
    cap_probe = [ellipse_point((0.5 * math.pi) * (i / 256), True) for i in range(257)]
    for previous, current in zip(cap_probe, cap_probe[1:]):
        cap_arc += math.hypot(current[0] - previous[0], current[1] - previous[1])
    target_step = cap_arc / cap_segments
    wall_segments = max(int(round((2.0 * wall_half_height) / max(target_step, 1.0e-8))), 2)
    wall: list[tuple[float, float, float, float]] = []
    for index in range(1, wall_segments):
        amount = index / wall_segments
        y = -wall_half_height + amount * (2.0 * wall_half_height)
        wall.append((outer_radius, y, 1.0, 0.0))

    profile = lower_cap + wall + upper_cap
    # Distance along the meridian supplies an even V coordinate.  U deliberately
    # spans two repeats around the circumference to correct the old horizontal
    # stretching while preserving seamless wrapping.
    profile_distances = [dome_height]
    bottom_pole = (0.0, -(wall_half_height + dome_height))
    previous_radius, previous_y = bottom_pole
    for radius, y, _radial_normal, _vertical_normal in profile:
        profile_distances.append(profile_distances[-1] + math.hypot(radius - previous_radius, y - previous_y))
        previous_radius, previous_y = radius, y
    top_pole = (0.0, wall_half_height + dome_height)
    total_meridian = profile_distances[-1] + math.hypot(top_pole[0] - previous_radius, top_pole[1] - previous_y)

    vertices: list[list[float]] = []
    indices: list[int] = []
    row = longitudes + 1
    ring_starts: list[int] = []
    for ring_index, (radius, y, radial_normal, vertical_normal) in enumerate(profile):
        ring_starts.append(len(vertices))
        v = profile_distances[ring_index + 1] / max(total_meridian, 1.0e-8)
        for x in range(row):
            fraction = x / longitudes
            angle = fraction * math.tau
            sin_angle = math.sin(angle)
            cos_angle = math.cos(angle)
            vertices.append([
                radius * sin_angle, y, radius * cos_angle,
                radial_normal * sin_angle, vertical_normal, radial_normal * cos_angle,
                fraction * 2.0, 1.0 - v,
            ])

    for ring in range(len(ring_starts) - 1):
        start = ring_starts[ring]
        following = ring_starts[ring + 1]
        for x in range(longitudes):
            a = start + x
            b = following + x
            indices.extend((a, a + 1, b, a + 1, b + 1, b))

    bottom_centre = len(vertices)
    vertices.append([0.0, bottom_pole[1], 0.0, 0.0, -1.0, 0.0, 1.0, 1.0])
    first_ring = ring_starts[0]
    for x in range(longitudes):
        indices.extend((bottom_centre, first_ring + x + 1, first_ring + x))

    top_centre = len(vertices)
    vertices.append([0.0, top_pole[1], 0.0, 0.0, 1.0, 0.0, 1.0, 0.0])
    last_ring = ring_starts[-1]
    for x in range(longitudes):
        indices.extend((top_centre, last_ring + x, last_ring + x + 1))

    return MeshData(np.asarray(vertices, dtype=np.float32), np.asarray(indices, dtype=np.uint32), "Rounded Cylinder")

def sphere_mesh(longitudes: int = 96, latitudes: int = 48) -> MeshData:
    longitudes = min(max(int(longitudes), 8), 512)
    latitudes = min(max(int(latitudes), 4), 256)
    vertices: list[list[float]] = []
    for y in range(latitudes + 1):
        v = y / latitudes
        phi = v * math.pi
        sin_phi = math.sin(phi)
        cos_phi = math.cos(phi)
        for x in range(longitudes + 1):
            u = x / longitudes
            theta = u * math.tau
            nx = sin_phi * math.sin(theta)
            ny = cos_phi
            nz = sin_phi * math.cos(theta)
            vertices.append([nx * 0.82, ny * 0.82, nz * 0.82, nx, ny, nz, u, v])
    indices: list[int] = []
    row = longitudes + 1
    for y in range(latitudes):
        for x in range(longitudes):
            a = y * row + x
            b = a + row
            # The old winding faced inward even though the stored vertex
            # normals pointed outward. This is now counter-clockwise from the
            # outside, matching every other built-in preview mesh.
            indices.extend((a, b, a + 1, a + 1, b, b + 1))
    return MeshData(np.asarray(vertices, dtype=np.float32), np.asarray(indices, dtype=np.uint32), "Sphere")


def _normalise_vectors(values: np.ndarray) -> np.ndarray:
    lengths = np.linalg.norm(values, axis=1, keepdims=True)
    return values / np.maximum(lengths, 1e-8)


def _compute_normals(positions: np.ndarray, indices: np.ndarray) -> np.ndarray:
    normals = np.zeros_like(positions, dtype=np.float32)
    triangles = indices.reshape(-1, 3)
    p0 = positions[triangles[:, 0]]
    p1 = positions[triangles[:, 1]]
    p2 = positions[triangles[:, 2]]
    face = np.cross(p1 - p0, p2 - p0)
    for corner in range(3):
        np.add.at(normals, triangles[:, corner], face)
    return _normalise_vectors(normals)


def _component_info(component_type: int) -> tuple[np.dtype, int]:
    table: dict[int, tuple[np.dtype, int]] = {
        5120: (np.dtype(np.int8), 1),
        5121: (np.dtype(np.uint8), 1),
        5122: (np.dtype("<i2"), 2),
        5123: (np.dtype("<u2"), 2),
        5125: (np.dtype("<u4"), 4),
        5126: (np.dtype("<f4"), 4),
    }
    if component_type not in table:
        raise ValueError(f"Unsupported glTF component type {component_type}")
    return table[component_type]


def _component_count(kind: str) -> int:
    counts = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
    if kind not in counts:
        raise ValueError(f"Unsupported glTF accessor type {kind!r}")
    return counts[kind]


def _decode_data_uri(uri: str) -> bytes:
    marker = ";base64,"
    if not uri.startswith("data:") or marker not in uri:
        raise ValueError("Only base64 glTF data URIs are supported")
    return base64.b64decode(uri.split(marker, 1)[1])


def _load_gltf_document(path: Path) -> tuple[dict[str, Any], list[bytes]]:
    if path.suffix.lower() == ".glb":
        raw = path.read_bytes()
        if len(raw) < 12 or raw[:4] != b"glTF":
            raise ValueError("Invalid GLB header")
        _magic, version, total_length = struct.unpack_from("<4sII", raw, 0)
        if version != 2 or total_length > len(raw):
            raise ValueError("Only glTF/GLB 2.0 files are supported")
        offset = 12
        json_chunk: bytes | None = None
        binary_chunks: list[bytes] = []
        while offset + 8 <= total_length:
            length, chunk_type = struct.unpack_from("<II", raw, offset)
            offset += 8
            chunk = raw[offset : offset + length]
            offset += length
            if chunk_type == 0x4E4F534A:
                json_chunk = chunk.rstrip(b"\x00 \t\r\n")
            elif chunk_type == 0x004E4942:
                binary_chunks.append(chunk)
        if json_chunk is None:
            raise ValueError("GLB does not contain a JSON chunk")
        document = json.loads(json_chunk.decode("utf-8"))
        buffers: list[bytes] = []
        binary_index = 0
        for buffer_info in document.get("buffers", []):
            uri = buffer_info.get("uri")
            if uri:
                buffers.append(_decode_data_uri(uri) if str(uri).startswith("data:") else (path.parent / str(uri)).read_bytes())
            else:
                if binary_index >= len(binary_chunks):
                    raise ValueError("GLB buffer is missing its BIN chunk")
                buffers.append(binary_chunks[binary_index])
                binary_index += 1
        return document, buffers

    document = json.loads(path.read_text(encoding="utf-8"))
    buffers = []
    for buffer_info in document.get("buffers", []):
        uri = str(buffer_info.get("uri", ""))
        if not uri:
            raise ValueError("External .gltf buffer has no URI")
        buffers.append(_decode_data_uri(uri) if uri.startswith("data:") else (path.parent / uri).read_bytes())
    return document, buffers


def _read_accessor(document: dict[str, Any], buffers: list[bytes], accessor_index: int) -> np.ndarray:
    accessor = document["accessors"][accessor_index]
    if "sparse" in accessor:
        raise ValueError("Sparse glTF accessors are not supported yet")
    view_index = accessor.get("bufferView")
    if view_index is None:
        raise ValueError("Accessor without bufferView is unsupported")
    view = document["bufferViews"][view_index]
    buffer_data = buffers[int(view["buffer"])]
    dtype, component_size = _component_info(int(accessor["componentType"]))
    components = _component_count(str(accessor["type"]))
    count = int(accessor["count"])
    offset = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    item_bytes = component_size * components
    stride = int(view.get("byteStride", item_bytes))
    if stride < item_bytes:
        raise ValueError("Invalid glTF byte stride")
    if stride == item_bytes:
        values = np.frombuffer(buffer_data, dtype=dtype, count=count * components, offset=offset).reshape(count, components)
    else:
        values = np.ndarray(
            shape=(count, components),
            dtype=dtype,
            buffer=buffer_data,
            offset=offset,
            strides=(stride, component_size),
        ).copy()
    if bool(accessor.get("normalized", False)) and dtype.kind in "iu":
        info = np.iinfo(dtype)
        if dtype.kind == "u":
            values = values.astype(np.float32) / float(info.max)
        else:
            values = np.maximum(values.astype(np.float32) / float(info.max), -1.0)
    return np.asarray(values)


def load_gltf_mesh(path: str | Path) -> MeshData:
    path = Path(path).expanduser().resolve()
    if path.suffix.lower() not in (".gltf", ".glb"):
        raise ValueError("Custom preview meshes must be glTF 2.0 (.gltf or .glb)")
    document, buffers = _load_gltf_document(path)
    meshes = document.get("meshes", [])
    if not meshes:
        raise ValueError("The glTF file contains no meshes")
    primitives = meshes[0].get("primitives", [])
    if not primitives:
        raise ValueError("The first glTF mesh contains no primitives")
    primitive = primitives[0]
    if int(primitive.get("mode", 4)) != 4:
        raise ValueError("Only triangle-list glTF primitives are supported")
    attributes = primitive.get("attributes", {})
    if "POSITION" not in attributes:
        raise ValueError("The glTF primitive has no POSITION attribute")
    positions = _read_accessor(document, buffers, int(attributes["POSITION"])).astype(np.float32)
    if positions.shape[1] != 3:
        raise ValueError("POSITION must be VEC3")
    if "indices" in primitive:
        indices = _read_accessor(document, buffers, int(primitive["indices"])).reshape(-1).astype(np.uint32)
    else:
        indices = np.arange(positions.shape[0], dtype=np.uint32)
    if indices.size % 3:
        raise ValueError("The glTF primitive does not contain complete triangles")
    if "NORMAL" in attributes:
        normals = _read_accessor(document, buffers, int(attributes["NORMAL"])).astype(np.float32)
        normals = _normalise_vectors(normals[:, :3])
    else:
        normals = _compute_normals(positions, indices)
    if "TEXCOORD_0" in attributes:
        uvs = _read_accessor(document, buffers, int(attributes["TEXCOORD_0"])).astype(np.float32)[:, :2]
    else:
        uvs = np.zeros((positions.shape[0], 2), dtype=np.float32)

    # Centre and fit the first primitive into the same convenient preview scale
    # as the built-in meshes, without changing UVs or relative proportions.
    minimum = positions.min(axis=0)
    maximum = positions.max(axis=0)
    centre = (minimum + maximum) * 0.5
    extent = float(np.max(maximum - minimum))
    positions = (positions - centre) * (1.6 / max(extent, 1e-8))
    vertices = np.concatenate((positions, normals, uvs), axis=1)
    name = str(meshes[0].get("name") or path.stem)
    return MeshData(vertices, indices, name)


def mesh_for_settings(mesh_name: str, quality: str | int, custom_path: str = "") -> MeshData:
    if isinstance(quality, int):
        legacy = int(quality)
        quality = "Ultra" if legacy >= 512 else "High" if legacy >= 256 else "Medium" if legacy >= 128 else "Low"
    quality = str(quality)
    plane_subdivisions = {"Low": 64, "Medium": 128, "High": 256, "Ultra": 512}.get(quality, 256)
    if mesh_name == "Sphere":
        longitude, latitude = {
            "Low": (32, 16),
            "Medium": (64, 32),
            "High": (96, 48),
            "Ultra": (192, 96),
        }.get(quality, (96, 48))
        return sphere_mesh(longitude, latitude)
    if mesh_name == "Cube":
        subdivisions = {"Low": 1, "Medium": 8, "High": 24, "Ultra": 48}.get(quality, 24)
        return cube_mesh(subdivisions)
    if mesh_name == "Rounded Cube":
        subdivisions = {"Low": 12, "Medium": 24, "High": 48, "Ultra": 96}.get(quality, 48)
        return rounded_cube_mesh(subdivisions)
    if mesh_name == "Rounded Cylinder":
        longitude, bevel_segments = {
            "Low": (32, 6),
            "Medium": (64, 10),
            "High": (96, 16),
            "Ultra": (192, 28),
        }.get(quality, (96, 16))
        return rounded_cylinder_mesh(longitude, bevel_segments)
    if mesh_name == "Custom Mesh":
        if not custom_path:
            raise FileNotFoundError("Choose a .gltf or .glb file for Custom Mesh")
        return load_gltf_mesh(custom_path)
    if mesh_name == "Flat Plane":
        return terrain_grid(plane_subdivisions, name="Flat Plane")
    return terrain_grid(plane_subdivisions, name="Terrain Plane")
