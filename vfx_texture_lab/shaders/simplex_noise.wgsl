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
    let scale = max(params.p1.x, 0.25);
    let seed = u32(max(params.p1.y, 0.0));
    let evolution = params.p1.z;
    let loop_cycles = max(params.p1.w, 0.001);
    let contrast = params.p2.x;
    let balance = params.p2.y;
    let invert = params.p2.z > 0.5;
    let uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / vec2<f32>(f32(width), f32(height));
    let angle = NOISE_TAU * noise_evolution_phase(evolution) * loop_cycles;
    let shift = vec2<f32>(cos(angle) - 1.0, sin(angle)) * 0.12;
    let radius = scale / NOISE_TAU;
    let phase = NOISE_TAU * (uv + shift);
    let point = vec4<f32>(
        cos(phase.x) * radius,
        sin(phase.x) * radius,
        cos(phase.y) * radius,
        sin(phase.y) * radius,
    );
    var value = noise_gradient4_value(point, seed);
    value = noise_finish(value, contrast, balance, invert);
    textureStore(output_tex, vec2<i32>(gid.xy), vec4<f32>(value, value, value, 1.0));
}
