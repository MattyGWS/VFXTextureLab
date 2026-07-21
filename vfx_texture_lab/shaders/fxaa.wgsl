struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

fn linear_to_srgb(v: vec3<f32>) -> vec3<f32> {
    let x = max(v, vec3<f32>(0.0));
    return select(1.055 * pow(x, vec3<f32>(1.0 / 2.4)) - 0.055, x * 12.92, x <= vec3<f32>(0.0031308));
}
fn srgb_to_linear(v: vec3<f32>) -> vec3<f32> {
    let x = clamp(v, vec3<f32>(0.0), vec3<f32>(1.0));
    return select(pow((x + 0.055) / 1.055, vec3<f32>(2.4)), x / 12.92, x <= vec3<f32>(0.04045));
}
fn load_clamped(c: vec2<i32>, size: vec2<i32>) -> vec4<f32> {
    return textureLoad(input_tex, clamp(c, vec2<i32>(0), size - vec2<i32>(1)), 0);
}
fn sample_raw(pixel: vec2<f32>, size: vec2<i32>) -> vec4<f32> {
    let p = clamp(pixel, vec2<f32>(0.0), vec2<f32>(size - vec2<i32>(1)));
    let i0 = vec2<i32>(floor(p));
    let i1 = min(i0 + vec2<i32>(1), size - vec2<i32>(1));
    let f = fract(p);
    let a = textureLoad(input_tex, i0, 0);
    let b = textureLoad(input_tex, vec2<i32>(i1.x, i0.y), 0);
    let c = textureLoad(input_tex, vec2<i32>(i0.x, i1.y), 0);
    let d = textureLoad(input_tex, i1, 0);
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}
fn working(value: vec4<f32>, kind: i32) -> vec4<f32> {
    if (kind == 1) {
        return vec4<f32>(linear_to_srgb(clamp(value.rgb, vec3<f32>(0.0), vec3<f32>(1.0))), value.a);
    }
    if (kind == 2) {
        let n = value.rgb * 2.0 - vec3<f32>(1.0);
        return vec4<f32>(normalize(n), value.a);
    }
    return vec4<f32>(value.r, value.r, value.r, 1.0);
}
fn sample_working(pixel: vec2<f32>, size: vec2<i32>, kind: i32) -> vec4<f32> {
    return working(sample_raw(pixel, size), kind);
}
fn luma(value: vec4<f32>, kind: i32) -> f32 {
    if (kind == 2) { return clamp(value.z * 0.5 + 0.5, 0.0, 1.0); }
    return dot(value.rgb, vec3<f32>(0.2126, 0.7152, 0.0722));
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let size = vec2<i32>(i32(params.p0.x), i32(params.p0.y));
    if (i32(gid.x) >= size.x || i32(gid.y) >= size.y) { return; }
    let c = vec2<i32>(gid.xy);
    let pixel = vec2<f32>(c);
    let kind = i32(params.p1.x + 0.5);
    let quality = i32(params.p1.y + 0.5);
    let source_raw = load_clamped(c, size);
    let source = working(source_raw, kind);

    let centre = luma(source, kind);
    let nw = luma(sample_working(pixel + vec2<f32>(-1.0, -1.0), size, kind), kind);
    let ne = luma(sample_working(pixel + vec2<f32>( 1.0, -1.0), size, kind), kind);
    let sw = luma(sample_working(pixel + vec2<f32>(-1.0,  1.0), size, kind), kind);
    let se = luma(sample_working(pixel + vec2<f32>( 1.0,  1.0), size, kind), kind);
    let north = luma(sample_working(pixel + vec2<f32>(0.0, -1.0), size, kind), kind);
    let south = luma(sample_working(pixel + vec2<f32>(0.0,  1.0), size, kind), kind);
    let west = luma(sample_working(pixel + vec2<f32>(-1.0, 0.0), size, kind), kind);
    let east = luma(sample_working(pixel + vec2<f32>( 1.0, 0.0), size, kind), kind);

    let local_min = min(centre, min(min(north, south), min(min(west, east), min(min(nw, ne), min(sw, se)))));
    let local_max = max(centre, max(max(north, south), max(max(west, east), max(max(nw, ne), max(sw, se)))));
    let contrast = local_max - local_min;
    let is_edge = contrast >= max(params.p1.z, local_max * params.p1.w);

    var direction = vec2<f32>(-((nw + ne) - (sw + se)), (nw + sw) - (ne + se));
    let diagonal_average = (nw + ne + sw + se) * 0.25;
    var span = 8.0;
    var reduce_mul = 1.0 / 8.0;
    var reduce_min = 1.0 / 128.0;
    if (quality >= 2) {
        span = 12.0;
    } else if (quality <= 0) {
        span = 4.0;
        reduce_mul = 1.0 / 4.0;
        reduce_min = 1.0 / 64.0;
    }
    let direction_reduce = max(diagonal_average * reduce_mul, reduce_min);
    let reciprocal_min = 1.0 / (min(abs(direction.x), abs(direction.y)) + direction_reduce);
    direction = clamp(direction * reciprocal_min, vec2<f32>(-span), vec2<f32>(span));

    let sample_a = sample_working(pixel + direction * (1.0 / 3.0 - 0.5), size, kind);
    let sample_b = sample_working(pixel + direction * (2.0 / 3.0 - 0.5), size, kind);
    let narrow = (sample_a + sample_b) * 0.5;
    var candidate = narrow;
    if (quality >= 1) {
        let outer_a = sample_working(pixel - direction * 0.5, size, kind);
        let outer_b = sample_working(pixel + direction * 0.5, size, kind);
        let wide = narrow * 0.5 + (outer_a + outer_b) * 0.25;
        let wide_luma = luma(wide, kind);
        candidate = select(wide, narrow, wide_luma < local_min || wide_luma > local_max);
    }

    let edge_strength = clamp(contrast / max(local_max, 0.000001), 0.0, 1.0);
    let blend = select(0.0, edge_strength * params.p2.x, is_edge);
    var result = mix(source, candidate, blend);
    if (kind == 1) {
        result = vec4<f32>(srgb_to_linear(clamp(result.rgb, vec3<f32>(0.0), vec3<f32>(1.0))), result.a);
    } else if (kind == 2) {
        result = vec4<f32>(normalize(result.rgb) * 0.5 + vec3<f32>(0.5), result.a);
    } else {
        result = vec4<f32>(result.r, result.r, result.r, 1.0);
    }
    if (params.p2.y >= 0.5) { result.a = source_raw.a; }
    textureStore(output_tex, c, clamp(result, vec4<f32>(0.0), vec4<f32>(1.0)));
}
