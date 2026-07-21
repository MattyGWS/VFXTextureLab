# GPU graph fusion

Version 0.30.0 adds the first automatic graph-fusion pass to VFX Texture Lab.

## What fusion changes

A conventional adjustment chain writes a complete texture after every node:

```text
Source → Brightness → Contrast → Gamma → Levels → Clamp
```

Without fusion, that example requires five adjustment dispatches and five intermediate output textures. The fusion planner temporarily represents the same authored chain as one internal operation:

```text
Source → Fused adjustments
```

The visible graph, saved document and individual node parameters are unchanged. Fusion exists only inside an evaluation snapshot.

## Supported nodes

The first safe fusion set targets grayscale masks and height data:

- Invert
- Levels
- Histogram Range
- Histogram Shift
- Histogram Scan
- Brightness
- Contrast
- Exposure
- Gamma
- Posterize
- Clamp

Up to eight consecutive operations are packed into one shader pass. Longer chains are divided into additional bounded passes.

## Safety rules

A chain is fused only when all of the following are true:

- Every node is a supported grayscale adjustment.
- Each node receives and produces the ordinary `Image` output.
- The chain is linear and an intermediate result has only one reachable consumer.
- No parameter socket in the chain is currently driven by an animation signal.
- No node is bypassed.
- Every node inherits precision rather than forcing an explicit precision override.
- WebGPU evaluation is available and selected.

Fusion stops at branches, named-output processors, type conversions, simulations, external package nodes and all unsupported filters.

## Precision policy

Grayscale textures currently use the backend's `r32float` physical path, allowing the fused shader to reproduce ordinary grayscale adjustment chains to numerical float precision.

Default colour and vector graphs commonly use `rgba16float`. Replacing several texture writes with one shader changes where half-float rounding occurs, even when the visible difference is tiny. Those chains deliberately remain unfused in 0.30.0. They will only be added when intermediate rounding can be preserved reliably across supported GPU backends.

## Caching and animation

The temporary fused node includes every original node UID, type and parameter value in its cache signature. A change to any member invalidates the fused result normally.

If the fused chain receives a time-dependent upstream texture, it remains time-dependent. Editing a node that was absorbed into a fused pass is redirected to the temporary pass so downstream interactive-quality behaviour remains active.

## Profiler

The Timeline profiler reports:

```text
fused 6 nodes / 1 passes
```

A fused pass also appears in node traces under a name such as:

```text
Fused: Brightness → Contrast → Gamma → Levels → Clamp
```

## Future expansion

Later fusion work can safely target:

- Exact colour/vector adjustment fusion.
- UV transform composition.
- Channel-selection and display-only operations.
- Generated specialised shaders for larger compatible expressions.
- Persistent fused pipelines keyed by operation layout.

Complex spatial filters, blurs, terrain processing and simulations remain separate dispatches because their texture neighbourhoods or iterative state prevent simple per-pixel fusion.
