struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

// @include "resampling_common.wgsl"

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
 let width=u32(params.p0.x); let height=u32(params.p0.y); if(gid.x>=width||gid.y>=height){return;}
 let coord=vec2<i32>(gid.xy); if(params.p2.w<0.5){textureStore(output_tex,coord,vec4<f32>(0.0));return;}
 let size_f=vec2<f32>(f32(width),f32(height)); var left=params.p1.x; var top=params.p1.y; var right=params.p1.z; var bottom=params.p1.w;
 let mode=i32(params.p2.x+0.5);
 if(mode==0){let side=min(max(right-left,bottom-top),1.0);let centre=vec2<f32>((left+right)*0.5,(top+bottom)*0.5);left=clamp(centre.x-side*0.5,0.0,1.0-side);top=clamp(centre.y-side*0.5,0.0,1.0-side);right=left+side;bottom=top+side;}
 let uv=(vec2<f32>(gid.xy)+vec2<f32>(0.5))/size_f; var valid=true; var pixel=vec2<f32>(0.0); var footprint=vec2<f32>(1.0);
 if(mode==1){let box_center=vec2<f32>((left+right)*0.5*f32(width)-0.5,(top+bottom)*0.5*f32(height)-0.5);let out_center=(size_f-vec2<f32>(1.0))*0.5;pixel=vec2<f32>(coord)+(box_center-out_center);valid=all(pixel>=vec2<f32>(0.0))&&all(pixel<=size_f-vec2<f32>(1.0));}
 else if(mode==2){let box_pixels=vec2<f32>((right-left)*f32(width),(bottom-top)*f32(height));let scale=min(f32(width)/max(box_pixels.x,1.0),f32(height)/max(box_pixels.y,1.0));let shown=box_pixels*scale;let local=(vec2<f32>(gid.xy)+vec2<f32>(0.5)-(size_f-shown)*0.5)/max(shown,vec2<f32>(1.0));valid=all(local>=vec2<f32>(0.0))&&all(local<=vec2<f32>(1.0));pixel=mix(vec2<f32>(left,top),vec2<f32>(right,bottom),local)*size_f-vec2<f32>(0.5);footprint=vec2<f32>(1.0/max(scale,1e-6));}
 else {pixel=mix(vec2<f32>(left,top),vec2<f32>(right,bottom),uv)*size_f-vec2<f32>(0.5);footprint=vec2<f32>(max(right-left,1e-6),max(bottom-top,1e-6));}
 if(!valid){textureStore(output_tex,coord,vec4<f32>(0.0));return;}
 let kind=i32(params.p2.z+0.5);var result=sample_filtered(pixel,vec2<i32>(i32(width),i32(height)),1,kind,i32(params.p2.y+0.5),footprint);if(kind==0){result=vec4<f32>(result.r,result.r,result.r,1.0);}textureStore(output_tex,coord,clamp(result,vec4<f32>(0.0),vec4<f32>(1.0)));
}
