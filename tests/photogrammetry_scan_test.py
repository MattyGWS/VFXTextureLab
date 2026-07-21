from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from vfx_texture_lab.engine.backends.cpu import CpuBackend
from vfx_texture_lab.engine.backends.wgpu_backend import WgpuBackend
from vfx_texture_lab.engine.formats import RenderContext, TextureFormat
from vfx_texture_lab.engine.resources import CpuImage
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.engine import GraphEvaluator, GraphSnapshot
from vfx_texture_lab.graph import GraphScene
from vfx_texture_lab.material_graph import MATERIAL_PRODUCER_TYPES, MaterialEvaluationSession, material_channel_present
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext


IMAGE_NODE_IDS = (
    "filter.make_it_tile_photo",
    "filter.lighting_equalisation",
    "transform.clone_patch",
    "transform.perspective",
    "transform.atlas_splitter",
)


def rgba(values: np.ndarray, alpha: np.ndarray | float = 1.0) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    if values.ndim == 2:
        rgb = np.repeat(values[..., None], 3, axis=2)
    else:
        rgb = values[..., :3]
    if np.isscalar(alpha):
        a = np.full((*rgb.shape[:2], 1), float(alpha), dtype=np.float32)
    else:
        a = np.asarray(alpha, dtype=np.float32)[..., None]
    return np.concatenate((rgb, a), axis=2).astype(np.float32)


def cpu_eval(registry, type_id: str, image: np.ndarray, params: dict, *, kind: str = "grayscale", mask=None):
    definition = registry.get(type_id)
    authored = definition.default_parameters()
    authored.update(params)
    authored["_resolved_kind"] = kind
    inputs = {"Image": image}
    if mask is not None:
        inputs["Mask"] = mask
    return definition.evaluator(inputs, authored, EvalContext(image.shape[1], image.shape[0]))


def assert_registry(registry) -> None:
    for type_id in IMAGE_NODE_IDS:
        definition = registry.get(type_id)
        assert definition.evaluator is not None
        assert definition.gpu_kernel
    for type_id in ("material.crop", "material.make_it_tile_photo"):
        definition = registry.get(type_id)
        assert definition.input_kind("Material") == "material"
        assert definition.output_kind("Material") == "material"
        assert type_id in MATERIAL_PRODUCER_TYPES
    assert any(item.type_id == "filter.make_it_tile_photo" for item in registry.search("make tile photo"))
    assert any(item.type_id == "transform.clone_patch" for item in registry.search("clone stamp"))
    assert any(item.type_id == "transform.atlas_splitter" for item in registry.search("atlas component"))


def assert_make_it_tile(registry) -> None:
    height, width = 96, 128
    y, x = np.mgrid[0:height, 0:width]
    source = 0.15 + 0.7 * (x / (width - 1)) + 0.08 * np.sin(y * 0.7)
    image = rgba(np.clip(source, 0.0, 1.0))
    result = cpu_eval(
        registry,
        "filter.make_it_tile_photo",
        image,
        {
            "mask_size_h": 0.16,
            "mask_size_v": 0.16,
            "mask_precision_h": 0.55,
            "mask_precision_v": 0.55,
            "mask_warping_h": 45.0,
            "mask_warping_v": 45.0,
        },
    )[..., 0]
    original_boundary = float(np.abs(image[:, 0, 0] - image[:, -1, 0]).mean())
    repaired_boundary = float(np.abs(result[:, 0] - result[:, -1]).mean())
    assert repaired_boundary < original_boundary * 0.12, (original_boundary, repaired_boundary)
    # The new construction keeps the original source untouched through the
    # central region instead of shifting the whole photograph by half a tile.
    central = np.s_[height // 4 : 3 * height // 4, width // 4 : 3 * width // 4]
    assert np.allclose(result[central], image[..., 0][central], atol=1.0e-6)
    assert float(result.std()) > 0.04

    straight = cpu_eval(
        registry,
        "filter.make_it_tile_photo",
        image,
        {"mask_size_h": 0.18, "mask_size_v": 0.18, "mask_warping_h": 0.0, "mask_warping_v": 0.0},
    )[..., 0]
    warped = cpu_eval(
        registry,
        "filter.make_it_tile_photo",
        image,
        {"mask_size_h": 0.18, "mask_size_v": 0.18, "mask_warping_h": 100.0, "mask_warping_v": 100.0},
    )[..., 0]
    edge_band = np.zeros((height, width), dtype=bool)
    edge_band[:, : width // 5] = True
    edge_band[:, -width // 5 :] = True
    edge_band[: height // 5, :] = True
    edge_band[-height // 5 :, :] = True
    assert float(np.abs(straight - warped)[edge_band].mean()) > 0.003


def assert_lighting_equalisation(registry) -> None:
    height, width = 96, 160
    y, x = np.mgrid[0:height, 0:width]
    lighting = 0.3 + 0.65 * x / (width - 1)
    detail = 0.85 + 0.15 * (((x // 3 + y // 3) % 2).astype(np.float32))
    image = rgba(np.clip(lighting * detail, 0.0, 1.0))
    result = cpu_eval(
        registry,
        "filter.lighting_equalisation",
        image,
        {"radius": 34.0, "strength": 1.0, "target_luminance": 0.55},
    )[..., 0]
    source_column_range = float(np.ptp(image[..., 0].mean(axis=0)))
    result_column_range = float(np.ptp(result.mean(axis=0)))
    assert result_column_range < source_column_range * 0.35, (source_column_range, result_column_range)
    assert float(result.std()) > 0.025


def assert_clone_patch(registry) -> None:
    height = width = 96
    image = np.zeros((height, width, 4), dtype=np.float32)
    image[..., 3] = 1.0
    yy, xx = np.mgrid[0:height, 0:width]
    source_circle = (xx - 24) ** 2 + (yy - 24) ** 2 <= 8 ** 2
    image[source_circle, 0] = 1.0
    result = cpu_eval(
        registry,
        "transform.clone_patch",
        image,
        {
            "source_x": 24 / width,
            "source_y": 24 / height,
            "target_x": 72 / width,
            "target_y": 70 / height,
            "radius": 0.12,
            "feather": 0.2,
        },
        kind="color",
    )
    assert float(result[70, 72, 0]) > 0.9
    assert float(result[70, 72, 1]) < 0.05
    assert np.allclose(result[50, 48], image[50, 48], atol=1e-6)


def assert_perspective(registry) -> None:
    height, width = 80, 120
    y, x = np.mgrid[0:height, 0:width]
    source = np.stack((x / (width - 1), y / (height - 1), np.zeros_like(x)), axis=2).astype(np.float32)
    image = rgba(source)
    identity = cpu_eval(registry, "transform.perspective", image, {}, kind="color")
    assert np.allclose(identity, image, atol=0.012)
    trapezoid = cpu_eval(
        registry,
        "transform.perspective",
        image,
        {
            "top_left_x": 0.2,
            "top_left_y": 0.1,
            "top_right_x": 0.8,
            "top_right_y": 0.1,
            "bottom_right_x": 0.95,
            "bottom_right_y": 0.9,
            "bottom_left_x": 0.05,
            "bottom_left_y": 0.9,
        },
        kind="color",
    )
    # The authored handles are destination corners. The complete source is
    # compressed into the trapezoid rather than the trapezoid being sampled and
    # expanded back to the whole output.
    top_left = (round(0.1 * (height - 1)), round(0.2 * (width - 1)))
    top_right = (round(0.1 * (height - 1)), round(0.8 * (width - 1)))
    bottom_right = (round(0.9 * (height - 1)), round(0.95 * (width - 1)))
    assert np.allclose(trapezoid[top_left][0:2], (0.0, 0.0), atol=0.04)
    assert np.allclose(trapezoid[top_right][0:2], (1.0, 0.0), atol=0.04)
    assert np.allclose(trapezoid[bottom_right][0:2], (1.0, 1.0), atol=0.04)
    assert float(trapezoid[0, 0, 3]) < 0.01


def assert_atlas_splitter(registry) -> None:
    height, width = 100, 140
    image = np.zeros((height, width, 4), dtype=np.float32)
    image[..., 3] = 1.0
    image[8:28, 10:30, :3] = (1.0, 0.0, 0.0)
    image[50:92, 65:125, :3] = (0.0, 1.0, 0.0)
    image[16:32, 100:120, :3] = (0.0, 0.0, 1.0)
    largest = cpu_eval(
        registry,
        "transform.atlas_splitter",
        image,
        {
            "selection": 1,
            "order": "Largest First",
            "detection": "Luminance",
            "threshold": 0.02,
            "padding": 0.0,
            "mode": "Fill (Stretch)",
            "isolate_component": True,
        },
        kind="color",
    )
    assert float(largest[..., 1].mean()) > 0.95
    assert float(largest[..., 0].mean()) < 0.02
    third_reading = cpu_eval(
        registry,
        "transform.atlas_splitter",
        image,
        {
            "selection": 3,
            "order": "Reading Order",
            "detection": "Luminance",
            "threshold": 0.02,
            "padding": 0.0,
            "mode": "Fill (Stretch)",
        },
        kind="color",
    )
    assert float(third_reading[..., 1].mean()) > 0.95



def assert_make_it_tile_migration(registry) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    scene = GraphScene(registry)
    image_node = scene.create_node(
        "filter.make_it_tile_photo",
        QPointF(),
        parameters={"seam_width": 0.23, "seam_blur": 18.0, "detail_preservation": 0.71},
        record_undo=False,
    )
    assert np.isclose(float(image_node.parameters["mask_size_h"]), 0.23)
    assert np.isclose(float(image_node.parameters["mask_size_v"]), 0.23)
    assert np.isclose(float(image_node.parameters["mask_precision_h"]), 0.71)
    assert np.isclose(float(image_node.parameters["mask_precision_v"]), 0.71)
    for old_key in ("seam_width", "seam_blur", "detail_preservation"):
        assert old_key not in image_node.parameters


def connect(scene: GraphScene, source, output: str, target, input_name: str) -> None:
    connection = scene.add_connection(
        source.output_ports[output], target.input_ports[input_name], record_undo=False
    )
    assert connection is not None, (source.definition.name, output, target.definition.name, input_name)


def assert_material_wrappers(registry) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    scene = GraphScene(registry)
    height = scene.create_node(
        "generator.linear_gradient", QPointF(),
        parameters={"angle": 0.0, "offset": 0.0, "repeat": False}, record_undo=False,
    )
    normal = scene.create_node(
        "convert.height_normal", QPointF(), parameters={"strength": 5.0}, record_undo=False
    )
    connect(scene, height, "Image", normal, "Height")
    material = scene.create_node(
        "material.pbr", QPointF(),
        parameters={"name": "Scanned Material", "surface_mode": "Alpha Cutout", "cutout_threshold": 0.37},
        record_undo=False,
    )
    connect(scene, height, "Image", material, "Height")
    connect(scene, normal, "Image", material, "Normal")

    crop = scene.create_node(
        "material.crop", QPointF(),
        parameters={"left": 0.25, "right": 0.75, "top": 0.0, "bottom": 1.0},
        record_undo=False,
    )
    connect(scene, material, "Material", crop, "Material")
    evaluator = GraphEvaluator(scene, backend_preference="cpu")
    snapshot = GraphSnapshot.from_scene(scene)
    session = MaterialEvaluationSession(evaluator, snapshot, 64, 48)
    cropped_height = session.evaluate_channel(crop.uid, "Height")
    assert cropped_height.present
    row = cropped_height.image[24, :, 0]
    assert 0.20 < float(row[0]) < 0.31, float(row[0])
    assert 0.69 < float(row[-1]) < 0.80, float(row[-1])
    assert material_channel_present(snapshot, crop.uid, "Height")
    assert material_channel_present(snapshot, crop.uid, "Normal")
    info = session.material_info(crop.uid)
    assert info.name == "Scanned Material"
    assert info.settings["surface_mode"] == "Alpha Cutout"
    assert np.isclose(info.settings["cutout_threshold"], 0.37)

    tile = scene.create_node(
        "material.make_it_tile_photo", QPointF(),
        parameters={
            "mask_size_h": 0.2,
            "mask_size_v": 0.2,
            "mask_precision_h": 0.55,
            "mask_precision_v": 0.55,
            "mask_warping_h": 40.0,
            "mask_warping_v": 40.0,
        },
        record_undo=False,
    )
    connect(scene, material, "Material", tile, "Material")
    snapshot = GraphSnapshot.from_scene(scene)
    session = MaterialEvaluationSession(evaluator, snapshot, 64, 48)
    source_height = session.evaluate_channel(material.uid, "Height").image[..., 0]
    tiled_height = session.evaluate_channel(tile.uid, "Height").image[..., 0]
    source_seam = float(np.abs(source_height[:, 0] - source_height[:, -1]).mean())
    tiled_seam = float(np.abs(tiled_height[:, 0] - tiled_height[:, -1]).mean())
    assert tiled_seam < source_seam * 0.15, (source_seam, tiled_seam)
    tiled_normal = session.evaluate_channel(tile.uid, "Normal")
    assert tiled_normal.present
    vectors = tiled_normal.image[..., :3] * 2.0 - 1.0
    lengths = np.linalg.norm(vectors, axis=2)
    assert float(np.max(np.abs(lengths - 1.0))) < 0.01, (lengths.min(), lengths.max())
    assert material_channel_present(snapshot, tile.uid, "Height")
    assert material_channel_present(snapshot, tile.uid, "Normal")


def assert_gpu(registry) -> None:
    gpu = WgpuBackend()
    if not gpu.available:
        print("Photogrammetry GPU checks skipped:", gpu.info().detail)
        return
    cpu = CpuBackend(gpu)
    context = RenderContext(96, 72, TextureFormat.RGBA16F)
    y, x = np.mgrid[0:context.height, 0:context.width]
    values = np.clip(0.2 + x / context.width * 0.65 + 0.08 * np.sin(y * 0.31), 0.0, 1.0)
    image = rgba(values)
    resource = CpuImage(image, TextureFormat.RGBA16F, "scan-source", frozenset({"cpu"}), "grayscale", "16-bit")
    cases = {
        "filter.make_it_tile_photo": {
            "mask_size_h": 0.17,
            "mask_size_v": 0.13,
            "mask_precision_h": 0.4,
            "mask_precision_v": 0.65,
            "mask_warping_h": 42.0,
            "mask_warping_v": 61.0,
        },
        "filter.lighting_equalisation": {"radius": 16.0, "strength": 0.8, "target_luminance": 0.52},
        "transform.clone_patch": {"source_x": 0.2, "source_y": 0.3, "target_x": 0.7, "target_y": 0.65, "radius": 0.16, "feather": 0.4},
        "transform.perspective": {"top_left_x": 0.08, "top_right_x": 0.92, "bottom_left_x": 0.0, "bottom_right_x": 1.0},
    }
    for type_id, authored in cases.items():
        definition = registry.get(type_id)
        params = definition.default_parameters()
        params.update(authored)
        params["_resolved_kind"] = "grayscale"
        cpu_result = cpu.evaluate_node(definition, {"Image": resource}, params, context, f"cpu:{type_id}")
        gpu_source = gpu.ensure_gpu(resource, context)
        gpu_result = gpu.to_cpu(gpu.evaluate_node(definition, {"Image": gpu_source}, params, context, f"gpu:{type_id}"))
        difference = np.abs(cpu_result.array - gpu_result.array)
        tolerance = 0.018 if type_id in {"filter.make_it_tile_photo", "filter.lighting_equalisation"} else 0.004
        assert float(difference.mean()) < tolerance, (type_id, difference.mean(), difference.max())
        assert float(np.quantile(difference, 0.995)) < max(tolerance * 5.0, 0.025), (type_id, difference.mean(), difference.max())


def main() -> None:
    registry = build_registry()
    assert_registry(registry)
    assert_make_it_tile(registry)
    assert_lighting_equalisation(registry)
    assert_clone_patch(registry)
    assert_perspective(registry)
    assert_atlas_splitter(registry)
    assert_make_it_tile_migration(registry)
    assert_material_wrappers(registry)
    assert_gpu(registry)
    print("Photogrammetry and scan preparation checks passed")


if __name__ == "__main__":
    main()
