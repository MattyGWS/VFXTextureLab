from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PARAMETERS = ROOT / "vfx_texture_lab" / "ui" / "parameters.py"


def test_manual_parameter_edits_update_summary_without_rebuilding_controls() -> None:
    source = PARAMETERS.read_text(encoding="utf-8")
    changed_start = source.index("    def _node_parameter_changed(")
    changed_end = source.index("\n    def ", changed_start + 8)
    changed_method = source[changed_start:changed_end]

    assert "self._refresh_manual_execution_summary(node)" in changed_method
    assert "or manual_relevant" not in changed_method
    assert "changes_parameter_layout or changes_resolved_type or refreshes_mesh_source" in changed_method


def test_same_node_refreshes_preserve_scroll_and_defer_during_drag() -> None:
    source = PARAMETERS.read_text(encoding="utf-8")
    set_item_start = source.index("    def set_item(")
    set_item_end = source.index("\n    def ", set_item_start + 8)
    set_item_method = source[set_item_start:set_item_end]

    assert "same_item and self._interactive_parameter_depth > 0" in set_item_method
    assert "self._deferred_same_item_refresh = True" in set_item_method
    assert "preserved_scroll = self.scroll.verticalScrollBar().value() if same_item else 0" in set_item_method
    assert "min(int(value), self.scroll.verticalScrollBar().maximum())" in set_item_method
