from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _function_source(relative: str, function_name: str) -> str:
    source = _source(relative)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Missing {function_name} in {relative}")


def main() -> int:
    mime = _source("vfx_texture_lab/graph/mime.py")
    assert "GRAPH_RESOURCE_MIME_TYPE" in mime

    explorer_drag = _function_source("vfx_texture_lab/ui/graph_explorer.py", "startDrag")
    assert "GRAPH_RESOURCE_MIME_TYPE" in explorer_drag
    assert '"graph_uid"' in explorer_drag and '"resource_uid"' in explorer_drag
    assert 'kind == "resource"' in explorer_drag

    view = _source("vfx_texture_lab/graph/view.py")
    assert 'MESH_SUFFIXES = {".obj"}' in view
    assert "graphResourceDropRequested = Signal(str, str, object)" in view
    assert "_first_dropped_mesh" in view
    assert '"input.mesh"' in _function_source("vfx_texture_lab/graph/view.py", "dropEvent")
    assert "graphResourceDropRequested.emit" in _function_source(
        "vfx_texture_lab/graph/view.py", "dropEvent"
    )
    create_node_internal = _function_source(
        "vfx_texture_lab/graph/scene.py", "_create_node_internal"
    )
    assert "refresh_mesh_metadata(effective_parameters)" in create_node_internal

    main_window = _source("vfx_texture_lab/main_window.py")
    assert "graphResourceDropRequested.connect(self._insert_graph_resource)" in main_window
    resource_insert = _function_source("vfx_texture_lab/main_window.py", "_insert_graph_resource")
    assert "copy_resource_from" in resource_insert
    assert "parameters_for_resource" in resource_insert
    assert '"input.mesh"' in resource_insert and '"input.image"' in resource_insert

    print(
        "resource drag/drop contract test passed: Explorer resource MIME, canvas resource dispatch, "
        "safe cross-graph copy and direct OBJ Mesh Input creation are wired"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
