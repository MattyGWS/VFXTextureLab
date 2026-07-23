from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vfx_texture_lab.geometry import (
    GeometryData,
    UV_ORIGIN_BOTTOM_LEFT,
    UV_ORIGIN_TOP_LEFT,
    convert_uv_origin,
    export_obj,
    plane_geometry,
)
from vfx_texture_lab.geometry_bake import (
    GeometryBakeResult,
    BakeMap,
    decode_bake_result,
    encode_bake_result,
)
from vfx_texture_lab.uv_unwrap import unwrap_geometry


def test_standard_uvs_convert_to_image_space_without_changing_authored_mesh() -> None:
    vertices = np.asarray(
        [
            [0, 0, 0, 0, 0, 1, 0.0, 0.0],
            [1, 0, 0, 0, 0, 1, 1.0, 0.0],
            [0, 1, 0, 0, 0, 1, 0.0, 1.0],
        ],
        dtype=np.float32,
    )
    geometry = GeometryData(vertices, np.asarray([0, 1, 2], dtype=np.uint32), "Standard", UV_ORIGIN_BOTTOM_LEFT)
    converted = convert_uv_origin(geometry.vertices, geometry.uv_origin, UV_ORIGIN_TOP_LEFT)

    assert converted[:, 6].tolist() == [0.0, 1.0, 0.0]
    assert converted[:, 7].tolist() == [1.0, 1.0, 0.0]
    assert geometry.vertices[:, 7].tolist() == [0.0, 0.0, 1.0]


def test_projection_unwrap_publishes_standard_bottom_left_uvs() -> None:
    source = plane_geometry(2.0, 2.0, 1, 1, "Vertical (XY)", name="Plane")
    result = unwrap_geometry(source, {"mode": "Planar Projection", "name": "Unwrapped"})
    assert result.geometry.uv_origin == UV_ORIGIN_BOTTOM_LEFT


def test_bake_codec_preserves_uv_origin() -> None:
    low = plane_geometry(2.0, 2.0, 1, 1, "Vertical (XY)", name="Low")
    low = GeometryData(low.vertices, low.indices, low.name, UV_ORIGIN_BOTTOM_LEFT)
    image = np.zeros((4, 4, 4), dtype=np.float32)
    result = GeometryBakeResult(low, {"Normal": BakeMap("Normal", "vector", image)}, {})
    restored = decode_bake_result(encode_bake_result(result))
    assert restored.low_geometry.uv_origin == UV_ORIGIN_BOTTOM_LEFT


def test_obj_export_always_writes_standard_uv_orientation(tmp_path: Path) -> None:
    source = plane_geometry(2.0, 2.0, 1, 1, "Vertical (XY)", name="Plane")
    assert source.uv_origin == UV_ORIGIN_TOP_LEFT
    path = export_obj(source, tmp_path / "plane.obj")
    uv_lines = [line for line in path.read_text().splitlines() if line.startswith("vt ")]
    exported_v = [float(line.split()[2]) for line in uv_lines]
    expected = (1.0 - source.vertices[:, 7]).tolist()
    assert exported_v == expected


def test_preview_shader_separates_texture_uv_from_tangent_uv() -> None:
    shader = (ROOT / "vfx_texture_lab" / "shaders" / "preview_3d.wgsl").read_text()
    assert "sampled.y = 1.0 - sampled.y" in shader
    assert "@location(4) tangent_uv" in shader
    assert "derivative_tangent_basis(input.world_position, input.tangent_uv" in shader


def test_preview_tangent_basis_retains_uv_determinant_orientation() -> None:
    shader = (ROOT / "vfx_texture_lab" / "shaders" / "preview_3d.wgsl").read_text()
    assert "let uv_orientation = select(-1.0, 1.0, determinant >= 0.0);" in shader
    assert "* uv_orientation" in shader
