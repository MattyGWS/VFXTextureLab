# Testing VFX Texture Lab 0.51.2.1

## Geometry Decimate performance

1. Import the same approximately 33k-vertex rock used to test 0.51.2.
2. Connect it to Geometry Decimate and move Percentage between 100%, 75%, 50% and 25%.
3. Confirm changes complete much faster than 0.51.2 and the graph remains responsive.
4. Inspect silhouettes, UV seams and hard edges for obvious flips, holes or degenerate spikes.
5. Confirm 100% returns the original topology and low percentages never produce an empty mesh.

## Geometry Un-Subdivide

1. Connect a Geometry Box with Subdivisions X/Y/Z set to 5. One iteration should visibly reduce the grid instead of reporting an error.
2. Repeat with Geometry Ribbon using several Length and Width Segments.
3. Put Geometry Subdivide after a simple mesh, then Geometry Un-Subdivide. Confirm the requested subdivision levels are removed exactly and extra iterations stop at the original mesh.
4. Connect an arbitrary imported rock or scan directly to Geometry Un-Subdivide. Confirm the node explains that the mesh has no reversible control topology and recommends Geometry Decimate.

## Regression checks

- Mesh Input linked and embedded OBJ loading
- Image and mesh resource drag-and-drop
- Geometry preview and Material geometry override
- Geometry Normals after Decimate
- OBJ export of reduced geometry
