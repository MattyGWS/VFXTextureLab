struct Params {
    p0: vec4<f32>,
    p1: vec4<f32>,
    p2: vec4<f32>,
    p3: vec4<f32>,
};

@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var output_tex: texture_storage_2d<rgba32float, write>;

fn fade(t: f32) -> f32 {
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0);
}

fn hash2(p: vec2<u32>, seed: u32) -> f32 {
    var h = p.x * 374761393u + p.y * 668265263u + seed * 2246822519u;
    h = (h ^ (h >> 13u)) * 1274126177u;
    h = h ^ (h >> 16u);
    return f32(h & 0x00ffffffu) / 16777215.0;
}

fn periodic_value_noise(uv: vec2<f32>, cells: vec2<u32>, seed: u32) -> f32 {
    let cell_count = max(cells, vec2<u32>(1u, 1u));
    let p = uv * vec2<f32>(cell_count);
    let base = vec2<i32>(floor(p));
    let frac = p - floor(p);
    let t = vec2<f32>(fade(frac.x), fade(frac.y));

    let x0 = u32((base.x % i32(cell_count.x) + i32(cell_count.x)) % i32(cell_count.x));
    let y0 = u32((base.y % i32(cell_count.y) + i32(cell_count.y)) % i32(cell_count.y));
    let x1 = (x0 + 1u) % cell_count.x;
    let y1 = (y0 + 1u) % cell_count.y;

    let a = hash2(vec2<u32>(x0, y0), seed);
    let b = hash2(vec2<u32>(x1, y0), seed);
    let c = hash2(vec2<u32>(x0, y1), seed);
    let d = hash2(vec2<u32>(x1, y1), seed);
    return mix(mix(a, b, t.x), mix(c, d, t.x), t.y);
}

fn periodic_value_noise_3d(
    uv: vec2<f32>, cells: vec2<u32>, seed: u32, z: f32, period: u32
) -> f32 {
    let safe_period = max(period, 1u);
    let z_floor = i32(floor(z));
    let z0 = u32((z_floor % i32(safe_period) + i32(safe_period)) % i32(safe_period));
    let z1 = (z0 + 1u) % safe_period;
    let tz = fade(fract(z));
    let a = periodic_value_noise(uv, cells, seed + z0 * 7919u);
    let b = periodic_value_noise(uv, cells, seed + z1 * 7919u);
    return mix(a, b, tz);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) {
        return;
    }

    let scale = max(params.p1.x, 0.5);
    let octave_count = clamp(u32(params.p1.y), 1u, 8u);
    let persistence = clamp(params.p1.z, 0.0, 1.0);
    let contrast = max(params.p1.w, 0.01);
    let seed = u32(params.p2.x);
    let evolution = params.p2.y;
    let evolution_period = max(u32(params.p2.z), 1u);
    let uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5, 0.5)) / vec2<f32>(f32(width), f32(height));
    let aspect = f32(height) / max(f32(width), 1.0);

    var total = 0.0;
    var amplitude = 1.0;
    var amplitude_sum = 0.0;
    var frequency = scale;
    var octave_multiplier = 1u;
    for (var octave: u32 = 0u; octave < 8u; octave = octave + 1u) {
        if (octave >= octave_count) {
            break;
        }
        let cells_x = max(u32(round(frequency)), 1u);
        let cells_y = max(u32(round(frequency * aspect)), 1u);
        let z = evolution * f32(evolution_period) * f32(octave_multiplier);
        let z_period = evolution_period * octave_multiplier;
        total = total + periodic_value_noise_3d(
            uv,
            vec2<u32>(cells_x, cells_y),
            seed + octave * 1013u,
            z,
            z_period,
        ) * amplitude;
        amplitude_sum = amplitude_sum + amplitude;
        amplitude = amplitude * persistence;
        frequency = frequency * 2.0;
        octave_multiplier = octave_multiplier * 2u;
    }

    total = total / max(amplitude_sum, 0.000001);
    total = clamp((total - 0.5) * contrast + 0.5, 0.0, 1.0);
    textureStore(output_tex, vec2<i32>(gid.xy), vec4<f32>(total, total, total, 1.0));
}
