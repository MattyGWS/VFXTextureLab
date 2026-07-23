# Testing 0.50.2 — Fur Profiles and Linear Gradients

## Fur rounded height profile

1. Add **Fur** and inspect it directly in the 2D Preview.
2. Feed Fur into a Normal node or use it as displacement on a dense mesh.
3. Compare individual hairs around their brightest midpoint.
4. The height should roll over as a rounded dome; there should be no sharp transverse crease at the strand's highest point.
5. Change Angle, Angle Random, Width, Softness and Length. The rounded crest must remain stable on both the main hairs and the softer undercoat.

## Fur range expansion

1. Confirm **Density** accepts values from 1 through **10**.
2. Confirm **Length** accepts values through **5.0**.
3. At Density 10, the result should become substantially fuller without stacking several Fur nodes.
4. At Length 5, hairs should extend much farther than the old limit while remaining deterministic for a fixed Seed.
5. Confirm Fibres and Messy Fibres retain their previous Density maximum of 3 and Length maximum of 3.

## Linear Gradient 2

1. Add **Linear Gradient 2**.
2. At its default 90° Angle, the image should be black at the top and bottom and white at the centre.
3. The centre should be smoothly rounded with no visible cusp.
4. Rotate Angle and adjust Offset. The complete black-white-black dome should move and rotate continuously.
5. Toggle Repeat and confirm repeated periods remain continuous at their black edges.

## Linear Gradient 3

1. Add **Linear Gradient 3**.
2. At its default 90° Angle, the image should be black at the top and bottom and white at the centre.
3. The two linear ramps should meet in a deliberately sharp white centre ridge.
4. Angle, Offset and Repeat should behave identically to Linear Gradient 2.

## Save, reload and backend

1. Save a graph containing Fur, Linear Gradient 2 and Linear Gradient 3, then reopen it.
2. Confirm all parameters and previews survive unchanged.
3. Test at 8-bit and 16-bit node precision and at several output resolutions.
4. When GPU execution is available, confirm the Inspector reports WGSL execution and that CPU fallback gives the same profiles.
