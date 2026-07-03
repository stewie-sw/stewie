# STEWIE backend architectural review — planning session vs. reality (2026-07-03)

**Scope:** backend only (frontend is a separate follow-up review). Compares the ~3-hour architecture planning
session (~24 conceptual layers: GeoLibre, hybrid persistence, branched twin, capability-fleet, engines/
services, four-primitive metamodel, inference-engine frame, packaging) against the ACTUAL backend, verified in
code 2026-07-03. Method: two grounded surveys of subsystems, contracts, runtime spine, twin/persistence, API,
physics.

## Headline finding

**The backend already implements ~80–85% of the proposed architecture.** The session was, in large part, a
re-derivation — in fresh vocabulary — of a system that already exists in typed, tested code. Two proposals are
genuinely new (both post-dissertation). Two are correctly rejected. One frame (inference engine) is the honest
thesis and it centers the dissertation.

## What the backend actually is (verified)

- **Subsystems (monorepo modules):** `stewie` (core: contracts/runtime/twin/server/physics/specs, 169 mods),
  `dart` (perception/nav/autonomy, 81), `lode` (planning/mapping, 44), `leap` (localization/estimation, 9),
  `forge` (geotech, 2). Clean-interfaced logical modules — i.e. the "engines" already exist as modules.
- **45 typed domain contracts** (`stewie/contracts/*`): `WorldState`, `WorldLayer`, `LayerManifest`,
  `VehicleState`, `BeliefState`, `MissionIntent`, `MissionExecutive`, `Objective`, `CompiledOrder`,
  `ObservedMapUpdate`, `DepthObservation`, `VisualHazardObservation`, `EphemerisObservation`, `PlanResult`,
  `CostmapSnapshot`, `RegolithVolumeEstimate`, `CommandEligibility`, `ExecutiveState`, `ExecutionEvent`,
  `ResourceReservation`, `Provenance`, `ProvenancedValue`, `NavFactor`, `ConstructionSkill`, `HazardDetection`,
  `KeepOutRegion`, `SignedRevision`, `LocalizationFix`, `PerceptionState`, `FleetState`, … This IS the "canonical
  domain model" the session kept proposing to define first.
- **Runtime spine:** RS-01…06 (`stewie/runtime/`: `nav_loop`, `replay_loop`, `process`, `route_impact`) —
  observe → plan → eligibility → world transaction, with `replay_loop` the deterministic end-to-end.
- **World model / twin:** `terrain_memory`, `world_model`, `versioned`, `backup`, `cadence`, `envelope`,
  `runtime_packet`. Persistence = **fsync'd append-only journal (124 refs) + npz snapshots** + json. Hash-chained,
  provenance-mandatory, byte-exact replay. Durability gaps W-1/W-2 CLOSED (fsync journal + cadence retention).
- **Belief vs truth:** `BeliefState` is explicitly DISTINCT from sim truth / telemetry, with uncertainty +
  confidence∈[0,1]. The probabilistic-robotics stance the session proposed is already the design.
- **Reconcile loop:** `replay_loop` + `lode/resync` + `RegolithVolumeEstimate` (predicted-vs-observed volume +
  confidence) + the two-channel conserved-authority / observed-twin split.
- **Physics:** `stewie/physics/` (bearing, sinkage, slip, stability, compaction/`column_state`, excavation,
  terramechanics, drive, rover, sandpile, rassor_mass_model) + `forge/bearing`. Body-aware via
  `bodies.py` (`Body`/`params_for_body`, regime-flagged, provenance-tagged).
- **API:** 36 routers / 140 routes, already grouped into the proposed service domains (world/twin,
  assets/fleet/rc, missions/plan/siteplan/executive, perception/nav/dem/solar/layers/ogc/gis_export/tiles,
  construction, models/evidence/program/figures, + auth/admin/session infra).
- **Digital thread:** `req_trace.py` (`[REQ:ID]`→citing test→evidence) + PRD §7 matrix + `/program` board +
  hash-anchored evidence bundles. Running today.

## Mapping: proposed concept → existing backend → status

| Proposed | Exists as | Status |
|---|---|---|
| Canonical entities (WorldObject/Asset/Mission/Task/Observation/Prediction/Decision/Event/Resource/Provenance) | the 45 typed contracts above | ✅ EXISTS |
| Event-sourced immutable world (events + snapshots + replay) | fsync journal + npz snapshots + `versioned` + `terrain_memory` | ✅ EXISTS (single-timeline) |
| World stores belief, not truth | `BeliefState` distinct from truth + uncertainty/confidence + observed twin | ✅ EXISTS |
| Factor graph (constraints + evidence + confidence) | `NavFactor` contract + estimator belief | 🟨 SEED (full unification = ARGUS's job) |
| Inference / reconcile loop (predict→observe→reconcile) | `replay_loop` + `lode/resync` + `RegolithVolumeEstimate` | ✅ EXISTS |
| "Every algorithm is an estimator" (common semantic contract) | BeliefState/PerceptionState/LocalizationFix + physics predictions | 🟨 IMPLICIT (semantic-level, by design — not one interface) |
| Service domains (World/Asset/Mission/Physics/Perception/Knowledge) | the 36 routers, grouped | ✅ EXISTS |
| Engines as logical modules | dart/lode/leap/forge/stewie | ✅ EXISTS |
| PlanetGroundhog (analytical geotech: bearing/sinkage/slope/excavation/compaction) | `stewie/physics/*` + `forge/bearing` | ✅ EXISTS (needs extraction to `forge`) |
| Body-aware physics / `Planet()` | `bodies.py` `Body`/`params_for_body` (regime-flagged) | ✅ EXISTS (better than sketch) |
| Digital thread / requirements traceability | `req_trace` + evidence bundles + `/program` | ✅ EXISTS (running) |
| Intent as first-class | `MissionIntent` + Plan IR + `Objective` | ✅ EXISTS (named) |
| PhysicsBackend interface (swappable Tier-2/Tier-3) | physics is functions, not a backend | ❌ NEW — PX lane, task #13 |
| BodyProfile registry | `bodies.py` constants, not a registry | 🟨 PARTIAL — BD lane, task #13 |
| Hybrid persistence (PostGIS/DuckDB/MCAP/tiers) | file-based fsync-journal + npz + json | 🟨 file-based SUFFICIENT for single-rover; Postgres = future |
| Named world BRANCHES (actual/sim/what-if promotion) | two-channel conserved/observed only | ❌ NEW — post-dissertation |
| Capability-fleet (Asset/Capability/matrix, multi-robot) | `VehicleState`/`VehicleModel`, no capability model | ❌ NEW — post-dissertation |
| WorldObject universal base class | — | ⛔ REJECTED (God Object; precise contracts win) |
| stewie-metamodel (model-driven, generate implementation) | — | ⛔ REJECTED (abstract-first; factor from concretes) |
| Godot as operator shell | Godot = sensor/render sidecar | ⛔ CONFLICTS with the decided GeoLibre web cockpit |

## Decisions of record (load-bearing)

1. **GIS / DB / ArcGIS / GeoLibre / PostGIS are all boundary/persistence/query layers — never the authority.**
   The conserved-physics world model is the source of truth. (This correction recurred four times.)
2. **Reject the universal `WorldObject` base class and the `stewie-metamodel`-first approach.** Precise typed
   contracts + small protocols; factor abstractions OUT of working concretes, not design-first.
3. **Monorepo workspace; publish only `stewie-bodies` + `stewie-forge`.** DART/LODE/LEAP/core stay internal
   (coupling architectural). Break three edges first (bodies→forge inverted; core↔dart/leap cycle; physics
   imports dart/leap).
4. **Unify at the SEMANTIC level (belief/evidence/confidence/provenance), not the algorithmic level.** forge
   stays deterministic; localization stays factor-graph; planning stays search. (This caution is correct.)
5. **Thesis framing:** *STEWIE is a planetary state inference engine; ARGUS is its state estimator.* Grounded
   in `BeliefState` + `NavFactor` + the reconcile loop — puts the gradeable contribution at the core.

## Genuinely new backend work (honest, prioritized)

**For the dissertation (small, from existing code):**
1. **PX + BD refactor** (task #13) — extract `PhysicsBackend` protocol + `BodyProfile` registry from the
   existing `stewie/physics` + `bodies.py`; break the three edges. Enables `stewie-forge`/`stewie-bodies`.
2. **Demo 001** (task #14) — the vertical slice proving the inference/reconcile loop end-to-end on existing
   code (`RegolithVolumeEstimate` is already the reconcile output). This validates the whole inference-engine
   frame with one run.

**Post-dissertation (real, but not now):**
3. Named world **branches** (actual/sim/what-if + promotion) — generalizes the two-channel twin.
4. **Capability-fleet** model (Asset/Capability/matrix) — generalizes `VehicleModel` to heterogeneous fleets.
5. **PostgreSQL/PostGIS** persistence — adopt when the fsync-journal + DuckDB limits bite (multi-branch /
   multi-client / complex spatial query). Single-rover ARGUS does not need it.

## Honest status

The backend is not a blank slate awaiting a grand architecture — it is a working, typed, tested system that
already realizes most of the proposed vision. The session produced an excellent *articulation* (the
inference-engine thesis especially) + two future generalizations + a packaging/extension plan. The open item
is unchanged and small: **the two extensions (PX/BD) and one vertical slice (Demo 001), both from code that
already runs.** Frontend review to follow.
