# STEWIE Architectural Review — Triage & Action Plan (2026-07-16)

Triage of `design/STEWIE_FULL_ARCHITECTURAL_REVIEW_2026-07-16.md` (16 findings AR-001…AR-016) into a
prioritized, tracked plan with **independent confirm-status**. The review is the detailed source (evidence,
acceptance criteria, and the 7-phase 9–12 month program in §11); this doc is the decision layer: what is
confirmed, what to do first, and what is deferred.

**Verdict carried forward:** OPERATE / live-rover control = **NO-GO**. Research, GIS planning, training,
evaluation, and SIL simulation are defensible. P0 findings mean the code must not be promoted to a physical
actuator boundary; the live-exec flag defaults off and the backend is a simulator, so no physical rover was
affected.

## Confirm-status legend

- **CONFIRMED** — I opened the cited code and reproduced the mechanism this session.
- **SPOT-CONFIRMED** — I verified the cited symbol/line and the mechanism is present as described (not a full exploit repro).
- **PER-REVIEW** — plausible and well-evidenced in the review; I have not independently verified it yet.

## Findings register (triaged)

| ID | Sev | Confirm-status (me) | Effort | Phase | One-line disposition |
|---|---|---|---|---|---|
| AR-001 | P0 | **CONFIRMED** (`rc.py:70` passes `token.mission_id`, not the command's mission → tautological check) | S | 0 | Bind the live token to the commanded mission + negative adapter test. **User-deferred this session.** |
| AR-002 | P0 | SPOT-CONFIRMED (`SignedRevision.signed_by: str` ← `ROLE_RELEASE="director"`; one request advances all roles) | L | 1 | Replace role-labeled hash with authenticated multi-actor attestations + offline verify. |
| AR-003 | P0 | SPOT-CONFIRMED (`_command_authority` returns `authorized:True` regardless of `revision_persisted`; legacy `orders` path) | M | 0→1 | Governed paths accept only `release_id`; no authority when persist=false; legacy → sandbox/SIM. |
| AR-004 | P0 | SPOT-CONFIRMED (`log_event` records `degraded`, never refuses; audit written after the action) | M | 0→2 | Critical actions: write state+audit in one txn or refuse; anchor signed roots off-host. |
| AR-005 | P1 | SPOT-CONFIRMED (api-key→director in `auth.py`; nginx injects the shared key on anon `/api/*`) | M | 0 | Scoped anonymous planner principal; drop director-key injection; the htpasswd gate is mounted-but-unused. |
| AR-006 | P1 | PER-REVIEW | L | 2 | Mandatory prod Postgres + migrations + optimistic concurrency + outbox/reconciliation. |
| AR-007 | P1 | PER-REVIEW | M | 3 | Immutable generation directory + atomic manifest/pointer switch for multi-file terrain publish. |
| AR-008 | P1 | PER-REVIEW | M | 3 | Missing DEM → fail closed for release/operate; label explicit training fixtures. |
| AR-009 | P1 | PER-REVIEW (matches the known "QWC2 build not reproducible from source" note) | M | 4 | Build the QWC image in CI; version host ingress manifests + hashes. |
| AR-010 | P1 | PER-REVIEW | L | 5 | External metrics/logs/alerting; signed anchors; scheduled restore drills (RPO/RTO). |
| AR-016 | P1 | SPOT-CONFIRMED-adjacent (the review's own subprocess leaked Alpaca/Artemis creds) | S | 0 | Minimal allowlisted child env for subprocess tests + secret-canary regression + log redaction. |
| AR-011 | P2 | PER-REVIEW | L | 4 | One generated workspace/role contract; complete or retire the 3 frontend generations. |
| AR-012 | P2 | PER-REVIEW | L | 4 | Application services + repository ports + public module APIs (still a monolith). |
| AR-013 | P2 | CONFIRMED-adjacent (PRD/ATG drift is real; I maintain the §7 matrix + req_trace) | M | 1 | Executable capability manifest + one verify entrypoint + dependency-realistic plan. |
| AR-014 | P2 | CONFIRMED (~1 GB tracked; MT-01 row already tracks DEM externalization) | M | 3 | Content-addressed data bundles + manifests + small CI fixtures. |
| AR-015 | P2 | PER-REVIEW | S | 4 | Separate browser (HttpOnly) and automation (JSON token) login flows. |

Effort: S ≈ hours–1 day · M ≈ days–1 week · L ≈ weeks (a real program).

## Near-term slice — Phase 0 containment (weeks 0–2)

Ordered by leverage. Two Phase-0 items are **deferred this session per your instruction** (credentials + the
AR-001 code fix); the rest are actionable now and each is a tracked task.

1. **[YOURS] Rotate credentials** — Artemis key + Alpaca key/secret + anything in the exposed ambient env. External action; I won't touch secrets.
2. **[DEFERRED] AR-001** — bind the live token to the commanded mission + cross-mission negative test (confirmed, ~2-line fix).
3. **AR-016** — replace whole-environment subprocess calls in tests with a minimal allowlisted child env + a secret-canary regression + log redaction. *This is the code root-cause of the credential leak — fixing it stops the next leak; rotation only cleans up this one.*
4. **AR-005** — remove director-key injection from anonymous Artemis routes (or gate the whole origin behind a real, tested access gate); wire or drop the mounted-but-unused htpasswd.
5. **AR-003 / AR-004 (containment slice)** — make critical release/command/audit failures **refuse** rather than proceed: no authority card/token when `revision_persisted` is false; fail-closed audit on the privileged routes.
6. **SimBackend assertion** — a startup/readiness check that the only configured command backend is `SimBackend`/Null unless a future operational gate file is present (belt-and-suspenders on the NO-GO posture).
7. **Publish OPERATE = NO-GO** — already stated in the review; surface it in the capability manifest / README.

## Ties to existing STEWIE work

- **AR-013 / AR-014** overlap live rows: the §7 PRD matrix + `req_trace` reconciliation I maintain (AR-013), and **MT-01** DEM externalization (AR-014). Fold, don't duplicate.
- **AR-009** matches the standing "QWC2 deployed build not reproducible from tracked source" gap.
- The full 7-phase program (Phases 1–7, weeks 2–44) is the review's §11 — this triage does not re-plan it; it sequences the near-term containment and pins confirm-status so we act on verified defects, not on say-so.

## What I did NOT do

- Did not act on credentials (yours) or AR-001 (you deferred it this session).
- Did not independently verify the PER-REVIEW findings (AR-006/007/008/010/011/012/015) beyond reading the register — each gets a confirm pass before its fix, same as I did for the P0s here.
