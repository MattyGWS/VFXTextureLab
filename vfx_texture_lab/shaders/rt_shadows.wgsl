struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var height_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;
const PI: f32 = 3.141592653589793; const GOLDEN_ANGLE: f32 = 2.399963229728653;
fn wrap_coord(value:i32,size:i32)->i32{return ((value%size)+size)%size;}
fn resolved(coord:vec2<i32>)->vec2<i32>{let size=vec2<i32>(i32(params.p0.x),i32(params.p0.y));if(params.p3.x>=0.5){return vec2<i32>(wrap_coord(coord.x,size.x),wrap_coord(coord.y,size.y));}return clamp(coord,vec2<i32>(0),size-vec2<i32>(1));}
fn sample_height_i(coord:vec2<i32>)->f32{return textureLoad(height_tex,resolved(coord),0).r;}
fn sample_height(position:vec2<f32>)->f32{let base_f=floor(position);let base=vec2<i32>(base_f);let f=position-base_f;let a=sample_height_i(base);let b=sample_height_i(base+vec2<i32>(1,0));let c=sample_height_i(base+vec2<i32>(0,1));let d=sample_height_i(base+vec2<i32>(1,1));return mix(mix(a,b,f.x),mix(c,d,f.x),f.y);}
fn minmod(a:f32,b:f32)->f32{if(a*b<=0.0){return 0.0;}return sign(a)*min(abs(a),abs(b));}
@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) gid:vec3<u32>){
 let width=u32(params.p0.x);let height=u32(params.p0.y);if(gid.x>=width||gid.y>=height){return;}
 let p=vec2<i32>(i32(gid.x),i32(gid.y));let center=sample_height_i(p);let height_scale=max(params.p1.x,0.0);
 let base_angle=params.p1.y*0.017453292519943295;let base_elevation=clamp(params.p1.z,0.1,89.9)*0.017453292519943295;
 let max_distance=max(params.p1.w,0.0);let softness=clamp(params.p2.x,0.0,1.0);let sample_count=max(u32(round(params.p2.y)),1u);
 let step_count=max(u32(round(params.p2.z)),1u);let bias=max(params.p2.w,0.0)+0.00025;let strength=clamp(params.p3.y,0.0,1.0);let invert=params.p3.z>=0.5;
 if(height_scale<=0.00000001||max_distance<=0.00000001){let v=select(1.0,0.0,invert);textureStore(output_tex,p,vec4<f32>(v,v,v,1.0));return;}
 let left=sample_height_i(p+vec2<i32>(-1,0));let right=sample_height_i(p+vec2<i32>(1,0));let up=sample_height_i(p+vec2<i32>(0,-1));let down=sample_height_i(p+vec2<i32>(0,1));
 let grad_x=minmod(center-left,right-center);let grad_y=minmod(center-up,down-center);let min_dim=max(min(f32(width),f32(height)),1.0);var lit=0.0;
 for(var sample=0u;sample<32u;sample=sample+1u){if(sample>=sample_count){break;}var angle=base_angle;var elevation=base_elevation;
  if(sample_count>1u&&softness>0.00000001){let radius=sqrt((f32(sample)+0.5)/f32(sample_count))*softness;let phase=f32(sample)*GOLDEN_ANGLE;angle=angle+cos(phase)*radius*0.40;elevation=clamp(elevation+sin(phase)*radius*0.25,0.0017453293,1.5690509975);}
  let direction=vec2<f32>(cos(angle),sin(angle));let slope=tan(elevation);var hit=false;
  for(var step=0u;step<28u;step=step+1u){if(step>=step_count){break;}let linear=(f32(step)+1.0)/f32(step_count);let fraction=pow(linear,1.25);let distance=max_distance*fraction;let offset=direction*distance;
   let sampled=sample_height(vec2<f32>(p)+offset);let tangent=center+grad_x*offset.x+grad_y*offset.y;let relative=(sampled-tangent)*height_scale;let ray_height=(distance/min_dim)*slope;if(relative>ray_height+bias){hit=true;break;}}
  if(!hit){lit=lit+1.0;}
 }
 var value=lit/f32(sample_count);value=1.0-(1.0-value)*strength;if(invert){value=1.0-value;}value=clamp(value,0.0,1.0);textureStore(output_tex,p,vec4<f32>(value,value,value,1.0));
}
