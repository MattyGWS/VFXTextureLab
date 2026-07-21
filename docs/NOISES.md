# Noise Foundation

VFX Texture Lab treats noises as distinct tools rather than one oversized “noise type” node. Each node has a clear visual character while sharing deterministic periodic NumPy/WGSL foundations.

## 0.47.0 foundational expansion

The built-in library now also includes:

- **Clouds 1/2/3** — soft layered, inflated billow and rough turbulent cloud constructions.
- **BnW Spots 1/2/3** — three distinct multiscale black-and-white breakup families.
- **Crystal 1/2** — peaked Voronoi facets and crossing angular crease/fold patterns.
- **Fractal Sum** — direct minimum/maximum octave-level control.
- **Anisotropic Noise** — smooth directional strip structure.
- **Fibres**, **Messy Fibres** and **Fur** — orderly, warped/broken and short tapered strand fields.
- **Moisture Noise** — overlapping positive/negative pools around neutral grey.

See [Foundational Noise Expansion](FOUNDATIONAL_NOISE_EXPANSION.md) for the full construction and parameter guide.

## 0.11.1 quality pass

- **Billow Noise** now builds soft inflated masses from two decorrelated gradient fields.
- **Ridged Noise** uses octave feedback, so it forms branching crests rather than an inverted Billow.
- **Turbulence Noise** uses multi-octave domain warping and directional flow.
- **Gaussian Noise** is smoothly interpolated by default; set Smoothness to 0 for the original hard-cell look.


## Core nodes

- **Value Noise** — smooth interpolation between random lattice values. Useful when soft cell-like structure is wanted deliberately.
- **Gradient / Perlin Noise** — organic periodic gradient noise with far less visible square structure.
- **Fractal Noise** — layered gradient FBM with Octaves, Lacunarity, Gain/Roughness, Disorder and loopable Evolution.
- **Simplex-style Noise** — isotropic 4D gradient noise sampled on a 2D torus for seamless spatial tiling and circular loop motion.
- **Voronoi Noise** — one feature point per repeating cell, with Distance, Edge, Cell Value and F2-F1 outputs.
- **Worley Noise** — one to three moving feature points per cell, with F1, F2 and F2-F1 outputs.
- **White Noise** — uniform random values with controllable cell resolution.
- **Gaussian Noise** — normally distributed values with Mean and Deviation controls.

## Fractal variations

- **Ridged Noise** — sharp mountain-like ridges.
- **Billow Noise** — rounded cloud and smoke masses.
- **Turbulence Noise** — folded, energetic detail for distortion, smoke and flame masks.
- **Voronoi Fractal** — layered cellular distance or edge fields.

## Looping

As of 0.17.6, **Evolution** is a normalised 0–1 phase. Most noise nodes also expose **Loop Cycles**. With Loop Cycles set to 1, Evolution 0 and Evolution 1 are the same image. Drive Evolution from `Time.Loop Phase` or `Loop Phase.Phase` for a seamless animation cycle.

```text
Loop Phase.Phase → Fractal Noise.Evolution
```

White Noise uses **Evolution Steps** to crossfade deterministic random layers while still returning exactly to the first layer at the end of the loop. Gaussian Noise uses the same compact coherent temporal lattice as the other smooth noises.

Fractal families keep their spatial octaves independent but move every octave through the same temporal phase. This prevents fine detail from racing many times faster than the broad forms.

## Tiling and scale

Lattice and cellular nodes use whole repeating cells. Integer Scale values provide the clearest exact tiling. The 2D preview’s **Tile 3×3** mode remains the quickest seam check.

## Voronoi outputs

- **Distance** — distance to the nearest feature point.
- **Edge** — a controllable white cell-boundary mask.
- **Cell Value** — a stable random value assigned to each cell.
- **F2 - F1** — distance between the nearest and second-nearest features; useful for cellular borders and cracks.

The Preview Output control chooses which result appears when the Voronoi node itself is active. All four outputs remain available simultaneously as graph sockets.

## Shared WGSL functions

Built-in and bundled package shaders can use:

```wgsl
// @include <noise/common.wgsl>
```

The application expands includes before WGSL compilation. The common library supplies hashes, gradient/value noise, cellular searches, loop helpers, domain warp and contrast/balance functions.
