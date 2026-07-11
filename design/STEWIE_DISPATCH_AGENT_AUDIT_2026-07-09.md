# STEWIE Dispatch-Agent Wiring Audit

**Date:** 2026-07-09

## Verdict

STEWIE has a real, mass-conserving Tier-2 simulation/planning core, but its dispatch spine is not coherent
enough to treat a reviewed plan, a released plan, a SIM run, and a live command as the same mission. The
current product is suitable only as a clearly labeled planning/SIM prototype. It is **not ready for live or
HIL dispatch** until the authority, plan-identity, watchdog, and ROS handoff gaps below are closed.

The highest-risk issue is not an individual terramechanics equation. It is that the frontend, release route,
SIM runner, and RC routes independently reconstruct a mission from different subsets of the input.

## Scope and Observed Modes

| Area | Current behavior | Audit result |
|---|---|---|
| `/ide/` QWC2 mission workbench | Full plan request, then a stripped SIM-run request | Plan-to-run contract broken |
| Legacy cockpit | Full plan request, then separate release/run payloads | Plan-to-release/run contract broken |
| `/executive/run` | Rebuilds a fresh lifecycle and one SIM mission | Not bound to a signed revision or reviewed Plan IR |
| `/rc/*` | Authorizes a `live` mission and uses an in-process `SimBackend` | Not a live-agent dispatch path |
| Tier-2 physics | Conserved NumPy terrain/terramechanics authority | Real, but selected/configured physics is not carried end to end |
| ROS2 packages | Contracts and translation seams exist | Core operational agents are skeleton/gated |

## Confirmed Findings

### 1. Critical: the reviewed, released, and executed plans are different artifacts

`/ide/` sends the full planner payload, including algorithm, objective, slope, fleet, charger capacity,
lat/lon anchor, keep-outs, and resource constraints (`gis/qwc2/js/mission/planAuthor.js:1358-1388`). It then
keeps only `payload.orders` for execution (`:1389-1393`) and submits only orders, body, site, and a new mission
name to `/executive/run` (`:1936-1941`). The legacy cockpit follows the same pattern: full `/plan` input
(`stewie/server/web/assets/cockpit.js:5046-5051`), stripped release input (`:2432-2436`), and stripped run
input (`:2516-2518`, `:5506-5508`).

The server schemas only preserve `orders`, `body`, `site`, `mission_id`, and `revision`
(`stewie/server/routers/executive.py:67-72`, `:144-150`). `/executive/run` builds a new intent, advances a
new lifecycle, and builds a new mission from orders/body/default charger (`:239-248`). It does not consume the
signed revision returned by `/executive/release-plan`.

Impact: a reviewed plan can lose keep-outs, precedence, solver/objective, fleet size, vehicle/tools/soil,
charger capacity, slope budget, resource constraints, anchor, and source terrain before it is simulated. The
run response can still be labeled released/completed even though it did not execute the reviewed artifact.

### 2. Critical: live namespace membership substitutes for director release authority

`/rc/command` and `/rc/plan_ros` accept a mission based on `OBJ.load_mission(..., namespace="live")`
(`stewie/server/routers/rc.py:43-50`, `:133-140`), not a durable signed revision, Plan IR hash, or
training-to-live token. `/executive/release-plan` only returns a signed SIM revision; it does not persist a
commandable release record (`stewie/server/routers/executive.py:100-141`).

Operators default to the shared `live` namespace (`stewie/server/deps.py:142-153`). Any authenticated user can
save there (`stewie/server/routers/missions.py:22-28`), and `save_mission` atomically replaces the shared file
without a revision/conflict/release check (`stewie/server/objects.py:146-156`). Publishing a sandbox mission
also overwrites the shared live file (`:127-138`). `test_ownership.py:38-43` explicitly permits this overwrite.

Impact: an operator can replace the command inputs of a live mission and lower or command it without director
sign-off on that exact content. This is a live-command authority bypass once a physical backend is connected.

### 3. Critical: physics and terrain inputs diverge across plan, release, and run

The plan route applies the selected site's current composed surface, including remembered/observed terrain
(`stewie/server/routers/plan.py:324-362`; `state.as_built_dem`). The run route loads the raw site DEM and passes
it directly to `run_closed_loop` (`stewie/server/routers/executive.py:245-249`), so an as-built or observed
hazard used during planning need not be present during SIM execution. It only folds terrain memory after the
run (`:265-274`).

The run contract also drops all fleet and planner controls. Direct validation of `RunRequest` showed that
`vehicles`, `vehicle`, `tools`, `algorithm`, and `charger_capacity` are silently discarded. The autonomy plant
calls `MP.plan` without `vehicles` (`lode/autonomy.py:171-185`), so the multi-vehicle plan is re-simulated as
the default single-vehicle plan. Per-run SSE events also default every event to vehicle `ipex`
(`lode/sim_execution.py:74-96`).

There is a separate non-lunar body defect: `intent_from_orders(..., body="mars")` leaves objectives in the
default `MOON_ME` frame (`lode/mission_intent_compiler.py:357-402`), and `_intent_body` compiles that to
`moon` (`:261-270`). Direct verification produced `input_body='mars', objective_frame='MOON_ME',
compiled_body='moon'`.

Impact: dispatch can use Moon gravity/configuration, a pristine/default terrain anchor, and one rover while
the UI shows a different body, terrain, route, and fleet.

### 4. High: RC plan lowering recomputes a DEM-free, unreviewed Plan IR

`/rc/plan_ros` lowers `PV.plan_ir(MP.mission_from_dict(saved))` with no site, DEM, as-built surface, plan
configuration, or reviewed result (`stewie/server/routers/rc.py:129-140`). Stored missions cannot retain a
site (`stewie/server/objects.py:142-156`). `plan_ir` uses direct paths when a DEM is absent
(`lode/planner_views.py:413-455`).

Impact: a returned ROS command tape can contain straight-line goals and different safety/route assumptions
from the terrain-aware reviewed plan. The route also bypasses the typed heavy-route deadline/quota that guards
`/plan`.

### 5. High: live-token and watchdog safety controls are not effective on the HTTP dispatch path

`/executive/run` issues a live token (`stewie/server/routers/executive.py:327-339`), but
`require_live_token` has no production caller. Its proposed signature is a predictable SHA-256 of public
mission/revision fields, not a secret-backed MAC or persisted issuance (`stewie/contracts/live_gate.py:53-74`).

The HTTP watchdog is only ticked when telemetry is read (`stewie/server/routers/rc.py:206-225`); command
submission only feeds it (`:111-116`). A disconnected client that stops polling never causes that backend to
safe. `seconds_idle` is time since server receipt, but is passed as `ack_age_s` (`:101-105`; see
`stewie/bridge/rc_contract.py:251-289`), not a rover/link acknowledgement. The `StreamSession` safe-stop
mechanism is created only as a transient response object, with no callback, ticks, or acknowledgements
(`stewie/server/routers/rc.py:143-151`; `stewie/bridge/stream.py:21-69`).

Impact: do not rely on the current HTTP command route for dropout safing or acknowledgement-based command
authority.

### 6. High: failed SIM runs leave committed world history

`commit_sim_run` appends the released-plan and execution records before terrain remembering
(`stewie/server/world_state.py:205-220`; `stewie/server/routers/executive.py:265-274`). If the later terrain
record fails, the route returns HTTP 500 (`:275-279`) but the earlier records remain in the world journal. A
fault-injection check confirmed a 500 response with three durable orphan records: released plan, leg, and
acceptance.

Impact: retrying a request can duplicate or misrepresent execution history, while the client believes the
first request failed. The hash chain remains valid, but the transaction is not atomic.

### 7. High: ROS agent dispatch is a deliberately gated skeleton, not an operational path

The ROS autonomy contract names perception, mapping, planning, control, vehicle-interface, and executive
edges (`stewie/bridge/autonomy_contract.py:151-175`). The executive, planning, control, perception, and
vehicle-interface packages currently create/spin bare nodes rather than wiring those edges
(`ros2_ws/src/stewie_executive/stewie_executive/node.py:25-43` and sibling package `node.py` files). The
Gazebo launch starts simulation/bridges rather than those agents (`ros2_ws/src/stewie_bringup/launch/gz_sim.launch.py:31-48`).

The FastAPI RC router hard-codes `SimBackend` (`stewie/server/routers/rc.py:24-25`), while `/rc/plan_ros`
returns transient JSON frames rather than publishing them (`:143-157`). This is correctly described in some
docs as gated; it must remain SIM/preview-only in every UI and deployment claim.

### 8. High: selectable physics backends have incompatible identifiers and no execution binding

The React workspace advertises `tier3_chrono` (`frontend/src/workspace.ts:16,25`), the executable physics
registry contains only `tier2_numpy` (`stewie/physics/backend.py:53-67`), and the physics-model control
ledger uses `tier2_chrono` (`stewie/contracts/physics_model_control.py:88-94`). Selecting the advertised
Chrono profile resolves an unknown backend. `/executive/run` has no backend input and hard-codes Tier-2
attribution/gating (`stewie/server/routers/executive.py:289-345`).

Impact: a UI-selected backend cannot be trusted to match the backend that produces the run, and the Chrono
option is presently a nonfunctional spike rather than a selectable authority.

### 9. Medium: the SIM executive only drives critical-fault safing

`run_sim_execution` passes only `faults` into `executive_step` (`lode/sim_execution.py:45-50`). Command
acknowledgement, plan acceptance, covariance, reservation conflict, recovery, and reactive-navigation inputs
retain permissive defaults (`lode/executive.py:27-29`). The normal result is therefore continue/completed
unless a critical fault is present (`lode/sim_execution.py:63-68`).

Impact: the tested state machine is real, but the dispatched SIM runner does not exercise pause,
relocalize, replan, reverse, multi-agent reservation, or recovery behavior.

### 10. Medium: UI playback is a substitute trajectory, and the persisted run is not reproducible

Persisted runs retain terminal state and ordinal actions, not the request payload, signed plan hash, terrain
hash, physics backend/version, or per-leg physical telemetry (`stewie/server/routers/executive.py:252-255`;
`stewie/server/objects.py:228-237`). SSE emits ordinal events (`lode/sim_execution.py:74-96`). QWC2 then
interpolates the prior rendered plan route (`gis/qwc2/js/mission/planAuthor.js:1810-1867`), even though its
own comments state the stream carries no position telemetry (`:1790-1796`).

Impact: the rover animation is a forecast visualization, not an executed physical trajectory. It should be
labeled accordingly until event telemetry carries actual per-vehicle pose/provenance.

### 11. Medium: production React authority screens contain functional stubs and broken mutation wiring

The React `/app` release action sends a cookie-authenticated POST without `X-CSRF-Token`
(`frontend/src/panes/Authority.tsx:69-76`; `stewie/server/deps.py:34-43`, `:97-104`). Its Execute route has
no `/executive/run` action, and authority eligibility omits the mission query that the backend needs
(`frontend/src/panes/Authority.tsx:109,130`; `stewie/server/routers/rc.py:234-261`). Eight declared panes
fall through to the migration placeholder (`frontend/src/panes.ts:20-33`; `frontend/src/App.tsx:62-66`).

Impact: do not advertise React `/app` as an operational cockpit. Its current role is a partial migration
shell. The legacy cockpit and QWC2 still need the canonical plan-reference fix above.

### 12. Medium: world transactions can use the default twin for a non-default site

The singleton installs `WorldStateService(twin=twin)` (`stewie/server/state.py:180-196`), and the service
calls that accessor without the transaction site (`stewie/server/world_state.py:102,118-129`). A transaction
can be labeled with a non-Haworth site while its twin identity comes from the default twin.

Impact: site provenance and the world-state hash can disagree outside the default site.

## Explicit Gated Work and Stubs

These are not hidden defects when kept visibly SIM-only, but they block any live-dispatch claim:

- The ROS2 operational agents are skeletons; live ROS/HIL closure is not implemented.
- `WorkSite` documents a stub controller and deferred cross-window/render/arm work
  (`stewie/physics/worksite.py:5,17-18`).
- The only executable physics backend is `tier2_numpy`; Chrono is not an available authority.
- The microgravity `RoverSimEnv` is explicitly placeholder/unvalidated (`stewie/envs/rover_env.py:97-104`).
- `mission_lifecycle` intentionally stops at RELEASED for hardware execution (`lode/mission_lifecycle.py:31-33`).

## Remediation Order

1. **Freeze and persist a canonical release artifact.** Persist a revisioned PlanResult/Plan IR with every
   planner input, site/anchor/frame, terrain and world-state hash, physics backend/version, vehicle fleet,
   constraints, approval evidence, and content hash. Make release return its immutable ID.
2. **Make run and RC routes accept only that immutable revision ID.** Do not rebuild from browser orders or a
   mutable saved mission. Reject stale terrain/world revisions and mismatched content hashes. Carry actual
   per-vehicle configuration into execution.
3. **Close command authority before enabling any physical backend.** Require a director-signed revision and
   a server-issued, secret-backed, expiring, persisted token at `/rc/command` and `/rc/plan_ros`. Restrict
   live writes/publish/overwrite to director-approved revision transitions with optimistic concurrency.
4. **Use the reviewed terrain and physics snapshot.** Execute against the composed as-built/observed terrain
   used for planning, preserve the selected body and explicit frame, and either implement non-lunar frames
   correctly or refuse them at release. Remove unavailable Chrono choices from UI until registered.
5. **Build a real dispatch loop or keep it disabled.** Bind persistent StreamSession ACKs to a scheduler/timer
   that safes independently of browser polling. Wire ROS nodes/publishers/subscribers and a physical backend
   only after an end-to-end safe-stop and acknowledgement test passes.
6. **Make transactions recoverable and playback honest.** Use a prepare/commit or compensating journal flow
   across run, terrain, traffic, and world records. Persist the full execution input and per-leg physical
   telemetry; render observed execution separately from the forecast route.
7. **Fix frontend state ownership.** Store the canonical revision ID in QWC2 and the cockpit, send it on run,
   add the CSRF helper to React mutations, and gate/remove placeholder controls until their backend workflow
   exists.

## Required Acceptance Tests

- A nondefault anchor, keep-out, fleet, solver, slope cap, charger capacity, and body produce one immutable
  revision. Release, run, ROS lowering, and replay must all report the same hash and physics/terrain inputs.
- A changed or replaced live mission cannot alter a released revision or command tape; operator-only requests
  for release/overwrite/lower must fail where director authority is required.
- Missing, expired, forged, or mismatched live tokens are rejected at both RC routes.
- A no-poll/no-ACK command safely stops within the watchdog deadline, verified against the actual backend.
- Terrain/world persistence fails as one recoverable unit: no orphan transaction records on a failed run.
- A multi-vehicle run emits per-vehicle execution events and actual positions; UI playback does not reuse a
  prior forecast route as telemetry.
- Mars/other supported bodies either retain body/frame through release/run or are rejected before release.

## Verification Performed

- `PYTHONPATH=. .venv/bin/python -m pytest stewie/server/test_executive_run.py stewie/server/test_executive_route.py stewie/server/test_planner_observed_world.py -q`: 20 passed.
- Focused executive, SIM transaction, physics backend, live-gate, RC, ownership, and ROS package tests passed
  during this audit; none cover the cross-contract defects above.
- `npm run build` in `frontend/`: passed.
- Frontend Playwright tests passed in DEV_OPEN mode; this does not validate production cookie CSRF or a
  release-to-run identity chain.
- Direct contract checks confirmed that `RunRequest` discards fleet/planner fields and that a Mars order intent
  compiles to a Moon mission under the current default frame.
