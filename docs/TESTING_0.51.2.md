# Testing VFX Texture Lab 0.51.2

## Geometry Decimate

1. Create a Geometry Plane with at least 32 subdivisions on each axis and connect it to Geometry Decimate.
2. Confirm the node starts at **100%** and the preview is unchanged.
3. Test 75%, 50%, 25%, 10% and 1%. The triangle count should fall progressively while the outer plane border remains stable and no black, exploded or folded triangles appear.
4. Repeat with Geometry Box, Cylinder and an imported OBJ. Inspect UV seams and hard edges in shaded and wireframe preview.
5. Scrub the percentage using both the slider and numeric field. The control should accept decimal values from **1.0 to 100.0** and should never create an empty mesh.
6. At unusually low percentages, a heavily split mesh may stop above the exact requested count because protected islands or boundaries cannot be collapsed safely. It must not jump below the requested target or generate invalid geometry.

## Geometry Un-Subdivide

1. Create any procedural mesh, pass it through Geometry Subdivide with two levels, then through Geometry Un-Subdivide.
2. Set Iterations to 1. Triangle count should return to the one-level result.
3. Set Iterations to 2. Topology should return to the pre-Subdivide mesh.
4. Request more iterations than exist. It should stop at the earliest recoverable mesh without deleting it.
5. Repeat with **Smooth Surface** enabled on Geometry Subdivide and with Transform, Bend or Twist after subdivision. Topology should still reduce cleanly, although deformed or smoothed vertex positions naturally remain authored at their current locations.
6. Connect an unrelated arbitrary triangulated mesh. When no compatible subdivision structure exists, the node should show a clear incompatibility error rather than corrupting the mesh.

## Regression checks

- Mesh Input linked and embedded OBJ loading still works.
- Graph Explorer image/mesh drag-and-drop still creates input nodes in the correct graph.
- Geometry Subdivide, Normals, Clean / Weld, Displace and OBJ export remain functional before and after the new reduction nodes.
- Material geometry override and focused wireframe preview continue to use the reduced result.
