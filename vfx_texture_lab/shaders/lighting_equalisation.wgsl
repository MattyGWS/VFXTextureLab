struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var source_tex: texture_2d<f32>;
@group(0) @binding(2) var low_tex: texture_2d<f32>;
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
    let low = textureLoad(low_tex, coord, 0);
    let kind = i32(params.p1.x + 0.5);
    if (kind == 2) { textureStore(output_tex, coord, source); return; }
    let strength = clamp(params.p1.y, 0.0, 1.0);
    let target_value = clamp(params.p1.z, 0.01, 1.0);
    let rgb_mode = params.p1.w >= 0.5;
    if (kind == 0) {
        let factor = target_value / max(low.r, 0.02);
        let corrected = clamp(source.r * mix(1.0, factor, strength), 0.0, 1.0);
        textureStore(output_tex, coord, vec4<f32>(corrected, corrected, corrected, 1.0));
        return;
    }
    var factor: vec3<f32>;
    if (rgb_mode) {
        factor = vec3<f32>(target_value) / max(low.rgb, vec3<f32>(0.02));
    } else {
        let luma = max(dot(low.rgb, vec3<f32>(0.2126, 0.7152, 0.0722)), 0.02);
        factor = vec3<f32>(target_value / luma);
    }
    let corrected = clamp(source.rgb * mix(vec3<f32>(1.0), factor, vec3<f32>(strength)), vec3<f32>(0.0), vec3<f32>(1.0));
    textureStore(output_tex, coord, vec4<f32>(srgb_to_linear(corrected), source.a));
}
