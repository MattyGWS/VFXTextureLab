from __future__ import annotations

import json
import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

main = (ROOT / "vfx_texture_lab" / "main_window.py").read_text(encoding="utf-8")
view = (ROOT / "vfx_texture_lab" / "graph" / "view.py").read_text(encoding="utf-8")
entry = (ROOT / "vfx_texture_lab" / "__main__.py").read_text(encoding="utf-8")

# Blender-style startup graph behaviour.
assert '"Save Current Graph as Startup"' in main
assert '"Restore Built-in Startup Graph"' in main
assert 'self._startup_graph_path = self._app_data_root / "startup" / "default.vfxgraph"' in main
assert "def _save_current_as_startup_graph" in main
assert "def _load_custom_startup_graph" in main
assert "if self._startup_graph_path.is_file() and self._load_custom_startup_graph():" in main
assert 'data["_startup_template"]' in main

# Shift-drag snaps the dragged node top-left and preserves the selection layout.
assert "NODE_GRID_SIZE = 24.0" in view
assert "event.modifiers() & Qt.KeyboardModifier.ShiftModifier" in view
assert "def _snap_moving_nodes_to_grid" in view
assert "current = anchor.pos()" in view
assert "node.setPos(node.pos() + delta)" in view

# Theme selection is applied before the main window is constructed.
assert 'settings.value("appearance/theme", "midnight")' in entry
assert "set_active_theme(theme)" in entry
assert "app.setStyleSheet(build_stylesheet(theme))" in entry

from vfx_texture_lab.theme import (  # noqa: E402
    BUILTIN_THEMES,
    build_stylesheet,
    load_custom_themes,
    normalise_theme,
)

assert set(BUILTIN_THEMES) == {"midnight", "graphite", "daylight"}
for theme in BUILTIN_THEMES.values():
    stylesheet = build_stylesheet(theme)
    assert "QScrollBar:vertical" in stylesheet
    assert "QScrollBar::handle:vertical" in stylesheet
    assert theme["colors"]["accent"] in stylesheet
    assert theme["colors"]["scrollbar_handle"] in stylesheet

custom = normalise_theme({
    "id": "forest-night",
    "name": "Forest Night",
    "base": "graphite",
    "colors": {"accent": "#56b870", "scrollbar_handle": "#668877"},
})
assert custom["colors"]["accent"] == "#56b870"
assert custom["colors"]["window"] == BUILTIN_THEMES["graphite"]["colors"]["window"]

with tempfile.TemporaryDirectory() as temp:
    path = Path(temp) / "forest.json"
    path.write_text(json.dumps(custom), encoding="utf-8")
    loaded = load_custom_themes(Path(temp))
    assert "forest-night" in loaded
    assert loaded["forest-night"]["colors"]["scrollbar_handle"] == "#668877"

print("startup graph, grid snap and theme test passed")
