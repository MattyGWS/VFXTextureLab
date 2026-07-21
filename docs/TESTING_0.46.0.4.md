# Testing VFX Texture Lab 0.46.0.4

## RTAO availability

1. Create **Ambient Occlusion (RTAO)** from the node search.
2. Confirm that it appears under **Filters/Surface Analysis** beside HBAO.
3. Connect a grayscale Height map and confirm the result is white where unoccluded and darker around blockers and recesses.

## Suggested Tile Sampler comparison

1. Create scattered circles with different scales in Tile Sampler.
2. Feed the same Height map into HBAO and RTAO.
3. Start RTAO at Height Scale `1.0`, Samples `16`, Uniform, Maximum Distance `0.10–0.20`, Spread Angle `1.0`, Denoise `0.75`.
4. Confirm RTAO shows interactions between nearby circles without HBAO-style radial sampling structures.
5. Increase Samples to `32` and `64`. The settled result should become cleaner and more stable, although evaluation should take longer.

## Edge behaviour

1. Feed a hard white square or circle on black into RTAO.
2. Confirm the raised white top remains white at its edge rather than receiving a solid black outline.
3. Confirm the lower black surface receives contact AO immediately beside the shape.
4. Increase Denoise and verify that the contact shadow becomes smoother without bleeding onto the white top.

## Controls

- Set Height Scale, Maximum Distance or Spread Angle to zero; the output should become white.
- Compare Uniform, Cosine Weighted and Horizon Weighted distributions; all should remain stable but emphasise different portions of the hemisphere.
- Set Denoise to zero to inspect raw stochastic ray variance, then restore it to `0.75` or higher.
- Compare Seamless / Wrap and Clamp near the image borders.
- Toggle Invert and confirm exact black/white inversion.

## Interaction and evaluation

1. Open Evaluation Inspector and drag Height Scale, Maximum Distance or Spread Angle.
2. The drag should use the reduced six-ray/eight-step draft path.
3. Release the control and confirm a settled full-quality RTAO evaluation follows.
4. At 2K, expect 32- and 64-ray results to be significantly slower than HBAO; this is intentional final-quality work rather than a hardware-RT path.
