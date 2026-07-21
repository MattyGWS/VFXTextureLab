# Parameter system

Version 0.20.2 retains the shared organisation and numeric-entry layer with soft slider ranges, reusable angle dials and per-parameter modifier snapping.

## Compact numbers

Floating-point controls still accept the precision declared by each `ParameterSpec`. Only redundant display zeroes are removed:

- `4.0000` displays as `4.0`;
- `12.5000` displays as `12.5`;
- `0.0125` remains `0.0125`.

Keyboard tracking is disabled while direct text entry is in progress. The graph receives the committed number when the edit is completed, instead of repeatedly receiving auto-formatted partial text. Slider dragging remains continuous and uses the interactive preview scheduler.

Native spin-button hit areas and repeat behaviour are preserved. VFX Texture Lab paints visible up/down chevrons over them so dark platform themes cannot leave blank buttons.

## Soft slider ranges and hard numeric limits

`minimum` and `maximum` remain the hard values accepted by a parameter. Optional `slider_minimum` and `slider_maximum` can expose a narrower everyday range without preventing larger values from being typed into the numeric field. When a typed value lies outside the soft range, it remains valid and the slider handle rests at the nearest end.

This is used by wide-domain controls such as Transform offsets/scales, multi-turn rotations, random seeds and Tile Sampler sizes. It keeps common values precise instead of making one slider cover an impractically large range.

## Angle controls

Directional degree parameters may declare `editor="angle"` and `unit="degrees"`. The shared control adds a compact circular dial while retaining the normal slider and exact numeric field. Clicking a direction moves the dial hand there immediately before dragging continues. Directional controls wrap cleanly at their soft bounds, while effects for which multiple turns are meaningful—currently Rotate, Transform 2D and Swirl—declare `angle_wrap=False` and choose the equivalent clicked direction nearest the current accumulated value. Double-clicking the dial restores the parameter default.

Angle rows span the parameter form and carry their own compact label. This prevents a longer neighbouring label from shifting the dial and crushing its slider, while preserving the same dial position across simple and extensive nodes.

The angle editor is applied consistently to Linear Gradient, Tile Sampler Rotation and Displacement Angle, Transform 2D, Rotate, polar angle offsets, Swirl, Directional Warp, Turbulence Flow Direction, and 3D Preview Sun Azimuth. Degree-valued ranges that are not directions—such as Tile Sampler Rotation Random Range, Sun Elevation and Thermal Erosion Talus Angle—retain linear controls and display a degree suffix.

## Modifier snapping

All shared numeric sliders, angle dials and spin-button stepping understand optional `fine_step` and `coarse_step` metadata:

- ordinary dragging remains smooth;
- **Ctrl** snaps to the fine step;
- **Shift** snaps to the coarse step.

For angles the standard fine/coarse values are 1° and 5°. Normalised values commonly use 0.01 and 0.05 or 0.1, while integer population controls use 1 and 5. Individual nodes can override both values when their units require different precision.

## Common settings

An ordinary `seed`, `random_seed` or `randomseed` parameter appears first in **Base Settings**. Image-producing nodes place their resolved data type and output precision in the same section.

The panel then groups applicable parameters into:

- **Parameters** — operation-specific controls;
- **Transform** — scale, rotation, centre, pivot and offset controls;
- **Animation** — Evolution, phase and loop controls;
- **Tiling / Boundaries** — actual Wrap, Tile, Boundary and tiling controls;
- **Quality** — preview/final iterations, passes, samples and solver quality;
- **Output** — output selection, inversion and related presentation controls.

Sections are collapsible and remember their state for each node type during the session.

Tiling controls are not added cosmetically to nodes that do not implement them. A universal tiling mode must eventually be backed by consistent CPU/WGSL sampling semantics; until then, existing real controls are organised consistently rather than presenting a no-op option.

## Custom-node metadata

`ParameterSpec` and public package parameter entries accept optional organisation metadata:

```toml
[[parameters]]
id = "angle"
name = "Angle"
type = "float"
default = 0.0
group = "Transform"
group_order = 30
slider_minimum = -180.0
slider_maximum = 180.0
fine_step = 1.0
coarse_step = 5.0
editor = "angle"
unit = "degrees"
angle_wrap = true # set false when multiple authored turns are meaningful
```

Existing manifests remain valid. Parameters without metadata use their hard numeric bounds, standard slider presentation and steps derived from `step`.

## Testing checklist

1. Select several noise nodes and confirm Seed is the first editable control in Base Settings.
2. Type `12` into a float field previously showing `4.0`; confirm no zero is inserted while typing.
3. Enter `0.0125`, commit it, and confirm all significant digits remain visible.
4. Use the up/down buttons in a node parameter and in Timeline Frame/Start/End/Speed; confirm visible chevrons and normal repeat behaviour.
5. Collapse Quality on an erosion node, switch away and back, and confirm the section remains collapsed.
6. Inspect transform, animated and boundary-aware nodes and confirm their controls appear in the expected sections.
7. Click several positions around an angle dial and confirm the hand moves to the clicked direction immediately.
8. Drag an angle dial normally, with Ctrl and with Shift; confirm smooth movement, 1° snapping and 5° snapping respectively.
9. Compare Linear Gradient and Tile Sampler Rotation; confirm long labels elsewhere in the Tile Sampler group do not push its dial to the right.
10. Type a Tile Sampler Size value above its slider range and confirm it remains accepted while the slider pins to its endpoint.

## X11 selection stability

Parameter pages are built while hidden and swapped into the scroll area atomically. Controls receive a concrete parent when constructed, avoiding transient native top-level widgets when switching rapidly between nodes on X11.
