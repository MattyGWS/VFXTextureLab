from __future__ import annotations

import hashlib
import json
import threading
import time
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import numpy as np

from ..animation_export import sample_positions_from_node
from ..evaluation_gate import EvaluationGate, EvaluationGateCancelled
from ..flipbook import flipbook_relative_index
from ..nodes.base import EvalContext, NodeDefinition, ParameterSpec, is_image_kind, normalise_port_kind
from ..graph_assets import (
    GRAPH_INPUT_TYPE, GRAPH_OUTPUT_TYPE, GRAPH_INSTANCE_TYPE,
    asset_graph_data, definition_for_serialised_node, derive_seed,
    external_parameter_name, graph_input_kind, graph_instance_definition,
)
from .backends import CpuBackend
from .backends.base import BackendCancelled
from .cache import CacheStats, MemoryLRU
from .formats import RenderContext, TextureFormat
from .resources import CpuImage, GpuImage, GraphResource, ImageResource, SignalValue
from .simulation import SimulationStateManager

try:
    from .backends.wgpu_backend import WgpuBackend
except Exception:
    WgpuBackend = None  # type: ignore[assignment]


class EvaluationError(RuntimeError):
    pass


class EvaluationCancelled(RuntimeError):
    pass


def _graph_asset_scalar_default(_inputs, parameters, _context):
    return {"Value": float(parameters.get("default_value", 0.0))}


@dataclass(frozen=True, slots=True)
class SnapshotNode:
    uid: str
    definition: NodeDefinition
    parameters: dict[str, Any]
    input_names: tuple[str, ...] = ()
    parameter_ports: tuple[tuple[str, str], ...] = ()
    resolved_kind: str = "grayscale"

    def __post_init__(self) -> None:
        if not self.input_names:
            object.__setattr__(self, "input_names", tuple(self.definition.inputs))

    def parameter_for_port(self, input_name: str) -> str | None:
        for port_name, parameter_name in self.parameter_ports:
            if port_name == input_name:
                return parameter_name
        return None


@dataclass(frozen=True, slots=True)
class GraphSnapshot:
    nodes: dict[str, SnapshotNode]
    # (target node, input name) -> (source node, source output)
    inputs: dict[tuple[str, str], tuple[str, str]]

    @classmethod
    def from_scene(cls, scene) -> "GraphSnapshot":
        nodes: dict[str, SnapshotNode] = {}
        for uid, item in scene.nodes.items():
            parameter_ports: list[tuple[str, str]] = []
            for input_name in item.input_ports:
                parameter_name = item.parameter_name_from_port(input_name)
                if parameter_name is not None:
                    parameter_ports.append((input_name, parameter_name))
            nodes[uid] = SnapshotNode(
                uid,
                item.definition,
                deepcopy(item.parameters),
                tuple(item.input_ports),
                tuple(parameter_ports),
                item.resolved_image_kind,
            )
        inputs: dict[tuple[str, str], tuple[str, str]] = {}
        for connection in scene.connections:
            if bool(getattr(connection, "broken", False)):
                continue
            inputs[(connection.target_node.uid, connection.input_name)] = (
                connection.source_node.uid,
                connection.output_name,
            )
        # Receive nodes are visually wireless but evaluate as an ordinary
        # zero-cost pass-through from the source connected to their Send node.
        for uid, item in scene.nodes.items():
            if item.definition.type_id != "graph.receive":
                continue
            sender_uid = str(item.parameters.get("sender_uid", ""))
            sender = scene.nodes.get(sender_uid)
            if sender is None or sender.definition.type_id != "graph.send":
                continue
            source = inputs.get((sender_uid, "Input"))
            if source is not None:
                inputs[(uid, "Input")] = source
        return cls(nodes, inputs)


@dataclass(frozen=True, slots=True)
class NodeEvaluationTrace:
    node_uid: str
    name: str
    type_id: str
    stage: str = "node"
    backend: str = ""
    state: str = "Computed"
    elapsed_ms: float = 0.0
    cache_hit: bool = False
    width: int = 0
    height: int = 0
    precision: str = ""
    data_kind: str = ""
    bytes_used: int = 0
    render_mode: str = "preview"
    details: str = ""


@dataclass(slots=True)
class EvaluationResult:
    image: np.ndarray | None
    error: str | None = None
    display_rgba: np.ndarray | None = None
    source_width: int = 0
    source_height: int = 0
    backend: str = "CPU"
    elapsed_ms: float = 0.0
    gpu_nodes: int = 0
    cpu_nodes: int = 0
    signal_nodes: int = 0
    cache_hits: int = 0
    fallback_nodes: tuple[str, ...] = ()
    reachable_nodes: int = 0
    error_node_uid: str | None = None
    signal_value: float | tuple[float, ...] | None = None
    frame_number: int = 0
    time_seconds: float = 0.0
    data_kind: str = "grayscale"
    precision: str = "16-bit"
    simulation_steps: int = 0
    simulation_nodes: int = 0
    simulation_checkpoint: int = -1
    finalise_ms: float = 0.0
    queue_wait_ms: float = 0.0
    dynamic_nodes: int = 0
    static_nodes: int = 0
    gpu_cache_entries: int = 0
    gpu_cache_bytes: int = 0
    fused_nodes: int = 0
    fused_passes: int = 0
    node_traces: tuple[NodeEvaluationTrace, ...] = ()


def _prepare_cpu_preview_rgba8(
    image: np.ndarray, width: int, height: int, data_kind: str
) -> np.ndarray:
    """Prepare a small display image without copying the full-resolution array."""
    source = np.asarray(image, dtype=np.float32)
    source_height, source_width = source.shape[:2]
    target_width = max(1, min(int(width), source_width))
    target_height = max(1, min(int(height), source_height))
    if target_width == source_width and target_height == source_height:
        resized = source
    else:
        x = (np.arange(target_width, dtype=np.float32) + 0.5) * (source_width / target_width) - 0.5
        y = (np.arange(target_height, dtype=np.float32) + 0.5) * (source_height / target_height) - 0.5
        x0 = np.clip(np.floor(x).astype(np.int32), 0, source_width - 1)
        y0 = np.clip(np.floor(y).astype(np.int32), 0, source_height - 1)
        x1 = np.minimum(x0 + 1, source_width - 1)
        y1 = np.minimum(y0 + 1, source_height - 1)
        tx = (x - x0).astype(np.float32)[None, :, None]
        ty = (y - y0).astype(np.float32)[:, None, None]
        a = source[y0[:, None], x0[None, :]]
        b = source[y0[:, None], x1[None, :]]
        c = source[y1[:, None], x0[None, :]]
        d = source[y1[:, None], x1[None, :]]
        resized = (a * (1.0 - tx) + b * tx) * (1.0 - ty) + (c * (1.0 - tx) + d * tx) * ty
    display = np.clip(resized, 0.0, 1.0).copy()
    if data_kind == "grayscale":
        display[..., 0:3] = display[..., 0:1]
        display[..., 3] = 1.0
    elif data_kind == "vector":
        display[..., 3] = 1.0
    else:
        rgb = display[..., :3]
        display[..., :3] = np.where(
            rgb <= 0.0031308,
            rgb * 12.92,
            1.055 * np.power(rgb, 1.0 / 2.4) - 0.055,
        )
    return (np.clip(display, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


class GraphEvaluator:
    """Demand-driven hybrid image and animation-signal graph evaluator.

    Image operations stay on WebGPU where available. Scalar/vector signal nodes
    run on the CPU because their cost is a few arithmetic operations per frame.
    Cache signatures include time only for branches proven to depend on time, so
    static texture branches remain cached during playback.
    """

    VALID_PREFERENCES = ("auto", "gpu", "cpu")

    _FUSION_OPCODES = {
        "filter.invert": 0,
        "filter.brightness": 1,
        "filter.contrast": 2,
        "filter.exposure": 3,
        "filter.gamma": 4,
        "filter.posterize": 5,
        "filter.clamp": 6,
        "filter.levels": 7,
        "filter.histogram_range": 8,
        "filter.histogram_shift": 9,
        "filter.histogram_scan": 10,
    }
    _MAX_FUSED_ADJUSTMENTS = 8

    def _is_fusion_candidate(self, snapshot: GraphSnapshot, node: SnapshotNode) -> bool:
        if self.backend_preference == "cpu" or not self.gpu_available:
            return False
        if node.definition.type_id not in self._FUSION_OPCODES:
            return False
        if node.definition.is_stateful or node.definition.is_signal_node:
            return False
        if tuple(node.definition.inputs) != ("Image",):
            return False
        if tuple(node.definition.output_names) != ("Image",):
            return False
        if node.definition.named_output_parameter is not None:
            return False
        if bool(node.parameters.get("_bypassed", False)):
            return False
        if str(node.parameters.get("_precision", "Inherit")) != "Inherit":
            return False
        # The first fusion pass targets grayscale mask/height chains, where the
        # existing GPU path uses r32float storage and can be reproduced bit for
        # bit without changing intermediate precision. Colour/vector chains
        # remain unfused until their rgba16float rounding can be guaranteed.
        if normalise_port_kind(node.resolved_kind) != "grayscale":
            return False
        image_ref = self._source_reference(snapshot.inputs.get((node.uid, "Image")))
        if image_ref is None or image_ref[1] != "Image":
            return False
        # A parameter driven by a signal changes the effective parameter set at
        # evaluation time. Keep those nodes on the ordinary path for now.
        for input_name in node.input_names:
            if input_name == "Image":
                continue
            if self._source_reference(snapshot.inputs.get((node.uid, input_name))) is not None:
                return False
        return self._backend_for(node.definition) == "gpu"

    def _fusion_plan(
        self, snapshot: GraphSnapshot, order: list[str]
    ) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
        reachable = set(order)
        outgoing: dict[str, list[tuple[str, str, str]]] = {uid: [] for uid in order}
        for (target_uid, input_name), raw_source in snapshot.inputs.items():
            source_ref = self._source_reference(raw_source)
            if source_ref is None:
                continue
            source_uid, source_output = source_ref
            if target_uid in reachable and source_uid in reachable:
                outgoing.setdefault(source_uid, []).append((target_uid, input_name, source_output))

        chains: dict[str, tuple[str, ...]] = {}
        member_to_tail: dict[str, str] = {}
        claimed: set[str] = set()
        for uid in order:
            if uid in claimed:
                continue
            node = snapshot.nodes[uid]
            if not self._is_fusion_candidate(snapshot, node):
                continue
            chain = [uid]
            current = uid
            while len(chain) < self._MAX_FUSED_ADJUSTMENTS:
                consumers = outgoing.get(current, ())
                if len(consumers) != 1:
                    break
                target_uid, input_name, source_output = consumers[0]
                if input_name != "Image" or source_output != "Image":
                    break
                if target_uid in claimed:
                    break
                target = snapshot.nodes[target_uid]
                if not self._is_fusion_candidate(snapshot, target):
                    break
                target_source = self._source_reference(snapshot.inputs.get((target_uid, "Image")))
                if target_source != (current, "Image"):
                    break
                chain.append(target_uid)
                current = target_uid
            if len(chain) < 2:
                continue
            tail = chain[-1]
            chains[tail] = tuple(chain)
            claimed.update(chain)
            for member in chain[:-1]:
                member_to_tail[member] = tail
        return chains, member_to_tail

    def _apply_fusion_plan(
        self,
        snapshot: GraphSnapshot,
        chains: dict[str, tuple[str, ...]],
    ) -> GraphSnapshot:
        if not chains:
            return snapshot
        nodes = dict(snapshot.nodes)
        inputs = dict(snapshot.inputs)
        for tail_uid, chain_uids in chains.items():
            first_uid = chain_uids[0]
            first_source = self._source_reference(snapshot.inputs.get((first_uid, "Image")))
            if first_source is None:
                continue
            chain_nodes = [snapshot.nodes[uid] for uid in chain_uids]
            operations = [list(self._fusion_operation(node, "32-bit float")) for node in chain_nodes]
            tail = chain_nodes[-1]
            names = " → ".join(node.definition.name for node in chain_nodes)
            definition = NodeDefinition(
                type_id="internal.fused_adjustments",
                name=f"Fused: {names}",
                category="Internal",
                evaluator=None,
                inputs=("Image",),
                description=f"One GPU pass replacing {len(chain_nodes)} compatible adjustment nodes.",
                accent=tail.definition.accent,
                tags=("internal", "fusion", "adjustments"),
                output_format=tail.definition.output_format,
                gpu_kernel="fused_adjustments.wgsl",
                hidden=True,
                input_kinds=(("Image", "image_any"),),
                output_kinds=(("Image", "image_any"),),
                type_policy="preserve_primary",
                primary_input="Image",
                default_image_kind=tail.resolved_kind,
            )
            parameters = {
                "_fusion_operations": operations,
                "_fusion_names": [node.definition.name for node in chain_nodes],
                "_fusion_uids": list(chain_uids),
                "_fusion_count": len(chain_nodes),
                "_precision": "Inherit",
                "_resolved_kind": tail.resolved_kind,
            }
            nodes[tail_uid] = SnapshotNode(
                tail_uid, definition, parameters, ("Image",), (), tail.resolved_kind
            )
            for member_uid in chain_uids[:-1]:
                nodes.pop(member_uid, None)
            for key in [key for key in inputs if key[0] in chain_uids]:
                inputs.pop(key, None)
            inputs[(tail_uid, "Image")] = first_source
        return GraphSnapshot(nodes, inputs)

    @staticmethod
    def _fusion_quantisation(precision: str) -> float:
        if precision == "8-bit":
            return 2.0
        if precision == "16-bit":
            return 1.0
        return 0.0

    def _fusion_operation(
        self, node: SnapshotNode, output_precision: str
    ) -> tuple[float, float, float, float, float, float, float, float]:
        type_id = node.definition.type_id
        code = float(self._FUSION_OPCODES[type_id])
        params = node.parameters
        quant = self._fusion_quantisation(output_precision)
        if type_id == "filter.brightness":
            return (code, float(params.get("brightness", 0.0)), 0.0, 0.0, 0.0, 0.0, 0.0, quant)
        if type_id == "filter.contrast":
            return (code, float(params.get("contrast", 0.0)), float(params.get("pivot", 0.5)), 0.0, 0.0, 0.0, 0.0, quant)
        if type_id == "filter.exposure":
            return (code, float(params.get("exposure", 0.0)), 0.0, 0.0, 0.0, 0.0, 0.0, quant)
        if type_id == "filter.gamma":
            return (code, float(params.get("gamma", 1.0)), 0.0, 0.0, 0.0, 0.0, 0.0, quant)
        if type_id == "filter.posterize":
            return (code, float(params.get("steps", 8)), 0.0, 0.0, 0.0, 0.0, 0.0, quant)
        if type_id == "filter.clamp":
            return (code, float(params.get("minimum", 0.0)), float(params.get("maximum", 1.0)), 0.0, 0.0, 0.0, 0.0, quant)
        if type_id == "filter.levels":
            return (
                code,
                float(params.get("in_low", params.get("black", 0.0))),
                float(params.get("in_high", params.get("white", 1.0))),
                float(params.get("in_mid", 0.5)),
                float(params.get("out_low", 0.0)),
                float(params.get("out_high", 1.0)),
                1.0 if bool(params.get("intermediary_clamp", True)) else 0.0,
                quant,
            )
        if type_id == "filter.histogram_range":
            return (code, float(params.get("range", 1.0)), float(params.get("position", 0.5)), 0.0, 0.0, 0.0, 0.0, quant)
        if type_id == "filter.histogram_shift":
            return (code, float(params.get("position", 0.0)), 0.0, 0.0, 0.0, 0.0, 0.0, quant)
        if type_id == "filter.histogram_scan":
            return (code, float(params.get("position", 0.5)), float(params.get("contrast", 0.5)), 0.0, 0.0, 0.0, 0.0, quant)
        return (code, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, quant)

    def __init__(
        self,
        scene=None,
        *,
        backend_preference: str = "auto",
        gpu_budget_mb: int = 512,
        cpu_budget_mb: int = 256,
    ) -> None:
        self.scene = scene
        self._lock = threading.RLock()
        self.backend_preference = backend_preference if backend_preference in self.VALID_PREFERENCES else "auto"
        self.gpu_backend = WgpuBackend() if WgpuBackend is not None else None
        self.cpu_backend = CpuBackend(self.gpu_backend)
        self.gpu_cache: MemoryLRU[GraphResource] = MemoryLRU(gpu_budget_mb * 1024 * 1024)
        self.cpu_cache: MemoryLRU[GraphResource] = MemoryLRU(cpu_budget_mb * 1024 * 1024)
        self.simulations = SimulationStateManager()
        self._last_node_signatures: dict[tuple[str, int, int, str, str], str] = {}
        # Evaluations share GPU resources and caches. This fair gate gives
        # direct 2D work priority over automatic 3D material refreshes.
        self._evaluation_gate = EvaluationGate()

    @property
    def gpu_available(self) -> bool:
        return bool(self.gpu_backend is not None and self.gpu_backend.available)

    def backend_info(self) -> dict[str, Any]:
        gpu_info = self.gpu_backend.info() if self.gpu_backend is not None else None
        return {
            "preference": self.backend_preference,
            "gpu_available": self.gpu_available,
            "gpu_name": gpu_info.name if gpu_info else "GPU (WebGPU/WGSL)",
            "gpu_detail": gpu_info.detail if gpu_info else "wgpu-py is not installed",
            "supported_gpu_nodes": (
                tuple(sorted(set(self.gpu_backend.supported_type_ids()) | {
                    definition.type_id
                    for definition in (self.scene.registry.all() if self.scene is not None else ())
                    if self.gpu_backend.supports(definition)
                }))
                if self.gpu_backend is not None else ()
            ),
        }

    def set_backend_preference(self, preference: str) -> None:
        if preference not in self.VALID_PREFERENCES:
            raise ValueError(f"Unknown backend preference: {preference}")
        self.backend_preference = preference

    def set_memory_budget_mb(self, gpu_mb: int, cpu_mb: int | None = None) -> None:
        self.gpu_cache.set_budget(max(gpu_mb, 32) * 1024 * 1024)
        self.cpu_cache.set_budget(max(cpu_mb if cpu_mb is not None else gpu_mb // 2, 32) * 1024 * 1024)

    def cache_stats(self) -> dict[str, CacheStats]:
        return {"gpu": self.gpu_cache.stats(), "cpu": self.cpu_cache.stats()}

    def clear_cache(self) -> None:
        with self._lock:
            self.gpu_cache.clear()
            self.cpu_cache.clear()
            if self.gpu_backend is not None:
                self.gpu_backend.clear()
            self.simulations.clear()
            self._last_node_signatures.clear()

    def reset_simulations(self, node_uid: str | None = None) -> None:
        """Discard runtime simulation state without changing graph data."""
        with self._lock:
            self.simulations.clear(node_uid)

    @contextmanager
    def _evaluation_slot(
        self,
        render_mode: str,
        cancel_check: Callable[[], bool] | None = None,
        wait_callback: Callable[[float], None] | None = None,
    ):
        """Serialise graph evaluation while prioritising direct feedback."""
        try:
            with self._evaluation_gate.slot(
                low_priority=str(render_mode or "preview") in {"preview_3d", "histogram", "thumbnail"},
                cancel_check=cancel_check,
                wait_callback=wait_callback,
            ) as wait_ms:
                yield wait_ms
        except EvaluationGateCancelled as exc:
            raise EvaluationCancelled() from exc

    def branch_revision(self, snapshot: GraphSnapshot, node_uid: str) -> str:
        """Return a stable content revision for one node and its upstream branch.

        Layout-only changes and edits in unrelated graph branches do not affect
        this value. UI schedulers use it to avoid redundant material-preview
        evaluations and to preserve already-computed upstream results.
        """
        return self._simulation_revision(snapshot, node_uid)

    def snapshot(self) -> GraphSnapshot:
        if self.scene is None:
            raise RuntimeError("No graph scene is attached")
        return GraphSnapshot.from_scene(self.scene)

    @staticmethod
    def _asset_sources(data: dict[str, Any]) -> dict[tuple[str, str], tuple[str, str]]:
        inputs: dict[tuple[str, str], tuple[str, str]] = {}
        nodes = {
            str(entry.get("uid", "")): entry
            for entry in data.get("nodes", ())
            if isinstance(entry, dict)
        }
        for connection in data.get("connections", ()):
            if not isinstance(connection, dict):
                continue
            source = str(connection.get("source", ""))
            target = str(connection.get("target", ""))
            input_name = str(connection.get("input", ""))
            source_output = str(connection.get("source_output", "Image") or "Image")
            if source and target and input_name:
                inputs[(target, input_name)] = (source, source_output)
        for uid, entry in nodes.items():
            if str(entry.get("type", "")) != "graph.receive":
                continue
            parameters = dict(entry.get("parameters", {}))
            sender_uid = str(parameters.get("sender_uid", ""))
            source = inputs.get((sender_uid, "Input"))
            if source is not None:
                inputs[(uid, "Input")] = source
        return inputs

    def _asset_snapshot_node(
        self,
        node_data: dict[str, Any],
        uid: str,
        *,
        parameters: dict[str, Any] | None = None,
        resolved_kind: str | None = None,
    ) -> SnapshotNode:
        definition = definition_for_serialised_node(self.scene.registry, node_data)
        if definition is None:
            type_id = str(node_data.get("type", ""))
            snapshot = node_data.get("definition") if isinstance(node_data.get("definition"), dict) else None
            definition = self.scene.registry.ensure_placeholder(type_id, snapshot)
        params = deepcopy(dict(node_data.get("parameters", {}))) if parameters is None else parameters
        if definition.type_id == GRAPH_INSTANCE_TYPE:
            definition = graph_instance_definition(params)
        exposed = [str(value) for value in params.get("_exposed_inputs", ())]
        input_names = list(definition.inputs)
        parameter_ports: list[tuple[str, str]] = []
        for name in exposed:
            if definition.parameter_spec(name) is None:
                continue
            port_name = f"@param:{name}"
            if port_name not in input_names:
                input_names.append(port_name)
            parameter_ports.append((port_name, name))
        kind = normalise_port_kind(
            resolved_kind or params.get("_resolved_kind", definition.default_image_kind)
        )
        if definition.type_id == GRAPH_INPUT_TYPE:
            kind = graph_input_kind(params)
        if kind not in {"grayscale", "color", "vector"}:
            kind = definition.default_image_kind
        return SnapshotNode(
            uid,
            definition,
            params,
            tuple(input_names),
            tuple(parameter_ports),
            kind,
        )

    def _expand_one_graph_instance(
        self,
        snapshot: GraphSnapshot,
        instance_uid: str,
    ) -> tuple[GraphSnapshot, dict[str, tuple[str, str]]]:
        instance = snapshot.nodes[instance_uid]
        params = deepcopy(instance.parameters)
        identity = str(
            params.get("_asset_identity")
            or params.get("_asset_path")
            or params.get("_asset_revision")
            or instance_uid
        )
        ancestry = tuple(str(value) for value in params.get("_asset_ancestry", ()))
        if identity in ancestry:
            chain = " → ".join((*ancestry, identity))
            raise EvaluationError(f"Recursive graph asset dependency detected: {chain}")
        child_ancestry = (*ancestry, identity)
        try:
            data = asset_graph_data(params)
        except Exception as exc:
            raise EvaluationError(f"Could not load graph asset '{instance.definition.name}': {exc}") from exc
        interface = dict(params.get("_asset_interface", {}))
        child_entries = [entry for entry in data.get("nodes", ()) if isinstance(entry, dict)]
        child_nodes_by_uid = {
            str(entry.get("uid", "")): entry
            for entry in child_entries
            if str(entry.get("uid", ""))
        }
        child_sources = self._asset_sources(data)
        namespace = f"{instance_uid}/"
        seed = int(params.get("random_seed", 0))

        graph_input_substitutions: dict[str, tuple[str, str]] = {}
        input_by_node = {
            str(entry.get("node", "")): entry
            for entry in interface.get("inputs", ())
            if isinstance(entry, dict)
        }
        new_nodes = dict(snapshot.nodes)
        new_inputs = dict(snapshot.inputs)
        new_nodes.pop(instance_uid, None)
        for key in [key for key in new_inputs if key[0] == instance_uid]:
            new_inputs.pop(key, None)

        for child_uid, entry in child_nodes_by_uid.items():
            if str(entry.get("type", "")) != GRAPH_INPUT_TYPE:
                continue
            public = input_by_node.get(child_uid)
            parent_source = None
            if public is not None:
                parent_source = snapshot.inputs.get((instance_uid, str(public.get("port", ""))))
            if parent_source is not None:
                graph_input_substitutions[child_uid] = parent_source
                continue
            child_params = deepcopy(dict(entry.get("parameters", {})))
            kind = graph_input_kind(child_params)
            virtual_uid = namespace + child_uid
            if kind == "scalar":
                definition = NodeDefinition(
                    type_id="internal.graph_asset_scalar_default",
                    name=f"{instance.definition.name} · {child_params.get('name', 'Input')}",
                    category="Internal",
                    evaluator=None,
                    parameters=(
                        ParameterSpec(
                            "default_value",
                            "Default Value",
                            "float",
                            float(child_params.get("default_value", 0.0)),
                        ),
                    ),
                    output_name="Value",
                    output_kinds=(("Value", "scalar"),),
                    signal_evaluator=_graph_asset_scalar_default,
                    hidden=True,
                )
                new_nodes[virtual_uid] = SnapshotNode(
                    virtual_uid, definition, child_params, (), (), "grayscale"
                )
                graph_input_substitutions[child_uid] = (virtual_uid, "Value")
            elif kind == "material":
                material_definition = self.scene.registry.get("material.pbr")
                material_params = material_definition.default_parameters()
                material_params["material_name"] = str(child_params.get("name", "Default Material"))
                new_nodes[virtual_uid] = SnapshotNode(
                    virtual_uid,
                    material_definition,
                    material_params,
                    tuple(material_definition.inputs),
                    (),
                    material_definition.default_image_kind,
                )
                graph_input_substitutions[child_uid] = (virtual_uid, "Material")
            else:
                child_node = self._asset_snapshot_node(
                    entry,
                    virtual_uid,
                    parameters=child_params,
                    resolved_kind=kind,
                )
                new_nodes[virtual_uid] = child_node
                graph_input_substitutions[child_uid] = (virtual_uid, "Value")

        parameter_entries = {
            (str(entry.get("node", "")), str(entry.get("parameter", ""))): entry
            for entry in interface.get("parameters", ())
            if isinstance(entry, dict)
        }

        for child_uid, entry in child_nodes_by_uid.items():
            child_type = str(entry.get("type", ""))
            if child_type in {GRAPH_INPUT_TYPE, GRAPH_OUTPUT_TYPE}:
                continue
            child_params = deepcopy(dict(entry.get("parameters", {})))
            child_params["_asset_ancestry"] = list(child_ancestry)
            definition = definition_for_serialised_node(self.scene.registry, entry)
            if definition is None:
                definition = self.scene.registry.ensure_placeholder(
                    child_type,
                    entry.get("definition") if isinstance(entry.get("definition"), dict) else None,
                )
            if child_type == GRAPH_INSTANCE_TYPE:
                definition = graph_instance_definition(child_params)
            for (parameter_node, parameter_name), public in parameter_entries.items():
                if parameter_node != child_uid:
                    continue
                external_name = external_parameter_name(str(public.get("id", "")))
                if external_name in params:
                    child_params[parameter_name] = deepcopy(params[external_name])
            for spec in definition.parameters:
                # A nested Graph Instance carries one public Random Seed of its
                # own. Remap that once through the dedicated instance path
                # below; ordinary stochastic nodes use their authored seed
                # parameter (currently named ``seed`` or explicitly tagged).
                if child_type == GRAPH_INSTANCE_TYPE and spec.name == "random_seed":
                    continue
                if not (spec.is_random_seed or spec.name == "seed"):
                    continue
                original = int(child_params.get(spec.name, spec.default))
                child_params[spec.name] = derive_seed(
                    seed, original, f"{child_uid}:{spec.name}"
                )
            if child_type == GRAPH_INSTANCE_TYPE:
                original = int(child_params.get("random_seed", 0))
                child_params["random_seed"] = derive_seed(
                    seed, original, f"{child_uid}:instance"
                )
            virtual_uid = namespace + child_uid
            new_nodes[virtual_uid] = self._asset_snapshot_node(
                entry,
                virtual_uid,
                parameters=child_params,
            )

        def mapped_source(source: tuple[str, str]) -> tuple[str, str]:
            source_uid, source_output = source
            if source_uid in graph_input_substitutions:
                return graph_input_substitutions[source_uid]
            return namespace + source_uid, source_output

        for (target_uid, input_name), source in child_sources.items():
            target_entry = child_nodes_by_uid.get(target_uid)
            if target_entry is None or str(target_entry.get("type", "")) in {
                GRAPH_INPUT_TYPE,
                GRAPH_OUTPUT_TYPE,
            }:
                continue
            new_inputs[(namespace + target_uid, input_name)] = mapped_source(source)

        output_map: dict[str, tuple[str, str]] = {}
        for public in interface.get("outputs", ()):
            if not isinstance(public, dict):
                continue
            source_uid = str(public.get("source_node", ""))
            source_output = str(public.get("source_output", "Image"))
            if not source_uid:
                continue
            output_map[str(public.get("port", ""))] = mapped_source(
                (source_uid, source_output)
            )

        for key, source in list(new_inputs.items()):
            if source[0] != instance_uid:
                continue
            replacement = output_map.get(source[1])
            if replacement is None:
                new_inputs.pop(key, None)
            else:
                new_inputs[key] = replacement
        return GraphSnapshot(new_nodes, new_inputs), output_map

    def _resolve_graph_output_proxy(
        self, snapshot: GraphSnapshot, node_uid: str, output_name: str
    ) -> tuple[str, str]:
        """Forward a public Graph Output preview to its connected source.

        Graph Output is a terminal interface declaration inside an asset, but it
        is still useful to double-click while authoring that asset.  Treat it as
        a transparent preview alias instead of trying to execute a terminal node
        with no evaluator.
        """
        target_uid = str(node_uid)
        target_output = str(output_name or "Image")
        visited: set[str] = set()
        for _pass in range(64):
            node = snapshot.nodes.get(target_uid)
            if node is None or node.definition.type_id != GRAPH_OUTPUT_TYPE:
                return target_uid, target_output
            if target_uid in visited:
                raise EvaluationError("Graph Output preview contains a cycle.")
            visited.add(target_uid)
            source = self._source_reference(snapshot.inputs.get((target_uid, "Value")))
            if source is None:
                raise EvaluationError(
                    f"Graph Output '{node.parameters.get('name', 'Output')}' is not connected."
                )
            target_uid, target_output = source
        raise EvaluationError("Graph Output preview forwarding exceeds the supported depth of 64.")

    def _expand_graph_instances(
        self,
        snapshot: GraphSnapshot,
        node_uid: str,
        output_name: str,
    ) -> tuple[GraphSnapshot, str, str]:
        target_uid = str(node_uid)
        target_output = str(output_name)
        for _pass in range(64):
            if target_uid not in snapshot.nodes:
                break
            # Graph Instance is a structural typed value. Ordinary image
            # execution-order traversal deliberately skips Material and some
            # signal edges, which meant an instance upstream of Material
            # Channels, Send/Receive or Texture Set Output could remain
            # unexpanded. Follow every serialized upstream connection here;
            # the normal evaluator will still execute only the requested image
            # or material channel after expansion.
            upstream_by_target: dict[str, list[str]] = {}
            for (target, _input_name), source_value in snapshot.inputs.items():
                source_ref = self._source_reference(source_value)
                if source_ref is None:
                    continue
                source, _output_name = source_ref
                upstream_by_target.setdefault(str(target), []).append(str(source))
            reachable: list[str] = []
            pending = [target_uid]
            seen: set[str] = set()
            while pending:
                current = pending.pop()
                if current in seen:
                    continue
                seen.add(current)
                reachable.append(current)
                pending.extend(upstream_by_target.get(current, ()))
            instances = [
                uid
                for uid in reachable
                if uid in snapshot.nodes
                and snapshot.nodes[uid].definition.type_id == GRAPH_INSTANCE_TYPE
            ]
            if not instances:
                break
            instance_uid = target_uid if target_uid in instances else instances[0]
            snapshot, output_map = self._expand_one_graph_instance(snapshot, instance_uid)
            if target_uid == instance_uid:
                replacement = output_map.get(target_output)
                if replacement is None:
                    raise EvaluationError(
                        f"Graph asset output '{target_output}' no longer exists. Reload or relink the instance."
                    )
                target_uid, target_output = replacement
        else:
            raise EvaluationError("Graph asset nesting exceeds the supported depth of 64.")
        return snapshot, target_uid, target_output

    @staticmethod
    def _source_reference(value: Any) -> tuple[str, str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value, "Image"
        if isinstance(value, (tuple, list)) and value:
            return str(value[0]), str(value[1]) if len(value) > 1 else "Image"
        return None

    def evaluate(
        self,
        node_uid: str | None,
        width: int,
        height: int,
        *,
        snapshot: GraphSnapshot | None = None,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
        node_activity_callback: Callable[[str, bool, int, int, str], None] | None = None,
        precision: TextureFormat = TextureFormat.RGBA16F,
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
        interactive_node_uid: str | None = None,
        output_name: str = "Image",
        prepare_display: bool = False,
        display_width: int | None = None,
        display_height: int | None = None,
        collect_traces: bool = True,
    ) -> EvaluationResult:
        graph = snapshot or self.snapshot()
        return self.evaluate_snapshot(
            graph,
            node_uid,
            width,
            height,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
            node_activity_callback=node_activity_callback,
            precision=precision,
            colour_space=colour_space,
            time_seconds=time_seconds,
            frame_number=frame_number,
            frame_position=frame_position,
            delta_time=delta_time,
            duration_seconds=duration_seconds,
            normalised_time=normalised_time,
            loop_phase=loop_phase,
            frames_per_second=frames_per_second,
            document_frame_count=document_frame_count,
            loop_start_frame=loop_start_frame,
            loop_end_frame=loop_end_frame,
            render_mode=render_mode,
            interactive_node_uid=interactive_node_uid,
            output_name=output_name,
            prepare_display=prepare_display,
            display_width=display_width,
            display_height=display_height,
            collect_traces=collect_traces,
        )

    def evaluate_snapshot(
        self,
        snapshot: GraphSnapshot,
        node_uid: str | None,
        width: int,
        height: int,
        *,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
        node_activity_callback: Callable[[str, bool, int, int, str], None] | None = None,
        precision: TextureFormat = TextureFormat.RGBA16F,
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
        interactive_node_uid: str | None = None,
        output_name: str = "Image",
        prepare_display: bool = False,
        display_width: int | None = None,
        display_height: int | None = None,
        collect_traces: bool = True,
    ) -> EvaluationResult:
        started = time.perf_counter()
        requested_output = str(output_name or "Image")
        context = RenderContext(
            width=max(int(width), 1),
            height=max(int(height), 1),
            precision=precision,
            colour_space=colour_space,
            time_seconds=float(time_seconds),
            frame_number=max(int(frame_number), 0),
            frame_position=float(frame_number if frame_position is None else frame_position),
            delta_time=max(float(delta_time), 0.0),
            duration_seconds=max(float(duration_seconds), 1e-9),
            normalised_time=float(normalised_time),
            loop_phase=float(loop_phase) % 1.0,
            frames_per_second=max(float(frames_per_second), 1.0),
            document_frame_count=max(int(document_frame_count), 1),
            loop_start_frame=max(int(loop_start_frame), 0),
            loop_end_frame=max(int(loop_end_frame), int(loop_start_frame)),
            render_mode=str(render_mode or "preview"),
        )
        if node_uid is None or node_uid not in snapshot.nodes:
            return EvaluationResult(
                empty_image_for(context),
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                frame_number=context.frame_number,
                time_seconds=context.time_seconds,
                source_width=context.width,
                source_height=context.height,
            )

        try:
            node_uid, requested_output = self._resolve_graph_output_proxy(
                snapshot, str(node_uid), requested_output
            )
            snapshot, node_uid, requested_output = self._expand_graph_instances(
                snapshot, str(node_uid), requested_output
            )
        except (EvaluationError, OSError, ValueError, json.JSONDecodeError) as exc:
            return EvaluationResult(
                empty_image_for(context),
                error=str(exc),
                error_node_uid=str(node_uid),
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                frame_number=context.frame_number,
                time_seconds=context.time_seconds,
                source_width=context.width,
                source_height=context.height,
            )

        # Material graph nodes are structural, lazy graph values rather than
        # nine eagerly evaluated image inputs.  Resolve only the requested
        # channel before the ordinary image execution-order walk begins.
        requested_node = snapshot.nodes[node_uid]
        requested_type = requested_node.definition.type_id
        material_uid: str | None = None
        material_channel: str | None = None
        if requested_type in {
            "material.pbr", "material.blend", "material.override", "material.switch",
            "material.crop", "material.make_it_tile_photo",
        }:
            material_uid = node_uid
            material_channel = requested_output if requested_output in {
                "Base Colour", "Emissive", "Normal", "Height", "Ambient Occlusion",
                "Metallic", "Roughness", "Specular Level", "Opacity",
            } else "Base Colour"
        elif requested_type == "material.channels":
            source_ref = snapshot.inputs.get((node_uid, "Material"))
            material_uid = str(source_ref[0]) if source_ref is not None else None
            material_channel = requested_output if requested_output in {
                "Base Colour", "Emissive", "Normal", "Height", "Ambient Occlusion",
                "Metallic", "Roughness", "Specular Level", "Opacity",
            } else str(requested_node.parameters.get("preview_channel", "Base Colour"))

        if material_channel is not None:
            from ..material_graph import MaterialEvaluationSession

            try:
                session = MaterialEvaluationSession(
                    self, snapshot, context.width, context.height,
                    cancel_check=cancel_check,
                    progress_callback=progress_callback,
                    node_activity_callback=node_activity_callback,
                    precision=precision,
                    colour_space=colour_space,
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
                    collect_traces=collect_traces,
                )
                channel_result = session.evaluate_channel(material_uid, material_channel)
                target_display_width = max(1, min(int(display_width or context.width), context.width))
                target_display_height = max(1, min(int(display_height or context.height), context.height))
                display_rgba = (
                    _prepare_cpu_preview_rgba8(
                        channel_result.image, target_display_width, target_display_height,
                        channel_result.data_kind,
                    )
                    if prepare_display else None
                )
                backend_names = {str(name) for name in channel_result.backends}
                has_gpu = any("GPU" in name for name in backend_names)
                has_cpu = any("CPU" in name or "Hybrid" in name for name in backend_names)
                if has_gpu and has_cpu:
                    backend = "Hybrid"
                elif has_gpu:
                    backend = "GPU"
                elif backend_names == {"Defaults"} or not backend_names:
                    backend = "Defaults"
                else:
                    backend = "CPU"
                material_passes = sum(
                    1 for trace in channel_result.node_traces
                    if str(getattr(trace, "type_id", "")).startswith("material.")
                )
                gpu_cache_stats = self.gpu_cache.stats()
                return EvaluationResult(
                    image=None if prepare_display else channel_result.image,
                    display_rgba=display_rgba,
                    source_width=context.width,
                    source_height=context.height,
                    backend=backend,
                    elapsed_ms=(time.perf_counter() - started) * 1000.0,
                    gpu_nodes=channel_result.gpu_nodes,
                    cpu_nodes=channel_result.cpu_nodes + material_passes,
                    signal_nodes=channel_result.signal_nodes,
                    cache_hits=channel_result.cache_hits,
                    reachable_nodes=max(channel_result.reachable_nodes + material_passes, 1),
                    frame_number=context.frame_number,
                    time_seconds=context.time_seconds,
                    data_kind=channel_result.data_kind,
                    precision=(
                        "32-bit float"
                        if context.precision in {TextureFormat.R32F, TextureFormat.RGBA32F}
                        else "16-bit"
                    ),
                    finalise_ms=channel_result.finalise_ms,
                    gpu_cache_entries=gpu_cache_stats.entries,
                    gpu_cache_bytes=gpu_cache_stats.bytes_used,
                    node_traces=tuple(channel_result.node_traces),
                )
            except EvaluationCancelled:
                raise
            except Exception as exc:
                return EvaluationResult(
                    empty_image_for(context),
                    f"{type(exc).__name__}: {exc}",
                    backend="Error",
                    elapsed_ms=(time.perf_counter() - started) * 1000.0,
                    error_node_uid=node_uid,
                    frame_number=context.frame_number,
                    time_seconds=context.time_seconds,
                    source_width=context.width,
                    source_height=context.height,
                    data_kind={
                        "Base Colour": "color", "Emissive": "color", "Normal": "vector"
                    }.get(material_channel, "grayscale"),
                )

        def cancelled() -> bool:
            return bool(cancel_check and cancel_check())

        def emit_node_activity(uid: str, active: bool, current: int = 0, target: int = 0, message: str = "") -> None:
            if node_activity_callback is None:
                return
            try:
                node_activity_callback(uid, bool(active), int(current), int(target), str(message or ""))
            except Exception:
                return

        queue_wait_visible = False

        def report_queue_wait(wait_ms: float) -> None:
            nonlocal queue_wait_visible
            queue_wait_visible = True
            if context.render_mode == "preview_3d":
                owner = "direct 2D preview or histogram work"
            elif context.render_mode == "histogram":
                owner = "direct 2D preview work"
            elif context.render_mode == "thumbnail":
                owner = "all interactive preview work"
            else:
                owner = "automatic 3D material or histogram work"
            emit_node_activity(
                node_uid,
                True,
                0,
                0,
                f"Waiting for {owner} to yield — {wait_ms / 1000.0:.1f} s",
            )

        gpu_batch = (
            self.gpu_backend.command_batch()
            if self.gpu_backend is not None and self.gpu_backend.available and self.backend_preference != "cpu"
            else nullcontext()
        )
        with self._evaluation_slot(context.render_mode, cancel_check, report_queue_wait) as queue_wait_ms, self._lock, gpu_batch:
            if queue_wait_visible:
                emit_node_activity(node_uid, False, 0, 0, "")
            before_cpu = self.cpu_cache.stats().hits
            before_gpu = self.gpu_cache.stats().hits
            stats = {"gpu": 0, "cpu": 0, "signal": 0, "simulation": 0}
            original_reachable_count = 0
            fused_nodes_total = 0
            fused_passes_total = 0
            simulation_steps_total = 0
            simulation_checkpoint = -1
            finalise_ms = 0.0
            fallbacks: list[str] = []
            conversion_cache: dict[tuple[str, str], ImageResource] = {}
            transients: list[GpuImage] = []
            # GPU dispatches are recorded in a command batch. Publishing their
            # textures into the shared cache before that batch succeeds allows a
            # focus-change cancellation to leave an uninitialised texture cached.
            # Hold new GPU results privately until the complete evaluation has
            # finalised successfully, then commit them atomically while the
            # evaluator lock is still held.
            pending_gpu_cache: dict[str, GpuImage] = {}
            gpu_cache_committed = False
            pinned: dict[str, GraphResource] = {}
            current_uid: str | None = None
            last_gpu_node_uid: str | None = None
            node_traces: list[NodeEvaluationTrace] = []
            if collect_traces and queue_wait_ms >= 0.1:
                node_traces.append(NodeEvaluationTrace(
                    node_uid=node_uid,
                    name="Evaluation queue wait",
                    type_id="internal.evaluation_queue",
                    stage="scheduler wait",
                    backend="Scheduler",
                    state="Waited",
                    elapsed_ms=queue_wait_ms,
                    cache_hit=False,
                    width=context.width,
                    height=context.height,
                    precision=context.precision.value,
                    render_mode=context.render_mode,
                    details=(
                        "Waited behind higher-priority direct preview work."
                        if context.render_mode in {"preview_3d", "histogram", "thumbnail"}
                        else "Waited for lower-priority background preview work to yield."
                    ),
                ))

            try:
                order = self._execution_order(snapshot, node_uid, cancelled)
                original_reachable_count = len(order)
                fusion_chains, fusion_members = self._fusion_plan(snapshot, order)
                if fusion_chains:
                    fused_nodes_total = sum(len(chain) for chain in fusion_chains.values())
                    fused_passes_total = len(fusion_chains)
                    if interactive_node_uid in fusion_members:
                        interactive_node_uid = fusion_members[interactive_node_uid]
                    snapshot = self._apply_fusion_plan(snapshot, fusion_chains)
                    order = self._execution_order(snapshot, node_uid, cancelled)
                reachable = set(order)
                interactive_affected: dict[str, bool] = {}
                if context.render_mode in {"interactive", "thumbnail"}:
                    for candidate_uid in order:
                        affected = (
                            context.render_mode == "thumbnail"
                            or interactive_node_uid is None
                            or candidate_uid == interactive_node_uid
                        )
                        if not affected:
                            candidate = snapshot.nodes[candidate_uid]
                            for input_name in candidate.input_names:
                                source_ref = self._source_reference(
                                    snapshot.inputs.get((candidate_uid, input_name))
                                )
                                if source_ref is not None and interactive_affected.get(source_ref[0], False):
                                    affected = True
                                    break
                        interactive_affected[candidate_uid] = affected

                def node_render_context(candidate_uid: str) -> RenderContext:
                    if context.render_mode == "thumbnail":
                        # Thumbnail jobs are deliberately low-priority and use
                        # the same bounded workloads as interactive drag previews.
                        return replace(context, render_mode="interactive")
                    if context.render_mode != "interactive" or interactive_node_uid is None:
                        return context
                    if interactive_affected.get(candidate_uid, False):
                        return context
                    return replace(context, render_mode="preview")

                remaining_consumers = {uid: 0 for uid in order}
                # A named output of a processor may need to rerun that processor
                # with its original inputs. Keep those immediate upstream
                # resources alive until the downstream named-output consumer has
                # been evaluated. Generator-style multi-output nodes need no
                # protection because they have no image inputs.
                protected_resources: set[str] = set()
                requested_node = snapshot.nodes[node_uid]
                if (
                    requested_output != "Image"
                    and requested_node.definition.named_output_parameter is not None
                    and requested_node.input_names
                ):
                    for requested_input in requested_node.input_names:
                        requested_ref = self._source_reference(snapshot.inputs.get((node_uid, requested_input)))
                        if requested_ref is not None and requested_ref[0] in reachable:
                            protected_resources.add(requested_ref[0])
                for target_uid in order:
                    target_node = snapshot.nodes[target_uid]
                    for input_name in target_node.input_names:
                        source_ref = self._source_reference(snapshot.inputs.get((target_uid, input_name)))
                        source_uid = source_ref[0] if source_ref else None
                        if source_uid in reachable:
                            remaining_consumers[source_uid] += 1
                        if source_ref is None or source_ref[1] == "Image" or source_uid not in snapshot.nodes:
                            continue
                        source_node = snapshot.nodes[source_uid]
                        if source_node.definition.named_output_parameter is None or not source_node.input_names:
                            continue
                        for source_input in source_node.input_names:
                            upstream_ref = self._source_reference(snapshot.inputs.get((source_uid, source_input)))
                            if upstream_ref is not None and upstream_ref[0] in reachable:
                                protected_resources.add(upstream_ref[0])

                resources: dict[str, GraphResource] = {}
                signatures: dict[str, str] = {}
                dynamic: dict[str, bool] = {}

                for uid in order:
                    current_uid = uid
                    if cancelled():
                        raise EvaluationCancelled()
                    node = snapshot.nodes[uid]
                    node_context = node_render_context(uid)
                    node_started = time.perf_counter() if collect_traces else 0.0
                    node_cache_hit = False
                    node_state = "Computed"
                    node_backend = ""
                    node_details = ""
                    resolved: dict[str, tuple[GraphResource, str, str]] = {}
                    input_signatures: list[tuple[str, str]] = []
                    upstream_dynamic = False
                    for input_name in node.input_names:
                        if node.definition.type_id == "material.channels" and input_name == "Material":
                            continue
                        source_ref = self._source_reference(snapshot.inputs.get((uid, input_name)))
                        if source_ref is None:
                            continue
                        source_uid, source_output = source_ref
                        source_resource = resources[source_uid]
                        source_signature = signatures[source_uid]
                        if (
                            isinstance(source_resource, (CpuImage, GpuImage))
                            and source_output != "Image"
                            and snapshot.nodes[source_uid].definition.type_id != "graph.receive"
                        ):
                            source_resource, source_signature = self._extract_named_output(
                                snapshot,
                                resources,
                                signatures,
                                snapshot.nodes[source_uid],
                                source_resource,
                                source_signature,
                                source_output,
                                node_render_context(source_uid),
                                cancelled,
                                stats,
                                fallbacks,
                                conversion_cache,
                                transients,
                                pending_gpu_cache,
                            )
                        elif isinstance(source_resource, SignalValue):
                            source_signature = hashlib.blake2b(
                                f"{source_signature}:output:{source_output}".encode(), digest_size=20
                            ).hexdigest()
                        resolved[input_name] = (source_resource, source_output, source_signature)
                        input_signatures.append((input_name, source_signature))
                        upstream_dynamic = upstream_dynamic or dynamic.get(source_uid, False)

                    direct_dynamic = bool(
                        node.definition.uses_time
                        or node.definition.is_stateful
                        or node.definition.type_id == "material.channels"
                        or (node.definition.gpu_spec is not None and node.definition.gpu_spec.uses_time)
                    )
                    node_dynamic = direct_dynamic or upstream_dynamic
                    dynamic[uid] = node_dynamic

                    passthrough = bool(
                        node.definition.type_id == "graph.reroute"
                        or node.definition.type_id == "graph.receive"
                        or node.parameters.get("_bypassed", False)
                    )
                    passthrough_input = (
                        node.definition.inputs[0]
                        if passthrough
                        and len(node.definition.inputs) == 1
                        and len(node.definition.output_names) == 1
                        else None
                    )
                    passthrough_value = resolved.get(passthrough_input) if passthrough_input else None

                    if node.definition.type_id == "material.channels":
                        result, signature, channel_result = self._material_channel_resource(
                            snapshot, node, "Base Colour", node_context, cancel_check,
                            progress_callback, node_activity_callback, collect_traces,
                        )
                        material_passes = sum(
                            1 for trace in channel_result.node_traces
                            if str(getattr(trace, "type_id", "")).startswith("material.")
                        )
                        stats["cpu"] += max(material_passes, 1)
                        stats["gpu"] += int(channel_result.gpu_nodes)
                        stats["signal"] += int(channel_result.signal_nodes)
                        node_backend = "Material resolver"
                        node_state = "Resolved channel"
                        node_details = "Resolved Base Colour lazily from the connected Material graph."
                        if collect_traces:
                            node_traces.extend(channel_result.node_traces)
                    elif passthrough_value is not None:
                        source_resource, source_output, source_signature = passthrough_value
                        signature = source_signature
                        node_backend = "Pass-through"
                        node_state = "Bypassed" if node.parameters.get("_bypassed", False) else "Reroute"
                        node_cache_hit = True
                        node_details = "Reused the connected upstream resource without processing."
                        if isinstance(source_resource, SignalValue):
                            passthrough_output_name = node.definition.output_names[0]
                            result = SignalValue(
                                {passthrough_output_name: source_resource.output(source_output)},
                                source_resource.kind,
                                signature,
                            )
                        else:
                            result = source_resource
                    else:
                        direct_flipbook_source = self._direct_flipbook_output_source(snapshot, node)
                        backend_key = (
                            "signal" if node.definition.is_signal_node
                            else "cpu" if direct_flipbook_source is not None
                            else self._backend_for(node.definition)
                        )
                        node_backend = {"gpu": "GPU", "cpu": "CPU", "signal": "Signal"}.get(backend_key, backend_key.title())
                        signature = self._signature(node, input_signatures, node_context, backend_key, node_dynamic)

                        if node.definition.is_stateful:
                            node_state = "State step"
                            node_details = f"Stateful evaluation at frame {node_context.frame_number}."
                            image_inputs, effective_parameters = self._materialise_node_inputs(node, resolved)
                            virtual = SnapshotNode(
                                node.uid, node.definition, effective_parameters, node.input_names,
                                node.parameter_ports, node.resolved_kind,
                            )
                            logical_format, output_precision, data_kind = self._output_spec_for(
                                virtual, image_inputs, node_context
                            )
                            revision = self._simulation_revision(snapshot, node.uid)
                            signature = hashlib.blake2b(
                                f"simulation:{revision}:{node.uid}:{node_context.frame_number}:{backend_key}".encode(),
                                digest_size=20,
                            ).hexdigest()

                            def frame_provider(frame: int):
                                return self._simulation_frame_inputs(
                                    snapshot, node, frame, node_context, cancel_check, progress_callback, node_activity_callback,
                                    interactive_node_uid
                                )

                            def simulation_progress(current: int, target: int, name: str) -> None:
                                if progress_callback is not None:
                                    progress_callback(current, target, name)
                                emit_node_activity(node.uid, True, current, target, name)

                            emit_node_activity(node.uid, True, 0, 0, node.definition.name)
                            try:
                                try:
                                    simulation = self.simulations.evaluate(
                                        definition=node.definition,
                                        node_uid=node.uid,
                                        revision=revision,
                                        target_frame=node_context.frame_number,
                                        current_inputs=image_inputs,
                                        current_parameters=effective_parameters,
                                        context=node_context,
                                        backend_key=backend_key,
                                        logical_format=logical_format,
                                        frame_provider=frame_provider,
                                        cpu_backend=self.cpu_backend,
                                        gpu_backend=self.gpu_backend,
                                        cancel_check=cancelled,
                                        progress_callback=simulation_progress,
                                    )
                                except BackendCancelled as exc:
                                    raise EvaluationCancelled() from exc
                                except Exception as exc:
                                    if backend_key != "gpu":
                                        raise
                                    fallbacks.append(f"{node.definition.name}: {type(exc).__name__}")
                                    self.simulations.clear(node.uid)
                                    simulation = self.simulations.evaluate(
                                        definition=node.definition,
                                        node_uid=node.uid,
                                        revision=revision,
                                        target_frame=node_context.frame_number,
                                        current_inputs=image_inputs,
                                        current_parameters=effective_parameters,
                                        context=node_context,
                                        backend_key="cpu",
                                        logical_format=logical_format,
                                        frame_provider=frame_provider,
                                        cpu_backend=self.cpu_backend,
                                        gpu_backend=self.gpu_backend,
                                        cancel_check=cancelled,
                                        progress_callback=simulation_progress,
                                    )
                            finally:
                                emit_node_activity(node.uid, False, 0, 0, "")
                            result = simulation.output
                            result.data_kind = data_kind
                            result.precision = output_precision
                            stats[simulation.backend] += 1
                            node_backend = simulation.backend.upper()
                            if simulation.backend == "gpu":
                                last_gpu_node_uid = node.uid
                            stats["simulation"] += 1
                            simulation_steps_total += simulation.steps
                            simulation_checkpoint = max(
                                simulation_checkpoint, simulation.restored_checkpoint
                            )
                        else:
                            cache = self.cpu_cache if backend_key in ("cpu", "signal") else self.gpu_cache
                            result = (
                                pending_gpu_cache.get(signature)
                                if backend_key == "gpu"
                                else None
                            )
                            if result is None:
                                result = cache.get(signature)
                            node_cache_hit = result is not None
                            if node_cache_hit:
                                node_state = "Cached"
                                node_details = "Upstream signature and node parameters are unchanged."
                            if result is None:
                                if backend_key == "signal":
                                    result = self._compute_signal_node(node, resolved, node_context, signature)
                                    stats["signal"] += 1
                                    self.cpu_cache.put(signature, result)
                                else:
                                    image_inputs, effective_parameters = self._materialise_node_inputs(node, resolved)
                                    virtual = SnapshotNode(
                                        node.uid, node.definition, effective_parameters, node.input_names,
                                        node.parameter_ports, node.resolved_kind,
                                    )
                                    if direct_flipbook_source is not None:
                                        result = self._compute_direct_flipbook_decode(
                                            snapshot, virtual, direct_flipbook_source, node_context, signature,
                                            stats, fallbacks, cancel_check,
                                        )
                                        self.cpu_cache.put(signature, result)
                                    else:
                                        emit_node_activity(node.uid, True, 0, 0, node.definition.name)
                                        try:
                                            result, signature = self._compute_node(
                                                virtual, image_inputs, input_signatures, node_context, backend_key,
                                                signature, stats, fallbacks, conversion_cache, transients,
                                                pending_gpu_cache, cancelled,
                                                lambda current, target: emit_node_activity(
                                                    node.uid, True, current, target, node.definition.name
                                                ),
                                            )
                                        finally:
                                            emit_node_activity(node.uid, False, 0, 0, "")
                                        if isinstance(result, GpuImage):
                                            last_gpu_node_uid = node.uid
                    if node.definition.type_id == "internal.fused_adjustments":
                        fused_names = tuple(node.parameters.get("_fusion_names", ()))
                        node_state = "Cached fused pass" if node_cache_hit else "Fused pass"
                        node_details = (
                            f"Fused one-pass chain ({len(fused_names)} nodes): " + " → ".join(str(name) for name in fused_names)
                        )
                    if collect_traces:
                        trace_key = (uid, node_context.width, node_context.height, node_backend, node_context.render_mode)
                        previous_signature = self._last_node_signatures.get(trace_key)
                        if not node_cache_hit and not node_details:
                            if previous_signature is None:
                                node_details = "First evaluation for this resolution and render mode."
                            elif previous_signature != signature:
                                node_details = (
                                    "Animation/state changed." if node_dynamic
                                    else "Node parameters or upstream content changed."
                                )
                            else:
                                node_details = "Signature unchanged, but the cached resource was unavailable or evicted."
                        self._last_node_signatures[trace_key] = signature
                        if node.definition.type_id == "terrain.hydraulic_erosion":
                            prefix = "Draft" if node_context.render_mode == "interactive" else "Preview"
                            node_details += (
                                f" {prefix} workload: {int(node.parameters.get('preview_iterations', 10))} erosion / "
                                f"{int(node.parameters.get('preview_drainage_iterations', 48))} drainage passes."
                            )
                        elif node.definition.type_id == "terrain.thermal_erosion":
                            prefix = "Draft" if node_context.render_mode == "interactive" else "Preview"
                            node_details += f" {prefix} workload: {int(node.parameters.get('preview_iterations', 24))} iterations."
                        elif node.definition.type_id == "terrain.flow_accumulation":
                            prefix = "Draft" if node_context.render_mode == "interactive" else "Preview"
                            node_details += f" {prefix} workload: {int(node.parameters.get('preview_iterations', 32))} iterations."
                        node_width = int(getattr(result, "width", node_context.width if not isinstance(result, SignalValue) else 0))
                        node_height = int(getattr(result, "height", node_context.height if not isinstance(result, SignalValue) else 0))
                        node_traces.append(NodeEvaluationTrace(
                            node_uid=uid,
                            name=node.definition.name,
                            type_id=node.definition.type_id,
                            backend=node_backend or ("Signal" if isinstance(result, SignalValue) else "CPU"),
                            state=node_state,
                            elapsed_ms=(time.perf_counter() - node_started) * 1000.0,
                            cache_hit=node_cache_hit,
                            width=node_width,
                            height=node_height,
                            precision=str(getattr(result, "precision", "")),
                            data_kind=str(getattr(result, "data_kind", getattr(result, "kind", ""))),
                            bytes_used=int(getattr(result, "bytes_used", 0)),
                            render_mode=node_context.render_mode,
                            details=node_details,
                        ))
                    result.pin()
                    pinned[uid] = result
                    resources[uid] = result
                    signatures[uid] = signature

                    for input_name in node.input_names:
                        source_ref = self._source_reference(snapshot.inputs.get((uid, input_name)))
                        source_uid = source_ref[0] if source_ref else None
                        if source_uid not in remaining_consumers:
                            continue
                        remaining_consumers[source_uid] -= 1
                        if (
                            remaining_consumers[source_uid] == 0
                            and source_uid != node_uid
                            and source_uid not in protected_resources
                        ):
                            source_resource = pinned.pop(source_uid, None)
                            if source_resource is not None:
                                source_resource.unpin()
                            resources.pop(source_uid, None)

                if cancelled():
                    raise EvaluationCancelled()
                final_resource = resources[node_uid]
                final_signature = signatures[node_uid]
                if (
                    isinstance(final_resource, (CpuImage, GpuImage))
                    and requested_output != "Image"
                    and snapshot.nodes[node_uid].definition.type_id != "graph.receive"
                ):
                    final_resource, final_signature = self._extract_named_output(
                        snapshot, resources, signatures, snapshot.nodes[node_uid], final_resource,
                        final_signature, requested_output, node_render_context(node_uid), cancelled, stats, fallbacks,
                        conversion_cache, transients, pending_gpu_cache,
                    )
                signal_value: float | tuple[float, ...] | None = None
                display_rgba: np.ndarray | None = None
                image: np.ndarray | None = None
                target_display_width = max(1, min(int(display_width or context.width), context.width))
                target_display_height = max(1, min(int(display_height or context.height), context.height))
                final_kind = "grayscale" if isinstance(final_resource, SignalValue) else getattr(
                    final_resource, "data_kind", snapshot.nodes[node_uid].resolved_kind
                )
                if isinstance(final_resource, SignalValue):
                    raw = final_resource.output(requested_output)
                    signal_value = raw
                    scalar = float(raw[0]) if isinstance(raw, tuple) and raw else float(raw)
                    if prepare_display:
                        value = np.uint8(min(max(scalar, 0.0), 1.0) * 255.0 + 0.5)
                        display_rgba = np.empty((target_display_height, target_display_width, 4), dtype=np.uint8)
                        display_rgba[..., 0:3] = value
                        display_rgba[..., 3] = 255
                    else:
                        image = np.full(
                            (context.height, context.width, 4),
                            (scalar, scalar, scalar, 1.0),
                            dtype=np.float32,
                        )
                    used = "Signal"
                else:
                    final_node = snapshot.nodes[node_uid]
                    waiting_on_gpu = isinstance(final_resource, GpuImage) or "gpu" in final_resource.provenance
                    final_activity_uids: list[str] = []
                    if waiting_on_gpu:
                        producer_uid = last_gpu_node_uid
                        producer = snapshot.nodes.get(producer_uid or "")
                        producer_name = producer.definition.name if producer is not None else "queued GPU work"
                        if producer_uid == node_uid and final_node.definition.type_id.startswith("output."):
                            wait_description = "the completed GPU branch"
                        elif producer_uid == node_uid:
                            wait_description = "its GPU work"
                        elif producer is not None:
                            wait_description = f"{producer_name} GPU work"
                        else:
                            wait_description = "queued GPU work"
                        if prepare_display:
                            finalise_message = (
                                f"Finalising {final_node.definition.name} — waiting for {wait_description}, then preparing "
                                f"{target_display_width} × {target_display_height} display pixels from the "
                                f"{context.width} × {context.height} graph texture"
                            )
                        else:
                            finalise_message = (
                                f"Finalising {final_node.definition.name} — waiting for {wait_description} and reading back "
                                f"{context.width} × {context.height} texture"
                            )
                        if producer_uid is not None and producer_uid != node_uid:
                            emit_node_activity(
                                producer_uid, True, 0, 0,
                                f"{producer_name} — GPU result pending for {final_node.definition.name}",
                            )
                            final_activity_uids.append(producer_uid)
                        emit_node_activity(node_uid, True, 0, 0, finalise_message)
                        final_activity_uids.append(node_uid)
                    finalise_started = time.perf_counter()
                    try:
                        if cancelled():
                            raise EvaluationCancelled()
                        if prepare_display:
                            if isinstance(final_resource, GpuImage) and self.gpu_backend is not None:
                                display_rgba = self.gpu_backend.prepare_preview_rgba8(
                                    final_resource,
                                    target_display_width,
                                    target_display_height,
                                    final_kind,
                                    cancel_check=cancel_check,
                                )
                            else:
                                cpu = self._to_cpu(final_resource, conversion_cache)
                                display_rgba = _prepare_cpu_preview_rgba8(
                                    cpu.array, target_display_width, target_display_height, final_kind
                                )
                        else:
                            cpu = self._to_cpu(final_resource, conversion_cache)
                            image = np.clip(cpu.array, 0.0, 1.0).astype(np.float32, copy=False)
                    finally:
                        finalise_ms = (time.perf_counter() - finalise_started) * 1000.0
                        for activity_uid in reversed(final_activity_uids):
                            emit_node_activity(activity_uid, False, 0, 0, "")
                    provenance = final_resource.provenance
                    if provenance == frozenset({"gpu", "cpu"}):
                        used = "Hybrid" if stats["gpu"] or stats["cpu"] else "Hybrid (cached)"
                    elif "gpu" in provenance:
                        used = "GPU" if stats["gpu"] else "GPU (cached)"
                    else:
                        used = "CPU" if stats["cpu"] else "CPU (cached)"
                if collect_traces and finalise_ms >= 0.01:
                    node_traces.append(NodeEvaluationTrace(
                        node_uid=node_uid,
                        name=f"{snapshot.nodes[node_uid].definition.name} finalise / readback",
                        type_id="internal.finalise_readback",
                        stage="finalise / readback",
                        backend=(
                            "GPU display preparation → RGBA8"
                            if prepare_display and isinstance(final_resource, GpuImage)
                            else "CPU display preparation"
                            if prepare_display
                            else "GPU → CPU"
                            if isinstance(final_resource, GpuImage) or "gpu" in getattr(final_resource, "provenance", ())
                            else "CPU"
                        ),
                        state="Completed",
                        elapsed_ms=finalise_ms,
                        cache_hit=False,
                        width=target_display_width if prepare_display else context.width,
                        height=target_display_height if prepare_display else context.height,
                        precision="8-bit display" if prepare_display else str(getattr(final_resource, "precision", "")),
                        data_kind=str(final_kind),
                        bytes_used=(
                            int(display_rgba.nbytes) if display_rgba is not None
                            else int(getattr(final_resource, "bytes_used", 0))
                        ),
                        render_mode=context.render_mode,
                        details=(
                            f"Prepared a view-sized RGBA8 image from the {context.width} × {context.height} graph result."
                            if prepare_display
                            else "Read back the complete graph result for full-resolution use."
                        ),
                    ))
                # Only now is the frame complete and safe to reuse. The surrounding
                # command_batch context will submit before the evaluator lock is
                # released, so no other evaluation can observe these entries early.
                for pending_signature, pending_image in pending_gpu_cache.items():
                    self.gpu_cache.put(pending_signature, pending_image)
                gpu_cache_committed = True

                elapsed = (time.perf_counter() - started) * 1000.0
                hits = self.cpu_cache.stats().hits - before_cpu + self.gpu_cache.stats().hits - before_gpu
                final_precision = "32-bit float" if isinstance(final_resource, SignalValue) else getattr(final_resource, "precision", "16-bit")
                gpu_cache_stats = self.gpu_cache.stats()
                dynamic_count = sum(1 for uid in order if dynamic.get(uid, False))
                static_count = max(len(order) - dynamic_count, 0)
                return EvaluationResult(
                    image=image,
                    display_rgba=display_rgba,
                    source_width=context.width,
                    source_height=context.height,
                    backend=used,
                    elapsed_ms=elapsed,
                    gpu_nodes=stats["gpu"],
                    cpu_nodes=stats["cpu"],
                    signal_nodes=stats["signal"],
                    cache_hits=hits,
                    fallback_nodes=tuple(dict.fromkeys(fallbacks)),
                    reachable_nodes=original_reachable_count or len(order),
                    signal_value=signal_value,
                    frame_number=context.frame_number,
                    time_seconds=context.time_seconds,
                    data_kind=final_kind,
                    precision=final_precision,
                    simulation_steps=simulation_steps_total,
                    simulation_nodes=stats["simulation"],
                    simulation_checkpoint=simulation_checkpoint,
                    finalise_ms=finalise_ms,
                    queue_wait_ms=float(queue_wait_ms),
                    dynamic_nodes=dynamic_count,
                    static_nodes=static_count,
                    gpu_cache_entries=gpu_cache_stats.entries,
                    gpu_cache_bytes=gpu_cache_stats.bytes_used,
                    fused_nodes=fused_nodes_total,
                    fused_passes=fused_passes_total,
                    node_traces=tuple(node_traces),
                )
            except EvaluationCancelled:
                raise
            except Exception as exc:
                elapsed = (time.perf_counter() - started) * 1000.0
                return EvaluationResult(
                    empty_image_for(context),
                    f"{type(exc).__name__}: {exc}",
                    backend="Error",
                    elapsed_ms=elapsed,
                    gpu_nodes=stats["gpu"],
                    cpu_nodes=stats["cpu"],
                    signal_nodes=stats["signal"],
                    fallback_nodes=tuple(dict.fromkeys(fallbacks)),
                    error_node_uid=current_uid,
                    frame_number=context.frame_number,
                    time_seconds=context.time_seconds,
                    source_width=context.width,
                    source_height=context.height,
                    simulation_steps=simulation_steps_total,
                    simulation_nodes=stats["simulation"],
                    simulation_checkpoint=simulation_checkpoint,
                    fused_nodes=fused_nodes_total,
                    fused_passes=fused_passes_total,
                    node_traces=tuple(node_traces),
                )
            finally:
                for resource in reversed(tuple(pinned.values())):
                    resource.unpin()
                if not gpu_cache_committed:
                    released_pending: set[int] = set()
                    for image in pending_gpu_cache.values():
                        identity = id(image)
                        if identity in released_pending:
                            continue
                        released_pending.add(identity)
                        image.release()
                for image in transients:
                    image.release()

    def _execution_order(
        self,
        snapshot: GraphSnapshot,
        target_uid: str,
        cancelled: Callable[[], bool],
    ) -> list[str]:
        state: dict[str, int] = {}
        order: list[str] = []
        stack: list[tuple[str, bool]] = [(target_uid, False)]
        while stack:
            if cancelled():
                raise EvaluationCancelled()
            uid, expanded = stack.pop()
            current = state.get(uid, 0)
            if expanded:
                if current == 2:
                    continue
                state[uid] = 2
                order.append(uid)
                continue
            if current == 2:
                continue
            if current == 1:
                raise EvaluationError("Cycle detected in node graph")
            if uid not in snapshot.nodes:
                raise EvaluationError(f"Connection references missing node {uid}")
            state[uid] = 1
            stack.append((uid, True))
            node = snapshot.nodes[uid]
            dependencies: list[str] = []
            for input_name in node.input_names:
                # Material Channels resolves its structural Material input on
                # demand. Traversing it here would eagerly execute every PBR
                # branch and attempt to treat a Material value as an image.
                if node.definition.type_id == "material.channels" and input_name == "Material":
                    continue
                source_ref = self._source_reference(snapshot.inputs.get((uid, input_name)))
                source_uid = source_ref[0] if source_ref else None
                if source_uid is None:
                    continue
                source_state = state.get(source_uid, 0)
                if source_state == 1:
                    raise EvaluationError("Cycle detected in node graph")
                if source_state != 2:
                    dependencies.append(source_uid)
            for source_uid in reversed(dependencies):
                stack.append((source_uid, False))
        return order

    @staticmethod
    def _direct_flipbook_output_source(snapshot: GraphSnapshot, node: SnapshotNode) -> SnapshotNode | None:
        if node.definition.type_id != "animation.flipbook_decode":
            return None
        source_ref = GraphEvaluator._source_reference(snapshot.inputs.get((node.uid, "Sheet")))
        if source_ref is None:
            return None
        source = snapshot.nodes.get(source_ref[0])
        if source is None or source.definition.type_id != "output.flipbook":
            return None
        return source

    def _compute_direct_flipbook_decode(
        self,
        snapshot: GraphSnapshot,
        node: SnapshotNode,
        flipbook_output: SnapshotNode,
        context: RenderContext,
        signature: str,
        stats: dict[str, int],
        fallbacks: list[str],
        cancel_check: Callable[[], bool] | None,
    ) -> CpuImage:
        """Decode a directly connected Flipbook Generator without materialising its atlas.

        Flipbook Generator is a timeline sampler rather than a normal single-frame
        image operation. When it feeds Flipbook Decode directly, evaluate the
        selected source sample at the decoder's current phase. Imported atlases
        still use the ordinary CPU/WGSL cell-decoding implementation.
        """
        image_ref = self._source_reference(snapshot.inputs.get((flipbook_output.uid, "Image")))
        if image_ref is None or image_ref[0] not in snapshot.nodes:
            return CpuImage(
                empty_image_for(context),
                TextureFormat.RGBA16F,
                signature,
                frozenset({"cpu"}),
                node.resolved_kind,
                "16-bit",
            )

        from ..document import DocumentSettings

        document = DocumentSettings(
            width=context.width,
            height=context.height,
            preview_max_dimension=max(context.width, context.height),
            working_precision="32-bit float" if context.precision is TextureFormat.RGBA32F else "16-bit float",
            colour_space=context.colour_space,
            frames_per_second=context.frames_per_second,
            duration_seconds=context.document_frame_count / max(context.frames_per_second, 1.0),
            loop_start_frame=context.loop_start_frame,
            loop_end_frame=context.loop_end_frame,
        )
        document.normalise()
        samples = sample_positions_from_node(document, flipbook_output.parameters)
        if not samples:
            raise EvaluationError("The connected Flipbook Generator contains no timeline samples")

        params = node.parameters
        if bool(params.get("inherit_layout", True)):
            start = 0
            count = len(samples)
        else:
            start = min(max(int(params.get("start_frame", 0)), 0), len(samples) - 1)
            available = max(len(samples) - start, 1)
            count = available if bool(params.get("use_full_grid", True)) else min(
                max(int(params.get("frame_count", available)), 1), available
            )
        selection_params = dict(params)
        if bool(params.get("inherit_layout", True)) and "__input_Phase" not in params:
            # A direct Flipbook Generator already defines samples across a timeline
            # range, so its decoder follows the document loop rather than treating
            # those procedural samples as an imported fixed-FPS atlas.
            selection_params["playback_mode"] = "Fit to Document Loop"
        relative, _phase, _mode = flipbook_relative_index(selection_params, context, count)
        sample_position = float(samples[start + relative])

        if cancel_check and cancel_check():
            raise EvaluationCancelled()
        frame_number = min(max(int(sample_position), 0), document.last_frame)
        nested = self.evaluate_snapshot(
            snapshot,
            image_ref[0],
            context.width,
            context.height,
            cancel_check=cancel_check,
            precision=context.precision,
            colour_space=context.colour_space,
            time_seconds=document.time_for_frame(sample_position),
            frame_number=frame_number,
            frame_position=sample_position,
            delta_time=1.0 / document.frames_per_second,
            duration_seconds=document.duration_seconds,
            normalised_time=document.normalised_time_for_frame(sample_position),
            loop_phase=document.loop_phase_for_frame(sample_position),
            frames_per_second=document.frames_per_second,
            document_frame_count=document.frame_count,
            loop_start_frame=document.loop_start_frame,
            loop_end_frame=document.loop_end_frame,
            render_mode=context.render_mode,
        )
        if nested.error:
            raise EvaluationError(nested.error)
        stats["gpu"] += nested.gpu_nodes
        stats["cpu"] += nested.cpu_nodes + 1
        stats["signal"] += nested.signal_nodes
        fallbacks.extend(nested.fallback_nodes)
        provenance = frozenset({"cpu"})
        if "GPU" in nested.backend or "Hybrid" in nested.backend:
            provenance = frozenset({"gpu", "cpu"})
        return CpuImage(
            np.ascontiguousarray(nested.image, dtype=np.float32),
            TextureFormat.RGBA32F if nested.precision == "32-bit float" else TextureFormat.RGBA16F,
            signature,
            provenance,
            nested.data_kind,
            nested.precision,
        )

    def _compute_signal_node(
        self,
        node: SnapshotNode,
        resolved: dict[str, tuple[GraphResource, str, str]],
        context: RenderContext,
        signature: str,
    ) -> SignalValue:
        evaluator = node.definition.signal_evaluator
        if evaluator is None:
            raise EvaluationError(f"{node.definition.name} has no signal evaluator")
        signal_inputs: dict[str, float | tuple[float, ...]] = {}
        for input_name, (resource, source_output, _signature) in resolved.items():
            if not isinstance(resource, SignalValue):
                raise EvaluationError(f"{node.definition.name}.{input_name} requires a scalar/vector signal")
            signal_inputs[input_name] = resource.output(source_output)
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
        raw = evaluator(signal_inputs, node.parameters, eval_context)
        if isinstance(raw, dict):
            clean = {str(name): value for name, value in raw.items()}
            kind = node.definition.output_kind(node.definition.output_names[0])
            return SignalValue(clean, kind, signature)
        kind = node.definition.output_kind(node.definition.output_names[0])
        return SignalValue(raw, kind, signature)

    def _material_channel_resource(
        self,
        snapshot: GraphSnapshot,
        node: SnapshotNode,
        channel: str,
        context: RenderContext,
        cancel_check: Callable[[], bool] | None,
        progress_callback: Callable[[int, int, str], None] | None = None,
        node_activity_callback: Callable[[str, bool, int, int, str], None] | None = None,
        collect_traces: bool = True,
    ) -> tuple[CpuImage, str, Any]:
        from ..material_graph import MATERIAL_CHANNEL_KINDS, MaterialEvaluationSession

        source_ref = self._source_reference(snapshot.inputs.get((node.uid, "Material")))
        material_uid = source_ref[0] if source_ref is not None else None
        selected = channel if channel in MATERIAL_CHANNEL_KINDS else "Base Colour"
        session = MaterialEvaluationSession(
            self,
            snapshot,
            context.width,
            context.height,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
            node_activity_callback=node_activity_callback,
            precision=context.precision,
            colour_space=context.colour_space,
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
            collect_traces=collect_traces,
        )
        channel_result = session.evaluate_channel(material_uid, selected)
        revision = self.branch_revision(snapshot, material_uid) if material_uid in snapshot.nodes else "default"
        signature_payload = (
            f"material-channel:{revision}:{node.uid}:{selected}:{context.width}x{context.height}:"
            f"{context.precision.value}:{context.colour_space}:{context.animation_signature}:{context.render_mode}"
        )
        signature = hashlib.blake2b(signature_payload.encode("utf-8"), digest_size=20).hexdigest()
        logical_format = (
            TextureFormat.R16F if channel_result.data_kind == "grayscale" else TextureFormat.RGBA16F
        )
        precision_name = "32-bit float" if context.precision in {TextureFormat.R32F, TextureFormat.RGBA32F} else "16-bit"
        resource = CpuImage(
            np.ascontiguousarray(channel_result.image, dtype=np.float32),
            logical_format,
            signature,
            frozenset({"cpu"}),
            channel_result.data_kind,
            precision_name,
        )
        return resource, signature, channel_result

    def _extract_named_output(
        self,
        snapshot: GraphSnapshot,
        resources: dict[str, GraphResource],
        signatures: dict[str, str],
        source_node: SnapshotNode,
        source_resource: ImageResource,
        source_signature: str,
        output_name: str,
        context: RenderContext,
        cancel_check: Callable[[], bool] | None,
        stats: dict[str, int],
        fallbacks: list[str],
        conversion_cache: dict[tuple[str, str], ImageResource],
        transients: list[GpuImage],
        pending_gpu_cache: dict[str, GpuImage],
    ) -> tuple[ImageResource, str]:
        if source_node.definition.type_id == "material.channels":
            if output_name == "Base Colour":
                return source_resource, source_signature
            resource, signature, channel_result = self._material_channel_resource(
                snapshot, source_node, output_name, context, cancel_check,
                collect_traces=False,
            )
            material_passes = sum(
                1 for trace in channel_result.node_traces
                if str(getattr(trace, "type_id", "")).startswith("material.")
            )
            stats["cpu"] += max(material_passes, 1)
            stats["gpu"] += int(channel_result.gpu_nodes)
            stats["signal"] += int(channel_result.signal_nodes)
            return resource, signature

        channel_map = {"R": "Red", "G": "Green", "B": "Blue", "A": "Alpha"}
        selected_output = channel_map.get(output_name, output_name)
        definition = source_node.definition

        selector_parameter: str | None = None
        selector_value: Any | None = None
        input_names = source_node.input_names
        resolved_kind = definition.output_kind(output_name)
        if definition.type_id == "convert.extract_channel" and selected_output in ("Red", "Green", "Blue", "Alpha"):
            selector_parameter = "channel"
            selector_value = selected_output
            input_names = ("Image",)
            resolved_kind = "grayscale"
        elif definition.named_output_parameter is not None:
            selector_parameter = definition.named_output_parameter
            selector_value = definition.named_output_value(output_name)
            if selector_value is None:
                return source_resource, source_signature
        else:
            return source_resource, source_signature

        signature = hashlib.sha256(
            f"{source_signature}:output:{output_name}:{selector_value}:{self.backend_preference}".encode()
        ).hexdigest()
        backend_key = self._backend_for(definition)
        cache = self.gpu_cache if backend_key == "gpu" else self.cpu_cache
        cached = pending_gpu_cache.get(signature) if backend_key == "gpu" else None
        if cached is None:
            cached = cache.get(signature)
        if isinstance(cached, (CpuImage, GpuImage)):
            return cached, signature
        params = dict(source_node.parameters)
        params[selector_parameter] = selector_value
        virtual = SnapshotNode(
            source_node.uid + ":" + output_name, definition, params, tuple(input_names), (), resolved_kind
        )
        input_resources: dict[str, ImageResource] = {}
        input_signatures: list[tuple[str, str]] = []
        if definition.type_id == "convert.extract_channel" and isinstance(source_resource, (CpuImage, GpuImage)):
            # Extract Channel is a special pass-through node whose base result
            # is the original image. Reuse that resource for the selected
            # channel rather than recursively looking up its source.
            input_resources["Image"] = source_resource
            input_signatures.append(("Image", source_signature))
        else:
            # Multi-output processors (for example Thermal Erosion) must be
            # recomputed with their original upstream inputs when a named
            # output is requested. Earlier versions only handled generator
            # nodes here, which made every named output of a processor lose its
            # input branch.
            for input_name in input_names:
                source_ref = self._source_reference(snapshot.inputs.get((source_node.uid, input_name)))
                if source_ref is None:
                    continue
                upstream_uid, upstream_output = source_ref
                resource = resources.get(upstream_uid)
                upstream_signature = signatures.get(upstream_uid)
                if not isinstance(resource, (CpuImage, GpuImage)) or upstream_signature is None:
                    continue
                if upstream_output != "Image":
                    resource, upstream_signature = self._extract_named_output(
                        snapshot,
                        resources,
                        signatures,
                        snapshot.nodes[upstream_uid],
                        resource,
                        upstream_signature,
                        upstream_output,
                        context,
                        cancel_check,
                        stats,
                        fallbacks,
                        conversion_cache,
                        transients,
                        pending_gpu_cache,
                    )
                input_resources[input_name] = resource
                input_signatures.append((input_name, upstream_signature))
        result, used_signature = self._compute_node(
            virtual,
            input_resources,
            input_signatures,
            context,
            backend_key,
            signature,
            stats,
            fallbacks,
            conversion_cache,
            transients,
            pending_gpu_cache,
            cancel_check,
        )
        return result, used_signature

    @staticmethod
    def _materialise_node_inputs(
        node: SnapshotNode,
        resolved: dict[str, tuple[GraphResource, str, str]],
    ) -> tuple[dict[str, ImageResource], dict[str, Any]]:
        image_inputs: dict[str, ImageResource] = {}
        effective_parameters = deepcopy(node.parameters)
        for input_name, (resource, source_output, _source_signature) in resolved.items():
            parameter_name = node.parameter_for_port(input_name)
            if parameter_name is not None:
                if not isinstance(resource, SignalValue):
                    raise EvaluationError(
                        f"{node.definition.name}.{parameter_name} requires a scalar animation signal"
                    )
                effective_parameters[parameter_name] = resource.scalar(source_output)
                continue
            expected_kind = node.definition.input_kind(input_name)
            if isinstance(resource, SignalValue):
                if is_image_kind(expected_kind):
                    raise EvaluationError(
                        f"Cannot connect signal output to image input {node.definition.name}.{input_name}"
                    )
                effective_parameters[f"__input_{input_name}"] = resource.output(source_output)
                continue
            if not is_image_kind(expected_kind):
                raise EvaluationError(
                    f"{node.definition.name}.{input_name} requires a {expected_kind} signal"
                )
            image_inputs[input_name] = resource
        return image_inputs, effective_parameters

    def _simulation_revision(self, snapshot: GraphSnapshot, node_uid: str) -> str:
        order = self._execution_order(snapshot, node_uid, lambda: False)
        payload_nodes: list[dict[str, Any]] = []
        for uid in order:
            node = snapshot.nodes[uid]
            source_revision: Any = None
            if node.definition.type_id == "input.image" and not node.parameters.get("_embedded_data"):
                try:
                    stat = Path(str(node.parameters.get("path", ""))).expanduser().stat()
                    source_revision = (stat.st_size, stat.st_mtime_ns)
                except OSError:
                    source_revision = "missing"
            payload_nodes.append(
                {
                    "uid": uid,
                    "type": node.definition.type_id,
                    "package_revision": node.definition.package.revision if node.definition.package else None,
                    "parameters": node.parameters,
                    "source_revision": source_revision,
                    "inputs": [
                        (name, self._source_reference(snapshot.inputs.get((uid, name))))
                        for name in node.input_names
                    ],
                }
            )
        encoded = json.dumps(payload_nodes, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.blake2b(encoded, digest_size=20).hexdigest()

    @staticmethod
    def _context_for_frame(base: RenderContext, frame: int) -> RenderContext:
        frame = min(max(int(frame), 0), max(base.document_frame_count - 1, 0))
        last = max(base.document_frame_count - 1, 0)
        normalised = 0.0 if last <= 0 else frame / float(last)
        loop_span = max(base.loop_end_frame - base.loop_start_frame + 1, 1)
        loop_phase = ((frame - base.loop_start_frame) / float(loop_span)) % 1.0
        return RenderContext(
            width=base.width,
            height=base.height,
            precision=base.precision,
            colour_space=base.colour_space,
            time_seconds=frame / max(base.frames_per_second, 1.0),
            frame_number=frame,
            frame_position=float(frame),
            delta_time=base.delta_time,
            duration_seconds=base.duration_seconds,
            normalised_time=normalised,
            loop_phase=loop_phase,
            frames_per_second=base.frames_per_second,
            document_frame_count=base.document_frame_count,
            loop_start_frame=base.loop_start_frame,
            loop_end_frame=base.loop_end_frame,
            render_mode=base.render_mode,
        )

    def _simulation_frame_inputs(
        self,
        snapshot: GraphSnapshot,
        node: SnapshotNode,
        frame: int,
        base_context: RenderContext,
        cancel_check: Callable[[], bool] | None,
        progress_callback: Callable[[int, int, str], None] | None = None,
        node_activity_callback: Callable[[str, bool, int, int, str], None] | None = None,
        interactive_node_uid: str | None = None,
    ) -> tuple[dict[str, ImageResource], dict[str, Any], RenderContext]:
        frame_context = self._context_for_frame(base_context, frame)
        image_inputs: dict[str, ImageResource] = {}
        effective_parameters = deepcopy(node.parameters)
        for input_name in node.input_names:
            if cancel_check is not None and cancel_check():
                raise EvaluationCancelled()
            source_ref = self._source_reference(snapshot.inputs.get((node.uid, input_name)))
            if source_ref is None:
                continue
            source_uid, source_output = source_ref
            result = self.evaluate_snapshot(
                snapshot,
                source_uid,
                frame_context.width,
                frame_context.height,
                cancel_check=cancel_check,
                progress_callback=progress_callback,
                node_activity_callback=node_activity_callback,
                precision=frame_context.precision,
                colour_space=frame_context.colour_space,
                time_seconds=frame_context.time_seconds,
                frame_number=frame_context.frame_number,
                frame_position=frame_context.frame_position,
                delta_time=frame_context.delta_time,
                duration_seconds=frame_context.duration_seconds,
                normalised_time=frame_context.normalised_time,
                loop_phase=frame_context.loop_phase,
                frames_per_second=frame_context.frames_per_second,
                document_frame_count=frame_context.document_frame_count,
                loop_start_frame=frame_context.loop_start_frame,
                loop_end_frame=frame_context.loop_end_frame,
                render_mode=frame_context.render_mode,
                interactive_node_uid=interactive_node_uid,
                output_name=source_output,
            )
            if result.error:
                raise EvaluationError(result.error)
            parameter_name = node.parameter_for_port(input_name)
            expected_kind = node.definition.input_kind(input_name)
            if result.signal_value is not None:
                if parameter_name is not None:
                    value = result.signal_value
                    effective_parameters[parameter_name] = float(value[0]) if isinstance(value, tuple) else float(value)
                elif is_image_kind(expected_kind):
                    raise EvaluationError(
                        f"Cannot connect signal output to image input {node.definition.name}.{input_name}"
                    )
                else:
                    effective_parameters[f"__input_{input_name}"] = result.signal_value
                continue
            if parameter_name is not None:
                raise EvaluationError(
                    f"{node.definition.name}.{parameter_name} requires a scalar animation signal"
                )
            if not is_image_kind(expected_kind):
                raise EvaluationError(
                    f"{node.definition.name}.{input_name} requires a {expected_kind} signal"
                )
            precision = result.precision
            grayscale = result.data_kind == "grayscale"
            if grayscale:
                logical = TextureFormat.R32F if precision == "32-bit float" else TextureFormat.R16F
            else:
                logical = TextureFormat.RGBA32F if precision == "32-bit float" else TextureFormat.RGBA16F
            image_inputs[input_name] = CpuImage(
                np.ascontiguousarray(result.image.copy(), dtype=np.float32),
                logical,
                f"simulation-input:{source_uid}:{source_output}:{frame}",
                frozenset({"cpu"}),
                result.data_kind,
                result.precision,
            )
        return image_inputs, effective_parameters, frame_context

    def _compute_node(
        self,
        node: SnapshotNode,
        input_resources: dict[str, ImageResource],
        input_signatures: list[tuple[str, str]],
        context: RenderContext,
        backend_key: str,
        signature: str,
        stats: dict[str, int],
        fallbacks: list[str],
        conversion_cache: dict[tuple[str, str], ImageResource],
        transients: list[GpuImage],
        pending_gpu_cache: dict[str, GpuImage],
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[ImageResource, str]:
        if node.definition.type_id == "convert.extract_channel" and ":" not in node.uid and "Image" in input_resources:
            return input_resources["Image"], signature
        logical_format, output_precision, data_kind = self._output_spec_for(node, input_resources, context)
        try:
            if backend_key == "gpu":
                prepared = {
                    name: self._to_gpu(resource, context, conversion_cache, transients)
                    for name, resource in input_resources.items()
                }
                assert self.gpu_backend is not None
                result = self.gpu_backend.evaluate_node(
                    node.definition,
                    prepared,
                    node.parameters,
                    context,
                    signature,
                    logical_format,
                    cancel_check=cancel_check,
                    progress_callback=progress_callback,
                )
                stats["gpu"] += 1
            else:
                prepared = {
                    name: self._to_cpu(resource, conversion_cache)
                    for name, resource in input_resources.items()
                }
                result = self.cpu_backend.evaluate_node(
                    node.definition,
                    prepared,
                    node.parameters,
                    context,
                    signature,
                    logical_format,
                    cancel_check=cancel_check,
                    progress_callback=progress_callback,
                )
                stats["cpu"] += 1
                self.cpu_cache.put(signature, result)
        except BackendCancelled as exc:
            raise EvaluationCancelled() from exc
        except Exception as exc:
            if backend_key != "gpu":
                raise
            if not self.cpu_backend.supports(node.definition):
                raise EvaluationError(
                    f"{node.definition.name} WGSL execution failed and this package has no CPU fallback.\n{exc}"
                ) from exc
            fallbacks.append(f"{node.definition.name}: {type(exc).__name__}")
            cpu_inputs = {
                name: self._to_cpu(resource, conversion_cache)
                for name, resource in input_resources.items()
            }
            cpu_signature = self._signature(node, input_signatures, context, "cpu-fallback", True)
            cached_cpu = self.cpu_cache.get(cpu_signature)
            if isinstance(cached_cpu, (CpuImage, GpuImage)):
                return cached_cpu, cpu_signature
            result = self.cpu_backend.evaluate_node(
                node.definition,
                cpu_inputs,
                node.parameters,
                context,
                cpu_signature,
                logical_format,
            )
            stats["cpu"] += 1
            self.cpu_cache.put(cpu_signature, result)
            signature = cpu_signature

        result.data_kind = data_kind
        result.precision = output_precision
        if output_precision == "8-bit" and node.definition.type_id not in {"input.image", "output.image", "output.flipbook"}:
            if isinstance(result, CpuImage):
                quantized = np.round(np.clip(result.array, 0.0, 1.0) * 255.0) / 255.0
                result = CpuImage(
                    np.ascontiguousarray(quantized, dtype=np.float32),
                    result.logical_format,
                    result.cache_key,
                    result.provenance,
                    data_kind,
                    output_precision,
                )
            elif self.gpu_backend is not None:
                unquantized = result
                result = self.gpu_backend.quantize8(result, context, signature)
                if result is not unquantized:
                    transients.append(unquantized)
                result.data_kind = data_kind
                result.precision = output_precision
        if isinstance(result, GpuImage):
            pending_gpu_cache[signature] = result
        else:
            self.cpu_cache.put(signature, result)
        return result, signature

    @staticmethod
    def _precision_rank(value: str) -> int:
        return {"8-bit": 0, "16-bit": 1, "32-bit float": 2}.get(value, 1)

    @classmethod
    def _output_spec_for(
        cls, node: SnapshotNode, inputs: dict[str, ImageResource], context: RenderContext
    ) -> tuple[TextureFormat, str, str]:
        data_kind = normalise_port_kind(node.resolved_kind)
        if data_kind not in ("grayscale", "color", "vector"):
            data_kind = node.definition.default_image_kind

        override = str(node.parameters.get("_precision", "Inherit"))
        if node.definition.type_id in {"filter.flood_fill", "filter.flood_fill_to_index"}:
            # Flood Fill metadata packs bounding-box information into exact
            # float32 channels, and the ordered index can contain thousands of
            # distinct values. These technical outputs must not be quantized.
            precision = "32-bit float"
        elif override in ("8-bit", "16-bit", "32-bit float"):
            precision = override
        elif node.definition.type_id.startswith("filter.flood_fill_"):
            # Derived visual maps are ordinary 0-1 textures. Keep them at the
            # application's practical default unless the artist explicitly
            # requests 32-bit output.
            precision = "16-bit"
        elif node.definition.type_id == "input.image":
            precision = str(node.parameters.get("_source_precision", "16-bit"))
            if precision not in ("8-bit", "16-bit", "32-bit float"):
                precision = "16-bit"
        elif inputs:
            precision = max((getattr(resource, "precision", "16-bit") for resource in inputs.values()), key=cls._precision_rank)
        else:
            precision = "32-bit float" if context.precision is TextureFormat.RGBA32F else "16-bit"

        if data_kind == "grayscale":
            logical = TextureFormat.R32F if precision == "32-bit float" else TextureFormat.R16F
        else:
            logical = TextureFormat.RGBA32F if precision == "32-bit float" else TextureFormat.RGBA16F
        return logical, precision, data_kind

    @staticmethod
    def _logical_format_for(definition: NodeDefinition, inputs: dict[str, ImageResource]) -> TextureFormat:
        type_id = definition.type_id
        preserve_first = {
            "filter.invert", "filter.levels", "filter.auto_levels", "filter.blur",
            "transform.basic", "output.image", "output.flipbook", "animation.flipbook_decode",
        }
        if definition.gpu_spec is not None and definition.gpu_spec.format_policy == "preserve_first" and inputs:
            return next(iter(inputs.values())).logical_format
        if type_id in preserve_first and inputs:
            return next(iter(inputs.values())).logical_format
        if type_id == "math.blend":
            formats = [resource.logical_format for resource in inputs.values()]
            if formats and all(fmt.channels == 1 for fmt in formats):
                return TextureFormat.R16F
            return TextureFormat.RGBA16F
        return TextureFormat(getattr(definition, "output_format", TextureFormat.RGBA16F.value))

    def _backend_for(self, definition: NodeDefinition) -> str:
        if self.backend_preference == "cpu":
            return "cpu"
        if self.gpu_backend is not None and self.gpu_backend.supports(definition):
            return "gpu"
        return "cpu"

    def _to_gpu(
        self,
        image: ImageResource,
        context: RenderContext,
        conversions: dict[tuple[str, str], ImageResource],
        transients: list[GpuImage],
    ) -> GpuImage:
        if isinstance(image, GpuImage):
            return image
        key = ("gpu", image.cache_key)
        cached = conversions.get(key)
        if isinstance(cached, GpuImage):
            return cached
        if self.gpu_backend is None:
            raise RuntimeError("WebGPU backend is unavailable")
        gpu = self.gpu_backend.ensure_gpu(image, context)
        conversions[key] = gpu
        transients.append(gpu)
        return gpu

    def _to_cpu(self, image: ImageResource, conversions: dict[tuple[str, str], ImageResource]) -> CpuImage:
        if isinstance(image, CpuImage):
            return image
        key = ("cpu", image.cache_key)
        cached = conversions.get(key)
        if isinstance(cached, CpuImage):
            return cached
        if self.gpu_backend is None:
            raise RuntimeError("Cannot read a GPU image without WebGPU")
        cpu = self.gpu_backend.to_cpu(image)
        conversions[key] = cpu
        return cpu

    @staticmethod
    def _signature(
        node: SnapshotNode,
        input_signatures: list[tuple[str, str]],
        context: RenderContext,
        backend_key: str,
        include_time: bool,
    ) -> str:
        source_revision = None
        if node.definition.type_id == "input.image" and not node.parameters.get("_embedded_data"):
            try:
                stat = Path(str(node.parameters.get("path", ""))).expanduser().stat()
                source_revision = (stat.st_size, stat.st_mtime_ns)
            except OSError:
                source_revision = "missing"
        payload = {
            "uid": node.uid,
            "type": node.definition.type_id,
            "package_revision": node.definition.package.revision if node.definition.package is not None else None,
            "parameters": node.parameters,
            "source_revision": source_revision,
            "inputs": input_signatures,
            "width": context.width,
            "height": context.height,
            "precision": context.precision.value,
            "colour_space": context.colour_space,
            # 2D and 3D preview modes use the same authored preview quality, so
            # matching resolutions can share expensive upstream GPU caches.
            "render_mode": "preview" if context.render_mode in ("preview", "preview_3d", "histogram") else context.render_mode,
            "backend": backend_key,
        }
        if include_time:
            payload["animation"] = context.animation_signature
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.blake2b(encoded, digest_size=20).hexdigest()


def empty_image_for(context: RenderContext) -> np.ndarray:
    image = np.zeros((context.height, context.width, 4), dtype=np.float32)
    image[..., 3] = 1.0
    return image
