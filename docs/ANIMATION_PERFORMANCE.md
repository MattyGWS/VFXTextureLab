# Animation and GPU Cache Performance

Version 0.28.0 extends the responsive 2D preview scheduler to timeline playback without lowering authored preview quality.

## Exact frame-ahead buffering

Ordinary graph playback now uses a dedicated sequential evaluation worker. The current frame remains visible while the next exact-quality frames are prepared. The compact display results are kept in a bounded four-frame buffer, while graph resources remain governed by the existing CPU/GPU LRU caches.

The buffer does not render at a reduced resolution or reduce node sample counts. It uses the document's normal preview resolution and the same GPU-prepared display path as a settled 2D preview.

## Playback modes

### Real-time

Real-time mode derives the playhead from wall-clock time and the document FPS. If a target frame is not ready, the previous completed image remains visible and that display interval is counted as dropped. No obsolete frame queue is built. The newest target becomes the next priority.

### Every frame

Every frame mode advances the playhead only after the next exact frame has completed. Playback may run slower than the requested FPS on a heavy graph, but no frame is omitted. This is especially useful for simulations, loop inspection and frame-transition debugging.

## Time-dependent branch reuse

The evaluator classifies a node as time-dependent when it directly consumes time/state or depends on an upstream time-dependent node. Static branches omit animation values from their cache signatures, so a static generator, Tile Sampler or adjustment branch can remain resident while only animated descendants are recomputed.

When the entire selected preview branch is static, playback prepares and presents its compact display image once. Later timeline ticks update only the frame/time label; they do not re-evaluate the graph, read the same pixels back again, rebuild a QImage or upload an identical preview.

Stateful nodes retain their hot sequential runtime state. Frame-ahead evaluation naturally keeps ordinary playback to one state step per prepared frame, while existing checkpoints continue to support backwards scrubbing and non-sequential requests.

## Compact profiler

Enable **Profiler** in the Timeline panel to display:

- rendered playback FPS;
- total evaluation, finalise/readback and Qt presentation time;
- prepared frame count and dropped display frames;
- time-dependent and static reachable-node counts;
- cache hits and current GPU-cache use;
- the slowest nodes actually computed for the latest frame.

Detailed per-node trace construction is skipped during playback while the profiler is disabled. This removes diagnostic overhead without changing the rendered image. The full Evaluation Inspector remains available for ordinary previews.

## 3D preview behaviour

During playback, automatic 3D updates are requested only after a completed 2D frame is presented and remain background-priority work. This prevents the material preview from competing with the next direct timeline frame.

## Next optimisation milestone

Compatible adjacent graph operations can eventually be fused into fewer shader passes. Adjustment chains such as Brightness, Contrast, Gamma, Levels, Clamp and Invert are the first intended candidates for shader and graph fusion.

## 0.28.1 real-time presentation correction

Real-time playback no longer requires a completed render to match the playhead's exact frame number before it can be shown. When a costly frame finishes after the timeline has moved on, the newest completed exact-quality frame is presented immediately while rendering continues toward the latest requested target. True frame-ahead results are still held until their timeline position arrives.


## Material 2D presentation in 0.48.6

Focused Material playback uses one material evaluation stream for both outputs. Each completed Base Colour display frame is presented to the 2D Preview immediately, while the 3D viewport independently coalesces completed material results to its stable display cadence. This avoids both the old 15 FPS 2D throttle and the earlier duplicate-evaluation design.
