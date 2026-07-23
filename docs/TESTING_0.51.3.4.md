# Testing VFX Texture Lab 0.51.3.4

This is a source-only correction for topology-protected native decimation. If the 0.51.3 dependency setup was already completed, overwrite the project folder and launch normally; `setup.sh` / `setup.bat` does not need to be rerun.

## Primary regression

1. Import the same closed rock OBJ that previously displayed the orange warning.
2. Connect it to Geometry Decimate and set a demanding percentage such as 25–30%.
3. Confirm the interface remains responsive and the node uses either:
   - `Native QEM (fast-simplification)`, or
   - `Native QEM (topology-protected)`.
4. When topology protection is used, confirm the result may contain slightly more triangles than the requested target and the Inspector explains that it stopped at the nearest watertight native state.
5. Confirm no Python compatibility fallback warning appears unless there is a genuine native-package or unrecoverable backend error.
6. Inspect the mesh closely for holes, cracks, spikes, flipped regions and detached UV-seam edges.

## General checks

- Repeatedly drag the Percentage control and confirm latest-request-wins behaviour, orange evaluation wires and progress reporting still work.
- Test an open mesh and a closed generated Box.
- Confirm Mesh Input diagnostics, Geometry Statistics and Auto Wireframe suppression above 250,000 triangles still display correctly.
- Launch with both `run.sh` and `run.bat` where available to confirm the startup import-cycle fix remains intact.
