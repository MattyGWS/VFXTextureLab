"""Geometry graph evaluation with an explicit bridge to image height inputs."""

from __future__ import annotations

import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .engine.evaluator import GraphEvaluator, GraphSnapshot
from .geometry import GeometryData, GeometryEvalContext, GeometryEvaluationCancelled
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
    node_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    preview_image: Any | None = None
    preview_material_texture: Any | None = None
    preview_material_textures: dict[str, Any] = field(default_factory=dict)
    preview_details: str = ""
    preview_kind: str = ""


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
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
        node_activity_callback: Callable[[str, bool, int, int, str], None] | None = None,
        preview_options: dict[str, Any] | None = None,
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
        self.cancel_check = cancel_check
        self.progress_callback = progress_callback
        self.node_activity_callback = node_activity_callback
        self.preview_options = dict(preview_options or {})
        self._node_previews: dict[str, tuple[Any, str, str]] = {}
        self._node_preview_materials: dict[str, Any] = {}
        self._node_preview_material_sets: dict[str, dict[str, Any]] = {}
        self._cache: dict[tuple[str, str], GeometryData] = {}
        self._image_cache: dict[tuple[str, str, int, int], Any] = {}
        self._stack: set[tuple[str, str]] = set()
        self._node_metadata: dict[str, dict[str, Any]] = {}

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
                node_metadata={key: dict(value) for key, value in self._node_metadata.items()},
                preview_image=(self._node_previews.get(uid) or (None, "", ""))[0],
                preview_material_texture=self._node_preview_materials.get(uid),
                preview_material_textures=dict(self._node_preview_material_sets.get(uid, {})),
                preview_details=(self._node_previews.get(uid) or (None, "", ""))[1],
                preview_kind=(self._node_previews.get(uid) or (None, "", ""))[2],
            )
        except GeometryEvaluationCancelled:
            raise
        except Exception as exc:
            return GeometryEvaluationResult(
                None,
                error=f"{type(exc).__name__}: {exc}",
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                source_uid=uid,
                source_output=port,
                node_metadata={key: dict(value) for key, value in self._node_metadata.items()},
                preview_image=(self._node_previews.get(uid) or (None, "", ""))[0],
                preview_material_texture=self._node_preview_materials.get(uid),
                preview_material_textures=dict(self._node_preview_material_sets.get(uid, {})),
                preview_details=(self._node_previews.get(uid) or (None, "", ""))[1],
                preview_kind=(self._node_previews.get(uid) or (None, "", ""))[2],
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
        if self.cancel_check is not None and self.cancel_check():
            raise GeometryEvaluationCancelled("Geometry evaluation was cancelled")
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
            input_geometry: GeometryData | None = None
            if type_id == "output.geometry":
                input_geometry = self._evaluate_input(node.uid, "Geometry")
                geometry = input_geometry
            elif type_id in {"graph.send", "graph.receive", "graph.reroute"}:
                input_geometry = self._evaluate_input(node.uid, "Input")
                geometry = input_geometry
            elif type_id == "material.pbr" and key[1] == "Geometry":
                input_geometry = self._evaluate_input(node.uid, "Geometry")
                geometry = input_geometry
            elif node.definition.geometry_evaluator is not None:
                resolved_inputs: dict[str, Any] = {}
                manual_has_result = bool(
                    node.definition.type_id == "geometry.bake_high_to_low"
                    and node.parameters.get("_manual_result_data")
                    and int(node.parameters.get("_manual_run_serial", 0) or 0)
                        <= int(node.parameters.get("_manual_completed_serial", 0) or 0)
                )
                manual_not_run = bool(
                    node.definition.type_id == "geometry.bake_high_to_low"
                    and not node.parameters.get("_manual_result_data")
                    and int(node.parameters.get("_manual_run_serial", 0) or 0)
                        <= int(node.parameters.get("_manual_completed_serial", 0) or 0)
                )
                for input_name in node.input_names:
                    if manual_has_result:
                        # Completed bake maps/low geometry are a transactional,
                        # self-contained result. Merely focusing the node must not
                        # reevaluate million-triangle source branches.
                        continue
                    if manual_not_run and input_name != "Low Geometry":
                        continue
                    if (
                        input_name in node.definition.presentation_only_inputs
                        and self.render_mode.startswith("final")
                    ):
                        continue
                    input_kind = normalise_port_kind(node.definition.input_kind(input_name))
                    source = self._source(self.snapshot, node.uid, input_name)
                    if source is None:
                        continue
                    if input_kind == "geometry":
                        resolved = self._evaluate_reference(*source)
                        resolved_inputs[input_name] = resolved
                        if input_geometry is None:
                            input_geometry = resolved
                    elif is_image_kind(input_kind):
                        if node.definition.type_id == "geometry.bake_high_to_low" and input_name == "High Albedo":
                            bake_resolution = int(node.parameters.get("resolution", 1024) or 1024)
                            # Source-texture resolution is independent from low-atlas
                            # supersampling. Evaluating a 4096 bake's source at 16K
                            # would allocate gigabytes before the baker can reject an
                            # unsafe internal atlas, while adding no source detail
                            # beyond the final output. Keep it bounded to the actual
                            # output side; the baker samples it continuously through
                            # the high-poly UVs for every supersample.
                            bake_source_resolution = min(max(bake_resolution, 64), 4096)
                            resolved_inputs[input_name] = self._evaluate_image_reference(
                                *source, width=bake_source_resolution, height=bake_source_resolution
                            )
                        else:
                            resolved_inputs[input_name] = self._evaluate_image_reference(*source)
                def report_progress(current: int, target: int, message: str) -> None:
                    if self.progress_callback is not None:
                        self.progress_callback(int(current), int(target), str(message or node.definition.name))
                    if self.node_activity_callback is not None:
                        self.node_activity_callback(
                            node.uid, True, int(current), int(target),
                            str(message or f"Evaluating {node.definition.name}"),
                        )

                context = GeometryEvalContext(
                    node_uid=node.uid,
                    node_name=node.definition.name,
                    cancel_check=self.cancel_check,
                    progress_callback=report_progress,
                    width=self.width,
                    height=self.height,
                    preview_options=dict(self.preview_options),
                    render_mode=self.render_mode,
                )
                if self.node_activity_callback is not None:
                    self.node_activity_callback(
                        node.uid, True, 0, 0, f"Evaluating {node.definition.name}"
                    )
                try:
                    evaluator = node.definition.geometry_evaluator
                    try:
                        parameter_count = len(inspect.signature(evaluator).parameters)
                    except (TypeError, ValueError):
                        parameter_count = 2
                    if parameter_count >= 3:
                        value = evaluator(resolved_inputs, node.parameters, context)
                    else:
                        value = evaluator(resolved_inputs, node.parameters)
                    if context.metadata:
                        self._node_metadata[node.uid] = dict(context.metadata)
                    if context.preview_image is not None:
                        self._node_previews[node.uid] = (
                            context.preview_image, str(context.preview_details or ""),
                            str(context.preview_kind or ""),
                        )
                    if context.preview_material_texture is not None:
                        self._node_preview_materials[node.uid] = context.preview_material_texture
                    if context.preview_material_textures:
                        self._node_preview_material_sets[node.uid] = dict(context.preview_material_textures)
                finally:
                    if self.node_activity_callback is not None:
                        self.node_activity_callback(
                            node.uid, False, 0, 0, f"Finished {node.definition.name}"
                        )
                if not isinstance(value, GeometryData):
                    raise GeometryEvaluationError(
                        f"{node.definition.name} did not produce a GeometryData value"
                    )
                geometry = value
                # UV operation nodes use the ordinary 3D geometry preview and a
                # dedicated 2D atlas view at the same time. Geometry UV Unwrap
                # publishes its richer preview from its evaluator; lightweight
                # UV operations can use this generic existing-UV presentation.
                if (
                    not self.render_mode.startswith("final")
                    and
                    node.definition.type_id.startswith("geometry.uv_")
                    and node.uid not in self._node_previews
                ):
                    from .uv_unwrap import existing_uv_result, render_uv_preview

                    uv_result = existing_uv_result(geometry, backend=node.definition.name)
                    self._node_previews[node.uid] = (
                        render_uv_preview(
                            uv_result,
                            None,
                            width=max(self.width, 128),
                            height=max(self.height, 128),
                            options=self.preview_options,
                        ),
                        (
                            f"UV layout · {int(uv_result.diagnostics.get('island_count', 0)):,} islands · "
                            f"{float(uv_result.diagnostics.get('coverage', 0.0)) * 100.0:.1f}% coverage · "
                            f"{int(uv_result.diagnostics.get('overlap_triangle_count', 0)):,} overlap triangles"
                        ),
                        "uv",
                    )
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
                input_geometry = self._evaluate_input(node.uid, candidates[0])
                geometry = input_geometry

            # Every evaluated geometry node publishes lightweight output statistics.
            # This is deliberately centralised here so generators and operations do
            # not each need bespoke inspector plumbing, and dense-mesh operations can
            # still prove that they completed when Auto wireframe is suppressed.
            metadata = dict(self._node_metadata.get(node.uid, {}))
            metadata.update({
                "_geometry_output_vertex_count": geometry.vertex_count,
                "_geometry_output_triangle_count": geometry.triangle_count,
                "_geometry_output_memory_bytes": int(geometry.vertices.nbytes + geometry.indices.nbytes),
            })
            if input_geometry is not None:
                metadata.update({
                    "_geometry_input_vertex_count": input_geometry.vertex_count,
                    "_geometry_input_triangle_count": input_geometry.triangle_count,
                    "_geometry_input_memory_bytes": int(input_geometry.vertices.nbytes + input_geometry.indices.nbytes),
                })
            self._node_metadata[node.uid] = metadata
            self._cache[key] = geometry
            return geometry
        finally:
            self._stack.discard(key)

    def _evaluate_image_reference(
        self, uid: str, output_name: str, *, width: int | None = None, height: int | None = None
    ) -> Any:
        if self.cancel_check is not None and self.cancel_check():
            raise GeometryEvaluationCancelled("Geometry evaluation was cancelled")
        resolved_width = max(int(width or self.width), 1)
        resolved_height = max(int(height or self.height), 1)
        key = (str(uid), str(output_name or "Image"), resolved_width, resolved_height)
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
        result = self.evaluator.evaluate(key[0], resolved_width, resolved_height, **kwargs)
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
        if type_id == "geometry.bake_high_to_low":
            return (current, "Low Geometry")
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
