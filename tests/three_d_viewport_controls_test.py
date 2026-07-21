from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from vfx_texture_lab.main_window import MainWindow
from vfx_texture_lab.three_d.settings import VIEWPORT_DEFAULTS


def main() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    app.processEvents()

    panel = window.preview_3d_panel
    assert panel.settings_button.isVisible()
    assert not panel.settings_frame.isVisible()
    panel.settings_button.click()
    app.processEvents()
    assert window.parameters_panel.title.text() == "3D Viewport Settings"
    assert panel.settings_frame.isVisible()
    assert panel.settings_frame.parent() is window.parameters_panel.form_host
    assert tuple(panel.settings_groups) == ("Mesh", "Displacement", "Camera", "Lighting", "Display", "Quality")

    panel.set_viewport_setting("sun_azimuth", 17.0)
    panel.canvas.renderer.restore_camera_state({"yaw": 1.2, "pitch": 0.3, "distance": 4.1})
    panel.view_combo.setCurrentText("Front")
    state = panel.project_state()
    assert state["settings"]["sun_azimuth"] == 17.0
    assert state["camera"]["view"] == "Front"
    project = window._project_data()
    assert project["viewport_3d"] == state

    panel.reset_project_state()
    assert panel.viewport_setting("sun_azimuth") == VIEWPORT_DEFAULTS["sun_azimuth"]
    panel.load_project_state(state)
    assert panel.viewport_setting("sun_azimuth") == 17.0
    assert panel.view_combo.currentText() == "Front"

    node = next(iter(window.scene.nodes.values()))
    window.scene.clearSelection()
    node.setSelected(True)
    app.processEvents()
    assert window.parameters_panel.title.text() != "3D Viewport Settings"
    assert panel.settings_frame.parent() is panel._settings_parking

    window.material_controller.cancel()
    window._document_dirty = False
    window._recovered_dirty = False
    window.scene.undo_stack.setClean()
    window._set_dirty(False)
    window.close()
    app.processEvents()
    print("3D viewport inspector and per-document state test passed")


if __name__ == "__main__":
    main()
