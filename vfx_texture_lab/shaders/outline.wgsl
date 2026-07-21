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

fn soft_step(edge0: f32, edge1: f32, value: f32) -> f32 {
    let t = clamp((value - edge0) / max(edge1 - edge0, 0.00001), 0.0, 1.0);
    return t * t * (3.0 - 2.0 * t);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let coord = vec2<i32>(gid.xy);
    let pixel = vec2<f32>(gid.xy);
    let dimensions = vec2<f32>(f32(width), f32(height));
    let outline_width = max(params.p1.x, 0.00001);
    let offset = params.p1.y;
    let softness = max(params.p1.z, 0.00001);
    let direction = i32(params.p1.w + 0.5); // 0 inner, 1 outer, 2 centred
    let threshold = params.p2.x;
    var inside = textureLoad(input_tex, coord, 0).r >= threshold;
    if (params.p2.y >= 0.5) { inside = !inside; }
    let wrap = params.p2.z >= 0.5;
    let seeds = textureLoad(seed_tex, coord, 0);
    let fallback = outline_width + abs(offset) + softness + 2.0;
    let distance_to_inside = seed_distance(pixel, seeds.rg, dimensions, wrap, fallback);
    let distance_to_outside = seed_distance(pixel, seeds.ba, dimensions, wrap, fallback);
    let signed_distance = select(-distance_to_inside, distance_to_outside, inside) + offset;
    var value: f32;
    if (direction == 0) {
        let near_edge = soft_step(-softness, softness, signed_distance);
        let beyond = soft_step(outline_width - softness, outline_width + softness, signed_distance);
        value = near_edge * (1.0 - beyond);
    } else if (direction == 1) {
        let outside_distance = -signed_distance;
        let near_edge = soft_step(-softness, softness, outside_distance);
        let beyond = soft_step(outline_width - softness, outline_width + softness, outside_distance);
        value = near_edge * (1.0 - beyond);
    } else {
        let half_width = outline_width * 0.5;
        value = 1.0 - soft_step(half_width - softness, half_width + softness, abs(signed_distance));
    }
    if (params.p2.w >= 0.5) { value = 1.0 - value; }
    value = clamp(value, 0.0, 1.0);
    textureStore(output_tex, coord, vec4<f32>(value, value, value, 1.0));
}
