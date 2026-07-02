# STEWIE fan-out dispatch specs (buildable §7 ready-set)

Self-contained dispatch briefs for the 62 buildable §7 rows (the ready-set from `scripts/fanout_plan.py`).
One brief per row so an orchestrator can hand a fresh agent a row and it can act + self-verify without
tribal knowledge. Regenerate the *ready-set membership* with `python3 scripts/fanout_plan.py`; these
*briefs* are the 2026-07-01 seven-agent normalization pass (verified against the live tree) and are
refreshed by re-running that pass when the code moves.

**Each brief:** goal (what to build) / acceptance (what a passing test asserts) / current_state (partial
vs missing) / files (real paths) / test_target (existing `path::test` to extend with `[REQ:ID]`, or a NEW
test path) / type (atomic | epic → subtasks | optional | gated-on-discovery).

**The done-gate is objective:** a row is done when a real test cites it `[REQ:ID]` and `req_trace`
reports it V=D. An agent finishes by adding/extending that test and flipping the §7 glyph.

## Cross-cutting findings (read before dispatching)

- **The 29 JS `*.test.js` (node:test) files are NOT run in GitHub CI.** `req_trace` also only scans
  python `test_*.py`. So a JS-only row (FS-16, FS-24, PO-10/11/12) needs a **python** citing test to
  count, and the browser tier itself is a gap (see PO-04). Rows whose only test is `*.test.js` are
  "uncounted," not done.
- **PO-04's three `[REQ:PO-04]` markers are misattributed** (they sit on auth/secret tests, not CI
  tiering) — reassign them as part of PO-04.
- **Done-stale (verify-flip, no build):** GI-03 is implemented + `[REQ:GI-03]`-tested; its N glyphs are
  lag. Verify green + reconcile the glyph.
- **Partial-gated legs:** many rows have a CPU-closeable slice + a gated leg (GPU render / ROS host /
  PyChrono / LAC data). Build the closeable slice, mark the gated leg — do not fabricate the gated half.
- **Epics must decompose** (subtasks are in each brief); **optionals** are the `[PROPOSED]`/"may" rows —
  the load-bearing invariant is usually a guardrail, not a new model.

---

## FS lane (system integration / front-end contracts) — 19 rows

### FS-01 (P0) — atomic
- goal: give the codebase-assessment gate a machine-checkable form (a slice can't be done without an inventory of touched panes/routers/modules/tests) and cite it.
- acceptance: a test asserts a slice's assessment artifact names affected files/modules + existing tests, and the tracer reports the row's coverage; fails when the inventory is absent.
- current_state: `scripts/fanout_plan.py` + `scripts/req_trace.py` provide the inventory machinery; nothing cites FS-01 (V=P). No per-slice assessment-note schema enforced.
- files: scripts/fanout_plan.py, scripts/req_trace.py, PRD.md
- test_target: extend scripts/test_req_trace.py with a `[REQ:FS-01]` marker, OR NEW scripts/test_assessment_gate.py
- notes: process gate; the missing piece is one citing test. Do not build a new note format if the tracer can express the inventory.

### FS-03 (P0) — epic
- goal: make Plan/Fleet/Navigation/Perception/Construction/Models/Security/Reports first-class cockpit work areas, mobile-safe, with explicit truth/belief/forecast/live provenance labels; cite it.
- acceptance: a served-cockpit test asserts each work area is a first-class view, each carries an epistemic label {truth,belief,forecast,live}, and mobile breakpoints apply at phone widths.
- current_state: partial — panes exist for plan/fleet/construction/models/report/system; Navigation+Perception are Validate sub-tabs; ad-hoc badges (FRESH/STALE, LIVE/TRAINING) but no systematic provenance-label component; MOBILE-* classes present; no `[REQ:FS-03]`.
- files: stewie/server/index.html, stewie/server/web/assets/cockpit.js, .../fleet_render.js, .../construction_render.js, .../models_render.js
- test_target: extend stewie/server/test_ui18_pane_manager.py or test_panel_layout_chrome.py; OR NEW stewie/server/test_ia_provenance_labels.py
- notes: subtasks — (1) promote Navigation+Perception to first-class (or assert the sub-tab strip satisfies it); (2) one reusable provenance-label component per pane; (3) mobile-safe at 390px; (4) the citing test.

### FS-04 (P1) — epic
- goal: close multi-vehicle coordination as one umbrella — per-vehicle state, reservations, corridor deconfliction, cross-vehicle precedence, conflict explanation, safe replan — with an FS-04 integration test on real Haworth.
- acceptance: a test drives `plan_multi` on a real multi-pit DEM asserting per-vehicle allocation+health, reservation admission ≤ capacity, corridor/space-time deconfliction, a cross-vehicle precedence edge honored, human-readable conflict explanations, and safe replan on infeasibility.
- current_state: partial — `lode/planner_multivehicle.py` + `lode/fleet_resources.py` exist (FL-02/03/04 have their own markers); gaps: no consolidated conflict-explanation surface, replan/fallback not asserted end-to-end, no umbrella `[REQ:FS-04]`.
- files: lode/planner_multivehicle.py, lode/fleet_resources.py, lode/mission_planner.py, stewie/server/routers/fleet.py
- test_target: extend lode/test_fl04_precedence_split.py with `[REQ:FS-04]`, OR NEW lode/test_fs04_coordination.py
- notes: real DEM fixtures under samples/lunar_dem/ — not gated. Subtasks: conflict-explanation strings, replan/fallback exercise, `/fleet`+`/plan` per-vehicle detail, umbrella test.

### FS-05 (P1) — gated
- goal: land the live Autoware/Nav2 planner BINARY egress (the one remaining nav tier) so I/V move off P.
- acceptance: on a ROS/Space-ROS host, `lode.planner_routing.navigation_contract()` reports the live-planner stage `present=True` and a lowered Plan-IR is consumed by the real planner binary end-to-end.
- current_state: on-host spine DONE (X=D): `lode/nav_pipeline.run_navigation`, `POST /nav/run`, DRIVE PREVIEW overlay (Playwright-verified). `navigation_contract()` hard-codes the live stage `present=False, note="gated: needs live planner binary on a ROS host"`.
- files: lode/planner_routing.py (navigation_contract ~L409-434), lode/nav_pipeline.py, stewie/bridge/plan_lowering.py, ros2_ws
- test_target: on-host tier already `[REQ:FS-05]` (lode/test_nav_pipeline.py, stewie/server/test_nav_router.py); live tier NEW stewie/bridge/test_live_planner_egress.py (host-gated)
- notes: GATED on a ROS2/Space-ROS host. On-host work complete; do not flip I/V without the host.

### FS-07 (P1) — epic
- goal: wire the nav seams (articulation pose, camera rig, shadow/parallax obs, pose-graph factor, residual gate, covariance update, evidence view, planner relocalization stop) into one auditable closed loop; cite it.
- acceptance: one test drives a single connected run: scheduled relocalization stop → observation → pose-graph factor → residual/accept-reject gate → covariance reduce (accept) / untouched (reject) → exposed to the evidence view.
- current_state: partial — all seams exist separately (dart/articulated_parallax.py, camera_rig.py, shadow_parallax_nav.py, factors.py, pose_graph_se2.py, relocalization.py, lode/relocalization.py, integrated_slam.py, evidence_ledger.py + /evidence). No single closed-loop module/test, no `[REQ:FS-07]`.
- files: dart/relocalization.py, lode/relocalization.py, dart/integrated_slam.py, dart/evidence_ledger.py, stewie/server/routers/evidence.py
- test_target: NEW dart/test_nav_operational_loop.py (`[REQ:FS-07]`); optionally extend dart/test_relocalization.py
- notes: real Katwijk fixtures already used; shadow factor runs at calibrated sigma (existing limitation). Subtasks: loop driver, accept+reject branches, evidence surfacing, citing test.

### FS-08 (P0) — epic
- goal: enforce that every new capability ships typed API + schema fixture + cockpit binding + loading/error/empty states + a desktop AND mobile browser regression; cite it.
- acceptance: a test asserts new routes expose typed schemas via /contracts/schema, the cockpit binds state, each data pane renders loading/error/empty, and a real-browser regression runs at desktop + phone viewports.
- current_state: partial — typed contract fixture (`routers/schema.py`), empty states present, real-browser smokes exist but split (ui_eval.py desktop-only, ux_a11y_smoke.py mobile). No systematic loading/error test, no `[REQ:FS-08]`.
- files: stewie/server/routers/schema.py, stewie/server/index.html, .../cockpit.js, scripts/ui_eval.py, scripts/ux_a11y_smoke.py
- test_target: extend stewie/server/test_ux_clusterb.py with `[REQ:FS-08]`, OR NEW stewie/server/test_fs08_wiring.py
- notes: Playwright present in .venv (not gated). Subtasks: mobile pass in ui_eval, loading/error/empty per pane, schema↔binding tie, citing test.

### FS-09 (P0) — atomic
- goal: cite a meta-test proving each user-visible slice has unit + route + FE tests, `[REQ:]` markers, deterministic fixtures, and one e2e path.
- acceptance: a meta-test asserts the pyramid is populated (markers resolve via req_trace; representative unit/route/FE/e2e tests exist; fixtures deterministic — no RNG/wall-clock); fails if a layer is missing.
- current_state: partial — the pyramid largely exists; nothing cites FS-09; no single completeness meta-assertion (V=P).
- files: scripts/req_trace.py, scripts/test_req_trace.py, conftest.py
- test_target: extend scripts/test_req_trace.py with `[REQ:FS-09]`, OR NEW scripts/test_pyramid_gate.py
- notes: reuse the req_trace scanner; one citing meta-test closes it.

### FS-10 (P1) — epic
- goal: extend the budget framework beyond latency to memory, CPU/GPU, bandwidth, tile/cache, and model-inference budgets across map render/plan/fleet/nav/mobile.
- acceptance: tests assert a declared budget + over-budget flag per class, computed from REAL recorded measurements (like the latency aggregator), surfaced in /metrics.
- current_state: partial — only latency done (`stewie/server/services.py` budget_for/record_latency + test_perf_budgets.py `[REQ:FS-10]` + /metrics). Other classes undefined.
- files: stewie/server/services.py, stewie/server/server.py, stewie/server/test_perf_budgets.py
- test_target: extend stewie/server/test_perf_budgets.py::test_over_budget_flag_set_only_when_breached
- notes: assert enforcement on real recorded samples (GPU on a CPU host → test the accounting, not live GPU traffic). Subtasks: define+record each class, map to subsystem, /metrics, extend test.

### FS-11 (P0) — atomic
- goal: consolidate the security-hardening gate into one FS-11 assertion + close the remaining backup/restore sub-item.
- acceptance: a test asserts fail-closed auth+roles, no browser secrets, CSP/no-inline, SBOM/CVE present, command interlocks active, AND a documented+tested backup/restore assumption for the store.
- current_state: mostly done (fail-closed store `[REQ:FS-11]`, CSP, SBOM, command interlock, egress auth); gap: backup/restore not tested, no umbrella assertion.
- files: stewie/server/operators.py, stewie/server/state.py, stewie/server/test_deploy_hardening.py, scripts/gen_sbom.py, stewie/server/test_command_gate.py
- test_target: extend stewie/server/test_account_store_failclosed.py, OR NEW stewie/server/test_fs11_hardening_gate.py
- notes: the controls pass; work is (1) a tested backup/restore assumption, (2) a consolidated FS-11 assertion.

### FS-12 (P1) — epic
- goal: enforce ML-01 model governance (no learned model exposed without lineage/split/registry/card/quant profile/calibration/OOD/fallback/rollback); cite it.
- acceptance: a `[REQ:FS-12]` test asserts `ModelArtifact.deployment_ready` is False unless every governed field is present + True when all are; `command_path=True` rejected; /models returns the criteria list + honest empty deployed_models.
- current_state: contract + gate built (`stewie/contracts/__init__.py:183-230`), /models serves ML-01 governance, gate tested `[REQ:ML-01]`. Missing: `[REQ:FS-12]`; no first-class model-card/calibration-report objects; zero deployed models by design.
- files: stewie/contracts/__init__.py, stewie/server/routers/models.py, stewie/server/test_models_pane.py, stewie/contracts/test_contracts.py, stewie/server/web/assets/models_render.js
- test_target: extend stewie/contracts/test_contracts.py::test_model_artifact_deployment_requires_declared_schemas_and_budgets with `[REQ:FS-12]`
- notes: full "every model has a card+calibration report" is GATED on real trained models (none by design); closeable slice = gate + citation.

### FS-13 (P1) — epic
- goal: record/version/replay/compare/approve construction + self-docking primitives (excavate/dump/berm/dock), replay belief-corrected + safety-bounded; cite it.
- acceptance: a `[REQ:FS-13]` test asserts a primitive records with version+approval + the closed_loop invariant (open-loop rejected); replays with belief-feedback + safety halt; two recordings compare; approval gates staging.
- current_state: `ConstructionSkill` contract carries version/approved/closed_loop (tested, no marker); `dart/teach_repeat.py` does record+reverse-replay+compare for DOCK. Missing: unified record/version/replay/compare/approve for excavate/dump/berm; `[REQ:FS-13]`.
- files: stewie/contracts/__init__.py, dart/teach_repeat.py, stewie/server/routers/construction.py, .../rehearse_render.js, stewie/contracts/test_contracts.py, dart/test_teach_repeat.py
- test_target: extend stewie/contracts/test_contracts.py::test_construction_skill_must_be_closed_loop with `[REQ:FS-13]`, OR NEW dart/test_skill_record_replay.py
- notes: dock leg exists; force-accurate excavation replay is Tier-3/Chrono-gated; kinematic conserved-authority replay is closeable.

### FS-14 (P0) — epic
- goal: code-enforce the atomic-rollout rule (a row can't reach V=D until contracts + FE affordance + route + tests + security + perf budget are complete-or-explicitly-gated); cite it.
- acceptance: a `[REQ:FS-14]` test refuses V=D for any row missing a required artifact unless on an explicit gated list; passes when all present-or-gated.
- current_state: req_trace enforces V=D-requires-citation (FS-22); release_gate maps AS tiers (report-only); perf budgets exist. Missing: single gate binding the full completeness set; `[REQ:FS-14]`.
- files: scripts/req_trace.py, scripts/release_gate.py, scripts/gen_status.py, scripts/test_release_gate.py, stewie/server/test_perf_budgets.py
- test_target: NEW scripts/test_atomic_rollout_gate.py (`[REQ:FS-14]`), OR extend scripts/test_release_gate.py
- notes: gate-tooling on req_trace/release_gate. Subtasks: required-artifact set + gated allowlist, failing gate, citation + CI wiring.

### FS-15 (P0) — atomic
- goal: give the Perception pane a typed contract + normalizer consuming the view model (not raw JSON), flipping X from N to D.
- acceptance: extend the parity gate to assert a Perception aggregate contract exists (real fields only), `adapters.js` has `normalizePerception`, the perception pane calls it, and it's in `_PANE_CONSUMES`.
- current_state: adapter layer complete (10 contracts, 3 panes wired, `[REQ:FS-15]`-cited); gap (X=N): no Perception contract, pane consumes /compare,/slam,/render raw.
- files: stewie/contracts/__init__.py, .../adapters.js, .../cockpit.js, stewie/server/routers/perception.py, stewie/server/test_adapter_contract_parity.py
- test_target: extend stewie/server/test_adapter_contract_parity.py (add PerceptionState to _ADAPTER_FIELDS + a perception _PANE_CONSUMES entry; existing `[REQ:FS-15]` covers it)
- notes: wire the contract to the already-served aggregate; if panorama/shadow depends on live render, that leg is GATED.

### FS-16 (P0) — atomic
- goal: add a PYTHON citing test proving the single routeable state model drives desktop + mobile (enum enforcement + hash round-trip), flipping V P→D.
- acceptance: a `[REQ:FS-16]` python test asserts defaultState covers the routeable fields, toHash/fromHash round-trips, setState rejects unknown workArea/source/mode, and cockpit.js wires desktop+mobile to the one STEWIE_STATE.
- current_state: cockpit_state.js + cockpit_state.test.js (node) fully implement it, but req_trace scans only python so it's uncounted. Missing: a python `[REQ:FS-16]` test.
- files: stewie/server/web/assets/cockpit_state.js, .../cockpit_state.test.js, .../cockpit.js, stewie/server/index.html
- test_target: NEW stewie/server/test_cockpit_state_routing.py (`[REQ:FS-16]`; static-read pattern of test_panel_layout_chrome.py)
- notes: model is fully built; the only gap is a counted python citing test.

### FS-18 (P0) — epic
- goal: build the frontend-backend contract GATE enforcing, per route-to-pane connection, six artifacts (schema fixture, route test, FE render test, permission test, mobile smoke, failure-mode test); cite it.
- acceptance: a `[REQ:FS-18]` test enumerates each wired route→pane connection and asserts all six artifacts exist; fails when a pane is wired without the full set.
- current_state: partial — test_adapter_contract_parity `[REQ:FS-18]` covers field-parity only; the six pieces exist scattered; no gate binding the checklist per connection.
- files: stewie/server/test_adapter_contract_parity.py, stewie/server/fixtures/, stewie/server/routers/, test_*_pane.py, test_ux_clusterb.py
- test_target: NEW stewie/server/test_contract_gate.py (`[REQ:FS-18]`)
- notes: subtasks — route→pane registry, map to six artifacts, failing gate, citation.

### FS-19 (P0) — epic
- goal: complete the observability ledger (every event class logs correlation-id + mission/site/body/time + actor + I/O hashes + result + latency + error, never secrets/truth-denied); broaden the citation.
- acceptance: `[REQ:FS-19]` tests assert each event class emits a full-field record with correlation-id threading, and redaction strips secrets + truth-denied fields.
- current_state: partial — services.py has correlation-id + redact + hash_payload + log_event; test_observability_ledger.py covers some (`[REQ:FS-19]`). Missing: not every class emitted/tested (role check, command emission, safing, model-inference, nav-factor, fleet conflict, state transition); truth-denied redaction not asserted.
- files: stewie/server/services.py, stewie/server/test_observability_ledger.py, stewie/server/test_audit_ledger.py, stewie/server/session.py, stewie/server/routers/
- test_target: extend stewie/server/test_observability_ledger.py with per-class `[REQ:FS-19]` assertions
- notes: some emitters (command, safing) may be ROS-bridge-gated — assert at the host-side seam. Subtasks: audit ~12 classes, wire missing emitters, truth-denied redaction, per-class tests.

### FS-21 (P2) — optional
- goal: finish the customizable workspace (drag/dock panes, persist per operator via localStorage + optional server profile, reset always available, view-only); broaden the citation.
- acceptance: `[REQ:FS-21]` tests assert drag-reorder persists+resets, the optional server-profile layout round-trips per operator, and the glue never touches auth/role/AG/contract.
- current_state: partial — panel_layout.js + wirePanelLayout + localStorage + reset, cited `[REQ:FS-21]`; view-only guard tested; layouts.js adds named layouts. Missing: server-profile layout, drag-to-dock beyond reorder.
- files: .../panel_layout.js, .../layouts.js, .../cockpit.js, stewie/server/index.html, stewie/server/routers/profiles.py, test_panel_layout_chrome.py, test_ui18_pane_manager.py
- test_target: extend stewie/server/test_panel_layout_chrome.py, OR NEW server-profile round-trip test
- notes: optional/soft — the localStorage+reset+view-only core (built+cited) may suffice to flip V=D; decide whether to satisfy the optional server-profile leg.

### FS-23 (P1) — epic
- goal: build the architecture-review traceability ledger — a living map PRD row → route/service → domain module → FE adapter/view → tests → logs — that exposes missing links without implying done.
- acceptance: a test/tool emits, per §7 row, its route/module/adapter/test/log links + a missing-link list, and asserts the ledger is generated (not hand-maintained) and flags a row with no route/test as incomplete.
- current_state: partial — req_trace maps row→`[REQ:]`test, fanout_plan maps row→lane/buildable/gated; no full route→module→adapter→log chain per row; no `[REQ:FS-23]`.
- files: scripts/req_trace.py, scripts/fanout_plan.py, PRD.md, stewie/server/routers/
- test_target: NEW scripts/test_arch_ledger.py (`[REQ:FS-23]`), OR extend req_trace to emit the full chain
- notes: reuse req_trace's marker scan + a route/module map; epic because the route→module→adapter→log links need a per-subsystem index. (Normalized by the aggregator, not a subagent.)

### FS-24 (P1) — atomic
- goal: add a python citing test locking the cockpit module split (app shell / state / adapters / view models / shared viz / work-area views / command rail / diagnostics) + proving CSP/no-inline + purity.
- acceptance: a `[REQ:FS-24]` test asserts the extracted pure ES modules load before cockpit.js (the 5 this session + adapters/cockpit_state/geofmt/htmlesc/role_rank/navplot/evidence_html/rover_hud), each is pure (no document./fetch(), sets its window.STEWIE_*, has a .test.js), and index.html has no inline script body.
- current_state: partial — 5 modules extracted this session + priors, each with a node .test.js; index.html loads all (FS-24 tagged); 0 inline scripts; CSP enforced by nginx + test_deploy_hardening. Missing: one python `[REQ:FS-24]` test tying split+purity+CSP.
- files: stewie/server/web/assets/{world_state_html,regolith_estimate,scorecard_chips,terrain_memory_html,nav_stats_html,adapters,cockpit_state,geofmt,htmlesc,role_rank,navplot,evidence_html,rover_hud}.js, stewie/server/index.html, stewie/server/test_deploy_hardening.py
- test_target: NEW stewie/server/test_cockpit_modularization.py (`[REQ:FS-24]`)
- notes: split + CSP already ship + are individually tested; the app-shell remainder is intentional. One gate test closes it.

---

## PO lane (packaging / ops / cockpit provenance) — 8 rows

### PO-01 (P0) — atomic
- goal: make "fresh wheel → `stewie-serve` runs with one product extra" close by citing an always-on proxy test + wiring the opt-in wheel smoke into a scheduled CI tier (the `[REQ:PO-01]` test is skip-by-default today).
- acceptance: a non-skipped test asserts `pip install stewie[server]` covers the import graph + the `stewie-serve` entrypoint resolves + the app builds; the wheel smoke runs in a release tier printing "FRESH WHEEL OK".
- current_state: partial — pyproject declares the script + [server] extra; test_fresh_wheel.py `[REQ:PO-01]` does the real clean-venv install but skips unless STEWIE_WHEEL_SMOKE=1; test_server_install.py runs always but has no marker.
- files: pyproject.toml, stewie/server/test_fresh_wheel.py, stewie/server/test_server_install.py, .github/workflows/ci.yml
- test_target: add `[REQ:PO-01]` to stewie/server/test_server_install.py::test_server_app_and_entrypoint_import; keep the wheel smoke + add a scheduled CI step
- notes: fix the contradictory row text ("alias stewie-serve deprecated" — no such alias exists; a botched rename artifact). Gold smoke needs network.

### PO-04 (P0) — epic
- goal: restructure CI to SEPARATELY gate the named tiers (python core / scripts / godot / browser-JS / package smoke / hardware-gated) + a test asserting the workflow declares them; fix the misattributed markers.
- acceptance: a test parses .github/workflows/ci.yml and asserts distinct gated jobs for each tier, and the browser tier actually runs the 29 JS `*.test.js` (which CI does not run today).
- current_state: partial/missing — ci.yml has only lint+test jobs running one combined pytest; gated tiers skip inline (not separate jobs); the 29 node:test files are not run; the 3 `[REQ:PO-04]` markers are on auth/secret tests (misattributed).
- files: .github/workflows/ci.yml, pyproject.toml (markers), stewie/server/web/assets/ (JS tests), deploy/
- test_target: NEW scripts/test_ci_tiers.py
- notes: subtasks — split ci.yml per tier, add a node/JS test job (real browser tier), reassign the 3 markers to their correct rows + add a real PO-04 test, confirm hardware tiers skip on the CPU runner.

### PO-05 (P1) — atomic
- goal: add the missing "scan resolved artifacts" step + wire the lock/SBOM/fresh-install scripts into CI as a real gate (lock+SBOM+fresh-install exist + are tested; only the CVE scan + CI wiring are missing).
- acceptance: a step runs a vuln scan over the resolved lock/SBOM + fails on a finding above threshold; the OPS-03 scripts are invoked as CI steps.
- current_state: partial — hash-pinned locks, gen_sbom.py (CycloneDX), check_deps_lock.py, fresh_install_smoke.py all exist with `[REQ:PO-05]` tests; no scanner (grype/trivy/pip-audit/osv); CI never invokes them.
- files: scripts/gen_sbom.py, scripts/check_deps_lock.py, scripts/fresh_install_smoke.py, requirements-dev.lock, requirements-server.lock, .github/workflows/ci.yml
- test_target: NEW scripts/test_scan_artifacts.py + a CI step
- notes: GATED (soft) — a live CVE scan needs a network vuln DB; assert the scan RAN + parsed real output (offline-DB fixture if no network); do not fabricate findings.

### PO-09 (P1) — atomic
- goal: add a real schema-migration mechanism for mission/profile schemas (versioning exists; the loader only REJECTS an unknown version).
- acceptance: a registered migrator upgrades a prior-version artifact to the current schema_version + it validates against the strict schema; a round-trip test loads a real legacy fixture and migrates it.
- current_state: partial — schema_version on every contract + profile loader validates + RAISES on mismatch; no migrate()/upgrade anywhere.
- files: stewie/contracts/__init__.py, stewie/specs/profiles.py, stewie/specs/profile_data/stewie_ipex_v1.json, lode/mission_planner.py
- test_target: NEW stewie/specs/test_profile_migration.py (`[REQ:PO-09]`)
- notes: HONESTY — only "1.0" schemas exist, so no real prior version to migrate from. Do not fabricate a legacy fixture; land the migrator registry + version-detecting loader + identity/rejection test, and record that a cross-version test is blocked until a 2nd schema ships (or capture a real prior artifact from git history).

### PO-10 (P1) — atomic
- goal: give the cockpit one tested four-way visual distinction among forecast / sim-truth / estimator-belief / live-telemetry (concepts exist scattered; state model carries a 3-value source enum).
- acceptance: a node:test asserts each of the four provenance classes renders with distinct labels/styles and the state model enumerates them.
- current_state: partial — VehicleState vs BeliefState, adapters normalizeBelief, execDraw forecast label, RC SSE live; but cockpit_state.js SOURCES=["live","sim","eval"] (3-value), no four-way labeling, no `[REQ:PO-10]`.
- files: .../cockpit_state.js, .../adapters.js, .../three3d.js, .../cockpit.js
- test_target: extend .../cockpit_state.test.js with `[REQ:PO-10]`, OR NEW .../provenance_label.test.js
- notes: integration-partial; keep pure/DOM-free for node:test (and it needs the PO-04 browser tier to count in CI).

### PO-11 (P1) — epic
- goal: make fleet playback render EVERY rover + each rover's INDEPENDENT telemetry (today it replays a single-rover forecast; the Fleet pane shows static tables).
- acceptance: given a multi-vehicle PlanResult (totals.vehicles_detail), playback renders one animated marker per rover on its own route with per-rover telemetry; a renderer test asserts N rovers → N tracks + N telemetry streams.
- current_state: missing — fleet_render.js builds static roster/allocation tables; execDraw animates ONE timeline (single marker); no per-rover multi-track playback; no `[REQ:PO-11]`.
- files: .../cockpit.js (execDraw P5), .../fleet_render.js, .../rover_hud.js
- test_target: extend .../fleet_render.test.js, OR NEW .../fleet_playback.test.js
- notes: data exists (plan_multi → totals.vehicles_detail); no backend gating. Subtasks: generalize execDraw over vehicles_detail, per-rover telemetry buffers, pure renderer test, wire into Fleet.

### PO-12 (P1) — epic
- goal: build an integrated Solar view (sun vector + illumination/shadow layers + active cameras/LEDs + arm posture + localization evidence accepted/rejected).
- acceptance: a Solar work-area renders, driven by one solar authority: sun vector (/ephemeris), illumination+shadow layers, active cameras/LEDs, arm posture, accepted-vs-rejected shadow evidence; a test asserts each element is present/labeled.
- current_state: missing as an integrated view — sun geometry (/ephemeris), illumination/incidence/psr layers (/layers), shadow-nav bearings (Perception pane) all exist but scattered; no "solar" work area; no `[REQ:PO-12]`.
- files: .../cockpit.js, .../cockpit_state.js, .../three3d.js, stewie/contracts/__init__.py
- test_target: NEW .../solar_view.test.js (`[REQ:PO-12]`)
- notes: FE + existing endpoints, not gated. Confirm the endpoint exposes SN-02 accept/reject flags before wiring.

### PO-14 (P1) — atomic
- goal: make optional Godot an explicit deploy PROFILE (ROS is a compose profile; Godot is not) + a test asserting docs + supported image + ros2/godot capability profiles are declared.
- acceptance: a test asserts deployment docs exist, a supported server image is defined (Dockerfile.backend/frontend + compose services), and compose declares optional capabilities as profiles including ros2 AND godot.
- current_state: partial — DEPLOY.md/README + Dockerfiles + compose exist; ros2 is a profile; no godot profile; no `[REQ:PO-14]`.
- files: deploy/compose.yml, deploy/DEPLOY.md, deploy/Dockerfile.backend, deploy/Dockerfile.frontend, deploy/ros2/
- test_target: NEW deploy/test_deploy_profiles.py (note deploy/ not in testpaths → place under scripts/ or add to testpaths)
- notes: a real Godot render service is GPU-gated, but declaring it as an opt-in compose profile + documenting it is not — the test asserts the profile is DECLARED.

---

## ML lane (perception / inference models) — 8 rows

### ML-02 (P1) — atomic
- goal: extend the terrain-assessment hazard layer to emit a hazard CLASS + slope/roughness SUMMARY + per-cell CONFIDENCE alongside the existing traversability/cost.
- acceptance: a test asserts build_hazard_map returns (a) a discrete hazard class per cell, (b) slope/roughness summary stats, (c) finite confidence in [0,1] dropping where inputs are nodata/UNKNOWN (nodata → low confidence AND no-go).
- current_state: partial — dart/hazard_map.py produces cost/slope_deg/rock_cost/traversable + nodata→no-go; missing class enum, summary, confidence layer; `[REQ:ML-02]` present but asserts only no-go.
- files: dart/hazard_map.py, dart/dem_cross.py, stewie/specs/rock_costs.py, dart/test_hazard_map.py
- test_target: dart/test_hazard_map.py::test_hazard_map_marks_steep_and_hard_rocks_nogo (extend, `[REQ:ML-02]` present)
- notes: real Haworth DEM fixture (skips if absent) — not GPU-gated.

### ML-03 (P1) — atomic
- goal: acceptance-GATE the Class-A (>7 cm) rock hazard classification against held-out truth with a pass/fail threshold; move the marker off the tautological binning test to the real held-out eval.
- acceptance: a test runs detect_rocks on a real held-out render, projects clast truth, scores it, and asserts precision/recall on the >7 cm avoid-class meet a declared threshold on held-out crater_boulders labels.
- current_state: partial — rock_taxonomy.classify bins + is_obstacle at 7 cm; rock_detect.py has the eval scorer (precision/recall vs projected truth, I3-firewalled); missing the threshold GATE; current `[REQ:ML-03]` sits on a bin-logic test.
- files: dart/rock_taxonomy.py, dart/rock_detect.py, dart/test_rock_detect.py, dart/test_rock_taxonomy.py
- test_target: dart/test_rock_detect.py::test_score_precision_recall_consistency (extend with a >7cm threshold gate + `[REQ:ML-03]`), OR NEW test_class_a_hazard_acceptance_gate
- notes: held-out inputs in-repo (stewie/eval/validation/a6_traverse + samples/crater_boulders); skips if absent — not GPU-gated.

### ML-04 (P1) — atomic
- goal: harden the shadow-SLAM factor path — assert factors carry covariance (information) AND the graph rejects factors failing a residual AND an observability gate.
- acceptance: a test asserts each accepted factor exposes non-negative information tied to sigma_deg, a low-observability/high-residual factor is rejected (not added), and good factors still recover a perturbed heading.
- current_state: most complete of ML (I=P,X=P,V=P) — shadow_factors.py builds contrast-gated yaw factors + recovers heading; NavFactor carries information + accepted verdict; missing explicit covariance-propagation assertion + an observability-gate rejection case.
- files: dart/shadow_factors.py, dart/pose_graph_se2.py, dart/se3_pose_graph.py, stewie/contracts/__init__.py (NavFactor), dart/test_shadow_factors.py
- test_target: dart/test_shadow_factors.py::test_shadow_factors_recover_a_perturbed_heading (extend, `[REQ:ML-04]` present)
- notes: verification hardening, not new capability.

### ML-05 (P1) — epic
- goal: build a unified ExcavationState estimator fusing drum torque/current + slip + IMU + arm/drum + drive current → {digging_state, fill_fraction, slip, stall_risk, confidence}, advisory until calibrated.
- acceptance: a test drives it from real conserved-sim signals, asserts the typed outputs, that confidence degrades with the DrumSensor uncertainty band, and the output is tagged advisory/uncalibrated.
- current_state: partial pieces, no integrator — fill+uncertainty+offload in rassor_mass_model.py, slip in slip.py, arm/drum in arm_state.py; excavation_state is only a ModelArtifact.task + a ROS topic. Missing the estimator + an IMU/torque input path.
- files: stewie/physics/rassor_mass_model.py, stewie/physics/slip.py, stewie/specs/arm_state.py, stewie/physics/worksite.py, stewie/bridge/autonomy_contract.py, stewie/contracts/__init__.py
- test_target: NEW stewie/physics/test_excavation_state.py
- notes: subtasks — typed ExcavationState output, fuse fill+uncertainty+slip→stall_risk+arm→digging_state, advisory flag, `[REQ:ML-05]` test on real signals.

### ML-06 (P1) — epic
- goal: build a regolith-volume estimator (moved volume/mass WITH UNCERTAINTY from observed before/after DEM/stereo), cross-checked vs conserved-authority mass + drum-fill.
- acceptance: a test estimates moved volume+mass from before/after heightfields, produces an uncertainty band, and asserts agreement (within band) with conserved mass_moved_kg AND the DrumSensor estimate.
- current_state: partial — mission_terrain_delta yields conserved delta + mass_moved_kg + net_volume; perception_measure produces observed dense-stereo RMSE; /render returns earthwork volumes. Missing: estimator over OBSERVED before/after + uncertainty + drum cross-check.
- files: lode/planner_acceptance.py, stewie/eval/perception_measure.py, stewie/twin/terrain_memory.py, stewie/physics/rassor_mass_model.py, lode/test_terrain_delta.py
- test_target: NEW lode/test_regolith_volume.py
- notes: the conserved-delta + drum cross-check legs are pure-numpy (testable now); the DENSE observed before/after leg needs rendered stereo (GPU) — GATED partial. Build the numpy legs, gate the dense leg.

### ML-07 (P1) — optional
- goal: enforce the mission-planner-LLM guardrail — any candidate task graph MUST compile to typed goals, pass deterministic validation, and be executive-approved before sim/lowering; the LLM itself is optional.
- acceptance: a test shows a candidate intent compiles through the typed MO-01 path to a validated Mission, an invalid/free-form plan is REJECTED at the typed boundary, and lowering/sim is blocked until the MissionExecutive approves.
- current_state: guardrail present, LLM absent — mission_intent_compiler.py (CP-04) + executive.py (MO-02) exist; no LLM.
- files: lode/mission_intent_compiler.py, stewie/contracts/mission_ops.py, stewie/contracts/executive.py, lode/mission_planner.py, lode/test_mission_intent_compiler.py
- test_target: extend lode/test_mission_intent_compiler.py with `[REQ:ML-07]`, OR NEW stewie/contracts/test_ml07_planner_guardrail.py
- notes: OPTIONAL — row says a model "MAY" convert intent; do NOT build an LLM. Only the compile→validate→approve guardrail is load-bearing; this is marker wiring.

### ML-08 (P1) — optional
- goal: establish the science/operator assistant as a read-only summarizer with the enforceable invariant of no command path.
- acceptance: a test asserts an assistant ModelArtifact(task="assistant") cannot be on the command path (command_path=True raises) and any summary surface consumes read-only twin/telemetry.
- current_state: governance only — ModelArtifact enumerates task="assistant" + enforces command_path=False; read-only twin routes exist; no summarizer.
- files: stewie/contracts/__init__.py, stewie/server/routers/twin.py, stewie/server/routers/plan.py, stewie/contracts/test_contracts.py
- test_target: extend stewie/contracts/test_contracts.py::test_model_artifact_cannot_be_on_command_path with `[REQ:ML-08]`
- notes: OPTIONAL — the load-bearing part is the read-only/no-command invariant (already provided); don't build a live summarizer unless requested.

### ML-09 (P0) — epic
- goal: define the edge deployment envelope — a Jetson-Orin-class compute profile (RAM/power/thermal/latency/sensor-IO) + an aggregate check that any SIMULTANEOUS model set fits it + degraded-mode scheduling.
- acceptance: a test asserts a set of ModelArtifact budgets (latency+memory + power/thermal/IO) validated against a selected Orin profile: an over-RAM/power/latency set FAILS, and degraded-mode returns a reduced feasible set.
- current_state: missing — profiles.py has runtime profiles but no Jetson/Orin/TOPS/watt/thermal compute profile; ModelArtifact carries latency+memory only; no aggregate fit check, no degraded scheduler.
- files: stewie/specs/profiles.py, stewie/contracts/__init__.py, stewie/server/services.py (FS-10 pattern), stewie/server/routers/models.py
- test_target: NEW stewie/specs/test_edge_envelope.py
- notes: P0. Pure-Python accounting against published Jetson specs — NOT GPU-gated. Subtasks: Orin profile spec (provenance-tagged), extend ModelArtifact with power/thermal/IO, aggregate fit checker, degraded-mode scheduler.

---

## PM lane (perception / measurement) — 6 rows

### PM-01 (P0) — epic
- goal: provide a unified explicit-clock + frame-ID synchronizer time-aligning camera/IMU/command/arm/truth streams into one estimator-consumable timeline.
- acceptance: a test asserts each stream associates to a common clock within tolerance + carries frame_id; matched camera pairs share a stamp, IMU/truth nearest-matched within tolerance, out-of-tolerance rejected.
- current_state: partial — nearest-timestamp assoc is real per-reader (s3li_reader, lusnar_reader) + ROS frame_id/stamp in bag_writer/rover_executive_node; missing: command(cmd_vel)+arm streams not aligned, no single cross-stream synchronizer.
- files: dart/s3li_reader.py, dart/lusnar_reader.py, scripts/ros2_bridge/bag_writer.py, scripts/ccsds_ros_nav/nodes/rover_executive_node.py
- test_target: extend dart/test_s3li_reader.py with `[REQ:PM-01]`; NEW dart/test_stream_sync.py for the unified aligner
- notes: the camera/IMU/truth sync is CPU-closeable now; the command/arm leg partly depends on McCardle's UDP/ROS link protocol (NV-11/12 external) — flag that sub-part GATED.

### PM-03 (P1) — epic
- goal: add an eval-mode segmenter labeling ≥ ground/rock/lander/fiducial/sky from grayscale without a truth mask.
- acceptance: a test feeds a real grayscale render (no truth mask) and asserts per-pixel/region labels cover the five classes, the perception signature takes an image only (I3 invariant), scored vs held-out truth in the eval path only.
- current_state: partial — masking.py defines the class set but filter_keypoints CONSUMES truth; only detect_shadow_mask + rock_detect are truth-free (2 of 5 classes); ground/lander/fiducial/sky have none.
- files: dart/masking.py, dart/rock_detect.py
- test_target: NEW dart/test_eval_segmentation.py
- notes: classical ground/rock/sky/shadow subset is CPU-closeable; reliable lander/fiducial-from-grayscale may need a learned model (render/GPU-gated).

### PM-04 (P1) — atomic
- goal: cite + close the illumination-robust feature detect/match row (already exposes confidence/inlier stats).
- acceptance: a test on the real rendered stereo pair asserts a RANSAC inlier ratio above a floor, a finite sub-few-pixel median Sampson error, and reported n_inliers/inlier_ratio/runtime.
- current_state: implemented + tested — features.py (ORB/SIFT CPU + DISK/LightGlue) exposes n_inliers/inlier_ratio/median_sampson_px/runtime_s; superpoint_vo.py is the NAVLAB26 front end; gap: no explicit illumination A/B test; learned leg needs GPU.
- files: dart/features.py, dart/superpoint_vo.py
- test_target: dart/test_features.py::test_math_check_at_least_one_method_exceeds_inlier_floor (add `[REQ:PM-04]`)
- notes: CPU classical path + stats satisfy the row now; learned SuperPoint/LightGlue leg is GATED (GPU). A lit/unlit A/B (exists under benchmarks/) would strengthen it.

### PM-07 (P0) — atomic
- goal: cite + close the loop-closure row (candidate-gated, geometrically verified, auditable, false closures kept out of the graph).
- acceptance: a test asserts candidates are gated by appearance+gap only (no GT), accepted closures passed PnP-RANSAC with a recorded reject_reason, all attempts retained for audit, only accepted closures become factors, and an aliased candidate is rejected + excluded.
- current_state: implemented + tested — loop_closure_visual.py (propose/verify/detect/to_json/build_loop_factors); gap: no explicit negative test that a rejected candidate is excluded; verify leg needs torch.
- files: dart/loop_closure_visual.py, dart/loop_closure.py
- test_target: dart/test_loop_closure_visual.py::test_detect_loops_finds_start_end_revisit_and_chain_matches_vo (add `[REQ:PM-07]`) + a negative-case test
- notes: candidate-gating + audit + accepted-only are pure numpy; verify_candidate re-runs LightGlue (torch, skips when cache absent) — partial GPU dependency; substantially closeable with a marker + negative test.

### PM-10 (P1) — epic
- goal: build one fixed LAC-style benchmark suite (localization RMSE, 5 cm height-cell pass, rock F1, coverage, runtime, failure count) swept over seeds × light × rocks.
- acceptance: a test runs the suite over the condition matrix and asserts a report with all six metrics per condition + an integer failure count, aggregated across the sweep.
- current_state: partial — metrics exist scattered (score_pose ate_mm, score_map cell_pass/rock_f1/coverage, features runtime, ablation ATE); eval_harness.py is report-only, single-scene, synthetic, no assembly/sweep.
- files: scripts/ros2_bridge/score_map.py, scripts/ros2_bridge/score_pose.py, scripts/ros2_bridge/eval_harness.py, dart/ablation.py, dart/map_channel.py, benchmarks/
- test_target: NEW scripts/ros2_bridge/test_lac_suite.py (or benchmarks/lac_suite/)
- notes: localization RMSE has real CPU numbers (S3LI/Katwijk); rock-F1/coverage on rendered scenes are render/GPU-gated — flag those legs GATED, report them as gated rows, don't fabricate. Subtasks: assemble six metrics, condition matrix, per-condition rows + failure count, suite test.

### PM-11 (P1) — gated
- goal: demonstrate repeatable cm-scale localization comparable to the 0.038-0.067 m NAVLAB26 band before any parity claim.
- acceptance: a benchmark reports localization RMSE in the 0.038-0.067 m band across repeats on LAC data, with the harness refusing "parity" until reached.
- current_state: blocked — present numbers are meters-scale (Katwijk ~3.35 m); cm parity needs the GPU dense render→depth + SuperPoint/LightGlue pipeline on LAC/IPEx sim data, absent on this host.
- files: benchmarks/katwijk/, benchmarks/s3li_crater/, scripts/ros2_bridge/score_pose.py
- test_target: NEW benchmarks/lac_suite/test_cm_parity.py (depends on PM-10)
- notes: GATED (GPU dense-stereo + weights + LAC data). Closeable slice = the comparison harness reporting current RMSE vs the band + withholding any parity claim; the demonstration itself cannot complete on this host.

---

## TW lane (terrain / illumination) — 3 rows

### TW-05 (P1) — epic
- goal: give the fleet one WorldState carrying all four per-cell fields together (material, traversability, observed/unobserved, calibrated uncertainty) instead of four scattered rasters; prove on real Haworth.
- acceptance: one WorldState/twin exposes per cell material + traversability cost/impassable + observed mask + calibrated sigma; a test asserts all four share the grid shape, unobserved cells carry no uncertainty/lock, observed cells get a finite sigma.
- current_state: all four exist disjoint — material (column_state), traversability (costmap_layers), observed (world_model_layers), uncertainty (mapping.ElevationMap.cell_uncertainty); the WorldState contract carries only scalar metadata.
- files: stewie/contracts/__init__.py, dart/world_model_layers.py, lode/costmap_layers.py, dart/mapping.py, stewie/physics/column_state.py
- test_target: NEW dart/test_world_model_layers.py::test_worldstate_carries_material_traversability_observed_uncertainty (`[REQ:TW-05]`)
- notes: subtasks — add material+traversability layers to WorldModelLayers, attach cell_uncertainty keyed to observed, surface through the WorldState contract, real-DEM test.

### TW-09 (P2) — atomic
- goal: model camera-LED illumination as a field separate from solar, parameterized by per-camera intensity AND pose, composable with the terrain solar map.
- acceptance: a function takes camera pose(s)+intensity → an LED contribution field distinct from the solar field; a test asserts LED is separate, intensity monotonically increases light, pose changes the footprint, zero intensity leaves the solar field byte-identical.
- current_state: partial — led_budget.py (SN-07) selects camera subset + intensity; comparison.py books LED energy; no LED-contribution model with configurable POSE separate from solar in illumination.py.
- files: dart/led_budget.py, dart/illumination.py, dart/camera_rig.py, dart/comparison.py
- test_target: NEW dart/test_illumination.py::test_led_contribution_separate_from_solar_with_pose_and_intensity (`[REQ:TW-09]`)
- notes: the numeric model is buildable (no hardware); the photorealistic render leg is GATED (Godot GPU).

### TW-10 (P2) — optional
- goal: add a dust/optical-degradation STATE that accumulates over operations + drives image-quality and maintenance decisions (not just render particles).
- acceptance: a degradation model where degradation accumulates with exposure, maps to an image-quality metric, and crosses a maintenance threshold; a test asserts monotonic increase, quality drop, threshold fire.
- current_state: missing as a state — dust is render-only particles (sidecar.gd) + a rover shader; no accumulation state, no quality coupling, no maintenance trigger.
- files: dart/illumination.py, stewie/physics/column_state.py, stewie/godot/sidecar.gd (render only)
- test_target: NEW dart/test_optical_degradation.py (`[REQ:TW-10]`)
- notes: OPTIONAL — row is `[PROPOSED]`, matrix all-N. Build the numpy state model; do not gate on Godot dust.

---

## SN lane (solar navigation) — 3 rows

### SN-12 (P1) — epic
- goal: turn the single-trajectory solar-vs-VO/SLAM head-to-head into a real ablation SWEEP across sun angles × terrains × terrain-change states × seeds.
- acceptance: an ablation harness runs the add-one solar-factor comparison over a grid (≥2 sun angles × ≥2 terrains × ≥2 terrain-change × ≥N seeds) returning per-condition ATE + heading error with vs without solar factors; a test asserts a result per grid point and solar-on beats solar-off aggregated.
- current_state: partial scaffold — ablation.py (seeded add-one) + integrated_slam.shared_testbed_comparison + POST /slam/compare (`[REQ:SN-12]` in test_server.py); all run on ONE Katwijk trajectory over seeds only, no sun/terrain/terrain-change sweep.
- files: dart/ablation.py, dart/integrated_slam.py, stewie/server/routers/perception.py
- test_target: extend dart/test_ablation.py with a `[REQ:SN-12]` sweep test
- notes: real SLAM stacks are modeled-at-sigma (honest comparison-of-classes) — keep that. Subtasks: sweep driver, per-grid illumination/terrain, aggregate, test.

### SN-13 (P1) — optional
- goal: add the preregistered acceptance gate for solar-nav claims (improve median yaw/pose error or track survival by a preregistered margin WITHOUT increasing tip events; report energy/time overhead).
- acceptance: a gate takes solar-on vs -off metrics + a preregistered margin → pass/fail requiring (1) median improvement ≥ margin, (2) tip events not increased, (3) energy+time overhead reported; a test asserts pass on a qualifying delta + fail otherwise.
- current_state: missing — no prereg-margin gate; building blocks exist (ablation yaw/pose, comparison energy/time, stability tip events).
- files: dart/ablation.py, dart/comparison.py, stewie/physics/stability.py, lode/faults.py
- test_target: NEW dart/test_ablation.py::test_sn13_preregistered_margin_gate (`[REQ:SN-13]`)
- notes: OPTIONAL — target is `[PROPOSED]`. Pure metric-gate logic over existing outputs; sequence AFTER SN-12 (consumes its sweep).

### SN-14 (P1) — atomic
- goal: build the active-perception objective ranking candidate observation actions by expected info per joule and per second, with stability margin as a HARD constraint.
- acceptance: an objective scores actions as info-gain ÷ (energy_J + time_s), rejecting any below stability threshold; a test asserts (1) infeasible-stability excluded regardless of info, (2) higher info-per-cost wins, (3) energy AND time enter the denominator.
- current_state: partial — posture_select.py (SN-08) treats stability as a hard gate + exposes viewpoint_gain; camera_select scores washout; missing per-joule/per-second normalization + unified ranking.
- files: dart/posture_select.py, dart/camera_select.py, dart/solar_observation.py, stewie/specs/ipex_specs.py
- test_target: NEW dart/test_posture_select.py::test_sn14_info_per_joule_per_second_with_stability_hard_constraint (`[REQ:SN-14]`)
- notes: reuse the stability gate + viewpoint_gain numerator; pull per-action energy+duration from ipex_specs; a new dart/active_perception.py may be the cleaner home.

---

## FL lane (fleet / multi-vehicle) — 3 rows

### FL-04 (P1) — atomic
- goal: implement ACTIVE work-reallocation — when fleet_needs_replan fires (a stranded rover), reassign its remaining work to healthy rovers, not just flag it.
- acceptance: on a plan where one rover strands, the planner reallocates its unfinished trips to feasible rovers + returns a re-simulated plan where the work is covered (or reports genuine infeasibility); a test asserts the trips are picked up + the fleet completes.
- current_state: partial — _rover_health sets fleet_needs_replan (detection tested `[REQ:FL-04]`); cross-precedence split exists; the trigger fires but nothing rebalances on it (acceptance text: "active reallocation is future MV work").
- files: lode/mission_planner.py, lode/planner_assembly.py, lode/planner_multivehicle.py
- test_target: NEW lode/test_fl04_precedence_split.py::test_stranded_rover_work_is_reallocated_to_healthy_rovers (`[REQ:FL-04]`)
- notes: on the trigger, re-run allocation excluding the stranded rover's unreachable trips (reuse _allocate_trips + per-vehicle re-sim); keep conservative.

### FL-05 (P1) — atomic
- goal: wire heterogeneous vehicle capability/physics vectors into the FLEET plan so one plan_multi run carries rovers with different physics (not N identical clones).
- acceptance: plan_multi accepts a heterogeneous vehicle list + a two-rover plan with different vehicles produces per-vehicle differences in the applicable numbers; a test asserts the two rovers get different physics-driven results + capability-gated trips.
- current_state: partial — heterogeneity exists at the specs layer (vehicles.py Deployment/Placement, tested `[REQ:FL-05]`); plan_multi takes vehicles=<int> and clones ONE physics across all.
- files: lode/planner_assembly.py, lode/planner_multivehicle.py, stewie/specs/vehicles.py
- test_target: NEW lode/test_mission_planner.py::test_fl05_heterogeneous_fleet_plan_uses_per_vehicle_physics (`[REQ:FL-05]`)
- notes: thread a per-vehicle spec list through _build_per_vehicle/sim; keep vehicles=<int> (homogeneous) byte-identical for back-compat.

### FL-07 (P1) — optional
- goal: make Solar/Meerkat raised observation sites reservable fleet resources with an occlusion/collision exclusion.
- acceptance: a raised observation declares a vantage reservation (time-windowed, capacity-1 + exclusion radius); a test asserts two rovers can't hold overlapping raised observations at conflicting vantages (loser waits) + the wait folds into makespan.
- current_state: partial substrate — fleet_resources.py has a vantage kind + FCFS ledger, planner_multivehicle schedules declared vantages (FL-03); missing: nothing declares a raised observation as a vantage + no occlusion exclusion.
- files: lode/fleet_resources.py, lode/planner_multivehicle.py, lode/planner_model.py, dart/solar_observation.py, dart/posture_select.py
- test_target: NEW lode/test_fleet_resources.py::test_fl07_raised_observation_reserves_vantage_no_occlusion (`[REQ:FL-07]`)
- notes: OPTIONAL — `[PROPOSED]`. Pure planner logic; map a Meerkat/solar observation to a vantage reservation + exclusion radius via the FL-03 ledger.

---

## Other small lanes — 12 rows

### GI-01 (P0, GIS) — gated
- goal: turn the CSP/runtime smoke into a real desktop + mobile browser check against the DEPLOYED headers asserting Cesium + Moon/Mars/Earth imagery + worksite overlays + sign-in + mobile nav load with zero blocking console errors.
- acceptance: a Playwright smoke loads the app under the production CSP at desktop + mobile viewports, captures console errors, asserts zero blocking messages while Cesium+imagery+overlays+sign-in render.
- current_state: partial — web01_csp_smoke.py loads under the nginx CSP at desktop + collects console errors; missing mobile pass, overlay/sign-in/nav assertions, running against deployed headers.
- files: scripts/web01_csp_smoke.py, deploy/nginx.conf, deploy/Dockerfile.frontend, stewie/server/cesium/index.js, stewie/server/index.html
- test_target: NEW stewie/server/test_gi01_runtime_smoke.py (`[REQ:GI-01]`)
- notes: GATED on a running deploy — the local-CSP desktop smoke is buildable now; the deployed-header + mobile/device leg needs a live app.stewie.space reachable from the test host.

### GI-02 (P1, GIS) — atomic
- goal: give each body body-correct ellipsoid/CRS metadata + drive real DEM 3D terrain where a layer claims terrain, labeling any smooth WGS84 drape imagery-only.
- acceptance: a test asserts Moon/Mars records carry correct ellipsoid radii + CRS (Moon ~1737.4 km), any 3D-terrain layer resolves to a real DEM source, and a smooth-drape layer is flagged imagery_only.
- current_state: partial — bodies.json has Moon/Mars (g/bekker/power) + map_layers groups terrain rasters; NO ellipsoid/radii/CRS fields, no terrain-vs-imagery honest labeling.
- files: stewie/server/bodies.json, stewie/server/map_layers.py, stewie/server/gen_bodies_json.py, stewie/server/cesium/index.js
- test_target: NEW stewie/server/test_gi02_body_crs.py (`[REQ:GI-02]`)
- notes: real-DEM terrain reuses the Haworth LOLA path; a Cesium 3D terrain provider may need tiled assets — honest fallback is label-as-imagery-only, which the test enforces.

### GI-03 (P2, GIS) — atomic (done-stale)
- goal: verify + glyph-reconcile the mission-required GIS interop subset (GeoJSON/COG import, feature query, offline mission package) that is already implemented.
- acceptance: the existing suite passes — RFC-7946 export round-trips, features match orders/keep-outs/route, COG availability honest, import inverts export + rejects non-FeatureCollections, offline package self-contained + reimportable, attribute query filters.
- current_state: implemented + tested — lode/gis_export.py + 7 `[REQ:GI-03]` tests in lode/test_gis_export.py. Row glyphs (N/N/N) are lag.
- files: lode/gis_export.py, lode/test_gis_export.py
- test_target: lode/test_gis_export.py::test_export_is_valid_rfc7946_featurecollection_that_parses_back (verify green + reconcile the §7 glyph)
- notes: NO new implementation — closure is verification + glyph reconciliation.

### VT-04 (P1) — atomic
- goal: replace the single global drum-inventory scalar with per-drum (four-drum) fill tracking for IPEx while preserving mass conservation.
- acceptance: ColumnState exposes a 4-element per-drum fill (kg) whose sum equals total drum mass; excavate/deposit routes to specific drums, per-drum fill non-negative + capacity-bounded, the grid+drum mass invariant round-trips.
- current_state: partial — column_state.py holds drum_inventory as ONE scalar; system_profile declares n_drums=4; no per-drum array.
- files: stewie/physics/column_state.py, stewie/specs/system_profile.py, stewie/specs/ipex_specs.py, stewie/physics/test_column_state.py
- test_target: NEW stewie/physics/test_column_state.py::test_vt04_per_drum_fill_conserves_total (`[REQ:VT-04]`)
- notes: keep the scalar total as sum(per_drum) so existing callers stay byte-identical when unsplit.

### VT-08 (P1) — atomic (soft)
- goal: model drum fill-RATE so effective collection saturates beyond ~half scoop depth (bridging plateau), per the sourced RASSOR behavior.
- acceptance: a fill-rate function over scoop depth returns a curve non-decreasing up to ~half depth + flat-or-declining beyond; a test asserts the beyond-half increment ≤ the pre-half increment.
- current_state: not modeled — rassor_mass_model.py has HALF_FULL_KG=20.0 for mass-inference error only, not a fill-rate/bridging model.
- files: stewie/physics/rassor_mass_model.py, stewie/physics/rover.py, stewie/specs/system_profile.py
- test_target: NEW stewie/physics/test_drum_sensing.py::test_vt08_fill_rate_bridging_plateau (`[REQ:VT-08]`)
- notes: SOFT (Q=P modeling choice); reuse HALF_FULL_KG source — no new external data.

### EP-01 (P0) — atomic
- goal: extend the energy ledger so observation, LED, compute, idle/heater appear as separate retrievable terms alongside drive/slope-slip/payload/dig/arm-drum/recharge, or are explicitly marked unmodeled.
- acceptance: plan totals expose each modeled term as its own key, modeled terms sum exactly to energy_J, any unmodeled term is explicitly flagged (not silently zero).
- current_state: partial — ledger tracks drive/haul/dig/lift/slip/charges/thermal-derate/idle; body base-power in bodies.json; missing as SEPARATE terms: observation, LED, compute. Two `[REQ:EP-01]` tests cover the existing separation.
- files: lode/planner_sim.py, lode/planner_trips.py, lode/mission_planner.py, lode/planner_endurance.py, lode/test_mission_planner.py
- test_target: lode/test_mission_planner.py::test_ep01_ledger_keeps_drive_slip_payload_and_dig_as_separate_terms (extend, `[REQ:EP-01]` present)
- notes: "where modeled" → enumerate every term key + flag unmodeled ones; do not fabricate observation/LED/compute magnitudes without a source.

### EP-07 (P2) — atomic
- goal: add a dust-accumulation state degrading optics/joints/thermal surfaces + driving maintenance actions in the energy/ops model.
- acceptance: a dust-state field accumulates over drive/dig activity + (a) reduces optical transmittance / raises joint friction / raises thermal-survival demand, (b) triggers a maintenance/clear action; a test asserts monotonic accumulation + post-clear residual.
- current_state: not in the energy/ops ledger — column_state handles bonded crust (not loose dust); eds_dust.py models EDS lens-cover transmittance in the perception bridge only.
- files: scripts/ros2_bridge/eds_dust.py, stewie/physics/column_state.py, stewie/specs/constants.py, lode/planner_sim.py
- test_target: NEW lode/test_ep07_dust.py (`[REQ:EP-07]`)
- notes: P2. Reuse eds_dust transmittance for optics; joints/thermal/maintenance are new; source accumulation rate to SCHULER24, don't invent.

### NV-02 (P1) — atomic
- goal: add a coverage-route generator emitting overlapping-loop / outward-spiral waypoints promoting map coverage + deliberate re-observation / loop closure.
- acceptance: a planner function over a region returns an ordered route whose swept coverage exceeds a point-to-point route AND revisits ≥1 earlier region (a loop-closure candidate); scored on real Haworth.
- current_state: partial — coverage measurement (map_channel.coverage_mask), coverage-pattern cost (comparison.coverage_pattern_cost), revisit detection (loop_closure.detect_revisits) exist; missing the route GENERATOR in the planner (only a scripted Godot demo).
- files: dart/map_channel.py, dart/comparison.py, dart/loop_closure.py, lode/planner_routing.py, lode/nav_pipeline.py
- test_target: NEW lode/test_coverage_route.py (`[REQ:NV-02]`)
- notes: reuse coverage_mask to score + detect_revisits to prove re-observation; the NAVLAB26 outward-spiral is the reference.

### DT-01 (P0) — epic
- goal: link the remaining runtime packets + the vehicle twin into the one versioned transaction envelope that already unifies authority + TwinStore + PlanResult + belief + session events.
- acceptance: a test constructs an envelope transaction from a RuntimePacket + a VehicleTwin update, asserts both carry the versioned header, enter the hash-chained log, and a cold rebuild reproduces them bit-exact.
- current_state: partial — envelope.py + WorldStateService + hash-chained log + the SIM execute→remember loop are built + tested `[REQ:DT-01]`; envelope.py references NEITHER RuntimePacket NOR VehicleTwin — those unifications are unbuilt.
- files: stewie/twin/envelope.py, stewie/twin/runtime_packet.py, stewie/specs/vehicle_twin.py, stewie/twin/test_envelope.py, stewie/server/test_world_state_service.py
- test_target: stewie/twin/test_envelope.py (extend, `[REQ:DT-01]` present) — add packet + vehicle-twin cases
- notes: subtasks — wrap RuntimePacket emission in an envelope transaction, fold VehicleTwin updates in, extend the cold-rebuild journal test to both new kinds.

### RL-01 (P1) — gated
- goal: enforce (+ mark) the deployed-RL-policy gate (no RL operational without versioned artifact + lineage + card + safety shield + deterministic fallback + OOD report).
- acceptance: a test asserts ModelArtifact.deployment_ready is False unless all six conditions hold + command_path=True rejected + /models reports deployed_models==[] (nothing operational until artifacts exist).
- current_state: gate defined, zero deployed policy — ModelArtifact + deployment_ready gate + /models governance + test_models_pane assert the empty-deploy; RL scaffolding exists (rover_env, cem) but no policy artifact/card/lineage/OOD report.
- files: stewie/contracts/__init__.py, stewie/server/routers/models.py, stewie/server/test_models_pane.py, stewie/envs/rover_env.py, validation/rl/
- test_target: stewie/server/test_models_pane.py::test_models_endpoint_serves_the_real_registries (add `[REQ:RL-01]`)
- notes: GATED — an operational RL policy needs a real training run + lineage/card/OOD + a safety shield (no synthetic policy). Enforceable-now close = the gate test proving nothing operational passes without them.

### SL-01 (P0) — epic / gated
- goal: close the truth-isolated SLAM/Nav benchmark — keep the built truth-topic denial, add evaluator-only pass/fail thresholds, score the full render→sensor→RTAB-Map→Nav→pose-graph pipeline end to end.
- acceptance: runtime bags/estimators are structurally denied truth (done), AND an evaluator-only scorer runs the full pipeline + emits pass/fail against localization RMSE / height-cell / map thresholds.
- current_state: partial — truth-isolation real + tested `[REQ:SL-01]` (bag_writer routes truth to the evaluator bag not tf; score_pose/score_map + launch files + Dockerfile exist); eval_harness.py is explicitly REPORT-ONLY (no thresholds — "inventing one would be fraudulent"); the full live pipeline is not scored.
- files: scripts/ros2_bridge/eval_harness.py, scripts/ros2_bridge/score_pose.py, scripts/ros2_bridge/score_map.py, scripts/ros2_bridge/bag_writer.py, scripts/ros2_bridge/slam_bringup.launch.py, scripts/ros2_bridge/test_bag_truth_split.py
- test_target: scripts/ros2_bridge/test_bag_truth_split.py (extend, `[REQ:SL-01]` present) with an evaluator-only threshold assertion
- notes: GATED — the full scored run needs a ROS2 Jazzy + RTAB-Map container + a real bag run. Buildable now: threshold-schema + truth-isolation. Subtasks: preregister thresholds from a real reference run, wire the evaluator-only channel, run the container pipeline + record the artifact.

### SE-01 (P0) — epic / gated
- goal: complete the full release security-audit gate (host / container / app / DNS-site / secret / backup-restore / dependency-SBOM-CVE / external-exposure) with recorded evidence.
- acceptance: a release-gate check confirms each of the eight domains has a completed dated evidence artifact, including an SBOM+CVE scan of resolved artifacts + a drilled backup/restore.
- current_state: partial slices — gen_sbom + deps lock (dependency/SBOM), test_deploy_hardening (container), sec01/sec04/web01 smokes (app), SECURITY.md. Missing: CVE scan of the SBOM, host/DNS/site/secret/external-exposure audits, a drilled backup/restore.
- files: scripts/gen_sbom.py, scripts/_deps_lock.py, stewie/server/test_deploy_hardening.py, scripts/sec01_cookie_smoke.py, scripts/sec04_xss_smoke.py, SECURITY.md, docs/RELEASE.md
- test_target: NEW scripts/test_se01_audit_gate.py (`[REQ:SE-01]`)
- notes: GATED — host/DNS/external-exposure + a real backup/restore drill need live-host/DNS access + a second host (off-host replication unbuilt). Subtasks: CVE-scan the SBOM, build the backup/restore drill (ties DT-01 cold rebuild), an audit-gate manifest test over all eight domains; the infra legs are gated.

## AS lane (flight autonomy / ROS2 -- container-buildable, Codex-cleared 2026-07-02) -- 12 rows

Host-side contract slice buildable here (ros2_ws/ tests run without a live ROS via conftest); the live-node/RViz runtime leg is container-gated. Screens from the 2026-07-02 AS fan-out (verified vs the live tree).

### AS-01 (AS) — atomic
- goal: the Autoware-shaped node graph + topic contract is frozen in autonomy_contract.py; cite the boundary test.
- acceptance: a [REQ:AS-01] python test asserts the row's host-side contract non-vacuously (the live-ROS runtime leg is gated).
- files: stewie/bridge/autonomy_contract.py, ros2_ws/test_ws_skeleton.py
- test_target: stewie/bridge/test_autonomy_contract.py (extend with [REQ:AS-01] node-graph/topic-contract assertion)
- type: atomic (host-side slice; live-node leg container-gated)

### AS-04 (AS) — atomic
- goal: Build Dockerfile.perception_slam, Dockerfile.bridge, Dockerfile.space_ros each FROM stewie-ros2dev:jazzy with pinned packages and smoke commands. Update test_container_tiers.py BUI
- acceptance: a [REQ:AS-04] python test asserts the row's host-side contract non-vacuously (the live-ROS runtime leg is gated).
- files: deploy/ros2/Dockerfile.perception_slam, deploy/ros2/Dockerfile.bridge, deploy/ros2/Dockerfile.space_ros, ros2_ws/test_container_tiers.py, deploy/ros2/evidence/README.md
- test_target: /mnt/projects/stewie/code/ros2_ws/test_container_tiers.py
- type: atomic (host-side slice; live-node leg container-gated)

### AS-07 (AS) — atomic
- goal: **Smallest honest closeable slice for AS-07:**

Create stewie/eval/test_nav_spine_integration.py that:
1. Instantiates mock depth sources (mock stereo point cloud, mock RGB-D, mock
- acceptance: a [REQ:AS-07] python test asserts the row's host-side contract non-vacuously (the live-ROS runtime leg is gated).
- files: dart/features.py, dart/integrated_slam.py, stewie/eval/test_nav_spine_integration.py
- test_target: stewie/eval/test_nav_spine_integration.py
- type: atomic (host-side slice; live-node leg container-gated)

### AS-08 (AS) — atomic
- goal: 1. Refactor shadow_factors.py to import MeasurementFactor, FactorType, Frame, EvidenceClass from dart.factors. 2. Update shadow_yaw_factors() to return list[MeasurementFactor] inst
- acceptance: a [REQ:AS-08] python test asserts the row's host-side contract non-vacuously (the live-ROS runtime leg is gated).
- files: dart/shadow_factors.py, dart/test_shadow_factors.py
- test_target: /mnt/projects/stewie/code/dart/test_shadow_factors.py
- type: atomic (host-side slice; live-node leg container-gated)

### AS-09 (AS) — atomic
- goal: 1. Publish accepted navigation factors to /stewie/nav/factors topic (visualization_msgs/Marker array with position, covariance, source, acceptance flag) from stewie/bridge/localiza
- acceptance: a [REQ:AS-09] python test asserts the row's host-side contract non-vacuously (the live-ROS runtime leg is gated).
- files: stewie/bridge/localization_node.py, ros2_ws/src/stewie_rviz/rviz/mission.rviz, ros2_ws/test_nav_factor_visualization.py
- test_target: dart/test_relocalization.py (existing, passing 4/4) cites the core acceptance/rejection/covariance logic; new test ros2_ws/test_nav_factor_visualization.py would cite the RViz visualization slice
- type: atomic (host-side slice; live-node leg container-gated)

### AS-10 (AS) — atomic
- goal: The smallest closeable slice is a TDD test that (1) builds a real ElevationMap from stereo pairs (real Godot frames + camera trajectory), (2) updates WorldModelLayers.observed from
- acceptance: a [REQ:AS-10] python test asserts the row's host-side contract non-vacuously (the live-ROS runtime leg is gated).
- files: dart/test_world_model_layers.py, dart/mapping.py, dart/world_model_layers.py, stewie/physics/excavation_state.py
- test_target: dart/test_world_model_layers.py::test_update_observed_from_real_elevationmap (existing test; extend with excavation-state assertion + multi-layer simultaneity proof)
- type: atomic (host-side slice; live-node leg container-gated)

### AS-11 (AS) — atomic
- goal: the lunar costmap layers (slope/roughness/sinkage/slip/tip) exist; cite the layer-stack test.
- acceptance: a [REQ:AS-11] python test asserts the row's host-side contract non-vacuously (the live-ROS runtime leg is gated).
- files: dart/world_model_layers.py, lode/map_uncertainty_route.py
- test_target: dart/test_world_model_layers.py (extend with [REQ:AS-11] costmap-layer assertion)
- type: atomic (host-side slice; live-node leg container-gated)

### AS-12 (AS) — atomic
- goal: Add a unified [REQ:AS-12] test that proves: (1) a real mission's lowered Plan IR contains work_goals with all fields (op, site, mass_kg, expect energy); (2) each lowered message pa
- acceptance: a [REQ:AS-12] python test asserts the row's host-side contract non-vacuously (the live-ROS runtime leg is gated).
- files: stewie/server/test_plan_ros_route.py
- test_target: /mnt/projects/stewie/code/stewie/server/test_plan_ros_route.py (extend existing test file with new [REQ:AS-12] test)
- type: atomic (host-side slice; live-node leg container-gated)

### AS-13 (AS) — atomic
- goal: 
**Smallest honest closeable slice for AS-13:**

Build a minimal ROS2 stewie_executive package (new ros2_ws/src/stewie_executive/) that:

1. **Skeleton structure (ported from stewi
- acceptance: a [REQ:AS-13] python test asserts the row's host-side contract non-vacuously (the live-ROS runtime leg is gated).
- files: ros2_ws/src/stewie_executive/setup.py, ros2_ws/src/stewie_executive/stewie_executive/__init__.py, ros2_ws/src/stewie_executive/stewie_executive/node.py, ros2_ws/src/stewie_executive/test/test_import_stewie_executive.py, ros2_ws/test_container_tiers.py
- test_target: ros2_ws/test_container_tiers.py (extend existing AS-02/03/05/06 pattern with AS-13 container smoke test)
- type: atomic (host-side slice; live-node leg container-gated)

### AS-14 (AS) — atomic
- goal: 1. Extend ros2_bridge.py _StewieRcNode to publish diagnostic_msgs/DiagnosticArray on /diagnostics with DiagnosticStatus messages for: command_eligibility (using command_eligibility
- acceptance: a [REQ:AS-14] python test asserts the row's host-side contract non-vacuously (the live-ROS runtime leg is gated).
- files: stewie/bridge/ros2_bridge.py, stewie/bridge/test_ros2_bridge.py
- test_target: [REQ:AS-14] test in stewie/bridge/test_ros2_bridge.py (new or extended) that shows _StewieRcNode publishing /diagnostics with lifecycle, latency, command_eligibility, SAFE events, and correlation IDs, and that diagnostics_ledger.ledger_event() correctly processes them without logging secrets or truth-denied fields
- type: atomic (host-side slice; live-node leg container-gated)

### AS-15 (AS) — atomic
- goal: AS-15 requires a NASA-style TDD gate: test-first with [REQ:] markers, container smoke, deterministic fixtures, failure-mode tests, Power-of-10/static-analysis, and no capability cl
- acceptance: a [REQ:AS-15] python test asserts the row's host-side contract non-vacuously (the live-ROS runtime leg is gated).
- files: stewie/bridge/test_autonomy_contract.py, scripts/test_release_gate.py, ros2_ws/deploy/test_container_tiers.py, conftest.py
- test_target: scripts/test_release_gate.py (existing, already cites AS-15; expansion: add a test that documents the 3 deferred container tiers and 2 deferred detection capabilities as genuinely gated, verifying the gate never silently marks them complete)
- type: atomic (host-side slice; live-node leg container-gated)

### AS-18 (AS) — atomic
- goal: The typed evidence contract is implemented (I=D) and integrated into the estimator (X=D). Verification is partial (V=P) because:
1. No test cites [REQ:AS-18] to non-vacuously verif
- acceptance: a [REQ:AS-18] python test asserts the row's host-side contract non-vacuously (the live-ROS runtime leg is gated).
- files: dart/test_factors.py
- test_target: dart/test_factors.py (existing; add [REQ:AS-18] marker to test_shadow_yaw_allows_measured_heading_but_metric_shadow_is_guarded)
- type: atomic (host-side slice; live-node leg container-gated)

## Architectural-review remediation (2026-07-02) -- 9 rows

Briefs for the §7.13 rows atomizing the 2026-07-02 review. Each anchors to the review's cited file:line
(repo-relative). All buildable on archimedes (ROS/Gazebo/RViz/Chrono/GPU run here); the truly-gated leg
is named per row.

### DT-03 (P0) — atomic
- goal: make world-state mutation + WorldTransaction commit atomic (two-phase or compensating), no swallowed best-effort.
- acceptance: an injected world-log failure leaves the store and /world/transaction consistent (fault-injection test).
- files: stewie/server/routers/twin.py, stewie/server/routers/executive.py, stewie/server/world_state.py
- test_target: NEW stewie/server/test_world_transaction_atomic.py citing [REQ:DT-03]
### DT-04 (P0) — atomic
- goal: key the observed twin + world journal by (site, depth-source profile), not hard-coded haworth.
- acceptance: a second imported site accumulates + reloads its own observed twin independent of Haworth.
- files: stewie/server/state.py, stewie/server/world_state.py
- test_target: NEW stewie/server/test_twin_per_site.py citing [REQ:DT-04]
### SF-02 (P0) — atomic
- goal: bound every rover command (incl. mission-less GoTo) to a released mission or an explicit dev/bench teleop grant refused on LIVE/OPERATE.
- acceptance: mission-less GoTo on a LIVE/OPERATE profile is rejected; bench teleop needs the explicit audited grant.
- files: stewie/server/routers/rc.py, stewie/bridge/autonomy_contract.py
- test_target: extend stewie/server/test_rc.py (or NEW test_rc_command_authority.py) citing [REQ:SF-02]
### DT-05 (P1) — atomic
- goal: make GET /world the authoritative rich descriptor (geometry + observed/mutated enrichment + provenance + freshness), completeness declared.
- acceptance: /world after a mutation reflects observed enrichment or explicitly flags it absent.
- files: stewie/server/routers/world.py
- test_target: extend stewie/server/test_world.py citing [REQ:DT-05]
### FS-25 (P1) — atomic
- goal: carry product mode + runnable profile as first-class routeable/persisted/shareable state fields.
- acceptance: a shared link restores mode+profile; the §26.2 rail reflects them on every screen.
- files: stewie/server/web/assets/cockpit_state.js, stewie/server/web/assets/cockpit.js, stewie/server/index.html
- test_target: NEW stewie/server/test_mode_profile_state.py citing [REQ:FS-25]
### PM-17 (P1) — atomic
- goal: cockpit depth-source-profile selection + calibration freshness + source health, with Release/Execute blocking on stale/degraded/mismatched.
- acceptance: selecting each profile updates the perception path; a bad source blocks Release/Execute with a legible reason.
- files: stewie/server/web/assets/cockpit.js, stewie/bridge/autonomy_contract.py, stewie/server/routers/perception.py
- test_target: NEW stewie/server/test_sensor_profile_gate.py citing [REQ:PM-17]
### PO-15 (P1) — atomic
- goal: scheduled+monitored backup/restore with an RPO/retention policy + mission/runtime/profile admin surfaces.
- acceptance: a retention/RPO policy is declared + enforced by a scheduled job with a monitored last-success/age signal; admin actions audited.
- files: stewie/server/routers/admin_ops.py, stewie/server/routers/operators_admin.py
- test_target: NEW scripts/test_backup_retention_policy.py citing [REQ:PO-15]
### SE-02 (P1) — atomic
- goal: make the training operator-view access model explicit (authenticated OR documented capability-URL with unguessable ids + risk).
- acceptance: the security posture + a test state and enforce the chosen model.
- files: stewie/server/routers/session.py
- test_target: extend stewie/server/test_session.py citing [REQ:SE-02]
### FS-26 (P2) — atomic
- goal: the public /program board fits the mobile viewport (no horizontal overflow at 390 px).
- acceptance: a Playwright check asserts scrollWidth <= innerWidth at 390 px; wide content scrolls in its own container.
- files: stewie/server/web/program.html, stewie/server/web/assets/program_board.js
- test_target: NEW stewie/server/test_program_mobile.py citing [REQ:FS-26] (or a node/Playwright check)
