# Testing VFX Texture Lab 0.46.5

This checklist focuses on Splatter Circular. Existing 0.46.4 graphs should open without migration because the graph format remains version 18.

## Basic rings

1. Create Splatter Circular with its default Disc pattern.
2. Confirm three visible concentric rings are produced.
3. Change Patterns per Ring from 1 through 64 and Ring Amount from 1 through 10.
4. Confirm the node remains deterministic and the final settled result restores the complete authored counts after dragging.
5. Test on a rectangular project and confirm the guides and result remain physically circular rather than becoming elliptical.

## Arcs, rotation and spirals

1. Reduce Arc Spread below 360 degrees and confirm the closed ring becomes a partial arc.
2. Rotate the arrangement with Ring Rotation.
3. Add Rotation Offset per Ring and confirm successive rings rotate relative to each other.
4. Move Spiral Amount in both positive and negative directions and confirm the radius changes progressively around each ring.
5. Add Angular Random and Radius Random, then change Random Seed to verify deterministic variation.

## Pattern orientation

Use an asymmetric input such as a triangle, tapered stripe or arrow.

1. Compare Face Outward, Face Centre, Tangent and Fixed.
2. Add Pattern Rotation and Rotation Random Range.
3. Confirm the pattern image itself is not accidentally mirrored.
4. Confirm Pattern Rotation Offset per Ring changes successive rings only.

## Custom pattern inputs

1. Connect two to four different grayscale patterns.
2. Test Single with each specific Pattern Input choice.
3. Test Random Inputs and confirm changing the seed changes the assignment.
4. Test Sequential Around Ring and confirm the connected patterns repeat in order.
5. Test One Input per Ring and confirm each ring receives one pattern.
6. Disconnect a middle input and confirm the distribution skips it cleanly.

## Scale and Connect Patterns

1. Independently change Pattern Width and Pattern Height.
2. Test Uniform Scale, Scale Random, Scale by Ring and Scale Around Ring.
3. Enable Connect Patterns with a rectangular or strip-shaped input.
4. Confirm neighbouring patterns expand or contract to meet around the ring.
5. Adjust Connected Width and verify it scales the chord-derived width without changing radial thickness.
6. Test partial arcs and multiple rings with Connect Patterns enabled.

## Value and compositing

1. Test Luminance, Luminance Random, Luminance by Ring and Luminance Around Ring.
2. Raise Random Removal and verify deterministic gaps rather than flickering changes.
3. Connect a grayscale Background input and test Maximum, Add, Subtract and Replace.
4. Test Global Opacity at 0, 0.5 and 1.
5. Disconnect Background and verify Background Value is used.

## Edge quality

1. Compare Antialiased and Pixel Exact using a built-in shape.
2. Compare them using a small connected bitmap or procedural pattern.
3. Test at 256, 512, 2048 and a rectangular resolution.
4. Check thin connected rings at 1:1 for unexpected gaps, halos or directional edge bias.

## 2D Preview gizmo

1. Drag the centre cross and confirm Centre X/Y update.
2. Drag the first-radius handle and confirm First Ring Radius updates.
3. With multiple rings, drag the outer-radius handle and confirm Ring Spacing updates.
4. Drag the rotation handle and confirm Ring Rotation follows the cursor.
5. Confirm the guides match partial arcs and spirals.
6. Undo each complete drag once and verify one drag equals one undo operation.
7. Confirm wheel zoom and middle-button pan still work.

## Performance and caching

1. Test 10 rings with 64 patterns per ring at 2K.
2. Drag Ring Rotation, First Ring Radius and Spiral Amount.
3. Confirm interaction uses a responsive draft and settles to the complete result.
4. Confirm an unchanged node returns from cache.
5. Compare CPU fallback and GPU output where available for the same seed and settings.

## Compatibility

1. Open a graph saved in 0.46.4.
2. Confirm its transform and material results remain unchanged.
3. Save and reopen a graph containing Splatter Circular.
4. Package a graph asset containing the node and confirm its parameters and custom pattern connections survive installation.
