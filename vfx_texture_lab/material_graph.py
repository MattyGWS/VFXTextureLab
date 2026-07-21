from __future__ import annotations

"""Lazy material-graph resolution and channel composition.

Material sockets deliberately remain tiny structural graph values.  This module
resolves one authored channel at a time, evaluates only the image branches that
are required for that channel, and composes Material Blend/Override/Switch
without expanding a material into nine permanent texture wires.
"""

from dataclasses import dataclass, field
import time
from typing import Any, Callable, Mapping

import numpy as np

from .nodes.base import EvalContext
from .nodes.processing import eval_crop
from .nodes.photogrammetry import eval_make_it_tile_photo
from .material import (
    LEGACY_INPUT_ALIASES,
    MATERIAL_DEFAULT_VALUES,
    MATERIAL_INPUTS,
    material_settings,
)

MATERIAL_PRODUCER_TYPES = frozenset(
    {
        "material.pbr",
        "material.blend",
        "material.override",
        "material.switch",
        "material.crop",
        "material.make_it_tile_photo",
    }
)

MATERIAL_CHANNEL_KINDS: dict[str, str] = {
    "Base Colour": "color",
    "Emissive": "color",
    "Normal": "vector",
    "Height": "grayscale",
    "Ambient Occlusion": "grayscale",
    "Metallic": "grayscale",
    "Roughness": "grayscale",
    "Specular Level": "grayscale",
    "Opacity": "grayscale",
}

MATERIAL_REMOVE_PARAMETERS: dict[str, str] = {
    "Base Colour": "remove_base_colour",
    "Emissive": "remove_emissive",
    "Normal": "remove_normal",
    "Height": "remove_height",
    "Ambient Occlusion": "remove_ambient_occlusion",
    "Metallic": "remove_metallic",
    "Roughness": "remove_roughness",
    "Specular Level": "remove_specular_level",
    "Opacity": "remove_opacity",
}


@dataclass(slots=True)
class MaterialOperationTrace:
    node_uid: str
    name: str
    type_id: str
    stage: str = "material channel"
    backend: str = "CPU"
    state: str = "Computed"
    elapsed_ms: float = 0.0
    cache_hit: bool = False
    width: int = 0
    height: int = 0
    precision: str = "16-bit"
    data_kind: str = "grayscale"
    bytes_used: int = 0
    render_mode: str = "preview"
    details: str = ""


@dataclass(slots=True)
class MaterialChannelResult:
    image: np.ndarray
    present: bool
    data_kind: str
    backends: set[str] = field(default_factory=set)
    node_traces: list[Any] = field(default_factory=list)
    cache_hits: int = 0
    finalise_ms: float = 0.0
    gpu_nodes: int = 0
    cpu_nodes: int = 0
    signal_nodes: int = 0
    reachable_nodes: int = 0
    dynamic_nodes: int = 0
    static_nodes: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ResolvedMaterialInfo:
    material_uid: str | None
    name: str
    settings: dict[str, Any]
    warnings: tuple[str, ...] = ()


class MaterialEvaluationSession:
    """Evaluate a material graph lazily for one render context.

    One session can serve all nine 3D/export channels.  Leaf image evaluations,
    masks, switch signals and composed channels are cached within the session,
    so shared material operations are not repeatedly read back.
    """

    def __init__(
        self,
        evaluator: Any,
        snapshot: Any,
        width: int,
        height: int,
        *,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
        node_activity_callback: Callable[[str, bool, int, int, str], None] | None = None,
        precision: Any = None,
        colour_space: str = "Linear",
        time_seconds: float = 0.0,
        frame_number: int = 0,
        frame_position: float | None = None,
        delta_time: float = 1.0 / 30.0,
        duration_seconds: float = 4.0,
        normalised_time: float = 0.0,
        loop_phase: float = 0.0,
        frames_per_second: float = 30.0,
        document_frame_count: int = 120,
        loop_start_frame: int = 0,
        loop_end_frame: int = 119,
        render_mode: str = "preview",
        collect_traces: bool = True,
    ) -> None:
        self.evaluator = evaluator
        self.snapshot = snapshot
        self.width = max(int(width), 1)
        self.height = max(int(height), 1)
        self.cancel_check = cancel_check
        self.progress_callback = progress_callback
        self.node_activity_callback = node_activity_callback
        self.collect_traces = bool(collect_traces)
        self.render_mode = str(render_mode or "preview")
        self.eval_kwargs = {
            "cancel_check": cancel_check,
            "progress_callback": progress_callback,
            "node_activity_callback": node_activity_callback,
            "colour_space": colour_space,
            "time_seconds": time_seconds,
            "frame_number": frame_number,
            "frame_position": frame_position,
            "delta_time": delta_time,
            "duration_seconds": duration_seconds,
            "normalised_time": normalised_time,
            "loop_phase": loop_phase,
            "frames_per_second": frames_per_second,
            "document_frame_count": document_frame_count,
            "loop_start_frame": loop_start_frame,
            "loop_end_frame": loop_end_frame,
            "render_mode": self.render_mode,
            "collect_traces": self.collect_traces,
        }
        if precision is not None:
            self.eval_kwargs["precision"] = precision

        self._channel_cache: dict[tuple[str, str], MaterialChannelResult] = {}
        self._image_cache: dict[tuple[str, str], MaterialChannelResult] = {}
        self._signal_cache: dict[tuple[str, str], float] = {}
        self._settings_cache: dict[str, ResolvedMaterialInfo] = {}
        self._channel_stack: set[tuple[str, str]] = set()
        self._settings_stack: set[str] = set()

    def _cancelled(self) -> bool:
        return bool(self.cancel_check and self.cancel_check())

    def _check_cancelled(self) -> None:
        if self._cancelled():
            from .engine.evaluator import EvaluationCancelled

            raise EvaluationCancelled()

    def _emit_activity(
        self,
        uid: str,
        active: bool,
        message: str = "",
        current: int = 0,
        target: int = 0,
    ) -> None:
        if self.node_activity_callback is None:
            return
        try:
            self.node_activity_callback(uid, active, current, target, message)
        except Exception:
            return

    @staticmethod
    def _source(snapshot: Any, uid: str, input_name: str) -> tuple[str, str] | None:
        source = snapshot.inputs.get((uid, input_name))
        if source is None:
            return None
        return str(source[0]), str(source[1] or "Image")

    def resolve_material_uid(self, uid: str | None) -> str | None:
        """Follow texture-set and portal wrappers to a material-producing node."""
        current = str(uid or "")
        visited: set[str] = set()
        while current:
            if current in visited:
                return None
            visited.add(current)
            node = self.snapshot.nodes.get(current)
            if node is None:
                return None
            type_id = node.definition.type_id
            if type_id in MATERIAL_PRODUCER_TYPES:
                return current
            if type_id == "output.texture_set":
                source = self._source(self.snapshot, current, "Material")
            elif type_id in {"graph.send", "graph.receive"}:
                source = self._source(self.snapshot, current, "Input")
            elif type_id == "material.channels":
                source = self._source(self.snapshot, current, "Material")
            else:
                return None
            if source is None:
                return None
            current = source[0]
        return None

    def material_input_uid(self, owner_uid: str, input_name: str) -> str | None:
        source = self._source(self.snapshot, owner_uid, input_name)
        return self.resolve_material_uid(source[0]) if source is not None else None

    def _default_image(self, channel: str) -> np.ndarray:
        value = np.asarray(MATERIAL_DEFAULT_VALUES[channel], dtype=np.float32)
        image = np.empty((self.height, self.width, 4), dtype=np.float32)
        image[...] = value
        return image

    @staticmethod
    def _copy_result(result: MaterialChannelResult) -> MaterialChannelResult:
        return MaterialChannelResult(
            image=result.image,
            present=result.present,
            data_kind=result.data_kind,
            backends=set(result.backends),
            node_traces=list(result.node_traces),
            cache_hits=result.cache_hits,
            finalise_ms=result.finalise_ms,
            gpu_nodes=result.gpu_nodes,
            cpu_nodes=result.cpu_nodes,
            signal_nodes=result.signal_nodes,
            reachable_nodes=result.reachable_nodes,
            dynamic_nodes=result.dynamic_nodes,
            static_nodes=result.static_nodes,
            warnings=list(result.warnings),
        )

    @staticmethod
    def _merge_stats(*results: MaterialChannelResult) -> dict[str, Any]:
        backends: set[str] = {"CPU"}
        traces: list[Any] = []
        cache_hits = finalise_ms = gpu_nodes = cpu_nodes = signal_nodes = reachable_nodes = 0
        dynamic_nodes = static_nodes = 0
        warnings: list[str] = []
        trace_keys: set[tuple[str, str, str]] = set()
        for result in results:
            backends.update(result.backends)
            cache_hits += int(result.cache_hits)
            finalise_ms += float(result.finalise_ms)
            gpu_nodes += int(result.gpu_nodes)
            cpu_nodes += int(result.cpu_nodes)
            signal_nodes += int(result.signal_nodes)
            reachable_nodes += int(result.reachable_nodes)
            dynamic_nodes += int(result.dynamic_nodes)
            static_nodes += int(result.static_nodes)
            warnings.extend(result.warnings)
            for trace in result.node_traces:
                key = (
                    str(getattr(trace, "node_uid", "")),
                    str(getattr(trace, "stage", "node")),
                    str(getattr(trace, "name", "")),
                )
                if key not in trace_keys:
                    trace_keys.add(key)
                    traces.append(trace)
        return {
            "backends": backends,
            "node_traces": traces,
            "cache_hits": cache_hits,
            "finalise_ms": finalise_ms,
            "gpu_nodes": gpu_nodes,
            "cpu_nodes": cpu_nodes,
            "signal_nodes": signal_nodes,
            "reachable_nodes": reachable_nodes,
            "dynamic_nodes": dynamic_nodes,
            "static_nodes": static_nodes,
            "warnings": warnings,
        }

    def _evaluate_image_reference(
        self,
        source_ref: tuple[str, str],
        *,
        label: str,
        owner_uid: str | None = None,
    ) -> MaterialChannelResult:
        key = (str(source_ref[0]), str(source_ref[1] or "Image"))
        cached = self._image_cache.get(key)
        if cached is not None:
            copied = self._copy_result(cached)
            copied.cache_hits += 1
            return copied
        self._check_cancelled()
        if owner_uid:
            self._emit_activity(owner_uid, True, f"Material — evaluating {label}")
        source_node = self.snapshot.nodes.get(key[0])
        uniform_source = bool(
            self.render_mode == "preview_3d"
            and source_node is not None
            and source_node.definition.type_id in {"generator.constant", "generator.color"}
        )
        evaluation_width = 1 if uniform_source else self.width
        evaluation_height = 1 if uniform_source else self.height
        try:
            result = self.evaluator.evaluate_snapshot(
                self.snapshot,
                key[0],
                evaluation_width,
                evaluation_height,
                output_name=key[1],
                **self.eval_kwargs,
            )
        finally:
            if owner_uid:
                self._emit_activity(owner_uid, False, "")
        if result.error:
            raise RuntimeError(f"{label}: {result.error}")
        if result.image is None:
            raise RuntimeError(f"{label}: no image was produced")
        image = np.ascontiguousarray(result.image, dtype=np.float32)
        evaluated = MaterialChannelResult(
            image=image,
            present=True,
            data_kind=str(result.data_kind or "grayscale"),
            backends={str(result.backend or "CPU")},
            node_traces=list(tuple(result.node_traces or ())),
            cache_hits=int(result.cache_hits),
            finalise_ms=float(result.finalise_ms),
            gpu_nodes=int(result.gpu_nodes),
            cpu_nodes=int(result.cpu_nodes),
            signal_nodes=int(result.signal_nodes),
            reachable_nodes=int(result.reachable_nodes),
            dynamic_nodes=int(result.dynamic_nodes),
            static_nodes=int(result.static_nodes),
        )
        self._image_cache[key] = evaluated
        return self._copy_result(evaluated)

    def _evaluate_signal_reference(self, source_ref: tuple[str, str], *, label: str) -> float:
        key = (str(source_ref[0]), str(source_ref[1] or "Value"))
        if key in self._signal_cache:
            return self._signal_cache[key]
        self._check_cancelled()
        result = self.evaluator.evaluate_snapshot(
            self.snapshot,
            key[0],
            1,
            1,
            output_name=key[1],
            prepare_display=False,
            **self.eval_kwargs,
        )
        if result.error:
            raise RuntimeError(f"{label}: {result.error}")
        value = result.signal_value
        if isinstance(value, tuple):
            scalar = float(value[0]) if value else 0.0
        elif value is None:
            scalar = float(result.image[0, 0, 0]) if result.image is not None else 0.0
        else:
            scalar = float(value)
        self._signal_cache[key] = scalar
        return scalar

    def _source_for_material_channel(self, uid: str, channel: str) -> tuple[str, str] | None:
        source = self._source(self.snapshot, uid, channel)
        if source is not None:
            return source
        legacy_name = next(
            (legacy for legacy, current in LEGACY_INPUT_ALIASES.items() if current == channel),
            None,
        )
        return self._source(self.snapshot, uid, legacy_name) if legacy_name else None

    def _mask(
        self,
        node: Any,
        *,
        amount: float,
        invert: bool,
        owner_uid: str,
    ) -> tuple[np.ndarray, MaterialChannelResult | None]:
        source = self._source(self.snapshot, owner_uid, "Mask")
        result: MaterialChannelResult | None = None
        if source is None:
            mask = np.ones((self.height, self.width), dtype=np.float32)
        else:
            result = self._evaluate_image_reference(source, label=f"{node.definition.name} Mask", owner_uid=owner_uid)
            mask = np.asarray(result.image[..., 0], dtype=np.float32)
        if invert:
            mask = 1.0 - mask
        mask = np.clip(mask * np.float32(min(max(amount, 0.0), 1.0)), 0.0, 1.0)
        return mask, result

    @staticmethod
    def _smoothstep(edge0: float, edge1: float, value: np.ndarray) -> np.ndarray:
        if edge1 <= edge0 + 1e-8:
            return (value >= edge1).astype(np.float32)
        t = np.clip((value - edge0) / (edge1 - edge0), 0.0, 1.0)
        return t * t * (3.0 - 2.0 * t)

    @staticmethod
    def _normalise_vectors(value: np.ndarray) -> np.ndarray:
        length = np.linalg.norm(value, axis=2, keepdims=True)
        fallback = np.zeros_like(value)
        fallback[..., 2] = 1.0
        return np.where(length > 1e-8, value / np.maximum(length, 1e-8), fallback)

    def _normal_crossfade(self, background: np.ndarray, foreground: np.ndarray, coverage: np.ndarray) -> np.ndarray:
        bg = self._normalise_vectors(background[..., :3] * 2.0 - 1.0)
        fg = self._normalise_vectors(foreground[..., :3] * 2.0 - 1.0)
        mixed = self._normalise_vectors(bg * (1.0 - coverage[..., None]) + fg * coverage[..., None])
        output = np.empty_like(background)
        output[..., :3] = mixed * 0.5 + 0.5
        output[..., 3] = background[..., 3] * (1.0 - coverage) + foreground[..., 3] * coverage
        return output

    def _normal_combine_detail(self, background: np.ndarray, foreground: np.ndarray, coverage: np.ndarray) -> np.ndarray:
        base = self._normalise_vectors(background[..., :3] * 2.0 - 1.0)
        detail = self._normalise_vectors(foreground[..., :3] * 2.0 - 1.0)
        t = base + np.asarray((0.0, 0.0, 1.0), dtype=np.float32)
        u = detail * np.asarray((-1.0, -1.0, 1.0), dtype=np.float32)
        dot = np.sum(t * u, axis=2, keepdims=True)
        combined = t * (dot / np.maximum(t[..., 2:3], 1e-5)) - u
        combined = self._normalise_vectors(combined)
        mixed = self._normalise_vectors(base * (1.0 - coverage[..., None]) + combined * coverage[..., None])
        output = np.empty_like(background)
        output[..., :3] = mixed * 0.5 + 0.5
        output[..., 3] = background[..., 3] * (1.0 - coverage) + foreground[..., 3] * coverage
        return output

    def _compose_channel(
        self,
        channel: str,
        background: np.ndarray,
        foreground: np.ndarray,
        coverage: np.ndarray,
        *,
        normal_mode: str = "Crossfade",
        height_mode: str = "Blend",
        emissive_mode: str = "Blend",
    ) -> np.ndarray:
        coverage = np.clip(np.nan_to_num(coverage, nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)
        if channel == "Normal":
            if normal_mode == "Combine Detail":
                return self._normal_combine_detail(background, foreground, coverage)
            return self._normal_crossfade(background, foreground, coverage)

        if channel == "Height":
            bg = background[..., 0]
            fg = foreground[..., 0]
            if height_mode in {"Add", "Add Foreground Detail"}:
                scalar = bg + (fg - 0.5) * coverage
            elif height_mode == "Maximum":
                scalar = bg * (1.0 - coverage) + np.maximum(bg, fg) * coverage
            elif height_mode == "Minimum":
                scalar = bg * (1.0 - coverage) + np.minimum(bg, fg) * coverage
            else:
                scalar = bg * (1.0 - coverage) + fg * coverage
            scalar = np.clip(scalar, 0.0, 1.0)
            output = np.empty_like(background)
            output[..., 0:3] = scalar[..., None]
            output[..., 3] = 1.0
            return output

        if channel == "Emissive" and emissive_mode == "Add":
            output = background.copy()
            output[..., :3] = np.clip(background[..., :3] + foreground[..., :3] * coverage[..., None], 0.0, 1.0)
            output[..., 3] = background[..., 3] * (1.0 - coverage) + foreground[..., 3] * coverage
            return output

        return np.clip(
            background * (1.0 - coverage[..., None]) + foreground * coverage[..., None],
            0.0,
            1.0,
        ).astype(np.float32)

    def _switch_choice(self, uid: str, node: Any) -> tuple[str, str | None, list[str]]:
        warnings: list[str] = []
        selection_source = self._source(self.snapshot, uid, "Selection")
        if selection_source is None:
            choice = str(node.parameters.get("selected_material", "A"))
        else:
            threshold = float(node.parameters.get("threshold", 0.5))
            value = self._evaluate_signal_reference(selection_source, label="Material Switch Selection")
            choice = "B" if value >= threshold else "A"
        choice = "B" if choice == "B" else "A"
        selected_uid = self.material_input_uid(uid, f"Material {choice}")
        if selected_uid is None:
            warnings.append(f"Material Switch selected Material {choice}, but that input is not connected.")
        return choice, selected_uid, warnings

    def material_info(self, uid: str | None) -> ResolvedMaterialInfo:
        resolved_uid = self.resolve_material_uid(uid)
        if resolved_uid is None:
            return ResolvedMaterialInfo(None, "Material", material_settings({}), ("No material is connected.",))
        cached = self._settings_cache.get(resolved_uid)
        if cached is not None:
            return cached
        if resolved_uid in self._settings_stack:
            return ResolvedMaterialInfo(resolved_uid, "Material", material_settings({}), ("Material graph contains a cycle.",))
        self._settings_stack.add(resolved_uid)
        try:
            node = self.snapshot.nodes[resolved_uid]
            type_id = node.definition.type_id
            warnings: list[str] = []
            if type_id == "material.pbr":
                info = ResolvedMaterialInfo(
                    resolved_uid,
                    str(node.parameters.get("name", "Material")) or "Material",
                    material_settings(node.parameters),
                )
            elif type_id == "material.blend":
                source_name = str(node.parameters.get("settings_source", "Background"))
                selected_uid = self.material_input_uid(resolved_uid, f"{source_name} Material")
                if selected_uid is None:
                    fallback_name = "Foreground" if source_name == "Background" else "Background"
                    selected_uid = self.material_input_uid(resolved_uid, f"{fallback_name} Material")
                    if selected_uid is None:
                        warnings.append("Material Blend has no connected material settings source.")
                inherited = self.material_info(selected_uid)
                warnings.extend(inherited.warnings)
                info = ResolvedMaterialInfo(
                    resolved_uid,
                    str(node.parameters.get("name", "Material Blend")) or "Material Blend",
                    dict(inherited.settings),
                    tuple(dict.fromkeys(warnings)),
                )
            elif type_id == "material.override":
                base_uid = self.material_input_uid(resolved_uid, "Material")
                inherited = self.material_info(base_uid)
                warnings.extend(inherited.warnings)
                settings = (
                    material_settings(node.parameters)
                    if bool(node.parameters.get("override_material_settings", False))
                    else dict(inherited.settings)
                )
                info = ResolvedMaterialInfo(
                    resolved_uid,
                    str(node.parameters.get("name", "Material Override")) or "Material Override",
                    settings,
                    tuple(dict.fromkeys(warnings)),
                )
            elif type_id == "material.switch":
                _choice, selected_uid, switch_warnings = self._switch_choice(resolved_uid, node)
                inherited = self.material_info(selected_uid)
                warnings.extend(switch_warnings)
                warnings.extend(inherited.warnings)
                info = ResolvedMaterialInfo(
                    resolved_uid,
                    inherited.name if selected_uid is not None else "Material Switch",
                    dict(inherited.settings),
                    tuple(dict.fromkeys(warnings)),
                )
            elif type_id in {"material.crop", "material.make_it_tile_photo"}:
                base_uid = self.material_input_uid(resolved_uid, "Material")
                inherited = self.material_info(base_uid)
                warnings.extend(inherited.warnings)
                if base_uid is None:
                    warnings.append(f"{node.definition.name} has no Material connected.")
                info = ResolvedMaterialInfo(
                    resolved_uid,
                    inherited.name if base_uid is not None else node.definition.name,
                    dict(inherited.settings),
                    tuple(dict.fromkeys(warnings)),
                )
            else:
                info = ResolvedMaterialInfo(resolved_uid, node.definition.name, material_settings({}))
            self._settings_cache[resolved_uid] = info
            return info
        finally:
            self._settings_stack.discard(resolved_uid)

    def evaluate_channel(self, uid: str | None, channel: str) -> MaterialChannelResult:
        if channel not in MATERIAL_INPUTS:
            channel = "Base Colour"
        resolved_uid = self.resolve_material_uid(uid)
        if resolved_uid is None:
            return MaterialChannelResult(
                self._default_image(channel),
                False,
                MATERIAL_CHANNEL_KINDS[channel],
                backends={"Defaults"},
                warnings=["No material is connected."],
            )
        key = (resolved_uid, channel)
        cached = self._channel_cache.get(key)
        if cached is not None:
            copied = self._copy_result(cached)
            copied.cache_hits += 1
            return copied
        if key in self._channel_stack:
            return MaterialChannelResult(
                self._default_image(channel),
                False,
                MATERIAL_CHANNEL_KINDS[channel],
                backends={"Defaults"},
                warnings=[f"Material channel cycle detected while resolving {channel}."],
            )
        self._channel_stack.add(key)
        try:
            node = self.snapshot.nodes[resolved_uid]
            type_id = node.definition.type_id
            if type_id == "material.pbr":
                result = self._evaluate_pbr(resolved_uid, node, channel)
            elif type_id == "material.blend":
                result = self._evaluate_blend(resolved_uid, node, channel)
            elif type_id == "material.override":
                result = self._evaluate_override(resolved_uid, node, channel)
            elif type_id == "material.switch":
                result = self._evaluate_switch(resolved_uid, node, channel)
            elif type_id == "material.crop":
                result = self._evaluate_material_filter(resolved_uid, node, channel, eval_crop, "cropped")
            elif type_id == "material.make_it_tile_photo":
                result = self._evaluate_material_filter(
                    resolved_uid, node, channel, eval_make_it_tile_photo, "made seamless"
                )
            else:
                result = MaterialChannelResult(
                    self._default_image(channel), False, MATERIAL_CHANNEL_KINDS[channel], backends={"Defaults"}
                )
            result.image = np.ascontiguousarray(
                np.clip(np.nan_to_num(result.image, nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0),
                dtype=np.float32,
            )
            self._channel_cache[key] = result
            return self._copy_result(result)
        finally:
            self._channel_stack.discard(key)

    def _evaluate_material_filter(
        self,
        uid: str,
        node: Any,
        channel: str,
        evaluator: Callable[[Mapping[str, np.ndarray], Mapping[str, Any], EvalContext], np.ndarray],
        action: str,
    ) -> MaterialChannelResult:
        base_uid = self.material_input_uid(uid, "Material")
        base = self.evaluate_channel(base_uid, channel)
        if not base.present:
            if base_uid is None:
                base.warnings.append(f"{node.definition.name} has no Material connected.")
            return base
        started = time.perf_counter()
        self._emit_activity(uid, True, f"Material — {action} {channel}")
        try:
            eval_context = EvalContext(
                width=self.width,
                height=self.height,
                render_mode=self.render_mode,
            )
            parameters = {**node.parameters, "_resolved_kind": MATERIAL_CHANNEL_KINDS[channel]}
            output = evaluator({"Image": base.image}, parameters, eval_context)
        finally:
            self._emit_activity(uid, False, "")
        output = np.ascontiguousarray(output, dtype=np.float32)
        stats = self._merge_stats(base)
        elapsed = (time.perf_counter() - started) * 1000.0
        if self.collect_traces:
            stats["node_traces"].append(MaterialOperationTrace(
                uid,
                f"{node.definition.name} · {channel}",
                node.definition.type_id,
                elapsed_ms=elapsed,
                width=self.width,
                height=self.height,
                data_kind=MATERIAL_CHANNEL_KINDS[channel],
                bytes_used=int(output.nbytes),
                render_mode=self.render_mode,
                details=f"The requested {channel} channel was {action}; unrelated Material channels were not evaluated.",
            ))
        return MaterialChannelResult(
            output, True, MATERIAL_CHANNEL_KINDS[channel], **stats
        )

    def _evaluate_pbr(self, uid: str, node: Any, channel: str) -> MaterialChannelResult:
        source = self._source_for_material_channel(uid, channel)
        if source is None:
            return MaterialChannelResult(
                self._default_image(channel), False, MATERIAL_CHANNEL_KINDS[channel], backends={"Defaults"}
            )
        result = self._evaluate_image_reference(source, label=f"{node.definition.name} · {channel}", owner_uid=uid)
        result.present = True
        result.data_kind = MATERIAL_CHANNEL_KINDS[channel]
        return result

    def _evaluate_blend(self, uid: str, node: Any, channel: str) -> MaterialChannelResult:
        started = time.perf_counter()
        background_uid = self.material_input_uid(uid, "Background Material")
        foreground_uid = self.material_input_uid(uid, "Foreground Material")
        background = self.evaluate_channel(background_uid, channel)
        foreground = self.evaluate_channel(foreground_uid, channel)

        if not foreground.present:
            result = self._copy_result(background)
            if foreground_uid is None:
                result.warnings.append("Material Blend has no Foreground Material connected.")
            return result
        if not background.present:
            background = MaterialChannelResult(
                self._default_image(channel), False, MATERIAL_CHANNEL_KINDS[channel], backends={"Defaults"}
            )

        amount = float(node.parameters.get("amount", 1.0))
        invert_mask = bool(node.parameters.get("invert_mask", False))
        coverage, mask_result = self._mask(node, amount=amount, invert=invert_mask, owner_uid=uid)
        dependencies: list[MaterialChannelResult] = [background, foreground]
        if mask_result is not None:
            dependencies.append(mask_result)

        if bool(node.parameters.get("use_foreground_opacity", False)):
            opacity = self.evaluate_channel(foreground_uid, "Opacity")
            dependencies.append(opacity)
            coverage *= np.asarray(opacity.image[..., 0], dtype=np.float32)

        blend_method = str(node.parameters.get("blend_method", "Standard"))
        if blend_method == "Height Aware":
            bg_height = self.evaluate_channel(background_uid, "Height")
            fg_height = self.evaluate_channel(foreground_uid, "Height")
            dependencies.extend((bg_height, fg_height))
            if bg_height.present or fg_height.present:
                influence = float(node.parameters.get("height_influence", 0.5))
                softness = max(float(node.parameters.get("transition_softness", 0.1)), 1e-4)
                bias = float(node.parameters.get("height_bias", 0.0))
                relative = fg_height.image[..., 0] - bg_height.image[..., 0] + bias
                shifted = coverage + relative * influence
                coverage = self._smoothstep(0.5 - softness, 0.5 + softness, shifted)

        output = self._compose_channel(
            channel,
            background.image,
            foreground.image,
            coverage,
            normal_mode=str(node.parameters.get("normal_handling", "Crossfade")),
            height_mode=str(node.parameters.get("height_handling", "Blend")),
            emissive_mode=str(node.parameters.get("emissive_handling", "Blend")),
        )
        stats = self._merge_stats(*dependencies)
        elapsed = (time.perf_counter() - started) * 1000.0
        if self.collect_traces:
            stats["node_traces"].append(MaterialOperationTrace(
                uid,
                f"{node.definition.name} · {channel}",
                node.definition.type_id,
                elapsed_ms=elapsed,
                width=self.width,
                height=self.height,
                data_kind=MATERIAL_CHANNEL_KINDS[channel],
                bytes_used=int(output.nbytes),
                render_mode=self.render_mode,
                details=(
                    f"{blend_method} material composition; only the requested {channel} branch and its coverage dependencies were evaluated."
                ),
            ))
        self._emit_activity(uid, False, "")
        return MaterialChannelResult(
            output,
            background.present or foreground.present,
            MATERIAL_CHANNEL_KINDS[channel],
            **stats,
        )

    def _evaluate_override(self, uid: str, node: Any, channel: str) -> MaterialChannelResult:
        remove_parameter = MATERIAL_REMOVE_PARAMETERS[channel]
        if bool(node.parameters.get(remove_parameter, False)):
            warnings = [f"{channel} was removed by Material Override."]
            if self._source(self.snapshot, uid, channel) is not None:
                warnings.append(f"The connected {channel} override is ignored while Remove {channel} is enabled.")
            return MaterialChannelResult(
                self._default_image(channel),
                False,
                MATERIAL_CHANNEL_KINDS[channel],
                backends={"Defaults"},
                warnings=warnings,
            )

        base_uid = self.material_input_uid(uid, "Material")
        base = self.evaluate_channel(base_uid, channel)
        override_source = self._source(self.snapshot, uid, channel)
        if override_source is None:
            return base

        started = time.perf_counter()
        override = self._evaluate_image_reference(
            override_source,
            label=f"{node.definition.name} · {channel} override",
            owner_uid=uid,
        )
        if not base.present:
            base = MaterialChannelResult(
                self._default_image(channel), False, MATERIAL_CHANNEL_KINDS[channel], backends={"Defaults"}
            )
        coverage, mask_result = self._mask(
            node,
            amount=float(node.parameters.get("amount", 1.0)),
            invert=bool(node.parameters.get("invert_mask", False)),
            owner_uid=uid,
        )
        dependencies: list[MaterialChannelResult] = [base, override]
        if mask_result is not None:
            dependencies.append(mask_result)
        output = self._compose_channel(
            channel,
            base.image,
            override.image,
            coverage,
            normal_mode=str(node.parameters.get("normal_handling", "Replace")),
            height_mode=str(node.parameters.get("height_handling", "Replace")),
            emissive_mode=str(node.parameters.get("emissive_handling", "Replace")),
        )
        # Replace is the user-facing name; the compositor's ordinary modes are
        # called Crossfade/Blend internally.
        if channel == "Normal" and str(node.parameters.get("normal_handling", "Replace")) == "Replace":
            output = self._normal_crossfade(base.image, override.image, coverage)
        if channel == "Height" and str(node.parameters.get("height_handling", "Replace")) == "Replace":
            output = self._compose_channel(channel, base.image, override.image, coverage, height_mode="Blend")
        if channel == "Emissive" and str(node.parameters.get("emissive_handling", "Replace")) == "Replace":
            output = self._compose_channel(channel, base.image, override.image, coverage, emissive_mode="Blend")

        stats = self._merge_stats(*dependencies)
        elapsed = (time.perf_counter() - started) * 1000.0
        if self.collect_traces:
            stats["node_traces"].append(MaterialOperationTrace(
                uid,
                f"{node.definition.name} · {channel}",
                node.definition.type_id,
                elapsed_ms=elapsed,
                width=self.width,
                height=self.height,
                data_kind=MATERIAL_CHANNEL_KINDS[channel],
                bytes_used=int(output.nbytes),
                render_mode=self.render_mode,
                details=f"Masked {channel} override; untouched channels remain lazy pass-throughs.",
            ))
        return MaterialChannelResult(
            output,
            True,
            MATERIAL_CHANNEL_KINDS[channel],
            **stats,
        )

    def _evaluate_switch(self, uid: str, node: Any, channel: str) -> MaterialChannelResult:
        choice, selected_uid, warnings = self._switch_choice(uid, node)
        selected = self.evaluate_channel(selected_uid, channel)
        selected.warnings.extend(warnings)
        if self.collect_traces:
            selected.node_traces.append(MaterialOperationTrace(
                uid,
                f"{node.definition.name} · Material {choice}",
                node.definition.type_id,
                elapsed_ms=0.0,
                cache_hit=True,
                width=self.width,
                height=self.height,
                data_kind=MATERIAL_CHANNEL_KINDS[channel],
                bytes_used=0,
                render_mode=self.render_mode,
                details=f"Selected Material {choice}; the other material branch was not evaluated.",
            ))
        return selected


def resolve_material_producer(snapshot: Any, uid: str | None) -> str | None:
    """Resolve a material producer without evaluating graph content."""
    current = str(uid or "")
    visited: set[str] = set()
    while current:
        if current in visited:
            return None
        visited.add(current)
        node = snapshot.nodes.get(current)
        if node is None:
            return None
        type_id = node.definition.type_id
        if type_id in MATERIAL_PRODUCER_TYPES:
            return current
        if type_id == "output.texture_set":
            source = snapshot.inputs.get((current, "Material"))
        elif type_id in {"graph.send", "graph.receive"}:
            source = snapshot.inputs.get((current, "Input"))
        elif type_id == "material.channels":
            source = snapshot.inputs.get((current, "Material"))
        else:
            return None
        if source is None:
            return None
        current = str(source[0])
    return None


def material_channel_present(
    snapshot: Any,
    uid: str | None,
    channel: str,
    _stack: set[tuple[str, str]] | None = None,
) -> bool:
    """Conservatively determine whether a material channel is authored.

    A signal-driven Material Switch is dynamic, so planning considers a channel
    present when either selectable branch can provide it. Runtime evaluation
    still selects only one branch.
    """
    producer_uid = resolve_material_producer(snapshot, uid)
    if producer_uid is None or channel not in MATERIAL_INPUTS:
        return False
    stack = _stack if _stack is not None else set()
    key = (producer_uid, channel)
    if key in stack:
        return False
    stack.add(key)
    try:
        node = snapshot.nodes[producer_uid]
        type_id = node.definition.type_id
        if type_id == "material.pbr":
            if (producer_uid, channel) in snapshot.inputs:
                return True
            legacy = next((old for old, new in LEGACY_INPUT_ALIASES.items() if new == channel), None)
            return bool(legacy and (producer_uid, legacy) in snapshot.inputs)
        if type_id == "material.blend":
            bg = snapshot.inputs.get((producer_uid, "Background Material"))
            fg = snapshot.inputs.get((producer_uid, "Foreground Material"))
            return material_channel_present(snapshot, bg[0] if bg else None, channel, stack) or material_channel_present(
                snapshot, fg[0] if fg else None, channel, stack
            )
        if type_id == "material.override":
            if bool(node.parameters.get(MATERIAL_REMOVE_PARAMETERS[channel], False)):
                return False
            if (producer_uid, channel) in snapshot.inputs:
                return True
            base = snapshot.inputs.get((producer_uid, "Material"))
            return material_channel_present(snapshot, base[0] if base else None, channel, stack)
        if type_id == "material.switch":
            a = snapshot.inputs.get((producer_uid, "Material A"))
            b = snapshot.inputs.get((producer_uid, "Material B"))
            if (producer_uid, "Selection") not in snapshot.inputs:
                selected = b if str(node.parameters.get("selected_material", "A")) == "B" else a
                return material_channel_present(snapshot, selected[0] if selected else None, channel, stack)
            return material_channel_present(snapshot, a[0] if a else None, channel, stack) or material_channel_present(
                snapshot, b[0] if b else None, channel, stack
            )
        if type_id in {"material.crop", "material.make_it_tile_photo"}:
            base = snapshot.inputs.get((producer_uid, "Material"))
            return material_channel_present(snapshot, base[0] if base else None, channel, stack)
        return False
    finally:
        stack.discard(key)
