# STEWIE architecture (honest index)

STEWIE is a lunar surface-construction platform: a GIS mission map, a versioned digital twin, a
conserved-physics terramechanics core, an energy-aware mission planner, and an autonomy and runtime
middleware layer, all over one workspace context. This page is the governing index over the
architecture: the running shape, the load-bearing decisions, and an honest split of what is designed
versus built. Where this page and the code disagree, the code wins.

## The running shape (two processes, GIS-first)

A single Python FastAPI backend is the authority and the sidecar at once. It owns the conserved-physics
world model, the planner, the digital twin, the evaluation gates, and roughly 140 HTTP routes. Two web
front ends consume it today:

- **The GIS mission-control IDE** (QGIS Web Client 2), served at `artemis.stewie.space/ide/`. It is the
  front door: one persistent lunar map with layers, selection, editing, and analysis as the primary
  surface, and Plan, Rehearse, Validate, Release, Execute as mission-lifecycle overlays on that map. A
  QGIS Server renders the pole-truthful raster and vector layers; the browser reaches the backend
  through same-origin `/api/*` routes and reads read-only ROS2 telemetry over a rosbridge WebSocket.
- **The single-page cockpit**, served at `app.stewie.space`. It is the earlier operational surface (the
  ConOps spine plus the requirement board) and stays live while the migration onto the GIS IDE proceeds
  pane by pane.

```
  artemis.stewie.space/ide/   ->  QWC2 GIS IDE  ->  QGIS Server (/ows layers)
                                              \->  FastAPI backend (/api plan, structure, run, world)
                                              \->  rosbridge (RT-04 read-only telemetry)

  app.stewie.space/app        ->  cockpit SPA   ->  FastAPI backend
```

Both public hosts sit behind Cloudflare and a cloudflared tunnel; the deploy is simulation-only. The
run commands and the cache and TLS rules are in the deploy runbook
([`deploy/DEPLOY.md`](https://github.com/stewie-sw/stewie/blob/main/deploy/DEPLOY.md)).

## Load-bearing decisions

- **The conserved-physics world model is the source of truth.** GIS surfaces (QGIS, QGIS Server, OGC,
  and any imported ArcGIS or GeoJSON layer) are a persistence, query, and interop boundary, never the
  authority. A layer must pass CRS and frame validation before it can influence planning, and a
  display-only layer cannot be marked planning-valid.
- **Lunar coordinates stay lunar.** The map works in the Moon south-polar stereographic frame
  (`IAU_2015:30135`), so the pole is the center of the canvas and no WGS84 or Earth claim is made on a
  lunar position. This is what the QWC2 spike proved before the incremental adoption began.
- **Mass is the invariant.** Every authority mutation is transactional and conserves mass; height is
  re-derived, and a runtime guard rejects any mutation that would not conserve mass.
- **Authority is a property of the environment mode, not a toggle.** The planning and command layers
  are governed centrally so a training session can never cross into live command (see the operational
  layers below).
- **Monorepo, not many repos.** The subsystems are clean-interfaced modules in one tree; only the two
  low-coupling, citable packages (the planetary body registry and the physics services) are candidates
  for standalone publication.

## Subsystems

| Subsystem | Package | What the code does |
|---|---|---|
| **DART** | `dart/` | Perception, estimation, and localization: DEM anchoring, stereo and shadow geometry, articulated parallax, the pose-graph estimator, the evidence ledger |
| **LODE** | `lode/` | Operations and planning: the mission planner, hazard-aware routing, the executive and mission lifecycle, fleet coordination, autonomy, acceptance |
| **LEAP** | `leap/` | Earthmoving and construction: excavation skills, worksite and terrain-target environments, structures, site plans, volume evidence |
| **FORGE** | `forge/` | Physics and terramechanics services; the conserved core itself lives in `stewie/physics` |
| **`stewie/`** | platform core | Conserved physics, terrain, the versioned twin, specs, the Gymnasium envs, the FastAPI server, the sensor and runtime bridges, the Godot render sidecar, and the evaluation gates |

**STEWIE-Orbit** (communications and observation) is the planned orbital layer and is design-stage, not
built.

## Operational layers

Two governance and planning layers are specified in the product requirements and partly built:

- **Environment-governed operations.** Authority is a property of the environment mode (DEV, TRAINING,
  REHEARSAL, LIVE, REPLAY, ARCHIVE) enforced centrally, with a per-mode authority matrix, isolated
  database and branch namespaces, a role model, and a training-to-live gate. The ROS2 bridge is the
  sole real-robot egress, and a command-timeout safing watchdog is the dead-man interlock on the
  command path.
- **The mission-planning engine.** Planning chooses actions that transform the world, not a path: intent
  to tasks to capability match to candidate plans to physics scoring to rehearsal to approval to
  execution to reconciliation to an updated world model, over an executability gate and a typed object
  model. Volume, route, and risk values are attributed to a physics backend and a calibration source; a
  value with no backend attribution is not release-eligible.

## Conceptual frame (the dissertation lens)

At the theory level, STEWIE reads as a planetary state inference engine: the physical planet has an
unknown true state, and everything the platform does reduces uncertainty about it. The world stores
belief, not reality (every world object carries identity, belief, evidence, confidence, and
alternatives), every algorithm is an estimator with a common semantic contract, and the world graph
generalizes to a factor graph. The unification is at the semantic level (belief, evidence, confidence,
provenance), not the algorithmic level: localization uses factor graphs, terramechanics stays
deterministic and analytical in FORGE, planning uses graph search, and learned perception uses neural
networks. This frame centers the navigation dissertation (the articulated-rover state estimator) at the
core of the platform rather than at its periphery.

## Honest status

- **Live and load-bearing:** the GIS IDE, mission authoring and planning, the conserved-physics core,
  the analysis layers, the digital twin (a completed simulated run folds its conserved terrain delta
  into terrain memory and records belief and authority in one hash-chained world-transaction log), and
  plan-anywhere over the global DEM. The deploy is simulation-only and mission Release is director-gated.
- **Progress:** the requirement matrix (product requirements, section 7) reads 251 of 339 verified done
  (about 74 percent overall; 77 percent of the 325 in-scope rows). The full split is the
  [capability matrix](CAPABILITIES.md).
- **Designed, not built:** a live ROS2 and Gazebo pit with a real rover (the containers build; there is
  no live pit link yet), the live Project Chrono producer and the Tier-3 drum-force track (the PyChrono
  force oracle is a stub), dense-range and point-cloud perception, and the dense map-channel reward. The
  STEWIE-Orbit CCSDS comms stack is intent-only.

## Where to read next

- The canonical design source is the product requirements
  ([`PRD.md`](https://github.com/stewie-sw/stewie/blob/main/PRD.md)): section 6 is the target
  architecture, section 7 is the requirement matrix, and section 7.B is the GIS mission-workbench target.
- The honest capability split is the [capability matrix](CAPABILITIES.md).
- The conserved-vs-learned design decision is the [world model](world_model.md).
- The modelled vehicle is [IPEx](vehicle_ipex.md); the physics-authority producer is
  [Chrono integration](chrono_integration.md); the render and sensor seam is the
  [sensor-bridge contract](sensor_bridge_contract.md).
