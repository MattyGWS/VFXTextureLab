struct Params {
    p0: vec4<f32>,
    positions0: vec4<f32>, positions1: vec4<f32>,
    colors: array<vec4<f32>, 8>,
};
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;
fn luminance(v: vec4<f32>) -> f32 { return dot(v.rgb, vec3<f32>(0.2126, 0.7152, 0.0722)); }
fn srgb_to_linear_channel(value: f32) -> f32 {
    if (value <= 0.04045) {
        return value / 12.92;
    }
    return pow((value + 0.055) / 1.055, 2.4);
}
fn srgb_to_linear(value: vec3<f32>) -> vec3<f32> {
    return vec3<f32>(
        srgb_to_linear_channel(value.r),
        srgb_to_linear_channel(value.g),
        srgb_to_linear_channel(value.b)
    );
}
fn pos(i: u32) -> f32 { return select(params.positions0[i], params.positions1[i-4u], i >= 4u); }
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let w=u32(params.p0.x); let h=u32(params.p0.y); if(gid.x>=w||gid.y>=h){return;}
    let coord=vec2<i32>(gid.xy); let source=textureLoad(input_tex,coord,0); let v=clamp(select(luminance(source), source.r, params.p0.w >= 0.5),0.0,1.0);
    let count=max(u32(params.p0.z),2u); var result=params.colors[0];
    for(var i:u32=0u;i<7u;i=i+1u){ if(i+1u>=count){break;} let a=pos(i); let b=pos(i+1u);
        if(v<=b || i+2u==count){ let t=clamp((v-a)/max(b-a,0.000001),0.0,1.0); result=mix(params.colors[i],params.colors[i+1u],t); break; }
    }
    let display_result = clamp(result, vec4<f32>(0.0), vec4<f32>(1.0));
    textureStore(output_tex, coord, vec4<f32>(srgb_to_linear(display_result.rgb), display_result.a));
}
