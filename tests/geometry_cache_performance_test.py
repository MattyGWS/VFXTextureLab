from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from types import MethodType, SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.engine.cache import MemoryLRU
from vfx_texture_lab.engine.evaluator import GraphSnapshot
from vfx_texture_lab.main_window import MainWindow
from vfx_texture_lab.three_d.meshes import MeshData
from vfx_texture_lab.three_d.renderer import ThreeDRenderer
import vfx_texture_lab.three_d.renderer as renderer_module


def connect(scene, source, output, target, input_name):
    assert scene.add_connection(
        source.output_ports[output], target.input_ports[input_name], record_undo=False
    ) is not None


class _FakeBuffer:
    def __init__(self, label: str) -> None:
        self.label = label
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True


class _FakeDevice:
    def __init__(self) -> None:
        self.uploads: list[str] = []

    def create_buffer_with_data(self, **kwargs):
        self.uploads.append(str(kwargs.get("label", "buffer")))
        return _FakeBuffer(self.uploads[-1])


def _renderer_cache_fixture() -> None:
    original_wgpu = renderer_module.wgpu
    renderer_module.wgpu = SimpleNamespace(BufferUsage=SimpleNamespace(VERTEX=1, INDEX=2))
    try:
        renderer = object.__new__(ThreeDRenderer)
        renderer.available = True
        renderer.device = _FakeDevice()
        renderer._lock = threading.RLock()
        renderer._geometry_override = None
        renderer._geometry_inspection = False
        renderer._geometry_override_token = 0
        renderer._mesh_key = None
        renderer._mesh = None
        renderer._vertex_buffer = None
        renderer._index_buffer = None
        renderer._wire_mesh_key = None
        renderer._wire_index_buffer = None
        renderer._wire_index_count = 0
        renderer._pivot_mesh_key = None
        renderer._pivot_vertex_buffer = None
        renderer._pivot_vertex_count = 0
        renderer._geometry_buffer_cache = MemoryLRU(16 * 1024 * 1024)
        renderer._active_geometry_cache_key = None
        renderer.settings = {}
        renderer.request_draw = MethodType(lambda self: None, renderer)

        vertices = np.zeros((3, 8), dtype=np.float32)
        indices = np.asarray((0, 1, 2), dtype=np.uint32)
        first = MeshData(vertices, indices, "Dense A", "geometry-cache-a")
        same_result_new_wrapper = MeshData(
            vertices.copy(), indices.copy(), "Dense A wrapper", "geometry-cache-a"
        )
        second = MeshData(vertices, indices, "Dense B", "geometry-cache-b")

        renderer.set_geometry_override(first)
        assert len(renderer.device.uploads) == 2
        renderer.set_geometry_override(same_result_new_wrapper)
        assert len(renderer.device.uploads) == 2, "stable geometry identity re-uploaded buffers"
        renderer.set_geometry_override(second)
        assert len(renderer.device.uploads) == 4
        renderer.set_geometry_override(first)
        assert len(renderer.device.uploads) == 4, "resident mesh buffers were uploaded twice"
        assert renderer.geometry_cache_stats().hits >= 1
    finally:
        renderer_module.wgpu = original_wgpu


def main() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.preview_timer.stop()
    window.material_preview_timer.stop()
    window.eval_controller.cancel()
    window.material_controller.cancel()
    window.scene.clear_graph(record_undo=False)
    window.document.width = window.document.height = 128
    window.document.preview_max_dimension = 128
    window._geometry_result_cache.clear()

    plane = window.scene.create_node(
        "geometry.plane",
        QPointF(),
        parameters={"subdivisions_x": 16, "subdivisions_y": 16},
        record_undo=False,
    )
    subdivide = window.scene.create_node(
        "geometry.subdivide", QPointF(), parameters={"levels": 2}, record_undo=False
    )
    material = window.scene.create_node("material.pbr", QPointF(), record_undo=False)
    connect(window.scene, plane, "Geometry", subdivide, "Geometry")
    connect(window.scene, subdivide, "Geometry", material, "Geometry")

    real_factory = window._geometry_evaluation_session
    evaluations = []

    def counted_factory(snapshot, *, final=False):
        session = real_factory(snapshot, final=final)
        real_evaluate = session.evaluate

        def counted_evaluate(uid, output_name="Geometry"):
            evaluations.append((uid, output_name))
            return real_evaluate(uid, output_name)

        session.evaluate = counted_evaluate
        return session

    window._geometry_evaluation_session = counted_factory

    first_snapshot = GraphSnapshot.from_scene(window.scene)
    first_mesh, first_revision, first_error = window._material_geometry_state(
        material, first_snapshot
    )
    assert first_mesh is not None and first_error is None
    assert len(evaluations) == 1

    # An unrelated Material edit changes the overall graph but not the geometry
    # branch. It must return the exact same MeshData object without running the
    # expensive Subdivide evaluator again.
    material.parameters["emissive_intensity"] = 3.5
    second_snapshot = GraphSnapshot.from_scene(window.scene)
    second_mesh, second_revision, second_error = window._material_geometry_state(
        material, second_snapshot
    )
    assert second_error is None
    assert second_mesh is first_mesh
    assert second_revision == first_revision
    assert len(evaluations) == 1, "unrelated Material edit reevaluated Geometry Subdivide"

    # A real geometry edit must invalidate exactly that branch and produce a new
    # stable mesh/cache identity.
    subdivide.parameters["levels"] = 3
    third_snapshot = GraphSnapshot.from_scene(window.scene)
    third_mesh, third_revision, third_error = window._material_geometry_state(
        material, third_snapshot
    )
    assert third_mesh is not None and third_error is None
    assert third_mesh is not first_mesh
    assert third_mesh.cache_key != first_mesh.cache_key
    assert third_revision != first_revision
    assert len(evaluations) == 2

    assert window._geometry_result_cache.stats().hits >= 1
    _renderer_cache_fixture()

    window.material_controller.cancel()
    window._document_dirty = False
    window._recovered_dirty = False
    window.scene.undo_stack.setClean()
    window._set_dirty(False)
    window.close()
    app.processEvents()
    print(
        "geometry cache performance test passed: unrelated Material edits reuse the exact "
        "subdivided mesh, geometry edits invalidate only their own branch, and GPU vertex/index "
        "buffers remain resident across wrapper and focus changes"
    )


if __name__ == "__main__":
    main()
