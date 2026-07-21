struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;
fn luminance(value: vec4<f32>) -> f32 { return dot(value.rgb, vec3<f32>(0.2126, 0.7152, 0.0722)); }
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x); let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let coord = vec2<i32>(gid.xy); let source = textureLoad(input_tex, coord, 0);
    let value = select(luminance(source), source.r, params.p1.z >= 0.5);
    let threshold_value = params.p1.x; let softness = params.p1.y;
    var result: f32;
    if (softness <= 0.00001) { result = select(0.0, 1.0, value >= threshold_value); }
    else { let t = clamp((value - threshold_value) / softness + 0.5, 0.0, 1.0); result = t * t * (3.0 - 2.0 * t); }
    textureStore(output_tex, coord, vec4<f32>(result, result, result, 1.0));
}
