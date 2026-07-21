from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from vfx_texture_lab.main_window import MainWindow
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.three_d.meshes import (cube_mesh, load_gltf_mesh, rounded_cube_mesh, rounded_cylinder_mesh, sphere_mesh, terrain_grid)


def _write_test_gltf(root: Path) -> Path:
    positions = np.asarray(((-1.0, 0.0, -1.0), (1.0, 0.0, -1.0), (0.0, 0.0, 1.0)), dtype=np.float32)
    normals = np.asarray(((0.0, 1.0, 0.0),) * 3, dtype=np.float32)
    uvs = np.asarray(((0.0, 0.0), (1.0, 0.0), (0.5, 1.0)), dtype=np.float32)
    indices = np.asarray((0, 2, 1), dtype=np.uint16)
    chunks = [positions.tobytes(), normals.tobytes(), uvs.tobytes(), indices.tobytes()]
    offsets = []
    cursor = 0
    payload = bytearray()
    for chunk in chunks:
        while cursor % 4:
            payload.append(0)
            cursor += 1
        offsets.append(cursor)
        payload.extend(chunk)
        cursor += len(chunk)
    (root / "mesh.bin").write_bytes(payload)
    doc = {
        "asset": {"version": "2.0"},
        "buffers": [{"uri": "mesh.bin", "byteLength": len(payload)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": offsets[0], "byteLength": positions.nbytes},
            {"buffer": 0, "byteOffset": offsets[1], "byteLength": normals.nbytes},
            {"buffer": 0, "byteOffset": offsets[2], "byteLength": uvs.nbytes},
            {"buffer": 0, "byteOffset": offsets[3], "byteLength": indices.nbytes},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5126, "count": 3, "type": "VEC2"},
            {"bufferView": 3, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
        "meshes": [{"name": "Test Triangle", "primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2}, "indices": 3}]}],
    }
    path = root / "mesh.gltf"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _wait(app: QApplication, predicate, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def main() -> None:
    registry = build_registry()
    definition = registry.get("material.pbr")
    expected = {
        "Base Colour": "color",
        "Emissive": "color",
        "Normal": "vector",
        "Height": "grayscale",
        "Ambient Occlusion": "grayscale",
        "Metallic": "grayscale",
        "Roughness": "grayscale",
        "Specular Level": "grayscale",
        "Opacity": "grayscale",
    }
    for name, kind in expected.items():
        assert definition.input_kind(name) == kind, (name, definition.input_kind(name))
    assert not definition.terminal
    assert definition.output_names == ("Material",)
    assert definition.output_kind("Material") == "material"

    assert terrain_grid(32).triangle_count == 32 * 32 * 2
    assert cube_mesh().triangle_count == 12
    assert rounded_cube_mesh(8).triangle_count > cube_mesh().triangle_count
    assert rounded_cylinder_mesh(32, 4).triangle_count > 100
    assert sphere_mesh(16, 8).triangle_count == 16 * 8 * 2
    with tempfile.TemporaryDirectory() as temp:
        mesh = load_gltf_mesh(_write_test_gltf(Path(temp)))
        assert mesh.vertex_count == 3 and mesh.triangle_count == 1
        assert mesh.name == "Test Triangle"

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    assert "Double-click" in window.preview_3d_panel.status.toolTip()
    output = next(node for node in window.scene.nodes.values() if node.definition.type_id == "material.pbr")
    assert window._find_3d_output() is output
    window.scene.set_active_node(output, force=True)
    assert _wait(app, lambda: "material maps" in window.preview_3d_panel.status.toolTip() or not window.preview_3d_panel.available)
    if window.evaluator.gpu_available:
        assert window.preview_3d_panel.available, window.preview_3d_panel.status.toolTip()
        renderer = window.preview_3d_panel.canvas.renderer
        assert renderer.error == "", renderer.error
        assert renderer._mesh is not None
        pixmap = window.preview_3d_panel.canvas.grab()
        image = pixmap.toImage()
        assert image.width() > 100 and image.height() > 100
        # The rendered terrain cannot be a flat clear-colour card.
        sample = image.pixelColor(image.width() // 2, image.height() // 2)
        corner = image.pixelColor(2, 2)
        assert sample != corner

        assert window._find_3d_output() is output
        for mesh_name in ("Sphere", "Cube", "Rounded Cube", "Rounded Cylinder", "Flat Plane", "Terrain Plane"):
            window.preview_3d_panel.set_viewport_setting("preview_mesh", mesh_name, persist=False)
            window.preview_3d_panel.set_viewport_setting(
                "tile_preview", "3 × 3" if "Plane" in mesh_name else "1 × 1", persist=False
            )
            assert _wait(app, lambda: renderer._mesh is not None and renderer._mesh.name == mesh_name)
            assert renderer.error == "", renderer.error

    texture_output = next(
        node for node in window.scene.nodes.values()
        if node.definition.type_id == "output.texture_set"
    )
    window.scene.set_active_node(texture_output, force=True)
    assert window._find_3d_output() is output
    assert _wait(app, lambda: window.preview_panel.title.text().startswith("Material") or not window.preview_3d_panel.available)

    window.material_controller.cancel()
    window._document_dirty = False
    window._recovered_dirty = False
    window.scene.undo_stack.setClean()
    window._set_dirty(False)
    window.close()
    app.processEvents()
    print(
        "3D preview test passed: focused reusable PBR Material node, viewport-owned mesh settings, "
        "terrain/sphere/cube/rounded meshes, glTF import and shared-device WebGPU rendering"
    )


if __name__ == "__main__":
    main()
