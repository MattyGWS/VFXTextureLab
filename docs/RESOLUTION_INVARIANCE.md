# Resolution-invariant graph evaluation

Version 0.29.0 separates **authored spatial size** from the temporary resolution used to evaluate the graph.

Changing **Preview Max** should change sampling precision and performance, not the proportions of the procedural result. A graph previewed at 512 should therefore retain the same silhouette, blur reach, bevel width and normal strength when evaluated at 1024, 2048 or during export.

## Relative pixels

Artist-facing pixel-distance controls now use **relative pixels**, shown as `rpx` in the Parameters panel.

The reference canvas is 512 pixels on its longest axis:

- 16 rpx evaluates as 8 pixels at 256.
- 16 rpx evaluates as 16 pixels at 512.
- 16 rpx evaluates as 32 pixels at 1024.
- 16 rpx evaluates as 64 pixels at 2048.

The authored parameter value does not change. CPU and WGSL paths resolve it to the current output resolution immediately before evaluation.

Relative-pixel controls include:

- Gaussian, Directional, Zoom, Anisotropic, Non-uniform and Slope Blur spatial reach.
- Distance and Bevel width/offset.
- Expand / Shrink amount and softness.
- Outline width, offset and softness.
- Aperture size.

Flood Fill's minimum-island area uses `rpx²`, scaling with image area rather than one axis.

## Derivative filters

Height to Normal strength now compensates for the smaller per-pixel height difference at higher resolutions. Curvature applies the corresponding squared resolution compensation required by its second derivative.

Normal-derived Curvature and Curvature Sobel scale their derivative footprint from the same 512-pixel reference. Curvature Smooth evaluates fixed 1×, 2× and 4× reference radii, while HBAO Radius is normalised to the texture size. Increasing output resolution therefore adds sampling detail without shrinking the apparent analysis scale.

Slope already measured derivatives in normalised image space and required no semantic change.

## Normalised nodes

Shapes, polygons, gradients, noises, transforms, distortions, Tile Sampler and Flood Fill metadata already use UV-, cell- or island-relative coordinates. They were audited and retain those normalised semantics.

The 2D preview also uses a stable presentation sampling footprint when Preview Max changes, preventing Qt's upsample/downsample choice from making identical geometry appear to shift slightly on screen.

## Compatibility

Existing parameter values are preserved. The 512-pixel preview—the application's historical default—remains the visual reference, while higher-resolution previews and exports now scale spatial effects to match it.

Explicit atlas padding, flipbook cell padding, iteration counts and other controls whose meaning is intentionally an exact count remain absolute rather than being silently reinterpreted.
