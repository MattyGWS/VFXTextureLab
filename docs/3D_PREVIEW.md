# Material and 3D Preview

VFX Texture Lab keeps material definition, viewport presentation and export configuration separate while saving all three with the graph document.

- The **Material** node describes what the material is.
- The **3D Preview** panel controls how that material is inspected.
- Material evaluation is demand-driven: it runs only while a Material, or a Texture Set Output connected to it, is the active double-clicked graph node.

## Basic workflow

1. Add **Material** from **Inputs & Outputs**.
2. Connect the required material branches.
3. Double-click the Material to activate it and evaluate the 3D material.
4. Adjust material behaviour in the Parameters panel.
5. Click **Settings…** in the 3D Preview toolbar to inspect mesh, camera, environment, lighting, display and renderer quality in the Parameters dock.
6. Connect the purple Material output to one or more Texture Set Output nodes.
7. Double-click any ordinary texture node to return evaluation focus to that node in the 2D preview.

An inactive Material does not evaluate when unrelated or upstream graph values change. This keeps large graphs responsive when the material is present but not being inspected. While Material is active, its Base Colour appears in 2D and the complete material appears in 3D.

```text
Ridged Noise → Levels ─────────────────→ Material.Height
                      ├→ Gradient Map ─→ Material.Base Colour
                      └→ Height to Normal → Material.Normal
Constant (0.72) ───────────────────────→ Material.Roughness
Constant (0.0) ────────────────────────→ Material.Metallic
Constant (0.0) ────────────────────────→ Material.Specular Level
                                           Material.Material → Texture Set Output.Material
```

## Reusable material node

Material exposes one purple **Material** output. This is a lightweight structural bundle of the connected branches and material settings, not a flattened image. It can feed any number of Texture Set Output nodes without duplicating the PBR wiring.

Double-clicking Material shows its connected Base Colour in 2D. Double-clicking a connected Texture Set Output follows the Material input and shows the same Base Colour.

### Material inputs

| Input | Type | Unconnected behaviour |
|---|---|---|
| Base Colour | Colour | Neutral grey |
| Emissive | Colour | Black |
| Normal | Vector / Normal | Flat normal |
| Height | Greyscale | Height midpoint |
| Ambient Occlusion | Greyscale | White |
| Metallic | Greyscale | Black |
| Roughness | Greyscale | 0.5 |
| Specular Level | Greyscale | 0.5 dielectric reflectance control |
| Opacity | Greyscale | White |

The typed graph prevents colour, greyscale, vector and animation-signal data from being connected to incompatible material sockets.

### Material parameters

**Material**

- Material name
- Surface mode
- Cutout threshold, shown only for Alpha Cutout
- Two-sided rendering
- Emissive intensity

**Normals**

- Normal / slope strength
- OpenGL (+Y) or DirectX (-Y) normal convention
- Optional normals derived from Height

**Displacement**

- Displacement amount
- Height midpoint
- Invert height

## Surface modes

- **Opaque** renders an ordinary opaque surface.
- **Alpha Cutout** discards pixels below the cutout threshold.
- **Alpha Blend** uses conventional source-alpha blending.
- **Premultiplied Alpha** supports premultiplied VFX textures without dark edge fringes.
- **Additive** adds emissive/card colour over the background and is useful for fire, energy and magic effects.

Transparent modes do not write depth. This is appropriate for most preview cards and simple surfaces, but intersecting transparent geometry can still expose the usual draw-order limitations.

## Project-owned viewport presentation settings

Click **Settings…** in the 3D Preview toolbar. The Parameters dock temporarily treats the viewport as its inspector target and shows six collapsible groups:

- **Mesh** — preview mesh, mesh-specific geometry quality, material UV tiling, terrain geometry tiling, custom glTF/GLB selection and material-map resolution.
- **Displacement** — mesh displacement amount, neutral Height midpoint and Height inversion.
- **Camera** — perspective/orthographic projection, field of view and optional turntable rotation.
- **Lighting** — environment preset and rotation, environment intensity, sun direction/intensity and optional directional shadows.
- **Display** — environment or colour background, plane grid, UV-grid overlay and material/debug inspection mode.
- **Quality** — tone mapping, exposure, anti-aliasing, bloom, sharpening and vignette.

Selecting any graph node returns Parameters to that node. The viewport is not represented by a hidden graph node; it is simply another inspector target.

Controls disappear when they do not apply. Terrain tiling is shown only for Terrain Plane, the custom-file row only for Custom Mesh, the plane surface grid only for plane meshes, and field of view only for perspective projection.

These values are saved in the current `.vfxgraph` together with camera orbit, pan and zoom. New files receive the built-in defaults instead of inheriting the previous file’s viewport. Opening a saved graph or recovering an autosave restores that graph’s own state. Changing camera, mesh, displacement, lighting, environment, background, overlays, debug view or post-processing does not reevaluate material branches; material-map preview resolution remains the one presentation setting that requests new texture maps.

## Preview meshes and displacement

Built-in meshes are:

- Terrain Plane
- Flat Plane
- Sphere
- Cube
- Rounded Cube
- Rounded Cylinder

**Custom Mesh** accepts glTF 2.0 `.gltf` or `.glb`. The first triangle primitive is loaded. UV coordinates are required for useful texture preview; missing normals are generated. Skins, morph targets, animation and complete scene hierarchies are not yet supported.

The renderer samples Height in the vertex shader and displaces along the mesh normal. **Displacement Amount**, **Height Midpoint** and **Invert Height** belong to the 3D viewport rather than Material nodes: Height is authored once in the graph, while the current inspection mesh decides how strongly and in which direction to present it. Dragging these controls updates only renderer uniforms against the already uploaded Height texture, so no graph evaluation, material readback, texture upload, environment reload or mesh rebuild is submitted.

Low/Medium/High/Ultra geometry presets map to suitable topology for each built-in mesh rather than one shared subdivision number. Terrain Plane and Flat Plane use regular grids, Sphere changes latitude/longitude density, Cube uses independently tessellated UV faces, and Rounded Cube retains flat face regions with smoothly bevelled edges. Rounded Cylinder is one continuous wall-and-dome surface: its ends are fully curved rather than closed with planar cap discs, and its rings are spaced by profile arc length so displacement remains even over the shoulders, wall and poles. Its U coordinate repeats twice around the circumference to avoid horizontally stretched material inspection.

**Material Tiling** repeats the complete material through the selected mesh UVs. It applies consistently to Base Colour, Emissive, normals, height/displacement, scalar maps, opacity/cutout and UV/debug inspection. It is a whole-number `1–32×` repeat count: `1×` preserves the mesh's authored UV layout, while higher values are useful for checking material repetition and seams on any built-in or custom mesh.

Set Terrain Plane tiling to **3 × 3** to inspect edge continuity across duplicated terrain geometry. Terrain geometry tiling and Material Tiling are independent presentation controls; neither modifies the source textures.

## Camera controls

- Left drag: orbit
- Shift + left drag: pan
- Middle drag: pan
- Mouse wheel: zoom
- `F` or `Home`: reset/frame the mesh
- Free / Front / Back / Left / Right / Top / Bottom: camera orientation
- Perspective / Orthographic: projection
- Field of view: perspective lens angle
- Turntable: continuous presentation rotation with adjustable degrees per second
- Settings: inspect the project-owned viewport settings in Parameters
- Screenshot: capture the square render canvas

## Material inspection views

The Display tab can isolate **Base Colour**, **Normal Map (Tangent)**, **Surface Normals (World)**, **Height**, **Roughness**, **Metallic**, **Ambient Occlusion**, **Emissive** or **Opacity** without rewiring the graph. **Normal Map (Tangent)** displays the conventional purple/blue connected normal texture after strength and OpenGL/DirectX Y handling. **Surface Normals (World)** displays the final normal used for shading after height-derived detail and tangent normal mapping. **UV Checker** exposes stretching and seams, while **Mesh Normals** visualises only the generated/imported geometry normals. **Final Material** returns to normal shading. A UV-grid overlay can be placed over the final material on any mesh.

## Motion and scheduling

When a Material is active, the material follows the current timeline frame and animated branches continue to update. Graph edits are coalesced through the existing preview scheduler, and unchanged upstream resources retain normal evaluator caching.

Double-clicking a 2D node immediately pauses 3D material refresh and gives evaluation priority back to that node. The last completed 3D material remains visible until a Material is activated again.

## Renderer correctness and quality

The material is rendered into an `RGBA16F` HDR scene target before a separate display pass applies exposure, tone mapping and optional post effects. Available tone mappers are ACES, Neutral, Reinhard and Linear. **4× MSAA** is used when supported, with an automatic single-sample fallback on adapters that cannot multisample the floating-point scene target.

Material textures receive complete mip chains and use trilinear filtering with anisotropic sampling. The renderer constructs its tangent frame from screen-space position and UV derivatives, so authored tangent-space normal maps follow the actual UV orientation on built-in and custom meshes. Height displacement is included before reconstructing the macro surface normal, and height-derived detail is combined with the authored normal using reoriented normal mapping.

Four locally bundled environment maps provide image-based diffuse and roughness-dependent specular lighting:

- Studio Small 02
- Cayley Interior
- Overcast Soil
- Chalk Quarry Sunset

They are compact floating-point environment-lighting maps derived from Poly Haven preview panoramas for practical application size. They are not the original full-resolution, unclipped `.hdr` downloads. The application does not contact Poly Haven at runtime.

The lighting presets apply practical multipliers to those HDR maps rather than treating `1.0` as a universal photographic exposure. In 0.43.9, Studio, Soft, Dramatic and Flat were reduced to environment intensities of `0.28`, `0.30`, `0.24` and `0.35` respectively so they retain their intended character without washing out ordinary materials. VFX Studio remains at `0.20`.

Optional directional shadows use a displacement-aware shadow pass with alpha/cutout-aware casting and 3×3 PCF filtering. The Quality tab also provides lightweight interactive bloom, sharpening and vignette. Bloom operates before tone mapping so emissive and additive VFX can exceed display white and produce a visible glow.

The current renderer still does not provide transparent-object sorting, a ground-plane shadow receiver, multi-resolution cinematic bloom, true polygon-edge wireframe or GPU-direct sharing of graph textures. Those remain later refinements rather than blockers for material inspection.

## Focused test checklist

1. Open a new graph and confirm Material is active, its Base Colour appears in 2D, and the complete material appears in 3D.
2. Change Ridged Noise or Levels without activating Material and confirm no 3D material evaluation starts.
3. Double-click Material and confirm the connected material branches evaluate.
4. Keep Material active, change an upstream node and confirm the material refreshes.
5. Double-click an ordinary node, change the same upstream value and confirm only the 2D preview refreshes.
6. Verify Base Colour and Specular Level connections plus the purple Material → Texture Set Output connection.
7. Test Opaque, Alpha Cutout, Alpha Blend, Premultiplied Alpha and Additive.
8. Open 3D Viewport Settings and drag displacement amount and midpoint continuously. Confirm the mesh responds live without an Evaluation Inspector job, node activity or renderer texture upload; then test inversion and height-derived normals.
9. Click **Settings…** and switch mesh, geometry quality, Material Tiling, terrain tiling and map resolution in Parameters.
10. Check Rounded Cube and Rounded Cylinder at every quality level, and confirm irrelevant controls disappear for non-terrain and Custom Mesh choices.
11. Rotate through all four environments and compare a rough dielectric material with a polished metallic one.
12. Toggle the environment background, change exposure and cycle ACES, Neutral, Reinhard and Linear tone mapping.
13. Compare anti-aliasing Off and 4× MSAA on the Sphere and displaced plane silhouette.
14. Enable directional shadows, rotate the sun and test displacement plus Alpha Cutout casting.
15. Connect a tangent-space normal map to Cube or a UV-mapped custom mesh and confirm it follows each face/UV island rather than world orientation.
16. Test emissive materials with Opaque, Alpha Blend, Premultiplied Alpha and Additive while adjusting bloom threshold, radius and intensity.
17. Check sharpening and vignette at zero, subtle and deliberately exaggerated settings.
18. Change renderer presentation controls and confirm the graph is not reevaluated.
19. Load a simple UV-mapped `.gltf` or `.glb` as Custom Mesh.
20. Exercise orbit, zoom, pan, frame, projection, fixed camera views and turntable.
21. Animate a connected branch and play the timeline while Material is active.
22. Connect the same Material to two Texture Set Outputs and confirm both can export independently.
23. Run:

```bash
python tests/viewport_displacement_test.py
python tests/three_d_preview_test.py
python tests/three_d_viewport_presentation_test.py
python tests/three_d_renderer_quality_test.py
python tests/interactive_preview_scheduler_test.py
python tests/incremental_preview_and_3d_feedback_test.py
```
