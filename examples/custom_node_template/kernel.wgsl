// VFX Texture Lab public custom-node ABI v2. p0.z = seconds; p0.w = document phase.
struct Params {
    p0: vec4<f32>,
    p1: vec4<f32>,
    p2: vec4<f32>,
    p3: vec4<f32>,
};

@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var output_tex: texture_storage_2d<rgba32float, write>;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) {
        return;
    }

    let frequency = params.p1.x;
    let angle = params.p1.y * 0.017453292519943295;
    let phase = params.p1.z;
    let uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) /
        vec2<f32>(f32(width), f32(height));
    let direction = vec2<f32>(cos(angle), sin(angle));
    let position = dot(uv, direction) * frequency + phase;
    let value = sin(position * 6.28318530718) * 0.5 + 0.5;
    textureStore(output_tex, vec2<i32>(gid.xy), vec4<f32>(value, value, value, 1.0));
}
