# Testing 0.48.7 — Geometry Operations and Cylinder Taper

## Geometry Combine

- Add two different Geometry generators and connect them to **Top Geometry** and **Bottom Geometry**.
- Give the Bottom generator a visibly offset origin, then focus Geometry Combine. Confirm the combined mesh uses that Bottom origin/pivot gizmo while neither input mesh changes position.
- Confirm both meshes remain complete, including their original normals and UVs.
- Connect Geometry Combine to Geometry Output and export OBJ. Confirm it is one file containing both meshes.
- Overlapping surfaces are expected to remain: this first Combine node concatenates meshes and does not weld or perform a boolean union.

## Geometry Displace

- Use a highly subdivided Plane, Box or Cylinder as Geometry and connect a grayscale procedural map to Height.
- Increase and decrease **Multiplier**, including negative values. Confirm vertices move along their normals in both directions.
- Confirm the neutral shaded preview responds to the new surface slopes rather than retaining completely flat pre-displacement normals.
- Test a geometry generator with UV Tiles U/V above 1 and confirm the heightmap repeats through those UVs.
- Animate the grayscale branch and focus Geometry Displace during timeline playback. Confirm the mesh follows the current frame.
- Export through Geometry Output and confirm the exported OBJ contains physically displaced vertices rather than only viewport displacement.

## Cylinder taper experiment

- Leave Top/Bottom Radius Offset at zero and confirm the ordinary cylinder is unchanged.
- Set **Top Radius Offset** positive and confirm the upper end becomes wider.
- Set **Bottom Radius Offset** positive and confirm the lower end becomes wider.
- Use a negative offset equal to or larger than the main Radius and confirm that end collapses to a clean cone tip without black/degenerate triangles.
- Test smooth/faceted sides, caps, cap subdivisions, all three orientations, origin placement and UV tiling on tapered forms.
- Confirm a collapsed cone end has no zero-area cap while the other end retains its cap.

## Integration and regression

- Connect Combined or Displaced Geometry to Material and confirm the material previews on the resulting mesh.
- Confirm pivot gizmo and wireframe inspection still appear only while Geometry is focused.
- Confirm Plane, Box, ordinary Cylinder and Geometry Output still behave normally.
- Confirm invalid Colour-to-Height and image-to-Geometry connections remain rejected by typed sockets.
