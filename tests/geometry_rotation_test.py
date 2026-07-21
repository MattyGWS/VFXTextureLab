from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np

from vfx_texture_lab.geometry import box_geometry, cylinder_geometry, plane_geometry
from vfx_texture_lab.nodes.registry import build_registry


def _contains_point(points: np.ndarray, expected: tuple[float, float, float], tolerance: float = 1.0e-5) -> bool:
    return bool(np.any(np.linalg.norm(points - np.asarray(expected, dtype=np.float32), axis=1) <= tolerance))


def _assert_unit_normals(vertices: np.ndarray) -> None:
    lengths = np.linalg.norm(vertices[:, 3:6], axis=1)
    assert np.allclose(lengths, 1.0, atol=1.0e-5)


def test_geometry_rotation() -> None:
    registry = build_registry()
    for type_id in ("geometry.plane", "geometry.box", "geometry.cylinder"):
        definition = registry.get(type_id)
        parameters = definition.default_parameters()
        assert parameters["rotation_x"] == 0.0
        assert parameters["rotation_y"] == 0.0
        assert parameters["rotation_z"] == 0.0
        for name in ("rotation_x", "rotation_y", "rotation_z"):
            spec = definition.parameter_spec(name)
            assert spec is not None
            assert spec.editor == "angle"
            assert spec.slider_minimum == -360.0
            assert spec.slider_maximum == 360.0

    # The Plane is first moved so its lower-left corner is the pivot. Rotating
    # around Y must leave that pivot at zero while turning +X into -Z.
    plane = plane_geometry(
        width=4.0,
        height=2.0,
        subdivisions_x=1,
        subdivisions_y=1,
        orientation="Horizontal (XZ)",
        origin_x=-1.0,
        origin_z=-1.0,
        rotation_y=90.0,
    )
    assert _contains_point(plane.vertices[:, :3], (0.0, 0.0, 0.0))
    minimum, maximum = plane.bounds
    assert np.allclose(minimum, (0.0, 0.0, -4.0), atol=1.0e-5)
    assert np.allclose(maximum, (2.0, 0.0, 0.0), atol=1.0e-5)
    assert np.allclose(plane.vertices[:, 3:6], (0.0, 1.0, 0.0), atol=1.0e-5)
    _assert_unit_normals(plane.vertices)

    # A Box rotated around its minimum corner must keep the chosen pivot fixed.
    box = box_geometry(
        width=4.0,
        height=2.0,
        depth=6.0,
        origin_x=-1.0,
        origin_y=-1.0,
        origin_z=-1.0,
        rotation_z=90.0,
    )
    assert _contains_point(box.vertices[:, :3], (0.0, 0.0, 0.0))
    minimum, maximum = box.bounds
    assert np.allclose(minimum, (-2.0, 0.0, 0.0), atol=1.0e-5)
    assert np.allclose(maximum, (0.0, 4.0, 6.0), atol=1.0e-5)
    _assert_unit_normals(box.vertices)
    unique_normals = np.unique(np.round(box.vertices[:, 3:6], 5), axis=0)
    assert len(unique_normals) == 6

    # A base-pivoted Y cylinder rotated around X should lie along +Z while its
    # base centre remains the world/export origin.
    cylinder = cylinder_geometry(
        radius=1.0,
        height=3.0,
        radial_segments=12,
        height_segments=2,
        caps=True,
        orientation="Axis Y",
        origin_y=-1.0,
        rotation_x=90.0,
    )
    assert _contains_point(cylinder.vertices[:, :3], (0.0, 0.0, 0.0))
    minimum, maximum = cylinder.bounds
    assert np.allclose(minimum, (-1.0, -1.0, 0.0), atol=1.0e-5)
    assert np.allclose(maximum, (1.0, 1.0, 3.0), atol=1.0e-5)
    _assert_unit_normals(cylinder.vertices)

    # Full-turn values are supported and must be equivalent to zero rotation.
    baseline = box_geometry(width=2.0, height=3.0, depth=4.0, origin_y=-1.0)
    full_turn = box_geometry(
        width=2.0,
        height=3.0,
        depth=4.0,
        origin_y=-1.0,
        rotation_x=360.0,
        rotation_y=-720.0,
        rotation_z=1080.0,
    )
    assert np.allclose(baseline.vertices, full_turn.vertices, atol=1.0e-5)
    assert np.array_equal(baseline.indices, full_turn.indices)

    # The registry evaluator forwards all three rotation parameters.
    parameters = registry.get("geometry.box").default_parameters()
    parameters.update({
        "width": 4.0,
        "height": 2.0,
        "depth": 6.0,
        "origin_x": -1.0,
        "origin_y": -1.0,
        "origin_z": -1.0,
        "rotation_z": 90.0,
    })
    evaluated = registry.get("geometry.box").geometry_evaluator({}, parameters)
    assert np.allclose(evaluated.bounds[0], (-2.0, 0.0, 0.0), atol=1.0e-5)
    assert np.allclose(evaluated.bounds[1], (0.0, 4.0, 6.0), atol=1.0e-5)


if __name__ == "__main__":
    test_geometry_rotation()
    print("geometry rotation test passed")
