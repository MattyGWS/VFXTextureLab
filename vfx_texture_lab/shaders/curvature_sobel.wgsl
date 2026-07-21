struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var normal_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

fn wrap_coord(value: i32, size: i32) -> i32 {
    return (value + size * 4) % size;
}

fn normal_at(coord: vec2<i32>) -> vec3<f32> {
    let size = vec2<i32>(i32(params.p0.x), i32(params.p0.y));
    let wrapped = vec2<i32>(wrap_coord(coord.x, size.x), wrap_coord(coord.y, size.y));
    var value = textureLoad(normal_tex, wrapped, 0).rgb * 2.0 - vec3<f32>(1.0);
    if (params.p1.y >= 0.5) { value.y = -value.y; }
    let magnitude = length(value);
    if (magnitude <= 0.0000001) { return vec3<f32>(0.0, 0.0, 1.0); }
    return value / magnitude;
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x); let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let p = vec2<i32>(i32(gid.x), i32(gid.y));
    let r = max(i32(round(params.p1.z)), 1);

    let ul = normal_at(p + vec2<i32>(-r, -r));
    let u = normal_at(p + vec2<i32>(0, -r));
    let ur = normal_at(p + vec2<i32>(r, -r));
    let l = normal_at(p + vec2<i32>(-r, 0));
    let rr = normal_at(p + vec2<i32>(r, 0));
    let dl = normal_at(p + vec2<i32>(-r, r));
    let d = normal_at(p + vec2<i32>(0, r));
    let dr = normal_at(p + vec2<i32>(r, r));

    let dnx = (ur.x + 2.0 * rr.x + dr.x - ul.x - 2.0 * l.x - dl.x) * 0.125;
    let dny = (dl.y + 2.0 * d.y + dr.y - ul.y - 2.0 * u.y - ur.y) * 0.125;
    let curvature = dnx + dny;
    var value = clamp(0.5 + 0.5 * curvature * params.p1.x * 2.0, 0.0, 1.0);
    if (abs(curvature) <= 0.0000000001) { value = 0.5; }
    textureStore(output_tex, p, vec4<f32>(value, value, value, 1.0));
}
