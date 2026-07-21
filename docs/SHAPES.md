# Procedural Shapes

Version 0.21.0 replaces the early standalone Circle and Rectangle generators with three broader grayscale shape nodes. All three have matching NumPy reference and WGSL compute implementations.

## Shape

The Shape node provides:

- Rectangle
- Rounded Rectangle
- Disc
- Ring
- Capsule
- Triangle
- Diamond
- Hexagon
- Cross
- X
- Crescent
- Bell
- Gaussian
- Pyramid
- Cone
- Hemisphere
- Waves
- Linear Gradation

Shared controls cover centre, X/Y size, uniform scale, rotation, tiling, aspect compensation, inversion and edge treatment. Silhouette shapes support Solid, Outline, Linear Bevel and Rounded Bevel output modes. Shape-specific controls only appear when they apply to the selected shape. New silhouette nodes default to **Edge Softness = 0** and **Edge Rasterisation = Antialiased**. This keeps the geometry sharp while storing approximately one pixel of fractional boundary coverage. Choose Pixel Exact for strict binary masks; raise Edge Softness only for a deliberately wider artistic feather.

## Polygon

Polygon produces both regular polygons and stars. Set Inner Radius to 1 for a regular polygon; lower it to pull alternating vertices inward and form stars, bursts and gear-like silhouettes.

Controls include side count, alternating-point offset, roundness, size, rotation, tiling, outline/bevel profiles, radial distortion and radial twist.

## Polygon Burst

Polygon Burst constructs segmented radial wedges for sunbursts, apertures, radial machinery, magic-circle elements and impact masks.

Controls include side count, slice gap, explode, inner radius, alternating slice value, rotation, twist and Solid, Radial Gradient or Angular Gradient fills.

## Performance

All three nodes are built-in GPU nodes. They remain GPU-resident in an otherwise GPU graph and retain NumPy implementations for CPU fallback and reference testing. Polygon supports up to 64 sides; stars evaluate up to 128 alternating vertices.


## Rasterisation and pixel-accurate presentation

The 2D Preview uses nearest-neighbour sampling whenever a texture is enlarged, preserving exact authored texels for low-resolution work and pixel inspection. When a higher-resolution texture is fitted smaller than native size it uses filtered minification to avoid aliasing. **1:1** maps one texel to one screen pixel; **Fit** reports its actual magnification or minification percentage. These presentation rules do not alter graph or export data.

Shape, Polygon, Polygon Burst and Tile Sampler separate geometric antialiasing from artistic softness:

- **Antialiased**: a hard edge stores fractional coverage only across the output pixel footprint.
- **Pixel Exact**: Edge Softness 0 produces a binary 0/1 boundary.
- **Edge Softness > 0**: both modes may create a wider authored feather.

Document Settings chooses the default for newly created geometric nodes. Existing older graphs preserve their original Pixel Exact result. Transform 2D and other resampling nodes keep their own sampling controls and behaviour.
