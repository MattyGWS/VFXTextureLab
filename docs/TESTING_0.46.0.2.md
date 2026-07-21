# Testing 0.46.0.2 — HBAO Edge-Aware Reconstruction

This patch addresses the remaining visible sampling shapes and the hard black contour around abrupt height transitions.

## 1. Dense Tile Sampler comparison

1. Create a Tile Sampler containing circles with varied scale.
2. Connect it directly to Ambient Occlusion (HBAO).
3. Start with Height Depth `0.30`, Radius `0.05`, Quality `16 Samples` and Occlusion Strength `1.0–1.6`.
4. Inspect at 1:1 as well as Fit.

Expected: occlusion forms continuous soft fields. Individual rings, petals and repeated sampling footprints should no longer be recognisable.

## 2. Hard-edge contour regression

Use crisp white circles or squares on a black Height background without a bevel.

Expected:

- The raised white top remains white right up to its silhouette.
- The lower surface receives soft contact AO outside the shape.
- There is no clipped one-pixel black stroke tracing the height edge.
- Increasing strength deepens the halo rather than reintroducing a solid outline.

## 3. Radius response

Sweep Radius from a tight contact range to a broad value.

Expected: both the horizon-search distance and reconstruction width grow continuously. Small radii remain crisp but smooth; large radii merge neighbouring occlusion into broad ambient fields rather than exposing larger sample circles.

## 4. Gradual height fields

Test a broad linear slope, bevel or smooth noise-derived height field.

Expected: planar slopes do not self-occlude, while real concavities and neighbouring raised regions still darken. The edge correction must not flatten legitimate smooth terrain shading.

## 5. Tiling and live editing

1. Use Boundary = Seamless / Wrap and Tile 3×3.
2. Drag Radius, Height Depth and Occlusion Strength continuously.
3. Clear Evaluation Inspector before the drag.

Expected: seams remain continuous. Raw HBAO and both reconstruction passes stay on GPU with no CPU readback. Interactive edits use the lighter draft sampling and bounded reconstruction width before the final selected quality settles.
