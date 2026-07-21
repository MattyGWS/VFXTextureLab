# Ambient Occlusion (RTAO)

**Ambient Occlusion (RTAO)** generates an ambient-visibility map from a grayscale Height input. It is the high-quality companion to **Ambient Occlusion (HBAO)**.

RTAO uses software ray tracing in a WebGPU compute shader. It does not require hardware ray-tracing extensions. For every output pixel it traces a distributed hemisphere through the 2.5-D height surface, records whether each ray reaches the environment or meets a blocker, and converts the visible-ray ratio into white-to-black ambient occlusion.

## Controls

- **Height Scale** multiplies the vertical relief represented by the Height map. Larger values make the same grayscale difference behave as taller geometry.
- **Samples** sets the number of hemisphere rays per pixel from 4 to 64. Higher values reduce variance and improve small-feature coverage at a substantial performance cost.
- **Distribution** controls where rays are concentrated:
  - **Uniform** distributes rays evenly over the selected solid angle.
  - **Cosine Weighted** favours directions nearer the surface normal.
  - **Horizon Weighted** favours grazing directions and stronger contact/crevice detection.
- **Maximum Distance** sets the furthest horizontal distance at which a surface can occlude the current pixel, measured against the texture's shorter dimension.
- **Spread Angle** sets the hemisphere opening. `1.0` covers the complete upper hemisphere; smaller values tighten the rays toward the surface normal.
- **Denoise** controls the height-aware reconstruction width. `0` exposes the raw stochastic solve. Higher values smooth ray variance while respecting Height discontinuities.
- **Boundary** chooses tileable wrapping or edge clamping.
- **Invert** swaps white and black.

## Performance

RTAO is intentionally expensive. A parameter drag temporarily uses at most six rays and eight march steps. Once editing settles, the node restores the authored sample count and its corresponding full march depth. HBAO remains the preferable node when continuously interactive feedback matters more than accuracy.

The raw ray pass and both denoise passes remain GPU-resident. There is no intermediate CPU readback. The NumPy implementation exists as a reference and fallback, but high-resolution CPU RTAO is expected to be slow.

## Surface handling

The local surface tangent uses a slope-limited gradient. This removes genuine planar slope before intersection tests while refusing to estimate a tangent across hard height discontinuities. Consequently:

- a smooth ramp does not shadow itself;
- the top of a raised binary shape remains white to its silhouette;
- the lower neighbouring surface receives contact occlusion;
- denoising does not smear that lower-surface occlusion onto the raised top.
