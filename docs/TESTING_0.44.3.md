# VFX Texture Lab 0.44.3 testing checklist

Version 0.44.3 adds the installable `.vfxpackage` format. A package is an ordinary ZIP-compatible archive internally, but VFX Texture Lab treats it as a validated graph asset with a manifest, stable Asset ID, file inventory and integrity hashes.

## 1. Export a basic package

1. Open a saved graph with a connected Graph Output.
2. Give it a Name, Author, Version, Description, Tags and thumbnail in Graph Properties.
3. Use **File → Export VFX Package…** or **Inspector → Portability & Recovery → Export VFX Package…**.
4. Save it as `My Asset.vfxpackage`.

Confirm:

- The completion message says the package was created and validated.
- The source graph is not modified and does not become dirty.
- The archive has the `.vfxpackage` extension.
- Renaming a copy to `.zip` lets an ordinary archive manager show `package.vfxmanifest`, `graphs/…vfxgraph`, and `thumbnail.png` when a thumbnail exists.
- Renaming is not required for normal use; VFX Texture Lab opens `.vfxpackage` directly.

## 2. Package details and metadata

Use **File → Open VFX Package…** and select the exported package.

Confirm the package window shows:

- Thumbnail.
- Asset name, version, author, category and tags.
- Description.
- Stable Asset ID.
- Application and package-format versions.
- Entry graph and file inventory.
- Bundled custom-node dependencies, when present.
- Any already-installed version with the same Asset ID.

Closing this window must not extract, install or modify anything.

## 3. Open Temporarily

Choose **Open Temporarily**.

Confirm:

- The graph opens in Graph Explorer with `(Package)` in its display name.
- It renders normally.
- It is an unsaved document rather than a graph pointing inside a temporary folder.
- The package archive remains unchanged.
- **Save** asks for a normal `.vfxgraph` location.
- Closing the temporary graph without saving does not modify the package.

## 4. Nested graphs and images

Create a parent graph containing:

- At least one linked Graph Instance.
- A child that itself contains another Graph Instance.
- At least one external Image Input.

Export a `.vfxpackage`, then move or rename all original child graphs and images.

Open the package temporarily and confirm:

- The complete result still evaluates.
- Every nested Graph Instance is embedded.
- Every Image Input is embedded.
- No original source path is required.
- Missing linked graphs with a valid last-known-good cache are reported as recovered during export.
- A truly missing image or graph with no recoverable copy blocks export with an ownership chain.

## 5. Extract as Editable Project

Open the package and choose **Extract as Editable Project…**. Select a parent folder.

Confirm:

- VFX Texture Lab creates a named project folder beneath the selected parent.
- The folder contains `package.vfxmanifest`, the entry graph, thumbnail when present, and bundled custom-node folders when required.
- The extracted entry graph opens automatically as a normal saved graph.
- Editing and saving it updates the extracted graph, not the original package.
- Extracting again to an occupied folder asks before replacement.
- Cancelling replacement leaves the existing folder untouched.

## 6. Install to Asset Library

Open the package and choose **Install to Asset Library**, or use **Library → Install VFX Package…**.

Confirm:

- The asset appears immediately under Graph Assets in Node Library.
- Its thumbnail and metadata are shown.
- Name, description, tags, author, version and output names remain searchable.
- Dragging the installed asset into a graph creates a working Graph Instance.
- The original `.vfxpackage` remains unchanged and may be deleted after installation.
- Installed files live under the application-managed Graph Asset `Packages` folder.

## 7. Update versus side-by-side installation

1. Install a package.
2. Change the source graph while keeping its Asset ID, increase its Version, and export it again.
3. Install the newer package.

Confirm the application reports the matching installed Asset ID and offers:

- **Update Installed** — replaces the selected managed installation.
- **Install Side by Side** — retains both package folders.
- **Cancel** — changes nothing.

For Update:

- The library shows the new version after refresh.
- The old managed package folder is replaced rather than accumulating stale files.

For Side by Side:

- Both graph-package versions remain present and are distinguishable by version/source details.
- Custom node packages use their own stable package IDs and cannot have two active runtime revisions simultaneously; the incoming bundled revision becomes the shared managed custom-node revision.

## 8. Bundled custom nodes

Use a graph containing a custom WGSL node from a registered or managed custom-node library.

Confirm:

- Export includes that custom node package automatically.
- Built-in bundled node packages are not redundantly copied.
- Package Details lists the custom node and version.
- **Open Temporarily** asks to install a missing or different custom-node revision before opening.
- **Install to Asset Library** installs or updates the bundled custom node automatically.
- **Extract as Editable Project** registers the extracted `custom_nodes` folder as a project custom-node library, then opens the graph successfully.
- A missing or invalid custom-node source blocks export instead of creating a package that will fail for the recipient.

## 9. Integrity and unsafe archive checks

Make disposable copies for these tests.

### Tampered graph

1. Rename a package copy to `.zip`.
2. Replace or edit its entry `.vfxgraph` without updating `package.vfxmanifest`.
3. Rename it back to `.vfxpackage` and open it.

The package must be rejected with a size or integrity-hash failure.

### Missing entry graph

Remove the entry graph from a package copy. It must be rejected as incomplete.

### Unexpected file

Add an unrelated file not listed in the manifest. It must be rejected.

VFX Texture Lab also rejects absolute paths, `../` traversal, symbolic links, encrypted members, duplicate paths, unsupported package versions and archives exceeding safety limits.

## 10. Opening through the normal Open dialogue and command line

Confirm:

- **File → Open…** lists both `.vfxgraph` and `.vfxpackage` formats.
- Selecting a `.vfxpackage` opens Package Details rather than trying to parse it as graph JSON.
- Starting the application with a package path, for example `python -m vfx_texture_lab MyAsset.vfxpackage`, opens Package Details after startup.
- Starting with a `.vfxgraph` still opens the graph normally.

## 11. Regression checks

Confirm the previous workflows remain intact:

- Export Self-Contained Graph still creates a single `.vfxgraph`.
- Graph thumbnail capture/import/clear still persists.
- Custom Node & Graph Asset library rescans do not disturb live graph wires.
- Single-click Graph Explorer inspection and double-click activation still work.
- Installed loose `.vfxgraph` assets and manually added asset folders remain usable.
- Ordinary graph Save, Save As, autosave recovery and nested Graph Instance evaluation are unchanged.
