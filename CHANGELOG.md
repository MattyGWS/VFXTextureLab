# Changelog

## 0.50.0 — VFX Geometry Shaping

- Added **Geometry Ribbon**, generating straight or tapered segmented strips with three base orientations, shared Origin/XYZ Rotation controls and integer U/V tiling. U runs across width and V along length for predictable beams, trails, slashes and scrolling effects.
- Added **Geometry Bend**, a vectorised circular-arc deformation with signed angle, axis, bend-plane direction, origin/bounds pivot, normalised range and continuous rigid tails outside a clamped range.
- Added **Geometry Twist**, progressively rotating positions and stored normals around X, Y or Z with origin/bounds pivot and a controllable normalised range.
- Added **Geometry UV Transform**, applying U/V swap, flip, scale, rotation, pivot and offset without changing mesh positions, normals, topology or export origin.
- Added **Geometry Clean / Weld**, removing degenerate triangles and unused vertices and merging exact or tolerance-based compatible vertices while preserving UV seams and hard-normal boundaries by default.
- Kept all new operations inside the persistent geometry-result and GPU-buffer cache path introduced in 0.49.1; unchanged shaping chains remain resident across unrelated Material edits.
- Replaced the release-history duplicate in `README.md` with a stable GitHub-facing application overview covering use cases, features, workflows, performance, formats, setup and documentation. Release notes now live exclusively in this changelog.
- Added `docs/GEOMETRY_SHAPING.md`, `docs/TESTING_0.50.0.md` and focused pure-geometry regression coverage.
- Graph format remains version 18. Existing geometry graphs load unchanged.

## 0.49.1 — Persistent Geometry Performance

- Added a byte-budgeted persistent procedural-geometry cache keyed by the geometry branch's own upstream content revision rather than the overall graph revision. Unrelated Material edits now reuse the exact existing mesh instead of rerunning Geometry Subdivide, Displace, Transform, Normals or Combine.
- Pure Geometry branches are resolution, colour-space and playback-quality independent in the cache. Geometry Displace branches remain correctly keyed by image sampling resolution, precision and timeline frame when their height input is dynamic.
- Added stable geometry identities to renderer meshes. Rewrapping or refocusing an unchanged procedural mesh no longer invalidates the 3D viewport mesh.
- Added a byte-budgeted renderer geometry cache that keeps recent vertex and index buffers GPU-resident. Switching away from and back to a dense mesh reactivates its existing buffers without another upload.
- Material texture changes now leave the connected procedural mesh and its GPU buffers untouched. A real upstream geometry edit invalidates only that geometry branch and uploads the replacement mesh once.
- Auto wireframe inspection now yields to interactivity above 250,000 triangles instead of constructing a potentially enormous unique-edge buffer. The viewport status reports when this protection is active; Wireframe Always remains an explicit override.
- Extended GPU / Renderer Diagnostics with procedural-geometry CPU and GPU cache entries, memory use and budgets. Clear Render Cache and cache-budget controls now include geometry results and resident mesh buffers.
- Added a focused geometry-cache performance regression covering unrelated Material edits, true geometry invalidation, stable mesh identity and resident GPU buffer reactivation.
- Graph format remains version 18 and the application node count remains **173 node types**.

## 0.49.0 — Geometry Toolkit Foundation

- Added **Geometry Transform** with Translate X/Y/Z, pivot-based Rotation X/Y/Z, Uniform and per-axis Scale, and Current Origin / Bounds Centre transform modes. Non-uniform scale uses the correct inverse normal transform and mirrored scales automatically repair triangle winding.
- Added **Geometry Subdivide**, splitting every triangle into four per level up to six levels. Shape-preserving subdivision adds displacement-ready topology without changing the mesh silhouette; optional Smooth Surface relaxes welded position groups and rebuilds smooth normals.
- Added **Geometry Normals** with Smooth, Smoothing Angle and Flat modes, plus Flip Normals and Reverse Triangle Winding. Angle and Flat modes split per-corner vertices where one position needs several shading normals.
- Added **Geometry Disc / Ring** with Outer/Inner Radius, radial/ring segmentation, partial Arc Start/Spread, Axis X/Y/Z orientation, shared origin and rotation controls, integer UV tiling, and Planar or Radial Strip UV layouts. A zero inner radius uses a non-degenerate centre fan.
- Changed **Geometry Displace** to preserve incoming vertex normals exactly. It now deforms positions only; artists explicitly opt into shading-normal reconstruction through Geometry Normals.
- Added graph, typing, save/load, Material-preview-compatible evaluation, OBJ export, mirrored transform, subdivision, smoothing-angle, non-degenerate disc/ring and preserved-displacement-normal regressions.
- Graph format remains version 18 and the application smoke suite now covers **173 node types**.

## 0.48.8 — Geometry Generator Rotation

- Added shared **Rotation X**, **Rotation Y** and **Rotation Z** controls to Geometry Plane, Box and Cylinder.
- Rotation is applied after Origin X/Y/Z placement, so every generator rotates around the selected export pivot rather than around its original centre.
- Each axis exposes a full **-360° to +360°** slider range, while the numeric field accepts additional accumulated turns.
- Plane and Cylinder orientation presets remain the base construction direction; XYZ rotation is applied on top in X → Y → Z order.
- Vertex normals rotate with positions and remain normalised, preserving correct shaded preview, displacement direction and OBJ normals.
- Added generator-rotation regressions covering pivot stability, axis bounds, full-turn equivalence, normals and registry parameter forwarding.
- Graph format remains version 18 and the application smoke suite remains at **169 node types**.

## 0.48.7 — Geometry Operations and Cylinder Taper

- Added **Geometry Combine** with Top Geometry and Bottom Geometry inputs. It concatenates both indexed meshes without moving either one, retains the Bottom Geometry origin as the shared output/export pivot and produces one Geometry value for a single OBJ export. The operation intentionally does not weld vertices or perform a boolean union.
- Added **Geometry Displace** with Geometry and strongly typed Greyscale Height inputs plus a signed **Multiplier**. Height values are sampled through the mesh UVs with repeat wrapping, vertices move along their stored normals, and vertex normals are rebuilt after deformation while preserving authored hard edges and UV seams.
- Added an explicit image-to-geometry evaluation bridge so Geometry Displace evaluates procedural grayscale branches at the current timeline frame. Live inspection uses the current preview resolution (bounded to 256 px during playback); Geometry Output export samples at the full document resolution.
- Added additive **Top Radius Offset** and **Bottom Radius Offset** controls to Geometry Cylinder. Final end radii are `Radius + Offset`, clamped at zero, supporting cylinders, tapered frustums and true cone tips.
- Added dedicated non-degenerate cone-tip topology, slope-correct smooth/faceted side normals and independent top/bottom cap radii. A collapsed end omits its zero-area cap.
- Added mixed typed-port, graph evaluation, focus-preview, Material geometry override, save/load, OBJ export, winding, normal and non-degenerate topology regressions.
- The application smoke suite now covers **169 node types**.

## 0.48.6.1 — Material Focus Playback Integrity

- Fixed moving horizontal scanline/banding artefacts that could appear in both 2D and 3D Material previews after switching focus away from a playing Material and back again.
- Made GPU cache publication transactional. Textures produced inside a command batch are now kept private until the complete evaluation and display finalisation succeed; cancelled, failed or superseded frames are released instead of entering the reusable graph cache.
- Added playback generation and request serials so a completed frame from an earlier Material focus session cannot be presented by a newer session, even when the same Material node is selected again.
- Clear the queued 3D presentation frame whenever Material focus changes, playback stops, the graph changes or a competing direct preview preempts Material work.
- Restricted adaptive live Material resolution to power-of-two **256 px** and **128 px** tiers. The former 192 px tier could amplify one-texel wrapping/resampling defects during rapid focus changes.
- Added sustained-pressure hysteresis before lowering live quality, preventing one-time shader warm-up from immediately dropping the Material preview tier.
- Added runtime regressions for focus-away/focus-back playback and cancelled GPU cache transactions, alongside the existing material, geometry, renderer, scheduler and complete application smoke suites.

## 0.48.6 — Smooth Material 2D Playback

- Removed the artificial **15 FPS** cap from the focused Material Base Colour preview. Every completed material frame now prepares its 2D display image.
- Decoupled 2D and 3D presentation: Base Colour reaches the 2D Preview immediately when the material worker completes, while the 3D viewport retains its stable newest-frame coalescing cadence.
- Kept the single Material evaluation stream introduced in 0.48.4. The smoother 2D preview does not launch a second graph evaluation or compete with the 3D material branch.
- Added a lightweight prepared-RGBA8 playback path in the 2D Preview that swaps the image at full cadence while updating title and frame-detail text less frequently.
- Added runtime coverage verifying focused-Material 2D presentations keep pace with or exceed coalesced 3D presentations, plus source regressions preventing the 15 FPS throttle from returning.

## 0.48.5 — Smooth Material Playback

- Decoupled Material evaluation from viewport presentation. A newer playhead frame can now evaluate while the latest completed frame waits for the stable 3D display cadence.
- Added newest-frame coalescing: playback keeps at most one active worker and one completed presentation frame, replacing obsolete completed frames instead of building a queue.
- Added adaptive live material resolution across 256, 192 and 128 px tiers. The viewport drops only when measured evaluation/upload cost exceeds the playback budget and restores quality after sustained headroom.
- Removed per-frame playback diagnostic overhead: detailed progress signals, node-state updates, inspector traces, busy labels and thumbnail refresh scheduling are suppressed while playing unless the profiler is explicitly enabled.
- Throttled the Material Base Colour 2D preview to a lighter cadence while allowing the 3D viewport to consume every completed presentation frame. CPU RGBA8 conversion is skipped on material frames that will not update the 2D preview.
- Kept live GPU texture objects and bind groups resident. Dynamic channel pixels update in place; material and shadow bind groups are rebuilt only when a texture view actually changes size or mip layout.
- Removed repeated procedural-geometry evaluation from every Material animation request key. Connected geometry is refreshed when its branch changes, not once per texture frame.
- Pausing still resolves the exact current frame at the selected full-quality material resolution with normal mipmaps and complete inspection diagnostics.
- Added updated scheduler, adaptive-quality, quiet-playback, persistent-binding and material/geometry integration regressions.

## 0.48.4 — Material Playback Performance

- Rebuilt focused **Material** animation around one evaluation stream that now feeds both the 2D Base Colour preview and the complete 3D material, removing the duplicate graph evaluation that previously competed for every playback frame.
- Fixed material-playback starvation: a completed frame is now accepted during real-time playback when the graph branch is still current, even if the wall-clock playhead has already advanced beyond that exact request key.
- Added persistent per-channel residency for direct PBR Materials. Static Roughness, Metallic, Height and other unchanged maps are evaluated once and remain cached across animation frames instead of being read back and uploaded repeatedly.
- Direct Constant and Colour inputs remain compact **1 × 1** material textures rather than expanding into full-resolution maps every frame.
- Added incremental renderer updates: only material channels whose content token changed are uploaded; semantic defaults and static maps remain GPU-resident.
- Dynamic playback maps skip CPU mip-chain construction. Pausing still settles the complete material at the authored viewport resolution with normal mipmaps.
- Material playback now uses a bounded **256 px live map resolution** for responsive animation, then immediately returns to the selected full-quality 3D texture resolution when playback stops.
- Added material-playback performance, static-channel reuse, incremental upload and source-contract regressions.

## 0.48.3 — Geometry Pivot and UV Controls

- Added **Origin X / Y / Z** controls to Geometry Plane, Box and Cylinder. These move the exported mesh pivot within the generator bounds using a normalised -1 to 1 range, making base-, edge- and corner-aligned spawning straightforward for downstream game-engine use.
- Added integer **UV Tiles U / V** controls to Geometry Plane, Box and Cylinder so procedural materials can tile seamlessly without introducing fractional seam mismatches.
- Added a non-interactive **pivot gizmo** to the 3D Preview that appears only while a Geometry node is focused, helping artists verify the current origin placement directly in the viewport.
- Removed the old Box/Cylinder **Centered on origin** option in favour of the new shared Origin controls.
- Extended geometry regression coverage to include origin placement, UV tiling and updated generator parameter evaluation.

## 0.48.2.1 — Wireframe Depth Correction

- Removed the fixed clip-space camera pull from the shaded wireframe overlay. At distance, that offset could become larger than the real depth separation between front and back faces, allowing hidden topology to bleed through.
- Wireframe vertices now use exactly the same displaced world position and projected depth as the shaded surface.
- Retained a read-only **less-equal** depth test so visible coincident lines render cleanly while the shaded depth buffer rejects occluded and back-side edges.
- Added a source-level regression that prevents camera-relative clip-depth offsets from returning to the wireframe shader.
- Geometry Box, Cylinder, Plane and OBJ export are unchanged; graph format remains version 18.

## 0.48.2 — Geometry Generator Expansion

- Added **Geometry Box**, generating hard-edged six-face meshes with independent Width/Height/Depth, per-axis face subdivisions, separate face normals and clean overlapping 0–1 UVs on every face.
- Added **Geometry Cylinder**, generating capped or uncapped cylinders with Radius/Height, radial and height segmentation, cap segmentation, clean cylindrical seam UVs and orientation along the X, Y or Z axis.
- Added a **Smooth sides** option to Geometry Cylinder so users can inspect either conventional smooth wall normals or deliberately faceted side shading.
- Added **Centered on origin** placement controls to Box and Cylinder for easier procedural modelling and downstream export alignment.
- Extended geometry regression coverage with box/cylinder topology, winding, UV-range, seam, orientation and OBJ export checks.
- Geometry Output remains Wavefront OBJ for now; existing 0.48.0/0.48.1 graphs load unchanged and the graph format remains version 18.

## 0.48.1 — Geometry Preview Polish

- Added a true shaded wireframe overlay pass to the 3D Preview, using deduplicated triangle edges and the same displaced vertex positions as the solid material pass.
- Added project-saved **Wireframe** modes: **Auto** (default), **Always** and **Off**. Auto shows topology only while a Geometry node is focused; Material previews remain uncluttered unless Always is selected.
- Added a small clip-space depth offset and alpha blending to keep topology readable without z-fighting or replacing the shaded surface.
- Kept graph-geometry Material overrides separate from Geometry inspection so Auto does not force wireframe onto finished material previews.
- Corrected the 2D preview source resolver so Geometry outputs cannot fall through to the image evaluator as a fictitious `Image` output.
- Added stale-result guards and successful-geometry error clearing, removing the harmless “WGSL package node has no CPU reference implementation” badge from Geometry Plane.
- Added focused wireframe mode, renderer pipeline, geometry-evaluation and stale-error regressions.
- Graph format remains version 18; existing graphs load unchanged and receive Auto wireframe by default.

## 0.48.0 — Geometry Foundation

- Added a dedicated strongly typed **Geometry** graph value with its own coral sockets/wires and strict incompatibility with image, normal, material and signal values.
- Added **Geometry Plane**, generating centred indexed triangle grids with independent width/height, X/Y subdivisions, three orientations, matching positive-axis normals and 0–1 UVs.
- Added a resolution-independent geometry evaluator separate from the established texture evaluator, GPU backend and image cache paths.
- Added focused Geometry inspection in the 3D Preview using neutral shaded PBR rendering; leaving Geometry focus restores the normal selected viewport primitive.
- Added an optional Geometry input to **Material** so focused materials can preview on procedural graph meshes while all unconnected materials retain existing viewport-mesh behaviour.
- Added **Geometry Output** with Wavefront OBJ export, optional UV/normal records, UV-V flipping and remembered Quick Export destinations.
- Added Geometry support to typed reroutes, loose-wire insertion/search, Send/Receive portals, Graph Input/Output interfaces, linked/embedded Graph Instances and graph persistence. Public Geometry graph inputs are always required because no implicit default mesh exists.
- Disabled terrain-only 3 × 3 replication and terrain-plane assumptions while graph geometry overrides are active, retaining normal material tiling, displacement and viewport controls.
- Added topology/winding/UV/OBJ, typed graph, portal, reroute, graph-instance, 3D focus/restore, Material override and export integration regressions.
- Graph format remains version 18; existing texture/material graphs load unchanged.

## 0.47.0.6 — Crystal 1 Dual-Voronoi Reconstruction

- Replaced the experimental angular-Worley/planar-shading implementation with the compact two-Voronoi construction shown by Material Maker's editable Crystal graph.
- Each independently randomised periodic Voronoi distance field is remapped with `sqrt(1 - A²)`; the relative min/max difference is divided by the larger field and scaled to create dark angular facets with sparse bright junctions.
- Added independent **Scale X** and **Scale Y** controls, matching the established Crystal workflow and allowing intentionally stretched crystal structures.
- Removed the previous Disorder and Facet Sharpness controls because they belonged to the discarded algorithm rather than the corrected construction.
- Added migration from the old scalar Scale parameter to matching Scale X/Y values and removed obsolete stored crystal parameters.
- Added exact construction-contract, parameter-focus, anisotropic-scale, tonal-character, loop and CPU/WGSL regression coverage.
- Graph format remains version 18.

## 0.47.0.5 — Moisture Noise Reconstruction

- Replaced the old strongest-cell moisture construction, which exposed Voronoi-like ownership boundaries and cracked polygonal regions.
- Rebuilt **Moisture Noise** as a layered deposit field: positive and negative sparse Gaussian pools are summed over a broad periodic dampness mask, with independent fine condensation and micro-speckle layers.
- Added focused **Pool Size**, **Fine Detail**, **Patchiness** and **Disorder** controls alongside Scale, Seed, loopable Evolution and the standard finish controls.
- Removed Pattern Size X/Y, Pattern Angle, Softness, Global Opacity and generic disorder-scale/anisotropy/angle controls; they were either tied to the incorrect construction or duplicated the new focused controls.
- Added a gentle isotropic value-noise warp for moisture distribution, preserving organic motion without directional curls.
- Added moisture-specific tonal, high-frequency-detail, parameter-focus, construction-contract, loop and CPU/WGSL regression coverage.
- Graph format remains version 18; older graphs load without migration and obsolete stored moisture parameters are ignored.

## 0.47.0.4 — Anisotropic Noise Reconstruction

- Replaced the previous capsule/strand scatter with a true periodic anisotropic value-noise lattice.
- Added focused **Scale X**, **Scale Y**, **Smoothness** and **Interpolation** controls matching the established directional-strip workflow.
- Removed Lines per Cell, Stretch, Strip Width, Angle, Angle Random, Luminance Random and the generic disorder/output blocks from this node; those controls belonged to a strand generator, not anisotropic noise.
- Smoothness now controls the horizontal fade width, while Interpolation blends linear and Hermite fades; each parameter has a distinct visible role.
- Preserved deterministic Seed, loopable Evolution and native NumPy/WGSL implementations with CPU/GPU parity.
- Added regressions for directional strip character, exact parameter focus, scale response, looping and prevention of the old segment/fractal construction returning.

## 0.47.0.3 — BnW Spots 3 Continuity and Crystal Reconstruction

- Fixed the hidden cell-grid discontinuities in **BnW Spots 3**. Sparse Gaussian deposits now use a 5×5 periodic search and a smooth compact-support fade, so both values and first derivatives remain continuous when the field is converted to a normal map.
- Rebuilt **Crystal 1** as an angular dual-Worley construction with mixed angular distance metrics, two offset fields, deterministic planar facet shading, dark plate boundaries and sparse angular highlights.
- Rebuilt **Crystal 2** as a continuous periodic triangular-fold field with long directional crease planes suited to subtle cloth, marble and crystalline detail. Removed the previous short blurred segment construction.
- Simplified both crystal nodes to one meaningful **Disorder** control. Removed duplicate Disorder labels and the inherited Disorder Scale, Disorder Anisotropy and Disorder Angle controls.
- Added focused gradient-continuity, crystal tonal/frequency character, parameter-label uniqueness, construction-contract and CPU/WGSL regression coverage.
- Confirmed the complete foundational-noise, legacy noise, backend and 163-node application smoke suites.
- Graph format remains version 18; existing graphs load without migration.

## 0.47.0.2 — BnW Spots Reconstruction

- Rebuilt **BnW Spots 1**, **BnW Spots 2** and **BnW Spots 3** around periodic sparse-convolution spot fields instead of FBM, turbulence, ridged and billow combinations.
- Each field now sums randomly positioned, signed Gaussian deposits with variable per-cell impulse counts, random size, amplitude and ellipticity, producing actual black/white specks and deposits rather than another cloudy fractal.
- Gave the family three distinct frequency roles: high-contrast multiscale deposits, broad mottling with dense fine speckles, and softer large/mid-scale spots with restrained grain.
- Retained the existing Scale, Roughness, Fine Grain, Disorder, Seed, Evolution and finish controls so saved graphs remain compatible while rendering through the corrected algorithms.
- Added BnW-specific tonal, frequency and construction regressions that prevent the nodes from falling back to FBM/billow/turbulence formulas.
- Added native WGSL sparse spot evaluation and focused CPU/GPU statistical parity coverage.
- Graph format remains version 18.

## 0.47.0.1 — Cloud Noise Reconstruction

- Rebuilt **Clouds 1**, **Clouds 2** and **Clouds 3** from periodic value-noise octave sums instead of the original gradient-FBM, turbulence and billow combinations.
- Added a cloud-specific, value-noise domain disorder path with gentler displacement so Disorder no longer introduces obvious curled contour loops.
- Gave the three nodes distinct cloud roles: fine layered wisps, broad soft vapour masses and darker dense mottling with fine breakup.
- Kept existing parameters, sockets and graph compatibility; existing graphs load unchanged but render with the corrected cloud constructions.
- Added cloud-character distribution/frequency regressions, explicit safeguards against reintroducing billow/turbulence folds, exact loop checks and focused CPU/WGSL parity validation.
- Graph format remains version 18.

## 0.47.0 — Foundational Noise Expansion

- Added fourteen artist-facing grayscale generators: **Clouds 1/2/3**, **BnW Spots 1/2/3**, **Crystal 1/2**, **Fractal Sum**, **Anisotropic Noise**, **Fibres**, **Messy Fibres**, **Moisture Noise** and **Fur**.
- Built the three Clouds as distinct layered, billowing and turbulent constructions instead of parameter presets of one FBM implementation.
- Added three multiscale BnW Spots algorithms with different coarse, ridge, billow, turbulence and grain relationships.
- Added fine peaked Voronoi facets in Crystal 1 and crossing tapered crease/fold structures with directional control in Crystal 2.
- Added Fractal Sum with Minimum/Maximum Level, Roughness, Global Opacity and domain disorder.
- Added a shared analytic segment foundation for anisotropic strips, orderly fibres, strongly warped/broken messy fibres and tapered fur with an undercoat.
- Added Moisture Noise from positive/negative soft pools and organic low-frequency variation.
- Added deterministic seeds, 0–1 loopable Evolution, Loop Cycles, directional disorder and shared finish controls across the applicable families.
- Added one native branch-based `foundational_noise.wgsl` compute kernel and backend parameter packing for all fourteen nodes; no built-in node requires a CPU fallback during ordinary GPU graph evaluation.
- Added focused quality, distinction, parameter-response, exact-loop, deterministic-seed, shader-contract and CPU/GPU comparison tests. Extended the full backend regression for threshold-sensitive cellular and sub-pixel strand ownership.
- The graph format remains version 18; existing projects require no migration.

## 0.46.5.1 — Directional Lighting

- Added **Directional Lighting** under Filters/Normal & Height. It converts a tangent-space normal map into a grayscale, art-directed baked-lighting mask without requiring a height map or ray traversal.
- Added Light Angle and Light Elevation controls, with Diffuse Power/Brightness, Highlight Power/Brightness, Ambient and Invert shaping.
- Added explicit OpenGL `+Y` and DirectX `-Y` normal convention handling, invalid-vector repair and unit-vector normalisation before lighting.
- Added a native WGSL implementation matching the NumPy reference path. The operation remains a single GPU compute pass with no readback.
- Added a 2D Preview light-direction gizmo: dragging around the guide changes Light Angle, while distance from the centre changes elevation from grazing at the outer ring to overhead at the centre.
- Added focused registry, mask response, diffuse/highlight, inversion, convention parity and gizmo regression coverage.
- Graph format remains version 18; existing projects require no migration.

## 0.46.5 — Splatter Circular

- Added **Splatter Circular**, a dedicated grayscale radial-placement generator rather than adding circular modes to Tile Sampler.
- Supports 1–64 patterns per ring, 1–10 rings, partial arcs, positive/negative ring spacing, per-ring rotation offsets and inward/outward spirals.
- Added deterministic pattern-count, angular, radial, scale, rotation, removal and luminance variation with a shared Random Seed.
- Added four custom grayscale Pattern inputs with Single, Random Inputs, Sequential Around Ring and One Input per Ring distribution.
- Added Face Outward, Face Centre, Tangent and Fixed orientation, plus authored/random/per-ring pattern rotation.
- Added independent pattern width/height, uniform scale, ring and around-ring progression, and chord-derived **Connect Patterns** sizing for continuous rings and bands.
- Added Maximum, Add, Subtract and Replace compositing over a constant or connected grayscale Background input.
- Added Antialiased and Pixel Exact rasterisation for built-in and connected patterns.
- Added a dedicated WGSL compute kernel with bounded angular-neighbour evaluation and a matching deterministic NumPy reference path.
- Added a 2D Preview radial gizmo for Centre, First Ring Radius, outer Ring Spacing and Ring Rotation, with ring/arc/spiral guides and one undo record per drag.
- Added focused regression coverage for registry/backend integration, concentric rings, arcs, spirals, custom input distribution, connected widths, deterministic variation, compositing and gizmo integration.
- Graph format remains version 18; existing projects require no migration.

## 0.46.4 — Transform Quality

- Added one shared CPU resampling module and one shared WGSL include for the transform family, replacing subtly different pixel-centre, interpolation, boundary and typed-image rules that had accumulated across older nodes.
- Added selectable **Automatic**, **Nearest**, **Bilinear** and Mitchell-Netravali **Bicubic** filtering to Transform 2D, Tile, Offset, Rotate, Scale, Crop, Auto Crop, Perspective Transform, Clone Patch, Atlas Splitter and Normal Transform, with the same choices carried into material-aware crop operations.
- Added adaptive minification to Automatic filtering. Enlargement and ordinary sampling use cubic reconstruction; shrinking uses a broader local sampling footprint so checkerboards, thin lines and procedural detail alias less severely.
- Standardised **Transparent**, **Clamp**, **Seamless / Wrap** and **Mirror** boundary behaviour. Fixed negative-coordinate wrapping in WGSL and preserved legacy Tile/Wrap project values through graph migration.
- Added premultiplied-alpha colour resampling to prevent hidden RGB in transparent pixels from contaminating rotated and scaled cutout edges. Grayscale/height values remain numeric, while normal/vector samples are decoded and renormalised after interpolation.
- Made identity transforms and integer-pixel offsets exact fast paths, avoiding accidental blur or half-pixel movement even when a high-quality filter is selected. Mirror now uses exact array reversal in the CPU reference path.
- Corrected Transform 2D, Rotate, Normal Transform and Clone Patch to rotate in physical pixel space. Rectangular documents now preserve geometric distance and circular patches instead of rotating in aspect-distorted normalised UV space. Updated the 2D Preview transform gizmo and axis handles to match those physical-pixel semantics.
- Added a distinct **Safe Transform** node with periodic-only sampling, integer tile count, manual or deterministic random pixel-snapped offsets, integer-lattice tile-safe rotation, X/Y symmetry, selectable filtering and automatic/manual detail prefiltering. It guarantees periodic output by design rather than expanding Transform 2D into a super-node.
- Added focused regressions for exact identity/pixel moves, rectangular rotation, premultiplied alpha, adaptive minification, all boundary modes, vector length, shader include consistency, Safe Transform seam continuity and migration, plus non-square CPU/WGSL comparisons.
- The graph format remains version 18; existing projects need no manual migration.

## 0.46.3.1 — Normal Vector Rotation

- Added **Normal Vector Rotation** under Filters/Normal & Height. It rotates the decoded tangent-space XY vector around local +Z without moving, sampling or transforming the texture coordinates.
- Added an animatable angle-dial parameter with arbitrary multi-turn values and explicit OpenGL `+Y` / DirectX `-Y` handling.
- Added NumPy and native WGSL implementations with invalid-vector repair and output renormalisation.
- Added focused spatial-ownership, 90-degree direction, flat-normal, convention-parity and CPU/GPU regression coverage.
- The graph format remains version 18; existing projects need no migration.

## 0.46.3 — Normal and Height Processing

- Added **Normal Blend** for maskable tangent-space crossfades with automatic unit-vector repair and OpenGL/DirectX convention handling.
- Added **Normal Combine** with Reoriented Normal Mapping (RNM), Whiteout and UDN methods, independent base/detail strength, overall amount and an optional mask. A flat detail normal is an exact identity in the RNM path.
- Added **Normal Normalize** to repair non-unit, zero or malformed tangent vectors and **Normal Invert** to flip the encoded X, Y and/or Z axes safely.
- Added **Normal Transform** with offset, uniform scale, independent X/Y stretch, rotation and tiling. Image rotation also rotates tangent-space XY directions before renormalisation, avoiding the incorrect shading produced by treating a normal map as ordinary RGB. The node uses the shared Transform 2D Preview gizmo for move, corner scale, side stretch and rotation.
- Added **Normal to Height** using a global Frankot-Chellappa/Poisson integration with low/high-frequency balance, Height Intensity, output normalisation, inversion and normal-convention controls. The node performs one deliberate whole-image GPU readback for the FFT solve, then uploads the grayscale result so downstream evaluation can remain GPU-resident.
- Added **Bent Normal** from Height. It traces distributed hemisphere visibility through the 2.5-D surface, averages unoccluded ray directions, applies two height-aware denoise passes and outputs a unit tangent-space vector. Interactive edits use a reduced ray/step workload before the authored quality resolves.
- Added **RT Shadows** from Height with light angle/elevation, height scale, maximum distance, softness, sample count, bias, shadow strength, Seamless/Wrap or Clamp boundaries and inversion. It uses software ray marching in WGSL and does not require hardware ray-tracing extensions.
- Added flat-normal defaults for unconnected vector inputs, white defaults for optional normal masks, native WGSL kernels for the normal utilities/transform/shadows, specialised GPU multi-pass execution for Bent Normal and the CPU-assisted global solve for Normal to Height.
- Added normal-composition identity tests, unit-vector repair, axis/convention parity, tangent-aware rotation, normal-to-height reconstruction, bent-direction, directional-shadow, 2D Preview gizmo, CPU/GPU and full backend/smoke regressions.

## 0.46.2.2 — Perspective Direction and Transform 2D Stretching

- Corrected Perspective Transform from source-selection rectification to destination-quad warping. The authored four-corner gizmo now describes where the complete source image lands in the output, so pinching the top corners narrows the top as displayed.
- Perspective corner handles are always active over the node result and no longer require the Edit source preview toggle.
- Kept Crop's source-preview toggle as **Edit crop source**, because Crop parameters describe source-space bounds before the selected region is expanded to the complete output.
- Added independent Scale X and Scale Y parameters to Transform 2D while retaining the existing Uniform Scale for compatibility and proportional resizing.
- Added four side handles to the Transform 2D preview gizmo. Corners adjust Uniform Scale; side handles stretch/squash one axis; move and rotation controls are unchanged.
- Updated CPU and WGSL Transform 2D implementations and backend packing for non-uniform scale.
- Fixed transparent greyscale Perspective Transform output so CPU and GPU paths agree outside the destination quad.
- Added perspective-direction, axis-stretch, gizmo, CPU/GPU parity, graph compatibility and smoke regressions.

## 0.46.2.1 — Make It Tile Cut Masks and 2D Preview Gizmos

- Rebuilt **Make It Tile Photo** around the photographic cut-mask construction used by dedicated scan tools. The original source remains centred and untouched away from the borders; half-period horizontal, vertical and diagonal wrapped copies are revealed only inside independently authored edge transitions.
- Replaced Seam Width, Seam Blur and Detail Preservation with per-axis **Mask Size**, **Mask Precision** and **Mask Warping**. Size controls how far the replacement reaches inward, Precision changes the cut from broad/soft to narrow/sharp, and deterministic multi-frequency periodic warping breaks up straight transition lines without introducing animation noise or a new seed dependency.
- Updated **Material Make It Tile** to use the same centred-source construction lazily for the requested material channel. Greyscale remains numeric, colour stays in linear graph space and normal/vector outputs are renormalised after blending.
- Added migration for graphs saved by the initial 0.46.2 Make It Tile implementation. Legacy Seam Width and Detail Preservation values are transferred to the new horizontal/vertical size and precision controls, and obsolete keys are removed on load.
- Added a reusable **2D Preview gizmo framework** with node-aware drawing, hit testing, parameter clamping, interactive draft evaluation and one undo command per drag. Gizmos remain aligned to the central tile in Tile 3×3 mode and coexist with wheel zoom and canvas panning.
- Added direct preview manipulation for **Transform 2D** (move, uniform scale and rotation), **Clone Patch** (source, target and radius), **Perspective Transform** and **Crop** (four source-space corner handles through the new Edit source toggle), plus automatic position handles for nodes exposing `center_x` and `center_y`.
- Added source-preview routing for Perspective Transform and Crop while Edit source is active, allowing handles to be adjusted against the connected unprocessed image instead of the already rectified/cropped result.
- Added focused CPU/WGSL seam-construction tests, centre-preservation and warped-mask regressions, standalone preview-gizmo interaction tests, MainWindow undo/render integration coverage and full backend/smoke validation.

## 0.46.2 — Photogrammetry and Scan Preparation

- Added **Make It Tile Photo** for converting a non-tiling photograph into a seamless texture without changing the graph canvas. It half-period shifts selected axes so the original borders become interior seams, reconstructs low-frequency continuity with a wrapped Gaussian field and confines detail suppression to an authored seam band. Horizontal and vertical repair can be controlled independently.
- Added **Lighting Equalisation** for removing broad illumination and colour cast while retaining local scan detail. Colour sources are corrected in display-sRGB using either luminance-preserving or per-channel RGB handling, greyscale remains numeric, Clamp/Wrap boundaries are supported and normal/vector data passes through unchanged.
- Added **Clone Patch** with normalised source and destination positions, radius, feather, opacity, rotation, scale, Clamp/Wrap source sampling and an optional greyscale destination Mask. Colour, greyscale and normal/vector sources retain their semantic type, with vectors renormalised after blending.
- Added **Perspective Transform** with four authored source corners, true projective homography, Nearest/Bilinear filtering and Transparent/Clamp outside handling. It rectifies photographed quadrilaterals rather than approximating them with an affine crop.
- Added **Atlas Splitter** based on connected-component detection rather than a fixed atlas grid. It supports luminance, alpha or an explicit Mask, minimum-area filtering, 4/8 connectivity, reading/spatial/area ordering, selection index, padding, fit/fill/auto framing and optional component isolation. Irregularly sized and spaced atlas elements are supported.
- Added **Material Crop** and **Material Make It Tile**. Both inherit material metadata and lazily transform only the requested authored channel through Material Channels, 3D Preview or Texture Set Output. Normal channels are decoded/resampled/reconstructed and renormalised rather than treated as ordinary colour.
- Added native WGSL paths for Make It Tile Photo, Lighting Equalisation, Clone Patch and Perspective Transform. Atlas Splitter intentionally performs one global component-statistics readback and uploads the selected result; ordinary graph caching avoids repeating unchanged detection work.
- Added focused scan-workflow tests covering seam continuity, lighting-gradient removal, clone placement, projective corner mapping, irregular atlas selection, CPU/GPU agreement, material-setting inheritance, lazy material-channel presence and unit-length normal preservation.
- Updated the stale graph-workflow serialization assertion to the already-current graph format 18. The graph format itself is unchanged in this release.

## 0.46.1 — Immediate Essential Filters

- Added **Histogram Select** with Position, Range and Contrast controls plus the shared live histogram editor. Unlike Histogram Scan, it isolates a centred tonal band rather than selecting everything above or below a threshold.
- Added type-preserving **Highpass** for greyscale and colour textures. Colour detail is separated in display-sRGB and returned to the graph's linear-light colour space, so its visible 50% grey remains neutral when combined with the corrected Overlay blend mode. Radius uses resolution-independent pixels, and Boundary can clamp photographs or wrap tileable textures.
- Added **Edge Detect** with Scharr and Sobel operators, resolution-independent Width, Intensity and Invert. Colour edges are measured perceptually, normal/vector edges use decoded vector differences, and the node emits a greyscale mask.
- Added type-preserving **FXAA** with Low/Medium/High search quality, absolute and relative edge thresholds, Subpixel strength and optional alpha preservation. Colour filtering occurs in display-sRGB; normal/vector inputs are decoded, filtered and renormalised instead of being treated as ordinary RGB.
- Added type-preserving **Crop** with normalised Left, Right, Top and Bottom bounds plus Nearest/Bilinear sampling. Reversed bounds are accepted, rectangular documents are handled correctly and sampled normal/vector outputs are renormalised.
- Added **Auto Crop** with luminance or alpha detection, Threshold, Padding, Auto/Nearest/Bilinear filtering and four distinct framing modes: Crop Auto centres content without resizing it, Crop Square extracts the smallest enclosing square, Fit preserves aspect ratio while scaling, and Fill stretches the detected bounds. Content-bound detection performs one global statistics readback when required; the final crop/resample remains a GPU pass and normal graph caching prevents unchanged branches from being recomputed.
- Extended the shared adjustment histogram with a dedicated three-guide Histogram Select presentation, keeping its selected centre and band edges visible while editing.
- Added native WGSL paths for all six nodes, multi-pass GPU Highpass, CPU reference implementations, custom semantic tests, colour/vector handling regressions, crop/aspect/boundary tests and full backend validation.
- Corrected the separable GPU Gaussian helper to release its horizontal intermediate after the vertical pass, reducing temporary texture retention for Blur and Highpass workloads.

## 0.46.0.4 — Ray-Traced Ambient Occlusion

- Added **Ambient Occlusion (RTAO)** as a separate high-quality height-map filter alongside the faster HBAO node. It performs software ray tracing in a WGSL compute shader and does not require hardware ray-tracing extensions or RT cores.
- Added Height Scale, integer Samples (4–64), Distribution (Uniform, Cosine Weighted or Horizon Weighted), Maximum Distance, Spread Angle, Denoise, Boundary and Invert controls. A Spread Angle of 1 covers the complete upper hemisphere.
- Added deterministic per-pixel hemisphere rotation and low-discrepancy ray azimuths so repeated geometry produces stochastic noise rather than fixed spokes. Rays march with near-surface-biased steps, stop at their first blocker and use a gentle distance cutoff to avoid a hard Maximum Distance ring.
- Reused the slope-limited local tangent from the refined HBAO implementation, preventing smooth ramps from self-occluding and preserving the white top silhouettes of hard height steps.
- Added a two-pass height-aware GPU denoiser that removes stochastic ray noise without bleeding dark lower-surface AO onto raised surfaces. Denoise can be disabled for inspection or downstream custom filtering.
- Added a reduced interactive path capped at six rays and eight march steps. Settled and final evaluation restore the authored sample count, with internally increasing step counts for 8, 16, 32 and 64-ray workloads.
- Added matching NumPy reference behaviour, exact CPU/WGSL parity coverage, flat/ramp/step/contact/inversion/distribution regressions and full built-in backend validation.

## 0.46.0.3 — Blend colour-space correction

- Corrected the Blend node applying standard artistic colour formulae directly to linear-light graph RGB. Colour inputs are now converted to display-sRGB for the blend calculation and converted back to linear light afterward, while the graph remains linear outside the node.
- Restored exact visible 50% grey neutrality for Overlay, Soft Light, Hard Light and Add Sub / Linear Light. A default black-to-white Gradient Map sampled at 0.5 no longer darkens or brightens the Background.
- Preserved raw numeric blend mathematics for greyscale and vector/data branches. Mixed colour/greyscale blends convert scalar values only when producing a colour result, so visible grey values remain intuitive without gamma-transforming technical maps.
- Audited all 16 modes on the NumPy and WGSL paths, including correct Overlay/Hard Light branch ownership, W3C Soft Light, finite Divide/Colour Dodge/Colour Burn boundaries, opacity-mask multiplication and alpha interpolation.
- Added CPU/GPU regressions for perceptual colour reference values, raw greyscale reference values, neutral contrast modes and mixed semantic input handling.

## 0.46.0.2 — HBAO edge-aware reconstruction

- Replaced the discontinuity-sensitive centred HBAO tangent estimate with a slope-limited minmod gradient. Genuine ramps still cancel their own planar slope, while hard Tile Sampler silhouettes no longer invent an opposite-facing tangent and produce a clipped black contour.
- Added a two-pass joint bilateral reconstruction stage after horizon sampling. It smooths the sparse ring contributions into a continuous ambient-visibility field while using the source Height map to keep ground occlusion from bleeding onto raised surfaces.
- Tied the reconstruction width to the authored AO Radius and texture resolution, with a bounded reduced-cost interactive width. The HBAO node remains GPU-resident through raw evaluation and both reconstruction passes.
- Added focused regressions for white upper silhouettes, non-clipped contact shading, monotonic halo falloff, circular smoothness and CPU/WGSL parity through the new multi-pass path.

## 0.46.0 — Surface Analysis

- Renamed the existing height-map **Curvature** node to **Height Curvature** without changing its `terrain.curvature` type ID, saved parameters, output or compatibility with older graphs. Its Signed mode now has explicit regression coverage for exact 50% grey on flat height fields.
- Added normal-derived **Curvature** with a sharp, resolution-aware signed response, 0–10 Intensity and OpenGL/DirectX green-channel handling.
- Added **Curvature Sobel** with a broader hard-edge Sobel response intended for stylised highlights and edge darkening. Its flat result is exactly 50% grey so Overlay leaves the base colour unchanged.
- Added **Curvature Smooth** with a fixed multi-scale normal analysis and separate Curvature, Convexity and Concavity output sockets.
- Added **Ambient Occlusion (HBAO)** for fast non-raytraced AO generation from height maps. It searches horizons relative to the local surface tangent, supports tileable wrap or clamped boundaries, 4/8/16-direction quality, height depth, radius, occlusion strength and inversion.
- Added an interactive HBAO draft path that temporarily limits the search to four directions and two radial steps while dragging, then restores the authored quality for the settled preview/final result.
- Added matching NumPy reference and WGSL implementations for all new nodes, neutral-normal defaults for unconnected curvature inputs, backend CPU/GPU parity coverage and focused surface-analysis regressions.

## 0.45.3 — Viewport-Owned Displacement

- Moved Displacement Amount, Height Midpoint and Invert Height out of Material and Material Override nodes into a dedicated **Displacement** group in 3D Viewport Settings. Height remains an authored material channel; how strongly the inspection mesh uses it is now project-owned viewport presentation state.
- Added a renderer-uniform-only displacement update path. Dragging Amount or Midpoint and toggling inversion now reuse the already resolved/uploaded Height texture, skip graph evaluation, skip GPU texture upload, skip mesh/environment rebuilding and request only a new viewport draw.
- Made viewport displacement settings take precedence over any legacy material metadata inside the renderer, preventing old hidden parameters from reasserting per-material displacement behaviour.
- Upgraded the graph format to version 18. Older graphs migrate the active material settings source's displacement values into `viewport_3d`, remove obsolete values from every Material/Material Override node and retain their previous visible displacement after opening.
- Updated the built-in starter graph to use viewport displacement while keeping normal strength as authored material behaviour.
- Added focused regression coverage for node contracts, viewport clamping/persistence, legacy Material Blend migration, unchanged material request keys and the direct renderer-uniform update path.

## 0.45.2 — Sharing and Packages

- Added the `.vfxexport` shareable export-template format with versioned JSON validation, stable Template IDs, author/version/engine metadata and safe import/export.
- Expanded the Export Template Editor with Description, Author, Template Version and Engine/Purpose metadata, plus Import, Export and direct User Library installation actions.
- Added a managed User Export Templates library with install, update, side-by-side, remove, refresh and reveal-folder workflows.
- Installed templates appear as reusable starting points in the Export Template Editor and as selectable Multi-Target Export layouts; selected user templates are snapshotted into graph-local targets so removing the global copy cannot break existing graphs.
- `.vfxpackage` export can include graph-local templates as independently installable `.vfxexport` files while retaining embedded graph fallbacks.
- Package inspection validates every included template and displays its metadata; package installation can install included templates with per-template update, side-by-side or skip conflict handling.
- `.vfxexport` files supplied on the command line or through desktop association are treated as installable export templates rather than graphs.
- Preserved compatibility with 0.45.0/0.45.1 custom templates, export profiles, Quick Export and packages without an export-template inventory.

## 0.45.1 — Multi-Target Export

- Expanded **Export Outputs** with graph-local profile sets and editable production targets. One profile can publish every selected Texture Set Output through several templates at once while Single Image Outputs remain one explicit file each.
- Added target-level template, subfolder, resolution, normal convention, image format, colour depth, scalar depth and Height-format overrides. The node remains the semantic source and fallback; targets only override what differs for a destination.
- Added profile and target creation, duplication, renaming, enable/disable and removal directly in the export window. Changes are saved inside the `.vfxgraph`, survive self-contained and `.vfxpackage` workflows, and are discarded when the export dialogue is cancelled.
- Added dynamic multi-target preflight with resolved relative folders, per-target files, formats, depths, colour handling, resolutions, template warnings and cross-target filename collision detection.
- Added `{graph}`, `{version}`, `{profile}` and `{target}` naming variables alongside `{set}`, `{map}`, `{output}`, `{width}` and `{height}`. Target folders support the graph/profile/target/output tokens and are constrained to safe relative paths.
- Reworked export execution to cache each evaluated graph source by output and resolution for the duration of the publish. Several targets at the same resolution now reuse one evaluation instead of repeating expensive erosion, simulation or nested-graph work.
- Quick Export now remembers the complete profile-set snapshot as well as destination, collision and folder-opening preferences. Its Inspector summary identifies the remembered profile, and **Configure Export…** reopens the full target setup.
- Bumped the readable graph format to version 17 and added focused profile-model, multi-target planning, dynamic UI, persistence, nested-path and shared-evaluation regression tests.

## 0.45.0.1 — Scalar Export Fix

- Fixed one-channel template outputs such as Height, AO, Roughness, Metallic and Specular failing during PNG/R16 preparation with an out-of-bounds channel error.
- Export preparation now handles grayscale, grayscale-plus-alpha, RGB and RGBA arrays consistently, including safe RGB/RGBA expansion and opaque alpha defaults.
- Added regression coverage for one-channel template output writing across the built-in texture-set templates.

## 0.45.0 — Export Template Foundation

- Rebuilt Texture Set Output presets on one reusable export-template model. Generic PBR Separate, Unreal ORM, Unity HDRP Mask Map, Godot ORM and VFX RGBA Masks now use the same file/channel definition path as custom layouts.
- Added an artist-facing Export Template Editor for graph-local custom templates. Authors can add, duplicate and remove output files; control each file's name, format, bit depth, channel count and colour handling; and assign semantic material sources, constants and inversion independently to R, G, B and A.
- Added automatic Normal Green/Y handling so template bindings follow the Texture Set Output OpenGL or DirectX normal convention without destructive graph changes.
- Added exact semantic defaults for missing packed channels, preserving AO 1, Roughness 0.5, Metallic 0, flat normals and the other material defaults whenever another assigned source keeps the file active.
- Expanded Export Outputs with a selected-output Planned Files preflight showing resolved filenames, format, depth, channel layout, colour handling, resolution, duplicate-path warnings and template warnings before evaluation begins.
- Added graph-save persistence, undo/redo and legacy Separate PBR Maps migration for custom template data. Graph-local templates automatically travel inside ordinary `.vfxgraph`, self-contained graphs and `.vfxpackage` archives.
- Added focused model, packing, migration, offscreen editor and preflight regression coverage.

## 0.44.3.1 — Package image-source preservation

- Added an export preflight option to **Include source image files in the package**, enabled by default.
- `.vfxpackage` archives now preserve exact imported image bytes under `resources/images/` while retaining embedded fallback copies in the entry graph for reliable temporary opening.
- Added manifest inventory and integrity validation for packaged image sources, including deterministic de-duplication when several Image Input nodes use identical bytes.
- Added packaged-source provenance to Image Input nodes and a **Use Included Package Source** context action after extracting or installing a package.
- Package Details and completion summaries now report how many separate image source files were included.

## 0.44.3 — VFX package archives and managed installation

- Added **Export VFX Package…** to File and Graph Properties. `.vfxpackage` files are standard ZIP-compatible archives internally, with a versioned `package.vfxmanifest`, stable Asset ID, entry graph, metadata, thumbnail, complete file inventory and SHA-256 integrity hashes.
- Package export reuses the self-contained graph pipeline, embedding nested graphs and images without changing the source project. External custom WGSL node packages used anywhere in the nested graph are bundled automatically; built-in node packages are not duplicated.
- Added a validated Package Details workflow with **Open Temporarily**, **Extract as Editable Project…** and **Install to Asset Library**. Temporary opening creates a clean unsaved graph, so Save always becomes an explicit editable copy rather than writing into a transient extraction folder.
- Added managed package installation under the Graph Asset library, immediate Node Library refresh, stable-ID update detection, Update Installed and Install Side by Side choices, and automatic installation of bundled custom-node dependencies. Extracted editable projects register their bundled custom-node folder as a live project library.
- Added strict archive safety checks for path traversal, absolute/drive paths, symbolic links, encryption, duplicate members, unmanifested files, size limits, unsupported format versions, missing entry graphs and hash/size mismatches. Extraction writes only validated, declared files through a staging folder.
- Added `.vfxpackage` support to the normal Open dialogue and command-line startup, plus focused pure-format and offscreen UI regression coverage.

## 0.44.2.1 — Shared library discovery and refresh safety

- Made folders registered through **Library → Custom Node & Graph Asset Libraries…** discover reusable `.vfxgraph` assets as well as declarative custom node packages. Graph assets now appear immediately without restarting, respect the library Enabled toggle, and remain searchable by metadata and tags.
- Clarified the shared-library dialog so authors know one folder may contain custom node packages, graph assets, or both.
- Prevented asset-only library refreshes from rebinding live graph node definitions when no custom node package actually changed.
- Made genuine custom-node hot reloads preserve every surviving outgoing connection by stable output socket name, and skip untouched built-in definitions entirely. This fixes the temporary crossed/disconnected graph state that could appear after adding or rescanning a library folder.
- Added focused regression coverage for shared-folder discovery, immediate search, enabled-state handling, non-mutating asset-only refreshes, and connection-safe definition rebinding.

## 0.44.2 — Graph thumbnails and library polish

- Added persistent 256 × 256 graph asset thumbnails stored as compact PNG data inside `.vfxgraph` metadata.
- Added a Graph Properties **Thumbnail** section with Capture 2D, Capture 3D, Import Image and Clear actions; capture is intentionally tied to the active graph so an inactive Explorer selection cannot accidentally receive another graph's preview.
- Added an evaluation-free Graph Asset details card to Node Library showing thumbnail, description, author, version, tags, published outputs, source path and validation state.
- Expanded Node Library and add-node graph-asset search to include tags, author, asset version and published output names.
- Made invalid or incomplete `.vfxgraph` files visible under **Graph Assets / Problems** rather than silently omitting them. Non-blocking interface warnings remain insertable and receive a warning marker.
- Added Open Source Graph, Validate Asset, Edit Thumbnail in Inspector and Reveal Source library actions, plus an explicit library refresh control.
- Added focused regression coverage for thumbnail encoding/metadata persistence, 2D capture, rich search, details presentation and visible invalid assets.

## 0.44.1 — Self-contained graphs and recovery

- Added **Export Self-Contained Graph…** to File and Graph Properties. It recursively embeds linked, embedded and live-session Graph Instances plus external Image Inputs into one portable `.vfxgraph`.
- Self-contained export uses current open child revisions, falls back to last-known-good graph caches when linked sources are missing or unreadable, resolves relative resources against their owning graph and validates the written copy before completion.
- Kept export non-destructive: it refuses to overwrite the active source graph and never changes source node modes or paths.
- Added Graph Instance recovery actions for making the cached revision local, restoring it as a validated self-contained `.vfxgraph`, and relinking all matching instances by stable asset identity.
- Added Image Input recovery actions for relinking one or all matching paths, embedding the current image locally, and restoring stored embedded bytes as an external file.
- Expanded Graph Instance Inspector diagnostics with recovery-cache availability and original-source provenance.
- Added Graph Properties **Portability & Recovery** counts and focused regression coverage for recursive embedding, post-source deletion evaluation, cache recovery, matching relinks and image restoration.

## 0.44.0 — Graph Inspector foundation

- Renamed the **Parameters** dock to **Inspector** and made it contextual: nodes and groups show their existing parameter editors, while graphs show document-level properties.
- Added single-click Graph Explorer inspection without changing the active canvas; double-click still activates the graph and now opens its graph properties first.
- Clicking empty canvas space or pressing Escape clears node focus and returns the Inspector to the active graph.
- Added persistent graph metadata: stable Asset ID, name, description, category, tags, author, asset version and originating application version.
- Added a live **Published Interface** summary for Graph Inputs, Graph Outputs, exposed parameters and the primary output, including a warning when no Graph Output exists.
- Preserved graph identity through Save, Save As, Save a Copy, duplication, autosave recovery, embedded graph editing and nested open-graph serialization.
- Added focused regression coverage for graph/node inspection, Graph Explorer selection behaviour, metadata serialization and live interface refresh.

## 0.43.10 — Rounded preview-mesh refinement

- Rebuilt **Rounded Cylinder** as one continuous surface with shallow elliptical domes and no planar top/bottom cap discs.
- Resampled the cylinder profile by arc length and matched wall-ring spacing to the dome spacing, giving displacement a much more even vertex distribution over the whole mesh.
- Changed Rounded Cylinder U coordinates to span two repeats around the circumference, reducing the stretched appearance of square and directional materials.
- Increased Rounded Cube tessellation at every Low/Medium/High/Ultra quality level for finer displacement while preserving its existing rounded-box shape and UV layout.
- Changed **Material Tiling** from a fractional float control to a whole-number `1–32×` repeat count. Loaded fractional values are rounded and clamped safely.
- Added topology, UV-range, winding, edge-distribution and integer-setting regressions for the refined 3D preview workflow.

## 0.43.9 — 3D preview mesh and lighting polish

- Added built-in **Rounded Cube** and **Rounded Cylinder** preview meshes with UVs, smooth rounded transitions and mesh-specific Low/Medium/High/Ultra topology.
- Added **Material Tiling** to the Mesh section of 3D Preview settings. It repeats every material map through mesh UVs without duplicating the mesh and also applies consistently to normal, height/displacement, opacity and debug views.
- Kept Terrain Plane **1 × 1 / 3 × 3** geometry tiling separate from material UV tiling.
- Reduced the environment intensity of the Studio, Soft, Dramatic and Flat lighting presets to practical inspection levels while retaining their original environments, sun directions and overall character.
- Extended 3D renderer uniforms, shader coverage, viewport persistence and focused tests for the new UV-tiling control and rounded meshes.
- The supplied external `.gltf` descriptions referenced missing `.bin` buffers, so this release uses equivalent procedural built-in meshes rather than embedding incomplete files.

## 0.43.8 — Tile Sampler luminance cleanup

- Removed **Tile Value** from Tile Sampler completely, including the hidden legacy compatibility controls and the old clipped symmetric-random evaluation path.
- Made **Luminance Random** use one artist-facing model everywhere: `0` leaves the tile multiplier at exactly `1`, `0.5` produces stable uniform values from `0.5–1`, and `1` produces stable uniform values across `0–1`.
- Fixed newly inserted or loaded pre-release Tile Samplers accidentally entering the old Tile Value model when a parameter dictionary was supplied by the editor.
- Stripped stale `tile_value` and `_legacy_luminance_model` fields while opening older pre-release graphs instead of preserving a second behaviour path.
- Kept connected Pattern Input luminance intact at zero randomness; random luminance scales the complete authored tile rather than replacing its internal gradient.
- Updated CPU, WGSL, backend parameter packing, graph schema and focused regressions to enforce the same luminance range.

## 0.43.7 — Tile Sampler layout and value controls

- Removed the misleading **None** entry from Tile Sampler Offset Mode. New nodes always expose a meaningful row/column mode, while an Offset Amount of zero retains the ordinary aligned grid.
- Changed **Row / Column Offset** to the clearer **Offset Amount** with an artist-friendly 0–1 tile-cell range. `0.5` produces classic half-tile brick staggering; continuous modes advance cumulatively and remain seamless.
- Migrated older signed offsets without changing their appearance. Negative values are converted to their equivalent wrapped 0–1 amount, and legacy `None` layouts become a zero-amount row offset.
- Added **Layout Mask** options for All Tiles, Checker, Alternate Rows and Alternate Columns, plus Invert Layout Mask. Layout selection combines predictably with Random Removal and the external Mask Map.
- Renamed **Mask Random** to **Random Removal** without changing its saved parameter identity or behaviour.
- Reworked **Luminance Random** for new Tile Samplers: zero keeps every tile white, while one distributes stable per-tile values uniformly across the complete 0–1 range without clipping bias.
- Removed Tile Value from the normal new-node interface. Older graphs retain their exact clipped Tile Value + random model and expose **Tile Value (Legacy)** only where required for compatibility.
- Fixed negative-neighbour modulo in the WGSL Tile Sampler path on software Vulkan/OpenGL drivers, restoring CPU/GPU parity for staggered tiles crossing seamless texture boundaries.
- Added CPU/GPU regressions for offset modes, seam wrapping, layout masks, inverted selection, unbiased luminance and legacy graph migration.

## 0.43.6 — Filtered Tile Sampler Pattern Inputs

- Extended Tile Sampler **Edge Rasterisation** to connected Pattern Inputs instead of applying it only to built-in analytic shapes.
- **Pixel Exact** now point-samples custom pattern texels, preserving a deliberately hard nearest-neighbour result.
- **Antialiased** now estimates the transformed destination-pixel footprint for each rotated, scaled and mirrored tile. Magnified patterns retain bilinear reconstruction, while minified patterns use a bounded five-tap quincunx coverage filter so thin grass blades, fibres and debris survive sub-pixel placement without global blur.
- Kept the filtering local to Tile Sampler placement; the source Pattern Input texture is not modified and downstream nodes still receive the authored result.
- Added matching NumPy and WGSL implementations, including custom-pattern CPU/GPU parity, binary Pixel Exact coverage and fractional Antialiased coverage regressions.

## 0.43.5 — Tile Sampler rasterisation and predictable re-export

- Fixed the GPU Tile Sampler path re-applying a one-pixel antialiasing footprint after the CPU/backend had already resolved **Antialiased** versus **Pixel Exact**. Built-in Square, Disc, Brick, Capsule, Bell, Diamond, Hexagon and Triangle patterns now visibly honour the selected mode in CPU and GPU evaluation.
- Changed Export Outputs and first-time Quick Export to default to **Replace existing**, so exporting the same Single Image Output or Texture Set Output again updates its established files instead of creating `_2`, `_3`, and later copies.
- Migrated pre-0.43.5 Quick Export configurations that inherited the old numeric-suffix default to the new replace behaviour.
- Added same-batch filename conflict detection. When two selected output nodes genuinely target the same filename, export warns before proceeding and applies stable node-specific suffixes only to the conflicting files. Repeating that batch overwrites the same safe paths rather than generating an unbounded numeric sequence.
- Retained **Add numeric suffix** and **Skip existing** as explicit choices for workflows that need them.
- Added CPU/GPU Tile Sampler rasterisation coverage, overwrite-repeat tests, deterministic conflict-name tests and Quick Export default regressions.

## 0.43.4 — Antialiased geometry, truthful zoom and Single Image Quick Export

- Added **Edge Rasterisation** to Shape, Polygon, Polygon Burst and Tile Sampler. New nodes default to Antialiased, storing approximately one pixel of fractional coverage around geometrically hard edges while keeping Edge Softness reserved for deliberate wider feathering.
- Added Pixel Exact for binary low-resolution masks and pixel-art workflows. Existing 0.43.3-and-earlier graphs without rasterisation metadata are migrated to Pixel Exact so saved output does not silently change.
- Added **Geometric rasterisation** to Document Settings as the default applied to newly created analytic geometry nodes.
- Kept CPU and WGSL paths aligned for antialiased and pixel-exact silhouettes, including Tile Sampler built-in shapes.
- Added a true **1:1** 2D Preview button. One texture pixel now maps to one screen pixel and the zoom readout reports the actual display scale.
- Corrected **Fit** zoom reporting: fitting a small texture can now correctly display values above 100%, while fitting a large texture reports its true minification percentage.
- Added the Texture Set-style **Quick Export** group to Single Image Output, including first-use setup, remembered destination, collision policy and open-folder behaviour.
- Added rasterisation migration, zoom, Quick Export and CPU/GPU regression coverage.

## 0.43.3 — Preview/export parity and linear-data metadata

- Removed the hidden 1024-pixel 2D display/readback ceiling. The 2D Preview now retains the complete configured Preview Max result as compact RGBA8 pixels, so a 2048 preview can be inspected at genuine 2048 detail.
- Changed canvas presentation to filtered minification when a high-resolution texture is fitted smaller than one screen pixel per texel, while retaining nearest-neighbour enlargement for low-resolution textures and pixel inspection.
- Fixed linear PNG exports writing a `gAMA=1.0` chunk. Colour-managed viewers interpreted the mathematically linear tag as display colour and made masks, height maps, packed data and normal maps appear much brighter than the numeric values shown in VFX Texture Lab.
- Linear/data PNGs are now intentionally untagged and preserve their numeric bytes. Only Colour/sRGB outputs receive the sRGB transfer and `sRGB` metadata chunk.
- Audited Single Image Output and Texture Set Output presets: Base Colour and Emissive remain sRGB; Greyscale, Vector/Normal, Height, AO, Roughness, Metallic, Specular, Opacity and packed maps remain linear numeric data.
- Added preview/export parity, PNG metadata, exact preview-resolution and filtered-minification regressions.

## 0.43.2 — Pixel-accurate preview and primitive edges

- Changed 2D Preview Fit, wheel zoom, pan and Tile 3×3 presentation to nearest-neighbour image sampling, preserving exact texels instead of introducing bilinear blur.
- Kept Copy and Save image tied to the underlying graph result; the display interpolation change does not resample exported textures.
- Changed the defaults for new Shape, Polygon and Polygon Burst nodes to **Edge Softness = 0.0**, matching hard raster primitive behaviour at low and high resolutions.
- Added exact zero-softness branches to the NumPy and WGSL silhouette profiles so zero means binary coverage rather than an epsilon-width smooth transition.
- Added the same exact hard-boundary handling to Polygon Burst while preserving its intentional Radial and Angular interior gradients.
- Left Tile Sampler and transform/resampling-node filtering unchanged; artists can still raise Edge Softness on source shapes when an antialiased mask is desired.
- Added focused regression coverage across multiple primitive resolutions, explicit soft edges and enlarged nearest-neighbour 2D presentation.

## 0.43.1 — Compatible-node search clarity

- Made loose-wire connection search visibly identify its source or destination node, socket name and data type instead of looking like the ordinary all-node search.
- Added an explicit explanation that compatible search only shows nodes which can complete the loose connection, with a reminder to press Escape then Space for unrestricted node search.
- Applied connection compatibility filtering before creating category headings, eliminating empty **BUILT-IN NODES** sections when textual matches exist but none can accept the wire.
- Added a clear **No compatible nodes match…** state rather than leaving an apparently broken blank result list.
- Slightly increased the initial socket-drag threshold and require a deliberate loose-wire distance before opening compatible search, reducing accidental popups while preserving normal wire connection behaviour.
- Added regression coverage for filtered headings, contextual guidance, compatible results and guarded loose-wire activation.

## 0.43.0 — Optional live node thumbnails

- Added an opt-in live thumbnail to every ordinary visual-output node while preserving the existing compact graph appearance by default. No thumbnail evaluator work is submitted for nodes that remain collapsed.
- Added one consistent chevron control in the node header beside the existing bypass/power control. The chevron expands or collapses a fixed 128 × 128 thumbnail directly beneath the title.
- Added per-node thumbnail-output selection for multi-output nodes through the chevron context menu. The stable selected output survives graph save/load and source-interface renames where possible.
- Added typed thumbnail presentation for Greyscale, Colour, Vector / Normal, Material and Signal outputs. Material thumbnails show Base Colour; Signal outputs use a compact numeric tile.
- Added a dedicated low-priority thumbnail scheduler. It evaluates only visible expanded nodes, one at a time, at exactly 128 × 128 using the lightweight interactive workload and yields immediately to 2D preview, 3D preview, playback and parameter interaction.
- Reused completed 2D preview results for the active node thumbnail, avoiding a second graph evaluation when the requested node/output is already being presented.
- Added a bounded 32 MiB RGBA8 thumbnail cache, branch-revision keys, fixed-resolution reuse, stale-result rejection and last-valid-image retention while a newer thumbnail waits.
- Prevented independent thumbnail evaluation during timeline playback. The active node can reuse the already rendered playback frame for free; other expanded nodes settle after playback pauses.
- Limited automatic refresh to expanded nodes currently visible in the canvas viewport. Off-screen thumbnails retain their last result until they become visible again.
- Suppressed thumbnails and chevrons on docked nodes, reroutes and compact Send/Receive portal aliases. Undocking a previously expanded node restores its thumbnail preference.
- Added clear Not Evaluated, Rendering, Updating and Error states instead of treating a blank placeholder as a legitimate black result.
- Integrated thumbnail state with undo/redo, graph copy/save/load, Clear Render Cache and GPU Diagnostics. Bumped the graph schema to version 14; older graphs load with every thumbnail collapsed.
- Added regression coverage for zero disabled-node requests, fixed geometry/resolution, cache reuse, multi-output selection, save/load, docking suppression, stale-image retention and compatibility with output-socket previewing and interactive scheduling.

## 0.42.1 — Graph-asset parameter editor and clean startup

- Fixed the Graph Asset Parameter `…` button appearing to do nothing for exposed parameters without an explicitly authored parameter group, including Ridge Noise **Octaves**. The dialogue now uses the same inferred group names as the Parameters panel.
- Hid the graph-asset `…` button until a publishable parameter is actually exposed, removing inactive metadata controls from ordinary parameter rows.
- Changed Graph Explorer startup restoration to opt-in. VFX Texture Lab now begins with a clean graph session by default instead of reopening every saved graph from the previous application session.
- Kept **File → Defaults & Startup → Restore Open Graphs on Startup** for users who deliberately prefer persistent document sessions.
- Added regression coverage for ungrouped integer parameter metadata, conditional ellipsis visibility and the clean-session startup default.

## 0.42.0 — Exact output preview and Graph Explorer

- Added exact output-socket previewing. Double-clicking a named output locks the 2D Preview to that result, while double-clicking the node body retains the existing primary/default-output behaviour.
- Added a persistent active-output ring, saved `active_output` graph state and lazy routing for Greyscale, Colour, Vector / Normal, Signal, Material and Graph Instance outputs.
- Separated output double-clicking from connection dragging with the platform drag threshold, preventing preview gestures from leaving temporary wires or interfering with ordinary press-and-drag connections.
- Added the dockable **Graph Explorer** above Node Library for keeping multiple saved and unsaved graph documents open in one application session.
- Added per-document graph scene, undo/redo history, dirty state, selection, pan/zoom, exact preview target, timeline frame, document settings and 3D viewport/camera state.
- Changed New and Open so they add documents to Graph Explorer rather than replacing the current graph. Added Save All, Close Graph, Close Others, Save a Copy, Duplicate Graph, Reload, Reveal and Add Parent Folder to Graph Assets workflows.
- Added drag-and-drop from Graph Explorer to the active canvas. Saved sources become live linked Graph Instances; unsaved sources remain live session instances and serialise into parent graphs as embedded dependencies.
- Made open source documents authoritative for matching linked instances, so unsaved child edits propagate after a short debounce without requiring save/reload. Propagation follows nested A → B → C dependency chains.
- Added live reopening of embedded Graph Instances as unsaved Explorer documents. Closing re-embeds the current revision; Save As gives the source a path and enables linked serialisation.
- Added safe dependant-aware close handling. Unsaved sources used by parents can be saved, embedded and closed, or left open; closing saved sources returns dependants to their linked disk revision.
- Added direct and indirect cycle rejection before Explorer drops, resolving both live session IDs and linked source paths.
- Added optional restoration of previously open saved graphs on startup and restoration of the previously active graph where possible.
- Expanded autosave into a multi-document recovery bundle. Every dirty Explorer document is retained, saving one graph does not discard the others, and stale entries are skipped when disk files are newer.
- Added a presentation-cache size bucket so small dock/busy-label layout changes reuse an unchanged 2D preview rather than submitting another evaluator job or GPU readback.
- Added Graph Explorer, runtime session, autosave, exact-output gesture, Material-output routing and presentation-cache regression coverage.

## 0.41.1 — Graph asset interface polish

- Fixed Graph Instance nodes drawing stable internal socket IDs instead of their public Graph Input/Output names. Public labels now render correctly on both sides of the node.
- Fixed selecting a Graph Instance leaving the Parameters dock on **Nothing selected** because the graph-asset information group was added through an invalid layout attribute. Random Seed and every published control now appear normally.
- Removed the separate **A** publication button from every parameter row. **Publish on Graph Instance nodes** now lives inside the existing **… Graph Asset Parameter** dialogue beside the public name, group, order and description.
- Combined public metadata and publication changes into one undoable graph edit while retaining the existing stable interface ID.
- Made connected Graph Output nodes directly previewable while authoring an asset. Image, Signal and Material Graph Outputs now forward to their connected typed source instead of reporting a missing evaluator.
- Made Material Graph Outputs resolve their connected Material producer for both 2D Base Colour preview and the complete 3D material preview.
- Added regression coverage for Graph Instance parameter-page construction, public label presentation, integrated publication metadata, direct Graph Output evaluation and Material-output preview routing.

## 0.41.0 — Nested graph assets

- Added **Graph Input** with one Data Type dropdown for Greyscale, Colour, Vector / Normal, Signal and Material public inputs, including names, descriptions, required-state warnings, ordering and type-appropriate defaults.
- Added **Graph Output**, whose public type is inherited automatically from its connected value. Dedicated graph-interface outputs remain separate from Single Image Output, Texture Set Output and other application outputs.
- Added dynamic **Graph Instance** nodes so a complete `.vfxgraph` can be used as one typed node inside another graph. Public sockets and parameter controls are generated from the source graph interface.
- Reused parameter exposure for graph assets: unconnected exposed parameters become instance controls, internally connected exposed parameters remain private, and the new **A** toggle can opt a locally exposed parameter out of asset publication.
- Added a public-parameter editor through the **…** button for instance-facing name, description, group and order while retaining stable hidden interface IDs.
- Added exactly one universal **Random Seed** to every Graph Instance. It deterministically remaps all internal random seeds, preserves authored per-node differences and propagates coherently through nested assets.
- Added linked graph assets with automatic source polling/reload, manual Reload, Open Source Graph, Relink and Reveal Source actions. Missing linked files keep evaluating from their last known good cached revision.
- Added **Make Local / Embed** so parent graphs can retain a portable frozen copy independent of the source file.
- Added three insertion workflows: drag `.vfxgraph` files from the operating-system file manager, use one **Add Graph Asset…** action in ordinary add-node search, or register recursively scanned asset folders in Node Library.
- Kept loose-wire search focused on compatible built-in nodes while ordinary search groups registered graph assets separately.
- Preserved parent wires and explicit parameter overrides through linked source updates by using stable interface IDs. Connected sockets removed from a source remain visible as clearly marked `(missing)` sockets instead of being silently deleted.
- Added lazy nested evaluation for image, Signal and Material outputs, including Material Channels, Send/Receive, 2D/3D preview and Texture Set Output. Requesting one public output does not evaluate unrelated outputs.
- Added private runtime namespaces for stateful nodes inside each instance, recursive seed propagation, last-known-good dependency data, direct/indirect cycle detection and a nesting limit of 64.
- Fixed nested Material assets upstream of Send/Receive or Texture Set Output being skipped by image-only reachability. Graph-instance expansion now follows all typed structural dependencies before ordinary demand-driven evaluation.
- Fixed the intermittent Fluvial Erosion 2D presentation race by rebuilding a malformed/empty small preview from the valid completed full-resolution result before caching it, without treating legitimate black outputs as errors.
- Fixed the static old-project flipbook migration helper referencing `self`.
- Added a reusable Rock Material Generator asset, an embedded two-instance composition example, graph-asset documentation and focused regression coverage for interfaces, seeds, links, embedding, reload migration, Material/export routing, scalar outputs, state isolation, search/library workflows and recursion safety.
- Bumped the graph schema to version 13.

## 0.40.1 — Preview caching and material performance

- Added a revision-keyed **2D presentation cache** that retains display-ready RGBA8 preview pixels, so returning to an unchanged image node can update the panel without resubmitting graph evaluation or repeating final GPU readback.
- Added a memory-budgeted **resolved Material cache** keyed by material producer, branch revision, requested channels, resolution, frame and precision. Returning to a recently viewed material can now skip graph traversal, channel resolution and GPU-to-CPU readback.
- Added a **renderer-resident material texture-set cache** with mipmapped GPU textures. Re-focusing a cached material swaps existing texture views instead of re-uploading every map and rebuilding mip chains.
- Changed the 3D material bridge to resolve and upload only genuinely authored channels. Missing PBR channels remain the renderer's existing semantic 1×1 defaults instead of being expanded into full-resolution float textures.
- Protected the currently displayed renderer material from LRU eviction while reducing cache budgets, and retained a safe transient copy when the render cache is explicitly cleared during an in-flight refresh.
- Separated graph/material invalidation from camera, lighting, environment and mesh redraws, so viewport-only changes do not reevaluate material textures.
- Added presentation-cache and renderer-reuse rows to the Evaluation Inspector, including **Reusing 2D preview**, **Resolved material cache hit**, **Renderer material reused** and **Renderer upload from resolved cache**.
- Expanded GPU diagnostics with separate totals for the graph GPU/CPU caches, 2D presentation cache, resolved-material CPU cache and 3D renderer material cache.
- Wired the existing cache budget control and **Clear Render Cache** command through all new cache layers. Exact animation/playback frames deliberately bypass the focus cache so animated materials continue to update correctly.
- Added end-to-end regression coverage for unchanged 2D focus, unchanged Material focus, authored-channel-only material evaluation, zero-upload renderer reuse and active-entry cache protection.

## 0.40.0 — Complete material composition

- Promoted the purple Material socket from a direct Material-node bundle into a lazy graph value that can be produced, layered, modified, selected, previewed and exported without expanding into nine permanent texture wires.
- Added **Material Blend** with Standard and Height Aware layering, Amount/Mask controls, optional foreground-opacity coverage, settings-source selection and specialised Normal, Height and Emissive handling.
- Added **Material Override** with optional per-channel replacement inputs, masked Amount, Normal/Height/Emissive modes, explicit channel removal and optional material-settings replacement.
- Added **Material Channels** with typed Base Colour, Emissive, Normal, Height, AO, Metallic, Roughness, Specular Level and Opacity outputs. Outputs resolve independently and absent channels produce semantic defaults.
- Added **Material Switch** with static A/B selection or scalar-signal thresholding. Only the selected material branch is evaluated.
- Generalised 2D preview, 3D preview, Texture Set Output, Send/Receive portals and material resolution so they accept any material-producing node rather than searching specifically for the original Material node.
- Preserved authored-channel presence separately from default values, allowing Texture Set Output to omit genuinely absent maps while Material Channels can still expose useful defaults.
- Added normalised normal-map crossfading and reoriented detail combination, additive/max/min height options and additive emissive composition.
- Added material-operation traces and shared per-session channel/image caches so 3D and export evaluation reuse leaf results while retaining channel-level laziness.
- Added a complete example graph and regression coverage for typed sockets, masks, height-aware blending, overrides/removal, settings inheritance, downstream channel breakout, branch-lazy animated switching, portals, 3D evaluation, export planning and graph persistence.

## 0.39.1 — Terrace shaping overhaul

- Rebuilt **Terrace** around irregular geological shelves instead of uniform threshold-like quantisation.
- Added **Step Spacing Variation**, deterministic **Layout Seed** and **Elevation Distribution** controls so successive shelves can have different vertical spacing and can be concentrated toward lowlands or peaks.
- Added a greyscale **Mask** input. Black preserves the original heightfield exactly, white applies the Terrace result, and **Invert Mask** swaps the coverage.
- Added a mid-grey-neutral **Variation** input and **Variation Input Influence** for graph-driven local terrace-boundary offsets.
- Added seamless procedural **Boundary Breakup** and **Breakup Scale** controls to stop terrace contours forming perfect repeated rings.
- Added **Plateau Slope** independently from Edge Smoothness, allowing shelves to retain a gentle natural grade while keeping readable step faces.
- Reorganised Terrace parameters into Terrace Layout, Terrace Profile, Shape Breakup and Mask groups with artist-facing descriptions and softer slider ranges.
- Preserved the existing `steps`, `offset`, `smoothness` and `strength` project parameter names while extending saved projects with safe defaults for the new controls.
- Updated the CPU reference and one-pass WGSL implementation for all three inputs and all new parameters.
- Added CPU/GPU regression coverage for hard shelf counts, spacing seeds, elevation distribution, masks, variation maps, plateau slope, two-layer blending and GPU parity.

## 0.39.0 — Erosion system overhaul

- Fixed intermittent black 2D previews in Fluvial Erosion at maximum Channel Widening by bounding wrapped/closed flow accumulation and sanitising non-finite CPU/GPU fields.
- Reorganised Fluvial and Thermal parameters into artist-facing Character, Water & Drainage, Sediment & Banks, Material, Quality, Advanced and Outputs groups.
- Added resolution-aware **Erosion Scale**, uniform **Rock Resistance** and **Sediment Transport** to Fluvial Erosion while retaining old project parameter names for compatibility.
- Rebuilt channel widening around retained river cores, smooth local valley profiles and broad scale-aware support, producing less brittle bank shapes.
- Added energy-dependent sediment settling, floodplain spread, valley-local bank stabilisation and gentler Shape Protection.
- Replaced Thermal Erosion's steepest-neighbour movement with proportional multi-direction talus transport.
- Added **Talus Mobility**, **Rock Resistance**, terrain-anchored **Fracture Variation / Scale / Seed**, and **Shape Protection** to Thermal Erosion.
- Updated the default erosion settings toward connected drainage, moderate downcutting, visible deposition and a natural 34° thermal repose angle.
- Added CPU/GPU regression coverage for maximum widening, high-retention drainage loops, finite previews, erosion scale, sediment transport, resistance, thermal isotropy and fracture variation.
- Rewrote the terrain guide with the recommended Fluvial → Thermal workflow and a rationale for a future dedicated Debris Flow / Mass Wasting node.

## 0.38.1 — Flipbook Decode continuous-playback fix

- Fixed Flipbook Decode remaining visually static during timeline playback when its Sheet input was connected directly to Flipbook Generator.
- Routed direct Flipbook Generator decoding through the existing frame-ahead playback evaluator, which evaluates only the selected procedural sample rather than trying to treat the generator as an imported static atlas.
- Retained the faster load-once, slice-locally playback path for imported static flipbook sheets.
- Added a continuous-playback regression test that verifies multiple changing decoded cells are actually presented while the timeline is playing.

## 0.38.0 — Graph docking and typed wireless portals

- Added **D** to toggle compact visual docking for eligible nodes with one output, at most one visible input and exactly one downstream connection.
- Docking is presentation-only: node identity, parameters, preview, bypass, undo/redo, incoming connections and evaluation remain ordinary graph behaviour.
- Added nested docking so compact utility chains can extend outward from a parent input.
- Saved dock parent and undocked position in graph, clipboard and reusable-group data; invalid or fanned-out dock relationships automatically return to ordinary nodes.
- Docked the starter graph's Metallic, Roughness and Specular constants into their Material inputs by default.
- Added named **Send** and **Receive** nodes under Graph Utilities with stable ID-based channel pairing and unique Send names.
- Added wireless propagation for greyscale, colour, Vector / Normal, Material, scalar, Vector2 and Vector3 graph types.
- Added temporary dashed portal guides while a Send or Receive is selected, missing-channel errors and wireless cycle detection.
- Retained incompatible Receive output connections as dashed red inactive wires when a Send changes type; the connections recover automatically when the channel becomes compatible again.
- Made evaluator snapshots treat Receive as a zero-cost virtual pass-through and taught Material preview/export resolution to follow Material values through portals.
- Bumped the graph schema to version 12.

## 0.37.1 — Material export workflow polish

- Reworked the built-in starter graph layout into clear generation, material-definition and export stages, with the Metallic, Roughness and Specular constants fanned cleanly into the Material node.
- Fixed Material and Texture Set Output focus so their connected Base Colour branch appears in the 2D Preview while the same Material continues driving the 3D Preview.
- Made double-clicking an already-active node explicitly refresh its preview rather than being ignored.
- Added a **Quick Export** section to Texture Set Output parameters with a per-output destination, remembered collision policy, **Open folder when complete** checkbox and **Change Export Location…** action.
- The first Quick Export opens Export Outputs for that endpoint only; successful setup is stored in the graph and later Quick Export presses write the texture set immediately.
- Made the Export Outputs window remember the global **Open output folder when complete** preference.
- Added a synthetic **★ Favourites** category at the top of the unfiltered Node Library while retaining favourite nodes in their normal categories.
- Removed the remaining unused Export Animation implementation; Flipbook Generator atlases export through Single Image Output.

## 0.37.0 — Material pipeline and output simplification

- Replaced **3D Output** with a non-terminal **Material** node that owns the PBR map set once and exposes a typed purple **Material** output socket.
- Simplified **Texture Set Output** to a single **Material** input so one authored material can drive any number of export endpoints.
- Updated the default startup graph to demonstrate the new `Material → Texture Set Output` pipeline and removed Single Image Output from the starter layout.
- Renamed **Image Output** to **Single Image Output**.
- Renamed **Flipbook Output** to **Flipbook Generator**, moved it into the **Animation** category, and removed the separate Export Animation command from the main File menu.
- Made the 2D preview show a Material node's connected Base Colour branch while that Material (or a Texture Set Output connected to it) is the active focused node.

## 0.36.0 — Graph-owned output and export overhaul

- Expanded **Image Output** from a name-only pass-through into a graph-owned export endpoint with enable state, file-name tokens, semantic presets, custom format/channel/encoding controls and independent resolution.
- Added semantic Auto export behaviour: Colour becomes sRGB PNG, Vector / Normal becomes linear RGB PNG, and Greyscale becomes linear 16-bit PNG.
- Added explicit Colour/sRGB, Linear Data, OpenGL Normal, DirectX Normal and Custom Image Output presets.
- Added per-output PNG, TGA and raw R16 writing, 8/16-bit depth where supported, grayscale source selection, RGB/RGBA selection, inversion and Green/Y flipping.
- Added terminal **Texture Set Output** with typed Base Colour, Emissive, Normal, Height, Ambient Occlusion, Metallic, Roughness, Specular Level and Opacity inputs.
- Added Separate PBR, Unreal ORM and Unity HDRP Mask Map export presets, including AO/Roughness/Metallic packing and Metallic/AO/Detail/Smoothness packing.
- Added target normal convention selection so a texture set can export OpenGL (+Y) or DirectX (-Y) normals without changing the graph.
- Added a batch **Export Outputs** centre showing each endpoint's planned files, preset, resolution and enabled state.
- Added Add numeric suffix, Replace existing and Skip existing collision policies, progress/cancellation and optional output-folder opening.
- Added right-click **Export This Output** and **Export Selected Outputs** actions for Image Output and Texture Set Output nodes.
- Stopped silently exporting arbitrary active preview nodes from the production export command; explicit graph endpoints now define repeatable export intent.
- Added pure regression coverage for export planning, typed default encoding, normal Y conversion, ORM/MaskMap packing, PNG writing and collision handling.
- Bumped the graph schema to version 11.

## 0.35.1 — Typed socket and 3D material-response polish

- Made connected `image_any` inputs retain universal compatibility while painting with the concrete greyscale, colour, or Vector / Normal type currently flowing through them; disconnected universal sockets return to neutral grey.
- Fixed Extract Channels therefore showing a grey input socket even when its connected wire was blue or gold.
- Corrected the dielectric Specular Level mapping so the conventional default value of 0.5 produces approximately 4% F0 reflectance instead of the overly glossy 9% response.
- Replaced direct environment-times-Fresnel reflections with a roughness-aware split-sum BRDF approximation, removing the bright grazing-angle bands that made matte terrain look coated or wet.
- Added derivative-based specular anti-aliasing so high-frequency height and normal detail raises effective micro-roughness instead of creating sharp, unstable highlights.
- Added a gentle lighting-only shoulder for the bundled inverse-tonemapped environment maps so bright reconstructed HDR peaks no longer overwhelm the material; visible HDRI backgrounds are unchanged.
- Added focused typed-socket and shader-regression coverage for these fixes.

## 0.35.0 — Normal-map import and typed channel pipeline

- Added conservative tangent-space normal-map detection to Image Input using common filename conventions plus encoded-vector pixel analysis.
- Auto-detected normal maps now expose a **Vector / Normal** output and remain linear instead of being treated as display-sRGB colour.
- Added a contextual **Flip Green / Y** option directly to Image Input for converting between OpenGL (+Y) and DirectX (-Y) tangent conventions.
- Expanded Source Information to report likely normal-map detection and its detection basis.
- Made Extract Channels accept greyscale, colour and vector/normal inputs while retaining greyscale R, G, B and A outputs.
- Added an explicit **Output data type** selector to Channel Pack, allowing packed RGBA data to be declared as Colour or Vector / Normal and propagated through typed sockets.
- Added **Colour to Vector / Normal** and **Vector / Normal to Colour** semantic reinterpretation nodes. They preserve encoded channel values while changing graph type.
- Registered both reinterpretation nodes on the CPU reference path and the ordinary one-pass WebGPU copy path.
- Fixed node-search keyboard navigation so the first Down press from the focused search field selects the second visible result rather than reselecting the default top result.
- Added Space-bar node search at the mouse cursor whenever the graph canvas has keyboard focus and the cursor is inside it.
- Added typed-pipeline and popup-interaction regression coverage for normal import, Y flipping, vector channel splitting/packing, semantic conversion and cursor-positioned Space search.

## 0.34.0 — Project-owned 3D viewport inspector

- Moved Mesh, Camera, Lighting, Display and Quality controls out of the 3D Preview dock and into a dedicated **3D Viewport Settings** page in the ordinary Parameters inspector.
- Added a **Settings…** action to the 3D Preview toolbar; selecting any graph node immediately returns the Parameters inspector to that node.
- Replaced the viewport settings tabs with the same collapsible parameter-group presentation used by graph nodes.
- Made the render canvas use the largest centred square that fits the available 3D Preview space, so inspector controls no longer crush or resize the material view.
- Stopped reading mesh, camera, lighting, display and renderer-quality values from global `QSettings`.
- Added a serialised `viewport_3d` project section containing both presentation settings and orbit/pan/zoom camera state.
- New files now always start from the application defaults, while opened graphs and recovered autosaves restore their own saved viewport state.
- Custom startup graphs still define graph/document content but intentionally start each new file with the application viewport defaults.
- Added the **VFX Studio** lighting preset and adopted the requested defaults: Cayley Interior, 301° environment rotation, 0.20 environment intensity, 328° sun azimuth, 35° sun elevation, `#2d2938` background, ACES +0.05 EV, 4× MSAA, bloom 1.58/1.60/21 px, sharpen 1.0 and vignette 0.58.
- Added **Reset Viewport Defaults** inside the viewport inspector; resetting affects only the current document and marks it dirty for saving.

## 0.33.2 — True bloom and 3D settings consistency

- Replaced sparse radial bloom sampling with a half-resolution HDR prefilter and true horizontal/vertical Gaussian blur passes.
- Added a soft-knee threshold and expanded bloom radius to 32 pixels without duplicated emissive silhouettes.
- Grouped Bloom, Sharpen, Vignette, Turntable, Directional Shadows and environment-background visibility into stable subordinate sections.
- Top-aligned every 3D settings tab so controls no longer spread across empty space or move upward when subordinate settings appear.
- Enlarged and padded the Lighting angle dials to remove the remaining lower-edge clipping.
- Kept all renderer presentation changes on the redraw-only path.

## 0.33.1 — Renderer polish and lighting/background fixes

- Restored smooth preview shading by basing default mesh lighting on interpolated mesh normals instead of per-triangle face derivatives.
- Smoothed the built-in Cube preview normals while keeping its UV layout intact.
- Kept **Surface Normals (World)** as the final shaded normal view and aligned **Mesh Normals** with the underlying smoothed mesh normals.
- Increased the viewport-settings height and reserved more space for the shared angle widgets so the environment-rotation and sun-azimuth dials are no longer clipped.
- Updated the shared `AngleDial` interaction polish so mouse-driven edits clear the lingering focus ring after release.
- Reworked bloom into a denser soft blur kernel so emissive glow spreads smoothly instead of creating visibly duplicated radial copies of the source.
- Repurposed the Display background slider into **environment background visibility**, allowing the HDRI to keep lighting the mesh while fading independently against a chosen solid background colour.
- Kept the solid background colour fully separate from environment-light intensity so lighting, visible HDRI background and fallback background colour can be judged independently.

## 0.33.0 — HDR renderer correctness and quality

- Replaced direct swapchain shading with an RGBA16F HDR scene pass and a dedicated post-processing pass.
- Added exposure plus ACES, Neutral, Reinhard and Linear tone-mapping options.
- Added four compact environment-lighting presets derived from Poly Haven CC0 panoramas: Studio Small 02, Cayley Interior, Overcast Soil and Chalk Quarry Sunset.
- Added equirectangular image-based diffuse and roughness-aware specular lighting, environment rotation and optional environment-background display.
- Replaced the arbitrary generated tangent frame with a derivative UV tangent frame that follows mesh UV orientation, including custom glTF/GLB meshes and mirrored UV handedness.
- Reconstructed displaced macro normals from the displaced world surface and combined height-derived and authored tangent normals using reoriented normal mapping.
- Added complete CPU-generated mip chains for all material maps and environment maps, trilinear filtering and anisotropic material sampling.
- Added 4× multisample anti-aliasing with automatic single-sample fallback where RGBA16F multisampling is unavailable.
- Added a displacement-aware directional shadow-map pass with 3×3 PCF filtering and alpha/cutout-aware shadow casting.
- Added optional HDR bloom with threshold, intensity and radius controls; bloom is enabled by default for emissive VFX preview.
- Added optional sharpening and vignette post effects.
- Preserved Opaque, Alpha Cutout, Alpha Blend, Premultiplied Alpha and Additive blend modes in the HDR render path.
- Added a compact Quality tab and contextual visibility for bloom, shadow, sharpen and vignette subordinate controls.
- Added focused regression coverage for environment assets, mip generation, renderer uniforms, HDR/MSAA rendering, shader tangent/shadow features and post-effect controls.

## 0.32.1 — 3D viewport angle and normal-view polish

- Replaced the stock Qt sun-azimuth dial with the shared `AngleDial` used by node parameters, including the same painting, direct dragging, wheel/key adjustment and double-click reset behaviour.
- Increased the compact viewport-settings height enough to display the complete angle widget without clipping the lower edge.
- Added **Normal Map (Tangent)**, which displays the connected tangent-space map after the selected OpenGL/DirectX Y convention and normal-strength adjustment.
- Renamed the former **Normal** view to **Surface Normals (World)** because it displays the final world-space normal after height-derived detail and tangent normal mapping.
- Retained **Mesh Normals** for unmodified geometry normals and migrated saved 0.32.0 `Normal` debug selections to the clarified world-space label.
- Added focused regression coverage for the shared angle widget, unclipped settings geometry and all three normal-inspection modes.

## 0.32.0 — 3D viewport presentation

- Replaced the single viewport grid with compact Mesh, Camera, Lighting and Display tabs.
- Made controls contextual: terrain tiling appears only for Terrain Plane, custom-mesh controls only for Custom Mesh, geometry quality only for built-ins, plane grid only for plane meshes, and field of view only in perspective projection.
- Replaced raw subdivision counts with mesh-specific Low, Medium, High and Ultra geometry presets.
- Added tessellated Flat Plane and Cube meshes so height displacement can affect more than their original corner vertices.
- Corrected the Sphere's reversed triangle winding while retaining outward vertex normals and UVs.
- Added perspective/orthographic projection, adjustable field of view, Free/Front/Back/Left/Right/Top/Bottom camera views, persisted orbit framing and turntable rotation.
- Added Studio, Soft, Dramatic, Flat and Unlit lighting presets; intensities and elevation now use linked sliders/value boxes and sun azimuth uses a circular dial with precise numeric entry.
- Added Final Material, Base Colour, Normal, Height, Roughness, Metallic, Ambient Occlusion, Emissive, Opacity, UV Checker and Mesh Normals display modes.
- Added a UV-grid overlay usable on every mesh while retaining the plane-specific surface grid.
- Kept camera, lighting, debug and mesh presentation changes on the renderer-only path; only material-map resolution asks the active 3D Output for new textures.
- Added focused regression coverage for outward sphere faces, mesh-specific quality, contextual UI, lighting presets, projection controls and debug-mode uniforms.

## 0.31.1 — Visible viewport controls and safe workspace reset

- Replaced the overfull single-row 3D toolbar with a compact camera selector and a full-width **Viewport Settings** header.
- Made the viewport settings section expanded by default and persist its collapsed/expanded state.
- Reflowed mesh, map resolution, subdivision, tiling, lighting, background and grid controls into a readable two-column layout.
- Fixed narrow or previously saved 3D dock layouts placing the Viewport button beyond the visible right edge.
- Reworked **Reset Workspace Layout** to move existing docks in place instead of removing and immediately reparenting the embedded 3D render canvas.
- Deferred workspace reset until after the confirmation dialog closes, suspended repainting during the dock transaction and requested one clean 3D redraw afterward.
- Added runtime regression coverage for visible viewport controls and repeated reset of a floating 3D dock without replacing its canvas.

## 0.31.0 — Focused 3D material definition

- Changed **3D Output** into a true terminal graph sink with no misleading downstream image socket.
- Renamed **Albedo** to **Base Colour** and **Specular** to **Specular Level** while preserving 0.30.0 graph connections through load-time aliases.
- Reduced the node to material channels and material behaviour: surface mode, cutout, two-sided rendering, emissive strength, normal convention/strength and displacement controls.
- Moved preview mesh, subdivision, custom mesh, terrain tiling, texture resolution, lighting, background and surface-grid controls into a persistent **Viewport** section in the 3D Preview panel.
- Made 3D material evaluation follow the same active-node contract as ordinary graph previews: double-clicking a 3D Output activates it, and inactive 3D Outputs do not refresh when upstream nodes change.
- Added **Alpha Blend**, **Premultiplied Alpha** and **Additive** VFX surface modes alongside Opaque and Alpha Cutout.
- Migrated legacy Cutout/Transparent modes and adopted legacy per-node viewport values the first time an older 3D Output is activated.
- Kept timeline-driven 3D updates, material-branch caching and coalesced interactive refreshes while the 3D Output remains active.
- Bumped the graph schema to version 10 and expanded focused 3D, scheduler, migration and viewport-setting regression coverage.

## 0.30.0 — Automatic GPU graph fusion

- Added a graph-planning pass that detects linear, unbranched grayscale adjustment chains before evaluation.
- Added `fused_adjustments.wgsl`, supporting up to eight Invert, Levels, Histogram Range/Shift/Scan, Brightness, Contrast, Exposure, Gamma, Posterize and Clamp operations in one dispatch.
- Collapsed fused chains into temporary internal nodes without modifying the saved graph or visible node layout.
- Preserved cache signatures, time-dependent invalidation, interactive-node propagation and full-resolution output semantics through fused chains.
- Prevented fusion across branches, named outputs, connected animation-signal parameter ports, bypassed nodes and explicit precision overrides.
- Kept default 16-bit colour/vector chains on the ordinary path until their intermediate RGBA16 rounding can be guaranteed exactly.
- Added fusion telemetry to evaluation results and the Timeline profiler.
- Added regression coverage for numerical agreement, dispatch reduction, bounded long-chain splitting, branching safety and colour-chain exclusion.

## 0.29.0 — Resolution-invariant graph evaluation

- Added a shared 512-reference relative-pixel system so spatial parameters preserve their authored proportions when Preview Max or export resolution changes.
- Converted Gaussian, Directional, Zoom, Anisotropic, Non-uniform and Slope Blur distances to resolution-independent `rpx` values.
- Converted Distance, Bevel, Expand / Shrink, Outline and Aperture spatial controls to the same CPU/WGSL-relative scale.
- Scaled Flood Fill minimum-island area in two dimensions using `rpx²`.
- Made Height to Normal and Curvature compensate for first- and second-derivative resolution changes.
- Audited Shapes, Polygon, Polygon Burst, gradients, procedural noises, Tile Sampler, transforms, distortions and Flood Fill metadata, which already use normalised coordinates.
- Stabilised 2D preview sampling so changing Preview Max does not switch between visibly different Qt scaling paths.
- Added cross-resolution regression coverage comparing the same authored graph across a fourfold resolution change.

## 0.28.1 — Real-time playback presentation fix

- Fixed a 0.28.0 regression where costly animated frames were only presented when their exact frame number still matched the wall-clock playhead.
- Real-time playback now displays the newest completed exact-quality frame after the playhead reaches or passes it, so heavy animated branches remain visibly in motion.
- Genuine frame-ahead results remain buffered and are not shown early.
- The scheduler still collapses obsolete targets and avoids building a historical render queue.
- Added direct regression coverage for **Loop Phase → Ridged Noise evolution → Aperture → Image Output** playback.

## 0.28.0 — Animation and GPU cache performance

- Added exact-quality frame-ahead buffering for ordinary timeline playback.
- Added **Real-time** playback, which keeps timeline timing correct and displays the newest completed exact frame without queuing stale work.
- Added **Every frame** playback, which advances only after each exact frame has completed.
- Playback now uses a dedicated sequential evaluation worker so the displayed frame, prepared next frame and ordinary edit-preview scheduler do not fight over one request slot.
- Static upstream branches remain shared through the existing GPU cache while only time-dependent descendants receive per-frame signatures.
- Completely static selected branches now prepare and upload one display frame per playback session, then advance only lightweight timeline metadata instead of repeatedly evaluating and presenting an identical image.
- Added an optional compact timeline profiler showing rendered FPS, evaluation/finalise/presentation time, buffered and dropped frames, static versus time-dependent node counts, cache hits, GPU-cache use and the slowest computed nodes.
- Playback skips detailed per-node trace construction while the profiler is disabled, reducing CPU-side animation overhead without changing image quality.
- Frame-ahead evaluation preserves hot sequential simulation state and existing checkpoint restoration.
- Automatic 3D refresh now follows completed 2D playback frames at background priority rather than competing with the frame currently being prepared.
- Added regression coverage for real-time buffering, every-frame playback, profiler telemetry, time-dependent branch classification and one-frame reuse for fully static graphs.
- Shader and graph fusion is recorded as the next planned optimisation milestone.

## 0.27.1 — Sustained interactive preview pacing

- Fixed rapid parameter drags repeatedly cancelling every in-flight draft frame before it could reach the 2D preview.
- Sustained edits now keep one lightweight frame in flight, present it, then immediately evaluate the newest accumulated parameter value.
- Intermediate edits still collapse into a single pending request, so there is no obsolete-render backlog.
- Raised the interactive dispatch ceiling from roughly 30 FPS to roughly 60 FPS when the graph is fast enough, while ordinary preview scheduling remains capped separately.
- Added a scheduler regression covering 100 rapid edits during one in-flight draft without cancellation starvation.

## 0.27.0 — GPU preview and interactive performance

- Added `preview_prepare.wgsl` to downsample graph output, convert linear colour to display sRGB, and prepare grayscale/vector previews directly on WebGPU.
- Ordinary 2D previews now read back compact RGBA8 display pixels rather than full-resolution float graph textures.
- Added persistent preview output textures, readback buffers, and uniform buffers, bounded to four view-size variants.
- Added command batching so ordinary GPU node chains use one command encoder and queue submission until readback or an iterative synchronisation point requires a flush.
- Added stale interactive-preview cancellation while retaining the previous completed image until a newer frame is ready.
- Discarded unsubmitted command batches when an evaluation is cancelled, preventing obsolete drag work from reaching the GPU queue.
- Added adaptive drag-time sample counts for the advanced blur family, with exact quality restored on release.
- Moved channel filtering and QImage construction onto the compact prepared image path.
- Added GPU/CPU display-preparation agreement and view-sized-readback regression coverage.

## 0.26.0 — Additional blur tools

- Added **Zoom Blur** for centre-based radial streak blurring along each pixel's outward ray.
- Added **Anisotropic Blur** for oriented elliptical blurring with adjustable anisotropy and angle.
- Integrated both nodes into the CPU and WGSL processing paths.

## 0.25.1 — Directional Blur and Aperture footprint fixes

- Corrected Directional Blur's angle convention so positive angles now rotate in the same screen-space direction as the shared angle dial and Directional Warp.
- Replaced Aperture's square-producing Disk neighbourhood with a genuinely filled circular structuring footprint.
- Replaced Aperture Polygon's shared 3x3 neighbourhood with a filled regular-polygon footprint whose silhouette changes with the Vertices parameter.
- Evaluated Disk and Polygon in bounded radius-four GPU chunks, preserving their intended silhouette without reverting to CPU processing.
- Fixed negative-coordinate wrapping in Aperture's WGSL sampling path so all aperture shapes remain continuous across both texture seams.
- Added regression tests for positive-angle Directional Blur orientation, wrapped Aperture sampling, non-square Disk output, distinct polygon vertex counts, and CPU/GPU agreement.

## 0.25.0 — GPU morphology and Aperture

- Added dedicated WGSL kernels for Expand / Shrink and Outline.
- Replaced the temporary CPU-backed Directional, Radial, Non-uniform Grayscale, and Slope Grayscale blur routes with dedicated WGSL kernels.
- Added GPU-native Open and Close through two chained thresholded distance-field operations.
- Corrected Outline's inner, outer, and centred softness profiles in both CPU and WGSL paths.
- Added the grayscale Aperture node with Dilation and Erosion modes.
- Added Disk, Polygon, Asterisk, Line, and Corner structuring shapes.
- Added polygon / asterisk vertices, directional controls, corner angle, antialiasing, strength blending, and seamless/clamped boundaries.
- Added an iterative WGSL aperture pipeline and matching NumPy reference implementation.
- Added CPU/GPU regression coverage for mask morphology, outlines, every aperture shape, partial strength, and wrapped boundaries.

## 0.24.0 — Morphology and Blur foundation

- Added **Expand / Shrink** with Expand, Shrink, Open and Close operations on seamless grayscale masks.
- Added **Outline** with Inner, Outer and Centered modes, edge offset and adjustable softness.
- Added **Directional Blur** for wrapped motion-style blurs along an angle.
- Added **Radial Blur** for wrapped spin blurs around a configurable centre.
- Added **Non-uniform Blur Grayscale** with a per-pixel Blur Map-controlled radius.
- Added **Slope Blur Grayscale** with Blur, Min and Max modes driven by a slope input.
- Reused the seamless distance-field foundation for the new morphology / outline nodes.
- Integrated the new nodes into the WebGPU backend through a compatible CPU-backed execution path so they evaluate correctly in the live graph.

## 0.23.0 — Distance and Bevel foundation

- Added a shared seamless Euclidean distance-field foundation for binary grayscale masks.
- Added a **Distance** filter with Inside, Outside, Signed and Absolute output modes.
- Added pixel-based maximum distance, edge offset, curve, profile smoothing, threshold, input/output inversion and wrap/clamp controls.
- Added a **Bevel** filter with Inner, Outer, Centered and Edge Ridge directions.
- Added Linear, Smooth, Rounded, Concave and Convex bevel profiles with independent height/background values and optional HDR unclamped output.
- Added toroidal nearest-edge measurement so wrapped shapes retain continuous distance and bevel profiles across both texture axes.
- Added matching CPU and WGSL jump-flood implementations and two local refinement passes for thin diagonals and dense corners.
- Kept seed propagation GPU-resident through 2048 pixels per axis and added a memory-safe CPU-assisted path for larger documents.
- Added focused registry, seam, profile, empty/full-mask and CPU/GPU agreement regression coverage.

## 0.22.1 — Seamless Flood Fill topology

- Changed Flood Fill component detection to use toroidal X/Y connectivity so regions crossing opposite texture borders remain one island.
- Added correct shortest wrapped bounding boxes and seam-aware island centres rather than recording edge-crossing regions as nearly full-texture bounds.
- Updated Flood Fill to Gradient and Flood Fill Mapper Grayscale on both CPU and WGSL paths to use shortest wrapped local UV deltas.
- Ensured Random Grayscale, Random Colour, Grayscale, Colour, Position, BBox Size and Index conversions all inherit one consistent metadata record for seam-crossing islands.
- Added regression tests for horizontal, vertical and diagonal wrapping, correct wrapped bounds, seam-continuous gradients and mapped patterns, and CPU/GPU agreement.

## 0.22.0 — Flood Fill island analysis

- Added a binary-mask Flood Fill node with threshold, 4-way/8-way connectivity, minimum-island filtering and optional input inversion.
- Implemented fast run-length connected-component analysis and compact per-pixel island metadata containing centre, bounding-box size and normalised top-left index.
- Added Flood Fill to Random Grayscale, Random Colour, controlled Grayscale, controlled Colour, Gradient, Position, BBox Size and Index nodes.
- Added a grayscale Flood Fill Mapper with per-island pattern fitting, scale/rotation randomisation and optional Scale/Rotation maps.
- Added shared CPU reference implementations and WGSL GPU implementations for all conversion and mapping nodes.
- Kept the topology-analysis node on CPU, where the optimized implementation evaluates a 2048² regular tile mask in under one second in the validation environment, then uploads its reusable metadata once for downstream GPU nodes.
- Removed the earlier 4095-island metadata limit by storing index as a full normalised float.
- Made vector previews opaque without altering their authored alpha data.
- Added focused regression coverage for island ordering, large island populations, metadata conversions, mapper behaviour and CPU/GPU agreement.

## 0.21.0 — Procedural Shapes foundation

- Replaced the legacy Circle and Rectangle generators with a broader **Shape** node.
- Added Rectangle, Rounded Rectangle, Disc, Ring, Capsule, Triangle, Diamond, Hexagon, Cross, X, Crescent, Bell, Gaussian, Pyramid, Cone, Hemisphere, Waves and Linear Gradation modes.
- Added grouped transform controls including centre, size X/Y, uniform scale, rotation, tiling X/Y and non-square compensation.
- Added grouped profile controls including edge softness, outline / bevel width and inversion.
- Added shape-specific controls for corner radius, ring thickness, capsule length, cross thickness, crescent cutout and wave behaviour.
- Added a **Polygon** node with side count, star inner radius, alternating-point offset, roundness, twist and radial distortion.
- Added a **Polygon Burst** node for radial slice / burst patterns with explode, gap, inner radius, alternating slice weighting and solid / radial / angular fills.
- Reused the shared angle-dial parameter UI across the new nodes for consistent interaction.
- Added matching WGSL kernels and GPU backend parameter packing for Shape, Polygon and Polygon Burst.
- Added conditional parameter visibility so shape-specific controls appear only for applicable Shape modes.
- Added exhaustive registry, CPU-variant and CPU/GPU reference regression coverage for all three nodes.
- Removed the old standalone Circle and Rectangle nodes from the Shapes category before public release.

## 0.20.2 — Map-driven Tile Sampler distribution

- Added four grayscale Pattern Input sockets while preserving the original Pattern Input connection name for existing graphs.
- Added Single, deterministic Random Inputs, Sequential Inputs and Pattern Distribution Map selection modes.
- Added Scale Map, Rotation Map, Displacement Map, Vector Map, Mask Map and Pattern Distribution Map inputs with per-feature strength, angle, multiplier and threshold controls.
- Added scalar directional displacement, encoded two-axis vector displacement and optional vector-driven X/Y scaling.
- Added Diamond, Hexagon and Triangle built-in patterns.
- Added row-major/column-major rendering order and reverse traversal for order-sensitive Replace overlaps.
- Expanded the shared CPU/WGSL candidate radius to include vector scale bounds and scalar/vector displacement.
- Skipped inactive map sampling in both renderers to preserve default Tile Sampler performance.
- Fixed angle controls being shifted and compressed by the longest label in a parameter group; angle rows now span the form consistently.
- Made angle dials jump to the clicked direction on mouse press, while multi-turn controls retain the nearest equivalent accumulated angle.
- Added focused regression coverage for all new inputs, selection modes, map effects, masking neutrality, rendering order, angle layout source and click-to-jump behaviour.

## 0.20.1 — Angle controls and wide numeric ranges

- Added a reusable circular angle dial with normalised direction display, accumulated multi-turn dragging, mouse wheel/keyboard adjustment and double-click reset.
- Applied the angle dial consistently to Linear Gradient, Tile Sampler Rotation, Transform 2D, Rotate, Cartesian/Polar angle offsets, Swirl, Directional Warp, Turbulence Flow Direction and 3D Preview Sun Azimuth.
- Added shared `slider_minimum` / `slider_maximum` metadata so sliders can remain precise while numeric fields retain larger hard limits.
- Added per-parameter Ctrl fine snapping and Shift coarse snapping across sliders, angle dials and spin-button stepping.
- Added degree suffixes and appropriate snapping to non-directional angle magnitudes without giving them a misleading direction dial.
- Expanded Tile Sampler Size X/Y from 1.5 to 8 grid cells and Scale from 1.5 to 4, with narrower everyday slider ranges.
- Replaced the Tile Sampler's fixed five-cell overlap lookup with a shared dynamic radius used by both CPU and WGSL paths, supporting large rotated/randomised overlaps without clipping.
- Renamed Rotation Random to Rotation Random Range and documented that 180° means a symmetric -180° to +180° span, already covering all orientations.
- Added practical soft ranges to wide Transform/tile controls, scalar animation defaults, custom frame ranges and all built-in random-seed controls.
- Extended public node package manifests with optional soft ranges, interaction steps, units and `editor = "angle"`.
- Added regression coverage for angle metadata, modifier controls, enlarged Tile Sampler limits and overlap radii beyond the old five-cell cap.

## 0.20.0 — Grayscale Tile Sampler foundation

- Added a native grayscale **Tile Sampler** node under **Patterns**.
- Added seamless X/Y tile distribution with stable seed-based per-cell randomisation.
- Added Square, Disc, Brick, Capsule and Bell built-in patterns and a custom grayscale Pattern Input.
- Added Size, global scale, scale randomisation, independent X/Y position randomisation, global tile-cell offsets, rotation and rotation randomisation.
- Added alternating-row, alternating-column, continuous-row and continuous-column staggering.
- Added random X/Y mirroring, random tile masking, per-tile luminance variation and global opacity.
- Added Maximum, Add, Subtract and Replace overlap modes over a scalar background or optional grayscale Background Input.
- Added non-square compensation so sampled and built-in patterns retain visual proportions across rectangular outputs or uneven grids.
- Added a bounded reverse-lookup renderer on both CPU and GPU: each pixel checks only nearby candidate cells rather than the full tile population.
- Added focused tests for registry metadata, all built-in shapes, deterministic randomisation, staggered layouts, custom pattern sampling, background input and compositing.

## 0.19.3 — Canvas node creation hotfix

- Fixed an `UnboundLocalError` when creating a Canvas node without an explicit parameter dictionary.
- Canvas nodes created from the empty-state button, Node Library, or graph search again inherit the current document dimensions.
- Added a regression check that ensures caller-supplied parameter tracking is initialised before Canvas defaults are applied.

## 0.19.2 — Canvas Editor workflow polish

- Replaced the inactive Canvas Editor with a true empty state when no Grayscale Canvas node is selected.
- Added a centred **Create Grayscale Canvas Node** button that inserts and selects a Canvas node at the centre of the current graph view.
- Made every newly created Canvas node inherit the current document width and height, including nodes created from the library, graph search or the Canvas Editor empty state.
- Replaced free-form width and height fields with a power-of-two native-size selector while preserving existing rectangular or legacy dimensions as a readback option.
- Replaced the tool dropdown with a vertical strip of equal square icon buttons beside the canvas.
- Removed the editable Background field; Canvas clear and erase behaviour is now consistently black.
- Replaced the Fit/100% dropdown with a Fit button, live zoom percentage, mouse-wheel zoom and middle-mouse panning matching the 2D Output interaction model.
- Kept Canvas-specific undo/redo, embedded node data, project dirty state and autosave behaviour intact.

## 0.19.1 — Canvas undo and authoring workspace

- Routed Undo/Redo to the focused Canvas Editor before falling back to the graph undo stack.
- Added a separate bounded compressed history per Canvas node, so strokes, clears, resizes and background changes undo inside the Canvas without removing graph nodes or connections.
- Kept Canvas edits project-dirty and autosave-aware while separating them from structural graph history.
- Changed the default workspace to keep Parameters visible in a full-height column beside a tabbed 2D Output / 3D Output / Canvas Editor group.
- Fixed Reset Workspace Layout omitting Canvas Editor from the restored dock tree.
- Added automatic recovery for 0.19.0 workspace states where Canvas Editor was checked in View but had no dock area.
- Updated the View helper action to tab 2D, 3D and Canvas together.

## 0.19.0 — Grayscale Canvas authoring

- Added a new **Grayscale Canvas** input node for painting greyscale source masks directly inside the graph.
- Added a dedicated **Canvas Editor** dock with paint, erase, smudge, line, rectangle and ellipse tools, plus brush value/size/softness/opacity controls.
- Canvas nodes now carry embedded image data inside the graph, so copying a canvas node duplicates its authored image and deleting the node removes it from the project.
- Canvas nodes preserve an independent native resolution and resample to the current graph resolution at evaluation time.
- The Parameters panel now includes a canvas summary and quick button to open the Canvas Editor dock.
- Accurate linear-frequency histogram rendering from 0.18.8 remains the shared display model across histogram-driven editors.

# Changelog

## 0.18.8 — Accurate shared histogram display

- Replaced logarithmic histogram height scaling with one conventional linear-frequency presentation shared by Levels, Histogram Range, Histogram Shift and Histogram Scan.
- Increased histogram analysis from 256 to 1024 internal bins, then population-preserving reduction to the actual editor width.
- Replaced the smoothed point-to-point envelope with a stepped/bin silhouette and half-bin edge padding so distributions return cleanly to zero at both ends.
- Stopped clipping values below 0 or above 1 into the endpoint bins; subtle edge indicators now disclose underflow/overflow without distorting the visible range.
- Replaced every-nth-pixel sampling with deterministic 2-D stratified sampling to reduce aliasing on cells, grids and other regular procedural patterns.
- Kept Auto Level based on the real clipped minimum and maximum, so this release changes histogram presentation rather than Levels processing.
- Added pure NumPy regression coverage for binning, overflow handling, population-preserving reduction and periodic-pattern sampling.

## 0.18.7 — Levels editor regression fix

- Restored the complete inline Levels histogram/sliders interface after the 0.18.4 shared parameter grouping and parenting refactor.
- Fixed a stray `parent_widget` reference inside `LevelsControl`; the failed construction had aborted the atomic page swap and left the Parameters viewport blank.
- Explicitly parented the Levels editor to its collapsible Levels section.
- Reset the Parameters scroll position when swapping to a newly selected node.
- Made atomic parameter-page replacement failure-safe: a construction exception now restores the previous visible page before being reported.
- Added focused regression coverage for Levels ownership and the failure-safe page swap.

## 0.18.6 — Startup graphs, grid snapping and themes

- Added **File → Defaults → Save Current Graph as Startup**, storing the current graph and Document Settings as the template used for application launch and every future New project.
- Added **Restore Built-in Startup Graph** and a shortcut to the startup-template folder without modifying the current open graph.
- Added Shift-drag node snapping to the existing 24 px graph grid, using the dragged node's top-left corner while preserving the internal layout of multi-node selections.
- Added three built-in themes: Midnight, Graphite and Daylight, each with a distinct accent and deliberately readable foreground/background contrast.
- Rebuilt the stylesheet around theme colour tokens rather than one fixed palette.
- Themed graph backgrounds, major/minor grids, node bodies, selection/active borders, groups, reroutes, preview backgrounds and evaluation feedback alongside the normal Qt interface.
- Added explicit vertical and horizontal scrollbar tracks, handles and hover states so scrollbars no longer disappear into their backing colour.
- Persisted the selected theme and applied it before constructing the main window, avoiding a startup flash from the previous palette.
- Added custom JSON theme import/export, an openable user-theme directory, reload support and inheritance from any built-in base theme.
- Added focused source and pure-Python regression coverage for startup-template wiring, Shift-to-grid behaviour, built-in theme completeness, scrollbar contrast tokens and custom-theme loading.

## 0.18.5 — Stable parameter switching and lightweight starter graph

- Rebuilt the Parameters panel through a hidden atomic host swap instead of removing visible form rows one by one, preventing transient native X11 child windows from flashing the application icon during node selection.
- Explicitly parented shared numeric controls, parameter-section widgets, file controls and animation-socket buttons at construction time so they never briefly exist as top-level Qt widgets.
- Removed Fluvial and Thermal Erosion from the new-document starter graph, avoiding expensive work every time a fresh graph is created.
- Kept the starter useful with Ridged Noise, Gaussian Blur, Levels, Gradient Map, Height to Normal, Image Output and 3D Output.
- Added separate zero-valued Constant nodes to the starter graph's Metallic and Specular inputs, alongside the existing Roughness constant.
- Added focused source regression coverage for transient-widget prevention and starter-graph composition.

## 0.18.4 — Numeric entry and organised node parameters

- Added compact float spin boxes that retain the parameter's full accepted precision but trim redundant trailing zeroes in normal display (`4.0` instead of `4.0000`).
- Disabled keyboard tracking while numbers are being typed, preventing partial values from being reformatted and padded before editing is complete.
- Added clearly painted up/down chevrons over native spin-box controls, including node parameters, visual-editor coordinates, timeline values, document settings and export dialogs.
- Increased numeric-entry width in the Parameters panel for easier direct entry of larger values.
- Added reusable collapsible parameter sections with remembered expansion state per node type.
- Moved every ordinary Seed/Random Seed control into a consistent **Base Settings** section at the top, alongside data type and output precision.
- Organised remaining controls into consistent Parameters, Transform, Animation, Tiling / Boundaries, Quality and Output sections where applicable.
- Added optional `group` and `group_order` metadata to `ParameterSpec` and public custom-node manifests without changing existing package compatibility.
- Kept tiling controls honest: nodes that already implement Wrap, Tile, Boundary or Tiling options now present them consistently, while nodes without a real tiling implementation do not receive a cosmetic no-op control.
- Added focused parameter-system source and registry regression coverage.

## 0.18.3 — Connection snapping and editor QoL

- Added viewport-pixel-based wire snapping to nearby compatible sockets, with a restrained orange target ring and an ambiguity guard between tightly packed inputs.
- Kept invalid exact socket targets red and preserved the loose-connection search popup only when no socket target is selected.
- Fixed 2D preview viewport shaking by giving its live status a fixed one-line height, eliding long messages, and retaining the full text in a tooltip.
- Replaced duplicate timeline triangle glyphs with native standard transport icons for jump-to-start, previous frame, play/pause, stop, next frame and jump-to-end.
- Simplified the main toolbar to Document Settings, Preview Max, renderer selection and concise graph interaction guidance; File/Edit duplicates remain in menus and shortcuts.
- Rebuilt graph Open/Save dialogs around persistent last-location and recent-directory history, adding Home, Documents, Desktop, Downloads, the current graph folder and recent graph folders to the sidebar when supported by the platform dialog.
- Added focused source regression coverage for snapping, preview stability, file-dialog persistence, toolbar contents and timeline controls.

## 0.18.2 — Cached histograms, leaner 3D maps and dock safety

- Fixed the Levels and Histogram adjustment parameter panels launching hidden reduced-resolution graph evaluations that rebuilt heavy upstream branches under a different cache signature.
- Evaluated histogram inputs directly from their connected source/output at the current graph-preview resolution, preserving completed 2D/3D Preview cache entries.
- Downsampled only the CPU-side histogram sample, keeping histogram analysis bounded without changing graph evaluation resolution.
- Added source-branch revision keys so edits to a Levels node's own parameters do not refresh its unchanged input histogram.
- Suspended and cancelled background histogram work during slider/curve/gradient/Levels interaction, then requested it again only when the upstream source actually changed.
- Marked histogram jobs as low-priority background work and exposed their activity in the Evaluation Inspector.
- Removed synthetic per-channel 3D Material Input sinks; connected material maps now evaluate their real source output directly, avoiding redundant 2K cache entries and unnecessary eviction pressure.
- Disabled Qt AnimatedDocks and prevented workspace `saveState()` while a mouse drag is active, mitigating a native Linux Qt crash in `QWidget::setParent` / `QPropertyAnimation` during floating-dock reparenting.
- Added focused source regression coverage for histogram cache reuse, direct material-source evaluation and dock safety.

## 0.18.1 — Direct-preview priority and stable 3D status

- Added a fair, re-entrant evaluation gate that prioritises direct 2D preview/playback/export work over automatic 3D material-map refreshes.
- Prevented a multi-map 3D worker from repeatedly reacquiring the shared evaluator ahead of a waiting 2D edit.
- Made every stopped 2D preview request pre-empt in-flight or scheduled automatic 3D work, including unrelated material branches.
- Added a 300 ms idle grace period before automatic 3D refresh resumes after direct editing.
- Added explicit Evaluation queue wait trace rows, including elapsed scheduler wait and ownership details.
- Deferred inspector-table completion by one event-loop turn so newly evaluated pixels appear before diagnostics are rebuilt.
- Bulk-populated inspector traces with painting disabled during insertion for large graphs.
- Fixed 3D viewport shaking by using a fixed-height, single-line elided status area with the complete message retained as a tooltip.
- Restored the last completed 3D summary when a background refresh is cancelled or yielded.
- Added focused evaluation-gate priority, re-entrancy and 3D status-layout regression coverage.

## 0.18.0 — Evaluation Inspector and active graph flow

- Added a dedicated dockable Evaluation Inspector beside the Timeline instead of relying on 2D/3D preview headers for application-wide work feedback.
- Added live job target, render mode, resolution, elapsed time and determinate/indeterminate progress.
- Added per-node evaluation traces covering backend, computed/cache state, elapsed time, output dimensions/precision, estimated memory and reuse/invalidation details.
- Added explicit final GPU synchronisation/readback and 3D renderer-upload stages.
- Added double-click navigation from inspector rows to graph nodes.
- Added orange animated dashed flow only on connections entering nodes that remain active beyond the existing 180 ms feedback threshold.
- Kept wire animation and inspector state runtime-only, rate-limited and excluded from graph serialization.
- Preserved existing workspaces while automatically introducing the new inspector for users whose saved layout predates it.
- Added focused source and CPU runtime tests for inspector wiring, traces, cache hits and downstream-only invalidation.

## 0.17.7 — Correct linear Gradient Map output

- Fixed Gradient Map interpreting display-sRGB hexadecimal stops as if they were already linear graph values.
- Kept ramp interpolation in display-sRGB so the generated gradient visually matches the inline Qt editor and familiar authoring-tool behaviour.
- Converted the interpolated RGB result to linear light before exposing it to downstream nodes; alpha remains an unmodified linear coverage value.
- Matched the NumPy CPU and WGSL/WebGPU implementations.
- Restored black-to-white identity in the 2D preview: a 50% greyscale input now displays as RGB 128 rather than approximately RGB 188 after Gradient Map.
- Added focused regression coverage for black/white identity, coloured multi-stop interpolation, exact stop colours, alpha handling and WGSL source parity.

## 0.17.6 — Normalised, calmer noise evolution

- Changed built-in noise Evolution parameters and the bundled Voronoi package from -100…100 to a normalised 0…1 loop phase.
- Added legacy graph migration that wraps old out-of-range Evolution values to their equivalent phase.
- Reduced the periodic temporal lattice from sixteen cells to four, making a standard 120-frame loop evolve smoothly instead of boiling through many unrelated states.
- Removed temporal frequency multiplication across fractal octaves in CPU and WGSL implementations for Fractal, Ridged, Billow, Turbulence and Voronoi Fractal noise.
- Kept all octaves on one coherent temporal phase while retaining independent spatial frequency, seed and amplitude behaviour.
- Made Gaussian fine detail share the base temporal loop instead of evolving at twice its speed.
- Changed White Noise's default Evolution Steps from sixteen to four.
- Updated Evolution descriptions to recommend Time → Loop Phase or Loop Phase → Phase and clarify that Seconds/Frame should be normalised first.
- Added focused tests for parameter ranges, exact loop closure, legacy wrapping, calmer 30 FPS deltas and matching CPU/WGSL temporal structure.

## 0.17.5 — Incremental branch previews and visible automatic 3D work

- Added independent live evaluation messaging to the 3D panel, including active material map, source node, resize and renderer-upload stages.
- Applied pulsing orange node feedback to 3D Output and uncached nodes involved in material evaluation.
- Added content-revision deduplication so enabled 3D Outputs update automatically for connected-branch changes without restarting for selection, layout or unrelated branches.
- Stopped 3D Output from being evaluated as an ordinary 2D image when double-clicked.
- Made explicit 2D active-node changes cancel and supersede stale locked output previews immediately.
- Scoped interactive render mode to the edited node and its downstream dependants, preserving normal Preview cache signatures for unchanged upstream nodes.
- Fixed downstream Levels edits restarting Fluvial/Thermal Erosion, including named erosion-output paths.
- Reused the graph-preview resolution for 3D material evaluation and downsampled only final material maps, preventing lower-resolution 3D previews from rebuilding completed 2K branches.
- Added regression coverage for branch-local invalidation, upstream cache preservation, 3D material activity, automatic request deduplication and active-preview switching.

## 0.17.4 — Truthful final GPU and readback feedback

- Added a dedicated finalisation activity stage around GPU queue completion and texture readback into the 2D preview.
- Kept Image Output visibly active with an indeterminate orange bar until the final preview pixels are genuinely available.
- Highlighted the last submitted GPU producer alongside the output when they are different nodes.
- Replaced the generic exact-preview message with live node, stage and resolution details in both the 2D preview header and application status bar.
- Added the current runtime stage to active-node tooltips without serialising any feedback state.
- Added finalisation/readback timing to the completed-preview status summary.
- Preserved performance by reusing the existing mandatory final readback rather than inserting extra per-node GPU synchronisation points.
- Extended evaluation-feedback regression coverage for the previously invisible post-node GPU/readback interval.

## 0.17.3 — Cooperative erosion previews and truthful GPU progress

- Changed iterative GPU progress to advance only after submitted batches have actually completed, including the final output-selection pass.
- Added cooperative preview batching, cancellation checks and short yields between completed batches to avoid building a massive hidden GPU queue and to reduce desktop-wide frame drops during long terrain solves.
- Replaced the old 1024-pixel Automatic-quality threshold with explicit render intent: live 2D/3D previews use Preview counts, exports use Final counts, and explicit Preview/Final choices still override Automatic.
- Added bounded interactive-drag workloads for Fluvial Erosion, Thermal Erosion and Flow Accumulation, followed by one exact authored-quality render on slider release.
- Prevented stale 3D material evaluation from queueing behind active 2D parameter edits; 3D work now waits until stopped 2D feedback has settled.
- Allowed matching 2D and 3D preview resolutions to share expensive upstream preview caches.
- Added 2048, 4096 and Match 2D Preview choices to the 3D Output texture-resolution control.
- Throttled intermediate node-progress signals to approximately 12 Hz while preserving exact start, final and clear events.
- Added focused regression coverage for preview/final intent, interactive caps, GPU completion waits, 2D/3D cache compatibility and deferred material scheduling.

## 0.17.2 — In-node evaluation feedback

- Added pulsing orange node activity outlines so long-running evaluations visibly show when work is still in progress.
- Added per-node progress bars, including determinate progress for iterative erosion passes and indeterminate activity for other node evaluations.
- Cleared transient node activity state on cancellation, completion and preview failures to keep the graph view accurate.

## 0.17.1 — Smooth interactive parameter previews

- Replaced the 110 ms trailing 2D preview debounce with a leading-edge, continuously throttled scheduler.
- Added immediate first-response rendering and an approximately 30 FPS maximum dispatch cadence for inexpensive 2D graphs.
- Coalesced every edit made during an in-flight render into one newest-state request, avoiding render cancellation, starvation, overlap and queued obsolete work.
- Applied the same scheduler to the heavier 3D material preview at an approximately 15 FPS maximum cadence.
- Guaranteed that the final authored value is rendered after interaction settles, even when a previous evaluation was still running.
- Added focused scheduler regression coverage for leading-edge dispatch, timer non-restarting, in-flight coalescing and separate 2D/3D cadences.

## 0.17.0 — Coordinate and distortion foundation

- Added UV Gradient with a typed Vector output.
- Added explicit Cartesian to Polar and Polar to Cartesian nodes with centre, radius, angle direction and wrapping controls.
- Added dedicated Tile, Offset, Rotate, Scale and Mirror transform nodes.
- Added Swirl and Spherize radial distortion nodes.
- Added typed Vector Warp and two-phase, seamlessly loopable Flow Map Distort nodes.
- Promoted Directional Warp from a GPU-only bundled package to native CPU/WebGPU evaluation while preserving its type ID.
- Retained the old Polar Coordinates type ID as a hidden compatibility node so existing project files remain valid.
- Added reusable CPU/GPU bilinear coordinate sampling, neutral missing-vector behaviour and coordinate/distortion regression coverage.

## 0.16.0 — Stateful simulation foundation

- Added `StatefulNodeSpec` and a dedicated runtime state manager for deterministic frame-dependent nodes.
- Added hot sequential state, bounded 15-frame checkpoints, backwards restoration, branch-aware invalidation and cancellable replay.
- Added CPU state arrays and WebGPU-resident ping-pong textures with no per-frame readback during ordinary sequential playback.
- Added simulation progress reporting, node header badges, per-node reset and timeline-wide reset.
- Added Frame Delay, Temporal Blend and Gray-Scott Reaction Diffusion nodes.
- Added named-output-aware replay of animated upstream branches and support across preview, timeline, 3D material evaluation and animation export.
- Added deterministic, checkpoint, cancellation, reset and CPU/GPU comparison regression coverage.

## 0.15.3 — Faster graph node search

- Changed the transient right-click and loose-connection node-search popup to create a result with one mouse click.
- Restored Return/Enter activation after Up/Down keyboard navigation transfers focus into the result list.
- Kept the persistent Node Library on its existing double-click activation model.
- Added off-screen regression coverage for mouse, keyboard and library activation behaviour.

## 0.15.2 — Visual editor deletion focus fix

- Scoped the graph's Delete shortcut to the graph canvas instead of the entire application window.
- Made Delete and Backspace remove the selected Tone Curve point or Gradient Map stop while its inline editor has focus.
- Consumed deletion keys inside a focused visual editor even when the final two required points/stops cannot be removed, preventing accidental whole-node deletion.
- Added regression coverage for curve and gradient deletion ownership.

## 0.15.1 — Shared visual parameter editor foundation

- Added `VisualEditorCanvas` as the common sizing, interaction, debounce, context-menu and rendering foundation for graphical parameters.
- Migrated Levels, Histogram Range, Histogram Shift, Histogram Scan, Gradient Map, Tone Curve and Animation Curve to the shared editor contract.
- Replaced Gradient Map's separate editor window with a complete inline stop editor.
- Added direct draggable guides to the three dedicated histogram adjustment nodes.
- Added consistent Reset actions, keyboard nudging with fine/coarse modifiers, larger hit targets and shared hover/selection styling.
- Added a curve Grid toggle and improved cycling through overlapping curve points.
- Grouped an entire visual drag into one undo command while preserving debounced live preview updates and an exact final release value.
- Added focused off-screen regression coverage for shared inheritance, sizing, keyboard editing, debounce, inline gradients and drag undo boundaries.

## 0.15.0 — Graph workflow and direct wire editing

- Added hidden graph-only Reroute nodes with dynamic Greyscale, Colour, Vector, Scalar, Vector2 and Vector3 typing.
- Added wire double-click, wire context-menu and **R** shortcut insertion for reroute dots.
- Added **X**-drag wire cutting with live intersection highlighting and one-step undo.
- Added loose-connection search filtered by port compatibility, with automatic creation and connection of the selected node.
- Added direct insertion of compatible one-input/one-output nodes by dropping library entries or newly created unconnected nodes onto wires.
- Added left/centre/right and top/middle/bottom alignment plus horizontal/vertical distribution under **Edit → Arrange**.
- Added serialized true pass-through bypass for eligible processing nodes, exposed through an on-node power icon and **B** shortcut.
- Added continuous edge auto-pan while drawing connections across a large graph.
- Widened connection hit testing for dependable wire interaction while preserving the visible stroke width.
- Bumped the serialized graph schema to version 9 and added evaluator, serialization, model and off-screen Qt interaction regression tests.

## 0.14.2 — Persistent, tabbed and floating workspace

- Persisted the main-window geometry, dock positions, sizes, visibility, tab groups and floating-panel geometry in application settings rather than graph files.
- Saved settled workspace changes immediately through synced `QSettings`, so the latest arrangement survives both normal exits and most application crashes.
- Enabled closable, movable and floatable behaviour for Node Library, 2D Output, 3D Output, Parameters and Timeline.
- Enabled nested and tabbed dock groups with tabs positioned above their panels.
- Added **View → Tab 2D and 3D Outputs** as a quick way to combine the large preview panels.
- Added **View → Reset Workspace Layout** and visibility toggles for every panel.
- Added off-screen recovery for the main window and floating docks when a saved monitor is no longer connected.
- Added tab styling and a focused workspace-layout regression test.

## 0.14.1 — Inline graphical curve editors

- Renamed the image **Curve** node to **Tone Curve** and the scalar **Curve** node to **Animation Curve** without changing serialized type IDs.
- Removed the separate curve-editing dialog.
- Added a fixed-height graph directly to both nodes' Parameters views.
- Added draggable points, double-click creation, Delete removal, coordinate fields, Add / Remove / Reset controls and integrated interpolation selection.
- Matched the displayed curve to the actual tone-curve Hermite and animation-curve smoothstep evaluation paths.
- Preserved `0–1` tone-curve bounds and the animation curve's wider numeric range.

## 0.14.0 — Dedicated adjustment nodes

- Added Histogram Range, Histogram Shift and Histogram Scan with live upstream histogram previews.
- Added dedicated Brightness, Contrast, Exposure, Gamma, Posterize and image Clamp nodes.
- Added separate Hue Shift, Saturation and Lightness nodes instead of an HSL super-node.
- Added an image Curve node with an eight-point editor and linear or smooth Hermite interpolation.
- Added CPU reference implementations and matching WGSL kernels for all thirteen nodes.
- Added a focused adjustment regression test and an individual manual testing guide.

## 0.13.4 — Compact Levels histogram

- Fixed the Levels histogram vertically stretching to fill a tall Parameters dock.
- Preserved responsive horizontal sizing while keeping the graph at its intended 230 px editor height.
- Added a regression test for the fixed-height behaviour.

## 0.13.3 — Histogram Levels editor

- Rebuilt Levels around Level In Low/High/Mid and Level Out Low/High.
- Added a live upstream histogram with draggable five-handle editing.
- Added one-shot Auto Level, output-range Invert and Histogram/Sliders quick actions.
- Added Intermediary Clamp and Passthrough behaviour.
- Added Luminance, Red, Green, Blue and Alpha histogram inspection where applicable.
- Preserved scalar animation sockets in the precise slider interface.
- Added legacy Black/White/Gamma migration and CPU/GPU regression tests.

## 0.13.2 — Expanded Blend modes

- Renamed Blend image inputs from A/B to Foreground/Background while preserving the greyscale Opacity mask.
- Moved Replace / Copy to the top of the list and made it the default.
- Added Subtract, Divide, Add Sub / Linear Light, Overlay, Soft Light, Hard Light, Exclusion, Colour Dodge and Colour Burn.
- Retained Add, Multiply, Minimum, Maximum, Screen and Difference.
- Implemented the same formulas in NumPy and WGSL, including W3C-style Soft Light and protected divide/dodge/burn boundaries.
- Added compatibility migration for older A/B Blend connections, including reusable group interfaces.
- Added CPU/GPU and opacity-mask regression tests.

## 0.13.1 — Fluvial erosion quality rewrite

- Replaced the local four-neighbour water/sediment filter with a stream-power fluvial solver.
- Added eight-direction drainage routing, a smoothed routing surface and depression handling for coherent watersheds.
- Removed per-pixel rain noise in favour of broad seamless rainfall variation.
- Added separate erosion-pass and drainage-pass quality controls.
- Added Channel Depth, Tributary Density, Headwater Detail, Valley Widening, Bank Erosion, Deposition, Sediment Spread, Macroform Preservation and Post-Thermal Smoothing.
- Added a dedicated Channel Mask output and retained Eroded Height, Erosion, Deposition, Flow Accumulation, Water, Sediment, Wetness and Flow Direction.
- Rebuilt the starter terrain graph around broad ridged macroforms and a pre-erosion blur.
- Added regression tests for drainage concentration, sparse channel networks, macroform correlation, seamless translation behaviour and GPU cancellation.

## 0.13.0 — Hydraulic and fluvial erosion

- Added a multi-pass GPU Hydraulic Erosion node with rainfall, water flow, sediment transport, erosion, deposition and evaporation.
- Added Rainfall Mask, Hardness, Initial Water and Sediment Source inputs.
- Added Eroded Height, Erosion, Deposition, Flow Accumulation, Water, Sediment, Wetness and vector Flow Direction outputs.
- Added channel-incision, sediment-capacity, gravity, viscosity, rainfall-variation and quality controls.
- Added standalone Flow Accumulation and Flow Direction terrain-analysis nodes.
- Added seamless, closed and drain boundary behaviour for hydraulic and drainage processing.
- Added cancellable ping-pong WebGPU state for hydraulic and accumulation iterations.
- Added CPU references and `tests/hydraulic_erosion_test.py`.

## 0.12.0 — Terrain foundation and iterative GPU compute

- Added Slope, Curvature, Terrace, Height Combine and Height Blend terrain nodes with CPU references and WGSL kernels.
- Added multi-pass Thermal Erosion with Eroded Height, Erosion and Deposition outputs plus an optional Hardness protection mask.
- Added Preview/Final iteration counts and Seamless / Wrap, Closed and Drain boundaries.
- Added iterative WebGPU ping-pong state textures and stale-preview cancellation.
- Added terrain-specific tests and `docs/TERRAIN.md`.

## 0.11.1 — Noise quality correction

- Rebuilt Ridged Noise as a weighted ridged multifractal with octave feedback, ridge offset, sharpness, valley width and octave weighting controls.
- Rebuilt Billow Noise around paired decorrelated gradient fields with dedicated Puffiness, Softness and Fine Detail controls.
- Rebuilt Turbulence Noise around multi-octave domain warping with warp scale, strength, direction and directional-bias controls.
- Reworked Gaussian Noise into a smooth, tileable Gaussian lattice field. Smoothness 0 preserves the old hard-cell look, while the default uses smooth interpolation, diagonal lattice blending, fine detail and disorder to remove the pixel-block appearance.
- Preserved exact spatial tiling and Evolution 0→1 temporal loops for all revised noises.
- Added dedicated WGSL kernels and CPU references for all four corrected nodes.
- Added numerical visual-distinction and smoothness regression tests.

## 0.11.0 — Noise foundation and high-quality periodic generators

- Replaced the original square-lattice Fractal Noise with periodic gradient FBM.
- Preserved the previous algorithm as a dedicated Value Noise node.
- Added Gradient / Perlin Noise, Simplex-style Noise, Worley Noise, White Noise and Gaussian Noise.
- Added Ridged Noise, Billow Noise, Turbulence Noise and Voronoi Fractal.
- Added loopable Evolution, Loop Cycles, Disorder, Disorder Scale, Lacunarity, Gain/Roughness, Contrast, Balance and other node-specific controls.
- Marked all numeric noise controls animatable so they can be exposed as scalar graph sockets.
- Upgraded bundled public-package Voronoi Noise to version 2.0 with loopable feature-point motion, multiple distance metrics, edge width/softness and four named outputs.
- Added declarative public-package multi-output support through `[[outputs]]`, `output_parameter` and selector values.
- Added trusted CPU references for bundled packages without allowing user-installed packages to execute Python.
- Added shared WGSL include preprocessing and a reusable noise common library.
- Added CPU/GPU, seam, loop, animation and multi-output regression tests in `tests/noise_foundation_test.py`.

## 0.10.0 — 3D material and terrain preview foundation

- Added an independent dockable 3D Preview driven by enabled 3D Output nodes rather than the active 2D node preview.
- Added a typed 3D Output material interface for Albedo, Emissive, Normal, Height, Ambient Occlusion, Metallic, Roughness, Specular, and Opacity.
- Added a custom WGSL vertex/fragment renderer on the existing WebGPU device, embedded in PySide6 through rendercanvas's safe bitmap-presenting QRenderWidget.
- Added height-map vertex displacement, configurable midpoint/inversion/amount, height-derived normals, normal-map strength, and OpenGL/DirectX normal-Y conventions.
- Added Opaque, Cutout, and Transparent surface modes, two-sided rendering, cutout threshold, emissive intensity, and opacity handling.
- Added procedurally generated Terrain Plane, Flat Plane, Sphere, and Cube meshes. Terrain resolution can be selected from 32×32 through 512×512.
- Added 1×1 and 3×3 terrain tiling for seam and infinite-terrain inspection.
- Added glTF 2.0 `.gltf`/`.glb` custom preview mesh loading with UVs, generated normals when absent, and indexed/non-indexed triangle primitives.
- Added orbit, zoom, bounded pan, frame/reset, and Perspective/Top/Front/Side camera controls.
- Added neutral environment light, directional sun controls, configurable background, optional surface grid, and screenshot capture.
- Added timeline-aware material evaluation so animated texture branches update in the 3D preview while static branches remain cached by the graph evaluator.
- Added a starter terrain graph connecting noise-derived height, colour, normal, and roughness branches into 3D Output.
- Added `tests/three_d_preview_test.py`, including an actual offscreen WebGPU render and custom glTF import.
- Added `rendercanvas` as an explicit runtime dependency.
- Current material handoff performs one graph readback and 3D texture upload; direct zero-copy binding is deferred to a later optimisation.
- Bumped the development graph schema to version 8.

## 0.9.0 — Typed image pipeline and native image precision

- Added semantic Greyscale, Colour, Vector/Normal and signal data types throughout the graph model.
- Added type-coloured sockets and connections: grey for masks/data, muted yellow for colour, blue for vector/normal data and green for scalar/vector animation signals.
- Added dashed-red invalid-connection feedback and strict rejection of incompatible image/signal links.
- Added prospective type validation so connection order cannot silently invalidate an already-wired downstream branch. Type-changing parameter edits or disconnections remove links that can no longer be valid.
- Added explicit Colour to Greyscale conversion with Luminance, Average, Maximum, Red, Green and Blue methods in both NumPy and WGSL.
- Made Gradient Map explicitly Greyscale → Colour and Height to Normal explicitly Greyscale → Vector/Normal.
- Made Blur, Levels, Auto Levels, Invert, Transform, Flipbook Decode and output nodes preserve their primary image type. Blend now requires matching A/B image types and a greyscale Opacity mask.
- Reworked Image Input to inspect native source mode, channels and precision before conversion. Native 16-bit greyscale PNGs retain their full 0–65535 range.
- Added Image Input data-type and colour-space overrides plus detected-source information in Parameters.
- Corrected Image Input bilinear sampling to use pixel-centred coordinates, preserving exact source texels at matching dimensions.
- Added linear-to-display-sRGB conversion for colour previews while keeping greyscale and vector data linear.
- Added per-node Output precision controls with Inherit, 8-bit, 16-bit and 32-bit float modes, automatic propagation and a WGSL 8-bit quantisation pass.
- Added R32F logical storage for 32-bit greyscale branches and corrected per-node RGBA32F physical allocation.
- Added a typed-pipeline regression suite covering native 16-bit input, colour round-tripping, connection rejection, dynamic type safety, precision propagation and GPU quantisation.
- Bumped graph schema to version 7. Backward compatibility with older development graph files is intentionally not guaranteed.

## 0.8.4 — Correct imported flipbook playback

- Added a dedicated active-preview path for static imported atlases: the sheet is evaluated once and cached, then individual cells are selected locally on each timeline tick.
- Removed imported Flipbook Decode from the ordinary expensive-graph frame-dropping path during preview playback, eliminating scheduler-induced cell skipping.
- Added Source FPS playback, defaulting to 30 FPS and independent from document duration or flipbook grid dimensions.
- Added Fit to Document Loop and One Cell per Timeline Frame playback modes.
- A connected Phase signal continues to override automatic playback timing.
- Source FPS timing is relative to the document loop start, so entering a non-zero loop range starts at the first atlas cell.
- Unified CPU and WGSL frame selection through shared timing helpers.
- Direct Flipbook Output decoding retains document-loop sampling rather than being treated as a fixed-FPS imported atlas.
- Added requested/displayed cell diagnostics to the 2D preview and status bar.
- Added regression tests for 30/60 FPS cadence, non-zero loop starts, fit-to-loop, frame-perfect stepping, Phase overrides, and cached native-cell extraction.

## 0.8.3 — Flipbook Decode

- Added a GPU/WGSL Flipbook Decode node with Sheet and typed scalar Phase inputs.
- An unconnected Phase input automatically follows the document Loop Phase for immediate animated preview playback.
- Added 2×2, 4×4, 8×8 and custom atlas layouts, partial frame counts, start-cell selection, row-major/column-major ordering, padding, phase offset, reverse and ping-pong controls.
- Added padding-aware bilinear cell sampling that clamps within the selected frame to prevent neighbouring-cell colour bleed.
- Added direct Flipbook Output → Flipbook Decode support. The decoder inherits the output's sampled frame range and evaluates the selected authored frame without requiring an intermediate exported file.
- Imported flipbooks from Image Input remain GPU-resident after the normal CPU file decode/upload boundary.
- Added general support for ordinary typed scalar/vector inputs on image-processing nodes, extending the motion graph beyond exposed parameter sockets.
- Flipbook Decode outputs an ordinary image, so decoded frames can feed Levels, Gradient Map, Warp, Blend, a new Flipbook Output, or any other downstream node.
- Added regression coverage for imported atlases, automatic Loop Phase playback, GPU execution, direct output inheritance, typed Phase connections and graph save/load.

## 0.8.2 — Loop phase and FPS-independent flipbooks

- Added a dedicated Loop Phase signal node with Phase, Angle, Frame Index and Pulse outputs.
- Renamed Time.Normalised to Document Phase and Time.Delta to Delta Seconds, while adding Time.Loop Phase.
- Added backward migration for older graph connections and exposed group outputs using the previous Time output names.
- Added sub-frame evaluation positions so exports can sample arbitrary points through a timeline range rather than being limited to integer frames.
- Decoupled Flipbook Output frame count from document frame rate and duration.
- Added Document Loop, Entire Document and Custom Frame Range source modes.
- Added Evenly Across Range and Consecutive Timeline Frames sampling modes.
- Added exclusive-end loop sampling by default, avoiding duplicated first/last cells; endpoint inclusion remains optional.
- Added 2×2, 4×4, 8×8 and Custom flipbook layouts, plus independent custom frame counts.
- Updated complete flipbook preview and final animation export to share the exact same sampling logic.
- Added common 30/60 FPS document animation presets and clearer UI guidance about FPS versus flipbook frame count.
- Migrated pre-0.8.2 Flipbook Output nodes to their previous custom-range/consecutive-frame behaviour when old projects are opened.
- Expanded motion tests for loop-phase wrap points, unique last frames, 16/64-frame sampling and optional endpoint duplication.

## 0.8.1 — Live playback and flipbook preview

- Fixed timeline playback starvation caused by repeatedly restarting the 110 ms edit-preview debounce timer at playback frame rates.
- Playback now keeps at most one preview render in flight, drops obsolete intermediate frames when necessary, and immediately renders the newest playhead position after each completed frame.
- Pausing settles on the exact current playhead frame at full preview quality.
- Flipbook Output now previews the complete configured sprite sheet rather than only the current animation frame.
- Flipbook previews render asynchronously at an automatically bounded per-cell resolution, preserving document aspect ratio without blocking the UI or allocating an enormous preview sheet.
- Invalid frame ranges or insufficient row/column capacity are reported directly in the 2D preview.
- The preview Copy action copies the assembled sheet, while Save image opens the animation export workflow for an active Flipbook Output.
- Expanded motion regression tests for non-starving playback scheduling, asynchronous flipbook preview rendering, and bounded sheet sizing.

## 0.8.0 — Motion foundation

- Added per-document FPS, duration, loop range and playback speed settings.
- Added a dockable timeline with transport controls and latest-frame-wins playback.
- Added typed scalar/vector signal ports and Animation nodes: Time, Cycle, Wave, Scalar Math, Remap, Clamp, Smoothstep, Curve, Combine Vector2 and Split Vector2.
- Added non-destructive parameter socket exposure for animatable numeric controls.
- Added true loopable Fractal Noise evolution in CPU and WGSL implementations.
- Added time-aware cache signatures so static branches stay cached across frames.
- Added Flipbook Output plus PNG/TGA sprite-sheet and image-sequence export.
- Added public custom-node API v2 time uniforms and animatable parameter declarations; API v1 remains supported.
- Added motion and flipbook regression tests.

## 0.7.1 — Node refinement fixes

- Fixed Auto Levels on scalar GPU inputs so it remains neutral greyscale rather than writing only the red component.
- Auto Levels now preserves the incoming logical texture format, matching ordinary Levels behaviour for scalar and colour branches.
- Renamed the `I/O` library category to `Inputs & Outputs` so the slash no longer creates nested `I` and `O` categories.
- Replaced the list-centric Gradient Map editor with an interactive ramp.
- Double-clicking empty ramp space adds an interpolated stop; clicking selects, dragging moves, double-clicking a stop opens its colour picker, and Delete/Backspace or Remove Stop deletes it.
- Added regression coverage for CPU/GPU Auto Levels neutrality, flat category discovery, and direct gradient-stop interaction.

## 0.7.0 — Node quality and workflow pass

- Extract Channels now exposes independent R, G, B and A output sockets.
- Gradient Map now supports an editable multi-stop RGBA gradient with up to eight stops.
- Gaussian Blur uses a proper three-sigma kernel support, reducing hard-edge ghosting and offset-looking artefacts.
- Added Auto Levels for automatic full-range normalization.
- Blend now accepts an Opacity mask input in addition to its global opacity control.
- Generator and I/O categories now use consistent node colours and placement.
- Colour dialogs no longer inherit the selected colour as their button theme.
- Multi-output connections survive copy/paste, project save/load, undo/redo and collapsed groups.

## 0.6.0 — Public WGSL node packages

- Added a declarative external node-package format using `node.toml`, `kernel.wgsl`, and optional SVG icons/documentation.
- Added application-wide custom node library folders, persisted through settings and scanned on startup.
- Added managed installation of ZIP-compatible `.zip` and `.vfxnodepkg` packages with safe archive extraction.
- Added package discovery, manifest validation, duplicate-ID handling, enable/disable controls, and a full Custom Node Diagnostics window.
- Added WGSL compiler feedback with line/column/source context where supplied by the backend.
- Added automatic file watching and hot reload for manifests, shaders, icons, package folders, and user library roots.
- Failed shader edits now preserve the last successfully compiled pipeline while displaying the new error.
- Added missing-package placeholders that preserve node metadata, parameters, positions, and connections until the required package is restored.
- Added visible graph-node error badges for package runtime failures.
- Added public WGSL ABI version 1 with declarative image inputs, float/int/bool/enum/colour parameters, logical output formats, and format propagation.
- Added three nodes authored entirely through the public format: Voronoi Noise, Polar Coordinates, and Directional Warp.
- Added a copyable custom-node template and complete authoring documentation.
- Added automated coverage for discovery, public WGSL execution, persistent library folders, archive installation, last-good hot reload, and missing-node recovery.

## 0.5.0

### Document settings and resolution tiers

- Added per-project width and height settings up to 16,384 pixels, including non-square documents.
- Added aspect-correct interactive preview tiers independent from authored/export resolution.
- Added 16-bit-float and 32-bit-float working precision choices.
- Added Linear/sRGB document colour-space metadata and a project-level default tiling preference.
- New compatible nodes inherit the document tiling default without rewriting existing node settings.
- Upgraded `.vfxgraph` serialization to version 3 while retaining older-project loading.

### Physical texture formats and memory use

- Replaced the all-RGBA32Float GPU allocation path with format-aware physical textures.
- Scalar masks and heights now use `R32Float`; colour outputs use `RGBA16Float` or `RGBA32Float` according to document precision.
- Added `RG32Float` backend support for future two-component vector and flow-map nodes.
- Added format propagation through compatible scalar processing branches.
- Upload, readback, cache accounting, shader-pipeline variants, and missing-input resources now respect actual channel count and storage precision.
- Updated scalar-sensitive WGSL kernels so threshold, gradient mapping, normal generation, extraction, packing, and blending preserve correct semantics.

### Export system

- Added **File → Export Textures…** with batch selection of named Image Output nodes.
- Added full-resolution and custom-resolution evaluation independent from the preview tier.
- Added 8-bit and genuine 16-bit PNG writing for grayscale, RGB, and RGBA.
- Added 8-bit TGA and raw little-endian R16 export.
- Added channel selection, luminance extraction, inversion, Linear/sRGB encoding, filename templates, output folders, and export presets.
- Added editable names to Image Output nodes for batch filenames and output selection.

### Image Input

- Added an Image Input node with PNG, TGA, JPEG, BMP, TIFF, and WebP decoding through Pillow.
- Added sRGB/Linear interpretation, Stretch/Contain/Cover fitting, and Tile/Clamp sampling.
- Added Browse and Reload controls in the Parameters panel.
- Added image-file drag and drop directly onto the graph canvas.
- Added optional base64 project embedding for portable `.vfxgraph` files.
- Image decoding remains a deliberate CPU operation followed by one GPU upload for downstream WGSL processing.

### Autosave and recovery

- Added atomic delayed and periodic autosaves in the platform application-data directory.
- Added startup recovery prompts for newer unsaved work and a manual **Recover Autosave…** action.
- Normal save, discard, new-project, and clean-close flows remove stale recovery data.
- Guarded asynchronous preview completion against shutdown-time Qt object destruction.

### Expanding graph canvas

- Replaced the effectively fixed graph boundary with a content-relative scene rectangle that expands as nodes and groups move.
- Added generous soft pan limits around authored content so users cannot reach a hard edge or become lost in endless empty space.
- Scene bounds refresh during graph changes, dragging, resizing, and viewport changes.
- Frame operations use authored content bounds instead of the padded navigation scene.

### Tests and documentation

- Expanded renderer tests for real `R32Float`, `RGBA16Float`, and `RGBA32Float` allocations, Image Input upload, CPU/GPU agreement, and existing scale/caching behaviour.
- Expanded smoke tests for rectangular documents, aspect-correct previews, image import, 16-bit PNG, R16 size, and canvas growth/clamping.
- Updated user and architecture documentation for the complete 0.5 foundation.

## 0.4.1

### Complete built-in WGSL migration

- Added WGSL compute kernels for Colour, Linear Gradient, Radial Gradient, Circle, Rectangle, Checker, Invert, Levels, Threshold, Transform 2D, Gradient Map, Height to Normal, Extract Channel, and Channel Pack.
- All 19 current built-in image nodes now use WebGPU in Auto/GPU mode while retaining their NumPy/Pillow CPU reference implementations.
- Extended Gaussian Blur's WGSL path across its full exposed 0–128 radius range.
- Kept intermediate images GPU-resident across complete built-in graphs, with safe CPU fallback still available for shader/driver failures and future CPU-only nodes.
- Aligned the CPU Fractal Noise reference with the deterministic WGSL hash so backend comparisons are stable.
- Added logical single-channel format declarations to greyscale generators and conversion nodes.

### Group interaction

- Expanded group interiors now behave like empty graph canvas, allowing rubber-band selection inside frames.
- Group movement begins only from the title bar; the bottom-right resize handle remains interactive.
- Collapsed groups continue to behave like normal compact nodes across their full body.

### Testing

- Added CPU/GPU comparison coverage for every built-in node.
- Added a full reachable graph containing every built-in node type and verified it completes without CPU fallbacks.
- Added maximum-radius GPU blur coverage and unconnected Channel Pack alpha-default coverage.
- Added a regression test for selection rectangles started inside expanded groups.

## 0.4.0

### WebGPU/WGSL vertical slice

- Added `wgpu-py` and a real WGSL compute backend.
- Added inspectable WGSL kernels for Constant, Fractal Noise, Blend, Gaussian Blur, and Image Output.
- Added per-node hybrid CPU/GPU execution, including CPU-to-GPU upload and GPU-to-CPU readback at backend boundaries.
- Added persistent Auto / GPU / CPU renderer selection.
- Added safe per-node CPU fallback for unsupported shader parameters, compilation/validation failures, and unavailable adapters.
- Added renderer diagnostics showing adapter details, migrated node IDs, and cache use.

### Large-graph foundations

- Replaced recursive graph evaluation with an iterative demand-driven topological planner.
- Added immutable graph snapshots for safe worker-thread evaluation.
- Added debounced background previews and latest-edit-wins cancellation.
- Added content-addressed cache signatures so layout changes do not invalidate images and parameter edits invalidate only downstream nodes.
- Added byte-budgeted CPU and GPU LRU caches with explicit texture destruction.
- Added resource pinning and final-consumer release so evicted intermediates can be reclaimed during large evaluations.
- Added logical R16F, RG16F, RGBA16F, and RGBA32F format metadata.
- Added a configurable render-cache budget.

### Testing and tools

- Added CPU/GPU reference tests and a five-node WGSL vertical-slice test.
- Added hybrid-graph, downstream-cache, LRU-eviction, and 1,501-node deep-chain tests.
- Added `tools/stress_test.py` for configurable reachable/disconnected graph benchmarks.
- Updated architecture and node-authoring documentation for the hybrid renderer.

## 0.3.0

### Undo and redo

- Added a complete graph undo stack with Edit menu actions and toolbar buttons.
- Added `Ctrl+Z` undo plus `Ctrl+Shift+Z` and `Ctrl+Y` redo.
- Covers node creation/deletion/paste, connections and connection replacement, parameters, movement, grouping, collapse, resize, membership, and group metadata.
- Continuous edits to the same slider or text field merge into one logical undo step.
- Saved and opened documents correctly establish a clean undo state.

### Groups and reusable nodes

- Added resizable Unreal-style comment frames with editable names and descriptions.
- `Ctrl+G` creates a frame around selected nodes; empty frames are available from the Edit menu.
- Moving a frame moves all member nodes. Moving nodes into or out of a frame updates membership on release.
- Added non-destructive collapse/expand. Internal nodes and internal wires are hidden while group boundary ports remain usable.
- Group inputs are generated from un-driven internal inputs; group outputs are generated from terminal internal nodes, including multiple outputs.
- Public group ports can be renamed, reordered, shown, or hidden. Ports used by existing external connections are protected from being hidden.
- Added manually exposed and renameable group parameters.
- Added human-readable `.vfxnode` export, a persistent User category in the Node Library, drag-and-drop instancing, and an action to open the user-node folder.
- Copy/paste and `.vfxgraph` persistence now include complete groups, internal nodes, exposed parameters, and collapse state.
- Deleting or ungrouping a frame deliberately leaves its contained nodes intact.

### Testing and documentation

- Expanded the smoke test to cover undo/redo, group visibility and wire routing, parameter command merging, reusable group assets, and project round-tripping.
- Updated the architecture documentation and application screenshot.

## 0.2.1

### Graph connections

- Connections can now be dragged from an input port to an output port as well as from an output port to an input port.
- Input-to-input and output-to-output connections remain invalid.
- Reverse-direction drags use mirrored Bezier handles so the temporary wire leaves an input port naturally to the left.
- Added a regression test for direction-independent connection creation.

## 0.2.0

### Graph workflow

- Added Ctrl+C/Ctrl+V node copying and pasting.
- Multi-node copies preserve relative placement and connections between copied nodes.
- Connections to nodes outside the selection are deliberately excluded.
- Pasted selections are centred at the mouse position and receive new node IDs.
- Added drag-and-drop creation from the Node Library while retaining double-click creation.

### Seamless textures

- Replaced Fractal Noise with a periodic value-noise implementation that wraps in X and Y.
- Circle, Rectangle, and Radial Gradient now use repeating UV distance, including shapes that cross an edge.
- Linear Gradient now has Repeat enabled by default.
- Gaussian Blur now samples across opposite edges rather than extending border pixels.
- Height to Normal now uses wrapped central differences.
- Transform 2D remains tiled by default.

### 2D preview

- Added a Tile 3×3 seam-inspection mode.
- Added mouse-wheel zoom centred on the cursor.
- Added left- or middle-drag panning.
- Added a Fit control to reset zoom and pan.
- High zoom uses crisp pixel display while reduced views remain smoothly filtered.

### Project and testing

- Improved Linux and Windows launcher scripts so they use the project virtual environment directly.
- Expanded the smoke test to cover seamless noise, wrapping shapes, node clipboard behaviour, and preview modes.
