from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..engine.evaluator import (
    EvaluationCancelled, GraphEvaluator, GraphSnapshot, _prepare_cpu_preview_rgba8,
)
from ..engine.formats import TextureFormat
from ..material_graph import MATERIAL_PRODUCER_TYPES, MaterialEvaluationSession, material_channel_present


from ..material import MATERIAL_DEFAULT_VALUES, MATERIAL_INPUTS



@dataclass(slots=True)
class MaterialEvaluationResult:
    output_uid: str
    output_name: str
    textures: dict[str, np.ndarray]
    connected: frozenset[str]
    settings: dict[str, Any]
    width: int
    height: int
    evaluation_width: int
    evaluation_height: int
    frame_number: int
    time_seconds: float
    elapsed_ms: float
    backend_summary: str
    warnings: tuple[str, ...] = field(default_factory=tuple)
    node_traces: tuple[Any, ...] = field(default_factory=tuple)
    cache_hits: int = 0
    finalise_ms: float = 0.0
    dynamic_channels: frozenset[str] = field(default_factory=frozenset)
    channel_tokens: dict[str, str] = field(default_factory=dict)
    static_cache_hits: int = 0
    base_colour_display: np.ndarray | None = None
    branch_revision: str = ""
    dynamic_nodes: int = 0
    static_nodes: int = 0


@dataclass(slots=True)
class _StaticMaterialChannel:
    image: np.ndarray
    data_kind: str
    backends: tuple[str, ...]
    warnings: tuple[str, ...]
    token: str

    @property
    def bytes_used(self) -> int:
        return int(self.image.nbytes)


class _MaterialSignals(QObject):
    finished = Signal(int, object)
    failed = Signal(int, str)
    progress = Signal(int, int, int, str)
    nodeState = Signal(int, str, bool, int, int, str)


class _MaterialWorker(QRunnable):
    def __init__(
        self,
        request_id: int,
        evaluator: GraphEvaluator,
        snapshot: GraphSnapshot,
        output_uid: str,
        evaluation_width: int,
        evaluation_height: int,
        texture_width: int,
        texture_height: int,
        precision: TextureFormat,
        colour_space: str,
        animation: dict[str, Any],
        cancel_event: threading.Event,
        static_channel_cache: OrderedDict[str, _StaticMaterialChannel] | None = None,
        static_channel_lock: threading.RLock | None = None,
        static_channel_limit: int = 64,
        output_port: str = "Material",
        playback: bool = False,
        collect_traces: bool = True,
        prepare_display: bool = True,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.evaluator = evaluator
        self.snapshot = snapshot
        self.output_uid = output_uid
        self.output_port = str(output_port or "Material")
        self.evaluation_width = max(int(evaluation_width), 1)
        self.evaluation_height = max(int(evaluation_height), 1)
        self.texture_width = max(int(texture_width), 1)
        self.texture_height = max(int(texture_height), 1)
        self.precision = precision
        self.colour_space = colour_space
        self.animation = dict(animation)
        self.cancel_event = cancel_event
        self.static_channel_cache = static_channel_cache if static_channel_cache is not None else OrderedDict()
        self.static_channel_lock = static_channel_lock if static_channel_lock is not None else threading.RLock()
        self.static_channel_limit = max(int(static_channel_limit), 1)
        self.playback = bool(playback)
        self.collect_traces = bool(collect_traces)
        self.prepare_display = bool(prepare_display)
        self.signals = _MaterialSignals()
        self._last_node_state_emit: dict[str, float] = {}

    def _emit_node_state(
        self,
        node_uid: str,
        active: bool,
        current: int = 0,
        target: int = 0,
        message: str = "",
    ) -> None:
        if self.playback:
            return
        now = time.perf_counter()
        last = self._last_node_state_emit.get(node_uid, 0.0)
        boundary = (not active) or target <= 0 or current <= 0 or current >= target
        if active and not boundary and (now - last) < (1.0 / 12.0):
            return
        self._last_node_state_emit[node_uid] = now
        try:
            self.signals.nodeState.emit(
                self.request_id, node_uid, bool(active), int(current), int(target), str(message or "")
            )
        except RuntimeError:
            return

    def _emit_progress(self, current: int, target: int, message: str) -> None:
        if self.playback:
            return
        try:
            self.signals.progress.emit(self.request_id, int(current), int(target), str(message or ""))
        except RuntimeError:
            return

    @staticmethod
    def _resize_float_image(image: np.ndarray, width: int, height: int) -> np.ndarray:
        """Bilinearly resize a float texture without quantising the preview."""
        source = np.asarray(image, dtype=np.float32)
        source_height, source_width = source.shape[:2]
        width = max(int(width), 1)
        height = max(int(height), 1)
        if source_width == width and source_height == height:
            return np.ascontiguousarray(source, dtype=np.float32)

        x = np.linspace(0.0, max(source_width - 1, 0), width, dtype=np.float32)
        y = np.linspace(0.0, max(source_height - 1, 0), height, dtype=np.float32)
        x0 = np.floor(x).astype(np.int32)
        y0 = np.floor(y).astype(np.int32)
        x1 = np.minimum(x0 + 1, source_width - 1)
        y1 = np.minimum(y0 + 1, source_height - 1)
        tx = (x - x0).reshape(1, width, 1)
        ty = (y - y0).reshape(height, 1, 1)
        top = source[y0[:, None], x0[None, :]] * (1.0 - tx) + source[y0[:, None], x1[None, :]] * tx
        bottom = source[y1[:, None], x0[None, :]] * (1.0 - tx) + source[y1[:, None], x1[None, :]] * tx
        return np.ascontiguousarray(top * (1.0 - ty) + bottom * ty, dtype=np.float32)

    def _evaluate_reference(self, input_name: str, source_ref: tuple[str, str]) -> tuple[np.ndarray, str, str, Any]:
        source_uid, output_name = source_ref
        source_node = self.snapshot.nodes.get(source_uid)
        if source_node is None:
            raise RuntimeError(f"Missing source node for material input {input_name}")

        def node_activity(uid: str, active: bool, current: int, target: int, message: str) -> None:
            self._emit_node_state(uid, active, current, target, message)
            if active:
                detail = str(message or f"Evaluating {source_node.definition.name}")
                self._emit_node_state(
                    self.output_uid, True, current, target,
                    f"Material — {input_name}: {detail}",
                )
            else:
                self._emit_node_state(
                    self.output_uid, True, 0, 0,
                    f"Material — preparing {input_name} material map",
                )

        # Evaluate the connected source directly. The previous synthetic Image
        # Output sink created an extra full-resolution cache entry for every
        # material map, which could evict expensive upstream textures and make
        # later 2D edits appear mysteriously slow.
        result = self.evaluator.evaluate_snapshot(
            self.snapshot,
            source_uid,
            self.evaluation_width,
            self.evaluation_height,
            cancel_check=self.cancel_event.is_set,
            progress_callback=None if self.playback else self._emit_progress,
            node_activity_callback=node_activity,
            precision=self.precision,
            colour_space=self.colour_space,
            render_mode="preview_3d",
            output_name=output_name,
            **self.animation,
        )
        if result.error:
            raise RuntimeError(f"{input_name}: {result.error}")
        image = np.ascontiguousarray(result.image, dtype=np.float32)
        if image.shape[1] != self.texture_width or image.shape[0] != self.texture_height:
            self._emit_node_state(
                self.output_uid, True, 0, 0,
                f"Material — resizing {input_name} from {image.shape[1]} × {image.shape[0]} "
                f"to {self.texture_width} × {self.texture_height}",
            )
            image = self._resize_float_image(image, self.texture_width, self.texture_height)
        return image, result.backend, result.precision, result

    def _channel_cache_key(self, material_uid: str, input_name: str, branch_revision: str) -> str:
        payload = {
            "material": str(material_uid),
            "channel": str(input_name),
            "branch": str(branch_revision),
            "evaluation": (self.evaluation_width, self.evaluation_height),
            "texture": (self.texture_width, self.texture_height),
            "precision": str(getattr(self.precision, "value", self.precision)),
            "colour_space": self.colour_space,
        }
        return hashlib.blake2b(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8"),
            digest_size=20,
        ).hexdigest()

    def _dynamic_channel_token(self, static_key: str) -> str:
        animation = {
            name: self.animation.get(name)
            for name in (
                "frame_number", "frame_position", "time_seconds", "normalised_time",
                "loop_phase", "delta_time",
            )
        }
        suffix = hashlib.blake2b(
            json.dumps(animation, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8"),
            digest_size=12,
        ).hexdigest()
        return f"dynamic:{static_key}:{suffix}"

    def _static_channel_get(self, key: str) -> _StaticMaterialChannel | None:
        with self.static_channel_lock:
            cached = self.static_channel_cache.get(key)
            if cached is not None:
                self.static_channel_cache.move_to_end(key)
            return cached

    def _static_channel_put(self, key: str, value: _StaticMaterialChannel) -> None:
        with self.static_channel_lock:
            self.static_channel_cache.pop(key, None)
            self.static_channel_cache[key] = value
            self.static_channel_cache.move_to_end(key)
            while len(self.static_channel_cache) > self.static_channel_limit:
                self.static_channel_cache.popitem(last=False)

    def run(self) -> None:
        started = time.perf_counter()
        try:
            public_output_uid = self.output_uid
            public_output_name = self.output_port
            public_branch_revision = self.evaluator.branch_revision(self.snapshot, self.output_uid)
            output_node = self.snapshot.nodes.get(self.output_uid)
            if output_node is None:
                raise RuntimeError("The selected material-producing node no longer exists")
            material_uid = self.output_uid
            if output_node.definition.type_id == "graph.instance":
                self.snapshot, material_uid, resolved_output = self.evaluator._expand_graph_instances(
                    self.snapshot, self.output_uid, self.output_port
                )
                output_node = self.snapshot.nodes.get(material_uid)
                if output_node is None:
                    raise RuntimeError("The selected graph asset output could not be resolved")
                self.output_port = resolved_output
            if output_node.definition.type_id not in MATERIAL_PRODUCER_TYPES:
                raise RuntimeError("The selected graph output is not a Material")
            self._emit_node_state(
                public_output_uid, True, 0, 0,
                f"Material — resolving channels at {self.evaluation_width} × {self.evaluation_height}",
            )
            session = MaterialEvaluationSession(
                self.evaluator,
                self.snapshot,
                self.evaluation_width,
                self.evaluation_height,
                cancel_check=self.cancel_event.is_set,
                progress_callback=None if self.playback else self._emit_progress,
                node_activity_callback=None if self.playback else self._emit_node_state,
                precision=self.precision,
                colour_space=self.colour_space,
                render_mode="preview_3d",
                collect_traces=self.collect_traces,
                **self.animation,
            )
            info = session.material_info(material_uid)
            material_revision = self.evaluator.branch_revision(self.snapshot, material_uid)
            allow_persistent_static_cache = output_node.definition.type_id == "material.pbr"
            textures: dict[str, np.ndarray] = {}
            connected: set[str] = set()
            warnings: list[str] = list(info.warnings)
            backends: set[str] = set()
            trace_by_key: dict[tuple[str, str, str], Any] = {}
            cache_hits = 0
            finalise_ms = 0.0
            dynamic_channels: set[str] = set()
            channel_tokens: dict[str, str] = {
                name: f"default:{name}" for name in MATERIAL_INPUTS
            }
            static_cache_hits = 0
            dynamic_node_count = 0
            static_node_count = 0
            # Missing material channels are represented by the renderer's 1 × 1
            # semantic defaults.  The old bridge expanded every absent channel
            # into a full-resolution RGBA32F image, then uploaded all nine maps.
            # At 2K that could allocate/read/upload more than half a gigabyte for
            # a material that authored only Base Colour, Height and Roughness.
            # Resolve only structurally possible channels; dynamic switches are
            # still evaluated conservatively and may report the selected channel
            # absent at runtime.
            planned_inputs = [
                input_name for input_name in MATERIAL_INPUTS
                if material_channel_present(self.snapshot, material_uid, input_name)
            ]
            total_inputs = len(planned_inputs)
            for input_index, input_name in enumerate(planned_inputs):
                if self.cancel_event.is_set():
                    raise EvaluationCancelled()
                self._emit_progress(
                    input_index, total_inputs, f"Material — {input_name} material map"
                )
                self._emit_node_state(
                    self.output_uid, True, input_index, total_inputs,
                    f"Material — resolving {input_name}",
                )
                stable_key = self._channel_cache_key(material_uid, input_name, material_revision)
                cached_channel = (
                    self._static_channel_get(stable_key)
                    if allow_persistent_static_cache else None
                )
                if cached_channel is not None:
                    textures[input_name] = cached_channel.image
                    connected.add(input_name)
                    channel_tokens[input_name] = cached_channel.token
                    warnings.extend(cached_channel.warnings)
                    backends.update(cached_channel.backends)
                    cache_hits += 1
                    static_cache_hits += 1
                    continue

                channel = session.evaluate_channel(material_uid, input_name)
                if channel.present:
                    image = channel.image
                    # Uniform generator channels deliberately remain 1 × 1. The
                    # material sampler expands them for free, avoiding a complete
                    # readback, resize, mip chain and upload for simple constants.
                    is_uniform = image.shape[0] == 1 and image.shape[1] == 1
                    if (
                        not is_uniform
                        and (image.shape[1] != self.texture_width or image.shape[0] != self.texture_height)
                    ):
                        self._emit_node_state(
                            self.output_uid, True, input_index, total_inputs,
                            f"Material — resizing {input_name} from {image.shape[1]} × {image.shape[0]} "
                            f"to {self.texture_width} × {self.texture_height}",
                        )
                        image = self._resize_float_image(image, self.texture_width, self.texture_height)
                    image = np.ascontiguousarray(image, dtype=np.float32)
                    textures[input_name] = image
                    connected.add(input_name)
                    # Material composition can be driven by scalar switches or
                    # masks whose time-dependency is not represented by the leaf
                    # image count. Keep composed materials conservative for now;
                    # direct PBR channels receive the full static residency path.
                    is_dynamic = int(channel.dynamic_nodes) > 0 or not allow_persistent_static_cache
                    if is_dynamic:
                        dynamic_channels.add(input_name)
                        channel_tokens[input_name] = self._dynamic_channel_token(stable_key)
                    else:
                        token = f"static:{stable_key}"
                        channel_tokens[input_name] = token
                        if allow_persistent_static_cache:
                            self._static_channel_put(
                                stable_key,
                                _StaticMaterialChannel(
                                    image=image,
                                    data_kind=channel.data_kind,
                                    backends=tuple(sorted(str(name) for name in channel.backends)),
                                    warnings=tuple(str(item) for item in channel.warnings),
                                    token=token,
                                ),
                            )
                dynamic_node_count += int(channel.dynamic_nodes)
                static_node_count += int(channel.static_nodes)
                warnings.extend(channel.warnings)
                backends.update(channel.backends)
                cache_hits += int(channel.cache_hits)
                finalise_ms += float(channel.finalise_ms)
                for trace in channel.node_traces:
                    trace_key = (
                        str(getattr(trace, "node_uid", "")),
                        str(getattr(trace, "stage", "node")),
                        str(getattr(trace, "name", "")),
                    )
                    trace_by_key.setdefault(trace_key, trace)

            if self.cancel_event.is_set():
                raise EvaluationCancelled()
            self._emit_progress(
                total_inputs, total_inputs, "Material — material maps ready for upload"
            )
            self._emit_node_state(
                self.output_uid, True, total_inputs, total_inputs,
                "Material — material maps ready for upload",
            )
            has_gpu = any("GPU" in str(name) for name in backends)
            has_cpu = any("CPU" in str(name) or "Hybrid" in str(name) for name in backends)
            if has_gpu and has_cpu:
                backend_summary = "Hybrid"
            elif has_gpu:
                backend_summary = "GPU"
            elif backends and backends != {"Defaults"}:
                backend_summary = "CPU"
            else:
                backend_summary = "Defaults"
            base_colour = textures.get(
                "Base Colour",
                np.asarray(MATERIAL_DEFAULT_VALUES["Base Colour"], dtype=np.float32).reshape(1, 1, 4),
            )
            base_colour_display = (
                _prepare_cpu_preview_rgba8(
                    base_colour, self.texture_width, self.texture_height, "color"
                )
                if self.prepare_display
                else None
            )
            result = MaterialEvaluationResult(
                output_uid=public_output_uid,
                output_name=info.name or public_output_name,
                textures=textures,
                connected=frozenset(connected),
                settings=info.settings,
                width=self.texture_width,
                height=self.texture_height,
                evaluation_width=self.evaluation_width,
                evaluation_height=self.evaluation_height,
                frame_number=int(self.animation.get("frame_number", 0)),
                time_seconds=float(self.animation.get("time_seconds", 0.0)),
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                backend_summary=backend_summary,
                warnings=tuple(dict.fromkeys(str(w) for w in warnings if str(w))),
                node_traces=tuple(trace_by_key.values()),
                cache_hits=cache_hits,
                finalise_ms=finalise_ms,
                dynamic_channels=frozenset(dynamic_channels),
                channel_tokens=channel_tokens,
                static_cache_hits=static_cache_hits,
                base_colour_display=base_colour_display,
                branch_revision=public_branch_revision,
                dynamic_nodes=dynamic_node_count,
                static_nodes=static_node_count,
            )
            if not self.cancel_event.is_set():
                self.signals.finished.emit(self.request_id, result)
        except EvaluationCancelled:
            return
        except Exception as exc:
            if not self.cancel_event.is_set():
                try:
                    self.signals.failed.emit(self.request_id, f"{type(exc).__name__}: {exc}")
                except RuntimeError:
                    return


class MaterialEvaluationController(QObject):
    resultReady = Signal(object)
    evaluationStarted = Signal()
    evaluationFailed = Signal(str)
    evaluationProgress = Signal(int, int, str)
    evaluationNodeState = Signal(str, bool, int, int, str)

    def __init__(self, evaluator: GraphEvaluator, parent=None) -> None:
        super().__init__(parent)
        self.evaluator = evaluator
        self.pool = QThreadPool.globalInstance()
        self._request_id = 0
        self._cancel_event: threading.Event | None = None
        self._static_channel_cache: OrderedDict[str, _StaticMaterialChannel] = OrderedDict()
        self._static_channel_lock = threading.RLock()
        self._static_channel_limit = 64

    def request(
        self,
        snapshot: GraphSnapshot,
        output_uid: str,
        output_port: str,
        evaluation_width: int,
        evaluation_height: int,
        texture_width: int,
        texture_height: int,
        precision: TextureFormat,
        colour_space: str,
        animation: dict[str, Any],
        *,
        playback: bool = False,
        collect_traces: bool = True,
        prepare_display: bool = True,
    ) -> int:
        if self._cancel_event is not None:
            self._cancel_event.set()
        self._request_id += 1
        request_id = self._request_id
        cancel_event = threading.Event()
        self._cancel_event = cancel_event
        worker = _MaterialWorker(
            request_id,
            self.evaluator,
            snapshot,
            output_uid,
            evaluation_width,
            evaluation_height,
            texture_width,
            texture_height,
            precision,
            colour_space,
            animation,
            cancel_event,
            self._static_channel_cache,
            self._static_channel_lock,
            self._static_channel_limit,
            output_port=output_port,
            playback=playback,
            collect_traces=collect_traces,
            prepare_display=prepare_display,
        )
        worker.signals.finished.connect(self._finished)
        worker.signals.failed.connect(self._failed)
        worker.signals.progress.connect(self._progress)
        worker.signals.nodeState.connect(self._node_state)
        self.evaluationStarted.emit()
        self.pool.start(worker)
        return request_id

    def clear_static_cache(self) -> None:
        with self._static_channel_lock:
            self._static_channel_cache.clear()

    def cancel(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
        # Invalidate queued worker signals as well as cooperative evaluation.
        # A worker can finish just before observing its cancel event; advancing
        # the generation prevents that stale result from reaching the preview.
        self._request_id += 1
        self._cancel_event = None

    def _finished(self, request_id: int, result: MaterialEvaluationResult) -> None:
        if request_id != self._request_id:
            return
        self._cancel_event = None
        self.resultReady.emit(result)

    def _progress(self, request_id: int, current: int, target: int, message: str) -> None:
        if request_id != self._request_id:
            return
        self.evaluationProgress.emit(current, target, message)

    def _node_state(
        self,
        request_id: int,
        node_uid: str,
        active: bool,
        current: int,
        target: int,
        message: str,
    ) -> None:
        if request_id != self._request_id:
            return
        self.evaluationNodeState.emit(node_uid, active, current, target, message)

    def _failed(self, request_id: int, message: str) -> None:
        if request_id != self._request_id:
            return
        self._cancel_event = None
        self.evaluationFailed.emit(message)
