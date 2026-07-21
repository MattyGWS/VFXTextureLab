struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var foreground_tex: texture_2d<f32>;
@group(0) @binding(2) var background_tex: texture_2d<f32>;
@group(0) @binding(3) var opacity_mask: texture_2d<f32>;
@group(0) @binding(4) var output_tex: texture_storage_2d<rgba32float, write>;

fn linear_to_srgb_channel(value: f32) -> f32 {
    let v = clamp(value, 0.0, 1.0);
    return select(1.055 * pow(v, 1.0 / 2.4) - 0.055, 12.92 * v, v <= 0.0031308);
}

fn linear_to_srgb(value: vec3<f32>) -> vec3<f32> {
    return vec3<f32>(
        linear_to_srgb_channel(value.r),
        linear_to_srgb_channel(value.g),
        linear_to_srgb_channel(value.b)
    );
}

fn srgb_to_linear_channel(value: f32) -> f32 {
    let v = clamp(value, 0.0, 1.0);
    return select(pow((v + 0.055) / 1.055, 2.4), v / 12.92, v <= 0.04045);
}

fn srgb_to_linear(value: vec3<f32>) -> vec3<f32> {
    return vec3<f32>(
        srgb_to_linear_channel(value.r),
        srgb_to_linear_channel(value.g),
        srgb_to_linear_channel(value.b)
    );
}

fn soft_light_d(v: vec3<f32>) -> vec3<f32> {
    let polynomial = ((vec3<f32>(16.0) * v - vec3<f32>(12.0)) * v + vec3<f32>(4.0)) * v;
    return select(sqrt(max(v, vec3<f32>(0.0))), polynomial, v <= vec3<f32>(0.25));
}

fn blend_rgb(background: vec3<f32>, foreground: vec3<f32>, mode: u32) -> vec3<f32> {
    let b = clamp(background, vec3<f32>(0.0), vec3<f32>(1.0));
    let f = clamp(foreground, vec3<f32>(0.0), vec3<f32>(1.0));
    let eps = vec3<f32>(0.000001);

    if (mode == 0u) { // Replace / Copy
        return f;
    }
    if (mode == 1u) { // Add / Linear Dodge
        return clamp(b + f, vec3<f32>(0.0), vec3<f32>(1.0));
    }
    if (mode == 2u) { // Subtract
        return clamp(b - f, vec3<f32>(0.0), vec3<f32>(1.0));
    }
    if (mode == 3u) { // Multiply
        return b * f;
    }
    if (mode == 4u) { // Divide
        return clamp(b / max(f, eps), vec3<f32>(0.0), vec3<f32>(1.0));
    }
    if (mode == 5u) { // Add Sub / Linear Light
        return clamp(b + vec3<f32>(2.0) * f - vec3<f32>(1.0), vec3<f32>(0.0), vec3<f32>(1.0));
    }
    if (mode == 6u) { // Minimum
        return min(b, f);
    }
    if (mode == 7u) { // Maximum
        return max(b, f);
    }
    if (mode == 8u) { // Screen
        return vec3<f32>(1.0) - (vec3<f32>(1.0) - b) * (vec3<f32>(1.0) - f);
    }
    if (mode == 9u) { // Overlay (decision based on Background)
        let low = vec3<f32>(2.0) * b * f;
        let high = vec3<f32>(1.0) - vec3<f32>(2.0) * (vec3<f32>(1.0) - b) * (vec3<f32>(1.0) - f);
        return select(high, low, b <= vec3<f32>(0.5));
    }
    if (mode == 10u) { // Soft Light, W3C compositing formula
        let d = soft_light_d(b);
        let low = b - (vec3<f32>(1.0) - vec3<f32>(2.0) * f) * b * (vec3<f32>(1.0) - b);
        let high = b + (vec3<f32>(2.0) * f - vec3<f32>(1.0)) * (d - b);
        return select(high, low, f <= vec3<f32>(0.5));
    }
    if (mode == 11u) { // Hard Light (decision based on Foreground)
        let low = vec3<f32>(2.0) * b * f;
        let high = vec3<f32>(1.0) - vec3<f32>(2.0) * (vec3<f32>(1.0) - b) * (vec3<f32>(1.0) - f);
        return select(high, low, f <= vec3<f32>(0.5));
    }
    if (mode == 12u) { // Difference
        return abs(b - f);
    }
    if (mode == 13u) { // Exclusion
        return b + f - vec3<f32>(2.0) * b * f;
    }
    if (mode == 14u) { // Colour Dodge
        let dodge = min(vec3<f32>(1.0), b / max(vec3<f32>(1.0) - f, eps));
        return select(dodge, vec3<f32>(1.0), f >= vec3<f32>(1.0) - eps);
    }
    if (mode == 15u) { // Colour Burn
        let burn = vec3<f32>(1.0) - min(vec3<f32>(1.0), (vec3<f32>(1.0) - b) / max(f, eps));
        return select(burn, vec3<f32>(0.0), f <= eps);
    }
    return f;
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }

    let coord = vec2<i32>(gid.xy);
    var foreground = textureLoad(foreground_tex, coord, 0);
    var background = textureLoad(background_tex, coord, 0);
    if (params.p1.z >= 0.5) { foreground = vec4<f32>(foreground.r, foreground.r, foreground.r, 1.0); }
    if (params.p1.w >= 0.5) { background = vec4<f32>(background.r, background.r, background.r, 1.0); }

    // Colour resources are stored in linear light. Familiar artistic blend
    // formulae operate on display/perceptual channel values, while greyscale
    // and vector/data resources retain their raw numeric values.
    let foreground_blend = select(foreground.rgb, linear_to_srgb(foreground.rgb), params.p2.x >= 0.5);
    let background_blend = select(background.rgb, linear_to_srgb(background.rgb), params.p2.y >= 0.5);

    let mode = u32(params.p1.x);
    let opacity = clamp(params.p1.y * textureLoad(opacity_mask, coord, 0).r, 0.0, 1.0);
    let mixed = clamp(blend_rgb(background_blend, foreground_blend, mode), vec3<f32>(0.0), vec3<f32>(1.0));

    var mixed_graph = mixed;
    var background_graph = background.rgb;
    if (params.p2.z >= 0.5) {
        mixed_graph = srgb_to_linear(mixed);
        if (params.p2.y < 0.5) {
            background_graph = srgb_to_linear(background.rgb);
        }
    }

    var result = vec4<f32>(mix(background_graph, mixed_graph, opacity), mix(background.a, foreground.a, opacity));
    result = clamp(result, vec4<f32>(0.0), vec4<f32>(1.0));
    textureStore(output_tex, coord, result);
}
