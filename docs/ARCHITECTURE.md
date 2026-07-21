# Architecture

VFX Texture Lab separates editor concerns from texture execution so the UI can remain productive in Python while image processing scales through WebGPU.

```text
PySide6 / Python
├── graph model and interaction
├── undo/redo and grouping
├── project, autosave, and reusable-group serialization
├── package discovery and application settings
├── export coordination and file encoding
└── evaluation planning and cache ownership

Texture backends
├── WGSL/WebGPU production path
├── NumPy/Pillow built-in CPU reference path
└── explicit CPU decode/upload boundaries such as Image Input
```

## Graph model

The scene owns nodes, connections, expanded/collapsed groups, membership, selection, and view-relative behaviour. Graph serialization stores stable node type IDs and parameter values, never Python class names or GPU handles.

The evaluator snapshots graph state and builds an iterative topological plan for the requested output. Only upstream nodes required by that output execute. Deep graphs therefore do not depend on Python recursion depth.

## Evaluation and caching

A render context includes width, height, working precision, document colour-space metadata, and backend preference. Cache signatures incorporate:

- stable node ID and type;
- parameters and external-source revisions;
- upstream signatures;
- dimensions and precision;
- backend and package shader revision.

Changing a node invalidates that node and downstream dependants. Moving graph items does not invalidate texture data. CPU and GPU caches are byte-budgeted LRU stores.

Interactive previews use a leading-edge, latest-value-wins scheduler and evaluate away from the UI thread. The first edit dispatches immediately, sustained changes are cadence-limited, and edits made during an in-flight evaluation collapse into one newest-state request without overlapping or starving the renderer. Exports take a synchronous snapshot at the requested resolution.

## GPU resources and formats

Logical data formats describe intent:

- `r16f` — scalar mask, distance, or height;
- `rg16f` — two-component vector or flow data;
- `rgba16f` — ordinary colour/four-component data;
- `rgba32f` — explicitly high-precision colour/four-component data.

Physical storage uses `r32float`, `rg32float`, `rgba16float`, or `rgba32float` according to the resolved semantic type and per-node precision. Compatible nodes preserve scalar/two-component branches rather than expanding every intermediate to RGBA.

GPU resources stay resident between WGSL nodes. CPU/GPU transfer occurs only at a real backend boundary or final preview/export readback.

## Built-in nodes

Built-in procedural nodes have:

- a Python `NodeDefinition`;
- a NumPy/Pillow evaluator used for forced CPU mode and correctness tests;
- a shipped WGSL kernel used by Auto/GPU mode.

Built-in parameter packing can use specialised backend code where necessary. Image Input is intentionally CPU-side for file decoding, followed by cached GPU upload.

## Public custom-node packages

Version 0.6 introduced public ABI version 1; version 0.8 adds backward-compatible API version 2 motion metadata. A package contains a declarative manifest and a WGSL compute shader:

```text
my_node/
├── node.toml
├── kernel.wgsl
├── icon.svg        # optional
└── README.md       # optional
```

The package manager scans three classes of source:

1. bundled public packages shipped with the application;
2. a managed per-user installation directory;
3. any application-wide library folders selected by the user.

All three pass through the same parser, validation, shader preflight, registry, and library UI. Bundled packages therefore prove the public API rather than using a private shortcut.

The manifest produces a normal `NodeDefinition` with a `GpuNodeSpec` containing shader location, input defaults, parameter bindings, output format policy, source metadata, and a content revision hash.

### Public WGSL ABI v1

Every shader receives one 64-byte uniform block:

```wgsl
struct Params {
    p0: vec4<f32>,
    p1: vec4<f32>,
    p2: vec4<f32>,
    p3: vec4<f32>,
};
```

- `p0.x` and `p0.y` contain output width and height.
- `p1` through `p3` contain twelve f32 parameter slots in manifest declaration order.
- Float, integer, boolean, and enum parameters consume one slot.
- Colour parameters consume four consecutive RGBA slots.
- Image inputs begin at binding 1 in manifest order.
- The storage output follows the final input binding.
- Workgroups are dispatched at 8×8.

Before module creation, the backend substitutes the shader's storage format token with the selected physical texture format and caches pipelines by type, physical format, and package revision.

Public packages cannot execute arbitrary Python. In API versions 1 and 2 they are GPU-only and report a clear error in forced CPU mode.

## Discovery, validation, and hot reload

The package manager validates manifest syntax, API compatibility, permanent reverse-domain IDs, unique parameters/inputs, supported formats, local package paths, and parameter-slot limits. WebGPU preflights shader variants when available.

`QFileSystemWatcher` observes manifests, shaders, icons, package directories, and library roots. Changes are coalesced before rescanning. Atomic editor saves are handled by rebuilding watches after notifications.

Shader validation is transactional: newly compiled pipelines replace old ones only after all supported physical variants succeed. A failed hot reload keeps the previous definition/pipelines active and records a diagnostic with source location where available.

## Registry and missing-node recovery

The registry combines permanent built-in definitions with dynamically discovered package definitions. Reloading packages rebinds live scene nodes while preserving compatible parameters and connections.

When a project references an unavailable package, the graph creates a placeholder definition from the interface snapshot embedded in the project. Unknown nodes are never silently deleted. Installing/restoring the package and rescanning replaces the placeholder with the real definition.

## Package security boundary

The public package surface is intentionally constrained:

- TOML metadata;
- WGSL compute code;
- static icon/documentation files.

Archive installation rejects absolute paths, traversal outside the destination, and symbolic-link entries. Shader code sees only bound uniform/texture resources and cannot directly access the user's filesystem, network, subprocesses, or Python runtime.

## Project and reusable-group formats

`.vfxgraph` and `.vfxnode` remain human-readable JSON. External package instances include enough definition metadata to construct a placeholder when the package is absent. No compiled shader, cache entry, device object, or absolute managed-library state is serialized into graph assets.

## Error containment

Manifest errors, duplicate IDs, unsupported API versions, compilation failures, missing images, GPU failures, and unavailable custom packages are isolated and reported. Healthy packages and unrelated graph branches remain usable. Runtime node failures add a visible graph badge and detailed diagnostics rather than terminating the application.


## Motion evaluation

Version 0.8 extends `RenderContext` with frame, seconds, delta time, duration, document phase and FPS. Signal nodes produce tiny typed scalar/vector resources on the CPU, while texture processing remains WGSL/WebGPU. Numeric parameters can expose scalar sockets. The evaluator marks branches dynamic from direct time use or dynamic upstream dependencies and adds timing only to those cache signatures, preserving static GPU intermediates across playback frames.

Ordinary animation remains stateless: any requested frame can be evaluated directly. Version 0.16 adds an explicit opt-in stateful-node contract for feedback and simulations. The simulation manager owns hot CPU arrays or GPU textures separately from graph data, advances sequential playback one step at a time, and stores bounded CPU checkpoints for backwards/non-sequential seeking. GPU state ping-pongs between textures and remains resident between frames. Branch revisions invalidate only affected simulation tracks; graph layout edits do not. Runtime state is never serialized. Cancellation is checked between replay frames and iterative GPU dispatches.

See [`SIMULATIONS.md`](SIMULATIONS.md) for the state key, checkpoint, loop, reset and proof-node behaviour.

## Typed image pipeline

Version 0.9 separates an image's semantic meaning from its storage precision:

- `grayscale` — masks, noise, height, AO and scalar texture data;
- `color` — albedo, emissive and other display colour;
- `vector` — normals, flow maps, UV offsets and direction fields;
- `scalar`, `vector2`, `vector3` — animation/control signals rather than images.

Fixed generators and converters declare concrete kinds. Type-preserving processors declare `image_any` plus a policy such as `preserve_primary` or `blend_match`; the scene resolves those ports from current connections and propagates the type through the branch. Connection creation simulates the resulting type propagation before accepting a link, so a late connection cannot invalidate an existing downstream branch. Type-changing edits remove any links that are no longer legal.

Semantic type and precision remain independent. Every image node stores `_precision` as `Inherit`, `8-bit`, `16-bit`, or `32-bit float`. Inherit uses the document precision for generators, the source precision for Image Input, and the highest relevant input precision for processors. Eight-bit results use an explicit quantisation pass; colour/vector 16-bit results use RGBA16F, colour/vector 32-bit results use RGBA32F, and 32-bit greyscale uses R32F.

The working graph stores colour in linear space. The Qt preview converts only `color` results from linear to display sRGB. Greyscale data is displayed as neutral RGB without gamma transformation, and vector data is displayed directly.
