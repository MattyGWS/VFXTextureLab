struct Params { p0:vec4<f32>, p1:vec4<f32>, p2:vec4<f32>, p3:vec4<f32>, };
@group(0) @binding(0) var<uniform> params:Params;
@group(0) @binding(1) var state_tex:texture_2d<f32>;
@group(0) @binding(2) var output_tex:texture_storage_2d<rgba32float, write>;
@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) gid:vec3<u32>){let w=u32(params.p0.x);let h=u32(params.p0.y);if(gid.x>=w||gid.y>=h){return;}let c=vec2<i32>(gid.xy);let q=textureLoad(state_tex,c,0);let a=max(q.r-q.a,0.0);var v=1.0-exp(-a*max(params.p1.x,0.000001));if(params.p1.y>=0.5){v=1.0-v;}textureStore(output_tex,c,vec4<f32>(v,v,v,1.0));}
