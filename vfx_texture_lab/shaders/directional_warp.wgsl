struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var image_tex: texture_2d<f32>;
@group(0) @binding(2) var intensity_tex: texture_2d<f32>;
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
    return mix(mix(textureLoad(image_tex, p00, 0), textureLoad(image_tex, p10, 0), f.x), mix(textureLoad(image_tex, p01, 0), textureLoad(image_tex, p11, 0), f.x), f.y);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let strength = params.p1.x;
    let radians = params.p1.y * 0.017453292519943295;
    let centered = params.p1.z >= 0.5;
    let wrap = params.p1.w >= 0.5;
    let uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / vec2<f32>(f32(width), f32(height));
    let amount_raw = textureLoad(intensity_tex, vec2<i32>(gid.xy), 0).x;
    let amount = select(amount_raw, amount_raw * 2.0 - 1.0, centered);
    let direction = vec2<f32>(cos(radians), sin(radians));
    let source_uv = uv - direction * amount * strength;
    let value = sample_image(source_uv, vec2<i32>(i32(width), i32(height)), wrap);
    textureStore(output_tex, vec2<i32>(gid.xy), value);
}
