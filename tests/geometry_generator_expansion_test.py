from __future__ import annotations

from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np

from vfx_texture_lab.geometry import box_geometry, cylinder_geometry, export_obj, plane_geometry
from vfx_texture_lab.nodes.registry import build_registry


def _triangle_normal(vertices: np.ndarray, triangle: np.ndarray) -> np.ndarray:
    points = vertices[triangle, :3]
    normal = np.cross(points[1] - points[0], points[2] - points[0])
    length = np.linalg.norm(normal)
    return normal / max(float(length), 1.0e-8)


def _assert_triangle_winding_matches_normals(vertices: np.ndarray, indices: np.ndarray) -> None:
    triangles = indices.reshape(-1, 3)
    step = max(len(triangles) // 24, 1)
    for triangle in triangles[::step]:
        face_normal = _triangle_normal(vertices, triangle)
        vertex_normal = vertices[triangle[0], 3:6]
        assert float(np.dot(face_normal, vertex_normal)) > 0.0


def test_geometry_generator_expansion(tmp_path: Path) -> None:
    registry = build_registry()
    plane_definition = registry.get("geometry.plane")
    box_definition = registry.get("geometry.box")
    cylinder_definition = registry.get("geometry.cylinder")
    output_definition = registry.get("output.geometry")

    assert plane_definition.output_kind("Geometry") == "geometry"
    assert box_definition.output_kind("Geometry") == "geometry"
    assert cylinder_definition.output_kind("Geometry") == "geometry"
    assert output_definition.input_kind("Geometry") == "geometry"
    assert plane_definition.geometry_evaluator is not None
    assert box_definition.geometry_evaluator is not None
    assert cylinder_definition.geometry_evaluator is not None

    plane = plane_geometry(
        width=4.0,
        height=2.0,
        subdivisions_x=2,
        subdivisions_y=1,
        orientation="Horizontal (XZ)",
        origin_x=-1.0,
        origin_z=-1.0,
        uv_tiles_u=3,
        uv_tiles_v=2,
        name="Test Plane",
    )
    assert plane.vertex_count == 6
    assert plane.triangle_count == 4
    minimum, maximum = plane.bounds
    assert np.allclose(minimum, (0.0, 0.0, 0.0))
    assert np.allclose(maximum, (4.0, 0.0, 2.0))
    assert np.allclose(plane.vertices[:, 6:8].min(axis=0), (0.0, 0.0))
    assert np.allclose(plane.vertices[:, 6:8].max(axis=0), (3.0, 2.0))

    box = box_geometry(
        width=4.0,
        height=2.0,
        depth=6.0,
        subdivisions_x=2,
        subdivisions_y=1,
        subdivisions_z=3,
        origin_x=-1.0,
        origin_y=-1.0,
        origin_z=-1.0,
        uv_tiles_u=4,
        uv_tiles_v=2,
        name="Test Box",
    )
    assert box.vertex_count == 52
    assert box.triangle_count == 44
    minimum, maximum = box.bounds
    assert np.allclose(minimum, (0.0, 0.0, 0.0))
    assert np.allclose(maximum, (4.0, 2.0, 6.0))
    assert np.allclose(box.vertices[:, 6:8].min(axis=0), (0.0, 0.0))
    assert np.allclose(box.vertices[:, 6:8].max(axis=0), (4.0, 2.0))
    unique_normals = np.unique(np.round(box.vertices[:, 3:6], 6), axis=0)
    assert len(unique_normals) == 6
    _assert_triangle_winding_matches_normals(box.vertices, box.indices)

    smooth_cylinder = cylinder_geometry(
        radius=1.25,
        height=3.0,
        radial_segments=8,
        height_segments=2,
        caps=True,
        cap_segments=2,
        smooth_sides=True,
        orientation="Axis Z",
        origin_x=-1.0,
        origin_y=-1.0,
        origin_z=-1.0,
        uv_tiles_u=4,
        uv_tiles_v=3,
        name="Test Cylinder",
    )
    assert smooth_cylinder.vertex_count == 65
    assert smooth_cylinder.triangle_count == 80
    minimum, maximum = smooth_cylinder.bounds
    assert np.allclose(minimum, (0.0, 0.0, 0.0))
    assert np.allclose(maximum, (2.5, 2.5, 3.0))
    assert np.allclose(smooth_cylinder.vertices[:, 6:8].min(axis=0), (0.0, 0.0))
    assert np.allclose(smooth_cylinder.vertices[:, 6:8].max(axis=0), (4.0, 3.0))
    row = 9
    for ring in range(3):
        start = ring * row
        assert np.allclose(smooth_cylinder.vertices[start, :3], smooth_cylinder.vertices[start + 8, :3])
        assert np.allclose(smooth_cylinder.vertices[start, 3:6], smooth_cylinder.vertices[start + 8, 3:6])
        assert np.isclose(smooth_cylinder.vertices[start, 6], 0.0)
        assert np.isclose(smooth_cylinder.vertices[start + 8, 6], 4.0)
    _assert_triangle_winding_matches_normals(smooth_cylinder.vertices, smooth_cylinder.indices)

    faceted_cylinder = cylinder_geometry(
        radius=0.75,
        height=2.0,
        radial_segments=5,
        height_segments=1,
        caps=False,
        smooth_sides=False,
        orientation="Axis Y",
        origin_x=0.0,
        origin_y=0.0,
        origin_z=0.0,
        uv_tiles_u=2,
        uv_tiles_v=2,
    )
    assert faceted_cylinder.vertex_count == 20
    assert faceted_cylinder.triangle_count == 10
    side_normals = np.unique(np.round(faceted_cylinder.vertices[:, 3:6], 6), axis=0)
    assert len(side_normals) == 5
    _assert_triangle_winding_matches_normals(faceted_cylinder.vertices, faceted_cylinder.indices)

    plane_parameters = plane_definition.default_parameters()
    plane_parameters.update(
        {
            "width": 4.0,
            "height": 2.0,
            "subdivisions_x": 2,
            "subdivisions_y": 1,
            "origin_x": -1.0,
            "origin_z": -1.0,
            "uv_tiles_u": 3,
            "uv_tiles_v": 2,
            "name": "Test Plane",
        }
    )
    evaluated_plane = plane_definition.geometry_evaluator({}, plane_parameters)
    assert evaluated_plane.vertex_count == 6
    assert evaluated_plane.triangle_count == 4

    box_parameters = box_definition.default_parameters()
    box_parameters.update(
        {
            "width": 4.0,
            "height": 2.0,
            "depth": 6.0,
            "subdivisions_x": 2,
            "subdivisions_y": 1,
            "subdivisions_z": 3,
            "origin_x": -1.0,
            "origin_y": -1.0,
            "origin_z": -1.0,
            "uv_tiles_u": 4,
            "uv_tiles_v": 2,
            "name": "Test Box",
        }
    )
    evaluated_box = box_definition.geometry_evaluator({}, box_parameters)
    assert evaluated_box.vertex_count == 52
    assert evaluated_box.triangle_count == 44

    cylinder_parameters = cylinder_definition.default_parameters()
    cylinder_parameters.update(
        {
            "radius": 1.25,
            "height": 3.0,
            "radial_segments": 8,
            "height_segments": 2,
            "caps": True,
            "cap_segments": 2,
            "smooth_sides": True,
            "orientation": "Axis Z",
            "origin_x": -1.0,
            "origin_y": -1.0,
            "origin_z": -1.0,
            "uv_tiles_u": 4,
            "uv_tiles_v": 3,
            "name": "Test Cylinder",
        }
    )
    evaluated_cylinder = cylinder_definition.geometry_evaluator({}, cylinder_parameters)
    assert evaluated_cylinder.vertex_count == 65
    assert evaluated_cylinder.triangle_count == 80

    export_path = export_obj(evaluated_box, tmp_path / "box.obj")
    text = export_path.read_text(encoding="utf-8")
    assert text.count("\nv ") == evaluated_box.vertex_count
    assert text.count("\nvt ") == evaluated_box.vertex_count
    assert text.count("\nvn ") == evaluated_box.vertex_count
    assert text.count("\nf ") == evaluated_box.triangle_count


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        test_geometry_generator_expansion(Path(directory))
    print("geometry generator expansion test passed")
