from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vfx_texture_lab.geometry import (
    GeometryData,
    bend_geometry,
    box_geometry,
    clean_weld_geometry,
    ribbon_geometry,
    twist_geometry,
    uv_transform_geometry,
)
from vfx_texture_lab.nodes.registry import build_registry


def _face_alignment(geometry: GeometryData) -> np.ndarray:
    triangles = geometry.indices.reshape(-1, 3)
    positions = geometry.vertices[:, :3]
    face = np.cross(
        positions[triangles[:, 1]] - positions[triangles[:, 0]],
        positions[triangles[:, 2]] - positions[triangles[:, 0]],
    )
    return np.einsum("ij,ij->i", face, geometry.vertices[triangles[:, 0], 3:6])


def main() -> None:
    registry = build_registry()
    expected = {
        "geometry.ribbon": False,
        "geometry.bend": True,
        "geometry.twist": True,
        "geometry.uv_transform": True,
        "geometry.clean_weld": True,
    }
    for type_id, has_input in expected.items():
        definition = registry.get(type_id)
        assert definition.output_kind("Geometry") == "geometry"
        assert definition.geometry_evaluator is not None
        if has_input:
            assert definition.input_kind("Geometry") == "geometry"

    for orientation in (
        "Horizontal (XZ)",
        "Vertical (XY)",
        "Vertical (YZ)",
    ):
        ribbon = ribbon_geometry(
            length=4.0,
            width_start=2.0,
            width_end=0.5,
            length_segments=4,
            width_segments=2,
            orientation=orientation,
            uv_tiles_u=2,
            uv_tiles_v=3,
        )
        assert ribbon.vertex_count == 15
        assert ribbon.triangle_count == 16
        assert np.all(_face_alignment(ribbon) > 1.0e-8)
        assert np.allclose(ribbon.vertices[:, 6:8].min(axis=0), (0.0, 0.0))
        assert np.allclose(ribbon.vertices[:, 6:8].max(axis=0), (2.0, 3.0))

    pointed = ribbon_geometry(
        length=4.0, width_start=1.5, width_end=0.0,
        length_segments=4, width_segments=3,
    )
    pointed_triangles = pointed.indices.reshape(-1, 3)
    pointed_positions = pointed.vertices[:, :3]
    pointed_area = np.linalg.norm(
        np.cross(
            pointed_positions[pointed_triangles[:, 1]] - pointed_positions[pointed_triangles[:, 0]],
            pointed_positions[pointed_triangles[:, 2]] - pointed_positions[pointed_triangles[:, 0]],
        ),
        axis=1,
    )
    assert pointed.triangle_count == 21
    assert np.all(pointed_area > 1.0e-8)
    assert np.all(_face_alignment(pointed) > 1.0e-8)

    ribbon = ribbon_geometry(
        length=4.0,
        width_start=1.0,
        width_end=1.0,
        length_segments=32,
        width_segments=2,
    )
    bent = bend_geometry(
        ribbon,
        amount=120.0,
        deformation_axis="Axis Z",
        direction=25.0,
        pivot_mode="Current Origin",
    )
    assert bent.vertex_count == ribbon.vertex_count
    assert bent.triangle_count == ribbon.triangle_count
    assert np.array_equal(bent.indices, ribbon.indices)
    assert np.array_equal(bent.vertices[:, 6:8], ribbon.vertices[:, 6:8])
    assert not np.allclose(bent.vertices[:, :3], ribbon.vertices[:, :3])
    assert np.allclose(np.linalg.norm(bent.vertices[:, 3:6], axis=1), 1.0, atol=1.0e-5)
    assert np.all(_face_alignment(bent) > 1.0e-7)

    partial = bend_geometry(
        ribbon,
        amount=90.0,
        deformation_axis="Axis Z",
        range_start=0.25,
        range_end=0.75,
        clamp_outside=True,
    )
    original_z = ribbon.vertices[:, 2]
    untouched = original_z <= -1.0 + 1.0e-6
    assert np.allclose(partial.vertices[untouched, :3], ribbon.vertices[untouched, :3])

    twisted = twist_geometry(
        ribbon,
        amount=180.0,
        axis="Axis Z",
        pivot_mode="Current Origin",
    )
    assert np.array_equal(twisted.indices, ribbon.indices)
    assert np.array_equal(twisted.vertices[:, 6:8], ribbon.vertices[:, 6:8])
    assert np.allclose(np.linalg.norm(twisted.vertices[:, 3:6], axis=1), 1.0, atol=1.0e-5)
    assert np.all(_face_alignment(twisted) > 1.0e-7)
    start = np.isclose(ribbon.vertices[:, 2], ribbon.vertices[:, 2].min())
    end = np.isclose(ribbon.vertices[:, 2], ribbon.vertices[:, 2].max())
    assert np.allclose(twisted.vertices[start, :3], ribbon.vertices[start, :3], atol=1.0e-5)
    assert np.allclose(twisted.vertices[end, 0], -ribbon.vertices[end, 0], atol=1.0e-5)

    transformed_uv = uv_transform_geometry(
        ribbon,
        scale_u=2.0,
        scale_v=0.5,
        offset_u=0.25,
        offset_v=-0.5,
        rotation=90.0,
        pivot_u=0.5,
        pivot_v=0.5,
        flip_u=True,
        swap_uv=True,
    )
    assert np.array_equal(transformed_uv.vertices[:, :6], ribbon.vertices[:, :6])
    assert np.array_equal(transformed_uv.indices, ribbon.indices)
    assert not np.allclose(transformed_uv.vertices[:, 6:8], ribbon.vertices[:, 6:8])

    box = box_geometry(2.0, 2.0, 2.0)
    preserved = clean_weld_geometry(box)
    assert preserved.vertex_count == box.vertex_count
    assert preserved.triangle_count == box.triangle_count
    welded = clean_weld_geometry(
        box,
        preserve_uv_seams=False,
        preserve_hard_edges=False,
    )
    assert welded.vertex_count == 8
    assert welded.triangle_count == box.triangle_count
    assert np.allclose(np.linalg.norm(welded.vertices[:, 3:6], axis=1), 1.0)

    # Cleanup must remove both an unused vertex and triangles collapsed by
    # duplicate indices or zero area.
    vertices = np.asarray(
        [
            [0, 0, 0, 0, 1, 0, 0, 0],
            [1, 0, 0, 0, 1, 0, 1, 0],
            [0, 0, 1, 0, 1, 0, 0, 1],
            [5, 5, 5, 0, 1, 0, 0, 0],
        ],
        dtype=np.float32,
    )
    dirty = GeometryData(vertices, np.asarray((0, 2, 1, 0, 0, 1), dtype=np.uint32))
    cleaned = clean_weld_geometry(dirty)
    assert cleaned.vertex_count == 3
    assert cleaned.triangle_count == 1

    print(
        "geometry shaping test passed: Ribbon, Bend, Twist, UV Transform and "
        "Clean/Weld are typed, preserve topology/attributes where intended, and "
        "follow existing geometry generator conventions"
    )


if __name__ == "__main__":
    main()
