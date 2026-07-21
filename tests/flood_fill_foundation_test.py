from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from vfx_texture_lab.engine.backends.cpu import CpuBackend
from vfx_texture_lab.engine.backends.wgpu_backend import WgpuBackend
from vfx_texture_lab.engine.formats import RenderContext, TextureFormat
from vfx_texture_lab.engine.resources import CpuImage
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext
from vfx_texture_lab.nodes.image_ops import grayscale_rgba


FLOOD_NODE_IDS = {
    "filter.flood_fill",
    "filter.flood_fill_random_grayscale",
    "filter.flood_fill_random_colour",
    "filter.flood_fill_to_grayscale",
    "filter.flood_fill_to_colour",
    "filter.flood_fill_to_gradient",
    "filter.flood_fill_to_position",
    "filter.flood_fill_to_bbox_size",
    "filter.flood_fill_to_index",
    "filter.flood_fill_mapper",
}


def sample_mask(width: int, height: int) -> np.ndarray:
    mask = np.zeros((height, width), dtype=np.float32)
    mask[3:15, 4:21] = 1.0
    mask[20:39, 27:55] = 1.0
    mask[8:17, 43:59] = 1.0
    return mask


def flood_data(registry, width: int, height: int) -> np.ndarray:
    definition = registry.get("filter.flood_fill")
    return definition.evaluator(
        {"Binary Mask": grayscale_rgba(sample_mask(width, height))},
        definition.default_parameters(),
        EvalContext(width, height),
    )


def assert_registry_contract() -> None:
    registry = build_registry()
    assert FLOOD_NODE_IDS <= {definition.type_id for definition in registry.all()}
    base = registry.get("filter.flood_fill")
    assert base.output_format == "rgba32f"
    assert base.output_kind("Flood Fill") == "vector"
    assert base.gpu_kernel == "flood_fill.wgsl"
    for type_id in FLOOD_NODE_IDS - {"filter.flood_fill"}:
        assert registry.get(type_id).gpu_kernel
    gradient = registry.get("filter.flood_fill_to_gradient")
    assert {spec.group for spec in gradient.parameters} >= {"Direction", "Slope"}
    assert next(spec for spec in gradient.parameters if spec.name == "angle").editor == "angle"


def assert_cpu_behaviour() -> None:
    registry = build_registry()
    width, height = 64, 48
    data = flood_data(registry, width, height)
    active = data[..., 2] > 0.0
    assert data.shape == (height, width, 4)
    assert np.isfinite(data).all()
    # Three islands have three stable centre pairs and normalised ordered indices.
    centres = np.unique(np.round(data[active, :2], 6), axis=0)
    indices = np.unique(np.round(data[active, 3], 6))
    assert centres.shape[0] == 3
    assert np.allclose(indices, (0.0, 0.5, 1.0))

    for type_id in FLOOD_NODE_IDS - {"filter.flood_fill"}:
        definition = registry.get(type_id)
        inputs = {"Flood Fill": data}
        if type_id == "filter.flood_fill_mapper":
            ramp = np.tile(np.linspace(0.0, 1.0, width, dtype=np.float32), (height, 1))
            inputs["Pattern Input"] = grayscale_rgba(ramp)
        result = definition.evaluator(inputs, definition.default_parameters(), EvalContext(width, height))
        assert result.shape == (height, width, 4), type_id
        assert np.isfinite(result).all(), type_id

    random_definition = registry.get("filter.flood_fill_random_grayscale")
    random_image = random_definition.evaluator(
        {"Flood Fill": data}, random_definition.default_parameters(), EvalContext(width, height)
    )[..., 0]
    for centre in centres:
        island = active & np.isclose(data[..., 0], centre[0]) & np.isclose(data[..., 1], centre[1])
        assert np.unique(np.round(random_image[island], 7)).size == 1
    assert np.unique(np.round(random_image[active], 7)).size == 3

    gradient_definition = registry.get("filter.flood_fill_to_gradient")
    gradient_params = gradient_definition.default_parameters()
    gradient_params.update({"angle": 27.0, "angle_variation": 70.0, "seed": 9})
    gradient = gradient_definition.evaluator(
        {"Flood Fill": data}, gradient_params, EvalContext(width, height)
    )[..., 0]
    assert float(gradient[active].max() - gradient[active].min()) > 0.25

    bbox_definition = registry.get("filter.flood_fill_to_bbox_size")
    bbox = bbox_definition.evaluator(
        {"Flood Fill": data}, bbox_definition.default_parameters(), EvalContext(width, height)
    )[..., 0]
    assert np.unique(np.round(bbox[active], 5)).size >= 2

    # More than 4095 islands remain distinct: index data is no longer packed into 12 bits.
    dense_size = 256
    y, x = np.mgrid[0:dense_size, 0:dense_size]
    dense_mask = ((x % 2) == 0) & ((y % 2) == 0)
    base = registry.get("filter.flood_fill")
    dense = base.evaluator(
        {"Binary Mask": grayscale_rgba(dense_mask.astype(np.float32))},
        base.default_parameters(),
        EvalContext(dense_size, dense_size),
    )
    assert np.unique(dense[..., 3][dense_mask]).size == 16384


def assert_toroidal_seams() -> None:
    registry = build_registry()
    width, height = 32, 24
    mask = np.zeros((height, width), dtype=np.float32)
    # One horizontal and one vertical island cross opposite texture borders.
    mask[5:12, :3] = 1.0
    mask[5:12, -3:] = 1.0
    mask[:3, 13:18] = 1.0
    mask[-3:, 13:18] = 1.0
    base = registry.get("filter.flood_fill")
    data = base.evaluator(
        {"Binary Mask": grayscale_rgba(mask)},
        base.default_parameters(),
        EvalContext(width, height),
    )
    horizontal = np.zeros_like(mask, dtype=bool)
    horizontal[5:12, :3] = True
    horizontal[5:12, -3:] = True
    vertical = np.zeros_like(mask, dtype=bool)
    vertical[:3, 13:18] = True
    vertical[-3:, 13:18] = True

    # Opposite-edge pieces must carry exactly the same island metadata.
    assert np.unique(np.round(data[horizontal], 7), axis=0).shape[0] == 1
    assert np.unique(np.round(data[vertical], 7), axis=0).shape[0] == 1
    assert np.unique(np.round(data[mask > 0.0, 3], 7)).size == 2

    # Wrapped bounding boxes describe the actual island size, not almost the
    # entire texture just because the island crosses a seam.
    horizontal_metadata = data[5, 0]
    vertical_metadata = data[0, 13]
    from vfx_texture_lab.nodes.flood_fill import _unpack_pair
    horizontal_size = _unpack_pair(np.array(horizontal_metadata[2], dtype=np.float32))
    vertical_size = _unpack_pair(np.array(vertical_metadata[2], dtype=np.float32))
    assert abs(float(horizontal_size[0]) / 4095.0 - 6.0 / width) < 1.0 / 4095.0 + 1.0e-6
    assert abs(float(vertical_size[1]) / 4095.0 - 6.0 / height) < 1.0 / 4095.0 + 1.0e-6

    random_definition = registry.get("filter.flood_fill_random_grayscale")
    random_image = random_definition.evaluator(
        {"Flood Fill": data}, random_definition.default_parameters(), EvalContext(width, height)
    )[..., 0]
    assert np.unique(np.round(random_image[horizontal], 7)).size == 1
    assert np.unique(np.round(random_image[vertical], 7)).size == 1

    # Gradient and Mapper use wrapped local coordinates, so their values move
    # continuously through the seam rather than restarting independently.
    gradient_definition = registry.get("filter.flood_fill_to_gradient")
    gradient_params = gradient_definition.default_parameters()
    gradient_params.update({"angle": 0.0, "slope_intensity": 1.0, "flat_value": 0.5})
    gradient = gradient_definition.evaluator(
        {"Flood Fill": data}, gradient_params, EvalContext(width, height)
    )[..., 0]
    seam_gradient = gradient[7, [-3, -2, -1, 0, 1, 2]]
    assert np.all(np.diff(seam_gradient) > 0.0), seam_gradient

    mapper_definition = registry.get("filter.flood_fill_mapper")
    mapper_params = mapper_definition.default_parameters()
    ramp = np.tile(np.linspace(0.0, 1.0, width, dtype=np.float32), (height, 1))
    mapped = mapper_definition.evaluator(
        {"Flood Fill": data, "Pattern Input": grayscale_rgba(ramp)},
        mapper_params,
        EvalContext(width, height),
    )[..., 0]
    seam_mapped = mapped[7, [-3, -2, -1, 0, 1, 2]]
    assert np.all(np.diff(seam_mapped) > 0.0), seam_mapped

    # 8-way topology also wraps diagonally across both axes.
    diagonal_mask = np.zeros((height, width), dtype=np.float32)
    diagonal_mask[0, 0] = 1.0
    diagonal_mask[-1, -1] = 1.0
    params = base.default_parameters()
    params["connectivity"] = "8-way"
    diagonal_data = base.evaluator(
        {"Binary Mask": grayscale_rgba(diagonal_mask)}, params, EvalContext(width, height)
    )
    assert np.allclose(diagonal_data[0, 0], diagonal_data[-1, -1])


def assert_cpu_gpu_agreement() -> None:
    registry = build_registry()
    gpu = WgpuBackend()
    if not gpu.available:
        print("Flood Fill GPU conversions skipped:", gpu.info().detail)
        return
    cpu = CpuBackend(gpu)
    width, height = 61, 47
    data = flood_data(registry, width, height)
    flood = CpuImage(
        data,
        TextureFormat.RGBA32F,
        "flood-data",
        frozenset({"cpu"}),
        data_kind="vector",
        precision="32-bit",
    )
    y, x = np.mgrid[0:height, 0:width]
    ramp_values = ((x + y) / float(width + height - 2)).astype(np.float32)
    ramp = CpuImage(
        grayscale_rgba(ramp_values), TextureFormat.R16F, "ramp", frozenset({"cpu"}), data_kind="grayscale"
    )
    colour_values = np.stack(
        (ramp_values, 1.0 - ramp_values, 0.25 + 0.5 * ramp_values, np.ones_like(ramp_values)), axis=-1
    ).astype(np.float32)
    colour = CpuImage(
        colour_values, TextureFormat.RGBA16F, "colour", frozenset({"cpu"}), data_kind="color"
    )
    context = RenderContext(width, height, TextureFormat.RGBA16F)
    cases = (
        ("filter.flood_fill_random_grayscale", {}, {}),
        ("filter.flood_fill_random_colour", {}, {}),
        ("filter.flood_fill_to_grayscale", {"Value Input": ramp}, {"random": 0.3, "adjustment": 0.1}),
        ("filter.flood_fill_to_colour", {"Colour Input": colour}, {"colour_random": 0.2, "luminance_adjustment": -0.05}),
        ("filter.flood_fill_to_gradient", {"Angle Input": ramp, "Slope Input": ramp}, {"angle": 27.0, "angle_variation": 75.0, "angle_input_multiplier": 0.4, "slope_input_multiplier": 0.7, "multiply_bbox_size": 0.3}),
        ("filter.flood_fill_to_position", {}, {}),
        ("filter.flood_fill_to_bbox_size", {}, {"output": "Area"}),
        ("filter.flood_fill_to_index", {}, {}),
        ("filter.flood_fill_mapper", {"Pattern Input": ramp, "Scale Map": ramp, "Rotation Map": ramp}, {"scale": 0.8, "scale_random": 0.2, "scale_map_multiplier": 0.5, "rotation": 15.0, "rotation_random": 50.0, "rotation_map_multiplier": 0.3, "offset_x": 0.05}),
    )
    for type_id, extra_inputs, authored in cases:
        definition = registry.get(type_id)
        parameters = definition.default_parameters()
        parameters.update(authored)
        inputs = {"Flood Fill": flood, **extra_inputs}
        cpu_result = cpu.evaluate_node(definition, inputs, parameters, context, f"flood-cpu:{type_id}")
        gpu_result = gpu.to_cpu(gpu.evaluate_node(definition, inputs, parameters, context, f"flood-gpu:{type_id}"))
        difference = np.abs(cpu_result.array - gpu_result.array)
        assert float(difference.mean()) < 1.0e-4, (type_id, difference.mean(), difference.max())
        assert float(difference.max()) < 1.0e-3, (type_id, difference.mean(), difference.max())


def main() -> int:
    app = QApplication.instance() or QApplication([])
    assert_registry_contract()
    assert_cpu_behaviour()
    assert_toroidal_seams()
    assert_cpu_gpu_agreement()
    app.processEvents()
    print("Flood Fill foundation test passed: seamless toroidal island analysis, random/value/colour/gradient/position/BBox/index conversions, mapper, large island counts and CPU/GPU agreement")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
