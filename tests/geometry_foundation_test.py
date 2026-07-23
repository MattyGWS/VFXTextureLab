from __future__ import annotations

from pathlib import Path
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.engine import GraphEvaluator
from vfx_texture_lab.engine.evaluator import GraphSnapshot, SnapshotNode
from vfx_texture_lab.geometry import export_obj, plane_geometry
from vfx_texture_lab.geometry_graph import GeometryEvaluationSession, material_geometry_reference
from vfx_texture_lab.graph import GraphScene
from vfx_texture_lab.nodes.registry import build_registry


class _StructuralEvaluator:
    @staticmethod
    def _resolve_graph_output_proxy(snapshot, uid, output):
        return uid, output

    @staticmethod
    def _expand_graph_instances(snapshot, uid, output):
        return snapshot, uid, output


def test_geometry_foundation(tmp_path: Path) -> None:
    registry = build_registry()
    plane_definition = registry.get("geometry.plane")
    output_definition = registry.get("output.geometry")
    material_definition = registry.get("material.pbr")

    assert plane_definition.output_kind("Geometry") == "geometry"
    assert output_definition.input_kind("Geometry") == "geometry"
    assert material_definition.input_kind("Geometry") == "geometry"
    assert plane_definition.geometry_evaluator is not None

    parameters = plane_definition.default_parameters()
    parameters.update({"width": 4.0, "height": 2.0, "subdivisions_x": 4, "subdivisions_y": 2})
    plane = SnapshotNode("plane", plane_definition, parameters)
    output = SnapshotNode("output", output_definition, output_definition.default_parameters())
    material = SnapshotNode("material", material_definition, material_definition.default_parameters())
    snapshot = GraphSnapshot(
        {"plane": plane, "output": output, "material": material},
        {
            ("output", "Geometry"): ("plane", "Geometry"),
            ("material", "Geometry"): ("plane", "Geometry"),
        },
    )

    result = GeometryEvaluationSession(_StructuralEvaluator(), snapshot).evaluate("output", "Geometry")
    assert result.error is None
    assert result.geometry is not None
    assert result.geometry.vertex_count == 15
    assert result.geometry.triangle_count == 16
    assert result.node_metadata["plane"]["_geometry_output_vertex_count"] == 15
    assert result.node_metadata["plane"]["_geometry_output_triangle_count"] == 16
    assert result.node_metadata["output"]["_geometry_input_triangle_count"] == 16
    assert result.node_metadata["output"]["_geometry_output_triangle_count"] == 16
    assert np.allclose(result.geometry.vertices[:, 6:8].min(axis=0), (0.0, 0.0))
    assert np.allclose(result.geometry.vertices[:, 6:8].max(axis=0), (1.0, 1.0))
    assert np.allclose(result.geometry.vertices[:, 3:6], (0.0, 1.0, 0.0))
    first_triangle = result.geometry.indices[:3]
    positions = result.geometry.vertices[first_triangle, :3]
    face_normal = np.cross(positions[1] - positions[0], positions[2] - positions[0])
    assert float(np.dot(face_normal, result.geometry.vertices[first_triangle[0], 3:6])) > 0.0
    assert material_geometry_reference(snapshot, "material") == ("plane", "Geometry")

    path = export_obj(result.geometry, tmp_path / "plane.obj")
    text = path.read_text(encoding="utf-8")
    assert text.count("\nv ") == result.geometry.vertex_count
    assert text.count("\nvt ") == result.geometry.vertex_count
    assert text.count("\nvn ") == result.geometry.vertex_count
    assert text.count("\nf ") == result.geometry.triangle_count
    assert "f 1/1/1" in text

    for orientation, expected in (
        ("Horizontal (XZ)", (0.0, 1.0, 0.0)),
        ("Vertical (XY)", (0.0, 0.0, 1.0)),
        ("Vertical (YZ)", (1.0, 0.0, 0.0)),
    ):
        oriented = plane_geometry(2.0, 2.0, 1, 1, orientation)
        assert np.allclose(oriented.vertices[:, 3:6], expected)
        triangle = oriented.indices[:3]
        points = oriented.vertices[triangle, :3]
        face_normal = np.cross(points[1] - points[0], points[2] - points[0])
        assert float(np.dot(face_normal, oriented.vertices[triangle[0], 3:6])) > 0.0

    # Exercise the real graph scene contract, including strict typing, dynamic
    # geometry reroutes, graph persistence and evaluation after reload.
    app = QApplication.instance() or QApplication([])
    scene = GraphScene(registry)
    scene_plane = scene.create_node(
        "geometry.plane", QPointF(),
        parameters={"subdivisions_x": 3, "subdivisions_y": 2},
        record_undo=False,
    )
    scene_material = scene.create_node("material.pbr", QPointF(260, 0), record_undo=False)
    scene_output = scene.create_node("output.geometry", QPointF(520, 0), record_undo=False)
    reroute = scene.create_reroute(QPointF(260, 160), "geometry", record_undo=False)
    assert scene.add_connection(
        scene_plane.output_ports["Geometry"], reroute.input_ports["Input"], record_undo=False
    )
    noise = scene.create_node("noise.perlin", QPointF(0, 240), record_undo=False)

    assert scene.can_connect(scene_plane.output_ports["Geometry"], scene_material.input_ports["Geometry"])[0]
    ok, reason = scene.can_connect(scene_plane.output_ports["Geometry"], scene_material.input_ports["Base Colour"])
    assert not ok and "Geometry" in reason
    ok, reason = scene.can_connect(noise.output_port, scene_output.input_ports["Geometry"])
    assert not ok and "Geometry" in reason
    assert reroute.input_ports["Input"].kind == "geometry"
    assert reroute.output_ports["Output"].kind == "geometry"
    assert scene.add_connection(reroute.output_ports["Output"], scene_output.input_ports["Geometry"], record_undo=False)
    assert scene.add_connection(scene_plane.output_ports["Geometry"], scene_material.input_ports["Geometry"], record_undo=False)

    sender = scene.create_node(
        "graph.send", QPointF(260, 260), parameters={"channel_name": "Mesh Channel"}, record_undo=False
    )
    assert scene.add_connection(
        scene_plane.output_ports["Geometry"], sender.input_ports["Input"], record_undo=False
    )
    receiver = scene.create_node(
        "graph.receive", QPointF(520, 260), parameters={"sender_uid": sender.uid}, record_undo=False
    )
    portal_output = scene.create_node("output.geometry", QPointF(760, 260), record_undo=False)
    scene._resolve_dynamic_types()
    assert receiver.output_ports["Output"].kind == "geometry"
    assert scene.add_connection(
        receiver.output_ports["Output"], portal_output.input_ports["Geometry"], record_undo=False
    )

    restored = GraphScene(build_registry())
    restored.from_dict(scene.to_dict())
    restored_outputs = [node for node in restored.nodes.values() if node.definition.type_id == "output.geometry"]
    restored_output = next(
        node for node in restored_outputs
        if restored.connection_for_input(node.uid, "Geometry").source_node.definition.type_id == "graph.reroute"
    )
    restored_portal_output = next(node for node in restored_outputs if node is not restored_output)
    restored_material = next(node for node in restored.nodes.values() if node.definition.type_id == "material.pbr")
    restored_snapshot = GraphSnapshot.from_scene(restored)
    restored_evaluator = GraphEvaluator(restored, backend_preference="cpu")
    restored_result = GeometryEvaluationSession(
        restored_evaluator, restored_snapshot
    ).evaluate(restored_output.uid, "Geometry")
    assert restored_result.error is None, restored_result.error
    assert restored_result.geometry is not None
    assert restored_result.geometry.vertex_count == 12
    assert restored_result.geometry.triangle_count == 12
    restored_reference = material_geometry_reference(restored_snapshot, restored_material.uid)
    assert restored_reference is not None
    portal_result = GeometryEvaluationSession(
        restored_evaluator, restored_snapshot
    ).evaluate(restored_portal_output.uid, "Geometry")
    assert portal_result.error is None, portal_result.error
    assert portal_result.geometry is not None and portal_result.geometry.vertex_count == 12

    graph_input = scene.create_node(
        "graph.input", QPointF(0, 400),
        parameters={"name": "Mesh", "data_type": "Geometry", "required": True},
        record_undo=False,
    )
    graph_output = scene.create_node(
        "graph.output", QPointF(260, 400), parameters={"name": "Mesh"}, record_undo=False
    )
    assert graph_input.output_ports["Value"].kind == "geometry"
    assert scene.add_connection(graph_input.output_ports["Value"], graph_output.input_ports["Value"], record_undo=False)
    assert graph_output.input_ports["Value"].kind == "geometry"

    insert_scene = GraphScene(registry)
    insert_plane = insert_scene.create_node("geometry.plane", QPointF(), record_undo=False)
    insert_output = insert_scene.create_node("output.geometry", QPointF(420, 0), record_undo=False)
    direct = insert_scene.add_connection(
        insert_plane.output_ports["Geometry"], insert_output.input_ports["Geometry"], record_undo=False
    )
    assert direct is not None
    inserted = insert_scene.insert_reroute_on_connection(direct, QPointF(210, 0))
    assert inserted is not None
    assert inserted.input_ports["Input"].kind == "geometry"
    assert inserted.output_ports["Output"].kind == "geometry"
    assert len(insert_scene.connections) == 2

    child = GraphScene(registry)
    child_input = child.create_node(
        "graph.input", QPointF(),
        parameters={"name": "Mesh", "data_type": "Geometry", "required": False},
        record_undo=False,
    )
    child_output = child.create_node(
        "graph.output", QPointF(260, 0), parameters={"name": "Mesh"}, record_undo=False
    )
    assert child.add_connection(
        child_input.output_ports["Value"], child_output.input_ports["Value"], record_undo=False
    )
    child_data = child.to_dict()
    child_data["graph_asset"] = {
        "name": "Geometry Passthrough",
        "category": "Tests",
        "description": "Geometry graph-instance regression fixture.",
        "version": "1.0.0",
    }
    child_path = tmp_path / "geometry_passthrough.vfxgraph"
    child_path.write_text(json.dumps(child_data, indent=2), encoding="utf-8")

    host = GraphScene(registry)
    host_plane = host.create_node("geometry.plane", QPointF(), record_undo=False)
    instance = host.create_graph_instance(child_path, QPointF(260, 0), record_undo=False)
    host_output = host.create_node("output.geometry", QPointF(520, 0), record_undo=False)
    assert instance.parameters["_asset_interface"]["inputs"][0]["required"] is True
    geometry_input_name = next(name for name, port in instance.input_ports.items() if port.kind == "geometry")
    geometry_output_name = next(name for name, port in instance.output_ports.items() if port.kind == "geometry")
    assert host.add_connection(
        host_plane.output_ports["Geometry"], instance.input_ports[geometry_input_name], record_undo=False
    )
    assert host.add_connection(
        instance.output_ports[geometry_output_name], host_output.input_ports["Geometry"], record_undo=False
    )
    host_snapshot = GraphSnapshot.from_scene(host)
    host_result = GeometryEvaluationSession(
        GraphEvaluator(host, backend_preference="cpu"), host_snapshot
    ).evaluate(host_output.uid, "Geometry")
    assert host_result.error is None, host_result.error
    assert host_result.geometry is not None and host_result.geometry.vertex_count == 289
    del app


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        test_geometry_foundation(Path(directory))
    print("geometry foundation test passed")
