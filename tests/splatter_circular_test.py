from __future__ import annotations

import ast
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext
from vfx_texture_lab.nodes.image_ops import grayscale_rgba


TYPE_ID = "pattern.splatter_circular"
EXPECTED_INPUTS = (
    "Pattern Input",
    "Pattern Input 2",
    "Pattern Input 3",
    "Pattern Input 4",
    "Background Input",
)


def render(parameters: dict, inputs: dict | None = None, width: int = 128, height: int = 128, mode: str = "preview") -> np.ndarray:
    definition = build_registry().get(TYPE_ID)
    values = definition.default_parameters()
    values.update(parameters)
    assert definition.evaluator is not None
    return definition.evaluator(inputs or {}, values, EvalContext(width, height, render_mode=mode))[..., 0]


def scalar(value: float, width: int = 32, height: int = 32) -> np.ndarray:
    return grayscale_rgba(np.full((height, width), value, dtype=np.float32))


def assert_registry_contract() -> None:
    definition = build_registry().get(TYPE_ID)
    assert definition.name == "Splatter Circular"
    assert definition.category == "Patterns"
    assert definition.inputs == EXPECTED_INPUTS
    assert definition.gpu_kernel == "splatter_circular.wgsl"
    assert definition.output_format == "r16f"
    assert definition.output_kind("Image") == "grayscale"
    assert all(definition.input_kind(name) == "grayscale" for name in EXPECTED_INPUTS)
    specs = {spec.name: spec for spec in definition.parameters}
    assert specs["pattern_amount"].maximum == 64
    assert specs["ring_amount"].maximum == 10
    assert specs["orientation"].options == ("Face Outward", "Face Centre", "Tangent", "Fixed")
    assert specs["pattern_selection"].options == (
        "Single", "Random Inputs", "Sequential Around Ring", "One Input per Ring"
    )
    assert specs["connect_patterns"].kind == "bool"
    assert specs["seed"].is_random_seed
    assert {"Rings", "Position", "Pattern", "Scale", "Selection", "Value", "Compositing", "Quality"} <= {
        spec.group for spec in definition.parameters
    }


def assert_backend_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    backend_path = root / "vfx_texture_lab" / "engine" / "backends" / "wgpu_backend.py"
    backend_source = backend_path.read_text(encoding="utf-8")
    module = ast.parse(backend_source)
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
    assert shaders is not None and shaders[TYPE_ID] == "splatter_circular.wgsl"
    assert inputs is not None and inputs[TYPE_ID] == EXPECTED_INPUTS
    assert 'if type_id == "pattern.splatter_circular"' in backend_source
    assert 'effective_parameters["_pattern_connected_mask"]' in backend_source
    shader = (root / "vfx_texture_lab" / "shaders" / "splatter_circular.wgsl").read_text(encoding="utf-8")
    for token in (
        "MAX_RINGS", "NEIGHBOURS", "random_instance", "pattern_from_ordinal",
        "connect_patterns", "arc_spread", "textureStore(output_tex",
    ):
        assert token in shader


def assert_radial_layout_and_arc() -> None:
    full = render({
        "pattern": "Disc", "pattern_amount": 8, "ring_amount": 1,
        "first_ring_radius": 0.28, "ring_spacing": 0.0,
        "size_x": 0.08, "size_y": 0.08, "arc_spread": 360.0,
        "orientation": "Fixed", "edge_softness": 0.0,
    })
    # Right, bottom, left and top cardinal placements are all occupied.
    coordinates = ((64, 100), (100, 64), (64, 28), (28, 64))
    assert all(full[y, x] > 0.5 for y, x in coordinates)
    assert full[64, 64] < 0.05

    arc = render({
        "pattern": "Disc", "pattern_amount": 5, "ring_amount": 1,
        "first_ring_radius": 0.28, "size_x": 0.08, "size_y": 0.08,
        "arc_spread": 90.0, "ring_rotation": 0.0, "orientation": "Fixed",
    })
    assert arc[64, 100] > 0.5  # right endpoint
    assert arc[100, 64] > 0.5  # lower endpoint in image coordinates
    assert arc[64, 28] < 0.05  # opposite side is not populated


def assert_rings_spiral_and_progression() -> None:
    rings = render({
        "pattern": "Disc", "pattern_amount": 10, "ring_amount": 3,
        "first_ring_radius": 0.10, "ring_spacing": 0.13,
        "size_x": 0.05, "size_y": 0.05, "orientation": "Fixed",
        "ring_rotation_offset": 11.0,
    })
    assert rings.max() > 0.99
    # Three authored radial bands produce nonzero coverage at three distances.
    yy, xx = np.mgrid[0:128, 0:128]
    radius = np.sqrt((xx - 63.5) ** 2 + (yy - 63.5) ** 2) / 128.0
    for expected in (0.10, 0.23, 0.36):
        annulus = np.abs(radius - expected) < 0.025
        assert float(rings[annulus].max()) > 0.5

    spiral = render({
        "pattern": "Disc", "pattern_amount": 24, "ring_amount": 1,
        "first_ring_radius": 0.08, "spiral": 0.34,
        "size_x": 0.045, "size_y": 0.045, "orientation": "Fixed",
    })
    closed = render({
        "pattern": "Disc", "pattern_amount": 24, "ring_amount": 1,
        "first_ring_radius": 0.08, "spiral": 0.0,
        "size_x": 0.045, "size_y": 0.045, "orientation": "Fixed",
    })
    assert np.mean(np.abs(spiral - closed)) > 0.02

    faded = render({
        "pattern": "Disc", "pattern_amount": 12, "ring_amount": 3,
        "first_ring_radius": 0.10, "ring_spacing": 0.13,
        "size_x": 0.05, "size_y": 0.05, "orientation": "Fixed",
        "luminance_by_ring": -0.8,
    })
    inner = np.abs(radius - 0.10) < 0.025
    outer = np.abs(radius - 0.36) < 0.025
    assert float(faded[inner].max()) > float(faded[outer].max())


def assert_connected_width_and_custom_inputs() -> None:
    source_a = scalar(1.0)
    yy, xx = np.mgrid[0:32, 0:32]
    source_b = grayscale_rgba(((xx > yy).astype(np.float32)))
    inputs = {"Pattern Input": source_a, "Pattern Input 2": source_b}
    sequential = render({
        "pattern_selection": "Sequential Around Ring", "pattern_amount": 16,
        "ring_amount": 1, "first_ring_radius": 0.28,
        "size_x": 0.055, "size_y": 0.08, "orientation": "Face Outward",
    }, inputs)
    per_ring = render({
        "pattern_selection": "One Input per Ring", "pattern_amount": 16,
        "ring_amount": 2, "first_ring_radius": 0.18, "ring_spacing": 0.16,
        "size_x": 0.055, "size_y": 0.08, "orientation": "Face Outward",
    }, inputs)
    assert sequential.max() > 0.9 and per_ring.max() > 0.9
    assert np.mean(np.abs(sequential - per_ring)) > 0.02

    separated = render({
        "pattern": "Square", "pattern_amount": 18, "ring_amount": 1,
        "first_ring_radius": 0.31, "size_x": 0.03, "size_y": 0.055,
        "connect_patterns": False, "orientation": "Tangent",
    })
    connected = render({
        "pattern": "Square", "pattern_amount": 18, "ring_amount": 1,
        "first_ring_radius": 0.31, "size_x": 0.03, "size_y": 0.055,
        "connect_patterns": True, "connect_scale": 1.05, "orientation": "Tangent",
    })
    assert np.mean(connected > 0.5) > np.mean(separated > 0.5) * 1.8


def assert_deterministic_randomisation_and_compositing() -> None:
    params = {
        "pattern": "Triangle", "pattern_amount": 23, "pattern_amount_random": 0.65,
        "minimum_pattern_amount": 8, "ring_amount": 5, "first_ring_radius": 0.06,
        "ring_spacing": 0.09, "radius_random": 0.5, "angular_random": 0.7,
        "scale_random": 0.4, "rotation_random": 90.0, "random_removal": 0.25,
        "luminance_random": 0.8, "seed": 77,
    }
    first = render(params, width=96, height=96)
    second = render(params, width=96, height=96)
    changed = render({**params, "seed": 78}, width=96, height=96)
    assert np.array_equal(first, second)
    assert np.mean(np.abs(first - changed)) > 0.01
    assert np.isfinite(first).all() and first.min() >= 0.0 and first.max() <= 1.0

    background = scalar(0.25, 96, 96)
    additive = render({
        "pattern": "Disc", "pattern_amount": 8, "ring_amount": 1,
        "first_ring_radius": 0.25, "size_x": 0.08, "size_y": 0.08,
        "blend_mode": "Add", "global_opacity": 0.5,
    }, {"Background Input": background}, width=96, height=96)
    assert additive.min() >= 0.249
    assert additive.max() > 0.7


def assert_preview_gizmo_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "vfx_texture_lab" / "ui" / "preview.py").read_text(encoding="utf-8")
    assert 'type_id == "pattern.splatter_circular"' in source
    assert "splatter_first_radius" in source
    assert "splatter_outer_radius" in source
    assert "splatter_rotation" in source
    assert '"ring_spacing"' in source and '"ring_rotation"' in source


def main() -> None:
    assert_registry_contract()
    assert_backend_contract()
    assert_radial_layout_and_arc()
    assert_rings_spiral_and_progression()
    assert_connected_width_and_custom_inputs()
    assert_deterministic_randomisation_and_compositing()
    assert_preview_gizmo_contract()
    print(
        "Splatter Circular test passed: registry/backend integration, concentric rings, partial arcs, spirals, "
        "custom pattern distribution, connected widths, deterministic variation, compositing and 2D Preview gizmos."
    )


if __name__ == "__main__":
    main()
