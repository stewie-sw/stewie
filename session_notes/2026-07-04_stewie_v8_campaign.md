# STEWIE v8 campaign — 2026-07-04

An autonomous `/loop` session drove the **v8 "Cleanup / Optimize / Harden / Complete" campaign PRD**
(`design/STEWIE_PRD_v8_2026-07-04.md`, local-only) over the §7 requirement matrix, plus the gate-wiring
follow-up from earlier the same day. Method throughout: screen live code → TDD `[REQ:ID]` → full gate (row
test + server-import smoke + FULL mypy + req_trace + assessment + broad regression) → newline-preserving glyph
flip → post-flip req_trace + row-count check → regen all 3 artifacts → gated branch→main ff push. Never a
fake-promote; never fabricated data or a source.

## Board

**195 → 224 / 315 V=D (74% in-scope)** this arc. Per-priority at exit: **P0 93/102, P1 127/178, P2 4/33,
P3 0/2.** `origin/main` = `6cc5955`, every push CI-jobs-green.

## What landed

**Gate-wiring (earlier 2026-07-04) — the delivered contracts now ENFORCE in the live flow:**
- EG-07 audit → `/executive/release-plan` + `/run` append a tamper-evident hash-chained record; `GET
  /executive/audit` exposes the chain.
- MP-07 → `/executive/run` reports the 8-precondition plan-executability card (derived from real run state).
- EG-08 → the run reconciles budgeted-vs-slip-truth energy against the estimator's own sigma → proposals.
- EG-05 → mints a signed LiveExecutionToken when all 6 §29.5 preconditions hold (refused + reason if safed).
- **PX-02** → mission `physics_backend_id` (fail-closed on the not-yet-conserving Chrono oracle) +
  `GET /physics/backends` (EG-12 model ledger: validated/frozen/deprecated).

**Wave 0 (restore green):** W0-1 fixed the CI-red AS-15 B905 ratchet (31→29, correct `strict=` on the 2 new
fan-out zips). W0-2 = the dirty `planner_model.py` was the PX-02 schema half (finished, not dropped). W0-4
pruned 12 fully-contained `ui/*-integration` branches (61→49; rollback map saved).

**Wave 1 (drift cleanup):** C-1 (PRD header 188→315 + live-artifact pointer), C-3 (every dead CONFIG.md
module path → the real `stewie.*`, each verified to import/run), C-4 (dead manifest path), C-5 (wrapper
CLAUDE.md fresh banner), C-9 (gitignore `out/`, committed load-bearing design docs). **Ledgered:** C-2
(dup §7.13–7.18 section numbers — parser-safe but real prose cross-refs make a mechanical renumber risky),
C-6 (6 `[CALIB]/[ASSUMPTION]` constants — honest documented placeholders awaiting real data/model/external
input, not fabricatable).

**CI optimization (Aaron directive) — diagnosed, not faked:** applied a BLAS thread-cap + a concurrency-cancel
(both kept as hygiene), but the honest measurement proved **neither moved the wall-clock** — the ~25-min CI
is **runner-queue time**, not test execution (every job, incl. trivial `node --test`, shows ~24 min because
GitHub stamps `startedAt` at enqueue; real exec ~1–2 min). Root cause = runner availability / concurrent-job
quota (infra/billing), which code cannot fix. **Real fix is Aaron's call:** a self-hosted runner on the
32-core box (biggest win) / fewer parallel jobs (drops a Python version = coverage tradeoff) / larger paid
runners.

**Wave 2 (harden) — COMPLETE; the v8 "BP-03/04/06 closed" success criterion is MET:**
- BP-03: prod (`STEWIE_TLS_TERMINATED=1`) fails loud without a standalone `STEWIE_SESSION_SECRET`; rotation
  semantics proven (API-key rotation leaves sessions valid; session-secret rotation resets them) + documented.
- BP-04: prod fails closed on the built-in allowlist (requires explicit `STEWIE_ALLOWED_OPERATORS`); a
  built-in staff email is denied; `/healthz`+`/config` surface the degraded "on built-in defaults" posture.
  (mypy caught a real `_auth` parameter-shadow bug in config.py, fixed.)
- BP-06 + SE-02: the training operator view is now authenticated (a leaked session id no longer grants
  truth-denylisted telemetry; truth-denial demoted to defense-in-depth). Updated the 3 existing session tests
  that spoke the old open contract.
- H-5: AS-15 ratchet promoted to a NAMED CI step (independent of the pytest wrapper).
- H-6: **verified NON-BUG in-container** — the gpu_lidar `/points` suffix already matches the bridge topic;
  the v8 static read missed the Gazebo convention. "Fixing" it would have created the mismatch. No change.

## The honest ceiling (why the loop stopped here)

The success criteria (P0 102/102, P1 ≥170/178) are **not met**, and the gap is structural, not laziness:
- The **9 open P0s are the React rewrite lane** (AC-01/02, RF-01/02, GL-01, MG-01/02/04) + **AS-04** — all
  frontend (D1, Aaron's scope) or the off-limits AS lane.
- The **51 open P1s** are: the frontend React/GeoLibre track (FR/RF/GL/DW/BD/TU); honestly-partial rows
  blocked on features/data that don't exist (e.g. PO-09 cross-version migration would need a fabricated
  legacy fixture — forbidden); high-blast migrations (MT-01 DEM externalization — git-rm 225 MB of
  test-depended fixtures + history rewrite, needs sign-off); doc-heavy bundles (MT-05 ADRs); and ROS/GPU/
  hardware rows (Wave 5).
- **No fake-promote-free quick flips remain.** The `V=P` rows are honestly partial for real reasons.

## Decisions this needs from Aaron

1. **D1 — the frontend React/GeoLibre rewrite scope** (the biggest lever: it's most of the open P0 + a chunk
   of P1). The loop deliberately did NOT auto-start it (D1 default is web-first React, wrapper-agnostic).
2. **CI runner infra** (self-hosted on the 32-core box recommended).
3. **MT-01 DEM externalization** sign-off (removes 225 MB tracked fixtures; implies a history rewrite).
4. **D2/D3** — the Wave 6 vision/packaging scope (defaults: PKG-only after Wave 4, vision proposal-first).
5. **Wave 5 ROS/hardware** — some is CPU-verifiable in the on-host ros:jazzy container; GPU-render rows
   segfault on mesa in-container (need the NVIDIA EGL container config or real hardware).

## Deploy

`app.stewie.space` redeployed to `6cc5955` (224 board) with the Wave-2 security hardening + the /executive
attestations + /physics/backends live. Rollback tags staged (`stewie-{backend,frontend}:rollback`).
