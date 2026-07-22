from __future__ import annotations

import math
import re
import struct
import threading
import time
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np

try:
    import wgpu
except ImportError as exc:  # pragma: no cover - exercised by CPU-only installs.
    raise RuntimeError("wgpu-py is not installed") from exc

from ...nodes.base import EvalContext, NodeDefinition
from ...nodes.image_ops import parse_hex_color, relative_pixels, resolution_scale, srgb_to_linear
from ...nodes.generators import geometric_raster_feather, tile_sampler_candidate_radius
from ...nodes.distance import _jump_steps
from ...nodes.photogrammetry import quad_homography
from ...nodes.processing import _safe_lattice, _safe_transform_offset
from ...nodes.resampling import affine_pixel_footprint
from ...flipbook import flipbook_frame_selection, flipbook_grid
from ..cache import MemoryLRU
from ..formats import RenderContext, TextureFormat
from ..resources import CpuImage, GpuImage, ImageResource
from .base import BackendCancelled, BackendInfo, RenderBackend


class WgpuBackend(RenderBackend):
    """WGSL/WebGPU compute backend for every built-in image node.

    Python remains responsible for graph orchestration, files and UI. Built-in
    pixel generation and texture processing stay GPU-resident between nodes;
    NumPy/Pillow implementations remain available through the CPU reference
    backend for fallback and comparison testing.
    """

    key = "gpu"
    name = "GPU (WebGPU/WGSL)"

    _SHADERS = {
        "generator.constant": "constant.wgsl",
        "generator.color": "color.wgsl",
        "generator.linear_gradient": "linear_gradient.wgsl",
        "generator.radial_gradient": "radial_gradient.wgsl",
        "shape.shape": "shape.wgsl",
        "shape.polygon": "polygon.wgsl",
        "shape.polygon_burst": "polygon_burst.wgsl",
        "pattern.checker": "checker.wgsl",
        "pattern.tile_sampler": "tile_sampler.wgsl",
        "pattern.splatter_circular": "splatter_circular.wgsl",
        "noise.value": "base_noise.wgsl",
        "noise.perlin": "base_noise.wgsl",
        "noise.fractal": "fractal_family.wgsl",
        "noise.simplex": "simplex_noise.wgsl",
        "noise.worley": "worley_noise.wgsl",
        "noise.white": "random_noise.wgsl",
        "noise.gaussian": "gaussian_noise.wgsl",
        "noise.ridged": "ridged_noise.wgsl",
        "noise.billow": "billow_noise.wgsl",
        "noise.turbulence": "turbulence_noise.wgsl",
        "noise.voronoi_fractal": "voronoi_fractal.wgsl",
        "noise.clouds_1": "foundational_noise.wgsl",
        "noise.clouds_2": "foundational_noise.wgsl",
        "noise.clouds_3": "foundational_noise.wgsl",
        "noise.bnw_spots_1": "foundational_noise.wgsl",
        "noise.bnw_spots_2": "foundational_noise.wgsl",
        "noise.bnw_spots_3": "foundational_noise.wgsl",
        "noise.crystal_1": "foundational_noise.wgsl",
        "noise.crystal_2": "foundational_noise.wgsl",
        "noise.fractal_sum": "foundational_noise.wgsl",
        "noise.anisotropic": "foundational_noise.wgsl",
        "noise.fibres": "foundational_noise.wgsl",
        "noise.messy_fibres": "foundational_noise.wgsl",
        "noise.moisture": "foundational_noise.wgsl",
        "noise.fur": "foundational_noise.wgsl",
        "filter.flood_fill": "flood_fill.wgsl",
        "filter.flood_fill_random_grayscale": "flood_fill_random_grayscale.wgsl",
        "filter.flood_fill_random_colour": "flood_fill_random_colour.wgsl",
        "filter.flood_fill_to_grayscale": "flood_fill_to_grayscale.wgsl",
        "filter.flood_fill_to_colour": "flood_fill_to_colour.wgsl",
        "filter.flood_fill_to_gradient": "flood_fill_to_gradient.wgsl",
        "filter.flood_fill_to_position": "flood_fill_to_position.wgsl",
        "filter.flood_fill_to_bbox_size": "flood_fill_to_bbox_size.wgsl",
        "filter.flood_fill_to_index": "flood_fill_to_index.wgsl",
        "filter.flood_fill_mapper": "flood_fill_mapper.wgsl",
        "filter.invert": "invert.wgsl",
        "filter.levels": "levels.wgsl",
        "filter.histogram_range": "histogram_range.wgsl",
        "filter.histogram_shift": "histogram_shift.wgsl",
        "filter.histogram_scan": "histogram_scan.wgsl",
        "filter.histogram_select": "histogram_select.wgsl",
        "filter.brightness": "adjust_scalar.wgsl",
        "filter.contrast": "adjust_scalar.wgsl",
        "filter.exposure": "adjust_scalar.wgsl",
        "filter.gamma": "adjust_scalar.wgsl",
        "filter.posterize": "adjust_scalar.wgsl",
        "filter.clamp": "adjust_scalar.wgsl",
        "filter.hue_shift": "hsl_adjust.wgsl",
        "filter.saturation": "hsl_adjust.wgsl",
        "filter.lightness": "hsl_adjust.wgsl",
        "filter.curve": "image_curve.wgsl",
        "filter.auto_levels": "auto_levels.wgsl",
        "filter.highpass": "highpass_combine.wgsl",
        "internal.highpass_prepare": "highpass_prepare.wgsl",
        "internal.highpass_combine": "highpass_combine.wgsl",
        "filter.edge_detect": "edge_detect.wgsl",
        "filter.fxaa": "fxaa.wgsl",
        "filter.make_it_tile_photo": "make_it_tile_photo.wgsl",
        "filter.lighting_equalisation": "lighting_equalisation.wgsl",
        "filter.threshold": "threshold.wgsl",
        "filter.curvature": "curvature_normal.wgsl",
        "filter.curvature_sobel": "curvature_sobel.wgsl",
        "filter.curvature_smooth": "curvature_smooth.wgsl",
        "filter.ambient_occlusion_hbao": "ambient_occlusion_hbao.wgsl",
        "filter.ambient_occlusion_rtao": "ambient_occlusion_rtao.wgsl",
        "normal.blend": "normal_blend.wgsl",
        "normal.combine": "normal_combine.wgsl",
        "normal.normalize": "normal_normalize.wgsl",
        "normal.invert": "normal_invert.wgsl",
        "normal.vector_rotation": "normal_vector_rotation.wgsl",
        "filter.directional_lighting": "directional_lighting.wgsl",
        "normal.transform": "normal_transform.wgsl",
        "normal.to_height": "normal_to_height_prepare.wgsl",
        "normal.bent": "bent_normal.wgsl",
        "filter.rt_shadows": "rt_shadows.wgsl",
        "internal.hbao_bilateral_blur": "hbao_bilateral_blur.wgsl",
        "internal.bent_normal_denoise": "bent_normal_denoise.wgsl",
        "filter.blur": "gaussian_blur.wgsl",
        "internal.fused_adjustments": "fused_adjustments.wgsl",
        "filter.directional_blur": "directional_blur.wgsl",
        "filter.radial_blur": "radial_blur.wgsl",
        "filter.zoom_blur": "zoom_blur.wgsl",
        "filter.anisotropic_blur": "anisotropic_blur.wgsl",
        "filter.non_uniform_blur_grayscale": "non_uniform_blur_grayscale.wgsl",
        "filter.slope_blur_grayscale": "slope_blur_grayscale.wgsl",
        "filter.distance": "distance.wgsl",
        "filter.bevel": "bevel.wgsl",
        "filter.expand_shrink": "expand_shrink.wgsl",
        "filter.outline": "outline.wgsl",
        "filter.aperture": "aperture_step.wgsl",
        "transform.crop": "crop.wgsl",
        "transform.auto_crop": "auto_crop.wgsl",
        "transform.clone_patch": "clone_patch.wgsl",
        "transform.perspective": "perspective_transform.wgsl",
        "transform.atlas_splitter": "image_output.wgsl",
        "transform.basic": "transform_2d.wgsl",
        "transform.safe": "safe_transform.wgsl",
        "transform.tile": "transform_simple.wgsl",
        "transform.offset": "transform_simple.wgsl",
        "transform.rotate": "transform_simple.wgsl",
        "transform.scale": "transform_simple.wgsl",
        "transform.mirror": "transform_simple.wgsl",
        "coordinates.uv_gradient": "uv_gradient.wgsl",
        "coordinates.cartesian_to_polar": "coordinate_polar.wgsl",
        "coordinates.polar_to_cartesian": "coordinate_polar.wgsl",
        "distortion.swirl": "distortion_radial.wgsl",
        "distortion.spherize": "distortion_radial.wgsl",
        "distortion.vector_warp": "vector_warp.wgsl",
        "distortion.flow_map": "vector_warp.wgsl",
        "org.vfxtexturelab.directional_warp": "directional_warp.wgsl",
        "org.vfxtexturelab.polar_coordinates": "coordinate_polar.wgsl",
        "math.blend": "blend.wgsl",
        "convert.color_to_grayscale": "color_to_grayscale.wgsl",
        "convert.color_to_vector": "image_output.wgsl",
        "convert.vector_to_color": "image_output.wgsl",
        "convert.gradient_map": "gradient_map.wgsl",
        "convert.height_normal": "height_to_normal.wgsl",
        "convert.extract_channel": "extract_channel.wgsl",
        "convert.channel_pack": "channel_pack.wgsl",
        "output.image": "image_output.wgsl",
        "output.flipbook": "image_output.wgsl",
        "animation.flipbook_decode": "flipbook_decode.wgsl",
        "terrain.slope": "terrain_slope.wgsl",
        "terrain.curvature": "terrain_curvature.wgsl",
        "terrain.terrace": "terrain_terrace.wgsl",
        "terrain.height_combine": "terrain_height_combine.wgsl",
        "terrain.height_blend": "terrain_height_blend.wgsl",
        "terrain.flow_direction": "terrain_flow_direction.wgsl",
        "terrain.flow_accumulation": "terrain_flow_accum_step.wgsl",
        "terrain.hydraulic_erosion": "terrain_fluvial_erode.wgsl",
        "terrain.thermal_erosion": "terrain_thermal_step.wgsl",
        "internal.flow_accum_init": "terrain_flow_accum_init.wgsl",
        "internal.flow_accum_step": "terrain_flow_accum_step.wgsl",
        "internal.flow_accum_select": "terrain_flow_accum_select.wgsl",
        "internal.fluvial_init": "terrain_fluvial_init.wgsl",
        "internal.fluvial_flow_init": "terrain_fluvial_flow_init.wgsl",
        "internal.fluvial_flow_step": "terrain_fluvial_flow_step.wgsl",
        "internal.fluvial_erode": "terrain_fluvial_erode.wgsl",
        "internal.fluvial_select": "terrain_fluvial_select.wgsl",
        "internal.thermal_init": "terrain_thermal_init.wgsl",
        "internal.thermal_step": "terrain_thermal_step.wgsl",
        "internal.thermal_select": "terrain_thermal_select.wgsl",
        "internal.distance_seed_init": "distance_seed_init.wgsl",
        "internal.distance_seed_jump": "distance_seed_jump.wgsl",
        "internal.aperture_mix": "aperture_mix.wgsl",
        "internal.preview_prepare": "preview_prepare.wgsl",
        "internal.quantize8": "quantize8.wgsl",
        "internal.simulation_copy": "simulation_copy.wgsl",
        "internal.simulation_temporal_blend": "simulation_temporal_blend.wgsl",
        "internal.simulation_reaction_init": "simulation_reaction_init.wgsl",
        "internal.simulation_reaction_step": "simulation_reaction_step.wgsl",
        "internal.simulation_reaction_output": "simulation_reaction_output.wgsl",
    }

    _INPUT_ORDER = {
        "generator.constant": (),
        "generator.color": (),
        "generator.linear_gradient": (),
        "generator.radial_gradient": (),
        "shape.shape": (),
        "shape.polygon": (),
        "shape.polygon_burst": (),
        "pattern.checker": (),
        "pattern.tile_sampler": (
            "Pattern Input",
            "Pattern Input 2",
            "Pattern Input 3",
            "Pattern Input 4",
            "Scale Map",
            "Rotation Map",
            "Displacement Map",
            "Vector Map",
            "Mask Map",
            "Pattern Distribution Map",
            "Background Input",
        ),
        "pattern.splatter_circular": (
            "Pattern Input",
            "Pattern Input 2",
            "Pattern Input 3",
            "Pattern Input 4",
            "Background Input",
        ),
        "noise.value": (),
        "noise.perlin": (),
        "noise.fractal": (),
        "noise.simplex": (),
        "noise.worley": (),
        "noise.white": (),
        "noise.gaussian": (),
        "noise.ridged": (),
        "noise.billow": (),
        "noise.turbulence": (),
        "noise.voronoi_fractal": (),
        "noise.clouds_1": (),
        "noise.clouds_2": (),
        "noise.clouds_3": (),
        "noise.bnw_spots_1": (),
        "noise.bnw_spots_2": (),
        "noise.bnw_spots_3": (),
        "noise.crystal_1": (),
        "noise.crystal_2": (),
        "noise.fractal_sum": (),
        "noise.anisotropic": (),
        "noise.fibres": (),
        "noise.messy_fibres": (),
        "noise.moisture": (),
        "noise.fur": (),
        "filter.flood_fill": ("Binary Mask",),
        "filter.flood_fill_random_grayscale": ("Flood Fill",),
        "filter.flood_fill_random_colour": ("Flood Fill",),
        "filter.flood_fill_to_grayscale": ("Flood Fill", "Value Input"),
        "filter.flood_fill_to_colour": ("Flood Fill", "Colour Input"),
        "filter.flood_fill_to_gradient": ("Flood Fill", "Angle Input", "Slope Input"),
        "filter.flood_fill_to_position": ("Flood Fill",),
        "filter.flood_fill_to_bbox_size": ("Flood Fill",),
        "filter.flood_fill_to_index": ("Flood Fill",),
        "filter.flood_fill_mapper": ("Flood Fill", "Pattern Input", "Scale Map", "Rotation Map"),
        "filter.invert": ("Image",),
        "filter.levels": ("Image",),
        "filter.histogram_range": ("Image",),
        "filter.histogram_shift": ("Image",),
        "filter.histogram_scan": ("Image",),
        "filter.histogram_select": ("Image",),
        "filter.brightness": ("Image",),
        "filter.contrast": ("Image",),
        "filter.exposure": ("Image",),
        "filter.gamma": ("Image",),
        "filter.posterize": ("Image",),
        "filter.clamp": ("Image",),
        "filter.hue_shift": ("Colour",),
        "filter.saturation": ("Colour",),
        "filter.lightness": ("Colour",),
        "filter.curve": ("Image",),
        "filter.auto_levels": ("Image",),
        "filter.highpass": ("Image",),
        "internal.highpass_prepare": ("Image",),
        "internal.highpass_combine": ("Image", "Blurred"),
        "filter.edge_detect": ("Image",),
        "filter.fxaa": ("Image",),
        "filter.make_it_tile_photo": ("Image",),
        "filter.lighting_equalisation": ("Image",),
        "filter.threshold": ("Image",),
        "filter.curvature": ("Normal",),
        "filter.curvature_sobel": ("Normal",),
        "filter.curvature_smooth": ("Normal",),
        "filter.ambient_occlusion_hbao": ("Height",),
        "filter.ambient_occlusion_rtao": ("Height",),
        "normal.blend": ("Background", "Foreground", "Mask"),
        "normal.combine": ("Base", "Detail", "Mask"),
        "normal.normalize": ("Normal",),
        "normal.invert": ("Normal",),
        "normal.vector_rotation": ("Normal",),
        "filter.directional_lighting": ("Normal",),
        "normal.transform": ("Normal",),
        "normal.to_height": ("Normal",),
        "normal.bent": ("Height",),
        "filter.rt_shadows": ("Height",),
        "filter.blur": ("Image",),
        "internal.fused_adjustments": ("Image",),
        "filter.directional_blur": ("Image",),
        "filter.radial_blur": ("Image",),
        "filter.zoom_blur": ("Image",),
        "filter.anisotropic_blur": ("Image",),
        "filter.non_uniform_blur_grayscale": ("Image", "Blur Map"),
        "filter.slope_blur_grayscale": ("Image", "Slope"),
        "filter.distance": ("Image",),
        "filter.bevel": ("Image",),
        "filter.expand_shrink": ("Image",),
        "filter.outline": ("Image",),
        "filter.aperture": ("Image",),
        "transform.crop": ("Image",),
        "transform.auto_crop": ("Image",),
        "transform.clone_patch": ("Image", "Mask"),
        "transform.perspective": ("Image",),
        "transform.atlas_splitter": ("Image", "Mask"),
        "transform.basic": ("Image",),
        "transform.safe": ("Image",),
        "transform.tile": ("Image",),
        "transform.offset": ("Image",),
        "transform.rotate": ("Image",),
        "transform.scale": ("Image",),
        "transform.mirror": ("Image",),
        "coordinates.uv_gradient": (),
        "coordinates.cartesian_to_polar": ("Image",),
        "coordinates.polar_to_cartesian": ("Image",),
        "distortion.swirl": ("Image",),
        "distortion.spherize": ("Image",),
        "distortion.vector_warp": ("Image", "Vector"),
        "distortion.flow_map": ("Image", "Flow"),
        "org.vfxtexturelab.directional_warp": ("Image", "Intensity"),
        "org.vfxtexturelab.polar_coordinates": ("Image",),
        "math.blend": ("Foreground", "Background", "Opacity"),
        "convert.color_to_grayscale": ("Colour",),
        "convert.color_to_vector": ("Image",),
        "convert.vector_to_color": ("Image",),
        "convert.gradient_map": ("Image",),
        "convert.height_normal": ("Height",),
        "convert.extract_channel": ("Image",),
        "convert.channel_pack": ("Red", "Green", "Blue", "Alpha"),
        "output.image": ("Image",),
        "output.flipbook": ("Image",),
        "animation.flipbook_decode": ("Sheet",),
        "terrain.slope": ("Height",),
        "terrain.curvature": ("Height",),
        "terrain.terrace": ("Height", "Mask", "Variation"),
        "terrain.height_combine": ("A", "B", "Mask"),
        "terrain.height_blend": ("Base", "Layer", "Mask"),
        "terrain.flow_direction": ("Height",),
        "terrain.flow_accumulation": ("Height", "Rainfall Mask"),
        "terrain.hydraulic_erosion": ("Height", "Rainfall Mask", "Hardness"),
        "terrain.thermal_erosion": ("Height", "Hardness"),
        "internal.distance_seed_init": ("Image",),
        "internal.distance_seed_jump": ("Seeds",),
        "internal.quantize8": ("Image",),
    }

    def __init__(self, readback_budget_mb: int = 128) -> None:
        self._lock = threading.RLock()
        self._pipelines: dict[tuple[str, str, str], Any] = {}
        self._solid_textures: dict[tuple[int, int, float, str], GpuImage] = {}
        self._colour_textures: dict[tuple[int, int, tuple[float, float, float, float], str, str], GpuImage] = {}
        self._readbacks: MemoryLRU[CpuImage] = MemoryLRU(readback_budget_mb * 1024 * 1024)
        self._batch_encoder = None
        self._batch_keepalive: list[Any] = []
        self._batch_depth = 0
        self._batch_has_commands = False
        self._batch_failed = False
        self._preview_targets: dict[tuple[int, int], tuple[Any, Any, Any, Any, int]] = {}
        self._initialization_error = ""
        self.adapter = None
        self.device = None
        self.queue = None
        self.adapter_detail = ""
        self._initialize()

    def _initialize(self) -> None:
        try:
            adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
            if adapter is None:
                adapter = wgpu.gpu.request_adapter_sync(force_fallback_adapter=True)
            if adapter is None:
                raise RuntimeError("No WebGPU adapter was found")
            device = adapter.request_device_sync(required_features=[], required_limits={})
            self.adapter = adapter
            self.device = device
            self.queue = device.queue
            info = dict(adapter.info)
            device_name = info.get("device") or info.get("description") or "Unknown adapter"
            backend = info.get("backend_type") or "WebGPU"
            adapter_type = info.get("adapter_type") or "unknown"
            self.adapter_detail = f"{device_name} · {backend} · {adapter_type}"
        except Exception as exc:
            self._initialization_error = f"{type(exc).__name__}: {exc}"
            self.adapter = None
            self.device = None
            self.queue = None

    @property
    def available(self) -> bool:
        return self.device is not None and self.queue is not None

    def info(self) -> BackendInfo:
        detail = self.adapter_detail if self.available else self._initialization_error
        return BackendInfo(self.key, self.name, self.available, detail)

    def supports(self, definition: NodeDefinition) -> bool:
        if not self.available:
            return False
        if definition.stateful is not None:
            return bool(definition.stateful.gpu_supported)
        return definition.type_id in self._SHADERS or definition.gpu_spec is not None

    def supported_type_ids(self) -> tuple[str, ...]:
        public = {type_id for type_id in self._SHADERS if not type_id.startswith("internal.")}
        public.update({
            "simulation.frame_delay",
            "simulation.temporal_blend",
            "simulation.reaction_diffusion",
        })
        return tuple(sorted(public))

    @contextmanager
    def command_batch(self):
        """Batch ordinary graph dispatches into as few queue submissions as possible.

        Texture dependencies remain ordered inside one command encoder. Iterative
        nodes and CPU readbacks flush the current batch only when they genuinely
        need a synchronisation point.
        """
        if not self.available:
            yield
            return
        with self._lock:
            assert self.device is not None
            self._batch_depth += 1
            if self._batch_depth == 1:
                self._batch_encoder = self.device.create_command_encoder(label="VFXTL graph command batch")
                self._batch_keepalive = []
                self._batch_has_commands = False
                self._batch_failed = False
        try:
            yield
        except BaseException:
            with self._lock:
                self._batch_failed = True
            raise
        finally:
            with self._lock:
                self._batch_depth = max(self._batch_depth - 1, 0)
                if self._batch_depth == 0:
                    if self._batch_failed:
                        self._discard_batch_locked()
                    else:
                        self._flush_batch_locked(restart=False)

    def _discard_batch_locked(self) -> None:
        """Drop unsubmitted commands after cancellation or evaluation failure."""
        for resource in self._batch_keepalive:
            if isinstance(resource, GpuImage):
                resource.unpin()
        self._batch_encoder = None
        self._batch_keepalive = []
        self._batch_has_commands = False
        self._batch_failed = False

    def _flush_batch_locked(self, *, restart: bool) -> None:
        encoder = self._batch_encoder
        keepalive = self._batch_keepalive
        if encoder is not None and self._batch_has_commands:
            assert self.queue is not None
            self.queue.submit([encoder.finish()])
        for resource in keepalive:
            if isinstance(resource, GpuImage):
                resource.unpin()
        self._batch_keepalive = []
        if restart and self._batch_depth > 0:
            assert self.device is not None
            self._batch_encoder = self.device.create_command_encoder(label="VFXTL continued graph command batch")
            self._batch_has_commands = False
        else:
            self._batch_encoder = None
            self._batch_has_commands = False
            self._batch_failed = False

    def _wait_for_submitted_work(
        self,
        cancel_check: Callable[[], bool] | None = None,
        *,
        cooperative: bool = False,
    ) -> None:
        """Wait until previously submitted GPU work is genuinely complete.

        Iterative preview nodes use this between small batches. Besides making
        progress truthful, it prevents thousands of passes being queued ahead
        of the UI and gives cancellation and the desktop compositor regular
        opportunities to run.
        """
        lock = getattr(self, "_lock", None)
        if lock is not None:
            with lock:
                if getattr(self, "_batch_encoder", None) is not None:
                    self._flush_batch_locked(restart=getattr(self, "_batch_depth", 0) > 0)
        if self.queue is None:
            return
        waiter = getattr(self.queue, "on_submitted_work_done_sync", None)
        if callable(waiter):
            waiter()
        if cancel_check is not None and cancel_check():
            raise BackendCancelled("GPU evaluation was cancelled")
        if cooperative:
            # A tiny yield is enough to avoid monopolising a shared desktop GPU
            # during long live previews. Final exports remain maximum-throughput.
            time.sleep(0.001)

    def validate_definition(self, definition: NodeDefinition) -> None:
        """Preflight and cache every physical-format pipeline for a package.

        Pipelines are committed atomically only after all variants compile. This
        guarantees hot-reload failures retain a complete last-known-good shader,
        even if the node had not yet been used in the current graph.
        """
        if not self.available:
            raise RuntimeError(self._initialization_error or "WebGPU backend is unavailable")
        if definition.gpu_spec is None and definition.type_id not in self._SHADERS:
            raise NotImplementedError(f"{definition.name} has no WGSL kernel")
        revision = self._definition_revision(definition)
        physical_formats = ("r32float", "rg32float", "rgba16float", "rgba32float")
        built: dict[tuple[str, str, str], Any] = {}
        for physical in physical_formats:
            built[(definition.type_id, physical, revision)] = self._build_pipeline(definition, physical)
        with self._lock:
            for key in [key for key in self._pipelines if key[0] == definition.type_id]:
                self._pipelines.pop(key, None)
            self._pipelines.update(built)

    def invalidate_definition(self, type_id: str) -> None:
        with self._lock:
            for key in [key for key in self._pipelines if key[0] == type_id]:
                self._pipelines.pop(key, None)

    def evaluate_node(
        self,
        definition: NodeDefinition,
        inputs: Mapping[str, ImageResource],
        parameters: Mapping[str, Any],
        context: RenderContext,
        cache_key: str,
        logical_format: TextureFormat | None = None,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> GpuImage:
        if not self.available:
            raise RuntimeError(self._initialization_error or "WebGPU backend is unavailable")
        type_id = definition.type_id
        if type_id not in self._SHADERS and definition.gpu_spec is None:
            raise NotImplementedError(f"{definition.name} has no WGSL kernel")

        with self._lock:
            if type_id == "terrain.hydraulic_erosion" and definition.gpu_spec is None:
                result = self._evaluate_hydraulic_erosion(
                    definition, inputs, parameters, context, cache_key,
                    logical_format or TextureFormat.R16F,
                    cancel_check=cancel_check,
                    progress_callback=progress_callback,
                )
                result.provenance = self._node_provenance(inputs)
                return result

            if type_id == "terrain.flow_accumulation" and definition.gpu_spec is None:
                result = self._evaluate_flow_accumulation(
                    definition, inputs, parameters, context, cache_key,
                    logical_format or TextureFormat.R16F,
                    cancel_check=cancel_check,
                    progress_callback=progress_callback,
                )
                result.provenance = self._node_provenance(inputs)
                return result

            if type_id == "terrain.thermal_erosion" and definition.gpu_spec is None:
                result = self._evaluate_thermal_erosion(
                    definition, inputs, parameters, context, cache_key,
                    logical_format or TextureFormat.R16F,
                    cancel_check=cancel_check,
                    progress_callback=progress_callback,
                )
                result.provenance = self._node_provenance(inputs)
                return result

            if type_id == "filter.highpass" and definition.gpu_spec is None:
                result = self._evaluate_highpass(
                    definition, inputs, parameters, context, cache_key,
                    logical_format or TextureFormat(getattr(definition, "output_format", TextureFormat.RGBA16F.value)),
                )
                result.provenance = self._node_provenance(inputs)
                return result

            if type_id == "filter.make_it_tile_photo" and definition.gpu_spec is None:
                result = self._evaluate_make_it_tile_photo(
                    definition, inputs, parameters, context, cache_key,
                    logical_format or TextureFormat(getattr(definition, "output_format", TextureFormat.RGBA16F.value)),
                )
                result.provenance = self._node_provenance(inputs)
                return result

            if type_id == "filter.lighting_equalisation" and definition.gpu_spec is None:
                result = self._evaluate_lighting_equalisation(
                    definition, inputs, parameters, context, cache_key,
                    logical_format or TextureFormat(getattr(definition, "output_format", TextureFormat.RGBA16F.value)),
                )
                result.provenance = self._node_provenance(inputs)
                return result

            if type_id == "transform.auto_crop" and definition.gpu_spec is None:
                result = self._evaluate_auto_crop(
                    definition, inputs, parameters, context, cache_key,
                    logical_format or TextureFormat(getattr(definition, "output_format", TextureFormat.RGBA16F.value)),
                )
                result.provenance = self._node_provenance(inputs) | frozenset({"cpu"})
                return result

            if type_id == "transform.atlas_splitter" and definition.gpu_spec is None:
                result = self._evaluate_atlas_splitter(
                    definition, inputs, parameters, context, cache_key,
                    logical_format or TextureFormat(getattr(definition, "output_format", TextureFormat.RGBA16F.value)),
                )
                result.provenance = self._node_provenance(inputs) | frozenset({"cpu"})
                return result

            if type_id == "normal.to_height" and definition.gpu_spec is None:
                result = self._evaluate_normal_to_height(
                    definition, inputs, parameters, context, cache_key,
                    logical_format or TextureFormat.R16F,
                )
                result.provenance = self._node_provenance(inputs) | frozenset({"cpu"})
                return result

            if type_id == "filter.auto_levels" and definition.gpu_spec is None:
                source_resource = inputs.get("Image")
                source = self.ensure_gpu(source_resource, context) if source_resource is not None else self._blank(context)
                cpu = self.to_cpu(source).array
                values = cpu[..., :3] @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
                low = float(np.min(values)); high = float(np.max(values))
                scalar_source = 1.0 if source.logical_format.channels == 1 else 0.0
                result = self._dispatch(
                    definition, [source], self._pack_params(context, (low, high, scalar_source, 0.0)),
                    context, cache_key, logical_format or source.logical_format,
                )
                result.provenance = self._node_provenance(inputs) | frozenset({"cpu"})
                return result

            if type_id == "filter.blur" and definition.gpu_spec is None:
                result = self._evaluate_blur(
                    definition, inputs, parameters, context, cache_key,
                    logical_format or TextureFormat(getattr(definition, "output_format", TextureFormat.RGBA16F.value)),
                )
                result.provenance = self._node_provenance(inputs)
                return result

            if type_id == "filter.ambient_occlusion_hbao" and definition.gpu_spec is None:
                result = self._evaluate_hbao(
                    definition, inputs, parameters, context, cache_key,
                    logical_format or TextureFormat.R16F,
                )
                result.provenance = self._node_provenance(inputs)
                return result

            if type_id == "filter.ambient_occlusion_rtao" and definition.gpu_spec is None:
                result = self._evaluate_rtao(
                    definition, inputs, parameters, context, cache_key,
                    logical_format or TextureFormat.R16F,
                )
                result.provenance = self._node_provenance(inputs)
                return result

            if type_id == "normal.bent" and definition.gpu_spec is None:
                result = self._evaluate_bent_normal(
                    definition, inputs, parameters, context, cache_key,
                    logical_format or TextureFormat.RGBA16F,
                )
                result.provenance = self._node_provenance(inputs)
                return result

            if type_id in {"filter.distance", "filter.bevel", "filter.expand_shrink", "filter.outline"} and definition.gpu_spec is None:
                result = self._evaluate_distance_profile(
                    definition, inputs, parameters, context, cache_key,
                    logical_format or TextureFormat.R16F,
                    cancel_check=cancel_check,
                    progress_callback=progress_callback,
                )
                result.provenance = result.provenance | self._node_provenance(inputs)
                return result

            if type_id == "filter.aperture" and definition.gpu_spec is None:
                result = self._evaluate_aperture(
                    definition, inputs, parameters, context, cache_key,
                    logical_format or TextureFormat.R16F,
                    cancel_check=cancel_check,
                    progress_callback=progress_callback,
                )
                result.provenance = result.provenance | self._node_provenance(inputs)
                return result

            if type_id == "filter.flood_fill" and definition.gpu_spec is None:
                source_resource = inputs.get("Binary Mask")
                if source_resource is None:
                    source_array = np.zeros((context.height, context.width, 4), dtype=np.float32)
                    provenance = frozenset({"cpu"})
                else:
                    source_cpu = self.to_cpu(source_resource)
                    source_array = source_cpu.array
                    provenance = source_cpu.provenance | frozenset({"cpu"})
                eval_context = EvalContext(
                    width=context.width,
                    height=context.height,
                    time_seconds=context.time_seconds,
                    frame_number=context.frame_number,
                    frame_position=context.frame_position,
                    delta_time=context.delta_time,
                    duration_seconds=context.duration_seconds,
                    normalised_time=context.normalised_time,
                    loop_phase=context.loop_phase,
                    frames_per_second=context.frames_per_second,
                    document_frame_count=context.document_frame_count,
                    loop_start_frame=context.loop_start_frame,
                    loop_end_frame=context.loop_end_frame,
                    render_mode=context.render_mode,
                )
                assert definition.evaluator is not None
                array = np.ascontiguousarray(
                    definition.evaluator({"Binary Mask": source_array}, parameters, eval_context),
                    dtype=np.float32,
                )
                cpu_result = CpuImage(
                    array,
                    logical_format or TextureFormat.RGBA32F,
                    cache_key,
                    provenance,
                    data_kind="vector",
                    precision="32-bit",
                )
                result = self.ensure_gpu(cpu_result, context)
                result.cache_key = cache_key
                result.provenance = provenance | frozenset({"gpu"})
                result.data_kind = "vector"
                result.precision = "32-bit"
                return result

            input_order = definition.inputs if definition.gpu_spec is not None else self._INPUT_ORDER[type_id]
            gpu_inputs: list[GpuImage] = []
            for name in input_order:
                resource = inputs.get(name)
                if resource is None:
                    if definition.gpu_spec is not None:
                        default_value = definition.gpu_spec.input_default(name)
                    else:
                        default_value = 1.0 if (
                        (type_id == "convert.channel_pack" and name == "Alpha")
                        or (type_id == "math.blend" and name == "Opacity")
                        or (type_id in {"terrain.height_combine", "terrain.height_blend", "terrain.terrace"} and name == "Mask")
                        or (type_id in {"normal.blend", "normal.combine"} and name == "Mask")
                    ) else 0.0
                    if (
                        (type_id == "distortion.vector_warp" and name == "Vector")
                        or (type_id == "distortion.flow_map" and name == "Flow")
                        or (type_id == "pattern.tile_sampler" and name == "Vector Map")
                    ):
                        default = self._solid(context, 0.5, TextureFormat.RGBA16F)
                        default.data_kind = "vector"
                    elif (
                        (type_id in {"filter.curvature", "filter.curvature_sobel", "filter.curvature_smooth"} and name == "Normal")
                        or (type_id == "normal.blend" and name in {"Background", "Foreground"})
                        or (type_id == "normal.combine" and name in {"Base", "Detail"})
                        or (type_id in {"normal.normalize", "normal.invert", "normal.vector_rotation", "normal.transform", "filter.directional_lighting"} and name == "Normal")
                    ):
                        default = self._solid_colour(
                            context, (0.5, 0.5, 1.0, 1.0), TextureFormat.RGBA16F, data_kind="vector"
                        )
                    elif type_id == "terrain.terrace" and name == "Variation":
                        default = self._solid(context, 0.5, TextureFormat.R16F)
                    elif type_id == "pattern.tile_sampler" and name in {"Scale Map", "Mask Map"}:
                        default = self._white(context, TextureFormat.R16F)
                    elif type_id == "filter.non_uniform_blur_grayscale" and name == "Blur Map":
                        default = self._white(context, TextureFormat.R16F)
                    elif type_id == "filter.slope_blur_grayscale" and name == "Slope" and gpu_inputs:
                        default = gpu_inputs[0]
                    else:
                        default = (
                            self._white(context, TextureFormat.R16F)
                            if default_value >= 0.5
                            else self._blank(context, TextureFormat.R16F)
                        )
                    gpu_inputs.append(default)
                else:
                    gpu_inputs.append(self.ensure_gpu(resource, context))

            actual_logical = logical_format or TextureFormat(
                getattr(definition, "output_format", TextureFormat.RGBA16F.value)
            )
            effective_parameters: Mapping[str, Any] = parameters
            if type_id in {"pattern.tile_sampler", "pattern.splatter_circular"} and definition.gpu_spec is None:
                effective_parameters = dict(parameters)
                pattern_names = ("Pattern Input", "Pattern Input 2", "Pattern Input 3", "Pattern Input 4")
                connected_mask = sum((1 << index) for index, name in enumerate(pattern_names) if name in inputs)
                effective_parameters["_pattern_connected_mask"] = connected_mask
                effective_parameters["_background_connected"] = "Background Input" in inputs
                if type_id == "pattern.tile_sampler":
                    effective_parameters["_mask_connected"] = "Mask Map" in inputs
            elif type_id == "transform.clone_patch" and definition.gpu_spec is None:
                effective_parameters = dict(parameters)
                effective_parameters["_has_mask"] = "Mask" in inputs
            elif type_id.startswith("filter.flood_fill_") and definition.gpu_spec is None:
                effective_parameters = dict(parameters)
                for input_name in definition.inputs:
                    effective_parameters[f"_connected_{input_name}"] = input_name in inputs
            parameter_block = (
                self._package_parameter_block(definition, effective_parameters, context)
                if definition.gpu_spec is not None
                else self._parameter_block(type_id, effective_parameters, context, gpu_inputs)
            )
            result = self._dispatch(
                definition,
                gpu_inputs,
                parameter_block,
                context,
                cache_key,
                actual_logical,
            )
            result.provenance = self._node_provenance(inputs)
            return result

    def _simulation_definition(self, type_id: str, name: str, inputs: tuple[str, ...]) -> NodeDefinition:
        return NodeDefinition(type_id, name, "Internal", None, inputs=inputs, hidden=True)

    def _simulation_copy(
        self, image: ImageResource, context: RenderContext, cache_key: str, logical_format: TextureFormat
    ) -> GpuImage:
        source = self.ensure_gpu(image, context)
        definition = self._simulation_definition("internal.simulation_copy", "Simulation Copy", ("Image",))
        result = self._dispatch(definition, [source], self._pack_params(context), context, cache_key, logical_format)
        result.provenance = source.provenance | frozenset({"gpu"})
        result.data_kind = image.data_kind
        result.precision = image.precision
        if isinstance(image, CpuImage):
            source.release()
        return result

    def evaluate_stateful_initial(
        self,
        definition: NodeDefinition,
        inputs: Mapping[str, ImageResource],
        parameters: Mapping[str, Any],
        context: RenderContext,
        cache_key: str,
        logical_format: TextureFormat,
        cancel_check: Callable[[], bool] | None = None,
    ) -> tuple[dict[str, ImageResource], ImageResource]:
        if cancel_check is not None and cancel_check():
            raise BackendCancelled("Simulation initialisation was cancelled")
        if definition.type_id == "simulation.frame_delay":
            source = inputs.get("Image")
            owned_source = source is None
            if source is None:
                source = self._blank(context, logical_format)
            stored = self._simulation_copy(source, context, f"{cache_key}:stored", logical_format)
            if owned_source and isinstance(source, GpuImage):
                source.release()
            blank = self._blank(context, logical_format)
            output = self._simulation_copy(blank, context, f"{cache_key}:output", logical_format)
            blank.release()
            return {"stored": stored}, output
        if definition.type_id == "simulation.temporal_blend":
            source = inputs.get("Image")
            owned_source = source is None
            if source is None:
                source = self._blank(context, logical_format)
            result = self._simulation_copy(source, context, f"{cache_key}:history", logical_format)
            if owned_source and isinstance(source, GpuImage):
                source.release()
            return {"history": result}, result
        if definition.type_id == "simulation.reaction_diffusion":
            seed_resource = inputs.get("Seed")
            owned_seed = seed_resource is None
            seed = self.ensure_gpu(seed_resource, context) if seed_resource is not None else self._blank(context, TextureFormat.R16F)
            init_definition = self._simulation_definition(
                "internal.simulation_reaction_init", "Reaction Diffusion Initialise", ("Seed",)
            )
            state = self._dispatch(
                init_definition,
                [seed],
                self._pack_params(
                    context,
                    (
                        float(parameters.get("seed", 1)),
                        float(parameters.get("seed_count", 12)),
                        float(parameters.get("seed_radius", 0.025)),
                        float(parameters.get("seed_strength", 1.0)),
                    ),
                    (1.0 if seed_resource is not None else 0.0, 0.0, 0.0, 0.0),
                ),
                context,
                f"{cache_key}:chemicals",
                TextureFormat.RGBA16F,
            )
            output_definition = self._simulation_definition(
                "internal.simulation_reaction_output", "Reaction Diffusion Output", ("State",)
            )
            output = self._dispatch(
                output_definition, [state], self._pack_params(context), context, f"{cache_key}:output", logical_format
            )
            if isinstance(seed_resource, CpuImage) or owned_seed:
                seed.release()
            return {"chemicals": state}, output
        raise NotImplementedError(f"No WebGPU state initializer for {definition.type_id}")

    def evaluate_stateful_step(
        self,
        definition: NodeDefinition,
        previous_state: Mapping[str, ImageResource],
        inputs: Mapping[str, ImageResource],
        parameters: Mapping[str, Any],
        context: RenderContext,
        cache_key: str,
        logical_format: TextureFormat,
        cancel_check: Callable[[], bool] | None = None,
    ) -> tuple[dict[str, ImageResource], ImageResource]:
        if cancel_check is not None and cancel_check():
            raise BackendCancelled("Simulation step was cancelled")
        if definition.type_id == "simulation.frame_delay":
            previous = previous_state["stored"]
            current = inputs.get("Image")
            owned_current = current is None
            if current is None:
                current = self._blank(context, logical_format)
            output = self._simulation_copy(previous, context, f"{cache_key}:output", logical_format)
            stored = self._simulation_copy(current, context, f"{cache_key}:stored", logical_format)
            if owned_current and isinstance(current, GpuImage):
                current.release()
            return {"stored": stored}, output
        if definition.type_id == "simulation.temporal_blend":
            current_resource = inputs.get("Image")
            owned_current = current_resource is None
            if current_resource is None:
                current_resource = self._blank(context, logical_format)
            history_resource = previous_state["history"]
            current = self.ensure_gpu(current_resource, context)
            history = self.ensure_gpu(history_resource, context)
            step_definition = self._simulation_definition(
                "internal.simulation_temporal_blend", "Temporal Blend Step", ("Current", "History")
            )
            result = self._dispatch(
                step_definition,
                [current, history],
                self._pack_params(context, (float(parameters.get("persistence", 0.85)), 0.0, 0.0, 0.0)),
                context,
                f"{cache_key}:history",
                logical_format,
            )
            if isinstance(current_resource, CpuImage) or owned_current:
                current.release()
            if isinstance(history_resource, CpuImage):
                history.release()
            return {"history": result}, result
        if definition.type_id == "simulation.reaction_diffusion":
            state_resource = previous_state["chemicals"]
            state = self.ensure_gpu(state_resource, context)
            seed_resource = inputs.get("Seed")
            owned_seed = seed_resource is None
            seed = self.ensure_gpu(seed_resource, context) if seed_resource is not None else self._blank(context, TextureFormat.R16F)
            step_definition = self._simulation_definition(
                "internal.simulation_reaction_step", "Reaction Diffusion Step", ("State", "Seed")
            )
            current = state
            intermediates: list[GpuImage] = []
            substeps = min(max(int(parameters.get("steps_per_frame", 8)), 1), 64)
            for index in range(substeps):
                if cancel_check is not None and cancel_check():
                    for image in intermediates:
                        image.release()
                    if current is not state and current not in intermediates:
                        current.release()
                    if isinstance(state_resource, CpuImage):
                        state.release()
                    if isinstance(seed_resource, CpuImage) or owned_seed:
                        seed.release()
                    raise BackendCancelled("Reaction diffusion was cancelled")
                next_state = self._dispatch(
                    step_definition,
                    [current, seed],
                    self._pack_params(
                        context,
                        (
                            float(parameters.get("feed", 0.055)),
                            float(parameters.get("kill", 0.062)),
                            float(parameters.get("diffusion_u", 0.16)),
                            float(parameters.get("diffusion_v", 0.08)),
                        ),
                        (
                            float(parameters.get("time_step", 1.0)),
                            float(parameters.get("continuous_seed", 0.0)),
                            0.0,
                            0.0,
                        ),
                    ),
                    context,
                    f"{cache_key}:substep:{index}",
                    TextureFormat.RGBA16F,
                )
                if current is not state:
                    intermediates.append(current)
                current = next_state
            for image in intermediates:
                if image is not current:
                    image.release()
            if isinstance(state_resource, CpuImage):
                state.release()
            if isinstance(seed_resource, CpuImage) or owned_seed:
                seed.release()
            output_definition = self._simulation_definition(
                "internal.simulation_reaction_output", "Reaction Diffusion Output", ("State",)
            )
            output = self._dispatch(
                output_definition, [current], self._pack_params(context), context, f"{cache_key}:output", logical_format
            )
            return {"chemicals": current}, output
        raise NotImplementedError(f"No WebGPU state stepper for {definition.type_id}")

    def evaluate_fused_adjustments(
        self,
        source: GpuImage,
        operations: list[tuple[float, float, float, float, float, float, float, float]],
        context: RenderContext,
        cache_key: str,
        logical_format: TextureFormat,
    ) -> GpuImage:
        """Evaluate up to eight compatible adjustment nodes in one dispatch.

        Each operation occupies two aligned vec4 groups. The final value in the
        second group selects the original node's output quantisation so fusing
        a 16-bit or 8-bit chain preserves the same intermediate precision.
        """
        if not operations:
            return source
        if len(operations) > 8:
            raise ValueError("A fused adjustment pass supports at most eight operations")
        groups: list[tuple[float, float, float, float]] = [
            (float(len(operations)), 0.0, 0.0, 0.0)
        ]
        for operation in operations:
            if len(operation) != 8:
                raise ValueError("Fused adjustment operations require eight values")
            groups.append(tuple(float(value) for value in operation[0:4]))
            groups.append(tuple(float(value) for value in operation[4:8]))
        while len(groups) < 17:
            groups.append((0.0, 0.0, 0.0, 0.0))
        definition = NodeDefinition(
            "internal.fused_adjustments",
            "Fused Adjustments",
            "Internal",
            None,
            inputs=("Image",),
            gpu_kernel="fused_adjustments.wgsl",
            output_format=logical_format.value,
            hidden=True,
        )
        result = self._dispatch(
            definition,
            [source],
            self._pack_param_groups(context, *groups),
            context,
            cache_key,
            logical_format,
        )
        result.provenance = source.provenance | frozenset({"gpu"})
        return result

    def quantize8(self, image: GpuImage, context: RenderContext, cache_key: str) -> GpuImage:
        definition = NodeDefinition(
            "internal.quantize8", "Quantize 8-bit", "Internal", None,
            inputs=("Image",), gpu_kernel="quantize8.wgsl",
            output_format=image.logical_format.value,
        )
        result = self._dispatch(
            definition, [image], self._pack_params(context), context,
            f"{cache_key}:quantize8", image.logical_format,
        )
        result.provenance = image.provenance
        result.data_kind = image.data_kind
        result.precision = "8-bit"
        return result

    @staticmethod
    def _node_provenance(inputs: Mapping[str, ImageResource]) -> frozenset[str]:
        provenance = frozenset({"gpu"})
        for resource in inputs.values():
            provenance = provenance | resource.provenance
        return provenance

    def _evaluate_highpass(
        self,
        definition: NodeDefinition,
        inputs: Mapping[str, ImageResource],
        parameters: Mapping[str, Any],
        context: RenderContext,
        cache_key: str,
        logical_format: TextureFormat,
    ) -> GpuImage:
        source_resource = inputs.get("Image")
        source = self.ensure_gpu(source_resource, context) if source_resource is not None else self._blank(context)
        kind = str(getattr(source, "data_kind", parameters.get("_resolved_kind", "grayscale")))
        kind_code = {"grayscale": 0.0, "color": 1.0, "vector": 2.0}.get(kind, 0.0)
        working = source
        prepared: GpuImage | None = None
        if kind == "color":
            prepare_def = self._simulation_definition("internal.highpass_prepare", "Highpass Colour Prepare", ("Image",))
            prepared = self._dispatch(
                prepare_def, [source], self._pack_params(context), context,
                f"{cache_key}:highpass-srgb", logical_format,
            )
            prepared.data_kind = "color"
            working = prepared
        blur_def = self._simulation_definition("filter.blur", "Highpass Gaussian Separation", ("Image",))
        blurred = self._evaluate_blur(
            blur_def, {"Image": working}, {
                "radius": float(parameters.get("radius", 16.0)),
                "boundary": str(parameters.get("boundary", "Clamp")),
            },
            context, f"{cache_key}:highpass-low", logical_format,
        )
        combine_def = self._simulation_definition(
            "internal.highpass_combine", "Highpass Detail Combine", ("Image", "Blurred")
        )
        result = self._dispatch(
            combine_def, [working, blurred], self._pack_params(context, (kind_code, 0.0, 0.0, 0.0)),
            context, cache_key, logical_format,
        )
        result.data_kind = kind
        result.precision = getattr(source, "precision", "16-bit")
        blurred.release()
        if prepared is not None:
            prepared.release()
        return result

    def _evaluate_make_it_tile_photo(
        self,
        definition: NodeDefinition,
        inputs: Mapping[str, ImageResource],
        parameters: Mapping[str, Any],
        context: RenderContext,
        cache_key: str,
        logical_format: TextureFormat,
    ) -> GpuImage:
        source_resource = inputs.get("Image")
        source = self.ensure_gpu(source_resource, context) if source_resource is not None else self._blank(context)
        kind = str(getattr(source, "data_kind", parameters.get("_resolved_kind", "grayscale")))
        kind_code = {"grayscale": 0.0, "color": 1.0, "vector": 2.0}.get(kind, 0.0)
        result = self._dispatch(
            definition,
            [source],
            self._pack_params(
                context,
                (
                    min(max(float(parameters.get("mask_size_h", 0.14)), 0.001), 0.5),
                    min(max(float(parameters.get("mask_precision_h", 0.35)), 0.0), 1.0),
                    min(max(float(parameters.get("mask_warping_h", 35.0)), 0.0), 100.0),
                    kind_code,
                ),
                (
                    min(max(float(parameters.get("mask_size_v", 0.10)), 0.001), 0.5),
                    min(max(float(parameters.get("mask_precision_v", 0.35)), 0.0), 1.0),
                    min(max(float(parameters.get("mask_warping_v", 35.0)), 0.0), 100.0),
                    1.0 if bool(parameters.get("horizontal", True)) else 0.0,
                ),
                (
                    1.0 if bool(parameters.get("vertical", True)) else 0.0,
                    0.0,
                    0.0,
                    0.0,
                ),
            ),
            context,
            cache_key,
            logical_format,
        )
        result.data_kind = kind
        result.precision = getattr(source, "precision", "16-bit")
        return result

    def _evaluate_lighting_equalisation(
        self,
        definition: NodeDefinition,
        inputs: Mapping[str, ImageResource],
        parameters: Mapping[str, Any],
        context: RenderContext,
        cache_key: str,
        logical_format: TextureFormat,
    ) -> GpuImage:
        source_resource = inputs.get("Image")
        source = self.ensure_gpu(source_resource, context) if source_resource is not None else self._blank(context)
        kind = str(getattr(source, "data_kind", parameters.get("_resolved_kind", "grayscale")))
        kind_code = {"grayscale": 0.0, "color": 1.0, "vector": 2.0}.get(kind, 0.0)
        working = source
        prepared: GpuImage | None = None
        if kind == "color":
            prepare_def = self._simulation_definition(
                "internal.highpass_prepare", "Lighting Equalisation Colour Prepare", ("Image",)
            )
            prepared = self._dispatch(
                prepare_def,
                [source],
                self._pack_params(context),
                context,
                f"{cache_key}:lighting-srgb",
                logical_format,
            )
            prepared.data_kind = "color"
            working = prepared
        blur_def = self._simulation_definition("filter.blur", "Lighting Field", ("Image",))
        blurred = self._evaluate_blur(
            blur_def,
            {"Image": working},
            {
                "radius": float(parameters.get("radius", 96.0)),
                "boundary": str(parameters.get("boundary", "Clamp")),
            },
            context,
            f"{cache_key}:lighting-low",
            logical_format,
        )
        result = self._dispatch(
            definition,
            [working, blurred],
            self._pack_params(
                context,
                (
                    kind_code,
                    min(max(float(parameters.get("strength", 1.0)), 0.0), 1.0),
                    min(max(float(parameters.get("target_luminance", 0.5)), 0.01), 1.0),
                    1.0 if str(parameters.get("mode", "Luminance")) == "RGB Channels" else 0.0,
                ),
            ),
            context,
            cache_key,
            logical_format,
        )
        result.data_kind = kind
        result.precision = getattr(source, "precision", "16-bit")
        blurred.release()
        if prepared is not None:
            prepared.release()
        return result

    def _evaluate_atlas_splitter(
        self,
        definition: NodeDefinition,
        inputs: Mapping[str, ImageResource],
        parameters: Mapping[str, Any],
        context: RenderContext,
        cache_key: str,
        logical_format: TextureFormat,
    ) -> GpuImage:
        source_resource = inputs.get("Image")
        source = self.ensure_gpu(source_resource, context) if source_resource is not None else self._blank(context)
        kind = str(getattr(source, "data_kind", parameters.get("_resolved_kind", "grayscale")))
        cpu_inputs = {"Image": self.to_cpu(source).array}
        mask_resource = inputs.get("Mask")
        if mask_resource is not None:
            cpu_inputs["Mask"] = self.to_cpu(mask_resource).array
        eval_context = EvalContext(
            width=context.width,
            height=context.height,
            time_seconds=context.time_seconds,
            frame_number=context.frame_number,
            frame_position=context.frame_position,
            delta_time=context.delta_time,
            duration_seconds=context.duration_seconds,
            normalised_time=context.normalised_time,
            loop_phase=context.loop_phase,
            frames_per_second=context.frames_per_second,
            document_frame_count=context.document_frame_count,
            loop_start_frame=context.loop_start_frame,
            loop_end_frame=context.loop_end_frame,
            render_mode=context.render_mode,
        )
        assert definition.evaluator is not None
        array = np.ascontiguousarray(
            definition.evaluator(cpu_inputs, {**parameters, "_resolved_kind": kind}, eval_context),
            dtype=np.float32,
        )
        cpu_result = CpuImage(
            array,
            logical_format,
            cache_key,
            self._node_provenance(inputs),
            data_kind=kind,
            precision=getattr(source, "precision", "16-bit"),
        )
        result = self.ensure_gpu(cpu_result, context)
        result.cache_key = cache_key
        result.data_kind = kind
        result.precision = getattr(source, "precision", "16-bit")
        return result

    def _evaluate_normal_to_height(
        self,
        definition: NodeDefinition,
        inputs: Mapping[str, ImageResource],
        parameters: Mapping[str, Any],
        context: RenderContext,
        cache_key: str,
        logical_format: TextureFormat,
    ) -> GpuImage:
        """Perform the global Poisson integration on CPU, then resume on GPU."""
        source_resource = inputs.get("Normal")
        source = (
            self.ensure_gpu(source_resource, context)
            if source_resource is not None
            else self._solid_colour(
                context, (0.5, 0.5, 1.0, 1.0), TextureFormat.RGBA16F, data_kind="vector"
            )
        )
        eval_context = EvalContext(
            width=context.width,
            height=context.height,
            time_seconds=context.time_seconds,
            frame_number=context.frame_number,
            frame_position=context.frame_position,
            delta_time=context.delta_time,
            duration_seconds=context.duration_seconds,
            normalised_time=context.normalised_time,
            loop_phase=context.loop_phase,
            frames_per_second=context.frames_per_second,
            document_frame_count=context.document_frame_count,
            loop_start_frame=context.loop_start_frame,
            loop_end_frame=context.loop_end_frame,
            render_mode=context.render_mode,
        )
        assert definition.evaluator is not None
        array = np.ascontiguousarray(
            definition.evaluator({"Normal": self.to_cpu(source).array}, parameters, eval_context),
            dtype=np.float32,
        )
        cpu_result = CpuImage(
            array,
            logical_format,
            cache_key,
            self._node_provenance(inputs) | frozenset({"cpu"}),
            data_kind="grayscale",
            precision="16-bit",
        )
        result = self.ensure_gpu(cpu_result, context)
        result.cache_key = cache_key
        result.data_kind = "grayscale"
        result.precision = "16-bit"
        return result

    def _evaluate_auto_crop(
        self,
        definition: NodeDefinition,
        inputs: Mapping[str, ImageResource],
        parameters: Mapping[str, Any],
        context: RenderContext,
        cache_key: str,
        logical_format: TextureFormat,
    ) -> GpuImage:
        source_resource = inputs.get("Image")
        source = self.ensure_gpu(source_resource, context) if source_resource is not None else self._blank(context)
        array = self.to_cpu(source).array
        threshold = min(max(float(parameters.get("threshold", 0.001)), 0.0), 1.0)
        if bool(parameters.get("use_alpha", False)):
            values = array[..., 3]
        else:
            values = array[..., :3] @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        ys, xs = np.nonzero(values > threshold)
        has_content = xs.size > 0 and ys.size > 0
        if has_content:
            padding = min(max(float(parameters.get("padding", 0.0)), 0.0), 0.5)
            left = max(float(xs.min()) / context.width - padding, 0.0)
            right = min(float(xs.max() + 1) / context.width + padding, 1.0)
            top = max(float(ys.min()) / context.height - padding, 0.0)
            bottom = min(float(ys.max() + 1) / context.height + padding, 1.0)
        else:
            left, top, right, bottom = 0.0, 0.0, 1.0, 1.0
        modes = {"Crop Square": 0.0, "Crop Auto": 1.0, "Fit (Keep Ratio)": 2.0, "Fill (Stretch)": 3.0}
        filters = {"Automatic": 0.0, "Auto": 0.0, "Nearest": 1.0, "Bilinear": 2.0, "Bicubic": 3.0}
        kind = str(getattr(source, "data_kind", parameters.get("_resolved_kind", "grayscale")))
        kind_code = {"grayscale": 0.0, "color": 1.0, "vector": 2.0}.get(kind, 0.0)
        result = self._dispatch(
            definition, [source],
            self._pack_params(
                context,
                (left, top, right, bottom),
                (
                    modes.get(str(parameters.get("mode", "Fit (Keep Ratio)")), 2.0),
                    filters.get(str(parameters.get("filtering", "Automatic")), 0.0),
                    kind_code,
                    1.0 if has_content else 0.0,
                ),
            ),
            context, cache_key, logical_format,
        )
        result.data_kind = kind
        result.precision = getattr(source, "precision", "16-bit")
        return result

    def _evaluate_blur(
        self,
        definition: NodeDefinition,
        inputs: Mapping[str, ImageResource],
        parameters: Mapping[str, Any],
        context: RenderContext,
        cache_key: str,
        logical_format: TextureFormat,
    ) -> GpuImage:
        source_resource = inputs.get("Image")
        source = self.ensure_gpu(source_resource, context) if source_resource is not None else self._blank(context)
        radius = min(max(relative_pixels(float(parameters.get("radius", 0.0)), context), 0.0), 2048.0)
        logical = logical_format
        clamp_boundary = 0.0 if str(parameters.get("boundary", "Seamless / Wrap")) == "Seamless / Wrap" else 1.0
        if radius <= 0.01:
            return self._dispatch(
                definition,
                [source],
                self._pack_params(context, (0.0, 1.0, 0.0, clamp_boundary)),
                context,
                cache_key,
                logical,
            )
        horizontal = self._dispatch(
            definition,
            [source],
            self._pack_params(context, (radius, 1.0, 0.0, clamp_boundary)),
            context,
            f"{cache_key}:blur-x",
            logical,
        )
        result = self._dispatch(
            definition,
            [horizontal],
            self._pack_params(context, (radius, 0.0, 1.0, clamp_boundary)),
            context,
            cache_key,
            logical,
        )
        horizontal.release()
        return result

    def _evaluate_hbao(
        self,
        definition: NodeDefinition,
        inputs: Mapping[str, ImageResource],
        parameters: Mapping[str, Any],
        context: RenderContext,
        cache_key: str,
        logical_format: TextureFormat,
    ) -> GpuImage:
        """Evaluate raw horizon AO, then reconstruct it with a joint blur.

        The reconstruction pass is intentionally height-aware: it smooths the
        sparse horizon samples across one surface while preventing dark ground
        AO from bleeding onto the top of a raised shape. Keeping all three
        passes GPU-resident avoids a readback and makes the quality correction
        practical for live graph work.
        """

        height_resource = inputs.get("Height")
        height = (
            self.ensure_gpu(height_resource, context)
            if height_resource is not None
            else self._blank(context, TextureFormat.R16F)
        )
        parameter_block = self._parameter_block(
            definition.type_id, parameters, context, [height]
        )
        raw = self._dispatch(
            definition, [height], parameter_block, context,
            f"{cache_key}:hbao-raw", logical_format,
        )

        authored_radius = max(float(parameters.get("radius", 0.15)), 0.0)
        depth = max(float(parameters.get("height_depth", 0.10)), 0.0)
        if authored_radius <= 1e-8 or depth <= 1e-8:
            raw.cache_key = cache_key
            return raw

        radius_pixels = max(
            authored_radius * 0.5 * min(context.width, context.height), 1.0
        )
        sigma = min(max(radius_pixels * 0.065, 0.65), 6.0)
        if context.render_mode == "interactive":
            sigma = min(sigma, 2.25)
        height_sigma = min(max(0.035 + depth * 0.025, 0.035), 0.065)
        wrap = 1.0 if str(parameters.get("boundary", "Seamless / Wrap")) == "Seamless / Wrap" else 0.0
        blur_definition = self._simulation_definition(
            "internal.hbao_bilateral_blur", "HBAO Joint Reconstruction", ("AO", "Height")
        )
        horizontal = self._dispatch(
            blur_definition,
            [raw, height],
            self._pack_params(
                context,
                (sigma, 1.0, 0.0, height_sigma),
                (wrap, 0.0, 0.0, 0.0),
            ),
            context,
            f"{cache_key}:hbao-reconstruct-x",
            logical_format,
        )
        result = self._dispatch(
            blur_definition,
            [horizontal, height],
            self._pack_params(
                context,
                (sigma, 0.0, 1.0, height_sigma),
                (wrap, 0.0, 0.0, 0.0),
            ),
            context,
            cache_key,
            logical_format,
        )
        raw.release()
        horizontal.release()
        return result

    def _evaluate_rtao(
        self,
        definition: NodeDefinition,
        inputs: Mapping[str, ImageResource],
        parameters: Mapping[str, Any],
        context: RenderContext,
        cache_key: str,
        logical_format: TextureFormat,
    ) -> GpuImage:
        """Trace height-field rays, then denoise their stochastic visibility.

        The raw pass is intentionally expensive but self-contained: no hardware
        ray-tracing feature is required. The reconstruction remains GPU-resident
        and uses the source height as its edge guide, preserving raised surfaces
        while removing per-pixel hemisphere noise.
        """

        height_resource = inputs.get("Height")
        height = (
            self.ensure_gpu(height_resource, context)
            if height_resource is not None
            else self._blank(context, TextureFormat.R16F)
        )
        parameter_block = self._parameter_block(
            definition.type_id, parameters, context, [height]
        )
        raw = self._dispatch(
            definition, [height], parameter_block, context,
            f"{cache_key}:rtao-raw", logical_format,
        )

        height_scale = max(float(parameters.get("height_scale", 1.0)), 0.0)
        maximum_distance = min(max(float(parameters.get("maximum_distance", 0.15)), 0.0), 1.0)
        denoise = min(max(float(parameters.get("denoise", 0.75)), 0.0), 1.0)
        if height_scale <= 1e-8 or maximum_distance <= 1e-8 or denoise <= 1e-8:
            raw.cache_key = cache_key
            return raw

        maximum_distance_pixels = max(
            maximum_distance * min(context.width, context.height), 1.0
        )
        sigma = min(max(0.55 + maximum_distance_pixels * 0.035 * denoise, 0.55), 5.0)
        if context.render_mode == "interactive":
            sigma = min(sigma, 2.0)
        height_sigma = min(max(0.018 + 0.035 / (1.0 + height_scale), 0.018), 0.053)
        wrap = 1.0 if str(parameters.get("boundary", "Seamless / Wrap")) == "Seamless / Wrap" else 0.0
        blur_definition = self._simulation_definition(
            "internal.hbao_bilateral_blur", "RTAO Height-Aware Denoise", ("AO", "Height")
        )
        horizontal = self._dispatch(
            blur_definition,
            [raw, height],
            self._pack_params(
                context,
                (sigma, 1.0, 0.0, height_sigma),
                (wrap, 0.0, 0.0, 0.0),
            ),
            context,
            f"{cache_key}:rtao-denoise-x",
            logical_format,
        )
        result = self._dispatch(
            blur_definition,
            [horizontal, height],
            self._pack_params(
                context,
                (sigma, 0.0, 1.0, height_sigma),
                (wrap, 0.0, 0.0, 0.0),
            ),
            context,
            cache_key,
            logical_format,
        )
        raw.release()
        horizontal.release()
        return result

    def _evaluate_bent_normal(
        self,
        definition: NodeDefinition,
        inputs: Mapping[str, ImageResource],
        parameters: Mapping[str, Any],
        context: RenderContext,
        cache_key: str,
        logical_format: TextureFormat,
    ) -> GpuImage:
        """Trace a bent visibility direction, then denoise it against height."""

        height_resource = inputs.get("Height")
        height = (
            self.ensure_gpu(height_resource, context)
            if height_resource is not None
            else self._blank(context, TextureFormat.R16F)
        )
        parameter_block = self._parameter_block(
            definition.type_id, parameters, context, [height]
        )
        raw = self._dispatch(
            definition, [height], parameter_block, context,
            f"{cache_key}:bent-raw", logical_format,
        )

        height_scale = max(float(parameters.get("height_scale", 1.0)), 0.0)
        maximum_distance = min(max(float(parameters.get("maximum_distance", 0.15)), 0.0), 1.0)
        denoise = min(max(float(parameters.get("denoise", 0.75)), 0.0), 1.0)
        if height_scale <= 1e-8 or maximum_distance <= 1e-8 or denoise <= 1e-8:
            raw.cache_key = cache_key
            return raw

        maximum_distance_pixels = max(
            maximum_distance * min(context.width, context.height), 1.0
        )
        sigma = min(max(0.55 + maximum_distance_pixels * 0.035 * denoise, 0.55), 5.0)
        if context.render_mode == "interactive":
            sigma = min(sigma, 2.0)
        height_sigma = min(max(0.018 + 0.035 / (1.0 + height_scale), 0.018), 0.053)
        wrap = 1.0 if str(parameters.get("boundary", "Seamless / Wrap")) == "Seamless / Wrap" else 0.0
        blur_definition = self._simulation_definition(
            "internal.bent_normal_denoise", "Bent Normal Height-Aware Denoise", ("Normal", "Height")
        )
        horizontal = self._dispatch(
            blur_definition, [raw, height],
            self._pack_params(
                context,
                (sigma, 1.0, 0.0, height_sigma),
                (wrap, 0.0, 0.0, 0.0),
            ),
            context, f"{cache_key}:bent-denoise-x", logical_format,
        )
        result = self._dispatch(
            blur_definition, [horizontal, height],
            self._pack_params(
                context,
                (sigma, 0.0, 1.0, height_sigma),
                (wrap, 0.0, 0.0, 0.0),
            ),
            context, cache_key, logical_format,
        )
        raw.release()
        horizontal.release()
        return result

    def _build_distance_seeds(
        self,
        source: GpuImage,
        context: RenderContext,
        cache_key: str,
        *,
        threshold: float,
        input_invert: float,
        wrap: float,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
        progress_base: int = 0,
        progress_total: int | None = None,
    ) -> GpuImage:
        init_definition = self._simulation_definition(
            "internal.distance_seed_init", "Distance Seed Initialise", ("Image",)
        )
        jump_definition = self._simulation_definition(
            "internal.distance_seed_jump", "Distance Seed Jump", ("Seeds",)
        )
        steps = _jump_steps(context.width, context.height)
        total = progress_total if progress_total is not None else len(steps) + 1
        seeds = self._dispatch(
            init_definition, [source],
            self._pack_params(context, (threshold, input_invert, 0.0, 0.0)),
            context, f"{cache_key}:distance-seeds-init", TextureFormat.RGBA16F,
        )
        if progress_callback is not None:
            progress_callback(progress_base + 1, total)
        for pass_index, step in enumerate(steps):
            if cancel_check is not None and cancel_check():
                seeds.release()
                raise BackendCancelled("Distance-field evaluation was cancelled")
            following = self._dispatch(
                jump_definition, [seeds],
                self._pack_params(context, (float(step), wrap, 0.0, 0.0)),
                context, f"{cache_key}:distance-seeds-{pass_index}", TextureFormat.RGBA16F,
            )
            seeds.release()
            seeds = following
            if progress_callback is not None:
                progress_callback(progress_base + pass_index + 2, total)
        return seeds

    def _evaluate_distance_profile(
        self,
        definition: NodeDefinition,
        inputs: Mapping[str, ImageResource],
        parameters: Mapping[str, Any],
        context: RenderContext,
        cache_key: str,
        logical_format: TextureFormat,
        *,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> GpuImage:
        """Evaluate distance, bevel, mask morphology and outline profiles.

        Up to 2048 pixels per axis the connected-component distance seeds and
        final profile remain entirely on WebGPU. Larger images retain the
        existing memory-safe CPU-assisted route because RGBA16F cannot store
        every integer pixel coordinate exactly beyond that range.
        """
        source_resource = inputs.get("Image")
        source = self.ensure_gpu(source_resource, context) if source_resource is not None else self._blank(context, TextureFormat.R16F)
        if max(context.width, context.height) > 2048:
            source_cpu = self.to_cpu(source).array
            eval_context = EvalContext(
                width=context.width, height=context.height,
                time_seconds=context.time_seconds, frame_number=context.frame_number,
                frame_position=context.frame_position, delta_time=context.delta_time,
                duration_seconds=context.duration_seconds, normalised_time=context.normalised_time,
                loop_phase=context.loop_phase, frames_per_second=context.frames_per_second,
                document_frame_count=context.document_frame_count,
                loop_start_frame=context.loop_start_frame, loop_end_frame=context.loop_end_frame,
                render_mode=context.render_mode,
            )
            assert definition.evaluator is not None
            array = np.ascontiguousarray(definition.evaluator({"Image": source_cpu}, parameters, eval_context), dtype=np.float32)
            cpu_result = CpuImage(
                array, logical_format, cache_key,
                self._node_provenance(inputs) | frozenset({"cpu"}),
                data_kind="grayscale", precision="16-bit",
            )
            result = self.ensure_gpu(cpu_result, context)
            result.cache_key = cache_key
            return result

        threshold = float(parameters.get("threshold", 0.5))
        input_invert = 1.0 if bool(parameters.get("input_invert", False)) else 0.0
        wrap = 1.0 if str(parameters.get("boundary", "Seamless / Wrap")) == "Seamless / Wrap" else 0.0
        spatial_scale = resolution_scale(context)
        steps_per_field = len(_jump_steps(context.width, context.height)) + 1
        operation = str(parameters.get("operation", "Expand"))
        two_stage = definition.type_id == "filter.expand_shrink" and operation in {"Open", "Close"}
        total_progress = (steps_per_field + 1) * (2 if two_stage else 1)
        seeds = self._build_distance_seeds(
            source, context, cache_key, threshold=threshold, input_invert=input_invert, wrap=wrap,
            cancel_check=cancel_check, progress_callback=progress_callback,
            progress_base=0, progress_total=total_progress,
        )

        if definition.type_id == "filter.distance":
            modes = {"Inside": 0.0, "Outside": 1.0, "Signed": 2.0, "Absolute": 3.0}
            parameter_block = self._pack_params(
                context,
                (
                    float(parameters.get("distance", 32.0)) * spatial_scale,
                    float(parameters.get("edge_offset", 0.0)) * spatial_scale,
                    float(parameters.get("curve", 1.0)),
                    float(parameters.get("smoothness", 0.0)),
                ),
                (modes.get(str(parameters.get("mode", "Inside")), 0.0), threshold, input_invert, wrap),
                (1.0 if bool(parameters.get("invert", False)) else 0.0, 0.0, 0.0, 0.0),
            )
            result = self._dispatch(definition, [source, seeds], parameter_block, context, cache_key, logical_format)
        elif definition.type_id == "filter.bevel":
            directions = {"Inner": 0.0, "Outer": 1.0, "Centered": 2.0, "Edge Ridge": 3.0}
            profiles = {"Linear": 0.0, "Smooth": 1.0, "Rounded": 2.0, "Concave": 3.0, "Convex": 4.0}
            parameter_block = self._pack_params(
                context,
                (
                    float(parameters.get("width", 16.0)) * spatial_scale,
                    float(parameters.get("edge_offset", 0.0)) * spatial_scale,
                    float(parameters.get("height", 1.0)),
                    float(parameters.get("background", 0.0)),
                ),
                (
                    directions.get(str(parameters.get("direction", "Inner")), 0.0),
                    profiles.get(str(parameters.get("profile", "Rounded")), 2.0),
                    float(parameters.get("smoothness", 0.0)), threshold,
                ),
                (
                    input_invert, wrap,
                    1.0 if bool(parameters.get("invert", False)) else 0.0,
                    1.0 if bool(parameters.get("clamp", True)) else 0.0,
                ),
            )
            result = self._dispatch(definition, [source, seeds], parameter_block, context, cache_key, logical_format)
        elif definition.type_id == "filter.outline":
            directions = {"Inner": 0.0, "Outer": 1.0, "Centered": 2.0}
            parameter_block = self._pack_params(
                context,
                (
                    float(parameters.get("width", 8.0)) * spatial_scale,
                    float(parameters.get("edge_offset", 0.0)) * spatial_scale,
                    float(parameters.get("softness", 0.5)) * spatial_scale,
                    directions.get(str(parameters.get("direction", "Centered")), 2.0),
                ),
                (
                    threshold, input_invert, wrap,
                    1.0 if bool(parameters.get("invert", False)) else 0.0,
                ),
            )
            result = self._dispatch(definition, [source, seeds], parameter_block, context, cache_key, logical_format)
        else:
            amount = float(parameters.get("amount", 8.0)) * spatial_scale
            softness = float(parameters.get("softness", 0.0)) * spatial_scale
            invert = 1.0 if bool(parameters.get("invert", False)) else 0.0
            if operation in {"Expand", "Shrink"}:
                mode = 0.0 if operation == "Expand" else 1.0
                parameter_block = self._pack_params(
                    context, (amount, softness, mode, 0.0), (threshold, input_invert, wrap, invert)
                )
                result = self._dispatch(definition, [source, seeds], parameter_block, context, cache_key, logical_format)
            else:
                first_mode = 1.0 if operation == "Open" else 0.0
                second_mode = 0.0 if operation == "Open" else 1.0
                first_block = self._pack_params(
                    context, (amount, 0.0, first_mode, 0.0), (threshold, input_invert, wrap, 0.0)
                )
                intermediate = self._dispatch(
                    definition, [source, seeds], first_block, context, f"{cache_key}:morphology-first", logical_format
                )
                seeds.release()
                seeds = self._build_distance_seeds(
                    intermediate, context, f"{cache_key}:morphology-second",
                    threshold=0.5, input_invert=0.0, wrap=wrap,
                    cancel_check=cancel_check, progress_callback=progress_callback,
                    progress_base=steps_per_field + 1, progress_total=total_progress,
                )
                final_block = self._pack_params(
                    context, (amount, softness, second_mode, 0.0), (0.5, 0.0, wrap, invert)
                )
                result = self._dispatch(
                    definition, [intermediate, seeds], final_block, context, cache_key, logical_format
                )
                intermediate.release()

        seeds.release()
        if progress_callback is not None:
            progress_callback(total_progress, total_progress)
        return result

    def _evaluate_aperture(
        self,
        definition: NodeDefinition,
        inputs: Mapping[str, ImageResource],
        parameters: Mapping[str, Any],
        context: RenderContext,
        cache_key: str,
        logical_format: TextureFormat,
        *,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> GpuImage:
        source_resource = inputs.get("Image")
        source = self.ensure_gpu(source_resource, context) if source_resource is not None else self._blank(context, TextureFormat.R16F)
        size = max(int(round(relative_pixels(float(parameters.get("size", 8)), context))), 0)
        strength = min(max(float(parameters.get("strength", 1.0)), 0.0), 1.0)
        modes = {"Dilation": 0.0, "Erosion": 1.0}
        shapes = {"Disk": 0.0, "Polygon": 1.0, "Asterisk": 2.0, "Line": 3.0, "Corner": 4.0}
        mode = modes.get(str(parameters.get("mode", "Dilation")), 0.0)
        shape = shapes.get(str(parameters.get("shape", "Disk")), 0.0)
        vertices = float(max(int(parameters.get("vertices", 6)), 3))
        direction = float(parameters.get("direction", 0.0))
        corner_angle = float(parameters.get("corner_angle", 90.0))
        antialiased = 1.0 if bool(parameters.get("antialiased", True)) else 0.0
        wrap = 1.0 if str(parameters.get("boundary", "Seamless / Wrap")) == "Seamless / Wrap" else 0.0

        if size <= 0 or strength <= 0.0:
            mix_definition = self._simulation_definition(
                "internal.aperture_mix", "Aperture Mix", ("Processed", "Original")
            )
            return self._dispatch(
                mix_definition, [source, source], self._pack_params(context, (0.0, 0.0, 0.0, 0.0)),
                context, cache_key, logical_format,
            )

        current = source
        intermediates: list[GpuImage] = []
        # Filled Disk/Polygon footprints are evaluated in radius-four chunks.
        # Minkowski addition preserves their silhouette while keeping each
        # shader pass bounded to an inexpensive 9x9 neighbourhood. Directional
        # Asterisk/Line/Corner shapes retain their one-pixel iterative steps.
        if int(shape + 0.5) in {0, 1}:
            pass_radii: list[int] = []
            remaining = size
            while remaining > 0:
                radius = min(4, remaining)
                pass_radii.append(radius)
                remaining -= radius
        else:
            pass_radii = [1] * size
        pass_count = len(pass_radii)
        total_progress = pass_count + (1 if strength < 1.0 else 0)

        for pass_index, radius in enumerate(pass_radii):
            if cancel_check is not None and cancel_check():
                for image in intermediates:
                    image.release()
                raise BackendCancelled("Aperture evaluation was cancelled")
            block = self._pack_params(
                context, (mode, shape, vertices, float(radius)),
                (direction, corner_angle, antialiased, wrap),
            )
            following = self._dispatch(
                definition, [current], block, context,
                f"{cache_key}:aperture-{pass_index}", logical_format,
            )
            self._wait_for_submitted_work(
                cancel_check, cooperative=context.render_mode != "final" and pass_index < pass_count - 1
            )
            if current is not source:
                intermediates.append(current)
            current = following
            if progress_callback is not None:
                progress_callback(pass_index + 1, total_progress)

        if strength < 1.0:
            mix_definition = self._simulation_definition(
                "internal.aperture_mix", "Aperture Mix", ("Processed", "Original")
            )
            result = self._dispatch(
                mix_definition, [current, source], self._pack_params(context, (strength, 0.0, 0.0, 0.0)),
                context, cache_key, logical_format,
            )
            self._wait_for_submitted_work(cancel_check, cooperative=False)
            intermediates.append(current)
            current = result
            if progress_callback is not None:
                progress_callback(total_progress, total_progress)
        else:
            current.cache_key = cache_key

        for image in intermediates:
            if image is not current:
                image.release()
        return current

    def _evaluate_thermal_erosion(
        self,
        definition: NodeDefinition,
        inputs: Mapping[str, ImageResource],
        parameters: Mapping[str, Any],
        context: RenderContext,
        cache_key: str,
        logical_format: TextureFormat,
        *,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> GpuImage:
        """Run iterative thermal erosion entirely on the GPU.

        The state texture stores height, accumulated erosion, accumulated
        deposition and hardness. Two RGBA32F textures are ping-ponged through
        all iterations without CPU readback between passes. Iterations are
        submitted in small batches so stale previews can be cancelled.
        """
        assert self.device is not None and self.queue is not None
        height_resource = inputs.get("Height")
        height = self.ensure_gpu(height_resource, context) if height_resource is not None else self._blank(context)
        hardness_resource = inputs.get("Hardness")
        hardness = self.ensure_gpu(hardness_resource, context) if hardness_resource is not None else self._blank(context)

        quality = str(parameters.get("quality", "Automatic"))
        preview_iterations = max(int(parameters.get("preview_iterations", 28)), 0)
        final_iterations = max(int(parameters.get("final_iterations", 140)), 0)
        iterations = preview_iterations if quality == "Preview" else final_iterations if quality == "Final" else (
            final_iterations if context.render_mode == "final" else preview_iterations
        )
        if context.render_mode == "interactive":
            iterations = min(iterations, 8)
        iterations = min(iterations, 2000)

        angle = math.radians(min(max(float(parameters.get("talus_angle", 34.0)), 0.0), 89.0))
        height_scale = max(float(parameters.get("height_scale", 1.0)), 1e-6)
        talus = math.tan(angle) / max(min(context.width, context.height), 1) / height_scale
        strength = min(max(float(parameters.get("erosion_strength", 0.42)), 0.0), 1.0)
        max_transfer = max(float(parameters.get("max_transfer", 0.025)), 0.0)
        mobility = min(max(float(parameters.get("talus_mobility", 0.65)), 0.0), 1.0)
        rock_resistance = min(max(float(parameters.get("rock_resistance", 0.12)), 0.0), 1.0)
        fracture_strength = min(max(float(parameters.get("fracture_strength", 0.16)), 0.0), 1.0)
        fracture_scale = min(max(float(parameters.get("fracture_scale", 0.35)), 0.0), 1.0)
        shape_protection = min(max(float(parameters.get("shape_protection", 0.08)), 0.0), 1.0)
        seed = float(int(parameters.get("seed", 1)))
        preserve_per_iteration = shape_protection * 0.25 / max(iterations, 1)
        neighbourhood = 8.0 if str(parameters.get("neighbourhood", "8 Neighbours")) == "8 Neighbours" else 4.0
        boundary = {"Seamless / Wrap": 0.0, "Closed": 1.0, "Drain": 2.0}.get(str(parameters.get("boundary", "Seamless / Wrap")), 0.0)

        init_def = NodeDefinition("internal.thermal_init", "Thermal Init", "Internal", None, inputs=("Height", "Hardness"))
        step_def = NodeDefinition("internal.thermal_step", "Thermal Step", "Internal", None, inputs=("State", "Original"))
        select_def = NodeDefinition("internal.thermal_select", "Thermal Select", "Internal", None, inputs=("State",))
        init_pipeline = self._pipeline(init_def, "rgba32float")
        step_pipeline = self._pipeline(step_def, "rgba32float")
        state_a = self._new_texture(context, TextureFormat.RGBA32F, f"{cache_key}:thermal-a")
        state_b = self._new_texture(context, TextureFormat.RGBA32F, f"{cache_key}:thermal-b")

        def uniform_buffer(data: bytes, label: str):
            size = max(64, ((len(data) + 15) // 16) * 16)
            buffer = self.device.create_buffer(
                label=label, size=size,
                usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
            )
            self.queue.write_buffer(buffer, 0, data + bytes(size - len(data)))
            return buffer, size

        init_uniform, init_size = uniform_buffer(self._pack_params(context), "VFXTL thermal init params")
        step_uniform, step_size = uniform_buffer(
            self._pack_params(
                context,
                (talus, strength, max_transfer, neighbourhood),
                (boundary, mobility, rock_resistance, preserve_per_iteration),
                (fracture_strength, fracture_scale, seed, 0.0),
            ),
            "VFXTL thermal step params",
        )
        init_group = self.device.create_bind_group(
            label="VFXTL thermal init bindings",
            layout=init_pipeline.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": {"buffer": init_uniform, "offset": 0, "size": init_size}},
                {"binding": 1, "resource": height.view},
                {"binding": 2, "resource": hardness.view},
                {"binding": 3, "resource": state_a.view},
            ],
        )
        group_ab = self.device.create_bind_group(
            label="VFXTL thermal A to B",
            layout=step_pipeline.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": {"buffer": step_uniform, "offset": 0, "size": step_size}},
                {"binding": 1, "resource": state_a.view},
                {"binding": 2, "resource": height.view},
                {"binding": 3, "resource": state_b.view},
            ],
        )
        group_ba = self.device.create_bind_group(
            label="VFXTL thermal B to A",
            layout=step_pipeline.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": {"buffer": step_uniform, "offset": 0, "size": step_size}},
                {"binding": 1, "resource": state_b.view},
                {"binding": 2, "resource": height.view},
                {"binding": 3, "resource": state_a.view},
            ],
        )
        if cancel_check is not None and cancel_check():
            raise BackendCancelled("Thermal erosion evaluation was cancelled")

        # Initialise once, then submit erosion in small ordered batches. Queue
        # submission order preserves the ping-pong state, while the gaps between
        # batches let the async evaluator cancel a stale heavy preview instead
        # of waiting for every requested iteration to finish.
        init_encoder = self.device.create_command_encoder(label="VFXTL thermal erosion initialise")
        init_pass = init_encoder.begin_compute_pass(label="Thermal erosion initialise")
        init_pass.set_pipeline(init_pipeline)
        init_pass.set_bind_group(0, init_group)
        init_pass.dispatch_workgroups(math.ceil(context.width / 8), math.ceil(context.height / 8), 1)
        init_pass.end()
        self.queue.submit([init_encoder.finish()])
        cooperative = context.render_mode != "final"
        self._wait_for_submitted_work(cancel_check, cooperative=cooperative)

        batch_size = 2 if context.render_mode == "interactive" else 4 if cooperative else 8
        completed = 0
        total_progress = iterations + 2  # initialise + iterations + output selection
        if progress_callback is not None:
            progress_callback(1, total_progress)
        while completed < iterations:
            if cancel_check is not None and cancel_check():
                raise BackendCancelled("Thermal erosion evaluation was cancelled")
            stop = min(completed + batch_size, iterations)
            encoder = self.device.create_command_encoder(
                label=f"VFXTL thermal erosion iterations {completed + 1}-{stop}"
            )
            for iteration in range(completed, stop):
                compute_pass = encoder.begin_compute_pass(label=f"Thermal erosion iteration {iteration + 1}")
                compute_pass.set_pipeline(step_pipeline)
                compute_pass.set_bind_group(0, group_ab if iteration % 2 == 0 else group_ba)
                compute_pass.dispatch_workgroups(math.ceil(context.width / 8), math.ceil(context.height / 8), 1)
                compute_pass.end()
            self.queue.submit([encoder.finish()])
            self._wait_for_submitted_work(cancel_check, cooperative=cooperative)
            completed = stop
            if progress_callback is not None:
                progress_callback(1 + completed, total_progress)

        if cancel_check is not None and cancel_check():
            raise BackendCancelled("Thermal erosion evaluation was cancelled")
        final_state = state_b if iterations % 2 == 1 else state_a
        output_index = {"Eroded Height": 0.0, "Erosion": 1.0, "Deposition": 2.0}.get(
            str(parameters.get("preview_output", "Eroded Height")), 0.0
        )
        result = self._dispatch(
            select_def,
            [final_state],
            self._pack_params(context, (output_index, float(parameters.get("mask_gain", 8.0)), 0.0, 0.0)),
            context,
            cache_key,
            logical_format,
        )
        self._wait_for_submitted_work(cancel_check, cooperative=False)
        if progress_callback is not None:
            progress_callback(total_progress, total_progress)
        result.data_kind = "grayscale"
        return result


    def _evaluate_flow_accumulation(
        self,
        definition: NodeDefinition,
        inputs: Mapping[str, ImageResource],
        parameters: Mapping[str, Any],
        context: RenderContext,
        cache_key: str,
        logical_format: TextureFormat,
        *,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> GpuImage:
        assert self.device is not None and self.queue is not None
        height_resource = inputs.get("Height")
        height = self.ensure_gpu(height_resource, context) if height_resource is not None else self._blank(context)
        rain_resource = inputs.get("Rainfall Mask")
        rain = self.ensure_gpu(rain_resource, context) if rain_resource is not None else self._white(context, TextureFormat.R16F)
        quality = str(parameters.get("quality", "Automatic"))
        preview = max(int(parameters.get("preview_iterations", 32)), 0)
        final = max(int(parameters.get("final_iterations", 128)), 0)
        iterations = preview if quality == "Preview" else final if quality == "Final" else (
            final if context.render_mode == "final" else preview
        )
        if context.render_mode == "interactive":
            iterations = min(iterations, 16)
        iterations = min(iterations, 2000)
        retention = min(max(float(parameters.get("retention", 0.94)), 0.0), 0.999)
        minimum_slope = max(float(parameters.get("minimum_slope", 0.0001)), 0.0)
        neighbourhood = 8.0 if str(parameters.get("neighbourhood", "8 Neighbours")) == "8 Neighbours" else 4.0
        boundary = {"Seamless / Wrap": 0.0, "Closed": 1.0, "Drain": 2.0}.get(str(parameters.get("boundary", "Seamless / Wrap")), 0.0)

        init_def = NodeDefinition("internal.flow_accum_init", "Flow Accum Init", "Internal", None, inputs=("Rainfall Mask",))
        step_def = NodeDefinition("internal.flow_accum_step", "Flow Accum Step", "Internal", None, inputs=("Height", "State"))
        select_def = NodeDefinition("internal.flow_accum_select", "Flow Accum Select", "Internal", None, inputs=("State",))
        init_pipeline = self._pipeline(init_def, "rgba32float")
        step_pipeline = self._pipeline(step_def, "rgba32float")
        state_a = self._new_texture(context, TextureFormat.RGBA32F, f"{cache_key}:flow-a")
        state_b = self._new_texture(context, TextureFormat.RGBA32F, f"{cache_key}:flow-b")

        def ub(data: bytes, label: str):
            size = max(64, ((len(data) + 15) // 16) * 16)
            buffer = self.device.create_buffer(label=label, size=size, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
            self.queue.write_buffer(buffer, 0, data + bytes(size - len(data)))
            return buffer, size

        init_uniform, init_size = ub(self._pack_params(context), "VFXTL flow accumulation init params")
        step_uniform, step_size = ub(self._pack_params(context, (retention, minimum_slope, neighbourhood, boundary)), "VFXTL flow accumulation step params")
        init_group = self.device.create_bind_group(label="VFXTL flow accumulation init bindings", layout=init_pipeline.get_bind_group_layout(0), entries=[
            {"binding":0,"resource":{"buffer":init_uniform,"offset":0,"size":init_size}},
            {"binding":1,"resource":rain.view},{"binding":2,"resource":state_a.view},
        ])
        group_ab = self.device.create_bind_group(label="VFXTL flow accumulation A to B", layout=step_pipeline.get_bind_group_layout(0), entries=[
            {"binding":0,"resource":{"buffer":step_uniform,"offset":0,"size":step_size}},
            {"binding":1,"resource":height.view},{"binding":2,"resource":state_a.view},{"binding":3,"resource":state_b.view},
        ])
        group_ba = self.device.create_bind_group(label="VFXTL flow accumulation B to A", layout=step_pipeline.get_bind_group_layout(0), entries=[
            {"binding":0,"resource":{"buffer":step_uniform,"offset":0,"size":step_size}},
            {"binding":1,"resource":height.view},{"binding":2,"resource":state_b.view},{"binding":3,"resource":state_a.view},
        ])
        if cancel_check is not None and cancel_check():
            raise BackendCancelled("Flow accumulation evaluation was cancelled")
        cooperative = context.render_mode != "final"
        total_progress = iterations + 2
        encoder = self.device.create_command_encoder(label="VFXTL flow accumulation initialise")
        cp = encoder.begin_compute_pass(label="Flow accumulation initialise")
        cp.set_pipeline(init_pipeline)
        cp.set_bind_group(0, init_group)
        cp.dispatch_workgroups(math.ceil(context.width / 8), math.ceil(context.height / 8), 1)
        cp.end()
        self.queue.submit([encoder.finish()])
        self._wait_for_submitted_work(cancel_check, cooperative=cooperative)
        if progress_callback is not None:
            progress_callback(1, total_progress)
        completed = 0
        batch_size = 2 if context.render_mode == "interactive" else 4 if cooperative else 8
        while completed < iterations:
            if cancel_check is not None and cancel_check():
                raise BackendCancelled("Flow accumulation evaluation was cancelled")
            stop = min(completed + batch_size, iterations)
            encoder = self.device.create_command_encoder(label=f"VFXTL flow accumulation {completed + 1}-{stop}")
            for iteration in range(completed, stop):
                cp = encoder.begin_compute_pass(label=f"Flow accumulation iteration {iteration + 1}")
                cp.set_pipeline(step_pipeline)
                cp.set_bind_group(0, group_ab if iteration % 2 == 0 else group_ba)
                cp.dispatch_workgroups(math.ceil(context.width / 8), math.ceil(context.height / 8), 1)
                cp.end()
            self.queue.submit([encoder.finish()])
            self._wait_for_submitted_work(cancel_check, cooperative=cooperative)
            completed = stop
            if progress_callback is not None:
                progress_callback(1 + completed, total_progress)
        final_state = state_b if iterations % 2 == 1 else state_a
        result = self._dispatch(
            select_def,
            [final_state],
            self._pack_params(
                context,
                (float(parameters.get("gain", 1.0)), 1.0 if bool(parameters.get("invert", False)) else 0.0, 0.0, 0.0),
            ),
            context,
            cache_key,
            logical_format,
        )
        self._wait_for_submitted_work(cancel_check, cooperative=False)
        if progress_callback is not None:
            progress_callback(total_progress, total_progress)
        result.data_kind = "grayscale"
        return result

    def _evaluate_hydraulic_erosion(
        self,
        definition: NodeDefinition,
        inputs: Mapping[str, ImageResource],
        parameters: Mapping[str, Any],
        context: RenderContext,
        cache_key: str,
        logical_format: TextureFormat,
        *,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> GpuImage:
        """Run stream-power fluvial erosion with coherent drainage on GPU.

        Each erosion pass rebuilds a D8 drainage field on a smoothed routing
        surface, propagates rainfall through that field, then applies channel
        incision, bank widening and deposition.  Height and all masks remain
        GPU-resident throughout the complete solve.
        """
        assert self.device is not None and self.queue is not None

        def image(name: str, white: bool = False) -> GpuImage:
            resource = inputs.get(name)
            if resource is not None:
                return self.ensure_gpu(resource, context)
            return self._white(context, TextureFormat.R16F) if white else self._blank(context, TextureFormat.R16F)

        height = image("Height")
        rain = image("Rainfall Mask", True)
        hardness = image("Hardness")

        quality = str(parameters.get("quality", "Automatic"))
        preview_erosion = max(int(parameters.get("preview_iterations", 12)), 0)
        final_erosion = max(int(parameters.get("final_iterations", 40)), 0)
        preview_drainage = max(int(parameters.get("preview_drainage_iterations", 56)), 1)
        final_drainage = max(int(parameters.get("final_drainage_iterations", 112)), 1)
        if quality == "Preview":
            erosion_iterations, drainage_iterations = preview_erosion, preview_drainage
        elif quality == "Final":
            erosion_iterations, drainage_iterations = final_erosion, final_drainage
        elif context.render_mode == "final":
            erosion_iterations, drainage_iterations = final_erosion, final_drainage
        else:
            erosion_iterations, drainage_iterations = preview_erosion, preview_drainage
        if context.render_mode == "interactive":
            erosion_iterations = min(erosion_iterations, 4)
            drainage_iterations = min(drainage_iterations, 24)
        erosion_iterations = min(erosion_iterations, 512)
        drainage_iterations = min(drainage_iterations, 2048)

        rainfall = max(float(parameters.get("rainfall", 0.62)), 0.0)
        duration = max(float(parameters.get("erosion_duration", 1.10)), 0.0)
        if rainfall <= 1e-12 or duration <= 1e-12:
            erosion_iterations = 0
        boundary = {"Seamless / Wrap": 0.0, "Closed": 1.0, "Drain": 2.0}.get(
            str(parameters.get("boundary", "Seamless / Wrap")), 0.0
        )
        erosion_scale = min(max(float(parameters.get("erosion_scale", 0.35)), 0.0), 1.0)
        resolution_factor = max(min(context.width, context.height) / 512.0, 0.75)
        feature_radius = max(1, min(32, int(round(1.0 + erosion_scale * 4.0 * resolution_factor))))

        init_def = NodeDefinition("internal.fluvial_init", "Fluvial Init", "Internal", None, inputs=("Height", "Rainfall Mask", "Hardness"))
        flow_init_def = NodeDefinition("internal.fluvial_flow_init", "Fluvial Flow Init", "Internal", None, inputs=("State",))
        flow_step_def = NodeDefinition("internal.fluvial_flow_step", "Fluvial Flow Step", "Internal", None, inputs=("State", "Flow"))
        erode_def = NodeDefinition("internal.fluvial_erode", "Fluvial Erode", "Internal", None, inputs=("State", "Accum", "Flow"))
        select_def = NodeDefinition("internal.fluvial_select", "Fluvial Select", "Internal", None, inputs=("State", "Accum", "Flow"))

        init_pipeline = self._pipeline(init_def, "rgba32float")
        flow_init_pipeline = self._pipeline(flow_init_def, "rgba32float")
        flow_step_pipeline = self._pipeline(flow_step_def, "rgba32float")
        erode_pipeline = self._pipeline(erode_def, "rgba32float")

        state_a = self._new_texture(context, TextureFormat.RGBA32F, f"{cache_key}:fluvial-state-a")
        state_b = self._new_texture(context, TextureFormat.RGBA32F, f"{cache_key}:fluvial-state-b")
        accum_a = self._new_texture(context, TextureFormat.RGBA32F, f"{cache_key}:fluvial-accum-a")
        accum_b = self._new_texture(context, TextureFormat.RGBA32F, f"{cache_key}:fluvial-accum-b")
        flow_a = self._new_texture(context, TextureFormat.RGBA32F, f"{cache_key}:fluvial-flow-a")
        flow_b = self._new_texture(context, TextureFormat.RGBA32F, f"{cache_key}:fluvial-flow-b")

        def uniform_buffer(data: bytes, label: str):
            size = max(64, ((len(data) + 15) // 16) * 16)
            buffer = self.device.create_buffer(
                label=label,
                size=size,
                usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
            )
            self.queue.write_buffer(buffer, 0, data + bytes(size - len(data)))
            return buffer, size

        init_uniform, init_size = uniform_buffer(self._pack_params(context), "VFXTL fluvial init params")
        flow_init_bytes = self._pack_param_groups(
            context,
            (
                float(parameters.get("terrain_smoothing", 0.58)),
                float(parameters.get("depression_handling", 0.45)),
                rainfall,
                float(parameters.get("rain_variation", 0.10)),
            ),
            (
                float(parameters.get("seed", 1)),
                boundary,
                float(parameters.get("height_scale", 1.0)),
                float(feature_radius),
            ),
        )
        flow_init_uniform, flow_init_size = uniform_buffer(flow_init_bytes, "VFXTL fluvial flow-init params")
        flow_step_bytes = self._pack_param_groups(
            context,
            (
                float(parameters.get("flow_retention", 0.955)),
                rainfall,
                float(parameters.get("rain_variation", 0.10)),
                0.0,
            ),
            (float(parameters.get("seed", 1)), boundary, 0.0, 0.0),
        )
        flow_step_uniform, flow_step_size = uniform_buffer(flow_step_bytes, "VFXTL fluvial flow-step params")
        step_scale = 1.0 / max(erosion_iterations, 1)
        erode_bytes = self._pack_param_groups(
            context,
            (
                step_scale,
                duration,
                float(parameters.get("channel_depth", 0.27)),
                float(parameters.get("max_erosion_step", 0.020)),
            ),
            (
                float(parameters.get("tributary_density", 0.30)),
                float(parameters.get("channel_width", 0.075)),
                float(parameters.get("headwater_detail", 0.18)),
                float(parameters.get("valley_widening", 0.38)),
            ),
            (
                float(parameters.get("bank_erosion", 0.22)),
                float(parameters.get("deposition", 0.14)),
                float(parameters.get("sediment_spread", 0.42)),
                float(parameters.get("terrain_uplift", 0.08)),
            ),
            (
                float(parameters.get("post_thermal_smoothing", 0.12)),
                float(parameters.get("drainage_exponent", 1.35)),
                float(parameters.get("slope_exponent", 0.72)),
                float(parameters.get("flow_gain", 0.012)),
            ),
            (float(feature_radius), boundary, float(parameters.get("rock_resistance", 0.12)), float(parameters.get("sediment_transport", 0.62))),
        )
        erode_uniform, erode_size = uniform_buffer(erode_bytes, "VFXTL fluvial erosion params")

        init_group = self.device.create_bind_group(
            label="VFXTL fluvial init bindings",
            layout=init_pipeline.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": {"buffer": init_uniform, "offset": 0, "size": init_size}},
                {"binding": 1, "resource": height.view},
                {"binding": 2, "resource": rain.view},
                {"binding": 3, "resource": hardness.view},
                {"binding": 4, "resource": state_a.view},
                {"binding": 5, "resource": accum_a.view},
            ],
        )

        def flow_init_group(state: GpuImage, output: GpuImage, label: str):
            return self.device.create_bind_group(
                label=label,
                layout=flow_init_pipeline.get_bind_group_layout(0),
                entries=[
                    {"binding": 0, "resource": {"buffer": flow_init_uniform, "offset": 0, "size": flow_init_size}},
                    {"binding": 1, "resource": state.view},
                    {"binding": 2, "resource": output.view},
                ],
            )

        def flow_step_group(state: GpuImage, source: GpuImage, output: GpuImage, label: str):
            return self.device.create_bind_group(
                label=label,
                layout=flow_step_pipeline.get_bind_group_layout(0),
                entries=[
                    {"binding": 0, "resource": {"buffer": flow_step_uniform, "offset": 0, "size": flow_step_size}},
                    {"binding": 1, "resource": state.view},
                    {"binding": 2, "resource": source.view},
                    {"binding": 3, "resource": output.view},
                ],
            )

        def erode_group(state: GpuImage, accum: GpuImage, flow: GpuImage, out_state: GpuImage, out_accum: GpuImage, label: str):
            return self.device.create_bind_group(
                label=label,
                layout=erode_pipeline.get_bind_group_layout(0),
                entries=[
                    {"binding": 0, "resource": {"buffer": erode_uniform, "offset": 0, "size": erode_size}},
                    {"binding": 1, "resource": state.view},
                    {"binding": 2, "resource": accum.view},
                    {"binding": 3, "resource": flow.view},
                    {"binding": 4, "resource": out_state.view},
                    {"binding": 5, "resource": out_accum.view},
                ],
            )

        if cancel_check is not None and cancel_check():
            raise BackendCancelled("Fluvial erosion evaluation was cancelled")
        encoder = self.device.create_command_encoder(label="VFXTL fluvial initialise")
        cp = encoder.begin_compute_pass(label="Fluvial initialise")
        cp.set_pipeline(init_pipeline); cp.set_bind_group(0, init_group)
        cp.dispatch_workgroups(math.ceil(context.width / 8), math.ceil(context.height / 8), 1)
        cp.end(); self.queue.submit([encoder.finish()])

        cooperative = context.render_mode != "final"
        self._wait_for_submitted_work(cancel_check, cooperative=cooperative)
        current_state, next_state = state_a, state_b
        current_accum, next_accum = accum_a, accum_b
        final_flow = flow_a
        cycles = max(erosion_iterations, 1)
        erosion_per_cycle = 1 if erosion_iterations > 0 else 0
        cycle_work = 1 + drainage_iterations + erosion_per_cycle
        total_progress = 2 + cycles * cycle_work  # initialisation + cycles + output selection
        progress_done = 1
        if progress_callback is not None:
            progress_callback(progress_done, total_progress)
        for cycle in range(cycles):
            if cancel_check is not None and cancel_check():
                raise BackendCancelled("Fluvial erosion evaluation was cancelled")

            encoder = self.device.create_command_encoder(label=f"VFXTL fluvial drainage initialise {cycle + 1}")
            cp = encoder.begin_compute_pass(label=f"Fluvial drainage initialise {cycle + 1}")
            cp.set_pipeline(flow_init_pipeline)
            cp.set_bind_group(0, flow_init_group(current_state, flow_a, f"VFXTL flow init {cycle + 1}"))
            cp.dispatch_workgroups(math.ceil(context.width / 8), math.ceil(context.height / 8), 1)
            cp.end(); self.queue.submit([encoder.finish()])
            self._wait_for_submitted_work(cancel_check, cooperative=cooperative)
            progress_done += 1
            if progress_callback is not None:
                progress_callback(progress_done, total_progress)

            completed = 0
            batch_size = 2 if context.render_mode == "interactive" else 4 if cooperative else 8
            while completed < drainage_iterations:
                if cancel_check is not None and cancel_check():
                    raise BackendCancelled("Fluvial erosion evaluation was cancelled")
                stop = min(completed + batch_size, drainage_iterations)
                encoder = self.device.create_command_encoder(label=f"VFXTL fluvial drainage {cycle + 1}:{completed + 1}-{stop}")
                for iteration in range(completed, stop):
                    source_flow = flow_a if iteration % 2 == 0 else flow_b
                    output_flow = flow_b if iteration % 2 == 0 else flow_a
                    cp = encoder.begin_compute_pass(label=f"Fluvial drainage pass {iteration + 1}")
                    cp.set_pipeline(flow_step_pipeline)
                    cp.set_bind_group(0, flow_step_group(current_state, source_flow, output_flow, f"VFXTL flow {cycle}:{iteration}"))
                    cp.dispatch_workgroups(math.ceil(context.width / 8), math.ceil(context.height / 8), 1)
                    cp.end()
                self.queue.submit([encoder.finish()])
                self._wait_for_submitted_work(cancel_check, cooperative=cooperative)
                advanced = stop - completed
                completed = stop
                progress_done += advanced
                if progress_callback is not None:
                    progress_callback(progress_done, total_progress)
            final_flow = flow_b if drainage_iterations % 2 == 1 else flow_a

            if cycle < erosion_iterations:
                encoder = self.device.create_command_encoder(label=f"VFXTL fluvial erosion pass {cycle + 1}")
                cp = encoder.begin_compute_pass(label=f"Fluvial erosion pass {cycle + 1}")
                cp.set_pipeline(erode_pipeline)
                cp.set_bind_group(0, erode_group(current_state, current_accum, final_flow, next_state, next_accum, f"VFXTL erode {cycle + 1}"))
                cp.dispatch_workgroups(math.ceil(context.width / 8), math.ceil(context.height / 8), 1)
                cp.end(); self.queue.submit([encoder.finish()])
                self._wait_for_submitted_work(cancel_check, cooperative=cooperative)
                current_state, next_state = next_state, current_state
                current_accum, next_accum = next_accum, current_accum
                progress_done += 1
                if progress_callback is not None:
                    progress_callback(progress_done, total_progress)

        output_name = str(parameters.get("preview_output", "Eroded Height"))
        output_index = {
            "Eroded Height": 0.0,
            "Erosion": 1.0,
            "Deposition": 2.0,
            "Flow Accumulation": 3.0,
            "Channel Mask": 4.0,
            "Water": 5.0,
            "Sediment": 6.0,
            "Wetness": 7.0,
            "Flow Direction": 8.0,
        }.get(output_name, 0.0)
        select_bytes = self._pack_param_groups(
            context,
            (
                output_index,
                float(parameters.get("mask_gain", 8.0)),
                float(parameters.get("flow_display_gain", 1.0)),
                float(parameters.get("channel_gain", 1.0)),
            ),
            (
                float(parameters.get("water_gain", 1.0)),
                float(parameters.get("sediment_gain", 8.0)),
                float(parameters.get("wetness_gain", 1.0)),
                float(parameters.get("flow_gain", 0.012)),
            ),
        )
        result = self._dispatch(
            select_def,
            [current_state, current_accum, final_flow],
            select_bytes,
            context,
            cache_key,
            logical_format,
        )
        self._wait_for_submitted_work(cancel_check, cooperative=False)
        progress_done += 1
        if progress_callback is not None:
            progress_callback(total_progress, total_progress)
        result.data_kind = "vector" if output_index == 8.0 else "grayscale"
        return result

    def _parameter_block(
        self,
        type_id: str,
        parameters: Mapping[str, Any],
        context: RenderContext,
        inputs: list[GpuImage] | None = None,
    ) -> bytes:
        flag = lambda value: 1.0 if bool(value) else 0.0
        scalar_flags = [1.0 if image.logical_format.channels == 1 else 0.0 for image in (inputs or [])]
        scalar = lambda index: scalar_flags[index] if index < len(scalar_flags) else 1.0
        if type_id == "generator.constant":
            return self._pack_params(context, (float(parameters.get("value", 0.5)), 0.0, 0.0, 0.0))
        if type_id == "generator.color":
            color_values = parse_hex_color(str(parameters.get("color", "#ffffffff")))
            color_values[:3] = srgb_to_linear(color_values[:3])
            color = tuple(float(value) for value in color_values)
            return self._pack_params(context, color)  # type: ignore[arg-type]
        if type_id == "generator.linear_gradient":
            return self._pack_params(context, (
                float(parameters.get("angle", 0.0)),
                float(parameters.get("offset", 0.0)),
                flag(parameters.get("repeat", True)),
                0.0,
            ))
        if type_id == "generator.radial_gradient":
            return self._pack_params(context, (
                float(parameters.get("center_x", 0.5)),
                float(parameters.get("center_y", 0.5)),
                float(parameters.get("radius", 0.5)),
                float(parameters.get("falloff", 1.0)),
            ))
        if type_id == "shape.shape":
            shapes = {
                "Rectangle": 0, "Rounded Rectangle": 1, "Disc": 2, "Ring": 3,
                "Capsule": 4, "Triangle": 5, "Diamond": 6, "Hexagon": 7,
                "Cross": 8, "X": 9, "Crescent": 10, "Bell": 11,
                "Gaussian": 12, "Pyramid": 13, "Cone": 14, "Hemisphere": 15,
                "Waves": 16, "Linear Gradation": 17,
            }
            fills = {"Solid": 0, "Outline": 1, "Linear Bevel": 2, "Rounded Bevel": 3}
            return self._pack_param_groups(
                context,
                (
                    float(shapes.get(str(parameters.get("shape", "Rectangle")), 0)),
                    float(fills.get(str(parameters.get("fill_mode", "Solid")), 0)),
                    float(parameters.get("center_x", 0.5)),
                    float(parameters.get("center_y", 0.5)),
                ),
                (
                    float(parameters.get("size_x", 1.0)),
                    float(parameters.get("size_y", 1.0)),
                    float(parameters.get("scale", 0.8)),
                    float(parameters.get("rotation", 0.0)),
                ),
                (
                    float(parameters.get("tile_x", 1.0)),
                    float(parameters.get("tile_y", 1.0)),
                    flag(parameters.get("non_square_compensation", True)),
                    geometric_raster_feather(parameters, EvalContext(context.width, context.height)),
                ),
                (
                    float(parameters.get("profile_width", 0.18)),
                    flag(parameters.get("invert", False)),
                    float(parameters.get("corner_radius", 0.25)),
                    float(parameters.get("thickness", 0.2)),
                ),
                (
                    float(parameters.get("capsule_length", 0.5)),
                    float(parameters.get("bar_thickness", 0.35)),
                    float(parameters.get("cutout_size", 0.8)),
                    float(parameters.get("cutout_offset_x", 0.35)),
                ),
                (
                    float(parameters.get("cutout_offset_y", 0.0)),
                    float(parameters.get("wave_frequency", 4.0)),
                    float(parameters.get("wave_phase", 0.0)),
                    float(parameters.get("wave_balance", 0.5)),
                ),
            )
        if type_id == "shape.polygon":
            fills = {"Solid": 0, "Outline": 1, "Linear Bevel": 2, "Rounded Bevel": 3}
            return self._pack_param_groups(
                context,
                (
                    float(parameters.get("sides", 6)),
                    float(parameters.get("inner_radius", 1.0)),
                    float(parameters.get("alternating_offset", 0.0)),
                    float(parameters.get("roundness", 0.0)),
                ),
                (
                    float(fills.get(str(parameters.get("fill_mode", "Solid")), 0)),
                    float(parameters.get("center_x", 0.5)),
                    float(parameters.get("center_y", 0.5)),
                    float(parameters.get("rotation", 0.0)),
                ),
                (
                    float(parameters.get("size_x", 1.0)),
                    float(parameters.get("size_y", 1.0)),
                    float(parameters.get("scale", 0.8)),
                    float(parameters.get("tile_x", 1.0)),
                ),
                (
                    float(parameters.get("tile_y", 1.0)),
                    flag(parameters.get("non_square_compensation", True)),
                    geometric_raster_feather(parameters, EvalContext(context.width, context.height)),
                    float(parameters.get("profile_width", 0.18)),
                ),
                (
                    float(parameters.get("twist", 0.0)),
                    float(parameters.get("radial_distortion", 0.0)),
                    flag(parameters.get("invert", False)),
                    0.0,
                ),
            )
        if type_id == "shape.polygon_burst":
            fills = {"Solid": 0, "Radial Gradient": 1, "Angular Gradient": 2}
            return self._pack_param_groups(
                context,
                (
                    float(parameters.get("sides", 6)),
                    float(fills.get(str(parameters.get("fill_mode", "Solid")), 0)),
                    float(parameters.get("explode", 0.0)),
                    float(parameters.get("slice_gap", 0.05)),
                ),
                (
                    float(parameters.get("inner_radius", 0.0)),
                    flag(parameters.get("alternate_value", False)),
                    float(parameters.get("alternate_strength", 0.5)),
                    float(parameters.get("center_x", 0.5)),
                ),
                (
                    float(parameters.get("center_y", 0.5)),
                    float(parameters.get("size_x", 1.0)),
                    float(parameters.get("size_y", 1.0)),
                    float(parameters.get("scale", 0.8)),
                ),
                (
                    float(parameters.get("rotation", 0.0)),
                    float(parameters.get("tile_x", 1.0)),
                    float(parameters.get("tile_y", 1.0)),
                    flag(parameters.get("non_square_compensation", True)),
                ),
                (
                    geometric_raster_feather(parameters, EvalContext(context.width, context.height)),
                    float(parameters.get("twist", 0.0)),
                    flag(parameters.get("invert", False)),
                    0.0,
                ),
            )
        if type_id == "pattern.checker":
            return self._pack_params(context, (
                float(parameters.get("scale", 8)),
                float(parameters.get("value_a", 0.0)),
                float(parameters.get("value_b", 1.0)),
                0.0,
            ))
        if type_id == "pattern.tile_sampler":
            patterns = {
                "Pattern Input": 0,
                "Pattern Input 2": 1,
                "Pattern Input 3": 2,
                "Pattern Input 4": 3,
                "Square": 4,
                "Disc": 5,
                "Brick": 6,
                "Capsule": 7,
                "Bell": 8,
                "Diamond": 9,
                "Hexagon": 10,
                "Triangle": 11,
            }
            selections = {"Single": 0, "Random Inputs": 1, "Sequential Inputs": 2, "Distribution Map": 3}
            offsets = {"None": 0, "Every Second Row": 1, "Every Second Column": 2, "Continuous Rows": 3, "Continuous Columns": 4}
            layout_masks = {"All Tiles": 0, "Checker": 1, "Alternate Rows": 2, "Alternate Columns": 3}
            blends = {"Maximum": 0, "Add": 1, "Subtract": 2, "Replace": 3}
            rendering_orders = {"Rows then Columns": 0, "Columns then Rows": 1}
            x_amount = max(int(parameters.get("x_amount", 8)), 1)
            y_amount = max(int(parameters.get("y_amount", 8)), 1)
            size_x = max(float(parameters.get("size_x", 0.8)), 0.001)
            size_y = max(float(parameters.get("size_y", 0.8)), 0.001)
            scale_value = max(float(parameters.get("scale", 1.0)), 0.001)
            candidate_radius = tile_sampler_candidate_radius(parameters)
            pixel_basis = max(min(context.width / x_amount, context.height / y_amount), 1.0e-6)
            pixel_feather = 1.25 / max(pixel_basis * min(size_x, size_y) * scale_value, 1.0)
            authored_feather = max(float(parameters.get("edge_softness", 0.0)), 0.0)
            effective_feather = (
                max(authored_feather, pixel_feather)
                if str(parameters.get("rasterization", "Pixel Exact")) == "Antialiased"
                else authored_feather
            )
            return self._pack_param_groups(
                context,
                (float(x_amount), float(y_amount), float(parameters.get("seed", 0)), flag(parameters.get("non_square_expansion", True))),
                (
                    float(patterns.get(str(parameters.get("pattern", "Square")), 4)),
                    float(selections.get(str(parameters.get("pattern_selection", "Single")), 0)),
                    float(parameters.get("_pattern_connected_mask", 0)),
                    effective_feather,
                ),
                (size_x, size_y, scale_value, float(parameters.get("scale_random", 0.0))),
                (
                    float(parameters.get("scale_map_strength", 0.0)),
                    float(parameters.get("scale_vector_map_strength", 0.0)),
                    float(parameters.get("position_random_x", 0.0)),
                    float(parameters.get("position_random_y", 0.0)),
                ),
                (
                    float(offsets.get(str(parameters.get("offset_mode", "Every Second Row")), 1)),
                    float(parameters.get("row_offset", 0.0)),
                    float(parameters.get("global_offset_x", 0.0)),
                    float(parameters.get("global_offset_y", 0.0)),
                ),
                (
                    float(parameters.get("displacement_intensity", 0.0)),
                    float(parameters.get("displacement_angle", 0.0)),
                    float(parameters.get("vector_displacement", 0.0)),
                    float(parameters.get("rotation", 0.0)),
                ),
                (
                    float(parameters.get("rotation_random", 0.0)),
                    float(parameters.get("rotation_map_multiplier", 0.0)),
                    float(parameters.get("mask_random", 0.0)),
                    float(parameters.get("mask_map_threshold", 0.5)),
                ),
                (
                    0.0,  # p8.x reserved; Tile Value was removed in 0.43.8.
                    float(parameters.get("luminance_random", 0.0)),
                    float(parameters.get("global_opacity", 1.0)),
                    float(blends.get(str(parameters.get("blend_mode", "Maximum")), 0)),
                ),
                (
                    float(parameters.get("background_value", 0.0)),
                    flag(parameters.get("mirror_x_random", False)),
                    flag(parameters.get("mirror_y_random", False)),
                    float(
                        (1 if bool(parameters.get("mask_map_invert", False)) else 0)
                        + (2 if bool(parameters.get("_mask_connected", False)) else 0)
                        + (4 if str(parameters.get("rasterization", "Pixel Exact")) == "Antialiased" else 0)
                        + (int(layout_masks.get(str(parameters.get("layout_mask", "All Tiles")), 0)) << 3)
                        + (32 if bool(parameters.get("invert_layout_mask", False)) else 0)
                    ),
                ),
                (
                    float(candidate_radius),
                    float(rendering_orders.get(str(parameters.get("rendering_order", "Rows then Columns")), 0)),
                    flag(parameters.get("reverse_rendering_order", False)),
                    flag(parameters.get("_background_connected", False)),
                ),
            )
        if type_id == "pattern.splatter_circular":
            patterns = {
                "Pattern Input": 0,
                "Pattern Input 2": 1,
                "Pattern Input 3": 2,
                "Pattern Input 4": 3,
                "Square": 4,
                "Disc": 5,
                "Brick": 6,
                "Capsule": 7,
                "Bell": 8,
                "Diamond": 9,
                "Hexagon": 10,
                "Triangle": 11,
            }
            selections = {"Single": 0, "Random Inputs": 1, "Sequential Around Ring": 2, "One Input per Ring": 3}
            orientations = {"Face Outward": 0, "Face Centre": 1, "Tangent": 2, "Fixed": 3}
            blends = {"Maximum": 0, "Add": 1, "Subtract": 2, "Replace": 3}
            authored_patterns = max(int(parameters.get("pattern_amount", 12)), 1)
            authored_rings = max(int(parameters.get("ring_amount", 3)), 1)
            if str(getattr(context, "render_mode", "preview")) == "interactive":
                authored_patterns = min(authored_patterns, 32)
                authored_rings = min(authored_rings, 6)
            return self._pack_param_groups(
                context,
                (
                    float(authored_patterns),
                    float(parameters.get("pattern_amount_random", 0.0)),
                    float(parameters.get("minimum_pattern_amount", 1)),
                    float(authored_rings),
                ),
                (
                    float(parameters.get("first_ring_radius", 0.15)),
                    float(parameters.get("ring_spacing", 0.12)),
                    float(parameters.get("radius_random", 0.0)),
                    float(parameters.get("arc_spread", 360.0)),
                ),
                (
                    float(parameters.get("ring_rotation", 0.0)),
                    float(parameters.get("ring_rotation_offset", 0.0)),
                    float(parameters.get("spiral", 0.0)),
                    float(parameters.get("angular_random", 0.0)),
                ),
                (
                    float(parameters.get("center_x", 0.5)),
                    float(parameters.get("center_y", 0.5)),
                    float(patterns.get(str(parameters.get("pattern", "Disc")), 5)),
                    float(selections.get(str(parameters.get("pattern_selection", "Single")), 0)),
                ),
                (
                    float(orientations.get(str(parameters.get("orientation", "Face Outward")), 0)),
                    float(parameters.get("pattern_rotation", 0.0)),
                    float(parameters.get("rotation_random", 0.0)),
                    float(parameters.get("rotation_by_ring", 0.0)),
                ),
                (
                    float(parameters.get("size_x", 0.12)),
                    float(parameters.get("size_y", 0.12)),
                    float(parameters.get("scale", 1.0)),
                    float(parameters.get("scale_random", 0.0)),
                ),
                (
                    float(parameters.get("scale_by_ring", 0.0)),
                    float(parameters.get("scale_by_pattern", 0.0)),
                    flag(parameters.get("connect_patterns", False)),
                    float(parameters.get("connect_scale", 1.0)),
                ),
                (
                    float(parameters.get("random_removal", 0.0)),
                    float(parameters.get("luminance", 1.0)),
                    float(parameters.get("luminance_random", 0.0)),
                    float(parameters.get("luminance_by_ring", 0.0)),
                ),
                (
                    float(parameters.get("luminance_by_pattern", 0.0)),
                    float(parameters.get("global_opacity", 1.0)),
                    float(blends.get(str(parameters.get("blend_mode", "Maximum")), 0)),
                    float(parameters.get("background_value", 0.0)),
                ),
                (
                    float(parameters.get("_pattern_connected_mask", 0)),
                    flag(str(parameters.get("rasterization", "Antialiased")) == "Antialiased"),
                    flag(parameters.get("_background_connected", False)),
                    float(parameters.get("edge_softness", 0.0)),
                ),
                (
                    float(parameters.get("seed", 0)),
                    6.0,
                    0.0,
                    0.0,
                ),
            )
        if type_id in {"noise.value", "noise.perlin"}:
            return self._pack_params(
                context,
                (
                    float(parameters.get("scale", 8.0)),
                    float(parameters.get("seed", 1)),
                    float(parameters.get("evolution", 0.0)),
                    float(parameters.get("loop_cycles", 1.0)),
                ),
                (
                    float(parameters.get("disorder", 0.0)),
                    float(parameters.get("disorder_scale", 3.0)),
                    float(parameters.get("contrast", 1.0)),
                    float(parameters.get("balance", 0.0)),
                ),
                (1.0 if type_id == "noise.perlin" else 0.0, flag(parameters.get("invert", False)), 0.0, 0.0),
            )
        if type_id == "noise.fractal":
            packed_mode = 8 if bool(parameters.get("invert", False)) else 0
            return self._pack_params(
                context,
                (
                    float(parameters.get("scale", 4.0)),
                    float(parameters.get("octaves", 5)),
                    float(parameters.get("lacunarity", 2.0)),
                    float(parameters.get("gain", 0.5)),
                ),
                (
                    float(parameters.get("seed", 1)),
                    float(parameters.get("evolution", 0.0)),
                    float(parameters.get("loop_cycles", 1.0)),
                    float(parameters.get("disorder", 0.0)),
                ),
                (
                    float(parameters.get("disorder_scale", 3.0)),
                    float(parameters.get("contrast", 1.0)),
                    float(parameters.get("balance", 0.0)),
                    float(packed_mode),
                ),
            )
        if type_id == "noise.ridged":
            return self._pack_param_groups(
                context,
                (float(parameters.get("scale", 4.0)), float(parameters.get("octaves", 6)), float(parameters.get("lacunarity", 2.0)), float(parameters.get("gain", 0.5))),
                (float(parameters.get("seed", 1)), float(parameters.get("evolution", 0.0)), float(parameters.get("loop_cycles", 1.0)), float(parameters.get("disorder", 0.15))),
                (float(parameters.get("disorder_scale", 3.0)), float(parameters.get("ridge_offset", 1.0)), float(parameters.get("ridge_sharpness", 2.2)), float(parameters.get("octave_weight", 2.0))),
                (float(parameters.get("valley_width", 0.35)), float(parameters.get("contrast", 1.15)), float(parameters.get("balance", -0.08)), flag(parameters.get("invert", False))),
            )
        if type_id == "noise.billow":
            return self._pack_param_groups(
                context,
                (float(parameters.get("scale", 3.0)), float(parameters.get("octaves", 5)), float(parameters.get("lacunarity", 1.85)), float(parameters.get("gain", 0.42))),
                (float(parameters.get("seed", 1)), float(parameters.get("evolution", 0.0)), float(parameters.get("loop_cycles", 1.0)), float(parameters.get("disorder", 0.1))),
                (float(parameters.get("disorder_scale", 2.0)), float(parameters.get("puffiness", 2.0)), float(parameters.get("softness", 0.55)), float(parameters.get("detail", 0.35))),
                (float(parameters.get("contrast", 0.9)), float(parameters.get("balance", -0.08)), flag(parameters.get("invert", False)), 0.0),
            )
        if type_id == "noise.turbulence":
            return self._pack_param_groups(
                context,
                (float(parameters.get("scale", 5.0)), float(parameters.get("octaves", 5)), float(parameters.get("lacunarity", 2.0)), float(parameters.get("gain", 0.5))),
                (float(parameters.get("seed", 1)), float(parameters.get("evolution", 0.0)), float(parameters.get("loop_cycles", 1.0)), float(parameters.get("warp_strength", 1.5))),
                (float(parameters.get("warp_scale", 2.0)), float(parameters.get("warp_octaves", 3)), float(parameters.get("flow_direction", 0.0)), float(parameters.get("directional_bias", 0.65))),
                (float(parameters.get("fold_sharpness", 0.68)), float(parameters.get("contrast", 1.15)), float(parameters.get("balance", -0.05)), flag(parameters.get("invert", False))),
            )
        if type_id == "noise.simplex":
            return self._pack_params(
                context,
                (
                    float(parameters.get("scale", 6.0)),
                    float(parameters.get("seed", 1)),
                    float(parameters.get("evolution", 0.0)),
                    float(parameters.get("loop_cycles", 1.0)),
                ),
                (
                    float(parameters.get("contrast", 1.0)),
                    float(parameters.get("balance", 0.0)),
                    flag(parameters.get("invert", False)),
                    0.0,
                ),
            )
        if type_id == "noise.white":
            return self._pack_params(
                context,
                (float(parameters.get("scale", 256.0)), float(parameters.get("seed", 1)), 0.5, 0.15),
                (float(parameters.get("evolution", 0.0)), float(parameters.get("loop_frames", 4)), float(parameters.get("contrast", 1.0)), float(parameters.get("balance", 0.0))),
                (0.0, flag(parameters.get("invert", False)), 0.0, 0.0),
            )
        if type_id == "noise.gaussian":
            return self._pack_param_groups(
                context,
                (float(parameters.get("scale", 16.0)), float(parameters.get("seed", 1)), float(parameters.get("mean", 0.5)), float(parameters.get("deviation", 0.18))),
                (float(parameters.get("smoothness", 1.0)), float(parameters.get("detail", 0.4)), float(parameters.get("disorder", 0.45)), float(parameters.get("disorder_scale", 4.0))),
                (float(parameters.get("evolution", 0.0)), float(parameters.get("loop_cycles", 1.0)), float(parameters.get("contrast", 1.0)), float(parameters.get("balance", 0.0))),
                (flag(parameters.get("invert", False)), 0.0, 0.0, 0.0),
            )
        if type_id == "noise.worley":
            metrics = {"Euclidean": 0, "Manhattan": 1, "Chebyshev": 2, "Minkowski": 3}
            outputs = {"F1": 0, "F2": 1, "F2 - F1": 2}
            return self._pack_params(
                context,
                (
                    float(parameters.get("scale", 8.0)),
                    float(parameters.get("seed", 1)),
                    float(parameters.get("points_per_cell", 2)),
                    float(parameters.get("jitter", 1.0)),
                ),
                (
                    float(parameters.get("evolution", 0.0)),
                    float(parameters.get("loop_cycles", 1.0)),
                    float(metrics.get(str(parameters.get("distance_metric", "Euclidean")), 0)),
                    float(parameters.get("distance_exponent", 2.0)),
                ),
                (
                    float(outputs.get(str(parameters.get("output_mode", "F1")), 0)),
                    float(parameters.get("contrast", 1.0)),
                    float(parameters.get("balance", 0.0)),
                    flag(parameters.get("invert", False)),
                ),
            )
        if type_id == "noise.voronoi_fractal":
            modes = {"Distance": 0, "Edges": 1}
            return self._pack_params(
                context,
                (
                    float(parameters.get("scale", 3.0)),
                    float(parameters.get("octaves", 4)),
                    float(parameters.get("lacunarity", 2.0)),
                    float(parameters.get("gain", 0.5)),
                ),
                (
                    float(parameters.get("seed", 1)),
                    float(parameters.get("jitter", 1.0)),
                    float(parameters.get("evolution", 0.0)),
                    float(parameters.get("loop_cycles", 1.0)),
                ),
                (
                    float(modes.get(str(parameters.get("fractal_mode", "Distance")), 0)),
                    float(parameters.get("contrast", 1.0)),
                    float(parameters.get("balance", 0.0)),
                    flag(parameters.get("invert", False)),
                ),
            )
        if type_id in {
            "noise.clouds_1", "noise.clouds_2", "noise.clouds_3",
            "noise.bnw_spots_1", "noise.bnw_spots_2", "noise.bnw_spots_3",
            "noise.crystal_1", "noise.crystal_2", "noise.fractal_sum",
            "noise.anisotropic", "noise.fibres", "noise.messy_fibres",
            "noise.moisture", "noise.fur",
        }:
            variants = {
                "noise.clouds_1": 0, "noise.clouds_2": 1, "noise.clouds_3": 2,
                "noise.bnw_spots_1": 3, "noise.bnw_spots_2": 4, "noise.bnw_spots_3": 5,
                "noise.crystal_1": 6, "noise.crystal_2": 7, "noise.fractal_sum": 8,
                "noise.anisotropic": 9, "noise.fibres": 10, "noise.messy_fibres": 11,
                "noise.moisture": 12, "noise.fur": 13,
            }
            variant = variants[type_id]
            scale = float(parameters.get("scale", 1.0))
            p3 = [float(parameters.get("disorder_angle", 0.0)), 0.0, 0.0, 0.0]
            p4 = [0.0, 0.0, 0.0, 0.0]
            p6 = [0.0, 0.0, 0.0, 0.0]
            if variant <= 2:
                p3[1] = float(parameters.get("octaves", 5))
                p3[2] = float(parameters.get("roughness", 0.5))
                if variant == 0:
                    p3[3] = float(parameters.get("softness", 0.62))
                elif variant == 1:
                    p3[3] = float(parameters.get("puffiness", 1.8))
                else:
                    p3[3] = float(parameters.get("erosion", 0.46))
                    p4[0] = float(parameters.get("detail", 0.65))
            elif variant in {3, 4, 5}:
                p3[1] = float(parameters.get("roughness", 0.6))
                p3[2] = float(parameters.get("grain", 0.6))
            elif variant == 6:
                legacy_scale = float(parameters.get("scale", 16.0))
                scale = 1.0
                p3 = [
                    float(parameters.get("scale_x", legacy_scale)),
                    float(parameters.get("scale_y", legacy_scale)),
                    0.0,
                    0.0,
                ]
            elif variant == 7:
                p3[1] = float(parameters.get("jitter", 0.85))
                p3[2] = float(parameters.get("facet_sharpness", 1.5))
                p3[3] = float(parameters.get("edge_weight", 0.55))
                p4[0] = float(parameters.get("angle", 90.0))
            elif variant == 8:
                scale = 1.0
                p3[1] = float(parameters.get("roughness", 0.58))
                p3[2] = float(parameters.get("min_level", 0))
                p3[3] = float(parameters.get("max_level", 7))
                p4[0] = float(parameters.get("global_opacity", 1.0))
            elif variant == 9:
                scale = 1.0
                p3 = [
                    float(parameters.get("scale_x", 5)),
                    float(parameters.get("scale_y", 34)),
                    float(parameters.get("smoothness", 1.0)),
                    float(parameters.get("interpolation", 1.0)),
                ]
            elif variant in {10, 11, 13}:
                p3[1] = float(parameters.get("density", 2))
                p3[2] = float(parameters.get("length", 1.0))
                p3[3] = float(parameters.get("width", 0.05))
                p4 = [
                    float(parameters.get("softness", 0.25)),
                    float(parameters.get("angle", 0.0)),
                    float(parameters.get("angle_random", 30.0)),
                    float(parameters.get("luminance_random", 0.5)),
                ]
                if variant == 11:
                    p6 = [
                        float(parameters.get("messiness", 1.15)),
                        float(parameters.get("messiness_scale", 5.0)),
                        float(parameters.get("breakage", 0.38)),
                        0.0,
                    ]
            elif variant == 12:
                p3 = [
                    float(parameters.get("pool_size", 1.0)),
                    float(parameters.get("fine_detail", 0.65)),
                    float(parameters.get("patchiness", 0.72)),
                    0.0,
                ]
            disorder_scale = float(parameters.get("disorder_scale", 3.0))
            disorder_anisotropy = float(parameters.get("disorder_anisotropy", 0.0))
            if variant == 12:
                disorder_scale = max(scale * 0.5, 1.0)
                disorder_anisotropy = 0.0
            return self._pack_param_groups(
                context,
                (float(variant), scale, float(parameters.get("seed", 1)), float(parameters.get("evolution", 0.0))),
                (
                    float(parameters.get("loop_cycles", 1.0)),
                    float(parameters.get("disorder", 0.0)),
                    disorder_scale,
                    disorder_anisotropy,
                ),
                tuple(p3), tuple(p4),
                (
                    float(parameters.get("contrast", 1.0)),
                    float(parameters.get("balance", 0.0)),
                    flag(parameters.get("invert", False)),
                    float(parameters.get("global_opacity", 1.0)),
                ),
                tuple(p6),
            )
        if type_id == "terrain.flow_direction":
            return self._pack_params(context, (float(parameters.get("strength", 1.0)), 0.0, 0.0, 0.0))
        if type_id == "terrain.slope":
            return self._pack_params(context, (
                float(parameters.get("height_scale", 1.0)),
                float(parameters.get("contrast", 1.0)),
                flag(parameters.get("invert", False)),
                0.0,
            ))
        if type_id == "terrain.curvature":
            modes = {"Signed": 0, "Convex": 1, "Concave": 2, "Absolute": 3}
            return self._pack_params(context, (
                float(modes.get(str(parameters.get("mode", "Signed")), 0)),
                float(parameters.get("strength", 4.0)) * resolution_scale(context) ** 2,
                float(parameters.get("contrast", 1.0)),
                flag(parameters.get("invert", False)),
            ))
        if type_id == "terrain.terrace":
            return self._pack_params(
                context,
                (
                    float(parameters.get("steps", 8)),
                    float(parameters.get("offset", 0.0)),
                    float(parameters.get("spacing_variation", 0.18)),
                    float(parameters.get("height_distribution", 0.0)),
                ),
                (
                    float(parameters.get("smoothness", 0.16)),
                    float(parameters.get("plateau_slope", 0.06)),
                    float(parameters.get("strength", 1.0)),
                    float(parameters.get("seed", 1)),
                ),
                (
                    float(parameters.get("boundary_breakup", 0.10)),
                    float(parameters.get("breakup_scale", 4.0)),
                    float(parameters.get("variation_influence", 0.5)),
                    flag(parameters.get("invert_mask", False)),
                ),
            )
        if type_id == "terrain.height_combine":
            modes = {"Add": 0, "Subtract": 1, "Multiply": 2, "Maximum": 3, "Minimum": 4, "Average": 5, "Difference": 6}
            return self._pack_params(context, (
                float(modes.get(str(parameters.get("mode", "Maximum")), 3)),
                float(parameters.get("opacity", 1.0)),
                flag(parameters.get("clamp", True)),
                0.0,
            ))
        if type_id == "terrain.height_blend":
            return self._pack_params(context, (
                float(parameters.get("height_offset", 0.0)),
                float(parameters.get("transition", 0.1)),
                float(parameters.get("bias", 0.0)),
                float(parameters.get("opacity", 1.0)),
            ))
        if type_id in {"filter.flood_fill_random_grayscale", "filter.flood_fill_random_colour"}:
            return self._pack_params(context, (float(parameters.get("seed", 0)), 0.0, 0.0, 0.0))
        if type_id == "filter.flood_fill_to_grayscale":
            return self._pack_params(
                context,
                (
                    float(parameters.get("base_value", 0.5)),
                    float(parameters.get("adjustment", 0.0)),
                    float(parameters.get("random", 0.0)),
                    float(parameters.get("seed", 0)),
                ),
                (flag(parameters.get("_connected_Value Input", False)), 0.0, 0.0, 0.0),
            )
        if type_id == "filter.flood_fill_to_colour":
            colour = tuple(float(value) for value in parse_hex_color(str(parameters.get("base_colour", "#ffffffff"))))
            return self._pack_params(
                context,
                colour,
                (
                    float(parameters.get("luminance_adjustment", 0.0)),
                    float(parameters.get("colour_random", 0.0)),
                    float(parameters.get("seed", 0)),
                    flag(parameters.get("_connected_Colour Input", False)),
                ),
            )
        if type_id == "filter.flood_fill_to_gradient":
            return self._pack_params(
                context,
                (
                    float(parameters.get("angle", 0.0)),
                    float(parameters.get("angle_variation", 0.0)),
                    float(parameters.get("angle_input_multiplier", 0.0)),
                    float(parameters.get("seed", 0)),
                ),
                (
                    float(parameters.get("slope_intensity", 1.0)),
                    float(parameters.get("slope_input_multiplier", 0.0)),
                    float(parameters.get("multiply_bbox_size", 0.0)),
                    float(parameters.get("flat_value", 0.5)),
                ),
                (
                    flag(parameters.get("_connected_Angle Input", False)),
                    flag(parameters.get("_connected_Slope Input", False)),
                    0.0,
                    0.0,
                ),
            )
        if type_id == "filter.flood_fill_to_position":
            return self._pack_params(context)
        if type_id == "filter.flood_fill_to_bbox_size":
            modes = {"Max X/Y": 0, "Min X/Y": 1, "X": 2, "Y": 3, "Area": 4}
            return self._pack_params(context, (float(modes.get(str(parameters.get("output", "Max X/Y")), 0)), 0.0, 0.0, 0.0))
        if type_id == "filter.flood_fill_to_index":
            return self._pack_params(context, (1.0 if str(parameters.get("output", "Normalised")) == "Integer" else 0.0, 0.0, 0.0, 0.0))
        if type_id == "filter.flood_fill_mapper":
            tiling = 1.0 if str(parameters.get("tiling", "No Tiling")) == "H + V Tiling" else 0.0
            return self._pack_param_groups(
                context,
                (
                    tiling,
                    float(parameters.get("scale", 1.0)),
                    float(parameters.get("scale_random", 0.0)),
                    float(parameters.get("scale_map_multiplier", 0.0)),
                ),
                (
                    float(parameters.get("rotation", 0.0)),
                    float(parameters.get("rotation_random", 0.0)),
                    float(parameters.get("rotation_map_multiplier", 0.0)),
                    float(parameters.get("offset_x", 0.0)),
                ),
                (
                    float(parameters.get("offset_y", 0.0)),
                    float(parameters.get("luminance_range", 1.0)),
                    float(parameters.get("luminance_offset", 0.0)),
                    float(parameters.get("background_value", 0.0)),
                ),
                (
                    float(parameters.get("seed", 0)),
                    flag(parameters.get("_connected_Pattern Input", False)),
                    flag(parameters.get("_connected_Scale Map", False)),
                    flag(parameters.get("_connected_Rotation Map", False)),
                ),
            )
        if type_id == "internal.fused_adjustments":
            raw_operations = parameters.get("_fusion_operations", ())
            source = inputs[0] if inputs else None
            precision = source.precision if source is not None else "16-bit"
            quant = (
                2.0 if precision == "8-bit"
                else 1.0 if precision == "16-bit" and source is not None and source.logical_format.channels > 1
                else 0.0
            )
            groups: list[tuple[float, float, float, float]] = [
                (float(min(len(raw_operations), 8)), 0.0, 0.0, 0.0)
            ]
            for raw in list(raw_operations)[:8]:
                values = [float(value) for value in list(raw)[:8]]
                values.extend([0.0] * (8 - len(values)))
                values[7] = quant
                groups.append(tuple(values[0:4]))
                groups.append(tuple(values[4:8]))
            while len(groups) < 17:
                groups.append((0.0, 0.0, 0.0, 0.0))
            return self._pack_param_groups(context, *groups)
        if type_id == "filter.levels":
            return self._pack_params(
                context,
                (
                    float(parameters.get("in_low", parameters.get("black", 0.0))),
                    float(parameters.get("in_high", parameters.get("white", 1.0))),
                    float(parameters.get("in_mid", 0.5)),
                    float(parameters.get("out_low", 0.0)),
                ),
                (
                    float(parameters.get("out_high", 1.0)),
                    flag(parameters.get("intermediary_clamp", True)),
                    0.0,
                    0.0,
                ),
            )
        if type_id == "filter.histogram_range":
            return self._pack_params(context, (
                float(parameters.get("range", 1.0)),
                float(parameters.get("position", 0.5)),
                0.0,
                0.0,
            ))
        if type_id == "filter.histogram_shift":
            return self._pack_params(context, (float(parameters.get("position", 0.0)), 0.0, 0.0, 0.0))
        if type_id == "filter.histogram_scan":
            return self._pack_params(context, (
                float(parameters.get("position", 0.5)),
                float(parameters.get("contrast", 0.5)),
                0.0,
                0.0,
            ))
        if type_id == "filter.histogram_select":
            return self._pack_params(context, (
                float(parameters.get("position", 0.5)),
                float(parameters.get("range", 0.25)),
                float(parameters.get("contrast", 0.5)),
                0.0,
            ))
        if type_id == "filter.brightness":
            return self._pack_params(context, (0.0, float(parameters.get("brightness", 0.0)), 0.0, 0.0))
        if type_id == "filter.contrast":
            return self._pack_params(context, (
                1.0,
                float(parameters.get("contrast", 0.0)),
                float(parameters.get("pivot", 0.5)),
                0.0,
            ))
        if type_id == "filter.exposure":
            return self._pack_params(context, (2.0, float(parameters.get("exposure", 0.0)), 0.0, 0.0))
        if type_id == "filter.gamma":
            return self._pack_params(context, (3.0, float(parameters.get("gamma", 1.0)), 0.0, 0.0))
        if type_id == "filter.posterize":
            return self._pack_params(context, (4.0, float(parameters.get("steps", 8)), 0.0, 0.0))
        if type_id == "filter.clamp":
            return self._pack_params(context, (
                5.0,
                float(parameters.get("minimum", 0.0)),
                float(parameters.get("maximum", 1.0)),
                0.0,
            ))
        if type_id == "filter.hue_shift":
            return self._pack_params(context, (0.0, float(parameters.get("degrees", 0.0)), 0.0, 0.0))
        if type_id == "filter.saturation":
            return self._pack_params(context, (1.0, float(parameters.get("saturation", 1.0)), 0.0, 0.0))
        if type_id == "filter.lightness":
            return self._pack_params(context, (2.0, float(parameters.get("lightness", 0.0)), 0.0, 0.0))
        if type_id == "filter.curve":
            raw = parameters.get("points")
            points: list[tuple[float, float]] = []
            if isinstance(raw, list):
                for item in raw[:8]:
                    if not isinstance(item, Mapping):
                        continue
                    try:
                        x = min(max(float(item.get("x", 0.0)), 0.0), 1.0)
                        y = min(max(float(item.get("y", 0.0)), 0.0), 1.0)
                    except (TypeError, ValueError):
                        continue
                    points.append((x, y))
            if len(points) < 2:
                points = [(0.0, 0.0), (1.0, 1.0)]
            points.sort(key=lambda point: point[0])
            deduplicated: list[tuple[float, float]] = []
            for point in points:
                if deduplicated and abs(point[0] - deduplicated[-1][0]) < 1e-6:
                    deduplicated[-1] = point
                else:
                    deduplicated.append(point)
            points = deduplicated if len(deduplicated) >= 2 else [(0.0, 0.0), (1.0, 1.0)]
            points = points[:8]
            padded = points + [points[-1]] * (8 - len(points))
            groups = []
            for index in range(0, 8, 2):
                groups.append((padded[index][0], padded[index][1], padded[index + 1][0], padded[index + 1][1]))
            return self._pack_param_groups(
                context,
                (float(len(points)), flag(str(parameters.get("interpolation", "Smooth")) == "Smooth"), 0.0, 0.0),
                *groups,
            )
        if type_id == "filter.edge_detect":
            method = 1.0 if str(parameters.get("method", "Scharr")) == "Sobel" else 0.0
            source_kind = str(getattr(inputs[0], "data_kind", parameters.get("_resolved_kind", "grayscale"))) if inputs else str(parameters.get("_resolved_kind", "grayscale"))
            kind_code = {"grayscale": 0.0, "color": 1.0, "vector": 2.0}.get(source_kind, 0.0)
            return self._pack_params(
                context,
                (
                    max(relative_pixels(float(parameters.get("width", 1.0)), context), 1.0),
                    max(float(parameters.get("intensity", 1.0)), 0.0),
                    method,
                    flag(parameters.get("invert", False)),
                ),
                (kind_code, 0.0, 0.0, 0.0),
            )
        if type_id == "filter.fxaa":
            source_kind = str(getattr(inputs[0], "data_kind", parameters.get("_resolved_kind", "grayscale"))) if inputs else str(parameters.get("_resolved_kind", "grayscale"))
            kind_code = {"grayscale": 0.0, "color": 1.0, "vector": 2.0}.get(source_kind, 0.0)
            quality = {"Low": 0.0, "Medium": 1.0, "High": 2.0}.get(str(parameters.get("quality", "Medium")), 1.0)
            return self._pack_params(
                context,
                (
                    kind_code, quality,
                    max(float(parameters.get("edge_threshold", 0.0312)), 0.0),
                    max(float(parameters.get("relative_threshold", 0.125)), 0.0),
                ),
                (
                    min(max(float(parameters.get("subpixel", 0.75)), 0.0), 1.0),
                    flag(parameters.get("preserve_alpha", True)),
                    0.0, 0.0,
                ),
            )
        if type_id == "transform.clone_patch":
            source_kind = (
                str(getattr(inputs[0], "data_kind", parameters.get("_resolved_kind", "grayscale")))
                if inputs else str(parameters.get("_resolved_kind", "grayscale"))
            )
            kind_code = {"grayscale": 0.0, "color": 1.0, "vector": 2.0}.get(source_kind, 0.0)
            has_mask = 1.0 if bool(parameters.get("_has_mask", False)) else 0.0
            filter_code = {"Automatic": 0.0, "Nearest": 1.0, "Bilinear": 2.0, "Bicubic": 3.0}.get(
                str(parameters.get("filtering", "Automatic")), 0.0
            )
            scale = max(float(parameters.get("scale", 1.0)), 1e-4)
            return self._pack_param_groups(
                context,
                (
                    float(parameters.get("source_x", 0.25)),
                    float(parameters.get("source_y", 0.25)),
                    float(parameters.get("target_x", 0.75)),
                    float(parameters.get("target_y", 0.75)),
                ),
                (
                    max(float(parameters.get("radius", 0.12)), 1e-5),
                    min(max(float(parameters.get("feather", 0.35)), 0.0), 1.0),
                    min(max(float(parameters.get("opacity", 1.0)), 0.0), 1.0),
                    scale,
                ),
                (
                    float(parameters.get("rotation", 0.0)),
                    1.0 if str(parameters.get("boundary", "Clamp")) == "Seamless / Wrap" else 0.0,
                    has_mask,
                    kind_code,
                ),
                (filter_code, 1.0 / scale, 1.0 / scale, 0.0),
            )
        if type_id == "transform.perspective":
            source_kind = (
                str(getattr(inputs[0], "data_kind", parameters.get("_resolved_kind", "grayscale")))
                if inputs else str(parameters.get("_resolved_kind", "grayscale"))
            )
            kind_code = {"grayscale": 0.0, "color": 1.0, "vector": 2.0}.get(source_kind, 0.0)
            filter_code = {"Automatic": 0.0, "Nearest": 1.0, "Bilinear": 2.0, "Bicubic": 3.0}.get(
                str(parameters.get("filtering", "Automatic")), 0.0
            )
            matrix = quad_homography(parameters)
            return self._pack_params(
                context,
                (float(matrix[0, 0]), float(matrix[0, 1]), float(matrix[0, 2]), filter_code),
                (float(matrix[1, 0]), float(matrix[1, 1]), float(matrix[1, 2]), kind_code),
                (
                    float(matrix[2, 0]), float(matrix[2, 1]), float(matrix[2, 2]),
                    1.0 if str(parameters.get("outside", "Transparent")) == "Transparent" else 0.0,
                ),
            )
        if type_id == "normal.blend":
            return self._pack_params(
                context,
                (
                    min(max(float(parameters.get("amount", 1.0)), 0.0), 1.0),
                    1.0 if str(parameters.get("normal_format", "OpenGL (+Y)")) == "DirectX (-Y)" else 0.0,
                    0.0, 0.0,
                ),
            )
        if type_id == "normal.combine":
            method = {"Reoriented (RNM)": 0.0, "Whiteout": 1.0, "UDN": 2.0}.get(
                str(parameters.get("method", "Reoriented (RNM)")), 0.0
            )
            return self._pack_params(
                context,
                (
                    method,
                    max(float(parameters.get("base_strength", 1.0)), 0.0),
                    max(float(parameters.get("detail_strength", 1.0)), 0.0),
                    min(max(float(parameters.get("amount", 1.0)), 0.0), 1.0),
                ),
                (
                    1.0 if str(parameters.get("normal_format", "OpenGL (+Y)")) == "DirectX (-Y)" else 0.0,
                    0.0, 0.0, 0.0,
                ),
            )
        if type_id == "normal.normalize":
            return self._pack_params(context, (0.0, 0.0, 0.0, 0.0))
        if type_id == "normal.invert":
            return self._pack_params(
                context,
                (
                    flag(parameters.get("invert_x", False)),
                    flag(parameters.get("invert_y", False)),
                    flag(parameters.get("invert_z", False)),
                    0.0,
                ),
                (
                    1.0 if str(parameters.get("normal_format", "OpenGL (+Y)")) == "DirectX (-Y)" else 0.0,
                    0.0, 0.0, 0.0,
                ),
            )
        if type_id == "normal.vector_rotation":
            return self._pack_params(
                context,
                (
                    float(parameters.get("angle", 0.0)),
                    1.0 if str(parameters.get("normal_format", "OpenGL (+Y)")) == "DirectX (-Y)" else 0.0,
                    0.0, 0.0,
                ),
            )
        if type_id == "filter.directional_lighting":
            return self._pack_params(
                context,
                (
                    float(parameters.get("angle", 45.0)),
                    min(max(float(parameters.get("elevation", 45.0)), 0.0), 90.0),
                    max(float(parameters.get("diffuse_power", 1.0)), 0.01),
                    max(float(parameters.get("diffuse_brightness", 1.0)), 0.0),
                ),
                (
                    max(float(parameters.get("highlight_power", 16.0)), 1.0),
                    max(float(parameters.get("highlight_brightness", 0.0)), 0.0),
                    min(max(float(parameters.get("ambient", 0.0)), 0.0), 1.0),
                    flag(parameters.get("invert", False)),
                ),
                (
                    1.0 if str(parameters.get("normal_format", "OpenGL (+Y)")) == "DirectX (-Y)" else 0.0,
                    0.0, 0.0, 0.0,
                ),
            )
        if type_id == "normal.transform":
            uniform_scale = max(float(parameters.get("scale", 1.0)), 0.01)
            scale_x = max(float(parameters.get("scale_x", 1.0)) * uniform_scale, 0.01)
            scale_y = max(float(parameters.get("scale_y", 1.0)) * uniform_scale, 0.01)
            boundary_text = str(parameters.get("boundary", "Seamless / Wrap"))
            if "tile" in parameters:
                boundary_text = "Seamless / Wrap" if bool(parameters.get("tile")) else "Transparent"
            boundary_code = {
                "Transparent": 0.0, "Clamp": 1.0, "Seamless / Wrap": 2.0, "Mirror": 3.0,
            }.get(boundary_text, 2.0)
            filter_code = {"Automatic": 0.0, "Nearest": 1.0, "Bilinear": 2.0, "Bicubic": 3.0}.get(
                str(parameters.get("filtering", "Automatic")), 0.0
            )
            angle = float(parameters.get("angle", 0.0))
            identity = (
                abs(float(parameters.get("offset_x", 0.0))) <= 1e-12
                and abs(float(parameters.get("offset_y", 0.0))) <= 1e-12
                and abs(scale_x - 1.0) <= 1e-12 and abs(scale_y - 1.0) <= 1e-12
                and abs(math.fmod(angle, 360.0)) <= 1e-12
            )
            footprint_x, footprint_y = affine_pixel_footprint(scale_x, scale_y, angle)
            return self._pack_params(
                context,
                (float(parameters.get("offset_x", 0.0)), float(parameters.get("offset_y", 0.0)), scale_x, scale_y),
                (
                    angle, boundary_code,
                    1.0 if str(parameters.get("normal_format", "OpenGL (+Y)")) == "DirectX (-Y)" else 0.0,
                    filter_code,
                ),
                (footprint_x, footprint_y, flag(identity), 0.0),
            )
        if type_id == "normal.bent":
            requested_samples = min(max(int(parameters.get("samples", 16)), 4), 64)
            ray_count = min(requested_samples, 6) if context.render_mode == "interactive" else requested_samples
            if context.render_mode == "interactive":
                step_count = 8
            elif ray_count <= 8:
                step_count = 10
            elif ray_count <= 16:
                step_count = 14
            elif ray_count <= 32:
                step_count = 18
            else:
                step_count = 22
            maximum_distance = min(max(float(parameters.get("maximum_distance", 0.15)), 0.0), 1.0)
            maximum_distance_pixels = (
                max(maximum_distance * min(context.width, context.height), 1.0)
                if maximum_distance > 1e-8 else 0.0
            )
            distribution = {
                "Uniform": 0.0, "Cosine Weighted": 1.0, "Horizon Weighted": 2.0,
            }.get(str(parameters.get("distribution", "Cosine Weighted")), 1.0)
            return self._pack_params(
                context,
                (
                    max(float(parameters.get("height_scale", 1.0)), 0.0),
                    maximum_distance_pixels,
                    float(ray_count),
                    min(max(float(parameters.get("spread_angle", 1.0)), 0.0), 1.0),
                ),
                (
                    distribution, float(step_count),
                    1.0 if str(parameters.get("boundary", "Seamless / Wrap")) == "Seamless / Wrap" else 0.0,
                    1.0 if str(parameters.get("normal_format", "OpenGL (+Y)")) == "DirectX (-Y)" else 0.0,
                ),
            )
        if type_id == "filter.rt_shadows":
            requested_samples = min(max(int(parameters.get("samples", 8)), 1), 32)
            sample_count = min(requested_samples, 4) if context.render_mode == "interactive" else requested_samples
            step_count = 12 if context.render_mode == "interactive" else (20 if sample_count <= 8 else 28)
            maximum_distance = min(max(float(parameters.get("maximum_distance", 0.25)), 0.0), 1.0)
            maximum_distance_pixels = (
                max(maximum_distance * min(context.width, context.height), 1.0)
                if maximum_distance > 1e-8 else 0.0
            )
            return self._pack_params(
                context,
                (
                    max(float(parameters.get("height_scale", 1.0)), 0.0),
                    float(parameters.get("angle", 45.0)),
                    min(max(float(parameters.get("elevation", 35.0)), 0.1), 89.9),
                    maximum_distance_pixels,
                ),
                (
                    min(max(float(parameters.get("softness", 0.15)), 0.0), 1.0),
                    float(sample_count), float(step_count),
                    max(float(parameters.get("bias", 0.001)), 0.0),
                ),
                (
                    1.0 if str(parameters.get("boundary", "Seamless / Wrap")) == "Seamless / Wrap" else 0.0,
                    min(max(float(parameters.get("strength", 1.0)), 0.0), 1.0),
                    flag(parameters.get("invert", False)), 0.0,
                ),
            )
        if type_id == "filter.threshold":
            return self._pack_params(context, (
                float(parameters.get("threshold", 0.5)),
                float(parameters.get("softness", 0.0)),
                scalar(0),
                0.0,
            ))
        if type_id in {"filter.curvature", "filter.curvature_sobel"}:
            return self._pack_params(context, (
                float(parameters.get("intensity", 1.0)),
                1.0 if str(parameters.get("normal_format", "OpenGL (+Y)")) == "DirectX (-Y)" else 0.0,
                float(max(int(round(resolution_scale(context))), 1)),
                0.0,
            ))
        if type_id == "filter.curvature_smooth":
            outputs = {"Curvature": 0.0, "Convexity": 1.0, "Concavity": 2.0}
            scale = resolution_scale(context)
            return self._pack_params(
                context,
                (
                    1.0 if str(parameters.get("normal_format", "OpenGL (+Y)")) == "DirectX (-Y)" else 0.0,
                    outputs.get(str(parameters.get("preview_output", "Curvature")), 0.0),
                    float(max(int(round(scale)), 1)),
                    float(max(int(round(2.0 * scale)), 1)),
                ),
                (float(max(int(round(4.0 * scale)), 1)), 0.0, 0.0, 0.0),
            )
        if type_id == "filter.ambient_occlusion_hbao":
            quality_text = str(parameters.get("quality", "8 Samples"))
            direction_count = 16 if quality_text.startswith("16") else (8 if quality_text.startswith("8") else 4)
            radial_steps = {4: 6, 8: 7, 16: 8}[direction_count]
            if context.render_mode == "interactive":
                direction_count = min(direction_count, 4)
                radial_steps = 3
            authored_radius = max(float(parameters.get("radius", 0.15)), 0.0)
            radius_pixels = (
                max(authored_radius * 0.5 * min(context.width, context.height), 1.0)
                if authored_radius > 1e-8
                else 0.0
            )
            return self._pack_params(
                context,
                (
                    max(float(parameters.get("height_depth", 0.10)), 0.0),
                    radius_pixels,
                    float(direction_count),
                    max(float(parameters.get("contrast", 1.0)), 0.0),
                ),
                (
                    flag(parameters.get("invert", False)),
                    1.0 if str(parameters.get("boundary", "Seamless / Wrap")) == "Seamless / Wrap" else 0.0,
                    float(radial_steps),
                    0.0,
                ),
            )
        if type_id == "filter.ambient_occlusion_rtao":
            requested_samples = min(max(int(parameters.get("samples", 16)), 4), 64)
            ray_count = min(requested_samples, 6) if context.render_mode == "interactive" else requested_samples
            if context.render_mode == "interactive":
                step_count = 8
            elif ray_count <= 8:
                step_count = 10
            elif ray_count <= 16:
                step_count = 14
            elif ray_count <= 32:
                step_count = 18
            else:
                step_count = 22
            maximum_distance = min(max(float(parameters.get("maximum_distance", 0.15)), 0.0), 1.0)
            maximum_distance_pixels = (
                max(maximum_distance * min(context.width, context.height), 1.0)
                if maximum_distance > 1e-8
                else 0.0
            )
            distribution = {
                "Uniform": 0.0,
                "Cosine Weighted": 1.0,
                "Horizon Weighted": 2.0,
            }.get(str(parameters.get("distribution", "Uniform")), 0.0)
            return self._pack_params(
                context,
                (
                    max(float(parameters.get("height_scale", 1.0)), 0.0),
                    maximum_distance_pixels,
                    float(ray_count),
                    min(max(float(parameters.get("spread_angle", 1.0)), 0.0), 1.0),
                ),
                (
                    distribution,
                    float(step_count),
                    1.0 if str(parameters.get("boundary", "Seamless / Wrap")) == "Seamless / Wrap" else 0.0,
                    flag(parameters.get("invert", False)),
                ),
            )
        if type_id == "filter.directional_blur":
            return self._pack_params(context, (
                relative_pixels(float(parameters.get("distance", 16.0)), context),
                float(parameters.get("angle", 0.0)),
                float(min(int(parameters.get("samples", 16)), 8) if context.render_mode == "interactive" else int(parameters.get("samples", 16))),
                0.0,
            ))
        if type_id == "filter.radial_blur":
            return self._pack_params(context, (
                float(parameters.get("amount", 20.0)),
                float(parameters.get("center_x", 0.5)),
                float(parameters.get("center_y", 0.5)),
                float(min(int(parameters.get("samples", 16)), 8) if context.render_mode == "interactive" else int(parameters.get("samples", 16))),
            ))
        if type_id == "filter.zoom_blur":
            return self._pack_params(context, (
                relative_pixels(float(parameters.get("amount", 16.0)), context),
                float(parameters.get("center_x", 0.5)),
                float(parameters.get("center_y", 0.5)),
                float(min(int(parameters.get("samples", 16)), 8) if context.render_mode == "interactive" else int(parameters.get("samples", 16))),
            ))
        if type_id == "filter.anisotropic_blur":
            return self._pack_params(context, (
                relative_pixels(float(parameters.get("intensity", 16.0)), context),
                float(parameters.get("anisotropy", 0.75)),
                float(parameters.get("angle", 0.0)),
                float(min(int(parameters.get("samples", 12)), 8) if context.render_mode == "interactive" else int(parameters.get("samples", 12))),
            ))
        if type_id == "filter.non_uniform_blur_grayscale":
            return self._pack_params(context, (
                relative_pixels(float(parameters.get("radius", 16.0)), context),
                float(min(int(parameters.get("samples", 12)), 6) if context.render_mode == "interactive" else int(parameters.get("samples", 12))),
                0.0,
                0.0,
            ))
        if type_id == "filter.slope_blur_grayscale":
            modes = {"Blur": 0.0, "Min": 1.0, "Max": 2.0}
            return self._pack_params(context, (
                relative_pixels(float(parameters.get("intensity", 8.0)), context),
                float(min(int(parameters.get("samples", 8)), 6) if context.render_mode == "interactive" else int(parameters.get("samples", 8))),
                modes.get(str(parameters.get("mode", "Blur")), 0.0),
                0.0,
            ))
        if type_id == "transform.crop":
            left = min(max(float(parameters.get("left", 0.0)), 0.0), 1.0)
            right = min(max(float(parameters.get("right", 1.0)), 0.0), 1.0)
            top = min(max(float(parameters.get("top", 0.0)), 0.0), 1.0)
            bottom = min(max(float(parameters.get("bottom", 1.0)), 0.0), 1.0)
            if right < left: left, right = right, left
            if bottom < top: top, bottom = bottom, top
            source_kind = str(getattr(inputs[0], "data_kind", parameters.get("_resolved_kind", "grayscale"))) if inputs else str(parameters.get("_resolved_kind", "grayscale"))
            kind_code = {"grayscale": 0.0, "color": 1.0, "vector": 2.0}.get(source_kind, 0.0)
            filter_code = {"Automatic": 0.0, "Nearest": 1.0, "Bilinear": 2.0, "Bicubic": 3.0}.get(
                str(parameters.get("filtering", "Automatic")), 0.0
            )
            identity = left == 0.0 and top == 0.0 and right == 1.0 and bottom == 1.0
            return self._pack_params(
                context, (left, top, right, bottom),
                (filter_code, kind_code, max(right-left, 1e-6), max(bottom-top, 1e-6)),
                (flag(identity), 0.0, 0.0, 0.0),
            )
        if type_id == "transform.basic":
            uniform_scale = max(float(parameters.get("scale", 1.0)), 0.01)
            scale_x = max(float(parameters.get("scale_x", 1.0)) * uniform_scale, 0.01)
            scale_y = max(float(parameters.get("scale_y", 1.0)) * uniform_scale, 0.01)
            source_kind = str(getattr(inputs[0], "data_kind", parameters.get("_resolved_kind", "grayscale"))) if inputs else str(parameters.get("_resolved_kind", "grayscale"))
            kind_code = {"grayscale": 0.0, "color": 1.0, "vector": 2.0}.get(source_kind, 0.0)
            boundary_text = str(parameters.get("boundary", "Seamless / Wrap"))
            if "tile" in parameters:
                boundary_text = "Seamless / Wrap" if bool(parameters.get("tile")) else "Transparent"
            boundary_code = {"Transparent": 0.0, "Clamp": 1.0, "Seamless / Wrap": 2.0, "Mirror": 3.0}.get(
                boundary_text, 2.0
            )
            filter_code = {"Automatic": 0.0, "Nearest": 1.0, "Bilinear": 2.0, "Bicubic": 3.0}.get(
                str(parameters.get("filtering", "Automatic")), 0.0
            )
            angle = float(parameters.get("angle", 0.0))
            identity = (abs(float(parameters.get("offset_x", 0.0))) <= 1e-12 and abs(float(parameters.get("offset_y", 0.0))) <= 1e-12
                        and abs(scale_x-1.0) <= 1e-12 and abs(scale_y-1.0) <= 1e-12
                        and abs(math.fmod(angle, 360.0)) <= 1e-12)
            footprint_x, footprint_y = affine_pixel_footprint(scale_x, scale_y, angle)
            return self._pack_params(
                context,
                (float(parameters.get("offset_x", 0.0)), float(parameters.get("offset_y", 0.0)), scale_x, scale_y),
                (angle, boundary_code, filter_code, kind_code),
                (footprint_x, footprint_y, flag(identity), 0.0),
            )
        if type_id == "transform.safe":
            tiles = min(max(int(parameters.get("tiles", 1)), 1), 16)
            angle = float(parameters.get("angle", 0.0))
            safe_rotation = bool(parameters.get("tile_safe_rotation", True))
            if safe_rotation:
                a, b = _safe_lattice(tiles, -angle)
                footprint = max(math.hypot(a, b), 1.0)
            else:
                radians = math.radians(-angle)
                a = math.cos(radians) * tiles
                b = math.sin(radians) * tiles
                footprint = float(tiles)
            offset_x, offset_y = _safe_transform_offset(parameters, context)
            source_kind = str(getattr(inputs[0], "data_kind", parameters.get("_resolved_kind", "grayscale"))) if inputs else str(parameters.get("_resolved_kind", "grayscale"))
            kind_code = {"grayscale": 0.0, "color": 1.0, "vector": 2.0}.get(source_kind, 0.0)
            filter_code = {"Automatic": 0.0, "Nearest": 1.0, "Bilinear": 2.0, "Bicubic": 3.0}.get(
                str(parameters.get("filtering", "Automatic")), 0.0
            )
            symmetry_code = {"None": 0.0, "X": 1.0, "Y": 2.0, "X + Y": 3.0}.get(str(parameters.get("symmetry", "None")), 0.0)
            mip_factor = float(2 ** min(max(int(parameters.get("mipmap_level", 0)), 0), 10)) if str(parameters.get("mipmap_mode", "Automatic")) == "Manual" else 1.0
            identity = (
                abs(float(a) - 1.0) <= 1e-12 and abs(float(b)) <= 1e-12
                and abs(offset_x) <= 1e-12 and abs(offset_y) <= 1e-12
                and symmetry_code == 0.0 and mip_factor == 1.0
            )
            return self._pack_params(
                context, (float(a), float(b), offset_x, offset_y),
                (filter_code, kind_code, symmetry_code, flag(safe_rotation)),
                (footprint * mip_factor, footprint * mip_factor, flag(identity), 0.0),
            )
        if type_id in {"transform.tile", "transform.offset", "transform.rotate", "transform.scale", "transform.mirror"}:
            source_kind = str(getattr(inputs[0], "data_kind", parameters.get("_resolved_kind", "grayscale"))) if inputs else str(parameters.get("_resolved_kind", "grayscale"))
            kind_code = {"grayscale": 0.0, "color": 1.0, "vector": 2.0}.get(source_kind, 0.0)
            filter_code = {"Automatic": 0.0, "Nearest": 1.0, "Bilinear": 2.0, "Bicubic": 3.0}.get(str(parameters.get("filtering", "Automatic")), 0.0)
            boundary_text = str(parameters.get("boundary", "Seamless / Wrap"))
            if "wrap" in parameters:
                boundary_text = "Seamless / Wrap" if bool(parameters.get("wrap")) else "Transparent"
            boundary_code = {"Transparent": 0.0, "Clamp": 1.0, "Seamless / Wrap": 2.0, "Mirror": 3.0}.get(boundary_text, 2.0)
            footprint_x = 1.0; footprint_y = 1.0
            identity = False
            if type_id == "transform.tile":
                mode = 0.0; value1 = float(parameters.get("tiles_x", 2.0)); value2 = float(parameters.get("tiles_y", 2.0))
                boundary_code = 2.0; footprint_x = max(value1, 1.0); footprint_y = max(value2, 1.0)
                identity = abs(value1 - 1.0) <= 1e-12 and abs(value2 - 1.0) <= 1e-12
            elif type_id == "transform.offset":
                mode = 1.0; value1 = float(parameters.get("offset_x", 0.0)); value2 = float(parameters.get("offset_y", 0.0))
                identity = abs(value1) <= 1e-12 and abs(value2) <= 1e-12
                pixel_dx = value1 * context.width; pixel_dy = value2 * context.height
                if abs(pixel_dx - round(pixel_dx)) <= 1e-7 and abs(pixel_dy - round(pixel_dy)) <= 1e-7:
                    filter_code = 1.0
            elif type_id == "transform.rotate":
                mode = 2.0; value1 = float(parameters.get("angle", 0.0)); value2 = 0.0
                identity = abs(math.fmod(value1, 360.0)) <= 1e-12
            elif type_id == "transform.scale":
                mode = 3.0; value1 = max(float(parameters.get("scale_x", 1.0)), 0.001); value2 = max(float(parameters.get("scale_y", 1.0)), 0.001)
                footprint_x = 1.0 / value1; footprint_y = 1.0 / value2
                identity = abs(value1 - 1.0) <= 1e-12 and abs(value2 - 1.0) <= 1e-12
            else:
                mode = 4.0; value1 = {"Horizontal": 0.0, "Vertical": 1.0, "Both": 2.0}.get(str(parameters.get("axis", "Horizontal")), 0.0); value2 = 0.0
                boundary_code = 1.0; filter_code = 1.0
            return self._pack_params(context, (mode, value1, value2, 0.0), (boundary_code, filter_code, kind_code, 0.0), (footprint_x, footprint_y, flag(identity), 0.0))
        if type_id == "coordinates.uv_gradient":
            return self._pack_params(context)
        if type_id in {"coordinates.cartesian_to_polar", "coordinates.polar_to_cartesian", "org.vfxtexturelab.polar_coordinates"}:
            mode = 0.0 if type_id == "coordinates.cartesian_to_polar" else 1.0
            return self._pack_params(
                context,
                (
                    mode,
                    float(parameters.get("center_x", 0.5)),
                    float(parameters.get("center_y", 0.5)),
                    float(parameters.get("radius_scale", 1.0)),
                ),
                (
                    float(parameters.get("angle_offset", 0.0)),
                    flag(parameters.get("clockwise", True)),
                    flag(parameters.get("wrap", True)),
                    0.0,
                ),
            )
        if type_id in {"distortion.swirl", "distortion.spherize"}:
            is_swirl = type_id == "distortion.swirl"
            return self._pack_params(
                context,
                (
                    0.0 if is_swirl else 1.0,
                    float(parameters.get("angle", 180.0) if is_swirl else parameters.get("amount", 0.5)),
                    float(parameters.get("radius", 0.5)),
                    float(parameters.get("center_x", 0.5)),
                ),
                (float(parameters.get("center_y", 0.5)), flag(parameters.get("wrap", True)), 0.0, 0.0),
            )
        if type_id in {"distortion.vector_warp", "distortion.flow_map"}:
            return self._pack_params(
                context,
                (
                    0.0 if type_id == "distortion.vector_warp" else 1.0,
                    float(parameters.get("strength", 0.1)),
                    float(parameters.get("phase", 0.0)),
                    flag(parameters.get("wrap", True)),
                ),
            )
        if type_id == "org.vfxtexturelab.directional_warp":
            return self._pack_params(
                context,
                (
                    float(parameters.get("strength", 0.08)),
                    float(parameters.get("angle", 0.0)),
                    flag(parameters.get("centered", True)),
                    flag(parameters.get("wrap", True)),
                ),
            )
        if type_id == "math.blend":
            modes = {
                "Replace / Copy": 0,
                "Add": 1,
                "Subtract": 2,
                "Multiply": 3,
                "Divide": 4,
                "Add Sub / Linear Light": 5,
                "Minimum": 6,
                "Maximum": 7,
                "Screen": 8,
                "Overlay": 9,
                "Soft Light": 10,
                "Hard Light": 11,
                "Difference": 12,
                "Exclusion": 13,
                "Colour Dodge": 14,
                "Colour Burn": 15,
                # Compatibility aliases from older graph files.
                "Replace": 0,
            }
            input_kinds = [str(getattr(image, "data_kind", "grayscale")) for image in (inputs or [])]
            foreground_kind = input_kinds[0] if len(input_kinds) > 0 else "grayscale"
            background_kind = input_kinds[1] if len(input_kinds) > 1 else "grayscale"
            output_is_color = 1.0 if "color" in (foreground_kind, background_kind) else 0.0
            return self._pack_params(
                context,
                (
                    float(modes.get(str(parameters.get("mode", "Replace / Copy")), 0)),
                    float(parameters.get("opacity", 1.0)),
                    scalar(0),
                    scalar(1),
                ),
                (
                    1.0 if foreground_kind == "color" else 0.0,
                    1.0 if background_kind == "color" else 0.0,
                    output_is_color,
                    0.0,
                ),
            )
        if type_id == "convert.color_to_grayscale":
            methods = {"Luminance": 0, "Average": 1, "Maximum": 2, "Red": 3, "Green": 4, "Blue": 5}
            return self._pack_params(context, (float(methods.get(str(parameters.get("method", "Luminance")), 0)), 0.0, 0.0, 0.0))
        if type_id == "convert.gradient_map":
            raw = parameters.get("stops")
            stops = raw if isinstance(raw, list) else []
            clean: list[tuple[float, tuple[float, float, float, float]]] = []
            for entry in stops[:8]:
                if not isinstance(entry, Mapping):
                    continue
                try:
                    position = min(max(float(entry.get("position", 0.0)), 0.0), 1.0)
                    colour = tuple(float(value) for value in parse_hex_color(str(entry.get("color", "#ffffffff"))))
                    clean.append((position, colour))
                except Exception:
                    continue
            if not clean:
                clean = [(0.0, (0.0, 0.0, 0.0, 1.0)), (1.0, (1.0, 1.0, 1.0, 1.0))]
            clean.sort(key=lambda item: item[0])
            if len(clean) == 1:
                clean.append((1.0, clean[0][1]))
            clean = clean[:8]
            values = [float(context.width), float(context.height), float(len(clean)), float(scalar(0))]
            values.extend([item[0] for item in clean] + [0.0] * (8 - len(clean)))
            for _position, colour in clean:
                values.extend(colour)
            values.extend([0.0] * ((8 - len(clean)) * 4))
            return struct.pack(f"{len(values)}f", *values)
        if type_id == "convert.height_normal":
            return self._pack_params(context, (
                float(parameters.get("strength", 4.0)) * resolution_scale(context),
                flag(parameters.get("invert_y", False)),
                scalar(0),
                0.0,
            ))
        if type_id == "convert.extract_channel":
            channels = {"Red": 0, "Green": 1, "Blue": 2, "Alpha": 3, "Luminance": 4}
            return self._pack_params(context, (
                float(channels.get(str(parameters.get("channel", "Red")), 0)),
                scalar(0),
                0.0,
                0.0,
            ))
        if type_id == "convert.channel_pack":
            return self._pack_params(context, (scalar(0), scalar(1), scalar(2), scalar(3)))
        if type_id == "animation.flipbook_decode":
            columns, rows = flipbook_grid(parameters)
            selection = flipbook_frame_selection(parameters, context)
            order = 1.0 if str(parameters.get("order", "Left to Right, Top to Bottom")) == "Top to Bottom, Left to Right" else 0.0
            return self._pack_params(
                context,
                (float(columns), float(rows), float(selection.frame_count), float(selection.relative_index)),
                (float(parameters.get("start_frame", 0)), order, 0.0, 0.0),
                (float(parameters.get("padding", 0)), 0.0, scalar(0), 0.0),
            )
        return self._pack_params(context)

    def _package_parameter_block(
        self,
        definition: NodeDefinition,
        parameters: Mapping[str, Any],
        context: RenderContext,
    ) -> bytes:
        spec = definition.gpu_spec
        if spec is None:
            return self._pack_params(context)
        values = [0.0] * 12
        for binding in spec.parameter_bindings:
            value = parameters.get(binding.name)
            if binding.kind == "color":
                colour = parse_hex_color(str(value or "#ffffffff"))
                for index in range(4):
                    values[binding.offset + index] = float(colour[index])
            elif binding.kind == "bool":
                values[binding.offset] = 1.0 if bool(value) else 0.0
            elif binding.kind == "enum":
                try:
                    values[binding.offset] = float(binding.options.index(str(value)))
                except ValueError:
                    values[binding.offset] = 0.0
            else:
                try:
                    values[binding.offset] = float(value)
                except (TypeError, ValueError):
                    values[binding.offset] = 0.0
        return self._pack_params(
            context,
            tuple(values[0:4]),
            tuple(values[4:8]),
            tuple(values[8:12]),
        )

    @staticmethod
    def _pack_params(
        context: RenderContext,
        p1: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
        p2: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
        p3: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
    ) -> bytes:
        # Public ABI v2: p0.xy = resolution, p0.z = seconds, p0.w = normalised time.
        # API v1 shaders remain compatible because they only consumed p0.xy.
        p0 = (
            float(context.width),
            float(context.height),
            float(context.time_seconds),
            float(context.normalised_time),
        )
        return struct.pack("16f", *(p0 + p1 + p2 + p3))

    @staticmethod
    def _pack_param_groups(
        context: RenderContext,
        *groups: tuple[float, float, float, float],
    ) -> bytes:
        """Pack an arbitrary number of aligned vec4 uniform groups.

        Most early shaders use p0-p3. More sophisticated nodes can add p4,
        p5, and beyond without changing the public WGSL parameter ABI.
        """
        p0 = (
            float(context.width),
            float(context.height),
            float(context.time_seconds),
            float(context.normalised_time),
        )
        values: tuple[float, ...] = p0 + tuple(value for group in groups for value in group)
        return struct.pack(f"{len(values)}f", *values)

    @staticmethod
    def _definition_revision(definition: NodeDefinition) -> str:
        package = definition.package
        return package.revision if package is not None else "builtin"

    _INCLUDE_RE = re.compile(r'^\s*//\s*@include\s+[<"]([^>"]+)[>"]\s*$', re.MULTILINE)

    def _expand_shader_includes(
        self, source: str, *, base_dir: Path, seen: set[Path] | None = None
    ) -> str:
        seen = set() if seen is None else seen
        builtin_root = Path(__file__).resolve().parents[2] / "shaders"

        def replacement(match: re.Match[str]) -> str:
            include_name = match.group(1).strip()
            candidate = (base_dir / include_name).resolve()
            if not candidate.is_file():
                candidate = (builtin_root / include_name).resolve()
            if not candidate.is_file():
                raise FileNotFoundError(f"WGSL include not found: {include_name}")
            if candidate in seen:
                raise RuntimeError(f"Recursive WGSL include: {candidate}")
            nested_seen = set(seen)
            nested_seen.add(candidate)
            nested = candidate.read_text(encoding="utf-8")
            return self._expand_shader_includes(nested, base_dir=candidate.parent, seen=nested_seen)

        return self._INCLUDE_RE.sub(replacement, source)

    def _shader_source(self, definition: NodeDefinition) -> tuple[str, str, str]:
        package = definition.package
        if definition.gpu_spec is not None:
            path = Path(definition.gpu_spec.shader_path)
            source = path.read_text(encoding="utf-8")
            source = self._expand_shader_includes(source, base_dir=path.parent, seen={path.resolve()})
            revision = package.revision if package is not None else str(path.stat().st_mtime_ns)
            return source, str(path), revision
        shader_name = self._SHADERS[definition.type_id]
        shader_path = Path(__file__).resolve().parents[2] / "shaders" / shader_name
        source = shader_path.read_text(encoding="utf-8")
        source = self._expand_shader_includes(source, base_dir=shader_path.parent, seen={shader_path.resolve()})
        return source, f"vfx_texture_lab/shaders/{shader_name}", "builtin"

    def _build_pipeline(self, definition: NodeDefinition, physical_format: str):
        assert self.device is not None
        source, source_label, _revision = self._shader_source(definition)
        source = source.replace(
            "texture_storage_2d<rgba32float, write>",
            f"texture_storage_2d<{physical_format}, write>",
        )
        try:
            module = self.device.create_shader_module(
                label=f"VFXTL {definition.type_id} {physical_format}", code=source
            )
            return self.device.create_compute_pipeline(
                label=f"VFXTL pipeline {definition.type_id} {physical_format}",
                layout="auto",
                compute={"module": module, "entry_point": "main"},
            )
        except Exception as exc:
            raise RuntimeError(f"{source_label}\n{type(exc).__name__}: {exc}") from exc

    def _pipeline(self, definition: NodeDefinition, physical_format: str):
        revision = self._definition_revision(definition)
        key = (definition.type_id, physical_format, revision)
        pipeline = self._pipelines.get(key)
        if pipeline is not None:
            return pipeline
        pipeline = self._build_pipeline(definition, physical_format)
        # A successful compile becomes the only active revision for this package.
        for old_key in [candidate for candidate in self._pipelines if candidate[0] == definition.type_id and candidate[1] == physical_format]:
            self._pipelines.pop(old_key, None)
        self._pipelines[key] = pipeline
        return pipeline

    def _dispatch(
        self,
        definition: NodeDefinition,
        inputs: list[GpuImage],
        parameter_bytes: bytes,
        context: RenderContext,
        cache_key: str,
        logical_format: TextureFormat,
    ) -> GpuImage:
        assert self.device is not None and self.queue is not None
        type_id = definition.type_id
        physical_format = self._physical_format(context, logical_format)
        pipeline = self._pipeline(definition, physical_format)
        output = self._new_texture(context, logical_format, cache_key)
        uniform_size = max(64, ((len(parameter_bytes) + 15) // 16) * 16)
        uniform = self.device.create_buffer(
            label=f"VFXTL params {type_id}",
            size=uniform_size,
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
        )
        self.queue.write_buffer(uniform, 0, parameter_bytes + bytes(uniform_size - len(parameter_bytes)))
        entries: list[dict[str, Any]] = [
            {"binding": 0, "resource": {"buffer": uniform, "offset": 0, "size": uniform_size}}
        ]
        for index, image in enumerate(inputs, start=1):
            entries.append({"binding": index, "resource": image.view})
        entries.append({"binding": len(inputs) + 1, "resource": output.view})
        bind_group = self.device.create_bind_group(
            label=f"VFXTL bindings {type_id}",
            layout=pipeline.get_bind_group_layout(0),
            entries=entries,
        )
        batched = self._batch_encoder is not None
        encoder = self._batch_encoder if batched else self.device.create_command_encoder(label=f"VFXTL command {type_id}")
        compute_pass = encoder.begin_compute_pass(label=f"VFXTL compute {type_id}")
        compute_pass.set_pipeline(pipeline)
        compute_pass.set_bind_group(0, bind_group)
        compute_pass.dispatch_workgroups(math.ceil(context.width / 8), math.ceil(context.height / 8), 1)
        compute_pass.end()
        if batched:
            self._batch_has_commands = True
            for resource in (*inputs, output):
                resource.pin()
            self._batch_keepalive.extend((uniform, bind_group, *inputs, output))
        else:
            self.queue.submit([encoder.finish()])
        return output

    def _new_texture(
        self,
        context: RenderContext,
        logical_format: TextureFormat,
        cache_key: str,
    ) -> GpuImage:
        assert self.device is not None
        texture = self.device.create_texture(
            label=f"VFXTL image {cache_key[:20]}",
            size=(context.width, context.height, 1),
            format=self._physical_format(context, logical_format),
            usage=(
                wgpu.TextureUsage.STORAGE_BINDING
                | wgpu.TextureUsage.TEXTURE_BINDING
                | wgpu.TextureUsage.COPY_SRC
                | wgpu.TextureUsage.COPY_DST
            ),
        )
        return GpuImage(
            texture=texture,
            view=texture.create_view(),
            width=context.width,
            height=context.height,
            logical_format=logical_format,
            cache_key=cache_key,
            physical_format=self._physical_format(context, logical_format),
        )

    @staticmethod
    def _physical_format(context: RenderContext, logical_format: TextureFormat) -> str:
        if logical_format.channels == 1:
            return "r32float"
        if logical_format.channels == 2:
            return "rg32float"
        return "rgba32float" if logical_format is TextureFormat.RGBA32F else "rgba16float"

    def _solid(
        self, context: RenderContext, value: float, logical_format: TextureFormat = TextureFormat.R16F
    ) -> GpuImage:
        key = (context.width, context.height, float(value), self._physical_format(context, logical_format))
        image = self._solid_textures.get(key)
        if image is not None:
            return image
        array = np.full((context.height, context.width, 4), value, dtype=np.float32)
        array[..., 3] = 1.0
        image = self.ensure_gpu(
            CpuImage(
                array, logical_format,
                f"solid:{value}:{logical_format.value}:{context.width}x{context.height}",
                frozenset(), "grayscale", "16-bit"
            ),
            context,
        )
        self._solid_textures[key] = image
        return image

    def _solid_colour(
        self,
        context: RenderContext,
        colour: tuple[float, float, float, float],
        logical_format: TextureFormat = TextureFormat.RGBA16F,
        *,
        data_kind: str = "color",
    ) -> GpuImage:
        rgba = tuple(float(value) for value in colour)
        key = (context.width, context.height, rgba, self._physical_format(context, logical_format), data_kind)
        image = self._colour_textures.get(key)
        if image is not None:
            return image
        array = np.empty((context.height, context.width, 4), dtype=np.float32)
        array[...] = np.asarray(rgba, dtype=np.float32)
        image = self.ensure_gpu(
            CpuImage(
                array,
                logical_format,
                f"solid-colour:{rgba}:{logical_format.value}:{context.width}x{context.height}",
                frozenset(),
                data_kind,
                "16-bit",
            ),
            context,
        )
        image.data_kind = data_kind
        self._colour_textures[key] = image
        return image

    def _blank(self, context: RenderContext, logical_format: TextureFormat = TextureFormat.R16F) -> GpuImage:
        return self._solid(context, 0.0, logical_format)

    def _white(self, context: RenderContext, logical_format: TextureFormat = TextureFormat.R16F) -> GpuImage:
        return self._solid(context, 1.0, logical_format)

    def ensure_gpu(self, image: ImageResource, context: RenderContext | None = None) -> GpuImage:
        if isinstance(image, GpuImage):
            return image
        if not isinstance(image, CpuImage):
            raise TypeError(f"Unsupported image resource: {type(image)!r}")
        if not self.available:
            raise RuntimeError(self._initialization_error or "WebGPU backend is unavailable")
        with self._lock:
            actual_context = context or RenderContext(image.width, image.height, image.logical_format)
            output = self._new_texture(actual_context, image.logical_format, f"upload:{image.cache_key}")
            output.provenance = image.provenance
            output.data_kind = image.data_kind
            output.precision = image.precision
            channels, dtype, bytes_per_pixel = self._physical_layout(output.physical_format)
            if channels == 1:
                data = np.ascontiguousarray(image.array[..., 0], dtype=dtype)
            else:
                data = np.ascontiguousarray(image.array[..., :channels], dtype=dtype)
            assert self.queue is not None
            self.queue.write_texture(
                {"texture": output.texture, "mip_level": 0, "origin": (0, 0, 0)},
                data,
                {"offset": 0, "bytes_per_row": image.width * bytes_per_pixel, "rows_per_image": image.height},
                (image.width, image.height, 1),
            )
            return output

    def prepare_preview_rgba8(
        self,
        image: ImageResource,
        width: int,
        height: int,
        data_kind: str,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> np.ndarray:
        """Downsample and display-convert a graph texture entirely on WebGPU.

        The returned array is already RGBA8 display data. This avoids the old
        full-resolution float readback, NumPy colour transform and second GPU
        upload through Qt for ordinary 2D previews.
        """
        if not self.available:
            raise RuntimeError(self._initialization_error or "WebGPU backend is unavailable")
        source = self.ensure_gpu(image)
        target_width = max(1, int(width))
        target_height = max(1, int(height))
        kind_code = {"color": 0.0, "grayscale": 1.0, "vector": 2.0}.get(str(data_kind), 0.0)
        with self._lock:
            assert self.device is not None and self.queue is not None
            if self._batch_encoder is not None:
                self._flush_batch_locked(restart=self._batch_depth > 0)
            context = RenderContext(target_width, target_height, TextureFormat.RGBA16F)
            definition = NodeDefinition(
                "internal.preview_prepare", "Prepare 2D Preview", "Internal", None,
                inputs=("Image",), hidden=True,
            )
            pipeline = self._pipeline(definition, "rgba8unorm")
            target_key = (target_width, target_height)
            target = self._preview_targets.pop(target_key, None)
            if target is None:
                texture = self.device.create_texture(
                    label="VFXTL prepared 2D preview",
                    size=(target_width, target_height, 1),
                    format="rgba8unorm",
                    usage=wgpu.TextureUsage.STORAGE_BINDING | wgpu.TextureUsage.COPY_SRC,
                )
                output_view = texture.create_view()
                row_bytes = target_width * 4
                aligned_row_bytes = ((row_bytes + 255) // 256) * 256
                read_buffer = self.device.create_buffer(
                    label="VFXTL prepared preview readback",
                    size=aligned_row_bytes * target_height,
                    usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ,
                )
                uniform = self.device.create_buffer(
                    label="VFXTL preview parameters",
                    size=64,
                    usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
                )
            else:
                texture, output_view, read_buffer, uniform, aligned_row_bytes = target
                row_bytes = target_width * 4
            self._preview_targets[target_key] = (texture, output_view, read_buffer, uniform, aligned_row_bytes)
            while len(self._preview_targets) > 4:
                _old_key, old_target = next(iter(self._preview_targets.items()))
                self._preview_targets.pop(_old_key, None)
                try:
                    old_target[0].destroy()
                    old_target[2].destroy()
                    old_target[3].destroy()
                except Exception:
                    pass
            parameter_bytes = self._pack_params(
                context,
                (float(source.width), float(source.height), kind_code, 0.0),
            )
            self.queue.write_buffer(uniform, 0, parameter_bytes)
            bind_group = self.device.create_bind_group(
                label="VFXTL preview bindings",
                layout=pipeline.get_bind_group_layout(0),
                entries=[
                    {"binding": 0, "resource": {"buffer": uniform, "offset": 0, "size": 64}},
                    {"binding": 1, "resource": source.view},
                    {"binding": 2, "resource": output_view},
                ],
            )
            encoder = self.device.create_command_encoder(label="VFXTL preview command")
            compute_pass = encoder.begin_compute_pass(label="VFXTL preview prepare pass")
            compute_pass.set_pipeline(pipeline)
            compute_pass.set_bind_group(0, bind_group)
            compute_pass.dispatch_workgroups(math.ceil(target_width / 8), math.ceil(target_height / 8), 1)
            compute_pass.end()
            encoder.copy_texture_to_buffer(
                {"texture": texture, "mip_level": 0, "origin": (0, 0, 0)},
                {
                    "buffer": read_buffer,
                    "offset": 0,
                    "bytes_per_row": aligned_row_bytes,
                    "rows_per_image": target_height,
                },
                (target_width, target_height, 1),
            )
            self.queue.submit([encoder.finish()])
            if cancel_check is not None and cancel_check():
                raise BackendCancelled("2D preview preparation was cancelled")
            read_buffer.map_sync(wgpu.MapMode.READ)
            mapped = memoryview(read_buffer.read_mapped())
            if aligned_row_bytes == row_bytes:
                result = np.frombuffer(mapped, dtype=np.uint8, count=row_bytes * target_height).reshape(
                    target_height, target_width, 4
                ).copy()
            else:
                result = np.empty((target_height, target_width, 4), dtype=np.uint8)
                flat = result.reshape(target_height, row_bytes)
                for row in range(target_height):
                    start = row * aligned_row_bytes
                    flat[row] = np.frombuffer(mapped[start:start + row_bytes], dtype=np.uint8, count=row_bytes)
            read_buffer.unmap()
            return result

    def to_cpu(self, image: ImageResource) -> CpuImage:
        if isinstance(image, CpuImage):
            return image
        if not isinstance(image, GpuImage):
            raise TypeError(f"Unsupported image resource: {type(image)!r}")
        cached = self._readbacks.get(image.cache_key)
        if cached is not None:
            return cached
        if not self.available:
            raise RuntimeError(self._initialization_error or "WebGPU backend is unavailable")

        with self._lock:
            assert self.device is not None and self.queue is not None
            if self._batch_encoder is not None:
                self._flush_batch_locked(restart=self._batch_depth > 0)
            channels, dtype, bytes_per_pixel = self._physical_layout(image.physical_format)
            row_bytes = image.width * bytes_per_pixel
            aligned_row_bytes = ((row_bytes + 255) // 256) * 256
            read_buffer = self.device.create_buffer(
                label="VFXTL readback",
                size=aligned_row_bytes * image.height,
                usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ,
            )
            encoder = self.device.create_command_encoder(label="VFXTL readback command")
            encoder.copy_texture_to_buffer(
                {"texture": image.texture, "mip_level": 0, "origin": (0, 0, 0)},
                {
                    "buffer": read_buffer,
                    "offset": 0,
                    "bytes_per_row": aligned_row_bytes,
                    "rows_per_image": image.height,
                },
                (image.width, image.height, 1),
            )
            self.queue.submit([encoder.finish()])
            read_buffer.map_sync(wgpu.MapMode.READ)
            mapped = bytes(read_buffer.read_mapped())
            read_buffer.unmap()

            array = np.zeros((image.height, image.width, 4), dtype=np.float32)
            for row in range(image.height):
                start = row * aligned_row_bytes
                stop = start + row_bytes
                values = np.frombuffer(mapped[start:stop], dtype=dtype).astype(np.float32).reshape(image.width, channels)
                if channels == 1:
                    array[row, :, 0:3] = values
                    array[row, :, 3] = 1.0
                elif channels == 2:
                    array[row, :, :2] = values
                    array[row, :, 3] = 1.0
                else:
                    array[row] = values
            result = CpuImage(
                np.clip(array, 0.0, 1.0), image.logical_format, image.cache_key,
                image.provenance, image.data_kind, image.precision
            )
            self._readbacks.put(image.cache_key, result)
            return result

    @staticmethod
    def _physical_layout(physical_format: str) -> tuple[int, type[np.floating], int]:
        if physical_format == "r32float":
            return 1, np.float32, 4
        if physical_format == "rg32float":
            return 2, np.float32, 8
        if physical_format == "rgba16float":
            return 4, np.float16, 8
        return 4, np.float32, 16

    def clear(self) -> None:
        with self._lock:
            self._readbacks.clear()
            self._batch_encoder = None
            self._batch_keepalive = []
            self._batch_depth = 0
            self._batch_has_commands = False
            self._batch_failed = False
            for target in self._preview_targets.values():
                try:
                    target[0].destroy()
                    target[2].destroy()
                    target[3].destroy()
                except Exception:
                    pass
            self._preview_targets.clear()
            for image in self._solid_textures.values():
                image.release()
            self._solid_textures.clear()
            self._pipelines.clear()
