# STEWIE — Operational-OS Reframe: Atomic Implementation Plan (2026-07-09)

**Task:** #64, scoping Aaron's 2026-07-08 "operational OS" reframe into a concrete, atomic build plan.
**Method:** read the vision source verbatim, audited the live artemis `/ide` (QWC2) code against it, and
organized the delta into buildable increments. Where an increment was already scoped by the prior
`scripts/fanout_plan.py` run over the same vision doc (`FANOUT_SPECS.md`), this plan cites and organizes
that existing brief under the four-pillar frame rather than re-scoping it from scratch — those are marked
**[FANOUT: <ID>]**. Where no dispatch brief exists yet, the increment is marked **[NEW]**. This document
does not build anything; it is read-and-plan only.

---

## 1. Vision source (verbatim)

**Primary source:** `design/STEWIE_world_state_mission_console_2026-07-08.md` (the ONLY file matching
Aaron's four vision phrases in the repo — confirmed by `grep -rli` across `design/`, `session_notes/`,
`docs/`, and `PRD.md`; also referenced once more in `FANOUT_SPECS.md:1622` as the FS-32 dispatch's
`current_state` citation). There is no separate 2026-07-08 session note; the vision lives entirely in this
one design doc, added in two extensions the same day.

**Central thesis** (lines 8–19):
> **Shift from a COMMAND-driven interface to a WORLD-STATE-driven one.** Every plan should be based on the
> *current* state of the lunar world model; every executed mission should *modify* that state; every
> modification should automatically become part of the historical record used for future planning,
> validation, and learning. Make the persistent lunar world model the centerpiece. ... **Good news from the
> audit:** STEWIE already has the world-state BACKBONE — the observed twin (DT-04/05, per-(site,source),
> versioned + chain-verified), the as-built TerrainMemory, and the SIM **execute→remember** loop... The
> review is mostly about CENTERING that in the UI, not building new world-state machinery.

**Operational-OS reframe** (lines 78–122, "Extension pt.2"):
> **Bigger philosophy shift (Aaron):** for production (NASA / commercial ISRU / terrestrial autonomous
> construction) STEWIE should resemble mission-control / mine-planning / fleet-management / SCADA software,
> not a collection of planning widgets. **Intent-driven, NOT algorithm-driven** ... **Workspaces (STEWIE =
> the OS for lunar construction):** Operations · Planning · World Model (the heart) · Fleet (SCADA) ·
> Simulation · Execution · Replay. **THE architectural distinction — the MOON IS THE DATABASE:** the Moon is
> the persistent, version-controlled object; every mission updates it... STEWIE ALREADY has the substrate:
> the versioned observed twin + as-built TerrainMemory + the SIM execute→remember loop. **The mode switch —
> RECOMMENDED = 3 lenses on ONE world model:** RESEARCH (algorithm-forward, the dissertation surface) /
> OPERATE (intent-forward, algorithms+ML HIDDEN) / TRAIN (lifecycle-forward, ML engineer). **Status:**
> north-star vision captured. Mode-set + sequencing pending Aaron's confirmation.

**Mission Tasks palette** (lines 126–163, "Extension pt.3"):
> **Reframe "Tool Palette" → "Mission Tasks" (Aaron):** operators think in WHAT-TO-BUILD, not geometry...
> **This backend capability ALREADY EXISTS** — structure templates (LandingPad/HaulRoad/Berm/…) decompose
> into mass-balanced cut/fill with per-structure constructability evidence... **Functional groups** (6:
> Earthworks/Transportation/Construction/Survey/Science/Fleet, each Primitive Ops + Templates). **Intelligent
> Templates**, **Dynamic palette (rover-dependent)**, **Object palette**, **Smart context**. **Existing-vs-
> new:** structure templates + cut/fill decomposition + constructability evidence EXIST (backend);
> place-object markers EXIST. NEW: the capability/work-package palette framing, the template WIZARDS, the
> rover-dynamic palette, the object-palette expansion, and smart-context.

**Consolidated build order Aaron already wrote** (lines 165–177):
> 1. Mission Tasks palette reframe + World-State header/centerpiece. 2. Mode scaffold (thin). 3. Layers
> promotion + Mission Report + Future-comparison. 4. Intent→optimization + template wizards. 5. Fleet SCADA
> + Execution controls + NASA approval chain. 6. Digital-twin health + prediction-vs-reality + Playback. 7.
> Learning (background/foreground per mode) + 7-phase reorg last.

Nothing in this plan invents scope beyond these words. Where this plan proposes an increment not literally
named above (e.g., a lineage-browser UI, or wiring the lens into visible menu behavior), it is explicitly
flagged as an inference, not attributed to Aaron.

---

## 2. Current architecture baseline (confirmed by direct read, this session)

- **ConOps spine = the menu itself.** `gis/qwc2/static/config.json` → `plugins.common[44].cfg.menuItems`:
  six sections `SecPlan` (title "Plan") → `SecValidate` ("Validate") → `SecRelease` ("Release") →
  `SecExecute` ("Execute") → `SecReport` ("Report") → `SecSettings` ("Settings"). Shipped by commit
  `b833069` (2026-07-08, "mission menu in ConOps order"), which originally also added a `SecRehearse`
  section (title "Rehearse", holding `MissionAssets`) and a `SecSupport` section — both were then folded
  the same day by `c5580a10` ("move MissionAssets Rehearse→Report + drop the empty Rehearse section") and
  `44525528` ("reorder... + dedup icons"). **So the live menu today has no separate Rehearse or Support
  section** — the PRD note's "7-phase... Plan→Rehearse→Validate→Release→Execute→Report→Support" describes
  an intermediate state, not the current one. This is a fact worth flagging to Aaron since the World-State
  doc's §"RECONCILIATION" paragraph (line 27) still describes the 7-name spine as shipped.
- **Plugin roster:** 12 `Mission*.jsx` files in `gis/qwc2/js/plugins/` — `MissionPlan.jsx` (1857 lines,
  the largest: structure templates, forward-compare, Plan IR export), `MissionLayers.jsx` (483 lines, the
  68-entry layer catalog per `stewie/server/layer_catalog.json`), `MissionProgram.jsx` (286),
  `MissionHUD.jsx` (342), `MissionEvidence.jsx` (232), `MissionRuntime.jsx` (83, thin), plus
  `MissionCrossSection`, `MissionEngPanel`, `MissionAssets`, `MissionTerrain3D`, `MissionTerramech`,
  `MissionUserLayer`. Pure-logic siblings live in `gis/qwc2/js/mission/*.js` (27 non-test files: workspace,
  planAuthor, planTools, programBoard, runtimeClient, terrain3d, etc.), each with a `node --test` file —
  this is the established plugin+client+test pattern every new increment below should follow.
- **The shared workspace store already exists but is thin.** `gis/qwc2/js/mission/workspace.js` (119
  lines, read in full): a pub/sub store with `KEYS = ["site","body","mission","profile","source"]`,
  `hydrateFromQuery`/`toQuery` (URL round-trip), plus three separate transient event channels (`emitPlot`,
  `requestFloat`, `emitRoute`) added task-by-task. **Confirmed: there is no `lens` field** — the
  RESEARCH/OPERATE/TRAIN mode has no representation in the store today. `programBoard.js` separately
  defines a `LANE_GROUPS`/`GIS_LANES` grouping vocabulary (`gis/qwc2/js/mission/programBoard.js:97,110`)
  for the `/program` board's lane-bucketing — a reusable pattern for "group things into named clusters"
  but not wired to workspace state or to panel visibility.
- **A richer ConOps already exists, just not in `/ide`.** The old cockpit (`stewie/server/index.html` +
  `stewie/server/web/assets/cockpit.js`) has the full `Plan → Rehearse → Validate → Release → Execute →
  Report` tab strip (`cockpit.js:3613`, `index.html:817-836`) plus a role-gated secondary cluster — Fleet /
  Construction / Models / Trainer — behind a "More ▾" button, each tab carrying `data-minrole="operator"`
  or `"director"` (`index.html:849-861`). This is the closest thing in the live codebase to an
  operator/researcher role distinction, and it is NOT ported to the QWC2 `/ide` front door. The 2026-07-07
  council synthesis (`design/STEWIE_council_ide_organization_2026-07-07.md`, untracked, superseded in
  practice by Aaron's 2026-07-08 ConOps-order redirect) independently found "zero references to
  `workspace.ts` [the React `/app` cockpit's GW-02 reducer, `frontend/src/workspace.ts`, 117 lines] from
  `gis/qwc2/`" — the mode/role concept exists in two other surfaces (old cockpit, React `/app`) but not in
  the QWC2 IDE that is now the product front door.
- **Moon-as-database substrate is real and file-locatable.** `stewie/twin/terrain_memory.py`
  (`TerrainMemory`), `stewie/twin/envelope.py` (hash-chained `WorldTransaction` log, `verify_chain`),
  `stewie/twin/store_isolation.py` (per-mode branch isolation), `stewie/server/routers/twin.py` (`GET
  /twin/version`, `GET /twin/terrain/{site}`, `GET /twin/history`, `POST /twin/resync`, `GET /twin/cg`),
  `stewie/server/routers/world.py` (`GET /world/layer-catalog`, `/world/site-markers`, `/world/point`,
  `observed_fraction` DT-05 enrichment computed from real per-site mask coverage, `world.py:252-259` —
  "No synthetic timestamps — a site with no fresh observation reports observed_fraction 0.0"). These are
  read surfaces, not UI — nothing in `/ide` currently narrates "you are looking at a versioned database."
- **Mission Tasks backend is real.** `leap/structures.py::decompose` (8 templates → mass-balanced cut/fill
  with constructability evidence), `POST /api/structure`, `GET /api/construction` catalog,
  `MissionPlan.jsx::renderStructures()` (places a template → adopts decomposed orders), Playwright hooks
  already present (`data-stewie-structure` attributes) even though no Playwright CI tier runs them yet.
  `stewie/specs/vehicles.py` — confirmed by direct read: **3 registered vehicles, all identical**
  (`capabilities=frozenset({"drive","excavate","haul","dump","compact"})` at lines 135/151/169), no
  survey-class vehicle, no `grade` capability anywhere in the file. So "the palette changes per selected
  vehicle" has nothing to visibly differ on today — this is a real, load-bearing gap behind Pillar 2's
  TP-03 increment (see §3.2).
- **`FANOUT_SPECS.md` already contains atomic dispatch briefs against this exact vision doc.** A prior
  fan-out run produced `WS-01/02/04/05` (World-State), `TP-01/02/03/04` (Mission Tasks), `FS-32` (the
  RESEARCH/OPERATE/TRAIN lens), and `BR-02` (mission-snapshot lineage — the one real Moon-as-database
  backend gap). None of these are marked done in `git log` (no matching recent commits); they are scoped
  but unbuilt. This plan's job is to organize them under Aaron's four pillars, fill the one or two gaps the
  fanout run did not cover, and give a build order — not to re-derive them.

---

## 3. Pillar-by-pillar plan

### 3.1 Pillar: World-State console

**(a) What exists today:** the World-State header's four real data sources are all live endpoints —
`GET /twin/version` (twin-sync + chain_valid), `GET /world` (`observed_fraction` = confidence),
`GET /twin/terrain/{site}` (`cells_changed` = changed-since-last-mission) — plus `MissionLayers.jsx` (483
lines) rendering the 68-entry layer catalog, an executable **Plan IR** (`lode/mission_planner.py::plan_ir`
— typed actions + precedence DAG + deterministic `plan_id`, downloadable from `MissionPlan.jsx`), a
forward-compare card (`MissionPlan.jsx::renderCompare/renderFutures`, backed by real
`lode.resync.forward_compare` rows), an SSE mission-replay stream already hardened with `id:`/resume
(`MissionHUD.jsx` ← `executive.py`), and an EV-01 evidence bundle (`MissionEvidence.jsx`, 232 lines).

**(b) The gap:** no single persistent strip composes the four header values; two of the header's proposed
counters (learning-dataset-size, pending-validation) have **no backend source at all** — per the
no-synthetic-data rule these must render "unavailable," not a fabricated number, until a real producer
exists; the forward-compare card is missing slip and completion columns; the Plan IR has no timeline/
behavior-tree visualization; twin-health per-model trust percentages are not surfaced anywhere.

**(c) Atomic increments:**

1. **[FANOUT: WS-01]** World-State header strip. Deliverable: a persistent top strip on every `/ide` screen
   showing mission/twin-sync/terrain-version/changed-since-last/confidence, with the 2 new counters
   explicitly "unavailable." Files: `gis/qwc2/js/mission/worldStateStrip.js` (NEW), `gis/qwc2/js/plugins/
   WorldStateStrip.jsx` (NEW), `workspace.js`, `appConfig.js`, `config.json`. Acceptance:
   `worldStateStrip.test.js` (NEW node:test) asserts the model binds real values from `/twin/version`,
   `GET /world`, `/twin/terrain/{site}` + `workspace.js`, and marks the 2 uncovered counters "unavailable."
   No new backend needed — pure composition of already-live endpoints. **Lowest-risk, highest-leverage
   increment in the whole plan** (this is also Aaron's own #1 pick).
2. **[FANOUT: WS-05]** Forward-compare tradeoff card upgrade — add slip + completion columns to
   `lode/resync.py`'s `forward_compare` output (currently `resync.py:112-136` has neither) and restructure
   `MissionPlan.jsx::renderFutures` from a stacked `<li>` list into a real side-by-side table. Files:
   `gis/qwc2/js/plugins/MissionPlan.jsx`, `gis/qwc2/js/mission/planAuthor.js`, `lode/resync.py`,
   `stewie/server/routers/plan.py`.
3. **[NEW]** Mission Timeline (Plan IR visualization). No dispatch brief exists for this yet. Deliverable:
   render the already-existing Plan IR (typed actions + precedence DAG) as a timeline/behavior-tree instead
   of a flat queue. Files: likely a new `gis/qwc2/js/plugins/MissionTimeline.jsx` + a pure `mission/
   planTimeline.js` renderer consuming `lode/mission_planner.py::plan_ir` output (no backend change
   needed — the DAG already exists). Acceptance (proposed): a node:test asserts the DAG's precedence edges
   render as parent/child timeline rows, not a flat list.
4. **[FANOUT: WS-02]** Digital Twin Health panel — per-model agreement/trust (localization, map-agreement,
   terrain, wheel, battery, excavation), each traced to a real predicted-vs-observed computation (TM-04,
   already surfaced in `POST /executive/run`) or explicitly flagged `not_surfaced`. Files:
   `stewie/runtime/replay_loop.py`, `stewie/server/routers/executive.py`, `gis/qwc2/js/mission/
   twinHealth.js` (NEW), `gis/qwc2/js/plugins/MissionTwinHealth.jsx` (NEW).
5. **[FANOUT: WS-04]** Learning-lifecycle panel — the biggest genuinely new capability in this pillar:
   surfaces the real roversim RL stack (`RoverSimEnv`, `train_ppo`, `validation/rl/*`) as a
   collect→generate→retrain→evaluate lineage, gated so an RL-01-incomplete policy (missing
   `ModelArtifact.deployment_ready` fields) is blocked from an "operational" label. Files:
   `stewie/server/routers/models.py`, `stewie/contracts/__init__.py`, `gis/qwc2/js/plugins/
   MissionLearning.jsx` (NEW).

**(d) Dependencies / order:** WS-01 has zero dependencies (pure GET wiring) — build first. WS-05 is
independent of WS-01. The Mission Timeline increment (#3) needs nothing new. WS-02 and WS-04 both depend on
verifying two things the vision doc itself flags as **inferred, not confirmed**: "the roversim RL stack
EXISTS but not in the IDE" and the twin-health per-model metrics (line 70 of the source doc) — audit the
live `/executive/run` response shape and the RL artifact registry before committing to WS-02/WS-04 scope,
since if either surface doesn't actually expose the needed telemetry, the honest move is a smaller panel
with more "not yet surfaced" flags, not invented numbers.

### 3.2 Pillar: Mission Tasks palette

**(a) What exists today:** `leap/structures.py::decompose` (8 templates → mass-balanced cut/fill with
constructability evidence), `POST /api/structure`, `GET /api/construction` catalog,
`MissionPlan.jsx::renderStructures()` (places a template → adopts the decomposed orders), and Playwright
selector hooks already in the DOM (`data-stewie-structure`, controller `placeStructure`/`structureCount`)
even though no Playwright tier runs in CI yet.

**(b) The gap:** the palette is a flat list today, not two-level (Primitive Ops + Templates) or grouped
into the 6 functional groups (Earthworks/Transportation/Construction/Survey/Science/Fleet); templates have
flat default-param editors, not the 8-field wizard (`landing_pad` currently has only 3 params:
`side_m`/`cut_depth_m`/`berm_height_m`, confirmed against the TP-02 brief); the vehicle registry has **no
real capability contrast** to filter against (confirmed: 3 identical excavators, no survey vehicle, no
`grade` capability); the object palette covers only 5 of 11 named types (`ALLOWED_MARKER_TYPES` in
`stewie/server/edit_session.py` — beacon/cache/instrument/sample/antenna only) with no per-object
provenance stamp; smart-context (select a berm → get Inspect/Extend/Repair/Remove actions) has a partial
substrate (`SelectionInspector` already renders a cell-affordance action list) but nothing wires it to
palette state.

**(c) Atomic increments:**

1. **[FANOUT: TP-01, epic]** 6-functional-group reframe. Deliverable: the palette leads with work-packages
   grouped Earthworks/Transportation/Construction/Survey/Science/Fleet, two-level (Primitive Ops +
   Templates), and selecting a template still emits the existing mass-balanced decompose order. Files:
   `gis/qwc2/js/plugins/MissionPlan.jsx`, `leap/structures.py`, `stewie/server/routers/construction.py`,
   `gis/qwc2/js/mission/planAuthor.js`. **Flag:** the acceptance test the fanout brief specifies is a
   Playwright test over the built QWC2 IDE, and **no Playwright/browser CI tier for `/ide` exists today**
   (only `node --test` unit tests run in CI per `PO-04`). Building to that literal acceptance bar means
   either standing up a new CI tier or accepting the documented data-leg alternative (extending
   `test_construction_pane.py` for the catalog taxonomy only, leaving the UI grouping tested by hand/
   Playwright locally). This is a decision Aaron should make explicitly (see §5).
2. **[FANOUT: TP-02, epic]** Intelligent template wizard — the 8-field parameterized schema (Length/Width/
   Bearing/Finish/Flatness/Elevation/Material/Priority for Landing Pad) expanding to the named 7-step work
   order Survey→Excavate→Move→Grade→Compact→Inspect→Approve. Files: `leap/structures.py`,
   `stewie/server/constructability.py`, `gis/qwc2/js/plugins/MissionPlan.jsx`, `leap/work_order.py` (NEW).
3. **[FANOUT: TP-04]** Object palette expansion to the 11-type vocabulary + per-object provenance stamping
   in the versioned edit-session twin store. Files: `stewie/server/edit_session.py`, `gis/qwc2/js/mission/
   planTools.js`, `gis/qwc2/js/plugins/MissionPlan.jsx`.
4. **[FANOUT: TP-03]** Vehicle- and feature-context-aware palette filtering. **Blocked on a product/data
   decision, not just code:** the fanout brief itself requires "adding a survey-class vehicle and `grade`
   to the excavator so the capability contrast is real in the registry" — i.e., this increment cannot be
   built honestly without first deciding whether STEWIE should model a second vehicle class now. Files:
   `stewie/specs/vehicles.py`, `gis/qwc2/js/mission/planTools.js`, `gis/qwc2/js/plugins/MissionPlan.jsx`,
   `stewie/server/routers/models.py`.

**(d) Dependencies / order:** TP-01 first (the framing all the others sit inside; matches Aaron's own #1
build-order pick, paired with WS-01). TP-02 next (deepens TP-01's templates with the wizard). TP-04 is
independent of the other three and can run in parallel. TP-03 last — it is genuinely gated on the vehicle-
registry decision (§5), not on engineering effort.

### 3.3 Pillar: Research / Operate / Train modes

**(a) What exists today:** the workspace store pattern itself (`workspace.js`, pub/sub + URL round-trip,
already proven for site/body/mission/profile/source), the lane-grouping vocabulary in `programBoard.js`
(`LANE_GROUPS`/`GIS_LANES`) as a precedent for "bucket things into named groups," and the vision doc itself
(already-written design spec for the 3-lens split). The old cockpit's role-gated tab visibility
(`data-minrole="operator"/"director"`) is the closest existing UX precedent for "hide surfaces per persona,"
though it lives in the wrong codebase (old cockpit, not `/ide`).

**(b) The gap:** confirmed by direct read of `workspace.js` — **there is no `lens` field in `KEYS` at all**.
The mode switch does not exist at any level: no store field, no RESEARCH/OPERATE/TRAIN→foregrounded-cluster
map, and no consumer that changes what's visible based on it. This is a from-scratch build, not a promotion
of existing scattered pieces (unlike Pillars 1 and 2, where most of the substrate already exists).

**(c) Atomic increments:**

1. **[FANOUT: FS-32]** Add a `lens` field (RESEARCH/OPERATE/TRAIN) to `workspace.js`'s routeable/persisted/
   shareable store, plus a pure `lens.js` map from lens value → foregrounded-control-cluster, without
   touching world/authority state. Files: `gis/qwc2/js/mission/workspace.js`, `gis/qwc2/js/mission/
   lens.js` (NEW), `gis/qwc2/js/mission/programBoard.js`. Acceptance:
   `gis/qwc2/js/mission/lens.test.js` (NEW node:test) asserts switching the lens changes the foregrounded
   panel set AND round-trips through `toQuery`/`hydrateFromQuery` while site/body/mission/source stay
   unchanged. This is intentionally thin — a data-model scaffold, not a UI change yet.
2. **[NEW]** Visible-menu wiring. FS-32's acceptance criterion is satisfied by a pure JS model change; it
   does **not** require anything in `config.json` or the TopBar to actually look different. A second,
   currently-unscoped increment is needed to make the lens do something a user can see — e.g., re-order or
   dim `menuItems` sections by lens, or a CSS-class toggle on the ConOps tab strip. Files (proposed):
   `gis/qwc2/static/config.json`, whatever TopBar-consuming component reads `menuItems` today (would need a
   short Explore pass to name precisely — not done in this session, flagged as a scoping gap).
3. **[NEW, larger]** Port role-gating semantics from the old cockpit into `/ide` as the concrete mechanism
   for "OPERATE mode hides algorithms + ML." The old cockpit's `data-minrole="operator"/"director"` pattern
   (`index.html:849-861`) is the one place in the codebase that already does "hide this surface unless the
   persona qualifies" — reusing that vocabulary (rather than inventing a new one) is the path of least
   resistance, but deciding which of the ~12 `Mission*.jsx` plugins are RESEARCH-only vs OPERATE-visible is
   a product call (§5), not an engineering one.

**(d) Dependencies / order:** FS-32 must come first — everything else in this pillar reads the `lens` field
it creates. The visible-wiring follow-on (#2) can ship immediately after as a small increment. The deeper
role-gating port (#3) should wait until Aaron has picked, section by section, what RESEARCH/OPERATE/TRAIN
actually show — building it before that risks the same churn the ConOps menu already went through twice in
one day (§2).

### 3.4 Pillar: Moon-as-database

**(a) What exists today:** this pillar is explicitly, in Aaron's own words, **already built at the
substrate level** — "STEWIE ALREADY has the substrate: the versioned observed twin + as-built TerrainMemory
+ the SIM execute→remember loop." Confirmed present: `stewie/twin/terrain_memory.py` (`TerrainMemory`),
`stewie/twin/envelope.py` (hash-chained `WorldTransaction` log with `verify_chain`), `stewie/twin/
store_isolation.py` (per-mode branch isolation), the full `/twin/*` and `/world/*` router surface (§2), and
the SIM execute→remember loop (per `CLAUDE.md`'s 2026-07-01 entry, commit `d8ecd9a`: "a completed run folds
its terrain into `TerrainMemory` + records belief/authority into the DT-01 log" — not re-verified against
code this session, but it is a specific, dated, previously-verified claim in the project's own operational
log, not a fresh assertion).

**(b) The gap:** this pillar is almost entirely an **exposure gap, not a build gap.** Nothing in the UI
currently narrates "you are querying a versioned world database" — that narration IS Pillar 1's WS-01
header strip; there is no second, separate UI gap here. The one genuine backend gap is a missing lineage
object: no `Moon → Mission-000 → 001 → … → N` numbered, replayable, branch-selectable snapshot chain
exists yet (confirmed via `FANOUT_SPECS.md` BR-02: "missing: no mission_snapshot object, no numbered
lineage, no producer wiring on mission completion, and no select-snapshot-as-branch-parent API for
what-if/retrain" — despite the hash-chained transaction log and deterministic replay already existing as
prerequisites).

**(c) Atomic increments:**

1. **Reuse, no new work.** WS-01 (§3.1 #1) IS this pillar's primary UI deliverable — a second, separate
   "Moon-as-database" panel would be redundant with the World-State header. Nothing new to scope here.
2. **[FANOUT: BR-02, epic]** Mission-snapshot lineage producer. Deliverable: on mission completion, append
   an immutable hash-chained snapshot into a numbered `Moon → Mission-000 → 001 → N` lineage that replays
   deterministically and can be selected as a branch parent for what-if/retrain. Files:
   `stewie/twin/envelope.py`, `stewie/twin/store_isolation.py`, `stewie/contracts/mission_flow.py`,
   `stewie/twin/mission_snapshot.py` (NEW). This is the one genuinely new backend capability in the whole
   operational-OS arc that isn't just "surface what already exists."
3. **[NEW, follow-on, not yet scoped]** A lineage-browser UI panel consuming BR-02's numbered snapshots
   (e.g., a "Moon version history" timeline distinct from the Mission Timeline in §3.1 — that one shows a
   single mission's plan; this one would show the world's version history across missions). Cannot be
   scoped in detail until BR-02 exists and its data shape is known.

**(d) Dependencies / order:** BR-02 has no dependency on the other three pillars and can be built in
parallel with anything else. The lineage-browser UI (#3) depends on BR-02 shipping first — do not scope its
files/acceptance criteria until BR-02's actual snapshot schema exists, to avoid guessing at a shape that
doesn't match the real implementation.

---

## 4. Consolidated recommended build order

Matches Aaron's own build-order note (source doc lines 165–177) where it is specific, and fills in the
first ambiguous step with the smallest, lowest-risk increment:

1. **WS-01** (World-State header strip) — zero new backend, composes 3 already-live endpoints, highest
   leverage per the vision doc's own ranking.
2. **FS-32** (mode-lens scaffold) — thin, unblocks every later lens-aware increment, and is explicitly
   "thin at first... deepens over time" per Aaron's own framing.
3. **TP-01** (Mission Tasks 6-group reframe) — pairs with WS-01 as Aaron's own "highest-leverage, both
   mostly surfacing existing backend" pick; resolve the Playwright-CI-tier question (§5) before or during
   this increment since its acceptance bar depends on the answer.
4. WS-05 (forward-compare columns) + the Mission Timeline (Plan IR viz) — both small, independent,
   no new backend.
5. TP-02 (template wizard) + TP-04 (object palette expansion) — independent of each other, both deepen
   Pillar 2 without needing the vehicle-registry decision.
6. BR-02 (mission-snapshot lineage) — the one real new backend capability; can start any time after step 1
   but is naturally sequenced here since nothing else depends on it yet.
7. WS-02 (twin health) + WS-04 (learning lifecycle) — larger, and gated on verifying two currently-inferred
   claims about backend telemetry shape (§3.1d) before committing scope.
8. TP-03 (vehicle/feature-context palette) — last, gated on the vehicle-registry product decision (§5), not
   on engineering sequencing.
9. The visible-menu lens wiring (§3.3 #2) and the deeper role-gating port (§3.3 #3) — layer in once Aaron
   has picked which surfaces are RESEARCH-only vs OPERATE-visible.
10. Lineage-browser UI (§3.4 #3) — only after BR-02 ships and its schema is known.

---

## 5. Decisions needed from Aaron (not buildable without a call)

- **TP-03 vehicle registry:** should STEWIE add a second, functionally distinct vehicle class (a survey
  rover + `grade` on the excavator) now, purely to make the Mission Tasks palette's "dynamic by vehicle"
  claim real — or does that wait until a second vehicle type is modeled for its own reasons (e.g., a real
  hauler/survey mission profile)? Building TP-03 before this call means inventing a vehicle distinction
  whose only purpose is to unblock a UI feature, which risks becoming a fabricated fixture the moment
  someone asks whether that vehicle reflects anything real.
- **Playwright/browser CI tier for `/ide`:** TP-01's own fanout brief specifies a Playwright acceptance
  test, but no Playwright tier for the QWC2 IDE exists in CI today (only `node --test` unit tests, per
  `PO-04`). Options: (a) stand up a Playwright CI tier now (larger, but closes a real testing gap the
  council review also flagged), or (b) accept the brief's documented fallback — extend the existing
  `test_construction_pane.py` for the catalog taxonomy only, leaving the visual grouping verified by hand.
  This should be decided once, not re-litigated per increment, since several of the TP-* and GW-* fanout
  briefs share the same gap.
- **How much OPERATE mode actually hides:** the vision doc says "algorithms + ML HIDDEN" in OPERATE mode.
  That could mean anything from a cosmetic re-ordering of the existing 6 ConOps menu sections to genuinely
  removing/disabling specific plugins (e.g., is `MissionTerramech` — the physics-attribution inspector —
  RESEARCH-only, or does an operator ever need it during a live anomaly?). This determines whether the
  Pillar 3 follow-on (§3.3 #3) is a small CSS/config change or a change touching most of the 12 `Mission*`
  plugins' registration logic.
- **BR-02 + WS-04 sequencing:** BR-02's own acceptance criterion references "a new what-if/retrain branch"
  — which is WS-04 (Learning-lifecycle panel) territory. Both are epic-sized. Aaron should confirm whether
  these should be scoped and built together (since they reference each other's output) or genuinely
  sequentially (BR-02's lineage object first, WS-04's consumer of it later) — this plan defaults to
  sequential (§4 steps 6 and 7) but that is this document's judgment call, not a confirmed decision.
- **The stale "7-phase ConOps" reconciliation note:** the World-State source doc's own reconciliation
  paragraph (line 27) describes a shipped 7-name spine (Plan/Rehearse/Validate/Release/Execute/Report/
  Support) that the live `config.json` no longer has — Rehearse and Support were folded away the same day
  they were added (§2). This is a small honesty gap in the source doc itself, not a build item, but Aaron
  should know the design doc's own "RECONCILIATION" note is now stale so it isn't cited as current fact in
  a future session.

---

## 6. What this plan deliberately does not do

Per the task scope, this document does not build any increment, does not modify code, does not deploy, and
does not push. It also does not re-litigate the atomic breakdowns already produced in `FANOUT_SPECS.md` for
WS-01/02/04/05, TP-01–04, FS-32, and BR-02 — those were audited against the live code in a prior session and
are cited here, not rewritten. The only genuinely new scoping in this document is: the current-state
ConOps-spine correction (§2), the Mission Timeline increment (§3.1 #3), the two Pillar-3 follow-ons beyond
FS-32's thin scaffold (§3.3 #2, #3), the lineage-browser follow-on to BR-02 (§3.4 #3), and the consolidated
cross-pillar build order + decision list (§4, §5).
