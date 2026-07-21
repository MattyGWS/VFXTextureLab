struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var height_tex: texture_2d<f32>;
@group(0) @binding(2) var mask_tex: texture_2d<f32>;
@group(0) @binding(3) var variation_tex: texture_2d<f32>;
@group(0) @binding(4) var output_tex: texture_storage_2d<rgba32float, write>;

fn hash_u32(value: u32) -> u32 {
    var v = value;
    v = v ^ (v >> 16u);
    v = v * 0x7feb352du;
    v = v ^ (v >> 15u);
    v = v * 0x846ca68bu;
    v = v ^ (v >> 16u);
    return v;
}

fn hash01(index: u32, seed: u32) -> f32 {
    let key = index * 0x9e3779b9u ^ seed * 0x85ebca6bu;
    return f32(hash_u32(key)) / 4294967295.0;
}

fn hash2(ix: u32, iy: u32, seed: u32) -> f32 {
    let key = ix * 0x9e3779b9u ^ iy * 0x85ebca6bu ^ seed;
    return f32(hash_u32(key)) / 4294967295.0;
}

fn interval_weight(index: u32, count: u32, variation: f32, distribution: f32, seed: u32) -> f32 {
    let position = (f32(index) + 0.5) / max(f32(count), 1.0);
    let trend = exp2(clamp(distribution, -1.0, 1.0) * (position * 2.0 - 1.0));
    let jitter = 1.0 + (hash01(index, seed) * 2.0 - 1.0) * clamp(variation, 0.0, 1.0) * 0.9;
    return max(trend * jitter, 0.08);
}

fn breakup_noise(coord: vec2<u32>, size: vec2<u32>, scale: f32, seed: u32) -> f32 {
    let cells = max(u32(round(max(scale, 1.0))), 1u);
    let uv = (vec2<f32>(coord) + vec2<f32>(0.5)) / vec2<f32>(max(size, vec2<u32>(1u)));
    let p = uv * f32(cells);
    let cell = vec2<i32>(floor(p));
    let frac = fract(p);
    let blend = frac * frac * (vec2<f32>(3.0) - 2.0 * frac);
    let cell_count = i32(cells);
    let x0 = u32((cell.x % cell_count + cell_count) % cell_count);
    let y0 = u32((cell.y % cell_count + cell_count) % cell_count);
    let x1 = (x0 + 1u) % cells;
    let y1 = (y0 + 1u) % cells;
    let a = hash2(x0, y0, seed);
    let b = hash2(x1, y0, seed);
    let c = hash2(x0, y1, seed);
    let d = hash2(x1, y1, seed);
    let top = mix(a, b, blend.x);
    let bottom = mix(c, d, blend.x);
    return mix(top, bottom, blend.y);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }

    let coord = vec2<i32>(gid.xy);
    let source = clamp(textureLoad(height_tex, coord, 0).r, 0.0, 1.0);
    var mask = clamp(textureLoad(mask_tex, coord, 0).r, 0.0, 1.0);
    if (params.p3.w >= 0.5) { mask = 1.0 - mask; }
    let variation_map = clamp(textureLoad(variation_tex, coord, 0).r, 0.0, 1.0);

    let steps = max(u32(round(params.p1.x)), 2u);
    let interval_count = steps - 1u;
    let spacing_variation = clamp(params.p1.z, 0.0, 1.0);
    let distribution = clamp(params.p1.w, -1.0, 1.0);
    let seed = u32(max(round(params.p2.w), 0.0));

    var total_weight = 0.0;
    for (var index = 0u; index < 127u; index = index + 1u) {
        if (index >= interval_count) { break; }
        total_weight = total_weight + interval_weight(index, interval_count, spacing_variation, distribution, seed);
    }
    total_weight = max(total_weight, 0.000001);

    let procedural = breakup_noise(gid.xy, vec2<u32>(width, height), params.p3.y, seed);
    let phase_shift =
        (procedural * 2.0 - 1.0) * clamp(params.p3.x, 0.0, 1.5)
        + (variation_map * 2.0 - 1.0) * clamp(params.p3.z, 0.0, 2.0);
    let sample_height = clamp(
        source + (params.p1.y + phase_shift) / max(f32(interval_count), 1.0),
        0.0,
        1.0
    );

    var lower = 0.0;
    var upper = 1.0;
    var cumulative = 0.0;
    for (var index = 0u; index < 127u; index = index + 1u) {
        if (index >= interval_count) { break; }
        let next = cumulative + interval_weight(index, interval_count, spacing_variation, distribution, seed) / total_weight;
        if (sample_height <= next || index + 1u == interval_count) {
            lower = cumulative;
            upper = next;
            break;
        }
        cumulative = next;
    }

    let local_height = clamp((sample_height - lower) / max(upper - lower, 0.000001), 0.0, 1.0);
    let smoothness = clamp(params.p2.x, 0.0, 1.0);
    var edge_profile = 0.0;
    if (smoothness > 0.000001) {
        edge_profile = smoothstep(1.0 - smoothness, 1.0, local_height);
    }
    let plateau_slope = clamp(params.p2.y, 0.0, 1.0);
    let profile = mix(edge_profile, local_height, plateau_slope);
    let terraced = clamp(lower + (upper - lower) * profile, 0.0, 1.0);
    let influence = clamp(params.p2.z, 0.0, 1.0) * mask;
    let value = mix(source, terraced, influence);
    textureStore(output_tex, coord, vec4<f32>(value, value, value, 1.0));
}
