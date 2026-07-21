# VFX Texture Lab 0.43.6 Testing

This release extends Tile Sampler rasterisation to connected Pattern Inputs.

## Primary reproduction

1. Create or import a high-resolution narrow grass-blade mask.
2. Connect it to **Tile Sampler → Pattern Input**.
3. Use a dense grid, reduced Size X/Y and substantial Rotation Random so individual blades become small and diagonally transformed.
4. Inspect the Tile Sampler at **1:1** zoom.

Switch **Quality → Edge Rasterisation**:

- **Pixel Exact** should point-sample the input and produce a deliberately hard, visibly aliased nearest-neighbour result.
- **Antialiased** should visibly smooth sub-pixel blade coverage and preserve more coherent thin shapes.

The source blade node itself must remain unchanged.

## Magnification versus minification

- Use one large tile occupying most of the output. Antialiased should use normal bilinear reconstruction rather than unnecessarily blurring it with a wide footprint.
- Increase X/Y Amount until the pattern is strongly minified. The filtered difference should become obvious.
- Test rotations near 0°, 45°, 90° and fully random rotation.
- Test non-square output dimensions and Non-square Compensation.

## Multiple custom patterns

Connect Pattern Input 1–4 and test:

- Single
- Random Inputs
- Sequential Inputs
- Distribution Map

Every selected custom pattern should use the same Pixel Exact or Antialiased sampling rule.

## Built-in patterns

Confirm Square, Disc, Brick, Capsule, Bell, Diamond, Hexagon and Triangle still retain the 0.43.5 behaviour:

- Antialiased uses geometric edge coverage.
- Pixel Exact uses binary coverage when Edge Softness is zero.

## CPU/GPU and persistence

- Compare normal GPU evaluation with CPU fallback where available.
- Save and reopen the graph; Edge Rasterisation must persist.
- Confirm node thumbnails, 2D Preview, 3D Preview and exported results agree.
- Rapidly adjust Size, Scale and Rotation Random at 2K and confirm the interactive preview remains responsive and settles on the final value.
