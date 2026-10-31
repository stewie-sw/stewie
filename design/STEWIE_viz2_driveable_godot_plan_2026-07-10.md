# STEWIE viz2 — Driveable Godot Simulation ("Artemis STEWIE viz2") — Implementation Plan

**Date:** 2026-07-10
**Status:** PLAN ONLY. No pipeline code touched; this document is the single write of the planning pass.

---

## §0 Status / method note

Read-and-plan pass over `/mnt/projects/stewie/code` @ `main` HEAD `7b250003` (confirmed `git log`).
Every EXISTS / PARTIAL / NEW claim below cites a file:line I opened this session; claims I could not
confirm by opening the artifact are marked *(inferred)* with what would confirm them. Two upstream
anchors given in the task were verified and corrected:

- The DEM cross-reference doc is at **`/mnt/projects/stewie/design/DEM_CROSSREF_2026-06-11.md`**
  (repo-root sibling), NOT `code/design/` (confirmed: `code/design/` listing has no CROSSREF file).
- The multi-level viz doc's note that a dig/fill **difference drape "does not yet exist" is STALE**:
  LY-07 (`changed_terrain` signed as-built-minus-base drape) shipped D|D|D since
  (`PRD.md:721`, producer `stewie/server/gis_layers.py::_changed_terrain_rgba` per that row), as did
  GW-11 (/ide 3D terrain view, `PRD.md:717`), GW-12 (coordinate contract, `PRD.md:718`) and LY-05
  (aspect/curvature/roughness/contours, `PRD.md:719`). The plan REUSES these instead of rebuilding.

Constraint posture: Godot 4.6.3 (binary pinned by `render.sh`; scripts reference
`stewie/godot/.tools/godot/Godot_v4.6.3-stable_linux.x86_64`, `scripts/demo/render_ezrassor_katwijk_parallax.py:32`).
No synthetic terrain, no fabricated boulder statistics; FORGE authority rules
("a backend that does not conserve mass cannot claim release authority",
`packages/stewie-forge/stewie_forge/backend_protocol.py:5,30-31`) are kept intact throughout.

---

## §1 Current-state table (all evidence opened 2026-07-10)

| # | Requirement | Status | Evidence (opened) |
|---|---|---|---|
| 1 | Driveable EZ-RASSOR rover, keyboard/gamepad | **PARTIAL** | A live WASD 8-pane drive view exists: `stewie/godot/drive_controller.gd:1-6` ("intern drives the rover (WASD)... 60 fps"), dispatched from `sidecar.gd:144-148,244-248` (`--drive` / `--drive-auto`). BUT (a) pose integration is a **kinematic GDScript port** — `drive_controller.gd:143-157` integrates `pose_x/pose_yaw` directly from key state and `_apply_pose()` (L99-103) just sets y = `sf.height_uv(u,v) + WHEEL_R + lift`: **no slip, no sinkage, no entrapment, no terrain mutation**; the file's own header says the conserved Python authority "stays the analysis/export tier". (b) **Gamepad: NEW** — `project.godot` has no `[input]` section (grep "input" empty) and the controller polls raw `Input.is_key_pressed` (L149-152). (c) EZ-RASSOR assets are real and converted: `stewie/godot/assets/{rover_base,rover_body,drum,drum_arm}.glb` (dir listing) + `out/body_ez_rassor.png` (dir listing); provenance + MIT-attribution rules in `docs/ezrassor_assets.md:14-33,138-151`. (d) **Live bug found:** `drive_controller.gd:51` loads postures from `../terrain_authority/data/ipex_postures.json` — that path no longer exists (`ls` fails); the file moved to `stewie/physics/data/ipex_postures.json` (find). Posture buttons currently silently no-op. |
| 2 | Hot-swappable terramechanics via FORGE in the drive loop | **PARTIAL** | The pieces all exist but are not joined for a live drive view. (a) `PhysicsBackend` protocol + authority classes: `stewie_forge/backend_protocol.py:15-39`; concrete `Tier2NumpyBackend` + registry: `stewie/physics/backend.py:26-67` — **only `tier2_numpy` registered**; Chrono is "PX-03 (geometry-oracle, NOT release-authority until it conserves mass)" (`backend.py:58-59`). (b) `GET /physics/backends` (PX-02) exposes selectable backends + the model ledger, `tier3_chrono` listed with `validated=False` and excluded from the selectable set (`stewie/server/routers/models.py:149-177`). (c) The REAL conserved drive loop with slip-sinkage lives at `stewie/physics/drive.py:181-298` (`drive_step`: conform → slip-sinkage equilibrium → entrapment discrete state L240-257 → `step_pose` → slip-deepened ruts via `four_wheel_pass(physical=True)` L286-288, per-cell material strength L207-215, skid-steer per-side slip L260-282). (d) GAP: `drive_step` calls `stewie.physics.terramechanics`/`slip` **directly**, not through `get_backend()` — the backend protocol today exposes only 3 point functions (`wheel_static_sinkage`/`static_wheel_load_n`/`allowable_bearing_pa`, `backend_protocol.py:36-39`), NOT a step-level seam; and no Godot view calls `drive_step` at all. |
| 3 | Haworth at highest resolution (1 m SfS base + 2 cm runtime fine) | **PARTIAL** | (a) The 1 m NAC SfS DEM is REAL and on host twice: `code/datasets/lunar_dem/Lunar_LROnac_Haworth_sfs-dem_1m_v3.tif` and `data/gis/raw/Haworth_1m_sfs.tif`, both 11660×12060 @ 1.0 m, polar stereographic R=1737400, bounds X∈[−40120,−28460], Y∈[83260,95320] (verified via rasterio this session). Registered in `dart/dem_sources.py:168-174` (`lroc_nac_sfs_1m`, ingest="dem_import", USGS photoclinometry URL — the 2026-07-09 404 finding is already fixed). PIL opens it in mode 'F' with tags 33550/33922/34735 present (verified; matches `dart.dem_import.load_lola_geotiff` assumptions incl. the PixelIsArea corner fix, `dem_import.py:110,233,266`) — with a `DecompressionBombWarning` (140.6 Mpx > PIL's 89.5 Mpx default; loads today, needs an explicit `MAX_IMAGE_PIXELS` guard — grep found none in `dem_import.py`/`build_from_dem.py`). (b) **LOAD-BEARING FINDING: the committed `haworth_10km_5m` bundle does NOT overlap the SfS footprint.** Bundle `world_bounds_m` X∈[−52900,−42900], Y∈[95400,105400] (`samples/lunar_dem/haworth_10km_5m/metadata.json`, read) vs SfS X∈[−40120,−28460], Y∈[83260,95320] — disjoint. A "Haworth at 1 m" site is a **NEW crop centered inside the SfS footprint**, not a resolution upgrade of the existing bundle. (c) The 5 m base + 2 cm runtime-fine contract (coordinate-hashed determinism, LRU resident window) is frozen at `docs/dem_terrain_contract.md:6-14` with the machinery in `stewie/terrain/` (`tiles_mosaic.py`, `procgen_seed.py`, `dem_overlay.py` — dir listing; contract §3-§5). (d) The Godot terrain builder renders active-fine + far-field LOD from the authoritative heightmap (`stewie/godot/terrain.gd:1-27,44-98,136-168`). Ingest CLI supports `--extent-m/--base-cell-m` (`scripts/build_from_dem.py:19,58`). |
| 4 | Interactive sun azimuth + elevation sliders | **PARTIAL** (scripted only) | `stewie/godot/sun_sweep.gd` is a **scripted** 12-frame sweep (cadence constants L32-47; `run_sun_sweep` L62; sun drive convention `rotation_degrees = Vector3(-elev, azim, 0)` L121, matching the sidecar's live sun members). The sidecar exposes `--sun-elev/--sun-azim` CLI (defaults 5°/215°, `sidecar.gd:16,113-116,535-538`) — per-render, not live. **No interactive slider UI exists.** The sun-sweep manifest honestly flags its az/el model as a documented assumption, not an ephemeris (`sun_sweep.gd:163-177`); the backend does have real SPICE-sun illumination/PSR producers (`design/STEWIE_multilevel_dem_viz_design_2026-07-08.md` §4 table, EXISTS rows; `dart/illumination.py` in dir listing) for cross-checks. |
| 5 | Realistic rock dispersion + size patterns from real statistics | **PARTIAL** | (a) The Golombek cumulative-fractional-area SFD is implemented and sourced: `golombek_q(k) = 1.79 + 0.152/k`, `F_k(D) = k·exp(−q(k)·D)` (`stewie/specs/constants.py:202-215`, citing Golombek et al. 2003 LPSC XXXIV; the model "correct AS-IS (Golombek & Rapp 1997, doi:10.1029/96JE03319)" `constants.py:526-527`). Sampler `sample_boulders` inverts area-SFD → Poisson counts → clast list (`stewie/terrain/procgen.py:289-352`), with the self-declared gap at L311-313: "PAPERED OVER: clast positions/sizes are independently sampled (no spatial clustering, no overlap rejection, no slope/ejecta correlation)". (b) Spatial abundance k is sourced-but-[CALIB]: polar background <1% (Bandfield 2011 Diviner), ejecta ramp 0.05-0.40 (`constants.py:524-539`); buried-fraction honestly [UNKNOWN] (`constants.py:541-546`). (c) Real-NAC validation machinery exists: `benchmarks/nac_shadow/nac_boulder_repro.py:1-100` (H = L·tan(e) reproduced against Demidov & Basilevsky 2014 h/d = 0.60±0.03, DOI 10.1134/S0038094614050013, + Apollo 17 House Rock absolute anchor; truth firewall L17-21), `nac_twosun.py:1-23` (two-Sun self-consistency on sparse mare), real ortho fixtures on disk (`benchmarks/nac_shadow/fixtures/`, 9 GeoTIFF crops, 2.4 MB). (d) Godot consumes clasts from scene metadata verbatim (`boulder_manifest.gd:8-14,29-83`; source of truth `sf.clasts`, state_fields.gd:160 per that header). GAP: no per-site spatial-k rock map has ever been generated over a REAL DEM tile (the sampler is uniform-random over a patch), and no polar/Haworth-specific measured boulder census exists in the repo (the NAC work is mare/Apollo sites — see §4 BLOCKED). |
| 6 | Dig + before/after dig-depth difference field | **PARTIAL** (engines EXIST; Godot surface NEW) | (a) Conserved dig verbs: `stewie/physics/worksite.py` — `WorkSite.drive/.flatten/.dump/.sinter` (L229,242,256,297; `flatten_to_level` L40). (b) RL/energy-grounded worksite env over real Haworth with the IPEx battery budget (`leap/worksite_env.py:1-16,60-72` — dig 4151 J/kg, drive 135 J/m, `bundle_dir` loads the real DEM). (c) Typed conserved volume evidence: `leap/volume_evidence.py:15-35` (`RegolithVolumeEstimate.from_delta`, conserved-mass cross-check) over `lode/regolith_volume.py:1-20` (ML-06 volume/mass + uncertainty). (d) The before/after difference drape EXISTS server-side: LY-07 `changed_terrain` (signed as-built−base, diverging legend, `/world/point` per-cell depth), verified on real Haworth after a conserved cut+fill (`PRD.md:721`, D|D|D). (e) Godot already renders excavation state + cut-depth albedo (`terrain.gd:194-232`: state/disturbance/mass_areal textures, `cut_depth_enabled`, fresh-albedo gain; falsecolor state/height modes L238-248). GAP: no **live** in-Godot dig interaction (WorkSite verbs are Python-only) and no in-Godot signed-difference drape (the falsecolor shaders show state + absolute height, not before−after). |
| 7 | Map + path analysis vs rock height/size and slope | **PARTIAL** | (a) The 12-layer costmap with per-cell blocking reasons EXISTS: `lode/costmap_layers.py:1-29` (slope, roughness, Bekker sinkage, slip, tip_risk, negative_obstacle, illumination, psr, shadow_conf, energy, keepout, reservation; layer functions L62-118). (b) Path planning + full mission planner EXIST: `lode/mission_planner.py:1-20` (facade over 10 leaf modules; `plan()` L223, `run()` L395 — cut-fill balance, routing, battery-aware sequencing, PDF report). (c) GAP — **rock height/size is NOT a costmap input**: rocks enter only as "dynamic rocks IS negative_obstacle (the drop-off / rock-rim hazard)" (`costmap_layers.py:22-23`) i.e. DEM drop-offs, and 3×3 slope roughness (L70-78). A discrete-clast layer (exposed rock height h = 2r(1−buried) vs the sourced IPEx obstacle limit `OBSTACLE_HEIGHT_M = 0.075` [SCHULER24], `stewie/specs/ipex_specs.py:79`) does not exist. (d) In-Godot path display: the cockpit 3D (`three3d.js`) and /ide (GW-11) already animate planned paths; the Godot sidecar renders pose tracks via `--rover-pose` (`sidecar.gd:156`), but no live costmap/path overlay exists in Godot. |
| 8 | Cross-analyze / compare all DEM sites + papers | **PARTIAL** | (a) 11 real site bundles on disk (`samples/lunar_dem/` listing: haworth, shackleton_rim, nobile_rim1/2, connecting_ridge, de_gerlache_rim, de_gerlache_kocher, leibnitz_beta, malapert_massif, peak_near_shackleton, shoemaker); raw `Site*_surf/_slp.tif` + `ldem_75s_120m.img` + the 1 m SfS in `data/gis/raw/` (listing); global LDEM 118 m on host (`/mnt/projects/datasets/argus_dem_nav/lunar_dem/Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif`, ls) feeding the plan-anywhere resolver (`design/STEWIE_more_DEMs_plan_2026-07-09.md` §1.4/§3.1). (b) The DEM source catalog with honest per-source readiness: `dart/dem_sources.py:1-16` (11 tiles bundled-noted, `planning_grade` L41-45). (c) `dart/dem_cross.py` is **NOT a DEM-vs-DEM site comparator** — it cross-validates imagery obstacle detections against ONE prior DEM's derived layers (`dem_cross.py:1-11,41-67`); `dart/dem_terrain_match.py:1-30` is terrain-relative localization (S3LI Etna TRN). A cross-SITE / cross-PRODUCT comparison surface (side-by-side stats, slope/roughness/uncertainty per site, SfS-vs-LOLA residual where footprints overlap) is **NEW**. (d) The papers + placement/error-budget analysis exist in `/mnt/projects/stewie/design/DEM_CROSSREF_2026-06-11.md` (5 products, §a-§c; toterr/ldec/slperr layer recommendations §c — toterr/ldec ingest still NOT implemented: no `--aux` companion-raster support in `scripts/build_from_dem.py`, its CLI at L19 shows only src/out/extent/base-cell/stride). |

---

## §2 Key architecture forks

### (a) Separate Godot project vs a new driveable mode inside `code/stewie/godot/`

**Recommendation: a new, separately-launched SCENE + script family inside the existing
`code/stewie/godot/` project** (`viz2.tscn` + `viz2_*.gd` + a `viz2.sh` launcher), zero edits to the
frozen sidecar/render seams. "Separate simulation" is satisfied at the entry-point level: viz2 never
runs through `render.sh`/`sidecar.tscn`'s headless contract, has its own root node, HUD and process
loop, and can be deleted without touching the sidecar.

- Why not a second Godot project: every asset viz2 needs already lives in this project —
  `state_fields.gd` (the FROZEN INTERFACE.md rf32 loader, header L3-8), `terrain.gd` (active-fine +
  far-field LOD + Hapke/cut-depth shaders), `camera_rig.gd`, the clast shader, and the EZ-RASSOR glbs
  (`assets/rover_base.glb` etc.). Godot cannot share `res://` resources across projects without
  duplication; a copy forks the frozen seams and the 4.6.3 pin.
- Why not extend `drive_controller.gd` in place: its header declares the kinematic-port design
  ("the conserved Python authority stays the analysis/export tier", `drive_controller.gd:2-5`) —
  viz2's core requirement inverts that. Keep the old `--drive` mode intact for the headless-verify
  lane (`--drive-auto`, L146-147,163-174) and build viz2 beside it.
- PRD alignment: this is the natural implementation lane for **RT-05 "Godot mission view
  (sidecar-first)"** — currently glyph N (`PRD.md:672`) — extended with drive interactivity. New PRD
  rows should extend RT-05 rather than duplicate it.

### (b) How the Godot loop talks to FORGE/LODE/LEAP

**Recommendation: a persistent local Python "viz2 physics daemon" owning the authority, spoken to by
Godot over a length-prefixed JSON stream on a localhost TCP socket (StreamPeerTCP in Godot,
`socketserver`/asyncio in Python), with terrain-field updates flowing back through the FROZEN rf32
window-patch seam (atomic tmp+rename + a generation counter in the JSON channel).**

- Authority stays in Python: Godot sends `{v_cmd, omega_cmd, dt, seq}` at the physics rate
  (10-20 Hz); the daemon runs `stewie.physics.drive.drive_step` on the real `ColumnState`
  (slip, sinkage, entrapment, conserved ruts — `drive.py:181-298`) and returns the telemetry dict
  verbatim (rc/yaw/slip/entrapped/sinkage_m/contact_len_m, L289-297). Godot interpolates pose to
  60 fps and NEVER integrates its own pose — this retires the GDScript kinematic port for viz2 and
  keeps single-authority discipline (the same rule the Chrono seam enforces).
- Dig verbs ride the same channel: `{"op":"flatten"|"dump", mask_window, target}` →
  `WorkSite.flatten/.dump` (`worksite.py:242,256`); the daemon responds with moved kg + writes the
  dirty heightmap/state/mass_areal windows as rf32 patches Godot re-textures (the existing
  `state_fields.gd` texture path; `io_fields` contract stays frozen per
  `docs/dem_terrain_contract.md:74`).
- Alternatives weighed:
  - **GDExtension / embedded Python** — heaviest option, no precedent in the repo, couples Godot
    build to the venv; rejected.
  - **File-seam polling** (the existing pattern: `--rover-pose` JSON track `sidecar.gd:156`,
    `cmd_vel` dir from the roversim era) — proven but adds disk-latency jitter to an interactive
    loop; kept ONLY as the terrain-patch lane (bulk arrays), not the command lane.
  - **FastAPI/WebSocket via `stewie/server`** — attractive later (PX-02 backend selection, auth,
    LY-07 drape all live there), and the CSP already anticipates same-origin WebSocket for
    Godot/RViz panels (`stewie/server/test_gw00_csp.py:4`); rejected as the *primary* loop because
    viz2 must run standalone at 60 fps without the server stack. Phase F adds an OPTIONAL
    read-only bridge to the server for costmap/plan payloads.
  - **ROS2 bridge** (`stewie/bridge/ros2_bridge.py`, `stream.py:1-13` versioned backpressured
    session) — that is the flight/rehearsal lane (RT-00/RT-03), not the operator-viz loop; the
    daemon protocol deliberately mirrors `StreamSession`'s seq/ack shape so a later ROS2 lowering
    is mechanical.

### (c) Coordinate frames

**Recommendation: adopt the shipped GW-12 contract wholesale; add viz2 as one more render surface
under it.** Authoritative coordinates exist ONLY in IAU_2015:30135/30100 (or an ad-hoc tile's local
CRS) on the server side; every render surface declares a local origin near the work area and renders
float32-relative; every pick converts back through `stewie/terrain/site_dem.py` transforms
(`latlon_to_dem_origin` L211, `dem_origin_to_latlon` L227, `grid_north_bearing_deg` L245) before
persisting (`PRD.md:718`, shipped with a 0.98 mm worst-case ULP finding and a 2^17 m 1-cm-safe bound).
Concretely for viz2:

- Godot local origin = the site bundle's `world_bounds_m` min corner, exactly the existing
  field→Godot mapping (`terrain.gd:13-14`: gx = col·cell, gz = row·cell, origin at world_bounds min).
  For the recommended 2 km @ 1 m site (below), max in-scene coordinate ≈ 2×10³ m → float32 ULP
  ≈ 0.125 mm; far under budget.
- Every viz2 pick/waypoint/dig footprint serializes as order-frame metres through the daemon and,
  when handed to LODE/server, converts via the shared `site_dem.py` transforms — viz2 never invents
  a frame. The new 1 m site registers in `stewie/specs/sites.py` + `dart/dem_sources.py` like any
  site, so `/dem/site_lonlat` and the GW-12 round-trip test cover it for free (extend the GW-12
  test's site list to include it — the test iterates curated tiles per `PRD.md:718`).
- Sun convention: keep the sidecar/sun_sweep convention `rotation_degrees = Vector3(−elev, azim, 0)`
  (`sun_sweep.gd:121`; grid-north vs true-north correction available via `grid_north_bearing_deg`
  when comparing against SPICE-sun backend layers).

### (d) Where the GPU rendering runs

**Recommendation: host GPU, interactive session — primary on the archimedes RTX 3090 (windowed or
xvfb+Vulkan for the headless verify tier), with euclid (NVIDIA 535.261.03, via SSH + display
forwarding or local session) as the second host. NOT in Docker.** GPU *graphics* in Docker on this
host is blocked (compute-not-graphics CDI; Gazebo/ogre2 EGL segfault → llvmpipe — project memory
`infra_stewie_gpu_render_blocked`; fixing it needs a sudo host CDI change). The proven on-host lane
already exists: Godot 4.6.3 headless on the 3090 via
`xvfb-run … --rendering-driver vulkan` (project record, CLAUDE.md "GODOT RENDER TRACK LIVE
2026-06-04"; `render.sh` documents the ICD attach). An interactive operator sim wants a real
window/compositor anyway; keep `deploy/Dockerfile.godot` strictly for the opt-in headless sidecar it
already gates. The Python daemon is CPU-only (numpy authority is sub-ms/step per the repo's own
record) and runs beside Godot on the same host.

---

## §3 Phased, atomic task list

Verification discipline: each task ends with a REAL observation (a rendered frame diffed by eye/
Playwright-style capture, a pytest exit code, or a numeric check against the authority) — the full
suite gate stays `pytest` over `lode/ leap/ dart/ forge/ stewie/` parsed by EXIT CODE (standing
project rule), plus the Godot headless-verify captures.

### Phase A — 1 m Haworth site + viz2 scene renders it + drive input

| Task | Change | File(s) | Verification |
|---|---|---|---|
| A1 | Add a PIL `Image.MAX_IMAGE_PIXELS` guard (explicit, bounded, with a comment naming the 140.6 Mpx SfS file) to the ingest lane | `dart/dem_import.py` | Unit test: `load_lola_geotiff` on the real SfS tif returns (11660,12060) float32 with the verified affine (corner −40120/95320, 1.0 m px), no warning |
| A2 | Build the **new 1 m site bundle**: `scripts/build_from_dem.py --src code/datasets/lunar_dem/Lunar_LROnac_Haworth_sfs-dem_1m_v3.tif --out samples/lunar_dem/haworth_sfs_2km_1m --extent-m 2000 --base-cell-m 1.0`, crop center chosen INSIDE the SfS footprint (max-relief window, e.g. near (−34290, 89290)); 2000² grid = identical memory shape to every existing bundle | new bundle dir + no code (CLI exists, `build_from_dem.py:19,58`) | The script's own self-verify (round-trip max_err print + non-zero `world_bounds_m` asserts, per `design/STEWIE_more_DEMs_plan_2026-07-09.md` §1.2); manually confirm `world_bounds_m` ⊂ SfS bounds |
| A3 | Register the site: `Site(...)` in `stewie/specs/sites.py` + `DemSource(bundled=True)` update of the existing `lroc_nac_sfs_1m` row (or a bundle-specific row) in `dart/dem_sources.py` | those two registries | Existing gates: `dart/test_dem_sources.py`, `stewie/server/test_dem_sources_registry.py`, `stewie/specs/test_sites.py`, `test_geo_siting.py`, `test_plan_anywhere.py` all green (exit code); `/dem/sources` lists it |
| A4 | viz2 scene skeleton: `viz2.tscn` + `viz2_root.gd` — loads the bundle via `state_fields.gd`, builds terrain via `TerrainNode` (`terrain.gd:34`), places the EZ-RASSOR glb rig (reuse the rover build path the sidecar uses; carry the MIT notice per `docs/ezrassor_assets.md:21-23`); `viz2.sh` launcher | new files under `stewie/godot/` only | Headless verify capture (the `--drive-auto` pattern, `drive_controller.gd:163-174`): a viz2 `--auto N` flag writes a frame; human eyeball: real 1 m relief + rover visible |
| A5 | Input: Godot InputMap actions (`viz2_forward/back/left/right/dig/dump/brake`) bound to WASD **and** gamepad axes/buttons in `project.godot`; controller reads actions, not raw keys | `project.godot`, `viz2_root.gd` | On-host interactive run with a gamepad: drive translates/turns (operator observation — this one is a real-hands check); headless: action-injection unit via `Input.parse_input_event` in a GUT-less script test *(inferred that scripted injection works headless; confirm in A5 itself)* |
| A6 | Fix the stale postures path (`../terrain_authority/data/ipex_postures.json` → `../physics/data/ipex_postures.json`) in the EXISTING drive_controller (adjacent one-line bug, flagged §1 row 1) | `stewie/godot/drive_controller.gd:51` | `--drive-auto` run prints posture load success; buttons change arm angles in the capture |

### Phase B — FORGE authority in the loop (hot-swappable)

| Task | Change | File(s) | Verification |
|---|---|---|---|
| B1 | **Extend the FORGE seam with the step-level contract**: add `drive_step(...)` (and a `worksite(...)` accessor) to the `PhysicsBackend` protocol; `Tier2NumpyBackend` delegates verbatim to `stewie.physics.drive.drive_step` (byte-identical, same pattern as the existing 3 delegates `backend.py:42-50`) | `stewie_forge/backend_protocol.py`, `stewie/physics/backend.py` | New `[REQ:]` test: `get_backend("tier2_numpy").drive_step(...)` output == direct `drive.drive_step(...)` on a real bundle crop; existing `test_physics_backend*.py` green |
| B2 | viz2 physics daemon: `stewie/godot/viz2_bridge.py` (precedent: `articulation_bridge.py` lives there) — loads the site `ColumnState`, owns a `PhysicsBackend` chosen by id, serves the JSON-over-TCP protocol (§2b), writes rf32 window patches | new file | Pytest drives the daemon over a real socket (the `planet_browser/server.py` real-socket test pattern): command a twist on the 1 m bundle → telemetry has slip>0 on slope, entrapment on the crater wall; mass conserved before/after |
| B3 | Godot side: `viz2_drive_client.gd` — StreamPeerTCP client, sends actions at 15 Hz, interpolates authority poses at 60 fps, applies rut/terrain patches to the StateFields textures; HUD shows live slip/sinkage/entrapped from telemetry | new files | `--auto` headless run over a scripted twist sequence: final pose in the capture matches the daemon's reported pose (numeric diff < 1 cell); rut visibly carved in the falsecolor-state capture |
| B4 | **Hot-swap honoring authority rules**: HUD backend picker populated from `GET /physics/backends` when the server is up, else from the daemon's `list_backends()`; swap = daemon re-resolves `get_backend(id)` mid-session on the SAME ColumnState. Selection is validated against `selectable_backends` — `tier3_chrono` renders in the picker greyed with its `validated=False` ledger reason (`models.py:160-176`) and CANNOT be given terrain-mutation authority (fail-closed, the PX-02 behavior) | `viz2_bridge.py`, HUD | Test: requesting `chrono`/`tier3_chrono` raises the registry `ValueError` (`backend.py:60-62`) / returns the fail-closed refusal; swapping tier2→tier2 mid-drive is a no-op on state |
| B5 | Chrono **advisory** lane (display-only): when a PyChrono env is present (micromamba host env — see §4 status), the daemon may run the committed-SCM-anchored comparison as a side channel (advisory sinkage overlay next to tier2 numbers), never mutating terrain | `viz2_bridge.py` | Skip-clean test when PyChrono absent; when present: advisory numbers appear in telemetry tagged `authority_class="advisory"`, terrain hash unchanged. **Partially BLOCKED**: a registered live Chrono backend is PX-03, unbuilt; needs the validated PyChrono host env |

### Phase C — Live sun sliders

| Task | Change | File(s) | Verification |
|---|---|---|---|
| C1 | HUD sliders: azimuth 0-360°, elevation −5..+90° driving the DirectionalLight via the `Vector3(−elev, azim, 0)` convention (`sun_sweep.gd:121`); numeric readout + "grazing polar band" annotation (the 0-7° band constant, `sun_sweep.gd:33-36`) | `viz2_hud.gd` | Interactive: shadows sweep live. Headless: two `--auto` captures at (215°,5°) vs (35°,5°) — shadow direction flips in the images |
| C2 | Consistency check vs the backend's real illumination producer: at slider (az,el), sample `dart.illumination.horizon_clip`/incidence on the same heightfield window and display %-shadowed; assert the Godot shadow mask and the horizon-march mask agree within a stated tolerance on a test capture | `viz2_bridge.py` + a `[REQ:]` test | Pytest: mask IoU above threshold on the real 1 m crop at grazing sun (a real render-vs-analytic gate, not "looks right") |
| C3 | Preserve the scripted sweep as a viz2 export (reuse `SunSweep.run_sun_sweep` untouched for dataset generation) | none (reuse) | Existing sun_sweep manifest run still green on the new scene |

### Phase D — Rock dispersion from real statistics

| Task | Change | File(s) | Verification |
|---|---|---|---|
| D1 | **Spatial-k Golombek field over the real DEM**: `stewie/terrain/rockfield.py` — per-cell k from the sourced envelope (background `BOULDER_K_BACKGROUND=0.005`, ejecta ramp to `BOULDER_K_EJECTA=0.20`, `constants.py:534-539`) keyed to REAL DEM features (crater rims/ejecta from the LY-05 curvature + slope producers on the actual 1 m heightfield — no invented geology); then bin-wise Poisson sampling reusing `sample_boulders`' inversion math (`procgen.py:299-328`) per k-stratum, deterministic via `coord_seed` (`docs/dem_terrain_contract.md` §3) | new file + scene metadata clasts[] | `[REQ:]` test: (1) recovered cumulative fractional area per stratum matches F_k(D) within Poisson tolerance; (2) determinism: same seed+window → byte-identical clast list; (3) abundance in the Bandfield-anchored envelope |
| D2 | Height/shape realism: clast heights follow the shipped h-diameter geometry; record in the manifest that h/d validation traces to Demidov & Basilevsky 2014 via the nac_shadow reproduction (`nac_boulder_repro.py:5-11`); buried_frac stays the honest [UNKNOWN] U(0.1,0.7) (`constants.py:541-546`) — no fabricated distribution | manifest/provenance fields | Test asserts the manifest carries the citation + [UNKNOWN] tag verbatim |
| D3 | Render + interact: clasts render through the existing clast/boulder path (`boulder_manifest.gd` copies scene clasts verbatim, L8-14); viz2 threads clasts into `drive_step(clasts=…)` so ride-over/blocking is physical (`drive.py:187,222-224`) | `viz2_root.gd`, daemon | Capture: rocky vs sparse k renders visibly different fields; drive into a >wheel-radius rock → pose blocked/ridden per `conform_pose` clast logic |
| D4 | (Stretch, real-data) Haworth-local calibration hook: IF a Haworth-area NAC ortho is fetched (§4 BLOCKED item), run the `nac_boulder_repro` detector to produce a measured local density and clamp k to it | `benchmarks/nac_shadow/` reuse | Only activates with the real ortho on disk; skip-clean otherwise |

### Phase E — Dig + before/after difference drape

| Task | Change | File(s) | Verification |
|---|---|---|---|
| E1 | Dig interaction: viz2 `dig`/`dump` actions send footprint ops to the daemon → `WorkSite.flatten/.dump` under the rover's drum footprint (`worksite.py:242,256`); FORGE excavation-resistance/energy debits from `ipex_specs` (dig 4151 J/kg, the `worksite_env.py:60-72` grounding) shown on the HUD battery bar | daemon + HUD | Pytest: dig N kg → conserved mass check (grid+inventory invariant); HUD energy decreases by the grounded J/kg |
| E2 | Signed difference field in-Godot: daemon keeps the session-start base heightmap; streams a `diff = h_now − h_base` window as one more rf32 texture; new `falsecolor_diff.gdshader` (diverging ramp, zero transparent) as a toggleable drape — the in-Godot twin of the shipped LY-07 server drape (`PRD.md:721`) | new shader + `terrain.gd` wiring (additive mode) | Capture after a scripted dig+dump: cut region reads negative-color, berm positive; numeric: max cut depth in the texture == authority `max_cut_m` |
| E3 | Evidence tie-in: on "end session", emit `RegolithVolumeEstimate` via `leap/volume_evidence.py:15-35` and (server up) register the run so the LY-07 `changed_terrain` drape + `/world/point` show the SAME dig on the /ide map | daemon | Pytest: estimate's conserved mass == WorkSite ledger; cross-surface check: `/world/point` depth == Godot diff texture value at the same cell |

### Phase F — Path/traversability analysis vs rock height/size + slope

| Task | Change | File(s) | Verification |
|---|---|---|---|
| F1 | **NEW costmap layer `rock_hazard`**: rasterize the D1 clast list — per-cell max exposed rock height h = 2r(1−buried_frac); cost ∝ h/`OBSTACLE_HEIGHT_M`; impassable where h > the sourced 0.075 m limit (`ipex_specs.py:79` [SCHULER24]); registered in `compose` with its blocking reason like the existing 12 (`costmap_layers.py:1-29`) | `lode/costmap_layers.py` (additive) | `[REQ:]` test: a 0.3 m rock cell blocks with reason "rock_hazard"; a 0.05 m rock costs but passes; existing `test_costmap_layers.py` unchanged-green |
| F2 | Plan over it: `mission_planner.plan()` (`mission_planner.py:223`) on the 1 m site with the rockfield → route bends around rock clusters + steep slope; viz2 draws the returned path polyline on the terrain (order-frame, §2c) | daemon glue + `viz2_path.gd` | Pytest: with rocks the route length > without, and no path cell violates the mask; capture: path visibly detours around a rock cluster |
| F3 | Live what-if: sun sliders (Phase C) re-shade; a "replan" action re-runs the costmap with current keep-outs/diff terrain (post-dig surface — the as-built h, so digging changes traversability) | daemon | Test: dig a trench across the old path → replan routes around it (the terrain-memory loop, observed numerically) |

### Phase G — Cross-site DEM compare

| Task | Change | File(s) | Verification |
|---|---|---|---|
| G1 | Site switcher in viz2 over every bundled site (the 11 dirs + `haworth_sfs_2km_1m` + ad-hoc picks via `resolve_adhoc_bundle` at 118 m, `STEWIE_more_DEMs_plan_2026-07-09.md` §1.4) — same loader, different bundle_dir | `viz2_root.gd` | Capture per site: 3 spot-checked sites render with correct relief ranges (vs each `metadata.json height_range_m`) |
| G2 | **Cross-site comparison producer** (backend, not Godot): `dart/dem_site_compare.py` — per-site stat table (slope median/RMS via the LY-05 gradient producers, roughness, height range, cell size, provenance/citation from bundle metadata) + where footprints overlap (currently: NONE of the curated 5 m bundles overlaps the 1 m SfS — verified §1 row 3 — so the first real residual pair needs either a 5 m re-crop over the SfS footprint from `Haworth_final_adj_5mpp_surf.tif` (on host, `/mnt/projects/datasets/lola_5mpp/`) or the `NAC_DTM_SHACKRDGE02` upgrade in §4) a 1 m-vs-5 m residual map — the honest resolution-difference exhibit | new file + a `/dem/compare` router read | `[REQ:]` test on real bundles: table rows == on-disk bundles; residual only offered where footprints truly overlap (else explicit refusal) |
| G3 | Companion uncertainty layers (the DEM_CROSSREF §c "DO FIRST/SECOND" items): `--aux toterr=…,ldec=…,slp=…,slperr=…` support in `build_from_dem.py`, cropped with the identical window; exposed as viz2 drapes + compare inputs | `scripts/build_from_dem.py`, bundle metadata `fields` | Ingest Haworth `_toterr/_ldec` (requires the raw companion tifs — see §4 BLOCKED), assert grid alignment is exact-by-construction; drape renders with a real ramp |
| G4 | Paper panel: viz2 "About this DEM" pane reads each bundle's `dem_provenance.citation` verbatim (`metadata.json`, Barker 2021 + Mazarico 2011 confirmed present) + the §5 product table (static content generated FROM the crossref doc, not hand-retyped) | small generator script | Rendered pane text == the metadata citation strings (test string-compares) |

Phase order rationale: A before B (need the site to drive on); B is the keystone (everything after
reads its telemetry); C and D are independent after B (parallelizable); E needs B (dig verbs on the
daemon); F needs D (rock layer) + E (as-built replan); G is independent of C-F and can run any time
after A.

---

## §4 Real-data + provenance inventory

**On disk, verified this session (path — content — provenance):**

| Asset | Verified facts | Citation / license (from repo provenance) |
|---|---|---|
| `code/datasets/lunar_dem/Lunar_LROnac_Haworth_sfs-dem_1m_v3.tif` (+ byte-twin `data/gis/raw/Haworth_1m_sfs.tif`) | 11660×12060 @ 1.0 m float32, polar stereo R=1737400, X∈[−40120,−28460] Y∈[83260,95320] (rasterio) | LRO NAC photoclinometry (SfS) DEM 1 m, USGS Astrogeology; public domain (US Gov) — `dart/dem_sources.py:168-174` |
| `samples/lunar_dem/` — 11 bundles @ 10 km/5 m (haworth, shackleton_rim, nobile_rim1/2, connecting_ridge, de_gerlache_rim, de_gerlache_kocher, leibnitz_beta, malapert_massif, peak_near_shackleton, shoemaker) | dir listing; haworth metadata read: 2000² @5 m, bounds X[−52900,−42900] Y[95400,105400], citation string present | Barker et al. 2021 (PSS 203:105119) + Mazarico et al. 2011 (Icarus 211:1066); US-Gov work treated public-domain, honestly caveated — `THIRD_PARTY.md:80-85` |
| `data/gis/raw/Site{01,04,06,07,11,20,23,42}_surf/_slp.tif`, `ldem_75s_120m.img/.lbl` | dir listing | PGDA Product 78 site tiles + LOLA 75S 120 m polar DEM (PDS label present); same US-Gov basis |
| `/mnt/projects/datasets/lola_5mpp/` — raw `Haworth/DM2/Shoemaker/Site*_final_adj_5mpp_surf.tif` | dir listing | PGDA Product 78 raw source tiles |
| `/mnt/projects/datasets/argus_dem_nav/lunar_dem/Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif` | ls; wired into the plan-anywhere resolver (`STEWIE_more_DEMs_plan_2026-07-09.md` §1.4) | Smith et al. 2010 lineage per crossref; public domain |
| `benchmarks/nac_shadow/fixtures/` — 9 real NAC ortho/DTM crops (Messier, Reiner, Giordano Bruno, Apollo 17 Station 6) | dir listing, 2.4 MB | LROC PDS RDR (im-ldi mirror URLs in `nac_boulder_repro.py:65-88`, `nac_twosun.py:42-63`); US-Gov |
| EZ-RASSOR meshes `stewie/godot/assets/*.glb` | dir listing; conversion + license analysis in `docs/ezrassor_assets.md` | **MIT with attribution** (UCF/FSI/NASA); MIT notice must ride along (`ezrassor_assets.md:17-23`); `extra_models/` art explicitly excluded (L25-33) |
| Rock/crater statistical constants | `constants.py:202-215,524-546,398-413,552-557` | Golombek & Rapp 1997; Golombek 2003; Bandfield 2011; Xiao & Werner 2015; Minton 2019; Ruesch & Woehler 2021; ChaSTE (Durga Prasad 2026 / Mathew 2025) — all tagged [FIXED]/[CALIB]/[UNKNOWN] in-file |

**MISSING — BLOCKED items (say so, don't invent):**

1. **Haworth companion uncertainty rasters** (`Haworth_final_adj_5mpp_toterr/_ldec/_slperr.tif`) —
   not on disk (not in `data/gis/raw/` or `/mnt/projects/datasets/lola_5mpp/` listings). G3 is
   **BLOCKED, need the PGDA Product-78 Haworth companion downloads** (same directory as the surf
   tile; no download without an explicit go, standing rule).
2. **A NAC ortho covering the Haworth work area** for measured local boulder density (D4) — the
   nac_shadow fixtures are mare/Apollo sites, not Haworth. **BLOCKED, need a real Haworth-area NAC
   map-projected ortho** (and low-sun geometry) before any "measured Haworth rock abundance" claim;
   until then the rockfield stays honestly [CALIB] on Bandfield/Golombek envelopes.
3. **Live Chrono backend (PX-03)** — `tier3_chrono` is ledger-listed, `validated=False`, not
   selectable (`models.py:155-156,176`; registry `backend.py:54-62`). B5's advisory lane needs the
   user-local micromamba PyChrono env validated on this host (project memory
   `infra_stewie_convergence_toolchain`; PyPI `pychrono` is a typosquat — never pip-install it).
   Until then Chrono appears ONLY as the greyed, fail-closed picker entry.
4. **Overlap pair for the 1 m-vs-5 m residual** (G2) — no curated 5 m bundle overlaps the SfS
   footprint (verified §1 row 3). Needs the cheap re-crop of the on-host 5 m Haworth source over
   the SfS window (no download; one `build_from_dem.py` run) — planned inside G2, flagged here so
   the residual exhibit is not assumed free.

---

## §5 Research-paper summary (every citation verified present in the repo)

**DEM products** (all from `/mnt/projects/stewie/design/DEM_CROSSREF_2026-06-11.md`, table L17-24 +
§a/§b, plus bundle metadata / `THIRD_PARTY.md:80-85`):

| Product | Paper (as cited in-repo) | What viz2 uses it for |
|---|---|---|
| PGDA Product 78 — 5 m/px south-pole site LDEMs | Barker et al. 2021, *Planet. Space Sci.* 203:105119 (+ Mazarico et al. 2011, *Icarus* 211:1066 in every bundle's `dem_provenance.citation`) | The 11 curated 5 m bundles; error budget: RMS Z ~0.30-0.50 m, RMS slope ~1.5-2.5°, per-pixel `toterr`/`ldec` companions (crossref §b) |
| PGDA Products 81/90 — polar mosaics 10-240 m + `*_ADJ_ERR` | Barker et al. 2023, *Planet. Sci. J.* 4:183 | Regional context / future approach planning; only published uncertainty at those scales |
| SLDEM2015 (±60°, 512 ppd) | Barker et al. 2016, *Icarus* 273:346 | Explicitly EXCLUDED from the polar pipeline (coverage stops 60°S; 3-4 m vertical accuracy) — contrast only |
| ASP Shape-from-Shading method | Alexandrov & Beyer 2018, *Earth & Space Sci.* 5:652 | The method behind SfS DEMs; expected SfS error ~1-2 m vs ground truth (crossref §b) — the honesty label on the 1 m Haworth base |
| LuNaMaps 30 m SfS strip (PGDA Product 92) | Bertone, Barker & Mazarico 2023, Zenodo 10258683; 2026 SfS DEMs Zenodo 10.5281/zenodo.17954508 are **CC-BY-4.0, license-segregated** (`THIRD_PARTY.md:87` region) | Reference-only; never vendored beside the CC0-treated tiles |
| LOLA global LDEM 118 m | Smith et al. 2010 lineage (crossref §2 table) | The plan-anywhere 118 m fallback resolver |

**Rock size-frequency / boulder statistics** (verified in `stewie/specs/constants.py` and
`benchmarks/nac_shadow/`):

- **Golombek et al. 2003 (LPSC XXXIV)** — F_k(D)=k·exp(−q(k)D), q(k)=1.79+0.152/k
  (`constants.py:204-207`); the sampler's core (`procgen.py:292-297`).
- **Golombek & Rapp 1997**, doi:10.1029/96JE03319 (`constants.py:526-527`) — the SFD family basis.
- **Bandfield et al. 2011** (Diviner rock abundance <1% background) — anchors the sparse polar
  background k (`constants.py:528-529,534`).
- **Bernhardt/Boazman 2022, Watkins 2019, Bickel & Kring 2020** — per-region areal densities,
  honestly tagged SECONDARY-SOURCED in-file (`constants.py:531-533`); cross-checked vs USGS LROC
  NAC Boulder DB v1 (same lines).
- **Ruesch & Woehler 2021**, arXiv:2109.00052 — buried-fraction direction only; the numeric
  distribution stays [UNKNOWN] (`constants.py:541-546`).
- **Demidov & Basilevsky 2014**, doi:10.1134/S0038094614050013 — h/d = 0.60±0.03 over 445 rocks;
  reproduced on real NAC shadows with a truth firewall (`nac_boulder_repro.py:5-21,94-100`), plus
  the Apollo 17 "House Rock" ~6 m absolute anchor (L12-15,71-88).
- Crater side (for the ejecta/k field): **Neukum/Ivanov/Hartmann 2001** production coefficients
  (`THIRD_PARTY.md` cratermaker note), **Xiao & Werner 2015** equilibrium + **Minton 2019** mare
  lower bound (`constants.py:393-413`), **Pike 1977** fresh-crater morphometry (`constants.py:221-224`),
  **Stöffler 2006** rim/diameter (`constants.py:518-520`).

Honesty note: the task brief suggested "Golombek/**Cintala**-style CFA" — **Cintala is not cited
anywhere in this repo** (grep). The plan cites only what the repo actually grounds; if a
Cintala & McBride-style count-density comparison is wanted, that is new literature work, not a
citation to copy forward.

---

## §6 Risks / explicitly deferred

**Risks**

1. **Interactive-loop latency** (B2/B3): daemon step + socket round-trip must stay ≪ 66 ms. The
   authority is sub-ms/step on 256² windows (repo record), but `four_wheel_pass` on a 2000² @1 m
   state + texture re-upload is unmeasured — B3's verification includes a frame-time budget capture;
   fallback is a smaller live window (the `terrain.gd` rover-window pattern, L26-27, already crops).
2. **2 cm fine layer at 1 m base**: the frozen contract's fine machinery was built for 5 m→2 cm
   (`dem_terrain_contract.md:6-14`); a 1 m base changes the octave stack (`base_cell_class` in
   `coord_seed`, contract §3). Risk: seam artifacts at base-cell boundaries; the contract's
   `coarsen(fine)==base` acceptance (§7) is the gate — run it at 1 m before trusting the visuals.
3. **SfS DEM veracity at rock scale**: SfS reconstructs albedo-entangled relief; sub-2 m "bumps" in
   the 1 m product are not certified boulders (Alexandrov & Beyer error 1-2 m). D-phase rocks are
   therefore STATISTICAL (sourced SFD), never "read off the DEM" — stated in the manifest.
4. **Two copies of the same 562 MB SfS tif** (`code/datasets/` + `data/gis/raw/`) — drift risk;
   pick `code/datasets/...` as canonical in A2 and note the twin for a later dedupe (name-and-leave).
5. **GDScript kinematic drive remains** beside the daemon-driven viz2 (`drive_controller.gd`) — an
   operator could confuse the tiers; viz2 HUD labels its authority (`tier2_numpy`, conserved) and
   the old mode keeps its "prototype" banner.
6. **Godot editor-vs-headless input** (A5): gamepad verification is inherently an on-host,
   human-in-the-loop observation; the headless tier only covers action-injection, so A5 carries a
   named operator check.

**Explicitly deferred (not in this plan's scope)**

- Registering a **live Chrono producer** as a selectable backend (PX-03) — blocked per §4; only the
  advisory display lane (B5) is planned, and only when the PyChrono host env is validated.
- **ROS2/Gazebo lowering** of the viz2 loop (RT-00/RT-03 lanes) — the daemon protocol mirrors
  `stream.py`'s seq/ack shape to keep that door open, nothing more.
- **Whole-tile 10 km @ 1 m** bundle (10000² grid) — needs the TileMosaic streaming path
  (`dem_terrain_contract.md` §5) in the daemon; the 2 km crop is the deliberate first cut.
- **Multi-rover / fleet** in viz2 (fleet layers exist in LODE, `costmap_layers.py:19` reservation) —
  single-vehicle first.
- **QWC2 /ide embedding of viz2** (a Godot-in-browser or stream panel) — the /ide already has the
  GW-11 Three.js validate view; viz2 stays a native operator app for now.
- Downloading DM1/LM7 (the two missing official Artemis III tiles) — tracked in
  `STEWIE_more_DEMs_plan_2026-07-09.md` §5.2, unrelated to viz2's critical path.
