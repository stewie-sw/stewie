# STEWIE PRD: Lunar Construction and Solar-Terrain Autonomy

**Version:** 7.0
**Date:** 2026-06-09
**Status:** CANONICAL — the single source of truth for project design + reference. All other design
documents are archived (`docs/archive/`) or are upstream STEWIE architecture/roadmap sources
(maintained privately; public mapping in §16). The granular execution breakdown lives in the private
workspace: `design/STEWIE_ATOMIC_EXECUTION_PLAN_2026-06-09.md`.
**Baseline commit:** `047331250cf443498c25b5bead4bed167668752c`

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
| CT-01 | P0 | All public numeric inputs enforce units, finiteness, and physical domains. Negative depth/mass and NaN/Inf are rejected. | P | P | P | NA |
| CT-02 | P0 | `ColumnState` validates dimensions, array shapes, dtypes/domains, density, labels, disturbance, datum, ice, and inventory at construction. | P | N | P | NA |
| CT-03 | P0 | Every authority mutation is transactional, conserves mass when required, and leaves all invariants valid. | P | P | P | NA |
| CT-04 | P0 | Scene publication writes verified rasters atomically and metadata last as the commit marker. | N | N | N | NA |
| CT-05 | P0 | Python, Godot, and ROS share a versioned schema with strict required-field, frame, dtype, and range validation. | P | P | P | NA |
| CT-06 | P0 | Production contract checks use explicit exceptions, never removable `assert` statements. | P | P | N | NA |
| CT-07 | P1 | Every artifact records source commit, configuration, mode, seed, schema version, and input hashes. | P | P | N | NA |

### 7.2 Terrain, Material, and Illumination

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| TW-01 | P0 | Load and crop real polar LOLA terrain; fail explicitly if a requested real asset is unavailable. | D | P | D | P |
| TW-02 | P1 | Reproject supported non-polar products into a documented local metric frame. | D | P | D | P |
| TW-03 | P1 | Product paths use windowed/tiled terrain access rather than loading the full map by default. | D | N | P | NA |
| TW-04 | P1 | One seeded composite generator combines craters, rocks, material, and illumination parameters. | P | P | P | NA |
| TW-05 | P1 | `WorldState` carries per-cell material, traversability, observed/unobserved state, and calibrated uncertainty. | P | P | P | P |
| TW-06 | P1 | Add a site/time sun vector `s(t)` in the local world frame using a documented ephemeris interface. | D | D | D | P |
| TW-07 | P1 | Compute terrain horizon, direct illumination, cast-shadow mask, incidence angle, and overexposure risk from terrain plus `s(t)`. | P | N | P | P |
| TW-08 | P1 | Recompute affected illumination and navigation layers after excavation changes terrain. No stale pre-build shadow map may remain authoritative. | P | P | N | NA |
| TW-09 | P2 | Model camera LED contribution separately from solar illumination, including configurable intensity and pose. | P | N | N | N |
| TW-10 | P2 | Track dust/optical degradation as a state affecting image quality and maintenance decisions. `[PROPOSED]` | N | N | N | N |

### 7.3 Vehicle, Arms, Drums, and Stability

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| VT-01 | P0 | A typed `VehicleModel` supplies mass, gauge, wheelbase, wheel/contact geometry, CG, battery, drum capacity, speed, energy, sensors, and render assets. | P | P | P | P |
| VT-02 | P0 | Selecting a vehicle changes all applicable authority/planner numbers; cross-vehicle tests assert expected differences. | N | N | N | N |
| VT-03 | P1 | Model front and rear arm joint state, limits, velocity, brake state, and energy. Exact geometry must come from authoritative LAC/IPEx data. | N | N | N | G |
| VT-04 | P1 | Track four drums and per-drum fill rather than one global inventory for IPEx mode. | N | N | N | P |
| VT-05 | P1 | Compute dynamic CG from chassis, arm pose, drum pose, and fill mass. `[SPEC/PROPOSED model]` | N | N | N | G |
| VT-06 | P1 | Compute posture-dependent support polygon and static stability margin each step. | P | N | P | G |
| VT-07 | P1 | Nominal excavation requires balanced front/rear counter-rotation; asymmetric digging exposes reaction, traction, yaw, and pitch risk. | N | N | N | P |
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
| PM-05 | P0 | Stereo VO triangulates landmarks, maintains persistent tracks, and estimates relative SE(3) pose with robust outlier rejection. | P | N | P | N |
| PM-06 | P0 | Fuse VO/IMU and validated absolute factors in a recursive estimator or factor graph with covariance. | P | N | P | N |
| PM-07 | P0 | Loop closures are candidate-gated, geometrically verified, and auditable; false closures must not silently enter the graph. | N | N | N | N |
| PM-08 | P1 | Produce a local/world elevation map using robust per-cell aggregation and a rock occupancy/probability map. | P | P | P | P |
| PM-09 | P1 | Track observed coverage, effective sample support, uncertainty floor, and correlation; dense pixels from one view are not treated as independent evidence. | P | P | P | N |
| PM-10 | P1 | Benchmark on a fixed LAC-style suite: localization RMSE, 5 cm height-cell pass fraction, rock F1, coverage, runtime, and failure count across seeds/light/rocks. | P | N | P | N |
| PM-11 | P1 | Target benchmark: demonstrate repeatable centimeter-scale localization comparable to the `0.038-0.067 m` `[NAVLAB26]` reference before claiming parity. | N | N | N | N |
| PM-12 | P1 | Truth pose and semantic masks are development/evaluation-only and structurally unavailable to operational estimator code. | N | N | N | NA |

### 7.6 Solar-Terrain Navigation

Solar-terrain navigation is the use of known/estimated solar geometry and terrain-induced
illumination as navigation evidence and an active-perception control variable. It is distinct from
solar power scheduling.

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| SN-01 | P1 | Derive expected shadow azimuth from `s(t)` and local terrain/objects. `[PROPOSED]` | N | N | N | N |
| SN-02 | P1 | Detect reliable shadow vectors while rejecting rover/LED shadows, saturation, ambiguous penumbra, and texture edges. `[PROPOSED]` | N | N | N | N |
| SN-03 | P1 | Fuse accepted shadow evidence as a weak yaw factor with covariance; never as an unqualified absolute heading. `[PROPOSED]` | N | N | N | N |
| SN-04 | P1 | Re-evaluate shadow factors when terrain is excavated, the sun vector changes, or the observation viewpoint changes. | N | N | N | NA |
| SN-05 | P1 | Add illumination-aware route cost: visibility, saturation, shadow hazard, map uncertainty, energy, slope, and construction constraints remain separate inspectable terms. | N | N | N | N |
| SN-06 | P1 | Choose camera direction and exposure to avoid low-sun washout while preserving useful stereo overlap. | N | N | N | N |
| SN-07 | P1 | Choose camera subset and LED intensity to illuminate hard shadows within the active-camera and power budgets. | N | N | N | G |
| SN-08 | P1 | Permit arm-angle selection for near-field downward mapping or horizon/sun-grazing views using posture-dependent extrinsics. `[PROPOSED]` | N | N | N | G |
| SN-09 | P1 | Permit a Meerkat observation action for multi-height parallax and shadow/rock disambiguation when stability guards pass. `[PROPOSED]` | N | N | N | G |
| SN-10 | P1 | The active-perception objective maximizes expected localization/map information per joule and second, with stability risk as a hard constraint. | P | N | P | N |
| SN-11 | P1 | Low/high posture observations must be associated to the same world features through the current arm/camera transforms. | N | N | N | G |
| SN-12 | P1 | Solar-navigation claims require ablations against VO/SLAM without solar factors across multiple sun angles, terrains, terrain-change states, and seeds. | N | N | N | N |
| SN-13 | P1 | Acceptance target `[PROPOSED]`: improve median yaw/pose error or feature-track survival by a preregistered margin without increasing tip events; report energy/time overhead. | N | N | N | N |

### 7.7 Navigation, Planning, and Recovery

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| NV-01 | P0 | Global routing rejects unreachable goals; it never substitutes an unsafe straight line. | P | P | P | NA |
| NV-02 | P1 | Coverage routes promote map coverage and deliberate re-observation/loop closure. `[NAVLAB26 reference: overlapping loops/outward spiral]` | P | N | P | N |
| NV-03 | P1 | A local planner samples dynamically feasible short-horizon trajectories and rejects rock/terrain collisions. `[NAVLAB26 reference: constant-curvature arcs]` | N | N | N | N |
| NV-04 | P1 | A path tracker converts trajectories into bounded commands and reports expected speed/progress. | N | N | N | N |
| NV-05 | P1 | Reactive obstacle observations update dynamic keep-outs and trigger local/global replan. | N | N | N | N |
| NV-06 | P1 | Backup recovery triggers on progress ratio, duration, and planner failure; initial benchmark uses the `[NAVLAB26]` less-than-25%-for-2-to-3-second rule as a configurable reference. | N | N | N | N |
| NV-07 | P1 | Recovery distinguishes collision/obstacle blockage from expected slope/slip slowdown to avoid false reverse maneuvers. | N | N | N | N |
| NV-08 | P1 | Tip, entrapment, localization divergence, low energy, thermal violation, and actuator faults are explicit fault classes. | P | N | P | N |
| NV-09 | P1 | An executive monitors action preconditions, command acknowledgements, belief covariance, and acceptance state, then pauses/replans/fails safely. | N | N | N | N |
| NV-10 | P0 | Plan IR maintains independent position, energy, time, and action state per vehicle. | P | P | N | NA |
| NV-11 | P1 | ROS lowering emits paths, motion commands, arm/drum goals, observation actions, and replan events from Plan IR. | N | N | N | N |
| NV-12 | P1 | Live command/telemetry uses a versioned streaming API with timestamps, sequence numbers, backpressure, and safe-stop semantics. | N | N | N | N |

### 7.8 Construction Mission Planning

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| CP-01 | P0 | One immutable `PlanResult` is produced once and consumed by totals, report, validation, timeline, Plan IR, autonomy, and UI. | N | N | N | NA |
| CP-02 | P0 | Balance bank cut and loose fill by mass with drum/capacity constraints. | D | D | D | P |
| CP-03 | P0 | Execute/validate the selected optimized plan on the conserved authority and real terrain. | P | P | P | P |
| CP-04 | P1 | Goal grammar supports typed structures, tolerances, budgets, priorities, deadlines, dependencies, and keep-outs. | P | P | P | NA |
| CP-05 | P1 | Footprints support rectangle, circle, corridor, and polygon with orientation; scalar-area squares are legacy input only. | N | N | N | NA |
| CP-06 | P1 | Acceptance includes pad flatness, berm profile, bearing/compaction, repose stability, mass, time, and energy. | P | P | P | P |
| CP-07 | P1 | Plan uncertainty carries DEM, material, slip, dig-rate, drum-fill, localization, and power-window uncertainty into feasibility/time/energy bands. | P | N | P | N |
| CP-08 | P1 | Planner objectives support hard constraints and risk terms, not only unconstrained weighted metrics. | N | N | N | NA |
| CP-09 | P1 | Construction actions mutate `WorldState`; routing, illumination, observability, and acceptance consume the updated terrain. | P | N | P | NA |
| CP-10 | P1 | Sinter remains unavailable for baseline IPEx; enabling it requires a distinct tool/power model and capability-qualified vehicle. | D | D | D | P |

### 7.9 Energy, Thermal, Power, and Operations

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| EP-01 | P0 | Energy ledger includes drive, slope/slip, payload, dig, arm/drum motion, observation, LEDs, compute, idle/heater, and recharge losses where modeled. | P | P | P | P |
| EP-02 | P1 | Dig energy depends on material/density/ice or is explicitly marked constant-model uncertainty. | N | N | N | N |
| EP-03 | P1 | Distinguish PSR lander/tower power from sunlit solar power. | D | P | D | P |
| EP-04 | P1 | Mission clock enforces power, illumination, thermal, and communications windows on actions/recharge. | N | N | N | N |
| EP-05 | P1 | Thermal derating and heater/survival demand affect usable battery and action availability. | P | P | P | N |
| EP-06 | P1 | Meerkat/arm posture and camera/LED policies include transition and dwell energy. | N | N | N | G |
| EP-07 | P2 | Dust accumulation affects optics, joints, thermal surfaces, and maintenance actions. | N | N | N | N |
| EP-08 | P1 | Endurance and reports use the selected `VehicleModel`, not global IPEx constants. | N | N | N | N |

### 7.10 Fleet Planning

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| FL-01 | P0 | Fleet allocation, simulation, validation, timeline, Plan IR, and playback share one `PlanResult`. | P | N | N | NA |
| FL-02 | P1 | Detect and resolve route, site, and temporal conflicts rather than only same-site overlap. | P | N | P | NA |
| FL-03 | P1 | Model charger, pit, dump, observation vantage, and constrained corridor as shared resources. | N | N | N | NA |
| FL-04 | P1 | Maintain one belief/health/resource state per rover and coordinate replans. | N | N | N | N |
| FL-05 | P2 | Support heterogeneous vehicle capability and physics vectors. | P | N | P | N |
| FL-06 | P1 | Validate two-rover plans against an exact small-problem oracle before learned/heuristic superiority claims. | N | N | N | NA |
| FL-07 | P1 | Solar/Meerkat observation sites are reservable fleet resources so rovers do not occlude or collide during raised observations. `[PROPOSED]` | N | N | N | N |

### 7.11 Product, Packaging, and Operations

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| PO-01 | P0 | `stewie-serve` (alias `dustgym-serve`, deprecated) works after a fresh wheel install with one documented product extra. | P | P | N | N |
| PO-02 | P0 | Reports, profiles, caches, and renders use configurable application-data directories and atomic writes. | N | N | N | NA |
| PO-03 | P0 | CI installs declared dependencies and runs the configured suite across supported Python versions. | P | P | N | NA |
| PO-04 | P0 | CI separately gates Python core, scripts, Godot, browser, package smoke, and hardware-gated tiers. | P | N | P | NA |
| PO-05 | P1 | Commit a dependency lock, build an SBOM, scan resolved artifacts, and run a fresh-install test. | P | N | N | NA |
| PO-06 | P1 | Server enforces streamed body limits, execution timeouts, bounded concurrency, auth policy, and deployment-safe CORS. | P | P | P | N |
| PO-07 | P1 | Structured logs include request/event ID, mode, plan ID, route, duration, outcome, and error class. | P | P | P | N |
| PO-08 | P1 | Metrics are bounded and exportable in a standard operations format. | P | P | P | N |
| PO-09 | P1 | Mission/profile schemas are versioned and migratable. | P | P | P | NA |
| PO-10 | P1 | UI distinguishes forecast, simulation truth, estimator belief, and live telemetry. | P | P | P | NA |
| PO-11 | P1 | Fleet playback renders every rover and its independent telemetry. | N | N | N | NA |
| PO-12 | P1 | Solar view displays sun vector, illumination/shadow layers, active cameras/LEDs, arm posture, and evidence accepted/rejected by localization. | N | N | N | N |
| PO-13 | P1 | Add `CHANGELOG.md`, exported `__version__`, SemVer policy, and release evidence manifest. | N | N | N | NA |
| PO-14 | P1 | Provide deployment documentation and a supported server image; optional Godot/ROS capabilities are explicit profiles. | N | N | N | N |

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
The SolNav dissertation planning set (G1–G9 gates, separate honesty firewall) is NOT renamed or
re-scoped by STEWIE. Convergence: STEWIE P20 (ROS2 bridge + live drive loop) is the same engineering
object as the dissertation's persistent-runtime gap (G1.A4/A6) — one build advances both tracks;
the dissertation's evidence-mode rules still apply on its side.

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
→ state correction → re-simulate futures) — the dissertation-relevant piece.

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

### 19.1 Where the §7 matrix actually stands (census, 2026-06-10)
112 identified requirements; **0 release-ready (all-required-columns D), 19 partial, 93 not
started.** By family (worst-column):

| Family | Scope | P | N | Note |
|---|---|---|---|---|
| CT 7.1 | contracts/conserved authority | 3 | 4 | the strongest family — the core IS the product |
| TW 7.2 | terrain/material/illumination | 4 | 6 | TW-06 ephemeris sun = DONE in code (SPICE) — matrix stale, flip on evidence |
| VT 7.3 | vehicle/arms/drums/stability | 1 | 9 | the two-vehicle stance gap lives here (VT-01/02/05) |
| AM 7.4 | posture maneuvers (MEERKAT…) | 0 | 9 | all gated on authoritative IPEx geometry |
| CP 7.5 | perception/mapping/localization | 5 | 5 | the G1/G2 evidence feeds this |
| SN 7.6 | solar-terrain navigation | 0 | 13 | **the dissertation family** (ARGUS) — by design still open |
| NV 7.7 | navigation/planning/recovery | 1 | 11 | berm re-hazard + routing exist; recovery behaviors don't |
| PM 7.8 | construction mission planning | 1 | 11 | the planner is rich but matrix-unverified |
| EP 7.9 | energy/thermal/power/ops | 2 | 6 | battery-honest timeline shipped; thermal ops partial |
| FL 7.10 | fleet | 0 | 7 | MV1-7 exists; fleet reqs unverified |
| PO 7.11 | product/packaging/ops | 2 | 12 | docs trilogy + fetcher land here; flip on evidence |

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
   SN as the dissertation track.

### 18.1 Rung status (2026-06-11)
Rung 4: gaps 2 (telemetry shaping — downlink latency first-class, per-sol ledger + stranded
accounting) and 3 (director/operator roles; truth views + admin director-gated) are CLOSED with
TDD; gap 1 (the pluggable RC contract + SF-01 watchdog) remains BLOCKED on the dirt-pit protocol
(the ask is staged). Rung 3: designed (COLMAP_TRIAGE_DESIGN); the budget ledger shipped; ingest
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
- **As FLIGHT-RELEVANT autonomy / the ARGUS estimator (the dissertation):** **~30%, by design.**
  The SN solar-terrain-navigation family is 13/13 open; the pose-graph that fuses sun/shadow/DEM
  factors over mutating terrain is scaffolded (shadow_predict, register_to_dem, the re-hazard,
  the conserved mutable twin) but NOT integrated. This is the protected contribution, correctly
  unbuilt at proposal stage.

**Quantitatively against the §7 matrix:** 112 requirements, 0 were release-ready (all-D) at the
§19.1 census; after the audit fixes + the traceability seeding, the CT (contracts) family is the
closest to release and the security posture moved from "one remote-compromise critical" to
"no known criticals." The honest headline: **the simulator product is ~75% and gated on one
external dependency (the RC protocol); the flight-autonomy story is early and protected.**
