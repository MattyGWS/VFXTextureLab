# Erosion preview performance

Version 0.17.3 separates live interaction, settled preview and final export work so heavy terrain nodes remain controllable without changing the authored result.

## Quality intent

The **Iteration Quality** control still supports Automatic, Preview and Final.

- **Automatic** uses Preview pass counts in the live 2D and 3D previews.
- **Automatic** uses Final pass counts during image and animation export.
- **Preview** always uses the authored Preview counts.
- **Final** always uses the authored Final counts.

Resolution no longer decides which pass count is selected. A 2048-pixel application preview therefore uses the same authored Preview settings as a 512- or 1024-pixel preview. This prevents a 2K preview from unexpectedly switching to Final work and changing the appearance.

## Live slider drafts

While a numeric slider is held, iterative terrain nodes use a deliberately bounded draft:

- **Fluvial Erosion:** up to 4 erosion passes and 24 drainage passes
- **Thermal Erosion:** up to 8 iterations
- **Flow Accumulation:** up to 16 iterations

The draft is only for continuous feedback. Releasing the slider cancels any obsolete draft and immediately starts one exact render using the authored Preview or Final settings. Interactive and exact results use separate cache signatures, so a draft can never be mistaken for the settled result.

## Truthful progress

Earlier progress measured how much work had been submitted to the GPU. A large erosion node could therefore reach 100% while thousands of queued passes were still executing.

Iterative nodes now:

1. Submit a small ordered batch.
2. Wait for that batch to genuinely complete.
3. Re-check cancellation.
4. Advance the node progress bar.
5. Briefly yield during preview work before submitting the next batch.

The final 100% update is sent only after the output-selection dispatch has also completed. Final exports use larger, maximum-throughput batches without the preview yield.

Intermediate graph painting is capped to roughly 12 updates per second. Start, completion, cancellation and error states are still delivered exactly.

## 2D and 3D scheduling

Stopped 2D feedback has priority over the material preview. A stale 3D evaluation is cancelled when the graph changes, and new 3D work waits until the exact 2D preview has settled. This prevents the shared evaluator from immediately launching a second erosion solve after the visible progress bar finishes.

The Material texture choices are now:

- 256
- 512
- 1024
- 2048
- 4096
- Match 2D Preview

When **Match 2D Preview** resolves to the same dimensions as the 2D preview, both preview paths can reuse matching upstream graph caches. Higher 3D resolutions remain expensive because every connected material texture must also be read back and uploaded to the renderer.

## Suggested test

1. Open a terrain graph containing Fluvial Erosion.
2. Set the document and maximum preview dimension to 2048.
3. Use Automatic quality with visibly different Preview and Final pass counts.
4. Confirm the live application preview uses the Preview appearance rather than switching to Final because it is above 1024 pixels.
5. Drag Rainfall, Channel Depth or another numeric erosion parameter.
6. Confirm the graph remains controllable and shows a fast approximate draft while the slider is held.
7. Release the slider and confirm one exact Preview solve begins immediately.
8. Confirm the progress bar advances more slowly but does not reach 100% while GPU work is still outstanding.
9. Keep the Material visible. Confirm it does not begin a competing material evaluation during the drag or before the exact 2D result appears.
10. Set 3D texture preview to Match 2D Preview and confirm the material view follows after the 2D preview settles.
11. Export an image with Automatic quality and confirm the Final pass counts are used.
