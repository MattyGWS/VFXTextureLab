# Testing VFX Texture Lab 0.51.0

This pass is intentionally focused on Mesh Input, resource portability and the expanded Graph Explorer. Use throwaway copies of graphs while testing migration.

## 1. Basic Mesh Input

1. Add **Mesh Input** from **Inputs & Outputs**.
2. Load a simple triangulated OBJ with UVs and normals.
3. Confirm the mesh appears when the node is focused and can be connected to Material geometry override and Geometry Output.
4. Confirm Source Information reports sensible vertex/triangle counts, UV status, authored normals and object/group count.
5. Set **Geometry name** and confirm the override is used downstream.

Repeat with:

- A quad or n-gon OBJ to verify triangulation
- An OBJ with UVs but no normals to verify generated shading normals
- An OBJ without UVs to verify it imports but reports **UVs missing**
- An OBJ with UV seams or hard normals to check that seams do not collapse
- A moderately dense production mesh to assess import and focus-switch performance

## 2. Linked and embedded meshes

1. Save a graph containing a linked Mesh Input, close it and reopen it.
2. Move or rename the OBJ on disk. Reopen/refresh the graph and confirm the resource is marked missing rather than crashing.
3. Use **Relink / Replace Source** from the Mesh Input context menu and from Graph Explorer.
4. Use **Make Local / Embed in Graph**, save, temporarily remove the original OBJ and reopen the graph. The mesh should still evaluate.
5. Use **Restore Embedded Copy As**, choose a new path and confirm the resource becomes linked to the restored OBJ.
6. Export a self-contained graph and confirm the imported mesh survives on another folder/path without its original OBJ.

## 3. Existing Image Input migration

1. Open several pre-0.51 graphs containing linked and embedded Image Input nodes.
2. Confirm they evaluate identically and require no manual action.
3. Expand each graph in Graph Explorer and confirm the image sources appear under graph resources.
4. Save and reopen the migrated graph. Confirm no duplicate resource entries are added.
5. Use two Image Input nodes pointing to the same file and confirm they share one resource with a use count of two.

## 4. Graph Explorer hierarchy

1. Confirm every open graph remains a top-level Graph Explorer entry.
2. Import images and meshes and confirm they appear beneath the correct graph.
3. Double-click a resource and confirm its graph activates and all using nodes are selected.
4. Create root and nested virtual folders with **Folder +** and the context menu.
5. Rename folders and resources, then move resources between folders and graph root.
6. Save/reopen and confirm the full hierarchy persists.
7. Remove a folder and confirm children move to its parent without any source files being moved or deleted.
8. Delete the final node using a resource, then remove the unused resource from Explorer.

## 5. Shared-resource behaviour

1. Create two Image Input or Mesh Input nodes using the same file.
2. Confirm Explorer shows one resource and a use count of two.
3. Relink the resource through Explorer and confirm both nodes update.
4. Change only one node's source directly in its parameter panel. Confirm it becomes a separate resource and the other node retains its old source.
5. Toggle **Embed in project** on only one of two shared nodes. Confirm that use splits rather than silently changing the other node's portability mode.
6. Rename a resource in Explorer, relink it and confirm the custom display name is preserved.

## 6. Packages

1. Create a `.vfxpackage` from a graph containing Mesh Input and Image Input.
2. Inspect/install/extract it and confirm validation succeeds.
3. Confirm imported OBJs are preserved under `resources/meshes/` and images under `resources/images/` when source inclusion is enabled.
4. Confirm the packaged graph remains self-contained even when the separate source-resource copies are unavailable.

## Regression checks

- Create, save, reopen and export procedural Geometry with no imported resources.
- Test ordinary Image Input reload, embed, restore and normal-map detection.
- Open several graphs, switch between them, duplicate a graph containing an embedded image/mesh, drag a graph containing embedded resources into another and use Save All.
- Confirm Graph Explorer graph dragging still creates Graph Instance nodes; resource/folder entries must not be draggable as graph instances.
- Confirm autosave/recovery retains resource folders and embedded source data.
- Confirm the Windows packaging workflow still builds the source tree without missing `graph_resources.py`.

Record the source OBJ type, operating system, GPU, exact action and terminal output for any failure. A minimal `.vfxgraph` plus its small source OBJ is particularly useful for import problems.
