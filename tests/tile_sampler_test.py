from __future__ import annotations

import ast
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext
from vfx_texture_lab.nodes.generators import (
    TILE_SAMPLER_MAX_CANDIDATE_RADIUS,
    tile_sampler_candidate_radius,
)
from vfx_texture_lab.nodes.image_ops import grayscale_rgba


PATTERN_INPUTS = ("Pattern Input", "Pattern Input 2", "Pattern Input 3", "Pattern Input 4")
MAP_INPUTS = (
    "Scale Map",
    "Rotation Map",
    "Displacement Map",
    "Vector Map",
    "Mask Map",
    "Pattern Distribution Map",
)
EXPECTED_INPUTS = PATTERN_INPUTS + MAP_INPUTS + ("Background Input",)


def render(parameters: dict, inputs: dict | None = None, width: int = 128, height: int = 96) -> np.ndarray:
    definition = build_registry().get("pattern.tile_sampler")
    values = definition.default_parameters()
    values.update(parameters)
    assert definition.evaluator is not None
    return definition.evaluator(inputs or {}, values, EvalContext(width, height))[..., 0]


def scalar_image(value: float, width: int, height: int) -> np.ndarray:
    return grayscale_rgba(np.full((height, width), value, dtype=np.float32))


def assert_backend_integration() -> None:
    root = Path(__file__).resolve().parents[1]
    backend_source = (root / "vfx_texture_lab" / "engine" / "backends" / "wgpu_backend.py").read_text(encoding="utf-8")
    module = ast.parse(backend_source)
    shader_map = None
    input_order = None
    for item in module.body:
        if isinstance(item, ast.ClassDef) and item.name == "WgpuBackend":
            for statement in item.body:
                if not isinstance(statement, ast.Assign):
                    continue
                for target in statement.targets:
                    if isinstance(target, ast.Name) and target.id == "_SHADERS":
                        shader_map = ast.literal_eval(statement.value)
                    if isinstance(target, ast.Name) and target.id == "_INPUT_ORDER":
                        input_order = ast.literal_eval(statement.value)
    assert shader_map is not None and shader_map["pattern.tile_sampler"] == "tile_sampler.wgsl"
    assert input_order is not None and input_order["pattern.tile_sampler"] == EXPECTED_INPUTS
    shader = (root / "vfx_texture_lab" / "shaders" / "tile_sampler.wgsl").read_text(encoding="utf-8")
    assert "fn random_cell" in shader
    assert "fn pattern_from_ordinal" in shader
    assert "sample_scale_map" in shader and "sample_vector_map" in shader
    assert "clamp(i32(params.p10.x), 1, 64)" in shader
    assert "candidate_count = diameter * diameter" in shader
    assert "let feather = edge_softness;" in shader
    assert "max(edge_softness, pixel_feather)" not in shader
    assert "sample_pattern_1_nearest" in shader and "sample_pattern_1_filtered" in shader
    assert "pattern_is_minified" in shader and "antialiased_input" in shader
    assert "textureStore(output_tex" in shader
    assert '(4 if str(parameters.get("rasterization", "Pixel Exact")) == "Antialiased" else 0)' in backend_source


def assert_registry_contract() -> None:
    definition = build_registry().get("pattern.tile_sampler")
    assert definition.category == "Patterns"
    assert definition.inputs == EXPECTED_INPUTS
    assert all(definition.input_kind(name) == "grayscale" for name in EXPECTED_INPUTS if name != "Vector Map")
    assert definition.input_kind("Vector Map") == "vector"
    assert definition.output_kind("Image") == "grayscale"
    assert definition.output_format == "r16f"
    assert definition.gpu_kernel == "tile_sampler.wgsl"
    groups = {spec.group for spec in definition.parameters}
    assert {"Distribution", "Pattern", "Size", "Position", "Rotation", "Tile Selection", "Value", "Compositing"} <= groups
    specs = {spec.name: spec for spec in definition.parameters}
    assert specs["size_x"].maximum == 8.0 and specs["size_x"].slider_maximum == 4.0
    assert specs["size_y"].maximum == 8.0 and specs["size_y"].slider_maximum == 4.0
    assert specs["scale"].maximum == 4.0 and specs["scale"].slider_maximum == 2.0
    assert specs["rotation"].editor == "angle" and specs["rotation"].unit == "degrees"
    assert specs["displacement_angle"].editor == "angle"
    assert specs["rotation_random"].maximum == 180.0 and specs["rotation_random"].editor == ""
    assert specs["pattern_selection"].options == ("Single", "Random Inputs", "Sequential Inputs", "Distribution Map")
    assert specs["offset_mode"].default == "Every Second Row"
    assert "None" not in specs["offset_mode"].options
    assert specs["row_offset"].minimum == 0.0 and specs["row_offset"].maximum == 1.0
    assert specs["row_offset"].label == "Offset Amount"
    assert specs["layout_mask"].options == ("All Tiles", "Checker", "Alternate Rows", "Alternate Columns")
    assert specs["mask_random"].label == "Random Removal"
    assert "tile_value" not in specs
    assert "_legacy_luminance_model" not in specs
    assert {"Diamond", "Hexagon", "Triangle"} <= set(specs["pattern"].options)


def assert_large_overlap_radius() -> None:
    ordinary = tile_sampler_candidate_radius({"size_x": 0.8, "size_y": 0.8, "scale": 1.0})
    expanded = tile_sampler_candidate_radius({
        "size_x": 8.0,
        "size_y": 6.0,
        "scale": 2.0,
        "scale_random": 0.5,
        "position_random_x": 1.0,
        "position_random_y": 1.0,
        "row_offset": 0.5,
        "displacement_intensity": 1.0,
        "vector_displacement": 1.0,
    })
    maximum = tile_sampler_candidate_radius({
        "size_x": 8.0,
        "size_y": 8.0,
        "scale": 4.0,
        "scale_random": 1.0,
        "scale_vector_map_strength": 1.0,
        "position_random_x": 1.0,
        "position_random_y": 1.0,
        "row_offset": 0.5,
        "displacement_intensity": 2.0,
        "vector_displacement": 2.0,
    })
    assert ordinary == 1
    assert expanded > 5
    assert maximum <= TILE_SAMPLER_MAX_CANDIDATE_RADIUS == 64

    image = render(
        {
            "pattern": "Disc",
            "x_amount": 3,
            "y_amount": 2,
            "size_x": 8.0,
            "size_y": 6.0,
            "scale": 2.0,
            "rotation": 37.0,
            "blend_mode": "Maximum",
        },
        width=36,
        height=24,
    )
    assert np.isfinite(image).all()
    assert float(image.min()) >= 0.0 and float(image.max()) <= 1.0
    assert float(image.mean()) > 0.5


def assert_default_grid_and_shapes() -> None:
    for pattern in ("Square", "Disc", "Brick", "Capsule", "Bell", "Diamond", "Hexagon", "Triangle"):
        image = render({"pattern": pattern, "x_amount": 7, "y_amount": 5})
        assert image.shape == (96, 128)
        assert np.isfinite(image).all()
        assert 0.0 <= float(image.min()) <= float(image.max()) <= 1.0
        assert float(image.max()) > 0.5
        assert float(image.mean()) > 0.01


def assert_deterministic_randomisation() -> None:
    parameters = {
        "pattern": "Disc",
        "x_amount": 10,
        "y_amount": 7,
        "scale_random": 0.55,
        "position_random_x": 0.7,
        "position_random_y": 0.45,
        "rotation_random": 135.0,
        "mask_random": 0.23,
        "luminance_random": 0.5,
        "mirror_x_random": True,
        "mirror_y_random": True,
    }
    first = render({**parameters, "seed": 812})
    repeated = render({**parameters, "seed": 812})
    changed = render({**parameters, "seed": 813})
    assert np.array_equal(first, repeated)
    assert float(np.mean(np.abs(first - changed))) > 0.03


def assert_stagger_and_custom_pattern() -> None:
    straight = render({"pattern": "Brick", "x_amount": 8, "y_amount": 6})
    staggered = render({
        "pattern": "Brick",
        "x_amount": 8,
        "y_amount": 6,
        "offset_mode": "Every Second Row",
        "row_offset": 0.5,
    })
    assert float(np.mean(np.abs(straight - staggered))) > 0.02

    height, width = 96, 128
    gradient = np.broadcast_to(np.linspace(0.0, 1.0, width, dtype=np.float32), (height, width))
    custom = render(
        {
            "pattern": "Pattern Input",
            "x_amount": 1,
            "y_amount": 1,
            "size_x": 1.0,
            "size_y": 1.0,
            "scale": 1.0,
            "edge_softness": 0.0,
            "non_square_expansion": False,
        },
        {"Pattern Input": grayscale_rgba(gradient)},
        width,
        height,
    )
    assert float(custom[:, -16:].mean()) > float(custom[:, :16].mean()) + 0.45


def _tile_centres(image: np.ndarray, x_amount: int, y_amount: int) -> np.ndarray:
    height, width = image.shape
    xs = [min(int((index + 0.5) * width / x_amount), width - 1) for index in range(x_amount)]
    ys = [min(int((index + 0.5) * height / y_amount), height - 1) for index in range(y_amount)]
    return image[np.ix_(ys, xs)]


def assert_offset_modes_and_layout_masks() -> None:
    base = {
        "pattern": "Square",
        "x_amount": 6,
        "y_amount": 6,
        "size_x": 0.72,
        "size_y": 0.72,
        "rasterization": "Pixel Exact",
        "blend_mode": "Replace",
    }
    straight = render({**base, "row_offset": 0.0}, width=120, height=120)
    brick = render({**base, "offset_mode": "Every Second Row", "row_offset": 0.5}, width=120, height=120)
    columns = render({**base, "offset_mode": "Every Second Column", "row_offset": 0.5}, width=120, height=120)
    progressive = render({**base, "offset_mode": "Continuous Rows", "row_offset": 0.25}, width=120, height=120)
    assert float(np.mean(np.abs(straight - brick))) > 0.04
    assert float(np.mean(np.abs(brick - columns))) > 0.04
    assert float(np.mean(np.abs(straight - progressive))) > 0.04

    all_tiles = _tile_centres(render(base, width=120, height=120), 6, 6)
    checker = _tile_centres(render({**base, "layout_mask": "Checker"}, width=120, height=120), 6, 6)
    rows = _tile_centres(render({**base, "layout_mask": "Alternate Rows"}, width=120, height=120), 6, 6)
    columns_mask = _tile_centres(render({**base, "layout_mask": "Alternate Columns"}, width=120, height=120), 6, 6)
    inverted = _tile_centres(render({**base, "layout_mask": "Checker", "invert_layout_mask": True}, width=120, height=120), 6, 6)
    expected_checker = np.fromfunction(lambda y, x: ((x + y) % 2) == 0, (6, 6), dtype=int)
    expected_rows = np.fromfunction(lambda y, x: (y % 2) == 0, (6, 6), dtype=int)
    expected_columns = np.fromfunction(lambda y, x: (x % 2) == 0, (6, 6), dtype=int)
    assert np.all(all_tiles > 0.99)
    assert np.array_equal(checker > 0.5, expected_checker)
    assert np.array_equal(rows > 0.5, expected_rows)
    assert np.array_equal(columns_mask > 0.5, expected_columns)
    assert np.array_equal(inverted > 0.5, ~expected_checker)


def assert_unbiased_luminance_random() -> None:
    base = {
        "pattern": "Square",
        "x_amount": 32,
        "y_amount": 32,
        "size_x": 0.74,
        "size_y": 0.74,
        "rasterization": "Pixel Exact",
        "blend_mode": "Replace",
        "seed": 31415,
    }
    white = _tile_centres(render({**base, "luminance_random": 0.0}, width=320, height=320), 32, 32)
    half = _tile_centres(render({**base, "luminance_random": 0.5}, width=320, height=320), 32, 32)
    full = _tile_centres(render({**base, "luminance_random": 1.0}, width=320, height=320), 32, 32)
    assert np.allclose(white, 1.0)
    assert float(half.min()) >= 0.5 and float(half.max()) <= 1.0
    assert 0.72 < float(half.mean()) < 0.78
    assert float(full.min()) < 0.01 and float(full.max()) > 0.99
    assert 0.47 < float(full.mean()) < 0.53


def assert_custom_pattern_rasterisation_modes() -> None:
    source_size = 256
    y, x = np.mgrid[0:source_size, 0:source_size]
    taper = np.maximum(1.0, source_size * 0.035 * (1.0 - y / source_size * 0.72))
    centre = source_size * 0.5 + 0.12 * (source_size - y)
    blade = (
        (np.abs(x - centre) < taper)
        & (y > source_size * 0.04)
        & (y < source_size * 0.96)
    ).astype(np.float32)
    inputs = {"Pattern Input": grayscale_rgba(blade)}
    parameters = {
        "pattern": "Pattern Input",
        "x_amount": 18,
        "y_amount": 18,
        "size_x": 0.82,
        "size_y": 0.82,
        "rotation_random": 180.0,
        "seed": 37,
        "edge_softness": 0.0,
    }
    exact = render({**parameters, "rasterization": "Pixel Exact"}, inputs, 192, 192)
    antialiased = render({**parameters, "rasterization": "Antialiased"}, inputs, 192, 192)

    exact_fractional = np.count_nonzero((exact > 1.0e-6) & (exact < 1.0 - 1.0e-6))
    aa_fractional = np.count_nonzero((antialiased > 1.0e-6) & (antialiased < 1.0 - 1.0e-6))
    exact_variation = float(np.mean(np.abs(np.diff(exact, axis=0))) + np.mean(np.abs(np.diff(exact, axis=1))))
    aa_variation = float(np.mean(np.abs(np.diff(antialiased, axis=0))) + np.mean(np.abs(np.diff(antialiased, axis=1))))

    assert exact_fractional == 0
    assert aa_fractional > 1000
    assert float(np.mean(np.abs(exact - antialiased))) > 0.005
    assert aa_variation < exact_variation * 0.9


def assert_multi_pattern_distribution() -> None:
    width, height = 128, 48
    inputs = {
        "Pattern Input": scalar_image(0.2, width, height),
        "Pattern Input 2": scalar_image(0.85, width, height),
    }
    sequential = render(
        {
            "pattern_selection": "Sequential Inputs",
            "x_amount": 4,
            "y_amount": 1,
            "size_x": 0.95,
            "size_y": 0.95,
            "non_square_expansion": False,
            "blend_mode": "Replace",
            "edge_softness": 0.0,
        },
        inputs,
        width,
        height,
    )
    centres = [float(sequential[height // 2, int((index + 0.5) * width / 4)]) for index in range(4)]
    assert centres[0] < 0.35 and centres[1] > 0.7 and centres[2] < 0.35 and centres[3] > 0.7

    distribution = np.broadcast_to(np.linspace(0.0, 1.0, width, dtype=np.float32), (height, width))
    mapped = render(
        {
            "pattern_selection": "Distribution Map",
            "x_amount": 4,
            "y_amount": 1,
            "size_x": 0.95,
            "size_y": 0.95,
            "non_square_expansion": False,
            "blend_mode": "Replace",
            "edge_softness": 0.0,
        },
        {**inputs, "Pattern Distribution Map": grayscale_rgba(distribution)},
        width,
        height,
    )
    assert float(mapped[:, : width // 2].mean()) + 0.25 < float(mapped[:, width // 2 :].mean())


def assert_map_driven_controls() -> None:
    width, height = 96, 64
    white = scalar_image(1.0, width, height)
    black = scalar_image(0.0, width, height)
    horizontal = np.broadcast_to(np.linspace(0.0, 1.0, width, dtype=np.float32), (height, width))

    baseline = render({"pattern": "Brick", "x_amount": 4, "y_amount": 3, "size_y": 0.35}, width=width, height=height)
    scaled = render(
        {"pattern": "Brick", "x_amount": 4, "y_amount": 3, "size_y": 0.35, "scale_map_strength": 1.0},
        {"Scale Map": grayscale_rgba(horizontal)},
        width,
        height,
    )
    assert float(np.mean(np.abs(baseline - scaled))) > 0.03

    rotated = render(
        {"pattern": "Brick", "x_amount": 4, "y_amount": 3, "size_y": 0.35, "rotation_map_multiplier": 45.0},
        {"Rotation Map": white},
        width,
        height,
    )
    assert float(np.mean(np.abs(baseline - rotated))) > 0.04

    displaced = render(
        {"pattern": "Disc", "x_amount": 3, "y_amount": 2, "size_x": 0.55, "size_y": 0.55, "displacement_intensity": 0.4},
        {"Displacement Map": white},
        width,
        height,
    )
    undisplaced = render(
        {"pattern": "Disc", "x_amount": 3, "y_amount": 2, "size_x": 0.55, "size_y": 0.55},
        width=width,
        height=height,
    )
    assert float(np.mean(np.abs(displaced - undisplaced))) > 0.04

    vector = np.zeros((height, width, 4), dtype=np.float32)
    vector[..., 0] = 1.0
    vector[..., 1] = 0.5
    vector[..., 3] = 1.0
    vector_shifted = render(
        {"pattern": "Disc", "x_amount": 3, "y_amount": 2, "size_x": 0.55, "size_y": 0.55, "vector_displacement": 0.35},
        {"Vector Map": vector},
        width,
        height,
    )
    assert float(np.mean(np.abs(vector_shifted - undisplaced))) > 0.04

    mask = np.zeros((height, width), dtype=np.float32)
    mask[:, width // 2 :] = 1.0
    masked = render(
        {"pattern": "Square", "x_amount": 4, "y_amount": 2, "mask_map_threshold": 0.5},
        {"Mask Map": grayscale_rgba(mask)},
        width,
        height,
    )
    assert float(masked[:, : width // 2].mean()) + 0.25 < float(masked[:, width // 2 :].mean())

    # No connected mask remains neutral even when Invert is enabled.
    no_mask = render(
        {"pattern": "Square", "x_amount": 4, "y_amount": 2, "mask_map_invert": True},
        width=width,
        height=height,
    )
    assert float(no_mask.mean()) > 0.3


def assert_rendering_order() -> None:
    parameters = {
        "pattern": "Square",
        "x_amount": 2,
        "y_amount": 2,
        "size_x": 1.8,
        "size_y": 1.8,
        "luminance_random": 0.8,
        "blend_mode": "Replace",
        "seed": 91,
    }
    forward = render(parameters, width=64, height=64)
    reverse = render({**parameters, "reverse_rendering_order": True}, width=64, height=64)
    columns = render({**parameters, "rendering_order": "Columns then Rows"}, width=64, height=64)
    assert float(np.mean(np.abs(forward - reverse))) > 0.01
    assert float(np.mean(np.abs(forward - columns))) > 0.0001


def assert_background_and_compositing() -> None:
    height, width = 72, 104
    background = np.full((height, width), 0.35, dtype=np.float32)
    replaced = render(
        {
            "pattern": "Disc",
            "x_amount": 4,
            "y_amount": 3,
            "size_x": 0.55,
            "size_y": 0.55,
            "luminance_random": 0.1,
            "blend_mode": "Replace",
        },
        {"Background Input": grayscale_rgba(background)},
        width,
        height,
    )
    assert float(replaced.min()) >= 0.34
    assert float(replaced.max()) > 0.8

    subtracted = render(
        {
            "pattern": "Square",
            "x_amount": 4,
            "y_amount": 3,
            "size_x": 0.6,
            "size_y": 0.6,
            "luminance_random": 0.0,
            "global_opacity": 0.2,
            "blend_mode": "Subtract",
        },
        {"Background Input": grayscale_rgba(background)},
        width,
        height,
    )
    assert float(subtracted.min()) < 0.2
    assert float(subtracted.max()) <= 0.351


def main() -> int:
    assert_backend_integration()
    assert_registry_contract()
    assert_large_overlap_radius()
    assert_default_grid_and_shapes()
    assert_deterministic_randomisation()
    assert_stagger_and_custom_pattern()
    assert_offset_modes_and_layout_masks()
    assert_unbiased_luminance_random()
    assert_custom_pattern_rasterisation_modes()
    assert_multi_pattern_distribution()
    assert_map_driven_controls()
    assert_rendering_order()
    assert_background_and_compositing()
    print(
        "Tile Sampler test passed: expanded registry/GPU bindings, dynamic overlap lookup, built-in and multiple custom patterns, "
        "deterministic distribution, artist-friendly offsets, layout masks, unbiased luminance, custom-pattern filtered/point sampling, map-driven scale/rotation/displacement/vector/mask controls, rendering order, background and compositing"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
