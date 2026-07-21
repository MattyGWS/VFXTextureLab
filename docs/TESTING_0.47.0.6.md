# Testing VFX Texture Lab 0.47.0.6

## Crystal 1

1. Create **Crystal 1** at its defaults. The output should be mostly dark, with angular planar facets and sparse soft-bright junctions similar to the Material Maker reference—not white-centred Voronoi cells.
2. Change **Scale X** while keeping Scale Y fixed. Only the horizontal feature density should change.
3. Change **Scale Y** independently and confirm vertically stretched/compressed crystal structures.
4. Change Seed and confirm a deterministic new arrangement.
5. Set Evolution to 0 and 1 and confirm exact loop closure.
6. Convert Crystal 1 through Height to Normal and inspect at 1:1 for seams or cell-grid discontinuities.
7. Open a graph saved with the older scalar Crystal Scale and confirm the value migrates to both Scale X and Scale Y.
