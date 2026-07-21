# Startup graphs, grid snapping and themes

## User-defined startup graph

VFX Texture Lab can use the current document as the starting point for every new project.

1. Arrange the graph and Document Settings as desired.
2. Choose **File → Defaults → Save Current Graph as Startup**.
3. Confirm the operation.

The template stores the graph, node parameters, connections, groups, the active preview node and Document Settings. It does not replace, rename or move the currently open project file.

The saved template is used when the application launches and whenever **File → New** is chosen. **File → Defaults → Restore Built-in Startup Graph** removes the custom template for future new projects while leaving the current document untouched.

The startup template is stored in the application's data directory under `startup/default.vfxgraph`. **Open Startup Graph Folder** opens that location directly.

If a custom template cannot be read, VFX Texture Lab falls back to the bundled lightweight graph and reports the failure in the status bar.

## Shift-to-grid movement

Hold **Shift** while dragging a node to snap it to the graph's 24 px minor grid.

- The dragged node's top-left corner is the snap anchor.
- When several nodes are selected, their relative spacing is preserved; the selected group moves by the anchor node's snap offset.
- Group frames continue to move freely so they can wrap arbitrary layouts.
- Releasing Shift resumes free movement immediately.

## Built-in themes

The built-in themes are available under **View → Theme**:

- **Midnight** — the original dark blue/purple appearance with a violet accent.
- **Graphite** — a neutral dark-grey interface with a teal accent.
- **Daylight** — a light-grey interface with a blue accent.

Themes cover standard controls, panel and dock surfaces, scrollbar visibility, graph background and grid, node bodies and borders, previews, selection state and progress feedback. Node category header colours remain distinct so the graph's visual language is preserved.

The selected theme is saved immediately and applied before the main window is constructed on the next launch.

## Custom JSON themes

Choose **View → Theme → Export Current Theme as JSON…** to create a complete editable theme file. After changing the colours, choose **Import Theme…** or place the file in the user-theme folder and select **Reload User Themes**.

A theme file has this structure:

```json
{
  "id": "forest-night",
  "name": "Forest Night",
  "base": "graphite",
  "colors": {
    "accent": "#56b870",
    "accent_hover": "#72cc8a",
    "scrollbar_handle": "#668877"
  }
}
```

`base` may be `midnight`, `graphite` or `daylight`. A custom file may override only the colours it needs; every omitted value is inherited from the selected base. Colours use six- or eight-digit hexadecimal notation.

The exported file lists every supported colour token and is the easiest starting point for a fully customised palette.

## Testing checklist

- Save a visibly customised graph as the startup graph, restart, and confirm the graph and Document Settings load.
- Press New and confirm the custom startup graph is used again.
- Restore the built-in startup graph, press New, and confirm the bundled lightweight graph returns.
- Drag one node while holding Shift and confirm its top-left corner aligns with the minor grid.
- Shift-drag several selected nodes and confirm their spacing does not change.
- Switch among all three built-in themes and inspect scrollbars, docks, graph text, selected nodes, previews and parameter controls.
- Export a theme, change its name/accent, import it, and confirm it appears in View → Theme and persists after restart.
