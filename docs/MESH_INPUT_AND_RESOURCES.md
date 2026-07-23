# Mesh Input and graph resources

VFX Texture Lab 0.51.0 adds imported OBJ geometry and makes imported images and meshes first-class resources owned by each graph.

## Mesh Input

Add **Mesh Input** from **Inputs & Outputs**, then choose a Wavefront `.obj` file.

The node outputs the ordinary Geometry data type, so it can feed Geometry Transform, Clean / Weld, Normals, Subdivide, Un-Subdivide, Decimate, Displace, Bend, Twist, UV Transform, Combine, Material preview geometry or Geometry Output.

The importer currently supports the geometry portions of Wavefront OBJ:

- Vertex positions (`v`)
- Texture coordinates (`vt`)
- Vertex normals (`vn`)
- Polygon faces (`f`)
- Positive and negative indices
- Object and group names (`o` and `g`)

Polygon faces are triangulated with their authored winding. Corners with different UV or normal indices become separate interleaved vertices, preserving UV seams and hard-normal splits. Authored normals are normalised. When complete normals are absent, the importer generates area-weighted smooth normals while keeping duplicated UV-seam vertices visually continuous.

Materials, MTL files, animation, bones, curves and point-only OBJ data are not imported in this first foundation.

### Source information

The parameter panel reports:

- Imported vertex and triangle counts
- Whether the OBJ contains complete UVs
- Whether normals were authored or generated
- Object/group count and detected mesh name
- Source or parsing errors

The optional **Geometry name** overrides the imported object, group or filename used by downstream preview and export.

## Linked and embedded sources

A Mesh Input can use either source mode:

- **Linked** keeps the OBJ on disk and stores its path in the graph. Enabling **Embed in project** also keeps an embedded recovery copy while retaining that link.
- **Make Local / Embed in Graph** stores the exact OBJ bytes inside the `.vfxgraph`, clears the external path and no longer depends on the original file.

Mesh Input supports the same source workflow as Image Input:

- Reload the source metadata
- Relink or replace a missing/moved source
- Embed the source in the graph
- Restore an embedded copy to disk and relink it
- Reveal a linked source in the file manager

Self-contained graph export embeds imported OBJ bytes recursively. A `.vfxpackage` can additionally preserve those exact bytes under `resources/meshes/` so an installed or extracted package retains an editable source file as well as the graph's embedded fallback.

## Graph-owned resources

Each graph now stores a resource library. Image Input and Mesh Input nodes refer to stable resource IDs while retaining their existing runtime parameters for compatibility.

This provides several useful behaviours:

- Multiple nodes using the same file share one resource entry.
- Relinking or embedding through Graph Explorer updates every node using that resource.
- Directly changing one of several shared nodes to a different source creates or reuses a separate resource rather than unexpectedly changing the others.
- Missing sources are visible centrally.
- Unused imported resources remain available until deliberately removed.
- Embedded data is stored once in the saved graph resource record, then hydrated onto runtime node parameters when a graph or nested Graph Instance is loaded.

Existing graphs require no manual conversion. On load, old Image Input nodes are assigned graph resources automatically. Their established paths, embedded bytes, typing and evaluation behaviour remain valid.

## Resources in Graph Explorer

Expand a graph in **Graph Explorer** to see its imported resources.

- `▧` identifies an image resource.
- `◇` identifies a mesh resource.
- Missing, embedded and linked-plus-embedded states appear next to the resource.
- The tooltip shows status, source path and the number of using nodes.

Double-click a resource to activate its graph and select all nodes that use it.

Right-click a resource for:

- **Select Using Node(s)**
- **Relink / Replace Source**
- **Make Local / Embed in Graph**
- **Restore Embedded Copy As**
- **Reveal Source in File Manager**
- **Rename Resource**
- **Move to Folder**
- **Remove Unused Resource**

Removing a resource is only allowed when no nodes use it. It never deletes a linked file from disk.

## Virtual folders

Use **Folder +** in Graph Explorer, or right-click a graph/folder, to create virtual folders. Folders may be nested and can contain both image and mesh resources.

These are graph organisation only. Moving a resource between folders does not move or rename its actual source file. Removing a folder moves its child folders and resources to the removed folder's parent instead of deleting anything.

Default **Images** and **Meshes** folders are created as resources are first imported. They can be renamed or reorganised like any other virtual folder.

## Drag and drop

Resources can be turned back into nodes directly from **Graph Explorer**:

- Drag an image resource onto its parent graph to create an **Image Input** using that resource.
- Drag a mesh resource onto its parent graph to create a **Mesh Input** using that resource.
- Drag either resource onto a different open graph to copy it into the destination graph first, then create the matching input node.

Cross-graph drops never point a destination node at the source graph's resource ID. The destination receives its own resource record, embedded payload and virtual folder hierarchy. Linked paths are resolved against the source graph before copying, so relative paths do not accidentally refer to a different file beside the destination graph. Repeated drops reuse an equivalent copied resource.

Wavefront `.obj` files can also be dragged directly from the operating-system file manager onto the graph canvas. This creates a linked **Mesh Input** in the same way that dropping a supported image creates an Image Input. The imported file then appears beneath that graph in Graph Explorer.

## Graph format

The resource library and folder hierarchy advance the `.vfxgraph` format from version 18 to version 19. Migration is automatic and idempotent: loading or saving an older graph creates only the missing resource records.

A later UV workflow can build on the same foundation by operating on Mesh Input or procedural Geometry without coupling unwrapping to file import.
