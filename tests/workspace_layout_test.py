from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    source = (ROOT / "vfx_texture_lab" / "main_window.py").read_text()
    ast.parse(source)

    assert 'WORKSPACE_SETTINGS_GROUP = "workspace/v1"' in source
    assert "self.saveGeometry()" in source
    assert "self.saveState(self.WORKSPACE_STATE_VERSION)" in source
    assert "self.restoreGeometry(geometry)" in source
    assert "self.restoreState(state, self.WORKSPACE_STATE_VERSION)" in source
    assert "self.settings.sync()" in source

    assert "DockWidgetFloatable" in source
    assert "DockWidgetClosable" in source
    assert "AllowTabbedDocks" in source
    assert "AllowNestedDocks" in source
    assert "GroupedDragging" in source
    assert "QMainWindow.DockOption.AnimatedDocks" not in source
    assert "self.setAnimated(False)" in source
    assert "QApplication.mouseButtons()" in source
    assert "self.tabifyDockWidget(self.preview_dock, self.preview_3d_dock)" in source
    assert "self.tabifyDockWidget(self.preview_dock, self.canvas_dock)" in source

    default_start = source.index("    def _apply_default_workspace_layout")
    default_end = source.index("    def eventFilter", default_start)
    reset_source = source[default_start:default_end]
    assert "removeDockWidget" not in reset_source
    assert "self.preview_3d_panel.canvas.setUpdatesEnabled(False)" in reset_source
    assert "QTimer.singleShot(0, self._perform_workspace_reset)" in reset_source

    assert 'QAction("Tab 2D, 3D and Canvas Outputs", self)' in source
    assert 'QAction("Reset Workspace Layout", self)' in source
    assert "dock.toggleViewAction()" in source
    assert "dock.installEventFilter(self)" in source
    assert "QEvent.Type.WindowStateChange" in source
    assert "_recover_offscreen_windows" in source

    stylesheet = (ROOT / "vfx_texture_lab" / "theme.py").read_text()
    assert "QTabBar::tab" in stylesheet
    assert "QTabBar::tab:selected" in stylesheet

    print("workspace layout test passed")


if __name__ == "__main__":
    main()
