# Blend node

VFX Texture Lab stores authored colour textures in a linear-light working space. Familiar texture-authoring blend modes, however, are defined in perceptual/display channel values. The Blend node therefore handles colour and technical data differently.

## Colour branches

For a colour result, each colour input is converted from linear light to display-sRGB before applying the selected formula. The blended RGB is then converted back to linear light for downstream nodes, materials, previews and export.

This makes an authored visible 50% grey neutral in:

- Overlay
- Soft Light
- Hard Light
- Add Sub / Linear Light

For example, a black-to-white Gradient Map at position `0.5` stores approximately `0.214` internally because that is linear-light RGB for visible sRGB 50% grey. Blend temporarily interprets it as display `0.5`, so Overlay returns the Background unchanged.

## Greyscale and vector/data branches

Greyscale masks, heights and other technical data retain raw numeric 0–1 mathematics. Numeric `0.5` is therefore the neutral point for the same contrast modes, with no sRGB transfer applied. Vector branches are likewise treated as raw channel data.

When one input is colour and the other is greyscale, the result is colour. The greyscale branch is interpreted as a visible display value during the blend and converted into the output's linear-light representation.

## Opacity and alpha

The selected mode is evaluated first. Node Opacity is multiplied by the optional greyscale Opacity input, and that combined coverage mixes the blended RGB over Background. Alpha uses the same coverage to interpolate Background alpha toward Foreground alpha; it is never gamma converted.

## Modes

The node provides Replace / Copy, Add, Subtract, Multiply, Divide, Add Sub / Linear Light, Minimum, Maximum, Screen, Overlay, Soft Light, Hard Light, Difference, Exclusion, Colour Dodge and Colour Burn. CPU and WGSL implementations share the same formulas and boundary handling.
