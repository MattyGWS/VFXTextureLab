from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# The production evaluator has no Qt dependency, but engine.__init__ exports the
# async controller. Tiny stubs keep this CPU-only regression runnable on build
# hosts without PySide6.
qtcore = types.ModuleType("PySide6.QtCore")
class QObject: pass
class QRunnable: pass
class QThreadPool:
    @staticmethod
    def globalInstance(): return QThreadPool()
class Signal:
    def __init__(self, *args): pass
    def connect(self, *args): pass
    def emit(self, *args): pass
qtcore.QObject = QObject; qtcore.QRunnable = QRunnable; qtcore.QThreadPool = QThreadPool; qtcore.Signal = Signal
pyside = types.ModuleType("PySide6"); pyside.QtCore = qtcore
sys.modules.setdefault("PySide6", pyside); sys.modules.setdefault("PySide6.QtCore", qtcore)

from vfx_texture_lab.engine.evaluator import GraphEvaluator, GraphSnapshot, SnapshotNode
from vfx_texture_lab.nodes.base import NodeDefinition

calls = {"source": 0, "invert": 0, "scale": 0}

def source(_inputs, params, context):
    calls["source"] += 1
    return np.full((context.height, context.width), float(params.get("value", .25)), np.float32)

def invert(inputs, _params, _context):
    calls["invert"] += 1
    return 1.0 - inputs["Image"]

def scale(inputs, params, _context):
    calls["scale"] += 1
    return inputs["Image"] * float(params.get("amount", 1.0))


def main() -> None:
    source_def = NodeDefinition("test.source", "Constant", "Test", source, output_format="r16f", output_kinds=(("Image", "grayscale"),), default_image_kind="grayscale")
    invert_def = NodeDefinition("test.invert", "Invert", "Test", invert, inputs=("Image",), output_format="r16f", input_kinds=(("Image", "grayscale"),), output_kinds=(("Image", "grayscale"),), default_image_kind="grayscale")
    scale_def = NodeDefinition("test.scale", "Scale", "Test", scale, inputs=("Image",), output_format="r16f", input_kinds=(("Image", "grayscale"),), output_kinds=(("Image", "grayscale"),), default_image_kind="grayscale")
    nodes = {
        "source": SnapshotNode("source", source_def, {"value": .25}, (), (), "grayscale"),
        "invert": SnapshotNode("invert", invert_def, {}, ("Image",), (), "grayscale"),
        "scale": SnapshotNode("scale", scale_def, {"amount": 1.0}, ("Image",), (), "grayscale"),
    }
    inputs = {("invert", "Image"): ("source", "Image"), ("scale", "Image"): ("invert", "Image")}
    evaluator = GraphEvaluator(backend_preference="cpu")
    first = evaluator.evaluate_snapshot(GraphSnapshot(nodes, inputs), "scale", 16, 16)
    assert first.error is None
    assert [trace.name for trace in first.node_traces[:3]] == ["Constant", "Invert", "Scale"]
    assert all(not trace.cache_hit for trace in first.node_traces[:3])
    second = evaluator.evaluate_snapshot(GraphSnapshot(nodes, inputs), "scale", 16, 16)
    assert all(trace.cache_hit for trace in second.node_traces[:3])
    changed = dict(nodes)
    changed["scale"] = SnapshotNode("scale", scale_def, {"amount": .5}, ("Image",), (), "grayscale")
    third = evaluator.evaluate_snapshot(GraphSnapshot(changed, inputs), "scale", 16, 16)
    by_name = {trace.name: trace for trace in third.node_traces}
    assert by_name["Constant"].cache_hit and by_name["Invert"].cache_hit
    assert not by_name["Scale"].cache_hit
    assert "parameters or upstream" in by_name["Scale"].details.lower()
    print("evaluation trace runtime test passed")

if __name__ == "__main__": main()
