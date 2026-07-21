# Testing 0.45.3 — Viewport-Owned Displacement

## Ownership and migration

1. Open a new graph and select the Material node.
2. Confirm the Material Inspector contains Material and Normals controls but no Displacement section.
3. Add Material Override, enable **Override Material Settings**, and confirm it also has no displacement amount, midpoint or inversion controls.
4. Open an older graph that saved custom Material displacement values. Confirm the same visible displacement is restored in **3D Preview → Settings… → Displacement**.
5. Save and reopen the migrated graph. Confirm the viewport values persist and no obsolete displacement controls return to Material nodes.

## Live renderer feedback

1. Activate a Material with a connected Height map and wait for the 3D preview to complete.
2. Clear completed entries in Evaluation Inspector so new work is obvious.
3. Open 3D Viewport Settings and drag **Displacement Amount** continuously across a broad range.
4. The mesh should deform continuously while the pointer moves. There should be no graph evaluation job, orange node activity, material finalise/readback stages or CPU → GPU texture upload.
5. Repeat with **Height Midpoint**, then toggle **Invert Height**. All three should reuse the currently displayed Height texture immediately.
6. Confirm Base Colour, normals, roughness and the other material maps remain unchanged and do not flicker or temporarily disappear.
7. Change an upstream Height-producing node afterward. That genuine graph edit should still trigger the normal material refresh exactly once.

## Composition behaviour

1. Build two Materials, blend them with Material Blend and preview the result.
2. Change viewport displacement. The complete blended Height channel should respond; neither source Material should acquire independent displacement state.
3. Switch the material through Material Switch or Material Override. The viewport Amount, Midpoint and Invert values should remain stable.
4. Open another graph with different saved 3D viewport settings, then return. Each graph should restore its own displacement presentation.

## Automated checks

```bash
python tests/viewport_displacement_test.py
python tests/material_composition_test.py
python tests/three_d_viewport_controls_test.py
python tests/three_d_renderer_quality_test.py
```
