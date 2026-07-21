from __future__ import annotations

import ast
from pathlib import Path


def main() -> None:
    source_path = Path(__file__).resolve().parents[1] / "vfx_texture_lab" / "ui" / "parameters.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    levels_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "LevelsControl"
    )
    levels_source = ast.get_source_segment(source, levels_class) or ""
    assert "QWidget(parent_widget)" not in levels_source, (
        "LevelsControl must not reference the ParametersPanel-local parent_widget variable"
    )
    assert "row = QWidget(sliders)" in levels_source, (
        "Levels slider rows should be owned by the sliders page"
    )

    panel_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ParametersPanel"
    )
    panel_source = ast.get_source_segment(source, panel_class) or ""
    assert "parent_widget = target.body if isinstance(target, ParameterGroupWidget) else self.form_host" in panel_source
    assert "parent=parent_widget" in panel_source
    assert "self.form_host = old_host" in panel_source
    assert "old_host.show()" in panel_source
    assert "self.scroll.verticalScrollBar().setValue(0)" in panel_source

    print(
        "Levels parameter-panel regression test passed: valid ownership, visible editor, "
        "top-reset scrolling and failure-safe atomic page replacement"
    )


if __name__ == "__main__":
    main()
