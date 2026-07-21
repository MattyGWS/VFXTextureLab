# Adding nodes

There are two supported authoring routes.

## Public WGSL package — recommended for new visual nodes

Create a folder containing `node.toml` and `kernel.wgsl`, then add its parent folder through **Library → Custom Node & Graph Asset Libraries…**. The application discovers it, builds the UI from the manifest, compiles the shader, and hot-reloads saved edits.

Start from:

```text
examples/custom_node_template/
```

Complete details are in [`CUSTOM_NODES.md`](CUSTOM_NODES.md).

Public packages are the preferred route for new generators, filters, distortions, coordinate operations, and other GPU texture nodes because they:

- require no modification of the application source;
- remain readable and shareable;
- are validated independently;
- use the same loader as bundled public nodes;
- update live while being edited;
- cannot execute arbitrary downloaded Python.

## Built-in node with CPU reference

Core nodes may still be implemented inside the application when they need a trusted NumPy/Pillow reference, specialised engine behaviour, file decoding, or close integration with project/export systems.

A built-in definition resembles:

```python
from typing import Any, Mapping

import numpy as np

from .base import EvalContext, ImageArray, NodeDefinition, ParameterSpec
from .image_ops import grayscale_rgba


def eval_sine(
    _inputs: Mapping[str, ImageArray],
    params: Mapping[str, Any],
    context: EvalContext,
) -> ImageArray:
    _y, x = np.mgrid[0:context.height, 0:context.width]
    u = (x.astype(np.float32) + 0.5) / context.width
    frequency = float(params["frequency"])
    values = np.sin(u * np.pi * 2.0 * frequency) * 0.5 + 0.5
    return grayscale_rgba(values)


SINE_NODE = NodeDefinition(
    type_id="pattern.sine",
    name="Sine Waves",
    category="Patterns",
    evaluator=eval_sine,
    parameters=(
        ParameterSpec("frequency", "Frequency", "float", 8.0, 1.0, 64.0, 0.5),
    ),
    tags=("wave", "stripe"),
    output_format="r16f",
    output_kinds=(("Image", "grayscale"),),
    default_image_kind="grayscale",
    gpu_kernel="sine.wgsl",
)
```

Built-in kernels live in `vfx_texture_lab/shaders/`. They use the same 64-byte parameter block but may use specialised packing and dispatch paths in `WgpuBackend`.

When adding a built-in procedural node:

1. Keep a deterministic vectorised CPU evaluator.
2. Add its WGSL kernel.
3. Register the permanent type ID.
4. Choose the smallest truthful logical output format.
5. Add parameter/input packing in the backend if the public ABI is insufficient.
6. Add CPU/GPU comparison coverage in `tests/backend_test.py`.
7. Test rectangular resolutions and seamless borders.
8. Avoid Python loops over pixels.

## CPU-only source or utility nodes

A built-in node may omit a GPU kernel when its purpose is fundamentally CPU-side. Image Input is the reference case:

- Pillow decodes and interprets the source;
- evaluator caching prevents unnecessary repeat work;
- downstream WGSL consumers upload once;
- the remainder of the chain stays GPU-resident.

CPU-only nodes must still contribute deterministic external revisions to cache signatures.

## Semantic type and format conventions

Declare image semantics independently from storage: `grayscale`, `color`, `vector`, or `image_any`. Use `image_any` only for processors that also declare `type_policy="preserve_primary"` (or a public package using `format_policy="preserve_first"`).

Every image node receives the standard Output precision control automatically. Do not add a duplicate precision parameter to the node definition.

- `r16f` for scalar masks, distances, and heights.
- `rg16f` for two-component vectors and flow maps.
- `rgba16f` for ordinary colour/four-component data.
- `rgba32f` only for explicitly high-precision data.

Compatible processors should preserve the input format when sensible. Do not inflate a scalar graph branch into RGBA merely for convenience.

## General conventions

- Stable type IDs are permanent serialized API.
- CPU images are linear float32 RGBA arrays, usually in 0–1.
- Do not mutate input arrays.
- Respect width and height independently.
- Generator and sampling nodes should tile by default unless their purpose explicitly differs.
- Keep colour encoding decisions explicit; data textures normally remain Linear.
- Verify both interactive preview and full export resolution.
