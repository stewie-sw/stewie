# STEWIE Multi-Level DEM Visualization — Design Fold of Aaron's 2026-07-08 Architecture Vision

**Status:** DRAFT for main-thread review. Read-only screen of `/mnt/projects/stewie/code` @ working tree 2026-07-08; no repo files touched.
**Source vision:** `scratchpad/aaron_arch_vision_2026-07-08.md` (verbatim).
**Method note:** every EXISTS/PARTIAL claim below is grounded in a file opened during this screen (file:line cited). Claims I could not confirm are marked *(inferred)*.

---

## 1. Vision summary

One DEM, several coordinated levels — not separate 2D and 3D products. The 2D map is where you plan and analyze (slope, cost, traversability, hazards, paths, keep-outs); the 3D view is where you validate terrain geometry, line-of-sight, excavation and rover ops against the same surface. The web architecture keeps *authoritative geospatial truth* in QGIS/QGIS Server (WMS/WFS/WMTS, feature queries, editing) and treats Three.js strictly as a renderer synchronized to the GIS: click-3D returns exact map coordinates, draw-2D appears in 3D, measures use authoritative GIS geometry, edits land in the GIS database, never only in the viewer. Everything is stored planet-fixed (lunar body-fixed / projected lunar CRS); rendering and robot ops use a local frame near the mission area because Three.js GPUs are single-precision — define a local origin, render relative, convert back to global on save. Tool roles: QGIS = planning GIS; QGIS 3D = terrain validation; Godot = mission ops center; Gazebo = physics; RViz2 = robot console. Every mission starts from the DEM and ends with an updated world model.

## 2. Current-state table (screened 2026-07-08)

| # | Vision element | Status | Evidence |
|---|---|---|---|
| 1 | QWC2 artemis IDE (2D planning surface) | **EXISTS** | `gis/qwc2/static/config.json` registers Map + LayerTree + Identify + Measure + Redlining + Editing + HeightProfile + 14 STEWIE `Mission*` plugins (plugins.common list); theme `stewie_lunar` binds QGIS Server WMS `http://localhost:8082/ows/?MAP=...stewie_south_pole.qgz` with `mapCrs: IAU_2015:30135` (`gis/qwc2/static/themesConfig.json`, themes.items[0]); PRD QW-01 marked `[SHIPPED: gis/qwc2/js/appConfig.js ... deploy/compose.yml:294]` (`PRD.md:571`) |
| 2 | OpenLayers 2D map in the lunar CRS | **EXISTS** | map is IAU_2015:30135 polar-stereographic, both proj4 defs registered in config.json; drapes arrive as `ImageStatic` in 30100 and OpenLayers reprojects to the 30135 view (`gis/qwc2/js/mission/catalogLayers.js:12-15,49-50,263-275`) |
| 3 | Whole-moon 3D globe (task #27) | **EXISTS** | Cesium 1.119 self-hosted globe, Moon ellipsoid R=1737400, LRO WAC Trek tiles, clickable site markers → site dive (`gis/qwc2/js/mission/wholeMoonGlobe.js:1-40,88-142,149-183`; plugin `js/plugins/WholeMoon.jsx`) |
| 4 | 3D TERRAIN view synced to the GIS (click-3D→coords, draw-2D→3D) **in the IDE** | **NEW** (for /ide) / **PARTIAL** (platform-wide) | The QWC2 IDE has NO Three.js terrain view: no `three` in `gis/qwc2/package.json` (grep empty), no `heightfield` consumer under `gis/qwc2/js` (grep empty). BUT the vanilla cockpit already ships `stewie/server/web/assets/three3d.js` (659 lines, Three.js r170): orbitable work-area DEM in the planner's order frame fed by `GET /dem/heightfield`, with click→terrain waypoint pick, live cursor coordinate readout, plotted coordinate markers, 3D distance measures, sun shadows, layer-texture drape (`three3d.js:1-10,48-49,78,440-449,527`); loaded only by the cockpit (`stewie/server/index.html:1563`), not /ide. So the *component* exists; the *IDE integration + 2D↔3D sync contract* is the new work |
| 5 | QGIS Desktop project (2D analysis, correct CRS) | **EXISTS** | headless PyQGIS builder constructs `stewie_south_pole.qgz` in IAU_2015:30135 (30100 geodetic), 8 Artemis sites + Haworth, DEM+hillshade+slope COGs, site vectors, provenance metadata (`gis/build_project.py:1-58`) |
| 6 | QGIS 3D terrain validation (vertical exaggeration) | **EXISTS** | P1.7: per-site QGIS 3D local scenes persisted into the .qgz as hand-authored `<mapViewDocks3D>` XML (3.22 API gaps documented), DEM terrain generator, `DEFAULT_EXAGGERATION = 2.0` labeled display choice, 5 sites persisted + 4 deferred with reasons (`gis/scene3d.py:1-60`); headless render proof `gis/render_3d_proof.py` |
| 7 | QGIS Server serving the project | **EXISTS (WMS only)** | WMS 1.3.0 GetCapabilities/GetMap/GetFeatureInfo proven; GetMap byte-identical to Desktop render (`max_abs_diff = 0`); GetFeatureInfo returns real Float32 elevations cross-checked vs gdallocationinfo; Docker lane `qgis/qgis-server:3.34` at 127.0.0.1:8082 (compose `gis` profile) + host 3.22.16 lane (`gis/SERVER.md:1-103,105-109`). **WFS/WMTS: NOT proven** — SERVER.md documents WMS only; PRD QG-02 claims "WMS/WMTS/WFS" but its evidence is the WMS GetMap (`PRD.md:666`); the only WMTS in the tree is the *consumed* NASA Trek WMTS, deferred for a CRS reason (`gis/build_project.py:258-294`) |
| 8 | Backend mini-WMS over globe layers | **EXISTS** | FastAPI `/ogc/wms` WMS 1.3.0 (GetCapabilities/GetMap) over the drape kinds, CRS:84 / EPSG:4326 / IAU_2015:30100 — returns InvalidCRS for 30135, which is why the IDE consumes `/layers/globe/{kind}.png` + bbox instead (`stewie/server/routers/ogc.py:56-70,176-182`; `catalogLayers.js:12-15`). Its docstring still says "7 globe layers"; `_GLOBE_KINDS` is now 16 (`ogc.py:1`, `layers.py:38-45`) — stale comment, flag for cleanup |
| 9 | Analysis rasters already produced | **EXISTS (subset)** | `_GLOBE_KINDS` = dem(=hillshade), slope, hazard, illumination, incidence, psr, grid, cost, blocking, bearing, sinkage, slip_risk, traction_margin, energy_cost, excavation_resistance, traffic (`stewie/server/routers/layers.py:38-45`); renderers in `stewie/server/gis_layers.py:316-400` (dem/hillshade lambertian 315°/45° L330-337; slope graduated L339-353; hazard L355-362; illumination horizon-clip L363-369; psr sweep L370+; incidence L383+; 12-layer FORGE costmap cost/blocking L394+). QGIS project carries per-site DEM/hillshade/slope COGs (`gis/build_project.py:14`). Legend from physics (`layers.py:73-123`) |
| 10 | Analysis rasters NOT yet produced | **NEW** | **aspect, curvature, contours** — no producer anywhere (grep over `stewie/` python: contour/aspect/curvature hits only in unrelated files); `base.contours` is catalog-declared, vector, no producer (`stewie/server/layer_catalog.json` id `base.contours`). **Roughness** exists only *inside* the costmap sum (`lode/costmap_layers.py:70-78,172`), not as a standalone drape. **Line-of-sight** (`terrain.los`, `terrain.comms`) catalog-only, no producer found. **Dig/fill depth + terrain deformation**: the *data* exists — TerrainMemory / as-built compose (`stewie/twin/terrain_view.py:48-83`, `/world/terrain_view` `stewie/server/routers/world.py:473-494`, `/dem/asbuilt` `routers/dem.py:156`) and catalog rows `map.changed_terrain` / `evidence.before_after_dem` — but no *difference drape* (before-minus-after raster) is in `_GLOBE_KINDS` |
| 11 | Layer catalog / eligibility registry (LY-01) | **EXISTS** | 66-layer typed catalog with source_class, planning/release/execute eligibility (`stewie/server/layer_catalog.json`); served with per-layer confidence derived from provenance at `/world/layer-catalog`, `/world/layer-manifest`, `/world/layer-consumption` (`stewie/server/routers/world.py:29-60,85-120,279-305`). NOTE: catalog declaration ≠ producer — rows in #10 are declared but unproduced |
| 12 | Lunar CRS + coordinate flow (planet-fixed authoritative → local frame) | **EXISTS (structure)** / **PARTIAL (formal contract)** | Authoritative frames: IAU_2015:30135 south-polar stereographic metres + 30100 selenographic; per-bundle CRS resolution (ad-hoc tiles carry a local azimuthal-equidistant proj4) (`stewie/terrain/site_dem.py:75-89`). Local site frame: pixel-metre "order frame" anchored at the tile origin, forward/inverse transforms `latlon_to_dem_origin` / `dem_origin_to_latlon` (L211-242), meridian-convergence-aware `grid_north_bearing_deg` (L245-266), globe georef corners + vectorized terrain grid (L269-323). Convert-back-on-save exists in the plan path: map-click 30135 → selenographic → anchor-relative order metres in ONE serializer (`gis/qwc2/js/mission/planTools.js:46-60,99-108`); markers stored in the 30135 map frame (L112+). What does NOT exist: a *named, tested* planet-fixed-authoritative + local-render-origin + float32-precision contract (see §6) |
| 13 | Single-precision / local-origin handling in the 3D renderer | **PARTIAL (implicit)** | `three3d.js` renders a windowed local crop (default `window_m=300`, n=129, `routers/dem.py:112-113`) in metres from the site origin (`three3d.js:1-4,446`), so world coords stay ≤ ~10^4 m and float32 is safe *by construction*; but nothing documents or tests the precision budget, and no code guards a future whole-tile / whole-moon 3D case *(inferred: no precision test found; grep "precision" in three3d.js hits nothing load-bearing)* |
| 14 | Edits stored in the GIS/backend, not the 3D viewer | **EXISTS** | GW-08 edit sessions (keep-outs/waypoints/work-zones) write ONLY through backend routes with versioned audit, glyph D\|D\|D (`PRD.md:647`); `stewie/server/edit_session.py` exists (dir listing); plan orders POST `/api/plan` via the shared serializer (`planTools.js:99-108`). The 3D cockpit view's waypoint picks also round-trip through order coords (`three3d.js:78,263`). PostGIS as durable projection is tracked, not built (PG-01 P2, `PRD.md:599`) |
| 15 | Godot render lane | **EXISTS (offline render/sensor sidecar; mission view NEW)** | `stewie/godot/` = Godot 4.6.3 headless render + sensor rig (terrain/rover shaders, capture scripts, render.sh); `deploy/Dockerfile.godot` is the opt-in GPU-gated sidecar image — host mounts the binary + GPU, honest gate documented (`deploy/Dockerfile.godot:1-12`). The *operator-facing Godot mission view* is PRD RT-05, glyph N (`PRD.md:663`) |
| 16 | ROS2 / Gazebo / RViz | **PARTIAL** | Bridge layer exists (`stewie/bridge/ros2_bridge.py`, frames.py, telemetry.py, plan_lowering.py — dir listing) + `deploy/ros2/` image; PRD: RT-00 ROS-image-carries-stewie N, RT-03 Gazebo-rehearsal-on-real-DEM N, RT-04 RViz/Foxglove evidence panel D\|D\|P\|G, RT-02 evidence-bound-to-run N (`PRD.md:643,660-663`). Per project memory these are container-buildable on this host, not externally gated |
| 17 | 2D transect / cross-section analysis | **EXISTS** | MissionCrossSection: draw a transect on the 30135 map → `/api/world/transect` → real per-cell elevation/slope/bearing/sinkage/PSR profile, unavailable layers rendered as explicit grey gaps (`gis/qwc2/js/plugins/MissionCrossSection.jsx:1-20`; `/world/transect` `routers/world.py:378`) |

## 3. Target architecture mapped onto STEWIE's real components

Aaron's stack, annotated with what each box already is in this repo:

```
Lunar DEM (GeoTIFF/COG + heightmap.rf32 bundles)          [EXISTS: data/gis COGs + samples/lunar_dem bundles;
   |                                                        loaders stewie/terrain/site_dem.py]
   v
QGIS Desktop  — scientific analysis, CRS, terrain products [EXISTS: gis/build_project.py -> stewie_south_pole.qgz,
   |            + QGIS 3D validation scenes                  IAU_2015:30135; 3D scenes gis/scene3d.py P1.7]
   v
QGIS Server   — WMS (proven) / WFS+WMTS (to prove)         [EXISTS-WMS: gis/SERVER.md, compose `gis` profile :8082;
   |            feature queries via GetFeatureInfo           WFS/WMTS = QG-04 below]
   |            + FastAPI backend as the SECOND server:     [EXISTS: /layers/globe/*, /ogc/wms, /world/*, /dem/*
   |              physics/analysis drapes + typed world      — the analysis-raster + world-model half QGIS Server
   |              model + edit sessions + audit               does not own]
   v
QWC2 (/ide)   — mission planning, editing, measurements    [EXISTS: QW-01 shipped; Mission* plugins; edits via
   |                                                         backend routes only (GW-08)]
   +-- OpenLayers 2D map (IAU_2015:30135)                  [EXISTS: catalogLayers.js reprojection wiring]
   +-- Cesium whole-moon globe (context/overview)          [EXISTS: wholeMoonGlobe.js]
   +-- Three.js 3D TERRAIN view, shared coordinates        [NEW in /ide — reuse three3d.js from the cockpit;
                                                             rows GW-11/GW-12 below]
   v
ROS 2 + Gazebo (physics/sensors)  /  RViz2 (robot console) [PARTIAL: bridge + RT-00/03/04 rows]
Godot (mission ops center / rehearsal render)               [PARTIAL: offline sidecar exists; RT-05 mission view N]
```

Two deliberate deviations from the vision's literal pipeline, both already settled in the repo and worth keeping:

1. **The FastAPI backend is a co-equal geospatial server, not a bypass.** QGIS Server serves the *cartographic* project (base DEM/hillshade/slope, byte-identical to Desktop); the backend serves the *physics/world-model* rasters (costmap, terramechanics spine, traffic, PSR at a commanded sun) that QGIS cannot compute, plus the typed layer catalog, edit sessions and audit. The vision's "accuracy comes from the GIS" maps to *both*: cartographic accuracy from QGIS Server, physical accuracy from the conserved authority. Merging them into QGIS-only would forfeit the live-physics drapes.
2. **Edits land in backend edit-sessions (versioned, audited), not a QGIS-writable DB.** This already satisfies the vision's intent ("edits stored in the project/database rather than only in the 3D viewer") with a stronger audit story; PG-01 (PostGIS projection, P2, `PRD.md:599`) is the eventual durable-GIS-DB mirror and needs no new row.

## 4. Multi-level DEM visualization (2D plan/analyze + 3D validate, same DEM several ways)

The same DEM already renders at four levels, all from one loader family (`site_dem.py`):

| Level | Surface | Status |
|---|---|---|
| Whole-moon context | Cesium globe + WAC tiles + site markers; work-area drape via `dem_terrain_grid` 3D mesh (`site_dem.py:291-323`) | EXISTS |
| Regional 2D (16 km sites) | QGIS Desktop/Server DEM+hillshade+slope; QWC2 map + backend drapes | EXISTS |
| Site 2D analysis | 16 `_GLOBE_KINDS` physics/analysis drapes + legend-from-physics + transect profiles | EXISTS |
| Site 3D validate | QGIS 3D scenes (Desktop, exaggeration 2×); cockpit `three3d.js` orbit/fly view with shadows, drapes, coord readout | EXISTS — but NOT in the /ide, and not exaggeration-controlled in the web view *(inferred: no exaggeration UI found in three3d.js beyond `setVertExag` mention at the wire-overlay comment — the hook exists, `three3d.js:13-15`; confirm in main thread)* |

**Analysis-raster product set — exists vs to-build** (the vision's §"Lunar raster products"):

| Product | Status | Where |
|---|---|---|
| DEM (elevation) | EXISTS | `_GLOBE_KINDS` "dem"; QGIS COGs |
| Hillshade | EXISTS | `gis_layers.py:330-337` (dem drape IS the 315°/45° hillshade); QGIS per-site hillshade COGs |
| Slope | EXISTS | `gis_layers.py:339-353` graduated; QGIS slope COGs |
| Traversability cost | EXISTS | `cost` + `blocking` from the 12-layer FORGE costmap (`gis_layers.py:394+`; `lode/costmap_layers.py:172`) |
| Illumination / shadow (time-driven) | EXISTS | `illumination`, `incidence` w/ SPICE sun + grid-north correction (`layers.py:58-70`; `gis_layers.py:363+`) |
| PSR | EXISTS | `gis_layers.py:370+` (azimuth-sweep never-lit) |
| Terramechanics set (bearing/sinkage/slip/traction/energy/excavation-resistance) | EXISTS | T12 drapes (`layers.py:41`) |
| Traffic compaction | EXISTS | TW-11 drape (`layers.py:43-45`) |
| **Aspect** | **NEW** | no producer (grep) — trivial from the existing gradient (`np.arctan2(gy,gx)` next to slope in `_layer_rgba`) |
| **Curvature** | **NEW** | no producer — second derivative of the same heightfield |
| **Contours (vector)** | **NEW** | `base.contours` catalog-only; natural QGIS-Desktop product (gdal_contour into the .qgz) + optional backend GeoJSON |
| **Roughness (standalone drape)** | **PARTIAL** | computed inside the costmap (`costmap_layers.py:70-78`) but not exposed as its own `_GLOBE_KINDS` drape/legend |
| **Line-of-sight / comms visibility** | **NEW** | `terrain.los`/`terrain.comms` catalog-only, no producer; the horizon-march machinery in `dart.illumination` is the reusable core *(inferred: reusability judged from the psr/illumination call sites, not a LOS prototype)* |
| **Dig/fill depth + terrain deformation (before/after diff)** | **PARTIAL** | data exists (TerrainMemory as-built compose `stewie/twin/terrain_view.py:48-83`; `/world/terrain_view` + `/dem/asbuilt`) but no signed-difference drape in `_GLOBE_KINDS`; catalog rows `map.changed_terrain`/`evidence.before_after_dem` unproduced |
| World-model updates | EXISTS | the execute→remember loop folds runs into TerrainMemory + the DT-01 log (CLAUDE.md 2026-07-01 record; `twin/versioned.py:176`) |

## 5. Tool-role pipeline mapped to STEWIE

| Vision role | STEWIE reality | Status |
|---|---|---|
| QGIS = mission planning GIS | `stewie_south_pole.qgz` + Processing provider `stewie_qgis/` (StewieTerramechanics/StewieSamplePoint algorithms over the public backend, QG-01 `[SHIPPED]` `PRD.md:668`) + QG-03 (Desktop workbench over the same backend, N) | EXISTS core; QG-03 open |
| QGIS 3D = terrain validation | P1.7 persisted 3D scenes, exaggeration 2×, headless render proof (`gis/scene3d.py`) | EXISTS (Desktop-side) |
| QWC2 = collaborative web planning | /ide front door, plan/edit/measure/cross-section plugins, edits via backend routes | EXISTS |
| Godot = mission operations center | offline render/sensor sidecar (`stewie/godot/`, `deploy/Dockerfile.godot`); operator mission view = RT-05 (N) | PARTIAL |
| Gazebo = physics simulator | `gazebo_sim` runtime profile named (RT-01 D); real-DEM rehearsal = RT-03 (N); bridge exists | PARTIAL |
| RViz2 = robot engineering console | RT-04 evidence-only panel D\|D\|P\|G | PARTIAL |
| "mission ends with an updated world model" | SIM execute→remember loop + WorldTransaction (DT-03) + as-built readback | EXISTS |

The vision's sequencing ("Orbital DEM → QGIS 2D → QGIS 3D → Godot → Gazebo → RViz2") is already the PRD's ConOps spine (Plan → Rehearse → Validate → Release → Execute → Report) with the runtime engines behind ONE workspace context and *no independent command surfaces* (§7.B preamble, `PRD.md:636`) — the fold is role-labeling, not restructuring.

## 6. Coordinate + numerical-precision strategy vs what site_dem.py does today

**Vision:** planet-fixed authoritative store; local ENU only for render/robot ops; Three.js single-precision → local origin near the mission area, render relative, convert back on save.

**Today (confirmed):**
- *Planet-fixed authoritative:* IAU_2015:30135 (south-polar stereographic, metres, R=1737400 sphere) is the projected authority for every curated tile; 30100 selenographic is the geodetic authority; an ad-hoc tile carries its own local azimuthal-equidistant proj4 in metadata (`site_dem.py:75-89`). The QWC2 map, the .qgz, the QGIS Server all speak 30135 natively (`themesConfig.json`; `build_project.py:52`).
- *Local frame for ops:* the per-site "order frame" (pixel-metres from the tile origin, raster-down y) is what the planner, cockpit 3D, ROS lowering, and edit serializers use; forward/inverse transforms + convergence bearing are centralized in `site_dem.py:211-266`. This is STEWIE's ENU-equivalent (grid-aligned rather than true-north-aligned; `grid_north_bearing_deg` carries the correction, L245-266).
- *Convert-back-on-save:* map clicks serialize to anchor-relative order metres in one shared serializer, markers persist in 30135 (`planTools.js:99-115`); 3D waypoint picks land in order coords (`three3d.js:78,263`).
- *Single-precision safety:* achieved **implicitly** — the web 3D view only ever loads a windowed crop (≤ ~640 m typical, `dem.py:112-113,220`) in site-local metres, so float32 (~7 significant digits) holds sub-mm at these magnitudes. Nothing *states or tests* this. The failure mode arrives exactly when the vision's ambitions do: a whole-tile (10 km ⇒ ~1 mm ulp, still fine) or 30135-absolute (up to ~457 km extents, `themesConfig.json` extent ⇒ ~3 cm ulp) or moon-fixed-Cartesian (1.7×10⁶ m ⇒ ~0.1 m ulp) Three.js scene silently loses precision.

**Gap → requirement (CS via GW-12 below):** name the contract — (a) authoritative coordinates live only in 30135/30100 (+ per-tile local CRS) on the server; (b) every render surface declares its local origin (site anchor or window SW corner) and renders float32-relative; (c) every pick/edit converts back through the shared transforms before persisting; (d) a test asserts round-trip error < 1 cm at the 30135 extent corners and at ad-hoc tile centers. Items (a)-(c) are current behavior to *freeze*; (d) does not exist.

## 7. Key capabilities × build status

| Capability (vision) | Status | Evidence / gap |
|---|---|---|
| Click a point in 3D → exact map coordinates | **EXISTS in cockpit, NEW in /ide** | `three3d.js` live cursor readout + coordinate markers (`three3d.js:440-449,527`, `_coordOf` L446: order metres + elevation); order→lon/lat via `dem_origin_to_latlon` (`site_dem.py:227-242`, exposed at `/dem/site_lonlat` `dem.py:80`). Gap: not in the QWC2 IDE, and readout is order-frame (30135/lon-lat display needs the one extra transform the backend already provides) |
| Draw a path in 2D → see it immediately in 3D | **PARTIAL** | 2D authoring is complete (traverse waypoints/orders, `planTools.js:63-85`); the cockpit 3D animates the *planned timeline* rover+path on the same surface (`three3d.js:1-5`). Gap: no live 2D-edit → 3D-scene sync, and no 3D surface in the IDE at all |
| Measure with authoritative GIS geometry | **EXISTS (2D) / PARTIAL (3D)** | QWC2 Measure plugin on the 30135 map (config.json); QGIS ellipsoid set to the lunar sphere (`build_project.py:56`); transect profiles server-computed (`world.py:378`). The cockpit 3D measure is chord distance in the local frame (`three3d.js:48-49`) — fine at window scale, not "authoritative geodesic"; acceptable if the contract labels it |
| Edits stored in the GIS DB, not the 3D viewer | **EXISTS** | GW-08 D\|D\|D: backend-routes-only, versioned audit (`PRD.md:647`); 3D picks round-trip through order coords; PG-01 (P2) is the future PostGIS mirror — **no new row needed** |
| Vertical exaggeration 2-5× for lunar terrain | **EXISTS (QGIS 3D) / PARTIAL (web 3D)** | `scene3d.py` DEFAULT_EXAGGERATION=2.0, per-view editable; `three3d.js` has a `setVertExag` hook (L13-15 comment) — UI/persistence unconfirmed *(inferred)* |
| Switch among several rasters over one DEM | **EXISTS** | 16 drape kinds + LY-01 eligibility + legend-from-physics (§4) |
| Same-DEM-several-levels (globe → region → site → 3D) | **EXISTS** | §4 table |

---

## 8. Proposed PRD §7 additions (additive; glyphs `N | N | N | NA`)

Collision check: existing prefixes/IDs grepped from `PRD.md` (`^\| XX-nn`): GW-00..10, LY-01..04, QG-01..03, SD-01..03, CS unused, V3 unused. New IDs below do not collide. All rows are candidates for the §7.B "GIS Mission Workbench" block (they extend its lanes), keeping the `(extends X)` rollup convention.

| ID | P | Requirement and acceptance | I | X | V | Q |
|---|---|---|---|---|---|---|
| GW-11 | P1 | **3D terrain view in the /ide, synced to the GIS map.** A Three.js 3D terrain panel in the QWC2 IDE renders the selected site's REAL DEM window (via `/dem/heightfield`) in the site-local frame with a vertical-exaggeration control (1-5×, labeled display choice); it reuses/ports the cockpit `three3d.js` capabilities (orbit/fly, sun shadows, layer-texture drape) rather than a new renderer. Click-3D returns the exact map coordinate (IAU_2015:30135 + selenographic, via the shared `/dem/site_lonlat` transforms) into the IDE's coordinate display; a mission feature authored on the 2D map (waypoint/keep-out/work-zone) appears in the 3D view from the same backend state within one refresh, and a 3D waypoint pick lands in the same order-frame serializer the 2D path uses. Playwright: open the 3D panel, pick a point, assert the 2D map centers on the returned coord; author a 2D keep-out, assert it renders in 3D. (extends QW-01/GW-05/GW-02; reuses stewie/server/web/assets/three3d.js + routers/dem.py heightfield) | N | N | N | NA |
| GW-12 | P0 | **Planet-fixed-authoritative + local-render-origin coordinate contract (single-precision safe).** One documented, tested contract: authoritative coordinates exist ONLY in the lunar CRSs (IAU_2015:30135/30100, or the ad-hoc tile's local CRS) on the server; every render surface (three3d/cockpit 3D, /ide 3D, Cesium globe, Godot) declares a local origin near the work area and renders float32-relative to it; every pick/edit/measure converts back through `site_dem.py` transforms (`latlon_to_dem_origin`/`dem_origin_to_latlon`) before persisting — a renderer never stores its own frame. Acceptance: an executable `[REQ:GW-12]` test asserts (a) coordinate round-trip error < 1 cm at the 30135 theme-extent corners, at each imported site anchor, and at an ad-hoc tile center; (b) the largest coordinate magnitude handed to a float32 render path stays under a stated bound (documented ulp budget); (c) a grep/AST guard that no `gis/qwc2/js` or `web/assets` module persists coordinates without the shared serializer. (formalizes site_dem.py:211-266 + planTools.js:99-115; extends GW-02/GW-05) | N | N | N | NA |
| LY-05 | P1 | **DEM-derivative analysis rasters: aspect, curvature, roughness drape, contours.** Aspect (gradient azimuth) + curvature (profile/plan or Laplacian, stated) join `_GLOBE_KINDS` as real producers with legend entries computed from the same heightfield gradient the slope drape uses; roughness is exposed as a standalone drape (same window-RMS-slope definition as `lode/costmap_layers._roughness`, one source of truth); contours generate as a REAL vector product (QGIS-Desktop gdal_contour layers persisted into the .qgz at stated intervals, and/or a backend GeoJSON endpoint) registered in the LY-01 catalog with provenance + eligibility (display-only by default per the catalog). Acceptance: each new kind renders via `/layers/globe/{kind}.png` + bbox on a real site, appears in the /ide layer tree with a legend, and a test asserts aspect/curvature values on a synthetic-free real-DEM fixture crop. (extends LY-01/GW-06; producers land in stewie/server/gis_layers.py + gis/build_project.py) | N | N | N | NA |
| LY-06 | P2 | **Line-of-sight / comms-visibility layer.** A real producer for `terrain.los`/`terrain.comms`: given an observer point + mast height on the site DEM, a horizon-marched visibility raster (reusing the dart.illumination horizon machinery) renders as a drape and answers point queries; registered in LY-01 with provenance; planning-eligibility only after validation. Acceptance: a `[REQ:LY-06]` test asserts a cell behind a ridge from the observer is not-visible and a same-slope open cell is visible, on a real DEM crop. (extends LY-01; fills the catalog-only terrain.los row) | N | N | N | NA |
| LY-07 | P1 | **Terrain-change / dig-fill-depth drape (before-vs-after DEM difference).** A signed elevation-difference drape (base DEM vs the as-built/observed compose from `stewie/twin/terrain_view.compose_terrain_view`) renders cut (below base) vs fill (above base) with a diverging legend and per-cell depth readout via `/world/point`; zero-change is transparent; the drape carries the as_built/twin versions it was computed from. This is the visual producer for the catalog rows `map.changed_terrain` + `evidence.before_after_dem`. Acceptance: after a conserved cut+fill transaction on a real site, the drape shows the cut region negative and the berm positive with depths matching the transaction volumes; `[REQ:LY-07]` test. (extends LY-01/DT-04/SD-01; data path already exists at /world/terrain_view + /dem/asbuilt) | N | N | N | NA |
| QG-04 | P2 | **QGIS Server WFS + WMTS proven (completes QG-02's claim).** The `--profile gis` QGIS Server serves (a) WFS: GetCapabilities lists the project's site vectors and a GetFeature returns them in IAU_2015:30135; (b) WMTS: GetCapabilities advertises a lunar-CRS tile matrix and a GetTile returns a correct pole-truthful tile (or the WMTS leg is explicitly recorded infeasible on the pinned server version with the reason, like the Trek WMTS deferral). `gis/test_server.py` extends to assert both (skip-clean when no server is up). Note: QG-02's shipped evidence is WMS-only (gis/SERVER.md); this row makes the WFS/WMTS words in QG-02 true or honestly retracts them. (extends QG-02; alternative raster path already tracked as TT-01) | N | N | N | NA |

**Deliberately NOT proposed** (already built or already tracked — do not rebuild):
- Whole-moon 3D globe — built (task #27, `wholeMoonGlobe.js` + WholeMoon.jsx).
- QWC2 IDE, OpenLayers 30135 map, layer tree/eligibility, edit sessions, measure, transect — built (QW-01, GW-05/06/07/08, LY-01, SD-03 plugin).
- Edits-in-GIS-DB — GW-08 (D|D|D) already enforces backend-routes-only with versioned audit; PostGIS mirror already tracked as PG-01 (P2).
- QGIS Desktop 2D + 3D validation scenes with vertical exaggeration — built (`build_project.py`, `scene3d.py`).
- QGIS Server WMS — built + proven byte-identical (`gis/SERVER.md`).
- Hillshade/slope/illumination/PSR/incidence/cost/traversability/terramechanics/traffic rasters — built (16 `_GLOBE_KINDS`).
- Godot mission view, Gazebo real-DEM rehearsal, RViz evidence panel — already tracked as RT-05/RT-03/RT-04; ice/confidence/coverage/twin-diff layer kinds as LY-04; OGC API Features as OF-01; TiTiler alternative as TT-01.

**Small honesty fixes to carry with any of the above (no new rows):** `ogc.py:1` docstring says "7 globe layers" (now 16); PRD QG-02's "WMS/WMTS/WFS" wording vs WMS-only evidence (resolved by QG-04 either way).
