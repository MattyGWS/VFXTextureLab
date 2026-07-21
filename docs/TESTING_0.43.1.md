# VFX Texture Lab 0.43.1 testing

## Compatible-node search

1. Drag a wire from the output of **Gaussian Blur** and release it over empty canvas. The popup should say **Connect from Gaussian Blur** and identify the output as Greyscale.
2. Search for `noise`. The popup should show **No compatible nodes match “noise”** rather than an empty **BUILT-IN NODES** section.
3. Press Escape, then Space. Search for `noise` again; the ordinary search should show the complete Noise and Noise/Fractal Variations results.
4. Repeat loose-wire search and type `levels`. Levels should appear and selecting it should create and connect the node.
5. Drag from an input socket instead. The popup should say **Connect to…** and explain that it is showing nodes with compatible outputs.

## Gesture guard

1. Click an output socket without moving. No wire or popup should appear.
2. Move only a few pixels and release. No compatible-node popup should appear.
3. Drag deliberately into empty canvas and release. Compatible-node search should open.
4. Drag directly to a compatible input socket. The wire should connect normally without opening search.
5. Double-click an output socket. Exact-output preview should still activate and should not leave a wire behind.

## Regression checks

- Space/right-click ordinary search still includes graph assets and **Add Graph Asset…**.
- Loose-wire search still excludes graph assets and only creates nodes which can actually connect.
- Keyboard Up/Down and Enter still select results correctly.
- Optional node thumbnails, output-specific previewing and wire snapping behave as in 0.43.0.
