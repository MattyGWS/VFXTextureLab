# Testing VFX Texture Lab 0.46.2

> **Superseded Make It Tile controls:** Version 0.46.2.1 replaces the Seam Width/Blur/Detail controls described below with per-axis Mask Size, Mask Precision and Mask Warping. Use [`TESTING_0.46.2.1.md`](TESTING_0.46.2.1.md) for the current seam and 2D gizmo checklist.


Use photographs or scans containing visible lighting gradients, perspective distortion, unique defects and mismatched borders. Inspect results at 1:1 and in Tile 3×3 mode.

## 1. Perspective Transform

1. Load a photograph of a rectangular surface taken at an angle.
2. Set the four corner X/Y pairs to that rectangle's visible corners.
3. Confirm the chosen quadrilateral becomes a full rectangular output rather than an affine approximation.
4. Compare Nearest and Bilinear.
5. Move a corner outside the image and compare Transparent against Clamp.
6. Repeat with a greyscale map and a generated normal map.

The first implementation uses Parameters controls; direct four-corner preview handles are not yet included.

## 2. Lighting Equalisation

1. Feed a surface photograph with a broad left-to-right light gradient into Lighting Equalisation.
2. Increase Lighting Radius until it follows illumination rather than the texture detail.
3. Raise Strength and confirm the broad gradient is reduced while pores, grains and scratches remain.
4. Compare Luminance and RGB Channels on a photograph with a colour cast.
5. Adjust Target Luminance and compare Clamp against Seamless / Wrap.
6. Confirm a normal/vector input passes through unchanged.

## 3. Clone Patch

1. Choose a photograph with one obvious unwanted mark.
2. Set Source X/Y over a clean nearby region and Target X/Y over the mark.
3. Adjust Radius and Feather until the repair blends into its surroundings.
4. Rotate or scale the source to reduce visible repetition.
5. Reduce Opacity and attach a Mask to test restricted repair coverage.
6. Compare Clamp and Wrap near a border.
7. Repeat on greyscale and normal/vector data and confirm the latter still shades correctly.

## 4. Make It Tile Photo

1. Load a non-tiling photograph and enable Tile 3×3 in the 2D Preview.
2. Add Make It Tile Photo with both axes enabled.
3. Confirm the outer tile boundaries join continuously.
4. Adjust Seam Width and Seam Blur and inspect the new central repair region at 1:1.
5. Increase Detail Preservation and confirm smoothing stays closer to the seam rather than restoring a hard discontinuity.
6. Disable one axis and confirm only the other is repaired.
7. Try Clone Patch before Make It Tile on a source with one prominent unique feature.

## 5. Atlas Splitter

1. Create or load an atlas containing irregularly sized and spaced opaque or bright shapes.
2. Select Alpha, Luminance or attach an explicit Mask.
3. Step through Shape Selection and verify each disconnected component can be extracted.
4. Compare Reading Order, Largest First, Left to Right and Top to Bottom.
5. Adjust Threshold, Minimum Area and 4/8 connectivity around noise and diagonal contacts.
6. Compare Crop Auto, Fit and Fill, then test Padding and Isolate Component.
7. Confirm a regular square grid is not required.

Atlas Splitter may show a component-analysis readback/upload stage in Evaluation Inspector.

## 6. Material Crop

1. Assemble a Material with at least Base Colour, Height and Normal.
2. Connect it through Material Crop and then Material Channels or Texture Set Output.
3. Change all four bounds and confirm every requested channel uses the same crop.
4. Confirm the material name and surface settings are preserved.
5. Inspect Evaluation Inspector and confirm viewing one breakout channel does not eagerly evaluate every other channel.

## 7. Material Make It Tile

1. Assemble a deliberately non-tiling multi-channel Material.
2. Connect it through Material Make It Tile and inspect Base Colour, Height and Normal in Tile 3×3 mode.
3. Confirm all authored channels remain spatially aligned and missing channels remain absent.
4. Preview the material in 3D and check that reconstructed normals remain valid rather than becoming dim or flattened.
5. Export through Texture Set Output and confirm the same repaired channels are written.

## Regression and compatibility

- All seven nodes should be searchable under Photogrammetry or Materials.
- Make It Tile Photo, Lighting Equalisation, Clone Patch and Perspective Transform should use WGSL in ordinary image graphs.
- Atlas Splitter is allowed one global component-analysis readback.
- Existing 0.46.1 graphs should open unchanged. Graph format remains version 18.
- Histogram Select, Highpass, FXAA, surface analysis, Blend, material composition, 3D preview, export templates and `.vfxpackage` workflows should continue to work normally.
