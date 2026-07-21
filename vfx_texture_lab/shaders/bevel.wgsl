struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var seed_tex: texture_2d<f32>;
@group(0) @binding(3) var output_tex: texture_storage_2d<rgba32float, write>;

fn seed_distance(pixel: vec2<f32>, seed: vec2<f32>, dimensions: vec2<f32>, wrap: bool, fallback: f32) -> f32 {
    if (seed.x < 0.0 || seed.y < 0.0) { return fallback; }
    var delta = abs(seed - pixel);
    if (wrap) { delta = min(delta, dimensions - delta); }
    return max(length(delta) - 0.5, 0.0);
}

fn bevel_curve(value: f32, profile: i32) -> f32 {
    let t = clamp(value, 0.0, 1.0);
    if (profile == 1) { return t * t * (3.0 - 2.0 * t); }
    if (profile == 2) { return sqrt(clamp(1.0 - (1.0 - t) * (1.0 - t), 0.0, 1.0)); }
    if (profile == 3) { return t * t; }
    if (profile == 4) { return 1.0 - (1.0 - t) * (1.0 - t); }
    return t;
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let coord = vec2<i32>(gid.xy);
    let pixel = vec2<f32>(gid.xy);
    let dimensions = vec2<f32>(f32(width), f32(height));
    let bevel_width = max(params.p1.x, 0.00001);
    let offset = params.p1.y;
    let height_value = params.p1.z;
    let background = params.p1.w;
    let direction = i32(params.p2.x + 0.5);
    let profile = i32(params.p2.y + 0.5);
    let smoothing = clamp(params.p2.z, 0.0, 1.0);
    let threshold = params.p2.w;
    var inside = textureLoad(input_tex, coord, 0).r >= threshold;
    if (params.p3.x >= 0.5) { inside = !inside; }
    let wrap = params.p3.y >= 0.5;
    let seeds = textureLoad(seed_tex, coord, 0);
    let fallback = bevel_width + abs(offset) + 0.5;
    let distance_to_inside = seed_distance(pixel, seeds.rg, dimensions, wrap, fallback);
    let distance_to_outside = seed_distance(pixel, seeds.ba, dimensions, wrap, fallback);
    let signed_distance = select(-distance_to_inside, distance_to_outside, inside) + offset;
    var factor: f32;
    if (direction == 1) {
        factor = clamp(1.0 + signed_distance / bevel_width, 0.0, 1.0);
    } else if (direction == 2) {
        factor = clamp(0.5 + signed_distance / bevel_width, 0.0, 1.0);
    } else if (direction == 3) {
        factor = clamp(1.0 - abs(signed_distance) / bevel_width, 0.0, 1.0);
    } else {
        factor = clamp(signed_distance / bevel_width, 0.0, 1.0);
    }
    factor = bevel_curve(factor, profile);
    let smooth_factor = factor * factor * (3.0 - 2.0 * factor);
    factor = mix(factor, smooth_factor, smoothing);
    var value = mix(background, height_value, factor);
    if (params.p3.z >= 0.5) { value = 1.0 - value; }
    if (params.p3.w >= 0.5) { value = clamp(value, 0.0, 1.0); }
    textureStore(output_tex, coord, vec4<f32>(value, value, value, 1.0));
}
