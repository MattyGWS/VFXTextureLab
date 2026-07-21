from __future__ import annotations

import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.engine.evaluator import GraphEvaluator
from vfx_texture_lab.graph.scene import GraphScene
from vfx_texture_lab.nodes.registry import build_registry


def main() -> None:
    app = QApplication.instance() or QApplication([])
    registry = build_registry()
    scene = GraphScene(registry)

    colour = scene.create_node("generator.color", QPointF(0, 0), record_undo=False)
    colour.parameters["color"] = "#204080c0"
    split = scene.create_node("convert.extract_channel", QPointF(250, 0), record_undo=False)
    output = scene.create_node("output.image", QPointF(500, 0), record_undo=False)
    scene.add_connection(colour.output_port, split.input_ports["Image"], record_undo=False)
    expected = {"R": 0x20 / 255, "G": 0x40 / 255, "B": 0x80 / 255, "A": 0xC0 / 255}
    for name, value in expected.items():
        for connection in list(scene.connections):
            if connection.target_node is output:
                scene.remove_connection(connection, record_undo=False)
        scene.add_connection(split.output_ports[name], output.input_ports["Image"], record_undo=False)
        result = GraphEvaluator(scene, backend_preference="cpu").evaluate(output.uid, 8, 8)
        assert result.error is None, result.error
        assert abs(float(result.image[0, 0, 0]) - value) < 1e-5

    gradient = registry.get("convert.gradient_map")
    defaults = gradient.default_parameters()["stops"]
    assert len(defaults) >= 2
    blend = registry.get("math.blend")
    assert blend.inputs == ("Foreground", "Background", "Opacity")
    assert registry.get("input.image").category == "Inputs & Outputs"
    assert registry.get("output.image").category == "Inputs & Outputs"
    assert registry.get("generator.constant").accent == registry.get("generator.color").accent
    assert registry.contains("filter.auto_levels")

    data = scene.to_dict()
    restored = GraphScene(registry)
    restored.from_dict(data)
    assert any(connection.output_name == "A" for connection in restored.connections)
    print("Node improvements test passed: multi-output channels, gradient stops, Auto Levels, opacity masks, consistent categories and serialization")


if __name__ == "__main__":
    main()
