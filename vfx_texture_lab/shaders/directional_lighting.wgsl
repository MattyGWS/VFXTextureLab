struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var normal_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

const DEG_TO_RAD: f32 = 0.017453292519943295;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }

    let p = vec2<i32>(gid.xy);
    let angle = params.p1.x * DEG_TO_RAD;
    let elevation = clamp(params.p1.y, 0.0, 90.0) * DEG_TO_RAD;
    let diffuse_power = max(params.p1.z, 0.01);
    let diffuse_brightness = max(params.p1.w, 0.0);
    let highlight_power = max(params.p2.x, 1.0);
    let highlight_brightness = max(params.p2.y, 0.0);
    let ambient = clamp(params.p2.z, 0.0, 1.0);
    let invert = params.p2.w >= 0.5;
    let directx = params.p3.x >= 0.5;

    var normal = textureLoad(normal_tex, p, 0).rgb * 2.0 - vec3<f32>(1.0);
    if (directx) { normal.y = -normal.y; }
    normal = normalize(select(normal, vec3<f32>(0.0, 0.0, 1.0), dot(normal, normal) < 0.00000001));

    let horizontal = cos(elevation);
    let light = normalize(vec3<f32>(cos(angle) * horizontal, sin(angle) * horizontal, sin(elevation)));
    let diffuse_term = pow(max(dot(normal, light), 0.0), diffuse_power) * diffuse_brightness;

    let half_vector = normalize(light + vec3<f32>(0.0, 0.0, 1.0));
    let highlight_term = pow(max(dot(normal, half_vector), 0.0), highlight_power) * highlight_brightness;

    var value = clamp(ambient + diffuse_term + highlight_term, 0.0, 1.0);
    if (invert) { value = 1.0 - value; }
    textureStore(output_tex, p, vec4<f32>(value, value, value, 1.0));
}
