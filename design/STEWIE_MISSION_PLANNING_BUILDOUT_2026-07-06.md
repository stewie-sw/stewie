# STEWIE Mission-Planning Buildout — Artemis GIS IDE

**Date:** 2026-07-06 · **Scope:** rebuild the SKELETON mission-planning capability in the QWC2
lunar IDE (`artemis.stewie.space/ide/`) into the real thing. **Analysis + plan only** — no app code
here. All "exists" claims are grounded at `file:line` (paths relative to `/mnt/projects/stewie/code`).

---

## Executive summary

Mission planning is **backend-rich and GIS-thin**. The planner already does cut/fill mass-balance,
DEM-aware least-cost routing, battery-aware recharge scheduling, multi-vehicle fleets, a full sequencer
suite (nearest/greedy/2-opt/or-opt/LK/Held-Karp), an executable Plan IR with a precedence DAG,
as-built acceptance, a 2–3 page PDF report, and a SIM execution loop — all reachable. The GIS
`MissionPlan` plugin today exercises only the **thin spine**: place raw cut/fill orders → `POST
/api/plan` → draw the routed plan → run-SIM. It ignores most of what the planner returns and exposes
none of the levers the planner accepts.

- **~85–90% of mission planning is backend-ready-to-rebind.** 8 of 10 capabilities have a working
  backend reachable through the two key-injected routes the IDE already uses (`/api/plan`,
  `/api/executive/run`). Most of the rebuild is **surfacing data already in the `/plan` response**
  (timeline, plan IR, validation, per-vehicle routes) and **adding input levers that pass through the
  SAME POST** (keepouts, budgets, fleet size, algorithm/objective, slope budget). Zero new planner
  logic, zero new backend, zero infra for those.
- **Net-new is small and mostly UI.** No capability needs new planner code. Two capabilities
  (structure-template authoring; forward-compare/ConOps Release) are backend-complete but **gated by
  the artemis proxy** — they 401 because only `/plan` + `/executive/run` + the run-stream are
  key-injected (`deploy/artemis-nginx.conf:139,164,179`). Unlocking them is a small deploy-host nginx
  change (add keyless server-side proxy blocks for the non-destructive planning routes), not code.
- **Top 3 to build first (all pure GIS rebind, zero infra):** (1) **Keep-out draw tool** →
  `payload.keepouts` on the existing `/api/plan`; (2) **Plan controls** — algorithm + objective +
  slope-budget + resource-budget levers, all passed through the same POST; (3) **Multi-vehicle fleet**
  — `vehicles` + `charger_capacity` inputs with per-vehicle route rendering.

---

## Reachability model (how the artemis `/api/` proxy gates the backend)

`deploy/artemis-nginx.conf` fronts the public IDE. Three tiers:

| Tier | Routes | Reachable from `/ide/`? |
|---|---|---|
| **Key-injected** (secret added server-side) | `POST /api/plan` (`:139`), `POST /api/executive/run` (`:164`), `GET /api/executive/run/{id}/stream` (`:179`) | **Yes** — the shared key is injected; browser never sees it. |
| **Public GET** (backend route has no auth dep) | `/api/layers/globe/{kind}.png` + `/bbox`, `/api/evidence`, `/api/sample_missions` + `/sample_mission/{name}`, `/api/solar`, `/api/ephemeris`, `/api/world/{layer-catalog,traffic-layer,terramechanics-layers,layer-consumption}`, `/api/export/*`, `/api/reports/*`, `/api/contracts/schema`, `/api/layers` | **Yes** — generic `/api/` block (`:120`) forwards **no** credential; these routes don't require one. |
| **Auth-gated, NOT key-injected** | everything with `Depends(require_auth/role/director/heavy_quota)` and no exact-match block: `/plan/math`, `/plan/commands`, `/resync/compare`, `/layers/raster`, `/construction`, `/structure`, `/structures/custom/*`, `/executive/{advance,release-plan,audit}`, `/dem/*`, `/missions/*`, `/world`, `/nav/*` | **No — 401.** Needs either a new keyless proxy block (the `/plan` pattern) or the backend route made public. |

**Consequence for the rebuild:** any capability that rides `/api/plan` or `/api/executive/run` is a
pure GIS rebind. Anything needing `/construction`, `/resync/compare`, `/executive/release-plan`, etc.
is blocked on a small deploy-host proxy change first.

---

## (a) Capability inventory

| # | Capability | Backend exists? (`file:line`) | Artemis-reachable? | In GIS today? | Effort | Reuse vs net-new |
|---|---|---|---|---|---|---|
| 1 | **Structure-level authoring** (LandingPad/HaulRoad/BlastWall/SolarPad/HabitatFoundation/BorrowPit/CraterFill → auto mass-balanced cut/fill) | **Yes.** `leap/structures.py:116` `STRUCTURES` (8 templates), `:123` `decompose()`; per-template mass-balanced orders (`landing_pad:50`, `blast_berm:74`, `crater_fill:86`, …). Routes: `construction.py:66` `GET /construction` (expands all w/ defaults), `perception.py:378` `POST /structure` (one at x,y). | **No** — `/construction` = `require_role("operator")`, `/structure` = `require_auth` → 401. Needs a keyless proxy block or public route. | **No** — `planAuthor` only places raw cut/fill. | **M** (+**S** infra) | Reuse `decompose`; net-new = template palette UI + proxy unlock. |
| 2 | **Keep-outs / avoid-regions / hazard constraints** | **Yes.** Parsed `planner_model.py:394-421` (circle `{x,y,r}` / rect / polygon), field `:209`; consumed in routing `planner_trips.py:156,181,296` + `planner_views.py:449,477` (plan_ir) + costmap `costmap_layers.py:159`. `/plan` accepts via `plan.py:64` (`extra="allow"`) + cap `:37,48`. | **Yes** — same `POST /api/plan`. | **No** — no draw tool in `planAuthor` (nor in Frontend A `gis/web/app.js`). | **M** | **100% reuse**; net-new = OL draw interaction only. Zero backend. |
| 3 | **Executable Plan IR** (typed actions + precedence DAG + versioned `plan_id`) | **Yes.** `planner_views.py:413` `plan_ir` — GoTo/Excavate/CutHaulFill/Import/Sinter, precedence DAG `:508`, deterministic `plan_id`, `PLAN_IR_VERSION`. Returned by `plan.py:323,390`. | **Yes** — already in the `/plan` response. | **Partial** — `planAuthor.js:346-361` consumes `plan_ir.actions` to draw routes/haul, but no IR inspector/download, no DAG view, no editing. | **S** (view) / **L** (edit) | Reuse the IR in-hand; net-new = inspector + download; editing = net-new (re-plan round-trip). |
| 4 | **Resource budgets as levers** (energy/battery/drum/time) + recharge scheduling | **Yes.** Levers: `planner_model.py:218` `objective_constraints` (CP-08: `max_time_s/max_energy_J/max_charges/max_distance_m/risk_weight`), `:225` `mission_windows` (EP-04 clock), `:213` `temp_c` (EP-05 derate), `:245` `dig_energy_factor` (EP-02). Energy model `ipex_specs.py:130,140,167,283`. Recharge sched = battery-aware `_simulate` (`mission_planner.py:115`) + `endurance` (`:363`). Consumption in `totals` + `endurance` (`plan.py:321`). | **Yes** — all pass through `/api/plan` via `extra="allow"`; consumption already returned. | **No** levers exposed; result card shows makespan/energy/recharges/drum (read-only). | **M** | Reuse; net-new = lever inputs + budget-vs-actual display. Zero backend. |
| 5 | **Multi-vehicle fleet** (allocation + space-time conflict + precedence) | **Yes.** `plan_multi` (`mission_planner.py:138`); `planner_multivehicle` conflict solvers (`:147-153`: allocate / vehicle+temporal+haul-path conflicts / charger queue / shared-resource / cross-vehicle precedence). Inputs: `plan.py:72` `vehicles`, `:75` `charger_capacity`; `planner_model.py:231` `shared_resources`, `:238` `observations`. | **Yes** — `vehicles`/`charger_capacity` on `/api/plan`. | **No** — `planAuthor` is single-vehicle; result shows `vehicles=1`. (plan_ir already tags `a.vehicle`, never exercised >1.) | **S–M** | Reuse; net-new = fleet inputs + per-vehicle route colors/legend. Zero backend. |
| 6 | **Route/sequence optimization** (nearest/two-opt/beam) + forward-compare | **Yes.** `planner_optimize.py:48` `SEQUENCERS` (auto/nearest/greedy/two_opt/or_opt/lk/brute/held_karp), `:27` `OBJECTIVES`, weighted `parse_objective`. `compare_algorithms` (`mission_planner.py:259`, Pareto frontier). `forward_compare` (`resync.py:94`, feasible-first rank + recommendation) via `/resync/compare` (`plan.py:204`). | algorithm/objective on `/api/plan` = **Yes**. `/resync/compare` = `require_director` → **401**. `compare_algorithms` has **no route** at all. | **No** — `planAuthor.js:291` hardcodes `algorithm:'nearest', objective:'time'`. | **S** (algo/obj) / **M** (compare) | algo/obj = pure rebind; compare/forward-compare = needs route exposure + net-new UI. |
| 7 | **Terramechanics-aware routing** (respect slip/sinkage/tip) | **Yes.** `costmap_layers.py:193` `compose` — 12 layers (slope/roughness/sinkage/slip/tip_risk/negative_obstacle/illumination/psr/shadow_conf/energy/keepout/reservation) + per-cell blocking-reason grid. Consumed by `planner_routing.route_least_cost/route_leg` (`mission_planner.py:351-356`); slope gate `plan.py:74,309`. Layers: `/world/terramechanics-layers` + `/world/traffic-layer` (public), `/layers/raster` (401). | Routing effect = **Yes** (inside `/plan`). Analysis layers = **Yes** (public world-layer GETs). | **Yes (routing effect + layers)** — `catalogLayers.js:20-26,84-90` already drapes cost/blocking + 6 T12 physics fields via `MissionLayers.jsx`. `MissionPlan` does **not** expose the slope budget lever. | **S** | Reuse; net-new = slope-budget slider + a "why blocked" affordance tying route to the reason grid. |
| 8 | **Mission-control report** (multi-page PDF) | **Yes.** `planner_views.py:137` `report()` → PDF+MD; `mission_planner.py:395` `run()`; URLs at `plan.py:382-383`. | **Yes** — `/api/reports/*` public GET + link in `/plan`. | **Yes — DONE.** `planAuthor.js:398` + `MissionPlan.jsx:197-204` render the PDF link. | **0** | Done. |
| 9 | **Schedule / Gantt / mission-clock** | **Yes.** `build_timeline` (`mission_planner.py:314`) → time-bounded frames (t0/t1, battery frac, phase, cum-mass), returned `plan.py:319`. `mission_windows` (EP-04) = clock. `plan_ir.expect.makespan_s`. Gantt util `gantt_downsample.js` exists (used by program board). | **Yes** — `timeline` already in the `/plan` response. | **No** — `planAuthor` ignores `resp.timeline`; no Gantt/clock. | **M** | Reuse the timeline frames + existing `gantt_downsample.js`; net-new = Gantt/clock panel. Zero backend. |
| 10 | **ConOps lifecycle** (Rehearse → Validate → Release → Report) | **Yes.** `mission_lifecycle.run_lifecycle` (DRAFT→ANALYZED→REHEARSED→REVIEWED→RELEASED, `executive.py:47`); `/executive/release-plan` (`:100`, FS-28 command-authority card `:75`), `/executive/advance` (`:41`), `/executive/audit` (`:365`), `/executive/run` (`:223`, SIM) + stream (`:378`). Validate = `validate_plan`/`execute_plan_acceptance` in `/plan` (`plan.py:311,329` → `validation` + `ordered_acceptance`). Rehearse-compare = `forward_compare`. | **Run/Report = Yes** (`/executive/run` + stream key-injected; reports public). **Validate = Yes** (in `/plan` response). **Release / Rehearse-compare / Audit = 401** (director/operator, not key-injected). | **Run = Yes** (`planAuthor.runMission` T10). **Validate = Partial** (`/plan` returns validation/ordered_acceptance; not surfaced). **Release/Rehearse/Audit = No.** | Validate=**S**; Release/Rehearse=**M–L** (+**S** infra) | Run = done; Validate = rebind (data in-hand); Release/Rehearse/Audit = needs proxy unlock + net-new UI. |

---

## (b) Sequenced increments (loop-sized, priority order)

Each is one loop unless flagged. "Reuses" names the backend route (already reachable unless marked
**[infra]**). Acceptance is one observable check.

### Wave 1 — pure GIS rebind, zero infra (highest value / lowest friction)

1. **Keep-out draw tool.** Add an OL draw interaction (circle + rect) to `MissionPlan`; serialize
   drawn shapes to `payload.keepouts` (`{x,y,r}` / `{x0,y0,x1,y1}` in the order frame, same anchor
   math as orders). **Reuses** `POST /api/plan` (`planner_model.py:394` parse; `planner_trips.py:156`
   routing). **Accept:** a no-go drawn across the straight path makes the rendered route visibly bend
   around it; a build placed inside one is rejected with an `infeasible_reason`.

2. **Plan controls — algorithm + objective + slope budget.** Replace the hardcoded
   `algorithm:'nearest', objective:'time'` (`planAuthor.js:291`) with selectors: algorithm ∈
   `SEQUENCERS` (`planner_optimize.py:48`), objective ∈ `OBJECTIVES` (`:27`) incl. a weighted spec,
   and a `max_traverse_slope_deg` slider (`plan.py:74`). **Reuses** `POST /api/plan`. **Accept:**
   switching nearest→held_karp / time→energy re-plans and the result card's makespan/energy/distance
   change accordingly; the resolved algorithm is echoed.

3. **Resource-budget levers + budget-vs-actual.** Add optional inputs for `objective_constraints`
   (`max_time_s/max_energy_J/max_charges/max_distance_m`, `planner_model.py:218`), `temp_c`,
   `dig_energy_factor`, and surface the returned `endurance` + `totals` consumption against them.
   **Reuses** `POST /api/plan` (`extra="allow"`). **Accept:** setting `max_energy_J` below the plan's
   need flips `feasible=false` with the budget reason; the card shows energy used vs budget.

4. **Multi-vehicle fleet.** Add `vehicles` (1–16) + `charger_capacity` inputs; color/legend the
   per-vehicle routes using `plan_ir` `a.vehicle`. **Reuses** `POST /api/plan` (`plan_multi`,
   `mission_planner.py:138`). **Accept:** `vehicles=3` renders 3 distinct-colored routes; the card
   shows `vehicles=3` and a makespan < the single-vehicle time.

5. **Validation / acceptance surfacing.** Render the `validation` + `ordered_acceptance` blocks the
   `/plan` response already carries (flatness RMSE, berm profile, repose, bearing, drum supply,
   siting) as a pass/fail checklist. **Reuses** `POST /api/plan` (`plan.py:311,329`). **Accept:** a
   uniform cut on a slope shows the `as_built_flatness`/`slope_siting` check failing.

6. **Timeline / Gantt panel.** Build a Gantt + mission-clock from `resp.timeline` frames
   (`mission_planner.py:314`), reusing `gantt_downsample.js`. **Reuses** `POST /api/plan`. **Accept:**
   the panel shows per-phase bars (drive/work/charge) summing to the reported makespan; a battery
   trace dips and recovers at each recharge.

7. **Plan-IR inspector + download.** Add an expandable typed-action list + precedence-DAG view +
   `⤓ Plan IR` download from `resp.plan_ir` (already in hand). **Reuses** `POST /api/plan`.
   **Accept:** the panel lists GoTo/CutHaulFill actions with expected energy/duration and the DAG
   edges; the download is valid JSON matching `PLAN_IR_VERSION`.

### Wave 2 — needs a deploy-host proxy unlock (**[infra]** = add a keyless `/plan`-style nginx block)

8. **[infra]** **Structure-template authoring.** Expose `decompose` reachably — make `GET
   /construction` (read-only catalog, `construction.py:66`) public **or** add a keyless proxy block —
   then add a template palette (LandingPad/HaulRoad/BlastWall/SolarPad/HabitatFoundation/BorrowPit/
   CraterFill) that expands a picked template at a map click into mass-balanced cut/fill orders in the
   queue. **Reuses** `leap/structures.py:123` `decompose` + `POST /api/plan`. **Accept:** picking
   LandingPad and clicking the map appends a balanced cut+fill order pair that plans and reports a
   near-zero mass surplus. *(Interim, no infra: load a `/api/sample_mission/{name}` — public — that
   already carries structure-decomposed orders.)*

9. **[infra]** **Forward-compare ("rank candidate futures").** Add a keyless proxy block for
   `/resync/compare` (or a thin public `compare_algorithms` route), then a "Compare solvers" panel
   ranking candidate sequencers feasible-first with wall times. **Reuses** `resync.py:94`
   `forward_compare` / `mission_planner.py:259` `compare_algorithms`. **Accept:** the panel lists ≥3
   solvers with time/energy/distance + a Pareto flag and a recommended head.

10. **[infra]** **ConOps Release + Audit lane.** Add keyless proxy blocks for
    `/executive/release-plan` + `/executive/audit`; add a director-gated "Release" affordance that
    shows the FS-28 command-authority card (`executive.py:75`) and an audit-trail view. **Reuses**
    `executive.py:100,365`. **Accept:** releasing a feasible plan returns state `RELEASED` with a
    frozen plan hash + signer; the audit view lists the release with an integrity flag.
    *(Blast-radius note: `/executive/*` is director-equivalent — the proxy secret is director-scoped;
    treat exactly like the existing `/plan` key block. Main-thread/deploy owner only.)*

### Wave 3 — net-new UX (defer)

11. **Plan-IR editing / re-plan round-trip.** Let the operator reorder/edit actions and re-POST.
    Net-new (no backend blocker, but a real UX design). **Reuses** `POST /api/plan`.

---

## (c) Honest flags

- **Net-new backend logic: none.** Every capability's planner code exists and is tested. The only
  "net-new backend" is a **thin route** for `compare_algorithms` (it has no HTTP surface today,
  `mission_planner.py:259`) — S.
- **The real gate is the artemis proxy, not the code.** Only `/plan`, `/executive/run`, and the
  run-stream are key-injected (`artemis-nginx.conf:139,164,179`). Structure authoring, forward-compare,
  and ConOps Release/Audit are backend-complete but 401 from the public IDE. Unlock = add keyless
  server-side proxy blocks (the exact `/plan` pattern) for the **non-destructive** planning routes.
  This is a deploy-host nginx edit (`api-key.conf` secret is local-only, uncommitted) owned by the
  main thread — **not** a code change. **Rollback:** remove the added `location` blocks.
- **Genuinely hard (defer):** (a) **Plan-IR editing** — reordering a precedence-constrained DAG in
  the UI and re-validating is a net-new interaction, not a data-surfacing task. (b) **Live execution**
  beyond SIM — the `ARMED..EXECUTING` real-rover chain is intentionally gated (MO-04, `executive.py`
  docstring); the IDE must stay SIM/read-only. (c) **`/layers/raster` PIP overlay** is `heavy_quota`
  (401); the GIS should keep using the **public** `/world/terramechanics-layers` + `/world/traffic-layer`
  drapes already wired in `MissionLayers`, not the raster route.
- **Already done, don't rebuild:** the PDF report link (#8) and the SIM run loop (#10 run-half) are
  live in `planAuthor`. Terramechanics **analysis layers** (#7) are already draped by
  `MissionLayers.jsx`/`catalogLayers.js` (T12) — `MissionPlan` only needs the slope-budget lever and a
  cross-link, not a re-implementation.
- **Frontend A is not ahead.** `gis/web/app.js` (the OpenLayers reference `planAuthor` was ported
  from) has the same skeleton — no keepouts, no structures, no fleet, no budgets. Porting from it
  gains nothing for these; the depth must be built fresh against the (already-capable) backend.

---

*Grounding: every "exists" row cites real `file:line`. Reachability verified against
`deploy/artemis-nginx.conf` + per-router `Depends(...)` auth deps. GIS-current state read from
`gis/qwc2/js/plugins/MissionPlan.jsx` + `gis/qwc2/js/mission/planAuthor.js` + `catalogLayers.js`.*
