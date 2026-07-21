struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, p4: vec4<f32>, p5: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var state_tex: texture_2d<f32>;
@group(0) @binding(2) var accum_tex: texture_2d<f32>;
@group(0) @binding(3) var flow_tex: texture_2d<f32>;
@group(0) @binding(4) var state_out: texture_storage_2d<rgba32float, write>;
@group(0) @binding(5) var accum_out: texture_storage_2d<rgba32float, write>;

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
fn smoothstep_safe(a: f32, b: f32, x: f32) -> f32 {
    let t = clamp((x - a) / max(b - a, 0.000001), 0.0, 1.0);
    return t * t * (3.0 - 2.0 * t);
}
fn channel_at(c: vec2<i32>, s: vec2<i32>, boundary: u32) -> f32 {
    let f = flow_at(c, s, boundary);
    let flow = 1.0 - exp(-max(f.x, 0.0) * max(params.p4.w, 0.000001));
    let threshold = mix(0.58, 0.12, clamp(params.p2.x, 0.0, 1.0));
    let base = smoothstep_safe(threshold, threshold + max(params.p2.y, 0.001), flow);
    let slope = 1.0 - exp(-max(f.w, 0.0) * 45.0);
    let head = smoothstep_safe(threshold * 0.35, threshold, flow) * (1.0 - base) * slope * clamp(params.p2.z, 0.0, 1.0);
    return clamp(base + head, 0.0, 1.0);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let s = vec2<i32>(i32(params.p0.x), i32(params.p0.y));
    let c = vec2<i32>(gid.xy);
    if (!inside(c, s)) { return; }
    let boundary = u32(params.p5.y);
    let radius = max(i32(round(params.p5.x)), 1);
    let q = textureLoad(state_tex, c, 0);
    let a = textureLoad(accum_tex, c, 0);
    let f = textureLoad(flow_tex, c, 0);
    let flow = 1.0 - exp(-clamp(max(f.x, 0.0), 0.0, 1000000.0) * max(params.p4.w, 0.000001));
    let channel = channel_at(c, s, boundary);
    let slope = 1.0 - exp(-clamp(max(f.w, 0.0), 0.0, 1000000.0) * 45.0);

    var channel_average = channel;
    var channel_local = channel * 4.0;
    var channel_maximum = channel;
    var channel_weight = 1.0;
    var channel_local_weight = 4.0;
    var height_average = q.x * 4.0;
    var height_weight = 4.0;
    for (var i = 0u; i < 8u; i = i + 1u) {
        let broad_n = c + DIRS[i] * radius;
        if (!(boundary == 1u && !inside(broad_n, s))) {
            let broad_channel = channel_at(broad_n, s, boundary);
            let w = select(1.0, 0.70710678, i >= 4u);
            channel_average += broad_channel * w;
            channel_maximum = max(channel_maximum, broad_channel);
            channel_weight += w;
        }
        let local_n = c + DIRS[i];
        if (!(boundary == 1u && !inside(local_n, s))) {
            let w = select(1.0, 0.70710678, i >= 4u);
            channel_local += channel_at(local_n, s, boundary) * w;
            channel_local_weight += w;
            height_average += state_at(local_n, s, boundary).x * w;
            height_weight += w;
        }
    }
    channel_average /= max(channel_weight, 1.0);
    channel_local /= max(channel_local_weight, 1.0);
    height_average /= max(height_weight, 1.0);
    let local_profile = sqrt(clamp(channel_local, 0.0, 1.0));
    let broad_profile = sqrt(clamp(channel_average, 0.0, 1.0)) * 0.65 + channel_maximum * 0.35;
    let expanded = max(channel, local_profile * 0.72 + broad_profile * 0.28);
    let valley = mix(channel, expanded, clamp(params.p2.w, 0.0, 1.0));
    let floodplain = sqrt(clamp(max(channel_local, channel_average), 0.0, 1.0));
    let spread = mix(valley, max(valley, floodplain * 0.78), clamp(params.p3.z, 0.0, 1.0) * 0.45);
    let softness = clamp(1.0 - q.z, 0.0, 1.0) * (1.0 - clamp(params.p5.z, 0.0, 1.0));
    let step_scale = max(params.p1.x, 0.0) * max(params.p1.y, 0.0);
    let incision_profile = mix(channel, spread, 0.35 * clamp(params.p2.w, 0.0, 1.0));
    let incision = step_scale * max(params.p1.z, 0.0)
        * pow(max(incision_profile, 0.000001), max(params.p4.y, 0.05))
        * pow(slope + 0.06, max(params.p4.z, 0.05)) * softness;
    let bank_mask = max(spread - channel * 0.30, 0.0);
    let bank_cut = step_scale * max(params.p1.z, 0.0)
        * clamp(params.p3.x, 0.0, 1.0) * bank_mask * (0.20 + 0.80 * slope) * softness;
    var erosion = min(incision + bank_cut, max(params.p1.w, 0.0));
    erosion = min(erosion, max(q.x, 0.0));

    let transport = clamp(params.p5.w, 0.0, 1.0);
    let low_energy = pow(clamp(1.0 - slope, 0.0, 1.0), 1.2 + 3.8 * transport);
    let deposit_field = spread * (1.0 - 0.35 * transport) + max(spread - channel, 0.0) * (0.35 * transport);
    var deposition = step_scale * clamp(params.p3.y, 0.0, 1.0) * deposit_field
        * low_energy * (0.10 + 0.90 * flow) * softness;
    deposition = min(deposition, max(params.p1.w, 0.0) * 0.6);

    var height = clamp(q.x - erosion + deposition, 0.0, 1.0);
    if (params.p4.x > 0.0 && slope > 0.24 && spread > 0.02) {
        let stabilise = clamp(params.p4.x, 0.0, 1.0) * softness * (0.25 + 0.75 * spread);
        height = mix(height, height_average, stabilise);
    }
    if (params.p3.w > 0.0) {
        let preserve = clamp(params.p3.w, 0.0, 1.0) * 0.25 * max(params.p1.x, 0.0);
        height = clamp(height + (q.y - height) * preserve * (1.0 - q.z), 0.0, 1.0);
    }
    textureStore(state_out, c, vec4<f32>(height, q.y, q.z, q.w));
    textureStore(accum_out, c, vec4<f32>(
        min(a.x + max(erosion, 0.0), 1000000.0),
        min(a.y + max(deposition, 0.0), 1000000.0),
        max(a.z, clamp(channel, 0.0, 1.0)),
        max(a.w * 0.98, clamp(flow, 0.0, 1.0))
    ));
}
