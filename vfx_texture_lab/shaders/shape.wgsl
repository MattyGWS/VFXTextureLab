struct Params {
    p0: vec4<f32>,
    p1: vec4<f32>,
    p2: vec4<f32>,
    p3: vec4<f32>,
    p4: vec4<f32>,
    p5: vec4<f32>,
    p6: vec4<f32>,
};

@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var output_tex: texture_storage_2d<rgba32float, write>;

const PI: f32 = 3.14159265358979323846;

fn shape_coordinates(uv: vec2<f32>, resolution: vec2<f32>) -> vec2<f32> {
    let tile = max(params.p3.xy, vec2<f32>(0.0001));
    let centre = params.p1.zw;
    var local = fract(uv * tile - centre + vec2<f32>(0.5)) - vec2<f32>(0.5);
    if (params.p3.z >= 0.5) {
        let aspect = (resolution.x / max(resolution.y, 1.0)) * (tile.y / max(tile.x, 0.000001));
        local.x *= aspect;
    }
    let angle = params.p2.w * PI / 180.0;
    let c = cos(angle);
    let s = sin(angle);
    let rotated = vec2<f32>(local.x * c + local.y * s, -local.x * s + local.y * c);
    let scale = max(params.p2.z, 0.0001);
    let half_size = max(params.p2.xy * scale * 0.5, vec2<f32>(0.0001));
    return rotated / half_size;
}

fn profile_from_metric(metric: f32, mode: f32, feather_value: f32, profile_width_value: f32) -> f32 {
    let profile_width = max(profile_width_value, 0.00001);
    if (feather_value <= 0.0) {
        let coverage = select(0.0, 1.0, metric >= 0.0);
        if (mode >= 0.5 && mode < 1.5) {
            return select(0.0, 1.0, abs(metric) <= profile_width);
        }
        if (mode >= 1.5 && mode < 2.5) {
            return clamp(metric / profile_width, 0.0, 1.0) * coverage;
        }
        if (mode >= 2.5) {
            let bevel = clamp(metric / profile_width, 0.0, 1.0);
            return (1.0 - (1.0 - bevel) * (1.0 - bevel)) * coverage;
        }
        return coverage;
    }

    let feather = max(feather_value, 0.00001);
    let coverage = clamp(metric / feather + 0.5, 0.0, 1.0);
    if (mode >= 0.5 && mode < 1.5) {
        return clamp((profile_width - abs(metric)) / feather + 0.5, 0.0, 1.0);
    }
    if (mode >= 1.5 && mode < 2.5) {
        return clamp(metric / profile_width, 0.0, 1.0) * coverage;
    }
    if (mode >= 2.5) {
        let bevel = clamp(metric / profile_width, 0.0, 1.0);
        return (1.0 - (1.0 - bevel) * (1.0 - bevel)) * coverage;
    }
    return coverage;
}

fn rounded_rectangle_metric(p: vec2<f32>, radius_value: f32) -> f32 {
    let radius = clamp(radius_value, 0.0, 0.95);
    let q = abs(p) - vec2<f32>(1.0 - radius);
    let outside = length(max(q, vec2<f32>(0.0)));
    let inside = min(max(q.x, q.y), 0.0);
    return -(outside + inside - radius);
}

fn cross_metric(p: vec2<f32>, thickness_value: f32) -> f32 {
    let bar = clamp(thickness_value, 0.05, 1.5);
    let vertical = min(1.0 - abs(p.y), bar - abs(p.x));
    let horizontal = min(1.0 - abs(p.x), bar - abs(p.y));
    return max(vertical, horizontal);
}

fn shape_value(p: vec2<f32>) -> f32 {
    let shape = params.p1.x;
    let fill_mode = params.p1.y;
    let feather = params.p3.w;
    let profile_width = params.p4.x;
    let radius = length(p);

    if (shape >= 10.5 && shape < 11.5) {
        return select(0.0, exp(-3.5 * radius * radius), radius <= 1.0);
    }
    if (shape >= 11.5 && shape < 12.5) {
        return select(0.0, exp(-8.0 * radius * radius), radius <= 1.0);
    }
    if (shape >= 12.5 && shape < 13.5) {
        return clamp(1.0 - max(abs(p.x), abs(p.y)), 0.0, 1.0);
    }
    if (shape >= 13.5 && shape < 14.5) {
        return clamp(1.0 - radius, 0.0, 1.0);
    }
    if (shape >= 14.5 && shape < 15.5) {
        return sqrt(clamp(1.0 - radius * radius, 0.0, 1.0));
    }
    if (shape >= 15.5 && shape < 16.5) {
        let frequency = max(params.p6.y, 0.1);
        let phase = params.p6.z * PI / 180.0;
        let balance = clamp(params.p6.w, 0.0, 1.0);
        let wave = 0.5 + 0.5 * sin((p.x + 1.0) * PI * frequency + phase);
        return clamp((wave - balance) / max(1.0 - balance, 0.00001), 0.0, 1.0);
    }
    if (shape >= 16.5) {
        return clamp((p.x + 1.0) * 0.5, 0.0, 1.0);
    }

    var metric = 1.0 - max(abs(p.x), abs(p.y));
    if (shape >= 0.5 && shape < 1.5) {
        metric = rounded_rectangle_metric(p, params.p4.z);
    } else if (shape >= 1.5 && shape < 2.5) {
        metric = 1.0 - radius;
    } else if (shape >= 2.5 && shape < 3.5) {
        let thickness = clamp(params.p4.w, 0.01, 0.99);
        metric = thickness - abs(radius - (1.0 - thickness));
    } else if (shape >= 3.5 && shape < 4.5) {
        let half_segment = 0.35 + clamp(params.p5.x, 0.0, 1.6) * 0.45;
        let qx = max(abs(p.x) - half_segment, 0.0);
        metric = 0.35 - length(vec2<f32>(qx, p.y));
    } else if (shape >= 4.5 && shape < 5.5) {
        metric = min(1.0 - p.y, p.y + 1.0 - 2.0 * abs(p.x));
    } else if (shape >= 5.5 && shape < 6.5) {
        metric = 1.0 - (abs(p.x) + abs(p.y));
    } else if (shape >= 6.5 && shape < 7.5) {
        let absolute = abs(p);
        metric = 1.0 - max(absolute.y, absolute.x * 0.8660254 + absolute.y * 0.5);
    } else if (shape >= 7.5 && shape < 8.5) {
        metric = cross_metric(p, params.p5.y);
    } else if (shape >= 8.5 && shape < 9.5) {
        let c = 0.70710678;
        let rotated = vec2<f32>(p.x * c + p.y * c, -p.x * c + p.y * c);
        metric = cross_metric(rotated, params.p5.y);
    } else if (shape >= 9.5 && shape < 10.5) {
        let outer = radius - 1.0;
        let cutout_offset = vec2<f32>(params.p5.w, params.p6.x);
        let inner = length(p - cutout_offset) - clamp(params.p5.z, 0.05, 1.5);
        metric = -max(outer, -inner);
    }
    return profile_from_metric(metric, fill_mode, feather, profile_width);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let resolution = vec2<f32>(f32(width), f32(height));
    let uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / resolution;
    let local = shape_coordinates(uv, resolution);
    var value = clamp(shape_value(local), 0.0, 1.0);
    if (params.p4.y >= 0.5) { value = 1.0 - value; }
    textureStore(output_tex, vec2<i32>(gid.xy), vec4<f32>(value, value, value, 1.0));
}
