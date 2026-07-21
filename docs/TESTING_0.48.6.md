# Testing 0.48.6 — Smooth Material 2D Playback

This pass targets the 2D Base Colour preview specifically while a Material node is focused. The 3D improvements from 0.48.5 should remain intact.

## Main comparison

1. Build an animated branch such as Noise → Gradient Map and drive Evolution, Offset or another exposed parameter with Time or Document Phase.
2. Confirm the upstream Noise and Gradient Map animate smoothly in the 2D Preview.
3. Connect the result to **Material → Base Colour** and focus the Material.
4. Press Play and compare the focused Material Base Colour animation directly with the upstream node.

The focused Material 2D Preview should now update continuously rather than at the visibly choppy former 15 FPS cadence.

## 2D and 3D independence

- Keep both the 2D and 3D previews visible while the Material is focused.
- Confirm Base Colour updates immediately as material frames complete.
- Confirm the 3D viewport remains smooth and may coalesce older completed frames independently.
- Adding static Constant inputs for Roughness, Metallic, AO or other channels should not progressively slow either preview.

## Quality and controls

- Test 24 FPS and 30 FPS timelines.
- Test different selected 3D texture resolutions. Live playback may still use the adaptive 256/192/128 px tiers from 0.48.5.
- Toggle R/G/B/A channel buttons during playback and confirm channel isolation remains functional.
- Pause and confirm both previews settle on the exact current frame at full authored quality.

## Geometry integration

- Connect Geometry Plane, Box and Cylinder to the animated Material.
- Confirm both previews continue updating and the connected mesh remains stable.
- Confirm the Material focus still hides the Geometry pivot gizmo.

## Regression watch

- Ordinary upstream 2D node playback must remain unchanged.
- The Material path must still use one evaluation stream rather than starting the ordinary 2D playback evaluator as well.
- No stale frame should survive a focus change, graph edit, stop or graph switch.
