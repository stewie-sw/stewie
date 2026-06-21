# STEWIE Full-Fidelity UI Overhaul Plan (2026-06-20)

**Status:** plan of record for the cockpit overhaul. Companion to PRD §27. Grounded in the
2026-06-20 mission-ops review (`docs/architecture_review_2026-06-20_mission_ops.md`), the
2026-06-20 architecture review, and the prior UI/UX design corpus (`design/WIREFRAME_SPRINT`,
`design/TRAINER_DASHBOARD_DESIGN`, `design/MISSION_PLANNER_UIUX_AUDIT`, `design/BRAND_UI_ANALYSIS`,
`design/PLAN_TAB_GIS_PATHWAY`, `design/PLANNING_REVISION`, `design/OSS_GIS_SURVEY`,
`docs/ui_ux_assessment_2026-06-06`, `docs/uiux_audit_2026-06-09`).

This plan supersedes nothing in those docs; it sequences them into one full-fidelity build and binds
each step to a PRD ID.

---

## 0. The single fact that shapes this plan

The target IA was already designed **and built once** as a React+Vite rewrite (Phases 0–5, FS-23,
targeting the §11 eight-work-area shell), deployed to `app.stewie.space`, **broke on a Cesium init
bug** (`CESIUM_BASE_URL` unset blanked the map panes), and was **reverted at commit `55c44c6`**
(PRD §0, 2026-06-19). The live cockpit is the vanilla `stewie/server/web/assets/cockpit.js` 5-tab
shell (Plan/Navigation/Perception/Metrics/Report). FS-03's Fleet / Construction / Models first-class
work areas **do not exist** — this is the single largest standing product-surface gap.

**The overhaul therefore optimizes for "never black-screen the map again," not for framework
novelty.** Every approach decision below is downstream of that.

---

## 1. The stack decision (lead decision — recommendation + alternatives + evidence)

**Recommended: incremental strangler-fig migration of the vanilla cockpit behind the
already-built FS-15 typed adapters, work-area by work-area, with Cesium and `three3d.js` kept as
isolated modules that are never rewritten.** Adopt the *patterns* of TerriaJS (catalog tree +
workbench cards, OSS_GIS_SURVEY's "USE THIS ONE") and QGIS (edit sessions), not the whole apps.

Why (evidence):
- The big-bang React rewrite already failed exactly here (`55c44c6`). The failure was the map init
  inside a new bundler/CSP context — a strangler-fig keeps the proven Cesium/`three3d` init paths
  untouched and migrates only the chrome and work-area views around them.
- FS-15's typed contract-adapter layer is **already built** (10 contracts:
  `stewie/contracts/__init__.py`); the views can bind to those view models regardless of shell tech,
  so the migration has a stable seam.
- FS-24 already specifies the module split (app shell / route-state store / typed adapters / view
  models / shared viz components / work-area views / command-approval rail / diagnostics viewers)
  under the hard constraint of preserving the no-inline-script CSP, mobile hardening, and
  fixture-driven tests.

**Alternatives weighed and why they lose as the primary path:**
- *Full framework rewrite (React/Svelte + Resium/cesium-react).* Rejected as the primary path: it is
  the approach that already black-screened and was reverted; blast radius is the whole cockpit at
  once. **Permitted only as an island:** a framework may be introduced to render **one work-area pane
  at a time** inside the existing shell, and a pane may flip to it only after a signed-in Playwright
  pass on a real browser confirms the map renders. Never flip the whole shell in one step.
- *Adopt TerriaJS wholesale.* Rejected: it would replace the cockpit and its auth/role/command
  model. Adopt its catalog-tree + workbench-card interaction model (already partially shipped as
  UI-16 workbench cards), not the application.
- *Stay on the single 4321-line `cockpit.js` indefinitely.* Rejected: it blocks FS-03 (no room for
  three new first-class work areas) and is the FS-24 debt the audits keep flagging.

**Hard constraints any step must satisfy (non-negotiable, from the corpus):** self-hosted Cesium;
no-inline-script CSP preserved; mobile-safe; fixture-driven per-pane tests; **a real signed-in
Playwright render verification before any pane flip**; the single-window command-authority model
(FS-17) and role gating (FS-20) unchanged; Cesium remains the 3-D globe (OSS_GIS_SURVEY: MapLibre/
Leaflet/OpenLayers explicitly not adopted).

---

## 2. Target information architecture (FS-03, the 8 work areas)

Eight first-class, routeable, role-gated, mobile-safe work areas, each bound to FS-15 view models,
each with route/state binding, role gate, fixture render, error/empty states, and log visibility
(the §20 "every work area" checklist):

| Work area | Subsystem | Audience | Backed by |
|---|---|---|---|
| **Plan** | LODE | operator | `PlanResult`, `WorldState`, GIS layers, MissionIntent (MO-01) |
| **Fleet** | LODE | operator | `FleetState`, allocation, FL-02 conflicts |
| **Navigation / ARGUS** | LEAP | engineer-leaning | `LocalizationFix`, `ARGUSFactor`, pose-graph |
| **Perception / Imagery** | DART | engineer/demo | panorama, point cloud, shadow landmarks |
| **Construction** | FORGE | operator | structures, acceptance, certified records |
| **Models** | — | engineer | `ModelArtifact` registry, vehicle/soil/body profiles |
| **Security / System** | — | director/dev | validation `/figures`, `/healthz`, `/metrics`, `/config`, Admin |
| **Reports** | FORGE | operator/reviewer | mission-control PDF, Plan IR, debrief |

Chrome (Settings/System/Admin) stays in the role-gated profile menu (FS-20, done). Command authority
stays single-window (FS-17, done). The operator sees only mission work areas; truth surfaces are
director-gated and labeled.

---

## 3. The operational overlay — the four screens (2026-06-20 mission-ops review)

On top of the work areas, the operational flow is the four-screen model from
`docs/architecture_review_2026-06-20_mission_ops.md`. The first three are authoring/analysis screens
(buildable now); the Execute screen is **gated behind a real mission executive** (see §7).

- **Plan screen** — 60/40 layout, **2-D orthographic operational map as the default authoring
  surface, 3-D as secondary inspection**. Nine ordered map layers: base DEM/hillshade+grid → observed
  confidence/age veil → cost layers (slope / illumination-thermal / comms / traversability) →
  hazards/keep-outs (inflation shown separately from source geometry) → objectives/footprints/
  charger/lander/resources/geofences → candidate routes colored by vehicle → energy + localization
  uncertainty corridors → planned cut/fill delta as diverging colors → labels (action ID / priority /
  acceptance). Right pane = objective/constraint inspector (purpose, success criteria, hard
  constraints, priority, assumptions, unresolved warnings, resource margins, uncertainty, provenance).
  Bottom = vehicle-lane timeline (work/travel/charge/waits/comms+sun windows/dependencies/contingency
  branches).
- **Rehearse & compare screen** — three synchronized panes (nominal / uncertainty-envelope +
  Monte-Carlo-fault / worst-credible-or-contingency). Candidate cards expose **feasibility first**,
  then minimum margins, objective completion, duration, energy, charge cycles, localization exposure,
  comms exposure, optimality claim. **Never rank an infeasible candidate above a feasible one on
  weighted score.**
- **Execute screen** (gated, §7) — sparse, glanceable. Header
  `[MISSION/REV][SIM|HIL|LIVE][STATE][COMMAND AUTHORITY][LINK][UTC/MET]`, persistent guarded
  `[HOLD][RETURN][SAFE]`, 2-D observed map with stale-data hatching, vehicle cards (mode / pose
  integrity / SOC reserve / thermal / slip / comms / active-cmd ack), objective progress + action
  timeline + a single task-selected camera (not a video wall). **Explicit color rules:** green =
  verified within limits (never merely connected); amber = degraded/decision required; red =
  violated/SAFE/abort; gray hatch = stale/unavailable; cyan = forecast; white = observed estimate;
  **magenta = truth, directors only in sim/debrief.** Every value shows units + data age.
- **Debrief screen** — one scrubber across synchronized operator-seen / estimated / truth views,
  marking commands/acks/replans/holds/safety-trips/sensor-gaps/map-revisions/objective-decisions/
  human-actions; plots expected-vs-actual energy/pose-error/slip/throughput/terrain-delta/comms/
  acceptance; emits a **signed summary** referencing exact plan/software/config/bag/map/event-log
  hashes. (This is the trainer C-board + UI-9 handover, made operational.)

---

## 4. GIS authoring to full fidelity (the S-2..S-6 pathway + path-first revision)

Bring the Plan tab to a real GIS workstation (`PLAN_TAB_GIS_PATHWAY`, `PLANNING_REVISION`,
`OSS_GIS_SURVEY`):

- **Contents tree (S-2):** merge the LAYERS strip + build queue + keep-outs + lander into one ordered
  checkbox layer tree (TerriaJS workbench-card model — legend, opacity, zoom-to, remove, attribute
  table per layer). **Orders become a feature layer, not a sidebar list.** Groups: Basemap / Terrain /
  Sun / Safety / Operations.
- **Feature editing (S-3), path-first:** draw the traverse on the map (waypoint polyline), attach
  ACTIONS at waypoints (dig/dump/observe/dock), compile to the same Plan IR. **True footprint
  geometry: polygon / corridor / oriented-rectangle** (today scalar → axis-aligned square — a 15×2 m
  road must stop becoming a square). Vertex editing, attribute popup, order undo/redo. QGIS-style
  **edit sessions** (toggle-edit → digitize → save/discard, camera-locked).
- **Object store (S-4):** server-side CRUD for missions/structures + a catalog pane (saved objects,
  sessions, reports with preview/load/delete). *(Path-first authoring, drag-to-move, branded glyphs,
  and the object store have partially shipped — verify live before re-listing.)*
- **Workflow ribbon (S-5):** reorganize the sidebar by the mission-ops 15-step entry order (§5
  below), progressively revealed.
- **Vehicle sheet (S-6):** the registry spec sheet served in-app in the Fleet area with role labels
  (flight / precursor / render-body).
- **GIS interop (GI-03, open):** GeoJSON / COG / OGC import + export, so plans and layers leave the
  tool in standard formats.

The 2-D→3-D handoff is already designed: select a work-area region → Godot renders that crop at
perception fidelity (`design/IPEX_TRUTH_INTEGRATION_PLAN_2026-06-10.md`).

---

## 5. Mission intent + executive + provenance (the data spine the UI renders)

Full-fidelity operational UI is only as honest as its data contracts. From the 2026-06-20 review,
these are new typed contracts (PRD §27 IDs MO-01..MO-04):

- **MO-01 MissionIntent hierarchy:** `MissionIntent` → primary/secondary/stretch objectives →
  constraints/flight-rules → acceptance criteria → contingencies/abort → task graph. Each objective:
  id+revision, statement/rationale, priority+mandatory flag, target geometry/frame, measurable
  acceptance, confidence requirement, time/illumination/comms windows, budgets, prerequisites,
  hold/abort thresholds, contingency policy, approver+evidence. **The planner may optimize
  time/energy/risk/coverage only after mandatory objectives + hard safety constraints are compiled;
  weighted scoring must never convert a flight rule into a soft preference.**
- **MO-02 mission-executive state machine:** `DRAFT → ANALYZED → REHEARSED → REVIEWED → RELEASED →
  ARMED → EXECUTING → HOLDING|SAFED|COMPLETED|ABORTED → DEBRIEFED`; transitions require named
  evidence + roles; RELEASED is a signed immutable revision; replanning makes a new revision, never
  mutates in place. **This is the gate the Execute screen waits on.**
- **MO-03 provenance vocabulary:** every operational view-model field carries `source`, `basis`,
  `timestamp`, `age`, `frame`, `units`, `confidence`, `revision`; the UI renders provenance
  consistently and **rejects incompatible frames/revisions rather than silently combining them.**
- **MO-04 SIM/FORECAST/LIVE labeling contract:** a strict visual + data contract everywhere —
  forecast (cyan) / observed estimate (white) / truth (magenta, directors only). **Until the mission
  executive (MO-02) exists and passes fault injection, all execution UI stays visibly labeled
  SIMULATION or FORECAST.**

---

## 6. Trainer dashboard, brand, accessibility, pane manager

- **Trainer dashboard (TR-01..04, `design/TRAINER_DASHBOARD_DESIGN`):** A-board operator scorecard
  (per-session, persisted scorecard record under `data_dir/sessions/`); B-board director truth/
  divergence (believed vs true pose, director-gated); C-board program leaderboard + per-operator
  trend + handover export; the debrief scrubber (= screen 4). v1 backs A on autonomy-run KPIs; v2 on
  human-operator behavior once the RC seam lands.
- **Brand finish (`design/BRAND_UI_ANALYSIS`, B-3/B-4):** drum-red `#c8102e` accent + graphite ramp +
  Orbitron/Inter type are partially shipped (B-1/B-2). Finish **B-3** (app icon set: favicon + PWA
  tiles from the 1024 board) and **B-4** (patch-style subsystem badges on every work-area pane).
- **Accessibility to WCAG-AA (uiux_audit P2-6):** contrast pass (no 11px gray-on-dark), 44px touch
  targets on queue controls, visible focus rings, a `?` keyboard-shortcut overlay, colorblind-safe
  status (never color/glyph alone — pair with text/units). Currently unaudited.
- **Pane manager (FS-21 / UI-18, `design/WIREFRAME_SPRINT`):** golden-layout draggable docking panes
  (map / plan-view / telemetry / CG / notes / events / render), splits, and **multiple named layouts
  saved per operator in the mission document** (drag-reorder + a single persisted layout already
  shipped; named layouts are the open piece). Layout is a view preference only — it never changes
  command authority.

---

## 7. Phasing (full fidelity is multi-week; the sprint lands the foundation)

| Phase | Scope | PRD IDs | Gate |
|---|---|---|---|
| **U0 — Foundation (in the 2-week sprint)** | FS-24 module split behind FS-15 adapters; 8-area IA scaffold routed on the **vanilla** shell (no rewrite); MO-01 + MO-04 contracts; GIS S-2 Contents tree; per-body globe radius; brand B-3/B-4; a11y pass started | FS-03, FS-24, MO-01, MO-04, B-3/B-4 | every pane flip Playwright-verified signed-in; CSP intact |
| **U1 — Plan + Rehearse to full fidelity** | Plan screen 9-layer map + objective/constraint inspector + timeline; GIS S-3 footprints (polygon/corridor/oriented-rect) + edit sessions + undo; Rehearse 3-pane compare; trainer A-board | FS-03, GIS S-3, MO-01, TR-01 | feasibility-first cards; flight rules never softened |
| **U2 — Debrief + program + interop** | Debrief scrubber + signed summary; trainer B/C boards; pane manager named layouts; GeoJSON/COG export | TR-02, TR-03, TR-04, FS-21, GI-03 | director-gated truth; provenance enforced (MO-03) |
| **U3 — Execute to full fidelity (GATED)** | Execute screen color-rule HMI, vehicle cards, guarded SAFE/HOLD | MO-02, MO-04 | **unlocks only when the mission executive (MO-02) exists + passes fault injection; until then Execute stays labeled SIMULATION/FORECAST** |

**Cross-cutting (every phase):** preserve CSP/no-inline-script + mobile; fixture-driven per-pane
tests; a signed-in Playwright render check before any pane flip; provenance vocabulary (MO-03) on
every rendered field; the SIM/FORECAST/LIVE labeling contract (MO-04) everywhere.

**Ordering note (honest):** the 2026-06-20 review puts operational-visuals work (its Phase D) *after*
the safety/execution spine and autonomy closure. That is why U3 (Execute) is gated and last, while
U0–U2 (authoring, rehearsal, debrief, IA, GIS, brand, a11y) proceed now — they do not need the
executive and are the bulk of the "feels like a real tool" value.

---

## 8. Definition of done (full fidelity)

The overhaul is full-fidelity-done when: (1) all eight FS-03 work areas exist, routed, role-gated,
mobile-safe, fixture-tested, each bound to an FS-15 view model; (2) the four operational screens are
built, with Execute honestly gated/labeled; (3) GIS authoring supports polygon/corridor/oriented-rect
footprints with edit sessions, undo, a Contents tree, an object store, and GeoJSON/COG export;
(4) MO-01..04 contracts back every operational field; (5) the trainer A/B/C boards + debrief scrubber
exist; (6) brand B-3/B-4 shipped and a WCAG-AA contrast audit passes; (7) the pane manager saves
named layouts; (8) `cockpit.js` is split per FS-24 with the CSP intact; and (9) every flip was
verified signed-in on a real browser via Playwright. Until MO-02 exists, the Execute screen is
present but explicitly SIMULATION/FORECAST, not LIVE.
