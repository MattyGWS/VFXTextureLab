# Directional Lighting

Version 0.46.5.1 adds a lightweight normal-derived lighting mask under **Filters/Normal & Height**.

Unlike **RT Shadows**, Directional Lighting does not trace through a height field and therefore does not create cast shadows between separate features. It evaluates the local tangent-space normal against one authored light direction. This makes it fast enough for ordinary graph authoring and useful for stylised highlights, directional colour masks, edge emphasis and baked-lighting effects.

## Input and output

- **Normal** accepts a tangent-space vector/normal map.
- **Lighting** is a grayscale mask from `0` to `1`.

The node decodes and normalises every input vector before evaluation. Invalid zero vectors become a flat `(0, 0, 1)` normal.

## Light controls

- **Light Angle** is the horizontal image-space direction *toward* the light.
- **Light Elevation** moves the light from grazing at `0°` to directly overhead at `90°`.
- **Normal Format** interprets the input as OpenGL `+Y` or DirectX `-Y`.

The diffuse response is the clamped dot product between the decoded normal and the light direction.

## Mask shaping

- **Diffuse Power** changes the broad directional contrast. Values above `1` narrow the bright-facing region; values below `1` broaden it.
- **Diffuse Brightness** scales the diffuse contribution.
- **Highlight Power** controls the width of an optional view-facing highlight lobe. Higher values create tighter highlights.
- **Highlight Brightness** scales that highlight. Its default is `0`, so the node begins as a pure diffuse mask.
- **Ambient** lifts fully unlit regions without changing the light direction.
- **Invert** swaps black and white after all lighting contributions are combined.

The highlight uses a fixed tangent-space view direction along `+Z`, making it deterministic and suitable for texture-mask generation rather than scene-dependent rendering.

## 2D Preview gizmo

The Preview draws a projected light-direction guide:

- Drag around the guide to change **Light Angle**.
- Drag toward the outer circle for a grazing light.
- Drag toward the centre for a higher light elevation.
- The exact values remain available in Parameters and one complete drag creates one undo operation.

## Performance

Directional Lighting is a single native WGSL compute pass and performs no GPU-to-CPU readback. The NumPy implementation is retained as the CPU reference path and follows the same formula.
