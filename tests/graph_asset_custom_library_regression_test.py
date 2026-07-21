from __future__ import annotations

import json
from dataclasses import replace
import os
import sys
import tempfile
from pathlib import Path

root = Path(tempfile.mkdtemp(prefix="vfx-custom-graph-library-"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["XDG_CONFIG_HOME"] = str(root / "config")
os.environ["XDG_DATA_HOME"] = str(root / "data")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPointF, QSettings
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.custom_nodes import CustomNodePackageManager
from vfx_texture_lab.graph import GraphScene
from vfx_texture_lab.graph_assets import GRAPH_OUTPUT_TYPE
from vfx_texture_lab.main_window import MainWindow
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.ui.library import NodeLibrary, ROLE_KIND
from vfx_texture_lab.ui.node_preferences import NodePreferences


def connect(scene, source, output, target, input_name):
    connection = scene.add_connection(
        source.output_ports[output], target.input_ports[input_name], record_undo=False
    )
    assert connection is not None
    return connection


def write_asset(path: Path) -> None:
    registry = build_registry()
    scene = GraphScene(registry)
    source = scene.create_node("generator.constant", QPointF(), record_undo=False)
    output = scene.create_node(
        GRAPH_OUTPUT_TYPE,
        QPointF(220, 0),
        parameters={"name": "Grass Material", "primary_preview": True},
        record_undo=False,
    )
    connect(scene, source, "Image", output, "Value")
    data = scene.to_dict()
    data["graph_asset"] = {
        "asset_id": "grass-custom-library-test",
        "name": "Grass Generator",
        "description": "Reusable grass generator fixture.",
        "category": "Graph Assets",
        "tags": ["grass", "terrain", "green"],
        "author": "Library Regression",
        "version": "1.0.0",
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def asset_items(library: NodeLibrary):
    pending = [library.tree.topLevelItem(index) for index in range(library.tree.topLevelItemCount())]
    result = []
    while pending:
        item = pending.pop(0)
        if item.data(0, ROLE_KIND) in {"asset", "asset_problem"}:
            result.append(item)
        pending.extend(item.child(index) for index in range(item.childCount()))
    return result


def semantic_connections(scene: GraphScene):
    return sorted(
        (connection.source_node.uid, connection.output_name, connection.target_node.uid, connection.input_name)
        for connection in scene.connections
    )


def assert_live_ports(scene: GraphScene) -> None:
    for connection in scene.connections:
        assert connection.source_port is connection.source_node.output_ports[connection.output_name]
        assert connection.target_port is connection.target_node.input_ports[connection.input_name]
        assert connection.source_port.scene() is scene
        assert connection.target_port.scene() is scene


def main() -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings()
    settings.clear()

    asset_dir = root / "mixed-library"
    asset_dir.mkdir(parents=True)
    asset_path = asset_dir / "Grass_Generator.vfxgraph"
    write_asset(asset_path)

    manager = CustomNodePackageManager(settings)
    entry = manager.add_library(asset_dir, "Mixed VFX Library")

    library = NodeLibrary(build_registry(), NodePreferences())
    items = asset_items(library)
    assert len(items) == 1 and items[0].text(0).endswith("Grass Generator")
    library.search.setText("terrain green")
    app.processEvents()
    assert len(asset_items(library)) == 1

    manager.set_library_enabled(entry.uid, False)
    library.search.clear()
    library.rebuild()
    assert not asset_items(library), "Disabled shared libraries must hide their graph assets"
    manager.set_library_enabled(entry.uid, True)
    library.rebuild()
    assert len(asset_items(library)) == 1

    # Adding an asset-only shared library while the application is running must
    # refresh the Node Library without touching the live graph topology.
    settings.clear()
    window = MainWindow()
    window.periodic_autosave_timer.stop()
    window.graph_asset_watch_timer.stop()
    window.show()
    app.processEvents()
    before = semantic_connections(window.scene)
    assert before
    window.package_manager.add_library(asset_dir, "Mixed VFX Library")
    window._reload_custom_nodes()
    app.processEvents()
    assert semantic_connections(window.scene) == before
    assert_live_ports(window.scene)
    assert any(item.text(0).endswith("Grass Generator") for item in asset_items(window.library_panel))

    # Actual definition rebinding is also connection-safe: every outgoing wire
    # is retargeted to the replacement output PortItem by stable socket name.
    candidate = next(connection for connection in window.scene.connections if connection.source_node.output_ports)
    changed_node = candidate.source_node
    old_source_port = candidate.source_port
    replacement_definition = replace(changed_node.definition, description=changed_node.definition.description + " ")
    window.registry.register(replacement_definition, replace=True)
    window.scene.rebind_registry_definitions()
    app.processEvents()
    assert semantic_connections(window.scene) == before
    assert_live_ports(window.scene)
    refreshed = next(
        connection for connection in window.scene.connections
        if connection.source_node.uid == changed_node.uid and connection.output_name == candidate.output_name
    )
    assert refreshed.source_port is not old_source_port

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
        "custom graph library regression passed: shared Custom Libraries discover .vfxgraph files, "
        "respect enabled state, refresh immediately and preserve live wire endpoints"
    )


if __name__ == "__main__":
    main()
