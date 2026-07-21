# VFX Texture Lab

**VFX Texture Lab** is an open-source, node-based procedural authoring application for real-time VFX textures, animated flipbooks, reusable PBR materials and lightweight procedural geometry.

It is designed for artists who want the flexibility of a procedural graph without forcing a conventional material-only workflow. The same project can generate masks, noises, distortions, normal and height data, animated effects, complete texture sets and the mesh used to preview or export them.

> VFX Texture Lab is in active development. Current source-testing builds target Linux and Windows and may intentionally change graph behaviour while major systems are still being established.

![VFX Texture Lab workspace](docs/application-layout.png)

## What it is for

VFX Texture Lab is aimed at effects such as:

- Fire, smoke, clouds, energy, magical effects and dissolves
- Distortion, flow maps, scrolling masks and animated gradients
- Flipbook sheets and loopable procedural animation
- Terrain, erosion, surface analysis and scan cleanup
- Reusable PBR material graphs and channel-packed texture sets
- VFX cards, ribbons, rings, beams and simple procedural meshes
- Portable graph assets that can be shared or reused as ordinary nodes

The application is not intended to replace a full polygon modeller or DCC. Its geometry workflow focuses on procedural meshes that are useful for VFX construction, preview and export alongside the generated textures.

## Major features

### Procedural texture graph

- Strongly typed **Greyscale, Colour, Vector/Normal, Material, Math/Signal and Geometry** connections
- GPU-accelerated WGSL evaluation with CPU reference paths for supported nodes
- Noise, shape, blend, adjustment, transform, distortion, blur, flood-fill, distance and terrain families
- Surface-analysis tools including curvature, ambient occlusion, high-pass filtering and histogram selection
- Normal/height processing, scan preparation and tile-making workflows
- 8-bit and 16-bit output handling with higher-precision internal processing

### Materials and 3D preview

- Reusable PBR Material data carrying Base Colour, Emissive, Normal, Height, Roughness, Metallic, AO and related settings
- Material Blend, Override, Switch and channel breakout/composition workflows
- HDR environment lighting, displacement, bloom, shadows, debug views and multiple preview meshes
- Optional procedural Geometry input so a material can be previewed on the mesh produced by the graph
- Responsive animated material playback with incremental texture uploads and persistent GPU resources

### Procedural geometry

Geometry uses a dedicated typed graph value and exports as indexed, UV-mapped Wavefront OBJ data.

Current generators include:

- Plane
- Box
- Cylinder, cone and frustum
- Disc, ring and partial arc
- Tapered VFX ribbon

Current operations include:

- Transform
- Combine
- Subdivide
- Displace from a greyscale heightmap
- Rebuild smooth, angle-limited or flat normals
- Bend and Twist
- UV Transform
- Clean and Weld

Generated meshes support artist-controlled pivots, XYZ rotation, UV tiling and focused 3D inspection. Dense static branches and their vertex/index buffers remain cached across unrelated Material changes.

### Animation and simulation

- Timeline playback with frame, seconds, normalised time, delta time and loop-phase signals
- Exposable animated parameters and curve-driven control
- Loop-aware procedural noise evolution
- Flipbook Generator and Decode workflows
- Stateful nodes including temporal blending, frame delay and reaction diffusion
- Bounded checkpoints, deterministic invalidation and playback-aware preview scheduling

### Graph authoring and reuse

- Searchable node library and keyboard-driven node creation
- Typed reroutes, wire cutting, direct insertion and alignment/distribution tools
- Nested docking for compact graph organisation
- Named Send/Receive portals for long-distance connections
- Graph Input and Graph Output nodes for turning a complete graph into a reusable node
- Multi-document Graph Explorer with linked or embedded graph instances
- Optional node thumbnails and graph-asset thumbnails
- Self-contained graph export, dependency recovery and missing-resource reporting

### Canvas and preview tools

- Dockable 2D Preview, 3D Preview and Canvas Editor
- Fit, tile and 1:1 pixel inspection in the 2D Preview
- Pixel-exact and antialiased rasterisation paths where appropriate
- Dedicated drawing history for Canvas Editor content
- Contextual Inspector with evaluation timing, backend, cache and memory information
- Saved workspace layouts and application themes

### Export and packaging

- PNG, TGA and raw R16 image output
- Quick Export and reusable multi-file texture-set templates
- Channel packing and built-in engine-oriented presets
- Multi-target export profiles with shared graph evaluation
- Wavefront OBJ geometry export with UV and normal controls
- Shareable `.vfxexport` export-template files
- Portable self-contained `.vfxgraph` files
- Validated installable `.vfxpackage` archives with optional source images, thumbnails and dependencies

## Typical workflow

1. Create or import source textures, noises, masks and signals.
2. Build procedural image branches and preview any intermediate output directly.
3. Assemble channels into a Material and inspect it in the 3D Preview.
4. Generate or process Geometry when the effect needs a custom card, ring, ribbon or displaced mesh.
5. Animate parameters with Time, Loop Phase or curves and test playback on the final material.
6. Export individual textures, a complete texture set, a flipbook, an OBJ mesh or a portable graph package.

Because every major output is typed, texture, material, signal and mesh branches remain visually distinct and cannot be connected accidentally without an appropriate conversion or composition node.

## Performance model

VFX Texture Lab is built around interactive graph editing rather than full-graph recomputation:

- Compatible image operations run through WebGPU compute shaders.
- GPU textures remain resident and unchanged branches reuse cached results.
- Compatible linear adjustment chains can be fused into one GPU pass.
- Material playback updates only channels that changed.
- Static procedural meshes persist independently from Material edits.
- Dense mesh vertex and index buffers remain resident in the 3D renderer.
- Preview work is coalesced so obsolete intermediate frames do not build a backlog.
- CPU implementations remain available for tests, fallbacks and operations that do not yet have GPU kernels.

The Inspector and GPU/Renderer Diagnostics expose timing and cache information when a graph needs investigation.

## Project and sharing formats

| Format | Purpose |
| --- | --- |
| `.vfxgraph` | Editable graph document or reusable graph asset |
| `.vfxpackage` | Validated installable graph package with dependencies and metadata |
| `.vfxexport` | Shareable texture-set export template |
| `.vfxnodepkg` | Installable custom node package |
| `.obj` | Exported procedural geometry |
| `.png`, `.tga`, `.r16` | Exported texture data |

Graph assets can be linked for live library updates or embedded for portability. Self-contained export recursively embeds reachable graph instances and image sources required to reproduce the result.

## Source-testing setup

These archives are development copies rather than finished installers. Extract the complete folder before running the setup scripts.

### Windows

1. Install 64-bit Python 3.11 or newer and enable **Add Python to PATH**.
2. Extract the source archive.
3. Run `setup.bat` once.
4. Launch with `run.bat`.

### Linux

Install Python 3.11 or newer with pip and virtual-environment support, then run:

```bash
bash setup.sh
./run.sh
```

The setup scripts create a private `.venv` inside the extracted folder. Do not copy that environment between operating systems or unrelated Python versions.

A reasonably current graphics driver is recommended. GPU rendering and compute use WebGPU through `wgpu-py`; exact feature availability depends on the graphics adapter and driver.

## Documentation

Detailed subsystem documentation is available in [`docs/`](docs/), including:

- [`ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`3D_PREVIEW.md`](docs/3D_PREVIEW.md)
- [`MATERIALS.md`](docs/MATERIALS.md)
- [`GEOMETRY_FOUNDATION.md`](docs/GEOMETRY_FOUNDATION.md)
- [`GEOMETRY_TOOLKIT.md`](docs/GEOMETRY_TOOLKIT.md)
- [`GEOMETRY_SHAPING.md`](docs/GEOMETRY_SHAPING.md)
- [`GRAPH_ASSETS.md`](docs/GRAPH_ASSETS.md)
- [`EXPORTING.md`](docs/EXPORTING.md)
- [`SIMULATIONS.md`](docs/SIMULATIONS.md)

Release notes are maintained exclusively in [`CHANGELOG.md`](CHANGELOG.md).

## Development status

The project is currently distributed as source-testing builds while its feature set, graph schema and packaging workflow mature. Bug reports are most useful when they include:

- The application version
- Operating system and graphics hardware
- A minimal `.vfxgraph` reproducer when possible
- The complete terminal or Command Prompt output for startup or GPU failures
- A screenshot or short capture for visual and playback issues

## License

VFX Texture Lab is released under the [MIT License](LICENSE).
