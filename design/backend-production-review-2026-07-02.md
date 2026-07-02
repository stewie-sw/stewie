# STEWIE Backend Production-Grade Review

Date: 2026-07-02
Scope: `/mnt/projects/stewie/code`
Skill applied: `backend-review-design`

## Verdict

STEWIE has a serious backend scaffold: FastAPI route boundaries are mostly explicit, the object stores are path-confined and atomically written, critical admin routes are director-gated, the deployment runs non-root with a read-only root filesystem, dependencies are hash-pinned in CI and the server image, and the targeted backend hardening suite passes.

It is not yet production-release complete. The largest remaining gaps are not broad rewrites; they are production gates and policy mismatches: the SE-01 release audit evidence is incomplete, several production secrets/defaults are still migration-friendly rather than deployment-strict, the container entrypoint bypasses the CLI TLS guard, AG-06 live delete governance is weaker than the PRD, and the training operator view still lacks an explicit access model.

## Verification Run

Command:

```bash
.venv/bin/python -m pytest \
  stewie/server/test_security.py \
  stewie/server/test_deploy_hardening.py \
  stewie/server/test_account_store_failclosed.py \
  stewie/server/test_revocation_failclosed.py \
  stewie/server/test_auth.py \
  stewie/server/test_operator_admin.py \
  stewie/server/test_command_gate.py \
  stewie/server/test_audit_ledger.py \
  stewie/server/test_audit_route_coverage.py \
  stewie/server/test_world_transaction_atomic.py \
  stewie/server/test_session.py
```

Result: `171 passed, 1 warning in 26.55s`.

Warning: Starlette/httpx deprecation from `fastapi.testclient`; no test failure.

Worktree note: `design/` and `stewie/server/test_planner_observed_world.py` were already untracked before this report was added.

## Architecture Snapshot

- Backend entrypoint: `stewie/server/server.py`, FastAPI app with route modules under `stewie/server/routers/`.
- Auth and roles: `stewie/server/auth.py`, `stewie/server/deps.py`, `stewie/server/operators.py`, `stewie/server/routers/auth.py`, `stewie/server/routers/operators_admin.py`.
- Persistence: JSON object stores under configurable `STEWIE_DATA_DIR`, audit JSONL, reports, profiles, sessions, terrain memory, world-state journal.
- Domain contracts: `stewie/contracts/`, `lode/`, `dart/`, `leap/`, `forge/`.
- Frontend bridge: OpenAPI/schema route, typed adapters in the frontend, auth cookies/CSRF, operational routes guarded by role dependencies.
- Deployment: `deploy/Dockerfile.backend`, `deploy/compose.yml`, `deploy/nginx.conf`, GitHub Actions CI/release workflows.

## Strengths To Preserve

- `deploy/Dockerfile.backend:4-39` uses a digest-pinned Python base, hash-pinned server requirements, non-root user, immutable root filesystem assumptions, and a healthcheck.
- `deploy/compose.yml:34-45` gives the backend a persistent `/data` volume, drops capabilities, disables privilege escalation, and mounts `/tmp` as tmpfs.
- `stewie/server/deps.py` centralizes auth, role ladder enforcement, CSRF checks, and sandbox/live namespace resolution.
- `stewie/server/routers/operators_admin.py:41-126` keeps operator administration director-only and protects against deleting/demoting the last active director.
- `stewie/server/auth.py:84-136` makes revocation-store corruption fail closed.
- `stewie/server/services.py:157-179` records audit-write degradation instead of silently swallowing it.
- `stewie/server/server.py:203-254` adds correlation IDs, bounded request body checks, finite route-template metrics, latency sampling, and response correlation headers.
- `stewie/server/world_state.py` and the DT-03 tests provide a meaningful hash-chained transaction spine for world-state commitments.
- `.github/workflows/ci.yml:24-40` installs from a hashed lock, runs traceability, lint, mypy, tier reporting, tests, and coverage.

## Priority Findings

### P0-1: SE-01 Release Security Audit Gate Is Still Incomplete

Evidence:

- `PRD.md:735` requires host, container, app, DNS/site, secret, backup/restore, dependency/SBOM/CVE, and external exposure audits.
- `FANOUT_SPECS.md:551-557` says current state is partial and explicitly lists missing CVE scan, host/DNS/site/secret/external-exposure audits, and drilled backup/restore.

Risk: the codebase has hardening slices, but there is no release artifact proving the actual deployed system passed the required audit domains.

Recommendation:

- Add `docs/security/se-01/2026-07-02/manifest.json` or equivalent with one evidence record per required domain.
- Add `scripts/test_se01_audit_gate.py` with `[REQ:SE-01]` that fails unless all eight evidence artifacts exist, are dated, identify the environment, and name the tool/manual procedure used.
- Run and store an SBOM CVE scan, not just SBOM generation.
- Add a backup/restore drill that restores `/data` into a fresh container and verifies auth store, audit log, reports, profiles, mission artifacts, terrain memory, and world journal readability.

Acceptance test:

- `python scripts/test_se01_audit_gate.py` fails on a missing domain and passes only with all eight current evidence records.

### P1-1: Backend Container Entrypoint Bypasses The Public-Bind TLS Guard

Evidence:

- `stewie/server/server.py:351-365` refuses public binds unless TLS termination or dev-open is declared.
- `stewie/server/server.py:368-383` calls that guard only from `main()`.
- `deploy/Dockerfile.backend:39` starts `python -m uvicorn stewie.server.server:app --host 0.0.0.0`, which imports the ASGI app directly and bypasses `main()`.
- `deploy/compose.yml:19-22` sets `STEWIE_TLS_TERMINATED=1` and keeps the backend internal, so the current compose path is probably safe, but the guard is not enforced by the production image entrypoint itself.

Risk: a direct container run or future compose edit can bind plaintext on `0.0.0.0` without hitting the guard that tests currently validate for the CLI path.

Recommendation:

- Either change `deploy/Dockerfile.backend:39` to invoke `stewie-serve --host 0.0.0.0 --port 8770`, or move the production invariant into ASGI startup/lifespan where direct uvicorn imports must pass it.
- Add a deploy test asserting the backend image command enters the guarded path or that lifespan rejects public bind without TLS.

Acceptance test:

- A test equivalent to `test_tls_guard` must inspect the Dockerfile command and fail if production starts `server:app` directly without an equivalent guard.

### P1-2: Production Session Signing Secret Is Optional In Compose

Evidence:

- `stewie/server/auth.py:61-72` prefers `STEWIE_SESSION_SECRET`, but falls back to a derived key from `STEWIE_API_KEY`.
- `deploy/compose.yml:10-33` requires `STEWIE_API_KEY` but does not require or set `STEWIE_SESSION_SECRET`.

Risk: the fallback is migration-friendly, but production should separate automation credentials from browser session signing. If the automation API key leaks, the session-signing derivation is no longer an independent control.

Recommendation:

- Require `STEWIE_SESSION_SECRET` in `deploy/compose.yml` for production, with the same fail-loud style used for `STEWIE_API_KEY`.
- Add a startup/config health warning or failure when `STEWIE_TLS_TERMINATED=1` and `STEWIE_SESSION_SECRET` is absent.
- Document rotation separately: API key rotation should not invalidate sessions unless explicitly intended; session secret rotation should invalidate sessions.

Acceptance test:

- Compose/deploy hardening test fails when production env omits `STEWIE_SESSION_SECRET`.
- Auth token tests prove API key rotation and session secret rotation have separate effects.

### P1-3: Default Allowlist And Director Fallback Are Not Production-Strict

Evidence:

- `stewie/server/auth.py:27-41` hardcodes `DEFAULT_ALLOWLIST`.
- `stewie/server/auth.py:44-52` falls back to the allowlist for emails absent from the operator store.
- `stewie/server/auth.py:186-201` makes all allowlisted users directors when `STEWIE_DIRECTORS` is unset.
- `stewie/server/routers/auth.py:70-101` preserves the legacy raw-key bootstrap that can claim any allowlisted email.

Risk: a fresh production deployment with an empty or missing operator store still trusts built-in personal identities. The raw API key remains a bootstrap authority for any default allowlisted address.

Recommendation:

- In production mode, require explicit `STEWIE_ALLOWED_OPERATORS` and `STEWIE_DIRECTORS`, or require a one-time bootstrap director record in `operators.json`.
- Keep default allowlist only for local/dev/desktop modes, not `STEWIE_TLS_TERMINATED=1` production.
- Add `/healthz` or `/config` degraded state when production is running on built-in identity defaults.

Acceptance test:

- With `STEWIE_TLS_TERMINATED=1` and no explicit allowlist/directors, login/bootstrap should fail closed or startup should fail with an actionable error.

### P1-4: Live Artifact Delete Policy Does Not Match AG-06

Evidence:

- `PRD.md:716` requires director approval for deleting another operator's artifact or any live-namespace artifact.
- `stewie/server/routers/missions.py:99-111` allows a user to delete their own live mission because it delegates to owner-or-director logic.
- `stewie/server/routers/structures.py:43-54` allows a user to delete their own shared live structure template.
- `stewie/server/objects.py:70-76` implements generic `is_director or owner == identity` deletion.

Risk: live operational artifacts can be soft-deleted by their creator without director escalation, contrary to the product governance requirement.

Recommendation:

- Make live namespace deletion director-only.
- Keep self-service deletion for the caller's own sandbox artifacts.
- Split `deletion_allowed()` into `deletion_allowed(kind, namespace, owner, identity, role)` or enforce namespace-specific policy in the routes before calling it.

Acceptance test:

- Operator deleting own live mission returns 403.
- Operator deleting own sandbox mission succeeds.
- Director deleting live mission succeeds and audit event includes namespace.

### P1-5: Training Operator View Needs An Explicit Access Model

Evidence:

- `PRD.md:845` says `/session/{sid}/operator` must be authenticated or explicitly documented/enforced as a capability URL.
- `stewie/server/routers/session.py:44-50` is open by contract.
- `stewie/server/session.py:180-216` stores sessions in-process and evicts expired sessions only when `start()` calls `_evict()`, not on `get()`.

Risk: a leaked session id is currently a bearer capability for truth-denylisted training telemetry. Truth denial reduces sensitivity, but it is not itself an access-control decision. Also, expired sessions can persist in memory until another session starts.

Recommendation:

- Choose one model:
  - Authenticated route: add `require_auth` and optionally trainer/session ownership.
  - Capability URL: use an explicit signed share token with expiry, document that it is a bearer URL, and make `get()` enforce TTL.
- Add `[REQ:SE-02]` coverage in `stewie/server/test_session.py`.

Acceptance test:

- If authenticated: anonymous GET returns 401/403.
- If capability URL: unsigned id-only URL returns 401/403, signed unexpired URL succeeds, expired URL fails.

### P2-1: Audit Ledger Degradation Does Not Stop Privileged Operations

Evidence:

- `stewie/server/services.py:157-179` records audit failures but deliberately does not raise into the request path.
- Director/admin/command routes call `log_event(...)`, but operation success is not conditional on durable audit success.

Risk: in production, a disk-full or permission failure can let sensitive admin/command changes continue while the durable audit ledger is degraded.

Recommendation:

- Add `log_event(..., critical=True) -> bool` or `require_audit_healthy()` for director admin, live mission mutation, release/execute, rover command, and security settings changes.
- For critical operations, refuse with 503 when the audit sink is degraded.
- Keep non-critical informational logs best-effort.

Acceptance test:

- Inject audit-write failure and prove `/admin/operators/create`, live mission delete, release/execute, and `/rc/command` refuse or surface a hard degraded result.

### P2-2: FS-19 Observability Ledger Is Partial

Evidence:

- `PRD.md:786` requires mission decisions, operator actions, role checks, backend contract calls, plan/replan, command emission, safing, model inference, Navigation factor decisions, fleet conflicts, and state transitions with correlation ID, mission/site/body/time, actor, input/output hashes, result, latency, and error code.
- `FANOUT_SPECS.md:155-160` states current FS-19 coverage is partial.
- `stewie/server/server.py:249-253` explicitly avoids writing per-request HTTP events into the audit ledger and says full per-contract-call observability belongs in a separate stream.

Risk: the audit trail is useful for operator actions, but it is not yet the full production observability ledger required by FS-19.

Recommendation:

- Define a typed event schema for observability events separate from the director-facing audit trail if needed.
- Add a decorator/helper for backend contract routes that records correlation ID, actor, route contract, result, latency, error code, input hash, output hash, and mission/site/body/time where present.
- Extend `stewie/server/test_observability_ledger.py` with one assertion per required event class.

Acceptance test:

- `[REQ:FS-19]` fails if any required event class is missing full-field coverage or if redaction misses secrets/truth-denied fields.

### P2-3: Single-Process Assumptions Are Real But Not Fully Guarded

Evidence:

- `deploy/Dockerfile.backend:39` runs uvicorn with `--workers 1`.
- `stewie/server/routers/auth.py:48-60` uses process-local rate limiters.
- `stewie/server/session.py:180-216` stores training sessions in memory.
- `stewie/server/services.py:186-208` stores request metrics in process memory.

Risk: the current deployment is single-worker by design, but accidental scaling to multiple workers would split auth rate limits, sessions, and metrics.

Recommendation:

- Add a deploy hardening test that fails if production workers are set above 1 without moving rate limiters, sessions, and metrics to shared storage.
- Document "single-worker backend" as an architectural invariant, not an incidental Dockerfile flag.
- If scaling is needed, move these process-local stores to SQLite/Redis or another shared backend.

Acceptance test:

- A test checks the production command and a config invariant such as `STEWIE_SINGLE_PROCESS_STATE=1`.

### P2-4: Report Pruning Does Not Remove Nested Render Directories

Evidence:

- `stewie/server/services.py:377-393` deletes only files directly under `reports_dir`.
- `stewie/server/routers/perception.py:406-420` writes render outputs under a stemmed reports path.
- `stewie/specs/config.py:164-166` places reports under persistent application data.

Risk: render/report subdirectories can accumulate in `/data/reports` even when top-level PDF/Markdown artifacts are pruned.

Recommendation:

- Extend `prune_reports()` to remove old, known-safe generated directories such as `render_*`.
- Avoid recursive deletion of arbitrary paths; only prune names matching generated prefixes and ensure resolved paths remain under `reports_dir`.

Acceptance test:

- Existing report prune test should add an old `render_*` directory and prove it is removed while unrelated directories are preserved.

### P2-5: Shared Live Object Stores Lack Optimistic Concurrency

Evidence:

- `stewie/server/objects.py:141-151` saves missions via read-owner-meta plus atomic replace.
- `stewie/server/objects.py:298-314` saves structures similarly.

Risk: atomic replace prevents partial writes, but two operators saving the same live artifact can race and last-writer-wins without a revision conflict. For operational mission/profile/shared-template surfaces, that is too easy to miss.

Recommendation:

- Add `updated_at`, `revision`, and `sha256` metadata to shared live artifacts.
- Require `If-Match` or a request body `base_revision` for writes to live missions, profiles, and shared structures.
- Return 409 with the current revision when a stale client saves.

Acceptance test:

- Two clients load revision N; first save succeeds as N+1; second save with N returns 409.

### P2-6: Publish Workflow Does Not Use The Hashed Dev Lock

Evidence:

- `.github/workflows/ci.yml:24-40` installs `requirements-dev.lock` with `--require-hashes`.
- `.github/workflows/publish-stewie.yml:25-34` installs `pip install -e .[dev]`.

Risk: release-gate tests can run against dependency versions different from CI, creating a supply-chain and reproducibility gap before PyPI publication.

Recommendation:

- Make publish gate match CI install:
  - `pip install --require-hashes -r requirements-dev.lock`
  - `pip install -e . --no-deps`
- Consider running `scripts/req_trace.py` and the deploy hardening tests in the publish gate too.

Acceptance test:

- Workflow lint/test asserts publish workflow uses `requirements-dev.lock` with `--require-hashes`.

### P3-1: Browser Login Still Returns The Session Token In JSON

Evidence:

- `stewie/server/routers/auth.py:111-120` sets HttpOnly session and CSRF cookies.
- `stewie/server/routers/auth.py:123-133` still returns the token in the JSON response body for both browser and automation paths.

Risk: HttpOnly cookies are the right browser credential, but echoing the bearer token in JSON expands exposure through browser memory, logs, devtools, or accidental frontend persistence.

Recommendation:

- Split browser and automation token responses.
- For normal browser login, return role/operator/ttl/must_set_password but omit `token`.
- Require an explicit automation route, header, or query flag to return a bearer token.

Acceptance test:

- Browser login response omits `token`; automation login path includes it only when explicitly requested and tested.

## Backend To Frontend Bridge Review

Current bridge strengths:

- The backend exposes schemas/contracts and the frontend has typed adapter parity tests.
- Auth uses SameSite Strict HttpOnly session cookie plus readable CSRF cookie for browser mutation paths.
- Routes return consistent `{ok: false, error: ...}` envelopes for many validation and HTTP errors.
- Role-gated APIs are mostly centralized through `require_auth`, `require_role`, and `require_director`.

Bridge gaps to prioritize:

- Permission contracts should be explicit in API schemas or a route capability manifest so the frontend can drive disabled states without duplicating role logic.
- Live/sandbox namespace and product/runnable profile should be returned consistently in mutation responses and command refusals.
- AG-06 live-delete policy should be fixed backend-first, then reflected in frontend affordances.
- SE-02 access model for training sessions must be surfaced clearly in UI links: either authenticated operator view or explicitly labeled expiring share URL.
- FS-19/observability events need a stable admin-facing read model separate from raw route logs.

Recommended bridge artifact:

- Add `stewie/server/route_capabilities.py` or a generated JSON manifest with route, method, min_role, namespace behavior, command authority, audit criticality, and frontend work area.
- Add a frontend adapter test that verifies every mutating route used by the cockpit has a capability mapping.

## Local LLM-Council Synthesis

No external subagents were launched. This is a local council-style review using the perspectives required by the backend review skill.

Security reviewer:

- Production defaults must be explicit. Remove built-in identity trust from production, require a standalone session secret, and close the SE-01 evidence gate before release.

Backend architecture reviewer:

- The modular route structure is good. The most important code-level fixes are centralizing production invariants, tightening namespace-aware policy, and adding optimistic concurrency to shared live artifacts.

Operations reviewer:

- The Docker/compose hardening is stronger than typical, but release evidence, backup/restore drill, CVE scan, and deploy command guard are not complete enough for a production sign-off.

Frontend bridge reviewer:

- Backend capabilities need to become machine-readable so the cockpit/admin UI can reflect authority, namespace, runnable profile, audit criticality, and refusal reasons without duplicating hidden backend rules.

Consensus:

- Do not reorganize the whole backend. Fix production gates and policy invariants first, then add a route capability manifest and focused tests. The codebase is scaffolded well enough to harden incrementally.

## File-Level Review Matrix

| File | Review notes |
|---|---|
| `stewie/server/server.py` | Good middleware, body caps, metrics, correlation IDs. TLS public-bind guard exists but is CLI-only; production image bypasses it. |
| `stewie/server/auth.py` | Solid token claims and fail-closed revocation. Production identity defaults and session-secret fallback need stricter production behavior. |
| `stewie/server/deps.py` | Central auth/role/CSRF/namespace logic is the right pattern. Keep route policy here or adjacent. |
| `stewie/server/routers/auth.py` | Good field caps, rate limiting, registration fail-closed, cookies. Token-in-body should be split from browser login. |
| `stewie/server/operators.py` | Durable operator store with migration and fail-closed corruption posture. Production should not fall back to built-in allowlist when store is absent. |
| `stewie/server/routers/operators_admin.py` | Director-only admin with last-director guard. Audit is present; should become audit-critical once audit failure can block sensitive ops. |
| `stewie/server/objects.py` | Atomic writes and path confinement are good. Needs namespace-aware delete policy and optimistic concurrency for live shared artifacts. |
| `stewie/server/routers/missions.py` | Namespace-aware CRUD and publishing exist. Live delete currently conflicts with AG-06. |
| `stewie/server/routers/structures.py` | Shared live structure writes are operator-gated. Live delete currently conflicts with AG-06. |
| `stewie/server/services.py` | Audit, redaction, metrics, budgets, and pruning exist. Critical audit writes should fail closed; report pruning should cover generated dirs. |
| `stewie/server/session.py` | Training session cap/TTL exist, but state is in-process and TTL is not enforced on read. |
| `stewie/server/routers/session.py` | Scorecard/debrief truth gating is good. Operator view needs explicit auth or capability URL model. |
| `stewie/server/state.py` | Per-site twin caching and terrain views are materially improved. Multi-site world journal assumptions should stay under DT-04 review. |
| `stewie/server/world_state.py` | Strong hash-chain/transaction spine. Keep expanding routes into this model instead of adding side stores. |
| `stewie/server/routers/twin.py` | Resync and terrain record paths use locks/compensation. Preserve no-swallow behavior in future mutations. |
| `stewie/server/routers/executive.py` | Director-gated release/run path is explicit; SIM labeling is clear. Add audit-critical behavior for release/run. |
| `stewie/server/routers/rc.py` | Command authority tests passed. Keep SF-02 bounded teleop invariants pinned by tests. |
| `stewie/server/routers/assets.py` | Static assets are path-confined; reports require auth and basename confinement. |
| `deploy/Dockerfile.backend` | Strong image hardening and pinning. Entrypoint should use guarded server path or equivalent ASGI startup guard. |
| `deploy/compose.yml` | Good backend isolation and hardening. Add required `STEWIE_SESSION_SECRET`; clean duplicate API-key wording in the comment/expression. |
| `deploy/nginx.conf` | CSP is intentional and self-hosted. HSTS remains dependent on the outer TLS terminator and should be part of SE-01 evidence. |
| `.github/workflows/ci.yml` | Strong hash-locked CI gate. Preserve this as the reference install pattern. |
| `.github/workflows/publish-stewie.yml` | Publish gate should install from hashed lock like CI. |
| `PRD.md` | Contains the correct production requirements; several rows now need implementation evidence rather than more prose. |
| `FANOUT_SPECS.md` | Useful backlog map. SE-01, FS-19, and SE-02 entries align with this review's highest-priority gaps. |

## Recommended Work Order

1. Close production defaults: require `STEWIE_SESSION_SECRET`, disable built-in allowlist/director fallback in production, and make Docker entrypoint hit the TLS guard.
2. Fix AG-06 live delete governance and add namespace-specific tests.
3. Decide and implement SE-02 session operator access model.
4. Add critical audit failure behavior for command/admin/release routes.
5. Add SE-01 release evidence manifest and gate test.
6. Add route capability manifest for frontend/admin bridge.
7. Add optimistic concurrency to shared live artifacts.
8. Make publish workflow use the hashed dev lock.
9. Extend report pruning for generated render directories.

## Production Sign-Off Checklist

- [ ] `scripts/test_se01_audit_gate.py` passes with dated evidence for all eight SE-01 domains.
- [ ] Production startup fails without `STEWIE_API_KEY`, `STEWIE_SESSION_SECRET`, explicit operator/director policy, and declared TLS termination for public bind.
- [ ] All mutating live artifact deletes are director-only.
- [ ] Training operator view is either authenticated or uses signed expiring capability URLs.
- [ ] Critical admin/command/release operations fail closed when the audit ledger is degraded.
- [ ] FS-19 ledger tests cover every required event class and redaction condition.
- [ ] Backend route capability manifest is consumed by frontend/admin controls.
- [ ] Publish gate uses hashed locks and runs the same core backend quality gates as CI.
