struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;
fn linear_to_srgb(v: vec3<f32>) -> vec3<f32> {
    let x = max(v, vec3<f32>(0.0));
    return select(1.055 * pow(x, vec3<f32>(1.0 / 2.4)) - 0.055, x * 12.92, x <= vec3<f32>(0.0031308));
}
fn sample_coord(coord: vec2<i32>, width: i32, height: i32) -> vec4<f32> {
    return textureLoad(input_tex, clamp(coord, vec2<i32>(0), vec2<i32>(width - 1, height - 1)), 0);
}
fn scalar_value(coord: vec2<i32>, width: i32, height: i32, kind: i32) -> f32 {
    let c = sample_coord(coord, width, height);
    if (kind == 0) { return c.r; }
    let rgb = linear_to_srgb(clamp(c.rgb, vec3<f32>(0.0), vec3<f32>(1.0)));
    return dot(rgb, vec3<f32>(0.2126, 0.7152, 0.0722));
}
fn vector_value(coord: vec2<i32>, width: i32, height: i32) -> vec3<f32> {
    return normalize(sample_coord(coord, width, height).rgb * 2.0 - vec3<f32>(1.0));
}
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = i32(params.p0.x); let height = i32(params.p0.y);
    if (i32(gid.x) >= width || i32(gid.y) >= height) { return; }
    let c = vec2<i32>(gid.xy);
    let radius = max(i32(round(params.p1.x)), 1);
    let intensity = max(params.p1.y, 0.0);
    let sobel = params.p1.z >= 0.5;
    let invert = params.p1.w >= 0.5;
    let kind = i32(params.p2.x + 0.5);
    let side = select(3.0, 1.0, sobel);
    let centre = select(10.0, 2.0, sobel);
    let norm = select(16.0, 4.0, sobel);
    var result: f32;
    if (kind == 2) {
        let tl = vector_value(c + vec2<i32>(-radius, -radius), width, height);
        let tc = vector_value(c + vec2<i32>(0, -radius), width, height);
        let tr = vector_value(c + vec2<i32>(radius, -radius), width, height);
        let ml = vector_value(c + vec2<i32>(-radius, 0), width, height);
        let mr = vector_value(c + vec2<i32>(radius, 0), width, height);
        let bl = vector_value(c + vec2<i32>(-radius, radius), width, height);
        let bc = vector_value(c + vec2<i32>(0, radius), width, height);
        let br = vector_value(c + vec2<i32>(radius, radius), width, height);
        let gx = (-side * tl - centre * ml - side * bl + side * tr + centre * mr + side * br) / norm;
        let gy = (-side * tl - centre * tc - side * tr + side * bl + centre * bc + side * br) / norm;
        result = clamp(sqrt(dot(gx, gx) + dot(gy, gy)) * 0.5 * intensity, 0.0, 1.0);
    } else {
        let tl = scalar_value(c + vec2<i32>(-radius, -radius), width, height, kind);
        let tc = scalar_value(c + vec2<i32>(0, -radius), width, height, kind);
        let tr = scalar_value(c + vec2<i32>(radius, -radius), width, height, kind);
        let ml = scalar_value(c + vec2<i32>(-radius, 0), width, height, kind);
        let mr = scalar_value(c + vec2<i32>(radius, 0), width, height, kind);
        let bl = scalar_value(c + vec2<i32>(-radius, radius), width, height, kind);
        let bc = scalar_value(c + vec2<i32>(0, radius), width, height, kind);
        let br = scalar_value(c + vec2<i32>(radius, radius), width, height, kind);
        let gx = (-side * tl - centre * ml - side * bl + side * tr + centre * mr + side * br) / norm;
        let gy = (-side * tl - centre * tc - side * tr + side * bl + centre * bc + side * br) / norm;
        result = clamp(length(vec2<f32>(gx, gy)) * intensity, 0.0, 1.0);
    }
    if (invert) { result = 1.0 - result; }
    textureStore(output_tex, c, vec4<f32>(result, result, result, 1.0));
}
