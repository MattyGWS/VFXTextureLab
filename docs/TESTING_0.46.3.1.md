# Testing VFX Texture Lab 0.46.3.1

## Normal Vector Rotation

1. Create a Shape, feed it to Height to Normal, then connect that to **Normal Vector Rotation**.
2. Set Rotation to `90°`. The normal colours/directions should rotate by one quarter turn while the shape silhouette and every texel remain stationary.
3. Compare with **Normal Transform** at `90°`: Normal Transform should rotate the image layout as well, while Normal Vector Rotation must not.
4. Try `-90°`, `360°`, `720°` and an animated angle. The output should remain continuous and unit length.
5. Feed a flat normal `(0.5, 0.5, 1.0)`. It should remain exactly flat at every angle.
6. Flip the source green channel and select **DirectX (-Y)**. The decoded visual rotation should match the equivalent OpenGL source.
7. Test at 8-bit and 16-bit output precision and at 512, 2048 and 4096 resolutions. No spatial drift or seam should appear.

## Regression checks

- Normal Blend, Normal Combine, Normal Invert and Normal Transform still behave as in 0.46.3.
- Node search finds the node with `normal vector`, `direction` and `rotation`.
- Evaluation Inspector should report a normal GPU compute pass with no readback.
