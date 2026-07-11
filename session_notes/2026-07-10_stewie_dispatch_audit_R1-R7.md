# STEWIE dispatch-agent audit remediation — R1 → R7c (2026-07-10)

Autonomous `/loop` session that drove the dispatch-agent audit
(`design/STEWIE_DISPATCH_AGENT_AUDIT_2026-07-09.md`) to remediation. Every slice: screen vs live code →
TDD (test-first, fail) → implement → verify against the real gate (full CI-equivalent suite or the
frontend Playwright/ui-smoke) → commit (no Claude trailer, per `feedback_no_claude_trailers_astoreyai`) →
push → confirm the actual CI conclusion. Ten commits, all CI-green on `stewie-sw/stewie` `main`.

## What the audit found + what shipped

The audit's core theme: the release → run → command → world-record chain did not *bind* a single
immutable identity — the run rebuilt from mutable browser orders, command authority was a public checksum
with no expiry, terrain/physics inputs diverged from what was reviewed, a failed run orphaned world-journal
records, and the frontends never used the signed revision. The remediation:

| Slice | Commit | Fix |
|---|---|---|
| **R1** | `4dccb3a8` (+`a9ece073`) | Durable, immutable release-revision store — `ReleaseRevisionRow` (content_hash PK, **first-write-wins** = immutable by construction) + `persist_release_revision`/`read_release_revision` on the PG-01 db.py pattern (SQLite fallback in CI, Postgres in prod); persist-on-release in `/executive/release-plan` + `/executive/advance`; operator-gated `GET /executive/revision/{content_hash}`. |
| **R2/F1** | `a360cc5e` | `/executive/run` accepts `revision_hash` → fetches the frozen revision, executes `compile_intent(frozen_intent).mission` (the SIGNED plan), reports `bound_revision`; unknown hash → 400. |
| **R2/F3** | `f12f30cf` | `/rc/plan_ros` binds `revision_hash` → lowers the frozen revision to ROS, reports the same `content_hash`. |
| **R2/F4a** | `3f4991a3` | The run executes on the reviewed **as-built** surface (`state.as_built_dem`), not the raw DEM. |
| **R3a** | `7e114214` | `LiveExecutionToken` is now **expiring** (`issued_at` + `ttl_s`), **HMAC-signed** (keyed `_SECRET`, so unforgeable + expiry-unextendable), and bound to the released **content_hash**. |
| **R3b** | `7b250003` (+`ad414bb2`) | The live-write path (`/rc/command` GoTo) **requires** a valid, unexpired, hash-bound token behind a fail-closed `STEWIE_ALLOW_LIVE_EXEC` gate (default off = MO-04 SIM posture). |
| **R4** | `f632f5ef` | The run binds the reviewed physics backend (`mission.physics_backend_id`, PX-02) instead of a hardcoded literal (frame + Chrono-id already fixed: `7d6fb674`/`9e216b31`/`404003a5`). |
| **R6a** | `ec540d3d` | SIM run world-commit is **prepare/commit**: the fallible terrain fold runs BEFORE any journal write, so a fold failure writes zero orphan plan/leg records (finding #6; the append-only hash-chained journal has no rollback). |
| **R6b** | `03404a70` | The persisted run carries `bound_revision` + `physics_backend` + an honest `trajectory_kind: "forecast"` label (finding #10); surfaced on the SSE stream. |
| **R7a** | `2e987125` | The React `/app` release POST sends the SEC-01 `X-CSRF-Token` (finding #11) via a reusable `frontend/src/csrf.ts`. |
| **R7b** | `07ab89bd` | The vanilla cockpit binds `RELEASED_REV.content_hash` as `revision_hash` on both `/executive/run` POSTs. |
| **R7c(a)** | `4acb0a98` | The React AuthorityPane eligibility verdict keys on `?mission=` (finding #11). |

## Honestly deferred (spun out, not overclaimed)

- **F4b** (task #97): multi-vehicle SIM execution + per-vehicle events — `run_closed_loop` is single-vehicle;
  a real multi-vehicle closed-loop sim is a large build, not a loop slice.
- **R6 residuals** (documented in the R6a/R6b commit bodies): batch-atomic journal-append (fully closes the
  rare mid-append orphan) + real per-leg pose telemetry (makes playback an executed trajectory, not a
  labeled forecast).
- **R7 tail** (task #98): React Execute `/executive/run` action, de-stub the 8 placeholder panes, QWC2
  release-then-run binding — all the React `/app` partial-migration-shell + QWC2, lower-value per the audit
  ("do not advertise React /app as an operational cockpit").
- **R5** (task #86): correctly ROS-gated.

## Process lessons (four self-caused CI reds, all fixed forward → durable memories)

1. **req_trace 6-path-copy drift** — adding a package to only some of req_trace's duplicated scan-path copies.
2. **A Playwright spec enshrining a removed value** — removing `tier3_chrono` broke `workspace.spec.ts`.
3. **AC-01 TS-client drift gate** — adding a route without regenerating `api_client.ts`. → `feedback_full_suite_not_subset` updated: the CI-equivalent command must include `scripts/`; regen the client on a route change.
4. **A watchdog stale-link timing flake** — `_release_and_run` setup aged the SF-01 watchdog past its 5 s deadline on CI's slower runners; passed locally (< 5 s). → new memory `feedback_stewie_watchdog_test_timing`: re-feed the watchdog before the command; a local full-suite green cannot catch environment-timing differences.

Recurring signal-hygiene note: a background bash task's reported "exit code 0" is the *wrapper's* (a trailing
`grep`/`tail`), not pytest's — always read the real `FAILED` lines + the captured exit; and an xdist run
killed near 100% has NO end-summary, so it must be re-run.

## Verification caveats

- All ten commits are CI-green (7/7), verified via `gh run view` (not a `gh run watch` exit code, which
  misled twice).
- The CSRF + revision-binding are verified **client-side** (the frontend sends the header / `revision_hash`)
  and the backend guards are tested separately; the real cookie-authed production path is **not** exercised
  in CI (dev-open loopback bypasses CSRF) — only a live `app.stewie.space` browser session confirms
  end-to-end.
- The 5 "environmental DEM-bundle" test failures that appear on every local full-suite run are untracked
  `samples/lunar_dem/` bundles shadowing sites the tests expect to 404; they pass in CI's clean tree.
