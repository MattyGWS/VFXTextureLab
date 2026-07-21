struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var ao_tex: texture_2d<f32>;
@group(0) @binding(2) var height_tex: texture_2d<f32>;
@group(0) @binding(3) var output_tex: texture_storage_2d<rgba32float, write>;

fn wrap_coord(value: i32, size: i32) -> i32 {
    return ((value % size) + size) % size;
}

fn resolved_coord(coord: vec2<i32>) -> vec2<i32> {
    let size = vec2<i32>(i32(params.p0.x), i32(params.p0.y));
    if (params.p2.x >= 0.5) {
        return vec2<i32>(wrap_coord(coord.x, size.x), wrap_coord(coord.y, size.y));
    }
    return clamp(coord, vec2<i32>(0), size - vec2<i32>(1));
}

fn sample_channel_i(tex: texture_2d<f32>, coord: vec2<i32>) -> f32 {
    return textureLoad(tex, resolved_coord(coord), 0).r;
}

fn sample_channel_bilinear(tex: texture_2d<f32>, position: vec2<f32>) -> f32 {
    let base_f = floor(position);
    let base = vec2<i32>(base_f);
    let fraction = position - base_f;
    let a = sample_channel_i(tex, base);
    let b = sample_channel_i(tex, base + vec2<i32>(1, 0));
    let c = sample_channel_i(tex, base + vec2<i32>(0, 1));
    let d = sample_channel_i(tex, base + vec2<i32>(1, 1));
    return mix(mix(a, b, fraction.x), mix(c, d, fraction.x), fraction.y);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }

    let p = vec2<i32>(i32(gid.x), i32(gid.y));
    let center_position = vec2<f32>(p);
    let center_height = sample_channel_i(height_tex, p);
    let sigma = max(params.p1.x, 0.01);
    let direction = vec2<f32>(params.p1.y, params.p1.z);
    let height_sigma = max(params.p1.w, 0.0001);
    let spacing = max(sigma * 0.65, 0.75);
    let denom = 2.0 * sigma * sigma;
    let height_denom = 2.0 * height_sigma * height_sigma;

    var sum = 0.0;
    var weight_sum = 0.0;
    for (var tap = -4; tap <= 4; tap = tap + 1) {
        let distance = f32(tap) * spacing;
        let sample_position = center_position + direction * distance;
        let sample_ao = sample_channel_bilinear(ao_tex, sample_position);
        let sample_height = sample_channel_bilinear(height_tex, sample_position);
        let spatial_weight = exp(-(distance * distance) / denom);
        let height_delta = sample_height - center_height;
        let range_weight = exp(-(height_delta * height_delta) / height_denom);
        let weight = spatial_weight * range_weight;
        sum = sum + sample_ao * weight;
        weight_sum = weight_sum + weight;
    }

    let value = clamp(sum / max(weight_sum, 0.000001), 0.0, 1.0);
    textureStore(output_tex, p, vec4<f32>(value, value, value, 1.0));
}
