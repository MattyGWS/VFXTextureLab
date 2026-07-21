from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vfx_texture_lab.nodes.base import EvalContext
from vfx_texture_lab.nodes.normal_height import _decode_normal
from vfx_texture_lab.nodes.processing import eval_height_normal
from vfx_texture_lab.nodes.registry import build_registry


def _rgba(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    result = np.repeat(values[..., None], 4, axis=2)
    result[..., 3] = 1.0
    return result


def _flat_normal(context: EvalContext) -> np.ndarray:
    result = np.zeros((context.height, context.width, 4), dtype=np.float32)
    result[..., 0] = 0.5
    result[..., 1] = 0.5
    result[..., 2] = 1.0
    result[..., 3] = 1.0
    return result


def assert_registry_and_types() -> None:
    registry = build_registry()
    expected = {
        "normal.blend": (("Normal", "vector"),),
        "normal.combine": (("Normal", "vector"),),
        "normal.normalize": (("Normal", "vector"),),
        "normal.invert": (("Normal", "vector"),),
        "normal.vector_rotation": (("Normal", "vector"),),
        "filter.directional_lighting": (("Lighting", "grayscale"),),
        "normal.transform": (("Normal", "vector"),),
        "normal.to_height": (("Height", "grayscale"),),
        "normal.bent": (("Normal", "vector"),),
        "filter.rt_shadows": (("Shadow", "grayscale"),),
    }
    for type_id, output_kinds in expected.items():
        definition = registry.get(type_id)
        assert definition.output_kinds == output_kinds
        assert definition.category == "Filters/Normal & Height"
        assert definition.default_parameters()["_resolved_kind"] == output_kinds[0][1]


def assert_normal_utilities() -> None:
    registry = build_registry()
    context = EvalContext(48, 40)
    flat = _flat_normal(context)
    y, x = np.mgrid[0:context.height, 0:context.width]
    nx = 0.45 * np.sin(x * 0.18)
    ny = 0.35 * np.cos(y * 0.21)
    nz = np.sqrt(np.maximum(1.0 - nx * nx - ny * ny, 0.0))
    source = np.empty_like(flat)
    source[..., :3] = np.stack((nx, ny, nz), axis=2) * 0.5 + 0.5
    source[..., 3] = 1.0

    normalize = registry.get("normal.normalize")
    repaired = normalize.evaluator({"Normal": source}, normalize.default_parameters(), context)
    decoded = _decode_normal(repaired, context)
    assert np.allclose(np.linalg.norm(decoded, axis=2), 1.0, atol=1.0e-6)

    combine = registry.get("normal.combine")
    for method in ("Reoriented (RNM)", "Whiteout", "UDN"):
        result = combine.evaluator(
            {"Base": source, "Detail": flat},
            {**combine.default_parameters(), "method": method},
            context,
        )
        assert np.allclose(result, repaired, atol=2.0e-6), method

    blend = registry.get("normal.blend")
    zero = blend.evaluator(
        {"Background": source, "Foreground": flat},
        {**blend.default_parameters(), "amount": 0.0},
        context,
    )
    one = blend.evaluator(
        {"Background": source, "Foreground": flat},
        {**blend.default_parameters(), "amount": 1.0},
        context,
    )
    assert np.allclose(zero, repaired, atol=2.0e-6)
    assert np.allclose(one, flat, atol=2.0e-6)

    invert = registry.get("normal.invert")
    inverted = invert.evaluator(
        {"Normal": source},
        {**invert.default_parameters(), "invert_x": True, "invert_y": True},
        context,
    )
    decoded_inverted = _decode_normal(inverted, context)
    assert np.allclose(decoded_inverted[..., 0], -decoded[..., 0], atol=1.0e-6)
    assert np.allclose(decoded_inverted[..., 1], -decoded[..., 1], atol=1.0e-6)
    assert np.allclose(decoded_inverted[..., 2], decoded[..., 2], atol=1.0e-6)


def assert_normal_vector_rotation() -> None:
    registry = build_registry()
    context = EvalContext(24, 20)
    normal = np.zeros((context.height, context.width, 4), dtype=np.float32)
    left = np.array((0.36, 0.48, 0.8), dtype=np.float32)
    right = np.array((-0.6, 0.0, 0.8), dtype=np.float32)
    normal[:, : context.width // 2, :3] = left * 0.5 + 0.5
    normal[:, context.width // 2 :, :3] = right * 0.5 + 0.5
    normal[..., 3] = 1.0
    definition = registry.get("normal.vector_rotation")

    result = definition.evaluator(
        {"Normal": normal},
        {**definition.default_parameters(), "angle": 90.0},
        context,
    )
    decoded = _decode_normal(result, context)
    assert np.allclose(decoded[:, : context.width // 2], (-0.48, 0.36, 0.8), atol=1.0e-6)
    assert np.allclose(decoded[:, context.width // 2 :], (0.0, -0.6, 0.8), atol=1.0e-6)
    # Unlike Normal Transform, the left/right texel ownership must not move.
    assert float(decoded[8, 4, 1]) > 0.3
    assert float(decoded[8, 18, 1]) < -0.5

    directx = normal.copy()
    directx[..., 1] = 1.0 - directx[..., 1]
    result_dx = definition.evaluator(
        {"Normal": directx},
        {**definition.default_parameters(), "angle": 90.0, "normal_format": "DirectX (-Y)"},
        context,
    )
    decoded_dx = _decode_normal(result_dx, context, "DirectX (-Y)")
    assert np.allclose(decoded, decoded_dx, atol=1.0e-6)

    flat_result = definition.evaluator(
        {"Normal": _flat_normal(context)},
        {**definition.default_parameters(), "angle": 1234.5},
        context,
    )
    assert np.array_equal(flat_result, _flat_normal(context))


def assert_directional_lighting() -> None:
    registry = build_registry()
    context = EvalContext(40, 32)
    definition = registry.get("filter.directional_lighting")

    normal = np.zeros((context.height, context.width, 4), dtype=np.float32)
    right = np.array((0.6, 0.0, 0.8), dtype=np.float32)
    left = np.array((-0.6, 0.0, 0.8), dtype=np.float32)
    normal[:, : context.width // 2, :3] = right * 0.5 + 0.5
    normal[:, context.width // 2 :, :3] = left * 0.5 + 0.5
    normal[..., 3] = 1.0

    params = {
        **definition.default_parameters(),
        "angle": 0.0,
        "elevation": 30.0,
        "diffuse_power": 1.0,
        "diffuse_brightness": 1.0,
        "highlight_brightness": 0.0,
        "ambient": 0.0,
    }
    result = definition.evaluator({"Normal": normal}, params, context)[..., 0]
    assert float(result[8, 4]) > float(result[8, 34]) + 0.5

    overhead = definition.evaluator(
        {"Normal": _flat_normal(context)},
        {**params, "elevation": 90.0},
        context,
    )[..., 0]
    assert np.allclose(overhead, 1.0, atol=1.0e-6)

    highlighted = definition.evaluator(
        {"Normal": _flat_normal(context)},
        {
            **params,
            "elevation": 60.0,
            "diffuse_brightness": 0.0,
            "highlight_power": 24.0,
            "highlight_brightness": 1.0,
        },
        context,
    )[..., 0]
    assert float(highlighted.mean()) > 0.1

    angled = np.zeros_like(normal)
    up_right = np.array((0.36, -0.48, 0.8), dtype=np.float32)
    down_left = np.array((-0.36, 0.48, 0.8), dtype=np.float32)
    angled[:, : context.width // 2, :3] = up_right * 0.5 + 0.5
    angled[:, context.width // 2 :, :3] = down_left * 0.5 + 0.5
    angled[..., 3] = 1.0
    parity_params = {**params, "angle": -53.0}
    result_gl = definition.evaluator({"Normal": angled}, parity_params, context)[..., 0]
    directx = angled.copy()
    directx[..., 1] = 1.0 - directx[..., 1]
    result_dx = definition.evaluator(
        {"Normal": directx},
        {**parity_params, "normal_format": "DirectX (-Y)"},
        context,
    )[..., 0]
    assert np.allclose(result_gl, result_dx, atol=1.0e-6)

    inverted = definition.evaluator(
        {"Normal": normal}, {**params, "invert": True}, context
    )[..., 0]
    assert np.allclose(inverted, 1.0 - result, atol=1.0e-7)


def assert_normal_transform_rotates_vectors() -> None:
    registry = build_registry()
    context = EvalContext(32, 32)
    normal = np.zeros((context.height, context.width, 4), dtype=np.float32)
    vector = np.array((0.6, 0.0, 0.8), dtype=np.float32)
    normal[..., :3] = vector * 0.5 + 0.5
    normal[..., 3] = 1.0
    definition = registry.get("normal.transform")
    result = definition.evaluator(
        {"Normal": normal},
        {**definition.default_parameters(), "angle": 90.0, "tile": True},
        context,
    )
    decoded = _decode_normal(result, context)
    assert np.allclose(decoded[..., 0], 0.0, atol=1.0e-6)
    assert np.allclose(decoded[..., 1], 0.6, atol=1.0e-6)
    assert np.allclose(decoded[..., 2], 0.8, atol=1.0e-6)


def assert_normal_to_height_reconstruction() -> None:
    registry = build_registry()
    context = EvalContext(128, 96)
    y, x = np.mgrid[0:context.height, 0:context.width]
    u = (x - context.width * 0.5) / 22.0
    v = (y - context.height * 0.5) / 18.0
    height = np.exp(-(u * u + v * v)).astype(np.float32)
    normal = eval_height_normal(
        {"Height": _rgba(height)},
        {"strength": 18.0, "invert_y": False},
        context,
    )
    definition = registry.get("normal.to_height")
    reconstructed = definition.evaluator(
        {"Normal": normal}, definition.default_parameters(), context
    )[..., 0]
    assert float(np.corrcoef(height.ravel(), reconstructed.ravel())[0, 1]) > 0.995
    assert float(reconstructed[context.height // 2, context.width // 2]) > 0.95
    assert float(reconstructed[0, 0]) < 0.05

    directx = normal.copy()
    directx[..., 1] = 1.0 - directx[..., 1]
    reconstructed_dx = definition.evaluator(
        {"Normal": directx},
        {**definition.default_parameters(), "normal_format": "DirectX (-Y)"},
        context,
    )[..., 0]
    assert np.allclose(reconstructed, reconstructed_dx, atol=1.0e-5)

    flat = definition.evaluator(
        {"Normal": _flat_normal(context)}, definition.default_parameters(), context
    )[..., 0]
    assert np.array_equal(flat, np.full_like(flat, 0.5))


def assert_bent_normal_and_rt_shadows() -> None:
    registry = build_registry()
    context = EvalContext(96, 96)
    flat_height = np.zeros((context.height, context.width), dtype=np.float32)
    bent = registry.get("normal.bent")
    flat_bent = bent.evaluator(
        {"Height": _rgba(flat_height)},
        {**bent.default_parameters(), "denoise": 0.0, "samples": 16},
        context,
    )
    assert np.allclose(flat_bent[..., :3], np.array((0.5, 0.5, 1.0), dtype=np.float32), atol=2.0e-6)

    height = flat_height.copy()
    height[32:64, 50:66] = 1.0
    bent_result = bent.evaluator(
        {"Height": _rgba(height)},
        {
            **bent.default_parameters(),
            "samples": 32,
            "maximum_distance": 0.30,
            "denoise": 0.0,
            "boundary": "Clamp",
        },
        context,
    )
    decoded = _decode_normal(bent_result, context)
    # On the ground immediately left of the blocker, right-facing sky is
    # occluded and the average visible direction bends away to the left.
    assert float(decoded[48, 45, 0]) < -0.05
    assert float(decoded[48, 58, 2]) > 0.98  # raised top remains upward-facing

    shadows = registry.get("filter.rt_shadows")
    params = {
        **shadows.default_parameters(),
        "angle": 0.0,
        "elevation": 25.0,
        "maximum_distance": 0.35,
        "softness": 0.0,
        "samples": 1,
        "boundary": "Clamp",
    }
    shadow = shadows.evaluator({"Height": _rgba(height)}, params, context)[..., 0]
    assert float(shadow[48, 58]) > 0.99
    assert float(shadow[48, 45]) < 0.1
    assert float(shadow[48, 80]) > 0.99
    inverted = shadows.evaluator(
        {"Height": _rgba(height)}, {**params, "invert": True}, context
    )[..., 0]
    assert np.allclose(inverted, 1.0 - shadow, atol=1.0e-7)


def main() -> int:
    assert_registry_and_types()
    assert_normal_utilities()
    assert_normal_vector_rotation()
    assert_directional_lighting()
    assert_normal_transform_rotates_vectors()
    assert_normal_to_height_reconstruction()
    assert_bent_normal_and_rt_shadows()
    print("Normal and height processing test passed: typed normal utilities, vector-direction rotation, directional lighting, RNM/Whiteout/UDN combination, tangent-aware transform, Poisson normal-to-height, bent normals and RT shadows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
