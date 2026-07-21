struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

fn clamp_coord(value: i32, extent: i32) -> i32 {
    return min(max(value, 0), extent - 1);
}

fn sample_bilinear(position: vec2<f32>, dimensions: vec2<i32>) -> vec4<f32> {
    let base_float = floor(position);
    let fraction = fract(position);
    let base = vec2<i32>(
        clamp_coord(i32(base_float.x), dimensions.x),
        clamp_coord(i32(base_float.y), dimensions.y)
    );
    let next = vec2<i32>(
        clamp_coord(base.x + 1, dimensions.x),
        clamp_coord(base.y + 1, dimensions.y)
    );
    let a = textureLoad(input_tex, base, 0);
    let b = textureLoad(input_tex, vec2<i32>(next.x, base.y), 0);
    let c = textureLoad(input_tex, vec2<i32>(base.x, next.y), 0);
    let d = textureLoad(input_tex, next, 0);
    return mix(mix(a, b, fraction.x), mix(c, d, fraction.x), fraction.y);
}

fn linear_to_srgb(value: vec3<f32>) -> vec3<f32> {
    let v = clamp(value, vec3<f32>(0.0), vec3<f32>(1.0));
    let low = v * 12.92;
    let high = 1.055 * pow(v, vec3<f32>(1.0 / 2.4)) - 0.055;
    return select(high, low, v <= vec3<f32>(0.0031308));
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let target_width = i32(params.p0.x);
    let target_height = i32(params.p0.y);
    if (i32(gid.x) >= target_width || i32(gid.y) >= target_height) { return; }

    let source_width = max(i32(params.p1.x), 1);
    let source_height = max(i32(params.p1.y), 1);
    let kind = i32(params.p1.z + 0.5); // 0 colour, 1 greyscale, 2 vector
    let source_position = (vec2<f32>(gid.xy) + vec2<f32>(0.5))
        * vec2<f32>(f32(source_width) / f32(target_width), f32(source_height) / f32(target_height))
        - vec2<f32>(0.5);
    let sample = sample_bilinear(source_position, vec2<i32>(source_width, source_height));

    var output = clamp(sample, vec4<f32>(0.0), vec4<f32>(1.0));
    if (kind == 1) {
        output = vec4<f32>(sample.r, sample.r, sample.r, 1.0);
    } else if (kind == 2) {
        output = vec4<f32>(sample.rgb, 1.0);
    } else {
        output = vec4<f32>(linear_to_srgb(sample.rgb), clamp(sample.a, 0.0, 1.0));
    }
    textureStore(output_tex, vec2<i32>(gid.xy), output);
}
