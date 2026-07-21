from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

root = Path(tempfile.mkdtemp(prefix="vfx-multigraph-autosave-"))
os.environ.setdefault("QT_QPA_PLATFORM", "minimal")
os.environ["XDG_CONFIG_HOME"] = str(root / "config")
os.environ["XDG_DATA_HOME"] = str(root / "data")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QCoreApplication, QPointF
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.main_window import MainWindow


def main() -> None:
    QCoreApplication.setOrganizationName("VFXTextureLabTests")
    QCoreApplication.setApplicationName("MultiGraphAutosaveTest")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.periodic_autosave_timer.stop()
    window.graph_asset_watch_timer.stop()
    window.show()
    app.processEvents()

    first = window._active_graph_session()
    assert first is not None
    node_a = next(iter(first.scene.nodes.values()))
    first.scene.change_node_parameter(
        node_a,
        next(spec.name for spec in node_a.definition.parameters if spec.name in node_a.parameters),
        node_a.parameters[next(spec.name for spec in node_a.definition.parameters if spec.name in node_a.parameters)],
        label="Autosave touch A",
    )
    # A no-op parameter command may be ignored; make the graph structurally dirty.
    first.scene.create_node("generator.constant", QPointF(850, 400))

    window.new_project()
    second = window._active_graph_session()
    assert second is not None and second.uid != first.uid
    second.scene.create_node("generator.constant", QPointF(900, 420))
    assert first.dirty and second.dirty

    window._write_autosave()
    payload = json.loads(window._autosave_path.read_text(encoding="utf-8"))
    assert payload["format"] == "vfx-texture-lab-autosave-session"
    entries = window._autosave_graph_entries(payload)
    assert len(entries) == 2
    assert {entry["uid"] for entry in entries} == {first.uid, second.uid}

    # Saving one active graph refreshes rather than deleting recovery data for
    # another modified graph that remains open in Explorer.
    destination = root / "second.vfxgraph"
    assert window._write_project(destination)
    assert window._autosave_path.is_file()
    refreshed = window._autosave_graph_entries(
        json.loads(window._autosave_path.read_text(encoding="utf-8"))
    )
    assert len(refreshed) == 1
    assert refreshed[0]["uid"] == first.uid

    # A cleanly saved file newer than its autosave entry is filtered as stale.
    entry = refreshed[0]
    entry_data = entry["data"]
    stale_path = root / "first.vfxgraph"
    stale_path.write_text("{}", encoding="utf-8")
    entry["original_path"] = str(stale_path)
    entry_data["_autosave"]["original_path"] = str(stale_path)
    entry_data["_autosave"]["timestamp"] = 1.0
    assert window._autosave_entry_is_stale(entry)

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
        "graph explorer autosave test passed: all dirty documents are bundled and saving one graph "
        "preserves recovery data for the others"
    )


if __name__ == "__main__":
    main()
