from __future__ import annotations

import os
import tempfile
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.main_window import MainWindow


def main() -> None:
    app = QApplication.instance() or QApplication([])
    QCoreApplication.setOrganizationName("VFXTextureLabTests")
    QCoreApplication.setApplicationName("WorkspaceResetRuntime")
    with tempfile.TemporaryDirectory() as temp:
        QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, temp)
        window = MainWindow()
        window.resize(1400, 900)
        window.show()
        app.processEvents()

        # Exercise the risky path: a floating 3D render dock followed by repeated
        # default-layout restoration. The reset must retain the dock widget and
        # its render canvas rather than removing/recreating either object.
        canvas = window.preview_3d_panel.canvas
        window.preview_3d_dock.setFloating(True)
        app.processEvents()
        for _ in range(8):
            window._perform_workspace_reset()
            app.processEvents()
            assert window.preview_3d_dock.widget() is window.preview_3d_panel
            assert window.preview_3d_panel.canvas is canvas
            assert not window.preview_3d_dock.isFloating()
            assert window.preview_3d_dock in window.tabifiedDockWidgets(window.preview_dock)

        window.material_controller.cancel()
        window._document_dirty = False
        window._recovered_dirty = False
        window.scene.undo_stack.setClean()
        window._set_dirty(False)
        window.close()
        app.processEvents()

    print("workspace reset safely reuses the existing 3D render dock and canvas")


if __name__ == "__main__":
    main()
