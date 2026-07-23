# Testing VFX Texture Lab 0.51.3.1

## Setup requirement

If you already ran `setup.sh` or `setup.bat` for 0.51.3, no dependency reinstall is required: overwrite the project folder and launch normally. Users upgrading from 0.51.2.1 or older still need to run the matching setup script once to install `fast-simplification`.

Focus a Geometry Decimate node. **Simplification Diagnostics → Backend** should report **Native QEM (fast-simplification)**. In particular, it must no longer show `Buffer dtype mismatch, expected 'float' but got 'double'`. A fallback warning whose details explicitly say the package is not installed still requires the setup script; any other warning should be reported with its full details.

## Imported rock comparison

1. Import the same UV-mapped rock used for the 0.51.2.1 comparison.
2. Connect Mesh Input to Geometry Decimate.
3. Test 50%, 10%, 5% and 1%.
4. Orbit around the complete result with wireframe enabled where practical.
5. Confirm there are no holes or cracks along UV seams, no detached slivers, and no invalid dark triangles caused by zero-area geometry.
6. Compare the silhouette and triangle distribution with Blender's Collapse Decimate at the same ratio.

At extreme 1% reduction, large triangles are expected because very little topology remains. They should still form a connected, closed surface when the input is closed.

## Responsiveness and cancellation

1. Use a mesh around 30,000–100,000 vertices.
2. Drag Percentage continuously between several values.
3. Confirm the main window, viewport orbit and graph pan remain responsive.
4. Confirm the Decimate node and connected wires animate orange while working.
5. Confirm the Evaluation Inspector and 3D status line report topology preparation, native simplification, collapse replay, attribute restoration and completion.
6. Release the slider on a distinct final value. Only that newest value should appear; obsolete intermediate results must not flash into the viewport later.
7. Change Percentage again after one result completes. Nearby values should generally reuse the cached collapse sequence and complete faster than the first request.
8. Change focus to an image node during a long geometry operation. The old geometry result must not replace the new active preview when it eventually finishes.

## Mesh Input diagnostics

Test a closed mesh, an intentionally open plane and a damaged/non-manifold OBJ.

Check that Source Information shows:

- file and loaded-mesh memory;
- unique geometric positions;
- boundary and non-manifold edges;
- degenerate and duplicate triangles;
- connected components;
- UV and hard-normal seam counts;
- a correct closed-manifold summary.

For a linked OBJ larger than 32 MiB, selecting the file should not synchronously freeze the interface. The panel should initially say diagnostics are pending and populate after the Mesh Input is previewed.

## Million-triangle stress test

From the project directory:

```bash
.venv/bin/python tools/geometry_stress.py --triangles 1000000 --obj-roundtrip --json million-mesh.json
```

On Windows:

```bat
.venv\Scripts\python.exe tools\geometry_stress.py --triangles 1000000 --obj-roundtrip --json million-mesh.json
```

Then optionally add `--decimate-percent 1`. Confirm the report contains exactly 1,000,000 imported triangles, sensible memory figures, one connected component for the generated grid, native backend availability, and automatic wireframe suppression.

## Regression checks

- Procedural Plane, Box, Cylinder, Disc, Ring and Ribbon still preview.
- Geometry Transform, Combine, Displace, Normals, Subdivide, Un-Subdivide and Clean/Weld still evaluate.
- Mesh Input linked/embedded resources and Explorer drag-and-drop still work.
- Material Geometry override still uses the latest cached mesh.
- Geometry Output OBJ export still writes the visible result.
- Windows release automation includes the native simplification extension in the portable build and installer.
