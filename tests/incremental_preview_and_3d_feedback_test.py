from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from vfx_texture_lab.engine.evaluator import GraphEvaluator, GraphSnapshot, SnapshotNode
from vfx_texture_lab.engine.formats import TextureFormat
from vfx_texture_lab.main_window import MainWindow
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import NodeDefinition
from vfx_texture_lab.three_d.evaluation import _MaterialWorker


def main() -> None:
    app = QApplication.instance() or QApplication([])
    registry = build_registry()
    calls = {"source": 0}

    def source_eval(_inputs, _parameters, context):
        calls["source"] += 1
        y, x = np.mgrid[0:context.height, 0:context.width]
        return ((x + y) / max(context.width + context.height - 2, 1)).astype(np.float32)

    source_def = NodeDefinition(
        "test.cached_source", "Cached Source", "Test", source_eval,
        output_format="r16f",
        output_kinds=(("Image", "grayscale"),),
        default_image_kind="grayscale",
    )
    levels_def = registry.get("filter.levels")
    image_out_def = registry.get("output.image")
    material_def = registry.get("material.pbr")

    source = SnapshotNode("source", source_def, {}, (), (), "grayscale")
    levels_params = levels_def.default_parameters()
    levels = SnapshotNode("levels", levels_def, levels_params, tuple(levels_def.inputs), (), "grayscale")
    image_out = SnapshotNode(
        "image_out", image_out_def, image_out_def.default_parameters(),
        tuple(image_out_def.inputs), (), "grayscale",
    )
    material_params = material_def.default_parameters()
    material = SnapshotNode(
        "material", material_def, material_params,
        tuple(material_def.inputs), (), "grayscale",
    )
    unrelated = SnapshotNode(
        "unrelated", source_def, {"unrelated": True}, (), (), "grayscale",
    )
    inputs = {
        ("levels", "Image"): ("source", "Image"),
        ("image_out", "Image"): ("levels", "Image"),
        ("material", "Height"): ("levels", "Image"),
    }
    snapshot = GraphSnapshot(
        {"source": source, "levels": levels, "image_out": image_out, "material": material},
        inputs,
    )
    evaluator = GraphEvaluator(backend_preference="cpu")

    first = evaluator.evaluate_snapshot(snapshot, "image_out", 64, 64)
    assert first.error is None
    assert calls["source"] == 1

    changed_params = dict(levels_params)
    changed_params["in_low"] = 0.2
    changed_levels = SnapshotNode(
        "levels", levels_def, changed_params, tuple(levels_def.inputs), (), "grayscale"
    )
    changed_snapshot = GraphSnapshot(
        {"source": source, "levels": changed_levels, "image_out": image_out, "material": material},
        inputs,
    )
    drag = evaluator.evaluate_snapshot(
        changed_snapshot,
        "image_out",
        64,
        64,
        render_mode="interactive",
        interactive_node_uid="levels",
    )
    assert drag.error is None
    assert calls["source"] == 1, "a downstream Levels drag recomputed its unchanged upstream source"

    second = evaluator.evaluate_snapshot(changed_snapshot, "image_out", 64, 64)
    assert second.error is None
    assert calls["source"] == 1, "a downstream Levels release recomputed its unchanged upstream source"

    # Match the reported terrain graph shape exactly: a named erosion output
    # feeding Levels must stay cached while Levels itself is dragged.
    constant_def = registry.get("generator.constant")
    thermal_def = registry.get("terrain.thermal_erosion")
    terrain_levels_params = levels_def.default_parameters()
    thermal_params = thermal_def.default_parameters()
    thermal_params.update({"preview_iterations": 2, "final_iterations": 2, "quality": "Automatic"})
    terrain_nodes = {
        "constant": SnapshotNode(
            "constant", constant_def, constant_def.default_parameters(),
            tuple(constant_def.inputs), (), "grayscale",
        ),
        "thermal": SnapshotNode(
            "thermal", thermal_def, thermal_params,
            tuple(thermal_def.inputs), (), "grayscale",
        ),
        "terrain_levels": SnapshotNode(
            "terrain_levels", levels_def, terrain_levels_params,
            tuple(levels_def.inputs), (), "grayscale",
        ),
        "terrain_out": SnapshotNode(
            "terrain_out", image_out_def, image_out_def.default_parameters(),
            tuple(image_out_def.inputs), (), "grayscale",
        ),
    }
    terrain_inputs = {
        ("thermal", "Height"): ("constant", "Image"),
        ("terrain_levels", "Image"): ("thermal", "Eroded Height"),
        ("terrain_out", "Image"): ("terrain_levels", "Image"),
    }
    terrain_snapshot = GraphSnapshot(terrain_nodes, terrain_inputs)
    terrain_evaluator = GraphEvaluator(backend_preference="cpu")
    initial_terrain = terrain_evaluator.evaluate_snapshot(terrain_snapshot, "terrain_out", 16, 16)
    assert initial_terrain.error is None
    changed_terrain_nodes = dict(terrain_nodes)
    changed_terrain_params = dict(terrain_levels_params)
    changed_terrain_params["in_low"] = 0.15
    changed_terrain_nodes["terrain_levels"] = SnapshotNode(
        "terrain_levels", levels_def, changed_terrain_params,
        tuple(levels_def.inputs), (), "grayscale",
    )
    terrain_events = []
    dragged_terrain = terrain_evaluator.evaluate_snapshot(
        GraphSnapshot(changed_terrain_nodes, terrain_inputs),
        "terrain_out",
        16,
        16,
        render_mode="interactive",
        interactive_node_uid="terrain_levels",
        node_activity_callback=lambda *event: terrain_events.append(event),
    )
    assert dragged_terrain.error is None
    assert not any(event[0].startswith("thermal") and event[1] for event in terrain_events), terrain_events

    # Branch revisions ignore unrelated graph content but change for edits in
    # the connected material branch.
    revision = evaluator.branch_revision(snapshot, "material")
    with_unrelated = GraphSnapshot({**snapshot.nodes, "unrelated": unrelated}, dict(inputs))
    assert evaluator.branch_revision(with_unrelated, "material") == revision
    assert evaluator.branch_revision(changed_snapshot, "material") != revision

    # The 3D worker evaluates at the shared graph-preview resolution, reuses the
    # warmed branch cache, and downsamples only the final material map.
    worker = _MaterialWorker(
        1,
        evaluator,
        changed_snapshot,
        "material",
        64,
        64,
        32,
        32,
        TextureFormat.RGBA16F,
        "Linear",
        {"frame_number": 0, "time_seconds": 0.0},
        threading.Event(),
    )
    results = []
    node_events = []
    progress_events = []
    failures = []
    worker.signals.finished.connect(lambda _request, result: results.append(result))
    worker.signals.failed.connect(lambda _request, message: failures.append(message))
    worker.signals.nodeState.connect(lambda *event: node_events.append(event))
    worker.signals.progress.connect(lambda *event: progress_events.append(event))
    worker.run()
    app.processEvents()
    assert results, failures
    material_result = results[-1]
    assert (material_result.evaluation_width, material_result.evaluation_height) == (64, 64)
    assert (material_result.width, material_result.height) == (32, 32)
    assert material_result.textures["Height"].shape[:2] == (32, 32)
    assert calls["source"] == 1, "3D preview recomputed an already-cached upstream branch"
    assert any(event[1] == "material" and event[2] for event in node_events), node_events
    assert progress_events and progress_events[-1][1:3] == (1, 1)

    # Explicitly switching the 2D preview cancels the stale locked render. Material focus drives the complete 3D preview and routes its Base Colour branch through the ordinary 2D preview scheduler.
    class Timer:
        def __init__(self): self.stopped = 0
        def stop(self): self.stopped += 1

    class Controller:
        def __init__(self): self.cancels = 0
        def cancel(self): self.cancels += 1

    class Scene:
        def __init__(self): self.clears = 0
        def clear_node_evaluation_states(self): self.clears += 1

    class Panel:
        def __init__(self): self.busy = ""; self.notice = None; self.result = None; self.active = False
        def set_busy(self, _busy, message=None): self.busy = message
        def show_notice(self, title, message): self.notice = (title, message)
        def set_result(self, *args): self.result = args
        def set_active_output(self, active, name=None): self.active = bool(active)
        def adopt_legacy_output_settings(self, _parameters): return False
        def clear_geometry_override(self): pass

    class Harness:
        MATERIAL_NODE_TYPE = "material.pbr"
        TEXTURE_SET_NODE_TYPE = "output.texture_set"
        _active_node_changed = MainWindow._active_node_changed
        _is_material_preview_node = MainWindow._is_material_preview_node
        def _is_geometry_preview_node(self, _node): return False
        _resolve_material_node = MainWindow._resolve_material_node
        def __init__(self):
            self.preview_timer = Timer()
            self.eval_controller = Controller()
            self.scene = Scene()
            self.preview_panel = Panel()
            self.preview_3d_panel = Panel()
            self.document = SimpleNamespace(working_precision="16-bit float")
            self._legacy_3d_viewport_nodes = set()
            self._material_preview_pending = False
            self._playing = False
            self._preview_node_activity = {}
            self._preview_in_flight = True
            self._preview_pending = False
            self._playback_preview_pending = True
            self.armed = []
            self.material_schedules = []
        def _invalidate_flipbook_decode_cache(self): pass
        def _sync_preview_gizmo(self, _node=None): pass
        def _preempt_material_preview_for_2d(self, _reason=""): pass
        def _arm_preview_dispatch(self, *, force_immediate=False): self.armed.append(force_immediate)
        def _schedule_3d_preview(self, *, immediate=False): self.material_schedules.append(immediate)
        def _refresh_material_geometry_override(self, _node): pass

    harness = Harness()
    levels_item = SimpleNamespace(uid="levels", parameters={}, definition=SimpleNamespace(type_id="filter.levels", name="Levels"))
    harness._active_node_changed(levels_item)
    assert harness.eval_controller.cancels == 1
    assert harness._preview_pending and harness.armed == [True]

    harness._preview_in_flight = True
    material_item = SimpleNamespace(uid="material", parameters={"name": "Material Test"}, definition=SimpleNamespace(type_id="material.pbr", name="Material"))
    harness._active_node_changed(material_item)
    assert harness._preview_pending
    assert harness.armed[-1] is True
    assert harness.material_schedules[-1] is True
    assert harness.preview_panel.busy and "base colour" in harness.preview_panel.busy.lower()
    assert harness.preview_3d_panel.active

    print(
        "incremental preview and 3D feedback test passed: downstream-only edits preserve upstream caches, "
        "3D maps reuse the graph-resolution cache before downsampling, material activity is surfaced, "
        "and active 2D preview switches preempt stale work"
    )
    app.quit()


if __name__ == "__main__":
    main()
