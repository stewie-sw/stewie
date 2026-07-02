# STEWIE WM / DT Architecture Gap Analysis

Date: 2026-06-29

Scope: STEWIE world model and digital twin directly. This is based on the refreshed Graphify map at
`graphify-out/graph.json`, the interaction source table at
`docs/stewie_digital_twin_interaction_map_2026-06-28.md`, and the current STEWIE code paths.

## Graphify Baseline

The map is current.

| Check | Result |
|---|---|
| state-block nodes | 18 |
| interaction rows retained | 51, `INT-001` through `INT-051` |
| graph hops | 102, because each `INT-###` row is modeled as `source -> INT -> target` |
| dangling endpoints | 0 |
| duplicate directed edges | 0 |
| collapsed directed edges | 0 |

Do not read the 102 graph hops as 102 distinct requirements. The actual interaction table has 51
distinct couplings. Current row status:

| Status | Count |
|---|---:|
| complete | 26 |
| partial | 10 |
| started | 9 |
| planned | 5 |
| sim_only | 1 |

## Comparison To 60-Entry Phase 1 Spanning Set

The supplied "STEWIE Interaction Layer: Phase 1 Spanning Set" is a better committee-facing taxonomy than
the current implementation graph. It separates the **Lunar World Model** from the **IPEx Digital Twin** and
uses the interaction layer as the formal third object. The current Graphify map is still useful, but it is
implementation-state oriented: it tracks what is complete, partial, started, and planned in the STEWIE repo.

These are not competing artifacts. The correct reading is:

- current Graphify map: "what STEWIE currently implements and wires"
- 60-entry spanning set: "what the full Phase 1 interaction taxonomy should cover"
- next graph revision: keep the current implementation status fields, but adopt the 60-entry family taxonomy
  and add a crosswalk from old `INT-001..051` to the family IDs

### Coverage By Family

| Target family | Target count | Current coverage | Reading |
|---|---:|---|---|
| A. Terramechanics and contact | 6 | strong partial | slope, weak soil, sinkage, payload load, and compaction exist; subsurface rock impact and crater-rim collapse are not first-class rows |
| B. Excavation and terrain modification | 5 | strong partial | cut, dump, terrain events, and memory exist; drum cutting force and stratigraphic volatile exposure are not operationally wired |
| C. Optical and lighting | 6 | partial | ephemeris, shadow, PSR low light, and shadow-yaw factors exist; phase-angle/opposition effects and camera exposure response need explicit rows |
| D. Dust dynamics | 5 | weak | current graph has only excavation dust to camera; missing dust as a world state and missing radiator, panel, optics, and mechanism degradation branches |
| E. Thermal | 5 | weak partial | cold sink, camera health, and PSR route exist; missing day heating, radiative cooling, regolith contact, lunar night survival, and thermal fatigue as rows |
| F. Power | 5 | partial | reserve-aware planning exists; missing solar incidence generation, explicit load-to-SoC, SoC-to-autonomy, heater-budget arbitration, and shadow power drop |
| G. Localization and mapping | 6 | strong partial | DEM, landmark, parallax, shadow-yaw, loop closure, stereo, and map diff exist; low-texture drift and six-camera mapping are not explicit rows |
| H. Hazard and planning | 5 | partial | obstacle, slope, uncertainty, and active-perception gates exist; predicted traction, illumination-window scheduling, and resource-value planning are thin |
| I. Fault, health, autonomy | 5 | partial | watchdog and executive policies exist; missing entrapment fault, thermal fault, disparity-health monitor, degradation prognostics, and comm-loss policy rows |
| J. Multi-agent | 5 | gap | multi-vehicle planning exists elsewhere in code, but the interaction graph does not model shared-world multi-agent couplings |
| K. Communication and geometry | 3 | gap | line-of-sight, light-time latency, relay windows, and comm planning are absent from the interaction graph |
| L. Synchronization and persistence | 4 | partial | `TerrainMemory`, `TwinStore`, and `TransactionLog` exist; graph lacks first-class `DigitalTwinSync` / `PersistenceWorldState` rows and checkpoint/replay edges |

### Current Rows That Map Cleanly

| Target family | Current rows |
|---|---|
| A | `INT-005`, `INT-006`, `INT-007`, `INT-015` |
| B | `INT-012`, `INT-013`, `INT-014`, `INT-015`, `INT-016`, `INT-047` |
| C | `INT-002`, `INT-003`, `INT-004`, `INT-017`, `INT-025`, `INT-033` |
| D | `INT-048` only |
| E | `INT-022`, `INT-023`, `INT-049` |
| F | `INT-021`, `INT-041`, `INT-049` |
| G | `INT-024`, `INT-026`, `INT-027`, `INT-028`, `INT-029`, `INT-031`, `INT-032`, `INT-034`, `INT-035`, `INT-036`, `INT-040` |
| H | `INT-010`, `INT-011`, `INT-037`, `INT-038`, `INT-042` |
| I | `INT-025`, `INT-043`, `INT-045` |
| J | no direct current rows |
| K | no direct current rows |
| L | `INT-016`, `INT-039`, `INT-040`, `INT-046`, `INT-050`, plus `TransactionLog` code not yet represented as an interaction row |

### Important Mismatches

The target set uses clearer world/twin nouns than the current map. The current map should eventually add or
rename these state blocks:

| Missing or under-modeled target block | Why it matters |
|---|---|
| `DustDynamics` | Without it, dust remains a one-off camera degradation row instead of a world-mediated cascade into optics, thermal, power, and mechanisms. |
| `Communication` | Needed for line-of-sight, latency, relay windows, command acknowledgement, and comm-loss autonomy. |
| `MultiAgentCoordination` | Needed for shared-world path reuse, deconfliction, map sharing, and one rover changing another rover's plan. |
| `HealthMonitoring` / `FaultDetection` | Needed to model degradation and protective behavior as explicit state, not only as executive decisions. |
| `ResourceModeling` | Needed for volatiles, ice, and resource-priority planning. |
| `PredictionModels` | Needed to keep illumination, traction, power, and observation forecasts separate from measured state. |
| `DigitalTwinSync` / `PersistenceWorldState` | Needed to represent DT-01 as runtime synchronization, not just library code. |

The target set also contains NASA-open reference and STEWIE-realization columns. The current graph lacks this
two-layer fidelity contract. That is a real weakness for committee review because it makes sim-only lunar
physics less explicit.

### Graph Update Recommendation

Do not renumber the current `INT-001..051` implementation graph in place. It is already useful as a status
graph and has test-backed links to current STEWIE code. Instead, create a v2 interaction graph with:

1. the 60-entry family taxonomy as the canonical Phase 1 coverage map
2. stable family-range IDs, such as `INT-010`, `INT-030`, `INT-040`
3. a `legacy_current_id` field for rows that map to the current graph
4. the existing `status`, `needed_next`, and code-evidence fields from the current graph
5. the new `reference_nasa_open` and `stewie_realization` fields from the spanning set
6. explicit `sim_only` flags for vacuum, one-sixth gravity, electrostatic dust, PSR optics, thermal cycling,
   orbital geometry, and relay geometry

This gives the project two clean views over one model: a committee taxonomy and an implementation status
view.

## Current Architecture Reading

STEWIE now has three real but overlapping world-model artifacts:

1. `TerrainMemory`: the product-facing terrain memory. It records per-site, mass-conserving terrain
   deltas from completed missions, persists them, and lets `/plan` imprint the remembered surface onto
   the planning DEM before solving another mission.
2. `TwinStore`: the observed-terrain twin. It stores perception/operator resync patches as an append-only,
   hash-chained journal with provenance and undo-as-event.
3. `TransactionLog` / `WorldTransaction`: the DT-01 transaction envelope. It can link conserved authority,
   observed `TwinStore`, latest `PlanResult`, and belief into one hash-chained, durable world-state record.

That is good architecture progress. The remaining problem is product wiring: these artifacts are not yet
forced through one runtime authority in every plan, execute, perceive, and cockpit read path. STEWIE has the
spine pieces, but the live operational twin is still assembled by convention rather than by one mandatory
transaction path.

## What Is Working

### Conserved Terrain And Planning

- `TerrainMemory` is the current product-facing terrain memory.
- `/plan` calls `_as_built_dem(...)`, loads site memory if present, and plans against the as-built DEM.
- Mission terrain deltas can be recorded through `/twin/terrain/{site}`.
- The conserved terrain delta path is tested.

Claimable: STEWIE can remember prior construction and use that remembered terrain in later planning, in the
sim/product path.

### Observed Twin

- `TwinStore` exists, is hash-chained, requires provenance, supports undo-as-event, journals per edit, and
  cold-restores from disk.
- `/twin/resync` mutates observed terrain and is operator-gated.
- `/twin/version` is auth-gated and exposes only minimal version state.
- `/twin/history` is director-gated.

Claimable: the observed twin has a durable audit model. It is not yet the same thing as the conserved
terrain memory.

### DT-01 Transaction Envelope

- `TransactionLog` and `WorldTransaction` exist.
- They link authority hash, twin version/hash, plan id, belief snapshot, mission/site/body/time/provenance,
  uncertainty, and a chain hash.
- Journaling and cold restore are tested.

Claimable: the DT-01 transaction data structure exists and is tested as a library-level spine.

Not yet claimable: every product state transition is committed through that spine.

### ROS / Executive Seams

- The pure ROS bridge converts `/cmd_vel` to the RC contract and publishes odometry-shaped state.
- SF-01 watchdog behavior is tested in the pure bridge path.
- Plan IR lowering exists for paths, motion goals, work goals, observation goals, posture plan, and replan
  events.
- `PitBackend` is a real adapter shape over the CCSDS link, but live UDP/ROS binding remains gated.
- `run_sim_execution` can drive a released mission through the SIM executive lifecycle.

Claimable: the command/odom and plan-lowering seams exist and are tested without requiring ROS 2.

Not yet claimable: live ROS/pit execution is operational end to end on the default host.

## Architecture Gaps

### A1. One Runtime World-State Authority Is Still Missing

The product still has separate stores:

- conserved physics authority / `ColumnState`
- `TerrainMemory`
- `TwinStore`
- `TransactionLog`
- runtime packets
- `PlanResult`
- belief state
- session/executive events

`TransactionLog` is the right unifier, but current runtime routes do not appear to require a transaction
commit for every meaningful state transition. That means code can still plan, resync, record terrain, or run
SIM execution without producing one canonical world-state record.

Needed next:

- Add a server-owned `WorldStateService` or equivalent that is the only route-level facade for plan,
  terrain record, resync, execution event, and belief update.
- Make that service commit `WorldTransaction` records.
- Expose a read route for the latest linked transaction and its source versions.
- Treat independent reads of plan/twin/belief/authority as internal implementation details, not product API.

Graph couplings: `INT-016`, `INT-039`, `INT-046`.

### A2. TerrainMemory And TwinStore Need A Clear Ownership Contract

Right now both are valid:

- `TerrainMemory` remembers physically built terrain deltas.
- `TwinStore` remembers observed/resynced terrain patches.

They should not silently compete. The product needs a stated rule:

- physical action writes `TerrainMemory` and conserved authority evidence
- perception/operator correction writes `TwinStore`
- the transaction envelope links both
- planning chooses a defined surface composition, for example `base DEM + TerrainMemory delta + accepted TwinStore overlay`, with provenance and confidence tags

Without this, "current terrain" can mean different things depending on which module a caller uses.

Needed next:

- Define `CurrentTerrainView` with explicit inputs and precedence.
- Make `_as_built_dem` consume that view rather than `TerrainMemory` alone.
- Add tests where a physical build and an observed patch both affect the next plan, with provenance retained.

Graph couplings: `INT-016`, `INT-040`, `INT-046`.

### A3. State Variables Are Not Yet All Carried In One Message Surface

The architecture doc names `WorldState`, `VehicleState`, `VehicleModel`, `BeliefState`, `PlanResult`,
`ExecutionEvent`, `TwinStore`, `RuntimePacket`, and `SessionRecord`. Current code has many of these pieces,
but not a single product contract that every subsystem reads/writes.

Needed next:

- Define one typed `WorldStateSnapshot` for product reads.
- Define one typed `ExecutionEvent` for all command, observation, ack, fault, replan, terrain mutation, and
  safety transitions.
- Store both under the transaction envelope.

Graph couplings: `INT-039`, `INT-043`, `INT-044`, `INT-051`.

## Wiring Gaps

### W1. Sim Execution Is Not Yet The Main Product Execute Path

`lode/sim_execution.py` is good, but its own docstring says route, persistence, and HMI calling are separate.
The graph still marks executive-to-mission and executive-to-ledger paths partial.

Needed next:

- Wire released plan -> `run_sim_execution` -> SSE/cockpit state.
- On each leg, emit an `ExecutionEvent`.
- On terrain-changing work, record `TerrainMemory` and commit a `WorldTransaction`.
- Label every output `SIM`, never live.

Graph couplings: `INT-039`, `INT-043`.

### W2. Live ROS / Pit Path Remains Host And Link Gated

The pure bridge, plan lowering, stream session, watchdog, and PitBackend adapter exist. The remaining missing
piece is the live runtime binding:

- `rclpy` host/container path
- real pit link details
- live telemetry feeding the same belief and transaction surfaces
- command acknowledgement and fail-safe semantics exercised over the real transport

Needed next:

- Keep pure tests as acceptance guards.
- Add one container-run verification script that launches the bridge, sends a command, receives odom, trips
  watchdog, and records a transaction.
- Do not promote this to a live claim until that run is reproducible.

Graph couplings: `INT-008`, `INT-044`, `INT-045`.

### W3. NavFactor ROS Message Is Too Narrow For The Python Factor Contract

`dart/factors.py` has the richer contract: factor type, value, covariance, frame, source, evidence class,
accepted/refused, refusal reason, metadata.

The ROS message surface is still scalar:

- `kind`
- `x`
- `y`
- `sigma_m`
- `header`

That cannot carry 2x2 covariance, yaw factors, DEM height-normal factors, loop closures, evidence class,
refusal reason, or source/provenance without side channels.

Needed next:

- Upgrade `stewie_msgs/NavFactor.msg` and `NavFactorArray.msg`.
- Add bridge conversion from `MeasurementFactor.to_json()` to ROS message and back.
- Add tests for `dem_xy`, `parallax_xy`, `shadow_yaw`, `loop_closure`, and refused metric shadow factors.

Graph couplings: `INT-027`, `INT-032`, `INT-034`, `INT-035`, `INT-051`.

### W4. Perception Producers Are Still Mostly Artifact-Level

The factor types exist, and many DART algorithms exist, but operational producers are still incomplete:

- truth-free DEM scan-match producer
- truth-free articulation parallax producer
- runtime AprilTag factor producer
- measured loop closure producer
- live rock detector path
- covariance propagation from lighting/shadow confidence

Needed next:

- Promote the best offline artifacts into runtime producer modules with one input packet and one factor output.
- Make each producer refuse when it cannot produce a factor with valid covariance and provenance.
- Commit accepted and refused factors into the evidence ledger and transaction envelope.

Graph couplings: `INT-026`, `INT-028`, `INT-031`, `INT-035`, `INT-042`.

## What Is Not Working Yet

### N1. "Operational Digital Twin" Is Not Fully True Yet

The pieces are real, but the product path does not yet force all state changes through one world transaction.
Until then, the honest phrase is:

> STEWIE has tested digital-twin components and as-built terrain memory, but the operational twin is still
> being unified.

### N2. Planning On As-Built Terrain Exists, But Full Read-Back Is Narrow

`/plan` can imprint `TerrainMemory`, which closes a meaningful part of the read-back loop. But it does not
yet consume a composed current-terrain view that includes observed patches, uncertainty, lighting, material
changes, and live execution events.

### N3. Perception-To-Belief Is The Main Scientific Gap

The graph shows the heaviest incomplete cluster around:

- `PerceptionState -> RoverBelief`
- `TerrainMesh -> PerceptionState`
- `ArticulationState -> PerceptionState`
- `LightingModel -> PerceptionState`

That is exactly the lunar navigation research frontier: turning DEM, shadows, articulation parallax, loop
closure, and landmarks into accepted covariance-bearing factors without truth leakage.

### N4. Environmental Fidelity Is Still Shallow

The 60-entry spanning set makes this sharper: current STEWIE has enough environmental state for planning and
simulation claims, but it does not yet cover the full south-pole interaction taxonomy. The shallow areas are:

- ephemeris provenance
- terrain-event shadow residuals
- camera noise/exposure under PSR and low light
- thermal survivability and camera health
- dust/occlusion
- volatile/ice material effects
- line-of-sight and relay geometry
- communication latency and comm-loss behavior
- multi-agent shared-world effects
- long-horizon health degradation

These are not blockers for planner/trainer claims, but they are blockers for lunar operational fidelity
claims.

### N5. The Current Graph Under-Represents World-To-Twin Cascades

The target set is better at tracing physical cascades:

- dust lofting into optics, radiator, panel, and mechanism degradation
- thermal environment into power and fault behavior
- communication geometry into autonomy mode
- one rover's terrain change into another rover's route
- persistence checkpoint into deterministic replay

The current graph has some of the endpoints, but not the intermediate world-state blocks. That makes it look
as if effects jump directly from regolith to camera, or from executive state to mission plan, when the actual
system should pass through persistent world state, health monitoring, communication, or coordination layers.

## Highest-Leverage Build Order

1. **WorldStateService / transaction integration.** Make one route-level service commit transactions for
   plan, terrain record, resync, sim execution, belief update, and factor ledger update.
2. **CurrentTerrainView.** Compose base DEM, TerrainMemory, TwinStore, uncertainty, and provenance into the
   one terrain surface planners and cockpit reads use.
3. **SIM execute lifecycle wiring.** Released plan -> simulated execution -> terrain memory -> transaction
   log -> cockpit/SSE. Keep `SIM` labels explicit.
4. **NavFactor message upgrade.** Align ROS `NavFactorArray` with `dart.MeasurementFactor`.
5. **First truth-free producer pair.** Implement accepted `dem_xy` and `parallax_xy` producers with
   covariance, refusal paths, and evidence ledger records.
6. **Lighting covariance path.** Propagate shadow/contrast/disparity confidence into factor covariance.
7. **Interaction graph v2.** Add the 60-entry family taxonomy with `legacy_current_id`, NASA-open reference,
   STEWIE realization, and `sim_only` fields, then regenerate Graphify from the v2 table.
8. **Dust, comms, and multi-agent seed rows.** Add minimal runtime stubs or explicit planned rows for
   `DustDynamics`, `Communication`, and `MultiAgentCoordination` so the graph covers the full Phase 1 taxonomy.
9. **Live ROS/pit verification.** Reproduce command, odom, watchdog, telemetry, and transaction recording in
   a ROS 2 container or pit setup.

## Claim Boundary After This Review

Claimable now:

- conserved terrain authority
- terrain memory that feeds later planning
- durable observed-twin patch journal
- tested transaction-envelope data structure
- tested pure ROS command/odom bridge and watchdog
- tested plan-lowering contract
- tested factor/evidence data model
- simulation-level executive execution

Not claimable yet:

- one mandatory operational digital-twin runtime path
- live ROS/pit execution end to end
- covariance-rich ROS nav factor transport
- truth-free DEM/parallax navigation end to end
- hardware-validated lunar excavation autonomy
- full lunar south-pole environmental fidelity
- complete 60-family Phase 1 interaction taxonomy in the implementation graph

## Verification Run

Commands run:

```bash
python3 scripts/export_stewie_interaction_graph.py
graphify diagnose multigraph --graph graphify-out/graph.json --json
pytest -q -o addopts='' \
  stewie/twin/test_envelope.py \
  stewie/twin/test_versioned.py \
  stewie/twin/test_terrain_memory.py \
  stewie/twin/test_runtime_packet.py \
  stewie/bridge/test_autonomy_contract.py \
  stewie/bridge/test_ros2_bridge.py \
  stewie/bridge/test_plan_lowering.py \
  lode/test_sim_execution.py \
  lode/test_terrain_delta.py \
  dart/test_factors.py
```

Result: Graphify diagnostics passed. Targeted tests passed: 89 passed.
