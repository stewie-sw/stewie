# Cockpit reorganization plan (2026-06-23) — DECIDED spec

Status: **decided and approved**, implementation pending. This is the executable spec for the cockpit
nav + sidebar reorganization (batch item F / task #209). It supersedes the earlier 4-primary proposal
captured in `_batch_plan/cockpit-inventory.json` (`proposed_order`), which left two questions open
(primary set; Rehearse gating). Both are now resolved here.

Companion context: the 8-area information architecture and four-screen operational model in
[`ui_overhaul_plan_2026-06-20.md`](ui_overhaul_plan_2026-06-20.md) and
[`architecture_review_2026-06-20_mission_ops.md`](architecture_review_2026-06-20_mission_ops.md). The
lead architectural decision stands: strangler-fig the existing vanilla cockpit, do NOT repeat the
reverted big-bang React rewrite (`55c44c6`).

## Decided top nav: a 6-slot ConOps spine

The top tabs become the linear concept-of-operations spine an operator actually walks, left to right:

1. **Plan (LODE)** — primary mission authoring (Cesium globe / 3D path map + the planning sidebar).
   Default active tab. Unchanged in purpose.
2. **Rehearse (LODE)** — forward-compare / sim review of the authored plan. Promoted from director-only
   to **operator-visible read-only**: non-directors see the rehearsal results but cannot mutate; the
   director retains the advance action. (Resolves the open "Rehearse gating" question: operators no
   longer jump Plan -> Execute blind.)
3. **Validate** — **merges Navigation (LEAP) + Perception (DART) into one tab with two sub-tabs**:
   - Navigation sub-tab: ARGUS state estimation (drive preview `/nav/run`, est-vs-truth localization,
     real-Haworth `register_to_dem` fix, Katwijk estimator + ARGUS compare, articulation-parallax).
   - Perception sub-tab: Godot before/after sensor render, 8-camera shadow-nav panorama, front-stereo
     depth / point cloud.
   Rationale: both answer the same operator question ("does the plan hold up against truth / against
   what the rover will actually see?") and both were non-adjacent diagnostic tabs before.
4. **Release** — **new surface** wrapping `POST /executive/advance`, the REVIEWED -> RELEASED gate
   (director-gated). Makes the executive lifecycle transition a first-class screen instead of an
   implicit button, between validation and execution.
5. **Execute (LEAP)** — **merges the old Metrics + execution panes**: top-down replay of the planned
   mission, live CG and tip-over margin (stability), speed/pause/3D-dry-run controls, plus the
   **Telemetry block moved here from the Plan sidebar** (telemetry belongs with execution, not
   authoring).
6. **Report (FORGE)** — mission-control PDF / debrief. Unchanged in purpose.

### Secondary, role-gated cluster (right of a divider)

Reference / registry / diagnostic screens, grouped so same-subsystem tabs are adjacent, gated to
operator+/director exactly as today: **Fleet (LODE) · Construction (FORGE) · Models (FORGE) ·
Trainer (DART)**. Promoting the existing permission gate into a visual "primary | reference" divider
matches the permission model already in the markup.

### Chrome (far right, unchanged)

Alerts bell · Workspace badge · Account menu (Settings / System / Admin).

## Decided sidebar (Plan `#ctx-plan`): 7 panes -> 4

Keep the numbered authoring spine but compress it:

1. **Site**
2. **Contents**
3. **Rovers** (renamed from "Fleet" to break the collision with the Fleet tab)
4. **Plan** — queue + feasibility + files/catalog combined, specifically:
   - **MOVE (do NOT remove)** the old `4 Feasibility` controls into the `5 Plan` section as a sub-step.
     **Correction (2026-06-23, found by reading the code):** the Feasibility inputs are LOAD-BEARING, not
     a removable duplicate — `padW`/`padL`/`cut`/`bermH`/`est` drive `estimate()` (cockpit.js:2270 +
     input listeners at :2600) AND the "Pad cut" order convenience (:3495-3501). The restructure must
     reparent them with **every id + listener preserved**; removing them breaks the live estimate and the
     pad-cut quick-order. (The original "remove the duplicate" wording was wrong.)
   - **FOLD (move, preserve ids)** the old `6 Catalog` (`msname`/`mssave`/`msnotes`/`mslist`/`stname`/
     `stsave`/`stlist`, all wired) into the Plan "files" substep — one save / load / template home.

Removed-from-position (moved, not deleted): `7 Telemetry` (`telerail`/`telespark`/`drumkg`/`drumnoise`/
`drumout`, wired) relocates to the Execute pane. Collapse the four pointer-only context blocks
(nav / perception / metrics / report `#ctx-*`) into their pane headers, keeping only the live summary line.

**Verification caveat for the sidebar stage:** the screenshot harness (`scripts/cockpit_harness.py`) only
captures the default state — it will NOT catch a silent wiring break (e.g. `estimate()` no longer firing
after a moved input). Sidebar-restructure stages require INTERACTIVE Playwright checks (fill `padW` →
assert `#est` updates; click the pad-cut convenience → assert an order is appended) in addition to the
page-error/screenshot pass.

## Cross-cutting

- Extend the existing **drag-to-reorder + named-layouts** mechanism (currently sidebar-only) to the
  **top tabs**, so an operator can reorder/save a tab layout.
- Subsystem badges (LODE / LEAP / DART / FORGE) stay, but the new order makes same-subsystem tabs
  adjacent within each cluster.

## Implementation surface

- `stewie/server/web/assets/cockpit.js` (~4300 lines) — the nav tab definitions, the view-switcher,
  the sidebar `#ctx-plan` structure, the role-gating, and the drag-reorder/named-layout code.
- The ES-module render files (e.g. `three3d.js`) for any pane-content moves.
- New "Validate" tab = compose the existing `#navview` + `#renderpanel` panes under one tab with a
  sub-tab switcher (do not rewrite their internals — move/wrap).
- New "Release" surface. **Correction (2026-06-23, found by reading `stewie/server/routers/executive.py`):**
  there is NO GET state endpoint and no persistent executive — `POST /executive/advance` is a one-shot,
  director-gated call that takes a full `MissionIntent`, runs the entire DRAFT→ANALYZED→REHEARSED→REVIEWED
  →RELEASED lifecycle (`lode.mission_lifecycle.run_lifecycle`), and returns the reached state + signed
  revision + evidence (plan_id, forward_compare) + transition log. So Release is an ACTION surface, not a
  display: it must (a) build a valid `MissionIntent` from the cockpit's current plan/queue (the cockpit
  already constructs mission payloads for `/plan` — reuse that), (b) POST it, (c) render the returned
  state/revision/evidence/log. Open design choices (need a decision before building): which intent it
  submits (the current queue? a named mission?), how the operator selects it, and the result layout. This
  makes Release a real integration, not a quick additive pane.
- After ANY `cockpit.js` / `three3d.js` change: run `python scripts/stamp_cockpit_version.py` to
  re-stamp the `?v=` content hashes (CI `stewie/server/test_asset_version_stamp.py` fails on a stale
  stamp). Do NOT hand-edit `?v=`.

## Verification (mandatory before any deploy)

- **Playwright visual verification, done in-session** (per standing rule): sign in, screenshot each of
  the 6 spine tabs + the secondary cluster + the restructured sidebar, assert each renders without a
  console error and the empty-state copy is honest. The cockpit is the public surface
  (`app.stewie.space` via Cloudflare -> the frontend container); a CI-green build does NOT prove the
  layout is right — only the screenshots do.
- Then update docs/code-comments/CLAUDE/PRD to match the new structure (the "organize and update all
  docs" part of the task).

## Why this is held for a user-present session

This is a high-blast, visual, public-surface change. The deploy is outward (it changes what every
visitor to `app.stewie.space` sees), and visual-craft work is reviewed best round-by-round with the
user's eyes on the result. Backend batch items (FL-03, Chrono, render/ROS seams) were safe to push on
green CI; a nav reorg is not the same category. Implement + Playwright-verify, then show the
screenshots and get the call before the public deploy.
