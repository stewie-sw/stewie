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

### FS-27 (P0) — atomic
- goal: surface ROS/Gazebo/RViz run evidence (lifecycle nodes, /clock, /tf, /joint_states, bridge freshness, RViz status/screenshots, bag links, container profile, no-truth-input) in Validate/System/Report.
- acceptance: with a ros2/gazebo profile selected, the panes show ROS/Gazebo/RViz status matching the profile and flag a mismatch.
- files: stewie/server/index.html, stewie/server/web/assets/cockpit.js, stewie/server/routers/health.py
- test_target: NEW stewie/server/test_ros_evidence_surface.py citing [REQ:FS-27]
### FS-28 (P0) — atomic
- goal: Release freezes+shows plan hash/runtime profile/namespace/sensor profile/AG-08 eligibility/SF-01 watchdog/sign-off; Execute shows bounded next command + acks/watchdog/link-ack/covariance/map-freshness/SAFE controls + refusal reason.
- acceptance: a released revision shows every field; an ineligible command is refused with its reason surfaced.
- files: stewie/server/web/assets/cockpit.js, stewie/server/index.html, stewie/server/routers/executive.py, stewie/server/routers/rc.py
- test_target: NEW stewie/server/test_release_execute_evidence.py citing [REQ:FS-28]

## Runtime spine + hazard-perception loop (2026-07-02) -- 9 rows

Briefs for §7.13 perception rows (PM-18/FS-29/PM-19) + §7.14 runtime-spine rows (RS-01..05,07; RS-06 is
hardware-gated). Buildable on archimedes; each anchors to a real existing file (NEW modules listed too).

### PM-18 (P1) — atomic
- goal: run the tested dart classifiers/mapper inside the stewie_perception + stewie_mapping ROS2 nodes (not skeletons).
- acceptance: a container run on a recorded bag yields detections + a map matching the host-side dart output.
- files: ros2_ws/src/stewie_perception/stewie_perception/node.py, ros2_ws/src/stewie_mapping/stewie_mapping/node.py, dart/rock_detect.py, dart/mapping.py
- test_target: NEW ros2_ws/test_perception_mapping_nodes.py citing [REQ:PM-18]
### FS-29 (P1) — atomic
- goal: cockpit live visual-hazard classifier panel (detections, confidence, accepted/rejected obstacles + reason, hazard overlay, replan consequence).
- acceptance: the panel renders real detections + accepted/rejected + a hazard-triggered-replan indicator.
- files: stewie/server/index.html, stewie/server/web/assets/cockpit.js, stewie/server/routers/perception.py
- test_target: NEW stewie/server/test_hazard_classifier_panel.py citing [REQ:FS-29]
### PM-19 (P1) — atomic
- goal: connect camera/depth -> classifier -> observed map -> costmap -> eligibility -> evidence as one host-side runtime path.
- acceptance: an injected hazard flows end-to-end to a measurably different plan + eligibility/evidence change.
- files: dart/hazard_map.py, lode/costmap_layers.py, lode/playthrough.py
- test_target: NEW stewie/eval/test_hazard_perception_loop.py citing [REQ:PM-19]
### RS-01 (P0) — atomic
- goal: typed runtime contracts (DepthObservation/VisualHazardObservation/ObservedMapUpdate/HazardMap/CostmapSnapshot/LocalizationState/TrajectoryCommand/CommandEligibility/WorldTransaction) as the only inter-module interface.
- acceptance: each stage boundary carries+validates its typed payload; a raw-dict/wrong-shape crossing is rejected.
- files: stewie/contracts/__init__.py, stewie/bridge/autonomy_contract.py
- test_target: NEW stewie/contracts/test_runtime_spine.py citing [REQ:RS-01]
### RS-02 (P0) — atomic
- goal: planner consumes the observed world (observed DEM/occupancy/rock-graph/changed-terrain/uncertainty + provenance), not just static DEM + keepouts.
- acceptance: an observed hazard absent from the static DEM measurably changes the route/costmap.
- files: lode/costmap_layers.py, lode/planner_routing.py, lode/map_uncertainty_route.py
- test_target: NEW lode/test_planner_observed_world.py citing [REQ:RS-02]
### RS-03 (P0) — atomic
- goal: receding-horizon nav loop (pose/belief -> local costmap -> global route if needed -> local trajectory/tick -> next bounded command -> replan/recover).
- acceptance: a per-tick loop drives to goal, emits one bounded command/tick, recovers from an injected block.
- files: lode/planner_routing.py, dart/drive.py, dart/relocalization.py
- test_target: NEW stewie/runtime/test_nav_loop.py citing [REQ:RS-03]
### RS-04 (P0) — epic
- goal: the ros2_replay/desktop_sil deterministic end-to-end fixture: replay->classify->observed map->plan->issue/refuse bounded command->world transaction->evidence bundle.
- acceptance: runs deterministically; each RS-01 payload + the evidence bundle asserted; seeded hazard reroutes, seeded ineligibility refuses.
- files: stewie/server/world_state.py, lode/costmap_layers.py, dart/hazard_map.py, stewie/bridge/autonomy_contract.py
- test_target: NEW stewie/runtime/test_replay_loop.py citing [REQ:RS-04]
### RS-05 (P1) — atomic
- goal: Gazebo as the live sensor producer driving the RS loop; RViz shows robot/cloud/map/costmap/path/command.
- acceptance: the loop runs on Gazebo-produced sensors in-container; RViz displays the live evidence; inputs truth-denied.
- files: ros2_ws/src/stewie_bringup/config/gz_bridge.yaml, deploy/ros2/Dockerfile.gazebo, ros2_ws/src/stewie_rviz/rviz/mission.rviz
- test_target: NEW ros2_ws/test_gazebo_loop.py citing [REQ:RS-05]
### RS-07 (P1) — atomic
- goal: primary command cockpit + a SECONDARY read-only viz that is two-fold (PLAN column = sim-of-record route/forecast/Godot + prior/forecast/edited twin provenance; ACTUAL column = live ROS2 observed map/cloud/pose/executed cmd + observed provenance), co-registered in the site frame on one run/time state.
- acceptance: the two-column layout renders PLAN + ACTUAL co-registered on the same run/time; secondary emits no command.
- files: stewie/server/index.html, stewie/server/web/assets/cockpit_state.js, deploy/nginx.conf
- test_target: NEW stewie/server/test_multiscreen_display.py citing [REQ:RS-07]
### RS-08 (P1) — atomic
- goal: the plan-vs-actual DIVERGENCE surface (executed-vs-planned trajectory, observed-vs-forecast hazard/DEM, pose-vs-truth covariance) with a follow-live/scrub-plan time offset; threshold crossing drives the replan indicator; informs only, never commands.
- acceptance: a fixture where ACTUAL departs from PLAN yields a measured divergence surface + a threshold replan indicator, co-registered + read-only.
- files: dart/relocalization.py, lode/costmap_layers.py, stewie/server/web/assets/cockpit_state.js
- test_target: NEW stewie/eval/test_plan_actual_divergence.py citing [REQ:RS-08]

## Repository maintainability + continuity governance (2026-07-02 bloat audit) -- 5 rows

Briefs for §7.15 MT-01..05 (Phase-3 runtime contracts/ROS adapters already tracked as RS-01/PM-18/RS-04).

### MT-01 (P1) — atomic
- goal: CI rejects a newly-tracked large binary unless allowlisted; externalize samples/lunar_dem/*.rf32 to checksum manifest + fetch script, keep one tiny real-derived smoke fixture.
- acceptance: a large tracked binary reds CI; the DEM resolves via manifest+fetch; suite green on the tiny fixture.
- files: scripts/gen_release_manifest.py, samples/lunar_dem, stewie/specs/config.py
- test_target: NEW scripts/test_large_file_policy.py citing [REQ:MT-01]
### MT-02 (P2) — atomic
- goal: a safe documented cleaner for local generated/vendor bloat; generated outputs steered to one ignored artifact root; never touches tracked files.
- acceptance: dry-run lists only ignored/generated paths; removal never touches a git-tracked file (asserted vs git ls-files).
- files: scripts/gen_status.py, .gitignore, deploy/DEPLOY.md
- test_target: NEW scripts/test_workspace_cleanup.py citing [REQ:MT-02]
### MT-03 (P1) — epic
- goal: continue the cockpit strangler split (api_client / route-state / profile+sensor rail / command rail / diagnostics rail / one pane) into pure node-tested modules; HTML-sink allowlist gate.
- acceptance: each extraction is a pure node:test module, cockpit.js LOC drops, the HTML-sink gate reds on a new unlisted sink, ui-smoke green.
- files: stewie/server/web/assets/cockpit.js, stewie/server/web/assets/cockpit_state.js, stewie/server/index.html
- test_target: NEW stewie/server/web/assets/html_sink_gate.test.js + scripts/test_html_sink_allowlist.py citing [REQ:MT-03]
### MT-04 (P1) — atomic
- goal: split optional extras into core/perception/planning/server/ros/dev profiles; default install lean; heavy CV/GIS/benchmark deps out of minimal runtime.
- acceptance: a minimal-profile install boots stewie-serve + /healthz without heavy extras; each profile resolves from the hashed lock.
- files: pyproject.toml, scripts/fresh_install_smoke.py, requirements-dev.lock
- test_target: NEW scripts/test_dependency_profiles.py citing [REQ:MT-04]
### MT-05 (P1) — atomic
- goal: a continuity-governance release gate reporting tracked-payload size + large-file diff + HTML-sink count + test-tier status; ADRs per boundary; generated-artifact manifest.
- acceptance: gate emits all four metrics and reds on a new large tracked file or new unlisted HTML sink; ADR set + artifact manifest checked in.
- files: scripts/release_gate.py, scripts/gen_release_manifest.py, docs/repo_bloat_maintainability_audit_2026-07-02.md
- test_target: NEW scripts/test_continuity_gate.py citing [REQ:MT-05]

## Backend production-grade review remediation (2026-07-02) -- 13 rows (§7.16 BP-01..13)

Briefs for the backend production review findings. Existing-row extensions cross-ref SE-01/SE-02/AG-06/FS-19.

### BP-01 (P0) — atomic
- goal: SE-01 8-domain security-audit evidence manifest + real SBOM CVE scan + backup/restore drill; gate fails on any missing/undated/env-less domain.
- acceptance: python scripts/test_se01_audit_gate.py fails on a missing domain, passes only with all eight dated env-identified records.
- files: scripts/security_audit.py, scripts/test_se01_audit_gate.py, scripts/scan_artifacts.py
- test_target: scripts/test_se01_audit_gate.py citing [REQ:SE-01]
### BP-02 (P1) — atomic
- goal: the production backend image enters the public-bind TLS guard (guarded stewie-serve path or ASGI lifespan enforcement), not a raw uvicorn server:app.
- acceptance: a deploy test inspects the image command and fails if production starts server:app public without an equivalent guard.
- files: deploy/Dockerfile.backend, stewie/server/server.py, stewie/server/test_deploy_hardening.py
- test_target: stewie/server/test_deploy_hardening.py citing [REQ:BP-02]
### BP-03 (P1) — atomic
- goal: production requires STEWIE_SESSION_SECRET separate from STEWIE_API_KEY; fail-loud when TLS-terminated + secret absent; separate rotation semantics.
- acceptance: a deploy-hardening test fails when production omits the secret; auth tests prove API-key vs session-secret rotation differ.
- files: stewie/server/auth.py, deploy/compose.yml, stewie/server/test_auth.py
- test_target: stewie/server/test_session_secret.py citing [REQ:BP-03]
### BP-04 (P1) — atomic
- goal: TLS-terminated production requires explicit STEWIE_ALLOWED_OPERATORS + STEWIE_DIRECTORS (or bootstrap director), disables default-allowlist/raw-key trust; /healthz+/config DEGRADED on defaults.
- acceptance: TLS-terminated with no explicit allowlist/directors fails closed (403 or actionable startup error).
- files: stewie/server/auth.py, stewie/server/routers/auth.py, stewie/server/test_auth.py
- test_target: stewie/server/test_production_identity_strict.py citing [REQ:BP-04]
### BP-05 (P1) — atomic
- goal: live-namespace artifact deletion is director-only (missions/structures/objects); self-delete only for sandbox; delete audit names the namespace.
- acceptance: operator delete own live -> 403; own sandbox -> ok; director delete live -> ok + audited namespace.
- files: stewie/server/objects.py, stewie/server/routers/missions.py, stewie/server/routers/structures.py
- test_target: stewie/server/test_live_delete_policy.py citing [REQ:BP-05]
### BP-06 (P1) — atomic
- goal: training operator-view access model (authenticated OR signed expiring capability URL with TTL enforced on get()); documented.
- acceptance: authenticated -> anon GET 401/403; capability -> unsigned 401/403, signed unexpired ok, expired fails.
- files: stewie/server/routers/session.py, stewie/server/session.py, stewie/server/test_session.py
- test_target: stewie/server/test_session.py citing [REQ:SE-02]
### BP-07 (P2) — atomic
- goal: critical ops (director admin, live mission mutation, release/execute, rc/command, security settings) refuse 503 on a degraded audit ledger; non-critical best-effort.
- acceptance: injected audit-write failure makes /admin/operators/create, live-mission delete, release/execute, /rc/command refuse/hard-degrade.
- files: stewie/server/services.py, stewie/server/routers/admin.py, stewie/server/routers/rc.py
- test_target: stewie/server/test_audit_critical.py citing [REQ:BP-07]
### BP-08 (P2) — epic
- goal: full FS-19 observability ledger -- typed event schema + per-contract-route decorator (correlation id/actor/route/result/latency/error/hashes/mission-site-body-time) + redaction; one assertion per event class.
- acceptance: [REQ:FS-19] fails if any required event class lacks full-field coverage or redaction misses secrets/truth-denied fields.
- files: stewie/server/services.py, stewie/server/server.py, stewie/server/test_observability_ledger.py
- test_target: stewie/server/test_observability_ledger.py citing [REQ:FS-19]
### BP-09 (P2) — atomic
- goal: single-worker backend invariant (STEWIE_SINGLE_PROCESS_STATE=1) documented + a deploy test fails if production workers>1 without shared state.
- acceptance: a test checks the production command + the single-process invariant.
- files: deploy/Dockerfile.backend, stewie/server/test_deploy_hardening.py, deploy/compose.yml
- test_target: stewie/server/test_deploy_hardening.py citing [REQ:BP-09]
### BP-10 (P2) — atomic
- goal: prune_reports removes old nested render_* dirs (prefix-matched, resolved paths asserted under reports_dir); no arbitrary recursive delete.
- acceptance: the prune test adds an old render_* dir and proves it is removed while unrelated dirs survive.
- files: stewie/server/services.py, stewie/specs/config.py, stewie/server/test_report_prune.py
- test_target: stewie/server/test_report_prune.py citing [REQ:BP-10]
### BP-11 (P2) — atomic
- goal: optimistic concurrency for live object stores -- updated_at/revision/sha256 + If-Match/base_revision + 409 on stale save.
- acceptance: two clients load rev N; first save N+1; second save with N -> 409.
- files: stewie/server/objects.py, stewie/server/routers/missions.py, stewie/server/test_object_concurrency.py
- test_target: stewie/server/test_object_concurrency.py citing [REQ:BP-11]
### BP-12 (P2) — atomic
- goal: the publish workflow installs from requirements-dev.lock --require-hashes + -e . --no-deps, matching CI (supply-chain parity).
- acceptance: a workflow-lint test asserts the publish workflow uses requirements-dev.lock with --require-hashes.
- files: .github/workflows/publish-stewie.yml, .github/workflows/ci.yml, scripts/test_ci_tiers.py
- test_target: scripts/test_publish_workflow_lock.py citing [REQ:BP-12]
### BP-13 (P3) — atomic
- goal: browser login omits the bearer token in JSON (returns role/operator/ttl/must_set_password); token only on an explicit automation path.
- acceptance: browser login response omits token; automation path includes it only when explicitly requested + tested.
- files: stewie/server/routers/auth.py, stewie/server/test_auth.py, stewie/server/auth.py
- test_target: stewie/server/test_login_token_split.py citing [REQ:BP-13]

## Frontend + lunar-mission-systems review remediation (2026-07-02) -- 15 rows (§7.17 FR-01..15)

Briefs for the two 2026-07-02 reviews. Extensions cross-ref FS-25/PM-17/FS-28/PO-15/SE-02/FS-18/FS-26/PM-19/RS-04/TW-05/RS-02/ML-06/FS-19.

### FR-01 (P1) — atomic
- goal: product mode + runnable profile in the cockpit route/state contract + shell + Release/Execute/eligibility gating.
- acceptance: mode/profile in the state contract + shell-visible; a mismatched-profile Release/Execute is refused/degraded.
- files: stewie/server/web/assets/cockpit_state.js, stewie/server/web/assets/cockpit.js, stewie/server/routers/executive.py
- test_target: stewie/server/test_product_mode_profile.py citing [REQ:FS-25]
### FR-02 (P1) — atomic
- goal: depth-source profile selector + health/freshness; Release/Execute refuse/degrade on stale/mismatched/sim-when-live.
- acceptance: selector shows health/freshness; a stale/mismatched profile blocks Release/Execute with a reason.
- files: stewie/server/web/assets/cockpit.js, stewie/server/index.html, stewie/server/routers/perception.py
- test_target: stewie/server/test_sensor_profile_ui.py citing [REQ:PM-17]
### FR-03 (P1) — atomic
- goal: full Release/Execute authority-evidence field set.
- acceptance: released revision shows every field; an ineligible command surfaces its refusal reason.
- files: stewie/server/web/assets/cockpit.js, stewie/server/routers/executive.py, stewie/server/routers/rc.py
- test_target: stewie/server/test_authority_evidence_panel.py citing [REQ:FS-28]
### FR-04 (P1) — atomic
- goal: admin as governed operations (policy + audit), not loose buttons.
- acceptance: each admin action shows its policy + writes an audit event; degraded-governance visible.
- files: stewie/server/web/assets/cockpit.js, stewie/server/routers/admin.py, stewie/server/services.py
- test_target: stewie/server/test_governed_admin_ui.py citing [REQ:PO-15]
### FR-05 (P1) — atomic
- goal: training operator link shows scope/expiry/actions/signed/revocation; signed expiring capability URL or authenticated.
- acceptance: UI labels scope/expiry/actions/revocation; an expired/unsigned link is refused.
- files: stewie/server/routers/session.py, stewie/server/session.py, stewie/server/web/assets/cockpit.js
- test_target: stewie/server/test_operator_link_model.py citing [REQ:SE-02]
### FR-06 (P1) — atomic
- goal: a route_pane_registry.js source of truth + a pytest checking route coverage + a node test loading each adapter fixture (render/error/provenance).
- acceptance: a route-backed pane missing from the registry or missing an evidence/mobile fixture fails the gate.
- files: stewie/server/web/assets/route_pane_registry.js, stewie/server/web/assets/adapters.js, stewie/server/test_adapter_contract_parity.py
- test_target: stewie/server/test_route_pane_registry.py citing [REQ:FS-18]
### FR-07 (P2) — atomic
- goal: reconcile stale PRD/FANOUT provenance text with the shipped provenance labels.
- acceptance: a doc-coherence check finds no PRD/FANOUT claim contradicted by the shipped provenance labeling.
- files: PRD.md, FANOUT_SPECS.md, stewie/server/web/assets/cockpit.js
- test_target: scripts/test_provenance_doc_coherence.py citing [REQ:FR-07]
### FR-08 (P2) — atomic
- goal: the ui-smoke 390px no-overflow check covers all cockpit panes, not only /program.
- acceptance: any pane overflowing the phone viewport reds the ui-smoke tier.
- files: scripts/ui_smoke.mjs, stewie/server/index.html, stewie/server/test_program_mobile.py
- test_target: stewie/server/test_cockpit_mobile_fit.py citing [REQ:FS-26]
### FR-09 (P1) — epic
- goal: prove the live hazard-perception->world->planner->eligibility->cockpit loop end-to-end with provenance + refusal/approval evidence.
- acceptance: the mission-critical loop demonstrated end-to-end with operator evidence.
- files: stewie/runtime/replay_loop.py, stewie/eval/test_hazard_perception_loop.py, stewie/server/routers/world.py
- test_target: stewie/eval/test_live_perception_loop_e2e.py citing [REQ:PM-19]
### FR-10 (P1) — epic
- goal: unified typed layer-manifest world contract (id/type/CRS/bounds/res/source/provenance/freshness/uncertainty/validity/txn/consumer-eligibility); planner consumes the same manifest.
- acceptance: material/traversability/observed/uncertainty layers discoverable+typed with consumer eligibility; planner builds costmap from the manifest.
- files: stewie/contracts/__init__.py, stewie/server/routers/world.py, lode/costmap_layers.py
- test_target: stewie/server/test_world_layer_manifest.py citing [REQ:TW-05]
### FR-11 (P1) — atomic
- goal: observed-world-to-planner end-to-end acceptance gate (DEM+route -> inject hazard -> world txn -> rebuild costmap -> route changes/refuses/justified -> cockpit+release evidence).
- acceptance: the end-to-end gate passes on real terrain.
- files: stewie/server/test_planner_observed_world.py, stewie/server/routers/nav.py, stewie/server/world_state.py
- test_target: stewie/server/test_observed_world_planner_e2e.py citing [REQ:RS-02]
### FR-12 (P1) — atomic
- goal: precise GIS/ArcGIS product language + an ArcGIS adapter boundary + per-layer display-eligibility vs planning-eligibility fields.
- acceptance: precise labels; ArcGIS boundary + per-shape fixtures exist; a displayable-not-planning-valid layer is not treated as planning-valid.
- files: stewie/server/index.html, stewie/server/gis_layers.py, stewie/server/routers/layers.py
- test_target: stewie/server/test_gis_platform_claims.py citing [REQ:FR-12]
### FR-13 (P1) — atomic
- goal: a RegolithVolumeEstimate contract (before/after source, change mask, cut/fill, uncertainty, drum cross-check, conservation residual, confidence, acceptance, linked txn); LEAP emits it; cockpit/report render it.
- acceptance: a before/after delta yields a conserved uncertainty-carrying volume estimate cross-checked vs the drum sensor, linked to a world txn.
- files: leap/siteplan.py, leap/structures.py, stewie/contracts/__init__.py
- test_target: leap/test_regolith_volume_estimate.py citing [REQ:ML-06]
### FR-14 (P2) — atomic
- goal: label navigation preview/rehearsal unless the runnable profile proves a live+authorized autonomy binary.
- acceptance: nav surfaces labeled preview/rehearsal, flipping to live only on a live+authorized autonomy attestation.
- files: stewie/server/web/assets/cockpit.js, stewie/server/routers/nav.py, stewie/server/index.html
- test_target: stewie/server/test_nav_preview_labeling.py citing [REQ:FR-14]
### FR-15 (P2) — atomic
- goal: observability records link source assets/freshness/provenance/operator/product-mode/runnable-profile/transaction-id (mission evidence).
- acceptance: [REQ:FS-19] fails if a required record lacks the source-asset/freshness/provenance/mode/profile/transaction linkage.
- files: stewie/server/services.py, stewie/server/server.py, stewie/server/test_observability_ledger.py
- test_target: stewie/server/test_mission_evidence_ledger.py citing [REQ:FS-19]
### FR-16 (P1) — atomic
- goal: fixed mobile status/action bar -- move #healthchip/#alertbtn/#wsbadge/#whoami out of the scrolling #viewtabs into a non-scrolling top bar.
- acceptance: at 320/360/390/430px health/alerts/workspace/account are visible in the first viewport, no body horizontal overflow.
- files: stewie/server/index.html, stewie/server/web/assets/cockpit.js
- test_target: stewie/server/test_fr16_mobile_topbar.py citing [REQ:FR-16]
### FR-17 (P1) — atomic
- goal: More/profile menus render as position:fixed viewport-clamped mobile sheets (were absolutely positioned in tab-strip children, opened offscreen).
- acceptance: opening #moremenu/#profmenu at 320/390/430/768 never produces an offscreen menu rect.
- files: stewie/server/index.html, stewie/server/web/assets/cockpit.js
- test_target: stewie/server/test_fr17_mobile_menu_sheets.py citing [REQ:FR-17]
### FR-18 (P1) — atomic
- goal: /program mobile touch ergonomics -- .fbtn/#program-search/.rowchip to min-height 44px, full-width search.
- acceptance: at phone widths every /program filter/search/row control >=44px, enforced by a static + runtime check.
- files: stewie/server/web/program.html, stewie/server/web/assets/program_board.js
- test_target: stewie/server/test_fr18_program_touch_targets.py citing [REQ:FR-18]
### FR-19 (P1) — atomic
- goal: Plan ToolBox is a viewport-contained mobile sheet with a 44px keep-out radius control (#edittoolbar/#edittools/#koradius).
- acceptance: at 320/390/430/768 every visible #edittoolbar button/input is inside the viewport and >=44px incl the keep-out radius.
- files: stewie/server/index.html, stewie/server/test_fr19_toolbox_mobile.py, scripts/fr19_toolbox_probe.py
- test_target: stewie/server/test_fr19_toolbox_mobile.py citing [REQ:FR-19]
### FR-20 (P2) — atomic
- goal: mobile command-surface smoke gate across 320/360/390/430/768 (overflow + first-viewport chrome + menus in-viewport + ToolBox contained + all controls >=44x44).
- acceptance: the gate runs the five viewports and fails on any violation.
- files: stewie/server/test_fr20_mobile_smoke.py, stewie/server/index.html, stewie/server/web/program.html
- test_target: stewie/server/test_fr20_mobile_smoke.py citing [REQ:FR-20]
### FR-21 (P2) — atomic
- goal: mobile IA control-plane split (status bar / workflow rail / subnav / drawer / account sheet).
- acceptance: the mobile shell separates the stable status/action plane from the scrollable workflow rail (verified via FR-16 + FR-20).
- files: stewie/server/index.html, stewie/server/web/assets/cockpit.js
- test_target: stewie/server/test_fr21_mobile_ia.py citing [REQ:FR-21]

## Bottom-up rover autonomy architecture audit (2026-07-02) -- 11 rows (§7.18 BA-01..11)

### BA-01 (P0) — atomic
- goal: fix/validate the gz_bridge point-cloud topic vs the gpu_lidar publisher (gpu_lidar <topic>X</topic> -> PointCloudPacked on X/points; the bridge is actually correct) + a host-side consistency test asserting every bridged sensor topic has a matching xacro/SDF publisher.
- files: ros2_ws/src/stewie_bringup/config/gz_bridge.yaml, ros2_ws/src/stewie_description/urdf/ipex.gazebo.xacro
- test_target: extend ros2_ws/test_gz_bridge.py with a `[REQ:BA-01]` topic-publisher-consistency test

### BA-02 (P0) — atomic
- goal: add stereo camera_info + the missing rear/side/drum image topics to the Gazebo bridge + the autonomy contract; assert each image topic has a paired camera_info.
- files: ros2_ws/src/stewie_bringup/config/gz_bridge.yaml, stewie/bridge/autonomy_contract.py
- test_target: extend ros2_ws/test_gz_bridge.py (or NEW ros2_ws/test_camera_info.py) citing [REQ:BA-02]

### BA-03 (P0) — epic
- goal: add ros2_control.xacro transmissions + controllers.yaml so Gazebo AND live share one controller_manager actuation interface.
- files: ros2_ws/src/stewie_description/urdf/ipex.gazebo.xacro, ros2_ws/src/stewie_bringup/config/gz_bridge.yaml
- test_target: NEW ros2_ws/test_ros2_control.py citing [REQ:BA-03] (loads the controller config)

### BA-04 (P0) — epic
- goal: generate a Gazebo heightfield world from a real lunar DEM (Haworth) instead of the flat regolith plane.
- files: ros2_ws/src/stewie_description/worlds/stewie_lunar.sdf, stewie/terrain/site_dem.py
- test_target: NEW scripts/test_dem_to_gazebo_heightfield.py citing [REQ:BA-04] (validates the heightfield vs the DEM)

### BA-05 (P0) — epic
- goal: typed CRS transform chain body_crs->site_enu->map->odom->base_link->sensors + a Godot Y-up<->ROS REP-103 converter, validated against control points.
- files: ipex-terrain-sim-spec.md, stewie/server/test_gi02_body_crs.py
- test_target: NEW stewie/geospatial/test_crs_transform.py citing [REQ:BA-05] (control-point round-trips)

### BA-06 (P1) — epic
- goal: interop converters (xacro_to_sdf, urdf_to_godot_scene, dem_to_godot_heightfield, gridmap<->geotiff, rosbag<->world_transactions) with round-trip fixtures.
- files: lode/gis_export.py, dart/world_model_layers.py
- test_target: NEW scripts/test_interop_converters.py citing [REQ:BA-06] (bounds/georef/event-count preserved)

### BA-07 (P1) — atomic
- goal: Phase-0 running-sim smoke gate: one launch brings up Gazebo+RSP+controllers+bridge+RViz+bag; assert contract topics publish, /cmd_vel moves the rover, no estimator subscribes /stewie/truth/*.
- files: ros2_ws/test_gz_sim_artifacts.py, ros2_ws/src/stewie_bringup/config/gz_bridge.yaml
- test_target: extend ros2_ws/test_gz_sim_artifacts.py with a container `[REQ:BA-07]` smoke assertion

### BA-08 (P1) — epic
- goal: stewie_godot_bridge node subscribes ROS state (tf/joints/odom/path/costmap/map/rocks/factors/decision) and renders live in Godot, publishing NO commands (source_class=sim_render).
- files: stewie/godot/sidecar.gd, stewie/bridge/autonomy_contract.py
- test_target: NEW ros2_ws/test_godot_bridge.py citing [REQ:BA-08] (subscription set + no command publishers)

### BA-09 (P1) — epic
- goal: promote the DART/LODE perception/mapping/costmap/planner logic into real ROS 2 nodes (skeletons -> real), reusing the tested Python cores + adding running-sim tests.
- files: ros2_ws/src/stewie_perception/stewie_perception/node.py, dart/hazard_map.py, lode/costmap_layers.py
- test_target: NEW ros2_ws/test_perception_node.py citing [REQ:BA-09] (perception->observed-map->costmap->plan chain)

### BA-10 (P2) — gated
- goal: live robot / HIL through the same ROS interfaces (ros2_control hardware interface + drivers + calibration + time sync + bounded command namespace + safety watchdog); GATED on physical hardware.
- files: ros2_ws/src/stewie_perception/stewie_perception/node.py, ros2_ws/src/stewie_bringup/config/gz_bridge.yaml
- test_target: NEW ros2_ws/test_hardware_interface.py citing [REQ:BA-10] (bench_robot profile parity; hardware-gated)

### BA-11 (P1) — epic
- goal: mission-package import/export in ArcGIS-compatible open-geospatial formats (GeoTIFF/COG, GeoJSON/FlatGeobuf, STAC metadata, manifest + authority tuple) with round-trip preservation.
- files: lode/gis_export.py, stewie/server/map_layers.py
- test_target: NEW stewie/test_mission_package_io.py citing [REQ:BA-11] (export->import bounds/resolution/CRS + authority tuple preserved)

### BD-04 (P0) — atomic
- goal: break the inverted `bodies→physics` edge; raw `BodyProfile`/`RegolithProfile` records; `params_for_body` becomes a compat wrapper.
- acceptance: `stewie.specs.bodies` imports no `stewie.physics`; built-in body values unchanged; microgravity fail-closed stays; import-boundary test proves the break.
- files: stewie/specs/bodies.py, stewie/physics/terramechanics.py, stewie/server/bodies.json
- test_target: NEW stewie/specs/test_body_profiles.py citing [REQ:BD-04]

### PX-04 (P0) — atomic
- goal: `PhysicsBackend` protocol + `Tier2NumpyBackend` over existing terramechanics/forge.bearing/planner-context.
- acceptance: Moon/BP-1 /plan byte-compatible or diff-reviewed; verdict reports authority_class + conserves_mass; no client mutates terrain.
- files: stewie/physics/terramechanics.py, forge/bearing.py, lode/planner_model.py, stewie/server/routers/plan.py
- test_target: NEW stewie/physics/test_physics_backend.py citing [REQ:PX-04]

### PX-05 (P0) — atomic
- goal: lock the production physics import boundary; correct the stale docs claim; relocate/mark the 3 coupled test files.
- acceptance: executable test proves production stewie/physics imports no dart/leap; forge unit gate needs no dart/leap.
- files: stewie/physics/test_constrained_skill.py, stewie/physics/test_drum_sensing.py, stewie/physics/test_slam04_fk_authority.py
- test_target: NEW scripts/test_import_boundaries.py citing [REQ:PX-05]

### AP-01 (P0) — atomic
- goal: move composing runtime/router code that imports dart/leap out of the future stewie-core boundary into the app layer.
- acceptance: core subset imports no dart/lode/leap; route URLs + RS-04 behavior unchanged.
- files: stewie/runtime/nav_loop.py, stewie/runtime/replay_loop.py, stewie/server/routers/evidence.py, stewie/server/routers/siteplan.py, stewie/server/server.py
- test_target: NEW scripts/test_core_import_boundaries.py citing [REQ:AP-01]

### PO-16 (P0) — atomic
- goal: uv/hatch workspace skeleton after BD/PX/AP boundaries pass; encode the import DAG; public targets = bodies+forge only.
- acceptance: editable install + current suite green; import-boundary policy encoded; root stays monorepo.
- files: pyproject.toml, scripts/fanout_plan.py
- test_target: NEW scripts/test_workspace_packaging.py citing [REQ:PO-16]

### PO-17 (P0) — atomic
- goal: extract stewie-bodies as the first public/citable package from the dependency-neutral registry.
- acceptance: standalone import/build; profiles round-trip; Moon/Mars/Earth golden gravity tests pass; no fabricated fields.
- files: stewie/specs/bodies.py, stewie/server/bodies.json, pyproject.toml
- test_target: NEW packages/stewie-bodies/tests/test_body_profiles.py citing [REQ:PO-17]

### PO-18 (P0) — atomic
- goal: extract stewie-forge from pure geotech/terramechanics + PhysicsBackend; depends only on stewie-bodies + numeric.
- acceptance: standalone build; concept-first API; Chrono optional/advisory; bearing/sinkage/slip examples pass.
- files: forge/bearing.py, stewie/physics/terramechanics.py, pyproject.toml
- test_target: NEW packages/stewie-forge/tests/test_forge_public_api.py citing [REQ:PO-18]

### DE-01 (P0) — atomic
- goal: Demo 001 — one IPEx-dig vertical slice proving the platform loop end-to-end from existing code.
- acceptance: body/profile + backend → plan → conserved execution/twin txn → RegolithVolumeEstimate → report/evidence, deterministic, no synthetic values.
- files: lode/mission_planner.py, stewie/runtime/replay_loop.py, stewie/server/routers/siteplan.py, stewie/twin/terrain_memory.py
- test_target: NEW tests/demo/test_demo_001_ipex_dig.py citing [REQ:DE-01]

### MG-04 (P0) — atomic
- goal: make the /program board mobile-friendly (44px targets, single-column, no overflow, collapsible filter/inspect).
- acceptance: Playwright at 320/360/390/430 px — no horizontal overflow, touch targets >=44px.
- files: stewie/server/web/program.html, stewie/server/web/assets/program_board.js
- test_target: NEW stewie/server/test_mg04_program_mobile.py citing [REQ:MG-04]

### AC-01 (P0) — atomic
- goal: platform-restructure backlog row AC-01 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/server/server.py
- test_target: NEW frontend/api/test_route_coverage.test.ts citing [REQ:AC-01]

### AC-02 (P0) — atomic
- goal: platform-restructure backlog row AC-02 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/server/server.py
- test_target: NEW frontend/api/test_route_coverage.test.ts citing [REQ:AC-02]

### RF-01 (P0) — atomic
- goal: platform-restructure backlog row RF-01 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/server/web/assets/cockpit_state.js
- test_target: NEW frontend/src/app/test_shell.test.tsx citing [REQ:RF-01]

### RF-02 (P0) — atomic
- goal: platform-restructure backlog row RF-02 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/server/web/assets/cockpit_state.js
- test_target: NEW frontend/src/app/test_shell.test.tsx citing [REQ:RF-02]

### RF-03 (P1) — atomic
- goal: platform-restructure backlog row RF-03 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/server/web/assets/cockpit_state.js
- test_target: NEW frontend/src/app/test_shell.test.tsx citing [REQ:RF-03]

### GL-01 (P0) — atomic
- goal: platform-restructure backlog row GL-01 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/server/web/assets/cockpit.js
- test_target: NEW frontend/src/map/test_map.test.tsx citing [REQ:GL-01]

### GL-02 (P1) — atomic
- goal: platform-restructure backlog row GL-02 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/server/web/assets/cockpit.js
- test_target: NEW frontend/src/map/test_map.test.tsx citing [REQ:GL-02]

### DW-01 (P1) — atomic
- goal: platform-restructure backlog row DW-01 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/contracts/__init__.py
- test_target: NEW frontend/src/data/duckdb/test_query.test.tsx citing [REQ:DW-01]

### DW-02 (P2) — atomic
- goal: platform-restructure backlog row DW-02 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/contracts/__init__.py
- test_target: NEW frontend/src/data/duckdb/test_query.test.tsx citing [REQ:DW-02]

### PX-01 (P0) — atomic
- goal: platform-restructure backlog row PX-01 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/physics/terramechanics.py
- test_target: NEW stewie/physics/test_physics_backend.py citing [REQ:PX-01]

### PX-02 (P1) — atomic
- goal: platform-restructure backlog row PX-02 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/physics/terramechanics.py
- test_target: NEW stewie/physics/test_physics_backend.py citing [REQ:PX-02]

### PX-03 (P2) — atomic
- goal: platform-restructure backlog row PX-03 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/physics/terramechanics.py
- test_target: NEW stewie/physics/test_physics_backend.py citing [REQ:PX-03]

### BD-01 (P0) — atomic
- goal: platform-restructure backlog row BD-01 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/specs/bodies.py
- test_target: NEW stewie/specs/test_body_profiles.py citing [REQ:BD-01]

### BD-02 (P1) — atomic
- goal: platform-restructure backlog row BD-02 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/specs/bodies.py
- test_target: NEW stewie/specs/test_body_profiles.py citing [REQ:BD-02]

### BD-03 (P1) — atomic
- goal: platform-restructure backlog row BD-03 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/specs/bodies.py
- test_target: NEW stewie/specs/test_body_profiles.py citing [REQ:BD-03]

### TU-01 (P1) — atomic
- goal: platform-restructure backlog row TU-01 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/server/index.html
- test_target: NEW desktop/test_tauri_sidecar.test.ts citing [REQ:TU-01]

### MG-01 (P0) — atomic
- goal: platform-restructure backlog row MG-01 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/server/web/program.html
- test_target: NEW stewie/server/test_mg_migration.py citing [REQ:MG-01]

### MG-02 (P0) — atomic
- goal: platform-restructure backlog row MG-02 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/server/web/program.html
- test_target: NEW stewie/server/test_mg_migration.py citing [REQ:MG-02]

### MG-03 (P2) — atomic
- goal: platform-restructure backlog row MG-03 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/server/web/program.html
- test_target: NEW stewie/server/test_mg_migration.py citing [REQ:MG-03]

### BR-01 (P2) — atomic
- goal: platform-restructure backlog row BR-01 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/twin/versioned.py
- test_target: NEW stewie/twin/test_world_branches.py citing [REQ:BR-01]

### CF-01 (P2) — atomic
- goal: platform-restructure backlog row CF-01 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/contracts/__init__.py
- test_target: NEW lode/test_capability_fleet.py citing [REQ:CF-01]

### PG-01 (P2) — atomic
- goal: platform-restructure backlog row PG-01 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/twin/terrain_memory.py
- test_target: NEW stewie/twin/test_postgis_projection.py citing [REQ:PG-01]

### MI-01 (P3) — atomic
- goal: platform-restructure backlog row MI-01 (see PRD §7.A/§7.B + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/server/index.html
- test_target: NEW frontend/test_multiengine_ide.test.tsx citing [REQ:MI-01]

### TW-11 (P2) — atomic
- goal: platform backlog row TW-11 (PRD §7 + docs/prd_reorg_spec_2026-07-03.md).
- files: stewie/twin/terrain_memory.py
- test_target: NEW test citing [REQ:TW-11]

### EG-01 (P0) — atomic
- goal: platform backlog row EG-01 (PRD §7 + §29/§30 governance+planning specs).
- files: stewie/contracts/__init__.py
- test_target: NEW test citing [REQ:EG-01]

### EG-02 (P0) — atomic
- goal: platform backlog row EG-02 (PRD §7 + §29/§30 governance+planning specs).
- files: stewie/contracts/__init__.py
- test_target: NEW test citing [REQ:EG-02]

### EG-03 (P0) — atomic
- goal: platform backlog row EG-03 (PRD §7 + §29/§30 governance+planning specs).
- files: stewie/contracts/__init__.py
- test_target: NEW test citing [REQ:EG-03]

### EG-04 (P1) — atomic
- goal: platform backlog row EG-04 (PRD §7 + §29/§30 governance+planning specs).
- files: stewie/contracts/__init__.py
- test_target: NEW test citing [REQ:EG-04]

### EG-05 (P0) — atomic
- goal: platform backlog row EG-05 (PRD §7 + §29/§30 governance+planning specs).
- files: stewie/contracts/__init__.py
- test_target: NEW test citing [REQ:EG-05]

### EG-06 (P0) — atomic
- goal: platform backlog row EG-06 (PRD §7 + §29/§30 governance+planning specs).
- files: stewie/contracts/__init__.py
- test_target: NEW test citing [REQ:EG-06]

### EG-07 (P1) — atomic
- goal: platform backlog row EG-07 (PRD §7 + §29/§30 governance+planning specs).
- files: stewie/contracts/__init__.py
- test_target: NEW test citing [REQ:EG-07]

### EG-08 (P1) — atomic
- goal: platform backlog row EG-08 (PRD §7 + §29/§30 governance+planning specs).
- files: stewie/contracts/__init__.py
- test_target: NEW test citing [REQ:EG-08]

### EG-09 (P1) — atomic
- goal: platform backlog row EG-09 (PRD §7 + §29/§30 governance+planning specs).
- files: stewie/contracts/__init__.py
- test_target: NEW test citing [REQ:EG-09]

### EG-10 (P2) — atomic
- goal: platform backlog row EG-10 (PRD §7 + §29/§30 governance+planning specs).
- files: stewie/contracts/__init__.py
- test_target: NEW test citing [REQ:EG-10]

### EG-11 (P0) — atomic
- goal: platform backlog row EG-11 (PRD §7 + §29/§30 governance+planning specs).
- files: stewie/contracts/__init__.py
- test_target: NEW test citing [REQ:EG-11]

### EG-12 (P1) — atomic
- goal: platform backlog row EG-12 (PRD §7 + §29/§30 governance+planning specs).
- files: stewie/contracts/__init__.py
- test_target: NEW test citing [REQ:EG-12]

### MP-05 (P1) — atomic
- goal: platform backlog row MP-05 (PRD §7 + §29/§30 governance+planning specs).
- files: lode/mission_planner.py
- test_target: NEW test citing [REQ:MP-05]

### MP-06 (P1) — atomic
- goal: platform backlog row MP-06 (PRD §7 + §29/§30 governance+planning specs).
- files: lode/mission_planner.py
- test_target: NEW test citing [REQ:MP-06]

### MP-07 (P0) — atomic
- goal: platform backlog row MP-07 (PRD §7 + §29/§30 governance+planning specs).
- files: lode/mission_planner.py
- test_target: NEW test citing [REQ:MP-07]

### MP-08 (P1) — atomic
- goal: platform backlog row MP-08 (PRD §7 + §29/§30 governance+planning specs).
- files: lode/mission_planner.py
- test_target: NEW test citing [REQ:MP-08]

### MP-09 (P1) — atomic
- goal: platform backlog row MP-09 (PRD §7 + §29/§30 governance+planning specs).
- files: lode/mission_planner.py
- test_target: NEW test citing [REQ:MP-09]

### MP-10 (P1) — atomic
- goal: platform backlog row MP-10 (PRD §7 + §29/§30 governance+planning specs).
- files: lode/mission_planner.py
- test_target: NEW test citing [REQ:MP-10]

### MP-11 (P1) — atomic
- goal: platform backlog row MP-11 (PRD §7 + §29/§30 governance+planning specs).
- files: lode/mission_planner.py
- test_target: NEW test citing [REQ:MP-11]

### MP-12 (P2) — atomic
- goal: platform backlog row MP-12 (PRD §7 + §29/§30 governance+planning specs).
- files: lode/mission_planner.py
- test_target: NEW test citing [REQ:MP-12]

### PX-06 (P0) — atomic
- goal: break terramechanics->stewie.specs.constants (prereq for PO-18); forge-local geotech defaults + preserve config-overlay via injection at stewie-side call sites; behavior byte-identical.
- acceptance: production stewie/physics/terramechanics imports no stewie.specs.constants (AST guard extends PX-05); from_constants() unchanged; a config override still reaches built params via injection; physics+lode regression green.
- files: stewie/physics/terramechanics.py, stewie/specs/constants.py, stewie/physics/body_params.py, scripts/test_import_boundaries.py
- test_target: NEW/extended [REQ:PX-06] in scripts/test_import_boundaries.py + stewie/physics/test_terramechanics.py

## §7.B GIS Mission Workbench briefs (PRD2 fold, 2026-07-04)

### GW-00
- goal: Trek + web-panel CSP allowlist pinned for GeoLibre (prerequisite for GW-05/RT-04).
- files: deploy/nginx.conf
- test_target: stewie/server/test_gw00_geolibre_csp.py [REQ:GW-00]

### RT-00
- goal: install pip + the stewie python monorepo into the ROS image so live-spine rclpy nodes import run_replay.
- files: deploy/ros2/Dockerfile.ros2dev, deploy/ros2/Dockerfile.gazebo
- test_target: NEW ros2_ws/test_rt00_stewie_stack.py [REQ:RT-00]

### GW-05
- goal: MapLibre map substrate in the local polar-stereo frame (Trek tiles + LOLA terrain-RGB); /dem/site_xy round-trip.
- files: frontend/src/App.tsx, frontend/package.json, stewie/server/routers/dem.py
- test_target: NEW stewie/server/test_gw05_map_substrate.py [REQ:GW-05]

### GW-06
- goal: layer tree + legend toggling the LY-01 catalog on the map.
- files: frontend/src/App.tsx, frontend/src/fetchState.ts
- test_target: NEW stewie/server/test_gw06_layer_tree.py [REQ:GW-06]

### GW-07
- goal: selection + right inspector (attributes/provenance/freshness/actions/runtime evidence).
- files: frontend/src/App.tsx
- test_target: NEW stewie/server/test_gw07_inspector.py [REQ:GW-07]

### GW-08
- goal: edit session (create/modify/delete/measure/snap/undo mission features) writing only via backend routes.
- files: frontend/src/App.tsx, stewie/server/routers/missions.py
- test_target: NEW stewie/server/test_gw08_edit_session.py [REQ:GW-08]

### GW-02
- goal: unified routeable workspace context (PRD2 field set) drives every view; one URL restores all.
- files: frontend/src/workspace.ts, frontend/src/workspace_context.tsx
- test_target: NEW stewie/server/test_gw02_context.py [REQ:GW-02]

### GW-03
- goal: layer-eligibility UI (display/planning/release/execute + freshness/provenance/uncertainty).
- files: frontend/src/App.tsx, frontend/src/panes/DepthSource.tsx
- test_target: NEW stewie/server/test_gw03_layer_eligibility.py [REQ:GW-03]

### GW-04
- goal: Asset Library (browse/search/inspect/export/recover durable assets, separate from visible layers).
- files: frontend/src/App.tsx, stewie/server/routers/missions.py
- test_target: NEW stewie/server/test_gw04_assets.py [REQ:GW-04]

### LY-01
- goal: backend layer catalog/registry — the ~65 named layers with type/frame/source-class/eligibility/provenance.
- files: stewie/server/routers/world.py, stewie/server/routers/dem.py
- test_target: NEW stewie/server/test_ly01_layer_catalog.py [REQ:LY-01]

### LY-02
- goal: layer-consumption inspector (display/planner/costmap/rehearsal/release/execute/report/export).
- files: stewie/server/routers/world.py
- test_target: NEW stewie/server/test_ly02_consumption.py [REQ:LY-02]

### PH-01
- goal: physics backend registry (authority scope/conservation/calibration/compatibility/refusal/evidence); extends PX-02.
- files: stewie/server/routers/models.py, stewie/contracts/physics_model_control.py
- test_target: NEW stewie/server/test_ph01_physics_registry.py [REQ:PH-01]

### PH-02
- goal: attribute every route/volume/risk value to a physics backend + calibration source.
- files: stewie/server/routers/executive.py, stewie/contracts/physics_model_control.py
- test_target: NEW stewie/server/test_ph02_attribution.py [REQ:PH-02]

### TM-02
- goal: terramechanics spine exposes terms (slope/roughness/bearing/sinkage/slip/traction/energy/uncertainty) inspectable.
- files: stewie/physics/terramechanics.py, stewie/server/routers/models.py
- test_target: NEW stewie/server/test_tm02_terra_spine.py [REQ:TM-02]

### TM-03
- goal: terramechanics outputs generate the derived catalog layers (traversability/energy/slip-risk/bearing-sinkage/...).
- files: stewie/physics/terramechanics.py, stewie/server/routers/world.py
- test_target: NEW stewie/server/test_tm03_terra_layers.py [REQ:TM-03]

### TM-04
- goal: rehearsal/report compares predicted slip/sinkage/energy vs observed/replayed telemetry.
- files: stewie/runtime/replay_loop.py, stewie/server/routers/evidence.py
- test_target: NEW stewie/server/test_tm04_predicted_observed.py [REQ:TM-04]

### SD-01
- goal: Surface Design view (pads/berms/cuts/fills/roads -> typed mission orders + volume/constructability evidence).
- files: frontend/src/App.tsx, stewie/server/routers/missions.py
- test_target: NEW stewie/server/test_sd01_surface_design.py [REQ:SD-01]

### RT-01
- goal: runtime profile registry endpoint (desktop_sil/digital_twin/ros2_replay/gazebo_sim/hil/field_test/live_rover + capabilities).
- files: stewie/server/routers/models.py
- test_target: NEW stewie/server/test_rt01_runtime_profiles.py [REQ:RT-01]

### RT-02
- goal: evidence bound to run/profile; execution service the sole command egress.
- files: stewie/server/routers/evidence.py
- test_target: NEW stewie/server/test_rt02_evidence_binding.py [REQ:RT-02]

### RT-03
- goal: Gazebo rehearsal on real site DEM + truth-isolated sensors; cockpit shows /clock/bridge-freshness/bag/truth-denial.
- files: ros2_ws/src/stewie_bringup/launch/gz_sim.launch.py, deploy/ros2/Dockerfile.gazebo
- test_target: NEW ros2_ws/test_rt03_gazebo_rehearsal.py [REQ:RT-03]

### RT-04
- goal: RViz/Foxglove engineering panel (evidence-only) served via web bridge.
- files: deploy/nginx.conf, frontend/src/App.tsx
- test_target: NEW stewie/server/test_rt04_rviz_panel.py [REQ:RT-04]

### RT-05
- goal: Godot mission view (sidecar-first) rendering the selected branch/run + capture metadata.
- files: ros2_ws/src/stewie_bringup/launch/gz_sim.launch.py, deploy/ros2/Dockerfile.gazebo
- test_target: NEW ros2_ws/test_rt05_godot_view.py [REQ:RT-05]

### AU-01
- goal: global command-authority card visible from every command-capable view; every refusal reason.
- files: frontend/src/panes/Authority.tsx, frontend/src/App.tsx
- test_target: NEW stewie/server/test_au01_global_authority.py [REQ:AU-01]

### EV-01
- goal: Evidence/Report reproduces plan inputs + selected layers + runtime profile + artifacts + transactions + audit.
- files: frontend/src/panes/Report.tsx, stewie/server/routers/evidence.py
- test_target: NEW stewie/server/test_ev01_evidence_report.py [REQ:EV-01]


## Council-#55 buildable-row dispatch briefs (FS-01 assessment gate)

Retroactive dispatch briefs for the 26 buildable ready-set §7 rows the FS-01 assessment gate flagged as un-briefed (drafted 2026-07-08 via a 26-agent read-only pass; each re-checked to name a real repo file). Parser scripts/fanout_plan.py assessment_inventory reads `### ID` + `- files:` + `- test_target:`.

### QW-01 — atomic
- goal: Add a signed-in browser smoke that boots the served QWC2 /ide SPA and opens each STEWIE Mission* plugin (the 11 registered in appConfig) over the OpenLayers map at desktop + phone widths, failing on any blocking console error.
- acceptance: For every Mission* plugin registered in gis/qwc2/js/appConfig.js, opening it in the /ide SPA at desktop (~1600px) and phone (~390px) widths yields zero non-allowlisted console errors.
- current_state: partial: the QWC2 /ide front door exists — appConfig.js registers 11 STEWIE Mission* plugins over an OpenLayers map, built to gis/qwc2/prod and served read-only by the artemis-web nginx at /ide/ (deploy/compose.yml:296), with ad-hoc per-feature Playwright proof drivers in gis/qwc2/proof/*.cjs / missing the single consolidated signed-in browser smoke (analog of scripts/ui_smoke.mjs for the cockpit) that iterates EACH Mission* plugin at desktop+phone widths asserting zero blocking console errors; no [REQ:QW-01] marker exists in the tree.
- files: gis/qwc2/js/appConfig.js, scripts/ui_smoke.mjs, deploy/compose.yml, scripts/ide_smoke.mjs, scripts/ide_smoke.test.mjs
- test_target: NEW scripts/ide_smoke.mjs (live signed-in browser smoke carrying a [REQ:QW-01] marker: iterates the appConfig Mission* plugins at desktop+phone widths, fails on any non-allowlisted console error; pure console-violation/summarize helpers unit-tested in NEW scripts/ide_smoke.test.mjs, mirroring scripts/ui_smoke.test.mjs)

### GW-01 — atomic
- goal: Build a per-site LROC NAC regional drape (0.5-2 m) as a Trek-WMTS/COG layer that loads into the QWC2 IAU_2015:30135 map, registered to the site LOLA DEM bbox, leaving the whole-moon basemap on WAC/Kaguya.
- acceptance: A pure builder returns a QWC2 WMTS/image layer object for a site's NAC drape declared in the lunar frame with imageExtent = the site's LOLA DEM bbox (within tolerance), while the whole-moon basemap stays WAC.
- current_state: partial: whole-moon WAC/Kaguya basemap done (wholeMoonGlobe.js streams real LRO WAC from trek.nasa.gov) + a manual "LROC Lunaserv WMS" import preset (config.json:59) + a site DEM bbox fetch already in MissionLayers.ensureBbox / no auto per-site NAC drape (0.5-2 m) built as a Trek-WMTS/COG layer registered to the LOLA DEM in the 30135 frame; catalogLayers.imageLayerFor only serializes the 16 backend globe PNG kinds
- files: gis/qwc2/js/mission/catalogLayers.js, gis/qwc2/js/plugins/MissionLayers.jsx, gis/qwc2/js/mission/wholeMoonGlobe.js, gis/qwc2/static/config.json
- test_target: gis/qwc2/js/mission/catalogLayers.test.js (add a [REQ:GW-01] node:test asserting nacDrapeLayer builds a Trek-WMTS/COG layer in the lunar CRS with imageExtent = the site DEM bbox, and that the WAC whole-moon source is unchanged)

### GW-09 — atomic
- goal: Attribute the already-shipped dual-mode lunar planning graticule (selenographic lon/lat reprojected to polar-stereographic + straight metric km-grid, injected reproject) to GW-09 by tagging its node test [REQ:GW-09]; the feature/module/plugin already exist and are wired.
- acceptance: A node test asserts the graticule generates gridline coords + labels from an injected reproject(lon,lat)->[x,y]: 12 selenographic meridians (reprojected, labeled "0°".."330°") plus a straight metric km-grid with "N km" labels — mirroring the GW-09 clause and carrying a [REQ:GW-09] marker.
- current_state: partial: pure generator graticule.js (meridians/parallels/kmGrid/selenographic + #60 reproject/step guards), its node test graticule.test.js (asserts gridline coords + "0°"/"N km" labels + hardening), and the QWC2 map-button plugin Graticule.jsx (proj4 IAU_2015:30100->30135 reproject, off/selenographic/metric cycle) all SHIPPED and registered in appConfig.js:85/:186 — every acceptance-clause part is met / missing only the [REQ:GW-09] req_trace marker: the code+test are tagged [REQ:#40], so no REQ:GW-09 marker exists under gis/ and req_trace cannot attribute the acceptance test to the PRD row (blocks an honest glyph flip).
- files: gis/qwc2/js/mission/graticule.test.js, gis/qwc2/js/mission/graticule.js, gis/qwc2/js/plugins/Graticule.jsx, gis/qwc2/js/appConfig.js
- test_target: gis/qwc2/js/mission/graticule.test.js::"meridians: 12 constant-lon lines every 30deg, spanning latMin..latMax"

### GW-10 — atomic
- goal: Extend the shipped monotonic reqGuard to the two remaining surfaces the GW-10 clause names -- the physics panel (MissionTerramech.jsx, incl. its currently-unguarded authority fetch) and the raster panel (MissionLayers.jsx) -- so every named surface (raster/physics/inspector) drops a stale in-flight load on a rapid site switch instead of relying on a weaker inline WS.site() compare.
- acceptance: A slow site-A load that resolves AFTER a switch to site-B is dropped (its reqGuard token is stale) and cannot overwrite site-B's physics/raster state -- the "wrong-site race" assertion (A slow, B fast -> B kept, A's late resolve dropped) now holds for the terramech and layers panel loads, not only the inspector.
- current_state: partial: reqGuard.js utility (makeReqGuard next/current/bump) + reqGuard.test.js (4 unit tests, ran green via node --test) SHIPPED and adopted in SelectionInspector.jsx (inspector) + MissionCrossSection.jsx (cross-section) / the physics panel MissionTerramech.jsx (spine fetch uses only inline WS.site()!==site, authority fetch L42 has NO guard) and the raster panel MissionLayers.jsx (inline WS.site() string compares, not the monotonic token) are NOT on the guard, and reqGuard.test.js carries no [REQ:GW-10] marker.
- files: gis/qwc2/js/mission/reqGuard.js, gis/qwc2/js/plugins/MissionTerramech.jsx, gis/qwc2/js/plugins/MissionLayers.jsx, gis/qwc2/js/plugins/SelectionInspector.jsx, gis/qwc2/js/mission/reqGuard.test.js
- test_target: gis/qwc2/js/mission/reqGuard.test.js::"the wrong-site race: A(slow) then B(fast) -> B kept, A's late resolve dropped" -- add the [REQ:GW-10] marker (currently unmarked) and extend with physics/raster panel-load race cases; this is a node:test (JS) tier gated by CI `node --test gis/qwc2/js/**/*.test.js`, as GW-10 is a pure-frontend row with no python surface.

### LY-03 — atomic
- goal: Complete the LY-03 Earth-CRS reject gate for user-imported GeoJSON so all four Earth-CRS spellings (EPSG:4326/3857/CRS84/WGS84) are rejected with a legible reason and both lunar frames (IAU_2015:30135/30100) are accepted, carrying a [REQ:LY-03] marker.
- acceptance: A [REQ:LY-03] test asserts validateLayerCrs returns ok:false with an /EARTH CRS/i reason for EPSG:4326, EPSG:3857, CRS84, and WGS84, and ok:true (isLunar) for IAU_2015:30135 and 30100, so an Earth-CRS import never reaches the map or is promoted planning-eligible.
- current_state: partial: userLayers.validateLayerCrs already rejects Earth CRS + accepts IAU frames and MissionUserLayer.jsx gates map-add on it (EPSG:4326/3857 + IAU:30100 asserted in userLayers.test.js) / missing: explicit test assertions for the CRS84, WGS84, and IAU_2015:30135 strings the clause enumerates + a [REQ:LY-03] marker; the promote-to-planning-eligible half is a separate unbuilt path (plugin defers it as "next increment").
- files: gis/qwc2/js/mission/userLayers.test.js, gis/qwc2/js/mission/userLayers.js, gis/qwc2/js/plugins/MissionUserLayer.jsx
- test_target: gis/qwc2/js/mission/userLayers.test.js (extend with a [REQ:LY-03] header marker + assertions for CRS84/WGS84 rejection and IAU_2015:30135 acceptance; runs in the CI test-js tier via `node --test gis/qwc2/js/**/*.test.js`. NOTE: scripts/req_trace.py globs only Python test_*.py, so this JS marker will NOT count toward a §7 V=D glyph flip.)

### LY-04 — atomic
- goal: Bind each of the four LY-04 layer kinds (ice-probability, localization-confidence, sensor-coverage, digital-twin-difference) to the LY-01 catalog: register with a REAL backend producer + provenance/eligibility, or declare it explicitly unavailable (no fabricated drape).
- acceptance: A test asserts each of the four named kinds is either typed+registered in the layer catalog with a real producer + declared source_class/eligibility, or explicitly declared absent/unavailable (no fabricated raster), mirroring PRD.md:680 (extends LY-01).
- current_state: partial: 3 of 4 kinds already have near-equivalent TYPED+REGISTERED catalog rows in layer_catalog.json (66 layers) with source_class + planning/release eligibility -- robot.covariance ("localization covariance")=localization-confidence, robot.sensor_frustums ("camera/depth/LiDAR coverage")=sensor-coverage, map.changed_terrain + evidence.before_after_dem ("before/after terrain delta")=digital-twin-difference; and the "no fabricated drape" unavailable-declaration pattern already exists for ice-stability (gis_layers.transect_profile, lines 846-850, and terrain.thermal noted catalog-only-no-producer). MISSING: ice-probability has NO catalog entry (only the real horizon-computed terrain.psr proxy + producerless terrain.thermal); the four LY-04-named kinds are never explicitly mapped to a producer-available-or-unavailable status at the catalog level; and NO test exists (grep found zero REQ:LY-04 markers and no test_ly04_*.py) asserting each of the four is typed+registered-or-explicitly-absent.
- files: stewie/server/layer_catalog.json, scripts/gen_layer_catalog.py, design/STEWIE_PRD2_gis_mission_workbench_2026-07-04.md, stewie/server/gis_layers.py, stewie/server/test_ly04_missing_layer_kinds.py
- test_target: stewie/server/test_ly04_missing_layer_kinds.py::test_ly04_each_missing_kind_is_registered_or_explicitly_absent (NEW; alternatively extend stewie/server/test_ly01_layer_catalog.py::test_ly01_endpoint_serves_the_catalog_with_eligibility_rules with a [REQ:LY-04] marker)

### SD-02 — atomic
- goal: Extend the SD-01 earthwork balance -- backend order_earthwork + its JS materialBalance mirror -- to return loose-spoil volume and a signed net borrow/spoil kg (cut-only => spoil, fill-only => borrow), cited by a Python [REQ:SD-02] test the CI req_trace gate actually scans.
- acceptance: A [REQ:SD-02] test asserts, on real leap.structures.decompose'd cut+fill orders, that the balance returns bank cut volume, loose spoil (RHO_DEEP->RHO_SPOIL bulking), fill demand, and net borrow/spoil kg with mass conserved: cut-only => net spoil, fill-only => net borrow.
- current_state: partial: JS materialBalance (planTools.js:132) + its uncited node test (planTools.test.js:135) already return bank cut, loose_spoil bulking, fill mass, and net balance_kg (surplus/deficit); Python SD-01 order_earthwork (constructability.py:49) returns cut/fill volume+mass+mass_balanced / MISSING a Python [REQ:SD-02] test the req_trace gate scans (it scans only test_*.py, so the JS test is unscanned -> glyphs I|V|X = N|N|N), the explicit cut-only=>spoil / fill-only=>borrow assertions, and a signed net-borrow/spoil kg term with a loose_spoil volume field in the backend.
- files: stewie/server/constructability.py, gis/qwc2/js/mission/planTools.js, gis/qwc2/js/mission/planTools.test.js, stewie/server/test_sd02_material_balance.py
- test_target: stewie/server/test_sd02_material_balance.py::test_material_balance_returns_bank_cut_loose_spoil_and_net_borrow_spoil

### SD-03 — atomic
- goal: Drape per-value uncertainty on the SD-03 transect so each sampled layer (elevation/slope/bearing/sinkage/PSR) carries BOTH its source layer and an uncertainty (DEM resolution + terramechanics calibration status), mirroring SD-01's evidence, and surface it in the cross-section panel.
- acceptance: transect_profile / POST /world/transect returns an `uncertainty` block (dem_resolution_m + per-layer sinkage/bearing/slope calibration status) alongside the existing `sources` trace, so each draped value carries source-layer AND uncertainty, with ice-stability still an explicit non-fabricated gap.
- current_state: partial: POST /world/transect + transect_profile (gis_layers.py:779) drape elevation/slope/bearing/sinkage/PSR per sample with cumulative distance, a `sources` source-layer trace, and an honest ice-stability gap (all tested in test_transect.py [REQ:SD-03]); MissionCrossSection.jsx + crossSection.js render them. MISSING: the "+ uncertainty" half of the clause -- no per-value uncertainty/calibration/DEM-resolution block on the transect (the exact pattern already exists in SD-01 constructability evidence, test_sd01_constructability.py:113, but is not carried here), and regolith is only implied via bearing/sinkage rather than named.
- files: stewie/server/gis_layers.py, stewie/server/routers/world.py, gis/qwc2/js/plugins/MissionCrossSection.jsx, gis/qwc2/js/mission/crossSection.js, stewie/server/test_transect.py
- test_target: stewie/server/test_transect.py::test_transect_each_value_carries_source_layer_and_uncertainty (NEW test in the existing file, add [REQ:SD-03] marker)

### WS-01 — atomic
- goal: Add a permanent top World-State header-strip plugin to the QWC2 lunar IDE (persistent on every screen) showing mission, twin-sync, terrain-version, changed-since-last-mission, confidence, and the 2 new counters (learning-dataset-size, pending-validation), binding real endpoints or marking a counter "unavailable".
- acceptance: A test asserts the strip's model renders real values sourced from /twin/version (twin_version + chain_valid), GET /world observed_fraction (confidence), and /twin/terrain cells_changed (changed-since-last-mission), while the 2 new counters (learning-dataset-size, pending-validation) render "unavailable" rather than any fabricated count.
- current_state: partial: real backend sources exist (/twin/version twin.py:100 -> twin-sync+terrain-version; GET /world observed_fraction world.py:403 -> confidence; /twin/terrain/{site} cells_changed twin.py:116 -> changed-since-last-mission; workspace.js:11 -> mission/site) and the pure-client + node-test + plugin pattern is established (runtimeClient.js + runtimeClient.test.js + a Mission*.jsx registered in appConfig.js/config.json) / MISSING: the World-State header-strip plugin + its pure client module itself, and any endpoint for the 2 new counters (learning-dataset-size, pending-validation) -- those have no source and must render "unavailable".
- files: gis/qwc2/js/mission/worldStateStrip.js, gis/qwc2/js/plugins/WorldStateStrip.jsx, gis/qwc2/js/mission/workspace.js, gis/qwc2/js/appConfig.js, gis/qwc2/static/config.json
- test_target: gis/qwc2/js/mission/worldStateStrip.test.js (NEW node --test, carry a [REQ:WS-01] marker; mirrors runtimeClient.test.js -- asserts buildWorldStateModel binds real values from /twin/version, GET /world, /twin/terrain + workspace.js, and marks the 2 new counters "unavailable")

### WS-02 — atomic
- goal: Build a Digital-Twin Health panel (QWC2 IDE) showing per-model agreement/trust for localization/map-agreement/terrain/wheel/battery/excavation, each rolled up from the real TM-04 predicted-vs-observed run telemetry or honestly flagged not-yet-surfaced.
- acceptance: A test asserts every per-model percent shown traces to a real predicted-vs-observed computation (energy->battery/residual, slip->wheel, terramechanics->terrain) and that localization/map-agreement/excavation (and any un-telemetered term) are flagged not_surfaced, never fabricated.
- current_state: partial: TM-04 predicted-vs-observed backend already exists and is surfaced in POST /executive/run (terramechanics_comparison + reconciliation) / MISSING the per-model twin-health rollup and the Digital-Twin Health frontend panel
- files: stewie/runtime/replay_loop.py, stewie/server/routers/executive.py, gis/qwc2/js/mission/twinHealth.js, gis/qwc2/js/plugins/MissionTwinHealth.jsx, gis/qwc2/js/appConfig.js, gis/qwc2/static/config.json
- test_target: stewie/server/test_ws02_twin_health.py::test_ws02_per_model_health_traces_to_real_computation

### WS-04 — atomic
- goal: Build a QWC2 IDE "Learning-lifecycle" panel plus a backend read-surface that lists collect-experience -> generate-dataset -> retrain(traversability/slip/energy) -> evaluate-policy sourced from the REAL roversim RL stack (RoverSimEnv + train_ppo + validation/rl artifacts), and blocks any policy from an operational label unless it carries the RL-01 card (ModelArtifact.deployment_ready).
- acceptance: A python test asserts the lifecycle lineage renders from real RL-stack artifacts (no synthetic/fabricated stages) and that an RL-01-incomplete policy (ModelArtifact missing card fields so deployment_ready is False) is blocked from the operational label.
- current_state: partial: the RL-01 card gate exists (stewie/contracts/__init__.py::ModelArtifact.deployment_ready), the /models endpoint (routers/models.py) already surfaces RL-01 deployment-ready criteria + ModelArtifact governance, and the real RL stack exists (stewie/envs/rover_env.py RoverSimEnv, scripts/demo/train_ppo.py, validation/rl/*.png) / missing: no endpoint enumerates the 4 collect->generate->retrain->evaluate lifecycle stages bound to those real artifacts, no QWC2 Learning-lifecycle panel plugin, and no test asserting real lineage renders + an RL-01-incomplete policy is blocked from an operational label.
- files: stewie/server/routers/models.py, stewie/contracts/__init__.py, gis/qwc2/js/plugins/MissionLearning.jsx, gis/qwc2/js/appConfig.js, scripts/demo/train_ppo.py
- test_target: stewie/server/test_ws04_learning_lifecycle.py (NEW; python so it counts in req_trace/CI) with a [REQ:WS-04] marker asserting real lifecycle lineage + RL-01-incomplete policy block; alternatively extend stewie/server/test_models_pane.py::test_models_endpoint_serves_the_real_registries.

### WS-05 — atomic
- goal: Redesign the QWC2 Mission forward-compare card to render >=2 candidate futures side-by-side with kWh/hours/slip/recharge/completion columns bound to real lode.resync.forward_compare rows, surfacing slip + explicit completion from the conserved planner totals.
- acceptance: /resync/compare (forward_compare) returns >=2 real futures each carrying energy_MJ (kWh), time_s (hours), slip, charges (recharge) and a completion field from real planner totals, and the card binds those real rows (no synthetic values).
- current_state: partial: a forward-compare card exists (MissionPlan.jsx renderCompare/renderFutures + planAuthor.js compareFutures POSTing to real /api/resync/compare -> lode.resync.forward_compare, rendering hours/kWh/recharges/feasibility/optimality) / missing = a slip column + an explicit completion column in forward_compare output (resync.py:112-136 has neither; slip lives only in planner_endurance, not in plan totals), the side-by-side tradeoff layout (renderFutures stacks futures vertically as <li> rows), and a test asserting the card binds those real forward-compare rows.
- files: gis/qwc2/js/plugins/MissionPlan.jsx, gis/qwc2/js/mission/planAuthor.js, lode/resync.py, stewie/server/routers/plan.py
- test_target: stewie/server/test_admin.py::test_resync_compare_endpoint_ranks_futures (extend with a [REQ:WS-05] marker asserting each real future row carries slip + completion + energy_MJ/time_s/charges)

### TP-01 — epic
- goal: Reframe the plan tool palette into a Mission Tasks palette that leads with work-packages grouped into 6 functional groups (Earthworks/Transportation/Construction/Survey/Science/Fleet), two-level (Primitive Ops + Templates), where selecting a work-package emits a typed order that decomposes to mass-balanced cut/fill via SD-01.
- acceptance: A Playwright test asserts the 6 functional groups render in the palette AND selecting a template work-package produces a decomposed (mass-balanced cut/fill) order.
- current_state: partial: decompose backend exists (leap/structures.py::decompose -> 8 templates -> mass-balanced cut/fill; POST /api/structure at perception.py:384; GET /api/construction catalog with balanced flags) and the frontend template palette MissionPlan.jsx::renderStructures() places a template -> /api/structure -> adopts decomposed orders, with Playwright hooks (data-stewie-structure, controller placeStructure/structureCount); MISSING the 6 functional-group taxonomy (templates/primitives are a flat list, no group/category field), the two-level Primitive-Ops+Templates organization, the Mission Tasks leading reframe, and any Playwright browser test over the QWC2 IDE (only non-CI node:test *.test.js exist; browser tier is a gap).
- files: gis/qwc2/js/plugins/MissionPlan.jsx, leap/structures.py, stewie/server/routers/construction.py, gis/qwc2/js/mission/planAuthor.js, stewie/server/test_tp01_mission_tasks_palette.py
- test_target: NEW stewie/server/test_tp01_mission_tasks_palette.py::test_mission_tasks_palette_renders_six_groups_and_template_decomposes (Playwright against the gis/qwc2/prod build; PRD clause mandates Playwright and no QWC2 browser test exists). Data-leg alternative: extend stewie/server/test_construction_pane.py::test_construction_endpoint_serves_the_real_catalog_and_acceptance with [REQ:TP-01] for the catalog 6-group taxonomy.

### TP-02 — epic
- goal: Build the TP-02 intelligent template wizard: a parameterized structure template (e.g. Landing Pad collecting Length/Width/Bearing/Finish/Flatness/Elevation/Material/Priority) that computes mass-balanced cut/fill + equipment/routes/time/energy/risk and expands to the ordered Survey->Excavate->Move->Grade->Compact->Inspect->Approve work order.
- acceptance: A parameterized template yields order_earthwork mass_balanced=True with the expected cut/fill volumes AND an ordered 7-step work order equal to [Survey, Excavate, Move, Grade, Compact, Inspect, Approve].
- current_state: partial: template catalog + decompose->mass-balanced cut/fill orders (leap/structures.py, routers/construction.py, constructability.order_earthwork) and route/time/energy totals (lode/mission_planner.py) exist, plus a flat template-default param editor UI (MissionPlan.jsx/planAuthor.js) / missing the 8-field wizard schema (landing_pad has only side_m/cut_depth_m/berm_height_m), the named Survey->Excavate->Move->Grade->Compact->Inspect->Approve ordered work-order expansion, and the risk term.
- files: leap/structures.py, stewie/server/constructability.py, stewie/server/routers/construction.py, gis/qwc2/js/plugins/MissionPlan.jsx, leap/work_order.py
- test_target: stewie/server/test_tp02_template_wizard.py::test_parameterized_template_yields_massbalanced_volumes_and_ordered_steps

### TP-03 — atomic
- goal: Make the QWC2 mission palette context-aware: filter the offered tools to the SELECTED vehicle's capabilities (from the real stewie/specs/vehicles.py VehicleModel registry) AND to a selected existing feature's type/state (a berm -> Inspect/Extend/Repair/Remove/Compact/Survey), via a shared capability->tool + feature->action-set map served to the palette. Requires adding a survey-class vehicle and `grade` to the excavator so the capability contrast is real in the registry.
- acceptance: A test asserts the excavator's palette exposes Dig/Dump/Compact/Grade while a survey rover's does not (grounded in the real registry capabilities), and that selecting a berm feature yields its Inspect/Extend/Repair/Remove/Compact/Survey action set.
- current_state: partial: the real VehicleModel registry with per-vehicle `capabilities` frozensets + capabilities_of() exists (vehicles.py) and is already served (models.py `_vehicle_row` GET /models, GET /fleet); a cell-affordance list (gis_layers._point_actions) + a SelectionInspector rendering p.actions exist / MISSING: a survey-class vehicle and `grade` on the excavator (all 3 registry entries are excavators with identical caps, none have grade), the capability->palette-tool map, the feature-type/state->action-set map (berm actions), and the palette actually filtering offered tools by the selected vehicle's caps AND the selected feature.
- files: stewie/specs/vehicles.py, stewie/specs/test_vehicles.py, gis/qwc2/js/mission/planTools.js, gis/qwc2/js/plugins/MissionPlan.jsx, stewie/server/routers/models.py
- test_target: stewie/specs/test_vehicles.py::test_context_aware_palette_filters_by_vehicle_and_feature

### TP-04 — atomic
- goal: Expand the object palette to TP-04's 11-type place-object vocabulary and stamp per-object provenance so a placed object is a durable first-class world object in the versioned edit-session twin store (survives reload).
- acceptance: A test places an expanded-vocab object (e.g. habitat), reloads the session from the twin store (db.load_session / _reload_from_store), and asserts the object round-trips intact with its otype and provenance preserved.
- current_state: partial: the versioned db-backed edit-session twin (stewie/server/edit_session.py) already stores place-object markers as first-class point features {fid,kind:marker,x,y,otype,label}, persists them via db.persist_session/load_session so they survive restart, versions + before/after-audits them, and drives them from a frontend object palette (planTools.js OBJECT_TYPES, MissionPlan.jsx, planAuthor.js MARKER_COLOR); create/audit/undo/delete are tested in test_edit_session_markers.py / missing: ALLOWED_MARKER_TYPES holds only 5 types (beacon/cache/instrument/sample/antenna) so 7 of the 11 (habitat/powerstation/relay/charger/storagebin/processingplant/navmarker) are absent, the stored marker carries NO per-object provenance stamp (created_by/created_at/source), and no test round-trips a placed object through the store after a reload.
- files: stewie/server/edit_session.py, gis/qwc2/js/mission/planTools.js, gis/qwc2/js/plugins/MissionPlan.jsx, gis/qwc2/js/mission/planAuthor.js, stewie/server/test_edit_session_markers.py
- test_target: stewie/server/test_edit_session_markers.py::test_placed_object_roundtrips_through_twin_store_with_provenance

### QG-01 — atomic
- goal: Add a [REQ:QG-01] traceability marker to the existing QGIS-free backend test (plus a small qgis-free assertion that the provider wires both named Processing algorithms) so the already-shipped stewie_qgis provider's §7 glyph legitimately flips to V=D.
- acceptance: A [REQ:QG-01]-marked CI test asserts the QGIS-free stewie_backend fetch+parse (spine rows + point attributes) with no qgis.* on the test path, and that the provider registers StewieTerramechanics + StewieSamplePoint.
- current_state: partial: provider (StewieProvider/StewiePlugin), both algorithms (StewieTerramechanicsAlgorithm/StewieSamplePointAlgorithm), the qgis-free stewie_backend, metadata.txt, and 5 pure-CI tests (in pytest testpaths, no qgis import, all 5 PASS via runtime venv) all shipped; public endpoints /world/terramechanics-layers (routers/world.py:143) + /world/point (:306) exist / MISSING: no [REQ:QG-01] marker anywhere (scripts/req_trace.py therefore keeps §7 glyphs N|N|N despite SHIPPED tag), and no CI assertion that the provider registers exactly the two named algorithms.
- files: stewie_qgis/test_stewie_backend.py, stewie_qgis/stewie_backend.py, stewie_qgis/stewie_provider.py, stewie_qgis/stewie_algorithms.py, stewie/server/routers/world.py
- test_target: stewie_qgis/test_stewie_backend.py::test_terramechanics_rows_normalizes_the_spine (extend with a [REQ:QG-01] marker; optionally add test_provider_wires_both_algorithms in the same file, asserting registration qgis-free via static source, not import)

### QG-02 — atomic
- goal: Close the loop on QG-02: tag and tighten the live qgis-server (--profile gis) acceptance so GetMap output is test-asserted to match the QGIS Desktop proof render, not just non-blank.
- acceptance: A --profile gis WMS GetMap of Site01 in IAU_2015:30135 returns a pole-truthful PNG that pixel-matches the QGIS Desktop reference render gis/proof/site01_render.png within tolerance (real on-disk project, no synthetic data).
- current_state: partial: existing = gis/stewie_south_pole.qgz + deploy/compose.yml qgis-server (profile gis, qgis/qgis-server:3.34) + live gis/test_server.py WMS GetCapabilities/GetMap tests asserting Site01 layers, IAU_2015:30135, and a non-blank correct-size PNG; missing = no test ties the server GetMap to the QGIS Desktop proof render (gis/proof/site01_render.png) so the 'matching QGIS Desktop' clause is comment-only, and WMTS/WFS publish is unverified in tests (WMS only).
- files: gis/test_server.py, gis/stewie_south_pole.qgz, deploy/compose.yml, gis/proof/site01_render.png, gis/build_project.py
- test_target: gis/test_server.py::test_getmap_site01_nonblank_correct_size (extend with a [REQ:QG-02] marker + a pixel-match assertion vs gis/proof/site01_render.png)

### QG-03 — epic
- goal: Build a QGIS Desktop authoring/analysis workbench over the same FastAPI backend as the web IDE: a thematic .qgz template that binds the backend STEWIE layer catalog, a Model Builder model chaining >=3 STEWIE Processing algorithms rerunnable headless via qgis_process with identical params, and a mission Analysis Profile that filters the Processing toolbox to its algorithm subset.
- acceptance: Backend serves the layer catalog a thematic .qgz binds AND returns each mission Analysis Profile's STEWIE algorithm subset, and a serialized >=3-algorithm STEWIE model round-trips byte-identical params for a headless qgis_process rerun (QGIS-free, no qgis.* import in the test path).
- current_state: partial
- files: stewie_qgis/stewie_algorithms.py, stewie_qgis/stewie_backend.py, stewie/server/routers/profiles.py, gis/build_project.py, stewie_qgis/stewie_model.py
- test_target: stewie/server/test_qg03_qgis_workbench.py (NEW; asserts /world/layer-catalog binding + profiles.py algorithm-subset filter via TestClient and the QGIS-free stewie_qgis.stewie_model >=3-algorithm chain param round-trip; mark [REQ:QG-03])

### BR-02 — epic
- goal: Add a mission-snapshot producer that, on mission completion, appends an immutable hash-chained snapshot into a Moon->Mission-000->001->N lineage that replays deterministically and can be selected as a branch parent for what-if/retrain.
- acceptance: A completed mission writes one immutable snapshot appended to a numbered lineage; that snapshot replays byte-identically (deterministic) and a new what-if/retrain branch resolves it as parent under an isolated (non-live) store.
- current_state: partial: hash-chained/replayable WorldTransaction TransactionLog (stewie/twin/envelope.py: from_journal + verify_chain, bit-exact cold-restore), deterministic MissionFlowResult producer (stewie/contracts/mission_flow.run_mission_flow), and per-mode store/branch isolation (stewie/twin/store_isolation.py) all exist / missing: no mission_snapshot object, no numbered Moon->Mission-000->001->N lineage, no producer wiring on mission completion, and no select-snapshot-as-branch-parent API for what-if/retrain
- files: stewie/twin/envelope.py, stewie/twin/store_isolation.py, stewie/contracts/mission_flow.py, stewie/twin/mission_snapshot.py
- test_target: stewie/twin/test_mission_snapshot.py (NEW; tests carry [REQ:BR-02] markers, mirroring the [REQ:...] convention in stewie/twin/test_store_isolation.py and test_envelope.py)

### MP-13 — atomic
- goal: Add a REHEARSAL-mode failure-injection stress-test module that maps a declared scenario (night-ops / comm-loss / wheel-or-sensor-failure / dust) to fault telemetry, runs it mode-gated per EG-02, and returns the classify_faults (NV-08) classification plus the executive_step (NV-09) plan response.
- acceptance: A test drives each of the 4 declared injections in REHEARSAL mode, asserts classify_faults returns the scenario's fault class and the executive's defined response fires (e.g. fail_safe/pause/relocalize/replan), and asserts the run touches no live/accepted world (LIVE / non-simulate mode fails closed per EG-02).
- current_state: partial: rehearse() MP-10 REHEARSAL mode-gate (stewie/contracts/rehearsal.py), classify_faults() NV-08 (lode/faults.py), executive_step() NV-09 (lode/executive.py), and a training-scenario SESSION library (stewie/server/test_scenarios.py: comm-dropout/battery/shadow profiles) all exist independently / MISSING the binding that injects a declared scenario as fault telemetry, runs it mode-gated in REHEARSAL, and returns classify_faults + executive_step together, plus a test driving each of the 4 injections asserting the executive's defined response fires.
- files: lode/failure_injection.py, lode/faults.py, lode/executive.py, stewie/contracts/rehearsal.py, stewie/contracts/governance.py
- test_target: lode/test_failure_injection.py::test_mp13_each_injection_fires_executive_response

### TW-12 — atomic
- goal: Add a viewshed/LOS producer that computes a terrain.los raster from the site DEM + a localization anchor, and have SN-05's visibility term consume that raster instead of marching dart.visibility.is_visible per-route.
- acceptance: A viewshed raster built from the DEM + an anchor marks each cell visible vs terrain-occluded matching dart.visibility.is_visible, SN-05's illumination_cost visibility term reads that raster (blind cells flagged, no per-route march), and terrain.los serves it.
- current_state: partial: dart.visibility.is_visible LOS march + illumination_cost's opt-in per-cell visibility march + the terrain.los catalog entry (source_class derived, planning-eligible, layer_catalog.json:164) all exist / MISSING the viewshed producer that writes the terrain.los raster and a consumer path that reads it instead of marching per-route (no drape/kind in gis_layers, terrain.los absent from the point_values order list).
- files: dart/viewshed.py, dart/visibility.py, dart/illumination_cost.py, stewie/server/gis_layers.py, stewie/server/layer_catalog.json
- test_target: dart/test_viewshed.py::test_viewshed_raster_matches_is_visible_and_sn05_consumes_it

### FL-08 — epic
- goal: Build a Fleet SCADA supervisor dashboard (live QWC2 IDE) showing every rover's own live status, battery SoC, drum-fill(bucket), health, and ETA from the real per-vehicle PlanResult/runtime telemetry.
- acceptance: A >=2-rover plan yields one supervisor row per rover, each binding that rover's OWN drum_fill_kg + eta_s + battery(min SoC) + health from totals.vehicles_detail, with no fleet-global-inventory (totals.mass_kg) fallback.
- current_state: partial: the vanilla-cockpit Fleet pane (fleet_render.js fleetPlanHTML) already binds per-rover battery(min SoC)/health/trips from totals.vehicles_detail and _rover_health (planner_multivehicle.py:661) carries feasible/min_batt_frac/health per rover / MISSING: no SCADA supervisor dashboard in the live QWC2 IDE (only single-rover MissionHUD.jsx whose drum bars read 0.0 kg), and vehicles_detail (planner_assembly.py:382) has no per-rover drum-fill or ETA field.
- files: lode/planner_assembly.py, lode/planner_multivehicle.py, stewie/server/web/assets/fleet_render.js, gis/qwc2/js/plugins/MissionFleet.jsx, stewie/server/test_fleet_supervisor.py
- test_target: stewie/server/test_fleet_supervisor.py::test_supervisor_rows_bind_per_rover_state[REQ:FL-08] (NEW)

### FS-31 — atomic
- goal: FS-31 (SSE execute-and-watch stream + Last-Event-ID resume) is already SHIPPED end-to-end; cite the existing resume test with a [REQ:FS-31] marker so the req_trace gate lets the N|N|N glyph flip to D|D|D.
- acceptance: GET /executive/run/{id}/stream returns text/event-stream legs each carrying id: <leg>; a request with header Last-Event-ID: 0 replays only legs after id 0 (leg 0 skipped, exactly len(ids)-1 events) — asserted at test_executive_stream.py:74-75.
- current_state: partial: backend endpoint + per-leg `id:` + Last-Event-ID resume shipped (executive.py:378-413), the resume test test_run_stream_resumes_from_last_event_id exists, and both EventSource consumers (cockpit.js:2528, QWC2 planAuthor.js:1955-1971) are wired / MISSING only the [REQ:FS-31] marker on the test + the PRD §7 glyph flip (row still reads N|N|N despite [SHIPPED] note).
- files: stewie/server/routers/executive.py, stewie/server/test_executive_stream.py, gis/qwc2/js/mission/planAuthor.js, stewie/server/web/assets/cockpit.js, PRD.md
- test_target: stewie/server/test_executive_stream.py::test_run_stream_resumes_from_last_event_id

### FS-32 — atomic
- goal: Add a RESEARCH/OPERATE/TRAIN persona-lens as an orthogonal routeable+persisted+shareable field on the shared workspace store, plus a pure lens->foregrounded-control-cluster map, so switching the lens re-foregrounds researcher/operator/ML-engineer panels without touching world/authority state.
- acceptance: A node:test asserts switching workspace lens (RESEARCH/OPERATE/TRAIN) changes the foregrounded panel set AND round-trips via toQuery/hydrateFromQuery (shared link restores it), while site/body/mission/source stay unchanged.
- current_state: partial: routeable+persisted+shareable workspace store (workspace.js KEYS site/body/mission/profile/source + hydrateFromQuery/toQuery/subscribe, the FS-25/FR-01 substrate) + lane/foreground vocabulary (programBoard.js GIS_LANES/LANE_GROUPS) + the 3-lens design spec (design/STEWIE_world_state_mission_console_2026-07-08.md) all EXIST / MISSING: no `lens` field in the store, no RESEARCH/OPERATE/TRAIN->foregrounded-cluster map, no consumer that re-foregrounds panels off the lens.
- files: gis/qwc2/js/mission/workspace.js, gis/qwc2/js/mission/lens.js, gis/qwc2/js/mission/programBoard.js
- test_target: gis/qwc2/js/mission/lens.test.js (NEW node:test, header marker [REQ:FS-32])

### DT-06 — atomic
- goal: Add the missing [REQ:DT-06] acceptance test proving the /world observed-twin read takes (mask, heights, version) as one atomic triple under state._RESYNC_LOCK, so a concurrent /twin/resync can never yield a torn pre-/post-resync read (the lock + read-side and write-side critical sections already exist).
- acceptance: A /world (terrain_view) observed read issued concurrently with an in-flight /twin/resync write returns one self-consistent (mask, heights, version) triple, never a torn mix of pre- and post-resync state.
- current_state: partial: _RESYNC_LOCK (state.py:49) is held on the read that composes the (mask, heights, version) triple (state.py:86-90) AND across the resync apply_patch..commit..compensate write (twin.py:76-95), and a lock-HELD proxy test exists (test_current_terrain_view.py:40) / MISSING a [REQ:DT-06]-marked test that drives a genuinely concurrent resync and asserts no torn triple (no DT-06 marker exists anywhere), and world.py:_site_enrichment reads observed_mask() unlocked (line 257).
- files: stewie/server/test_current_terrain_view.py, stewie/server/state.py, stewie/server/routers/twin.py, stewie/server/routers/world.py
- test_target: stewie/server/test_current_terrain_view.py::test_current_terrain_view_reads_the_twin_under_the_resync_lock (extend: add the [REQ:DT-06] marker and strengthen from a lock-held proxy to a real concurrent-resync torn-read assertion on the composed triple)



## DEM-viz + GIS-architecture fold dispatch briefs (2026-07-08)

Briefs for the 6 §7.B rows added folding Aaron's multi-level DEM viz + QGIS/QGIS-Server/QWC2/OpenLayers+Three.js architecture vision (design/STEWIE_multilevel_dem_viz_design_2026-07-08.md). Parser scripts/fanout_plan.py assessment_inventory reads `### ID` + `- files:` + `- test_target:`.

### GW-11 — atomic
- goal: A Three.js 3D terrain panel INSIDE the QWC2 /ide (not only the cockpit), rendering the selected site's real DEM window synced to the 2D GIS map (click-3D -> map coord, 2D-authored feature -> visible in 3D, 3D pick -> same order-frame serializer).
- acceptance: Playwright opens the 3D panel, picks a point, the 2D map centers on the returned IAU_2015:30135/selenographic coord; a 2D-authored keep-out renders in 3D within one refresh.
- current_state: three3d.js (659 lines, Three.js r170) already ships in the cockpit (stewie/server/web/index.html:1563) with orbit/pick/shadows/drape over /dem/heightfield; the QWC2 IDE has NO three.js (no `three` in gis/qwc2/package.json). This is a PORT + 2D<->3D sync contract, not a new renderer.
- files: gis/qwc2/js/plugins/Mission3D.jsx, stewie/server/web/assets/three3d.js, stewie/server/routers/dem.py
- test_target: gis/qwc2/js/mission/terrain3dSync.test.js

### GW-12 — atomic
- goal: One named, tested planet-fixed-authoritative + local-render-origin coordinate contract so every renderer (cockpit 3D, /ide 3D, Cesium globe, Godot) renders float32-relative to a local origin and converts back through site_dem.py before persisting (never storing a renderer-local frame).
- acceptance: a [REQ:GW-12] test asserts coordinate round-trip error under 1 cm at the 30135 theme-extent corners, each site anchor, and an ad-hoc tile center; the largest magnitude handed to a float32 path stays under a documented ulp bound.
- current_state: 30135/30100 authoritative + per-site order-frame transforms already centralized in site_dem.py:211-266; convert-back-on-save exists in planTools.js:99-115; single-precision safety is currently only IMPLICIT (windowed <=640 m crops), never stated or tested.
- files: stewie/terrain/site_dem.py, gis/qwc2/js/mission/planTools.js
- test_target: stewie/terrain/test_coord_contract.py

### LY-05 — atomic
- goal: DEM-derivative analysis rasters aspect + curvature + a standalone roughness drape + real contour vectors, joining the existing 16 _GLOBE_KINDS as real producers with legends, registered in the LY-01 catalog.
- acceptance: each new kind renders via /layers/globe/{kind}.png + bbox on a real site, appears in the /ide layer tree with a legend, and a test asserts aspect/curvature values on a real-DEM fixture crop (no synthetic).
- current_state: slope/hillshade/illumination/psr/cost etc. already produced in gis_layers.py:316-400; aspect/curvature/contours have NO producer (grep); roughness exists only inside the costmap sum (lode/costmap_layers.py:70-78), not as its own drape; base.contours is catalog-only.
- files: stewie/server/gis_layers.py, stewie/server/routers/layers.py, gis/build_project.py
- test_target: stewie/server/test_derivative_rasters.py

### LY-06 — atomic
- goal: A real line-of-sight / comms-visibility producer for the catalog-only terrain.los/terrain.comms: observer point + mast height -> horizon-marched visibility raster + point queries, reusing the dart illumination horizon machinery.
- acceptance: a [REQ:LY-06] test asserts a cell behind a ridge from the observer is not-visible and a same-slope open cell is visible, on a real DEM crop.
- current_state: terrain.los/terrain.comms are catalog-declared with no producer; the horizon-march core exists in the illumination/psr path (gis_layers.py:363+) and is the reusable basis.
- files: stewie/server/gis_layers.py, stewie/server/routers/layers.py
- test_target: stewie/server/test_los_layer.py

### LY-07 — atomic
- goal: A signed terrain-change / dig-fill-depth drape (base DEM minus as-built/observed compose) with a diverging cut/fill legend + per-cell depth readout, the visual producer for the catalog rows map.changed_terrain + evidence.before_after_dem.
- acceptance: after a conserved cut+fill transaction on a real site the drape shows the cut region negative and the berm positive with depths matching the transaction volumes; [REQ:LY-07] test.
- current_state: the difference DATA exists (stewie/twin/terrain_view.compose_terrain_view + /world/terrain_view + /dem/asbuilt) but no signed-difference drape is registered in _GLOBE_KINDS; the two catalog rows are unproduced.
- files: stewie/server/gis_layers.py, stewie/twin/terrain_view.py, stewie/server/routers/layers.py
- test_target: stewie/server/test_change_drape.py

### QG-04 — atomic
- goal: Prove (or honestly retract) QG-02's WFS + WMTS legs on the --profile gis QGIS Server, completing its "WMS/WMTS/WFS" claim which today has WMS-only evidence.
- acceptance: gis/test_server.py asserts WFS GetCapabilities lists the site vectors + GetFeature returns them in IAU_2015:30135, and WMTS GetCapabilities advertises a lunar-CRS tile matrix + GetTile returns a pole-truthful tile (or the WMTS leg is recorded infeasible on the pinned version with a reason); skip-clean when no server is up.
- current_state: gis/SERVER.md proves WMS 1.3.0 GetMap byte-identical to Desktop; WFS/WMTS are NOT proven though QG-02's text claims all three; the only WMTS in-tree is the consumed NASA Trek WMTS (deferred for a CRS reason, build_project.py:258-294).
- files: gis/test_server.py, gis/SERVER.md
- test_target: gis/test_server.py


## AUTODIG + sensor-ingest fold dispatch briefs (2026-07-08)

### AD-01 — atomic
- goal: AUTODIG autonomous-excavation controller (torque-regulated dig/bite/drum/lift/dump/traverse) beneath the berm FSM.
- acceptance: torque regulates to a setpoint across densities, cut-depth bound respected, stall abort, offload handoff, emits the AD-02 effort log.
- current_state: AUTODIG documented (docs/vehicle_ipex.md) not coded; cycle FSM lode/berm_fsm.py + cut-depth bound system_profile.py exist; no torque-regulated dig controller.
- files: stewie/lode/berm_fsm.py, stewie/physics/excavation_state.py, stewie/specs/system_profile.py
- test_target: stewie/physics/test_autodig_controller.py

### AD-02 — atomic
- goal: per-actuator electrical observables (I,V,tau,P,E) synthesized from conserved effort, generalizing DrumSensor, on the truth-firewalled proprioception channel.
- acceptance: two regolith densities give distinguishable I/V/tau/P/E logs whose energy reconciles with dig_energy_per_kg.
- current_state: drum current modeled (rassor_mass_model.py), tau is an input slot only, V/P schema validated (proprioception) but no producer.
- files: stewie/physics/rassor_mass_model.py, stewie/bridge/proprioception_io.py
- test_target: stewie/physics/test_actuator_observables.py

### AD-03 — atomic
- goal: inverse effort-proxy estimator: excavation-effort residual -> observed rho_eff/R_dig/k_terrain/E_specific with uncertainty into EG-08; distinct from the forward excavation_resistance drape.
- acceptance: seeded dense pocket -> a localized accepted belief update the next plan re-costs over; typed proxy=True, never surfaced as density.
- current_state: reconciliation_step.py + EG-08 fully exist; ML-05 excavation_state.py fuses effort; no k_terrain estimation; physics.excavation_resistance catalog entry (layer_catalog.json:362) is a FORWARD drape (mislabel tracked by task #53).
- files: stewie/contracts/reconciliation_step.py, stewie/physics/excavation_state.py, stewie/server/layer_catalog.json
- test_target: stewie/physics/test_effort_proxy_estimator.py

### IN-01 — atomic
- goal: live ROS2 Sensor Ingest Node routing sensor topics through the existing validation gate into the estimators.
- acceptance: a replayed bag feeds the mapper + AD-03; malformed messages rejected legibly; truth-denial holds.
- current_state: /cmd_vel in + odom out (ros2_bridge.py) + one PointCloud2 sub; the gate exists file-mediated (sensor_io.py truth firewall + PM-01, proprioception_io.py validation, frames.py single TF site); no general live sensor-topic ingest node.
- files: stewie/bridge/ros2_bridge.py, stewie/bridge/sensor_io.py, stewie/bridge/frames.py
- test_target: stewie/bridge/test_sensor_ingest_node.py

### IN-02 — atomic
- goal: closed tier {raw,derived,belief,world,mission} on every LY-01 entry + twin surface with promotion enforcement.
- acceptance: a raw-tier layer marked planning-valid fails validation; promotion only advances raw->derived->belief->world via EG-08.
- current_state: 66-layer LY-01 catalog source_class approximates the tiers but is free-form + unenforced (layer_catalog.json); GW-03 eligibility exists (verify JS enforcement before scoping).
- files: stewie/server/layer_catalog.json, stewie/server/routers/layers.py
- test_target: stewie/server/test_layer_tier_enforcement.py
