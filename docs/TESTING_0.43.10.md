# VFX Texture Lab 0.43.10 testing checklist

## Rounded Cylinder

1. Select **Rounded Cylinder** and inspect it from above and below. The surface should curve continuously into one pole at each end; no flat top or bottom disc should remain.
2. Enable the UV grid or use a square checker material. The circumference should show roughly twice the horizontal texture frequency of 0.43.9, with less horizontal stretching.
3. Connect a detailed Height map and raise displacement. Check the wall, shoulders and domes for even deformation without the old broad cap bands.
4. Compare Low, Medium, High and Ultra. Silhouette and displacement density should increase steadily without changing the underlying shape.

## Rounded Cube

1. Select **Rounded Cube** and compare each geometry-quality level with displacement enabled.
2. The shape and UV layout should remain familiar, but Medium/High/Ultra should retain finer height detail than 0.43.9.

## Material Tiling

1. Open 3D Preview Settings and adjust **Material Tiling**. The slider and value field should move only in whole numbers from `1×` through `32×`.
2. Confirm Base Colour, Normal, Height/displacement, Roughness, opacity and debug views all use the same repeat count.
3. Save and reopen the graph; the integer value should persist.
4. Open a pre-release graph that stored a fractional tiling value such as `2.83`; it should load as the nearest whole number (`3×`).
5. On Terrain Plane, confirm Material Tiling remains independent of Terrain Tiling `1 × 1 / 3 × 3`.

## Regression

- Cycle all lighting presets and built-in meshes.
- Check Perspective and Orthographic cameras.
- Verify Custom Mesh still loads normally.
- Confirm changing Material Tiling redraws the viewport without reevaluating graph textures.
