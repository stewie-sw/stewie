# STEWIE vs ArcGIS-type GIS — capability diff (2026-06-29)

A graphify-informed LLM-council assessment of STEWIE's *actual* GIS capability (read against the code at
`/mnt/projects/stewie/code`) versus production ArcGIS-type software (ArcGIS Pro / Enterprise / Online,
Spatial Analyst, 3D Analyst, GeoEvent). Three reviewers, file:line-grounded, across data/geoprocessing,
cartography/3D/editing, and web-GIS/real-time/extensibility. This is the cross-compare input that updates the
graphify schema (`graphify-out/stewie_arcgis_parity_2026-06-29.json`). STEWIE is a purpose-built lunar
mission-planning GIS (numpy + pyproj, no GDAL/rasterio by default), not a general GIS; verdicts are relative.

## The moat — where STEWIE meets or EXCEEDS ArcGIS

- **Conserved digital-twin Terrain Memory** (`stewie/twin/terrain_memory.py`): a versioned, hash-chained,
  integrity-verifiable "terrain at time t" that remembers mass-conserved changes a vehicle physically made.
  ArcGIS feature-versioning has no conserved-physics, time-varying operational-twin equivalent.
- **Mass-conserving cut/fill geoprocessing** (`lode/planner_acceptance.py` validate_plan): drum-capacity-
  bounded ordered replay, as-built flatness RMSE, repose stability, Terzaghi/Vesic bearing — exceeds ArcGIS
  3D-Analyst Cut Fill (two static surfaces → volume).
- **Lunar solar-geometry analysis** (`dart/illumination.py`): real horizon-cast-shadow ray-march, per-pixel
  incidence, PSR cold-trap sweep. Domain physics ArcGIS does not ship.
- **Click-to-author mission INTENT** (`cockpit.js` + `footprint_geom.js`): digitize a typed cut/fill order
  (oriented rect/corridor/circle/polygon) that round-trips to the planner → physics → report → executive run.
  ArcGIS digitizes features; STEWIE digitizes an executable plan.
- **Executive run lifecycle** (MO-02, `/executive/run` #245) + **ephemeris-coupled 3D scene** with real cast
  shadows + on-surface fly/measure (`three3d.js`). Lunar-native CRS (IAU_2015:30135) + multi-body. Runtime
  demand-driven LOD corridor mosaic (`tiles_mosaic.py`) vs precomputed pyramids.
- **Invitation-only auth + per-owner namespaces + fail-closed security** (`deps.py`/`auth.py`/`objects.py`):
  tighter and more auditable out-of-the-box than a default ArcGIS Online org, for this scope.

## Parity — ArcGIS-grade today

Raster layer MATH (slope/hillshade/incidence, `gis_layers.py`); least-cost path routing (Dijkstra, richer
separable cost layers, `planner_routing.py`); GeoJSON interchange + attribute query (`gis_export.py`);
contents/layer tree + visibility + physics-fed legend (`contents_tree.js`, `layers.py`); 3D scene drape +
vertical exaggeration + fly; basemap management + opacity; live coordinate readout + CRS transform.

## Gaps — what ArcGIS has that STEWIE lacks (prioritized by leverage)

| # | Gap | ArcGIS has | STEWIE now (file:line) | Smallest next build |
|---|---|---|---|---|
| G1 | **No served OGC service** (WMS/WMTS/WFS/OGC-API) | publish/consume OGC live services | consumes GIBS only; serves GeoJSON files + RGBA PNGs, zero OGC endpoint | wrap `/layers/globe/{kind}.png`+bbox (`layers.py:93,115`) as OGC API-Tiles / WMTS GetCapabilities+GetTile |
| G2 | **Layers are RGBA renders, not value rasters; no map-algebra** | persisted GeoTIFF/COG value rasters; Raster Calculator, reclassify, weighted overlay, aspect, focal/zonal stats | slope/hazard/incidence computed per-request, displayed only (`gis_layers.py:184-227`); COG export GDAL-gated | route value arrays through the COG path (`gis_export.py:260`); add reclassify + aspect |
| G3 | **No bring-your-own DEM upload** | add/publish your own raster | curated LOLA tiles only; no `POST /dem` (GIS-WA3 #237 pending, #171) | GDAL-gated `POST /dem` → a per-owner site (reuse the per-owner namespace) |
| G4 | **On-map feature MODIFY** (move/reshape/vertex-edit) | sketch + snapping + vertex edit + move/rotate/scale + topology | create-only; a placed keep-out/order can only be deleted + redrawn (`cockpit.js:505-517`) | draggable pins to reposition; then vertex handles on a selected polygon |
| G5 | **User-editable symbology / classification** | unique-value/graduated/class-break renderers, editable ramps, Jenks/quantile | ramps + breaks are literals in Python (`gis_layers.py:184-227`); one fixed kind→color vector map | a graduated-renderer control: break count + ramp → `_layer_rgba` |
| G6 | **Map layout / print composer** | layout view: map frames + legend/scalebar/north-arrow → PDF/PNG | no print/`toDataURL` path; the 3-page report PDF is fixed, not a composable map | a "capture map" button: Cesium `scene.canvas.toDataURL()` + legend → PNG |
| G7 | **No accumulated cost-distance / allocation surface** | Cost Distance: accumulated-cost + backlink + allocation rasters | one Dijkstra path returned, `dist[]` discarded (`planner_routing.py:199`) | emit the accumulated-cost + backlink raster, not just the path |
| G8 | **No raster viewshed surface** | observer→all-cells viewshed | point-to-point LOS only (`dart/visibility.py:26`) | sweep `is_visible` to an observer→all-cells output raster |
| G9 | **Groups + per-item sharing** | items shared to groups/org/public; per-item ACL | binary owner-sandbox vs live-shared; no groups (`objects.py`) | a `groups` table + `shared_with` field gated in `load_/list_*` |
| G10 | **No extensibility / ModelBuilder / arcpy** | arcpy, Python toolboxes, custom GP services | fixed planner pipeline; `/models` read-only; ML-01 bars learned models on the command path (partly intentional) | expose the structure-template expander as a constrained declarative "model" |

## The through-line

STEWIE is **ArcGIS-grade (or beyond) on the domain-specific operational-twin axis** — conserved physics,
mission-intent authoring, executive execution, lunar solar/terramechanics analysis — and **below ArcGIS on the
general-GIS-platform axis**: it has no served standard services (OGC), its analysis layers are display renders
rather than value-raster data products, it can't ingest user data or edit placed features, and its symbology
is baked in. The single highest external-value move is **G1 (an OGC tile service)** — it turns STEWIE's
already-rendered layers into something any QGIS/ArcGIS client can consume, for little new compute. G2 (value
rasters via COG) and G3 (DEM upload) convert STEWIE from "a demo on Haworth" into "load and analyze your AOI."
