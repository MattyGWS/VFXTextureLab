struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var output_tex: texture_storage_2d<rgba32float, write>;
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x); let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / vec2<f32>(f32(width), f32(height));
    let angle = params.p1.x * 0.017453292519943295;
    let direction = vec2<f32>(cos(angle), sin(angle));
    var coordinate = dot(uv - vec2<f32>(0.5), direction) + 0.5 + params.p1.y;
    if (params.p1.z >= 0.5) { coordinate = fract(coordinate); }
    coordinate = clamp(coordinate, 0.0, 1.0);

    let variant = u32(round(params.p1.w));
    var value = coordinate;
    if (variant == 1u) {
        // Rounded dome: zero slope at both black edges and at the white crest.
        value = 0.5 - 0.5 * cos(coordinate * 6.283185307179586);
    } else if (variant == 2u) {
        // Mirrored linear ramp: intentionally retains a sharp centre ridge.
        value = 1.0 - abs(coordinate * 2.0 - 1.0);
    }
    value = clamp(value, 0.0, 1.0);
    textureStore(output_tex, vec2<i32>(gid.xy), vec4<f32>(value, value, value, 1.0));
}
