# Testing 0.48.3 — Geometry Pivot and UV Controls

Please test the shared Origin and UV controls on Plane, Box and Cylinder, along with the new pivot gizmo in the 3D Preview.

## Origin / pivot placement

- On **Geometry Plane**, **Geometry Box** and **Geometry Cylinder**, test **Origin X / Y / Z** at `0`, `-1` and `1`.
- Confirm `0` keeps the pivot centred.
- Confirm `-1` places the pivot on the minimum bound of that axis, and `1` on the maximum bound.
- For a Y-axis cylinder, set **Origin Y = -1** and confirm the base sits on the world origin so it can spawn flush to a ground plane.

## UV tiling

- On each generator, test **UV Tiles U / V** with values such as `4 × 1`, `1 × 4` and `4 × 2`.
- Confirm materials visibly repeat the expected number of times and the cylinder wall seam remains clean.
- Confirm Geometry Output writes the adjusted UVs correctly to OBJ.

## Pivot gizmo

- Focus a Geometry node and confirm a non-interactive pivot gizmo appears in the 3D Preview.
- Move the origin controls and confirm the gizmo updates to the new pivot location.
- Focus a **Material** node using connected geometry and confirm the pivot gizmo does **not** appear there; it should only show for focused Geometry nodes.

## Regression watch

- Geometry Plane, Box and Cylinder should still generate correctly.
- Wireframe overlay behaviour should remain correct with no hidden-edge bleed-through.
- Geometry Output OBJ export should continue working normally.
