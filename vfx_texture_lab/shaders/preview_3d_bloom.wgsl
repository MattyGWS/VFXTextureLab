struct BloomUniforms {
    texel_direction: vec4<f32>,
    parameters: vec4<f32>,
};
@group(0) @binding(0) var<uniform> uniforms: BloomUniforms;
@group(0) @binding(1) var source_tex: texture_2d<f32>;
@group(0) @binding(2) var source_sampler: sampler;
struct VertexOutput { @builtin(position) position: vec4<f32>, @location(0) uv: vec2<f32>, };
@vertex fn vs_main(@builtin(vertex_index) index: u32) -> VertexOutput {
    let positions = array<vec2<f32>, 3>(vec2<f32>(-1.0,-1.0), vec2<f32>(3.0,-1.0), vec2<f32>(-1.0,3.0));
    let p = positions[index]; var output: VertexOutput;
    output.position = vec4<f32>(p,0.0,1.0); output.uv = vec2<f32>(p.x*0.5+0.5,0.5-p.y*0.5); return output;
}
fn bright_pass(colour: vec3<f32>, threshold: f32) -> vec3<f32> {
    let luminance = dot(colour, vec3<f32>(0.2126,0.7152,0.0722));
    let knee = max(threshold*0.35,0.05);
    let soft = clamp((luminance-threshold+knee)/(2.0*knee),0.0,1.0);
    let contribution = max(luminance-threshold,0.0)+soft*soft*knee;
    return colour*(contribution/max(luminance,1.0e-5));
}
fn source_colour(uv: vec2<f32>) -> vec3<f32> {
    let colour = textureSample(source_tex, source_sampler, uv).rgb;
    if (uniforms.parameters.z > 0.5) { return bright_pass(colour, uniforms.parameters.x); }
    return colour;
}
@fragment fn fs_main(input: VertexOutput) -> @location(0) vec4<f32> {
    let step = uniforms.texel_direction.xy * uniforms.texel_direction.zw * uniforms.parameters.y;
    var colour = source_colour(input.uv)*0.2270270270;
    colour += source_colour(input.uv+step*1.0)*0.1945945946; colour += source_colour(input.uv-step*1.0)*0.1945945946;
    colour += source_colour(input.uv+step*2.0)*0.1216216216; colour += source_colour(input.uv-step*2.0)*0.1216216216;
    colour += source_colour(input.uv+step*3.0)*0.0540540541; colour += source_colour(input.uv-step*3.0)*0.0540540541;
    colour += source_colour(input.uv+step*4.0)*0.0162162162; colour += source_colour(input.uv-step*4.0)*0.0162162162;
    return vec4<f32>(max(colour,vec3<f32>(0.0)),1.0);
}
