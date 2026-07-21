# Testing 0.46.0 — Surface Analysis

## 1. Height Curvature compatibility

1. Open an older graph containing the original **Curvature** terrain node.
2. Confirm it now displays as **Height Curvature** and all connections and parameters remain intact.
3. Feed a Constant height into Signed mode.

Expected: the result is uniform 50% grey. Convex, Concave and Absolute remain black on a flat input.

## 2. Curvature neutral Overlay

1. Create a flat normal map (Height to Normal from a Constant works).
2. Connect it to **Curvature**, then Overlay the result over a coloured texture at 100% opacity.
3. Repeat with **Curvature Sobel**.

Expected: the base colour is unchanged everywhere. Flat regions must not become darker or brighter.

## 3. Curvature convention and response

1. Generate a normal map from a rounded height shape.
2. View Curvature and Curvature Sobel.
3. Flip the normal map green channel and change Normal Format from OpenGL (+Y) to DirectX (-Y).

Expected: the curvature appearance remains the same after both changes. Convex areas are bright and concave transitions are dark. Sobel produces broader, harder bands than Curvature.

## 4. Curvature Smooth outputs

1. Connect the same normal map to **Curvature Smooth**.
2. Double-click each output socket.

Expected:

- Curvature uses neutral grey with bright convex and dark concave information.
- Convexity is black except for convex detail.
- Concavity is black except for concave detail.
- Flat areas do not appear in either split mask.

## 5. HBAO material use

1. Build a height pattern containing raised tiles, grooves or overlapping shapes.
2. Connect it to **Ambient Occlusion (HBAO)**.
3. Feed the result into a Material node's Ambient Occlusion input and inspect it in 3D.

Expected: lower regions beside raised height become darker, while broad flat tops remain largely white. The output tiles cleanly with Boundary = Seamless / Wrap.

## 6. HBAO controls and interactivity

1. Drag Height Depth and Radius while watching the 2D preview.
2. Compare 4, 8 and 16 Samples.
3. Try Clamp on a deliberately non-tiling height image.

Expected: dragging remains responsive using the temporary draft path. Releasing the control resolves to the selected quality. Higher quality reduces directional banding without changing the overall interpretation of the height field.

## 7. Evaluation Inspector

1. Clear completed jobs.
2. Adjust Curvature Sobel Intensity and HBAO Radius.

Expected: both nodes execute on GPU when WebGPU is available. HBAO is a single graph node evaluation with no CPU readback or ray-tracing stage.
