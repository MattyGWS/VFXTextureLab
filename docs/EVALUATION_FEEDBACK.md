# In-node evaluation feedback

Version 0.17.2 introduced runtime work directly on graph nodes. Version 0.17.3 made iterative GPU progress represent completed work rather than merely submitted commands. Version 0.17.4 also covers the final GPU synchronisation and texture-readback interval after node progress reaches 100%.

## Behaviour

- A node that remains active for roughly 180 ms gains a pulsing orange outline.
- A thin orange bar appears along the bottom of the active node.
- Nodes with measurable iterative work use a determinate bar.
- Nodes that cannot expose trustworthy progress use a moving indeterminate segment.
- Fast and cached nodes complete before the display threshold and therefore do not flash.
- Activity is runtime-only and is never serialized into graph or reusable-node files.
- Completion, cancellation, replacement by a newer preview, and errors all clear the indicator.
- After the last measured node finishes, **Single Image Output** remains active while queued GPU work is synchronised and the final texture is read back for display.
- If the last GPU producer is a different node, that producer and Single Image Output are both highlighted during finalisation.
- The 2D preview header and status bar name the live stage, responsible node and requested resolution rather than falling back to a generic `Evaluating exact preview` message.
- The completed-preview status summary reports how much of the total render time was spent in finalisation/readback.

Intermediate progress painting is explicitly limited to roughly 12 updates per second. Iterative GPU nodes advance only after a batch has genuinely completed; progress never triggers graph evaluation or adds texture readbacks.

## Suggested manual test

1. Create a noise or height generator and connect it to **Thermal Erosion**.
2. Make Thermal Erosion the active preview node.
3. Set the preview to 2K and raise Preview Iterations enough for the calculation to take longer than a fraction of a second.
4. Change an erosion parameter.
5. Confirm the Thermal Erosion node gains a pulsing orange outline after a brief delay.
6. Confirm its bottom progress bar advances as iterative GPU batches actually complete.
7. When the erosion progress reaches 100%, confirm the 2D preview identifies any remaining **Finalising Single Image Output** stage instead of appearing idle.
8. Confirm Single Image Output receives an indeterminate orange bar while GPU synchronisation/readback is still underway, and that the last GPU producer is also highlighted when different.
9. Confirm the header includes the requested resolution, for example `2048 × 2048 preview`.
10. Confirm all indicators clear only when the preview image is actually replaced.
11. Start another heavy update and immediately make a newer edit. Confirm stale activity clears rather than remaining stuck.
12. Evaluate an inexpensive node. Confirm it normally completes without visible flashing.
13. Force CPU rendering and repeat. Heavy CPU nodes should still show indeterminate activity even when exact internal progress is unavailable.

Stateful simulations use the same presentation. Long non-sequential timeline jumps additionally report their frame replay progress.
