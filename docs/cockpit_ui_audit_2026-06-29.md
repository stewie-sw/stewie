---
title: "Cockpit UI/UX audit (2026-06-29)"
nav_order: 57
---

# STEWIE cockpit UI/UX audit — decision matrix (2026-06-29)

A 3-reviewer LLM-council audit of the live cockpit (dev-open bypass at :8799 + screenshots in the
session's ui_audit set), against Aaron's 12 issues. Each verdict is file:line-grounded and confirmed
against the running app. Verdict legend: **BUG** (broken) · **WIRE** (capability exists backend, UI
wire missing) · **UX** (works, presentation fix) · **DECIDE** (needs Aaron's call) · **NOT-A-BUG**.

| # | Issue (Aaron's words) | Verdict | Confirmed state (file:line) | Fix | Pri | Eff |
|---|---|---|---|---|---|---|
| 1 | Pointer coords still show in Navigation sidebar | NOT-A-BUG (+defensive) | `#cursorcoord` is tab-scoped + hidden off-Plan (cockpit.js:866); only the floating `#cursorxy` (index.html:842) could freeze on a fast pointer-exit | unconditional hide of `#cursorxy`/`#cursorcoord` in `setView` when name≠plan (cockpit.js:876) | P2 | S |
| 2 | Work area predefined top-left, can't change | WIRE | NOT top-left — `flattest_anchor` picks the flattest patch (site_dem.py:139); the M11 lat/lon re-anchor works end-to-end (plan.py:321); but a globe CLICK never writes `#lat/#lon` (setPicked cockpit.js:727) | setPicked writes `#lat/#lon`.value so a click re-anchors the next plan; BYO-DEM stays #237 | P1 | S |
| 3 | Redundant flat "LAYERS" block under Contents | UX | `#layerpanel` (index.html:608) duplicates the grouped contents-tree; kept in lockstep by `syncLayerStripCheckbox` (cockpit.js:3356). Only `excavation` lacks a standalone tree toggle | fold an `excavation` row into the tree's Operations group, THEN delete `#layerpanel` + `loadLayers` flat branch + the sync shim (keep `LAYER_ON` default seeding) | P1 | M |
| 4 | Robot emoji on "🤖 Rover 1 · IPEx" | BUG (cosmetic) | `&#129302;` prefix in `renderFleet()` cockpit.js:5203 | delete the `&#129302; ` prefix | P2 | S |
| 5 | 4b should autoload last-known location | WIRE | 4a=Plan§A "Where are we" autoloads LAST_POSE ✓ (cockpit.js:3047/3055); 4b=Plan§B "Traverse" hardcodes wpx/wpy=0 (index.html:470), no LAST_POSE seed | seed `#wpx/#wpy` from LAST_POSE on load; no-location empty-state ("place rover in step A, or traverse starts at origin 0,0") | P1 | S |
| 6 | 100m ring should be adjustable | WIRE+DECIDE | `LANDER_RING_M=100` const (cockpit.js:3500), checkbox-only (index.html:461); adjustable-circle precedent = keep-out `#kor` (cockpit.js:441) | const→let + a number input next to the checkbox, persist + redraw (plumbing at 3507 exists). **Aaron: default/min/max? 2D-only or also 3D?** | P2 | S |
| 7 | 3D map: no coord overlay, no markers (waypoints/lander/rovers/marks) | BUG/feature (HIGHEST VALUE) | globe CAN render entities (dropPin/dropKeepout/graticule/cursor-coord all exist) but they fire only in EDIT mode (cockpit.js:228); ORDERS/KEEPOUTS/routes/imports draw ONLY on the 2D plancanvas — no `syncPlanToGlobe` | add `syncPlanToGlobe()` called from drawPlan: clear a dedicated PLAN_GLOBE_ENTS layer + re-drop orders/keep-outs/route via local→lonlat (`/dem/site_lonlat`), gated by a Contents toggle | P0 | L |
| 8 | Feasibility tab — what does/should it show? | UX | No standalone tab anymore — folded into Plan§4 as a dig-only quick estimate (cockpit.js:2754), honest + IPEx-grounded, defers to the solver | promote to a real labeled header + a meaningful `#est` empty-state (not "—"); optional green/amber feasibility badge | P2 | S |
| 9 | Create+import a test file to verify it works | BUG (import-load) | Server pipeline PROVEN end-to-end: import→plan→export→**5-page PDF** round-trips EXACTLY (real HTTP). But `gisImport()` (cockpit.js:4273) prints a count and NEVER pushes results into ORDERS/KEEPOUTS | on success: push `b.orders`→ORDERS, `b.keepouts`→KEEPOUTS, then renderQueue/renderKeepouts/drawPlan | P0 | S |
| 10 | Validate / Execute / Report — usable & beneficial? | UX | ALL show real content + honest empty states (real Haworth DEM, 8-cam Godot render, 65k-pt stereo cloud, real PDF). Execute is density-cramped | Execute: collapsible cards / 2-col + a persistent status bar; Validate: in-pane jump-nav for the 4 stacked panels | P2 | M |
| 11 | Execute/Report/Fleet/Construction/Models/Trainer — necessary? placeholders? stack under sub-nav? | BUG (boot) + DECIDE | All 6 are REAL backend-wired views (loadFleet→/fleet etc.), not placeholders. The 6 role-gated tabs stay hidden because `refreshAuthState` short-circuits `/auth/me` with no cookie (cockpit.js:1710) — so dev-open/first-load never reveals them | fix the boot probe (always try `/auth/me`, treat 401 as signed-out). **Aaron: group Fleet/Construction/Models/Trainer under one "More ▾" overflow?** (Rehearse/Release stay in the spine) | P1 | S–M |
| 12 | Hamburger "|||" placement / overlap | NOT-A-BUG | The `⠿` (cockpit.js:1441) is a non-destructive drag-to-reorder handle; `☰` `#drawerbtn` does not overlap the panel at desktop width (confirmed) | optional: swap the glyph for an icons.js drag glyph for legibility | P3 | S |

## Sequenced plan

**Batch A — clear bugs / hidden wires, low-risk (this tick):** #9 import-load, #4 emoji, #1 defensive
coord hide, #2 click-to-anchor, #5 4b LAST_POSE seed. All small, additive, frontend-only, Playwright-verifiable.

**Batch B — P0 high-value, larger (next):** #7 `syncPlanToGlobe` (the globe should mirror placed
features — the single biggest "the globe looks empty" complaint), #11 boot-probe fix (unhide the
role-gated views).

**Batch C — UX restructure (after):** #3 LAYERS de-dup (fold excavation first), #10 Execute regroup,
#6 ring control, #8 feasibility labeling, #12 grip glyph.

**Aaron decisions:** #6 ring default/min/max + 2D-vs-3D; #11 group the 4 secondary tabs under a
"More ▾" overflow vs leave inline; #2/#237 bring-your-own-DEM is the real "change the work area"
feature (separately scoped).
