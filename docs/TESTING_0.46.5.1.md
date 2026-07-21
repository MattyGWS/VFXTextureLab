# Testing VFX Texture Lab 0.46.5.1

## Directional Lighting

1. Create **Shape → Height to Normal → Directional Lighting** and preview the result.
2. Rotate **Light Angle** through a full turn. The bright side should travel around the shape without moving the texture itself.
3. Set **Light Elevation** near `0°`; the mask should become strongly directional. Move it toward `90°`; upward-facing surfaces should brighten evenly.
4. Raise **Diffuse Power** to narrow the broad bright region, then lower it below `1` to broaden it.
5. Set **Highlight Brightness** above zero and vary **Highlight Power**. The highlight should tighten as power increases.
6. Raise **Ambient** and confirm dark regions lift without changing the directional pattern.
7. Enable **Invert** and confirm the result is exactly the complement of the uninverted mask.
8. Flip the source green channel and switch Normal Format to **DirectX (-Y)**. The decoded lighting should match the equivalent OpenGL input.
9. Drag the Preview light handle. Angle should follow the direction around the centre; distance should control elevation. One complete drag should create one undo step.
10. Check Evaluation Inspector. The node should report one GPU compute pass with no readback.

## Regression checks

- Normal Vector Rotation still changes normal direction without moving pixels.
- Normal Transform still moves the image and rotates its vectors together.
- RT Shadows continues to create cast shadows from Height and is not replaced by this local lighting mask.
- Splatter Circular and the transform-quality nodes remain unchanged.
