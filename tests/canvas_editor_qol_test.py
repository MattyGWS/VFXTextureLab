from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    canvas_editor = (ROOT / "vfx_texture_lab" / "ui" / "canvas_editor.py").read_text()
    main_window = (ROOT / "vfx_texture_lab" / "main_window.py").read_text()
    graph_scene = (ROOT / "vfx_texture_lab" / "graph" / "scene.py").read_text()
    input_nodes = (ROOT / "vfx_texture_lab" / "nodes" / "input_nodes.py").read_text()
    parameters = (ROOT / "vfx_texture_lab" / "ui" / "parameters.py").read_text()

    for source in (canvas_editor, main_window, graph_scene, input_nodes, parameters):
        ast.parse(source)

    # No selected Canvas node presents a dedicated empty page rather than a
    # disabled but paintable-looking editor.
    assert "self.pages = QStackedWidget(self)" in canvas_editor
    assert 'self.pages.setCurrentWidget(self.empty_page)' in canvas_editor
    assert 'QPushButton("Create Grayscale Canvas Node"' in canvas_editor
    assert "createCanvasRequested = Signal()" in canvas_editor
    assert 'self.graph_view.add_node_at_centre("input.canvas")' in main_window

    # Canvas tools are equal square buttons in a vertical strip beside the image.
    assert "self.tool_buttons: dict[str, QToolButton]" in canvas_editor
    assert "button.setFixedSize(38, 38)" in canvas_editor
    assert "tool_column.addWidget(button)" in canvas_editor
    assert "self.tool_combo" not in canvas_editor

    # Native size is selected from common power-of-two dimensions; legacy or
    # document-specific rectangular dimensions remain represented as Current.
    assert "CANVAS_SIZES = (256, 512, 1024, 2048, 4096, 8192)" in canvas_editor
    assert "self.size_combo = QComboBox" in canvas_editor
    assert 'self.size_combo.addItem(f"Current: {current[0]} × {current[1]}"' in canvas_editor
    assert "self.width_spin" not in canvas_editor
    assert "self.height_spin" not in canvas_editor

    # Every new Canvas node, including library/search creation, inherits the
    # current document dimensions from GraphScene.
    assert "self.canvas_default_size = (1024, 1024)" in graph_scene
    assert 'if "canvas_width" not in provided:' in graph_scene
    assert 'if "canvas_height" not in provided:' in graph_scene
    # Regression: Canvas creation without explicit parameters must initialise
    # `provided` before the Canvas-specific default-size branch uses it.
    assert graph_scene.index("provided = set(migrated_parameters)") < graph_scene.index('if type_id == "input.canvas":')
    assert "self.scene.canvas_default_size = (self.document.width, self.document.height)" in main_window

    # Canvas background is fixed black and the editable field/parameter is gone.
    assert "self.background_spin" not in canvas_editor
    assert 'self.node.parameters["background_value"] = 0.0' in canvas_editor
    assert "np.zeros((height, width), dtype=np.float32)" in canvas_editor
    canvas_definition = input_nodes[input_nodes.index('"input.canvas"'):input_nodes.index('"input.canvas"') + 1800]
    assert 'f("background_value"' not in canvas_definition
    assert "· background" not in parameters

    # View interaction matches the 2D output pattern: Fit reset, visible zoom
    # percentage, wheel zoom and middle-mouse panning.
    assert 'self.fit_button.setText("Fit")' in canvas_editor
    assert 'self.zoom_label = QLabel("100%"' in canvas_editor
    assert "def wheelEvent(self, event: QWheelEvent) -> None:" in canvas_editor
    assert "event.button() == Qt.MouseButton.MiddleButton" in canvas_editor
    assert 'self.zoom_label.setText(f"{max(float(zoom), 0.0) * 100.0:.0f}%")' in canvas_editor

    print("canvas editor QoL regression passed")


if __name__ == "__main__":
    main()
