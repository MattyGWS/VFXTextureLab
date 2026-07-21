const NOISE_PI: f32 = 3.14159265358979323846;
const NOISE_TAU: f32 = 6.28318530717958647692;

fn noise_fade(t: f32) -> f32 {
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0);
}

fn noise_hash_u32(value_in: u32) -> u32 {
    var value = value_in;
    value = value ^ (value >> 16u);
    value = value * 0x7feb352du;
    value = value ^ (value >> 15u);
    value = value * 0x846ca68bu;
    value = value ^ (value >> 16u);
    return value;
}

fn noise_hash3(cell: vec3<u32>, seed: u32, salt: u32) -> u32 {
    let value = cell.x * 0x9e3779b1u
        ^ cell.y * 0x85ebca77u
        ^ cell.z * 0xc2b2ae3du
        ^ seed * 0x27d4eb2fu
        ^ salt * 0x165667b1u;
    return noise_hash_u32(value);
}

fn noise_hash01(value: u32) -> f32 {
    return f32(value & 0x00ffffffu) / 16777215.0;
}

fn noise_hash31(cell: vec3<u32>, seed: u32, salt: u32) -> f32 {
    return noise_hash01(noise_hash3(cell, seed, salt));
}

fn noise_hash4(cell: vec4<u32>, seed: u32, salt: u32) -> u32 {
    let value = cell.x * 0x9e3779b1u
        ^ cell.y * 0x85ebca77u
        ^ cell.z * 0xc2b2ae3du
        ^ cell.w * 0x27d4eb2fu
        ^ seed * 0x165667b1u
        ^ salt * 0xd3a2646cu;
    return noise_hash_u32(value);
}

fn noise_hash41(cell: vec4<u32>, seed: u32, salt: u32) -> f32 {
    return noise_hash01(noise_hash4(cell, seed, salt));
}

fn noise_gradient4(cell: vec4<u32>, seed: u32) -> vec4<f32> {
    var value = vec4<f32>(
        noise_hash41(cell, seed, 0u),
        noise_hash41(cell, seed, 1u),
        noise_hash41(cell, seed, 2u),
        noise_hash41(cell, seed, 3u),
    ) * 2.0 - vec4<f32>(1.0);
    let magnitude = max(length(value), 0.000001);
    return value / magnitude;
}

fn noise_gradient4_value(point: vec4<f32>, seed: u32) -> f32 {
    let base = vec4<i32>(floor(point));
    let fraction = fract(point);
    let t = vec4<f32>(
        noise_fade(fraction.x), noise_fade(fraction.y),
        noise_fade(fraction.z), noise_fade(fraction.w)
    );
    var corner: array<f32, 16>;
    var index: u32 = 0u;
    for (var ow: i32 = 0; ow <= 1; ow = ow + 1) {
        for (var oz: i32 = 0; oz <= 1; oz = oz + 1) {
            for (var oy: i32 = 0; oy <= 1; oy = oy + 1) {
                for (var ox: i32 = 0; ox <= 1; ox = ox + 1) {
                    let lattice_i = base + vec4<i32>(ox, oy, oz, ow);
                    let lattice = bitcast<vec4<u32>>(lattice_i);
                    let gradient = noise_gradient4(lattice, seed);
                    let delta = fraction - vec4<f32>(f32(ox), f32(oy), f32(oz), f32(ow));
                    corner[index] = dot(gradient, delta);
                    index = index + 1u;
                }
            }
        }
    }
    var y_mix: array<f32, 8>;
    for (var i: u32 = 0u; i < 8u; i = i + 1u) {
        y_mix[i] = mix(corner[i * 2u], corner[i * 2u + 1u], t.x);
    }
    var z_mix: array<f32, 4>;
    for (var i: u32 = 0u; i < 4u; i = i + 1u) {
        z_mix[i] = mix(y_mix[i * 2u], y_mix[i * 2u + 1u], t.y);
    }
    var w_mix: array<f32, 2>;
    for (var i: u32 = 0u; i < 2u; i = i + 1u) {
        w_mix[i] = mix(z_mix[i * 2u], z_mix[i * 2u + 1u], t.z);
    }
    let signed_value = mix(w_mix[0], w_mix[1], t.w);
    return clamp(0.5 + signed_value * 0.95, 0.0, 1.0);
}

fn noise_gradient3(cell: vec3<u32>, seed: u32) -> vec3<f32> {
    let h1 = noise_hash31(cell, seed, 0u);
    let h2 = noise_hash31(cell, seed, 1u);
    let z = h1 * 2.0 - 1.0;
    let angle = h2 * NOISE_TAU;
    let radial = sqrt(max(1.0 - z * z, 0.0));
    return vec3<f32>(cos(angle) * radial, sin(angle) * radial, z);
}

fn noise_wrap_i(value: i32, period: i32) -> u32 {
    let safe_period = max(period, 1);
    return u32((value % safe_period + safe_period) % safe_period);
}

fn noise_periodic_value3(
    uv_in: vec2<f32>, cells_in: vec2<u32>, seed: u32, z: f32, z_period_in: u32
) -> f32 {
    let cells = max(cells_in, vec2<u32>(1u));
    let z_period = max(z_period_in, 1u);
    let uv = fract(uv_in);
    let p = vec3<f32>(uv * vec2<f32>(cells), z);
    let base = vec3<i32>(floor(p));
    let fraction = fract(p);
    let t = vec3<f32>(noise_fade(fraction.x), noise_fade(fraction.y), noise_fade(fraction.z));
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
                corner[index] = noise_hash31(cell, seed, 0u);
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

fn noise_periodic_gradient3(
    uv_in: vec2<f32>, cells_in: vec2<u32>, seed: u32, z: f32, z_period_in: u32
) -> f32 {
    let cells = max(cells_in, vec2<u32>(1u));
    let z_period = max(z_period_in, 1u);
    let uv = fract(uv_in);
    let p = vec3<f32>(uv * vec2<f32>(cells), z);
    let base = vec3<i32>(floor(p));
    let fraction = fract(p);
    let t = vec3<f32>(noise_fade(fraction.x), noise_fade(fraction.y), noise_fade(fraction.z));
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
                let gradient = noise_gradient3(cell, seed);
                let delta = fraction - vec3<f32>(f32(ox), f32(oy), f32(oz));
                corner[index] = dot(gradient, delta);
                index = index + 1u;
            }
        }
    }
    let z0y0 = mix(corner[0], corner[1], t.x);
    let z0y1 = mix(corner[2], corner[3], t.x);
    let z1y0 = mix(corner[4], corner[5], t.x);
    let z1y1 = mix(corner[6], corner[7], t.x);
    let signed_value = mix(mix(z0y0, z0y1, t.y), mix(z1y0, z1y1, t.y), t.z);
    return clamp(0.5 + signed_value * 0.86, 0.0, 1.0);
}

fn noise_aspect_cells(scale: f32, width: f32, height: f32) -> vec2<u32> {
    let x = max(u32(round(max(scale, 1.0))), 1u);
    let y = max(u32(round(max(scale, 1.0) * height / max(width, 1.0))), 1u);
    return vec2<u32>(x, y);
}

fn noise_evolution_phase(value: f32) -> f32 {
    if (value >= 0.0 && value <= 1.0) {
        return value;
    }
    return fract(value);
}

fn noise_loop_period() -> u32 {
    // Four temporal lattice cells keep a 0..1 loop organic without racing
    // through sixteen unrelated states. Loop Cycles controls repetitions.
    return 4u;
}

fn noise_loop_z(evolution: f32, cycles: f32) -> vec2<f32> {
    let period = f32(noise_loop_period());
    let phase = noise_evolution_phase(evolution);
    return vec2<f32>(phase * period * max(cycles, 0.001), period);
}

fn noise_domain_warp(
    uv: vec2<f32>, width: f32, height: f32, scale: f32, seed: u32,
    evolution: f32, cycles: f32, amount: f32, disorder_scale: f32
) -> vec2<f32> {
    if (abs(amount) <= 0.000001) {
        return fract(uv);
    }
    let cells = noise_aspect_cells(max(disorder_scale, 1.0), width, height);
    let loop_data = noise_loop_z(evolution, cycles);
    let z_period = u32(loop_data.y);
    let x = noise_periodic_gradient3(uv, cells, seed + 181u, loop_data.x, z_period) * 2.0 - 1.0;
    let y = noise_periodic_gradient3(uv, cells, seed + 347u, loop_data.x, z_period) * 2.0 - 1.0;
    let strength = amount * 0.16 / max(sqrt(max(scale, 1.0)), 1.0);
    return fract(uv + vec2<f32>(x, y) * strength);
}

fn noise_finish(value: f32, contrast: f32, balance: f32, invert: bool) -> f32 {
    var result = clamp((value - 0.5) * max(contrast, 0.001) + 0.5 + balance * 0.5, 0.0, 1.0);
    if (invert) {
        result = 1.0 - result;
    }
    return result;
}

fn noise_metric(delta: vec2<f32>, mode: i32, exponent: f32) -> f32 {
    let value = abs(delta);
    if (mode == 1) {
        return value.x + value.y;
    }
    if (mode == 2) {
        return max(value.x, value.y);
    }
    if (mode == 3) {
        let p = max(exponent, 0.25);
        return pow(pow(value.x, p) + pow(value.y, p), 1.0 / p);
    }
    return length(delta);
}

struct NoiseCellularResult {
    f1: f32,
    f2: f32,
    cell_value: f32,
};

fn noise_cellular(
    uv_in: vec2<f32>, cells_in: vec2<u32>, seed: u32, jitter: f32,
    evolution: f32, loop_cycles: f32, metric_mode: i32, exponent: f32,
    points_per_cell_in: u32
) -> NoiseCellularResult {
    let cells = max(cells_in, vec2<u32>(1u));
    let uv = fract(uv_in);
    let point = uv * vec2<f32>(cells);
    let base = vec2<i32>(floor(point));
    let phase = NOISE_TAU * noise_evolution_phase(evolution) * loop_cycles;
    let points_per_cell = clamp(points_per_cell_in, 1u, 3u);
    var f1 = 1e9;
    var f2 = 1e9;
    var nearest_value = 0.0;
    for (var oy: i32 = -1; oy <= 1; oy = oy + 1) {
        for (var ox: i32 = -1; ox <= 1; ox = ox + 1) {
            let neighbour = base + vec2<i32>(ox, oy);
            let wrapped = vec2<u32>(
                noise_wrap_i(neighbour.x, i32(cells.x)),
                noise_wrap_i(neighbour.y, i32(cells.y)),
            );
            for (var point_index: u32 = 0u; point_index < 3u; point_index = point_index + 1u) {
                if (point_index >= points_per_cell) {
                    break;
                }
                let cell3 = vec3<u32>(wrapped, point_index);
                let angle_hash = noise_hash31(cell3, seed, 3u);
                let radius_hash = noise_hash31(cell3, seed, 4u);
                let angle = angle_hash * NOISE_TAU + phase;
                let radius = clamp(jitter, 0.0, 1.0) * 0.48 * (0.35 + 0.65 * radius_hash);
                let feature = vec2<f32>(neighbour) + vec2<f32>(0.5) + vec2<f32>(cos(angle), sin(angle)) * radius;
                let distance = noise_metric(feature - point, metric_mode, exponent);
                if (distance < f1) {
                    f2 = f1;
                    f1 = distance;
                    nearest_value = noise_hash31(cell3, seed, 5u);
                } else if (distance < f2) {
                    f2 = distance;
                }
            }
        }
    }
    return NoiseCellularResult(f1, f2, nearest_value);
}

fn noise_simplex2(point: vec2<f32>, seed: u32) -> f32 {
    let f2 = 0.3660254037844386;
    let g2 = 0.21132486540518713;
    let skew = (point.x + point.y) * f2;
    let cell = vec2<i32>(floor(point + vec2<f32>(skew)));
    let unskew = f32(cell.x + cell.y) * g2;
    let p0 = point - (vec2<f32>(cell) - vec2<f32>(unskew));
    let offset1 = select(vec2<i32>(0, 1), vec2<i32>(1, 0), p0.x > p0.y);
    let p1 = p0 - vec2<f32>(offset1) + vec2<f32>(g2);
    let p2 = p0 - vec2<f32>(1.0) + vec2<f32>(2.0 * g2);

    var total = 0.0;
    var t0 = max(0.5 - dot(p0, p0), 0.0);
    let h0 = noise_hash31(vec3<u32>(bitcast<vec2<u32>>(cell), 0u), seed, 0u);
    let g0 = vec2<f32>(cos(h0 * NOISE_TAU), sin(h0 * NOISE_TAU));
    total = total + t0 * t0 * t0 * t0 * dot(g0, p0);

    var t1 = max(0.5 - dot(p1, p1), 0.0);
    let cell1 = cell + offset1;
    let h1 = noise_hash31(vec3<u32>(bitcast<vec2<u32>>(cell1), 0u), seed, 1u);
    let g1 = vec2<f32>(cos(h1 * NOISE_TAU), sin(h1 * NOISE_TAU));
    total = total + t1 * t1 * t1 * t1 * dot(g1, p1);

    var t2 = max(0.5 - dot(p2, p2), 0.0);
    let cell2 = cell + vec2<i32>(1);
    let h2 = noise_hash31(vec3<u32>(bitcast<vec2<u32>>(cell2), 0u), seed, 2u);
    let g2v = vec2<f32>(cos(h2 * NOISE_TAU), sin(h2 * NOISE_TAU));
    total = total + t2 * t2 * t2 * t2 * dot(g2v, p2);
    return clamp(0.5 + 35.0 * total, 0.0, 1.0);
}
