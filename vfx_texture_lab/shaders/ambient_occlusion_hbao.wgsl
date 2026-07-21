struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var height_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

const TAU: f32 = 6.283185307179586;
const INV_HALF_PI: f32 = 0.6366197723675814;
const GOLDEN_ANGLE: f32 = 2.399963229728653;

fn wrap_coord(value: i32, size: i32) -> i32 {
    return ((value % size) + size) % size;
}

fn resolved_coord(coord: vec2<i32>) -> vec2<i32> {
    let size = vec2<i32>(i32(params.p0.x), i32(params.p0.y));
    if (params.p2.y >= 0.5) {
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

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }

    let p = vec2<i32>(i32(gid.x), i32(gid.y));
    let center = sample_height_i(p);
    let depth = max(params.p1.x, 0.0);
    let radius_pixels = max(params.p1.y, 1.0);
    let direction_count = max(u32(round(params.p1.z)), 1u);
    let strength = max(params.p1.w, 0.0);
    let ring_count = max(u32(round(params.p2.z)), 1u);

    if (depth <= 0.00000001 || params.p1.y <= 0.00000001) {
        let value = select(1.0, 0.0, params.p2.x >= 0.5);
        textureStore(output_tex, p, vec4<f32>(value, value, value, 1.0));
        return;
    }

    // Height change per pixel. The tangent estimate removes broad planar slope
    // so the node responds to nearby blockers rather than darkening a tilted
    // but otherwise flat height field.
    let left = sample_height_i(p + vec2<i32>(-1, 0));
    let right = sample_height_i(p + vec2<i32>(1, 0));
    let up = sample_height_i(p + vec2<i32>(0, -1));
    let down = sample_height_i(p + vec2<i32>(0, 1));
    let grad_x = minmod(center - left, right - center);
    let grad_y = minmod(center - up, down - center);
    let dimensions = vec2<f32>(max(f32(width), 1.0), max(f32(height), 1.0));
    let height_scale = depth * 0.12;

    var occlusion = 0.0;
    var weight_sum = 0.0;

    // Quality selects azimuth samples per ring. Concentric equal-area rings are
    // independently rotated by the golden angle, producing an isotropic disc
    // instead of repeatedly stamping the same visible radial rays.
    for (var ring = 0u; ring < 8u; ring = ring + 1u) {
        if (ring >= ring_count) { break; }
        let ring_fraction = sqrt((f32(ring) + 0.5) / f32(ring_count));
        let distance_pixels = max(radius_pixels * ring_fraction, 0.75);
        let ring_rotation = f32(ring) * GOLDEN_ANGLE;
        let radial_weight = pow(max(1.0 - ring_fraction * ring_fraction, 0.0), 1.5) + 0.15;

        for (var slot = 0u; slot < 16u; slot = slot + 1u) {
            if (slot >= direction_count) { break; }
            let angle = TAU * (f32(slot) + 0.5) / f32(direction_count) + ring_rotation;
            let offset = vec2<f32>(cos(angle), sin(angle)) * distance_pixels;
            let sample_value = sample_height_bilinear(vec2<f32>(p) + offset);
            let tangent_height = center + grad_x * offset.x + grad_y * offset.y;
            let delta = max(sample_value - tangent_height, 0.0);
            let distance_uv = max(length(offset / dimensions), 0.000001);
            let slope = delta * height_scale / (distance_uv + 0.002);
            let angular_occlusion = atan(slope) * INV_HALF_PI;
            occlusion = occlusion + angular_occlusion * radial_weight;
            weight_sum = weight_sum + radial_weight;
        }
    }

    let mean_occlusion = occlusion / max(weight_sum, 0.000001);
    var value = exp(-mean_occlusion * strength * 4.0);
    if (params.p2.x >= 0.5) { value = 1.0 - value; }
    value = clamp(value, 0.0, 1.0);
    textureStore(output_tex, p, vec4<f32>(value, value, value, 1.0));
}
