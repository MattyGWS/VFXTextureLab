// Flood Fill topology is evaluated by the backend's optimized CPU run-length
// pass, then uploaded as reusable vector metadata. This valid pass-through
// kernel keeps the built-in shader contract complete for validation and future
// replacement by a native iterative GPU topology implementation.
struct Params { p0: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    textureStore(output_tex, vec2<i32>(gid.xy), textureLoad(input_tex, vec2<i32>(gid.xy), 0));
}
