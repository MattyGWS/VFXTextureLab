# Testing VFX Texture Lab 0.46.3

## Normal Blend and Combine

1. Feed a flat normal into Background/Base and a visible generated normal into Foreground/Detail.
2. On Normal Blend, move Amount from `0` to `1` and confirm a smooth fade without darkening or invalid vector colours.
3. Connect a black-to-white mask and confirm it controls the blend spatially.
4. On Normal Combine, compare RNM, Whiteout and UDN.
5. Connect a flat normal as Detail and confirm RNM leaves Base unchanged.
6. Change Base Strength and Detail Strength and confirm each layer changes independently.
7. Inspect the result in 3D and confirm it remains a valid tangent normal rather than becoming flatter/darker from RGB blending.

## Normalize and Invert

1. Feed imported or deliberately distorted vector data into Normal Normalize.
2. Confirm the result shades consistently and invalid/zero vectors become flat normals.
3. On Normal Invert, toggle X and confirm horizontal lighting direction reverses.
4. Toggle Y and confirm vertical lighting direction reverses.
5. Compare OpenGL and DirectX conventions and confirm the encoded green-channel behaviour is consistent.
6. Toggle Z only as a stress test and confirm the output remains normalised.

## Normal Transform and 2D Preview gizmo

1. Connect a recognisable asymmetric normal map to Normal Transform.
2. Rotate it by 90 degrees and confirm both the image detail and tangent-space lighting direction rotate together.
3. Change Scale X and Scale Y independently and confirm the pattern stretches on only the selected axis.
4. Use the 2D Preview centre, corner, side and rotation handles.
5. Rotate first, then drag a side handle and confirm scaling follows the transform's local rotated axis.
6. Confirm one complete preview drag creates one undo step.
7. Disable Tile and confirm outside pixels become flat normals rather than black/invalid vectors.

## Normal to Height

1. Generate a Height map, convert it to a Normal map with Height to Normal, then feed it into Normal to Height.
2. Compare the reconstructed large forms and fine detail with the original Height; exact absolute values are not expected.
3. Change Low Frequency and High Frequency independently.
4. Disable Normalize Output and confirm the solution remains centred around mid-grey.
5. Toggle Invert.
6. Switch both the normal producer and Normal to Height between OpenGL and DirectX and confirm the reconstructed orientation remains consistent.
7. At 2K, inspect Evaluation Inspector and confirm the node performs a deliberate global readback/solve rather than repeatedly reevaluating unchanged upstream nodes.

## Bent Normal

1. Feed a completely flat Height map into Bent Normal and confirm the output is exactly a flat normal.
2. Add a raised square or circle and inspect the Bent Normal around it.
3. Confirm surrounding vectors bend away from the blocked hemisphere rather than forming a scalar dark halo.
4. Compare 4, 16, 32 and 64 Samples and verify noise/coverage improves as the workload rises.
5. Set Denoise to `0` to inspect the raw ray result, then raise it and confirm smoothing respects hard height boundaries.
6. Compare Uniform, Cosine Weighted and Horizon Weighted distributions.
7. Verify Seamless/Wrap across Tile 3×3 and Clamp on a non-tiling image.

## RT Shadows

1. Feed a raised shape over a flat Height background into RT Shadows.
2. Rotate Light Angle and confirm the shadow rotates to the opposite side of the blocker.
3. Raise Light Elevation and confirm shadows shorten; lower it and confirm they lengthen.
4. Increase Height Scale and confirm the same grayscale relief casts a longer/stronger shadow.
5. Increase Maximum Distance and confirm distant shadow reach grows.
6. Set Samples to `1` and Softness to `0` for a hard shadow.
7. Increase Softness and Samples and confirm the penumbra becomes smoother rather than merely blurred after the fact.
8. Adjust Bias enough to remove self-shadow acne without visibly detaching the shadow.
9. Confirm Seamless/Wrap crosses the tile border correctly and Clamp does not sample the opposite side.
10. Toggle Invert and Shadow Strength.

## Regression

1. Reopen an older 0.46.2.2 graph and confirm no graph-format migration is required.
2. Verify existing Transform 2D, Height to Normal, RTAO, HBAO, Curvature and material normal channels behave unchanged.
3. Test 8-bit and 16-bit inherited precision.
4. Test CPU fallback and GPU execution where available.
5. Save, reopen and export a graph containing each new node.
