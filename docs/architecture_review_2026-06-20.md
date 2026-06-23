# STEWIE Architecture Review (2026-06-20)

Full review of the STEWIE project — local and deployed — against the PRD, with a done-vs-needed
accounting and a presentation recommendation. Companion to the same-day mission-ops review
(`architecture_review_2026-06-20_mission_ops.md`) and the appended execution backlog (PRD §27). All
"verified" claims were run on the deploy host (archimedes) this session.

## Verdict

- **Pattern:** layered modular monolith — conserved-physics core → subsystem layer
  (DART/LODE/LEAP/FORGE) → FastAPI cockpit, with an optional ROS2/Gymnasium/Godot egress. Clean
  acyclic dependency DAG.
- **Size:** ~91.5k Python LOC (320 test files); JS cockpit ~5.9k LOC (Cesium + Three.js); ROS2 11
  packages; Electron desktop shell.
- **Local health (verified):** full suite **2418 passed / 5 skipped / 0 failed** (2423 collected,
  ~22 min); **coverage 92.91%** (gate 85%); `ruff --select F` clean; `mypy` clean (240 files); CI green
  (lint+type+cov on 3.11, test matrix 3.12/3.13).
- **Deployed (verified):** `app.stewie.space` returned **HTTP 502 — origin down**. Root cause:
  `docker.service` is `inactive (dead)` and `disabled` on archimedes; `cloudflared` is up and routes
  `app.stewie.space → 127.0.0.1:8000`, but no frontend container is running. Host action, not code
  (PRD §27.2 OPS-01).

The code is healthy and green; the public site is down for an ops reason.

## Done vs needed (PRD v7.2 §7, 186 rows)

Parsed from the live §7 matrix (the §4.2/§19.1 prose census is stale — reconciled 2026-06-20):

| Bucket | Count |
|---|---:|
| DONE (all required columns D incl. Q) | 33 |
| IXV-done, Q-pending (tested, not hardware-qualified) | 39 |
| Partial | 73 |
| Gated (external input) | 17 |
| Open | 24 |

A 5-row over-claim spot check (FL-02 conflict resolution, immutable PlanResult, resync/forward-sim,
typed contract spine, StreamSession+SafingWatchdog) was **5/5 real with citing tests** — the PRD's
honesty discipline holds. The full backlog and the 2-week sprint are PRD §27.

## Strengths

- Disciplined honesty as an engineering invariant: `[CALIB]`/`[ASSUMPTION]`/`[UNKNOWN]` tags, the
  4-column I/X/V/Q status model, a `ModelArtifact._no_command_path` validator. This is the project's
  biggest credibility asset.
- Single conserved-physics authority (`stewie/physics/column_state.py`) is the **sole terrain
  mutator** (verified): two mutating primitives, validate-before-mutate, single-writer test.
- Clean layering (acyclic at import; the one `stewie↔dart` cycle is deliberately broken via deferred
  imports). `forge` is a pure leaf.
- Real, not theatrical: 0 TODO/FIXME in source; `NotImplementedError` only at 3 documented abstract
  seams; genuine rclpy behind an optional-dependency gate.
- The presentation core is the hard part done right: an honest plan → validate → report → debrief loop
  with a server-enforced director/operator training split, embedded mission-control PDF, executable
  Plan IR, and graceful GPU-less 2-D fallback.

## Risks (ranked)

1. **[HIGH] Public deploy down + non-persistent** — 502 now; Docker `disabled` means it recurs on
   reboot. (OPS-01.)
2. **[HIGH] "What's done" is unanswerable without the tool** — status fragmented across 5 ID
   namespaces (PRD I/X/V/Q · atomic B/P/Y2 · git FS-xx · audit ARCH/SEC), with stale headlines
   (§4.2 RB blockers, §19.1 census). (OPS-04 + the reconciliation in §27.1.)
3. **[MEDIUM] God-modules** — `lode/mission_planner.py` (2612 LOC), `cockpit.js` (4321), `scenes.py`
   (1189). Tracked as ARCH-2/FS-24. — **ARCH-2 RESOLVED 2026-06-22:** `mission_planner.py` is now a
   448-line facade over 10 `planner_*` leaf modules; the cockpit.js / scenes.py splits (FS-24) remain.
4. **[MEDIUM] Presentation gaps for the GMRO/KSC audience** — build-order authoring is typed `x,y`
   with axis-aligned squares; the optimizer reports but doesn't respect sun/thermal/comms windows; no
   trainer dashboard; the Moon renders on a WGS84 sphere. (See the UI overhaul plan.)
5. **[LOW] External-presentation conflation** — 39 IXV-done-but-Q-pending rows can read as "done" if
   the I/X/V/Q nuance is dropped in a deck.

## Recommendations

1. Restore + harden the deploy (start/enable Docker, `compose up`, verify through Cloudflare; SEC-host
   `chmod 600 deploy/.env` + key rotation). — OPS-01/02
2. Make the tool the single status surface: auto-derive status from `req_trace.py`/`release_gate.py`,
   publish `STATUS.md`/`/figures`, run the per-row `[REQ:]` marker pass, retire the hand-maintained
   checkboxes. — OPS-04
3. Split the two god-modules behind their existing seams. — ARCH-2 (mission_planner: **DONE 2026-06-22**, 448-line facade over 10 `planner_*` leaves), FS-24 (cockpit.js: open)
4. Presentation upgrades in audience-priority order: draw-on-map order authoring (polygon/corridor/
   oriented-rect) → constraint-respecting optimizer → trainer dashboard → per-body globe. See the
   full-fidelity plan: [UI overhaul plan (2026-06-20)](ui_overhaul_plan_2026-06-20.md).
5. Keep the I/X/V/Q split visible in any external material (label sim-tested vs hardware-qualified).

## Best way to present this material

For a NASA-lab / mission-planning audience, lead with the honest, physics-grounded plan → validate →
report → debrief loop with the director/operator training split and the mission-control PDF, framed
as a **pre-operational ground / trainer tool** (self-rated TRL ~3-4), not flight autonomy. The full
presentation plan — the FS-03 eight-area IA, the 2026-06-20 four-screen operational model
(Plan/Rehearse/Execute/Debrief), GIS feature-layer authoring, the brand system, WCAG-AA, and a
strangler-fig migration that does not repeat the reverted React rewrite — is in
[the UI overhaul plan](ui_overhaul_plan_2026-06-20.md) and PRD §27.4.
