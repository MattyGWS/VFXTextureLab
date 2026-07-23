from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pytest

from vfx_texture_lab.geometry import (
    box_geometry,
    decimate_geometry,
    plane_geometry,
    ribbon_geometry,
    subdivide_geometry,
    unsubdivide_geometry,
)
from vfx_texture_lab.nodes.registry import build_registry


def _triangle_areas(geometry) -> np.ndarray:
    triangles = geometry.indices.reshape(-1, 3)
    positions = geometry.vertices[:, :3]
    p0 = positions[triangles[:, 0]]
    p1 = positions[triangles[:, 1]]
    p2 = positions[triangles[:, 2]]
    return np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1) * 0.5


def test_geometry_reduction_nodes_are_registered() -> None:
    registry = build_registry()
    decimate = registry.get("geometry.decimate")
    unsubdivide = registry.get("geometry.unsubdivide")

    percentage = next(spec for spec in decimate.parameters if spec.name == "percentage")
    assert percentage.default == 100.0
    assert percentage.minimum == 1.0
    assert percentage.maximum == 100.0
    assert percentage.unit == "%"

    iterations = next(spec for spec in unsubdivide.parameters if spec.name == "iterations")
    assert iterations.default == 1
    assert iterations.minimum == 1
    assert iterations.maximum == 6


def test_decimate_percentage_and_topology_safety() -> None:
    source = plane_geometry(2.0, 2.0, 16, 16)
    unchanged = decimate_geometry(source, 100.0)
    assert np.array_equal(unchanged.vertices, source.vertices)
    assert np.array_equal(unchanged.indices, source.indices)

    reduced = decimate_geometry(source, 25.0)
    assert reduced.triangle_count == round(source.triangle_count * 0.25)
    assert reduced.vertex_count < source.vertex_count
    assert np.allclose(reduced.bounds[0], source.bounds[0])
    assert np.allclose(reduced.bounds[1], source.bounds[1])
    assert np.all(_triangle_areas(reduced) > 1.0e-10)
    assert np.isfinite(reduced.vertices).all()
    assert np.allclose(np.linalg.norm(reduced.vertices[:, 3:6], axis=1), 1.0)

    minimum = decimate_geometry(plane_geometry(2.0, 2.0, 1, 1), 1.0)
    assert minimum.triangle_count == 1


def test_decimate_does_not_overshoot_requested_target() -> None:
    source = box_geometry(
        subdivisions_x=2,
        subdivisions_y=2,
        subdivisions_z=2,
    )
    for percentage in (75.0, 50.0, 25.0, 10.0, 1.0):
        reduced = decimate_geometry(source, percentage)
        target = max(1, round(source.triangle_count * percentage / 100.0))
        assert reduced.triangle_count >= target
        assert reduced.triangle_count <= source.triangle_count
        assert np.all(_triangle_areas(reduced) > 1.0e-10)


def test_unsubdivide_exactly_reverses_geometry_subdivide() -> None:
    source = plane_geometry(2.0, 2.0, 3, 2)
    dense = subdivide_geometry(source, levels=2, smooth_surface=False)

    one_level = unsubdivide_geometry(dense, iterations=1)
    assert one_level.triangle_count == source.triangle_count * 4

    restored = unsubdivide_geometry(dense, iterations=2)
    assert restored.vertex_count == source.vertex_count
    assert restored.triangle_count == source.triangle_count
    assert np.allclose(restored.vertices, source.vertices)
    assert np.array_equal(restored.indices, source.indices)

    # Asking for more passes than exist stops at the earliest recoverable mesh.
    exhausted = unsubdivide_geometry(dense, iterations=6)
    assert np.allclose(exhausted.vertices, source.vertices)
    assert np.array_equal(exhausted.indices, source.indices)


def test_unsubdivide_handles_smoothed_subdivide_topology_and_rejects_noise() -> None:
    source = box_geometry()
    dense = subdivide_geometry(source, levels=2, smooth_surface=True)
    restored = unsubdivide_geometry(dense, iterations=2)
    assert restored.triangle_count == source.triangle_count
    assert restored.vertex_count == source.vertex_count
    assert np.all(_triangle_areas(restored) > 1.0e-10)

    # A random triangle soup has no recoverable four-triangle subdivision patches.
    randomised = source.copy()
    randomised.indices = randomised.indices[::-1].copy()
    with pytest.raises(ValueError, match="compatible midpoint subdivision topology"):
        unsubdivide_geometry(randomised, iterations=1)


def test_unsubdivide_reduces_structured_generator_grids() -> None:
    box = box_geometry(subdivisions_x=5, subdivisions_y=5, subdivisions_z=5)
    box_reduced = unsubdivide_geometry(box, iterations=1)
    assert box_reduced.triangle_count == 108
    assert box_reduced.triangle_count < box.triangle_count
    assert np.all(_triangle_areas(box_reduced) > 1.0e-10)

    ribbon = ribbon_geometry(length_segments=16, width_segments=4)
    ribbon_reduced = unsubdivide_geometry(ribbon, iterations=1)
    assert ribbon_reduced.triangle_count == 32
    assert ribbon_reduced.triangle_count < ribbon.triangle_count
    assert np.all(_triangle_areas(ribbon_reduced) > 1.0e-10)


def test_unsubdivide_error_directs_scanned_meshes_to_decimate() -> None:
    source = box_geometry()
    randomised = source.copy()
    randomised.indices = randomised.indices[::-1].copy()
    with pytest.raises(ValueError, match="use Geometry Decimate"):
        unsubdivide_geometry(randomised, iterations=1)
