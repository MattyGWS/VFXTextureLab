struct Params { p0:vec4<f32>, p1:vec4<f32>, p2:vec4<f32>, p3:vec4<f32>, };
@group(0) @binding(0) var<uniform> params:Params;
@group(0) @binding(1) var state_tex:texture_2d<f32>;
@group(0) @binding(2) var original_tex:texture_2d<f32>;
@group(0) @binding(3) var output_tex:texture_storage_2d<rgba32float, write>;
const DIRS:array<vec2<i32>,8>=array<vec2<i32>,8>(
 vec2<i32>(-1,0),vec2<i32>(1,0),vec2<i32>(0,-1),vec2<i32>(0,1),
 vec2<i32>(-1,-1),vec2<i32>(1,-1),vec2<i32>(-1,1),vec2<i32>(1,1)
);
fn in_bounds(c:vec2<i32>,size:vec2<i32>)->bool{return c.x>=0&&c.y>=0&&c.x<size.x&&c.y<size.y;}
fn wrapped(c:vec2<i32>,size:vec2<i32>)->vec2<i32>{return vec2<i32>((c.x%size.x+size.x)%size.x,(c.y%size.y+size.y)%size.y);}
fn load_state(c:vec2<i32>,size:vec2<i32>,boundary:u32)->vec4<f32>{
 if(boundary==0u){return textureLoad(state_tex,wrapped(c,size),0);}
 if(in_bounds(c,size)){return textureLoad(state_tex,c,0);}
 if(boundary==1u){return textureLoad(state_tex,clamp(c,vec2<i32>(0),size-vec2<i32>(1)),0);}
 return vec4<f32>(0.0);
}
fn original_at(c:vec2<i32>,size:vec2<i32>,boundary:u32)->f32{
 if(boundary==0u){return textureLoad(original_tex,wrapped(c,size),0).r;}
 if(in_bounds(c,size)){return textureLoad(original_tex,c,0).r;}
 if(boundary==1u){return textureLoad(original_tex,clamp(c,vec2<i32>(0),size-vec2<i32>(1)),0).r;}
 return 0.0;
}
fn fracture_variation(c:vec2<i32>,size:vec2<i32>,boundary:u32)->f32{
 let scale=clamp(params.p3.y,0.0,1.0);
 let center=original_at(c,size,boundary);
 let left=original_at(c+vec2<i32>(-1,0),size,boundary);
 let right=original_at(c+vec2<i32>(1,0),size,boundary);
 let up=original_at(c+vec2<i32>(0,-1),size,boundary);
 let down=original_at(c+vec2<i32>(0,1),size,boundary);
 let broad=(center*4.0+left+right+up+down)/8.0;
 let gx=right-left;
 let gy=down-up;
 let detail=center-broad;
 let phase=broad*(3.0+7.0*scale)+detail*(9.0+15.0*scale)+(gx-gy)*(5.0+9.0*scale)+params.p3.z*0.173;
 let value=0.55+0.30*sin(phase*6.28318530718)+0.15*cos((phase*0.47+gx+gy)*6.28318530718);
 return clamp(value,0.0,1.0);
}
fn excess_for(c:vec2<i32>,size:vec2<i32>,boundary:u32,index:u32,current_h:f32)->f32{
 let destination=c+DIRS[index];
 if(boundary==1u&&!in_bounds(destination,size)){return 0.0;}
 let neighbour_h=load_state(destination,size,boundary).r;
 let distance=select(1.0,1.41421356,index>=4u);
 return max(current_h-neighbour_h-params.p1.x*distance,0.0);
}
fn total_outflow(c:vec2<i32>,size:vec2<i32>,boundary:u32)->vec2<f32>{
 if(boundary!=0u&&!in_bounds(c,size)){return vec2<f32>(0.0);}
 let current=load_state(c,size,boundary);
 let count=select(4u,8u,params.p1.w>=7.5);
 var total_excess=0.0;
 for(var i=0u;i<8u;i=i+1u){if(i>=count){break;}total_excess+=excess_for(c,size,boundary,i,current.r);}
 let production=mix(1.0,fracture_variation(c,size,boundary),clamp(params.p3.x,0.0,1.0));
 let erodibility=clamp(1.0-current.a,0.0,1.0)*(1.0-clamp(params.p2.z,0.0,1.0))*production;
 let mobility=clamp(params.p2.y,0.0,1.0);
 var amount=total_excess*clamp(params.p1.y,0.0,1.0)*(0.28+0.72*mobility)*erodibility;
 amount=min(amount,max(params.p1.z,0.0)*(0.20+0.80*mobility));
 amount=min(amount,max(current.r,0.0)*0.45);
 return vec2<f32>(total_excess,max(amount,0.0));
}
fn sent_in_direction(c:vec2<i32>,size:vec2<i32>,boundary:u32,index:u32)->f32{
 if(boundary!=0u&&!in_bounds(c,size)){return 0.0;}
 let current=load_state(c,size,boundary);
 let totals=total_outflow(c,size,boundary);
 if(totals.x<=0.000000000001){return 0.0;}
 let excess=excess_for(c,size,boundary,index,current.r);
 return totals.y*excess/totals.x;
}
@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) gid:vec3<u32>){
 let size=vec2<i32>(i32(params.p0.x),i32(params.p0.y));
 let c=vec2<i32>(gid.xy);
 if(!in_bounds(c,size)){return;}
 let boundary=u32(params.p2.x);
 let state=textureLoad(state_tex,c,0);
 let own=total_outflow(c,size,boundary).y;
 let count=select(4u,8u,params.p1.w>=7.5);
 var incoming=0.0;
 for(var i=0u;i<8u;i=i+1u){
   if(i>=count){break;}
   let sender=c-DIRS[i];
   if(boundary!=0u&&!in_bounds(sender,size)){continue;}
   incoming+=sent_in_direction(sender,size,boundary,i);
 }
 var new_h=clamp(state.r-own+incoming,0.0,1.0);
 if(params.p2.w>0.0){
   let original=textureLoad(original_tex,c,0).r;
   new_h=clamp(new_h+(original-new_h)*params.p2.w*(1.0-state.a),0.0,1.0);
 }
 textureStore(output_tex,c,vec4<f32>(new_h,min(state.g+own,1000000.0),min(state.b+incoming,1000000.0),state.a));
}
