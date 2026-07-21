# VFX Geometry Shaping

Version 0.50.0 expands the procedural Geometry graph from primitive construction and topology control into reusable VFX-oriented shaping.

## Geometry Ribbon

Geometry Ribbon produces a straight indexed strip with:

- Length
- Width Start and Width End
- Independent length and width segmentation
- Horizontal and vertical base orientations
- The shared Origin X/Y/Z and Rotation X/Y/Z generator controls
- Integer UV Tiles U/V

U runs across the width. V runs from Width Start to Width End, making animated textures predictable for beams, trails, slashes, smoke strips and other scrolling effects.

Width may reach zero at one end to create a tapered point. Both ends cannot be zero because that would produce no valid surface.

## Geometry Bend

Geometry Bend deforms any sufficiently segmented mesh into a circular arc.

- **Bend Amount** controls total signed curvature.
- **Deformation Axis** chooses which mesh bounds axis progresses through the bend.
- **Bend Direction** rotates the bend plane around that axis.
- **Bend Around** selects the authored origin or bounds centre as the bend-axis line.
- **Range Start/End** select a normalised portion of the axis bounds.
- **Clamp Outside Range** keeps the surrounding mesh rigid and extends it along the start/end tangents.

Positions and stored vertex normals rotate together. UVs and topology remain unchanged. Geometry needs enough segments along the deformation axis for a visibly smooth curve.

## Geometry Twist

Geometry Twist rotates each cross-section progressively around X, Y or Z.

The selected range maps from zero rotation to the complete Twist Amount. Clamp Outside Range holds the angle before and after that section; disabling it allows the twist to extrapolate beyond the selected interval.

As with Bend, positions and normals change while UVs and triangle connectivity remain intact.

## Geometry UV Transform

Geometry UV Transform changes only the mesh UV coordinates. Its operation order is:

1. Swap U/V
2. Flip selected axes around the UV pivot
3. Scale U/V around the pivot
4. Rotate around the pivot
5. Apply U/V offset

Geometry positions, normals, indices and export pivot are unaffected. This allows separate shells to receive distinct UV layouts before Geometry Combine, or a generated mesh to be retiled without returning to its source generator.

## Geometry Clean / Weld

Geometry Clean / Weld provides topology cleanup without pretending to be a boolean union.

- Remove degenerate triangles
- Remove unused vertices
- Merge compatible vertices
- Weld using a positive spatial tolerance
- Preserve UV seams by default
- Preserve hard-normal edges by default

At a Weld Distance of zero, exact compatible duplicates are merged. A positive distance uses deterministic spatial quantisation and averages the merged positions and attributes.

Preserving seams includes UV values in the compatibility key. Preserving hard edges includes normals. Disable either option only when those boundaries are intentionally meant to collapse.

This node can join already-compatible boundaries or clean imported/combined shells, but it does not calculate mesh intersections, fill overlapping volumes or perform a manifold boolean union.

## Performance and caching

All five nodes participate in the persistent Geometry branch cache introduced in 0.49.1:

- An unchanged shaping chain evaluates once.
- Unrelated Material edits reuse the existing GeometryData result.
- The 3D renderer retains the mesh vertex and index buffers.
- UV-only edits invalidate the geometry branch but do not invoke image evaluation.
- Bend and Twist operate as vectorised array transforms rather than Python vertex loops.

Very dense meshes remain expensive to create and draw. Use generator segmentation deliberately, add Geometry Subdivide only where needed, and rely on the Subdivide safety limit rather than treating maximum density as a routine working level.
