# STEWIE Backend-Architecture Reconciliation: Aaron's QGIS-Kernel Vision vs the Real Code + the Design Deliverable

**Date:** 2026-07-06
**Repo HEAD:** `14ecade` ("ROS egress: advisory occupancy/costmap/path exports + MapMeta georef") on `main`
**Grounding design doc:** `design/STEWIE_LUNAR_PLATFORM_DESIGN_2026-07-06.md` (committed `250c0c9`, the 40/24/5 capability matrix + 15-service map + PostGIS/Timescale data model)
**Purpose:** map Aaron's detailed backend spec (QGIS-as-geospatial-kernel, STEWIE as mission/world-state layer; GeoAI map-intelligence; Autoware-inspired autonomy) onto (a) the REAL current code at HEAD `14ecade` and (b) the existing design deliverable, and update the roadmap.

**Evidence convention.** Every EXISTS / PARTIAL verdict cites a real `file:line` I opened at HEAD `14ecade` (marked *confirmed*). NEW verdicts and forward-roadmap claims are *inferred design*. Where I reuse the design doc's own evidence I say so. I did not touch code and did not commit.

---

## 0. The delta since the design doc was written (read this first)

The design doc (`250c0c9`) was committed **before** the two most recent code commits. Those two commits close four of its five outright-Missing capabilities:

- **`534af04` — TW-11 TrafficMemory** (per-cell traversal hardening -> `traffic.compaction` layer). *Confirmed:* `stewie/twin/traffic_memory.py:79` (`class TrafficMemory`), folded on run completion at `stewie/server/routers/executive.py:195,272`, read out at `stewie/server/routers/world.py:61`, bound into the spine at `stewie/specs/terramechanics_spine.py:88-89`, catalog row at `stewie/server/layer_catalog.json:285` (`traffic.compaction`).
- **`14ecade` — ROS egress** (advisory occupancy/costmap/path + MapMeta georef). *Confirmed:* lowering compute in `stewie/bridge/ros_export.py` (`occupancy_grid_msg:79`, `costmap_msgs:200`, `gridmap_msg:156`, `path_msg` block from `:213`, `occupancy_values:56`); HTTP egress routes in `stewie/server/routers/nav.py:127` (`/ros/export/occupancy` `[REQ:AS-10]`), `:154` (`/ros/export/costmap` `[REQ:AS-11]`), `:194` (`/ros/export/path` `[REQ:NV-11]`), latched MapMeta at `nav.py:109-115`.

**Revised tally.** The design's "Existing 40 / Partial 24 / **Missing 5**" (design line 90) is now effectively **Missing 1**. The five Missing rows were: (1) backend TW-11 traffic, (2) the frontend terramechanics spatial-overlay renderer, (3) ROS occupancy-grid, (4) ROS cost-map, (5) ROS waypoint `nav_msgs/Path`. Commits `534af04` + `14ecade` close (1),(3),(4),(5). The **only** still-Missing item is (2), the frontend terramechanics-overlay renderer, which is a frontend-rebind item (QWC2), already the subject of the in-progress GIS/QWC2 frontend work. This is the single most load-bearing fact for the roadmap below: Aaron's backend targets that the design flagged as gaps are, on the backend side, already built.

Honest caveat on the ROS egress: what is closed is the **lowering + the `/ros/export/*` routes** (pure, testable without a ROS2 runtime; `stewie/bridge/test_ros_export.py` present). The **live publish onto a real ROS2 host** remains container-gated, but that was always the gated tier, not the "Missing capability" the design named ("numpy products unbridged to `/stewie/*`", design line 964). The bridge now exists.

---

## 1. Mapping table: Aaron's 10 services + GeoAI + 8 Autoware modules

Verdicts: **EXISTS** (reuse verbatim, real producer on disk), **PARTIAL** (real producer exists; a persisted format / served route / thin adapter is missing), **NEW** (genuinely absent). Expectation from the design was ~80% EXISTS/PARTIAL; the actual split below is **~85%** (of 18 rows: 6 EXISTS, 9 PARTIAL, 3 NEW).

### Aaron's 10 proposed services

| # | Aaron's service | Verdict | Real evidence (file:line, confirmed at HEAD `14ecade`) | One-line reconciliation |
|---|---|---|---|---|
| 1 | **stewie-qgis-core** (PyQGIS engine: load/create .qgz, style, `run_processing_algorithm` slope/aspect/hillshade/raster-calc/clip/reproject/contour/polygonize/zonal, generate_tiles, export_geotiff/geopackage/ros_costmap) | **PARTIAL** | PyQGIS is already an internal engine, scoped to the project builder: `gis/build_project.py:383` (`from qgis.core import ...`), `:415` (`import processing`), `:430` (`QgsProject.instance()`), `:515` (`processing.run("gdal:hillshade", ...)`), `:526` (`addMapLayer`). geoai/QGIS stack lives in `.venv-gis`. | The PyQGIS-as-engine pattern EXISTS but only builds DEM/hillshade/slope COGs + styling into `stewie_south_pole.qgz`. Aaron's generic `run_processing_algorithm` wrapper (slope/aspect/clip/reproject/contour/polygonize/zonal-stats/export_ros_costmap) is a genuine **NEW** thin service that generalizes `make_hillshade` (see §3.c). |
| 2 | **stewie-map-server** (QGIS Server per-mission WMS/WFS/WCS/WMTS/OGC-API-Features) | **PARTIAL** | OGC WMS 1.3.0 GetCapabilities/GetMap is hand-rolled in FastAPI at `stewie/server/routers/ogc.py:56`; Cesium 3D Tiles at `stewie/server/routers/tiles.py:25`; server-reprojected globe drape at `stewie/server/routers/layers.py:104,132`; QWC2 theme server config under `gis/qwc2/` + `gis/SERVER.md`. | The WMS surface and tile serving EXIST as FastAPI routes, not as QGIS Server. Aaron's full OGC suite (WFS/WCS/WMTS/OGC-API-Features + a QGIS-Server sidecar per mission) is the design's Tile-Serving §2 "add XYZ/WMTS + MVT" gap plus a QGIS-Server option. Reconcile: keep the FastAPI WMS/tiles, add WMTS/MVT (design line 861), and only stand up QGIS Server if per-mission `.qgz`-driven WFS/WCS is actually needed. |
| 3 | **Layer Registry** + PostGIS `map_layers` table | **PARTIAL** | The registry EXISTS as `stewie/server/layer_catalog.json` (65 rows) served at `stewie/server/routers/world.py:32` (`/world/layer-catalog`) + `:82` (`/world/terramechanics-layers`). The **PostGIS `map_layer` table** is NEW (fully designed: design §4.2 `CREATE TABLE map_layer`, lines 1386-1404). | The single-source-of-truth registry already exists; Aaron's SQL `map_layers(id, mission_id, name, layer_type, qgis_layer_id, source_uri, data_format, crs, zoom, opacity, style_json, metadata)` is the design's `map_layer` projection of that JSON. Reuse: mirror the JSON into the table, do not fork the schema. |
| 4 | **Mission-state PostGIS** (missions, map_layers, rovers, tasks, task_geometries, waypoints, paths, path_segments, terrain_cells, terrain_change_events, traffic_events, simulation_runs, validation_reports, ros_export_packages); PostGIS = "operational source of truth" | **PARTIAL** | Mission CRUD + lifecycle EXIST: `stewie/server/routers/missions.py` (CRUD/publish/restore), `stewie/server/routers/executive.py:41,100` (MO-01 advance/release). Write authority is the file-store + hash-chained journals (`objects.py`, `world_state.py`; design §0 line 749-755). The **PostGIS relational schema** is NEW (design §4 gives DDL for all 15 entities). | The domain exists; the SQL is NEW. **One correction to Aaron's framing (evidence-backed):** PostGIS is a **projected read model, NOT the operational source of truth** (see §2.b). The DT-01 hash-chained journals + `.npz` stay the write authority; PostGIS is rebuildable from them. Every entity Aaron lists maps to a design §4 table. |
| 5 | **terrain-cell / world-state engine** (`terrain_cells` table: elevation/slope/roughness/hazard/traversability/sinkage_risk/slip_risk/bearing_strength/traffic_count/compaction/excavation_delta/confidence) | **PARTIAL** | The per-cell world state EXISTS as the mass-conserving numpy authority: `stewie/twin/terrain_memory.py` (`TerrainMemory` `.npz` + chain) + the spine fields at `stewie/specs/terramechanics_spine.py` + `stewie/server/routers/world.py:82`. The **`terrain_cells` SQL table** is NEW (design §4.3: a 10-band `terrain_cell_raster` mirror, lines 1406-1418). | The hot grid EXISTS in `.npz` and MUST stay there (mass conservation, sub-ms step). Aaron's `terrain_cells` is a **projection** of that grid, not a replacement (see §2.c). His `traffic_count`/`compaction`/`bearing_strength` columns are now backed by the just-committed TrafficMemory (`traffic_memory.py:180` relative-density Dr, `:185` bearing-uplift). |
| 6 | **stewie-terramechanics** (evaluate-path, evaluate-dig-zone, update-traffic, update-compaction; layers -> sinkage/slip/energy/compaction/dig_feasibility/traffic_hardening `.tif`) | **EXISTS** (compute) / **PARTIAL** (endpoints) | Conserved solver: `packages/stewie-forge/stewie_forge/terramechanics.py` (`physical_compaction_field:255`, `_RHO_DEEP=1920:61`); 11 derived layers served at `world.py:82`; traffic-hardening now real via `traffic_memory.py:79` + spine `terramechanics_spine.py:88`. | The physics + layer set EXIST and are load-bearing (do NOT touch the solver, §2.a). Aaron's `evaluate-path` / `evaluate-dig-zone` / `update-traffic` verbs are the design's NEW `POST /physics/evaluate` what-if endpoint (design line 928) + `POST /traffic/ingest` (design line 955); `update-traffic` is already implemented as the run-completion fold at `executive.py:272`. The `.tif` per-layer exports extend `/export/cog/{kind}.tif` (`gis_export.py:96`). |
| 7 | **stewie-mission-api** (missions/tasks/zones survey\|dig\|dump\|flatten/plan/simulate/validate/export-ros2/readout/timeline; a DIG_AREA command abstraction) | **PARTIAL** | plan (`stewie/server/routers/plan.py:262`), simulate/validate (`executive.py` run + reconciliation), export-ros2 (`nav.py:127/154/194`). But the verb vocabulary is `cut\|fill\|sinter` (`stewie/contracts/mission_ops.py:210,235`), and the command shapes are **three disjoint objects**: `Objective.order_kind` (`mission_ops.py:191,210`), `KeepOutRegion` (`mission_ops.py:249`), and `Order` (design cites `schemas.py:11/16`). | plan/simulate/validate/export EXIST. Aaron's `survey\|dig\|dump\|flatten` + `DIG_AREA` abstraction + a **single unified operator-command Task** is the design's NEW unified 10-verb `Task` (design §0 line 1243-1245, §4 JSON schema line 1790-1820). This is the one genuinely-new domain object; today's vocabulary is narrower (`cut/fill/sinter`) and split across three shapes. |
| 8 | **stewie-path-engine** (cost = distance+slope+hazard+sinkage+slip+energy+shadow **- hardened_traffic_bonus**; outputs nav_msgs/Path, costmap_2d, GeoJSON/GeoPackage) | **PARTIAL** | 12-layer cost stack EXISTS: `lode/costmap_layers.py:160` `LAYERS = (_slope, _roughness, _sinkage, _slip, _tip_risk, _negative_obstacle, _illumination, _psr, _shadow_confidence, _energy, _keepout, _reservation)`. Outputs: `nav_msgs/Path` (`nav.py:194`), costmap OccupancyGrid (`nav.py:154`), GeoJSON (`gis_export.py:29`). | The cost stack + Path/costmap/GeoJSON outputs EXIST. The `- hardened_traffic_bonus` term is **NOT yet in `LAYERS`** (confirmed: no traffic term in the tuple at `costmap_layers.py:160`; grep for `traffic\|uplift\|bonus` across `lode/*.py` cost files is empty) but is now **ENABLED** by TW-11 (see §4). GeoPackage output is the design's NEW `/export/gpkg` (design line 1144). |
| 9 | **stewie-ros-bridge** (OccupancyGrid/Path/PoseStamped/MarkerArray/PointCloud2 + custom stewie_msgs; package mission.yaml/map.pgm/costmap.tif/path_ros.yaml/tasks.json/markers.rviz) | **EXISTS** (core egress) / **PARTIAL** (msg breadth + bundle) | OccupancyGrid/Path/GridMap + MapMeta egress just committed (`ros_export.py`, `nav.py:127/154/194`); translation layer `stewie/bridge/ros2_bridge.py`; `stewie_msgs` frozen; PointCloud2/points egress at `stewie/bridge/points_egress.py`; offline package at `lode/mission_package.py` + `/gis/mission-package` (`gis_export.py:201`). | The three core map/costmap/path egress + MapMeta EXIST (the design's flagship NEW rows, now done). MarkerArray + the full `mission.yaml/map.pgm/costmap.tif/markers.rviz` bundle are PARTIAL: a Nav2-shaped on-disk package generator is a thin NEW extension over the existing mission-package + gridmap-geotiff interop. |
| 10 | **Godot (operator twin/replay/before-after) / Gazebo (physics/articulation/feasibility/rehearsal) split; validation report JSON** | **PARTIAL** | Godot `/render` 503-honest without binary: `stewie/server/routers/perception.py:412` + `:57-70` (degrades to 503, never fabricates). Gazebo = evidence surface: `/ros/evidence` (`nav.py:35`). Validation JSON = executive-run reconciliation (EG-08 residual + TM-04) + G1/G2 gates. | The Godot/Gazebo split + honest gating + a validation report EXIST as evidence surfaces. Aaron's live before/after twin + `POST /sim/validate` (replay a released plan through the sim tier -> divergence vs tier2 authority) is the design's NEW Sim-Bridge endpoint (design line 987). GPU-render remains honestly gated. |

### GeoAI (map-intelligence layer)

| Capability | Verdict | Real evidence (confirmed) | Reconciliation |
|---|---|---|---|
| Learned **rock_detection / crater_detection / shadow_classification / hazard_probability / traversability / slip / sinkage / excavation_feasibility / traffic_compaction_prediction / terrain_change_detection** -> QGIS-compatible layers (.geojson/.tif/.gpkg) | **NEW** (fills PARTIAL detector rows) | No learned detector producers exist in `stewie/server/routers/perception.py` (it holds SLAM / parallax-relocalization / shadow-nav-for-**localization** at `:175`, not object detection). Catalog rows are declared but unproduced: `layer_catalog.json:197` (`hazard.rocks` "rock/obstacle detections"), `:560` (`map.rocks`). **geoai IS installed** but only in `/mnt/projects/stewie/.venv-gis/lib/python3.11/site-packages/geoai` (confirmed present); it is NOT importable from the main runtime venv and NOT in `requirements-server.lock`. | GeoAI is a genuine **NEW track** and the natural producer for the design's Partial detector rows (design capability rows "Rock/crater detection layer | Partial", line 54). Rule holds: everything GeoAI predicts becomes a registered catalog layer (`.geojson/.tif/.gpkg`) with `source_class=belief`. Provisioning note: geoai must be added to the server env or run as a sidecar in `.venv-gis`; it is not on the FastAPI import path today. |

### Autoware-inspired autonomy modules (template framing, NOT lunar-ready as-is)

| Autoware -> STEWIE module | Verdict | Real evidence (confirmed) | Reconciliation |
|---|---|---|---|
| perception -> **stewie_geoai_perception** | **NEW** | (as GeoAI row above) | The learned-detector node = the GeoAI track. |
| localization -> **stewie_lunar_localization** | **PARTIAL** (real gap) | Map-relative localization primitives exist: `perception.py:175` (parallax + shadow-tip fix), `lode/relocalization.py:24` (`schedule_relocalization_stops`), `register_to_dem` (scan-to-DEM). No continuous ESKF/SLAM state-estimator node runs. | Localization is a **real gap**: STEWIE has discrete map-relative fixes, not a continuous pose estimator. This is one of the two genuine autonomy gaps Aaron's Autoware framing usefully names. |
| prediction -> (no named module) | **NEW / genuine gap** | No moving-agent / dynamic-obstacle trajectory-prediction module found in `lode/` or `stewie/`. | **Prediction is the second genuine gap.** STEWIE handles static terrain hazards; multi-agent / moving-obstacle prediction is absent. Correctly deferred until multi-rover ops are live. |
| (semantic map) -> **stewie_semantic_mapping** | **PARTIAL** | World model + provenance: `stewie/twin/terrain_memory.py` + `world.py:170` (`/world/terrain_view` per-cell PRISTINE/AS_BUILT/OBSERVED). | Semantic mapping EXISTS as the terrain-memory world model + provenance classes; the GeoAI detector layers feed richer semantics. |
| planning -> **stewie_costmap_generator** | **EXISTS** | `lode/costmap_layers.py:160` (12-layer `compose`), egress `nav.py:154`. | Reuse verbatim; it is the costmap generator. |
| planning -> **stewie_behavior_planner** | **EXISTS** | `lode/mission_intent_compiler.py:361` (Objective -> plan lowering), `lode/mission_planner.py`, `stewie/server/routers/executive.py`. | Reuse; the mission/intent compiler + executive is the behavior planner. |
| planning -> **stewie_motion_planner** | **EXISTS** | `lode/local_planner.py:71` (`plan_local` curvature fan), `:118` (`track_arc`), `lode/nav_pipeline.py:110` (`drive_route`), `:229` (`run_navigation`), `lode/reactive_nav.py:21` (`react`). | Reuse; the local arc-fan + receding-horizon + reactive replan is the motion planner. |
| control/exec -> **stewie_task_executor** | **EXISTS** | `lode/autonomy.py`, `lode/executive.py`, `stewie/server/routers/executive.py:195` (run + TW-11 fold). | Reuse; the autonomy/executive loop is the task executor. |
| output -> **stewie_ros_bridge** | **EXISTS** | `stewie/bridge/ros_export.py` + `stewie/bridge/ros2_bridge.py` + `nav.py:127/154/194`. | Reuse (row 9). |

**Autoware framing verdict:** 5 of 8 modules map to EXISTING STEWIE code, 1 to the GeoAI NEW track, and the framing's real value is that it **names the two true gaps precisely: localization (continuous estimator) and prediction (dynamic agents).** Use Autoware as a naming/architecture template, not as importable code (it is Earth-automotive; lunar frames, comms latency, and reduced-g dynamics differ).

---

## 2. The three PRESERVE-THE-CORE reconciliations (layer over, do NOT replace)

These are the non-negotiable "do not rip-and-replace" calls the design already made; Aaron's PostGIS-first framing must layer on top of them, not through them.

### (a) Terramechanics stays the conserved `tier2_numpy` authority; QGIS Processing only for generic derivatives

The mass-conserving solver (`packages/stewie-forge/stewie_forge/terramechanics.py`, `physical_compaction_field:255`, RHO_DEEP ceiling `:61`) and the H-09 / TW-11 hardening (`stewie/twin/traffic_memory.py:79`, idempotent on telemetry event-id `:119`) are **load-bearing, not decorative** (design line 918-925, "do NOT touch the solver"). Aaron's `stewie-qgis-core` `run_processing_algorithm` may compute **generic GIS derivatives** (slope/aspect/hillshade/roughness/contour/reproject) via QGIS/GDAL, but the physics terms (sinkage/slip/bearing/compaction/dig-feasibility) MUST come from the conserved solver, never from a GDAL raster-calc that would break mass conservation. Split: QGIS Processing = terrain math; `stewie_forge` = physics.

### (b) DT-01 hash-chain is the WRITE authority; PostGIS is a rebuildable READ projection (NOT the sole source of truth)

The design's one architectural fork (design §0 lines 746-762): the append-only, hash-chained journals + `.npz` (`world_state.py:64` DT-01, `stewie/twin/*`) are the **tamper-evident write authority**; **PostGIS + TimescaleDB are projected read models**, rebuildable by replaying the journals (design lines 757-761, `POST /admin/reproject/rebuild` byte-equality guard line 827-830). This directly **amends Aaron's "PostGIS as operational source of truth"**: PostGIS is the *query/serving* authority (spatial `ST_*`, MVT, WMS, QGIS handoff), but if any write reaches PostGIS that the journal never saw, the tamper-evident chain is broken. Keep the journal the write path; project into PostGIS on each committed `WorldTransaction`.

### (c) `terrain_cells` is a PROJECTION of the numpy `TerrainMemory` `.npz`, not a replacement (do NOT move the hot grid into SQL)

The per-cell physics grid mutates in numpy and is mass-conservation-guarded there (`stewie/twin/terrain_memory.py`; design §4.3 lines 1406-1418). Moving it into SQL would break the conservation invariant and the sub-ms step (design line 1247-1252). Aaron's `terrain_cells` table = the design's **10-band `terrain_cell_raster` mirror** (`height/slope/density/sinkage/slip/bearing/illumination/provenance/traffic_passes/compaction`, design lines 1415-1418), refreshed on each committed run for QGIS/WMS/`ST_Value` query. His columns map 1:1; `traffic_passes`/`compaction`/`bearing_strength` are now sourced from `traffic_memory.py:180` (Dr) + `:185` (bearing-uplift).

**Mapping Aaron's three tables onto the design's "PostGIS as projected read model":** `terrain_cells` -> design §4.3 `terrain_cell_raster` (10-band mirror of the `.npz`); `map_layers` -> design §4.2 `map_layer` (mirror of `layer_catalog.json`); `tasks` -> design §4 unified `Task` (the new operator-command object, JSONB params + `geometry(30135)`). All three are *reads projected from* the journal/`.npz`/catalog authorities, never the authorities themselves.

---

## 3. The genuine NEW tracks + how they plug in

Only these pieces are net-new; everything else is reuse or a thin adapter.

### (a) GeoAI perception -> layers (fills the Partial detector rows)

- **What:** a learned-detector producer (`stewie_geoai_perception`) for rock/crater/shadow/hazard-probability/traversability, emitting `.geojson` (features) + `.tif` (probability rasters) + `.gpkg`.
- **Plug-in point:** register every output in the layer catalog (`layer_catalog.json`; the `hazard.rocks:197` / `map.rocks:560` rows are already declared, waiting for a producer) with `source_class=belief`; feed detections into the hazard costmap (`costmap_layers.py`) and semantic map. Rule: everything GeoAI predicts becomes a map layer.
- **Provisioning reality (confirmed):** geoai is installed in `.venv-gis` only; it is NOT importable from the FastAPI server env and NOT in `requirements-server.lock`. Adopting GeoAI in-process requires either adding it to the server env or running it as a `.venv-gis` sidecar that writes COG/GeoJSON the catalog then serves. This is a real provisioning task, not a one-line import.

### (b) Autoware-module framing (map lode nav/planner onto planning/motion; flag localization + prediction as the real gaps)

- **What:** adopt Autoware's module names as an architecture template. costmap_generator/behavior_planner/motion_planner/task_executor/ros_bridge already EXIST in `lode/*` + `stewie/bridge/*` (§1 table). 
- **The real gaps the framing exposes:** `stewie_lunar_localization` (a continuous ESKF/SLAM estimator; today only discrete map-relative fixes, `perception.py:175` + `relocalization.py:24`) and **prediction** (dynamic-agent trajectory prediction; absent). Sequence localization before prediction; prediction waits for multi-rover ops.

### (c) `stewie-qgis-core` PyQGIS-Processing wrapper (generic GIS ops)

- **What:** a thin service wrapping `processing.run(...)` for generic derivatives (slope/aspect/hillshade/raster-calc/clip/reproject/contour/polygonize/zonal-stats/generate_tiles/export_geotiff/export_geopackage), generalizing the existing `make_hillshade` (`gis/build_project.py:515`) and the `.qgz` build path.
- **Plug-in point:** runs in `.venv-gis` (where QGIS/geoai live), writes COG/GeoPackage into the object store, registers results in the catalog. Constraint from §2.a: generic terrain math only; physics stays in `stewie_forge`. `export_ros_costmap` is a convenience wrapper over the already-built `ros_export.costmap_msgs`.

### (d) PostGIS projection layer (the concrete relational schemas as read models)

- **What:** stand up PostGIS 16 (+ TimescaleDB) with the IAU_2015:30135/30100 `spatial_ref_sys` inserts (design §3 DDL lines 1315-1332) and the design §4 tables (`mission`, `map_layer`, `terrain_cell_raster`, `task`, `path`/`waypoint`, `terrain_change_event`, `traffic_event`, `simulation_run`, `ros_export_package`).
- **Plug-in point:** dual-write from the existing journals (journal stays authoritative, §2.b), add `POST /missions/search?bbox=` (spatial), re-back `/gis/query` on PostGIS, `POST /admin/reproject/rebuild` as the byte-equality guard. Reversible (drop the projections). Aaron's `tasks(task_type, status, priority, parameters JSONB, geometry)` = design §4 `Task`.

---

## 4. Aaron's `- hardened_traffic_bonus` cost term is now ENABLED by the just-committed TW-11 layer

Aaron's `stewie-path-engine` cost function is `distance + slope + hazard + sinkage + slip + energy + shadow - hardened_traffic_bonus`. The subtracted bonus rewards routing over ground that repeated traffic has compacted into a firmer surface (a haul road that hardens into a future pad).

**Status (confirmed):** the bonus is **not yet a term in the planner cost** (`lode/costmap_layers.py:160` `LAYERS` tuple has 12 layers, none of them traffic; grep for `traffic\|uplift\|bonus` in the `lode` cost files is empty), **but the substrate it needs is now built.** The TW-11 TrafficMemory provides exactly the per-cell field the bonus reads:

- `stewie/twin/traffic_memory.py:180` `relative_density()` -> per-cell Dr in [0,1] (0 loose RHO_SURFACE, 1 paved RHO_DEEP), the `traffic.compaction` map field;
- `stewie/twin/traffic_memory.py:185` `bearing_uplift_pa()` -> per-cell allowable-bearing UPLIFT [Pa] the traffic produced (the same bearing solver the release gate uses).

Before `534af04` there was no per-cell traffic field to subtract (the design's Missing #1; the `costmap_layers.py:82` disclaimer "compaction is not modelled per cell" still stands for the *slope-driven* proxy). Now the field exists. **The remaining work is a single new `_traffic` cost layer** appended to `LAYERS` that reads `TrafficMemory.relative_density(site)` and returns a **negative** cost (a bonus, floored so it cannot flip a cell passable), co-registered with the DEM/slope grid (traffic memory shares the site DEM order-frame, `traffic_memory.py:80-82`). That is the concrete plug-in that turns Aaron's cost equation on. It is now a wiring task, not a physics-or-data gap.

---

## 5. Updated roadmap

Extends the design's two backlogs (the 15-task frontend backlog, design §D T1-T15; and the 6-step backend sequence, design Backend §4) with Aaron's four new tracks. **Reuse-vs-new tagged.** Two backend Missing items the design flagged (TW-11 traffic, ROS map/costmap/path egress) are **already CLOSED** (`534af04` + `14ecade`) and therefore dropped from "to build." The frontend rebind (QWC2 IDE, design T1-T15) is already in progress.

### Already closed (verify, do not rebuild)
- **TW-11 traffic layer** (was design Missing #1 / backlog T11) -> DONE `534af04`. Verify: `traffic_memory.py:79`, `world.py:61`, `executive.py:272`.
- **ROS occupancy/costmap/path egress** (was design Missing #3/#4/#5) -> DONE `14ecade`. Verify: `nav.py:127/154/194`, `ros_export.py`.

### Still open from the design's own backlog
- **Frontend terramechanics spatial-overlay renderer** (the ONLY still-Missing capability, design row line 39; backlog T12) -> **REUSE** the QWC2 overlay path; render `physics.slip_risk` / `physics.sinkage` / the new `traffic.compaction` (`world.py:61`) with `/layers/legend`. In progress with the GIS/QWC2 frontend rebind.
- **Continuous mission-timeline transport** (design T14) -> **NEW** (frontend).
- **Scalar-rollup adapters** distance/risk/route-confidence (design T13) -> **NEW** thin adapters.

### New track B: PostGIS projection layer (backend, high value, reversible)
1. **B1** stand up PostGIS 16 + TimescaleDB + the 30135/30100 `spatial_ref_sys` inserts (design §3 DDL). **NEW.** Reversible.
2. **B2** create the design §4 tables (`mission`, `map_layer`, `terrain_cell_raster`, `task`, `path/waypoint`, `terrain_change_event`, `traffic_event`, `simulation_run`, `ros_export_package`). **NEW.**
3. **B3** dual-write from the existing journals (journal stays authoritative, §2.b); `POST /admin/reproject/rebuild` byte-equality guard. **NEW.**
4. **B4** re-back `/gis/query` + add `POST /missions/search?bbox=` on PostGIS. **REUSE** contract, re-backed.
5. **B5** the unified 10-verb `Task` object (`survey/dig/dump/flatten/DIG_AREA` + JSONB params + geometry) replacing the three disjoint shapes (`Objective.order_kind`/`KeepOutRegion`/`Order`). **NEW** domain object; the single largest new piece.

### New track C: stewie-qgis-core (generic GIS ops)
6. **C1** wrap `processing.run(...)` for slope/aspect/hillshade/raster-calc/clip/reproject/contour/polygonize/zonal-stats, generalizing `build_project.py:515`. **NEW** (thin), runs in `.venv-gis`.
7. **C2** `export_geotiff`/`export_geopackage`/`generate_tiles`; `export_ros_costmap` as a wrapper over `ros_export.costmap_msgs`. **REUSE** the egress; **NEW** the wrappers. Constraint: generic terrain math only (§2.a).

### New track D: GeoAI perception -> layers
8. **D0** provision geoai on the server import path (or a `.venv-gis` sidecar); today it is `.venv-gis`-only. **NEW** (infra).
9. **D1** `stewie_geoai_perception` detectors (rock/crater/shadow/hazard-prob/traversability) -> `.geojson/.tif/.gpkg`, registered in `layer_catalog.json` (`hazard.rocks`/`map.rocks` rows waiting). **NEW.** Fills the Partial detector rows.
10. **D2** feed GeoAI hazard/traversability into `costmap_layers.py` + the semantic map. **REUSE** the costmap; **NEW** the input adapter.

### New track E: Autoware-module framing + the two real gaps
11. **E1** relabel `lode/*` under the Autoware module names (costmap_generator/behavior_planner/motion_planner/task_executor/ros_bridge). **REUSE** (naming only).
12. **E2** `stewie_lunar_localization`: a continuous ESKF/SLAM estimator over the existing discrete fixes (`perception.py:175`, `relocalization.py:24`). **NEW** (the first real autonomy gap).
13. **E3** prediction module (dynamic-agent trajectories). **NEW** (the second real gap; defer until multi-rover ops).

### Immediate one-liner (independent, do it first)
14. **A0** append a `_traffic` bonus layer to `costmap_layers.py:160` `LAYERS` reading `TrafficMemory.relative_density` (§4). **NEW** (small); turns on Aaron's `- hardened_traffic_bonus` term now that TW-11 supplies the field.

**Sequencing rationale:** A0 is a self-contained backend one-liner unblocked today. Track B (PostGIS) is the load-bearing backend substrate and gates the QGIS/MVT/spatial-search value; B1-B4 are reversible. Track C rides on B (and the `.venv-gis` QGIS env). Track D needs D0 (provisioning) before D1. Track E is naming (E1, free) + two genuine builds (E2 localization, then E3 prediction) that are the longest-horizon items. The frontend rebind (design T1-T15) runs in parallel and does not block any backend track.

---

## 6. What I'd most expect to be wrong (inferred, named out loud)

- **geoai provisioning.** Confirmed geoai is in `.venv-gis` but not the server env; I did NOT test whether it imports cleanly there or what its heavy deps (torch/rasterio/GDAL) do to the server image. D0 may be larger than "add to requirements."
- **`- hardened_traffic_bonus` sign/scale.** I confirmed the field exists and the term is absent from `LAYERS`; I did NOT verify that a negative cost floors correctly against the impassable-mask logic in `compose()` (`costmap_layers.py`). A bonus that flips a cell passable would be a safety bug; it must be floored.
- **PostGIS-as-projection discipline.** The design's whole safety story rests on the journal staying the sole write path; the `POST /admin/reproject/rebuild` byte-equality guard that enforces it is unbuilt (design line 827-830, 1207-1210). This is the claim most worth a second look before B3 dual-writes anything.
- **Autoware localization/prediction as "the two gaps."** I searched `lode/` + `stewie/` and found no continuous estimator or prediction module; a producer could exist under a name I did not grep. Confirm before scoping E2/E3.
- **QGIS Server vs FastAPI WMS.** I marked `stewie-map-server` PARTIAL on the basis that WMS/tiles are FastAPI-hand-rolled; whether Aaron actually needs QGIS Server (vs extending the FastAPI routes with WMTS/MVT) is a scope call, not a code fact.
