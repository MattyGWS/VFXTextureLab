# Flood Fill toolkit

Version 0.22.1 provides a seamless island-aware workflow for masks made with Tile Sampler, Shape, Polygon, Polygon Burst, Threshold and other grayscale nodes.

## Seamless topology

Flood Fill treats the image as a repeating texture. Pixels touching the left and right borders, or the top and bottom borders, are tested as neighbours using the selected 4-way or 8-way connectivity. A region crossing a seam therefore keeps one island ID, one random value, one wrapped centre and the shortest wrapped bounding box. Gradient and Mapper conversions also use wrapped local coordinates so their result continues through the seam rather than restarting at each border.

## Input requirements

Flood Fill expects a binary or strongly contrasted grayscale mask. Every intended island should be separated from its neighbours by at least one full-black pixel. Use Threshold or Levels first when antialiasing, slopes or soft edges accidentally bridge regions.

The core node exposes:

- **Threshold** — decides which pixels belong to an island.
- **Connectivity** — 4-way joins edge-adjacent pixels; 8-way also joins diagonal contact.
- **Ignore Shapes Smaller Than** — removes tiny components and isolated noise by pixel count.
- **Invert Input** — treats dark regions as the islands.

The output is technical vector data. Red/Green encode each island centre, Blue encodes its bounding-box dimensions, and Alpha carries the island’s ordered normalised index. Vector previews are displayed opaque, but Alpha remains available to downstream nodes.

## Conversion nodes

### Flood Fill to Random Grayscale

Produces one deterministic grayscale value per island. Changing the seed changes the complete variation while preserving constant values inside each region.

### Flood Fill to Random Colour

Produces one deterministic RGB colour per island.

### Flood Fill to Grayscale / Colour

Assigns controlled values instead of unconstrained random values. Optional input textures are sampled once at each island centre, then adjustment and random controls are applied per island.

### Flood Fill to Gradient

Builds an independent linear gradient inside every bounding box. It supports a global angle, per-island random angle, optional centre-sampled Angle and Slope maps, slope intensity, flat value and bounding-box-size multiplication.

### Flood Fill to Position

Outputs each island centre in Red and Green. This is intended as technical data for later modulation.

### Flood Fill to BBox Size

Returns X size, Y size, maximum/minimum axis size or bounding-box area relative to the full document.

### Flood Fill to Index

Orders regions from top-left and maps that index across 0–1. The first island is black and the final island is white when at least two regions exist.

## Flood Fill Mapper Grayscale

Maps a custom grayscale pattern independently into every island bounding box. Controls include:

- Fit scale and per-island scale randomisation.
- Optional centre-sampled Scale Map.
- Rotation, random rotation and optional Rotation Map.
- Pattern-space offsets.
- Optional H/V tiling.
- Luminance range, offset and background value.

## Runtime design

Connected-component topology is calculated once on the CPU with a run-length union algorithm. The reusable metadata image is then uploaded to the GPU, and every conversion and Mapper node has matching NumPy and WGSL implementations. This avoids repeating island detection for each derived effect while keeping downstream graph work GPU-resident.
