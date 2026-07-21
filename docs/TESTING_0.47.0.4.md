# Testing VFX Texture Lab 0.47.0.4

## Anisotropic Noise

1. Add **Anisotropic Noise** and inspect the default result at 1:1.
   - It should consist of long horizontal grayscale strips.
   - It should not contain capsules, isolated strands, glowing bars or an FBM background.
2. Set **Scale X** to 2, then 16.
   - Lower values should make values change only a few times across the width.
   - Higher values should shorten the horizontal structures.
3. Set **Scale Y** to 12, then 96.
   - This should directly reduce/increase the number of strips.
4. Move **Smoothness** from 0 to 1.
   - Zero should produce crisp horizontal transitions between X lattice values.
   - One should spread those fades across the full cell.
5. Move **Interpolation** from 0 to 1.
   - Zero uses linear fades.
   - One uses smoother Hermite fades.
6. Change Seed and verify deterministic repeatability.
7. Compare Evolution 0 and 1 with Loop Cycles 1; they should match.
8. View Tile 3×3 and verify the result is seamless.

The Inspector should contain only Scale X, Scale Y, Smoothness, Interpolation, Seed, Evolution and Loop Cycles.
