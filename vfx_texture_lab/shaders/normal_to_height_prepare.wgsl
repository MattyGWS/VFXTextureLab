// The public node uses a global FFT Poisson solve in the backend because the
// reconstruction depends on all pixels at once. This kernel is package metadata
// for the built-in GPU-assisted path and is not dispatched directly.
struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;
@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= u32(params.p0.x) || gid.y >= u32(params.p0.y)) { return; }
    textureStore(output_tex, vec2<i32>(gid.xy), textureLoad(input_tex, vec2<i32>(gid.xy), 0));
}
