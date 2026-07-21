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
    let centred_pixels = ((vec2<f32>(gid.xy) + vec2<f32>(0.5)) / size_f - vec2<f32>(0.5) - params.p1.xy) * size_f;
    let angle = params.p2.x * 0.017453292519943295;
    let ci = cos(-angle); let si = sin(-angle);
    let scale = max(params.p1.zw, vec2<f32>(0.01));
    let source_pixels = vec2<f32>(centred_pixels.x*ci - centred_pixels.y*si, centred_pixels.x*si + centred_pixels.y*ci) / scale;
    let pixel = source_pixels + (size_f - vec2<f32>(1.0)) * 0.5;
    let sampled = sample_filtered(pixel, vec2<i32>(i32(width), i32(height)), i32(params.p2.y+0.5), 2, i32(params.p2.w+0.5), params.p3.xy);
    var n = sampled.rgb * 2.0 - vec3<f32>(1.0);
    let directx = params.p2.z >= 0.5;
    if (directx) { n.y = -n.y; }
    let c = cos(angle); let s = sin(angle);
    n = vec3<f32>(n.x*c - n.y*s, n.x*s + n.y*c, n.z);
    let l = length(n); n = select(vec3<f32>(0.0,0.0,1.0), n/max(l,1e-7), l>1e-7);
    if (directx) { n.y = -n.y; }
    textureStore(output_tex, vec2<i32>(gid.xy), vec4<f32>(clamp(n*0.5+vec3<f32>(0.5), vec3<f32>(0.0), vec3<f32>(1.0)), 1.0));
}
