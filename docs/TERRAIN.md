# Terrain and erosion authoring

VFX Texture Lab 0.39.1 expands terrain shaping as well as erosion. Terrace is now a full shelf-building node rather than a uniform height quantiser, with irregular vertical spacing, local boundary breakup and graph-driven masking.

# Terrace

Terrace is intended for broad pre-erosion shaping: sedimentary shelves, mesa-like layers, stepped volcanic forms and broken plateaus. It now separates four different artistic decisions that were previously collapsed into Terrace Count and Smoothness.

## Inputs

- **Height** — source greyscale terrain.
- **Mask** — black preserves the exact source height; white applies the Terrace result. Unconnected defaults to white.
- **Variation** — locally offsets terrace boundaries. Mid-grey is neutral, darker values pull a boundary downward and lighter values push it upward. Unconnected defaults to mid-grey.

## Terrace Layout

- **Terrace Count** — number of elevation shelves.
- **Terrace Offset** — moves the entire pattern vertically in terrace-step units.
- **Step Spacing Variation** — changes the vertical distance between successive shelves instead of spacing every shelf uniformly.
- **Elevation Distribution** — negative values concentrate more shelves in lowlands; positive values concentrate them toward peaks.
- **Layout Seed** — deterministic arrangement for Step Spacing Variation and the built-in breakup field.

Two Terrace nodes with the same source but different seeds now produce genuinely different elevation layouts. Blending them at low-to-medium opacity is a useful way to create compound shelves without losing a readable macroform.

## Terrace Profile

- **Edge Smoothness** — widens the transition into the next shelf.
- **Plateau Slope** — keeps a gentle grade across each shelf. Zero creates flat plateaus; modest values avoid a hard threshold appearance while retaining visible step faces.
- **Terrace Strength** — blends the complete terrace result against the source before masking.

## Shape Breakup

- **Boundary Breakup** — applies a broad seamless procedural offset so every contour does not form a perfect repeated ring.
- **Breakup Scale** — size of that breakup pattern. Integer values remain tileable.
- **Variation Input Influence** — amount of local offset contributed by the Variation input.

The built-in breakup is deliberately broad and restrained. For deliberate geological direction, connect a low-frequency noise, warped gradient, erosion mask or hand-painted Canvas image to **Variation**. Fine noisy inputs usually produce chipped contour edges rather than believable landforms.

## Mask workflow

The Mask input is an effect mask, not another height quantisation source:

```text
source terrain ───────────────→ Terrace Height
regional noise / slope mask ─→ Terrace Mask
low-frequency warp/noise ────→ Terrace Variation
```

This allows terraces to appear only on selected sides of a mountain, on resistant strata, above a chosen elevation or inside hand-authored regions. **Invert Mask** swaps black and white.

## Recommended pre-erosion workflow

```text
broad source terrain
→ Terrace with moderate spacing variation
→ optional second Terrace blended at low opacity
→ Fluvial Erosion
→ light Thermal Erosion
```

Terracing before erosion gives rivers shelves to cut through and gives Thermal Erosion meaningful escarpments to relax. Terracing after erosion is better reserved for stylised results because it can flatten established drainage.

# Erosion

VFX Texture Lab 0.39.0 rebuilds the erosion workflow around two complementary geological processes:

- **Fluvial Erosion** organises rainfall into connected catchments, cuts channels, widens valleys and transports sediment.
- **Thermal Erosion** relaxes slopes above a material's repose angle and forms scree, talus and softened cliff bases.

The most natural general-purpose terrain workflow is usually:

```text
broad source landforms
→ Fluvial Erosion
→ light Thermal Erosion
→ optional fine detail blended afterwards
```

Fluvial erosion creates drainage structure. Thermal erosion then stabilises the unnaturally sharp banks and ridge faces that a stream-power model alone tends to leave behind.

## Why the controls changed

A comparison of Gaea, World Machine and World Creator shows a useful common pattern. Their strongest erosion tools expose geological or visual intent first—duration, scale, downcutting, rock strength, sediment behaviour, repose angle and shape preservation—while iteration counts and numerical limits are secondary quality controls.

0.39.0 follows that pattern. Parameters are grouped as:

1. **Character** — the terrain result the artist wants.
2. **Water & Drainage** or **Material** — the physical character of the solve.
3. **Sediment & Banks** — secondary landforms and stabilisation.
4. **Quality** — preview/export workloads.
5. **Advanced** — solver response and safety limits.
6. **Outputs** — masks and display gains.

Existing project parameter names remain compatible, even where the visible label is now clearer. For example, the stored `channel_depth` value is presented as **Downcutting**, and `terrain_uplift` is presented as **Shape Protection**.

# Fluvial Erosion

Fluvial Erosion is a drainage-first stream-power model:

```text
prepare a hidden routing surface
→ find coherent D8 drainage directions
→ accumulate upstream rainfall
→ identify the river hierarchy
→ incise channels and erode banks
→ transport and deposit sediment
→ stabilise active valley walls
→ gently preserve source macroforms
```

It is not a frame-by-frame liquid simulation. This makes it deterministic, tileable, practical at texture resolutions and easier to direct artistically.

## Inputs

- **Height** — required greyscale terrain.
- **Rainfall Mask** — white receives rainfall; black remains dry. Unconnected defaults to white.
- **Hardness** — white protects terrain spatially. Use it for resistant strata, cap rock or masked art direction.

## Character

- **Erosion Duration** — overall geological time. This is the best first control to raise or lower.
- **Erosion Scale** — moves from fine gullies toward broad valleys. The sampling radius scales with document resolution so the authored character survives 512 px, 2K and export renders.
- **Downcutting** — depth of incision in established channels.
- **Channel Widening** — changes narrow river cuts into smoother V- and U-shaped valleys and floodplains.
- **Tributary Density** — selects how much of the drainage hierarchy becomes visible.
- **Shape Protection** — gently retains the source macroform during long erosion solves.

## Water & Drainage

- **Rainfall** — runoff source strength.
- **Rain Variation** — broad, periodic rainfall variation. It never injects independent per-pixel noise.
- **Flow Retention** — how much upstream water remains after each drainage step. Higher values produce longer connected river systems.
- **Drainage Smoothing** — smooths only the hidden routing surface, not the visible source height.
- **Depression Handling** — lets shallow pits find a weak spill route. Set it to zero to preserve closed basins exactly.

## Sediment & Banks

- **Channel Softness** — width of the transition into active channels.
- **Headwater Detail** — restores small high-slope tributaries without covering the whole terrain in scratches.
- **Bank Erosion** — lateral erosion along valley walls.
- **Deposition** — amount of alluvial material placed where flow loses energy.
- **Sediment Transport** — low values deposit near the source; high values carry material farther toward flatter terrain.
- **Sediment Spread** — broadens valley-floor and floodplain deposits.
- **Bank Stabilisation** — applies restrained talus-like relaxation only around active channels and steep banks.

## Material

- **Rock Resistance** — uniform bedrock resistance. It combines with the Hardness input.
- **Terrain Height Scale** — relationship between vertical height and horizontal texel spacing when slope is measured.

## Outputs

- **Eroded Height** — modified terrain.
- **Erosion** — material removed.
- **Deposition** — material deposited.
- **Flow Accumulation** — upstream runoff concentration.
- **Channel Mask** — river and tributary hierarchy.
- **Water** — final runoff proxy.
- **Sediment** — remaining transported-material proxy.
- **Wetness** — persistent drainage field.
- **Flow Direction** — encoded downhill vector field.

## Numerical robustness

Wrapped and closed drainage networks can contain loops. With very high Flow Retention, repeatedly accumulating a loop can eventually exceed floating-point range even though the artistic flow response was already fully saturated. 0.39.0 caps accumulation far above the meaningful response range and sanitises intermediate and final fields. This fixes intermittent black 2D previews at **Channel Widening = 1.0** without clipping a visible terrain result.

# Thermal Erosion

Thermal erosion models weathered material moving whenever a slope exceeds its stable repose angle. It now distributes outgoing material among every unstable downslope neighbour in proportion to slope excess. The previous steepest-neighbour-only method could produce directional streaks and unnaturally uniform bands.

## Inputs and outputs

Inputs:

- **Height** — source heightfield.
- **Hardness** — white protects terrain from weathering and movement.

Outputs:

- **Eroded Height** — relaxed terrain.
- **Erosion** — material removed from unstable slopes.
- **Deposition** — accumulated talus and scree.

## Character

- **Repose Angle** — stable angle of loose material. The default 34° is a useful natural starting point.
- **Weathering** — how readily unstable rock becomes movable material.
- **Talus Mobility** — how freely material spreads among available downslope directions.
- **Shape Protection** — retains broad landforms while local cliffs and slopes relax.
- **Terrain Height Scale** — vertical-to-horizontal interpretation used by the slope threshold.

## Material

- **Rock Resistance** — uniform resistance, combined with the Hardness input.
- **Fracture Variation** — varies weathering across the terrain to break up uniform talus bands.
- **Fracture Scale** — broadness of that variation.
- **Fracture Seed** — deterministic variation choice.

Fracture variation is anchored to the source terrain rather than absolute texture coordinates. A shifted seamless terrain therefore carries its weathering pattern with it.

# Quality and performance

**Automatic** uses Preview iterations in live 2D/3D views and Final iterations for export. While a numeric control is dragged, both erosion nodes use a bounded draft solve, then resolve the exact selected quality on release.

Recommended starting budgets:

```text
Fluvial Preview Erosion:   8–16
Fluvial Preview Drainage:  40–80
Fluvial Final Erosion:     24–64
Fluvial Final Drainage:    80–180

Thermal Preview:           16–40
Thermal Final:              80–240
```

Both iterative solvers remain GPU-resident and cancellable. CPU implementations remain as deterministic reference paths and for machines without a suitable WebGPU adapter.

# Boundary modes

- **Seamless / Wrap** — default for tileable terrain; drainage and material cross opposite edges.
- **Closed** — sealed borders.
- **Drain** — outside is zero height, allowing water or loose material to leave through the edge.

Inspect seamless erosion with both the 2D Tile 3×3 view and the Terrain Plane's 3×3 tiling mode.

# Building natural terrain

Start with broad, readable elevation changes. Let erosion create the drainage detail:

```text
Ridged or Fractal Noise at low scale
→ light Gaussian Blur
→ Levels / Height Combine
→ Fluvial Erosion
→ light Thermal Erosion
→ fine noise blended at low opacity
```

Common causes of artificial results:

- Feeding erosion mostly pixel-scale noise.
- Raising Downcutting before a connected drainage network has formed.
- Using maximum Tributary Density and Headwater Detail together.
- Applying heavy Thermal Erosion before Fluvial Erosion, which can remove the slopes needed to organise drainage.
- Judging height only as a greyscale image instead of also inspecting displaced lighting in 3D.

# Which erosion nodes belong in the application?

For general procedural terrain, Fluvial plus Thermal covers the two highest-value processes and supports a strong combined workflow. The next genuinely distinct process should be **Debris Flow / Mass Wasting**: steep, low-drainage failures that create scars, lobes and depositional fans. It should be a separate future node rather than another hidden slider inside Fluvial Erosion.

More specialised processes—coastal, wind, glacial and volcanic erosion—are useful later, but each needs different assumptions and outputs. They should not be folded into one oversized “universal erosion” node.

# Focused tests

```bash
.venv/bin/python tests/terrain_foundation_test.py
.venv/bin/python tests/hydraulic_erosion_test.py
.venv/bin/python tests/erosion_overhaul_test.py
.venv/bin/python tests/erosion_interactivity_test.py
```
