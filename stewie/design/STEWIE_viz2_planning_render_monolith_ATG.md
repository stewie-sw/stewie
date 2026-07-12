# STEWIE viz2 — Planning→Rendering integration + MONOLITH terrain look (ATG plan)

Authored 2026-07-12 (Opus, via the `atg-plan` skill = Atomic Task Graph, arXiv:2607.01942).
Directive: "godot planning and rendering planning ... passing to rendering, integration" +
"synthetic/dem should look more like https://kaolti.github.io/monolith-terrain/ — research and integrate."
Build via `/loop` until complete. Scope decision (see Thought Experiment): the monolith TOPO style is a
TOGGLEABLE analysis/planning overlay (extends the existing `analysis_mode`), NOT a replacement — the
photoreal lunar drive view stays default; only the cinematic POSTPROCESSING is global.

## Task interface
in = current viz2 (launch-arg + control-frame planning seam; viz2_root.gd + terrain shaders;
mission_planner route wired ONLY to an offline `--path` capture) + MONOLITH reference spec (below).
out = live stream where planning artifacts (region/route/waypoints/overlay) flow as ONE `plan` object
into the Godot render, AND the DEM terrain renders monolith-topo-styled; gate green + live captures.

## Current planning→render seam (screened 2026-07-12)
- LAUNCH args app.py→Godot: `--bundle --session-dir --seconds --fine-cell-m --live --stream --site
  --stream-port --size --stream-fps --stream-quality --sun-az --sun-el`, `--clasts <json>`,
  `--region-size --region-cx --region-cz`. NOTE: `--path <route.json>` exists in viz2_root.gd
  (`_build_path_display`/`_run_path_capture`, viz2_path.gd emissive ribbon) but is an OFFLINE CAPTURE
  MODE, NOT passed by app.py to the live stream. => the mission_planner route never renders live (council #14).
- LIVE control browser→server→Godot (protocol.normalize_input): v/omega/dig/dump/sun/cam/orbit/drum/
  arm_front_d/arm_back_d/click_px/traverse/clear_wp/overlay. Waypoints are click-plotted INSIDE Godot
  (`_add_waypoint_from_click`, `_waypoints`, `_traverse_step`), physics-blind.
- mission_planner (lode/mission_planner.py): `plan()` / `build_timeline()` produce a slope-gated (25deg),
  battery-aware ordered-trip route + timeline (rows: coordinates/actions/speed/battery). Reaches the
  browser only as the frozen `--path` polyline.

## MONOLITH reference spec (researched from github.com/kaolti/monolith-terrain/src, 2026-07-12)
three.js; topo styling injected into the standard PBR frag via `onBeforeCompile` (file: terrain.js);
postprocessing lib (main.js); hand-rolled simplex/FBM/ridged-multifractal (noise.js); DEM via AWS
Terrarium tiles (dem.js); 2D FUI HUD via canvas-texture planes (hud3d.js). Aesthetic = "vintage USGS
topographic sheet x sci-fi FUI overlay."

### Terrain frag GLSL (terrain.js onBeforeCompile) — world pos via `varying vec3 vWorldPos;`
Hypsometric gradient:
```glsl
float hNorm = clamp((vWorldPos.y - uHeightRange.x)/max(uHeightRange.y-uHeightRange.x,1e-4),0.0,1.0);
float rampT = clamp(0.5 + (hNorm - uHeightPivot) * uHeightContrast, 0.0, 1.0);
vec3 ramp = texture2D(uRampTex, vec2(rampT,0.5)).rgb;   // 4-stop: gradLow/gradMid1/gradMid2/gradHigh
// + slope darkening toward brown vec3(0.42,0.31,0.21) via uSlopeTint
```
Contours (minor every interval, major every 5th):
```glsl
float ch = vWorldPos.y / uContourInterval;  float dch = fwidth(ch);
float minorLine = 1.0 - smoothstep(0.0, dch*1.4, abs(fract(ch+0.5)-0.5));
float ch5 = ch/5.0;  float dch5 = fwidth(ch5);
float majorLine = 1.0 - smoothstep(0.0, dch5*1.4, abs(fract(ch5+0.5)-0.5));
// uContourOpacity, uContourColor
```
Survey grid (world xz):
```glsl
vec2 g = vWorldPos.xz / uGridStep;  vec2 dg = fwidth(g);
vec2 dGrid = abs(fract(g+0.5)-0.5);
float grid = max(1.0-smoothstep(0.0,dg.x*1.4,dGrid.x), 1.0-smoothstep(0.0,dg.y*1.4,dGrid.y)) * uGridOpacity;
// grid color vec3(0.14,0.13,0.12)
```
Radar scan wave (expanding ring from origin, speed 42 u/normT; + vertex lift uScanDispH/W):
```glsl
float d = length(vWorldPos.xz);  float R = uScanT * 42.0;
float band = 1.0 - smoothstep(0.0, max(uScanBlur, fwidth(d)), abs(d - R) - uScanWidth*0.5);
// uScanT (0->1, neg=inactive), uScanWidth, uScanBlur, uScanColor
```
### Postprocessing (main.js EffectComposer)
ACES_FILMIC tonemap, exposure 0.96 (renderer NoToneMapping, done in post); DOF focus 24.74 / focal 0.06
/ bokeh 0-8; film grain 0.35 OVERLAY; vignette darkness 0.6 offset 0.28; SMAA; VSMShadowMap soft shadows;
linear fog near 35.5 far 50 color #ffffff. No bloom.

## ATG plan (Level 0 -> 1 -> 2)
- A Research & target: A1 src list [done] -> A2 shaders+postproc spec [done, above] -> A3 Playwright
  screenshot the live demo as the visual comparison target [pending].
- B Planning->render seam (council #14): B1 design `plan` JSON schema {region{cx,cz,size}, route[world_xy],
  waypoints[world_xy], overlay, timeline?} grounded in mission_planner.plan(); B2 protocol.py + app.py live
  `plan` frame (file-mediated like --clasts, browser or server can push); B3 viz2_root.gd consume live plan
  -> build route (reuse viz2_path.gd build()), waypoints, region live (not launch-only); B4 protocol/runtime tests.
- C Terrain look (Godot .gdshader ports of the GLSL above): C1 terrain_farfield.gdshader + viz2_window.gdshader
  + terrain_window: hypsometric ramp + contour + grid uniforms on world pos (already have v_suv/world varying);
  C2 time-driven scan-wave uniform (drive uScanT from the runtime/Godot clock); C3 WorldEnvironment: ACES
  tonemap + DOF + soft shadows + linear fog + a post CanvasLayer shader for grain+vignette; C4 wire the topo
  layers behind `overlay=topo` (extends analysis_mode: 0 none / 1 slope-heat [exists] / 2 topo).
- D Verify: D1 gate (pytest exit code, physics/runtime/specs + stream); D2 live capture drive+plan+topo,
  read frames vs the A3 target; D3 commit on feat/viz2-lunar-dataset.

Edges: A->C, A->B(overlay), B->D, C->D. Parallel: {A2,A3}, {B,C} after A.
Thought experiment: Constraint FLAG at C resolved (topo=toggle overlay, postproc=global, drive stays photoreal).
Repair rule: on failure localize to the atomic node, freeze validated nodes, repair minimal subgraph.
