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
    GeometryData,
    GeometryEvalContext,
    UV_ORIGIN_BOTTOM_LEFT,
    box_geometry,
    convert_uv_origin,
    plane_geometry,
)
from vfx_texture_lab.geometry_bake import (
    BAKE_OUTPUTS,
    BAKE_OUTPUT_KINDS,
    GeometryBakeResult,
    _EmbreeIntersector,
    _perform_bake,
    _rasterise_low_uv,
    _sample_low_surface,
    bake_output_image,
    bake_result_map_names,
    decode_bake_result,
    encode_bake_result,
    evaluate_manual_high_to_low_bake,
)
from vfx_texture_lab.nodes.registry import build_registry


def _scene() -> tuple:
    low = plane_geometry(
        2.0, 2.0, 1, 1, "Vertical (XY)", origin_z=0.0, name="Low"
    )
    high_base = plane_geometry(
        2.0, 2.0, 1, 1, "Vertical (XY)", name="High"
    )
    high_vertices = high_base.vertices.copy()
    high_vertices[:, 2] += 0.1
    high = GeometryData(high_vertices, high_base.indices.copy(), "High")
    yy, xx = np.mgrid[0:32, 0:32]
    albedo = np.zeros((32, 32, 4), dtype=np.float32)
    albedo[..., 0] = xx / 31.0
    albedo[..., 1] = yy / 31.0
    albedo[..., 2] = 0.25
    albedo[..., 3] = 1.0
    return high, low, albedo


def _parameters(**updates) -> dict:
    definition = build_registry().get("geometry.bake_high_to_low")
    parameters = definition.default_parameters()
    parameters.update(
        {
            "resolution": 64,
            "supersampling": "1x",
            "padding": 2,
            "bake_ambient_occlusion": False,
            "projection_mode": "Outward Only",
            "distance_mode": "Manual",
            "front_distance": 0.25,
            "back_distance": 0.25,
            "ray_bias_percent": 0.001,
        }
    )
    parameters.update(updates)
    return parameters



def test_embree_intersector_retains_lazy_trimesh_barycentric_helper() -> None:
    class FakeNativeIntersector:
        def intersects_location(self, origins, directions, multiple_hits=False):
            del directions, multiple_hits
            return (
                np.asarray([[0.25, 0.25, 0.0]], dtype=np.float64),
                np.asarray([0], dtype=np.int64),
                np.asarray([0], dtype=np.int64),
            )

    native = _EmbreeIntersector.__new__(_EmbreeIntersector)
    native.mesh = type(
        "FakeMesh",
        (),
        {
            "triangles": np.asarray(
                [[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]],
                dtype=np.float64,
            )
        },
    )()
    native.intersector = FakeNativeIntersector()
    native._points_to_barycentric = lambda triangles, locations: np.asarray(
        [[0.5, 0.25, 0.25]], dtype=np.float64
    )

    hit_tri, hit_distance, hit_bary = native.first_hits(
        np.asarray([[0.25, 0.25, 1.0]], dtype=np.float64),
        np.asarray([[0.0, 0.0, -1.0]], dtype=np.float64),
        2.0,
    )

    assert hit_tri.tolist() == [0]
    assert hit_distance.tolist() == pytest.approx([1.0])
    assert hit_bary[0].tolist() == pytest.approx([0.5, 0.25, 0.25])

def test_bake_node_registration_and_future_map_contract() -> None:
    registry = build_registry()
    definition = registry.get("geometry.bake_high_to_low")

    assert definition.input_kind("High Geometry") == "geometry"
    assert definition.input_kind("Low Geometry") == "geometry"
    assert definition.input_kind("High Albedo") == "color"
    assert definition.input_kind("Cage Geometry") == "geometry"
    assert definition.output_kind("Baked Material") == "material"
    assert definition.output_kind("Albedo") == "color"
    assert definition.output_kind("Normal") == "vector"
    assert definition.output_kind("Height") == "grayscale"
    assert definition.output_kind("Ambient Occlusion") == "grayscale"
    assert definition.output_kind("Projection Mask") == "grayscale"
    assert definition.output_kind("Low Geometry") == "geometry"
    assert definition.manual_action_label == "Bake"
    assert "resolution" in definition.manual_action_relevant_parameters
    assert "preview_output" not in definition.manual_action_relevant_parameters
    assert BAKE_OUTPUTS == (
        "Albedo",
        "Normal",
        "Height",
        "Ambient Occlusion",
        "Projection Mask",
    )
    assert set(BAKE_OUTPUTS) <= set(BAKE_OUTPUT_KINDS)
    assert len(registry.all()) == 187


def test_mirrored_uv_chart_uses_positive_u_and_v_tangent_axes() -> None:
    source = plane_geometry(2.0, 2.0, 1, 1, "Vertical (XY)", name="Mirrored Low")
    vertices = convert_uv_origin(
        source.vertices, source.uv_origin, UV_ORIGIN_BOTTOM_LEFT
    ).copy()
    vertices[:, 6] = 1.0 - vertices[:, 6]
    low = GeometryData(
        vertices, source.indices.copy(), "Mirrored Low", UV_ORIGIN_BOTTOM_LEFT
    )

    raster = _rasterise_low_uv(low, 32, 32, None)
    samples = _sample_low_surface(low, raster)
    valid_flat = np.flatnonzero(raster.valid.ravel())
    centre_index = int(np.flatnonzero(valid_flat == (16 * 32 + 16))[0])

    # Mirroring U means increasing texture U travels toward world -X. The
    # tangent basis must follow that authored direction rather than retaining
    # the triangle numerator's pre-determinant +X sign.
    assert samples["tangents"][centre_index] == pytest.approx([-1.0, 0.0, 0.0])
    assert samples["bitangents"][centre_index] == pytest.approx([0.0, 1.0, 0.0])

    high_vertices = low.vertices.copy()
    high_vertices[:, 2] += 0.1
    tilted = np.asarray([0.2, 0.0, 1.0], dtype=np.float32)
    tilted /= np.linalg.norm(tilted)
    high_vertices[:, 3:6] = tilted
    high = GeometryData(
        high_vertices, low.indices.copy(), "Mirrored High", UV_ORIGIN_BOTTOM_LEFT
    )

    result = _perform_bake(
        high,
        low,
        None,
        None,
        _parameters(
            resolution=32,
            padding=0,
            bake_albedo=False,
            bake_height=False,
            bake_ambient_occlusion=False,
        ),
        None,
    )
    encoded = result.maps["Normal"].image[16, 16, :3]
    decoded = encoded * 2.0 - 1.0
    assert decoded == pytest.approx([-0.196116, 0.0, 0.980581], abs=2.0e-3)

def test_reference_bake_transfers_albedo_and_direct_surface_maps() -> None:
    high, low, albedo = _scene()
    context = GeometryEvalContext(width=64, height=64)
    result = _perform_bake(high, low, albedo, None, _parameters(), context)

    assert isinstance(result, GeometryBakeResult)
    assert result.diagnostics["hit_percent"] == pytest.approx(100.0)
    assert result.diagnostics["overlap_pixels"] == 0
    assert result.diagnostics["height_min"] == pytest.approx(0.1, abs=2.0e-4)
    assert result.diagnostics["height_max"] == pytest.approx(0.1, abs=2.0e-4)
    assert set(result.maps) == {"Albedo", "Normal", "Height", "Projection Mask"}

    # The atlas centre samples the source texture centre.
    centre = result.maps["Albedo"].image[32, 32]
    assert centre[0] == pytest.approx(0.5, abs=0.06)
    assert centre[1] == pytest.approx(0.5, abs=0.06)
    assert centre[2] == pytest.approx(0.25, abs=0.02)
    assert centre[3] == pytest.approx(1.0)

    normal = result.maps["Normal"].image[32, 32]
    assert normal[:3] == pytest.approx([0.5, 0.5, 1.0], abs=2.0e-3)
    assert result.maps["Height"].image[32, 32, 0] == pytest.approx(1.0, abs=2.0e-3)
    assert result.maps["Projection Mask"].image[32, 32, 0] == pytest.approx(1.0)


def test_bake_result_codec_and_socket_resize_round_trip() -> None:
    high, low, albedo = _scene()
    result = _perform_bake(high, low, albedo, None, _parameters(), None)
    encoded = encode_bake_result(result)
    restored = decode_bake_result(encoded)

    assert restored.low_geometry.vertex_count == low.vertex_count
    assert restored.low_geometry.triangle_count == low.triangle_count
    assert set(restored.maps) == set(result.maps)
    assert restored.maps["Height"].precision == "16-bit"
    assert restored.maps["Albedo"].image.shape == (64, 64, 4)

    image, kind, precision = bake_output_image(
        {"_manual_result_data": encoded}, "Normal", 32, 24
    )
    assert image.shape == (24, 32, 4)
    assert kind == "vector"
    assert precision == "8-bit"
    lengths = np.linalg.norm(image[..., :3] * 2.0 - 1.0, axis=2)
    assert np.allclose(lengths, 1.0, atol=2.0e-3)


def test_manual_bake_is_transactional_and_persists_previous_result() -> None:
    high, low, albedo = _scene()

    not_run = _parameters()
    initial_context = GeometryEvalContext(width=64, height=64)
    initial = evaluate_manual_high_to_low_bake(
        {"Low Geometry": low}, not_run, initial_context
    )
    assert initial.triangle_count == low.triangle_count
    assert initial_context.metadata["_manual_status"] == "Not Run"

    running = _parameters()
    running["_manual_run_serial"] = 1
    context = GeometryEvalContext(width=64, height=64)
    output = evaluate_manual_high_to_low_bake(
        {"High Geometry": high, "Low Geometry": low, "High Albedo": albedo},
        running,
        context,
    )
    assert output.triangle_count == low.triangle_count
    assert context.metadata["_manual_status"] == "Up to Date"
    assert context.metadata["_manual_completed_serial"] == 1
    assert context.metadata["_manual_result_data"]
    assert context.metadata["_bake_hit_percent"] == pytest.approx(100.0)
    assert set(context.preview_material_textures) == {
        "Base Colour", "Normal", "Height"
    }

    saved = dict(running)
    saved.update(context.metadata)
    saved["_manual_status"] = "Out of Date"
    saved["padding"] = 7
    stale_context = GeometryEvalContext(width=64, height=64)
    stale = evaluate_manual_high_to_low_bake(
        {"Low Geometry": low}, saved, stale_context
    )
    assert stale_context.metadata["_manual_status"] == "Out of Date"
    assert stale.triangle_count == output.triangle_count
    assert stale_context.preview_image is not None

    # A failed replacement keeps the last successful result transactionally.
    retry = dict(saved)
    retry["_manual_run_serial"] = 2
    failed_context = GeometryEvalContext(width=64, height=64)
    retained = evaluate_manual_high_to_low_bake(
        {"High Geometry": high, "Low Geometry": low}, retry, failed_context
    )
    # Missing High Albedo is a supported partial bake, so force a genuine failure.
    assert retained.triangle_count == low.triangle_count

    broken = dict(saved)
    broken["_manual_run_serial"] = 3
    broken["projection_mode"] = "Custom Cage"
    broken_context = GeometryEvalContext(width=64, height=64)
    retained = evaluate_manual_high_to_low_bake(
        {"High Geometry": high, "Low Geometry": low, "High Albedo": albedo},
        broken,
        broken_context,
    )
    assert retained.triangle_count == low.triangle_count
    assert broken_context.metadata["_manual_status"] == "Failed"
    assert "Cage Geometry" in broken_context.metadata["_manual_last_error"]


def test_missing_high_albedo_skips_only_albedo() -> None:
    high, low, _albedo = _scene()
    result = _perform_bake(high, low, None, None, _parameters(), None)

    assert "Albedo" not in result.maps
    assert {"Normal", "Height", "Projection Mask"} <= set(result.maps)
    assert any("High Albedo is not connected" in warning for warning in result.diagnostics["warnings"])


def test_custom_cage_requires_matching_low_topology() -> None:
    high, low, albedo = _scene()
    cage = box_geometry(2.0, 2.0, 2.0, 1, 1, 1, name="Wrong Cage")
    with pytest.raises(ValueError, match="same vertices and triangle topology"):
        _perform_bake(
            high,
            low,
            albedo,
            cage,
            _parameters(projection_mode="Custom Cage"),
            None,
        )


def test_persisted_map_presence_ignores_unapplied_checkbox_changes() -> None:
    high, low, albedo = _scene()
    result = _perform_bake(high, low, albedo, None, _parameters(), None)
    parameters = {
        "_manual_result_data": encode_bake_result(result),
        "_bake_maps": tuple(result.maps),
        "bake_normal": False,
        "bake_height": False,
    }
    # Manual-node edits are only proposals until Re-Bake is pressed.
    assert {"Albedo", "Normal", "Height", "Projection Mask"} <= bake_result_map_names(parameters)


def test_missing_high_uvs_skips_albedo_without_blocking_geometry_maps() -> None:
    high, low, albedo = _scene()
    vertices = high.vertices.copy()
    vertices[:, 6:8] = 0.0
    high_without_uvs = GeometryData(vertices, high.indices.copy(), "High without UVs")
    result = _perform_bake(high_without_uvs, low, albedo, None, _parameters(), None)

    assert "Albedo" not in result.maps
    assert {"Normal", "Height", "Projection Mask"} <= set(result.maps)
    assert not result.diagnostics["high_uv_usable"]
    assert any("no usable UV area" in warning for warning in result.diagnostics["warnings"])


def test_uv_overlap_detection_accepts_split_normal_seam_edges() -> None:
    # Two triangles form one quad but deliberately use separate render vertices
    # along the diagonal, as imported hard-normal seams do.
    vertices = np.asarray(
        [
            [-1, 1, 0, 0, 0, 1, 0, 0],
            [1, 1, 0, 0, 0, 1, 1, 0],
            [-1, -1, 0, 0, 0, 1, 0, 1],
            [1, 1, 0, 0, 0, 1, 1, 0],
            [1, -1, 0, 0, 0, 1, 1, 1],
            [-1, -1, 0, 0, 0, 1, 0, 1],
        ],
        dtype=np.float32,
    )
    geometry = GeometryData(vertices, np.arange(6, dtype=np.uint32), "Split quad")
    raster = _rasterise_low_uv(geometry, 64, 64, None)
    assert not np.any(raster.overlap)


def test_bake_rejects_unsafe_internal_resolution_before_allocating() -> None:
    high, low, albedo = _scene()
    with pytest.raises(ValueError, match="16-million-sample safety limit"):
        _perform_bake(
            high, low, albedo, None,
            _parameters(resolution=4096, supersampling="2x"),
            None,
        )

    definition = build_registry().get("geometry.bake_high_to_low")
    resolution = next(item for item in definition.parameters if item.name == "resolution")
    assert resolution.maximum == 4096
