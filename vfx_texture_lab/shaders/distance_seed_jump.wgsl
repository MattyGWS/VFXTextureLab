struct Params { p0: vec4<f32>, p1: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var seed_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

fn wrapped_coord(value: i32, size: i32) -> i32 {
    var result = value;
    if (result < 0) { result = result + size; }
    if (result >= size) { result = result - size; }
    return result;
}

fn seed_distance_squared(pixel: vec2<f32>, seed: vec2<f32>, dimensions: vec2<f32>, wrap: bool) -> f32 {
    if (seed.x < 0.0 || seed.y < 0.0) { return 3.402823466e+38; }
    var delta = abs(seed - pixel);
    if (wrap) { delta = min(delta, dimensions - delta); }
    return dot(delta, delta);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = i32(params.p0.x);
    let height = i32(params.p0.y);
    if (i32(gid.x) >= width || i32(gid.y) >= height) { return; }
    let coord = vec2<i32>(gid.xy);
    let pixel = vec2<f32>(gid.xy);
    let dimensions = vec2<f32>(f32(width), f32(height));
    let step = max(i32(params.p1.x + 0.5), 1);
    let wrap = params.p1.y >= 0.5;
    let current = textureLoad(seed_tex, coord, 0);
    var best_foreground = current.rg;
    var best_background = current.ba;
    var foreground_distance = seed_distance_squared(pixel, best_foreground, dimensions, wrap);
    var background_distance = seed_distance_squared(pixel, best_background, dimensions, wrap);

    for (var oy: i32 = -1; oy <= 1; oy = oy + 1) {
        for (var ox: i32 = -1; ox <= 1; ox = ox + 1) {
            if (ox == 0 && oy == 0) { continue; }
            var sample_coord = coord + vec2<i32>(ox * step, oy * step);
            if (wrap) {
                sample_coord = vec2<i32>(wrapped_coord(sample_coord.x, width), wrapped_coord(sample_coord.y, height));
            } else if (sample_coord.x < 0 || sample_coord.y < 0 || sample_coord.x >= width || sample_coord.y >= height) {
                continue;
            }
            let candidate = textureLoad(seed_tex, sample_coord, 0);
            let candidate_foreground_distance = seed_distance_squared(pixel, candidate.rg, dimensions, wrap);
            if (candidate_foreground_distance < foreground_distance) {
                foreground_distance = candidate_foreground_distance;
                best_foreground = candidate.rg;
            }
            let candidate_background_distance = seed_distance_squared(pixel, candidate.ba, dimensions, wrap);
            if (candidate_background_distance < background_distance) {
                background_distance = candidate_background_distance;
                best_background = candidate.ba;
            }
        }
    }
    textureStore(output_tex, coord, vec4<f32>(best_foreground, best_background));
}
