struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x); let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let coord = vec2<i32>(gid.xy);
    let source = textureLoad(input_tex, coord, 0);
    let method = u32(params.p1.x);
    var value = dot(source.rgb, vec3<f32>(0.2126, 0.7152, 0.0722));
    if (method == 1u) { value = (source.r + source.g + source.b) / 3.0; }
    else if (method == 2u) { value = max(source.r, max(source.g, source.b)); }
    else if (method == 3u) { value = source.r; }
    else if (method == 4u) { value = source.g; }
    else if (method == 5u) { value = source.b; }
    textureStore(output_tex, coord, vec4<f32>(value, value, value, 1.0));
}
