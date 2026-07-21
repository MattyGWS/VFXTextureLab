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

fn burst_coordinates(uv: vec2<f32>, resolution: vec2<f32>) -> vec2<f32> {
    let tile = max(params.p4.yz, vec2<f32>(0.0001));
    let centre = vec2<f32>(params.p2.w, params.p3.x);
    var local = fract(uv * tile - centre + vec2<f32>(0.5)) - vec2<f32>(0.5);
    if (params.p4.w >= 0.5) {
        let aspect = (resolution.x / max(resolution.y, 1.0)) * (tile.y / max(tile.x, 0.000001));
        local.x *= aspect;
    }
    let angle = params.p4.x * PI / 180.0;
    let c = cos(angle);
    let s = sin(angle);
    let rotated = vec2<f32>(local.x * c + local.y * s, -local.x * s + local.y * c);
    let scale = max(params.p3.w, 0.0001);
    let half_size = max(params.p3.yz * scale * 0.5, vec2<f32>(0.0001));
    return rotated / half_size;
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let resolution = vec2<f32>(f32(width), f32(height));
    let uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / resolution;
    let p = burst_coordinates(uv, resolution);
    let sides = max(i32(round(params.p1.x)), 3);
    let sector = TAU / f32(sides);
    let radius = length(p);
    var angle = atan2(p.y, p.x) + radius * (params.p5.y * PI / 180.0);
    angle = ((angle + PI) - floor((angle + PI) / TAU) * TAU) - PI;
    let local_angle = ((angle + sector * 0.5) - floor((angle + sector * 0.5) / sector) * sector) - sector * 0.5;
    let explode = max(params.p1.z, 0.0);
    let inner_radius = clamp(params.p2.x, 0.0, 0.95);
    let gap = clamp(params.p1.w, 0.0, 0.98);
    let r = radius - explode;
    let angular_limit = sector * 0.5 * (1.0 - gap);
    let angular_metric = 1.0 - abs(local_angle) / max(angular_limit, 0.00001);
    let radial_metric = min((r - inner_radius) / max(1.0 - inner_radius, 0.00001), 1.0 - r);
    let metric = min(angular_metric, radial_metric);
    var mask = 0.0;
    if (params.p5.x <= 0.0) {
        mask = select(0.0, 1.0, metric >= 0.0);
    } else {
        mask = clamp(metric / max(params.p5.x, 0.00001) + 0.5, 0.0, 1.0);
    }
    var value = mask;
    if (params.p1.y >= 0.5 && params.p1.y < 1.5) {
        let gradient = clamp((1.0 - r) / max(1.0 - inner_radius, 0.00001), 0.0, 1.0);
        value = mask * gradient;
    } else if (params.p1.y >= 1.5) {
        let gradient = clamp(1.0 - abs(local_angle) / max(sector * 0.5, 0.00001), 0.0, 1.0);
        value = mask * gradient;
    }
    if (params.p2.y >= 0.5) {
        let slice_index = i32(floor((angle + PI) / sector));
        if ((slice_index % 2) != 0) { value *= params.p2.z; }
    }
    if (params.p5.z >= 0.5) { value = 1.0 - value; }
    value = clamp(value, 0.0, 1.0);
    textureStore(output_tex, vec2<i32>(gid.xy), vec4<f32>(value, value, value, 1.0));
}
