# Testing 0.53.0.4 — Graph Canvas Wheel-Zoom Recovery

This source-only maintenance release fixes an intermittent graph-canvas state where the mouse wheel could appear completely unresponsive after opening a graph.

## Why it happened

Opening a very wide graph uses `fitInView` so the whole graph is visible. Depending on the graph width, window size and dock layout, Qt could choose a scale below the graph canvas's ordinary `0.18×` interactive minimum. The previous wheel handler rejected any next step that was still below that minimum, including wheel-in, so the view could never move back into range. Pressing **F** on a selected node worked because framing that node replaced the transform with a larger valid scale.

## Test

1. Launch VFX Texture Lab and open a large or widely spaced graph, such as the Grass Generator graph that exposed the issue.
2. Without selecting a node or pressing **F**, place the pointer over the graph canvas.
3. Scroll the wheel upward several steps.
4. Confirm the graph zooms in immediately and remains centred under the pointer.
5. Scroll back out and confirm the normal lower zoom boundary still applies once reached.
6. Select a node and press **F**, then confirm wheel zoom continues to work normally.
7. Repeat after changing the application window width and dock layout.

## Expected result

- A graph fitted below the usual minimum can always zoom inward.
- A tiny framed selection above the usual maximum can always zoom outward.
- The canvas only blocks wheel motion that would move farther beyond a boundary.
- Pixel-only high-resolution touchpad scrolling is accepted.
- A zero-delta wheel event causes no zoom rather than being treated as zoom-out.

Graph format remains **20** and no setup rerun is required.
