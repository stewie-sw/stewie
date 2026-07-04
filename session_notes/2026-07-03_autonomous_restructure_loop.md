# Autonomous STEWIE platform-restructure loop — 2026-07-03

A self-paced unattended loop (charter: `docs/autonomous_loop_charter_2026-07-03.md`) drove the platform
restructure + governance/planning build across 10 wakes, one gated row per wake, on branch
`feat/platform-restructure`. Method per row: screen the live implementation → TDD (`[REQ:ID]` test first) →
implement (real data only) → full gate (row test + req_trace + assessment + check_deps + ruff + mypy + broad
regression; Docker build for packages; Playwright for UI) → flip the glyph on green → commit → regen snapshot.

## Rows landed (10)

| Wake | Row | Commit | Result |
|---|---|---|---|
| 1 | PX-06 | 1b9b64b | Broke `terramechanics → stewie.specs.constants`; forge-local defaults + config-overlay re-injected at call time in `body_params` (byte-identical, more robust for overrides). |
| 2 | PO-18 | c30d6f2 | Extracted **stewie-forge** (terramechanics + bearing + PhysicsBackend protocol; numpy-only). backend.py split protocol→forge / Tier2→core; shims verbatim. Docker build rc=0 + in-container smoke passed. |
| 3 | DE-01 | f106454 | **Demo 001** end-to-end vertical slice from existing code: body → conserved backend → plan → conserved twin txn → RegolithVolumeEstimate → deterministic artifact. Real dig 3528 kg, conserved_err ~2.7e-11. |
| 4 | EG-01 | cf9072e | `EnvironmentMode` enum + per-mode authority matrix (§29.1) in `contracts/governance.py`. |
| 5 | EG-02 | 64ed122 | Central enforcement (`require_authority`/`permits`/`ModeAuthorityError`); wired the command-real-robot gate in `command_eligibility` (matrix-driven, byte-identical). |
| 6 | EG-03 | 6646ee4 | DB/branch isolation by mode (`twin/store_isolation.py`) — minimal directory-namespace over the file store; only LIVE → the live store. |
| 7 | EG-05 | b16c12e | Training-to-live gate + live-execution token (`contracts/live_gate.py`); separate from EG-02. |
| 8 | EG-06 | 93b632b | Command-safety pipeline (`bridge/command_pipeline.py`) + the single-ROS2-egress invariant, test-guarded. |
| 9 | EG-11 | 5a29800 | Safety-control layer (`runtime/safety_limits.py`) — all sourced limits (V_CAP 0.5, slope 20°, obstacle 0.075m, dig 0.50, battery 0.10, comms 2.0s); e-stop, comms-loss safe. |
| 10 | MP-07 | c4d6ae5 | Plan-executability gate (`contracts/plan_gate.py`) — the 8 §30.3 preconditions; planning-domain mirror of EG-05. |

Prior same-session rows (before the autonomous loop, on the same branch): BD-04, PX-04, PX-05, AP-01, PO-16,
PO-17 (edge-breaks + workspace + stewie-bodies extraction), plus the `/program` board phase-grouping rewrite,
PRD §29/§30 + EG/MP lane additions, and the docs sweep.

## /program deploy (Aaron-requested, mid-loop)

Built + deployed the branch to **app.stewie.space** (backend + frontend images). Verified: backend healthy on
the new image, `/program` live at 315/193 phase-grouped, restructure endpoints 200, board JS fresh
(cf-cache MISS), zero JS errors. Rollback tags: `stewie-{backend,frontend}:rollback` (= old main `7247d94`).
**Prod now runs the unmerged branch build (a0c98d3); rows after that — EG-11, MP-07 — are branch-only until a
re-deploy.**

## Branch state → MERGED

- **57 commits** merged to `origin/main` (fast-forward `7247d94 → 2c22e83`, 2026-07-03, on Aaron's "merge now").
- Board: **195 / 315 rows done (67.2% in-scope)**. All per-row local gates green.
- Prod (app.stewie.space) = the `01d8407` build (deploy-refreshed; EG-11 + MP-07 live at 195/315).

## Merge + CI reconciliation (the push surfaced pre-existing repo debt)

Pushing the branch surfaced CI failures the per-row LOCAL gates structurally could not catch. Restructure/
loop-caused (all FIXED + pushed):
- **wheel smoke** (`4edf1d6`): clean-venv wheel didn't include the extracted packages → build+install all 3 wheels.
- **full-tree mypy** (`ed6c392`): the `import *` shims were unresolvable by `mypy` (no `__all__`) → explicit re-exports + `__all__` in the terramechanics/bearing shims. LESSON: run the FULL `mypy` (no args), not per-file — per-file misses cross-module attr-defined errors.
- **deploy-hardening** (`03a73f4`): the Dockerfile app-install string changed (`--no-deps packages/… .`) → updated the SEC-05 assertion.
- **s3li artifact** (`03a73f4`): the frozen `s3li_crater_vo_dem_anchor_2026-06-28.json` (SL-01) was never committed → committed (5.7 KB).
- **STATUS.md/STATUS.json/release_manifest** (`2c22e83`): the loop regenerated `program_snapshot.json` each row but not these → regenerated (manifest gen needs the venv, imports `stewie_bodies`).

**Pre-existing, shared with `main` (NOT fixed — a governance call):** `test_release_gate` catches **AS-04 =
V=D without recorded container evidence** (not in `CONTAINER_EVIDENCE_VERIFIED`, not host-tier). The AS-04 flip
(`7ecf0ed`) is a `main` ancestor; **`main`'s own CI had been red 10+ h** on the same 3 jobs (from concurrent
FR/BA/AS work). Merging did NOT introduce this — it's an AS-lane (Codex) firewall issue. Un-flip AS-04 (no
evidence → not V=D) or record its container evidence is the resolution; deferred to the AS-lane owner / Aaron.

## Noted integration follow-ups (all `[REQ:]`-cited, delivered-but-not-fully-wired)

- **EG-02**: `modify_accepted_world` enforcement at the write sites (`world_state.record_terrain/record_plan`) — they carry no mode yet (EG-03 territory).
- **EG-03**: thread the active session mode into every `WorldStateService`/router call site (the resolver + guard are done).
- **EG-05**: thread the live-execution token through `/executive/run` (mint on RELEASED, present at command lowering).
- **EG-06**: already wired (`rc.py` lowers only via `command_eligible`; single egress guarded).
- **EG-11**: call `check_within_limits` inside `command_pipeline.lower_command`.
- **MP-07**: derive `PlanPreconditions` from the real `PlanResult`/executive state in `plan()` / `/executive/run`.

## Remaining backlog (not on-host-P0)

P1 governance/planning rows (EG-04 roles, EG-07 audit, EG-08 reconciliation, EG-09 service separation, EG-12
physics-model control; MP-05/06/08/09/10/11 planning engine); P2 EG-10 admin taxonomy, MP-12 UI panels; the
frontend GeoLibre lanes (RF/GL/DW/AC/TU/MG) which need the React rewrite; the deferred packaging rows'
integration follow-ups above.

## Status of the 1-2-3 (done)

1. **Reconcile branch ↔ main** — DONE. Fast-forward merge `7247d94 → 2c22e83` pushed to `origin/main` (57 commits).
2. **Deploy refresh** — DONE. app.stewie.space rebuilt to `01d8407`, live at 195/315, backend healthy, rollback tagged.
3. **Continue the loop into P1** — IN PROGRESS (governance/planning P1 rows, one per wake, on the branch).

## Open for Aaron / the AS-lane owner

- **AS-04 firewall (blocks a green CI on both branch and `main`)**: resolve AS-04's V=D — un-flip it (no recorded container evidence → not V=D) or record its real container evidence in `CONTAINER_EVIDENCE_VERIFIED`. This is the last thing between `main` and a green build; it predates + is outside the restructure.
- **Integration follow-ups** (the delivered governance gates wired into the live `/executive/run` flow) — see the list above.
