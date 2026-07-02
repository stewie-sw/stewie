# Haworth render: RESOLVED. The "near-black" frames were forward-pair aim/illumination geometry, NOT an engine bug

**Filed:** 2026-06-29 (LEAP estimator lane). **Updated/RESOLVED:** 2026-06-29 (same day, after the
Godot binary came up on this host and the render was run + diagnosed directly).

## TL;DR (the correction)

The original hypothesis in this note ("Haworth terrain material albedo / exposure / tonemap problem")
is **DISPROVEN**. The Godot render works correctly: the Haworth terrain, the rover seating (correctly
snapped onto the absolute LOLA elevations ~1831 m), and the lighting are all right. The
**downward-looking cameras render the Haworth surface fully lit** (`drum_back_cam` mean 99.6 / 255 at
sun-elev 30). What was "near-black" is **specifically the front stereo pair** (the pair
`benchmarks/render/run_render_vo.py` uses for VO), and the cause is two real **polar-terrain perception
hazards**, not an exposure bug:

1. **Geometric overshoot.** On the steep Haworth patch (8 m relief over a 20 m / 400-cell window =
   ~40 percent average grade), a forward-looking camera at ~1 m height facing downslope or off the
   patch edge sees mostly empty space above the local horizon. The terrain falls out of the bottom of
   the frame; the rest is black sky. Headings that face INTO rising/near terrain are full and lit;
   headings that face downslope see space.
2. **Grazing-sun self-shadow.** At low/oblique sun the camera-facing slopes are in shadow. Pitching the
   camera down to catch terrain then aims it into the shadowed near-slope (`--cam-pitch 35` at sun-elev
   25 azim 135 -> mean 4.0). This compounds #1.

Both are exactly the hazards the dissertation's shadow-channel / multi-camera niches are about. The
earlier 6-frame `haworth_sun5` / `haworth_sun30` renders (mean 4.1) used the worst combination:
`--cam-pitch 0` (overshoot into space) + an azimuth that shadowed the camera-facing slope.

## Evidence (all run directly on this host, RTX 3090 + Vulkan + xvfb, Godot 4.6.3)

| config (rc 91,276 on `haworth_spiral_driven`) | front_left mean | front_left frac>30 |
|---|---|---|
| sun-elev 30 azim 135, cam-pitch 0 (the original "black" recipe) | 13.4 (drum_back_cam = 99.6) | 0.06 |
| cam-pitch 35 (aim down into shadow) | 4.0 | 0.001 |
| sun-elev 60 (raise sun, pitch 0) | 14.0 | 0.09 |
| cam-pitch 25 + azim 315 (sun lights camera-facing terrain) | 35.5 | 0.26 |
| cam-pitch 25 + sun-elev 85 (near-zenith, heading-invariant) azim 135 | 24.7 | 0.20 |

Raising the sun alone does almost nothing (13.4 -> 14.0): the dominant effect is the camera AIM vs the
terrain, then the sun-vs-heading shadow. The pair is lit (mean 25-35, comparable to the working
`crater_boulders` mean ~34) only when the camera is pitched down AND the sun lights the terrain it
faces (a sun-behind azimuth, or a near-zenith inspection sun).

## Working configuration + the VO result it produced

A heading-invariant lit recipe: **near-zenith inspection sun (`--sun-elev 85`) + `--cam-pitch 25`**,
on a straight traverse kept inside the lit region facing into near terrain. Rendered a 14-frame
straight traverse (`--cameras-seq --rover-rc 91,205 --stride 14 SEQ_STEP_CELLS=4 --sun-elev 85
--sun-azim 135 --cam-pitch 25`): 11/14 frames well-lit (median front_left frac>30 = 0.21, matching
crater). Forward-stereo VO then ran:

- **VO valid 11/14 frames, ATE 0.518 m SE3 / 0.437 m Sim3 over a 3.82 m GT traverse**
  (`stewie/eval/validation/render_vo_haworth_straight_lit_2026-06-29.json`).

So the render track is unblocked and the VO stack runs on REAL rendered Haworth geometry, comparable to
`crater_boulders` (0.55 m). This is the concrete progress for the render-track items.

## Driven-spiral renderer: BUILT (2026-06-29), and what it revealed about the spiral

The driven-trajectory render path is now wired (it was the "(a) no wired render path" gap below).
`capture_seq.gd` gained an A/B trajectory source: when `--rover-pose <rover_pose.json>` is passed under
`--cameras-seq`, it reads the authored per-frame rc/yaw/up records as the trajectory (the REAL traverse)
instead of synthesizing a straight approach; off-patch records are skipped. Rendering the 80-frame
Haworth spiral (`--rover-pose .../rover_pose.json --sun-elev 85 --cam-pitch 25`) produced **78 in-bounds
lit frames** (median front_left frac>30 = 0.23, 71 percent of frames textured) -- GIFs at
`stewie/eval/validation/figures/haworth_spiral_driven_{front_left,drum_back}.gif`.

But VO on the spiral is **4/78 valid (med inliers 0)**
(`stewie/eval/validation/render_vo_haworth_spiral_sparse_2026-06-29.json`), because the authored spiral
is a **sparse-waypoint** track: per-frame motion is **median 2.5 m (max 7.8 m)**, matching the
`rover_pose.json` waypoint spacing. It was authored for the per-frame AprilTag pose demo (each frame
localizes independently off the lander tag), NOT for frame-to-frame stereo VO, which needs ~0.1-0.3 m
overlap. The spiral also only closes to **5.5 m** of its start (an inward spiral, not a true revisit).

## #3 loop-closing SLAM: BUILT + RUN (2026-06-29), with an honest limitation

The dense-revisiting trajectory + the full loop-closing SE(3) SLAM are now built and run end to end.
`benchmarks/render/gen_haworth_loop.py` writes a dense closed-loop `rover_pose.json` (a circle in the lit
patch interior, ~0.20 m/frame, returns to its start, then retraces a short overlap arc -- a true
revisit). `benchmarks/render/run_render_slam.py` runs the proven `dart` stack on the render contract:
SuperPoint+LightGlue stereo VO -> visual loop closure on the front-left stream (SuperPoint global
descriptor place recognition + LightGlue/PnP geometric verification) -> SE(3) pose graph (VO odometry +
loop edges + start prior), scored VO vs VO+LC vs the render GT pose. Two loops rendered + run with the lit
recipe:

| scene | frames | loop closures | VO ATE SE3 / Sim3 | VO+LC ATE SE3 / Sim3 | SE(3) converged |
|---|---|---|---|---|---|
| `haworth_loop` (3.0 m radius, 28 m path) | 105 | 46 | 1.343 / 1.331 m | 1.196 / 0.897 m | yes (9 it) |
| `haworth_loop2` (2.1 m radius, 16.9 m path) | 74 | 57 | 1.221 / 1.219 m | **0.816 / 0.560 m** | no (60 it cap) |

(`stewie/eval/validation/render_slam_haworth_loop{,2}_2026-06-29.json`; GIF
`figures/haworth_loop2_front_left.gif`.) **Loop closure measurably helps** -- it cuts the Sim3 ATE by 33
percent (loop1) to 54 percent (loop2). Visual loop closure is robust here (46-57 closures fire from the
revisit, high PnP inliers).

**The honest limitation (a finding, not a pipeline bug):** the VO front end is degraded by the single
DIRECTIONAL sun. On a full-rotation loop the rover must face away from the sun on part of the circle, so
even with a near-zenith inspection sun ~20-26 percent of frames go dark (anti-sun heading + geometric
overshoot) and hit 0 PnP inliers, which breaks the VO's conservative chain-validity flag (valid 11/74 on
loop2) and drops motion on those steps; the SE(3) graph then converges on the larger loop but not on the
tighter one (the held-pose odometry conflicts with the loop edges). This is exactly the directional-light
passive-vision starvation the dissertation's shadow / multi-camera channels exist to address -- forward
stereo alone cannot carry a full-rotation lunar loop under a single sun.

## Multi-camera VO: the limitation RESOLVED (2026-06-29)

The fix is the LAC rig's second stereo pair. On a full-rotation loop the REAR pair (looks -X) faces
TOWARD the sun exactly when the FRONT pair faces away, and the two are uncorrelated (corr 0.06). On
`haworth_loop2`: front-only frames usable (>=15 PnP inliers) = 48/74, rear = 70/74, **front-OR-rear =
71/74 (97 percent)**; the rear rescues 23 frames the front loses. `run_render_slam.py --multicam` fuses
them: per step it takes the pair with more inliers and maps that camera motion into the rover body frame
via the rig extrinsic (`DT_body = E . DT_cam . E^-1`), accumulating one body trajectory (rear carried 55
of 73 steps, only 1 held). The ladder (`render_slam_haworth_loop2{,_multicam}_2026-06-29.json`):

| stage (16.9 m loop) | ATE SE3 | ATE Sim3 | SE(3) converged |
|---|---|---|---|
| front VO | 1.221 | 1.219 | -- |
| front VO + loop closure | 0.816 | 0.560 | no |
| multicam VO (front+rear) | 0.565 | 0.550 (scale 0.943) | -- |
| **multicam VO + loop closure** | **0.480** | **0.459** | yes |

(A `--multicam` rotation-convention bug was caught + fixed before these numbers: the fusion must use the
inter-frame camera rotation `R_rel.T`, not `R_rel`; the front-only fusion now reproduces the direct VO to
0.00000 m, confirming the convention. The pre-fix table read 0.415/0.546 and is superseded.)

**Findings:** (1) the multi-camera front end roughly HALVES the VO error (front 1.221 -> multicam 0.565 m)
-- the rear pair covers the anti-sun headings the front loses; (2) loop closure HELPS at every stage
(front 1.221 -> 0.816; multicam 0.565 -> 0.480), so the full stack **multicam VO + loop closure (0.480 m
SE3 / 0.459 m Sim3, converged)** is best; (3) the multicam Sim3 scale 0.943 confirms the body-frame fusion
is metrically sound. So directional-sun starvation is real but the multi-camera rig resolves it.

**Nadir/drum camera as a third VO source: INVESTIGATED, not viable (2026-06-29).** The drum cameras are
always-lit (median textured fraction 0.996) and feature-rich (median 1543 SuperPoint matches/step), so
they looked like the ideal always-lit floor. But they are drum-INSPECTION cameras rigidly viewing the
rover's own drum, so their median inter-frame pixel flow is **0.6 px/step** (vs front_left 68.7, left_mono
25.3): the dominant features are rover-fixed and carry NO ego-motion. A mono VO from drum_back recovers
path 0.02 m over the 16.9 m loop by BOTH planar PnP and homography decomposition -- conclusively a
static-view degeneracy, not a method choice. So the viable multi-camera answer is the front+rear STEREO
fusion (above); the side monos (left/right, 25 px flow) DO see moving terrain and could be a monocular
third source, but they are mono (need a scale anchor) and directional (each covers only its lit side).
**Multi-exposure channel: INVESTIGATED, wrong tool here (2026-06-29).** Of the 25 VO-failing front
frames, 16 are deep-shadow (textured fraction < 0.08) and **0 have any clipping** (fraction of pixels at
>=250 is 0.0 everywhere). HDR / exposure bracketing exists to recover CLIPPED highlights, which do not
occur here. An exposure-gain test confirms the limit: a deep-shadow frame yields **0 SuperPoint keypoints
at gain 1, 3, and 8** (geometrically shadowed regolith has no signal in vacuum -- no fill light to
amplify), while partially-lit frames gain modestly (one went 297 -> 559 keypoints) but those are already
covered by the sun-facing rear pair. So multi-exposure does not address the bottleneck. The correct
responses to shadow-dark frames are the multi-camera rig (done) and, for the shadows specifically, the
shadow channel below -- which turns the shadow from a problem into a navigation signal.

## Shadow channel (Niche 1): FOUNDED + de-risked, measurement not yet validated (2026-06-29)

The dissertation's novel observable: recover a clast's height from its cast-shadow length,
`H = L_measured . tan(elevation)` (the inverse of the forward model already in `boulder_manifest.gd`:
`h_exposed = 2.radius.(1-buried_frac)`, `L = h_exposed/tan e`). Groundwork DONE: the clast ground truth
(center_m/radius_m/buried_frac in the scene metadata), the forward model, and the ortho world->pixel
projection (~30 px/m) are all in hand. Render blockers found by experiment, and the working config:

- The `--topdown-spiral` ortho mode renders only clast SELF-shadows, not the long GROUND-cast shadows
  (an intensity profile from a clast base along the anti-sun direction stays at terrain level) -- not
  usable for shadow-length measurement.
- A grazing perspective frame goes fully dark (directional-sun starvation), and the haworth clasts are
  low-buried domes (h_exposed 0.1-0.24 m, weak casters).
- **Working config FOUND:** a MODERATE sun on a sun-facing slope -- `--sun-elev 22 --sun-azim 315
  --cam-pitch 30` renders a lit regolith slope with the clast cast shadows visible as dark spots
  (front_left frac>30 = 0.12, the lit band textured). This is the render to measure on.

Remaining (the focused completion): a shadow-tip detector (project each clast base, scan the lit slope
along the projected anti-sun direction to the shadow tip + the `H = L.tan e` recovery validated against
the true `h_exposed`.

**Attempted (2026-06-29): projection VERIFIED, but the haworth clasts do not validate the recovery.** The
self-consistency gate was run and the camera convention nailed: the rover sits on a DOWN-slope facing the
dark valley while the lit terrain + clasts are UP-slope, so looking up-slope (`--cam-pitch -12`) puts 9
clasts exactly on their lit domes (intensities 88-143; the lander self-check confirms the world->pixel
math). BUT the cast shadows are NOT measurable on this scene: the clasts are low-buried domes (h_exposed
0.1-0.28 m, weak casters) and at the depths where they are lit + in-frame (6-11 m) each is ~13 px and
BLENDS into the texture-rich, relief-shadowed regolith. Marching the anti-sun direction (az 135 =
sun_az+180, derived from the Godot light + sign-checked) from each clast base shows lit terrain, no dark
streak; a visual crop of the biggest clast (id 5, h_exposed 0.282 m, depth 6.6 m) shows no
distinguishable dome-plus-shadow. So `H = L.tan e` could NOT be validated -- and **no recovery number is
reported, because the measurement gate did not pass** (an id-5 march gave 0.044 m vs 0.282 m true: a
failure, not a validation). Honest blocker: Niche 1 needs PROMINENT, well-separated casters (taller /
less buried, or fiducial posts of known height) on flatter lit terrain at close range -- a controlled
shadow-test scene, or a scene selected for big boulders. The geometry + detector code is proven; the
scene is the missing piece.

**Then found: the shadow channel was ALREADY BUILT (and my finding reproduces its documented status).**
Screening the live code (which should have come first) surfaced a mature DART/LEAP shadow subsystem:
`dart/shadow_height.py` (the `H = L.tan e` recovery), `shadow_extract.py`, `shadow_edge_sigma.py`,
`shadow_factors.py`, `shadow_predict.py`, `shadow_vectors.py`, `articulated_shadow.py`,
`shadow_sigma_calibration{,_measured}.py` -- **34 tests pass**. Its UNCERTAINTY is calibrated on REAL
Chang'e-3 descent-camera imagery (88 images, `sigma_edge_px` 0.685) propagated through real Haworth DEM
cast-shadow geometry (`shadow_sigma_calibration_MEASURED_2026-06-11.json`). Crucially, `shadow_height.py`'s
own VALIDATION STATUS docstring already states, definitively: H = L.tan e is correct geometry, but
**per-rock height could NOT be validated on the stewie renders by ANY method tried** (1-D ray-walk, 2-D
mask, at sun 6 and 25 deg; Pearson r ~ -0.1..-0.2, unstable recovered azimuth) -- a render/data
limitation, needs real ShadowCam PSR / NAC; `estimate_height_m` is a REGIME cue, not a calibrated height,
and the validated size sources are stereo + DEM residual. My from-scratch attempt above (projection
verified, shadows unmeasurable on the haworth domes) **independently reproduced exactly this conclusion.**
So Niche 1's channel is DONE + tested + honestly bounded; the open item is real PSR/NAC imagery, not code.

**Real-imagery acquisition tried, and DECISION (2026-06-29): accept the channel as a correctly-bounded
regime cue.** Pursued the real-data validation: downloaded the real **1 m LROC NAC-SfS Haworth DEM**
(`Lunar_LROnac_Haworth_sfs-dem_1m_v3.tif`, 537 MB, USGS public domain, now at `datasets/lunar_dem/`).
It cannot supply per-rock GT: shape-from-shading SMOOTHS rocks out -- meter-scale relief std 0.08 m, and
across windows only 0-2 discrete prominent features (smooth continuous crater slopes, not boulders). The
5 m LOLA DEM is coarser still. Rocks live only in the raw NAC IMAGERY, whose `.IMG`/`.cub` reading needs
ISIS / `pdr` (absent here; `rasterio` reads the DEM GeoTIFF but not NAC `.IMG`), and an INDEPENDENT
boulder-height GT (stereo NAC DTM resolving the boulder) is scarce at the pole even in the literature.
ShadowCam is the wrong instrument (PSR, secondary illumination only, no cast shadows). So the per-rock
validation is gated on tooling + GT scarcity -- a research-grade data obstacle, NOT a code gap. DECISION:
the shadow channel stands as a regime cue (the validated size sources remain stereo + DEM residual); the
real-NAC-imagery validation is deferred until the ISIS pipeline + a co-registered stereo-DTM GT exist.

## Provenance

Diagnosed by the LEAP estimator lane running the FORGE render directly. Evidence:
`render_vo_haworth_straight_lit_2026-06-29.json` (dense-traverse VO, 0.518 m),
`render_vo_haworth_spiral_sparse_2026-06-29.json` (sparse-spiral VO, 4/78), and
`render_vo_crater_boulders_2026-06-29.json` (the working reference scene), all under
`stewie/eval/validation/`. Reproducible via `bash stewie/godot/render.sh` +
`benchmarks/render/run_render_vo.py`. The only code change was the additive `capture_seq.gd`
driven-pose-track mode; no engine/exposure change was needed and the render geometry was not modified.
