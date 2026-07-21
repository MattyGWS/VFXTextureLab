# Graph Explorer and exact output previewing

VFX Texture Lab 0.42.0 adds a multi-document graph workspace and lets the 2D Preview lock to one exact output socket. Together these features make nested `.vfxgraph` assets practical to author, inspect and compose without repeatedly saving, reopening or wiring temporary preview nodes.

## Preview one exact output

Double-click a node body to preview its normal primary/default output. Double-click one of the node's output circles to preview that exact named output instead.

The preview lock stores both the node identity and the stable output name. A thin highlight ring remains around the active output socket, and the exact choice is saved in the graph file.

This is useful for multi-output nodes such as:

- Worley and other multi-result noises
- Fluvial Erosion
- Flood Fill tools
- Material Channels
- Graph Instance nodes
- Any custom graph asset with several public outputs

Output behaviour follows its data type:

- Greyscale and Colour appear normally in 2D.
- Vector / Normal appears using the existing encoded-vector display.
- Material shows Base Colour in 2D and activates the complete material in 3D.
- Signal uses the 2D panel's scalar-value presentation.

Named outputs remain lazy. Previewing one Graph Instance output does not evaluate its other public outputs.

### Wire dragging remains unchanged

An output-socket press does not immediately become a connection drag. Pointer movement must first cross Qt's normal drag threshold. Therefore:

- Double-click without moving previews the output.
- Press and move starts a wire.
- A simple click does neither.

Beginning a wire drag cancels the possible double-click gesture, so previewing and graph construction do not compete.

## Graph Explorer

The **Graph Explorer** dock appears above Node Library in the default workspace. It lists every graph document currently open in this VFX Texture Lab session.

The panel is separate from Node Library:

- **Graph Explorer** is the current working session: open, editable, saved and unsaved graphs.
- **Node Library / Graph Assets** is the persistent searchable collection of reusable built-in nodes and registered asset files.

The dock can be resized, hidden, floated, tabbed or moved like every other workspace panel.

## Opening and switching graphs

The Graph Explorer toolbar contains:

- **+** — create another untitled graph
- **Open** — open a `.vfxgraph` as another document
- **Save** — save the selected graph
- **Save All** — save every modified graph

Double-click a graph entry, or select it and press Enter, to make it active. Merely single-clicking an entry selects it in Explorer without replacing the canvas.

Each graph retains its own:

- Graph model and undo/redo history
- Dirty/unsaved state
- Selection
- Canvas pan and zoom
- Active preview node and exact output socket
- Timeline frame
- Document settings
- 3D viewport settings and camera state

Switching documents does not save, close or flatten either graph.

An asterisk marks unsaved changes. The active graph is shown in bold.

## Drag an open graph into another graph

Drag any Graph Explorer entry onto the active canvas to create a Graph Instance at the drop position.

### Saved source graph

When the source already has a `.vfxgraph` path, the instance remains a linked asset when the parent is saved. While both documents are open, however, the instance reads the authoritative in-memory source revision. Unsaved edits in the child therefore update the parent without requiring a save/reload cycle.

### Unsaved source graph

An untitled source has no file path. Dragging it creates a live session instance while the source remains open. Saving the parent serialises the current child graph as an embedded dependency, keeping the parent portable.

If the child is later saved to disk, use its Graph Instance workflow deliberately; the application does not silently change a previously embedded dependency into an external link.

## Live nested editing

Open source graphs act as the authoritative revision for all matching open Graph Instances. Changes are propagated after a short debounce so parameter drags do not rebuild every dependant on every mouse event.

Propagation follows nested chains. For example:

```text
Crack Generator → Rock Generator → Final Material
```

Changing Crack Generator refreshes the open Rock Generator instance and then the dependant Final Material graph. Only affected graph revisions and requested outputs are invalidated.

Saved linked instances opened before their source are rebound automatically when the source file later enters Graph Explorer. The reverse order works as well.

## Embedded graphs

An embedded Graph Instance can be opened for editing through its node context menu using **Open Embedded Graph**.

It becomes an unsaved Graph Explorer document and the parent temporarily references that live session. Edits propagate back to the parent immediately.

- Closing the embedded editor stores its current revision back inside dependant parents.
- Saving the embedded document with **Save As** gives it a real file path; dependant instances can then serialise as linked sources.

## Closing graphs safely

Closing a normal dirty graph offers Save, Discard or Cancel.

Closing an unsaved graph that is used by open parents offers:

- **Save Graph…** — give it a path so dependants can use a linked source
- **Embed and Close** — freeze the current revision into each dependant parent
- **Cancel**

Closing a saved source returns its dependant instances to the saved linked revision on disk. Unsaved child edits are handled by the ordinary Save/Discard confirmation first.

The context menu also provides Close and Close Others.

## Explorer context actions

Right-click a graph entry for:

- Open / Activate
- Save
- Save As
- Save a Copy
- Duplicate Graph
- Reload from Disk
- Reveal in File Manager
- Add Parent Folder to Graph Assets
- Close
- Close Others

These actions operate on the chosen Explorer document, not whichever graph happened to be first when the application started.

## Cycle prevention

A graph cannot be dropped into itself. Indirect cycles are also rejected before insertion. For example, when A already contains B, B cannot be dropped into A.

Cycle checks resolve both live session references and ordinary linked file paths, so opening files in a different order does not bypass dependency safety.

## Session restore

VFX Texture Lab starts with a clean Graph Explorer session by default. Enable **File → Defaults & Startup → Restore Open Graphs on Startup** only when you prefer to reopen the saved graph files that were present when the application last closed cleanly. The previously active saved graph is restored where possible.

Untitled documents are not treated as permanent startup files. Their unsaved contents are protected by autosave instead.

## Multi-document autosave and recovery

Autosave now records every dirty Graph Explorer document in one recovery bundle. Saving one graph does not erase recovery data for other unsaved graphs.

After an interrupted session, recovery restores each recoverable graph as its own Explorer document. A disk file saved more recently than its autosave entry is skipped rather than overwritten by stale recovery data.

A clean application shutdown removes the recovery bundle after all close confirmations have completed.
