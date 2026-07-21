from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.ui.preview import PreviewPanel
from vfx_texture_lab.main_window import MainWindow


def main() -> int:
    app = QApplication.instance() or QApplication([])
    panel = PreviewPanel()
    panel.resize(900, 900)
    image = QImage(128, 128, QImage.Format.Format_RGBA8888)
    image.fill(0xFFFFFFFF)
    panel.canvas.set_image(image)
    panel.show()
    app.processEvents()

    fit_scale = panel.canvas.display_scale
    assert fit_scale > 1.0, fit_scale
    assert panel.zoom_label.text() != "100%", panel.zoom_label.text()

    panel.one_to_one_button.click()
    app.processEvents()
    assert abs(panel.canvas.display_scale - 1.0) < 1.0e-9
    assert panel.zoom_label.text() == "100%"

    panel.fit_button.click()
    app.processEvents()
    assert panel.canvas.display_scale > 1.0
    assert panel.zoom_label.text() != "100%"
    panel.close()

    parameters = (ROOT / "vfx_texture_lab/ui/parameters.py").read_text()
    main_window = (ROOT / "vfx_texture_lab/main_window.py").read_text()
    export_dialog = (ROOT / "vfx_texture_lab/ui/export_dialog.py").read_text()
    assert 'node.definition.type_id in {"output.image", "output.texture_set"}' in parameters
    assert 'node.definition.type_id not in {self.IMAGE_OUTPUT_NODE_TYPE, self.TEXTURE_SET_NODE_TYPE}' in main_window
    assert 'quick_collision = "Replace existing"' in main_window
    assert 'default_collision: str = "Replace existing"' in export_dialog
    assert 'self.collision.addItems(("Replace existing", "Add numeric suffix", "Skip existing"))' in export_dialog

    migrated = MainWindow._migrate_project_data({
        "version": 9,
        "nodes": [{
            "type": MainWindow.TEXTURE_SET_NODE_TYPE,
            "parameters": {"_quick_export_collision": "Add numeric suffix"},
        }],
    })
    assert migrated["nodes"][0]["parameters"]["_quick_export_collision"] == "Replace existing"
    print("preview zoom and quick export test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
