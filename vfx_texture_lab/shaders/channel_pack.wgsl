struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_r: texture_2d<f32>;
@group(0) @binding(2) var input_g: texture_2d<f32>;
@group(0) @binding(3) var input_b: texture_2d<f32>;
@group(0) @binding(4) var input_a: texture_2d<f32>;
@group(0) @binding(5) var output_tex: texture_storage_2d<rgba32float, write>;
fn luminance(value: vec4<f32>) -> f32 { return dot(value.rgb, vec3<f32>(0.2126, 0.7152, 0.0722)); }
fn scalar_value(value: vec4<f32>, is_scalar: f32) -> f32 { return select(luminance(value), value.r, is_scalar >= 0.5); }
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x); let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let coord = vec2<i32>(gid.xy);
    textureStore(output_tex, coord, vec4<f32>(
        scalar_value(textureLoad(input_r, coord, 0), params.p1.x), scalar_value(textureLoad(input_g, coord, 0), params.p1.y),
        scalar_value(textureLoad(input_b, coord, 0), params.p1.z), scalar_value(textureLoad(input_a, coord, 0), params.p1.w)));
}
