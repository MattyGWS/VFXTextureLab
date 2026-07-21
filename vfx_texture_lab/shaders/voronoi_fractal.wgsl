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
    let octave_count = clamp(u32(round(params.p1.y)), 1u, 8u);
    let lacunarity = max(params.p1.z, 1.01);
    let gain = clamp(params.p1.w, 0.0, 1.0);
    let seed = u32(max(params.p2.x, 0.0));
    let jitter = clamp(params.p2.y, 0.0, 1.0);
    let evolution = params.p2.z;
    let loop_cycles = max(params.p2.w, 0.001);
    let fractal_mode = i32(round(params.p3.x));
    let contrast = params.p3.y;
    let balance = params.p3.z;
    let invert = params.p3.w > 0.5;
    let uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / vec2<f32>(f32(width), f32(height));
    var total = 0.0;
    var amplitude = 1.0;
    var amplitude_sum = 0.0;
    var frequency = scale;
    for (var octave: u32 = 0u; octave < 8u; octave = octave + 1u) {
        if (octave >= octave_count) { break; }
        let cells = noise_aspect_cells(frequency, f32(width), f32(height));
        let result = noise_cellular(
            uv, cells, seed + octave * 1301u, jitter,
            evolution, loop_cycles,
            0, 2.0, 1u
        );
        var sample = clamp(result.f1 * 1.45, 0.0, 1.0);
        if (fractal_mode == 1) {
            sample = clamp((result.f2 - result.f1) * 1.75, 0.0, 1.0);
        }
        total = total + sample * amplitude;
        amplitude_sum = amplitude_sum + amplitude;
        amplitude = amplitude * gain;
        frequency = frequency * lacunarity;
    }
    var value = total / max(amplitude_sum, 0.000001);
    value = noise_finish(value, contrast, balance, invert);
    textureStore(output_tex, vec2<i32>(gid.xy), vec4<f32>(value, value, value, 1.0));
}
