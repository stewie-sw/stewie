# STEWIE system status synthesis (2026-06-29)

Derived from the graphify digital-twin interaction graph (`graphify-out/graph.json`, 18 state-blocks /
102 interactions) cross-checked against a graphify-informed LLM council review of the live code. This is
the loop's driving map: it answers what relationships exist, the status, what we need and why, and the
variables and their interactions. Source graph: `docs/stewie_digital_twin_interaction_map_2026-06-28.md`.

## Variables (the 18 state-blocks STEWIE reasons over)

**Lunar World Model (the environment STEWIE owns and remembers).** LunarSite, TerrainMesh,
MutableTerrainLedger, RegolithState, Ephemeris, LightingModel, ThermalEnvironment, SurveyedMonuments.

**Robot and Perception State (the rover body and its beliefs).** RoverPose, RoverBelief, PerceptionState,
WheelDynamics, ArticulationState, ExcavatorDrum, CameraRig, PowerThermalState.

**Mission Planning and Executive.** MissionPlan, ExecutiveState.

## Relationships (the coupling hubs)

102 directed interactions. The most-coupled blocks (relationship count) are the hubs the whole twin turns on:

| State-block | Relationships | Role |
|---|---:|---|
| MissionPlan | 30 | the plan everything feeds into and reads from |
| PerceptionState | 30 | what the rover believes it sees |
| TerrainMesh | 18 | the surface (the most-coupled world-model block) |
| RoverBelief | 16 | fused pose and map estimate |
| ExecutiveState | 16 | the run lifecycle |
| MutableTerrainLedger | 14 | the conserved record of what was built |

Reading: the platform's spine is MissionPlan <-> TerrainMesh <-> MutableTerrainLedger (plan on the surface,
mutate the surface, record the mutation), with PerceptionState and RoverBelief as the rover-side mirror.

## Status (where the 102 interactions stand)

| Status | Count | Meaning |
|---|---:|---|
| complete | 52 | wired and load-bearing (incl. complete-in-sim, complete-pure, complete-in-code) |
| partial | 20 | one side wired, the loop not closed |
| started | 18 | begun, needs a producer or a calibration |
| planned | 10 | designed, not built |
| sim_only | 2 | works in sim, not on the sensor path |

About half the digital twin is closed (52/102). The open half clusters into three honest gaps the council
confirmed at file:line: a world-model read-back gap, a live-execution gap, and a perception-producer gap.

## What we need, and why (the open interactions, from the graph's `needed_next`)

| Interaction | Needs | Why |
|---|---|---|
| ExecutiveState -> MissionPlan | live executive node | the run lifecycle's live half (ARMED->EXECUTING) is dead; Execute only replays a forecast |
| ExecutiveState -> MutableTerrainLedger | live command provenance | executed actions are not recorded as a live audit trail |
| TerrainMesh -> MissionPlan (read-back) | plan on the as-built surface | a 2nd mission plans on the pristine DEM, ignoring what the 1st built (paradigm not closed) |
| WheelDynamics -> RegolithState | compaction calibration | the per-cell density loop is modeled in sim but not calibrated or fed to the planner |
| TerrainMesh -> PerceptionState | accepted producer | the observed-map / map-channel producer does not exist (render-gated) |
| LightingModel -> PerceptionState | covariance propagation | perception uncertainty under grazing-sun lighting is not propagated |
| LunarSite -> PowerThermalState | PSR layer | permanently-shadowed-region power/thermal is an inert schema slot |

## The council-prioritized next builds (each maps to a needed_next, each TDD-first)

The council's three converging builds are exactly the highest-leverage `needed_next` edges, in order:

1. **#246 auth-gate egress (security).** Not an interaction edge; it protects the data egress of the
   world-model blocks (TerrainMesh, RegolithState, Ephemeris) for the invitation-only deploy. Cheapest,
   most urgent. TDD: 401/403 unauthenticated, 200 with session; runtime-verify no pre-login 401s.
2. **#242 inc-1b-2 world-model read-back (closes TerrainMesh->MissionPlan + WheelDynamics->RegolithState).**
   Make `/plan` plan on `TerrainMemory.imprint_on_dem(base)` and give the ledger a density channel. TDD: a
   second mission over a built site plans a different (cheaper) route than the first.
3. **#245 SIM execute lifecycle (closes ExecutiveState->MissionPlan + ExecutiveState->MutableTerrainLedger).**
   Wire ARMED->EXECUTING against the sim authority, reusing session.py + executive_step + the SSE, with
   watchdog->SAFED and SIM-only labeling. TDD: a released plan runs leg-by-leg, halts on a watchdog trip.

## Honesty firewall (do not cross)

Everything from the sim run is `DataLabel.SIM`, never LIVE. The real-rover command path, AprilTag 12.7mm,
live Chrono, and live ROS odom stay gated. Uncalibrated magnitudes stay tagged `[CALIB]`/`[UNKNOWN]`.
`twin/world_model.py` is dead in production (excluded from the public cut); dedup the three world-model
representations down to the wired one (TerrainMemory) rather than crediting the dead one.

## Loop discipline

ONE verified checkpoint per tick: build TDD-first, council-validate before commit, deploy, verify (Playwright
for UI, real run for backend), commit with no Claude trailer, confirm CI green via `gh run view`, halt+fix on
red. Backend deploys are clean again (the coordination block is resolved).
