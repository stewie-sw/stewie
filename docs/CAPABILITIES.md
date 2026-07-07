# STEWIE capability matrix (honest status)

> One place for the truths that are otherwise scattered across the requirement rows, environment
> docstrings, and provenance tags. Three columns: **shipped and load-bearing** (real, wired,
> test-backed), **training-only or offline** (real code, but not in the deployed product path), and
> **unbuilt and gated** (named in the requirements, deferred or externally blocked). Claims are grounded
> in file and line; if a row here disagrees with the code, the code wins, so fix the row.
>
> The single honest headline: **STEWIE is a GIS-first lunar construction planner, trainer, and digital
> twin on an unusually honest conserved-physics core.** The front door is a GIS mission-control IDE, live
> at `artemis.stewie.space/ide/`. It is not yet an operational mission-operations console over live
> hardware, and does not claim to be. The deployed planner is deterministic on purpose; reinforcement
> learning is training-only; the Execute playback is a simulated run (no live telemetry).
>
> **Baseline.** The requirement matrix (product requirements, section 7, 339 rows) reads **254 verified
> done** (about 75 percent overall; 78 percent of the 325 in-scope rows, with hardware and host gated
> rows excluded from that denominator). By priority: P0 107/116, P1 143/188, P2 4/33. These are the live
> tool output (`STATUS.json`, `release_manifest.json`), not hand counts. The CI coverage floor is 85
> percent; CI is green on the working branch. Both public hosts are up: the GIS IDE at
> `artemis.stewie.space/ide/` (the bare `artemis.stewie.space` redirects there) and the single-page
> cockpit at `app.stewie.space`. The committed matrix is projected read-only onto the in-IDE requirement
> board, and the generated traceability file is written by the traceability tools. This narrative matrix
> is hand-maintained; the code wins on any disagreement.

## GIS mission-control IDE

| Shipped and load-bearing | Training-only or offline | Unbuilt and gated |
|---|---|---|
| One persistent lunar map (QGIS Web Client 2 over QGIS Server) in the Moon south-polar stereographic frame (`IAU_2015:30135`); pole-truthful, no WGS84 or Earth claim on lunar coordinates; the bare `artemis.stewie.space` redirects to `/ide/` | The full QWC2 migration is incremental; the earlier single-page cockpit stays live at `app.stewie.space` for panes not yet ported | Full multi-panel GIS parity with a production desktop GIS (measure, snap, undo, and edit history exist; the deep editing surface is still being adopted) |
| Real terrain: 8 Artemis III candidate-site DEMs (LOLA 5 m polar) plus a 1 m Haworth shape-from-shading DEM, with slope, hillshade, and LROC imagery context drapes; nine candidate-site pins (Haworth included) zoom on click; a WAC-albedo drape and a whole-Moon globe give context | | Some external OGC drapes are deferred with reasons (Moon Trek WMTS CRS, QuickMap SPA, and the in-canvas STEWIE OGC render pending a caps extension) |
| Mission-authoring tool palette on the map: cut and fill build orders, structures, keep-out barriers, traverse-by-waypoints, return-to-lander, and place-objects (beacon, cache, instrument, sample, antenna), plus planner controls and a multi-vehicle fleet — every edit written only through a server-owned, versioned edit-session (monotonic version, before/after audit, linear undo) | | |
| Plan-anywhere: pick any lat/lon (typed or by map-click); a request-time DEM resolver crops the global LOLA to plan in that local frame, not only at the fixed sites | | The pole itself (`|lat| > 89.9`) is served by the curated polar tiles, not an ad-hoc equirectangular crop |
| Plan inspection: candidate-future compare, plan detail, a Gantt schedule, and a simulated run | | |
| The roughly 65-layer catalog (66 with the traversal-compaction traffic layer) with per-layer provenance, freshness, uncertainty, and display versus planning, release, and execute eligibility; a selection inspector, an asset library, and an evidence and report bundle | | |
| Analysis layers: route cost, blocking, the terramechanics terms (slope, bearing, sinkage, slip, traction, energy), and traversal-compaction traffic | | |
| A rover HUD (an IPEx instrument: 8 URDF joints plus IMU from live `/joint_states`, and an animated kinematic wireframe with sensor and field-of-view markers), a read-only RViz/Foxglove-style engineering panel, an in-IDE requirement board, and plan-anywhere over the global DEM | | |

## Mission planning

| Shipped and load-bearing | Training-only or offline | Unbuilt and gated |
|---|---|---|
| Cut-fill min-cost transport over a hazard-routed cost matrix, bulking conserved (`lode/mission_planner.py`) | The RL scheduler (`SchedulerEnv`, PPO, beam, distill) is not in the deployed planner; greedy and Held-Karp tie or beat it on single-objective tasks (the empirical finding) | Cross-vehicle precedence chain-splitting plus active work-reallocation on a stranded rover (detection and the replan trigger exist) |
| Hazard-aware slip-weighted Dijkstra routing plus keep-outs and a negative-obstacle mask (`planner_routing.py`) | | Optimal joint fleet re-ordering (today's resolution is conservative FCFS re-sequencing) |
| A TSP family with honest optimality labels (nearest, 2opt, or-opt, LK, brute, Held-Karp) | | Slip-band uncertainty fold-in, blocked on the PyChrono calibration oracle |
| Reserve-aware battery recharge; one immutable plan result threaded through run, timeline, plan IR, and acceptance | | Sinter (real and tested, gated off by a flag); material and ice-dependent dig energy (uniform for now) |
| A versioned executable plan IR; acceptance as additive inspectable checks (flatness, berm profile, bearing and compaction, repose, and mass, time, and energy against the as-built terrain) | | |
| Multi-vehicle allocation plus parallel makespan and an exact small-fleet oracle; fleet conflict detection and FCFS re-sequencing over site, temporal, and haul-path conflicts | | |
| Joint shared-resource scheduling: charger, pit, dump, vantage, and corridor as capacity-limited servers against one reservation ledger, waits folded into the makespan | | |

## Simulation and physics

| Shipped and load-bearing | Training-only or offline | Unbuilt and gated |
|---|---|---|
| Conserved mass as the invariant, height re-derived, a runtime guard on every mutation (`stewie/physics/column_state.py`) | The 4 construction and drive Gymnasium envs plus the CEM and PPO trainers (real, tested, gym-optional) | Tier-3 force-accurate drum excavation (needs a Chrono GPU DEM, not in-repo) |
| Load-bearing Bekker pressure-sinkage as the live drive-loop default (`terramechanics.py`, `drive.py`) | The Godot 3D render and sensor track (real, on-disk binary), which runs offline, not in the drive loop | The live Project Chrono soil producer (the exporter is a self-labeled stub; PyChrono is absent) |
| A real slip ladder with discrete entrapment (Coulomb-Mohr, Janosi-Hanamoto) (`slip.py`) | | Quantitative terramechanics calibration, blocked on the unavailable PyChrono oracle |
| Drum mass-inference grounded in real ICE-RASSOR data, no fabricated coefficients (`rassor_mass_model.py`) | | PSR and volatile (ice) optics, a wired-but-inert schema slot |
| The weight-coupling chain (drum fill to load to sinkage to slip) wired end to end; per-body gravity | | |

## Perception

| Shipped and load-bearing | Training-only or offline | Unbuilt and gated |
|---|---|---|
| The perception loop (the differentiator): the observed-map producer closes the loop on perception, not just action — a rover observes its own terrain change through a real render (`dart/observed_map.py`) and the map-channel scores the observed map against the conserved truth, so the localized observed-versus-truth divergence is a self-made hazard an open-loop generator cannot produce; the deterministic end-to-end replay loop (`stewie/runtime/replay_loop.py`, RS-04) reacts to a seeded hazard with a reroute or a logged refusal, path-dependent and mass-conserving | Forward passive stereo (`dart/stereo_depth.py`, real cv2 SGBM) consumed by the eval gates, sparse and container-gated, not a live producer | The dense reconstruction tier (render to stereo or COLMAP RMSE, reconstructed map versus truth); the live-ROS closure (RS-05/RS-06) |
| The cheap in-loop observability map channel (route coverage and per-cell uncertainty from conserved truth; a low-coverage dig site triggers observe-more before it commits) | AprilTag 12.7 mm / 7.15 degrees end to end, container-gated, not reproducible in default CI | The dense render to depth to point-cloud perception producer |
| Terrain scan-match and AprilTag-beacon localization fixes in the closed loop (`lode/autonomy.py`) | | |
| A typed navigation factor contract: accepted estimator evidence carries factor type, covariance, frame, source, and evidence class (`dart/factors.py`, `dart/evidence_ledger.py`); metric shadow-length and boundary claims are blocked behind a negative-residual artifact | | Truth-free operational SLAM at centimeter parity (the real Katwijk ATE is 3.35 m; map visibility is not operational parity) |

## Cockpit and UI

| Shipped and load-bearing | Training-only or offline | Unbuilt and gated |
|---|---|---|
| Full Plan-tab authoring: on-map edit, a top-down order canvas, a build queue, templates, keep-outs, precedence, solvers, and load to plan to embedded report | | Live rover telemetry (the Execute pane plays back a simulated run over a stream, an explicit conserved-authority execution, not hardware), gated on the ROS2 bridge |
| The ConOps tab spine (Plan, Rehearse, Validate, Release, Execute, Report) plus the role-gated secondary cluster; inside Plan, a wizard stepper gates Review and Execute behind a plan | | Operational-constraints authoring (time, sun, comms window, slope budget); the backend exists, the UI exposure is pending |
| The requirement board: the committed matrix and dispatch briefs projected read-only, with a bucket filter deck, an inspect panel, and provenance hashes on the page | | A true live-versus-sim overlay, gated on the ROS2 bridge plus streaming telemetry |
| An in-cockpit 3D terrain dry-run (real DEM heightfield plus rover and truth or estimate paths), which is a simulation dry-run, not a live rover | | |

## Autonomy, infrastructure, and access

| Shipped and load-bearing | Training-only or offline | Unbuilt and gated |
|---|---|---|
| A four-tier role ladder (guest, trainee, operator, director) with capability gating | | A live rclpy node joining the ROS2 graph plus a real pit transport, the binding gate dependency, externally blocked on the pit link details |
| A full control panel: create, approve, role, revoke, reset, and delete operators, plus invite tokens and an audit log | | The live-execute fault-injection tier; a deployed-browser GIS smoke test |
| Sandbox and live workspace separation; real rover instructions gated to a live mission plus operator-or-above plus the safing watchdog | | |
| The command-timeout safing watchdog plus the ROS2 translation layer (`stewie/bridge/ros2_bridge.py`, tested) | | |
| The digital-twin unification: a completed simulated run folds its conserved terrain delta into terrain memory and records belief and authority in one hash-chained world-transaction log | | |

---

**The phase-1 gate (ROS2 bridge to a Docker intern beta):** the safing watchdog, the command contract,
and the translation layer are done and tested; what remains is the live rclpy node and the real pit
transport, both gated externally on the pit link details (an integration, not a design unknown). The
end-to-end intern beta is therefore not claimable today.

**On the roadmap (planned, not shipped):** persistence is moving to a hybrid Postgres plus PostGIS store.
Today the edit-session is a server-owned, versioned, in-memory source of truth (before/after audit plus
undo); the durable, database-backed layer (Phase 0) is in progress. It is named here as a direction, not
a claim of a shipped datastore.

**What not to claim:** RL beating greedy on single-objective tasks; the 3D dry-run as live; map
visibility as operational SLAM parity; the dense reconstruction RMSE tier as in-loop; a durable database
as shipped. These are the honesty traps the matrix above guards.
