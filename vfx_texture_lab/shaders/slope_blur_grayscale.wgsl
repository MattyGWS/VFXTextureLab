struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var slope_tex: texture_2d<f32>;
@group(0) @binding(3) var output_tex: texture_storage_2d<rgba32float, write>;
fn wrap_i(value:i32,extent:i32)->i32{var r=value;if(r<0){r=r+extent;}if(r>=extent){r=r-extent;}return r;}
fn load_slope(coord:vec2<i32>,dimensions:vec2<i32>)->f32{return textureLoad(slope_tex,vec2<i32>(wrap_i(coord.x,dimensions.x),wrap_i(coord.y,dimensions.y)),0).r;}
fn wrap_float(value:f32,extent:f32)->f32{return value-floor(value/extent)*extent;}
fn sample_scalar(position:vec2<f32>,dimensions:vec2<i32>)->f32{
 let wrapped=vec2<f32>(wrap_float(position.x,f32(dimensions.x)),wrap_float(position.y,f32(dimensions.y)));let base=vec2<i32>(floor(wrapped));let f=fract(wrapped);let next=vec2<i32>((base.x+1)%dimensions.x,(base.y+1)%dimensions.y);
 let a=textureLoad(input_tex,base,0).r;let b=textureLoad(input_tex,vec2<i32>(next.x,base.y),0).r;let c=textureLoad(input_tex,vec2<i32>(base.x,next.y),0).r;let d=textureLoad(input_tex,next,0).r;return mix(mix(a,b,f.x),mix(c,d,f.x),f.y);
}
@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) gid:vec3<u32>){
 let width=i32(params.p0.x);let height=i32(params.p0.y);if(i32(gid.x)>=width||i32(gid.y)>=height){return;}
 let intensity=params.p1.x;let samples=clamp(i32(params.p1.y+0.5),2,128);let mode=i32(params.p1.z+0.5);let dimensions=vec2<i32>(width,height);let coord=vec2<i32>(gid.xy);let pixel=vec2<f32>(gid.xy);
 let gx=(load_slope(coord+vec2<i32>(1,0),dimensions)-load_slope(coord-vec2<i32>(1,0),dimensions))*0.5;let gy=(load_slope(coord+vec2<i32>(0,1),dimensions)-load_slope(coord-vec2<i32>(0,1),dimensions))*0.5;
 let length_value=length(vec2<f32>(gx,gy));var direction=vec2<f32>(0.0);if(length_value>0.000001){direction=vec2<f32>(gx,gy)/length_value;}
 var value=textureLoad(input_tex,coord,0).r;var total=value;
 for(var step:i32=1;step<129;step=step+1){if(step<=samples){let distance=intensity*f32(step)/f32(samples);let sample_value=sample_scalar(pixel+direction*distance,dimensions);if(mode==1){value=min(value,sample_value);}else if(mode==2){value=max(value,sample_value);}else{total=total+sample_value;}}}
 if(mode==0){value=total/f32(samples+1);}value=clamp(value,0.0,1.0);textureStore(output_tex,coord,vec4<f32>(value,value,value,1.0));
}
