# FS-23 wiring ledger — cockpit rewrite

**Date:** 2026-06-18 · **Status:** living (grows as each phase ports a work area).
This is the do-first-regardless inventory from the rewrite plan §10: every work area → the backend
route(s) it consumes → the domain module → the React view status → tests. It is the map that makes the
strangler port safe — a pane is not "done" until its row here shows a React view + a test, and the
vanilla twin is deleted only then.

**Legend (React view):** `stub` = Phase-0 placeholder in `cockpit/`; `ported` = real React view consuming
the contract; `vanilla` = still only in the live `stewie/server/web/assets/cockpit.js`.

## Cross-cutting (Phase 1)

| Concern | Backend route(s) | Domain module | React view | Tests |
|---|---|---|---|---|
| Auth / session | `/auth/me` `/auth/login` `/auth/logout` | `routers/auth.py`, `operators.py` | **ported** (`cockpit/AuthGate.tsx`, `auth.ts`) | `cockpit/auth.test.ts`, `render_phase1.py` |
| Role ladder (AG-01/02) | (role on `/auth/me`) | `operators.role_rank` | **ported** (`auth.roleRank` → `store.roleRank` gates ModeBar/command) | `cockpit/auth.test.ts` |
| Command authority (FS-17) | n/a (client election) | ported from `cockpit.js` CMD_AUTH | **ported** (`useCommandAuthority.ts`) | `cockpit/useCommandAuthority.test.tsx` |
| Chrome IA (FS-20) | `/admin/operators` `/events` `/healthz` `/metrics` | `operators_admin.py`, `health.py` | **ported** (`ProfileMenu.tsx` + `ChromePanels.tsx`: Admin roster+audit / System health / Settings theme+font) | `render_phase1.py`, `render_phase2.py`, `api.test.ts` |
| Contract types (FS-02) | `GET /contracts/schema` | `stewie/contracts` | **adapters.js view models (done)** | `test_adapter_contract_parity.py`, `test_contracts.py` |
| Observability (FS-19) | `/events` | `routers/events.py` | vanilla (admin log) | — |
| Registration / invites | `/auth/register` `/auth/invite/redeem` `/auth/password` | `routers/auth.py` | vanilla (Phase 2) | `test_operators*.py` |

## Work areas (§11 IA)

| Work area | Key route(s) | Domain module | React view | Tests |
|---|---|---|---|---|
| **Plan** (+fleet) | `/plan` `/dem/*` `/layers` `/bodies.json` `/structure` `/profile` | `lode/mission_planner.py`, `planner_routing.py` | stub (canvas placeholder) | `lode/test_mission_planner.py` |
| **Navigation/Autonomy** | `/nav/contract` `/nav/local_plan` `/rc/plan_ros` | `lode/planner_routing.navigation_contract`, `stewie/bridge/plan_lowering.py` (NV-11), `stream.py` (NV-12), `routers/rc.py` (AG-08) | stub | `test_navigation_contract.py`, `bridge/test_plan_lowering.py`, `test_plan_ros_route.py` |
| **Perception** | `/evidence` `/compare` `/localize/render` `/localize/traverse` `/twin/*` | `dart/`, `leap/`, `planet_browser/localization.py` | stub | (perception suite) |
| **Metrics/Execution** | `/events` | `routers/operators_admin.py` | **ported** (event timeline + metric tiles; `EventsTable.tsx`, `api.ts`) | `cockpit/api.test.ts`, `render_phase2.py` |
| **Models** | `GET /contracts/schema` (ModelArtifact) | `stewie/contracts.ModelArtifact` (ML-01) | stub (Phase 3) | `test_adapter_contract_parity.py` |
| **Reports** | `/plan` (PDF) `/reports/*` | `planet_browser/mission_planner` report | stub (Phase 3 — produced by Plan flow) | — |

## Shell + design system (Phase 0 — DONE)

| Piece | React | Source | Verify |
|---|---|---|---|
| App shell / top bar / tabs / map canvas / command rail | **ported** | `cockpit/src/App.tsx` | `render_under_csp.py` (CSP-clean, shell mounts) |
| State store (FS-16) | **ported** | `cockpit/src/store.ts` (Zustand) | render harness (truth-disabled-in-OPERATE) |
| Design system | **shipped** | `@stewie/design-system` (8 components) | `adapters.test.js`, `components.test.tsx`, claude.ai/design |

## Next ports (by phase)

- **Phase 1**: auth/role context + FS-17 command authority + FS-20 chrome menu → move the cross-cutting
  rows to `ported`.
- **Phase 2**: Reports, Metrics, System/Settings/Admin (data-light).
- **Phase 3**: Navigation/Autonomy, Plan, Perception (the stateful, high-value panes) — bind the routes
  above through the FS-15 adapters.
- **Phase 4**: the Map/World canvas (Cesium + Three.js) behind a thin React boundary.
- **Phase 5**: cutover — delete `cockpit.js` once every row above is `ported` + tested.
