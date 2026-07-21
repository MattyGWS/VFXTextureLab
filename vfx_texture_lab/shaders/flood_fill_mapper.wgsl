struct Params { p0:vec4<f32>, p1:vec4<f32>, p2:vec4<f32>, p3:vec4<f32>, p4:vec4<f32>, };
@group(0) @binding(0) var<uniform> params:Params;
@group(0) @binding(1) var flood_tex:texture_2d<f32>;
@group(0) @binding(2) var pattern_tex:texture_2d<f32>;
@group(0) @binding(3) var scale_tex:texture_2d<f32>;
@group(0) @binding(4) var rotation_tex:texture_2d<f32>;
@group(0) @binding(5) var output_tex:texture_storage_2d<rgba32float, write>;
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
fn sample_scalar_clamped(tex:texture_2d<f32>,uv_value:vec2<f32>)->f32{
 let dims_u=textureDimensions(tex);let dims=vec2<f32>(dims_u);let pixel=clamp(uv_value,vec2<f32>(0.0),vec2<f32>(1.0))*dims-vec2<f32>(0.5);
 let base=vec2<i32>(floor(pixel));let f=fract(pixel);let maximum=vec2<i32>(dims_u)-vec2<i32>(1);
 let p00=clamp(base,vec2<i32>(0),maximum);let p10=clamp(base+vec2<i32>(1,0),vec2<i32>(0),maximum);let p01=clamp(base+vec2<i32>(0,1),vec2<i32>(0),maximum);let p11=clamp(base+vec2<i32>(1,1),vec2<i32>(0),maximum);
 return mix(mix(textureLoad(tex,p00,0).r,textureLoad(tex,p10,0).r,f.x),mix(textureLoad(tex,p01,0).r,textureLoad(tex,p11,0).r,f.x),f.y);
}
fn sample_pattern(uv_value:vec2<f32>,tiling:bool)->f32{
 var uv=uv_value;if(tiling){uv=fract(uv);}let dims_u=textureDimensions(pattern_tex);let dims=vec2<f32>(dims_u);let pixel=clamp(uv,vec2<f32>(0.0),vec2<f32>(1.0))*dims-vec2<f32>(0.5);
 let base=vec2<i32>(floor(pixel));let f=fract(pixel);let maximum=vec2<i32>(dims_u)-vec2<i32>(1);
 let p00=clamp(base,vec2<i32>(0),maximum);let p10=clamp(base+vec2<i32>(1,0),vec2<i32>(0),maximum);let p01=clamp(base+vec2<i32>(0,1),vec2<i32>(0),maximum);let p11=clamp(base+vec2<i32>(1,1),vec2<i32>(0),maximum);
 return mix(mix(textureLoad(pattern_tex,p00,0).r,textureLoad(pattern_tex,p10,0).r,f.x),mix(textureLoad(pattern_tex,p01,0).r,textureLoad(pattern_tex,p11,0).r,f.x),f.y);
}
@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) gid:vec3<u32>){
 let width=u32(params.p0.x);let height=u32(params.p0.y);if(gid.x>=width||gid.y>=height){return;}let coord=vec2<i32>(gid.xy);let data=textureLoad(flood_tex,coord,0);
 if(!is_active(data)||params.p4.y<0.5){let bg=params.p3.w;textureStore(output_tex,coord,vec4<f32>(bg,bg,bg,1.0));return;}
 let resolution=vec2<f32>(f32(width),f32(height));let uv=(vec2<f32>(gid.xy)+vec2<f32>(0.5))/resolution;let size=max(flood_size(data),vec2<f32>(1.0)/resolution);let local=wrapped_delta(uv,data.rg)/size;let seed=u32(max(params.p4.x,0.0));
 var scale=max(params.p1.y*(1.0+(flood_hash(data,seed,7u)*2.0-1.0)*params.p1.z),0.0001);if(params.p4.z>=0.5){scale*=mix(1.0,sample_scalar_clamped(scale_tex,data.rg),params.p1.w);}scale=max(scale,0.0001);
 var angle=params.p2.x+(flood_hash(data,seed,8u)*2.0-1.0)*params.p2.y;if(params.p4.w>=0.5){angle+=(sample_scalar_clamped(rotation_tex,data.rg)-0.5)*360.0*params.p2.z;}
 let radians=angle*PI/180.0;let c=cos(radians);let s=sin(radians);let mapped=vec2<f32>((local.x*c+local.y*s)/scale+0.5+params.p2.w,(-local.x*s+local.y*c)/scale+0.5+params.p3.x);
 let tiling=params.p1.x>=0.5;var value=params.p3.w;let inside=all(mapped>=vec2<f32>(0.0))&&all(mapped<=vec2<f32>(1.0));if(tiling||inside){value=sample_pattern(mapped,tiling);}value=clamp(value*params.p3.y+params.p3.z,0.0,1.0);textureStore(output_tex,coord,vec4<f32>(value,value,value,1.0));
}
