# VFX Texture Lab 0.44.2 Testing — Thumbnails and Library Polish

This build focuses on persistent graph thumbnails and the Graph Asset section of Node Library. Existing node thumbnails are a separate feature and should continue behaving exactly as before.

## 1. Capture a 2D graph thumbnail

1. Open a graph with a useful image or Material output.
2. Double-click the output you want displayed in **2D Output** and wait for evaluation to complete.
3. Click empty canvas space so the Inspector returns to Graph Properties.
4. Expand **Thumbnail** and click **Capture 2D**.

Expected:

- The 256 × 256 thumbnail appears immediately.
- **Source** says `2D Preview`.
- The graph receives an unsaved `*` marker.
- Non-square previews are fitted inside the square without stretching.
- Saving, closing and reopening the graph preserves the thumbnail.

## 2. Capture a 3D Material thumbnail

1. Double-click a Material-producing node or Texture Set Output so the 3D Preview is active.
2. Frame and orbit the material to a useful angle.
3. Return to Graph Properties and click **Capture 3D**.

Expected:

- The current square 3D viewport becomes the thumbnail.
- **Source** says `3D Preview`.
- Capture 3D reports that no preview is available when no Material has been evaluated.

## 3. Import and clear

1. Click **Import Image…** and choose a PNG, JPEG, WebP or BMP.
2. Save and reopen the graph.
3. Click **Clear** and save again.

Expected:

- The imported image is fitted, not distorted, and Source says `Imported image`.
- The original external image is not required after import; its compact PNG copy is stored in the graph.
- Clear removes both the picture and its source label.

## 4. Inactive Graph Explorer selection

1. Keep graph A active on the canvas.
2. Single-click graph B in Graph Explorer.

Expected:

- Graph B's properties and stored thumbnail can be inspected and changed with Import/Clear.
- Capture 2D and Capture 3D are disabled, preventing graph A's preview from being written into graph B.
- Double-clicking graph B activates it and enables capture actions.

## 5. Node Library details card

1. Add the containing folder through **Add Asset Folder…**, or use an asset already in a registered folder.
2. Save the graph after assigning metadata and a thumbnail.
3. Single-click its entry in Node Library.

Expected:

- A details card appears below the tree without evaluating the graph.
- It shows the thumbnail, name, description, author, version, tags, published outputs, source path and `Ready` validation state.
- Selecting a built-in node or user node hides the graph-asset details card.
- Saving a registered asset refreshes its library metadata and thumbnail.

## 6. Rich graph-asset search

Search Node Library and ordinary Spacebar add-node search by each of the following:

- A tag
- Author
- Asset version
- Published Graph Output name
- Description/category/name as before

Expected: the same asset is found by every relevant field. Loose-wire compatible-node search should remain focused on compatible built-in nodes and should not gain graph assets.

## 7. Validation and problem visibility

Create or copy a `.vfxgraph` into a registered asset folder, then make one of these problems:

- Remove every connected Graph Output.
- Corrupt the JSON deliberately.
- Leave one additional Graph Output unconnected while keeping another output valid.

Expected:

- A graph with no usable output or unreadable JSON appears under **Graph Assets → Problems** with a `⚠` marker and cannot be dragged into the graph.
- Double-clicking the problem entry shows its validation reason.
- A graph with at least one valid output remains usable; non-blocking warnings receive a `△` marker rather than moving it into Problems.
- Invalid assets do not appear as insertable results in Spacebar add-node search.

## 8. Graph Asset context actions

Right-click a valid or problem asset and test:

- **Open Source Graph**
- **Validate Asset**
- **Edit Thumbnail in Inspector…**
- **Reveal Source**
- **Remove This Asset Folder**, for a manually registered folder

Expected:

- Open Source Graph reuses an already-open document rather than opening duplicates.
- Edit Thumbnail opens/activates the source and leaves Graph Properties visible.
- Validate distinguishes valid, usable-with-warnings and blocking-problem states.
- Reveal opens the correct containing folder.

## 9. Regression checks

- Node selection still replaces Graph Properties with normal node parameters.
- Clicking empty canvas returns to Graph Properties.
- Existing per-node thumbnail buttons and node thumbnail evaluation still work.
- Self-contained export preserves the graph asset thumbnail.
- Graph Instances, Graph Explorer live editing and recovery actions still work.
- A library with many graph assets does not evaluate them during refresh; only JSON metadata and embedded thumbnail bytes are read.
