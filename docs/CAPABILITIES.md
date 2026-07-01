# STEWIE Capability Matrix — honest status

> One place for the truths that are otherwise scattered across `PRD.md` rows, env docstrings, and
> `[CALIB]`/`[UNKNOWN]` tags. Three columns: **shipped & load-bearing** (real, wired, test-backed) /
> **training-only or offline** (real code, but NOT in the deployed product path) / **unbuilt & gated**
> (named in the PRD, deferred or externally blocked). Claims are grounded in `file:line`; if a row here
> disagrees with the code, the code wins — fix the row.
>
> The single honest headline: **STEWIE is a mature single-rover construction *planner + trainer* on an
> unusually honest conserved-physics core. It is not yet an operational mission-operations console**, and
> does not claim to be. The deployed planner is deterministic on purpose; RL is training-only; the 3D
> playback is a sim dry-run (no live telemetry).
>
> **Verified baseline 2026-06-20:** full suite **2418 passed / 92.91% coverage**, ruff+mypy clean,
> CI green. **The public deploy `app.stewie.space` is 502** (Docker daemon stopped + disabled on the
> host — a deploy state, not code; fix = PRD §27.2 OPS-01). The actionable backlog + 2-week sprint is
> **PRD §27**; the cockpit overhaul plan is `ui_overhaul_plan_2026-06-20.md`. This matrix will be
> auto-generated from `req_trace.py`/`release_gate.py` once OPS-04 (the per-row `[REQ:]` marker pass)
> lands; until then it is hand-maintained and the code wins on any disagreement.

## Mission planning

| Shipped & load-bearing | Training-only / offline | Unbuilt & gated |
|---|---|---|
| Cut-fill min-cost transport over a hazard-routed cost matrix; bulking conserved (`lode/mission_planner.py`) | RL scheduler (`SchedulerEnv`, PPO/beam/distill) — **not** in the deployed `/plan`; greedy/Held-Karp ties or beats it on single-objective (the empirical finding) | Cross-vehicle precedence chain-splitting (`plan_multi_oracle` refuses) — PRD FL-04 |
| Hazard-aware slip-weighted Dijkstra routing + keep-outs + negative-obstacle mask (`planner_routing.py`) | | Shared-charger contention *planned* (today FCFS post-hoc, not against the ReservationLedger) — PRD FL-03 |
| TSP family with honest optimality labels (nearest/2opt/or-opt/LK/brute/Held-Karp) | | Haul-path collision avoidance (detect-only today, never re-routes) — PRD FL-02 |
| Reserve-aware battery recharge; single immutable `PlanResult` threaded through run+timeline+IR+acceptance | | Berm-profile / bearing / repose acceptance (stubbed to flatness RMSE only) — PRD CP-06 |
| Versioned executable Plan IR; material-realizability + as-built flatness RMSE vs ±2 cm on real terrain | | Sinter (real + tested, gated off via `SINTER_ENABLED`); material/ice-dependent dig energy (uniform 4151 J/kg) |
| Multi-vehicle allocation + parallel makespan + exact ≤6-trip oracle | | |

## Simulation / physics

| Shipped & load-bearing | Training-only / offline | Unbuilt & gated |
|---|---|---|
| Conserved mass as THE invariant, height re-derived, runtime `conserves_mass()` guard (`stewie/physics/column_state.py`) | The 4 construction/drive Gymnasium envs + CEM/PPO trainers (real, tested, gym-optional) | Tier-3 force-accurate drum excavation (needs Chrono::GPU DEM, not in-repo) — PRD §1572 |
| Load-bearing Bekker pressure-sinkage as the live drive-loop default (`terramechanics.py`, `drive.py`) | The Godot 3D render/sensor track (real, on-disk binary) — runs offline, not in the RL/drive loop | Live Project Chrono SCM soil producer (`chrono_scm_export.py` is a self-labeled STUB; PyChrono.vehicle absent) — PRD P7 |
| Real slip ladder + discrete entrapment (Coulomb-Mohr, Janosi-Hanamoto) (`slip.py`) | | Quantitative terramechanics calibration (FIX-1 K_PHI, FIX-2 Lyasko) — blocked on the unavailable PyChrono oracle |
| Drum mass-inference grounded in real ICE-RASSOR data, no fabricated coefficients (`rassor_mass_model.py`) | | PSR/volatile (ice) optics — wired-but-inert schema slot |
| K10 weight-coupling chain (drum fill → load → sinkage → slip) wired end-to-end; per-body gravity | | |

## Perception

| Shipped & load-bearing | Training-only / offline | Unbuilt & gated |
|---|---|---|
| The cheap onboard-observability map channel (route coverage + uncertainty from conserved truth) | `dart/stereo_depth.py` (real cv2 SGBM) — consumed by `eval/gates.py`, not a live producer | Dense render→depth→point-cloud perception producer (PM-13..16) — PRD Convergence-B |
| Terrain scan-match + AprilTag-beacon localization fixes in the closed loop (`lode/autonomy.py`) | AprilTag 12.7 mm / 7.15° end-to-end — container-gated, not reproducible in default CI | Dense-tier §10/P6 map-channel RMSE (reconstructed-map vs truth) |
| Typed ARGUS Navigation factor contract: accepted estimator evidence now carries factor type, covariance, frame, source, and evidence class (`dart/factors.py`, `dart/evidence_ledger.py`); metric shadow-length/boundary claims are blocked behind the 2026-06-24 negative residual artifact | | |
| | | Truth-free operational SLAM/Navigation cm-parity (real Katwijk ATE is 3.35 m — `/slam` visibility ≠ operational parity) — the protected navigation frontier |

## Cockpit / UI

| Shipped & load-bearing | Training-only / offline | Unbuilt & gated |
|---|---|---|
| Full Plan-tab authoring: A-F flow, on-globe Cesium edit, top-down order canvas, build queue, 8 templates, keep-outs, precedence, 8 solvers, load→plan→embedded-PDF | — | Live execution / telemetry view (Metrics "execution" is an explicit deterministic forecast replay) — gated on the ROS2 bridge |
| Pipeline stepper spine (Site→Fleet→Orders→Solve→Review→Execute) gating Review/Execute behind a plan | — | In-cockpit guided walkthrough / tutorials (#126) |
| Tab-contextual left workspace; mobile font-boosting + overlap fixed | — | Operational-constraints authoring (time/sun/comms window, slope budget) — backend exists, UI exposure only |
| **In-cockpit 3D terrain dry-run** (Three.js, `▦ 3D` in Metrics): real DEM heightfield + rover + truth/estimate paths from `LAST_LOCALIZATION` — **a SIMULATION dry-run, not a live rover** | — | True live-vs-sim overlay — gated on the ROS2 bridge (P20) + streaming telemetry (NV-12) |

## Autonomy / infra / access

| Shipped & load-bearing | Training-only / offline | Unbuilt & gated |
|---|---|---|
| Four-tier role ladder (guest<trainee<operator<director) + `require_role` capability gating | — | Live `rclpy` node joining the ROS2 graph + real PitBackend transport — the binding Phase-1-gate dependency, externally blocked on the pit link details |
| Full control panel: create/approve/role/revoke/reset/delete operators + invite tokens + audit log | — | Operational digital-twin unification (DT-01) + the `/twin/version` read-auth fix (DT-02) |
| Sandbox/live workspace separation; real rover instructions gated to live mission + operator+ + SF-01 watchdog | — | |
| SF-01 command-timeout watchdog + the P20 ROS2 translation layer (`stewie/bridge/ros2_bridge.py`, tested) | — | |

---

**Phase-1 gate (ROS2 bridge → Docker intern beta):** SF-01 watchdog + the RC contract + the translation
layer are **done and tested**; what remains is the live `rclpy` node + the real PitBackend transport,
both gated externally on the pit link details (an integration, not a design unknown). So the Day-28
intern beta is **not** claimable end-to-end today.

**What NOT to claim:** RL beating greedy on single-objective tasks; the 3D dry-run as "live"; `/slam`
cockpit visibility as operational SLAM parity. These are the three honesty traps the matrix above guards.
