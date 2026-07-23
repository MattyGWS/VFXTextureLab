from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import vfx_texture_lab.engine.evaluator as evaluator_module
from vfx_texture_lab.main_window import MainWindow
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.three_d.renderer import ThreeDRenderer
from vfx_texture_lab.three_d.settings import VIEWPORT_DEFAULTS, viewport_settings


MOVED = {"displacement_amount", "height_midpoint", "invert_height"}


def main() -> None:
    registry = build_registry()
    material = registry.get("material.pbr")
    override = registry.get("material.override")
    assert MOVED.isdisjoint({parameter.name for parameter in material.parameters})
    assert MOVED.isdisjoint({parameter.name for parameter in override.parameters})
    assert MOVED.issubset(VIEWPORT_DEFAULTS)

    normalised = viewport_settings({
        "displacement_amount": 99.0,
        "height_midpoint": -2.0,
        "invert_height": 1,
    })
    assert normalised["displacement_amount"] == 5.0
    assert normalised["height_midpoint"] == 0.0
    assert normalised["invert_height"] is True

    # Even a result carrying obsolete material metadata cannot override the
    # project-owned viewport values inside the renderer.
    renderer = ThreeDRenderer.__new__(ThreeDRenderer)
    renderer.available = True
    renderer._lock = threading.RLock()
    renderer.material_settings = {
        "surface_mode": "Opaque",
        "displacement_amount": 4.0,
        "height_midpoint": 0.9,
        "invert_height": False,
    }
    renderer.viewport_settings = viewport_settings()
    renderer.settings = {}
    draws = []
    renderer.request_draw = lambda: draws.append(True)
    renderer.update_viewport_uniforms({
        **renderer.viewport_settings,
        "displacement_amount": 0.83,
        "height_midpoint": 0.41,
        "invert_height": True,
    })
    assert renderer.settings["displacement_amount"] == 0.83
    assert renderer.settings["height_midpoint"] == 0.41
    assert renderer.settings["invert_height"] is True
    assert draws == [True]

    legacy = {
        "format": "vfx-texture-lab-graph",
        "version": 17,
        "active_node": "blend",
        "nodes": [
            {"uid": "background", "type": "material.pbr", "parameters": {
                "name": "Background",
                "displacement_amount": 0.92,
                "height_midpoint": 0.37,
                "invert_height": True,
            }},
            {"uid": "foreground", "type": "material.pbr", "parameters": {
                "name": "Foreground",
                "displacement_amount": 0.12,
                "height_midpoint": 0.5,
                "invert_height": False,
            }},
            {"uid": "blend", "type": "material.blend", "parameters": {
                "settings_source": "Background",
            }},
        ],
        "connections": [
            {"source": "background", "source_output": "Material", "target": "blend", "input": "Background Material"},
            {"source": "foreground", "source_output": "Material", "target": "blend", "input": "Foreground Material"},
        ],
        "viewport_3d": {"settings": {"preview_mesh": "Terrain Plane"}},
    }
    migrated = MainWindow._migrate_project_data(legacy)
    viewport = migrated["viewport_3d"]["settings"]
    assert viewport["displacement_amount"] == 0.92
    assert viewport["height_midpoint"] == 0.37
    assert viewport["invert_height"] is True
    for node in migrated["nodes"]:
        if node["type"] in {"material.pbr", "material.override"}:
            assert MOVED.isdisjoint(node["parameters"])

    # This regression checks scheduling and ownership, not WebGPU itself. Keep
    # headless CI on the CPU path so surfaceless driver availability is irrelevant.
    evaluator_module.WgpuBackend = None
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1300, 850)
    window.show()
    app.processEvents()

    panel = window.preview_3d_panel
    material_node = next(node for node in window.scene.nodes.values() if node.definition.type_id == "material.pbr")
    window.scene.set_active_node(material_node, force=True)
    app.processEvents()
    request_key_before = window._current_material_request_key()
    graph_parameters_before = dict(material_node.parameters)
    uniform_updates = []
    full_viewport_updates = []
    original_uniform_update = panel.canvas.renderer.update_viewport_uniforms
    original_full_update = panel.canvas.renderer.update_viewport
    panel.canvas.renderer.update_viewport_uniforms = lambda settings: uniform_updates.append(dict(settings))
    panel.canvas.renderer.update_viewport = lambda settings: full_viewport_updates.append(dict(settings))

    panel.displacement_amount_spin.setValue(0.83)
    panel.height_midpoint_spin.setValue(0.41)
    panel.invert_height_checkbox.setChecked(True)
    app.processEvents()

    assert panel.viewport_setting("displacement_amount") == 0.83
    assert panel.viewport_setting("height_midpoint") == 0.41
    assert panel.viewport_setting("invert_height") is True
    assert material_node.parameters == graph_parameters_before
    assert window._current_material_request_key() == request_key_before
    assert len(uniform_updates) == 3
    assert not full_viewport_updates
    panel.canvas.renderer.update_viewport_uniforms = original_uniform_update
    panel.canvas.renderer.update_viewport = original_full_update
    if panel.available:
        renderer = panel.canvas.renderer
        renderer.update_viewport_uniforms(panel.viewport_settings())
        assert renderer.settings["displacement_amount"] == 0.83
        assert renderer.settings["height_midpoint"] == 0.41
        assert renderer.settings["invert_height"] is True

    saved = window._project_data()
    assert saved["version"] == 20
    assert saved["viewport_3d"]["settings"]["displacement_amount"] == 0.83
    saved_material = next(node for node in saved["nodes"] if node["type"] == "material.pbr")
    assert MOVED.isdisjoint(saved_material["parameters"])

    window.material_controller.cancel()
    window._document_dirty = False
    window._recovered_dirty = False
    window.scene.undo_stack.setClean()
    window._set_dirty(False)
    window.close()
    app.processEvents()
    print("Viewport-owned live displacement test passed")


if __name__ == "__main__":
    main()
