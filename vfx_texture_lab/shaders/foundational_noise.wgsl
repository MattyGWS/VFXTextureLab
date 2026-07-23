struct Params {
    p0: vec4<f32>,
    p1: vec4<f32>,
    p2: vec4<f32>,
    p3: vec4<f32>,
    p4: vec4<f32>,
    p5: vec4<f32>,
    p6: vec4<f32>,
};
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var output_tex: texture_storage_2d<rgba32float, write>;

// @include <noise/common.wgsl>

fn smooth_range(edge0: f32, edge1: f32, value: f32) -> f32 {
    let denominator = select(edge1 - edge0, 0.0000001, abs(edge1 - edge0) < 0.0000001);
    let t = clamp((value - edge0) / denominator, 0.0, 1.0);
    return t * t * (3.0 - 2.0 * t);
}

fn directional_disorder(
    uv: vec2<f32>, width: f32, height: f32, scale: f32, seed: u32,
    evolution: f32, cycles: f32, amount: f32, disorder_scale: f32,
    anisotropy: f32, angle_degrees: f32
) -> vec2<f32> {
    if (abs(amount) <= 0.0000001) { return fract(uv); }
    let cells = noise_aspect_cells(max(disorder_scale, 1.0), width, height);
    let loop_data = noise_loop_z(evolution, cycles);
    let first = noise_periodic_gradient3(uv, cells, seed + 411u, loop_data.x, u32(loop_data.y)) * 2.0 - 1.0;
    let second = noise_periodic_gradient3(uv, cells, seed + 977u, loop_data.x, u32(loop_data.y)) * 2.0 - 1.0;
    let angle = radians(angle_degrees);
    let direction = vec2<f32>(cos(angle), sin(angle));
    let a = clamp(anisotropy, 0.0, 1.0);
    let isotropic = vec2<f32>(first, second);
    let directional = direction * first;
    let displacement = mix(isotropic, directional, a);
    let strength = amount * 0.16 / max(sqrt(max(scale, 1.0)), 1.0);
    return fract(uv + displacement * strength);
}

fn cloud_disorder(
    uv: vec2<f32>, width: f32, height: f32, scale: f32, seed: u32,
    evolution: f32, cycles: f32, amount: f32, disorder_scale: f32,
    anisotropy: f32, angle_degrees: f32
) -> vec2<f32> {
    if (abs(amount) <= 0.0000001) { return fract(uv); }
    let cells = noise_aspect_cells(max(disorder_scale, 1.0), width, height);
    let loop_data = noise_loop_z(evolution, cycles);
    let first = noise_periodic_value3(uv, cells, seed + 411u, loop_data.x, u32(loop_data.y)) * 2.0 - 1.0;
    let second = noise_periodic_value3(uv, cells, seed + 977u, loop_data.x, u32(loop_data.y)) * 2.0 - 1.0;
    let angle = radians(angle_degrees);
    let direction = vec2<f32>(cos(angle), sin(angle));
    let a = clamp(anisotropy, 0.0, 1.0);
    let isotropic = vec2<f32>(first, second);
    let directional = direction * first;
    let displacement = mix(isotropic, directional, a);
    let strength = amount * 0.08 / max(sqrt(max(scale, 1.0)), 1.0);
    return fract(uv + displacement * strength);
}

fn fractal_field(
    uv: vec2<f32>, width: f32, height: f32, scale: f32, octave_count_in: u32,
    roughness: f32, seed: u32, evolution: f32, cycles: f32, mode: u32,
    lacunarity: f32
) -> f32 {
    let octave_count = clamp(octave_count_in, 1u, 10u);
    let loop_data = noise_loop_z(evolution, cycles);
    var total = 0.0;
    var weight_sum = 0.0;
    var amplitude = 1.0;
    var frequency = max(scale, 1.0);
    for (var octave: u32 = 0u; octave < 10u; octave = octave + 1u) {
        if (octave >= octave_count) { break; }
        let cells = noise_aspect_cells(frequency, width, height);
        let base = noise_periodic_gradient3(uv, cells, seed + octave * 1301u, loop_data.x, u32(loop_data.y));
        let signed_value = base * 2.0 - 1.0;
        var sample = base;
        if (mode == 1u) {
            sample = 1.0 - abs(signed_value);
        } else if (mode == 2u) {
            sample = abs(signed_value);
        } else if (mode == 3u) {
            let ridge = 1.0 - abs(signed_value);
            sample = ridge * ridge;
        }
        total = total + sample * amplitude;
        weight_sum = weight_sum + amplitude;
        amplitude = amplitude * clamp(roughness, 0.0, 1.0);
        frequency = frequency * max(lacunarity, 1.01);
    }
    return total / max(weight_sum, 0.000001);
}

fn value_fractal_field(
    uv: vec2<f32>, width: f32, height: f32, scale: f32, octave_count_in: u32,
    roughness: f32, seed: u32, evolution: f32, cycles: f32, lacunarity: f32
) -> f32 {
    let octave_count = clamp(octave_count_in, 1u, 10u);
    let loop_data = noise_loop_z(evolution, cycles);
    var total = 0.0;
    var weight_sum = 0.0;
    var amplitude = 1.0;
    var frequency = max(scale, 1.0);
    for (var octave: u32 = 0u; octave < 10u; octave = octave + 1u) {
        if (octave >= octave_count) { break; }
        let cells = noise_aspect_cells(frequency, width, height);
        let sample = noise_periodic_value3(uv, cells, seed + octave * 1301u, loop_data.x, u32(loop_data.y));
        total = total + sample * amplitude;
        weight_sum = weight_sum + amplitude;
        amplitude = amplitude * clamp(roughness, 0.0, 1.0);
        frequency = frequency * max(lacunarity, 1.01);
    }
    return total / max(weight_sum, 0.000001);
}

fn anisotropic_value_noise(
    uv_in: vec2<f32>, scale_x_in: u32, scale_y_in: u32, seed: u32,
    evolution: f32, cycles: f32, smoothness_in: f32, interpolation_in: f32
) -> f32 {
    let scale_x = max(scale_x_in, 1u);
    let scale_y = max(scale_y_in, 1u);
    let uv = fract(uv_in);
    let point = uv * vec2<f32>(f32(scale_x), f32(scale_y));
    let base = vec2<i32>(floor(point));
    let fraction = fract(point);
    let smoothness = clamp(smoothness_in, 0.0, 1.0);
    let interpolation = clamp(interpolation_in, 0.0, 1.0);

    // Smoothness controls the width of the horizontal fade, while
    // Interpolation blends a linear ramp with a Hermite ramp.  Keeping them
    // independent avoids two differently named controls doing the same job.
    let transition_width = max(smoothness, 0.001);
    let transition_start = 0.5 - transition_width * 0.5;
    let x_local = clamp((fraction.x - transition_start) / transition_width, 0.0, 1.0);
    let x_hermite = x_local * x_local * (3.0 - 2.0 * x_local);
    let tx = mix(x_local, x_hermite, interpolation);
    let y_hermite = fraction.y * fraction.y * (3.0 - 2.0 * fraction.y);
    let ty = mix(fraction.y, y_hermite, interpolation);

    let loop_data = noise_loop_z(evolution, cycles);
    let z_period = max(u32(loop_data.y), 1u);
    let z_base = i32(floor(loop_data.x));
    let z_fraction = fract(loop_data.x);
    let z_hermite = z_fraction * z_fraction * (3.0 - 2.0 * z_fraction);
    let tz = mix(z_fraction, z_hermite, interpolation);

    let x0 = noise_wrap_i(base.x, i32(scale_x));
    let x1 = noise_wrap_i(base.x + 1, i32(scale_x));
    let y0 = noise_wrap_i(base.y, i32(scale_y));
    let y1 = noise_wrap_i(base.y + 1, i32(scale_y));
    let z0 = noise_wrap_i(z_base, i32(z_period));
    let z1 = noise_wrap_i(z_base + 1, i32(z_period));

    let a0 = noise_hash31(vec3<u32>(x0, y0, z0), seed, 1701u);
    let b0 = noise_hash31(vec3<u32>(x1, y0, z0), seed, 1701u);
    let c0 = noise_hash31(vec3<u32>(x0, y1, z0), seed, 1701u);
    let d0 = noise_hash31(vec3<u32>(x1, y1, z0), seed, 1701u);
    let low = mix(mix(a0, b0, tx), mix(c0, d0, tx), ty);

    let a1 = noise_hash31(vec3<u32>(x0, y0, z1), seed, 1701u);
    let b1 = noise_hash31(vec3<u32>(x1, y0, z1), seed, 1701u);
    let c1 = noise_hash31(vec3<u32>(x0, y1, z1), seed, 1701u);
    let d1 = noise_hash31(vec3<u32>(x1, y1, z1), seed, 1701u);
    let high = mix(mix(a1, b1, tx), mix(c1, d1, tx), ty);
    return mix(low, high, tz);
}

struct SpotResult {
    profile: f32,
    signed_profile: f32,
    nearest: f32,
};

fn cell_spots(
    uv: vec2<f32>, width: f32, height: f32, scale: f32, seed: u32,
    evolution: f32, cycles: f32, points_per_cell_in: u32, size: f32,
    softness: f32, elliptical: f32, angle_degrees: f32
) -> SpotResult {
    let cells = noise_aspect_cells(scale, width, height);
    let point = fract(uv) * vec2<f32>(cells);
    let base = vec2<i32>(floor(point));
    let points_per_cell = clamp(points_per_cell_in, 1u, 3u);
    let radius = max(size, 0.01) * 0.48;
    let edge = max(softness, 0.001) * radius + 0.002;
    let global_angle = radians(angle_degrees);
    let phase = NOISE_TAU * evolution * cycles;
    var profile = 0.0;
    var signed_profile = 0.0;
    var nearest = 1e9;
    for (var oy: i32 = -1; oy <= 1; oy = oy + 1) {
        for (var ox: i32 = -1; ox <= 1; ox = ox + 1) {
            let neighbour = base + vec2<i32>(ox, oy);
            let wrapped = vec2<u32>(
                noise_wrap_i(neighbour.x, i32(cells.x)),
                noise_wrap_i(neighbour.y, i32(cells.y)),
            );
            for (var point_index: u32 = 0u; point_index < 10u; point_index = point_index + 1u) {
                if (point_index >= points_per_cell) { break; }
                let cell3 = vec3<u32>(wrapped, point_index);
                let hx = noise_hash31(cell3, seed, 13u);
                let hy = noise_hash31(cell3, seed, 17u);
                let hr = noise_hash31(cell3, seed, 19u);
                let hp = noise_hash31(cell3, seed, 23u);
                let ha = noise_hash31(cell3, seed, 29u);
                let centre = vec2<f32>(neighbour) + vec2<f32>(0.15) + vec2<f32>(hx, hy) * 0.7;
                let local_angle = global_angle + ha * NOISE_TAU + sin(phase + hp * NOISE_TAU) * 0.22;
                let ca = cos(local_angle);
                let sa = sin(local_angle);
                let delta = point - centre;
                let local = vec2<f32>(ca * delta.x + sa * delta.y, -sa * delta.x + ca * delta.y);
                let stretch = 1.0 + elliptical * (0.35 + 1.65 * hr);
                let distance = length(vec2<f32>(local.x / stretch, local.y * stretch));
                let local_radius = radius * (0.65 + hr * 0.7);
                let spot = 1.0 - smooth_range(local_radius - edge, local_radius + edge, distance);
                profile = max(profile, spot);
                let signed_value = spot * select(-1.0, 1.0, hp >= 0.5);
                if (abs(signed_value) > abs(signed_profile)) { signed_profile = signed_value; }
                nearest = min(nearest, distance / max(local_radius, 0.00001));
            }
        }
    }
    return SpotResult(profile, signed_profile, nearest);
}


fn sparse_spot_field(
    uv: vec2<f32>, width: f32, height: f32, scale: f32, seed: u32,
    evolution: f32, cycles: f32, points_per_cell_in: u32, radius: f32, probability: f32, ellipticity: f32
) -> f32 {
    let cells = noise_aspect_cells(max(scale, 1.0), width, height);
    let point = fract(uv) * vec2<f32>(cells);
    let base = vec2<i32>(floor(point));
    let points_per_cell = clamp(points_per_cell_in, 1u, 3u);
    var result = 0.0;
    // Smoothly compacted Gaussian tails need a 5x5 neighbourhood.  The
    // previous 3x3 truncation created cell-aligned derivative discontinuities.
    for (var oy: i32 = -2; oy <= 2; oy = oy + 1) {
        for (var ox: i32 = -2; ox <= 2; ox = ox + 1) {
            let neighbour = base + vec2<i32>(ox, oy);
            let wrapped = vec2<u32>(
                noise_wrap_i(neighbour.x, i32(cells.x)),
                noise_wrap_i(neighbour.y, i32(cells.y)),
            );
            for (var point_index: u32 = 0u; point_index < 10u; point_index = point_index + 1u) {
                if (point_index >= points_per_cell) { break; }
                let cell3 = vec3<u32>(wrapped, point_index);
                let hx = noise_hash31(cell3, seed, 101u);
                let hy = noise_hash31(cell3, seed, 103u);
                let hr = noise_hash31(cell3, seed, 107u);
                let hs = noise_hash31(cell3, seed, 109u);
                let ha = noise_hash31(cell3, seed, 127u);
                let hd = noise_hash31(cell3, seed, 131u);
                let centre = vec2<f32>(neighbour) + vec2<f32>(0.1) + vec2<f32>(hx, hy) * 0.8;
                let angle = ha * NOISE_TAU;
                let ca = cos(angle);
                let sa = sin(angle);
                let delta = point - centre;
                let local = vec2<f32>(ca * delta.x + sa * delta.y, -sa * delta.x + ca * delta.y);
                let stretch = 1.0 + clamp(ellipticity, 0.0, 1.0) * (0.25 + 1.25 * hr);
                let distance_squared = (local.x / stretch) * (local.x / stretch)
                    + (local.y * stretch) * (local.y * stretch);
                let sigma = max(radius, 0.01) * (0.55 + 0.90 * hr);
                let distance = sqrt(distance_squared);
                var kernel = exp(-distance_squared / max(2.0 * sigma * sigma, 0.000001));
                let support_fade = 1.0 - smooth_range(1.05, 1.45, distance);
                kernel = kernel * support_fade;
                let sign_value = select(-1.0, 1.0, hs >= 0.5);
                let amplitude = sign_value * (0.55 + 0.90 * ha);
                let enabled = select(0.0, 1.0, hd <= clamp(probability, 0.0, 1.0));
                result = result + kernel * amplitude * enabled;
            }
        }
    }
    return result;
}


struct CellularSimpleResult {
    f1: f32,
    f2: f32,
    cell_value: f32,
};

fn cellular_fields_simple(
    uv: vec2<f32>, width: f32, height: f32, scale: f32, seed: u32,
    jitter: f32, evolution: f32, cycles: f32
) -> CellularSimpleResult {
    let cells = noise_aspect_cells(scale, width, height);
    let point = fract(uv) * vec2<f32>(cells);
    let base = vec2<i32>(floor(point));
    let phase = NOISE_TAU * evolution * cycles;
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
            let cell3 = vec3<u32>(wrapped, 0u);
            let h_angle = noise_hash31(cell3, seed, 3u);
            let h_radius = noise_hash31(cell3, seed, 4u);
            let angle = h_angle * NOISE_TAU + phase;
            let radius = clamp(jitter, 0.0, 1.0) * 0.48 * (0.35 + 0.65 * h_radius);
            let feature = vec2<f32>(neighbour) + vec2<f32>(0.5) + vec2<f32>(cos(angle), sin(angle)) * radius;
            let distance = length(feature - point);
            if (distance < f1) {
                f2 = f1;
                f1 = distance;
                nearest_value = noise_hash31(cell3, seed, 5u);
            } else if (distance < f2) {
                f2 = distance;
            }
        }
    }
    return CellularSimpleResult(f1, f2, nearest_value);
}


fn crystal_voronoi_distance(
    uv_in: vec2<f32>, cells_x_in: u32, cells_y_in: u32, seed: u32,
    evolution: f32, cycles: f32
) -> f32 {
    let cells_x = clamp(cells_x_in, 1u, 256u);
    let cells_y = clamp(cells_y_in, 1u, 256u);
    let point = fract(uv_in) * vec2<f32>(f32(cells_x), f32(cells_y));
    let base = vec2<i32>(floor(point));
    let phase = NOISE_TAU * evolution * cycles;
    var nearest = 1e9;
    for (var oy: i32 = -1; oy <= 1; oy = oy + 1) {
        for (var ox: i32 = -1; ox <= 1; ox = ox + 1) {
            let neighbour = base + vec2<i32>(ox, oy);
            let wrapped = vec2<u32>(
                noise_wrap_i(neighbour.x, i32(cells_x)),
                noise_wrap_i(neighbour.y, i32(cells_y)),
            );
            let cell3 = vec3<u32>(wrapped, 0u);
            let h_angle = noise_hash31(cell3, seed, 3u);
            let h_radius = noise_hash31(cell3, seed, 4u);
            let angle = h_angle * NOISE_TAU + phase;
            let radius = 0.48 * (0.35 + 0.65 * h_radius);
            let feature = vec2<f32>(neighbour) + vec2<f32>(0.5)
                + vec2<f32>(cos(angle), sin(angle)) * radius;
            nearest = min(nearest, length(feature - point));
        }
    }
    return nearest;
}


fn crystal_lattice_direction(angle_degrees: f32) -> vec2<i32> {
    let angle = radians(angle_degrees);
    var x = i32(round(cos(angle) * 3.0));
    var y = i32(round(sin(angle) * 3.0));
    if (x == 0 && y == 0) { x = 1; }
    let ax = abs(x);
    let ay = abs(y);
    if (ax == 3 && ay == 3) {
        x = x / 3;
        y = y / 3;
    } else if (ax == 2 && ay == 2) {
        x = x / 2;
        y = y / 2;
    } else if (x == 0 && ay > 1) {
        y = select(-1, 1, y > 0);
    } else if (y == 0 && ax > 1) {
        x = select(-1, 1, x > 0);
    }
    return vec2<i32>(x, y);
}

fn crystal_corner_value(
    line_index: i32, band_index: i32, fold_count: i32, band_count: i32,
    seed: u32, phase: f32
) -> f32 {
    let wrapped_line = noise_wrap_i(line_index, fold_count);
    let wrapped_band = noise_wrap_i(band_index, band_count);
    let hashed = noise_hash31(vec3<u32>(wrapped_line, wrapped_band, 0u), seed, 41u);
    return 0.5 + 0.36 * sin(hashed * NOISE_TAU + phase);
}

fn crease_crystal_field(
    uv: vec2<f32>, width: f32, height: f32, fold_count_in: u32,
    band_count_in: u32, seed: u32, disorder_in: f32, sharpness: f32,
    angle_degrees: f32, evolution: f32, cycles: f32, phase_offset: f32
) -> f32 {
    let fold_count = i32(clamp(fold_count_in, 2u, 48u));
    let band_count = i32(clamp(band_count_in, 2u, 24u));
    let direction_i = crystal_lattice_direction(angle_degrees);
    let across_i = vec2<i32>(-direction_i.y, direction_i.x);
    let direction = vec2<f32>(direction_i);
    let across_direction = vec2<f32>(across_i);
    let across = fract(dot(uv, across_direction));
    let along = fract(dot(uv, direction));
    let loop_data = noise_loop_z(evolution, cycles);
    let warp_cells = noise_aspect_cells(max(f32(fold_count) * 0.32, 2.0), width, height);
    let warp = noise_periodic_value3(uv, warp_cells, seed + 777u, loop_data.x, u32(loop_data.y)) * 2.0 - 1.0;
    let disorder = clamp(disorder_in, 0.0, 1.0);
    let fold_coord = fract(across + warp * disorder * 0.075) * f32(fold_count) + phase_offset;
    let base = i32(floor(fold_coord));
    var left_position = -1e9;
    var right_position = 1e9;
    var left_index = 0;
    var right_index = 0;
    let phase = NOISE_TAU * evolution;
    for (var offset: i32 = -2; offset <= 2; offset = offset + 1) {
        let index = base + offset;
        let wrapped = noise_wrap_i(index, fold_count);
        let cell3 = vec3<u32>(wrapped, 0u, 0u);
        let position_hash = noise_hash31(cell3, seed, 31u);
        let motion_hash = noise_hash31(cell3, seed, 37u);
        let position = f32(index) + 0.5
            + (position_hash - 0.5) * disorder * 0.72
            + sin(phase + motion_hash * NOISE_TAU) * disorder * 0.045;
        if (position <= fold_coord && position > left_position) {
            left_position = position;
            left_index = index;
        }
        if (position > fold_coord && position < right_position) {
            right_position = position;
            right_index = index;
        }
    }
    let local_x = clamp((fold_coord - left_position) / max(right_position - left_position, 0.00001), 0.0, 1.0);
    let band_coord = along * f32(band_count);
    let band_base = i32(floor(band_coord));
    let local_y = fract(band_coord);
    let c00 = crystal_corner_value(left_index, band_base, fold_count, band_count, seed, phase);
    let c10 = crystal_corner_value(right_index, band_base, fold_count, band_count, seed, phase);
    let c01 = crystal_corner_value(left_index, band_base + 1, fold_count, band_count, seed, phase);
    let c11 = crystal_corner_value(right_index, band_base + 1, fold_count, band_count, seed, phase);
    let first_triangle = c00 + local_x * (c10 - c00) + local_y * (c01 - c00);
    let second_triangle = c11 + (1.0 - local_x) * (c01 - c11) + (1.0 - local_y) * (c10 - c11);
    let triangular = select(second_triangle, first_triangle, local_x + local_y <= 1.0);
    let smooth_x = local_x * local_x * (3.0 - 2.0 * local_x);
    let smooth_y = local_y * local_y * (3.0 - 2.0 * local_y);
    let bilinear = ((c00 * (1.0 - smooth_x) + c10 * smooth_x) * (1.0 - smooth_y))
        + ((c01 * (1.0 - smooth_x) + c11 * smooth_x) * smooth_y);
    let smoothing = clamp(0.16 / max(sharpness, 0.1), 0.0, 0.65);
    return mix(triangular, bilinear, smoothing);
}

struct SegmentArgs {
    density: u32,
    length_value: f32,
    width_value: f32,
    softness: f32,
    angle_degrees: f32,
    angle_random: f32,
    luminance_random: f32,
    jitter: f32,
    taper: f32,
    rounded_profile: u32,
};

fn segment_max_abs_cos_interval(center: f32, half_span: f32, phase: f32) -> f32 {
    let start = center - half_span - phase;
    let end = center + half_span - phase;
    let pi = 0.5 * NOISE_TAU;
    let first_peak = ceil(start / pi);
    let last_peak = floor(end / pi);
    if (first_peak <= last_peak) {
        return 1.0;
    }
    return max(abs(cos(start)), abs(cos(end)));
}

fn segment_search_radius(args: SegmentArgs) -> vec2<i32> {
    if (args.rounded_profile == 0u) {
        return vec2<i32>(1, 1);
    }
    let base_angle = radians(args.angle_degrees);
    // The random term spans +/- 0.5 of Angle Random and animated sway adds
    // another +/- 0.08, so 0.58 is the exact conservative half-span.
    let deviation = radians(abs(args.angle_random)) * 0.58;
    let max_half_length = max(args.length_value, 0.02) * 1.35 * 0.5;
    let max_local_width = max(args.width_value, 0.002) * 1.3;
    let max_radial_reach = max_local_width * (1.05 + 1.5 * max(args.softness, 0.001));
    let reach_x = max_half_length * segment_max_abs_cos_interval(base_angle, deviation, 0.0)
        + max_radial_reach;
    let reach_y = max_half_length * segment_max_abs_cos_interval(base_angle, deviation, 0.25 * NOISE_TAU)
        + max_radial_reach;
    return vec2<i32>(
        clamp(i32(ceil(reach_x)), 1, 5),
        clamp(i32(ceil(reach_y)), 1, 5),
    );
}

fn segment_field(
    uv: vec2<f32>, width: f32, height: f32, scale: f32, seed: u32,
    evolution: f32, cycles: f32, args: SegmentArgs
) -> f32 {
    let cells = noise_aspect_cells(scale, width, height);
    let point = fract(uv) * vec2<f32>(cells);
    let base = vec2<i32>(floor(point));
    let density = clamp(args.density, 1u, 10u);
    let base_angle = radians(args.angle_degrees);
    let phase = NOISE_TAU * evolution * cycles;
    let search_radius = segment_search_radius(args);
    var value = 0.0;
    for (var oy: i32 = -5; oy <= 5; oy = oy + 1) {
        if (abs(oy) > search_radius.y) { continue; }
        for (var ox: i32 = -5; ox <= 5; ox = ox + 1) {
            if (abs(ox) > search_radius.x) { continue; }
            let neighbour = base + vec2<i32>(ox, oy);
            let wrapped = vec2<u32>(
                noise_wrap_i(neighbour.x, i32(cells.x)),
                noise_wrap_i(neighbour.y, i32(cells.y)),
            );
            for (var point_index: u32 = 0u; point_index < 10u; point_index = point_index + 1u) {
                if (point_index >= density) { break; }
                let cell3 = vec3<u32>(wrapped, point_index);
                let hx = noise_hash31(cell3, seed, 41u);
                let hy = noise_hash31(cell3, seed, 43u);
                let ha = noise_hash31(cell3, seed, 47u);
                let hl = noise_hash31(cell3, seed, 53u);
                let hw = noise_hash31(cell3, seed, 59u);
                let hv = noise_hash31(cell3, seed, 61u);
                let centre = vec2<f32>(neighbour) + vec2<f32>(0.5) + (vec2<f32>(hx, hy) - vec2<f32>(0.5)) * args.jitter;
                let angle_random_radians = radians(args.angle_random);
                let angle = base_angle + (ha - 0.5) * angle_random_radians
                    + sin(phase + hl * NOISE_TAU) * angle_random_radians * 0.08;
                let direction = vec2<f32>(cos(angle), sin(angle));
                let delta = point - centre;
                let half_length = max(args.length_value, 0.02) * (0.65 + 0.7 * hl) * 0.5;
                let along = dot(delta, direction);
                let clamped_along = clamp(along, -half_length, half_length);
                let closest = delta - direction * clamped_along;
                let distance = length(closest);
                let local_width = max(args.width_value, 0.002) * (0.7 + 0.6 * hw);
                let edge = local_width * (max(args.softness, 0.001) * 1.5 + 0.05);
                var strand = 1.0 - smooth_range(local_width - edge, local_width + edge, distance);
                if (args.taper > 0.0) {
                    let normalised_along = along / max(half_length, 0.00001);
                    var endpoint = clamp(1.0 - abs(normalised_along), 0.0, 1.0);
                    if (args.rounded_profile != 0u) {
                        // A parabolic dome removes the midpoint cusp produced
                        // by the mirrored linear profile used by other fibres.
                        endpoint = clamp(1.0 - normalised_along * normalised_along, 0.0, 1.0);
                    }
                    strand = strand * pow(endpoint, 0.35 + args.taper * 1.65);
                }
                let luminance = 1.0 - hv * clamp(args.luminance_random, 0.0, 1.0);
                value = max(value, strand * luminance);
            }
        }
    }
    return value;
}

fn finalise(value_in: f32) -> f32 {
    return noise_finish(value_in, params.p5.x, params.p5.y, params.p5.z > 0.5);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width_u = u32(params.p0.x);
    let height_u = u32(params.p0.y);
    if (gid.x >= width_u || gid.y >= height_u) { return; }
    let width = f32(width_u);
    let height = f32(height_u);
    let variant = u32(round(params.p1.x));
    let scale = max(params.p1.y, 1.0);
    let seed = u32(max(params.p1.z, 0.0));
    let evolution = noise_evolution_phase(params.p1.w);
    let cycles = max(params.p2.x, 0.001);
    let disorder = params.p2.y;
    let disorder_scale = max(params.p2.z, 1.0);
    let disorder_anisotropy = clamp(params.p2.w, 0.0, 1.0);
    let disorder_angle = params.p3.x;
    var uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / vec2<f32>(width, height);
    if (variant <= 2u) {
        uv = cloud_disorder(
            uv, width, height, scale, seed, evolution, cycles, disorder,
            disorder_scale, disorder_anisotropy, disorder_angle
        );
    } else if (variant == 12u) {
        // Moisture is isotropic.  A gentle value-noise warp breaks up the
        // deposit distribution without introducing directional curls or
        // reusing the old Pattern Angle/anisotropy controls.
        uv = cloud_disorder(
            uv, width, height, scale, seed, evolution, cycles, disorder,
            disorder_scale, 0.0, 0.0
        );
    } else if (variant == 8u) {
        let minimum_level = clamp(u32(round(params.p3.z)), 0u, 9u);
        uv = noise_domain_warp(
            uv, width, height, max(pow(2.0, f32(minimum_level)), 1.0), seed,
            evolution, cycles, disorder, disorder_scale
        );
    } else {
        uv = directional_disorder(
            uv, width, height, scale, seed, evolution, cycles, disorder,
            disorder_scale, disorder_anisotropy, disorder_angle
        );
    }
    var value = 0.0;

    if (variant == 0u) {
        let octaves = u32(round(params.p3.y));
        let roughness = clamp(params.p3.z, 0.0, 1.0);
        let softness = clamp(params.p3.w, 0.0, 1.0);
        let gain = 0.34 + 0.38 * roughness;
        let broad = value_fractal_field(uv, width, height, scale, octaves, gain, seed, evolution, cycles, 2.0);
        let middle = value_fractal_field(uv, width, height, scale * 2.15, max(octaves, 2u) - 1u, gain * 0.88, seed + 3701u, evolution, cycles, 2.0);
        let fine = value_fractal_field(uv, width, height, scale * 4.2, max(octaves, 3u) - 2u, gain * 0.74, seed + 9103u, evolution, cycles, 2.0);
        let raw = broad * 0.48 + middle * 0.35 + fine * 0.20;
        let gamma = 0.78 - 0.32 * softness;
        let shaped = pow(clamp(raw, 0.0, 1.0), gamma);
        let internal_contrast = 1.45 + 0.58 * (1.0 - softness);
        value = clamp((shaped - 0.5) * internal_contrast + 0.39, 0.0, 1.0);
    } else if (variant == 1u) {
        let octaves = u32(round(params.p3.y));
        let roughness = clamp(params.p3.z, 0.0, 1.0);
        let puffiness = max(params.p3.w, 0.25);
        let gain = 0.28 + 0.42 * roughness;
        let low = value_fractal_field(uv, width, height, scale * 0.75, octaves, gain, seed, evolution, cycles, 2.0);
        let middle = value_fractal_field(uv, width, height, scale * 1.75, max(octaves, 2u) - 1u, gain * 0.94, seed + 3701u, evolution, cycles, 2.0);
        let fine = value_fractal_field(uv, width, height, scale * 3.75, max(octaves, 3u) - 2u, gain * 0.80, seed + 9103u, evolution, cycles, 2.0);
        let raw = low * 0.62 + middle * 0.31 + fine * 0.07;
        let gamma = clamp(0.88 - 0.18 * puffiness, 0.42, 1.10);
        let shaped = pow(clamp(raw, 0.0, 1.0), gamma);
        let internal_contrast = 1.20 + 0.14 * puffiness;
        value = clamp((shaped - 0.5) * internal_contrast + 0.425, 0.0, 1.0);
    } else if (variant == 2u) {
        let octaves = u32(round(params.p3.y));
        let roughness = clamp(params.p3.z, 0.0, 1.0);
        let erosion = clamp(params.p3.w, 0.0, 1.0);
        let detail = clamp(params.p4.x, 0.0, 1.0);
        let gain = 0.36 + 0.42 * roughness;
        let body = value_fractal_field(uv, width, height, scale, octaves, gain, seed, evolution, cycles, 2.0);
        let middle = value_fractal_field(uv, width, height, scale * 2.35, max(octaves, 2u) - 1u, gain * 0.90, seed + 3701u, evolution, cycles, 2.0);
        let fine = value_fractal_field(uv, width, height, scale * 5.0, max(octaves, 3u) - 2u, gain * 0.75, seed + 9103u, evolution, cycles, 2.0);
        var raw = (body * 0.64 + middle * 0.26 + fine * (0.10 * detail)) / (0.90 + 0.10 * detail);
        let broken = raw * (0.82 + middle * 0.36);
        raw = mix(raw, broken, erosion * 0.45);
        let internal_contrast = 1.25 + 0.92 * erosion;
        value = clamp((raw - 0.5) * internal_contrast + 0.427, 0.0, 1.0);
    } else if (variant == 3u) {
        let roughness = clamp(params.p3.y, 0.0, 1.0);
        let grain = clamp(params.p3.z, 0.0, 1.0);
        let broad = sparse_spot_field(uv, width, height, scale * 0.75, seed, evolution, cycles, 3u, 0.34, 0.82, 0.18);
        let middle = sparse_spot_field(uv, width, height, scale * 2.8, seed + 4099u, evolution, cycles, 3u, 0.25, 0.68, 0.12);
        let fine = sparse_spot_field(uv, width, height, scale * 8.4, seed + 8191u, evolution, cycles, 2u, 0.20, 0.48, 0.08);
        let impulse_sum = broad * 0.60 + middle * (0.38 + 0.35 * roughness) + fine * (0.18 + 0.45 * grain);
        value = clamp(0.440 + 0.36 * tanh(impulse_sum * 0.82), 0.0, 1.0);
    } else if (variant == 4u) {
        let roughness = clamp(params.p3.y, 0.0, 1.0);
        let grain = clamp(params.p3.z, 0.0, 1.0);
        let broad = sparse_spot_field(uv, width, height, scale * 0.48, seed, evolution, cycles, 2u, 0.44, 0.72, 0.22);
        let middle = sparse_spot_field(uv, width, height, scale * 1.85, seed + 4099u, evolution, cycles, 3u, 0.27, 0.58, 0.12);
        let speckles = sparse_spot_field(uv, width, height, scale * 9.5, seed + 8191u, evolution, cycles, 2u, 0.18, 0.36, 0.04);
        let impulse_sum = broad * 0.48 + middle * (0.25 + 0.28 * roughness) + speckles * (0.36 + 0.70 * grain);
        value = clamp(0.442 + 0.40 * tanh(impulse_sum * 0.70), 0.0, 1.0);
    } else if (variant == 5u) {
        let roughness = clamp(params.p3.y, 0.0, 1.0);
        let grain = clamp(params.p3.z, 0.0, 1.0);
        let broad = sparse_spot_field(uv, width, height, scale, seed, evolution, cycles, 2u, 0.43, 0.76, 0.18);
        let middle = sparse_spot_field(uv, width, height, scale * 2.25, seed + 4099u, evolution, cycles, 3u, 0.38, 0.62, 0.10);
        let fine = sparse_spot_field(uv, width, height, scale * 7.0, seed + 8191u, evolution, cycles, 2u, 0.24, 0.38, 0.05);
        let impulse_sum = broad * 0.55 + middle * (0.32 + 0.28 * roughness) + fine * (0.14 + 0.30 * grain);
        value = clamp(0.505 + 0.30 * tanh(impulse_sum * 0.68), 0.0, 1.0);
    } else if (variant == 6u) {
        let cells_x = clamp(u32(round(params.p3.x)), 1u, 256u);
        let cells_y = clamp(u32(round(params.p3.y)), 1u, 256u);
        let first_distance = crystal_voronoi_distance(
            uv, cells_x, cells_y, seed, evolution, cycles
        );
        let second_distance = crystal_voronoi_distance(
            uv, cells_x, cells_y, seed + 101u, evolution, cycles
        );
        let first_scaled = clamp(first_distance * 0.88, 0.0, 1.0);
        let second_scaled = clamp(second_distance * 0.88, 0.0, 1.0);
        let first = sqrt(max(1.0 - first_scaled * first_scaled, 0.0));
        let second = sqrt(max(1.0 - second_scaled * second_scaled, 0.0));
        let low = min(first, second);
        let high = max(first, second);
        value = clamp((high - low) / max(high, 0.000001) * 1.45, 0.0, 1.0);
    } else if (variant == 7u) {
        let disorder_value = clamp(params.p3.y, 0.0, 1.0);
        let sharpness = max(params.p3.z, 0.1);
        let strength = clamp(params.p3.w, 0.0, 1.0);
        let angle = params.p4.x;
        let primary_folds = max(u32(round(scale * 1.7)), 3u);
        let primary_bands = max(u32(round(scale * 0.75)), 2u);
        let primary = crease_crystal_field(
            uv, width, height, primary_folds, primary_bands, seed, disorder_value,
            sharpness, angle, evolution, cycles, 0.0
        );
        let secondary = crease_crystal_field(
            uv, width, height, max(u32(round(scale * 2.6)), 4u), max(primary_bands + 1u, 3u),
            seed + 97u, disorder_value * 0.88, sharpness * 1.08, angle,
            evolution, cycles, 0.37
        );
        let tertiary = crease_crystal_field(
            uv, width, height, max(u32(round(scale * 1.2)), 3u), max(primary_bands - 1u, 2u),
            seed + 211u, disorder_value * 0.72, sharpness * 0.82, angle,
            evolution, cycles, 0.13
        );
        let combined = 0.5 + (primary - 0.5) * 0.58
            + (secondary - 0.5) * 0.30 + (tertiary - 0.5) * 0.12;
        value = clamp(0.5 + (combined - 0.5) * (0.50 + 0.50 * strength), 0.0, 1.0);
    } else if (variant == 8u) {
        let roughness = clamp(params.p3.y, 0.0, 1.0);
        let minimum = clamp(u32(round(params.p3.z)), 0u, 9u);
        let maximum = clamp(u32(round(params.p3.w)), minimum, 10u);
        let loop_data = noise_loop_z(evolution, cycles);
        var total = 0.0;
        var weight_sum = 0.0;
        var amplitude = 1.0;
        for (var level: u32 = 0u; level <= 10u; level = level + 1u) {
            if (level < minimum || level > maximum) { continue; }
            let frequency = pow(2.0, f32(level));
            let base = noise_periodic_gradient3(uv, noise_aspect_cells(frequency, width, height), seed + level * 1423u, loop_data.x, u32(loop_data.y));
            total = total + base * amplitude;
            weight_sum = weight_sum + amplitude;
            amplitude = amplitude * roughness;
        }
        value = total / max(weight_sum, 0.000001);
        value = clamp(0.5 + (value - 0.5) * params.p4.x, 0.0, 1.0);
    } else if (variant == 9u) {
        value = anisotropic_value_noise(
            uv,
            u32(round(params.p3.x)),
            u32(round(params.p3.y)),
            seed,
            evolution,
            cycles,
            params.p3.z,
            params.p3.w
        );
    } else if (variant == 10u || variant == 11u || variant == 13u) {
        var working_uv = uv;
        if (variant == 11u) {
            working_uv = directional_disorder(working_uv, width, height, scale, seed + 2281u, evolution, cycles, params.p6.x, params.p6.y, 0.35, params.p4.y);
        }
        var taper = 0.35;
        if (variant == 11u) { taper = 0.55; }
        if (variant == 13u) { taper = 0.95; }
        let rounded_profile = select(0u, 1u, variant == 13u);
        let args = SegmentArgs(u32(round(params.p3.y)), params.p3.z, params.p3.w, params.p4.x, params.p4.y, params.p4.z, params.p4.w, 1.0, taper, rounded_profile);
        value = segment_field(working_uv, width, height, scale, seed, evolution, cycles, args);
        if (variant == 11u) {
            let breakup = fractal_field(working_uv, width, height, scale * 1.8, 3u, 0.55, seed + 6343u, evolution, cycles, 0u, 2.0);
            let breakage = clamp(params.p6.z, 0.0, 1.0);
            value = value * clamp(1.0 - breakage * (1.0 - breakup) * 1.35, 0.0, 1.0);
        } else if (variant == 13u) {
            let under_args = SegmentArgs(2u, params.p3.z * 0.72, params.p3.w * 1.5, 0.55, params.p4.y, params.p4.z * 1.4, 0.8, 1.0, 0.8, 1u);
            let undercoat = segment_field(working_uv, width, height, scale * 0.62, seed + 9511u, evolution, cycles, under_args);
            value = max(value, undercoat * 0.42);
        }
    } else if (variant == 12u) {
        // Moisture is a layered deposit process: positive and negative soft
        // discs are summed over a broad dampness mask, with a separate fine
        // condensation layer.  No nearest-cell ownership or max-profile
        // operation is used, so the output cannot form Voronoi-like cracks.
        let pool_size = clamp(params.p3.x, 0.35, 2.5);
        let fine_detail = clamp(params.p3.y, 0.0, 1.0);
        let patchiness = clamp(params.p3.z, 0.0, 1.0);
        let root_size = sqrt(pool_size);
        let broad = sparse_spot_field(
            uv, width, height, max(scale * 0.58 / root_size, 1.0), seed,
            evolution, cycles, 3u, 0.50 * root_size, 0.92, 0.12
        );
        let middle = sparse_spot_field(
            uv, width, height, max(scale * 2.20 / root_size, 1.0), seed + 2671u,
            evolution, cycles, 3u, 0.29 * root_size, 0.75, 0.10
        );
        let fine = sparse_spot_field(
            uv, width, height, max(scale * 9.5, 1.0), seed + 8111u,
            evolution, cycles, 3u, 0.18, 0.48, 0.03
        );
        let micro = sparse_spot_field(
            uv, width, height, max(scale * 18.0, 1.0), seed + 12347u,
            evolution, cycles, 2u, 0.14, 0.28, 0.0
        );
        let damp_mask = value_fractal_field(
            uv, width, height, max(scale * 0.30 / root_size, 1.0),
            4u, 0.55, seed + 991u, evolution, cycles, 2.0
        );
        let broad_field = broad * 0.38 + middle * 0.28
            + (damp_mask - 0.5) * (0.18 + 0.47 * patchiness);
        let speckles = fine * (0.018 + 0.057 * fine_detail)
            + micro * (0.010 + 0.040 * fine_detail);
        value = clamp(0.55 + 0.38 * tanh(broad_field * 0.85) + speckles, 0.0, 1.0);
    }
    value = finalise(value);
    textureStore(output_tex, vec2<i32>(gid.xy), vec4<f32>(value, value, value, 1.0));
}
