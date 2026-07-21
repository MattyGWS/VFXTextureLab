struct Params {
    p0: vec4<f32>,
    p1: vec4<f32>,
    p2: vec4<f32>,
    p3: vec4<f32>,
    p4: vec4<f32>,
    p5: vec4<f32>,
};
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

fn curve_point(index: i32) -> vec2<f32> {
    if (index == 0) { return params.p2.xy; }
    if (index == 1) { return params.p2.zw; }
    if (index == 2) { return params.p3.xy; }
    if (index == 3) { return params.p3.zw; }
    if (index == 4) { return params.p4.xy; }
    if (index == 5) { return params.p4.zw; }
    if (index == 6) { return params.p5.xy; }
    return params.p5.zw;
}

fn apply_curve(value: f32) -> f32 {
    let count = max(i32(params.p1.x + 0.5), 2);
    let smooth_mode = params.p1.y > 0.5;
    let v = clamp(value, 0.0, 1.0);
    let first = curve_point(0);
    let last = curve_point(count - 1);
    if (v <= first.x) { return first.y; }
    if (v >= last.x) { return last.y; }
    var result = v;
    for (var index = 0; index < 7; index = index + 1) {
        if (index >= count - 1) { break; }
        let a = curve_point(index);
        let b = curve_point(index + 1);
        if (v >= a.x && v <= b.x) {
            let t = clamp((v - a.x) / max(b.x - a.x, 0.000001), 0.0, 1.0);
            if (smooth_mode) {
                let previous = curve_point(max(index - 1, 0));
                let following = curve_point(min(index + 2, count - 1));
                let slope0 = (b.y - previous.y) / max(b.x - previous.x, 0.000001);
                let slope1 = (following.y - a.y) / max(following.x - a.x, 0.000001);
                let t2 = t * t;
                let t3 = t2 * t;
                let h00 = 2.0 * t3 - 3.0 * t2 + 1.0;
                let h10 = t3 - 2.0 * t2 + t;
                let h01 = -2.0 * t3 + 3.0 * t2;
                let h11 = t3 - t2;
                result = clamp(
                    h00 * a.y + h10 * (b.x - a.x) * slope0 + h01 * b.y + h11 * (b.x - a.x) * slope1,
                    0.0,
                    1.0
                );
            } else {
                result = mix(a.y, b.y, t);
            }
            break;
        }
    }
    return result;
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let coord = vec2<i32>(gid.xy);
    let source = textureLoad(input_tex, coord, 0);
    let rgb = vec3<f32>(apply_curve(source.r), apply_curve(source.g), apply_curve(source.b));
    textureStore(output_tex, coord, vec4<f32>(rgb, source.a));
}
