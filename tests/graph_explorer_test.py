from __future__ import annotations

import json
import os
import sys
import tempfile
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.document import DocumentSettings
from vfx_texture_lab.graph.scene import GraphScene
from vfx_texture_lab.graph_assets import (
    GRAPH_INSTANCE_TYPE,
    GRAPH_OUTPUT_TYPE,
    instance_parameters_for_asset,
    parse_graph_asset_interface,
)
from vfx_texture_lab.main_window import GraphDocumentSession, MainWindow
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.ui.graph_explorer import ExplorerGraphInfo, GraphExplorer


def connect(scene, source, output, target, input_name):
    assert scene.add_connection(
        source.output_ports[output], target.input_ports[input_name], record_undo=False
    ) is not None


def make_asset_scene(registry, value: float = 0.4):
    scene = GraphScene(registry)
    constant = scene.create_node(
        "generator.constant", QPointF(), parameters={"value": value}, record_undo=False
    )
    output = scene.create_node(
        GRAPH_OUTPUT_TYPE, QPointF(220, 0), parameters={"name": "Height"}, record_undo=False
    )
    connect(scene, constant, "Image", output, "Value")
    scene.undo_stack.clear()
    scene.undo_stack.setClean()
    return scene, constant


class PreviewStub:
    def project_state(self):
        return {}


class ExplorerStub:
    def update_graph(self, _info):
        pass


class SessionHarness:
    _active_graph_session = MainWindow._active_graph_session
    _session_explorer_info = MainWindow._session_explorer_info
    _open_session_uid_for_path = MainWindow._open_session_uid_for_path
    _instance_open_session_uid = MainWindow._instance_open_session_uid
    _session_depends_on = MainWindow._session_depends_on
    _can_insert_open_graph_instance = MainWindow._can_insert_open_graph_instance
    _project_data_for_session = MainWindow._project_data_for_session
    _dependant_open_instances = MainWindow._dependant_open_instances
    _bind_linked_instances_to_open_sessions = MainWindow._bind_linked_instances_to_open_sessions
    _propagate_live_graph_source = MainWindow._propagate_live_graph_source

    def _update_graph_explorer_entry(self, _uid):
        pass


def main() -> None:
    app = QApplication.instance() or QApplication([])
    registry = build_registry()
    temp = Path(tempfile.mkdtemp(prefix="vfx-graph-explorer-test-"))

    # Basic Explorer presentation: active graph is bold, dirty graphs carry an
    # asterisk, and double-click activation addresses the stable session UID.
    explorer = GraphExplorer()
    activated: list[str] = []
    explorer.activateRequested.connect(activated.append)
    explorer.update_graph(ExplorerGraphInfo("a", "Rock Generator", dirty=True))
    explorer.update_graph(ExplorerGraphInfo("b", "Final Material", active=True))
    assert explorer._items["a"].text(0) == "Rock Generator *"
    assert explorer._items["b"].font(0).bold()
    explorer.tree._activate_item(explorer._items["a"], 0)
    assert activated == ["a"]

    source_scene, source_constant = make_asset_scene(registry, 0.25)
    parent_scene = GraphScene(registry)
    source_path = temp / "source.vfxgraph"
    source_path.write_text(json.dumps(source_scene.to_dict(), indent=2), encoding="utf-8")

    source_session = GraphDocumentSession(
        uid="source", scene=source_scene, document=DocumentSettings(),
        current_path=source_path.resolve(), viewport_state={}, display_name="Source.vfxgraph"
    )
    parent_session = GraphDocumentSession(
        uid="parent", scene=parent_scene, document=DocumentSettings(),
        current_path=(temp / "parent.vfxgraph").resolve(), viewport_state={}, display_name="Parent.vfxgraph"
    )

    harness = SessionHarness()
    harness.registry = registry
    harness._graph_sessions = OrderedDict([
        (source_session.uid, source_session),
        (parent_session.uid, parent_session),
    ])
    harness._active_graph_session_uid = parent_session.uid
    harness._propagating_live_graphs = False
    harness._loading = False
    harness._embedded_asset_cache = {}
    harness.preview_3d_panel = PreviewStub()
    harness.graph_explorer = ExplorerStub()
    harness._document_dirty = False

    source_data = source_scene.to_dict()
    interface = parse_graph_asset_interface(source_data, registry, source_path=source_path)
    params = instance_parameters_for_asset(
        source_data, interface, source_path=source_path, embedded=False
    )
    linked = parent_scene.create_node(
        GRAPH_INSTANCE_TYPE, QPointF(), parameters=params, record_undo=False
    )
    assert linked.parameters["_asset_mode"] == "Linked"

    # Opening a linked source turns existing parent instances into authoritative
    # in-memory Session links without altering their public identity.
    harness._bind_linked_instances_to_open_sessions()
    assert linked.parameters["_asset_mode"] == "Session"
    assert linked.parameters["_asset_session_uid"] == source_session.uid
    assert harness._dependant_open_instances(source_session.uid) == [(parent_session, linked)]

    # Edits to an open source are propagated from memory before the file is
    # saved. Saved-source parents remain linked on disk but use the live cached
    # revision during the session.
    source_constant.parameters["value"] = 0.81
    harness._propagate_live_graph_source(source_session.uid)
    cached = linked.parameters["_asset_cached_graph"]
    cached_constant = next(node for node in cached["nodes"] if node["uid"] == source_constant.uid)
    assert cached_constant["parameters"]["value"] == 0.81

    # Live dependency updates propagate through more than one nesting level in
    # one pass: Source -> Parent asset -> Grandparent instance.
    parent_output = parent_scene.create_node(
        GRAPH_OUTPUT_TYPE, QPointF(280, 0), parameters={"name": "Height"}, record_undo=False
    )
    public_name = linked.definition.output_names[0]
    connect(parent_scene, linked, public_name, parent_output, "Value")
    parent_asset_data = harness._project_data_for_session(
        parent_session, serialise_live_instances=False
    )
    parent_asset_interface = parse_graph_asset_interface(
        parent_asset_data, registry, source_path=parent_session.current_path
    )
    grand_scene = GraphScene(registry)
    grand_params = instance_parameters_for_asset(
        parent_asset_data, parent_asset_interface,
        source_path=parent_session.current_path, embedded=False,
    )
    grand_params["_asset_mode"] = "Session"
    grand_params["_asset_session_uid"] = parent_session.uid
    grand_params["_asset_cached_graph"] = deepcopy(parent_asset_data)
    grand_instance = grand_scene.create_node(
        GRAPH_INSTANCE_TYPE, QPointF(), parameters=grand_params, record_undo=False
    )
    grand_session = GraphDocumentSession(
        uid="grand", scene=grand_scene, document=DocumentSettings(),
        current_path=(temp / "grand.vfxgraph").resolve(), viewport_state={},
        display_name="Grand.vfxgraph",
    )
    harness._graph_sessions[grand_session.uid] = grand_session
    source_constant.parameters["value"] = 0.79
    harness._propagate_live_graph_source(source_session.uid)
    grand_cached = grand_instance.parameters["_asset_cached_graph"]
    parent_instance_record = next(
        node for node in grand_cached["nodes"] if node["uid"] == linked.uid
    )
    nested_source = parent_instance_record["parameters"]["_asset_cached_graph"]
    nested_constant = next(
        node for node in nested_source["nodes"] if node["uid"] == source_constant.uid
    )
    assert nested_constant["parameters"]["value"] == 0.79

    parent_payload = harness._project_data_for_session(parent_session)
    serialized_instance = next(
        node for node in parent_payload["nodes"] if node["uid"] == linked.uid
    )
    assert serialized_instance["parameters"]["_asset_mode"] == "Linked"
    assert Path(serialized_instance["parameters"]["_asset_path"]).resolve() == source_path.resolve()
    assert "_asset_session_uid" not in serialized_instance["parameters"]

    # Unsaved sources serialize as embedded graph snapshots and make the parent
    # dirty whenever their live contents change.
    source_session.current_path = None
    linked.parameters["_asset_path"] = ""
    source_constant.parameters["value"] = 0.63
    harness._propagate_live_graph_source(source_session.uid)
    assert parent_session.document_dirty
    unsaved_payload = harness._project_data_for_session(parent_session)
    unsaved_instance = next(
        node for node in unsaved_payload["nodes"] if node["uid"] == linked.uid
    )
    assert unsaved_instance["parameters"]["_asset_mode"] == "Embedded"
    assert isinstance(unsaved_instance["parameters"]["_asset_embedded_graph"], dict)

    # Cycle checks follow both live session IDs and linked paths to other open
    # documents. A source that already contains its parent cannot be dropped
    # back into that parent.
    parent_data = parent_scene.to_dict()
    parent_interface = {
        "name": "Parent", "inputs": [],
        "outputs": [{
            "id": "dummy", "port": "dummy", "name": "Dummy",
            "kind": "grayscale", "description": "", "order": 0,
            "primary_preview": True,
        }],
        "parameters": [], "warnings": [],
    }
    reverse_params = instance_parameters_for_asset(
        parent_data, parent_interface, source_path=parent_session.current_path, embedded=False
    )
    reverse_params["_asset_mode"] = "Session"
    reverse_params["_asset_session_uid"] = parent_session.uid
    source_scene.create_node(
        GRAPH_INSTANCE_TYPE, QPointF(300, 0), parameters=reverse_params, record_undo=False
    )
    allowed, reason = harness._can_insert_open_graph_instance(source_session.uid)
    assert not allowed
    assert "recursive" in reason.lower()

    # Path-aware dependency resolution also sees a normal linked reference to an
    # already-open graph, not only explicit Session-mode nodes.
    source_session.current_path = source_path.resolve()
    linked.parameters["_asset_mode"] = "Linked"
    linked.parameters.pop("_asset_session_uid", None)
    linked.parameters["_asset_path"] = str(source_path.resolve())
    assert harness._session_depends_on(parent_session.uid, source_session.uid)

    print(
        "graph explorer test passed: document list state, open-source binding, live saved/unsaved "
        "propagation, linked/embedded serialization and recursive-drop safety"
    )


if __name__ == "__main__":
    main()
