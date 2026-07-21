struct Params {
    p0: vec4<f32>,
    p1: vec4<f32>,
    p2: vec4<f32>,
    p3: vec4<f32>,
    p4: vec4<f32>,
};
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var output_tex: texture_storage_2d<rgba32float, write>;

// @include <noise/common.wgsl>

fn gaussian_lattice(cell: vec3<u32>, seed: u32, mean: f32, deviation: f32) -> f32 {
    let first = max(noise_hash31(cell, seed, 0u), 0.0000001);
    let second = noise_hash31(cell, seed, 1u);
    let sample = sqrt(-2.0 * log(first)) * cos(NOISE_TAU * second);
    return clamp(mean + sample * max(deviation, 0.0001), 0.0, 1.0);
}

fn periodic_gaussian(
    uv_in: vec2<f32>, cells_in: vec2<u32>, seed: u32, z: f32, z_period_in: u32,
    mean: f32, deviation: f32, smoothness_in: f32
) -> f32 {
    let cells = max(cells_in, vec2<u32>(1u));
    let z_period = max(z_period_in, 1u);
    let uv = fract(uv_in);
    let p = vec3<f32>(uv * vec2<f32>(cells), z);
    let base = vec3<i32>(floor(p));
    let fraction = fract(p);
    let smoothness = clamp(smoothness_in, 0.0, 1.0);
    let hard = vec3<f32>(
        select(0.0, 1.0, fraction.x >= 0.5),
        select(0.0, 1.0, fraction.y >= 0.5),
        select(0.0, 1.0, fraction.z >= 0.5),
    );
    let soft = vec3<f32>(noise_fade(fraction.x), noise_fade(fraction.y), noise_fade(fraction.z));
    let t = mix(hard, soft, vec3<f32>(smoothness));

    var corner: array<f32, 8>;
    var index: u32 = 0u;
    for (var oz: i32 = 0; oz <= 1; oz = oz + 1) {
        for (var oy: i32 = 0; oy <= 1; oy = oy + 1) {
            for (var ox: i32 = 0; ox <= 1; ox = ox + 1) {
                let cell = vec3<u32>(
                    noise_wrap_i(base.x + ox, i32(cells.x)),
                    noise_wrap_i(base.y + oy, i32(cells.y)),
                    noise_wrap_i(base.z + oz, i32(z_period)),
                );
                corner[index] = gaussian_lattice(cell, seed, mean, deviation);
                index = index + 1u;
            }
        }
    }
    let z0y0 = mix(corner[0], corner[1], t.x);
    let z0y1 = mix(corner[2], corner[3], t.x);
    let z1y0 = mix(corner[4], corner[5], t.x);
    let z1y1 = mix(corner[6], corner[7], t.x);
    return mix(mix(z0y0, z0y1, t.y), mix(z1y0, z1y1, t.y), t.z);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }

    let scale = max(params.p1.x, 1.0);
    let seed = u32(max(params.p1.y, 0.0));
    let mean = params.p1.z;
    let deviation = max(params.p1.w, 0.0001);
    let smoothness = clamp(params.p2.x, 0.0, 1.0);
    let detail = clamp(params.p2.y, 0.0, 1.0);
    let disorder = params.p2.z;
    let disorder_scale = max(params.p2.w, 1.0);
    let evolution = params.p3.x;
    let loop_cycles = max(params.p3.y, 0.001);
    let contrast = params.p3.z;
    let balance = params.p3.w;
    let invert = params.p4.x > 0.5;

    var uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / vec2<f32>(f32(width), f32(height));
    uv = noise_domain_warp(uv, f32(width), f32(height), scale, seed, evolution, loop_cycles, disorder, disorder_scale);
    let cells = noise_aspect_cells(scale, f32(width), f32(height));
    let loop_data = noise_loop_z(evolution, loop_cycles);
    let first = periodic_gaussian(uv, cells, seed, loop_data.x, u32(loop_data.y), mean, deviation, smoothness);
    let diagonal_uv = fract(vec2<f32>(uv.x + uv.y, uv.x - uv.y));
    let second = periodic_gaussian(
        diagonal_uv, cells, seed + 1777u, loop_data.x, u32(loop_data.y), mean, deviation, smoothness
    );
    let first_weight = 0.75;
    let second_weight = 0.66;
    let base = mean + ((first - mean) * first_weight + (second - mean) * second_weight)
        / sqrt(first_weight * first_weight + second_weight * second_weight);
    var value = base;
    if (detail > 0.000001) {
        let fine_cells = noise_aspect_cells(scale * 4.0, f32(width), f32(height));
        let fine = periodic_gaussian(
            uv, fine_cells, seed + 3571u, loop_data.x, u32(loop_data.y),
            mean, deviation, smoothness
        );
        let weight = detail * 0.35;
        value = mean + ((base - mean) + (fine - mean) * weight) / sqrt(1.0 + weight * weight);
    }
    value = noise_finish(clamp(value, 0.0, 1.0), contrast, balance, invert);
    textureStore(output_tex, vec2<i32>(gid.xy), vec4<f32>(value, value, value, 1.0));
}
