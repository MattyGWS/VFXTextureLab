# Public custom-node packages

VFX Texture Lab supports source-visible GPU nodes that can be installed or discovered from ordinary folders without modifying the application.

## Package layout

```text
my_node/
├── node.toml          # required
├── kernel.wgsl        # required unless another local filename is declared
├── icon.svg           # optional
└── README.md          # optional
```

A folder added through **Library → Custom Node & Graph Asset Libraries…** may contain many package subfolders. The managed install folder is used by **Install Custom Node Package…**.

## Minimal manifest

```toml
api_version = 2
id = "com.example.sine_waves"
name = "Sine Waves"
version = "1.0.0"
category = "Patterns"
description = "A seamless horizontal sine pattern."
accent = "#6876df"
tags = ["sine", "wave", "stripe"]
shader = "kernel.wgsl"
icon = "icon.svg"
output_format = "r16f"
output_name = "Value"
output_kind = "grayscale"
format_policy = "declared"

[[parameters]]
id = "frequency"
name = "Frequency"
type = "float"
default = 8.0
minimum = 1.0
maximum = 64.0
step = 0.25
description = "Cycles across the texture."
```

## Top-level manifest fields

| Field | Required | Meaning |
|---|---:|---|
| `api_version` | yes | `1` for static packages or `2` for motion/animatable metadata. |
| `id` | yes | Permanent unique reverse-domain identifier, e.g. `com.artist.cloud_noise`. |
| `name` | yes | Display name. |
| `version` | yes | Package's own version string. |
| `category` | no | Library category; defaults to `Custom`. Slash-separated text is allowed for organisation. |
| `description` | no | User-facing explanation and tooltip. |
| `accent` | no | Six-digit node colour such as `#6876df`. |
| `tags` | no | Search terms as a TOML string array. |
| `shader` | no | Shader filename inside the package; defaults to `kernel.wgsl`. |
| `icon` | no | Optional icon filename inside the package. |
| `output_format` | no | `r16f`, `rg16f`, `rgba16f`, or `rgba32f`; defaults to `rgba16f`. |
| `output_name` | no | Label for the single public output; defaults to `Image`. |
| `output_kind` | no | `grayscale`, `color`, `vector`, or `image_any`. Inferred from format when omitted. |
| `format_policy` | no | `declared` or `preserve_first`; defaults to `declared`. |

`id` is serialized into graphs and must never be casually changed after publishing. Display names may change without breaking projects.

### Output format policy

`declared` always uses `output_format` as the node's logical result type.

`preserve_first` keeps the first connected input's logical format where possible. It is useful for coordinate transforms and filters that should preserve scalar input as scalar and colour input as colour.

### Multiple public outputs

A package can expose several named outputs from one WGSL kernel. The kernel still writes one result per evaluation; VFX Texture Lab sets the declared selector parameter to the value associated with the connected output socket.

```toml
output_parameter = "preview_output"

[[outputs]]
name = "Distance"
kind = "grayscale"
format = "r16f"
value = "Distance"

[[outputs]]
name = "Edge"
kind = "grayscale"
format = "r16f"
value = "Edge"

[[outputs]]
name = "Cell Value"
kind = "grayscale"
format = "r16f"
value = "Cell Value"

[[parameters]]
id = "preview_output"
name = "Preview Output"
type = "enum"
default = "Distance"
options = ["Distance", "Edge", "Cell Value"]
```

`output_parameter` must name an enum or numeric parameter. Each `[[outputs]]` entry may declare `name`, `kind`, `format`, and `value`. `value` is assigned to the selector parameter while that socket is evaluated. The selector parameter also controls which output appears when the node itself is active in the 2D preview.

Connections remember the exact output name, so multiple outputs survive saving, copy/paste, groups, and reusable `.vfxnode` assets. The bundled Voronoi package is the authoritative multi-output example.

## Image inputs

Inputs are declared in binding order:

```toml
[[inputs]]
name = "Image"
type = "color"
default = "black"

[[inputs]]
name = "Mask"
type = "grayscale"
default = "white"
```

API versions 1 and 2 support at most eight image inputs. `type` may be `grayscale`, `color`, `vector`, or `image_any`. `default` must be `black` or `white` and is used when the socket is unconnected. Typed inputs participate in the same connection validation and colour coding as built-in nodes.

## Parameters

Parameters appear in the declaration order and are packed into twelve f32 shader slots. A scalar parameter consumes one slot; a colour consumes four.

### Float

```toml
[[parameters]]
id = "strength"
name = "Strength"
type = "float"
default = 0.5
minimum = -2.0
maximum = 2.0
step = 0.01
description = "Amount of distortion."
```

### Integer

```toml
[[parameters]]
id = "seed"
name = "Seed"
type = "int"
default = 1
minimum = 0
maximum = 100000
step = 1
```

Integers are represented as exactly-valued f32 data in WGSL and can be converted with `i32()` or `u32()`.

### Boolean

```toml
[[parameters]]
id = "wrap"
name = "Wrap"
type = "bool"
default = true
```

Booleans arrive as `1.0` or `0.0`.

### Enum

```toml
[[parameters]]
id = "mode"
name = "Mode"
type = "enum"
default = "Distance"
options = ["Distance", "Edge", "Cell Random"]
```

Enums arrive as the zero-based index of the selected option.

### Colour

```toml
[[parameters]]
id = "colour"
name = "Colour"
type = "color"
default = "#ff8040ff"
```

Colours consume four consecutive slots and arrive as linearised RGBA values in the application's standard 0–1 representation.

Parameter IDs must match `[A-Za-z_][A-Za-z0-9_]*`. Treat IDs as serialized API once a node is shared.

## WGSL ABI version 1

Every package shader declares:

```wgsl
struct Params {
    p0: vec4<f32>,
    p1: vec4<f32>,
    p2: vec4<f32>,
    p3: vec4<f32>,
};

@group(0) @binding(0) var<uniform> params: Params;
```

- `params.p0.x` = output width.
- `params.p0.y` = output height.
- `params.p0.zw` are reserved.
- `p1`–`p3` are twelve consecutive parameter slots in manifest order.

Each image input follows at bindings 1, 2, and so on. The output storage texture is the next binding after the final input.

For a one-input node:

```wgsl
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;
```

For a generator with no inputs, the output is binding 1.

Use `rgba32float` as the storage token in source. Before compilation, VFX Texture Lab creates variants and substitutes the physical output format (`r32float`, `rg32float`, `rgba16float`, or `rgba32float`). A shader should therefore store a `vec4<f32>` even when only the red channel is retained.

The application dispatches 8×8 workgroups:

```wgsl
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) {
        return;
    }

    let uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) /
        vec2<f32>(f32(width), f32(height));
    let value = 0.5 + 0.5 * sin(uv.x * 6.28318530718 * params.p1.x);
    textureStore(output_tex, vec2<i32>(gid.xy), vec4<f32>(value, value, value, 1.0));
}
```

### Scalar input sampling

A greyscale GPU texture should be read from `.x`. The manifest now declares semantic input and output kinds, while `format_policy = "preserve_first"` makes an `image_any` processor follow its primary connected image type.

### Shared WGSL includes

VFX Texture Lab expands source-visible includes before compiling a package shader:

```wgsl
// @include <noise/common.wgsl>
```

Angle brackets resolve against the application's shared shader library. Quoted or relative paths resolve inside the package folder. Includes are expanded recursively, duplicate inclusions are suppressed, and cycles are reported as diagnostics.

The built-in noise library provides hashes, periodic value and gradient noise, cellular searches, domain warping, loop helpers, and common shaping functions. Packages should still be distributed with all package-local includes they require.

### Tiling

WGSL integer `textureLoad` does not wrap automatically. Wrap indices explicitly:

```wgsl
fn wrap_index(value: i32, size: i32) -> i32 {
    return (value % size + size) % size;
}
```

For bilinear resampling, wrap or clamp all four neighbour coordinates deliberately. The bundled Polar Coordinates and Directional Warp packages contain working examples.

## Discovery order and duplicate IDs

The application scans:

1. bundled public packages;
2. the managed user installation folder;
3. enabled user-added library folders.

The first discovered package with a permanent ID remains active. Later duplicates are shown as diagnostics. Do not depend on source order to override another package.

## Library folders

Open **Library → Custom Node & Graph Asset Libraries…** to:

- add any folder containing package folders;
- assign a friendly library name;
- enable or disable scanning;
- open or remove the location;
- rescan immediately.

Removing a library entry does not delete its files. Settings apply to the whole application rather than one project.

## Installing archives

**Install Custom Node Package…** accepts ZIP-compatible `.zip` and `.vfxnodepkg` files. The archive should contain either the package files at its root or one top-level package folder.

The installer validates the archive and copies the package into the managed user directory. Absolute paths, `..` traversal, and symbolic-link entries are rejected.

## Hot reload

Saving `kernel.wgsl`, `node.toml`, or the icon triggers a coalesced rescan. The watcher also observes package/library directories so newly added package folders appear while the application is open.

A valid shader edit recompiles and refreshes current graph instances. If compilation fails:

- the error appears in Custom Node Diagnostics;
- line/column and source context are shown when available;
- the previous successfully compiled shader remains active where possible;
- fixing and saving the source reloads it again.

Use `Ctrl+Shift+R` for a manual reload.

Structural manifest changes are best made carefully. Renamed or removed sockets cannot preserve every external connection, while compatible parameters and ports are retained by name.

## Missing packages in graphs

Projects embed a small interface snapshot for custom package instances. When a package is absent, the node becomes a visible placeholder rather than being discarded. Restoring the package and reloading replaces it with the real node definition.

Keep permanent IDs stable and increment `version` when publishing meaningful changes. API version and package version are separate concepts:

```toml
api_version = 1       # VFX Texture Lab package specification
version = "1.2.0"     # your node package release
```

## Diagnostics

Open **Library → Custom Node Diagnostics…** for manifest errors, shader compiler output, duplicate IDs, disabled packages, unavailable WebGPU warnings, and source paths. Packages can be disabled without removing their files.

A runtime shader failure marks the affected graph node and records the error. Other graph branches and healthy packages continue to function.

## CPU mode and security

User-installed API version 1 and 2 packages are WGSL-only. Forced CPU mode cannot evaluate them and reports a clear error. Built-in nodes retain trusted CPU references.

A package bundled with the application may be mapped to a trusted internal CPU reference for automated CPU/GPU comparison tests. That mapping is application source code, not executable content loaded from the package folder. Third-party packages never gain Python execution through this mechanism.

Third-party packages cannot include executable Python. WGSL receives only declared uniforms and textures; it cannot directly read files, access the network, spawn programs, or import Python modules.

## Sharing checklist

Before distributing a node:

1. Use a unique reverse-domain permanent ID.
2. Test non-square textures and edge tiling.
3. Verify every parameter limit and default.
4. Open Custom Node Diagnostics and confirm a Ready status.
5. Test the package from a separate library folder.
6. Increment the package version.
7. Include a short README or usage example.
8. Zip the entire package folder.

The three bundled packages under `vfx_texture_lab/node_packages/` are authoritative examples of generator, one-input coordinate, and two-input distortion nodes.

## API version 2: animation and time

API version 2 remains compatible with the API version 1 image-compute ABI and adds first-class motion metadata.

```toml
api_version = 2

[animation]
uses_time = true

[[parameters]]
id = "phase"
name = "Phase"
type = "float"
default = 0.0
minimum = 0.0
maximum = 1.0
step = 0.01
animatable = true
```

`animatable = true` gives a numeric parameter a toggle in the Parameters panel. Exposing it creates a scalar input socket that can be driven by Time, Cycle, Wave, Math, Remap or Curve nodes. When a socket is unconnected, the ordinary parameter value remains in control.

Optional `group` and `group_order` fields place the control in a named collapsible Parameters section. Existing manifests may omit them and use the editor's standard Base Settings, Parameters, Transform, Animation, Tiling / Boundaries, Quality and Output grouping rules.

Numeric parameters may also declare interaction metadata without changing the WGSL ABI:

```toml
slider_minimum = -180.0 # optional soft slider range
slider_maximum = 180.0
fine_step = 1.0         # Ctrl while dragging/stepping
coarse_step = 5.0       # Shift while dragging/stepping
editor = "angle"        # optional circular direction dial
unit = "degrees"        # displays a degree suffix
angle_wrap = true        # false allows authored values beyond one revolution
```

`minimum` and `maximum` remain the hard accepted bounds. A typed value outside the soft slider range remains valid. `editor = "angle"` is supported for float or integer degree controls; omit it for angle magnitudes such as random ranges or slope limits. Angle dials wrap through their soft range by default; set `angle_wrap = false` for operations where values beyond one revolution have a distinct authored meaning.

When `[animation].uses_time = true`, the node is invalidated as the timeline changes even without an incoming signal. The public uniform block exposes:

- `p0.x`: output width
- `p0.y`: output height
- `p0.z`: time in seconds
- `p0.w`: normalised document time from 0 to 1

API version 1 packages remain loadable and behave as static image nodes. Public packages remain WGSL-only and cannot execute arbitrary Python.
