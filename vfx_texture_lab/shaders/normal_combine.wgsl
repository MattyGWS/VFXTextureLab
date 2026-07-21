struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var base_tex: texture_2d<f32>;
@group(0) @binding(2) var detail_tex: texture_2d<f32>;
@group(0) @binding(3) var mask_tex: texture_2d<f32>;
@group(0) @binding(4) var output_tex: texture_storage_2d<rgba32float, write>;

fn decode_normal(value: vec3<f32>, directx: bool) -> vec3<f32> {
    var n = value * 2.0 - vec3<f32>(1.0);
    if (directx) { n.y = -n.y; }
    if (dot(n, n) < 0.00000001) { return vec3<f32>(0.0, 0.0, 1.0); }
    return normalize(n);
}
fn strengthen(value: vec3<f32>, strength: f32) -> vec3<f32> {
    let n = vec3<f32>(value.xy * max(strength, 0.0), value.z);
    return normalize(select(n, vec3<f32>(0.0, 0.0, 1.0), dot(n, n) < 0.00000001));
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
    let directx = params.p2.x >= 0.5;
    let base = strengthen(decode_normal(textureLoad(base_tex, p, 0).rgb, directx), params.p1.y);
    let detail = strengthen(decode_normal(textureLoad(detail_tex, p, 0).rgb, directx), params.p1.z);
    let method = u32(round(params.p1.x));
    var combined: vec3<f32>;
    if (method == 1u) {
        combined = vec3<f32>(base.xy + detail.xy, base.z * detail.z);
    } else if (method == 2u) {
        combined = vec3<f32>(base.xy + detail.xy, base.z);
    } else {
        let t = base + vec3<f32>(0.0, 0.0, 1.0);
        let u = detail * vec3<f32>(-1.0, -1.0, 1.0);
        combined = t * (dot(t, u) / max(t.z, 0.000001)) - u;
    }
    let amount = clamp(textureLoad(mask_tex, p, 0).r * params.p1.w, 0.0, 1.0);
    textureStore(output_tex, p, vec4<f32>(encode_normal(mix(base, combined, amount), directx), 1.0));
}
