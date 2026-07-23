# Testing VFX Texture Lab 0.53.0

Run `setup.sh` or `setup.bat` once after replacing an older project folder. This release adds the binary `embreex`/Embree baking dependency.

## Basic photogrammetry bake

1. Import a textured high-poly OBJ with **Mesh Input**.
2. Build a low branch through **Geometry Delete Small Parts**, optional **Geometry Remesh**, **Geometry Decimate**, **Geometry Normals** and **Geometry UV Unwrap**.
3. Connect the original high mesh to **High Geometry** and the final UV-unwrapped low mesh to **Low Geometry** on **Geometry Bake High to Low**.
4. Connect the scan colour texture to **High Albedo**.
5. Focus the bake node and press **Bake** in the Inspector without changing defaults.

Confirm:

- The application remains responsive and orange activity wires/progress appear.
- Bake status becomes Up to Date.
- Albedo, Normal, Height, Ambient Occlusion and Projection Mask sockets can each be previewed or connected downstream.
- Baked Material displays the low mesh with the available maps together in 3D.
- The Inspector reports the native Embree backend, hit percentage and timings.
- Saving and reopening the graph retains the result without rebaking.

## Manual execution

After a successful bake:

1. Change Island Padding or another bake parameter.
2. Confirm the node becomes Out of Date without starting work.
3. Confirm the previous maps remain visible and downstream connections continue working.
4. Press Re-Bake, then cancel during a longer AO pass.
5. Confirm the previous successful maps remain intact.
6. Press Re-Bake again and allow it to complete.

Changing only **2D Preview** must not mark the result Out of Date.

## Projection diagnostics

- Reduce manual ray distances until some pixels miss and confirm Projection Mask shows black regions.
- Restore Automatic distance and confirm hit coverage improves.
- Test Outward Only and Inward Only on a mesh with cavities.
- Connect a deliberately incompatible cage and confirm a clear topology error appears without replacing a valid previous result.
- Test a matching cage edited outward from the low mesh.

## Map checks

### Albedo

- Confirm high-poly texture features appear in the corresponding low-poly UV islands.
- Toggle Bilinear/Nearest and Preserve Alpha, then rebake.
- Disconnect High Albedo: Normal, Height, AO and Projection Mask should still bake, with an explicit warning that Albedo was skipped.

### Normal

- Compare OpenGL (+Y) and DirectX (-Y).
- Apply the baked Material in 3D and confirm lighting detail follows the high mesh rather than looking like a height-derived approximation.

### Height

- Confirm Automatic Symmetric places the unchanged low surface around mid-grey.
- Test Manual range and Invert.
- Confirm Inspector reports real measured signed minimum/maximum distances.

### Ambient Occlusion

- Compare Draft, Medium and High on a cavity-rich scan.
- Confirm higher presets take longer but the interface remains responsive and cancellation works.
- Test automatic and manual AO distance.

## Output quality

- Test 512, 1024, 2048 and 4096 output where memory permits.
- Test 1×, 2× and 4× supersampling within the 4096 internal-side safety limit (4096/1×, 2048/2× or 1024/4×).
- Confirm larger internal requests are rejected before a large allocation rather than freezing or exhausting memory.
- Inspect island borders with padding disabled and enabled.
- Confirm UV-overlap warnings are not triggered merely by adjacent triangles sharing an island edge.
- Confirm Normal maps remain unit-length after resized downstream previews.

## Scale and platform coverage

Please test the same reference graph on Linux and the automated Windows build. Useful source sizes include:

- Tiny generated meshes for correctness
- A 50k–250k triangle high scan
- A 1M+ triangle high scan with a much smaller low target
- A source with disconnected scan fragments

Report the application version, OS, CPU, high/low triangle counts, output resolution, enabled maps, bake backend, hit percentage, total time and any terminal output.

## Repeatable native stress harness

After setup, run:

```bash
python tools/geometry_bake_stress.py
```

The default scene generates 1,002,528 high-poly triangles, a 2,048-triangle UV low mesh and a 256² Albedo/Normal/Height projection. It must report the Embree backend and at least 99% hits. Add `--ao` to include Draft AO, or lower `--high-subdivisions` for a quicker diagnostic.
