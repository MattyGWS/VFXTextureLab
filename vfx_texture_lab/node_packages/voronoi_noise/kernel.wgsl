// VFX Texture Lab public node ABI v2.
struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var output_tex: texture_storage_2d<rgba32float, write>;

// @include <noise/common.wgsl>

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let scale = max(params.p1.x, 1.0);
    let seed = u32(max(params.p1.y, 0.0));
    let jitter = clamp(params.p1.z, 0.0, 1.0);
    let evolution = params.p1.w;
    let loop_cycles = max(params.p2.x, 0.001);
    let metric_mode = i32(round(params.p2.y));
    let exponent = max(params.p2.z, 0.25);
    let edge_width = max(params.p2.w, 0.0);
    let edge_softness = max(params.p3.x, 0.0001);
    let contrast = params.p3.y;
    let balance = params.p3.z;
    let output_mode = i32(round(params.p3.w));
    let uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / vec2<f32>(f32(width), f32(height));
    let cells = noise_aspect_cells(scale, f32(width), f32(height));
    let result = noise_cellular(
        uv, cells, seed, jitter, evolution, loop_cycles, metric_mode, exponent, 1u
    );
    var value = clamp(result.f1 * 1.45, 0.0, 1.0);
    if (output_mode == 1) {
        let t = smoothstep(edge_width, edge_width + edge_softness, result.f2 - result.f1);
        value = 1.0 - t;
    } else if (output_mode == 2) {
        value = result.cell_value;
    } else if (output_mode == 3) {
        value = clamp((result.f2 - result.f1) * 1.75, 0.0, 1.0);
    }
    value = noise_finish(value, contrast, balance, false);
    textureStore(output_tex, vec2<i32>(gid.xy), vec4<f32>(value, value, value, 1.0));
}
