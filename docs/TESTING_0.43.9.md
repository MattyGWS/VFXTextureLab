# VFX Texture Lab 0.43.9 testing checklist

## Rounded preview meshes

1. Activate a complete Material and open 3D Preview settings.
2. Select **Rounded Cube** and orbit around it. Confirm the broad faces remain flat while edges and corners are smoothly rounded.
3. Select **Rounded Cylinder**. Confirm the side wall, rounded shoulders and flat top/bottom caps render correctly.
4. Cycle Low, Medium, High and Ultra Geometry Quality. The silhouettes should become smoother without changing the mesh proportions or UV layout.
5. Test Base Colour, Normal Map, Height displacement and UV Checker on both new meshes.

## Material tiling

1. Set Material Tiling to `1×`, then `2×`, `4×` and a fractional value such as `0.5×`.
2. Confirm the texture repeats on Sphere, Cube, Rounded Cube, Rounded Cylinder, Flat Plane and a UV-mapped Custom Mesh without creating duplicate geometry.
3. On Terrain Plane, compare Material Tiling with Terrain Tiling `1 × 1` and `3 × 3`. They should remain independent: one changes UV repetition, the other duplicates terrain geometry for seam inspection.
4. Connect Height and Normal maps. Confirm their detail frequency follows the same tiling value as Base Colour.
5. Test Alpha Cutout or Opacity and verify the repeated coverage agrees with the repeated colour texture.
6. Save and reopen the graph. Material Tiling should retain its value.

## Lighting presets

1. Apply Studio, Soft, Dramatic and Flat to a neutral mid-grey material.
2. Confirm none is washed out at its default exposure.
3. Their environment intensities should be Studio `0.28`, Soft `0.30`, Dramatic `0.24`, and Flat `0.35`.
4. Confirm VFX Studio and the other unaffected presets retain their previous values and character.
5. Adjust Environment Intensity manually and confirm the preset changes to Custom as before.

## Regression commands

```bash
python tests/three_d_preview_test.py
python tests/three_d_viewport_presentation_test.py
python tests/three_d_renderer_quality_test.py
python tests/three_d_viewport_controls_test.py
```
