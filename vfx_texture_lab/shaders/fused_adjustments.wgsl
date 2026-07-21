struct Params {
    p0: vec4<f32>,
    info: vec4<f32>,
    ops: array<vec4<f32>, 16>,
};

@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

fn quantize_result(value: vec4<f32>, mode: i32) -> vec4<f32> {
    if (mode == 1) {
        return vec4<f32>(quantizeToF16(value.r), quantizeToF16(value.g), quantizeToF16(value.b), quantizeToF16(value.a));
    }
    if (mode == 2) {
        let half_value = vec4<f32>(
            quantizeToF16(value.r), quantizeToF16(value.g),
            quantizeToF16(value.b), quantizeToF16(value.a)
        );
        return round(clamp(half_value, vec4<f32>(0.0), vec4<f32>(1.0)) * 255.0) / 255.0;
    }
    return value;
}

fn apply_scalar(value: f32, mode: i32, a: f32, b: f32) -> f32 {
    if (mode == 1) { return value + a; }
    if (mode == 2) {
        let factor = pow(2.0, clamp(a, -1.0, 1.0) * 3.0);
        return (value - b) * factor + b;
    }
    if (mode == 3) { return value * pow(2.0, a); }
    if (mode == 4) { return pow(max(value, 0.0), 1.0 / max(a, 0.00001)); }
    if (mode == 5) {
        let steps = max(round(a), 2.0);
        return round(clamp(value, 0.0, 1.0) * (steps - 1.0)) / (steps - 1.0);
    }
    if (mode == 6) {
        let low = min(a, b);
        let high = max(a, b);
        return clamp(value, low, high);
    }
    return value;
}

fn apply_levels(value: f32, a: vec4<f32>, b: vec4<f32>) -> f32 {
    let in_low = a.y;
    let in_high = max(a.z, in_low + 0.000001);
    let in_mid = clamp(a.w, 0.00001, 0.99999);
    let out_low = b.x;
    let out_high = b.y;
    let intermediary_clamp = b.z > 0.5;
    let raw = (value - in_low) / (in_high - in_low);
    let exponent = log(0.5) / log(in_mid);
    var shaped: f32;
    if (intermediary_clamp) {
        shaped = pow(clamp(raw, 0.0, 1.0), exponent);
    } else if (raw < 0.0 || raw > 1.0) {
        shaped = raw;
    } else {
        shaped = pow(raw, exponent);
    }
    return out_low + shaped * (out_high - out_low);
}

fn apply_operation(source: vec4<f32>, a: vec4<f32>, b: vec4<f32>) -> vec4<f32> {
    let mode = i32(a.x + 0.5);
    var result = source;
    if (mode == 0) {
        result = vec4<f32>(vec3<f32>(1.0) - source.rgb, source.a);
    } else if (mode >= 1 && mode <= 6) {
        result = vec4<f32>(
            apply_scalar(source.r, mode, a.y, a.z),
            apply_scalar(source.g, mode, a.y, a.z),
            apply_scalar(source.b, mode, a.y, a.z),
            source.a
        );
    } else if (mode == 7) {
        result = vec4<f32>(
            apply_levels(source.r, a, b),
            apply_levels(source.g, a, b),
            apply_levels(source.b, a, b),
            source.a
        );
    } else if (mode == 8) {
        let range_amount = clamp(a.y, 0.0, 1.0);
        let position = clamp(a.z, 0.0, 1.0);
        let low = (1.0 - range_amount) * position;
        let value = low + clamp(source.r, 0.0, 1.0) * range_amount;
        result = vec4<f32>(value, value, value, 1.0);
    } else if (mode == 9) {
        let position = a.y - floor(a.y);
        let value = source.r + position - floor(source.r + position);
        result = vec4<f32>(value, value, value, 1.0);
    } else if (mode == 10) {
        let position = clamp(a.y, 0.0, 1.0);
        let contrast = clamp(a.z, 0.0, 1.0);
        let edge0 = 1.0 - position;
        let width = max(1.0 - contrast, 0.000001);
        var t = clamp((source.r - edge0) / width, 0.0, 1.0);
        t = t * t * (3.0 - 2.0 * t);
        result = vec4<f32>(t, t, t, 1.0);
    }
    return quantize_result(result, i32(b.w + 0.5));
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let coord = vec2<i32>(gid.xy);
    var value = textureLoad(input_tex, coord, 0);
    let count = clamp(i32(params.info.x + 0.5), 0, 8);
    for (var index: i32 = 0; index < 8; index = index + 1) {
        if (index < count) {
            value = apply_operation(value, params.ops[u32(index * 2)], params.ops[u32(index * 2 + 1)]);
        }
    }
    textureStore(output_tex, coord, value);
}
