struct Params { p0:vec4<f32>, p1:vec4<f32>, p2:vec4<f32>, p3:vec4<f32>, p4:vec4<f32>, };
@group(0) @binding(0) var<uniform> params:Params;
@group(0) @binding(1) var state_tex:texture_2d<f32>;
@group(0) @binding(2) var accum_tex:texture_2d<f32>;
@group(0) @binding(3) var rain_tex:texture_2d<f32>;
@group(0) @binding(4) var state_out:texture_storage_2d<rgba32float, write>;
@group(0) @binding(5) var accum_out:texture_storage_2d<rgba32float, write>;
const DIRS:array<vec2<i32>,4>=array<vec2<i32>,4>(vec2<i32>(-1,0),vec2<i32>(1,0),vec2<i32>(0,-1),vec2<i32>(0,1));
fn inside(c:vec2<i32>,s:vec2<i32>)->bool{return c.x>=0&&c.y>=0&&c.x<s.x&&c.y<s.y;}
fn wrap(c:vec2<i32>,s:vec2<i32>)->vec2<i32>{return vec2<i32>((c.x%s.x+s.x)%s.x,(c.y%s.y+s.y)%s.y);}
fn st(c:vec2<i32>,s:vec2<i32>,b:u32)->vec4<f32>{if(b==0u){return textureLoad(state_tex,wrap(c,s),0);}if(inside(c,s)){return textureLoad(state_tex,c,0);}if(b==1u){return textureLoad(state_tex,clamp(c,vec2<i32>(0),s-vec2<i32>(1)),0);}return vec4<f32>(0.0);}
fn ac(c:vec2<i32>,s:vec2<i32>,b:u32)->vec4<f32>{if(b==0u){return textureLoad(accum_tex,wrap(c,s),0);}if(inside(c,s)){return textureLoad(accum_tex,c,0);}return vec4<f32>(0.0);}
fn rain(c:vec2<i32>,s:vec2<i32>)->f32{let cc=wrap(c,s);let mask=clamp(textureLoad(rain_tex,cc,0).r,0.0,1.0);let n=fract(sin(dot(vec2<f32>(cc),vec2<f32>(12.9898,78.233))+params.p3.w*37.719)*43758.5453);return mask*params.p1.x*mix(1.0,n,clamp(params.p1.y,0.0,1.0));}
fn flow(c:vec2<i32>,s:vec2<i32>,b:u32)->vec4<f32>{
 let q=st(c,s,b);if(b!=0u&&!inside(c,s)){return vec4<f32>(0.0);}let water=max(q.y+rain(c,s),0.0);let surface=q.x+water;var drops=vec4<f32>(0.0);var sumd=0.0;
 for(var i=0u;i<4u;i=i+1u){let n=c+DIRS[i];if(b==1u&&!inside(n,s)){continue;}let nq=st(n,s,b);let nr=select(0.0,rain(n,s),b==0u||inside(n,s));let d=max(surface-(nq.x+nq.y+nr),0.0);drops[i]=d;sumd+=d;}
 if(sumd<=0.0000001||water<=0.0){return vec4<f32>(0.0);}let mobility=clamp(params.p1.z*(1.0-params.p4.y),0.0,1.0);let total=min(water,(sumd*params.p4.x+water*0.08)*mobility);return drops/sumd*total;
}
@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) gid:vec3<u32>){
 let s=vec2<i32>(i32(params.p0.x),i32(params.p0.y));let c=vec2<i32>(gid.xy);if(!inside(c,s)){return;}let b=u32(params.p3.z);let q=textureLoad(state_tex,c,0);let a=textureLoad(accum_tex,c,0);let water0=max(q.y+rain(c,s),0.0);let own=flow(c,s,b);let out_total=own.x+own.y+own.z+own.w;var incoming=0.0;var incoming_sed=0.0;
 for(var i=0u;i<4u;i=i+1u){let sender=c-DIRS[i];if(b!=0u&&!inside(sender,s)){continue;}let sf=flow(sender,s,b);let amount=sf[i];let sq=st(sender,s,b);incoming+=amount;incoming_sed+=amount*(sq.z/max(sq.y+rain(sender,s),0.000001));}
 let sent_sed=min(q.z,out_total*(q.z/max(water0,0.000001)));var transported=max(q.z-sent_sed+incoming_sed,0.0);var water=max(water0-out_total+incoming,0.0);
 let left=st(c+vec2<i32>(-1,0),s,b);let right=st(c+vec2<i32>(1,0),s,b);let up=st(c+vec2<i32>(0,-1),s,b);let down=st(c+vec2<i32>(0,1),s,b);let gx=((right.x+right.y)-(left.x+left.y))*0.5;let gy=((down.x+down.y)-(up.x+up.y))*0.5;let slope=length(vec2<f32>(gx,gy))*params.p4.w;
 let throughput=out_total+incoming;let flow_acc=a.z+throughput;let channel=1.0+params.p3.x*pow(flow_acc/(flow_acc+1.0),max(params.p3.y,0.1));let capacity=params.p2.x*max(slope,0.00001)*max(throughput,0.00001)*channel;
 let soft=clamp(1.0-q.w,0.0,1.0);var erode=max(capacity-transported,0.0)*params.p2.y*soft;erode=min(erode,params.p4.z);erode=min(erode,max(q.x,0.0));var deposit=max(transported-capacity,0.0)*params.p2.z;deposit+=transported*params.p2.w*params.p1.w;deposit=min(deposit,transported+erode);
 let h=clamp(q.x-erode+deposit,0.0,1.0);transported=max(transported+erode-deposit,0.0);water*=1.0-clamp(params.p1.w,0.0,0.99);textureStore(state_out,c,vec4<f32>(h,water,transported,q.w));textureStore(accum_out,c,vec4<f32>(a.x+erode,a.y+deposit,flow_acc,max(a.w*0.985,water)));
}
