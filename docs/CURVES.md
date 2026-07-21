# Curve editors

Version 0.14.1 gives both curve nodes a direct graphical editor in the Parameters panel. Existing graphs remain compatible because the serialized IDs are unchanged: `filter.curve` is now displayed as **Tone Curve**, and `signal.curve` as **Animation Curve**.

## Shared interaction

- Drag a square point directly on the graph.
- Double-click empty graph space to add a point.
- Select a point and press **Delete** or use **Remove**.
- Use **Add** to place a point in the largest empty interval.
- Use **Reset** to restore the neutral two-point diagonal.
- Edit the selected point precisely with **Input X** and **Output Y**.
- Choose **Smooth** or **Linear** from the toolbar above the graph.
- Curves support two to eight points.

The graph is fixed at 270 px high so a tall Parameters dock does not stretch the editor. Its width still follows the dock.

## Tone Curve

Tone Curve processes image values and constrains both axes to `0–1`. Smooth mode displays the same cubic Hermite response used by CPU and WebGPU evaluation. Values before the first point and after the final point hold those endpoint outputs.

Suggested test:

1. Connect Linear Gradient to Tone Curve.
2. Double-click near the graph centre.
3. Drag the new point upward and verify that the preview brightens around the corresponding input range.
4. Switch between Smooth and Linear and verify that the drawn graph and preview change together.
5. Reset and verify that the input is neutral again.

## Animation Curve

Animation Curve remaps scalar signals. It retains the original `-1000` to `1000` point range and automatically frames all authored points while keeping the familiar `0–1` region visible. Smooth mode displays the same per-segment smoothstep interpolation used by signal evaluation.

Suggested test:

1. Connect Time or Normalized Time to Animation Curve, then connect its output to an exposed numeric parameter.
2. Add a middle point and drag it to shape the timing response.
3. Enter a value outside `0–1` in the coordinate fields and verify that the graph reframes rather than clamping it.
4. Switch between Smooth and Linear and verify the driven parameter changes accordingly.

## Shared editor behaviour in 0.15.1

Tone Curve and Animation Curve now use the common visual-editor foundation. Arrow keys nudge the selected point, **Shift** uses fine movement, the toolbar can hide/show the grid, and a continuous drag creates one undo command. Hover styling, hit areas, context actions and final-value flushing now match the histogram and gradient editors. Repeated clicking cycles through points whose screen positions overlap.
