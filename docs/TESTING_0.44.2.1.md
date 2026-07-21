# VFX Texture Lab 0.44.2.1 Testing — Shared Libraries and Refresh Safety

## 1. Re-test the reported Graph Asset folder workflow

1. Create a folder containing a valid saved `.vfxgraph` with at least one connected Graph Output.
2. Give the graph a distinctive Name and Tags in Graph Properties, then save it.
3. Open **Library → Custom Node & Graph Asset Libraries…**.
4. Add that folder.
5. Close the dialog; do not restart the application.

Expected:

- The graph appears immediately under Graph Assets in the Node Library.
- Searching by its Name or any Tag finds it.
- Its thumbnail and metadata details appear when selected.
- Double-click/drag creates a Graph Instance normally.

## 2. Enabled toggle

1. Return to **Custom Node & Graph Asset Libraries…**.
2. Untick the folder.
3. Close the dialog.
4. Re-enable it afterwards.

Expected:

- Disabling removes its graph assets from the Node Library without deleting files.
- Re-enabling restores them immediately.

## 3. Live graph safety while adding and rescanning folders

1. Open a moderately connected graph, preferably with Material inputs and several differently typed wires.
2. Take a screenshot or note every connection.
3. Add an asset-only folder through the shared-library dialog.
4. Press **Rescan Now** several times.
5. Use the Node Library refresh button as well.

Expected:

- Existing wires do not swap, cross, detach, reverse, or change type.
- The preview remains the same.
- The graph does not gain an unsaved marker solely because of a library refresh.
- Saving and reopening is not required to restore the graph.

## 4. Mixed library folder

Place both a valid custom node package and one or more `.vfxgraph` files beneath the same registered folder.

Expected:

- The custom node appears under its declared category.
- The graph assets appear under Graph Assets.
- Editing/reloading the custom node package keeps existing connections attached to surviving socket names.
- Graph Asset thumbnails and search remain functional after the custom node reload.

## 5. Existing Add Asset Folder route

Use the **Add Asset Folder…** button at the bottom of the Node Library with a different folder.

Expected:

- This dedicated route continues to work exactly as before.
- A folder registered through both routes is scanned only once and does not create duplicate entries.
