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
@group(0) @binding(5) var scale_map_tex: texture_2d<f32>;
@group(0) @binding(6) var rotation_map_tex: texture_2d<f32>;
@group(0) @binding(7) var displacement_map_tex: texture_2d<f32>;
@group(0) @binding(8) var vector_map_tex: texture_2d<f32>;
@group(0) @binding(9) var mask_map_tex: texture_2d<f32>;
@group(0) @binding(10) var distribution_map_tex: texture_2d<f32>;
@group(0) @binding(11) var background_tex: texture_2d<f32>;
@group(0) @binding(12) var output_tex: texture_storage_2d<rgba32float, write>;

fn positive_mod(value: i32, divisor: i32) -> i32 {
    // Avoid implementation-dependent signed remainder behaviour on software
    // Vulkan/OpenGL drivers. Tile indices are small enough for exact f32
    // integer conversion, and floor division gives the mathematical modulo
    // required for seamless negative neighbour cells.
    let quotient = i32(floor(f32(value) / f32(divisor)));
    return value - quotient * divisor;
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

fn random_cell(ix: i32, iy: i32, seed: u32, stream: u32) -> f32 {
    return f32(hash_u32(ix, iy, seed, stream) & 0x00FFFFFFu) / 16777216.0;
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

fn wrapped_bilinear_coords(uv: vec2<f32>, size: vec2<i32>) -> BilinearCoords {
    let wrapped = fract(uv);
    let pixel = wrapped * vec2<f32>(size) - vec2<f32>(0.5);
    let base = vec2<i32>(floor(pixel));
    let fraction = fract(pixel);
    return BilinearCoords(
        vec2<i32>(positive_mod(base.x, size.x), positive_mod(base.y, size.y)),
        vec2<i32>(positive_mod(base.x + 1, size.x), positive_mod(base.y, size.y)),
        vec2<i32>(positive_mod(base.x, size.x), positive_mod(base.y + 1, size.y)),
        vec2<i32>(positive_mod(base.x + 1, size.x), positive_mod(base.y + 1, size.y)),
        fraction
    );
}

fn mix_bilinear(a: f32, b: f32, c: f32, d: f32, fraction: vec2<f32>) -> f32 {
    return mix(mix(a, b, fraction.x), mix(c, d, fraction.x), fraction.y);
}

fn sample_pattern_1(uv: vec2<f32>) -> f32 {
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) { return 0.0; }
    let c = local_bilinear_coords(uv, vec2<i32>(textureDimensions(pattern_tex_1)));
    return mix_bilinear(textureLoad(pattern_tex_1, c.p00, 0).r, textureLoad(pattern_tex_1, c.p10, 0).r, textureLoad(pattern_tex_1, c.p01, 0).r, textureLoad(pattern_tex_1, c.p11, 0).r, c.fraction);
}

fn sample_pattern_2(uv: vec2<f32>) -> f32 {
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) { return 0.0; }
    let c = local_bilinear_coords(uv, vec2<i32>(textureDimensions(pattern_tex_2)));
    return mix_bilinear(textureLoad(pattern_tex_2, c.p00, 0).r, textureLoad(pattern_tex_2, c.p10, 0).r, textureLoad(pattern_tex_2, c.p01, 0).r, textureLoad(pattern_tex_2, c.p11, 0).r, c.fraction);
}

fn sample_pattern_3(uv: vec2<f32>) -> f32 {
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) { return 0.0; }
    let c = local_bilinear_coords(uv, vec2<i32>(textureDimensions(pattern_tex_3)));
    return mix_bilinear(textureLoad(pattern_tex_3, c.p00, 0).r, textureLoad(pattern_tex_3, c.p10, 0).r, textureLoad(pattern_tex_3, c.p01, 0).r, textureLoad(pattern_tex_3, c.p11, 0).r, c.fraction);
}

fn sample_pattern_4(uv: vec2<f32>) -> f32 {
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) { return 0.0; }
    let c = local_bilinear_coords(uv, vec2<i32>(textureDimensions(pattern_tex_4)));
    return mix_bilinear(textureLoad(pattern_tex_4, c.p00, 0).r, textureLoad(pattern_tex_4, c.p10, 0).r, textureLoad(pattern_tex_4, c.p01, 0).r, textureLoad(pattern_tex_4, c.p11, 0).r, c.fraction);
}

fn pattern_nearest_coord(uv: vec2<f32>, size: vec2<i32>) -> vec2<i32> {
    return clamp(vec2<i32>(floor(uv * vec2<f32>(size))), vec2<i32>(0), size - vec2<i32>(1));
}

fn sample_pattern_1_nearest(uv: vec2<f32>) -> f32 {
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) { return 0.0; }
    return textureLoad(pattern_tex_1, pattern_nearest_coord(uv, vec2<i32>(textureDimensions(pattern_tex_1))), 0).r;
}

fn sample_pattern_2_nearest(uv: vec2<f32>) -> f32 {
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) { return 0.0; }
    return textureLoad(pattern_tex_2, pattern_nearest_coord(uv, vec2<i32>(textureDimensions(pattern_tex_2))), 0).r;
}

fn sample_pattern_3_nearest(uv: vec2<f32>) -> f32 {
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) { return 0.0; }
    return textureLoad(pattern_tex_3, pattern_nearest_coord(uv, vec2<i32>(textureDimensions(pattern_tex_3))), 0).r;
}

fn sample_pattern_4_nearest(uv: vec2<f32>) -> f32 {
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) { return 0.0; }
    return textureLoad(pattern_tex_4, pattern_nearest_coord(uv, vec2<i32>(textureDimensions(pattern_tex_4))), 0).r;
}

fn pattern_is_minified(dx: vec2<f32>, dy: vec2<f32>, size: vec2<i32>) -> bool {
    let source_size = vec2<f32>(size);
    return max(length(dx * source_size), length(dy * source_size)) > 1.0;
}

fn sample_pattern_1_filtered(uv: vec2<f32>, dx: vec2<f32>, dy: vec2<f32>) -> f32 {
    let size = vec2<i32>(textureDimensions(pattern_tex_1));
    if (!pattern_is_minified(dx, dy, size)) { return sample_pattern_1(uv); }
    let spread = 0.375;
    return (sample_pattern_1_nearest(uv)
        + sample_pattern_1_nearest(uv - dx * spread - dy * spread)
        + sample_pattern_1_nearest(uv + dx * spread - dy * spread)
        + sample_pattern_1_nearest(uv - dx * spread + dy * spread)
        + sample_pattern_1_nearest(uv + dx * spread + dy * spread)) * 0.2;
}

fn sample_pattern_2_filtered(uv: vec2<f32>, dx: vec2<f32>, dy: vec2<f32>) -> f32 {
    let size = vec2<i32>(textureDimensions(pattern_tex_2));
    if (!pattern_is_minified(dx, dy, size)) { return sample_pattern_2(uv); }
    let spread = 0.375;
    return (sample_pattern_2_nearest(uv)
        + sample_pattern_2_nearest(uv - dx * spread - dy * spread)
        + sample_pattern_2_nearest(uv + dx * spread - dy * spread)
        + sample_pattern_2_nearest(uv - dx * spread + dy * spread)
        + sample_pattern_2_nearest(uv + dx * spread + dy * spread)) * 0.2;
}

fn sample_pattern_3_filtered(uv: vec2<f32>, dx: vec2<f32>, dy: vec2<f32>) -> f32 {
    let size = vec2<i32>(textureDimensions(pattern_tex_3));
    if (!pattern_is_minified(dx, dy, size)) { return sample_pattern_3(uv); }
    let spread = 0.375;
    return (sample_pattern_3_nearest(uv)
        + sample_pattern_3_nearest(uv - dx * spread - dy * spread)
        + sample_pattern_3_nearest(uv + dx * spread - dy * spread)
        + sample_pattern_3_nearest(uv - dx * spread + dy * spread)
        + sample_pattern_3_nearest(uv + dx * spread + dy * spread)) * 0.2;
}

fn sample_pattern_4_filtered(uv: vec2<f32>, dx: vec2<f32>, dy: vec2<f32>) -> f32 {
    let size = vec2<i32>(textureDimensions(pattern_tex_4));
    if (!pattern_is_minified(dx, dy, size)) { return sample_pattern_4(uv); }
    let spread = 0.375;
    return (sample_pattern_4_nearest(uv)
        + sample_pattern_4_nearest(uv - dx * spread - dy * spread)
        + sample_pattern_4_nearest(uv + dx * spread - dy * spread)
        + sample_pattern_4_nearest(uv - dx * spread + dy * spread)
        + sample_pattern_4_nearest(uv + dx * spread + dy * spread)) * 0.2;
}

fn sample_scale_map(uv: vec2<f32>) -> f32 {
    let c = wrapped_bilinear_coords(uv, vec2<i32>(textureDimensions(scale_map_tex)));
    return mix_bilinear(textureLoad(scale_map_tex, c.p00, 0).r, textureLoad(scale_map_tex, c.p10, 0).r, textureLoad(scale_map_tex, c.p01, 0).r, textureLoad(scale_map_tex, c.p11, 0).r, c.fraction);
}

fn sample_rotation_map(uv: vec2<f32>) -> f32 {
    let c = wrapped_bilinear_coords(uv, vec2<i32>(textureDimensions(rotation_map_tex)));
    return mix_bilinear(textureLoad(rotation_map_tex, c.p00, 0).r, textureLoad(rotation_map_tex, c.p10, 0).r, textureLoad(rotation_map_tex, c.p01, 0).r, textureLoad(rotation_map_tex, c.p11, 0).r, c.fraction);
}

fn sample_displacement_map(uv: vec2<f32>) -> f32 {
    let c = wrapped_bilinear_coords(uv, vec2<i32>(textureDimensions(displacement_map_tex)));
    return mix_bilinear(textureLoad(displacement_map_tex, c.p00, 0).r, textureLoad(displacement_map_tex, c.p10, 0).r, textureLoad(displacement_map_tex, c.p01, 0).r, textureLoad(displacement_map_tex, c.p11, 0).r, c.fraction);
}

fn sample_mask_map(uv: vec2<f32>) -> f32 {
    let c = wrapped_bilinear_coords(uv, vec2<i32>(textureDimensions(mask_map_tex)));
    return mix_bilinear(textureLoad(mask_map_tex, c.p00, 0).r, textureLoad(mask_map_tex, c.p10, 0).r, textureLoad(mask_map_tex, c.p01, 0).r, textureLoad(mask_map_tex, c.p11, 0).r, c.fraction);
}

fn sample_distribution_map(uv: vec2<f32>) -> f32 {
    let c = wrapped_bilinear_coords(uv, vec2<i32>(textureDimensions(distribution_map_tex)));
    return mix_bilinear(textureLoad(distribution_map_tex, c.p00, 0).r, textureLoad(distribution_map_tex, c.p10, 0).r, textureLoad(distribution_map_tex, c.p01, 0).r, textureLoad(distribution_map_tex, c.p11, 0).r, c.fraction);
}

fn sample_vector_map(uv: vec2<f32>) -> vec2<f32> {
    let c = wrapped_bilinear_coords(uv, vec2<i32>(textureDimensions(vector_map_tex)));
    let top = mix(textureLoad(vector_map_tex, c.p00, 0).rg, textureLoad(vector_map_tex, c.p10, 0).rg, c.fraction.x);
    let bottom = mix(textureLoad(vector_map_tex, c.p01, 0).rg, textureLoad(vector_map_tex, c.p11, 0).rg, c.fraction.x);
    return mix(top, bottom, c.fraction.y);
}

fn connected_count(mask: u32) -> u32 {
    var count = 0u;
    for (var index = 0u; index < 4u; index = index + 1u) {
        if ((mask & (1u << index)) != 0u) { count = count + 1u; }
    }
    return count;
}

fn pattern_from_ordinal(mask: u32, ordinal: u32) -> u32 {
    var seen = 0u;
    for (var index = 0u; index < 4u; index = index + 1u) {
        if ((mask & (1u << index)) != 0u) {
            if (seen == ordinal) { return index; }
            seen = seen + 1u;
        }
    }
    return 0u;
}

fn tile_shape(
    pattern: u32,
    local: vec2<f32>,
    feather: f32,
    pattern_dx: vec2<f32>,
    pattern_dy: vec2<f32>,
    antialiased_input: bool
) -> f32 {
    let uv = local * 0.5 + vec2<f32>(0.5);
    if (pattern == 0u) {
        if (antialiased_input) { return sample_pattern_1_filtered(uv, pattern_dx, pattern_dy); }
        return sample_pattern_1_nearest(uv);
    }
    if (pattern == 1u) {
        if (antialiased_input) { return sample_pattern_2_filtered(uv, pattern_dx, pattern_dy); }
        return sample_pattern_2_nearest(uv);
    }
    if (pattern == 2u) {
        if (antialiased_input) { return sample_pattern_3_filtered(uv, pattern_dx, pattern_dy); }
        return sample_pattern_3_nearest(uv);
    }
    if (pattern == 3u) {
        if (antialiased_input) { return sample_pattern_4_filtered(uv, pattern_dx, pattern_dy); }
        return sample_pattern_4_nearest(uv);
    }
    if (pattern == 8u) {
        let radius_squared = dot(local, local);
        let profile = exp(-3.5 * radius_squared);
        let edge = 1.0 - sqrt(radius_squared);
        if (feather <= 0.0) { return select(0.0, profile, edge >= 0.0); }
        return profile * clamp(edge / feather + 0.5, 0.0, 1.0);
    }

    var edge = 0.0;
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
        edge = 1.0 - abs(local.x) - abs(local.y);
    } else if (pattern == 10u) {
        let a = abs(local);
        edge = 1.0 - max(a.y, a.x * 0.8660254 + a.y * 0.5);
    } else if (pattern == 11u) {
        edge = min(1.0 - local.y, local.y + 1.0 - 2.0 * abs(local.x));
    } else {
        edge = 1.0 - max(abs(local.x), abs(local.y));
    }
    if (feather <= 0.0) { return select(0.0, 1.0, edge >= 0.0); }
    return clamp(edge / feather + 0.5, 0.0, 1.0);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }

    let x_amount = max(i32(params.p1.x), 1);
    let y_amount = max(i32(params.p1.y), 1);
    let seed = u32(max(params.p1.z, 0.0));
    let non_square = params.p1.w >= 0.5;
    let authored_pattern = u32(params.p2.x);
    let selection_mode = u32(params.p2.y);
    let connected_mask = u32(params.p2.z);
    let edge_softness = max(params.p2.w, 0.0);
    let size_x = clamp(params.p3.x, 0.001, 8.0);
    let size_y = clamp(params.p3.y, 0.001, 8.0);
    let scale = clamp(params.p3.z, 0.001, 4.0);
    let scale_random = clamp(params.p3.w, 0.0, 1.0);
    let scale_map_strength = clamp(params.p4.x, 0.0, 1.0);
    let vector_scale_strength = clamp(params.p4.y, 0.0, 1.0);
    let position_random_x = clamp(params.p4.z, 0.0, 1.0);
    let position_random_y = clamp(params.p4.w, 0.0, 1.0);
    let offset_mode = u32(params.p5.x);
    let row_offset = clamp(params.p5.y, 0.0, 1.0);
    let global_offset = params.p5.zw;
    let displacement_intensity = clamp(params.p6.x, 0.0, 2.0);
    let displacement_angle = params.p6.y * 0.017453292519943295;
    let vector_displacement = clamp(params.p6.z, 0.0, 2.0);
    let rotation = params.p6.w;
    let rotation_random = clamp(params.p7.x, 0.0, 180.0);
    let rotation_map_multiplier = clamp(params.p7.y, -720.0, 720.0);
    let mask_random = clamp(params.p7.z, 0.0, 1.0);
    let mask_threshold = clamp(params.p7.w, 0.0, 1.0);
    let luminance_random = clamp(params.p8.y, 0.0, 1.0);
    let opacity = clamp(params.p8.z, 0.0, 1.0);
    let blend_mode = u32(params.p8.w);
    let background_value = clamp(params.p9.x, 0.0, 1.0);
    let mirror_x_random = params.p9.y >= 0.5;
    let mirror_y_random = params.p9.z >= 0.5;
    let mask_flags = u32(params.p9.w);
    let invert_mask = (mask_flags & 1u) != 0u;
    let mask_connected = (mask_flags & 2u) != 0u;
    let antialiased_input = (mask_flags & 4u) != 0u;
    let layout_mask = (mask_flags >> 3u) & 3u;
    let invert_layout_mask = (mask_flags & 32u) != 0u;
    let candidate_radius = clamp(i32(params.p10.x), 1, 64);
    let rendering_order = u32(params.p10.y);
    let reverse_order = params.p10.z >= 0.5;
    let background_connected = params.p10.w >= 0.5;

    let coord = vec2<i32>(gid.xy);
    var result = background_value;
    if (background_connected) { result = textureLoad(background_tex, coord, 0).r; }

    let uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / vec2<f32>(f32(width), f32(height));
    let grid = uv * vec2<f32>(f32(x_amount), f32(y_amount)) - global_offset;
    let base = vec2<i32>(floor(grid));
    let cell_pixels = vec2<f32>(f32(width) / f32(x_amount), f32(height) / f32(y_amount));
    let pixel_basis = max(min(cell_pixels.x, cell_pixels.y), 0.000001);
    // p2.w is already the complete effective feather prepared by the backend:
    // authored Edge Softness in Pixel Exact mode, or authored softness plus
    // the one-pixel coverage footprint in Antialiased mode. Re-applying the
    // pixel footprint here made the GPU path antialiased in both modes.
    let feather = edge_softness;
    let diameter = candidate_radius * 2 + 1;
    let candidate_count = diameter * diameter;

    for (var iteration = 0; iteration < candidate_count; iteration = iteration + 1) {
        let candidate_index = select(iteration, candidate_count - 1 - iteration, reverse_order);
        let major = candidate_index / diameter;
        let minor = candidate_index % diameter;
        var ox = minor - candidate_radius;
        var oy = major - candidate_radius;
        if (rendering_order == 1u) {
            ox = major - candidate_radius;
            oy = minor - candidate_radius;
        }

        let cell = base + vec2<i32>(ox, oy);
        let canonical = vec2<i32>(positive_mod(cell.x, x_amount), positive_mod(cell.y, y_amount));
        var shift = vec2<f32>(0.0);
        if (offset_mode == 1u && (canonical.y & 1) == 1) {
            shift.x = row_offset;
        } else if (offset_mode == 2u && (canonical.x & 1) == 1) {
            shift.y = row_offset;
        } else if (offset_mode == 3u) {
            shift.x = fract(f32(canonical.y) * row_offset);
        } else if (offset_mode == 4u) {
            shift.y = fract(f32(canonical.x) * row_offset);
        }

        var centre = vec2<f32>(cell) + vec2<f32>(0.5) + shift
            + vec2<f32>(
                (random_cell(canonical.x, canonical.y, seed, 1u) - 0.5) * position_random_x,
                (random_cell(canonical.x, canonical.y, seed, 2u) - 0.5) * position_random_y
            );
        let map_uv = fract((centre + global_offset) / vec2<f32>(f32(x_amount), f32(y_amount)));
        var scale_map_value = 1.0;
        if (scale_map_strength > 0.0) { scale_map_value = sample_scale_map(map_uv); }
        var rotation_map_value = 0.0;
        if (abs(rotation_map_multiplier) > 0.000001) { rotation_map_value = sample_rotation_map(map_uv); }
        var displacement_map_value = 0.0;
        if (displacement_intensity > 0.0) { displacement_map_value = sample_displacement_map(map_uv); }
        var vector_map_value = vec2<f32>(0.5);
        if (vector_scale_strength > 0.0 || vector_displacement > 0.0) { vector_map_value = sample_vector_map(map_uv); }
        var mask_map_value = 1.0;
        if (mask_connected) { mask_map_value = sample_mask_map(map_uv); }
        var distribution_value = 0.0;
        if (selection_mode == 3u && connected_count(connected_mask) > 0u) {
            distribution_value = sample_distribution_map(map_uv);
        }

        centre = centre + vec2<f32>(cos(displacement_angle), sin(displacement_angle))
            * displacement_map_value * displacement_intensity;
        centre = centre + (vector_map_value * 2.0 - vec2<f32>(1.0)) * vector_displacement;

        let random_scale = max(0.05, 1.0 + (random_cell(canonical.x, canonical.y, seed, 3u) * 2.0 - 1.0) * scale_random);
        let scalar_map_scale = mix(1.0, max(scale_map_value, 0.001), scale_map_strength);
        let vector_scale = mix(vec2<f32>(1.0), vec2<f32>(0.75) + vector_map_value * 0.5, vector_scale_strength);
        let half_size = max(vec2<f32>(size_x, size_y) * scale * random_scale * scalar_map_scale * vector_scale * 0.5, vec2<f32>(0.00001));
        var local = (grid - centre) / half_size;
        if (non_square) { local = local * cell_pixels / pixel_basis; }

        var local_step = vec2<f32>(f32(x_amount) / f32(width), f32(y_amount) / f32(height)) / half_size;
        if (non_square) { local_step = local_step * cell_pixels / pixel_basis; }

        let angle = (rotation
            + (random_cell(canonical.x, canonical.y, seed, 4u) * 2.0 - 1.0) * rotation_random
            + rotation_map_value * rotation_map_multiplier) * 0.017453292519943295;
        let cosine = cos(angle);
        let sine = sin(angle);
        var rotated = vec2<f32>(cosine * local.x + sine * local.y, -sine * local.x + cosine * local.y);
        var pattern_dx = vec2<f32>(cosine * local_step.x, -sine * local_step.x) * 0.5;
        var pattern_dy = vec2<f32>(sine * local_step.y, cosine * local_step.y) * 0.5;
        if (mirror_x_random && random_cell(canonical.x, canonical.y, seed, 5u) >= 0.5) {
            rotated.x = -rotated.x;
            pattern_dx.x = -pattern_dx.x;
            pattern_dy.x = -pattern_dy.x;
        }
        if (mirror_y_random && random_cell(canonical.x, canonical.y, seed, 6u) >= 0.5) {
            rotated.y = -rotated.y;
            pattern_dx.y = -pattern_dx.y;
            pattern_dy.y = -pattern_dy.y;
        }

        var actual_pattern = authored_pattern;
        let input_count = connected_count(connected_mask);
        if (selection_mode != 0u && input_count > 0u) {
            var ordinal = 0u;
            if (selection_mode == 1u) {
                ordinal = min(u32(random_cell(canonical.x, canonical.y, seed, 9u) * f32(input_count)), input_count - 1u);
            } else if (selection_mode == 2u) {
                ordinal = u32(canonical.y * x_amount + canonical.x) % input_count;
            } else {
                ordinal = min(u32(clamp(distribution_value, 0.0, 0.999999) * f32(input_count)), input_count - 1u);
            }
            actual_pattern = pattern_from_ordinal(connected_mask, ordinal);
        } else if (selection_mode != 0u && actual_pattern < 4u) {
            actual_pattern = 4u;
        }

        var coverage = tile_shape(actual_pattern, rotated, feather, pattern_dx, pattern_dy, antialiased_input);
        if (random_cell(canonical.x, canonical.y, seed, 7u) < mask_random) { coverage = 0.0; }
        var layout_visible = true;
        if (layout_mask == 1u) {
            layout_visible = ((canonical.x + canonical.y) & 1) == 0;
        } else if (layout_mask == 2u) {
            layout_visible = (canonical.y & 1) == 0;
        } else if (layout_mask == 3u) {
            layout_visible = (canonical.x & 1) == 0;
        }
        if (invert_layout_mask) { layout_visible = !layout_visible; }
        if (!layout_visible) { coverage = 0.0; }
        if (mask_connected) {
            var map_visible = mask_map_value >= mask_threshold;
            if (invert_mask) { map_visible = !map_visible; }
            if (!map_visible) { coverage = 0.0; }
        }

        let random_luminance = random_cell(canonical.x, canonical.y, seed, 8u);
        // 0 -> untouched white tiles, 0.5 -> 0.5..1, 1 -> 0..1.
        let value = mix(1.0, random_luminance, luminance_random);
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

    let value = clamp(result, 0.0, 1.0);
    textureStore(output_tex, coord, vec4<f32>(value, value, value, 1.0));
}
