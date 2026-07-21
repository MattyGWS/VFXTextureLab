struct Params { p0: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var flood_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;
const PACK_SCALE: f32 = 16777215.0;
const PACK_MAX: f32 = 4095.0;

fn unpack_pair(value: f32) -> vec2<f32> {
    let packed = u32(round(clamp(value, 0.0, 1.0) * PACK_SCALE));
    return vec2<f32>(f32(packed & 4095u), f32(packed >> 12u));
}

fn is_active(data: vec4<f32>) -> bool {
    let size_q = unpack_pair(data.b);
    return size_q.x > 0.0 && size_q.y > 0.0;
}

fn flood_size(data: vec4<f32>) -> vec2<f32> {
    return unpack_pair(data.b) / PACK_MAX;
}

fn flood_index(data: vec4<f32>) -> f32 {
    return data.a;
}

fn flood_hash(data: vec4<f32>, seed: u32, stream: u32) -> f32 {
    let size_q = unpack_pair(data.b);
    var value = u32(round(data.r * 65535.0)) * 0x9E3779B9u;
    value = value ^ (u32(round(data.g * 65535.0)) * 0x85EBCA6Bu);
    value = value ^ (u32(round(size_q.x)) * 0xC2B2AE35u);
    value = value ^ (u32(round(size_q.y)) * 0x27D4EB2Du);
    value = value ^ (u32(round(data.a * PACK_SCALE)) * 0x165667B1u);
    value = value ^ (seed * 0xA24BAED5u);
    value = value ^ (stream * 0x9FB21C65u);
    value = value ^ (value >> 16u);
    value = value * 0x7FEB352Du;
    value = value ^ (value >> 15u);
    value = value * 0x846CA68Bu;
    value = value ^ (value >> 16u);
    return f32(value & 0x00FFFFFFu) / 16777216.0;
}
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width=u32(params.p0.x); let height=u32(params.p0.y); if(gid.x>=width||gid.y>=height){return;}
    let coord=vec2<i32>(gid.xy); let data=textureLoad(flood_tex,coord,0);
    let result=select(vec4<f32>(0.0), vec4<f32>(data.r, data.g, 0.0, 1.0), is_active(data));
    textureStore(output_tex,coord,result);
}
