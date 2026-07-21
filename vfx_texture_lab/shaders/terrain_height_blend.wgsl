struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var base_tex:texture_2d<f32>;
@group(0) @binding(2) var layer_tex:texture_2d<f32>;
@group(0) @binding(3) var mask_tex:texture_2d<f32>;
@group(0) @binding(4) var output_tex:texture_storage_2d<rgba32float, write>;
@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) gid:vec3<u32>){
 let w=u32(params.p0.x);let h=u32(params.p0.y);if(gid.x>=w||gid.y>=h){return;}let c=vec2<i32>(gid.xy);let base=textureLoad(base_tex,c,0).r;let layer=textureLoad(layer_tex,c,0).r;let mask=textureLoad(mask_tex,c,0).r;
 let transition=max(params.p1.y,0.000001);let dominance=(layer+params.p1.x-base+params.p1.z)/transition;let hw=smoothstep(0.0,1.0,dominance*0.5+0.5);let weight=clamp(mask*params.p1.w*hw,0.0,1.0);let v=clamp(mix(base,layer,weight),0.0,1.0);
 textureStore(output_tex,c,vec4<f32>(v,v,v,1.0));
}
