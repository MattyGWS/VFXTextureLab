from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.engine import GraphEvaluator
from vfx_texture_lab.engine.evaluator import GraphSnapshot
from vfx_texture_lab.geometry import (
    box_geometry,
    disc_ring_geometry,
    displace_geometry,
    export_obj,
    normals_geometry,
    plane_geometry,
    subdivide_geometry,
    transform_geometry,
)
from vfx_texture_lab.geometry_graph import GeometryEvaluationSession
from vfx_texture_lab.graph import GraphScene
from vfx_texture_lab.nodes.registry import build_registry


def _triangle_areas(geometry) -> np.ndarray:
    triangles = geometry.indices.reshape(-1, 3)
    points = geometry.vertices[:, :3]
    p0 = points[triangles[:, 0]]
    p1 = points[triangles[:, 1]]
    p2 = points[triangles[:, 2]]
    return np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1) * 0.5


def _assert_valid_winding(geometry) -> None:
    triangles = geometry.indices.reshape(-1, 3)
    points = geometry.vertices[:, :3]
    p0 = points[triangles[:, 0]]
    p1 = points[triangles[:, 1]]
    p2 = points[triangles[:, 2]]
    face = np.cross(p1 - p0, p2 - p0)
    dots = np.einsum("ij,ij->i", face, geometry.vertices[triangles[:, 0], 3:6])
    assert np.all(dots > 1.0e-8)


def test_geometry_toolkit(tmp_path: Path) -> None:
    registry = build_registry()
    transform_definition = registry.get("geometry.transform")
    subdivide_definition = registry.get("geometry.subdivide")
    normals_definition = registry.get("geometry.normals")
    disc_definition = registry.get("geometry.disc_ring")
    displace_definition = registry.get("geometry.displace")

    for definition in (
        transform_definition,
        subdivide_definition,
        normals_definition,
    ):
        assert definition.input_kind("Geometry") == "geometry"
        assert definition.output_kind("Geometry") == "geometry"
        assert definition.geometry_evaluator is not None
    assert disc_definition.output_kind("Geometry") == "geometry"
    assert disc_definition.geometry_evaluator is not None
    assert "preserving" in displace_definition.description.lower()

    # Transform around the authored origin versus the current bounds centre.
    grounded_box = box_geometry(width=2.0, height=2.0, depth=2.0, origin_y=-1.0)
    origin_rotation = transform_geometry(grounded_box, rotation_z=90.0)
    centre_rotation = transform_geometry(
        grounded_box, rotation_z=90.0, pivot_mode="Bounds Centre"
    )
    assert np.allclose(origin_rotation.bounds[0], (-2.0, -1.0, -1.0), atol=1.0e-5)
    assert np.allclose(origin_rotation.bounds[1], (0.0, 1.0, 1.0), atol=1.0e-5)
    assert np.allclose(centre_rotation.bounds[0], (-1.0, 0.0, -1.0), atol=1.0e-5)
    assert np.allclose(centre_rotation.bounds[1], (1.0, 2.0, 1.0), atol=1.0e-5)

    mirrored = transform_geometry(
        grounded_box,
        translate_x=3.0,
        rotation_y=37.0,
        uniform_scale=1.25,
        scale_x=-2.0,
        scale_y=0.75,
        scale_z=0.5,
    )
    assert np.allclose(np.linalg.norm(mirrored.vertices[:, 3:6], axis=1), 1.0)
    _assert_valid_winding(mirrored)

    # Shape-preserving subdivision must add topology without changing bounds,
    # UV range, or the original plane normals.
    plane = plane_geometry(2.0, 2.0, 1, 1)
    subdivided = subdivide_geometry(plane, levels=2, smooth_surface=False)
    assert subdivided.vertex_count == 25
    assert subdivided.triangle_count == 32
    assert np.allclose(subdivided.bounds[0], plane.bounds[0])
    assert np.allclose(subdivided.bounds[1], plane.bounds[1])
    assert np.allclose(subdivided.vertices[:, 3:6], (0.0, 1.0, 0.0))
    assert np.allclose(subdivided.vertices[:, 6:8].min(axis=0), (0.0, 0.0))
    assert np.allclose(subdivided.vertices[:, 6:8].max(axis=0), (1.0, 1.0))
    assert np.all(_triangle_areas(subdivided) > 1.0e-8)

    dense_box = subdivide_geometry(grounded_box, levels=1, smooth_surface=False)
    smoothed_box = subdivide_geometry(grounded_box, levels=1, smooth_surface=True)
    assert dense_box.triangle_count == smoothed_box.triangle_count == 48
    assert not np.allclose(dense_box.vertices[:, :3], smoothed_box.vertices[:, :3])
    assert np.allclose(np.linalg.norm(smoothed_box.vertices[:, 3:6], axis=1), 1.0)
    assert np.all(_triangle_areas(smoothed_box) > 1.0e-8)

    # Normals are now an explicit operation. Smooth mode welds shading across
    # duplicate UV/hard-edge vertices at the same position; Flat and angle modes
    # split per-corner data where one position needs several normals.
    smooth = normals_geometry(grounded_box, mode="Smooth")
    corner = np.all(np.isclose(smooth.vertices[:, :3], (-1.0, 0.0, -1.0)), axis=1)
    assert int(corner.sum()) == 3
    assert np.allclose(smooth.vertices[corner, 3:6], smooth.vertices[corner][0, 3:6])
    assert np.allclose(np.linalg.norm(smooth.vertices[:, 3:6], axis=1), 1.0)

    flat = normals_geometry(grounded_box, mode="Flat")
    assert flat.vertex_count == grounded_box.triangle_count * 3
    assert flat.triangle_count == grounded_box.triangle_count
    for triangle in flat.indices.reshape(-1, 3):
        triangle_normals = flat.vertices[triangle, 3:6]
        assert np.allclose(triangle_normals, triangle_normals[0])
    _assert_valid_winding(flat)

    hard_angle = normals_geometry(
        grounded_box, mode="Smoothing Angle", smoothing_angle=30.0
    )
    soft_angle = normals_geometry(
        grounded_box, mode="Smoothing Angle", smoothing_angle=120.0
    )
    assert hard_angle.vertex_count == soft_angle.vertex_count == grounded_box.triangle_count * 3
    hard_unique = np.unique(np.round(hard_angle.vertices[:, 3:6], 5), axis=0)
    soft_unique = np.unique(np.round(soft_angle.vertices[:, 3:6], 5), axis=0)
    assert len(hard_unique) == 6
    assert len(soft_unique) == 8

    reversed_and_flipped = normals_geometry(
        grounded_box, mode="Flat", reverse_winding=True, flip_normals=True
    )
    # Reversing winding rebuilds normals for the reversed faces; flipping them
    # once more deliberately makes them point against the new front faces.
    triangles = reversed_and_flipped.indices.reshape(-1, 3)
    points = reversed_and_flipped.vertices[:, :3]
    face = np.cross(
        points[triangles[:, 1]] - points[triangles[:, 0]],
        points[triangles[:, 2]] - points[triangles[:, 0]],
    )
    dots = np.einsum(
        "ij,ij->i", face, reversed_and_flipped.vertices[triangles[:, 0], 3:6]
    )
    assert np.all(dots < -1.0e-8)

    # Disc and ring topology, UV layouts, arc support, origin/rotation and
    # orientation all share the existing generator conventions.
    ring = disc_ring_geometry(
        outer_radius=2.0,
        inner_radius=1.0,
        radial_segments=8,
        ring_segments=2,
        uv_mode="Radial Strip",
        uv_tiles_u=4,
        uv_tiles_v=2,
    )
    assert ring.vertex_count == 27
    assert ring.triangle_count == 32
    assert np.allclose(ring.vertices[:, 6:8].min(axis=0), (0.0, 0.0))
    assert np.allclose(ring.vertices[:, 6:8].max(axis=0), (4.0, 2.0))
    assert np.all(_triangle_areas(ring) > 1.0e-8)
    _assert_valid_winding(ring)

    disc = disc_ring_geometry(
        outer_radius=2.0,
        inner_radius=0.0,
        radial_segments=8,
        ring_segments=2,
        arc_start=45.0,
        arc_spread=180.0,
        uv_mode="Planar",
        orientation="Axis X",
        origin_x=-1.0,
        rotation_x=30.0,
    )
    assert disc.vertex_count == 26
    assert disc.triangle_count == 24
    assert np.all(_triangle_areas(disc) > 1.0e-8)
    assert np.allclose(np.linalg.norm(disc.vertices[:, 3:6], axis=1), 1.0)
    _assert_valid_winding(disc)

    # Geometry Displace must now preserve incoming normals exactly, even when
    # the resulting surface slope changes.
    gradient = np.zeros((32, 32, 4), dtype=np.float32)
    gradient[..., 0] = np.linspace(0.0, 1.0, 32, dtype=np.float32)[None, :]
    gradient[..., 3] = 1.0
    displaced = displace_geometry(subdivided, gradient, amount=0.75)
    assert not np.allclose(displaced.vertices[:, :3], subdivided.vertices[:, :3])
    assert np.array_equal(displaced.vertices[:, 3:6], subdivided.vertices[:, 3:6])
    rebuilt = normals_geometry(displaced, mode="Smooth")
    assert not np.allclose(rebuilt.vertices[:, 3:6], displaced.vertices[:, 3:6])

    # Real typed graph integration: Disc -> Transform -> Subdivide -> Displace
    # -> Normals -> Combine -> one Geometry Output, including save/load/export.
    app = QApplication.instance() or QApplication([])
    scene = GraphScene(registry)
    disc_node = scene.create_node(
        "geometry.disc_ring",
        QPointF(0, 0),
        parameters={
            "inner_radius": 0.5,
            "radial_segments": 8,
            "ring_segments": 1,
            "uv_mode": "Radial Strip",
        },
        record_undo=False,
    )
    transform_node = scene.create_node(
        "geometry.transform",
        QPointF(240, 0),
        parameters={"translate_y": 0.5, "rotation_x": 20.0, "scale_x": 1.5},
        record_undo=False,
    )
    subdivide_node = scene.create_node(
        "geometry.subdivide",
        QPointF(480, 0),
        parameters={"levels": 1, "smooth_surface": False},
        record_undo=False,
    )
    constant = scene.create_node(
        "generator.constant",
        QPointF(480, 220),
        parameters={"value": 0.25},
        record_undo=False,
    )
    displace_node = scene.create_node(
        "geometry.displace",
        QPointF(720, 0),
        parameters={"amount": 0.4},
        record_undo=False,
    )
    normals_node = scene.create_node(
        "geometry.normals",
        QPointF(960, 0),
        parameters={"mode": "Smooth"},
        record_undo=False,
    )
    box_node = scene.create_node(
        "geometry.box",
        QPointF(960, 240),
        parameters={"width": 0.5, "height": 0.5, "depth": 0.5},
        record_undo=False,
    )
    combine_node = scene.create_node("geometry.combine", QPointF(1200, 0), record_undo=False)
    output_node = scene.create_node("output.geometry", QPointF(1440, 0), record_undo=False)

    assert scene.add_connection(disc_node.output_ports["Geometry"], transform_node.input_ports["Geometry"], record_undo=False)
    assert scene.add_connection(transform_node.output_ports["Geometry"], subdivide_node.input_ports["Geometry"], record_undo=False)
    assert scene.add_connection(subdivide_node.output_ports["Geometry"], displace_node.input_ports["Geometry"], record_undo=False)
    assert scene.add_connection(constant.output_port, displace_node.input_ports["Height"], record_undo=False)
    assert scene.add_connection(displace_node.output_ports["Geometry"], normals_node.input_ports["Geometry"], record_undo=False)
    assert scene.add_connection(normals_node.output_ports["Geometry"], combine_node.input_ports["Top Geometry"], record_undo=False)
    assert scene.add_connection(box_node.output_ports["Geometry"], combine_node.input_ports["Bottom Geometry"], record_undo=False)
    assert scene.add_connection(combine_node.output_ports["Geometry"], output_node.input_ports["Geometry"], record_undo=False)

    noise = scene.create_node("noise.perlin", QPointF(0, 400), record_undo=False)
    ok, reason = scene.can_connect(noise.output_port, transform_node.input_ports["Geometry"])
    assert not ok and "Geometry" in reason
    ok, reason = scene.can_connect(disc_node.output_ports["Geometry"], displace_node.input_ports["Height"])
    assert not ok and ("image" in reason.lower() or "Greyscale" in reason)

    result = GeometryEvaluationSession(
        GraphEvaluator(scene, backend_preference="cpu"),
        GraphSnapshot.from_scene(scene),
        32,
        32,
        render_mode="preview_3d",
    ).evaluate(output_node.uid, "Geometry")
    assert result.error is None, result.error
    assert result.geometry is not None
    assert result.geometry.triangle_count == 16 * 4 + 12
    assert np.all(_triangle_areas(result.geometry) > 1.0e-8)

    data = json.loads(json.dumps(scene.to_dict()))
    restored = GraphScene(build_registry())
    restored.from_dict(data)
    restored_output = next(
        node for node in restored.nodes.values() if node.definition.type_id == "output.geometry"
    )
    restored_result = GeometryEvaluationSession(
        GraphEvaluator(restored, backend_preference="cpu"),
        GraphSnapshot.from_scene(restored),
        32,
        32,
    ).evaluate(restored_output.uid, "Geometry")
    assert restored_result.error is None, restored_result.error
    assert restored_result.geometry is not None
    assert restored_result.geometry.vertex_count == result.geometry.vertex_count
    assert restored_result.geometry.triangle_count == result.geometry.triangle_count

    export_path = export_obj(restored_result.geometry, tmp_path / "geometry_toolkit.obj")
    exported = export_path.read_text(encoding="utf-8")
    assert exported.count("\no ") == 1
    assert exported.count("\nv ") == restored_result.geometry.vertex_count
    assert exported.count("\nf ") == restored_result.geometry.triangle_count
    del app


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        test_geometry_toolkit(Path(directory))
    print("geometry toolkit test passed")
