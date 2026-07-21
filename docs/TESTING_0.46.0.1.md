# Testing 0.46.0.1 — HBAO Quality Refinement

This patch focuses only on the visual quality and control response of **Ambient Occlusion (HBAO)**.

## 1. Reproduce the dense Tile Sampler comparison

1. Create a Tile Sampler containing many circles of varied scale.
2. Connect it directly to Ambient Occlusion (HBAO).
3. Use Height Depth `0.30`, Radius `0.05`, Quality `16 Samples` and Occlusion Strength around `1.0–1.6`.
4. View the AO output at 1:1 and Fit.

Expected: circular features produce continuous soft occlusion. The previous repeated radial flower/petal shapes should be absent, including around the smallest circles.

## 2. Height Depth range

1. Keep Radius and Occlusion Strength fixed.
2. Move Height Depth slowly through `0.30`, `0.60`, `0.80` and `1.00`.

Expected: each part of the range continues to deepen the AO. Values above roughly `0.6` must not appear frozen or equivalent.

## 3. Quality levels

Compare 4, 8 and 16 Samples on the same dense pattern.

Expected: 4 Samples is the quickest and least even; 8 is a useful working quality; 16 produces the smoothest angular and radial coverage. None should reproduce the old fixed-ray petals.

## 4. Radius and tiling

1. Sweep Radius from a tight contact shadow to a broad spread.
2. Use Tile 3×3 with Boundary = Seamless / Wrap.
3. Switch to Clamp on a deliberately non-tileable image.

Expected: radius changes the physical spread smoothly, wrapped seams remain continuous, and Clamp does not sample the opposite image edge.

## 5. Interactive draft and GPU execution

1. Clear Evaluation Inspector.
2. Drag Height Depth and Radius continuously.
3. Release and allow the selected quality to settle.

Expected: dragging uses the reduced four-direction, three-ring draft path. The finished result evaluates on GPU without CPU readback or ray tracing.
