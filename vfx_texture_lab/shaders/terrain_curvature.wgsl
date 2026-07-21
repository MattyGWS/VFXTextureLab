struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var height_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;
fn sample_h(x:u32,y:u32)->f32{return textureLoad(height_tex,vec2<i32>(i32(x),i32(y)),0).r;}
@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) gid:vec3<u32>){
 let w=u32(params.p0.x);let h=u32(params.p0.y);if(gid.x>=w||gid.y>=h){return;}
 let c=sample_h(gid.x,gid.y);let lap=sample_h((gid.x+w-1u)%w,gid.y)+sample_h((gid.x+1u)%w,gid.y)+sample_h(gid.x,(gid.y+h-1u)%h)+sample_h(gid.x,(gid.y+1u)%h)-4.0*c;
 let signed_value=lap*params.p1.y;let mode=u32(params.p1.x);var v=0.5+0.5*signed_value;
 if(mode==1u){v=max(-signed_value,0.0);}else if(mode==2u){v=max(signed_value,0.0);}else if(mode==3u){v=abs(signed_value);}
 v=clamp((v-0.5)*params.p1.z+0.5,0.0,1.0);if(params.p1.w>=0.5){v=1.0-v;}
 textureStore(output_tex,vec2<i32>(gid.xy),vec4<f32>(v,v,v,1.0));
}
