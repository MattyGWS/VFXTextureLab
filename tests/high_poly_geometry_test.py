from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vfx_texture_lab.geometry import (
    GeometryEvalContext,
    GeometryEvaluationCancelled,
    box_geometry,
    decimate_geometry,
    evaluate_mesh_input_geometry,
    refresh_mesh_metadata,
)
from vfx_texture_lab import geometry as geometry_module
from vfx_texture_lab import mesh_processing


class _PassThroughNative:
    """Dtype-strict API stand-in for the compiled wheel.

    The upstream package intentionally uses different point precision for its
    two entry points: simplify accepts float64, while replay accepts float32.
    Enforcing that here prevents a package-installed-but-fallback regression.
    """

    @staticmethod
    def simplify(points, triangles, *args, **kwargs):
        del args, kwargs
        assert isinstance(points, np.ndarray)
        assert points.dtype == np.float64
        assert points.flags.c_contiguous
        assert isinstance(triangles, np.ndarray)
        assert triangles.dtype == np.int32
        assert triangles.flags.c_contiguous
        return (
            points.copy(),
            triangles.copy(),
            np.asarray([[0, 1]], dtype=np.int32),
        )

    @staticmethod
    def replay_simplification(*, points, triangles, collapses):
        assert isinstance(points, np.ndarray)
        assert points.dtype == np.float32
        assert points.flags.c_contiguous
        assert isinstance(triangles, np.ndarray)
        assert triangles.dtype == np.int32
        assert triangles.flags.c_contiguous
        assert isinstance(collapses, np.ndarray)
        assert collapses.dtype == np.int32
        assert collapses.flags.c_contiguous
        return (
            points.copy(),
            triangles.copy(),
            np.arange(points.shape[0], dtype=np.int32),
        )


class _TopologyBreakingNative:
    """Stand-in whose first collapse opens an otherwise closed mesh."""

    @staticmethod
    def simplify(points, triangles, *args, **kwargs):
        del args, kwargs
        return (
            points.copy(),
            triangles[:6].copy(),
            np.asarray([[0, 1], [2, 3]], dtype=np.int32),
        )

    @staticmethod
    def replay_simplification(*, points, triangles, collapses):
        if collapses.shape[0] == 0:
            faces = triangles.copy()
        else:
            faces = triangles[:6].copy()
        return (
            points.copy(),
            faces,
            np.arange(points.shape[0], dtype=np.int32),
        )


def test_diagnostics_weld_attribute_seams_without_inventing_cracks() -> None:
    source = box_geometry()
    diagnostics = mesh_processing.diagnose_mesh(source.vertices, source.indices)

    # The box stores per-face UV and hard-normal copies (24 render vertices),
    # but simplification must see the eight shared geometric corners.
    assert diagnostics.vertex_count == 24
    assert diagnostics.unique_position_count == 8
    assert diagnostics.uv_seam_vertices == 24
    assert diagnostics.hard_normal_seam_vertices == 24
    assert diagnostics.boundary_edges == 0
    assert diagnostics.non_manifold_edges == 0
    assert diagnostics.closed_manifold is True


def test_native_reconstruction_preserves_closed_manifold_seams(monkeypatch) -> None:
    monkeypatch.setattr(mesh_processing, "_fast_simplification", _PassThroughNative())
    mesh_processing.clear_simplification_cache()
    source = box_geometry()

    vertices, indices, diagnostics, backend, pass_count = mesh_processing.native_decimate(
        source.vertices, source.indices, target_count=6
    )

    assert backend == "Native QEM (fast-simplification)"
    assert pass_count == 1
    assert vertices.shape[1] == 8
    assert indices.dtype == np.uint32
    assert diagnostics.closed_manifold is True
    assert diagnostics.boundary_edges == 0
    # Attribute copies remain exactly coincident after reconstruction.
    positions = np.ascontiguousarray(vertices[:, :3], dtype=np.float32)
    unique_positions = np.unique(positions.view(np.uint32).reshape(-1, 3), axis=0)
    assert unique_positions.shape[0] == diagnostics.unique_position_count


def test_native_decimate_backs_off_instead_of_falling_back_when_a_collapse_opens_mesh(
    monkeypatch,
) -> None:
    monkeypatch.setattr(mesh_processing, "_fast_simplification", _TopologyBreakingNative())
    mesh_processing.clear_simplification_cache()
    source = box_geometry()

    vertices, indices, diagnostics, backend, pass_count = mesh_processing.native_decimate(
        source.vertices, source.indices, target_count=6
    )

    assert backend == "Native QEM (topology-protected)"
    assert pass_count == 1
    assert diagnostics.closed_manifold is True
    assert indices.size // 3 >= 6
    assert vertices.shape[1] == 8

    context = GeometryEvalContext(node_uid="decimate", node_name="Geometry Decimate")
    result = decimate_geometry(source, 50.0, context=context)
    assert result.triangle_count >= 6
    assert context.metadata["_decimation_backend"] == "Native QEM (topology-protected)"
    assert context.metadata["_decimation_warning"] == ""



def test_native_decimate_replans_from_watertight_intermediates_to_reach_absolute_target(
    monkeypatch,
) -> None:
    monkeypatch.setattr(mesh_processing, "_fast_simplification", object())
    source = box_geometry()
    requested_targets: list[int] = []
    output_counts = iter((9, 6, 3))

    def fake_pass(vertices, indices, target_count, **kwargs):
        del kwargs
        requested_targets.append(int(target_count))
        count = next(output_counts)
        fake_indices = np.resize(np.asarray(indices, dtype=np.uint32), count * 3)
        diagnostics = mesh_processing.MeshDiagnostics(
            vertex_count=int(np.asarray(vertices).shape[0]),
            triangle_count=count,
            unique_position_count=8,
            boundary_edges=0,
            non_manifold_edges=0,
            degenerate_triangles=0,
            duplicate_triangles=0,
            connected_components=1,
            uv_seam_vertices=0,
            hard_normal_seam_vertices=0,
            bytes_used=int(np.asarray(vertices).nbytes + fake_indices.nbytes),
        )
        return (
            np.ascontiguousarray(vertices, dtype=np.float32),
            np.ascontiguousarray(fake_indices, dtype=np.uint32),
            diagnostics,
            True,
        )

    monkeypatch.setattr(mesh_processing, "_native_decimate_pass", fake_pass)
    vertices, indices, diagnostics, backend, pass_count = mesh_processing.native_decimate(
        source.vertices, source.indices, target_count=3
    )

    assert requested_targets == [3, 3, 3]
    assert indices.size // 3 == 3
    assert diagnostics.triangle_count == 3
    assert pass_count == 3
    assert backend == "Native QEM (iterative topology-protected · 3 passes)"
    assert vertices.shape[1] == 8

def test_decimate_reports_native_backend_and_cooperative_cancellation(monkeypatch) -> None:
    monkeypatch.setattr(mesh_processing, "_fast_simplification", _PassThroughNative())
    mesh_processing.clear_simplification_cache()
    source = box_geometry(subdivisions_x=2, subdivisions_y=2, subdivisions_z=2)
    context = GeometryEvalContext(node_uid="decimate", node_name="Geometry Decimate")

    result = decimate_geometry(source, 50.0, context=context)
    assert result.triangle_count > 0
    assert context.metadata["_decimation_backend"] == "Native QEM (fast-simplification)"
    assert context.metadata["_output_closed_manifold"] is True

    cancelled = GeometryEvalContext(
        node_uid="decimate",
        node_name="Geometry Decimate",
        cancel_check=lambda: True,
    )
    mesh_processing.clear_simplification_cache()
    with pytest.raises(GeometryEvaluationCancelled):
        decimate_geometry(source, 50.0, context=cancelled)


def test_large_obj_metadata_is_deferred_then_published_by_background_evaluation(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "scan.obj"
    source.write_text(
        "o Scan\n"
        "v 0 0 0\n"
        "v 1 0 0\n"
        "v 0 1 0\n"
        "vt 0 0\n"
        "vt 1 0\n"
        "vt 0 1\n"
        "f 1/1 2/2 3/3\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(geometry_module, "_DEFERRED_METADATA_BYTES", 1)
    parameters: dict[str, object] = {"path": str(source)}
    refresh_mesh_metadata(parameters)
    assert parameters["_source_pending"] is True
    assert parameters["_source_file_bytes"] == source.stat().st_size

    progress: list[tuple[int, int, str]] = []
    context = GeometryEvalContext(
        node_uid="mesh",
        node_name="Mesh Input",
        progress_callback=lambda current, total, message: progress.append(
            (current, total, message)
        ),
    )
    geometry = evaluate_mesh_input_geometry({}, parameters, context)
    assert geometry.triangle_count == 1
    assert context.metadata["_source_pending"] is False
    assert context.metadata["_source_triangle_count"] == 1
    assert context.metadata["_source_connected_components"] == 1
    assert progress


def test_release_declares_native_dependency_and_background_geometry_controller() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    main_window = (ROOT / "vfx_texture_lab" / "main_window.py").read_text(encoding="utf-8")
    spec = (ROOT / "packaging" / "windows" / "VFXTextureLab.spec").read_text(encoding="utf-8")

    assert "fast-simplification>=0.1.13,<0.2" in pyproject
    assert "fast-simplification>=0.1.13,<0.2" in requirements
    assert "GeometryEvaluationController" in main_window
    assert "geometry_preview_timer" in main_window
    assert "_geometry_node_state" in main_window
    assert 'collect_dynamic_libs("fast_simplification")' in spec
