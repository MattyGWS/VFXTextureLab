from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.engine.backends.wgpu_backend import WgpuBackend
from vfx_texture_lab.engine.formats import RenderContext, TextureFormat
from vfx_texture_lab.engine.resources import CpuImage
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.document import DocumentSettings
from vfx_texture_lab.graph.scene import GraphScene
from vfx_texture_lab.nodes.base import EvalContext
from vfx_texture_lab.nodes.image_ops import grayscale_rgba
from vfx_texture_lab.ui.preview import PreviewCanvas


def _assert_binary(image: np.ndarray, label: str) -> None:
    channel = np.asarray(image[..., 0], dtype=np.float32)
    assert np.all((channel == 0.0) | (channel == 1.0)), (
        label,
        np.unique(channel)[:20],
    )


def assert_shape_sources_are_antialiased_by_default() -> None:
    registry = build_registry()
    cases = (
        ("shape.shape", {"shape": "Triangle"}),
        ("shape.polygon", {"sides": 3}),
        ("shape.polygon_burst", {"fill_mode": "Solid"}),
        ("pattern.tile_sampler", {"pattern": "Triangle", "x_amount": 5, "y_amount": 5, "size_x": 0.8, "size_y": 0.8}),
    )
    for type_id, authored in cases:
        definition = registry.get(type_id)
        parameters = definition.default_parameters()
        assert parameters["edge_softness"] == 0.0, (type_id, parameters["edge_softness"])
        assert parameters["rasterization"] == "Antialiased"
        parameters.update(authored)
        antialiased = definition.evaluator({}, parameters, EvalContext(128, 128))[..., 0]
        assert np.any((antialiased > 0.0) & (antialiased < 1.0)), type_id

        parameters["rasterization"] = "Pixel Exact"
        for size in (32, 127, 128, 257):
            exact = definition.evaluator({}, parameters, EvalContext(size, size))
            _assert_binary(exact, f"{type_id}@{size}")

        parameters["edge_softness"] = 0.02
        softened = definition.evaluator({}, parameters, EvalContext(128, 128))[..., 0]
        assert np.any((softened > 0.0) & (softened < 1.0)), type_id



def assert_gpu_rasterisation_modes() -> None:
    registry = build_registry()
    gpu = WgpuBackend()
    if not gpu.available:
        print("Pixel-accurate GPU checks skipped:", gpu.info().detail)
        return
    context = RenderContext(128, 128, TextureFormat.RGBA16F)
    cases = (
        ("shape.shape", {"shape": "Triangle"}),
        ("shape.polygon", {"sides": 3}),
        ("shape.polygon_burst", {"fill_mode": "Solid"}),
        ("pattern.tile_sampler", {"pattern": "Triangle", "x_amount": 5, "y_amount": 5, "size_x": 0.8, "size_y": 0.8}),
    )
    for type_id, authored in cases:
        definition = registry.get(type_id)
        parameters = definition.default_parameters()
        parameters.update(authored)
        antialiased = gpu.to_cpu(
            gpu.evaluate_node(
                definition, {}, parameters, context, f"pixel-aa:{type_id}"
            )
        ).array[..., 0]
        assert np.any((antialiased > 0.0) & (antialiased < 1.0)), type_id
        parameters["rasterization"] = "Pixel Exact"
        exact = gpu.to_cpu(
            gpu.evaluate_node(
                definition, {}, parameters, context, f"pixel-exact:{type_id}"
            )
        ).array
        _assert_binary(exact, f"GPU {type_id}")




def assert_gpu_custom_pattern_rasterisation_modes() -> None:
    registry = build_registry()
    definition = registry.get("pattern.tile_sampler")
    source_size = 128
    y, x = np.mgrid[0:source_size, 0:source_size]
    taper = np.maximum(1.0, source_size * 0.035 * (1.0 - y / source_size * 0.72))
    centre = source_size * 0.5 + 0.12 * (source_size - y)
    blade = (
        (np.abs(x - centre) < taper)
        & (y > source_size * 0.04)
        & (y < source_size * 0.96)
    ).astype(np.float32)
    source = grayscale_rgba(blade)
    parameters = definition.default_parameters()
    parameters.update({
        "pattern": "Pattern Input",
        "x_amount": 12,
        "y_amount": 12,
        "size_x": 0.82,
        "size_y": 0.82,
        "rotation_random": 180.0,
        "seed": 19,
        "edge_softness": 0.0,
        "_pattern_connected_mask": 1,
    })

    cpu_exact_parameters = dict(parameters, rasterization="Pixel Exact")
    cpu_aa_parameters = dict(parameters, rasterization="Antialiased")
    cpu_exact = definition.evaluator({"Pattern Input": source}, cpu_exact_parameters, EvalContext(128, 128))[..., 0]
    cpu_aa = definition.evaluator({"Pattern Input": source}, cpu_aa_parameters, EvalContext(128, 128))[..., 0]
    assert np.count_nonzero((cpu_exact > 1.0e-6) & (cpu_exact < 1.0 - 1.0e-6)) == 0
    assert np.count_nonzero((cpu_aa > 1.0e-6) & (cpu_aa < 1.0 - 1.0e-6)) > 250

    gpu = WgpuBackend()
    if not gpu.available:
        print("Tile Sampler custom-pattern GPU checks skipped:", gpu.info().detail)
        return
    resource = CpuImage(
        source, TextureFormat.R16F, "custom-pattern", frozenset({"cpu"}), "grayscale", "16-bit"
    )
    context = RenderContext(128, 128, TextureFormat.R16F)
    gpu_exact = gpu.to_cpu(gpu.evaluate_node(
        definition, {"Pattern Input": resource}, cpu_exact_parameters, context, "custom-pattern-exact"
    )).array[..., 0]
    gpu_aa = gpu.to_cpu(gpu.evaluate_node(
        definition, {"Pattern Input": resource}, cpu_aa_parameters, context, "custom-pattern-aa"
    )).array[..., 0]

    assert np.count_nonzero((gpu_exact > 1.0e-6) & (gpu_exact < 1.0 - 1.0e-6)) == 0
    assert np.count_nonzero((gpu_aa > 1.0e-6) & (gpu_aa < 1.0 - 1.0e-6)) > 250
    assert np.allclose(cpu_exact, gpu_exact, atol=1.0e-5)
    assert np.allclose(cpu_aa, gpu_aa, atol=1.0e-5)
    assert float(np.mean(np.abs(gpu_exact - gpu_aa))) > 0.005


def assert_gpu_tile_sampler_layout_and_luminance() -> None:
    registry = build_registry()
    definition = registry.get("pattern.tile_sampler")
    parameters = definition.default_parameters()
    parameters.update({
        "pattern": "Square",
        "x_amount": 9,
        "y_amount": 7,
        "size_x": 0.72,
        "size_y": 0.66,
        "offset_mode": "Continuous Rows",
        "row_offset": 0.35,
        "layout_mask": "Checker",
        "invert_layout_mask": True,
        "mask_random": 0.17,
        "luminance_random": 1.0,
        "blend_mode": "Replace",
        "rasterization": "Pixel Exact",
        "seed": 456,
    })
    cpu = definition.evaluator({}, parameters, EvalContext(126, 98))[..., 0]

    gpu = WgpuBackend()
    if not gpu.available:
        print("Tile Sampler layout/luminance GPU checks skipped:", gpu.info().detail)
        return
    context = RenderContext(126, 98, TextureFormat.R16F)
    gpu_image = gpu.to_cpu(gpu.evaluate_node(
        definition, {}, parameters, context, "tile-layout-luminance"
    )).array[..., 0]
    assert np.allclose(cpu, gpu_image, atol=1.0e-5)


def assert_document_default_and_legacy_loading() -> None:
    registry = build_registry()
    settings = DocumentSettings(default_geometric_rasterization="Pixel Exact")
    restored = DocumentSettings.from_dict(settings.to_dict())
    assert restored.default_geometric_rasterization == "Pixel Exact"

    scene = GraphScene(registry)
    scene.default_geometric_rasterization = "Pixel Exact"
    new_node = scene.create_node("shape.polygon", __import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(), record_undo=False)
    assert new_node.parameters["rasterization"] == "Pixel Exact"

    legacy = scene.create_node(
        "shape.polygon",
        __import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(10, 10),
        parameters={"sides": 3, "edge_softness": 0.0},
        record_undo=False,
    )
    assert legacy.parameters["rasterization"] == "Pixel Exact"

    new_sampler = scene.create_node(
        "pattern.tile_sampler",
        __import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(20, 20),
        record_undo=False,
    )
    assert new_sampler.parameters["offset_mode"] == "Every Second Row"
    assert new_sampler.parameters["row_offset"] == 0.0
    assert "tile_value" not in new_sampler.parameters
    assert "_legacy_luminance_model" not in new_sampler.parameters

    legacy_sampler = scene.create_node(
        "pattern.tile_sampler",
        __import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(30, 30),
        parameters={
            "offset_mode": "Every Second Row",
            "row_offset": -0.25,
            "tile_value": 0.4,
            "luminance_random": 0.7,
        },
        record_undo=False,
    )
    assert legacy_sampler.parameters["row_offset"] == 0.75
    assert "tile_value" not in legacy_sampler.parameters
    assert "_legacy_luminance_model" not in legacy_sampler.parameters

    legacy_none = scene.create_node(
        "pattern.tile_sampler",
        __import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(40, 40),
        parameters={"offset_mode": "None", "row_offset": 0.4},
        record_undo=False,
    )
    assert legacy_none.parameters["offset_mode"] == "Every Second Row"
    assert legacy_none.parameters["row_offset"] == 0.0


def assert_preview_uses_nearest_neighbour(app: QApplication) -> None:
    source = QImage(2, 1, QImage.Format.Format_RGBA8888)
    source.setPixelColor(0, 0, QColor(0, 0, 0, 255))
    source.setPixelColor(1, 0, QColor(255, 255, 255, 255))

    canvas = PreviewCanvas()
    canvas.resize(304, 304)
    canvas.set_image(source)
    canvas.show()
    app.processEvents()

    rendered = QImage(canvas.size(), QImage.Format.Format_RGBA8888)
    rendered.fill(Qt.GlobalColor.transparent)
    canvas.render(rendered)

    scale = canvas._display_scale()
    origin = canvas._content_origin(scale)
    target_width = source.width() * scale
    target_height = source.height() * scale
    y = int(origin.y() + target_height * 0.5)
    left = int(origin.x()) + 1
    right = int(origin.x() + target_width) - 2
    values = {rendered.pixelColor(x, y).red() for x in range(left, right + 1)}
    assert values == {0, 255}, values

    # The source texels must remain distinct on both sides of the enlarged
    # boundary rather than forming a bilinear grey transition.
    boundary = int(origin.x() + scale)
    assert rendered.pixelColor(boundary - 2, y).red() == 0
    assert rendered.pixelColor(boundary + 2, y).red() == 255

    canvas.close()




def assert_preview_filters_only_when_minifying(app: QApplication) -> None:
    source = QImage(512, 512, QImage.Format.Format_RGBA8888)
    for y in range(512):
        for x in range(512):
            value = 255 if (x + y) % 2 else 0
            source.setPixelColor(x, y, QColor(value, value, value, 255))

    canvas = PreviewCanvas()
    canvas.resize(304, 304)
    canvas.set_image(source)
    canvas.show()
    app.processEvents()

    rendered = QImage(canvas.size(), QImage.Format.Format_RGBA8888)
    rendered.fill(Qt.GlobalColor.transparent)
    canvas.render(rendered)

    scale = canvas._display_scale()
    assert scale < 1.0
    origin = canvas._content_origin(scale)
    sample = rendered.pixelColor(
        int(origin.x() + source.width() * scale * 0.5),
        int(origin.y() + source.height() * scale * 0.5),
    ).red()
    assert 0 < sample < 255, sample
    canvas.close()


def main() -> int:
    app = QApplication.instance() or QApplication([])
    assert_shape_sources_are_antialiased_by_default()
    assert_gpu_rasterisation_modes()
    assert_gpu_custom_pattern_rasterisation_modes()
    assert_gpu_tile_sampler_layout_and_luminance()
    assert_document_default_and_legacy_loading()
    assert_preview_uses_nearest_neighbour(app)
    assert_preview_filters_only_when_minifying(app)
    print(
        "pixel-accurate preview test passed: antialiased primitive and custom-pattern defaults, pixel-exact override, "
        "nearest-neighbour enlargement and filtered high-resolution minification"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
