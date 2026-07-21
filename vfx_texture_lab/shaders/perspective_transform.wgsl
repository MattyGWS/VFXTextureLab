struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

// @include "resampling_common.wgsl"

fn project_uv(uv: vec2<f32>) -> vec2<f32> {
    let denominator = params.p3.x*uv.x + params.p3.y*uv.y + params.p3.z;
    let safe_d = select(1e-8, denominator, abs(denominator) >= 1e-8);
    return vec2<f32>((params.p1.x*uv.x + params.p1.y*uv.y + params.p1.z)/safe_d,
                     (params.p2.x*uv.x + params.p2.y*uv.y + params.p2.z)/safe_d);
}
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x); let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let size_f = vec2<f32>(f32(width), f32(height));
    let identity = abs(params.p1.x-1.0)<1e-7 && abs(params.p1.y)<1e-7 && abs(params.p1.z)<1e-7 && abs(params.p2.x)<1e-7 && abs(params.p2.y-1.0)<1e-7 && abs(params.p2.z)<1e-7 && abs(params.p3.x)<1e-7 && abs(params.p3.y)<1e-7 && abs(params.p3.z-1.0)<1e-7;
    if (identity) { textureStore(output_tex, vec2<i32>(gid.xy), textureLoad(input_tex, vec2<i32>(gid.xy), 0)); return; }
    let uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / size_f;
    let source_uv = project_uv(uv);
    let source_x = project_uv(uv + vec2<f32>(1.0/f32(width), 0.0));
    let source_y = project_uv(uv + vec2<f32>(0.0, 1.0/f32(height)));
    let footprint = vec2<f32>(length((source_x-source_uv)*size_f), length((source_y-source_uv)*size_f));
    let pixel = source_uv*size_f - vec2<f32>(0.5);
    let boundary = select(1, 0, params.p3.w >= 0.5);
    let kind = i32(params.p2.w+0.5);
    var result = sample_filtered(pixel, vec2<i32>(i32(width),i32(height)), boundary, kind, i32(params.p1.w+0.5), footprint);
    if (kind == 0) { result = vec4<f32>(result.r,result.r,result.r,1.0); }
    textureStore(output_tex, vec2<i32>(gid.xy), clamp(result, vec4<f32>(0.0), vec4<f32>(1.0)));
}
