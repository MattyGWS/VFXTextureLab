struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;
fn luminance(value: vec4<f32>) -> f32 { return dot(value.rgb, vec3<f32>(0.2126, 0.7152, 0.0722)); }
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x); let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let coord = vec2<i32>(gid.xy); var source = textureLoad(input_tex, coord, 0);
    if (params.p1.y >= 0.5) { source = vec4<f32>(source.r, source.r, source.r, 1.0); }
    let channel = u32(params.p1.x);
    var value = source.r;
    if (channel == 1u) { value = source.g; } else if (channel == 2u) { value = source.b; }
    else if (channel == 3u) { value = source.a; } else if (channel == 4u) { value = luminance(source); }
    textureStore(output_tex, coord, vec4<f32>(value, value, value, 1.0));
}
