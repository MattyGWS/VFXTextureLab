struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var state_tex: texture_2d<f32>;
@group(0) @binding(2) var flow_out: texture_storage_2d<rgba32float, write>;

const DIRS: array<vec2<i32>, 8> = array<vec2<i32>, 8>(
    vec2<i32>(-1, 0), vec2<i32>(1, 0), vec2<i32>(0, -1), vec2<i32>(0, 1),
    vec2<i32>(-1, -1), vec2<i32>(-1, 1), vec2<i32>(1, -1), vec2<i32>(1, 1)
);
const DISTS: array<f32, 8> = array<f32, 8>(1.0, 1.0, 1.0, 1.0, 1.41421356, 1.41421356, 1.41421356, 1.41421356);

fn inside(c: vec2<i32>, s: vec2<i32>) -> bool {
    return c.x >= 0 && c.y >= 0 && c.x < s.x && c.y < s.y;
}
fn wrap(c: vec2<i32>, s: vec2<i32>) -> vec2<i32> {
    return vec2<i32>((c.x % s.x + s.x) % s.x, (c.y % s.y + s.y) % s.y);
}
fn state_at(c: vec2<i32>, s: vec2<i32>, boundary: u32) -> vec4<f32> {
    if (boundary == 0u) { return textureLoad(state_tex, wrap(c, s), 0); }
    if (inside(c, s)) { return textureLoad(state_tex, c, 0); }
    if (boundary == 1u) { return textureLoad(state_tex, clamp(c, vec2<i32>(0), s - vec2<i32>(1)), 0); }
    return vec4<f32>(0.0);
}
fn route_height(c: vec2<i32>, s: vec2<i32>, boundary: u32, smoothing: f32) -> f32 {
    let q = state_at(c, s, boundary).x;
    var total = q * 4.0;
    var weight = 4.0;
    for (var i = 0u; i < 8u; i = i + 1u) {
        let n = c + DIRS[i];
        if (boundary == 1u && !inside(n, s)) { continue; }
        let w = select(1.0, 0.70710678, i >= 4u);
        total += state_at(n, s, boundary).x * w;
        weight += w;
    }
    let smoothed = total / max(weight, 1.0);
    return mix(q, smoothed, clamp(smoothing, 0.0, 1.0));
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
fn rain_source(c: vec2<i32>, s: vec2<i32>, boundary: u32) -> f32 {
    let q = state_at(c, s, boundary);
    let variation = mix(1.0, rain_variation(wrap(c, s), s, params.p2.x), clamp(params.p1.w, 0.0, 1.0));
    return max(q.w, 0.0) * max(params.p1.z, 0.0) * variation;
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let s = vec2<i32>(i32(params.p0.x), i32(params.p0.y));
    let c = vec2<i32>(gid.xy);
    if (!inside(c, s)) { return; }
    let boundary = u32(params.p2.y);
    let radius = max(i32(round(params.p2.w)), 1);
    let center = route_height(c, s, boundary, params.p1.x);
    var best_drop = -1e20;
    var best_index = 0u;
    var lowest_height = 1e20;
    var lowest_index = 0u;
    for (var i = 0u; i < 8u; i = i + 1u) {
        let n = c + DIRS[i] * radius;
        if (boundary == 1u && !inside(n, s)) { continue; }
        let nh = route_height(n, s, boundary, params.p1.x);
        let drop = (center - nh) / (DISTS[i] * f32(radius));
        if (drop > best_drop) { best_drop = drop; best_index = i; }
        if (nh < lowest_height) { lowest_height = nh; lowest_index = i; }
    }
    if (best_drop <= 0.00000001 && params.p1.y > 0.0) {
        best_index = lowest_index;
        best_drop = params.p1.y * 0.00025 / f32(radius);
    }
    let dir = vec2<f32>(DIRS[best_index]);
    let slope = max(best_drop * max(params.p2.z, 0.000001), 0.0);
    textureStore(flow_out, c, vec4<f32>(rain_source(c, s, boundary), dir.x, dir.y, slope));
}
