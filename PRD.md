# STEWIE PRD: Lunar Construction and Solar-Terrain Autonomy

**Version:** 7.1
**Date:** 2026-06-15
**Status:** CANONICAL — the single source of truth for project design + reference. All other design
documents are archived (`docs/archive/`) or are upstream STEWIE architecture/roadmap sources
(maintained privately; public mapping in §16). The granular execution breakdown lives in the private
workspace: `design/STEWIE_ATOMIC_EXECUTION_PLAN_2026-06-09.md`.
**Baseline commit:** `047331250cf443498c25b5bead4bed167668752c`

## 0. Where we are / what's next (2026-06-11 — read this first)

**Status:** the research track is FOLDED IN as a live production system — STEWIE is one platform,
not a platform plus a separate research track. The trainer/simulator product (PRD §18 rung 4) is **software-complete**.

**Done (this build cycle):** all three rung-4 gaps — the pluggable RC contract + SF-01 safing
watchdog (#66, deduced from the frozen CONTRACT.md; a plan exports a reusable GoTo command tape),
telemetry shaping (#67, downlink latency + per-sol stranded-byte ledger), operator/director roles
(#68); the COLMAP/triage design + budget ledger (#69); the resync forward-sim (#70); the
NASA-standards mechanism (§19: requirements-traceability + Power-of-10 gates live in CI; SF-01
built); the 8-agent full-stack audit (§20: 2 criticals + 2 highs fixed, no known criticals
remain); the ARGUS pose-graph estimator spine (DEM + shadow-outline factors); the cockpit
(authoring, math worksheet, dashboards, mobile); Moon coordinate chain verified end-to-end.

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
>   → `shadow_landmarks.py` real cast-shadow landmarks + azimuth bearings (the ARGUS measurement). NOT
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

**Current forward order (2026-06-15, codebase-aligned):**
1. **Stabilize the production web/GIS surface.** Keep WEB-01/SEC-01 live-site hardening load-bearing:
   self-host Cesium, preserve no-inline-script CSP, remove deploy-key-in-browser paths, run a real
   Nginx/Cesium/mobile smoke, and verify the declared `server` extra is actually installed in the
   execution environment. Current local bare-interpreter checks still fail GIS globe/cache tests when
   `pyproj` is absent, despite `pyproj` being declared in `pyproject.toml` and the server/dev locks.
2. **Close the data-leak/read-auth tail.** Operational reads are gated, but `/twin/version` still exposes
   observed-twin version/history without auth. Add a least-privilege version token for ordinary clients
   and director-only history. Keep browser sessions cookie-based; no automation key may enter the DOM.
3. **Finish P3 evidence surfacing.** Head-to-head comparison, cross-dataset generalization, photometric
   render-pair, depth pass, and G1/G2 readout should be visible in System/Perception without implying
   truth-free operational SLAM parity.
4. **Finish P2 backend closure.** REG-01 DEM site imports, FORGE populate/remove, berm firming,
   map-uncertainty coefficient, MV cross-precedence, and site/body/terrain provenance should become
   normal product paths. The worksite controller seam remains hardware/protocol-gated; the Lyasko
   correction remains oracle-gated.
5. **Unify the operational world model.** The conserved authority, `TwinStore`, runtime packets,
   PlanResult, vehicle twin, and belief state must become one transactionally linked world-state log
   before the PRD may claim a production-complete digital twin.

The pre-audit queue (still valid, lower priority): the real-pit `PitBackend` over the UDP/ROS
transport (awaiting McCardle's link details); the mission-brief packet (§8); the ARGUS SE(3)+IMU
upgrade and the construction-autonomy + perception roadmap (#79: docking/berm autonomy, RL on the
multi-objective/multi-vehicle frontier, 8-cam feature front-end, shadow-outline landmark learning).

**Production readiness:** useful trainer/simulator prototype, but not a production release. The
trainer/simulator surface has many completed slices; the flight-autonomy stack, security posture,
truth-free SLAM/ARGUS path, operational digital twin, and field-calibrated terramechanics remain earlier.

**SN / ARGUS evidence path — DONE (2026-06-11):** CP-01 (release-ready), SN-02 detection front-end,
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

**NEXT SESSION — plan (2026-06-11):** finish the articulation-instrument tie-in chain, then the queued
SN slices. Bounded TDD, each gate-byte-identical with a `[REQ:]` marker + a baseline-comparing notebook:
1. **Planner relocalization stops (#96)** — the autonomy consumer: predict DR drift along a traverse and
   insert standstill parallax-fix stops where predicted uncertainty exceeds tolerance (like recharge
   stops), costed in time/energy. Notebook: drift with-vs-without scheduled relocalization.
2. **Server + cockpit action/display (#97)** — operator-triggered relocalization (perception-gated, like
   DockWithLander) + a covariance ellipse that shrinks after the fix; trainer metrics (localization σ,
   relocalization count). Live-verify in headless Chrome.
3. **SN-07 LED-budget policy (#91)**, **load-aware viewpoint selector (#92)**, **SN-01/04 promotion (#93)**.
Optional cleanup: fully unify `posture_a3`'s lift basis with `posture_kinematics` (only the parallax dh
is reconciled so far; the stability model still uses the estimated [CONFIRM] dims).
Then the bigger #79 frontier: the 8-cam SuperGlue front-end to convert the modelled fixes in the
ablations into MEASURED ones (the move from characterized to qualified, fresh-session scale).
The completed plan that produced this session, for reference:

**Completed plan (2026-06-11): the SN / ARGUS evidence path.** The trainer product is
done + gated on John's wire transport, so solo effort goes to the navigation-research contribution (the SN
family, 13 rows mostly open). Sequenced, bounded TDD slices (tasks #83-86), each gate-byte-identical
with a `[REQ:]` marker:
1. **CP-01 flip** (warm-up) — write the citing test for the produced-once `PlanResult`; clear the stale N.
2. **SN-03** — the shadow *yaw* factor in `PoseGraphSE2` (this session's shadow factor is positional;
   SN-03 is the heading-from-shadow-azimuth factor, weak + covariance-weighted from the shadow-sigma
   envelope). The core research instrument, made operational.
3. **SN-02** — the shadow-vector detection front-end (reject rover/LED/saturation/penumbra) that feeds SN-03.
4. **SN-05** — illumination-aware route cost (separable visibility/shadow-hazard/map-uncertainty terms).
The arc: detect shadow -> fuse as a yaw factor -> route by illumination, turning the shadow-sigma
calibration into a *used* channel end to end. Considered + deferred: the #79 SuperGlue front-end
(heavier, fresh-session scale) and a PitBackend skeleton (can't verify without John's protocol).

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
Those are proposed STEWIE research/product requirements derived from the IPEx/LAC platform
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

```text
L7  Product and operations
    browser / API / reports / profiles / deployment / observability

L6  Mission and fleet planning
    goals / structures / PlanResult / resources / acceptance / Plan IR

L5  Navigation and execution
    coverage planner / local planner / tracker / recovery / executive

L4  Perception and localization
    camera policy / segmentation / stereo VO / SLAM / map / solar factors

L3  ARGUS -- articulated vehicle digital twin (PRD 16.3b)
    VehicleTwin / ArmState / drums / per-drum load / CG / support polygon / work lights / camera rig

L2  Terrain, illumination, and world state
    conserved terrain / rocks / uncertainty / sun vector / shadows / mutable illumination

L1  Physical authority
    terramechanics / mobility / excavation / energy / thermal / power

L0  Contracts
    units / schemas / time / frames / provenance / invariant enforcement
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
| TW-04 | P1 | One seeded composite generator combines craters, rocks, material, and illumination parameters. | P | P | P | NA |
| TW-05 | P1 | `WorldState` carries per-cell material, traversability, observed/unobserved state, and calibrated uncertainty. | P | P | P | P |
| TW-06 | P1 | Add a site/time sun vector `s(t)` in the local world frame using a documented ephemeris interface. | D | D | D | P |
| TW-07 | P1 | Compute terrain horizon, direct illumination, cast-shadow mask, incidence angle, and overexposure risk from terrain plus `s(t)`. The dart compute (horizon / cast-shadow / `incidence_angle_deg`) is surfaced in the cockpit as toggleable `/layers` rasters: `illumination` (binary horizon shadow), `incidence` (continuous grazing-angle / overexposure-risk amber overlay, distinct from the shadow mask), and `psr`, all responding to the sun az/el controls. | D | D | D | P |
| TW-08 | P1 | Recompute affected illumination and navigation layers after excavation changes terrain. No stale pre-build shadow map may remain authoritative. | D | D | D | NA |
| TW-09 | P2 | Model camera LED contribution separately from solar illumination, including configurable intensity and pose. | P | N | N | N |
| TW-10 | P2 | Track dust/optical degradation as a state affecting image quality and maintenance decisions. `[PROPOSED]` | N | N | N | N |

### 7.3 Vehicle, Arms, Drums, and Stability

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| VT-01 | P0 | A typed `VehicleModel` supplies mass, gauge, wheelbase, wheel/contact geometry, CG, battery, drum capacity, speed, energy, sensors, and render assets. | D | D | D | P |
| VT-02 | P0 | Selecting a vehicle changes all applicable authority/planner numbers; cross-vehicle tests assert expected differences. | D | D | D | N |
| VT-03 | P1 | Model front and rear arm joint state, limits, velocity, brake state, and energy. Exact geometry must come from authoritative LAC/IPEx data. | N | N | N | G |
| VT-04 | P1 | Track four drums and per-drum fill rather than one global inventory for IPEx mode. | N | N | N | P |
| VT-05 | P1 | Compute dynamic CG from chassis, arm pose, drum pose, and fill mass. `[SPEC/PROPOSED model]` | N | N | N | G |
| VT-06 | P1 | Compute posture-dependent support polygon and static stability margin each step. | P | N | P | G |
| VT-07 | P1 | Nominal excavation requires balanced front/rear counter-rotation; asymmetric digging exposes reaction, traction, yaw, and pitch risk. | D | D | D | P |
| VT-08 | P1 | Drum fill-rate supports the sourced bridging behavior: effective collection need not increase monotonically beyond approximately half scoop depth. | N | N | N | P |
| VT-09 | P2 | Arm/drum force and torque model distinguishes horizontal reaction, vertical fill-dependent load, cutting torque, and internal tumble. | N | N | N | G |
| VT-10 | P1 | Posture-dependent camera extrinsics are derived from vehicle and arm state for every image. | N | N | N | G |

### 7.4 Meerkat and Excavator-Arm Maneuvers

The maneuver vocabulary is sourced from LAC/IPEx/RASSOR capabilities through
`[IPEx-DT-REF]`; exact geometry and transition limits remain qualification inputs.

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| AM-01 | P1 | Implement an explicit posture state machine: `TRANSIT`, `DIG`, `DUMP_Z`, `MEERKAT`, `DRUM_WALK`, `IRON_CROSS`, `SELF_RIGHT`, and `BRAKED_HOLD`. | N | N | N | G |
| AM-02 | P1 | Every transition has preconditions for slope, arm range, drum load, support contacts, stability margin, and collision clearance. | N | N | N | G |
| AM-03 | P1 | `MEERKAT` raises the camera vantage by lowering arms under the chassis; motion is speed-limited and rejected when stability margin is inadequate. | N | N | N | G |
| AM-04 | P1 | Differential front/rear arm pose may be used as a controlled camera-pitch action only after kinematic and stability validation. `[PROPOSED]` | N | N | N | G |
| AM-05 | P2 | `DRUM_WALK` supports bounded slow translation while raised and records contact/slip/energy separately from wheel drive. | N | N | N | G |
| AM-06 | P2 | `IRON_CROSS` permits wheel-cleaning/recovery only under explicit raised-posture safety limits. | N | N | N | G |
| AM-07 | P2 | `SELF_RIGHT` is a fault-recovery plan with transient stability/contact checks; it is not available as an unconstrained action. | N | N | N | G |
| AM-08 | P1 | Arm brake allows a validated posture hold with zero or modeled holding power; transition energy remains charged. | N | N | N | G |
| AM-09 | P1 | The planner may choose Meerkat only when predicted information gain or recovery value exceeds time, energy, and risk cost. `[PROPOSED]` | N | N | N | N |

### 7.5 Perception, Mapping, and Localization

The target spine follows the modular pattern demonstrated by `[NAVLAB26]`. Equivalent components are
allowed if they meet the acceptance criteria.

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| PM-01 | P0 | Time-synchronize camera, IMU, command, arm, and truth/evaluation streams using explicit clocks and frame IDs. | P | N | P | N |
| PM-02 | P1 | Support the documented IPEx/LAC camera set and a maximum active-camera budget; camera activation/resolution has compute and energy cost. | P | N | N | G |
| PM-03 | P1 | Segment at least ground, rock, lander, fiducial, and sky from grayscale images without truth masks in evaluation mode. | N | N | N | N |
| PM-04 | P1 | Detect/match illumination-robust features and expose confidence/inlier statistics. `[NAVLAB26 reference: SuperPoint + LightGlue]` | N | N | N | N |
| PM-05 | P0 | Stereo VO triangulates landmarks, maintains persistent tracks, and estimates relative SE(3) pose with robust outlier rejection. | D | N | D | N |
| PM-06 | P0 | Fuse VO/IMU and validated absolute factors in a recursive estimator or factor graph with covariance. | D | N | D | N |
| PM-07 | P0 | Loop closures are candidate-gated, geometrically verified, and auditable; false closures must not silently enter the graph. | N | N | N | N |
| PM-08 | P1 | Produce a local/world elevation map using robust per-cell aggregation and a rock occupancy/probability map. | D | D | D | P |
| PM-09 | P1 | Track observed coverage, effective sample support, uncertainty floor, and correlation; dense pixels from one view are not treated as independent evidence. | D | P | D | N |
| PM-10 | P1 | Benchmark on a fixed LAC-style suite: localization RMSE, 5 cm height-cell pass fraction, rock F1, coverage, runtime, and failure count across seeds/light/rocks. | P | N | P | N |
| PM-11 | P1 | Target benchmark: demonstrate repeatable centimeter-scale localization comparable to the `0.038-0.067 m` `[NAVLAB26]` reference before claiming parity. | N | N | N | N |
| PM-12 | P1 | Truth pose and semantic masks are development/evaluation-only and structurally unavailable to operational estimator code. | D | D | D | NA |
| PM-13 | P1 | Stereo distance/range: rectified stereo pairs yield a calibrated disparity→depth estimate to a selected pixel/target, with per-estimate uncertainty from baseline + disparity noise. Acceptance scores the estimate against the conserved truth depth in sim (no synthetic depth). | N | N | N | N |
| PM-14 | P1 | 3D depth point cloud + recognition: a dense/semi-dense point cloud is reconstructed from stereo, expressed in the world frame with per-point confidence; recognition (ground/rock/berm/pit/lander) operates on the cloud, never on truth masks. | N | N | N | N |
| PM-15 | P1 | Regional target height: over an operator-selected footprint, estimate a height field / max-min relief (berm crest, pad flatness, obstacle height) from the stereo cloud, with uncertainty; acceptance compares to the conserved as-built truth (ties CP-06 flatness/profile and I11 as-built RMSE). | N | N | N | N |
| PM-16 | P1 | Regional target volume: over a selected footprint, integrate cut/fill volume (excavated pit, spoil/berm) from the stereo height field vs a reference datum, with an uncertainty band; cross-checked against the conserved mass/volume the authority actually moved (CT-03 conservation). | N | N | N | N |

PM-13–16 are the stereo-perception *measurement* family — they feed the construction-acceptance loop and the Perception ("what it sees") pane, and are validated against the conserved-physics truth rather than synthetic data. They are the perceived counterparts to the truth-field acceptance already in CP-06/I11; all are gated on the render→depth pipeline (the §16.7 perception layer).

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
| SN-05 | P1 | Add illumination-aware route cost: visibility, saturation, shadow hazard, map uncertainty, energy, slope, and construction constraints remain separate inspectable terms. | P | P | P | N |
| SN-06 | P1 | Choose camera direction and exposure to avoid low-sun washout while preserving useful stereo overlap. | D | D | D | G |
| SN-07 | P1 | Choose camera subset and LED intensity to illuminate hard shadows within the active-camera and power budgets. | D | D | N | G |
| SN-08 | P1 | Permit arm-angle selection for near-field downward mapping or horizon/sun-grazing views using posture-dependent extrinsics. `[PROPOSED]` | D | D | D | G |
| SN-09 | P1 | Use the rover self-shadow LENGTH CHANGE under a COMMANDED articulated posture change as an instrument: the known `dh` cancels the unknown casting height, recovering sun elevation (or local slope) unbiased. `[PROPOSED]` | D | D | D | G |
| SN-10 | P1 | Triangulate landmark range from the KNOWN articulation baseline `dh` (depression-angle parallax of shadow tips), and fix rover `(x,y)` by heading-free trilateration from a standstill. `[PROPOSED]` | D | D | D | G |
| SN-11 | P1 | Permit a Meerkat observation action for multi-height parallax and shadow/rock disambiguation when stability guards pass. `[PROPOSED]` | N | N | N | G |
| SN-12 | P1 | Solar-navigation claims require ablations against VO/SLAM without solar factors across multiple sun angles, terrains, terrain-change states, and seeds. | N | N | N | N |
| SN-13 | P1 | Acceptance target `[PROPOSED]`: improve median yaw/pose error or feature-track survival by a preregistered margin without increasing tip events; report energy/time overhead. | N | N | N | N |
| SN-14 | P1 | The active-perception objective maximizes expected localization/map information per joule and second, with stability risk as a hard constraint. | P | N | P | N |
| SN-15 | P1 | Low/high posture observations must be associated to the same world features through the current arm/camera transforms. | N | N | N | G |

### 7.7 Navigation, Planning, and Recovery

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| NV-01 | P0 | Global routing rejects unreachable goals; it never substitutes an unsafe straight line. | D | D | D | NA |
| NV-02 | P1 | Coverage routes promote map coverage and deliberate re-observation/loop closure. `[NAVLAB26 reference: overlapping loops/outward spiral]` | P | N | P | N |
| NV-03 | P1 | A local planner samples dynamically feasible short-horizon trajectories and rejects rock/terrain collisions. `[NAVLAB26 reference: constant-curvature arcs]` `lode/local_planner.py`: samples a symmetric constant-curvature arc fan, rejects keep-out/rock/terrain (injected obstacle oracle), returns the max-progress feasible arc or feasible=False (NV-01: never a forced unsafe arc). Verified on the real Haworth slope map. Reachable from the cockpit via `POST /nav/local_plan` (router `stewie/server/routers/nav.py`, returns the arc + the NV-04 bounded drive command). | D | D | D | N |
| NV-04 | P1 | A path tracker converts trajectories into bounded commands and reports expected speed/progress. `lode/local_planner.py` `bounded_twist`/`track_arc`/`track_plan`: a constant-curvature arc -> a bounded (v, omega) twist (gentle = linear-capped, sharp = yaw-rate-capped), with expected speed (slip-derated via injected `(1-slip)`), duration, and arc-length progress; consumes an NV-03 plan and refuses an infeasible one. | D | D | D | N |
| NV-05 | P1 | Reactive obstacle observations update dynamic keep-outs and trigger local/global replan. `lode/reactive_nav.py` `react`: discovers newly-observed D/E rocks in sensor range (path_track), folds them into the dynamic keep-out set, and replans -- LOCAL (NV-03 arc around the updated keep-outs) first, escalating to GLOBAL when every local arc is blocked; deviation off-route also triggers. | D | D | D | N |
| NV-06 | P1 | Backup recovery triggers on progress ratio, duration, and planner failure; initial benchmark uses the `[NAVLAB26]` less-than-25%-for-2-to-3-second rule as a configurable reference. `lode/recovery.py` `recovery_needed`: fires on planner failure or sustained low progress (configurable threshold/stall window, default <25% for 2 s). | D | D | D | N |
| NV-07 | P1 | Recovery distinguishes collision/obstacle blockage from expected slope/slip slowdown to avoid false reverse maneuvers. `lode/recovery.py` `classify_stall`/`recommend`: low progress matching the slip-predicted (injected) ground speed -> 'slope_slip' (persist, no reverse); far below it -> 'blockage' (reverse); planner failure -> replan_global. | D | D | D | N |
| NV-08 | P1 | Tip, entrapment, localization divergence, low energy, thermal violation, and actuator faults are explicit fault classes. `lode/faults.py` `classify_faults`: the six classes with warn/critical severity off the existing models' signals (SSA tip margin, slip-ladder entrapment, pose-graph sigma, battery fraction vs the sourced 0.10 reserve, the -35/+40 C actuator qual, actuator status) + a safety-critical rollup the executive gates on. | D | D | D | N |
| NV-09 | P1 | An executive monitors action preconditions, command acknowledgements, belief covariance, and acceptance state, then pauses/replans/fails safely. `lode/executive.py` `executive_step`: strict safety precedence over the nav family -- safety-critical fault (NV-08) -> fail_safe; un-acked command / unaccepted step -> pause; recovery/reactive (NV-05/06/07) -> replan_global / reverse / persist / replan_local; else continue. | D | D | D | N |
| NV-10 | P0 | Plan IR maintains independent position, energy, time, and action state per vehicle. | D | D | D | NA |
| NV-11 | P1 | ROS lowering emits paths, motion commands, arm/drum goals, observation actions, and replan events from Plan IR. | N | N | N | N |
| NV-12 | P1 | Live command/telemetry uses a versioned streaming API with timestamps, sequence numbers, backpressure, and safe-stop semantics. | N | N | N | N |

### 7.8 Construction Mission Planning

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| CP-01 | P0 | One immutable `PlanResult` is produced once and consumed by totals, report, validation, timeline, Plan IR, autonomy, and UI. | D | D | D | NA |
| CP-02 | P0 | Balance bank cut and loose fill by mass with drum/capacity constraints. | D | D | D | P |
| CP-03 | P0 | Execute/validate the selected optimized plan on the conserved authority and real terrain. | D | D | D | P |
| CP-04 | P1 | Goal grammar supports typed structures, tolerances, budgets, priorities, deadlines, dependencies, and keep-outs. | P | P | P | NA |
| CP-05 | P1 | Footprints support rectangle, circle, corridor, and polygon with orientation; scalar-area squares are legacy input only. | D | D | D | NA |
| CP-06 | P1 | Acceptance includes pad flatness, berm profile, bearing/compaction, repose stability, mass, time, and energy. | P | P | P | P |
| CP-07 | P1 | Plan uncertainty carries DEM, material, slip, dig-rate, drum-fill, localization, and power-window uncertainty into feasibility/time/energy bands. | P | N | P | N |
| CP-08 | P1 | Planner objectives support hard constraints and risk terms, not only unconstrained weighted metrics. | D | D | D | NA |
| CP-09 | P1 | Construction actions mutate `WorldState`; routing, illumination, observability, and acceptance consume the updated terrain. | P | N | P | NA |
| CP-10 | P1 | Sinter remains unavailable for baseline IPEx; enabling it requires a distinct tool/power model and capability-qualified vehicle. | D | D | D | P |

CP-06 now reports pad flatness (I11), berm crest-profile vs ordered rise, and repose-angle flank stability (`validate_plan` `berm_profile`/`repose`, additive and reported in the acceptance dict, not folded into `feasible`), alongside the existing mass conservation and the simulated time/energy totals. Tests: `lode/test_cp06_acceptance.py`. The one remaining sub-item is bearing-capacity / compaction-state acceptance (needs a Terzaghi-style bearing model plus a compaction-state field from FORGE), which is why I/X/V stay P rather than D.

### 7.9 Energy, Thermal, Power, and Operations

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| EP-01 | P0 | Energy ledger includes drive, slope/slip, payload, dig, arm/drum motion, observation, LEDs, compute, idle/heater, and recharge losses where modeled. | P | P | P | P |
| EP-02 | P1 | Dig energy depends on material/density/ice or is explicitly marked constant-model uncertainty. | N | N | N | N |
| EP-03 | P1 | Distinguish PSR lander/tower power from sunlit solar power. | D | D | D | P |
| EP-04 | P1 | Mission clock enforces power, illumination, thermal, and communications windows on actions/recharge. | D | D | D | N |
| EP-05 | P1 | Thermal derating and heater/survival demand affect usable battery and action availability. | D | D | D | N |
| EP-06 | P1 | Meerkat/arm posture and camera/LED policies include transition and dwell energy. | N | N | N | G |
| EP-07 | P2 | Dust accumulation affects optics, joints, thermal surfaces, and maintenance actions. | N | N | N | N |
| EP-08 | P1 | Endurance and reports use the selected `VehicleModel`, not global IPEx constants. | D | D | D | N |

EP-04 is enforced in the battery-aware simulator: `Mission.mission_windows` = `{class: [[open_s, close_s], ...]}` for class in `recharge` (solar/power illumination), `work` (illumination/thermal), and `drive` (comms/teleop transit). `_window_gate` idles the mission clock to the next allowed interval before each gated action (a `wait` leg, no battery drawn); an action with no remaining window is skipped and recorded infeasible. Threaded through `mission_from_dict` and validated at the `/plan` boundary; `None` (or a missing class) is unconstrained and byte-identical to an un-windowed plan. Tests: `lode/test_ep04_mission_windows.py`. Q stays N: the window schedules are operator-supplied, not yet driven by real lunar day/night illumination or DTE comms ephemerides; gating is also at action-start granularity (an action that begins inside a window may run past its close). Cockpit authoring control is pending.

### 7.10 Fleet Planning

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| FL-01 | P0 | Fleet allocation, simulation, validation, timeline, Plan IR, and playback share one `PlanResult`. | D | D | D | NA |
| FL-02 | P1 | Detect and resolve route, site, and temporal conflicts rather than only same-site overlap. Detection: `_vehicle_conflicts` (same-site) + `_charger_conflicts` (shared charger) + `_temporal_conflicts` (FL-02: two vehicles working within a proximity radius at overlapping times -- space-time crowding beyond exact same-site), reported as `temporal_conflicts` + in the Fleet report. Resolution = the FCFS charger queue (FL-03); continuous moving haul-PATH crossing + re-sequencing on a work-crowding conflict are future MV work. | P | N | P | NA |
| FL-03 | P1 | Model charger, pit, dump, observation vantage, and constrained corridor as shared resources. Charger = one-server FCFS queue: overlapping recharges serialise, the loser's wait shifts its timeline, the headline makespan reflects it (`makespan_parallel_s` keeps the optimistic value, `charger_wait_s` the cost). Pit/dump/vantage/corridor are declared via `mission.shared_resources` (`[{id, kind, capacity, sites}]`) and resolved by `_resolve_shared_resources` as capacity-k FCFS servers keyed on work sites (`ReservationLedger` admission); over-capacity rovers wait, the wait folds into `makespan_s` and is reported as `resource_wait_s` / `resource_waits`. None/empty (or single-vehicle) is byte-identical. v1 schedules each resource and the charger independently (conservative upper estimate on total wait). | D | P | D | NA |
| FL-04 | P1 | Maintain one belief/health/resource state per rover and coordinate replans. `_rover_health(pv)` distils each rover's state from its sim (feasibility, lowest battery margin, recharges, health rollup stranded/low_margin/nominal) into `vehicles_detail[].health` + the Fleet report; a stranded rover sets `fleet_needs_replan` (the reallocation trigger). Active work-reallocation on the trigger is future MV work. | P | N | P | N |
| FL-05 | P2 | Support heterogeneous vehicle capability and physics vectors. | P | N | P | N |
| FL-06 | P1 | Validate two-rover plans against an exact small-problem oracle before learned/heuristic superiority claims. `plan_multi_oracle` brute-forces the true site-exclusive optimum (every group->vehicle assignment x every per-vehicle order, jointly, same simulator + charger queue) up to MV_ORACLE_MAX_TRIPS; oracle <= heuristic by construction. Verified: heuristic within 0.15% of optimum on the 3-site instance. | D | N | D | NA |
| FL-07 | P1 | Solar/Meerkat observation sites are reservable fleet resources so rovers do not occlude or collide during raised observations. `[PROPOSED]` | N | N | N | N |

### 7.11 Product, Packaging, and Operations

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| PO-01 | P0 | `stewie-serve` (alias `stewie-serve`, deprecated) works after a fresh wheel install with one documented product extra. | P | P | N | N |
| PO-02 | P0 | Reports, profiles, caches, and renders use configurable application-data directories and atomic writes. | D | D | D | NA |
| PO-03 | P0 | CI installs declared dependencies and runs the configured suite across supported Python versions. | D | D | D | NA |
| PO-04 | P0 | CI separately gates Python core, scripts, Godot, browser, package smoke, and hardware-gated tiers. | P | N | P | NA |
| PO-05 | P1 | Commit a dependency lock, build an SBOM, scan resolved artifacts, and run a fresh-install test. | P | N | N | NA |
| PO-06 | P1 | Server enforces streamed body limits, execution timeouts, bounded concurrency, auth policy, and deployment-safe CORS. | D | D | D | N |
| PO-07 | P1 | Structured logs include request/event ID, mode, plan ID, route, duration, outcome, and error class. | D | D | D | N |
| PO-08 | P1 | Metrics are bounded and exportable in a standard operations format. | D | D | D | N |
| PO-09 | P1 | Mission/profile schemas are versioned and migratable. | P | P | P | NA |
| PO-10 | P1 | UI distinguishes forecast, simulation truth, estimator belief, and live telemetry. | P | P | P | NA |
| PO-11 | P1 | Fleet playback renders every rover and its independent telemetry. | N | N | N | NA |
| PO-12 | P1 | Solar view displays sun vector, illumination/shadow layers, active cameras/LEDs, arm posture, and evidence accepted/rejected by localization. | N | N | N | N |
| PO-13 | P1 | Add `CHANGELOG.md`, exported `__version__`, SemVer policy, and release evidence manifest. | D | P | D | NA |
| PO-14 | P1 | Provide deployment documentation and a supported server image; optional Godot/ROS capabilities are explicit profiles. | N | N | N | N |

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
| AG-08 | P0 | **End-goal gate:** real rover instructions (NV-11/NV-12) are emitted ONLY from a `live`-namespace mission, by an `operator`+, under the SF-01 interlock. Sandbox/trainee/guest plans may simulate and output a Plan IR for review but cannot lower to hardware commands. | D | D | D | NA |

### 7.13 Cross-Cutting Production Requirements (added 2026-06-15)

These rows close the gaps found by the 2026-06-15 PRD-to-code review. They are deliberately narrow:
they do not turn STEWIE into ArcGIS, a flight-certified autonomy stack, or a high-fidelity granular
DEM. They make the advertised product boundary enforceable.

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| GI-01 | P0 | Production GIS runtime gate: the built Nginx/front-end image loads Cesium, Moon/Mars/Earth imagery, worksite overlays, sign-in, and mobile navigation under the actual CSP with zero blocking console errors. Acceptance is a desktop + mobile browser smoke against the deployed headers, not a direct asset curl. | P | P | P | N |
| GI-02 | P1 | Planetary map correctness: Moon/Mars views use body-correct ellipsoid/CRS metadata and real DEM terrain/elevation where a layer claims 3D terrain. A smooth WGS84 drape must be labeled as imagery-only, not terrain. | P | N | N | N |
| GI-03 | P2 | GIS interoperability scope: define and implement the mission-required subset only -- GeoJSON/COG import, selected OGC/ArcGIS service consumption, feature attributes/query, measurement/profile tools, provenance, and offline mission package export. Do not claim ArcGIS parity. | N | N | N | NA |
| DT-01 | P0 | Operational digital-twin unification: conserved authority, observed `TwinStore`, runtime packets, vehicle twin, PlanResult, belief state, and session events are linked by one versioned transaction envelope with mission/site/body/time/provenance/uncertainty. | P | N | N | N |
| DT-02 | P0 | Twin audit read security: `/twin/version` exposes only a minimal authenticated version token to ordinary clients; full event history/provenance requires director/admin authorization and audit logging. | D | D | D | NA |
| RL-01 | P1 | Deployed RL policy gate: no RL capability may be called operational until a versioned policy artifact, training/eval lineage, model card, safety shield, deterministic fallback, and out-of-distribution acceptance report exist. Training scripts/environments alone do not satisfy this row. | P | N | N | N |
| SL-01 | P0 | Truth-isolated SLAM/ARGUS benchmark: runtime bags and estimator processes are physically denied truth topics/frames; the full render/sensor/RTAB-Map-or-equivalent/ARGUS/pose-graph pipeline is scored by an evaluator-only channel with pass/fail thresholds. | P | P | P | N |
| SE-01 | P0 | Full security audit gate: release requires a completed host, container, app, DNS/site, secret, backup/restore, dependency/SBOM/CVE, and external exposure audit. The current non-invasive Archimedes/site review is not sufficient. | P | N | N | N |
| TM-01 | P1 | Calibrated terramechanics/excavation gate: construction forecasts distinguish analytical surrogate, calibrated mission model, and offline oracle; excavation resistance, drum/arm torque, drivetrain/current limits, low-g parameters, and uncertainty are validated before field-confidence claims. | P | P | P | N |

### 7.14 Small-Model Autonomy Architecture (added 2026-06-15)

The on-rover autonomy architecture is **not** a single large VLM directly commanding ROS2. For an
IPEx-class excavator, learned components are bounded specialist estimators or planners behind typed
contracts. The world model and mission executive own state, authority, safety, and command emission.
LLMs may draft plans or explain telemetry, but they do not directly actuate the rover.

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| ML-01 | P0 | Model-orchestration rule: every learned model declares input schema, output schema, latency budget, compute/memory budget, calibration set, uncertainty output, failure modes, and safe fallback. Mission Executive consumes only typed outputs, never free-form model actions. | D | P | D | N |
| ML-02 | P1 | Terrain Assessment Model: stereo/depth, DEM, slope, shadow, and uncertainty layers produce traversability, hazard class, slope/roughness summaries, and confidence for the local planner. | P | N | N | N |
| ML-03 | P1 | Rock Classification Model: image/depth observations produce rock size, class, confidence, and navigation/excavation relevance; Class-A `>7 cm` hazard classification is acceptance-gated against held-out truth/evaluation labels. | P | N | N | N |
| ML-04 | P1 | Shadow-SLAM / ARGUS Model: image pair or sequence plus sun geometry and articulation pose propose pose/landmark factors with covariance; the factor graph accepts them only through residual/observability gates. | P | P | P | N |
| ML-05 | P1 | Excavation State Model: drum torque/current, wheel slip, IMU, arm/drum state, and drive current estimate digging state, fill fraction, slip, stall risk, and confidence; advisory until calibrated against IPEx/AutoDig-style data. | P | N | P | N |
| ML-06 | P1 | Regolith Volume Estimator: before/after DEM or stereo heightfields estimate moved volume/mass with uncertainty, cross-checked against conserved authority mass and drum-fill sensing. | P | N | P | N |
| ML-07 | P1 | Mission Planner LLM: a small language model may convert operator intent into candidate task graphs, but plans must compile to typed goals, pass deterministic validation, and be approved by the mission executive before simulation or command lowering. | N | N | N | N |
| ML-08 | P1 | Science/Operator Assistant: a separate explanatory model may summarize telemetry, faults, and evidence; it has read-only access and no command path. | N | N | N | N |
| ML-09 | P0 | Edge deployment envelope: any simultaneous model set intended for IPEx-class hardware must fit the selected compute profile (for example Jetson Orin NX/AGX class) under measured RAM, power, thermal, latency, and sensor-I/O budgets with degraded-mode scheduling. | N | N | N | N |

### 7.15 Full-Stack Onboard Autonomy Build Requirements (added 2026-06-15)

These rows turn the onboard-autonomy roadmap into atomic product work. They explicitly include
multi-vehicle coordination, path planning, navigation, ephemerides/azimuth, ARGUS, front-end
restructuring, backend-to-frontend wiring, testing, optimization, security, and model hardening.
The sequence is defined in §25. No broad rewrite is allowed: each slice must start from a current
front-end/back-end inventory, add one contract or view, and land with tests before the next layer
claims completion.

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| FS-01 | P0 | Codebase assessment gate: before implementing a roadmap slice, inventory the touched front-end panes, backend routers, domain modules, tests, data contracts, security boundaries, and deployment assumptions. Acceptance is an updated slice note or PRD entry naming affected files/modules and existing tests. | P | P | P | NA |
| FS-02 | P0 | Contract spine: define versioned schemas for `WorldState`, `VehicleState`, `FleetState`, `BeliefState`, `PlanResult`, `ExecutionEvent`, `EphemerisObservation`, `ARGUSFactor`, `ModelArtifact`, and `ConstructionSkill`. Backend APIs and cockpit views must consume these contracts instead of ad hoc payloads. | D | D | D | NA |
| FS-03 | P0 | Front-end information architecture: restructure the cockpit so Plan, Fleet, Navigation/ARGUS, Perception/Imagery, Construction, Models, Security/System, and Reports are first-class work areas with mobile-safe layouts and explicit truth/belief/forecast/live labels. | P | N | N | NA |
| FS-04 | P1 | Multi-vehicle coordination: extend allocation into coordinated execution with per-vehicle state, shared-resource reservations, space-time corridor deconfliction, cross-vehicle precedence, conflict explanation, and safe replan/fallback behavior. | P | N | P | N |
| FS-05 | P1 | Path-planning and navigation stack: connect global route planning, local trajectory sampling, tracker, recovery, keep-outs, negative obstacles, illumination risk, slip/energy budgets, and ROS2/Autoware-style action lowering through one auditable navigation contract. | P | N | P | N |
| FS-06 | P0 | Ephemerides and azimuth authority: one backend service owns mission time, body/site frame, sun vector, sun elevation, azimuth convention, uncertainty, cache/provenance, and all shadow consumers. Acceptance includes cross-module azimuth tests and UI display of the convention. | D | D | D | P |
| FS-07 | P1 | ARGUS operational loop: articulation pose, camera rig, shadow/parallax observation, pose-graph factor, residual gate, covariance update, operator evidence view, and planner-triggered relocalization stop form one closed loop. | P | P | P | N |
| FS-08 | P0 | Backend-to-frontend wiring: every new autonomy capability exposes a typed API, OpenAPI/schema example or equivalent fixture, cockpit state binding, loading/error/empty states, and a browser regression test covering desktop and mobile widths. | P | N | N | NA |
| FS-09 | P0 | Test pyramid: each slice lands with unit tests for math/contracts, backend route tests, front-end interaction tests, traceability markers, deterministic fixtures, and one integration/e2e path where the capability is user-visible. | P | P | P | NA |
| FS-10 | P1 | Optimization budgets: define and enforce latency, memory, CPU/GPU, bandwidth, tile/cache, and model-inference budgets for map rendering, planning, fleet solving, ARGUS estimation, and cockpit mobile performance. | P | P | P | N |
| FS-11 | P0 | Security and hardening gate: capability work must preserve fail-closed auth, role gating, no automation secrets in browser state, CSP/no-inline-script deployment, SBOM/CVE review, backup/restore assumptions, and command-path interlocks. | P | P | P | N |
| FS-12 | P1 | Model integration and fine-tuning hardening: every learned model has dataset lineage, train/eval split, artifact registry entry, model card, quantization/deployment profile, calibration report, OOD detector, safe fallback, and rollback plan before cockpit exposure. | P | N | N | N |
| FS-13 | P1 | Recorded construction and self-docking skills: record, version, replay, compare, and approve movement primitives for excavation, dumping, berm shaping, and docking; replay must be corrected by belief feedback and bounded by safety checks. | P | N | N | N |
| FS-14 | P0 | Atomic rollout rule: the roadmap is implemented in dependency order; a phase cannot be marked done until the previous phase's contracts, front-end affordance, backend route, tests, security review, and performance budget are complete or explicitly gated. | P | N | N | NA |
| FS-15 | P0 | Front-end contract adapters: each cockpit work area owns a typed client adapter, request/response fixture, normalized view model, loading/error/empty mapping, and permission mapping. UI components consume view models, not raw backend JSON. | P | N | N | NA |
| FS-16 | P0 | Cockpit state and routing: the app has one routeable state model for selected mission, site, vehicle, body, time, mode, role, work area, selected entity, and live/sim/eval source. Desktop and mobile navigation are alternate views of the same state, not separate logic. | D | D | P | NA |
| FS-17 | P0 | Windowing policy: the production operator flow is one browser cockpit. Any second window is read-only engineering/debug context or a separate ROS/RViz/Gazebo tool; it cannot hold independent command authority, hidden state, or unique approval controls. Enforced in `cockpit.js` by a single-authority election (`CMD_AUTH`: a localStorage claim + heartbeat, `BroadcastChannel` + `storage`-event sync); a window without the fresh claim is read-only (`body.dataset.cmdrole`), shows the `#cmd-readonly-banner`, disables `[data-cmd-authority]` command controls, and `guardCommand` refuses the command-tape emit. An explicit Take-over control promotes a window (no silent promotion of a hidden tab). Two-tab behavior Playwright-verified; static wiring guarded by `stewie/server/test_fs17_command_authority.py`. | D | D | D | NA |
| FS-18 | P0 | Frontend-backend contract gate: every new route-to-pane connection has a schema fixture, backend route test, frontend fixture render test, permission test, mobile-width smoke, and one failure-mode test before it is considered wired. | P | N | N | NA |
| FS-19 | P0 | End-to-end observability ledger: log every mission decision, operator action, role/permission check, backend contract call, plan/replan, command emission, safing event, model inference summary, ARGUS factor accept/reject, fleet conflict, and state transition with correlation ID, mission/site/body/time, actor, input/output hashes, result, latency, and error code. Secrets, passwords, tokens, private keys, and operational truth-denied fields must never be logged. | P | P | P | NA |
| FS-20 | P1 | Cockpit chrome IA: System, Settings, and Admin move OUT of the top-level work-area tab bar into a profile/account menu, role-gated (Settings per-user; System eng/director; Admin director-only) — an operator sees only the mission work areas. Directors get a read-only log/audit viewer surfacing the FS-19 observability ledger (logs visible to admins; secrets/tokens/truth-denied fields never shown). | D | D | D | NA |
| FS-21 | P2 | Customizable workspace: within a work area, panes can be rearranged (drag-and-drop / dock) and the layout persists per operator (localStorage + optional server profile), with reset-to-default always available. Layout is a VIEW preference only — it never changes command authority, AG-08 gating, role gates, or which contract a pane consumes. | P | P | P | NA |
| FS-22 | P0 | PRD-code reconciliation gate: before claiming "complete the PRD", audit every open or partial §7 row against code and tests, classify it as DONE-stale, PARTIAL, OPEN, or BLOCKED, and record file:line evidence plus the smallest next action. Stale PRD statuses must be corrected before new implementation work is counted. | D | P | N | NA |
| FS-23 | P1 | Architecture review ledger: maintain a living full-stack map from PRD row -> backend route/service -> domain module -> frontend adapter/view -> tests -> logs. It must expose missing links without implying the capability is done. | P | N | N | NA |
| FS-24 | P1 | Front-end module organization: split the cockpit into app shell, route/state store, typed API adapters, domain view models, shared visualization components, work-area views, command/approval rail, and diagnostics/log viewers. The split must preserve CSP/no-inline-script and fixture-driven tests. | P | N | N | NA |

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

Force-controlled excavation and high-energy sintering remain gated research/tool variants. Meerkat
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

## 16. STEWIE alignment (2026-06-09)

**STEWIE** (Surface Terrain Engineering & World-model Integration Environment, McCardle & Storey,
June 2026) is the adopted platform name + responsibility architecture over this codebase. IPEx is the
hardware program ("IPEx builds the Moon; STEWIE plans the build"; *in silico → in situ*). Subsystems
own OUTCOMES, not algorithms. Authoritative architecture/roadmap docs are maintained privately;
this section is the public mapping of record.

### 16.1 Subsystem ↔ codebase mapping
| STEWIE subsystem | Question it answers | Existing code (this repo) | Primary gap |
|---|---|---|---|
| **STEWIE platform** | What is happening on the Moon right now? | stewie physics authority, the server/UI, io_fields twin seams, world-model/forward-sim engines (`autonomy`, beam search) | live ROS2 bridge; telemetry injection; director/operator split |
| **DART** (perception) | What does the world look like? | Godot sensor render, YOLOv8/U-Net++ detectors, `dem_import` (LOLA + GeoTIFF), `map_channel`, `localization` | typed interface contract; COLMAP→resync pipeline |
| **LODE** (operations) | What should happen next? | `mission_planner` (7-alg optimizer, multi-vehicle, precedence, plan IR, PDF report), scheduler | acquisition inventory; bandwidth-aware downlink queue |
| **LEAP** (earthmoving) | How should we move the regolith? | conserved cut/fill/dump physics, `structures`, skill/worksite envs, build-order queue | per-structure policy; multi-vehicle routing |
| **FORGE** (infrastructure) | What are we building? | sinter authority (gated, `SINTER_ENABLED=False`), `validate_plan`/I11 as-built acceptance | typed interface; certified-record provenance store |

### 16.2 Phase-1 gate — the new top of the forward queue
The ROS2 bridge is the first gate on operational usefulness (the sim must speak the real robot's
language). These stages PRECEDE the previously queued P-stages:

| Stage | Deliverable | Acceptance |
|---|---|---|
| **P20 ROS2 bridge** | bidirectional bridge: sim state → standard sensor/geometry topics; `/cmd_vel` → the physics drive loop; REP-103 ↔ sim frame mapping implemented ONCE at the bridge | container starts, `/healthz` 200, ROS2 node joins the graph, external teleop moves the simulated rover |
| **P21 Telemetry injection** | configurable bandwidth/latency/drop/frame-rate layer from a mission-profile JSON ("ideal" profile = constraints off) | operator node receives downsampled/delayed data; drops counted + reported; director sees full-rate |
| **P22 Director/operator split** | session-mode toggle: operator view = telemetry-constrained only; director view = full state + auth + replay/debrief (fast-forward without breaking link time accounting) | two browser sessions, one simulation; side-by-side replay of seen-vs-actual trajectory |
| **P23 Intern beta (Day 28)** | Docker container packaging physics + server + bridge; end-to-end training run with real remote-control software | operator completes a simulated Haworth traverse in <30 min with no technical assistance |

Note: the container exposes host port 8000 per the STEWIE docs; the app's internal default (8770)
is unchanged — the container maps the port.

### 16.3 Year-1 phase ↔ P-stage crosswalk
- **Ph.1 (Mo 1–3) Training sim** = P20–P23 + full motion-planner topic set + scenario library +
  pluggable external-planner interface + DEM site expansion (wires the existing `dem_import`).
- **Ph.2 (Mo 4–6) World model + charging gap** = COLMAP→GeoTIFF→**resync POST API** (versioned twin)
  + forward-sim ensemble service/panel (existing headless engines) + **DART typed contract locked**
  (extends P6/P15).
- **Ph.3 (Mo 7–9) Data management** = acquisition inventory (per-cell imagery/sun-angle/downlink) +
  world-model uncertainty map + bandwidth-aware downlink queue + science-targeting overlay (extends
  `map_channel`).
- **Ph.4 (Mo 10–12) Construction integration + Year-1 release** = LODE+LEAP end-to-end scenario +
  FORGE certified records + the packaged benchmark (extends the M1 challenge platform: authored
  scenarios + rubric + baseline; reviewer runs on a clean machine in <1 hr).
- **Year 2** = mission assistant (suggestion queue), multi-sol planning, DART live feedback loop —
  the operator approves; they no longer initiate.

### 16.3b ARGUS — Articulated Rover Geometry for Unified State Estimation (added 2026-06-10)
The articulated vehicle-twin subsystem: documented rover geometry (chassis/wheels, bucket drums,
arm swing, the 8-camera rig, the LED work-light units) carried as ONE state consumed by every
estimator and the renderer alike. Implementation spine: stewie/specs/vehicle_twin.py +
ipex_specs.py camera/lighting truth + camera_rig.gd LIGHT_UNITS + the ArmState joint model (plan
T2.1). Plan of record: design/IPEX_TRUTH_INTEGRATION_PLAN_2026-06-10.md. Named in tribute to
Jadon Schuler, IPEx Project Manager and Principal Investigator, whose TRL-5 documentation
[SCHULER24] is the ground truth the subsystem traces to.

### 16.4 World-model strategy vs reconstruction-based world models (added 2026-06-10)
Assessment of the Martian World Model line of work (M3arsSynth + MarsGen, arXiv:2507.07978):
**we already own their OUTPUT side, with something stronger underneath.** Their world model is
reconstructed APPEARANCE (3DGS scenes, static); ours is a conserved PHYSICAL STATE -- terrain that
actually changes under excavation, with producer-exact poses and per-pixel geometric depth truth
(stewie/eval/depth_truth). What we lack is their INPUT side: real-mission stereo -> metric 3D
scenes. Their recipe for that is genuinely good (VGGT intrinsics + Metric3D depth + PnP; COLMAP
fails ~30% on planetary stereo, theirs hits 100% at 0.77 px reprojection).

Adoption, three phases in value order:
1. **LunarSynth data engine (first; modest cost):** curate real lunar stereo -- CE-3/CE-4 PCAM
   (CE-3 already in our detector training), Apollo surface pairs, LRO NAC -- through metric-aware
   reconstruction into REAL-imagery scenes imported via the existing dem_import path. Yields
   real-lunar DART evaluation scenes + planner demos on real terrain + a dataset paper. All real
   data.
2. **3DGS NVS layer** for the training sim (photoreal operator views) -- rides Year-1 Ph.2.
3. **Generative video ("MoonGen") -- DEFERRED** until 1-2 prove out + GPU access (their fine-tune
   used 8xA100).

**Non-negotiable rail: diffusion-generated frames are NEVER evidence.** Rehearsal, visualization,
and detector-training augmentation only -- the same fencing as the perception research track.
Their 2D-warp-error consistency metric is adopted for render/NVS QA regardless. Full note:
`design/LUNAR_WORLD_MODEL_NOTE_2026-06-10.md` (private workspace).

### 16.5 Control-room human-factors analysis (Carstens & Schuler, IEMS 2025) — UI/UX requirements
Source: Carstens, D.S. & Schuler, J.M. (2025), "Next Generation ISRU Pilot Excavator control room
and facility design," Proc. 31st IEMS, 73-88, doi:10.62704/10057/31312 — interviews with the 8
operators of the fall-2024 5-day mock IPEx mission (13-h shifts, 2-h rotations; roles: Primary/
Secondary Operator, Telemetry Desk, Sim-C). 50 recommendations across 11 Spradley domains. The
software-relevant findings map DIRECTLY onto STEWIE's operator UI:

| Operator finding (domain) | STEWIE UI requirement |
|---|---|
| Fonts illegible / "small font defeats at-a-glance reading" (D1) | **UI-1 Settings tab: font-size control** (global scale, persisted) |
| "Dark room kept people calm" + dim-lighting recommendation (D4/D8) | **UI-2 Settings tab: light/dark mode** (dark default for ops) |
| "Push a lot of buttons to get information," drill-down slow, cognitive overload (D1) | UI-3 One-action depth for critical info; macros/scripts for repeatable tasks |
| 6 camera grid "not pertinent" -> show 1-3 relevant; tedious full-screen/zoom/exposure (D1) | UI-4 Pertinent-camera selection + one-click fullscreen/zoom/exposure per feed |
| Image freshness uncertainty -> "green border, ~20 s yellow, >1 min red" (D1, P4 verbatim) | **UI-5 Staleness borders on every camera/telemetry tile (green/yellow/red)** |
| Warnings/errors/info messages wanted (D1) | UI-6 Alert rail (severity-typed, timestamped) |
| "One big display to know what the robot is doing" (D1) | UI-7 Big-board mode (single situational view; operator desk composes it) |
| Lap/cycle counter "easy to forget"; "status visual on where we are in the cycle" (D2) | UI-8 ConOps position widget (cycle/lap/phase, always visible) |
| Handover: "show instead of tell," pull up past noteworthy events, checklists (D6) | UI-9 The session debrief/summary IS this -- add noteworthy-event bookmarks + handover checklist export |
| "Structure on how to replay what just happened" when overloaded (D9) | UI-10 Replay scrubber over recorded legs (P22 visual replay; same data, operator-facing) |
| Sim-C tracked believed-vs-actual state (methodology) | UI-11 The operator/director divergence view = exactly our truth-denylisted session design — keep it load-bearing |

These are OPERATOR-DERIVED requirements from the real IPEx mock mission — the highest-authority
UI/UX source we hold. UI-1/UI-2 ship first (the Settings tab); UI-5 and UI-8 are small and
high-value; UI-4/UI-7/UI-10 fold into the operator-screen redesign (the role x workflow split).

### 16.5b UI/UX status pass + the 2026-06-10 audit folded in (the planner-voice audit,
### pane boundaries, OSS survey, and wireframe sprint — design/MISSION_PLANNER_UIUX_AUDIT,
### OSS_GIS_SURVEY, WIREFRAME_SPRINT)

Status of UI-1..11 (evidence = shipped commits + captures, per the V&V discipline):

| Req | Status 2026-06-10 |
|---|---|
| UI-1 font control | ✅ SHIPPED (Settings, persisted) |
| UI-2 light/dark | ✅ SHIPPED (dark ops default) |
| UI-3 one-action depth | 🟡 partial (popovers + workbench cards; macros ⬜) |
| UI-4 pertinent cameras | ⬜ (rides the operator-screen split, #68) |
| UI-5 staleness borders | ✅ SHIPPED (green/20s-yellow/60s-red sweeper) |
| UI-6 alert rail | ⬜ |
| UI-7 big-board mode | 🟡 (the control-room patterns adopted: status rail + sparklines; the single composed view ⬜) |
| UI-8 ConOps widget | ✅ SHIPPED (header chip) |
| UI-9 debrief + bookmarks | 🟡 (debrief ships; bookmarks/checklist export ⬜) |
| UI-10 replay scrubber | 🟡 (exec playback at 60×; an operator-facing scrubber ⬜) |
| UI-11 divergence view | ✅ load-bearing (truth-denylisted sessions) |

New requirements from the 2026-06-10 audit/wireframe (the audit's priority order):

| Req | Source | Requirement | Status |
|---|---|---|---|
| UI-12 | audit P1 | physics-fed layer legends + an on-map true-scale bar | ✅ SHIPPED (TDD: legend == code defaults) |
| UI-13 | audit P2 | drag-to-move features + the branded glyph set, one drawing language | ✅ SHIPPED |
| UI-14 | audit P3 | the queue as an attribute table + authoring undo | ⬜ |
| UI-15 | audit P4 | the pip as a true overview-locator (draggable view rectangle) — or removed | ⬜ |
| UI-16 | survey | TerriaJS workbench cards (per-layer legend/opacity/zoom/remove) + basemap stacking | ✅ SHIPPED |
| UI-17 | wireframe | REPORT = the mission dashboard (totals strip ✅; route hero + Gantt ⬜) | 🟡 |
| UI-18 | wireframe | the pane manager (user-created, resizable, persisted layouts) | ⬜ (resizable inset shipped as the slice) |
| UI-19 | pane spec | SYSTEM tab consolidation + pane boundaries (the one-line tests) | ✅ SHIPPED |
| UI-20 | Aaron | mobile: drawer cockpit, touch targets, phone-viewport verified | ✅ SHIPPED |
| UI-21 | edit mode | QGIS-style edit sessions: camera lock, draw tools, select/move/delete features | ✅ SHIPPED |

Open UI surface, in priority order: UI-14 (attribute table + undo), UI-6 (alert rail), UI-15
(overview-locator), UI-17 remainder (route hero + Gantt), UI-4/UI-7 (the operator-screen split,
rides #68), UI-18 (pane manager), UI-9/10 remainders.

### 16.6 Boundary note
The DART research track planning set (G1–G9 gates, separate honesty firewall) is NOT renamed or
re-scoped by STEWIE. Convergence: STEWIE P20 (ROS2 bridge + live drive loop) is the same engineering
object as the research track's persistent-runtime gap (G1.A4/A6) — one build advances both tracks;
the research track's evidence-mode rules still apply on its side.

### 16.7 On-rover autonomy stack — Autoware-derived architecture (added 2026-06-15)

**Intent, not a committed full build.** The rover needs a modular on-board autonomy stack with the same
*shape* Autoware established for terrestrial AVs (Sensing → Perception → Localization → Planning →
Control → Vehicle interface, as ROS2 nodes with frozen message contracts). STEWIE's subsystems already
mirror those layers, so the strategy is **adopt the architecture + the road-agnostic plumbing; reuse the
off-road-applicable components; build the lunar-specific autonomy ourselves** — never fork the whole
stack (Autoware's planning is road/lanelet2-centric; there are no lanes on the Moon, so that layer is
dead weight). The lunar planning/perception layer is both the product differentiator and the
dissertation-worthy novelty (ARGUS).

| Layer | Autoware fit | STEWIE plan | Maps to |
|---|---|---|---|
| ROS2 framework, node lifecycle, QoS, TF, message discipline | Excellent | **Adopt** | the P20 ROS2 bridge |
| Sensing drivers, time-sync | Good | **Adopt/adapt** | DART sensing |
| Localization (NDT scan-match, EKF/ESKF fusion) | Reusable reference | **Adapt** (we already do map-relative `register_to_dem` + ESKF, P15) | LEAP |
| Control (pure-pursuit / MPC tracking) | Mostly reusable | **Adapt** (skid-steer kinematics) | LEAP→vehicle |
| **Planning / behavior** | **Poor fit (lanelet2/road)** | **Build our own** — terrain-costmap, slip/sinkage/tip-aware, illumination/PSR-aware, excavation-aware | DART + LODE |

**The seam to STEWIE = AG-08.** The cockpit plans → rehearses → and at the Command stage lowers a verified
Plan IR / commands across the ROS2 bridge (NV-11 lowering / NV-12 live channel) under the SF-01 dead-man
interlock to this on-rover stack. STEWIE is the ground/planning/twin side; the autonomy stack is the
on-rover consumer of AG-08's output. Most of the on-rover stack is the **gated hardware future** — the
planning cockpit and sim drive-loop exist today; real on-rover perception/localization/control do not.

**License.** Modern Autoware (autowarefoundation) is **Apache-2.0** (permissive, patent grant). Adopting
the *architecture* (reimplementing layers) carries **no license obligation** (architecture/APIs are not
copyrightable). Vendoring Apache-2.0 *code* into the all-rights-reserved STEWIE is permitted (Apache-2.0
is not copyleft) provided we preserve license/copyright/`NOTICE`, state changes to modified files, and
avoid the Autoware trademark. **Caveat:** Autoware's transitive dependencies are mixed-license (BSD/GPL/…)
and must be swept before any code is vendored — tracked as task #124 (THIRD_PARTY.md). Reimplementation
(no vendored code) sidesteps this entirely and is the recommended default.

**ROS 2 distribution strategy (added 2026-06-15).** The ROS 2 framework layer targets two distinct
distributions for two purposes:
- **Ground / sim development → ROS 2 Jazzy** (the current P20 bridge target; the live `cmd_vel`→SF-01
  seam lands here, `ros2_bridge.py`). **ROS 2 Iron (Iron Irwini)** is the intermediate release and is an
  acceptable dev target where a tool requires it, but Jazzy is the default (newer, longer support than Iron,
  which is EOL'd; Humble/Jazzy are the LTS-class anchors).
- **Flight / on-rover → Space ROS.** [Space ROS](https://space.ros.org) is the NASA + Blue Origin + Open
  Robotics **spaceflight-hardened ROS 2** distribution — deterministic execution, safety-process/V&V
  rigor (toward NPR-7150-class software assurance), and a vetted subset — currently tracking ROS 2
  **Humble (LTS)**. The on-rover autonomy stack's flight build targets Space ROS; STEWIE's contracts and
  the bridge stay distribution-agnostic at the message/topic seam so the same Plan-IR lowering (NV-11/12,
  under AG-08 + SF-01) drives a Jazzy ground/sim node OR a Space ROS flight node. Honest: this is the
  **gated hardware future** — STEWIE develops against Jazzy today; Space ROS is the flight-grade migration
  target, not a current dependency.

## 17. Cockpit state + pending work (2026-06-10 session close)

A full live-debug day with Aaron driving. SHIPPED and verified (each capture-proofed,
commits adff7b6..e59cbde):

**Map truth chain**: SPICE is the default sun (NAIF kernels at $STEWIE_SPICE_KERNELS;
mean-motion fallback's 5.6° elevation error MEASURED into a dated artifact — it can mis-state
polar day/night); the Haworth tile drapes the globe via server-side reprojection to geographic
(IAU_2015:30135; the matplotlib-figure-as-drape and footprint-polygon-paint bugs found and
killed); coordinate truth verified (WGS84-shaped globe documented; scale bar now true body
meters); slope hierarchy verified (15° ConOps / 20° TESTED no-go / ~30° Gen-1 failure — 40°
indefensible); docs/map_reference.md carries the pipeline + in-stack source links.

**Cockpit**: workflow sidebar (7 independently collapsible groups, separators, drum-mark header,
Orbitron headers); Contents pane with TerriaJS-style WORKBENCH CARDS (in-card physics-fed
legends, opacity, zoom-to, remove); layer toggles ACTUALLY work (root cause: `let viewer` is not
`window.viewer` — every globe-path guard silently early-returned since written); toggles fly to
the work area; footprint click loads the granular set; cursor lat/lon + site-frame meters +
scale bar; per-body WORKSETS (no cross-body leakage); S-3 path-first authoring (goto orders,
auto-precedence, draw-path mode, drag-to-move, branded glyphs); S-4 object store (missions +
custom structures CRUD, mission notes); live plan→render reactivity (#33); API key via Settings
with actionable 401s; nginx no-cache (the stale-UI culprit).

**Physics**: berm re-hazard rule (later legs crossing executed cut/fill flag at the body's
repose angle); CG with loaded drums (mass-symmetric ballast is the maneuver target — the naive
counter-pose REFUTED by the model and test-pinned).

**Pending (the task queue, in priority order)**: #31 telemetry rail (channel chips +
sparklines); #40/#41 QGIS-style edit mode (camera lock + globe drawing tools through
/dem/site_xy); #32 no-terminal (Server-tab buttons for snapshot/backup/replicate/gate-run);
#26 info popovers; #25 remainder (live CG widget, perception-gated DockWithLander, Mars
enhanced datasets); #38 resizable panes; #39 event history (who/what/when audit trail); #30 the
FULL docs rewrite + astrophysics primer (agent fan-out, constants verified against code).
Hard-won lessons in force: guard on bare let bindings; verify USER click paths; setView not
flyTo; tile-verify every imagery product; a keyless browser's 401 confirms auth wiring.

### 17.1 Hot-loop addendum (2026-06-10 evening, f669336..e58686e + queue)

Shipped in the production-readiness rendering loop (each USER-path capture-proven):
- **#45 full-tile analysis layers** (slope/hazard/shadow/permanently-shadowed over the whole
  10 km tile; rock-hazard disclosure: surveyed crop only)
- **#46+#47 linear Plan methodology** (A where-are-we → B traverse → C work → D constraints →
  E solve → F review; solver wiring TDD-pinned nearest-vs-brute; Feasibility = sandbox)
- **#40/#41 edit mode** (camera-locked QGIS-style session; waypoint/keep-out/note via
  /dem/site_xy; footprint click = far-out gesture only) + **#48 plan-canvas hillshade underlay**
- **sub-collapsible A..F steps**; **#51 basemap stacking** (multi-imagery + per-layer opacity
  cards) + Site-before-Contents reorder (groups 1..7)
- **PSR root-cause** (44 s sweep → 384 px + disk cache + startup warm = 2.6 s; opacity persists)
  + acronym rule (Permanently Shadowed Region spelled out)
- **#26 popover pattern debut** on Feasibility (one key line + live ⓘ breakdown; open popovers
  refresh on change) + render-401 actionable + keyless auto-render skip
- **#31 telemetry rail** (channel chips + sparklines, exec-fed)

Open queue (tracked tasks): **#52 auth + operator whitelist** (mccardle.john@gmail.com,
aaron.w.storey80@gmail.com, storeyaw@clarkson.edu; Tailscale-header and email+key paths) — IN
PROGRESS; #32 no-terminal Server tab; #25 CG widget + docking + Mars sets; #38 panes; #39 event
history (rides the #52 identity); #49 Artemis-site DEM bundles (all candidates south-polar);
#50 wireframe sprint + 3D quantized-mesh terrain spike; #30 docs+primer fan-out; #26 remaining
surfaces (capabilities/validation verdicts).

## 18. Intent alignment — the scope ladder (John's framing via Aaron, 2026-06-10)

**Who is this for?** Four rungs, from horizon to ground truth. The PRD's product modes (§5) and
everything in §17 must serve these in priority order BOTTOM-UP — the concrete rung funds the
ambitious ones, never the reverse.

### Rung 4 (MOST CONCRETE — the product): the training environment / mission simulator
The rover is ordered to waypoints. A Docker container runs the ACTUAL rover motion planning and
simulated sensors. The TEAM observes only the data they would really receive — over the limited
telemetry and the latency of the real mission. The SIMULATION OPERATOR gets the 3rd-person view
and immediate state access. **Hard requirement: pluggable with the existing remote-control
system that operates the actual robot in the dirt pit** — the sim differs only in its training
affordances: fast-forward while driving, ignore battery, disable latency.

What exists today → this rung:
- the operator/sim-operator SPLIT is already real: training sessions (B3) run the closed loop
  server-side with the operator link showing only telemetry-delivered legs; link models
  (ideal / mission / comm_dropout) exist; the debrief view exists
- the Docker container IS the deployment (compose, healthz, beta_accept)
- RuntimeProcess is the frozen seam the motion planner + sensors speak through (Unix-socket
  JSON-lines; checkpoint/restore bit-exact); the ROS 2 bridge (rover_executive /cmd_vel teleop)
  is the dirt-pit-shaped interface
- waypoint ordering is the S-3 path-first authoring; EXEC fast-forward exists (60×); the
  third-person view is the Godot render path
GAPS (the real backlog for this rung):
1. **The pluggable RC contract** — a written interface spec matching the dirt-pit remote-control
   system's actual protocol (need that protocol from John); the sim must present the SAME
   surface, with the training toggles (fast-forward / battery-ignore / latency-off) as sim-side
   flags the operator cannot see.
2. Telemetry SHAPING to mission reality — bandwidth caps + latency injection per link model on
   EVERY operator-visible channel (today the link models gate legs; cameras/telemetry need the
   same budget).
3. Operator/sim-op AUTH separation (the #52 identity work makes this assignable: operator role
   vs director role).

### Rung 3: COLMAP world-map updates + the bandwidth-triage science loop
COLMAP (offline map generator) refines the rover's world map between sorties → better waypoint
navigation. Charging = ZERO connectivity; the mission ends with data stranded on the rover.
Opportunity: low-res first-pass data downlinked → suggest what to image at high-res next, or
where exploratory excavation should go.
Today's assets: the frame store + camera channels (8-cam rig with intrinsics) are COLMAP's
input shape; the map-channel reward (P6) is the "what's been observed" machinery; the conserved
twin holds as-built state. GAPS: the COLMAP ingest path (images → poses/points → DEM/feature
update), a downlink BUDGET model (bytes per sol), and the triage recommender (rank unimaged /
under-observed cells by science value — needs the team's actual objectives).

### Rung 2: faster-than-realtime forward simulation, compared outcomes, frequent resync
"COLMAP output + simulate movements faster than realtime with multiple possible inputs, compare
outcomes, resync often" — the world-model-flavored rung, honestly implementable as input
iteration over the existing terramechanics (the closed loop already runs candidate plans;
optimize_sequence already compares algorithms). GAP: a resync protocol (real telemetry ingested
→ state correction → re-simulate futures) — the research track-relevant piece.

### Rung 1 (HORIZON): "Claude Rove" — click-accept mission autonomy
A glimpse, not a deliverable: the rover will not run this code, and no one is running
--dangerously-skip-permissions on flight hardware. Keep as the north-star demo only.

### What today's 40+ tasks served (honest audit)
The GIS cockpit + truth chain (reprojection, half-pixel fix, SPICE sun, site DEMs, grid,
legends, edit mode, waypoint lifecycle) = the MISSION-AUTHORING FACE of rung 4 and the data
truth every rung needs. The auth/whitelist + event history = rung 4's role separation. The
telemetry rail + link sessions = rung 4's operator reality. Horizon-flavored excursions (Mars
enhanced basemaps, multi-body worksets) were cheap and stay, but the priority from here is the
rung-4 gap list above.

## 19. NASA-standards build-out (2026-06-10, Aaron: "build this out to NASA standards")

### 19.0 SF-01 safing/watchdog — DONE (2026-06-11)
The P0 safety requirement declared in §19.2 is BUILT: `stewie/bridge/rc_contract.py`
`SafingWatchdog` — a command-timeout dead-man switch that auto-issues SAFE to whatever backend is
plugged in (sim or real pit) when valid commands stop arriving, latching on the trip and resetting
on each heartbeat. [REQ:SF-01] test-cited; wired at /rc/telemetry (ticks on every poll). This
closes the architecture's "flagged-REQUIRED-and-missing, Phase-0/Week-4" node.

### 19.1 Where the §7 matrix actually stands (census, 2026-06-10)
112 identified requirements; **0 release-ready (all-required-columns D), 19 partial, 93 not
started.** By family (worst-column):

**Track tagging (architecture review rec 3, 2026-06-11):** the "0 release-ready" headline is read
correctly only WITH the track each family is on. **PRODUCT** families are on the rung-4 trainer
critical path (their gap is real product work); **DEFERRED** families are research-frontier or
externally-gated by design (their "N" rows are the roadmap, not debt) — do not read their N count
as product debt. **GATED** = blocked on an external input (IPEx geometry, John's pit protocol).

| Family | Scope | P | N | Track | Note |
|---|---|---|---|---|---|
| CT 7.1 | contracts/conserved authority | 3 | 4 | PRODUCT | the strongest family — the core IS the product |
| TW 7.2 | terrain/material/illumination | 4 | 6 | PRODUCT | TW-06 ephemeris sun = DONE in code (SPICE) — matrix stale, flip on evidence |
| VT 7.3 | vehicle/arms/drums/stability | 1 | 9 | GATED | the two-vehicle stance gap (VT-01/02/05); exact geometry awaits authoritative IPEx data |
| AM 7.4 | posture maneuvers (MEERKAT…) | 0 | 9 | GATED | all gated on authoritative IPEx geometry |
| CP 7.5 | perception/mapping/localization | 5 | 5 | PRODUCT | the G1/G2 evidence feeds this |
| SN 7.6 | solar-terrain navigation | 0 | 13 | DEFERRED | **the ARGUS research frontier** — open by design (the navigation-research contribution) |
| NV 7.7 | navigation/planning/recovery | 1 | 11 | PRODUCT | berm re-hazard + routing + docking/berm FSMs exist; recovery behaviors don't |
| PM 7.8 | construction mission planning | 1 | 11 | PRODUCT | the planner is rich but matrix-unverified (mostly flip-on-evidence) |
| EP 7.9 | energy/thermal/power/ops | 2 | 6 | PRODUCT | battery-honest timeline shipped; thermal ops partial |
| FL 7.10 | fleet | 0 | 7 | DEFERRED | MV1-7 exists; the RL multi-vehicle frontier + fleet reqs are research-scale |
| PO 7.11 | product/packaging/ops | 2 | 12 | PRODUCT | docs trilogy + fetcher land here; flip on evidence |

**Reading the census honestly:** the rung-4 trainer product (the §0 / §18 intent) is software-COMPLETE;
the matrix's "N" rows are dominated by the DEFERRED frontier (SN 15, FL 7) + the GATED families
(VT/AM 18, awaiting IPEx geometry / John's protocol) + PRODUCT rows that are flip-on-evidence (the
capability exists, the matrix column hasn't been moved on a citing test yet). "0 release-ready" means
no family has every column at D, NOT that the product doesn't work.

### 19.2 The standards frame (honest scoping)
- **Classification (NPR 7150.2 software classes):** STEWIE-as-simulator/training-tool is research/
  Class-E-like; the moment the pluggable RC contract (#66) lets it COMMAND the dirt-pit robot, the
  command path crosses into safety-relevant territory → that path (and only that path) needs
  Class-D-style rigor: independent review, hazard analysis, the SAFING/WATCHDOG requirement the
  architecture notes already flag as REQUIRED-and-missing (command-timeout halt). The watchdog is
  hereby **SF-01**, P0, owner = the #66 contract work.
- **Requirements traceability:** the §7 ID matrix becomes ENFORCED, not aspirational —
  `scripts/req_trace.py` (added with this section) parses every §7 requirement ID and scans the
  test suite for `[REQ:<ID>]` markers; a requirement may only hold `V=D` if at least one test
  cites it. CI runs the tracer; the report is the traceability matrix.
- **V&V evidence discipline:** the I/X/V/Q columns only move on artifacts (tests, dated
  validation JSONs, captures) — the same rule the G1/G2 gates already enforce. No column flips by
  prose.
- **Coding standard:** the conserved core already lives Power-of-10-adjacent (no recursion-heavy
  paths, bounded loops, asserts banned in production contracts per CT-06); adopt explicitly for
  stewie/physics + stewie/twin: add ruff rules + a documented exception list rather than a
  rewrite.
- **Configuration management:** already strong (frozen byte-identical baseline, dated artifacts,
  CI gates, the event audit trail, journaled twin) — document it as the CM plan rather than
  rebuild it.

### 19.3 The build-out order (what "to NASA standards" means next)
1. **SF-01 safing/watchdog** + the #66 RC contract (the class boundary).
2. `req_trace.py` in CI + seed `[REQ:]` markers on the requirements that ALREADY have tests
   (CT/TW/CP families first) — turn the 19 P's into evidence-backed D's or honest N's.
3. Flip stale matrix rows on existing evidence (TW-06 SPICE; PO docs/fetcher; EP battery).
4. Then the families in mission order: VT/AM (needs IPEx geometry from John), NV recovery,
   SN as the research track track.

### 18.1 Rung status (2026-06-11)
Rung 4: ALL THREE software gaps CLOSED. Gap 2 (telemetry shaping — downlink latency first-class,
per-sol ledger + stranded accounting) and gap 3 (director/operator roles; truth views + admin
director-gated) shipped earlier. **Gap 1 (the pluggable RC contract + SF-01 watchdog) is now DONE
too** — it was never actually blocked: John's frozen `ccsds_ros_nav/CONTRACT.md` §2/§3 already
specifies the dirt-pit interface (GoTo/Safe/SetSim + Pose/Leg/Img over CCSDS). `stewie/bridge/
rc_contract.py` is the STEWIE adapter: the RCBackend ABC (pluggable sim/pit), `commands_from_plan`
(a plan → a reusable GoTo command tape, "plan once command many" — /plan/commands + a cockpit
download), and **SF-01 the SafingWatchdog** (command-timeout dead-man auto-SAFE). What remains for
a REAL pit is the wire-level UDP/ROS binding to John's package + a PitBackend when the pit's link
details land — an integration, not a design unknown. Rung 3: designed (COLMAP_TRIAGE_DESIGN); the budget ledger shipped; ingest
awaits the director-side COLMAP container; triage weights await science objectives. Rung 2: in
progress (#70). UI: 16.5b updated through UI-15; UI-17 remainder + UI-18 open.

## 20. Full-stack audit + production-readiness (2026-06-11)

An 8-dimension line-by-line audit (security, concurrency, twin integrity, vehicle twin, physics,
registries, frontend↔backend wiring, comments), every high-severity finding adversarially
verified (0 refuted of 5). 44 confirmed findings. Disposition:

### 20.1 Fixed (this session)
| ID | Sev | Finding | Family | Fix (commit) |
|---|---|---|---|---|
| SEC-1 | CRIT | GET /config leaked the plaintext API key (reproduced live) | CT/PO | source-redacted describe()+endpoint, TDD (414df2e) |
| RC-01 | CRIT | TwinStore journal append unlocked race -> chain corruption | CT-03 | per-store RLock + torn-line recovery, 24-thread TDD (414df2e) |
| RC-02 | HIGH | _TWIN lazy singleton double-init race | CT | double-checked lock (414df2e) |
| RC-03 | HIGH | globe cache non-atomic .npy+.json write | PO | .part -> os.replace, JSON commit-marker last (414df2e) |
| TWIN-01 | MED | torn FINAL journal line aborted the whole restore | CT-03 | recover-past-tail (414df2e) |
| SEC-2 | MED | GET /events disclosed the operator audit trail | PO | director-gated (c819b40) |

### 20.2 Verified FALSE POSITIVE
| ID | Finding | Why it's not real |
|---|---|---|
| PHYS-01 | "shipped slip uses Earth-fit Bekker on the Moon" | each body's Bekker is its SOURCED value; the Moon's k_phi 820000 IS the NASA LTV lunar measurement (already low-g). A runtime lyasko reduction would DOUBLE-count (the known FIX-6). Caught by test_bodies; reverted. Low-g physics is correct in the shipped path. |

### 20.3 Confirmed open (tasked / tracked) — maps to the §7 matrix gaps
| ID | Sev | Finding | Family | Disposition |
|---|---|---|---|---|
| VT4-01 | MED | /twin/cg discards the fore/aft CG shift (dx) | VT-05/06 | the posture model is 3D-in-Z, 2D-fixed-rect in XY; posture_a3.py has the fore/aft + shrinking polygon but isn't wired. Real physics-incompleteness in an ADVISORY widget. -> a vehicle-twin task |
| PHYS-02 | MED | cg_offset_m drum-load term absolute, not relative-to-stow | VT-05 | refine with VT4-01 |
| REG-01 | MED | imported sites (Shackleton, Nobile) unreachable from the PLANNER | PM/TW | the globe shows them; the planner still hard-targets Haworth. Real functional gap -> task |
| REG-02 | MED | vehicle choice only changes drum capacity in the plan | VT-02 | drive/dig/battery/mass not threaded through the planner per-vehicle |
| TWIN-02 | MED | io_fields float32 save not mass-exact + omits drum_inventory | CT-03 | the RUNTIME checkpoint IS exact; only the scene-export path drifts ~6e-10 -> document/fix |
| SEC-3 | MED | body-size cap trusts client Content-Length | CT | hardening |
| RC-04/05 | MED | _METRICS + object-store writes non-atomic | PO | observability/store hardening |
| D8-01 | LOW | stale `terrain_authority.*` run-instructions in ~7 docstrings | PO | comment sweep |

### 20.4 Production-readiness assessment (honest)
STEWIE has TWO production targets with very different bars (PRD §18 ladder):

- **As the TRAINING ENVIRONMENT / MISSION SIMULATOR (rung 4, the product):** **~75%.** The
  authoring cockpit, conserved twin, link/latency shaping, operator/director roles, audit trail,
  and no-terminal ops are real and tested; the two security criticals are now closed. The
  remaining 25% is almost entirely the **#66 pluggable RC contract + SF-01 watchdog** (blocked on
  John's protocol) plus the medium hardening list above. NOT a research demo — a usable trainer
  once the RC seam lands.
- **As FLIGHT-RELEVANT autonomy / the ARGUS estimator (the research track):** **~30%, by design.**
  The SN solar-terrain-navigation family is 13/13 open; the pose-graph that fuses sun/shadow/DEM
  factors over mutating terrain is scaffolded (shadow_predict, register_to_dem, the re-hazard,
  the conserved mutable twin) but NOT integrated. This is the protected contribution, correctly
  unbuilt at proposal stage.

**Quantitatively against the §7 matrix:** 112 requirements, 0 were release-ready (all-D) at the
§19.1 census; after the audit fixes + the traceability seeding, the CT (contracts) family is the
closest to release and the security posture moved from "one remote-compromise critical" to
"no known criticals." The honest headline: **the simulator product is ~75% and gated on one
external dependency (the RC protocol); the flight-autonomy story is early and protected.**

## 21. Architecture review + structural remediation (2026-06-11)

A full architecture review (pattern, layering, coupling/complexity hotspots, PRD-vs-intent) ran
against the live tree (~62k LOC, 153 core modules, 169 test files, 61 endpoints). Verdict: the
system is in unusually good shape for a research-stage codebase — a PURE conserved kernel
(`stewie/physics` + `stewie/twin` have zero upward imports; mass-exactness + the hash-chained
journal are production guards, not asserts), four enforced CI gates (pyflakes, mypy,
requirements-traceability, Power-of-10), and documented contract seams. Against INTENT (the rung-4
trainer product) the system is software-complete; against the full §7 matrix it is ~18%
partial/done, but that delta is the DEFERRED/GATED frontier (§19.1 track tags), not architectural
debt. Findings + remediation (ranked):

### 21.1 Structural defects to remediate (tracked)
| ID | Sev | Finding (file:line) | Remediation |
|---|---|---|---|
| ARCH-1 | MED | **`lode`↔`dart` circular dependency**: `dart/hazard_map.py:22` `from lode import rock_costs`, while `lode/actions.py` + `lode/resync.py` import `dart`. Perception (lower layer) reaches up into planning. | Move `rock_costs` to `stewie/specs` (the shared kernel both already depend on) — it is cost DATA, not planning logic. One move removes the only layering violation. |
| ARCH-2 | MED | **`lode/mission_planner.py` god-module** (2110 lines / 78 functions): solver + report + Plan-IR + math worksheet + command-tape + site loading all in one file; the `lode` coupling magnet. | Split into `planner_core` (the `plan`/`_build_trips`/`PlanResult` solver) and `planner_views` (report/PDF, `plan_math`, `commands_from_plan`) — formalizes the RB-03 "every output is a VIEW over the one artifact" principle the PRD already states. Well-tested, so this is decomposition, not a rewrite. |
| ARCH-3 | LOW | **`server.py` handler sprawl**: 61 endpoints in 1261 lines — the safety-relevant auth + RC command path sits beside everything else. | Split into routers by concern (auth/session/plan/twin/rc/admin); isolate the RC command path (the Class-boundary surface, §19.2) for focused review. |
| ARCH-4 | LOW | **Cockpit is a single 2855-line inline `index.html`** — no module boundary; the largest single-file complexity in the repo. | Extract the cockpit JS into modules behind a small build/bundling step; keep the `node --check` gate. Lower priority — it is verified per-change and outward behavior is covered by the live UI evals. |

### 21.2 Non-issues confirmed (do NOT "fix")
- The high fan-in of `stewie/specs` (×96) and `stewie/physics` (×74) is a shared KERNEL, not a god
  object — expected and healthy for a conserved-core design.
- "0 release-ready" in §7 is NOT product debt — see the §19.1 track tags. The rung-4 product is
  complete; the open rows are the deferred research frontier + externally-gated families.

### 21.3 Sequencing
ARCH-1 first (smallest, removes the cycle), then ARCH-2 (the RB-03-aligned split), then ARCH-3
(routers — do this WITH the SF-01/#66 hardening since it touches the same command path), ARCH-4 last
(or never, if the build step is judged not worth it). None block the product; all improve
reviewability ahead of a NASA-standards external review.

## 22. Completion audit + the navigation-track bridge (2026-06-12 — read with §0)

A four-agent fan-out (server API, estimator reachability, frontend cockpit, unfinished-marker
sweep) mapped the whole monorepo against intent; findings verified and folded in below. The shape:
STEWIE is two tracks.
The excavation planner and trainer (LODE planning, the conserved physics, the operator/trainer
sessions) is wired end to end, backend to a 71-endpoint API to a full cockpit. The navigation
research, the ARGUS estimator that is the navigation-research core, is built and validated as a library
of eighteen modules but has no HTTP endpoint and no cockpit presence. Completing the system is
mostly bridging the second track into the live one.

### 22.1 The three findings

**(1) Not in the frontend (backend exists, no UI).** The cockpit (`stewie/server/index.html`) is
entirely the planning product. Absent: the whole localization stack (no pose-graph estimate, no
trajectory-versus-truth, no drift bounding, no shadow-yaw or articulation-parallax fix, no
relocalization action, no covariance ellipse); the integrated SLAM result, the leave-one-out
attribution, the shared-testbed head-to-head; the measured-edge sigma and cross-dataset
generalization; the depth pass and photometric render-pair (the Perception tab shows only the
planner before/after, not the parallax measurement); the eval-gate results (a validate button with
no readout) and the evidence-notebook set.

**(2) Not wired on the backend.** Eighteen estimator modules have no HTTP endpoint (integrated_slam,
articulated_parallax, articulated_shadow, pose_graph_se2, shadow_vectors, shadow_edge_sigma,
localization, mapping, camera_select, comparison, depth_truth, annotate, posture_select,
posture_coverage): reachable only from tests and notebooks. `articulation_bridge` is not on the
`/render` path (it produces the planner before/after, not the two-posture parallax capture).
Genuinely unimplemented: the worksite controller seam (the one stub, the RL/autonomy that drives
the build is deferred); multi-vehicle cross-precedence (v1, not yet coordinated); berm-holds-slope
firming (the G5 gap); the Lyasko one-g to one-sixth-g sinkage correction (deferred to the euclid
oracle); DEM imports for several Artemis sites (`bundle_dir` is None); the map-uncertainty cost
coefficient (placeholder until the coverage field feeds it). FORGE is an empty package (its physics
code lives in `stewie/physics`). Gated by design, not a gap: sinter (IPEx carries no sinter tool).

**(3) What is left.** P1 wire the navigation half into the system; P2 finish the backend build
items; P3 surface the evidence. External, not buildable here: a lunar-surface rover traverse with
shadows and pose truth; the SN-07 LED-illumination hardware.

### 22.2 UI/UX status — live cockpit visibility pass (screenshots, 2026-06-12)

Captured headless on the live server (`validation/ui_2026-06-12/`, playwright + chromium, no page
errors). Each view read against intent:

| View (tab) | Screenshot | What it shows today | Gap vs the ARGUS nav track |
|---|---|---|---|
| Plan (LODE) | `00_initial.png`, `01_plan.png` | Cesium Haworth globe; sidebar 1 Site / 2 Contents / 3 Fleet / 4 Feasibility / 5 Plan A-F / 6 Catalog / 7 Telemetry. The full authoring product. | None — the complete planning surface. |
| Perception (DART) | `02_perception.png` | "Godot PLAN → RENDER", before/after sensor frame. Empty-state copy: a live SLAM map is "the open map-channel work, not a faked feed." | No parallax measurement, no depth pass, no photometric render-pair, no shadow-vector overlay. P1 (parallax capture) + P3 (evidence). |
| Metrics (LEAP) | `03_metrics.png` | Live CG and tip-margin stability widget; an execution top-down replay ("a deterministic forecast of the plan, not live rover telemetry"). | By its name (Localization, Estimation and Analysis) it should host the estimator; it shows none — no pose-graph, no trajectory-versus-truth, no covariance. P1. |
| Report (FORGE) | `04_report.png` | Mission-control PDF surface (empty until a plan runs). The planner product. | None for the planner; the comparison/evidence packet (P3) can surface here. |
| System | `05_system.png` | VALIDATION / API / SERVER / CONFIG sub-panes; Twin snapshot, Retention, Replicate-backup, and a "Validate gates" button with no readout; health + metrics JSON. The `by_route` census confirms the cockpit never calls `/localize`, `/slam`, `/sense`, or `/compare`. | Gate results have no readout (P3); the estimator endpoints do not exist (P1). |
| Settings | `06_⚙.png` | Configuration pane. | None. |

The finding the screenshots make concrete: every empty-state placeholder narrates a planner
function, and none of the six tabs references the navigation/estimation track. The cockpit is the
planning-and-trainer product, complete; the ARGUS estimator is invisible to it. The work
tied into UI/UX is therefore P1 (a Navigation/Estimation view plus the endpoints behind it) and P3
(the evidence figures into Perception, System, and Report).

### 22.3 TDD-sequenced forward plan

Each slice is bounded, gate-byte-identical, and lands with a citing `[REQ:]` test plus (where it is
navigation-research evidence) a baseline-comparing notebook. The matrix rows each slice promotes are named.

**P1 — wire the navigation half (#106, #96, #97) — ✅ DONE 2026-06-14.** The ARGUS estimator is now
reachable from the live system and visible in the cockpit: P1.1 `/localize` (heading-free fix +
covariance; truth-field denylist; 5 citing tests), P1.2 `/slam` + `/slam/compare` (trajectory + ATE +
LOO over a named real segment; 503 when the dataset is absent; 5 tests), P1.3 `/render/parallax` +
`stewie/godot/articulation_bridge.py` (two-posture parallax capture → shadow-tip pixels + exact dh),
P1.4 the cockpit Navigation/Estimation view (pose-graph estimate vs dead reckoning, covariance,
perception-gated relocalize #96/#97) — live-verified headless-Chrome (`scripts/ui_eval.py`,
`validation/ui_2026-06-14_nav/`: navview renders, gate `ARMED` when σ>tolerance, no page errors). The
table below is the original slice plan.


| # | Slice | Citing test (`[REQ:]`) | Promotes |
|---|---|---|---|
| P1.1 | `/localize` endpoint: `articulation_localize` returns a heading-free fix + covariance from a posture-pair shadow-tip parallax. | `test_server_localize` (socket POST → fix + covariance; truth-field denylist holds) | PM-06 I, PO-10 |
| P1.2 | `/slam` endpoint: `run_integrated_slam` returns trajectory, absolute trajectory error, and the leave-one-out attribution over a named real segment. | `test_server_slam` (POST → trajectory + ATE + LOO; matches the frozen keystone artifact) | PM-06 V, NV-10 |
| P1.3 | `articulation_bridge` on `/render`: a two-posture parallax capture (not the planner before/after), returning the per-frame shadow-tip pixels + the exact `dh`. | `test_render_parallax_capture` | SN-10 wiring (I→V) |
| P1.4 | Cockpit Navigation/Estimation view: pose-graph estimate versus dead reckoning, the shrinking covariance ellipse, a perception-gated relocalize action (#97), and planner relocalization stops (#96). Live-verify headless Chrome + a `ui_eval` screenshot. | `test_ui_eval_nav_view` (the view renders the estimate + ellipse; relocalize is perception-gated) | PO-12, PO-10, SN-10 tie-ins B/C |

**P2 — finish the genuinely-unimplemented backend items (#107).** Buildable now: REG-01 DEM site
imports (make the Shackleton/Nobile bundles plannable), FORGE (point its `__init__` at
`stewie/physics` or remove the empty package), berm-holds-slope firming (CP-06 acceptance), the
map-uncertainty cost coefficient (feed it from the coverage field), multi-vehicle cross-precedence
(FL-02/FL-04). Externally gated, kept honest: the worksite controller seam (needs John's pit wire /
the RC transport), the Lyasko one-sixth-g correction (the euclid PyChrono oracle, FIX-2). Each
buildable item is one bounded slice with a citing test; the gated items stay N until their external
dependency arrives.

**P3 — surface the evidence (#108).** Put the comparison head-to-head (notebook stages 17-19, 28),
the cross-dataset generalization (stage 26), and the photometric render-pair + depth pass (stages
23-24) into the System and Perception tabs; give the "Validate gates" button a G1/G2 readout; link
the evidence-notebook set. A `/compare` endpoint serves the shared-testbed result the System tab
renders. These are product-story and review-surface items, not new measurement.

**External, not buildable here.** A lunar-surface rover traverse carrying both shadows and pose
truth (no such public dataset exists); the SN-07 LED-illumination hardware (the one row that stays N
honestly).

### 22.4 Sequence rationale

P1 first and most: it is the only item that changes what the system IS rather than what it shows,
and it is the two tie-ins already on the board (#96, #97) plus the two endpoints that make the
eighteen library modules reachable from the live system. P3 is cheap and high-value for the review
surface but adds no capability, so it can interleave with P1.4. P2 is a mix of small now-buildable
closes and honestly-gated externals; it blocks neither P1 nor P3. The frozen 2026-06-07 gate JSON is
untouched by all of this: every slice reproduces it byte-identically, and a gate flips only via a
new dated artifact.

## 23. Architectural/security/numerical audit (2026-06-13) — production-readiness remediation

A read-only architectural + security + numerical + terramechanics audit (4 critical, 20 high, 24
medium, 10 low; against commit `9a592cc`) found the core theme: several product paths bypass or
disagree with the authoritative models they claim to represent ("recomputing alternate versions of
reality"). It re-prioritizes the production-readiness work AHEAD of new capability. Tracked as tasks
**#110-#116**; one finding (M-34, a SPICE call left outside the serialization lock) is already fixed.

**Phase 0 — stop unsafe operation (production blockers, do first):**
- **C-01 (#110)** the published Compose deployment is auth-fail-open by default (`require_auth`
  returns director-equivalent `dev-open` when no key is set; `deploy/compose.yml` defaults it empty
  on port 8000). Production must fail closed.
- **C-02 (#111)** conserved-state mutations (`cut_to_inventory`/`dump_from_inventory`/
  `set_height_via_mass`/`drum_pass`) accept negative/non-finite values and reverse mass flow. Validate
  every authority-mutation boundary.
- **C-03 (#112)** the two shadow engines use incompatible azimuth→grid mappings (90° rotation between
  `shadow_predict.horizon_clip` and `illumination.cast_shadow_mask`). **Gates the SN/nav track** —
  shadow-derived localization may be rotated. One frame contract + cross-module tests first.
- **C-04 (#113)** mission transit can drive battery SoC negative and still return an executable plan.
  Reserve-aware edges; suppress Plan IR on infeasibility.

**Phase 1 — one source of truth (#114) — ✅ DONE 2026-06-13 (11/11 HIGH, all gated, gate byte-identical):**
one `PlanningContext` from the selected vehicle threaded through energy/mass/range/slip/report/acceptance
(H-01, `plan_context`; rassor2 mass/drum now drive the plan); route inter-site legs once and share the
routed geometry across optimizer/timeline/report so sequencing scores what the Plan IR executes (H-02,
`_make_routes`); acceptance honestly scoped, not over-claimed full validation (H-07, the self-balanced
trip decomposition makes IR re-execution materially identical); compaction is timestep/pass-invariant
(H-09, convergent target density); skid-steer propagated to the runtime drive loop (H-10); out-of-regime
microgravity body gate (H-12); fail-closed routing — off-DEM footprint reject (H-08), unreachable-leg
fail-closed at /plan (H-03), no diagonal corner-cut (H-04), adaptive window vs the 20 m bbox margin
(H-05), cumulative-ascent haul lift (H-06).

**Phase 2 — harden estimation + persistence (#115) — ✅ DONE 2026-06-13 (every slice TDD, gate
byte-identical). Touched the §22 nav track:** estimation — reject impossible parallax (H-13, the
`/localize` + render-fix primitives), require ≥3 landmarks or flag the 2-landmark mirror ambiguity
(H-14, `/localize` allows 2), pose-graph observability/anchor check (H-15, no ridge covariance), real
shadow map-match not centroid (H-16), per-frame camera pose in mapping (H-17), keep anisotropic
parallax covariance (H-30), one solar authority (H-18). Persistence/socket — durable-before-commit +
atomic verify-before-mutate twin journal (H-20/M-12, `bb6aa94`), atomic + content-checksummed twin
snapshots (M-11, `1bac883`), Unix-socket hardening = bounded readline + finite/bounded twist +
0o600 socket + finite set_thermal (M-03/04/05, `f471648`), session TTL + bounded store (M-09,
`60f0406`). Adjacent finding tracked for its own slice: arbitrary-path checkpoint/restore traversal
(#120).

**Phase 3 — scale + maintain (#116) — IN PROGRESS:** sparse graph factorization, swept/compiled
illumination, materialized twin state, split the server/planner god modules, pin deps + CI action
SHAs, green the lint gate (L-01 broken `viz/*` imports), reduce mypy exclusions, quarantine
archive/public copies + the committed Godot binary.

*Low-blast cleanup DONE 2026-06-14 (each verified, frozen G1/G2 gate byte-identical, no Claude
trailer): L-01 ruff-F lint gate greened — fixed 3 botched `viz/*` imports (`from the conserved
authority import constants as K` -> `from stewie.specs import constants as K`) + a dead dart import
(`8dce51d`); mypy ratchet tightened — un-excluded `lode.self_optimizing`, the remaining
18-module/90-error typing debt tracked as #121 (`f8f0c8c`); CI action SHAs pinned across ci/pages/
publish workflows + a publish-lint typo fixed (`2966da5`); Power-of-10 complexity gate greened —
`sandpile.deposit` had been complexity 11 since the Phase-0 C-02 fix, extracted `_deposit_target_cells`
(`f5baa06`). The full CI gate now passes locally end to end (req_trace + Power-of-10 + ruff-F + mypy +
pytest/coverage). STILL OPEN (high-blast, each its own reviewed slice): the server/planner god-module
split, materialized twin state, sparse graph factorization, swept/compiled illumination, and the
archive/public-copy + committed-Godot-binary quarantine.*

Sequencing (Aaron, 2026-06-13): **the next session STARTS with audit Phase 0** — the four criticals
**#110 C-01 → #111 C-02 → #112 C-03 → #113 C-04**, in order, before option 1/2b or any new
capability. C-03 (the 90° shadow-azimuth disagreement) is a hard prerequisite for further nav work.
Then the Phase 2 nav-primitive hardening rides alongside the option-1 rendered-DEM traverse (it makes
the measured nav fixes honest under bad geometry), then Phase 1, then Phase 3. The honesty rules are
unchanged: every fix lands TDD, gate byte-identical, no synthetic data.

## 24. LanderPi / IPEx capability diff + convergence plan (2026-06-15)

A terrestrial nav testbed (LanderPi-class: ROS2 + Nav2 + SLAM-Toolbox/RTAB-Map + AMCL + TEB/DWA on
real hardware) covers ~70% of the autonomy *software* stack but only ~30% of the IPEx *mission* stack
because it has zero excavation/terramechanics. **STEWIE is the inverse:** it owns the mission-physics
"hard 30%" a terrestrial robot structurally cannot, and is weaker exactly where the testbed is strong
(real-hardware ROS2/perception/SLAM). They are **complementary**, not competing — prototype the
autonomy-software layer on the testbed, validate the excavation/terramechanics/illumination layer in
STEWIE, converge on IPEx.

### 24.1 Capability map — STEWIE actual (grounded)

| Domain | testbed | STEWIE actual | Evidence / PRD |
|---|---|---|---|
| ROS2 infra | 100% | ~50% — RC contract + SF-01 watchdog + CCSDS PitBackend + telemetry; live rclpy node bridge gated | `bridge/rc_contract.py`, `pit_backend.py`; P20 |
| Navigation | 90% | ~50% — routing, plan-view authoring, keep-outs, negative-obstacle, multi-goal; local trajectory planner N | NV-01 P, NV-03/04 N |
| SLAM/localization | 90% | ~60% — map-relative register-to-DEM, SE(2) pose graph, loop closure, Shadow-SLAM shadow-σ calib, PSR supervisor; Katwijk ATE 3.35 m; full SLAM-from-scratch N | `dart/pose_graph_se2.py`, `loop_closure.py`, `shadow_sigma_calibration.py` |
| Perception | 80% | ~40% — rock taxonomy, obstacle map, camera rig/select, dock pose; dense stereo→depth→cloud gated | PM-13..16 N |
| Mission planning | 70% | ~85% — planner, Plan IR, scheduler, `plan_multi`, challenge platform | CP-01..10 |
| **Excavation** | **5%** | **~70%** — mass-conserving cut/fill, deposit_field, drum-fill mass sensing (ICE-RASSOR FDC), IPEx dig energy; Tier-3 force-accurate drum gated | `physics/column_state.py`, `rassor_mass_model.py` |
| **Terramechanics** | **0%** | **~85%** — Bekker pressure-sinkage, slip ladder (Janosi/drawbar/entrapment/runaway), Lyasko ⅙g, tip-over stability; quantitative oracle calib deferred | `physics/terramechanics.py`, `slip.py`, `stability.py` |
| Lunar ops | 10% | ~40% — solar/shadow/PSR illumination; thermal partial; dust render-only; multi-day clock N | TW-06 D, EP-04/07 N |

**STEWIE already holds 5 of the 6 "missing" areas** the analysis flags as the differentiator (excavation
physics, regolith flow, terramechanics, wheel-slip, illumination/shadow); AutoDig is partial (dig physics
+ energy yes, adaptive control loop no), and Shadow-SLAM is real scaffolding, not just a concept.

### 24.2 Diff — three buckets
- **STEWIE owns (testbed can't):** Bekker terramechanics, slip/entrapment, mass-conserving excavation,
  drum-fill sensing, IPEx dig energy, solar/shadow/PSR, the conserved digital twin, the planner +
  multi-vehicle scheduler, Shadow-SLAM + ARGUS articulation localization (the dissertation novelty).
- **Testbed complements (STEWIE's real gaps):** a physical robot running ROS2/Nav2/RTAB-Map/AMCL on real
  sensors — the proving ground for the autonomy software STEWIE only simulates.
- **Gaps in both (the build list):** live ROS2-Jazzy node bridge, dense stereo→depth producer, adaptive
  AutoDig, Tier-3 force-accurate drum (Chrono GPU-DEM), full fleet coordination, dust/thermal/multi-day.

### 24.3 Convergence plan (Phases A–E)
- **A. Autonomy seam** — live ROS2-Jazzy bridge (RC contract + PitBackend speak rclpy/cmd_vel); adopt the
  Autoware architecture (§16.7). Where testbed ROS2/Nav2/SLAM prototyping transfers in. (P20, AG-08 seam.)
- **B. Perception producer** — render→depth→point-cloud, unblocking PM-13..16 + dense Shadow-SLAM.
- **C. Multi-vehicle coordination** — extend `plan_multi` (allocation + space-time conflict, built) into
  fleet coordination: shared chargers/pits/corridors as reservable resources, cross-vehicle precedence,
  per-rover belief/health, exact-oracle validation; Autoware multi-robot conventions inform interfaces.
  (FL-03..07.) Progress: the shared CHARGER is now a one-server FCFS queue (FL-03 partial) — overlapping
  recharges serialise and the makespan reflects the contention; the exact 2-rover oracle (FL-06,
  `plan_multi_oracle`) now lower-bounds + validates the heuristic. pit/dump/vantage/corridor + per-rover
  belief (FL-04) remain.
- **D. Excavation depth** — Tier-3 force-accurate drum (Chrono GPU-DEM) + adaptive AutoDig control. (CP-03, P7.)
- **E. ARGUS contribution** — close the Shadow-SLAM + articulation-parallax loop (scaffolds exist) →
  GPS-independent PSR localization + excavation-progress tracking; the publishable contribution. (SN-*.)

Honest restatement: the "~70% software / ~35% mission" figure is the *testbed's*. STEWIE is the mirror —
~55% autonomy-software (ROS2/perception/real-SLAM is the gap), ~70% mission-physics (excavation/
terramechanics/illumination is the strength). Fastest path to an IPEx-relevant twin = **Phase A** (connect
the mission-physics twin to a testbed/Autoware-style ROS2 autonomy layer). All phases land TDD, gate
byte-identical, no synthetic data.

## 25. Full-stack onboard autonomy execution plan (2026-06-15)

This is the optimized sequence for the next autonomy build. It is deliberately ordered from
contracts -> backend -> frontend -> autonomy loops -> model integration -> hardening. Each phase is
atomic: it may touch several files, but it must ship one coherent contract or capability, with tests,
traceability, security review, and performance budget before the next phase depends on it.

### 25.1 Current codebase assessment baseline

Current front-end surface:
- `stewie/server/index.html` and `stewie/server/web/assets/cockpit.js` provide the cockpit shell,
  static tabs, plan authoring, GIS/map layers, Navigation/Estimation, Perception, Metrics, Report,
  System, Admin, and Settings.
- Navigation/Estimation already calls the `/slam`, `/slam/compare`, and `/localize/render` endpoints
  and renders trajectory/covariance evidence, but Fleet, Models, Construction Skills, and Security
  are not yet first-class work areas.
- The front end is still effectively one large cockpit script; the restructure must split by product
  work area without breaking the existing no-inline-script CSP and mobile hardening.

Current backend surface:
- `stewie/server/routers/plan.py` owns planning, math, command, and raster-layer paths.
- `stewie/server/routers/perception.py` owns compare, localize, SLAM, render, structure, and sensing
  paths, including the current ARGUS/render-pair entry points.
- `stewie/server/routers/twin.py`, `admin_ops.py`, `missions.py`, `structures.py`, `config.py`,
  `layers.py`, `auth.py`, `invites.py`, `operators_admin.py`, `health.py`, and related routers cover
  world/twin state, mission persistence, access, layers, admin, health, and operator state.
- Domain support already exists for conserved terrain, Bekker/slip/stability, PlanResult-like planning,
  route planning, fleet allocation/reservation primitives, solar geometry, articulated shadow/parallax,
  pose graphs, training scripts, and model experimentation. The gap is not absence of code; it is that
  the surfaces are not yet unified by one typed onboard-autonomy contract and one cockpit workflow.

### 25.2 Build sequence

**Phase 0 — inventory and freeze the contract boundary.**
Exit: FS-01 and FS-02 are current. Produce a module map for touched frontend/backend/domain code,
define the typed contract spine, and decide which current routes remain public, which become internal,
and which need role-gated writes. Define the correlation-ID and event-ledger fields at this phase.
Do not start new UI work before the contracts and logging envelope exist.

**Phase 1 — backend contract APIs.**
Exit: typed API fixtures exist for world, fleet, navigation, ephemerides, ARGUS, model artifacts, and
construction skills. Add schema validation at route boundaries and expose examples that browser tests
can load. Existing route handlers may delegate to current modules, but their payloads must match the
contract spine. Every route emits structured decision/error/latency logs with redaction and truth-firewall
checks.

**Phase 2 — front-end contract layer and cockpit restructuring.**
Exit: the cockpit has first-class work areas for Plan, Fleet, Navigation/ARGUS, Perception/Imagery,
Construction, Models, Security/System, and Reports on desktop and mobile. Build this in sublayers:
first the route/state shell, then typed API adapters, then normalized view models, then shared
visualization components, then command/approval affordances. The existing plan/GIS/nav features keep
working while new panes are introduced behind typed API adapters. Every pane labels forecast,
simulated truth, estimator belief, and live telemetry explicitly. No component may fetch raw backend
JSON directly after its work area has a contract adapter.

**Phase 3 — ephemerides, azimuth, imagery, and ARGUS authority.**
Exit: one sun/ephemeris/azimuth service feeds shadows, imagery layers, navigation risk, camera policy,
and ARGUS. The UI displays sun elevation, azimuth convention, site frame, source/provenance, and
accepted/rejected evidence. ARGUS becomes an operational loop: planned relocalization stop -> render or
camera observation -> articulation/shadow/parallax factor -> pose graph update -> cockpit evidence.

**Phase 4 — path planning, navigation, and Autoware-style execution seam.**
Exit: global planner, local planner, tracker, recovery, keep-outs, obstacle classification, height/volume
classification, slip/energy budget, and command lowering are connected by one navigation contract.
Autoware concepts may be reused at the interface level, but STEWIE's lunar terrain, illumination,
excavation, and low-g terramechanics remain the authority. ROS2 action lowering stays gated by AG-08
and SF-01.

**Phase 5 — multi-vehicle coordination.**
Exit: fleet planning moves beyond allocation into coordinated execution: per-vehicle belief/health,
shared-resource reservations, corridor/time deconfliction, charger/dock/pit conflicts, cross-vehicle
precedence, conflict explanation, and deterministic fallback. The Fleet pane must show why a rover is
waiting, blocked, replanning, or cleared.

**Phase 6 — construction skills, recorded movements, volume/height acceptance, and self-docking.**
Exit: excavation, dump, berm-shape, traverse-repeat, and dock behaviors can be recorded, versioned,
replayed, compared, approved, and corrected by estimator feedback. Obstacle size, terrain height,
cut/fill volume, berm geometry, fill fraction, slip, and docking alignment all produce uncertainty
bands and acceptance events.

**Phase 7 — model integration and fine-tuning hardening.**
Exit: terrain assessment, rock classification, Shadow-SLAM/ARGUS, excavation state, regolith volume,
mission-planner LLM, and operator-assistant models are registered artifacts with lineage, model cards,
evaluation fixtures, calibration, OOD detection, quantized deployment budgets, rollback, and safe
fallback. No model gets a command path; the mission executive consumes typed outputs only.

**Phase 8 — test, optimize, secure, and release-gate.**
Exit: the slice has unit, contract, route, browser, mobile, integration, security, performance, and
traceability coverage. Optimization budgets cover map rendering, tile/cache behavior, planning latency,
fleet solve time, ARGUS factor latency, model inference, memory, and bandwidth. Security review covers
auth/roles, CSP, secrets, SBOM/CVEs, backup/restore, exposed routes, command interlocks, log retention,
redaction, and replayability from event hashes.

### 25.3 Non-negotiable implementation rules

- No capability is complete unless it is visible in the cockpit, backed by a typed route, tested, and
  traceable to a PRD row.
- No learned model directly controls the rover. Models produce bounded, typed estimates; deterministic
  planners, safety checks, role gates, and the mission executive decide whether commands can be emitted.
- No solar, shadow, ARGUS, or illumination result may use a private azimuth convention. The convention
  must be displayed, tested, and shared across all consumers.
- No fleet claim is complete until resource conflicts and path/time conflicts are represented in both
  the backend result and the UI.
- No self-docking or recorded construction movement may replay open loop; estimator feedback and safing
  checks are part of the primitive.
- No slice is complete without structured logs for success, rejection, failure, timeout, fallback,
  permission denial, and safing paths. Logs must be correlated across browser, backend, model runner,
  ROS bridge, simulator, and report artifacts.
- No release claim is allowed while front-end, backend, security, optimization, and test evidence are
  split across separate unverifiable narratives.

### 25.4 Front-end contracts, wiring, and windowing

The cockpit should be organized as one production application with routeable work areas, not as a set
of independent pages that each invent their own fetch/state/error logic. The contract boundary is:

```text
Backend route
  -> schema / fixture
  -> typed frontend client adapter
  -> normalized view model
  -> work-area component
  -> browser/mobile regression test
```

Required frontend contract adapters:
- `world`: body/site/time, terrain layers, illumination, ephemerides, map provenance.
- `mission`: PlanResult, command tape, feasibility, report, namespace/ownership.
- `fleet`: vehicles, assignments, reservations, conflicts, health, waiting reasons.
- `navigation`: route, local trajectory, tracker state, recovery state, keep-outs, cost layers.
- `argus`: articulation pose, camera rig, shadow/parallax factors, covariance, residual gates.
- `perception`: imagery, depth/point cloud summaries, rock/obstacle classes, height/volume estimates.
- `construction`: cut/fill state, bucket/drum fill, volume moved, berm/pad acceptance, recorded skills.
- `models`: model artifacts, datasets, eval reports, deployment profile, fallback/rollback status.
- `security`: role, permissions, command eligibility, audit events, session/auth state.
- `system`: health, metrics, storage, backups, validation gates, dependency/SBOM state.

Required log/event channels:
- `audit`: login, logout, invite, role change, permission decision, namespace publish/delete/restore.
- `mission`: mission create/save/load, plan request, feasibility result, replan, report export.
- `command`: command eligibility, approval, lowering, dispatch, acknowledgement, timeout, SAFE.
- `world`: TwinStore/timeline event, terrain mutation, observed patch, backup, restore, provenance.
- `navigation`: route request, local-plan update, tracker state, recovery action, blocked reason.
- `argus`: sun/azimuth source, observation, residual, covariance, accepted/rejected factor.
- `fleet`: reservation, conflict, wait reason, handoff, deconfliction, reassignment.
- `model`: artifact selected, version, input/output hashes, confidence, OOD/fallback, latency.
- `frontend`: pane route, contract adapter error, empty/loading/error state, command affordance shown.
- `system`: startup, config, dependency, storage, health, metrics, security scan, backup drill.

Wiring order for each work area:
1. Add or freeze the backend response schema and example fixture.
2. Add the frontend adapter and normalized view model.
3. Render a fixture-only empty/loading/error/success pane.
4. Connect the live route behind the adapter.
5. Add route, permission, mobile, and failure-mode tests.
6. Only then expose the pane in the primary cockpit navigation.

Windowing decision:
- **Production operations use one browser cockpit.** A commandable mission must not require two
  browser windows, because duplicated command state, stale approvals, and split role context are safety
  risks.
- **A second browser window is allowed only as read-only support context**, for example a detached
  telemetry/evidence display for a director or reviewer. It mirrors state from the primary cockpit and
  has no unique command buttons, approvals, or hidden state.
- **Engineering tools are separate by design.** RViz, Gazebo, ROS2 CLI, bag replay, and Godot render
  diagnostics may run in separate windows during development, but they are not the operator interface
  and must not bypass AG-08, SF-01, role gates, or the cockpit audit trail.
- **Large screens use panes, not independent authority.** The preferred production layout is a single
  routeable cockpit with optional split panes: map/world left, selected work area right, evidence drawer
  bottom, command/approval rail explicit and role-gated.

### 25.5 Code-grounded architectural review and reconciliation

The current PRD is not allowed to be treated as automatically current. The completion path is a
code-grounded reconciliation sweep, then implementation of the truly-open subset. Each row reviewed
gets one of four labels:

| Label | Meaning | Action |
|---|---|---|
| DONE-stale | Code and tests satisfy the requirement, but the PRD row is stale. | Correct the PRD status and add/verify `[REQ:<ID>]` trace markers. |
| PARTIAL | Some implementation exists, but product integration, tests, qualification, or frontend wiring is incomplete. | Record the missing link and smallest atomic follow-up. |
| OPEN | No meaningful implementation exists. | Keep the row open and sequence it into §25.2. |
| BLOCKED | Implementation requires external data, hardware, licensing, deployment, or qualification. | Name the blocker and avoid claiming completion. |

Reconciliation evidence format:

```text
REQ-ID:
  status: DONE-stale | PARTIAL | OPEN | BLOCKED
  evidence:
    - file:line implementation
    - file:line test
    - file:line frontend/backend wiring, if applicable
  missing:
    - smallest next action, or "none"
```

First verified stale-done correction:
- `CT-04` is no longer `N/N/N`. `stewie/twin/io_fields.py` publishes scene rasters atomically,
  validates raster dimensions before writing, writes `metadata.json` last as the commit marker, and
  removes stale optional contract rasters on republish. Existing tests cover commit-marker behavior,
  no leftover `.tmp` files, and incomplete-scene rejection; the PRD row is corrected to `D/P/D/NA`.

Architectural review scope for the next sweep:
- Contracts and authority: CT, TW, VT, AG, FS rows plus manifest drift.
- Terrain, energy, vehicle, terramechanics: real authority versus calibrated/oracle gaps.
- Perception, ARGUS, SLAM, imagery, small models: backend reachability, truth firewall, UI evidence.
- Navigation, construction, fleet: PlanResult, local planner, resource conflicts, execution feedback.
- Frontend organization: every top-level work area must have a contract adapter, route/state binding,
  role gate, fixture render, mobile layout, error/empty states, and log visibility.

The review output should feed §7 status corrections first, then implementation. A row that is stale
done should not consume implementation time; a row that is partial should be split into the exact
missing backend route, frontend adapter, test, log, or qualification slice.
