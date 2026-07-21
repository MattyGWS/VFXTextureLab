struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;
fn wrap_float(value: f32, extent: f32) -> f32 { return value - floor(value / extent) * extent; }
fn sample_bilinear(position: vec2<f32>, dimensions: vec2<i32>) -> vec4<f32> {
    let wrapped = vec2<f32>(wrap_float(position.x, f32(dimensions.x)), wrap_float(position.y, f32(dimensions.y)));
    let base = vec2<i32>(floor(wrapped)); let fraction = fract(wrapped);
    let next = vec2<i32>((base.x + 1) % dimensions.x, (base.y + 1) % dimensions.y);
    let a = textureLoad(input_tex, base, 0); let b = textureLoad(input_tex, vec2<i32>(next.x, base.y), 0);
    let c = textureLoad(input_tex, vec2<i32>(base.x, next.y), 0); let d = textureLoad(input_tex, next, 0);
    return mix(mix(a,b,fraction.x), mix(c,d,fraction.x), fraction.y);
}
@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = i32(params.p0.x); let height = i32(params.p0.y);
    if (i32(gid.x) >= width || i32(gid.y) >= height) { return; }
    let intensity = max(params.p1.x, 0.0);
    let anisotropy = clamp(params.p1.y, 0.0, 1.0);
    let radians = params.p1.z * 0.017453292519943295;
    let samples = clamp(i32(params.p1.w + 0.5), 2, 128);
    let major = vec2<f32>(cos(radians), sin(radians));
    let minor = vec2<f32>(-major.y, major.x);
    let major_radius = intensity;
    let minor_radius = intensity * (1.0 - 0.9 * anisotropy);
    let minor_steps = clamp(i32(round(1.0 + (1.0 - anisotropy) * 0.5 * f32(samples))), 1, 64);
    let major_steps = samples;
    let pixel = vec2<f32>(gid.xy); let dimensions = vec2<i32>(width, height);
    var total = vec4<f32>(0.0);
    var total_weight = 0.0;
    for (var mi:i32 = 0; mi < 64; mi = mi + 1) {
        if (mi < minor_steps) {
            let v = select((f32(mi) / f32(minor_steps - 1) - 0.5) * 2.0, 0.0, minor_steps == 1);
            let minor_offset = minor * minor_radius * v;
            let minor_weight = 1.0 - abs(v) * 0.5;
            for (var mj:i32 = 0; mj < 128; mj = mj + 1) {
                if (mj < major_steps) {
                    let u = select((f32(mj) / f32(major_steps - 1) - 0.5) * 2.0, 0.0, major_steps == 1);
                    let weight = minor_weight * (1.0 - abs(u) * 0.35);
                    let pos = pixel + major * major_radius * u + minor_offset;
                    total = total + sample_bilinear(pos, dimensions) * weight;
                    total_weight = total_weight + weight;
                }
            }
        }
    }
    textureStore(output_tex, vec2<i32>(gid.xy), total / max(total_weight, 1.0e-6));
}
