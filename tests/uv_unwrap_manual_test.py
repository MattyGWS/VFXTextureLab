from __future__ import annotations

import base64
import os
import sys
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from vfx_texture_lab.geometry import GeometryEvalContext, box_geometry, cylinder_geometry, plane_geometry
from vfx_texture_lab.nodes.registry import build_registry
from vfx_texture_lab.nodes.base import normalise_interrupted_manual_action
from vfx_texture_lab.uv_unwrap import (
    UNWRAP_SIGNATURE_PARAMETERS,
    UVUnwrapResult,
    decode_result,
    encode_result,
    evaluate_manual_uv_unwrap,
    geometry_signature,
    render_uv_preview,
    unwrap_geometry,
    uv_checker_texture,
)


def _projection_parameters() -> dict:
    registry = build_registry()
    definition = registry.get("geometry.uv_unwrap")
    parameters = definition.default_parameters()
    parameters.update({
        "mode": "Box Projection",
        "pack_resolution": 1024,
        "island_padding": 8,
    })
    return parameters


def test_uv_unwrap_node_registration_and_manual_contract() -> None:
    registry = build_registry()
    definition = registry.get("geometry.uv_unwrap")
    assert definition.input_kind("Geometry") == "geometry"
    assert definition.input_kind("Preview Texture") == "image_any"
    assert definition.output_kind("Geometry") == "geometry"
    assert definition.manual_action_label == "Unwrap"
    assert "mode" in definition.manual_action_relevant_parameters
    assert "Preview Texture" not in definition.manual_action_relevant_parameters
    assert definition.presentation_only_inputs == ("Preview Texture",)
    assert definition.geometry_evaluator is evaluate_manual_uv_unwrap
    assert len(registry.all()) == 187


def test_interrupted_manual_request_never_restarts_after_reopen() -> None:
    definition = build_registry().get("geometry.uv_unwrap")
    with_result = {
        "_manual_status": "Running",
        "_manual_run_serial": 4,
        "_manual_completed_serial": 3,
        "_manual_result_data": "saved-result",
        "_manual_changed_during_run": True,
        "_manual_last_error": "temporary",
    }
    assert normalise_interrupted_manual_action(definition, with_result)
    assert with_result["_manual_completed_serial"] == 4
    assert with_result["_manual_status"] == "Cancelled"
    assert with_result["_manual_changed_during_run"] is False
    assert with_result["_manual_last_error"] == ""

    without_result = {
        "_manual_status": "Cancelling",
        "_manual_run_serial": 2,
        "_manual_completed_serial": 1,
    }
    assert normalise_interrupted_manual_action(definition, without_result)
    assert without_result["_manual_completed_serial"] == 2
    assert without_result["_manual_status"] == "Not Run"

    current = {
        "_manual_status": "Up to Date",
        "_manual_run_serial": 2,
        "_manual_completed_serial": 2,
    }
    assert not normalise_interrupted_manual_action(definition, current)


def test_manual_projection_publishes_and_reuses_persistent_result() -> None:
    source = box_geometry(2.0, 1.5, 1.0, 2, 2, 2, name="Source")
    parameters = _projection_parameters()
    parameters["_manual_run_serial"] = 1
    context = GeometryEvalContext(width=320, height=256)

    output = evaluate_manual_uv_unwrap({"Geometry": source}, parameters, context)
    assert output.triangle_count == source.triangle_count
    assert context.metadata["_manual_status"] == "Up to Date"
    assert context.metadata["_manual_completed_serial"] == 1
    assert context.metadata["_manual_result_data"]
    assert context.metadata["_manual_result_revision"]
    assert context.metadata["_uv_island_count"] == 6
    assert context.preview_kind == "uv"
    assert context.preview_image is not None
    assert context.preview_image.shape == (256, 320, 4)
    assert context.preview_material_texture is uv_checker_texture()
    assert context.preview_material_texture.shape == (128, 128, 4)
    assert not context.preview_material_texture.flags.writeable
    assert np.unique(context.preview_material_texture[..., 0]).tolist() == pytest.approx([0.12, 0.32])

    saved = dict(parameters)
    saved.update(context.metadata)
    restored_context = GeometryEvalContext(width=256, height=256)
    restored = evaluate_manual_uv_unwrap({"Geometry": source}, saved, restored_context)
    assert restored_context.metadata["_manual_status"] == "Up to Date"
    assert np.array_equal(restored.vertices, output.vertices)
    assert np.array_equal(restored.indices, output.indices)

    renamed = dict(saved)
    renamed["name"] = "Retopologised Rock"
    renamed_context = GeometryEvalContext(width=128, height=128)
    renamed_output = evaluate_manual_uv_unwrap({"Geometry": source}, renamed, renamed_context)
    assert renamed_context.metadata["_manual_status"] == "Up to Date"
    assert renamed_output.name == "Retopologised Rock"
    assert np.array_equal(renamed_output.indices, output.indices)

    # Preview Texture is presentation-only: swapping it must not make the
    # persistent geometry result stale or request another unwrap.
    texture = np.ones((16, 16, 4), dtype=np.float32)
    texture[..., 0] = 0.25
    texture_context = GeometryEvalContext(width=128, height=128)
    textured = evaluate_manual_uv_unwrap(
        {"Geometry": source, "Preview Texture": texture}, saved, texture_context
    )
    assert texture_context.metadata["_manual_status"] == "Up to Date"
    assert np.array_equal(textured.indices, output.indices)
    assert texture_context.preview_image.shape == (128, 128, 4)
    assert texture_context.preview_material_texture is texture

    # Final/export evaluation consumes only the authored geometry. Preview-only
    # inputs and UV rasterisation stay out of the final dependency path.
    final_context = GeometryEvalContext(width=2048, height=2048, render_mode="final")
    final_output = evaluate_manual_uv_unwrap(
        {"Geometry": source, "Preview Texture": texture}, saved, final_context
    )
    assert np.array_equal(final_output.indices, output.indices)
    assert final_context.preview_image is None
    assert final_context.preview_material_texture is None
    assert final_context.preview_kind == ""

    stale = dict(saved)
    stale["island_padding"] = int(stale["island_padding"]) + 1
    stale_context = GeometryEvalContext(width=128, height=128)
    stale_output = evaluate_manual_uv_unwrap({"Geometry": source}, stale, stale_context)
    assert stale_context.metadata["_manual_status"] == "Out of Date"
    assert np.array_equal(stale_output.vertices, output.vertices)

    # When Automatic Charts is preserving existing seams, a UV-only upstream
    # edit is part of the unwrap source signature even though positions and
    # normals did not change.
    automatic = dict(saved)
    automatic["mode"] = "Automatic Charts"
    automatic["preserve_existing_seams"] = True
    automatic["_manual_signature"] = geometry_signature(
        source, automatic, UNWRAP_SIGNATURE_PARAMETERS
    )
    uv_changed = source.copy(name="UV changed")
    uv_changed.vertices[:, 6] += 0.125
    uv_context = GeometryEvalContext(width=128, height=128)
    evaluate_manual_uv_unwrap({"Geometry": uv_changed}, automatic, uv_context)
    assert uv_context.metadata["_manual_status"] == "Out of Date"



def test_cylindrical_projection_handles_dense_and_rotated_cylinders() -> None:
    parameters = {
        "mode": "Cylindrical Projection",
        "name": "Projected Cylinder",
        "island_padding": 8,
        "pack_resolution": 1024,
    }
    cases = (
        cylinder_geometry(radial_segments=32, height_segments=4, cap_segments=2),
        cylinder_geometry(
            radial_segments=32,
            height_segments=4,
            cap_segments=2,
            rotation_x=37.0,
            rotation_z=23.0,
        ),
        cylinder_geometry(
            radial_segments=32,
            height_segments=4,
            cap_segments=2,
            orientation="Axis X",
        ),
    )
    for source in cases:
        result = unwrap_geometry(source, parameters)
        assert result.geometry.triangle_count == source.triangle_count
        assert result.diagnostics["island_count"] == 3
        assert result.diagnostics["overlap_triangle_count"] == 0
        assert result.diagnostics["zero_area_triangle_count"] == 0
        assert result.diagnostics["out_of_bounds_vertex_count"] == 0
        assert np.all(np.isfinite(result.geometry.vertices[:, 6:8]))


def test_saved_result_preserves_overlap_highlight_array() -> None:
    geometry = plane_geometry(2.0, 2.0, 1, 1, "Horizontal (XZ)")
    overlap = np.zeros(geometry.triangle_count, dtype=bool)
    overlap[-1] = True
    result = UVUnwrapResult(
        geometry,
        np.asarray((2, 5), dtype=np.int32),
        {
            "backend": "test",
            "coverage": 0.5,
            "overlap_triangle_count": 1,
            "overlap_mask": overlap,
        },
    )
    encoded = encode_result(result)
    # Ensure this is a real compressed binary payload rather than JSON with a
    # stringified NumPy array.
    with np.load(BytesIO(base64.b64decode(encoded)), allow_pickle=False) as archive:
        assert "overlap_mask" in archive
        assert archive["overlap_mask"].dtype == np.uint8
    restored = decode_result(encoded)
    assert np.array_equal(restored.diagnostics["overlap_mask"], overlap)
    preview = render_uv_preview(restored, None, width=128, height=128)
    assert preview.shape == (128, 128, 4)


def test_uv_transform_nodes_publish_generic_2d_uv_preview() -> None:
    pytest.importorskip("PySide6")
    from vfx_texture_lab.engine.evaluator import GraphSnapshot, SnapshotNode
    from vfx_texture_lab.geometry_graph import GeometryEvaluationSession

    class _StructuralEvaluator:
        @staticmethod
        def _resolve_graph_output_proxy(snapshot, uid, output):
            return uid, output

        @staticmethod
        def _expand_graph_instances(snapshot, uid, output):
            return snapshot, uid, output

    registry = build_registry()
    plane_definition = registry.get("geometry.plane")
    transform_definition = registry.get("geometry.uv_transform")
    plane = SnapshotNode(
        "plane",
        plane_definition,
        {**plane_definition.default_parameters(), "subdivisions_x": 2, "subdivisions_y": 2},
    )
    transform = SnapshotNode(
        "uv",
        transform_definition,
        {**transform_definition.default_parameters(), "offset_x": 0.1},
    )
    snapshot = GraphSnapshot(
        {"plane": plane, "uv": transform},
        {("uv", "Geometry"): ("plane", "Geometry")},
    )
    result = GeometryEvaluationSession(
        _StructuralEvaluator(), snapshot, 192, 160,
        preview_options={"wireframe": True, "islands": True, "seams": True, "overlaps": True, "checker": True},
    ).evaluate("uv", "Geometry")
    assert result.error is None, result.error
    assert result.geometry is not None
    assert result.preview_kind == "uv"
    assert result.preview_image is not None
    assert result.preview_image.shape == (160, 192, 4)
    assert "UV layout" in result.preview_details


def test_automatic_charts_uses_current_xatlas_assignment_api(monkeypatch) -> None:
    import types
    from vfx_texture_lab.uv_unwrap import unwrap_geometry

    class _Options:
        pass

    class _Atlas:
        width = 1024
        height = 1024
        utilization = 0.75

        def __init__(self) -> None:
            self.positions = None
            self.faces = None

        def add_mesh(self, positions, faces, normals=None, uvs=None) -> None:
            self.positions = np.asarray(positions)
            self.faces = np.asarray(faces)

        def generate(self, chart_options=None, pack_options=None) -> None:
            assert chart_options is not None
            assert pack_options is not None

        def __getitem__(self, index):
            assert index == 0
            mapping = np.arange(self.positions.shape[0], dtype=np.uint32)
            uv = self.positions[:, (0, 2)].astype(np.float32)
            uv -= uv.min(axis=0)
            uv /= np.maximum(uv.max(axis=0), 1.0e-6)
            return mapping, self.faces.astype(np.uint32), uv

        def get_mesh_vertex_assignment(self, index):
            assert index == 0
            atlas_ids = np.zeros(self.positions.shape[0], dtype=np.int32)
            chart_ids = np.arange(self.positions.shape[0], dtype=np.int32) % 2
            return atlas_ids, chart_ids

        def get_mesh_chart_count(self, index):
            return 2

    fake = types.SimpleNamespace(Atlas=_Atlas, ChartOptions=_Options, PackOptions=_Options)
    monkeypatch.setitem(sys.modules, "xatlas", fake)
    source = plane_geometry(2.0, 2.0, 2, 2, "Horizontal (XZ)")
    parameters = _projection_parameters()
    parameters["mode"] = "Automatic Charts"
    result = unwrap_geometry(source, parameters)
    assert result.diagnostics["backend"] == "Native xatlas"
    assert result.geometry.triangle_count == source.triangle_count
    assert result.diagnostics["island_count"] == 2
    assert np.all(np.isfinite(result.geometry.vertices[:, 6:8]))


def test_automatic_charts_combines_multiple_xatlas_pages(monkeypatch) -> None:
    import types
    from vfx_texture_lab.uv_unwrap import unwrap_geometry

    class _Options:
        pass

    class _Atlas:
        width = 256
        height = 256
        atlas_count = 3

        def add_mesh(self, positions, faces, normals=None, uvs=None) -> None:
            self.positions = np.asarray(positions)
            self.faces = np.asarray(faces)

        def generate(self, chart_options=None, pack_options=None) -> None:
            assert chart_options is not None
            assert pack_options is not None

        def __getitem__(self, index):
            assert index == 0
            # Give every triangle independent vertices so its assignment is
            # unambiguous in this synthetic multi-page result.
            source = self.faces.reshape(-1)
            mapping = source.astype(np.uint32)
            output_faces = np.arange(source.size, dtype=np.uint32).reshape(-1, 3)
            local_uvs = np.tile(
                np.asarray(((0.1, 0.1), (0.9, 0.1), (0.1, 0.9)), dtype=np.float32),
                (self.faces.shape[0], 1),
            )
            return mapping, output_faces, local_uvs

        def get_mesh_vertex_assignment(self, index):
            assert index == 0
            vertex_count = self.faces.size
            pages = np.repeat(np.arange(self.faces.shape[0], dtype=np.int32) % 3, 3)
            charts = np.repeat(np.arange(self.faces.shape[0], dtype=np.int32), 3)
            assert pages.size == vertex_count
            return pages, charts

        def get_utilization(self, page):
            assert 0 <= page < 3
            return 0.8

    fake = types.SimpleNamespace(Atlas=_Atlas, ChartOptions=_Options, PackOptions=_Options)
    monkeypatch.setitem(sys.modules, "xatlas", fake)
    source = plane_geometry(2.0, 2.0, 2, 2, "Horizontal (XZ)")
    parameters = _projection_parameters()
    parameters["mode"] = "Automatic Charts"
    result = unwrap_geometry(source, parameters)
    uvs = result.geometry.vertices[:, 6:8]
    assert result.diagnostics["atlas_page_count"] == 3
    assert result.diagnostics["atlas_width"] == 512
    assert result.diagnostics["atlas_height"] == 512
    assert np.all(uvs >= 0.0)
    assert np.all(uvs <= 1.0)
    # Three 80%-full pages in a four-cell super-atlas cover 60% overall.
    assert result.diagnostics["coverage"] == pytest.approx(0.6)


def test_manual_output_revision_advances_only_when_result_is_published() -> None:
    pytest.importorskip("PySide6")
    from vfx_texture_lab.engine.evaluator import GraphEvaluator, GraphSnapshot, SnapshotNode

    registry = build_registry()
    plane_definition = registry.get("geometry.plane")
    unwrap_definition = registry.get("geometry.uv_unwrap")
    texture_definition = registry.get("generator.uniform_color")

    plane_parameters = plane_definition.default_parameters()
    unwrap_parameters = unwrap_definition.default_parameters()
    texture_parameters = texture_definition.default_parameters()
    nodes = {
        "plane": SnapshotNode("plane", plane_definition, plane_parameters),
        "texture": SnapshotNode("texture", texture_definition, texture_parameters),
        "unwrap": SnapshotNode("unwrap", unwrap_definition, unwrap_parameters),
    }
    inputs = {
        ("unwrap", "Geometry"): ("plane", "Geometry"),
        ("unwrap", "Preview Texture"): ("texture", "Image"),
    }
    evaluator = GraphEvaluator.__new__(GraphEvaluator)
    base = evaluator.branch_revision(GraphSnapshot(nodes, inputs), "unwrap")

    # Unapplied controls and preview-only texture edits do not alter the
    # currently published pass-through result.
    changed_unwrap = dict(unwrap_parameters)
    changed_unwrap["island_padding"] = int(changed_unwrap["island_padding"]) + 4
    changed_texture = dict(texture_parameters)
    changed_texture["colour"] = (0.8, 0.1, 0.2, 1.0)
    changed_nodes = dict(nodes)
    changed_nodes["unwrap"] = SnapshotNode("unwrap", unwrap_definition, changed_unwrap)
    changed_nodes["texture"] = SnapshotNode("texture", texture_definition, changed_texture)
    assert evaluator.branch_revision(GraphSnapshot(changed_nodes, inputs), "unwrap") == base

    # Once a persistent result exists, even source geometry edits merely mark
    # it stale; the output revision remains stable until another result commits.
    published = dict(changed_unwrap)
    published["_manual_result_data"] = "result-a"
    published["_manual_result_revision"] = "revision-a"
    published_nodes = dict(changed_nodes)
    published_nodes["unwrap"] = SnapshotNode("unwrap", unwrap_definition, published)
    published_revision = evaluator.branch_revision(GraphSnapshot(published_nodes, inputs), "unwrap")
    changed_plane = dict(plane_parameters)
    changed_plane["width"] = float(changed_plane["width"]) + 3.0
    stale_nodes = dict(published_nodes)
    stale_nodes["plane"] = SnapshotNode("plane", plane_definition, changed_plane)
    assert evaluator.branch_revision(GraphSnapshot(stale_nodes, inputs), "unwrap") == published_revision

    republished = dict(published)
    republished["_manual_result_data"] = "result-b"
    republished["_manual_result_revision"] = "revision-b"
    republished_nodes = dict(stale_nodes)
    republished_nodes["unwrap"] = SnapshotNode("unwrap", unwrap_definition, republished)
    assert evaluator.branch_revision(GraphSnapshot(republished_nodes, inputs), "unwrap") != published_revision


def test_manual_output_revision_uses_compact_digest_not_persistent_payload() -> None:
    pytest.importorskip("PySide6")
    from vfx_texture_lab.engine.evaluator import GraphEvaluator, SnapshotNode

    definition = build_registry().get("geometry.uv_unwrap")
    parameters = definition.default_parameters()
    parameters.update({
        "_manual_result_data": "A" * 4_000_000,
        "_manual_result_revision": "compact-result-digest",
        "_manual_signature": "source-settings-signature",
    })
    node = SnapshotNode("unwrap", definition, parameters)
    cleaned = GraphEvaluator._output_revision_parameters(node)
    assert cleaned["_manual_result_revision"] == "compact-result-digest"
    assert "_manual_result_data" not in cleaned
    assert len(repr(cleaned)) < 10_000
