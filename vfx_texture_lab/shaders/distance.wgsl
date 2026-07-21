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

fn smooth_profile(value: f32, amount: f32) -> f32 {
    let smooth_value = value * value * (3.0 - 2.0 * value);
    return mix(value, smooth_value, clamp(amount, 0.0, 1.0));
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let coord = vec2<i32>(gid.xy);
    let pixel = vec2<f32>(gid.xy);
    let dimensions = vec2<f32>(f32(width), f32(height));
    let limit = max(params.p1.x, 0.00001);
    let offset = params.p1.y;
    let exponent = max(params.p1.z, 0.0001);
    let smoothing = params.p1.w;
    let mode = i32(params.p2.x + 0.5);
    let threshold = params.p2.y;
    var inside = textureLoad(input_tex, coord, 0).r >= threshold;
    if (params.p2.z >= 0.5) { inside = !inside; }
    let wrap = params.p2.w >= 0.5;
    let seeds = textureLoad(seed_tex, coord, 0);
    let fallback = limit + abs(offset) + 0.5;
    let distance_to_inside = seed_distance(pixel, seeds.rg, dimensions, wrap, fallback);
    let distance_to_outside = seed_distance(pixel, seeds.ba, dimensions, wrap, fallback);
    let signed_distance = select(-distance_to_inside, distance_to_outside, inside) + offset;
    var value: f32;
    if (mode == 1) {
        value = pow(clamp(-signed_distance / limit, 0.0, 1.0), exponent);
    } else if (mode == 2) {
        let normalised = clamp(signed_distance / limit, -1.0, 1.0);
        let shaped = sign(normalised) * pow(abs(normalised), exponent);
        value = shaped * 0.5 + 0.5;
    } else if (mode == 3) {
        value = pow(clamp(abs(signed_distance) / limit, 0.0, 1.0), exponent);
    } else {
        value = pow(clamp(signed_distance / limit, 0.0, 1.0), exponent);
    }
    value = smooth_profile(value, smoothing);
    if (params.p3.x >= 0.5) { value = 1.0 - value; }
    value = clamp(value, 0.0, 1.0);
    textureStore(output_tex, coord, vec4<f32>(value, value, value, 1.0));
}
