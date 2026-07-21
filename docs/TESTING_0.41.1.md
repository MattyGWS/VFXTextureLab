# VFX Texture Lab 0.41.1 Test Checklist

This patch focuses on the public interface and authoring experience of nested graph assets.

## 1. Reopen the included composition

Open `examples/graph_asset_rock_composition.vfxgraph` and single-click either Rock Material Generator instance.

Check that:

- The node sockets read **Shape Mask**, **Base Tint**, **Material**, **Height** and **Surface Variation**.
- No long hexadecimal interface IDs are visible on the node.
- The Parameters panel title reads **Rock Material Generator**.
- Random Seed, Rock Shape, Strata and Material controls are present.
- Changing a published control updates only that instance.

## 2. Check parameter publication UI

Open `examples/graph_assets/rock_material_generator.vfxgraph` and select an internal node with exposed controls, such as Terrace.

Check that:

- Each animatable row has the usual **◇** exposure button and one **…** graph-asset button.
- The separate **A** button is gone.
- Clicking **…** shows Public name, Parameter group, Interface order, Description and **Publish on Graph Instance nodes**.
- Disabling publication and saving removes that control after the parent instance reloads.
- Re-enabling it restores the control with its public name and group.
- Existing parent values survive public renaming because the hidden interface ID remains stable.

## 3. Preview Graph Outputs directly

Inside a source graph, double-click connected Graph Output nodes of several types.

Check that:

- A Greyscale or Colour Graph Output shows the connected image in 2D.
- A Signal Graph Output displays the connected signal value.
- A Material Graph Output shows Base Colour in 2D and the complete material in 3D.
- The Graph Output does not receive a red missing-evaluator badge.
- An actually unconnected Graph Output still reports clearly that it has no source.

## 4. Reload and persistence

Save the source, reload the linked parent and then reopen both files.

Check that public labels, publication state, groups, values and all existing wires survive. Embedded instances should show the same corrected labels and Parameters page.

## 5. Regression checks

Also verify that:

- Drag from Dolphin/Explorer, **Add Graph Asset…**, and registered library folders still insert assets.
- Material, Signal and image outputs still work through Send/Receive and downstream nodes.
- Random Seed remains the only public seed.
- Linked reload, embedding, missing-source fallback and recursion errors behave as in 0.41.0.
