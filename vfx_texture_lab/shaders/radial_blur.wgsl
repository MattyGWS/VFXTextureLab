struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;
fn wrap_float(value: f32, extent: f32) -> f32 { return value - floor(value / extent) * extent; }
fn sample_bilinear(position: vec2<f32>, dimensions: vec2<i32>) -> vec4<f32> {
    let wrapped = vec2<f32>(wrap_float(position.x, f32(dimensions.x)), wrap_float(position.y, f32(dimensions.y)));
    let base = vec2<i32>(floor(wrapped)); let fraction = fract(wrapped);
    let next = vec2<i32>((base.x + 1) % dimensions.x, (base.y + 1) % dimensions.y);
    let a = textureLoad(input_tex, base, 0); let b = textureLoad(input_tex, vec2<i32>(next.x, base.y), 0);
    let c = textureLoad(input_tex, vec2<i32>(base.x, next.y), 0); let d = textureLoad(input_tex, next, 0);
    return mix(mix(a,b,fraction.x), mix(c,d,fraction.x), fraction.y);
}
@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width=i32(params.p0.x); let height=i32(params.p0.y);
    if (i32(gid.x)>=width || i32(gid.y)>=height) { return; }
    let amount = abs(params.p1.x) * 0.017453292519943295;
    let centre = vec2<f32>(params.p1.y * f32(width), params.p1.z * f32(height));
    let samples = clamp(i32(params.p1.w + 0.5), 2, 128);
    let pixel=vec2<f32>(gid.xy); let delta=pixel-centre; let dimensions=vec2<i32>(width,height);
    var total=vec4<f32>(0.0);
    for (var index:i32=0; index<128; index=index+1) {
        if (index<samples) {
            let t=f32(index)/f32(samples-1)-0.5; let angle=amount*t;
            let c=cos(angle); let s=sin(angle);
            let position=centre+vec2<f32>(delta.x*c-delta.y*s, delta.x*s+delta.y*c);
            total=total+sample_bilinear(position,dimensions);
        }
    }
    textureStore(output_tex,vec2<i32>(gid.xy),total/f32(samples));
}
