# VFX Texture Lab 0.43.3 Testing

## Full-quality 2D Preview

1. Set a square document and Preview Max to 2048. Build or open a detailed 2048 texture and focus it in 2D.
2. Confirm the preview header reports 2048 × 2048 and that zooming to 100% or above reveals finer detail rather than a hidden 1024-pixel display copy.
3. At Fit, confirm a dense high-resolution texture looks smoothly minified rather than crunched or heavily aliased.
4. Create a 128 × 128 triangle or checker and enlarge it. Confirm enlargement remains hard/pixelated with no bilinear fringe.
5. Toggle Tile 3×3 and the R/G/B/A channel buttons; quality and sampling rules should remain consistent.

## Linear data export parity

1. Connect a Greyscale branch to Single Image Output and choose **Linear Data**. Export PNG.
2. Compare it with the 2D Preview in an ordinary image viewer. Mid-grey and mask brightness should agree rather than appearing gamma-brightened.
3. Inspect the PNG with a metadata tool if available: it should have neither an `sRGB` nor a `gAMA` chunk.
4. Export the same branch with **Colour / sRGB**. It should be visibly brighter for mid-range linear values and should contain the `sRGB` chunk.

## Normal maps

1. Connect Height to Normal to Single Image Output. Export both OpenGL and DirectX normal presets.
2. Confirm the exported red/blue brightness matches the raw Vector/Normal 2D Preview.
3. Confirm DirectX changes only the Green/Y channel.
4. Confirm neither normal PNG contains an `sRGB` or `gAMA` chunk.

## Texture Set Output

1. Export Separate PBR Maps from a complete Material.
2. Base Colour and Emissive should be sRGB encoded/tagged.
3. Normal, Height, AO, Roughness, Metallic, Specular and Opacity should remain untagged numeric data.
4. Export Unreal ORM and Unity HDRP Mask Map; packed channels should remain untagged numeric data.
5. Try both 8-bit and 16-bit PNG scalar depths and Raw R16 Height.

## Performance sanity

1. Compare 512, 1024 and 2048 Preview Max settings. Larger settings should visibly preserve more detail and use more presentation-cache memory.
2. Rapid parameter edits should still prioritise interactive work and settle to the exact configured preview.
3. Returning to an unchanged node should reuse the full-quality presentation cache.
4. Clear Render Cache and confirm the next focus rebuilds the preview correctly.
