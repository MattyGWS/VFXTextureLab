struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var normal_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x); let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let p = vec2<i32>(gid.xy);
    let directx = params.p2.x >= 0.5;
    var n = textureLoad(normal_tex, p, 0).rgb * 2.0 - vec3<f32>(1.0);
    if (directx) { n.y = -n.y; }
    if (params.p1.x >= 0.5) { n.x = -n.x; }
    if (params.p1.y >= 0.5) { n.y = -n.y; }
    if (params.p1.z >= 0.5) { n.z = -n.z; }
    n = normalize(select(n, vec3<f32>(0.0, 0.0, 1.0), dot(n, n) < 0.00000001));
    if (directx) { n.y = -n.y; }
    textureStore(output_tex, p, vec4<f32>(clamp(n * 0.5 + vec3<f32>(0.5), vec3<f32>(0.0), vec3<f32>(1.0)), 1.0));
}
