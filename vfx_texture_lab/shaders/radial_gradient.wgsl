struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var output_tex: texture_storage_2d<rgba32float, write>;
fn wrapped_delta(value: f32, centre: f32) -> f32 { return fract(value - centre + 0.5) - 0.5; }
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x); let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / vec2<f32>(f32(width), f32(height));
    let aspect = f32(width) / max(f32(height), 1.0);
    let delta = vec2<f32>(wrapped_delta(uv.x, params.p1.x) * aspect, wrapped_delta(uv.y, params.p1.y));
    let radius = max(params.p1.z, 0.0001);
    var value = clamp(1.0 - length(delta) / radius, 0.0, 1.0);
    value = pow(value, max(params.p1.w, 0.01));
    textureStore(output_tex, vec2<i32>(gid.xy), vec4<f32>(value, value, value, 1.0));
}
