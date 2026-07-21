# Interactive preview scheduling

Version 0.27.0 keeps the leading-edge, latest-value-wins preview loop and removes two major sources of drag latency: obsolete in-flight display work and full-resolution preview readback.

## Behaviour

When a parameter begins changing, the 2D preview dispatches immediately. Continued slider, spin-box, histogram, gradient, or curve edits are capped to an approximately 33 ms dispatch interval. The graph still evaluates at the configured preview resolution.

During a continuous drag, a newer parameter value can cancel an obsolete draft evaluation before its display preparation/readback. The previous completed image remains visible, so cancellation does not blank or flicker the preview. Only the newest graph state is retained.

On release, any remaining reduced-cost draft is cancelled and one exact authored-quality preview is requested immediately.

Timeline playback retains its separate stale-frame-dropping scheduler. Automatic 3D material refreshes remain lower priority and wait for direct 2D editing to settle.

## Adaptive interactive work

The advanced blur family temporarily uses bounded sample counts during continuous editing:

- Directional Blur
- Radial Blur
- Zoom Blur
- Anisotropic Blur
- Non-uniform Blur Grayscale
- Slope Blur Grayscale

This only affects transient drag frames. Releasing the control restores the authored sample count at the full configured preview resolution.

Iterative terrain nodes keep their existing draft workloads, with the same exact-on-release rule.

## GPU-prepared display

Ordinary 2D previews no longer read the complete float graph texture back to Python. WebGPU prepares an RGBA8 display image at the complete configured Preview Max dimensions, including semantic display conversion. Channel toggles operate on this compact byte image, not on a copied float graph result. A 2048 × 2048 preview therefore retains all detail at roughly 16 MiB rather than a 64 MiB RGBA32F readback.

See `GPU_PREVIEW_PERFORMANCE.md` for the complete data path.

## Why this remains responsive

- Obsolete drag frames do not force the newest value to wait for a full display readback.
- The last completed preview stays visible while replacement work runs.
- Ordinary GPU node chains are submitted in batches rather than one queue submission per node.
- View-sized RGBA8 transfer replaces the former full-resolution float transfer.
- Expensive nodes can lower only their temporary interaction workload.
- Exact authored quality is guaranteed after release.
- Direct 2D feedback retains priority over automatic 3D and histogram work.

## Manual testing checklist

1. Set the preview resolution to 2048 and drag a cheap scalar parameter continuously. The result should begin moving immediately and continue updating without UI-thread stalls.
2. Release the slider at an obvious value. The preview must settle on the exact value without another click.
3. Repeat with Directional, Radial, Zoom, and Anisotropic Blur. Draft frames may be slightly less smooth, but release must restore the authored Samples setting.
4. Toggle R/G/B/A channels on a 2K preview. The controls should react immediately because only the compact display image is changed.
5. Test a graph with several inexpensive GPU nodes. The inspector should show the compact finalise/readback stage rather than a 64 MiB full-resolution display transfer.
6. Test a heavy erosion or simulation graph. The interface should remain responsive and should not continue rendering a long backlog after release.
7. Keep both 2D and 3D previews visible. During direct editing, 3D should wait and then update after the exact 2D result settles.
8. Play and pause the timeline. Playback may drop stale frames; pause must settle on the exact current frame.

## 0.27.1 sustained-drag pacing

Rapid edits no longer cancel the currently rendering interactive frame on every input event. That cancellation policy could starve presentation indefinitely when a dial or slider moved faster than the draft evaluation time. The scheduler now keeps at most one draft in flight and one logical newest-state request pending. Once the current draft is displayed, the newest accumulated state begins immediately. Intermediate states are still discarded rather than queued.
