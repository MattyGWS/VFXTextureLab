struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

fn index_for(value: i32, size: i32, wrap: bool) -> i32 {
    if (wrap) { return (value % size + size) % size; }
    return clamp(value, 0, size - 1);
}

fn sample_bilinear(uv_in: vec2<f32>, size: vec2<i32>, wrap: bool) -> vec4<f32> {
    var uv = uv_in;
    if (wrap) { uv = fract(uv); }
    if (!wrap && (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0)) {
        return vec4<f32>(0.0);
    }
    let pixel = uv * vec2<f32>(size) - vec2<f32>(0.5);
    let base = vec2<i32>(floor(pixel));
    let fraction = fract(pixel);
    let p00 = vec2<i32>(index_for(base.x, size.x, wrap), index_for(base.y, size.y, wrap));
    let p10 = vec2<i32>(index_for(base.x + 1, size.x, wrap), p00.y);
    let p01 = vec2<i32>(p00.x, index_for(base.y + 1, size.y, wrap));
    let p11 = vec2<i32>(p10.x, p01.y);
    return mix(
        mix(textureLoad(input_tex, p00, 0), textureLoad(input_tex, p10, 0), fraction.x),
        mix(textureLoad(input_tex, p01, 0), textureLoad(input_tex, p11, 0), fraction.x),
        fraction.y
    );
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let centre = params.p1.xy;
    let radius_scale = max(params.p1.z, 0.0001);
    let angle_offset = params.p1.w / 360.0;
    let clockwise = params.p2.x >= 0.5;
    let wrap_source = params.p2.y >= 0.5;
    let uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / vec2<f32>(f32(width), f32(height));
    var delta = uv - centre;
    delta.x = delta.x * (f32(width) / max(f32(height), 1.0));
    var angle = atan2(delta.y, delta.x) / 6.28318530718 + 0.5 + angle_offset;
    if (clockwise) { angle = 1.0 - angle; }
    let radius = length(delta) * 2.0 * radius_scale;
    let source_uv = vec2<f32>(angle, radius);
    let value = sample_bilinear(source_uv, vec2<i32>(i32(width), i32(height)), wrap_source);
    textureStore(output_tex, vec2<i32>(gid.xy), value);
}
