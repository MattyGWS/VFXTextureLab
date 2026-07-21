# Evaluation Inspector

VFX Texture Lab 0.18.2 uses the dedicated inspector introduced in 0.18.0, exposes scheduler contention, and now also accounts for background histogram work while prioritising direct 2D interaction.

## Default placement

The inspector is placed to the right of the Timeline in the bottom dock area. It can be resized, tabbed, floated, closed and restored from the View menu like every other workspace panel. Existing saved workspaces are preserved; the inspector is introduced without resetting the user's other panels.

## Live information

While a preview or material evaluation is active, the inspector shows:

- 2D preview, playback or 3D material ownership;
- target node/material output;
- graph and material-map resolution;
- elapsed time;
- active node or finalisation stage;
- determinate progress for iterative work and indeterminate progress otherwise.

The 2D and 3D panels may still show brief local status, but they are no longer the main source of application-wide evaluation information.

## Evaluation priority

Direct interaction owns the renderer first. A 3D material branch is scheduled only while its Material is the active, double-clicked node. Double-clicking an ordinary node cancels or yields the material job and returns evaluation ownership to the 2D preview.

While Material remains active, its material evaluation yields between connected maps whenever direct UI work is waiting and uses a short 300 ms coalescing window during rapid edits. This prevents repeated material-map readbacks from starving the newest authored value.

When an evaluation still has to wait for the currently executing GPU/readback operation to reach a safe yield point, the completed trace includes an **Evaluation queue wait** row. Its timing accounts for the difference between total elapsed time and the sum of individual node timings.

## Completed trace

Each completed job records:

- node or stage name;
- CPU, GPU, Signal or pass-through backend;
- Computed, Cached, State step, Reroute or Bypassed state;
- elapsed time;
- cache hit/miss;
- output resolution and precision;
- estimated texture memory;
- a reuse or invalidation explanation.

Final GPU synchronisation/readback and 3D renderer upload appear as separate stages. Double-click a node row to select and centre that node in the graph.

## Wire flow

Only wires entering a node that remains active beyond 180 ms receive an orange moving dashed overlay. The normal data-type colour remains underneath it. The animation runs at a modest cadence and stops completely when no qualifying node is active.

## Background histograms

Levels, Histogram Range, Histogram Shift and Histogram Scan show an input histogram in the Parameters panel. These editors now evaluate the connected source output directly at the current graph-preview resolution so the normal 2D/3D Preview cache can be reused. Only the returned CPU pixels are sampled down to a bounded histogram workload.

Changing the adjustment node's own controls does not alter its input branch and therefore does not request another histogram. Active histogram work is cancelled as soon as an interactive edit begins, runs at background priority, and appears on the inspector's independent **Background:** line when a genuine upstream refresh is required.

## 3D material cache pressure

Material evaluates each distinct connected source/output directly. It no longer inserts a synthetic full-resolution Single Image Output node per material channel, so material refreshes do not fill the GPU cache with redundant 2K copies of Base Colour, Height, Normal and other maps.

## Dock safety

Docking, tabbing and floating remain fully supported. Cosmetic dock animations are disabled because Qt's animated native reparent path can crash on some Linux Qt/graphics-stack combinations. Workspace state is also saved only after the mouse drag has ended, rather than while Qt is still reparenting the dock widget.

## Testing checklist

1. Open a graph with a heavy erosion branch and keep the 2D Output tab hidden behind Material.
2. Change an upstream parameter and confirm the inspector identifies each active node/stage.
3. Confirm long-running incoming wires animate toward the working node and return to normal afterward.
4. Edit Levels downstream of completed erosion and confirm erosion is listed as Cached rather than Computed.
5. Confirm finalise/readback appears after GPU nodes and renderer upload appears for 3D previews.
6. Double-click a node row and confirm the graph centres and previews that node.
7. Activate a Material, then double-click and edit a downstream Levels node and confirm the 2D result takes priority; any unavoidable wait appears as Evaluation queue wait.
8. Confirm the 3D status text stays on one fixed-height line and the viewport no longer changes size while messages change.
9. Select a Levels node after a completed heavy erosion graph, drag a Levels handle, and confirm the inspector shows no long hidden histogram solve and erosion remains cached.
10. Connect several 3D material inputs and confirm completed traces no longer contain synthetic `3D Material Input` rows.
11. Float and redock the inspector repeatedly; docking should be immediate (without animation), stable, and persist after restart.
