struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

fn adjust(value: f32) -> f32 {
    let mode = i32(params.p1.x + 0.5);
    let a = params.p1.y;
    let b = params.p1.z;
    if (mode == 0) { return value + a; }
    if (mode == 1) {
        let factor = pow(2.0, clamp(a, -1.0, 1.0) * 3.0);
        return (value - b) * factor + b;
    }
    if (mode == 2) { return value * pow(2.0, a); }
    if (mode == 3) { return pow(max(value, 0.0), 1.0 / max(a, 0.00001)); }
    if (mode == 4) {
        let steps = max(round(a), 2.0);
        return round(clamp(value, 0.0, 1.0) * (steps - 1.0)) / (steps - 1.0);
    }
    let low = min(a, b);
    let high = max(a, b);
    return clamp(value, low, high);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let coord = vec2<i32>(gid.xy);
    let source = textureLoad(input_tex, coord, 0);
    let rgb = vec3<f32>(adjust(source.r), adjust(source.g), adjust(source.b));
    textureStore(output_tex, coord, vec4<f32>(rgb, source.a));
}
