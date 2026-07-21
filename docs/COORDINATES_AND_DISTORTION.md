# Coordinates, transforms and distortion — 0.17.0

VFX Texture Lab 0.17.0 adds a native coordinate and distortion foundation. Each node performs one recognisable operation; Transform 2D remains available for compact legacy graphs, while the new dedicated nodes make graph intent clearer and are easier to animate independently.

Every node has matching NumPy and WebGPU/WGSL implementations. Image-processing nodes preserve the input branch's Greyscale, Colour or Vector type and inherited precision.

## Coordinate nodes

### UV Gradient

Generates normalized texture coordinates:

- Red = horizontal **U**, increasing from left to right.
- Green = vertical **V**, increasing from top to bottom.
- Blue = `0.5` and Alpha = `1.0`.

The output is typed as a **Vector** texture and can connect directly to Vector Warp or Flow Map Distort. It is also useful for building masks, coordinate diagnostics and future vector-field operations.

### Cartesian to Polar

Unwraps a circular/cartesian image into a rectangle:

- Horizontal position represents angle around the chosen centre.
- Vertical position represents distance from the centre.

Useful for unwrapping rings, circular masks and radial designs before applying ordinary horizontal processing.

### Polar to Cartesian

Wraps a rectangular angle-by-radius image around a centre. Useful for shockwaves, radial wipes, circular texturing and turning a horizontal strip into a ring.

Both polar nodes expose Centre X/Y, Radius Scale, Angle Offset, Clockwise and Wrap. The old bundled **Polar Coordinates** package is retained invisibly for project compatibility and evaluates as the Polar to Cartesian form; newly created graphs should use the explicit pair.

## Dedicated transform nodes

### Tile

Repeats an image independently using Tiles X and Tiles Y. Fractional counts are allowed for animation and intentional phase drift.

### Offset

Moves an image by normalized X/Y offsets. Positive X moves visible content to the right and positive Y moves it downward.

### Rotate

Rotates around the image centre in degrees.

### Scale

Scales around the centre independently on X and Y. Values above `1` enlarge visible content; values below `1` reveal more repetitions when Wrap is enabled.

### Mirror

Reflects horizontally, vertically or on both axes.

Offset, Rotate and Scale can wrap seamlessly. With Wrap disabled, coordinates outside the source become transparent rather than smearing the edge pixel.

## Distortion nodes

### Directional Warp

The existing package node is now native on both CPU and GPU. A greyscale Intensity input offsets the image along one chosen angle. With Centred Intensity enabled, `0.5` means no movement, black moves in the negative direction and white moves in the positive direction.

### Swirl

Twists the source around a configurable centre. Angle controls the maximum rotation at the centre; Radius controls the affected region. A smooth radial falloff avoids a hard circular boundary.

### Spherize

Bulges or pinches a circular region:

- Positive Amount creates a magnifying/spherical bulge.
- Negative Amount creates a pinch.
- Zero is an exact pass-through.

### Vector Warp

Uses a two-channel Vector texture for genuine two-dimensional displacement:

- Red `0.5` means zero horizontal movement.
- Green `0.5` means zero vertical movement.
- Values below/above `0.5` move in opposite directions.

Flow Direction, UV Gradient and other Vector outputs connect directly. A disconnected Vector input is neutral, so adding the node does not unexpectedly move the image.

### Flow Map Distort

Moves an image along a Vector flow map using a two-phase cross-fade. Animate Phase from `0` to `1` for a seamless looping flow cycle. Unlike Vector Warp, this node is designed for continuously moving fire, smoke, water, magical energy and heat distortion.

## Suggested tests

1. Connect Checker to Tile and change X/Y independently.
2. Insert Offset, Rotate and Scale separately and test Wrap on and off.
3. Use Mirror in all three axis modes.
4. Feed Checker into Swirl; test Angle `0`, positive/negative angles, Radius and an off-centre position.
5. Feed Checker into Spherize; test Amount `0`, `1` and `-1`.
6. Connect Flow Direction or UV Gradient to Vector Warp and adjust Strength through positive and negative values.
7. Connect a vector flow map to Flow Map Distort, expose Phase, and connect **Loop Phase** from a Time signal.
8. Build a horizontal stripe, pass it through Polar to Cartesian and confirm it becomes a ring.
9. Pass a circular design through Cartesian to Polar and confirm it becomes an angle-by-radius rectangle.
10. Save and reload a graph containing the old Polar Coordinates node and confirm it still evaluates.
