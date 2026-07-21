// Shared typed transform resampling. The including shader must declare `input_tex`.
fn wrap_index(value: i32, size: i32) -> i32 {
    if (size <= 1) { return 0; }
    return value - i32(floor(f32(value) / f32(size))) * size;
}
fn mirror_index(value: i32, size: i32) -> i32 {
    if (size <= 1) { return 0; }
    let period = size * 2;
    let wrapped = wrap_index(value, period);
    return select(period - 1 - wrapped, wrapped, wrapped < size);
}
fn load_raw(coord: vec2<i32>, size: vec2<i32>, boundary: i32) -> vec4<f32> {
    if (boundary == 0 && (any(coord < vec2<i32>(0)) || any(coord >= size))) { return vec4<f32>(0.0); }
    var c = coord;
    if (boundary == 2) {
        c = vec2<i32>(wrap_index(c.x, size.x), wrap_index(c.y, size.y));
    } else if (boundary == 3) {
        c = vec2<i32>(mirror_index(c.x, size.x), mirror_index(c.y, size.y));
    } else {
        c = clamp(c, vec2<i32>(0), size - vec2<i32>(1));
    }
    return textureLoad(input_tex, c, 0);
}
fn prepare(value: vec4<f32>, kind: i32) -> vec4<f32> {
    if (kind == 1) { return vec4<f32>(value.rgb * value.a, value.a); }
    if (kind == 2) { return vec4<f32>(value.rgb * 2.0 - vec3<f32>(1.0), value.a); }
    return value;
}
fn finish(value: vec4<f32>, kind: i32) -> vec4<f32> {
    if (kind == 1) {
        let rgb = select(vec3<f32>(0.0), value.rgb / max(value.a, 1e-7), value.a > 1e-7);
        return vec4<f32>(rgb, value.a);
    }
    if (kind == 2) {
        var n = value.rgb; let l = length(n);
        n = select(vec3<f32>(0.0, 0.0, 1.0), n / max(l, 1e-7), l > 1e-7);
        return vec4<f32>(n * 0.5 + vec3<f32>(0.5), value.a);
    }
    return value;
}
fn load_typed(coord: vec2<i32>, size: vec2<i32>, boundary: i32, kind: i32) -> vec4<f32> {
    if (boundary == 0 && (any(coord < vec2<i32>(0)) || any(coord >= size))) {
        return select(vec4<f32>(0.0), vec4<f32>(0.0, 0.0, 1.0, 0.0), kind == 2);
    }
    return prepare(load_raw(coord, size, boundary), kind);
}
fn sample_nearest(pixel: vec2<f32>, size: vec2<i32>, boundary: i32, kind: i32) -> vec4<f32> {
    return finish(load_typed(vec2<i32>(floor(pixel + vec2<f32>(0.5))), size, boundary, kind), kind);
}
fn sample_bilinear_working(pixel: vec2<f32>, size: vec2<i32>, boundary: i32, kind: i32) -> vec4<f32> {
    let base_f = floor(pixel); let base = vec2<i32>(base_f); let f = pixel - base_f;
    let a = load_typed(base, size, boundary, kind);
    let b = load_typed(base + vec2<i32>(1, 0), size, boundary, kind);
    let c = load_typed(base + vec2<i32>(0, 1), size, boundary, kind);
    let d = load_typed(base + vec2<i32>(1, 1), size, boundary, kind);
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}
fn sample_bilinear(pixel: vec2<f32>, size: vec2<i32>, boundary: i32, kind: i32) -> vec4<f32> {
    return finish(sample_bilinear_working(pixel, size, boundary, kind), kind);
}
fn cubic_weight(d: f32) -> f32 {
    let x = abs(d); let x2 = x*x; let x3 = x2*x;
    if (x < 1.0) { return (7.0*x3 - 12.0*x2 + 5.3333333333) / 6.0; }
    if (x < 2.0) { return ((-2.3333333333)*x3 + 12.0*x2 - 20.0*x + 10.6666666667) / 6.0; }
    return 0.0;
}
fn sample_bicubic(pixel: vec2<f32>, size: vec2<i32>, boundary: i32, kind: i32) -> vec4<f32> {
    let base = vec2<i32>(floor(pixel));
    var result = vec4<f32>(0.0); var total = 0.0;
    for (var oy = -1; oy <= 2; oy = oy + 1) {
        let wy = cubic_weight(pixel.y - f32(base.y + oy));
        for (var ox = -1; ox <= 2; ox = ox + 1) {
            let w = wy * cubic_weight(pixel.x - f32(base.x + ox));
            result += load_typed(base + vec2<i32>(ox, oy), size, boundary, kind) * w;
            total += w;
        }
    }
    return finish(result / max(total, 1e-7), kind);
}
fn sample_auto(pixel: vec2<f32>, size: vec2<i32>, boundary: i32, kind: i32, footprint: vec2<f32>) -> vec4<f32> {
    let fp = max(max(footprint.x, footprint.y), 1.0);
    if (fp <= 1.05) { return sample_bicubic(pixel, size, boundary, kind); }
    var result = vec4<f32>(0.0);
    if (fp <= 2.5) {
        let spread = min(footprint, vec2<f32>(8.0));
        result += sample_bilinear_working(pixel + vec2<f32>(-0.25, -0.25) * spread, size, boundary, kind);
        result += sample_bilinear_working(pixel + vec2<f32>( 0.25, -0.25) * spread, size, boundary, kind);
        result += sample_bilinear_working(pixel + vec2<f32>(-0.25,  0.25) * spread, size, boundary, kind);
        result += sample_bilinear_working(pixel + vec2<f32>( 0.25,  0.25) * spread, size, boundary, kind);
        return finish(result * 0.25, kind);
    }
    let spread = min(footprint, vec2<f32>(8.0));
    for (var y = -1; y <= 1; y = y + 1) {
        for (var x = -1; x <= 1; x = x + 1) {
            result += sample_bilinear_working(pixel + vec2<f32>(f32(x), f32(y)) * spread / 3.0, size, boundary, kind);
        }
    }
    return finish(result / 9.0, kind);
}
fn sample_filtered(pixel: vec2<f32>, size: vec2<i32>, boundary: i32, kind: i32, filtering: i32, footprint: vec2<f32>) -> vec4<f32> {
    if (filtering == 1) { return sample_nearest(pixel, size, boundary, kind); }
    if (filtering == 2) { return sample_bilinear(pixel, size, boundary, kind); }
    if (filtering == 3) { return sample_bicubic(pixel, size, boundary, kind); }
    return sample_auto(pixel, size, boundary, kind, footprint);
}
