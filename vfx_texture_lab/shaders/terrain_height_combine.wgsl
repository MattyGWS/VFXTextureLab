struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var a_tex:texture_2d<f32>;
@group(0) @binding(2) var b_tex:texture_2d<f32>;
@group(0) @binding(3) var mask_tex:texture_2d<f32>;
@group(0) @binding(4) var output_tex:texture_storage_2d<rgba32float, write>;
@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) gid:vec3<u32>){
 let w=u32(params.p0.x);let h=u32(params.p0.y);if(gid.x>=w||gid.y>=h){return;}let c=vec2<i32>(gid.xy);let a=textureLoad(a_tex,c,0).r;let b=textureLoad(b_tex,c,0).r;let mode=u32(params.p1.x);var mixed=max(a,b);
 if(mode==0u){mixed=a+b;}else if(mode==1u){mixed=a-b;}else if(mode==2u){mixed=a*b;}else if(mode==4u){mixed=min(a,b);}else if(mode==5u){mixed=(a+b)*0.5;}else if(mode==6u){mixed=abs(a-b);}
 let opacity=clamp(params.p1.y*textureLoad(mask_tex,c,0).r,0.0,1.0);var v=mix(a,mixed,opacity);if(params.p1.z>=0.5){v=clamp(v,0.0,1.0);}textureStore(output_tex,c,vec4<f32>(v,v,v,1.0));
}
