from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext


def main() -> int:
    registry = build_registry()
    context = EvalContext(64, 64)
    noise_definitions = [
        definition
        for definition in registry.all()
        if definition.category.startswith("Noise")
        and definition.parameter_spec("evolution") is not None
        and definition.evaluator is not None
    ]
    assert noise_definitions, "No built-in noise nodes expose Evolution"

    worst_step = ("", 0.0)
    for definition in noise_definitions:
        spec = definition.parameter_spec("evolution")
        assert spec is not None
        assert spec.minimum == 0.0, (definition.type_id, spec.minimum)
        assert spec.maximum == 1.0, (definition.type_id, spec.maximum)

        parameters = definition.default_parameters()
        parameters["evolution"] = 0.0
        start = definition.evaluator({}, parameters, context)
        parameters["evolution"] = 1.0
        end = definition.evaluator({}, parameters, context)
        assert np.allclose(start, end, atol=2e-5), f"{definition.type_id} no longer closes at Evolution 1"

        parameters["evolution"] = 0.25
        quarter = definition.evaluator({}, parameters, context)
        parameters["evolution"] = 3.25
        legacy = definition.evaluator({}, parameters, context)
        assert np.allclose(quarter, legacy, atol=2e-5), f"{definition.type_id} does not wrap legacy Evolution"

        parameters["evolution"] = 0.0
        first = definition.evaluator({}, parameters, context)
        parameters["evolution"] = 1.0 / 120.0
        second = definition.evaluator({}, parameters, context)
        step = float(np.mean(np.abs(first[..., :3] - second[..., :3])))
        if step > worst_step[1]:
            worst_step = (definition.type_id, step)
        assert step < 0.05, f"{definition.type_id} still changes too abruptly per 30 FPS frame: {step:.5f}"

    shader_root = Path(__file__).resolve().parents[1] / "vfx_texture_lab" / "shaders"
    for filename in (
        "fractal_family.wgsl",
        "ridged_noise.wgsl",
        "billow_noise.wgsl",
        "turbulence_noise.wgsl",
        "voronoi_fractal.wgsl",
    ):
        source = (shader_root / filename).read_text(encoding="utf-8")
        assert "evolution * z_multiplier" not in source
        assert "evolution * evolution_multiplier" not in source
        assert "loop_cycles * z_multiplier" not in source
        assert "loop_cycles * evolution_multiplier" not in source

    common = (shader_root / "noise" / "common.wgsl").read_text(encoding="utf-8")
    assert "return 4u;" in common
    assert "noise_evolution_phase" in common

    package_manifest = (
        Path(__file__).resolve().parents[1]
        / "vfx_texture_lab"
        / "node_packages"
        / "voronoi_noise"
        / "node.toml"
    ).read_text(encoding="utf-8")
    evolution_section = package_manifest.split('id = "evolution"', 1)[1].split("[[parameters]]", 1)[0]
    assert "minimum = 0.0" in evolution_section
    assert "maximum = 1.0" in evolution_section

    print(
        "Noise evolution test passed: all Evolution controls are 0..1, legacy values wrap, "
        f"loops close, and the largest default 30 FPS step was {worst_step[0]} at {worst_step[1]:.5f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
