# Testing VFX Texture Lab 0.51.3.3

## Startup regression

1. Overwrite the existing 0.51.3.x source folder with this archive.
2. Launch using `./run.sh` on Linux or `run.bat` on Windows.
3. Confirm the application reaches the main workspace without an `AngleDial` / partially initialized `ui.parameters` import error.
4. No setup rerun is required when the 0.51.3 dependency environment is already installed.

## Dense-geometry regression

1. Focus a dense generated or imported mesh routed through Geometry Subdivide.
2. Confirm Geometry Statistics still shows input/output vertex and triangle counts.
3. Confirm Auto Wireframe still disappears above 250,000 triangles and the Inspector explains why.
4. Set Wireframe to Always and confirm the overlay can still be forced.
5. Confirm Geometry Decimate continues to report Native QEM when `fast-simplification` is installed.
