struct Uniforms {
    view_proj: mat4x4<f32>,
    model: mat4x4<f32>,
    light_view_proj: mat4x4<f32>,
    camera_position: vec4<f32>,
    light_direction: vec4<f32>,
    material0: vec4<f32>,
    material1: vec4<f32>,
    environment: vec4<f32>,
    texture_info: vec4<f32>,
    flags: vec4<f32>,
    flags2: vec4<f32>,
    display: vec4<f32>,
    render: vec4<f32>,
    uv_settings: vec4<f32>,
};

@group(0) @binding(0) var<uniform> uniforms: Uniforms;
@group(0) @binding(1) var albedo_tex: texture_2d<f32>;
@group(0) @binding(2) var emissive_tex: texture_2d<f32>;
@group(0) @binding(3) var normal_tex: texture_2d<f32>;
@group(0) @binding(4) var height_tex: texture_2d<f32>;
@group(0) @binding(5) var ao_tex: texture_2d<f32>;
@group(0) @binding(6) var metallic_tex: texture_2d<f32>;
@group(0) @binding(7) var roughness_tex: texture_2d<f32>;
@group(0) @binding(8) var specular_tex: texture_2d<f32>;
@group(0) @binding(9) var opacity_tex: texture_2d<f32>;
@group(0) @binding(10) var material_sampler: sampler;
@group(0) @binding(11) var environment_tex: texture_2d<f32>;
@group(0) @binding(12) var environment_sampler: sampler;
@group(0) @binding(13) var shadow_tex: texture_depth_2d;
@group(0) @binding(14) var shadow_sampler: sampler_comparison;

struct VertexInput {
    @location(0) position: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) uv: vec2<f32>,
    @builtin(instance_index) instance_index: u32,
};

struct VertexOutput {
    @builtin(position) clip_position: vec4<f32>,
    @location(0) world_position: vec3<f32>,
    @location(1) world_normal: vec3<f32>,
    @location(2) uv: vec2<f32>,
    @location(3) shadow_position: vec4<f32>,
    @location(4) tangent_uv: vec2<f32>,
};

struct ShadowOutput {
    @builtin(position) clip_position: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

struct WireframeOutput {
    @builtin(position) clip_position: vec4<f32>,
};

struct PivotInput {
    @location(0) position: vec3<f32>,
    @location(1) color: vec3<f32>,
};

struct PivotOutput {
    @builtin(position) clip_position: vec4<f32>,
    @location(0) color: vec3<f32>,
};

fn material_uv(uv: vec2<f32>) -> vec2<f32> {
    var sampled = uv;
    if (uniforms.uv_settings.y > 0.5) {
        sampled.y = 1.0 - sampled.y;
    }
    return sampled * max(uniforms.uv_settings.x, 0.001);
}

fn tangent_uv(uv: vec2<f32>) -> vec2<f32> {
    return uv * max(uniforms.uv_settings.x, 0.001);
}

fn sampled_height(uv: vec2<f32>) -> f32 {
    var value = textureSampleLevel(height_tex, material_sampler, uv, 0.0).r;
    if (uniforms.material0.w > 0.5) {
        value = 1.0 - value;
    }
    return value;
}

fn displaced_world(input: VertexInput) -> vec4<f32> {
    var position = input.position;
    let normal = normalize(input.normal);
    if (uniforms.flags2.x > 0.5) {
        let height_value = sampled_height(material_uv(input.uv));
        position += normal * ((height_value - uniforms.material0.y) * uniforms.material0.x);
    }
    var world = uniforms.model * vec4<f32>(position, 1.0);
    let tile_count = i32(round(uniforms.environment.w));
    if (tile_count == 3 && uniforms.flags2.w > 0.5) {
        let ix = i32(input.instance_index % 3u) - 1;
        let iz = i32(input.instance_index / 3u) - 1;
        world.x += f32(ix) * 2.0;
        world.z += f32(iz) * 2.0;
    }
    return world;
}

@vertex
fn vs_main(input: VertexInput) -> VertexOutput {
    let world = displaced_world(input);
    var output: VertexOutput;
    output.clip_position = uniforms.view_proj * world;
    output.world_position = world.xyz;
    output.world_normal = normalize((uniforms.model * vec4<f32>(normalize(input.normal), 0.0)).xyz);
    output.uv = material_uv(input.uv);
    output.shadow_position = uniforms.light_view_proj * world;
    output.tangent_uv = tangent_uv(input.uv);
    return output;
}

@vertex
fn vs_wireframe(input: VertexInput) -> WireframeOutput {
    let world = displaced_world(input);
    var output: WireframeOutput;
    // Use exactly the same projected depth as the shaded pass. The wireframe
    // pipeline uses a less-equal depth comparison, so visible coincident edges
    // pass without pulling hidden back-side edges through the front surface.
    output.clip_position = uniforms.view_proj * world;
    return output;
}

@fragment
fn fs_wireframe() -> @location(0) vec4<f32> {
    return vec4<f32>(0.018, 0.021, 0.026, 0.72);
}

@vertex
fn vs_pivot(input: PivotInput) -> PivotOutput {
    var output: PivotOutput;
    output.clip_position = uniforms.view_proj * vec4<f32>(input.position, 1.0);
    output.color = input.color;
    return output;
}

@fragment
fn fs_pivot(input: PivotOutput) -> @location(0) vec4<f32> {
    return vec4<f32>(input.color, 0.96);
}

@vertex
fn vs_shadow(input: VertexInput) -> ShadowOutput {
    let world = displaced_world(input);
    var output: ShadowOutput;
    output.clip_position = uniforms.light_view_proj * world;
    output.uv = material_uv(input.uv);
    return output;
}

@fragment
fn fs_shadow(input: ShadowOutput) {
    let surface_mode = i32(round(uniforms.material1.w));
    if (surface_mode == 0) {
        return;
    }
    let alpha = textureSample(albedo_tex, material_sampler, input.uv).a;
    let opacity = clamp(textureSample(opacity_tex, material_sampler, input.uv).r * alpha, 0.0, 1.0);
    let threshold = select(0.08, uniforms.material1.y, surface_mode == 1);
    if (opacity < threshold) {
        discard;
    }
}

fn derivative_tangent_basis(position: vec3<f32>, uv: vec2<f32>, normal: vec3<f32>) -> mat3x3<f32> {
    let dp1 = dpdx(position);
    let dp2 = dpdy(position);
    let duv1 = dpdx(uv);
    let duv2 = dpdy(uv);
    let determinant = duv1.x * duv2.y - duv1.y * duv2.x;
    if (abs(determinant) < 1.0e-8) {
        let helper = select(vec3<f32>(0.0, 1.0, 0.0), vec3<f32>(1.0, 0.0, 0.0), abs(normal.y) > 0.96);
        let tangent = normalize(cross(helper, normal));
        return mat3x3<f32>(tangent, normalize(cross(normal, tangent)), normal);
    }
    // Dividing by the UV determinant is unnecessary after normalisation, but
    // retaining its sign is mandatory for mirrored UV charts. Without it the
    // tangent axes reverse on those islands and standards-compliant baked
    // normal maps appear to need an arbitrary red/green channel inversion.
    let uv_orientation = select(-1.0, 1.0, determinant >= 0.0);
    var tangent = normalize((dp1 * duv2.y - dp2 * duv1.y) * uv_orientation);
    let raw_bitangent = normalize((-dp1 * duv2.x + dp2 * duv1.x) * uv_orientation);
    tangent = normalize(tangent - normal * dot(normal, tangent));
    let handedness = select(-1.0, 1.0, dot(cross(normal, tangent), raw_bitangent) >= 0.0);
    let bitangent = normalize(cross(normal, tangent)) * handedness;
    return mat3x3<f32>(tangent, bitangent, normal);
}

fn blend_rnm(base: vec3<f32>, detail: vec3<f32>) -> vec3<f32> {
    let t = base + vec3<f32>(0.0, 0.0, 1.0);
    let u = detail * vec3<f32>(-1.0, -1.0, 1.0);
    return normalize(t * dot(t, u) / max(t.z, 1.0e-5) - u);
}

fn mesh_normal(input: VertexOutput, front_facing: bool) -> vec3<f32> {
    var normal = normalize(input.world_normal);
    if (!front_facing) {
        normal = -normal;
    }
    return normal;
}

fn tangent_map_sample(uv: vec2<f32>) -> vec3<f32> {
    var mapped = textureSample(normal_tex, material_sampler, uv).xyz * 2.0 - 1.0;
    mapped = vec3<f32>(
        mapped.x * uniforms.material0.z,
        mapped.y * uniforms.material1.z * uniforms.material0.z,
        mapped.z
    );
    return normalize(mapped);
}

fn surface_normal(input: VertexOutput, front_facing: bool) -> vec3<f32> {
    let base_normal = mesh_normal(input, front_facing);
    let tbn = derivative_tangent_basis(input.world_position, input.tangent_uv, base_normal);
    var tangent_normal = vec3<f32>(0.0, 0.0, 1.0);

    if (uniforms.texture_info.z > 0.5 && uniforms.flags2.x > 0.5) {
        let texel = uniforms.texture_info.xy;
        let left = sampled_height(input.uv - vec2<f32>(texel.x, 0.0));
        let right = sampled_height(input.uv + vec2<f32>(texel.x, 0.0));
        let down = sampled_height(input.uv - vec2<f32>(0.0, texel.y));
        let up = sampled_height(input.uv + vec2<f32>(0.0, texel.y));
        let uv_y_sign = select(1.0, -1.0, uniforms.uv_settings.y > 0.5);
        tangent_normal = normalize(vec3<f32>(
            (left - right) * uniforms.material0.z,
            (down - up) * uniforms.material0.z * uv_y_sign,
            1.0
        ));
    }

    if (uniforms.texture_info.w > 0.5) {
        tangent_normal = blend_rnm(tangent_normal, tangent_map_sample(input.uv));
    }
    return normalize(tbn * tangent_normal);
}

fn distribution_ggx(n: vec3<f32>, h: vec3<f32>, roughness: f32) -> f32 {
    let a = roughness * roughness;
    let a2 = a * a;
    let ndoth = max(dot(n, h), 0.0);
    let denominator = ndoth * ndoth * (a2 - 1.0) + 1.0;
    return a2 / max(3.14159265 * denominator * denominator, 0.00001);
}

fn geometry_schlick_ggx(ndotv: f32, roughness: f32) -> f32 {
    let r = roughness + 1.0;
    let k = (r * r) / 8.0;
    return ndotv / max(ndotv * (1.0 - k) + k, 0.00001);
}

fn geometry_smith(n: vec3<f32>, v: vec3<f32>, l: vec3<f32>, roughness: f32) -> f32 {
    return geometry_schlick_ggx(max(dot(n, v), 0.0), roughness) *
           geometry_schlick_ggx(max(dot(n, l), 0.0), roughness);
}

fn fresnel_schlick(cos_theta: f32, f0: vec3<f32>) -> vec3<f32> {
    return f0 + (vec3<f32>(1.0) - f0) * pow(clamp(1.0 - cos_theta, 0.0, 1.0), 5.0);
}

fn fresnel_schlick_roughness(cos_theta: f32, f0: vec3<f32>, roughness: f32) -> vec3<f32> {
    return f0 + (max(vec3<f32>(1.0 - roughness), f0) - f0) *
        pow(clamp(1.0 - cos_theta, 0.0, 1.0), 5.0);
}

fn specular_aa_roughness(normal: vec3<f32>, base_roughness: f32) -> f32 {
    // High-frequency height/normal detail can otherwise create bright,
    // crawling GGX highlights. Fold the local normal variance into roughness
    // so sub-pixel detail remains matte and stable rather than looking coated.
    let dx = dpdx(normal);
    let dy = dpdy(normal);
    let variance = 0.15 * (dot(dx, dx) + dot(dy, dy));
    let kernel_roughness2 = min(2.0 * variance, 0.25);
    return clamp(sqrt(base_roughness * base_roughness + kernel_roughness2), 0.045, 1.0);
}

fn environment_brdf(f0: vec3<f32>, roughness: f32, ndotv: f32) -> vec3<f32> {
    // Epic's compact split-sum approximation. The previous implementation
    // multiplied the environment directly by Schlick Fresnel, which made
    // rough dielectric surfaces approach a full white reflection at grazing
    // angles and produced the conspicuous glossy bands seen on terrain.
    let c0 = vec4<f32>(-1.0, -0.0275, -0.572, 0.022);
    let c1 = vec4<f32>(1.0, 0.0425, 1.04, -0.04);
    let r = roughness * c0 + c1;
    let a004 = min(r.x * r.x, exp2(-9.28 * ndotv)) * r.x + r.y;
    let ab = vec2<f32>(-1.04, 1.04) * a004 + r.zw;
    return max(f0 * ab.x + vec3<f32>(ab.y), vec3<f32>(0.0));
}

fn environment_uv(direction: vec3<f32>) -> vec2<f32> {
    let d = normalize(direction);
    let rotation = uniforms.display.w / 6.28318530718;
    let u = fract(atan2(d.x, d.z) / 6.28318530718 + 0.5 + rotation);
    let v = acos(clamp(d.y, -1.0, 1.0)) / 3.14159265359;
    return vec2<f32>(u, v);
}

fn sample_environment(direction: vec3<f32>, lod: f32) -> vec3<f32> {
    let radiance = textureSampleLevel(
        environment_tex,
        environment_sampler,
        environment_uv(direction),
        clamp(lod, 0.0, max(uniforms.render.x - 1.0, 0.0))
    ).rgb;
    // The bundled compact maps are inverse-tonemapped preview panoramas rather
    // than original production HDR files. A gentle lighting-only shoulder
    // keeps reconstructed peaks useful without allowing them to overwhelm the
    // material. The visible environment background remains untouched.
    return radiance / (vec3<f32>(1.0) + radiance / 16.0);
}

fn shadow_visibility(input: VertexOutput, normal: vec3<f32>, light: vec3<f32>) -> f32 {
    if (uniforms.render.y < 0.5) {
        return 1.0;
    }
    let projected = input.shadow_position.xyz / max(input.shadow_position.w, 1.0e-6);
    let uv = vec2<f32>(projected.x * 0.5 + 0.5, 0.5 - projected.y * 0.5);
    if (projected.z <= 0.0 || projected.z >= 1.0 || any(uv < vec2<f32>(0.0)) || any(uv > vec2<f32>(1.0))) {
        return 1.0;
    }
    let bias = max(0.00035 * (1.0 - dot(normal, light)), 0.00008);
    let texel = vec2<f32>(uniforms.render.w);
    var sum = 0.0;
    for (var y = -1; y <= 1; y = y + 1) {
        for (var x = -1; x <= 1; x = x + 1) {
            sum += textureSampleCompare(
                shadow_tex,
                shadow_sampler,
                uv + vec2<f32>(f32(x), f32(y)) * texel,
                projected.z - bias
            );
        }
    }
    let pcf = sum / 9.0;
    return mix(1.0, pcf, clamp(uniforms.render.z, 0.0, 1.0));
}

fn uv_checker(uv: vec2<f32>) -> vec3<f32> {
    let cell = vec2<i32>(floor(uv * 10.0));
    let odd = (cell.x + cell.y) & 1;
    let base = select(vec3<f32>(0.12), vec3<f32>(0.72), odd == 1);
    let axis_u = 1.0 - smoothstep(0.0, max(fwidth(uv.x) * 1.5, 0.0015), abs(uv.x - 0.5));
    let axis_v = 1.0 - smoothstep(0.0, max(fwidth(uv.y) * 1.5, 0.0015), abs(uv.y - 0.5));
    return mix(base, vec3<f32>(0.15, 0.55, 1.0), axis_u * 0.7) + vec3<f32>(0.45, 0.12, 0.08) * axis_v * 0.7;
}

fn uv_grid_amount(uv: vec2<f32>) -> f32 {
    let scaled = uv * 10.0;
    let distance_to_line = abs(fract(scaled - 0.5) - 0.5);
    let width = max(fwidth(scaled), vec2<f32>(0.0001));
    return 1.0 - min(min(distance_to_line.x / width.x, distance_to_line.y / width.y), 1.0);
}

@fragment
fn fs_main(input: VertexOutput, @builtin(front_facing) front_facing: bool) -> @location(0) vec4<f32> {
    let albedo_sample = textureSample(albedo_tex, material_sampler, input.uv);
    let emissive = textureSample(emissive_tex, material_sampler, input.uv).rgb * uniforms.material1.x;
    let ao = textureSample(ao_tex, material_sampler, input.uv).r;
    let metallic = clamp(textureSample(metallic_tex, material_sampler, input.uv).r, 0.0, 1.0);
    let authored_roughness = clamp(textureSample(roughness_tex, material_sampler, input.uv).r, 0.045, 1.0);
    let specular_level = clamp(textureSample(specular_tex, material_sampler, input.uv).r, 0.0, 1.0);
    let opacity = clamp(textureSample(opacity_tex, material_sampler, input.uv).r * albedo_sample.a, 0.0, 1.0);
    let surface_mode = i32(round(uniforms.material1.w));
    if (surface_mode == 1 && opacity < uniforms.material1.y) {
        discard;
    }

    let n = surface_normal(input, front_facing);
    let roughness = specular_aa_roughness(n, authored_roughness);
    let debug_mode = i32(round(uniforms.display.x));
    if (debug_mode == 1) {
        return vec4<f32>(albedo_sample.rgb, 1.0);
    }
    if (debug_mode == 2) {
        return vec4<f32>(n * 0.5 + 0.5, 1.0);
    }
    if (debug_mode == 3) {
        let value = sampled_height(input.uv);
        return vec4<f32>(vec3<f32>(value), 1.0);
    }
    if (debug_mode == 4) {
        return vec4<f32>(vec3<f32>(authored_roughness), 1.0);
    }
    if (debug_mode == 5) {
        return vec4<f32>(vec3<f32>(metallic), 1.0);
    }
    if (debug_mode == 6) {
        return vec4<f32>(vec3<f32>(ao), 1.0);
    }
    if (debug_mode == 7) {
        return vec4<f32>(emissive, 1.0);
    }
    if (debug_mode == 8) {
        return vec4<f32>(vec3<f32>(opacity), 1.0);
    }
    if (debug_mode == 9) {
        return vec4<f32>(uv_checker(input.uv), 1.0);
    }
    if (debug_mode == 10) {
        return vec4<f32>(mesh_normal(input, front_facing) * 0.5 + 0.5, 1.0);
    }
    if (debug_mode == 11) {
        return vec4<f32>(tangent_map_sample(input.uv) * 0.5 + 0.5, 1.0);
    }

    let v = normalize(uniforms.camera_position.xyz - input.world_position);
    let l = normalize(-uniforms.light_direction.xyz);
    let h = normalize(v + l);
    let ndotl = max(dot(n, l), 0.0);
    let ndotv = max(dot(n, v), 0.0);
    // A conventional dielectric Specular Level of 0.5 represents roughly
    // four-percent reflectance (F0), not the nine percent used previously.
    let base_reflectance = vec3<f32>(0.08 * specular_level);
    let f0 = mix(base_reflectance, albedo_sample.rgb, metallic);
    let f = fresnel_schlick(max(dot(h, v), 0.0), f0);
    let d = distribution_ggx(n, h, roughness);
    let g = geometry_smith(n, v, l, roughness);
    let specular = (d * g * f) / max(4.0 * ndotv * ndotl, 0.0001);
    let kd = (vec3<f32>(1.0) - f) * (1.0 - metallic);
    let diffuse = kd * albedo_sample.rgb / 3.14159265;
    let visibility = shadow_visibility(input, n, l);
    let direct = (diffuse + specular) * ndotl * uniforms.environment.y * visibility;

    let max_lod = max(uniforms.render.x - 1.0, 0.0);
    let diffuse_lod = max(max_lod - 2.0, 0.0);
    let diffuse_environment = sample_environment(n, diffuse_lod);
    let reflection = reflect(-v, n);
    let specular_environment = sample_environment(reflection, roughness * max_lod);
    let ambient_f = fresnel_schlick_roughness(ndotv, f0, roughness);
    let ambient_kd = (vec3<f32>(1.0) - ambient_f) * (1.0 - metallic);
    let diffuse_ibl = ambient_kd * albedo_sample.rgb * diffuse_environment;
    let specular_ibl = specular_environment * environment_brdf(f0, roughness, ndotv);
    let ambient = (diffuse_ibl + specular_ibl) * uniforms.environment.x * ao;

    var colour = direct + ambient + emissive;
    if (uniforms.display.z > 0.5) {
        colour = albedo_sample.rgb + emissive;
    }
    if (surface_mode == 3) {
        colour *= opacity;
    }

    if (uniforms.flags2.z > 0.5 && uniforms.flags2.w > 0.5) {
        let scale = 8.0;
        let coord = abs(fract(input.world_position.xz * scale - 0.5) - 0.5) /
            max(fwidth(input.world_position.xz * scale), vec2<f32>(0.0001));
        let line = 1.0 - min(min(coord.x, coord.y), 1.0);
        colour = mix(colour, colour * 0.45, line * 0.32);
    }
    if (uniforms.display.y > 0.5) {
        colour = mix(colour, vec3<f32>(0.08, 0.32, 0.72), uv_grid_amount(input.uv) * 0.48);
    }

    let transparent_surface = surface_mode >= 2;
    return vec4<f32>(max(colour, vec3<f32>(0.0)), select(1.0, opacity, transparent_surface));
}
