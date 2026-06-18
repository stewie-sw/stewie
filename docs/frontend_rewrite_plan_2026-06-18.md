# STEWIE Cockpit Front-End Rewrite Plan (vanilla JS to React + TypeScript)

**Date:** 2026-06-18
**Status:** PROPOSED, awaiting Aaron's go on the decision points in §9.
**Scope:** Front-end only. The Python backend (25 routers, the FS-02 contract spine, all domain
modules) is UNTOUCHED. This replaces the browser cockpit, not the server.

---

## 0. Why rewrite (the evidence)

Measured on the current tree, not opinion:

- `web/assets/cockpit.js` is a **264 KB monolith**: 216 functions, 40 `addEventListener`, **65
  `innerHTML` assignments**, 92 `createElement`/`querySelector`. Those 65 hand-rolled
  string-template re-render sites are the maintainability and XSS/perf footgun.
- The team is **already hand-building a UI framework's primitives**: `cockpit_state.js` (a state
  store), `adapters.js` (typed view models for all 10 spine contracts), `panel_layout.js`,
  `panes/ephemeris_pane.js` (a function component with a render fn + unit test). PRD **FS-24** is a
  description of a component framework written as a requirement.
- The forward work (Fleet, the autonomy seam, ARGUS evidence, Perception, Models registry, the
  command/approval rail, live telemetry) is heavily stateful and data-bound. That is precisely the
  work imperative DOM is worst at.
- Claude Design (claude.ai/design) emits **React**. A React cockpit is what lets future UI be
  designed there and map 1:1 onto shippable code (see §8).

**Decision:** full rewrite to React + TypeScript, reaching deletion of `cockpit.js`, executed via a
**strangler path** (§5), not a literal parallel big-bang.

---

## 1. Target stack (recommended)

| Concern | Choice | Why / alternative |
|---|---|---|
| Framework | **React 18 + TypeScript** | Claude-Design-native; types matter for the contract spine. Alt: **Preact** (~3 KB, drop-in API) if bundle size dominates; **Lit** web-components if avoiding React entirely (not Claude-Design-native). |
| Build | **Vite** | Fast, standard, emits hashed assets into `/assets/`. Alt: esbuild directly (lighter, less batteries). |
| State | **Zustand** | Tiny, no boilerplate, maps cleanly onto `cockpit_state.js`. Alt: Context (simpler, more re-renders) / Redux Toolkit (heavier). |
| Data | thin `fetch` + the existing view models, wrapped in **TanStack Query** for cache/loading/error | reuses `adapters.js` normalizers directly. |
| Types | **generate TS types from `GET /contracts/schema`** (`json-schema-to-typescript`) | the Pydantic contract spine becomes the single source of truth for FE types; extends the parity guarantee we just shipped so FE types cannot drift from the backend. |
| Test | **Vitest + React Testing Library** (component) + **Playwright** (e2e/visual) | port the existing `node --test` adapter/state tests to Vitest; Playwright per pane (visual verification is required). |

---

## 2. The binding constraint: CSP (must be resolved in Phase 0)

Production CSP (`deploy/nginx.conf:46`) is:

```
script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval' blob: https://static.cloudflareinsights.com
```

There is **no `'unsafe-inline'` for scripts**. Vite's default production build emits a small inline
module-preload bootstrap, which this CSP would **block**. Phase 0 must prove one of:

1. Configure Vite to emit **zero inline scripts** (`build.modulePreload.polyfill = false`, verify the
   emitted `index.html` has only external `<script src>` tags), or
2. Add a per-response **nonce** via nginx `sub_filter` (more moving parts; only if (1) is insufficient).

`'unsafe-eval'` / `'wasm-unsafe-eval'` are already present (Cesium/wasm need them), so React itself is
fine. This is the single highest-risk unknown and gates the stack choice. **Do not commit the stack
until a CSP-clean Vite build is verified against the real deployed headers.**

---

## 3. Target architecture (realizes FS-24 + FS-03 + FS-15/16)

```
app shell (layout, routing)
 ├─ route/state store (Zustand)            <- replaces cockpit_state.js
 ├─ auth/role context (AG-01 ladder)        <- guest<trainee<operator<director
 ├─ typed API adapters (TS)                 <- adapters.js view models, now typed
 ├─ generated contract types                <- from /contracts/schema
 ├─ shared viz components                   <- Cesium globe + three3d.js wrappers (imperative, §4)
 ├─ work-area views                         <- Plan / Fleet / Navigation+Autonomy / Perception /
 │                                              Construction / Models / Metrics / Report
 ├─ command/approval rail                   <- AG-08 gated, SF-01 interlock, FS-17 single authority
 └─ diagnostics/log viewer                  <- FS-19 observability ledger
```

---

## 4. WebGL / 3D: the integration that needs care

Cesium (the globe) and `three3d.js` (the in-cockpit 3D playback) are **imperative WebGL/canvas
APIs**. They must NOT be re-rendered by React. The pattern: a thin React component owns the
mount/unmount lifecycle (`useEffect` + a `ref`), creates the Cesium/Three viewer once, and pushes
prop changes via imperative calls (`viewer.entities.add(...)`, not JSX). React owns *when* it lives,
not *what* it draws. This is Phase 4 and the trickiest seam; budget for it.

---

## 5. Migration strategy: full rewrite via strangler (recommended)

1. Stand up the React shell served at a parallel route (or behind a feature flag) alongside the live
   vanilla cockpit.
2. Port **one work-area at a time**; each ported area consumes the view models and passes the same
   Playwright checks its vanilla twin did.
3. **Delete the corresponding vanilla code as each area lands.** `cockpit.js` shrinks monotonically.
4. Final cutover removes the last of `cockpit.js` + the vanilla helpers.

The app stays shippable and CSP-clean throughout; no flag-day. A pane is never deleted from vanilla
until its React replacement is verified.

**Alternative (NOT recommended): literal parallel big-bang.** Build the entire React app on a long
branch, cut over once. Higher risk (flag-day regression surface, long no-merge divergence, the live
cockpit keeps changing under you). Only sane if the vanilla cockpit can be frozen for the duration.

---

## 6. Phased execution

Every phase: TDD (Vitest/RTL) + Playwright visual verification + CI green + deploy to a staging route
before prod. No vanilla deletion until the React twin passes.

- **Phase 0 — Foundations + CSP spike.** Vite + TS + Vitest + RTL scaffold; resolve §2 (CSP-clean
  prod build served by the existing nginx at a staging route); wire TS type-gen from
  `/contracts/schema` into CI; port `panes/ephemeris_pane.js` as the proof-of-loop.
  **Gate:** CSP-clean build deployed to staging + ephemeris pane Playwright-verified end to end.
- **Phase 1 — Shell + cross-cutting.** App shell, router, auth/role context, **FS-17** single
  command-authority election, **FS-16** routeable state, **FS-20** chrome IA (profile menu), idle
  logout. **Gate:** login to role-gated shell; two-tab command-authority preserved (Playwright).
- **Phase 2 — Data-light areas.** Report, Metrics, System/Settings/Admin (operators, invites,
  **FS-19** audit-log viewer). Mostly tables/forms.
- **Phase 3 — Stateful areas (the high-value ones).** Plan authoring, Fleet, Navigation+Autonomy
  (nav contract, Plan IR + posture plan, the command rail under AG-08/SF-01), Perception/ARGUS
  evidence. These are where the 65-innerHTML pattern hurts most and React pays off most.
- **Phase 4 — WebGL/3D wrappers.** Cesium globe + `three3d.js` as React components per §4.
- **Phase 5 — Cutover + cleanup.** Delete `cockpit.js` + vanilla helpers; full Playwright regression
  (desktop + mobile) across every work-area; CSP re-audit; deploy via the cloudflared path; bump the
  asset cache version (the `?v=` / Cloudflare edge-cache trap).

---

## 7. Risks and mitigations

| Risk | Mitigation |
|---|---|
| CSP blocks Vite inline bootstrap | Phase 0 hard gate (§2); stack not committed until proven |
| Cesium/Three.js re-render hazards | Phase 4 imperative boundary (§4) |
| Two-paradigm window during migration | strangler + per-pane delete keeps it bounded and shippable |
| Undocumented behavior in 264 KB | **build the FS-23 ledger FIRST (§10)**: map each pane's routes/state/behavior before porting it |
| Deploy/cache pipeline change | Phase 0 proves the new build on staging through the real Cloudflare path |
| Test-coverage parity | port node tests to Vitest + add RTL + Playwright per pane; the parity test extends to generated types |
| AG-08 / SF-01 / role gating regressions (security-critical) | dedicated tests carry over; command rail is Phase 1/3 with explicit two-tab + role Playwright checks |

---

## 8. Claude Design enablement (the design-sync tie-in)

Once Phase 1 (shell) plus a handful of components exist, optionally **extract the shared components
into a packaged component library with a real `dist/` bundle**. That packaged library is what
`/design-sync` uploads to claude.ai/design, so future cockpit UI can be designed there and emitted as
real, on-brand React that maps 1:1 onto this codebase. This is why the rewrite unlocks design-sync;
the current app-shaped repo cannot be synced. **Decision: extract the library during the rewrite
(more upfront discipline, earlier Claude Design payoff) vs after (faster rewrite, design-sync later).**

---

## 9. Decision points for Aaron (before Phase 0)

1. **Stack:** React + TS + Vite (recommended) vs Preact vs Lit web-components.
2. **Path:** strangler (recommended) vs literal parallel big-bang.
3. **State lib:** Zustand (recommended) vs Context vs Redux Toolkit.
4. **Component-library extraction for Claude Design:** during the rewrite vs after.

---

## 10. Prerequisite, do first regardless of the above: the FS-23 ledger

Before porting any pane, build the row -> route -> module -> view -> test ledger (FS-23, the
architecture-review map). You cannot safely rewrite what you have not inventoried; this is the
"capture current behavior" artifact that every Phase-N port checks itself against. It is also the
deliverable that answers the broader "map all the intricacies to the front end" question independent
of the rewrite, so it is useful even if a decision point above stalls.

---

## 11. Information architecture (settled 2026-06-18 with Aaron)

This locks the FS-03 work-area set and the windowing/sim-vs-truth model for the rewrite. It is the
answer to "how do we set up sim vs truth, and how many panes/windows".

**Sim vs truth = two orthogonal axes (never one toggle), plus a hardware firewall.**

- **Mode** (the truth boundary, PRD §5): a 5-mode explicit, always-labeled selector on the top bar:
  `GIS-PLAN` / `TRAIN` / `SIM-OPERATE` / `EVALUATE` / `OPERATE`. Role-gated (EVALUATE/OPERATE need
  elevated roles); defaults to the safe end. "Simulated truth must never be presented as a live
  measurement."
- **Source** (provenance per layer/number, PO-10): a `forecast / truth / belief / live` toggle.
  Mapping to §6.1 artifacts: forecast = `PlanResult`; truth = `WorldState` conserved authority;
  belief = `BeliefState` + `TwinStore` observed twin; live = `RuntimePacket` telemetry. **The Truth
  layer is selectable only in SIM-OPERATE/EVALUATE and is absent/greyed in OPERATE** — there is no
  truth channel on real hardware, so belief can never masquerade as truth. The forecast-vs-truth and
  belief-vs-truth divergence (the reality gap) is the product's core value.
- **Hardware firewall** (orthogonal, already built): real commands require live namespace (AG-07) +
  operator+ (AG-02) + OPERATE mode + the SF-01 dead-man watchdog (AG-08). All four, or it is a
  simulation.

**Window model:** ONE command-authority cockpit (FS-17, enforced by the `CMD_AUTH` election).
Secondary windows are read-only satellites or external ROS/RViz tools; they can never command.

**Layout:** a persistent **Map/World canvas** at center (Cesium globe + local DEM; the four source
layers stack here with provenance tags — this is where the reality gap is seen), a left
**work-area rail**, and a right **context/command rail** (selection details + the AG-08 command
controls, armed only in OPERATE + live + operator under SF-01). Chrome (System/Settings/Admin) lives
in a `☰` profile menu (FS-20), not the work-area bar.

**6 work areas (FS-03):**

1. **Plan** (L6) — authoring (orders, footprints, keep-outs, sequencing) AND fleet in one flow
   (`Rovers: N`; allocation/conflicts surface when N>1). Forecast source. (Plan+Fleet merged.)
2. **Navigation / Autonomy** (L5) — routed paths, nav contract (`/nav/contract`), Plan IR + posture
   plan, the command/approval rail.
3. **Perception** (L4) — camera frames, stereo depth, the observed map (TwinStore), ARGUS evidence.
4. **Metrics / Execution** (L7) — timeline: forecast-vs-actual, seen-vs-truth divergence (TRAIN
   director view), energy/time, sim run / live playback.
5. **Models** (L4) — the ML registry, deployment-ready gating (ML-01).
6. **Reports** (L7) — mission-control report output.

**Count: 1 window · 5 modes · 4 sources · 1 map canvas · 6 work areas · 1 command rail · chrome menu.**

This supersedes the current 7-tab set (Plan / Fleet / Navigation / Perception / Metrics / Report):
Fleet folds into Plan, the map becomes a persistent spine rather than an implicit backdrop, and
Models becomes a first-class work area.
```
