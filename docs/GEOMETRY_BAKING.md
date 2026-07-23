# High-to-Low Geometry Baking

VFX Texture Lab 0.53.0 introduces the first photogrammetry-oriented high-to-low texture baker. The intended graph is:

```text
High Mesh Input ────────────────────────────────┐
High Albedo Image Input ────────────────────────┤
                                                ▼
Low branch: Mesh Input → Delete Small Parts → Remesh → Decimate
           → Normals → UV Unwrap ────────────── Geometry Bake High to Low
```

The node is deliberately manual. Adjust its controls without starting expensive work, then press **Bake** in the Inspector. A completed result remains usable while settings are Out of Date, while a replacement bake runs, or when a later attempt is cancelled or fails.

## Inputs

- **High Geometry** — the detailed source mesh. It does not need low-poly UVs for Normal, Height or AO.
- **Low Geometry** — the target mesh. It must contain usable 0–1 UVs.
- **High Albedo** — optional source colour texture sampled through the high mesh UVs. If it is absent, only Albedo is skipped.
- **Cage Geometry** — optional custom projection cage. It must have exactly the same vertices and triangle topology as Low Geometry.

High and low meshes must occupy the same object space.

## Outputs

- **Baked Material** — lazy Material value containing every completed supported channel and the Low Geometry preview mesh.
- **Albedo**
- **Normal**
- **Height**
- **Ambient Occlusion**
- **Projection Mask** — white where projection found a high-poly surface and black where it missed.
- **Low Geometry**

The saved result is a versioned map dictionary, not four fixed fields. New outputs such as Curvature, Thickness, Bent Normal, Position, Object Normal, ID or Opacity can be added later without changing the persistence and manual-execution design.

## One-click defaults

The defaults target the common case where a low mesh was produced by decimating the high scan:

- 1024 × 1024
- 1× supersampling
- 16 pixels of island padding
- Albedo, Tangent Normal, Signed Height and AO enabled
- Bidirectional normal projection
- Automatic front/back ray range with a 5% bounds margin
- OpenGL (+Y) normal convention
- Automatic symmetric height range around 0.5
- Draft AO with 16 hemisphere rays

For many aligned scan pairs, connecting High Geometry, Low Geometry and High Albedo and pressing **Bake** should be enough.

## Projection

**Bidirectional Normals** casts from both sides of the low surface and chooses the nearest valid high-poly hit. **Outward Only** and **Inward Only** are useful when nearby surfaces cause cross-projection. **Custom Cage** derives projection rays from a matching cage.

Automatic distance considers the combined high/low bounds and a user margin. Manual front and back distances provide tighter control for thin objects, cavities and separate nearby surfaces. The Projection Mask and hit diagnostics reveal missed regions.

## Maps

### Albedo

The baker interpolates the hit triangle's high-poly UV coordinates and samples High Albedo with bilinear or nearest filtering. Alpha can be retained. This first release supports one source atlas; multiple OBJ materials, UDIMs, vertex colour and complete high Material transfer are future work.

### Normal

Normals are transferred directly from the high-poly surface and transformed into the low mesh's tangent basis. The output can use OpenGL (+Y) or DirectX (-Y) convention. Normal is not reconstructed from Height.

The current tangent generator is kept behind an isolated interface so it can be replaced by a bundled MikkTSpace implementation without changing node sockets or saved bake results.

### Height

Height stores the signed projected difference between the low surface and the high hit. Automatic Symmetric mode places the unchanged low surface at 0.5 and fits the largest measured inward/outward distance. Manual mode accepts explicit minimum and maximum distances. Height is persisted at 16-bit precision.

### Ambient Occlusion

AO casts deterministic cosine-weighted hemisphere rays from projected high-poly samples. Draft, Medium and High presets use 16, 64 and 256 rays. AO is normally the slowest pass and is evaluated in cancellable stages.

## Padding and supersampling

Padding extends valid island pixels into empty atlas space to avoid visible mip-map seams. Supersampling evaluates at 2× or 4× linear resolution and downsamples the finished maps. Both increase memory and processing cost; 1× is the interactive default.

The current dense baker allows at most 4096 pixels per internal side: 4096 at 1×, 2048 at 2×, or 1024 at 4×. Requests beyond that limit are rejected before allocating the large working buffers. A future tiled backend can raise this ceiling without changing the node or saved-result format.

## Backend and portability

Production projection uses the open-source `embreex` Python wrapper around Intel Embree's CPU ray tracing kernels. The dependency is installed from binary wheels and is bundled into automated Windows builds. The same CPU bake path is used on Windows and Linux and does not require CUDA or a particular GPU.

A bounded NumPy reference intersector remains available for tests and tiny generated meshes. It intentionally rejects production workloads when Embree is unavailable rather than making the application appear frozen.

## Persistence and caching

Completed maps are compressed into the graph's manual result and survive save/reopen. The high-poly acceleration structure is cached by geometry content. The architecture also separates UV rasterisation, projection and map generation so later releases can add finer incremental rebaking without changing the public node.

## Current limitations

- One high-poly albedo atlas
- No multi-material OBJ/MTL transfer or UDIMs yet
- No vertex-colour source yet
- No curvature, thickness, bent normal, position or ID outputs yet
- No animated geometry baking
- CPU-only production ray projection
- Custom cages must already match Low Geometry topology

These are deliberate first-release boundaries rather than format limitations.
