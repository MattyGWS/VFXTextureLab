# Testing 0.50.0 — VFX Geometry Shaping

## 1. Geometry Ribbon

1. Create **Geometry Ribbon** and focus it.
2. Confirm it starts as a horizontal segmented strip.
3. Change Width Start and Width End independently.
4. Set one width to zero and confirm the ribbon tapers cleanly without invalid triangles.
5. Test all three Orientation values.
6. Move Origin X/Y/Z and rotate on all three axes.
7. Set UV Tiles U/V to visibly different values and apply a checker or scrolling material.

Expected: U runs across the width and V runs along the length. The pivot gizmo and generator controls match Plane, Box, Cylinder and Disc/Ring conventions.

## 2. Geometry Bend

1. Connect a Ribbon with at least 16 Length Segments to **Geometry Bend**.
2. Sweep Bend Amount through positive and negative values.
3. Test X, Y and Z Deformation Axis values.
4. Rotate Bend Direction.
5. Compare Current Origin and Bounds Centre.
6. Set Range Start to 0.25 and Range End to 0.75.
7. Toggle Clamp Outside Range.

Expected: the selected section forms a smooth circular arc. With clamping enabled, geometry outside the range remains rigid and follows the end tangents without a positional break.

## 3. Geometry Twist

1. Connect a segmented Ribbon, Plane, Box or Cylinder to **Geometry Twist**.
2. Test positive and negative Twist Amount.
3. Test all three axes and both pivot modes.
4. Restrict the normalised range and toggle clamping.
5. Place Geometry Normals afterwards when a deliberately rebuilt shading result is desired.

Expected: positions and existing normals twist together; UVs do not change.

## 4. Geometry UV Transform

1. Apply a checker material to a generated mesh.
2. Change Scale U/V and Offset U/V.
3. Rotate around the default 0.5/0.5 pivot.
4. Move the pivot, then test Flip U, Flip V and Swap U/V.
5. Export the mesh as OBJ and inspect its UVs in another application when practical.

Expected: only texture placement changes. Mesh position, shading normals, topology and export pivot remain identical.

## 5. Geometry Clean / Weld

1. Combine two meshes with some coincident compatible vertices.
2. Add **Geometry Clean / Weld**.
3. Keep Weld Distance at zero and compare the vertex count in the 3D status line.
4. Increase Weld Distance gradually.
5. Disable Preserve UV Seams and Preserve Hard Normal Edges separately.
6. Test Remove Degenerate Triangles and Remove Unused Vertices with deliberately dirty geometry when available.

Expected: default cleanup does not collapse visible UV seams or hard edges. Disabling preservation may reduce the vertex count and smooth/merge those boundaries. The node does not perform a boolean union.

## 6. Composition and caching

Build:

`Ribbon → Subdivide → Bend → Twist → UV Transform → Material Geometry`

Then repeatedly adjust Base Colour, Roughness, Emissive and other Material-only controls.

Expected: the shaping chain does not reevaluate and its GPU buffers are not reuploaded until a parameter inside the Geometry branch changes.

## 7. Save, reopen and export

1. Save and reopen the graph.
2. Confirm every parameter and typed connection returns.
3. Export through Geometry Output.
4. Verify the OBJ is one indexed mesh containing the final positions, normals and transformed UVs.

## Automated coverage

The source package includes `tests/geometry_shaping_test.py`, covering typed registration, Ribbon topology/winding/UVs, Bend/Twist attribute preservation, UV-only transformation, and seam-aware cleanup/welding.
