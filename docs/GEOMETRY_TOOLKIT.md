# Geometry Toolkit

Version 0.49.0 turns the Geometry data type from a small set of generators into a reusable procedural mesh workflow.

## Geometry Transform

Geometry Transform accepts any Geometry value and applies scale, X/Y/Z rotation, then translation. **Current Origin** uses the exported pivot at world zero. **Bounds Centre** transforms around the current mesh centre while leaving the output export pivot unchanged. Non-uniform scale transforms normals with the inverse scale, and an odd number of mirrored axes reverses triangle winding automatically.

## Geometry Subdivide

Every level splits one triangle into four and shares midpoint vertices across indexed edges. **Smooth Surface** off preserves positions, normals, UVs and the original silhouette while increasing topology density. This is the preferred mode before Geometry Displace. Smooth Surface on performs a welded-position relaxation and rebuilds smooth normals. A safety limit rejects requests that would exceed two million output triangles.

## Geometry Normals

- **Smooth** averages connected face normals across coincident positions, including UV seam duplicates.
- **Smoothing Angle** averages only faces within the selected angle and splits per-corner vertices when a position needs more than one normal.
- **Flat** creates one face normal per triangle corner.
- **Flip Normals** reverses the rebuilt normal vectors.
- **Reverse Triangle Winding** reverses face orientation before normals are rebuilt.

## Geometry Disc / Ring

Inner Radius zero creates a disc; positive values create an annulus. Arc Start and Arc Spread create partial sectors. Ring Segments add radial topology and Radial Segments control circumference density. **Planar** UVs project the circle into a square, while **Radial Strip** maps U around the arc and V across the ring width for scrolling radial effects. Origin, XYZ rotation, axis orientation and integer UV tiling match the existing generators.

## Displacement normal policy

Geometry Displace samples the grayscale height input through UVs and moves vertices along the incoming stored normals. It intentionally copies those normals unchanged into the result. This keeps terrain and VFX meshes compatible with separate normal-map shading and avoids an implicit expensive shading decision. Geometry Normals is the explicit opt-in recalculation stage.

## Persistent geometry performance in 0.49.1

Procedural mesh results now persist above the short-lived geometry evaluation session. The cache key is derived from the selected geometry output and the content revision of only its reachable upstream branch. An edit elsewhere in the graph—such as changing a Material setting or replacing a Roughness constant—therefore does not invalidate a dense Subdivide result.

Pure geometry branches are independent from image resolution, colour space and playback quality. Branches that cross into image evaluation through Geometry Displace retain those context fields, and animated or stateful height branches include their timeline sample in the key.

Every cached result carries one stable renderer identity. The 3D renderer uses that identity to retain recent vertex and index buffers in a separate GPU-memory LRU. Refocusing an unchanged mesh or updating its Material swaps no geometry data and performs no mesh upload. A genuine upstream geometry edit creates one new result and one new GPU buffer pair.

Dense inspection also protects responsiveness: Auto wireframe is skipped above 250,000 triangles because generating the unique edge list can cost more than drawing the shaded mesh. Selecting Wireframe Always remains an explicit opt-in for artists who need every edge.
