struct PostUniforms {
    inverse_view_proj: mat4x4<f32>,
    camera_position: vec4<f32>,
    background: vec4<f32>,
    display: vec4<f32>,
    bloom: vec4<f32>,
    effects: vec4<f32>,
    viewport: vec4<f32>,
};

@group(0) @binding(0) var<uniform> uniforms: PostUniforms;
@group(0) @binding(1) var scene_tex: texture_2d<f32>;
@group(0) @binding(2) var scene_sampler: sampler;
@group(0) @binding(3) var environment_tex: texture_2d<f32>;
@group(0) @binding(4) var environment_sampler: sampler;
@group(0) @binding(5) var bloom_tex: texture_2d<f32>;

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) index: u32) -> VertexOutput {
    let positions = array<vec2<f32>, 3>(
        vec2<f32>(-1.0, -1.0),
        vec2<f32>(3.0, -1.0),
        vec2<f32>(-1.0, 3.0)
    );
    let p = positions[index];
    var output: VertexOutput;
    output.position = vec4<f32>(p, 0.0, 1.0);
    output.uv = vec2<f32>(p.x * 0.5 + 0.5, 0.5 - p.y * 0.5);
    return output;
}

fn environment_uv(direction: vec3<f32>) -> vec2<f32> {
    let d = normalize(direction);
    let rotation = uniforms.effects.w / 6.28318530718;
    return vec2<f32>(
        fract(atan2(d.x, d.z) / 6.28318530718 + 0.5 + rotation),
        acos(clamp(d.y, -1.0, 1.0)) / 3.14159265359
    );
}

fn background_colour(uv: vec2<f32>) -> vec3<f32> {
    let solid = uniforms.background.rgb;
    if (uniforms.effects.z < 0.5) {
        return solid;
    }
    let ndc = vec2<f32>(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0);
    let near_h = uniforms.inverse_view_proj * vec4<f32>(ndc, 0.0, 1.0);
    let far_h = uniforms.inverse_view_proj * vec4<f32>(ndc, 1.0, 1.0);
    let near_position = near_h.xyz / max(abs(near_h.w), 1.0e-6);
    let far_position = far_h.xyz / max(abs(far_h.w), 1.0e-6);
    let perspective = uniforms.viewport.z > 0.5;
    let ray = normalize(select(far_position - near_position, far_position - uniforms.camera_position.xyz, perspective));
    let environment = textureSampleLevel(environment_tex, environment_sampler, environment_uv(ray), 0.0).rgb;
    return mix(solid, environment, clamp(uniforms.background.a, 0.0, 1.0));
}

fn tone_aces(colour: vec3<f32>) -> vec3<f32> {
    let a = 2.51;
    let b = 0.03;
    let c = 2.43;
    let d = 0.59;
    let e = 0.14;
    return clamp((colour * (a * colour + b)) / (colour * (c * colour + d) + e), vec3<f32>(0.0), vec3<f32>(1.0));
}

fn tone_neutral(colour: vec3<f32>) -> vec3<f32> {
    let start_compression = 0.8 - 0.04;
    let desaturation = 0.15;
    let x = min(colour.r, min(colour.g, colour.b));
    let offset = select(x - 6.25 * x * x, 0.04, x >= 0.08);
    var result = colour - offset;
    let peak = max(result.r, max(result.g, result.b));
    if (peak >= start_compression) {
        let d = 1.0 - start_compression;
        let new_peak = 1.0 - d * d / (peak + d - start_compression);
        result *= new_peak / peak;
        let g = 1.0 - 1.0 / (desaturation * (peak - new_peak) + 1.0);
        result = mix(result, vec3<f32>(new_peak), g);
    }
    return clamp(result, vec3<f32>(0.0), vec3<f32>(1.0));
}

fn apply_tone_mapping(colour: vec3<f32>) -> vec3<f32> {
    let mode = i32(round(uniforms.display.y));
    if (mode == 0) {
        return tone_aces(colour);
    }
    if (mode == 1) {
        return tone_neutral(colour);
    }
    if (mode == 2) {
        return colour / (vec3<f32>(1.0) + colour);
    }
    return clamp(colour, vec3<f32>(0.0), vec3<f32>(1.0));
}

@fragment
fn fs_main(input: VertexOutput) -> @location(0) vec4<f32> {
    let scene = textureSample(scene_tex, scene_sampler, input.uv);
    let background = background_colour(input.uv);
    var colour = scene.rgb + background * (1.0 - clamp(scene.a, 0.0, 1.0));

    if (uniforms.display.z > 0.5) {
        colour += textureSample(bloom_tex, scene_sampler, input.uv).rgb * uniforms.display.w;
    }
    if (uniforms.bloom.z > 0.5) {
        let step = uniforms.viewport.xy;
        let neighbours = (
            textureSample(scene_tex, scene_sampler, input.uv + vec2<f32>( step.x, 0.0)).rgb +
            textureSample(scene_tex, scene_sampler, input.uv + vec2<f32>(-step.x, 0.0)).rgb +
            textureSample(scene_tex, scene_sampler, input.uv + vec2<f32>(0.0,  step.y)).rgb +
            textureSample(scene_tex, scene_sampler, input.uv + vec2<f32>(0.0, -step.y)).rgb
        ) * 0.25;
        colour += (scene.rgb - neighbours) * uniforms.bloom.w;
    }

    colour *= exp2(uniforms.display.x);
    colour = apply_tone_mapping(max(colour, vec3<f32>(0.0)));

    if (uniforms.effects.x > 0.5) {
        let centred = input.uv * 2.0 - 1.0;
        let radius = dot(centred, centred);
        let vignette = 1.0 - smoothstep(0.25, 1.35, radius) * uniforms.effects.y;
        colour *= vignette;
    }
    return vec4<f32>(colour, 1.0);
}
