from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from types import MethodType

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.engine.cache import MemoryLRU
from vfx_texture_lab.engine.evaluator import GraphEvaluator, GraphSnapshot
from vfx_texture_lab.engine.formats import TextureFormat
from vfx_texture_lab.graph import GraphScene
from vfx_texture_lab.main_window import MainWindow
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.three_d.evaluation import _MaterialWorker
from vfx_texture_lab.three_d.renderer import ThreeDRenderer, _MaterialTextureSet


class FakeHandle:
    def __init__(self, width: int, height: int, mip_count: int = 1) -> None:
        self.width = width
        self.height = height
        self.mip_count = mip_count
        self.released = False

    def release(self) -> None:
        self.released = True


def connect(scene, source, output, target, input_name):
    assert scene.add_connection(
        source.output_ports[output], target.input_ports[input_name], record_undo=False
    ) is not None


def main() -> None:
    app = QApplication.instance() or QApplication([])
    del app

    # Uniform material generators remain compact 1x1 textures in the 3D bridge.
    # Missing channels stay implicit and are supplied by 1x1 renderer defaults.
    scene = GraphScene(build_registry())
    colour = scene.create_node("generator.color", QPointF(), parameters={"color": "#a04020ff"}, record_undo=False)
    height = scene.create_node("generator.constant", QPointF(), parameters={"value": 0.42}, record_undo=False)
    roughness = scene.create_node("generator.constant", QPointF(), parameters={"value": 0.71}, record_undo=False)
    material = scene.create_node("material.pbr", QPointF(), record_undo=False)
    connect(scene, colour, "Image", material, "Base Colour")
    connect(scene, height, "Image", material, "Height")
    connect(scene, roughness, "Image", material, "Roughness")
    evaluator = GraphEvaluator(scene, backend_preference="cpu")
    worker = _MaterialWorker(
        1, evaluator, GraphSnapshot.from_scene(scene), material.uid,
        64, 64, 64, 64, TextureFormat.RGBA16F, "Linear", {}, threading.Event(),
    )
    results = []
    errors = []
    worker.signals.finished.connect(lambda _request, result: results.append(result))
    worker.signals.failed.connect(lambda _request, message: errors.append(message))
    worker.run()
    assert results and not errors, errors
    result = results[-1]
    assert set(result.textures) == {"Base Colour", "Height", "Roughness"}, set(result.textures)
    assert result.connected == frozenset(result.textures)
    assert all(image.shape == (1, 1, 4) for image in result.textures.values())
    assert sum(image.nbytes for image in result.textures.values()) == 1 * 1 * 4 * 4 * 3
    assert result.static_cache_hits == 0
    assert not result.dynamic_channels

    # Renderer texture sets are keyed by material revision. The first activation
    # uploads all authored/default bindings; revisiting the same key performs no
    # upload and simply swaps the cached texture views back in.
    renderer = object.__new__(ThreeDRenderer)
    renderer.available = True
    renderer._lock = threading.RLock()
    renderer._textures = {}
    renderer._active_material_cache_key = None
    renderer._active_channel_tokens = {}
    renderer._material_texture_cache = MemoryLRU(32 * 1024 * 1024)
    renderer.connected = frozenset()
    renderer.material_settings = {}
    renderer.viewport_settings = {}
    renderer.settings = {}
    renderer._bind_group = None
    renderer._bind_group_pipeline = None
    renderer._shadow_bind_groups = {}
    uploads = []

    def fake_upload(self, name, array, texture_store=None, *, generate_mips=True):
        del generate_mips
        store = self._textures if texture_store is None else texture_store
        uploads.append(name)
        h, w = np.asarray(array).shape[:2]
        store[name] = FakeHandle(w, h, 1)

    renderer._upload_texture = MethodType(fake_upload, renderer)
    renderer._ensure_mesh = MethodType(lambda self: None, renderer)
    renderer.request_draw = MethodType(lambda self: None, renderer)

    reused = renderer.update_material(
        result.textures, result.connected, result.settings,
        cache_key="material-revision-a", channel_tokens=result.channel_tokens,
    )
    assert reused is False
    first_upload_count = len(uploads)
    assert first_upload_count == 9, first_upload_count
    assert renderer.material_cache_stats().entries == 1

    uploads.clear()
    reused = renderer.update_material(
        {}, result.connected, result.settings,
        cache_key="material-revision-a", channel_tokens=result.channel_tokens,
    )
    assert reused is True
    assert not uploads, uploads

    # Live playback detaches the active cached set and updates only channels
    # whose content tokens changed. Static roughness/height maps stay resident.
    uploads.clear()
    live_tokens = dict(result.channel_tokens)
    live_tokens["Base Colour"] = "dynamic:base:frame-1"
    reused = renderer.update_material(
        {"Base Colour": np.ones((64, 64, 4), dtype=np.float32)},
        result.connected, result.settings, channel_tokens=live_tokens, incremental=True,
    )
    assert reused is False
    assert uploads == ["Base Colour"], uploads
    uploads.clear()
    live_tokens["Base Colour"] = "dynamic:base:frame-2"
    renderer.update_material(
        {"Base Colour": np.zeros((64, 64, 4), dtype=np.float32)},
        result.connected, result.settings, channel_tokens=live_tokens, incremental=True,
    )
    assert uploads == ["Base Colour"], uploads

    # Re-enter static inspection after playback and confirm a fresh keyed set is
    # protected when a smaller budget is chosen.
    renderer.update_material(
        result.textures, result.connected, result.settings,
        cache_key="material-revision-b", channel_tokens=result.channel_tokens,
    )
    active = renderer._material_texture_cache.get("material-revision-b")
    assert isinstance(active, _MaterialTextureSet)
    renderer.set_material_cache_budget_mb(1)
    assert renderer.activate_cached_material("material-revision-b", result.connected, result.settings)

    renderer._material_texture_cache.clear()

    # End-to-end focus behaviour: the second 2D request must not submit an
    # evaluator job, and returning to an already-rendered Material must not
    # submit a material worker or renderer upload.
    window = MainWindow()
    window.resize(900, 700)
    window.show()
    QApplication.processEvents()
    window.preview_timer.stop()
    window.material_preview_timer.stop()
    window.eval_controller.cancel()
    window.material_controller.cancel()
    window.scene.clear_graph(record_undo=False)
    window.document.width = window.document.height = 64
    window.document.preview_max_dimension = 64

    focus_colour = window.scene.create_node(
        "generator.color", QPointF(), parameters={"color": "#4080c0ff"}, record_undo=False
    )
    focus_material = window.scene.create_node("material.pbr", QPointF(), record_undo=False)
    connect(window.scene, focus_colour, "Image", focus_material, "Base Colour")

    window.scene.set_active_node(focus_colour)
    window.preview_timer.stop()
    window.material_preview_timer.stop()
    window._preview_pending = False
    window._preview_in_flight = False
    window._evaluate_active()
    deadline = time.time() + 10.0
    while window._preview_in_flight and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    QApplication.processEvents()
    assert window._preview_result_cache.stats().entries >= 1
    original_preview_request = window.eval_controller.request
    preview_requests = []
    window.eval_controller.request = lambda *args, **kwargs: preview_requests.append((args, kwargs))
    window._evaluate_active()
    QApplication.processEvents()
    assert not preview_requests, "unchanged 2D focus submitted a new evaluator job"
    window.eval_controller.request = original_preview_request

    window.scene.set_active_node(focus_material)
    window.preview_timer.stop()
    window.material_preview_timer.stop()
    window.eval_controller.cancel()
    window.material_controller.cancel()
    window._preview_pending = False
    window._preview_in_flight = False
    window._material_preview_pending = False
    window._material_preview_in_flight = False
    window._request_3d_preview()
    deadline = time.time() + 15.0
    while window._material_preview_in_flight and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    QApplication.processEvents()
    material_key = window._current_material_request_key()
    assert material_key and material_key == window._last_material_result_key
    assert window.preview_3d_panel.material_cache_stats().entries >= 1
    original_material_request = window.material_controller.request
    material_requests = []
    window.material_controller.request = lambda *args, **kwargs: material_requests.append((args, kwargs))
    window._last_material_result_key = "force-cache-lookup"
    window._request_3d_preview()
    QApplication.processEvents()
    assert not material_requests, "unchanged Material focus submitted a new material worker"
    assert window._last_material_result_key == material_key
    window.material_controller.request = original_material_request

    window._document_dirty = False
    window._recovered_dirty = False
    window.scene.undo_stack.setClean()
    window._set_dirty(False)
    window.close()
    QApplication.processEvents()

    print(
        "presentation cache performance test passed: uniform maps remain 1x1, absent maps remain implicit, "
        "static renderer channels stay resident during incremental playback, cached sets reuse without upload, "
        "and active sets survive budget changes"
    )


if __name__ == "__main__":
    main()
