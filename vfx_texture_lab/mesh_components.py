"""Connected-component geometry cleanup for imported scans and kitbashed meshes."""
from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from .geometry import GeometryData, GeometryEvalContext


def _position_topology(positions: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    values = np.ascontiguousarray(positions, dtype=np.float32).reshape(-1, 3)
    bits = values.view(np.uint32).reshape(-1, 3)
    _unique, first, inverse = np.unique(
        bits, axis=0, return_index=True, return_inverse=True
    )
    return (
        np.ascontiguousarray(values[first], dtype=np.float32),
        np.ascontiguousarray(inverse, dtype=np.int64),
    )


def _component_labels(
    vertex_count: int,
    edges: np.ndarray,
    context: GeometryEvalContext | None,
) -> tuple[int, np.ndarray, str]:
    try:
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
    except ImportError:
        coo_matrix = None
        connected_components = None

    if coo_matrix is not None and connected_components is not None:
        if context is not None:
            context.progress(35, 100, "Building connected-component adjacency")
            context.checkpoint()
        if edges.size:
            # ``directed=False`` treats the sparse graph as undirected, so one
            # orientation per triangle edge is sufficient. Avoiding an explicit
            # reverse-edge copy saves six large temporary arrays on scan meshes.
            rows = np.ascontiguousarray(edges[:, 0], dtype=np.int64)
            columns = np.ascontiguousarray(edges[:, 1], dtype=np.int64)
            data = np.ones(rows.shape[0], dtype=np.uint8)
            graph = coo_matrix(
                (data, (rows, columns)), shape=(vertex_count, vertex_count)
            ).tocsr()
        else:
            graph = coo_matrix((vertex_count, vertex_count), dtype=np.uint8).tocsr()
        count, labels = connected_components(
            graph, directed=False, return_labels=True
        )
        if context is not None:
            context.checkpoint()
        return int(count), np.ascontiguousarray(labels, dtype=np.int64), "SciPy connected components"

    # Small dependency-free compatibility path. The project setup installs
    # SciPy for voxel remeshing, so this is mainly useful to open old source
    # checkouts in incomplete development environments.
    parent = np.arange(vertex_count, dtype=np.int64)
    rank = np.zeros(vertex_count, dtype=np.uint8)

    def find(value: int) -> int:
        root = value
        while parent[root] != root:
            root = int(parent[root])
        while parent[value] != value:
            following = int(parent[value])
            parent[value] = root
            value = following
        return root

    for edge_index, edge in enumerate(edges):
        if context is not None and (edge_index & 0xFFFF) == 0:
            context.progress(edge_index, max(len(edges), 1), "Finding connected mesh parts")
        a = find(int(edge[0]))
        b = find(int(edge[1]))
        if a == b:
            continue
        if rank[a] < rank[b]:
            a, b = b, a
        parent[b] = a
        if rank[a] == rank[b]:
            rank[a] += 1
    roots = np.asarray([find(index) for index in range(vertex_count)], dtype=np.int64)
    _unique, labels = np.unique(roots, return_inverse=True)
    return int(labels.max() + 1 if labels.size else 0), labels, "Python compatibility fallback"


def delete_small_parts_geometry(
    geometry: GeometryData,
    *,
    mode: str = "Keep Largest Only",
    measure: str = "Vertex Count",
    minimum_relative_size: float = 2.0,
    name: str = "Largest Mesh Part",
    context: GeometryEvalContext | None = None,
) -> GeometryData:
    if not isinstance(geometry, GeometryData):
        raise TypeError("Geometry Delete Small Parts requires a connected Geometry input")
    if geometry.triangle_count < 1:
        raise ValueError("Geometry Delete Small Parts requires at least one triangle")

    if context is not None:
        context.progress(5, 100, "Welding exact position copies for connectivity")
    positions, raw_to_topology = _position_topology(geometry.vertices[:, :3])
    triangles = np.ascontiguousarray(geometry.indices, dtype=np.uint32).reshape(-1, 3)
    topology_faces = raw_to_topology[triangles]
    edges = np.concatenate(
        (
            topology_faces[:, (0, 1)],
            topology_faces[:, (1, 2)],
            topology_faces[:, (2, 0)],
        ),
        axis=0,
    )
    if context is not None:
        context.checkpoint()
    _count, labels, backend = _component_labels(positions.shape[0], edges, context)
    triangle_components = labels[topology_faces[:, 0]]
    active_labels, compact_triangle_components = np.unique(
        triangle_components, return_inverse=True
    )
    component_count = int(active_labels.size)
    if component_count <= 1:
        # A mesh can still contain unreferenced render vertices even when all
        # triangles form one connected surface. Compact those too so this node
        # remains a dependable one-click scan cleanup stage.
        used_raw = np.unique(triangles.reshape(-1))
        removed_vertices = geometry.vertex_count - int(used_raw.size)
        if removed_vertices > 0:
            remap = np.full((geometry.vertex_count,), -1, dtype=np.int64)
            remap[used_raw] = np.arange(used_raw.size, dtype=np.int64)
            output = GeometryData(
                np.ascontiguousarray(geometry.vertices[used_raw], dtype=np.float32),
                np.ascontiguousarray(remap[triangles].astype(np.uint32).reshape(-1)),
                name,
                geometry.uv_origin,
            )
        else:
            output = geometry.copy(name=name)
        if context is not None:
            p0 = positions[topology_faces[:, 0]].astype(np.float64)
            p1 = positions[topology_faces[:, 1]].astype(np.float64)
            p2 = positions[topology_faces[:, 2]].astype(np.float64)
            surface_area = float(
                (np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1) * 0.5).sum()
            )
            context.report_metadata(
                {
                    "_parts_backend": backend,
                    "_parts_input_components": component_count,
                    "_parts_output_components": component_count,
                    "_parts_removed_components": 0,
                    "_parts_removed_vertices": removed_vertices,
                    "_parts_removed_triangles": 0,
                    "_parts_largest_vertices": int(np.unique(topology_faces).size),
                    "_parts_largest_triangles": int(triangles.shape[0]),
                    "_parts_largest_surface_area": surface_area,
                    "_parts_measure": str(measure),
                }
            )
            message = (
                "Removed unreferenced vertices"
                if removed_vertices
                else "The mesh already contains one connected part"
            )
            context.progress(100, 100, message)
        return output

    if context is not None:
        context.progress(62, 100, "Measuring disconnected mesh parts")
        context.checkpoint()
    triangle_counts = np.bincount(
        compact_triangle_components, minlength=component_count
    ).astype(np.int64)
    used_topology = np.unique(topology_faces.reshape(-1))
    active_lookup = np.full((int(labels.max()) + 1,), -1, dtype=np.int64)
    active_lookup[active_labels] = np.arange(component_count, dtype=np.int64)
    vertex_components = active_lookup[labels[used_topology]]
    vertex_counts = np.bincount(
        vertex_components[vertex_components >= 0], minlength=component_count
    ).astype(np.int64)
    p0 = positions[topology_faces[:, 0]].astype(np.float64)
    p1 = positions[topology_faces[:, 1]].astype(np.float64)
    p2 = positions[topology_faces[:, 2]].astype(np.float64)
    triangle_areas = np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1) * 0.5
    surface_areas = np.bincount(
        compact_triangle_components,
        weights=triangle_areas,
        minlength=component_count,
    ).astype(np.float64)

    measure_name = str(measure or "Vertex Count")
    if measure_name == "Triangle Count":
        metric = triangle_counts.astype(np.float64)
    elif measure_name == "Surface Area":
        metric = surface_areas
        if not np.any(metric > 0.0):
            metric = triangle_counts.astype(np.float64)
            measure_name = "Triangle Count"
    else:
        metric = vertex_counts.astype(np.float64)
        measure_name = "Vertex Count"
    largest = int(np.argmax(metric))
    keep_components = np.zeros(component_count, dtype=bool)
    if str(mode or "Keep Largest Only") == "Keep Parts Above Relative Size":
        threshold = float(metric[largest]) * min(
            max(float(minimum_relative_size), 0.0), 100.0
        ) / 100.0
        keep_components = metric >= threshold
    keep_components[largest] = True

    keep_triangles = keep_components[compact_triangle_components]
    selected_triangles = triangles[keep_triangles]
    if selected_triangles.shape[0] < 1:
        selected_triangles = triangles[compact_triangle_components == largest]
        keep_components[:] = False
        keep_components[largest] = True
    used_raw = np.unique(selected_triangles.reshape(-1))
    remap = np.full((geometry.vertex_count,), -1, dtype=np.int64)
    remap[used_raw] = np.arange(used_raw.size, dtype=np.int64)
    output_vertices = np.ascontiguousarray(geometry.vertices[used_raw], dtype=np.float32)
    output_indices = np.ascontiguousarray(
        remap[selected_triangles].astype(np.uint32).reshape(-1), dtype=np.uint32
    )
    output = GeometryData(output_vertices, output_indices, name, geometry.uv_origin)

    kept_count = int(np.count_nonzero(keep_components))
    if context is not None:
        context.report_metadata(
            {
                "_parts_backend": backend,
                "_parts_input_components": component_count,
                "_parts_output_components": kept_count,
                "_parts_removed_components": component_count - kept_count,
                "_parts_removed_vertices": geometry.vertex_count - output.vertex_count,
                "_parts_removed_triangles": geometry.triangle_count - output.triangle_count,
                "_parts_largest_vertices": int(vertex_counts[largest]),
                "_parts_largest_triangles": int(triangle_counts[largest]),
                "_parts_largest_surface_area": float(surface_areas[largest]),
                "_parts_measure": measure_name,
                "_parts_relative_threshold": float(minimum_relative_size),
            }
        )
        context.progress(100, 100, "Small disconnected mesh parts removed")
    return output


def evaluate_delete_small_parts(
    inputs: Mapping[str, Any],
    parameters: Mapping[str, Any],
    context: GeometryEvalContext | None = None,
) -> GeometryData:
    source = inputs.get("Geometry")
    if not isinstance(source, GeometryData):
        raise TypeError("Geometry Delete Small Parts requires a connected Geometry input")
    return delete_small_parts_geometry(
        source,
        mode=str(parameters.get("mode", "Keep Largest Only")),
        measure=str(parameters.get("measure", "Vertex Count")),
        minimum_relative_size=float(parameters.get("minimum_relative_size", 2.0)),
        name=str(parameters.get("name", "Largest Mesh Part") or "Largest Mesh Part"),
        context=context,
    )
