struct Params {
    p0: vec4<f32>,
    p1: vec4<f32>,
    p2: vec4<f32>,
    p3: vec4<f32>,
    p4: vec4<f32>,
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
    let octave_count = clamp(u32(round(params.p1.y)), 1u, 10u);
    let lacunarity = max(params.p1.z, 1.01);
    let gain = clamp(params.p1.w, 0.0, 1.0);
    let seed = u32(max(params.p2.x, 0.0));
    let evolution = params.p2.y;
    let loop_cycles = max(params.p2.z, 0.001);
    let disorder = params.p2.w;
    let disorder_scale = max(params.p3.x, 1.0);
    let ridge_offset = max(params.p3.y, 0.01);
    let ridge_sharpness = max(params.p3.z, 0.1);
    let octave_weight = max(params.p3.w, 0.0);
    let valley_width = clamp(params.p4.x, 0.0, 1.0);
    let contrast = params.p4.y;
    let balance = params.p4.z;
    let invert = params.p4.w > 0.5;

    var uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / vec2<f32>(f32(width), f32(height));
    uv = noise_domain_warp(uv, f32(width), f32(height), scale, seed, evolution, loop_cycles, disorder, disorder_scale);

    var total = 0.0;
    var amplitude = 1.0;
    var amplitude_sum = 0.0;
    var feedback = 1.0;
    var frequency = scale;
    for (var octave: u32 = 0u; octave < 10u; octave = octave + 1u) {
        if (octave >= octave_count) { break; }
        let cells = noise_aspect_cells(frequency, f32(width), f32(height));
        let loop_data = noise_loop_z(evolution, loop_cycles);
        let base = noise_periodic_gradient3(uv, cells, seed + octave * 1013u, loop_data.x, u32(loop_data.y));
        let signed_value = base * 2.0 - 1.0;
        var ridge = clamp(ridge_offset - abs(signed_value) * (1.0 + valley_width), 0.0, 1.0);
        ridge = pow(ridge, ridge_sharpness);
        let weighted = ridge * feedback;
        total = total + weighted * amplitude;
        amplitude_sum = amplitude_sum + amplitude;
        feedback = clamp(weighted * octave_weight, 0.0, 1.0);
        amplitude = amplitude * gain;
        frequency = frequency * lacunarity;
    }
    var value = total / max(amplitude_sum, 0.000001);
    value = noise_finish(value, contrast, balance, invert);
    textureStore(output_tex, vec2<i32>(gid.xy), vec4<f32>(value, value, value, 1.0));
}
