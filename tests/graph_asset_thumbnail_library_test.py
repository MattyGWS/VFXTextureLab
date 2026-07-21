from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

root = Path(tempfile.mkdtemp(prefix="vfx-asset-thumbnail-library-"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["XDG_CONFIG_HOME"] = str(root / "config")
os.environ["XDG_DATA_HOME"] = str(root / "data")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PySide6.QtCore import QPointF, QSettings
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QPushButton

from vfx_texture_lab.document import GraphAssetMetadata
from vfx_texture_lab.graph import GraphScene
from vfx_texture_lab.graph_asset_library import add_graph_asset_directory, load_graph_asset_files
from vfx_texture_lab.graph_asset_thumbnails import decode_thumbnail_image, encode_thumbnail_image
from vfx_texture_lab.graph_assets import GRAPH_OUTPUT_TYPE
from vfx_texture_lab.main_window import MainWindow
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.ui.library import NodeLibrary, ROLE_KIND
from vfx_texture_lab.ui.node_preferences import NodePreferences
from vfx_texture_lab.ui.parameters import GraphPropertiesWidget


def connect(scene, source, output, target, input_name):
    assert scene.add_connection(
        source.output_ports[output], target.input_ports[input_name], record_undo=False
    ) is not None


def write_valid_asset(path: Path, thumbnail: str) -> None:
    registry = build_registry()
    scene = GraphScene(registry)
    source = scene.create_node("generator.constant", QPointF(), record_undo=False)
    output = scene.create_node(
        GRAPH_OUTPUT_TYPE,
        QPointF(220, 0),
        parameters={"name": "Height", "primary_preview": True},
        record_undo=False,
    )
    connect(scene, source, "Image", output, "Value")
    data = scene.to_dict()
    data["graph_asset"] = {
        "asset_id": "thumbnail-asset",
        "name": "Thumbnail Rock",
        "description": "A searchable thumbnail fixture.",
        "category": "Terrain",
        "tags": ["stone", "cliff"],
        "author": "Library Tester",
        "version": "2.3.0",
        "thumbnail_png": thumbnail,
        "thumbnail_source": "imported",
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_invalid_asset(path: Path) -> None:
    registry = build_registry()
    scene = GraphScene(registry)
    scene.create_node("generator.constant", QPointF(), record_undo=False)
    data = scene.to_dict()
    data["graph_asset"] = {"name": "Broken Library Asset", "author": "Library Tester"}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def walk(tree):
    pending = [tree.topLevelItem(index) for index in range(tree.topLevelItemCount())]
    while pending:
        item = pending.pop(0)
        yield item
        pending.extend(item.child(index) for index in range(item.childCount()))


def main() -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings()
    settings.clear()

    image = QImage(96, 48, QImage.Format.Format_RGBA8888)
    image.fill(0xFF4A7DB8)
    encoded = encode_thumbnail_image(image)
    decoded = decode_thumbnail_image(encoded)
    assert not decoded.isNull() and decoded.size().width() == 256 and decoded.size().height() == 256

    metadata = GraphAssetMetadata.from_dict({
        "name": "Metadata Thumbnail",
        "thumbnail_png": encoded,
        "thumbnail_source": "2d",
    })
    restored = GraphAssetMetadata.from_dict(metadata.to_dict())
    assert restored.thumbnail_png == encoded and restored.thumbnail_source == "2d"

    asset_dir = root / "assets"
    asset_dir.mkdir()
    valid_path = asset_dir / "thumbnail_rock.vfxgraph"
    invalid_path = asset_dir / "broken.vfxgraph"
    write_valid_asset(valid_path, encoded)
    write_invalid_asset(invalid_path)
    assert add_graph_asset_directory(asset_dir, settings)

    registry = build_registry()
    valid_only = load_graph_asset_files(registry, settings)
    assert [path for path, _interface in valid_only] == [valid_path.resolve()]
    all_assets = load_graph_asset_files(registry, settings, include_invalid=True)
    assert len(all_assets) == 2
    by_name = {interface["name"]: interface for _path, interface in all_assets}
    assert by_name["Thumbnail Rock"]["valid"]
    assert not by_name["Broken Library Asset"]["valid"]

    library = NodeLibrary(registry, NodePreferences())
    items = [item for item in walk(library.tree) if item.data(0, ROLE_KIND) in {"asset", "asset_problem"}]
    assert len(items) == 2
    valid_item = next(item for item in items if item.data(0, ROLE_KIND) == "asset")
    problem_item = next(item for item in items if item.data(0, ROLE_KIND) == "asset_problem")
    assert problem_item.text(0).startswith("⚠")
    library.tree.setCurrentItem(valid_item)
    app.processEvents()
    assert library.details.isVisibleTo(library)
    assert library.details.thumbnail.pixmap() is not None and not library.details.thumbnail.pixmap().isNull()
    assert "Library Tester" in library.details.metadata.text()
    assert "Height" in library.details.outputs.text()

    for query in ("Library Tester", "cliff", "Height", "2.3.0"):
        library.search.setText(query)
        app.processEvents()
        found = [item for item in walk(library.tree) if item.data(0, ROLE_KIND) == "asset"]
        assert len(found) == 1, query
    library.search.clear()

    window = MainWindow()
    window.periodic_autosave_timer.stop()
    window.graph_asset_watch_timer.stop()
    window.show()
    app.processEvents()
    session = window._active_graph_session()
    assert session is not None
    rgba = np.zeros((64, 128, 4), dtype=np.uint8)
    rgba[..., 0] = 200
    rgba[..., 1] = 90
    rgba[..., 2] = 40
    rgba[..., 3] = 255
    window.preview_panel.set_result(
        "Thumbnail Source", None, None, 128, 64, display_rgba=rgba, data_kind="color"
    )
    window._capture_graph_thumbnail_2d(session.uid)
    assert session.graph_asset.thumbnail_source == "2d"
    assert decode_thumbnail_image(session.graph_asset.thumbnail_png).width() == 256
    assert session.document_dirty
    widget = window.parameters_panel._external_widget
    assert isinstance(widget, GraphPropertiesWidget)
    button_texts = {button.text() for button in widget.findChildren(QPushButton)}
    assert {"Capture 2D", "Capture 3D", "Import Image…", "Clear"}.issubset(button_texts)

    saved = root / "saved_thumbnail.vfxgraph"
    assert window._write_project(saved)
    payload = json.loads(saved.read_text(encoding="utf-8"))
    assert payload["graph_asset"]["thumbnail_png"] == session.graph_asset.thumbnail_png
    assert payload["graph_asset"]["thumbnail_source"] == "2d"
    window._clear_graph_thumbnail(session.uid)
    assert not session.graph_asset.thumbnail_png and not session.graph_asset.thumbnail_source

    for open_session in window._graph_sessions.values():
        open_session.scene.undo_stack.clear()
        open_session.scene.undo_stack.setClean()
        open_session.document_dirty = False
        open_session.recovered_dirty = False
    window._document_dirty = False
    window._recovered_dirty = False
    window.close()
    app.processEvents()

    print(
        "graph asset thumbnail/library test passed: embedded PNG metadata, 2D capture, "
        "rich metadata search, details preview and visible invalid assets"
    )


if __name__ == "__main__":
    main()
