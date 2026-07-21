from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
main = (ROOT / "vfx_texture_lab/main_window.py").read_text()
view = (ROOT / "vfx_texture_lab/graph/view.py").read_text()
items = (ROOT / "vfx_texture_lab/graph/items.py").read_text()
preview = (ROOT / "vfx_texture_lab/ui/preview.py").read_text()
timeline = (ROOT / "vfx_texture_lab/ui/timeline.py").read_text()

# 2D status must never resize the viewport while evaluation messages change.
assert "self.info.setWordWrap(False)" in preview
assert "self.info.setFixedHeight" in preview
assert "Qt.TextElideMode.ElideRight" in preview
assert "self._info_full_text" in preview

# Wire snapping uses a screen-space radius, compatibility filtering and an
# ambiguity guard for adjacent sockets.
assert "PORT_SNAP_RADIUS_PX = 32.0" in view
assert "PORT_SNAP_AMBIGUITY_PX = 5.0" in view
assert "def _nearest_compatible_port" in view
assert "self.graph_scene.can_connect(start, item)" in view
assert "second_distance - best_distance" in view
assert "target.set_snap_target(True)" in view
assert "self._snap_hover_port" in view
assert "def set_snap_target" in items
assert 'theme_colour("progress", "#ff9d36")' in items

# Graph file dialogs remember the last location and populate useful shortcuts.
assert 'files/last_graph_directory' in main
assert 'files/recent_graph_directories' in main
assert "dialog.setSidebarUrls" in main
assert "dialog.setHistory" in main
assert "QStandardPaths.StandardLocation.DocumentsLocation" in main
assert "QStandardPaths.StandardLocation.DownloadLocation" in main

# The main toolbar is intentionally not a duplicate File/Edit toolbar.
toolbar = main[main.index("    def _build_toolbar"):main.index("    def _connect_signals")]
assert "toolbar.addAction(self.document_settings_action)" in toolbar
assert "self.new_action" not in toolbar
assert "self.open_action" not in toolbar
assert "self.save_action" not in toolbar
assert "self.undo_action" not in toolbar
assert "self.redo_action" not in toolbar

# Standard transport icons distinguish frame stepping from playback.
for icon in (
    "SP_MediaSkipBackward",
    "SP_MediaSeekBackward",
    "SP_MediaPlay",
    "SP_MediaPause",
    "SP_MediaStop",
    "SP_MediaSeekForward",
    "SP_MediaSkipForward",
):
    assert icon in timeline
assert 'setToolTip("Previous frame")' in timeline
assert 'setToolTip("Next frame")' in timeline

print("editor QoL source test passed")
