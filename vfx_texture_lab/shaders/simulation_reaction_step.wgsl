struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var state_tex: texture_2d<f32>;
@group(0) @binding(2) var seed_tex: texture_2d<f32>;
@group(0) @binding(3) var output_tex: texture_storage_2d<rgba32float, write>;

fn wrap(c: vec2<i32>, size: vec2<i32>) -> vec2<i32> {
    return vec2<i32>((c.x % size.x + size.x) % size.x, (c.y % size.y + size.y) % size.y);
}
fn load_uv(c: vec2<i32>, size: vec2<i32>) -> vec2<f32> {
    return textureLoad(state_tex, wrap(c, size), 0).rg;
}
fn lap(c: vec2<i32>, size: vec2<i32>) -> vec2<f32> {
    let centre = load_uv(c, size);
    var result = -centre;
    result += (load_uv(c + vec2<i32>(1,0), size) + load_uv(c + vec2<i32>(-1,0), size) + load_uv(c + vec2<i32>(0,1), size) + load_uv(c + vec2<i32>(0,-1), size)) * 0.2;
    result += (load_uv(c + vec2<i32>(1,1), size) + load_uv(c + vec2<i32>(-1,1), size) + load_uv(c + vec2<i32>(1,-1), size) + load_uv(c + vec2<i32>(-1,-1), size)) * 0.05;
    return result;
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let size = vec2<i32>(i32(params.p0.x), i32(params.p0.y));
    let c = vec2<i32>(gid.xy);
    if (c.x >= size.x || c.y >= size.y) { return; }
    let state = load_uv(c, size);
    let reaction = state.x * state.y * state.y;
    let l = lap(c, size);
    var u = state.x + (params.p1.z * l.x - reaction + params.p1.x * (1.0 - state.x)) * params.p2.x;
    var v = state.y + (params.p1.w * l.y + reaction - (params.p1.x + params.p1.y) * state.y) * params.p2.x;
    let injection = clamp(textureLoad(seed_tex, c, 0).r * params.p2.y, 0.0, 1.0);
    v = max(v, injection);
    u = min(u, 1.0 - injection);
    textureStore(output_tex, c, vec4<f32>(clamp(u, 0.0, 1.0), clamp(v, 0.0, 1.0), 0.0, 1.0));
}
