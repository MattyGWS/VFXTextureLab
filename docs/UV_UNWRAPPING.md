# UV Unwrapping and UV Preview

Version 0.52.0 introduces **Geometry UV Unwrap** and the first reusable manual-action node workflow.

## Manual execution

Geometry UV Unwrap does not recalculate merely because a parameter changes. Adjust the node, then use the action in the Inspector:

- **Unwrap** creates the first result.
- **Re-Unwrap** applies settings or geometry changes while retaining the previous successful result until the new one completes.
- **Unwrap Again** deliberately regenerates an already-current result.
- **Cancel** stops the active request and keeps the previous successful result.

The node reports Not Run, Running, Up to Date, Out of Date, Cancelled or Failed. Work runs on the cancellable geometry worker and publishes only after the full mesh, UV data and diagnostics are complete. Changes made during execution do not restart the operation; the completed snapshot is marked Out of Date when necessary.

Completed results are compressed into the graph with the source/settings signature, chart IDs and diagnostics. Reopening the graph therefore restores the last successful result without requiring another unwrap.

## Modes

- **Automatic Charts** uses the native `xatlas` bindings for chart creation and packing.
- **Box Projection** places six directional charts in a deterministic atlas.
- **Planar Projection** projects along the mesh's thinnest bounds axis.
- **Cylindrical Projection** creates a body chart plus cap charts.
- **Spherical Projection** creates longitude/latitude UVs with an inspectable wrap seam.

Automatic Charts provides Chart Angle, Chart Quality, Preserve Existing Seams, Pack Resolution, Island Padding, Rotate Islands and Best Packing controls. Projection modes remain useful for simple assets and as a dependency-free fallback.

## 2D and 3D presentation

Focusing the node shows the output geometry in the 3D Preview and the UV atlas in the 2D Preview at the same time. The UV toolbar controls:

- triangle wires;
- island tinting;
- seam highlighting;
- overlap highlighting;
- checker background.

The optional **Preview Texture** input is presentation-only. It appears beneath the UV overlay but does not affect the unwrap signature, geometry cache or manual state. Geometry UV Transform uses the same generic 2D UV presentation.

## Diagnostics

The Inspector reports the backend, chart count, estimated atlas coverage, atlas dimensions, overlapping triangles, zero-area UV triangles and vertices outside the 0–1 range. Red overlap fills and cyan seam lines make validation visible in the 2D Preview.

## Dependency and packaging

Automatic Charts requires `xatlas>=0.0.11,<0.1`. Source testers upgrading to 0.52.1 must run `setup.sh` or `setup.bat` once. xatlas 0.0.11 publishes CPython wheels through 3.13, so Linux setup automatically rebuilds an incompatible Python 3.14 `.venv` with a private managed Python 3.13 runtime instead of attempting a local C++ build. The dependency is explicitly collected and smoke-tested in the automated Windows build.

Graph format 20 identifies projects that can contain persistent manual-operation results. Older graph formats continue to load and migrate automatically.

## Textureless inspection

When Preview Texture is disconnected, the 2D atlas and 3D mesh both use a checker reference automatically. The fallback is presentation-only and never invalidates the stored unwrap.
