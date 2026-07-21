from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    main_window = (ROOT / "vfx_texture_lab" / "main_window.py").read_text()
    canvas_editor = (ROOT / "vfx_texture_lab" / "ui" / "canvas_editor.py").read_text()
    ast.parse(main_window)
    ast.parse(canvas_editor)

    # Undo/redo must route to the focused Canvas Editor before the graph stack.
    assert 'self.undo_action = QAction("Undo", self)' in main_window
    assert 'self.undo_action.triggered.connect(self._route_undo)' in main_window
    assert 'self.redo_action.triggered.connect(self._route_redo)' in main_window
    assert 'self._canvas_editor_has_focus() and self.canvas_panel.can_undo_canvas()' in main_window
    assert 'self._canvas_editor_has_focus() and self.canvas_panel.can_redo_canvas()' in main_window
    assert 'self.scene.undo_stack.undo()' in main_window
    assert 'self.scene.undo_stack.redo()' in main_window

    # Canvas edits keep a separate per-node compressed history and no longer
    # push ordinary graph snapshot commands for every brush stroke.
    assert 'self._history_by_node: dict[str, list[_CanvasSnapshot]]' in canvas_editor
    assert 'def undo_canvas(self) -> bool:' in canvas_editor
    assert 'def redo_canvas(self) -> bool:' in canvas_editor
    assert 'self.scene.begin_user_action("Paint Canvas")' not in canvas_editor
    assert 'self._push_history(self._stroke_before, after)' in canvas_editor
    assert 'self.canvasChanged.emit()' in canvas_editor

    # Default authoring layout: Parameters stays visible beside one tab group
    # containing the 2D preview, 3D preview and Canvas Editor.
    default_start = main_window.index('    def _apply_default_workspace_layout')
    default_end = main_window.index('    def _reset_workspace_layout', default_start)
    default_layout = main_window[default_start:default_end]
    assert 'self.splitDockWidget(self.parameters_dock, self.preview_dock, Qt.Orientation.Horizontal)' in default_layout
    assert 'self.tabifyDockWidget(self.preview_dock, self.preview_3d_dock)' in default_layout
    assert 'self.tabifyDockWidget(self.preview_dock, self.canvas_dock)' in default_layout
    assert 'self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.canvas_dock)' in default_layout

    # Repair the invalid 0.19.0 state where Canvas Editor was checked in View
    # but had been removed from the actual dock tree.
    assert 'canvas_area == Qt.DockWidgetArea.NoDockWidgetArea' in main_window
    assert 'self.canvas_dock.toggleViewAction().isChecked()' in main_window

    print("canvas undo and default workspace regression passed")


if __name__ == "__main__":
    main()
