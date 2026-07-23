# Testing VFX Texture Lab 0.51.3.2

## Geometry statistics and dense wireframe behaviour

1. Focus a Geometry Box, Plane or imported Mesh Input routed through Geometry Subdivide.
2. Confirm the Inspector shows a **Geometry Statistics** section after evaluation.
3. Confirm it reports exact input and output vertex/triangle counts, output mesh memory and the topology multiplier.
4. Increase subdivision until the result exceeds 250,000 triangles.
5. Confirm the shaded mesh still appears, Auto wireframe disappears, and the Inspector explicitly explains that this is intentional rather than a failed subdivision.
6. Set 3D Preview → Wireframe to **Always** and confirm the overlay can still be forced (expect a possible pause on very dense meshes).
7. Return Wireframe to **Auto** and confirm interactivity recovers.

## Regression checks

- Geometry Decimate still reports Native QEM when fast-simplification is installed.
- Mesh Input source diagnostics remain unchanged.
- Dense geometry still respects the two-million-triangle Geometry Subdivide safety cap.
- Material preview geometry overrides continue to use the evaluated mesh.
