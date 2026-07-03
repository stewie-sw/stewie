# STEWIE frontend architectural review — planning session vs. reality (2026-07-03)

**Scope:** frontend / operator experience. Compares the proposed frontend vision (question-centric UI →
Planetary Operations Center → Planetary IDE → workspace model → **context-first** UI) against the ACTUAL
cockpit + the already-staged GeoLibre 2D decision, verified in code 2026-07-03. Platform-first framing (the
platform is the deliverable; ARGUS is a reference component inside it). Companion to
`backend_architectural_review_2026-07-03.md`.

## Headline finding

**The current cockpit already implements ~70–75% of the proposed frontend model** — and the proposal's "final
abstraction," the **Context**, already exists in code as the FS-16 routeable state model. Same pattern as the
backend: the session re-derived, in richer vocabulary, a design the cockpit already has. The genuinely-new
piece is one specific, heavy thing (a multi-engine orchestration shell), and it partially conflicts with the
staged web-2D decision — that conflict is the one real fork to resolve.

## What the frontend actually is (verified)

- **The context-first "Context" already exists**: `cockpit_state.js` (FS-16) is "the cockpit's single
  routeable STATE MODEL — one state object for the selected mission / site / vehicle / body / **time** /
  **mode** / **role** / **workArea** / **selectedEntity** / **source**." That is exactly the proposed
  `Context = {selected, branch, time, workspace, role, mission}`. It's already the design; panes render off it
  (43 `setView`/`renderPane`/`VIEW_PANE` refs).
- **Workspaces already exist as the ConOps panes**: the 13 panes (Plan/Rehearse/Validate/Release/Execute/
  Report + Fleet/Construction/Models/Trainer/admin/settings/system) + the `workArea` axis = "an arrangement of
  tools around a question." Validate already sub-splits Nav/Perception/Solar.
- **Timeline / replay / compare already partial**: `timeline` (12) + `scrub` (8) + `timeS` in state; `replay`
  (10) + `playback` (11, fleet_playback) + `compare` (26) + `reconcile` (2). The time-slider + replay + diff
  widgets exist in seed form.
- **Layer manager exists**: the ArcGIS/TerriaJS-style Contents tree (ordered checkbox layer tree,
  Basemap/Terrain/Sun) driven from `LAYER_ON`/`ORDERS`/`KEEPOUTS` state.
- **Branch/epistemic axis exists as `source`**: live / sim / eval + sim-truth / estimator-belief / simulated-
  prediction — the belief-vs-truth axis, surfaced by `provenance_label.js`.
- **Godot / RViz are NOT embedded** in the web cockpit today — they are separate tools. Orchestrating them into
  one shell is genuinely new.
- Current stack: vanilla-JS cockpit (6321 LOC `cockpit.js`, 1599 LOC `index.html`), 41 pure render modules,
  CesiumJS globe (142 refs) + `three3d.js` local 3D relief, `/program` board.

## Mapping: proposed → current → status

| Proposed | Exists as | Status |
|---|---|---|
| **Context-first** (one Context → all panels update) | `cockpit_state.js` FS-16 routeable state (mission/site/vehicle/body/time/mode/role/workArea/selectedEntity/source) | ✅ EXISTS — *this is the Context* |
| Workspaces (Survey/Nav/Construction/Science/Reconcile/Engineering) | the 13 ConOps panes + `workArea` axis | ✅ EXISTS (workspaces = panes) |
| Everything selectable → panels update | `selectedEntity` in state + 43 pane-render refs | ✅ EXISTS (seed) |
| Timeline slider (everything updates) | `timeline`/`scrub` + `timeS` | ✅ EXISTS (partial) |
| Replay / playback / compare / reconcile | fleet_playback + `compare`/`replay` + RS-04 | ✅ EXISTS (partial) |
| Layer manager (GIS-style) | Contents tree, `LAYER_ON`-driven | ✅ EXISTS |
| Branch selector (actual/sim/what-if) | the `source` epistemic axis | 🟨 SEED (named branches = NEW) |
| Query bar (spatial / NL queries) | — | 🟨 PLANNED (DW lane — DuckDB-WASM over FR-10) |
| Per-object inspector | pane detail views + `provenance_label` | 🟨 PARTIAL |
| Provenance graph (prediction → model → paper → DOI → commit) | evidence bundles + `req_trace` digital thread | 🟨 SEED (data exists; graph viz is new) |
| **Multi-engine shell** (orchestrate Godot+RViz+GeoLibre in one IDE) | separate tools, not embedded | ❌ NEW — the big, heavy piece |
| AI copilot (grounded in the world engine) | — | ❌ NEW |
| Transformation-graph / architecture-explorer views | — | ❌ NEW |
| Godot as the operator shell | Godot = sidecar; web cockpit is the operator UI | ⛔ CONFLICTS with the staged GeoLibre web decision |
| Plugin marketplace / collaborative editing | — | ❌ NEW (later-stage platform) |

## The one real fork: web-2D cockpit vs. desktop multi-engine IDE

- **Staged decision** (`geolibre_rewrite_plan_2026-07-03.md`): a GeoLibre-style **2D React WEB cockpit**;
  Python backend as sidecar; Godot as a sim/render sidecar. Lean, web-first, single stack.
- **This proposal**: a **desktop Planetary IDE** that orchestrates native **Godot (3D render) + RViz (ROS
  debug) + GeoLibre (GIS) + panels**, all context-synchronized.

These are genuinely different shell strategies, and embedding RViz (ROS/Qt) + the Godot engine + a web GIS
into one synchronized shell is a MAJOR desktop-integration effort — far heavier than the web rewrite.

**Reconciliation (they are not either/or):** build the GeoLibre 2D web cockpit **context-first from day one**
— the FS-16 `Context` becomes the React store (Zustand), every pane subscribes, changing context updates all
panes. That is immediate and grounded (FS-16 + the panes already do it). Then wrap it in the **Tauri shell**
already in the plan (TU lane) — and Tauri is exactly the bridge that lets the web cockpit later **orchestrate
native Godot/RViz as context-synced side panels** via the shared Context + the backend event stream. So the
path is: *web cockpit, built context-first, inside a Tauri shell that grows into the multi-engine IDE.* Not
web-XOR-desktop — web-cockpit-in-a-shell-that-grows. Godot stays the render engine (not the operator shell),
which keeps the staged decision intact while reaching the IDE vision.

## Genuinely new frontend work (platform-first, sequenced)

**Now (extends the staged rewrite, from what exists):**
1. Build the React cockpit **context-first**: FS-16 `Context` → the store; the 13 panes → workspaces; the
   `source` axis → the branch selector; the Contents tree → the layer manager. This is the RF/GL lanes done
   right, and it is ~70% a port of existing structure.
2. **Query bar** = the DW lane (DuckDB-WASM over the FR-10 manifest) — the single highest-value new panel.

**Later-stage platform (legitimately in scope — the platform IS the goal):**
3. **Multi-engine orchestration shell** (Tauri hosting the web cockpit + native Godot/RViz as context-synced
   panels). The big piece; approach incrementally (one embedded engine at a time), gated on the context bus.
4. **Named branches** UI (mirrors the backend branch model) + **provenance/transformation-graph** views
   (the data already exists in evidence bundles + req_trace).
5. **AI copilot** grounded in the world engine, **plugin marketplace**, **collaborative editing** — the
   Planetary-IDE frontier.

## Honest status

Like the backend, the frontend is not a blank slate: the cockpit already implements the context-first,
workspace, synchronized-view, timeline, and layer-manager model — the FS-16 state model IS the "Context." The
proposal's genuine additions are the multi-engine orchestration shell (heavy, later, reconcilable with the
staged web decision via Tauri), the query bar (now, DW lane), and the graph/copilot views (later). The path
forward is the staged GeoLibre 2D rewrite, built **context-first**, in a Tauri shell that can grow into the
Planetary IDE — not a from-scratch desktop IDE. The one decision to make explicit: **Godot stays the render
engine, the web cockpit stays the operator shell** (resolving the one conflict in the proposal).

## Language / tech stack (assessment, 2026-07-03)

Proposed polyglot stack: Python (core) + Rust (kernels) + C++ (ROS/Gazebo/Chrono) + TypeScript/React/Tauri
(frontend) + PostGIS/DuckDB + gRPC/Protobuf. Assessed against current reality (Python backend + vanilla-JS
frontend + Godot/GDScript sidecar + ROS2-via-rclpy).

**Aligned — adopt now (already decided or correct):**
- **Python core** — this is what STEWIE is; forge/bodies stay Python (packaging decision). ✅
- **TypeScript + React + Tauri frontend** — exactly the staged GeoLibre 2D decision (RF/GL/TU lanes). ✅
- **DuckDB + GeoParquet analytics** — the DW lane. ✅ (PostGIS is later, per `data_architecture.md`.)
- **OpenAPI-typed TS client** (AC lane), **YAML + JSON-Schema config**, open formats (GeoParquet/COG/glTF/
  MCAP), **uv/hatch/ruff/mypy/pytest + pnpm/Vite** — all correct, most already in use. ✅

**Right 10-year target, but PREMATURE now (the polyglot-too-early trap):**
- **Rust performance kernels** (event store / geometry / scheduler / graph) — the numpy core is already
  sub-millisecond per step; a Rust rewrite adds a permanent Python↔Rust FFI boundary (pyo3/maturin) for
  performance not yet needed. Add a Rust kernel ONLY when a specific hot path is a PROFILED bottleneck, one
  kernel at a time. Not now.
- **C++ nodes** — only where the ecosystem forces native (a real-time ROS2 node, a Gazebo/Chrono plugin).
  STEWIE does ROS2 via `rclpy` today, which is fine. Don't write business logic in C++.
- **gRPC / Protobuf** — REST + the OpenAPI-generated client (AC lane) is sufficient for a Python monolith +
  web frontend. gRPC/proto earns its keep only when a SECOND-language service (Rust/C++) needs efficient typed
  IPC. (Protobuf here = the deferred `stewie-specs` — same "defer until a non-Python consumer exists" call.)

**The discipline:** stay **two languages (Python + TypeScript)** until a MEASURED need forces a third. Keep the
semantic contracts (schemas / APIs / events) **language-agnostic** — as the proposal rightly says — so a
language CAN be added at a seam later WITHOUT a rewrite. But each implementation language is a permanent tax on
every build, contributor, and refactor; **polyglot-in-the-core-too-early is one of the top ways ambitious
platforms die under their own build complexity.** Polyglot at the forced seams (C++ where ROS demands it, TS
in the browser) — yes; polyglot by default — no. This mirrors the other sequencing calls: monorepo-not-N-repos,
logical-modules-not-microservices, file-store-not-Postgres — the vision is right; add complexity only when
profiled need forces it.
