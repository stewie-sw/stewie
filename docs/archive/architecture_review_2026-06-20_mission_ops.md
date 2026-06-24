# STEWIE Mission-Operations Architectural Review

**Review date:** 2026-06-20  
**Reviewed commit:** `d41d1e8` (`main`, with one unrelated modified test file present)  
**Scope assumption:** `/mnt/projects/stewie/code` is the requested system.  
**Review stance:** what a team would require before using STEWIE to plan, rehearse, authorize, execute,
and debrief a surface mission. This is a software architecture and operational-readiness review, not a
flight-safety certification.

## Executive verdict

STEWIE is a strong mission-planning and simulation platform with a conserved terrain authority, real
DEM-based routing, explicit Plan IR, useful uncertainty/provenance work, a capable planning cockpit, and
substantially improved web security. It is suitable for engineering analysis, simulation, training, and
mission-design iteration.

It is **not yet an operational ROS 2 mission system**. The ROS workspace is a contract and packaging
skeleton around a Gazebo sensor bridge and one small `/cmd_vel` adapter. The perception, localization,
mapping, planning, control, and vehicle-interface processes do not implement their declared graph. There
is no persistent ROS command session, no live action server/executive, no lifecycle orchestration, no
SROS2/DDS security, and no hardware backend in the deployed command path. The current RViz configuration
describes the intended picture but most of its data producers do not exist.

The release-blocking issue is not lack of another visualization. It is the absence of one durable,
authoritative execution path:

`approved PlanResult -> signed plan release -> persistent mission executive -> command eligibility ->`
`ROS actions -> hardware interface -> acknowledgements -> observed world state -> replan/SAFE -> audit`

Until that path exists and passes fault-injection tests, all UI execution controls should remain visibly
labeled **SIMULATION** or **FORECAST**.

## What is already worth preserving

- The conserved terrain authority and explicit truth/observed-state separation are the correct foundation.
- One `PlanResult` now drives plan views, timeline, validation, report, and Plan IR rather than independent
  recomputations.
- Physical input validation, route feasibility, battery reserve, return-to-lander logic, uncertainty
  reporting, keep-outs, precedence, shared resources, and multi-vehicle planning provide a credible mission
  design core.
- Web controls fail closed when production authentication is absent. Role, namespace, CSRF, revocation,
  audit, compute quota, read-only container, and proxy-trust controls are present and tested.
- ROS message definitions, REP-103 intent, truth-denial policy, Gazebo description, bridge configuration,
  and RViz packaging give the integration work a useful starting contract.
- The cockpit already distinguishes forecast, observed, and truth concepts in several places. That
  honesty must become a strict visual and data contract everywhere.

## Release-blocking findings

### P0-1: The ROS 2 autonomy graph is descriptive, not executable

All six domain nodes are 28-line skeletons. For example,
`ros2_ws/src/stewie_control/stewie_control/node.py:1-24` creates a plain `Node`, logs that it is a
skeleton, and spins. It has no publisher, subscriber, lifecycle transitions, parameters, diagnostics,
or control logic. The same implementation is repeated for perception, localization, mapping, planning,
and vehicle interface.

The frozen contract says these are managed lifecycle nodes and declares nine required roles
(`stewie/bridge/autonomy_contract.py:50-122`), but there are no sensing, diagnostics, or mission-executive
packages. The single launch file starts Gazebo, robot state publication, spawning, and `ros_gz_bridge`
only (`ros2_ws/src/stewie_bringup/launch/gz_sim.launch.py:21-35`).

**Required:** implement actual managed nodes, compose them under one bringup launch, and prove the live
topic graph, QoS, lifecycle, diagnostics, and failure transitions in launch tests. Do not mark a phase
complete because package discovery or an RViz config-load smoke passes.

### P0-2: `/rc/plan_ros` does not publish to ROS or maintain a safe command session

`stewie/server/routers/rc.py:60-89` lowers a live mission to dictionaries, creates a local
`StreamSession`, frames every item at one timestamp, returns those frames in an HTTP response, and then
discards the session. There is:

- no ROS publisher or action client;
- no acknowledgement endpoint/consumer;
- no call to `StreamSession.tick()`;
- no `on_safe_stop` callback;
- no durable sequence state or replay protection;
- no call to `command_eligible()`.

The repository's backpressure, stale-link, namespace, and safing logic is therefore tested pure logic,
not a property of the live emission path (`stewie/bridge/stream.py:25-79`,
`stewie/bridge/command_eligibility.py:26-54`).

**Required:** replace the request-scoped object with a persistent mission-executive service. The HTTP API
may request a release, but only the executive may publish. It must durably own plan/revision/sequence,
consume acks and heartbeats, call the eligibility interlock for every emission, tick deadlines, and issue
SAFE through an independent hard-stop path.

### P0-3: The apparent rover command path is a simulator and accepts unsafe numeric input

The server hardcodes `RC.SimBackend` (`stewie/server/routers/rc.py:20-21`). A hardware backend cannot be
selected through a typed, attested runtime configuration. The low-level `/rc/command` endpoint constructs
commands from untyped dictionary floats without finite/range validation (`:43-55`); NaN, infinity,
negative speed/radius, and unreasonable time factors are not rejected by the frozen command dataclasses.

The CLI ROS bridge also constructs `SimBackend` (`stewie/bridge/ros2_bridge.py:193-210`). Its docstring
correctly calls a real backend a future swap, but product language elsewhere calls this a real command
path.

**Required:** introduce validated command schemas, bounded velocity/acceleration/curvature/work envelopes,
unique command IDs, expiry, source plan revision, authorization decision, and idempotency. Hardware mode
must require an explicit backend plugin, hardware identity, two-person release policy, active SAFE chain,
and startup self-test. It must never silently fall back to simulation.

### P0-4: The ROS frame and odometry contract is insufficient for navigation

The bridge maps grid `row/col` directly to odometry metres without applying `cell_m`
(`stewie/bridge/ros2_bridge.py:51-60`), omits `child_frame_id`, covariance, z/roll/pitch, angular velocity,
and timestamps from source telemetry, and labels achieved velocity as map-frame while placing it in the
Odometry twist field (`:172-186`). The contract also declares both localization and vehicle interface as
publishers of `/stewie/odom` (`autonomy_contract.py:100-113`), while it separately defines
`/stewie/wheel_odom`. This creates two authorities for one state estimate.

Pure rotation is not correctly represented by the Twist-to-short-goal conversion: nonzero angular speed
with zero linear speed yields a zero-distance `GoTo` with zero maximum speed
(`ros2_bridge.py:25-40`). Reverse motion is converted to a forward speed aimed behind the robot, losing
the original velocity semantics.

**Required:** establish one REP-103/105 frame authority and one unit system. Vehicle interface publishes
`odom -> base_link` wheel odometry; localization publishes `map -> odom` plus fused pose; TF owns frame
transforms. Use `ros2_control` velocity/effort interfaces or a typed motion action rather than translating
Twist into an ad hoc moving waypoint. Add frame/unit/covariance/timestamp tests against rosbag fixtures.

### P0-5: Command and telemetry transports have no operational cryptographic protection

The ROS deployment has no SROS2 enclave, keystore, governance/permissions policy, DDS security settings,
or domain isolation beyond a demo `ROS_DOMAIN_ID`. The optional ROS service uses host networking. The
CCSDS `UdpLink` sends and accepts unauthenticated datagrams from any source and silently ignores send
errors (`scripts/ccsds_ros_nav/link.py:79-130`). Packet structure and sequence counts are not source
authentication, integrity protection, freshness enforcement, or anti-replay.

**Required:** enable SROS2/DDS Security with per-node enclaves and least-privilege topic/service/action
permissions; pin the RMW and discovery configuration; isolate the robot network; authenticate operator,
ground, and vehicle endpoints; and protect the CCSDS transport with an approved authenticated security
layer. Reject wrong peers, stale epochs, duplicate sequence numbers, expired commands, and invalid
message bounds. Record all rejects.

### P0-6: Safety depends on polling and shares the application failure domain

The web watchdog advances only when `/rc/telemetry` is polled (`routers/rc.py:92-101`). A blocked worker,
dead UI, wedged process, or stalled event loop may therefore prevent the check intended to stop motion.
The ROS bridge has a timer, but the bridge, watchdog, command translation, and backend still share one
Python process and DDS path.

**Required:** implement the stop chain in the lowest practical vehicle controller, default outputs to
zero on process/link loss, and supervise it independently. The mission executive may request SAFE, but
loss of the executive, DDS, ground station, or browser must also result in bounded autonomous safing.
Exercise power loss, process kill, DDS partition, delayed/out-of-order command, sensor freeze, and stuck
actuator scenarios in HIL.

## High-priority architectural findings

### P1-1: Mission intent lacks a first-class objective and acceptance contract

The planner has orders, weighted optimization metrics, budgets, precedence, windows, and validation, but
the operator-facing mission object does not require a structured statement of purpose, measurable success
criteria, abort criteria, mandatory/optional objectives, priority, confidence, or contingency branches.
An optimization objective such as `time` is not the mission objective.

**Required:** add versioned `MissionIntent`, `Objective`, `Constraint`, `AcceptanceCriterion`,
`Contingency`, and `ReleaseDecision` contracts. Every objective needs a stable ID, priority, geographic
scope, observable completion test, deadline/window, resource ceiling, minimum acceptable outcome, and
abort/hold conditions. Plan actions and telemetry events must trace back to those IDs.

### P1-2: The mission executive needs explicit state and authority transitions

The target executive should expose at least:

`DRAFT -> ANALYZED -> REHEARSED -> REVIEWED -> RELEASED -> ARMED -> EXECUTING ->`
`HOLDING | SAFED | COMPLETED | ABORTED -> DEBRIEFED`

Transitions require named evidence and roles. `RELEASED` is a signed immutable plan revision;
`ARMED` requires rover identity, configuration match, clock sync, map/pose freshness, energy reserve,
communications, SAFE health, and operator readiness. Replanning creates a new revision and never mutates
the released plan in place.

### P1-3: ROS interfaces need actions and services, not only topics

Topics are appropriate for sensor streams and continuously sampled state. Mission execution needs ROS 2
actions for `Navigate`, `Excavate`, `Dump`, `Observe`, `Dock/Charge`, and `ReturnToLander`, with goal
acceptance, feedback, cancel, timeout, result, and recovery semantics. Use services for arm/disarm,
snapshot, reset-localization, load-plan, validate-plan, and request-hold. Keep emergency stop outside the
normal action queue.

Each action goal should carry mission ID, plan revision, action ID, vehicle ID, objective IDs, frame,
deadline, validity interval, expected resource envelope, tolerances, and idempotency key.

### P1-4: RViz is an engineering view, not the mission-control display

The current config has useful layers, but it is one undifferentiated display tree with only Orbit camera
controls (`ros2_ws/src/stewie_rviz/rviz/mission.rviz:7-104`). Several configured `*_viz` and marker topics
are outside the frozen topic table and currently have no producers. It lacks mission state, command
authority, objective status, data age, source/provenance, link health, energy margin, timeline, alerts,
and acknowledgement state.

**Required:** keep RViz for autonomy engineers and field-debugging. Use the web cockpit as the operational
human-machine interface, fed by a read-only gateway that consumes ROS and emits a versioned operator view
model. Never let the browser subscribe directly to arbitrary DDS topics or publish `/cmd_vel`.

### P1-5: Topic QoS classes are comments, not enforced profiles

The contract stores strings such as `sensor`, `command`, and `state`, while skeleton nodes use no concrete
QoS. A queue depth of 10 in the small bridge is not a mission QoS specification. Define named profiles
with reliability, durability, history, depth, deadline, lifespan, liveliness, and lease duration. Add
runtime graph assertions and incompatible-QoS tests.

Recommended defaults:

| Data | QoS intent |
|---|---|
| Camera/point cloud | best effort, volatile, keep-last 1-3, deadline monitored |
| IMU/wheel state | best effort or reliable by measured link, volatile, short lifespan |
| Fused state/diagnostics | reliable, volatile, bounded history, deadline + liveliness |
| Map/plan/config | reliable, transient-local, revisioned |
| Commands/actions | reliable, volatile, explicit expiry and ack; never rely on DDS delivery alone |
| SAFE state | reliable, transient-local, independent vehicle-local enforcement |

### P1-6: Plan identity should be collision-resistant and release-aware

Plan IR uses a 16-hex-character truncated SHA-1 content ID (`lode/planner_views.py:477-486`). Bandit flags
this and a non-security render cache SHA-1. The immediate risk is not password cracking; it is using a
short, unversioned digest as operational command correlation.

**Required:** canonicalize the full release manifest and use SHA-256 (or a signed release UUID plus full
digest). Include mission schema version, world-state version, vehicle/config hashes, software build,
planner configuration, objective contract, and all external data checksums. Keep render cache identifiers
separate from command identities.

### P1-7: Planning deadlines do not cancel computation

The server explicitly notes that timing out a planner future does not kill the worker. Four timed-out
requests can continue consuming the pool, and additional work can accumulate. Move heavy planning/render
jobs to bounded worker processes with cancellation, memory/CPU quotas, queue limits, and job status.

### P1-8: Simulation, forecast, observed, and truth need one enforced provenance vocabulary

The code is generally candid, but operator trust will fail if a simulated pose, forecast battery, observed
DEM, and truth surface share colors or labels. Every field in the operational view model should carry
`source`, `basis`, `timestamp`, `age`, `frame`, `units`, `confidence`, and `revision`. UI components must
render provenance consistently and reject incompatible frames/revisions rather than silently combine them.

## Target architecture

```text
MISSION DESIGN ZONE (ground, non-real-time)
  Mission Intent -> World/Vehicle Snapshot -> Constraint Compiler -> Candidate Planner
       -> Deterministic Validation -> Simulation/Fault Campaign -> Review Package
       -> signed immutable Plan Release

OPERATIONS ZONE (ground, durable)
  Operator Cockpit -> Operations API -> Mission Executive / Event Store
                                      -> ROS Gateway (allowlisted schema only)
  Telemetry Archive <- View Builder <- ROS Gateway <- vehicle telemetry/diagnostics

ROBOT ZONE (real-time and safety bounded)
  Plan Action Server -> Local Planner -> ros2_control Controller -> Hardware Interface
          ^                 |                   |                   |
  Mapping/Localization <- Perception <- Sensors/TF              Vehicle MCU
          |                 |                                       |
          +-> Health/Safety Supervisor -> independent stop/hold ----+

TRUTH/EVALUATION ZONE (simulation/test only)
  Gazebo/Chrono/terrain authority -> truth topics + score pipeline
  No route from truth topics to estimator or operational command enclaves.
```

Architectural rules:

1. The terrain/twin store is authoritative for material state; ROS nodes propose actions and report
   observations, never mutate terrain files directly.
2. The mission executive is authoritative for plan revision and action state.
3. Localization is authoritative for `map -> odom`; vehicle odometry is authoritative for
   `odom -> base_link`; no duplicate publisher authority.
4. The vehicle safety supervisor is authoritative for whether motion is physically enabled.
5. Every cross-zone interface is versioned, authenticated, bounded, observable, and replayable.
6. Simulation and hardware backends are explicit modes with incompatible startup attestations.

## Full ROS 2 integration plan

### Required packages

| Package | Responsibility |
|---|---|
| `stewie_description` | URDF/Xacro, calibrated sensor extrinsics, collision/inertial models |
| `stewie_hardware` | `ros2_control` SystemInterface, MCU heartbeat, brakes, drum/arm I/O |
| `stewie_sensing` | drivers, timestamps, calibration, image/IMU/wheel publication |
| `stewie_perception` | stereo/depth, rock/negative-obstacle detection, quality metrics |
| `stewie_localization` | wheel/IMU/visual/Navigation fusion, TF, covariance, integrity monitor |
| `stewie_mapping` | observed DEM, occupancy, excavation state, map revision/provenance |
| `stewie_planning` | Plan IR adapter, global corridor, local trajectories, costmap layers |
| `stewie_control` | bounded trajectory tracking through `ros2_control` |
| `stewie_work_actions` | excavate/dump/observe/dock action servers and posture FSM |
| `stewie_executive` | plan release, action dispatch, ack, hold/replan/abort, event log |
| `stewie_safety` | lifecycle-independent health aggregation and vehicle-local SAFE interface |
| `stewie_gateway` | allowlisted ROS-to-operations view; no arbitrary topic bridge |
| `stewie_bringup` | sim/HIL/vehicle launch profiles, lifecycle manager, namespaces |
| `stewie_rviz` | engineering layouts and custom status/objective panels |

### Integration order and acceptance gates

1. **Frames, units, time, QoS:** freeze REP-103/105 frames, metre/radian/SI units, clock policy,
   calibration schema, and concrete QoS. Gate with TF, timestamp, covariance, and bag-contract tests.
2. **Vehicle safety and hardware:** implement `ros2_control`, vehicle-local watchdog, brakes/hold, command
   bounds, and diagnostics. Gate with HIL stop-distance and process/network-loss tests.
3. **Localization integrity:** publish wheel odometry, fused pose, covariance, transform health, and
   innovation/integrity alarms. Gate against truth-denied bags and known ground control.
4. **Observed mapping/perception:** publish revisioned map layers and quality/coverage; prove no truth
   subscriptions in operational enclaves.
5. **Navigation:** global route -> local trajectory -> controller -> hardware, with cancel/hold/recovery.
   Gate on obstacle, negative-obstacle, slip, localization-loss, and unreachable-path scenarios.
6. **Work actions:** typed actions for dig/dump/observe/dock with posture, resource, and acceptance feedback.
7. **Mission executive:** persistent plan release, per-action eligibility, ack/retry/idempotency, hold,
   replan, abort, resume, and append-only events.
8. **Gateway and visuals:** publish a stable `MissionOpsView`, not raw ROS internals, to the cockpit.
9. **Security:** SROS2 enclaves, network segmentation, key rotation/revocation, signed releases, secure
   boot/config attestation where hardware supports it.
10. **Qualification:** SIL -> accelerated sim -> fault injection -> HIL -> field analogue -> operational
    rehearsal. Promotion requires recorded evidence, not only unit tests.

## How the visuals should be set up

### Screen 1: Plan

Use a 60/40 layout. The left/main area is a 2D orthographic operational map by default; 3D is a secondary
inspection mode, not the primary authoring surface. The right side is the objective/constraint inspector.

Map layers, in this order:

1. base DEM/hillshade and coordinate grid;
2. confidence/age veil for the observed map;
3. slope, illumination/thermal, comms, and traversability costs;
4. hazards and keep-outs, with inflation shown separately from source geometry;
5. objectives, work footprints, charger/lander, resources, and geofences;
6. candidate routes colored by vehicle;
7. energy and localization uncertainty corridors;
8. planned terrain delta (cut/fill) as diverging colors;
9. labels for action ID, priority, and acceptance status.

The right inspector should show mission purpose, success criteria, hard constraints, objective priority,
assumptions, unresolved warnings, resource margins, uncertainty, and provenance. A bottom timeline shows
vehicle lanes, work, travel, charge, waits, comms/sun windows, dependencies, and contingency branches.

### Screen 2: Rehearse and compare

Show three synchronized panes:

- expected/nominal execution;
- uncertainty envelope and Monte Carlo/fault outcomes;
- worst credible or selected contingency.

Candidate cards should expose feasibility first, then minimum margins, objective completion, duration,
energy, charge cycles, localization exposure, comms exposure, and optimality claim. Never rank an
infeasible candidate above a feasible one because of a weighted score.

### Screen 3: Execute

The execution screen must be sparse and glanceable:

```text
[MISSION / REV] [SIM|HIL|LIVE] [STATE] [COMMAND AUTHORITY] [LINK] [UTC/MET]
[SAFE/HOLD banner and highest-priority alert]

[2D map: observed state, active path/action, uncertainty, hazards, stale-data hatching]
[vehicle cards: mode, pose integrity, SOC/reserve, thermal, slip, comms, active cmd/ack]

[objective progress] [action timeline / events] [camera selected by task, not a video wall]
[HOLD] [RETURN] [SAFE]                         [details/replan drawer]
```

Color rules:

- green means verified within limits, never merely connected;
- amber means degraded margin or operator decision required;
- red means violated limit/SAFE/abort;
- gray hatch means stale or unavailable;
- cyan/blue means forecast;
- white means observed estimate;
- magenta, shown only to directors in simulation/debrief, means truth.

Every value shows units and data age. Blinking is reserved for an unacknowledged critical condition.
SAFE is always visible and requires a deliberate guarded interaction; resuming requires a separate
checklist and authority decision.

### Screen 4: Debrief

Provide one scrubber across synchronized operator-seen, estimated, and truth/reconstructed views. Mark
commands, acknowledgements, replans, holds, safety trips, sensor gaps, map revisions, objective decisions,
and human actions. Plot expected versus actual energy, pose error/covariance, slip, throughput, terrain
delta, comms, and objective acceptance. Generate a signed summary referencing the exact plan, software,
configuration, bags, maps, and event-log hashes.

### RViz engineering layout

Ship separate configs rather than one overloaded file:

- `localization.rviz`: TF, wheel/fused odometry, covariance, factors, innovation health;
- `perception_mapping.rviz`: stereo, clouds, rocks, negative obstacles, DEM/occupancy revisions;
- `navigation.rviz`: global/local paths, footprint, cost layers, controller errors, recoveries;
- `worksite.rviz`: excavation state, target/as-built surfaces, drum/posture/action feedback;
- `safety.rviz`: lifecycle, diagnostics, command/ack, deadlines, SAFE causes, data ages.

Add a custom panel for mission/revision, lifecycle state, command authority, active action, last ack,
SAFE state, and data freshness. Disable truth displays by build/launch profile, not only by checkbox.

## Feedback the mission team needs

Feedback should answer five questions continuously:

1. **What is happening?** Active vehicle/action, executive state, command ID, acceptance/ack state.
2. **Are we still safe?** Stop margin, collision/keep-out margin, localization integrity, stability,
   thermal/power reserve, link health, actuator/controller faults.
3. **Are objectives still achievable?** Per-objective percent and evidence, critical path, remaining
   resources, forecast completion band, violated assumptions.
4. **What changed?** New observation/map revision, deviation from plan, replan reason, operator action,
   configuration or authority change.
5. **What decision is required?** Ranked options with consequence, deadline, required role, and the safe
   default if nobody responds.

Alert design must be stateful: `NEW -> ACKNOWLEDGED -> MITIGATING -> CLEARED`, with owner, cause,
consequence, recommended action, and linked evidence. Do not generate one alert per topic symptom; the
health supervisor should correlate symptoms into an operational fault.

## How mission objectives should be planned

Use a hierarchy rather than a flat order queue:

```text
Mission intent
  Primary objectives (must complete)
  Secondary objectives (complete if margins permit)
  Stretch/science objectives (opportunistic)
  Constraints and flight rules
  Acceptance criteria
  Contingencies and abort/return criteria
    Task graph
      Vehicle actions and observation requirements
```

Each objective should contain:

| Field | Purpose |
|---|---|
| `objective_id`, revision | Stable traceability |
| statement and rationale | Why the work exists |
| priority and mandatory flag | What may be sacrificed |
| target geometry/frame | Where and in which coordinate authority |
| measurable acceptance | Evidence needed to declare success |
| confidence requirement | Minimum belief quality, not only nominal value |
| time/illumination/comms windows | When it may occur |
| energy/material/thermal/data budgets | Hard resource ceilings |
| prerequisites/dependencies | Task-graph ordering |
| hold/abort thresholds | When autonomy must stop |
| contingency policy | Retry, observe, replan, skip, return, SAFE |
| approver and evidence | Who may release it and on what basis |

The planner may optimize time, energy, risk, coverage, or information gain only after mandatory
objectives and hard safety constraints are compiled. Weighted scoring must not convert a flight rule into
a soft preference. The output should include objective coverage and an explicit list of objectives that
are unplanned, partially planned, or dependent on unverified assumptions.

## Sequence for entering mission information

This is the order I would require in the cockpit. It follows dependency order and prevents operators from
authoring detailed tasks against an undefined world or vehicle.

1. **Mission identity and mode:** mission ID/name, campaign, SIM/HIL/LIVE, classification/data policy,
   operator/director roles, UTC/MET epoch.
2. **Intent and success:** purpose, primary/secondary objectives, measurable acceptance, priority, minimum
   useful outcome, abort/return criteria.
3. **Site and reference frame:** body, site/DEM version, CRS, origin, geodetic anchor, map age/coverage,
   charger, lander/safe havens.
4. **Fleet configuration:** vehicle IDs, hardware/firmware/calibration hashes, tools, payload, battery,
   communications, autonomy level, known degraded equipment.
5. **Environment and ephemeris:** terrain/material assumptions, sun/thermal/PSR, comms windows, forecast
   validity, uncertainty and provenance.
6. **Safety constraints:** keep-outs, slope/stability limits, localization integrity limits, energy reserve,
   thermal limits, velocity/acceleration, stop policy, no-go times, return margin.
7. **Operational resources:** charger and corridor capacity, pits/dumps, shared resources, data/downlink,
   crew/ground constraints.
8. **Objective geometry and work products:** cut/fill/observe/goto footprints, target profiles, tolerances,
   quantities, acceptance sensors, mandatory versus optional work.
9. **Dependencies and contingencies:** precedence, synchronization, retry/skip/replan rules, alternate routes,
   safe-hold and return branches.
10. **Planner policy:** hard constraints first; then objective weights, solver, risk posture, uncertainty
    method, and compute budget.
11. **Candidate review:** feasibility, worst margin, assumptions, uncertainty, conflicts, objective coverage,
    plan optimality, and alternatives.
12. **Rehearsal:** nominal, degraded comms, localization loss, energy shortfall, obstacle, actuator fault,
    process/network loss, abort, return, and recovery.
13. **Release package:** immutable plan/revision, checksums, software/config/map/vehicle versions, approvals,
    evidence, expiration, and rollback plan.
14. **Arm checklist:** physical vehicle identity, configuration match, clocks, pose/map freshness, link,
    batteries/thermal, SAFE chain, clear worksite, operator readiness.
15. **Execute and debrief:** continuous objective/safety feedback, event recording, controlled revision on
    replan, acceptance evidence, final terrain/material reconciliation, lessons and anomaly actions.

The UI should reveal these progressively. It should not ask for solver selection before objectives,
constraints, site, and fleet are defined, and it should not enable release because a plan merely rendered.

## Security hardening backlog

### Immediate

- Implement SROS2 enclaves and deny-by-default DDS governance/permissions.
- Remove unauthenticated UDP from any hardware-capable mode; add peer authentication, integrity,
  anti-replay, expiry, and source filtering.
- Validate every RC/ROS command field for finiteness, units, bounds, rate, freshness, and plan revision.
- Make watchdog/safing vehicle-local and continuously scheduled, not telemetry-poll-driven.
- Wire `command_eligible()` into the single emission point and audit both allow and deny decisions.
- Separate SIM/HIL/LIVE deployments, credentials, networks, data stores, and visual branding.
- Replace the truncated SHA-1 Plan ID with a full release digest and signed manifest.

### Before hardware field trials

- Threat-model browser, operations API, ROS gateway, DDS, vehicle MCU, update chain, data archive, and
  physical maintenance ports.
- Use per-service identities and short-lived credentials; remove shared API keys from human workflows;
  rotate and revoke keys without restarts.
- Pin base images by digest, generate SBOMs, sign images/artifacts, verify provenance on deploy, and scan
  OS plus Python/Node dependencies in CI.
- Run ROS services as non-root with seccomp/AppArmor, minimal mounts, read-only roots, resource limits,
  and no host network unless a reviewed DDS design requires it.
- Add append-only/tamper-evident command, auth, configuration, safety, and release logs with synchronized
  clocks and offline export.
- Fuzz CCSDS/message decoders, malformed ROS messages, file ingest, mission schemas, and action servers.
- Back up and restore mission/twin/event stores; exercise key loss, corrupt state, partial write, and
  rollback recovery.

### Before operational claims

- Independent penetration test and safety/security co-analysis.
- Two-person release/arm policy for LIVE and separation of duties for admin versus command authority.
- Incident response, credential compromise, lost-link, rogue-node, and unsafe-command drills.
- Documented residual-risk acceptance tied to tested software/configuration/hardware baselines.

## Recommended delivery sequence

### Phase A: make claims exact

Label current ROS nodes and cockpit execution as skeleton/simulation in the capability matrix and UI.
Resolve frame/unit/topic authority and remove duplicate `/stewie/odom` ownership. Define the objective and
release schemas.

### Phase B: build the safety and execution spine

Deliver vehicle-local SAFE, `ros2_control` hardware interface, validated actions, persistent executive,
eligibility at emission, ack/deadline handling, lifecycle bringup, and durable events. This precedes more
visual polish.

### Phase C: close autonomy on observed data

Implement truth-denied sensing, localization, perception, mapping, planning, control, and work actions.
Prove the full graph in SIL/HIL with bag replay and fault injection.

### Phase D: operational visuals

Build the Plan/Rehearse/Execute/Debrief views on a versioned gateway model, plus the five focused RViz
engineering layouts. Validate with mission operators using timed scenarios and error-recovery tasks.

### Phase E: security and qualification

Enable SROS2 and authenticated command transport, harden deployments and supply chain, then run field
analogue rehearsals. Promote a baseline only when its evidence package passes safety, security,
performance, and mission acceptance gates.

## Verification performed

- 101 targeted ROS workspace, bridge, autonomy-contract, command-eligibility, server-security,
  command-gate, deployment-hardening, authority, and ROS-lowering tests: **passed**.
- Ruff Pyflakes gate over bridge, server, planner, ROS workspace, and CCSDS code: **passed**.
- Docker Compose production configuration parse: **passed**.
- `pip-audit` against `requirements-server.lock`: **no known vulnerabilities**.
- `npm audit --omit=dev` for the Electron desktop: **0 vulnerabilities**.
- Bandit high/high scan: two SHA-1 findings described above; no credential or password hashing use.
- Tracked sensitive-filename check: no tracked `.env`, private key, credential, or secret file found.

Not performed in this review: a full 1,000+ test suite run, live Docker image rebuild, live ROS graph/HIL
test, browser usability session, external penetration test, or hardware safety validation. Those are
required evidence for later gates and cannot be inferred from static code or unit tests.
