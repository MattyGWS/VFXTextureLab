struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let w = u32(params.p0.x);
    let h = u32(params.p0.y);
    if (gid.x >= w || gid.y >= h) { return; }

    let source = textureLoad(input_tex, vec2<i32>(gid.xy), 0);
    let low = params.p1.x;
    let span = params.p1.y - low;
    let scalar_source = params.p1.z > 0.5;

    var output: vec4<f32>;
    if (span <= 0.0000001) {
        output = vec4<f32>(0.0, 0.0, 0.0, select(source.a, 1.0, scalar_source));
    } else if (scalar_source) {
        let value = clamp((source.r - low) / span, 0.0, 1.0);
        output = vec4<f32>(value, value, value, 1.0);
    } else {
        let rgb = clamp((source.rgb - vec3<f32>(low)) / span, vec3<f32>(0.0), vec3<f32>(1.0));
        output = vec4<f32>(rgb, source.a);
    }
    textureStore(output_tex, vec2<i32>(gid.xy), output);
}
