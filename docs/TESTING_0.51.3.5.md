# Testing VFX Texture Lab 0.51.3.5

This is a source-only correction for deep topology-protected decimation. If the 0.51.3 dependency setup was already completed, overwrite the project folder and launch normally; `setup.sh` / `setup.bat` does not need to be rerun.

## Primary regression

1. Import the same closed rock OBJ used for the 1% decimation test.
2. Connect a single Geometry Decimate node and set Percentage to 1%.
3. Confirm the node no longer stops at the first large watertight prefix such as roughly 9,820 triangles when the requested target is roughly 648.
4. Confirm the Inspector reports `Native QEM (iterative topology-protected · N passes)` when multiple collapse plans are required.
5. Confirm every pass keeps the original absolute target. A 1% request must not become 1% of 1% on later passes.
6. Compare the single-node result with the previous chain of repeated 1% Decimate nodes. The single node should now reach the requested target, or stop only when a fresh pass makes no further safe progress or the bounded pass limit is reached.
7. Inspect the result closely for holes, cracks, spikes, flipped regions and detached UV-seam edges.

## Responsiveness and diagnostics

- Repeatedly drag Percentage and confirm latest-request-wins behaviour, orange evaluation wires and cancellation still work.
- Confirm progress messages mention successive watertight passes and the interface stays responsive.
- Confirm the Result row reports both the absolute target and actual output triangle count.
- Confirm no Python compatibility fallback warning appears unless the native package is genuinely missing or the backend raises an unrecoverable error.

## General checks

- Test a closed imported mesh, an open mesh and a generated Geometry Box.
- Confirm UVs and shading remain intact after iterative reduction.
- Confirm Mesh Input diagnostics, Geometry Statistics and Auto Wireframe suppression above 250,000 triangles remain correct.
- Launch with `run.sh`; this update does not change dependencies or graph format.
