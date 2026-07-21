# Testing 0.49.1 — Persistent Geometry Performance

## Primary dense-Material test

1. Create a Geometry Plane with enough base subdivisions to make the result obvious.
2. Connect it to Geometry Subdivide and use one or two subdivision levels.
3. Connect the Geometry output to a Material node.
4. Connect ordinary image nodes or Constants to Base Colour, Roughness, Metallic and Emissive.
5. Focus the Material and wait for the first mesh evaluation and upload.
6. Repeatedly adjust only the Material channels and Material parameters.

Expected: the first geometry build may still take time according to its triangle count, but subsequent Material changes should not rerun Subdivide or stall the interface for the same duration. The existing mesh remains visible while material maps update.

## Geometry invalidation

1. Keep the Material focused.
2. Change Subdivision Levels or another parameter upstream of its Geometry input.

Expected: the geometry branch evaluates once, a replacement mesh is uploaded once, and later Material-only edits reuse that new result.

## Focus residency

1. Focus a different image or Material node.
2. Return to the Material using the dense procedural mesh.

Expected: the existing resident vertex/index buffers reactivate without a second full upload, subject to the configured cache budget and normal LRU eviction.

## Pure geometry context reuse

Change document preview resolution or begin/end Material playback without editing the pure geometry branch.

Expected: Plane, Box, Cylinder, Disc/Ring, Transform, Subdivide, Normals and Combine results remain reusable because they do not depend on texture resolution. Geometry Displace correctly keeps separate results when its heightmap sampling resolution or animated frame differs.

## Dense wireframe protection

1. Focus a geometry result above 250,000 triangles with 3D Preview Wireframe set to Auto.

Expected: the shaded mesh remains visible, the status text states that Auto wireframe is hidden for the dense preview, and the application does not pause to construct a full unique-edge buffer. Wireframe Always explicitly overrides this protection.

## Diagnostics and cache clearing

Open Render → GPU / Renderer Diagnostics.

Expected: separate entries appear for Procedural geometry CPU cache and 3D renderer geometry cache. Render → Clear Render Cache clears both while keeping the currently displayed frame safe until its replacement is ready.

## Automated regression

Run:

```bash
python tests/geometry_cache_performance_test.py
```

The test verifies that an unrelated Material edit returns the exact same cached MeshData without another geometry evaluation, a true Subdivide edit invalidates the branch, and stable geometry keys reuse renderer vertex/index buffers across wrapper and focus changes.

A renderer-only buffer residency test is also available and does not require a live Qt window:

```bash
python tests/geometry_buffer_cache_unit_test.py
```
