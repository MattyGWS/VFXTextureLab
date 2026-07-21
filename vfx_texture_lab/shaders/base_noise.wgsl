struct Params {
    p0: vec4<f32>,
    p1: vec4<f32>,
    p2: vec4<f32>,
    p3: vec4<f32>,
};
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
    let evolution = params.p1.z;
    let loop_cycles = max(params.p1.w, 0.001);
    let disorder = params.p2.x;
    let disorder_scale = max(params.p2.y, 1.0);
    let contrast = params.p2.z;
    let balance = params.p2.w;
    let mode = i32(round(params.p3.x));
    let invert = params.p3.y > 0.5;
    var uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / vec2<f32>(f32(width), f32(height));
    uv = noise_domain_warp(uv, f32(width), f32(height), scale, seed, evolution, loop_cycles, disorder, disorder_scale);
    let cells = noise_aspect_cells(scale, f32(width), f32(height));
    let loop_data = noise_loop_z(evolution, loop_cycles);
    var value = noise_periodic_value3(uv, cells, seed, loop_data.x, u32(loop_data.y));
    if (mode == 1) {
        value = noise_periodic_gradient3(uv, cells, seed, loop_data.x, u32(loop_data.y));
    }
    value = noise_finish(value, contrast, balance, invert);
    textureStore(output_tex, vec2<i32>(gid.xy), vec4<f32>(value, value, value, 1.0));
}
