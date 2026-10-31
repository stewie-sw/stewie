# STEWIE as a QGIS-centered closed-loop lunar-construction platform (2026-07-07)

> Aaron's architecture direction, recorded verbatim-in-substance as the plan of record. The reframe:
> **QGIS is the scientific mission-planning + geospatial-intelligence + analysis workbench — not a viewer.**
> Godot/RViz/Gazebo are the 3D operational/physics views. **STEWIE is the orchestration layer + the
> versioned lunar world model (the system of record).** The loop: QGIS plans against the current world →
> STEWIE executes via ROS2/Godot/Gazebo → live rover feedback updates the GIS layers → replan.

> **Current authority correction, 2026-07-28.** QGIS and PostGIS expose derived, version-attributed
> views. Executed construction events, observation evidence, dependency graphs, decisions, and
> accepted-world versions form the canonical ledger. Rover feedback creates evidence; it does not
> directly update accepted terrain. The live `/twin/resync` path still bypasses that target decision
> seam. See ADR-0008 and `../docs/construction_event_ledger_contract.md`.

## The closed loop

```
Mission Planning (QGIS: authoring + scientific analysis)
        │
        ▼
Canonical ledger + accepted versions                ← DA-07--DA-10 target; not yet complete
        │
        ▼
PostGIS / GeoPackage projections                     ← durable/queryable views, not authority
        │
        ▼
STEWIE World Model (versioned, temporal, provenance)  ← DT-01 world-txn + Terrain Memory + BR-01 branches ✓
        │
 ┌──────┼──────┬──────────┐
 ▼      ▼      ▼          ▼
ROS2  Godot  Digital-Twin  ML pipeline
 │
 ▼
Live rover feedback → observation evidence → decision → accepted version → updated GIS projections
                    → next Mission snapshot → replan / retrain
```

Every executed mission action is **preserved and versioned**; physical mutation remains under the
conserved authority, accepted belief requires a recorded decision, and GIS views are never the write path.
`Moon → Mission 000 → 001 → … → 125`, branchable, replayable, trainable.

## The eight thematic QGIS projects (not one giant map)

1. **Base Mapping** (rarely changes) — orthomosaics, DEMs, slope, hillshade, illumination, **PSR**, peaks-of-
   persistent-light, grids, landing zones. *Environmental priors.*
2. **Terrain Analysis** (DEM-derived) — slope/aspect/curvature/roughness, rock abundance, traversability,
   sinkage, wheel-slip, bearing capacity, excavation difficulty → **planning cost maps.**
3. **ISRU Resources** (mission-specific) — H probability, water-ice confidence, regolith maturity, mineralogy,
   ilmenite, volatiles, excavation priority, scientific value. *Each cell stores confidence + provenance.*
4. **Infrastructure Planning** (human-intended) — roads, berms, pads, solar arrays, habitats, cable routes,
   comms towers, storage, excavation boundaries, dump sites → planned geometry STEWIE tracks through execution.
5. **Rover Operations** (dynamic, from ROS2) — trajectories, wheel tracks, dig/dump locations, traversed cells,
   energy, localization confidence, sensor coverage, comms quality.
6. **World-State Layers** (STEWIE's uniqueness) — every terrain cell carries *temporal state*: elevation,
   slope, compaction, excavated depth, last-updated, confidence, responsible rover, mission id. **Changes are
   stored, not overwritten.**
7. **Risk Layers** (auto-generated) — high-sinkage, shadow, boulder, high-slip, poor-visibility, thermal,
   battery, comms-blackout → combined into navigation cost.
8. **Mission Planning Layers** (human-authored) — waypoints, survey regions, dig polygons, sample targets,
   construction tasks, no-go zones, science regions, emergency routes.

## STEWIE as Python-powered QGIS Processing algorithms  (← "script + automate tasks")

The core move: **every STEWIE analysis is a Python QGIS Processing algorithm**, version-controlled and callable
from (a) the QGIS GUI one-click, (b) the command line / batch, (c) CI, (d) the ROS2 autonomy pipeline. That is
exactly the scripting + automation surface — analyses become reproducible, testable, and pipeline-callable.
Chain them into **Processing Models** (graphical workflows), e.g.:

```
Import DEM → Clean → Slope → Roughness → Rock detection → Terramechanics → Traversability cost → Path plan → Mission package
```

Every step documented, rerunnable with identical parameters. **Reproducibility is mandatory** — each run records
inputs+versions, algorithm+version, parameters, CRS, software version, timestamp, operator/agent, output paths,
random seed, runtime, and a processing log → a complete provenance record (this is STEWIE's `EV-01` evidence
bundle, generalized to every analysis).

## Tool palettes / Analysis Profiles (users see only their mission's tools)

Data Management · Terrain Analysis · **Terramechanics** (STEWIE custom: sinkage/slip/drawbar/bearing/
compaction/rolling-resistance/excavation-resistance/energy-per-m/energy-per-m³/trafficability) · Navigation
(cost-distance, least-cost path, multi-objective routing, reachability, safe-stopping, risk heatmaps) · ISRU
Planning (cut/fill, haul, berm/stockpile volume, resource confidence, dig priority, production forecast) ·
Scientific (raster/vector calc, spatial stats, interpolation, clustering, PCA, time-series, change detection) ·
Perception Evaluation (stereo coverage, overlap, feature density, occlusion, shadow quality, registration) ·
Digital-Twin Validation (elevation/excavation/path/localization/energy/slip *prediction-vs-reality* error) ·
Mission Analytics (distance, energy, volume, avg slip, duration, utilization, hazards) · Machine Learning
(traversability/segmentation/rock/hazard/object/semantic/anomaly outputs).

## What STEWIE ALREADY has (the vision is ~60% built)

- **PostGIS world DB** → Phase-0 durable Postgres (`stewie/server/db.py`) is the first brick.
- **Versioned/temporal world state** → DT-01 world-transaction chain, Terrain Memory (versioned as-built .npz),
  BR-01 named branches (actual/observed/predicted/sim/design/what-if), the SIM execute→remember loop.
- **The thematic layers** → the 66-row `layer_catalog.json` already spans base/terrain/hazard/regolith/physics/
  mission/design/robot/runtime/evidence with per-layer source-class + freshness + eligibility.
- **Terramechanics analyses** → conserved Bekker/slip/bearing/energy in `stewie/physics` + `forge` (served as
  the physics/terrain/hazard rasters).
- **Reproducibility** → `EV-01` evidence bundle + the DT-01 provenance chain.
- **PSR / illumination** → `dart/illumination.py:psr_gate()` (<110 K cold-trap), `terrain.psr/shadow/illumination`.
- **QGIS Server** → already renders the `.qgz` as OGC services behind the web IDE.

## The NEW work (what the vision adds)

1. **A STEWIE QGIS Processing provider** — the terramechanics/ISRU/navigation analyses as Python Processing
   algorithms (GUI + CLI + CI + ROS2 callable). *This is the scripting/automation ask + the plugin thread.*
2. **QGIS Desktop as the authoring/analysis workbench** — the thematic projects + tool palettes + Model Builder,
   over the same FastAPI/PostGIS backend the web IDE uses (one source of truth).
3. **Fill the geometry gaps via QGIS** — LOS/viewshed (`r.viewshed`→`terrain.los`), contours (GDAL), least-cost
   path — mature QGIS algorithms instead of building from scratch.
4. **1 m imagery** — link LROC NAC (0.5–2 m) regional mosaics for the sites (NASA Trek WMTS / a site NAC drape);
   NAC is regional, not a seamless global mosaic (whole-moon stays ~100 m WAC / ~10 m Kaguya TC).
5. **Formalize reproducibility/provenance** on every analysis (the record above) + **mission-snapshot
   versioning** as the branchable unit (Mission 000…N) for replay + ML.
6. **Resource cross-sections** (#45) + the civil analyze panel (#41) as Processing outputs.

## Incremental execution (proposed phases)

- **P-A — STEWIE Processing provider POC**: a `stewie_qgis/` Python plugin registering 2 algorithms
  (`STEWIE: Load Site DEM`, `STEWIE: Terramechanics/Traversability`) that call the live FastAPI backend; runnable
  from GUI + `qgis_process` CLI + a CI test. Proves the scripting/automation + reproducibility pattern.
- **P-B — thematic project templates**: the 8 `.qgz` project templates wired to the STEWIE layer catalog + the
  PostGIS store.
- **P-C — 1 m NAC imagery** linked for the sites; **LOS/contours** via QGIS Processing → fill `terrain.los`.
- **P-D — mission-snapshot versioning** as the branchable world-state unit (replay + ML training).
- **P-E — the closed loop end-to-end**: QGIS plan → PostGIS → STEWIE → ROS2/Godot → feedback → updated layers.

*License note: a QGIS Processing plugin can ship + be distributed privately now; the public QGIS FOSS portal
needs an OSI license (STEWIE is all-rights-reserved) — a separate decision. Keep STEWIE's physics core the
authority; use QGIS for geometry + the workbench, never re-implement the conserved physics in QGIS.*
