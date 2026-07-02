# Frontend Review Design Audit

Date: 2026-07-02
Project: STEWIE
Scope: cockpit, program board, frontend state/routing, UI assets, admin/control surfaces, frontend/backend bridge
Skills applied: `frontend-review-design`, bridged with `lunar-mission-systems-audit`

## Executive Summary

STEWIE has moved past a generic dashboard into a mission-oriented cockpit with a recognizable workflow: Plan, Rehearse, Validate, Release, Execute, Report. The current frontend has strong foundations: route-backed panes, provenance labels, mobile-specific CSS, a program board, health/workspace badges, and browser tests covering adapters, pane chrome, program mobile behavior, and state routing.

The main remaining frontend design risk is not visual polish. It is control clarity: the UI still does not carry a complete product mode and runnable profile through the URL, state model, release packet, execution pane, and admin backend. For a mission-planning, digital-twin, and lunar operations system, that missing context makes it too easy to confuse training, simulation, evaluation, planning, rehearsal, and live command surfaces.

The second major risk is asset and authority traceability. The frontend exposes mission assets such as routes, plans, perception evidence, terrain views, world transactions, and release artifacts, but it still needs a stricter registry that tells the operator what each asset is, where it came from, whether it is current, whether it is simulated or live, and which backend contract is authoritative.

## Evidence Collected

### Runtime checks

- Browser opened: `http://127.0.0.1:8771/`
- Title observed: `STEWIE - Digital Twin & Planning Platform`
- Console errors: 0
- Console warnings: 6 after screenshot
- Desktop screenshot captured: `stewie-cockpit-desktop-2026-07-02.png`
- Mobile cockpit screenshot captured: `stewie-cockpit-mobile-390-2026-07-02.png`
- Mobile program board screenshot captured: `stewie-program-mobile-390-2026-07-02.png`

### Mobile viewport checks

Viewport: 390 x 844

- Cockpit `document.scrollingElement.scrollWidth`: 390
- Cockpit `document.documentElement.clientWidth`: 390
- Cockpit body horizontal overflow: false
- Program board body horizontal overflow: false
- Top work-area tabs intentionally scroll inside the tab strip. The page itself does not overflow horizontally.

### Test runs

Node frontend/browser modules:

```text
node --test stewie/server/web/assets/*.test.js stewie/server/web/assets/panes/*.test.js
281 passed, 0 failed
```

Focused frontend and bridge pytest suite:

```text
.venv/bin/python -m pytest \
  stewie/server/test_ia_provenance_labels.py \
  stewie/server/test_program_mobile.py \
  stewie/server/test_cockpit_state_routing.py \
  stewie/server/test_adapter_contract_parity.py \
  stewie/server/test_panel_layout_chrome.py \
  stewie/server/test_ui18_pane_manager.py \
  stewie/server/test_profile_menu_chrome.py \
  stewie/server/test_command_authority_evidence.py \
  stewie/server/test_gis03_globe_guard.py \
  stewie/server/test_gi02_body_crs.py \
  stewie/server/test_gis_export.py \
  stewie/server/test_ogc_wms.py \
  stewie/server/test_world_state_service.py \
  stewie/server/test_world_transaction_atomic.py \
  stewie/server/test_per_site_twin.py \
  stewie/server/test_current_terrain_view.py \
  stewie/server/test_nav_router.py \
  stewie/server/test_plan_result.py \
  stewie/server/test_models_pane.py
129 passed, 2 warnings
```

## Product Purpose Assessment

The system should present itself as a mission planning and digital twin workbench for lunar surface operations, not as a general analytics dashboard. The primary operator mental model should be:

1. Select a mission, site, body, data source, and runnable profile.
2. Build or import a plan using terrain, fleet, structure, and order assets.
3. Rehearse the plan in simulation and record deltas.
4. Validate navigation, perception, solar, communications, hazards, and acceptance gates.
5. Release a signed, bounded command package.
6. Execute only inside the selected runtime authority.
7. Report results back into the world model and program ledger.

The current cockpit mostly follows this shape, but the mode/profile selection is incomplete and spread across workspace labels, source choices, role gates, hash state, and release/execute panels.

## User Asset Model

The frontend should make the following user-visible assets first-class and traceable:

- Mission: objective, site, crew/robot context, constraints, authority mode.
- Site: lunar body CRS, DEM/terrain source, observation coverage, map freshness.
- World model: observed mask, terrain view, transactions, provenance and uncertainty.
- Fleet: vehicles, capabilities, health, command eligibility, simulated or live namespace.
- Structures: pads, berms, zones, keep-outs, acceptance criteria.
- Orders: build, move, inspect, sample, traverse, solar, communications, science tasks.
- Plans: solver inputs, route legs, cost model, constraints, rejected alternatives.
- Rehearsals: simulation run, divergence, incident log, operator signoff.
- Validation evidence: navigation, perception, solar, mapping, hazard, command authority.
- Release packet: signed plan revision, runtime profile, sensor profile, namespace, watchdog state.
- Execution run: bounded command stream, acknowledgements, telemetry, refusal reasons.
- Reports: transaction ledger, after-action evidence, world-state deltas, generated artifacts.

The UI already exposes many of these, but not through a single asset registry or cross-pane contract. That is the main reorganization opportunity.

## Findings

### P1 - Product mode and runnable profile are absent from the frontend state contract

Evidence:

- `stewie/server/web/assets/cockpit_state.js:8` defines work areas.
- `stewie/server/web/assets/cockpit_state.js:10` defines data sources as `live`, `sim`, and `eval`.
- `stewie/server/web/assets/cockpit_state.js:11` defines modes as `sandbox` and `live`.
- `stewie/server/web/assets/cockpit_state.js:27` defines default state without product mode or runnable profile.
- `stewie/server/web/assets/cockpit_state.js:43` serializes hash state without product mode or runnable profile.
- `PRD.md:842` tracks FS-25 as not done: product mode and runnable profile are missing.
- `FANOUT_SPECS.md:682` tracks the same gap.

Impact:

The cockpit cannot reliably answer "what kind of system am I operating right now?" A shared URL can restore selected work area, site, mission, vehicle, source, and sandbox/live mode, but it cannot restore the mission-planning product mode or executable runtime profile. That weakens release, execution, review, operator handoff, training, and auditability.

Recommendation:

Add a first-class `productMode` and `runnableProfile` to the route/state model, then wire them into the visible shell, profile menu, release packet, execute panel, and admin backend.

Suggested product modes:

- `gis-planning`
- `mission-planning`
- `training`
- `simulation`
- `evaluation`
- `live-operations`

Suggested runnable profiles:

- `offline-demo`
- `replay`
- `digital-twin-sim`
- `hardware-in-loop`
- `field-test`
- `live-rover`

File-level work:

- Update `stewie/server/web/assets/cockpit_state.js` defaults, validation, hash parsing, and serialization.
- Add mode/profile controls near `#workspace-badge` in `stewie/server/index.html`.
- Extend release output in `stewie/server/web/assets/cockpit.js` to display product mode, runnable profile, source, sensor profile, command namespace, and command authority.
- Add backend contract fields to the release and execute responses before making them user-facing authority claims.
- Add browser and pytest coverage around URL round-trip, mode/profile display, release evidence, and execute refusal state.

### P1 - Depth-source profile selection and health are static

Evidence:

- `stewie/server/web/assets/cockpit.js:941` initializes perception state from static sample assets.
- `stewie/server/web/assets/cockpit.js:958` sets `source_profile` to `stereo_sgbm`.
- `stewie/server/web/assets/adapters.js:152` normalizes perception profile data.
- `PRD.md:843` tracks PM-17 as partial: depth-source profile selection and health are not complete.
- `FANOUT_SPECS.md:687` tracks the same gap.

Impact:

Perception evidence is visible, but the operator cannot select or verify the active depth source profile as an operational precondition. For lunar mission planning, the difference between stereo, lidar, RGB-D, learned depth, replay, and simulated truth must be explicit. Otherwise, a release or execution surface can look valid while depending on stale or mismatched perception inputs.

Recommendation:

Add a perception source profile selector with health and freshness state. Release and Execute should refuse or degrade when profile health is stale, simulated when live is required, or not compatible with the selected runnable profile.

File-level work:

- Extend `stewie/server/routers/perception.py` with source profile status and freshness endpoints.
- Replace the static perception profile in `stewie/server/web/assets/cockpit.js` with route-backed profile loading.
- Add a compact profile/health control to the Perception validation pane in `stewie/server/index.html`.
- Extend `stewie/server/web/assets/adapters.js` to normalize freshness, calibration id, covariance, and simulation/live evidence class.
- Add tests that prove a degraded profile is visible and blocks release when policy requires it.

### P1 - Release and Execute need a complete authority evidence panel

Evidence:

- `stewie/server/web/assets/cockpit.js:2380` renders release state, signed revision hash, plan id, solver algorithm, and skipped non-build orders.
- `stewie/server/web/assets/cockpit.js:2433` starts a simulated execution run through `/executive/run`.
- `stewie/server/web/assets/cockpit.js:2448` opens the execution event stream.
- `FANOUT_SPECS.md:713` tracks FS-28 authority evidence requirements.
- `FANOUT_SPECS.md:745` tracks RS-02 planner consumption of observed world.

Impact:

The current release and execute panels have useful signals, but they do not yet present the full operator evidence chain needed for mission safety: runtime profile, namespace, command envelope, watchdog status, map freshness, sensor profile, covariance, last acknowledgement, signoff status, and next bounded command. The Execute pane is correctly simulation-oriented today, but the UI needs stronger refusal states before live command capability is introduced.

Recommendation:

Create a dedicated authority evidence component used by both Release and Execute.

Minimum evidence fields:

- Product mode.
- Runnable profile.
- Command namespace.
- Vehicle id and capability scope.
- Plan revision hash.
- Signed release id and signer.
- Sensor profile and health.
- Map freshness and observed-world coverage.
- Navigation covariance.
- Watchdog/stop channel state.
- Next bounded command.
- Last acknowledgement.
- Refusal reason if any gate is closed.

File-level work:

- Add a shared renderer under `stewie/server/web/assets/panes/` or a new `authority_evidence.js`.
- Wire Release and Execute views in `stewie/server/web/assets/cockpit.js`.
- Add backend schemas for authority evidence instead of assembling UI-only text.
- Add tests to `stewie/server/test_command_authority_evidence.py` and a node test for rendered refusal states.

### P1 - Admin and control panel should move from manual operations to governed operations

Evidence:

- `stewie/server/index.html:1350` defines the API/server system pane.
- `stewie/server/index.html:1355` exposes manual operation buttons such as Twin snapshot, Retention, Replicate backup, and Validate gates.
- `stewie/server/index.html:1371` defines the settings pane.
- `stewie/server/index.html:1414` notes that settings persist in the browser.
- `stewie/server/index.html:1440` defines account/admin controls.
- `PRD.md:844` tracks PO-15 as partial: ops governance beyond account admin is not complete.
- `FANOUT_SPECS.md:692` tracks the same gap.

Impact:

The UI has useful operational controls but not a full administrative backend model. Mission systems need governed operations: policy, schedule, last-success state, retention, restore drills, runtime profile management, command locks, account roles, audit logs, and permission-aware visibility.

Recommendation:

Split the administrative backend into four operator-facing areas:

- Identity and access: accounts, roles, invites, audit.
- Runtime authority: product mode, runnable profile, command namespace, live lock, emergency stop integration.
- Data governance: snapshots, backups, restore, retention, export, data freshness.
- System readiness: service health, queue health, model registry, GIS source status, gate validation.

File-level work:

- Keep account admin in `stewie/server/index.html`, but move runtime and data governance into route-backed panes.
- Add server-side policy models for backup, retention, restore readiness, and command lock.
- Add tests for permission visibility and disabled/refusal states for director/admin-only controls.

### P1 - Training operator access model is unresolved

Evidence:

- `stewie/server/web/assets/cockpit.js:4920` starts a training session.
- `stewie/server/web/assets/cockpit.js:4926` renders `operator_url`, `debrief_url`, and summary.
- `PRD.md:845` tracks SE-02 as not done: session operator access model.
- `FANOUT_SPECS.md:697` tracks the same gap.

Impact:

Training flows are valuable, but operator access links are security-sensitive. If a link grants a scoped operator view, the frontend needs to label whether it is authenticated, expiring, signed, single-use, role-limited, and whether it can issue commands or only observe.

Recommendation:

Use signed, expiring capability URLs or authenticated session membership. The UI should show scope, expiry, allowed actions, and revocation state beside each generated operator link.

File-level work:

- Add access metadata to the training session response.
- Render capability scope in the training panel.
- Add backend tests for expired, revoked, and role-mismatched operator links.
- Add frontend tests that verify unsafe links are not presented as unrestricted command links.

### P1 - Route-to-pane contract coverage is still incomplete

Evidence:

- `stewie/server/web/assets/adapters.js` normalizes several route responses.
- `stewie/server/test_adapter_contract_parity.py` exists and passed in the targeted suite.
- `FANOUT_SPECS.md:148` tracks FS-18 route-to-pane contract gate.

Impact:

Adapter tests help, but a mission UI needs every route-backed pane to carry a common contract: schema fixture, successful render, empty/degraded render, permission behavior, mobile fit, provenance labels, and failure state. Without this, new panes can silently bypass evidence and accessibility rules.

Recommendation:

Create a route-to-pane registry and make it the source of truth for bridge tests.

Suggested registry fields:

- Route path and method.
- Backend schema model.
- Frontend adapter.
- Pane id.
- Required role.
- Provenance requirement.
- Empty state fixture.
- Failure fixture.
- Mobile screenshot fixture.

File-level work:

- Add `stewie/server/web/assets/route_pane_registry.js`.
- Add a pytest that enumerates backend routes and checks registry coverage for cockpit-visible panes.
- Add a node test that loads each adapter fixture and verifies pane render status, error state, and provenance labels.

### P2 - Provenance labeling has improved, but PRD/FANOUT text is stale

Evidence:

- `stewie/server/web/assets/provenance_label.js:1` defines reusable provenance labels.
- `stewie/server/web/assets/provenance_label.js:19` defines truth, belief, forecast, and live label semantics.
- `stewie/server/web/assets/provenance_label.js:46` applies labels across matching DOM nodes.
- `stewie/server/index.html:222` includes mobile provenance label legibility rules.
- `FANOUT_SPECS.md:43` still describes FS-03 as lacking systematic provenance labels.

Impact:

The code is ahead of parts of the planning documents. This creates review drag and can lead future contributors to fix already-fixed behavior while missing remaining risks.

Recommendation:

Update PRD/FANOUT status to reflect current provenance implementation. Keep the remaining open question specific: whether each pane has the correct provenance label for each asset and whether mixed live/sim/eval assets are clearly separated.

### P2 - Mobile fit is substantially better and should be protected as a regression gate

Evidence:

- `stewie/server/index.html:108` starts responsive layout rules.
- `stewie/server/index.html:222` includes mobile-specific rules for labels and wide content.
- Browser check at 390 x 844 found no body-level horizontal overflow on cockpit or program board.
- `stewie/server/test_program_mobile.py` passed.
- `PRD.md:846` tracks FS-26 as partial.

Impact:

The cockpit is usable on narrow viewports in the tested pages. Top tabs scroll inside their rail, which is appropriate for this dense application. This should now become a regression gate.

Recommendation:

Keep the current horizontal tab rail behavior, but add automated screenshot or DOM overflow tests for the main cockpit, program board, admin/settings, validation sub-tabs, and execute/report panes.

## Frontend Reorganization Proposal

### Information architecture

Use a two-level structure:

- Primary mission workflow: Plan, Rehearse, Validate, Release, Execute, Report.
- System/support workspace: Fleet, Construction, Models, Trainer, Program, Settings, System, Admin.

Keep Navigation, Perception, and Solar under Validate if the product decision is that they are validation domains. If they must be first-class operational work areas, promote them to the primary rail and keep Validate as a gate summary. Do not leave them halfway between the two models.

### Shell controls

The shell should always display:

- Active mission.
- Active site/body.
- Product mode.
- Runnable profile.
- Source class: live, sim, eval, replay.
- Role.
- Health.
- Workspace or training/live status.
- Command lock status.

### Asset registry

Add a frontend asset registry that each pane can query. This can start as a simple route-backed manifest.

Required columns:

- Asset id.
- Asset type.
- Site/body.
- Source.
- Provenance.
- Freshness.
- Owner route.
- Last transaction.
- User action.
- Eligibility for release/execute.

### Admin backend bridge

The frontend should not treat admin as a collection of buttons. It should expose governed backend resources:

- Backup policy and last restore test.
- Retention policy and pending deletions.
- Runtime profile registry.
- Command namespace registry.
- Account and role registry.
- Audit events.
- Model registry.
- GIS source registry.
- Gate validation results.

## Concrete Next Changes

1. Implement FS-25 in `cockpit_state.js` and the shell UI.
2. Add a route-backed perception source profile selector and health panel.
3. Build a shared authority evidence component for Release and Execute.
4. Convert manual system/admin buttons into governed route-backed resources.
5. Add route-to-pane registry coverage for every visible pane.
6. Update stale PRD/FANOUT claims for provenance labels and mobile viewport status.

## Verification Notes

The audit used live browser inspection, mobile viewport checks, frontend node tests, and targeted pytest suites. The local server was started with developer-open mode and operator login disabled for audit visibility only; those settings are not production recommendations.
