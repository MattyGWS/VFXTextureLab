from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from vfx_texture_lab.main_window import MainWindow
from vfx_texture_lab.three_d.environment import ENVIRONMENT_PRESETS, load_environment, mip_chain
from vfx_texture_lab.three_d.settings import viewport_settings


def assert_environment_assets() -> None:
    for name in ENVIRONMENT_PRESETS:
        image = load_environment(name)
        assert image.shape == (512, 1024, 3), (name, image.shape)
        assert image.dtype == np.float32
        assert float(image.max()) > 2.0, (name, image.max())
        levels = mip_chain(image)
        assert len(levels) >= 10
        assert levels[-1].shape[:2] == (1, 1)


def assert_shader_features() -> None:
    shader = (ROOT / "vfx_texture_lab" / "shaders" / "preview_3d.wgsl").read_text(encoding="utf-8")
    post = (ROOT / "vfx_texture_lab" / "shaders" / "preview_3d_post.wgsl").read_text(encoding="utf-8")
    for token in (
        "derivative_tangent_basis",
        "dpdx(position)",
        "blend_rnm",
        "textureSampleCompare",
        "sample_environment",
        "specular_aa_roughness",
        "environment_brdf",
        "0.08 * specular_level",
        "radiance / (vec3<f32>(1.0) + radiance / 16.0)",
        "vs_shadow",
        "vs_wireframe",
        "fs_wireframe",
        "material_uv",
        "uv_settings",
    ):
        assert token in shader, token
    for token in ("tone_aces", "tone_neutral", "textureSample(bloom_tex", "colour += (scene.rgb - neighbours)", "let vignette"):
        assert token in post, token


def main() -> None:
    assert_environment_assets()
    assert_shader_features()
    defaults = viewport_settings()
    assert defaults["anti_aliasing"] == "4× MSAA"
    assert defaults["tone_mapping"] == "ACES"
    assert defaults["bloom"] is True
    assert defaults["shadows"] is True
    assert defaults["lighting_preset"] == "VFX Studio"
    assert defaults["environment_preset"] == "Cayley Interior"
    assert defaults["background"] == "#2d2938ff"
    assert defaults["show_environment"] is False
    assert defaults["camera_fov"] == 40.0
    assert defaults["material_tiling"] == 1
    assert defaults["wireframe"] == "Auto"
    assert isinstance(defaults["material_tiling"], int)
    assert viewport_settings({"material_tiling": 2.83})["material_tiling"] == 3
    assert viewport_settings({"material_tiling": 0.25})["material_tiling"] == 1
    assert viewport_settings({"wireframe": "Unexpected"})["wireframe"] == "Auto"

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    app.processEvents()
    panel = window.preview_3d_panel
    panel.settings_button.click()
    app.processEvents()

    assert tuple(panel.settings_groups) == ("Mesh", "Displacement", "Camera", "Lighting", "Display", "Quality")
    assert panel.settings_groups["Quality"].body.isVisible()
    assert panel.environment_preset_combo.count() == len(ENVIRONMENT_PRESETS)
    assert panel.wireframe_combo.currentText() == "Auto"
    assert panel.bloom_intensity_control.isVisible()
    panel.set_viewport_setting("bloom", False, persist=False)
    app.processEvents()
    assert not panel.bloom_intensity_control.isVisible()
    panel.set_viewport_setting("bloom", True, persist=False)
    panel.set_viewport_setting("shadows", False, persist=False)
    app.processEvents()
    assert not panel.shadow_control.isVisible()
    panel.set_viewport_setting("shadows", True, persist=False)
    app.processEvents()
    assert panel.shadow_control.isVisible()

    renderer = panel.canvas.renderer
    if renderer.available:
        test_map = np.linspace(0.0, 1.0, 64 * 64, dtype=np.float32).reshape(64, 64)
        renderer.update_material(
            {"Height": test_map},
            frozenset({"Height"}),
            {"surface_mode": "Opaque", "two_sided": False, "cutout_threshold": 0.5, "emissive_intensity": 1.0},
        )
        app.processEvents()
        assert renderer._textures["Height"].mip_count == 7
        for environment in ENVIRONMENT_PRESETS:
            panel.set_viewport_setting("environment_preset", environment, persist=False)
            assert renderer._environment_name == environment
            assert renderer._environment is not None and renderer._environment.mip_count >= 10
        for aa in ("Off", "4× MSAA"):
            panel.set_viewport_setting("anti_aliasing", aa, persist=False)
            renderer.draw()
            assert renderer.error == "" or "MSAA is unavailable" in renderer.error
        panel.set_viewport_setting("preview_mesh", "Flat Plane", persist=False)
        panel.set_viewport_setting("mesh_quality", "Low", persist=False)
        panel.set_viewport_setting("wireframe", "Always", persist=False)
        renderer.draw()
        assert renderer.wireframe_enabled()
        assert renderer._wire_index_count > 0
        assert renderer._wireframe_pipelines
        panel.set_viewport_setting("wireframe", "Off", persist=False)
        assert not renderer.wireframe_enabled()
        for tone in ("ACES", "Neutral", "Reinhard", "Linear"):
            panel.set_viewport_setting("tone_mapping", tone, persist=False)
            renderer._post_uniform_data(640, 420)
        for surface_mode in ("Opaque", "Alpha Cutout", "Alpha Blend", "Premultiplied Alpha", "Additive"):
            renderer.update_material(
                {},
                frozenset(),
                {
                    "surface_mode": surface_mode,
                    "two_sided": False,
                    "cutout_threshold": 0.5,
                    "emissive_intensity": 1.0,
                },
            )
            renderer.draw()
            assert renderer.error == "" or "MSAA is unavailable" in renderer.error, (surface_mode, renderer.error)
        assert renderer._uniform_data(640, 420).size == 92
        assert renderer._post_uniform_data(640, 420).size == 40

    window.material_controller.cancel()
    window._document_dirty = False
    window._recovered_dirty = False
    window.scene.undo_stack.setClean()
    window._set_dirty(False)
    window.close()
    app.processEvents()
    print("3D renderer quality test passed")


if __name__ == "__main__":
    main()
