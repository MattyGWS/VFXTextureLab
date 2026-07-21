from __future__ import annotations

from typing import Any, Callable, Mapping

import numpy as np

from ...nodes.base import EvalContext, NodeDefinition
from ...nodes.image_ops import ensure_rgba
from ..formats import RenderContext, TextureFormat
from ..resources import CpuImage, GpuImage, ImageResource
from .base import BackendInfo, RenderBackend


class CpuBackend(RenderBackend):
    key = "cpu"
    name = "CPU (NumPy/Pillow)"

    def __init__(self, gpu_backend=None) -> None:
        self.gpu_backend = gpu_backend

    def info(self) -> BackendInfo:
        return BackendInfo(self.key, self.name, True, "Reference renderer")

    def supports(self, definition: NodeDefinition) -> bool:
        return definition.evaluator is not None

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
    ) -> CpuImage:
        if definition.evaluator is None:
            if definition.missing:
                raise RuntimeError(definition.missing_reason or f"Missing node package: {definition.type_id}")
            raise RuntimeError(
                f"{definition.name} is a WGSL package node and has no CPU reference implementation. "
                "Use Auto or GPU rendering."
            )
        cpu_resources = {name: self.to_cpu(resource) for name, resource in inputs.items()}
        cpu_inputs = {name: resource.array for name, resource in cpu_resources.items()}
        evaluator_parameters: Mapping[str, Any] = parameters
        if definition.type_id in {
            "filter.highpass", "filter.edge_detect", "filter.fxaa",
            "filter.make_it_tile_photo", "filter.lighting_equalisation",
            "transform.basic", "transform.safe", "transform.tile", "transform.offset",
            "transform.rotate", "transform.scale", "transform.mirror", "transform.crop",
            "transform.auto_crop", "transform.clone_patch", "transform.perspective",
            "transform.atlas_splitter",
        }:
            primary_name = definition.primary_input or (definition.inputs[0] if definition.inputs else "Image")
            primary_kind = str(getattr(cpu_resources.get(primary_name), "data_kind", parameters.get("_resolved_kind", definition.default_image_kind)))
            evaluator_parameters = {**parameters, "_resolved_kind": primary_kind}
        if definition.type_id == "math.blend":
            # Colour resources live in the graph's linear-light working space,
            # but artistic blend formulae use display/perceptual channel values.
            # Supply semantic kinds to the CPU reference evaluator without
            # serialising implementation-only parameters into the graph.
            foreground_kind = str(getattr(cpu_resources.get("Foreground"), "data_kind", "grayscale"))
            background_kind = str(getattr(cpu_resources.get("Background"), "data_kind", "grayscale"))
            if "color" in (foreground_kind, background_kind):
                output_kind = "color"
            elif foreground_kind != "grayscale":
                output_kind = foreground_kind
            else:
                output_kind = background_kind
            evaluator_parameters = {
                **parameters,
                "_foreground_kind": foreground_kind,
                "_background_kind": background_kind,
                "_output_kind": output_kind,
            }
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
        del progress_callback
        result = definition.evaluator(cpu_inputs, evaluator_parameters, eval_context)
        logical = logical_format or TextureFormat(getattr(definition, "output_format", TextureFormat.RGBA16F.value))
        rgba = ensure_rgba(result, eval_context).astype(np.float32, copy=False)
        if logical not in (TextureFormat.R32F, TextureFormat.RGBA32F):
            rgba = np.clip(rgba, 0.0, 1.0)
        else:
            rgba = np.nan_to_num(rgba, nan=0.0, posinf=np.finfo(np.float32).max, neginf=np.finfo(np.float32).min)
        provenance = frozenset({"cpu"})
        for resource in inputs.values():
            provenance = provenance | resource.provenance
        return CpuImage(np.ascontiguousarray(rgba), logical, cache_key, provenance)

    def to_cpu(self, image: ImageResource) -> CpuImage:
        if isinstance(image, CpuImage):
            return image
        if isinstance(image, GpuImage) and self.gpu_backend is not None:
            return self.gpu_backend.to_cpu(image)
        raise TypeError(f"Unsupported image resource: {type(image)!r}")
