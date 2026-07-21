struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

fn levels_channel(value: f32) -> f32 {
    let in_low = params.p1.x;
    let in_high = max(params.p1.y, in_low + 0.000001);
    let in_mid = clamp(params.p1.z, 0.00001, 0.99999);
    let out_low = params.p1.w;
    let out_high = params.p2.x;
    let intermediary_clamp = params.p2.y > 0.5;

    let span = in_high - in_low;
    let raw = (value - in_low) / span;
    let mid_normalized = in_mid;
    let exponent = log(0.5) / log(mid_normalized);

    var shaped: f32;
    if (intermediary_clamp) {
        shaped = pow(clamp(raw, 0.0, 1.0), exponent);
    } else if (raw < 0.0 || raw > 1.0) {
        // Linear extension keeps out-of-range floating-point values finite.
        shaped = raw;
    } else {
        shaped = pow(raw, exponent);
    }
    return out_low + shaped * (out_high - out_low);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let coord = vec2<i32>(gid.xy);
    let source = textureLoad(input_tex, coord, 0);
    let result = vec3<f32>(
        levels_channel(source.r),
        levels_channel(source.g),
        levels_channel(source.b)
    );
    textureStore(output_tex, coord, vec4<f32>(result, source.a));
}
