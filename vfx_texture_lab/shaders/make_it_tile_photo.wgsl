struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var source_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

fn wrap_index(value: i32, size: i32) -> i32 { return ((value % size) + size) % size; }
fn sample_wrap(tex: texture_2d<f32>, pixel: vec2<f32>, size: vec2<i32>) -> vec4<f32> {
    let base = vec2<i32>(floor(pixel));
    let f = fract(pixel);
    let x0 = wrap_index(base.x, size.x); let y0 = wrap_index(base.y, size.y);
    let x1 = wrap_index(base.x + 1, size.x); let y1 = wrap_index(base.y + 1, size.y);
    let a = textureLoad(tex, vec2<i32>(x0, y0), 0);
    let b = textureLoad(tex, vec2<i32>(x1, y0), 0);
    let c = textureLoad(tex, vec2<i32>(x0, y1), 0);
    let d = textureLoad(tex, vec2<i32>(x1, y1), 0);
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}
fn renormalise(value: vec4<f32>) -> vec4<f32> {
    var n = value.rgb * 2.0 - vec3<f32>(1.0);
    let l = length(n);
    n = select(vec3<f32>(0.0, 0.0, 1.0), n / max(l, 1e-6), l > 1e-6);
    return vec4<f32>(n * 0.5 + vec3<f32>(0.5), value.a);
}
fn smooth_curve(value: f32) -> f32 {
    let t = clamp(value, 0.0, 1.0);
    return t * t * (3.0 - 2.0 * t);
}
fn periodic_warp(value: f32, phase: f32) -> f32 {
    let tau = 6.283185307179586;
    return clamp(
        sin(tau * (3.0 * value + phase)) * 0.45
        + sin(tau * (7.0 * value + phase * 1.73 + 0.19)) * 0.25
        + sin(tau * (13.0 * value + phase * 2.41 + 0.37)) * 0.15
        + sin(tau * (29.0 * value + phase * 3.17 + 0.11)) * 0.10
        + sin(tau * (53.0 * value + phase * 4.03 + 0.43)) * 0.05,
        -1.0,
        1.0
    );
}
fn edge_mask(distance: f32, cross_axis: f32, size: f32, sharpness: f32, warping: f32, phase: f32) -> f32 {
    let warp_strength = clamp(warping, 0.0, 100.0) / 100.0;
    let local_size = clamp(size, 0.001, 0.5) * clamp(
        1.0 + periodic_warp(cross_axis, phase) * warp_strength * 0.72,
        0.2,
        1.8
    );
    let t = clamp(distance / max(local_size, 1e-6), 0.0, 1.0);
    let authored_precision = clamp(sharpness, 0.0, 1.0);
    let cut = 0.52 + authored_precision * 0.30;
    let feather = 0.46 * (1.0 - authored_precision) + 0.018;
    let blend = smooth_curve((t - (cut - feather)) / max(feather * 2.0, 1e-6));
    return 1.0 - blend;
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let size = vec2<i32>(i32(params.p0.x), i32(params.p0.y));
    if (i32(gid.x) >= size.x || i32(gid.y) >= size.y) { return; }
    let coord = vec2<f32>(gid.xy);
    let uv = (coord + vec2<f32>(0.5)) / vec2<f32>(size);
    let horizontal = params.p2.w >= 0.5;
    let vertical = params.p3.x >= 0.5;

    let edge_x = min(uv.x, 1.0 - uv.x);
    let edge_y = min(uv.y, 1.0 - uv.y);
    let mask_x = select(
        0.0,
        edge_mask(edge_x, uv.y, params.p1.x, params.p1.y, params.p1.z, 0.071),
        horizontal
    );
    let mask_y = select(
        0.0,
        edge_mask(edge_y, uv.x, params.p2.x, params.p2.y, params.p2.z, 0.413),
        vertical
    );

    let half_shift = vec2<f32>(f32(size.x) * 0.5, f32(size.y) * 0.5);
    let original = sample_wrap(source_tex, coord, size);
    let horizontal_copy = sample_wrap(source_tex, coord + vec2<f32>(half_shift.x, 0.0), size);
    let vertical_copy = sample_wrap(source_tex, coord + vec2<f32>(0.0, half_shift.y), size);
    let diagonal_copy = sample_wrap(source_tex, coord + half_shift, size);

    var result = original * (1.0 - mask_x) * (1.0 - mask_y)
        + horizontal_copy * mask_x * (1.0 - mask_y)
        + vertical_copy * (1.0 - mask_x) * mask_y
        + diagonal_copy * mask_x * mask_y;
    let kind = i32(params.p1.w + 0.5);
    if (kind == 2) { result = renormalise(result); }
    if (kind == 0) { result = vec4<f32>(result.r, result.r, result.r, 1.0); }
    textureStore(output_tex, vec2<i32>(gid.xy), clamp(result, vec4<f32>(0.0), vec4<f32>(1.0)));
}
