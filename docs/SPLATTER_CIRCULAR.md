# Splatter Circular

Version 0.46.5 adds a dedicated grayscale radial-placement generator. It is intentionally separate from Tile Sampler: Tile Sampler owns Cartesian grids, while Splatter Circular owns concentric rings, arcs and spirals.

## Inputs and output

Splatter Circular accepts four optional grayscale pattern inputs plus an optional grayscale Background input. Its output is grayscale.

Without a connected pattern, the node can render built-in Square, Disc, Brick, Capsule, Bell, Diamond, Hexagon and Triangle shapes. Connected inputs remain ordinary graph images, so procedural patterns, imported bitmaps and graph assets can all become radial instances.

The first release is deliberately grayscale. A future colour variant can be designed alongside Tile Sampler Colour without complicating the grayscale node’s value and blend semantics.

## Ring construction

- **Patterns per Ring** controls the authored number of instances, from 1 to 64.
- **Pattern Amount Random** deterministically reduces that count independently for each ring.
- **Minimum Pattern Amount** prevents random reduction from collapsing a ring below an authored lower limit.
- **Ring Amount** creates 1–10 rings.
- **First Ring Radius** places the innermost ring relative to the image height.
- **Ring Spacing** adds or subtracts radius for each later ring. Negative spacing is valid.
- **Radius Random** moves individual instances inward or outward relative to the local ring spacing.
- **Arc Spread** changes a closed 360-degree ring into a partial arc.
- **Ring Rotation** rotates the entire radial arrangement.
- **Rotation Offset per Ring** rotates each successive ring relative to the previous one.
- **Spiral Amount** progressively changes radius around a ring, opening it into an inward or outward spiral.
- **Angular Random** jitters placement within each authored angular cell while retaining deterministic seeding.

Coordinates are evaluated in physical pixel space rather than square UV space, so circular arrangements remain circular on rectangular documents.

## Pattern selection

**Single** uses the Pattern dropdown. It can select a built-in shape or one specific connected pattern input.

When multiple custom inputs are connected:

- **Random Inputs** chooses a deterministic input independently per instance.
- **Sequential Around Ring** cycles through connected inputs around every ring.
- **One Input per Ring** assigns one connected input to each successive ring.

Disconnected input slots are skipped by the multi-input distribution modes.

## Orientation and rotation

- **Face Outward** points the pattern’s forward direction away from the centre.
- **Face Centre** points it toward the centre.
- **Tangent** aligns it along the ring.
- **Fixed** leaves every instance at the authored Pattern Rotation.

Pattern Rotation, Rotation Random Range and Pattern Rotation Offset per Ring are applied in addition to the selected orientation.

## Scale and connected rings

Pattern Width, Pattern Height and Uniform Scale establish the base size. Scale Random, Scale by Ring and Scale Around Ring add deterministic variation and progression.

**Connect Patterns** replaces the ordinary authored width with a width derived from the chord between neighbouring radial positions. **Connected Width** scales that result. This is useful for continuous strips, segmented rings, radial chains, petals and repeated runes that should meet rather than float apart.

Connect Patterns changes width only; Pattern Height remains available for controlling the radial thickness of the ring.

## Value, removal and compositing

- **Random Removal** deterministically discards instances.
- **Luminance** sets the base pattern value.
- **Luminance Random** lowers individual values by a deterministic amount.
- **Luminance by Ring** progresses value from the first ring to the last.
- **Luminance Around Ring** progresses value through the pattern order around each ring.
- **Global Opacity** scales the final contribution.

The compositor supports Maximum, Add, Subtract and Replace. A connected Background input is used when present; otherwise Background Value initializes the output.

## Rasterisation and performance

Built-in shapes use resolution-aware edge coverage in Antialiased mode. Pixel Exact retains hard procedural edges. Custom pattern inputs use filtered footprint sampling in Antialiased mode and exact source sampling in Pixel Exact mode.

The GPU path uses a bounded angular-neighbour search rather than testing all possible instances for every pixel. During direct parameter or gizmo dragging, especially large authored arrays are temporarily capped; the full authored ring and instance counts return when interaction settles.

## 2D Preview gizmo

When Splatter Circular is selected, the 2D Preview displays:

- a centre cross for Centre X/Y;
- a first-ring radius handle;
- an outer-radius handle that edits Ring Spacing while respecting Ring Amount;
- a rotation handle for Ring Rotation;
- ring, arc or spiral guides matching the current placement model.

Each drag becomes one undo operation. Inspector parameters remain available for exact values, animation and reset.
