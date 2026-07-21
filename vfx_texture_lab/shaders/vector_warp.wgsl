struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var image_tex: texture_2d<f32>;
@group(0) @binding(2) var vector_tex: texture_2d<f32>;
@group(0) @binding(3) var output_tex: texture_storage_2d<rgba32float, write>;

fn index_for(value: i32, size: i32, wrap: bool) -> i32 {
    if (wrap) { return (value % size + size) % size; }
    return clamp(value, 0, size - 1);
}
fn sample_image(uv_in: vec2<f32>, size: vec2<i32>, wrap: bool) -> vec4<f32> {
    var uv = uv_in;
    if (wrap) { uv = fract(uv); }
    if (!wrap && (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0)) { return vec4<f32>(0.0); }
    let pixel = uv * vec2<f32>(size) - vec2<f32>(0.5);
    let base = vec2<i32>(floor(pixel));
    let f = fract(pixel);
    let p00 = vec2<i32>(index_for(base.x, size.x, wrap), index_for(base.y, size.y, wrap));
    let p10 = vec2<i32>(index_for(base.x + 1, size.x, wrap), p00.y);
    let p01 = vec2<i32>(p00.x, index_for(base.y + 1, size.y, wrap));
    let p11 = vec2<i32>(p10.x, p01.y);
    return mix(mix(textureLoad(image_tex, p00, 0), textureLoad(image_tex, p10, 0), f.x),
               mix(textureLoad(image_tex, p01, 0), textureLoad(image_tex, p11, 0), f.x), f.y);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x); let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let size = vec2<i32>(i32(width), i32(height));
    let coordinate = vec2<i32>(gid.xy);
    let uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / vec2<f32>(f32(width), f32(height));
    let mode = i32(round(params.p1.x));
    let strength = params.p1.y;
    let phase = fract(params.p1.z);
    let wrap = params.p1.w >= 0.5;
    let displacement = (textureLoad(vector_tex, coordinate, 0).rg * 2.0 - vec2<f32>(1.0)) * strength;

    var result: vec4<f32>;
    if (mode == 0) {
        result = sample_image(uv - displacement, size, wrap);
    } else {
        let phase_b = fract(phase + 0.5);
        let first = sample_image(uv - displacement * phase, size, wrap);
        let second = sample_image(uv - displacement * phase_b, size, wrap);
        let first_weight = abs(phase * 2.0 - 1.0);
        result = mix(second, first, first_weight);
    }
    textureStore(output_tex, coordinate, result);
}
