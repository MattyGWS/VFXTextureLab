from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

root = Path(tempfile.mkdtemp(prefix="vfx-graph-inspector-"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["XDG_CONFIG_HOME"] = str(root / "config")
os.environ["XDG_DATA_HOME"] = str(root / "data")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.graph_assets import GRAPH_OUTPUT_TYPE
from vfx_texture_lab.main_window import MainWindow
from vfx_texture_lab.ui.parameters import GraphPropertiesWidget


def main() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.periodic_autosave_timer.stop()
    window.graph_asset_watch_timer.stop()
    window.show()
    app.processEvents()

    first = window._active_graph_session()
    assert first is not None
    assert window.parameters_dock.windowTitle() == "Inspector"
    assert window.parameters_panel.is_showing_graph(first.uid)
    graph_widget = window.parameters_panel._external_widget
    assert isinstance(graph_widget, GraphPropertiesWidget)

    # Graph metadata is editable, dirty-aware and included in serialization.
    graph_widget.name_edit.setText("Terrain Surface")
    graph_widget.name_edit.editingFinished.emit()
    graph_widget.tags_edit.setText("terrain, rock, Terrain")
    graph_widget.tags_edit.editingFinished.emit()
    app.processEvents()
    assert first.graph_asset.name == "Terrain Surface"
    assert first.graph_asset.tags == ["terrain", "rock"]
    assert first.document_dirty
    payload = window._project_data_for_session(first)
    assert payload["graph_asset"]["name"] == "Terrain Surface"
    assert payload["graph_asset"]["asset_id"] == first.graph_asset.asset_id

    # A second graph can be inspected with one click without changing canvas.
    window.new_project()
    second = window._active_graph_session()
    assert second is not None and second.uid != first.uid
    window.graph_explorer.tree._select_item(window.graph_explorer._items[first.uid], 0)
    app.processEvents()
    assert window._active_graph_session_uid == second.uid
    assert window.parameters_panel.is_showing_graph(first.uid)

    # Double-click activation switches canvas and initially inspects the graph.
    window.graph_explorer.tree._activate_item(window.graph_explorer._items[first.uid], 0)
    app.processEvents()
    assert window._active_graph_session_uid == first.uid
    assert window.parameters_panel.is_showing_graph(first.uid)
    assert not window.scene.selectedItems()

    # Selecting a node restores node parameters; clearing focus restores the
    # active graph even if Explorer had previously inspected another document.
    node = next(iter(window.scene.nodes.values()))
    node.setSelected(True)
    app.processEvents()
    assert window.parameters_panel.item is node
    window.graph_explorer.tree._select_item(window.graph_explorer._items[second.uid], 0)
    assert window.parameters_panel.is_showing_graph(second.uid)
    window._inspect_active_graph()
    assert window.parameters_panel.is_showing_graph(first.uid)

    # The published-interface summary refreshes while graph properties are open.
    source = next(
        candidate for candidate in window.scene.nodes.values()
        if candidate.definition.output_names
        and candidate.definition.type_id not in {GRAPH_OUTPUT_TYPE, "graph.input"}
        and candidate.definition.output_kind(candidate.definition.output_names[0]) in {
            "grayscale", "color", "vector", "image_any"
        }
    )
    output = window.scene.create_node(
        GRAPH_OUTPUT_TYPE,
        QPointF(source.pos().x() + 300, source.pos().y()),
        parameters={"name": "Published Result", "primary_preview": True},
        record_undo=False,
    )
    assert window.scene.add_connection(
        source.output_ports[source.definition.output_names[0]],
        output.input_ports["Value"],
        record_undo=False,
    ) is not None
    window.scene.graphChanged.emit()
    app.processEvents()
    refreshed = window.parameters_panel._external_widget
    assert isinstance(refreshed, GraphPropertiesWidget)
    visible = "\n".join(label.text() for label in refreshed.findChildren(type(refreshed.asset_id_label)))
    assert "Published Result" in visible

    # Save/reload preserves identity and authored metadata.
    path = root / "terrain_surface.vfxgraph"
    saved_id = first.graph_asset.asset_id
    assert window._write_project(path)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["graph_asset"]["asset_id"] == saved_id
    assert on_disk["graph_asset"]["name"] == "Terrain Surface"
    window.graph_asset.name = "Temporary Change"
    window._load_project_path(path)
    assert window.graph_asset.name == "Terrain Surface"
    assert window.graph_asset.asset_id == saved_id

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
        "graph inspector test passed: contextual graph/node inspection, Explorer single/double click, "
        "persistent metadata and live published-interface summary"
    )


if __name__ == "__main__":
    main()
