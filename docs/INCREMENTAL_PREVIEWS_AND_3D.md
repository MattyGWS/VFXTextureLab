# Incremental previews and automatic 3D feedback

Version 0.17.5 separates direct 2D inspection from the automatic 3D material preview and makes preview invalidation branch-aware.

## 2D preview switching

Double-clicking a texture node is an explicit request to inspect that node. Any older in-flight 2D preview is superseded immediately and the newly selected node becomes the newest evaluation request.

Double-clicking **Material** no longer evaluates that multi-input material sink as an ordinary 2D image. The 2D panel explains that the node drives the dedicated 3D panel, while the 3D preview continues updating automatically.

## Automatic Material updates

Every enabled Material has a content revision built from:

- the output node and all connected upstream nodes;
- parameters and connections in that branch;
- preview dimensions, precision and colour space;
- the current animation frame.

Changes inside the material branch schedule a new 3D preview. Layout-only changes and edits in unrelated graph branches keep the same revision and do not restart the material evaluation. Selecting or double-clicking an already-current Material also does not launch duplicate work.

The 3D panel now reports the live node and material-map stage. The Material node receives the same delayed pulsing orange outline and progress bar used by the 2D evaluator. Uncached source nodes are highlighted while they work, and the output remains active while maps are resized and uploaded to the renderer.

## Reusing the 2D graph cache

The 3D texture setting controls the material-map size sent to the renderer, not a second independent evaluation resolution when a larger 2D graph preview is already available.

For example, with a 2048 graph preview and 512 material maps:

1. Connected branches evaluate at 2048.
2. Existing 2048 node caches are reused.
3. Only the completed material maps are downsampled to 512.

This prevents a 512 or 1024 3D preview from recomputing an already-finished 2K erosion branch. A 3D texture resolution larger than the 2D preview still evaluates at the larger requested size.

## Branch-scoped interactive quality

Reduced interactive terrain workloads are now applied only to the edited node and nodes downstream of it.

For a graph such as:

`Fluvial Erosion → Levels → Gradient Map → Single Image Output`

Dragging a Levels parameter keeps Fluvial Erosion in normal Preview mode, allowing its completed result and named outputs to remain cached. Levels and its downstream branch update from that cached texture.

Dragging a parameter upstream of erosion still causes downstream erosion to use its bounded interactive workload, because that result genuinely depends on the edited value.

## Testing checklist

1. Open a 2K terrain graph with erosion feeding Levels.
2. Wait for the initial 2D and 3D previews to finish.
3. Drag a Levels control. The erosion node should remain inactive while Levels and downstream nodes update.
4. Drag an erosion control. The erosion node should show its bounded interactive progress, followed by one exact Preview render on release.
5. While Single Image Output is evaluating, double-click Levels or another upstream node. The 2D panel should switch to that node instead of waiting for the old output preview.
6. Leave the 3D panel visible and edit a connected node. Its status should name the active material map or source node without relying on the 2D panel.
7. Double-click Material after it is current. It should not start a duplicate material evaluation.
8. Edit an unrelated graph branch. The current 3D preview should not restart.
