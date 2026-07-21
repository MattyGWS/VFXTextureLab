struct Params { p0: vec4<f32>, p1: vec4<f32>, p2: vec4<f32>, p3: vec4<f32>, };
@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var input_tex: texture_2d<f32>;
@group(0) @binding(2) var output_tex: texture_storage_2d<rgba32float, write>;

fn rgb_to_hsl(c: vec3<f32>) -> vec3<f32> {
    let mx = max(c.r, max(c.g, c.b));
    let mn = min(c.r, min(c.g, c.b));
    let d = mx - mn;
    let l = (mx + mn) * 0.5;
    var h = 0.0;
    var s = 0.0;
    if (d > 0.0000001) {
        s = d / max(1.0 - abs(2.0 * l - 1.0), 0.0000001);
        if (mx == c.r) {
            h = (c.g - c.b) / d;
            if (h < 0.0) { h = h + 6.0; }
        } else if (mx == c.g) {
            h = ((c.b - c.r) / d) + 2.0;
        } else {
            h = ((c.r - c.g) / d) + 4.0;
        }
        h = fract(h / 6.0);
        if (h < 0.0) { h = h + 1.0; }
    }
    return vec3<f32>(h, clamp(s, 0.0, 1.0), clamp(l, 0.0, 1.0));
}

fn hsl_to_rgb(hsl: vec3<f32>) -> vec3<f32> {
    let h = fract(hsl.x);
    let s = clamp(hsl.y, 0.0, 1.0);
    let l = clamp(hsl.z, 0.0, 1.0);
    let c = (1.0 - abs(2.0 * l - 1.0)) * s;
    let hp = h * 6.0;
    let hp_mod_2 = hp - 2.0 * floor(hp * 0.5);
    let x = c * (1.0 - abs(hp_mod_2 - 1.0));
    var rgb1 = vec3<f32>(0.0);
    if (hp < 1.0) { rgb1 = vec3<f32>(c, x, 0.0); }
    else if (hp < 2.0) { rgb1 = vec3<f32>(x, c, 0.0); }
    else if (hp < 3.0) { rgb1 = vec3<f32>(0.0, c, x); }
    else if (hp < 4.0) { rgb1 = vec3<f32>(0.0, x, c); }
    else if (hp < 5.0) { rgb1 = vec3<f32>(x, 0.0, c); }
    else { rgb1 = vec3<f32>(c, 0.0, x); }
    return rgb1 + vec3<f32>(l - c * 0.5);
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let width = u32(params.p0.x);
    let height = u32(params.p0.y);
    if (gid.x >= width || gid.y >= height) { return; }
    let coord = vec2<i32>(gid.xy);
    let source = textureLoad(input_tex, coord, 0);
    var hsl = rgb_to_hsl(clamp(source.rgb, vec3<f32>(0.0), vec3<f32>(1.0)));
    let mode = i32(params.p1.x + 0.5);
    let amount = params.p1.y;
    if (mode == 0) {
        hsl.x = fract(hsl.x + amount / 360.0);
        if (hsl.x < 0.0) { hsl.x = hsl.x + 1.0; }
    } else if (mode == 1) {
        hsl.y = clamp(hsl.y * amount, 0.0, 1.0);
    } else {
        hsl.z = clamp(hsl.z + amount, 0.0, 1.0);
    }
    textureStore(output_tex, coord, vec4<f32>(hsl_to_rgb(hsl), source.a));
}
