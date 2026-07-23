# Testing VFX Texture Lab 0.51.1

This update focuses on resource drag-and-drop and direct OBJ drops. Use two throwaway graphs plus a small image and OBJ.

## 1. Resource drops inside the parent graph

1. Open a graph containing one Image Input and one Mesh Input.
2. Expand the graph in Graph Explorer.
3. Drag the image resource onto that graph's canvas. Confirm a new Image Input appears and the Explorer use count increases without creating a duplicate resource.
4. Drag the mesh resource onto the same canvas. Confirm a new Mesh Input appears, displays the imported geometry and shares the original resource.
5. Relink either resource through Explorer and confirm every node using that resource updates.

## 2. Safe cross-graph drops

1. Open a second graph and keep it active.
2. Drag an image or mesh resource from the first graph's Explorer hierarchy onto the second graph's canvas.
3. Confirm the correct input node is created in the second graph and a separate resource appears beneath the second graph.
4. Place the source resource inside nested virtual folders before repeating the drop. Confirm the folder hierarchy is recreated in the destination graph.
5. Rename, move, relink or embed the destination resource. Confirm the source graph and its nodes do not change.
6. Drop the same source resource into the destination again. Confirm the use count increases on the existing destination resource rather than adding another duplicate.
7. Test both a linked resource and a fully embedded resource. Save, close and reopen both graphs and confirm each remains self-contained according to its own resource state.
8. Test a source graph saved in a different directory with a relative linked path. Confirm the destination resolves the original source correctly rather than interpreting the relative path beside the destination graph.

## 3. OBJ drops from the file manager

1. Drag a valid `.obj` from the desktop or file manager directly onto an empty graph canvas.
2. Confirm a Mesh Input is created at the drop position, its geometry previews correctly and a mesh resource appears under the active graph.
3. Repeat with an OBJ containing an n-gon, one without normals and one without UVs to ensure the normal Mesh Input import behaviour remains intact.
4. Drag an unsupported mesh format such as `.fbx` or `.glb`. It should not create a node in this OBJ-only foundation.
5. Drag an image afterward and confirm the established Image Input drop workflow still works.

## Regression checks

- Dragging a graph entry from Explorer must still create a Graph Instance, not an Image Input or Mesh Input.
- Folder entries must not begin a canvas drag.
- Dropping resources while several graphs are open must always target the currently visible canvas.
- Undo the newly created node and confirm the resource remains available as an unused graph resource until explicitly removed.
- Save All, duplicate graph sessions, autosave/recovery, self-contained export and `.vfxpackage` creation must retain the copied resources and virtual folders.
- Confirm ordinary node-library drag insertion and drag-to-insert-on-wire behaviour are unchanged.
