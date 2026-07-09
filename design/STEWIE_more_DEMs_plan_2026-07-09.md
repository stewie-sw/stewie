# STEWIE — plan for adding more REAL lunar DEM sites (task #43)

**Status:** read-and-plan only. No pipeline code touched, no DEM fabricated, no download executed.
Everything below is either (a) confirmed by reading the live code/data on this host, or (b)
sourced from a live web fetch and marked as such — nothing is invented.

---

## 1. Pipeline summary (confirmed — how a real DEM becomes a STEWIE site bundle)

### 1.1 The on-disk bundle format (confirmed: `samples/lunar_dem/haworth_10km_5m/metadata.json`)

A site bundle is a directory with 5 raster files (`heightmap.rf32`, `mass_areal.rf32`,
`density.rf32`, `disturbance.rf32`, `state_label.r8`, all row-major little-endian) plus a
`metadata.json`. The load-bearing fields for a **new real** bundle:

- `grid.{width,height,cell_m}` — cell size (5.0 m for every curated site today).
- `world_bounds_m` — the tile's GLOBAL frame offsets (non-zero; this is what lets the globe
  drape and planner place the tile correctly). Contract: `docs/dem_terrain_contract.md` §2.
- `dem_provenance` — `source`, `frame`, `z_semantics`, `native_cell_m`, `citation`,
  `license_basis`. Every existing bundle cites *"Barker et al. 2021 (Planet. Space Sci.
  203:105119); Mazarico et al. 2011 (Icarus 211:1066)"* and *"U.S. Government work (NASA GSFC
  PGDA) … treated as public-domain / CC0-compatible"* (confirmed identical across all 10
  on-disk bundles, `dart/dem_import.py:148-160` region-derivation + `THIRD_PARTY.md:82-85`).
- `region`, `local_datum_offset_m`, `height_range_m`, `regolith_model` (the ChaSTE
  depth-integrated mantle density, not a spatial field — `dart/dem_import.py:440-500`).

### 1.2 The ingest path (confirmed: `dart/dem_import.py`, `scripts/build_from_dem.py`)

For a **same-frame polar** LOLA product (the PGDA Product-78 `*_surf.tif` lane already used 10
times):

```
load_lola_geotiff(path)   -- pure PIL + hand-parsed GeoTIFF tags (33550/33922/34735), NO GDAL
      -> (Z float32 [height-above-sphere, m], Affine, meta)
crop_square(Z, affine, center_xy_m, extent_m)
      -> pixel-window slice, NO reprojection (product is already south-polar-stereographic,
         IAU_2015:30135, R=1737400 m)
dem_to_base(Z_crop, affine_crop, base_cell_m, mantle_m=Z_T, density_fn=polar_mantle_density_fn())
      -> ColumnState via the frozen datum path: datum = Z - mantle_m, mass_areal = mantle_m*rho,
         derive_height() == Z to ~1e-3 m
save_scene(...) + write_hillshade_png(...)          -- stewie.twin.io_fields
```

`scripts/build_from_dem.py` wraps all of this end-to-end (crop at max-relief window, inject,
write metadata, self-verify the round-trip, assert non-zero `world_bounds_m`) — it is exactly
the script that produced all 10 existing bundles (`producer` field in every metadata.json).
CLI: `python scripts/build_from_dem.py --src <tif> --out samples/lunar_dem/<name>_10km_5m
[--extent-m 10000] [--base-cell-m 5.0] [--stride 200]`.

For a **non-polar / equirectangular** product, `dart/dem_import.py`'s absorbed
`reproject_cylindrical(...)` (pyproj-based, local azimuthal-equidistant frame) +
`ingest_to_bundle(...)` do the equivalent — this is the path `stewie/terrain/adhoc_dem.py`
uses (below), not yet used for a curated site.

### 1.3 Registering a new site (confirmed: `stewie/specs/sites.py`, `dart/dem_sources.py`)

Two registries must be updated for a new curated site to become selectable, and they are
**presently out of sync** with each other (finding, §4):

- **`stewie/specs/sites.py`** — the `SITES` dict. Each `Site(name, label, lat_deg, lon_deg,
  artemis_candidate, bundle_dir=_bundle("<dirname>"), note=...)`. `bundle_dir` is `None` until
  the tile is actually imported (`sites.py:22-24`, `_bundle()` checks `os.path.isdir`) — this is
  the "honest state" the file's own docstring describes. **10 of the 13 sites already carry a
  real `bundle_dir`.**
- **`dart/dem_sources.py`** — the `_CATALOG` tuple that feeds `GET /dem/sources` (the cockpit
  layer selector + the THIRD_PARTY provenance audit). A `DemSource(id, name, instrument,
  resolution_m, coverage, crs, fmt, access_url, license, ingest, bundled=True/False, notes=...)`.

### 1.4 The request-time "PLAN ANYWHERE" resolver (confirmed: `stewie/terrain/adhoc_dem.py`)

For an **arbitrary** lat/lon that is not one of the curated sites, `resolve_adhoc_bundle(lat,
lon, extent_m=10000)` (`adhoc_dem.py:93-116`):

1. Validates `|lat| <= 89.9°` (a local equirectangular crop degenerates at the literal pole —
   the curated polar-stereo tiles serve that case instead).
2. Opens the **on-host global LOLA LDEM** (`Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif`,
   already at `/mnt/projects/datasets/argus_dem_nav/lunar_dem/`, override via
   `$STEWIE_GLOBAL_LDEM`), windowed-reads a halo'd crop via `rasterio`.
3. Reprojects that equirectangular patch to a **local** azimuthal-equidistant frame centred on
   the pick (`dart.dem_import.reproject_cylindrical(..., return_frame=True)`) — chosen
   specifically so distortion is ~0 at ANY latitude (polar-stereo would be ~2x scale-error at
   the equator; AEQD is not).
4. Crops to the pick-centred `extent_m` square (`dart.dem_import.crop_square`), writes a
   Haworth-format bundle (`dart.dem_import.ingest_to_bundle`) into a cache keyed by
   `adhoc_site_id(lat, lon)` (milli-degree granularity, ~30 m — repeat picks in the same cell
   are a cache hit), published atomically (`tempfile` + `os.replace`).
5. Fails HONESTLY: `FileNotFoundError` if the global LDEM asset is absent, `ValueError` for a
   degenerate/out-of-range window — **no synthesized surface is ever substituted** (this is
   asserted three separate times in the module's own comments and enforced by raising, not
   returning a stand-in).

The router (`stewie/server/routers/dem.py`) and `stewie.specs.sites.site_latlon` already thread
`adhoc_*` ids through the exact same code paths a curated site uses
(`is_adhoc_site`/`parse_adhoc_site` in `sites.py:85-90`), so an off-site pick is not a second,
parallel feature — it is the same DEM-consumption surface with a different resolver upstream.

---

## 2. Real candidate DEM sources (with provenance + license)

Confidence tags: **[CONFIRMED]** = read directly from this repo's code/data/docs.
**[WEB-CONFIRMED]** = live-fetched this session (cross-checked with a second independent fetch
where noted). **[WEB, single-source]** = one fetch, not independently cross-checked — verify
before ordering a download.

| Source | Resolution | Coverage | Access | License basis | Status here |
|---|---|---|---|---|---|
| **PGDA Product 78** — LOLA 5 m polar DEM, per-site tiles (Barker et al. 2021) | 5 m/px | ~15×15 km per named site, south pole | `pgda.gsfc.nasa.gov/products/78`, data at `pgda.gsfc.nasa.gov/data/LOLA_5mpp/` | U.S. Gov work (NASA GSFC PGDA); no formal license string, treated public-domain (repo's own `THIRD_PARTY.md:84`) | **10 sites already imported** [CONFIRMED] |
| **PGDA Product 78 — Site42** (de Gerlache-Kocher Massif) | 5 m/px | one of the official 13 Artemis III candidate regions | same as above | same as above | **Raw tile ALREADY ON HOST**, not yet ingested — see §3.1 [CONFIRMED] |
| **PGDA Product 78 — DM1** (Amundsen Rim) | 5 m/px | official 13th candidate region | `pgda.gsfc.nasa.gov/data/LOLA_5mpp/` (file pattern `DM1_final_adj_5mpp_surf.tif`) | same as above | not on host, real download needed [WEB-CONFIRMED, 2 independent fetches] |
| **PGDA Product 78 — LM7** (Faustini Rim A) | 5 m/px | official 13th candidate region | same, `LM7_final_adj_5mpp_surf.tif` | same as above | not on host, real download needed [WEB-CONFIRMED, 2 independent fetches] |
| **PGDA Product 78 — SL2 / SL3** (de Gerlache Rim 2 / Connecting Ridge Extension) | 5 m/px | supplementary PGDA site tiles beyond the core 13 | same | same as above | not on host, real, lower priority [WEB-CONFIRMED] |
| **PGDA Product 78 — NPA/NPB/NPC/NPD, LM1–LM8** (Cabeus Ext. Wall 1, Amundsen 1, Idel'son L Crater 1, Malapert Crater 1, Shackleton/Shoemaker Rim variants) | 5 m/px | additional named PGDA site tiles, not part of the official 13 | same | same as above | not on host, real, exists if broader coverage is wanted later [WEB-CONFIRMED] |
| **PGDA Products 81/90** — South Pole LOLA DEM Mosaic / "A New View of the South Pole from LOLA" | 5–30 m/px | regional mosaic, poleward of 80°S | `pgda.gsfc.nasa.gov/products/81`, `/90` | same U.S.-Gov basis | real, already cited in `docs/map_reference.md:13-14`; would give REGIONAL context between the per-site tiles, not a new named site — different use case than "one more site" |
| **LROC NAC stereo DTM — `NAC_DTM_SHACKRDGE02`** (Shackleton–de Gerlache Connecting Ridge) | 3.5 m/px native (product resampled 3–10× that) | −89.63° to −89.37°S, 209.81°–239.10°E — directly overlapping the existing shackleton_rim / de_gerlache_rim / connecting_ridge tiles | `data.lroc.im-ldi.com/lroc/view_rdr/NAC_DTM_SHACKRDGE02` | LROC/PDS instrument-team product, NASA-funded — same public-domain basis as LOLA (not independently re-confirmed for this specific product page, but consistent with every other LRO PDS product in this catalog) | real, downloadable GeoTIFF today; would be a genuine **resolution upgrade** (~3.5 m vs the existing 5 m LOLA) over an already-imported area [WEB-CONFIRMED] |
| **LROC NAC Photoclinometry (SfS) DEM 1 m — Haworth** (O'Connor & Beyer, NASA Ames, 2021) | 1 m/px | Haworth crater area | `astrogeology.usgs.gov/search/map/lunar_lro_nac_haworth_photoclinometry_dem_1m` (537 MB GeoTIFF) | public domain via USGS Astrogeology / PDS | real, downloadable; **the existing `dart/dem_sources.py` `lroc_nac_sfs_1m` entry's `access_url` is WRONG/404 — see §4** [WEB-CONFIRMED] |
| **Kaguya TC / SLDEM2015** (Barker et al. 2016, Icarus 273) | ~60 m/px (512 ppd) | **±60° latitude only** | `pgda.gsfc.nasa.gov/products/54`, PDS LOLA node / `imbrium.mit.edu` | public domain (NASA/JAXA joint product, U.S.-Gov-hosted) | **NOT usable for STEWIE's south-polar sites** — its coverage stops at 60°S, ~25–30° short of every current/candidate STEWIE site (all at 84–90°S). Named in the task; ruled out here on coverage grounds, not fabricated as a candidate. |
| **Global LDEM 118 m** (Smith et al. 2010) | 118 m/px | global | `astrogeology.usgs.gov/search/map/moon_lro_lola_dem_118m` | public domain | **already on host and already wired into the plan-anywhere resolver** — see §3 |
| **LuNaMaps SfS strip** (Bertone et al. 2023/2026, Zenodo 10.5281/zenodo.10258683 / .17954508) | 30 m/px | 60–80°S approach corridor | Zenodo | **CC-BY-4.0 — NOT public domain** | real, but the repo's own `THIRD_PARTY.md:87` already deliberately keeps this reference-only (download-script / marked CC-BY subfolder only) for license-segregation reasons. Do not casually vendor into `samples/lunar_dem/` alongside the CC0-treated PGDA tiles without the same attribution-subfolder treatment. |

---

## 3. Feasibility assessment — what already works vs what needs a real ingest

### 3.1 "More sites" that ALREADY work today, with zero code change

**Any arbitrary lat/lon (|lat| ≤ 89.9°) already resolves to a real, non-fabricated 118 m/px DEM
crop** via `stewie/terrain/adhoc_dem.resolve_adhoc_bundle` — this is not a future capability, it
is live code exercised by `stewie/server/test_plan_anywhere.py` today. A pick anywhere off the
10 curated sites gets a real crop of the global LOLA LDEM, reprojected to a local frame with ~0
warp at that latitude, cached, and consumed by the same `bundle_for_site` / `load_site_dem` /
globe-drape / planner code the curated sites use. The honesty is real: the resolution is coarse
(native ~118 m/px, explicitly labeled `"NOT upsampled or infilled off-site"` in the written
metadata), but it is not synthetic — it is the real global product, cropped.

**So "add more DEM coverage" is already solved for the *reconnaissance-grade* case.** What is
NOT yet solved is *site-scale planning-grade* (5 m or better) detail at a NEW named location —
that needs a real high-res ingest per §3.2.

### 3.2 What a new 5 m curated site needs, concretely

1. **Obtain the real `*_surf.tif`** for the target site (download from PGDA, or — for Site42 —
   it is already on this host, see below).
2. Run `python scripts/build_from_dem.py --src <path/to/SiteNN_surf.tif> --out
   samples/lunar_dem/<name>_10km_5m` (defaults: 10 km extent, 5 m cell — matches every existing
   bundle). This is the exact script + defaults used 10 times already; no new code path.
3. Confirm the script's own self-verification passes (`VERIFY round-trip heightmap max_err=...`
   printed by `build_from_dem.py:184-193`, plus its `AssertionError` guards on non-zero
   `world_bounds_m` and round-trip error).
4. Add a `Site(...)` entry to `stewie/specs/sites.py` (`bundle_dir=_bundle("<dirname>")`, real
   lat/lon center, `artemis_candidate=True/False`).
5. Add a `DemSource(...)` entry to `dart/dem_sources.py` with `bundled=True` so `GET
   /dem/sources` reports it correctly (currently this step has been SKIPPED for 7 of the 10
   existing sites — finding, §4).
6. Re-run the DEM-touching test gate: `dart/test_dem_sources.py`,
   `stewie/server/test_dem_sources_registry.py`, `stewie/specs/test_sites.py`,
   `stewie/server/test_geo_siting.py`, `stewie/server/test_plan_anywhere.py`.

**Is this safe/feasible to run on this host?** Yes for the PGDA Product-78 lane specifically:
pure PIL + numpy + scipy (no GDAL/rasterio needed for the same-frame polar crop), the exact code
path already exercised 10 times, no new dependency, runtime is small (the existing 10 tiles were
all built this way already). For a **non-polar or non-Product-78** product (the LROC NAC DTM,
the Haworth SfS 1 m), the CRS/GeoTIFF tags have not been confirmed against
`dart.dem_import.load_lola_geotiff`'s assumptions (classic TIFF, mode `'F'` single-band
float32, `ModelPixelScale`/`ModelTiepoint`/GeoKeys tags) — this would need a short verification
step on the actual downloaded file before assuming the same zero-new-code ingest lane applies.

### 3.3 What needs Aaron's go before I touch it

- **Any download** — PGDA Site42's sibling tiles on this host range 41–142 MB each
  (`ls -la /mnt/projects/datasets/lola_5mpp/`); DM1/LM7 are very likely in the same range (not
  yet confirmed, since they are not downloaded). The Haworth SfS 1 m product is 537 MB — the
  largest single file this pipeline would touch. None of these are large by absolute bandwidth
  standards, but per the task instructions and standing operating discipline, **no download
  executes without an explicit go**, regardless of size.
- **Ingesting Site42** needs NO download (already on host) but DOES write new files under
  `samples/lunar_dem/` and edit two registry files — flagged below as the recommended next step,
  not yet executed.

---

## 4. Findings along the way (bugs/drift, flagged — not fixed, per "read-and-plan only")

1. **`dart/dem_sources.py`'s bundled-set is stale.** Only 3 of the **10** real, already-imported
   site bundles are marked `bundled=True` in the catalog (`haworth_10km_5m`,
   `nobile_rim1_10km_5m`, `shackleton_rim_10km_5m`). The other 7 — `connecting_ridge_10km_5m`,
   `de_gerlache_rim_10km_5m`, `leibnitz_beta_10km_5m`, `malapert_massif_10km_5m`,
   `nobile_rim2_10km_5m`, `peak_near_shackleton_10km_5m`, `shoemaker_10km_5m` — sit real and
   ready on disk (confirmed via `ls samples/lunar_dem/` and each one's `metadata.json`) but are
   entirely ABSENT from `_CATALOG`, so `GET /dem/sources` (the cockpit layer selector's source of
   truth) currently underreports STEWIE's own real DEM coverage. The test
   `dart/test_dem_sources.py:22-28`
   (`test_bundled_sources_match_the_three_on_disk_tiles_rest_gated`) hardcodes and asserts the
   stale 3-tile set, so this drift is currently green, not red — the test's own premise ("three
   real LOLA tiles are carved into samples/lunar_dem") is factually out of date relative to
   `stewie/specs/sites.py`, which correctly lists all 10. This is a pre-existing gap, unrelated
   to adding a new site, but adding an 11th site without fixing it would make the drift worse.
2. **`dart/dem_sources.py`'s `lroc_nac_sfs_1m.access_url` 404s.** It points to
   `.../lunar_lro_nac_haworth_sfs_dem_1m`; the live product is at
   `.../lunar_lro_nac_haworth_photoclinometry_dem_1m` (confirmed via WebFetch: the former returns
   USGS's literal 404 page, the latter loads the real product page).

Both are cheap, safe, narrowly-scoped fixes (edit two lines / one catalog gap) that a future pass
could take alongside a new-site addition — flagged per the "cheap adjacent win" convention, not
actioned here since the task scope is read-and-plan.

---

## 5. Recommended next step

**Two real, concrete moves, ranked by confidence/cost:**

### 5.1 Do first — ingest Site42 (de Gerlache-Kocher Massif). Zero network, zero new code path.

The raw tile is **already on this host**: `/mnt/projects/stewie/data/gis/raw/Site42_surf.tif`
(64 MB, fetched 2026-07-05 for the QGIS/gis/ track — confirmed via `ls -la` and
`gis/build_project.py:59,80` / `gis/README.md`'s Site42 row: center −116.32°, −85.830°, DEM range
−1093.2/2997.7 m). It is one of the 13 official Artemis III candidate regions and is not yet in
`samples/lunar_dem/` or either registry. Exact steps:

```bash
python scripts/build_from_dem.py \
  --src /mnt/projects/stewie/data/gis/raw/Site42_surf.tif \
  --out samples/lunar_dem/de_gerlache_kocher_massif_10km_5m
```

then add to `stewie/specs/sites.py`:
```python
Site("de_gerlache_kocher_massif", "de Gerlache-Kocher Massif (Site42)", -85.830, -116.32,
     artemis_candidate=True, bundle_dir=_bundle("de_gerlache_kocher_massif_10km_5m"),
     note="PGDA Product 78 Site42; 10 km / 5 m tile"),
```
and a matching `bundled=True` `DemSource` row in `dart/dem_sources.py`, then re-run the test
gate in §3.2 step 6. This completes 11/13 of the official Artemis III candidate list on this
host and needs no download, no new dependency, and no CRS verification (same PGDA Product-78
lane run 10 times already).

### 5.2 Do second (needs your go — real external download) — Amundsen Rim (DM1) and/or Faustini
Rim A (LM7), the two still-missing official Artemis III candidate regions.

Both are real PGDA Product-78 tiles (`DM1_final_adj_5mpp_surf.tif`,
`LM7_final_adj_5mpp_surf.tif`), same license basis, same ingest lane, from
`pgda.gsfc.nasa.gov/data/LOLA_5mpp/`. Fetching both would bring STEWIE to **13/13** of the
official candidate regions. **I have not downloaded these — say go and I will fetch, verify the
GeoTIFF tags match `load_lola_geotiff`'s assumptions, run the same `build_from_dem.py` lane, and
register both.**

A lower-priority third option once 5.1/5.2 are done: the `NAC_DTM_SHACKRDGE02` LROC stereo DTM
(~3.5 m/px) as a resolution upgrade over the existing Shackleton/de Gerlache/Connecting-Ridge
tiles — real and downloadable today, but needs a short CRS-tag verification step before assuming
zero-new-code ingest, so it is a slightly larger lift than 5.1/5.2 and is not the recommended
*first* move.
