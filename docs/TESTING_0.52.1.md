# Testing VFX Texture Lab 0.52.1

Run `setup.sh` or `setup.bat` once before testing this update. Geometry Remesh adds the wheel-installed `trimesh`, `scipy` and `scikit-image` dependencies.

## Best Packing responsiveness

1. Complete an Automatic Charts unwrap on a moderately dense imported mesh.
2. Scroll to **Best Packing** and toggle it repeatedly without pressing Re-Unwrap.
3. Confirm the checkbox and Inspector respond immediately, the previous UV result remains visible, and the node becomes **Out of Date**.
4. Undo and redo the checkbox change. Confirm the node returns to **Up to Date** when its settings again match the completed unwrap.
5. Press **Re-Unwrap** and confirm Best Packing is applied only during the prompted manual run.

## Geometry Remesh

1. Connect an imported scan or a generated mesh to **Geometry Remesh**.
2. Confirm the input passes through before the first run and the Inspector shows **Remesh**.
3. Use **Relative to Bounds**, begin around 1–2%, then press **Remesh**.
4. Confirm orange activity wires/progress appear and the interface remains responsive.
5. Inspect the rebuilt topology. It should be evenly distributed, normally form a closed surface, retain the source placement, and report no UVs.
6. Change Voxel Size without pressing Re-Remesh. Confirm the previous result remains visible and the node becomes Out of Date.
7. Try an extremely small voxel size and confirm the node rejects an unsafe grid with a useful instruction rather than exhausting memory.
8. Test **Fill Interior**, **Surface Smoothness**, **Preserve Volume** and **Adaptivity** separately.
9. Save/reopen the graph and confirm the completed remesh restores without recalculation.

## Geometry Delete Small Parts

1. Import a scan containing a dominant mesh plus disconnected floating fragments, or combine several separated generated meshes.
2. Add **Geometry Delete Small Parts** with **Keep Largest Only**.
3. Confirm only the dominant connected surface remains and the Inspector reports components/vertices/triangles removed.
4. Change **Size Measure** between Vertex Count, Triangle Count and Surface Area.
5. Use **Keep Parts Above Relative Size** to retain meaningful secondary pieces while removing tiny debris.
6. Confirm UV and hard-normal seams within the main object do not cause it to be split into separate parts.

## Regression checks

- Mesh Input linked and embedded OBJ handling
- Geometry Decimate native backend and diagnostics
- Geometry UV Unwrap manual execution, persistence and 2D/3D preview texture
- Dense geometry Auto Wireframe suppression and statistics
- Save/reopen, undo/redo and Windows package smoke test
