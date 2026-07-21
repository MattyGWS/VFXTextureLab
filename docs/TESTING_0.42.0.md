# VFX Texture Lab 0.42.0 Test Checklist

This release focuses on exact output previewing and the new multi-document Graph Explorer. The highest-value checks are listed first.

## 1. Preview exact output sockets

Create or open a node with several outputs, such as Worley, Fluvial Erosion, Material Channels or the included Rock Material Generator Graph Instance.

- Double-click one output circle.
- Confirm only that exact output appears in 2D.
- Confirm a highlight ring remains around the chosen output.
- Double-click another output and confirm the lock moves.
- Save, close and reopen the graph; confirm the chosen output remains active.
- Double-click the node body and confirm it returns to the node's primary/default output.

For a Material output, confirm Base Colour appears in 2D and the complete Material activates in 3D. Then select a Height output on the same Graph Instance and confirm it remains a plain 2D height preview rather than activating Material mode.

## 2. Confirm wire dragging is unaffected

On the same multi-output node:

- Press an output socket and drag to a compatible input.
- Confirm the wire begins only after the pointer moves.
- Confirm the connection is created normally.
- Confirm a simple single click on the socket does not start a dangling wire or change the preview.
- Confirm double-clicking a socket does not leave a temporary wire behind.

## 3. Open several graphs

Use **+** and **Open** in Graph Explorer to keep at least three graphs open.

For each graph, set a different:

- Canvas zoom/pan
- Selected node
- Active preview output
- Timeline frame
- 3D camera position or viewport setting

Switch between them by double-clicking Explorer entries. Confirm every graph returns to its own state and has its own undo/redo history. Dirty graphs should carry an asterisk and the active graph should be bold.

## 4. Drag a saved graph from Explorer

Open `examples/graph_assets/rock_material_generator.vfxgraph`, create or open a parent graph, then drag the Rock Material Generator entry from Graph Explorer onto the parent canvas.

Check that:

- A Graph Instance appears at the drop position.
- Its readable sockets and published parameters are present.
- Editing the open Rock Material Generator source updates the parent instance without saving the source first.
- Saving the parent stores the instance as Linked.
- Closing and reopening the parent still resolves the source correctly.

## 5. Drag an unsaved graph from Explorer

Create a new untitled graph with one Graph Output, then drag it into another open graph.

Check that:

- It works immediately as a live Graph Instance.
- Editing the untitled source updates the parent.
- Saving the parent embeds the current child revision.
- Closing the child offers **Save Graph…**, **Embed and Close**, and **Cancel**.
- Choosing Embed and Close leaves the parent instance functional.

## 6. Reopen an embedded graph

Right-click an embedded Graph Instance and choose **Open Embedded Graph**.

- Confirm it appears as another unsaved Graph Explorer document.
- Edit it and confirm the parent updates live.
- Close it and confirm the changed revision remains embedded.
- Repeat, then use Save As; confirm the source gains a path and linked-source behaviour works after saving the parent.

## 7. Test a nested dependency chain

Create three graphs:

```text
A → instance in B → instance in C
```

Edit A while all three are open. Confirm B updates and C receives the updated nested revision without manually saving or reloading either graph.

Request only one output from C and use Evaluation Inspector to confirm unrelated outputs remain lazy.

## 8. Test cycle rejection

- Try dragging the active graph onto its own canvas.
- Create A containing B, then try to drag A into B.

The drop should be rejected before a Graph Instance is created, with a recursion/cycle explanation rather than a hang or broken node.

## 9. Save and document commands

Try the Graph Explorer toolbar and context menu:

- Save
- Save All
- Save As
- Save a Copy
- Duplicate Graph
- Reload from Disk
- Reveal in File Manager
- Close
- Close Others

Confirm each command operates on the selected graph and does not unexpectedly replace or edit another open document. `Ctrl+W` should close the active graph and `Ctrl+Alt+S` should save all modified graphs.

## 10. Restore an open session

Enable **Restore Open Graphs on Startup**, open two saved graphs, make one active, then close VFX Texture Lab cleanly.

Restart it and confirm both saved graphs return to Graph Explorer and the previous active graph is restored where possible. Disable the option and confirm a later startup returns to the normal single starter graph.

## 11. Exercise multi-graph autosave

Keep two unsaved or dirty graphs open and wait for autosave. Save only one graph, then simulate an interrupted session using your normal development/testing method.

On recovery:

- The other dirty graph should still be offered.
- Multiple recovered graphs should return as separate Explorer entries.
- A disk graph saved more recently than its autosave entry should not be replaced by stale recovery data.

## 12. Performance and preview caching

At 2K, preview several outputs and switch among several open graphs.

- Returning to an unchanged exact output should use the 2D presentation cache.
- Small panel-size changes caused by dock chrome should not submit a fresh graph evaluation.
- Switching graph documents should cancel irrelevant stale interactive work but preserve reusable graph/material caches.
- Live child edits should invalidate dependants only after the short debounce and should settle on the newest revision.

## 13. Regression checks

Finally verify that these existing workflows still behave normally:

- Dragging `.vfxgraph` files from the file manager
- Registered Graph Asset folders in Node Library
- Send/Receive portals across nested Material graphs
- Material Channels and Texture Set Output
- Timeline playback and Flipbook Decode
- Stateful simulation isolation between two Graph Instances
- Fluvial Erosion at Channel Widening 1.0
- Workspace reset and custom dock layouts
