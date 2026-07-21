struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;
fn linear_to_srgb(v: vec3<f32>) -> vec3<f32> {
    let x = max(v, vec3<f32>(0.0));
    let low = x * 12.92;
    let high = 1.055 * pow(x, vec3<f32>(1.0 / 2.4)) - 0.055;
    return select(high, low, x <= vec3<f32>(0.0031308));
}
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x); let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    var source = textureLoad(input_tex, vec2<i32>(gid.xy), 0);
    source = vec4<f32>(linear_to_srgb(clamp(source.rgb, vec3<f32>(0.0), vec3<f32>(1.0))), source.a);
    textureStore(output_tex, vec2<i32>(gid.xy), source);
}
