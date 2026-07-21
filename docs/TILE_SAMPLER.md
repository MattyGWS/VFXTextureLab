# Tile Sampler

Version 0.20.2 turns the grayscale Tile Sampler into a map-driven placement and distribution node for procedural brickwork, paving, panels, scales, rivets, roof tiles, repeated ornaments, debris masks and height-pattern construction.

## Inputs

The first socket remains **Pattern Input** for compatibility with graphs created in 0.20.0/0.20.1. Three additional custom pattern sockets are available as **Pattern Input 2–4**.

Map inputs are sampled once at each tile centre, keeping modulation stable per tile rather than changing across its pixels:

- **Scale Map** reduces the authored scale according to grayscale value and Scale Map Strength.
- **Rotation Map** adds `map value × Rotation Map Multiplier` degrees.
- **Displacement Map** moves tiles in the chosen Displacement Angle by the authored intensity in grid-cell units.
- **Vector Map** uses encoded R/G around neutral 0.5 for X/Y displacement and optional anisotropic scale variation.
- **Mask Map** retains tiles whose centre sample passes Mask Map Threshold; Invert Mask Map reverses the test.
- **Pattern Distribution Map** selects among connected pattern inputs from black to white.
- **Background Input** supplies the grayscale image beneath the generated tiles. When it is unconnected, Background Value is used.

The node remains grayscale. A future colour sampler can reuse the same placement engine while adding colour, alpha and colour-aware compositing separately.

## Distribution

- **X Amount / Y Amount** control the grid population.
- **Random Seed** drives stable per-cell random values. Changing graph resolution does not reshuffle tile identities.
- **Non-square Compensation** preserves visual proportions when output dimensions or grid-cell dimensions differ.

## Pattern selection

**Pattern Selection** offers four modes:

- **Single** uses the Pattern control directly.
- **Random Inputs** chooses deterministically among connected Pattern Input sockets per tile.
- **Sequential Inputs** cycles through connected pattern inputs in grid order.
- **Distribution Map** maps the Pattern Distribution Map value across the connected input set.

Single mode can use Pattern Input 1–4 or a built-in pattern. Built-ins now include Square, Disc, Brick, Capsule, Bell, Diamond, Hexagon and Triangle.

Random Mirror X/Y independently flips sampled or built-in patterns per tile. **Edge Rasterisation** applies to both analytic built-ins and connected Pattern Inputs:

- **Antialiased** stores a restrained one-pixel fractional-coverage boundary around built-in geometry. Connected Pattern Inputs are bilinearly reconstructed when enlarged and destination-footprint filtered when reduced or rotated into sub-pixel tiles.
- **Pixel Exact** stores binary built-in coverage when Edge Softness is zero and point-samples connected Pattern Input texels with nearest-neighbour sampling.

Edge Softness remains an explicit artistic feather for built-in geometry and is separate from custom-pattern sampling. Footprint filtering is applied only while Tile Sampler transforms a connected pattern; it does not blur or modify the source node. The filter uses a bounded five-tap quincunx footprint instead of full-graph supersampling, and CPU/GPU evaluation share the same sample positions.

## Size

Size X/Y and Scale establish base tile dimensions. Scale Random varies the common scale per tile. Size X/Y accept values up to 8 grid cells and Scale accepts values up to 4, with narrower slider ranges retained for precise everyday adjustment.

- **Scale Map Strength** blends from full authored scale toward the grayscale Scale Map.
- **Vector Scale Strength** uses Vector Map R/G to vary X/Y scale independently around neutral 0.5.

## Position and displacement

Position Random X/Y offsets each tile within its cell. **Offset Mode** is always meaningful and supports:

- **Every Second Row** — shifts alternate rows horizontally, including classic brickwork.
- **Every Second Column** — shifts alternate columns vertically.
- **Continuous Rows** — advances each row cumulatively for diagonal and woven layouts.
- **Continuous Columns** — advances each column cumulatively.

**Offset Amount** is expressed directly as 0–1 of one tile cell. `0` keeps the aligned grid, `0.5` creates a half-tile stagger, and `1` wraps back to a complete tile-cell shift. The layouts remain seamless. Older negative offset values are migrated to their equivalent wrapped positive amount.

Global Offset X/Y is measured in tile cells.

Displacement Map Intensity and Displacement Angle apply directional scalar-map movement. Vector Map Displacement applies two-axis movement from the encoded vector map. Candidate lookup expands to include the maximum possible displacement so moved tiles do not disappear at cell boundaries.

## Rotation

Rotation uses the shared angle dial and is measured in degrees. Clicking the dial now moves the hand immediately to the clicked direction before dragging; normal dragging is smooth, Ctrl snaps to 1° and Shift snaps to 5°.

**Rotation Random Range** is symmetric. A value of 180° selects from -180° through +180° per tile and already covers every possible orientation.

**Rotation Map Multiplier** adds grayscale-driven rotation. Black adds zero degrees and white adds the complete multiplier; negative multipliers reverse the direction.

## Tile selection, value and compositing

**Layout Mask** selects tiles from their stable row/column identity before position jitter, displacement or rotation:

- **All Tiles**
- **Checker**
- **Alternate Rows**
- **Alternate Columns**

**Invert Layout Mask** swaps the retained and removed tiles. Layout selection multiplies with the other masking systems rather than replacing them. For example, a Checker layout can also use Random Removal and an external erosion Mask Map.

- **Random Removal** is the probability that an individual tile is removed. This is the existing Mask Random behaviour with a clearer label and the same saved parameter identity.
- **Mask Map Threshold** and **Invert Mask Map** control centre-sampled map masking. With no Mask Map connected, these controls leave the result unchanged.
- **Luminance Random** controls a per-tile multiplier. At `0`, the multiplier is exactly `1`, leaving built-in shapes fully white and connected Pattern Inputs completely untouched. At `0.5`, stable multipliers are uniformly distributed from `0.5–1`. At `1`, they span the complete `0–1` range.
- **Global Opacity** scales generated tiles.
- **Maximum**, **Add**, **Subtract** and **Replace** determine how overlaps combine.
- **Background Value** is used only when Background Input is unconnected.

There is no separate Tile Value control. The pattern defines its authored luminance, Luminance Random varies that result downward per tile, and Levels or Histogram Range can remap the completed sampler when a narrower artistic range is needed.

Replace is order-sensitive. **Rendering Order** chooses row-major or column-major candidate traversal and **Reverse Rendering Order** flips that order, allowing controlled foreground/background priority between overlaps.

## Performance model

The renderer works backwards from each output pixel. It identifies the local grid cell and tests only a dynamically sized bounded neighbourhood of cells that could overlap that pixel. Tile properties are reconstructed deterministically from cell coordinates and Random Seed. The neighbourhood includes authored size, random scale, vector scale bounds, jitter, offset layout and both displacement systems. Stable layout masks and luminance are reconstructed from the same canonical tile identity, so changing output resolution does not reshuffle the pattern.

Map textures are sampled only when their corresponding control is active; an unconnected or inactive map does not add unnecessary per-candidate texture reads. The complete grid population is never iterated.

Custom Pattern Inputs use one point sample in Pixel Exact mode. Antialiased mode uses ordinary bilinear reconstruction when the pattern is at or above destination resolution, and a bounded five-sample footprint only when the transformed pattern is genuinely minified. This avoids the severe aliasing of thin rotated patterns without paying for unconditional high-order supersampling.

The CPU NumPy implementation is the reference renderer. The normal application path uses the matching WGSL compute shader and keeps the result GPU-resident for downstream nodes.
