"""Geometry graph evaluation with an explicit bridge to image height inputs."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .engine.evaluator import GraphEvaluator, GraphSnapshot
from .geometry import GeometryData
from .graph_assets import GRAPH_INSTANCE_TYPE
from .nodes.base import is_image_kind, normalise_port_kind


class GeometryEvaluationError(RuntimeError):
    pass


@dataclass(slots=True)
class GeometryEvaluationResult:
    geometry: GeometryData | None
    error: str | None = None
    elapsed_ms: float = 0.0
    source_uid: str = ""
    source_output: str = "Geometry"


class GeometryEvaluationSession:
    """Evaluate mesh branches and explicitly resolve image inputs when required."""

    def __init__(
        self,
        evaluator: GraphEvaluator,
        snapshot: GraphSnapshot,
        width: int = 512,
        height: int = 512,
        *,
        precision: Any | None = None,
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
        render_mode: str = "preview_3d",
    ) -> None:
        self.evaluator = evaluator
        self.snapshot = snapshot
        self.width = max(int(width), 1)
        self.height = max(int(height), 1)
        self.precision = precision
        self.colour_space = str(colour_space or "Linear")
        self.animation = {
            "time_seconds": float(time_seconds),
            "frame_number": max(int(frame_number), 0),
            "frame_position": float(frame_number if frame_position is None else frame_position),
            "delta_time": max(float(delta_time), 0.0),
            "duration_seconds": max(float(duration_seconds), 1.0e-9),
            "normalised_time": float(normalised_time),
            "loop_phase": float(loop_phase) % 1.0,
            "frames_per_second": max(float(frames_per_second), 1.0),
            "document_frame_count": max(int(document_frame_count), 1),
            "loop_start_frame": max(int(loop_start_frame), 0),
            "loop_end_frame": max(int(loop_end_frame), int(loop_start_frame)),
        }
        self.render_mode = str(render_mode or "preview_3d")
        self._cache: dict[tuple[str, str], GeometryData] = {}
        self._image_cache: dict[tuple[str, str], Any] = {}
        self._stack: set[tuple[str, str]] = set()

    @staticmethod
    def _source(snapshot: GraphSnapshot, uid: str, input_name: str) -> tuple[str, str] | None:
        source = snapshot.inputs.get((uid, input_name))
        if source is None:
            return None
        return str(source[0]), str(source[1] or "Geometry")

    def evaluate(self, node_uid: str, output_name: str = "Geometry") -> GeometryEvaluationResult:
        started = time.perf_counter()
        uid = str(node_uid or "")
        port = str(output_name or "Geometry")
        try:
            snapshot, uid, port = self._resolve_structure(self.snapshot, uid, port)
            self.snapshot = snapshot
            geometry = self._evaluate_reference(uid, port)
            return GeometryEvaluationResult(
                geometry,
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                source_uid=uid,
                source_output=port,
            )
        except Exception as exc:
            return GeometryEvaluationResult(
                None,
                error=f"{type(exc).__name__}: {exc}",
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                source_uid=uid,
                source_output=port,
            )

    def _resolve_structure(
        self, snapshot: GraphSnapshot, uid: str, output_name: str
    ) -> tuple[GraphSnapshot, str, str]:
        if uid not in snapshot.nodes:
            raise GeometryEvaluationError("Geometry source no longer exists")
        # Reuse the established graph-asset expansion and Graph Output proxy
        # logic.  These methods only rewrite immutable snapshot topology and do
        # not invoke the image renderer.
        uid, output_name = self.evaluator._resolve_graph_output_proxy(snapshot, uid, output_name)
        snapshot, uid, output_name = self.evaluator._expand_graph_instances(snapshot, uid, output_name)
        return snapshot, uid, output_name

    def _evaluate_reference(self, uid: str, output_name: str) -> GeometryData:
        key = (str(uid), str(output_name or "Geometry"))
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        if key in self._stack:
            raise GeometryEvaluationError("Geometry graph contains a cycle")
        node = self.snapshot.nodes.get(key[0])
        if node is None:
            raise GeometryEvaluationError("Geometry source node is missing")
        self._stack.add(key)
        try:
            type_id = node.definition.type_id
            if type_id == "output.geometry":
                geometry = self._evaluate_input(node.uid, "Geometry")
            elif type_id in {"graph.send", "graph.receive", "graph.reroute"}:
                geometry = self._evaluate_input(node.uid, "Input")
            elif type_id == "material.pbr" and key[1] == "Geometry":
                geometry = self._evaluate_input(node.uid, "Geometry")
            elif node.definition.geometry_evaluator is not None:
                resolved_inputs: dict[str, Any] = {}
                for input_name in node.input_names:
                    input_kind = normalise_port_kind(node.definition.input_kind(input_name))
                    source = self._source(self.snapshot, node.uid, input_name)
                    if source is None:
                        continue
                    if input_kind == "geometry":
                        resolved_inputs[input_name] = self._evaluate_reference(*source)
                    elif is_image_kind(input_kind):
                        resolved_inputs[input_name] = self._evaluate_image_reference(*source)
                value = node.definition.geometry_evaluator(resolved_inputs, node.parameters)
                if not isinstance(value, GeometryData):
                    raise GeometryEvaluationError(
                        f"{node.definition.name} did not produce a GeometryData value"
                    )
                geometry = value
            else:
                declared = normalise_port_kind(node.definition.output_kind(key[1]))
                if declared != "geometry":
                    raise GeometryEvaluationError(
                        f"{node.definition.name} output '{key[1]}' is {declared}, not Geometry"
                    )
                # Transparent one-input geometry helpers, including future
                # reroutes, can pass through without requiring image execution.
                candidates = [
                    name for name in node.input_names
                    if normalise_port_kind(node.definition.input_kind(name)) == "geometry"
                ]
                if len(candidates) != 1:
                    raise GeometryEvaluationError(
                        f"{node.definition.name} has no geometry evaluator"
                    )
                geometry = self._evaluate_input(node.uid, candidates[0])
            self._cache[key] = geometry
            return geometry
        finally:
            self._stack.discard(key)

    def _evaluate_image_reference(self, uid: str, output_name: str) -> Any:
        key = (str(uid), str(output_name or "Image"))
        cached = self._image_cache.get(key)
        if cached is not None:
            return cached
        if not hasattr(self.evaluator, "evaluate"):
            raise GeometryEvaluationError("This geometry evaluator cannot resolve image inputs")
        kwargs = dict(self.animation)
        kwargs.update({
            "snapshot": self.snapshot,
            "output_name": key[1],
            "colour_space": self.colour_space,
            "render_mode": self.render_mode,
            "prepare_display": False,
            "collect_traces": False,
        })
        if self.precision is not None:
            kwargs["precision"] = self.precision
        result = self.evaluator.evaluate(key[0], self.width, self.height, **kwargs)
        if getattr(result, "error", None):
            raise GeometryEvaluationError(str(result.error))
        image = getattr(result, "image", None)
        if image is None:
            raise GeometryEvaluationError(
                f"Image input '{key[1]}' produced no readable pixel data"
            )
        self._image_cache[key] = image
        return image

    def _evaluate_input(self, uid: str, input_name: str) -> GeometryData:
        source = self._source(self.snapshot, uid, input_name)
        if source is None:
            raise GeometryEvaluationError(f"Geometry input '{input_name}' is not connected")
        return self._evaluate_reference(*source)


def material_geometry_reference(
    snapshot: GraphSnapshot, material_uid: str | None
) -> tuple[str, str] | None:
    """Resolve the mesh association carried by a material composition chain."""

    current = str(material_uid or "")
    visited: set[str] = set()
    while current:
        if current in visited:
            return None
        visited.add(current)
        node = snapshot.nodes.get(current)
        if node is None:
            return None
        type_id = node.definition.type_id
        if type_id == "material.pbr":
            source = snapshot.inputs.get((current, "Geometry"))
            return (str(source[0]), str(source[1] or "Geometry")) if source is not None else None
        if type_id == "material.blend":
            selected = (
                "Foreground Material"
                if str(node.parameters.get("settings_source", "Background")) == "Foreground"
                else "Background Material"
            )
        elif type_id in {"material.override", "material.crop", "material.make_it_tile_photo"}:
            selected = "Material"
        elif type_id == "material.switch":
            selected = "Material B" if str(node.parameters.get("selected_material", "A")) == "B" else "Material A"
        elif type_id == "output.texture_set":
            selected = "Material"
        else:
            return None
        source = snapshot.inputs.get((current, selected))
        if source is None:
            return None
        current = str(source[0])
    return None
