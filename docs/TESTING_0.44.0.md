# VFX Texture Lab 0.44.0 testing checklist

This build is the first testable part of the Portable Projects milestone. It establishes the contextual Inspector and persistent graph metadata before dependency collection and relative-path rewriting are added.

## 1. Initial graph properties

1. Start VFX Texture Lab.
2. Confirm the right-hand dock is named **Inspector**, not Parameters.
3. Confirm the new graph initially shows **Untitled Graph** properties rather than “Nothing selected”.
4. Expand **Asset Identity** and confirm an Asset ID is present, the graph is marked unsaved, and Created with reports 0.44.0.
5. Confirm **Published Interface** warns when the graph has no connected Graph Output.

## 2. Context switching

1. Select several ordinary nodes and groups; confirm their existing parameter editors still appear normally.
2. Click empty canvas space. The active graph’s properties should return.
3. Select a node, then press Escape. The active graph’s properties should return.
4. Open or create a second graph.
5. Single-click the first graph in Graph Explorer. Its properties should appear, but the second graph must remain on the canvas.
6. Double-click the first graph. It should become the active canvas graph and its graph properties should appear initially.
7. Select a node in it and confirm the Inspector immediately returns to that node’s parameters.

## 3. Persistent metadata

1. Enter a Name, Description, Category, comma-separated Tags, Author and Version.
2. Confirm the graph gains a dirty asterisk.
3. Save it, close it and reopen it.
4. Confirm every field and the Asset ID are unchanged.
5. Use Save a Copy and confirm the copy retains the same Asset ID.
6. Duplicate the open graph in Graph Explorer and confirm the duplicate also retains the same Asset ID.
7. In the duplicate, expand Asset Identity and choose **New…**. Cancel once, then repeat and confirm; only the confirmed action should generate a different Asset ID.

## 4. Published interface summary

1. Add and connect one or more Graph Output nodes.
2. Give them clear names and choose a primary preview output.
3. Return to graph properties and confirm each output name and data type are listed and the primary output is identified.
4. Add a Graph Input and confirm it appears in the summary.
5. Expose a publishable node parameter and confirm it appears under Exposed Parameters.
6. Rename or change any of these while graph properties are visible; the summary should refresh without reopening the file.

## 5. Regression checks

1. Verify 3D Viewport Settings still temporarily occupy the Inspector and selecting a node restores node parameters.
2. Verify Levels, Gradient Map, curves, Tile Sampler and other custom parameter editors still work.
3. Verify switching graphs preserves each graph’s canvas view, active preview and undo history.
4. Verify Save All saves metadata-only changes in non-active graphs.
5. Verify autosave recovery restores graph metadata and Asset IDs.

Report any case where the Inspector shows stale information, a single click unexpectedly switches the canvas, metadata does not make the correct graph dirty, or an existing node parameter editor regresses.
