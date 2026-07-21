struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var current_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

const PI: f32 = 3.14159265358979323846;
const TAU: f32 = 6.28318530717958647692;

fn wrap_coord(value: i32, extent: i32) -> i32 {
    let wrapped = f32(value) - floor(f32(value) / f32(extent)) * f32(extent);
    return i32(wrapped);
}

fn sample_value(coord: vec2<i32>, dimensions: vec2<i32>, wrap: bool, erosion: bool) -> f32 {
    if (wrap) {
        let wrapped = vec2<i32>(wrap_coord(coord.x, dimensions.x), wrap_coord(coord.y, dimensions.y));
        return textureLoad(current_tex, wrapped, 0).r;
    }
    if (coord.x < 0 || coord.y < 0 || coord.x >= dimensions.x || coord.y >= dimensions.y) {
        return select(0.0, 1.0, erosion);
    }
    return textureLoad(current_tex, coord, 0).r;
}

fn direction_offset(degrees: f32) -> vec2<i32> {
    let radians = degrees * 0.017453292519943295;
    var offset = vec2<i32>(i32(round(cos(radians))), i32(round(-sin(radians))));
    if (offset.x == 0 && offset.y == 0) { offset.x = 1; }
    return offset;
}

fn combine(current: f32, candidate: f32, erosion: bool) -> f32 {
    return select(max(current, candidate), min(current, candidate), erosion);
}

fn inside_disk(offset: vec2<i32>, radius: i32, antialiased: bool) -> bool {
    let tolerance = select(0.05, 0.5, antialiased);
    let limit = f32(radius) + tolerance;
    let point = vec2<f32>(offset);
    return dot(point, point) <= limit * limit;
}

fn inside_polygon(
    offset: vec2<i32>,
    radius: i32,
    vertices: i32,
    direction: f32,
    antialiased: bool,
) -> bool {
    let tolerance = select(0.05, 0.5, antialiased);
    let count = clamp(vertices, 3, 16);
    let apothem = f32(radius) * cos(PI / f32(count)) + tolerance;
    let point = vec2<f32>(offset);
    let base_angle = direction * 0.017453292519943295;
    for (var index: i32 = 0; index < 16; index = index + 1) {
        if (index < count) {
            let angle = base_angle + (f32(index) + 0.5) * TAU / f32(count);
            let normal = vec2<f32>(cos(angle), -sin(angle));
            if (dot(point, normal) > apothem) {
                return false;
            }
        }
    }
    return true;
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = i32(params.p0.x);
    let height = i32(params.p0.y);
    if (i32(gid.x) >= width || i32(gid.y) >= height) { return; }
    let coord = vec2<i32>(gid.xy);
    let dimensions = vec2<i32>(width, height);
    let erosion = i32(params.p1.x + 0.5) == 1;
    let shape = i32(params.p1.y + 0.5);
    let vertices = clamp(i32(params.p1.z + 0.5), 3, 16);
    let radius = clamp(i32(params.p1.w + 0.5), 1, 4);
    let direction = params.p2.x;
    let corner_angle = params.p2.y;
    let antialiased = params.p2.z >= 0.5;
    let wrap = params.p2.w >= 0.5;

    var value = sample_value(coord, dimensions, wrap, erosion);

    // Disk and Polygon use real filled area kernels. The previous 3x3
    // neighbourhood accumulated into a square regardless of vertex count.
    if (shape == 0 || shape == 1) {
        for (var oy: i32 = -4; oy <= 4; oy = oy + 1) {
            for (var ox: i32 = -4; ox <= 4; ox = ox + 1) {
                if (abs(ox) <= radius && abs(oy) <= radius) {
                    let offset = vec2<i32>(ox, oy);
                    let accepted = select(
                        inside_disk(offset, radius, antialiased),
                        inside_polygon(offset, radius, vertices, direction, antialiased),
                        shape == 1,
                    );
                    if (accepted) {
                        value = combine(value, sample_value(coord + offset, dimensions, wrap, erosion), erosion);
                    }
                }
            }
        }
    } else if (shape == 3) {
        let ray = direction_offset(direction);
        value = combine(value, sample_value(coord + ray, dimensions, wrap, erosion), erosion);
        value = combine(value, sample_value(coord - ray, dimensions, wrap, erosion), erosion);
    } else if (shape == 4) {
        let half_angle = corner_angle * 0.5;
        let first = direction_offset(direction - half_angle);
        let second = direction_offset(direction + half_angle);
        value = combine(value, sample_value(coord + first, dimensions, wrap, erosion), erosion);
        value = combine(value, sample_value(coord + second, dimensions, wrap, erosion), erosion);
        let combined = clamp(first + second, vec2<i32>(-1), vec2<i32>(1));
        if (combined.x != 0 || combined.y != 0) {
            value = combine(value, sample_value(coord + combined, dimensions, wrap, erosion), erosion);
        }
    } else { // Asterisk
        for (var index: i32 = 0; index < 16; index = index + 1) {
            if (index < vertices) {
                let ray = direction_offset(direction + f32(index) * 360.0 / f32(vertices));
                value = combine(value, sample_value(coord + ray, dimensions, wrap, erosion), erosion);
            }
        }
    }

    value = clamp(value, 0.0, 1.0);
    textureStore(output_tex, coord, vec4<f32>(value, value, value, 1.0));
}
