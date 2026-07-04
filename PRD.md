# STEWIE PRD: Lunar Construction and Solar-Terrain Autonomy

**Version:** 7.3
**Date:** 2026-06-29
**Status:** CANONICAL — the single source of truth for project design + reference. All other design
documents are archived (`docs/archive/`) or are upstream STEWIE architecture/roadmap sources
(maintained privately; public mapping in §16). The granular execution breakdown lives in the private
workspace: `design/STEWIE_ATOMIC_EXECUTION_PLAN_2026-06-09.md`.
**Baseline commit:** `047331250cf443498c25b5bead4bed167668752c`

> **⚠ ARCHITECTURE PIVOT 2026-07-03 — GeoLibre-style 2D frontend rewrite + pluggable physics/body seams.**
> Aaron's decision, planned by conferring with Codex (max-reasoning). The full plan is
> `docs/geolibre_rewrite_plan_2026-07-03.md` (Claude + Codex reconciled); the migration assessment behind it
> is `docs/geolibre_migration_assessment_2026-07-03.md`. **What changes:** the frontend is rebuilt on a
> GeoLibre-style stack (React/TypeScript + MapLibre GL JS + deck.gl 2D + DuckDB-WASM + Tauri v2); the map is
> **2D only** (no Cesium globe — this deliberately defuses the lunar-CRS-on-an-Earth-engine risk); the Python
> FastAPI backend is **unchanged** and becomes the sidecar (all 140 routes reused); and STEWIE gains two
> first-class extension seams — a **PhysicsBackend** interface (Tier-2 conserved NumPy / Tier-3 Chrono-hybrid /
> future engines, swappable per mission) and a **BodyProfile** registry (Moon/Mars/Ceres/… as versioned
> profiles). **New §7 lanes:** RF (React frontend), GL (GeoLibre 2D map), DW (DuckDB-WASM), AC (API client),
> PX (physics extensibility), BD (body profiles), TU (Tauri desktop), MG (migration governance) — see §7.A.
> **Roadmap:** the phased strangler-fig migration is §10.A. **Honesty note:** the pivot RE-OPENS P0 — the
> pre-pivot backend/cockpit scope's "all P0 complete" still holds, but the rebuild adds NEW P0 foundations
> (AC/RF/GL/PX/BD/MG). The vanilla cockpit stays live and served until React reaches pane-by-pane parity;
> nothing is retired until then. §6 Target Architecture below is rewritten for the two-process shape.

## 0. Where we are / what's next (2026-06-11 — read this first)

**Status (2026-07-01):** STEWIE is one live production platform, deployed on app.stewie.space
(Cloudflare / cloudflared / docker), CI green on `main`. The ConOps spine Plan · Rehearse · Validate ·
Release · Execute · Report is shipped, and the operational world-model loop is now CLOSED: a plan
executes, its conserved terrain delta folds into TerrainMemory, and the next plan reads the remembered
surface through CurrentTerrainView, all recorded in one hash-chained world-transaction log (DT-01 / the
§28 slice). The trainer, planner, and digital-twin product is functionally complete; the flight-autonomy,
arm, live-pit, and Tier-3 tracks remain hardware and host gated.

**Completion snapshot (§7 requirements = 315; live machine counts in STATUS.json / program_snapshot.json / release_manifest.json).** Raw verification glyphs (2026-07-04): 220 verified-done, 20
partial, 75 not-started; 239 are cited by a real `[REQ:]` test; hardware/host-gated rows stay excluded from the in-scope denominator. The
glyphs are ROUGHLY ACCURATE, not a large undercount (a 2026-07-01 audit corrected the earlier
"~38 done-stale" optimism): 33 rows are cited but read V!=D (STATUS.md "V!=D flagged"), yet a citation
does NOT mean done -- the implementation glyph confirms ~32 of those are genuinely partial (I=P/N), a
test legitimately citing a partial row, not a done row awaiting a flip. Excluding the 24 gated rows,
in-scope verified-done is about 52 percent (86 of ~164). Reconciling the two honest bars: the production
spine is functional and DEPLOYED (the product works end to end), but by the strict §7 verified-done bar
many in-scope rows are legitimately partial (hardening, full verification, edge cases), not a glyph-lag
artifact. The honest remaining work splits three ways:

- **Open, in-scope, buildable here:** finish the genuinely-partial in-scope rows (real work + a citing
  test each; NOT a bulk glyph flip -- only ~1 row, FS-15, is impl-done-but-under-verified); finish FS-24
  (5 pure modules extracted this session, the DOM app-shell remainder is by design, not a pure-module
  candidate); the MO-02 live-execute fault-injection tier; GI-01 deployed-browser GIS smoke.
- **Gated, deferred (not unfinished):** the live rclpy node + P23 intern-beta traverse (needs a ROS host
  and a real pit); P7 live Chrono producer + Tier-3 drum forces (needs a PyChrono host); the AS-* flight-
  autonomy stack (the ARGUS / navigation lane); arm geometry (AM-*, VT-03/05, needs LAC/IPEx data); dense
  range/point-cloud PM-13..16 (stereo by default, LiDAR/RGB-D swappable when sensors are available; GPU or
  live sensor host required); CP-07 slip-band fold-in (blocked on the PyChrono calibration oracle); the
  STEWIE-Orbit CCSDS comms stack (intent-only).
- **Bottom line:** the production trainer/planner/twin is essentially finished and live; "finishing the
  program" past this point is mostly the marker-pass hygiene plus the externally-gated flight stack, not
  new in-scope product code.

**Done (build history, retained for provenance):** the three rung-4 gaps (pluggable RC contract + SF-01
safing watchdog #66, telemetry shaping #67, operator/director roles #68); the COLMAP/triage design +
budget ledger (#69); the resync forward-sim (#70); the NASA-standards mechanism (§19: requirements-
traceability + Power-of-10 gates in CI); the 8-agent full-stack audit (§20); the Navigation pose-graph
estimator spine; the cockpit (authoring, worksheet, dashboards, mobile); the Moon coordinate chain.

> **UPDATE 2026-06-14:** item 1 below (**P1 — the navigation bridge**) is **DONE** (§22.3): /localize +
> /slam endpoints, articulation_bridge on /render, and the cockpit Navigation/Estimation view, all
> live-verified. The §23 production-readiness audit Phases 0–2 are also complete and Phase 3 (scale +
> maintain) is in progress. Next: **P3** (surface the evidence) then **P2** (backend closes), alongside
> the Phase-3 audit remainder.

> **UPDATE 2026-06-15:** this PRD was re-checked against the current worktree at
> `ea7574ec3875928075b11072cd32f0c25f3d079d` plus local uncommitted web/deploy hardening. The prior
> P1 navigation bridge is no longer an open queue item; keeping it in the "next" list made the PRD
> contradict itself. The source-of-truth queue below replaces that stale list.
>
> **UPDATE 2026-06-17 (cockpit hardening + convergence frontier, all live on app.stewie.space):**
> two tracks advanced past what this §0 recorded.
> **(A) Trainer/sim surface (forward-item #1) — hardened.** A full cockpit live-debug pass shipped +
> Playwright-verified + deployed: TRAINING-default + data-store wiring, the map coordinate UX (type-in
> lat/long, a floating cursor lat/long readout, crosshair), the Site→…→Execute stepper gates, inline
> vehicle/soil/charger info, the "where are we" locator with a NEW `/dem/site_lonlat` reverse transform
> (site metres → selenographic lat/lon, TDD), the renamed/grouped **🧰 ToolBox**, the Swagger `/docs`
> fix, the CRITICAL working-draft persistence fix, the full **ArcGIS editing toolbox** (distance
> measure · feature notes · landmarks · **circle/box/polygon keep-out barriers with REAL planner
> routing** — `point_in_keepout`/`_apply_keepouts` rasterize all three shapes, TDD 169 planner tests
> green), panel completeness (Admin **invite mint** + the `#invite=` **redeem** flow, Settings
> reset-workspace), and a signed-in mobile sweep (all 8 panes, zero overflow). THIRD_PARTY re-reviewed
> under the all-rights-reserved license (Cesium/swagger/fonts/AprilTag added). Tasks #166–#179, #124,
> #129/#160.
> **(B) Convergence frontiers — now REAL + run-verified (ahead of the queue below).** The PRD's named
> next-contribution items moved from modelled to measured:
> • **ROS2 autonomy seam (the PitBackend transport's STEWIE side, §0 pre-audit queue):** `stewie/bridge`
>   — `/cmd_vel` Twist → RC GoTo through the **SF-01 watchdog**, the `/stewie/odom` `nav_msgs/Odometry`
>   egress, the closed `cmd_vel→sim→odom` loop, and a deployable `stewie-ros2-bridge` service, ALL
>   run-verified on the `stewie-ros2:latest` Jazzy container. Nav2/Autoware plug straight in.
> • **#79 8-cam front-end + shadow-outline landmarks:** the LAC **8-camera rig renders on the RTX 3090**
>   (Godot 4.6.3, `render.sh sidecar.tscn --cameras`) → `panorama.py` 8192×768 heading-ordered surround
>   → `shadow_landmarks.py` real cast-shadow landmarks + azimuth bearings (the Navigation measurement). NOT
>   render-gated on this host. Plus a `sensor_msgs/PointCloud2` perception egress. Tasks #144/#145/#183.
> • **Convergence visualization (cockpit 3D view, live):** the depth/heightfield as a wire overlay,
>   **ephemeris-driven sun + shadows** (`/ephemeris` solar authority + Three.js shadow casting), the
>   **lander rendered with the real tag36h11 AprilTag**, and a **rover HUD** (battery · azimuth compass ·
>   front/rear drum weight · live pose). Tasks #180–#184.
> Still genuinely gated: #185 DA3 monocular producer (model install) and the live Autoware/Nav2 *planner*
> driving through the seam (needs the costmap from the perception egress). Forward-queue items 2/4/5 below
> remain the path to a production-complete twin.
>
> **UPDATE 2026-06-17 (code-grounded §7 reconciliation + PRD-completion drive).** A parallel
> verification sweep re-checked every open §7 row against the actual tree (the paths in older rows
> predate the monorepo move to `code/`; authority is now `stewie/physics/`, specs `stewie/specs/`,
> contracts `stewie/contracts/`). Findings:
> - **The §4.2 release blockers RB-01..06 are effectively CLEARED in code, each with tests** — domain
>   validation + mass-conserving mutation invariants (`stewie/physics/validation.py`,
>   `test_mutation_guards.py`), `trimesh` declared (`pyproject.toml`), ONE immutable fleet-aware
>   `PlanResult` (`test_plan_result.py::test_consumers_reuse_the_one_result_no_recompute`), per-vehicle
>   Plan-IR with an explicit no-position-leak test, the typed `VehicleModel` threaded through the
>   planner/authority (`PlanningContext`; cross-vehicle drum/mass/footprint/endurance diff tests),
>   configurable app-data dirs + atomic writes. **§4.2's "blockers" list is stale; no RB actually
>   blocks** (the residual is per-row §7 marker hygiene, not missing code).
> - **~36 §7 rows are DONE-STALE** (impl + passing tests exist, the row understates): incl. CT-01/03/04/05,
>   PO-02/03/06/07/08, TW-01/02/03/08, VT-01/02/07, NV-01/04/05/08/09/10, CP-02, FL-06, FS-02/06/16,
>   PM-05/06/08/12, EP-03/08. These need a per-row marker pass, not new code.
> - **Closed this drive (TDD, gated, committed):** DT-02 (auth-gated `/twin/version` + director-only
>   `/twin/history`), CT-07 (provenance now stamps source commit + version + seed), PO-13
>   (`stewie.__version__` + CHANGELOG + SemVer), TW-07 (solar incidence-angle compute + tests; cockpit
>   incidence `/layers` raster now surfaced + toggleable -- X closed), ML-01 (`ModelArtifact` typed I/O schemas + inference budgets
>   + a `deployment_ready` gate).
> - **~34 rows are hard-blocked external** and cannot be honestly completed on this host (kept marked,
>   never stubbed): authoritative IPEx/LAC arm-camera-drum geometry (VT-03/05/09/10, AM-01..08, SN-11/15),
>   GPU model weights + render→depth pipeline (PM-04/11/13-16, ML-04, DA3 #185, SuperPoint/LightGlue),
>   McCardle's UDP/ROS link protocol (NV-11/12, FS-05 Autoware tail), LED-hardware photometry (TW-09,
>   SN-06..10 Q-tails), the PyChrono SCM oracle (TM-01, VT-09, Lyasko), and Jetson Orin edge hardware
>   (ML-09). The remaining ~40 doable rows are being closed in priority batches.

> **UPDATE 2026-06-19 — FULL PRD↔CODE RECONCILIATION (FS-22) + the front-end-rewrite episode.** A
> three-front evidence-grounded audit (planner+physics, autonomy+perception, product surface) re-checked
> the §7 matrix + forward stages against the tree. Headline: several long-open items CLOSED, the front-end
> IA REGRESSED (a React rewrite was reverted), the dense-reconstruction tier was UNBLOCKED as a
> demonstrator, and the deep autonomy/comms tiers remain honestly gated. **Intent vs state:** STEWIE's
> intent — a lunar mission-planning + digital-twin + autonomy *environment* whose trainer/sim product
> drives a real rover, plus the Navigation navigation evidence — is **substantially realized as a
> planning + estimation + visualization platform; the live-autonomy and operational-twin tiers are built
> as tested code but not yet deploy-integrated or hardware-passed.**
>
> **Closed since the last reconciliation (statuses corrected — these rows below are now STALE):**
> - **REG-01 DEM site imports → DONE** (was an open functional gap). `site` is a PlanRequest field threaded
>   through plan/timeline/IR/report; Shackleton + Nobile are plannable (`server/routers/plan.py:291`,
>   `stewie/terrain/site_dem.py`, `server/test_dem_site_aware.py`). §20.3/§22.2 "planner hard-targets
>   Haworth" no longer holds.
> - **FORGE → populated** (was "empty package"): `forge/bearing.py` (Terzaghi/Vesic, sourced) + re-export `__init__`.
> - **CP-06 bearing-capacity acceptance → DONE** (the sub-item that pinned CP-06 at "P", line ~532):
>   `validate_plan` reports loose+firmed allowable bearing + holds/firming_recommended, additive, never
>   folded into `feasible` (`lode/planner_acceptance.py` `validate_plan`, an ARCH-2 leaf; re-exported as `MP.validate_plan`). Honest residual: a loose-vs-bank-density proxy,
>   not yet a true FORGE per-cell compaction-state field.
> - **DT-02 `/twin/version` read-auth → DONE** (old forward-item #2). **REG-02 / VT-02 per-vehicle planner
>   numbers → largely DONE** via H-01 (drive/dig/battery/mass threaded; the V=D delta test is the confirm).
>   **PO-14 deployment docs/image → STALE-understated** (DEPLOY.md + compose + Dockerfiles exist + current).
>
> **New capability (real, on disk + verified):** a **3D Terrain** Cesium layer over the real reprojected
> LOLA DEM (`/dem/terrain_grid`) and a **Reconstruction** 3D-Tiles twin layer (`/tiles`) on the cockpit
> globe; and the **dense COLMAP MVS path UNBLOCKED** — a from-source CUDA-12.2 + sm_86 image
> (`scripts/colmap/colmap-src.Dockerfile`, the one combo no prebuilt tag offered) produced a 149,709-pt
> dense cloud (12/12 reg, 0.19 px, 3.3 mm ATE) packed to a georeferenced tileset (`ply_to_3dtiles.py`).
> **Scope caveat:** a *demonstrator on 12 self-rendered Godot arc views of `boulder_field`* placed at the
> site — NOT a reconstruction of a real traverse; **PM-13..16 stay OPEN** (no measurement-vs-truth acceptance).
>
> **Front-end IA — landed via a strangler-fig reorg of the vanilla cockpit (2026-06-23, deployed).** The
> earlier React+Vite rewrite (Phases 0–5, FS-23) had black-screened on a Cesium init bug and was REVERTED
> (`55c44c6`); rather than retry a big-bang rewrite, the vanilla `cockpit.js` was reorganized in place into
> the decided **6-slot ConOps spine: Plan · Rehearse · Validate · Release · Execute · Report** (Validate
> merges the former Navigation + Perception tabs into one tab + a sub-tab strip; Release is a new
> director-gated mission-sign-off surface — `POST /executive/release-plan` drives the current build queue
> through the MO-02 lifecycle to RELEASED, faithfully releasing the full cut/fill/sinter vocabulary via the
> `Objective.order_kind` contract extension), the Plan sidebar consolidated **7 groups → 4**, and the
> role-gated **Fleet / Construction / Models / Trainer** work areas surfaced as first-class secondary tabs —
> so **FS-03's 8-area IA is now substantially realized**. Verified end-to-end (interactive Playwright gate +
> live e2e release + contracts/lode/server suites) and **deployed live to app.stewie.space** (CI green,
> `?v=` cache-bust confirmed `MISS`). Spec + history: `docs/cockpit_reorg_plan_2026-06-23.md`.
>
> **COUNCIL ROUND 2 (2026-06-29): GIS / world-model / security / API correctness, deployed.** A 6-lens
> adversarial council review (17 agents, refute-to-confirm) surfaced 11 verified findings. 7 surgical fixes
> shipped, each TDD-first on REAL Haworth data, deployed and CI-green: **#266** the sun-azimuth true->grid
> mapping is a REFLECTION (not a ~26 deg rotation; off up to ~180 deg at some sun positions) in
> `gis_layers.render`/`render_globe`, **plus #272** the same correction in the `/dem/workarea.png` inset (a
> 3rd `_layer_rgba` consumer that was missed); **#274** mission-time sun geometry now resolves lat+lon per
> site via `sites.site_latlon` (was hardcoded -87.45, wrong even for Haworth at -86.33); **#267**
> `/dem/asbuilt` builds on the as-built remembered surface (shared `state.as_built_dem` with the planner);
> **#269** `run_closed_loop` classifies each leg's telemetry so the SIM watchdog can reach SAFED (the WMDT-L4
> cascade was dead); **#270** the login rate-limiter is no longer bypassed by a forged Authorization/X-API-Key
> header; **#275** `/rc/command` returns 400 (not 500) on a malformed GoTo. **Open from the same review
> (design / decision, NOT done):** #268 user soils are write-only (planner never reads `/soil` back;
> cross-layer, overlaps #242); #273 flat-drive/haul energy is gravity-independent and ~6x over-estimated on
> the Moon (`body_gravity` never reaches `drive_j_per_m`); #276 + #281 the operator-gated `/executive/run`
> forges a director Release sign-off and the MO-02 chain is self-asserted (ConOps decision); #277 + #278
> `TerrainMemory` save is non-atomic and unlocked; #279 per-email lockout griefing; #280 the observed
> `TwinStore` map has no downstream consumer.
>
> **Honest gates (unchanged — NOT passed):** **P20 live ROS2 node / P23 intern beta** — the
> bridge/telemetry/role-split are real tested code + container-run-verified, but the live rclpy node is
> host-gated (rclpy absent) and the P23 "<30 min unassisted Haworth traverse through real RC software" has
> no evidence artifact → "built + container-verified, deploy-integration pending," not "gate passed."
> **P7 live Chrono producer — still a STUB** (`scripts/chrono_scm_export.py:2`); **Tier-3 force-accurate
> drum — OPEN**. (CORRECTED 2026-07-01: **Fleet conflict RESOLUTION + MV precedence-chain splitting is
> DONE**, not open, contradicting the stale text this block used to carry: `lode/planner_multivehicle.py`
> `_resolve_spacetime_crowding` re-sequences work-crowding + haul crossings to a fixed point, and
> `_allocate_precedence_split` / `_resolve_cross_vehicle_precedence` split a chain across vehicles, both
> wired in `planner_assembly` and tested `[REQ:FL-02]` / `[REQ:FL-04]`; §7 FL-02 = D D D D.) **STEWIE-Orbit comms stack —
> intent-only** (only the gated CCSDS Space-Packet RC seam exists; no Proximity-1/AOS-USLP/CFDP/SDLS/Yamcs/
> Foxglove code). **GIS interop GI-03 — PARTIAL** (the in-repo GeoJSON subset is DONE in `lode.gis_export`:
> plan→GeoJSON/COG export, GeoJSON import (`geojson_to_features`), offline mission-package (`mission_package`),
> and feature query (`query_features`); the cockpit-toolbox annotation, COG/GeoTIFF feature import,
> OGC/ArcGIS service consumption, and measurement/profile tools stay OPEN).
>
> **Strongest, fully DONE + tested:** the AG-01..08 governance ladder (whole family), SF-01 safing, NV-11/12
> Plan-IR lowering + stream under AG-08, FS-17 windowing, FS-20 chrome, server hardening (PO-06/07/08),
> CSP/self-hosted-Cesium deploy, the SN-01..10 + P15 + articulation-parallax estimator library, the
> map-channel observability reward, and the AprilTag pose channel (12.7 mm, container-gated qual).
>
> **Corrected forward order (supersedes the 2026-06-15 list below):**
> 1. **Land the front-end IA** — the reverted §11 8-area shell, incrementally on the vanilla cockpit OR a
>    re-attempted rewrite verified SIGNED-IN on a real browser before any flip. Biggest product gap.
> 2. **Deploy-integrate the ROS2 bridge** (P20 live node in the deploy) + capture the P23 intern-beta run.
> 3. **Fleet conflict resolution** (FL-02 re-sequencing) + MV precedence-chain splitting.
> 4. **Operational world-model unification** (DT-01: authority + TwinStore + packets + PlanResult + belief).
> 5. Externally gated (unchanged): Tier-3 drum forces (Chrono::GPU), the live Chrono producer, a
>    real-traverse reconstruction closing PM-13..16, and the STEWIE-Orbit comms stack.

**Forward order:** see the Completion snapshot at the top of §0 (2026-07-01). The 2026-06-15 and
2026-06-19 forward lists that used to sit here are removed as stale: item 1 (front-end IA) shipped as the
ConOps-spine reorg, item 3 (fleet resolution) and item 5 / DT-01 (world-model unification) are done, and
items 2/4/5's residue is the gated tail the snapshot enumerates.

The pre-audit queue (still valid, lower priority): the real-pit `PitBackend` over the UDP/ROS
transport (awaiting McCardle's link details); the mission-brief packet (§8); the Navigation SE(3)+IMU
upgrade and the construction-autonomy + perception roadmap (#79: docking/berm autonomy, RL on the
multi-objective/multi-vehicle frontier, 8-cam feature front-end, shadow-outline landmark learning).

**Production readiness:** useful trainer/simulator prototype, but not a production release. The
trainer/simulator surface has many completed slices; the flight-autonomy stack, security posture,
truth-free SLAM/Navigation path, operational digital twin, and field-calibrated terramechanics remain earlier.

**SN / Navigation evidence path — DONE (2026-06-11):** CP-01 (release-ready), SN-02 detection front-end,
SN-03 shadow yaw factor, SN-05 illumination route cost, SN-06 camera selection, SN-08 active-morphology
posture + SN-08b full posture×load coverage, all shipped TDD + flipped on citing tests. SN family now
SN-01 D, SN-02 D, SN-03 D, SN-04 D, SN-05 P, SN-06 D, SN-08 D, SN-09 D (articulated self-shadow:
a commanded posture change cancels the unknown casting height -> exact sun-elevation/slope), SN-10 D
(articulation-parallax triangulation: a known pose-change baseline -> heading-free standstill position
fix); SN-07's LED-budget selection POLICY is now built + tested (I=X=D, #91); only its real-photometry
validation (V) + the LED hardware (Q=G) remain. Improvement attributed vs baseline across
**16 executed notebooks** (real data, Colab-friendly): position 28× (real Katwijk 160→5.7 m), heading
6.2× with an honest crossover, camera 100% vs 71% at low sun, viewpoint 0.20 m vs 0, posture×load
cross-load-tip safety, articulation sun-elevation exact vs 0.55–3.2° static bias, and a heading-free
position fix 0.0 vs 1.64 m under 8° drift (bounds real DR drift 160→1.3 m). **Camera-feasible**: the
pixel shift dv=fx·dh/R on the real IMX547+6 mm gives 88 px @5 m, >1 px to ~440 m; the ~0.20 m
pose-driven elevation gain is the baseline. **ARTICULATION INSTRUMENT TIE-IN**: estimator
(`articulation_localize` -> live PoseGraphSE2) and **Godot render/sensor** (`stewie/godot/articulation_bridge`
render-at-posture capture -> pixel measurement -> estimator) both wired + TDD. **Posture models
RECONCILED**: the parallax dh now sources from `posture_kinematics` (sourced render FK) everywhere, with
a cross-module consistency test. Findings: `FINDINGS_2026-06-11_SN_evidence_path.md` (+ `.pdf`).

**ARGUS/NAV Lab integration boundary — UPDATED (2026-06-26):** `docs/argus_navigation_integration.md`
is now the Navigation integration plan. Stanford NAV Lab / Adam Dai is the full-stack baseline for
stereo VO, DEM anchoring, loop closure, neural terrain/radiance maps, and IPEx digital-twin autonomy.
STEWIE's protected Navigation lane is narrower: construction-rover posture as a commanded localization
action, articulation-created parallax as a local position cue, shadow direction as yaw, shadow length and
shadow boundaries as queued research channels, and localization on terrain the rover changes. New
Navigation producers must emit typed `MeasurementFactor` records with factor type, covariance, frame,
source, and evidence class; modeled cue runs may not be reported as measured-cue results. Current
metric-shadow guardrail: shadow length and shadow-boundary registration remain proposed or modeled until
the negative `sigma_n_two_split_2026-06-24` status is replaced by a passing residual-coverage artifact.

**STEWIE world-model / digital-twin architecture loop — UPDATED 2026-06-29:** the current implementation
graph (`docs/stewie_digital_twin_interaction_map_2026-06-28.md`) has 51 current interactions and is the
implementation-status map. The new Phase 1 v2 coverage map
(`docs/stewie_interaction_layer_phase1_v2_current_2026-06-29.md`) accounts for the full 60-row target
taxonomy using current STEWIE names, with status counts of 8 complete, 22 partial, 9 started, 18 planned,
and 3 sim-only rows. The reference architecture using current names is
`docs/stewie_layered_reference_architecture_current_2026-06-29.md`, and the gap analysis is
`docs/stewie_wm_dt_architecture_gap_analysis_2026-06-29.md`. The next implementation target is not a
large standalone framework: it is the six-layer executable slice loop in §28, organized for parallel
agents and Graphify-backed status updates.

(The 2026-06-11 "next session" and "completed plan" SN/navigation session logs that used to close §0
are removed here as stale; they remain in git history and `session_notes/`. Current forward work is the
Completion snapshot at the top of §0.)

## 1. Purpose

STEWIE is a lunar construction-planning and digital-twin platform for an IPEx/RASSOR-lineage
excavator. It must:

1. load real or generated terrain;
2. author construction goals and constraints;
3. produce a physically valid, energy-aware plan;
4. simulate and visualize execution;
5. emit a mission-control report and machine-consumable plan;
6. support a progression from simulated autonomy to sensor-driven navigation and execution.

The next product expansion is **solar-terrain autonomy**: use terrain shape, terrain changes,
low-sun illumination, shadow geometry, camera/LED selection, and articulated-arm posture to improve
mapping, localization, route safety, and construction execution.

This PRD replaces the June 4 v5 document. Historical stage narratives remain available through Git
history. Current status is based on:

- [`docs/architecture_review_2026-06-06_full.md`](docs/architecture_review_2026-06-06_full.md)
- [`docs/prd_gap_analysis_2026-06-06.md`](docs/prd_gap_analysis_2026-06-06.md)
- the current repository and locally executed verification described by those reviews.

The conserved terramechanics authority retains John McCardle's CC0 provenance. STEWIE's product,
planner, Gymnasium, vehicle, perception, and visualization layers build on that authority.

## 2. Source Discipline

Every physical or operational claim must carry one of these evidence classes:

| Tag | Meaning |
|---|---|
| `[SPEC]` | Directly stated by an authoritative NASA, LAC, standards, or peer-reviewed source. |
| `[MEASURED]` | Measured by STEWIE or a cited experiment with reproducible conditions. |
| `[CALIB]` | Calibrated model value with a documented data source and fitting procedure. |
| `[ASSUMPTION]` | Deliberate engineering assumption exposed through configuration. |
| `[PROPOSED]` | New behavior or algorithm that must be validated before capability claims. |
| `[UNKNOWN]` | Required parameter or behavior for which no defensible value is available. |

### 2.1 New references

**[NAVLAB26]** A. Dai et al., *Full Stack Navigation, Mapping, and Planning for the Lunar
Autonomy Challenge*, arXiv:2603.17232v1, March 18, 2026. Local review copy:
`/home/aaron/Downloads/2603.17232v1.pdf`. Publication page:
`https://arxiv.org/abs/2603.17232`.

This paper provides a validated LAC simulator reference architecture:

- semantic segmentation;
- SuperPoint + LightGlue feature matching;
- stereo visual odometry using triangulation and `solvePnPRansac`;
- GTSAM pose-graph optimization and loop closure;
- median-cell terrain mapping and majority-vote rock mapping;
- overlapping-loop/outward-spiral coverage planning;
- constant-curvature local arc sampling;
- reverse-and-replan recovery when progress collapses.

Its reported localization RMSE was approximately `0.038-0.067 m` across documented presets and
seeds. Those results are a benchmark, not evidence that STEWIE currently achieves them.

**[IPEx-DT-REF]** *IPEx Rover: Architectural Review & Digital-Twin / World-Model Reference*.
Local working reference:
`/home/aaron/Downloads/IPEx_Rover_Architecture_DigitalTwin_Reference.md`.

This is a secondary synthesis. Statements marked `[SPEC]` in that document must still be traced to
its listed NASA/LAC source before becoming fixed model constants. Statements marked `[EST]` there
are treated as `[PROPOSED]` or `[ASSUMPTION]` here.

### 2.2 Solar-navigation claim boundary

The NavLab paper establishes robust navigation under variable lunar lighting. It does **not**
establish shadow-azimuth heading, arm-controlled solar observation, or Meerkat solar navigation.
Those are proposed STEWIE product requirements derived from the IPEx/LAC platform
capabilities and south-pole lighting environment.

## 3. Status Model

A single checkmark is not sufficient. Every requirement carries four independent states:

| Column | Meaning |
|---|---|
| `I` | Implementation exists. |
| `X` | Integrated into the advertised product path. |
| `V` | Automated acceptance verifies the stated behavior. |
| `Q` | Qualified with representative external data, hardware, or deployment evidence. |

Values:

- `D`: done for the stated scope;
- `P`: partial;
- `N`: not done;
- `G`: externally gated;
- `NA`: qualification does not apply.

A requirement is release-ready only when its required columns are `D`. Research prototypes may
have `I=D` while `X`, `V`, or `Q` remain partial.

## 4. Current Product Truth

### 4.1 Working foundations

- Conserved mass-per-area terrain authority with derived height.
- Bekker/slip/sinkage mobility and mass-conserving earthmoving.
- Seeded Gymnasium environments and high Python source coverage.
- Real Haworth LOLA terrain bundle and non-polar reprojection library.
- Structure templates, cut/fill balancing, multiple sequence optimizers, precedence, and reports.
- Godot terrain/rover rendering and a browser planning cockpit.
- Versioned Plan IR and a simulated belief/replan loop.
- Initial fleet allocation and parallel makespan calculation.

### 4.2 Release blockers

> **RECONCILED 2026-06-20 (see §27.1):** RB-01..06 are **effectively cleared in code, each with citing
> tests** (per the §0 2026-06-17 reconciliation: domain validation + mutation invariants, declared
> `trimesh`, one immutable fleet-aware `PlanResult`, per-vehicle Plan-IR no-position-leak test, typed
> `VehicleModel` threaded through, externalized atomic data dirs). **No RB actually blocks.** The
> residual is per-row §7 marker hygiene, scheduled as OPS-04 (the `[REQ:]` marker pass), not missing
> code. The table below is kept for historical traceability.

| ID | Blocker | Required exit |
|---|---|---|
| RB-01 | Negative/non-finite physical values and malformed authority state are accepted. | Shared domain validation at every public boundary; mutation invariants enforced. |
| RB-02 | The configured test suite cannot collect because `trimesh` is undeclared; CI excludes that path. | Declared dependency/marker policy and CI running the configured suite. |
| RB-03 | Fleet totals, timeline, autonomy, validation, and UI do not represent one plan. | One immutable fleet-aware `PlanResult` consumed by all outputs. |
| RB-04 | Multi-vehicle Plan IR leaks position between vehicles. | Per-vehicle state ledger and route/energy tests. |
| RB-05 | Vehicle selection does not drive end-to-end mass, contact, energy, and capacity. | Typed `VehicleModel` threaded through authority, planner, Plan IR, and rendering. |
| RB-06 | The installed server has incomplete dependencies, assets, and writable storage assumptions. | Fresh-wheel server smoke test with externalized data directories and explicit asset mode. |

No production-grade release may be declared while any `RB-*` item is open.

## 5. Product Modes

STEWIE supports five explicitly distinct modes (revised 2026-06-10 -- the earlier four-verb table
undersold what each mode now is):

| Mode | What it actually is | Reads / writes | Truth boundary |
|---|---|---|---|
| `GIS-PLAN` | 2D layered planning on the real Haworth DEM: slope / hazard-no-go / horizon-clipped shadow / PSR rasters under an auto sun driven by mission time; build-queue authoring, keep-outs, fleet + vehicle selection; output = routed, energy-budgeted Plan IR + the 2-page mission-control report. | reads WorldState + VehicleModel; writes PlanResult | model-based forecast over VALIDATED terrain/vehicle data; every figure traces to a tagged constant |
| `TRAIN` | Operator/director sessions over the real closed loop: the operator sees only telemetry-DELIVERED, truth-denylisted legs under a mission link profile (bandwidth/latency/drop); the director gets full state, seen-vs-actual divergence, debrief + summary artifacts; authored scenario library with tested teaching points. | reads PlanResult + WorldState; writes SessionRecord | the operator path is STRUCTURALLY truth-isolated (file-layer + field denylist); fast-forward never alters link accounting |
| `SIM-OPERATE` | The live loop on the conserved authority: the persistent runtime owns ONE world that outlives clients; ROS2 teleop (/cmd_vel through slip-aware physics) and goal-level CCSDS tasks; strict canonical packets carry real IMU/wheel/power channels, the 8-camera rig, work-light state + exact poses; checkpoint/restore bit-exact. | mutates WorldState via physics verbs ONLY; writes RuntimePackets + ExecutionEvents | simulation only -- no live-hardware claim; producer packets carry NO truth fields (strict-parser enforced) |
| `EVALUATE` | The honesty machinery: hash-anchored evidence corpora, role-isolated produce->estimate->evaluate (the estimator is structurally DENIED truth), geometric depth truth, gate checks that flip ONLY via dated code-enforced artifacts; real-sensor scoring (Katwijk vs RTK). | reads everything incl. truth; writes dated validation artifacts | the ONLY mode with truth access; its artifacts are append-only and byte-pinned |
| `OPERATE` | Consume real telemetry and issue commands to hardware. | -- | FUTURE; unavailable until command, timing, safety, and fault requirements pass |

The API and reports must label the active mode. Simulated truth must never be presented as a live
measurement.

## 6. Target Architecture

The rebuilt system is TWO processes (2026-07-03 pivot): a Python **compute/authority backend** (UNCHANGED --
the FastAPI sidecar, all 140 routes, DART/LODE/LEAP/FORGE, physics, RL, planner, runtime spine, digital twin)
and a React **operator frontend** (the 2D GeoLibre-style cockpit). The layered stack below is the backend
compute stack (L0-L6) plus the new frontend product layers (L7-L8). Physics is now a PLUGGABLE authority (L1)
and body data is a PROFILE registry (L0). Client state may author intent and view results, but conserved
terrain mutation happens ONLY through the backend authority path (§6.1, §6.2). Full design:
`docs/geolibre_rewrite_plan_2026-07-03.md`.

```text
L8  Product shells
    web deployment + Tauri v2 desktop, both the same React/TypeScript app

L7  Operator cockpit + GIS workbench
    React ConOps panes / MapLibre + deck.gl 2D projected map (no globe) / DuckDB-WASM query workbench /
    generated API client / route-to-pane registry / provenance + mode + authority labels

L6  Mission and fleet planning
    goals / structures / PlanResult / resources / acceptance / Plan IR / body + physics-backend selection

L5  Navigation and execution
    coverage planner / local planner / tracker / recovery / executive / command eligibility

L4  Perception and localization
    camera policy / segmentation / stereo VO / SLAM / observed layers / solar factors

L3  Vehicle digital twin
    VehicleTwin / ArmState / drums / per-drum load / CG / support polygon / work lights / camera rig

L2  Terrain, illumination, and world state
    FR-10 LayerManifest / conserved terrain / observed twin / rocks / uncertainty / sun vector / shadows

L1  Pluggable physics authority  (NEW seam: PhysicsBackend interface)
    Tier-2 NumPy conserved authority / Tier-3 Chrono-hybrid (geometry-oracle until it conserves mass) /
    future engines -- selectable per mission/body; a non-conserving backend is refused for release/execute

L0  Contracts and profiles
    units / schemas / time / frames / provenance / invariant enforcement /
    BodyProfile registry (NEW seam) / PhysicsBackend contracts / authority labels
```

### 6.1 Authoritative artifacts

The architecture must have these single-source runtime artifacts:

1. `WorldState`: terrain, material, rocks, illumination, uncertainty, time, and frame metadata.
2. `VehicleState`: pose, velocity, arm angles, per-drum fill, battery, thermal/dust state, and health.
3. `VehicleModel`: geometry, mass properties, contact, capacity, actuators, sensors, and power.
4. `BeliefState`: estimated state and covariance, separate from simulator truth.
5. `PlanResult`: fleet allocation, routes, actions, timeline, resources, acceptance, and provenance.
6. `ExecutionEvent`: command, observation, acknowledgement, fault, replan, and state-transition record.

7. `TwinStore` (NEW 2026-06-10): the versioned OBSERVED-terrain layer log -- immutable base +
   append-only, hash-chained, provenance-mandatory edit events; the current map is derived by
   replay; undo is itself an event. The perception/resync channel writes HERE, never to the
   conserved authority.
8. `RuntimePacket`: the strict canonical sensor packet (one clock, closed channel set, truth-scan
   enforced) -- the ONLY surface estimators see.
9. `SessionRecord`: a training session's recorded legs + link accounting + debrief/divergence.
10. `LayerManifest` (FR-10, implemented): the typed per-layer catalog `/world` carries and the planner +
    the React map consume; the single layer authority (no client-only catalog).
11. `BodyProfile` (NEW seam BD): a versioned body/regolith/CRS profile with per-field provenance, replacing
    direct `BODIES`-dict coupling; missing numeric fields are `null` + labeled, never fabricated.
12. `PhysicsBackendInfo` + `PhysicsBackendSelection` (NEW seam PX): the selected physics engine per
    mission/body, recorded in `PlanResult` / report / release evidence; carries `conserves_mass` +
    `authority_class` so release/execute can refuse a non-conserving backend.
13. `ApiRouteRegistry` (NEW lane AC): generated typed client coverage for all 140 router-owned routes, with
    per-route pane ownership, auth, response kind, provenance, and mutation flags.
14. `SpatialQueryWorkspace` (NEW lane DW): the DuckDB-WASM loaded catalog + query state -- advisory/display
    only until a result is written back through a backend route.

Reports, Plan IR, playback, validation, and autonomy must be views over these artifacts, not
independent recomputations.

### 6.2 World-state layering, storage, and backups (added 2026-06-10)

**The rule: every change made on the Moon is a LAYER in world state, never an overwrite.** Two
change channels, both already event-layered:

| Channel | What changes it | Storage today (implemented) |
|---|---|---|
| CONSERVED authority (the physical Moon) | physics verbs only -- dig, dump, drive ruts, compaction | "store history, not terrain": L0 orbital base + the L4 excavation-event log -> terrain DERIVED by replay (stewie/twin world model); mass conservation asserted at 1e-12 |
| OBSERVED twin (what we believe the surface is) | perception resync patches (POST /twin/resync), operator edits | TwinStore: append-only sha256 hash-chained events, provenance REQUIRED, undo-as-event, byte-exact rebuild proven by test |

Snapshots that exist today: runtime checkpoint/restore (npz, bit-exact by mass-sha test);
io_fields scene snapshots (atomic); Seam-1 rasters (frozen contract); the hash-anchored evidence
manifests (evaluation side).

**HONEST GAPS (the answer to "have we figured out storage? backups?" is: layering yes, durability
partially, backups NO):**

| Req | Gap | Requirement |
|---|---|---|
| W-1 | TwinStore's event log lives IN-PROCESS; a crash between checkpoints loses observed-twin edits | per-edit durable append (journal file, fsync-on-event) under data_dir/twin/ |
| W-2 | checkpoints are manual/on-demand; no cadence, no retention | scheduled snapshots (per sol + per N events) with a retention ladder (hourly->daily->weekly) |
| W-3 | everything lives on ONE host/volume | off-host replication of journals + snapshots (second host or remote store); RPO documented |
| W-4 | restore has never been drilled end-to-end from cold | a recovery test in CI: rebuild from journal+snapshot reproduces the world sha bit-exact |

W-1..W-4 are the data-management spine of Year-1 Ph.3 (the acquisition-inventory phase already
planned there); W-1 and W-4 are small and should land with the next runtime slice.

## 7. Requirements

### 7.A GeoLibre-style frontend rewrite + extensibility seams (2026-07-03 pivot)

These lanes track the 2026-07-03 rewrite (design: `docs/geolibre_rewrite_plan_2026-07-03.md`). The backend
lanes (§7.1-§7.17) are UNCHANGED — the FastAPI core is reused. The vanilla-cockpit rows (FR-16..21 mobile +
the pane/shell FR/FS rows) are SUPERSEDED by RF/GL and marked migrated as each React pane reaches parity; they
are not deleted (history) and stay valid until the vanilla cockpit retires (MG-03). Roadmap: §10.A. Lane keys:
RF React frontend · GL GeoLibre 2D map · DW DuckDB-WASM · AC API client · PX physics · BD body profiles ·
TU Tauri desktop · MG migration governance.

| ID | P | Requirement and acceptance | I | X | V | Q |
| --- | --- | --- | --- | --- | --- | --- |
| AC-01 | P0 | Generate a TypeScript API client from live `/openapi.json`; CI fails on generated-vs-FastAPI path drift. Every one of the 140 router-owned routes has a registry entry or an explicit static/internal exemption. | N | N | N | NA |
| AC-02 | P0 | The route registry records per-route pane ownership, auth/role, response kind, provenance requirement, fixtures, and authority-mutation flag; a pane-backed route missing fixture/role/provenance fails. | N | N | N | NA |
| RF-01 | P0 | React shell implements the same 13 pane identities + role visibility as the vanilla cockpit; signed-in browser tests open all 13 panes at desktop + phone widths. | N | N | N | NA |
| RF-02 | P0 | React workspace state carries mission/site/body/vehicle/physics-backend/product-mode/runnable-profile/source-class/work-area; URL+state round-trip; Release/Execute refuse mismatched profile/backend states. | N | N | N | NA |
| RF-03 | P1 | Each migrated pane ships empty/error/loading/mobile fixtures + a signed-in Playwright parity test vs the vanilla pane before it is flipped. | N | N | N | NA |
| GL-01 | P0 | 2D MapLibre/deck workbench renders the selected site DEM + FR-10 layers in the local order frame; control points round-trip through `/dem/site_xy` + `/dem/site_lonlat` within tolerance; no WGS84/Earth claim on lunar coordinates. | N | N | N | NA |
| GL-02 | P1 | Map identify/measure/edit sessions operate on deck layers and write mission edits ONLY through backend routes; a keep-out drawn on the map appears in the mission request and routes around it. | N | N | N | NA |
| DW-01 | P1 | DuckDB-WASM loads the FR-10 manifest + a vector mission package into queryable tables carrying display/planning/release/execute eligibility; a display-only layer cannot be marked planning-valid. | N | N | N | NA |
| DW-02 | P2 | Client query panel supports bbox/provenance/eligibility queries within a defined browser memory + latency budget on Haworth-scale data; degrades to an optional panel if the budget is exceeded. | N | N | N | NA |
| PX-01 | P0 | Define the `PhysicsBackend` protocol + a `tier2_numpy` adapter over the existing terramechanics/FORGE/planner-context functions; Moon Tier-2 `/plan` output is byte-compatible or diff-reviewed; microgravity refusal stays fail-closed. | D | D | D | NA |
| PX-02 | P1 | Mission/profile schema carries `physics_backend_id`; `/physics/backends` exposes backend support/authority-class/conserves_mass; the selected backend appears in plan/report/release evidence. | D | D | D | NA |
| PX-03 | P2 | The Chrono SCM backend is exposed ONLY as geometry-oracle/hybrid until mass-conservation closure; it cannot be selected for release/execute authority while conserves_mass=false. | N | N | N | NA |
| BD-01 | P0 | Convert the BODIES constants into versioned BodyProfile records with NO value changes; Moon/Mars/Ceres/Bennu/Phobos/Earth/BP-1 profiles match bodies.py and params_for_body compatibility is test-proven. | D | D | D | NA |
| BD-02 | P1 | The body registry supports built-in JSON + local profile paths with provenance + duplicate-id rules; invalid/missing provenance or a fabricated numeric field is rejected. | N | N | N | NA |
| BD-03 | P1 | The body/profile UI (Plan + Models panes) shows body selector + soil override + physics-backend selector + support verdict + regime refusal + a body-by-backend compatibility matrix. | N | N | N | NA |
| TU-01 | P1 | The Tauri v2 app starts/connects the FastAPI sidecar and surfaces health/logs/version; cold start reaches `/healthz` + `/auth/config`; sidecar failure produces a SystemPane degraded state, never fabricated data. | N | N | N | NA |
| MG-01 | P0 | The vanilla cockpit stays served + deployable until React parity gates pass (`/app` vanilla, `/app2` React); its smoke tests keep passing throughout the migration. | N | N | N | NA |
| MG-02 | P0 | No pane is flipped vanilla to React without signed-in Playwright parity + fixtures + mobile fit + route-registry coverage + a rollback route. | N | N | N | NA |
| MG-03 | P2 | Vanilla-cockpit retirement: `/app` flips to React only after the full signed-in Playwright suite passes desktop+mobile, the backend suite stays green, route coverage is 100% for pane-backed routes, and Cesium is removed from the active surface. | N | N | N | NA |
| MG-04 | P0 | The `/program` requirements board (`program.html` + `program_board.js`) is responsive at phone widths — >=44px touch targets, single-column row-chip stack, no horizontal overflow, filter deck + inspect panel collapse/stack. Verify via Playwright at 320/360/390/430 px. | N | N | N | NA |

### 7.B Platform restructure backlog (2026-07-03, platform-first, Codex-conferred)

STEWIE is the **planetary digital engineering platform**; ARGUS is a reference estimator component inside it
(NOT the organizing goal). The 2026-07-03 architecture session found the platform spine is **already built**
(~80-85% backend, ~70-75% frontend): the conserved authority (§7.1 CT-*, `stewie/physics/column_state.py` +
`terramechanics.py` + `forge/bearing.py`), the event-sourced twin (§7.2 TW-*, `stewie/twin/versioned.py` +
`terrain_memory.py`), the runtime/reconcile spine (§7.14 RS-*, `replay_loop.py` + `lode/resync.py`), the 38
typed `Contract` subclasses, the 35-router/140-route API, and the FS-16 context-first cockpit are done. This
lane is the genuinely-NEW work: extension seams → packaging → the Demo-001 platform proof, plus later-stage
platform scope. Design: `docs/prd_reorg_spec_2026-07-03.md` + `docs/backend_/frontend_architectural_review`.
**Dependency order (strangler-fig, on a branch, full-gate each row):** BD-04 → PX-04 → {PX-05, AP-01 parallel}
→ PO-16 → PO-17 → PO-18 → DE-01. Frontend lanes (RF/GL/DW/AC/TU/MG) run in parallel (disjoint files).

| ID | P | Requirement and acceptance | I | X | V | Q |
| --- | --- | --- | --- | --- | --- | --- |
| BD-04 | P0 | Break the inverted `bodies→physics` edge: introduce dependency-neutral `BodyProfile`/`RegolithProfile` raw records; `stewie.specs.bodies` imports no `stewie.physics`; `params_for_body` becomes a compatibility wrapper; built-in body values unchanged; microgravity refusal stays fail-closed; an import-boundary test proves the break. | D | D | D | NA |
| PX-04 | P0 | Define `PhysicsBackend` protocol + `Tier2NumpyBackend` over existing terramechanics/`forge.bearing`/planner-context; Moon/BP-1 `/plan` byte-compatible or diff-reviewed; support verdict reports authority_class + conserves_mass; no learned/client component mutates terrain. | D | D | D | NA |
| PX-05 | P0 | Lock the production physics import boundary: an executable test proves production `stewie/physics` imports no `dart`/`leap` (corrects the stale docs claim); the three coupled *test* files are relocated/marked so the `stewie-forge` unit gate needs no dart/leap. | D | D | D | NA |
| PX-06 | P0 | Break the `terramechanics` -> `stewie.specs.constants` edge (prerequisite for PO-18's bodies+numeric-only `stewie-forge`). `terramechanics` carries forge-local literal geotech defaults (the 13 K.* values: K_C/K_PHI/N_SINKAGE/COHESION/PHI/K_SHEAR/SLIP_C1/SLIP_C2/RHO_SURFACE/RHO_DEEP/ROVER_MASS_DRY_KG/N_WHEELS/g); the config-overlay path is PRESERVED by injecting config-overlaid values at the stewie-side call sites (dependency inversion), so runtime behavior is byte-identical. Acceptance: production `stewie/physics/terramechanics` imports no `stewie.specs.constants` at module level ([REQ:PX-06] AST guard, extends PX-05); `TerramechanicsParams.from_constants()` values unchanged; a `config` override of a geotech constant still reaches the built params via the injection path; physics + lode regression green. | D | D | D | NA |
| AP-01 | P0 | Move composing runtime/API code that imports `dart`/`leap` (`nav_loop`, `replay_loop`, `evidence`/`siteplan` routers) out of the future `stewie-core` boundary into the app layer; route URLs + RS-04 behavior unchanged; `stewie-core` subset imports no dart/lode/leap. | D | D | D | NA |
| PO-16 | P0 | uv/hatch workspace skeleton (after BD/PX/AP boundaries pass); editable install + current suite green; import-boundary policy encoded (bodies→none, forge→bodies+numeric, apps→everything); public build targets are `stewie-bodies` + `stewie-forge` ONLY; root stays monorepo. | D | D | D | NA |
| PO-17 | P0 | Extract/publish-prep `stewie-bodies` from the dependency-neutral registry: imports no STEWIE internals; JSON/YAML profiles round-trip; Moon/Mars/Earth golden gravity/profile tests pass; no fabricated numeric fields. | D | D | D | NA |
| PO-18 | P0 | Extract/publish-prep `stewie-forge` from pure geotech/terramechanics + `PhysicsBackend`: depends only on `stewie-bodies` + numeric stack; concept-first API (`estimate_sinkage`/`estimate_bearing_capacity`); Chrono optional, not release authority while `conserves_mass=false`. | D | D | D | NA |
| DE-01 | P0 | Demo 001 — one IPEx-dig vertical slice proving the platform loop end-to-end from existing code: body/profile + selected physics backend → plan → conserved execution/terrain-memory transaction → `RegolithVolumeEstimate` reconcile → report/evidence artifact, deterministic, `[REQ:DE-01]` test, no synthetic/fabricated values. | D | D | D | NA |
| BR-01 | P2 | Named world branches generalize the conserved/observed split into actual/observed/predicted/sim/design/what-if with diff/merge/promotion; mass-conservation precondition gates terrain-mutating promotion. | N | N | N | NA |
| CF-01 | P2 | Capability-fleet model generalizes the multi-vehicle planner to heterogeneous Asset/Capability; the matrix drives assignment + UI; current `VehicleState`/fleet rows remain the source. | N | N | N | NA |
| PG-01 | P2 | PostgreSQL/PostGIS as a durable persistence/projection layer, NOT authority: `TwinStore` events mirror to a PostGIS projection; the conserved model still mutates truth. | N | N | N | NA |
| MI-01 | P3 | Multi-engine planetary IDE: the Tauri shell hosts the web cockpit and may orchestrate Godot/RViz as context-synced panels; the web cockpit stays the operator shell; native engines are sidecars. | N | N | N | NA |

### 7.C Environment-governed operations + control backend (2026-07-03, see §29)

| ID | P | Requirement and acceptance | I | X | V | Q |
|----|---|----------------------------|---|---|---|---|
| EG-01 | P0 | Environment modes as a typed model: `EnvironmentMode` = DEV/TRAINING/REHEARSAL/LIVE/REPLAY/ARCHIVE + a per-mode authority matrix over 7 flags (command-real-robot / modify-accepted-world / create-branches / publish / delete / simulate / approve-merges), encoded per §29.1. Acceptance: the matrix contract + a test asserting each mode's flags (LIVE alone commands robots; REPLAY/ARCHIVE fully read-only). | D | D | D | NA |
| EG-02 | P0 | Central mode-authority ENFORCEMENT: every world-write + asset-command routes through one guard that rejects the action unless the active mode grants it. Acceptance: a TRAINING-mode write to accepted/live world is rejected, a non-LIVE command to a real asset is rejected, and a cross-mode isolation test proves training cannot reach live world state. | D | D | D | NA |
| EG-03 | P0 | Database/branch isolation: `stewie_{dev,training,live,archive}` with per-store branches (actual_world/simulation/training/replay/what_if); LIVE physically separate. Acceptance: a training-branch write cannot land in the live actual_world store (isolation test); the store a session resolves is a function of its mode. | D | D | D | NA |
| EG-04 | P1 | Role/permission model: Admin/SafetyOfficer/MissionDirector/Operator/Planner/Scientist/Engineer/Trainer/Trainee/Viewer/AIAgent + a per-role permission set + explicit live-command eligibility. Acceptance: role floors enforced (Viewer read-only, Trainee training-only, Engineer non-live-only, SafetyOfficer approves live transitions); test. | D | D | D | NA |
| EG-05 | P0 | Training-to-live gate: the 8-step sequence (mission→sim branch→rehearsal→physics→safety→human approval→live token→bridge unlock) mints a live-execution TOKEN; execution-service unlocks the command bridge only with a valid token. Acceptance: a mission cannot issue a live command without a token derived from steps 1-7; test. | D | D | D | NA |
| EG-06 | P0 | Command-safety pipeline: UI→mission-service(validate)→safety-service(constraints)→execution-service(mode)→ROS2 bridge→audit. Invariant: no UI panel commands ROS2 directly; execution-service is the sole egress. Acceptance: a command skipping any stage is rejected; test proves the single egress. | D | D | D | NA |
| EG-07 | P1 | Immutable audit trail: every critical action records who/what/when/where/mode/reason/before-state/after-state/evidence, append-only + hash-chained (extends the TwinStore journal). Acceptance: a live command, a merge, and a config change each emit a record carrying all 9 fields; tamper is detectable; test. | D | D | D | NA |
| EG-08 | P1 | Reconciliation lifecycle: `observed→compared→proposed→reviewed→accepted/rejected→applied→archived` with confidence + model/sensor error flags. Acceptance: a proposal advances the states; a rejected proposal never mutates accepted truth; a manual override is logged; test. | D | D | D | NA |
| EG-09 | P1 | Backend service separation: the 12 bounded services (config/auth/world/mission/asset/physics/sim/execution/reconcile/training/audit/admin) with an explicit import-DAG (extends §7.B); execution-service alone imports the ROS2 bridge. Acceptance: an import-boundary test asserts the DAG (no cross-service back-edges; sole ROS2 egress). | D | D | D | NA |
| EG-10 | P2 | Admin/control-backend taxonomy: the 13 sections (§29.8) as role-gated admin panels, each reading only its service. Acceptance: each section routes to its service data; a role without authority cannot see/act on a section; test. | N | N | N | NA |
| EG-11 | P0 | Safety-control layer: e-stop, live-command lock, geofences, speed/dig-depth/slope limits, battery minimums, comms-loss behavior, collision constraints, abort rules. No live execution bypasses it. Acceptance: each limit rejects an out-of-bound command, e-stop halts, comms-loss triggers the defined behavior; test. | D | D | D | NA |
| EG-12 | P1 | Physics/model control: backend selection (analytical/Chrono, PX-04), model versioning, freeze-validated, per-body/regolith profiles, calibration + validation status. Acceptance: the frozen validated model is the LIVE default; a deprecated/unvalidated model cannot be selected for LIVE; test. | D | D | D | NA |

### 7.D Mission-planning engine (2026-07-03, see §30)

| ID | P | Requirement and acceptance | I | X | V | Q |
|----|---|----------------------------|---|---|---|---|
| MP-05 | P1 | Mission-planning object model: intent/mission/task/task_dependency/plan/plan_candidate/assignment/resource_budget/risk_assessment/rehearsal_result/execution_policy/plan_decision as strict typed contracts, provenance + transaction-linked to the world-model store. Acceptance: each is a Contract subclass; a plan round-trips through the store carrying its decision + provenance; test. | D | D | D | NA |
| MP-06 | P1 | The intent-to-world planning FLOW: Intent→Tasks→Capability matching→Candidate plans→Physics scoring→Rehearsal→Approval→Execution→Reconciliation→Updated world model, deterministic on existing code (ties DE-01). Acceptance: a mission drives the full flow end-to-end producing an updated world + a report; test. | D | D | D | NA |
| MP-07 | P0 | Plan-executability gate: no plan is executable until it has all 8 of required-capabilities, assigned-assets, physics-score, resource-budget, rehearsal-result, safety-check, approval-record, rollback/abort-rule (the planning mirror of §29.5). Acceptance: a plan missing any one precondition is non-executable; test enumerates all 8. | D | D | D | NA |
| MP-08 | P1 | Capability matching: required-capabilities × available-assets × assignment-rules select the asset set. Acceptance: an unmet required capability blocks assignment; a met set yields an assignment honoring the rules; test. | D | D | D | NA |
| MP-09 | P1 | Physics planning/scoring: sinkage/slip/excavation-force/energy/stability scored per candidate via the conserved PhysicsBackend (PX-04). Acceptance: each candidate carries a physics score from the conserved backend; an infeasible candidate is flagged (not silently ranked); test. | D | D | D | NA |
| MP-10 | P1 | Rehearsal: candidate plans → Gazebo/Chrono simulation → predicted outcomes → risk scoring, on simulation branches in REHEARSAL mode. Acceptance: a rehearsal yields predicted outcomes + a risk score WITHOUT touching live/accepted world (mode-gated per EG-02); test. | D | D | D | NA |
| MP-11 | P1 | Reconciliation step: prediction vs observation → plan deviation → world-update + model-update proposals (feeds EG-08 / §29.7). Acceptance: an executed plan's predicted-vs-observed diff yields a world-update proposal + a flagged model error; test. | D | D | D | NA |
| MP-12 | P2 | The 10 planning UI panels: Mission Graph / Map-3D / Capability Board / Physics / Timeline / Resource / Rehearsal / Risk / Execution / Reconcile, each rendering its planning object from the API. Acceptance: each panel renders its object; frontend (GeoLibre rewrite lane). | N | N | N | NA |

### 7.1 Contracts and Conserved Authority

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| CT-01 | P0 | All public numeric inputs enforce units, finiteness, and physical domains. Negative depth/mass and NaN/Inf are rejected. | D | D | D | NA |
| CT-02 | P0 | `ColumnState` validates dimensions, array shapes, dtypes/domains, density, labels, disturbance, datum, ice, and inventory at construction. | D | D | D | NA |
| CT-03 | P0 | Every authority mutation is transactional, conserves mass when required, and leaves all invariants valid. | D | D | D | NA |
| CT-04 | P0 | Scene publication writes verified rasters atomically and metadata last as the commit marker. | D | D | D | NA |
| CT-05 | P0 | Python, Godot, and ROS share a versioned schema with strict required-field, frame, dtype, and range validation. | D | D | D | NA |
| CT-06 | P0 | Production contract checks use explicit exceptions, never removable `assert` statements. | D | D | D | NA |
| CT-07 | P1 | Every artifact records source commit, configuration, mode, seed, schema version, and input hashes. | D | D | D | NA |
| SF-01 | P0 | A command-timeout safing watchdog auto-issues SAFE to any RC backend (sim or real pit) when valid commands stop arriving; resets on each heartbeat. The dead-man interlock on the command path (the §19.0 safety requirement; the moment STEWIE commands hardware, this is its interlock). | D | D | D | N |

### 7.2 Terrain, Material, and Illumination

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| TW-01 | P0 | Load and crop real polar LOLA terrain; fail explicitly if a requested real asset is unavailable. | D | D | D | P |
| TW-02 | P1 | Reproject supported non-polar products into a documented local metric frame. | D | D | D | P |
| TW-03 | P1 | Product paths use windowed/tiled terrain access rather than loading the full map by default. | D | D | D | NA |
| TW-04 | P1 | One seeded composite generator combines craters, rocks, material, and illumination parameters. `stewie/terrain/scenes.build_from_dem` combines all FOUR families on the real Haworth DEM: craters (DEM corridor, `populate_craters`), material (ChaSTE density), illumination (`horizon_clip`), and ROCKS (a seeded Golombek SFD boulder field via `procgen.sample_boulders` over the corridor window, `rocks_d_min_m`-bounded to resolvable boulders >= 0.30 m, surface-snapped into the non-zero global frame; clasts are metadata refs NOT carved into the conserved mass, so the datum round-trip is preserved). `stewie/terrain/test_scenes.py` [REQ:TW-04]: `test_build_from_dem_roundtrip_and_provenance` validates all four families present + provenance + datum round-trip on one build; `test_build_from_dem_rocks_seeded` validates the rocks family is seeded (fast, sampler-level -- avoids extra ~180 s builds). PERF NOTE (separate item): `build_from_dem`'s ~180 s per-call cost is `dart/illumination.py horizon_clip` -- a per-pixel shadow ray-march over the base heightmap, O(grid*sqrt(grid)), radius-independent -- NOT rocks/craters. `carve_crater` was the original crater bottleneck, now windowed + byte-identical (commit `fe18d91`); `horizon_clip` is NOT byte-identically optimizable (a faster horizon sweep changes the illumination result), so its speedup is tracked separately, not part of this row. | D | D | D | NA |
| TW-05 | P1 | `WorldState` carries per-cell material, traversability, observed/unobserved state, and calibrated uncertainty. | D | P | D | P |
| TW-06 | P1 | Add a site/time sun vector `s(t)` in the local world frame using a documented ephemeris interface. | D | D | D | P |
| TW-07 | P1 | Compute terrain horizon, direct illumination, cast-shadow mask, incidence angle, and overexposure risk from terrain plus `s(t)`. The dart compute (horizon / cast-shadow / `incidence_angle_deg`) is surfaced in the cockpit as toggleable `/layers` rasters: `illumination` (binary horizon shadow), `incidence` (continuous grazing-angle / overexposure-risk amber overlay, distinct from the shadow mask), and `psr`, all responding to the sun az/el controls. | D | D | D | P |
| TW-08 | P1 | Recompute affected illumination and navigation layers after excavation changes terrain. No stale pre-build shadow map may remain authoritative. | D | D | D | NA |
| TW-09 | P2 | Model camera LED contribution separately from solar illumination, including configurable intensity and pose. | P | N | N | N |
| TW-10 | P2 | Track dust/optical degradation as a state affecting image quality and maintenance decisions. `[PROPOSED]` | N | N | N | N |
| TW-11 | P2 | Traversal-compaction "traffic" layer (the multipass effect): accumulate per-cell rover-pass count + compaction + accumulated shear into the conserved twin; surface as FR-10 `traffic`/`compaction_state`/`shear_state` world layers with a traffic-color heat viz; add a costmap term that PREFERS established firm-compacted haul roads (lower sinkage) and AVOIDS over-sheared/rutted cells — emergent lunar haul-road / civil-infrastructure mapping from traversal history. Design: `docs/traversal_compaction_layer_2026-07-03.md`. `[PROPOSED]` | N | N | N | N |

### 7.3 Vehicle, Arms, Drums, and Stability

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| VT-01 | P0 | A typed `VehicleModel` supplies mass, gauge, wheelbase, wheel/contact geometry, CG, battery, drum capacity, speed, energy, sensors, and render assets. | D | D | D | P |
| VT-02 | P0 | Selecting a vehicle changes all applicable authority/planner numbers; cross-vehicle tests assert expected differences. | D | D | D | N |
| VT-03 | P1 | Model front and rear arm joint state, limits, velocity, brake state, and energy. Exact geometry must come from authoritative LAC/IPEx data. | D | D | D | G |
| VT-04 | P1 | Track four drums and per-drum fill rather than one global inventory for IPEx mode. | D | D | D | P |
| VT-05 | P1 | Compute dynamic CG from chassis, arm pose, drum pose, and fill mass. `[SPEC/PROPOSED model]` | D | D | D | G |
| VT-06 | P1 | Compute posture-dependent support polygon and static stability margin each step. | D | D | D | G |
| VT-07 | P1 | Nominal excavation requires balanced front/rear counter-rotation; asymmetric digging exposes reaction, traction, yaw, and pitch risk. | D | D | D | P |
| VT-08 | P1 | Drum fill-rate supports the sourced bridging behavior: effective collection need not increase monotonically beyond approximately half scoop depth. | D | N | D | P |
| VT-09 | P2 | Arm/drum force and torque model distinguishes horizontal reaction, vertical fill-dependent load, cutting torque, and internal tumble. | N | N | N | G |
| VT-10 | P1 | Posture-dependent camera extrinsics are derived from vehicle and arm state for every image. | D | D | D | G |

### 7.4 Meerkat and Excavator-Arm Maneuvers

The maneuver vocabulary is sourced from LAC/IPEx/RASSOR capabilities through
`[IPEx-DT-REF]`; exact geometry and transition limits remain qualification inputs.

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| AM-01 | P1 | Implement an explicit posture state machine: `TRANSIT`, `DIG`, `DUMP_Z`, `MEERKAT`, `DRUM_WALK`, `IRON_CROSS`, `SELF_RIGHT`, and `BRAKED_HOLD`. `stewie.specs.posture_machine` is that FSM: the eight states + a legal-transition table + `PostureMachine`. `BRAKED_HOLD` (the SF-01 safe stop) is reachable from every state; `SELF_RIGHT`/`IRON_CROSS` are recovery-only from `BRAKED_HOLD` (AM-06). Consumed in the product command path by NV-11 `lower_plan_ir`: each lowered action declares its required posture (GoTo→TRANSIT, Excavate/CutHaulFill→DIG, Import→DUMP_Z, Observe→MEERKAT) and a `PostureMachine` is driven through the action sequence, emitting the FSM-legal `posture_plan` (inserting TRANSIT / the BRAKED_HOLD safe stance where a direct transition is illegal) so the executive holds a legal posture per action. Pure + on-host; only structural transition legality is enforced at this seam -- the per-posture stability margin (AM-02) and flight-qualified posture geometry are the gated Q tier. | D | D | D | G |
| AM-02 | P1 | Every transition has preconditions for slope, arm range, drum load, support contacts, stability margin, and collision clearance. `posture_machine.can_transition` enforces transition LEGALITY (collision/support-contact structure) and gates a transition INTO a raised/working posture on a caller-supplied stability margin (AM-03). The slope / arm-range / drum-load preconditions plug into the same guard from the on-host posture geometry / gated flight numbers (Q tier). | P | N | P | G |
| AM-03 | P1 | `MEERKAT` raises the camera vantage by lowering arms under the chassis; motion is speed-limited and rejected when stability margin is inadequate. | D | D | D | G |
| AM-04 | P1 | Differential front/rear arm pose may be used as a controlled camera-pitch action only after kinematic and stability validation. `[PROPOSED]` | D | D | D | G |
| AM-05 | P2 | `DRUM_WALK` supports bounded slow translation while raised and records contact/slip/energy separately from wheel drive. | N | N | N | G |
| AM-06 | P2 | `IRON_CROSS` permits wheel-cleaning/recovery only under explicit raised-posture safety limits. | N | N | N | G |
| AM-07 | P2 | `SELF_RIGHT` is a fault-recovery plan with transient stability/contact checks; it is not available as an unconstrained action. | N | N | N | G |
| AM-08 | P1 | Arm brake allows a validated posture hold with zero or modeled holding power; transition energy remains charged. | D | D | D | G |
| AM-09 | P1 | The planner may choose Meerkat only when predicted information gain or recovery value exceeds time, energy, and risk cost. `[PROPOSED]` | D | D | D | N |

### 7.5 Perception, Mapping, and Localization

The target spine follows the modular pattern demonstrated by `[NAVLAB26]`. Equivalent components are
allowed if they meet the acceptance criteria.

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| PM-01 | P0 | Time-synchronize camera, IMU, command, arm, and truth/evaluation streams using explicit clocks and frame IDs. | D | D | D | N |
| PM-02 | P1 | Support the documented IPEx/LAC camera set and a maximum active-camera budget; camera activation/resolution has compute and energy cost. | P | N | N | G |
| PM-03 | P1 | Segment at least ground, rock, lander, fiducial, and sky from grayscale images without truth masks in evaluation mode. | P | N | P | N |
| PM-04 | P1 | Detect/match illumination-robust features and expose confidence/inlier statistics. `[NAVLAB26 reference: SuperPoint + LightGlue]` | D | P | D | N |
| PM-05 | P0 | Stereo VO triangulates landmarks, maintains persistent tracks, and estimates relative SE(3) pose with robust outlier rejection. | D | N | D | N |
| PM-06 | P0 | Fuse VO/IMU and validated absolute factors in a recursive estimator or factor graph with covariance. | D | N | D | N |
| PM-07 | P0 | Loop closures are candidate-gated, geometrically verified, and auditable; false closures must not silently enter the graph. | D | D | D | N |
| PM-08 | P1 | Produce a local/world elevation map using robust per-cell aggregation and a rock occupancy/probability map. | D | D | D | P |
| PM-09 | P1 | Track observed coverage, effective sample support, uncertainty floor, and correlation; dense pixels from one view are not treated as independent evidence. | D | P | D | N |
| PM-10 | P1 | Benchmark on a fixed LAC-style suite: localization RMSE, 5 cm height-cell pass fraction, rock F1, coverage, runtime, and failure count across seeds/light/rocks. | P | N | P | N |
| PM-11 | P1 | Target benchmark: demonstrate repeatable centimeter-scale localization comparable to the `0.038-0.067 m` `[NAVLAB26]` reference before claiming parity. | P | N | P | N |
| PM-12 | P1 | Truth pose and semantic masks are development/evaluation-only and structurally unavailable to operational estimator code. | D | D | D | NA |
| PM-13 | P1 | Range/depth source abstraction: the selected sensor profile may provide depth from rectified stereo disparity, LiDAR, RGB-D, or a simulator sensor feed, but every source must emit the same typed `DepthObservation`/point-cloud contract with frame, timestamp, calibration identity, valid mask, range limits, and uncertainty. Stereo remains the default no-LiDAR IPEx path; LiDAR is a swappable upgrade or testbed source when mass/power/sensor availability permits. Acceptance scores each source against conserved truth depth in sim or against surveyed targets on hardware, without allowing simulator truth into estimator code. | N | N | N | N |
| PM-14 | P1 | 3D point cloud + recognition: a dense/semi-dense cloud is reconstructed from the selected depth source, converted to `sensor_msgs/PointCloud2` or an equivalent STEWIE cloud record, expressed in the world frame with per-point confidence; recognition (ground/rock/berm/pit/lander) operates on the cloud, never on truth masks. Downstream mapping/planning must be unchanged whether the cloud came from stereo, LiDAR, RGB-D, or replay. | N | N | N | N |
| PM-15 | P1 | Regional target height: over an operator-selected footprint, estimate a height field / max-min relief (berm crest, pad flatness, obstacle height) from the selected depth cloud, with uncertainty; acceptance compares to the conserved as-built truth (ties CP-06 flatness/profile and I11 as-built RMSE). | N | N | N | N |
| PM-16 | P1 | Regional target volume: over a selected footprint, integrate cut/fill volume (excavated pit, spoil/berm) from the selected depth-derived height field vs a reference datum, with an uncertainty band; cross-checked against the conserved mass/volume the authority actually moved (CT-03 conservation). | N | N | N | N |

PM-13–16 are the depth-perception *measurement* family. Stereo is the baseline because it minimizes mass,
power, and mechanical complexity for the no-LiDAR IPEx profile, but LiDAR is explicitly swappable when the
vehicle or test stand has it. The downstream contract is source-neutral: depth observation -> point cloud ->
observed height/occupancy layers -> construction acceptance. A LiDAR-equipped run may improve range quality,
but it does not bypass truth-denial, calibration, covariance, or evidence requirements. These rows feed the
construction-acceptance loop and the Perception ("what it sees") pane, and are validated against the
conserved-physics truth rather than synthetic depth. They are the perceived counterparts to the truth-field
acceptance already in CP-06/I11; all are gated on the render/live-sensor -> depth pipeline (the §16.7
perception layer).

### 7.6 Solar-Terrain Navigation

Solar-terrain navigation is the use of known/estimated solar geometry and terrain-induced
illumination as navigation evidence and an active-perception control variable. It is distinct from
solar power scheduling.

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| SN-01 | P1 | Derive expected shadow azimuth from `s(t)` and local terrain/objects. `[PROPOSED]` | D | D | D | N |
| SN-02 | P1 | Detect reliable shadow vectors while rejecting rover/LED shadows, saturation, ambiguous penumbra, and texture edges. `[PROPOSED]` | D | D | D | N |
| SN-03 | P1 | Fuse accepted shadow evidence as a weak yaw factor with covariance; never as an unqualified absolute heading. `[PROPOSED]` | D | D | D | N |
| SN-04 | P1 | Re-evaluate shadow factors when terrain is excavated, the sun vector changes, or the observation viewpoint changes. | D | D | D | NA |
| SN-05 | P1 | Add illumination-aware route cost: visibility, saturation, shadow hazard, map uncertainty, energy, slope, and construction constraints remain separate inspectable terms. `dart.illumination_cost.illumination_cost` returns the four illumination terms SEPARATELY (never a fused black box): shadow-hazard (unlit -> no tag-lock), saturation (low-sun washout), map-uncertainty (coverage field), and visibility (opt-in: a cell with NO line-of-sight to a localization anchor cannot get a fiducial pose-lock -- distinct from shadow, reusing the audited `dart.visibility.is_visible` LOS march); energy/slope/construction stay the planner's existing separate route terms. [REQ:SN-05] tests assert each is its own retrievable field + the visibility term flags cells blind to the anchor. The separable terms now remain SEPARATE AND INSPECTABLE THROUGH THE LIVE ROUTE COST, not only at the DART layer: `lode.planner_routing.slope_costmap` / `route_leg` (and the footprint-inflated multi-vehicle `lode.mission_planner.route_leg`) accept either the bare `total` array OR the FULL `illumination_cost` dict and expose, via `return_terms=True`, a per-term breakdown of the routed corridor -- slope + each illumination sub-term (shadow_hazard / saturation / map_uncertainty / visibility) + map_unc as its OWN per-waypoint cost vector, so the cockpit/report can (once a consumer is wired) inspect why each routed cell costs what it does, term by term (the weighted terms sum exactly to the fused route cost; `return_terms=False` keeps the original 4-tuple contract byte-identical, and the dict-fed route is identical to the total-fed route). Validated on the real Haworth DEM by `lode/test_illumination_route.py` [REQ:SN-05]: a route across a shadowed region prefers lit cells AND the live route exposes the separable per-term breakdown (`test_route_leg_exposes_per_term_breakdown_on_real_dem`, point + inflated routers). I=D (separable per-term route cost fully implemented on the point + multi-vehicle inflated routers), V=D (the [REQ:SN-05] test verifies per-term inspectability through the live route, proven non-vacuous). X=D: the per-term breakdown now has a LIVE consumer + endpoint -- `lode.nav_pipeline.run_navigation` (the FS-05 spine) threads `illum_cost` + `return_terms` and surfaces `route_terms` (slope + each separable illumination sub-term shadow_hazard / saturation / map_uncertainty / visibility, each its own per-waypoint vector) in its result, and `POST /nav/run` surfaces `route_terms` in its JSON response. `illum_cost=None` keeps the live path byte-identical (the slope term only). `lode/test_illumination_route.py::test_run_navigation_surfaces_the_separable_route_terms_on_the_live_path` + `stewie/server/test_nav_router.py` [REQ:SN-05] verify the live spine + endpoint expose the separable breakdown on the real Haworth DEM; the endpoint does not auto-compute illumination per request (a full-DEM recompute) -- the illumination sub-terms appear when a precomputed `illum_cost` field is supplied to `run_navigation`. Illumination routing remains opt-in (off by default leaves routes byte-identical), the intended design. | D | D | D | N |
| SN-06 | P1 | Choose camera direction and exposure to avoid low-sun washout while preserving useful stereo overlap. | D | D | D | G |
| SN-07 | P1 | Choose camera subset and LED intensity to illuminate hard shadows within the active-camera and power budgets. | D | D | D | G |
| SN-08 | P1 | Permit arm-angle selection for near-field downward mapping or horizon/sun-grazing views using posture-dependent extrinsics. `[PROPOSED]` | D | D | D | G |
| SN-09 | P1 | Use the rover self-shadow LENGTH CHANGE under a COMMANDED articulated posture change as an instrument: the known `dh` cancels the unknown casting height, recovering sun elevation (or local slope) unbiased. `[PROPOSED]` | D | D | D | G |
| SN-10 | P1 | Triangulate landmark range from the KNOWN articulation baseline `dh` (depression-angle parallax of shadow tips), and fix rover `(x,y)` by heading-free trilateration from a standstill. `[PROPOSED]` | D | D | D | G |
| SN-11 | P1 | Permit a Meerkat observation action for multi-height parallax and shadow/rock disambiguation when stability guards pass. `[PROPOSED]` | D | D | D | G |
| SN-12 | P1 | Solar-navigation claims require ablations against VO/SLAM without solar factors across multiple sun angles, terrains, terrain-change states, and seeds. | P | N | P | N |
| SN-13 | P1 | Acceptance target `[PROPOSED]`: improve median yaw/pose error or feature-track survival by a preregistered margin without increasing tip events; report energy/time overhead. | D | N | D | N |
| SN-14 | P1 | The active-perception objective maximizes expected localization/map information per joule and second, with stability risk as a hard constraint. | D | N | D | N |
| SN-15 | P1 | Low/high posture observations must be associated to the same world features through the current arm/camera transforms. | D | D | D | G |

### 7.7 Navigation, Planning, and Recovery

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| NV-01 | P0 | Global routing rejects unreachable goals; it never substitutes an unsafe straight line. | D | D | D | NA |
| NV-02 | P1 | Coverage routes promote map coverage and deliberate re-observation/loop closure. `[NAVLAB26 reference: overlapping loops/outward spiral]` | D | N | D | N |
| NV-03 | P1 | A local planner samples dynamically feasible short-horizon trajectories and rejects rock/terrain collisions. `[NAVLAB26 reference: constant-curvature arcs]` `lode/local_planner.py`: samples a symmetric constant-curvature arc fan, rejects keep-out/rock/terrain (injected obstacle oracle), returns the max-progress feasible arc or feasible=False (NV-01: never a forced unsafe arc). Verified on the real Haworth slope map. Reachable from the cockpit via `POST /nav/local_plan` (router `stewie/server/routers/nav.py`, returns the arc + the NV-04 bounded drive command). | D | D | D | N |
| NV-04 | P1 | A path tracker converts trajectories into bounded commands and reports expected speed/progress. `lode/local_planner.py` `bounded_twist`/`track_arc`/`track_plan`: a constant-curvature arc -> a bounded (v, omega) twist (gentle = linear-capped, sharp = yaw-rate-capped), with expected speed (slip-derated via injected `(1-slip)`), duration, and arc-length progress; consumes an NV-03 plan and refuses an infeasible one. | D | D | D | N |
| NV-05 | P1 | Reactive obstacle observations update dynamic keep-outs and trigger local/global replan. `lode/reactive_nav.py` `react`: discovers newly-observed D/E rocks in sensor range (path_track), folds them into the dynamic keep-out set, and replans -- LOCAL (NV-03 arc around the updated keep-outs) first, escalating to GLOBAL when every local arc is blocked; deviation off-route also triggers. | D | D | D | N |
| NV-06 | P1 | Backup recovery triggers on progress ratio, duration, and planner failure; initial benchmark uses the `[NAVLAB26]` less-than-25%-for-2-to-3-second rule as a configurable reference. `lode/recovery.py` `recovery_needed`: fires on planner failure or sustained low progress (configurable threshold/stall window, default <25% for 2 s). | D | D | D | N |
| NV-07 | P1 | Recovery distinguishes collision/obstacle blockage from expected slope/slip slowdown to avoid false reverse maneuvers. `lode/recovery.py` `classify_stall`/`recommend`: low progress matching the slip-predicted (injected) ground speed -> 'slope_slip' (persist, no reverse); far below it -> 'blockage' (reverse); planner failure -> replan_global. | D | D | D | N |
| NV-08 | P1 | Tip, entrapment, localization divergence, low energy, thermal violation, and actuator faults are explicit fault classes. `lode/faults.py` `classify_faults`: the six classes with warn/critical severity off the existing models' signals (SSA tip margin, slip-ladder entrapment, pose-graph sigma, battery fraction vs the sourced 0.10 reserve, the -35/+40 C actuator qual, actuator status) + a safety-critical rollup the executive gates on. | D | D | D | N |
| NV-09 | P1 | An executive monitors action preconditions, command acknowledgements, belief covariance, and acceptance state, then pauses/replans/fails safely. `lode/executive.py` `executive_step`: strict safety precedence over the nav family -- safety-critical fault (NV-08) -> fail_safe; un-acked command / unaccepted step -> pause; recovery/reactive (NV-05/06/07) -> replan_global / reverse / persist / replan_local; else continue. | D | D | D | N |
| NV-10 | P0 | Plan IR maintains independent position, energy, time, and action state per vehicle. | D | D | D | NA |
| NV-11 | P1 | ROS lowering emits paths, motion commands, arm/drum goals, observation actions, and replan events from Plan IR. `stewie.bridge.plan_lowering.lower_plan_ir` lowers the IR's typed actions to ROS2-shaped messages -- `nav_msgs/Path` + `geometry_msgs/PoseStamped` per GoTo, an arm/drum action goal per Excavate/CutHaulFill/Import/Sinter, an observation goal per Observe, and replan events for blocked legs / an infeasible plan -- carrying the deterministic `plan_id`. Pure (rclpy-optional, the bridge pattern); the standard `nav_msgs`/`geometry_msgs` shapes are exactly what a Space ROS (hardened, API-compatible ROS 2) executive consumes. Published on the AG-08-gated `/rc/plan_ros` route (operator+, live-namespace mission only, SF-01) which lowers a live mission's plan and frames it on the NV-12 `StreamSession`. | D | D | D | N |
| NV-12 | P1 | Live command/telemetry uses a versioned streaming API with timestamps, sequence numbers, backpressure, and safe-stop semantics. `stewie.bridge.stream.StreamSession`: every frame carries `protocol_version` + a monotonic `seq` + a timestamp; a bounded un-acked window applies backpressure (frames past the window are refused + counted, never silently dropped); cumulative `ack` is the heartbeat; and an SF-01-tied safe-stop trips when the oldest un-acked frame stalls past `ack_deadline_s`, submitting `RC.Safe(SAFE_REASON_LINK_STALL)` through the same backend SF-01 uses. Pure (caller supplies `now`, the watchdog pattern; rclpy-optional). Wired into the AG-08-gated `/rc/plan_ros` route, which frames NV-11's lowered messages on a `StreamSession` (sequenced, back-pressured) for a live mission only. | D | D | D | N |

### 7.8 Construction Mission Planning

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| CP-01 | P0 | One immutable `PlanResult` is produced once and consumed by totals, report, validation, timeline, Plan IR, autonomy, and UI. | D | D | D | NA |
| CP-02 | P0 | Balance bank cut and loose fill by mass with drum/capacity constraints. | D | D | D | P |
| CP-03 | P0 | Execute/validate the selected optimized plan on the conserved authority and real terrain. | D | D | D | P |
| CP-04 | P1 | Goal grammar supports typed structures, tolerances, budgets, priorities, deadlines, dependencies, and keep-outs. `lode/mission_intent_compiler.py` lowers a canonical MO-01 `MissionIntent` onto the real planner path: objectives->`cut` orders, hard energy/time budgets->`objective_constraints`, soft-weight priorities->the weighted objective, deadlines->`max_time_s`, prerequisites->precedence, TOLERANCES (`AcceptanceCriterion.tolerance_m`, tightest per mission->`Mission.accept_flatness_tol_m`, honored by `validate_plan`'s as-built RMSE gate), and KEEP-OUTS (`KeepOutRegion` circle/rectangle/polygon->`Mission.keepouts`, the planner's own routing input: `route_leg` detours around them, a build inside is flagged `keepout_conflicts`). Keep-outs are integrated end-to-end: `lode/mission_lifecycle.analyze`/`rehearse` (executive ANALYZED/REHEARSED) compile the intent to the planner `Mission`, whose `keepouts` the planner honors in routing + `keepout_conflicts` through the forward_compare -> planner path. `lode/test_mission_intent_compiler.py` [REQ:CP-04] verifies all terms incl. a compiled tolerance failing a tight pad + passing a loose one on a real sloped DEM, and a compiled keep-out routing the real planner around it + flagging a build inside it. I=D/V=D: the tolerances + keep-outs implementation gap from the I-audit is closed + test-verified. X=D: keep-outs are on the live product path, AND the compiled acceptance tolerance is now EXERCISED on a live product path -- `lode.resync.forward_compare` (the executive REHEARSED edge, reachable via `POST /executive/advance`) plans each candidate `with_acceptance` WHEN the mission carries a compiled `accept_flatness_tol_m` and surfaces the as-built verdict (`as_built_pass` + the compiled `as_built_tol_m`) in every future; a mission without a compiled tolerance is byte-identical (no acceptance computed, no field). `lode/test_mission_intent_compiler.py::test_compiled_tolerance_is_exercised_on_the_live_rehearse_path` [REQ:CP-04] verifies the COMPILED tolerance (not a default) drives the live forward_compare path, and the no-tolerance case stays byte-identical. | D | D | D | NA |
| CP-05 | P1 | Footprints support rectangle, circle, corridor, and polygon with orientation; scalar-area squares are legacy input only. | D | D | D | NA |
| CP-06 | P1 | Acceptance includes pad flatness, berm profile, bearing/compaction, repose stability, mass, time, and energy. `validate_plan` reports each as an additive, inspectable check (never folded into `feasible`): `as_built_flatness` (I11 RMSE on the real datum), `berm_profile` (executed crest rise vs ordered depth, per fill order), `bearing_capacity` (allowable static capacity loose + firmed/compacted-to-bank-density, per pad/berm), `repose_stability` (as-built flank slope vs the soil angle of repose phi), and `mass_conservation`; time + energy acceptance are carried by the plan totals (`makespan_s` / `energy_J` + the EP-* ledger + battery reserve) and named in `acceptance_scope.defers_to_totals`. So `acceptance_scope` accounts for all seven CP-06 terms with no silent gap. Tested by `test_cp06_acceptance.py` + `test_bearing_acceptance.py` + the all-seven-terms completeness test [REQ:CP-06]. Q stays P: validated on the conserved physics in-sim, not yet qualified against a real as-built lunar surface. | D | D | D | P |
| CP-07 | P1 | Plan uncertainty carries DEM, material, slip, dig-rate, drum-fill, localization, and power-window uncertainty into feasibility/time/energy bands. A single `plan_uncertainty` block in the plan totals (`_plan_uncertainty`) aggregates all seven named sources, carrying a numeric figure where the model is grounded in-repo -- the dig-rate energy band (`dig_energy_bounds_MJ`, rated-vs-max RPM), the localization corridor margin (P-06), the DEM per-cell sigma (PM-09), the operator material factor (EP-02), and the drum-fill CYCLE band (`cycles_band` = `drum_cycles` ±`FDC_MPE_HALF_FULL`, the grounded DrumSensor FDC MPE from ICE-RASSOR NTRS 20210022781: fill-sensing error does not change the dig energy but perturbs the offload cycle count). Slip is named with `quantified: False` because its plan-level uncertainty is the [CALIB] Bekker/slip moduli, oracle-gated (FIX-1/2); power-window is quantified only when mission windows are declared (EP-04). No fabricated fraction. Full per-source band propagation of the slip term stays open (I/V partial). | P | P | P | N |
| CP-08 | P1 | Planner objectives support hard constraints and risk terms, not only unconstrained weighted metrics. | D | D | D | NA |
| CP-09 | P1 | Construction actions mutate `WorldState`; routing, illumination, observability, and acceptance consume the updated terrain. Three consumers read the MUTATED as-built in the product `/plan` path: routing (`run_closed_loop` re-hazards a leg crossing a freshly EXECUTED cut/fill at the repose slope -- `test_berm_rehazard`), acceptance (`validate_plan` flatness/berm/repose on `as_built` -- CP-06), and illumination (shadow recompute after excavation -- TW-08 `test_shadow_predict`). Observability (the onboard map-channel coverage) consuming the as-built remains render/onboard-gated, so I stays partial. | P | P | D | NA |
| CP-10 | P1 | Sinter remains unavailable for baseline IPEx; enabling it requires a distinct tool/power model and capability-qualified vehicle. | D | D | D | P |
| MO-02 | P1 | Mission-executive state machine (`DRAFT->ANALYZED->REHEARSED->REVIEWED->RELEASED->ARMED->EXECUTING->HOLDING/SAFED/COMPLETED/ABORTED->DEBRIEFED`; RELEASED = signed immutable revision). The planning + authorization head (DRAFT->RELEASED) is implemented: `stewie.contracts.executive.MissionExecutive` drives the typed transitions, `lode.mission_lifecycle.run_lifecycle` attaches REAL evidence at each edge (the compiler's deterministic plan_id at ANALYZED; the forward_compare ranking at REHEARSED), and `POST /executive/advance` (`stewie/server/routers/executive.py`, director-gated) exposes it. An uncompilable intent yields a 400 with no fabricated plan_id. Tested by `lode/test_mission_lifecycle.py` + `stewie/server/test_executive_route.py` [REQ:MO-02]. Q stays N: the live ARMED..EXECUTING execution tier is gated (MO-04, SIM/FORECAST-labeled) and not yet qualified against fault injection or hardware. | D | D | D | N |

CP-06 now reports pad flatness (I11), berm crest-profile vs ordered rise, and repose-angle flank stability (`validate_plan` `berm_profile`/`repose`, additive and reported in the acceptance dict, not folded into `feasible`), alongside the existing mass conservation and the simulated time/energy totals. Tests: `lode/test_cp06_acceptance.py`. The one remaining sub-item is bearing-capacity / compaction-state acceptance (needs a Terzaghi-style bearing model plus a compaction-state field from FORGE), which is why I/X/V stay P rather than D.

### 7.9 Energy, Thermal, Power, and Operations

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| EP-01 | P0 | Energy ledger includes drive, slope/slip, payload, dig, arm/drum motion, observation, LEDs, compute, idle/heater, and recharge losses where modeled. | D | D | D | P |
| EP-02 | P1 | Dig energy depends on material/density/ice or is explicitly marked constant-model uncertainty. The baseline is a CONSTANT J/kg (`ipex_specs.dig_energy_per_kg`, BP-1-calibrated, material/density/ice-independent) whose uncertainty is explicitly marked: the drum-rate `(0.72-1.0)x` band reported as `dig_energy_bounds_MJ`. An optional `Mission.dig_energy_factor` (default `None`=1.0=byte-identical, folded once in `plan_context` so every dig site is consistent) lets an operator scale it for a known harder/icier site, so the plan's dig energy depends on the declared material. Physical auto-derivation from density/ice remains unmodeled (Q=P). | D | D | D | P |
| EP-03 | P1 | Distinguish PSR lander/tower power from sunlit solar power. | D | D | D | P |
| EP-04 | P1 | Mission clock enforces power, illumination, thermal, and communications windows on actions/recharge. | D | D | D | N |
| EP-05 | P1 | Thermal derating and heater/survival demand affect usable battery and action availability. | D | D | D | N |
| EP-06 | P1 | Meerkat/arm posture and camera/LED policies include transition and dwell energy. | D | D | D | G |
| EP-07 | P2 | Dust accumulation affects optics, joints, thermal surfaces, and maintenance actions. | N | N | N | N |
| EP-08 | P1 | Endurance and reports use the selected `VehicleModel`, not global IPEx constants. | D | D | D | N |

EP-04 is enforced in the battery-aware simulator: `Mission.mission_windows` = `{class: [[open_s, close_s], ...]}` for class in `recharge` (solar/power illumination), `work` (illumination/thermal), and `drive` (comms/teleop transit). `_window_gate` idles the mission clock to the next allowed interval before each gated action (a `wait` leg, no battery drawn); an action with no remaining window is skipped and recorded infeasible. Threaded through `mission_from_dict` and validated at the `/plan` boundary; `None` (or a missing class) is unconstrained and byte-identical to an un-windowed plan. Tests: `lode/test_ep04_mission_windows.py`. Q stays N: the window schedules are operator-supplied, not yet driven by real lunar day/night illumination or DTE comms ephemerides; gating is also at action-start granularity (an action that begins inside a window may run past its close). Cockpit authoring control is pending.

### 7.10 Fleet Planning

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| FL-01 | P0 | Fleet allocation, simulation, validation, timeline, Plan IR, and playback share one `PlanResult`. | D | D | D | NA |
| FL-02 | P1 | Detect AND resolve route, site, and temporal conflicts rather than only same-site overlap. Detection: `_vehicle_conflicts` (same-site) + `_charger_conflicts` (shared charger) + `_temporal_conflicts` (two vehicles working within a proximity radius at overlapping times -- stationary space-time crowding) + `_haul_path_conflicts` (two vehicles' MOVING drive legs passing within a safe-separation radius at overlapping times -- segment-vs-segment proximity over the routed haul paths). Resolution: the FCFS charger queue (FL-03) for the shared charger, and `_resolve_spacetime_crowding` RE-SEQUENCES the work-crowding + haul-path crossings by the SAME FCFS discipline (lower vehicle index wins; the loser waits until the winner's span clears, iterated to a fixed point). The per-vehicle wait is folded into the makespan and surfaced as `crowd_wait_s` + a per-rover column in the Fleet report; the exact `plan_multi_oracle` applies the same re-sequencing so it stays a valid lower bound. The resolved spans match the detectors, so applying the waits drives both counts to 0 (`test_fl02_resequencing.py` [REQ:FL-02]). CONSERVATIVE (each loser yields to every lower-index crowder, shifting its whole later timeline); optimal JOINT re-ordering across the fleet remains future MV work. | D | D | D | NA |
| FL-03 | P1 | Model charger, pit, dump, observation vantage, and constrained corridor as shared resources. Charger = one-server FCFS queue: overlapping recharges serialise, the loser's wait shifts its timeline, the headline makespan reflects it (`makespan_parallel_s` keeps the optimistic value, `charger_wait_s` the cost). Pit/dump/vantage/corridor are declared via `mission.shared_resources` (`[{id, kind, capacity, sites}]`) and modelled as capacity-k FCFS servers keyed on work sites (`ReservationLedger` admission); over-capacity rovers wait, the wait folds into `makespan_s` and is reported as `resource_wait_s` / `resource_waits`. None/empty (or single-vehicle) is byte-identical. The charger AND all declared resources are scheduled JOINTLY by `_resolve_joint_resources`: one per-vehicle delay clock advanced over a single event calendar, every contended segment admitted against ONE multi-server `ReservationLedger`, so the reported makespan/waits are the real coupled FCFS schedule (feasible on every server at once) rather than a sum of independent per-server estimates -- removing the v1 double-count of a rover modelled as queued in two resources at once. A wait on one server now shifts the rover's later events on every server, so the coupled total is usually below (but can exceed) the old per-server sum: it is the true coupled schedule, not a bound. FL-02 crowding + FL-04 cross-vehicle precedence remain separate fixed-point resolvers folded on top. `test_fl03_shared_resources.py` [REQ:FL-03]. | D | D | D | NA |
| FL-04 | P1 | Maintain one belief/health/resource state per rover and coordinate replans. `_rover_health(pv)` distils each rover's state from its sim (feasibility, lowest battery margin, recharges, health rollup stranded/low_margin/nominal) into `vehicles_detail[].health` + the Fleet report; a stranded rover sets `fleet_needs_replan` (the reallocation trigger). Active work-reallocation on the trigger is future MV work. | D | P | D | N |
| FL-05 | P2 | Support heterogeneous vehicle capability and physics vectors. | P | N | P | N |
| FL-06 | P1 | Validate two-rover plans against an exact small-problem oracle before learned/heuristic superiority claims. `plan_multi_oracle` brute-forces the true site-exclusive optimum (every group->vehicle assignment x every per-vehicle order, jointly, same simulator + charger queue) up to MV_ORACLE_MAX_TRIPS; oracle <= heuristic by construction. Verified: heuristic within 0.15% of optimum on the 3-site instance. | D | N | D | NA |
| FL-07 | P1 | Solar/Meerkat observation sites are reservable fleet resources so rovers do not occlude or collide during raised observations. `[PROPOSED]` | D | D | D | N |

### 7.11 Product, Packaging, and Operations

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| PO-01 | P0 | `stewie-serve` (alias `stewie-serve`, deprecated) works after a fresh wheel install with one documented product extra. | D | D | D | N |
| PO-02 | P0 | Reports, profiles, caches, and renders use configurable application-data directories and atomic writes. | D | D | D | NA |
| PO-03 | P0 | CI installs declared dependencies and runs the configured suite across supported Python versions. | D | D | D | NA |
| PO-04 | P0 | CI separately gates Python core, scripts, Godot, browser, package smoke, and hardware-gated tiers. | D | D | D | NA |
| PO-05 | P1 | Commit a dependency lock, build an SBOM, scan resolved artifacts, and run a fresh-install test. | D | D | D | NA |
| PO-06 | P1 | Server enforces streamed body limits, execution timeouts, bounded concurrency, auth policy, and deployment-safe CORS. | D | D | D | N |
| PO-07 | P1 | Structured logs include request/event ID, mode, plan ID, route, duration, outcome, and error class. | D | D | D | N |
| PO-08 | P1 | Metrics are bounded and exportable in a standard operations format. | D | D | D | N |
| PO-09 | P1 | Mission/profile schemas are versioned and migratable. | P | P | P | NA |
| PO-10 | P1 | UI distinguishes forecast, simulation truth, estimator belief, and live telemetry. | D | D | D | NA |
| PO-11 | P1 | Fleet playback renders every rover and its independent telemetry. | D | D | D | NA |
| PO-12 | P1 | Solar view displays sun vector, illumination/shadow layers, active cameras/LEDs, arm posture, and evidence accepted/rejected by localization. | D | D | D | N |
| PO-13 | P1 | `CHANGELOG.md` (Keep a Changelog), exported `stewie.__version__` (== pyproject `[project].version`, enforced by `stewie/server/test_version.py`), a SemVer policy (`docs/RELEASE.md`), and a release-evidence manifest (`release_manifest.json`) aggregated from REAL artifacts by `scripts/gen_release_manifest.py` — version+drift, req_trace reconciliation, autonomy gate, SBOM component count, dep-lock status, changelog/SemVer presence; deterministic surface CI-guarded by `--check` (the gen_status.py honesty pattern), volatile fields (commit, live coverage/tests) written by `--full` to the reports dir at release time. `scripts/test_gen_release_manifest.py` [REQ:PO-13] proves every field IS the live tool output (no hand numbers) + the committed surface is in-sync + volatile-excluded. | D | D | D | NA |
| PO-14 | P1 | Provide deployment documentation and a supported server image; optional Godot/ROS capabilities are explicit profiles. | D | D | D | N |

### 7.12 Access, Identity, and Governance (added 2026-06-15)

The product is invitation-only and multi-operator, and it ultimately emits **real
instructions to a rover** (NV-11 Plan-IR lowering / NV-12 live command channel, under the
SF-01 dead-man interlock). Who may do that, on which artifacts, must be governed. These
requirements are **sequenced so each unblocks the next**; the terminal requirement (AG-08)
is the end goal — a live, role-gated, owned mission lowered to real rover commands.
Implementation order (TDD, atomic): AG-01 → AG-02 → AG-03/04 → AG-05 → AG-06 → AG-07 → AG-08.
The backend (operators store, deps, new invites router, role gating) is buildable now; the
admin-panel and sandbox/redeem UI land with the cockpit-frontend coordination (task #134).

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| AG-01 | P0 | Role model is a four-tier ordered ladder: `guest` (read-only) < `trainee` (own-sandbox write) < `operator` (live write + command) < `director` (admin + approve + escalation). A single `role_rank()` is the source of capability ordering; the legacy two-role store (`director`/`operator`) migrates forward without data loss. | D | D | D | NA |
| AG-02 | P0 | Capability gating keys every mutating/command route off `role_rank`, not merely authenticated-or-not. A `require_role(min)` dependency enforces it: reads open to `guest`+, live writes + real rover commands (rc_command, NV-11/NV-12 lowering) require `operator`+, admin/escalation require `director`. | D | D | D | NA |
| AG-03 | P1 | One-time invite tokens: `create_invite(by, role, ttl, max_uses=1)` mints a crypto-random token stored **hashed** (never plaintext, like a password) with role, issuer, expiry, and use-count; expired/spent tokens are inert. Default mint authority = `director` (Open Decision 11). | D | D | D | NA |
| AG-04 | P1 | Invite redemption: `POST /auth/invite/redeem {token,email,password}` activates the account at the token's role iff the token is valid/unexpired/unused, then burns it. The invitee sets their own password; no secret is transmitted out-of-band. | D | D | D | NA |
| AG-05 | P1 | Artifact ownership: missions, structures, and reports stamp `created_by` + `created_at` at save; the public record exposes the owner. Existing unowned artifacts read as owner `unknown` (no silent backfill). | D | D | D | NA |
| AG-06 | P1 | Delete is a recoverable soft-delete (trash + audit event). Self-service for your OWN sandbox artifact; deleting another operator's artifact OR any live-namespace artifact requires `director` (escalation). No hard purge without director confirmation. | D | D | D | NA |
| AG-07 | P1 | Workspace separation: artifacts save to a per-owner `sandbox/<owner>/` namespace by default; a role-gated `publish` promotes a copy into the shared `live/` namespace. Sandbox state never feeds the real-command path. | D | D | D | NA |
| AG-08 | P0 | **End-goal gate:** real rover instructions (NV-11/NV-12) are emitted ONLY from a `live`-namespace mission, by an `operator`+, under the SF-01 interlock. Sandbox/trainee/guest plans may simulate and output a Plan IR for review but cannot lower to hardware commands. **Note (2026-07-02 review, finding 3): a MISSION-LESS `/rc/command` GoTo is currently treated as low-level teleop and skips the published-mission check — the bounded-teleop/OPERATE-refusal requirement is tracked as SF-02.** | D | D | D | NA |

### 7.13 Cross-Cutting Production Requirements (added 2026-06-15)

These rows close the gaps found by the 2026-06-15 PRD-to-code review. They are deliberately narrow:
they do not turn STEWIE into ArcGIS, a flight-certified autonomy stack, or a high-fidelity granular
DEM. They make the advertised product boundary enforceable.

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| GI-01 | P0 | Production GIS runtime gate: the built Nginx/front-end image loads Cesium, Moon/Mars/Earth imagery, worksite overlays, sign-in, and mobile navigation under the actual CSP with zero blocking console errors. Acceptance is a desktop + mobile browser smoke against the deployed headers, not a direct asset curl. | D | D | D | N |
| GI-02 | P1 | Planetary map correctness: Moon/Mars views use body-correct ellipsoid/CRS metadata and real DEM terrain/elevation where a layer claims 3D terrain. A smooth WGS84 drape must be labeled as imagery-only, not terrain. | D | N | D | N |
| GI-03 | P2 | GIS interoperability scope: define and implement the mission-required subset only -- GeoJSON/COG import, selected OGC/ArcGIS service consumption, feature attributes/query, measurement/profile tools, provenance, and offline mission package export. Do not claim ArcGIS parity. | N | N | N | NA |
| DT-01 | P0 | Operational digital-twin unification: conserved authority, observed `TwinStore`, runtime packets, vehicle twin, PlanResult, belief state, and session events are linked by one versioned transaction envelope with mission/site/body/time/provenance/uncertainty. Runtime path done (`WorldStateService`, hash-chained log) + the SIM execute->remember loop (`commit_sim_run` folds terrain into `TerrainMemory` + records belief) + packet/vehicle-twin linkage (`packet_sha`/`vehicle_sha` in the hashed body, backward-compatible, cold-restore bit-exact). **Envelope linkage is verified on the happy path; the ATOMICITY of the mutation<->transaction commit (no swallowed best-effort) is tracked separately as DT-03 (2026-07-02 architectural review, finding 1) — today `twin.resync`/terrain-record/SIM-execute persist first, then best-effort the WorldTransaction.** | D | D | D | N |
| DT-02 | P0 | Twin audit read security: `/twin/version` exposes only a minimal authenticated version token to ordinary clients; full event history/provenance requires director/admin authorization and audit logging. | D | D | D | NA |
| RL-01 | P1 | Deployed RL policy gate: no RL capability may be called operational until a versioned policy artifact, training/eval lineage, model card, safety shield, deterministic fallback, and out-of-distribution acceptance report exist. Training scripts/environments alone do not satisfy this row. | D | D | D | N |
| SL-01 | P0 | Truth-isolated SLAM/Navigation benchmark: runtime bags and estimator processes are physically denied truth topics/frames; the full render/sensor/RTAB-Map-or-equivalent/Navigation/pose-graph pipeline is scored by an evaluator-only channel with pass/fail thresholds. | D | D | D | N |
| SE-01 | P0 | Full security audit gate: release requires a completed host, container, app, DNS/site, secret, backup/restore, dependency/SBOM/CVE, and external exposure audit. The current non-invasive Archimedes/site review is not sufficient. | D | D | D | N |
| TM-01 | P1 | Calibrated terramechanics/excavation gate: construction forecasts distinguish analytical surrogate, calibrated mission model, and offline oracle; excavation resistance, drum/arm torque, drivetrain/current limits, low-g parameters, and uncertainty are validated before field-confidence claims. | P | P | P | N |

### 7.14 Small-Model Autonomy Architecture (added 2026-06-15)

The on-rover autonomy architecture is **not** a single large VLM directly commanding ROS2. For an
IPEx-class excavator, learned components are bounded specialist estimators or planners behind typed
contracts. The world model and mission executive own state, authority, safety, and command emission.
LLMs may draft plans or explain telemetry, but they do not directly actuate the rover.

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| ML-01 | P0 | Model-orchestration rule: every learned model declares input schema, output schema, latency budget, compute/memory budget, calibration set, uncertainty output, failure modes, and safe fallback. Mission Executive consumes only typed outputs, never free-form model actions. | D | P | D | N |
| ML-02 | P1 | Terrain Assessment Model: stereo/depth, DEM, slope, shadow, and uncertainty layers produce traversability, hazard class, slope/roughness summaries, and confidence for the local planner. | P | N | D | N |
| ML-03 | P1 | Rock Classification Model: image/depth observations produce rock size, class, confidence, and navigation/excavation relevance; Class-A `>7 cm` hazard classification is acceptance-gated against held-out truth/evaluation labels. | P | N | D | N |
| ML-04 | P1 | Shadow-SLAM / Navigation Model: image pair or sequence plus sun geometry and articulation pose propose pose/landmark factors with covariance; the factor graph accepts them only through residual/observability gates. | P | P | D | N |
| ML-05 | P1 | Excavation State Model: drum torque/current, wheel slip, IMU, arm/drum state, and drive current estimate digging state, fill fraction, slip, stall risk, and confidence; advisory until calibrated against IPEx/AutoDig-style data. | D | D | D | N |
| ML-06 | P1 | Regolith Volume Estimator: before/after DEM or stereo heightfields estimate moved volume/mass with uncertainty, cross-checked against conserved authority mass and drum-fill sensing. | D | D | D | N |
| ML-07 | P1 | Mission Planner LLM: a small language model may convert operator intent into candidate task graphs, but plans must compile to typed goals, pass deterministic validation, and be approved by the mission executive before simulation or command lowering. | D | D | D | N |
| ML-08 | P1 | Science/Operator Assistant: a separate explanatory model may summarize telemetry, faults, and evidence; it has read-only access and no command path. | P | P | D | N |
| ML-09 | P0 | Edge deployment envelope: any simultaneous model set intended for IPEx-class hardware must fit the selected compute profile (for example Jetson Orin Nano/NX/AGX class) under measured RAM, power, thermal, latency, and sensor-I/O budgets with degraded-mode scheduling. The budget must name the active depth source (stereo SGBM, neural stereo, LiDAR, RGB-D, or replay), image/cloud rate, CPU/GPU split, RAM ceiling, thermal/power ceiling, telemetry bandwidth, and offload boundary to a base station. | D | D | D | N |

### 7.15 Full-Stack Onboard Autonomy Build Requirements (added 2026-06-15)

These rows turn the onboard-autonomy roadmap into atomic product work. They explicitly include
multi-vehicle coordination, path planning, navigation, ephemerides/azimuth, Navigation, front-end
restructuring, backend-to-frontend wiring, testing, optimization, security, and model hardening.
The sequence is defined in §25. No broad rewrite is allowed: each slice must start from a current
front-end/back-end inventory, add one contract or view, and land with tests before the next layer
claims completion.

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| FS-01 | P0 | Codebase assessment gate: before implementing a roadmap slice, inventory the touched front-end panes, backend routers, domain modules, tests, data contracts, security boundaries, and deployment assumptions. Acceptance is an updated slice note or PRD entry naming affected files/modules and existing tests. | D | D | D | NA |
| FS-02 | P0 | Contract spine: define versioned schemas for `WorldState`, `VehicleState`, `FleetState`, `BeliefState`, `PlanResult`, `ExecutionEvent`, `EphemerisObservation`, `NavigationFactor`, `ModelArtifact`, and `ConstructionSkill`. Backend APIs and cockpit views must consume these contracts instead of ad hoc payloads. | D | D | D | NA |
| FS-03 | P0 | Front-end information architecture: restructure the cockpit so Plan, Fleet, Navigation/Navigation, Perception/Imagery, Construction, Models, Security/System, and Reports are first-class work areas with mobile-safe layouts and explicit truth/belief/forecast/live labels. | D | D | D | NA |
| FS-04 | P1 | Multi-vehicle coordination: extend allocation into coordinated execution with per-vehicle state, shared-resource reservations, space-time corridor deconfliction, cross-vehicle precedence, conflict explanation, and safe replan/fallback behavior. | P | N | D | N |
| FS-05 | P1 | Path-planning and navigation stack: connect global route planning, local trajectory sampling, tracker, recovery, keep-outs, negative obstacles, illumination risk, slip/energy budgets, and ROS2/Autoware-style action lowering through one auditable navigation contract. `lode.planner_routing.navigation_contract` is that contract: it names each stage's implementing seam (`route_leg`, `local_planner.plan_local`/`track_plan`, `recovery.recovery_needed`, `negative_obstacle_mask`, `dart.illumination`, the `_simulate` slip/energy budget, and the NV-11 `lower_plan_ir` ROS egress) and self-reports whether each is wired on-host (import-check, not a hard-coded claim); surfaced read-only at `GET /nav/contract`. `on_host_complete` is true. An executable end-to-end spine now CONNECTS those on-host stages rather than leaving them as nine seams that merely import: `lode.nav_pipeline.run_navigation` routes the global corridor (`route_leg`), then DRIVES it as a receding-horizon closed loop through `plan_local` (local_trajectory), `track_plan` (the bounded cmd_vel egress), exact-unicycle integration, and `recovery_needed` (backup on a planner failure or a sustained low-progress stall), and `cross_track_deviation` scores the executed path against the planned route. `lode/test_nav_pipeline.py` is the on-host acceptance: it drives a real LOLA Haworth corridor to the goal with all five stages exercised in one connected run, fires-and-escapes recovery on a fully blocking keep-out (never entering the obstacle), and reports the honest no-corridor infeasible, so the on-host V evidence is now a real connected drive, not the import-check alone. X is now D: the spine is wired into the advertised product path. `POST /nav/run` runs the route-then-drive on the real site DEM and returns the planned waypoints + executed trajectory + recovery events + cross-track deviation + the stages exercised, and the cockpit Navigation pane's FS-05 DRIVE PREVIEW overlay (`navDrawDrive`) renders the planned route vs the executed trajectory with start/goal + recovery markers. Playwright-verified against a desktop-mode sidecar: the overlay drew the arrived-at-goal drive on the real Haworth corridor (54.5 m routed, 94 control ticks, cross-track mean 0.76 m). Tests: `test_nav_router.py` (the route end-to-end + unknown-site/extra-field 400s) and `test_ui_nav_drive.py` (the served drive-preview wiring). The cockpit drive is a PREVIEW simulated on the conserved terrain; commanding a real rover stays AG-08/SF-01 gated. I and V stay P: the live Autoware/Nav2 planner BINARY remains the one gated tier (present=False, needs a ROS/Space ROS host). | P | D | P | N |
| FS-06 | P0 | Ephemerides and azimuth authority: one backend service owns mission time, body/site frame, sun vector, sun elevation, azimuth convention, uncertainty, cache/provenance, and all shadow consumers. Acceptance includes cross-module azimuth tests and UI display of the convention. | D | D | D | P |
| FS-07 | P1 | Navigation operational loop: articulation pose, camera rig, shadow/parallax observation, pose-graph factor, residual gate, covariance update, operator evidence view, and planner-triggered relocalization stop form one closed loop. | P | P | D | N |
| FS-08 | P0 | Backend-to-frontend wiring: every new autonomy capability exposes a typed API, OpenAPI/schema example or equivalent fixture, cockpit state binding, loading/error/empty states, and a browser regression test covering desktop and mobile widths. | P | P | D | NA |
| FS-09 | P0 | Test pyramid: each slice lands with unit tests for math/contracts, backend route tests, front-end interaction tests, traceability markers, deterministic fixtures, and one integration/e2e path where the capability is user-visible. | D | D | D | NA |
| FS-10 | P1 | Optimization budgets: define and enforce latency, memory, CPU/GPU, bandwidth, tile/cache, and model-inference budgets for map rendering, planning, fleet solving, Navigation estimation, and cockpit mobile performance. | P | P | P | N |
| FS-11 | P0 | Security and hardening gate: capability work must preserve fail-closed auth, role gating, no automation secrets in browser state, CSP/no-inline-script deployment, SBOM/CVE review, backup/restore assumptions, and command-path interlocks. | D | D | D | N |
| FS-12 | P1 | Model integration and fine-tuning hardening: every learned model has dataset lineage, train/eval split, artifact registry entry, model card, quantization/deployment profile, calibration report, OOD detector, safe fallback, and rollback plan before cockpit exposure. | P | D | P | N |
| FS-13 | P1 | Recorded construction and self-docking skills: record, version, replay, compare, and approve movement primitives for excavation, dumping, berm shaping, and docking; replay must be corrected by belief feedback and bounded by safety checks. | P | N | D | N |
| FS-14 | P0 | Atomic rollout rule: the roadmap is implemented in dependency order; a phase cannot be marked done until the previous phase's contracts, front-end affordance, backend route, tests, security review, and performance budget are complete or explicitly gated. | D | D | D | NA |
| FS-15 | P0 | Front-end contract adapters: each cockpit work area owns a typed client adapter, request/response fixture, normalized view model, loading/error/empty mapping, and permission mapping. UI components consume view models, not raw backend JSON. The adapter LAYER is complete: `web/assets/adapters.js` normalizes all 10 FS-02 spine contracts (Ephemeris / World / Vehicle / Fleet / Belief / PlanResult / ExecutionEvent / NavigationFactor / ModelArtifact / ConstructionSkill) to view models, `toViewState` maps every fetch outcome to loading/ok/empty/error, `canAct` maps work-area→role (AG-01), and `ModelArtifact.deploymentReady` mirrors the backend ML-01 gate. Tested by `adapters.test.js` (node) + the CI-gated `test_adapter_contract_parity.py`, which proves every field an adapter reads is a real Pydantic contract field (no fabrication) and fails on backend drift. FS-08 pane wiring is now UNDERWAY (incremental, one pane per step, each Playwright-verified): `adapters.js` is loaded into the cockpit (the `STEWIE_ADAPTERS` global), the `/plan` route returns the typed `PlanResult` contract (built from the same `totals`, additive), and the Report-pane dashboard strip + CONOPS line consume the `normalizePlanResult` view model instead of ad-hoc `totals` keys -- which also fixed a latent bug where the `recharges` chip read a non-existent `totals.recharges` and showed a dash (now the real charge count, Playwright-confirmed). Increment 2 adds the new `TimelineFrame` contract (the activity-gantt motion frames; the /plan timeline frames are tested to conform to it) and the `normalizeTimelineFrame` view model, and the Report-pane ACTIVITY gantt + battery curve now consume it instead of raw frame dicts. Increment 3 adds the `LocalizationFix` contract (the Nav pane's est-vs-truth trace leg: `est`/`true`/`sigma`/`fix`; the /plan trace legs are tested to conform) + `normalizeLocalizationFix`, and the Nav pane's mission-localization plot consumes it. Increment 4 adds `PerceptionState` for the selected depth/cloud + panorama/shadow health card, `normalizePerception`, node coverage, and CI-gated parity coverage proving the Perception pane calls the view model instead of owning an untyped status shape. X is now D for the wired Plan/Report/Nav/Perception surfaces; V remains P until the remaining non-plan live-runtime panes get their route fixtures, browser render tests, and failure-mode coverage. | D | D | D | NA |
| FS-16 | P0 | Cockpit state and routing: the app has one routeable state model for selected mission, site, vehicle, body, time, mode, role, work area, selected entity, and live/sim/eval source. Desktop and mobile navigation are alternate views of the same state, not separate logic. Production now loads `cockpit_state.js` before `cockpit.js`; `setView` synchronizes through `window.STEWIE_STATE` using enum-guarded `setState`, `toHash`, and `fromHash`; Python gate `test_cockpit_state_routing.py` cites the row. **Note (2026-07-02 review, finding 4): the state model carries `source`(live/sim/eval)+`mode`(sandbox/live) but NOT the PRD product mode (GIS-PLAN/TRAIN/SIM-OPERATE/EVALUATE/OPERATE) or runnable profile (`desktop_sil`/`digital_twin`/`ros2_replay`/`hil_jetson`/...) as routeable fields — tracked as FS-25.** | D | D | D | NA |
| FS-17 | P0 | Windowing policy: the production operator flow is one browser cockpit. Any second window is read-only engineering/debug context or a separate ROS/RViz/Gazebo tool; it cannot hold independent command authority, hidden state, or unique approval controls. Enforced in `cockpit.js` by a single-authority election (`CMD_AUTH`: a localStorage claim + heartbeat, `BroadcastChannel` + `storage`-event sync); a window without the fresh claim is read-only (`body.dataset.cmdrole`), shows the `#cmd-readonly-banner`, disables `[data-cmd-authority]` command controls, and `guardCommand` refuses the command-tape emit. An explicit Take-over control promotes a window (no silent promotion of a hidden tab). Two-tab behavior Playwright-verified; static wiring guarded by `stewie/server/test_fs17_command_authority.py`. | D | D | D | NA |
| FS-18 | P0 | Frontend-backend contract gate: every new route-to-pane connection has a schema fixture, backend route test, frontend fixture render test, permission test, mobile-width smoke, and one failure-mode test before it is considered wired. | D | D | D | NA |
| FS-19 | P0 | End-to-end observability ledger: log every mission decision, operator action, role/permission check, backend contract call, plan/replan, command emission, safing event, model inference summary, Navigation factor accept/reject, fleet conflict, and state transition with correlation ID, mission/site/body/time, actor, input/output hashes, result, latency, and error code. Secrets, passwords, tokens, private keys, and operational truth-denied fields must never be logged. | D | D | D | NA |
| FS-20 | P1 | Cockpit chrome IA: System, Settings, and Admin move OUT of the top-level work-area tab bar into a profile/account menu, role-gated (Settings per-user; System eng/director; Admin director-only) — an operator sees only the mission work areas. Directors get a read-only log/audit viewer surfacing the FS-19 observability ledger (logs visible to admins; secrets/tokens/truth-denied fields never shown). | D | D | D | NA |
| FS-21 | P2 | Customizable workspace: within a work area, panes can be rearranged (drag-and-drop / dock) and the layout persists per operator (localStorage + optional server profile), with reset-to-default always available. Layout is a VIEW preference only — it never changes command authority, AG-08 gating, role gates, or which contract a pane consumes. | P | P | P | NA |
| FS-22 | P0 | PRD-code reconciliation gate: before claiming "complete the PRD", audit every open or partial §7 row against code and tests, classify it as DONE-stale, PARTIAL, OPEN, or BLOCKED, and record file:line evidence plus the smallest next action. Stale PRD statuses must be corrected before new implementation work is counted. The STRUCTURAL reconciliation invariants are now CODE-ENFORCED in `scripts/req_trace.py` and run as a hard CI step (`.github/workflows/ci.yml`): every `[REQ:]` citation must resolve to a real matrix row (an orphan/typo'd marker FAILS the gate), every row claiming V=D must be test-cited (FAILS otherwise), and rows that are cited but not yet V=D are surfaced as an "understated — review for promotion" audit list (the reverse-staleness signal). Tested by `scripts/test_req_trace.py` [REQ:FS-22] (orphan citation → exit 1; valid citation → pass; understated rows surfaced). The per-row SEMANTIC classification (DONE-stale/PARTIAL/OPEN/BLOCKED + smallest next action) remains the periodic manual audit deliverable. | D | D | D | NA |
| FS-23 | P1 | Architecture review ledger: maintain a living full-stack map from PRD row -> backend route/service -> domain module -> frontend adapter/view -> tests -> logs. It must expose missing links without implying the capability is done. | P | N | D | NA |
| FS-24 | P1 | Front-end module organization: split the cockpit into app shell, route/state store, typed API adapters, domain view models, shared visualization components, work-area views, command/approval rail, and diagnostics/log viewers. The split must preserve CSP/no-inline-script and fixture-driven tests. | P | N | P | NA |

### 7.16 Autoware-Shaped Lunar Navigation Requirements (added 2026-06-18)

STEWIE will **not** vendor or fork full Autoware as the rover brain. It will adopt the useful
Autoware architecture shape and ROS discipline: lifecycle-managed ROS2 nodes, typed message contracts,
TF/QoS discipline, containerized bringup, sensing -> perception -> localization -> mapping -> planning
-> control -> vehicle-interface separation, and RViz/Gazebo engineering visualization. Lunar planning,
excavation, ShadowNav, Navigation, terramechanics, and mission authority remain STEWIE-native.

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| AS-01 | P0 | Autoware-shaped boundary: define the ROS2 node graph and topic contract for sensing, depth-source selection, perception, localization, mapping, planning, control, vehicle interface, diagnostics, and mission executive without importing road/lanelet behavior planning. The graph must allow stereo, LiDAR, RGB-D, or replayed point clouds to feed the same mapping/localization contracts. | D | D | D | NA |
| AS-02 | P0 | ROS2 workspace skeleton: create container-buildable packages for `stewie_msgs`, `stewie_description`, `stewie_bringup`, `stewie_vehicle_interface`, `stewie_perception`, `stewie_localization`, `stewie_mapping`, `stewie_planning`, `stewie_control`, and `stewie_rviz`. | D | D | D | NA |
| AS-03 | P0 | IPEx vehicle description: add URDF/Xacro/SDF describing chassis, wheels, drums, arms, camera rig, IMU, optional swappable LiDAR/RGB-D mounts, collision geometry, inertials, joint limits, TF tree, and frame names derived from STEWIE vehicle specs. Sensor profiles must label absent, simulated, bench, flight, and legacy sensors explicitly. | D | D | D | G |
| AS-04 | P0 | ROS container tiers: provide reproducible containers for base ROS2 Jazzy dev, perception/SLAM, Gazebo simulation, RViz diagnostics, bridge runtime, and a Space ROS migration profile. Each container has a smoke command and pinned package manifest. | D | D | P | NA |
| AS-05 | P0 | RViz mission dashboard: ship an RViz config showing robot model, TF, odom, `/stewie/odom`, planned path, local trajectory, costmaps, occupancy/DEM map, selected depth-source cloud (`PointCloud2` or equivalent), camera feeds, covariance, Navigation factors, diagnostics, SAFE state, and command topic state. | D | D | D | NA |
| AS-06 | P1 | Gazebo simulation seam: launch the IPEx description in Gazebo with cameras, selected depth source (stereo pair, depth camera, LiDAR/RGB-D, or replay bridge), IMU, wheel odometry, contact/collision, `/cmd_vel`, `/joint_states`, `/tf`, `/clock`, `/stewie/perception/points` or equivalent `DepthObservation`, and bridgeable terrain/world state. Gazebo sim is robot/sensor sim, not excavation truth; estimator and planner inputs must be truth-denied. | D | D | D | N |
| AS-07 | P0 | Stanford/NavLab-derived navigation spine: implement or integrate stereo feature detection/matching, stereo VO, optional LiDAR/depth-cloud odometry or scan-to-DEM registration when a range sensor is selected, robust PnP/triangulation, pose graph optimization, loop-closure gating, terrain/rock mapping, coverage planning, local arc planner, and recovery benchmarks on truth-denied bags. | D | D | D | N |
| AS-08 | P0 | ShadowNav factor path: convert ephemeris-controlled sun geometry plus panorama/shadow landmark bearings into typed `NavigationFactor` observations with covariance, residual gates, false-factor rejection, and ablation versus non-shadow VO/SLAM. | D | D | D | N |
| AS-09 | P0 | Navigation articulation path: convert commanded posture changes, arm/camera kinematics, shadow perturbations, and articulation parallax into standstill relocalization factors; accepted factors must reduce covariance and be visible in cockpit and RViz. | D | D | D | N |
| AS-10 | P0 | Autonomous mapping: maintain observed DEM, occupancy/rock map, object graph, uncertainty, changed-terrain mask, and excavation state as separate layers over the conserved world model; estimator/mapping nodes are denied simulator truth. **Note (2026-07-02 hazard-perception assessment): the ROS2 mapping node that would maintain this live is a skeleton -- running the tested `dart.mapping` mapper in it is tracked as PM-18; the connected loop as PM-19.** | D | D | D | N |
| AS-11 | P1 | Lunar costmap stack: expose slope, roughness, sinkage, slip, tip risk, illumination, PSR, shadow confidence, energy, keep-outs, dynamic rocks, and shared fleet-resource reservations as composable planning layers. | D | D | D | N |
| AS-12 | P1 | ROS lowering and control: lower verified Plan IR into ROS2 paths, motion goals, work goals, observation goals, replan events, and bounded `/cmd_vel` or action goals under AG-08, NV-12, SF-01, and role-gated command eligibility. | P | D | P | N |
| AS-13 | P1 | Mission executive node: add a ROS2-side executive that monitors preconditions, acknowledgements, covariance, resource reservations, faults, acceptance state, and safing, then emits continue/pause/replan/relocalize/reverse/SAFE decisions. | P | N | P | N |
| AS-14 | P1 | ROS diagnostics and logging: every ROS node emits diagnostics, lifecycle state, health, latency, dropped frames, QoS warnings, command eligibility, SAFE events, and correlation IDs into the STEWIE observability ledger without logging secrets or truth-denied fields. | D | D | D | NA |
| AS-15 | P0 | NASA-style TDD gate: every autonomy slice lands test-first with `[REQ:<ID>]` markers, container smoke, deterministic fixtures, failure-mode tests, Power-of-10/static-analysis review for safety-critical code, and no capability claim until route/node/UI/log evidence exists. | D | D | D | NA |
| AS-16 | P1 | (MOVED to the dissertation acceptance extract; research-acceptance, not a production gate row) ShadowNav/Navigation/Stanford benchmark suite: compare passive VO, Stanford-style stereo SLAM, ShadowNav factors, Navigation articulation factors, and combined fusion across sun angles, terrain changes, rocks, PSR, camera degradation, and excavation state. | P | N | P | N |
| AS-17 | P0 | TRL5 stereo rig authority gate: navigation, mapping, ShadowNav, Navigation, RViz, Gazebo, and cockpit visuals load camera intrinsics/extrinsics from the authoritative IPEx/LAC camera profile, not hard-coded baselines. Acceptance distinguishes the TRL5-final 0.05 m stereo module (sourced SCHULER24 Figs 28/30/32, single rigid housing) from the rejected 0.165 m shoulder-split; any non-final profile is labelled rejected/legacy. **2026-06-18: legacy 0.070 m fixture RETIRED — the G2 corpus (13 g2cal poses + frame fixture) re-rendered at 0.05 m, profile/camera_rig/ipex_specs/system_profile/manifest re-frozen, `stereo_authority.py` is the gate (4 tests). Camera count confirmed against SCHULER24: 8 physical / 4 operational + 4 redundant (NOT 8-surround). Suite green (308 eval/specs + 731 dart/lode).** | D | N | D | G |
| AS-18 | P0 | Typed ARGUS Navigation evidence contract: every accepted navigation measurement crossing the estimator seam carries factor type, covariance, frame, source, and evidence class; shadow-yaw remains heading-only; metric shadow-length/boundary factors are blocked from calibrated/measured labels until a passing residual artifact replaces the 2026-06-24 negative. | D | D | D | N |

### 7.13 Architectural review remediation (2026-07-02)

These rows atomize the nine findings of the 2026-07-02 architectural review of the deployed system
(app.stewie.space/program) against the target architecture. Each finding is confirmed against the
cited `file:line`. **Runnable-on-archimedes note:** ROS2 Jazzy / Gazebo / RViz containers, RTAB-Map,
real Project Chrono (user-local micromamba), the RTX 3090 render/depth path, and COLMAP/pycolmap ALL
run on this host — so rows needing only those are *buildable here*, not gated. The truly-gated
frontier is now narrower: a live pit / real rover / field traverse, external LAC/IPEx arm geometry,
and the real-world locked-validation (Katwijk) acquisition.

**2026-07-02 100%-frontend-audit corroboration (`docs/frontend_100_audit_2026-07-02.md`):** its P0 mode/profile-state and depth-source-selector findings and its Settings/Admin-governance finding independently confirm FS-25, PM-17, and PO-15 (extended above); it adds the ROS/Gazebo/RViz cockpit evidence surface (FS-27), the Release/Execute authority-evidence card (FS-28), and the cockpit half of the mobile-fit finding (FS-26, extended). Its reported 16 `stewie/server` failures are host-dependency gaps in the auditor's env (pyproj/gymnasium/pytest-timeout) + DEM/GIS egress, not logic regressions.

**2026-07-02 hazard-perception assessment:** the visual-hazard-classification + mapping ALGORITHMS are built + tested (`hazard_map`/`rock_detect`/`obstacle_map`/`playthrough`/`masking`/`mapping`/`costmap_layers`; 52 focused tests green) and back the tracked ML-02/ML-03/PM-03/PM-07 rows -- but they are NOT yet a live closed loop: the ROS2 perception/mapping nodes are skeletons (PM-18), the cockpit lacks a live hazard-classifier evidence panel (FS-29), and the camera->classifier->map->planner->eligibility->cockpit path is not one connected runtime (PM-19).

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| DT-03 | P0 | **Atomic world-state transaction (review finding 1).** A world-state mutation (`twin.resync`, terrain record, SIM-execute remember) and its `WorldTransaction` commit succeed or fail together: either a two-phase commit or a compensating rollback, so `TwinStore`/`TerrainMemory`/run records can never run ahead of `/world/transaction`. No mutation path swallows a world-log failure (the current `try/except Exception: pass` best-effort at `twin.py:80,169`, `executive.py:190` is replaced by an atomic/compensating commit). Acceptance: an injected world-log failure leaves the store and `/world/transaction` consistent (mutation rolled back or transaction retried to durability), proven by a fault-injection test; the canonical-linked-record invariant holds under failure. Buildable on archimedes (pure server logic). | D | D | D | NA |
| DT-04 | P0 | **Per-site / per-source observed twin (review finding 2).** The observed digital-twin overlay and its world journal are keyed by `(site, depth-source profile)` — not hard-coded to `site == "haworth"` / `haworth.journal` (`state.py:77,128`). An imported site or a multi-site operation each carries its own observed twin and journal; switching site/source loads the correct observed surface. Acceptance: a second imported site accumulates and reloads its own observed twin independent of Haworth, verified on a real second DEM bundle. Buildable on archimedes. | D | D | D | NA |
| SF-02 | P0 | **Bounded command authority for all rover commands (review finding 3).** Every low-level rover command — including a MISSION-LESS `/rc/command` GoTo/teleop — is bounded by an explicit command-authority context: a released/published (`live`) mission, OR an explicitly-labelled dev/bench teleop authorization that is REFUSED on a `LIVE`/`OPERATE` runnable profile and audited. No path emits motion to a real rover outside a released mission or an explicit, audited teleop grant (`rc.py:43,74`). Acceptance: a mission-less GoTo on a LIVE/OPERATE profile is rejected; a bench/dev profile teleop is allowed only with the explicit grant and is audit-logged. Buildable on archimedes. | D | D | D | NA |
| DT-05 | P1 | **/world is the authoritative rich world descriptor (review finding 6).** `GET /world` returns geometry PLUS observed/mutated enrichment, provenance, and freshness — not geometry/defaults with enrichment deferred (`world.py:1,29`). A consumer cannot mistake an incomplete descriptor for the full world model: the payload declares its completeness/enrichment state explicitly. Acceptance: `/world` after a mutation reflects the observed enrichment (or explicitly flags it absent), verified against `/world/terrain_view` provenance. Buildable on archimedes. | D | D | D | NA |
| FS-25 | P1 | **Product mode + runnable profile in the route/state model (review finding 4).** The cockpit route/state model carries the PRD product mode (`GIS-PLAN`/`TRAIN`/`SIM-OPERATE`/`EVALUATE`/future `OPERATE`) and the runnable profile (`desktop_sil`/`digital_twin`/`ros2_replay`/`hil_jetson`/`sensor_bench`/`rover_bench`/`field_traverse`/`monte_carlo`) as first-class routeable, persisted, shareable fields — beyond today's `source`(live/sim/eval)+`mode`(sandbox/live) (`cockpit_state.js:8`). The persistent mode/profile rail (§26.2) is driven from this state; sim/forecast/replay/HIL/live never share ambiguous styling. Acceptance: a shared link restores mode+profile; the rail reflects them on every screen. Buildable on archimedes. | N | N | N | NA |
| PM-17 | P1 | **Sensor-profile selection + health in the cockpit workflow (review finding 5).** The cockpit exposes full depth-source-profile selection (`stereo_sgbm`/neural stereo/`lidar`/`rgbd`/`replay`, §26.3) with calibration freshness and source health, and Release/Execute BLOCK when the selected depth source is stale, degraded, or mismatched to the runtime — not just the static `stereo_sgbm` default (`cockpit.js:946`, `autonomy_contract.py:157`). Acceptance: selecting each profile updates the perception path; a stale/degraded/mismatched source blocks Release/Execute with an operator-legible reason. Depth-source contracts + sim sources buildable on archimedes; a live LiDAR/RGB-D sensor is the gated leg. | P | N | N | NA |
| PO-15 | P1 | **Operations governance beyond account admin (review finding 7).** Backup/restore is a scheduled + monitored control with an explicit RPO/retention policy (not a manual director endpoint at `admin_ops.py:18`); mission, runtime, and profile administration exist as first-class operations surfaces (not browser-local display preferences at `index.html:1354`). Also covers (100%-frontend-audit finding 6): ROS-runtime administration, hardware/live-command LOCKS (an explicit safety interlock separate from role), and an evidence-retention policy (`index.html:1354,1423`). Acceptance: a retention/RPO policy is declared and enforced by a scheduled job with a monitored last-success/age signal; mission/runtime/profile/ROS-runtime admin + the hardware-live lock are first-class audited surfaces, not browser-local display prefs. Buildable on archimedes. | P | N | N | NA |
| SE-02 | P1 | **Explicit access model for the training operator view (review finding 8).** `/session/{sid}/operator` (`session.py:44`) is either authenticated OR a deliberate capability-URL share whose posture is documented (a leaked session id = a bearer token for truth-denylisted training telemetry); truth-denial is not a substitute for the access decision. Acceptance: the security posture (PRD §security + a test) states and enforces the chosen model — authenticated, or capability-URL with unguessable ids + documented risk + optional expiry. Buildable on archimedes. | N | N | N | NA |
| FS-26 | P1 | **Mobile viewport fit for the public /program board AND the deployed cockpit (review finding 9 + 100%-frontend-audit finding 5).** Neither the `/program` board (today ~575 px wide) nor the deployed cockpit (key controls overflow/clip at 390 px) horizontally overflows the mobile viewport; wide content (tables, plots, 3D) scrolls inside its own `overflow-x:auto` container, never the page body (`program.html:28`, cockpit chrome). Acceptance: a Playwright check at 390 px asserts `document.scrollingElement.scrollWidth <= innerWidth` on both `/program` and the cockpit, with every wide region self-scrolling. Buildable on archimedes. | D | D | D | NA |
| FS-27 | P0 | **ROS/Gazebo/RViz as first-class cockpit evidence surfaces (100%-frontend-audit finding 3).** The Validate/System/Report panes surface, for the selected run, the ROS/Gazebo/RViz evidence that proves the run matches its runnable profile: lifecycle nodes, `/clock`, `/tf`, `/joint_states`, bridge-topic freshness, RViz display status + screenshots, Gazebo/bag links, the process/container profile, and a no-truth-input assertion (`index.html:879`). These are engineering-visualization evidence, never a separate command surface. Acceptance: with a `ros2`/`gazebo` profile selected, the panes show live-or-recorded ROS/Gazebo/RViz status matching the profile, and flag a mismatch. Buildable on archimedes (ROS2 Jazzy / Gazebo / RViz containers run here). | D | D | D | NA |
| FS-28 | P0 | **Release/Execute carry the full command-authority evidence card (100%-frontend-audit finding 4).** Release freezes and displays the immutable plan hash, runtime profile, namespace, sensor profile, AG-08 eligibility, SF-01 watchdog, and sign-off; Execute displays only the bounded NEXT command plus acknowledgements, watchdog/link-ack state, covariance, map freshness, SAFE/pause/replan controls, and a legible REFUSAL REASON when AG-08/NV-12/SF-01 reject a command (`cockpit.js:2366`). Acceptance: a released revision shows every field above; an ineligible command is refused with its reason surfaced. Buildable on archimedes. | D | D | D | NA |
| PM-18 | P1 | **Perception + mapping ROS2 nodes run the tested classifiers/mapper (2026-07-02 hazard-perception assessment).** The `stewie_perception` and `stewie_mapping` nodes (today 28-line skeletons at `ros2_ws/src/stewie_perception/.../node.py`, `.../stewie_mapping/.../node.py`) execute the REAL, already-tested host-side algorithms -- `dart.rock_detect.detect_rocks`, `dart.obstacle_map.classify` (detect->stereo->size-gate), `dart.masking.segment_eval_mode`, and `dart.mapping.build_elevation_map` -- over the sensor-bridge input, publishing detections + an accumulated 2.5D hazard/elevation map with uncertainty. Extends AS-10 (autonomous mapping). Acceptance: a container run of the nodes on a recorded sensor bag yields detections + a map matching the host-side dart output for the same frames (truth-denied). Buildable on archimedes (ROS2 Jazzy containers run here); a live pit/rover is the gated leg. | P | N | N | NA |
| FS-29 | P1 | **Cockpit live visual-hazard classifier evidence panel (2026-07-02 hazard-perception assessment).** A Validate/Perception surface shows the LIVE visual-hazard classifier -- per-frame detections, per-detection confidence, accepted vs REJECTED obstacles with the size-gate/appearance reason, the hazard-class + no-go overlay, and the replan CONSEQUENCE (which detection forced a reroute) -- beyond today's static hazard rasters + keep-outs. Acceptance: the panel renders real detections + accepted/rejected + confidence + a hazard-triggered-replan indicator, no-truth-input labelled. Buildable on archimedes. | P | N | N | NA |
| FS-30 | P1 | **Cockpit ConOps de-duplication (2026-07-02 UI review, Screenshot_20260702_131756).** The top tab bar and the mission-pipeline `#stepper` both rendered Rehearse/Validate/Release/Execute/Report -- two stacked rows of the same phase labels. `#stepper` is reduced to the PLAN micro-wizard (Site->Fleet->Orders->Solve, the sub-steps that exist nowhere else) + a single "-> Rehearse" hand-off cue; the downstream phases' done/current progress rides as a dot ON each phase tab (`renderStepper` PHASE_TAB). Acceptance: `#stepper` carries no downstream-phase chip, each phase tab carries a progress dot, and the ui-smoke + a [REQ:FS-30] gate pin it. Buildable on archimedes. | D | D | D | NA |
| PM-19 | P1 | **Connected live hazard-perception loop (2026-07-02 hazard-perception assessment).** Camera/depth/`PointCloud2` -> classifier (PM-18) -> observed hazard/elevation map (DT-04/AS-10) -> planner costmap (`lode.costmap_layers`) -> command eligibility (AG-08/SF-02) -> cockpit evidence (FS-29) is ONE connected runtime path, not disconnected stages: a newly-detected hazard changes the plan AND the command eligibility AND is reflected in cockpit evidence within the loop. The underlying algorithms (`hazard_map`/`rock_detect`/`obstacle_map`/`playthrough`/`masking`/`mapping`/`costmap_layers`) are built + tested (supporting ML-02/ML-03/PM-03/PM-07); the GAP is the connected productized loop. Acceptance: an injected hazard on a real frame flows end-to-end -> a measurably different plan + a surfaced eligibility/evidence change. Host-side connected path buildable on archimedes; the live-ROS runtime closure is the gated leg. | P | N | N | NA |

### 7.14 Runtime spine — the audited perception→command loop (2026-07-02)

The algorithms are no longer the main gap; the **connective tissue** is. The modules (perception,
hazard maps, mapping, costmaps, routing, local planning, sim execution) exist and are tested, but they
are not yet one **stateful, audited runtime loop**. The target loop is:

`sensor/replay input -> DepthObservation/PointCloud2 -> visual hazard classifier -> observed DEM/
occupancy/rock-object layer -> localization/belief update -> hazard+terrain costmap -> global route ->
local trajectory -> bounded cmd_vel/action goal -> watchdog + command eligibility -> world-model
transaction -> cockpit/RViz/report evidence.`

This subsection tracks the SPINE (contracts, orchestration, staged runrunable-profile rollout, and the
two-screen operator display); the algorithm/piece rows it wires are cross-referenced, not duplicated:
the real ROS2 6-node set = **PM-18** + AS-01..14; command eligibility = **SF-02**/**AG-08**/**FS-28**;
the observed twin/world transaction = **DT-04**/**DT-03**; the cockpit loop cards = **FS-27**/**FS-28**/
**FS-29**/**PM-17**. **Staged rollout is mandatory** — prove `ros2_replay` (RS-04) FIRST, then Gazebo
(RS-05), then hardware (RS-06); do NOT wire every profile at once. All buildable on archimedes except
the hardware leg.

**Display / embedding design (RS-07 + RS-08):** the operator surface is a PRIMARY command cockpit
(`app.stewie.space`: Plan→…→Report + the bounded software-command console + eligibility/refusal) plus a
SECONDARY, READ-ONLY visualization/telemetry surface on its own route/subdomain (e.g. `viz.stewie.space`).
The secondary is **two-fold** on one shared site-frame + run/time state: a **PLAN column** (what we
intend — the sim-of-record Rehearse/route/forecast + the digital-twin `prior`/`forecast`/`edited`
provenance, rendered by Godot) beside an **ACTUAL column** (what the rover senses/does — the live ROS2
runtime, observed map, point cloud, real pose, executed `cmd_vel` + the `observed` provenance), with the
ACTUAL source escalating replay→Gazebo→hardware (RS-04→05→06) while PLAN stays fixed. The operator
PAYLOAD is the **divergence** between them (RS-08): executed-vs-planned trajectory, observed-vs-forecast
hazard/DEM, pose-vs-truth covariance — the same pose-vs-truth discipline STEWIE already runs (12.7 mm/
7.15° AprilTag eval), promoted to a live surface that drives the replan indicator. Godot embeds as its
rendered PNG/stream sidecar; Gazebo/RViz embed via a containerized web bridge (rosbridge + Foxglove
Studio) or a noVNC stream. The whole secondary carries NO independent command authority (§26.4) — the
divergence informs, it never commands.

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| RS-01 | P0 | **Hard runtime contracts.** Typed payloads — `DepthObservation`, `VisualHazardObservation`, `ObservedMapUpdate`, `HazardMap`, `CostmapSnapshot`, `LocalizationState`, `TrajectoryCommand`, `CommandEligibility`, `WorldTransaction` — are the ONLY things passed across the perception↔mapping↔localization↔planning↔control↔UI boundaries; no module passes a raw ad-hoc dict across a stage boundary. Acceptance: a contract test asserts each boundary carries + validates its typed payload, and a raw-dict / wrong-shape crossing is rejected. Buildable on archimedes. | D | P | D | NA |
| RS-02 | P0 | **Planning consumes the OBSERVED world, not just the static DEM.** The planner reads the current observed DEM layer, occupancy/no-go layer, rock/object graph, changed-terrain mask, and map uncertainty — each tagged with provenance (prior vs observed vs forecast vs edited) — instead of only the static DEM + hand-authored keep-outs. Acceptance: an observed hazard absent from the static DEM measurably changes the route/costmap. Buildable on archimedes. | D | D | D | NA |
| RS-03 | P0 | **Receding-horizon navigation runtime loop.** A runtime tick takes the current pose/belief, updates the local hazard/costmap, produces a global route when needed and a local arc/trajectory EACH tick, lowers ONLY the next bounded command, and replans/recovers when blocked, stale, or uncertain. Acceptance: a per-tick loop over a fixture drives toward goal, emits exactly one bounded command per tick, and recovers from an injected block/stale/uncertain condition. Buildable on archimedes. | D | P | D | NA |
| RS-04 | P0 | **`ros2_replay` deterministic end-to-end loop fixture (the keystone gate).** ONE deterministic fixture on the first runnable profile (`ros2_replay` / `desktop_sil`) proves the whole spine: replay stereo/depth → classify hazards → update observed map → plan around hazards → issue OR REFUSE a bounded command (via eligibility) → record a `WorldTransaction` → produce an evidence bundle. Acceptance: the fixture runs end-to-end deterministically; each stage's typed RS-01 payload and the final evidence bundle are asserted; a seeded hazard forces a reroute and a seeded ineligibility forces a logged refusal. Buildable on archimedes. | D | P | D | NA |
| RS-05 | P1 | **Gazebo live-sensor loop + RViz.** After RS-04 is stable, Gazebo becomes the live sensor producer (cameras/depth/LiDAR topics, IMU/wheel odom, `/tf`, `/clock`, `/joint_states`, `/cmd_vel`) driving the SAME RS loop; RViz shows robot, point cloud, map, costmap, path, and command state. Acceptance: the loop runs on Gazebo-produced sensors in-container and RViz displays the live evidence; estimator/planner inputs stay truth-denied. Buildable on archimedes (Gazebo + RViz containers). | N | N | N | NA |
| RS-06 | P1 | **Hardware loop (gated).** ONLY after the replay + Gazebo loop is stable: a Jetson runnable profile, a real stereo/LiDAR bench, calibration, MEASURED latency/RAM/thermal budgets, fault injection, and watchdog proof. Genuinely gated on a real Jetson + sensor hardware bench. Acceptance (when hardware exists): the loop closes on-device within the declared compute/thermal envelope with the watchdog + fault-injection proven. | N | N | N | G |
| RS-07 | P1 | **Multi-screen operator display architecture (primary command + two-fold viz).** The operator surface is a PRIMARY command cockpit (`app.stewie.space` — Plan→…→Report + the bounded software-command console + eligibility/refusal) and a SECONDARY, READ-ONLY visualization/telemetry surface on its own route/subdomain (e.g. `viz.stewie.space`) that is itself **two-fold** on one shared site-frame + run/time state model: a **PLAN column** (what we INTEND — the sim-of-record: Rehearse trajectory, planned global route + local arcs, forecast costmap, and the digital-twin `prior`/`forecast`/`edited` provenance layers per RS-02/DT-04, rendered by Godot) and an **ACTUAL column** (what the rover SENSES/DOES — the live ROS2 runtime via a web ROS bridge/Foxglove or web-RViz: observed DEM/occupancy, point cloud, real pose/belief, executed `cmd_vel`, and the twin's `observed` provenance layer). The ACTUAL column's source escalates across the staged rollout (RS-04 replay → RS-05 Gazebo → RS-06 hardware) while PLAN stays fixed. The whole secondary is READ-ONLY with NO independent command authority (§26.4). Acceptance: the two-column layout renders the PLAN (Godot/route/forecast) and ACTUAL (Gazebo/RViz cloud/observed-map/executed-cmd) surfaces co-registered in the site frame on the same selected run/time, and the secondary emits no command. Buildable on archimedes. | N | N | N | NA |
| RS-08 | P1 | **Plan-vs-actual divergence surface (the operator payload).** The value of the two-fold viz (RS-07) is the DELTA, not either column alone: PLAN and ACTUAL are co-registered in the site frame and their divergence is a first-class surface — executed-vs-planned trajectory error, observed-vs-forecast hazard/DEM deltas, and pose-vs-truth covariance growth (the pose-vs-truth discipline STEWIE already runs — the 12.7 mm/7.15° AprilTag eval — promoted to a live operator surface). A time model exposes PLAN's lead/lag vs ACTUAL (a `follow-live` mode vs a `scrub-plan` mode with a visible offset), since planning runs ahead of execution. When divergence crosses a declared threshold it drives the replan indicator (PM-19) and the operator's attention; it INFORMS only — never commands (§26.4). Acceptance: a fixture where ACTUAL departs from PLAN produces a measured trajectory/DEM/covariance divergence surface + a threshold-crossing replan indicator, co-registered and read-only. Buildable on archimedes. | N | N | N | NA |

### 7.15 Repository maintainability + continuity governance (2026-07-02 bloat audit)

The 2026-07-02 bloat/maintainability audit (`docs/repo_bloat_maintainability_audit_2026-07-02.md`) found
STEWIE does NOT need a rewrite: the tested math/perception/planning core stays, wrapped behind stricter
contracts; ~15-25% of active code needs restructuring, concentrated in the cockpit shell, runtime
adapters, test organization, and artifact/data policy. Working tree is 5.3 GB but only ~349 MB is
tracked; the rest is local/generated (`.venv`/`.mypy_cache`/`.claude`/`desktop` build/`datasets`/`out`/
`stewie/godot/out`). The audit's **Phase 3** (runtime contracts + ROS adapters + first connected profile)
is ALREADY tracked as **RS-01** (typed contracts), **PM-18** (ROS nodes run the real classifiers), and
**RS-04** (`ros2_replay` first profile) — cross-referenced here, not duplicated. The rows below are the
new maintainability/governance items.

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| MT-01 | P1 | **Large-file / tracked-artifact policy + CI gate.** A CI check REJECTS a newly-tracked large binary artifact unless it is on an explicit allowlist; the ~225 MB of tracked `samples/lunar_dem/*/*.rf32` DEM fixtures are externalized to checksum manifests + a fetch script, keeping ONE tiny real-derived smoke fixture in git (no synthetic). Acceptance: adding a large tracked binary reds CI; the externalized DEM resolves via manifest+fetch; the suite is green on the tiny fixture. Buildable on archimedes. | P | P | P | NA |
| MT-02 | P2 | **Documented workspace-cleanup script.** A SAFE cleaner reclaims the ~4.9 GB of local generated/vendor bloat (`.venv`/`.mypy_cache`/`.claude`/`desktop/dist`/`desktop/node_modules`/`datasets`/root `out`/`stewie/godot/out`) and steers generated outputs toward ONE ignored artifact root. Acceptance: the script previews then removes ONLY ignored/generated paths (a dry-run lists them; it never touches a tracked file — asserted against `git ls-files`). Buildable on archimedes. | N | N | N | NA |
| MT-03 | P1 | **Frontend strangler split of the cockpit shell (extends FS-24).** Continue extracting the ~6.2k-line `cockpit.js` + ~1.5k-line `index.html` into pure modules one at a time — `api_client`, route/state, the mode/profile/sensor rail, the command rail, the diagnostics rail, one pane per step — each with node:test coverage; add an allowlist gate over HTML sinks (the frontend's large blast radius + `innerHTML`/authority/localStorage surface the audit flags). Cross-refs FS-24, FS-09 (pyramid), PM-17 (profile rail). Acceptance: each extraction lands as a pure node-tested module, `cockpit.js` LOC drops measurably, the HTML-sink gate reds on a new unlisted sink, and the ui-smoke stays green. Buildable on archimedes. | N | N | N | NA |
| MT-04 | P1 | **Lean package / dependency-profile split.** Split the optional extras into `core` / `perception` / `planning` / `server` / `ros` / `dev` profiles so the DEFAULT install is lean and the heavy CV/GIS/benchmark deps stay out of the minimal runtime. Acceptance: a minimal-profile install boots `stewie-serve` + `/healthz` without the heavy extras, and each profile resolves from the hashed lock. Buildable on archimedes. | N | N | N | NA |
| MT-05 | P1 | **Continuity-governance release gate + ADRs.** A release gate REPORTS the tracked-payload size, the large-file diff, the HTML-sink count, and the test-tier status; each subsystem boundary gets an architecture decision record; a generated-artifact manifest declares what is regenerable vs tracked. Acceptance: the gate emits all four metrics and reds on a new large tracked file OR a new unlisted HTML sink; the ADR set + artifact manifest exist and are checked in. Buildable on archimedes. | P | P | P | NA |

### 7.16 Backend production-grade review remediation (2026-07-02)

The 2026-07-02 backend production review (`design/backend-production-review-2026-07-02.md`) graded the
backend production-ready with a hardenable list: 1 P0 (SE-01 audit-gate evidence), 5 P1 (production
defaults + governance), 6 P2, 1 P3. The findings that name EXISTING rows extend them (SE-01 P0-1, AG-06
P1-4, SE-02 P1-5, FS-19 P2-2) -- cross-referenced, not duplicated; the rest are the new production-
hardening rows below. Council synthesis: production defaults must be EXPLICIT -- no built-in identity
trust, a standalone session secret, and the SE-01 evidence gate closed before release.

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| BP-01 | P0 | **SE-01 release security-audit EVIDENCE gate (review P0-1, closes SE-01).** A dated `docs/security/se-01/<date>/manifest.json` carries ONE evidence record per required domain -- host, container, app, DNS/site, secret, backup/restore drill, dependency/SBOM/**CVE scan** (run + stored, not just SBOM generation), external exposure -- each naming the environment + the tool/manual procedure. A backup/restore drill restores `/data` into a fresh container and verifies the auth store, audit log, reports, profiles, mission artifacts, terrain memory, and world journal read back. Acceptance: `[REQ:SE-01]` gate fails on any missing/undated/env-less domain and passes only with all eight current records. Buildable on archimedes. | D | D | D | NA |
| BP-02 | P1 | **Backend container entrypoint enters the public-bind TLS guard (review P1-1).** `server.py`'s public-bind guard (refuse plaintext `0.0.0.0` unless TLS-terminated / dev-open) runs only from `main()`, but `deploy/Dockerfile.backend` starts `uvicorn ... server:app` directly, bypassing it. Fix: the production image invokes the guarded `stewie-serve` path OR the invariant moves into ASGI startup/lifespan so a direct `server:app` import must pass it. Acceptance: a deploy test inspects the image command and fails if production starts `server:app` public without an equivalent guard. Buildable on archimedes. | D | D | D | NA |
| BP-03 | P1 | **Production requires a standalone session-signing secret (review P1-2).** `auth.py` falls back to deriving the session key from `STEWIE_API_KEY`; `compose.yml` does not require `STEWIE_SESSION_SECRET`. Fix: production (`STEWIE_TLS_TERMINATED=1`) REQUIRES `STEWIE_SESSION_SECRET` (fail-loud like the API key), startup fails/warns when TLS-terminated + secret absent, and rotation is documented (API-key rotation must not silently invalidate sessions; session-secret rotation must). Acceptance: a deploy-hardening test fails when production omits the secret; auth tests prove API-key vs session-secret rotation have separate effects. Buildable on archimedes. | D | D | D | NA |
| BP-04 | P1 | **Production identity is strict -- no built-in trust (review P1-3).** `auth.py` hardcodes a `DEFAULT_ALLOWLIST`, falls back to it for unknown emails, makes all allowlisted users directors when `STEWIE_DIRECTORS` is unset, and keeps a raw-key bootstrap that can claim any allowlisted email. Fix: in `STEWIE_TLS_TERMINATED=1` production, REQUIRE explicit `STEWIE_ALLOWED_OPERATORS` + `STEWIE_DIRECTORS` (or a one-time bootstrap director record) and disable the default-allowlist/raw-key-bootstrap trust; keep defaults only for local/dev/desktop; `/healthz`+`/config` report a DEGRADED state when running on built-in defaults. Acceptance: TLS-terminated with no explicit allowlist/directors fails closed (login/bootstrap 403 or startup errors actionably). Buildable on archimedes. | N | N | N | NA |
| BP-05 | P1 | **Live-namespace artifact deletion is director-only (review P1-4, enforces AG-06).** `missions.py`/`structures.py` delegate to `objects.deletion_allowed` (`is_director or owner==identity`), so an operator can soft-delete their OWN live mission/shared structure -- contrary to AG-06 (director approval for any live-namespace artifact). Fix: live-namespace deletion is director-only; self-service delete stays for the caller's own SANDBOX artifacts; enforce namespace policy in the routes (or `deletion_allowed(kind, namespace, owner, identity, role)`); the delete audit event names the namespace. Acceptance: operator deleting own LIVE mission -> 403; own sandbox mission -> ok; director deleting live -> ok + audited namespace. Buildable on archimedes. | D | D | D | NA |
| BP-06 | P1 | **Training operator-view access model (review P1-5, closes SE-02).** `/session/{sid}/operator` is open-by-contract and expired sessions persist until another `start()` evicts. Fix: pick ONE model -- authenticated (`require_auth` + optional trainer/session ownership) OR a signed expiring capability URL (explicit share token, `get()` enforces TTL) -- and document it. Acceptance `[REQ:SE-02]`: authenticated -> anonymous GET 401/403; capability -> unsigned id-only URL 401/403, signed unexpired ok, expired fails. Buildable on archimedes. | N | N | N | NA |
| BP-07 | P2 | **Critical operations fail closed on a degraded audit ledger (review P2-1).** `services.log_event` records audit-write failures but never raises, so a disk-full/permission failure lets privileged changes proceed with a degraded ledger. Fix: a `critical=True` / `require_audit_healthy()` path for director admin, live-mission mutation, release/execute, `/rc/command`, and security-settings changes REFUSES with 503 when the audit sink is degraded; non-critical logs stay best-effort. Acceptance: injecting an audit-write failure makes `/admin/operators/create`, live-mission delete, release/execute, and `/rc/command` refuse or surface a hard degraded result. Buildable on archimedes. | N | N | N | NA |
| BP-08 | P2 | **Full FS-19 observability ledger (review P2-2, extends FS-19).** The audit trail covers operator actions but not the full FS-19 per-contract observability (correlation id, actor, route contract, result, latency, error code, input/output hashes, mission/site/body/time, per required event class). Fix: a typed observability-event schema (separate from the director audit trail), a decorator/helper for backend contract routes recording all fields with redaction, and one `[REQ:FS-19]` assertion per required event class. Acceptance: `[REQ:FS-19]` fails if any required event class lacks full-field coverage or redaction misses secrets/truth-denied fields. Buildable on archimedes. | N | N | N | NA |
| BP-09 | P2 | **Single-worker backend is a guarded invariant (review P2-3).** Rate limiters, training sessions, and request metrics are process-local; the deployment is `--workers 1` by design, but accidental scaling would split them. Fix: document "single-worker backend" as an architectural invariant (`STEWIE_SINGLE_PROCESS_STATE=1`) and add a deploy-hardening test that fails if production workers > 1 without moving those stores to shared storage. Acceptance: a test checks the production command + the single-process invariant. Buildable on archimedes. | N | N | N | NA |
| BP-10 | P2 | **Report pruning removes nested render directories (review P2-4).** `prune_reports()` deletes only files directly under `reports_dir`, so `render_*` subdirs (perception render outputs) accumulate. Fix: prune old generated directories matching known prefixes (`render_*`) with resolved paths asserted to stay under `reports_dir` (no arbitrary recursive delete). Acceptance: the prune test adds an old `render_*` dir and proves it is removed while unrelated dirs survive. Buildable on archimedes. | N | N | N | NA |
| BP-11 | P2 | **Optimistic concurrency on live object stores (review P2-5).** `objects.save_*` use atomic replace (no partial writes) but two operators saving the same live mission/profile/shared-structure race last-writer-wins with no conflict. Fix: add `updated_at`/`revision`/`sha256` to shared live artifacts; require `If-Match` or a body `base_revision`; return 409 + the current revision on a stale save. Acceptance: two clients load rev N; first save -> N+1; second save with N -> 409. Buildable on archimedes. | N | N | N | NA |
| BP-12 | P2 | **Publish workflow uses the hashed dev lock (review P2-6).** `ci.yml` installs `requirements-dev.lock --require-hashes` but `publish-stewie.yml` installs `pip install -e .[dev]`, so the release gate can run against different dependency versions (supply-chain/reproducibility gap). Fix: the publish gate matches CI (`pip install --require-hashes -r requirements-dev.lock` + `pip install -e . --no-deps`) and optionally runs `req_trace` + the deploy-hardening tests. Acceptance: a workflow-lint test asserts the publish workflow uses `requirements-dev.lock` with `--require-hashes`. Buildable on archimedes. | D | D | D | NA |
| BP-13 | P3 | **Browser login does not echo the bearer token in JSON (review P3-1).** Login sets HttpOnly session + CSRF cookies (correct) but still returns the token in the JSON body for BOTH browser and automation, widening exposure (browser memory/logs/devtools). Fix: a normal browser login returns role/operator/ttl/must_set_password and OMITS `token`; only an explicit automation route/header/flag returns a bearer token. Acceptance: browser login response omits `token`; the automation path includes it only when explicitly requested + tested. Buildable on archimedes. | N | N | N | NA |

### 7.17 Frontend + lunar-mission-systems review remediation (2026-07-02)

Two 2026-07-02 reviews (`design/frontend-review-design-2026-07-02.md`,
`design/lunar-mission-systems-audit-2026-07-02.md`): the frontend/system is a strong lunar mission-
planning + digital-twin workbench but not yet a proven end-to-end operational perception-navigation
stack, and some GIS/ArcGIS + autonomy language over-claims. EVERY finding is tracked below (no
exceptions); the ones that extend an existing row cross-reference it rather than duplicating its scope.

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| FR-01 | P1 | **Product mode + runnable profile in the frontend state contract AND mission authority (both reviews; extends FS-25).** The cockpit route/state carries the active product mode + runnable profile, the shell always shows them, and Release/Execute + command eligibility KEY on them. Acceptance: mode/profile are in the state contract + visible in the shell, and a Release/Execute on a mismatched profile is refused/degraded. Buildable on archimedes. | N | N | N | NA |
| FR-02 | P1 | **Depth-source profile selector + health/freshness (frontend; extends PM-17).** A perception-source selector (stereo/lidar/rgbd/learned/replay/sim-truth) with health + freshness; Release/Execute REFUSE or DEGRADE when the profile is stale, simulated-when-live-is-required, or incompatible with the runnable profile. Acceptance: the selector shows health/freshness and a stale/mismatched profile blocks Release/Execute with a legible reason. Buildable on archimedes. | N | N | N | NA |
| FR-03 | P1 | **Release + Execute complete authority evidence panel (frontend; extends FS-28).** The full authority-evidence field set on Release (plan hash, profile, namespace, sensor profile, eligibility, watchdog, sign-off) + Execute (bounded next command, acks, watchdog/link, covariance, map freshness, SAFE/pause/replan, refusal reason). Acceptance: a released revision shows every field; an ineligible command surfaces its refusal reason. Buildable on archimedes. | N | N | N | NA |
| FR-04 | P1 | **Admin/control moves from manual buttons to GOVERNED operations (frontend; extends PO-15).** The frontend exposes governed backend resources (operators/roles, security settings, retention/RPO, audit health) as governed operations with their policy + audit, not a loose button collection. Acceptance: each admin action shows its governing policy + writes an audit event; a degraded-governance state is visible. Buildable on archimedes. | N | N | N | NA |
| FR-05 | P1 | **Training operator-view access model surfaced in the UI (frontend; extends SE-02/BP-06).** Each generated operator link shows scope, expiry, allowed actions (observe vs command), signed/single-use, and revocation state; the link is a signed expiring capability URL or authenticated session membership. Acceptance: the UI labels scope/expiry/actions/revocation beside each link; an expired/unsigned link is refused. Buildable on archimedes. | N | N | N | NA |
| FR-06 | P1 | **Route-to-pane contract registry + coverage gate (frontend; extends FS-18).** A `route_pane_registry.js` is the source of truth (route+method, backend schema, adapter, pane id, required role, provenance requirement, empty-state fixture, failure fixture, mobile fixture); a pytest enumerates backend routes and checks registry coverage for cockpit-visible panes; a node test loads each adapter fixture and verifies render status + error state + provenance labels. Acceptance: a route-backed pane missing from the registry (or missing an evidence/mobile fixture) fails the gate. Buildable on archimedes. | N | N | N | NA |
| FR-07 | P2 | **Provenance-labeling doc coherence (frontend).** The shipped provenance labels improved past the PRD/FANOUT prose; reconcile the stale text so the docs describe the real provenance surfaces. Acceptance: a doc-coherence check finds no PRD/FANOUT claim contradicted by the shipped provenance labeling. Buildable on archimedes. | N | N | N | NA |
| FR-08 | P2 | **Mobile fit is a protected regression gate across the cockpit (frontend; extends FS-26).** The ui-smoke 390 px no-horizontal-overflow assertion covers the cockpit panes (Plan..Report) + /program, not only /program. Acceptance: any pane that overflows the phone viewport reds the ui-smoke tier. Buildable on archimedes. | N | N | N | NA |
| FR-09 | P1 | **Prove the live hazard-perception -> world -> planner -> eligibility -> cockpit loop end-to-end (lunar; extends PM-19/RS-04).** A sensor observation changes the world model (with uncertainty + provenance), changes the planner costmap/route, gates command eligibility, and appears to the operator with provenance + refusal/approval evidence -- proven as ONE chain, not per-component. Acceptance: the mission-critical loop is demonstrated end-to-end with the operator evidence; until then the system is described as a planning/simulation scaffold, not a validated operational stack. Buildable on archimedes (host-side); the live-ROS runtime is the gated leg. | N | N | N | NA |
| FR-10 | P1 | **Unified typed LAYER MANIFEST world contract (lunar; extends TW-05).** `/world` carries a per-layer manifest -- layer id/type (DEM/imagery/slope/roughness/material/traversability/observed-mask/uncertainty/hazard/illumination/comms), body CRS, site bounds, resolution, source, provenance, timestamp+freshness, uncertainty model, validity mask, transaction id, and CONSUMER ELIGIBILITY (display/planning/release/execute) -- and the planner costmap consumes the SAME manifest the cockpit reads. Acceptance: material/traversability/observed/uncertainty layers are discoverable + typed, each with consumer eligibility, and the planner builds its costmap from that manifest. Buildable on archimedes. | D | D | D | NA |
| FR-11 | P1 | **Observed-world-to-planner END-TO-END acceptance gate (lunar; extends RS-02).** A single test: known DEM + route -> inject an observed hazard/terrain delta -> commit it through a world transaction -> rebuild the costmap from the layer manifest -> prove the route changes, is refused, OR records a justified-unchanged result -> render the impact in the cockpit + release evidence ("route changed because observed hazard X entered leg Y"). Acceptance: that end-to-end gate passes on real terrain. Buildable on archimedes. | D | D | D | NA |
| FR-12 | P1 | **GIS/ArcGIS platform claims get stricter boundaries (lunar).** Use precise language (GIS-oriented lunar planning / OGC-WMS + export / body-aware CRS / ArcGIS-compatible concepts where implemented) and STOP implying "ArcGIS platform complete"; add an ArcGIS integration adapter BOUNDARY (Feature Service read/query/edit, auth/token, schema mapping, offline package, CRS+vertical datum, round-trip validation) instead of mixing ArcGIS assumptions into generic GIS code; every layer carries SEPARATE display-eligibility and planning-eligibility fields. Acceptance: UI/labels use the precise language, the ArcGIS boundary + per-shape fixtures exist, and a layer displayable-but-not-planning-valid is not treated as planning-valid. Buildable on archimedes. | D | D | D | NA |
| FR-13 | P1 | **Observed before/after volume + uncertainty evidence for surface design (lunar; extends ML-06).** A `RegolithVolumeEstimate` contract (structure/work-order id, before + after terrain source, change mask, estimated cut/fill, uncertainty, drum/load cross-check, conservation residual, confidence class, acceptance status, linked world transaction); LEAP siteplan/structures emit it; the cockpit/report render volume acceptance + uncertainty. Acceptance: a before/after terrain delta produces a conserved, uncertainty-carrying volume estimate cross-checked against the drum sensor, linked to a world transaction. Buildable on archimedes. | D | D | D | NA |
| FR-14 | P2 | **Navigation is labeled preview/rehearsal unless a live autonomy integration is proven (lunar).** The UI + product language mark navigation as preview/rehearsal until the selected runnable profile proves a live autonomy binary is active + authorized. Acceptance: the nav surfaces are labeled preview/rehearsal, flipping to live only when the runnable profile attests a live+authorized autonomy integration. Buildable on archimedes (the live autonomy binary is the gated leg). | D | D | D | NA |
| FR-15 | P2 | **Observability records become mission evidence (lunar; extends FS-19/BP-08).** Each observability record links its source assets, source freshness, provenance, operator, product mode, runnable profile, and transaction id -- mission evidence, not just ops telemetry. Acceptance: `[REQ:FS-19]` fails if a required record lacks the source-asset/freshness/provenance/mode/profile/transaction linkage. Buildable on archimedes. | N | N | N | NA |

### 7.18 Frontend mobile review remediation (2026-07-03)

Mobile review (`design/frontend-mobile-review-2026-07-03.md`, Playwright over 320/360/390/430/768 px;
screenshots in `design/mobile-review-2026-07-03-screenshots/`): the cockpit has a responsive shell + no
page-level horizontal overflow, but critical operational chrome (health/alerts/account) is trapped in a
horizontally-scrolling tab strip, `/program` controls sit below the 44 px touch floor, and the Plan ToolBox
clips at 320 px with an undersized keep-out radius input. Each finding is a tracked remediation row.

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| FR-16 | P1 | **Fixed mobile status/action bar -- critical chrome out of the scrolling tab strip (mobile review; extends FR-06/FS-26).** On phones `#healthchip`/`#alertbtn`/`#wsbadge`/`#whoami` live inside the horizontally-scrolling `#viewtabs` (measured x>=570 px) and scroll offscreen. Move them into a FIXED non-scrolling mobile top bar (drawer + health + alerts + workspace + account), leaving `#viewtabs` a work-area rail only; use `env(safe-area-inset-*)`. Acceptance: at 320/360/390/430 px, health/alerts/workspace/account are visible in the first viewport without horizontal tab scrolling and no body horizontal overflow. Buildable on archimedes. | D | D | D | NA |
| FR-17 | P1 | **More/profile menus are viewport-clamped mobile sheets (mobile review).** `#moremenu`/`#profmenu` are absolutely positioned inside tab-strip children and open OUTSIDE the viewport on phones (right edges ~624/~881 px). On mobile render them as `position:fixed` overlays / bottom sheets clamped to the viewport (left>=8, right<=innerWidth-8, max-height<=visualViewport-insets). Acceptance: opening More/profile at 320/390/430/768 never produces an offscreen menu rect. Buildable on archimedes. | D | D | D | NA |
| FR-18 | P1 | **/program mobile touch ergonomics (mobile review; extends FS-26).** `/program` fits width but `.fbtn` (~24 px), `#program-search` (~26 px), `.rowchip` (~22 px) are below the 44 px touch floor (263 controls under 44 px). Add a mobile media block: `.fbtn`/`.rowchip`/`#program-search` min-height 44 px, search full-width, filters wrap into 44 px rows, rows tappable; keep the working no-overflow guards. Acceptance: at phone widths every `/program` filter/search/row control >=44 px, enforced by a static guard + a runtime touch-target check. Buildable on archimedes. | D | D | D | NA |
| FR-19 | P1 | **Plan ToolBox is a viewport-contained mobile sheet with a 44 px keep-out radius control (mobile review).** The expanded `#edittools` tray clips ~2 px past the 320 px viewport (`note`/`poly` at right=322) and `#koradius` (keep-out radius, `index.html:952`) is 52x29 -- below the 44 px touch floor. Convert the expanded mobile ToolBox (`#edittoolbar`/`#edittools`/`#editmode`) into a viewport-contained sheet/drawer section (not a free-floating absolute toolbar); make `#koradius` + its radius control a full mobile row with min-height 44 px + explicit label + stepper-friendly sizing; group phone edit tools (Place/Barriers/Measure/Done). Acceptance: opening `#editmode` at 320/390/430/768 keeps every visible `#edittoolbar` button/input inside the viewport and >=44 px incl. the keep-out radius. Buildable on archimedes. | D | D | D | NA |
| FR-20 | P2 | **Mobile command-surface smoke gate (mobile review; extends FR-08).** Existing mobile tests check the breakpoint CSS + `.vtab`/`#drawerbtn` + `/program` overflow only -- they pass while offscreen chrome + undersized controls ship. Add `scripts/mobile_review_smoke.mjs` (or expand `scripts/ux_a11y_smoke.py`) asserting at 320/360/390/430/768: no body horizontal overflow; health/alerts/workspace/account visible in the first viewport; More/profile menus in-viewport; ToolBox viewport-contained; all visible cockpit + `/program` controls >=44x44 (or justified-exempt); Plan/Validate/Execute/Report/Settings/System/Admin activate without overflow. Acceptance: the gate runs the five viewports and fails on any violation. Buildable on archimedes. | D | D | D | NA |
| FR-21 | P2 | **Mobile IA control-plane split (mobile review; root cause of FR-16/FR-17).** The mobile cockpit treats work-area navigation and system command/status controls as one strip. Adopt the hierarchy: top status bar (drawer/health/alerts/workspace/account); primary workflow rail (Plan/Rehearse/Validate/Release/Execute/Report); contextual subnav (Validate sub-tabs / pane toolbars / stepper); drawer (mission inputs); account/system sheet (Settings/System/Admin/Program/sign-out). Acceptance: the mobile shell separates the stable status/action plane from the scrollable workflow rail (verified via FR-16 + FR-20). Buildable on archimedes. | D | D | D | NA |

### 7.18 Bottom-up rover autonomy architecture audit (2026-07-02)

*Source: `design/stewie-bottom-up-rover-autonomy-architecture-audit-2026-07-02.md` (skill: lunar-mission-systems-audit). Verdict: STEWIE is a strong autonomy/digital-twin SCAFFOLD, not a finished stack -- the mature logic lives in Python app modules while the ROS 2 packages are skeletons, Gazebo runs a flat regolith plane, Godot is a batch render/sensor sidecar (not a live ROS viz bridge), and the observed-perception -> world -> planner -> command-eligibility loop is not closed in the ROS runtime. Most audit gaps are ALREADY tracked: the ROS lane (AS-01..AS-18), the observed-world/closed-loop (RS-02/RS-04/FR-09/FR-11), the unified layer manifest (FR-10), the ArcGIS boundary (FR-12), preview/rehearsal labeling (FR-14), and product mode + runnable profile (FS-25). The rows below are the NEW concrete gaps not previously atomized; each cross-references the row it extends. All start N (corrected/new requirements, not yet built).*

| BA-01 | P0 | **Gazebo bridge topic-endpoint consistency gate (extends AS-06).** The audit flagged `gz_bridge.yaml` sourcing `/model/ipex/perception/points` while the xacro `gpu_lidar` sets `<topic>/model/ipex/perception` as a possible mismatch; SCREENING confirmed it is a FALSE POSITIVE -- a `gpu_lidar` publishes its PointCloudPacked on `<topic>/points`, so the bridge is correct (renaming it would break it). Deliverable: a host-side consistency test that parses `gz_bridge.yaml` + the xacro/SDF and asserts every bridged gz topic has a real sensor/plugin/system endpoint (encoding the gpu_lidar `/points`, diff-drive odom/tf, and Physics/JointState/Pose system-plugin conventions), FAILING on a real orphan. Acceptance: `ros2_ws/test_gz_bridge.py` `[REQ:BA-01]` passes on the current config (11/11 bridged topics have endpoints) and fails if any bridged topic lacks one. Buildable on archimedes. | D | D | D | NA |
| BA-02 | P0 | **Stereo `camera_info` + the missing 8-camera image topics (extends AS-05/AS-06).** The bridge/contract carry `front_left/right/image` but no `camera_info`, and the rear/side/drum cameras of the 8-camera rig are absent -- perception cannot rectify or triangulate without intrinsics. Add `/stewie/camera/front_{left,right}/camera_info` and the rear/side/drum image topics to the Gazebo bridge + `stewie/bridge/autonomy_contract.py`. Acceptance: the contract + bridge expose `camera_info` for the stereo pair and the full 8-camera image set, and a test asserts each image topic has a paired `camera_info`. Buildable on archimedes. | D | D | D | NA |
| BA-03 | P0 | **`ros2_control` is the single actuation authority for sim AND live (extends AS-03/AS-12).** The URDF exists but `ros2_control` transmissions/controllers do not, so Gazebo diff-drive and a future live robot would use different command paths. Add `ros2_control.xacro` (transmissions) + `controllers.yaml` (joint_state_broadcaster + skid/diff-drive controller) so BOTH `gazebo_sim` and `bench_robot`/`live_rover` lower commands through the same `controller_manager`. Acceptance: one controller config drives the Gazebo model and is the declared live-robot path; a launch/param test loads the controllers. Container-buildable (ROS 2 Jazzy + Gazebo). | D | D | D | NA |
| BA-04 | P0 | **Gazebo terrain generated from a real lunar DEM, not a flat plane (extends AS-06).** `ros2_ws/src/stewie_description/worlds/stewie_lunar.sdf` is a flat regolith plane ingesting no DEM/craters/rocks/world-state. Add `dem_to_gazebo_heightfield.py` emitting a Gazebo heightfield collision/visual from a real DEM (the Haworth bundle) + a world that loads it. Acceptance: a Haworth-derived heightfield world loads in the Gazebo container with correct bounds/resolution metadata, and a test validates the generated heightfield against the DEM. Container-buildable (real Haworth DEM on disk). | D | D | D | NA |
| BA-05 | P0 | **Explicit CRS transform chain body_crs->site_enu->map->odom->base_link->sensors + Godot Y-up<->REP-103 (extends FR-10).** The layer manifest (FR-10) carries a body CRS but the frame-transform CHAIN is not a tested contract, and the Godot Y-up vs ROS Z-up conversion is noted only in prose (`ipex-terrain-sim-spec.md:305`). Add `stewie/geospatial/crs_transform.py` with typed transforms per seam + a Godot<->REP-103 converter, validated against known control points. Acceptance: each transform round-trips a control point within tolerance and the Godot<->ROS conversion is tested, not asserted in prose. Buildable on archimedes (pyproj). | D | D | D | NA |
| BA-06 | P1 | **Interop conversion scripts (model/terrain/grid/bag round-trips) (extends FR-12).** The import/export interop names formats but lacks converters. Add: `xacro_to_sdf.py`, `urdf_to_godot_scene.py`, `dem_to_godot_heightfield.py`, `gridmap_to_geotiff.py`/`geotiff_to_gridmap.py`, `rosbag_to_world_transactions.py`/`world_transactions_to_replay.py`. Acceptance: each converter round-trips a real fixture (DEM<->heightfield bounds preserved, GridMap<->GeoTIFF georeference preserved, bag<->world-transaction event-count preserved) under test. Buildable on archimedes (the ROS-bag converters are container-gated). | N | N | N | NA |
| BA-07 | P1 | **Phase-0 running-sim smoke gate: one launch, real topics, truth-denial (extends AS-06/RS-04).** A single launch brings up Gazebo + `robot_state_publisher` + controllers + `gz_bridge` + RViz + bag recording; a container smoke test asserts the contract topics publish (IMU, wheel odom, camera, points), a short `/cmd_vel` moves the rover into a bag, and NO estimator subscribes a `/stewie/truth/*` topic. Acceptance: the smoke test passes in the Gazebo container and reds if a truth topic gains an estimator subscriber. Container-gated (Gazebo container). | N | N | N | NA |
| BA-08 | P1 | **`stewie_godot_bridge`: live ROS->Godot visualization, never command authority (extends RS-07/RS-08).** A ROS 2 node subscribes `/tf`, `/joint_states`, `/stewie/odom`, `/stewie/plan/path`, `/stewie/costmap`, `/stewie/map/*`, `/stewie/perception/rocks`, `/stewie/nav/factors`, `/stewie/exec/decision` and renders the URDF-derived articulated pose + overlays in Godot; it publishes NO commands (`source_class=sim_render` egress only). Acceptance: Gazebo drives ROS, Godot follows pose/articulation + overlays path/costmap/hazards, and killing Godot does not affect ROS autonomy. Container/live-gated. | N | N | N | NA |
| BA-09 | P1 | **Promote the DART/LODE autonomy logic into REAL ROS 2 nodes phase-by-phase (extends AS-07/AS-10/AS-11/AS-12).** The mature perception/mapping/costmap/planner logic lives in Python modules while `stewie_{perception,localization,mapping,planning,control,vehicle_interface}` nodes are skeletons (`ros2_ws/src/stewie_perception/stewie_perception/node.py:1`). Wrap the tested cores (`dart.hazard_map`, `lode.costmap_layers.compose`, `lode.planner_routing`, the observed-map/world-transaction path) as ROS nodes, keeping the host-side tests AND adding running-sim tests. Acceptance: at least the perception->observed-map->costmap->plan chain runs as ROS nodes in the container against injected Gazebo/Godot frames, reusing the tested Python cores. Container-gated. | N | N | N | NA |
| BA-10 | P2 | **Live robot / hardware-in-the-loop through the SAME ROS interfaces (Phase 6).** Implement the `ros2_control` hardware interface + sensor drivers + calibration/transforms + time sync + a bounded command namespace + live safety watchdog + live telemetry/bag recording, so the SAME autonomy launch runs `gazebo_sim` and `bench_robot`. Acceptance: the identical stack runs both profiles; live commands are bounded, release-gated, acknowledged, logged, and replayable. GATED: needs a physical bench rover / hardware (no container substitute). | N | N | N | N |
| BA-11 | P1 | **Mission-package import/export in open-geospatial formats (extends FR-10/FR-12).** Add `mission_package_export.py`/`mission_package_import.py` producing an ArcGIS-COMPATIBLE open package: GeoTIFF/COG DEM + layers, GeoJSON/FlatGeobuf vectors (keepouts/routes/zones/targets), STAC-style metadata, a manifest, and the authority tuple (body+site+mission+runtime_mode+runnable_profile+source_class+vehicle+role+command_namespace). Acceptance: a Haworth package round-trips (export->import) with identical layer bounds/resolution/CRS and the authority tuple preserved; ArcGIS Feature Service is left as a later adapter (FR-12), not claimed. Buildable on archimedes. | D | D | D | NA |

## 8. User Workflows

### 8.1 Construction planning

1. Select body, terrain product, site, vehicle, tools, and operating mode.
2. Place typed structures/footprints and constraints.
3. Validate terrain, power, vehicle, and mission inputs.
4. Produce one `PlanResult`.
5. Review routes, resources, uncertainty, acceptance, and infeasibility.
6. Export report and Plan IR.
7. Simulate against the authority and compare actual simulation results to forecast.

### 8.2 Mapping/navigation evaluation

1. Select a benchmark scene, sun condition, rocks, spawn, and seed.
2. Run without truth access in the estimator/planner process.
3. Execute coverage and local navigation with recovery.
4. Score pose, terrain height, rock map, coverage, energy, and failures against held-out truth.
5. Run ablations for loop closure, solar factors, active camera policy, and Meerkat observations.

### 8.3 Solar-terrain observation

1. Predict useful illumination and expected shadow direction from terrain plus `s(t)`.
2. Evaluate visibility, saturation, feature support, map uncertainty, stability, energy, and time.
3. Choose transit, arm-angle observation, LED-assisted observation, or guarded Meerkat observation.
4. Update posture-dependent camera transforms.
5. Acquire synchronized images/IMU/arm state.
6. Accept or reject shadow heading evidence using residual and covariance gates.
7. Update belief/map and replan.
8. After earthmoving, recompute terrain illumination before the next observation decision.

## 9. Verification Strategy

### 9.1 Test tiers

| Tier | Runs in standard CI | Purpose |
|---|---|---|
| T0 | Yes | Unit/domain/invariant tests. |
| T1 | Yes | Cross-module plan, vehicle, terrain, and API integration. |
| T2 | Yes | Fresh-wheel install, browser syntax, headless Godot parser/render smoke. |
| T3 | Scheduled/artifact runner | Nav/perception benchmark over fixed rendered datasets. |
| T4 | Hardware/external environment | ROS, physical/test-site, Chrono SCM, calibrated cameras/arms. |

### 9.2 Required benchmark matrix

The autonomy benchmark must vary:

- terrain seed and real-terrain crop;
- rock distribution;
- initial pose;
- sun azimuth/elevation and exposure;
- unchanged versus excavated terrain;
- low versus Meerkat observation posture;
- LEDs off/on;
- fiducials available/disabled;
- nominal versus degraded camera/feature conditions.

Every result records configuration and source hashes.

### 9.3 Solar-navigation acceptance

No solar-navigation capability claim is allowed until:

1. the sun vector and frame transform are independently verified;
2. shadow factors are rejected when inconsistent with terrain/viewpoint;
3. an ablation demonstrates benefit or clearly bounded no-benefit conditions;
4. terrain mutation invalidates/recomputes affected shadow predictions;
5. posture/camera transforms are sourced and tested;
6. Meerkat transitions maintain a positive configured stability margin;
7. energy/time/risk overhead is reported.

## 10. Roadmap

### 10.A GeoLibre-style frontend rewrite roadmap (2026-07-03)

Strangler-fig — the vanilla cockpit stays live until pane-by-pane React parity (a React rewrite was reverted
once at `55c44c6`; never big-bang). Full detail + kill-gates: `docs/geolibre_rewrite_plan_2026-07-03.md` §3.
Rough order 7-12 months for one focused builder; shorter with parallel lanes after the Phase 2/3 gates.

| Phase | Work | Kill-gate | Est |
|---|---|---|---|
| 0 | ADR + route inventory + freeze vanilla parity fixtures; pick `/app2` served path | vanilla `/app` stays default; 140 routes inventoried; no pane flip until inventory exists | 1 wk |
| 1 | React/TS shell + generated OpenAPI client + route registry + auth/state; SystemPane health first | client covers every router route or explicit exemption; shell loads signed-in/out; `/app` unaffected | 2-3 wk |
| 2 | 2D map spike (MapLibre local-projected first, deck.gl Ortho fallback) over real Haworth DEM + FR-10 | DEM/layers render non-blank; control points round-trip within tolerance; honest local-frame labels — **if 2D map fails here, STOP the UI rewrite, keep DuckDB/API as additive** | 2-4 wk |
| P (parallel) | PX + BD backend refactor: PhysicsBackend protocol + tier2_numpy adapter + BodyProfile registry + read/validate endpoints. INDEPENDENT of the UI — benefits the current cockpit too | Moon Tier-2 byte-compatible; microgravity fail-closed; `/models` + registry agree; Chrono not release-eligible | 3-5 wk |
| 4 | DuckDB-WASM workbench over FR-10 + mission packages | queries a real manifest/package; eligibility survives; within memory/latency budget | 2-3 wk |
| 5 | First pane: ReportPane (read-heavy, low command risk) side-by-side | opens a real mission's report/dashboard/provenance + empty/error; **record real per-pane hours/LOC → re-plan if >2× estimate** | 3-4 wk |
| 6 | PlanPane authoring + solve (the densest surface) | a real Haworth mission in React yields an equivalent `/plan` result to vanilla; no client-side terrain mutation | 5-8 wk |
| 7 | Rehearse / Validate(+Nav/Perc/Solar) / Release / Execute | Release refuses incomplete evidence; Execute never presents sim as live; role gates + SSE hold | 6-10 wk |
| 8 | Fleet / Construction / Models / Trainer / Admin / Settings / System | all 13 panes React-backed with fixtures + mobile + role + route coverage | 5-8 wk |
| 9 | Tauri v2 packaging + sidecar supervision + offline/degraded | cold start reaches sidecar health; crash visible in SystemPane; web parity preserved | 3-6 wk |
| 10 | Vanilla retirement: flip `/app` to React, keep `/legacy-app` one release, remove Cesium | full signed-in Playwright passes desktop+mobile; backend green; 100% pane-route coverage | 1-2 wk |

The "P (parallel)" physics/body track is the reconciled decision (Claude+Codex): it is NOT gated behind the
Phase-2 map spike, so the extensibility Aaron requires lands early and survives even if the UI rewrite stalls.
The legacy roadmap (backend/autonomy phases) continues below.

**Current position (2026-07-01):** Phase 0 exit is met (the `RB-*` release blockers are cleared in code,
see §0). The platform sits across Phase 1 (vehicle/posture twin, partial: geometry gated on LAC/IPEx data)
and Phase 2 (navigation spine, partial: the estimator + evidence path are built, the truth-free live
stack is host/pit gated). See the §0 completion snapshot for the current per-area status; the phases below
are the standing strategic arc, not a live status board.

### Phase 0: Truthful baseline and release gates

**Exit:** all `RB-*` issues closed.

- Complete physical input/state validation.
- Fix the configured suite and CI scope.
- Introduce `PlanResult`; fix fleet Plan IR/timeline/autonomy consistency.
- Repair installed-server dependencies, assets, and storage.
- Correct documentation claims and remove stale source-layout guidance.

### Phase 1: Vehicle and posture twin

**Exit:** one vehicle/arm/drum state drives physics, rendering, planning, and sensors.

- Complete `VehicleModel`.
- Import authoritative IPEx/LAC arm/camera geometry.
- Add arm joints, four drum inventories, dynamic CG, support polygon, and posture transforms.
- Implement guarded posture state machine through Meerkat and braked hold first.
- Keep drum-walk, iron-cross, and self-right behind qualification gates.

### Phase 2: LAC-derived navigation spine

**Exit:** repeatable sensor-only mapping/navigation benchmark without truth leakage.

- Time synchronization and strict frames.
- Segmentation and robust stereo feature/VO pipeline.
- Covariant estimator/factor graph and loop closure.
- Height/rock map generation.
- Coverage routes, local arc planner, tracker, and backup recovery.
- Benchmark against the `[NAVLAB26]` architecture and metrics.

### Phase 3: Solar-terrain active perception

**Exit:** validated solar evidence and arm/Meerkat observation decisions improve or safely preserve
navigation performance under defined low-sun conditions.

- Sun-vector service and mutable terrain illumination.
- Shadow extraction and weak yaw-factor fusion.
- Illumination-aware route/camera/exposure/LED policy.
- Posture-dependent views and multi-height association.
- Guarded Meerkat observation planner.
- Full ablation across sun, terrain change, posture, and seed.

### Phase 4: Construction under changing terrain

**Exit:** planning, navigation, perception, and acceptance consume the same mutated world.

- Rich footprint/goal grammar.
- Authority execution of the selected plan.
- Terrain-dependent routing and illumination updates after each work action.
- Complete structure acceptance and uncertainty bands.
- Tool/arm/drum actions in Plan IR and executive.

### Phase 5: Fleet and operational product

**Exit:** deployable, observable product with coordinated fleets and supported live I/O.

- Shared-resource fleet scheduling and coordinated replan.
- Fleet visualization and telemetry.
- Streaming command/event API and ROS lowering.
- Deployment image/docs, locks/SBOM/audit, versioned persistence, and release process.

## 11. KPIs

### Physics and construction

- Mass drift: `<= 1e-9` relative for conserved operations.
- Invalid-state acceptance: zero in public constructors/mutations.
- Plan/simulation mass and action ledger: exact within declared numeric tolerance.
- Pad flatness and other structure acceptance: per mission specification.

### Navigation and mapping

- Localization RMSE across benchmark seeds and lighting.
- Height-map RMSE and fraction of evaluated cells within `0.05 m`.
- Rock precision, recall, and F1.
- Coverage and uncertainty versus energy/time.
- Loop-closure acceptance/rejection and catastrophic-failure count.
- Local-planner collision count, stuck time, and successful recoveries.

### Solar-terrain autonomy

- Shadow-factor yaw residual and accepted-factor precision.
- Feature-track survival under low-sun/saturation conditions.
- Pose/map improvement versus no-solar ablation.
- Information gain per joule/second for transit, arm-angle, LED, and Meerkat observations.
- Stability margin and tip/fault count during posture transitions.
- Correct illumination invalidation after terrain mutation.

### Product and operations

- Fresh-wheel install and server startup.
- Full configured CI suite pass.
- Plan response consistency across totals/report/timeline/IR/playback.
- Bounded request latency, queue depth, error rate, and artifact storage.
- Reproducibility from manifest, lock, input hashes, and seed.

## 12. Non-Goals

- Flight certification.
- Full granular DEM at map scale.
- General-purpose manipulation, grasping, humanoid, or legged control.
- Fabricated arm, camera, force, or power constants.
- Claiming real closed-loop autonomy from simulator truth.
- Treating proposed solar/shadow methods as proven before ablation and qualification.

Force-controlled excavation and high-energy sintering remain gated tooling variants. Meerkat
observation is in scope; unconstrained stunt-like motion is not.

## 13. Open Decisions and Required Data

1. Exact IPEx/LAC arm pivot geometry, limits, speed, brake behavior, and lift travel.
2. Exact camera intrinsics/extrinsics, including arm-mounted camera transforms.
3. Chassis, arm, wheel, empty-drum, and fill mass properties.
4. IPEx-scale drum geometry, scoop opening, and per-drum capacity.
5. Actuator power/efficiency and posture transition energy.
6. Authoritative sun-vector/ephemeris library and site/time frame convention.
7. Solar camera response: exposure, saturation, LED photometry, and dust degradation.
8. Whether NavLab components are adopted directly, reimplemented, or used only as benchmark baselines.
9. Preregistered improvement threshold for solar-navigation and Meerkat ablations.
10. First operational target: simulator-only LAC parity, terrestrial test site, or rover hardware.
11. Invite mint authority (AG-03): directors-only (recommended default) vs any operator may mint an invite at-or-below their own role (peer/viral onboarding).
12. Default role granted by a self-service access request / open invite (AG-04): `guest`, `trainee`, or `operator`.
13. Delete governance strength (AG-06): soft-delete + ownership with self-service for your own (recommended default) vs full director-approval for every non-owner/live delete.

No `[UNKNOWN]` item may be replaced by an undocumented guessed constant.

## 14. Legacy Crosswalk

| v5 area/stage | v6 destination |
|---|---|
| A, N1, N14 | Contracts/authority (`CT-*`) |
| B, R1, R3-R7, R14, P13-P16 | Navigation/execution (`NV-*`) |
| C, D, E, L | Terrain/world (`TW-*`) |
| F, P6, R6, R8-R9, P15/P17 | Perception/mapping (`PM-*`) |
| New solar-navigation work | Solar-terrain navigation (`SN-*`) |
| K6, R12, P19 and IPEx arm work | Vehicle/arm/posture (`VT-*`, `AM-*`) |
| H, I, J, P8-P10 | Construction planning (`CP-*`) |
| K2-K11 | Energy/power (`EP-*`) |
| MV | Fleet (`FL-*`) |
| M, N7-N18, O, P11 | Product/operations (`PO-*`) |
| P12 | Split between `PM-*`, `NV-*`, and simulated mode |
| P18 | Gated vehicle/force work (`VT-09`) |

## 15. Definition of Done

A requirement is done only when:

1. implementation is merged;
2. the advertised product path consumes it;
3. acceptance tests exercise success and failure behavior;
4. representative qualification evidence exists when required;
5. documentation states limitations and provenance;
6. no contradictory status remains elsewhere in the repository.

The PRD is the current requirement source. Historical test counts, screenshots, and stage narratives
must live in release/evidence records rather than being duplicated as present-tense product status.

## Posture system + real-time drive view (2026-06-08)

- **IPEx postures (data-driven).** `terrain_authority/data/ipex_postures.json` (TRANSIT/DIG/DUMP_Z/
  MEERKAT/DRUM_WALK/IRON_CROSS/SELF_RIGHT/BRAKED_HOLD/COBRA; arm angles editable, [ASSUMPTION] geometric
  targets) + `postures.py` loader + `posture_kinematics.py` forward kinematics (chassis lift; posture
  pitch from asymmetric arms; per-camera slope-aware height: each of the 8 LAC cams = terrain +
  base_link(arms) - sinkage + attitude-rotated mount). 17 tests. Godot rig posed via the additive
  `--arm-front-pitch/--arm-back-pitch/--chassis-lift` (Python owns the data; the renderer takes angles).
- **Real-time drive view (`--drive`).** `godot_sidecar/drive_controller.gd`: live 8-SubViewport grid,
  WASD/auto drive (GDScript port of rover.step_pose; the conserved Python authority stays the analysis/
  export tier), terrain conform (sf.height_uv), posture buttons (faithful rig rebuild), per-pane camera-
  height labels. The terrain-modeller's mapping/planning drive view: the intern drives and watches what
  the rover sees through all 8 cameras at 60 fps. Headless `--drive-auto N` saves the 8 live feeds for
  verification (all 8 confirmed rendering real onboard views). Browser-cockpit stream = the (B) follow-on.
- **Offline faithful export tier (unchanged):** the full grazing-sun Hapke render + 8-pane montage/GIF.

## 16-25. Historical session logs (2026-06-08 to 2026-06-15) — extracted

The dated session-log sections §16 (STEWIE alignment) through §25 (full-stack onboard autonomy plan)
were moved to `PRD_HISTORY.md` on 2026-07-01 to keep this PRD focused on current truth. They are
provenance only (superseded by §0 + §7); nothing there is machine-parsed. See `PRD_HISTORY.md` or git
history. Any reference elsewhere in this PRD to §16 through §25 (for example §19.0, §20.3, §22.3, §23)
resolves in `PRD_HISTORY.md`. The live spec continues at §26 below.

## 26. Autoware-Shaped ShadowNav / Navigation Build Sequence (2026-06-18)

This sequence is the next execution path for STEWIE autonomy. It deliberately uses Autoware's
architecture shape, ROS2 discipline, lifecycle thinking, and visualization conventions without
importing Autoware wholesale. Lunar planning, excavation, ShadowNav, Navigation, autonomous mapping,
terramechanics, mission authority, and safety logic remain STEWIE-native.

Every item below is test-driven. The first commit for each slice must add or update the failing
`[REQ:<ID>]` test, fixture, or trace expectation before implementation. The slice is not complete
until the test passes, `scripts/req_trace.py` sees the marker, logs are visible, and the cockpit or
RViz evidence route exists where applicable.

NASA-style development rules for this sequence:
- Prefer bounded, deterministic functions for estimation and command eligibility.
- Keep safety-critical code simple enough for review: no hidden global state, no unbounded recursion,
  no silent exception swallowing, no dynamic command construction, and explicit failure returns.
- Treat simulator truth as controlled test oracle only; estimator, mapper, planner, and model code
  must not subscribe to truth topics or fixtures.
- Log every accept/reject/fallback/SAFE decision with a correlation ID across browser, backend, ROS,
  simulator, and report artifacts.
- Gate each slice with unit tests, integration tests, container smoke, static checks where available,
  and at least one failure-mode test.
- Do not mark a row `D` unless implementation, execution wiring, verification, and qualification
  evidence match the §7 status columns.

### 26.1 Ordered Implementation Plan

| Step | Requirement rows | Build action | Test-first acceptance |
|---|---|---|---|
| 0 | AS-01, AS-15 | Freeze the STEWIE-native autonomy boundary: ROS2 nodes, topic names, frame names, QoS expectations, lifecycle states, command authority, SAFE path, and truth-denial policy. | Contract test rejects missing nodes/topics, road/lanelet behavior planning dependencies, and truth-topic estimator inputs. |
| 1 | AS-02, AS-04 | Create the container-buildable ROS2 workspace skeleton: `stewie_msgs`, `stewie_description`, `stewie_bringup`, `stewie_vehicle_interface`, `stewie_perception`, `stewie_localization`, `stewie_mapping`, `stewie_planning`, `stewie_control`, and `stewie_rviz`. | `colcon test` runs in the base ROS2 container; smoke command proves the workspace builds and package discovery works. |
| 2 | AS-03, AS-17 | Add the IPEx vehicle description and TRL5 stereo/depth-source authority: chassis, wheels, excavation drum/arm joints, camera rig, IMU, optional swappable LiDAR/RGB-D mounts, inertials, collisions, joint limits, TF tree, camera intrinsics/extrinsics, lens/FOV profile, stereo baselines, and depth-source profiles loaded from the authoritative profile. | Robot-state-publisher and rig-contract tests verify the complete TF tree, expected frame names, front/rear stereo pairs, active-camera budget, optional range-sensor frames when selected, and that the TRL5-final 0.05 m profile is separate from the legacy 0.070 m frozen fixture and historical 0.165 m shoulder-split design. |
| 3 | AS-05, AS-14 | Add the RViz mission dashboard for robot model, TF, odom, planned path, local trajectory, costmaps, DEM/occupancy, point cloud, camera feeds, covariance, Navigation factors, diagnostics, SAFE state, and command topics. | RViz config lint/smoke verifies required displays; replay fixture exposes diagnostics and command eligibility state. |
| 4 | AS-06 | Add the Gazebo robot/sensor simulation seam with `/cmd_vel`, `/joint_states`, `/tf`, `/clock`, cameras, selected depth-source output, IMU, wheel odometry, contact/collision, and bridgeable terrain state. | Launch test proves Gazebo publishes expected robot, sensor, and depth/point-cloud topics; estimator test proves it consumes only truth-denied sensor outputs, never simulator truth. |
| 5 | AS-07 | Implement the Stanford/NavLab-style navigation spine: stereo feature detection, matching, stereo VO, robust PnP/triangulation, pose graph, loop-closure gates, terrain/rock mapping, coverage planning, local arcs, and recovery triggers. | Truth-denied bag tests report ATE, coverage, obstacle recall, recovery decisions, and no-truth-input assertions. |
| 6 | AS-08 | Implement ShadowNav factors: ephemeris/azimuth convention, panorama or camera shadow landmark extraction, bearing residuals, covariance, false-shadow rejection, and fusion into the localization graph. | Sun-angle ablation shows shadow factors help under supported geometry and are rejected under ambiguous/false-shadow cases. |
| 7 | AS-09 | Implement Navigation articulation navigation: commanded posture change, arm/camera kinematics, articulation-induced parallax, shadow perturbation, covariance reduction, and accepted/rejected factor visualization. | Standstill relocalization test proves accepted Navigation factors reduce covariance and rejected factors are not inserted. |
| 8 | AS-10 | Build autonomous mapping layers: observed DEM, occupancy, rock/object graph, uncertainty, changed-terrain mask, excavation state, and provenance over the conserved world model. | Mapper tests update layers from observations only and preserve separate truth, observed, forecast, and edited layers. |
| 9 | AS-11 | Build lunar costmap layers: slope, roughness, sinkage, slip, tip risk, illumination, PSR, shadow confidence, energy, keep-outs, dynamic rocks, and fleet reservations. | Planner tests prove each layer affects path cost or rejection and exposes a visible reason when it blocks motion. |
| 10 | AS-12 | Lower verified Plan IR into ROS2 paths, action goals, work goals, observation goals, bounded velocity commands, replan events, and command eligibility state under AG-08, NV-12, and SF-01. | Command tests prove unsafe, unauthorized, stale, or namespace-conflicting commands fail closed before ROS emission. |
| 11 | AS-13 | Add the ROS-side mission executive: monitor preconditions, acknowledgements, covariance, reservations, faults, acceptance state, and safing; emit continue/pause/replan/relocalize/reverse/SAFE decisions. | Executive tests cover nominal progress, timeout, blocked path, covariance loss, resource conflict, and SAFE escalation. |
| 12 | AS-14 | Wire structured ROS diagnostics and logs into the STEWIE observability ledger with lifecycle state, latency, dropped frames, QoS warnings, command eligibility, SAFE events, and correlation IDs. | Log tests prove every failure path has a ledger event and no secrets or truth-denied fields are emitted. |
| 13 | AS-16 | (MOVED to the dissertation acceptance extract; research-acceptance, not a production gate row) Build the benchmark suite comparing passive VO, Stanford-style stereo SLAM, ShadowNav, Navigation, and fused localization across sun angles, terrain changes, rocks, PSR, camera degradation, and excavation state. | Benchmark report includes per-method metrics, ablations, failure classes, fixed seeds, and reproducible container command. |
| 14 | AS-01 through AS-17 | Run release gate: requirement trace, ROS container smoke, browser cockpit evidence, RViz/Gazebo smoke, security scan, SBOM, benchmark report, TRL5 stereo-rig profile evidence, and stale-status reconciliation. | No row advances to `D` without implementation, execution, verification, and qualification evidence in §7. |

### 26.2 Front-End And Visual Organization For This Sequence

The production cockpit remains one authoritative browser application. RViz, Gazebo, ROS2 CLI, and bag
replay are engineering tools; they may run beside the cockpit but cannot carry independent command
authority.

Required cockpit panes for the autonomy sequence:
- World/map pane: DEM, occupancy, object graph, observed/forecast/edited layers, selected cloud source,
  observed DEM freshness, illumination, PSR, shadow confidence, terrain changes, and provenance.
- Sensor/rig pane: selected vehicle profile, camera placements, active stereo pair, selected depth source,
  baseline, FOV, range limits, cloud freshness, calibration/covariance status, dust/EDS status, LED profile,
  profile provenance, Gazebo/RViz/replay profile, and whether the run is using TRL5-final, calibration, or
  legacy geometry.
- Navigation pane: global route, local arc, tracker state, costmap layer breakdown, recovery action,
  blocked reason, and energy/slip/tip margins.
- ShadowNav/Navigation pane: sun azimuth/elevation source, camera/posture state, detected shadow landmarks,
  candidate factors, residuals, covariance delta, accepted/rejected factors, and explanation.
- Mission executive pane: active objective, preconditions, acknowledgements, command eligibility,
  replan reasons, SAFE state, and operator approvals.
- ROS diagnostics pane: lifecycle state, node health, Gazebo bridge status, RViz config/run status, bag
  replay status, topic freshness for `/stewie/perception/points` and command topics, QoS warnings, latency,
  dropped frames, bridge status, and container profile.
- Evidence drawer: requirement ID, fixture/bag/run ID, logs, benchmark metrics, screenshots, and report
  artifact links for the selected decision.

Full-use cockpit design requirements:

- Persistent mode/source rail: every screen shows `GIS-PLAN`, `SIM-OPERATE`, `TRAIN`, `EVALUATE`, or
  future `OPERATE`; the active runnable profile (`desktop_sil`, `digital_twin`, `ros2_replay`,
  `hil_jetson`, `sensor_bench`, `rover_bench`, `field_traverse`, or `monte_carlo`); selected sensor profile;
  command-authority state; and truth-denial label. Simulation, forecast, replay, HIL, and live state must
  never share ambiguous styling.
- Mission workflow spine: the primary operator path is Plan -> Rehearse -> Validate -> Release -> Execute
  -> Report. System and Admin remain supporting surfaces, not mission work areas.
- Plan surface: select body/site/DEM, vehicle/tool configuration, depth-source profile, constraints,
  objectives, fleet/resource reservations, and evidence requirements before solving.
- Rehearse surface: compare candidate plans, scenario variants, costmap explanations, time/energy budgets,
  map updates, and failure branches before release.
- Validate surface: split evidence into Perception, Navigation, Mapping, ROS/Gazebo, and Evidence panes.
  It must show `DepthObservation`/`PointCloud2` freshness, source profile, point count or valid fraction,
  range/covariance, observed DEM coverage, accepted/rejected factors, estimator covariance, and no-truth
  status.
- Release surface: show immutable plan revision, selected runtime profile, namespace, sensor/depth-source
  profile, AG-08 command eligibility, director/operator sign-off, and artifact links. Release cannot depend
  on an RViz-only control or hidden browser state.
- Execute surface: show only the bounded next segment or action goal, acknowledgements, link/watchdog state,
  SAFE/pause/replan controls, covariance and map freshness, and command refusal reasons. RViz/Gazebo may
  visualize the run but must not own independent command authority.
- Report surface: emit the evidence bundle with run metrics, cockpit and RViz screenshots, bag/log links,
  requirement IDs, claim labels, and pass/fail/refuted status.
- System/Admin surface: expose ROS node health, container/runtime profile, topic/QoS/dropped-frame status,
  Gazebo/RViz/bag process status, operator roles, audit events, and evidence retention controls.

Required operational cards:

| Card | Required content | Action consequence |
|---|---|---|
| Sensor Profile | vehicle profile, active cameras, depth-source profile, calibration ID, range limits, covariance model, provenance | blocks Release if missing, stale, or labelled legacy without director override |
| Depth/Cloud Health | `DepthObservation`/`PointCloud2` topic, freshness, frame, point count or valid fraction, confidence, dropped frames, degraded mode | blocks Execute if stale below the selected profile threshold |
| Map/Belief Delta | observed DEM coverage, occupancy changes, changed-terrain mask, odom-vs-belief divergence, covariance thresholds | forces replan/relocalize when thresholds are exceeded |
| Command Eligibility | AG-08 role/namespace/profile checks, SF-01 watchdog, link ack, active SAFE state, bounded next command | disables command controls and records refusal reasons |
| ROS/Gazebo/RViz Status | lifecycle nodes, `/clock`, `/tf`, `/joint_states`, bridge topics, bag replay, RViz display status, process/container profile | prevents claiming a profile-complete run without matching runtime evidence |
| Evidence Drawer | requirement IDs, fixtures/bags, logs, metrics, screenshots, validation JSON, Graphify diagnostics, report links | no row may advance to done without linked evidence |

Frontend implementation rules:
- Cockpit components consume typed adapters and view models, not raw backend JSON, ROS topic payloads, or
  ad-hoc global state.
- Every pane has explicit empty, loading, stale, degraded, error, permission-denied, and truth-denied states.
- Desktop and mobile layouts are alternate views of the same route/state model; command authority and
  approvals cannot move to a mobile-only or second-window-only control.
- No fake telemetry, simulated truth, or evaluator-only fields may be displayed as live measurements.
- The operator UI is dense, utilitarian, and workflow-first; visualizations are used to inspect state and
  command consequences, not to market the product.

Information input sequence for mission planning:
1. Select body, site, terrain product, coordinate frame, and ephemeris/azimuth convention.
2. Select vehicle, tool configuration, camera/IMU/depth-source profile, and container/runtime profile.
3. Confirm the sensor/rig profile: TRL5-final stereo baseline, FOV/lens option, active-camera budget,
   selected `DepthObservation`/`PointCloud2` source, range limits, cloud confidence, LED profile,
   calibration status, and any legacy/calibration override.
4. Load observed map layers and mark their provenance, age, uncertainty, and truth-denial status.
5. Define keep-outs, resource zones, construction targets, docking targets, and fleet reservations.
6. Enter mission objective as typed goals: traverse, observe, excavate, grade, haul, dump, dock, or
   inspect.
7. Run feasibility and costmap explanation before command lowering.
8. Review route, local trajectory, ShadowNav/Navigation observation opportunities, energy/slip/tip margins,
   and contingency branches.
9. Approve only the bounded next command or action segment, not the entire mission as an open-loop tape.
10. Monitor acknowledgements, covariance, map updates, execution feedback, and mission-executive state.
11. Replan, relocalize, reverse, pause, or SAFE through explicit logged decisions.

### 26.3 Sensor-Swappable Depth Contract

The perception stack is depth-source neutral. The no-LiDAR lunar rover profile uses calibrated stereo as
the baseline because it is lower mass and lower power; a LiDAR-equipped rover, bench rig, or simulation
profile may replace or augment that source without changing localization, mapping, costmaps, or planning.

The source selection is a runtime/profile decision, not a forked architecture:

| Depth source profile | Primary use | Required output | Claim boundary |
|---|---|---|---|
| `stereo_sgbm` | default onboard real-time path | disparity, depth, valid mask, sigma, point cloud | calibrated stereo estimate, noisier than LiDAR |
| `stereo_neural` | high-quality GPU/offboard path | disparity/depth + confidence, point cloud | only when model artifact and edge budget pass ML-09/FS-12 |
| `lidar` | hardware/testbed upgrade when available | range cloud, per-point timing/frame/calibration, confidence | direct range source, still must pass calibration/truth-denial gates |
| `rgbd` | lab/bench substitute | depth image/cloud with calibration | bench evidence, not automatically flight-equivalent |
| `replay` | SIL/regression | recorded `PointCloud2`/cloud + metadata | valid for regression only; truth topics denied to estimator |

Every source must emit the same downstream contract:

```text
DepthObservation
  source_profile: stereo_sgbm | stereo_neural | lidar | rgbd | replay
  frame_id, stamp, calibration_id, sensor_pose
  depth_image or point_cloud
  valid_mask / confidence
  range_min_m, range_max_m
  covariance or per-point uncertainty
  evidence_class
```

Downstream software consumes only `DepthObservation` or its ROS `PointCloud2` equivalent. The mapper,
DEM-registration factor, obstacle detector, construction acceptance, and cockpit visualization must not
branch on "stereo vs LiDAR" except to display provenance, confidence, and degraded-mode warnings. A
LiDAR-equipped run may be better data, but it does not bypass the same evidence ledger, calibration, TF,
and truth-denial rules.

### 26.4 Runnable Profiles

The autonomy stack must be runnable in explicitly named profiles. A profile is complete only when it has a
command, a fixture or live endpoint, expected topics/files, and an artifact bundle.

| Profile | Runs where | Purpose | Required artifacts |
|---|---|---|---|
| `desktop_sil` | developer workstation | simulator + STEWIE server + DART/LODE over deterministic fixtures | test log, metrics JSON, cockpit screenshot, world-transaction log |
| `digital_twin` | workstation/Godot host | rendered cameras/depth, sun/shadow, mutable terrain, replayable missions | render packet, depth/cloud artifact, terrain diff, evidence ledger |
| `ros2_replay` | ROS2 container | bag replay through perception/localization/mapping/planning contracts | rosbag2, RViz screenshot, topic freshness report, no-truth-input assertion |
| `hil_jetson` | Jetson or edge host + simulated sensors | CPU/GPU/RAM/thermal/latency budget and degraded-mode scheduling | perf report, ML-09 budget, dropped-frame log, watchdog log |
| `sensor_bench` | real stereo/LiDAR/RGB-D + IMU bench rig | calibrate sensor profile and range/depth uncertainty | calibration file, target measurements, covariance report |
| `rover_bench` | rover or pit testbed | bounded `/cmd_vel`, odom, watchdog, local planner, no open-loop command tape | command log, odom trace, SAFE/fault injection evidence |
| `field_traverse` | analog field or lunar-analog dataset | truth-denied autonomy benchmark | ATE/RPE, map coverage, obstacle recall, recovery decisions |
| `monte_carlo` | CI/offline batch | randomized lighting, texture, slip, terrain, sensor failures | scenario summary, failure taxonomy, regression diff |

No profile may be described as "flight-autonomy complete" unless it executes the §26.6 run-everything
gate with the selected sensor profile and records all required artifacts.

### 26.5 Algorithm Selection Policy

The default onboard stack is conservative: classical stereo/depth plus typed factors first; neural and
third-party stacks are optional accelerators or baselines.

| Function | Default | Optional / baseline | Rule |
|---|---|---|---|
| Depth | OpenCV SGBM + LR consistency | RAFT-Stereo/CREStereo/IGEV/HITNet, LiDAR, RGB-D | optional models require FS-12 + ML-09; LiDAR/RGB-D require sensor-profile calibration |
| VO/features | DART stereo VO / ORB-style features | SuperPoint/LightGlue, ORB-SLAM3, VINS-Fusion | external stacks are baselines or replaceable components behind typed factors |
| Map-relative localization | scan/heightfield-to-DEM registration + factors | RTAB-Map, Cartographer, ICP/NDT libraries | prior DEM localization is preferred over full SLAM-from-scratch when a site DEM exists |
| Mapping | observed DEM + occupancy/object layers over conserved world model | TSDF/Voxblox/Open3D/OctoMap | mapping layers stay separate from conserved truth and mutable-terrain ledger |
| Planning/control | STEWIE route/local planner + SF-01 watchdog | Nav2/Autoware-style planners | Autoware architecture shape is adopted; road/lanelet behavior is not imported |
| Mission logic | typed Mission Executive | small read-only assistant models | no free-form model directly commands ROS2 or rover hardware |

### 26.6 Run-Everything Gate

The full autonomy gate is one connected run, not a list of importable modules:

```text
selected sensor profile
  -> camera/LiDAR/RGB-D/replay input
  -> DepthObservation / PointCloud2
  -> observed DEM + occupancy/object layers
  -> localization factors (VO/IMU/wheel/dem/shadow/parallax as available)
  -> estimator covariance update
  -> costmap layers
  -> global route + local trajectory
  -> bounded cmd_vel or action goal
  -> SF-01 watchdog + command eligibility
  -> world-model update
  -> report/evidence artifact
```

Acceptance requires:

- no estimator/planner subscription to simulator truth;
- one bag or replay fixture with camera/depth/IMU/wheel/joint/time topics or equivalent files;
- selected depth source identified as stereo, LiDAR, RGB-D, or replay, with calibration/provenance;
- point cloud or observed heightfield generated and consumed by mapping/localization;
- at least one accepted or correctly rejected navigation factor with covariance and evidence class;
- route and local trajectory produced from inspectable costmap layers;
- command lowered through AG-08/NV-12/SF-01 or explicitly refused with a logged reason;
- world transaction recorded with terrain/map/belief/provenance deltas;
- metrics JSON containing latency, memory, CPU/GPU if available, coverage, ATE/RPE if truth is evaluator-only,
  fault/recovery decisions, and degraded-mode flags;
- RViz or cockpit evidence screenshot plus a report artifact linking requirement IDs and run IDs.

This is the gate that turns "stereo as virtual LiDAR," "LiDAR swappable," "ARGUS factors," and "ROS2
autonomy" into one runnable system. Passing one sensor profile does not automatically pass another:
`stereo_sgbm`, `lidar`, and `rgbd` each need their own calibration/performance evidence.

### 26.7 Fan-Out Normalization Update

The 2026-07-01 normalization pass produced `FANOUT_SPECS.md`: 62 self-contained dispatch briefs for the
current buildable ready-set, one per row, with goal, acceptance, current state, real paths, test target,
and type. Treat it as the orchestrator-facing execution layer for §7 marker work and small build slices,
not as a replacement for this PRD. The binding gates remain `scripts/req_trace.py`, `scripts/release_gate.py`,
and the §7 glyphs.

The pass surfaced three PRD-relevant findings:

- JavaScript `*.test.js` files are not currently counted by `req_trace.py` and are not run in GitHub CI, so
  JS-only frontend rows need Python citing tests or a CI/browser-tier update before they can count as V=D.
- PO-04 markers are currently misattributed to auth/secret tests; the CI-tier row needs a real workflow test.
- GI-03 appears done-stale: implementation and test coverage exist, so it should be verified and reconciled
  rather than rebuilt.

Operational rule: a fan-out agent may use `FANOUT_SPECS.md` as its dispatch brief, but it finishes only by
adding or extending a real `[REQ:<ID>]` test, running the targeted gate, and updating the PRD/status glyph
only when the implementation, execution, verification, and qualification evidence match the row.

### 26.8 Immediate Next Work

The next implementation slice is Step 0 followed by Step 1, then the Step 2 TRL5 stereo rig authority
gate. Do not start ShadowNav, Navigation, autonomous mapping, or Gazebo feature work until the ROS2 autonomy
boundary, package skeleton, container smoke, requirement traces, cockpit/diagnostic contracts, and
authoritative camera/depth-source profile are in place. That foundation prevents duplicate interfaces, keeps
navigation/mapping tied to the real sensor geometry, and makes the later navigation work measurable
instead of anecdotal.

Construction-round readiness checklist:
- `AS-01`: ROS2 autonomy boundary contract exists and blocks Autoware road/lane behavior dependencies.
- `AS-02`/`AS-04`: ROS2 package skeleton and containers build with a smoke command.
- `AS-03`/`AS-17`: IPEx vehicle, TRL5 stereo rig, and optional LiDAR/RGB-D sensor profiles are loaded by
  ROS, backend, simulator, and cockpit from one authority; legacy 0.070 m fixtures are labelled
  legacy/calibration, not final IPEx.
- `AS-05`/`AS-14`: RViz and cockpit expose rig state, diagnostics, command eligibility, and SAFE state.
- `AS-15`: failing tests, `[REQ:]` markers, deterministic fixtures, logs, and trace checks exist before
  each implementation slice.

## 27. Actionable Execution Backlog + 2-Week Sprint + Full-Fidelity UI Overhaul (2026-06-20)

This section is the appended, dated, actionable to-do register requested 2026-06-20, sequenced for
completion in the next two weeks. It is grounded in two same-day reviews — the architecture review
(this session) and the mission-ops review (`docs/architecture_review_2026-06-20_mission_ops.md`,
incorporated as co-authoritative) — plus the UI/UX design corpus. The full-fidelity UI overhaul plan
lives in `docs/ui_overhaul_plan_2026-06-20.md` and is summarized in §27.4.

New IDs introduced here (`OPS-`, `MO-`, `TR-`) are defined inline; per the chosen integration mode
they live in this section and are referenced by the sprint, **not** mass-inserted into the §7 matrix.
Existing IDs (FS-/NV-/FL-/DT-/SN-/PM-/CP-/GI-/PO-/ARCH-/AS-/B-/P-) are referenced as-is.

### 27.0 Verified baseline (this review, run on archimedes 2026-06-20)

- **Code health (local):** full suite **2418 passed / 5 skipped / 0 failed** (2423 collected, ~22 min);
  **coverage 92.91%** (gate 85%); `ruff --select F` clean; `mypy` clean (240 files); CI green
  (lint+type+cov on 3.11, test matrix 3.12/3.13). This is the no-regression baseline to diff against.
- **Deploy (public):** `app.stewie.space` returned **HTTP 502 — origin down**. Root cause: on the
  deploy host (archimedes) `docker.service` is `inactive (dead)` and `disabled`; `cloudflared` is up
  and routes `app.stewie.space → 127.0.0.1:8000`, but no frontend container is running. **Host action,
  not code.**
- **Status integrity:** the §7 matrix understates (§0 lists ~36 done-stale rows; `req_trace.py`
  reports 186 requirements, 105 test-cited, 25 V≠D flagged). Per §19.2, a row may hold `V=D` **only**
  with a `[REQ:]`-citing test (CI-enforced). The reconciliation below therefore fixes stale *headlines*
  (§4.2, §19.1) and **schedules a per-row marker pass (OPS-04)** rather than flipping unverified cells.

### 27.1 Reconciliation applied 2026-06-20

- **§4.2** carries a banner: RB-01..06 are effectively cleared in code with citing tests (per §0
  2026-06-17); no RB blocks; the residual is per-row §7 marker hygiene (OPS-04).
- **§19.1** carries a banner: the "112 requirements / 0 release-ready / 19 partial / 93 not started"
  census is stale; the live §7 matrix is ~186 rows; the parsed 2026-06-20 tally is **33 DONE /
  39 IXV-done (Q-pending) / 73 partial / 41 open-or-gated**.
- The §7 matrix glyphs are **not** mass-flipped here (would violate the §19.2 `[REQ:]` rule and could
  red the `req_trace` CI gate); OPS-04 closes them on citing evidence.

### 27.2 Actionable backlog (buildable now, in-repo; grouped, ID-mapped)

**A. Ops / deploy / status truth (highest leverage, smallest cost)**
- **OPS-01** Restore the public deploy: `systemctl start docker && systemctl enable docker`;
  `docker compose -f deploy/compose.yml up -d backend frontend`; verify **through Cloudflare**
  (`curl -I https://app.stewie.space/assets/cockpit.js`, check `cf-cache-status`, run
  `scripts/stamp_cockpit_version.py` if cockpit.js changed). Host action; rollback = `compose down`.
- **OPS-02** SEC-host: `chmod 600 deploy/.env`; rotate `STEWIE_API_KEY`; drop any stale
  `STEWIE_DIRECTOR_KEY`. (Carried from the 2026-06-15 audit.)
- **OPS-03** CI dependency hardening (= PO-04/05/09 follow-on): dependency lock + SBOM + fresh-install
  smoke; mark PO-14 done (DEPLOY.md + compose + Dockerfiles exist + current).
- **OPS-04** Single status surface: auto-derive the §7 status from `scripts/req_trace.py` +
  `scripts/release_gate.py`; publish a generated `STATUS.md` / `/figures` readout; run the per-row
  `[REQ:]` marker pass to close the 25 V≠D flags + the ~36 done-stale rows on citing tests. Retire the
  hand-maintained checkboxes in the execution plans. **Directly answers "determine exactly what is done."**

**B. Architecture health**
- **ARCH-2 — DONE (2026-06-22).** `lode/mission_planner.py` is now a 448-line facade re-exporting 10
  `planner_*` leaf modules (constants/model/routing/balance/multivehicle/endurance/trips/sim/optimize/
  assembly + the earlier views/acceptance); all public symbols byte-identical via re-export, the former
  lode↔planner_views cycle broken via `planner_constants`.
- **FS-24** Begin the `cockpit.js` (4321 LOC) module split (app shell / route-state store / typed
  adapters / view models / shared viz / work-area views / command rail / diagnostics viewers),
  preserving the no-inline-script CSP + fixture tests.

**C. Mission-ops contracts (new, from the 2026-06-20 mission-ops review; no executive needed)**
- **MO-01** `MissionIntent` → objective → constraint/flight-rule → acceptance → contingency/abort →
  task-graph typed hierarchy; mandatory objectives + hard constraints compiled before any weighted
  optimization (a flight rule is never softened into a weight).
- **MO-02** Mission-executive state machine `DRAFT→ANALYZED→REHEARSED→REVIEWED→RELEASED→ARMED→
  EXECUTING→HOLDING|SAFED|COMPLETED|ABORTED→DEBRIEFED` (RELEASED = signed immutable revision). *Spine
  for live execution; gates the Execute screen (U3).*
- **MO-03** One enforced provenance vocabulary on every operational field (`source/basis/timestamp/
  age/frame/units/confidence/revision`); reject incompatible frames/revisions, never silently combine.
- **MO-04** Strict SIM/FORECAST/LIVE visual+data labeling contract everywhere (forecast cyan /
  observed white / truth magenta directors-only); **all execution UI stays labeled SIMULATION/FORECAST
  until MO-02 exists and passes fault injection.**

**D. Planning / fleet / twin (in-repo)**
- **FL-02 / FL-04** Fleet conflict *resolution* (re-sequencing) beyond detection + MV precedence-chain
  splitting across vehicles.
- **DT-01** Operational world-model unification (authority + TwinStore + packets + PlanResult + belief
  as one transactionally linked world-state log) + W-1/W-4 durability (twin journal + cold-restore CI).
- **CP-04 / CP-07** Goal grammar (budgets/priorities/deadlines/dependencies) + per-source uncertainty
  bands (quantify the slip term).
- **SN-05** Wire `illumination_cost` into the live planner route cost; **PM-08/09** map-uncertainty
  cost coefficient feed.

**E. GIS / presentation (Demo/GMRO; detailed in `docs/ui_overhaul_plan_2026-06-20.md`)**
- **GIS S-2** Contents tree (TerriaJS workbench-card model; orders become a feature layer).
- **GIS S-3** True footprint geometry (polygon / corridor / oriented-rectangle) + QGIS edit sessions +
  order undo/redo. *(#1 "feels like a real tool" gap.)*
- **GI-02 / GI-03** Body-correct CRS labeling + per-body globe radius (stop rendering the Moon on a
  WGS84 sphere); GeoJSON / COG / OGC import+export.
- **TR-01..TR-04** Trainer dashboard A-board (operator scorecard + persisted session record) /
  B-board (director truth+divergence) / C-board (program leaderboard) / debrief scrubber.

**F. Intern-beta P23 in-repo halves (the live rclpy node stays ROS2-host-gated)**
- **B2.x** Telemetry injector (rate/latency/drop) verification; **B3.3** replay/debrief record;
  **B4.2** auto mission-summary artifact; **P1.4** scenario library (4 authored scenarios on real DEMs).

**Gated — explicitly NOT in the 2-week window** (kept honest, never stubbed): live rclpy node +
P23 traverse evidence (ROS2 host); AS-02..06 Autoware nodes/RViz (ROS2 Jazzy container);
PM-13..16 depth-source pipeline (stereo GPU/render path or live LiDAR/RGB-D bench); TM-01 calibrated terramechanics + P7 live Chrono producer
(PyChrono on euclid); Tier-3 drum forces (Chrono::GPU); RC wire binding + IPEx geometry (John / NASA);
real-traverse reconstruction + SL-01 (no public dataset); STEWIE-Orbit comms stack.

### 27.3 The 2-week sprint sequence (10 working days)

Primary axis = Demo/GMRO readiness; interleaved with Architecture-health (status truth) and the
intern-beta in-repo halves. Navigation navigation evidence is deferred (proven later). Every slice is
TDD with a `[REQ:]` marker; the full gate must stay green (baseline 2418 passed / 92.91% cov); every
UI pane flip is Playwright-verified **signed-in on a real browser** before it ships.

| Day | Slice | IDs |
|---|---|---|
| **0** | Restore deploy + verify through Cloudflare; SEC-host hardening | OPS-01, OPS-02 |
| **1** | Status truth: req_trace/release_gate → generated STATUS surface; start the per-row `[REQ:]` marker pass | OPS-04 |
| **1–2** | UI U0: FS-24 split scaffold behind FS-15 adapters; 8-area IA routing on the **vanilla** shell (fixture-tested empty panes); Playwright signed-in render harness | FS-03, FS-24 |
| **2–3** | Mission-ops contracts: MissionIntent hierarchy + SIM/FORECAST/LIVE labeling + provenance vocab | MO-01, MO-03, MO-04 |
| **3–4** | GIS S-2 Contents tree (orders → feature layer); per-body globe radius | GIS S-2, GI-02 |
| **4–5** | Fleet conflict resolution (re-sequencing); SN-05 illumination route cost | FL-02, SN-05 |
| **6–7** | GIS S-3 footprints (polygon/corridor/oriented-rect) + edit sessions + undo | GIS S-3, GI-03 |
| **7–8** | Plan-screen fidelity: 9-layer ordered map + objective/constraint inspector bound to MissionIntent | FS-03, MO-01 |
| **8–9** | Trainer A-board + persisted scorecard; intern-beta in-repo (replay/debrief, mission summary, scenario library) | TR-01, B3.3, B4.2, P1.4 |
| **9–10** | Brand B-3/B-4 (icons + patch badges) + WCAG-AA contrast pass; ARCH-2 + FS-24 increment; full-gate diff; regenerate STATUS; final signed-in Playwright sweep | B-3, B-4, ARCH-2, FS-24, OPS-04 |

**Honest sizing:** this is a prioritized *sequence*, not a guarantee every slice fully lands in 10
days for one builder; days 6–10 are the stretch. The sprint deliberately lands the **deploy + status
truth + UI foundation + the highest-value authoring upgrades**, and explicitly leaves the gated tiers
(Execute screen, live ROS2 node, dense perception, Chrono) out of the window.

### 27.4 Full-fidelity UI overhaul (summary; full plan in `docs/ui_overhaul_plan_2026-06-20.md`)

The cockpit overhaul is full-fidelity but phased, organized by the 2026-06-20 mission-ops four-screen
model (Plan / Rehearse / Execute / Debrief) over the FS-03 eight-area IA, behind the FS-15 adapters.

- **Lead decision:** an **incremental strangler-fig migration of the vanilla cockpit**, work-area by
  work-area, with Cesium + `three3d.js` kept as never-rewritten modules — **not** a big-bang framework
  rewrite. Evidence: the React+Vite rewrite already black-screened on Cesium init and was reverted
  (`55c44c6`). A framework, if used, enters as an *island* per pane and flips only after a signed-in
  Playwright render check. Adopt TerriaJS catalog/workbench *patterns* and QGIS *edit-session* model,
  not the whole apps; Cesium stays the globe.
- **Phases:** **U0 Foundation** (sprint: module split + 8-area IA scaffold + MO-01/03/04 + GIS S-2 +
  per-body globe + brand + a11y start) → **U1 Plan+Rehearse** (9-layer map, objective/constraint
  inspector, GIS S-3 footprints, trainer A-board) → **U2 Debrief+program+interop** (debrief scrubber,
  trainer B/C, pane manager named layouts, GeoJSON/COG) → **U3 Execute (GATED)** — the live Execute
  HMI unlocks only when the mission executive (MO-02) exists and passes fault injection; until then
  Execute is present but labeled SIMULATION/FORECAST.
- **Non-negotiables every phase:** preserve CSP/no-inline-script + mobile; fixture-driven per-pane
  tests; provenance (MO-03) + SIM/FORECAST/LIVE labeling (MO-04) on every field; a real signed-in
  Playwright verification before any pane flip (the lesson of the revert).

### 27.5 Fan-out execution structure (parallel agent lanes)

§27.3 is the single-builder day grid. For multi-agent fan-out the binding constraint is **file
contention, not task order** — nearly all UI items touch `cockpit.js` and several planning items
touch `mission_planner.py`, so naive parallel agents would collide. The structure is
**decouple-then-fan**.

**Contention map (what serializes a naive fan-out):**

| Shared file | Lane items that touch it | Fan-out rule |
|---|---|---|
| `stewie/server/web/assets/cockpit.js` (4321) | FS-03 IA, GIS S-2/S-3, per-body globe, Plan screen, trainer UI, MO-04 labels, brand | split via FS-24 FIRST, then one agent per extracted module |
| `lode/mission_planner.py` (448 facade) + `planner_*` leaves | MO-01 wiring (CP-04, SN-05 now CLOSED) | ALREADY SPLIT (ARCH-2 done): one agent per `planner_*` leaf; the facade only re-exports |
| `stewie/server/routers/*` | MO-*, resync, session | one agent per router file |
| test files (broad) | OPS-04 `[REQ:]` markers | additive-only; coordinate to avoid races (a concurrent session is already in `test_io_fields.py`) |

**Waves (the DAG):**
- **Wave 0 — parallel from T0, low/zero contention:** OPS-01/02 deploy (host, no code); **Lane C**
  MO-01/03/04 contracts (new files); **Lane D** intern-beta B2.x/B3.3/B4.2/P1.4 (new files); the
  **FS-24** + **ARCH-2** enabling splits; **OPS-04** status surface + marker pass. These unblock the rest.
- **Wave 1 — fans after the splits:** **Lane A (UI)** A1 IA shell · A2 GIS authoring · A3 globe/3D ·
  A4 trainer dashboard · A5 brand+a11y; **Lane B (planning)** FL-02 → `planner_multivehicle`,
  SN-05 → `planner_routing`, CP-04 → new goal-grammar module.
- **Wave 2 — cross-lane joins:** Plan-screen fidelity (needs A2 GIS + C MissionIntent); then the
  integration barrier.

**Mechanism + rules:**
1. Every code-mutating lane runs in its **own git worktree off `code/.git`** (branched from clean
   `HEAD`), so the main tree stays pristine and lanes don't stomp each other.
2. **Verification is per-lane scoped; the full suite + signed-in Playwright sweep is the integration
   gate AT MERGE**, not per-lane (standard feature-branch → CI-on-merge model). The editable install +
   `.venv` live in the main tree, so a worktree lane verifies via a per-worktree venv or proves which
   tree it tested — it must never claim green falsely.
3. **Merge order:** the enabling splits (FS-24, ARCH-2) merge before the dependent UI/planning lanes;
   new-file lanes (C, D) merge any time; OPS-04 last (it re-derives status from the merged tree).
4. Every lane is TDD, real-data-only, no stubs/synthetic/TODO; no commit/push without review; no
   Claude/co-author trailer.

This is what makes §27.3 dispatchable to a swarm without merge chaos.

## 28. STEWIE world-model / digital-twin executable architecture loop (2026-06-29)

This section supersedes ad hoc world-model planning for the next STEWIE architecture push. It folds the
current interaction catalogue, the layered reference architecture, and the gap analysis into one
agent-dispatchable loop.

Authoritative inputs:

- current implementation graph: `docs/stewie_digital_twin_interaction_map_2026-06-28.md`
- Phase 1 v2 target coverage map: `docs/stewie_interaction_layer_phase1_v2_current_2026-06-29.md`
- current-name reference architecture: `docs/stewie_layered_reference_architecture_current_2026-06-29.md`
- current gap analysis: `docs/stewie_wm_dt_architecture_gap_analysis_2026-06-29.md`
- Graphify export: `graphify-out/graph.json` from `scripts/export_stewie_interaction_graph.py`

### 28.1 Product decision

The six next layers are required, but they must be implemented as thin executable contracts over the
same interaction graph, not as six new architecture frameworks. The dependency chain is:

```text
state variables
  -> interaction wires
    -> cascades
      -> executive decisions
        -> scenarios
          -> verification evidence
```

The PRD claim boundary is:

- A row is **accounted for** when it exists in the Phase 1 v2 table with current STEWIE block names,
  variables, legacy-current mapping, status, and next-build field.
- A row is **implemented** when producer, consumer, runtime wire, log/evidence surface, and test exist.
- A row is **claimable** only when the verification layer states the acceptance criterion and the
  refutation condition, and the evidence artifact is present.
- A row marked `sim_only` may support lunar reasoning, but it must not be described as
  hardware-validated on STEWIE.

### 28.2 The six build layers

| Layer | Purpose | Deliverable | Needed now? |
|---|---|---|---|
| **WMDT-L1 State Registry** | Declare every state block, variable, unit, frame, range, owner, persistence class, and source of truth. | machine-readable registry plus rendered markdown crosswalk | yes, blocks all rigorous wiring |
| **WMDT-L2 Interaction Wiring** | Turn `INT` rows into runtime wires: ROS topics, services, message types, logs, rates, QoS, and producer/consumer ownership. | ICD table plus bridge/test stubs for each implemented row | yes, turns prose into software architecture |
| **WMDT-L3 Cascade Tests** | Convert interaction paths into connected walks with measurable propagation. | `CAS` records plus tests/replays for each path | yes, required for causal dissertation claims |
| **WMDT-L4 Executive Behavior** | Bind cascades to `ExecutiveState` decisions: hold, safe, replan, power-save, comm-loss fallback, excavation start/stop. | transition table plus behavior tests | yes, otherwise the twin does not change autonomy |
| **WMDT-L5 Scenario Runs** | Exercise multiple edges in repeatable mission playthroughs. | scenario fixtures, replay logs, Graphify trace, pass/fail summary | yes, but keep the first set small |
| **WMDT-L6 Verification Evidence** | State what proves or refutes each claim. | `VV`/`KPI`/`FID` records tied to logs, tests, figures, or NASA-open references | yes, this is the claim boundary |

### 28.3 Current coverage baseline

The 51-row current implementation graph remains the live status graph. The 60-row Phase 1 v2 table is
the target coverage graph. As of 2026-06-29:

| Status | Phase 1 v2 rows |
|---|---:|
| complete | 8 |
| partial | 22 |
| started | 9 |
| planned | 18 |
| sim_only | 3 |

Missing or under-modeled target blocks that must become first-class registry entries before their rows
can graduate:

- `DustDynamics`
- `CommunicationState`
- `MultiAgentCoordination`
- `HealthMonitoring`
- `FaultDetection`
- `ResourceModeling`
- `PredictionModels`
- `DigitalTwinSync`
- `PersistenceWorldState`

### 28.4 First vertical slices

Do not try to implement all 60 rows at once. Each loop must advance one vertical slice from state
variables through evidence.

| Slice | Interaction path | Why first | Minimum completion condition |
|---|---|---|---|
| **WMDT-S1 soft-soil caution** | `RegolithState -> WheelDynamics -> RoverBelief -> MissionPlan/ExecutiveState` | already closest to implemented and directly tied to lunar mobility | slip/sinkage raises `pos_sigma_m`; planner or executive visibly shortens, holds, or replans; replay evidence exists |
| **WMDT-S2 shadow perception loss** | `LightingModel/TerrainMesh -> PerceptionState -> FaultDetection -> MissionPlan/ExecutiveState` | central to ShadowNav and south-pole low-sun operations | changing sun/shadow lowers disparity confidence or factor acceptance; executive response is logged |
| **WMDT-S3 excavation mutates terrain** | `ExcavatorDrum -> MutableTerrainLedger/TerrainMesh -> PerceptionState/MissionPlan` | differentiates STEWIE from rover-only navigation stacks | cut/fill event changes terrain, invalidates stale map/cost, and forces remap or replan |
| **WMDT-S4 persistence and replay** | `RoverPose/MutableTerrainLedger -> DigitalTwinSync -> PersistenceWorldState` | required for digital-twin rigor and reproducible experiments | checkpoint/replay reproduces state within declared tolerance and emits divergence metric |
| **WMDT-S5 power-window survival** | `Ephemeris/LightingModel/ThermalEnvironment -> PowerThermalState -> ExecutiveState` | required for lunar south-pole mission planning | illumination or shadow window changes generation/SoC and causes a power-aware mode decision |
| **WMDT-S6 comm-loss fallback** | `TerrainMesh/Ephemeris -> CommunicationState -> ExecutiveState` | required for supervised autonomy rather than teleop claims | link state/latency window causes fallback mode and prevents unsafe open-loop continuation |

### 28.5 Parallel agent lanes

Agents may fan out only when they own disjoint artifacts or clearly additive rows. Shared status docs
and generated Graphify outputs merge last.

| Lane | Owns | Primary files | May edit | Must not edit |
|---|---|---|---|---|
| **Lane A, registry** | WMDT-L1 state variables and block ownership | new registry under `docs/` or `stewie/twin/`; reference architecture doc | variable schemas, crosswalk tables | runtime behavior |
| **Lane B, wiring** | WMDT-L2 ICD and ROS/log contracts | `stewie/bridge/`, `ros2_ws/`, wiring docs | topic/message/service contracts, bridge tests | planner algorithms |
| **Lane C, cascades** | WMDT-L3 connected paths and Graphify validation | `docs/*cascade*`, `scripts/export_stewie_interaction_graph*.py`, `graphify-out/` | CAS records, graph export, diagnostics | state variable definitions except references |
| **Lane D, executive** | WMDT-L4 behavior transitions | `lode/autonomy.py`, `stewie/contracts/`, executive router/tests | transition guards and actions | Graphify source tables |
| **Lane E, scenarios** | WMDT-L5 mission playthroughs | `validation/`, `lode/playthrough.py`, scenario docs/tests | fixtures, replay logs, scenario summaries | core schemas |
| **Lane F, evidence** | WMDT-L6 VV/KPI/FID and claim status | `docs/`, `stewie/eval/validation/`, release/status tooling | acceptance/refutation records, figures, status derivation | implementation logic except test hooks |

Merge rule: L1 registry and L2 wiring merge before L3/L4 depend on them. Scenario/evidence lanes may
start with fixtures, but they cannot mark a slice complete until the registry, wire, cascade, executive
decision, and verification record all resolve.

### 28.6 Backend-to-frontend contract

The WMDT loop must map backend state to cockpit surfaces explicitly. A row is not product-complete if it
only exists in a backend module, ROS topic, log, or Graphify table; the operator or director must have a
bounded surface that shows the state, the provenance, and the command consequence without exposing truth
to the wrong role.

The cockpit mapping uses the current ConOps spine: Plan, Rehearse, Validate, Release, Execute, Report,
plus System/Admin for health and governance. Validate owns navigation/perception evidence; Execute stays
SIMULATION/FORECAST until the relevant live-execution gates pass.

| Backend object | API/topic/log contract | Frontend surface | What the UI must show | Primary slice |
|---|---|---|---|---|
| `LunarSite` | site DEM endpoints, site metadata, body/frame config | **Plan** site selector and map header | site ID, body, lat/lon, DEM ID, cell size, frame/provenance | all slices |
| `TerrainMesh`, `RegolithState`, `MutableTerrainLedger` | `/plan`, terrain layers, terrain-memory read-back, Graphify row status | **Plan** and **Rehearse** map layers | DEM/as-built toggle, changed cells, slope/traversability, source/provenance, stale-map warning | WMDT-S1, WMDT-S3 |
| `RoverPose`, `WheelDynamics`, `RoverBelief` | `/stewie/odom`, belief packet, replay log, `/tf` | **Validate** navigation sub-pane | pose, slip, sinkage if available, `pos_sigma_m`, odom-vs-belief divergence, covariance threshold state | WMDT-S1 |
| `LightingModel`, `Ephemeris`, `PerceptionState` | `/ephemeris`, render/shadow products, selected `DepthObservation` or `/stewie/perception/points`, disparity/depth/cloud/factor logs | **Validate** perception/navigation sub-pane and RViz evidence view | sun azimuth/elevation, shadow mask, source profile, cloud freshness/count or valid fraction, range/covariance, disparity confidence, accepted/rejected factors, low-light warning, no-truth status | WMDT-S2, AS-06, PM-13..16 |
| `ArticulationState`, `CameraRig`, `SurveyedMonuments` | `/tf_static`, render packet, camera profile, landmark/factor logs | **Validate** navigation/perception sub-pane | posture, camera extrinsics, active camera pair, landmark visibility, factor acceptance/rejection | WMDT-S2 |
| `ExcavatorDrum`, `MutableTerrainLedger` | excavation event log, drum/current packet, terrain diff | **Execute** forecast and **Report** evidence | commanded cut/fill, measured or simulated volume, before/after terrain diff, acceptance status | WMDT-S3 |
| `MissionPlan` | `/plan`, `PlanResult`, `/executive/advance`, mission lifecycle evidence | **Plan**, **Rehearse**, **Release**, and **Report** | objective, constraints, route, costs, infeasible reasons, release eligibility, replay/evidence links | all slices |
| `DigitalTwinSync`, `PersistenceWorldState` | `WorldTransaction`, `TransactionLog`, checkpoint/replay diff | **System** twin/provenance pane and **Report** | world hash, chain hash, checkpoint age, replay divergence, unresolved sync mismatch | WMDT-S4 |
| `PowerThermalState`, `ThermalEnvironment`, `Ephemeris` | battery/power packet, mission windows, thermal flags | **Plan**, **Execute**, and **System** | SoC/reserve, illumination window, heater load, power-save/night-survival trigger | WMDT-S5 |
| `CommunicationState` | link-state packet, latency/ack ledger, contact-window schedule | **Execute** command rail and **System** comms pane | link state, one-way/ack latency, command eligibility, comm-loss fallback reason | WMDT-S6 |
| `DustDynamics` | dust field/deposition log, camera/panel/radiator degradation metrics | **Validate**, **System**, and **Report** | dust opacity/coverage, affected subsystem, degradation trend, sim-only or analog label | Phase 2 dust-accrual slice |
| `FaultDetection`, `HealthMonitoring` | fault rollup, health index, degradation trend, `/stewie/exec/decision` reason | **Execute** command rail and **System** health pane | active fault class, severity, trigger evidence, derating/safe action, remaining-life estimate | WMDT-S1, WMDT-S2, WMDT-S5, WMDT-S6 |
| `ResourceModeling` | resource-value map, `ice_frac`, prospecting layer, goal-priority log | **Plan** resource layer and **Rehearse** objective inspector | resource target, confidence/provenance, goal priority, excavation rationale | Phase 2 prospecting slice |
| `PredictionModels` | slip/illumination/power forecast, predictor residual, activity-window schedule | **Plan**, **Rehearse**, and **System** model pane | forecast map, prediction residual, confidence, model version, correction event | WMDT-S1, WMDT-S2, WMDT-S5 |
| `MultiAgentCoordination` | shared-map updates, reservation ledger, task split, inter-agent route state | **Plan** fleet pane and **Execute** coordination pane | agent positions, reservations, changed shared cells, route conflicts, right-of-way decision | Phase 2 multi-agent slice |
| `ExecutiveState` | `/stewie/exec/decision`, `/executive/advance`, mission lifecycle log, ROS/Gazebo/RViz runtime evidence | **Release**, **Execute**, **Report**, and **System** runtime pane | current state, guard that fired, safe/replan/hold reason, operator action required, active runtime profile, bridge/topic freshness, RViz/Gazebo/bag evidence status | WMDT-S1 through WMDT-S6, AS-02..06, AS-14 |
| `VV`/`KPI`/`FID` evidence records | validation JSON, figure path, Graphify diagnostic, test ID | **Report** and **System** validation pane | claim label, acceptance criterion, refutation condition, artifact link, pass/fail status | all slices |

Coverage check: the table above explicitly names all 18 current Graphify state blocks and all 9 added
Phase 1 target blocks. The 60 Phase 1 v2 interaction rows also resolve their source/target endpoint
tokens to these mapped objects; `all subsystems` in the checkpoint/replay row is treated as a global
view over the same mapped object set. If a new state block appears in the Graphify export or the state
registry, this table must gain a row in the same change.

Frontend completion rule for each slice:

1. **Empty state:** pane renders without fake data and names the missing backend producer.
2. **Fixture state:** pane renders a checked fixture with SIMULATION/FORECAST/LIVE label.
3. **Live/replay state:** pane consumes the real API, ROS bridge output, or replay log.
4. **Evidence state:** pane links to the test, replay, figure, Graphify diagnostic, or validation JSON.
5. **Role boundary:** operator sees operational state; director may see truth/divergence; trainee never
   sees denied truth fields.

Agent ownership:

- Backend agents own producers, schemas, APIs, topics, replay logs, and tests.
- Frontend agents own routeable panes, typed adapters, empty/loading/error/success states, and role labels.
- Evidence agents own the validation artifact and claim status.
- A slice merges only when all three views agree on the same variable names and artifact IDs.

### 28.7 Loop protocol

Each autonomous loop uses the same packet format so work can resume without rereading the whole PRD.

**Loop input packet**

- selected slice ID, for example `WMDT-S2`
- rows to advance, for example `INT-041`, `INT-043`, `INT-047`, `INT-142`
- owned lane and files
- starting status from the v2 table
- acceptance criterion and refutation condition

**Loop body**

1. Read the current source artifacts listed at the top of §28.
2. Update the state registry or interaction row only if the variable names and endpoints are current.
3. Implement the smallest runtime wire or replay needed to move one row forward.
4. Add or update the cascade/behavior/scenario/evidence artifact that proves the row moved.
5. Regenerate Graphify if endpoints, rows, or status changed.
6. Run targeted tests plus any graph/export diagnostics touched by the lane.

**Loop exit packet**

- rows changed and old -> new status
- files changed
- tests/diagnostics run
- evidence artifact path
- remaining blocker, if any, classified as code, data, hardware, NASA-reference, or sim-only
- next recommended slice

No loop may mark a row complete because the concept is documented. Completion requires an executed
artifact: test, replay, log, figure, Graphify diagnostic, or generated status surface.

### 28.8 Implementation backlog

| ID | Work item | Layer | Status |
|---|---|---|---|
| **WMDT-01** | Create the state-variable registry for the 18 current blocks and the 9 added target blocks. | L1 | next |
| **WMDT-02** | Export the 60-row Phase 1 v2 table to Graphify as a separate target graph without replacing the 51-row implementation graph. | L2/L3 | next |
| **WMDT-03** | Add ICD rows for the first three slices: soft soil, shadow perception loss, excavation mutation. | L2 | next |
| **WMDT-04** | Implement or document the cascade tests for WMDT-S1, WMDT-S2, and WMDT-S3. | L3 | next |
| **WMDT-05** | Bind first-slice cascade outputs to `ExecutiveState` decisions and logs. | L4 | next |
| **WMDT-06** | Build three scenario fixtures: soft-soil traverse, shadowed navigation, excavation-remap. | L5 | next |
| **WMDT-07** | Add VV/KPI/FID records with refutation conditions for every row touched by WMDT-S1 through WMDT-S3. | L6 | next |
| **WMDT-08** | Reconcile PRD §7 statuses affected by the new world-model/digital-twin loop through `[REQ:]` evidence, not manual flips. | L6/OPS | planned |
| **WMDT-09** | Add typed frontend adapters and pane bindings for the backend-to-frontend contract in §28.6. | UI/L2/L6 | next |

### 28.9 Claim discipline

The dissertation/committee claim should use three labels:

- **implemented in STEWIE**: code path exists, is wired, and has test or replay evidence
- **validated in STEWIE analog**: hardware or terrestrial simulation evidence supports the mechanism
- **lunar-parameterized in sim**: lunar physics is represented from NASA-open references, but not
  hardware-validated on STEWIE

This prevents the common over-claim: STEWIE can validate the mechanism and the autonomy response, while
vacuum, one-sixth gravity, electrostatic dust, PSR radiometry, multi-week thermal cycles, and long-period
relay geometry remain simulation/reference-layer claims unless a future testbed can reproduce them.

## 29. Environment-Governed Operations & Control Backend (2026-07-03)

STEWIE operations are governed by the ENVIRONMENT MODE, not by loose admin toggles. Authority (what a
session may do) is a property of the mode it runs in, enforced centrally, so nothing can accidentally cross
from training into live. The control backend is organized around four axes: authority (mode + role), intent
(mission), permission (safety), and truth + accountability (world-state + audit): admin config controls
authority, mission control controls intent, safety control controls permission, execution control controls
commands, world control controls truth, audit control records everything.

### 29.1 Core environment modes + mode-authority matrix

| Mode | Purpose | Command real robot? | Modify accepted world? | Create branches? | Publish? | Delete data? | Simulate? | Approve merges? |
|---|---|---|---|---|---|---|---|---|
| DEV | local testing, fake robots, disposable data | no | no (dev DB only) | yes | no | yes (dev only) | yes | no |
| TRAINING | simulated missions, sandboxes, guided workflows | no | no (training branch only) | training branches only | no | sandbox reset only | yes | no |
| REHEARSAL | mission simulation on REAL configs, no hardware writes | no | no (sim branch only) | simulation branches only | no | no | yes | no |
| LIVE | real robot / real mission authority | yes | yes (via merge queue) | yes | yes | no | n/a | yes (Safety Officer) |
| REPLAY | read-only historical reconstruction | no | no | no | no | no | no | no |
| ARCHIVE | frozen record | no | no | no | export only | no | no | no |

Mode authority rule (the binding invariant): TRAINING may write only to training branches; REHEARSAL only to
simulation branches; LIVE may command real assets; REPLAY / ARCHIVE are read-only. A write or command is
rejected unless the active mode grants that authority. No training-mode session can reach live world state.

### 29.2 Backend service separation

Bounded services, each owning one concern, wired by an explicit import-DAG (the packaging boundary of §7.B +
the interface contracts). The ROS 2 bridge in execution-service is the ONLY path to a real robot.

```
stewie-backend/
  config-service       settings, environment mode, feature flags
  auth-service         users, roles, permissions
  world-service        world state (bodies, branches, snapshots, accepted truth)
  mission-service      tasks, plans, assignments, approval gates
  asset-service        robots, capabilities, health, command locks
  physics-service      Forge / Chrono predictions (PhysicsBackend, PX-04)
  sim-service          Gazebo / rehearsal branches
  execution-service    ROS 2 command bridge (sole real-robot egress)
  reconcile-service    predicted vs observed merge
  training-service     lessons, scenarios, scoring, synthetic robots
  audit-service        immutable logs
  admin-api            operator / admin controls
```

### 29.3 Database + branch split

Separate databases (or hard schema isolation); LIVE is physically separate. Early setup:
`stewie_dev`, `stewie_training`, `stewie_live`, `stewie_archive`. Inside each: `actual_world`,
`simulation_branch`, `training_branch`, `replay_branch`, `what_if_branch`. Training never touches live tables.

### 29.4 Roles + permissions

Admin, Safety Officer, Mission Director, Operator, Planner, Scientist, Engineer, Trainer, Trainee, Viewer,
AI Agent. Representative floors: Viewer read-only; Trainee training mode only; Operator executes approved
missions; Planner creates plans + rehearsals; Scientist runs experiments/analysis; Engineer modifies
models/configs in non-live modes only; Admin manages users + system settings; Safety Officer approves live
transitions + critical commands. Each user carries training status + explicit live-command eligibility.

### 29.5 Training-to-live gate

Before a mission goes live, in order: (1) mission created, (2) simulation branch created, (3) rehearsal
completed, (4) physics checks passed, (5) safety checks passed, (6) human approval recorded, (7) live
execution token issued, (8) execution-service unlocks the command bridge. No live command executes without a
valid token.

### 29.6 Command safety model + invariants

```
UI request -> mission-service validates task -> safety-service checks constraints
           -> execution-service checks mode -> ROS 2 bridge sends command -> audit-service records everything
```

Critical invariants: no UI panel sends commands directly to ROS 2; no training mode writes to live world
state; no live command executes without mode, role, mission, safety, and audit approval.

### 29.7 Reconciliation lifecycle

`observed -> compared -> proposed -> reviewed -> accepted/rejected -> applied -> archived`. Carries prediction
vs observation, world diffs, confidence scores, and model/sensor error flags; manual override is logged.

### 29.8 Admin / control-backend sections (13)

System Admin (services health, versions, DB/bus/storage status, build SHA, feature flags, maintenance mode);
Users & Roles (users/teams/roles/permissions/API keys/sessions/access history/approval authority/live-command
eligibility); Environment Mode Control (the six modes + their authority definitions); Asset Control
(robots/sensors/actuators/payloads/relays/capabilities/health/limits/command locks; per-asset status/pose/
battery/thermal/comms/faults/twin link); Mission Control (creation/templates/objectives/task graph/assignment/
approval gates/execution state/abort criteria; lifecycle draft -> planned -> rehearsed -> approved -> live ->
completed -> reconciled -> archived); World-State Control (bodies/branches/snapshots/layers/WorldObjects/
accepted truth/candidate updates; create/lock/snapshot/compare/promote/rollback/archive); Simulation/Training
Control (scenarios/synthetic robots/lessons/scoring/Gazebo+Chrono runs/rehearsal branches/sandbox reset);
Physics/Model Control (Forge+Chrono versions/regolith+body profiles/terramechanics params/calibration/
validation/backend selection/freeze/deprecate); Safety Control (e-stop, live-command lock, geofences, speed/
dig-depth/slope limits, battery minimums, comms-loss behavior, collision constraints, approval gates, abort
rules); Reconciliation Control (merge proposals/diffs/confidence/accept-reject/overrides/error flags); Data/
Artifact Control (DEM/COG-GeoTIFF/GeoParquet/MCAP/images/meshes/glTF-USD/3D-Tiles/reports/checksums/URIs);
Audit/Compliance (user actions/config changes/approvals/live commands/safety overrides/merge decisions/model
changes/imports/promotions/exports; each with who/what/when/where/mode/reason/before/after/evidence);
Developer/Ops Tools (logs/metrics/tracing/event stream/queue status/migrations/import-boundary checks/schema
validation/API explorer/ROS bridge status/service restart/test scenario runner).

### 29.9 Tracked rows

The buildable core is atomized into the §7.C EG lane (EG-01..EG-12): the mode model + authority matrix, the
central mode-authority enforcement, the DB/branch isolation, the role/permission model, the training-to-live
gate + token, the command-safety pipeline, the immutable audit trail, the reconciliation lifecycle, the
service separation, the admin-console taxonomy, the safety-control layer, and physics/model control.

## 30. Mission-Planning Engine (2026-07-03)

Planning is a MISSION-PLANNING ENGINE, not a path planner. It does not "find a path": it chooses actions that
transform the world safely, with known resources, known physics, known uncertainty, and traceable
justification. The engine is a directed flow from intent to an updated world model.

### 30.1 Planning structure

```
Intent          objective, success criteria, constraints
Mission         phases, tasks, dependencies, approval gates
Capabilities    required capabilities, available assets, assignment rules
Spatial         routes, traversability, hazards, geofences
Physics         sinkage, slip, excavation force, energy, stability
Rehearsal       candidate plans, Gazebo/Chrono simulation, predicted outcomes, risk scoring
Execution       command sequence, behavior tree, monitoring, abort rules
Reconciliation  prediction vs observation, plan deviation, world update, model update
Report          mission metrics, evidence, decisions, replay
```

### 30.2 Core planning flow

`Intent -> Tasks -> Capability matching -> Candidate plans -> Physics scoring -> Rehearsal -> Approval ->
Execution -> Reconciliation -> Updated world model`.

### 30.3 Plan-executability gate

No plan becomes executable until it has all eight of: (1) required capabilities, (2) assigned assets,
(3) physics score, (4) resource budget, (5) rehearsal result, (6) safety check, (7) approval record,
(8) rollback / abort rule. This is the planning-side mirror of the §29.5 training-to-live gate.

### 30.4 Object model

`missions.intent`, `missions.mission`, `missions.task`, `missions.task_dependency`, `missions.plan`,
`missions.plan_candidate`, `missions.assignment`, `missions.resource_budget`, `missions.risk_assessment`,
`missions.rehearsal_result`, `missions.execution_policy`, `missions.plan_decision` (typed contracts, provenance
+ transaction-linked per the world-model store).

### 30.5 Planning UI panels

Mission Graph (objectives/tasks/dependencies); Map/3D View (route/terrain/hazards/work area); Capability Board
(which robot can do what); Physics Panel (slip/sinkage/excavation/energy); Timeline (task order + duration);
Resource Panel (battery/time/bandwidth/wear); Rehearsal Panel (candidate-plan simulations); Risk Panel
(confidence/safety/abort triggers); Execution Panel (approved command sequence); Reconcile Panel (predicted vs
actual outcome).

### 30.6 Tracked rows

The buildable core is atomized into the §7.D MP lane (MP-05..MP-12): the object model, the intent-to-world
flow, the eight-precondition executability gate, capability matching, physics scoring, rehearsal, the
reconciliation step, and the ten planning UI panels.
