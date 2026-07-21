# Adjustment nodes

Version 0.14.0 expands the Filters library with small, single-purpose adjustment nodes. Existing nodes were not duplicated: Auto Levels already provides live normalization, Threshold already includes a soft transition control, and Gradient Map already handles greyscale-to-colour remapping.

## Histogram nodes

All three histogram nodes accept and output greyscale data. Their Parameters views show the actual upstream histogram at a fixed 230 px height.
The display is shared with Levels and uses linear bin counts rather than logarithmic height exaggeration, so peaks, tails and endpoint populations remain analytically comparable across every histogram-based node.

### Histogram Range

Compresses the input into a smaller output interval.

- **Range** controls the width of the output interval. `1` is unchanged; `0` collapses the image to one value.
- **Position** moves the unused portion of the range between black and white.

Useful test: connect a Linear Gradient, set Range to `0.5`, and leave Position at `0.5`. The output should occupy `0.25–0.75`.

### Histogram Shift

Adds a circular offset to greyscale values. Values that pass white wrap back to black.

- **Position** ranges from `0–1`.
- `0` and `1` represent a complete cycle and are equivalent.

Useful test: connect a Linear Gradient and use Position `0.25`. The gradient should wrap sharply from white to black three quarters of the way across.

### Histogram Scan

Turns a greyscale transition into an adjustable mask.

- **Position** grows or shrinks the white portion of the mask.
- **Contrast** controls transition hardness. `1` produces a hard edge.

Useful test: connect a Linear Gradient, set Position to `0.5`, then move Contrast between `0` and `1`.

## Tonal adjustments

### Brightness

Adds a constant value to RGB/data channels. Neutral value: `0`.

### Contrast

Expands or contracts values around **Pivot**. Neutral Contrast: `0`; default Pivot: `0.5`.

### Exposure

Multiplies values in photographic stops. `+1` doubles values and `-1` halves them.

### Gamma

Applies a dedicated gamma curve. Neutral value: `1`. Values above `1` brighten midtones; values below `1` darken them.

### Posterize

Reduces the image to a chosen number of evenly spaced levels. The minimum is two levels.

### Clamp

Restricts image values to a Minimum and Maximum. Reversed values are safely ordered internally.

## Colour adjustments

These nodes require a colour input and preserve alpha.

### Hue Shift

Rotates hue around the HSL colour wheel in degrees while preserving HSL saturation and lightness.

### Saturation

Multiplies only HSL saturation. `0` produces greyscale, `1` is unchanged, and `2` doubles saturation before clamping.

### Lightness

Adds only to HSL lightness. Neutral value: `0`.

## Tone Curve

Remaps image values through up to eight response points using an inline graph in the Parameters panel.

- **Linear** joins points with straight segments.
- **Smooth** uses cubic Hermite interpolation and preserves a neutral straight-line curve.
- Tone Curve point coordinates are constrained to `0–1`.
- Drag points directly, double-click the graph to add one, and press Delete to remove the selected point.

## Individual test order

1. Histogram Range
2. Histogram Shift
3. Histogram Scan
4. Brightness
5. Contrast
6. Exposure
7. Gamma
8. Posterize
9. Clamp
10. Hue Shift
11. Saturation
12. Lightness
13. Tone Curve

For the first nine and Tone Curve, a Linear Gradient is the clearest source. For Hue Shift, Saturation and Lightness, use a Colour node or imported colour image.

## Shared editor behaviour in 0.15.1

Histogram Range, Histogram Shift and Histogram Scan now have draggable guides in the histogram itself. Their precise sliders remain synchronized with direct edits. Gradient Map now exposes its complete colour-stop editor inline in Parameters, with selected-stop Position/Colour fields, keyboard nudging, Add/Remove/Reset actions and no separate editor window. All migrated visual controls share fixed sizing, hover/selection styling, context actions, debounced preview updates and one-command drag undo.
