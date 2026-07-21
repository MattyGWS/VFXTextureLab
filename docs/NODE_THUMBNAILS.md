# Optional live node thumbnails

VFX Texture Lab 0.43.0 adds visual checkpoints without changing the default compact graph. Every ordinary node with a visual output starts collapsed and performs no thumbnail evaluation until the user explicitly expands it.

## Show or hide a thumbnail

Compatible nodes show a small chevron at the right side of the title bar, beside the existing bypass/power control where one exists.

- Click the downward chevron to expand the thumbnail.
- Click the upward chevron to collapse it.
- The expanded node places one fixed 128 × 128 image directly beneath its title and above every input/output row.
- The choice is undoable and saved with the graph. Older graphs open with every node collapsed.

The default graph appearance and graph evaluation path therefore remain unchanged until an individual node is opted in.

## Multi-output nodes

A node owns one thumbnail, not one thumbnail per output. The primary output is selected when the thumbnail is first enabled.

Right-click the chevron to choose **Thumbnail Output** on nodes such as Worley, Fluvial Erosion, Flood Fill, Material Channels or Graph Instances. The selection uses the stable output identity and is saved in the `.vfxgraph`.

Changing the output used by the main 2D Preview does not silently change the pinned thumbnail, and changing the pinned thumbnail does not change the main preview lock.

## Data types

- **Greyscale and Colour** use the same display conversion as the 2D Preview.
- **Vector / Normal** appears using the encoded RGB representation.
- **Material** shows its resolved Base Colour while the complete material remains available in the 3D Preview.
- **Signal** uses a compact numeric tile.

Structural items that are intentionally compact do not offer a thumbnail: reroutes and Send/Receive portal aliases. Nodes with no visual output also have no chevron.

## Docked nodes

A docked node never displays a thumbnail or thumbnail chevron. Its saved opt-in state is retained, so undocking it restores the expanded thumbnail. This keeps nested docking as compact as before.

## Placeholder and update states

A thumbnail that has never completed does not display an ambiguous black image. It shows a neutral checker with **Not evaluated**.

Other states are:

- **Rendering…** — the first low-resolution result is in progress.
- **Updating…** — the previous valid image is retained and dimmed while a newer revision waits.
- **Preview error** — the last valid image is retained where possible and the unchanged failing revision is not retried in a loop.

A genuinely black node result remains visibly black once evaluation completes.

## Performance model

### Collapsed nodes

Collapsed nodes submit zero thumbnail jobs, allocate no thumbnail image, and perform no GPU readback for thumbnails. The ordinary 2D/3D preview and graph evaluator behave as before. The application only performs a negligible check for whether any expanded thumbnails exist when graph/view state changes.

### Expanded nodes

Thumbnail work follows strict safeguards:

1. It uses a fixed 128 × 128 render; it never requests the document's 2K/4K/8K resolution merely for a node image.
2. It runs below normal 2D and 3D preview priority and uses the bounded interactive workload for expensive nodes.
3. Only expanded nodes currently visible in the canvas viewport are refreshed.
4. Only one independent thumbnail evaluation is in flight at once.
5. Parameter interaction, 2D preview, 3D material work and playback pre-empt thumbnail work.
6. The active node can reuse an already completed 2D/playback result and downsample it without reevaluating the graph.
7. Completed thumbnails are RGBA8 and cached by graph session, node, exact output, upstream branch revision, precision, colour space and frame.
8. The cache is bounded to 32 MiB and uses least-recently-used eviction. A 128 × 128 RGBA8 entry uses 64 KiB.
9. Independent thumbnail jobs are disabled during timeline playback. The active thumbnail follows the already presented playback frames; other pinned nodes settle after playback pauses.
10. **Render → Clear Render Cache** clears graph caches, presentation caches and node thumbnails together.

These rules make the feature effectively free when unused and deliberately subordinate to interactive work when enabled. An expanded expensive node can still require some computation the first time it has no reusable result, so a literal zero-cost guarantee would be dishonest; the system ensures that this cost is small-resolution, bounded and non-blocking.

## GPU Diagnostics

The GPU Diagnostics panel reports the **Node thumbnail cache** separately from graph GPU/CPU caches, 2D presentation caches and 3D material caches. This makes unexpected thumbnail memory use visible.
