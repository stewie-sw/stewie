shader_type spatial;
// FAR-FIELD LOD terrain (spec §4 "Far field: render only, no physics ...
// procedural heightfield, 10+ cm with shader detail"; efficiency note).
//
// The D2 LOD demonstration: a SINGLE low-subdivision PlaneMesh whose vertices
// are displaced *in the vertex shader* by sampling a decimated heightmap tile.
// This is how the big inactive quadtree regions render cheaply — no per-vertex
// CPU mesh, no fine subdivision, just one plane + a cheap vertex displace.
// Contrast with terrain.gdshader, used for the fine ACTIVE zone.

// Diffuse is owned by the custom light() below — the SAME Hapke / Lommel-Seeliger BRDF as
// terrain.gdshader (render_fidelity), so the far field and the fine active window share one
// airless-regolith photometry (no BRDF seam where they meet), NOT Lambert.
render_mode specular_disabled;

uniform sampler2D height_lowres : filter_linear;   // R = elevation (m), decimated
// Aligned with terrain.gdshader's base_albedo (#2) so the fine ACTIVE window and this
// far-field plane don't show a brightness seam where they meet.
uniform vec3 base_albedo : source_color = vec3(0.45, 0.44, 0.43);
uniform float lod_step_m = 0.08;                   // world meters per low-res texel

// Macro albedo mottle (render_fidelity #2), mirrored from terrain.gdshader: the far-field
// plane FILLS the fly-through frame (the fine active mesh is only a sub-metre window around
// the rover), so the "textureless" grey was mostly THIS shader. Low-freq value mottle keyed
// to real metres so undisturbed far terrain reads weathered, not as a flat slab. Pure
// appearance. (GDShader has no shared include here, so hash/vnoise are duplicated.)
uniform float macro_albedo_amp = 0.13;
uniform float macro_scale_m = 0.42;
// Fine granular ALBEDO speckle (mirror of terrain.gdshader): world-anchored high-freq brightness
// grit so the far ground reads gritty + gives passive stereo matchable texture at distance, stable
// across sun angles. Per-state amp via state_grain_factor (TREAD smoothed). The far plane has NO
// detail-NORMAL pass (coarse geometry), so this albedo speckle is the far-field's grit contribution.
uniform float grain_albedo_amp = 0.22;
uniform float speckle_size_m = 0.020;

// State + disturbance at full field res (render_fidelity track fix): the far-field mesh is
// coarse, so the rover rut was rendering as undersampled geometric dimples. Reading the state
// label here makes the track a continuous TREAD albedo band that does NOT depend on mesh
// density (mirror of terrain.gdshader §6 state look, minus the in-shader detail-normal pass).
uniform sampler2D state_tex : filter_nearest;          // R = label/255 (0..4)
uniform sampler2D disturbance_tex : filter_linear;     // R = [0,1]

// Cut-depth / exposed-sublayer albedo (mirror of terrain.gdshader; render_fidelity). Gated
// by cut_depth_enabled (uniform-mantle scenes only) so it is fully additive.
uniform bool cut_depth_enabled = false;
uniform sampler2D mass_areal_tex : filter_linear;      // R = kg/m^2 (raw)
uniform float mantle_areal_m0 = 156.0;
uniform float surface_density_cd = 1300.0;
uniform float cut_depth_full_m = 0.08;
uniform float fresh_albedo_gain = 1.5;

// Photometry: Hapke BRDF (mirror of terrain.gdshader — see that file's light() block for the
// full equation + sources). The far-field plane fills the fly-through frame, so it MUST use the
// same airless-regolith photometry as the active window or the two would shade differently.
uniform bool  hapke_enabled = true;
uniform float hapke_b  = 0.26;     // 2-term HG lobe width (mare 643 nm; Sato et al. 2014)
uniform float hapke_c  = 0.08;     // 2-term HG back/forward partition (mare; Sato et al. 2014)
uniform float hapke_B0 = 1.0;      // shadow-hiding opposition amplitude (Hapke 2002)
uniform float hapke_h  = 0.06;     // shadow-hiding opposition angular width [rad] (Hapke 2002)
uniform float hapke_gain = 1.4;    // radiance calibration -> Lambert-comparable mid-tone (documented)

varying vec2 fuv;   // UV (0..1 across the field) carried to the fragment stage
varying float v_slope;                    // world-normal slope angle [rad], for the analysis overlay
uniform int analysis_mode = 0;            // 0 = normal shading, 1 = slope heatmap (path analysis)
uniform vec2 window_origin = vec2(0.0);   // world XZ min corner of the live fine window
uniform vec2 window_side = vec2(0.0);     // world XZ extent of the live fine window
uniform bool window_active = false;       // discard the coarse plane inside the window rect (no poke-through)
varying vec2 v_world_xz;                   // fragment world XZ (for the window-rect discard)
uniform vec2 region_uv_offset = vec2(0.0); // map plane UV -> the mission region's slice of the textures
uniform vec2 region_uv_scale = vec2(1.0);
varying vec2 v_suv;                         // region-mapped sample UV (height / state / disturbance)
varying float v_height;                      // world elevation (m), for the topo hypsometric ramp + contours
varying vec2 v_scan_rel;                      // fragment pos RELATIVE to the scan centre (small coords ->
                                             // avoids catastrophic cancellation of ~1e5 polar-stereo world XZ)

// TOPO overlay (analysis_mode == 2): MONOLITH-style shaded-relief topographic map — hypsometric
// gradient + contour isolines + survey grid + an expanding radar scan wave. Ported from
// kaolti/monolith-terrain (terrain.js onBeforeCompile); see stewie/design/STEWIE_viz2_planning_render_monolith_ATG.md.
// A toggleable ANALYSIS overlay for the planning view — the photoreal drive view (mode 0) is untouched.
uniform vec2  topo_height_range = vec2(0.0, 20.0);   // elevation min/max (m) mapped across the ramp
uniform float topo_height_pivot = 0.5;
uniform float topo_height_contrast = 1.0;
uniform vec3  topo_grad_low  : source_color = vec3(0.10, 0.18, 0.26);   // 4-stop hypsometric ramp
uniform vec3  topo_grad_mid1 : source_color = vec3(0.16, 0.40, 0.40);
uniform vec3  topo_grad_mid2 : source_color = vec3(0.58, 0.54, 0.34);
uniform vec3  topo_grad_high : source_color = vec3(0.86, 0.83, 0.75);
uniform float topo_slope_tint = 0.35;                // darken steep faces toward brown
uniform float topo_contour_interval = 1.0;           // m between MINOR contours (major every 5th)
uniform vec3  topo_contour_color : source_color = vec3(0.05, 0.04, 0.03);
uniform float topo_contour_opacity = 0.55;
uniform float topo_grid_step = 10.0;                 // m between survey-grid lines (world XZ)
uniform vec3  topo_grid_color : source_color = vec3(0.14, 0.13, 0.12);
uniform float topo_grid_opacity = 0.5;
uniform vec2  topo_scan_center = vec2(0.0);          // world XZ the scan ring expands from
uniform float topo_scan_span = 120.0;                // max scan radius (m); R = topo_scan_t * span
uniform float topo_scan_t = -1.0;                    // 0..1 progress, < 0 = scan off
uniform float topo_scan_width = 3.0;
uniform float topo_scan_blur = 1.5;
uniform vec3  topo_scan_color : source_color = vec3(1.0, 0.55, 0.12);   // amber sweep, high-contrast on teal topo
uniform float topo_ambient = 0.4;   // self-lit map floor so grazing-PSR shadows still read the topo
uniform float far_ambient_floor = 0.13;   // photoreal backdrop: dim self-lit floor so the full-DEM Haworth horizon reads under the grazing polar sun (the far light() diffuse is ~0 at el 18°)

// --- simplex noise (Ashima Arts / Stefan Gustavson "webgl-noise", MIT; mirror of terrain.gdshader) ---
// Replaces the prior square-lattice value noise (axis-aligned diamond artifacts) with isotropic
// simplex noise. snoise()~[-1,1]; vnoise() wraps to [0,1] so call sites (macro mottle, speckle) hold.
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

// Per-state micro-texture amplitude (mirror of terrain.gdshader; spec §6 state profiles). VIRGIN
// full grit, TREAD way down (compaction smooths), EXCAVATED/SPOIL coarse, BERM packed smoother.
float state_grain_factor(int lbl) {
	if (lbl == 1) return 0.20;
	if (lbl == 2) return 1.10;
	if (lbl == 3) return 1.15;
	if (lbl == 4) return 0.45;
	return 1.0;
}

// 2-term Henyey-Greenstein phase function P(g) vs cos(phase angle) (mirror of terrain.gdshader).
float hg_phase(float cg, float b, float c) {
	float b2 = b * b;
	float back = (1.0 - b2) / pow(max(1.0 - 2.0 * b * cg + b2, 1e-4), 1.5);
	float fwd  = (1.0 - b2) / pow(max(1.0 + 2.0 * b * cg + b2, 1e-4), 1.5);
	return 0.5 * (1.0 + c) * back + 0.5 * (1.0 - c) * fwd;
}

void vertex() {
	fuv = UV;
	// map the plane UV to the MISSION region's slice of the textures (region_uv_* = identity when off)
	vec2 suv = region_uv_offset + UV * region_uv_scale;
	v_suv = suv;
	// PlaneMesh lies in XZ; UV runs 0..1. Sample the (region-mapped) low-res tile and push Y up.
	float h = texture(height_lowres, suv).r;
	VERTEX.y += h;

	// Recompute the NORMAL from the heightmap gradient (central differences).
	vec2 ts = 1.0 / vec2(textureSize(height_lowres, 0));
	float hL = texture(height_lowres, suv - vec2(ts.x, 0.0)).r;
	float hR = texture(height_lowres, suv + vec2(ts.x, 0.0)).r;
	float hD = texture(height_lowres, suv - vec2(0.0, ts.y)).r;
	float hU = texture(height_lowres, suv + vec2(0.0, ts.y)).r;
	NORMAL = normalize(vec3(hL - hR, 2.0 * lod_step_m, hD - hU));
	v_slope = acos(clamp(NORMAL.y, -1.0, 1.0));   // 0 = flat, larger = steeper (for the slope overlay)
	vec4 wpos = MODEL_MATRIX * vec4(VERTEX, 1.0);
	v_world_xz = wpos.xz;   // world XZ (for the fine-window discard + topo grid/scan)
	v_height = wpos.y;      // world elevation (m), for the topo hypsometric ramp + contours
	v_scan_rel = wpos.xz - topo_scan_center;   // scan distance in a LOCAL frame (huge-coord-safe)
}

void fragment() {
	// The live fine window owns its footprint -> discard the coarse far plane inside it (minus a 0.3 m
	// rim the window's z-bias hides) so the coarse surface can't punch through the window on slopes. (#13)
	if (window_active) {
		vec2 rel = v_world_xz - window_origin;
		if (rel.x > 0.3 && rel.x < window_side.x - 0.3 && rel.y > 0.3 && rel.y < window_side.y - 0.3) {
			discard;
		}
	}
	// Macro albedo mottle (#2): field span = lowres_width * lod_step_m == world extent.
	float span = float(textureSize(height_lowres, 0).x) * lod_step_m;
	vec2 mp = fuv * (span / max(macro_scale_m, 1e-3));
	float m = 0.62 * vnoise(mp) + 0.38 * vnoise(mp * 3.3 + vec2(7.1, 2.7));   // [0,1]
	vec3 col = base_albedo * (1.0 + macro_albedo_amp * (m * 2.0 - 1.0));

	// State-driven track look (mirror of terrain.gdshader §6), so the rut reads as a
	// continuous band on the coarse far field. disturbance darkens churned fines; the label
	// tints the band. This is what makes the track a track and not a row of shadowed pits.
	float dist = clamp(texture(disturbance_tex, v_suv).r, 0.0, 1.0);
	col *= (1.0 - 0.18 * dist);
	float rough = 0.97;
	int lbl = int(round(texture(state_tex, v_suv).r * 255.0));
	float state_grain = state_grain_factor(lbl);
	if (lbl == 1) {            // TREAD: compacted rut -> darker, a touch smoother
		col *= 0.82;
		rough = 0.90;
	} else if (lbl == 2) {     // EXCAVATED: fresh firm sublayer -> brighter
		if (!cut_depth_enabled) { col *= 1.30; }   // cut-depth owns the brightening when on
		rough = 0.92;
	} else if (lbl == 3) {     // SPOIL: loose pile -> slightly darker, very rough
		col *= 0.90;
		rough = 0.98;
	} else if (lbl == 4) {     // COMPACTED_BERM: packed mound -> a touch brighter
		col *= 1.12;
		rough = 0.92;
	}

	// Fine granular ALBEDO speckle (world-anchored, mirror of terrain.gdshader): high-freq grit
	// keyed to real metres (fuv*span) so the far ground reads gritty + stereo-matchable at
	// distance; per-state amp (TREAD smoothed). The far plane's grit contribution (no detail-normal).
	{
		vec2 sp = fuv * (span / max(speckle_size_m, 1e-4));
		float spk = 0.6 * vnoise(sp) + 0.4 * vnoise(sp * 2.3 + vec2(19.7, 4.1));
		spk = smoothstep(0.28, 0.72, spk);   // crisp flecks (mirror of terrain.gdshader)
		col *= (1.0 + grain_albedo_amp * state_grain * (spk * 2.0 - 1.0));
	}

	// Cut-depth / exposed-sublayer albedo (continuous; mirror of terrain.gdshader).
	if (cut_depth_enabled) {
		float ma = texture(mass_areal_tex, v_suv).r;
		float removed_m = max(mantle_areal_m0 - ma, 0.0) / max(surface_density_cd, 1.0);
		float expo = clamp(removed_m / max(cut_depth_full_m, 1e-4), 0.0, 1.0);
		vec3 fresh = col * fresh_albedo_gain;
		float g = dot(fresh, vec3(0.3333));
		fresh = mix(fresh, vec3(g), 0.18 * expo);
		col = mix(col, fresh, expo);
		rough = mix(rough, 0.90, 0.4 * expo);
	}

	// slope analysis overlay: tint by terrain slope (flat green -> ~17deg yellow -> >=35deg red) so a
	// planner reads drivable vs no-go grade at a glance. (task #19 analysis)
	if (analysis_mode == 1) {
		float s = clamp(v_slope / 0.61, 0.0, 1.0);          // 0.61 rad ~= 35 deg -> full red
		vec3 heat = mix(vec3(0.15, 0.7, 0.2), vec3(0.9, 0.8, 0.12), clamp(s * 2.0, 0.0, 1.0));
		heat = mix(heat, vec3(0.95, 0.15, 0.1), clamp(s * 2.0 - 1.0, 0.0, 1.0));
		col = mix(col, heat, 0.6);
	} else if (analysis_mode == 2) {
		// MONOLITH shaded-relief TOPO map: hypsometric ramp + contour isolines + survey grid + scan wave.
		// (kaolti/monolith-terrain terrain.js onBeforeCompile, ported.) Self-lit floor keeps PSR shadows legible.
		float hN = clamp((v_height - topo_height_range.x) / max(topo_height_range.y - topo_height_range.x, 1e-4), 0.0, 1.0);
		float rt = clamp(0.5 + (hN - topo_height_pivot) * topo_height_contrast, 0.0, 1.0);
		vec3 ramp = (rt < 0.5) ? mix(topo_grad_low, topo_grad_mid1, rt * 2.0)
		                       : mix(topo_grad_mid2, topo_grad_high, (rt - 0.5) * 2.0);
		ramp = mix(ramp, vec3(0.42, 0.31, 0.21), clamp(v_slope / 0.61, 0.0, 1.0) * topo_slope_tint);
		// contour isolines: minor every interval, major every 5th (fwidth screen-space AA)
		float ch = v_height / max(topo_contour_interval, 1e-3);
		float minorL = 1.0 - smoothstep(0.0, fwidth(ch) * 1.4, abs(fract(ch + 0.5) - 0.5));
		float ch5 = ch / 5.0;
		float majorL = 1.0 - smoothstep(0.0, fwidth(ch5) * 1.4, abs(fract(ch5 + 0.5) - 0.5));
		ramp = mix(ramp, topo_contour_color, max(minorL * 0.55, majorL) * topo_contour_opacity);
		// survey grid (world XZ)
		vec2 gg = v_world_xz / max(topo_grid_step, 1e-3);
		vec2 dg = fwidth(gg);
		vec2 dGrid = abs(fract(gg + 0.5) - 0.5);
		float grid = max(1.0 - smoothstep(0.0, dg.x * 1.4, dGrid.x), 1.0 - smoothstep(0.0, dg.y * 1.4, dGrid.y));
		col = mix(ramp, topo_grid_color, grid * topo_grid_opacity);
		EMISSION = col * topo_ambient;   // self-lit map floor (readable in shadow); Hapke relief adds on top
		// expanding radar scan wave (bright emissive wavefront sweeping the site)
		if (topo_scan_t >= 0.0) {
			float d = length(v_scan_rel);   // relative-to-centre distance (precision-safe at 1e5 world XZ)
			float R = topo_scan_t * topo_scan_span;
			// clean triangular ring: peaks at d==R, falls to 0 at |d-R|==topo_scan_width (no fwidth noise)
			float band = smoothstep(topo_scan_width, 0.0, abs(d - R));
			float fade = 1.0 - smoothstep(0.6, 1.0, topo_scan_t);
			col = mix(col, topo_scan_color, band * fade * 0.85);
			EMISSION += topo_scan_color * band * fade * 1.8;
		}
	} else {
		// photoreal / slope modes: a dim self-lit floor so the full-tile Haworth backdrop reads at a grazing
		// polar sun (light() diffuse ~0 in the distance). Sun highlights still add on top via light().
		EMISSION = col * far_ambient_floor;
	}
	ALBEDO = col;
	ROUGHNESS = rough;
	METALLIC = 0.0;
}

// Hapke IMSA BRDF, identical to terrain.gdshader's light() (see that file for the full
// derivation + sources). The far-field NORMAL is the geometric heightmap-gradient normal
// (no detail-normal pass here), but the photometry — Lommel-Seeliger limb behavior, the
// backscatter phase function, opposition surge, multiple scattering — is the same, so the
// far plane and the active window read as one surface under the grazing sun.
void light() {
	// Godot's light() processor forbids `return` -> nested if/else (mirror of terrain.gdshader).
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
