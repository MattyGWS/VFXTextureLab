struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var height_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

const TAU: f32 = 6.283185307179586;
const GOLDEN_RATIO: f32 = 0.6180339887498949;
const HALF_PI: f32 = 1.5707963267948966;

fn wrap_coord(value: i32, size: i32) -> i32 {
    return ((value % size) + size) % size;
}

fn resolved_coord(coord: vec2<i32>) -> vec2<i32> {
    let size = vec2<i32>(i32(params.p0.x), i32(params.p0.y));
    if (params.p2.z >= 0.5) {
        return vec2<i32>(wrap_coord(coord.x, size.x), wrap_coord(coord.y, size.y));
    }
    return clamp(coord, vec2<i32>(0), size - vec2<i32>(1));
}

fn sample_height_i(coord: vec2<i32>) -> f32 {
    return textureLoad(height_tex, resolved_coord(coord), 0).r;
}

fn sample_height_bilinear(position: vec2<f32>) -> f32 {
    let base_f = floor(position);
    let base = vec2<i32>(base_f);
    let fraction = position - base_f;
    let a = sample_height_i(base);
    let b = sample_height_i(base + vec2<i32>(1, 0));
    let c = sample_height_i(base + vec2<i32>(0, 1));
    let d = sample_height_i(base + vec2<i32>(1, 1));
    return mix(mix(a, b, fraction.x), mix(c, d, fraction.x), fraction.y);
}

fn minmod(a: f32, b: f32) -> f32 {
    if (a * b <= 0.0) { return 0.0; }
    return sign(a) * min(abs(a), abs(b));
}

fn hash_u32(input_value: u32) -> u32 {
    var value = input_value;
    value = value ^ (value >> 16u);
    value = value * 0x7feb352du;
    value = value ^ (value >> 15u);
    value = value * 0x846ca68bu;
    value = value ^ (value >> 16u);
    return value;
}

fn pixel_rotation(p: vec2<u32>) -> f32 {
    let value = hash_u32(p.x + p.y * 0x9e3779b9u);
    return f32(value & 0x00ffffffu) / 16777216.0;
}

fn ray_cosine(ray_fraction: f32, spread: f32, distribution: u32) -> f32 {
    let maximum_angle = clamp(spread, 0.0, 1.0) * HALF_PI;
    let u = clamp(ray_fraction, 0.0, 1.0);
    if (distribution == 1u) {
        let cos_max = cos(maximum_angle);
        return sqrt(max(1.0 - u * (1.0 - cos_max * cos_max), 0.0));
    }
    if (distribution == 2u) {
        return cos(maximum_angle * pow(u, 0.45));
    }
    let cos_max = cos(maximum_angle);
    return 1.0 - u * (1.0 - cos_max);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }

    let p = vec2<i32>(i32(gid.x), i32(gid.y));
    let center = sample_height_i(p);
    let height_scale = max(params.p1.x, 0.0);
    let maximum_distance_pixels = max(params.p1.y, 0.0);
    let ray_count = max(u32(round(params.p1.z)), 1u);
    let spread = clamp(params.p1.w, 0.0, 1.0);
    let distribution = u32(round(params.p2.x));
    let step_count = max(u32(round(params.p2.y)), 1u);
    let invert = params.p2.w >= 0.5;

    if (height_scale <= 0.00000001 || maximum_distance_pixels <= 0.00000001 || spread <= 0.00000001) {
        let value = select(1.0, 0.0, invert);
        textureStore(output_tex, p, vec4<f32>(value, value, value, 1.0));
        return;
    }

    let left = sample_height_i(p + vec2<i32>(-1, 0));
    let right = sample_height_i(p + vec2<i32>(1, 0));
    let up = sample_height_i(p + vec2<i32>(0, -1));
    let down = sample_height_i(p + vec2<i32>(0, 1));
    let grad_x = minmod(center - left, right - center);
    let grad_y = minmod(center - up, down - center);
    let minimum_dimension = max(min(f32(width), f32(height)), 1.0);
    let rotation = pixel_rotation(gid.xy);
    let origin_bias = 0.00025 + height_scale * 0.0005;
    var occlusion = 0.0;

    for (var ray = 0u; ray < 64u; ray = ray + 1u) {
        if (ray >= ray_count) { break; }
        let ray_fraction = (f32(ray) + 0.5) / f32(ray_count);
        let cosine = clamp(ray_cosine(ray_fraction, spread, distribution), 0.0, 1.0);
        let sine = sqrt(max(1.0 - cosine * cosine, 0.0));
        if (sine <= 0.0000001) { continue; }
        let cotangent = cosine / max(sine, 0.000001);
        let angle = TAU * fract(f32(ray) * GOLDEN_RATIO + rotation);
        let direction = vec2<f32>(cos(angle), sin(angle));
        var hit = false;
        var hit_fraction = 1.0;

        for (var step = 0u; step < 22u; step = step + 1u) {
            if (step >= step_count) { break; }
            let linear_fraction = (f32(step) + 1.0) / f32(step_count);
            let fraction = pow(linear_fraction, 1.35);
            let distance_pixels = maximum_distance_pixels * fraction;
            let offset = direction * distance_pixels;
            let sampled_height = sample_height_bilinear(vec2<f32>(p) + offset);
            let tangent_height = center + grad_x * offset.x + grad_y * offset.y;
            let relative_surface = (sampled_height - tangent_height) * height_scale;
            let ray_height = (distance_pixels / minimum_dimension) * cotangent;
            if (relative_surface > ray_height + origin_bias) {
                hit = true;
                hit_fraction = fraction;
                break;
            }
        }

        if (hit) {
            occlusion = occlusion + (1.0 - 0.35 * hit_fraction);
        }
    }

    var value = clamp(1.0 - occlusion / f32(ray_count), 0.0, 1.0);
    if (invert) { value = 1.0 - value; }
    textureStore(output_tex, p, vec4<f32>(value, value, value, 1.0));
}
