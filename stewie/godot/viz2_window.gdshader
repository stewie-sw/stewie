shader_type spatial;
// STEWIE viz2 Phase B3 — the LIVE moving-window terrain shader (plan v4 §2b.5, NB-2).
//
// A fine-scale copy of terrain_farfield.gdshader's MECHANISM: a single PlaneMesh whose
// vertices are displaced *in the vertex shader* by sampling a LIVE height texture. The
// difference from the far-field plane is scale — this texture is the WorkSite streaming
// window at fine resolution (5 cm / 2 cm cells), updated in place every physics generation
// via ImageTexture.update() from the runtime's patch manifests (viz2_terrain_window.gd).
//
// WHY a new mesh (NB-2, plan §0.1): the FROZEN active-zone mesh (terrain.gd / terrain.gdshader)
// CPU-bakes heights into ArrayMesh vertices, and its vertex() stage displaces NOTHING — so
// ImageTexture.update on a height texture under THAT mesh would render a static surface. This
// mesh displaces from the live texture in vertex(), so when the runtime carves a rut/trench the
// geometry actually moves. The frozen seams are untouched; this is a new, viz2-owned file.
//
// Fragment appearance + photometry mirror terrain_farfield.gdshader (which itself mirrors
// terrain.gdshader): the same Hapke / Lommel-Seeliger airless-regolith BRDF, the same state /
// disturbance TREAD-band look, so the live window reads as one surface with the far context.

render_mode specular_disabled;

// LIVE window fields (updated in place per generation from the manifest crops). height_tex holds
// ABSOLUTE elevation in metres (derive_height()) — the same convention the frozen loader bakes,
// so the window mesh and the far context register without a datum offset.
uniform sampler2D height_tex : filter_linear;          // R = elevation (m), one texel per fine cell
uniform sampler2D state_tex : filter_nearest;          // R = label/255 (0..4)
uniform sampler2D disturbance_tex : filter_linear;     // R = [0,1]

uniform vec3 base_albedo : source_color = vec3(0.45, 0.44, 0.43);
uniform float lod_step_m = 0.05;                       // world metres per texel (= fine_cell_m)
// A tiny upward bias so the fine window mesh wins the depth test over the coplanar far context
// plane it overdraws (a documented z-fight bias, NOT a terrain edit — the physics is unchanged).
uniform float window_lift_m = 0.03;

// Macro albedo mottle (mirror of terrain_farfield.gdshader).
uniform float macro_albedo_amp = 0.13;
uniform float macro_scale_m = 0.42;
// Fine granular ALBEDO speckle (world-anchored, mirror of terrain_farfield.gdshader).
uniform float grain_albedo_amp = 0.22;
uniform float speckle_size_m = 0.020;

// Photometry: Hapke BRDF (mirror of terrain_farfield.gdshader / terrain.gdshader).
uniform bool  hapke_enabled = true;
uniform float hapke_b  = 0.26;
uniform float hapke_c  = 0.08;
uniform float hapke_B0 = 1.0;
uniform float hapke_h  = 0.06;
uniform float hapke_gain = 1.4;

varying vec2 fuv;   // UV (0..1 across the window) carried to the fragment stage
varying float v_slope;                    // world-normal slope angle [rad], for the analysis overlay
uniform int analysis_mode = 0;            // 0 = normal shading, 1 = slope heatmap (path analysis)

// --- simplex noise (Ashima Arts / Stefan Gustavson "webgl-noise", MIT; mirror of terrain_farfield) ---
vec2 _sx_mod289(vec2 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec3 _sx_mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec3 _sx_permute(vec3 x) { return _sx_mod289(((x * 34.0) + 1.0) * x); }
float snoise(vec2 v) {
	const vec4 C = vec4(0.211324865405187, 0.366025403784439, -0.577350269189626, 0.024390243902439);
	vec2 i = floor(v + dot(v, C.yy));
	vec2 x0 = v - i + dot(i, C.xx);
	vec2 i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
	vec4 x12 = x0.xyxy + C.xxzz;
	x12.xy -= i1;
	i = _sx_mod289(i);
	vec3 p = _sx_permute(_sx_permute(i.y + vec3(0.0, i1.y, 1.0)) + i.x + vec3(0.0, i1.x, 1.0));
	vec3 m = max(0.5 - vec3(dot(x0, x0), dot(x12.xy, x12.xy), dot(x12.zw, x12.zw)), 0.0);
	m = m * m; m = m * m;
	vec3 x = 2.0 * fract(p * C.www) - 1.0;
	vec3 h = abs(x) - 0.5;
	vec3 ox = floor(x + 0.5);
	vec3 a0 = x - ox;
	m *= 1.79284291400159 - 0.85373472095314 * (a0 * a0 + h * h);
	vec3 g;
	g.x = a0.x * x0.x + h.x * x0.y;
	g.yz = a0.yz * x12.xz + h.yz * x12.yw;
	return 130.0 * dot(m, g);
}
float vnoise(vec2 p) { return snoise(p) * 0.5 + 0.5; }

float state_grain_factor(int lbl) {
	if (lbl == 1) return 0.20;
	if (lbl == 2) return 1.10;
	if (lbl == 3) return 1.15;
	if (lbl == 4) return 0.45;
	return 1.0;
}

float hg_phase(float cg, float b, float c) {
	float b2 = b * b;
	float back = (1.0 - b2) / pow(max(1.0 - 2.0 * b * cg + b2, 1e-4), 1.5);
	float fwd  = (1.0 - b2) / pow(max(1.0 + 2.0 * b * cg + b2, 1e-4), 1.5);
	return 0.5 * (1.0 + c) * back + 0.5 * (1.0 - c) * fwd;
}

void vertex() {
	fuv = UV;
	// Fine window: displace Y from the live height texture (the far-field mechanism at fine scale).
	// height_tex carries absolute elevation (m); window_lift_m is the coplanar-overdraw z-bias.
	float h = texture(height_tex, UV).r;
	VERTEX.y += h + window_lift_m;

	// Recompute the NORMAL from the height gradient (central differences), so a carved rut/trench
	// shades as real relief (a live edit changes the normal, hence the shading — the NB-2 proof).
	vec2 ts = 1.0 / vec2(textureSize(height_tex, 0));
	float hL = texture(height_tex, UV - vec2(ts.x, 0.0)).r;
	float hR = texture(height_tex, UV + vec2(ts.x, 0.0)).r;
	float hD = texture(height_tex, UV - vec2(0.0, ts.y)).r;
	float hU = texture(height_tex, UV + vec2(0.0, ts.y)).r;
	NORMAL = normalize(vec3(hL - hR, 2.0 * lod_step_m, hD - hU));
	v_slope = acos(clamp(NORMAL.y, -1.0, 1.0));   // 0 = flat, larger = steeper (for the slope overlay)
}

void fragment() {
	float span = float(textureSize(height_tex, 0).x) * lod_step_m;   // window side in metres
	vec2 mp = fuv * (span / max(macro_scale_m, 1e-3));
	float m = 0.62 * vnoise(mp) + 0.38 * vnoise(mp * 3.3 + vec2(7.1, 2.7));
	vec3 col = base_albedo * (1.0 + macro_albedo_amp * (m * 2.0 - 1.0));

	// State-driven TREAD look (mirror of terrain_farfield.gdshader §6): the rut reads as a
	// continuous band; disturbance darkens churned fines; the label tints the band. This is what
	// makes the driven track and the excavated swath visible where the live manifest patched them.
	float dist = clamp(texture(disturbance_tex, fuv).r, 0.0, 1.0);
	col *= (1.0 - 0.18 * dist);
	float rough = 0.97;
	int lbl = int(round(texture(state_tex, fuv).r * 255.0));
	float state_grain = state_grain_factor(lbl);
	if (lbl == 1) {            // TREAD: compacted rut -> darker, a touch smoother
		col *= 0.82;
		rough = 0.90;
	} else if (lbl == 2) {     // EXCAVATED: fresh firm sublayer -> brighter
		col *= 1.30;
		rough = 0.92;
	} else if (lbl == 3) {     // SPOIL: loose pile -> slightly darker, very rough
		col *= 0.90;
		rough = 0.98;
	} else if (lbl == 4) {     // COMPACTED_BERM: packed mound -> a touch brighter
		col *= 1.12;
		rough = 0.92;
	}

	{
		vec2 sp = fuv * (span / max(speckle_size_m, 1e-4));
		float spk = 0.6 * vnoise(sp) + 0.4 * vnoise(sp * 2.3 + vec2(19.7, 4.1));
		spk = smoothstep(0.28, 0.72, spk);
		col *= (1.0 + grain_albedo_amp * state_grain * (spk * 2.0 - 1.0));
	}

	if (analysis_mode == 1) {              // slope heatmap: flat green -> ~17deg yellow -> >=35deg red
		float s = clamp(v_slope / 0.61, 0.0, 1.0);
		vec3 heat = mix(vec3(0.15, 0.7, 0.2), vec3(0.9, 0.8, 0.12), clamp(s * 2.0, 0.0, 1.0));
		heat = mix(heat, vec3(0.95, 0.15, 0.1), clamp(s * 2.0 - 1.0, 0.0, 1.0));
		col = mix(col, heat, 0.6);
	}
	ALBEDO = col;
	ROUGHNESS = rough;
	METALLIC = 0.0;
}

// Hapke IMSA BRDF, identical to terrain_farfield.gdshader's light() (see that file / terrain.gdshader
// for the full derivation + sources). The window NORMAL is the live height-gradient normal, so the
// window and the far context read as one airless-regolith surface under the grazing sun.
void light() {
	float mu0 = dot(NORMAL, LIGHT);
	if (mu0 > 0.0) {
		if (!hapke_enabled) {
			DIFFUSE_LIGHT += ALBEDO * LIGHT_COLOR * ATTENUATION * mu0;
		} else {
			float mu = max(dot(NORMAL, VIEW), 1e-3);
			float cg = clamp(dot(LIGHT, VIEW), -1.0, 1.0);
			float g  = acos(cg);
			float P  = hg_phase(cg, hapke_b, hapke_c);
			float B  = hapke_B0 / (1.0 + tan(0.5 * g) / max(hapke_h, 1e-4));
			vec3  w  = clamp(ALBEDO, vec3(0.0), vec3(0.999));
			vec3  gamma = sqrt(1.0 - w);
			vec3  Hi = (1.0 + 2.0 * mu0) / (1.0 + 2.0 * mu0 * gamma);
			vec3  He = (1.0 + 2.0 * mu)  / (1.0 + 2.0 * mu  * gamma);
			float ls = mu0 / (mu0 + mu);
			vec3  r  = (w * 0.25) * ls * ((1.0 + B) * P + Hi * He - 1.0);
			DIFFUSE_LIGHT += LIGHT_COLOR * ATTENUATION * max(r, vec3(0.0)) * hapke_gain;
		}
	}
}
