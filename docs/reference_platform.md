# STEWIE platform reference

Reference manual for the `code/` monorepo (state as of 2026-06-10). Everything below is read
from the code; file paths are repo-relative. STEWIE = Surface Terrain Engineering & World-model
Integration Environment (McCardle & Storey). The public subsystem ↔ codebase mapping of record
is `PRD.md` §16.

---

## 1. Architecture — the monorepo packages

Top-level layout: one installable distribution (`pyproject.toml`, `name = "stewie"`) containing
the `stewie/` platform package plus four subsystem packages `dart/`, `lode/`, `leap/`, `forge/`.
Tests live next to the modules they test (`test_*.py` in-package).

| Package | Subsystem role | One-line ownership |
|---|---|---|
| `stewie/physics` | platform | conserved Tier-2 terrain authority + terramechanics |
| `stewie/terrain` | platform | DEM I/O, procedural generation, scenes, tiled LOD |
| `stewie/twin` | platform | versioned observed-terrain twin, runtime packet, backup |
| `stewie/specs` | platform | constants, IPEx/vehicle/body registries, config overlay, solar |
| `stewie/envs` | platform | Gymnasium RL environments + registration |
| `stewie/server` | platform | FastAPI server, GIS layers, sessions, object store, auth |
| `stewie/godot` | platform | Godot render/sensor sidecar (GDScript + shaders) |
| `stewie/eval` | platform | gates, metrics, role isolation, validation artifacts |
| `stewie/bridge` | platform | packet/frame/telemetry contracts, dataset ingest |
| `stewie/sensors` | platform | consumer-side proprioception types + derived odometry |
| `stewie/runtime` | platform | persistent shared runtime process (Unix-socket seam) |
| `dart/` | DART (perception) | "What does the world look like?" |
| `lode/` | LODE (operations) | "What should happen next?" |
| `leap/` | LEAP (earthmoving) | "How should we move the regolith?" |
| `forge/` | FORGE (infrastructure) | "What are we building?" (namespace only — see below) |

**`stewie/physics`** — the deterministic, mass-conserving, numpy-only Tier-2 terrain authority.
`column_state.py` is the per-column data model (spec §5.3/§6; INTERFACE.md §4) including the
conserved `sinter()` primitive; `terramechanics.py` is the load-bearing Bekker pressure-sinkage
solve; `slip.py` the slip-sinkage ladder (traction budget, Janosi-Hanamoto, entrapment/recovery);
`drive.py` the closed-loop `cmd_vel` drive; `rover.py` wheel-pass rut carving; `worksite.py` the
streaming coarse-base + rover-following fine-window execution engine; plus stability (SSA tip
margin), sandpile relaxation, quadtree refinement, the RASSOR drum mass-inference model
(`rassor_mass_model.py`), and validation self-tests.

**`stewie/terrain`** — terrain data in and out. `dem_io.py` is the windowed/memmap base reader on
top of the frozen `io_fields` on-disk contract; `procgen.py`/`procgen_csfd.py`/`procgen_seed.py`
generate calibrated procedural lunar terrain (variance-anchored fbm, crater SFDs); `scenes.py`
builds/exports the sample scenes; `tiles_mosaic.py` is the demand-driven, bounded, evictable
corridor LOD over a global-frame tiled base.

**`stewie/twin`** — the authoritative world-state record. `versioned.py` is the versioned,
event-sourced observed-terrain twin (journal-durable, hash-chained history; STEWIE P2.2);
`world_model.py` the coherent world-model surface; `backup.py` snapshot retention + off-host
replication (PRD W-2/W-3); `proprioception.py` producer-side IMU/wheel sensor generation;
`runtime_packet.py` the canonical single-clock runtime packet (P0-3 / G1.A6); `io_fields.py`
atomic field I/O.

**`stewie/specs`** — the sourced numbers and registries. `constants.py` (Tier-2 physical
constants + calibration parameters, honesty-tagged), `ipex_specs.py` (IPEx flight-system
parameters, "real-data-sourced (no fabricated values)"), `bodies.py` (per-planet terramechanics),
`vehicles.py` (vehicle/power/tool registries, PRD O4), `vehicle_twin.py` (one pluggable record
per vehicle instance — the ARGUS spine), `arm_state.py` (joint model), `solar.py` (sun az/el from
mission time; SPICE-backed), `sites.py` (site registry), `config.py` (the PRD N15 externalized
config overlay), `profiles.py`/`system_profile.py` (sensor-profile validation).

**`stewie/envs`** — the RL suite. `rover_env.py` (`RoverSimEnv`, drive-to-goal over the
slip-aware authority), `active_perception_env.py` (next-best-view mapping: information gained
per joule), `cem.py` (pure-numpy cross-entropy-method trainer, no RL library),
`registration.py` (registers the envs with Gymnasium under the `Dust/` namespace — e.g.
`gym.make("Dust/RoverDrive-Moon-v0")`; idempotent, no-op without gymnasium). Importing `stewie`
triggers registration.

**`stewie/server`** — the HTTP layer (section 2). `server.py` (the FastAPI app), `auth.py`
(section 6), `gis_layers.py` (computed rasters over the real Haworth DEM), `map_layers.py`
(layer registry), `session.py` (operator/director training sessions, STEWIE P22/B3),
`objects.py` (mission + custom-structure object store), `hexviz.py`, `gen_bodies_json.py`,
`fetch_assets.py` (checksum-verified LOLA DEM fetch), plus the static front-end (`index.html`,
`bodies.json`, fonts, icons, sample missions).

**`stewie/godot`** — the render + sensor model sidecar (GDScript/shaders, not Python).
`sidecar.gd` is the layer-toggle headless render CLI; render-only consumer of the frozen state
fields ("Godot = renderer + sensor model only; it never authors physics"). Cameras
(`camera_rig.gd`), AprilTag generation, drive controller, terrain/dust/distortion shaders,
capture sequencing, and `render.sh`/`render_layers.sh` entry scripts.

**`stewie/eval`** — gates and evidence (section 5). `gates.py` (G1/G2 validation), `metrics.py`
(gauge-aware ATE/RPE trajectory metrics), `roles.py` (file-layer permission isolation:
produce/estimate/evaluate), `g1_pipeline.py` (isolated evidence pipeline),
`katwijk_baseline.py` (wheel+IMU dead-reckoning on the real Katwijk Traverse-1),
`depth_truth.py` (independent ray-cast per-pixel depth truth), and the dated artifacts under
`stewie/eval/validation/`.

**`stewie/bridge`** — the contracts between producer, estimator, and operator. `dustgym_io.py`
(strict runtime/evaluation packet bridge: truth physically separate from `runtime_sensors.json`),
`runtime_io.py` (`parse_canonical`, the strict single-clock packet consumer + truth firewall),
`proprioception_io.py` (schema `proprioception/1.x` parsing/validation), `frames.py` (THE sim ↔
REP-103 frame mapping, the only conversion site), `telemetry.py` (mission-link constraint model:
downlink token bucket, seeded drop, uplink latency; STEWIE P21/B2), `katwijk_io.py` (ESA Katwijk
Beach dataset ingest — the real-world G1 leg).

**`stewie/sensors`** — consumer-side proprioception types and slip-blind derived odometry
(`imu_wheel.py`). Ownership split: the producer (`stewie/twin/proprioception.py`) generates;
this package parses, time-syncs, and derives.

**`stewie/runtime`** — the persistent shared runtime (section 4). `process.py` +
`test_process.py` only.

**`dart/`** — Decision-support perception: stereo depth (SGBM) and VO, feature tracks,
landmarks, pose graph, map-relative localization (`localization.py`: scan-to-DEM registration
against the prior LOLA map — "not SLAM-from-scratch"), 2.5D mapping, rock detection/taxonomy,
hazard/obstacle maps (Stanford-LAC-style cost grids), shadow extraction/height/prediction,
illumination/horizon/visibility, solar observation, DEM import/anchor/cross-checks, camera-rig
extrinsics, teach-and-repeat, AprilTag dock pose.

**`lode/`** — Operations: `mission_planner.py` (the SimCity-Space build planner: cut-fill
balancing, route optimization, battery-aware recharge, multi-vehicle, plan IR, 2-3 page
mission-control PDF/markdown report), `autonomy.py` (closed-loop belief-state executive — the
AutoNav "OD" analog), `adaptive_planner.py` (self-learned slip-energy re-pricing),
`scheduler_env.py` (multi-objective construction scheduling), `zones.py` (hard, non-overridable
NO_GO/NO_EXCAVATION/HAZARD/PROTECTED refusal gates), path tracking, PSR supervisor, rock costs,
playthrough, actions.

**`leap/`** — Earthmoving: `structures.py` (composite structures → mass-balanced cut/fill
orders, volume-balanced so it holds on any body), `challenge.py` + `challenge_runner.py`
(declarative challenge schema, deterministic realize/run/scorecard), `worksite_env.py` (RL
controller over the WorkSite seam), `skill_env.py` (skill-macro construction RL),
`terrain_target_env.py` (goal-conditioned terrain matching).

**`forge/`** — currently an **empty namespace package** (`__init__.py` is zero bytes; only
`py.typed` beside it). Per PRD §16.1 FORGE's existing code lives elsewhere for now: the gated
sinter authority (`stewie/physics/column_state.py::sinter`, gated by
`constants.SINTER_ENABLED=False`) and the I11 as-built acceptance (`validate_plan`). The named
gap is a typed interface + certified-record provenance store.

Also at `stewie/` top level: `lander.py` (to-scale CLPS-class lander geometry for the map;
Nova-C documented body 1.57 m × ~4.0 m, footprint ~4.6 m approximate).

---

## 2. The HTTP API (`stewie/server/server.py`)

FastAPI/uvicorn app, default bind `127.0.0.1:8770` (`stewie-serve`; deprecated alias
`dustgym-serve`). The Docker deployment exposes the UI on host `:8000` via nginx →
`backend:8770` (`deploy/compose.yml`). Error envelope is `{ok: false, error: ...}` everywhere
(validation errors are returned as 400, not FastAPI's 422); two catch-all routes keep unknown
GET/POST paths in the same envelope at 404. POST/PUT/PATCH bodies are capped at 4 MiB
(`STEWIE_MAX_BODY_BYTES`); build queues are capped at 1000 orders; access logging + in-process
`/metrics` counters key on matched route templates (bounded, not attacker-controlled paths).

**Auth column**: `key` = `Depends(require_auth)` (section 6) — enforced only when
`STEWIE_API_KEY`/`DUSTGYM_API_KEY` is set, otherwise the identity is `"dev-open"`. `open` = no
dependency. 52 functional endpoints (counting `GET /` + `GET /index.html` as one) + 2 catch-alls.

### Planning

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/plan` | key | Plan a mission: cut-fill balance, route, validate, render the PDF/MD report; returns totals, validation, timeline, endurance, autonomy + perception blocks, machine-executable plan IR, provenance. `terrain_source` flags `haworth_dem` vs `flat_fallback` (never silently degrades). |
| POST | `/compare` | key | Run the algorithm comparison (`compare_algorithms`) for a mission/objective. |
| POST | `/structure` | key | Decompose a named structure (Landing Pad / Haul Road / Berm / ...) at (x, y) into mass-balanced cut/fill orders. |
| POST | `/sense` | key | Drum-fill sensing (ICE-RASSOR): true mass → motor-current observable → inferred mass + offload decision; `noise_frac` toggles seeded noise (0 = off). |
| POST | `/render` | key | Crop a Haworth window at picked (u, v), plan a flatten, render BEFORE/AFTER in Godot; 503 if the Godot binary is absent. Slow. |
| POST | `/profile` | key | Save a planning profile (full config snapshot) under a slug; atomic write. |
| GET | `/profiles` | open | List saved profile slugs. |
| GET | `/profile/{name}` | open | Load a saved profile by slug. |

### Layers / DEM / GIS

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/layers` | open | Selectable map layers for the navigation UI (vector + raster defs). |
| GET | `/layers/legend` | open | Legend values FROM the physics (hazard thresholds, slope ramp, shadow/PSR text) — the UI never hardcodes a threshold. |
| GET | `/layers/raster/{kind}.png` | open | Computed GIS raster over the real Haworth DEM (slope/hazard/shadow/PSR); `mission_t_s` puts the sun under the SPICE solar authority, `sun_el`/`sun_az` are the manual override. |
| GET | `/layers/globe/{kind}.png` | open | The geographic globe drape (server-reprojected). |
| GET | `/layers/globe/{kind}/bbox` | open | The drape's true selenographic bbox. |
| GET | `/dem/georef` | open | Haworth tile globe footprint (selenographic corners) for the cockpit overlay. |
| GET | `/dem/site_xy` | open | Selenographic lat/lon → Haworth site-frame (x, y) m (pyproj, true CRS; 503 if pyproj absent). |
| GET | `/dem/{name}` | open | Bundled DEM previews (`hillshade.png`, `height.png`); 404 when the bundle is absent (e.g. wheel install). |
| GET | `/sites` | open | The site registry (Haworth imported; Artemis III candidates honest about data state). |

### Missions / structures (object store)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/missions/{name}` | key | Save a named mission (full authoring state) — logged to the event history. |
| GET | `/missions` | open | List saved missions. |
| GET | `/missions/{name}` | open | Load a mission document. |
| DELETE | `/missions/{name}` | key | Delete a mission — logged. |
| POST | `/structures/custom/{name}` | key | Save a custom structure template — logged. |
| GET | `/structures/custom` | open | List custom structure templates. |
| GET | `/structures/custom/{name}/expand` | open | Expand a template at (x, y) into queue-ready orders. |
| DELETE | `/structures/custom/{name}` | key | Delete a template — logged. |
| GET | `/sample_missions` | open | List the bundled intern sample missions. |
| GET | `/sample_mission/{name}` | open | Serve a bundled sample mission (allowlisted names only). |

### Auth

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/auth/config` | open | Whether operator login is enabled (`STEWIE_OPERATOR_LOGIN`). |
| POST | `/auth/login` | key | Email + API key → 12 h HMAC identity token; email must be whitelisted; 403 when the operator-login kill switch is off. |

### Admin

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/admin/twin/snapshot` | key | Snapshot the twin to `data_dir/snapshots`. |
| POST | `/admin/twin/retention` | key | Apply the snapshot retention policy. |
| POST | `/admin/backup/replicate` | key | Replicate `data_dir` to `STEWIE_BACKUP_DIR` (default `data_dir/replica`). |
| POST | `/admin/gates/validate` | key | Re-run the dated G1/G2 validation and compare against the frozen 2026-06-07 artifact byte-for-byte (section 5). |

### Events / sessions

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/events` | open | Newest-first audit history (who did what when; actor = the auth identity), from append-only `events.jsonl`. |
| POST | `/session/start` | key | Start an operator/director training session (runs the real closed-loop executive once). |
| GET | `/session/{sid}/operator` | open | Operator-trainee view — open BY CONTRACT (B3): only telemetry-delivered, truth-denylisted data. |
| GET | `/session/{sid}/debrief` | key | Director debrief view (full state; `fast_forward` supported). |
| GET | `/session/{sid}/summary` | key | Persist + serve the session summary as markdown. |

### Twin

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/twin/resync` | key | Apply an observed-height patch (heights + origin + provenance) to the versioned twin → new version. |
| GET | `/twin/version` | open | Twin version, hash-chain validity, event history. |
| GET | `/twin/cg` | open | Live center-of-gravity + tip margin from arm posture + drum loads (SSA model; gauge = the documented IPEx skid-steer track 0.5207 m [WHEELTEST Eq.1]; wheelbase 0.40 m [ASSUMPTION — no documented IPEx wheelbase]). |

### Misc / static / ops

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/` and `/index.html` | open | The cockpit front-end. |
| GET | `/bodies.json` | open | Per-body terramechanics + IPEx energy block (generated from the .py sources). |
| GET | `/reports/{name}` | open | Generated plan reports (basename-only — no traversal); TTL-swept (`STEWIE_REPORTS_TTL_S`, default 86400 s). |
| GET | `/figures` | open | List validation PNGs (engineer pane); keys are the allowlist. |
| GET | `/figure/{key:path}` | open | Serve a validation PNG by allowlisted key. |
| GET | `/fonts/{name}` | open | Vendored brand fonts (Orbitron, OFL); no CDN at runtime. |
| GET | `/icons/{name}` | open | The app icon set. |
| GET | `/config` | open | Runtime config overlay state (PRD N15). |
| GET | `/config/full` | open | Organized one-call Config-pane state: server, auth FLAGS (never the key — values matching key/token/secret are `[REDACTED]`), data holdings, overlay. |
| GET | `/healthz` | open | Liveness: status, version, uptime. |
| GET | `/metrics` | open | Request counters by status and by matched route template. |
| GET/POST | `/{path:path}` | open | Catch-all 404 in the `{ok:false,error}` envelope. |

Startup hook: a daemon thread pre-warms the five globe products (dem/slope/hazard/illumination/
psr; the PSR sweep measured 44 s cold) so the first click finds them ready.

---

## 3. The map / layer stack

Authoritative reference: **[`docs/map_reference.md`](map_reference.md)** (current as of
2026-06-10). Summary only — do not duplicate from here:

- **Three render tiers**: live NASA Trek tile basemaps (8 products, tile-verified); the in-repo
  Haworth 5 m LOLA-derived DEM drape (raw-heightmap hillshade → server-side reprojection →
  Cesium single-tile drape in its true bbox); and computed work-area rasters
  (slope/hazard/shadow/PSR) from the same heightmap over the 640 m work-area bbox, with legends
  served by `/layers/legend` from the physics constants.
- **Coordinate truth**: the globe is deliberately WGS84-shaped (Cesium custom-globe limitation),
  but drape bboxes carry true selenographic values via the IAU_2015:30135 inverse projection;
  the scale bar is corrected by `R_body / R_earth`; `/dem/site_xy` runs server-side on the true
  CRS via pyproj, independent of the globe shape.
- **The slope hierarchy** (all sourced): penalty >15° [SCHULER24 ConOps], hard no-go >20°
  [WHEELTEST demonstrated incline], empirical ceiling ~30° (RASSOR Gen-1 slip-avalanche
  failure), closed-loop routing default 25°. 40° has no support in the traced record.
- **Live services**: NASA Trek tiles, NASA GIBS (Earth), SPICE/NAIF generic kernels (cache at
  `$STEWIE_SPICE_KERNELS`; WebGeocalc as the manual cross-check oracle), LOLA PDS lineage.

---

## 4. The runtime seam (`stewie/runtime/process.py`)

The persistent shared runtime — STEWIE P20 core / G1 blocker #1. One long-lived
`RuntimeProcess` owns the conserved world (a `ColumnState` built the same way the envs build
theirs, plus a `VehicleTwin`) and serves a **Unix-socket JSON-lines seam**: each request is one
JSON object on one line; the response is one JSON line back. The world OUTLIVES clients (the G1
persistent-runtime criterion); request handling is single-threaded by design — the authority is
the serialization point. The ROS bridge (B1) attaches later through this same seam.

**Roles and verbs** (every request carries `role` + `cmd`):

| Role | Verbs | Notes |
|---|---|---|
| `drive` | `twist`, `pose`, `checkpoint`, `restore`, `set_thermal` | the ONLY role allowed the mutating verbs (`_MUTATING = {twist, checkpoint, restore, set_thermal}`) |
| `produce` | `pose`, `packet` | `packet` emits the STRICT canonical runtime packet (`dustgym_runtime/1.0`, single `sim_monotonic` clock), accepted by `stewie.bridge.runtime_io.parse_canonical` |
| `estimate` / `evaluate` | `pose` only here | their file work stays in `stewie.eval.roles` (permission-isolated produce → estimate → evaluate) |

**What `twist` does**: steps the slip-aware drive loop (`physics.drive.drive_step`), advances
sim time, feeds the REAL producer models from the *achieved* motion (the IMU sees the true yaw
rate; slip stays hidden inside the encoder model), and integrates pack draw from the twin's
grounded drive power. Returns pose + slip + a SHA-256 prefix of the conserved mass field.

**The packet**: channels `imu`/`wheel` (buffered samples drain on emit — no double-reporting),
`joints` (UNAVAILABLE), `power` (real BMS: SoC from integrated draw against the IPEx 12S/30Ah
pack, instantaneous draw), `camera` (from an attached frame store of REAL rendered frames —
intrinsics/baseline come from the store's own producer `sensors.json`; "the runtime never
invents calibration"; gated by the camera thermal state: below the documented 0 °C TVAC floor
the channel reports UNAVAILABLE with the thermal reason).

**Thermal model (T5.1, heater-driven)**: at a polar site passive solar cannot hold the 0..50 °C
window (max el ~1.6° at Haworth), so the window holds while the pack can power the heaters;
below the shed reserve the housing falls to the cold equilibrium. Constants
`THERMAL_T_COLD_C = -60.0` [ASSUMPTION], `THERMAL_T_HEATED_C = 10.0` [ASSUMPTION],
`HEATER_RESERVE_FRAC = 0.10` [ASSUMPTION]. `set_thermal` is the manual inspection override and
beats the model.

**Checkpoint/restore**: bit-exact npz round-trip of the conserved fields + pose + sequence
counter (pinned by `test_process.py`: two clients see ONE world; disconnecting changes nothing;
checkpoint/restore round-trips bit-exact).

---

## 5. Gates and evidence (`stewie/eval/gates.py` + `stewie/eval/validation/`)

Two functions, two kinds of artifact:

- **`validate()`** reproduces the **frozen 2026-06-07 baseline** exactly: it hash-verifies every
  fixture in `validation/scene_manifest.json`, re-runs the contract checks (strict runtime
  schema, truth physical separation, stereo depth, shadow azimuth, the controlled P5 heights at
  sun 30°/50°), and returns the dated result whose serialized form must equal
  `validation/g1_g2_validation_2026-06-07.json` **byte-for-byte**. That byte-identity is the
  standing invariant — `POST /admin/gates/validate` runs it as a button and reports
  `byte_identical_to_frozen`. The frozen artifact's summary: G1 `NOT_PASSED (SIMULATED baseline
  locked; real-world capture + stereo pending)`, G2 `NOT_PASSED`.
- **`validate_current()`** is the **2026-06-10 evaluation**: it starts from `validate()`
  unchanged, then checks the NEW dated evidence and flips a gate ONLY when every formal
  criterion verifies against on-disk artifacts. Gates flip only via new dated artifacts — the
  frozen baseline is never edited.

2026-06-10 result (`validation/g1_g2_validation_2026-06-10.json`): **G1 `PASSED`**, **G2
`PASSED (rendered-sensor sim scope; all four formal criteria verified against on-disk
artifacts)`**.

G1 criteria checked in code (each a live probe, not a test-suite citation): strict-parser
rejection probes (`parse_canonical` refuses covert keys, unknown channels, alternate clocks,
negative sequence, truth leakage); RoleFS permission isolation (estimate denied truth reads,
produce denied evaluation writes); the persistent runtime core (drive → packet → parse, SoC in
(0, 1)); the locked capture re-run THROUGH the runtime seam reproducing the direct evidence; the
real Katwijk capture scored (`validation/katwijk_dead_reckon_2026-06-10.json`: ATE aligned
3.3465 m over a 92.48 m eval track, 2550 eval points); and remote CI attested (astoreyai/stewie
run 27261544141: lint + mypy + coverage 92.7% + tests).

G2 criteria: fixed reference camera (`front_left`); shadow base/tip association reproduces both
controlled P5 heights from the image alone (<1% rel. err) AND refuses the ambiguous clutter
fixture; disparity covariance calibrated on development scenes and checked on a held-out split
(`validation/stereo_sigma_calibration_2026-06-10.json`); the P5 controlled render stays a
component fixture, not the headline.

Honesty framing carried in the artifacts: G1's PASS scope is contracts-and-frames + the
dead-reckoning baseline; G2's PASS is explicitly **rendered-sensor simulation scope** — neither
claims finished real-world SLAM. Other validation evidence (figures served by `/figures`) lives
under the top-level `validation/` tree (active_perception, autonomy, ipex, map_channel, nav,
planner, plan_render, rl, self_optimizing, ui).

---

## 6. The auth model (`stewie/server/auth.py`)

Identity-bearing auth on mutating routes (#52), open in dev when no API key is set. Three ways
in, checked in order by `require_auth`, all ending at an identity string recorded as the actor
in the event history (#39):

| # | Path | Mechanism | Identity |
|---|---|---|---|
| 0 | no key configured | `STEWIE_API_KEY`/`DUSTGYM_API_KEY` unset → auth disabled | `"dev-open"` |
| 1 | Tailscale | `STEWIE_TRUST_TAILSCALE=1` (deployment behind `tailscale serve`, which injects `Tailscale-User-Login`) AND the login is whitelisted | the Tailscale login |
| 2 | operator token | `POST /auth/login` (email + API key) → HMAC-SHA256 token signed with the API key, 12 h TTL (`TOKEN_TTL_S = 12*3600`), sent as `Authorization: Bearer <token>`; payload carries `op` + `exp`; verification is constant-time, expiry-checked, and re-checks the whitelist | the operator email |
| 3 | raw API key | `X-API-Key` (or Bearer) equal to the configured key, compared with `hmac.compare_digest` (no timing oracle) | `"api-key"` (the automation identity for CI/scripts) |

- **Whitelist**: `STEWIE_ALLOWED_OPERATORS` (comma list) when set, else the in-code
  `DEFAULT_ALLOWLIST` (the two project operators' emails). Both login and token verification
  enforce it; a valid unexpired token for a de-whitelisted email stops working.
- **Operator-login kill switch**: `STEWIE_OPERATOR_LOGIN=0` disables the email/token flow
  entirely (`POST /auth/login` → 403; key-only deployments). `GET /auth/config` exposes the flag
  to the UI.
- Env knobs accept `STEWIE_<NAME>` with a `DUSTGYM_<NAME>` fallback (rename 2026-06-10; legacy
  accepted one cycle).
- `GET /session/{sid}/operator` is deliberately open (B3 contract: the trainee sees only
  telemetry-delivered, truth-denylisted data); read-only GETs are deliberately open by design
  (server hardening commit notes).

---

## Appendix: naming legacies (verified 2026-06-10)

The 2026-06-09/10 dustgym → STEWIE restructure left a few legacy strings in docstrings and
metadata. Recorded here so readers are not misled; the code behavior is as documented above.

| Location | Legacy | Actual |
|---|---|---|
| `server.py` module docstring | `python -m planet_browser.server` | the module is `stewie.server.server`; entry points `stewie-serve` / `dustgym-serve` (deprecated alias) |
| `server.py::_version()` | `importlib.metadata.version("dustgym")` | the distribution is named `stewie` → the lookup falls back to `"0.1.0"` |
| `server.py::_sample_missions` docstring | `planet_browser/sample_missions/` | `stewie/server/sample_missions/` |
| `pyproject.toml` script `dustgym-fetch-dem` | target `planet_browser.fetch_assets:main` | no `planet_browser` package exists in this tree; the module is `stewie/server/fetch_assets.py` (entry point currently broken) |
| `stewie/__init__.py` docstring | "registers the Stewie/* Gymnasium envs" | `registration.py` registers the `Dust/*` namespace |
| `stewie/twin/world_model.py`, `stewie/envs/registration.py`, bridge modules | `terrain_authority.*` / "dustgym package" phrasing | the packages are `stewie.*`; the on-wire schema id `dustgym_runtime/1.0` is intentional and unchanged |
