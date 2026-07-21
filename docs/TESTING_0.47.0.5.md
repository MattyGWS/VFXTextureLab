# Testing VFX Texture Lab 0.47.0.5

## Moisture Noise

1. Create **Moisture Noise** at its defaults and view it at 1:1. The field should contain broad soft damp patches with dense fine black/white condensation specks. It should not contain polygonal cells, cracked Voronoi boundaries or hard straight seams.
2. Pass the result through **Height to Normal**. Inspect the normal map at 1:1 for hidden grid lines or hard cell boundaries.
3. Set **Fine Detail** to 0 and then 1. The broad patches should remain recognisable while the amount of fine condensation clearly changes.
4. Change **Pool Size** from roughly 0.5 to 2.0. Larger values should create broader overlapping pools rather than simply blurring the image.
5. Change **Patchiness** from 0 to 1. The low-frequency damp regions should become substantially more pronounced.
6. Animate **Disorder** or Evolution. The field should change organically without directional curls, and Evolution 0/1 should close exactly when Loop Cycles is 1.
7. Use **Tile 3×3** to confirm seamless edges.
8. Confirm the Inspector contains only Scale, Pool Size, Fine Detail, Patchiness, Disorder, Seed/Evolution and finish controls. The removed Pattern Size, Pattern Angle, Softness and Global Opacity controls should not appear.

## Regression checks

- Open an older 0.47.0 graph containing Moisture Noise. It should load normally; obsolete stored parameters are ignored.
- Compare CPU and GPU output if both paths are available. Small threshold-sensitive sparse-kernel differences are acceptable, but the overall deposit layout and tonal structure should agree.
