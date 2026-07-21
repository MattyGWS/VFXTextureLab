# VFX Texture Lab 0.43.2 Testing

This release separates authored texture edges from display scaling. The 2D Preview must preserve texels, while source shape nodes should generate hard edges unless the artist deliberately adds Edge Softness.

## 1. Polygon at 128 × 128

1. Create a Polygon node.
2. Set Sides to 3.
3. Set the graph resolution to 128 × 128.
4. Double-click the Polygon output and use Fit, then zoom in several steps.

Expected:

- The triangle edge is visibly stair-stepped/pixelated.
- No grey display blur appears between black and white texels.
- Edge Softness defaults to 0.

## 2. Authored hard edge versus soft edge

With the same Polygon:

1. Leave Edge Softness at 0 and save the image.
2. Set Edge Softness to 0.02 and save another image.

Expected:

- The zero-softness file contains a binary hard silhouette.
- The 0.02 file contains intentional fractional edge coverage.
- Zooming either image in the 2D Preview remains nearest-neighbour; the preview does not add further blur.

## 3. Other primitive nodes

Repeat with:

- Shape → Triangle, Disc and Rectangle
- Polygon Burst → Solid

Expected:

- New nodes default to hard edges.
- Edge Softness remains available and functional.
- Polygon Burst Radial Gradient and Angular Gradient retain their intended interior gradients while the outer boundary remains hard at zero softness.

## 4. Resolution changes

Test a hard-edged triangle at 32, 127, 128, 512 and 2048.

Expected:

- Every result is rasterised directly at its authored resolution.
- No resolution receives an automatic soft fringe.
- The stair-step size changes naturally with resolution.

## 5. Preview controls

Check:

- Fit
- Wheel zoom in and out
- Pan
- Tile 3×3
- R/G/B/A channel toggles
- Returning to a cached preview

Expected:

- All display modes preserve texels using nearest-neighbour sampling.
- Panning and cache reuse do not temporarily switch back to smooth scaling.

## 6. Resampling nodes remain intentional

Feed the hard Polygon into Transform 2D or Tile Sampler, then rotate or scale it by a non-integer amount.

Expected:

- Those nodes may produce filtered/soft values according to their own sampling behaviour.
- The 2D Preview displays that authored result exactly and does not add another layer of smoothing.

## 7. Copy and Save image

Use Copy and Save image on the hard Polygon.

Expected:

- The saved/copied texture matches the node data.
- Fit or zoom level does not affect the exported dimensions or pixels.
