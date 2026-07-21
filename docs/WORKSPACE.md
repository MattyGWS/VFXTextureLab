# Workspace layout

VFX Texture Lab stores its interface arrangement in application settings. It is global to the application and is deliberately separate from `.vfxgraph` project files.

## What is remembered

- Main-window position, size and maximised state
- Docked panel locations and splitter sizes
- Hidden or visible panels
- Tabbed panel groups and the selected tab
- Floating-panel position and size, including panels placed on another monitor

Changes are written shortly after the user finishes moving or resizing a panel and explicitly synced to disk. This means a saved graph is not required and the most recent workspace normally survives a crash.

## Default left-side graph tools

The default workspace places **Graph Explorer** above **Node Library** on the left. The splitter between them is adjustable, and either dock can be hidden, floated, moved or tabbed independently. Graph Explorer manages the graphs open in the current session; Node Library remains the persistent node and asset catalogue.

See [`GRAPH_EXPLORER.md`](GRAPH_EXPLORER.md) for multi-document switching and drag-to-instance workflows.

## Tabs

Drag one panel's title bar onto another dock area until the tab target appears, then release it. The tabs are shown above the combined panels.

For the common preview arrangement, use **View → Tab 2D and Materials**. Drag either resulting tab away to separate it again.

## Floating panels

Drag a dock title bar outside the main window and release it. It remains an independent floating window and can be moved to a second display. Double-clicking a dock title bar also toggles between docked and floating states.

Closing a floating panel hides it rather than deleting it. Reopen it from the **View** menu.

## Recovery and reset

If a display is disconnected, windows whose saved geometry no longer intersects an available screen are moved onto the primary display.

Use **View → Reset Workspace Layout** to restore the original arrangement without changing the graph.

## Manual test checklist

1. Resize the main window and every dock, close the application without saving a graph, then reopen it.
2. Move a dock to a different side, restart, and confirm its side and size are restored.
3. Use **Tab 2D and Materials**, select each tab, restart, and confirm the tab group remains.
4. Drag 3D Preview outside the main window, resize and move it, restart, and confirm it returns as a floating window.
5. Hide Parameters through **View**, restart, then restore it through **View**.
6. Use **Reset Workspace Layout** and confirm all panels return without altering graph contents.
7. With two displays, place a floating panel on the second display and restart. Then disconnect that display and confirm the panel is recovered onto the primary display.
