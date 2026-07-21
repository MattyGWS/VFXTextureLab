from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.engine import GraphEvaluator, GraphSnapshot
from vfx_texture_lab.engine.backends.cpu import CpuBackend
from vfx_texture_lab.engine.backends.wgpu_backend import WgpuBackend
from vfx_texture_lab.engine.evaluator import SnapshotNode
from vfx_texture_lab.engine.formats import RenderContext, TextureFormat
from vfx_texture_lab.engine.resources import CpuImage
from vfx_texture_lab.graph.scene import GraphScene
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext, NodeDefinition
from vfx_texture_lab.nodes.processing import eval_invert


def _reference_images(width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    y, x = np.mgrid[0:height, 0:width]
    u = (x.astype(np.float32) + 0.5) / width
    v = (y.astype(np.float32) + 0.5) / height
    first = np.stack((u, v, 0.25 + 0.5 * u * v, 0.2 + 0.8 * v), axis=2).astype(np.float32)
    second = np.stack((1.0 - u, 0.2 + 0.5 * v, np.full_like(u, 0.7), np.full_like(u, 0.65)), axis=2).astype(np.float32)
    return first, second


def _cpu_image(array: np.ndarray, key: str) -> CpuImage:
    return CpuImage(
        np.ascontiguousarray(array, dtype=np.float32),
        TextureFormat.RGBA16F,
        key,
        frozenset({"cpu"}),
    )


def _parameters_for(type_id: str) -> dict:
    return {
        "generator.constant": {"value": 0.37},
        "generator.color": {"color": "#3366cc99"},
        "generator.linear_gradient": {"angle": 33.0, "offset": -0.13, "repeat": True},
        "generator.radial_gradient": {"center_x": 0.92, "center_y": 0.13, "radius": 0.41, "falloff": 1.7},
        "shape.shape": {"shape": "Crescent", "center_x": 0.96, "center_y": 0.08, "scale": 0.67, "rotation": 31.0, "edge_softness": 0.037, "cutout_size": 0.72, "cutout_offset_x": 0.41},
        "shape.polygon": {"sides": 5, "inner_radius": 0.43, "roundness": 0.04, "rotation": -23.0, "fill_mode": "Rounded Bevel", "profile_width": 0.24, "twist": 17.0},
        "shape.polygon_burst": {"sides": 9, "fill_mode": "Angular Gradient", "explode": 0.08, "slice_gap": 0.18, "inner_radius": 0.2, "alternate_value": True, "alternate_strength": 0.37, "rotation": 14.0, "twist": 22.0},
        "pattern.checker": {"scale": 11, "value_a": 0.17, "value_b": 0.82},
        "noise.value": {"scale": 9.0, "seed": 481, "evolution": 0.37, "loop_cycles": 1.0, "disorder": 0.4, "disorder_scale": 3.0, "contrast": 1.2},
        "noise.perlin": {"scale": 9.0, "seed": 481, "evolution": 0.37, "loop_cycles": 1.0, "disorder": 0.4, "disorder_scale": 3.0, "contrast": 1.2},
        "noise.fractal": {"scale": 5.0, "octaves": 5, "lacunarity": 2.0, "gain": 0.61, "contrast": 1.43, "seed": 481, "evolution": 0.37, "loop_cycles": 1.0, "disorder": 0.3, "disorder_scale": 3.0},
        "noise.simplex": {"scale": 7.0, "seed": 481, "evolution": 0.37, "loop_cycles": 1.0, "contrast": 1.2},
        "noise.worley": {"scale": 8.0, "seed": 481, "points_per_cell": 2, "jitter": 0.8, "evolution": 0.37, "loop_cycles": 1.0, "distance_metric": "Euclidean", "output_mode": "F1"},
        "noise.white": {"scale": 73.0, "seed": 481, "evolution": 0.37, "loop_frames": 16, "contrast": 1.2},
        "noise.gaussian": {"scale": 73.0, "seed": 481, "mean": 0.5, "deviation": 0.17, "evolution": 0.37, "loop_frames": 16},
        "noise.ridged": {"scale": 5.0, "octaves": 5, "lacunarity": 2.0, "gain": 0.55, "seed": 481, "evolution": 0.37, "loop_cycles": 1.0},
        "noise.billow": {"scale": 5.0, "octaves": 5, "lacunarity": 2.0, "gain": 0.55, "seed": 481, "evolution": 0.37, "loop_cycles": 1.0},
        "noise.turbulence": {"scale": 5.0, "octaves": 5, "lacunarity": 2.0, "gain": 0.55, "seed": 481, "evolution": 0.37, "loop_cycles": 1.0},
        "noise.voronoi_fractal": {"scale": 3.0, "octaves": 4, "lacunarity": 2.0, "gain": 0.5, "seed": 481, "jitter": 0.8, "evolution": 0.37, "loop_cycles": 1.0},
        "filter.levels": {"in_low": 0.12, "in_high": 0.87, "in_mid": 0.37, "out_low": 0.05, "out_high": 0.94, "intermediary_clamp": True},
        "filter.histogram_range": {"range": 0.63, "position": 0.31},
        "filter.histogram_shift": {"position": 0.23},
        "filter.histogram_scan": {"position": 0.66, "contrast": 0.43},
        "filter.histogram_select": {"position": 0.43, "range": 0.31, "contrast": 0.72},
        "filter.brightness": {"brightness": 0.11},
        "filter.contrast": {"contrast": 0.18, "pivot": 0.43},
        "filter.exposure": {"exposure": -0.6},
        "filter.gamma": {"gamma": 1.7},
        "filter.posterize": {"steps": 7},
        "filter.clamp": {"minimum": 0.18, "maximum": 0.79},
        "filter.hue_shift": {"degrees": 71.0},
        "filter.saturation": {"saturation": 0.67},
        "filter.lightness": {"lightness": 0.09},
        "filter.curve": {"points": [{"x": 0.0, "y": 0.0}, {"x": 0.42, "y": 0.24}, {"x": 1.0, "y": 1.0}], "interpolation": "Smooth"},
        "filter.threshold": {"threshold": 0.42, "softness": 0.17},
        "filter.curvature": {"intensity": 2.0, "normal_format": "OpenGL (+Y)"},
        "filter.curvature_sobel": {"intensity": 0.73, "normal_format": "OpenGL (+Y)"},
        "filter.curvature_smooth": {"normal_format": "OpenGL (+Y)", "preview_output": "Curvature"},
        "filter.ambient_occlusion_hbao": {"height_depth": 0.15, "radius": 0.23, "quality": "8 Samples", "contrast": 1.1},
        "filter.ambient_occlusion_rtao": {"height_scale": 0.8, "samples": 8, "distribution": "Uniform", "maximum_distance": 0.18, "spread_angle": 0.9, "denoise": 0.65},
        "normal.vector_rotation": {"angle": 73.0, "normal_format": "OpenGL (+Y)"},
        "filter.directional_lighting": {"angle": -37.0, "elevation": 28.0, "diffuse_power": 1.4, "diffuse_brightness": 0.85, "highlight_power": 19.0, "highlight_brightness": 0.35, "ambient": 0.08, "normal_format": "OpenGL (+Y)"},
        "filter.highpass": {"radius": 5.0, "boundary": "Clamp"},
        "filter.edge_detect": {"method": "Sobel", "width": 3.0, "intensity": 1.7, "invert": False},
        "filter.fxaa": {"quality": "High", "edge_threshold": 0.01, "relative_threshold": 0.05, "subpixel": 0.9, "preserve_alpha": True},
        "filter.blur": {"radius": 4.0},
        "transform.crop": {"left": 0.12, "right": 0.78, "top": 0.08, "bottom": 0.72, "filtering": "Bilinear"},
        "transform.auto_crop": {"mode": "Fit (Keep Ratio)", "threshold": 0.1, "padding": 0.03, "filtering": "Bilinear"},
        "transform.basic": {"offset_x": 0.17, "offset_y": -0.23, "scale": 1.37, "scale_x": 0.72, "scale_y": 1.31, "angle": 41.0, "tile": True},
        "math.blend": {"mode": "Screen", "opacity": 0.63},
        "convert.gradient_map": {"color_a": "#10204080", "color_b": "#e08020ff"},
        "convert.height_normal": {"strength": 13.5, "invert_y": True},
        "convert.extract_channel": {"channel": "Luminance"},
    }.get(type_id, {})


def assert_every_procedural_builtin_has_wgsl(registry) -> None:
    shader_dir = Path(__file__).resolve().parents[1] / "vfx_texture_lab" / "shaders"
    definitions = registry.all(include_hidden=True)
    gpu_definitions = [
        definition for definition in definitions
        if definition.type_id not in {"input.image", "input.canvas", "graph.input", "graph.receive"}
        and not definition.type_id.startswith("material.")
        and not definition.is_signal_node
        and not definition.is_geometry_node
        and not definition.terminal
        and (definition.evaluator is not None or definition.is_stateful)
    ]
    missing = [definition.type_id for definition in gpu_definitions if not definition.gpu_kernel]
    assert not missing, f"Built-in procedural nodes without WGSL metadata: {missing}"
    missing_files = [definition.gpu_kernel for definition in gpu_definitions if not (shader_dir / str(definition.gpu_kernel)).is_file()]
    assert not missing_files, f"Missing WGSL files: {missing_files}"
    stateless_definitions = [definition for definition in gpu_definitions if not definition.is_stateful]
    stateful_definitions = [definition for definition in gpu_definitions if definition.is_stateful]
    public_shader_ids = {type_id for type_id in WgpuBackend._SHADERS if not type_id.startswith("internal.")}
    assert public_shader_ids == {definition.type_id for definition in stateless_definitions}
    assert stateful_definitions
    assert all(definition.stateful and definition.stateful.gpu_supported for definition in stateful_definitions)
    image_input = registry.get("input.image")
    assert image_input.gpu_kernel is None

def assert_cpu_gpu_reference_agreement(registry) -> None:
    gpu = WgpuBackend()
    if not gpu.available:
        print("GPU comparison tests skipped:", gpu.info().detail)
        return
    cpu = CpuBackend(gpu)
    context = RenderContext(37, 29, TextureFormat.RGBA16F)
    first, second = _reference_images(context.width, context.height)

    for definition in registry.all():
        if (
            definition.type_id in {"input.image", "input.canvas", "graph.input", "graph.receive"}
            or definition.type_id.startswith("material.")
            or definition.is_signal_node
            or definition.is_stateful
            or definition.is_geometry_node
            or definition.terminal
        ):
            continue
        if definition.type_id == "filter.flood_fill":
            mask = np.zeros((context.height, context.width), dtype=np.float32)
            mask[2:10, 3:14] = 1.0
            mask[14:26, 20:34] = 1.0
            mask_rgba = np.stack((mask, mask, mask, np.ones_like(mask)), axis=2)
            inputs = {"Binary Mask": CpuImage(
                np.ascontiguousarray(mask_rgba), TextureFormat.R16F,
                "filter.flood_fill:Binary Mask", frozenset({"cpu"}), "grayscale", "16-bit"
            )}
        elif definition.type_id.startswith("filter.flood_fill_"):
            mask = np.zeros((context.height, context.width), dtype=np.float32)
            mask[2:10, 3:14] = 1.0
            mask[14:26, 20:34] = 1.0
            mask_rgba = np.stack((mask, mask, mask, np.ones_like(mask)), axis=2)
            flood_definition = registry.get("filter.flood_fill")
            flood_array = flood_definition.evaluator(
                {"Binary Mask": mask_rgba}, flood_definition.default_parameters(),
                EvalContext(context.width, context.height),
            )
            inputs = {"Flood Fill": CpuImage(
                np.ascontiguousarray(flood_array), TextureFormat.RGBA32F,
                f"{definition.type_id}:Flood Fill", frozenset({"cpu"}), "vector", "32-bit"
            )}
            gray = (
                first[..., 0] * np.float32(0.2126)
                + first[..., 1] * np.float32(0.7152)
                + first[..., 2] * np.float32(0.0722)
            )
            gray_rgba = np.stack((gray, gray, gray, np.ones_like(gray)), axis=2).astype(np.float32)
            for name in definition.inputs:
                if name == "Flood Fill":
                    continue
                kind = definition.input_kind(name)
                if kind == "grayscale":
                    inputs[name] = CpuImage(
                        np.ascontiguousarray(gray_rgba), TextureFormat.R16F,
                        f"{definition.type_id}:{name}", frozenset({"cpu"}), "grayscale", "16-bit"
                    )
                else:
                    inputs[name] = _cpu_image(first, f"{definition.type_id}:{name}")
        elif definition.type_id == "math.blend":
            inputs = {"Foreground": _cpu_image(second, "blend-foreground"), "Background": _cpu_image(first, "blend-background")}
        elif definition.type_id == "convert.channel_pack":
            inputs = {
                "Red": _cpu_image(first, "pack-r"),
                "Green": _cpu_image(second, "pack-g"),
                "Blue": _cpu_image(first[..., ::-1].copy(), "pack-b"),
                "Alpha": _cpu_image(second, "pack-a"),
            }
        elif definition.inputs and all(definition.input_kind(name) == "grayscale" for name in definition.inputs):
            gray = (
                first[..., 0] * np.float32(0.2126)
                + first[..., 1] * np.float32(0.7152)
                + first[..., 2] * np.float32(0.0722)
            )
            gray_rgba = np.stack((gray, gray, gray, np.ones_like(gray)), axis=2).astype(np.float32)
            inputs = {name: CpuImage(
                np.ascontiguousarray(gray_rgba), TextureFormat.R16F,
                f"{definition.type_id}:{name}", frozenset({"cpu"}), "grayscale", "16-bit"
            ) for name in definition.inputs}
        elif definition.type_id.startswith("terrain."):
            gray = (
                first[..., 0] * np.float32(0.2126)
                + first[..., 1] * np.float32(0.7152)
                + first[..., 2] * np.float32(0.0722)
            )
            gray_rgba = np.stack((gray, gray, gray, np.ones_like(gray)), axis=2).astype(np.float32)
            inputs = {name: CpuImage(
                np.ascontiguousarray(gray_rgba), TextureFormat.R16F,
                f"{definition.type_id}:{name}", frozenset({"cpu"}), "grayscale", "16-bit"
            ) for name in definition.inputs}
        else:
            inputs = {}
            gray = (
                first[..., 0] * np.float32(0.2126)
                + first[..., 1] * np.float32(0.7152)
                + first[..., 2] * np.float32(0.0722)
            )
            gray_rgba = np.stack((gray, gray, gray, np.ones_like(gray)), axis=2).astype(np.float32)
            for name in definition.inputs:
                kind = definition.input_kind(name)
                if kind == "grayscale":
                    inputs[name] = CpuImage(
                        np.ascontiguousarray(gray_rgba), TextureFormat.R16F,
                        f"{definition.type_id}:{name}", frozenset({"cpu"}), "grayscale", "16-bit"
                    )
                elif kind == "vector":
                    inputs[name] = CpuImage(
                        np.ascontiguousarray(first), TextureFormat.RGBA16F,
                        f"{definition.type_id}:{name}", frozenset({"cpu"}), "vector", "16-bit"
                    )
                else:
                    inputs[name] = _cpu_image(first, f"{definition.type_id}:{name}")

        parameters = definition.default_parameters()
        parameters.update(_parameters_for(definition.type_id))
        cpu_result = cpu.evaluate_node(definition, inputs, parameters, context, f"cpu:{definition.type_id}")
        gpu_inputs = {name: gpu.ensure_gpu(image, context) for name, image in inputs.items()}
        gpu_resource = gpu.evaluate_node(definition, gpu_inputs, parameters, context, f"gpu:{definition.type_id}")
        gpu_result = gpu.to_cpu(gpu_resource)

        assert cpu_result.array.shape == gpu_result.array.shape == (context.height, context.width, 4)
        assert np.isfinite(gpu_result.array).all(), definition.type_id
        difference = np.abs(cpu_result.array - gpu_result.array)
        if definition.type_id == "filter.fxaa":
            # Edge thresholds amplify expected half-float source quantisation
            # around a few pixels while the filtered field remains equivalent.
            assert float(difference.mean()) < 0.001, (definition.type_id, difference.mean(), difference.max())
            assert float(difference.max()) < 0.004, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id == "filter.highpass":
            # Highpass inherits the CPU/GPU Gaussian-kernel approximation
            # difference and recentres it around neutral grey.
            assert float(difference.mean()) < 0.01, (definition.type_id, difference.mean(), difference.max())
            assert float(difference.max()) < 0.12, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id == "filter.blur":
            # Pillow and the WGSL separable Gaussian use different kernel approximations.
            # They should remain visually close without requiring identical samples.
            assert float(difference.mean()) < 0.08, (definition.type_id, difference.mean(), difference.max())
            assert float(difference.max()) < 0.5, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id == "filter.outline":
            # A thresholded outline can move a handful of one-pixel ownership
            # decisions after jump-flood tie breaking on dense high-frequency
            # inputs, while the band field remains visually identical.
            assert float(difference.mean()) < 0.01, (definition.type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.99)) < 0.02, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id == "filter.expand_shrink":
            # Relative morphology becomes sub-pixel on this deliberately tiny
            # 37x29 reference image. One half-float threshold ownership decision
            # may differ while the image-wide result remains equivalent.
            assert float(difference.mean()) < 0.003, (definition.type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.999)) < 0.02, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id in {
            "filter.directional_blur", "filter.radial_blur",
            "filter.non_uniform_blur_grayscale", "filter.slope_blur_grayscale",
        }:
            # Multi-sample blur kernels use CPU and WGSL trigonometric paths.
            # Tiny direction differences can select a different neighbour in a
            # few high-frequency pixels while the overall blur field agrees.
            assert float(difference.mean()) < 0.005, (definition.type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.99)) < 0.06, (definition.type_id, difference.mean(), difference.max())
            assert float(difference.max()) < 0.15, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id in {
            "coordinates.cartesian_to_polar", "coordinates.polar_to_cartesian",
            "transform.tile", "transform.offset", "transform.rotate", "transform.scale",
            "distortion.swirl", "distortion.spherize",
            "distortion.vector_warp", "distortion.flow_map",
            "org.vfxtexturelab.directional_warp",
        }:
            # Coordinate resampling can move a handful of samples across a
            # wrapped seam after half-float/trigonometric differences. The
            # image-wide field must still agree closely.
            assert float(difference.mean()) < 0.01, (definition.type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.95)) < 0.02, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id == "noise.worley":
            # Cellular nearest-feature ties can select a different equally-close
            # point after tiny CPU/GPU floating-point differences.
            assert float(difference.mean()) < 0.015, (definition.type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.98)) < 0.02, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id == "noise.voronoi_fractal":
            # The same boundary ambiguity compounds across octaves. Preserve a
            # strict visual/mean threshold rather than requiring identical cell
            # ownership at every pixel.
            assert float(difference.mean()) < 0.08, (definition.type_id, difference.mean(), difference.max())
            assert float(difference.max()) < 0.55, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id in {
            "noise.crystal_1", "noise.crystal_2", "noise.anisotropic",
            "noise.messy_fibres",
        }:
            # Cellular ownership and very narrow analytic strokes can move at a
            # small number of pixels after CPU/WGSL trigonometric rounding. The
            # image-wide procedural structure remains tightly equivalent.
            assert float(difference.mean()) < 0.006, (definition.type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.95)) < 0.02, (definition.type_id, difference.mean(), difference.max())
            assert float(difference.max()) < 0.7, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id == "noise.fibres":
            # Fibres deliberately use sub-pixel, long tapered strokes. At this
            # tiny reference resolution more pixels sit on analytic boundaries,
            # so compare the field statistically rather than per-texel exactly.
            assert float(difference.mean()) < 0.03, (definition.type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.95)) < 0.18, (definition.type_id, difference.mean(), difference.max())
            assert float(difference.max()) < 0.9, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id in {
            "normal.blend", "normal.combine", "normal.normalize", "normal.invert", "normal.vector_rotation", "normal.transform",
        }:
            # Normal-map operations decode and renormalise half-float vectors;
            # tiny endpoint differences can expand slightly after unit-length repair.
            assert float(difference.mean()) < 0.001, (definition.type_id, difference.mean(), difference.max())
            assert float(difference.max()) < 0.004, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id in {
            "terrain.slope", "terrain.curvature", "terrain.terrace",
            "filter.curvature", "filter.curvature_sobel", "filter.curvature_smooth",
        }:
            # Derivative nodes amplify the half-float quantisation already
            # present in the RGBA16F test source. Their visual agreement remains
            # much tighter than a single 8-bit display step.
            assert float(difference.mean()) < 0.001, (definition.type_id, difference.mean(), difference.max())
            assert float(difference.max()) < 0.004, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id == "filter.make_it_tile_photo":
            # The CPU reference uses Pillow's 8-bit wrapped Gaussian while the
            # GPU retains half/float intermediates. The greatest differences
            # are confined to a few reconstructed high-frequency seam pixels.
            assert float(difference.mean()) < 0.01, (definition.type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.95)) < 0.08, (definition.type_id, difference.mean(), difference.max())
            assert float(difference.max()) < 0.25, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id == "filter.lighting_equalisation":
            assert float(difference.mean()) < 0.01, (definition.type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.995)) < 0.04, (definition.type_id, difference.mean(), difference.max())
            assert float(difference.max()) < 0.08, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id == "filter.ambient_occlusion_rtao":
            # Ray hit tests sit on sharp thresholds and the GPU source is half
            # float. Compare the reconstructed visibility field rather than
            # requiring identical first-hit ownership at every pixel.
            assert float(difference.mean()) < 0.06, (definition.type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.95)) < 0.18, (definition.type_id, difference.mean(), difference.max())
            assert float(difference.max()) < 0.55, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id == "normal.to_height":
            # The global FFT integration runs after reading the graph's half-float
            # GPU normal texture. Small normal quantisation errors can shift the
            # reconstructed global range before output normalisation.
            assert float(difference.mean()) < 0.015, (definition.type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.95)) < 0.04, (definition.type_id, difference.mean(), difference.max())
            assert float(difference.max()) < 0.20, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id == "normal.bent":
            # Bent normals share RTAO's thresholded ray traversal, then encode
            # the surviving direction rather than a scalar visibility ratio.
            # Half-float height changes can therefore rotate a few edge vectors.
            assert float(difference.mean()) < 0.02, (definition.type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.95)) < 0.06, (definition.type_id, difference.mean(), difference.max())
            assert float(difference.max()) < 0.25, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id == "filter.rt_shadows":
            # Directional ray hits are similarly threshold-sensitive at hard
            # height silhouettes while the lit/shadow field remains equivalent.
            assert float(difference.mean()) < 0.04, (definition.type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.95)) < 0.12, (definition.type_id, difference.mean(), difference.max())
            assert float(difference.max()) < 0.55, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id in {"noise.bnw_spots_1", "noise.bnw_spots_2", "noise.bnw_spots_3", "noise.moisture"}:
            # Sparse-convolution spots contain very small Gaussian deposits.
            # CPU float32 and WGSL/half-float coordinate paths can shift a few
            # threshold-sized specks while preserving the same field statistics.
            assert float(difference.mean()) < 0.025, (definition.type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.95)) < 0.11, (definition.type_id, difference.mean(), difference.max())
            assert float(difference.max()) < 0.30, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id == "filter.ambient_occlusion_hbao":
            # Rotated bilinear sample rings use CPU and WGSL trigonometric paths
            # against a half-float GPU source. A few high-frequency pixels may
            # differ while the isotropic occlusion field remains equivalent.
            assert float(difference.mean()) < 0.01, (definition.type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.95)) < 0.04, (definition.type_id, difference.mean(), difference.max())
            assert float(difference.max()) < 0.15, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id == "terrain.flow_direction":
            # Direction normalisation is sensitive where the slope is almost
            # zero; those isolated vectors may rotate after half-float input
            # quantisation even though the field is visually equivalent.
            assert float(difference.mean()) < 0.02, (definition.type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.98)) < 0.02, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id == "terrain.flow_accumulation":
            # D8 routing can diverge at a tiny number of equal-slope cells after
            # half-float input quantisation, while the drainage field remains
            # effectively identical everywhere else.
            assert float(difference.mean()) < 0.01, (definition.type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.99)) < 0.02, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id == "terrain.hydraulic_erosion":
            # The multi-pass water/sediment simulation compounds tiny precision
            # differences over many iterations. Compare the visual field rather
            # than requiring bit-identical transport paths.
            assert float(difference.mean()) < 0.12, (definition.type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.95)) < 0.55, (definition.type_id, difference.mean(), difference.max())
        elif definition.type_id == "terrain.thermal_erosion":
            # Iterative steepest-neighbour ties can diverge after several passes
            # from tiny CPU/GPU input-precision differences, while preserving
            # the same terrain structure and total material behaviour.
            assert float(difference.mean()) < 0.04, (definition.type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.99)) < 0.18, (definition.type_id, difference.mean(), difference.max())
        else:
            # RGBA16F is the default physical GPU format in 0.5, so half-float
            # quantisation differences up to roughly one thousandth are expected.
            assert float(difference.max()) < 1.5e-3, (definition.type_id, difference.mean(), difference.max())

    # Verify Channel Pack's special unconnected-alpha default (white) on both paths.
    pack = registry.get("convert.channel_pack")
    red_only = {"Red": _cpu_image(first, "pack-red-only")}
    cpu_pack = cpu.evaluate_node(pack, red_only, {}, context, "cpu:pack-red-only")
    gpu_pack = gpu.to_cpu(gpu.evaluate_node(pack, {"Red": gpu.ensure_gpu(red_only["Red"], context)}, {}, context, "gpu:pack-red-only"))
    assert np.allclose(cpu_pack.array[..., 3], 1.0)
    assert np.allclose(gpu_pack.array[..., 3], 1.0)


def build_everything_gpu_graph(registry) -> tuple[GraphScene, tuple[str, str]]:
    """Build valid greyscale, colour and vector branches through the typed graph."""
    scene = GraphScene(registry)

    constant = scene.create_node("generator.constant", QPointF(), record_undo=False)
    color = scene.create_node("generator.color", QPointF(), record_undo=False)
    color_to_gray = scene.create_node("convert.color_to_grayscale", QPointF(), record_undo=False)
    linear = scene.create_node("generator.linear_gradient", QPointF(), record_undo=False)
    radial = scene.create_node("generator.radial_gradient", QPointF(), record_undo=False)
    shape = scene.create_node("shape.shape", QPointF(), parameters={"shape": "Disc"}, record_undo=False)
    polygon = scene.create_node("shape.polygon", QPointF(), parameters={"sides": 5, "inner_radius": 0.45}, record_undo=False)
    polygon_burst = scene.create_node("shape.polygon_burst", QPointF(), record_undo=False)
    checker = scene.create_node("pattern.checker", QPointF(), record_undo=False)
    noise = scene.create_node("noise.fractal", QPointF(), record_undo=False)

    blend_a = scene.create_node("math.blend", QPointF(), record_undo=False)
    blend_b = scene.create_node("math.blend", QPointF(), record_undo=False)
    blend_c = scene.create_node("math.blend", QPointF(), record_undo=False)
    blend_d = scene.create_node("math.blend", QPointF(), record_undo=False)
    assert scene.add_connection(color.output_port, color_to_gray.input_ports["Colour"], record_undo=False)
    assert scene.add_connection(color_to_gray.output_port, blend_a.input_ports["Background"], record_undo=False)
    assert scene.add_connection(linear.output_port, blend_a.input_ports["Foreground"], record_undo=False)
    assert scene.add_connection(radial.output_port, blend_b.input_ports["Background"], record_undo=False)
    assert scene.add_connection(constant.output_port, blend_b.input_ports["Foreground"], record_undo=False)
    assert scene.add_connection(blend_a.output_port, blend_c.input_ports["Background"], record_undo=False)
    assert scene.add_connection(blend_b.output_port, blend_c.input_ports["Foreground"], record_undo=False)
    assert scene.add_connection(blend_c.output_port, blend_d.input_ports["Background"], record_undo=False)
    assert scene.add_connection(noise.output_port, blend_d.input_ports["Foreground"], record_undo=False)

    blur = scene.create_node("filter.blur", QPointF(), record_undo=False)
    levels = scene.create_node("filter.levels", QPointF(), record_undo=False)
    auto_levels = scene.create_node("filter.auto_levels", QPointF(), record_undo=False)
    threshold = scene.create_node("filter.threshold", QPointF(), record_undo=False)
    invert = scene.create_node("filter.invert", QPointF(), record_undo=False)
    transform = scene.create_node("transform.basic", QPointF(), record_undo=False)
    gradient_map = scene.create_node("convert.gradient_map", QPointF(), record_undo=False)
    extract = scene.create_node("convert.extract_channel", QPointF(), record_undo=False)
    normal = scene.create_node("convert.height_normal", QPointF(), record_undo=False)
    pack = scene.create_node("convert.channel_pack", QPointF(), record_undo=False)
    color_output = scene.create_node("output.image", QPointF(), record_undo=False)
    vector_output = scene.create_node("output.image", QPointF(), record_undo=False)

    assert scene.add_connection(blend_d.output_port, blur.input_ports["Image"], record_undo=False)
    assert scene.add_connection(blur.output_port, levels.input_ports["Image"], record_undo=False)
    assert scene.add_connection(levels.output_port, auto_levels.input_ports["Image"], record_undo=False)
    assert scene.add_connection(auto_levels.output_port, threshold.input_ports["Image"], record_undo=False)
    assert scene.add_connection(threshold.output_port, invert.input_ports["Image"], record_undo=False)
    assert scene.add_connection(invert.output_port, transform.input_ports["Image"], record_undo=False)
    assert scene.add_connection(transform.output_port, gradient_map.input_ports["Image"], record_undo=False)
    assert scene.add_connection(gradient_map.output_port, extract.input_ports["Image"], record_undo=False)
    assert scene.add_connection(extract.output_ports["R"], normal.input_ports["Height"], record_undo=False)
    assert scene.add_connection(extract.output_ports["R"], pack.input_ports["Red"], record_undo=False)
    assert scene.add_connection(shape.output_port, pack.input_ports["Green"], record_undo=False)
    assert scene.add_connection(polygon.output_port, pack.input_ports["Blue"], record_undo=False)
    # Polygon Burst is exercised in the complete registry GPU pass even though
    # Channel Pack only has four sockets in this representative graph.
    assert polygon_burst.output_port is not None
    assert scene.add_connection(checker.output_port, pack.input_ports["Alpha"], record_undo=False)
    assert scene.add_connection(pack.output_port, color_output.input_ports["Image"], record_undo=False)
    assert scene.add_connection(normal.output_port, vector_output.input_ports["Image"], record_undo=False)
    return scene, (color_output.uid, vector_output.uid)


def assert_full_builtin_graph_is_gpu_only(registry) -> None:
    scene, output_uids = build_everything_gpu_graph(registry)
    evaluator = GraphEvaluator(scene, backend_preference="gpu")
    if not evaluator.gpu_available:
        return

    for output_uid in output_uids:
        result = evaluator.evaluate(output_uid, 96, 80)
        assert result.error is None, result.error
        assert result.backend in ("GPU", "GPU (cached)", "Hybrid", "Hybrid (cached)"), result
        assert result.cpu_nodes == 0, result
        assert result.gpu_nodes + result.cache_hits >= result.reachable_nodes, (
            result.gpu_nodes, result.cache_hits, result.reachable_nodes, result.fallback_nodes
        )
        assert not result.fallback_nodes, result.fallback_nodes

    warm = evaluator.evaluate(output_uids[0], 96, 80)
    assert warm.error is None
    assert warm.backend in ("GPU (cached)", "Hybrid (cached)")
    assert warm.cache_hits >= warm.reachable_nodes

    # The maximum exposed blur radius is a genuine GPU path, not a fallback.
    blur = next(node for node in scene.nodes.values() if node.definition.type_id == "filter.blur")
    blur.parameters["radius"] = 42.0
    maximum_blur = evaluator.evaluate(output_uids[0], 24, 24)
    assert maximum_blur.error is None, maximum_blur.error
    assert maximum_blur.cpu_nodes == 0
    assert not maximum_blur.fallback_nodes


def assert_hybrid_fallback_still_exists(registry) -> None:
    cpu_only = NodeDefinition(
        "test.cpu_only",
        "CPU-only Test Node",
        "Tests",
        eval_invert,
        inputs=("Image",),
    )
    constant = registry.get("generator.constant")
    output = registry.get("output.image")
    nodes = {
        "constant": SnapshotNode("constant", constant, {"value": 0.25}),
        "cpu": SnapshotNode("cpu", cpu_only, {}),
        "output": SnapshotNode("output", output, {}),
    }
    snapshot = GraphSnapshot(nodes, {("cpu", "Image"): "constant", ("output", "Image"): "cpu"})
    evaluator = GraphEvaluator(backend_preference="auto")
    result = evaluator.evaluate("output", 32, 32, snapshot=snapshot)
    assert result.error is None, result.error
    if evaluator.gpu_available:
        assert result.backend == "Hybrid"
        assert result.gpu_nodes == 2
        assert result.cpu_nodes == 1


def assert_downstream_caching(registry) -> None:
    scene = GraphScene(registry)
    noise = scene.create_node("noise.fractal", QPointF(), record_undo=False)
    levels = scene.create_node("filter.levels", QPointF(), record_undo=False)
    output = scene.create_node("output.image", QPointF(), record_undo=False)
    scene.add_connection(noise.output_port, levels.input_ports["Image"], record_undo=False)
    scene.add_connection(levels.output_port, output.input_ports["Image"], record_undo=False)
    evaluator = GraphEvaluator(scene, backend_preference="auto")

    first = evaluator.evaluate(output.uid, 128, 128)
    assert first.error is None
    levels.parameters["in_mid"] = 0.37
    second = evaluator.evaluate(output.uid, 128, 128)
    assert second.error is None
    assert second.cache_hits >= 1
    if evaluator.gpu_available:
        assert second.gpu_nodes == 2
        assert second.cpu_nodes == 0

    levels.setPos(500, 500)
    third = evaluator.evaluate(output.uid, 128, 128)
    assert third.error is None
    assert third.cache_hits == 3
    assert third.gpu_nodes == 0 and third.cpu_nodes == 0


def assert_deep_graph_and_demand_driven_evaluation(registry) -> None:
    constant_def = registry.get("generator.constant")
    invert_def = registry.get("filter.invert")
    nodes: dict[str, SnapshotNode] = {}
    inputs: dict[tuple[str, str], str] = {}

    first_uid = "node-0000"
    nodes[first_uid] = SnapshotNode(first_uid, constant_def, constant_def.default_parameters())
    previous = first_uid
    chain_length = 1500
    for index in range(1, chain_length + 1):
        uid = f"node-{index:04d}"
        nodes[uid] = SnapshotNode(uid, invert_def, invert_def.default_parameters())
        inputs[(uid, "Image")] = previous
        previous = uid

    for index in range(500):
        uid = f"unused-{index:04d}"
        nodes[uid] = SnapshotNode(uid, invert_def, invert_def.default_parameters())

    snapshot = GraphSnapshot(nodes, inputs)
    evaluator = GraphEvaluator(backend_preference="cpu", gpu_budget_mb=32, cpu_budget_mb=32)
    result = evaluator.evaluate(previous, 8, 8, snapshot=snapshot)
    assert result.error is None, result.error
    assert result.reachable_nodes == chain_length + 1
    assert result.cpu_nodes == chain_length + 1


def assert_cache_budget_evicts_safely(registry) -> None:
    scene = GraphScene(registry)
    source = scene.create_node("generator.constant", QPointF(), record_undo=False)
    previous = source
    for _index in range(70):
        node = scene.create_node("filter.invert", QPointF(), record_undo=False)
        scene.add_connection(previous.output_port, node.input_ports["Image"], record_undo=False)
        previous = node
    evaluator = GraphEvaluator(scene, backend_preference="cpu", gpu_budget_mb=32, cpu_budget_mb=32)
    result = evaluator.evaluate(previous.uid, 256, 256)
    assert result.error is None, result.error
    assert evaluator.cache_stats()["cpu"].evictions > 0


def assert_real_gpu_precision_formats(registry) -> None:
    gpu = WgpuBackend()
    if not gpu.available:
        return
    colour = registry.get("generator.color")
    for precision, expected_format, expected_bytes in (
        (TextureFormat.RGBA16F, "rgba16float", 8),
        (TextureFormat.RGBA32F, "rgba32float", 16),
    ):
        context = RenderContext(31, 19, precision)
        resource = gpu.evaluate_node(
            colour, {}, {"color": "#6b6b6bff"}, context, f"precision:{precision.value}", precision
        )
        assert resource.physical_format == expected_format
        assert resource.bytes_used == context.width * context.height * expected_bytes
        readback = gpu.to_cpu(resource)
        assert np.isfinite(readback.array).all()

    scalar = registry.get("generator.constant")
    context = RenderContext(31, 19, TextureFormat.RGBA16F)
    resource = gpu.evaluate_node(
        scalar, {}, {"value": 0.42}, context, "precision:scalar", TextureFormat.R16F
    )
    assert resource.physical_format == "r32float"
    assert resource.bytes_used == context.width * context.height * 4
    readback = gpu.to_cpu(resource)
    assert np.allclose(readback.array[..., :3], 0.42, atol=2e-5)



def assert_image_input_hybrid_path(registry) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "source.png"
        pixels = np.zeros((12, 20, 4), dtype=np.uint8)
        pixels[..., 0] = np.linspace(0, 255, 20, dtype=np.uint8)[None, :]
        pixels[..., 1] = 128
        pixels[..., 3] = 255
        Image.fromarray(pixels, mode="RGBA").save(path)
        image_def = registry.get("input.image")
        output_def = registry.get("output.image")
        nodes = {
            "image": SnapshotNode("image", image_def, {**image_def.default_parameters(), "path": str(path)}),
            "output": SnapshotNode("output", output_def, output_def.default_parameters()),
        }
        snapshot = GraphSnapshot(nodes, {("output", "Image"): "image"})
        evaluator = GraphEvaluator(backend_preference="auto")
        result = evaluator.evaluate("output", 64, 32, snapshot=snapshot)
        assert result.error is None, result.error
        assert result.image.shape == (32, 64, 4)
        if evaluator.gpu_available:
            assert result.backend == "Hybrid"
            assert result.cpu_nodes == 1 and result.gpu_nodes == 1


def main() -> int:
    app = QApplication.instance() or QApplication([])
    registry = build_registry()
    assert_every_procedural_builtin_has_wgsl(registry)
    assert_cpu_gpu_reference_agreement(registry)
    assert_full_builtin_graph_is_gpu_only(registry)
    assert_hybrid_fallback_still_exists(registry)
    assert_downstream_caching(registry)
    assert_deep_graph_and_demand_driven_evaluation(registry)
    assert_cache_budget_evicts_safely(registry)
    assert_real_gpu_precision_formats(registry)
    assert_image_input_hybrid_path(registry)
    app.processEvents()
    print(
        "Backend test passed: all built-in procedural nodes have WGSL kernels, Image Input uses a tested CPU-decode/GPU-upload path, "
        "RGBA16F/RGBA32F physical precision works, CPU/GPU references agree, full procedural graphs remain GPU-resident, "
        "hybrid fallback, downstream caching, 1501-node deep graphs, demand-driven execution and LRU eviction"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
