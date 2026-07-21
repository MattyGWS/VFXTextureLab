struct Params {
    p0: vec4<f32>,
    p1: vec4<f32>,
    p2: vec4<f32>,
    p3: vec4<f32>,
    p4: vec4<f32>,
    p5: vec4<f32>,
    p6: vec4<f32>,
    p7: vec4<f32>,
    p8: vec4<f32>,
    p9: vec4<f32>,
    p10: vec4<f32>,
    p11: vec4<f32>,
};

struct BilinearCoords {
    p00: vec2<i32>,
    p10: vec2<i32>,
    p01: vec2<i32>,
    p11: vec2<i32>,
    fraction: vec2<f32>,
};

@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var pattern_tex_1: texture_2d<f32>;
@group(0) @binding(2) var pattern_tex_2: texture_2d<f32>;
@group(0) @binding(3) var pattern_tex_3: texture_2d<f32>;
@group(0) @binding(4) var pattern_tex_4: texture_2d<f32>;
@group(0) @binding(5) var background_tex: texture_2d<f32>;
@group(0) @binding(6) var output_tex: texture_storage_2d<rgba32float, write>;

const PI: f32 = 3.14159265358979323846;
const DEG_TO_RAD: f32 = 0.017453292519943295;
const MAX_RINGS: i32 = 10;
const NEIGHBOURS: i32 = 6;

fn positive_mod(value: i32, divisor: i32) -> i32 {
    let quotient = i32(floor(f32(value) / f32(divisor)));
    return value - quotient * divisor;
}

fn positive_degrees(value: f32) -> f32 {
    return value - floor(value / 360.0) * 360.0;
}

fn hash_u32(ix: i32, iy: i32, seed: u32, stream: u32) -> u32 {
    var value = u32(ix) * 0x9E3779B9u
        ^ u32(iy) * 0x85EBCA6Bu
        ^ seed * 0xC2B2AE35u
        ^ stream * 0x27D4EB2Du;
    value = value ^ (value >> 16u);
    value = value * 0x7FEB352Du;
    value = value ^ (value >> 15u);
    value = value * 0x846CA68Bu;
    value = value ^ (value >> 16u);
    return value;
}

fn random_instance(ring: i32, pattern: i32, seed: u32, stream: u32) -> f32 {
    return f32(hash_u32(ring, pattern, seed, stream) & 0x00FFFFFFu) / 16777216.0;
}

fn local_bilinear_coords(uv: vec2<f32>, size: vec2<i32>) -> BilinearCoords {
    let pixel = uv * vec2<f32>(size) - vec2<f32>(0.5);
    let base = vec2<i32>(floor(pixel));
    let fraction = fract(pixel);
    let maximum = size - vec2<i32>(1);
    return BilinearCoords(
        clamp(base, vec2<i32>(0), maximum),
        clamp(base + vec2<i32>(1, 0), vec2<i32>(0), maximum),
        clamp(base + vec2<i32>(0, 1), vec2<i32>(0), maximum),
        clamp(base + vec2<i32>(1, 1), vec2<i32>(0), maximum),
        fraction
    );
}

fn mix_bilinear(a: f32, b: f32, c: f32, d: f32, fraction: vec2<f32>) -> f32 {
    return mix(mix(a, b, fraction.x), mix(c, d, fraction.x), fraction.y);
}

fn pattern_nearest_coord(uv: vec2<f32>, size: vec2<i32>) -> vec2<i32> {
    return clamp(vec2<i32>(floor(uv * vec2<f32>(size))), vec2<i32>(0), size - vec2<i32>(1));
}

fn sample_input_bilinear(which: u32, uv: vec2<f32>) -> f32 {
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) { return 0.0; }
    if (which == 0u) {
        let c = local_bilinear_coords(uv, vec2<i32>(textureDimensions(pattern_tex_1)));
        return mix_bilinear(textureLoad(pattern_tex_1, c.p00, 0).r, textureLoad(pattern_tex_1, c.p10, 0).r, textureLoad(pattern_tex_1, c.p01, 0).r, textureLoad(pattern_tex_1, c.p11, 0).r, c.fraction);
    }
    if (which == 1u) {
        let c = local_bilinear_coords(uv, vec2<i32>(textureDimensions(pattern_tex_2)));
        return mix_bilinear(textureLoad(pattern_tex_2, c.p00, 0).r, textureLoad(pattern_tex_2, c.p10, 0).r, textureLoad(pattern_tex_2, c.p01, 0).r, textureLoad(pattern_tex_2, c.p11, 0).r, c.fraction);
    }
    if (which == 2u) {
        let c = local_bilinear_coords(uv, vec2<i32>(textureDimensions(pattern_tex_3)));
        return mix_bilinear(textureLoad(pattern_tex_3, c.p00, 0).r, textureLoad(pattern_tex_3, c.p10, 0).r, textureLoad(pattern_tex_3, c.p01, 0).r, textureLoad(pattern_tex_3, c.p11, 0).r, c.fraction);
    }
    let c = local_bilinear_coords(uv, vec2<i32>(textureDimensions(pattern_tex_4)));
    return mix_bilinear(textureLoad(pattern_tex_4, c.p00, 0).r, textureLoad(pattern_tex_4, c.p10, 0).r, textureLoad(pattern_tex_4, c.p01, 0).r, textureLoad(pattern_tex_4, c.p11, 0).r, c.fraction);
}

fn sample_input_nearest(which: u32, uv: vec2<f32>) -> f32 {
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) { return 0.0; }
    if (which == 0u) {
        return textureLoad(pattern_tex_1, pattern_nearest_coord(uv, vec2<i32>(textureDimensions(pattern_tex_1))), 0).r;
    }
    if (which == 1u) {
        return textureLoad(pattern_tex_2, pattern_nearest_coord(uv, vec2<i32>(textureDimensions(pattern_tex_2))), 0).r;
    }
    if (which == 2u) {
        return textureLoad(pattern_tex_3, pattern_nearest_coord(uv, vec2<i32>(textureDimensions(pattern_tex_3))), 0).r;
    }
    return textureLoad(pattern_tex_4, pattern_nearest_coord(uv, vec2<i32>(textureDimensions(pattern_tex_4))), 0).r;
}

fn input_dimensions(which: u32) -> vec2<i32> {
    if (which == 0u) { return vec2<i32>(textureDimensions(pattern_tex_1)); }
    if (which == 1u) { return vec2<i32>(textureDimensions(pattern_tex_2)); }
    if (which == 2u) { return vec2<i32>(textureDimensions(pattern_tex_3)); }
    return vec2<i32>(textureDimensions(pattern_tex_4));
}

fn sample_input_filtered(which: u32, uv: vec2<f32>, dx: vec2<f32>, dy: vec2<f32>, antialiased: bool) -> f32 {
    if (!antialiased) { return sample_input_nearest(which, uv); }
    let size = input_dimensions(which);
    let source_size = vec2<f32>(size);
    let minified = max(length(dx * source_size), length(dy * source_size)) > 1.0;
    if (!minified) { return sample_input_bilinear(which, uv); }
    let spread = 0.375;
    return (
        sample_input_nearest(which, uv)
        + sample_input_nearest(which, uv - dx * spread - dy * spread)
        + sample_input_nearest(which, uv + dx * spread - dy * spread)
        + sample_input_nearest(which, uv - dx * spread + dy * spread)
        + sample_input_nearest(which, uv + dx * spread + dy * spread)
    ) * 0.2;
}

fn connected_count(mask: u32) -> u32 {
    return ((mask >> 0u) & 1u) + ((mask >> 1u) & 1u) + ((mask >> 2u) & 1u) + ((mask >> 3u) & 1u);
}

fn pattern_from_ordinal(mask: u32, ordinal: u32) -> u32 {
    var seen = 0u;
    for (var index = 0u; index < 4u; index = index + 1u) {
        if (((mask >> index) & 1u) != 0u) {
            if (seen == ordinal) { return index; }
            seen = seen + 1u;
        }
    }
    return 0u;
}

fn builtin_shape(pattern: u32, local: vec2<f32>, feather: f32) -> f32 {
    if (pattern == 8u) {
        let radius_squared = dot(local, local);
        let profile = exp(-3.5 * radius_squared);
        let edge = 1.0 - sqrt(radius_squared);
        if (feather <= 0.0) { return select(0.0, profile, edge >= 0.0); }
        return profile * clamp(edge / feather + 0.5, 0.0, 1.0);
    }
    var edge = 1.0 - max(abs(local.x), abs(local.y));
    if (pattern == 5u) {
        edge = 1.0 - length(local);
    } else if (pattern == 6u) {
        let radius = 0.12;
        let q = abs(local) - vec2<f32>(1.0 - radius);
        let outside = length(max(q, vec2<f32>(0.0)));
        let inside = min(max(q.x, q.y), 0.0);
        edge = -(outside + inside - radius);
    } else if (pattern == 7u) {
        let qx = max(abs(local.x) - 0.45, 0.0);
        edge = 0.55 - length(vec2<f32>(qx, local.y));
    } else if (pattern == 9u) {
        edge = 1.0 - (abs(local.x) + abs(local.y));
    } else if (pattern == 10u) {
        let a = abs(local);
        edge = 1.0 - max(a.y, a.x * 0.8660254 + a.y * 0.5);
    } else if (pattern == 11u) {
        edge = min(1.0 - local.y, local.y + 1.0 - 2.0 * abs(local.x));
    }
    if (feather <= 0.0) { return select(0.0, 1.0, edge >= 0.0); }
    return clamp(edge / feather + 0.5, 0.0, 1.0);
}

fn pattern_coverage(pattern: u32, local: vec2<f32>, feather: f32, dx: vec2<f32>, dy: vec2<f32>, antialiased: bool) -> f32 {
    if (pattern < 4u) {
        return sample_input_filtered(pattern, local * 0.5 + vec2<f32>(0.5), dx, dy, antialiased);
    }
    return builtin_shape(pattern, local, feather);
}

@compute @workgroup_size(8, 8, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }

    let authored_amount = clamp(i32(params.p1.x), 1, 64);
    let amount_random = clamp(params.p1.y, 0.0, 1.0);
    let minimum_amount = clamp(i32(params.p1.z), 1, authored_amount);
    let ring_amount = clamp(i32(params.p1.w), 1, MAX_RINGS);
    let first_radius = clamp(params.p2.x, 0.0, 2.0);
    let ring_spacing = clamp(params.p2.y, -1.0, 1.0);
    let radius_random = clamp(params.p2.z, 0.0, 1.0);
    let arc_spread = clamp(params.p2.w, 1.0, 360.0);
    let ring_rotation = params.p3.x;
    let ring_rotation_offset = params.p3.y;
    let spiral = clamp(params.p3.z, -1.0, 1.0);
    let angular_random = clamp(params.p3.w, 0.0, 1.0);
    let centre_uv = params.p4.xy;
    let authored_pattern = u32(params.p4.z);
    let selection_mode = u32(params.p4.w);
    let orientation = u32(params.p5.x);
    let pattern_rotation = params.p5.y;
    let rotation_random = clamp(params.p5.z, 0.0, 180.0);
    let rotation_by_ring = params.p5.w;
    let size_xy = clamp(params.p6.xy, vec2<f32>(0.001), vec2<f32>(4.0));
    let authored_scale = clamp(params.p6.z, 0.001, 4.0);
    let scale_random = clamp(params.p6.w, 0.0, 1.0);
    let scale_by_ring = clamp(params.p7.x, -1.0, 1.0);
    let scale_by_pattern = clamp(params.p7.y, -1.0, 1.0);
    let connect_patterns = params.p7.z >= 0.5;
    let connect_scale = clamp(params.p7.w, 0.05, 4.0);
    let random_removal = clamp(params.p8.x, 0.0, 1.0);
    let luminance = clamp(params.p8.y, 0.0, 1.0);
    let luminance_random = clamp(params.p8.z, 0.0, 1.0);
    let luminance_by_ring = clamp(params.p8.w, -1.0, 1.0);
    let luminance_by_pattern = clamp(params.p9.x, -1.0, 1.0);
    let opacity = clamp(params.p9.y, 0.0, 1.0);
    let blend_mode = u32(params.p9.z);
    let background_value = clamp(params.p9.w, 0.0, 1.0);
    let connected_mask = u32(params.p10.x);
    let antialiased = params.p10.y >= 0.5;
    let background_connected = params.p10.z >= 0.5;
    let authored_feather = clamp(params.p10.w, 0.0, 0.25);
    let seed = u32(max(params.p11.x, 0.0));

    let coord = vec2<i32>(gid.xy);
    var result = background_value;
    if (background_connected) { result = textureLoad(background_tex, coord, 0).r; }

    let uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / vec2<f32>(f32(width), f32(height));
    let aspect = f32(width) / max(f32(height), 1.0);
    let physical = vec2<f32>((uv.x - centre_uv.x) * aspect, uv.y - centre_uv.y);
    let polar_angle = positive_degrees(atan2(physical.y, physical.x) / DEG_TO_RAD);
    let ring_denominator = f32(max(ring_amount - 1, 1));
    let input_count = connected_count(connected_mask);

    for (var ring = 0; ring < MAX_RINGS; ring = ring + 1) {
        if (ring >= ring_amount) { break; }
        let amount_reduction = random_instance(ring, 0, seed, 31u) * amount_random * f32(authored_amount - minimum_amount);
        let count = clamp(i32(round(f32(authored_amount) - amount_reduction)), minimum_amount, authored_amount);
        let full_ring = arc_spread >= 359.999;
        let angle_step = select(arc_spread / f32(max(count - 1, 1)), 360.0 / f32(count), full_ring);
        let start_angle = ring_rotation + f32(ring) * ring_rotation_offset;
        let relative_angle = positive_degrees(polar_angle - start_angle);
        var nearest = i32(round(relative_angle / max(angle_step, 0.000001)));
        if (full_ring) {
            nearest = positive_mod(nearest, count);
        } else {
            nearest = clamp(nearest, 0, count - 1);
        }
        let small_ring = count <= NEIGHBOURS * 2 + 1;
        let iteration_count = select(NEIGHBOURS * 2 + 1, count, small_ring);

        for (var iteration = 0; iteration < NEIGHBOURS * 2 + 1; iteration = iteration + 1) {
            if (iteration >= iteration_count) { break; }
            var pattern_index = iteration;
            if (!small_ring) {
                pattern_index = positive_mod(nearest + iteration - NEIGHBOURS, count);
            }
            let pattern_t = f32(pattern_index) / f32(max(count - 1, 1));
            let angular_jitter = (random_instance(ring, pattern_index, seed, 1u) * 2.0 - 1.0) * angular_random * angle_step * 0.5;
            let instance_angle_degrees = start_angle + f32(pattern_index) * angle_step + angular_jitter;
            let instance_angle = instance_angle_degrees * DEG_TO_RAD;
            let radius_basis = select(max(first_radius, 0.1), abs(ring_spacing), abs(ring_spacing) > 0.000001);
            let radius_jitter = (random_instance(ring, pattern_index, seed, 2u) * 2.0 - 1.0) * radius_random * radius_basis * 0.5;
            let instance_radius = first_radius + f32(ring) * ring_spacing + spiral * pattern_t + radius_jitter;
            let instance_center = vec2<f32>(cos(instance_angle), sin(instance_angle)) * instance_radius;
            let relative = physical - instance_center;

            let random_scale = max(0.05, 1.0 + (random_instance(ring, pattern_index, seed, 3u) * 2.0 - 1.0) * scale_random);
            let ring_progress = f32(ring) / ring_denominator;
            let progression = max(0.05, 1.0 + scale_by_ring * ring_progress + scale_by_pattern * (pattern_t * 2.0 - 1.0));
            let instance_scale = authored_scale * random_scale * progression;
            var half_size = size_xy * instance_scale * 0.5;
            if (connect_patterns) {
                let chord = 2.0 * max(abs(instance_radius), 0.00001) * sin(angle_step * DEG_TO_RAD * 0.5);
                half_size.x = max(chord * connect_scale * instance_scale * 0.5, 0.00001);
            }
            half_size = max(half_size, vec2<f32>(0.00001));

            var rotation = pattern_rotation + f32(ring) * rotation_by_ring;
            if (orientation == 0u) {
                rotation = rotation + instance_angle_degrees + 90.0;
            } else if (orientation == 1u) {
                rotation = rotation + instance_angle_degrees - 90.0;
            } else if (orientation == 2u) {
                rotation = rotation + instance_angle_degrees;
            }
            rotation = rotation + (random_instance(ring, pattern_index, seed, 4u) * 2.0 - 1.0) * rotation_random;
            let angle = rotation * DEG_TO_RAD;
            let cosine = cos(angle);
            let sine = sin(angle);
            let local = vec2<f32>(
                (cosine * relative.x + sine * relative.y) / half_size.x,
                (-sine * relative.x + cosine * relative.y) / half_size.y
            );

            let physical_step = 1.0 / max(f32(height), 1.0);
            let pattern_dx = vec2<f32>(cosine * physical_step / half_size.x, -sine * physical_step / half_size.y) * 0.5;
            let pattern_dy = vec2<f32>(sine * physical_step / half_size.x, cosine * physical_step / half_size.y) * 0.5;
            let pixel_feather = 1.25 / max(f32(min(width, height)) * min(half_size.x, half_size.y), 1.0);
            let feather = select(authored_feather, max(authored_feather, pixel_feather), antialiased);

            var actual_pattern = authored_pattern;
            if (selection_mode != 0u && input_count > 0u) {
                var ordinal = 0u;
                if (selection_mode == 1u) {
                    ordinal = min(u32(random_instance(ring, pattern_index, seed, 41u) * f32(input_count)), input_count - 1u);
                } else if (selection_mode == 2u) {
                    ordinal = u32(pattern_index) % input_count;
                } else {
                    ordinal = u32(ring) % input_count;
                }
                actual_pattern = pattern_from_ordinal(connected_mask, ordinal);
            } else if (selection_mode != 0u && actual_pattern < 4u) {
                actual_pattern = 5u;
            }

            var coverage = pattern_coverage(actual_pattern, local, feather, pattern_dx, pattern_dy, antialiased);
            if (random_instance(ring, pattern_index, seed, 5u) < random_removal) { coverage = 0.0; }
            var value = luminance * mix(1.0, random_instance(ring, pattern_index, seed, 6u), luminance_random);
            value = clamp(value * clamp(1.0 + luminance_by_ring * ring_progress + luminance_by_pattern * (pattern_t * 2.0 - 1.0), 0.0, 2.0), 0.0, 1.0);
            let amount = coverage * value * opacity;
            if (blend_mode == 1u) {
                result = min(result + amount, 1.0);
            } else if (blend_mode == 2u) {
                result = max(result - amount, 0.0);
            } else if (blend_mode == 3u) {
                result = mix(result, value, clamp(coverage * opacity, 0.0, 1.0));
            } else {
                result = max(result, amount);
            }
        }
    }

    let value = clamp(result, 0.0, 1.0);
    textureStore(output_tex, coord, vec4<f32>(value, value, value, 1.0));
}
