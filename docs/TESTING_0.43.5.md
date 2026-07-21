# VFX Texture Lab 0.43.5 Testing

## Tile Sampler rasterisation

1. Create a Tile Sampler using the built-in Triangle pattern at 128×128 or 256×256.
2. Set Edge Softness to zero and Edge Rasterisation to **Antialiased**. Zoom to 1:1 or above and confirm the triangle edges contain restrained fractional coverage.
3. Switch to **Pixel Exact**. The built-in triangle edges should visibly become binary and stair-stepped.
4. Repeat with Disc, Diamond and Hexagon.
5. Increase Edge Softness and confirm both modes still allow deliberate wider feathering.
6. Test at 2K and confirm the mode still changes the result in normal GPU evaluation, not only CPU fallback.
7. Connect a custom Pattern Input and confirm its existing image filtering is unchanged by the built-in rasterisation control.

## Repeated Quick Export

1. Configure Quick Export on a Texture Set Output using the default **Replace existing** policy.
2. Export the complete set twice to the same folder.
3. Confirm the second export updates `Material_BaseColor.png`, `Material_Normal.png`, and the other original paths without creating `_2` files.
4. Repeat with Single Image Output.
5. Open a graph configured in 0.43.4 with the old inherited suffix default. Confirm Quick Export now replaces its established files.
6. Deliberately choose **Add numeric suffix** and confirm repeated export creates `_2`, `_3`, and later files only when explicitly requested.
7. Choose **Skip existing** and confirm existing files remain untouched.

## Duplicate output filenames

1. Create two output nodes that both plan the same filename, such as two Texture Set Outputs both named `Material`.
2. Select both and start a batch export.
3. Confirm VFX Texture Lab warns that the planned filenames collide.
4. Continue with safe names. Confirm only the conflicting files receive stable output-node tags.
5. Run the same batch again. Confirm those same tagged files are overwritten instead of generating fresh numeric suffixes.
6. Give the two output nodes distinct names or templates and confirm the warning disappears.

## Regression checks

- Preview Fit and 1:1 zoom remain accurate.
- Shape, Polygon and Polygon Burst still honour Antialiased and Pixel Exact.
- Single Image Output and Texture Set Output both retain remembered Quick Export destinations.
- Normal, height, mask and packed-map exports retain linear numeric values and correct metadata.
