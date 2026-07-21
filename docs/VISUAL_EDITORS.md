# Shared visual parameter editors

Version 0.15.2 builds on the 0.15.1 foundation and formalises the application's graphical parameter controls around a common `VisualEditorCanvas` foundation. Node evaluation remains separate: Levels, Histogram Range, Histogram Shift, Histogram Scan, Gradient Map, Tone Curve and Animation Curve still own their individual operations and serialized parameters.

## Shared interaction contract

All migrated editors now use the same core rules:

- Fixed, predictable canvas heights that do not expand with a tall Parameters dock.
- Click to select a handle or point; drag to edit it directly.
- Mouse capture keeps a drag active when the pointer leaves the canvas.
- Delete or Backspace removes a selected removable point/stop. While the visual editor has focus, the key is consumed there and can never delete the parent graph node.
- Arrow keys nudge the selected item. Hold **Shift** for fine `0.001` movement; hold **Ctrl** for coarse movement where applicable.
- Right-click exposes editor-appropriate Add, Remove, Reset and Grid actions.
- Larger invisible hit areas make small visual handles easier to grab.
- Selected and hovered items share one visual language across histograms, curves and ramps.
- All histogram editors use the same 1024-bin, linear-frequency, stepped display with stratified input sampling and separate underflow/overflow indicators.
- Drag updates are debounced for responsive previews, then the exact final value is always published on release.
- One continuous mouse drag produces one graph undo command. Separate drags remain separate undo commands.

## Editor-specific behaviour

### Levels

The five histogram handles can be selected, dragged and keyboard-nudged. The toolbar now includes **Reset**, which restores neutral input/output levels and intermediary clamping. The existing Histogram/Sliders toggle, Auto Level and Invert actions remain unchanged.

### Histogram Range, Shift and Scan

The guides are now directly editable rather than display-only:

- Histogram Range: drag either output-range edge.
- Histogram Shift: drag the circular-shift guide.
- Histogram Scan: drag the lower or upper transition guide.

The numeric controls remain available for exact values, and each node has a Reset action.

### Gradient Map

The gradient editor is now permanently inline in Parameters rather than opening a separate dialog. It provides:

- direct stop dragging;
- double-click stop creation;
- double-click or Enter colour editing;
- selected-stop Position and Colour controls;
- Add, Remove and Reset toolbar actions;
- keyboard nudging and Delete removal.

Gradient data remains a human-readable list of position/colour dictionaries in graph files.

### Tone Curve and Animation Curve

Both curve nodes share the same point editor, selected-coordinate fields and toolbar. The Grid toggle is available both in the toolbar and context menu. Overlapping points cycle selection when repeatedly clicked at the same location.

## Foundation for future nodes

New graphical nodes should inherit `VisualEditorCanvas` from `vfx_texture_lab/ui/visual_editor_foundation.py` and keep only their value mapping and node-specific painting in the subclass. The foundation owns edit lifecycle, debounce, sizing, keyboard step conventions, common palette, histogram drawing, checkerboards, grids, frames and handle rendering.

## Suggested manual test order

1. Drag each Levels handle, release, then use Undo once.
2. Nudge a selected Levels handle with Left/Right and Shift+Left/Right.
3. Drag both Histogram Range edges and verify the sliders follow.
4. Drag Histogram Shift through the full width.
5. Drag both Histogram Scan guides and verify Position/Contrast follow.
6. Add, move, recolour, nudge and delete Gradient Map stops; confirm the Gradient Map node itself remains in the graph.
7. Reset the gradient to black-to-white.
8. Drag Tone Curve points, toggle Grid, add overlapping points, delete a selected point and confirm the Tone Curve node remains in the graph.
9. Repeat with Animation Curve values outside `0–1`.
10. Confirm each drag is undone in one step, while two separate drags require two Undo operations.
