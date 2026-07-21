struct Params { p0:vec4<f32>, p1:vec4<f32>, p2:vec4<f32>, p3:vec4<f32>, };
@group(0) @binding(0) var<uniform> params:Params;
@group(0) @binding(1) var height_tex:texture_2d<f32>;
@group(0) @binding(2) var hardness_tex:texture_2d<f32>;
@group(0) @binding(3) var output_tex:texture_storage_2d<rgba32float, write>;
@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) gid:vec3<u32>){let w=u32(params.p0.x);let h=u32(params.p0.y);if(gid.x>=w||gid.y>=h){return;}let c=vec2<i32>(gid.xy);textureStore(output_tex,c,vec4<f32>(textureLoad(height_tex,c,0).r,0.0,0.0,textureLoad(hardness_tex,c,0).r));}
