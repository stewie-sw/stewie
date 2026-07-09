# STEWIE design fold: AUTODIG behavior layer + layered sensor ingest — 2026-07-08

Source vision: `scratchpad/aaron_autodig_ingest_2026-07-08.md` (Aaron, verbatim quotes below).
Repo screened READ-ONLY at `/mnt/projects/stewie/code/` (every claim cites a file opened during the screen).
Status vocabulary: **EXISTS** (reuse as-is), **PARTIAL** (structure present, the named piece missing), **NEW** (no implementation).

---

## 0. The two dissertation-safe wordings (verbatim, from Aaron's note)

> "This work integrates AUTODIG-like autonomous excavation routines with a mutable lunar world model by treating electrical excavation effort as a proxy observation for terrain resistance. The proxy does not replace regolith density; it constrains an effective regolith state used for planning, simulation, and post-mission map reconciliation."

> "STEWIE ingests live robot telemetry through ROS2 as timestamped observations, not authoritative ground truth. Sensor streams are fused into pose, terrain, excavation, and health estimates, which then update a versioned mutable world model used by planning, simulation, and mission reconciliation."

Clean claim (also verbatim): *"Use AUTODIG-style excavation control as the TRL-5 behavior layer, and use motor current/energy residuals as proxy measurements for effective regolith resistance, not as direct density measurements."*

---

## 1. AUTODIG as the TRL-5 behavior layer

**Target loop:** `AUTODIG command → excavation actuator electrical response → terramechanics residual → inferred regolith resistance/density proxy → STEWIE world-model update.`

### 1.1 What exists (screened)

| Element | Status | Evidence |
|---|---|---|
| The AutoDig control law, documented | EXISTS (doc only) | `docs/vehicle_ipex.md:78-92` — IPEx auto-dig per [BUCKLES]: "drum torque is the *process variable*, arm position the *control variable*"; front/rear setpoints equalised so horizontal dig forces cancel; "no force sensors: actuator models estimate joint torque from current + speed"; rock-stall state. This is the exact control structure to implement — it is described, not coded. |
| Cycle-level excavation behavior FSM | EXISTS | `lode/berm_fsm.py:1-58` — gated LOAD→HAUL→DUMP→GRADE→DONE cycle; LOAD→HAUL fires on `should_offload` upper-bound logic, HAUL→DUMP gates on arrival + tip margin, ABORT on instability. Commands only; the conserved authority mutates terrain. |
| Dig/dump/traverse verbs on the conserved authority | EXISTS | `stewie/physics/worksite.py` — `WorkSite.drive` (:229), `flatten` (:242), `dump` (:256), `compact_over` (:280), `sinter` (:297, gated). `leap/terrain_target_env.py:48,168` — `cut_depth_m` drum-cut action via `cut_to_inventory`. |
| Excavation orders in the mission planner | EXISTS | `lode/planner_model.py:269` — `_ORDER_KINDS = ("cut", "fill", "sinter", "goto")`; `lode/mission_intent_compiler.py:191,392` — `Objective.order_kind` lowered into plans. Berm building via the FSM above. |
| Bite depth (cut depth) as a bounded knob | EXISTS | `stewie/specs/system_profile.py:62` — `drum_cut_depth_frac_max = 0.50` [SPEC]; `stewie/physics/rassor_mass_model.py:83-97` — `drum_fill_rate_factor` models the anti-bridging knee (collection plateaus past ~50% scoop opening). |
| Drum speed | EXISTS (constant) | `stewie/specs/ipex_specs.py:45` — `DRUM_SPEED_RPM = 25.0` (RASSOR-2.0 actuator); used in `dig_power_w` (:160-163). Not a scheduled/controlled variable anywhere. |
| Arm/lift kinematics + dig reaction | EXISTS | `stewie/specs/arm_state.py` — `ArmState` posture, `net_dig_reaction_n` (:85), `ARM_EXCAVATION_LOAD_NM = 18.5` (TRL5 Table 7, `ipex_specs.py:65-66`); `rassor_mass_model.arm_raise_lift_energy_j` (:100) — gravity-work lift energy. |
| Traverse (closed drive loop) | EXISTS | `stewie/physics/drive.py:1-30` — cmd_vel closed loop with slip divergence; `lode/nav_pipeline.py:110,229` — `drive_route`/`run_navigation` receding-horizon spine over the real DEM. |

### 1.2 What is missing → the AUTODIG controller (NEW)

There is **no continuous excavation controller**: nothing regulates drum torque to a setpoint by servoing arm position/bite depth, nothing schedules drum speed, and no single behavior layer sequences dig → bite-depth regulation → lift → dump → traverse *below* the berm FSM's cycle granularity. `berm_fsm.py` decides *when* to haul; nothing decides *how* to dig. The dig verbs today are instantaneous conserved mutations (`cut_to_inventory` at a fixed `cut_depth_m`), not a controlled process with an electrical response over time.

**Design:** an `autodig.py` behavior layer (natural home: `stewie/physics/` or a new `forge/` module beside the terramechanics it consumes) implementing the [BUCKLES] loop — torque setpoint → arm-position control variable, front/rear setpoint equalisation, `MAX_CUT_DEPTH_FRAC` bound, stall detection (the documented rock ≥ 10 cm stall state, grounding on the existing slip-entrapment model `stewie/physics/slip.py:116` `slip_sinkage_equilibrium`), termination on `should_offload` (`rassor_mass_model.py:188`). It slots beneath `berm_fsm` (the FSM's LOAD state delegates to AUTODIG) and above the conserved authority (commands only; `ColumnState` mutates). Per-tick it emits the electrical observable record (§2) — the TRL-5 loop's first arrow.

---

## 2. Motor current/energy (I, V, τ, P, E) as proxy observables — PARTIAL

**Key correction (Aaron):** ρ is NOT replaced by an electric trigger. `I, V, τ, P, E` are **observables** for estimating `ρ̂_eff, R̂_dig, k̂_terrain, Ê_specific` — a proxy that *constrains an effective regolith state*, never a direct density measurement.

### 2.1 What exists

| Channel | Status | Evidence |
|---|---|---|
| Drum current **I** (forward + inverse) | EXISTS | `stewie/physics/rassor_mass_model.py` — `freespin_drum_current_a` (:111) synthesizes the FDC observable from conserved true drum mass; `LinearMassModel` (:130) calibrated inversion; `DrumSensor` (:213) end-to-end with seeded noise + published uncertainty band (`drum_mass_uncertainty_frac` :67, 2.56%/7.40% from NTRS 20210022781). This is the template for every other electrical observable. |
| Drum torque **τ** | PARTIAL | `stewie/physics/excavation_state.py:40` accepts `drum_dig_torque_nm` as an input; the lunar magnitude is sourced (`ipex_specs.py:66` 18.5 N·m). But no forward model *synthesizes* dig torque from the conserved cut — the channel is an input slot, not a produced observable. |
| Power/energy **P, E** | PARTIAL | `ipex_specs.dig_energy_per_kg` (:167, ≈4151 J/kg — this IS the nominal Ê_specific), drive 135 J/m, `dig_power_w` (:160); EP-02 dig-energy factor and EG-08 energy reconciliation exist (`PRD.md:614`). But energy is a *planner cost*, not an emitted per-cycle observable stream. |
| Voltage **V** + the telemetry schema | PARTIAL | The ingest schema already defines the power channel: `stewie/bridge/proprioception_io.py:37-38` — `_POWER_SAMPLE_KEYS = {"t", "voltage_v", "current_a", "power_w", "soc_frac"}` with strict SI-unit validation (V/A/W). The producer side (`stewie/twin/proprioception.py`) generates IMU + wheel encoders only — **no power-channel producer exists**. |
| Fusion of the channels | EXISTS | `stewie/physics/excavation_state.py:38` — `estimate_excavation_state` (ML-05, `PRD.md:970` glyph D\|D\|D\|N): fuses FDC drum current + drum torque + IMU pitch + arm posture + drive current → typed `ExcavationState {digging_state, fill_fraction, slip, stall_risk, confidence}`, advisory/uncalibrated until real IPEx/AutoDig telemetry (`stewie/contracts/__init__.py:296` — `calibration: "uncalibrated" | "ipex_autodig"` is already reserved). |

### 2.2 What is missing (NEW)

A **per-actuator electrical forward model**: given the conserved effort a dig/drive step demanded (cut mass, sinkage work, slope, lift), synthesize the (I, V, τ, P, E) record each motor would have logged — the drum FDC pattern (`DrumSensor`) generalized to the arm and drive actuators — published on the already-validated proprioception power channel, truth-firewalled (I3), covariance-carrying (I4). Without it there is no "excavation actuator electrical response" for the residual loop to consume.

---

## 3. The residual → effective-regolith-state estimator — the genuinely NEW core

### 3.1 What exists (the loop's skeleton is already in the repo)

- **Forward terramechanics** (predicted effort from nominal regolith params): Bekker pressure-sinkage + slip ladder, load-bearing — `stewie/physics/terramechanics.py` (re-export shim over `packages/stewie-forge`, :1-27) + `stewie/physics/slip.py:116` `slip_sinkage_equilibrium`.
- **The generic residual machinery**: `stewie/contracts/reconciliation_step.py` (MP-11) — `reconcile_prediction` (:68) takes predicted vs observed for "a real quantity (mass moved, energy, rover sinkage, pose, ...)", diagnoses the residual against the sensor tolerance, and emits WORLD-UPDATE and (beyond-tolerance) MODEL-UPDATE proposals into the **EG-08 lifecycle** (`PRD.md:614` — observed→compared→proposed→reviewed→accepted/rejected→applied→archived; a rejected proposal never mutates accepted truth). Both rows are glyph D.
- **Volume/mass cross-check**: `lode/regolith_volume.py:37` `estimate_moved_regolith` (ML-06, D) — before/after DEM mass vs conserved authority vs drum-fill sensing.
- **The catalog slot for the output**: `stewie/server/layer_catalog.json:362` — `physics.excavation_resistance` ("cutting/excavation difficulty", `source_class: derived/estimated`) is registered but has **no producer**; likewise `regolith.class` (prior/observed) and `physics.energy_cost`.

### 3.2 What is missing (NEW)

No code inverts effort residuals to terrain parameters. MP-11 proposes moving the *belief about the observed quantity*; nothing maps a dig-cycle's electrical-effort residual to **ρ̂_eff, R̂_dig, k̂_terrain, Ê_specific** as a *per-cell terrain state with uncertainty*. `k_terrain` estimation does not exist anywhere (grep across stewie/lode/dart/leap: forward-only).

**Design:** `regolith_estimator.py` — inputs: the AUTODIG cycle log (§1.2) + the electrical observables (§2.2) + the terramechanics forward prediction at nominal params; output: per-cell `(ρ̂_eff, R̂_dig, k̂_terrain, Ê_specific)` with covariance, emitted as MP-11 `PredictionResidual` proposals into EG-08, landing as the producer for `physics.excavation_resistance` + a `regolith.effective_state` belief layer. **Honesty invariant (from Aaron's wording, enforced in the type):** the output is tagged `proxy=True` — it constrains an *effective* regolith state for planning/simulation/reconciliation and is never surfaced as measured density. The conserved authority's true density is eval-only (the same truth firewall discipline as `stewie/bridge/sensor_io.py:26` `_FORBIDDEN_RUNTIME_KEYS`).

Aaron's six-step IPEx loop, mapped: (1) AUTODIG controls dig/bite/drum/lift/dump/traverse → §1.2 NEW; (2) motor logs reveal difficulty → §2.2 NEW; (3) terramechanics predicts expected effort → EXISTS (forge); (4) residuals update the world model → EXISTS (MP-11/EG-08), needs the new producer; (5) stored as a mutable terrain layer → EXISTS (twin, §5); (6) next plan avoids/exploits it → EXISTS (`lode/costmap_layers.py:193` `compose` already consumes named per-cell layers with blocking reasons; a calibrated resistance layer drops in as one more cost source).

---

## 4. Layered sensor ingest: ROS2 → gatekeeper → estimators → world model — PARTIAL

**Target path:** `Robot sensors → ROS2 topics → STEWIE Sensor Ingest Node (time-sync + TF + calibration + uncertainty gatekeeper) → state/terrain/excavation estimators → mutable versioned world model.`

### 4.1 What exists

| Stage | Status | Evidence |
|---|---|---|
| The gatekeeper (validation discipline) | EXISTS — file-mediated | `stewie/bridge/sensor_io.py` — strict runtime packet: truth physically separated (`evaluation_truth.json`), `_FORBIDDEN_RUNTIME_KEYS` (:26), `calibration_id` + per-camera intrinsics/extrinsics on `SensorFrame` (:47-64), canonical clock `SIM_CLOCK_DOMAIN` (PM-01, :22). `stewie/bridge/proprioception_io.py:1-11` — strictly-monotonic per-channel timestamps, SI-unit validation, covariance 4×4 symmetry + PSD ("no silent symmetrization"), truth firewall by denylist AND allow-list. This IS Aaron's "sensors = observations WITH uncertainty" gate — for file packets. |
| TF / frames | EXISTS | `stewie/bridge/frames.py:1-9` — "THE frame mapping: sim grid/world ↔ REP-103... The only conversion site. Every ROS-facing producer/consumer imports from here; no other module converts frames." |
| ROS2 bridge — command ingress + odom egress | EXISTS | `stewie/bridge/ros2_bridge.py:246-292` — `make_ros2_node` subscribes `/cmd_vel` (through the SF-01 SafingWatchdog) and publishes `/stewie/odom`. rclpy-optional. |
| A live ROS2 *sensor-topic* subscriber | PARTIAL (one topic) | `ros2_ws/src/stewie_mapping/stewie_mapping/node.py:91` subscribes `/stewie/perception/points` (PointCloud2). No general sensor-topic → validated-packet adapter; cameras/IMU/joint/power topics have no live ingest path into `sensor_io`/`proprioception_io`. |
| Estimators — state | EXISTS | dart VO/SLAM stack: `dart/stereo_vo.py:430` `estimate_vo`, `dart/superpoint_vo.py:207`, `dart/imu_preintegration.py` + `dart/imu_pose_graph.py`, `dart/loop_pose_graph_se2.py:177`, `dart/integrated_slam.py`, `dart/localization.py` (scan-to-DEM). Note: `dart/localization.py:9` says the corrected pose "feeds the autonomy ESKF" — **no ESKF module exists**; state estimation is pose-graph/VO based (the docstring over-promises; flag, don't build on it). |
| Estimators — terrain | EXISTS | `dart/observed_map.py` + the AS-10 mapper (`dart/world_model_layers.py:24` `WorldModelLayers.update_observed`, truth-denied I3). |
| Estimators — excavation | EXISTS | `stewie/physics/excavation_state.py:38` (§2.1). |
| Estimators — health | PARTIAL | power/soc schema validated (`proprioception_io.py:37`), diagnostics ledger (`stewie/bridge/diagnostics_ledger.py`); no fused health estimator — acceptable to defer. |
| Mutable versioned world model | EXISTS | §5. |

### 4.2 What is missing (NEW → one row)

The **live STEWIE Sensor Ingest Node**: a ROS2 node subscribing the sensor topics (stereo images, IMU, wheel/joint states, drum/arm motor power, battery) and emitting the *already-defined* validated packets (`SensorFrame`, proprioception/1.x) through the *already-built* gate — time-sync to the PM-01 clock domain, frame conversion only via `frames.py`, calibration-id check, uncertainty required, truth-key rejection. Everything downstream of the node exists; the node itself does not. Aaron's rule holds by construction: **no sensor writes the map directly** — the only paths into terrain state are the estimators, and the only path into *accepted* state is EG-08.

---

## 5. The layer structure raw/derived/belief/world/mission on STEWIE's real twin — PARTIAL

### 5.1 What exists

- **LY-01 layer catalog** (`stewie/server/layer_catalog.json`, 66 layers, 12 domains; LY-01 row D at `PRD.md:651`): every layer declares `source_class` — the observed values (`prior`, `observed`, `derived`, `derived/estimated`, `observed/belief`, `belief/live`, `forecast`, `observed/reconciled`, `sim_truth`, `live/replay`, ...) plus `planning_eligible` / `release_execute_eligible` gates. This *approximates* Aaron's tiers but is a free-form tag vocabulary, not a closed taxonomy.
- **The twin stack is versioned + mutable + reconciled**, exactly as the vision demands:
  - `stewie/twin/versioned.py:23` `TwinStore` — immutable base + append-only hash-chained event log, "resync patches come from reconstruction... the CONSERVED physics authority is never mutated through this channel."
  - `stewie/twin/terrain_memory.py:45` `TerrainMemory` — the authoritative as-built store, versioned hash-chained transactions per mission (`apply` :76).
  - `stewie/twin/terrain_view.py:27` `CurrentTerrainView` — the composed planning surface with **per-cell provenance** (observed > as-built > pristine) + versions + observed fraction.
  - `dart/world_model_layers.py:21` — AS-10 truth/observed/forecast/edited layers, per-layer provenance, cross-layer mutation forbidden.
  - Reconciliation-with-uncertainty into accepted state: EG-08 + MP-11 (§3.1) + the DT-03 atomic world transaction (CLAUDE.md 2026-07-02 record; contracts in `stewie/contracts/`).
- **Mission tier**: the `mission.*` catalog domain + `lode/planner_model.py` plans + the MO-02 lifecycle.

### 5.2 Mapping Aaron's five tiers onto the real system

| Aaron's tier | STEWIE reality | Gap |
|---|---|---|
| `/raw` (images, IMU, odom, current, voltage) | bridge packets + `session_record.py` streams; **not first-class catalog layers** | raw streams are not registered/addressable as layers |
| `/derived` (stereo depth, slip, sinkage, pose, drawbar proxy) | `physics.sinkage`/`physics.slip_risk`/`physics.traction_margin` etc. (`source_class: derived/estimated`) | tag ≈ tier, but nothing *enforces* the tier |
| `/belief` (terrain confidence, regolith resistance, traversability) | `observed/belief` + `belief/live` layers; `physics.excavation_resistance` (producer missing, §3) | same |
| `/world` (approved mutable terrain state) | `base.dem` + TerrainMemory/TwinStore compose; `observed/reconciled` | same |
| `/mission` (plans, executed paths, excavation changes) | `mission.*` domain + `map.changed_terrain`/`evidence.before_after_dem` | same |

### 5.3 What is missing (NEW → one row)

A **closed `tier` field** (`raw | derived | belief | world | mission`) on every catalog entry and twin surface, with enforced promotion semantics: planning/release eligibility requires `tier ∈ {world, mission}` (or `belief` with declared uncertainty), and state may only be *promoted* raw→derived→belief→world through an EG-08-accepted proposal. This is additive over `source_class` (keep both: source_class says where data came from; tier says what it may be used for) and makes the LY-01 eligibility gates derivable instead of hand-set.

**Reconciliation itself: EXISTS in full — no new row.** The observation-with-uncertainty → versioned-mutable-world pipeline (MP-11 residual → EG-08 lifecycle → DT-03 transaction → TwinStore/TerrainMemory version bump → CurrentTerrainView provenance) is delivered and glyph-D across its rows (`PRD.md:614,630`). The new work of §3 *feeds* it; it does not need rebuilding.

---

## 6. Proposed PRD §7 rows (additive; new section suggested: **§7.F AUTODIG excavation autonomy + layered sensor ingest (2026-07-08 fold)**)

Format matches the live matrix (`PRD.md:640`): `| ID | P | Requirement and acceptance | I | X | V | Q |`, all new rows `N | N | N | NA`. Prefixes **AD-** and **IN-** are unused in PRD.md (grepped against all 68 existing prefixes; the §7.B/§7.E blocks end at TF-01/QG-04/LY-07/GW-12, none colliding).

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| AD-01 | P1 | **AUTODIG excavation-control behavior layer.** The [BUCKLES] auto-dig loop as code: drum torque is the process variable, arm position/bite depth the control variable, front/rear setpoints equalised (counter-rotating cancellation); sequences dig / bite-depth regulation / drum speed / lift / dump / traverse as one behavior layer beneath the berm FSM (`lode/berm_fsm.py` LOAD delegates to it) and above the conserved authority (commands only). Bounded by `drum_cut_depth_frac_max` (system_profile.py:62); stall state grounds on slip-entrapment (`slip.slip_sinkage_equilibrium`) + the documented rock-stall (`docs/vehicle_ipex.md:78-92`); terminates on `should_offload`. Acceptance: a commanded dig cycle on the conserved authority regulates drum torque to setpoint under varying regolith density, respects the cut-depth bound, aborts on stall, hands a full drum to the FSM, and emits the per-tick AD-02 observable record; [REQ:AD-01] test. (extends berm_fsm/arm_state/WorkSite; feeds AD-03) | N | N | N | NA |
| AD-02 | P1 | **Per-actuator electrical observables (I, V, τ, P, E).** A forward model synthesizes motor current/voltage/torque/power/energy per actuator (drum, arm, drive) from the conserved effort of each step — generalizing the FDC pattern (`rassor_mass_model.DrumSensor`) — published on the already-validated proprioception power channel (`proprioception_io._POWER_SAMPLE_KEYS`), truth-firewalled (I3), covariance-carrying (I4), seeded-noise-optional. These are OBSERVABLES for estimation, never triggers. Acceptance: a dig cycle over two regolith densities produces distinguishable (I, τ, E) logs whose energy integral reconciles with the conserved dig energy (`ipex_specs.dig_energy_per_kg`) within stated tolerance; truth keys rejected by the ingest gate; [REQ:AD-02] test. (extends rassor_mass_model/twin.proprioception; needs AD-01's cycle log) | N | N | N | NA |
| AD-03 | P1 | **Effective-regolith-state estimator from excavation-effort residuals (proxy, NOT density).** Terramechanics-predicted effort at nominal params vs the AD-02 observed effort → residual → per-cell ρ̂_eff / R̂_dig / k̂_terrain / Ê_specific with uncertainty, emitted as MP-11 `PredictionResidual` proposals into the EG-08 lifecycle; the accepted result becomes the missing producer for the catalog's `physics.excavation_resistance` (layer_catalog.json:362) + a `regolith.effective_state` belief layer consumed by `costmap_layers.compose`. The output type carries `proxy=True`: it constrains an EFFECTIVE regolith state for planning/sim/reconciliation and is never surfaced as measured density (conserved true density stays eval-only). Acceptance: digging a seeded dense pocket on the conserved authority yields an accepted resistance update localized to the pocket with honest uncertainty, a rejected proposal never mutates accepted state, and the next planned route/dig re-costs over it; [REQ:AD-03] test. (extends reconciliation_step/EG-08/LY-01; needs AD-01+AD-02) | N | N | N | NA |
| IN-01 | P1 | **Live ROS2 Sensor Ingest Node — the gatekeeper.** One rclpy-optional node subscribes the robot sensor topics (stereo images, IMU, wheel/joint states, motor power, battery) and emits the existing validated packets (`sensor_io.SensorFrame`, proprioception/1.x) through the existing gate: time-sync to the PM-01 clock domain, frames only via `bridge/frames.py`, calibration-id check, per-sample uncertainty required, truth-key/allow-list rejection, monotonic-timestamp enforcement. No sensor writes any map directly; estimators are the only consumers. Acceptance: a bagged multi-topic sequence replayed through the node yields validated packets consumed by the dart mapper + AD-03 path; an out-of-sync, truth-carrying, or calibration-mismatched message is rejected with a legible reason and counted; [REQ:IN-01] test (container leg on the ros2 profile). (extends ros2_bridge/sensor_io/proprioception_io/stewie_mapping node) | N | N | N | NA |
| IN-02 | P1 | **raw/derived/belief/world/mission tier taxonomy on LY-01 + the twin.** Every layer-catalog entry and twin surface declares a closed `tier ∈ {raw, derived, belief, world, mission}` (additive beside `source_class`: source_class = where it came from, tier = what it may be used for). Enforcement: planning/release eligibility requires tier world/mission (or belief with declared uncertainty); promotion flows only raw→derived→belief→world and only via an EG-08-accepted proposal; raw sensor streams register as addressable `raw` catalog entries (never planning-eligible). Acceptance: all 66 catalog layers carry a valid tier; a raw layer marked planning-eligible fails validation; a belief→world promotion without an accepted proposal is refused; [REQ:IN-02] test. (extends LY-01/GW-03/GW-06/EG-08) | N | N | N | NA |

**Deliberately NO row** for "observation-with-uncertainty reconciliation into the versioned mutable world model": that pipeline fully EXISTS and is glyph-D — MP-11 (`stewie/contracts/reconciliation_step.py`, `PRD.md:630`) → EG-08 lifecycle (`PRD.md:614`) → DT-03 atomic transactions → `TwinStore` (versioned.py:23) / `TerrainMemory` (terrain_memory.py:45) → `CurrentTerrainView` per-cell provenance (terrain_view.py:27). AD-03 and IN-02 plug into it; nothing re-builds it.

### Dependency order
`IN-01` (ingest node) and `AD-01` (controller) are independent starts. `AD-02` needs AD-01's cycle log. `AD-03` needs AD-01+AD-02 and lands the loop. `IN-02` is independent governance, cheap, and should land early so AD-03's new layers register with correct tiers.

---

## 7. Screen summary (one table)

| Vision element | Verdict | Reuse | Build |
|---|---|---|---|
| AUTODIG behavior layer | PARTIAL | berm FSM, WorkSite verbs, order kinds, cut-depth bound, arm/drum specs, drive loop | the torque-regulated dig controller (AD-01) |
| I,V,τ,P,E observables | PARTIAL | drum FDC forward+inverse, power-channel schema, energy constants, ML-05 fusion | arm/drive electrical synthesis + emission (AD-02) |
| Residual → regolith proxy | NEW (skeleton EXISTS) | forward Bekker/slip, MP-11 residual machinery, EG-08, catalog slot | the inverse estimator ρ̂_eff/R̂_dig/k̂_terrain/Ê_specific (AD-03) |
| ROS2 ingest gatekeeper | PARTIAL | full validation gate (file-mediated), frames.py TF, PM-01 clock, one live topic | the live multi-topic ingest node (IN-01) |
| raw/derived/belief/world/mission | PARTIAL | 66-layer catalog + source_class + eligibility, versioned reconciled twin | the closed tier taxonomy + promotion enforcement (IN-02) |
| Reconciliation into versioned world | EXISTS | MP-11 + EG-08 + DT-03 + TwinStore/TerrainMemory/CurrentTerrainView | nothing (no row) |
