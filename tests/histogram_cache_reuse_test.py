from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parameters_path = ROOT / "vfx_texture_lab" / "ui" / "parameters.py"
    async_path = ROOT / "vfx_texture_lab" / "engine" / "async_eval.py"
    evaluator_path = ROOT / "vfx_texture_lab" / "engine" / "evaluator.py"
    material_path = ROOT / "vfx_texture_lab" / "three_d" / "evaluation.py"
    main_path = ROOT / "vfx_texture_lab" / "main_window.py"

    parameters = parameters_path.read_text()
    async_eval = async_path.read_text()
    evaluator = evaluator_path.read_text()
    material = material_path.read_text()
    main_window = main_path.read_text()

    for source in (parameters, async_eval, evaluator, material, main_window):
        ast.parse(source)

    # Histogram previews must evaluate the connected source at the graph's
    # existing preview resolution so an expensive upstream branch can hit its
    # completed cache. The old 512 px identity-node solve rebuilt that branch.
    assert "_histogram_source_reference" in parameters
    assert "source_uid" in parameters and "output_name=output_name" in parameters
    assert 'render_mode="histogram"' in parameters
    assert "width, height = document.preview_size()" in parameters
    assert "identity.update" not in parameters
    assert "_levels_histogram_completed_key" in parameters
    assert "_adjustment_histogram_completed_key" in parameters
    assert "_levels_histogram_cache" in parameters and "_adjustment_histogram_cache" in parameters
    assert "_histogram_interaction_started" in parameters
    assert "histogramActivityChanged" in parameters

    # The async controller forwards named outputs and the evaluator treats
    # histogram work as background priority.
    assert 'output_name: str = "Image"' in async_eval
    assert '"output_name": str(output_name or "Image")' in async_eval
    assert '{"preview_3d", "histogram", "thumbnail"}' in evaluator
    assert '("preview", "preview_3d", "histogram")' in evaluator

    # 3D maps now read connected sources directly instead of creating a
    # full-resolution synthetic Single Image Output cache entry per material channel.
    assert "__3d_sink__" not in material
    assert "3D Material Input" not in material
    assert "output_name=output_name" in material

    # Workspaces remain dockable but avoid Qt's native QPropertyAnimation crash
    # path and never save state while a mouse drag is active.
    assert "QMainWindow.DockOption.AnimatedDocks" not in main_window
    assert "self.setAnimated(False)" in main_window
    assert "QApplication.mouseButtons()" in main_window

    print("histogram cache reuse and dock safety source test passed")


if __name__ == "__main__":
    main()
