# STEWIE viz2 — Driveable Godot Simulation ("Artemis STEWIE viz2") — Implementation Plan v2

**Date:** 2026-07-10 (v2, incorporating LLM-council round 1 — see §7)
**Status:** PLAN ONLY. No pipeline code touched; this document is the single write of the v2 pass.
**Supersedes:** `STEWIE_viz2_driveable_godot_plan_2026-07-10.md` (v1, left untouched as the review target).
**Council review:** `STEWIE_viz2_council_review_2026-07-10.md` (4 reviewers; 2 blockers, 6 majors, 6 minors, 7 non-findings).

---

## §0 Status / method note

Read-and-plan pass over `/mnt/projects/stewie/code` @ `main` HEAD **`ad414bb2`** (confirmed `git log`
this session; moved from v1's `7b250003` during the council round, same branch line). Path-root
convention (council minor, Sonnet): `code/…` paths are under `/mnt/projects/stewie/code/`;
`data/gis/raw/`, `design/DEM_CROSSREF_…`, and `/mnt/projects/datasets/…` are **siblings of `code/`**
(repo-root or host level), not inside it.

Every EXISTS / PARTIAL / NEW claim cites a file:line opened either this session (v2 verification pass)
or in the v1 session; claims not re-opened are marked *(v1-verified)*. All five load-bearing council
premises were **independently re-verified this session** before this rewrite:

1. **The per-step whole-grid cost is real:** `drive_step` calls `cs.derive_height()` every step
   (`stewie/physics/drive.py:219`), and `derive_height` computes `datum + mass_areal/density` over the
   **whole grid** (`stewie/physics/column_state.py:155-161`). `four_wheel_pass` allocates full-grid
   boolean masks per wheel (`stewie/physics/rover.py:220-224`, via the full-grid `_wheel_mask` at
   `rover.py:44-49`). Codex's timing ladder (measured on this host, not re-run here):
   **256² = 0.75 ms · 512² = 2.6 ms · 1024² = 11.3 ms · 2000² = 47.1 ms (max 48.6)** per `drive_step`.
2. **Chrono IDs:** the ledger model is `tier3_chrono@0.0` with **backend id `tier2_chrono`**
   (`stewie/contracts/physics_model_control.py:88-89`); `tier3_chrono` is NOT a backend id. The strict
   mutation-authority gate `resolve_live_backend` exists (`physics_model_control.py:119-151`; refuses
   unvalidated / unfrozen / deprecated models AND non-conserved backends). Regression coverage:
   `stewie/server/test_r4_chrono_backend_ui_parity.py` (exists, confirmed `ls`).
3. **Datum:** a naive `ColumnState` load defaults `datum = 0` (`column_state.py:108-109`) — on a real
   DEM bundle that flattens the terrain. `coarse_base_from_bundle` reconstructs
   `datum = heightmap − mass_areal/density` AND raises if the round-trip fails
   (`stewie/physics/worksite.py:65-83`, CT-06 check at :81-82).
4. **Provenance:** `scripts/build_from_dem.py` hard-codes the LOLA lane — producer string
   "real LOLA DEM ingest" (`:106`), `dem_provenance.source = "PGDA LOLA_5mpp … (Product 78)"` (`:149`)
   with the Barker/Mazarico citation (`:53-54`), always picks its own max-relief window (`:61-66`), and
   the CLI (`:203-210`) has **no** `--center/--source/--provenance`. Running it on the NAC SfS tif
   would emit a bundle falsely claiming LOLA provenance — v1's A2 as written was a data-integrity bug.
5. **Precedent:** `stewie/runtime/process.py` (`RuntimeProcess`, class at `:55`) exists — a persistent,
   **single-threaded** Unix-socket JSON-lines authority with bounded request lines (`:51`), a readiness
   handshake (`:83-85`), and transactional atomic checkpoint/restore (module header `:11-20`).
   `planet_browser/server.py` — v1's cited socket-test precedent — **does not exist** anywhere under
   `code/` (confirmed `ls`/`find`; planet_browser was removed in the 2026-06-14 disk cleanup).

The two upstream anchors from v1 carry forward unchanged: the DEM cross-reference doc is at
`/mnt/projects/stewie/design/DEM_CROSSREF_2026-06-11.md` (repo-root sibling), and the multi-level viz
doc's "difference drape does not exist" note is STALE — LY-07 / GW-11 / GW-12 / LY-05 shipped
(`PRD.md:717-721`) and are REUSED, not rebuilt *(v1-verified)*.

Constraint posture unchanged: Godot 4.6.3 (binary pinned by `render.sh`;
`scripts/demo/render_ezrassor_katwijk_parallax.py:32` *(v1-verified)*). No synthetic terrain, no
fabricated boulder statistics; FORGE authority rules ("a backend that does not conserve mass cannot
claim release authority", `packages/stewie-forge/stewie_forge/backend_protocol.py:5,30-31`
*(v1-verified)*) are kept intact — and per council BLOCKER-2, the FORGE protocol itself now stays
**point-eval-only** (see §2b).

---

## §1 Current-state table

Carried from v1 with two corrections (all v1 evidence stands unless re-marked; rows 1, 3-8 unchanged
in substance):

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Driveable EZ-RASSOR rover, keyboard/gamepad | **PARTIAL** | Unchanged from v1: live WASD 8-pane kinematic drive view (`stewie/godot/drive_controller.gd:1-6,143-157`), no slip/sinkage/terrain mutation in Godot; gamepad NEW (`project.godot` has no `[input]` section); EZ-RASSOR glbs real + MIT-attributed (`docs/ezrassor_assets.md:14-33`); **live bug** — stale postures path `drive_controller.gd:51` → file moved to `stewie/physics/data/ipex_postures.json` (council NON-FINDING: bug + fix confirmed sound). |
| 2 | Hot-swappable terramechanics via FORGE in the drive loop | **PARTIAL** | (a) `PhysicsBackend` protocol: `stewie_forge/backend_protocol.py:15-39`; concrete `Tier2NumpyBackend` + registry `stewie/physics/backend.py:26-67` — only `tier2_numpy` registered (`:54`). **Correction (council minor, Opus):** the protocol exposes **six** members, not three — `info` / `conserves_mass` / `resolve_soil_params` plus the 3 point functions `wheel_static_sinkage` / `static_wheel_load_n` / `allowable_bearing_pa` (re-confirmed `backend.py:30-50`). It remains deliberately **pure/point-eval**: no member mutates terrain. (b) `GET /physics/backends` exposes `selectable_backends = list_backends()` **directly** (`stewie/server/routers/models.py:149-176`, re-confirmed) — so "is in selectable_backends" is NOT a future-proof mutation gate (council M-3); the strict gate is `resolve_live_backend` (`physics_model_control.py:119`). (c) The real conserved drive loop: `stewie/physics/drive.py:181-298` (re-confirmed: slip-sinkage equilibrium `:234`, discrete entrapment `:239-257`, per-side skid-steer `:260-282`, slip-deepened ruts via `four_wheel_pass(physical=True)` `:286-288`). (d) GAP unchanged: no Godot view calls `drive_step`; no step-level seam — and per BLOCKER-2 the step seam must NOT be added to the FORGE protocol (§2b). |
| 3 | Haworth at highest resolution (1 m SfS base + 2 cm runtime fine) | **PARTIAL** | Unchanged from v1: the 1 m NAC SfS DEM is real, on host twice (11660×12060 @ 1.0 m, polar stereo, X∈[−40120,−28460] Y∈[83260,95320]); registered as `lroc_nac_sfs_1m` (`dart/dem_sources.py:168-174`, re-confirmed this session); PIL DecompressionBomb guard needed. **Load-bearing finding stands (council NON-FINDING, md5-re-derived):** the committed `haworth_10km_5m` bundle does NOT overlap the SfS footprint — a 1 m site is a NEW crop, not an upgrade. Frozen 2 cm fine contract at `docs/dem_terrain_contract.md:6-14` *(v1-verified)*. |
| 4 | Interactive sun azimuth + elevation sliders | **PARTIAL** (scripted only) | Unchanged from v1: `sun_sweep.gd` scripted 12-frame sweep, sidecar `--sun-elev/--sun-azim` per-render CLI, no live slider UI; real SPICE-sun illumination producers exist backend-side for cross-checks. |
| 5 | Realistic rock dispersion + size patterns from real statistics | **PARTIAL** | Unchanged from v1: Golombek CFA implemented + sourced (`stewie/specs/constants.py:202-215,524-546`), `sample_boulders` with the self-declared no-clustering gap (`stewie/terrain/procgen.py:311-313`), real-NAC h/d validation machinery (`benchmarks/nac_shadow/`), Godot consumes clasts verbatim. GAP: no per-site spatial-k map over a real DEM tile; no Haworth-measured census in repo (§4 BLOCKED). Council NON-FINDING: all citations confirmed. |
| 6 | Dig + before/after dig-depth difference field | **PARTIAL** | Unchanged from v1: `WorkSite.drive/.flatten/.dump/.sinter` (`worksite.py:229,242,256,297`, re-confirmed); LEAP energy grounding (`leap/worksite_env.py:60-72`); LY-07 `changed_terrain` server drape shipped (`PRD.md:721`). GAP: no live in-Godot dig, no in-Godot signed diff drape. |
| 7 | Map + path analysis vs rock height/size and slope | **PARTIAL** | Unchanged from v1: 12-layer costmap (`lode/costmap_layers.py:1-29`), mission planner (`lode/mission_planner.py:223,395`); GAP: no discrete-clast `rock_hazard` layer vs `OBSTACLE_HEIGHT_M = 0.075` (`stewie/specs/ipex_specs.py:79` [SCHULER24]). |
| 8 | Cross-analyze / compare all DEM sites + papers | **PARTIAL** | Unchanged from v1: 11 real site bundles, honest source catalog (`dart/dem_sources.py`), `dem_cross.py` is NOT a site comparator; a cross-site comparison surface is NEW. Companion `toterr/ldec` ingest unimplemented. |

---

## §2 Key architecture forks

### (a) Separate Godot project vs a new driveable mode inside `code/stewie/godot/` — UNCHANGED

**Recommendation (carried from v1, no council objection):** a new, separately-launched SCENE + script
family inside the existing `code/stewie/godot/` project (`viz2.tscn` + `viz2_*.gd` + `viz2.sh`),
zero edits to the frozen sidecar/render seams; "separate simulation" satisfied at the entry-point
level. Rationale unchanged (asset sharing across Godot projects requires forking the frozen seams;
`drive_controller.gd`'s kinematic-port design is inverted by viz2's requirement; PRD lane = RT-05
extension). See v1 §2a for the full argument.

### (b) How the Godot loop talks to the physics — REWRITTEN (council consensus unifying fix)

**Recommendation: ONE core-owned, serialized, windowed conserved-terrain session actor — an
adopted `WorkSite` — served by a viz2 runtime that extends the `RuntimeProcess` seam discipline.
FORGE stays point-eval-only. Terrain reaches Godot as generation-namespaced complete patch
manifests applied by a viz2-owned live-terrain node via `ImageTexture.update`; the frozen
`state_fields.gd`/`terrain.gd` seams are untouched.**

#### (b.1) The session object: `WorkSite` — ADOPTED (the council's open fork, resolved)

The council left one fork open: is `WorkSite` the right single session object, or does viz2 need a
new `ConservedTerrainSession` wrapping a windowed `ColumnState` + inventory? **Decision: adopt
`WorkSite`. It already IS the core-owned conserved-terrain session**, verified member by member this
session (`stewie/physics/worksite.py`):

- **Datum reconstructed + verified at load** (unifying-fix item 7, M-4): `coarse_base_from_bundle`
  computes `datum = heightmap − mass_areal/density` and **raises** on round-trip mismatch
  (`worksite.py:65-83`, CT-06 at :81-82). The naive-load datum=0 flattening bug
  (`column_state.py:108`) is structurally impossible through this path.
- **A drive-compatible active window**: the fine worked window IS a real `ColumnState`
  (`worksite.py:137` `self.fine: ColumnState | None`), and `WorkSite.drive()` already runs the
  conserved closed loop on it (`worksite.py:229-240`, delegating to `drive.closed_loop_drive`) with
  `payload_kg` defaulting to the **live drum fill** (`:237-238` — a loaded drum sinks/slips more,
  the path-dependent loop for free). Per-tick interactive drive = one `drive_step` on `ws.fine`
  per command tick (drive_step's first arg is any `ColumnState`, `drive.py:181`); a thin **additive**
  `WorkSite.step(v, omega, dt)` wrapper keeps the seam single. Global-metres → window-rc conversion
  exists: `active_rc_for_xy` (`worksite.py:436-442`).
- **A recenter/store path** (the bounded moving window, BLOCKER-1): `recenter(rover_xy)`
  (`worksite.py:377-434`) pages the current window's worked state into `worked_store`
  (`_commit_active`, `:363-375`), assembles the new window from worked-or-virgin tiles, and **grows
  the conservation baseline** as virgin terrain enters (`:415-417`), keeping
  `conservation_residual()` (`:455-468`) sensitive across moves.
- **One inventory, one mass invariant**: the GLOBAL drum ledger `inventory_kg` (`:140`) carries mass
  across windows; `total_mass()` (`:446-453`) = active grid + ledger + paged store. Dig verbs
  (`flatten` `:242`, `dump` `:256`) route through the same ledger. There is **no second terrain
  authority and no copying between states** — exactly the M-4 fix.
- **Caveats found while verifying (adoption conditions, all plan-level):** (i) the single-window
  (`open_window`) and streaming (`recenter`) entry paths are **mutually exclusive by guard**
  (`worksite.py:192-194,389-392`) — viz2 standardizes on the **streaming `recenter` path only**;
  (ii) `drive()` wraps twist *lists*, so the additive per-tick `step()` is required (no frozen seam
  touched — WorkSite is core Python, not a frozen contract); (iii) the G1 cross-seam gap (a berm
  spanning a window advance) is documented in-file (`:17-18,383-384`) — mitigated by sizing
  `radius_tiles` so each dig+dump stays inside one window, carried as §6 Risk-6.

**Window sizing (the BLOCKER-1 numbers made concrete):** window side =
`(2·radius_tiles+1) · tile_base_cells · k` fine cells, `k = base_cell_m / fine_cell_m`
(`worksite.py:132`). On the new 1 m-base site with defaults (`tile_base_cells=4, radius_tiles=1`):
fine 5 cm → k=20 → **240² window** (≤ the measured 0.75 ms @ 256²); fine 2 cm (the contract fine
cell) → k=50 → **600² window** (~3-4 ms *inferred* by interpolating the measured 512²=2.6 ms /
1024²=11.3 ms ladder — confirmed only by the B2 latency gate). Both fit a 15 Hz budget with margin;
the whole-tile 2000² state (47.1 ms measured) **never enters the physics loop**.

#### (b.2) FORGE stays point-eval-only (BLOCKER-2)

v1's B1 ("add `drive_step` + a `worksite()` accessor to the `PhysicsBackend` protocol") is
**withdrawn**. The protocol's header rule — clients don't mutate terrain; non-conserving backends
can't hold release authority (`backend_protocol.py:1,5,30-31`) — is a design invariant, not an
omission. Mutation lives ONLY in the session actor (WorkSite verbs + `drive_step` on its window).
What "hot-swappable terramechanics" now means, precisely:

- The session resolves its **mutation authority** by immutable `model_id` through
  `resolve_live_backend` (or `select_backend(mode, model_id)` composing the same gate,
  `physics_model_control.py:119-165`): validated AND frozen AND non-deprecated AND
  `conserves_mass()` AND `authority_class == "conserved"` — fail-closed at every layer. Today that
  resolves exactly `tier2_numpy` (models `tier2_numpy@1.0` live-default, `@0.1` deprecated-refused).
- The resolved model's **calibration params** feed `drive_step(params=…)` — swapping validated model
  versions swaps the terramechanics the drive loop runs, with zero protocol mutation surface.
- A registered non-conserving backend (future `tier2_chrono`) may return **advisory point-evals**
  (the six protocol members) for display next to the authority's numbers — never a mutation-capable
  interface.
- Swaps apply only **between acknowledged generations** (b.4), after an invariant check
  (`conservation_residual()` + field digests) — never mid-step on live state (M-6).

#### (b.3) Transport: extend the `RuntimeProcess` seam (M-6)

v1's "planet_browser/server.py real-socket test pattern" citation was to a **removed tree** — the
real, live precedent is `stewie/runtime/process.py`: a single-threaded socketserver authority
("Single-threaded request handling by design: the authority is the serialization point", `:21`),
bounded request lines (`MAX_LINE_BYTES`, `:51`), input-bounds on the mutating seam (`:45-52`), a
readiness handshake (`:83-85`), and transactional atomic checkpoint/restore (`:11-20`). The viz2
runtime **extends** this shape rather than inventing a new daemon:

- **A `Viz2Runtime`** (subclass or sibling constructor path): swaps `RuntimeProcess`'s seeded 64²
  world (`process.py:72-74`) for the bundle-backed WorkSite session; keeps single-threaded handling,
  bounded lines, checkpoint/restore (extended to serialize the WorkSite: fine window + ledger +
  worked store + baseline — the soak test's restart leg).
- **Loopback TCP, not Unix socket, for the Godot side**: Godot's `StreamPeerTCP` speaks TCP only —
  no Unix-domain-socket client exists in Godot 4 *(inferred from Godot API surface; B2 confirms
  before build)*. The extension binds `127.0.0.1` (additive transport, same handler); the existing
  Unix-socket seam stays for Python clients.
- **Flow control mirrors `stream.py`'s actual discipline, not just its name** (M-6): every frame
  carries `(protocol_version, seq, timestamp)`; a **bounded un-acked window applies backpressure**
  (frames beyond it refused + counted); consumer ack is **cumulative** and is the link heartbeat; a
  **deadman** trips when the oldest un-acked frame ages past deadline → the runtime zeroes the twist
  (safe-stop), the exact SF-01 shape (`stewie/bridge/stream.py:1-13`, re-confirmed this session).
  Godot polls non-blocking; command sends coalesce to latest-twist.

#### (b.4) Terrain to Godot: generation-namespaced complete patch manifests (M-5)

`state_fields.gd` is a **load-once full-raster** loader (`load_scene` `:121-187`, `_load_rf` `:387`,
`ImageTexture.create_from_image` on demand `:459-465` — re-confirmed): it has no patch reader, and
atomic rename protects single files only, so multi-field updates through that seam can mix
generations. And a wheel pass changes **density, state_label, disturbance** (`rover.py:243,250-252`
— mass_areal is untouched on a drive; height moves because density does), which v1 never streamed.
The v2 protocol:

- Per physics generation N, the runtime writes changed-field **window patches** (rf32/r8 crops of
  the active window's dirty bbox) to `patches/gen_N/…`, then writes `manifest.json`
  **last** (atomic tmp+rename): `{generation, window_world_origin, bbox_rc, fields: [{name, file,
  shape, dtype, digest}]}` — **ALL changed fields**: height (derived), density, state_label,
  disturbance on every drive step; + mass_areal on dig/dump; full-window on `recenter` (the window
  itself moved).
- Godot side: a **new viz2-owned `viz2_live_terrain.gd`** node polls manifests, validates every
  digest, applies exactly **one complete generation** via `Image.blit_rect` +
  `ImageTexture.update()` (in-place, no texture realloc), **coalesces** (skips to the newest
  complete generation, drops stale), and ACKs the applied generation back on the command channel.
  `state_fields.gd` / `terrain.gd` are not edited — viz2's terrain node owns its own textures,
  seeded once from the bundle via the frozen loader, then patched live.

### (c) Coordinate frames — UNCHANGED (council NON-FINDING: confirmed sound, do not churn)

Carried verbatim from v1: adopt the shipped GW-12 contract wholesale (authoritative coordinates only
in IAU_2015:30135/30100 server-side; render surfaces declare a local origin and render
float32-relative; picks convert back through `stewie/terrain/site_dem.py:211,227,245`; `PRD.md:718`).
Godot local origin = the site bundle's `world_bounds_m` min corner (`terrain.gd:13-14`); 2 km @ 1 m
site → max in-scene coordinate ≈ 2×10³ m → float32 ULP ≈ 0.122 mm (council re-verified), far under
budget. New site registers in `stewie/specs/sites.py` + `dart/dem_sources.py`; extend the GW-12
round-trip test's site list. Sun convention `rotation_degrees = Vector3(−elev, azim, 0)`
(`sun_sweep.gd:121`).

### (d) Where the GPU rendering runs — UNCHANGED except one line (council minor)

Host GPU, interactive session — primary on the archimedes RTX 3090 (windowed, or xvfb+Vulkan for the
headless verify tier). NOT in Docker (compute-not-graphics CDI; memory
`infra_stewie_gpu_render_blocked`). **Dropped from v1:** euclid via "SSH + display forwarding" —
X11-forwarded Vulkan is not hardware-accelerated; euclid counts only as a second **headless render
host or a local session** (council minor, Opus). The Python runtime is CPU-only and runs beside
Godot on the same host.

---

## §3 Phased, atomic task list

Verification discipline unchanged: each task ends with a REAL observation; the full suite gate stays
`pytest` over `lode/ leap/ dart/ forge/ stewie/` parsed by **exit code** (standing project rule),
plus the Godot headless-verify captures. Tasks marked **BLOCKED** are honestly blocked (§4), not
deferred-verified.

Phase order + rationale (council minor fixed): A first (need the site). **B is the keystone because
it unlocks the dig/replan/authority chain (E, F, and the backend governance surface)** — not because
"everything reads its telemetry". **C depends only on A** and parallelizes immediately after it;
D is independent after B (D3 threads clasts into the session); E needs B; F needs D+E; G is
independent of B-F and can run any time after A.

### Phase A — 1 m Haworth site + viz2 scene renders it + drive input

| Task | Change | File(s) | Verification |
|---|---|---|---|
| A1 | PIL `Image.MAX_IMAGE_PIXELS` guard (explicit, bounded, comment naming the 140.6 Mpx SfS file) in the ingest lane | `dart/dem_import.py` | Unit test: `load_lola_geotiff` on the real SfS tif returns (11660,12060) float32 with the verified affine (corner −40120/95320, 1.0 m px), no DecompressionBombWarning |
| **A2 (REWRITTEN, M-7)** | **SfS-specific ingest path — no false LOLA provenance.** Extend `scripts/build_from_dem.py` with explicit `--source-id` (a `dart/dem_sources.py` id), `--citation-mode from-source`, and `--center X Y` args: provenance strings (`:106` producer, `:149` source, `:53-54` citation) derive from the named `DemSource` row — for `lroc_nac_sfs_1m` that is **USGS Astrogeology LRO NAC photoclinometry (SfS) DEM 1 m** (`dem_sources.py:168-174`) with the Alexandrov & Beyer 2018 method citation (crossref §b), NOT Barker/Mazarico; `--center` bypasses `find_max_relief_window` (`:61-66`) so the crop is chosen INSIDE the SfS footprint deliberately (e.g. near (−34290, 89290), max-relief within-footprint). Defaults unchanged → every existing LOLA bundle regenerates byte-identically | `scripts/build_from_dem.py` (additive args), possibly a small `dem_sources`-lookup helper | (1) Regression: rebuild `haworth_10km_5m` with defaults → metadata.json deep-equal to the committed one (provenance untouched). (2) New-path test: emitted `dem_provenance.source/citation` string-match the `lroc_nac_sfs_1m` registry row + Alexandrov & Beyer, and `world_bounds_m` ⊂ the verified SfS bounds (X∈[−40120,−28460], Y∈[83260,95320]) — **provenance + bounds compared, not just round-trip height** |
| A2b | Build the 1 m bundle: `--src code/datasets/lunar_dem/Lunar_LROnac_Haworth_sfs-dem_1m_v3.tif --out samples/lunar_dem/haworth_sfs_2km_1m --extent-m 2000 --base-cell-m 1.0 --source-id lroc_nac_sfs_1m --center …` (2000² grid, same memory shape as existing bundles) | new bundle dir (no code beyond A2) | The script's self-verify (round-trip max_err + non-zero world_bounds asserts, `build_from_dem.py:183-193`); manual confirm `world_bounds_m` ⊂ SfS bounds |
| A3 | Register the site: `Site(...)` in `stewie/specs/sites.py` + `DemSource(bundled=True)` note on `lroc_nac_sfs_1m` | those two registries | Existing gates green by exit code: `dart/test_dem_sources.py`, `stewie/server/test_dem_sources_registry.py`, `stewie/specs/test_sites.py`, `test_geo_siting.py`, `test_plan_anywhere.py`; `/dem/sources` lists it; GW-12 round-trip test extended to the new site |
| A4 | viz2 scene skeleton: `viz2.tscn` + `viz2_root.gd` — seeds terrain from the bundle via the frozen loader, builds the viz2-owned live-terrain node (§2b.4), places the EZ-RASSOR rig (MIT notice per `docs/ezrassor_assets.md:21-23`); `viz2.sh` launcher | new files under `stewie/godot/` only | Headless verify capture (`--auto N` writes a frame, the `--drive-auto` pattern); human eyeball: real 1 m relief + rover visible |
| A5 | Input: Godot InputMap actions (`viz2_forward/back/left/right/dig/dump/brake`) bound to WASD **and** gamepad in `project.godot`; controller reads actions, not raw keys | `project.godot`, `viz2_root.gd` | On-host interactive gamepad run (named operator check, §6 Risk-7); headless: action-injection via `Input.parse_input_event` *(inferred it works headless; A5 confirms first)* |
| A6 | Fix the stale postures path (`../terrain_authority/data/ipex_postures.json` → `../physics/data/ipex_postures.json`) in the EXISTING drive_controller (adjacent one-line bug; council NON-FINDING: keep) | `stewie/godot/drive_controller.gd:51` | `--drive-auto` run prints posture load success; buttons change arm angles in the capture |

### Phase B — the conserved-terrain session actor (REWRITTEN: unifying fix, BLOCKER-1/2, M-3/4/5/6)

| Task | Change | File(s) | Verification |
|---|---|---|---|
| B1 | **Additive `WorkSite.step(v_cmd, omega_cmd, dt)`**: per-tick conserved drive on the streaming session — tracks rover pose in GLOBAL metres, `recenter(rover_xy)` when the rover nears the window edge, converts via `active_rc_for_xy` (`worksite.py:436`), runs `drive_step` on `self.fine` with `payload_kg=self.inventory_kg` and window-frame clasts, returns the telemetry dict + the dirty bbox. NO change to the FORGE protocol (BLOCKER-2: withdrawn v1-B1) | `stewie/physics/worksite.py` (additive method) | `[REQ:]` test on the real 1 m bundle: (1) `step` telemetry == direct `drive_step` on the same window state (byte-identical); (2) datum verified — fine-window `derive_height()` at the start pose matches the bundle DEM within the contract tolerance BEFORE the first step (M-4/unifying-fix item 7; the ctor raise `worksite.py:81-82` is the backstop); (3) drive across a recenter boundary → `conservation_residual()` < 1e-6·baseline |
| B2 | **`Viz2Runtime`** extending the `RuntimeProcess` seam (§2b.3): bundle-backed WorkSite world (replacing the seeded grid, `process.py:72-74`), loopback-TCP transport for Godot (confirm StreamPeerTCP/no-Unix-socket first), `stream.py`-discipline flow control (bounded un-acked window + cumulative ACK + deadman → zero-twist safe-stop), single-threaded handling, checkpoint/restore extended to the WorkSite session. **Mandatory bounded physics window** (BLOCKER-1): default fine 5 cm / 240² window; 2 cm / 600² behind the same latency gate | `stewie/runtime/viz2_runtime.py` (new), reusing `process.py` | Pytest over a real socket: (1) command a twist on the 1 m bundle → telemetry has slip>0 on slope, entrapment on a crater wall, mass conserved; (2) **measured p95 command→telemetry latency gate** at the chosen window size on this host — p95 < 1/15 Hz budget with the render margin stated (the ONLY place the 600² "~3-4 ms" inference becomes a claim); (3) flood the command channel → backpressure refuses + counts, deadman zeroes the twist |
| B3 | **Patch protocol** (M-5): runtime writes generation-namespaced complete manifests of ALL changed fields (§2b.4); Godot `viz2_live_terrain.gd` + `viz2_drive_client.gd` — StreamPeerTCP, 15 Hz commands, 60 fps pose **interpolation** between acked authority poses (interp over extrapolation because entrapment is a v→0 discontinuity, `drive.py:248-257`; the ~66 ms display-latency budget is named on the HUD — council minor), `ImageTexture.update` per applied generation, generation-ACK back | new Godot files + runtime patch writer | (1) Pytest: manifest written LAST, digests match field crops; a torn write (missing field file) → generation refused whole; out-of-order generations → newest complete wins, stale dropped. (2) `--auto` headless drive: final pose in capture matches runtime pose (< 1 cell); a rut is visibly carved in the falsecolor-state capture AND the **density + disturbance** patches changed (`rover.py:243,252` fields — the v1 omission) |
| B4 | **Fail-closed backend governance** (M-3): HUD picker lists the `MODELS` ledger rows by immutable `model_id` (`physics_model_control.py:73-95`); the session's mutation authority resolves ONLY through `resolve_live_backend`/`select_backend` (`:119-165`); swaps apply between acked generations after `conservation_residual()` + digest checks. `tier3_chrono@0.0` renders greyed with its ledger reason (`validated=False`), read-only — its `backend_id` (`tier2_chrono`) is **never sent to `get_backend()`** for mutation | runtime + HUD | `[REQ:]` tests: (1) unknown id → registry `ValueError` (`backend.py:60-62`); (2) `tier3_chrono@0.0` → `PhysicsModelRefused` (unvalidated, gate step 1 `:129-132`); (3) **registered-fake-backend test**: monkeypatch a non-conserving backend INTO `_BACKENDS` + a validated+frozen model row for it → `list_backends()` includes it, but the mutation gate refuses at the conservation check (`:138-144`) — proving the gate does NOT lean on today's single-entry registry (the fake exists only inside the test to prove fail-closed logic; no synthetic data in any pipeline); (4) `tier2_numpy@1.0`→`tier2_numpy@1.0` mid-drive re-resolve is a state no-op applied between generations |
| B5 | Chrono **advisory** lane (display-only, point-eval per §2b.2): when a validated PyChrono host env exists AND PX-03 registers `tier2_chrono`, the runtime may show advisory point-eval numbers tagged `authority_class="advisory"` beside the authority's — never a mutation. | runtime | **BLOCKED** (§4 item 3): `tier2_chrono` is not in `_BACKENDS` (`backend.py:54`), so even the advisory lane cannot resolve today; needs the micromamba PyChrono env + PX-03. Until then: the greyed ledger row only. Skip-clean test when absent |
| B6 | **End-to-end soak test** (council minor, Codex): real socket + real headless Godot client, N minutes of scripted drive+dig: out-of-order generation delivery, a swap-during-drive request (must defer to the generation boundary), runtime kill + checkpoint restore (session resumes bit-exact per the `RuntimeProcess` A-01 pattern), p95 latency + bounded-backlog assertions | test only | Pytest exit code; the soak's recorded p95 + max backlog printed and asserted against the B2 budget |

### Phase C — Live sun sliders (parallelizes after A; only C2's cross-check consumes B telemetry context)

| Task | Change | File(s) | Verification |
|---|---|---|---|
| C1 | HUD sliders: azimuth 0-360°, elevation −5..+90° driving the DirectionalLight via `Vector3(−elev, azim, 0)` (`sun_sweep.gd:121`); numeric readout + grazing-band annotation (`sun_sweep.gd:33-36`). **Depends only on A** | `viz2_hud.gd` | Interactive: shadows sweep live. Headless: two `--auto` captures at (215°,5°) vs (35°,5°) — shadow direction flips in the images |
| C2 | Consistency check vs the backend's real illumination producer: at slider (az,el), sample `dart.illumination` horizon/incidence on the same heightfield window; assert Godot shadow mask vs horizon-march mask IoU above a stated threshold | runtime + a `[REQ:]` test | Pytest: mask IoU above threshold on the real 1 m crop at grazing sun (render-vs-analytic gate, not "looks right") |
| C3 | Preserve the scripted sweep as a viz2 export (reuse `SunSweep.run_sun_sweep` untouched) | none (reuse) | Existing sun_sweep manifest run still green on the new scene |

### Phase D — Rock dispersion from real statistics (+ the explicit DISPLAY task, M-8a)

| Task | Change | File(s) | Verification |
|---|---|---|---|
| D1 | **Spatial-k Golombek field over the real DEM**: `stewie/terrain/rockfield.py` — per-cell k from the sourced envelope (background 0.005, ejecta ramp to 0.20, `constants.py:534-539`) keyed to REAL DEM features (LY-05 curvature + slope on the actual 1 m heightfield — no invented geology); bin-wise Poisson sampling reusing `sample_boulders`' inversion (`procgen.py:299-328`), deterministic via `coord_seed`. **Honesty label carried into the manifest: the k-field is `[CALIB]` on global Bandfield/Golombek envelopes — NOT "Haworth-measured"** (M-8b; D4 is the only path to a measured claim and it is BLOCKED) | new file + scene metadata clasts[] | `[REQ:]` test: (1) recovered cumulative fractional area per stratum matches F_k(D) within Poisson tolerance; (2) determinism: same seed+window → byte-identical clast list; (3) abundance inside the Bandfield envelope; (4) the manifest carries the `[CALIB]` provenance tag verbatim |
| **D2 (NEW, M-8a)** | **Pre-dig rock-field DISPLAY**: before any Phase-E digging, the viz2 scene renders the D1 dispersion so "see dispersion patterns" is a first-class deliverable — clasts through the existing verbatim path (`boulder_manifest.gd:8-14`), plus a HUD toggle "rock density" drape (the D1 k-field as a falsecolor overlay on the live-terrain node) and a size-histogram panel (counts per diameter bin from the actual clast list, no invented stats) | `viz2_root.gd`, HUD, live-terrain node | Captures: rocky-vs-sparse k renders visibly different fields; the k-drape's high-k regions coincide with the DEM's crater-rim curvature (spot-check 3 rims); histogram bin counts == the clast-list counts (numeric equality test) |
| D3 | Height/shape realism + provenance (v1-D2): h-d geometry traces to Demidov & Basilevsky 2014 via `nac_boulder_repro.py:5-11`; buried_frac stays honest [UNKNOWN] U(0.1,0.7) (`constants.py:541-546`) | manifest fields | Test asserts the citation + [UNKNOWN] tag verbatim |
| D4 | Physical interaction (v1-D3): thread clasts into `WorkSite.step` → `drive_step(clasts=…)` (`drive.py:187,222-224`) so ride-over/blocking is physical | runtime | Capture + telemetry: drive into a >wheel-radius rock → pose blocked/ridden per `conform_pose` clast logic |
| D5 | (Stretch, real-data) Haworth-local measured calibration via `nac_boulder_repro` — **BLOCKED** on a real Haworth-area NAC ortho (§4 item 2); skip-clean otherwise. Fallback stated: D1's `[CALIB]` envelope is the shipping behavior | `benchmarks/nac_shadow/` reuse | Only activates with the real ortho on disk |

### Phase E — Dig + before/after difference drape

| Task | Change | File(s) | Verification |
|---|---|---|---|
| E1 | Dig interaction: viz2 `dig`/`dump` actions → session `WorkSite.flatten/.dump` under the drum footprint (`worksite.py:242,256`) — same serialized actor, same generation stream (mass_areal patches now included, §2b.4); energy debits from `ipex_specs` (dig 4151 J/kg, `worksite_env.py:60-72` grounding) on the HUD battery bar | runtime + HUD | Pytest: dig N kg → `conservation_residual()` invariant holds (grid+ledger); HUD energy decreases by the grounded J/kg |
| E2 | Signed difference in-Godot: diff = h_now − h_virgin, where h_virgin regenerates deterministically per tile (`worksite.py:344-358` `_virgin_tile_fields`, deterministic mosaic regen — no extra stored baseline needed); streamed as one more patch field; new `falsecolor_diff.gdshader` (diverging ramp, zero transparent) on the viz2 live node — the in-Godot twin of LY-07 (`PRD.md:721`) | new shader + live-node wiring (additive) | Capture after scripted dig+dump: cut negative-color, berm positive; numeric: max cut depth in the texture == authority value at the same cell |
| E3 | Evidence tie-in: on session end, emit `RegolithVolumeEstimate` (`leap/volume_evidence.py:15-35`) and (server up) register the run so LY-07 `changed_terrain` + `/world/point` show the SAME dig on /ide | runtime | Pytest: estimate's conserved mass == WorkSite ledger; cross-surface: `/world/point` depth == Godot diff texture value at the same cell |

### Phase F — Path/traversability analysis vs rock height/size + slope

| Task | Change | File(s) | Verification |
|---|---|---|---|
| F1 | **NEW costmap layer `rock_hazard`**: rasterize the D1 clast list — per-cell max exposed height h = 2r(1−buried_frac); cost ∝ h/`OBSTACLE_HEIGHT_M`; impassable where h > 0.075 m (`ipex_specs.py:79` [SCHULER24]); registered in `compose` with its blocking reason like the existing 12 (`costmap_layers.py:1-29`) | `lode/costmap_layers.py` (additive) | `[REQ:]` test: a 0.3 m rock cell blocks with reason "rock_hazard"; a 0.05 m rock costs but passes; existing `test_costmap_layers.py` unchanged-green |
| **F2 (STRENGTHENED, M-8e)** | Plan over it: `mission_planner.plan()` (`mission_planner.py:223`) on the 1 m site with the rockfield; viz2 draws the returned path polyline (order-frame, §2c) | runtime glue + `viz2_path.gd` | `[REQ:]` test proving the planner **routes around** rock clusters, not merely mask-compliance: (1) the straight start→goal corridor intersects ≥1 rock_hazard-BLOCKED cell (the cluster is genuinely in the way); (2) the planned path intersects 0 blocked cells; (3) planned length > straight-line length (a real detour); (4) with the rockfield removed, the planned path shortens and crosses the former cluster. Capture: the detour visible around a named cluster |
| F3 | Live what-if: sun sliders re-shade; "replan" re-runs the costmap over the as-built (post-dig) surface — digging changes traversability | runtime | Test: dig a trench across the old path → replan routes around it (numeric, same 4-clause pattern as F2) |

### Phase G — Cross-site DEM compare (M-8d: a REAL comparison deliverable, blocked parts named)

| Task | Change | File(s) | Verification |
|---|---|---|---|
| G1 | Site switcher in viz2 over every bundled site (11 dirs + `haworth_sfs_2km_1m` + ad-hoc 118 m picks via `resolve_adhoc_bundle`) | `viz2_root.gd` | Capture per site: 3 spot-checked sites render with relief ranges matching each `metadata.json height_range_m` |
| **G2a (NEW, promoted)** | **The real overlap pair — no download needed**: re-crop the on-host raw 5 m Haworth source (`/mnt/projects/datasets/lola_5mpp/Haworth_final_adj_5mpp_surf.tif`, dir-listed §4) over the SfS window using A2's `--center` (LOLA provenance, correct by default) → `haworth_5m_over_sfs` bundle. *(Inferred that the 5 m tile's footprint covers the SfS window — both are Haworth products; G2a's first act confirms bounds and STOPS with an honest report if not.)* | one `build_from_dem.py` run + registry rows | Bundle self-verify + explicit bounds-overlap assert vs the SfS bundle (refuse-and-report on no overlap) |
| G2b | **Cross-site comparison producer**: `dart/dem_site_compare.py` — per-site stat table (slope median/RMS via LY-05 gradient producers, roughness, height range, cell size, provenance citation from bundle metadata) + the **1 m-vs-5 m residual map on the G2a overlap pair** (the honest resolution-difference exhibit: SfS-minus-LOLA elevation residual, stats vs the crossref §b error budget ~0.30-0.50 m RMS Z + SfS 1-2 m) + a `/dem/compare` router read + a viz2 "compare" panel rendering the table + residual drape | new file + router + panel | `[REQ:]` test on real bundles: table rows == on-disk bundles; residual offered ONLY where footprints truly overlap (explicit refusal elsewhere); residual stats printed vs the published error budgets |
| G3 | Companion uncertainty layers (`--aux toterr=…,ldec=…,slperr=…` ingest + drapes) | `scripts/build_from_dem.py`, metadata | **BLOCKED** (§4 item 1): the Haworth companion rasters are not on disk; needs the PGDA download (explicit go required). No partial build |
| G4 | Paper panel: viz2 "About this DEM" pane reads each bundle's `dem_provenance.citation` verbatim + the §5 product table (generated FROM the crossref doc, not hand-retyped). After A2, the SfS bundle's pane shows the **SfS** citation — the M-7 fix made visible | small generator script | Rendered pane text == the metadata citation strings (string-compare test) |

### Resolution scope (M-8c, stated as a decision)

**First cut = 2 km @ 1 m base** (the A2b bundle; 2000² grid, identical memory shape to every
existing bundle). **Full 10 km @ 1 m (10000² base) is explicitly deferred** — it needs streamed
base-tile paging beyond the current whole-array bundle load, i.e. the TileMosaic base-reader lane
(`dem_terrain_contract.md` §5). **The 2 cm runtime fine layer IS wired**, via WorkSite itself: the
fine window at `fine_cell_m=0.02` over the 1 m base (k=50) is exactly the frozen contract's fine
machinery; the gate before trusting it is the contract's §7 `coarsen(fine)==base` acceptance **run
at a 1 m base** (v1 §6 Risk-2, kept) plus the B2 p95 latency gate at the 600² window. Until both
pass, viz2 ships at 5 cm fine (240² window, measured-safe) — an honest intermediate, not a stub.

---

## §4 Real-data + provenance inventory

**On disk, verified (v1 pass; re-cited where v2 re-opened):** unchanged from v1 — the table carries
forward verbatim: the SfS tif twins (11660×12060 @ 1.0 m, rasterio-verified), the 11 curated 5 m
bundles (Barker 2021 + Mazarico 2011 citations in metadata, `THIRD_PARTY.md:80-85`), the PGDA site
tiles + `ldem_75s_120m`, `/mnt/projects/datasets/lola_5mpp/` raw sources, the LOLA global 118 m, the
9 real NAC shadow fixtures, the EZ-RASSOR MIT meshes, and the [FIXED]/[CALIB]/[UNKNOWN]-tagged rock
and crater constants (`constants.py:202-215,524-546,398-413,552-557`). See v1 §4 for the full table;
nothing in it was challenged (council NON-FINDING: "the data lens is the plan's strongest part").

**MISSING — BLOCKED items (council-confirmed genuinely blocked; treated as BLOCKED, never
"verified", per the Codex minor):**

1. **Haworth companion uncertainty rasters** (`_toterr/_ldec/_slperr.tif`) — not on disk. **G3
   BLOCKED**; needs the PGDA Product-78 companion downloads (no download without an explicit go).
2. **A NAC ortho covering the Haworth work area** for measured local boulder density. **D5 BLOCKED**;
   until then the rockfield ships honestly `[CALIB]` on Bandfield/Golombek envelopes (D1) — the
   fallback is stated in-task, per M-8b.
3. **Live Chrono backend (PX-03)** — `tier3_chrono@0.0` is ledger-listed `validated=False`
   (`physics_model_control.py:88-94`), its backend id `tier2_chrono` is NOT in `_BACKENDS`
   (`backend.py:54`), so **both** mutation AND the advisory point-eval lane are unresolvable today.
   **B5 BLOCKED** on the user-local micromamba PyChrono env (memory
   `infra_stewie_convergence_toolchain`; PyPI `pychrono` is a typosquat — never pip-install it) +
   PX-03 registration. Until then Chrono is the greyed, read-only ledger row.
4. ~~Overlap pair for the 1 m-vs-5 m residual~~ — **UNBLOCKED into G2a**: the cheap on-host re-crop
   (one `build_from_dem.py --center` run over the SfS window; no download). Kept here so the
   residual exhibit is still not assumed free: G2a carries the explicit footprint-overlap
   confirm-or-stop.

---

## §5 Research-paper summary — UNCHANGED (council NON-FINDING: all citations verified; do not churn)

Carried verbatim from v1: the DEM product table (Barker 2021 / Barker 2023 / Barker 2016 /
Alexandrov & Beyer 2018 / Bertone-Barker-Mazarico CC-BY-segregated / Smith 2010) and the rock-SFD
literature list (Golombek 2003 `q(k)=1.79+0.152/k` + Golombek & Rapp 1997; Bandfield 2011;
Bernhardt/Boazman/Watkins/Bickel & Kring SECONDARY-SOURCED; Ruesch & Woehler 2021 direction-only;
Demidov & Basilevsky 2014 h/d=0.60±0.03 with the truth-firewalled NAC reproduction; Neukum/Ivanov/
Hartmann, Xiao & Werner, Minton, Pike, Stöffler). Honesty note stands: **Cintala is not cited
anywhere in this repo** (grep, v1) — the plan cites only what the repo grounds. One v2 addition to
the table's *use* column: Alexandrov & Beyer 2018 is now also the **A2 SfS provenance citation of
record** for the 1 m bundle (M-7), not merely the honesty label.

---

## §6 Risks / explicitly deferred

**Risks**

1. **Per-step whole-grid cost (RE-POINTED, BLOCKER-1):** the dominant cost is
   `cs.derive_height()` over the whole grid every step (`column_state.py:161`, called at
   `drive.py:219`) plus `four_wheel_pass`'s full-grid per-wheel masks (`rover.py:220-224`) — NOT
   `four_wheel_pass` alone as v1 stated. Measured (Codex, this host): 256² 0.75 ms → 2000² 47.1 ms
   (~71% of a 15 Hz period before transport/render). Mitigation is **structural, not a fallback**:
   physics runs only on the WorkSite bounded window (240² default; 600² for 2 cm fine), gated by
   B2's measured p95 latency test. The whole-tile state never enters the loop.
2. **2 cm fine at a 1 m base** (unchanged from v1): the frozen contract's fine machinery was built
   for 5 m→2 cm; a 1 m base changes the octave stack. Gate: contract §7 `coarsen(fine)==base` run
   at 1 m before trusting the visuals (now paired with the B2 latency gate — §3 scope decision).
3. **SfS DEM veracity at rock scale** (unchanged): sub-2 m SfS "bumps" are not certified boulders
   (Alexandrov & Beyer error 1-2 m); D-phase rocks are STATISTICAL (sourced SFD), never read off
   the DEM — stated in the manifest.
4. **Two copies of the 562 MB SfS tif** (unchanged): `code/datasets/…` is canonical (A2b);
   `data/gis/raw/` twin name-and-left for a later dedupe.
5. **GDScript kinematic drive remains** beside viz2 (unchanged): viz2 HUD labels its authority
   (`tier2_numpy@1.0`, conserved); the old mode keeps its prototype banner.
6. **WorkSite G1 cross-seam gap** (NEW, from the b.1 adoption caveats): a berm/cut spanning a
   recenter advance seam is the documented residual gap (`worksite.py:17-18,383-384`); mitigate by
   sizing `radius_tiles` so each dig+dump footprint stays inside one window; the B1 conservation
   test drives across a boundary deliberately.
7. **Godot editor-vs-headless input** (was v1 Risk-6): gamepad verification is an on-host
   human-in-the-loop observation; headless covers action-injection only — A5 carries the named
   operator check.
8. **Display latency of pose interpolation** (NEW, council minor): interpolating between acked
   authority poses adds ~one command period (~66 ms at 15 Hz) of fixed display latency; chosen over
   extrapolation because entrapment is a v→0 discontinuity (`drive.py:248-257`) that extrapolation
   would overshoot visibly. The budget is named on the HUD and asserted in the B6 soak.

**Explicitly deferred (not in scope)**

- Registering a **live Chrono producer** as a selectable backend (PX-03) — BLOCKED per §4 item 3;
  only the greyed ledger row ships until the PyChrono host env is validated.
- **ROS2/Gazebo lowering** of the viz2 loop — the flow-control discipline deliberately mirrors
  `stream.py`'s real seq/cumulative-ACK/deadman shape (§2b.3) so the lowering stays mechanical.
- **Whole-tile 10 km @ 1 m** base (10000²) — needs the TileMosaic base-reader streaming lane
  (§3 scope decision).
- **Multi-rover / fleet** in viz2 — single-vehicle first.
- **QWC2 /ide embedding of viz2** — /ide keeps the GW-11 Three.js validate view; viz2 stays native.
- Downloading DM1/LM7 — tracked in `STEWIE_more_DEMs_plan_2026-07-09.md` §5.2, off viz2's path.

---

## §7 Changes from v1 (council round 1)

| Amendment | What changed in v2 | Evidence (opened this session unless noted) |
|---|---|---|
| **CONSENSUS UNIFYING FIX** | §2b fully rewritten around ONE core-owned, serialized, windowed conserved-terrain session actor. The open fork resolved: **`WorkSite` ADOPTED** as the session object — it already has the datum-verified load, a drive-compatible active window (`ColumnState` + `drive()` + `active_rc_for_xy`), the recenter/worked-store paging path, the single global inventory, and the conservation residual. Adoption conditions (streaming-path-only; additive per-tick `step()`; G1 seam risk) named in §2b.1 | `worksite.py:65-83` (datum + CT-06 raise), `:137` (fine ColumnState), `:229-240` (drive, payload=ledger), `:436-442` (active_rc_for_xy), `:377-434` (recenter + store), `:140,446-468` (ledger + residual), `:192-194,389-392` (entry-path guards) |
| **BLOCKER-1** (2000² drive infeasible) | Bounded moving PHYSICS window is now mandatory + structural (the WorkSite window, sized concretely: 240² @ 5 cm / 600² @ 2 cm); B2 carries a **measured p95 command→telemetry latency gate**; §6 Risk-1 re-pointed at `column_state.py:161` / `drive.py:219` + full-grid masks, citing the Codex ladder as measured (not re-run) | `drive.py:219`, `column_state.py:155-161`, `rover.py:44-49,220-224`; window math `worksite.py:132`; timing = council-measured |
| **BLOCKER-2** (protocol mutation leak) | v1-B1 (protocol `drive_step`) **withdrawn**. FORGE stays point-eval-only; mutation lives solely in the session actor; "hot-swap" redefined as validated-model selection + params into `drive_step`, advisory point-evals for non-conserving backends (§2b.2) | `backend_protocol.py:1,5,29-39` *(v1-verified header rule)*; `backend.py:26-50` (pure members re-confirmed) |
| **M-3** (fail-closed gate + wrong Chrono id) | B4 rewritten: select by immutable `model_id`; mutation authority resolves ONLY through `resolve_live_backend`/`select_backend`; **registered-fake-non-conserving-backend test** added (proves the gate survives a populated registry); Chrono ledger row read-only, `tier2_chrono` (the correct backend id) never sent to `get_backend()` for mutation | `physics_model_control.py:88-89` (tier3_chrono@0.0 → backend `tier2_chrono`), `:119-151` (the gate's 3 layers), `models.py:149-176` (selectable = list_backends() directly), `backend.py:54,60-67`; `stewie/server/test_r4_chrono_backend_ui_parity.py` exists (ls) |
| **M-4** (two authorities + datum) | One session object (WorkSite); v1's plain-`ColumnState`-in-B2 vs `WorkSite`-in-E1 split eliminated; datum reconstructed + verified before the first drive step (B1 test clause 2, backed by the ctor raise) | `worksite.py:65-83`; `column_state.py:108-109` (the datum=0 default the path avoids) |
| **M-5** (patch protocol absent) | §2b.4 + B3: generation-namespaced complete manifest `{generation,bbox,field,shape,digest}` written LAST; Godot validates one complete generation, coalesces/drops stale; patches **ALL changed fields** — height, density, state_label, disturbance every drive step (+mass_areal on dig) — via a viz2-owned live node with `ImageTexture.update`; frozen `state_fields.gd`/`terrain.gd` untouched | `rover.py:243,250-252` (density/state/disturbance change on a pass; mass_areal untouched); `state_fields.gd:121-187,387-403,459-465` (load-once full-raster, create-not-update — re-confirmed) |
| **M-6** (flow control + dead precedent) | The `planet_browser/server.py` citation **dropped** (confirmed nonexistent under `code/`); transport rebuilt on `RuntimeProcess` (single-threaded authority serialization, bounded lines, readiness handshake, atomic checkpoint/restore) extended with loopback TCP for Godot; flow control adopts `stream.py`'s REAL discipline (bounded un-acked window + cumulative ACK + deadman safe-stop); swaps only between acked generations after invariant/hash checks | `process.py:21,45-52,55,83-85` + module header `:11-20`; `stream.py:1-13` (re-read); `find`/`ls`: no planet_browser under code/ |
| **M-7** (false LOLA provenance) | A2 rewritten as an SfS-correct ingest: `--source-id/--citation-mode/--center` args; provenance derives from the `DemSource` registry (USGS NAC photoclinometry + Alexandrov & Beyer 2018), never the hard-coded Barker/Mazarico string; verification compares **emitted provenance + bounds**, plus a byte-identical regression on the default LOLA path | `build_from_dem.py:53-54,61-66,106,149,203-210` (all re-confirmed); `dem_sources.py:168-174` |
| **M-8a** (see dispersion pre-dig) | NEW task D2: explicit pre-dig rock-field DISPLAY (clast render + k-field drape + real-count size histogram) landing before Phase E | `boulder_manifest.gd:8-14` *(v1-verified)* |
| **M-8b** (honest [CALIB]) | D1 manifest carries `[CALIB]` (global envelopes, NOT "Haworth-measured") with a test asserting the tag; D5 (measured) stays BLOCKED with the fallback stated in-task | `constants.py:524-546` *(v1-verified)* |
| **M-8c** (resolution scope) | §3 "Resolution scope" decision block: 2 km@1 m first cut; 10 km@1 m explicitly deferred to the TileMosaic base lane; 2 cm fine wired via WorkSite `fine_cell_m=0.02` gated by contract §7 coarsen acceptance at 1 m + the B2 latency gate; 5 cm is the honest intermediate | `worksite.py:132` (k), `docs/dem_terrain_contract.md:6-14` *(v1-verified)* |
| **M-8d** (real cross-site compare) | G2 split: **G2a** builds the real overlap pair from the on-host 5 m raw source (unblocked by A2's `--center`; footprint overlap confirm-or-stop); **G2b** ships the stat table + the 1 m-vs-5 m residual exhibit vs published error budgets; G3 stays BLOCKED (downloads) | `/mnt/projects/datasets/lola_5mpp/` dir listing *(v1-verified)*; crossref §b *(v1-verified)* |
| **M-8e** (routes-around) | F2 verification rebuilt as a 4-clause routes-around proof (straight corridor blocked / planned path clean / real detour length / cluster-removal control); F3 inherits the same pattern | `mission_planner.py:223` *(v1-verified)* |
| Minor: pose-interp latency | §6 Risk-8 names the ~66 ms budget + the interp-over-extrapolation tradeoff (entrapment v→0 discontinuity) | `drive.py:248-257` (re-confirmed) |
| Minor: "only 3 point functions" | §1 row 2 corrected to the six protocol members | `backend.py:30-50` |
| Minor: euclid SSH forwarding | §2d drops X11-forwarded Vulkan; euclid = 2nd headless host or local session | — (council reasoning adopted) |
| Minor: keystone rationale + C1 ordering | §3 phase-order note: B unlocks the dig/replan/authority chain; C1 depends only on A and parallelizes earlier | — |
| Minor: §0 conventions | HEAD updated to `ad414bb2`; path-root convention stated | `git log` this session |
| Minor: soak test + BLOCKED discipline | NEW B6 end-to-end soak (out-of-order generations, swap-during-drive, restart/restore, p95 + backlog); B5/D5/G3 marked **BLOCKED**, never "verified" | `process.py:11-20` (the restore pattern B6 exercises) |
| **NON-FINDINGS carried intact** | §2c GW-12 adoption, the disjoint-footprint finding, host-GPU-not-Docker (§2d core), §5 citations (incl. Cintala-absent), verification-by-real-observation discipline, the postures-path bug + fix (A6) — all carried forward unchanged, no churn | per council instruction |

**Council findings partially rejected after code check: none.** Every reviewed claim reproduced at
file:line. Two refinements beyond the council text, both from this session's verification: (i) the
unifying fix's open WorkSite question resolves YES but with the streaming-path-exclusivity and
per-tick-`step()` conditions (§2b.1 caveats — `worksite.py:192,389` guards the council did not
cite); (ii) "reuse `RuntimeProcess`" cannot mean attaching Godot to its Unix socket — Godot 4 has no
Unix-domain-socket client (`StreamPeerTCP` is TCP-only, *inferred*; B2 confirms before build), so
the reuse is the handler discipline + checkpoint machinery extended with an additive loopback-TCP
transport.
