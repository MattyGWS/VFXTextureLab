struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var state_tex: texture_2d<f32>;
@group(0) @binding(2) var accum_tex: texture_2d<f32>;
@group(0) @binding(3) var flow_tex: texture_2d<f32>;
@group(0) @binding(4) var output_tex: texture_storage_2d<rgba32float, write>;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let s = vec2<i32>(i32(params.p0.x), i32(params.p0.y));
    let c = vec2<i32>(gid.xy);
    if (c.x >= s.x || c.y >= s.y) { return; }
    let q = textureLoad(state_tex, c, 0);
    let a = textureLoad(accum_tex, c, 0);
    let f = textureLoad(flow_tex, c, 0);
    let mode = u32(params.p1.x);
    let flow = 1.0 - exp(-max(f.x, 0.0) * max(params.p2.w, 0.000001));
    var out = vec4<f32>(q.x, q.x, q.x, 1.0);
    if (mode == 1u) {
        let v = clamp(a.x * params.p1.y, 0.0, 1.0); out = vec4<f32>(v, v, v, 1.0);
    } else if (mode == 2u) {
        let v = clamp(a.y * params.p1.y, 0.0, 1.0); out = vec4<f32>(v, v, v, 1.0);
    } else if (mode == 3u) {
        let v = clamp(flow * params.p1.z, 0.0, 1.0); out = vec4<f32>(v, v, v, 1.0);
    } else if (mode == 4u) {
        let v = clamp(a.z * params.p1.w, 0.0, 1.0); out = vec4<f32>(v, v, v, 1.0);
    } else if (mode == 5u) {
        let v = clamp(flow * params.p2.x, 0.0, 1.0); out = vec4<f32>(v, v, v, 1.0);
    } else if (mode == 6u) {
        let v = clamp(max(a.x - a.y, 0.0) * params.p2.y, 0.0, 1.0); out = vec4<f32>(v, v, v, 1.0);
    } else if (mode == 7u) {
        let v = clamp(a.w * params.p2.z, 0.0, 1.0); out = vec4<f32>(v, v, v, 1.0);
    } else if (mode == 8u) {
        var dir = vec2<f32>(f.y, f.z);
        let len = length(dir);
        if (len > 0.000001) { dir /= len; }
        out = vec4<f32>(dir * 0.5 + vec2<f32>(0.5), 0.5, 1.0);
    }
    textureStore(output_tex, c, out);
}
