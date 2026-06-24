# Changelog

All notable changes to STEWIE are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

`0.x` is pre-release: STEWIE is a trainer/simulator surface plus a navigation
simulation + mission-planning platform, not a production flight-autonomy release (see PRD §0). The
exported version lives in `stewie.__version__` and `pyproject [project].version`;
`stewie/server/test_version.py` keeps them in lockstep (PO-13).

## [Unreleased]

### Added
- DT-02: least-privilege `/twin/version` (authenticated minimal version token) +
  director-only `/twin/history` audit route, replacing the unauthenticated
  full-history read.
- `dart/render_traverse.py`: the render→cue→fuse→score SLAM-seam adapter
  (stereo-VO + articulation-parallax extractors → `run_integrated_slam` →
  ATE-vs-truth), validated on committed renders and a fresh bounded Godot
  render (parallax fused beats odometry on a turning traverse).
- Cockpit Plan 3D: first-person fly/move-through camera and a 3D plotting
  toolbox (live coordinate readout, plotted coordinate markers, 3D measure).
- PO-13: `CHANGELOG.md` + exported `stewie.__version__` + SemVer policy (`docs/RELEASE.md`) + a
  **release-evidence manifest** (`release_manifest.json` via `scripts/gen_release_manifest.py`,
  aggregated from the live tools — req_trace / release_gate / SBOM / dep-lock / version, no hand
  numbers; `--check` CI staleness gate; `--full` writes commit + live coverage at release time).
- CP-04: the compiled MO-01 acceptance tolerance is now exercised on the live REHEARSE path
  (`lode.resync.forward_compare`, via `POST /executive/advance`), surfacing the as-built verdict
  (`as_built_pass` + the compiled tolerance) per candidate.
- SN-05: the separable per-term route cost (slope + the illumination sub-terms shadow / saturation /
  map-uncertainty / visibility) is surfaced on the live FS-05 nav spine (`lode.nav_pipeline.run_navigation`)
  and `POST /nav/run`.
- PRD §27: dated actionable execution backlog + a 10-working-day sprint + a full-fidelity UI
  overhaul summary (new IDs `OPS-`/`MO-`/`TR-`), from the 2026-06-20 architecture + mission-ops reviews.
- `docs/ui_overhaul_plan_2026-06-20.md` (full-fidelity cockpit overhaul plan) and
  `docs/architecture_review_2026-06-20.md` (this review); both added to the docs nav.

### Changed
- Cockpit reorg (landed + deployed): the cockpit nav is reorganized into the decided 6-slot ConOps spine
  **Plan · Rehearse · Validate · Release · Execute · Report** (+ a role-gated secondary cluster Fleet /
  Construction / Models / Trainer), and the Plan sidebar is consolidated **7 groups → 4** (Site / Contents /
  Rovers / Plan, with the old Feasibility + Catalog folded into Plan as sub-steps and Telemetry moved to the
  Execute context). **Validate** merges the former Navigation + Perception tabs into one tab with a
  Navigation|Perception sub-tab strip (reusing the existing panes). **Release** is a new director-gated
  mission-sign-off surface: `POST /executive/release-plan` builds a `MissionIntent` from the current build
  queue (the new `lode.mission_intent_compiler.intent_from_orders`) and drives it through the MO-02 lifecycle
  to RELEASED. To make this faithful, the MO-01 `Objective` gained an additive `order_kind` (cut|fill|sinter,
  default cut) and `compile_intent` now honors it, so the full plan vocabulary round-trips — no order is
  dropped or faked (non-build path waypoints are surfaced as skipped). A reusable interactive verification
  gate (`scripts/cockpit_interactive_check.py`) asserts the wiring a screenshot can't. Deployed live to
  app.stewie.space (CI green; `?v=` cache-bust confirmed). Spec: `docs/cockpit_reorg_plan_2026-06-23.md`.
- ARCH-2: `lode/mission_planner.py` decomposed from a ~2110-line god-module into a **448-line facade**
  re-exporting **10 dependency-ordered leaf modules** (`planner_constants` / `planner_model` /
  `planner_routing` / `planner_balance` / `planner_multivehicle` / `planner_endurance` / `planner_trips` /
  `planner_sim` / `planner_optimize` / `planner_assembly`, + the earlier `planner_views` / `planner_acceptance`).
  Every public symbol stays byte-identical via facade re-export; the former lode↔planner_views import
  cycle is broken via `planner_constants`.
- FL-03: the shared charger and all declared shared resources (pit/dump/vantage/corridor) are now
  scheduled **jointly** (`lode.planner_multivehicle._resolve_joint_resources`) — one per-vehicle delay
  clock advanced over a single event calendar, every contended segment admitted against ONE multi-server
  `ReservationLedger` — so the multi-vehicle makespan/waits are the real coupled FCFS schedule rather than
  a sum of independent per-server estimates (which double-counted a rover queued in two resources at once).
  A no-declared-resource fleet reduces to the prior charger-only queue (byte-identical). FL-02 crowding and
  FL-04 cross-vehicle precedence remain separate fixed-point resolvers folded on top.
- `stewie/godot/render.sh`: documented the working sensor-capture recipe
  (never `--headless`; run `res://sidecar.tscn` with `--layers …,rover`).
- PRD §4.2 (release blockers) and §19.1 (requirement census) reconciled: RB-01..06 are cleared in
  code with citing tests; the 112-row census is superseded by the live ~186-row matrix tally
  (33 DONE / 39 IXV-done / 73 partial / 41 open-or-gated). Per-row matrix glyph closure is scheduled
  as OPS-04 (the `[REQ:]` marker pass), not hand-flipped, to keep `req_trace` CI honest.
- Execution plans (`design/STEWIE_UNIFIED_EXECUTION_PLAN.md`,
  `design/STEWIE_ATOMIC_EXECUTION_PLAN_2026-06-09.md`) point to the PRD §27 sprint and reconcile the
  stale intern-beta checkboxes (bridge/deploy shipped + container-verified; live rclpy node still gated).
- README Python support corrected to 3.11–3.13 (the 3.10 leg was dropped; `requires-python>=3.11`).

## [0.1.0] — pre-release baseline

Initial tagged baseline of the consolidated monorepo (`code/`): the conserved
NumPy terrain authority, the LODE mission planner (multi-algorithm optimizer,
multi-vehicle, plan IR, PDF report), the DART perception/Navigation estimator spine,
the FastAPI server + cockpit (Plan/Navigation/Perception/Metrics/Report,
auth/role ladder, GIS globe), the ROS2 bridge seam, and the Gymnasium env suite.
See PRD §0 for the authoritative status model and release blockers.
