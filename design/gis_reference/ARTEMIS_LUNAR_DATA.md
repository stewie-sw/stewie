# Artemis — Lunar South Pole Data Catalog

The authoritative NASA datasets for the lunar south pole (Artemis III landing zone) and how each maps into
GeoLibre/Artemis. **Reference frame for all polar products: MOON_ME (mean-Earth/polar-axis), ephemeris DE421,
south-polar-stereographic X/Y in metres.** This is the frame the STEWIE Haworth tile already uses.

## 1. Topography — LOLA DEMs (PGDA = Planetary Geodesy Data Archive, gsfc.nasa.gov)

| Product | Coverage / res | Format | Use in Artemis | Link |
|---|---|---|---|---|
| **LOLA 5 m polar DEM** `ldem_87s_5mpp` | **87–90°S @ 5 m** (3.3 GB COG, Z in m) | polar-stereo COG | the pole cap at full res | pgda.gsfc.nasa.gov/products/78, data: pgda.gsfc.nasa.gov/data/LOLA_5mpp/ |
| **LOLA 20 m polar DEM** `LDEM_80S_20MPP_ADJ.TIF` | **80–90°S @ 20 m** | polar-stereo COG | regional polar terrain | pgda.gsfc.nasa.gov/products/78 |
| **South Pole LOLA DEM Mosaic** | south polar mosaic | polar-stereo | alt. mosaic | pgda.gsfc.nasa.gov/products/81 |
| **"A New View of the South Pole from LOLA"** | improved polar DEM | polar-stereo | latest polar DEM | pgda.gsfc.nasa.gov/products/90 |
| **Large-scale LOLA elevation (OpNav)** | regional | GeoTIFF | nav-grade | pgda.gsfc.nasa.gov/products/92 |
| **LOLA global LDEM** | global, 118 m–1 km | simple-cyl / mercator-able | GLOBAL 3D terrain (Artemis + Gaia/Ares analog) | imbrium.mit.edu (LOLA PDS node) |
| **STEWIE Haworth tile** (already local) | 10×10 km @ 5 m, ~86°S | `.rf32` (from Product 78) | the mission work-site 5 m | `stewie/code/samples/lunar_dem/haworth_10km_5m/` |

## 2. Imagery

| Dataset | Coverage | Frame | Use | Link |
|---|---|---|---|---|
| **OPM Moon basemap** (current Artemis base) | global to ~85° | web-mercator XYZ | base globe (mercator, caps at 85°) | openplanetary.org (in use) |
| **LROC NAC South Pole Mosaic** `NAC_POLE_SOUTH` | **−90 to −85.5°**, 40 polar-stereo tiles | polar-stereo | high-res pole imagery to fill the 85–90° cap | data.lroc.im-ldi.com/lroc/view_rdr/NAC_POLE_SOUTH |
| **LROC WAC global mosaic** | global | simple-cyl | mid-res global (OPM derives from this) | lroc.asu.edu |

## 3. Permanently Shadowed Regions (PSR) + Illumination

| Dataset | What | Use | Link |
|---|---|---|---|
| **LROC PSR Atlas** | every PSR ≥10 km² within 9° of pole (81–90°S), per-PSR NAC mosaics | PSR overlay (ice/shadow context — critical for Artemis) | LROC PDS RDR archive |
| **LROC Polar Illumination Maps** (PDS r32 RDRs) | % illumination over a lunar year, 100 m grid | solar/illumination layer (landing-site viability) | lroc.im-ldi.com/news/991 |
| **NASA SVS South Pole viz** | context renders | reference | svs.gsfc.nasa.gov/gallery/moonpole/ |

## 4. Landing sites — Artemis III candidate regions

- **13 candidate regions** (NASA, Aug 2022), each ~15×15 km, all within 6° of the pole: Peak near Shackleton,
  Connecting Ridge, Connecting Ridge Extension, de Gerlache Rim 1, de Gerlache Rim 2, de Gerlache-Kocher Massif,
  Faustini Rim A, **Haworth** (the STEWIE site), Malapert Massif, Leibnitz Beta Plateau, Nobile Rim 1,
  Nobile Rim 2, Amundsen Rim.
- **Authoritative coordinates**: USGS **Down-Selected Artemis III Candidate Landing Site Navigational Grids**
  (LGRS, Artemis Condensed Coordinate) — ScienceBase item 671a6fa8, and astrogeology.usgs.gov. Confirmed anchor:
  Nobile Rim 2 (DM2) = −84.202°, 60.700°E.

## 5. Integration plan into Artemis (GeoLibre = MapLibre globe)

The pole cap (85–90°S) cannot come from a web-mercator XYZ scheme (mercator stops at ~85°). So:

1. **Landing sites** → vector GeoJSON from the USGS grids (accurate markers, place correctly on the globe at any
   latitude). ✅ do first.
2. **LOLA global LDEM** → reproject to web-mercator terrarium/Terrain-RGB tiles → GeoLibre `raster-dem` terrain +
   hillshade (covers the globe incl. the pole region draped on the sphere). ✅ do first.
3. **Pole cap (85–90°)** → reproject the LOLA 20 m + 5 m polar DEM and the LROC NAC polar mosaic from
   polar-stereo → a form GeoLibre can drape at the pole (a bounded polar-cap raster / a custom pole source).
   This is the real coordinate-accuracy fix at the pole. Heavy pipeline (gdalwarp + tiling).
4. **5 m site detail** → the Haworth 5 m (+ LOLA 5 m 87–90°S) as high-res local layers; link innermost sites to
   the STEWIE cockpit polar-stereographic frame for cm/m work.
5. **PSR + illumination** → vector/raster overlays (shadow + sunlight context).

**Tooling:** GDAL (`gdalwarp` reproject polar-stereo→mercator, `gdal2tiles`/`rio-rgbify` terrarium), GeoLibre's
rasterio sidecar for COG handling.

**Sources:** [PGDA Product 78](https://pgda.gsfc.nasa.gov/products/78) · [PGDA Product 81](https://pgda.gsfc.nasa.gov/products/81) · [PGDA Product 90](https://pgda.gsfc.nasa.gov/products/90) · [LOLA 5mpp data](https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/) · [LROC NAC South Pole](https://data.lroc.im-ldi.com/lroc/view_rdr/NAC_POLE_SOUTH) · [USGS Artemis grids](https://www.sciencebase.gov/catalog/item/671a6fa8d34efed5620f89f8) · [NASA Artemis regions](https://www.nasa.gov/news-release/nasa-identifies-candidate-regions-for-landing-next-americans-on-moon/)
