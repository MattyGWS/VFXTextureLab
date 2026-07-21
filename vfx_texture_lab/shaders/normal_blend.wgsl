struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var background_tex: texture_2d<f32>;
@group(0) @binding(2) var foreground_tex: texture_2d<f32>;
@group(0) @binding(3) var mask_tex: texture_2d<f32>;
@group(0) @binding(4) var output_tex: texture_storage_2d<rgba32float, write>;

fn decode_normal(value: vec3<f32>, directx: bool) -> vec3<f32> {
    var n = value * 2.0 - vec3<f32>(1.0);
    if (directx) { n.y = -n.y; }
    if (dot(n, n) < 0.00000001) { return vec3<f32>(0.0, 0.0, 1.0); }
    return normalize(n);
}
fn encode_normal(value: vec3<f32>, directx: bool) -> vec3<f32> {
    var n = normalize(select(value, vec3<f32>(0.0, 0.0, 1.0), dot(value, value) < 0.00000001));
    if (directx) { n.y = -n.y; }
    return clamp(n * 0.5 + vec3<f32>(0.5), vec3<f32>(0.0), vec3<f32>(1.0));
}
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x); let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let p = vec2<i32>(gid.xy);
    let directx = params.p1.y >= 0.5;
    let base = decode_normal(textureLoad(background_tex, p, 0).rgb, directx);
    let detail = decode_normal(textureLoad(foreground_tex, p, 0).rgb, directx);
    let mask = clamp(textureLoad(mask_tex, p, 0).r * params.p1.x, 0.0, 1.0);
    let result = mix(base, detail, mask);
    textureStore(output_tex, p, vec4<f32>(encode_normal(result, directx), 1.0));
}
