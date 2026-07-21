struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var seed_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

fn hash2(p: vec2<f32>, seed: f32) -> f32 {
    return fract(sin(dot(p + vec2<f32>(seed * 0.013, seed * 0.071), vec2<f32>(127.1, 311.7))) * 43758.5453123);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let c = vec2<i32>(gid.xy);
    let uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / vec2<f32>(f32(width), f32(height));
    let connected = params.p2.x > 0.5;
    var mask = textureLoad(seed_tex, c, 0).r;
    if (!connected) {
        let scale = max(1.0 / max(params.p1.z, 0.001), 4.0);
        let cell = floor(uv * scale);
        let local = fract(uv * scale) - vec2<f32>(0.5);
        let chance = clamp(params.p1.y / (scale * scale), 0.02, 0.85);
        let exists = select(0.0, 1.0, hash2(cell, params.p1.x) < chance);
        let jitter = vec2<f32>(hash2(cell + vec2<f32>(17.0, 3.0), params.p1.x), hash2(cell + vec2<f32>(5.0, 29.0), params.p1.x)) - vec2<f32>(0.5);
        mask = exists * select(0.0, 1.0, length(local - jitter * 0.45) < 0.28);
    }
    let v = clamp(mask * params.p1.w, 0.0, 1.0);
    textureStore(output_tex, c, vec4<f32>(1.0 - v, v, 0.0, 1.0));
}
