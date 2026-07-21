# Testing 0.48.8 — Geometry Generator Rotation

Please test Rotation X, Y and Z on **Geometry Plane**, **Geometry Box** and **Geometry Cylinder**.

## Pivot behaviour

- Leave Origin X/Y/Z at zero and confirm each mesh rotates around its centre.
- Move the origin to an edge, corner or cylinder base, then rotate the mesh.
- Confirm the pivot gizmo stays fixed while the geometry moves around it.
- For a Y-axis cylinder, set Origin Y to `-1`, then rotate X or Z. The base-centre pivot should remain fixed at the world origin.

## Axis controls

- Test Rotation X, Y and Z independently at 90°, 180°, 270° and 360°.
- Test combinations such as X 30°, Y 45°, Z 60°.
- Confirm 360° returns to the same orientation as 0°.
- Confirm negative rotation works and typed multi-turn values such as 720° are accepted.

## Generator-specific checks

- Plane: test all three Orientation presets, then add XYZ rotation on top.
- Box: confirm hard normals remain correct after rotation.
- Cylinder: test Axis X/Y/Z orientation, taper offsets, cone tips and smooth/faceted sides with rotation.

## Integration

- Feed rotated geometry into **Geometry Combine** and confirm positions remain as authored.
- Feed rotated geometry into **Geometry Displace** and confirm displacement follows the rotated vertex normals.
- Connect rotated geometry to Material and confirm shaded preview matches direct Geometry inspection.
- Export through Geometry Output and confirm the OBJ contains the rotated positions and normals.

## Regression watch

- Origin and UV controls should behave exactly as before.
- The pivot gizmo should appear only for focused Geometry inspection, not Material focus.
- Wireframe occlusion and animated Material playback should remain unchanged.
