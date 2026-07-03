# STEWIE data / persistence architecture — hybrid store (2026-07-03)

Proposal (Aaron): a hybrid world-model database, not one DB for everything.

| Layer | Tool | Role |
|---|---|---|
| Authoritative world STATE | PostgreSQL + PostGIS | queryable interpreted world state + spatial indexing |
| Analytics / snapshots / offline science | DuckDB + GeoParquet | fast local geospatial analytics |
| Raw robot telemetry | MCAP / rosbag2 | high-rate ROS streams, replay |
| 3D scene / viz assets | 3D Tiles / glTF / USD | streamed 3D content |
| Blobs | Object storage | DEMs, meshes, imagery, bags, models |

## What is RIGHT (affirm)

- **Hybrid, each tool in its role** is the correct pattern (the "lakehouse for robotics" shape). Postgres for
  queryable interpreted state, DuckDB for analytics, MCAP for high-rate telemetry, object store for blobs.
- **"Do not store the raw sensor firehose in Postgres — store references + interpreted products"** is exactly
  right and matches STEWIE's evidence-bundle discipline (artifacts referenced by URI, interpreted state stored).
- **Event-sourced + snapshot + provenance** twin (events = what happened, snapshots = current state, files =
  raw evidence, provenance = why we believe it) MATCHES STEWIE's existing `TwinStore` (hash-chained,
  append-only, provenance-mandatory, byte-exact rebuild) + `terrain_memory` (snapshots) + `cadence.py`/
  `backup.py`. So this is an UPGRADE PATH for the existing store, not a greenfield need.

## The one recurring correction: PostGIS is a persistence/query LAYER, NOT the authority

This is the THIRD time a data store has been proposed for the authority slot (ArcGIS → GeoLibre → PostGIS).
The answer is the same each time: **STEWIE's authority is the conserved-physics world model** (mass-conserving
excavation + the hash-chained event log). PostGIS has no concept of mass conservation, provenance chaining, or
the excavation physics that MUTATES the world — so it cannot be the source of truth for what the world IS.

Correct framing: **the conserved model decides; Postgres/PostGIS DURABLY STORES the events + a queryable
PROJECTION of the interpreted state.** The world mutates through the physics authority path (never a direct DB
write); the DB is the durable, indexed, queryable record of that authority. That preserves the conservation +
provenance guarantees the dissertation depends on, while adding the query/durability Postgres is good at. Their
own "store interpreted products in PostGIS, references to raw in object store" is precisely this projection
layer — just not the authority.

## Grounding cautions

1. **Infra scale vs the dissertation.** The full stack (Postgres + PostGIS + MCAP + object store + 3D Tiles)
   is production / multi-robot scale. For ARGUS (single articulated rover), the current **file-based event
   store + DuckDB** is very likely sufficient — and DuckDB/GeoParquet analytics is ALREADY in the GeoLibre
   plan (DW lane), rosbags is already in the runtime venv (the MCAP leg). Add Postgres/PostGIS when the
   file-store durability limits (§6.2 W-1..W-4) actually bite, not before. Don't stand up a database cluster
   to run a single-rover experiment.
2. **The schema encodes the capability-fleet** (`assets.asset`, `capabilities.asset_capability`, multi-asset
   assignment) — that is the heterogeneous-fleet generalization marked post-dissertation in
   `packaging_strategy.md §9`. The schema is right for the 10-year vision, oversized for ARGUS.
3. **CRS: `GEOMETRY(..., 4978)` is EARTH (WGS84 geocentric).** For lunar work use a deliberate lunar body
   frame (an IAU Moon SRID, e.g. IAU_2015:30100, or a documented project-local metric frame). Same recurring
   lunar-CRS caution as the map layer — PostGIS, like the other Earth-GIS tools, defaults to Earth. Aaron's own
   note ("use a planetary CRS deliberately") is correct; make it concrete by not shipping `4978` for the Moon.

## Migration path (when it is time)

Keep the conserved-physics model as the authority. Add persistence in the order the file store fails you:
1. DuckDB + GeoParquet for analytics/snapshots (already planned, DW lane) — do first, cheap.
2. MCAP/rosbag2 + object storage for raw telemetry/blobs (rosbags already present) — reference by URI.
3. PostgreSQL + PostGIS as the durable event store + queryable projection — WHEN durability/query needs
   (W-1..W-4, multi-client, complex spatial queries) actually arrive. Mirror `TwinStore` events into it; never
   make it the authority.
4. 3D Tiles/glTF/USD as viz/asset streaming — pairs with the GL lane (deck.gl `Tile3DLayer`).

Status: recorded design (not built). The single-rover dissertation does not require the DB cluster; the
conserved model + DuckDB carries ARGUS. This is the fleet/production-scale persistence plan.

## World-state semantics — branched, event-sourced, provenance-gated twin (2026-07-03)

Aaron's full data-model cascade (truth semantics + multiple worlds/branches + diff/merge + event-sourcing +
query views), consolidated. This is "git for world state" — a strong, correct model for a scientific twin.

### Truth model + branches
- Schemas carry epistemic status: `world.*` = accepted truth · `perception.*` = observation (not truth yet) ·
  `physics.*` = prediction/estimate · `sim.*` = rehearsed future · `missions.*` = intent/execution ·
  `reconcile.*` = comparison/update · `provenance.*` = evidence chain.
- Multiple competing, time-indexed worlds as BRANCHES: actual (accepted) · observed (sensor) · predicted
  (physics/planner) · simulated (rehearsal) · design (intended construction target) · archived (history), +
  what_if/replay. `world.world_branch` (+ parent, base_snapshot) + `twins.entity_state` (branch-scoped,
  valid_from/valid_to, confidence, provenance). Answers: what did we believe before the dig? what did the sim
  predict? what did the rover observe? which branch became truth?

### Diff / merge / promotion
- `reconcile.world_diff` (geom/numeric/semantic delta + confidence) · `merge_proposal` (type, risk, proposed
  changes) · `merge_decision` (accept/reject/override + reviewer + rationale). Types: accept_observation /
  accept_simulation_result / accept_construction_change / reject_as_sensor_noise / reject_as_model_error /
  manual_override.
- INVARIANT (correct, load-bearing): nothing becomes accepted truth without {source branch, target branch,
  diff, confidence, provenance, merge decision}. This is what makes it a scientific twin, not a 3D dashboard.

### Event sourcing + snapshots
- `twins.event_log` (branch-scoped typed events + payload + provenance) → state = initial snapshot + event
  stream + merge decisions. Snapshot before mission / after each task / after major terrain change / after
  reconciliation / before a publishable experiment. Enables replay-from-t0, predicted-vs-actual audit,
  rebuild-figures-from-events, roll-back-a-bad-merge.

### Query discipline
Tables preserve evidence · views serve applications (`current_terrain`, `latest_robot_state`,
`active_task_board`, `current_traversability`, `open_merge_proposals`) · materialized views serve performance
(traversability raster cache). Auditable + fast.

### ★ Alignment — STEWIE already has ~half of this
- conserved authority vs observed twin (§6.2 two channels) = the actual vs observed branches.
- `TwinStore` (hash-chained, append-only, provenance-mandatory, byte-exact rebuild) = `twins.event_log` +
  provenance — already event-sourced.
- `cadence.py` / `backup.py` = the snapshot policy. RS-04 replay loop (predict→execute→reconcile) = the
  diff/merge/promotion loop. `BeliefState` + TW-05 uncertainty = `world.world_belief`.
- So this is a FORMALIZATION + GENERALIZATION (single observed-twin → N named branches; the reconcile loop →
  explicit diff/merge/decision rows), not greenfield. The genuinely NEW concept is the promotable BRANCH SET
  (predicted/simulated/design/what_if) — the git-for-world-state upgrade.

### ★ One correction to the merge semantics
Promotion to the `actual` branch that CHANGES TERRAIN must pass the CONSERVED-MASS gate — the physics
authority, not a bare DB write. A `merge_decision` of type `accept_construction_change` must assert mass
conservation (Δmass balances) BEFORE the actual branch updates. The DB records the promotion; the physics
validates it. That keeps the conserved authority intact within the branch model — add a conservation check as
a merge precondition for terrain-mutating merges.

### Scope
Production / fleet-scale twin data model (branches, diff/merge, ~30 tables, materialized views). For
single-rover ARGUS, the existing file-based `TwinStore` + reconcile loop already delivers the essential parts
(event-sourced, provenance, reconciliation, replay). Adopt the Postgres branched twin when multi-branch /
multi-client / complex-spatial-query needs actually arrive — the model is correct and worth keeping as the
target.

## Beyond storage: services, specs, tiers, and the knowledge/reasoning layers (2026-07-03)

Aaron's continued cascade — API/service boundaries · message contracts (`stewie-specs`) · storage tiers · and
Layers 11-20 (knowledge graph, semantic fusion, relationships, intent, decision history, explanation,
prediction, construction state machine, fleet reasoning, mission memory) + the 4-layer split (World State /
Knowledge / Reasoning / Experience). Consolidated; correct where it lands, flagged where it drifts.

### Services / specs / tiers — sound, mostly already-decided
- **Service boundaries** (world/asset/mission/physics/perception/reconcile/file services; ONLY services mutate
  truth tables; tools produce observations/predictions/proposals). CORRECT — the authority-gating restated at
  the service layer; matches STEWIE's existing router boundary. Right pattern.
- **Message contracts / `stewie-specs`** (JSON Schema + proto + ROS `.msg`; shared IDs; a common result shape
  with units + confidence + provenance). This is the `stewie-specs` package already DECIDED DEFERRED
  (`packaging_strategy.md §7`) — pydantic exports the JSON Schema for free until a non-Python consumer needs
  hand-authored proto/msg. BUT the **shared-result-shape** `{result_id, backend, value, units, confidence,
  provenance_id}` is good and worth adopting in `forge` NOW — cheap, and it is the citable output format.
- **Storage tiers** (Tier0 PostGIS hot / Tier1 DuckDB+GeoParquet analytics / Tier2 MCAP+rosbag raw / Tier3
  3DTiles+glTF+USD assets / Tier4 Zenodo/OSF archive) + a `files.artifact` reference table. CORRECT, matches
  the hybrid store; the tiering is the right way to not overload Postgres.

### Layers 11-20 — mostly OTHER projects, not STEWIE's twin
Strong ideas, but several are NOT new and NOT STEWIE — they are Aaron's OTHER research lineages, and folding
them into STEWIE's world-state twin blurs project boundaries:
- Knowledge graph + semantic fusion + relationships (11-13) = the `/graphify` skill + T4D knowledge graph.
  Keep it a GRAPH PROJECTION over the world state, not a rewrite of the twin into a graph DB.
- Mission memory / "learning digital twin" (20) = the kymera / T4D memory (Hebbian/forgetting) lineage.
  ★ Memory guardrail (`feedback_intro_frame_broad_applied_ai_vision`): AI-memory is kymera/T4D, NOT robot nav.
  STEWIE's twin stays a WORLD-STATE twin (evidence → reconcile → accepted update); a learning-memory system is
  a SEPARATE project, not an absorption into STEWIE.
- Explanation layer (16) = the PRIOR XAI thesis lineage. Explainable planner decisions are good; they do not
  require STEWIE to re-implement XAI.
- Intent / decision-history / prediction / construction-state-machine / fleet-as-capabilities (14,15,17,18,19)
  ARE STEWIE-appropriate and mostly generalize what exists (Plan IR, the fleet planner, the construction
  lifecycle) — record as future; none needed for ARGUS.

### The 4-layer split IS the right stopping point
World State / Knowledge / Reasoning / Experience is the correct top abstraction — and it says these are
SEPARATE layers, which is exactly why you do NOT design them all into one schema now. Natural place to stop.

### Honest status
This has crossed from a dissertation data model into a decade-scale planetary-autonomy OS that is absorbing
Aaron's whole body of work (graphify/T4D knowledge graph · kymera/T4D memory · XAI explanation · STEWIE nav).
That is a lab / research-program architecture, not a dissertation. NONE of Layers 11-20 is required for ARGUS.
Recorded as the north-star; the dissertation remains ARGUS state estimation on one articulated rover.

## ★ Decision: reject the universal `WorldObject` base class (2026-07-03)

Proposal: make `WorldObject` (uuid/geometry/pose/state/properties/relationships/history/belief/predictions/
capabilities/lifecycle) THE central abstraction, define it rigorously BEFORE implementing more subsystems, and
have every package exchange `WorldObject` instances.

**REJECT the universal base class.** Reasons:
- **God Object / universal-base anti-pattern.** A base that must serve Robot AND Rock AND Task AND Capability
  AND Astronaut becomes a null-field grab-bag (a Rock has no battery; a Task has no pose; a Capability has no
  lifecycle-in-space). "Everything behaves identically" is FALSE commonality — a Task and a Rock share almost
  nothing meaningful.
- **It erodes STEWIE's actual strength.** The precise typed contracts (`WorldState`, `VehicleModel`,
  `BeliefState`, `RegolithVolumeEstimate`, `WorldLayer`, `LayerManifest`) are what make mass-conservation +
  provenance ENFORCEABLE. You cannot enforce mass conservation on a generic `WorldObject`; you enforce it on a
  typed terrain authority.
- **It inverts the build order.** "Define it before implementing more subsystems" is speculative generality —
  the subsystems already exist and work. You FACTOR shared abstractions OUT of working concretes; you do not
  design a universal base up front and retrofit everything to it. STEWIE's working typed code IS the evidence
  that concrete-first produced results.

**ADOPT instead** (keeps ~all the benefit, none of the trap):
- Small shared PROTOCOLS (has-a / implements, not inherit-from-one-base): `Identified` (uuid) · `Located`
  (footprint + CRS) · `Provenanced` (source + confidence) · `Temporal` (valid_from/valid_to). Precise types
  implement only the ones they genuinely have.
- The ~dozen concepts (Body, World, Asset, Capability, Mission, Task, Observation, Prediction, Decision, Event,
  Resource) as DISTINCT, precise shared TYPES in the deferred `stewie-specs` — the common vocabulary packages
  exchange. Interoperability comes from agreeing on shared TYPES + small protocols, NOT from a God class
  everything inherits. That is the coherent semantic backbone the proposal wants, built the way that survives
  contact with real requirements.

### Resolution (2026-07-03): generic in the DB, typed in the code
Aaron moderated the proposal to a generic `world.object` TABLE + typed side-tables joined by `object_id`,
added only "when queried often / when stable" ("generic first · typed when queried · specialized only when
stable"). That is a LEGITIMATE database pattern (class-table inheritance / generic-entity-with-extensions) —
NOT the God Object OOP base class. Accepted, with one distinction held: **generic in the DB row (persistence
convenience), PRECISE in the code contracts.** The Python packages (bodies/forge/ARGUS) still exchange typed
`BodyProfile` / `TerrainCell` / `RegolithVolumeEstimate`, never a generic `WorldObject` — that is what keeps
the mass-conservation + provenance guarantees enforceable. `world.object` + `object_relation` are the flexible
persistence/query backbone; the code stays typed.

Invariants (correct, matching STEWIE's discipline — recorded): every accepted object has provenance · belongs
to a branch · every task names required capabilities · every event has asset+timestamp · every prediction
names its backend · every merge decision records rationale · raw evidence referenced not embedded. Governing
rule (the authority model stated cleanly): **DB constraints protect truth · application logic proposes truth ·
reconciliation accepts truth.** Index/perf rule: generic + GIST/GIN first; view when a join repeats;
materialized view when slow; promote JSONB→typed column when queried constantly. Start flexible, structure
where proven.
