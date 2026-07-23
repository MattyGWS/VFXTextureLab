"""Manual voxel remeshing for scan cleanup and uniform topology.

The implementation follows the same broad workflow as Blender's voxel remesh:
voxelise the surface at an object-space resolution, build a new manifold
isosurface, optionally smooth/preserve volume, then apply shape-aware
adaptivity. UVs are intentionally discarded because a remesh creates entirely
new topology; Geometry UV Unwrap belongs after this node.
"""
from __future__ import annotations

from typing import Any, Mapping

import math
import numpy as np

from .geometry import GeometryData, GeometryEvalContext
from .manual_geometry import ManualGeometryResult, evaluate_manual_geometry_operation
from .mesh_processing import build_topology, diagnose_mesh, native_decimate


REMESH_SIGNATURE_PARAMETERS = (
    "voxel_size_mode",
    "relative_voxel_size",
    "absolute_voxel_size",
    "fill_interior",
    "surface_smoothing",
    "preserve_volume",
    "adaptivity",
)

_MAX_VOXEL_CELLS = 64_000_000
_MAX_VOXEL_AXIS = 1024


def _dependencies():
    try:
        import trimesh
        from scipy import ndimage
        from skimage import measure
    except Exception as exc:  # pragma: no cover - setup/package diagnostic path.
        raise RuntimeError(
            "Geometry Remesh requires trimesh, scipy and scikit-image. "
            "Run setup.sh or setup.bat from this version."
        ) from exc
    return trimesh, ndimage, measure


def _progress(context: GeometryEvalContext | None, current: int, message: str) -> None:
    if context is not None:
        context.progress(int(current), 100, message)


def _volume_scale(mesh, target_volume: float) -> float:
    current = abs(float(getattr(mesh, "volume", 0.0) or 0.0))
    if target_volume <= 1.0e-12 or current <= 1.0e-12:
        return 1.0
    return float((target_volume / current) ** (1.0 / 3.0))


def _voxel_size(
    positions: np.ndarray, parameters: Mapping[str, Any]
) -> tuple[float, bool, np.ndarray, np.ndarray]:
    minimum = positions.min(axis=0)
    maximum = positions.max(axis=0)
    extent = np.maximum(maximum - minimum, 0.0)
    longest = max(float(extent.max()), 1.0e-8)
    relative = str(parameters.get("voxel_size_mode", "Relative to Bounds")) != "Absolute Units"
    if relative:
        percent = min(max(float(parameters.get("relative_voxel_size", 1.0)), 0.05), 50.0)
        pitch = longest * percent / 100.0
    else:
        pitch = max(float(parameters.get("absolute_voxel_size", 0.05)), 1.0e-8)
    pitch = max(pitch, longest * 1.0e-7, 1.0e-8)
    return pitch, relative, minimum, extent


def voxel_remesh(
    source: GeometryData,
    parameters: Mapping[str, Any],
    context: GeometryEvalContext | None = None,
) -> ManualGeometryResult:
    if not isinstance(source, GeometryData):
        raise TypeError("Geometry Remesh requires a connected Geometry input")
    if source.triangle_count < 1:
        raise ValueError("Geometry Remesh requires at least one triangle")

    trimesh, ndimage, measure = _dependencies()
    _progress(context, 2, "Preparing geometric topology")
    topology = build_topology(
        source.vertices,
        source.indices,
        cancel_check=(context.cancel_check if context is not None else None),
        progress_callback=None,
    )
    if topology.faces.shape[0] < 1:
        raise ValueError("The input has no usable geometric triangles after cleanup")
    if context is not None:
        context.checkpoint()

    positions = np.ascontiguousarray(topology.points, dtype=np.float64)
    faces = np.ascontiguousarray(topology.faces, dtype=np.int64)
    pitch, relative, _minimum, extent = _voxel_size(positions, parameters)
    estimated_shape = np.maximum(np.ceil(extent / pitch).astype(np.int64) + 5, 3)
    estimated_axis = int(estimated_shape.max())
    # Check the longest axis before multiplying dimensions so an intentionally
    # absurd typed voxel size cannot overflow int64 during the safety check.
    estimated_cells = (
        _MAX_VOXEL_CELLS + 1
        if estimated_axis > _MAX_VOXEL_AXIS
        else int(np.prod(estimated_shape, dtype=np.int64))
    )
    if estimated_axis > _MAX_VOXEL_AXIS or estimated_cells > _MAX_VOXEL_CELLS:
        relative_hint = float(parameters.get("relative_voxel_size", 1.0))
        raise ValueError(
            "The requested voxel size would create an unsafe "
            f"{int(estimated_shape[0]):,} × {int(estimated_shape[1]):,} × "
            f"{int(estimated_shape[2]):,} grid ({estimated_cells:,} cells). "
            "Increase Voxel Size"
            + (f" above {relative_hint:g}%" if relative else "")
            + "."
        )

    _progress(context, 10, "Voxelising the source surface")
    source_mesh = trimesh.Trimesh(
        vertices=positions,
        faces=faces,
        process=False,
        validate=False,
    )
    source_closed = bool(topology.diagnostics.closed_manifold)
    source_volume = abs(float(source_mesh.volume)) if source_closed else 0.0
    voxel_grid = source_mesh.voxelized(pitch=pitch, method="subdivide")
    if context is not None:
        context.checkpoint()
    if voxel_grid.is_empty:
        raise ValueError("Voxelisation produced no occupied cells; decrease Voxel Size")

    if bool(parameters.get("fill_interior", True)):
        _progress(context, 30, "Filling the voxel interior")
        voxel_grid.fill(method="holes")
        if context is not None:
            context.checkpoint()

    grid = np.asarray(voxel_grid.matrix, dtype=np.float32)
    grid_shape = np.asarray(grid.shape, dtype=np.int64)
    grid_axis = int(grid_shape.max())
    grid_cells = (
        _MAX_VOXEL_CELLS + 1
        if grid_axis > _MAX_VOXEL_AXIS
        else int(np.prod(grid_shape, dtype=np.int64))
    )
    if grid_axis > _MAX_VOXEL_AXIS or grid_cells > _MAX_VOXEL_CELLS:
        raise ValueError(
            "Voxelisation exceeded the safe grid limit after rasterisation. "
            "Increase Voxel Size."
        )
    filled_voxels = int(np.count_nonzero(grid))
    if filled_voxels < 1:
        raise ValueError("Voxelisation produced an empty occupancy grid")

    _progress(context, 42, "Preparing the remesh volume")
    field = np.pad(grid, 1, mode="constant", constant_values=0.0)
    smoothness = min(max(float(parameters.get("surface_smoothing", 0.75)), 0.0), 3.0)
    if smoothness > 1.0e-6:
        field = ndimage.gaussian_filter(
            field,
            sigma=smoothness,
            mode="constant",
            cval=0.0,
            output=np.float32,
        )
    if context is not None:
        context.checkpoint()
    maximum_field = float(field.max())
    if maximum_field <= 1.0e-8:
        raise ValueError("The smoothed voxel field is empty; reduce Surface Smoothing")
    iso_level = min(0.5, maximum_field * 0.5)

    _progress(context, 55, "Extracting a uniform triangle surface")
    out_positions, out_faces, _field_normals, _values = measure.marching_cubes(
        field,
        level=iso_level,
        spacing=(pitch, pitch, pitch),
        allow_degenerate=False,
        method="lewiner",
    )
    origin = np.asarray(voxel_grid.transform[:3, 3], dtype=np.float64) - pitch
    out_positions = np.ascontiguousarray(out_positions + origin[None, :], dtype=np.float64)
    out_faces = np.ascontiguousarray(out_faces, dtype=np.int64)
    if out_faces.shape[0] < 1:
        raise ValueError("Marching Cubes produced no remeshed triangles")
    if context is not None:
        context.checkpoint()

    _progress(context, 67, "Rebuilding outward normals")
    remeshed = trimesh.Trimesh(
        vertices=out_positions,
        faces=out_faces,
        process=False,
        validate=False,
    )
    try:
        remeshed.fix_normals(multibody=True)
    except TypeError:  # Compatibility with older trimesh builds.
        remeshed.fix_normals()

    preserve_volume = bool(parameters.get("preserve_volume", True))
    if preserve_volume:
        target_volume = source_volume
        if target_volume <= 1.0e-12 and bool(parameters.get("fill_interior", True)):
            target_volume = filled_voxels * (pitch ** 3)
        scale = _volume_scale(remeshed, target_volume)
        if abs(scale - 1.0) > 1.0e-6:
            centre = np.asarray(remeshed.bounds, dtype=np.float64).mean(axis=0)
            remeshed.vertices = (remeshed.vertices - centre) * scale + centre
            remeshed._cache.clear()

    # Discrete voxel grids can bias an isosurface by a fraction of one cell,
    # especially when an object's bounds do not align symmetrically with the
    # chosen pitch. Preserve the authored object-space placement by restoring
    # the source bounds centre after extraction/scaling.
    source_bounds_centre = (positions.min(axis=0) + positions.max(axis=0)) * 0.5
    output_bounds_centre = np.asarray(remeshed.bounds, dtype=np.float64).mean(axis=0)
    centre_offset = source_bounds_centre - output_bounds_centre
    if np.linalg.norm(centre_offset) > 1.0e-10:
        remeshed.vertices = remeshed.vertices + centre_offset
        remeshed._cache.clear()

    normals = np.asarray(remeshed.vertex_normals, dtype=np.float32)
    vertices = np.zeros((len(remeshed.vertices), 8), dtype=np.float32)
    vertices[:, :3] = np.asarray(remeshed.vertices, dtype=np.float32)
    vertices[:, 3:6] = normals
    # Remeshing creates new topology, therefore old UVs cannot remain valid.
    vertices[:, 6:8] = 0.0
    indices = np.asarray(remeshed.faces, dtype=np.uint32).reshape(-1)
    output_name = str(parameters.get("name", "Remeshed Geometry") or "Remeshed Geometry")
    geometry = GeometryData(vertices, indices, output_name)

    adaptivity = min(max(float(parameters.get("adaptivity", 0.0)), 0.0), 1.0)
    adaptivity_backend = "None"
    adaptivity_passes = 0
    if adaptivity > 1.0e-6 and geometry.triangle_count > 4:
        _progress(context, 74, "Applying shape-aware adaptivity")
        retain = max(0.05, 1.0 - adaptivity * 0.90)
        target = max(4, int(round(geometry.triangle_count * retain)))

        def decimate_progress(current: int, total: int, message: str) -> None:
            fraction = 0.0 if total <= 0 else min(max(current / total, 0.0), 1.0)
            _progress(context, 74 + int(round(fraction * 18.0)), message)

        reduced_vertices, reduced_indices, _diag, adaptivity_backend, adaptivity_passes = native_decimate(
            geometry.vertices,
            geometry.indices,
            target,
            aggression=3.0,
            cancel_check=(context.cancel_check if context is not None else None),
            progress_callback=decimate_progress if context is not None else None,
        )
        geometry = GeometryData(reduced_vertices, reduced_indices, output_name)

    _progress(context, 94, "Validating remeshed topology")
    diagnostics = diagnose_mesh(
        geometry.vertices,
        geometry.indices,
        cancel_check=(context.cancel_check if context is not None else None),
        progress_callback=None,
    )
    if context is not None:
        context.checkpoint()
    output_mesh = trimesh.Trimesh(
        vertices=geometry.vertices[:, :3].astype(np.float64),
        faces=geometry.indices.reshape(-1, 3).astype(np.int64),
        process=False,
        validate=False,
    )
    output_volume = abs(float(output_mesh.volume)) if diagnostics.closed_manifold else 0.0
    _progress(context, 100, "Voxel remesh complete")

    detail = {
        "backend": "Voxel remesh (trimesh + Lewiner Marching Cubes)",
        "voxel_size": float(pitch),
        "voxel_size_relative": bool(relative),
        "grid_x": int(grid_shape[0]),
        "grid_y": int(grid_shape[1]),
        "grid_z": int(grid_shape[2]),
        "grid_cells": int(grid_cells),
        "filled_voxels": int(filled_voxels),
        "input_vertex_count": int(source.vertex_count),
        "input_triangle_count": int(source.triangle_count),
        "input_closed_manifold": bool(source_closed),
        "output_vertex_count": int(geometry.vertex_count),
        "output_triangle_count": int(geometry.triangle_count),
        "output_closed_manifold": bool(diagnostics.closed_manifold),
        "output_boundary_edges": int(diagnostics.boundary_edges),
        "output_non_manifold_edges": int(diagnostics.non_manifold_edges),
        "output_connected_components": int(diagnostics.connected_components),
        "output_degenerate_triangles": int(diagnostics.degenerate_triangles),
        "source_volume": float(source_volume),
        "output_volume": float(output_volume),
        "surface_smoothing": float(smoothness),
        "preserve_volume": bool(preserve_volume),
        "adaptivity": float(adaptivity),
        "adaptivity_backend": str(adaptivity_backend),
        "adaptivity_pass_count": int(adaptivity_passes),
        "uvs_discarded": True,
    }
    return ManualGeometryResult(geometry, detail)


def evaluate_manual_remesh(
    inputs: Mapping[str, Any],
    parameters: Mapping[str, Any],
    context: GeometryEvalContext | None = None,
) -> GeometryData:
    source = inputs.get("Geometry")
    if not isinstance(source, GeometryData):
        raise TypeError("Geometry Remesh requires a connected Geometry input")
    return evaluate_manual_geometry_operation(
        source,
        parameters,
        context,
        parameter_names=REMESH_SIGNATURE_PARAMETERS,
        default_name="Remeshed Geometry",
        operation_name="Remesh",
        metadata_prefix="remesh",
        operation=voxel_remesh,
        include_normals_in_signature=False,
        include_uvs_in_signature=False,
    )
