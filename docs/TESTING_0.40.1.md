# VFX Texture Lab 0.40.1 performance test pass

This pass focuses on unchanged-focus reuse, precise invalidation and memory-safe 2D/3D preview behaviour. The first visit to a node may still evaluate it; the important comparison is the second visit after another node has been focused.

## 1. Material focus reuse at 2K

1. Open `examples/material_composition.vfxgraph`.
2. Set the document/3D material resolution to 2048 × 2048.
3. Focus **Rock**, **Moss**, **Rock + Moss** and **Wet Rock + Moss** once each and allow every preview to complete.
4. Cycle through the same four nodes again.

Expected: first visits may resolve new lazy channels. Subsequent visits should feel nearly immediate. A full hit should show **Resolved material cache hit** and **Renderer material reused** in the Evaluation Inspector, with no repeated noise, Material Blend, final readback or renderer-upload rows.

## 2. Ordinary 2D node focus reuse

1. Focus several expensive image nodes one by one and let the 2D Preview finish.
2. Return to each unchanged node.

Expected: returning to an unchanged result should display the retained preview without submitting graph evaluation. The inspector should report **Reusing 2D preview**.

## 3. Precise invalidation

1. After warming the example graph caches, change one parameter used only by the Moss branch.
2. Focus Moss and Rock + Moss.
3. Return to the unchanged Rock material.
4. Undo the edit and revisit the earlier material states.

Expected: affected materials evaluate once for the new revision. Rock remains reusable. Undo may reuse the previous revision if it is still within the memory budget. No unrelated branch should be invalidated merely because focus changed.

## 4. Authored-channel-only 3D work

Create or inspect a Material containing only Base Colour, Height and Roughness, then focus it in 3D.

Expected: the inspector resolves only those three authored channels. Emissive, Normal, AO, Metallic, Specular Level and Opacity should remain renderer defaults rather than appearing as full-resolution evaluation/readback/upload work. The rendered appearance should still use the documented semantic defaults.

## 5. Viewport-only changes

With a cached material visible, change camera orbit/pan/zoom, mesh, lighting, HDRI rotation, exposure and post-processing controls.

Expected: the viewport redraws, but no material graph evaluation, channel readback or material upload is submitted.

## 6. Resolution and display-size keys

1. View a node at one document/preview resolution.
2. Change resolution and view it again.
3. Return to the earlier resolution.
4. Resize the 2D Preview panel and revisit the same node.

Expected: the first request for a new resolution or display presentation may perform work. Returning to a retained earlier key should reuse it. Results from different resolutions must never be confused.

## 7. Cache budget and diagnostics

Open the GPU diagnostics and inspect the separate entries for:

- Graph GPU cache
- Graph CPU cache
- 2D presentation cache
- Resolved material CPU cache
- 3D renderer material cache

Lower the render-cache budget after displaying a material.

Expected: older entries may be evicted, but the material currently displayed remains valid. The application should not show destroyed/black textures or crash.

## 8. Clear Render Cache

1. Warm several 2D and Material previews.
2. Use **Render → Clear Render Cache**.
3. Revisit the same nodes.

Expected: the next visit evaluates again because every presentation layer was cleared. The currently visible 3D material should remain safely displayable while its refresh is pending.

## 9. Playback and animated Material Switch

Connect Loop Phase to Material Switch Selection and press Play. Also test an ordinary animated image branch.

Expected: frames continue updating normally. Focus-cache reuse must not freeze animation or cause an old frame to persist. Stop playback and revisit a stable frame to confirm ordinary focus caching resumes.

## 10. Stress comparison

At 2K, repeatedly alternate between three or four warmed Material nodes while watching elapsed time and inspector stages. Then alter one node and repeat.

Expected: warmed unchanged focus changes avoid graph computation, final readback and renderer upload. A changed node gets one fresh evaluation, after which it too becomes fast to revisit.
