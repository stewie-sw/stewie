shader_type spatial;
// STEWIE viz2 Phase E (E2) — the SIGNED before/after difference drape shader (plan v4 §3 Phase E).
//
// A toggleable falsecolor overlay for the live moving-window mesh: it displaces vertices from the
// SAME live height texture as viz2_window.gdshader (so the drape sits exactly on the carved geometry),
// but the fragment stage recolors by a DIVERGING colormap of diff = h_now - h_virgin (streamed as the
// runtime's "diff" patch field): CUT (negative) reads cool/blue, BERM (positive) reads warm/orange,
// undisturbed (~0) reads neutral. viz2_terrain_window.gd swaps this material in for the normal window
// shader when the diff drape is toggled on; the frozen terrain.gd/terrain.gdshader seams are untouched.
//
// The magnitude scale is diff_range_m (metres at full saturation); the drape is partly EMISSIVE so the
// cut/berm colour stays legible on the shadow side under a grazing sun, while a height-gradient normal
// keeps the carved relief readable.

render_mode specular_disabled;

uniform sampler2D height_tex : filter_linear;   // R = absolute elevation (m) — the displaced geometry
uniform sampler2D diff_tex : filter_linear;     // R = signed diff h_now - h_virgin (m)

uniform float lod_step_m = 0.05;                // world metres per texel (= fine_cell_m)
uniform float window_lift_m = 0.03;             // coplanar-overdraw z-bias vs the far context plane
uniform float diff_range_m = 0.15;              // |diff| at full colour saturation
uniform float emission_gain = 0.55;             // how much the falsecolor self-illuminates (shadow legibility)
uniform float neutral_band_m = 0.005;           // |diff| below this reads as undisturbed (no colour)

// Diverging endpoints (perceptually cool -> neutral -> warm).
uniform vec3 cut_color : source_color = vec3(0.13, 0.40, 0.95);    // negative: excavated / below virgin
uniform vec3 neutral_color : source_color = vec3(0.62, 0.62, 0.60); // ~0: undisturbed
uniform vec3 berm_color : source_color = vec3(0.98, 0.48, 0.12);   // positive: spoil / above virgin

varying float vdiff;

void vertex() {
	// Displace from the live height texture — identical to viz2_window.gdshader, so the drape and the
	// lit window register cell-for-cell and toggling never shifts the surface.
	float h = texture(height_tex, UV).r;
	VERTEX.y += h + window_lift_m;
	vec2 ts = 1.0 / vec2(textureSize(height_tex, 0));
	float hL = texture(height_tex, UV - vec2(ts.x, 0.0)).r;
	float hR = texture(height_tex, UV + vec2(ts.x, 0.0)).r;
	float hD = texture(height_tex, UV - vec2(0.0, ts.y)).r;
	float hU = texture(height_tex, UV + vec2(0.0, ts.y)).r;
	NORMAL = normalize(vec3(hL - hR, 2.0 * lod_step_m, hD - hU));
	vdiff = texture(diff_tex, UV).r;
}

void fragment() {
	float d = vdiff;
	vec3 col;
	if (abs(d) <= neutral_band_m) {
		col = neutral_color;
	} else {
		float t = clamp(d / max(diff_range_m, 1e-4), -1.0, 1.0);   // -1 (deep cut) .. +1 (high berm)
		col = (t < 0.0) ? mix(neutral_color, cut_color, -t)
		                : mix(neutral_color, berm_color, t);
	}
	ALBEDO = col;
	EMISSION = col * emission_gain;   // keep the cut/berm colour legible in shadow
	ROUGHNESS = 0.98;
	METALLIC = 0.0;
}
