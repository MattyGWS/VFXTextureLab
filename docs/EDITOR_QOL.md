# Editor quality-of-life behaviour

Version 0.18.3 focuses on common interactions that should not interrupt authoring.

## Connection snapping

While dragging a wire, the endpoint searches within a 32-pixel screen-space radius for compatible sockets. The nearest valid socket receives an orange ring and the temporary wire terminates at its centre. Because the radius is measured in viewport pixels, zooming the graph does not make snapping excessively weak or strong.

If two neighbouring sockets are nearly equidistant and the pointer is not already close to one, snapping temporarily disengages rather than selecting an arbitrary input. Move slightly toward the intended socket to make it unambiguous. Exact incompatible sockets continue to show the existing red invalid state. Releasing over empty graph space still opens compatible node search.

## Preview status stability

The 2D preview status occupies one fixed-height line. Long evaluation messages are elided instead of wrapping and resizing the viewport; hover the line to see the complete text. The 3D preview follows the same rule.

## Graph file dialogs

Open Graph and Save Graph remember the last successfully used graph directory. Their folder history includes recent graph locations plus available Home, Documents, Desktop and Downloads folders. Native platform dialogs may render these locations differently, but the initial directory remains persistent on Linux and Windows.

## Toolbar and timeline

The main toolbar contains controls that benefit from persistent visibility: Document Settings, Preview Max, document summary and renderer selection. New/Open/Save/Export/Undo/Redo remain available through menus and standard shortcuts.

Timeline transport buttons use native media icons and tooltips so stepping a frame cannot be confused with playback.

## Manual checks

1. Drag a wire near one input and confirm it snaps before the pointer reaches the exact socket.
2. Move between two adjacent inputs and confirm neither is chosen at the ambiguous midpoint.
3. Release on empty graph space and confirm compatible-node search still opens.
4. Trigger long 2D evaluation messages and confirm the viewport does not resize.
5. Open and save a graph, reopen each dialog, and confirm it starts in the last graph folder.
6. Confirm the main toolbar no longer duplicates File/Edit actions.
7. Confirm previous/next frame controls are visually distinct from play/pause.
