struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var source_tex: texture_2d<f32>;
@group(0) @binding(2) var blurred_tex: texture_2d<f32>;
@group(0) @binding(3) var output_tex: texture_storage_2d<rgba32float, write>;
fn srgb_to_linear(v: vec3<f32>) -> vec3<f32> {
    let x = clamp(v, vec3<f32>(0.0), vec3<f32>(1.0));
    let low = x / 12.92;
    let high = pow((x + 0.055) / 1.055, vec3<f32>(2.4));
    return select(high, low, x <= vec3<f32>(0.04045));
}
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x); let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let coord = vec2<i32>(gid.xy);
    let source = textureLoad(source_tex, coord, 0);
    let blurred = textureLoad(blurred_tex, coord, 0);
    let kind = i32(params.p1.x + 0.5);
    if (kind == 0) {
        let detail = clamp(source.r - blurred.r + 0.5, 0.0, 1.0);
        textureStore(output_tex, coord, vec4<f32>(detail, detail, detail, 1.0));
        return;
    }
    var detail = clamp(source.rgb - blurred.rgb + vec3<f32>(0.5), vec3<f32>(0.0), vec3<f32>(1.0));
    if (kind == 1) { detail = srgb_to_linear(detail); }
    textureStore(output_tex, coord, vec4<f32>(detail, source.a));
}
