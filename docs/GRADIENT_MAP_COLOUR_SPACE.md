# Gradient Map colour space

Gradient Map colour stops are authored through Qt colour controls and stored as ordinary hexadecimal sRGB values. The graph itself processes colour in linear light.

The node therefore follows this path:

1. Read the greyscale input as a 0–1 lookup position.
2. Interpolate the hexadecimal stops in display-sRGB component space, matching the inline ramp shown in Parameters.
3. Convert the interpolated RGB result with the standard sRGB transfer function into linear-light values.
4. Pass those linear values to downstream nodes, the 3D material evaluator and linear exports.
5. Convert only a display copy back to sRGB in the 2D preview or when an sRGB export is requested.

Alpha is interpolated directly and is never gamma converted.

## Why the old result looked brighter

Previously a 50% black-to-white ramp emitted numeric RGB 0.5 and marked it as colour. The 2D preview correctly treated that number as linear and converted it to display sRGB, producing about 0.735 or RGB 188. The corrected node emits approximately 0.214 linear, which the preview converts back to display RGB 128.

## Testing checklist

- Connect Linear Gradient to Gradient Map with black and white stops. Both previews should now match visually.
- At the centre, a saved display image should read approximately RGB 128 rather than RGB 188.
- Try red at 0, blue at 0.5 and green at 1. The output should match the inline ramp.
- Add transparent stops and confirm alpha transitions remain unchanged.
- Feed Gradient Map into Levels, Blend and Material to confirm downstream processing remains linear.
