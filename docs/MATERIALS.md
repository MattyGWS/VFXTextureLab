# Material composition

VFX Texture Lab 0.40.1 treats **Material** as a lazy structural graph value. A purple Material wire carries references to the complete PBR channel set and material rendering settings; it does not eagerly create nine hidden textures. Mesh displacement amount, midpoint and inversion are deliberately owned by the 3D viewport instead. The 2D Preview, 3D Preview, Material Channels and Texture Set Output request only the channels they need.

## Material channels and defaults

| Channel | Socket type | Default when absent |
|---|---|---|
| Base Colour | Colour | 0.32 grey |
| Emissive | Colour | Black |
| Normal | Vector / Normal | Flat tangent-space normal |
| Height | Greyscale | 0.5 |
| Ambient Occlusion | Greyscale | 1.0 |
| Metallic | Greyscale | 0.0 |
| Roughness | Greyscale | 0.5 |
| Specular Level | Greyscale | 0.5 |
| Opacity | Greyscale | 1.0 |

An absent channel remains distinct from a connected texture containing the same value. Texture Set Output can therefore omit an unused map, while Material Channels can still return a useful constant default when that output is connected.

## Material Blend

**Inputs:** Background Material, Foreground Material and optional Mask.

The effective broad coverage is `Mask × Amount`; without a Mask, coverage is solid white. **Use Foreground Opacity as Coverage** optionally multiplies coverage by the foreground Opacity channel.

### Standard

Standard performs a predictable mask crossfade. Base Colour and Emissive are blended in the graph's linear working values. Scalar channels are linearly blended. Normals are decoded, normalised, blended and encoded again rather than being treated as ordinary RGB.

### Height Aware

Height Aware retains the broad Mask placement but shifts the transition using the relative Background and Foreground Height channels.

- **Height Influence** controls how strongly relative height affects coverage.
- **Transition Softness** controls the width of the interlocking boundary.
- **Height Bias** favours one material without changing either source heightmap.

If neither material has an authored Height channel, the node falls back naturally to Standard coverage.

### Advanced channel handling

- **Normal:** Crossfade or Combine Detail using reoriented normal blending.
- **Height:** Blend, Add Foreground Detail, Maximum or Minimum.
- **Emissive:** Blend or Add.
- **Material Settings Source:** Background or Foreground. Preview settings are inherited rather than mathematically blended.

Missing foreground channels preserve the background unchanged. A channel present only in the foreground blends against that channel's semantic default outside the mask.

## Material Override

Material Override changes selected channels without unpacking and rebuilding the complete material.

- An unconnected override input preserves the incoming channel exactly.
- A connected input replaces or combines only that channel.
- Mask and Amount affect only connected overrides.
- A black Mask returns the incoming channel exactly.
- **Remove Channels** marks selected channels absent and returns their semantic defaults when inspected. Removal wins over a connected override and reports that the input is being ignored.

Normal can Replace or Combine Detail. Height can Replace, Add, Maximum or Minimum. Emissive can Replace or Add.

Incoming material settings are inherited by default. Enable **Override Material Settings** to replace Surface Mode, cutout threshold, two-sided state, emissive intensity and normal convention/strength. Mesh displacement presentation remains one shared 3D viewport decision.

## Material Channels

Material Channels exposes nine correctly typed outputs from one Material input. Each output resolves independently:

- Previewing or connecting Height does not evaluate Base Colour, Roughness or the other unused channels.
- The outputs contain raw authored texture data. Emissive Intensity and normal strength are material rendering settings and are not destructively baked into the textures. Displacement amount, midpoint and inversion are saved separately with the 3D viewport.
- Missing channels return the semantic constants listed above.

Search tags include **Breakout**, **Split** and **Unpack**.

## Material Switch

Material Switch chooses Material A or Material B without crossfading.

- **Selected Material** chooses A or B when Selection is disconnected.
- A scalar **Selection** input chooses B at or above **Threshold**, otherwise A.
- The unselected material branch is not evaluated.
- A missing selected input produces the default empty material and a clear warning; it does not silently fall back to the other input.

Use Material Blend when a visible transition is required. Use Material Switch for variants, timeline-driven material states or expensive alternatives that should remain inactive.

## Preview, portals and export

Every material-producing node can be focused directly:

- The 2D Preview displays its resolved Base Colour.
- The 3D Preview resolves the complete material and inherited settings.
- Texture Set Output accepts Material, Material Blend, Material Override, Material Switch or a material routed through Send/Receive.
- Material Channels can inspect or reuse individual maps after any amount of composition.

## Example workflows

### Height-aware surface layer

```text
Rock Material ───────────────┐
Moss Material ───────────────┼→ Material Blend → Texture Set Output
Low-frequency placement mask ┘     Height Aware
```

### Modify one map without rewiring

```text
Complete Material ─────────────┐
New Roughness ─────────────────┼→ Material Override → Material
Optional paint/noise mask ─────┘
```

### Inspect and reuse one channel

```text
Layered Material → Material Channels → Height → erosion/detail processing
```

### Animated variants

```text
Dry Material ─┐
Wet Material ─┼→ Material Switch → 3D Preview / export
Loop Phase ───┘
```

The included `examples/material_composition.vfxgraph` demonstrates two height-bearing materials, height-aware layering, a masked Roughness override, Material Switch, Material Channels and Texture Set Output.

## Preview reuse and memory behaviour

Material evaluation remains channel-lazy, but 0.40.1 also caches the completed presentation layers used while comparing nodes:

- A completed 2D preview is retained as display-ready RGBA8 pixels. Returning to the same unchanged node can therefore update the panel without resubmitting evaluation or repeating final GPU readback.
- A recently viewed Material can retain its resolved authored channel arrays. If its renderer textures were evicted, this cache still avoids graph traversal and channel recomposition; only the authored maps need to be uploaded again.
- The 3D renderer retains a memory-budgeted set of mipmapped GPU textures for recently viewed materials. A full renderer cache hit changes the active texture views immediately and performs no texture upload.
- Missing material channels are not materialised as full-resolution images. They remain the semantic 1×1 defaults already used by the renderer.
- Cache keys include the producing node/output, branch revision, requested channels, resolution, frame, precision and relevant display settings. A real graph change therefore creates a new result while unrelated previously viewed materials can remain reusable.
- Timeline playback bypasses the focus cache so animated materials and image nodes continue to request their current frames.

The cache is least-recently-used and bounded by the existing render-cache budget. **Render → Clear Render Cache** clears graph results, 2D presentation results, resolved Material bundles and renderer-resident Material texture sets together. Camera, lighting, environment and mesh changes redraw the 3D viewport without invalidating material textures.
