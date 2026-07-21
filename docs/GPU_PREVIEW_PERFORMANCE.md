# GPU preview and interactive performance

> **0.43.3 update:** the view-sized 512–1024 display ceiling described below was removed because it hid fine detail and made the 2D Preview disagree with full-resolution output. The GPU preparation path remains RGBA8, but now retains the complete configured Preview Max dimensions. Canvas minification is filtered; enlargement is nearest-neighbour.


Version 0.27.0 introduced GPU-native preview preparation. Since 0.43.3 the document and graph evaluate at the configured preview resolution and the complete authored Preview Max result is retained as RGBA8 display pixels.

## Previous path

The old 2D path completed GPU evaluation and then:

1. Read the complete float texture back to the CPU.
2. Expanded grayscale formats into a full float32 RGBA NumPy array.
3. Copied the full array for channel controls.
4. Converted linear colour to sRGB on the CPU.
5. Converted the full image to RGBA8 and constructed a QImage.
6. Let Qt upload that QImage again for presentation.

A 2048 × 2048 float32 RGBA preview is 64 MiB before temporary copies. This made the display stage expensive even when the graph shader itself was fast.

## New path

`preview_prepare.wgsl` now receives the completed graph texture and performs:

- exact-size presentation of the configured Preview Max result;
- linear-to-sRGB display conversion for colour data;
- grayscale replication;
- opaque vector/normal presentation;
- clamping and RGBA8 conversion.

Only the RGBA8 presentation result is read back. The graph resource remains untouched at full authored preview resolution for downstream nodes and exports. A 2048 × 2048 preview transfers about 16 MiB instead of a 64 MiB RGBA32F array; artists choosing a 4096 Preview Max explicitly accept the corresponding 64 MiB display cache in exchange for exact 4K inspection.

## Persistent preview resources

Prepared-preview output textures, readback buffers, and uniform buffers are reused across frames. Up to four target-size variants are retained so ordinary dock resizing does not create unbounded GPU allocations.

## Batched graph submissions

Ordinary GPU nodes are encoded into one command buffer and submitted together. The batch is flushed when a real synchronisation point is necessary, such as:

- an iterative node requesting truthful progress/cancellation;
- a CPU fallback requiring an intermediate readback;
- final display preparation;
- a full-resolution export readback.

Textures referenced by the command batch are pinned until submission, allowing the evaluator to release logical intermediates without destroying resources still referenced by queued commands.

## Interactive scheduling

During a parameter drag, a newly requested frame can cancel an obsolete draft before its full display preparation. The last completed image stays visible while the replacement is evaluated. This avoids the previous rhythm where the newest slider value had to wait behind a stale in-flight preview.
If cancellation happens while ordinary nodes are still being encoded, that unsubmitted command batch is discarded instead of being needlessly queued on the GPU.

Directional, Radial, Zoom, Anisotropic, Non-uniform, and Slope Blur temporarily use bounded sample counts during continuous interaction. Slider release cancels any remaining draft and immediately requests the exact authored sample count at the full configured preview resolution.

## What remains full resolution

The following still request untouched graph pixels:

- image export;
- flipbook assembly;
- histogram/analysis jobs that need source values;
- CPU fallback nodes when their algorithms require the complete image;
- 3D material branch evaluation and texture upload.

The performance path changes display transport, not graph correctness or export resolution.
