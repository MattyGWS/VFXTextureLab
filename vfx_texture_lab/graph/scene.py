from __future__ import annotations

from copy import deepcopy
import base64
import binascii
import json
import time
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QPointF, QRectF, Signal, QTimer, Qt
from PySide6.QtGui import QColor, QPainterPath, QPainterPathStroker, QPen, QUndoStack
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsScene

from ..nodes.base import (
    NodeDefinition,
    is_image_kind,
    normalise_interrupted_manual_action,
    normalise_port_kind,
    port_kinds_compatible,
)
from ..canvas_node import ensure_canvas_parameters
from ..graph_assets import (
    GRAPH_INPUT_TYPE, GRAPH_OUTPUT_TYPE, GRAPH_INSTANCE_TYPE,
    graph_input_kind, graph_instance_definition, load_graph_asset,
    instance_parameters_for_asset, parse_graph_asset_interface, source_revision,
)
from ..nodes.registry import NodeRegistry
from .items import ConnectionItem, GroupFrameItem, GroupPortItem, NodeItem, PortalNodeItem, PortItem, RerouteItem
from .undo import GraphSnapshotCommand, NodeParameterCommand


class GraphScene(QGraphicsScene):
    activeNodeChanged = Signal(object)
    selectedNodeChanged = Signal(object)  # Kept for compatibility; may emit a group.
    graphChanged = Signal()
    groupsChanged = Signal()
    thumbnailChanged = Signal(object)

    def __init__(self, registry: NodeRegistry, parent=None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.nodes: dict[str, NodeItem] = {}
        self.groups: dict[str, GroupFrameItem] = {}
        self.connections: list[ConnectionItem] = []
        self.active_node: NodeItem | None = None
        self.active_output_name: str | None = None
        self.undo_stack = QUndoStack(self)
        self.default_tiling = True
        self.default_geometric_rasterization = "Antialiased"
        self.canvas_default_size = (1024, 1024)
        self._evaluation_active_nodes: set[str] = set()
        self._evaluation_started_at: dict[str, float] = {}
        self._wire_flow_phase = 0.0
        self._wire_flow_connections: list[ConnectionItem] = []
        self._wire_flow_timer = QTimer(self)
        self._wire_flow_timer.setInterval(70)
        self._wire_flow_timer.timeout.connect(self._advance_wire_flow)
        self._portal_debug_items: list[QGraphicsPathItem] = []

        self._restoring = False
        self._constructing = False
        self._moving_group = False
        self._updating_docks = False
        self._action_depth = 0
        self._action_before: dict[str, Any] | None = None
        self._action_text = "Edit Graph"
        self._action_changed = False
        self._action_merge_key: str | None = None
        # One-shot context for listeners that can avoid rebuilding an unchanged
        # published result. Manual-action settings are authored graph edits, but
        # they do not alter the current mesh until the artist presses the action.
        self._graph_change_hint: tuple[str, str] | None = None

        self.setSceneRect(-1800, -1800, 3600, 3600)
        self.selectionChanged.connect(self._selection_changed)

    def set_node_evaluation_state(
        self,
        node_uid: str,
        active: bool,
        current: int = 0,
        target: int = 0,
        message: str | None = None,
    ) -> None:
        node = self.nodes.get(node_uid)
        if node is not None:
            node.set_evaluation_state(active, current, target, message)
        if active:
            if node_uid not in self._evaluation_active_nodes:
                self._evaluation_started_at[node_uid] = time.perf_counter()
            self._evaluation_active_nodes.add(node_uid)
        else:
            self._evaluation_active_nodes.discard(node_uid)
            self._evaluation_started_at.pop(node_uid, None)
        self._refresh_wire_flow()

    def clear_node_evaluation_states(self) -> None:
        for node in self.nodes.values():
            node.set_evaluation_state(False)
        self._evaluation_active_nodes.clear()
        self._evaluation_started_at.clear()
        self._refresh_wire_flow()

    def _refresh_wire_flow(self) -> None:
        now = time.perf_counter()
        visible_nodes = {
            uid for uid in self._evaluation_active_nodes
            if now - self._evaluation_started_at.get(uid, now) >= 0.18
        }
        active_connections = [
            connection for connection in self.connections
            if connection.target_node.uid in visible_nodes
        ]
        active_set = set(active_connections)
        for connection in self._wire_flow_connections:
            if connection not in active_set:
                connection.set_evaluation_flow(False)
        self._wire_flow_connections = active_connections
        for connection in active_connections:
            connection.set_evaluation_flow(True, self._wire_flow_phase)
        if self._evaluation_active_nodes:
            if not self._wire_flow_timer.isActive():
                self._wire_flow_timer.start()
        else:
            self._wire_flow_timer.stop()

    def _advance_wire_flow(self) -> None:
        self._wire_flow_phase = (self._wire_flow_phase + 0.08) % 1.0
        self._refresh_wire_flow()

    @staticmethod
    def _compatible_output_name(source: NodeItem, output_name: str) -> str:
        """Map output names renamed by newer graph schema versions."""
        if source.definition.type_id == "signal.time":
            legacy = {
                "Normalised": "Document Phase",
                "Delta": "Delta Seconds",
            }
            return legacy.get(output_name, output_name)
        return output_name

    @staticmethod
    def _compatible_input_name(target: NodeItem, input_name: str) -> str:
        """Map input names renamed by newer graph schema versions."""
        if target.definition.type_id == "math.blend":
            return {"A": "Background", "B": "Foreground"}.get(input_name, input_name)
        if target.definition.type_id == "material.pbr":
            return {"Albedo": "Base Colour", "Specular": "Specular Level"}.get(input_name, input_name)
        return input_name

    def _migrate_interface_outputs(self, entries: list[dict]) -> list[dict]:
        for entry in entries:
            node = self.nodes.get(str(entry.get("node", "")))
            if node is not None:
                entry["output"] = self._compatible_output_name(
                    node, str(entry.get("output", "Image"))
                )
        return entries

    def _migrate_interface_inputs(self, entries: list[dict]) -> list[dict]:
        for entry in entries:
            node = self.nodes.get(str(entry.get("node", "")))
            if node is not None:
                entry["input"] = self._compatible_input_name(
                    node, str(entry.get("input", ""))
                )
        return entries

    # ------------------------------------------------------------------
    # Typed image-flow support
    # ------------------------------------------------------------------
    @staticmethod
    def _concrete_image_kind(kind: str) -> str | None:
        kind = normalise_port_kind(kind)
        return kind if kind in ("grayscale", "color", "vector") else None

    def _connection_source_kind(self, node: NodeItem, input_name: str) -> str | None:
        connection = self.connection_for_input(node.uid, input_name)
        if connection is None:
            return None
        if connection.broken and connection.source_node.definition.type_id != "graph.receive":
            return None
        return self._concrete_image_kind(connection.source_port.kind)

    def _desired_node_kind(self, node: NodeItem) -> str:
        definition = node.definition
        policy = definition.type_policy
        if definition.gpu_spec is not None and definition.gpu_spec.format_policy == "preserve_first":
            policy = "preserve_primary"

        if policy == "image_input":
            selected = str(node.parameters.get("data_type", "Auto"))
            mapping = {"Greyscale": "grayscale", "Colour": "color", "Vector / Normal": "vector"}
            if selected in mapping:
                return mapping[selected]
            detected = normalise_port_kind(str(node.parameters.get("_detected_kind", definition.default_image_kind)))
            return detected if detected in ("grayscale", "color", "vector") else definition.default_image_kind

        if policy == "parameter_output":
            selected = str(node.parameters.get("output_data_type", "Colour"))
            return {"Colour": "color", "Vector / Normal": "vector"}.get(
                selected, definition.default_image_kind
            )

        if policy == "preserve_primary":
            primary = definition.primary_input or (definition.inputs[0] if definition.inputs else "")
            source_kind = self._connection_source_kind(node, primary) if primary else None
            return source_kind or definition.default_image_kind

        if policy == "blend_match":
            for name in ("Foreground", "Background"):
                source_kind = self._connection_source_kind(node, name)
                if source_kind is not None:
                    return source_kind
            return definition.default_image_kind

        # A fixed node can still expose an image_any output (for example a
        # placeholder). Keep its current/default kind rather than guessing.
        return node.resolved_image_kind or definition.default_image_kind

    def portal_sends(self) -> list[PortalNodeItem]:
        return [
            node for node in self.nodes.values()
            if isinstance(node, PortalNodeItem) and node.definition.type_id == "graph.send"
        ]

    def portal_display_name(self, receive: NodeItem) -> str:
        sender_uid = str(receive.parameters.get("sender_uid", ""))
        sender = self.nodes.get(sender_uid)
        if sender is not None and sender.definition.type_id == "graph.send":
            return str(sender.parameters.get("channel_name", "Channel")).strip() or "Channel"
        return str(receive.parameters.get("channel_name", "")).strip()

    def _unique_portal_name(self, requested: str, *, excluding_uid: str | None = None) -> str:
        base = str(requested or "Channel").strip() or "Channel"
        used = {
            str(node.parameters.get("channel_name", "")).strip().casefold()
            for node in self.portal_sends()
            if node.uid != excluding_uid
        }
        if base.casefold() not in used:
            return base
        index = 2
        while f"{base} {index}".casefold() in used:
            index += 1
        return f"{base} {index}"

    def _resolve_portal_types(self, *, refresh_validity: bool = True) -> bool:
        changed = False
        sends = {node.uid: node for node in self.portal_sends()}
        send_sources: dict[str, str] = {}
        for sender in sends.values():
            source = self.connection_for_input(sender.uid, "Input")
            valid_source = source is not None and not source.broken
            kind = normalise_port_kind(source.source_port.kind) if valid_source else "image_any"
            # Keep the topological source even when a retained Receive wire is
            # temporarily broken, so wireless-cycle detection cannot oscillate
            # between valid and invalid states on successive refreshes.
            if source is not None:
                send_sources[sender.uid] = source.source_node.uid
            changed = sender.set_portal_kind(kind) or changed
            sender.set_error(None if valid_source else "Connect a valid value to publish this channel.")

        receivers: list[PortalNodeItem] = []
        for node in self.nodes.values():
            if not isinstance(node, PortalNodeItem) or node.definition.type_id != "graph.receive":
                continue
            receivers.append(node)
            sender_uid = str(node.parameters.get("sender_uid", ""))
            sender = sends.get(sender_uid)
            if sender is None:
                changed = node.set_portal_kind("image_any") or changed
                node.set_error("The selected Send channel is missing.")
                continue
            node.parameters["channel_name"] = str(sender.parameters.get("channel_name", "Channel"))
            changed = node.set_portal_kind(sender.portal_kind) or changed
            node.update()
            if sender.portal_kind == "image_any":
                node.set_error("The selected Send channel has no connected value.")
            else:
                node.set_error(None)

        # Include wireless edges in cycle detection. A portal cycle is invalid
        # just like a visible wire cycle, but the Receive remains in place with
        # a clear error so the user can repair the channel selection.
        adjacency: dict[str, set[str]] = {uid: set() for uid in self.nodes}
        for connection in self.connections:
            source_kind = normalise_port_kind(connection.source_port.kind)
            target_kind = normalise_port_kind(connection.target_port.kind)
            if port_kinds_compatible(source_kind, target_kind):
                adjacency.setdefault(connection.source_node.uid, set()).add(connection.target_node.uid)
        virtual_sources: dict[str, str] = {}
        for receiver in receivers:
            sender_uid = str(receiver.parameters.get("sender_uid", ""))
            source_uid = send_sources.get(sender_uid)
            if source_uid:
                virtual_sources[receiver.uid] = source_uid
                adjacency.setdefault(source_uid, set()).add(receiver.uid)

        def reaches(start: str, target: str) -> bool:
            stack = [start]
            visited: set[str] = set()
            while stack:
                uid = stack.pop()
                if uid == target:
                    return True
                if uid in visited:
                    continue
                visited.add(uid)
                stack.extend(adjacency.get(uid, ()))
            return False

        for receiver in receivers:
            source_uid = virtual_sources.get(receiver.uid)
            if source_uid and reaches(receiver.uid, source_uid):
                receiver.set_error("This wireless channel creates a graph cycle.")

        if refresh_validity:
            self._refresh_connection_validity()
        return changed

    def _refresh_connection_validity(self) -> None:
        for connection in self.connections:
            source_kind = normalise_port_kind(connection.source_port.kind)
            target_kind = normalise_port_kind(connection.target_port.kind)
            incompatible = not port_kinds_compatible(source_kind, target_kind)
            if connection.source_node.definition.type_id == "graph.receive":
                connection.set_broken(
                    incompatible
                    or source_kind == "image_any"
                    or bool(connection.source_node.error_message)
                )
            elif not incompatible:
                connection.set_broken(False)

    def _resolve_graph_interface_types(self) -> bool:
        changed = False
        for node in self.nodes.values():
            if node.definition.type_id == GRAPH_INPUT_TYPE:
                port = node.output_ports.get("Value")
                if port is not None:
                    kind = graph_input_kind(node.parameters)
                    label = str(node.parameters.get("name", "Input") or "Input")
                    if port.display_name != label:
                        port.display_name = label
                        node.prepareGeometryChange()
                        node._position_ports()
                        node.update()
                        changed = True
                    if normalise_port_kind(port.kind) != kind:
                        port.set_kind(kind)
                        changed = True
            elif node.definition.type_id == GRAPH_OUTPUT_TYPE:
                port = node.input_ports.get("Value")
                if port is not None:
                    label = str(node.parameters.get("name", "Output") or "Output")
                    if port.display_name != label:
                        port.display_name = label
                        node.prepareGeometryChange()
                        node._position_ports()
                        node.update()
                        changed = True
                    connection = self.connection_for_input(node.uid, "Value")
                    kind = normalise_port_kind(connection.source_port.kind) if connection is not None else "any"
                    if normalise_port_kind(port.kind) != kind:
                        port.set_kind(kind)
                        changed = True
        return changed

    def _resolve_dynamic_types(self) -> None:
        # Resolve ordinary polymorphic image chains and wireless portal chains
        # together. Portal-to-portal and portal-to-preserve-type routes may need
        # several turns before every downstream socket has the final kind.
        for _pass in range(max(len(self.nodes), 1) + 1):
            changed = self._resolve_graph_interface_types()
            for node in self.nodes.values():
                if isinstance(node, PortalNodeItem):
                    continue
                changed = node.set_resolved_image_kind(self._desired_node_kind(node)) or changed
            changed = self._resolve_portal_types(refresh_validity=False) or changed
            if not changed:
                break

        # A deliberately polymorphic input remains declared as image_any so it
        # can accept greyscale, colour, or vector data, but its visible socket
        # should reflect the concrete type currently flowing through it. This
        # keeps universal tools such as Extract Channels consistent with their
        # connected wire without locking their compatibility.
        for node in self.nodes.values():
            if node.definition.type_policy != "accept_any_input":
                continue
            for input_name, port in node.input_ports.items():
                if normalise_port_kind(port.declared_kind) != "image_any":
                    continue
                port.set_kind(self._connection_source_kind(node, input_name) or "image_any")

        self._resolve_graph_interface_types()
        self._resolve_portal_types(refresh_validity=False)
        self._refresh_connection_validity()

        for connection in self.connections:
            connection.update_path()

        for node in self.nodes.values():
            if node.definition.type_id != GRAPH_INSTANCE_TYPE:
                continue
            messages: list[str] = []
            status = str(node.parameters.get("_asset_status", ""))
            if status == "Missing source":
                messages.append("Linked graph asset is missing; using the last cached revision.")
            elif status == "Reload failed":
                messages.append("The linked graph asset could not be reloaded.")
            interface = dict(node.parameters.get("_asset_interface", {}))
            for entry in interface.get("inputs", ()):
                if not isinstance(entry, dict) or not bool(entry.get("required", False)):
                    continue
                port_name = str(entry.get("port", ""))
                if port_name and self.connection_for_input(node.uid, port_name) is None:
                    messages.append(f"Required input '{entry.get('name', 'Input')}' is not connected.")
            if any(bool(entry.get("missing")) for key in ("inputs", "outputs") for entry in interface.get(key, ()) if isinstance(entry, dict)):
                messages.append("A connected public socket was removed from the source asset.")
            node.set_error(" ".join(messages) if messages else None)

    @staticmethod
    def _kind_label(kind: str) -> str:
        return {
            "grayscale": "Greyscale",
            "color": "Colour",
            "vector": "Vector / Normal",
            "material": "Material",
            "geometry": "Geometry",
            "scalar": "Scalar",
            "vector2": "Vector2",
            "vector3": "Vector3",
        }.get(normalise_port_kind(kind), str(kind).title())

    @staticmethod
    def _effective_port_kind(port: PortItem, kinds: dict[str, str]) -> str:
        declared = normalise_port_kind(port.declared_kind)
        if isinstance(port.owner, RerouteItem):
            return normalise_port_kind(port.kind)
        if declared == "any":
            return normalise_port_kind(port.kind)
        if declared == "image_any" and isinstance(port.owner, NodeItem):
            if not port.is_output and port.owner.definition.type_policy == "accept_any_input":
                return "image_any"
            return kinds.get(port.owner.uid, port.owner.resolved_image_kind)
        return declared

    def _prospective_kind_map(self, source: PortItem, target: PortItem) -> dict[str, str]:
        """Resolve dynamic image kinds as though source were connected to target.

        This lets the drag preview reject a connection *before* it silently turns
        a preserve-type branch from greyscale into colour and invalidates an
        already-connected downstream socket.
        """
        kinds = {uid: node.resolved_image_kind for uid, node in self.nodes.items()}
        replaced_key = (target.owner.uid, target.name)

        def source_for(node: NodeItem, input_name: str) -> PortItem | None:
            if (node.uid, input_name) == replaced_key:
                return source
            connection = self.connection_for_input(node.uid, input_name)
            return connection.source_port if connection is not None else None

        def port_kind(port: PortItem | None) -> str | None:
            if port is None:
                return None
            return self._effective_port_kind(port, kinds)

        for _pass in range(max(len(self.nodes), 1) + 1):
            changed = False
            for node in self.nodes.values():
                definition = node.definition
                policy = definition.type_policy
                if definition.gpu_spec is not None and definition.gpu_spec.format_policy == "preserve_first":
                    policy = "preserve_primary"
                desired = kinds.get(node.uid, definition.default_image_kind)
                if policy == "image_input":
                    selected = str(node.parameters.get("data_type", "Auto"))
                    desired = {
                        "Greyscale": "grayscale",
                        "Colour": "color",
                        "Vector / Normal": "vector",
                    }.get(selected, normalise_port_kind(str(node.parameters.get("_detected_kind", definition.default_image_kind))))
                elif policy == "parameter_output":
                    desired = {
                        "Colour": "color",
                        "Vector / Normal": "vector",
                    }.get(str(node.parameters.get("output_data_type", "Colour")), definition.default_image_kind)
                elif policy == "preserve_primary":
                    primary = definition.primary_input or (definition.inputs[0] if definition.inputs else "")
                    desired = port_kind(source_for(node, primary)) or definition.default_image_kind
                elif policy == "blend_match":
                    desired = None
                    for name in ("Foreground", "Background"):
                        desired = port_kind(source_for(node, name))
                        if desired is not None:
                            break
                    desired = desired or definition.default_image_kind
                if desired not in ("grayscale", "color", "vector"):
                    desired = definition.default_image_kind
                if kinds.get(node.uid) != desired:
                    kinds[node.uid] = desired
                    changed = True
            if not changed:
                break
        return kinds

    def _prospective_connection_error(self, source: PortItem, target: PortItem) -> str | None:
        if not (is_image_kind(source.kind) and normalise_port_kind(target.declared_kind) == "image_any"):
            return None
        kinds = self._prospective_kind_map(source, target)
        replaced_key = (target.owner.uid, target.name)
        pairs: list[tuple[PortItem, PortItem]] = [
            (connection.source_port, connection.target_port)
            for connection in self.connections
            if (connection.target_node.uid, connection.input_name) != replaced_key
        ]
        pairs.append((source, target))
        for existing_source, existing_target in pairs:
            source_kind = self._effective_port_kind(existing_source, kinds)
            target_kind = self._effective_port_kind(existing_target, kinds)
            if not port_kinds_compatible(source_kind, target_kind):
                owner = existing_target.owner
                node_name = owner.definition.name if isinstance(owner, NodeItem) else "target"
                return (
                    f"This would make the branch {self._kind_label(source_kind)}, but "
                    f"{node_name}.{existing_target.display_name} requires {self._kind_label(target_kind)}. "
                    "Use an explicit conversion node."
                )
        return None

    def _remove_incompatible_connections(self) -> int:
        """Remove links made invalid by a type-changing edit or disconnection.

        Interactive connection creation is rejected up front. This cleanup is
        for edits such as changing an Image Input from Colour to Greyscale or
        disconnecting the primary input of a preserve-type processor.
        """
        removed = 0
        for _pass in range(max(len(self.connections), 1) + 1):
            invalid: list[ConnectionItem] = []
            for connection in self.connections:
                source_kind = normalise_port_kind(connection.source_port.kind)
                target_kind = normalise_port_kind(connection.target_port.kind)
                if not port_kinds_compatible(source_kind, target_kind):
                    if connection.source_node.definition.type_id == "graph.receive":
                        connection.set_broken(True)
                    else:
                        invalid.append(connection)
                else:
                    connection.set_broken(False)
            if not invalid:
                break
            for connection in invalid:
                self._remove_connection_internal(connection)
                removed += 1
            self._resolve_dynamic_types()
        return removed

    def can_connect(self, first_port: PortItem, second_port: PortItem) -> tuple[bool, str]:
        first = self._resolve_port(first_port)
        second = self._resolve_port(second_port)
        if first is None or second is None:
            return False, "Missing connection endpoint"
        if first.is_output == second.is_output:
            return False, "Connect an output to an input"
        source = first if first.is_output else second
        target = second if not second.is_output else first
        if source.owner is target.owner:
            return False, "A node cannot connect to itself"

        source_kind = normalise_port_kind(source.kind)
        target_declared = normalise_port_kind(target.declared_kind)
        target_kind = normalise_port_kind(target.kind)

        if target_declared == "any":
            if source_kind in {"grayscale", "color", "vector", "material", "geometry", "scalar", "vector2", "vector3"}:
                return True, ""
            return False, "Graph Output requires a concrete typed value"

        if isinstance(target.owner, NodeItem) and target.owner.definition.type_id == "graph.send":
            if source_kind in {"grayscale", "color", "vector", "material", "geometry", "scalar", "vector2", "vector3"}:
                return True, ""
            return False, "Send requires a concrete image, material, geometry, scalar, or vector value"

        if is_image_kind(source_kind):
            if not is_image_kind(target_declared):
                target_label = self._kind_label(target_declared)
                return False, f"{self._kind_label(source_kind)} image cannot connect to a {target_label} input"
            if target_declared == "image_any":
                target_node = target.owner
                if isinstance(target_node, NodeItem):
                    policy = target_node.definition.type_policy
                    if target_node.definition.gpu_spec is not None and target_node.definition.gpu_spec.format_policy == "preserve_first":
                        policy = "preserve_primary"
                    if policy == "blend_match":
                        other_names = [name for name in ("Foreground", "Background") if name != target.name]
                        locked = next((self._connection_source_kind(target_node, name) for name in other_names if self._connection_source_kind(target_node, name)), None)
                        if locked is not None and source_kind != locked:
                            return False, f"Blend inputs must both be {self._kind_label(locked)}"
                    elif policy == "preserve_primary":
                        primary = target_node.definition.primary_input or (target_node.definition.inputs[0] if target_node.definition.inputs else "")
                        if target.name != primary:
                            locked = self._connection_source_kind(target_node, primary)
                            if locked is not None and source_kind != locked:
                                return False, f"This branch is {self._kind_label(locked)}; use an explicit conversion node"
                prospective_error = self._prospective_connection_error(source, target)
                if prospective_error:
                    return False, prospective_error
                return True, ""
            if source_kind != target_kind:
                return False, (
                    f"{self._kind_label(source_kind)} output cannot connect to "
                    f"{self._kind_label(target_kind)} input. Use an explicit conversion node."
                )
            return True, ""

        if is_image_kind(target_declared):
            return False, f"{self._kind_label(source_kind)} cannot connect to an image input"
        if not port_kinds_compatible(source_kind, target_kind):
            return False, f"{source_kind} cannot connect to {target_kind}"
        return True, ""

    # ------------------------------------------------------------------
    # Undo transaction support
    # ------------------------------------------------------------------
    def begin_user_action(self, text: str, *, merge_key: str | None = None) -> None:
        if self._restoring:
            return
        if self._action_depth == 0:
            self._action_before = self.to_dict()
            self._action_text = text
            self._action_changed = False
            self._action_merge_key = merge_key
        self._action_depth += 1

    def end_user_action(self, *, merge_key: str | None = None) -> None:
        if self._restoring or self._action_depth <= 0:
            return
        self._action_depth -= 1
        if self._action_depth:
            return
        before = self._action_before
        self._action_before = None
        effective_merge_key = merge_key if merge_key is not None else self._action_merge_key
        self._action_merge_key = None
        if before is None or not self._action_changed:
            self._action_changed = False
            return
        after = self.to_dict()
        if before == after:
            self._action_changed = False
            return
        command = GraphSnapshotCommand(
            self,
            before,
            after,
            self._action_text,
            merge_key=effective_merge_key,
            already_applied=True,
        )
        self.undo_stack.push(command)
        self._action_changed = False
        self.graphChanged.emit()

    def _touch(self) -> None:
        if self._restoring or self._constructing:
            return
        if self._action_depth:
            self._action_changed = True
        else:
            # Defensive fallback for a future edit path that forgot to open an
            # action. It still refreshes correctly, but won't be undoable.
            self.graphChanged.emit()

    def consume_graph_change_hint(self) -> tuple[str, str] | None:
        hint = self._graph_change_hint
        self._graph_change_hint = None
        return hint

    def perform_action(
        self,
        text: str,
        operation: Callable[[], Any],
        *,
        merge_key: str | None = None,
    ) -> Any:
        self.begin_user_action(text, merge_key=merge_key)
        try:
            return operation()
        finally:
            self.end_user_action(merge_key=merge_key)

    def restore_snapshot(self, data: dict[str, Any]) -> None:
        self._restoring = True
        try:
            self._load_dict(data)
        finally:
            self._restoring = False
        self.graphChanged.emit()
        self.groupsChanged.emit()
        self._selection_changed()

    # ------------------------------------------------------------------
    # Nodes and connections
    # ------------------------------------------------------------------
    def create_node(
        self,
        type_id: str,
        position: QPointF,
        *,
        uid: str | None = None,
        parameters: dict | None = None,
        group_uid: str | None = None,
        emit_change: bool = True,
        record_undo: bool | None = None,
    ) -> NodeItem:
        if record_undo is None:
            record_undo = emit_change

        result: NodeItem | None = None

        def create() -> None:
            nonlocal result
            result = self._create_node_internal(
                type_id,
                position,
                uid=uid,
                parameters=parameters,
                group_uid=group_uid,
            )
            if group_uid is None:
                self._assign_new_node_to_containing_group(result)
            self._touch()

        if record_undo:
            self.perform_action("Add Node", create)
        else:
            self._constructing = True
            try:
                create()
            finally:
                self._constructing = False
        assert result is not None
        return result

    def _create_node_internal(
        self,
        type_id: str,
        position: QPointF,
        *,
        uid: str | None = None,
        parameters: dict | None = None,
        group_uid: str | None = None,
    ) -> NodeItem:
        migrated_parameters = dict(parameters or {})
        definition = (
            graph_instance_definition(migrated_parameters)
            if type_id == GRAPH_INSTANCE_TYPE and migrated_parameters.get("_asset_interface")
            else self.registry.get(type_id)
        )
        effective_parameters = definition.default_parameters()
        # Track caller-supplied values before applying any node-specific defaults.
        # Canvas nodes are commonly created without an explicit parameter mapping,
        # so this must exist before the Canvas default-size branch below.
        provided = set(migrated_parameters)
        if type_id == "material.pbr":
            legacy_surface = str(migrated_parameters.get("surface_mode", "Opaque"))
            migrated_parameters["surface_mode"] = {
                "Cutout": "Alpha Cutout",
                "Transparent": "Alpha Blend",
            }.get(legacy_surface, legacy_surface)
        if type_id == "output.texture_set":
            # 0.44.x called the generic built-in preset Separate PBR Maps.
            # Keep old documents visually and functionally identical while
            # moving them onto the editable export-template model.
            if str(migrated_parameters.get("export_preset", "")) == "Separate PBR Maps":
                migrated_parameters["export_preset"] = "Generic PBR Separate"
        if type_id == "pattern.tile_sampler":
            # 0.43.6 and earlier offered a no-op Offset Mode and a signed
            # -0.5..0.5 amount. Preserve the authored layout while presenting
            # the clearer always-active 0..1 offset interface. Negative offsets
            # are equivalent modulo one tile cell.
            legacy_offset_mode = str(migrated_parameters.get("offset_mode", ""))
            if legacy_offset_mode == "None":
                migrated_parameters["offset_mode"] = "Every Second Row"
                migrated_parameters["row_offset"] = 0.0
            elif "row_offset" in migrated_parameters:
                try:
                    legacy_offset = float(migrated_parameters["row_offset"])
                    if legacy_offset < 0.0:
                        migrated_parameters["row_offset"] = legacy_offset % 1.0
                except (TypeError, ValueError):
                    migrated_parameters["row_offset"] = 0.0
            # Tile Value and the clipped legacy luminance model were removed.
            # Strip stale keys from any pre-release graph instead of retaining a
            # second behaviour path.
            migrated_parameters.pop("tile_value", None)
            migrated_parameters.pop("_legacy_luminance_model", None)
        if type_id == "noise.crystal_1" and "scale" in migrated_parameters:
            # 0.47.0.6 replaced the scalar experimental Crystal 1 control
            # with the Scale X/Y model used by the corrected dual-Voronoi
            # construction. Preserve the authored density on both axes.
            try:
                legacy_scale = float(migrated_parameters.pop("scale"))
            except (TypeError, ValueError):
                legacy_scale = 16.0
            migrated_parameters.setdefault("scale_x", legacy_scale)
            migrated_parameters.setdefault("scale_y", legacy_scale)
            provided.update({"scale_x", "scale_y"})
            migrated_parameters.pop("jitter", None)
            migrated_parameters.pop("facet_sharpness", None)
        if type_id in {"transform.basic", "normal.transform"}:
            if "boundary" not in migrated_parameters and "tile" in migrated_parameters:
                migrated_parameters["boundary"] = (
                    "Seamless / Wrap" if bool(migrated_parameters.get("tile", True)) else "Transparent"
                )
                # This value was caller-authored under the legacy key. Mark the
                # migrated replacement as provided so document defaults do not
                # overwrite it later in this constructor.
                provided.add("boundary")
            migrated_parameters.pop("tile", None)
        if type_id in {"transform.offset", "transform.rotate", "transform.scale"}:
            if "boundary" not in migrated_parameters and "wrap" in migrated_parameters:
                migrated_parameters["boundary"] = (
                    "Seamless / Wrap" if bool(migrated_parameters.get("wrap", True)) else "Transparent"
                )
                provided.add("boundary")
            migrated_parameters.pop("wrap", None)
        if str(migrated_parameters.get("filtering", "")) == "Auto":
            migrated_parameters["filtering"] = "Automatic"
            provided.add("filtering")
        if type_id in {"filter.make_it_tile_photo", "material.make_it_tile_photo"}:
            # 0.46.2.1 replaced the initial blurred-seam controls with
            # independent warped cut masks. Migrate only caller-authored legacy
            # values here, before defaults are merged, so new graphs retain the
            # current asymmetric H/V defaults and graphs already containing the
            # new keys always take precedence.
            if "mask_size_h" not in migrated_parameters and "seam_width" in migrated_parameters:
                try:
                    legacy_width = min(max(float(migrated_parameters["seam_width"]), 0.001), 0.5)
                except (TypeError, ValueError):
                    legacy_width = 0.14
                migrated_parameters["mask_size_h"] = legacy_width
                migrated_parameters["mask_size_v"] = legacy_width
            if "mask_precision_h" not in migrated_parameters and "detail_preservation" in migrated_parameters:
                try:
                    legacy_detail = min(max(float(migrated_parameters["detail_preservation"]), 0.0), 1.0)
                except (TypeError, ValueError):
                    legacy_detail = 0.35
                migrated_parameters["mask_precision_h"] = legacy_detail
                migrated_parameters["mask_precision_v"] = legacy_detail
            for obsolete_key in ("seam_width", "seam_blur", "detail_preservation"):
                migrated_parameters.pop(obsolete_key, None)
        if type_id == "filter.levels" and any(key in migrated_parameters for key in ("black", "white", "gamma")):
            # Legacy 0.13.2 Levels graphs used black/white/gamma. Preserve the
            # closest equivalent while moving to the five-point Levels model.
            black = float(migrated_parameters.pop("black", 0.0))
            white = float(migrated_parameters.pop("white", 1.0))
            gamma = max(float(migrated_parameters.pop("gamma", 1.0)), 1e-5)
            span = max(white - black, 1e-6)
            # Old output was t ** (1/gamma). Find the absolute input tone that
            # maps to 0.5 under the new mid-point representation.
            mid_normalized = 0.5 ** gamma
            migrated_parameters.setdefault("in_low", black)
            migrated_parameters.setdefault("in_high", white)
            migrated_parameters.setdefault("in_mid", mid_normalized)
            migrated_parameters.setdefault("out_low", 0.0)
            migrated_parameters.setdefault("out_high", 1.0)
            migrated_parameters.setdefault("intermediary_clamp", True)
        if migrated_parameters:
            effective_parameters.update(migrated_parameters)
        if type_id == "input.canvas":
            default_width, default_height = self.canvas_default_size
            if "canvas_width" not in provided:
                effective_parameters["canvas_width"] = int(default_width)
            if "canvas_height" not in provided:
                effective_parameters["canvas_height"] = int(default_height)
            effective_parameters["background_value"] = 0.0
            effective_parameters = ensure_canvas_parameters(effective_parameters)
        for key in ("tile", "repeat"):
            if key in effective_parameters and key not in provided:
                effective_parameters[key] = bool(self.default_tiling)
        if "wrap" in effective_parameters and "wrap" not in provided:
            effective_parameters["wrap"] = "Tile" if self.default_tiling else "Clamp"
        if "boundary" in effective_parameters and "boundary" not in provided:
            effective_parameters["boundary"] = "Seamless / Wrap" if self.default_tiling else "Transparent"
        if "rasterization" in effective_parameters and "rasterization" not in provided:
            if parameters is None:
                effective_parameters["rasterization"] = str(self.default_geometric_rasterization)
            else:
                # 0.43.3 and earlier stored no rasterisation field because zero
                # softness was always binary. Preserve those authored graphs.
                effective_parameters["rasterization"] = "Pixel Exact"
        if type_id == "input.image":
            try:
                from ..nodes.input_nodes import refresh_image_metadata
                refresh_image_metadata(effective_parameters)
            except Exception:
                pass
        elif type_id == "input.mesh":
            try:
                from ..geometry import refresh_mesh_metadata
                refresh_mesh_metadata(effective_parameters)
            except Exception:
                pass
        if type_id == "graph.send":
            effective_parameters["channel_name"] = self._unique_portal_name(
                str(effective_parameters.get("channel_name", "Channel")),
                excluding_uid=uid,
            )
        if type_id == "graph.reroute":
            item_class = RerouteItem
        elif type_id in {"graph.send", "graph.receive"}:
            item_class = PortalNodeItem
        else:
            item_class = NodeItem
        node = item_class(
            definition,
            uid=uid,
            parameters=effective_parameters,
            group_uid=group_uid,
        )
        node.setPos(position)
        self.nodes[node.uid] = node
        self.addItem(node)
        self._resolve_dynamic_types()
        return node

    def create_graph_instance(
        self, path: str | Path, position: QPointF, *, embedded: bool = False, record_undo: bool = True
    ) -> NodeItem:
        source = Path(path).expanduser().resolve()
        data, interface = load_graph_asset(source, self.registry)
        parameters = instance_parameters_for_asset(
            data, interface, source_path=source, embedded=embedded
        )
        try:
            parameters["_asset_mtime_ns"] = int(source.stat().st_mtime_ns)
        except OSError:
            parameters["_asset_mtime_ns"] = 0
        parameters["_asset_status"] = "Embedded" if embedded else "Linked"
        return self.create_node(
            GRAPH_INSTANCE_TYPE, position, parameters=parameters, record_undo=record_undo
        )

    @staticmethod
    def _asset_connected_ports(node: NodeItem, connections: list[ConnectionItem]) -> tuple[set[str], set[str]]:
        input_names = {
            connection.input_name for connection in connections
            if connection.target_node is node
        }
        output_names = {
            connection.output_name for connection in connections
            if connection.source_node is node
        }
        return input_names, output_names

    @staticmethod
    def _preserve_removed_asset_ports(
        old_interface: dict[str, Any],
        new_interface: dict[str, Any],
        connected_inputs: set[str],
        connected_outputs: set[str],
    ) -> dict[str, Any]:
        """Keep removed linked-asset sockets visible while they are connected.

        Stable interface IDs preserve ordinary renames.  When an author truly
        removes a socket, retaining a clearly labelled legacy port is safer than
        silently deleting the parent graph connection.
        """
        merged = deepcopy(new_interface)
        for key, connected in (("inputs", connected_inputs), ("outputs", connected_outputs)):
            current = {str(entry.get("port", "")) for entry in merged.get(key, ())}
            for entry in old_interface.get(key, ()):
                port = str(entry.get("port", ""))
                if not port or port in current or port not in connected:
                    continue
                legacy = deepcopy(dict(entry))
                legacy["missing"] = True
                legacy["name"] = f"{legacy.get('name', 'Port')} (missing)"
                legacy["description"] = "This socket was removed from the linked graph asset. Relink it before disconnecting if it should be preserved."
                merged.setdefault(key, []).append(legacy)
        warnings = list(merged.get("warnings", ()))
        if any(entry.get("missing") for key in ("inputs", "outputs") for entry in merged.get(key, ())):
            warnings.append("One or more connected sockets no longer exist in the linked graph asset.")
        merged["warnings"] = warnings
        return merged

    def _apply_graph_instance_asset(
        self,
        node: NodeItem,
        data: dict[str, Any],
        interface: dict[str, Any],
        *,
        source_path: str | Path | None,
        embedded: bool,
        touch: bool = True,
    ) -> None:
        if node.definition.type_id != GRAPH_INSTANCE_TYPE:
            raise ValueError("The selected node is not a Graph Instance.")
        incident = [
            connection for connection in self.connections
            if connection.source_node is node or connection.target_node is node
        ]
        connected_inputs, connected_outputs = self._asset_connected_ports(node, incident)
        old_interface = dict(node.parameters.get("_asset_interface", {}))
        interface = self._preserve_removed_asset_ports(
            old_interface, interface, connected_inputs, connected_outputs
        )
        records = [
            (connection.source_node.uid, connection.output_name, connection.target_node.uid, connection.input_name)
            for connection in incident
        ]
        for connection in incident:
            self._remove_connection_internal(connection)

        source = Path(source_path).expanduser().resolve() if source_path else None
        override_names = {
            str(value) for value in node.parameters.get("_asset_parameter_overrides", ())
        }
        previous_values = {
            str(entry.get("id", "")): deepcopy(node.parameters.get(f"asset_param::{entry.get('id', '')}"))
            for entry in old_interface.get("parameters", ())
            if isinstance(entry, dict)
            and f"asset_param::{entry.get('id', '')}" in override_names
        }
        fresh = instance_parameters_for_asset(
            data, interface, source_path=source, embedded=embedded
        )
        fresh["random_seed"] = int(node.parameters.get("random_seed", 0))
        fresh["_asset_parameter_overrides"] = sorted(override_names)
        for entry in interface.get("parameters", ()):
            interface_id = str(entry.get("id", ""))
            key = f"asset_param::{interface_id}"
            if interface_id in previous_values and previous_values[interface_id] is not None:
                fresh[key] = previous_values[interface_id]
        if source is not None:
            try:
                fresh["_asset_mtime_ns"] = int(source.stat().st_mtime_ns)
            except OSError:
                fresh["_asset_mtime_ns"] = 0
        else:
            fresh["_asset_mtime_ns"] = 0
        fresh["_asset_status"] = "Embedded" if embedded else "Linked"
        # Preserve parent-level exposed sockets and any UI-only overrides.
        for key, value in node.parameters.items():
            if key.startswith("_exposed_") or key.startswith("_graph_asset_unpublished"):
                fresh[key] = deepcopy(value)
        node.parameters = fresh
        node.replace_definition(graph_instance_definition(fresh))
        if node is self.active_node:
            if self.active_output_name not in node.output_ports:
                self.active_output_name = None
            node.set_active_output(self.active_output_name)

        for source_uid, output_name, target_uid, input_name in records:
            source_node = self.nodes.get(source_uid)
            target_node = self.nodes.get(target_uid)
            if source_node is None or target_node is None:
                continue
            source_port = source_node.output_ports.get(output_name)
            target_port = target_node.input_ports.get(input_name)
            if source_port is None or target_port is None:
                continue
            connection = ConnectionItem(source_port, target_port)
            self.connections.append(connection)
            self.addItem(connection)
            valid, _reason = self.can_connect(source_port, target_port)
            connection.set_broken(not valid)
        self._resolve_dynamic_types()
        self._refresh_all_groups()
        self._update_all_connections()
        if touch:
            self._touch()
        if node.isSelected():
            self.selectedNodeChanged.emit(node)

    def reload_graph_instance(
        self, node: NodeItem, *, path: str | Path | None = None, record_undo: bool = True
    ) -> bool:
        if node.definition.type_id != GRAPH_INSTANCE_TYPE:
            return False
        source_text = str(path or node.parameters.get("_asset_path", "")).strip()
        if not source_text:
            return False
        source = Path(source_text).expanduser().resolve()
        data, interface = load_graph_asset(source, self.registry)

        def apply() -> None:
            self._apply_graph_instance_asset(
                node, data, interface, source_path=source, embedded=False
            )

        if record_undo:
            self.perform_action("Reload Graph Asset", apply)
        else:
            self._constructing = True
            try:
                apply()
            finally:
                self._constructing = False
            self.graphChanged.emit()
        return True

    def embed_graph_instance(self, node: NodeItem) -> bool:
        if node.definition.type_id != GRAPH_INSTANCE_TYPE:
            return False
        data = deepcopy(node.parameters.get("_asset_cached_graph"))
        interface = deepcopy(node.parameters.get("_asset_interface"))
        if not isinstance(data, dict) or not isinstance(interface, dict):
            return False

        def apply() -> None:
            self._apply_graph_instance_asset(
                node, data, interface, source_path=node.parameters.get("_asset_path") or None, embedded=True
            )

        self.perform_action("Embed Graph Asset", apply)
        return True

    def relink_graph_instance(self, node: NodeItem, path: str | Path) -> bool:
        return self.reload_graph_instance(node, path=path, record_undo=True)

    def matching_graph_instances(self, reference: NodeItem) -> list[NodeItem]:
        if reference.definition.type_id != GRAPH_INSTANCE_TYPE:
            return []
        identity = str(reference.parameters.get("_asset_identity", "") or "").strip()
        path_text = str(reference.parameters.get("_asset_path", "") or "").strip()
        matches: list[NodeItem] = []
        for candidate in self.nodes.values():
            if candidate.definition.type_id != GRAPH_INSTANCE_TYPE:
                continue
            candidate_identity = str(candidate.parameters.get("_asset_identity", "") or "").strip()
            candidate_path = str(candidate.parameters.get("_asset_path", "") or "").strip()
            if identity and candidate_identity == identity:
                matches.append(candidate)
            elif not identity and path_text and candidate_path == path_text:
                matches.append(candidate)
            elif candidate is reference:
                matches.append(candidate)
        return matches

    def relink_matching_graph_instances(self, reference: NodeItem, path: str | Path) -> int:
        targets = self.matching_graph_instances(reference)
        if not targets:
            return 0
        source = Path(path).expanduser().resolve()
        data, interface = load_graph_asset(source, self.registry)

        def apply() -> None:
            for target in targets:
                self._apply_graph_instance_asset(
                    target, deepcopy(data), deepcopy(interface),
                    source_path=source, embedded=False,
                )

        self.perform_action(
            "Relink Matching Graph Assets" if len(targets) > 1 else "Relink Graph Asset",
            apply,
        )
        return len(targets)

    def restore_cached_graph_instance(
        self, node: NodeItem, path: str | Path, *, relink: bool = True,
        owner_graph_path: str | Path | None = None,
    ) -> bool:
        if node.definition.type_id != GRAPH_INSTANCE_TYPE:
            return False
        cached = node.parameters.get("_asset_cached_graph")
        if not isinstance(cached, dict):
            return False
        destination = Path(path).expanduser()
        if destination.suffix.lower() != ".vfxgraph":
            destination = destination.with_suffix(".vfxgraph")
        # A recovered cache may itself contain linked children or external
        # images. Make the restored source self-contained so it does not merely
        # move the missing-dependency problem into a new file.
        from ..portable_graph import build_self_contained_graph
        original_text = str(node.parameters.get("_asset_path", "") or "").strip()
        original_owner = None
        if original_text:
            from ..portable_graph import resolve_authored_path
            try:
                original_owner = resolve_authored_path(original_text, owner_graph_path)
            except ValueError:
                original_candidate = Path(original_text).expanduser()
                if original_candidate.is_absolute():
                    original_owner = original_candidate
        restored, _report = build_self_contained_graph(
            cached, owner_path=original_owner
        )
        # Validate before writing, then use an atomic replacement so a failed
        # recovery can never leave a half-written graph file behind.
        interface = parse_graph_asset_interface(restored, self.registry, source_path=destination)
        if not interface.get("outputs"):
            raise ValueError("The cached revision has no connected Graph Output nodes.")
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(restored, indent=2), encoding="utf-8")
        temporary.replace(destination)
        if relink:
            self.reload_graph_instance(node, path=destination, record_undo=True)
        return True

    @staticmethod
    def _file_resource_kind(node: NodeItem) -> str | None:
        if node.definition.type_id == "input.image":
            return "image"
        if node.definition.type_id == "input.mesh":
            return "mesh"
        return None

    def matching_file_inputs(self, reference: NodeItem) -> list[NodeItem]:
        kind = self._file_resource_kind(reference)
        if kind is None:
            return []
        path_text = str(reference.parameters.get("path", "") or "").strip()
        return [
            candidate for candidate in self.nodes.values()
            if self._file_resource_kind(candidate) == kind
            and (
                candidate is reference
                or (
                    path_text
                    and str(candidate.parameters.get("path", "") or "").strip() == path_text
                )
            )
        ]

    def relink_file_inputs(
        self, reference: NodeItem, path: str | Path, *, matching: bool = False
    ) -> int:
        kind = self._file_resource_kind(reference)
        if kind is None:
            return 0
        targets = self.matching_file_inputs(reference) if matching else [reference]
        source = str(Path(path).expanduser().resolve())
        noun = "Mesh" if kind == "mesh" else "Image"

        def apply() -> None:
            if kind == "mesh":
                from ..geometry import refresh_mesh_metadata as refresh_metadata
            else:
                from ..nodes.input_nodes import refresh_image_metadata as refresh_metadata
            for target in targets:
                target.parameters["path"] = source
                target.parameters["embedded"] = False
                target.parameters.pop("_embedded_data", None)
                target.parameters.pop("_embedded_name", None)
                target.parameters.pop("_embedded_original_name", None)
                target.parameters.pop("_resource_sha256", None)
                target.parameters.pop("_packaged_source_path", None)
                target.parameters.pop("_packaged_source_sha256", None)
                refresh_metadata(target.parameters)
            if kind == "image":
                self._resolve_dynamic_types()
                self._remove_incompatible_connections()
            self._refresh_all_groups()
            self._touch()

        self.perform_action(
            f"Relink Matching {noun}s" if matching and len(targets) > 1 else f"Relink {noun}",
            apply,
        )
        return len(targets)

    def embed_file_input(self, node: NodeItem, *, source_path: str | Path | None = None) -> bool:
        kind = self._file_resource_kind(node)
        if kind is None:
            return False
        encoded = str(node.parameters.get("_embedded_data", "") or "").strip()
        data: bytes | None = None
        if encoded:
            try:
                data = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error):
                data = None
        source = Path(source_path).expanduser().resolve() if source_path else None
        if source is not None and source.is_file():
            data = source.read_bytes()
        if data is None:
            return False
        original_text = str(node.parameters.get("path", "") or "").strip()
        embedded_name = source.name if source is not None else str(
            node.parameters.get("_embedded_name", "") or ""
        )
        if not embedded_name and original_text:
            embedded_name = Path(original_text).name
        fallback_name = "embedded-mesh.obj" if kind == "mesh" else "embedded-image"
        noun = "Mesh" if kind == "mesh" else "Image"

        def apply() -> None:
            node.parameters["embedded"] = True
            node.parameters["path"] = ""
            node.parameters["_embedded_data"] = base64.b64encode(data).decode("ascii")
            node.parameters.pop("_resource_sha256", None)
            node.parameters["_embedded_name"] = embedded_name or fallback_name
            if original_text:
                node.parameters["_embedded_original_name"] = Path(original_text).name
            if kind == "mesh":
                from ..geometry import refresh_mesh_metadata
                refresh_mesh_metadata(node.parameters)
            else:
                from ..nodes.input_nodes import refresh_image_metadata
                refresh_image_metadata(node.parameters)
                self._resolve_dynamic_types()
                self._remove_incompatible_connections()
            self._refresh_all_groups()
            self._touch()

        self.perform_action(f"Make {noun} Local", apply)
        return True

    def restore_embedded_file(
        self, node: NodeItem, path: str | Path, *, relink: bool = True
    ) -> bool:
        kind = self._file_resource_kind(node)
        if kind is None:
            return False
        encoded = str(node.parameters.get("_embedded_data", "") or "").strip()
        if not encoded:
            return False
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError(f"The embedded {kind} data is damaged.") from exc
        destination = Path(path).expanduser()
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(data)
        temporary.replace(destination)
        if relink:
            self.relink_file_inputs(node, destination, matching=False)
        return True

    # Backwards-compatible Image Input helpers used by existing UI/tests.
    def matching_image_inputs(self, reference: NodeItem) -> list[NodeItem]:
        return self.matching_file_inputs(reference) if reference.definition.type_id == "input.image" else []

    def relink_image_inputs(
        self, reference: NodeItem, path: str | Path, *, matching: bool = False
    ) -> int:
        return self.relink_file_inputs(reference, path, matching=matching) if reference.definition.type_id == "input.image" else 0

    def embed_image_input(self, node: NodeItem, *, source_path: str | Path | None = None) -> bool:
        return self.embed_file_input(node, source_path=source_path) if node.definition.type_id == "input.image" else False

    def restore_embedded_image(
        self, node: NodeItem, path: str | Path, *, relink: bool = True
    ) -> bool:
        return self.restore_embedded_file(node, path, relink=relink) if node.definition.type_id == "input.image" else False

    def matching_mesh_inputs(self, reference: NodeItem) -> list[NodeItem]:
        return self.matching_file_inputs(reference) if reference.definition.type_id == "input.mesh" else []

    def relink_mesh_inputs(
        self, reference: NodeItem, path: str | Path, *, matching: bool = False
    ) -> int:
        return self.relink_file_inputs(reference, path, matching=matching) if reference.definition.type_id == "input.mesh" else 0

    def embed_mesh_input(self, node: NodeItem, *, source_path: str | Path | None = None) -> bool:
        return self.embed_file_input(node, source_path=source_path) if node.definition.type_id == "input.mesh" else False

    def restore_embedded_mesh(
        self, node: NodeItem, path: str | Path, *, relink: bool = True
    ) -> bool:
        return self.restore_embedded_file(node, path, relink=relink) if node.definition.type_id == "input.mesh" else False

    def refresh_linked_graph_assets(self) -> list[tuple[str, str]]:
        """Poll linked files and reload changed assets without interrupting editing."""
        changes: list[tuple[str, str]] = []
        for node in list(self.nodes.values()):
            if node.definition.type_id != GRAPH_INSTANCE_TYPE:
                continue
            if str(node.parameters.get("_asset_mode", "Linked")) != "Linked":
                continue
            source_text = str(node.parameters.get("_asset_path", "")).strip()
            if not source_text:
                continue
            source = Path(source_text).expanduser()
            try:
                mtime = int(source.stat().st_mtime_ns)
            except OSError:
                if node.parameters.get("_asset_status") != "Missing source":
                    node.parameters["_asset_status"] = "Missing source"
                    node.set_error("Linked graph asset is missing. The last cached revision remains usable.")
                    changes.append((node.uid, "missing"))
                continue
            node.set_error(None)
            previous = int(node.parameters.get("_asset_mtime_ns", 0) or 0)
            if previous and mtime == previous:
                if node.parameters.get("_asset_status") != "Linked":
                    node.parameters["_asset_status"] = "Linked"
                continue
            try:
                self.reload_graph_instance(node, path=source, record_undo=False)
                changes.append((node.uid, "reloaded"))
            except Exception as exc:
                node.parameters["_asset_status"] = "Reload failed"
                node.set_error(f"Could not reload linked graph asset: {exc}")
                changes.append((node.uid, "error"))
        return changes

    def _assign_new_node_to_containing_group(self, node: NodeItem) -> None:
        candidates = [group for group in self.groups.values() if not group.collapsed and group.contains_node(node)]
        if not candidates:
            return
        candidates.sort(key=lambda group: group.frame_width * group.frame_height)
        group = candidates[0]
        node.group_uid = group.uid
        group.members.add(node.uid)
        group.rebuild_ports(self)
        self.groupsChanged.emit()

    def set_active_node(
        self, node: NodeItem | None, *, output_name: str | None = None, force: bool = False
    ) -> None:
        resolved_output = None
        if node is not None and output_name is not None:
            candidate = str(output_name)
            if candidate in node.output_ports:
                resolved_output = candidate
        if node is self.active_node and resolved_output == self.active_output_name:
            if force:
                self.activeNodeChanged.emit(node)
            return
        if self.active_node is not None:
            self.active_node.set_active(False)
            self.active_node.set_active_output(None)
        self.active_node = node
        self.active_output_name = resolved_output
        if node is not None:
            node.set_active(True)
            node.set_active_output(resolved_output)
        self.activeNodeChanged.emit(node)

    def set_active_output(self, node: NodeItem, output_name: str, *, force: bool = True) -> None:
        self.set_active_node(node, output_name=output_name, force=force)

    def toggle_node_thumbnail(self, node: NodeItem) -> None:
        if node.uid not in self.nodes or node.is_docked or not node.supports_thumbnail():
            return

        def operation() -> None:
            node.set_thumbnail_enabled(not node.thumbnail_enabled)
            self.update_connections_for_node(node)
            self._refresh_docked_layout()
            self._touch()

        self.perform_action("Show Node Thumbnail" if not node.thumbnail_enabled else "Hide Node Thumbnail", operation)
        self.thumbnailChanged.emit(node)

    def set_node_thumbnail_output(self, node: NodeItem, output_name: str) -> None:
        if node.uid not in self.nodes or not node.supports_thumbnail():
            return
        output_name = str(output_name or "")
        if output_name not in node.thumbnail_output_names():
            return

        def operation() -> None:
            if node.set_thumbnail_output(output_name):
                self._touch()

        self.perform_action("Change Node Thumbnail Output", operation)
        self.thumbnailChanged.emit(node)

    def node_moved(self, node: NodeItem) -> None:
        self.update_connections_for_node(node)
        self._refresh_docked_layout()
        selected = [item for item in self.selectedItems() if isinstance(item, PortalNodeItem)]
        if selected:
            self._refresh_portal_debug(selected[0] if len(selected) == 1 else None)
        if self._updating_docks:
            return
        if not self._moving_group:
            self._touch()

    def update_connections_for_node(self, node: NodeItem) -> None:
        for connection in self.connections:
            if connection.source_node is node or connection.target_node is node:
                connection.update_path()

    def outgoing_connections(self, node: NodeItem) -> list[ConnectionItem]:
        return [connection for connection in self.connections if connection.source_node is node]

    def node_can_dock(self, node: NodeItem) -> bool:
        if isinstance(node, RerouteItem) or node.definition.terminal:
            return False
        if len(node.definition.output_names) != 1:
            return False
        visible_inputs = [port for port in node.input_ports.values() if port.isVisible()]
        if len(visible_inputs) > 1:
            return False
        outgoing = self.outgoing_connections(node)
        return (
            len(outgoing) == 1
            and not outgoing[0].broken
            and isinstance(outgoing[0].target_node, NodeItem)
            and node.group_uid == outgoing[0].target_node.group_uid
        )

    def toggle_node_dock(self, node: NodeItem) -> bool:
        if node.is_docked:
            def undock() -> None:
                restore = QPointF(node.undocked_position)
                node.set_docked(None)
                self._updating_docks = True
                try:
                    node.setPos(restore)
                finally:
                    self._updating_docks = False
                self._refresh_docked_layout()
                self._touch()
            self.perform_action("Undock Node", undock)
            return True
        if not self.node_can_dock(node):
            return False
        connection = self.outgoing_connections(node)[0]

        def dock() -> None:
            node.set_docked(connection.target_node.uid, undocked_position=node.pos())
            self._refresh_docked_layout()
            self._touch()

        self.perform_action("Dock Node", dock)
        return True

    def toggle_selected_node_dock(self) -> bool:
        nodes = self.selected_nodes()
        if len(nodes) != 1:
            return False
        return self.toggle_node_dock(nodes[0])

    def _refresh_docked_layout(self) -> None:
        if self._updating_docks:
            return
        self._updating_docks = True
        try:
            for _pass in range(max(len(self.nodes), 1) + 1):
                changed = False
                for node in self.nodes.values():
                    if not node.is_docked:
                        continue
                    parent = self.nodes.get(str(node.docked_to_uid or ""))
                    outgoing = self.outgoing_connections(node)
                    matching = next((
                        connection for connection in outgoing
                        if connection.target_node is parent and not connection.broken
                    ), None)
                    if (
                        parent is None
                        or matching is None
                        or len(outgoing) != 1
                        or node.group_uid != parent.group_uid
                    ):
                        restore = QPointF(node.undocked_position)
                        node.set_docked(None)
                        node.setPos(restore)
                        changed = True
                        continue
                    target = matching.target_port.centre_scene_pos()
                    desired = QPointF(target.x() - node.width, target.y() - node.height * 0.5)
                    if (node.pos() - desired).manhattanLength() > 0.01:
                        node.setPos(desired)
                        changed = True
                if not changed:
                    break
            self._update_all_connections()
        finally:
            self._updating_docks = False

    def _resolve_port(self, port: PortItem) -> PortItem | None:
        if not isinstance(port, GroupPortItem):
            return port
        node = self.nodes.get(port.endpoint_node_uid)
        if node is None:
            return None
        if port.is_output:
            if node.output_port is None or not node.definition.output_names:
                return None
            return node.output_ports.get(port.endpoint_input_name or node.definition.output_names[0], node.output_port)
        if port.endpoint_input_name not in node.input_ports:
            return None
        return node.input_ports[port.endpoint_input_name]

    def add_connection(
        self,
        first_port: PortItem,
        second_port: PortItem,
        *,
        emit_change: bool = True,
        record_undo: bool | None = None,
    ) -> ConnectionItem | None:
        if record_undo is None:
            record_undo = emit_change
        created: ConnectionItem | None = None

        def connect() -> None:
            nonlocal created
            if (
                isinstance(first_port, GroupPortItem)
                and isinstance(second_port, GroupPortItem)
                and first_port.owner is second_port.owner
            ):
                return
            first = self._resolve_port(first_port)
            second = self._resolve_port(second_port)
            if first is None or second is None or first.is_output == second.is_output:
                return
            source_port = first if first.is_output else second
            target_port = second if not second.is_output else first
            if source_port.owner is target_port.owner:
                return
            compatible, _reason = self.can_connect(source_port, target_port)
            if not compatible:
                return
            existing = self.connection_for_input(target_port.owner.uid, target_port.name)
            if existing is not None:
                self._remove_connection_internal(existing)
            created = ConnectionItem(source_port, target_port)
            self.connections.append(created)
            self._refresh_wire_flow()
            self.addItem(created)
            self._resolve_dynamic_types()
            self._remove_incompatible_connections()
            self._refresh_docked_layout()
            self._refresh_all_groups()
            self._touch()

        if record_undo:
            self.perform_action("Connect Nodes", connect)
        else:
            self._constructing = True
            try:
                connect()
            finally:
                self._constructing = False
        return created

    def remove_connection(
        self,
        connection: ConnectionItem,
        *,
        emit_change: bool = True,
        record_undo: bool | None = None,
    ) -> None:
        if record_undo is None:
            record_undo = emit_change

        def remove() -> None:
            if connection not in self.connections:
                return
            self._remove_connection_internal(connection)
            self._resolve_dynamic_types()
            self._remove_incompatible_connections()
            self._refresh_docked_layout()
            self._refresh_all_groups()
            self._touch()

        if record_undo:
            self.perform_action("Disconnect Nodes", remove)
        else:
            remove()

    def _remove_connection_internal(self, connection: ConnectionItem) -> None:
        if connection in self.connections:
            self.connections.remove(connection)
        if connection.scene() is self:
            self.removeItem(connection)

    def connection_for_input(self, node_uid: str, input_name: str) -> ConnectionItem | None:
        for connection in self.connections:
            if connection.target_node.uid == node_uid and connection.input_name == input_name:
                return connection
        return None

    # ------------------------------------------------------------------
    # Graph workflow helpers
    # ------------------------------------------------------------------
    @staticmethod
    def node_is_bypassable(node: NodeItem) -> bool:
        definition = node.definition
        if isinstance(node, RerouteItem) or definition.missing:
            return False
        if definition.type_id.startswith(("input.", "output.", "graph.")):
            return False
        if len(definition.inputs) != 1 or len(definition.output_names) != 1:
            return False
        input_kind = normalise_port_kind(definition.input_kind(definition.inputs[0]))
        output_kind = normalise_port_kind(definition.output_kind(definition.output_names[0]))
        if is_image_kind(input_kind) and is_image_kind(output_kind):
            return True
        return port_kinds_compatible(input_kind, output_kind)

    def toggle_node_bypass(self, node: NodeItem) -> None:
        if not self.node_is_bypassable(node):
            return

        def toggle() -> None:
            node.parameters["_bypassed"] = not bool(node.parameters.get("_bypassed", False))
            node.update()
            self._touch()

        self.perform_action("Bypass Node" if not node.bypassed else "Enable Node", toggle)

    def create_reroute(
        self,
        position: QPointF,
        kind: str,
        *,
        record_undo: bool = True,
    ) -> RerouteItem:
        node = self.create_node(
            "graph.reroute",
            position,
            parameters={"_reroute_kind": normalise_port_kind(kind)},
            record_undo=record_undo,
        )
        assert isinstance(node, RerouteItem)
        return node

    def insert_reroute_on_connection(
        self,
        connection: ConnectionItem,
        position: QPointF,
    ) -> RerouteItem | None:
        if connection not in self.connections:
            return None
        result: RerouteItem | None = None

        def insert() -> None:
            nonlocal result
            source = connection.source_port
            target = connection.target_port
            self._remove_connection_internal(connection)
            result = self._create_node_internal(
                "graph.reroute",
                QPointF(position.x() - RerouteItem.DIAMETER * 0.5, position.y() - RerouteItem.DIAMETER * 0.5),
                parameters={"_reroute_kind": source.kind},
            )
            assert isinstance(result, RerouteItem)
            self._assign_new_node_to_containing_group(result)
            self.add_connection(source, result.input_ports["Input"], record_undo=False)
            self.add_connection(result.output_ports["Output"], target, record_undo=False)
            self.clearSelection()
            result.setSelected(True)
            self._refresh_all_groups()
            self._touch()

        self.perform_action("Add Reroute", insert)
        return result

    def connection_near(
        self,
        position: QPointF,
        tolerance: float = 14.0,
        *,
        exclude_nodes: set[str] | None = None,
    ) -> ConnectionItem | None:
        exclude_nodes = exclude_nodes or set()
        probe = QPainterPath()
        probe.addEllipse(position, tolerance, tolerance)
        candidates: list[tuple[float, ConnectionItem]] = []
        for connection in self.connections:
            if not connection.isVisible():
                continue
            if connection.source_node.uid in exclude_nodes or connection.target_node.uid in exclude_nodes:
                continue
            stroker = QPainterPathStroker()
            stroker.setWidth(max(tolerance * 2.0, 8.0))
            hit_shape = stroker.createStroke(connection.path())
            if not hit_shape.intersects(probe):
                continue
            bounds = connection.path().boundingRect()
            candidates.append(((bounds.center() - position).manhattanLength(), connection))
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1] if candidates else None

    def connections_intersecting_path(
        self,
        path: QPainterPath,
        width: float = 12.0,
    ) -> list[ConnectionItem]:
        stroker = QPainterPathStroker()
        stroker.setWidth(max(width, 4.0))
        cut_shape = stroker.createStroke(path)
        return [
            connection
            for connection in self.connections
            if connection.isVisible() and connection.path().intersects(cut_shape)
        ]

    def cut_connections(self, connections: list[ConnectionItem]) -> int:
        unique = [connection for connection in dict.fromkeys(connections) if connection in self.connections]
        if not unique:
            return 0

        def cut() -> None:
            for connection in unique:
                self._remove_connection_internal(connection)
            self._resolve_dynamic_types()
            self._remove_incompatible_connections()
            self._refresh_docked_layout()
            self._refresh_all_groups()
            self._touch()

        self.perform_action("Cut Wires", cut)
        return len(unique)

    @staticmethod
    def _definition_insert_ports(definition: NodeDefinition, source_kind: str, target_kind: str) -> tuple[str, str] | None:
        if definition.missing or definition.hidden:
            return None
        if len(definition.inputs) != 1 or len(definition.output_names) != 1:
            return None
        input_name = definition.inputs[0]
        output_name = definition.output_names[0]
        input_kind = normalise_port_kind(definition.input_kind(input_name))
        output_kind = normalise_port_kind(definition.output_kind(output_name))
        source_kind = normalise_port_kind(source_kind)
        target_kind = normalise_port_kind(target_kind)
        if not port_kinds_compatible(source_kind, input_kind):
            return None
        if output_kind == "image_any" and is_image_kind(source_kind):
            output_kind = source_kind
        if not port_kinds_compatible(output_kind, target_kind):
            return None
        return input_name, output_name

    def definition_can_insert_on_connection(self, definition: NodeDefinition, connection: ConnectionItem) -> bool:
        if definition.type_id in {"graph.send", "graph.receive"}:
            return False
        return self._definition_insert_ports(
            definition,
            connection.source_port.kind,
            connection.target_port.kind,
        ) is not None

    def definition_accepts_loose_port(self, definition: NodeDefinition, start_port: PortItem) -> bool:
        if definition.missing or definition.hidden:
            return False
        if start_port.is_output:
            if definition.type_id == "graph.send":
                return normalise_port_kind(start_port.kind) in {
                    "grayscale", "color", "vector", "material", "geometry", "scalar", "vector2", "vector3"
                }
            return any(
                port_kinds_compatible(start_port.kind, definition.input_kind(name))
                for name in definition.inputs
            )
        return any(
            port_kinds_compatible(definition.output_kind(name), start_port.kind)
            for name in definition.output_names
        )

    def _best_connection_port(self, node: NodeItem, start_port: PortItem) -> PortItem | None:
        if start_port.is_output:
            names = list(node.input_ports)
            primary = node.definition.primary_input
            if primary in names:
                names.remove(primary)
                names.insert(0, primary)
            for name in names:
                port = node.input_ports[name]
                if self.can_connect(start_port, port)[0]:
                    return port
            return None
        for name in node.definition.output_names:
            port = node.output_ports[name]
            if self.can_connect(port, start_port)[0]:
                return port
        return None

    def create_node_connected(
        self,
        type_id: str,
        position: QPointF,
        start_port: PortItem,
    ) -> NodeItem | None:
        if not self.registry.contains(type_id):
            return None
        result: NodeItem | None = None

        def create() -> None:
            nonlocal result
            result = self._create_node_internal(type_id, position)
            self._assign_new_node_to_containing_group(result)
            endpoint = self._best_connection_port(result, start_port)
            if endpoint is not None:
                self.add_connection(start_port, endpoint, record_undo=False)
            self.clearSelection()
            result.setSelected(True)
            self._touch()

        self.perform_action("Add and Connect Node", create)
        return result

    def insert_node_on_connection(
        self,
        type_id: str,
        position: QPointF,
        connection: ConnectionItem,
    ) -> NodeItem | None:
        if connection not in self.connections or not self.registry.contains(type_id):
            return None
        definition = self.registry.get(type_id)
        port_names = self._definition_insert_ports(
            definition, connection.source_port.kind, connection.target_port.kind
        )
        if port_names is None:
            return None
        input_name, output_name = port_names
        result: NodeItem | None = None

        def insert() -> None:
            nonlocal result
            source = connection.source_port
            target = connection.target_port
            self._remove_connection_internal(connection)
            result = self._create_node_internal(type_id, position)
            bounds = result.boundingRect()
            result.setPos(QPointF(position.x() - bounds.width() * 0.5, position.y() - bounds.height() * 0.5))
            self._assign_new_node_to_containing_group(result)
            self.add_connection(source, result.input_ports[input_name], record_undo=False)
            self.add_connection(result.output_ports[output_name], target, record_undo=False)
            self.clearSelection()
            result.setSelected(True)
            self._touch()

        self.perform_action("Insert Node", insert)
        return result

    def can_insert_existing_node(self, node: NodeItem, connection: ConnectionItem) -> bool:
        if isinstance(node, RerouteItem) or connection not in self.connections:
            return False
        if any(
            existing.source_node is node or existing.target_node is node
            for existing in self.connections
        ):
            return False
        return self._definition_insert_ports(
            node.definition, connection.source_port.kind, connection.target_port.kind
        ) is not None

    def insert_existing_node_on_connection(
        self,
        node: NodeItem,
        connection: ConnectionItem,
        *,
        record_undo: bool = True,
    ) -> bool:
        if not self.can_insert_existing_node(node, connection):
            return False
        input_name, output_name = self._definition_insert_ports(
            node.definition, connection.source_port.kind, connection.target_port.kind
        ) or ("", "")

        def insert() -> None:
            source = connection.source_port
            target = connection.target_port
            self._remove_connection_internal(connection)
            self.add_connection(source, node.input_ports[input_name], record_undo=False)
            self.add_connection(node.output_ports[output_name], target, record_undo=False)
            self._touch()

        if record_undo:
            self.perform_action("Insert Node", insert)
        else:
            insert()
        return True

    def arrange_selected(self, mode: str) -> bool:
        nodes = self.selected_nodes()
        if len(nodes) < 2:
            return False
        labels = {
            "left": "Align Left",
            "hcenter": "Align Horizontal Centres",
            "right": "Align Right",
            "top": "Align Top",
            "vcenter": "Align Vertical Centres",
            "bottom": "Align Bottom",
        }
        if mode not in labels:
            return False
        rects = {node.uid: node.sceneBoundingRect() for node in nodes}
        if mode == "left":
            target = min(rect.left() for rect in rects.values())
        elif mode == "right":
            target = max(rect.right() for rect in rects.values())
        elif mode == "hcenter":
            target = sum(rect.center().x() for rect in rects.values()) / len(rects)
        elif mode == "top":
            target = min(rect.top() for rect in rects.values())
        elif mode == "bottom":
            target = max(rect.bottom() for rect in rects.values())
        else:
            target = sum(rect.center().y() for rect in rects.values()) / len(rects)

        def arrange() -> None:
            for node in nodes:
                rect = rects[node.uid]
                if mode == "left":
                    delta = QPointF(target - rect.left(), 0.0)
                elif mode == "right":
                    delta = QPointF(target - rect.right(), 0.0)
                elif mode == "hcenter":
                    delta = QPointF(target - rect.center().x(), 0.0)
                elif mode == "top":
                    delta = QPointF(0.0, target - rect.top())
                elif mode == "bottom":
                    delta = QPointF(0.0, target - rect.bottom())
                else:
                    delta = QPointF(0.0, target - rect.center().y())
                node.setPos(node.pos() + delta)
            self.finalize_node_movement(nodes)
            self._update_all_connections()
            self._touch()

        self.perform_action(labels[mode], arrange)
        return True

    def distribute_selected(self, axis: str) -> bool:
        nodes = self.selected_nodes()
        if len(nodes) < 3 or axis not in {"horizontal", "vertical"}:
            return False
        horizontal = axis == "horizontal"
        nodes.sort(
            key=lambda node: node.sceneBoundingRect().left()
            if horizontal
            else node.sceneBoundingRect().top()
        )
        rects = [node.sceneBoundingRect() for node in nodes]
        start = rects[0].left() if horizontal else rects[0].top()
        end = rects[-1].right() if horizontal else rects[-1].bottom()
        sizes = [rect.width() if horizontal else rect.height() for rect in rects]
        gap = (end - start - sum(sizes)) / max(len(nodes) - 1, 1)

        def distribute() -> None:
            cursor = start
            for node, rect, size in zip(nodes, rects, sizes):
                current = rect.left() if horizontal else rect.top()
                delta = cursor - current
                node.setPos(node.pos() + (QPointF(delta, 0.0) if horizontal else QPointF(0.0, delta)))
                cursor += size + gap
            self.finalize_node_movement(nodes)
            self._update_all_connections()
            self._touch()

        self.perform_action(
            "Distribute Horizontally" if horizontal else "Distribute Vertically",
            distribute,
        )
        return True

    # ------------------------------------------------------------------
    # Groups
    # ------------------------------------------------------------------
    def create_group(
        self,
        position: QPointF,
        *,
        width: float = 520.0,
        height: float = 320.0,
        name: str = "Group",
        description: str = "",
        category: str = "User",
        collapsed: bool = False,
        members: set[str] | None = None,
        exposed_parameters: list[dict] | None = None,
        interface_inputs: list[dict] | None = None,
        interface_outputs: list[dict] | None = None,
        uid: str | None = None,
        record_undo: bool = True,
    ) -> GroupFrameItem:
        result: GroupFrameItem | None = None

        def create() -> None:
            nonlocal result
            migrated_outputs = self._migrate_interface_outputs(
                deepcopy(list(interface_outputs or []))
            )
            result = self._create_group_internal(
                position,
                width=width,
                height=height,
                name=name,
                description=description,
                category=category,
                collapsed=collapsed,
                members=members,
                exposed_parameters=exposed_parameters,
                interface_inputs=interface_inputs,
                interface_outputs=migrated_outputs,
                uid=uid,
            )
            self._touch()

        if record_undo:
            self.perform_action("Add Group", create)
        else:
            self._constructing = True
            try:
                create()
            finally:
                self._constructing = False
        assert result is not None
        return result

    def _create_group_internal(
        self,
        position: QPointF,
        *,
        width: float,
        height: float,
        name: str,
        description: str,
        category: str,
        collapsed: bool,
        members: set[str] | None,
        exposed_parameters: list[dict] | None,
        interface_inputs: list[dict] | None,
        interface_outputs: list[dict] | None,
        uid: str | None,
    ) -> GroupFrameItem:
        group = GroupFrameItem(
            uid=uid,
            name=name,
            description=description,
            category=category,
            width=width,
            height=height,
            collapsed=collapsed,
            members=members,
            exposed_parameters=exposed_parameters,
            interface_inputs=interface_inputs,
            interface_outputs=interface_outputs,
        )
        group._last_pos = QPointF(position)
        group.setPos(position)
        self.groups[group.uid] = group
        self.addItem(group)
        for node_uid in group.members:
            node = self.nodes.get(node_uid)
            if node is not None:
                if node.group_uid and node.group_uid != group.uid:
                    old = self.groups.get(node.group_uid)
                    if old is not None:
                        old.members.discard(node_uid)
                node.group_uid = group.uid
        group.rebuild_ports(self)
        self._refresh_group_visibility(group)
        self.groupsChanged.emit()
        return group

    def group_selected_nodes(self) -> GroupFrameItem | None:
        nodes = self.selected_nodes()
        if not nodes:
            return None
        bounds = nodes[0].sceneBoundingRect()
        for node in nodes[1:]:
            bounds = bounds.united(node.sceneBoundingRect())
        margin_x = 42.0
        margin_top = 70.0
        margin_bottom = 42.0
        position = QPointF(bounds.left() - margin_x, bounds.top() - margin_top)
        group: GroupFrameItem | None = None

        def group_nodes() -> None:
            nonlocal group
            member_ids = {node.uid for node in nodes}
            for node in nodes:
                if node.group_uid:
                    old = self.groups.get(node.group_uid)
                    if old is not None:
                        old.members.discard(node.uid)
            group = self._create_group_internal(
                position,
                width=bounds.width() + margin_x * 2,
                height=bounds.height() + margin_top + margin_bottom,
                name="Group",
                description="",
                category="User",
                collapsed=False,
                members=member_ids,
                exposed_parameters=[],
                interface_inputs=[],
                interface_outputs=[],
                uid=None,
            )
            self.clearSelection()
            group.setSelected(True)
            self._refresh_all_groups()
            self._touch()

        self.perform_action("Group Selected Nodes", group_nodes)
        return group

    def add_empty_group(self, position: QPointF) -> GroupFrameItem:
        return self.create_group(position, width=500, height=300, record_undo=True)

    def remove_group(self, group: GroupFrameItem, *, record_undo: bool = True) -> None:
        def remove() -> None:
            if group.uid not in self.groups:
                return
            for node_uid in list(group.members):
                node = self.nodes.get(node_uid)
                if node is not None:
                    node.group_uid = None
                    node.setVisible(True)
            group.members.clear()
            group._clear_ports()
            self.groups.pop(group.uid, None)
            if group.scene() is self:
                self.removeItem(group)
            self._refresh_all_groups()
            self.groupsChanged.emit()
            self._touch()

        if record_undo:
            self.perform_action("Ungroup", remove)
        else:
            remove()

    def ungroup_selected(self) -> None:
        groups = self.selected_groups()
        if not groups:
            return

        def ungroup() -> None:
            for group in list(groups):
                self.remove_group(group, record_undo=False)
            self._touch()

        self.perform_action("Ungroup", ungroup)

    def toggle_group(self, group: GroupFrameItem) -> None:
        def toggle() -> None:
            group.set_collapsed(not group.collapsed)
            group.rebuild_ports(self)
            self._refresh_group_visibility(group)
            self._update_all_connections()
            self._touch()
            if group.isSelected():
                self.selectedNodeChanged.emit(group)

        self.perform_action("Collapse Group" if not group.collapsed else "Expand Group", toggle)

    def toggle_selected_group(self) -> None:
        groups = self.selected_groups()
        if len(groups) == 1:
            self.toggle_group(groups[0])

    def group_moved(self, group: GroupFrameItem, delta: QPointF) -> None:
        if self._restoring or self._constructing or delta.isNull():
            return
        self._moving_group = True
        try:
            for node_uid in group.members:
                node = self.nodes.get(node_uid)
                if node is not None:
                    node.setPos(node.pos() + delta)
            self._update_all_connections()
        finally:
            self._moving_group = False
        self._touch()

    def group_resized(self, group: GroupFrameItem) -> None:
        del group
        self._touch()

    def finalize_node_movement(self, moved_nodes: list[NodeItem] | None = None) -> None:
        moved_nodes = moved_nodes or self.selected_nodes()
        changed = False
        expanded_groups = [g for g in self.groups.values() if not g.collapsed]
        # More recently drawn/smaller frames take precedence when overlapping.
        expanded_groups.sort(key=lambda g: g.frame_width * g.frame_height)
        for node in moved_nodes:
            containing = next((group for group in expanded_groups if group.contains_node(node)), None)
            new_uid = containing.uid if containing else None
            if new_uid == node.group_uid:
                continue
            if node.group_uid:
                old = self.groups.get(node.group_uid)
                if old is not None:
                    old.members.discard(node.uid)
            node.group_uid = new_uid
            if containing is not None:
                containing.members.add(node.uid)
            changed = True
        if changed:
            self._refresh_docked_layout()
            self._refresh_all_groups()
            self.groupsChanged.emit()
            self._touch()

    def set_group_property(self, group: GroupFrameItem, name: str, value: Any) -> None:
        if not hasattr(group, name) or getattr(group, name) == value:
            return

        def change() -> None:
            setattr(group, name, value)
            group.update()
            self.groupsChanged.emit()
            self._touch()

        self.perform_action(
            f"Change Group {name.replace('_', ' ').title()}",
            change,
            merge_key=f"group:{group.uid}:{name}",
        )

    def set_group_parameter_exposed(
        self,
        group: GroupFrameItem,
        node_uid: str,
        parameter_name: str,
        exposed: bool,
        alias: str | None = None,
    ) -> None:
        key = (node_uid, parameter_name)

        def change() -> None:
            existing = next(
                (
                    entry
                    for entry in group.exposed_parameters
                    if (entry.get("node"), entry.get("parameter")) == key
                ),
                None,
            )
            if exposed and existing is None:
                node = self.nodes.get(node_uid)
                if node is None:
                    return
                spec = next((s for s in node.definition.parameters if s.name == parameter_name), None)
                if spec is None:
                    return
                group.exposed_parameters.append(
                    {
                        "node": node_uid,
                        "parameter": parameter_name,
                        "name": alias or f"{node.definition.name} · {spec.label}",
                    }
                )
            elif not exposed and existing is not None:
                group.exposed_parameters.remove(existing)
            self._touch()

        self.perform_action("Change Exposed Parameters", change)

    def set_exposed_parameter_alias(self, group: GroupFrameItem, index: int, alias: str) -> None:
        if not 0 <= index < len(group.exposed_parameters):
            return

        def change() -> None:
            group.exposed_parameters[index]["name"] = alias
            self._touch()

        self.perform_action(
            "Rename Exposed Parameter",
            change,
            merge_key=f"group:{group.uid}:exposed:{index}:name",
        )

    def group_interface_is_forced(self, group: GroupFrameItem, kind: str, entry: dict) -> bool:
        node_uid = str(entry.get("node", ""))
        if kind == "input":
            input_name = str(entry.get("input", ""))
            return any(
                connection.target_node.uid == node_uid
                and connection.input_name == input_name
                and connection.source_node.uid not in group.members
                for connection in self.connections
            )
        return any(
            connection.source_node.uid == node_uid
            and connection.target_node.uid not in group.members
            for connection in self.connections
        )

    def set_group_interface_enabled(
        self,
        group: GroupFrameItem,
        kind: str,
        index: int,
        enabled: bool,
    ) -> None:
        collection = group.interface_inputs if kind == "input" else group.interface_outputs
        if not 0 <= index < len(collection):
            return
        if not enabled and self.group_interface_is_forced(group, kind, collection[index]):
            return
        if bool(collection[index].get("enabled", True)) == bool(enabled):
            return

        def change() -> None:
            collection[index]["enabled"] = bool(enabled)
            group.rebuild_ports(self)
            self._update_all_connections()
            self._touch()

        self.perform_action(f"{'Show' if enabled else 'Hide'} Group {kind.title()}", change)

    def set_group_interface_alias(
        self,
        group: GroupFrameItem,
        kind: str,
        index: int,
        alias: str,
    ) -> None:
        collection = group.interface_inputs if kind == "input" else group.interface_outputs
        if not 0 <= index < len(collection):
            return
        alias = alias.strip() or ("Input" if kind == "input" else "Output")
        if str(collection[index].get("name", "")) == alias:
            return

        def change() -> None:
            collection[index]["name"] = alias
            group.rebuild_ports(self)
            self._update_all_connections()
            self._touch()

        self.perform_action(
            f"Rename Group {kind.title()}",
            change,
            merge_key=f"group:{group.uid}:interface:{kind}:{index}:name",
        )

    def move_group_interface(
        self,
        group: GroupFrameItem,
        kind: str,
        index: int,
        direction: int,
    ) -> None:
        collection = group.interface_inputs if kind == "input" else group.interface_outputs
        target = index + direction
        if not (0 <= index < len(collection) and 0 <= target < len(collection)):
            return

        def change() -> None:
            collection[index], collection[target] = collection[target], collection[index]
            group.rebuild_ports(self)
            self._update_all_connections()
            self._touch()

        self.perform_action(f"Reorder Group {kind.title()}s", change)

    def set_parameter_socket_exposed(self, node: NodeItem, parameter_name: str, exposed: bool) -> None:
        spec = node.definition.parameter_spec(parameter_name)
        if spec is None or not spec.animatable:
            return
        port_name = node.parameter_port_name(parameter_name)

        def change() -> None:
            if exposed:
                node.exposed_parameter_inputs.add(parameter_name)
            else:
                existing = self.connection_for_input(node.uid, port_name)
                if existing is not None:
                    self._remove_connection_internal(existing)
                node.exposed_parameter_inputs.discard(parameter_name)
                port = node.input_ports.pop(port_name, None)
                if port is not None:
                    port.setParentItem(None)
                    if port.scene() is self:
                        self.removeItem(port)
                    port.deleteLater()
            node.parameters["_exposed_inputs"] = sorted(node.exposed_parameter_inputs)
            node.prepareGeometryChange()
            node._rebuild_input_ports()
            node._position_ports()
            self._refresh_all_groups()
            self._update_all_connections()
            node.update()
            self._touch()
            if node.isSelected():
                self.selectedNodeChanged.emit(node)

        self.perform_action("Expose Parameter Input" if exposed else "Hide Parameter Input", change)

    def set_parameter_asset_published(
        self, node: NodeItem, parameter_name: str, published: bool
    ) -> None:
        spec = node.definition.parameter_spec(parameter_name)
        if spec is None or not spec.graph_asset_publishable:
            return

        def change() -> None:
            unpublished = {
                str(value) for value in node.parameters.get("_graph_asset_unpublished_inputs", ())
            }
            if published:
                unpublished.discard(parameter_name)
            else:
                unpublished.add(parameter_name)
            node.parameters["_graph_asset_unpublished_inputs"] = sorted(unpublished)
            self._touch()
            if node.isSelected():
                self.selectedNodeChanged.emit(node)

        self.perform_action(
            "Publish Graph Asset Parameter" if published else "Hide Graph Asset Parameter",
            change,
        )

    def set_parameter_asset_metadata(
        self, node: NodeItem, parameter_name: str, metadata: dict[str, Any]
    ) -> None:
        spec = node.definition.parameter_spec(parameter_name)
        if spec is None or not spec.graph_asset_publishable:
            return

        def change() -> None:
            current = node.parameters.get("_graph_asset_parameter_meta", {})
            all_metadata = deepcopy(dict(current)) if isinstance(current, dict) else {}
            previous = dict(all_metadata.get(parameter_name, {}))
            # Interface identity is generated from the node UID and parameter
            # name and then retained independently from every public label.
            # Renaming or regrouping an asset control therefore cannot reset
            # parent-instance values.
            if previous.get("interface_id"):
                interface_id = str(previous["interface_id"])
            else:
                from ..graph_assets import stable_interface_id
                interface_id = stable_interface_id("parameter", node.uid, parameter_name)
            all_metadata[parameter_name] = {
                "interface_id": interface_id,
                "name": str(metadata.get("name", spec.label)).strip() or spec.label,
                "description": str(metadata.get("description", spec.description)).strip(),
                "group": str(metadata.get("group", spec.group or "Parameters")).strip() or "Parameters",
                "order": max(0, min(int(metadata.get("order", spec.group_order)), 9999)),
            }
            node.parameters["_graph_asset_parameter_meta"] = all_metadata
            unpublished = {
                str(value) for value in node.parameters.get("_graph_asset_unpublished_inputs", ())
            }
            if bool(metadata.get("published", parameter_name not in unpublished)):
                unpublished.discard(parameter_name)
            else:
                unpublished.add(parameter_name)
            node.parameters["_graph_asset_unpublished_inputs"] = sorted(unpublished)
            self._touch()
            if node.isSelected():
                self.selectedNodeChanged.emit(node)

        self.perform_action("Edit Graph Asset Parameter", change)

    def _refresh_manual_parameter_status(self, node: NodeItem) -> None:
        if not node.definition.manual_action_label or not node.parameters.get("_manual_result_data"):
            return
        status = str(node.parameters.get("_manual_status", "") or "")
        if status in {"Running", "Cancelling"}:
            node.parameters["_manual_changed_during_run"] = True
            return
        applied = node.parameters.get("_manual_applied_parameters", {})
        relevant = tuple(node.definition.manual_action_relevant_parameters)
        is_current = isinstance(applied, dict) and all(
            node.parameters.get(parameter_name) == applied.get(parameter_name)
            for parameter_name in relevant
        )
        node.parameters["_manual_status"] = "Up to Date" if is_current else "Out of Date"
        node.parameters["_manual_last_error"] = ""

    def apply_lightweight_node_parameter(
        self, node_uid: str, name: str, value: Any
    ) -> None:
        """Apply one manual-node setting without snapshotting persistent mesh data."""

        node = self.nodes.get(str(node_uid))
        if node is None:
            return
        node.parameters[str(name)] = value
        self._refresh_manual_parameter_status(node)
        self._graph_change_hint = ("manual-settings-only", str(node.uid))
        self.graphChanged.emit()

    def change_node_parameter(self, node: NodeItem, name: str, value: Any, *, label: str | None = None) -> None:
        if node.definition.type_id == "graph.send" and name == "channel_name":
            value = self._unique_portal_name(str(value), excluding_uid=node.uid)
        if node.parameters.get(name) == value:
            return
        manual_relevant = (
            bool(node.definition.manual_action_label)
            and name in set(node.definition.manual_action_relevant_parameters)
            and bool(node.parameters.get("_manual_result_data"))
        )
        if manual_relevant:
            # Persistent manual results may be many megabytes. A complete graph
            # snapshot for every slider tick copied that payload twice and was
            # the remaining Best Packing/UI pause. Store only this parameter
            # delta while retaining ordinary undo merging. Apply first, then push
            # an already-applied command so graphChanged observes the updated
            # QUndoStack dirty state.
            before = node.parameters.get(name)
            node.parameters[name] = value
            self._refresh_manual_parameter_status(node)
            self.undo_stack.push(
                NodeParameterCommand(
                    self,
                    node.uid,
                    name,
                    before,
                    value,
                    label or f"Change {name.replace('_', ' ').title()}",
                    merge_key=f"node:{node.uid}:parameter:{name}",
                    already_applied=True,
                )
            )
            self._graph_change_hint = ("manual-settings-only", str(node.uid))
            self.graphChanged.emit()
            return

        def change() -> None:
            node.parameters[name] = value
            if node.definition.type_id == GRAPH_INSTANCE_TYPE and name.startswith("asset_param::"):
                overrides = {str(item) for item in node.parameters.get("_asset_parameter_overrides", ())}
                interface_id = name.split("::", 1)[1]
                default = next((
                    deepcopy(entry.get("default"))
                    for entry in node.parameters.get("_asset_interface", {}).get("parameters", ())
                    if isinstance(entry, dict) and str(entry.get("id", "")) == interface_id
                ), None)
                if value == default:
                    overrides.discard(name)
                else:
                    overrides.add(name)
                node.parameters["_asset_parameter_overrides"] = sorted(overrides)
            if node.definition.type_id == "graph.receive" and name == "sender_uid":
                sender = self.nodes.get(str(value))
                node.parameters["channel_name"] = (
                    str(sender.parameters.get("channel_name", "Channel"))
                    if sender is not None and sender.definition.type_id == "graph.send"
                    else str(node.parameters.get("channel_name", ""))
                )
            if node.definition.type_id == "input.image" and name in ("path", "data_type", "colour_space"):
                try:
                    from ..nodes.input_nodes import refresh_image_metadata
                    refresh_image_metadata(node.parameters)
                except Exception:
                    pass
            self._resolve_dynamic_types()
            self._remove_incompatible_connections()
            self._refresh_all_groups()
            self._touch()

        self.perform_action(
            label or f"Change {name.replace('_', ' ').title()}",
            change,
            merge_key=f"node:{node.uid}:parameter:{name}",
        )

    def _refresh_group_visibility(self, group: GroupFrameItem) -> None:
        for node_uid in group.members:
            node = self.nodes.get(node_uid)
            if node is not None:
                node.setVisible(not group.collapsed)
        for connection in self.connections:
            connection.update_path()

    def _refresh_all_groups(self) -> None:
        for group in self.groups.values():
            # Remove stale memberships.
            group.members.intersection_update(self.nodes.keys())
            group.rebuild_ports(self)
            self._refresh_group_visibility(group)
        self._update_all_connections()

    def _update_all_connections(self) -> None:
        for connection in self.connections:
            connection.update_path()

    def visual_ports_for_connection(
        self,
        connection: ConnectionItem,
    ) -> tuple[PortItem | None, PortItem | None, bool]:
        if (
            connection.source_node.is_docked
            and connection.source_node.docked_to_uid == connection.target_node.uid
        ):
            return None, None, False
        source_group = self.groups.get(connection.source_node.group_uid or "")
        target_group = self.groups.get(connection.target_node.group_uid or "")

        if source_group is not None and target_group is source_group and source_group.collapsed:
            return None, None, False

        source: PortItem | None = connection.source_port
        target: PortItem | None = connection.target_port
        if source_group is not None and source_group.collapsed:
            source = source_group.proxy_output(connection.source_node.uid, connection.output_name)
        if target_group is not None and target_group.collapsed:
            target = target_group.proxy_input(connection.target_node.uid, connection.input_name)
        return source, target, source is not None and target is not None

    # ------------------------------------------------------------------
    # Selection, deletion and clipboard
    # ------------------------------------------------------------------
    def selected_nodes(self) -> list[NodeItem]:
        return [item for item in self.selectedItems() if isinstance(item, NodeItem)]

    def selected_groups(self) -> list[GroupFrameItem]:
        return [item for item in self.selectedItems() if isinstance(item, GroupFrameItem)]

    def delete_selected(self) -> None:
        selected = list(self.selectedItems())
        if not selected:
            return

        def delete() -> None:
            changed = False
            for item in selected:
                if isinstance(item, ConnectionItem):
                    self._remove_connection_internal(item)
                    changed = True
            # Deleting a group frame intentionally keeps its contents.
            for item in selected:
                if isinstance(item, GroupFrameItem) and item.uid in self.groups:
                    self.remove_group(item, record_undo=False)
                    changed = True
            for item in selected:
                if not isinstance(item, NodeItem) or item.uid not in self.nodes:
                    continue
                touching = [
                    connection
                    for connection in self.connections
                    if connection.source_node is item or connection.target_node is item
                ]
                for connection in touching:
                    self._remove_connection_internal(connection)
                if item.group_uid:
                    group = self.groups.get(item.group_uid)
                    if group is not None:
                        group.members.discard(item.uid)
                if self.active_node is item:
                    self.set_active_node(None)
                self.nodes.pop(item.uid, None)
                self.removeItem(item)
                changed = True
            if changed:
                self._resolve_dynamic_types()
                self._remove_incompatible_connections()
                self._refresh_docked_layout()
                self._refresh_all_groups()
                self.groupsChanged.emit()
                self._touch()

        self.perform_action("Delete Selection", delete)

    def clear_graph(self, *, record_undo: bool = False) -> None:
        def clear_items() -> None:
            self.set_active_node(None)
            self._clear_portal_debug()
            self.clear()
            self.nodes.clear()
            self.groups.clear()
            self.connections.clear()
            self._touch()

        if record_undo:
            self.perform_action("Clear Graph", clear_items)
        else:
            self._constructing = True
            try:
                clear_items()
            finally:
                self._constructing = False
            self.graphChanged.emit()
            self.groupsChanged.emit()

    def selection_to_dict(self) -> dict[str, Any] | None:
        selected_nodes = self.selected_nodes()
        selected_groups = self.selected_groups()
        included_groups = {group.uid: group for group in selected_groups}
        included_nodes = {node.uid: node for node in selected_nodes}
        for group in selected_groups:
            for uid in group.members:
                node = self.nodes.get(uid)
                if node is not None:
                    included_nodes[uid] = node
        if not included_nodes and not included_groups:
            return None

        rects = [item.sceneBoundingRect() for item in [*included_nodes.values(), *included_groups.values()]]
        bounds = rects[0]
        for rect in rects[1:]:
            bounds = bounds.united(rect)
        anchor = bounds.center()
        selected_ids = set(included_nodes)

        return {
            "format": "vfx-texture-lab-node-selection",
            "version": 3,
            "nodes": [
                {
                    "uid": node.uid,
                    "type": node.definition.type_id,
                    "x": node.pos().x() - anchor.x(),
                    "y": node.pos().y() - anchor.y(),
                    "parameters": deepcopy(node.parameters),
                    "definition": self._definition_snapshot(node),
                    "group": node.group_uid if node.group_uid in included_groups else None,
                    "docked_to": node.docked_to_uid if node.docked_to_uid in included_nodes else None,
                    "undocked_x": node.undocked_position.x() - anchor.x(),
                    "undocked_y": node.undocked_position.y() - anchor.y(),
                }
                for node in included_nodes.values()
            ],
            "groups": [
                {
                    "uid": group.uid,
                    "name": group.name,
                    "description": group.description,
                    "category": group.category,
                    "x": group.pos().x() - anchor.x(),
                    "y": group.pos().y() - anchor.y(),
                    "width": group.frame_width,
                    "height": group.frame_height,
                    "collapsed": group.collapsed,
                    "members": [uid for uid in group.members if uid in selected_ids],
                    "exposed_parameters": deepcopy(group.exposed_parameters),
                    "interface_inputs": deepcopy(group.interface_inputs),
                    "interface_outputs": deepcopy(group.interface_outputs),
                }
                for group in included_groups.values()
            ],
            "connections": [
                {
                    "source": connection.source_node.uid,
                    "source_output": connection.output_name,
                    "target": connection.target_node.uid,
                    "input": connection.input_name,
                }
                for connection in self.connections
                if connection.source_node.uid in selected_ids and connection.target_node.uid in selected_ids
            ],
        }

    def paste_selection(self, data: dict[str, Any], position: QPointF) -> list[NodeItem]:
        if data.get("format") != "vfx-texture-lab-node-selection":
            return []
        created: list[NodeItem] = []

        def paste() -> None:
            for node_data in data.get("nodes", []):
                type_id = str(node_data.get("type", ""))
                if type_id and not self.registry.contains(type_id):
                    self.registry.ensure_placeholder(
                        type_id,
                        node_data.get("definition") if isinstance(node_data.get("definition"), dict) else None,
                    )
            valid_types = {definition.type_id for definition in self.registry.all(include_hidden=True)}
            old_to_new: dict[str, NodeItem] = {}
            old_group_to_new: dict[str, GroupFrameItem] = {}
            self.clearSelection()

            for node_data in data.get("nodes", []):
                type_id = str(node_data.get("type", ""))
                if type_id not in valid_types:
                    continue
                node = self._create_node_internal(
                    type_id,
                    QPointF(position.x() + float(node_data.get("x", 0.0)), position.y() + float(node_data.get("y", 0.0))),
                    parameters=deepcopy(dict(node_data.get("parameters", {}))),
                )
                old_to_new[str(node_data.get("uid", ""))] = node
                created.append(node)

            for old_uid, node in old_to_new.items():
                if node.definition.type_id != "graph.receive":
                    continue
                old_sender = str(node.parameters.get("sender_uid", ""))
                if old_sender in old_to_new:
                    node.parameters["sender_uid"] = old_to_new[old_sender].uid

            for group_data in data.get("groups", []):
                old_uid = str(group_data.get("uid", ""))
                old_members = [str(uid) for uid in group_data.get("members", [])]
                members = {old_to_new[uid].uid for uid in old_members if uid in old_to_new}
                exposed = deepcopy(list(group_data.get("exposed_parameters", [])))
                interface_inputs = deepcopy(list(group_data.get("interface_inputs", [])))
                interface_outputs = deepcopy(list(group_data.get("interface_outputs", [])))
                for collection in (exposed, interface_inputs, interface_outputs):
                    for entry in collection:
                        old_node = str(entry.get("node", ""))
                        if old_node in old_to_new:
                            entry["node"] = old_to_new[old_node].uid
                interface_inputs = self._migrate_interface_inputs(interface_inputs)
                interface_outputs = self._migrate_interface_outputs(interface_outputs)
                group = self._create_group_internal(
                    QPointF(position.x() + float(group_data.get("x", 0.0)), position.y() + float(group_data.get("y", 0.0))),
                    width=float(group_data.get("width", 520.0)),
                    height=float(group_data.get("height", 320.0)),
                    name=str(group_data.get("name", "Group")),
                    description=str(group_data.get("description", "")),
                    category=str(group_data.get("category", "User")),
                    collapsed=bool(group_data.get("collapsed", False)),
                    members=members,
                    exposed_parameters=exposed,
                    interface_inputs=interface_inputs,
                    interface_outputs=interface_outputs,
                    uid=None,
                )
                old_group_to_new[old_uid] = group
                group.setSelected(True)

            for node_data in data.get("nodes", []):
                old_uid = str(node_data.get("uid", ""))
                old_group = str(node_data.get("group", ""))
                node = old_to_new.get(old_uid)
                group = old_group_to_new.get(old_group)
                if node is not None and group is not None:
                    node.group_uid = group.uid
                    group.members.add(node.uid)

            for connection_data in data.get("connections", []):
                source = old_to_new.get(str(connection_data.get("source", "")))
                target = old_to_new.get(str(connection_data.get("target", "")))
                input_name = str(connection_data.get("input", ""))
                if target is not None:
                    input_name = self._compatible_input_name(target, input_name)
                if source is not None and target is not None and input_name in target.input_ports:
                    if source.output_port is not None and source.definition.output_names:
                        source_port = source.output_ports.get(
                            self._compatible_output_name(
                                source, str(connection_data.get("source_output") or source.definition.output_names[0])
                            ),
                            source.output_port,
                        )
                        if source_port is not None:
                            self.add_connection(source_port, target.input_ports[input_name], record_undo=False)

            for node_data in data.get("nodes", []):
                old_uid = str(node_data.get("uid", ""))
                old_parent = str(node_data.get("docked_to", ""))
                node = old_to_new.get(old_uid)
                parent = old_to_new.get(old_parent)
                if node is None or parent is None:
                    continue
                node.set_docked(
                    parent.uid,
                    undocked_position=QPointF(
                        position.x() + float(node_data.get("undocked_x", node.pos().x() - position.x())),
                        position.y() + float(node_data.get("undocked_y", node.pos().y() - position.y())),
                    ),
                )

            if not old_group_to_new:
                for node in created:
                    node.setSelected(True)
            self._resolve_dynamic_types()
            self._remove_incompatible_connections()
            self._refresh_all_groups()
            self._refresh_docked_layout()
            self.groupsChanged.emit()
            self._touch()

        self.perform_action("Paste Nodes", paste)
        return created

    # ------------------------------------------------------------------
    # Reusable group assets
    # ------------------------------------------------------------------
    def group_to_asset(self, group: GroupFrameItem) -> dict[str, Any]:
        members = [self.nodes[uid] for uid in group.members if uid in self.nodes]
        if not members:
            raise ValueError("Cannot save an empty group as a reusable node")
        origin = group.pos()
        member_ids = {node.uid for node in members}
        return {
            "format": "vfx-texture-lab-user-node",
            "version": 1,
            "name": group.name,
            "description": group.description,
            "category": group.category or "User",
            "width": group.frame_width,
            "height": group.frame_height,
            "nodes": [
                {
                    "uid": node.uid,
                    "type": node.definition.type_id,
                    "x": node.pos().x() - origin.x(),
                    "y": node.pos().y() - origin.y(),
                    "parameters": deepcopy(node.parameters),
                    "definition": self._definition_snapshot(node),
                    "docked_to": node.docked_to_uid if node.docked_to_uid in member_ids else None,
                    "undocked_x": node.undocked_position.x() - origin.x(),
                    "undocked_y": node.undocked_position.y() - origin.y(),
                }
                for node in members
            ],
            "connections": [
                {
                    "source": connection.source_node.uid,
                    "source_output": connection.output_name,
                    "target": connection.target_node.uid,
                    "input": connection.input_name,
                }
                for connection in self.connections
                if connection.source_node.uid in member_ids and connection.target_node.uid in member_ids
            ],
            "exposed_parameters": deepcopy(group.exposed_parameters),
            "interface_inputs": deepcopy(group.interface_inputs),
            "interface_outputs": deepcopy(group.interface_outputs),
        }

    def instantiate_group_asset(self, data: dict[str, Any], position: QPointF) -> GroupFrameItem | None:
        if data.get("format") != "vfx-texture-lab-user-node":
            return None
        result: GroupFrameItem | None = None

        def instantiate() -> None:
            nonlocal result
            for node_data in data.get("nodes", []):
                type_id = str(node_data.get("type", ""))
                if type_id and not self.registry.contains(type_id):
                    self.registry.ensure_placeholder(
                        type_id,
                        node_data.get("definition") if isinstance(node_data.get("definition"), dict) else None,
                    )
            valid_types = {definition.type_id for definition in self.registry.all(include_hidden=True)}
            mapping: dict[str, NodeItem] = {}
            for node_data in data.get("nodes", []):
                type_id = str(node_data.get("type", ""))
                if type_id not in valid_types:
                    continue
                node = self._create_node_internal(
                    type_id,
                    QPointF(position.x() + float(node_data.get("x", 0.0)), position.y() + float(node_data.get("y", 0.0))),
                    parameters=deepcopy(dict(node_data.get("parameters", {}))),
                )
                mapping[str(node_data.get("uid", ""))] = node

            for node in mapping.values():
                if node.definition.type_id != "graph.receive":
                    continue
                old_sender = str(node.parameters.get("sender_uid", ""))
                if old_sender in mapping:
                    node.parameters["sender_uid"] = mapping[old_sender].uid

            exposed = deepcopy(list(data.get("exposed_parameters", [])))
            interface_inputs = deepcopy(list(data.get("interface_inputs", [])))
            interface_outputs = deepcopy(list(data.get("interface_outputs", [])))
            for collection in (exposed, interface_inputs, interface_outputs):
                for entry in collection:
                    old = str(entry.get("node", ""))
                    if old in mapping:
                        entry["node"] = mapping[old].uid
            interface_inputs = self._migrate_interface_inputs(interface_inputs)
            interface_outputs = self._migrate_interface_outputs(interface_outputs)
            result = self._create_group_internal(
                position,
                width=float(data.get("width", 520.0)),
                height=float(data.get("height", 320.0)),
                name=str(data.get("name", "User Node")),
                description=str(data.get("description", "")),
                category=str(data.get("category", "User")),
                collapsed=True,
                members={node.uid for node in mapping.values()},
                exposed_parameters=exposed,
                interface_inputs=interface_inputs,
                interface_outputs=interface_outputs,
                uid=None,
            )
            for connection_data in data.get("connections", []):
                source = mapping.get(str(connection_data.get("source", "")))
                target = mapping.get(str(connection_data.get("target", "")))
                input_name = str(connection_data.get("input", ""))
                if target is not None:
                    input_name = self._compatible_input_name(target, input_name)
                if source is not None and target is not None and input_name in target.input_ports:
                    if source.output_port is not None and source.definition.output_names:
                        source_port = source.output_ports.get(
                            self._compatible_output_name(
                                source, str(connection_data.get("source_output") or source.definition.output_names[0])
                            ),
                            source.output_port,
                        )
                        if source_port is not None:
                            self.add_connection(source_port, target.input_ports[input_name], record_undo=False)
            for node_data in data.get("nodes", []):
                node = mapping.get(str(node_data.get("uid", "")))
                parent = mapping.get(str(node_data.get("docked_to", "")))
                if node is None or parent is None:
                    continue
                node.set_docked(
                    parent.uid,
                    undocked_position=QPointF(
                        position.x() + float(node_data.get("undocked_x", node.pos().x() - position.x())),
                        position.y() + float(node_data.get("undocked_y", node.pos().y() - position.y())),
                    ),
                )
            self.clearSelection()
            result.setSelected(True)
            self._resolve_dynamic_types()
            self._remove_incompatible_connections()
            self._refresh_all_groups()
            self._refresh_docked_layout()
            self._touch()

        self.perform_action("Add User Node", instantiate)
        return result

    def content_bounds(self) -> QRectF:
        """Bounds of authored graph objects, excluding wires and helper items."""
        items = [*self.nodes.values(), *self.groups.values()]
        if not items:
            return QRectF(-300.0, -220.0, 600.0, 440.0)
        bounds = items[0].sceneBoundingRect()
        for item in items[1:]:
            bounds = bounds.united(item.sceneBoundingRect())
        return bounds

    # ------------------------------------------------------------------
    # Dynamic definitions, missing-package placeholders and node errors
    # ------------------------------------------------------------------
    def clear_node_errors(self) -> None:
        for node in self.nodes.values():
            node.set_error(None)

    def set_node_error(self, uid: str | None, message: str | None) -> None:
        if uid is None:
            return
        node = self.nodes.get(uid)
        if node is not None:
            node.set_error(message)

    def rebind_registry_definitions(self) -> None:
        """Apply hot-reloaded package definitions to existing graph instances.

        Common parameters and connections survive interface changes. Connections
        aimed at removed inputs are dropped visibly rather than left dangling.
        """
        self._constructing = True
        try:
            for node in self.nodes.values():
                type_id = node.definition.type_id
                definition = self.registry.get_optional(type_id)
                if definition is None:
                    definition = self.registry.ensure_placeholder(type_id, node.definition.snapshot())
                # Built-in definitions remain the same registry objects during a
                # custom-library reload. Leave those nodes and their typed ports
                # completely untouched; only replaced package definitions (or a
                # new missing-package placeholder) need rebinding.
                if definition is node.definition:
                    continue
                old_inputs = tuple(node.definition.inputs)
                new_inputs = tuple(definition.inputs)
                old_ports = dict(node.input_ports)
                outgoing = [connection for connection in self.connections if connection.source_node is node]
                node.definition = definition
                defaults = definition.default_parameters()
                defaults.update({key: value for key, value in node.parameters.items() if key in defaults})
                # Missing placeholders retain the original opaque parameter data so
                # installing the package later can restore the instance exactly.
                if definition.missing:
                    defaults.update(node.parameters)
                node.parameters = defaults
                # Rebuild output ports while preserving every surviving wire by
                # stable output name. The old implementation replaced the ports
                # without retargeting outgoing ConnectionItems, so a library
                # refresh could make an otherwise unchanged graph appear crossed
                # or disconnected until the project was reopened.
                for port in node.output_ports.values():
                    port.setParentItem(None)
                    if port.scene() is self:
                        self.removeItem(port)
                    port.deleteLater()
                node.output_ports = {
                    name: PortItem(
                        node,
                        name,
                        True,
                        kind=definition.output_kind(name),
                        display_name=definition.output_label(name),
                    )
                    for name in definition.output_names
                }
                node.output_port = next(iter(node.output_ports.values()), None)
                for connection in list(outgoing):
                    replacement = node.output_ports.get(connection.output_name)
                    if replacement is None:
                        self._remove_connection_internal(connection)
                        continue
                    connection.source_port = replacement
                    connection.source_node = node
                node._position_ports()
                if old_inputs != new_inputs:
                    incoming = [connection for connection in self.connections if connection.target_node is node]
                    for port in old_ports.values():
                        port.setParentItem(None)
                        if port.scene() is self:
                            self.removeItem(port)
                        port.deleteLater()
                    node.input_ports = {
                        name: PortItem(node, name, False, kind=definition.input_kind(name))
                        for name in new_inputs
                    }
                    node.exposed_parameter_inputs = {
                        str(name) for name in node.parameters.get("_exposed_inputs", []) if definition.parameter_spec(str(name)) is not None
                    }
                    node.prepareGeometryChange()
                    node._rebuild_input_ports()
                    node._position_ports()
                    for connection in list(incoming):
                        if connection.input_name not in node.input_ports:
                            self._remove_connection_internal(connection)
                            continue
                        connection.target_port = node.input_ports[connection.input_name]
                        connection.target_node = node
                    self._refresh_all_groups()
                node.exposed_parameter_inputs = {
                    str(name) for name in node.parameters.get("_exposed_inputs", []) if definition.parameter_spec(str(name)) is not None
                }
                node._rebuild_input_ports()
                node._position_ports()
                node.setToolTip(definition.description)
                node.update()
            self._update_all_connections()
            self.groupsChanged.emit()
        finally:
            self._constructing = False
        self.graphChanged.emit()
        self._selection_changed()

    @staticmethod
    def _definition_snapshot(node: NodeItem) -> dict[str, Any] | None:
        if node.definition.is_external or node.definition.missing or node.definition.type_id == GRAPH_INSTANCE_TYPE:
            return node.definition.snapshot()
        return None

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def _selection_changed(self) -> None:
        selected = [
            item
            for item in self.selectedItems()
            if isinstance(item, (NodeItem, GroupFrameItem))
        ]
        self._refresh_portal_debug(selected[0] if len(selected) == 1 else None)
        self.selectedNodeChanged.emit(selected[0] if len(selected) == 1 else None)

    def _clear_portal_debug(self) -> None:
        for item in self._portal_debug_items:
            if item.scene() is self:
                self.removeItem(item)
        self._portal_debug_items.clear()

    def _refresh_portal_debug(self, selected: object | None = None) -> None:
        self._clear_portal_debug()
        if not isinstance(selected, PortalNodeItem):
            return
        if selected.definition.type_id == "graph.send":
            sender = selected
        elif selected.definition.type_id == "graph.receive":
            sender = self.nodes.get(str(selected.parameters.get("sender_uid", "")))
        else:
            sender = None
        if not isinstance(sender, PortalNodeItem) or sender.definition.type_id != "graph.send":
            return
        receivers = [
            node for node in self.nodes.values()
            if isinstance(node, PortalNodeItem)
            and node.definition.type_id == "graph.receive"
            and str(node.parameters.get("sender_uid", "")) == sender.uid
        ]
        start = sender.sceneBoundingRect().center()
        for receiver in receivers:
            end = receiver.sceneBoundingRect().center()
            distance = max(abs(end.x() - start.x()) * 0.35, 45.0)
            path = QPainterPath(start)
            path.cubicTo(start.x() + distance, start.y(), end.x() - distance, end.y(), end.x(), end.y())
            item = QGraphicsPathItem(path)
            pen = QPen(QColor(176, 110, 232, 125), 2.0, Qt.PenStyle.DashLine, Qt.PenCapStyle.RoundCap)
            item.setPen(pen)
            item.setZValue(-4)
            self.addItem(item)
            self._portal_debug_items.append(item)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "vfx-texture-lab-graph",
            "version": 20,
            "active_node": self.active_node.uid if self.active_node else None,
            "active_output": self.active_output_name,
            "nodes": [
                {
                    "uid": node.uid,
                    "type": node.definition.type_id,
                    "x": node.pos().x(),
                    "y": node.pos().y(),
                    "parameters": deepcopy(node.parameters),
                    "definition": self._definition_snapshot(node),
                    "group": node.group_uid,
                    "docked_to": node.docked_to_uid,
                    "undocked_x": node.undocked_position.x(),
                    "undocked_y": node.undocked_position.y(),
                    "thumbnail_enabled": bool(node.thumbnail_enabled),
                    "thumbnail_output": node.thumbnail_output_name,
                }
                for node in self.nodes.values()
            ],
            "groups": [
                {
                    "uid": group.uid,
                    "name": group.name,
                    "description": group.description,
                    "category": group.category,
                    "x": group.pos().x(),
                    "y": group.pos().y(),
                    "width": group.frame_width,
                    "height": group.frame_height,
                    "collapsed": group.collapsed,
                    "members": sorted(group.members),
                    "exposed_parameters": deepcopy(group.exposed_parameters),
                    "interface_inputs": deepcopy(group.interface_inputs),
                    "interface_outputs": deepcopy(group.interface_outputs),
                }
                for group in self.groups.values()
            ],
            "connections": [
                {
                    "source": connection.source_node.uid,
                    "source_output": connection.output_name,
                    "target": connection.target_node.uid,
                    "input": connection.input_name,
                }
                for connection in self.connections
            ],
        }

    def from_dict(self, data: dict[str, Any]) -> None:
        self._restoring = True
        try:
            self._load_dict(data)
        finally:
            self._restoring = False
        self.graphChanged.emit()
        self.groupsChanged.emit()

    def _load_dict(self, data: dict[str, Any]) -> None:
        self.set_active_node(None)
        self._clear_portal_debug()
        self.clear()
        self.nodes.clear()
        self.groups.clear()
        self.connections.clear()

        self._constructing = True
        try:
            inferred_inputs: dict[str, list[str]] = {}
            for connection_data in data.get("connections", []):
                target = str(connection_data.get("target", ""))
                input_name = str(connection_data.get("input", ""))
                if target and input_name:
                    inferred_inputs.setdefault(target, []).append(input_name)
            for node_data in data.get("nodes", []):
                type_id = str(node_data.get("type", ""))
                if type_id and not self.registry.contains(type_id):
                    self.registry.ensure_placeholder(
                        type_id,
                        node_data.get("definition") if isinstance(node_data.get("definition"), dict) else None,
                        inferred_inputs.get(str(node_data.get("uid", "")), ()),
                    )
            valid_types = {definition.type_id for definition in self.registry.all(include_hidden=True)}
            pending_docks: list[tuple[NodeItem, str, QPointF]] = []
            for node_data in data.get("nodes", []):
                type_id = str(node_data.get("type", ""))
                if type_id not in valid_types:
                    continue
                node = self._create_node_internal(
                    type_id,
                    QPointF(float(node_data.get("x", 0.0)), float(node_data.get("y", 0.0))),
                    uid=str(node_data.get("uid")),
                    parameters=dict(node_data.get("parameters", {})),
                    group_uid=str(node_data.get("group")) if node_data.get("group") else None,
                )
                # Manual actions are persisted with their last successful
                # result, but an in-flight request itself is deliberately not
                # resumed after a crash, autosave recovery or ordinary reopen.
                # Sealing the serial here is essential: otherwise focusing a
                # graph saved while an unwrap was running would silently launch
                # the expensive operation again without the user pressing its
                # Inspector action button.
                normalise_interrupted_manual_action(node.definition, node.parameters)
                thumbnail_output = str(node_data.get("thumbnail_output", "") or "") or None
                if thumbnail_output in node.thumbnail_output_names():
                    node.thumbnail_output_name = thumbnail_output
                else:
                    node.thumbnail_output_name = node.resolved_thumbnail_output()
                node.set_thumbnail_enabled(bool(node_data.get("thumbnail_enabled", False)))
                docked_to = str(node_data.get("docked_to", ""))
                if docked_to:
                    pending_docks.append((
                        node,
                        docked_to,
                        QPointF(
                            float(node_data.get("undocked_x", node.pos().x())),
                            float(node_data.get("undocked_y", node.pos().y())),
                        ),
                    ))

            for group_data in data.get("groups", []):
                members = {str(uid) for uid in group_data.get("members", []) if str(uid) in self.nodes}
                self._create_group_internal(
                    QPointF(float(group_data.get("x", 0.0)), float(group_data.get("y", 0.0))),
                    width=float(group_data.get("width", 520.0)),
                    height=float(group_data.get("height", 320.0)),
                    name=str(group_data.get("name", "Group")),
                    description=str(group_data.get("description", "")),
                    category=str(group_data.get("category", "User")),
                    collapsed=bool(group_data.get("collapsed", False)),
                    members=members,
                    exposed_parameters=deepcopy(list(group_data.get("exposed_parameters", []))),
                    interface_inputs=self._migrate_interface_inputs(
                        deepcopy(list(group_data.get("interface_inputs", [])))
                    ),
                    interface_outputs=self._migrate_interface_outputs(
                        deepcopy(list(group_data.get("interface_outputs", [])))
                    ),
                    uid=str(group_data.get("uid")),
                )

            # Backward compatible membership from node.group for older or hand-edited files.
            for node in self.nodes.values():
                if node.group_uid and node.group_uid in self.groups:
                    self.groups[node.group_uid].members.add(node.uid)
                elif node.group_uid not in self.groups:
                    node.group_uid = None

            for connection_data in data.get("connections", []):
                source = self.nodes.get(str(connection_data.get("source")))
                target = self.nodes.get(str(connection_data.get("target")))
                input_name = str(connection_data.get("input"))
                if target is not None:
                    input_name = self._compatible_input_name(target, input_name)
                if (
                    source is not None
                    and target is not None
                    and input_name in target.input_ports
                    and source.output_port is not None
                    and source.definition.output_names
                ):
                    output_name = self._compatible_output_name(
                        source, str(connection_data.get("source_output") or source.definition.output_names[0])
                    )
                    source_port = source.output_ports.get(output_name, source.output_port)
                    if source_port is not None:
                        connection = ConnectionItem(source_port, target.input_ports[input_name])
                        self.connections.append(connection)
                        self._refresh_wire_flow()
                        self.addItem(connection)

            self._resolve_dynamic_types()
            self._remove_incompatible_connections()
            for node, parent_uid, undocked in pending_docks:
                if parent_uid in self.nodes:
                    node.set_docked(parent_uid, undocked_position=undocked)
            self._refresh_docked_layout()
            self._refresh_all_groups()
            active = self.nodes.get(str(data.get("active_node")))
            self.set_active_node(active, output_name=data.get("active_output"))
        finally:
            self._constructing = False
