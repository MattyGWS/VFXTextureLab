# VFX Texture Lab 0.43.4 Testing

## Antialiased geometric edges

1. Create a new Polygon, choose 3 sides and set the document/preview to 128 × 128.
2. Leave Edge Softness at 0 and Edge Rasterisation at Antialiased. The triangle should remain geometrically sharp but contain a restrained one-pixel coverage edge rather than a binary staircase.
3. Zoom above 100%. The 2D Preview should show those exact fractional texels using nearest-neighbour enlargement.
4. Change Edge Rasterisation to Pixel Exact. The same triangle should contain only black and white boundary pixels.
5. Raise Edge Softness in either mode and confirm it creates a wider intentional feather.
6. Repeat with Shape, Polygon Burst and Tile Sampler built-in Triangle/Disc patterns.
7. Open a graph saved in 0.43.3 containing a zero-softness primitive. It should preserve its former Pixel Exact result until changed manually.

## Document default

1. Open Document Settings and change Geometric rasterisation to Pixel Exact.
2. Create a new Polygon and Tile Sampler. Their Edge Rasterisation controls should start at Pixel Exact.
3. Existing nodes should retain their own authored setting.
4. Save and reopen the graph and confirm the document default and per-node settings persist.

## Accurate 2D zoom

1. Preview a 128 × 128 image in a large 2D panel and press Fit. The readout should show the real magnification, usually several hundred percent, not 100%.
2. Press 1:1. The readout must show 100% and one texture texel must occupy one screen pixel.
3. Preview a 2048 image in a smaller panel and press Fit. The readout should show the actual minification percentage.
4. Resize the panel while Fit is active and confirm the percentage updates.
5. Use wheel zoom and confirm the percentage tracks the actual display scale.
6. Repeat in Tile 3×3 mode.

## Single Image Quick Export

1. Connect an image to Single Image Output and open its Quick Export group.
2. Press Quick Export before configuration. Export Outputs should open with only that node selected.
3. Choose a folder, collision policy and Open folder when complete, then export.
4. Press Quick Export again. It should export immediately without reopening setup.
5. Use Change Export Location and confirm the updated destination is remembered.
6. Save and reopen the graph and confirm the destination/open-folder state persists.
7. Confirm Texture Set Output Quick Export still behaves identically.

## Preview/export parity

1. Compare a 128 × 128 antialiased primitive in the 2D Preview at 1:1, its exported PNG at 100% in an image editor, and its 3D material usage. The authored pixels should agree.
2. Confirm the 2D panel uses filtered Fit minification but nearest-neighbour enlargement.
3. Recheck colour, linear mask and normal exports from 0.43.3 for unchanged semantic encoding.
