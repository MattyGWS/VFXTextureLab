# Testing 0.49.0 — Geometry Toolkit Foundation

## Geometry Transform

- Transform a mesh using Translate X/Y/Z, Rotation X/Y/Z, Uniform Scale and Scale X/Y/Z.
- Confirm **Current Origin** rotates/scales around the pivot gizmo.
- Switch to **Bounds Centre** and confirm the mesh transforms around its centre while the pivot gizmo remains the export origin.
- Test a negative scale axis and confirm the shaded faces remain correctly oriented.
- Combine two meshes after transforming one and confirm their relative placement is retained in one OBJ export.

## Geometry Subdivide

- Apply one and two levels to Plane, Box, Cylinder and Disc / Ring. Each level should multiply triangle count by four.
- With **Smooth Surface** off, confirm the original silhouette and hard edges are retained while wireframe density increases.
- Put Subdivide before Displace and confirm the heightmap gains visibly more geometric detail.
- Enable Smooth Surface on a closed mesh and confirm it relaxes progressively without invalid triangles.

## Geometry Normals

- Compare **Smooth**, **Smoothing Angle** and **Flat** on a Box and a displaced Plane.
- At a low smoothing angle, box edges should remain hard. At a high angle, corners should shade smoothly.
- Test Flip Normals and Reverse Triangle Winding independently.
- Confirm Geometry Displace alone no longer changes vertex shading normals; adding Geometry Normals afterwards should update them.

## Geometry Disc / Ring

- Inner Radius 0 should create a solid disc; positive values should create a ring.
- Test partial arcs with Arc Start and Arc Spread.
- Increase Radial and Ring Segments and inspect topology in wireframe.
- Compare Planar and Radial Strip UV modes with an obvious tiled material.
- Test Axis X/Y/Z, Origin X/Y/Z, Rotation X/Y/Z and UV Tiles U/V.

## Integration and regression

- Focus every new node and confirm shaded geometry inspection, wireframe and pivot gizmo behaviour.
- Feed the output through Material and confirm the pivot gizmo is hidden for Material focus.
- Save/reload a graph containing all four nodes.
- Export through Geometry Output and confirm one valid OBJ with UVs and normals.
- Check animated Material 2D/3D playback and focus switching remain smooth and free of scanline corruption.
