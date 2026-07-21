# Testing 0.48.4 — Material Playback Performance

This update changes the focused Material animation path substantially. Please test both playback responsiveness and the transition back to full quality when paused.

## Core reproduction

1. Create an animated grayscale or colour branch, for example Noise → Gradient Map.
2. Expose an Evolution/Offset parameter and drive it with Time or Document Phase.
3. Connect the animated result to **Material → Base Colour**.
4. Add Constant inputs to Roughness, Metallic, Height or other channels.
5. Focus the Material and press Play.

The 2D Base Colour and 3D material should now advance together without the severe stalling previously caused by two competing preview evaluators.

## Static channel residency

- Add several static Constant maps to the Material. Playback should not become progressively slower with each additional unchanged channel.
- Change one static channel while paused, then resume playback and confirm the new value appears correctly.
- Verify that direct Constant and Colour inputs still look correct despite remaining compact 1 × 1 textures internally.

## Geometry integration

- Connect Geometry Plane, Box or Cylinder to the Material.
- Focus the Material and confirm the animation plays on the connected procedural mesh.
- Confirm focusing the Geometry node still uses geometry inspection and pivot/wireframe behaviour normally.

## Quality transition

- During playback, expect the material maps to use the bounded live-resolution path.
- Pause playback and confirm the 2D and 3D previews settle to the exact current frame at the selected full-quality preview resolution.
- Confirm static, non-playing Material inspection is unchanged.

## Playback modes

- Test **Real-time** mode: the playhead may skip frames if a graph is genuinely too expensive, but it should continue presenting completed frames rather than freezing.
- Test **Every frame** mode: each frame should render in sequence without skipping.

## Regression watch

- Ordinary non-Material node animation should remain unchanged.
- Material composition, texture-set export and Geometry Output should continue working.
- No stale Material frame should appear after editing the graph or switching focus.
