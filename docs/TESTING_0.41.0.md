# VFX Texture Lab 0.41.0 Test Checklist

The highest-value test is to use the included Rock Material Generator first, then author one small graph asset yourself.

## 1. Open the included composition example

Open:

`examples/graph_asset_rock_composition.vfxgraph`

It contains two embedded Rock Material Generator instances.

Check that:

- Both appear as single purple-accent Graph Instance nodes rather than expanded internal graphs.
- Each has only one Random Seed parameter despite several internal seeded nodes.
- The two seeds produce visibly different rock forms.
- Base Tint input sockets accept the connected Colour nodes.
- Material outputs feed Material Blend normally.
- Focusing Material Blend shows the complete result in 2D and 3D.
- Material Channels Height reaches Single Image Output.
- Texture Set Output plans Base Colour, Height and Roughness maps.

At 2K, return to previously focused material nodes as well; the 0.40.1 preview caches should still make repeat visits fast.

## 2. Drag a `.vfxgraph` from the file manager

Drag:

`examples/graph_assets/rock_material_generator.vfxgraph`

from Dolphin or Explorer onto a blank canvas.

Check that:

- A Rock Material Generator node appears exactly at the drop location.
- It has Shape Mask and Base Tint inputs.
- It has Material, Height and Surface Variation outputs.
- Its Parameters panel contains one Random Seed plus grouped Rock Shape, Strata and Material controls.
- Changing Random Seed changes every random aspect coherently.
- Duplicating the node and using the same seed gives the same result.

## 3. Test the ordinary search entry point

Right-click blank canvas space or press Space.

Check that:

- The popup contains one **Add Graph Asset…** action under IMPORT.
- Choosing it opens a `.vfxgraph` file picker and inserts the selected graph.
- Loose-wire search from a dragged connection does not contain the file picker or an unrelated list of assets.

## 4. Register an asset folder

Open Node Library and choose **Add Asset Folder…**. Select the included `examples/graph_assets` folder or another folder containing graph assets.

Check that:

- A Graph Assets category appears separately from built-in nodes and reusable Groups.
- Rock Material Generator appears under Terrain / Materials.
- Filtering the library for `rock` finds it.
- Dragging it from Node Library creates a linked Graph Instance.
- Searching `rock` in ordinary add-node search shows a separate GRAPH ASSETS result group.

The asset-folder context menu should reveal the source and allow that registered folder to be removed.

## 5. Author a basic graph asset

Create a new graph containing:

1. Graph Input set to Greyscale and named `Mask`.
2. A Noise node.
3. A Blend or other node that uses Mask.
4. Graph Output connected to the result and named `Pattern`.

Save it as `.vfxgraph`, then drag it into another graph.

Check that:

- Graph Input becomes a greyscale Mask socket.
- Graph Output becomes a greyscale Pattern output automatically.
- Renaming the Graph Output and saving the source updates the linked instance without changing existing parent wires.
- Leaving Graph Output disconnected prevents it from being published.

Repeat with Graph Input set to Colour, Vector / Normal, Signal and Material where convenient. Connections should follow the declared types.

## 6. Publish parameters

Inside the source asset:

1. Expose a numeric parameter with **◇**.
2. Leave its exposed socket unconnected.
3. Keep **A** enabled.
4. Use **…** to rename it, set a tooltip, choose a public group and change its order.
5. Save the source.

Check the parent instance:

- The control appears with the public name and group.
- Changing it affects only that instance.
- The reset action returns it to the source default.
- Renaming it again in the source preserves the instance value.
- Turning **A** off removes it from newly reloaded interfaces without changing its local animation exposure in the source graph.
- Connecting its exposed socket internally hides it from the public instance interface.

Seed parameters should never appear individually; only Random Seed should be public.

## 7. Test linked auto-reload

Keep a parent graph and its linked source graph open.

Change and save the source, for example:

- Change the default of an untouched public parameter.
- Add a new Graph Output.
- Rename an existing input or output.

Within roughly a second, check that the parent instance reloads:

- New ports appear.
- Renamed ports keep their connections.
- Untouched parameter values follow changed source defaults.
- Explicitly changed instance values remain overridden.

Use right-click → Reload from Disk to force the same operation manually.

## 8. Remove a connected public socket

Connect a parent wire to one source output, then remove that Graph Output in the source and save.

Check that:

- The parent wire is not silently deleted.
- The old socket remains visible with **(missing)** in its label.
- The Graph Instance shows a clear interface warning.
- Disconnecting or relinking can resolve it deliberately.

## 9. Test embedded mode

Right-click a linked Graph Instance and choose **Make Local / Embed**. Save the parent, then move or temporarily rename the original source file.

Check that:

- The embedded instance still evaluates after reopening the parent.
- Its mode reads Embedded in Parameters.
- It does not automatically change when the external source is edited.
- Other linked instances of the same source still update normally.

## 10. Test Material, portals and export

Create or use an asset with a Material Graph Output.

Check that its Material output can feed:

- Material Blend
- Material Override
- Material Channels
- Send → Receive
- Texture Set Output
- 3D Preview

Only authored channels should be evaluated and exported. A graph asset containing only Base Colour, Height and Roughness should not generate unused default texture maps.

## 11. Test Signal and animation outputs

Create a Signal Graph Input connected directly to a Signal Graph Output, or place Time/Loop Phase logic inside an asset.

Check that:

- Signal sockets remain scalar typed.
- Parent signals override the Graph Input default.
- Timeline playback updates nested animated outputs.
- A nested Material Switch or animated texture continues changing during play.

## 12. Test stateful instance isolation

Put Frame Delay, Temporal Blend or Reaction Diffusion inside an asset and create two instances with different inputs or seeds.

Advance or reset one instance.

Check that:

- The other instance does not inherit its state.
- Resetting simulation behaves per instance.
- Scrubbing and replay remain deterministic.

## 13. Test missing files and relinking

With a linked instance saved in a parent graph, temporarily move the source file.

Check that:

- The instance reports Missing source.
- Its last known good cached revision still evaluates.
- Relink… can point it to the moved source.
- Restoring the source returns it to normal linked status.

## 14. Test dependency safety

Try to place a graph inside itself, or create A → B → A through linked graph assets.

Check that VFX Texture Lab reports a recursive graph-asset dependency rather than hanging or overflowing.

## 15. Recheck Fluvial preview finalisation

At 2K, focus Fluvial Erosion and repeatedly test high Channel Widening, including 1.0. Change focus between Fluvial and other nodes without editing the graph.

Check that:

- A valid erosion result no longer occasionally becomes a cached black 2D presentation.
- Legitimately black graphs still display black rather than being rejected.
- Export and downstream output remain unchanged.

A malformed or empty small preview readback is now rebuilt from the valid completed full-resolution result before it enters the presentation cache.
