struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var state_tex: texture_2d<f32>;
@group(0) @binding(2) var flow_tex: texture_2d<f32>;
@group(0) @binding(3) var flow_out: texture_storage_2d<rgba32float, write>;

const DIRS: array<vec2<i32>, 8> = array<vec2<i32>, 8>(
    vec2<i32>(-1, 0), vec2<i32>(1, 0), vec2<i32>(0, -1), vec2<i32>(0, 1),
    vec2<i32>(-1, -1), vec2<i32>(-1, 1), vec2<i32>(1, -1), vec2<i32>(1, 1)
);
fn inside(c: vec2<i32>, s: vec2<i32>) -> bool { return c.x >= 0 && c.y >= 0 && c.x < s.x && c.y < s.y; }
fn wrap(c: vec2<i32>, s: vec2<i32>) -> vec2<i32> { return vec2<i32>((c.x % s.x + s.x) % s.x, (c.y % s.y + s.y) % s.y); }
fn state_at(c: vec2<i32>, s: vec2<i32>, boundary: u32) -> vec4<f32> {
    if (boundary == 0u) { return textureLoad(state_tex, wrap(c, s), 0); }
    if (inside(c, s)) { return textureLoad(state_tex, c, 0); }
    if (boundary == 1u) { return textureLoad(state_tex, clamp(c, vec2<i32>(0), s - vec2<i32>(1)), 0); }
    return vec4<f32>(0.0);
}
fn flow_at(c: vec2<i32>, s: vec2<i32>, boundary: u32) -> vec4<f32> {
    if (boundary == 0u) { return textureLoad(flow_tex, wrap(c, s), 0); }
    if (inside(c, s)) { return textureLoad(flow_tex, c, 0); }
    return vec4<f32>(0.0);
}
fn rain_variation(c: vec2<i32>, s: vec2<i32>, seed: f32) -> f32 {
    let uv = (vec2<f32>(c) + vec2<f32>(0.5)) / vec2<f32>(s);
    let phase = seed * 0.137;
    let v = 0.5
        + 0.22 * sin((uv.x * 2.0 + phase) * 6.28318530718)
        + 0.18 * cos((uv.y * 3.0 - phase * 0.7) * 6.28318530718)
        + 0.10 * sin(((uv.x + uv.y) * 4.0 + phase * 0.3) * 6.28318530718);
    return clamp(v, 0.0, 1.0);
}
fn source(c: vec2<i32>, s: vec2<i32>, boundary: u32) -> f32 {
    let q = state_at(c, s, boundary);
    let variation = mix(1.0, rain_variation(wrap(c, s), s, params.p2.x), clamp(params.p1.z, 0.0, 1.0));
    return max(q.w, 0.0) * max(params.p1.y, 0.0) * variation;
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let s = vec2<i32>(i32(params.p0.x), i32(params.p0.y));
    let c = vec2<i32>(gid.xy);
    if (!inside(c, s)) { return; }
    let boundary = u32(params.p2.y);
    let current = textureLoad(flow_tex, c, 0);
    var incoming = 0.0;
    for (var i = 0u; i < 8u; i = i + 1u) {
        let sender = c - DIRS[i];
        if (boundary != 0u && !inside(sender, s)) { continue; }
        let sf = flow_at(sender, s, boundary);
        let sdir = vec2<i32>(i32(round(sf.y)), i32(round(sf.z)));
        if (sdir.x == DIRS[i].x && sdir.y == DIRS[i].y) {
            incoming += max(sf.x, 0.0) * clamp(params.p1.x, 0.0, 0.9995);
        }
    }
    let accumulation = clamp(source(c, s, boundary) + incoming, 0.0, 1000000.0);
    textureStore(flow_out, c, vec4<f32>(accumulation, current.y, current.z, current.w));
}
