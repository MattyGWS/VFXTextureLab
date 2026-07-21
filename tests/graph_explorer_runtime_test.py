from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

root = Path(tempfile.mkdtemp(prefix="vfx-graph-explorer-runtime-"))
os.environ.setdefault("QT_QPA_PLATFORM", "minimal")
os.environ["XDG_CONFIG_HOME"] = str(root / "config")
os.environ["XDG_DATA_HOME"] = str(root / "data")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.graph_assets import GRAPH_INSTANCE_TYPE, GRAPH_OUTPUT_TYPE
from vfx_texture_lab.main_window import MainWindow


def main() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    # Graph Explorer starts as a clean working session by default. Reopening
    # the previous saved document set remains available as an explicit opt-in.
    assert not window.restore_graph_session_action.isChecked()
    window.periodic_autosave_timer.stop()
    window.graph_asset_watch_timer.stop()
    window.show()
    app.processEvents()

    source = window._active_graph_session()
    assert source is not None
    source_scene = source.scene
    source_node = next(
        node for node in source_scene.nodes.values()
        if node.definition.type_id == "filter.levels"
    )
    public_output = source_scene.create_node(
        GRAPH_OUTPUT_TYPE,
        QPointF(source_node.pos().x() + 300, source_node.pos().y() - 180),
        parameters={"name": "Height", "primary_preview": True},
        record_undo=False,
    )
    assert source_scene.add_connection(
        source_node.output_port, public_output.input_ports["Value"], record_undo=False
    ) is not None
    source_scene.undo_stack.clear()
    source_scene.undo_stack.setClean()

    # New creates another open graph rather than replacing the source.
    window.new_project()
    parent = window._active_graph_session()
    assert parent is not None and parent.uid != source.uid
    assert len(window._graph_sessions) == 2
    assert window.scene is parent.scene

    # Drag-equivalent insertion creates an authoritative live Session instance.
    window._insert_open_graph_instance(source.uid, QPointF(900, -120))
    instance = next(
        node for node in parent.scene.nodes.values()
        if node.definition.type_id == GRAPH_INSTANCE_TYPE
        and node.parameters.get("_asset_session_uid") == source.uid
    )
    assert instance.parameters["_asset_mode"] == "Session"
    assert "Height" in [port.display_name for port in instance.output_ports.values()]

    # Graph-specific actions must follow the active session rather than remain
    # bound to the first scene that existed when MainWindow was constructed.
    disposable = parent.scene.create_node("generator.constant", QPointF(1000, 200), record_undo=False)
    parent.scene.clearSelection()
    disposable.setSelected(True)
    window.delete_action.trigger()
    app.processEvents()
    assert disposable.uid not in parent.scene.nodes
    assert source_node.uid in source.scene.nodes

    # Each document keeps its own scene, selection/undo stack and view state.
    window.graph_view.resetTransform()
    window.graph_view.scale(1.35, 1.35)
    parent_transform = window.graph_view.transform().m11()
    assert window.activate_graph_session(source.uid)
    assert window.scene is source.scene
    assert window.activate_graph_session(parent.uid)
    assert window.scene is parent.scene
    assert abs(window.graph_view.transform().m11() - parent_transform) < 1e-6

    # Live child edits refresh the parent from memory without a save/reload loop.
    assert window.activate_graph_session(source.uid)
    old_scale = float(source_node.parameters["in_mid"])
    source.scene.change_node_parameter(source_node, "in_mid", min(old_scale + 0.08, 0.9))
    window._propagate_live_graph_source(source.uid)
    cached = instance.parameters["_asset_cached_graph"]
    cached_source = next(node for node in cached["nodes"] if node["uid"] == source_node.uid)
    assert cached_source["parameters"]["in_mid"] != old_scale

    # Closing an unsaved source can freeze it into dependants, and that embedded
    # graph can later be reopened as another editable Explorer document.
    assert window.activate_graph_session(parent.uid)
    window._detach_session_dependants(source)
    assert instance.parameters["_asset_mode"] == "Embedded"
    window._remove_graph_session_without_prompt(source.uid)
    before = set(window._graph_sessions)
    window._open_embedded_graph_instance(instance.uid)
    embedded = window._active_graph_session()
    assert embedded is not None and embedded.uid not in before
    assert instance.parameters["_asset_mode"] == "Session"
    assert instance.parameters["_asset_session_uid"] == embedded.uid

    # Keep shutdown non-interactive for the automated test.
    for session in window._graph_sessions.values():
        session.scene.undo_stack.clear()
        session.scene.undo_stack.setClean()
        session.document_dirty = False
        session.recovered_dirty = False
    window._document_dirty = False
    window._recovered_dirty = False
    window.close()
    app.processEvents()

    print(
        "graph explorer runtime test passed: multi-document switching, dynamic graph actions, "
        "live in-memory instances and reopenable embedded graphs"
    )


if __name__ == "__main__":
    main()
