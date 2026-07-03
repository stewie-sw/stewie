# PRD reorganization spec + conversation completeness audit (2026-07-03)

Drives the platform-first PRD rebuild (conferred with Codex). Captures (A) the reorg requirements from Aaron's
directives, (B) the proposed phase structure, (C) a completeness audit of the ~3-hour planning session so no
aspect is lost.

## A. Reorg requirements (Aaron's directives)

1. **PLATFORM-FIRST.** The planetary digital engineering platform is the deliverable; ARGUS is a reference
   component inside it. Drop all dissertation-centric framing ("for the dissertation," "foreground ARGUS");
   "post-dissertation" → "later-stage platform scope."
2. **FAN-OUT OPTIMIZED.** Rows organized so independent agents build in parallel WITHOUT file collision —
   lanes on DISJOINT file sets; every actionable row carries a `FANOUT_SPECS` brief (`- files:` ≥1 real path,
   `- test_target:`). Mark which rows are parallel-safe vs. which serialize on a dependency edge.
3. **PHASES + SUB-PHASES.** Backlog = Phase → Sub-phase → atomic rows (not one flat matrix).
4. **LOOP-ENGINEERING OPTIMIZED.** Each atomic row = one `/loop`-buildable unit: screen live impl → TDD
   failing test → implement → FULL gate (req_trace + assessment + check_deps + row test + ruff + mypy + node)
   → flip glyph → commit. **Strangler-fig: the working system stays green at every step; restructure on a
   branch.**
5. **SPLIT INTO SMALLER DOCS (token-saving).** Replace the 1951-line monolith `PRD.md` with `PRD/index.md`
   (thin: phase list + lane map + pointers) + `PRD/phase-<N>.md` per phase (that phase's rows). Update
   `scripts/req_trace.py` + `scripts/gen_program_snapshot.py` to read the split (glob `PRD/phase-*.md`). Agents
   /loops load ONLY the relevant phase doc — big context/token saving.
6. **PROGRAM BOARD MOBILE-FRIENDLY.** `/program` (`program.html` + `program_board.js`) responsive at phone
   widths (reuse the cockpit mobile arc: ≥44px touch targets, single-column stack, no horizontal overflow,
   filter deck collapses). Own row: **MG-04**.

## B. Proposed phase structure (platform-first, loop-ready)

| Phase | Sub-phases | Parallelism |
|---|---|---|
| **P0 Baseline + reframe** | commit architecture baseline (branch); platform-first reframe; split PRD into docs; mobile board (MG-04) | meta, mostly serial |
| **P1 Extension seams** | PX (PhysicsBackend protocol + tier2 adapter) · BD (BodyProfile registry) · break 3 dep edges (invert bodies→forge → move composing loops/routers to apps → pull dart/leap-free geotech into forge) | edge-breaks SERIALIZE; PX/BD tests parallel after |
| **P2 Packaging** | uv/hatch workspace · publish `stewie-bodies` · publish `stewie-forge` | after P1 |
| **P3 Demo 001** | seed → predict → rehearse → execute → reconcile → snapshot → artifact bundle, from existing code | after P1 (needs PX/BD); parallel to P4 |
| **P4 Frontend context-first cockpit** | GeoLibre 2D React (FS-16 Context→store) · workspaces=panes · query bar (DW) · Tauri shell · mobile | parallel to P1-P3 (disjoint files: frontend) |
| **P5 Later-stage platform** | named branches · capability-fleet · PostGIS · multi-engine IDE · AI copilot · graph views | P2/P3 priority, sequenced last |

Codex's proposal (`scratchpad/codex_prd_reorg.md`) + this spec are synthesized into the row-level breakdown.

## C. Completeness audit — every session aspect, coverage, gaps filled

| # | Topic | Captured in | Status |
|---|---|---|---|
| 1 | GeoLibre frontend rebuild + 2D/DEM/three3d | geolibre_migration_assessment, geolibre_rewrite_plan, frontend_review | ✅ |
| 2 | ArcGIS/Unity/Unreal/USD/PostGIS/3D-tiles stack | **filled below (C.3)** | 🟨→filled |
| 3 | GeoLibre-over-ArcGIS (GIS-as-boundary not authority) | data_architecture, ARCHITECTURE decisions | ✅ |
| 4 | PlanetGroundhog / geotech / earth-pressure gap | packaging_strategy, interface_contracts | ✅ |
| 5 | Packaging (monorepo, bodies/forge, 3 edges, workspace, extras, CI, version ladder) | packaging_strategy §7 | ✅ |
| 6 | TW-11 traversal-compaction layer | traversal_compaction_layer + PRD TW-11 + task#12 | ✅ |
| 7 | Publication tracks + chapters + core claim | packaging_strategy §8 (reframe platform-first) | ✅ |
| 8 | Research ecosystem / datasets / benchmarks / stewie-specs | packaging_strategy §8-9 | ✅ |
| 9 | Website subdomains | packaging_strategy §9 | ✅ |
| 10 | Mission Ops Center UI / capability-fleet | packaging_strategy §9 + frontend_review | ✅ |
| 11 | Hybrid DB (PostGIS/DuckDB/MCAP/tiers) + SQL schema | data_architecture | ✅ |
| 12 | World-state semantics + branches + diff/merge + event-sourcing + views | data_architecture | ✅ |
| 13 | Services + message-contracts + storage tiers | data_architecture §services | ✅ |
| 14 | Layers 11-20 (knowledge-graph/intent/explanation/memory) + project guardrails | data_architecture §beyond-storage | ✅ |
| 15 | WorldObject universal base / metamodel-first | data_architecture (REJECTED) | ✅ |
| 16 | Generic world.object table + typed side-tables + invariants | data_architecture §resolution | ✅ |
| 17 | Domain model / entity ownership / lifecycle / relationship vocabulary | **filled below (C.1)** | 🟨→filled |
| 18 | Mission abstraction (pipeline, world-update txn, asset taxonomy, resources, products, metrics) | **filled below (C.2)** | 🟨→filled |
| 19 | ADRs (25) / decisions register | **filled below (C.4)** | 🟨→filled |
| 20 | Control loops / engines / state machines / four primitives / graph-native | ARCHITECTURE conceptual model | ✅ |
| 21 | Inference-engine frame (state inference engine; ARGUS = estimator) | ARCHITECTURE §inference | ✅ |
| 22 | Frontend: question-centric / Planetary IDE / workspaces / context-first / six primitives | frontend_review | ✅ |
| 23 | Language/tech stack (Python/Rust/C++/TS polyglot) | frontend_review §language | ✅ |
| 24 | Backend + frontend architectural reviews | the two review docs | ✅ |
| 25 | Demo 001 full spec (seed/txn/API/UI/artifacts) | task#14 (full spec) | ✅ |
| 26 | Reorg: phases/subphases/loop/smaller-docs/mobile-board | this doc §A-B | ✅ |

### C.1 Domain entity vocabulary (grounded to the 45 existing contracts — reference, not spec-first)
Entities already exist as typed contracts; ownership + lifecycle documented for the reorg (NOT to build before code):
- Body/RegolithProfile → `stewie-bodies` (BD). WorldObject → the `WorldState`/`WorldLayer` family (world-svc).
  Asset → `VehicleState`/VehicleModel (asset-svc). Mission → `MissionIntent`/`MissionExecutive`. Task →
  `Objective`/`CompiledOrder`. Observation → `ObservedMapUpdate`/`Depth/Visual/EphemerisObservation`.
  Prediction → `PlanResult`/`CostmapSnapshot`/`RegolithVolumeEstimate`. Decision → `CommandEligibility`/
  `ExecutiveState`. Event → `ExecutionEvent`. Resource → `ResourceReservation`. Provenance →
  `Provenance`/`ProvenancedValue`. Constraint/Factor → `Constraint`/`NavFactor`. Belief → `BeliefState`.
- Lifecycles (for the reorg's state-machine rows): Task proposed→planned→assigned→rehearsed→executing→
  completed→reconciled→archived; WorldObject predicted→observed→accepted→verified→retired; ConstructionFeature
  designed→surveyed→under_construction→as_built→inspected→operational→maintenance→retired.
- Relationship vocabulary: provides/requires/observes/supports/blocks/modifies/creates/depends_on/located_in/
  derived_from/conflicts_with/reconciles/assigned_to/validated_by.
- Write-authority (service ownership): only the owning service mutates its aggregate; everyone else reads.
  Grounded rule already in code: routers are the write boundary; the conserved authority is the sole terrain
  mutator.

### C.2 Mission abstraction (grounded)
Pipeline Mission→Objectives→Tasks→Capabilities→Assignment→Rehearsal→Execution→Observation→Reconciliation→
WorldUpdate→Report = the existing Plan IR + RS-04 loop. **World-update transaction = {Observation, Prediction,
Decision, Accepted-Update}, never skip one** — matches the reconcile+provenance discipline. Asset taxonomy
Mobile/Static/Virtual + Resource accounting (battery/time/bandwidth/wear/thermal/safety) + Construction
products (berm/road/pad/pit/stockpile) + Evaluation metrics (localization error/mapping/volume/energy/slip/
duration/success/prediction-accuracy) — all later-stage platform rows (P5), except metrics which Demo 001 (P3)
seeds.

### C.3 ArcGIS/game-engine stack verdict
Do NOT rebuild around ArcGIS or Unity/Unreal/USD/PostGIS as the platform. GIS is a boundary; the conserved
model is the authority. Borrow at seams only: GeoParquet/COG/PMTiles/3D-Tiles formats (some built via BA-11),
DuckDB-WASM (DW lane), deck.gl `TerrainLayer` for 3D relief. Unity/Unreal/ArcGIS-SDK conflict with the
CC0/open + lean-web posture. USD = later asset-interchange. (This closes topic #2.)

### C.4 Decisions register (the "ADRs", accept/reject)
0001 REJECT universal WorldObject base class (God Object) · 0002 ACCEPT monorepo workspace (not N repos) ·
0003 GIS/PostGIS = persistence/boundary, NOT authority · 0004 ACCEPT event-sourcing (already = TwinStore) ·
0005 branches = later-stage · 0006 ACCEPT provenance-mandatory (already) · 0007 capability-fleet = later ·
0008 ACCEPT stewie-forge public (PlanetGroundhog) · 0009 ACCEPT stewie-bodies public · 0010 world-update via
reconciliation (already RS-04) · 0011 physics analytical-first, Chrono optional/gated · 0012 GeoLibre 2D web
cockpit; Godot = render engine not shell · 0013 REJECT metamodel-first (factor from concretes) · 0014 unify at
SEMANTIC not algorithmic level · 0015 two-language (Python+TS) until profiled need · 0016 file-store now,
Postgres later · 0017 platform-first (ARGUS = component) · 0018 split PRD into phase docs (token-saving) ·
0019 program board mobile-friendly.

## Confirmation
Every topic from the session is captured or filled above. Nothing from the ~24 planning layers is lost; the
reorg (phases/sub-phases/fan-out/loop/smaller-docs) proceeds from this + Codex's proposal.
