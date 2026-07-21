# Testing 0.48.2 — Geometry Generator Expansion

Please test the new Geometry generators with particular attention to topology, UVs, preview behaviour and export.

## Geometry Box

- Create **Geometry Box** and confirm Width, Height and Depth all affect the mesh correctly.
- Increase **Subdivisions X/Y/Z** and confirm wireframe density changes on the expected faces.
- Confirm the box is hard-edged rather than rounded.
- Toggle **Centered on origin** and confirm the mesh recentres or shifts so its bounds start at zero.
- Feed the box into **Geometry Output** and confirm OBJ export works.

## Geometry Cylinder

- Create **Geometry Cylinder** and test Radius, Height, Radial Segments and Height Segments.
- Toggle **Generate caps** and confirm the cylinder becomes open/closed correctly.
- Increase **Cap segments** and confirm the cap topology gains additional concentric rings.
- Toggle **Smooth sides** and confirm the wall switches between smooth and faceted shading.
- Change **Orientation** between Axis Y, Axis X and Axis Z and confirm the cylinder rotates correctly.
- Toggle **Centered on origin** and confirm placement updates as expected.
- Confirm the wireframe seam appears sensible and materials tile continuously around the wall.

## Integration

- Connect Box or Cylinder to a **Material** node and confirm focusing the Material previews on that geometry.
- Confirm Geometry nodes still show shaded solid geometry with wireframe in **Auto** mode.
- Confirm ordinary non-Geometry node preview behaviour is unchanged.
- Confirm reroutes, Send/Receive and Graph Input/Output still accept Geometry.

## Regression watch

- Plane generation should still work exactly as before.
- Geometry Output should still export OBJ correctly.
- No new runtime error badges should appear on Geometry nodes during normal use.
