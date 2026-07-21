struct Params { p0:vec4<f32>, p1:vec4<f32>, p2:vec4<f32>, p3:vec4<f32>, };
@group(0) @binding(0) var<uniform> params:Params;
@group(0) @binding(1) var height_tex:texture_2d<f32>;
@group(0) @binding(2) var output_tex:texture_storage_2d<rgba32float, write>;
fn wrap(c:vec2<i32>,s:vec2<i32>)->vec2<i32>{return vec2<i32>((c.x%s.x+s.x)%s.x,(c.y%s.y+s.y)%s.y);}
fn h(c:vec2<i32>,s:vec2<i32>)->f32{return textureLoad(height_tex,wrap(c,s),0).r;}
@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) gid:vec3<u32>){
 let s=vec2<i32>(i32(params.p0.x),i32(params.p0.y));let c=vec2<i32>(gid.xy);if(c.x>=s.x||c.y>=s.y){return;}
 let strength=max(params.p1.x,0.000001);let gx=(h(c+vec2<i32>(1,0),s)-h(c-vec2<i32>(1,0),s))*0.5*strength;let gy=(h(c+vec2<i32>(0,1),s)-h(c-vec2<i32>(0,1),s))*0.5*strength;
 let l=length(vec2<f32>(gx,gy));var d=vec2<f32>(0.0);if(l>0.0000001){d=-vec2<f32>(gx,gy)/l;}
 textureStore(output_tex,c,vec4<f32>(d*0.5+vec2<f32>(0.5),0.5,1.0));
}
