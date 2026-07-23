# High-Poly Geometry Foundations

VFX Texture Lab 0.51.3 establishes the performance and topology layer needed before automatic UV unwrapping and high-to-low baking.

## Native simplification

Geometry Decimate uses the `fast-simplification` compiled quadric-error backend when the current environment contains the new dependency. Run `setup.sh` or `setup.bat` again after replacing an older project folder so the existing `.venv` receives it. The Parameters panel reports **Native QEM (fast-simplification)**, **Native QEM (topology-protected)** when it must stop at the nearest watertight collapse state, or the slower Python compatibility fallback only for unrecoverable native failures.

Imported OBJ data commonly duplicates one geometric position for every UV island or hard-normal group. Decimating those copies independently can make coincident edges move to different locations and visibly split a closed mesh. The 0.51.3 path therefore:

1. welds bit-identical positions into one temporary geometric topology;
2. removes degenerate and duplicate geometric triangles;
3. simplifies the welded positions and triangles natively;
4. replays cached collapse prefixes for nearby Percentage values;
5. restores UV and hard-normal groups as separate render vertices at exactly the same output position;
6. rebuilds area-weighted normals and validates the output topology.

If the requested collapse prefix would open a closed manifold input, the reducer retreats through the cached native collapse sequence and keeps the nearest earlier watertight state. This can stop slightly above the requested triangle percentage, but it avoids both visible cracks and an unnecessary Python fallback.

## Scan cleanup and uniform remeshing

Version 0.52.1 adds two geometry preparation stages before decimation and UV work. **Geometry Delete Small Parts** finds disconnected components on welded geometric positions, so ordinary UV and hard-normal seam copies remain one object while floating scan fragments can be discarded. It can keep only the dominant component or retain every part above a relative vertex, triangle or area threshold.

**Geometry Remesh** is a manual-action voxel operation. It rasterises the source at a relative or absolute object-space voxel size, optionally fills the interior, smooths the scalar field and extracts a fresh closed triangle surface. The rebuilt topology receives smooth normals and no UVs. Unsafe grid dimensions are rejected before allocation, and the completed result uses the same persistent transactional framework as Geometry UV Unwrap.

A typical scan branch is:

```text
Mesh Input → Delete Small Parts → Remesh → Decimate → Normals → UV Unwrap
```

## Background scheduling

Focused geometry evaluation has its own single-worker queue. The graph remains interactive while slow work runs, active geometry nodes receive orange animated wires, and progress appears in the 3D status line and Evaluation Inspector.

Rapid edits use a 160 ms debounce. A newer request invalidates the older presentation immediately. Python import, diagnostics, attribute reconstruction and fallback simplification honour cancellation checkpoints. A native collapse loop already executing cannot be interrupted inside the third-party C++ call, so it finishes in the background and stores its valid collapse sequence; the newest request then replays that sequence instead of recomputing it.

## Mesh diagnostics

Mesh Input and Geometry Decimate publish:

- render vertices and triangles;
- unique geometric positions;
- boundary and non-manifold edges;
- degenerate and duplicate triangles;
- connected components;
- UV-seam and hard-normal-seam vertices;
- closed-manifold status;
- in-memory vertex/index size;
- simplification backend and target/output triangle counts.

These diagnostics are informational foundations for later UV validation and high-to-low baking. They do not automatically repair arbitrary scan topology.

## Large OBJ import

The OBJ importer streams line-by-line into compact numeric buffers and creates indexed seam vertices as faces are parsed. Missing normals are generated with vectorised area-weighted accumulation. Parsed meshes use a bounded cache.

Files of at least 32 MiB skip synchronous metadata parsing when selected. Their Mesh Input node is created immediately and the background geometry evaluation supplies full metadata when the node is previewed.

The current import safety cap is five million triangles. It prevents accidental exhaustion from malformed or unexpectedly huge files while still covering the one-million-triangle scan target used for this milestone.

## Stress tool

Run:

```bash
python tools/geometry_stress.py --triangles 1000000 --obj-roundtrip
```

Optional native reduction:

```bash
python tools/geometry_stress.py --triangles 1000000 --decimate-percent 1
```

The tool reports generation time, mesh memory, topology-diagnostic time, OBJ write/import time, viewport-buffer preparation, automatic wireframe suppression and native backend availability. Add `--json report.json` to preserve a machine-readable result.

The development environment completed the one-million-triangle OBJ round trip with these representative figures:

- 501,426 vertices and 1,000,000 triangles;
- 60,426,089-byte OBJ;
- 28,045,632-byte loaded interleaved/indexed mesh;
- approximately 11.0 seconds for streaming import, normal generation and diagnostics;
- approximately 7.1 seconds for standalone full diagnostics;
- automatic wireframe suppressed above the existing 250,000-triangle limit.

Those timings are environment-specific. The native wheel was unavailable in the build container, so native simplification timing and visible WebGPU presentation must be verified in the normal installed application.
