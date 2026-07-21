struct Params { p0:vec4<f32>, p1:vec4<f32>, p2:vec4<f32>, p3:vec4<f32>, };
@group(0) @binding(0) var<uniform> params:Params;
@group(0) @binding(1) var height_tex:texture_2d<f32>;
@group(0) @binding(2) var state_tex:texture_2d<f32>;
@group(0) @binding(3) var output_tex:texture_storage_2d<rgba32float, write>;
const DIRS:array<vec2<i32>,8>=array<vec2<i32>,8>(vec2<i32>(0,-1),vec2<i32>(0,1),vec2<i32>(-1,0),vec2<i32>(1,0),vec2<i32>(-1,-1),vec2<i32>(1,-1),vec2<i32>(-1,1),vec2<i32>(1,1));
fn inside(c:vec2<i32>,s:vec2<i32>)->bool{return c.x>=0&&c.y>=0&&c.x<s.x&&c.y<s.y;}
fn wrap(c:vec2<i32>,s:vec2<i32>)->vec2<i32>{return vec2<i32>((c.x%s.x+s.x)%s.x,(c.y%s.y+s.y)%s.y);}
fn hc(c:vec2<i32>,s:vec2<i32>,b:u32)->f32{if(b==0u){return textureLoad(height_tex,wrap(c,s),0).r;}if(inside(c,s)){return textureLoad(height_tex,c,0).r;}if(b==1u){return textureLoad(height_tex,clamp(c,vec2<i32>(0),s-vec2<i32>(1)),0).r;}return 0.0;}
fn ac(c:vec2<i32>,s:vec2<i32>,b:u32)->vec4<f32>{if(b==0u){return textureLoad(state_tex,wrap(c,s),0);}if(inside(c,s)){return textureLoad(state_tex,c,0);}return vec4<f32>(0.0);}
fn choose_target(c:vec2<i32>,s:vec2<i32>,b:u32,count:u32)->vec3<i32>{let here=hc(c,s,b);var best=-1e20;var bi=-1;for(var i=0u;i<8u;i=i+1u){if(i>=count){break;}let n=c+DIRS[i];if(b==1u&&!inside(n,s)){continue;}let dist=select(1.0,1.41421356,i>=4u);let drop=(here-hc(n,s,b))/dist;if(drop>best){best=drop;bi=i32(i);}}return vec3<i32>(bi,i32(select(0.0,1.0,best>params.p1.y)),0);}
@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) gid:vec3<u32>){
 let s=vec2<i32>(i32(params.p0.x),i32(params.p0.y));let c=vec2<i32>(gid.xy);if(!inside(c,s)){return;}let b=u32(params.p1.w);let count=select(4u,8u,params.p1.z>=7.5);let own=textureLoad(state_tex,c,0);var incoming=0.0;
 for(var i=0u;i<8u;i=i+1u){if(i>=count){break;}let sender=c-DIRS[i];if(b!=0u&&!inside(sender,s)){continue;}let t=choose_target(sender,s,b,count);if(t.y==1&&t.x==i32(i)){incoming+=ac(sender,s,b).r*params.p1.x;}}
 let next=own.a+incoming;textureStore(output_tex,c,vec4<f32>(next,incoming,0.0,own.a));
}
