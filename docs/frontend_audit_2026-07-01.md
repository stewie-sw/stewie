---
title: Frontend Visual + Engineering Audit (2026-07-01)
nav_order: 56
---

# Frontend audit — 2026-07-01

Method: full-surface capture of the running cockpit (dev-open director, real Haworth DEM backend, a
real mission plan executed mid-capture; 22 screenshots: 13 desktop panes, 4 phone-width, live-data
states, /program board, landing) + five independent review lenses (planning workflow, live-ops
observability, visual craft, human factors, sustainable engineering), each grounding findings in a
screenshot or file:line. 46 findings total; the load-bearing ones were re-verified by hand before
this write-up. Fix philosophy throughout: strangler-fig increments, no rewrites.

## Verified-and-fixed same day

- **Cache-bust coverage hole (critical, CONFIRMED, fixed):** `cockpit_state.js` was stamped with a
  stale hash and `adapters.js`/`panel_layout.js`/`idle_logout.js` carried unchecked hand labels
  (`?v=fs15a1`, `?v=1`) — the exact stale-Cloudflare-edge failure the stamp gate exists to prevent,
  invisible because both the stamp script and the CI test used hand-maintained tuples.
  `stamp_cockpit_version.py` + `test_asset_version_stamp.py` now DERIVE the asset list from each
  page's own `?v=` references; all four stamps corrected.

## Top findings by theme (full detail: the five lens reports)

### 1. The pipeline is presentational, not enforced (planning lens — the big one)

- `validateStep` keys solve/review/execute readiness to the same predicate (`!!LAST_TIMELINE`,
  cockpit.js:5764-5766): the rail shows **"Mission ready ✓" with no rehearse, no validation, no
  release**. Release itself gates on `ORDERS.length` only.
- Two competing six-step vocabularies on every screen: tabs (Plan/Rehearse/Validate/Release/
  Execute/Report) vs the CONOPS strip (SITE/FLEET/ORDERS/SOLVE/REVIEW/EXECUTE). On Rehearse the
  strip lights SOLVE; Release has no strip slot at all (cockpit.js:5824-5825).
- Rehearse is display-only: candidate cards have no adopt action and the released plan records no
  solver/candidate linkage (release POST body omits it, cockpit.js:2175).
- **Release signs blind**: the pre-sign pane shows an order COUNT and a button; hash, feasibility,
  margins, and queue contents appear only after the irreversible sign-off — and it is the only
  major action with NO confirm dialog while trivial reversible ones have one (cockpit.js:2168).
- Execute dead-ends after a real plan: stale "No mission loaded" canvas (paintExecIdle early-return,
  cockpit.js:5039), all-dash telemetry, playback trigger hidden back on the Plan sidebar, and two
  near-identical buttons ("Play SIM run" vs "Run (SIM)") that differ by an entire authority tier.

Improvements (all component-local): real per-stage predicates in `validateStep`; one global spine
(fold the CONOPS strip into Plan-only sub-progress); "Use this candidate" on rehearse cards carried
into the release body; a pre-sign evidence card + `window.confirm` on Release; hydrate Execute from
the last run_id and rename the two run buttons to encode authority ("Replay forecast" vs "Execute
on sim (MO-02)").

### 2. "Seeing everything live" is mostly not yet live (ops lens)

Good bones (TRAINING/LIVE badge, UI-6 alert center, UI-5 stale sweeper, honest what-if labels), but:
run state is ephemeral (run_id never persisted → Execute shows nothing after the fact); no link/comms
chip (an off RC stream is an unlabeled black canvas — indistinguishable from a dropped link, and
`renderRcTelemetry` never calls `markFresh` so the stale sweeper can't fire); `/healthz` is read once
at boot (a mid-session audit/revocation degradation changes nothing in the chrome); Fleet is a static
datasheet with no SoC/pose/last-seen; the Report's forecast chips ship with NO provenance label
(PO-10 is a P0); no mission clock anywhere. The improvements are one pattern applied five times:
persist + rehydrate, and put a small always-on chip in the chrome (health, link, mission time,
provenance) fed by data the app already has.

### 3. Visual craft: strong foundation, degrading at the edges (craft lens)

- **Mobile chrome collision (critical):** at 390px the TRAINING pill overlaps/clips the RELEASE tab
  and "? Guide" overlays the stepper on every captured phone view — the safety badge becomes
  illegible exactly where the operator taps (index.html:230-234 MOBILE-05 sticky rule).
- Color semantics fighting themselves: "retired" blue still leaks (native sliders, .site button
  borders #2f4a78, a blue **delete** next to a red "reset pw" in Admin); drum-red is simultaneously
  brand accent, danger, Gantt data ink, and the /program board's "buildable now" positive state.
  One-line wins: `input[type=range]{accent-color:var(--accent)}`, a `.site.danger` modifier, and a
  board palette remap.
- Live-data plots are the weakest tier: the post-plan ACTIVITY Gantt is a solid red barcode (92
  recharges over 2449 h, one bar per frame, cockpit.js:4955); MISSION LOCALIZATION renders one green
  dot in an empty grid (navplot viewport not fitted to data); the report iframe is a giant pure-white
  rectangle in a dark-adapted console (index.html:346 `background:#fff`, no load state).
- Map label pileup at the work site ("HAW…TILE/cul…ashout/WORK AREA" garble at boot zoom, desktop +
  mobile) — needs `distanceDisplayCondition` tiers.
- Landing route: prod nginx serves it at the apex, but a direct `/landing.html`/`/landing` URL
  proxies to the backend and returns raw JSON 404 — add the one-file pages route (program.py
  pattern). Downgraded from the lens's "critical" (production apex is fine).

### 4. Human factors (interaction lens)

Real investment visible (ARIA tablist + arrow keys, focus rings, Ctrl+Z authoring undo, honest empty
states) — the remaining failures are concentrated: the irreversible action has the least friction
(above); six of thirteen work areas are undiscoverable by construction (display:none until role
resolves, no cue when they appear — announce unlocks via the existing alert rail + list them locked
in the Guide); the two nav rows force a 6→7 item recall mapping ("Review"=Report, tab "Execute" is
internally `data-view="metrics"`); the ~10 s solve has no global busy indicator; jargon as primary
labels ("Run Katwijk estimator", FS-05/FS-21 codes in operator-facing copy); 44px touch-target rule
skips range sliders.

### 5. Sustainable engineering (code lens)

- The strangler-fig has stalled at the leaves: 25+ pure modules / 232 node tests cover ~2,900 lines,
  while cockpit.js is still **5,882 lines (62.5% of hand-written JS), 147 top-level mutable
  bindings, 98 raw fetch() sites, 122 innerHTML sinks, zero direct tests**.
- The declared architectures are aspirational: `toViewState` (FS-15's typed loading/error/empty
  contract) has **zero call sites**; `STEWIE_STATE` routes only workArea while site/vehicle/mode
  live in ad-hoc globals; `panes/ephemeris_pane.js` is tested but loaded by no page (dead in tree).
- Tokens have already forked: `--accent` is #ef3a52 in the cockpit/program board but #C8102E on the
  landing; 334-line inline style block duplicated per page.
- Next five moves (in order): (1) the page-derived stamp gate (DONE today); (2) `api.js` — a ~40-line
  tested `apiFetch` wrapper that routes through `toViewState`, migrating one pane per PR (metric:
  fetch() count down from 98); (3) route CURRENT_SITE + _validateSub through ROUTE_STATE (one field
  per PR); (4) wire ephemeris_pane as the first real pane mount, then extract the five loadX pane
  wirings (~800 lines out of cockpit.js mechanically); (5) one CI Playwright smoke job (~80 lines:
  boot, click the six spine tabs, assert zero console errors + one landmark per pane) — the entire
  recent regression class (unrun JS tier, stale stamps, pane wiring) lives in the untested shell
  layer that the 232 pure tests structurally cannot reach; (6, cheap) extract `theme.css` tokens
  shared by all three pages and reconcile the forked accent.

## Priority order (if only five things get done)

1. Real stage predicates + Release confirm + pre-sign evidence card (safety + honesty of the core loop).
2. Mobile chrome collision fix (the safety badge must never occlude a tab).
3. Execute rehydration from the last run + link-state chip (turns a replay viewer into an ops console).
4. CI Playwright smoke tier (locks in every fix above against the untested-shell regression class).
5. Gantt/localization plot scaling + report-iframe dark loading state (the "money shot" after a real
   plan currently looks broken).
