shader_type canvas_item;
// C3: MONOLITH-style cinematic post — vignette + film grain over the rendered frame. A full-screen
// ColorRect samples the composited screen texture; grain animates via TIME (a DETERMINISTIC hash, not
// rng). Params mirror kaolti/monolith-terrain main.js (film grain 0.35, vignette darkness 0.6 / offset
// 0.28). Global (lifts both the photoreal drive view and the topo overlay); no DOF/fog (kept faithful).

uniform sampler2D screen_tex : hint_screen_texture, filter_linear;
uniform float grain_amount = 0.35;
uniform float vignette_darkness = 0.6;
uniform float vignette_offset = 0.28;

float _hash(vec2 p) {
	return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}

void fragment() {
	vec3 col = texture(screen_tex, SCREEN_UV).rgb;
	// vignette: full brightness at the centre, darkening toward the corners (offset = where it starts)
	float r = length(SCREEN_UV - 0.5) * 1.41421356;          // 0 centre -> ~1 corner
	col *= 1.0 - vignette_darkness * smoothstep(vignette_offset, 1.0, r);
	// film grain: per-pixel animated hash (subtle additive), TIME-driven so it shimmers frame to frame
	float g = _hash(SCREEN_UV * vec2(1920.0, 1080.0) + fract(TIME) * 97.0) - 0.5;
	col += g * grain_amount * 0.10;
	COLOR = vec4(clamp(col, 0.0, 1.0), 1.0);
}
