from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

root = Path(tempfile.mkdtemp(prefix="vfx-export-template-integration-"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["XDG_CONFIG_HOME"] = str(root / "config")
os.environ["XDG_DATA_HOME"] = str(root / "data")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication, QDialog

from vfx_texture_lab.export_templates import CUSTOM_TEMPLATE_NAME, builtin_template, clone_as_custom
import vfx_texture_lab.main_window as main_window_module
from vfx_texture_lab.main_window import MainWindow


class AcceptedTemplateDialog:
    def __init__(self, template, parent=None) -> None:
        self.template = clone_as_custom(builtin_template("VFX RGBA Masks"), name="Project VFX Packing")

    def exec(self):
        return QDialog.DialogCode.Accepted

    def result_template(self):
        return self.template


def main() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.periodic_autosave_timer.stop()
    window.graph_asset_watch_timer.stop()
    app.processEvents()

    node = next(
        candidate for candidate in window.scene.nodes.values()
        if candidate.definition.type_id == window.TEXTURE_SET_NODE_TYPE
    )
    original_preset = str(node.parameters.get("export_preset"))
    main_window_module.ExportTemplateDialog = AcceptedTemplateDialog
    window._edit_export_template(node.uid)
    app.processEvents()

    assert node.parameters["export_preset"] == CUSTOM_TEMPLATE_NAME
    assert node.parameters["_custom_export_template"]["name"] == "Project VFX Packing"
    assert node.parameters["_custom_export_template"]["files"][0]["map_name"] == "Masks"

    window.scene.undo_stack.undo()
    node = window.scene.nodes[node.uid]
    assert node.parameters.get("export_preset") == original_preset
    assert "_custom_export_template" not in node.parameters
    window.scene.undo_stack.redo()
    node = window.scene.nodes[node.uid]
    assert node.parameters["export_preset"] == CUSTOM_TEMPLATE_NAME

    session = window._active_graph_session()
    assert session is not None
    payload = window._project_data_for_session(session)
    saved_node = next(item for item in payload["nodes"] if item["uid"] == node.uid)
    assert saved_node["parameters"]["_custom_export_template"]["name"] == "Project VFX Packing"

    path = root / "template_graph.vfxgraph"
    assert window._write_project(path)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    disk_node = next(item for item in on_disk["nodes"] if item["uid"] == node.uid)
    assert disk_node["parameters"]["export_preset"] == CUSTOM_TEMPLATE_NAME
    assert disk_node["parameters"]["_custom_export_template"]["files"][0]["bindings"]["R"]["source"] == "Opacity"

    for graph_session in window._graph_sessions.values():
        graph_session.scene.undo_stack.clear()
        graph_session.scene.undo_stack.setClean()
        graph_session.document_dirty = False
        graph_session.recovered_dirty = False
    window.close()
    app.processEvents()
    print("Export template integration test passed: Inspector action, one-step undo/redo and full graph JSON persistence.")


if __name__ == "__main__":
    main()
