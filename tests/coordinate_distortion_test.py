#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.engine.backends.cpu import CpuBackend
from vfx_texture_lab.engine.backends.wgpu_backend import WgpuBackend
from vfx_texture_lab.engine.formats import RenderContext, TextureFormat
from vfx_texture_lab.engine.resources import CpuImage
from vfx_texture_lab.graph import GraphScene
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext


VISIBLE_IDS = (
    "coordinates.uv_gradient",
    "coordinates.cartesian_to_polar",
    "coordinates.polar_to_cartesian",
    "transform.tile",
    "transform.offset",
    "transform.rotate",
    "transform.scale",
    "transform.mirror",
    "distortion.swirl",
    "distortion.spherize",
    "distortion.vector_warp",
    "distortion.flow_map",
    "org.vfxtexturelab.directional_warp",
)


def pattern(width: int = 32, height: int = 24) -> np.ndarray:
    y, x = np.mgrid[0:height, 0:width]
    u = (x.astype(np.float32) + 0.5) / width
    v = (y.astype(np.float32) + 0.5) / height
    out = np.empty((height, width, 4), dtype=np.float32)
    out[..., 0] = u
    out[..., 1] = v
    out[..., 2] = np.mod(np.floor(u * 8.0) + np.floor(v * 6.0), 2.0)
    out[..., 3] = 1.0
    return out


def run_cpu(definition, inputs: dict[str, np.ndarray], overrides: dict | None = None) -> np.ndarray:
    first = next(iter(inputs.values()), np.empty((24, 32, 4), dtype=np.float32))
    context = EvalContext(first.shape[1], first.shape[0])
    params = definition.default_parameters()
    if overrides:
        params.update(overrides)
    assert definition.evaluator is not None
    return definition.evaluator(inputs, params, context)


def main() -> int:
    app = QApplication.instance() or QApplication([])
    registry = build_registry()
    visible = {definition.type_id for definition in registry.all()}
    for type_id in VISIBLE_IDS:
        assert type_id in visible, type_id
    assert "org.vfxtexturelab.polar_coordinates" not in visible
    assert registry.get("org.vfxtexturelab.polar_coordinates").hidden

    image = pattern()
    neutral_vector = np.full_like(image, 0.5)
    neutral_vector[..., 3] = 1.0

    uv = run_cpu(registry.get("coordinates.uv_gradient"), {})
    assert uv.shape == (24, 32, 4)
    assert np.allclose(uv[0, 0], [0.5 / 32.0, 0.5 / 24.0, 0.5, 1.0], atol=1e-7)
    assert np.allclose(uv[-1, -1], [31.5 / 32.0, 23.5 / 24.0, 0.5, 1.0], atol=1e-7)

    identity_cases = {
        "transform.offset": ({"Image": image}, {"offset_x": 0.0, "offset_y": 0.0, "wrap": True}),
        "transform.rotate": ({"Image": image}, {"angle": 0.0, "wrap": True}),
        "transform.scale": ({"Image": image}, {"scale_x": 1.0, "scale_y": 1.0, "wrap": True}),
        "distortion.swirl": ({"Image": image}, {"angle": 0.0, "radius": 0.5, "wrap": True}),
        "distortion.spherize": ({"Image": image}, {"amount": 0.0, "radius": 0.5, "wrap": True}),
        "distortion.vector_warp": ({"Image": image, "Vector": neutral_vector}, {"strength": 0.8, "wrap": True}),
        "distortion.flow_map": ({"Image": image, "Flow": neutral_vector}, {"strength": 0.8, "phase": 0.37, "wrap": True}),
        "org.vfxtexturelab.directional_warp": (
            {"Image": image, "Intensity": neutral_vector},
            {"strength": 0.8, "angle": 37.0, "centered": True, "wrap": True},
        ),
    }
    for type_id, (inputs, overrides) in identity_cases.items():
        result = run_cpu(registry.get(type_id), inputs, overrides)
        assert np.allclose(result, image, atol=2e-6), type_id

    # A missing vector field is deliberately neutral rather than black, so a
    # freshly inserted warp node remains a pass-through until connected.
    disconnected_vector = run_cpu(
        registry.get("distortion.vector_warp"), {"Image": image}, {"strength": 1.0, "wrap": True}
    )
    disconnected_flow = run_cpu(
        registry.get("distortion.flow_map"), {"Image": image}, {"strength": 1.0, "phase": 0.37, "wrap": True}
    )
    assert np.allclose(disconnected_vector, image, atol=2e-6)
    assert np.allclose(disconnected_flow, image, atol=2e-6)

    mirrored = run_cpu(registry.get("transform.mirror"), {"Image": image}, {"axis": "Horizontal"})
    assert np.allclose(mirrored, image[:, ::-1], atol=2e-6)
    mirrored_both = run_cpu(registry.get("transform.mirror"), {"Image": image}, {"axis": "Both"})
    assert np.allclose(mirrored_both, image[::-1, ::-1], atol=2e-6)

    offset = run_cpu(
        registry.get("transform.offset"), {"Image": image},
        {"offset_x": 1.0 / image.shape[1], "offset_y": 0.0, "wrap": True},
    )
    assert np.allclose(offset, np.roll(image, 1, axis=1), atol=2e-6)

    tiled = run_cpu(registry.get("transform.tile"), {"Image": image}, {"tiles_x": 2.0, "tiles_y": 1.0})
    assert np.allclose(tiled[:, : image.shape[1] // 2], tiled[:, image.shape[1] // 2 :], atol=3e-5)

    # Explicit typed vector sockets accept UV Gradient / Flow Direction style maps,
    # but reject ordinary greyscale branches without an explicit conversion.
    scene = GraphScene(registry)
    source = scene.create_node("generator.color", QPointF(), record_undo=False)
    uv_node = scene.create_node("coordinates.uv_gradient", QPointF(), record_undo=False)
    warp = scene.create_node("distortion.vector_warp", QPointF(), record_undo=False)
    grey = scene.create_node("generator.constant", QPointF(), record_undo=False)
    assert scene.add_connection(source.output_port, warp.input_ports["Image"], record_undo=False)
    assert scene.can_connect(uv_node.output_port, warp.input_ports["Vector"])[0]
    assert not scene.can_connect(grey.output_port, warp.input_ports["Vector"])[0]
    assert warp.output_port.kind == "color"

    # Cartesian -> Polar -> Cartesian should preserve the broad structure away
    # from the polar seam and outer boundary. It is intentionally a resampling
    # operation, so compare with a practical filtering tolerance.
    cart_to_polar = registry.get("coordinates.cartesian_to_polar")
    polar_to_cart = registry.get("coordinates.polar_to_cartesian")
    polar = run_cpu(cart_to_polar, {"Image": image}, {"wrap": True})
    restored = run_cpu(polar_to_cart, {"Image": polar}, {"wrap": True})
    centre_patch = np.s_[5:-5, 7:-7, :3]
    assert float(np.mean(np.abs(restored[centre_patch] - image[centre_patch]))) < 0.13

    cpu_backend = CpuBackend()
    gpu_backend = WgpuBackend()
    if gpu_backend.available:
        # Use periodic smooth data for numerical parity. Sharp, non-seamless test
        # patterns amplify tiny half-float coordinate differences at a wrapped
        # boundary even though both renderers are sampling the intended seam.
        yy, xx = np.mgrid[0:image.shape[0], 0:image.shape[1]]
        gu = (xx.astype(np.float32) + 0.5) / image.shape[1]
        gv = (yy.astype(np.float32) + 0.5) / image.shape[0]
        gpu_image = np.empty_like(image)
        gpu_image[..., 0] = 0.5 + 0.32 * np.sin(gu * np.pi * 2.0)
        gpu_image[..., 1] = 0.5 + 0.28 * np.cos(gv * np.pi * 2.0)
        gpu_image[..., 2] = 0.5 + 0.20 * np.sin((gu + gv) * np.pi * 2.0)
        gpu_image[..., 3] = 1.0
        gpu_vector = np.empty_like(image)
        gpu_vector[..., 0] = 0.5 + 0.35 * np.sin(gv * np.pi * 2.0)
        gpu_vector[..., 1] = 0.5 + 0.35 * np.cos(gu * np.pi * 2.0)
        gpu_vector[..., 2] = 0.5
        gpu_vector[..., 3] = 1.0
        image_resource = CpuImage(
            gpu_image, TextureFormat.RGBA16F, "coordinate:image", data_kind="color", precision="16-bit"
        )
        vector_resource = CpuImage(
            gpu_vector, TextureFormat.RGBA16F, "coordinate:vector", data_kind="vector", precision="16-bit"
        )
        scalar = np.full_like(image, 0.65)
        scalar[..., 3] = 1.0
        scalar_resource = CpuImage(
            scalar, TextureFormat.R16F, "coordinate:scalar", data_kind="grayscale", precision="16-bit"
        )
        cases = {
            "coordinates.uv_gradient": ({}, {}),
            "coordinates.cartesian_to_polar": ({"Image": image_resource}, {"angle_offset": 21.0, "wrap": True}),
            "coordinates.polar_to_cartesian": ({"Image": image_resource}, {"radius_scale": 0.86, "wrap": True}),
            "transform.tile": ({"Image": image_resource}, {"tiles_x": 2.3, "tiles_y": 1.7}),
            "transform.offset": ({"Image": image_resource}, {"offset_x": 0.13, "offset_y": -0.08, "wrap": True}),
            "transform.rotate": ({"Image": image_resource}, {"angle": 31.0, "wrap": True}),
            "transform.scale": ({"Image": image_resource}, {"scale_x": 1.25, "scale_y": 0.72, "wrap": True}),
            "transform.mirror": ({"Image": image_resource}, {"axis": "Vertical"}),
            "distortion.swirl": ({"Image": image_resource}, {"angle": 220.0, "radius": 0.62, "wrap": True}),
            "distortion.spherize": ({"Image": image_resource}, {"amount": -0.55, "radius": 0.7, "wrap": True}),
            "distortion.vector_warp": ({"Image": image_resource, "Vector": vector_resource}, {"strength": 0.12, "wrap": True}),
            "distortion.flow_map": ({"Image": image_resource, "Flow": vector_resource}, {"strength": 0.16, "phase": 0.31, "wrap": True}),
            "org.vfxtexturelab.directional_warp": (
                {"Image": image_resource, "Intensity": scalar_resource},
                {"strength": 0.12, "angle": 47.0, "centered": True, "wrap": True},
            ),
        }
        for index, (type_id, (resources, overrides)) in enumerate(cases.items()):
            definition = registry.get(type_id)
            params = definition.default_parameters()
            params.update(overrides)
            render_context = RenderContext(image.shape[1], image.shape[0], TextureFormat.RGBA16F)
            cpu_result = cpu_backend.evaluate_node(
                definition, resources, params, render_context, f"coordinates:cpu:{index}"
            )
            gpu_inputs = {
                name: gpu_backend.ensure_gpu(resource, render_context)
                for name, resource in resources.items()
            }
            gpu_result = gpu_backend.to_cpu(
                gpu_backend.evaluate_node(
                    definition, gpu_inputs, params, render_context, f"coordinates:gpu:{index}",
                    logical_format=TextureFormat.RGBA16F,
                )
            )
            difference = np.abs(cpu_result.array[..., :3] - gpu_result.array[..., :3])
            # llvmpipe's trigonometric approximations can move a handful of
            # samples across a wrapped seam. The image-wide error remains tiny.
            assert float(np.mean(difference)) < 4.0e-3, type_id
            assert float(np.quantile(difference, 0.95)) < 4.0e-3, type_id

        for index, type_id in enumerate(("distortion.vector_warp", "distortion.flow_map"), start=100):
            definition = registry.get(type_id)
            params = definition.default_parameters()
            params.update({"strength": 1.0, "phase": 0.37, "wrap": True})
            render_context = RenderContext(image.shape[1], image.shape[0], TextureFormat.RGBA16F)
            gpu_image_resource = gpu_backend.ensure_gpu(image_resource, render_context)
            result = gpu_backend.to_cpu(
                gpu_backend.evaluate_node(
                    definition, {"Image": gpu_image_resource}, params, render_context,
                    f"coordinates:gpu-neutral:{index}", logical_format=TextureFormat.RGBA16F,
                )
            )
            assert np.allclose(result.array[..., :3], gpu_image[..., :3], atol=1.5e-3), type_id
    else:
        print("GPU coordinate/distortion comparison skipped:", gpu_backend.info().detail)

    print(
        "Coordinate/distortion test passed: typed UV vectors, dedicated transforms, polar conversions, "
        "radial distortions, vector/flow warps, legacy compatibility and CPU/GPU parity"
    )
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
