from __future__ import annotations

import ast
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext
from vfx_texture_lab.nodes.noise_expansion import _segment_search_radii


GRADIENT_IDS = (
    "generator.linear_gradient",
    "generator.linear_gradient_2",
    "generator.linear_gradient_3",
)


def _parameter(definition, name: str):
    return next(parameter for parameter in definition.parameters if parameter.name == name)


def _render(type_id: str, *, width: int = 33, height: int = 257) -> np.ndarray:
    definition = build_registry().get(type_id)
    assert definition.evaluator is not None
    parameters = definition.default_parameters()
    parameters["repeat"] = False
    return definition.evaluator({}, parameters, EvalContext(width, height))[..., 0]


def assert_fur_controls_and_rounded_profile() -> None:
    registry = build_registry()
    fur = registry.get("noise.fur")
    fibres = registry.get("noise.fibres")
    messy = registry.get("noise.messy_fibres")

    assert _parameter(fur, "density").maximum == 10
    assert _parameter(fur, "length").maximum == 5.0
    assert _parameter(fibres, "density").maximum == 3
    assert _parameter(fibres, "length").maximum == 3.0
    assert _parameter(messy, "density").maximum == 3
    assert _parameter(messy, "length").maximum == 3.0

    root = Path(__file__).resolve().parents[1]
    source = (root / "vfx_texture_lab" / "nodes" / "noise_expansion.py").read_text(encoding="utf-8")
    shader = (root / "vfx_texture_lab" / "shaders" / "foundational_noise.wgsl").read_text(encoding="utf-8")
    fur_section = source[source.index("def eval_fur"):source.index("def _seed_parameter")]

    assert fur_section.count("rounded_profile=True") == 2
    assert "normalised_along * normalised_along" in source
    assert "args.rounded_profile != 0u" in shader
    assert "normalised_along * normalised_along" in shader
    assert "clamp(args.density, 1u, 10u)" in shader
    assert "point_index < 10u" in shader
    assert "segment_search_radius" in shader
    assert "oy: i32 = -5" in shader
    assert "ox: i32 = -5" in shader

    # Long Fur expands its cell search along the actual strand direction, so
    # the generated dome cannot disappear at an internal lattice boundary.
    # The common vertical case stays narrow in X for substantially less work
    # than a brute-force 11x11 square.
    vertical_radius = _segment_search_radii(
        length=5.0, width=0.05, softness=1.0,
        angle_degrees=-90.0, angle_random=24.0, rounded_profile=True,
    )
    horizontal_radius = _segment_search_radii(
        length=5.0, width=0.05, softness=1.0,
        angle_degrees=0.0, angle_random=24.0, rounded_profile=True,
    )
    maximum_radius = _segment_search_radii(
        length=5.0, width=0.4, softness=1.0,
        angle_degrees=0.0, angle_random=180.0, rounded_profile=True,
    )
    assert vertical_radius == (1, 4)
    assert horizontal_radius == (4, 1)
    assert maximum_radius == (5, 5)
    assert _segment_search_radii(
        length=5.0, width=0.4, softness=1.0,
        angle_degrees=0.0, angle_random=180.0, rounded_profile=False,
    ) == (1, 1)

    # The parabolic profile is smooth at the crest while the legacy mirrored
    # linear profile has a cusp.  A symmetric finite difference around zero
    # therefore has much smaller one-sided slopes for the rounded form.
    x = np.float32(1.0e-3)
    rounded_centre = np.float32(1.0)
    rounded_side = np.float32(1.0) - x * x
    linear_side = np.float32(1.0) - x
    rounded_slope = float((rounded_centre - rounded_side) / x)
    linear_slope = float((rounded_centre - linear_side) / x)
    assert rounded_slope < linear_slope * 0.01

    # The requested upper limits must execute, remain finite and materially
    # increase coverage compared with the default density.
    assert fur.evaluator is not None
    defaults = fur.default_parameters()
    dense = dict(defaults, density=10, length=5.0)
    default_image = fur.evaluator({}, defaults, EvalContext(64, 64))[..., 0]
    dense_image = fur.evaluator({}, dense, EvalContext(64, 64))[..., 0]
    assert np.isfinite(dense_image).all()
    assert float(np.mean(dense_image > 0.05)) > float(np.mean(default_image > 0.05))


def assert_linear_gradient_profiles_and_backend_contract() -> None:
    registry = build_registry()
    for type_id in GRADIENT_IDS:
        definition = registry.get(type_id)
        assert definition.output_kind(definition.output_name) == "grayscale"
        assert definition.default_image_kind == "grayscale"
        assert definition.output_format == "r16f"
        assert definition.gpu_kernel == "linear_gradient.wgsl"
        assert definition.evaluator is not None

    smooth = _render("generator.linear_gradient_2")[:, 16]
    sharp = _render("generator.linear_gradient_3")[:, 16]
    centre = len(smooth) // 2

    assert float(smooth[centre]) > 0.9999
    assert float(sharp[centre]) > 0.9999
    assert float(smooth[0]) < 0.001
    assert float(smooth[-1]) < 0.001
    assert float(sharp[0]) < 0.01
    assert float(sharp[-1]) < 0.01

    # Both profiles pass through half height at quarter distance.  Gradient 2
    # rounds into its crest; Gradient 3 keeps the requested sharp ridge.
    quarter = len(smooth) // 4
    assert abs(float(smooth[quarter]) - 0.5) < 0.015
    assert abs(float(sharp[quarter]) - 0.5) < 0.015
    assert float(smooth[centre - 1]) > float(sharp[centre - 1])
    smooth_crest_drop = float(smooth[centre] - smooth[centre - 1])
    sharp_crest_drop = float(sharp[centre] - sharp[centre - 1])
    assert smooth_crest_drop < sharp_crest_drop * 0.05

    root = Path(__file__).resolve().parents[1]
    backend_path = root / "vfx_texture_lab" / "engine" / "backends" / "wgpu_backend.py"
    module = ast.parse(backend_path.read_text(encoding="utf-8"))
    shaders = None
    inputs = None
    for item in module.body:
        if isinstance(item, ast.ClassDef) and item.name == "WgpuBackend":
            for statement in item.body:
                if not isinstance(statement, ast.Assign):
                    continue
                for target in statement.targets:
                    if isinstance(target, ast.Name) and target.id == "_SHADERS":
                        shaders = ast.literal_eval(statement.value)
                    if isinstance(target, ast.Name) and target.id == "_INPUT_ORDER":
                        inputs = ast.literal_eval(statement.value)
    assert shaders is not None and inputs is not None
    for type_id in GRADIENT_IDS:
        assert shaders[type_id] == "linear_gradient.wgsl"
        assert inputs[type_id] == ()


def assert_optional_gpu_agreement() -> None:
    try:
        from vfx_texture_lab.engine.backends.cpu import CpuBackend
        from vfx_texture_lab.engine.backends.wgpu_backend import WgpuBackend
        from vfx_texture_lab.engine.formats import RenderContext, TextureFormat
    except (ImportError, ModuleNotFoundError) as exc:
        print("Fur/gradient GPU comparison skipped: optional runtime dependency unavailable:", exc)
        return

    gpu = WgpuBackend()
    if not gpu.available:
        print("Fur/gradient GPU comparison skipped:", gpu.info().detail)
        return
    cpu = CpuBackend(gpu)
    registry = build_registry()
    context = RenderContext(79, 73, TextureFormat.RGBA16F)
    cases = [
        (type_id, {"angle": 37.0, "offset": 0.17, "repeat": True})
        for type_id in GRADIENT_IDS
    ]
    cases.append(("noise.fur", {"density": 10, "length": 5.0, "seed": 27}))
    for type_id, changes in cases:
        definition = registry.get(type_id)
        parameters = definition.default_parameters()
        parameters.update(changes)
        cpu_image = cpu.evaluate_node(definition, {}, parameters, context, f"cpu:{type_id}").array
        gpu_image = gpu.to_cpu(
            gpu.evaluate_node(definition, {}, parameters, context, f"gpu:{type_id}")
        ).array
        difference = np.abs(cpu_image - gpu_image)
        assert float(difference.max()) < 0.002, (type_id, difference.mean(), difference.max())


def main() -> int:
    assert_fur_controls_and_rounded_profile()
    assert_linear_gradient_profiles_and_backend_contract()
    assert_optional_gpu_agreement()
    print(
        "Fur and Linear Gradients test passed: rounded Fur crest, complete long-strand "
        "cell coverage, Density 10, Length 5, smooth Linear Gradient 2, sharp Linear "
        "Gradient 3 and CPU/GPU contracts"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
