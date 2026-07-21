# Testing VFX Texture Lab 0.44.1

This build adds the first complete **single-file portability and dependency recovery** workflow. The ordinary source graph should remain unchanged throughout these tests.

## 1. Inspector portability section

1. Open a graph and click empty canvas space.
2. In **Inspector → Portability & Recovery**, confirm that the nested-graph and image counts roughly match the active graph.
3. Add a linked Graph Instance and an external Image Input. Return to graph properties and confirm the linked/external counts update.
4. Confirm **Export Self-Contained Graph…** is available both here and under **File**.

## 2. Basic self-contained export

Create a parent graph containing:

- At least one linked `.vfxgraph` Graph Instance.
- An Image Input, either in the parent or inside the child graph.
- Ideally another graph nested inside that child.

Then:

1. Save the parent normally.
2. Choose **File → Export Self-Contained Graph…**.
3. Save it under a different filename such as `Portable Test-self-contained.vfxgraph`.
4. Confirm the completion message reports the nested graphs and images embedded.
5. Close the source graphs.
6. Temporarily rename or move the original child `.vfxgraph` files and images.
7. Open the self-contained export.
8. Confirm it renders correctly and every Graph Instance reports **Embedded**.
9. Save and reopen the exported graph once more.

The exporter should refuse to use the active source graph’s exact filename, protecting the original from accidental replacement.

## 3. Current open child revision

1. Open a child graph and its parent in Graph Explorer.
2. Modify the child so the output visibly changes, but do not save it.
3. Confirm the parent’s live Graph Instance shows the new result.
4. Export the parent as a self-contained graph.
5. Revert or close the child without saving.
6. Open the exported copy.

The export should contain the visible unsaved child revision, not the older disk copy.

## 4. Missing linked graph and cached recovery

1. Create and save a child graph, then use it as a linked Graph Instance in a saved parent.
2. Close the child graph so the parent returns to normal linked operation.
3. Move or rename the child file outside VFX Texture Lab.
4. Wait for the Graph Instance to report **Missing source**. It should continue rendering from its cache.
5. Export the parent as self-contained.

The export should succeed and explicitly report that it recovered a graph from the last-known-good cache.

Now right-click the missing Graph Instance and test:

- **Use Cached Revision / Make Local** — it should become Embedded and continue rendering.
- Undo/redo should restore the previous state correctly.
- **Restore Cached Revision As…** — choose a new `.vfxgraph` filename. A self-contained restored child should be written and the node should relink to it.
- Open that restored child and confirm it is editable and renders normally.

## 5. Relink all matching Graph Instances

1. Add the same linked graph to a parent two or more times.
2. Make a compatible newer copy of that source while preserving its Asset ID. A normal Save As or saved copy does this.
3. Right-click one instance and choose **Relink All Matching Instances…**.
4. Select the newer source.

All matching nodes should relink together, preserve their individual Random Seed and exposed-parameter overrides, and produce one undo step.

## 6. Image Input recovery tools

Create two Image Input nodes that point to the same image.

- Use **Relink All Matching Images…** on one and confirm both paths change together.
- Undo and redo the operation.
- Use **Make Local / Embed Image**. The selected node should keep rendering after the source image is moved or deleted.
- Save and reopen the graph; the embedded image should remain available.
- Right-click it and choose **Restore Embedded Copy As…**. Confirm the image file is recreated and the node becomes an ordinary external Image Input pointing at the restored file.

Also test **Relink Image…** on only one of two matching nodes and confirm the other is not changed.

## 7. Blocking missing image

1. Create an Image Input pointing to a file.
2. Keep **Embed in project** disabled and save the graph.
3. Delete or move the image.
4. Try self-contained export.

Export should stop with a readable dependency chain identifying the graph and Image Input. It must not create a supposedly successful portable graph with a missing image.

## 8. Regression checks

- Existing linked Graph Instances still auto-reload after their source is saved.
- Existing embedded Graph Instances still open through **Open Embedded Graph**.
- Normal Save, Save As and Save All behave as before.
- Node parameters and Graph Properties still switch correctly in the Inspector.
- Image Input data-type detection and normal-map detection still work after relinking.
- Undo/redo remains stable after graph and image relinking.
