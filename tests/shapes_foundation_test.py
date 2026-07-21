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
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext


SHAPES = (
    "Rectangle", "Rounded Rectangle", "Disc", "Ring", "Capsule", "Triangle",
    "Diamond", "Hexagon", "Cross", "X", "Crescent", "Bell", "Gaussian",
    "Pyramid", "Cone", "Hemisphere", "Waves", "Linear Gradation",
)


def assert_registry_contract() -> None:
    registry = build_registry()
    assert not registry.contains("shape.circle")
    assert not registry.contains("shape.rectangle")
    assert {"shape.shape", "shape.polygon", "shape.polygon_burst"} <= {
        definition.type_id for definition in registry.all()
    }
    shape = registry.get("shape.shape")
    polygon = registry.get("shape.polygon")
    burst = registry.get("shape.polygon_burst")
    assert shape.gpu_kernel == "shape.wgsl"
    assert polygon.gpu_kernel == "polygon.wgsl"
    assert burst.gpu_kernel == "polygon_burst.wgsl"
    specs = {spec.name: spec for spec in shape.parameters}
    assert specs["shape"].options == SHAPES
    assert specs["corner_radius"].visible_when == (("shape", ("Rounded Rectangle",)),)
    assert specs["bar_thickness"].visible_when == (("shape", ("Cross", "X")),)
    assert specs["wave_frequency"].visible_when == (("shape", ("Waves",)),)
    assert specs["rotation"].editor == "angle"
    assert {spec.group for spec in shape.parameters} >= {"Shape", "Transform", "Profile", "Shape-Specific"}


def assert_cpu_variants() -> None:
    registry = build_registry()
    context = EvalContext(111, 83)
    shape = registry.get("shape.shape")
    for name in SHAPES:
        params = shape.default_parameters()
        params.update({
            "shape": name,
            "rotation": 23.0,
            "size_x": 0.84,
            "size_y": 1.17,
            "tile_x": 2.0,
            "tile_y": 3.0,
            "edge_softness": 0.025,
            "corner_radius": 0.31,
            "thickness": 0.23,
            "capsule_length": 0.67,
            "bar_thickness": 0.29,
            "cutout_size": 0.74,
            "cutout_offset_x": 0.39,
            "wave_frequency": 5.3,
            "wave_phase": 27.0,
            "wave_balance": 0.37,
        })
        image = shape.evaluator({}, params, context)
        assert image.shape == (83, 111, 4), name
        assert np.isfinite(image).all(), name
        assert 0.0 <= float(image.min()) <= float(image.max()) <= 1.0, name
        assert float(image[..., 0].max()) > 0.05, name

    polygon = registry.get("shape.polygon")
    for sides, inner_radius in ((3, 1.0), (5, 0.42), (6, 1.0), (12, 0.72), (64, 0.93)):
        for fill_mode in ("Solid", "Outline", "Linear Bevel", "Rounded Bevel"):
            params = polygon.default_parameters()
            params.update({
                "sides": sides,
                "inner_radius": inner_radius,
                "fill_mode": fill_mode,
                "roundness": 0.035,
                "rotation": -19.0,
                "twist": 14.0,
                "radial_distortion": 0.16,
            })
            image = polygon.evaluator({}, params, context)
            assert np.isfinite(image).all(), (sides, inner_radius, fill_mode)
            assert 0.0 <= float(image.min()) <= float(image.max()) <= 1.0

    burst = registry.get("shape.polygon_burst")
    for mode in ("Solid", "Radial Gradient", "Angular Gradient"):
        params = burst.default_parameters()
        params.update({
            "sides": 11,
            "fill_mode": mode,
            "explode": 0.09,
            "slice_gap": 0.21,
            "inner_radius": 0.24,
            "alternate_value": True,
            "alternate_strength": 0.36,
            "rotation": 17.0,
            "twist": 31.0,
        })
        image = burst.evaluator({}, params, context)
        assert np.isfinite(image).all(), mode
        assert 0.0 <= float(image.min()) <= float(image.max()) <= 1.0


def assert_cpu_gpu_agreement() -> None:
    registry = build_registry()
    gpu = WgpuBackend()
    if not gpu.available:
        print("Shape GPU comparisons skipped:", gpu.info().detail)
        return
    cpu = CpuBackend(gpu)
    context = RenderContext(61, 47, TextureFormat.RGBA16F)

    cases: list[tuple[str, dict]] = []
    for name in SHAPES:
        cases.append(("shape.shape", {
            "shape": name,
            "fill_mode": "Rounded Bevel",
            "center_x": 0.43,
            "center_y": 0.57,
            "size_x": 0.91,
            "size_y": 1.13,
            "scale": 0.77,
            "rotation": 21.0,
            "tile_x": 2.0,
            "tile_y": 1.0,
            "edge_softness": 0.023,
            "profile_width": 0.21,
            "corner_radius": 0.32,
            "thickness": 0.24,
            "capsule_length": 0.66,
            "bar_thickness": 0.28,
            "cutout_size": 0.73,
            "cutout_offset_x": 0.38,
            "cutout_offset_y": -0.07,
            "wave_frequency": 5.1,
            "wave_phase": 34.0,
            "wave_balance": 0.41,
        }))
    for fill_mode in ("Solid", "Outline", "Linear Bevel", "Rounded Bevel"):
        cases.append(("shape.polygon", {
            "sides": 7,
            "inner_radius": 0.47,
            "alternating_offset": 0.08,
            "roundness": 0.04,
            "fill_mode": fill_mode,
            "center_x": 0.46,
            "center_y": 0.54,
            "size_x": 1.07,
            "size_y": 0.86,
            "scale": 0.79,
            "rotation": -27.0,
            "tile_x": 2.0,
            "tile_y": 1.0,
            "edge_softness": 0.022,
            "profile_width": 0.23,
            "twist": 18.0,
            "radial_distortion": 0.13,
        }))
    for fill_mode in ("Solid", "Radial Gradient", "Angular Gradient"):
        cases.append(("shape.polygon_burst", {
            "sides": 13,
            "fill_mode": fill_mode,
            "explode": 0.08,
            "slice_gap": 0.19,
            "inner_radius": 0.22,
            "alternate_value": True,
            "alternate_strength": 0.39,
            "center_x": 0.48,
            "center_y": 0.53,
            "size_x": 0.94,
            "size_y": 1.06,
            "scale": 0.81,
            "rotation": 16.0,
            "tile_x": 2.0,
            "tile_y": 1.0,
            "edge_softness": 0.021,
            "twist": 29.0,
        }))

    for type_id, authored in cases:
        definition = registry.get(type_id)
        params = definition.default_parameters()
        params.update(authored)
        cpu_result = cpu.evaluate_node(definition, {}, params, context, f"shape-cpu:{type_id}:{authored}")
        gpu_result = gpu.to_cpu(gpu.evaluate_node(definition, {}, params, context, f"shape-gpu:{type_id}:{authored}"))
        difference = np.abs(cpu_result.array - gpu_result.array)
        assert float(difference.mean()) < 2.0e-4, (type_id, authored, difference.mean(), difference.max())
        assert float(difference.max()) < 3.0e-3, (type_id, authored, difference.mean(), difference.max())


def main() -> int:
    app = QApplication.instance() or QApplication([])
    assert_registry_contract()
    assert_cpu_variants()
    assert_cpu_gpu_agreement()
    app.processEvents()
    print("Shapes foundation test passed: consolidated Shape modes, stars/polygons, Polygon Burst variants, conditional parameter metadata and CPU/GPU reference agreement")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
