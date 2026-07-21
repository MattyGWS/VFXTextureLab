struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, p4: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var mask_tex: texture_2d<f32>;
@group(0) @binding(3) var output_tex: texture_storage_2d<rgba32float, write>;

// @include "resampling_common.wgsl"

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x); let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let size_i = vec2<i32>(i32(width),i32(height)); let size_f=vec2<f32>(f32(width),f32(height));
    let uv=(vec2<f32>(gid.xy)+vec2<f32>(0.5))/size_f;
    let d=uv-params.p1.zw; let angle=-params.p3.x*0.017453292519943295;
    let c=cos(angle); let s=sin(angle); let scale=max(params.p2.w,1e-4);
    let d_pixels=d*size_f;
    let local_pixels=vec2<f32>(d_pixels.x*c-d_pixels.y*s,d_pixels.x*s+d_pixels.y*c)/scale;
    let source_uv=params.p1.xy+local_pixels/size_f; let pixel=source_uv*size_f-vec2<f32>(0.5);
    let boundary=select(1,2,params.p3.y>=0.5); let kind=i32(params.p3.w+0.5);
    let sampled_patch=sample_filtered(pixel,size_i,boundary,kind,i32(params.p4.x+0.5),params.p4.yz);
    let radius_px=max(params.p2.x,1e-5)*min(f32(width),f32(height));
    let distance_px=length(d*size_f); let inner=radius_px*(1.0-clamp(params.p2.y,0.0,1.0));
    let t=clamp((distance_px-inner)/max(radius_px-inner,1e-6),0.0,1.0);
    var coverage=(1.0-t*t*(3.0-2.0*t))*clamp(params.p2.z,0.0,1.0);
    if (params.p3.z>=0.5) { coverage*=textureLoad(mask_tex,vec2<i32>(gid.xy),0).r; }
    let original=textureLoad(input_tex,vec2<i32>(gid.xy),0);
    var result=mix(original,sampled_patch,coverage);
    if (kind==2) { var n=result.rgb*2.0-vec3<f32>(1.0); let l=length(n); n=select(vec3<f32>(0.0,0.0,1.0),n/max(l,1e-7),l>1e-7); result=vec4<f32>(n*0.5+vec3<f32>(0.5),result.a); }
    if (kind==0) { result=vec4<f32>(result.r,result.r,result.r,1.0); }
    textureStore(output_tex,vec2<i32>(gid.xy),clamp(result,vec4<f32>(0.0),vec4<f32>(1.0)));
}
