# Testing VFX Texture Lab 0.52.0–0.52.0.3

## 0.52.0.3 textured inspection regression

1. Connect an image or procedural texture to Geometry UV Unwrap → Preview Texture.
2. Confirm the texture remains beneath the UV wires in the 2D Preview and is also mapped onto the unwrapped geometry in the 3D Preview.
3. Replace, animate or disconnect the Preview Texture. Confirm the presentation refreshes without changing the manual status or launching another unwrap.
4. Disconnecting the texture must restore the neutral shaded geometry inspection material.
5. With a completed unwrap containing a large persistent result, toggle Best Packing and other unapplied controls. Confirm the Inspector responds without the previous avoidable pause and the node simply becomes Out of Date.

## 0.52.0.2 Inspector editing regression

1. Focus Geometry UV Unwrap and scroll to controls near the bottom of the Inspector.
2. Drag a float slider continuously. Confirm the control stays under the pointer and the Inspector never jumps to Manual Execution.
3. Confirm the Manual Execution status changes to **Out of Date** and the button becomes **Re-Unwrap** without rebuilding the parameter page.
4. Change enum, checkbox and spin-box values while scrolled down. Confirm the same scroll position is retained.
5. Run or cancel an unwrap while scrolled down. Same-node status refreshes may rebuild the summary, but the Inspector must remain at the same vertical position.

## 0.52.0.1 setup note

On Linux systems whose default interpreter is Python 3.14 or newer, run `setup.sh` once. It replaces only the project-local `.venv` with a managed Python 3.13 environment so the published xatlas wheel can be installed. The system Python is left untouched.

Run `setup.sh` or `setup.bat` once after replacing the project folder. Automatic Charts requires the new native `xatlas` dependency.

## Manual action behaviour

1. Create or import a mesh, connect it to Geometry UV Unwrap and focus the node.
2. Confirm the Inspector initially says **Not Run** and presents **Unwrap**.
3. Change several unwrap controls. Confirm no expensive evaluation starts.
4. Press **Unwrap**. Confirm orange evaluation wires, progress reporting, a responsive interface and a **Cancel** action.
5. While it runs, change one relevant control. Confirm it does not restart automatically and the completed result becomes **Out of Date**.
6. Press **Re-Unwrap** and confirm the previous result remains visible until the replacement completes.
7. Cancel a later run and confirm the previous successful geometry and UV preview remain intact.
8. Save, close and reopen the graph. Confirm the completed result is restored without unwrapping again.
9. Save or autosave while an unwrap is running, then reopen that graph. Confirm the interrupted request is sealed as Cancelled/Not Run and never launches by itself.

## UV modes and quality

Test Automatic Charts, Box, Planar, Cylindrical and Spherical modes on:

- a generated Box;
- a generated Cylinder or Rounded Cylinder;
- the imported rock mesh used for decimation testing;
- an open Ribbon or Plane;
- a disconnected multi-part mesh.

For Automatic Charts, vary Chart Angle, quality, padding, resolution, seam preservation, rotation and Best Packing. Inspect for missing faces, invalid indices, severe island overlap, out-of-range UVs and unexpected normal changes.

## 2D UV preview

- Confirm the mesh remains visible in 3D while the atlas appears in 2D.
- Toggle Wires, Islands, Seams, Overlaps and Checker.
- Connect and replace Preview Texture. Confirm it updates beneath the UVs and on the 3D mesh without changing the manual state or starting another unwrap.
- Focus Geometry UV Transform and confirm it also shows its existing UV layout in 2D.
- Confirm Fit and 1:1 continue to work.

## Persistence and failure handling

- Save an Up to Date result, reopen it and confirm UV overlap highlighting still works.
- Temporarily use an environment without xatlas and run Automatic Charts. Confirm the node reports a useful failure rather than crashing; projection modes should still work.
- Disconnect Geometry, connect it again and confirm the node clearly becomes stale or requires a new run.
- Change the upstream mesh while an unwrap runs. The active snapshot may finish, but must be labelled Out of Date and must never silently claim to match the new mesh.

## General regressions

Confirm Geometry Decimate, Mesh Input resources, resource drag-and-drop, Material geometry override, Auto Wireframe suppression, Geometry Statistics, graph save/load, portable graph export and Windows release preparation still work.
