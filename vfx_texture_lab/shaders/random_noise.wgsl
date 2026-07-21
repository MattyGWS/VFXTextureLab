struct Params {
    p0: vec4<f32>,
    p1: vec4<f32>,
    p2: vec4<f32>,
    p3: vec4<f32>,
};
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var output_tex: texture_storage_2d<rgba32float, write>;

// @include <noise/common.wgsl>

fn random_layer(cell: vec2<u32>, layer: u32, seed: u32, gaussian: bool, mean: f32, deviation: f32) -> f32 {
    let cell3 = vec3<u32>(cell, layer);
    let h1 = noise_hash31(cell3, seed, 0u);
    if (!gaussian) { return h1; }
    let h2 = max(noise_hash31(cell3, seed, 1u), 0.0000001);
    let sample = sqrt(-2.0 * log(h2)) * cos(NOISE_TAU * h1);
    return clamp(mean + sample * max(deviation, 0.0001), 0.0, 1.0);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let scale = max(u32(round(params.p1.x)), 1u);
    let seed = u32(max(params.p1.y, 0.0));
    let mean = params.p1.z;
    let deviation = params.p1.w;
    let evolution = params.p2.x;
    let loop_frames = max(u32(round(params.p2.y)), 1u);
    let contrast = params.p2.z;
    let balance = params.p2.w;
    let mode = i32(round(params.p3.x));
    let invert = params.p3.y > 0.5;
    let uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / vec2<f32>(f32(width), f32(height));
    let cells = vec2<u32>(scale, max(u32(round(f32(scale) * f32(height) / max(f32(width), 1.0))), 1u));
    let cell = vec2<u32>(floor(uv * vec2<f32>(cells)));
    let phase = noise_evolution_phase(evolution) * f32(loop_frames);
    let base = i32(floor(phase));
    let layer0 = noise_wrap_i(base, i32(loop_frames));
    let layer1 = (layer0 + 1u) % loop_frames;
    let blend = noise_fade(fract(phase));
    let gaussian = mode == 1;
    let a = random_layer(cell, layer0, seed, gaussian, mean, deviation);
    let b = random_layer(cell, layer1, seed, gaussian, mean, deviation);
    var value = mix(a, b, blend);
    value = noise_finish(value, contrast, balance, invert);
    textureStore(output_tex, vec2<i32>(gid.xy), vec4<f32>(value, value, value, 1.0));
}
