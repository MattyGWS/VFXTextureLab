struct Params { p0:vec4<f32>, p1:vec4<f32>, p2:vec4<f32>, p3:vec4<f32>, };
@group(0) @binding(0) var<uniform> params:Params;
@group(0) @binding(1) var state_tex:texture_2d<f32>;
@group(0) @binding(2) var output_tex:texture_storage_2d<rgba32float, write>;
@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) gid:vec3<u32>){let w=u32(params.p0.x);let h=u32(params.p0.y);if(gid.x>=w||gid.y>=h){return;}let s=textureLoad(state_tex,vec2<i32>(gid.xy),0);let mode=u32(params.p1.x);var v=s.r;if(mode==1u){v=clamp(s.g*params.p1.y,0.0,1.0);}else if(mode==2u){v=clamp(s.b*params.p1.y,0.0,1.0);}textureStore(output_tex,vec2<i32>(gid.xy),vec4<f32>(v,v,v,1.0));}
