# Graph Assets and Nested `.vfxgraph` Nodes

VFX Texture Lab can use a complete `.vfxgraph` as one reusable node inside another graph. A graph asset remains encapsulated: its public sockets come from Graph Input and Graph Output nodes, its public controls come from exposed parameters, and its internal graph is evaluated lazily only when a parent requests one of its outputs.

This is deliberately different from reusable Groups:

- A **Group asset** inserts editable copies of its nodes into the current graph.
- A **Graph asset** remains one linked or embedded Graph Instance node with a controlled public interface.

Graph assets are suitable for reusable generators such as rocks, terrain macros, complete PBR materials, flipbook effects, masks and higher-level utilities.

## Declaring inputs

Add **Graph Input** from the Graph Assets category. One node supports every public type through its **Data Type** dropdown:

- Greyscale
- Colour
- Vector / Normal
- Signal
- Material

Each Graph Input defines:

- Name
- Data Type
- Description
- Required
- Interface Order
- A type-appropriate default value

A Graph Input becomes one input socket on every Graph Instance of the file. Leaving an optional socket unconnected uses its authored default. A required input also has a default so the graph remains evaluable, but the instance displays a warning until the parent connects it.

## Declaring outputs

Add **Graph Output** and connect the result that should be public. Its data type is inherited from the connected value, so the graph author cannot accidentally declare a Material output while connecting a greyscale texture.

Each Graph Output defines:

- Name
- Description
- Interface Order
- Primary Preview Output

An unconnected Graph Output is not published. If no output is explicitly marked primary, the first ordered output becomes the default preview output. While authoring the source graph, double-clicking a connected Graph Output previews its connected typed source directly; Material outputs activate the complete 2D/3D material workflow.

Dedicated Graph Outputs do not replace Single Image Output, Texture Set Output or Flipbook Generator. Those nodes retain their export and application-level behaviour; Graph Output exists only to describe a nested graph's public interface.

On a Graph Instance, double-click any public output circle to preview that exact output. The active output is highlighted and saved, while double-clicking the node body returns to its primary output. This remains lazy: choosing Height does not also evaluate Material or Surface Variation.

## Publishing parameters

VFX Texture Lab reuses the existing parameter-exposure system.

1. Click the **◇** button beside an animatable numeric parameter to expose it.
2. Leave that exposed parameter unconnected inside the asset.
3. It becomes a normal Parameters-panel control on the Graph Instance.

If the exposed parameter is internally connected, it is driven by the internal graph and is not published as an instance control. To let a parent graph drive it, connect a Signal Graph Input to the exposed parameter socket instead.

The **…** button opens the Graph Asset Parameter dialogue. It edits the public presentation without changing the internal node:

- **Publish on Graph Instance nodes**
- Public name
- Description / tooltip
- Parameter group
- Interface order

Disable publication when a parameter should remain exposed for local animation or authoring but should not appear on Graph Instances. Internally connected exposed parameters remain private regardless of this checkbox.

Public sockets and parameters have stable hidden interface IDs. Renaming a control or socket therefore preserves parent connections and saved instance values.

## One coherent Random Seed

Every Graph Instance always has exactly one **Random Seed** parameter. Individual internal seed parameters are not published separately.

The instance seed is deterministically combined with:

- Each internal node's authored seed
- The stable internal node and parameter identity
- Any containing Graph Instance seed

Changing the one public seed therefore changes all internal random processes without making unrelated noises use the same effective number. Two instances with the same graph, inputs, parameters and Random Seed remain reproducible. Nested graph assets inherit the outer seed coherently.

## Adding a graph asset

There are four entry points.

### Drag from Graph Explorer

Open or create both graphs in the same application session, then drag the source entry from **Graph Explorer** onto the active parent canvas. The parent uses the open in-memory source immediately: saved sources serialise as Linked and unsaved sources serialise as Embedded. See [`GRAPH_EXPLORER.md`](GRAPH_EXPLORER.md) for live editing, closing and recovery behaviour.

### Drag from the file manager

Drag any valid `.vfxgraph` from Dolphin, Explorer or another file manager onto the canvas. It becomes a linked Graph Instance at the drop position.

### Add Graph Asset from search

Open ordinary add-node search and choose **Add Graph Asset…** to pick a file. Registered assets also appear in their own **GRAPH ASSETS** result group. Loose-wire compatible-node search intentionally omits assets and the file picker to remain focused.

### Register asset folders

The Node Library has an **Add Asset Folder…** button and a default application Graph Assets folder. Folders registered through **Library → Custom Node & Graph Asset Libraries…** are also scanned, so one author library may contain custom node packages, reusable `.vfxgraph` assets, or both. Enabled folders are scanned recursively for `.vfxgraph` files with at least one valid Graph Output. Assets appear under a distinct Graph Assets category and can be dragged like built-in nodes.

Any valid `.vfxgraph` with a connected Graph Output is usable. Graph Properties can author a stable Asset ID, name, category, description, tags, author, version and thumbnail.

Selecting a registered Graph Asset in Node Library shows an evaluation-free details card with its thumbnail, metadata, published outputs, source path and validation state. Search covers names, descriptions, categories, tags, authors, versions and public output names. Invalid or unreadable assets remain visible under **Graph Assets / Problems** rather than disappearing silently; valid assets with non-blocking interface warnings remain usable and receive a warning marker.

Right-click a library asset to open its source graph, validate it, edit its thumbnail in the Inspector or reveal its source folder.

## Graph asset thumbnails

Graph Properties includes a dedicated **Thumbnail** section:

- **Capture 2D** uses the current 2D Output.
- **Capture 3D** uses the current Material viewport.
- **Import Image…** accepts an existing image.
- **Clear** removes the stored thumbnail.

The result is fitted into a 256 × 256 square without stretching and stored as compact PNG data inside the `.vfxgraph`. Node Library therefore never needs to evaluate every graph while scanning asset folders. Preview capture is enabled only for the active Graph Explorer document, preventing an inactive graph from accidentally receiving another document's current preview.

## Linked and embedded instances

A newly dragged or imported graph is **Linked** by default. The node references the source file and automatically reloads it after changes are saved.

Right-click a Graph Instance for:

- Open Source Graph
- Reload from Disk
- Use Cached Revision / Make Local
- Restore Cached Revision As…
- Relink…
- Relink All Matching Instances…
- Reveal Source in File Manager

**Use Cached Revision / Make Local** stores the last-known-good graph revision inside the parent. Embedded instances keep working if the original file is moved or deleted and do not automatically receive source updates. **Restore Cached Revision As…** writes that recovery copy as a validated self-contained `.vfxgraph` and relinks the selected instance to it.

A linked instance retains its last known good graph data. If the source becomes temporarily unavailable, the instance remains evaluable and shows a missing-source warning. Relinking or restoring the source returns it to normal linked operation.

When **Open Source Graph** is used, the source opens as another document in Graph Explorer. While it remains open, matching parent instances use the current in-memory revision and update after a short debounce, even before the source is saved. Closing a saved source returns dependants to the linked disk revision.

Embedded instances provide **Open Embedded Graph**, which opens their stored source as an unsaved Explorer document. Edits propagate to the parent live and are embedded again when that source document closes.

## Self-contained graph export

Use **File → Export Self-Contained Graph…** or the same action in Graph Properties to create one portable `.vfxgraph`. Every reachable Graph Instance is recursively converted to Embedded mode and every Image Input is stored as image bytes. Current open child revisions take precedence over older disk copies; a missing linked graph can use its last-known-good cache. The written copy is validated and the active source graph is never modified.

Image Input nodes also provide context actions to relink one or all matching references, make an image local, and restore embedded bytes as a normal external file.

## Installable `.vfxpackage` assets

Use **File → Export VFX Package…** or the Graph Properties portability section to create an installable asset archive. A `.vfxpackage` is a normal ZIP-compatible container with an application-specific extension and a validated `package.vfxmanifest`. The manifest identifies the entry graph, stable Asset ID, author/version metadata, thumbnail, bundled custom-node packages and every contained file with its byte size and SHA-256 hash.

Package export uses the same recursive self-contained conversion as single-file graph export, so linked Graph Instances and Image Inputs no longer depend on the author's filesystem. By default, the exporter also writes exact imported image bytes into `resources/images/`; these are separate artist-editable source files while the graph retains embedded fallback copies for direct temporary opening. The option can be disabled for a smaller embedded-only package. External custom WGSL node packages used by the graph or any nested child are bundled automatically; node packages shipped with VFX Texture Lab are recognised as built-in dependencies and are not copied.

After extracting or installing a package, an Image Input with a preserved source file offers **Use Included Package Source**. This switches the node from its embedded fallback to the separate resource stored with the package.

Opening a package displays its details before any action and offers:

- **Open Temporarily** — opens the entry graph as a clean unsaved Explorer document. Save therefore becomes an explicit Save As and never writes into a temporary extraction folder.
- **Extract as Editable Project…** — safely extracts the complete package to a chosen project folder and opens its saved entry graph. Bundled custom nodes are registered from the extracted project's `custom_nodes` folder.
- **Install to Asset Library** — installs the package under the application-managed Graph Asset `Packages` directory and installs any bundled custom nodes into the managed Custom Node library.

Installing an Asset ID that already exists offers **Update Installed**, **Install Side by Side**, or Cancel. Updates replace the selected managed package through a staging directory; side-by-side installation preserves both graph-package folders. Bundled custom nodes retain their own stable package IDs, so an incoming custom-node revision updates that shared managed dependency rather than loading two runtime revisions under one ID.

Before opening or extracting, VFX Texture Lab rejects unsupported package versions, missing or undeclared files, modified hashes, absolute paths, drive-qualified paths, `../` traversal, symbolic links, duplicate members, encrypted members and archives exceeding safety limits. Only files declared by a valid manifest are ever extracted.

See [`TESTING_0.44.3.md`](TESTING_0.44.3.md) for the complete package workflow and [`TESTING_0.44.3.1.md`](TESTING_0.44.3.1.md) for separate image-source preservation.

## Source updates and interface safety

When a linked asset reloads:

- New public parameters use their source defaults.
- Untouched instance parameters follow changed source defaults.
- Explicit parent overrides retain their values.
- Renamed sockets and parameters preserve wiring and values through stable IDs.
- Removed connected sockets remain visible as **(missing)** instead of silently deleting parent wires.
- Changed socket types retain visibly incompatible connections where possible rather than concealing the interface break.

The Parameters panel reports the asset's mode, status, source and published outputs.

## Evaluation and caching

Graph Instances use the same evaluator as built-in nodes. The parent evaluator expands only instances reachable from the requested result, substitutes public inputs and parameter overrides, then evaluates only the requested public output.

This preserves:

- CPU and WGSL execution
- Graph-result caching
- Lazy Material channel resolution
- Signal and timeline evaluation
- Send/Receive portals
- Texture Set Output planning
- 2D and 3D previews
- Stateful simulation isolation

Every instance receives a private runtime namespace for Frame Delay, Temporal Blend, Reaction Diffusion and future stateful nodes. Two instances of the same source cannot accidentally share simulation state.

The cache identity includes the source revision, instance parameters, Random Seed, connected input revisions, requested output, resolution, frame and precision. Requesting one output does not force unrelated public outputs to evaluate.

## Dependency safety

Graph assets can contain other graph assets. VFX Texture Lab rejects direct and indirect recursive dependencies and limits accidental nesting to 64 levels. Missing dependencies use their own last-known-good cached graph where available and otherwise produce a clear node error rather than hanging.

## Included example

`examples/graph_assets/rock_material_generator.vfxgraph` demonstrates:

- Greyscale and Colour Graph Inputs
- Material, Height and mask Graph Outputs
- Grouped public parameters
- One coherent Random Seed controlling several internal random nodes
- A complete procedural Material output

`examples/graph_asset_rock_composition.vfxgraph` embeds two independent instances, changes their seeds and controls, tints them differently, height-blends their Material outputs, breaks out Height and feeds Texture Set Output.
