from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

root = Path(tempfile.mkdtemp(prefix="vfx-graph-asset-ui-"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["XDG_CONFIG_HOME"] = str(root / "config")
os.environ["XDG_DATA_HOME"] = str(root / "data")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QByteArray, QCoreApplication, QMimeData, QPointF, QSettings, Qt, QUrl
from PySide6.QtWidgets import QApplication, QLabel, QToolButton

from vfx_texture_lab.graph import GraphScene, GraphView
from vfx_texture_lab.graph.mime import GRAPH_ASSET_MIME_TYPE
from vfx_texture_lab.graph_asset_library import (
    add_graph_asset_directory,
    graph_asset_directories,
    load_graph_asset_files,
    remove_graph_asset_directory,
)
from vfx_texture_lab.graph_assets import GRAPH_OUTPUT_TYPE
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.ui.library import NodeLibrary, ROLE_KIND, ROLE_VALUE
from vfx_texture_lab.ui.parameters import GraphAssetParameterDialog, ParametersPanel
from vfx_texture_lab.ui.node_preferences import NodePreferences
from vfx_texture_lab.ui.search import NodeSearchDialog


def connect(scene: GraphScene, source, output: str, target, input_name: str) -> None:
    assert scene.add_connection(
        source.output_ports[output], target.input_ports[input_name], record_undo=False
    ) is not None


def create_asset(path: Path) -> None:
    registry = build_registry()
    scene = GraphScene(registry)
    constant = scene.create_node(
        "generator.constant", QPointF(), parameters={"value": 0.65}, record_undo=False
    )
    scene.set_parameter_socket_exposed(constant, "value", True)
    scene.set_parameter_asset_metadata(
        constant, "value",
        {
            "name": "Surface Level",
            "description": "Published UI regression control.",
            "group": "Surface",
            "order": 10,
            "published": True,
        },
    )
    output = scene.create_node(
        GRAPH_OUTPUT_TYPE,
        QPointF(240, 0),
        parameters={"name": "Height", "primary_preview": True},
        record_undo=False,
    )
    connect(scene, constant, "Image", output, "Value")
    data = scene.to_dict()
    data["graph_asset"] = {
        "name": "UI Test Asset",
        "category": "Terrain",
        "description": "Reusable graph-asset UI fixture.",
        "version": "1.0.0",
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def walk_tree(tree):
    pending = [tree.topLevelItem(index) for index in range(tree.topLevelItemCount())]
    while pending:
        item = pending.pop(0)
        yield item
        pending.extend(item.child(index) for index in range(item.childCount()))


def main() -> int:
    QCoreApplication.setOrganizationName("VFXTextureLabTests")
    QCoreApplication.setApplicationName("GraphAssetUITest")
    app = QApplication.instance() or QApplication([])
    del app
    settings = QSettings()
    settings.clear()

    assets_dir = root / "external-assets"
    assets_dir.mkdir(parents=True)
    asset_path = assets_dir / "ui_test_asset.vfxgraph"
    create_asset(asset_path)

    assert add_graph_asset_directory(assets_dir, settings)
    assert assets_dir.resolve() in graph_asset_directories(settings)

    registry = build_registry()
    discovered = load_graph_asset_files(registry, settings)
    assert [(path, interface["name"]) for path, interface in discovered] == [
        (asset_path.resolve(), "UI Test Asset")
    ]

    preferences = NodePreferences()
    library = NodeLibrary(registry, preferences)
    asset_items = [
        item for item in walk_tree(library.tree)
        if item.data(0, ROLE_KIND) == "asset"
    ]
    assert len(asset_items) == 1
    assert Path(str(asset_items[0].data(0, ROLE_VALUE))).resolve() == asset_path.resolve()
    assert "Graph Assets" in [
        library.tree.topLevelItem(index).text(0)
        for index in range(library.tree.topLevelItemCount())
    ]

    activated: list[str] = []
    library.graphAssetActivated.connect(activated.append)
    library._activated(asset_items[0], 0)
    assert activated == [str(asset_path.resolve())]

    search = NodeSearchDialog(registry, preferences)
    search._populate("UI Test")
    found_asset = False
    found_import = False
    for row in range(search.list_widget.count()):
        item = search.list_widget.item(row)
        kind = item.data(Qt.ItemDataRole.UserRole + 1)
        found_asset |= kind == "asset" and Path(str(item.data(Qt.ItemDataRole.UserRole))).resolve() == asset_path.resolve()
        found_import |= kind == "asset_browse"
    assert found_asset and found_import

    # Loose-wire search remains uncluttered: it contains no registered assets or
    # file-picker action, only compatible built-in nodes.
    filtered = NodeSearchDialog(registry, preferences, definition_filter=lambda _definition: True)
    filtered._populate("UI Test")
    assert all(
        filtered.list_widget.item(row).data(Qt.ItemDataRole.UserRole + 1) not in {"asset", "asset_browse"}
        for row in range(filtered.list_widget.count())
    )

    scene = GraphScene(registry)
    view = GraphView(scene, preferences)

    # OS/file-manager URL drops and Node Library custom MIME both resolve to the
    # same graph asset path.
    url_mime = QMimeData()
    url_mime.setUrls([QUrl.fromLocalFile(str(asset_path))])
    assert Path(view._first_dropped_graph(url_mime)).resolve() == asset_path.resolve()

    library_mime = QMimeData()
    library_mime.setData(GRAPH_ASSET_MIME_TYPE, QByteArray(str(asset_path).encode("utf-8")))
    assert Path(view._first_dropped_graph(library_mime)).resolve() == asset_path.resolve()

    inserted = view._create_graph_asset(str(asset_path), QPointF(100, 80))
    assert inserted is not None
    assert inserted.definition.name == "UI Test Asset"
    assert inserted.definition.output_labels[0][1] == "Height"
    assert [port.display_name for port in inserted.output_ports.values()] == ["Height"]

    # Selecting a Graph Instance must build its actual Parameters page rather
    # than leaving the prior "Nothing selected" page after a slot exception.
    panel = ParametersPanel(scene)
    panel.set_item(inserted)
    assert panel.title.text() == "UI Test Asset"
    visible_text = {label.text() for label in panel.findChildren(QLabel)}
    assert "Surface Level" in visible_text
    assert "Random Seed" in visible_text
    assert not [button for button in panel.findChildren(QToolButton) if button.text() == "A"]

    dialogue = GraphAssetParameterDialog(
        name="Surface Level", description="Published UI regression control.",
        group="Surface", order=10, published=False
    )
    assert dialogue.metadata()["published"] is False

    # Parameters without an explicitly authored group still have a complete
    # graph-asset editor. Ridge Noise / Octaves previously called a removed
    # grouping helper, so clicking the ellipsis appeared to do nothing. The
    # ellipsis is also hidden until the parameter is actually exposed.
    ridged = scene.create_node("noise.ridged", QPointF(420, 180), record_undo=False)
    panel.set_item(ridged)
    assert not [button for button in panel.findChildren(QToolButton) if button.text() == "…"]
    scene.set_parameter_socket_exposed(ridged, "octaves", True)
    panel.set_item(ridged)
    metadata_buttons = [
        button for button in panel.findChildren(QToolButton) if button.text() == "…"
    ]
    assert len(metadata_buttons) == 1 and metadata_buttons[0].isEnabled()
    opened: dict[str, object] = {}
    original_exec = GraphAssetParameterDialog.exec

    def reject_after_capture(self):
        opened["name"] = self.name_edit.text()
        opened["group"] = self.group_edit.text()
        opened["published"] = self.published_check.isChecked()
        return self.DialogCode.Rejected

    GraphAssetParameterDialog.exec = reject_after_capture
    try:
        metadata_buttons[0].click()
        QApplication.processEvents()
    finally:
        GraphAssetParameterDialog.exec = original_exec
    assert opened == {"name": "Octaves", "group": "Parameters", "published": True}

    remove_graph_asset_directory(assets_dir, settings)
    assert assets_dir.resolve() not in graph_asset_directories(settings)

    print(
        "graph asset UI test passed: registered folders, library activation, grouped search, "
        "uncluttered loose-wire search, file-manager drag MIME and canvas insertion"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
