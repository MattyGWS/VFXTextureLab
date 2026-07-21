struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var blur_map_tex: texture_2d<f32>;
@group(0) @binding(3) var output_tex: texture_storage_2d<rgba32float, write>;
fn wrap_float(value:f32,extent:f32)->f32{return value-floor(value/extent)*extent;}
fn sample_scalar(position:vec2<f32>,dimensions:vec2<i32>)->f32{
 let wrapped=vec2<f32>(wrap_float(position.x,f32(dimensions.x)),wrap_float(position.y,f32(dimensions.y)));
 let base=vec2<i32>(floor(wrapped));let f=fract(wrapped);let next=vec2<i32>((base.x+1)%dimensions.x,(base.y+1)%dimensions.y);
 let a=textureLoad(input_tex,base,0).r;let b=textureLoad(input_tex,vec2<i32>(next.x,base.y),0).r;
 let c=textureLoad(input_tex,vec2<i32>(base.x,next.y),0).r;let d=textureLoad(input_tex,next,0).r;
 return mix(mix(a,b,f.x),mix(c,d,f.x),f.y);
}
@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) gid:vec3<u32>){
 let width=i32(params.p0.x);let height=i32(params.p0.y);if(i32(gid.x)>=width||i32(gid.y)>=height){return;}
 let radius=max(params.p1.x,0.0);let samples=clamp(i32(params.p1.y+0.5),2,128);let dimensions=vec2<i32>(width,height);let coord=vec2<i32>(gid.xy);let pixel=vec2<f32>(gid.xy);
 let amount=clamp(textureLoad(blur_map_tex,coord,0).r,0.0,1.0)*radius;var total=textureLoad(input_tex,coord,0).r;
 for(var index:i32=0;index<128;index=index+1){if(index<samples){let angle=f32(index)/f32(samples)*6.283185307179586;let offset=vec2<f32>(cos(angle),sin(angle))*amount;total=total+sample_scalar(pixel+offset,dimensions);}}
 let value=clamp(total/f32(samples+1),0.0,1.0);textureStore(output_tex,coord,vec4<f32>(value,value,value,1.0));
}
