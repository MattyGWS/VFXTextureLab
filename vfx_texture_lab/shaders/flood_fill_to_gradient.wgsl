struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var flood_tex: texture_2d<f32>;
@group(0) @binding(2) var angle_tex: texture_2d<f32>;
@group(0) @binding(3) var slope_tex: texture_2d<f32>;
@group(0) @binding(4) var output_tex: texture_storage_2d<rgba32float, write>;
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
const PI:f32=3.14159265358979323846;
fn wrapped_delta(value:vec2<f32>,centre:vec2<f32>)->vec2<f32>{return fract(value-centre+vec2<f32>(0.5))-vec2<f32>(0.5);}
fn sample_scalar(tex:texture_2d<f32>,uv_value:vec2<f32>)->f32{
 let dims_u=textureDimensions(tex);let dims=vec2<f32>(dims_u);let pixel=clamp(uv_value,vec2<f32>(0.0),vec2<f32>(1.0))*dims-vec2<f32>(0.5);
 let base=vec2<i32>(floor(pixel));let f=fract(pixel);let maximum=vec2<i32>(dims_u)-vec2<i32>(1);
 let p00=clamp(base,vec2<i32>(0),maximum);let p10=clamp(base+vec2<i32>(1,0),vec2<i32>(0),maximum);
 let p01=clamp(base+vec2<i32>(0,1),vec2<i32>(0),maximum);let p11=clamp(base+vec2<i32>(1,1),vec2<i32>(0),maximum);
 return mix(mix(textureLoad(tex,p00,0).r,textureLoad(tex,p10,0).r,f.x),mix(textureLoad(tex,p01,0).r,textureLoad(tex,p11,0).r,f.x),f.y);
}
@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) gid:vec3<u32>){
 let width=u32(params.p0.x);let height=u32(params.p0.y);if(gid.x>=width||gid.y>=height){return;}
 let coord=vec2<i32>(gid.xy);let data=textureLoad(flood_tex,coord,0);if(!is_active(data)){textureStore(output_tex,coord,vec4<f32>(0.0,0.0,0.0,1.0));return;}
 let resolution=vec2<f32>(f32(width),f32(height));let uv=(vec2<f32>(gid.xy)+vec2<f32>(0.5))/resolution;let size=max(flood_size(data),vec2<f32>(1.0)/resolution);
 let local=wrapped_delta(uv,data.rg)/size;let seed=u32(max(params.p1.w,0.0));var angle=params.p1.x+(flood_hash(data,seed,6u)*2.0-1.0)*params.p1.y;
 if(params.p3.x>=0.5){angle+=(sample_scalar(angle_tex,data.rg)-0.5)*360.0*params.p1.z;}
 var slope=params.p2.x;if(params.p3.y>=0.5){let map_value=sample_scalar(slope_tex,data.rg);slope*=mix(1.0,map_value,params.p2.y);}
 let radians=angle*PI/180.0;let direction=local.x*cos(radians)+local.y*sin(radians);var value=params.p2.w+direction*slope;
 if(params.p2.z>0.0){value*=mix(1.0,max(size.x,size.y),params.p2.z);}value=clamp(value,0.0,1.0);
 textureStore(output_tex,coord,vec4<f32>(value,value,value,1.0));
}
