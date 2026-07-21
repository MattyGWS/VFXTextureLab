from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    inspector = (ROOT / "vfx_texture_lab/ui/evaluation_inspector.py").read_text()
    main_window = (ROOT / "vfx_texture_lab/main_window.py").read_text()
    scene = (ROOT / "vfx_texture_lab/graph/scene.py").read_text()
    items = (ROOT / "vfx_texture_lab/graph/items.py").read_text()
    evaluator = (ROOT / "vfx_texture_lab/engine/evaluator.py").read_text()

    assert "class EvaluationInspector" in inspector
    assert "Node / Stage" in inspector and "Backend" in inspector and "Cache" in inspector
    assert "begin_job" in inspector and "finish_job" in inspector and "update_node" in inspector
    assert "set_background_activity" in inspector and "Background:" in inspector
    assert 'QDockWidget("Evaluation Inspector"' in main_window
    assert "splitDockWidget(self.timeline_dock, self.evaluation_dock" in main_window
    assert "nodeRequested.connect(self._focus_inspector_node)" in main_window
    assert "class NodeEvaluationTrace" in evaluator
    assert "node_traces=tuple(node_traces)" in evaluator
    assert "finalise / readback" in evaluator
    assert "set_evaluation_flow" in items
    assert "setDashOffset" in items
    assert "_wire_flow_timer" in scene and "_refresh_wire_flow" in scene
    print("evaluation inspector source test passed")


if __name__ == "__main__":
    main()
