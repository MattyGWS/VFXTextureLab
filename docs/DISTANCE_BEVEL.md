# Distance and Bevel

Version 0.23.0 adds a shared seamless distance-field foundation and two artist-facing grayscale filters: **Distance** and **Bevel**.

## Distance

Distance thresholds the input into a mask, measures Euclidean pixel distance to the nearest edge, and remaps that measurement into a grayscale texture.

### Modes

- **Inside** — black outside the mask, rising from black at the edge toward white inside.
- **Outside** — black inside the mask, rising away from the edge outside.
- **Signed** — the edge is middle grey; exterior values fall below 0.5 and interior values rise above 0.5.
- **Absolute** — distance increases on both sides of the edge.

### Controls

- **Maximum Distance** sets the pixel distance that maps to the end of the output range.
- **Edge Offset** shifts the detected edge. Positive values expand the effective interior; negative values contract it.
- **Curve** changes the profile response.
- **Profile Smoothness** blends the linear response toward smoothstep interpolation.
- **Input Threshold** and **Invert Input** define the binary source mask.
- **Boundary** switches between seamless toroidal wrapping and clamped image borders.
- **Invert Output** reverses the final grayscale result.

## Bevel

Bevel converts a flat mask into a controllable height profile derived from the same distance field.

### Directions

- **Inner** — slopes inward from the original edge to a flat interior plateau.
- **Outer** — preserves the interior height and extends a sloped border outside the mask.
- **Centered** — places the transition equally across the original edge.
- **Edge Ridge** — creates a ridge centred directly on the mask boundary.

### Profiles

- Linear
- Smooth
- Rounded
- Concave
- Convex

The **Height** and **Background** controls may exceed 0–1 when **Clamp Output** is disabled, allowing HDR height workflows between graph nodes.

## Seamless behaviour

Both nodes use the shortest wrapped distance when **Boundary** is set to **Seamless / Wrap**. A shape crossing the left/right or top/bottom edge is therefore treated as one continuous shape without a cut or bevel discontinuity at the texture seam.

## CPU and GPU execution

The CPU reference path and the WebGPU path use the same jump-flood step sequence and profile calculations. Up to 2048 pixels per axis, nearest foreground and background seeds remain entirely on the GPU. Larger images use the CPU reference analysis before returning the completed texture to the GPU, avoiding multi-gigabyte temporary seed textures during 4K and 8K work.
