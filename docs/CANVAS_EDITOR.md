# Grayscale Canvas Editor

The **Grayscale Canvas** node is a source node with no inputs. Its greyscale image is embedded in the graph and keeps an independent native resolution. The graph evaluator resamples that native image to the requested preview or export resolution without modifying the authored canvas.

## Empty state and node creation

When no Grayscale Canvas node is selected, the Canvas Editor shows a deliberately minimal empty state rather than a disabled painting surface. The **Create Grayscale Canvas Node** button inserts a new Canvas node at the centre of the visible graph area and selects it immediately, matching node creation from the Node Library.

Every newly created Canvas node starts at the current Document Settings width and height. This applies whether the node is created from the Canvas Editor, Node Library, graph search or a compatible loose connection.

## Editing

Select a Grayscale Canvas node and use the **Canvas Editor** dock. Paint, Erase, Smudge, Line, Rectangle and Ellipse are presented as equal square icon buttons in a vertical strip beside the image. Greyscale value, brush size, softness and opacity remain below the canvas.

The native-size selector offers common power-of-two square sizes: 256, 512, 1024, 2048, 4096 and 8192. Existing rectangular or legacy dimensions remain visible as a temporary **Current** entry so old projects are not silently resized.

Canvas authoring is opaque greyscale. New canvases start black, Clear fills black, and Erase paints black. There is no separate transparency or editable background value.

## Zoom and pan

The Canvas Editor follows the same navigation model as the 2D Output:

- **Fit** resets zoom and pan.
- The percentage label shows the current zoom relative to Fit.
- The mouse wheel zooms around the pointer.
- Hold the middle mouse button and drag to pan.

Left mouse input remains reserved for the active drawing tool.

## Undo and redo

While keyboard focus is anywhere inside Canvas Editor, Ctrl+Z and Ctrl+Shift+Z/Ctrl+Y operate on the selected Canvas node's own drawing history. Each complete stroke is one history step. Clear and Resize are also stored. When focus is outside Canvas Editor, the same shortcuts operate on the structural graph undo stack.

Canvas histories are maintained per node and bounded to avoid unlimited memory growth. Copying a Canvas node copies its embedded image into an independent node. Deleting the node removes its image from the saved graph.

## Default workspace

Parameters remains visible beside a shared tab group containing 2D Preview, 3D Preview and Canvas Editor. **View → Reset Workspace Layout** restores this arrangement.
