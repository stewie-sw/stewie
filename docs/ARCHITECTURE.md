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

- **The GIS mission-control IDE** (QGIS Web Client 2), served at `artemis.stewie.space/ide/` (the bare
  `artemis.stewie.space` redirects there, so the IDE is the single front door). One persistent lunar map
  with layers, selection, editing, and analysis is the primary surface, and Plan, Rehearse, Validate,
  Release, Execute are mission-lifecycle overlays on that map. Mission edits (cut/fill build orders,
  structures, keep-outs, traverse waypoints, return-to-lander, placed objects) are written only through
  a server-owned, versioned edit-session (before/after audit plus linear undo); the map layer is not the
  authority. A QGIS Server renders the pole-truthful raster and vector layers; the browser reaches the
  backend through same-origin `/api/*` routes and reads read-only ROS2 telemetry over a rosbridge
  WebSocket (the RViz/Foxglove-style engineering panel is evidence-only, no command egress).
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

- **Authority is separated by claim.** The conserved-physics world model is authoritative for
  simulated physical mutation. Sensors and estimators produce observation evidence, not truth.
  Accepted belief advances only through a recorded decision and immutable world version in the target
  DA-07--DA-10 architecture. GIS surfaces (QGIS, QGIS Server, OGC, and any imported ArcGIS or GeoJSON
  layer) are persistence, query, and interop projections, never mutation or acceptance authority. A
  layer must pass CRS and frame validation before it can influence planning, and a display-only layer
  cannot be marked planning-valid.
- **Actions are events, not layer authority.** Every executed construction action belongs in an
  immutable spatial-temporal ledger. Stable GIS layers aggregate or project those events by mission,
  time, asset, action, or accepted-world delta and carry their source version. See
  [ADR-0008](adr/0008-construction-event-ledger-and-gis-projections.md) and the
  [ledger contract](construction_event_ledger_contract.md).
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

The current dissertation lens is narrower than the platform. Multiple robots modify shared terrain and
then observe it; their evidence may be dependent through source identity, localization, timing,
registration, calibration, preprocessing, or shared construction provenance. The research path builds
a per-cell possible-dependency graph, constructs an observation-only mean, permits physics only to
veto, and proves a conditional harmful-promotion bound under explicit assumptions.

That research path is not the operational merge today. `POST /twin/resync` still applies an observed
patch without calling the theorem-facing rule, and `CurrentTerrainView` gives observed cells
precedence. DA-07--DA-10 close the bridge by binding immutable action/evidence records to a candidate,
decision, and atomically published accepted-world version. The probability theorem remains
conditional on calibration and covariance premises; shared action is evidence of possible dependence,
not itself a causal sensor-error model.

## Honest status

- **Live and load-bearing:** the GIS IDE, mission authoring and planning, the conserved-physics core,
  the analysis layers, the digital twin (a completed simulated run folds its conserved terrain delta
  into terrain memory and records belief and authority in one hash-chained world-transaction log), the
  perception loop (a rover observes its own terrain change through a real render and reacts to the
  self-made hazard, path-dependent and mass-conserving, at the cheap in-loop tier), and plan-anywhere
  over the global DEM. The deploy is simulation-only and mission Release is director-gated.
- **Research-only integration:** `stewie/twin/promotion.py` implements the per-cell dependency graph,
  observation-only accepted value, and veto-only physics rule with regression and mutation gates. It
  does not govern live resync or accepted-world publication.
- **Progress:** generated `STATUS.md`/`STATUS.json` report current matrix and citation counts, and
  `release_manifest.json` reports release traceability. This narrative intentionally carries no
  hand-maintained completion percentage. The full split is the [capability matrix](CAPABILITIES.md).
- **On the roadmap (planned, not built):** the complete construction/evidence ledger, atomic accepted
  world publication, cold replay, and version-attributed GIS projections. Durable edit sessions and a
  world-transaction projection exist; they do not by themselves implement DA-07--DA-10.
- **Designed, not built:** a live ROS2 and Gazebo pit with a real rover (the containers build; there is
  no live pit link yet), the live Project Chrono producer and the Tier-3 drum-force track (the PyChrono
  force oracle is a stub), dense-stereo GPU and point-cloud perception, the dense map-channel RMSE tier,
  LAC/IPEx arm geometry, and camera video. The STEWIE-Orbit CCSDS comms stack is intent-only.

## Where to read next

- The canonical design source is the product requirements
  ([`PRD.md`](https://github.com/stewie-sw/stewie/blob/main/PRD.md)): section 6 is the target
  architecture, section 7 is the requirement matrix, and section 7.B is the GIS mission-workbench target.
- The honest capability split is the [capability matrix](CAPABILITIES.md).
- The target operational evidence seam is the
  [construction-event ledger contract](construction_event_ledger_contract.md).
- The conserved-vs-learned design decision is the [world model](world_model.md).
- The modelled vehicle is [IPEx](vehicle_ipex.md); the physics-authority producer is
  [Chrono integration](chrono_integration.md); the render and sensor seam is the
  [sensor-bridge contract](sensor_bridge_contract.md).
