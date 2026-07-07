shader_type spatial;
// P6 nadir DEPTH encoder (depth_nadir.gd). Unshaded: the output is a MEASUREMENT of the
// per-fragment depth (camera-to-surface distance) of the real displaced terrain geometry,
// not a lit appearance. For a nadir camera at cam_height looking straight down, the depth of
// a surface point at world elevation wy is exactly (cam_height - wy); it is encoded to a
// [0,1] grayscale over the declared [d_lo, d_hi] metric range and stored in the framebuffer.
// dart/observed_map.py inverts the sRGB store and this mapping to recover wy per pixel.
render_mode unshaded, cull_disabled;

uniform float cam_height;
uniform float d_lo;
uniform float d_hi;

varying float world_y;

void vertex() {
	world_y = (MODEL_MATRIX * vec4(VERTEX, 1.0)).y;
}

void fragment() {
	float depth = cam_height - world_y;                 // nadir camera-to-surface distance (m)
	float t = clamp((depth - d_lo) / max(d_hi - d_lo, 1e-6), 0.0, 1.0);
	ALBEDO = vec3(t);
}
