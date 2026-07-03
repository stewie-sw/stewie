# Autonomous restructure loop — charter + state (2026-07-03)

The persistent memory + guardrails for the unattended STEWIE platform-restructure loop. Each wake reads this,
does the NEXT buildable row, updates the progress log, commits on the branch, and re-schedules. Configured
with Aaron 2026-07-03 (three decisions recorded below). Branch: `feat/platform-restructure`.

## Decisions (locked with Aaron)

1. **PX-06 approach = PRESERVE OVERLAY (inject).** `terramechanics` carries forge-local literal geotech
   defaults; the `stewie.specs.config` overlay path is PRESERVED by injecting config-overlaid values at the
   stewie-side call sites (dependency inversion). Runtime behavior byte-identical. `stewie-forge` ends up
   importing no `stewie.specs.constants`.
2. **Scope = RESTRUCTURE FIRST, THEN BROADEN.** Order: PX-06 -> PO-18 -> DE-01, then continue into the other
   on-host-buildable P0 rows (EG governance, MP planning, etc.). SKIP genuinely gated rows (need a live pit /
   real hardware / a physical GPU / external LAC-IPEx geometry) and pure-frontend rows that need the GeoLibre
   rewrite. Continue until the on-host-buildable P0 queue is dry, then report.
3. **Guardrails = BRANCH-ONLY, VERIFY, SURFACE ON BLOCKER.** See Hard stops.

## Per-row protocol (every row, no exceptions)

1. SCREEN the live implementation before any TDD (the row may be partially built; matrix "V != D" is often
   integration-partial, not missing).
2. TDD: write the `[REQ:<ID>]` test first (must fail), then implement, run it green. Real data only, no
   stubs/synthetic/placeholders. If real data/impl is unavailable, STOP and record a blocker.
3. FULL GATE green before flipping the glyph: `scripts/req_trace.py` + `scripts/test_assessment_gate.py` +
   `scripts/test_check_deps_lock.py` + the row test + `ruff` + `mypy` + a broad regression over the touched
   areas.
4. For a PACKAGE extraction (PO-18): also run a real `docker compose -f deploy/compose.yml build backend` +
   an in-container import smoke (the PO-17 pattern) before flipping.
5. For a UI/board row: verify via real-Chrome Playwright (runtime venv python has playwright; chrome at
   /usr/bin/google-chrome), screenshot + assert, before flipping. Re-stamp `?v=` after any `.js` edit.
6. COMMIT PRD before `gen_program_snapshot.py` (it reads `git show HEAD:PRD.md`). Flip the glyph N->D only on
   a fully green gate. Commit on the branch. Regen + commit the snapshot.
7. Update the progress log below (append one line). Re-schedule the next wake.

## Hard stops (NEVER do these unattended)

- NEVER `git push`, deploy, merge to `main`, `rclone`/gdrive, or `rm`/delete anything.
- NEVER integrate a subagent's unverified "done" — re-run the cited gate yourself.
- NEVER flip a glyph on a red or unrun gate; NEVER fake-promote.
- NEVER silently change behavior (e.g. drop the config overlay) — preserve it or record the decision.

## Surface + STOP conditions (record to this file's Blocker log, then wait)

- A genuine blocker (missing real data/impl, a gated resource, an external dependency).
- A design fork that needs Aaron's call (like the PX-06 overlay decision was).
- A red gate the loop cannot self-fix within the row.
- A regression the loop caused that it cannot cleanly revert.

On any of these: revert to the last known-good commit if the row broke something, append to the Blocker log,
and stop scheduling (wait for Aaron).

## Queue (ordered; updated as rows land)

1. **PX-06** — break `terramechanics -> constants` (inject, overlay-preserved). NEXT.
2. **PO-18** — extract `stewie-forge` (bearing + terramechanics + PhysicsBackend + body_params), bodies+numeric
   only, shim, Docker-verified.
3. **DE-01** — Demo 001 vertical slice (body/profile -> backend -> plan -> conserved txn -> reconcile ->
   report), deterministic, `[REQ:DE-01]`.
4. **P0 broaden** (on-host-buildable, screen each first): EG-01/02/03/05/06/11 (governance modes/enforcement/
   DB-isolation/live-gate/command-safety/safety-layer), MP-07 (plan-executability gate), then any other
   non-gated non-pure-frontend P0.
5. Report when the on-host-buildable P0 queue is dry.

## Progress log

- 2026-07-03 f28e2a9 — loop CONFIGURED (PX-06 row + brief added; charter written). Queue seeded. First wake = PX-06.
- 2026-07-03 1b9b64b — PX-06 DONE (wake 1). terramechanics->constants edge broken: forge-local literal defaults +
  config-overlay re-injected at call time in body_params.params_for_body (byte-identical, more robust for
  overrides). Fixed the one caller reaching constants via terramechanics.K (lode/costmap_layers.py). TDD 3/3;
  byte-identical regression green (physics+lode+specs+forge+dart+leap+runtime); ruff+mypy+req_trace+assessment
  +check_deps green. Note for PO-18: body_params STAYS in stewie-core (imports stewie.specs.constants for the
  overlay); split the PhysicsBackend protocol (-> forge) from the Tier2 concrete (-> core). NEXT = PO-18.
- 2026-07-03 c30d6f2 — PO-18 DONE (wake 2). stewie-forge extracted: terramechanics + bearing + the
  PhysicsBackend PROTOCOL -> packages/stewie-forge (numpy-only; concept API estimate_sinkage /
  estimate_bearing_capacity); backend.py SPLIT (protocol->forge, Tier2NumpyBackend->core); verbatim shims at
  the old paths. Docker build rc=0 + in-container smoke PASSED; byte-identical regression green
  (physics+lode+specs+forge+dart+leap); CI x4 install; ruff+mypy+req_trace+assessment+check_deps green.
  PACKAGING PHASE COMPLETE (stewie-bodies + stewie-forge both extracted, shimmed, Docker-verified). NEXT = DE-01.
- 2026-07-03 f106454 — DE-01 DONE (wake 3). Demo 001 vertical slice (scripts/demo_001.py) composes the platform
  loop from EXISTING code: body(moon) -> conserved PhysicsBackend -> plan(mission_planner) -> conserved
  execution + world/terrain-memory txn (mission_terrain_delta + WorldStateService) -> RegolithVolumeEstimate
  reconcile (siteplan_volume_evidence) -> deterministic evidence artifact. A real IPEx dig moves 3528 kg,
  conserved_err ~2.7e-11. [REQ:DE-01] 2/2 (every-stage payload + determinism); additive; gate green. RESTRUCTURE
  BACKBONE COMPLETE (edges + packaging + demo). NEXT = P0 BROADEN, starting EG-01 (EnvironmentMode enum +
  authority matrix). Screen for an existing runtime_mode/env concept first (BA-11 authority tuple has one).
