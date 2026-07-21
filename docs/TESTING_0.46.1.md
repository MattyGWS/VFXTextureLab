# Testing VFX Texture Lab 0.46.1

The most useful test is to create a small graph for each node and double-click its output socket to inspect it at 1:1.

## 1. Histogram Select

1. Connect Linear Gradient to Histogram Select.
2. Move Position and confirm the selected white band travels through the gradient.
3. Increase Range and confirm the band widens equally around Position.
4. Increase Contrast and confirm both transitions sharpen without shifting the centre.
5. Confirm the Inspector histogram shows the centre and both band-edge guides.

## 2. Highpass

1. Feed a photograph or a gradient containing fine noise into Highpass.
2. Increase Radius and confirm broad lighting/colour variation is removed while progressively larger detail remains.
3. Preview a flat input and confirm the result is uniform visible 50% grey.
4. Overlay the Highpass result over the original colour image and confirm neutral areas do not darken it.
5. Compare Clamp against Seamless / Wrap near a deliberately mismatched left/right edge. Clamp should not borrow the opposite border; Wrap should.

## 3. Edge Detect

1. Feed several hard and soft shapes into Edge Detect.
2. Compare Scharr and Sobel.
3. Increase Width and confirm the sampled edge scale grows consistently at 512, 2K and another resolution.
4. Increase Intensity and test Invert.
5. Confirm flat regions remain free of unexpected texture or seams.

## 4. FXAA

1. Create aliased diagonal Polygon, Tile Sampler or thresholded edges.
2. Compare the source and FXAA output at 1:1.
3. Test Low, Medium and High and adjust both thresholds.
4. Confirm Subpixel 0 leaves the source unchanged and 1 gives the strongest correction.
5. Test a colour image and a generated normal map. The normal output should shade normally in 3D without dim or invalid vectors.
6. Test Preserve Alpha with a hard transparent silhouette.

## 5. Crop

1. Feed a recognisable image into Crop.
2. Adjust all four bounds and confirm the selected rectangle fills the output.
3. Swap Left/Right or Top/Bottom numerically and confirm the crop remains valid rather than failing.
4. Compare Nearest and Bilinear on pixel art or a small checker pattern.
5. Repeat on a rectangular document and a normal map.

## 6. Auto Crop

1. Place an off-centre white or transparent shape inside a large empty canvas.
2. Confirm Crop Auto moves the detected content to the centre without changing its size.
3. Confirm Crop Square extracts and fills from the smallest enclosing square without sampling outside the source.
4. Confirm Fit (Keep Ratio) centres the complete shape without distortion.
5. Confirm Fill (Stretch) fills the output and visibly changes aspect ratio where appropriate.
6. Test luminance detection, Use Alpha, Threshold and Padding.
7. Test Auto, Nearest and Bilinear filtering and a completely empty input.

## Evaluation and compatibility

- All six nodes should appear in search and accept only semantically compatible connections.
- Histogram Select, Highpass, Edge Detect, FXAA and Crop should remain GPU-resident in the Evaluation Inspector.
- Auto Crop may show one CPU statistics/readback stage for content-bound detection followed by GPU resampling.
- Existing 0.46.0.4 graphs should open unchanged; the graph format was not bumped for this milestone.
