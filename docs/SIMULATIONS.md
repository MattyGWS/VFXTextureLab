# Stateful simulations

VFX Texture Lab 0.16 introduces a graph-level state system for effects whose next frame depends on the result of an earlier frame. Ordinary nodes remain stateless and continue to evaluate any requested frame directly.

## Why this is faster during playback

A stateful node keeps its most recently evaluated state hot. Moving from frame 42 to frame 43 therefore performs one simulation step instead of replaying frames 0–43. In Auto/GPU mode, working state stays in WebGPU textures and ping-pongs between steps without a CPU readback.

Non-sequential requests still need history. The evaluator stores periodic CPU checkpoints and restores the nearest valid checkpoint before replaying the remaining frames. Backward scrubbing and repeated export passes are therefore substantially cheaper than always restarting from frame zero.

A first request far into the timeline can still take time because the missing history must be constructed once. The preview reports its current simulation frame and obsolete requests are cancellable.

## Runtime state and project files

Simulation textures are runtime data. They are never embedded into `.vfxgraph` or `.vfxnode` files. Projects save only the nodes, parameters and connections required to reproduce the state deterministically.

State is keyed by:

- node and document branch revision;
- dimensions and working precision;
- colour-space metadata;
- CPU or GPU execution path;
- reset generation and requested frame.

Changing a simulation parameter, an upstream node, resolution, precision or backend invalidates stale state. Moving a node on the canvas does not.

## Controls

- Stateful nodes show a small circular-arrow badge in their header.
- Right-click a stateful node and choose **Reset Simulation** to discard only that node's runtime state.
- Use the circular-arrow button in the Timeline transport to reset every simulation.
- Stop pauses playback without clearing state.
- Looping restores the saved loop-start state when playback wraps.

## Proof nodes

### Frame Delay

Outputs the previous frame's input, then stores the current input for the next frame. Frame zero starts black. This is useful for explicit one-frame timing offsets and proves that animated upstream inputs are sampled correctly during replay.

### Temporal Blend

Blends the current input with its previous result.

- **Persistence** controls how strongly history remains.
- `0` follows the current frame immediately.
- Values near `1` create longer trails and smoother temporal changes.

Alpha follows the current input rather than accumulating.

### Reaction Diffusion

A deterministic Gray-Scott two-field simulation for organic cells, corrosion, magical growth and dissolve-like patterns.

- **Feed** and **Kill** define the reaction regime.
- **Diffusion U/V** control how quickly each chemical spreads.
- **Time Step** scales each numerical step.
- **Steps per Frame** trades speed for more development per timeline frame.
- **Seed**, **Seed Count**, **Seed Radius** and **Seed Strength** build a procedural initial condition when no Seed image is connected.
- **Continuous Seed** injects a connected Seed mask on every frame instead of using it only for initialisation.

The output is the V chemical as a greyscale image. The internal U/V state remains private to the simulation node.

## Checkpoints and cancellation

Built-in simulation nodes currently checkpoint every 15 frames, plus the configured loop-start frame. Checkpoints are bounded and evicted so long sessions do not grow without limit.

A newer preview request cancels obsolete replay between frames and between Reaction Diffusion substeps. Sequential playback reuses the current state; backward scrubbing restores the nearest checkpoint and replays only the gap.

## Manual testing checklist

1. Add **Linear Gradient → Frame Delay → Single Image Output**.
2. Animate the gradient or its upstream transform, then move from frame 0 to frame 1. Frame Delay should show frame 0's input.
3. Play forward for several frames. The status bar should normally report one simulation step per rendered frame after the initial build.
4. Jump from frame 0 directly to frame 90. The preview should report simulation progress and remain cancellable.
5. Scrub backward to frame 50. It should restore a checkpoint and replay only the remaining interval.
6. Right-click Frame Delay and choose **Reset Simulation**. The current frame should rebuild to exactly the same deterministic result.
7. Test **Temporal Blend** with moving noise or a moving shape. Raise Persistence to produce a longer trail.
8. Add **Reaction Diffusion** without an input and play the timeline. The seeded pattern should evolve rather than independently regenerating each frame.
9. Connect a mask to Reaction Diffusion's Seed input. Reset the simulation and confirm the initial pattern follows the mask.
10. Enable Continuous Seed and confirm the mask keeps injecting into later frames.
11. Switch between CPU and Auto/GPU modes, reset, and compare the same frame. Small floating-point differences are expected; the structure should agree.
12. Loop a subsection of the timeline. Each wrap should return to the same loop-start state instead of feeding the loop end into its beginning.
13. Save and reopen the graph. The simulation should rebuild deterministically; runtime textures should not enlarge the project file.
