# VFX Texture Lab 0.45.0.1 test checklist

This patch fixes scalar files produced by export templates. In 0.45.0, one-channel outputs were correctly composed as `height × width × 1`, but the final image-preparation step still assumed that Green, Blue and Alpha channels existed.

## Primary regression

1. Open a graph with a Material connected to Texture Set Output.
2. Use **Generic PBR Separate** and export.
3. Confirm Base Colour, Normal, Height, AO, Roughness, Metallic and Specular all export without `index 1 is out of bounds for axis 2 with size 1`.
4. Repeat with **Unreal ORM**.
5. Repeat with **Unity HDRP Mask Map**.
6. Repeat with **Godot ORM** and **VFX RGBA Masks** where relevant.

## Formats

- Export scalar maps as PNG 8-bit.
- Export scalar maps as PNG 16-bit.
- Export Height as Raw R16.
- Confirm RGB/RGBA packed files still contain their expected number of channels.
- Confirm Normal DirectX/OpenGL conversion still changes only the green channel.

## Existing workflows

- Quick Export uses the selected built-in or custom template.
- Export Outputs still reports planned files correctly.
- A custom template containing a one-channel Height, AO or Roughness file exports successfully.
- Save and reopen the graph, then repeat the export.
