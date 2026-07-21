struct Params {
    p0: vec4<f32>,
    p1: vec4<f32>,
    p2: vec4<f32>,
    p3: vec4<f32>,
};

@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var sheet_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

fn load_source(coord: vec2<i32>, scalar_source: bool) -> vec4<f32> {
    let value = textureLoad(sheet_tex, coord, 0);
    if (scalar_source) {
        return vec4<f32>(value.xxx, 1.0);
    }
    return value;
}

fn bilinear_cell_sample(
    source_pos: vec2<f32>,
    cell_min: vec2<i32>,
    cell_max: vec2<i32>,
    scalar_source: bool,
) -> vec4<f32> {
    let base = vec2<i32>(floor(source_pos));
    let next = min(base + vec2<i32>(1, 1), cell_max);
    let p00 = clamp(base, cell_min, cell_max);
    let p10 = vec2<i32>(next.x, p00.y);
    let p01 = vec2<i32>(p00.x, next.y);
    let p11 = next;
    let fraction = fract(source_pos);
    let top = mix(load_source(p00, scalar_source), load_source(p10, scalar_source), fraction.x);
    let bottom = mix(load_source(p01, scalar_source), load_source(p11, scalar_source), fraction.x);
    return mix(top, bottom, fraction.y);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) {
        return;
    }

    let columns = max(i32(round(params.p1.x)), 1);
    let rows = max(i32(round(params.p1.y)), 1);
    let frame_count = max(i32(round(params.p1.z)), 1);
    let relative_index = clamp(i32(round(params.p1.w)), 0, frame_count - 1);

    let capacity = max(columns * rows, 1);
    let start_frame = clamp(i32(round(params.p2.x)), 0, capacity - 1);
    let atlas_index = clamp(start_frame + relative_index, 0, capacity - 1);
    let vertical_order = params.p2.y >= 0.5;
    var column: i32 = 0;
    var row: i32 = 0;
    if (vertical_order) {
        column = atlas_index / rows;
        row = atlas_index % rows;
    } else {
        row = atlas_index / columns;
        column = atlas_index % columns;
    }

    let source_size_u = textureDimensions(sheet_tex);
    let source_size = vec2<f32>(source_size_u);
    let padding = max(params.p3.x, 0.0);
    let cell_size = max(
        (source_size - vec2<f32>(f32(columns - 1), f32(rows - 1)) * padding)
            / vec2<f32>(f32(columns), f32(rows)),
        vec2<f32>(1.0, 1.0),
    );
    let cell_origin = vec2<f32>(f32(column), f32(row)) * (cell_size + vec2<f32>(padding));
    let uv = (vec2<f32>(gid.xy) + vec2<f32>(0.5)) / vec2<f32>(f32(width), f32(height));
    let source_pos = cell_origin + uv * max(cell_size - vec2<f32>(1.0), vec2<f32>(0.0));
    let cell_min = vec2<i32>(floor(cell_origin));
    let cell_max = min(
        vec2<i32>(ceil(cell_origin + cell_size - vec2<f32>(1.0))),
        vec2<i32>(i32(source_size_u.x), i32(source_size_u.y)) - vec2<i32>(1, 1),
    );
    let output_value = bilinear_cell_sample(source_pos, cell_min, cell_max, params.p3.z >= 0.5);
    textureStore(output_tex, vec2<i32>(gid.xy), output_value);
}
