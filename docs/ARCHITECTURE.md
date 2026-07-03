# STEWIE architecture — index + honest status (2026-07-03)

This is the governing index over the architecture work done this session — the "System Architecture
Specification" assembled from the documents that already exist, not a new abstraction layer above them. It maps
the seven design levels to the real docs, records the load-bearing decisions, and states honestly what is
designed vs. built.

## The seven levels → where each lives

| Level | Covered by |
|---|---|
| 1. Metamodel (root concepts) | `data_architecture.md` §"reject WorldObject base" — decided AGAINST a universal metamodel; precise types + small protocols instead |
| 2. Domain model (Body, Asset, Mission, …) | `interface_contracts.md` + `packaging_strategy.md` §8 (the ~dozen concepts as distinct types) |
| 3. Information model (schemas, tables) | `data_architecture.md` (hybrid store, branched twin, schema) |
| 4. Service model (APIs, events) | `data_architecture.md` §"services / specs / tiers" |
| 5. Execution model (running system) | `geolibre_rewrite_plan.md` (2D frontend) + the existing backend |
| 6. Experiment model (scenarios, replay) | Demo 001 (task #14) + `packaging_strategy.md` §8 (benchmark track C) |
| 7. Digital engineering (traceability) | ALREADY RUNNING: `req_trace.py` `[REQ:ID]`→test→evidence + the PRD §7 matrix + `/program` board + hash-anchored evidence bundles |

## The document set (all staged, uncommitted)

- **`geolibre_rewrite_plan_2026-07-03.md`** — 2D GeoLibre-style React frontend rewrite (Claude+Codex reconciled); backend stays the sidecar; the two extension seams (PhysicsBackend, BodyProfile); phased strangler roadmap.
- **`packaging_strategy.md`** — monorepo workspace; publish only `stewie-forge` + `stewie-bodies`; the three dependency edges to break; publication tracks + dissertation framing; deferred/post-dissertation scope.
- **`interface_contracts.md`** — the frozen public APIs for the two packages + dependency rules + versioning + test gates.
- **`data_architecture_2026-07-03.md`** — hybrid persistence (PostGIS/DuckDB/MCAP/3D-Tiles/object store); branched, event-sourced, provenance-gated twin; the WorldObject-base rejection + resolution.
- **`traversal_compaction_layer_2026-07-03.md`** — the multipass "traffic" layer (PRD TW-11).
- **`geolibre_migration_assessment_2026-07-03.md`** — the original honest effort assessment.
- **`../PRD.md`** — rewritten §6 architecture + §7.A new lanes (RF/GL/DW/AC/PX/BD/TU/MG) + §10.A roadmap + TW-11.

## Load-bearing decisions (the ones with teeth)

- Frontend rebuilt on GeoLibre-style **2D** stack; **no spherical globe** (defuses lunar-CRS); Cesium's 3D relief maps to deck.gl `TerrainLayer` (DEM + construction stay 3D-capable).
- **GIS is a boundary, never the authority.** ArcGIS / GeoLibre / PostGIS are all persistence/query/interop layers; the **conserved-physics world model is the source of truth** (this correction recurred three times).
- **Monorepo**, not N repos; publish only the two low-coupling citable packages.
- **Reject** the universal `WorldObject` base class; precise typed contracts + small protocols; generic in the DB row, typed in the code.
- The **digital thread already exists** as `req_trace` + evidence bundles — extend it to figures/experiments; don't rebuild it.

## Operational layers (PRD §29 / §30, 2026-07-03)

Two operational layers were specified this session and atomized into tracked §7 rows:

- **Environment-Governed Operations & Control Backend (PRD §29).** Authority is a property of the
  ENVIRONMENT MODE, not a loose admin toggle: six modes (DEV / TRAINING / REHEARSAL / LIVE / REPLAY /
  ARCHIVE) with a per-mode authority matrix over seven flags, centrally enforced so training can never cross
  into live. Twelve bounded backend services, with the ROS2 bridge as the sole real-robot egress;
  `stewie_{dev,training,live,archive}` DB/branch isolation; an 11-role model; an 8-step training-to-live gate
  + a live-execution token; command-safety pipeline invariants; and a reconciliation lifecycle. Atomized as
  the §7.C EG-01..12 lane (EG-12 selects the PX-04 physics backend). Sits at the service level (level 4) with
  digital-engineering accountability (level 7).
- **Mission-Planning Engine (PRD §30).** Planning chooses actions that transform the world, not a path:
  Intent → Tasks → capability match → candidate plans → physics scoring → rehearsal → approval → execution →
  reconciliation → updated world model, over an 8-precondition executability gate and a 12-object typed model
  with 10 UI panels. Atomized as the §7.D MP-05..12 lane (MP-06 ties Demo 001 / task #14). This is the
  execution model (level 5) driving the world engine.

## Conceptual model (the theory layer, 2026-07-03)

Consolidated from the computational-theory inputs (control loops → engines → state machines → four primitives
→ graph-native runtime). This is the metamodel/ontology level (levels 1–2 of the seven), captured as the
theoretical foundation — the part most useful for a systems-architecture paper. Each layer is grounded against
existing code.

### Four primitives
Everything reduces to **Entity** (something that exists) · **State** (all known about an entity at an instant)
· **Transformation** (State(t) → State(t+1)) · **Relationship** (typed edges: uses / depends_on / contains /
blocks / observes / derived_from / validates / requires). Time and space are attributes of State, not special
concepts. GROUNDING: already maps onto STEWIE's typed contracts — `WorldState`/`VehicleState` = State, the
RS-01…08 pipeline steps = Transformations, `LayerManifest` + object relations = Entities+Relationships. A
paper-level articulation of the existing type system, not a rewrite.

### Graph-native / transformation runtime
The platform as one graph: Entities connected by Relationships, holding State, updated by Transformations. The
runtime is a dependency graph — a change marks dirty nodes, recomputes only those, notifies subscribers
(spreadsheet-recalc / reactive). Every Transformation is pure (inputs → outputs, no hidden state), cached by
input-hash, and emits a typed, versioned, provenance-carrying **Derived Product** (Traversability / Localization
/ World-Delta products…). GROUNDING: pure-transformation + typed-product + input-provenance is what forge's
functions + the evidence bundles + `RegolithVolumeEstimate` already do; this names the uniform interface.

### Control loops (cyber-physical view)
Organize by "what loop does this close?" Nested loops at different time scales: controller (ms) → localization
(100 ms) → perception (1 s) → planning (10 s) → mission (min) → construction (hr) → science (day) → learning
(wk). Core loop (OODA-extended): Observe → Interpret → Predict → Decide → **Rehearse** → Execute → Measure →
**Reconcile** → Learn (Rehearse-before + Reconcile-after are the STEWIE additions). GROUNDING: this IS the RS-04
replay loop + the ConOps spine (Plan/Rehearse/Validate/Execute/Report).

### Engines as logical modules (NOT microservices yet)
Domain engines (Planet/World/Physics/Mission/Perception/Knowledge/Learning/Visualization/Workflow) are LOGICAL
modules in the monorepo with clean interfaces — extract to independent services only on demonstrated
deploy/scale need. The World Engine (= TwinStore + scheduler + event system) is the sole authority; everything
else consumes/produces world state. Learning changes TRANSFORMATIONS (models), never the world directly — the
world stays evidence-based. GROUNDING: STEWIE is already a monorepo of clean-interfaced modules
(dart/lode/leap/forge/stewie); this is a view, not a restructure.

### Immutable event model
World = append-only immutable events (source of truth) + derived snapshots (cached queryable views) + branches
(alternate histories) + reconciliation (controlled promotion between branches). "World commits" with
author/evidence/message/snapshot; replay = checkout + replay events. GROUNDING: this is `TwinStore` verbatim
(hash-chained append-only events, snapshot-by-replay, provenance-mandatory) + the branch/diff/merge model in
`data_architecture.md`. Already built at single-branch scale.

### Intent (first-class)
Elevate **Intent** ("why the system acts") alongside Entity/Mission/Capability — the semantic thread from
objective ("landing pad for cargo") to actuator command, making explanation + traceability meaningful.
GROUNDING: this is the Plan IR + mission objectives, named as a root concept.

### ★ Inference-engine frame (the ARGUS-centering unification)
STEWIE as a **planetary state inference engine**: the physical planet has an unknown true state; everything
STEWIE does reduces uncertainty about it. The core loop is inference — Unknown → Observations → Inference →
**Belief** → Prediction → Action → new Observations. Consequences:
- The world stores **belief, not reality**: every WorldObject = Identity + Belief + Evidence + Confidence +
  Alternatives. Probabilistic-robotics stance, not GIS. Observations never become truth directly (hypothesis
  → evidence accumulation → accepted belief).
- **Every algorithm is an estimator** with a common SEMANTIC contract (inputs → belief update → confidence →
  evidence → diagnostics). The world graph generalizes to a **factor graph**: objects connected by
  constraints supported by evidence weighted by confidence — localization, terramechanics, and mission
  constraints are all constraint types in one optimization view.
- Unified abstract form: `Belief(t+1) = Update(Belief(t), Observations, Models, Evidence, Decisions,
  Transformations)`.
- CORRECT caution (keep it): unify at the **semantic** level (belief/evidence/confidence/provenance), NOT the
  algorithmic level — localization uses factor graphs, terramechanics stays deterministic analytical in
  `forge`, planning uses graph search, learned perception uses NNs. Preserve each discipline's machinery.

★ WHY THIS ONE MATTERS: this is the frame that centers the **dissertation**. ARGUS *is* the state estimator at
the heart of a planetary state inference engine; `BeliefState` (already separate from sim truth), TW-05
uncertainty, and the observed twin are the belief layer; the factor-graph view is ARGUS's own SLAM/estimation
formalism. So the honest one-line thesis framing falls out: **"STEWIE is a planetary state inference engine;
ARGUS is its state estimator."** That puts the gradeable contribution at the core of the platform rather than
at its periphery — the most publication-useful sentence in the whole cascade.

## ★ Honest status

- **Restructure phase 1 is now landed on `feat/platform-restructure`** (committed, NOT pushed, NOT deployed; `main` untouched): the import edges are broken (BD-04 / PX-04 / PX-05 / AP-01), the dependency graph is **acyclic**, the uv workspace skeleton is in place (PO-16), and the first package **`stewie-bodies` is extracted** and shimmed (PO-17), verified through the Docker backend image build. See `packaging_strategy.md` §Progress.
- **The rest of the architecture above is still captured plan** (the seven-level map, the data/persistence design, the conceptual/inference-engine frame, the §29/§30 operational layers): design is thorough; those layers are staged, not built.
- **The dissertation is ARGUS**: articulated-rover state estimation on ONE rover. STEWIE / bodies / forge / the whole PDEP vision are supporting, citable infrastructure. Foreground ARGUS.
- **The first real slice is Demo 001** (task #14): one IPEx dig, full loop, from existing tested code (`RegolithVolumeEstimate` is already the reconcile output). It exercises the digital thread end-to-end.
- **The two publishable packages** are `stewie-bodies` (extracted, PO-17) + `stewie-forge` (PO-18, next); publish is Stage 3, after `forge` is out.
- The map is nearly complete; the territory (one running slice, Demo 001) is not yet built. That is the open item.
