# Testing 0.48.5 — Smooth Material Playback

This is the second focused performance pass for animated Materials. Please compare it directly with 0.48.4 using the same graph and viewport settings.

## Main test

1. Build an animated branch such as Noise → Gradient Map and drive Evolution, Offset or another exposed parameter with Time/Document Phase.
2. Connect it to **Material → Base Colour**.
3. Add several static Constant channels such as Roughness, Metallic, Height or AO.
4. Connect Geometry Plane, Box or Cylinder to the Material.
5. Focus the Material and press Play.

The 3D material should update at a noticeably steadier cadence. Adding unchanged Constant channels should not progressively reduce playback speed.

## Evaluation/presentation overlap

- Use a moderately expensive animated graph and watch real-time playback. The viewport should continue showing the newest completed frame without accumulating delayed frames.
- Scrub or stop playback after a heavy section. The preview should settle on the exact current frame rather than playing through a backlog.
- Test **Every frame** mode and confirm frames still advance sequentially.

## Adaptive live quality

- Test at a selected 3D texture resolution of 512, 1024 or Match 2D Preview.
- During playback the live maps may adapt between 256, 192 and 128 px to maintain cadence.
- Pause and confirm the current frame immediately resolves again at the selected full-quality viewport resolution with normal mipmaps.

## UI and renderer behaviour

- Playback should no longer flash busy/progress text or evaluation states on every material frame.
- The 2D Material Base Colour preview may update at a slightly lighter cadence than the 3D viewport; this is intentional to protect 3D playback smoothness.
- Enable the Timeline profiler and confirm useful performance telemetry still appears.
- Confirm static Material inspection while paused still shows full status and evaluation details.

## Geometry integration

- Animate a Material on Plane, Box and Cylinder.
- Confirm the connected mesh remains stable while only the textures animate.
- Confirm focusing the Geometry node still shows wireframe and pivot inspection, while focusing the Material does not show the pivot gizmo.

## Regression watch

- Ordinary 2D node animation should remain unchanged.
- Material composition, Texture Set Output and OBJ Geometry Output should continue working.
- No stale material frame should survive a graph edit, focus change, graph switch or playback stop.
