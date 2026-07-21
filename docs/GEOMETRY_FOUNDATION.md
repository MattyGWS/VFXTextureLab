# Geometry Foundation

Version 0.48.0 established the first intentionally narrow procedural-geometry vertical slice to VFX Texture Lab. The goal is not to turn the application into a general modeller. It is to establish a safe typed mesh path for VFX cards, strips, simple surfaces and later terrain/deformation work while leaving the mature 2D texture evaluator untouched.

## Geometry value contract

A Geometry graph value contains:

- interleaved float32 vertex data: position XYZ, normal XYZ and UV XY;
- uint32 indexed triangles;
- a display/export name;
- validated finite values, triangle counts and index bounds.

This matches the existing 3D Preview mesh layout, so generated geometry can be uploaded directly without conversion or image readback. Geometry has its own coral socket and wire colour and is incompatible with Greyscale, Colour, Vector / Normal, Material and signal values.

## Geometry Plane

**Geometry Plane** is the proof-of-concept generator. It produces a centred rectangular grid with:

- Width and Height;
- Subdivisions X and Y;
- Horizontal XZ, Vertical XY or Vertical YZ orientation;
- consistent positive-axis normals and matching triangle winding;
- UVs covering exactly 0–1.

The default 16 × 16 subdivisions produce 289 vertices and 512 triangles. The topology is suitable for future deformation, displacement, VFX card and terrain experiments.

## 3D Preview precedence

The 3D Preview follows a simple temporary override hierarchy:

1. A focused Geometry node shows its generated mesh with neutral shaded PBR inspection and studio lighting.
2. A focused Material with a connected Geometry input shows that Material on the connected mesh.
3. All other nodes use the normal viewport-selected preview primitive exactly as before.

Graph geometry disables terrain-only 3 × 3 mesh replication and terrain-plane assumptions, but ordinary material UV tiling, displacement, lighting, environment and camera controls remain available.

### Wireframe inspection in 0.48.1

The viewport Mesh settings include **Wireframe: Auto / Always / Off**. Auto is the default and shows a topology overlay only while a Geometry node is the active focus. Always applies the overlay to built-in meshes, imported glTF/GLB meshes and Material geometry overrides; Off suppresses it completely.

The overlay is rendered after the shaded solid pass from a deduplicated line index buffer. It uses the same height-displaced vertex function as the material shader and a small depth offset, so the lines remain attached to displaced surfaces without z-fighting.

The Geometry input is a preview association, not a PBR texture channel. Texture Set export therefore continues to export only material maps and never serialises mesh buffers into the Material value.

## Geometry Output and OBJ export

**Geometry Output** accepts one Geometry value and exposes:

- output name and filename pattern;
- Wavefront OBJ encoding;
- Include UV Coordinates;
- Include Vertex Normals;
- Flip UV V Coordinate;
- Export Geometry and remembered Quick Export actions.

OBJ export preserves indexed triangle topology and writes matching `v`, `vt`, `vn` and `f` records. The first export chooses a path; subsequent Quick Export actions overwrite that remembered OBJ destination.

## Graph workflow support

Geometry is supported by:

- ordinary typed connections and loose-wire node search;
- typed reroutes and direct reroute insertion;
- Send/Receive portals;
- Graph Input and Graph Output;
- linked or embedded Graph Instances;
- graph save/load, copy/paste and package-contained nested graphs.

A public Geometry Graph Input is always required. Unlike image, scalar or default Material inputs, there is no meaningful implicit mesh value to manufacture when it is disconnected.

## Deliberate limits of 0.48.0

This milestone does not yet add mesh modifiers, imported geometry nodes, extrusion, curves, booleans, vertex-data texture sampling, tangents, skinning, animation or additional export formats. The mesh structure and evaluator are designed so those can be introduced incrementally after the first plane/preview/export path has been thoroughly tested.


### Generator expansion in 0.48.2

The Geometry Foundation now includes **Geometry Box** and **Geometry Cylinder** in addition to the original Plane. Box deliberately preserves hard edges and separate per-face UV squares so tiled procedural materials behave predictably on all six sides. Cylinder adds a wrapped wall seam, optional caps, cap tessellation and selectable smooth or faceted side normals, which makes it a useful stress test for shading, displacement and OBJ export without yet committing to more advanced mesh-editing nodes.


### Shared pivot and UV controls in 0.48.3

All current Geometry generators now expose the same **Origin X / Y / Z** and **UV Tiles U / V** controls. Origin values are normalised within the generated mesh bounds so pivot placement scales naturally with generator dimensions. The 3D Preview also renders a small non-interactive pivot gizmo while a Geometry node is focused, which makes it easier to confirm export alignment before sending the mesh to an external engine or DCC.


### Geometry operations in 0.48.7

**Geometry Combine** concatenates two complete indexed meshes into one Geometry value. Because mesh positions are stored relative to the origin, copying Top Geometry vertices directly into the Bottom Geometry coordinate space preserves their authored positions while the Bottom origin becomes the shared export pivot. This is intentionally not a weld or boolean operation.

**Geometry Displace** is the first explicit bridge between image and geometry evaluation. It evaluates a strongly typed grayscale Height branch at the current animation frame, samples it through each vertex UV and moves that vertex along its stored normal. Since 0.49.0 it preserves the incoming normals exactly; Geometry Normals is the explicit opt-in stage for rebuilding shading after deformation.

Geometry Cylinder also supports additive top and bottom radius offsets. End radii clamp at zero; collapsed ends use one valid triangle per radial segment and omit zero-area caps, allowing clean cone tips without degenerate topology.


### Pivot-based generator rotation in 0.48.8

Geometry Plane, Box and Cylinder expose shared **Rotation X / Y / Z** controls. The generator first creates its canonical mesh, applies UV tiling, moves the selected Origin point to `(0, 0, 0)`, and then rotates positions and normals around that origin in X → Y → Z order. This keeps the viewport pivot gizmo, Material preview and exported OBJ coordinate system in agreement. Orientation presets on Plane and Cylinder remain useful construction shortcuts and are applied before the shared rotation stage.


### Geometry toolkit foundation in 0.49.0

Geometry can now be transformed, subdivided and have its normals rebuilt through explicit operation nodes. Disc / Ring adds the first VFX-specific radial primitive. Geometry Displace no longer rebuilds normals implicitly; its result preserves incoming shading data until Geometry Normals is deliberately added.
