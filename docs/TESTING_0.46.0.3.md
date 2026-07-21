# Testing 0.46.0.3 — Blend Colour-Space Correction

## Exact neutral-grey test

1. Create **Constant** with Value `0.5`.
2. Feed it into a default black-to-white **Gradient Map**.
3. Connect Gradient Map to Blend Foreground and any coloured texture to Background.
4. Test Overlay, Soft Light, Hard Light and Add Sub / Linear Light at Opacity `1.0`.
5. The Blend output should match Background exactly. Moving Opacity between `0` and `1` should not change the image because the foreground is neutral.

## Curvature workflow

1. Feed a flat normal map into Curvature or Curvature Sobel.
2. Overlay the result over a coloured material.
3. Flat regions must remain unchanged; only convex/concave curvature values should brighten or darken the colour.

## Greyscale/data-map test

1. Blend greyscale Constant `0.5` directly over a greyscale gradient.
2. Overlay, Soft Light, Hard Light and Add Sub / Linear Light must remain neutral.
3. Multiply, Add, Subtract, Minimum and Maximum should continue behaving as raw numeric map operations.

## General mode audit

- Check Foreground and Background are not reversed in Overlay or Hard Light.
- Check Opacity `0` returns Background and Opacity `1` returns the complete selected-mode result.
- Attach an Opacity map and confirm it multiplies the node's Opacity control.
- Confirm Divide by black, Colour Dodge by white and Colour Burn by black remain finite and clipped to the valid range.
- Compare CPU and GPU backends if both are available; outputs should visually match.
