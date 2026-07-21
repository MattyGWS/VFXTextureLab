from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from .base import EvalContext, ImageArray, NodeDefinition, ParameterSpec, StatefulFrame, StatefulNodeSpec
from .image_ops import empty_image, ensure_rgba, grayscale_rgba, luminance
from .registry import NodeRegistry


def _image(inputs: Mapping[str, ImageArray], name: str, context: EvalContext) -> ImageArray:
    return ensure_rgba(inputs.get(name, empty_image(context)), context).astype(np.float32, copy=False)


def init_frame_delay(
    inputs: Mapping[str, ImageArray], _params: Mapping[str, Any], context: EvalContext
) -> StatefulFrame:
    current = np.ascontiguousarray(_image(inputs, "Image", context).copy())
    output = empty_image(context)
    return StatefulFrame({"stored": current}, output)


def step_frame_delay(
    previous: Mapping[str, ImageArray],
    inputs: Mapping[str, ImageArray],
    _params: Mapping[str, Any],
    context: EvalContext,
) -> StatefulFrame:
    output = np.ascontiguousarray(previous.get("stored", empty_image(context)).copy())
    current = np.ascontiguousarray(_image(inputs, "Image", context).copy())
    return StatefulFrame({"stored": current}, output)


def init_temporal_blend(
    inputs: Mapping[str, ImageArray], _params: Mapping[str, Any], context: EvalContext
) -> StatefulFrame:
    current = np.ascontiguousarray(_image(inputs, "Image", context).copy())
    return StatefulFrame({"history": current}, current.copy())


def step_temporal_blend(
    previous: Mapping[str, ImageArray],
    inputs: Mapping[str, ImageArray],
    params: Mapping[str, Any],
    context: EvalContext,
) -> StatefulFrame:
    current = _image(inputs, "Image", context)
    history = ensure_rgba(previous.get("history", current), context)
    persistence = float(np.clip(float(params.get("persistence", 0.85)), 0.0, 0.9999))
    result = current * (1.0 - persistence) + history * persistence
    result[..., 3] = current[..., 3]
    result = np.ascontiguousarray(np.clip(result, 0.0, 1.0), dtype=np.float32)
    return StatefulFrame({"history": result.copy()}, result)


def _procedural_seed(context: EvalContext, seed: int, count: int, radius: float) -> np.ndarray:
    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    yy, xx = np.mgrid[0:context.height, 0:context.width]
    x = (xx + 0.5) / max(context.width, 1)
    y = (yy + 0.5) / max(context.height, 1)
    result = np.zeros((context.height, context.width), dtype=np.float32)
    for _ in range(max(int(count), 1)):
        cx = rng.uniform(0.08, 0.92)
        cy = rng.uniform(0.08, 0.92)
        local_radius = radius * rng.uniform(0.65, 1.35)
        dx = np.minimum(np.abs(x - cx), 1.0 - np.abs(x - cx))
        dy = np.minimum(np.abs(y - cy), 1.0 - np.abs(y - cy))
        result = np.maximum(result, (dx * dx + dy * dy <= local_radius * local_radius).astype(np.float32))
    return result


def init_reaction_diffusion(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> StatefulFrame:
    if "Seed" in inputs:
        seed_mask = np.clip(luminance(_image(inputs, "Seed", context)), 0.0, 1.0)
    else:
        seed_mask = _procedural_seed(
            context,
            int(params.get("seed", 1)),
            int(params.get("seed_count", 12)),
            float(params.get("seed_radius", 0.025)),
        )
    strength = float(np.clip(float(params.get("seed_strength", 1.0)), 0.0, 1.0))
    v = np.clip(seed_mask * strength, 0.0, 1.0).astype(np.float32)
    u = np.clip(1.0 - v, 0.0, 1.0).astype(np.float32)
    state = np.zeros((context.height, context.width, 4), dtype=np.float32)
    state[..., 0] = u
    state[..., 1] = v
    state[..., 3] = 1.0
    return StatefulFrame({"chemicals": state}, grayscale_rgba(v))


def _laplacian(values: np.ndarray) -> np.ndarray:
    cardinal = (
        np.roll(values, 1, axis=0)
        + np.roll(values, -1, axis=0)
        + np.roll(values, 1, axis=1)
        + np.roll(values, -1, axis=1)
    )
    diagonal = (
        np.roll(np.roll(values, 1, axis=0), 1, axis=1)
        + np.roll(np.roll(values, 1, axis=0), -1, axis=1)
        + np.roll(np.roll(values, -1, axis=0), 1, axis=1)
        + np.roll(np.roll(values, -1, axis=0), -1, axis=1)
    )
    return cardinal * 0.2 + diagonal * 0.05 - values


def step_reaction_diffusion(
    previous: Mapping[str, ImageArray],
    inputs: Mapping[str, ImageArray],
    params: Mapping[str, Any],
    context: EvalContext,
) -> StatefulFrame:
    state = ensure_rgba(previous.get("chemicals", empty_image(context)), context).copy()
    u = state[..., 0]
    v = state[..., 1]
    feed = float(params.get("feed", 0.055))
    kill = float(params.get("kill", 0.062))
    diffusion_u = float(params.get("diffusion_u", 0.16))
    diffusion_v = float(params.get("diffusion_v", 0.08))
    dt = float(params.get("time_step", 1.0))
    substeps = min(max(int(params.get("steps_per_frame", 8)), 1), 64)
    injection = None
    if "Seed" in inputs:
        injection = np.clip(luminance(_image(inputs, "Seed", context)), 0.0, 1.0)
        injection_amount = float(np.clip(float(params.get("continuous_seed", 0.0)), 0.0, 1.0))
    else:
        injection_amount = 0.0

    for _ in range(substeps):
        uvv = u * v * v
        u += (diffusion_u * _laplacian(u) - uvv + feed * (1.0 - u)) * dt
        v += (diffusion_v * _laplacian(v) + uvv - (feed + kill) * v) * dt
        if injection is not None and injection_amount > 0.0:
            v = np.maximum(v, injection * injection_amount)
            u = np.minimum(u, 1.0 - injection * injection_amount)
        np.clip(u, 0.0, 1.0, out=u)
        np.clip(v, 0.0, 1.0, out=v)

    state[..., 0] = u
    state[..., 1] = v
    state[..., 2] = 0.0
    state[..., 3] = 1.0
    state = np.ascontiguousarray(state, dtype=np.float32)
    return StatefulFrame({"chemicals": state}, grayscale_rgba(v))


def register_simulation_nodes(registry: NodeRegistry) -> None:
    p = ParameterSpec
    registry.register(
        NodeDefinition(
            "simulation.frame_delay",
            "Frame Delay",
            "Simulation",
            evaluator=None,
            inputs=("Image",),
            description="Output the previous frame's input. Frame zero begins black.",
            accent="#8b63d2",
            tags=("previous frame", "delay", "feedback", "state"),
            input_kinds=(("Image", "image_any"),),
            output_kinds=(("Image", "image_any"),),
            type_policy="preserve_primary",
            primary_input="Image",
            gpu_kernel="simulation_copy.wgsl",
            stateful=StatefulNodeSpec(
                ("stored",), init_frame_delay, step_frame_delay, checkpoint_interval=15, gpu_supported=True
            ),
            uses_time=True,
        )
    )
    registry.register(
        NodeDefinition(
            "simulation.temporal_blend",
            "Temporal Blend",
            "Simulation",
            evaluator=None,
            inputs=("Image",),
            parameters=(
                p(
                    "persistence",
                    "Persistence",
                    "float",
                    0.85,
                    0.0,
                    0.999,
                    0.001,
                    "How strongly the previous result persists into the current frame.",
                    animatable=True,
                ),
            ),
            description="Blend each frame with the previous result to create trails and temporal smoothing.",
            accent="#8b63d2",
            tags=("trail", "feedback", "persistence", "history"),
            input_kinds=(("Image", "image_any"),),
            output_kinds=(("Image", "image_any"),),
            type_policy="preserve_primary",
            primary_input="Image",
            gpu_kernel="simulation_temporal_blend.wgsl",
            stateful=StatefulNodeSpec(
                ("history",), init_temporal_blend, step_temporal_blend, checkpoint_interval=15, gpu_supported=True
            ),
            uses_time=True,
        )
    )
    registry.register(
        NodeDefinition(
            "simulation.reaction_diffusion",
            "Reaction Diffusion",
            "Simulation",
            evaluator=None,
            inputs=("Seed",),
            parameters=(
                p("feed", "Feed", "float", 0.055, 0.0, 0.1, 0.0001),
                p("kill", "Kill", "float", 0.062, 0.0, 0.1, 0.0001),
                p("diffusion_u", "Diffusion U", "float", 0.16, 0.0, 1.0, 0.001),
                p("diffusion_v", "Diffusion V", "float", 0.08, 0.0, 1.0, 0.001),
                p("time_step", "Time Step", "float", 1.0, 0.01, 2.0, 0.01),
                p("steps_per_frame", "Steps per Frame", "int", 8, 1, 64, 1),
                p("seed", "Seed", "int", 1, 0, 2147483647, 1, slider_maximum=1000, fine_step=1, coarse_step=10),
                p("seed_count", "Seed Count", "int", 12, 1, 128, 1),
                p("seed_radius", "Seed Radius", "float", 0.025, 0.001, 0.25, 0.001),
                p("seed_strength", "Seed Strength", "float", 1.0, 0.0, 1.0, 0.01),
                p("continuous_seed", "Continuous Seed", "float", 0.0, 0.0, 1.0, 0.01),
            ),
            description="Gray-Scott reaction diffusion with deterministic checkpoints and optional seed mask.",
            accent="#8b63d2",
            tags=("gray scott", "cells", "organic", "corrosion", "simulation"),
            output_format="r16f",
            input_kinds=(("Seed", "grayscale"),),
            output_kinds=(("Image", "grayscale"),),
            default_image_kind="grayscale",
            gpu_kernel="simulation_reaction_step.wgsl",
            stateful=StatefulNodeSpec(
                ("chemicals",), init_reaction_diffusion, step_reaction_diffusion,
                checkpoint_interval=15, gpu_supported=True,
            ),
            uses_time=True,
        )
    )
