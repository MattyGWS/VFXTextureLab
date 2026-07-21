struct Params { p0: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var height_tex: texture_2d<f32>;
@group(0) @binding(2) var rain_tex: texture_2d<f32>;
@group(0) @binding(3) var hardness_tex: texture_2d<f32>;
@group(0) @binding(4) var state_out: texture_storage_2d<rgba32float, write>;
@group(0) @binding(5) var accum_out: texture_storage_2d<rgba32float, write>;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let w = u32(params.p0.x);
    let h = u32(params.p0.y);
    if (gid.x >= w || gid.y >= h) { return; }
    let c = vec2<i32>(gid.xy);
    let height = clamp(textureLoad(height_tex, c, 0).r, 0.0, 1.0);
    let hard = clamp(textureLoad(hardness_tex, c, 0).r, 0.0, 1.0);
    let rain = clamp(textureLoad(rain_tex, c, 0).r, 0.0, 1.0);
    // State: current height, original macro height, hardness, rainfall mask.
    textureStore(state_out, c, vec4<f32>(height, height, hard, rain));
    // Accumulation: erosion, deposition, channel mask, wetness.
    textureStore(accum_out, c, vec4<f32>(0.0));
}
