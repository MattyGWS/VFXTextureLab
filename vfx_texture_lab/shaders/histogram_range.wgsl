struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let coord = vec2<i32>(gid.xy);
    let source = textureLoad(input_tex, coord, 0);
    let range_amount = clamp(params.p1.x, 0.0, 1.0);
    let position = clamp(params.p1.y, 0.0, 1.0);
    let low = (1.0 - range_amount) * position;
    let value = low + clamp(source.r, 0.0, 1.0) * range_amount;
    textureStore(output_tex, coord, vec4<f32>(value, value, value, 1.0));
}
