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
    let warp_strength = params.p2.w;
    let warp_scale = max(params.p3.x, 1.0);
    let warp_octaves = clamp(u32(round(params.p3.y)), 1u, 6u);
    let flow_direction = params.p3.z * NOISE_PI / 180.0;
    let directional_bias = clamp(params.p3.w, 0.0, 1.0);
    let fold_sharpness = max(params.p4.x, 0.1);
    let contrast = params.p4.y;
    let balance = params.p4.z;
    let invert = params.p4.w > 0.5;

    let base_uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / vec2<f32>(f32(width), f32(height));
    var warp = vec2<f32>(0.0);
    var warp_amplitude = 1.0;
    var warp_amplitude_sum = 0.0;
    var warp_frequency = warp_scale;
    let direction = vec2<f32>(cos(flow_direction), sin(flow_direction));
    for (var octave: u32 = 0u; octave < 6u; octave = octave + 1u) {
        if (octave >= warp_octaves) { break; }
        let cells = noise_aspect_cells(warp_frequency, f32(width), f32(height));
        let loop_data = noise_loop_z(evolution, loop_cycles);
        let nx = noise_periodic_gradient3(base_uv, cells, seed + 2221u + octave * 811u, loop_data.x, u32(loop_data.y)) * 2.0 - 1.0;
        let ny = noise_periodic_gradient3(base_uv, cells, seed + 4447u + octave * 977u, loop_data.x, u32(loop_data.y)) * 2.0 - 1.0;
        let free_vector = vec2<f32>(nx, ny);
        let directed_vector = direction * nx;
        warp = warp + mix(free_vector, directed_vector, directional_bias) * warp_amplitude;
        warp_amplitude_sum = warp_amplitude_sum + warp_amplitude;
        warp_amplitude = warp_amplitude * 0.5;
        warp_frequency = warp_frequency * 2.0;
    }
    warp = warp / max(warp_amplitude_sum, 0.000001);
    let offset = warp_strength * 0.12 / max(sqrt(max(scale, 1.0)), 1.0);
    let uv = fract(base_uv + warp * offset);

    var total = 0.0;
    var amplitude = 1.0;
    var amplitude_sum = 0.0;
    var frequency = scale;
    for (var octave: u32 = 0u; octave < 10u; octave = octave + 1u) {
        if (octave >= octave_count) { break; }
        let cells = noise_aspect_cells(frequency, f32(width), f32(height));
        let loop_data = noise_loop_z(evolution, loop_cycles);
        let signed_value = noise_periodic_gradient3(uv, cells, seed + octave * 1013u, loop_data.x, u32(loop_data.y)) * 2.0 - 1.0;
        let sample = pow(clamp(abs(signed_value), 0.0, 1.0), fold_sharpness);
        total = total + sample * amplitude;
        amplitude_sum = amplitude_sum + amplitude;
        amplitude = amplitude * gain;
        frequency = frequency * lacunarity;
    }
    var value = total / max(amplitude_sum, 0.000001);
    value = noise_finish(value, contrast, balance, invert);
    textureStore(output_tex, vec2<i32>(gid.xy), vec4<f32>(value, value, value, 1.0));
}
