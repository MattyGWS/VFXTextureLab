from __future__ import annotations

import ast
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext


TYPE_ID = "filter.directional_lighting"


def encoded(normal: tuple[float, float, float], width: int = 32, height: int = 24) -> np.ndarray:
    result = np.empty((height, width, 4), dtype=np.float32)
    result[..., :3] = np.asarray(normal, dtype=np.float32) * 0.5 + 0.5
    result[..., 3] = 1.0
    return result


def assert_registry_and_backend_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    definition = build_registry().get(TYPE_ID)
    assert definition.name == "Directional Lighting"
    assert definition.inputs == ("Normal",)
    assert definition.input_kinds == (("Normal", "vector"),)
    assert definition.output_kinds == (("Lighting", "grayscale"),)
    assert definition.gpu_kernel == "directional_lighting.wgsl"

    backend_source = (root / "vfx_texture_lab" / "engine" / "backends" / "wgpu_backend.py").read_text()
    module = ast.parse(backend_source)
    shaders = inputs = None
    for item in module.body:
        if isinstance(item, ast.ClassDef) and item.name == "WgpuBackend":
            for statement in item.body:
                if not isinstance(statement, ast.Assign):
                    continue
                for target in statement.targets:
                    if isinstance(target, ast.Name) and target.id == "_SHADERS":
                        shaders = ast.literal_eval(statement.value)
                    elif isinstance(target, ast.Name) and target.id == "_INPUT_ORDER":
                        inputs = ast.literal_eval(statement.value)
    assert shaders is not None and shaders[TYPE_ID] == "directional_lighting.wgsl"
    assert inputs is not None and inputs[TYPE_ID] == ("Normal",)
    assert 'if type_id == "filter.directional_lighting"' in backend_source

    shader = (root / "vfx_texture_lab" / "shaders" / "directional_lighting.wgsl").read_text()
    for token in ("diffuse_power", "highlight_power", "half_vector", "directx", "textureStore"):
        assert token in shader


def assert_direction_and_mask_shaping() -> None:
    definition = build_registry().get(TYPE_ID)
    context = EvalContext(48, 32)
    params = {
        **definition.default_parameters(),
        "angle": 0.0,
        "elevation": 20.0,
        "diffuse_power": 1.0,
        "diffuse_brightness": 1.0,
        "highlight_brightness": 0.0,
        "ambient": 0.0,
    }
    right = definition.evaluator({"Normal": encoded((0.8, 0.0, 0.6), 48, 32)}, params, context)[..., 0]
    left = definition.evaluator({"Normal": encoded((-0.8, 0.0, 0.6), 48, 32)}, params, context)[..., 0]
    assert float(right.mean()) > float(left.mean()) + 0.7

    flat = encoded((0.0, 0.0, 1.0), 48, 32)
    overhead = definition.evaluator({"Normal": flat}, {**params, "elevation": 90.0}, context)[..., 0]
    assert np.allclose(overhead, 1.0, atol=1.0e-6)

    ambient = definition.evaluator(
        {"Normal": encoded((-1.0, 0.0, 0.0), 48, 32)},
        {**params, "ambient": 0.23},
        context,
    )[..., 0]
    assert np.allclose(ambient, 0.23, atol=1.0e-6)

    broad = definition.evaluator({"Normal": encoded((0.5, 0.0, np.sqrt(0.75)), 48, 32)}, params, context)[..., 0]
    narrow = definition.evaluator(
        {"Normal": encoded((0.5, 0.0, np.sqrt(0.75)), 48, 32)},
        {**params, "diffuse_power": 4.0},
        context,
    )[..., 0]
    assert float(narrow.mean()) < float(broad.mean())

    highlight = definition.evaluator(
        {"Normal": flat},
        {
            **params,
            "elevation": 60.0,
            "diffuse_brightness": 0.0,
            "highlight_power": 12.0,
            "highlight_brightness": 1.0,
        },
        context,
    )[..., 0]
    assert float(highlight.mean()) > 0.1

    inverted = definition.evaluator({"Normal": flat}, {**params, "invert": True}, context)[..., 0]
    plain = definition.evaluator({"Normal": flat}, params, context)[..., 0]
    assert np.allclose(inverted, 1.0 - plain, atol=1.0e-7)


def assert_convention_and_gizmo_contract() -> None:
    definition = build_registry().get(TYPE_ID)
    context = EvalContext(32, 24)
    gl = encoded((0.3, -0.4, np.sqrt(0.75)), 32, 24)
    dx = gl.copy()
    dx[..., 1] = 1.0 - dx[..., 1]
    params = {**definition.default_parameters(), "angle": -70.0, "elevation": 35.0}
    result_gl = definition.evaluator({"Normal": gl}, params, context)
    result_dx = definition.evaluator(
        {"Normal": dx}, {**params, "normal_format": "DirectX (-Y)"}, context
    )
    assert np.allclose(result_gl, result_dx, atol=1.0e-6)

    preview_source = (Path(__file__).resolve().parents[1] / "vfx_texture_lab" / "ui" / "preview.py").read_text()
    assert 'type_id == "filter.directional_lighting"' in preview_source
    assert "_directional_light_geometry" in preview_source
    assert '"directional_light"' in preview_source
    assert '"elevation"' in preview_source and '"angle"' in preview_source


def main() -> int:
    assert_registry_and_backend_contract()
    assert_direction_and_mask_shaping()
    assert_convention_and_gizmo_contract()
    print("Directional Lighting test passed: registry/backend wiring, diffuse and highlight masks, ambient/invert, convention parity and 2D Preview gizmo contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
