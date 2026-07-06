# Artemis — Selectable Map Layer Catalog (lunar south pole)

Every lunar south-pole map source Aaron named, organized into the **three rendering paths** the pole forces
(established this session): mercator/globe rasters die below ~85°, so only vectors + a per-site OrbitView reach
85-90°S. This is the concrete backing for reconciliation rows **BW-01** (`/layers`), **GW-06** (layer tree),
**MA-01** (accuracy), and the OrbitView terrain. Status: LIVE = in Artemis now · PULL = downloading/encoding ·
CAT = catalogued, endpoint known, not yet wired.

## Path A — Mercator/globe raster layers (selectable overlays, valid to ~85°S)

MapLibre-consumable (Web-Mercator XYZ, or WMS/WMTS reprojected). These populate the GeoLibre layer tree as
toggleable overlays over the base globe. Below ~82°S they smear (honest imagery-gap banner, MA-01).

| Layer | Source | Endpoint | Status |
|---|---|---|---|
| OPM Moon basemap (LRO/LOLA + CARTO) | OpenPlanetaryMap | `opm-moon-basemap-v0-1/all/{z}/{x}/{y}.png` (Web-Mercator) | **LIVE** (base) |
| Moon Trek — LOLA color hillshade, LROC WAC mosaic, LOLA slope | NASA Solar System Treks | `trek.nasa.gov` WMTS (Equirectangular service); per-layer id via GetCapabilities | CAT |
| LROC imagery / topographic (global, polar, regional) | ASU LROC **Lunaserv** | WMS `https://wms.lroc.asu.edu/lroc` (+ `webmap.lroc.asu.edu`) | CAT |
| QuickMap layer set | LROC **QuickMap** | `quickmap.lroc.im-ldi.com` OGC WMTS (`/1.0.0/{Style}/{TileMatrixSet}/{z}/{y}/{x}.png`) | CAT |

## Path B — OrbitView polar-stereographic DEMs (per-site 3D, 85-90°S)

Download-only polar-stereo GeoTIFFs → `scripts/encode_terrain_points.py` → `.bin` point cloud → deck.gl
OrbitView (the only pole-truthful renderer). All share `+proj=stere +lat_0=-90 +R=1737400`.

| DEM | Source | Res | Coverage | Status |
|---|---|---|---|---|
| **Haworth photoclinometry (SfS)** | USGS `planetarymaps.usgs.gov/mosaic/Lunar_Photoclinometry/Haworth-SfS/Lunar_LROnac_Haworth_sfs-dem_1m_v3.tif` (537 MB) | **1 m** | Haworth crater, 86.6-87.1°S | **PULL** (downloading) |
| 8× Artemis site DEMs | PGDA Product 78 `pgda.gsfc.nasa.gov/data/LOLA_5mpp/Site*/*_surf.tif` | 5 m | 85-90°S candidate sites | **LIVE** (OrbitView) |
| LOLA 5 m polar | PGDA Product 78 | 5 m | 87-90°S | CAT |
| LOLA 20 m polar | PGDA Product 78 | 20 m | 80-90°S | CAT |
| LROC NAC South Pole mosaic (imagery drape for the OrbitView) | `data.lroc.im-ldi.com/lroc/view_rdr/NAC_POLE_SOUTH` | ~1-2 m | −90 to −85.5° | CAT |

## Path C — Vector layers (place correctly at ANY latitude on the globe)

Real MapLibre GeoJSON layers — vectors render at the pole where rasters can't.

| Layer | Source | Status |
|---|---|---|
| Artemis III LOLA-5m sites (8 clickable pins → OrbitView) | DEM centres (gdalinfo) | **LIVE** |
| Artemis III candidate regions (13, polygons) | USGS Down-Selected Navigational Grids (ScienceBase 671a6fa8) | CAT |
| PSR — permanently shadowed regions (outlines) | LROC PSR Atlas (≥10 km², 81-90°S) | CAT |
| Illumination (% over a lunar year) | LROC Polar Illumination Maps (PDS r32) | CAT |
| LPI South Pole Atlas reference products | lpi.usra.edu/lunar/lunar-south-pole-atlas (403 to bots; via QuickMap/USGS mirrors) | CAT |

## Pull-in plan (realizes BW-01 + GW-06 for lunar)

1. **Haworth 1 m** → encode → OrbitView (highest-res mission site). *(in progress)*
2. **Path A overlays** → a GeoLibre layer-tree entry per Trek/LROC layer (raster source + toggle + legend +
   provenance); GetCapabilities parsed at wire time for the exact ids. Selectable, opacity, ordering.
3. **Path C vectors** → the site polygons + PSR + illumination as GeoJSON layers (the pins already prove the
   pattern), clickable → Site Inspector.
4. **BW-01 wiring**: once the STEWIE `/layers` manifest carries these with `renderTarget` (mercator vs
   site-inspector) + provenance/uncertainty, Artemis pulls the catalog from the backend instead of hardcoding.

## Mission-accurate rendering (COG-backed) — screened 2026-07-05, build queued

**Why not the PNG previews:** 8-bit color-quantized + downsampled to 1500 px + non-queryable = a picture, not
data. Detailed/mission work (MA-01) needs float32, full resolution, and readable values → **COG**.

**Reuse (GeoLibre already ships all of it):** `@developmentseed/deck.gl-geotiff` (a deck.gl COG layer — app
dep), `geotiff` ^3.0.5 (via processing/plugins), `@geolibre/processing` → `readRasterData`
(`bands: Float32Array[]` + width/height/originX), `convertGeoTiffToCog`, `readGeoTiffInfo`, `cog-tiler-wasm`.

**Data (done):** `scripts/cogify.sh` → `public/data/cog/<Site>/{dem,slope}.tif` (COG + overviews 1600/800/400,
Float32, DEFLATE) — ~73 MB/site (dem 29 + slope 47); `Haworth_1m_dem.tif` **259 MB**. Total **946 MB** →
**served from a mounted volume** (`.dockerignore`d, NOT baked; nginx range requests are the COG pattern).

**Build steps (queued, in order):**
1. Volume-serve the COGs: `-v .../public/data/cog:/usr/share/nginx/html/data/cog:ro` in the deploy.
2. **Value readout** (the mission-accuracy payoff): deck.gl `onClick` → local polar-stereo coord → real float.
   Sites (29 MB) via `readRasterData` (fetch-once + cache); the 259 MB Haworth needs `geotiff.js fromUrl`
   **range reads** → add `geotiff` to the app deps (a `package-lock` update).
3. **Float display**: render the COG float client-side with an *adjustable* color-map (deck.gl-geotiff layer,
   or geotiff overview → color-map canvas → BitmapLayer), replacing the PNGs; PNGs stay as fast thumbnails.
4. **Local-frame coords (MA-01)**: readout shows elevation/slope + local `x/y` (m) + selenographic lon/lat
   (proj4 from the site's polar-stereo origin), no Earth claim.

**Sources:** [USGS Haworth 1m DEM](https://astrogeology.usgs.gov/search/map/lunar_lro_nac_haworth_photoclinometry_dem_1m) · [LROC QuickMap](https://quickmap.lroc.im-ldi.com/) · [LROC Lunaserv WMS](https://wms.lroc.asu.edu/lroc) · [Moon Trek API](https://trek.nasa.gov/tiles/apidoc/trekAPI.html?body=moon) · [LPI South Pole Atlas](https://www.lpi.usra.edu/lunar/lunar-south-pole-atlas/)
