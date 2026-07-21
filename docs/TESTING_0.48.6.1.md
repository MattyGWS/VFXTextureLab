# Testing 0.48.6.1 — Material Focus Playback Integrity

This patch specifically targets the moving horizontal scanline/banding artefact seen after changing node focus during animated Material playback.

## Main reproduction test

1. Build an animated texture branch such as Noise → Gradient Map and drive Evolution with Time.
2. Connect it to Material Base Colour and connect any procedural Geometry mesh.
3. Focus the Material and start timeline playback.
4. While playback continues, focus an upstream image node.
5. Focus the Material again. Repeat this several times at different points in the animation.

The 2D and 3D previews should resume with complete frames. No horizontal band should crawl up or down the texture, and no partly rendered frame should persist.

## Presentation integrity

- It is acceptable for 2D and 3D to display slightly different frame numbers because they use independent presentation cadences.
- Each individual panel must show one complete animation frame, never a mixture of two frames.
- Rapidly alternate focus between Material, Geometry and upstream image nodes while playing. Old Material frames must not flash after returning.
- Stop and restart playback, edit the graph and switch graphs while Material work is in flight. The preview should settle on the current session only.

## Adaptive quality

- Live Material maps should use a 256 px tier under normal load and may fall to 128 px under sustained pressure.
- The removed 192 px tier should no longer appear in the Material playback detail text.
- One initial slow shader-warm-up frame should not immediately lower the tier.
- Pausing must still restore the exact current frame at the selected full-quality resolution.

## Regression watch

- Focused Material 2D and 3D animation should retain the smoother cadence from 0.48.5 and 0.48.6.
- Ordinary upstream-node 2D animation must remain smooth.
- Static Material channels should remain resident and should not be uploaded every frame.
- Geometry preview, pivot gizmo, wireframe, Material geometry override and OBJ export should remain unchanged.
