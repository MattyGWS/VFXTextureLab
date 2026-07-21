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
    if (!wrap && (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0)) { return vec4<f32>(0.0); }
    let pixel = uv * vec2<f32>(size) - vec2<f32>(0.5);
    let base = vec2<i32>(floor(pixel));
    let f = fract(pixel);
    let p00 = vec2<i32>(index_for(base.x, size.x, wrap), index_for(base.y, size.y, wrap));
    let p10 = vec2<i32>(index_for(base.x + 1, size.x, wrap), p00.y);
    let p01 = vec2<i32>(p00.x, index_for(base.y + 1, size.y, wrap));
    let p11 = vec2<i32>(p10.x, p01.y);
    return mix(mix(textureLoad(input_tex, p00, 0), textureLoad(input_tex, p10, 0), f.x),
               mix(textureLoad(input_tex, p01, 0), textureLoad(input_tex, p11, 0), f.x), f.y);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x); let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / vec2<f32>(f32(width), f32(height));
    let mode = i32(round(params.p1.x));
    let amount = params.p1.y;
    let radius = max(params.p1.z, 0.000001);
    let centre = vec2<f32>(params.p1.w, params.p2.x);
    let wrap = params.p2.y >= 0.5;
    let aspect = f32(width) / max(f32(height), 1.0);
    var delta = uv - centre;
    delta.x *= aspect;
    var source_delta = delta;

    if (mode == 0) {
        let distance = length(delta);
        let local = clamp(1.0 - distance / radius, 0.0, 1.0);
        let falloff = local * local * (3.0 - 2.0 * local);
        let angle = -amount * 0.017453292519943295 * falloff;
        let c = cos(angle); let s = sin(angle);
        source_delta = vec2<f32>(delta.x * c - delta.y * s, delta.x * s + delta.y * c);
    } else {
        let normalized = delta / radius;
        let distance = length(normalized);
        if (distance < 1.0 && distance > 0.0000001) {
            let target_distance = select(sqrt(max(distance, 0.0)), distance * distance, amount >= 0.0);
            let source_distance = mix(distance, target_distance, abs(amount));
            source_delta = delta * (source_distance / distance);
        }
    }

    source_delta.x /= aspect;
    let source_uv = centre + source_delta;
    textureStore(output_tex, vec2<i32>(gid.xy), sample_bilinear(source_uv, vec2<i32>(i32(width), i32(height)), wrap));
}
