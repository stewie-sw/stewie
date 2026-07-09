# viz3d.js geospatial upgrade — architecture + transform pipeline (2026-07-09)

Grounds the "make the 3D DEM geographically correct + mission-planning-ready" request in STEWIE's REAL
architecture. The headline reconciliation with the generic spec: **CRS transforms stay SERVER-SIDE.**
STEWIE already reprojects on the authoritative path (`dart/dem_reproject.py`, IAU_2015:30135 south-polar
stereographic, MOON_ME sphere R=1737400 m, tested in `dart/test_dem_reproject.py`) and exposes it as
`/dem/site_xy` (lat,lon→metres) and `/dem/site_lonlat` (metres→lat,lon) plus the pre-computed curved
`/dem/graticule`. Adding proj4js to the browser would duplicate that and risk silent divergence, so the
frontend consumes the server transform, never re-derives it. (proj4 only appears if we ever need an
offline/no-backend mode — out of scope.)

## 1. Architecture

Current `viz3d.js` (window.STEWIE_VIZ singleton) renders a DEM tile as a Three.js surface in **tile-pixel
metres** (`x0+lx, y0+ly`), with server-fed hillshade/slope drapes, a metric km grid, the server curved
lon/lat graticule, hover/plot/measure that resolve lon/lat via `/dem/site_lonlat` (all `_llGen`/`_plotGen`
generation-guarded from the council fixes). We ADD, without breaking that:

- `viz3d/frame.js` — the frame manager: `mode ∈ {enu, globe}`, vertical exaggeration `vex`, and the ONE
  function `place(e_m, n_m, elev_m) → THREE.Vector3` every consumer (mesh build, grid, graticule, markers,
  icons, paths) routes through. Flat↔globe is a single re-`place()` of the same source metres+elev, so all
  overlays stay registered by construction.
- `viz3d/layers.js` — a layer stack (LayerModel[]: id, kind, visible, opacity, zOrder, legend, source-url),
  driving the draped textures + a legend/opacity/visibility panel. Extends the existing `setLayer`.
- `viz3d/annotate.js` — icon dropping + GeoJSON feature store (raycast→server lonlat→feature), persisted to
  the backend mission edit-session.
- `viz3d/measure.js` — extend the existing measure tool: surface + straight-line distance, polygon area,
  slope/elevation profile, bearing.
- `viz3d/scalebar.js` — dynamic scale bar + north arrow + sun arrow + cursor readout (HUD overlay).
- `viz3d/exchange.js` — export/import GeoJSON, CZML, ROS2 waypoint YAML, CSV (ROS2 reuses the existing
  `stewie/bridge/rc_contract.py` GoTo leg contract server-side).

Server (mostly present): reuse `/dem/site_xy`, `/dem/site_lonlat`, `/dem/heightfield_full[_meta|_layer]`,
`/dem/graticule`. NEW backend: `/dem/site_meta` returning the tile's CRS id, bounds, pixel size, nodata,
vertical datum, and origin lon/lat (so the client never guesses); annotation persistence via the existing
mission edit-session routes; the export formatters (server-side, so ROS2/CZML reuse the authoritative plan).

## 2. Coordinate transform pipeline

The one true chain (every renderable position goes through it):

```
DEM pixel (col,row)
  → projected metres (x,y) in IAU_2015:30135   [server: dem_import/reproject; client already works in x0+lx,y0+ly]
  → lat,lon (deg)                              [server /dem/site_lonlat — NEVER client-side proj4]
  → elevation h (m)                            [server heightfield sample; already have elev_m]
  → render position:
       ENU (flat):   pos = (lx*S, exaggerate(elev)*S,  lz*S)     # current behaviour, scale S
       GLOBE:        pos = bodyFixed(lat,lon,h)                  # section 5
```

`h` is preserved with vertical exaggeration in BOTH modes (exaggerate about the tile's mean radius so the
globe curvature and the relief add rather than fight). Client caches the per-tile `(x0,y0,pixel_m,
lat0,lon0)` from `/dem/site_meta` + a coarse metres→lonlat bilinear grid (one batched `/dem/graticule`-style
fetch) so per-vertex globe placement needs no per-vertex server round-trip.

## 3. Recommended Three.js objects

- Terrain: keep `BufferGeometry` + computed normals; index type by max-vertex (council fix). LOD via the
  existing `n`/`window_m` heightfield params → swap geometries on camera-distance thresholds.
- Grid + graticule + paths: `Line2`/`LineMaterial` (fat, screen-space width, depth-correct on the surface)
  instead of `THREE.Line` — fixes z-fighting + gives labels an anchor.
- Icons: `THREE.Sprite` (billboarded) for the marker glyph + an `InstancedMesh` stem to the surface; one
  `Group` per annotation so flat↔globe re-place moves glyph+stem together.
- Labels (grid ticks, icon names): CSS2DRenderer overlay (DOM labels, crisp, no SDF font system) — the
  module already hand-rolls one-off sprite text; CSS2D scales better for many ticks.
- Scale bar / north / sun / readout: plain DOM HUD (not in-scene), updated from camera + `frame`.

## 4. Pseudocode — CRS-correct lat/lon gridlines

```
// lon/lat graticule is ALREADY server-correct (/dem/graticule returns densely-sampled polylines in tile
// metres). We only (a) drape it via frame.place so it follows exaggeration + globe, and (b) label it.
for line in fetch('/dem/graticule?site=&window=&x0=&y0='):     // [{value, kind:'lat'|'lon', coords:[[x,y],..]}]
    pts = line.coords.map(([x,y]) => frame.place(x - x0, y - y0, sampleElev(x,y) + drapeEps))
    scene.add(new Line2(pts, latlonMaterial(line.kind)))
    label = `${line.value.toFixed(2)}°${line.kind==='lat'?'N':'E'}`
    css2d.add(labelAt(pts[Math.floor(pts.length/2)], label))
// km grid: build in the PROJECTED tangent plane (constant-metre spacing), same place() drape:
for m in range(0, window_m, 1000):
    addLine([ (m,0),(m,window_m) ]); addLine([ (0,m),(window_m,m) ]); labelKm(m/1000)
// registration: grid/graticule are rebuilt (or just re-place()d) on vex change, camera is free; on globe
// toggle the SAME place() yields curved lines automatically — no separate globe grid code.
```

## 5. Pseudocode — DEM-on-globe placement

```
BODY_R = 1737400.0                         // MOON_ME, from stewie.specs (configurable per body)
function bodyFixed(lat_deg, lon_deg, h_m):
    lat = rad(lat_deg); lon = rad(lon_deg)
    r = (BODY_R + exaggerate(h_m))
    return Vector3( r*cos(lat)*cos(lon), r*cos(lat)*sin(lon), r*sin(lat) )   // body-fixed ECEF-style
function place(e_m, n_m, elev_m):
    if mode === 'enu': return new Vector3(e_m*S, exaggerate(elev_m)*S, n_m*S)
    [lat,lon] = metresToLonLat(e_m + x0, n_m + y0)      // cached bilinear grid from /dem/site_lonlat samples
    p = bodyFixed(lat, lon, elev_m)
    return worldFromBody(p)     // recentre+orient the tile patch to the origin so the camera framing is sane
// only the tile patch is placed on the sphere (a full-Moon shell is the separate whole-moon globe view);
// this makes a tile read as a curved cap, correct for regional planning, cheap (one tile's verts).
```

## 6. Pseudocode — raycast icon dropping

```
onTap(screenXY, activeIconType):
    hit = raycaster.setFromCamera(screenXY, camera).intersectObject(terrainMesh)[0]
    if !hit: return
    // invert render→source: read the tile metres back off the hit (same e_m/n_m the hover tool derives)
    {e_m, n_m, elev_m} = sourceMetresFromHit(hit)          // reuse _hoverPick's derivation
    gen = ++plotGen                                        // council generation-guard
    {lat,lon} = await fetch(`/dem/site_lonlat?x=${x0+e_m}&y=${y0+n_m}&site=${site}`)
    if gen !== plotGen || site !== siteAtTap: return       // dropped if the site switched mid-fetch
    feature = { type:'Feature', geometry:{type:'Point', coordinates:[lon,lat]},
                properties:{ id:uuid(), type:activeIconType, name:'', elevation:elev_m,
                             timestamp:serverNow(), notes:'', layer:'annotations', mission_id:S.missionId } }
    annotate.add(feature)                                  // Group(sprite+stem) placed via frame.place, georef'd
    persist(feature)                                       // backend mission edit-session; survives flat↔globe
// icon types: rover, lander, hazard, waypoint, dig_site, dump_site, sample_point, comm_relay, science_target
```

## 7. Minimal implementation checklist (fan-out increments, each isolated + node-tested where logic is pure)

- [ ] **A. Frame + globe** — `frame.js` (`place`, `mode`, `vex`, cached metres↔lonlat grid), globe toggle,
      re-`place()` all overlays; `bodyFixed` with configurable BODY_R; keep ENU exact. Backend `/dem/site_meta`.
- [ ] **B. Scale/HUD** — dynamic scale bar (camera-alt + latitude + mode aware), north arrow, sun arrow,
      cursor readout (lon,lat,elev,slope,local x/y m). Pure-JS scale math → node-tested.
- [ ] **C. Layers** — layer stack model + panel (visibility/opacity/zOrder/legend) over
      elevation/hillshade/slope/aspect/roughness/traversability/illumination drapes (server layer.png), pure
      LayerModel logic node-tested.
- [ ] **D. Annotations** — icon dropping + GeoJSON feature store + backend persist (mission edit-session);
      georef survives flat↔globe. GeoJSON schema + feature build node-tested.
- [ ] **E. Measure + export** — polygon area, slope profile, elevation profile, bearing; export GeoJSON/CZML/
      ROS2 YAML (reuse rc_contract GoTo)/CSV + import. Formatters node-tested against a fixed feature set.

## 8. Common failure modes to avoid

- **Client-side CRS drift** — do NOT re-implement the 30135↔lonlat transform in JS; a slightly-different
  proj string silently offsets every icon vs the server plan. Use `/dem/site_lonlat`. (This is the #1 trap.)
- **Overlay de-registration on mode/vex change** — anything that bakes ENU positions instead of routing
  through `place()` will detach on globe toggle or exaggeration. One transform, re-place, no parallel paths.
- **Per-vertex server calls** — never fetch `/dem/site_lonlat` per vertex; cache the bilinear metres→lonlat
  grid once per tile (batched), interpolate client-side.
- **Vertical exaggeration fighting curvature** — exaggerate about the tile mean radius, not raw |elev|, or a
  globe tile balloons.
- **Wrong-site async emits** — every raycast→lonlat emit MUST carry the `plotGen`/site guard (the council
  race). A drop that resolves after a site switch = a phantom wrong-site icon.
- **Web-Mercator assumption** — lunar polar-stereographic is NOT Mercator; never assume. Read CRS from
  `/dem/site_meta`.
- **Float precision on the sphere** — body-fixed metres are ~1.7e6; keep the tile patch recentred to the
  origin (worldFromBody) so Three.js float32 positions stay small and jitter-free.
- **nodata as elevation** — a nodata pixel rendered as 0 m punches a hole; mask nodata (from site_meta) out
  of the mesh + profiles.
