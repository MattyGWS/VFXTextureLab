# VFX Texture Lab 0.43.7 Testing

## Offset controls

1. Create a new Tile Sampler.
2. Confirm Offset Mode contains no **None** entry and defaults to **Every Second Row**.
3. Confirm **Offset Amount** runs from 0 to 1.
4. With a square or brick pattern, set Offset Amount to `0.5`; alternate rows should form a classic half-tile brick stagger.
5. Try Every Second Column, Continuous Rows and Continuous Columns.
6. Confirm `0` is the ordinary aligned grid and the layouts remain seamless in Tile 3×3 view.

## Layout masks

1. Set Layout Mask to **Checker** and confirm alternating cells remain.
2. Enable Invert Layout Mask and confirm the opposite cells remain.
3. Test **Alternate Rows** and **Alternate Columns**.
4. Add Random Removal and confirm it removes a subset of the already selected layout.
5. Connect a Mask Map and confirm the layout mask, random removal and external mask combine rather than replacing one another.

## Luminance Random

1. Use non-overlapping square tiles and set Luminance Random to `0`; all tiles should be white.
2. Set it to `0.5`; values should range from roughly 0.5 to 1.0.
3. Set it to `1`; tiles should span the full black-to-white range with no obvious white clipping bias.
4. Change Random Seed and confirm the values change deterministically.
5. Change resolution and confirm tile identities and relative values do not reshuffle.

## Legacy compatibility

1. Open a graph authored in 0.43.6 or earlier containing Tile Sampler.
2. Confirm its old Tile Value/Luminance Random appearance is unchanged.
3. If that node used Tile Value, confirm **Tile Value (Legacy)** remains available in its compatibility group.
4. Confirm an old Offset Mode of None opens as Every Second Row with Offset Amount 0, preserving the aligned result.
5. Confirm old negative offset amounts migrate to an equivalent wrapped 0–1 value.

## CPU/GPU and seam checks

1. Use a staggered layout with Luminance Random or Checker mask enabled.
2. Inspect the left/right and top/bottom edges in Tile 3×3 view.
3. Confirm wrapped tiles keep the same value and mask identity across the seam.
4. Repeat at 128, 512 and 2048 resolution.
5. Switch backend where available and confirm CPU and GPU results match.
