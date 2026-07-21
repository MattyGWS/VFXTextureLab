struct Params {
    p0: vec4<f32>,
    p1: vec4<f32>,
    p2: vec4<f32>,
    p3: vec4<f32>,
    p4: vec4<f32>,
    p5: vec4<f32>,
};

@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var output_tex: texture_storage_2d<rgba32float, write>;

const PI: f32 = 3.14159265358979323846;
const TAU: f32 = 6.28318530717958647692;

fn polygon_coordinates(uv: vec2<f32>, resolution: vec2<f32>) -> vec2<f32> {
    let tile = max(vec2<f32>(params.p3.w, params.p4.x), vec2<f32>(0.0001));
    let centre = params.p2.yz;
    var local = fract(uv * tile - centre + vec2<f32>(0.5)) - vec2<f32>(0.5);
    if (params.p4.y >= 0.5) {
        let aspect = (resolution.x / max(resolution.y, 1.0)) * (tile.y / max(tile.x, 0.000001));
        local.x *= aspect;
    }
    let angle = params.p2.w * PI / 180.0;
    let c = cos(angle);
    let s = sin(angle);
    let rotated = vec2<f32>(local.x * c + local.y * s, -local.x * s + local.y * c);
    let scale = max(params.p3.z, 0.0001);
    let half_size = max(params.p3.xy * scale * 0.5, vec2<f32>(0.0001));
    return rotated / half_size;
}

fn vertex(index: i32, count: i32, regular: bool, inner_radius: f32, alternating_offset: f32) -> vec2<f32> {
    let angle = TAU * f32(index) / f32(count) + PI * 0.5;
    var radius = 1.0;
    if (!regular && (index % 2) != 0) {
        radius = clamp(inner_radius + alternating_offset, 0.02, 1.0);
    }
    return vec2<f32>(cos(angle), sin(angle)) * radius;
}

fn signed_distance_polygon(p: vec2<f32>, sides: i32, inner_radius: f32, alternating_offset: f32) -> f32 {
    let regular = inner_radius >= 0.999;
    let count = select(sides * 2, sides, regular);
    var dist2 = 1.0e20;
    var inside = false;
    var i: i32 = 0;
    loop {
        if (i >= count) { break; }
        let previous = (i + count - 1) % count;
        let a = vertex(previous, count, regular, inner_radius, alternating_offset);
        let b = vertex(i, count, regular, inner_radius, alternating_offset);
        let edge = b - a;
        let denom = dot(edge, edge) + 0.000000000001;
        let projection = clamp(dot(p - a, edge) / denom, 0.0, 1.0);
        let nearest = a + projection * edge;
        let delta = p - nearest;
        dist2 = min(dist2, dot(delta, delta));
        let crossing = ((a.y > p.y) != (b.y > p.y)) &&
            (p.x < edge.x * (p.y - a.y) / (b.y - a.y + 0.000000000001) + a.x);
        if (crossing) { inside = !inside; }
        i += 1;
    }
    let distance = sqrt(dist2);
    return select(distance, -distance, inside);
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

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let resolution = vec2<f32>(f32(width), f32(height));
    let uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / resolution;
    var p = polygon_coordinates(uv, resolution);
    let sides = max(i32(round(params.p1.x)), 3);
    let twist = params.p5.x * PI / 180.0;
    if (abs(twist) > 0.000000001) {
        let radius = length(p);
        let angle = atan2(p.y, p.x) + radius * twist;
        p = vec2<f32>(cos(angle), sin(angle)) * radius;
    }
    let distortion = params.p5.y;
    if (abs(distortion) > 0.000000001) {
        let angle = atan2(p.y, p.x);
        var radius = length(p);
        radius /= max(1.0 + distortion * cos(angle * f32(sides)), 0.001);
        p = vec2<f32>(cos(angle), sin(angle)) * radius;
    }
    let signed_distance = signed_distance_polygon(p, sides, params.p1.y, params.p1.z) - params.p1.w;
    let metric = -signed_distance;
    var value = profile_from_metric(metric, params.p2.x, params.p4.z, params.p4.w);
    if (params.p5.z >= 0.5) { value = 1.0 - value; }
    value = clamp(value, 0.0, 1.0);
    textureStore(output_tex, vec2<i32>(gid.xy), vec4<f32>(value, value, value, 1.0));
}
