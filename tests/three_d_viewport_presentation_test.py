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
from vfx_texture_lab.ui.parameters import AngleDial
from vfx_texture_lab.three_d.settings import viewport_settings
from vfx_texture_lab.three_d.meshes import (cube_mesh, mesh_for_settings, rounded_cube_mesh, rounded_cylinder_mesh, sphere_mesh)


def assert_sphere_faces_outward() -> None:
    mesh = sphere_mesh(32, 16)
    triangles = mesh.indices.reshape(-1, 3)
    positions = mesh.vertices[:, :3]
    p0 = positions[triangles[:, 0]]
    p1 = positions[triangles[:, 1]]
    p2 = positions[triangles[:, 2]]
    faces = np.cross(p1 - p0, p2 - p0)
    centres = (p0 + p1 + p2) / 3.0
    orientation = np.einsum("ij,ij->i", faces, centres)
    non_degenerate = np.linalg.norm(faces, axis=1) > 1e-8
    assert np.all(orientation[non_degenerate] > 0.0), orientation.min()


def assert_rounded_mesh_topology() -> None:
    cylinder = rounded_cylinder_mesh(64, 10)
    positions = cylinder.vertices[:, :3]
    uvs = cylinder.vertices[:, 6:8]
    top = float(positions[:, 1].max())
    bottom = float(positions[:, 1].min())
    top_vertices = positions[np.isclose(positions[:, 1], top)]
    bottom_vertices = positions[np.isclose(positions[:, 1], bottom)]
    # Fully curved ends meet in one pole each; there are no planar cap discs.
    assert top_vertices.shape[0] == 1 and bottom_vertices.shape[0] == 1
    assert np.allclose(top_vertices[0, (0, 2)], 0.0)
    assert np.allclose(bottom_vertices[0, (0, 2)], 0.0)
    assert np.isclose(float(uvs[:, 0].max()), 2.0)

    triangles = cylinder.indices.reshape(-1, 3)
    p0 = positions[triangles[:, 0]]
    p1 = positions[triangles[:, 1]]
    p2 = positions[triangles[:, 2]]
    faces = np.cross(p1 - p0, p2 - p0)
    normals = cylinder.vertices[:, 3:6][triangles].mean(axis=1)
    assert np.all(np.einsum("ij,ij->i", faces, normals) > 0.0)
    edges = np.concatenate((
        np.linalg.norm(p1 - p0, axis=1),
        np.linalg.norm(p2 - p1, axis=1),
        np.linalg.norm(p0 - p2, axis=1),
    ))
    edges = edges[edges > 1.0e-7]
    assert float(edges.max() / np.median(edges)) < 1.6


def assert_quality_is_mesh_specific() -> None:
    assert cube_mesh().triangle_count == 12
    assert mesh_for_settings("Cube", "High").triangle_count > 12
    assert rounded_cube_mesh(8).triangle_count > 12
    assert rounded_cylinder_mesh(32, 4).triangle_count > 100
    assert mesh_for_settings("Rounded Cube", "Low").triangle_count < mesh_for_settings("Rounded Cube", "Ultra").triangle_count
    assert mesh_for_settings("Rounded Cylinder", "Low").triangle_count < mesh_for_settings("Rounded Cylinder", "Ultra").triangle_count
    assert mesh_for_settings("Flat Plane", "High").triangle_count == 256 * 256 * 2
    assert mesh_for_settings("Sphere", "Low").triangle_count < mesh_for_settings("Sphere", "Ultra").triangle_count


def main() -> None:
    assert_sphere_faces_outward()
    assert_rounded_mesh_topology()
    assert_quality_is_mesh_specific()

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    app.processEvents()
    panel = window.preview_3d_panel
    assert isinstance(panel.sun_azimuth_dial, AngleDial)
    assert panel.settings_frame.maximumHeight() >= 286
    panel.settings_button.click()
    app.processEvents()

    panel.set_viewport_setting("preview_mesh", "Terrain Plane", persist=False)
    app.processEvents()
    assert panel.mesh_quality_combo.isVisible()
    assert panel.tile_combo.isVisible()
    assert not panel.custom_mesh_row.isVisible()
    assert not panel.grid_checkbox.isHidden()

    panel.set_viewport_setting("preview_mesh", "Cube", persist=False)
    app.processEvents()
    assert panel.mesh_quality_combo.isVisible()
    assert not panel.tile_combo.isVisible()
    assert not panel.custom_mesh_row.isVisible()
    assert panel.grid_checkbox.isHidden()
    assert not panel.uv_grid_checkbox.isHidden()
    assert not panel.material_tiling_control.isHidden()
    panel.material_tiling_spin.setValue(4)
    app.processEvents()
    assert panel.viewport_setting("material_tiling") == 4
    assert panel.material_tiling_spin.singleStep() == 1

    panel.set_viewport_setting("preview_mesh", "Rounded Cube", persist=False)
    app.processEvents()
    assert panel.mesh_quality_combo.isVisible()
    assert not panel.material_tiling_control.isHidden()

    panel.set_viewport_setting("preview_mesh", "Rounded Cylinder", persist=False)
    app.processEvents()
    assert panel.mesh_quality_combo.isVisible()

    panel.set_viewport_setting("preview_mesh", "Custom Mesh", persist=False)
    app.processEvents()
    assert not panel.mesh_quality_combo.isVisible()
    assert not panel.tile_combo.isVisible()
    assert panel.custom_mesh_row.isVisible()

    panel.set_viewport_setting("camera_projection", "Orthographic", persist=False)
    app.processEvents()
    assert panel.fov_control.isHidden()
    panel.set_viewport_setting("camera_projection", "Perspective", persist=False)
    app.processEvents()
    assert not panel.fov_control.isHidden()

    panel.lighting_preset_combo.setCurrentText("Dramatic")
    app.processEvents()
    assert panel.viewport_setting("lighting_preset") == "Dramatic"
    assert panel.viewport_setting("sun_intensity") == 5.0
    assert panel.viewport_setting("environment_intensity") == 0.24
    expected_environment = {"Studio": 0.28, "Soft": 0.30, "Dramatic": 0.24, "Flat": 0.35}
    for preset, expected in expected_environment.items():
        panel.lighting_preset_combo.setCurrentText(preset)
        app.processEvents()
        assert abs(float(panel.viewport_setting("environment_intensity")) - expected) < 1.0e-6
    panel.environment_spin.setValue(0.8)
    app.processEvents()
    assert panel.viewport_setting("lighting_preset") == "Custom"
    assert panel.viewport_setting("lighting_mode") == "Lit"

    assert viewport_settings({"debug_view": "Normal"})["debug_view"] == "Surface Normals (World)"

    for mode in ("Base Colour", "Normal Map (Tangent)", "Surface Normals (World)", "Height", "UV Checker", "Mesh Normals", "Final Material"):
        panel.set_viewport_setting("debug_view", mode, persist=False)
        assert panel.viewport_setting("debug_view") == mode

    renderer = panel.canvas.renderer
    if renderer.available:
        uniforms = renderer._uniform_data(640, 420)
        assert uniforms.size == 92
        assert abs(float(uniforms[-4]) - 4.0) < 1.0e-6
        assert renderer.error == ""

    window.material_controller.cancel()
    window._document_dirty = False
    window._recovered_dirty = False
    window.scene.undo_stack.setClean()
    window._set_dirty(False)
    window.close()
    app.processEvents()
    print("3D viewport presentation test passed")


if __name__ == "__main__":
    main()
