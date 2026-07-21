struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

// @include "resampling_common.wgsl"

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x); let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    if (params.p3.z >= 0.5) {
        textureStore(output_tex, vec2<i32>(gid.xy), textureLoad(input_tex, vec2<i32>(gid.xy), 0));
        return;
    }
    let size_f = vec2<f32>(f32(width), f32(height));
    let uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / size_f;
    let mode = i32(params.p1.x + 0.5);
    var source_uv = uv;
    if (mode == 0) {
        source_uv = uv * max(params.p1.yz, vec2<f32>(0.001));
    } else if (mode == 1) {
        source_uv = uv - params.p1.yz;
    } else if (mode == 2) {
        let angle = -params.p1.y * 0.017453292519943295;
        let c = cos(angle); let s = sin(angle);
        let centred_pixels = (uv - vec2<f32>(0.5)) * size_f;
        let source_pixels = vec2<f32>(centred_pixels.x*c - centred_pixels.y*s, centred_pixels.x*s + centred_pixels.y*c);
        source_uv = source_pixels / size_f + vec2<f32>(0.5);
    } else if (mode == 3) {
        source_uv = (uv - vec2<f32>(0.5)) / max(params.p1.yz, vec2<f32>(0.001)) + vec2<f32>(0.5);
    } else {
        let axis = i32(params.p1.y + 0.5);
        if (axis == 0 || axis == 2) { source_uv.x = 1.0 - source_uv.x; }
        if (axis == 1 || axis == 2) { source_uv.y = 1.0 - source_uv.y; }
    }
    let pixel = source_uv * size_f - vec2<f32>(0.5);
    let result = sample_filtered(pixel, vec2<i32>(i32(width), i32(height)), i32(params.p2.x+0.5), i32(params.p2.z+0.5), i32(params.p2.y+0.5), params.p3.xy);
    textureStore(output_tex, vec2<i32>(gid.xy), clamp(result, vec4<f32>(0.0), vec4<f32>(1.0)));
}
