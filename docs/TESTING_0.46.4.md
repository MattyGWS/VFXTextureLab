# Testing VFX Texture Lab 0.46.4

## 1. Exact identity

1. Connect a detailed Image Input to Transform 2D.
2. Leave Offset at zero, all scales at `1`, and Angle at `0`.
3. Switch between Automatic, Bilinear and Bicubic.
4. Compare the input and output at 1:1.

The output should remain exactly unchanged and should not become softer.

## 2. Filtering comparison

1. Use a small checkerboard, thin line pattern or high-frequency noise.
2. Scale it down strongly with Transform 2D or Scale.
3. Compare Nearest, Bilinear, Bicubic and Automatic.

Nearest should remain intentionally jagged. Bilinear should soften. Bicubic should reconstruct ordinary detail cleanly. Automatic should suppress the strongest minification aliasing and moiré.

## 3. Transparent-edge colour

1. Import a transparent cutout whose invisible pixels contain a noticeable colour.
2. Rotate it over a contrasting background.
3. Use Bilinear or Bicubic filtering and Transparent boundaries.

No coloured or dark fringe should appear around partially transparent edges.

## 4. Boundary modes

Offset an image far enough to expose an outside edge and compare:

- Transparent: empty/transparent outside area.
- Clamp: repeated border texel.
- Seamless / Wrap: opposite side of the image.
- Mirror: reflected edge.

Negative offsets should behave as reliably as positive offsets.

## 5. Rectangular documents

1. Create a clearly circular shape on a wide rectangular document.
2. Place it away from the centre.
3. Rotate by `90°` using Rotate or Transform 2D.

Its distance from the centre should be preserved in physical pixels, and the circle should not be stretched because the canvas is rectangular. Transform 2D's outline and handles should match the rendered result.

## 6. Normal maps

1. Use a tangent-space normal map with obvious directional detail.
2. Apply Normal Transform with rotation and non-uniform scale.
3. Try Automatic and Bicubic filtering.
4. View the result in the 3D Preview.

The map should remain valid and unit-length, and rotating the image should rotate its tangent directions rather than treating it as ordinary colour.

## 7. Perspective Transform

1. Rectify a photographed quadrilateral.
2. Use a shape where one side is significantly reduced.
3. Compare Bilinear, Bicubic and Automatic.

Automatic should adapt across the image: enlarged areas should remain smooth while compressed areas should alias less than a fixed point filter.

## 8. Clone Patch

On a rectangular photograph, choose a circular patch, rotate it and change Scale. The copied patch and its feather should remain circular in image pixels instead of becoming elliptical due to canvas aspect ratio.

## 9. Safe Transform

1. Feed an already-seamless noise or material channel into Safe Transform.
2. Enable Tile Safe Rotation, set Tile to `3` or higher and choose an oblique Rotation.
3. View Tile 3×3.
4. Try manual offsets, Random offset with several seeds, and X/Y symmetry.

Opposite borders should remain continuous. At low Tile counts the actual safe angle can be coarser than the requested angle; increasing Tile should allow a closer result.

Then disable Tile Safe Rotation. The exact authored angle should be honoured, but it is no longer the guaranteed periodic lattice path.

## 10. Existing graph compatibility

Open an older graph that used:

- Transform 2D or Normal Transform Tile on/off.
- Offset, Rotate or Scale Wrap on/off.
- The former Auto filtering name.

The graph should retain the same wrapping intent and should show the new Boundary/Automatic names without broken connections or missing parameters.
