from __future__ import annotations

import importlib
import sys
import threading
import types
from pathlib import Path
from types import MethodType, SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _import_renderer_without_qt():
    """Renderer/mesh/cache modules do not require Qt themselves.

    The package __init__ files also expose Qt panels and async controllers, so a
    source-only test environment may need lightweight package shells to reach the
    independent modules without importing PySide6.
    """
    try:
        renderer_module = importlib.import_module("vfx_texture_lab.three_d.renderer")
        mesh_module = importlib.import_module("vfx_texture_lab.three_d.meshes")
        cache_module = importlib.import_module("vfx_texture_lab.engine.cache")
        return renderer_module, mesh_module, cache_module
    except ModuleNotFoundError as exc:
        if not str(getattr(exc, "name", "")).startswith("PySide6"):
            raise
        package_root = ROOT / "vfx_texture_lab"
        for name, directory in (
            ("vfx_texture_lab.engine", package_root / "engine"),
            ("vfx_texture_lab.three_d", package_root / "three_d"),
        ):
            shell = types.ModuleType(name)
            shell.__path__ = [str(directory)]
            sys.modules[name] = shell
        cache_module = importlib.import_module("vfx_texture_lab.engine.cache")
        mesh_module = importlib.import_module("vfx_texture_lab.three_d.meshes")
        renderer_module = importlib.import_module("vfx_texture_lab.three_d.renderer")
        return renderer_module, mesh_module, cache_module


class FakeBuffer:
    def __init__(self, label: str) -> None:
        self.label = label
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True


class FakeDevice:
    def __init__(self) -> None:
        self.uploads: list[str] = []

    def create_buffer_with_data(self, **kwargs):
        label = str(kwargs.get("label", "buffer"))
        self.uploads.append(label)
        return FakeBuffer(label)


def main() -> None:
    renderer_module, mesh_module, cache_module = _import_renderer_without_qt()
    ThreeDRenderer = renderer_module.ThreeDRenderer
    MeshData = mesh_module.MeshData
    MemoryLRU = cache_module.MemoryLRU

    original_wgpu = renderer_module.wgpu
    renderer_module.wgpu = SimpleNamespace(BufferUsage=SimpleNamespace(VERTEX=1, INDEX=2))
    try:
        renderer = object.__new__(ThreeDRenderer)
        renderer.available = True
        renderer.device = FakeDevice()
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
        mesh_a = MeshData(vertices, indices, "A", "geometry-a")
        mesh_a_wrapper = MeshData(vertices.copy(), indices.copy(), "A wrapper", "geometry-a")
        mesh_b = MeshData(vertices, indices, "B", "geometry-b")

        renderer.set_geometry_override(mesh_a)
        assert len(renderer.device.uploads) == 2
        renderer.set_geometry_override(mesh_a_wrapper)
        assert len(renderer.device.uploads) == 2
        renderer.set_geometry_override(mesh_b)
        assert len(renderer.device.uploads) == 4
        renderer.set_geometry_override(mesh_a)
        assert len(renderer.device.uploads) == 4
        assert renderer.geometry_cache_stats().hits >= 1

        renderer.clear_geometry_cache()
        assert renderer.geometry_cache_stats().entries == 0
        renderer.set_geometry_override(None)
    finally:
        renderer_module.wgpu = original_wgpu

    print(
        "geometry buffer cache unit test passed: stable mesh keys suppress duplicate uploads, "
        "recent vertex/index pairs reactivate from GPU cache, and cache clear preserves the active pair"
    )


if __name__ == "__main__":
    main()
