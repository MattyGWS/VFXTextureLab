struct Params {
    p0: vec4<f32>,
    p1: vec4<f32>,
    p2: vec4<f32>,
    p3: vec4<f32>,
};

@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

fn wrap_offset(coord: u32, offset: i32, size: u32) -> i32 {
    var wrapped = (i32(coord) + offset) % i32(size);
    if (wrapped < 0) { wrapped = wrapped + i32(size); }
    return wrapped;
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) {
        return;
    }
    let sigma = max(params.p1.x, 0.0);
    let radius = clamp(i32(ceil(sigma * 3.0)), 0, 4096);
    let direction = vec2<i32>(i32(params.p1.y), i32(params.p1.z));
    if (radius <= 0) {
        textureStore(output_tex, vec2<i32>(gid.xy), textureLoad(input_tex, vec2<i32>(gid.xy), 0));
        return;
    }
    let effective_sigma = max(sigma, 0.5);
    let denom = 2.0 * effective_sigma * effective_sigma;
    var sum = vec4<f32>(0.0);
    var weight_sum = 0.0;
    for (var i: i32 = -radius; i <= radius; i = i + 1) {
        var sample_x: i32;
        var sample_y: i32;
        if (params.p1.w >= 0.5) {
            sample_x = clamp(i32(gid.x) + direction.x * i, 0, i32(width) - 1);
            sample_y = clamp(i32(gid.y) + direction.y * i, 0, i32(height) - 1);
        } else {
            sample_x = wrap_offset(gid.x, direction.x * i, width);
            sample_y = wrap_offset(gid.y, direction.y * i, height);
        }
        let fi = f32(i);
        let weight = exp(-(fi * fi) / denom);
        sum = sum + textureLoad(input_tex, vec2<i32>(sample_x, sample_y), 0) * weight;
        weight_sum = weight_sum + weight;
    }
    textureStore(output_tex, vec2<i32>(gid.xy), sum / max(weight_sum, 0.000001));
}
