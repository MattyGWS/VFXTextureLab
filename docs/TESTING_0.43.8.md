# VFX Texture Lab 0.43.8 testing checklist

## Tile Sampler luminance

1. Create a fresh Tile Sampler using non-overlapping Square tiles and **Replace** blending.
2. Set **Luminance Random** to `0`. Every tile centre should be exactly white; connected Pattern Inputs should retain their original internal values without any per-tile darkening.
3. Set it to `0.5`. Tile multipliers should range from `0.5` to `1`, with no value below `0.5` and no clipping pile-up at white.
4. Set it to `1`. A sufficiently large grid should contain values close to black and white with an average close to `0.5`.
5. Change Random Seed. The values should change deterministically while preserving the requested range.
6. Repeat with a grass-blade Pattern Input containing an internal gradient. At zero randomness the blade should be unchanged; at full randomness each complete blade should be scaled by its stable tile value.

## Removed parameter

1. Confirm Tile Sampler has no Tile Value or Legacy Compatibility group.
2. Open a pre-release graph that stored `tile_value` or `_legacy_luminance_model`. The stale controls should not appear and the node should use the current Luminance Random model.
3. Save and reopen that graph; the removed keys should not return.

## CPU/GPU parity

1. Test the values at `0`, `0.5` and `1` at 512 and 2048 resolution.
2. Confirm interactive preview, final preview and export agree.
3. Combine luminance with Checker/row/column masks, staggered offsets and custom Pattern Inputs to ensure those systems remain unchanged.
