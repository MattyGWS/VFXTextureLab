struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var normal_tex: texture_2d<f32>;
@group(0) @binding(2) var height_tex: texture_2d<f32>;
@group(0) @binding(3) var output_tex: texture_storage_2d<rgba32float, write>;
fn wrap_coord(value: i32, size: i32) -> i32 { return ((value % size) + size) % size; }
fn resolved(coord: vec2<i32>) -> vec2<i32> {
    let size = vec2<i32>(i32(params.p0.x), i32(params.p0.y));
    if (params.p2.x >= 0.5) { return vec2<i32>(wrap_coord(coord.x,size.x), wrap_coord(coord.y,size.y)); }
    return clamp(coord, vec2<i32>(0), size-vec2<i32>(1));
}
fn sample_height(position: vec2<f32>) -> f32 {
    let base_f=floor(position); let base=vec2<i32>(base_f); let f=position-base_f;
    let a=textureLoad(height_tex,resolved(base),0).r; let b=textureLoad(height_tex,resolved(base+vec2<i32>(1,0)),0).r;
    let c=textureLoad(height_tex,resolved(base+vec2<i32>(0,1)),0).r; let d=textureLoad(height_tex,resolved(base+vec2<i32>(1,1)),0).r;
    return mix(mix(a,b,f.x),mix(c,d,f.x),f.y);
}
fn sample_normal(position: vec2<f32>) -> vec3<f32> {
    let base_f=floor(position); let base=vec2<i32>(base_f); let f=position-base_f;
    let a=textureLoad(normal_tex,resolved(base),0).rgb; let b=textureLoad(normal_tex,resolved(base+vec2<i32>(1,0)),0).rgb;
    let c=textureLoad(normal_tex,resolved(base+vec2<i32>(0,1)),0).rgb; let d=textureLoad(normal_tex,resolved(base+vec2<i32>(1,1)),0).rgb;
    return mix(mix(a,b,f.x),mix(c,d,f.x),f.y)*2.0-vec3<f32>(1.0);
}
@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width=u32(params.p0.x); let height=u32(params.p0.y); if(gid.x>=width||gid.y>=height){return;}
    let p=vec2<i32>(i32(gid.x),i32(gid.y)); let center_position=vec2<f32>(p); let center_height=textureLoad(height_tex,resolved(p),0).r;
    let sigma=max(params.p1.x,0.01); let direction=vec2<f32>(params.p1.y,params.p1.z); let height_sigma=max(params.p1.w,0.0001);
    let spacing=max(sigma*0.65,0.75); let denom=2.0*sigma*sigma; let height_denom=2.0*height_sigma*height_sigma;
    var sum=vec3<f32>(0.0); var weight_sum=0.0;
    for(var tap=-4;tap<=4;tap=tap+1){
        let distance=f32(tap)*spacing; let sample_position=center_position+direction*distance;
        let n=sample_normal(sample_position); let h=sample_height(sample_position);
        let spatial=exp(-(distance*distance)/denom); let dh=h-center_height; let range=exp(-(dh*dh)/height_denom); let w=spatial*range;
        sum=sum+n*w; weight_sum=weight_sum+w;
    }
    var n=sum/max(weight_sum,0.000001); n=normalize(select(n,vec3<f32>(0.0,0.0,1.0),dot(n,n)<0.00000001));
    textureStore(output_tex,p,vec4<f32>(clamp(n*0.5+vec3<f32>(0.5),vec3<f32>(0.0),vec3<f32>(1.0)),1.0));
}
