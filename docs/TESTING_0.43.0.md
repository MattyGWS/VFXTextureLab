# VFX Texture Lab 0.43.0 Test Checklist

## 1. Default zero-work behaviour

1. Open a reasonably large graph with every node collapsed.
2. Work normally at 2K and inspect Evaluation Inspector/GPU Diagnostics.
3. Confirm that no thumbnail stages or thumbnail cache entries appear merely because nodes are visible.
4. Confirm that node sizes and graph readability match 0.42.1.

## 2. Header control and geometry

1. Pick a bypassable node such as Gaussian Blur.
2. Confirm that the new chevron sits consistently beside the existing power/bypass control.
3. Expand it. A square thumbnail should appear directly beneath the title and before the port rows.
4. Collapse it and confirm the node returns to its original height.
5. Undo and redo both actions.

## 3. First evaluation and cache reuse

1. Expand a node which has not yet been previewed.
2. Confirm it shows **Not evaluated**, then **Rendering…**, then the image.
3. Collapse and expand it again without changing the graph. The cached image should return without a new expensive evaluation.
4. Edit the upstream branch. The previous image should remain dimmed with **Updating…** until the new image completes.
5. Edit an unrelated graph branch. The thumbnail should remain a cache hit.

## 4. Exact fixed size and performance priority

1. Set the document to 2K or 4K and expand several inexpensive nodes.
2. Confirm all thumbnails have identical displayed dimensions.
3. In Evaluation Inspector, confirm independent thumbnail jobs use 128 × 128 rather than document resolution.
4. Start dragging an expensive parameter while a thumbnail is queued. The main 2D preview should win immediately and thumbnail work should wait/cancel.
5. Focus a material node and move the 3D camera/lighting. Thumbnail work should not delay the viewport.

## 5. Multi-output selection

1. Expand Worley, Fluvial Erosion or a multi-output Graph Instance.
2. Right-click the chevron and choose another **Thumbnail Output**.
3. Confirm the thumbnail changes while the main 2D Preview remains locked to its previous exact output.
4. Save/reopen the graph and confirm the chosen thumbnail output remains.

## 6. Data types

Test one output of each kind:

- Greyscale
- Colour
- Vector / Normal
- Material (should display Base Colour)
- Signal (should show a numeric tile)

Confirm that black image results appear as true black only after completing, rather than being confused with the Not Evaluated placeholder.

## 7. Visible-node culling

1. Expand thumbnails on several distant nodes.
2. Pan so some expanded nodes are off-screen, then change a shared upstream parameter.
3. Visible thumbnails should update first; off-screen ones may retain their previous image.
4. Pan back and confirm the newly visible thumbnails settle.

## 8. Playback

1. Expand the active animated node and another inactive animated node.
2. Start playback. The active thumbnail should follow the already-presented playback result without launching a second evaluator job.
3. The inactive thumbnail should not compete with playback. Pause and confirm it settles to the current frame.

## 9. Docking and structural nodes

1. Expand a compatible node, then dock it into another node.
2. Confirm that the thumbnail and chevron disappear and the dock remains compact.
3. Undock it and confirm its previous expanded state returns.
4. Confirm reroutes and compact Send/Receive portal aliases do not expose thumbnail controls.

## 10. Persistence, copying and cache clearing

1. Save/reopen a graph containing a mixture of expanded and collapsed nodes.
2. Copy/paste an expanded node and confirm the preference/output is preserved.
3. Use **Render → Clear Render Cache**. Expanded nodes should return to **Not evaluated** and regenerate only while visible/idle.
4. Check GPU Diagnostics for the separate Node thumbnail cache and verify it clears.

## Automated regression

The release suite includes 74 standalone modules. The focused thumbnail test verifies zero disabled requests, fixed 128 × 128 evaluation, geometry, revision cache reuse, output selection, schema persistence, dock suppression and last-valid-image retention. The complete suite also covers exact-output preview gestures, interactive scheduling, playback, graph assets/Explorer, materials, GPU readback, erosion and workspace behaviour.
