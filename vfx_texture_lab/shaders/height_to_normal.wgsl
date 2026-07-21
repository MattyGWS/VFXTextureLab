struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;
fn luminance(value: vec4<f32>) -> f32 { return dot(value.rgb, vec3<f32>(0.2126, 0.7152, 0.0722)); }
fn height_value(coord: vec2<i32>) -> f32 {
    let source = textureLoad(input_tex, coord, 0);
    return select(luminance(source), source.r, params.p1.z >= 0.5);
}
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x); let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let left_x = (gid.x + width - 1u) % width;
    let right_x = (gid.x + 1u) % width;
    let up_y = (gid.y + height - 1u) % height;
    let down_y = (gid.y + 1u) % height;
    let left = height_value(vec2<i32>(i32(left_x), i32(gid.y)));
    let right = height_value(vec2<i32>(i32(right_x), i32(gid.y)));
    let up = height_value(vec2<i32>(i32(gid.x), i32(up_y)));
    let down = height_value(vec2<i32>(i32(gid.x), i32(down_y)));
    let dx = (right - left) * 0.5; let dy = (down - up) * 0.5; let strength = params.p1.x;
    let ny = select(-dy, dy, params.p1.y >= 0.5) * strength;
    let normal = normalize(vec3<f32>(-dx * strength, ny, 1.0)) * 0.5 + vec3<f32>(0.5);
    textureStore(output_tex, vec2<i32>(gid.xy), vec4<f32>(normal, 1.0));
}
