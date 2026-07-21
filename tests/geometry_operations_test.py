from __future__ import annotations

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
from vfx_texture_lab.engine.evaluator import GraphSnapshot, SnapshotNode
from vfx_texture_lab.geometry import (
    box_geometry,
    combine_geometry,
    cylinder_geometry,
    displace_geometry,
    export_obj,
    plane_geometry,
)
from vfx_texture_lab.geometry_graph import GeometryEvaluationSession
from vfx_texture_lab.graph import GraphScene
from vfx_texture_lab.nodes.registry import build_registry



class _FrameImageEvaluator:
    def __init__(self) -> None:
        self.kwargs = {}

    @staticmethod
    def _resolve_graph_output_proxy(snapshot, uid, output):
        return uid, output

    @staticmethod
    def _expand_graph_instances(snapshot, uid, output):
        return snapshot, uid, output

    def evaluate(self, _uid, width, height, **kwargs):
        from types import SimpleNamespace

        self.kwargs = dict(kwargs)
        value = float(kwargs.get("normalised_time", 0.0))
        image = np.full((height, width, 4), value, dtype=np.float32)
        image[..., 3] = 1.0
        return SimpleNamespace(image=image, error=None)

def _assert_valid_triangles(geometry) -> None:
    triangles = geometry.indices.reshape(-1, 3)
    points = geometry.vertices[:, :3]
    p0 = points[triangles[:, 0]]
    p1 = points[triangles[:, 1]]
    p2 = points[triangles[:, 2]]
    areas = np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1)
    assert np.all(areas > 1.0e-8)


def test_geometry_operations(tmp_path: Path) -> None:
    registry = build_registry()
    combine_definition = registry.get("geometry.combine")
    displace_definition = registry.get("geometry.displace")
    cylinder_definition = registry.get("geometry.cylinder")

    assert combine_definition.input_kind("Top Geometry") == "geometry"
    assert combine_definition.input_kind("Bottom Geometry") == "geometry"
    assert combine_definition.output_kind("Geometry") == "geometry"
    assert displace_definition.input_kind("Geometry") == "geometry"
    assert displace_definition.input_kind("Height") == "grayscale"
    assert displace_definition.output_kind("Geometry") == "geometry"
    assert cylinder_definition.parameter_spec("top_radius_offset") is not None
    assert cylinder_definition.parameter_spec("bottom_radius_offset") is not None

    frame_evaluator = _FrameImageEvaluator()
    plane_snapshot = SnapshotNode(
        "plane", registry.get("geometry.plane"),
        {**registry.get("geometry.plane").default_parameters(), "subdivisions_x": 1, "subdivisions_y": 1},
    )
    height_snapshot = SnapshotNode(
        "height", registry.get("generator.constant"), registry.get("generator.constant").default_parameters()
    )
    displace_snapshot = SnapshotNode(
        "displace", displace_definition,
        {**displace_definition.default_parameters(), "amount": 2.0},
    )
    frame_snapshot = GraphSnapshot(
        {"plane": plane_snapshot, "height": height_snapshot, "displace": displace_snapshot},
        {
            ("displace", "Geometry"): ("plane", "Geometry"),
            ("displace", "Height"): ("height", "Image"),
        },
    )
    frame_result = GeometryEvaluationSession(
        frame_evaluator, frame_snapshot, 8, 8,
        frame_number=90, frame_position=90.5, normalised_time=0.75, loop_phase=0.5,
    ).evaluate("displace", "Geometry")
    assert frame_result.error is None, frame_result.error
    assert frame_result.geometry is not None
    assert np.allclose(frame_result.geometry.vertices[:, 1], 1.5)
    assert frame_evaluator.kwargs["frame_number"] == 90
    assert np.isclose(frame_evaluator.kwargs["frame_position"], 90.5)
    assert np.isclose(frame_evaluator.kwargs["normalised_time"], 0.75)

    bottom = box_geometry(
        width=2.0,
        height=1.0,
        depth=2.0,
        subdivisions_x=1,
        subdivisions_y=1,
        subdivisions_z=1,
        origin_y=-1.0,
        name="Bottom",
    )
    top = plane_geometry(
        width=3.0,
        height=3.0,
        subdivisions_x=2,
        subdivisions_y=2,
        orientation="Horizontal (XZ)",
        origin_y=0.0,
        name="Top",
    )
    combined = combine_geometry(bottom, top)
    assert combined.vertex_count == bottom.vertex_count + top.vertex_count
    assert combined.triangle_count == bottom.triangle_count + top.triangle_count
    assert np.array_equal(combined.vertices[: bottom.vertex_count], bottom.vertices)
    assert np.array_equal(combined.vertices[bottom.vertex_count :], top.vertices)
    assert np.array_equal(combined.indices[: bottom.indices.size], bottom.indices)
    assert np.array_equal(
        combined.indices[bottom.indices.size :], top.indices + bottom.vertex_count
    )

    heightmap = np.full((8, 8, 4), 0.5, dtype=np.float32)
    heightmap[..., 3] = 1.0
    displaced = displace_geometry(top, heightmap, amount=2.0)
    assert displaced.vertex_count == top.vertex_count
    assert displaced.triangle_count == top.triangle_count
    assert np.allclose(displaced.vertices[:, 1], top.vertices[:, 1] + 1.0)
    assert np.array_equal(displaced.vertices[:, 3:8], top.vertices[:, 3:8])
    assert np.array_equal(displaced.indices, top.indices)

    gradient = np.zeros((16, 16, 4), dtype=np.float32)
    coordinate = np.linspace(0.0, 1.0, 16, endpoint=False, dtype=np.float32)
    gradient[..., 0] = (np.sin(np.pi * coordinate) ** 2)[None, :]
    gradient[..., 3] = 1.0
    sloped = displace_geometry(top, gradient, amount=0.5)
    assert np.array_equal(sloped.vertices[:, 3:6], top.vertices[:, 3:6])
    assert not np.allclose(sloped.vertices[:, :3], top.vertices[:, :3])

    # Positive top offset produces a frustum whose upper ring is wider.
    frustum = cylinder_geometry(
        radius=1.0,
        height=2.0,
        radial_segments=8,
        height_segments=2,
        top_radius_offset=1.0,
        bottom_radius_offset=0.0,
        caps=False,
    )
    row = 9
    lower_radius = np.linalg.norm(frustum.vertices[0, (0, 2)])
    upper_radius = np.linalg.norm(frustum.vertices[2 * row, (0, 2)])
    assert np.isclose(lower_radius, 1.0)
    assert np.isclose(upper_radius, 2.0)
    assert np.all(frustum.vertices[:row, 4] < 0.0)
    _assert_valid_triangles(frustum)

    # A negative offset may collapse an end to a genuine cone tip. The special
    # tip topology emits one triangle per segment instead of degenerate quads.
    cone = cylinder_geometry(
        radius=2.0,
        height=2.0,
        radial_segments=8,
        height_segments=2,
        top_radius_offset=-2.0,
        caps=True,
        cap_segments=1,
    )
    top_ring = cone.vertices[2 * row : 3 * row, :3]
    assert np.allclose(top_ring[:, (0, 2)], 0.0)
    assert cone.vertex_count == 37
    assert cone.triangle_count == 32
    _assert_valid_triangles(cone)

    app = QApplication.instance() or QApplication([])
    scene = GraphScene(registry)
    plane = scene.create_node(
        "geometry.plane",
        QPointF(0, 0),
        parameters={"subdivisions_x": 2, "subdivisions_y": 2},
        record_undo=False,
    )
    constant = scene.create_node(
        "generator.constant",
        QPointF(0, 220),
        parameters={"value": 0.5},
        record_undo=False,
    )
    displace = scene.create_node(
        "geometry.displace",
        QPointF(300, 0),
        parameters={"amount": 2.0},
        record_undo=False,
    )
    box = scene.create_node(
        "geometry.box",
        QPointF(300, 240),
        parameters={"width": 1.0, "height": 1.0, "depth": 1.0},
        record_undo=False,
    )
    combine = scene.create_node("geometry.combine", QPointF(600, 0), record_undo=False)
    output = scene.create_node("output.geometry", QPointF(900, 0), record_undo=False)

    assert scene.add_connection(
        plane.output_ports["Geometry"], displace.input_ports["Geometry"], record_undo=False
    )
    assert scene.add_connection(
        constant.output_port, displace.input_ports["Height"], record_undo=False
    )
    assert scene.add_connection(
        displace.output_ports["Geometry"], combine.input_ports["Top Geometry"], record_undo=False
    )
    assert scene.add_connection(
        box.output_ports["Geometry"], combine.input_ports["Bottom Geometry"], record_undo=False
    )
    assert scene.add_connection(
        combine.output_ports["Geometry"], output.input_ports["Geometry"], record_undo=False
    )

    color = scene.create_node("generator.color", QPointF(0, 400), record_undo=False)
    ok, reason = scene.can_connect(color.output_port, displace.input_ports["Height"])
    assert not ok and "Greyscale" in reason

    snapshot = GraphSnapshot.from_scene(scene)
    evaluator = GraphEvaluator(scene, backend_preference="cpu")
    result = GeometryEvaluationSession(
        evaluator,
        snapshot,
        32,
        32,
        render_mode="preview_3d",
    ).evaluate(output.uid, "Geometry")
    assert result.error is None, result.error
    assert result.geometry is not None
    assert result.geometry.vertex_count == 9 + 24
    assert result.geometry.triangle_count == 8 + 12
    assert np.allclose(result.geometry.vertices[24:, 1], 1.0)

    restored = GraphScene(build_registry())
    restored.from_dict(scene.to_dict())
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

    exported = export_obj(result.geometry, tmp_path / "combined_displaced.obj")
    text = exported.read_text(encoding="utf-8")
    assert text.count("\nv ") == result.geometry.vertex_count
    assert text.count("\nf ") == result.geometry.triangle_count
    assert text.count("\no ") == 1

    del app


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        test_geometry_operations(Path(directory))
    print("geometry operations test passed")
