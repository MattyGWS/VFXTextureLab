from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QTimer
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.document import DocumentSettings
from vfx_texture_lab.engine import AsyncEvaluationController, GraphEvaluator, GraphSnapshot
from vfx_texture_lab.engine.cache import MemoryLRU
from vfx_texture_lab.graph.scene import GraphScene
from vfx_texture_lab.graph.view import GraphView
from vfx_texture_lab.main_window import MainWindow
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.preview_cache import CachedThumbnail
from vfx_texture_lab.ui.node_preferences import NodePreferences


class ThumbnailHarness:
    _thumbnail_preview_source = MainWindow._thumbnail_preview_source
    _thumbnail_request_key = MainWindow._thumbnail_request_key
    _visible_thumbnail_nodes = MainWindow._visible_thumbnail_nodes
    _dispatch_thumbnail_work = MainWindow._dispatch_thumbnail_work
    _thumbnail_ready = MainWindow._thumbnail_ready
    _thumbnail_failed = MainWindow._thumbnail_failed
    _schedule_thumbnail_refresh = MainWindow._schedule_thumbnail_refresh
    _animation_context = MainWindow._animation_context

    def __init__(self, scene: GraphScene, view: GraphView, app: QApplication) -> None:
        self.scene = scene
        self.graph_view = view
        self.document = DocumentSettings(width=512, height=512, preview_max_dimension=512)
        self.current_frame = 0
        self._active_graph_session_uid = "thumbnail-test"
        self.evaluator = GraphEvaluator(scene, backend_preference="cpu", gpu_budget_mb=64, cpu_budget_mb=64)
        self.thumbnail_controller = AsyncEvaluationController(self.evaluator)
        self.thumbnail_controller.resultReady.connect(self._thumbnail_ready)
        self.thumbnail_controller.evaluationFailed.connect(self._thumbnail_failed)
        self.thumbnail_timer = QTimer()
        self.thumbnail_timer.setSingleShot(True)
        self.thumbnail_timer.timeout.connect(self._dispatch_thumbnail_work)
        self._thumbnail_cache: MemoryLRU[CachedThumbnail] = MemoryLRU(4 * 1024 * 1024)
        self._thumbnail_in_flight = False
        self._thumbnail_current = None
        self._thumbnail_idle_delay_ms = 1
        self._thumbnail_animation_interval_ms = 200
        self._thumbnail_last_animation_schedule = 0.0
        self._playing = False
        self._preview_in_flight = False
        self._preview_pending = False
        self._material_preview_in_flight = False
        self._material_preview_pending = False
        self._playback_render_in_flight = False
        self._interactive_parameter_edit_depth = 0
        self.app = app


def spin_until(app: QApplication, predicate, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for thumbnail evaluation")


def main() -> None:
    app = QApplication.instance() or QApplication([])
    registry = build_registry()
    scene = GraphScene(registry)
    view = GraphView(scene, NodePreferences())
    view.resize(1000, 700)
    view.show()

    noise = scene.create_node("noise.perlin", QPointF(-100, -100), record_undo=False)
    original_height = noise.height
    assert noise.supports_thumbnail()
    assert not noise.thumbnail_enabled
    assert not noise.thumbnail_visible

    # With no expanded nodes, dispatching thumbnail work submits no evaluation.
    harness = ThumbnailHarness(scene, view, app)
    initial_request = harness.thumbnail_controller._request_id
    harness._dispatch_thumbnail_work()
    assert harness.thumbnail_controller._request_id == initial_request

    scene.toggle_node_thumbnail(noise)
    assert noise.thumbnail_enabled and noise.thumbnail_visible
    assert noise.height == original_height + 148.0
    assert noise.thumbnail_rect().width() == 128.0
    assert noise.thumbnail_rect().height() == 128.0

    # A visible opted-in node evaluates once at the fixed thumbnail resolution.
    view.centerOn(noise)
    app.processEvents()
    harness._dispatch_thumbnail_work()
    spin_until(app, lambda: noise.thumbnail_state == "ready")
    assert noise.thumbnail_image is not None
    assert noise.thumbnail_image.width() == 128
    assert noise.thumbnail_image.height() == 128
    assert harness._thumbnail_cache.stats().entries == 1

    # The same revision is reused without another worker request.
    completed_request = harness.thumbnail_controller._request_id
    harness._dispatch_thumbnail_work()
    app.processEvents()
    assert harness.thumbnail_controller._request_id == completed_request

    # Multi-output nodes store a stable selected thumbnail output.
    worley = scene.create_node("noise.worley", QPointF(180, -100), record_undo=False)
    scene.toggle_node_thumbnail(worley)
    scene.set_node_thumbnail_output(worley, "F2")
    assert worley.resolved_thumbnail_output() == "F2"

    # Playback never starts independent thumbnail work. The active node may be
    # refreshed from the ordinary playback presentation, while other expanded
    # nodes settle after pausing.
    request_before_playback = harness.thumbnail_controller._request_id
    harness._playing = True
    harness._dispatch_thumbnail_work()
    app.processEvents()
    assert harness.thumbnail_controller._request_id == request_before_playback
    harness._playing = False

    # Compact structural aliases intentionally remain compact.
    portal = scene.create_node("graph.send", QPointF(400, 200), record_undo=False)
    assert not portal.supports_thumbnail()

    payload = scene.to_dict()
    assert payload["version"] == 17
    saved_noise = next(entry for entry in payload["nodes"] if entry["uid"] == noise.uid)
    saved_worley = next(entry for entry in payload["nodes"] if entry["uid"] == worley.uid)
    assert saved_noise["thumbnail_enabled"] is True
    assert saved_worley["thumbnail_output"] == "F2"

    restored = GraphScene(registry)
    restored.from_dict(payload)
    restored_noise = restored.nodes[noise.uid]
    restored_worley = restored.nodes[worley.uid]
    assert restored_noise.thumbnail_enabled
    assert restored_worley.thumbnail_enabled
    assert restored_worley.resolved_thumbnail_output() == "F2"

    # Docking always collapses the visual preview without forgetting the opt-in.
    restored_noise.set_docked(restored_worley.uid, undocked_position=restored_noise.pos())
    assert restored_noise.thumbnail_enabled
    assert not restored_noise.thumbnail_visible
    assert restored_noise.height == restored_noise.DOCK_HEIGHT
    restored_noise.set_docked(None)
    assert restored_noise.thumbnail_visible

    # UI presentation accepts an exact RGBA8 thumbnail and retains a last valid
    # image while a newer result is marked stale.
    rgba = np.zeros((128, 128, 4), dtype=np.uint8)
    rgba[..., 0] = 255
    rgba[..., 3] = 255
    restored_noise.set_thumbnail_rgba(rgba, cache_key="red")
    assert restored_noise.thumbnail_state == "ready"
    restored_noise.clear_thumbnail_result(keep_image=True)
    assert restored_noise.thumbnail_image is not None
    assert restored_noise.thumbnail_state == "stale"

    print(
        "node thumbnail test passed: opt-in geometry, zero disabled requests, fixed 128px evaluation, "
        "cache reuse, output selection, persistence and dock suppression"
    )


if __name__ == "__main__":
    main()
