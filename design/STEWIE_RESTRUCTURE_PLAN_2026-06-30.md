# STEWIE Restructure Plan: Honest Subpart Decomposition (2026-06-30)

Evidence-grounded plan for structuring STEWIE into subparts (terramechanics, world model,
digital twin, navigation, planning, backend, frontend). Built from an AST coupling map, the
graphify state-graph, six fan-out dimension agents, and the PRD's own target architecture.
No code moved. No repos created. Publicness/naming deferred per Aaron's instruction.

## 0. Bottom line

STEWIE is **not a monolith to break up**. It is already a PRD-defined **L0 to L7 layered system**
with subsystem packages (`stewie`, `dart`, `lode`, `leap`, `forge`) declared in `pyproject.toml`,
shipped as one distribution, masked by a flat `stewie.*` namespace. The dependency graph is a
**near-clean DAG**, not spaghetti: the raw "104-edge stewie<->lode cycle" and "48-edge stewie<->dart
cycle" are namespace artifacts, not real import cycles (the substrate packages import their consumers
back **zero** times, grep-verified).

So the work is a **refinement of an architecture that already exists**, in three moves:
1. Make the existing layers explicit and **machine-enforced** (there is no import-linter today).
2. Fix a small, confirmed set of real upward-edge violations.
3. Spin out the one genuinely reusable bottom layer, **terramechanics**, as a standalone open
   library (a lunar analogue of the Groundhog geotechnical library).

Hard invariant to preserve: the PRD's **conserved single-authority** rule. `stewie/physics` +
`stewie/twin` are ONE authority by design ("never split rigid-body authority across two engines").
The "digital twin" and "world model" may become clean internal modules, but **not two separate
authoritative packages**.

## 1. Evidence base

- **AST coupling map** (non-test imports): packages `stewie` (153 files), `dart` (76), `lode` (41),
  `leap` (8), `forge` (2). stewie submodules: `server` (51), `physics` (20), `bridge` (18),
  `specs` (15), `eval` (13), `twin` (11), `terrain` (10), `envs` (5), `contracts` (3), `sensors` (2),
  `runtime` (2), `godot` (2).
- **graphify state-graph** (`graphify-out/graph.json`): state clusters into world/terrain, rover/twin,
  executive/planning communities plus the INT-* interaction sequence.
- **arcgis parity sidecar**: ArcGIS is an export target + benchmark, never an imported dependency.
- **PRD.md**: §6 target architecture (L0 to L7), §6.1 nine single-source runtime artifacts (views not
  recomputations), §21 conserved kernel has zero upward imports, §16.1 DART/LODE/LEAP/FORGE bound to
  outcomes (perception / operations / earthmoving / infrastructure).

## 2. The layer map (subpart <-> code <-> separability)

| PRD layer | Subpart | Code home | Separability | Verdict |
|---|---|---|---|---|
| L0 | contracts | `stewie/contracts` (3) | shared schema base | keep central, both sides consume |
| L1 | **terramechanics** | constitutive core in `stewie/physics` (`terramechanics`, `sinkage`, `slip`, `material`) + `forge/bearing` + params `stewie/specs` (`constants`, `bodies`) | **CLEAN** (near-leaf: numpy + specs only) | **extract as standalone library** |
| L1.5 | conserved authority | `stewie/physics/column_state` (+ `sandpile`, `rover`, `drive`, `worksite`, `refinement`, `quadtree`) | stays in STEWIE | ONE authority, do not split |
| L2 to L3 | **world model + digital twin** | `stewie/twin` (6 WM + 3 sim), `terrain` (9), `godot` (2), `sensors` (1), `bridge` (18 ROS2) | MODERATE, interface-mediated | **one package, two internal modules** |
| L4 | **navigation (ARGUS)** | `dart` (76) | near-CLEAN | own package after cycle fixes |
| L5 to L6 | **planning** | `lode` (41) incl `gis_export` | CLEAN DAG once substrate sits below it | package, lower priority |
| L7 | **backend** | `stewie/server` (51, FastAPI, 32 routers, ~137 endpoints) | umbrella API, convergence point | stays central |
| L7 | **frontend** | `server/index.html` + `web/cockpit.js` + `cesium/` + `desktop/` Electron | **CLEAN** (zero Python coupling, REST + SSE) | extract as static bundle |
| n/a | RL / challenge | `leap` (8) + `stewie/envs` (5) | clean leaf | package or keep |
| n/a | forge | `forge` (2) | vestigial (1 real model) | **FOLD into terramechanics, delete namespace** |

## 3. Real violations (the only true blockers)

There is **no import-linter** wired today, so the PRD's "upward imports forbidden" is documented but
unenforced. Confirmed upward/cycle edges (all isolated, mostly lazy):

1. `dart/render_traverse.py` <-> `stewie/godot/articulation_bridge.py` (tight cycle; the bridge imports
   `dart.articulated_parallax`/`articulated_shadow`, render_traverse imports the bridge).
2. `dart/integrated_slam.py:117` + `dart/mono_depth.py:156` -> `stewie.eval` (lazy).
3. `dart/camera_rig.py:114` -> `stewie.bridge.sensor_io` (lazy upward).
4. `stewie/physics/worksite.py:29-31` -> `stewie.twin.io_fields` + `stewie.terrain` (the one
   physics-core upward reach; caused by `io_fields` being misfiled under `twin/`).

To VERIFY, not assumed: the PRD lists **ARCH-1 = dart imports lode**, but `grep` of `dart/*.py` shows
**no lode import** in current source. Treat ARCH-1 as likely already fixed or stale; Phase 0 replaces
this guesswork with a tool that reports the true set.

Misfiled files (packaging, not logic): `stewie/twin/io_fields.py`, `proprioception.py`,
`runtime_packet.py` are sim/sensor code sitting under the world-model `twin/` directory.

## 4. Recommendation

**One STEWIE monorepo with enforced layer-packages, plus ONE spun-out open library (terramechanics).**
Not three separate repos.

Why:
- The **conserved-authority invariant** forbids splitting world-model from digital-twin into two
  authorities. They stay one kernel.
- **terramechanics is the only clean, general, reusable bottom layer.** It is the OSS/JOSS/portfolio
  showpiece and doubles as the GMRO "calibrated regolith asset." It earns its own repo; nothing else
  clearly does yet.
- Three repos means 3x CI/docs/release for a solo maintainer, pre-proposal, before the seams are clean.
- A monorepo with explicit, import-linter-enforced layer packages gives the "multiple projects"
  legibility without the maintenance multiplier. This matches the PRD's single-distribution intent.

Deferred (only when a concrete need pulls): promote `dart` (ARGUS) to its own repo (it is the
dissertation artifact) after the cycle fixes; separate world-model/twin distributables.

## 5. Atomic execution plan

Each step is independently testable. Gate after every phase: full test suite green vs the captured
baseline, and the import-linter contract passing.

### Phase 0: make the layering executable (no code moved)
- **0.1** Add `import-linter` (grimp) to `[dev]` extras + a `.importlinter` contract encoding L0..L7
  (contracts < terramechanics < physics-authority < world-model/twin < navigation < planning < server).
- **0.2** Run it once. Record the **actual** current violation set as the baseline (this supersedes the
  PRD's hand-maintained ARCH-* list). Wire it into `ci.yml` as non-blocking first, blocking after Phase 1.

### Phase 1: fix the confirmed violations (one commit each, test after each)
- **1.1** Break `render_traverse <-> godot.articulation_bridge`: inject the localizer via a `Protocol`
  callback, or hoist `render_traverse.py` into an integration layer above both.
- **1.2** Reverse `dart -> stewie.eval`: pass baselines/depth in as data, or move `depth_truth` to a
  shared contracts layer.
- **1.3** Move `sensor_io` to a shared IO contract (or inject) so `camera_rig` stops importing
  `stewie.bridge`.
- **1.4** Relocate `stewie/twin/io_fields.py` to a sim/IO module so `physics/worksite.py` no longer
  reaches up into `twin`.
- **Gate:** import-linter clean; flip it to blocking in CI.

### Phase 2: packaging hygiene (no logic change)
- **2.1** Move `io_fields.py`, `proprioception.py`, `runtime_packet.py` out of `twin/` into a
  sim/twin-runtime module, so `twin/` is a pure world-model store.
- **2.2** Fold `forge/bearing.py` into the terramechanics core as its bearing-capacity member; update
  the one consumer (`lode/planner_acceptance.py`); delete the `forge` namespace.

### Phase 3: extract the terramechanics library (the portfolio win)
- **3.1** New package skeleton modeled on Groundhog: `pyproject`, MIT license, docs scaffold, tests dir,
  JOSS `paper.md` stub. (Name held per Aaron.)
- **3.2** Move the constitutive core: `terramechanics.py`, `sinkage.py`, `slip.py`, `material.py`,
  `bearing.py`, + the provenance-tagged param library (`constants.py`, `bodies.py` regolith subset).
- **3.3** Freeze a Groundhog-style public API (`TerramechanicsParams`, `bekker_pressure_sinkage`,
  `wheel_static_sinkage`, slip, bearing, param accessors with `[CALIB]/[UNKNOWN]` tags intact).
- **3.4** STEWIE depends on the new library (replace `stewie.physics.terramechanics` imports).
- **3.5** Education-first docs, one worked example, honest limitations section (Bekker lunar moduli are
  Apollo-era fits pending a low-g re-fit; the JSC/BP-1 reconciliation is deferred to a PyChrono sweep).
- **Gate:** terramechanics tests green standalone; STEWIE tests green using it as a dependency.

### Phase 4: explicit internal layer packages + frontend bundle
- **4.1** Promote the layers to named internal packages (contracts / worldmodel / twin-runtime /
  navigation / planning / server / rl), import-linter-enforced.
- **4.2** Extract the frontend (`index.html` + `web/` + `cesium/`) as a static bundle package documented
  as a REST + SSE client; `desktop/` already treats it as an opaque served app.

### Phase 5 (deferred, decision-gated)
- **5.1** Promote `dart` (ARGUS) to its own repo. Note: the current `projects/argus/code` is a vendored
  snapshot that copies stewie in (it has drifted, 18 files differ), not a real extraction.
- **5.2** Separate world-model/twin distributables, only if a concrete external consumer appears. Keep
  one authority regardless.

## 6. Invariants to preserve (do not violate while restructuring)

- **Conserved single-authority**: `physics` + `twin` stay one kernel; terrain mutation stays bound to
  the twin.
- **Downward-only imports**: enforced by the Phase 0 contract; fix violations, never add them.
- **No synthetic data**: params stay provenance-tagged real values (BP-1 IPEx simulant of record,
  GRC-3, Apollo Mitchell/Costes, Lyasko 2010). Microgravity bodies stay tagged out-of-regime, not
  fabricated.
- **Kernel high fan-in is healthy**: `specs` (fan-in ~96) and `physics` (~74) are meant to be depended
  on widely. Do not "decouple" them.

## 7. Open decisions for Aaron (held until plan review)

1. Structure: confirm monorepo-with-enforced-layers + one terramechanics library (vs 3 repos).
2. terramechanics: name, license (MIT assumed), public-from-day-one vs private-until-polished.
3. ARGUS (dart): own repo now, or stay an internal package until after the proposal.
4. Sequencing vs the August proposal: do Phases 0 to 3 now, or hold code churn until after the defense.
