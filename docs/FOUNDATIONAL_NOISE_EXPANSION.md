# Foundational Noise Expansion

VFX Texture Lab 0.47.0.6 continues the quality reconstruction within the 0.47.0 expansion, which adds fourteen artist-facing grayscale generators. They share deterministic hashing, exact spatial tiling, loopable temporal evolution and common GPU infrastructure, but each public node has its own construction and useful parameter set.

## Crystal 1 dual-Voronoi reconstruction in 0.47.0.6

The corrected Crystal 1 follows Material Maker's documented and openly inspectable construction rather than approximating the appearance with custom angular metrics. Two independently randomised periodic Voronoi distance fields are each transformed with `sqrt(1 - A²)`. Their minimum and maximum are compared, and the relative difference is divided by the maximum before a fixed gain is applied. This produces mostly dark polygonal facets with sparse bright ridges and junctions.

The public controls are intentionally narrow: **Scale X**, **Scale Y**, Seed, loopable Evolution and the common finish controls. The previous Disorder and Facet Sharpness parameters were removed because they changed an algorithm that no longer exists. Older scalar Scale values migrate to both axes.

## Moisture Noise reconstruction in 0.47.0.5

The first Moisture Noise implementation chose the strongest overlapping disc at each pixel and mixed that with a generic fractal field. That max/ownership operation exposed hard polygonal regions similar to cracked Voronoi cells. The rebuilt node follows the documented moisture model more directly: discs of varying size and sign add to or subtract from a neutral-grey foundation.

Four periodic sparse-convolution layers serve different jobs:

- broad positive/negative pools establish the damp regions;
- middle-sized deposits create rich spongy breakup;
- fine condensation specks add granular detail;
- a restrained micro layer prevents the fine structure from becoming one uniform grain.

A separate low-frequency value-noise mask controls broad patchiness. The deposits are summed and softly compressed; no nearest-cell ownership, maximum-profile selection or Voronoi-distance operation participates in the result.

The focused controls are **Scale**, **Pool Size**, **Fine Detail**, **Patchiness** and **Disorder**. Moisture is isotropic, so the old Pattern Angle and disorder-anisotropy controls were removed. The old Pattern Size X/Y, Softness and Global Opacity controls were also removed rather than retaining controls that no longer matched the algorithm.

## Anisotropic Noise reconstruction in 0.47.0.4

The first implementation incorrectly scattered soft capsules and mixed in an FBM background. The rebuilt node is a periodic anisotropic value-noise lattice with independent X/Y subdivisions. It produces the intended long strip structure and exposes only controls that belong to that construction.

The goal is not to create a single “noise type” super-node. Each generator should earn its place by producing a different visual language and by exposing controls that fit that language.

## Cloud family

The first 0.47.0 implementation incorrectly built these nodes from gradient FBM plus turbulence/billow folds. Those operations exposed curled ridges and closed contours, making the results overlap visually with the existing Turbulence and Billow nodes. In 0.47.0.1 the family uses smooth periodic **value-noise FBM** and a separate gentle value-noise disorder field. No cloud variant uses an absolute-value turbulence, billow or ridged transform.

### Clouds 1

A fine layered cloud generator. Broad, middle and fine value-noise octave bands are weighted toward dense wispy structure. **Softness** changes the tonal shaping without turning the field into folded ridges.

### Clouds 2

A broad vapour generator. Low-frequency value-noise masses dominate, with restrained middle and fine structure. **Puffiness** expands and softens those masses while preserving a recognisable cloud field.

### Clouds 3

A darker, rougher cloud generator. Body, middle and fine value-noise bands create dense mottling; **Erosion** increases breakup and **Fine Detail** controls the highest-frequency contribution.

All three retain Scale, Octaves, Roughness, Seed, Evolution, Loop Cycles, directional Disorder and finish controls. Their common primitive is value-noise octave summation, but their weighting and shaping are deliberately different.

## BnW Spots 3 continuity and Crystal reconstruction in 0.47.0.3

The large soft deposits in BnW Spots 3 previously used a finite 3×3 sparse-kernel search even though their Gaussian tails were still visible beyond that neighbourhood. Crossing a lattice-cell boundary could therefore add or remove a residual tail abruptly. The grayscale difference was subtle, but Height to Normal differentiated it into a grid of hard lines. The sparse field now searches a 5×5 periodic neighbourhood and smoothly fades each kernel to zero before its compact support ends.

**Crystal 1** now uses two independently offset angular Worley fields. Its metric blends Euclidean, Manhattan and Chebyshev distance, while the nearest feature owns a deterministic planar coordinate. Dark cell boundaries and sparse intersections create angular plates and highlights without falling back to an ordinary radial Voronoi distance map.

**Crystal 2** now builds continuous triangular planes between irregular periodic fold lines. Several restrained directional layers create long cloth/crease forms around mid-grey, suitable for subtle marble and fabric detail. It no longer stamps short blurred segments.

Both crystal definitions expose one Disorder control only. Generic Disorder Scale, Disorder Anisotropy and Disorder Angle controls were removed because they duplicated the node-specific variation and obscured the actual construction.

## BnW Spots family

The original 0.47.0 implementation incorrectly reused generic FBM, turbulence, ridged and billow fields. In 0.47.0.2 the family uses periodic **sparse-convolution spot noise**: each spatial cell contributes a variable set of randomly positioned positive or negative Gaussian kernels. Several independent scales are summed and softly compressed, creating actual dirt-like deposits and specks instead of another interpolated cloudy field.

- **BnW Spots 1** uses strong broad, middle and fine impulse layers for high-contrast multiscale breakup.
- **BnW Spots 2** combines broad mottling with a dominant dense micro-speckle layer.
- **BnW Spots 3** emphasises broad and middle-sized soft spots with a quieter fine layer.

**Roughness** adjusts the middle-scale contribution and **Fine Grain** adjusts the high-frequency impulse layer. Scale, directional Disorder, Seed and loopable Evolution remain shared controls.

## Crystal family

### Crystal 1

A two-Voronoi ratio construction. Independently randomised distance fields are curved, compared through min/max operations and divided by the larger field, producing dark angular facets and sparse bright crystal junctions. **Scale X** and **Scale Y** control the feature density directly.

### Crystal 2

An angular fold/crease construction. Two crossing families of long tapered facets are combined with a low-frequency body. **Fold Direction**, **Crease Strength**, **Facet Sharpness** and **Disorder** make it suitable for folded cloth, mineral shards, crushed surfaces and directional fractures.

## Fractal Sum

Fractal Sum exposes the octave band directly:

- **Minimum Level** chooses the coarsest included frequency.
- **Maximum Level** chooses the finest included frequency.
- **Roughness** controls how quickly amplitude falls across levels.
- **Global Opacity** expands or compresses the result around neutral grey.

This makes it useful as a controllable building block when an artist needs specific frequency ranges rather than a single Scale control.

## Directional and strand generators

### Anisotropic Noise

An anisotropic value-noise lattice that creates long horizontal random-value strips.

- **Scale X** controls the number of value changes along each strip.
- **Scale Y** controls the number and density of strips.
- **Smoothness** controls how much of each X cell is used for the fade between neighbouring values.
- **Interpolation** blends linear and Hermite fades.

The node intentionally has no angle, width, strand density, luminance-random or generic disorder block. Rotate or transform the result with the dedicated transform nodes when a different direction is required.

### Fibres

Orderly tapered strands for fabric threads, fine scratches, brushed fibres and hair-like breakup. Density, Length, Width, Softness and directional variation remain intentionally direct.

### Messy Fibres

A separate construction for rough, tangled fibres. A stronger secondary warp bends the strand field, **Messiness** and **Messiness Scale** control that warp, and **Breakage** removes portions through a fractal breakup field.

### Fur

Dense short tapered hairs plus a broader undercoat. Its defaults favour a consistent growth direction while **Angle Random** and Luminance Random can move it toward rough animal fur, grass-like fibres or noisy short hair.

## Moisture Noise

Moisture Noise places several summed layers of soft positive and negative deposits over a broad dampness mask. Pool Size changes the large deposit footprint, Fine Detail controls condensation specks, Patchiness controls low-frequency wet regions and Disorder organically moves the distribution. The result stays centred around neutral grey and contains no cell-ownership boundaries.

## Looping and determinism

Every generator exposes a deterministic integer **Seed**. For the same parameters, resolution and seed, the result is repeatable.

**Evolution** is a normalised 0–1 loop phase. At Loop Cycles = 1, Evolution 0 and 1 are the same image. Domain movement, feature orientation and strand motion use periodic functions rather than an unbounded time offset, so the generators can be driven directly by Loop Phase.

## GPU execution

All fourteen nodes use `foundational_noise.wgsl`. The public nodes remain separate in the registry and Inspector, while the shader selects the authored construction through a compact variant parameter. Shared low-level routines cover:

- periodic value-noise cloud fractals, sparse Gaussian spot convolution and periodic gradient fractals;
- directional domain disorder;
- cellular features and soft signed pools;
- analytic tapered strands;
- contrast, balance and inversion.

The NumPy evaluators remain the behavioural reference and fallback. The focused regression suite checks deterministic output, visual distinction, parameter response, exact loops, WGSL wiring and CPU/GPU agreement.
