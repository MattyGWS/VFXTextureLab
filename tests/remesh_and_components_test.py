from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from vfx_texture_lab.geometry import (
    GeometryEvalContext,
    box_geometry,
    combine_geometry,
)
from vfx_texture_lab.manual_geometry import (
    ManualGeometryResult,
    decode_manual_geometry_result,
    encode_manual_geometry_result,
)
from vfx_texture_lab.mesh_components import delete_small_parts_geometry
from vfx_texture_lab.mesh_processing import diagnose_mesh
from vfx_texture_lab.mesh_remesh import evaluate_manual_remesh, voxel_remesh
from vfx_texture_lab.nodes.registry import build_registry


def _remesh_parameters() -> dict:
    definition = build_registry().get("geometry.remesh")
    parameters = definition.default_parameters()
    parameters.update(
        {
            "voxel_size_mode": "Relative to Bounds",
            "relative_voxel_size": 20.0,
            "fill_interior": True,
            "surface_smoothing": 0.35,
            "preserve_volume": True,
            "adaptivity": 0.0,
        }
    )
    return parameters


def test_geometry_nodes_are_registered_with_expected_contracts() -> None:
    registry = build_registry()
    remesh = registry.get("geometry.remesh")
    cleanup = registry.get("geometry.delete_small_parts")

    assert remesh.input_kind("Geometry") == "geometry"
    assert remesh.output_kind("Geometry") == "geometry"
    assert remesh.manual_action_label == "Remesh"
    assert "relative_voxel_size" in remesh.manual_action_relevant_parameters
    assert cleanup.input_kind("Geometry") == "geometry"
    assert cleanup.output_kind("Geometry") == "geometry"
    assert cleanup.manual_action_label == ""
    assert len(registry.all()) == 187


def test_delete_small_parts_keeps_largest_geometric_component_across_seams() -> None:
    # Box meshes duplicate positions at hard-normal/UV seams. Connectivity must
    # be measured on welded geometric positions rather than raw render vertices.
    large = box_geometry(2.0, 2.0, 2.0, 3, 3, 3, name="Large")
    small = box_geometry(
        0.2,
        0.2,
        0.2,
        1,
        1,
        1,
        origin_x=4.0,
        origin_y=2.0,
        name="Small",
    )
    combined = combine_geometry(large, small)
    metadata: dict = {}
    context = GeometryEvalContext(metadata=metadata)

    output = delete_small_parts_geometry(combined, context=context)

    assert output.triangle_count == large.triangle_count
    assert output.vertex_count == large.vertex_count
    assert metadata["_parts_input_components"] == 2
    assert metadata["_parts_output_components"] == 1
    assert metadata["_parts_removed_components"] == 1
    assert metadata["_parts_removed_triangles"] == small.triangle_count


def test_delete_small_parts_also_compacts_unreferenced_vertices() -> None:
    source = box_geometry(1.0, 1.0, 1.0, 1, 1, 1, name="Source")
    extra = np.zeros((1, 8), dtype=np.float32)
    extra[0, :3] = (50.0, 50.0, 50.0)
    from vfx_texture_lab.geometry import GeometryData

    dirty = GeometryData(
        np.concatenate((source.vertices, extra), axis=0),
        source.indices.copy(),
        "Dirty",
    )
    context = GeometryEvalContext()
    output = delete_small_parts_geometry(dirty, context=context)

    assert output.vertex_count == source.vertex_count
    assert output.triangle_count == source.triangle_count
    assert context.metadata["_parts_removed_vertices"] == 1


def test_delete_small_parts_relative_mode_can_keep_meaningful_secondary_parts() -> None:
    large = box_geometry(2.0, 2.0, 2.0, 3, 3, 3, name="Large")
    medium = box_geometry(
        1.0,
        1.0,
        1.0,
        2,
        2,
        2,
        origin_x=4.0,
        name="Medium",
    )
    tiny = box_geometry(
        0.1,
        0.1,
        0.1,
        1,
        1,
        1,
        origin_x=8.0,
        name="Tiny",
    )
    combined = combine_geometry(combine_geometry(large, medium), tiny)

    output = delete_small_parts_geometry(
        combined,
        mode="Keep Parts Above Relative Size",
        measure="Triangle Count",
        minimum_relative_size=40.0,
    )

    assert output.triangle_count == large.triangle_count + medium.triangle_count
    assert output.triangle_count < combined.triangle_count


def test_voxel_remesh_rebuilds_closed_uniform_topology_and_discards_uvs() -> None:
    source = box_geometry(2.0, 1.5, 1.0, 2, 2, 2, name="Source")
    result = voxel_remesh(source, _remesh_parameters(), GeometryEvalContext())
    output = result.geometry
    diagnostics = diagnose_mesh(output.vertices, output.indices)

    assert output.triangle_count > 0
    assert diagnostics.closed_manifold
    assert diagnostics.connected_components == 1
    assert np.allclose(output.vertices[:, 6:8], 0.0)
    assert np.isfinite(output.vertices).all()
    source_centre = (source.bounds[0] + source.bounds[1]) * 0.5
    output_centre = (output.bounds[0] + output.bounds[1]) * 0.5
    assert np.allclose(output_centre, source_centre, atol=1.0e-5)
    assert result.diagnostics["backend"].startswith("Voxel remesh")
    assert result.diagnostics["output_closed_manifold"] is True
    assert result.diagnostics["uvs_discarded"] is True
    # Preserve Volume should keep a simple closed source close to its authored volume.
    assert result.diagnostics["output_volume"] == pytest.approx(
        result.diagnostics["source_volume"], rel=0.03
    )


def test_voxel_remesh_rejects_unsafe_dense_grids_before_allocation() -> None:
    source = box_geometry(1.0, 1.0, 1.0, 1, 1, 1, name="Source")
    parameters = _remesh_parameters()
    parameters["relative_voxel_size"] = 0.05

    with pytest.raises(ValueError, match="unsafe.*grid"):
        voxel_remesh(source, parameters, GeometryEvalContext())


def test_manual_remesh_runs_only_when_prompted_and_reuses_saved_result() -> None:
    source = box_geometry(1.0, 1.0, 1.0, 1, 1, 1, name="Source")
    parameters = _remesh_parameters()

    untouched_context = GeometryEvalContext()
    untouched = evaluate_manual_remesh({"Geometry": source}, parameters, untouched_context)
    assert untouched.triangle_count == source.triangle_count
    assert untouched_context.metadata["_manual_status"] == "Not Run"

    parameters["_manual_run_serial"] = 1
    run_context = GeometryEvalContext()
    completed = evaluate_manual_remesh({"Geometry": source}, parameters, run_context)
    assert completed.triangle_count != source.triangle_count
    assert run_context.metadata["_manual_status"] == "Up to Date"
    assert run_context.metadata["_manual_result_data"]

    parameters.update(run_context.metadata)
    parameters["relative_voxel_size"] = 25.0
    stale_context = GeometryEvalContext()
    stale = evaluate_manual_remesh({"Geometry": source}, parameters, stale_context)
    assert stale.triangle_count == completed.triangle_count
    assert np.array_equal(stale.indices, completed.indices)
    assert stale_context.metadata["_manual_status"] == "Out of Date"


def test_manual_geometry_result_codec_round_trips_mesh_and_diagnostics() -> None:
    geometry = box_geometry(1.0, 2.0, 3.0, 1, 1, 1, name="Saved")
    encoded = encode_manual_geometry_result(
        ManualGeometryResult(geometry, {"backend": "test", "count": 3})
    )
    decoded = decode_manual_geometry_result(encoded)

    assert decoded.geometry.name == "Saved"
    assert np.array_equal(decoded.geometry.vertices, geometry.vertices)
    assert np.array_equal(decoded.geometry.indices, geometry.indices)
    assert decoded.diagnostics == {"backend": "test", "count": 3}


def test_manual_parameter_edits_use_lightweight_undo_without_graph_snapshots() -> None:
    QtCore = pytest.importorskip("PySide6.QtCore")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    from vfx_texture_lab.graph.scene import GraphScene

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    scene = GraphScene(build_registry())
    node = scene.create_node(
        "geometry.uv_unwrap",
        QtCore.QPointF(0.0, 0.0),
        emit_change=False,
        record_undo=False,
    )
    node.parameters.update(
        {
            "_manual_result_data": "persistent-result-placeholder",
            "_manual_status": "Up to Date",
            "_manual_applied_parameters": {
                name: node.parameters.get(name)
                for name in node.definition.manual_action_relevant_parameters
            },
        }
    )

    def forbidden_snapshot():
        raise AssertionError("manual setting edit took a complete graph snapshot")

    scene.to_dict = forbidden_snapshot  # type: ignore[method-assign]
    original = bool(node.parameters["quality_pack"])
    scene.change_node_parameter(node, "quality_pack", not original)
    assert node.parameters["quality_pack"] is (not original)
    assert node.parameters["_manual_status"] == "Out of Date"

    scene.undo_stack.undo()
    assert node.parameters["quality_pack"] is original
    assert node.parameters["_manual_status"] == "Up to Date"
    app.processEvents()
