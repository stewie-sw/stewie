#!/usr/bin/env python3
"""Build the STEWIE shared-core lunar QGIS project (Phase 1, P1.0/P1.1/P1.2/P1.6).

Headless, re-runnable PyQGIS builder. Constructs ``stewie_south_pole.qgz`` from
scratch every run (idempotent): the on-disk LOLA/USGS Float32 COGs at
``/mnt/projects/stewie/data/gis`` become a projection-native, float-queryable,
pole-truthful GIS in ``IAU_2015:30135`` (Moon 2015 South Polar Stereographic,
R = 1737400 m). No terrestrial datum is claimed anywhere (MA-01 no-Earth-claim).

Scope of THIS builder:
  * P1.2/P1.6 (core, VERIFIED): DEM + hillshade + slope COGs, per-site groups.
  * P1.4 (added): real site vectors derived from the COG extents -- labeled pins
    at each DEM centre + translucent footprint polygons, in IAU_2015:30100, site
    ids matching the backend naming (Site01/04/06/07/11/20/23/42). Network-free.
  * P1.3 (added, best-effort): external imagery/OGC services as QGIS raster/WMS
    layers, each render-probed headlessly; renderable ones are added to the
    project, unreachable/unrenderable ones are DEFERRED with a reason + URL.
  * P1.5 (added): the ARTEMIS_LAYERS / PRD2 base.*/terrain.*/vector.* naming is
    mirrored into the QGIS layer-tree GROUP structure; provenance in metadata.

The core DEM/hillshade/slope loop is UNCHANGED (styling + provenance preserved);
everything above is strictly additive. Gate 5 (every ARTEMIS_LAYERS row is a
loaded layer OR an explicitly-deferred row with a reason) is driven by the
importable ``ARTEMIS_ROWS`` registry; gate 6 (external connections render a real
tile) is driven by the runtime render-probe written to ``layer_status.json``.

Run (headless):
    QT_QPA_PLATFORM=offscreen /usr/bin/python3 build_project.py --date 2026-07-05

The ``--date`` argument is stamped into every layer's provenance metadata; pass
it explicitly for a reproducible build (defaults to today's date). Data paths are
written PROJECT-RELATIVE so the .qgz is portable when code/ and data/ stay
siblings under /mnt/projects/stewie/.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
import zipfile

import scene3d   # shared 3D local-scene (P1.7) XML authoring; no QGIS import at module load

# ---------------------------------------------------------------------------
# Constants (importable without side effects; QGIS is only touched inside main).
# ---------------------------------------------------------------------------
CODE_GIS_DIR = os.path.dirname(os.path.abspath(__file__))          # .../code/gis
DEFAULT_DATA_ROOT = "/mnt/projects/stewie/data/gis"
DEFAULT_OUTPUT = os.path.join(CODE_GIS_DIR, "stewie_south_pole.qgz")

PROJ_CRS = "IAU_2015:30135"   # Moon 2015 South Polar Stereographic (metric, k=1 at pole)
GEO_CRS = "IAU_2015:30100"    # Moon 2015 geographic (selenographic lon/lat)
MOON_R = 1737400.0            # lunar mean radius (m) -> measurement sphere
MOON_ELLIPSOID = "PARAMETER:1737400:1737400"  # QGIS custom sphere (no WGS84)

# 8 Artemis III candidate sites: each has dem.tif + slope.tif COGs.
SITES = ["Site01", "Site04", "Site06", "Site07", "Site11", "Site20", "Site23", "Site42"]
# Haworth carries a DEM COG only (no slope COG on disk).
HAWORTH = "Haworth_1m_dem.tif"

# DISPLAY-ONLY region names for each site id. The SiteNN ids stay the stable keys
# (COG filenames cog/<Site>/dem.tif, layer names "<Site> DEM"/layer_catalog ids
# stewie.terrain.<site>.*, backend routes, the geojson "site" round-trip property);
# these strings are ONLY the human-readable marker/label text on the maps. Grounded in
# the authoritative PGDA Product 78 site index (Barker 2021), corroborated by the repo's
# own scripts/fetch_dem_data.py SITE_DIRS + docs/data_book.md + docs/map_reference.md, and
# coordinate-confirmed against the site DEM centroids (see design/gis_reference/
# ARTEMIS_LUNAR_DATA.md for the 13 Artemis III candidate regions). Each name is one of the
# 13 NASA (Aug 2022) Artemis III candidate landing regions.
SITE_NAMES = {
    "Site01": "Connecting Ridge",
    "Site04": "Shackleton Rim",
    "Site06": "Nobile Rim 1",
    "Site07": "Peak near Shackleton",
    "Site11": "de Gerlache Rim",
    "Site20": "Leibnitz Beta Plateau",
    "Site23": "Malapert Massif",
    "Site42": "de Gerlache-Kocher Massif",
}

# Hillshade parameters (gdal:hillshade). Recorded verbatim in provenance.
HS_AZIMUTH = 315.0
HS_ALTITUDE = 45.0
HS_ZFACTOR = 1.0

# Provenance source strings.
SRC_SITE_DEM = ("PGDA LOLA Product 78 (5 m/px polar-stereographic LOLA DEM), "
                "native IAU_2015:30135")
SRC_SITE_SLOPE = ("slope in degrees, derived from the site LOLA 5 m DEM "
                  "(PGDA Product 78), native IAU_2015:30135")
SRC_HAWORTH_DEM = ("USGS Haworth 1 m Shape-from-Shading DEM (LROC NAC SfS), "
                   "native IAU_2015:30135")

# Continuous south-polar basemap (context UNDER the site DEMs so the map reads as a
# whole moon, not 8 DEMs on black). Real LOLA LDEM polar shape map -> hillshade -> COG.
BASEMAP_SUBDIR = os.path.join("cog", "basemap_south_polar.tif")
BASEMAP_NAME = "South Polar Basemap"
BASEMAP_URL = ("https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/"
               "lrolol_1xxx/data/lola_gdr/polar/img/ldem_75s_120m.img")
SRC_BASEMAP = (
    "LOLA LDEM_75S_120M polar shape map (LRO-L-LOLA-4-GDR-V1.0, 120 m/px, 75-90S, "
    "polar stereographic true-at-pole, sphere R=1737400 m; David E. Smith / LRO LOLA "
    f"Team, GSFC), PDS Geosciences Node {BASEMAP_URL} -> gdaldem hillshade (z=0.5 "
    "unscales the 0.5 m/DN shape map to true metres; az 315, alt 45, -compute_edges) "
    "-> COG. Continuous CONTEXT basemap (not an authoritative measurement surface).")
BASEMAP_CMD = (
    "gdaldem hillshade -z 0.5 -az 315 -alt 45 -compute_edges ldem_75s_120m.lbl "
    "basemap_hs_tmp.tif ; gdal_translate -of COG -a_srs IAU_2015:30135 -a_nodata none "
    "-co COMPRESS=DEFLATE -co PREDICTOR=2 -co BLOCKSIZE=512 -co OVERVIEWS=AUTO "
    "-co OVERVIEW_RESAMPLING=AVERAGE basemap_hs_tmp.tif cog/basemap_south_polar.tif")

# Hypsometric elevation palette (fraction, R, G, B) interpolated across real min..max.
HYPSO_STOPS = [
    (0.00, 44, 66, 110),    # crater floor  -> deep blue
    (0.15, 40, 110, 120),   # low           -> teal
    (0.35, 90, 150, 90),    # mid-low       -> green
    (0.55, 210, 200, 120),  # mid           -> tan
    (0.72, 170, 120, 70),   # mid-high      -> brown
    (0.86, 120, 85, 70),    # high          -> dark brown
    (1.00, 240, 240, 240),  # peaks         -> near-white
]

# Slope mobility classes (upper-bound degrees, R, G, B, A, label). IPEx envelope:
# 15 deg nominal, 20 deg slope-test (terrain_authority/ipex_specs.py). Safe class is
# transparent so DEM+hillshade read through; hazard classes escalate to warning red.
SLOPE_CLASSES = [
    (5.0, 0, 0, 0, 0, "0-5 deg (mobility-safe)"),
    (10.0, 255, 235, 120, 80, "5-10 deg (caution)"),
    (15.0, 255, 165, 40, 120, "10-15 deg (approaching IPEx 15 deg nominal)"),
    (20.0, 235, 70, 30, 155, "15-20 deg (IPEx slope-test envelope)"),
    (1.0e6, 150, 25, 20, 190, ">20 deg (no-go)"),
]

# ---------------------------------------------------------------------------
# P1.4 site-vector styling + P1.5 catalog groups.
# ---------------------------------------------------------------------------
VECTORS_SUBDIR = os.path.join("vectors", "artemis_sites.geojson")
GPKG_SUBDIR = os.path.join("derived", "lunar_south_pole.gpkg")

# Layer-tree GROUP labels (P1.5): base = external imagery/context (non-authoritative
# frame), terrain = the authoritative LOLA/USGS COGs, vectors = the derived sites.
GRP_BASE = "Base & imagery - external context (non-authoritative frame)"
GRP_TERRAIN = "Terrain & hazard - authoritative (IAU_2015:30135)"
GRP_VECTORS = "Site vectors (IAU_2015:30100)"
GRP_BASEMAP = "South-polar basemap - LOLA LDEM context (IAU_2015:30135)"

# Pin marker + footprint fill (translucent so the terrain reads through).
PIN_RGB = (255, 210, 60)
FOOTPRINT_RGB = (80, 200, 235)

# ---------------------------------------------------------------------------
# P1.3 external services (real endpoints from ARTEMIS_LAYERS.md, verified on host
# 2026-07-05). Each renderable service is a QGIS WMS layer. Lunaserv advertises
# EPSG:4326 (Earth) + IAU2000:* (which QGIS 3.22 PROJ does NOT resolve) -> we
# request over the EPSG:4326 wire grid and RELABEL the QGIS layer CRS to the lunar
# geographic datum IAU_2015:30100 (same numeric lon/lat, no Earth claim), so QGIS
# reprojects lunar->lunar onto the 30135 polar canvas. Verified: NAC SP mosaic
# renders 0.68 non-black over Site01.
LUNASERV_URL = "http://wms.im-ldi.com/"   # LROC Lunaserv (moved from wms.lroc.asu.edu/lroc)
STEWIE_OGC_URL = "http://127.0.0.1:8000/ogc/wms"


def _wms_uri(url: str, layer: str, wire_crs: str, fmt: str = "image/png") -> str:
    return (f"contextualWMSLegend=0&crs={wire_crs}&dpiMode=7&format={fmt}"
            f"&layers={layer}&styles&url={url}")


EXTERNAL_SERVICES = [
    dict(id="stewie.base.lroc_nac_sp", name="LROC NAC South Pole mosaic (Lunaserv)",
         provider="wms", uri=_wms_uri(LUNASERV_URL, "luna_nac_2m_sp_mosaic", "EPSG:4326"),
         relabel="IAU_2015:30100", probe="site", add_when_blank=False,
         source="LROC Lunaserv WMS (wms.im-ldi.com) layer luna_nac_2m_sp_mosaic",
         endpoint=LUNASERV_URL),
    dict(id="stewie.base.lroc_wac_global", name="LROC WAC global mosaic (Lunaserv)",
         provider="wms", uri=_wms_uri(LUNASERV_URL, "luna_wac_global", "EPSG:4326"),
         relabel="IAU_2015:30100", probe="context", add_when_blank=False,
         source="LROC Lunaserv WMS (wms.im-ldi.com) layer luna_wac_global",
         endpoint=LUNASERV_URL),
    dict(id="stewie.base.lroc_psr_south", name="LROC PSR south (Lunaserv)",
         provider="wms", uri=_wms_uri(LUNASERV_URL, "luna_nac_pole_psr_south", "EPSG:4326"),
         relabel="IAU_2015:30100", probe="context", add_when_blank=True,
         source="LROC Lunaserv WMS (wms.im-ldi.com) layer luna_nac_pole_psr_south "
                "(permanently-shadowed-region overlay; sparse by nature)",
         endpoint=LUNASERV_URL),
    dict(id="stewie.base.stewie_ogc_dem", name="STEWIE /ogc dem drape (live backend)",
         provider="wms", uri=_wms_uri(STEWIE_OGC_URL, "dem", "IAU_2015:30100"),
         relabel=None, probe="ogc_own", add_when_blank=True,
         source="STEWIE FastAPI backend WMS 1.3.0 /ogc/wms (live globe drape, IAU_2015:30100)",
         endpoint=STEWIE_OGC_URL),
    # Attempted + DEFERRED (recorded, not added to the project): tile-matrix / no-caps.
    dict(id="stewie.base.moon_trek_wac", name="Moon Trek WMTS (LRO WAC global)",
         provider="wms",
         uri=("contextualWMSLegend=0&crs=EPSG:104903&dpiMode=7&format=image/jpeg"
              "&layers=LRO_WAC_Mosaic_Global_303ppd_v02&styles=default"
              "&tileMatrixSet=default028mm&url=https://trek.nasa.gov/tiles/Moon/EQ/"
              "LRO_WAC_Mosaic_Global_303ppd_v02/1.0.0/WMTSCapabilities.xml"),
         relabel="IAU_2015:30100", probe="context", add_when_blank=False,
         source="NASA Solar System Treks WMTS (trek.nasa.gov), EQ WAC mosaic",
         endpoint="https://trek.nasa.gov/tiles/Moon/EQ/LRO_WAC_Mosaic_Global_303ppd_v02/1.0.0/WMTSCapabilities.xml"),
]

# ---------------------------------------------------------------------------
# Gate 5: the FULL ARTEMIS_LAYERS.md row catalog -> {loaded | deferred}. Every row
# is present; deferred rows carry a real reason + the URL. Importable (no QGIS).
# disposition: "loaded" rows name the qgis layer/group they live in; "deferred"
# rows name why + where. Runtime render evidence (gate 6) is separate (status json).
# ---------------------------------------------------------------------------
ARTEMIS_ROWS = [
    # Path A -- mercator/globe + OGC raster services
    dict(row="A/OPM Moon basemap", disposition="deferred",
         reason="Web-Mercator XYZ basemap; smears/dies below ~85S and is superseded at "
                "the pole by the polar-native LROC NAC/WAC context drapes loaded here.",
         url="https://openplanetary.org (opm-moon-basemap-v0-1)"),
    dict(row="A/Moon Trek WMTS", disposition="deferred",
         reason="WMTS tile-matrix SupportedCRS=EPSG:104903 does not resolve in QGIS 3.22 "
                "bundled PROJ (only IAU_2015:* + EPSG:* resolve) -> tiles cannot be "
                "georeferenced; render-probe blank. Revisit on a QGIS/PROJ build carrying "
                "the EPSG:104903 (or an IAU_2015 equirectangular) tile-matrix mapping.",
         url="https://trek.nasa.gov/tiles/apidoc/trekAPI.html?body=moon"),
    dict(row="A/LROC Lunaserv WMS", disposition="loaded",
         layer="stewie.base.lroc_wac_global + stewie.base.lroc_nac_sp + stewie.base.lroc_psr_south",
         note="catalogued URL wms.lroc.asu.edu/lroc is an HTML viewer that 301-redirects to "
              "the live WMS host wms.im-ldi.com (used here)."),
    dict(row="A/QuickMap WMTS", disposition="deferred",
         reason="quickmap.lroc.im-ldi.com serves a proprietary single-page app, not a public "
                "OGC WMTS; the catalogued caps/tile paths return the app shell HTML, no "
                "parseable WMTSCapabilities. No open OGC endpoint to wire.",
         url="https://quickmap.lroc.im-ldi.com/"),
    # Path B -- polar-stereo DEMs + NAC drape
    dict(row="B/Haworth SfS 1 m DEM", disposition="loaded",
         layer="stewie.terrain.haworth.dem (core)"),
    dict(row="B/8x Artemis site DEMs (PGDA Product 78, 5 m)", disposition="loaded",
         layer="stewie.terrain.<site>.dem x8 (core)"),
    dict(row="B/LOLA 5 m polar", disposition="loaded",
         layer="== the 8 site DEMs (PGDA Product 78, 5 m/px polar-stereo)"),
    dict(row="B/LOLA LDEM 75S continuous south-polar basemap (120 m)", disposition="loaded",
         layer="stewie.base.south_polar_basemap (LDEM_75S_120M hillshade COG, 75-90S, "
               "bottom of the layer tree - continuous context under the site DEMs)"),
    dict(row="B/LOLA 20 m polar", disposition="deferred",
         reason="broader-area 20 m context tiles not downloaded (the 5 m site DEMs carry the "
                "mission zone); additive fetch when wider-area context is needed.",
         url="https://pgda.gsfc.nasa.gov/products/78"),
    dict(row="B/LROC NAC South Pole mosaic (imagery drape)", disposition="loaded",
         layer="stewie.base.lroc_nac_sp",
         note="catalogued URL data.lroc.im-ldi.com/lroc/view_rdr/NAC_POLE_SOUTH is an HTML "
              "browse viewer, not a raster service; the same mosaic is served as a WMS layer "
              "(luna_nac_2m_sp_mosaic) via Lunaserv and renders 0.68 over Site01."),
    # Path C -- vectors
    dict(row="C/Artemis III LOLA-5m site pins (8)", disposition="loaded",
         layer="stewie.vector.sites.pins (artemis_sites.geojson points, DEM centres)"),
    dict(row="C/Artemis III site footprints (8)", disposition="loaded",
         layer="stewie.vector.sites.footprints (artemis_sites.geojson polygons, DEM bbox)"),
    dict(row="C/Artemis III candidate regions (13 polygons)", disposition="deferred",
         reason="USGS ScienceBase item 671a6fa8 did not resolve to a downloadable "
                "shapefile/GeoJSON this run (item + keyword search returned no attached "
                "vector product); additive load into lunar_south_pole.gpkg when the item "
                "resolves. Non-blocking per plan.",
         url="https://www.sciencebase.gov/catalog/item/671a6fa8"),
    dict(row="C/PSR outlines (LROC PSR Atlas vector >=10 km2)", disposition="deferred",
         reason="vector outlines from the LROC PSR Atlas not fetched as GeoJSON; the PSR "
                "extent is loaded as a raster proxy (stewie.base.lroc_psr_south, Lunaserv) "
                "for context. Vector outlines are an additive gpkg load.",
         url="https://quickmap.lroc.im-ldi.com/ (PSR Atlas layer)"),
    dict(row="C/Illumination % (PDS r32)", disposition="deferred",
         reason="PDS polar-illumination product (r32) not downloaded this run (large PDS "
                "delivery; additive fetch into lunar_south_pole.gpkg).",
         url="https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/ (illumination r32)"),
    dict(row="C/LPI South Pole Atlas reference products", disposition="deferred",
         reason="lpi.usra.edu returns 403 to automated agents; products are mirrored via "
                "QuickMap/USGS (also deferred above). Reference-only, not a wireable service.",
         url="https://www.lpi.usra.edu/lunar/lunar-south-pole-atlas/"),
    # STEWIE live backend service (plan P1.3)
    dict(row="STEWIE /ogc WMS (live backend)", disposition="loaded",
         layer="stewie.base.stewie_ogc_dem",
         note="live WMS connection added; the server returns a real non-blank GetMap tile "
              "(curl-verified 56%), but the QGIS 3.22 client culls the in-canvas GetMap "
              "(only GetCapabilities sent) because ogc.py advertises no per-CRS <BoundingBox>/"
              "no polar-stereo CRS -> in-canvas render DEFERRED pending the P2.0 ogc.py caps "
              "extension (advertise IAU_2015:30135 + native BoundingBox), which is backend "
              "scope outside gis/."),
]


def artemis_gate5_ok():
    """Gate-5 self-check (importable, no QGIS): every row is loaded or deferred-with-reason."""
    bad = []
    for r in ARTEMIS_ROWS:
        d = r.get("disposition")
        if d == "loaded" and not r.get("layer"):
            bad.append((r["row"], "loaded but no layer named"))
        elif d == "deferred" and not (r.get("reason") and r.get("url")):
            bad.append((r["row"], "deferred but missing reason/url"))
        elif d not in ("loaded", "deferred"):
            bad.append((r["row"], f"bad disposition {d!r}"))
    return bad


def _write_layer_status_md(path, status):
    """Render LAYER_STATUS.md from ARTEMIS_ROWS (gate 5) + runtime probes (gate 6)."""
    L = []
    L.append("# STEWIE lunar QGIS project - layer status (`gis/`)\n")
    L.append(f"Generated by `build_project.py` on **{status['date']}** "
             f"(QGIS {status['qgis_version']}). Machine-readable: `layer_status.json`.\n")
    L.append("Authoritative measurement stays on the `IAU_2015:30135` LOLA/USGS COGs "
             "(and `IAU_2015:30100` site vectors). External NASA/STEWIE services are "
             "CONTEXT (non-authoritative frame).\n")
    L.append("## Gate 5 - every ARTEMIS_LAYERS row is loaded or deferred\n")
    L.append(f"Gate 5 self-check: **{'PASS' if status['gate5_ok'] else 'FAIL'}** "
             f"({len(status['gate5_artemis_rows'])} rows).\n")
    L.append("| ARTEMIS row | status | layer / reason | note / URL |")
    L.append("|---|---|---|---|")
    for r in status["gate5_artemis_rows"]:
        if r["disposition"] == "loaded":
            mid = r.get("layer", "")
            right = r.get("note", "")
            tag = "LOADED"
        else:
            mid = r.get("reason", "")
            right = r.get("url", "")
            tag = "DEFERRED"
        mid = mid.replace("|", "/")
        right = right.replace("|", "/")
        L.append(f"| {r['row']} | {tag} | {mid} | {right} |")
    L.append("\n## Gate 6 - external service render probes (real fetched tiles)\n")
    L.append("| service | endpoint | valid | render_frac | status | added |")
    L.append("|---|---|---|---|---|---|")
    for s in status["gate6_external_services"]:
        extra = ""
        if "server_tile_frac" in s:
            extra = f" (server tile {s['server_tile_frac']})"
        L.append(f"| {s['name']} | {s['endpoint']} | {s['valid']} | "
                 f"{s['render_frac']}{extra} | {s['status']} | {s['added']} |")
    L.append(f"\nCounts: {status['counts']['authoritative_rasters']} authoritative rasters, "
             f"{status['counts']['vectors']} vector layers, "
             f"{status['counts']['external_added']} external context layers added, "
             f"{status['counts']['total_layers']} layers total.\n")
    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")


def great_circle_m(lon1: float, lat1: float, lon2: float, lat2: float, radius: float = MOON_R) -> float:
    """True ground distance (m) between two selenographic points on the Moon sphere."""
    import math
    p1, l1, p2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    d = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2
    return radius * 2 * math.asin(math.sqrt(d))


def polar_stereo_scale_bound(lat_deg: float) -> float:
    """Point-scale exaggeration (k - 1) of polar stereographic (k0=1 at pole) at |lat|."""
    import math
    return 2.0 / (1.0 + math.sin(math.radians(abs(lat_deg)))) - 1.0


def inject_3d_views(qgz_path: str, mapviewdocks_xml: str) -> None:
    """Insert the ``<mapViewDocks3D>`` element (the P1.7 3D local scenes) into the
    already-written ``.qgz``, as the last child of the root ``<qgis>`` element.

    QGIS 3.22's PyQGIS cannot persist a 3D view headlessly (no ``viewsManager()``;
    ``Qgs3DMapSettings.writeXml`` segfaults here), so the view XML -- authored to the
    exact QGIS ``release-3_22`` schema in ``scene3d`` -- is spliced into the project
    XML. Reads/rewrites the zip preserving every member (e.g. the ``.qgd`` auxiliary
    store) so nothing else is disturbed.
    """
    with zipfile.ZipFile(qgz_path, "r") as zin:
        order = zin.namelist()
        members = {n: zin.read(n) for n in order}
    qgs_name = next((n for n in order if n.endswith(".qgs")), None)
    if qgs_name is None:
        raise RuntimeError(f"no .qgs member inside {qgz_path}")
    text = members[qgs_name].decode("utf-8")
    idx = text.rfind("</qgis>")
    if idx == -1:
        raise RuntimeError(f"no </qgis> root close in {qgs_name}")
    members[qgs_name] = (text[:idx] + mapviewdocks_xml + text[idx:]).encode("utf-8")
    tmp = qgz_path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in order:
            zout.writestr(n, members[n])
    os.replace(tmp, qgz_path)


# ---------------------------------------------------------------------------
# Build.
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=_dt.date.today().isoformat(),
                    help="ISO date stamped into layer provenance (default: today).")
    ap.add_argument("--data-root", default=DEFAULT_DATA_ROOT,
                    help="Root of the GIS data store (default: %(default)s).")
    ap.add_argument("--output", default=DEFAULT_OUTPUT,
                    help="Output .qgz path (default: %(default)s).")
    ap.add_argument("--no-proof", action="store_true",
                    help="Skip writing the Gate-1 proof PNGs.")
    ap.add_argument("--no-3d", action="store_true",
                    help="Skip persisting the P1.7 3D local scenes into the .qgz.")
    args = ap.parse_args(argv)

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from qgis.core import (
        Qgis, QgsApplication, QgsColorRampShader, QgsContrastEnhancement,
        QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsLayerMetadata,
        QgsMapSettings, QgsProject, QgsRasterBandStats, QgsRasterLayer,
        QgsRasterShader, QgsSingleBandGrayRenderer,
        QgsSingleBandPseudoColorRenderer,
    )
    from qgis.core import (
        QgsMapRendererParallelJob, QgsRectangle, QgsPointXY, QgsVectorLayer,
        QgsMarkerSymbol, QgsFillSymbol, QgsSingleSymbolRenderer,
        QgsPalLayerSettings, QgsTextFormat, QgsTextBufferSettings,
        QgsVectorLayerSimpleLabeling, QgsSettings,
    )
    from qgis.core import (
        QgsPrintLayout, QgsLayoutItemPage, QgsLayoutItemMap, QgsLayoutItemLabel,
        QgsLayoutItemLegend, QgsLayoutItemScaleBar, QgsLayoutItemPicture,
        QgsLayoutPoint, QgsLayoutSize, QgsUnitTypes,
    )
    from qgis.PyQt.QtCore import QSize
    from qgis.PyQt.QtGui import QColor, QFont
    import json as _json

    # Bound network waits so an unreachable service cannot stall the build.
    _qs = QgsSettings()
    _qs.setValue("qgis/networkAndProxy/networkTimeout", 15000)

    QgsApplication.setPrefixPath("/usr", True)
    qgs = QgsApplication([], False)
    qgs.initQgis()

    # Processing framework (for gdal:hillshade).
    sys.path.append("/usr/share/qgis/python/plugins")
    import processing  # noqa: E402
    from processing.core.Processing import Processing  # noqa: E402
    Processing.initialize()

    crs = QgsCoordinateReferenceSystem(PROJ_CRS)
    geo = QgsCoordinateReferenceSystem(GEO_CRS)
    if not crs.isValid():
        print(f"FATAL: {PROJ_CRS} did not resolve in this QGIS PROJ db.", file=sys.stderr)
        return 2

    data_root = os.path.abspath(args.data_root)
    hillshade_dir = os.path.join(data_root, "derived", "hillshade")
    os.makedirs(hillshade_dir, exist_ok=True)

    # ---- fresh project, selenographic frame -------------------------------
    project = QgsProject.instance()
    project.clear()
    project.setCrs(crs)
    project.setEllipsoid(MOON_ELLIPSOID)   # measurement sphere -> never WGS84
    project.setTitle("STEWIE shared core - lunar south pole (IAU_2015:30135)")

    # No-Earth-claim discipline (MA-01): declare the selenographic frame explicitly.
    pmd = project.metadata()
    pmd.setTitle("STEWIE shared core - lunar south pole")
    pmd.setAbstract(
        "Selenographic frame only. Project CRS IAU_2015:30135 (Moon 2015 South "
        "Polar Stereographic, sphere R=1737400 m); geographic reference "
        "IAU_2015:30100. No terrestrial datum is used or implied; every layer "
        "carries the lunar polar-stereo CRS. Layers: Artemis III candidate-site "
        "LOLA 5 m DEM/slope COGs + Haworth 1 m SfS DEM, per-DEM hillshade in the "
        f"polar-stereo frame. Built {args.date}.")
    project.setMetadata(pmd)

    # Store data paths relative to the .qgz (portable when code/ + data/ stay siblings).
    try:
        project.setFilePathStorage(Qgis.FilePathType.Relative)
    except (AttributeError, TypeError):
        project.writeEntryBool("Paths", "/Absolute", False)

    root = project.layerTreeRoot()

    def set_provenance(layer, ident, title, source, command=None):
        md = QgsLayerMetadata()
        md.setIdentifier(ident)
        md.setTitle(title)
        md.setCrs(crs)
        abstract = (f"source_file={layer.source()}; provenance={source}; "
                    f"loaded={args.date}; frame=selenographic IAU_2015:30135 "
                    f"(no terrestrial datum).")
        md.setAbstract(abstract)
        md.addHistoryItem(f"{args.date}: loaded into stewie_south_pole.qgz from {layer.source()}")
        if command:
            md.addHistoryItem(f"{args.date}: generated via `{command}`")
        layer.setMetadata(md)
        layer.setAbstract(abstract)

    def style_dem(layer):
        st = layer.dataProvider().bandStatistics(
            1, QgsRasterBandStats.Min | QgsRasterBandStats.Max)
        mn, mx = st.minimumValue, st.maximumValue
        rng = (mx - mn) or 1.0
        ramp = QgsColorRampShader(mn, mx)
        ramp.setColorRampType(QgsColorRampShader.Interpolated)
        items = [QgsColorRampShader.ColorRampItem(
            mn + f * rng, QColor(r, g, b), f"{mn + f * rng:.0f} m")
            for (f, r, g, b) in HYPSO_STOPS]
        ramp.setColorRampItemList(items)
        shader = QgsRasterShader()
        shader.setRasterShaderFunction(ramp)
        rnd = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
        rnd.setClassificationMin(mn)
        rnd.setClassificationMax(mx)
        layer.setRenderer(rnd)
        layer.setOpacity(0.60)   # let the hillshade below read through
        return mn, mx

    def style_slope(layer):
        ramp = QgsColorRampShader(0.0, SLOPE_CLASSES[-2][0])
        ramp.setColorRampType(QgsColorRampShader.Discrete)
        items = [QgsColorRampShader.ColorRampItem(
            ub, QColor(r, g, b, a), label)
            for (ub, r, g, b, a, label) in SLOPE_CLASSES]
        ramp.setColorRampItemList(items)
        shader = QgsRasterShader()
        shader.setRasterShaderFunction(ramp)
        rnd = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
        layer.setRenderer(rnd)

    def style_hillshade(layer):
        rnd = QgsSingleBandGrayRenderer(layer.dataProvider(), 1)
        ce = QgsContrastEnhancement(layer.dataProvider().dataType(1))
        ce.setContrastEnhancementAlgorithm(QgsContrastEnhancement.StretchToMinimumMaximum)
        ce.setMinimumValue(0.0)
        ce.setMaximumValue(255.0)
        rnd.setContrastEnhancement(ce)
        layer.setRenderer(rnd)

    def make_hillshade(dem_path, out_path):
        if os.path.exists(out_path):
            os.remove(out_path)
        processing.run("gdal:hillshade", {
            "INPUT": dem_path, "BAND": 1, "Z_FACTOR": HS_ZFACTOR, "SCALE": 1.0,
            "AZIMUTH": HS_AZIMUTH, "ALTITUDE": HS_ALTITUDE,
            "COMPUTE_EDGES": True, "OUTPUT": out_path})
        return (f"gdaldem hillshade -az {HS_AZIMUTH:g} -alt {HS_ALTITUDE:g} "
                f"-z {HS_ZFACTOR:g} -compute_edges {os.path.basename(dem_path)} "
                f"{os.path.basename(out_path)}")

    def add_grouped(group, layer):
        # insertLayer(0, ...) puts each new layer on TOP of the group; calling in
        # order hillshade -> dem -> slope yields final order slope/dem/hillshade.
        project.addMapLayer(layer, addToLegend=False)
        group.insertLayer(0, layer)

    def load_raster(path, name):
        lyr = QgsRasterLayer(path, name, "gdal")
        if not lyr.isValid():
            raise RuntimeError(f"failed to load raster: {path}")
        # The COGs carry an "unnamed" polar-stereo WKT (params byte-identical to
        # IAU_2015:30135, verified: +proj=stere +lat_0=-90 +R=1737400). Relabel it
        # with the authority code so authid() is legible/assertable (MA-01) - this
        # is a label assignment, NOT a reprojection.
        lyr.setCrs(crs)
        return lyr

    print(f"[build] project CRS={PROJ_CRS} ellipsoid={project.ellipsoid()} date={args.date}")
    site_extents = {}
    site_stats = {}   # site -> (dem_min, dem_max) for the vector properties (P1.4)
    site_layer_ids = {}   # site -> {dem,hillshade,slope} layer ids for the 3D scenes (P1.7)

    # P1.5: the authoritative terrain COGs live under one catalog parent group; the
    # per-site groups (unchanged) nest inside it. Sibling GRP_BASE / GRP_VECTORS
    # parents are created lower so they end up above terrain in the tree.
    terrain_parent = root.insertGroup(0, GRP_TERRAIN)

    for site in SITES:
        dem_path = os.path.join(data_root, "cog", site, "dem.tif")
        slope_path = os.path.join(data_root, "cog", site, "slope.tif")
        hs_path = os.path.join(hillshade_dir, f"{site}_hillshade.tif")
        for p in (dem_path, slope_path):
            if not os.path.exists(p):
                print(f"FATAL: missing COG {p}", file=sys.stderr)
                return 2

        grp = terrain_parent.insertGroup(0, site)   # top within terrain; last site on top
        hs_cmd = make_hillshade(dem_path, hs_path)

        dem = load_raster(dem_path, f"{site} DEM")
        mn, mx = style_dem(dem)
        set_provenance(dem, f"stewie.terrain.{site.lower()}.dem",
                       f"{site} LOLA 5 m DEM", SRC_SITE_DEM)

        hs = load_raster(hs_path, f"{site} Hillshade")
        style_hillshade(hs)
        set_provenance(hs, f"stewie.terrain.{site.lower()}.hillshade",
                       f"{site} hillshade", SRC_SITE_DEM, command=hs_cmd)

        slope = load_raster(slope_path, f"{site} Slope")
        style_slope(slope)
        set_provenance(slope, f"stewie.terrain.{site.lower()}.slope",
                       f"{site} slope (deg)", SRC_SITE_SLOPE)

        add_grouped(grp, hs)
        add_grouped(grp, dem)
        add_grouped(grp, slope)
        site_extents[site] = dem.extent()
        site_stats[site] = (mn, mx)
        site_layer_ids[site] = {"dem": dem.id(), "hillshade": hs.id(), "slope": slope.id()}
        print(f"[build] {site}: DEM min={mn:.1f} max={mx:.1f} m; hillshade+slope grouped")

    # ---- Haworth (DEM only) ----------------------------------------------
    haw_dem_path = os.path.join(data_root, "cog", HAWORTH)
    if os.path.exists(haw_dem_path):
        haw_hs_path = os.path.join(hillshade_dir, "Haworth_hillshade.tif")
        grp = terrain_parent.insertGroup(0, "Haworth 1 m")
        hs_cmd = make_hillshade(haw_dem_path, haw_hs_path)
        dem = load_raster(haw_dem_path, "Haworth DEM (1 m)")
        mn, mx = style_dem(dem)
        set_provenance(dem, "stewie.terrain.haworth.dem", "Haworth 1 m SfS DEM",
                       SRC_HAWORTH_DEM)
        hs = load_raster(haw_hs_path, "Haworth Hillshade")
        style_hillshade(hs)
        set_provenance(hs, "stewie.terrain.haworth.hillshade", "Haworth hillshade",
                       SRC_HAWORTH_DEM, command=hs_cmd)
        add_grouped(grp, hs)
        add_grouped(grp, dem)
        print(f"[build] Haworth: DEM min={mn:.1f} max={mx:.1f} m; hillshade grouped")
    else:
        print(f"WARNING: Haworth DEM missing at {haw_dem_path}; skipped", file=sys.stderr)

    # ======================================================================
    # P1.4 -- site vectors derived from the real COG extents (network-free).
    # ======================================================================
    ct_135_100 = QgsCoordinateTransform(crs, geo, project.transformContext())
    ct_100_135 = QgsCoordinateTransform(geo, crs, project.transformContext())

    def _ring_30100(ext, n=25):
        """Densified footprint ring (30135 rectangle -> 30100 lon/lat), n pts/edge.
        Densification is required near the pole: a straight edge in the metric polar
        frame is a strongly-curved arc in lon/lat, so a 4-corner polygon would be
        geometrically wrong. 25 pts/edge keeps the footprint faithful either frame."""
        xmin, xmax = ext.xMinimum(), ext.xMaximum()
        ymin, ymax = ext.yMinimum(), ext.yMaximum()
        corners = [(xmin, ymax), (xmax, ymax), (xmax, ymin), (xmin, ymin)]  # UL UR LR LL
        ring = []
        for i in range(4):
            x0, y0 = corners[i]
            x1, y1 = corners[(i + 1) % 4]
            for k in range(n):
                t = k / n
                p = ct_135_100.transform(QgsPointXY(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
                ring.append([round(p.x(), 8), round(p.y(), 8)])
        ring.append(ring[0])
        return ring

    vectors_path = os.path.join(data_root, "vectors", "artemis_sites.geojson")
    os.makedirs(os.path.dirname(vectors_path), exist_ok=True)
    features = []
    for site in SITES:
        ext = site_extents[site]
        mn, mx = site_stats[site]
        cx = (ext.xMinimum() + ext.xMaximum()) / 2.0
        cy = (ext.yMinimum() + ext.yMaximum()) / 2.0
        c = ct_135_100.transform(QgsPointXY(cx, cy))
        w_m, h_m = ext.width(), ext.height()
        props_common = {
            "site": site,
            # DISPLAY-ONLY region name (additive; "site" stays the stable SiteNN key).
            "name": SITE_NAMES.get(site, site),
            "label": SITE_NAMES.get(site, site),
            "dem_min_m": round(mn, 2), "dem_max_m": round(mx, 2),
            "center_lon": round(c.x(), 6), "center_lat": round(c.y(), 6),
            "extent_m": [round(ext.xMinimum(), 1), round(ext.yMinimum(), 1),
                         round(ext.xMaximum(), 1), round(ext.yMaximum(), 1)],
            "width_m": round(w_m, 1), "height_m": round(h_m, 1),
            "area_km2": round(w_m * h_m / 1.0e6, 2),
            "source": "PGDA Product 78 LOLA 5 m DEM extent (gdalinfo), reprojected 30135->30100",
        }
        features.append({"type": "Feature",
                         "geometry": {"type": "Point", "coordinates": [round(c.x(), 8), round(c.y(), 8)]},
                         "properties": dict(props_common, kind="pin")})
        features.append({"type": "Feature",
                         "geometry": {"type": "Polygon", "coordinates": [_ring_30100(ext)]},
                         "properties": dict(props_common, kind="footprint")})
    geojson = {
        "type": "FeatureCollection",
        "name": "artemis_sites",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:IAU_2015::30100"}},
        "note": ("Selenographic lon/lat (IAU_2015:30100, Moon 2015 sphere R=1737400 m). "
                 "NOT WGS84/Earth. Derived from the LOLA/USGS COG extents; one pin at each "
                 "DEM centre + a densified footprint polygon per site. site ids match the "
                 "STEWIE backend naming for round-trip."),
        "features": features,
    }
    with open(vectors_path, "w") as fh:
        _json.dump(geojson, fh, indent=1)
    print(f"[build] P1.4 wrote {vectors_path} "
          f"({len(SITES)} pins + {len(SITES)} footprints, IAU_2015:30100)")

    # Load the ONE geojson as two styled layers (OGR geometrytype filter).
    def _vec_provenance(layer, ident, title, src):
        md = QgsLayerMetadata()
        md.setIdentifier(ident)
        md.setTitle(title)
        md.setCrs(geo)
        md.setAbstract(f"source_file={layer.source()}; provenance={src}; loaded={args.date}; "
                       f"frame=selenographic IAU_2015:30100 (no terrestrial datum).")
        md.addHistoryItem(f"{args.date}: derived from LOLA/USGS COG extents; reprojected 30135->30100")
        layer.setMetadata(md)

    vec_group = root.insertGroup(0, GRP_VECTORS)

    footprints = QgsVectorLayer(f"{vectors_path}|geometrytype=Polygon",
                                "Artemis site footprints", "ogr")
    if not footprints.isValid():
        print("FATAL: footprint vector layer invalid", file=sys.stderr)
        return 2
    footprints.setCrs(geo)   # relabel to lunar geographic (file is lunar lon/lat)
    fsym = QgsFillSymbol.createSimple({
        "color": f"{FOOTPRINT_RGB[0]},{FOOTPRINT_RGB[1]},{FOOTPRINT_RGB[2]},60",
        "outline_color": f"{FOOTPRINT_RGB[0]},{FOOTPRINT_RGB[1]},{FOOTPRINT_RGB[2]},255",
        "outline_width": "0.5"})
    footprints.setRenderer(QgsSingleSymbolRenderer(fsym))
    _vec_provenance(footprints, "stewie.vector.sites.footprints",
                    "Artemis site footprints (DEM bbox)",
                    "LOLA/USGS COG bounding boxes, densified, reprojected 30135->30100")
    project.addMapLayer(footprints, addToLegend=False)
    vec_group.insertLayer(0, footprints)

    pins = QgsVectorLayer(f"{vectors_path}|geometrytype=Point",
                          "Artemis site pins", "ogr")
    if not pins.isValid():
        print("FATAL: pin vector layer invalid", file=sys.stderr)
        return 2
    pins.setCrs(geo)
    psym = QgsMarkerSymbol.createSimple({
        "name": "star", "size": "4.5",
        "color": f"{PIN_RGB[0]},{PIN_RGB[1]},{PIN_RGB[2]},255",
        "outline_color": "20,20,20,255", "outline_width": "0.4"})
    pins.setRenderer(QgsSingleSymbolRenderer(psym))
    # Labels: the real Artemis III region name next to each pin (DISPLAY only; the
    # stable SiteNN key lives on in the "site" property + the "<Site> DEM" layer names).
    pal = QgsPalLayerSettings()
    pal.fieldName = "label"
    pal.enabled = True
    try:
        pal.placement = QgsPalLayerSettings.OverPoint
    except AttributeError:
        pass
    tf = QgsTextFormat()
    tf.setSize(11)
    tf.setColor(QColor(255, 255, 255))
    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(1.0)
    buf.setColor(QColor(0, 0, 0))
    tf.setBuffer(buf)
    pal.setFormat(tf)
    pins.setLabeling(QgsVectorLayerSimpleLabeling(pal))
    pins.setLabelsEnabled(True)
    _vec_provenance(pins, "stewie.vector.sites.pins",
                    "Artemis site pins (DEM centre)",
                    "LOLA/USGS COG centres, reprojected 30135->30100")
    project.addMapLayer(pins, addToLegend=False)
    vec_group.insertLayer(0, pins)   # pins render above footprints
    print(f"[build] P1.4 vectors added: pins(30100)={pins.crs().authid()} "
          f"footprints(30100)={footprints.crs().authid()}")

    # ======================================================================
    # P1.3 -- external imagery / OGC services (best-effort, render-probed).
    # ======================================================================
    RENDER_THRESH = 0.02
    context_ext = QgsRectangle(-3.0e5, -3.0e5, 3.0e5, 3.0e5)   # ~80-90 S polar context

    def _nonblank_frac(img, step=6):
        if img.isNull():
            return 0.0
        w, h = img.width(), img.height()
        nz = n = 0
        for y in range(0, h, step):
            for x in range(0, w, step):
                col = img.pixelColor(x, y)
                n += 1
                nz += (col.alpha() > 0 and (col.red() + col.green() + col.blue()) > 20)
        return round(nz / n, 4) if n else 0.0

    def _probe(layer, ext135, size=256):
        ms = QgsMapSettings()
        ms.setLayers([layer])
        ms.setDestinationCrs(crs)
        ms.setExtent(ext135)
        ms.setOutputSize(QSize(size, size))
        ms.setBackgroundColor(QColor(0, 0, 0))
        job = QgsMapRendererParallelJob(ms)
        job.start()
        job.waitForFinished()
        return _nonblank_frac(job.renderedImage())

    ext_results = []
    base_group = root.insertGroup(0, GRP_BASE)
    for spec in EXTERNAL_SERVICES:
        rec = {"id": spec["id"], "name": spec["name"], "endpoint": spec["endpoint"],
               "source": spec["source"], "valid": False, "render_frac": 0.0,
               "probe": spec["probe"], "added": False, "status": "unreachable",
               "wire_crs": spec["uri"].split("crs=")[1].split("&")[0]}
        try:
            lyr = QgsRasterLayer(spec["uri"], spec["name"], "wms")
            rec["valid"] = bool(lyr.isValid())
            if rec["valid"]:
                if spec["relabel"]:
                    lyr.setCrs(QgsCoordinateReferenceSystem(spec["relabel"]))
                    rec["layer_crs"] = lyr.crs().authid()
                if spec["probe"] == "site":
                    pext = site_extents["Site01"]
                elif spec["probe"] == "ogc_own":
                    pext = ct_100_135.transformBoundingBox(lyr.extent())
                else:
                    pext = context_ext
                rec["render_frac"] = _probe(lyr, pext)
        except Exception as exc:   # noqa: BLE001 -- record, never crash the build
            rec["status"] = f"error: {exc}"
            ext_results.append(rec)
            print(f"[build] P1.3 {spec['id']}: EXCEPTION {exc}")
            continue
        renders = rec["render_frac"] >= RENDER_THRESH
        if not rec["valid"]:
            rec["status"] = "invalid (endpoint unreachable / no caps)"
        elif renders:
            rec["status"] = "renders"
        else:
            rec["status"] = "valid-blank (in-canvas render culled/empty)"
        if rec["valid"] and (renders or spec["add_when_blank"]):
            md = QgsLayerMetadata()
            md.setIdentifier(spec["id"])
            md.setTitle(spec["name"])
            md.setAbstract(f"provenance={spec['source']}; endpoint={spec['endpoint']}; "
                           f"wire_crs={rec['wire_crs']}; relabelled_to="
                           f"{spec['relabel'] or '(native)'}; render_frac={rec['render_frac']}; "
                           f"status={rec['status']}; loaded={args.date}. External NASA/STEWIE "
                           f"service = CONTEXT, non-authoritative frame (authoritative measurement "
                           f"stays on the IAU_2015:30135 COGs).")
            lyr.setMetadata(md)
            lyr.setAbstract(md.abstract())
            project.addMapLayer(lyr, addToLegend=False)
            base_group.insertLayer(0, lyr)
            rec["added"] = True
        ext_results.append(rec)
        print(f"[build] P1.3 {spec['id']}: valid={rec['valid']} "
              f"render_frac={rec['render_frac']} -> {rec['status']} added={rec['added']}")

    # STEWIE /ogc: capture direct server-tile evidence (curl-equivalent) so gate 6 has a
    # real fetched tile for it even though the QGIS 3.22 client culls the in-canvas GetMap.
    try:
        import urllib.request as _u
        from qgis.PyQt.QtGui import QImage as _QImage
        o = next(r for r in ext_results if r["id"] == "stewie.base.stewie_ogc_dem")
        url = (STEWIE_OGC_URL + "?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=dem"
               "&CRS=EPSG:4326&BBOX=-86.551,-29.009,-86.112,-22.147"
               "&WIDTH=256&HEIGHT=256&FORMAT=image/png&STYLES=")
        data = _u.urlopen(url, timeout=12).read()
        qi = _QImage()
        qi.loadFromData(data)
        o["server_tile_frac"] = _nonblank_frac(qi)
        o["server_tile_note"] = ("server returns a real non-blank GetMap tile; QGIS 3.22 client "
                                 "culls the in-canvas GetMap (ogc.py caps advertise no per-CRS "
                                 "BoundingBox / no 30135) -> fix is P2.0 backend, outside gis/.")
        print(f"[build] P1.3 /ogc server-tile frac={o['server_tile_frac']} (client render culled)")
    except Exception as exc:   # noqa: BLE001
        for r in ext_results:
            if r["id"] == "stewie.base.stewie_ogc_dem":
                r["server_tile_note"] = f"server-tile check skipped: {exc}"

    # ======================================================================
    # Continuous south-polar basemap (LOLA LDEM hillshade COG). Placed at the
    # BOTTOM of the layer tree so the whole 75-90S region reads as one continuous
    # moon UNDER the authoritative site DEMs (Aaron: "whole moon ... dont load").
    # A local COG (the container has no serve-time egress); relabelled to 30135
    # exactly like the site COGs (label assignment, not a reprojection).
    # ======================================================================
    basemap_path = os.path.join(data_root, BASEMAP_SUBDIR)
    basemap_added = False
    if os.path.exists(basemap_path):
        basemap_group = root.addGroup(GRP_BASEMAP)   # appended -> bottom of the tree
        bm = load_raster(basemap_path, BASEMAP_NAME)
        style_hillshade(bm)                          # grayscale stretch (continuous relief)
        set_provenance(bm, "stewie.base.south_polar_basemap",
                       "South-polar LOLA LDEM hillshade basemap", SRC_BASEMAP,
                       command=BASEMAP_CMD)
        project.addMapLayer(bm, addToLegend=False)
        basemap_group.insertLayer(0, bm)
        basemap_added = True
        print(f"[build] basemap: '{BASEMAP_NAME}' at bottom of tree "
              f"({bm.crs().authid()}, {bm.width()}x{bm.height()}, "
              f"extent {bm.extent().toString(0)})")
    else:
        print(f"WARNING: basemap COG missing at {basemap_path}; skipped", file=sys.stderr)

    # ======================================================================
    # P1.5 -- catalog provenance + machine/human status artifacts.
    # ======================================================================
    pmd2 = project.metadata()
    kw = dict(pmd2.keywords())
    kw["catalog_groups"] = [GRP_BASE, GRP_TERRAIN, GRP_VECTORS, GRP_BASEMAP]
    kw["catalog_ids"] = ["stewie.base.*", "stewie.terrain.*", "stewie.vector.*"]
    pmd2.setKeywords(kw)
    project.setMetadata(pmd2)

    n_auth = len([1 for lyr in project.mapLayers().values()
                  if lyr.name().endswith(("DEM", "Slope", "Hillshade", "DEM (1 m)"))])
    n_ext_added = sum(1 for r in ext_results if r["added"])
    status = {
        "date": args.date,
        "qgis_version": Qgis.QGIS_VERSION,
        "project": os.path.abspath(args.output),
        "vectors_geojson": os.path.abspath(vectors_path),
        "gate5_artemis_rows": ARTEMIS_ROWS,
        "gate5_ok": (artemis_gate5_ok() == []),
        "gate6_external_services": ext_results,
        "counts": {
            "authoritative_rasters": n_auth,
            "vectors": 2,
            "external_added": n_ext_added,
            "total_layers": len(project.mapLayers()),
        },
        "scenes_3d": {
            "enabled": not args.no_3d,
            "sites": [s for s in scene3d.SITES_3D if s in site_layer_ids],
            "deferred": scene3d.SCENE3D_DEFERRED,
            "terrain": "DEM generator (per-site dem.tif) in IAU_2015:30135 local scene",
            "drape": "slope / DEM / hillshade (same stack as the 2D render)",
            "exaggeration": scene3d.DEFAULT_EXAGGERATION,
            "note": ("persisted as <mapViewDocks3D> in the .qgz (openable in QGIS "
                     "Desktop); PyQGIS 3.22 cannot writeXml 3D settings headlessly."),
        },
    }
    status_json = os.path.join(CODE_GIS_DIR, "layer_status.json")
    with open(status_json, "w") as fh:
        _json.dump(status, fh, indent=2)
    print(f"[build] P1.5 wrote {status_json} (gate5_ok={status['gate5_ok']}, "
          f"external_added={n_ext_added}/{len(EXTERNAL_SERVICES)})")

    _write_layer_status_md(os.path.join(CODE_GIS_DIR, "LAYER_STATUS.md"), status)
    print(f"[build] P1.5 wrote {os.path.join(CODE_GIS_DIR, 'LAYER_STATUS.md')}")

    # ======================================================================
    # P1 print layout ("Mission Map", A4 landscape) -- unblocks QWC2 GetPrint.
    # STRICTLY ADDITIVE: a QgsPrintLayout in the project's layout manager; it
    # touches no layer, style, CRS, or the layer tree. The map item id "map0"
    # is the prefix the QWC2 Print tool sends for the GetPrint map params
    # (map0:extent / map0:LAYERS / map0:scale), and TEMPLATE="Mission Map"
    # selects the layout. keepLayerSet is left False (the QGIS default) so the
    # map FOLLOWS the project's layers -- a direct GetPrint with no LAYERS param
    # still renders the real lunar map, and QWC2 overrides map0:LAYERS at print
    # time with the viewer's currently-visible layers. Metric scale bar (map
    # units are metres in IAU_2015:30135), north arrow (library SVG present in
    # both the host builder + the qgis-server container), auto-model legend, a
    # title, and a provenance/attribution label. Full-pole default extent.
    # ======================================================================
    LAYOUT_NAME = "Mission Map"
    MAP_ID = "map0"
    MAP_W_MM, MAP_H_MM = 200.0, 176.0   # map item size (mm) -> mirrored into themes.json print.map
    MM = QgsUnitTypes.LayoutMillimeters
    FULL_EXTENT = QgsRectangle(-457440.0, -457440.0, 457440.0, 457440.0)  # theme/basemap extent

    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName(LAYOUT_NAME)
    layout.pageCollection().page(0).setPageSize("A4", QgsLayoutItemPage.Landscape)  # 297 x 210 mm

    lmap = QgsLayoutItemMap(layout)
    lmap.setId(MAP_ID)
    lmap.setCrs(crs)
    lmap.setExtent(FULL_EXTENT)
    lmap.setBackgroundColor(QColor(0, 0, 0))       # black canvas, matching the viewers
    lmap.setFrameEnabled(True)
    layout.addLayoutItem(lmap)
    lmap.attemptMove(QgsLayoutPoint(8, 22, MM))
    lmap.attemptResize(QgsLayoutSize(MAP_W_MM, MAP_H_MM, MM))

    def _layout_label(text, x, y, w, h, pt, bold=False):
        it = QgsLayoutItemLabel(layout)
        it.setText(text)
        fnt = QFont()
        fnt.setPointSize(pt)
        fnt.setBold(bold)
        it.setFont(fnt)
        layout.addLayoutItem(it)
        it.attemptMove(QgsLayoutPoint(x, y, MM))
        it.attemptResize(QgsLayoutSize(w, h, MM))
        return it

    _layout_label("STEWIE - Lunar South Pole Mission Map", 8, 5, 200, 12, 20, bold=True)

    # Auto-model legend (reflects the project layer tree), linked to the map, fixed frame.
    legend = QgsLayoutItemLegend(layout)
    legend.setTitle("Legend")
    legend.setLinkedMap(lmap)
    legend.setAutoUpdateModel(True)
    legend.setResizeToContents(False)              # fixed frame; clips rather than overrunning the page
    legend.setFrameEnabled(True)
    layout.addLayoutItem(legend)
    legend.attemptMove(QgsLayoutPoint(212, 22, MM))
    legend.attemptResize(QgsLayoutSize(79, 176, MM))

    # Metric scale bar (map units = metres in IAU_2015:30135), linked to the map.
    sbar = QgsLayoutItemScaleBar(layout)
    sbar.setLinkedMap(lmap)
    sbar.setStyle("Single Box")
    sbar.setUnits(QgsUnitTypes.DistanceMeters)
    sbar.applyDefaultSize(QgsUnitTypes.DistanceMeters)
    sbar.setUnitLabel("m")
    layout.addLayoutItem(sbar)
    sbar.attemptMove(QgsLayoutPoint(12, 188, MM))

    # North arrow (QGIS library SVG; the same path resolves in host + container QGIS).
    north = QgsLayoutItemPicture(layout)
    north.setPicturePath("/usr/share/qgis/svg/arrows/NorthArrow_04.svg",
                         QgsLayoutItemPicture.FormatSVG)
    north.setLinkedMap(lmap)
    north.setNorthMode(QgsLayoutItemPicture.GridNorth)
    layout.addLayoutItem(north)
    north.attemptMove(QgsLayoutPoint(192, 26, MM))
    north.attemptResize(QgsLayoutSize(12, 12, MM))

    _layout_label(
        "Selenographic frame IAU_2015:30135 (Moon 2015 South Polar Stereographic, "
        "R=1737400 m); no terrestrial datum. Terrain: PGDA LOLA Product 78 5 m DEM/slope "
        "+ USGS Haworth 1 m SfS DEM + LOLA LDEM_75S_120M basemap. Context imagery: LROC "
        f"Lunaserv. STEWIE / McCardle & Storey. Built {args.date}.",
        8, 200, 200, 9, 7)

    project.layoutManager().addLayout(layout)
    print(f"[build] P1 print layout '{LAYOUT_NAME}' added "
          f"(map id={MAP_ID}, A4 landscape, map item {MAP_W_MM:g}x{MAP_H_MM:g} mm, "
          f"legend+scalebar+north+title+attribution)")

    # ---- write .qgz -------------------------------------------------------
    if os.path.exists(args.output):
        os.remove(args.output)
    if not project.write(args.output):
        print(f"FATAL: project.write failed for {args.output}", file=sys.stderr)
        return 2
    n_layers = len(project.mapLayers())
    print(f"[build] wrote {args.output} ({n_layers} layers)")

    # ---- P1.7 persist the 3D local scenes into the .qgz -------------------
    # DEM-based terrain + slope/DEM/hillshade drape per 3200^2 site, in the
    # projected IAU_2015:30135 CRS (a local scene -- the supported non-Earth 3D
    # path). Authored as exact QGIS 3.22 <mapViewDocks3D> XML and spliced in, since
    # PyQGIS here cannot persist a 3D view (Qgs3DMapSettings.writeXml segfaults; no
    # viewsManager() until 3.24). Openable in QGIS Desktop 3.22+ (Scene > the dock).
    if not args.no_3d:
        from qgis.PyQt.QtXml import QDomDocument as _QDom
        crs_inner = scene3d.crs_inner_xml(crs, _QDom)
        views_xml, scene_ids = [], []
        for site in scene3d.SITES_3D:
            ids = site_layer_ids.get(site)
            ext = site_extents.get(site)
            if not ids or ext is None:
                continue
            mn, mx = site_stats[site]
            cx = (ext.xMinimum() + ext.xMaximum()) / 2.0
            cy = (ext.yMinimum() + ext.yMaximum()) / 2.0
            mid_elev = (mn + mx) / 2.0
            drape = [ids["slope"], ids["dem"], ids["hillshade"]]   # top -> bottom
            views_xml.append(scene3d.build_view_xml(
                f"{site} 3D (local scene)", ids["dem"], drape,
                cx, cy, mid_elev, ext.width(), ext.height(), crs_inner))
            scene_ids.append(site)
        if views_xml:
            inject_3d_views(args.output, scene3d.build_mapviewdocks3d_xml(views_xml))
            print(f"[build] P1.7 persisted {len(views_xml)} 3D local scenes "
                  f"({', '.join(scene_ids)}) into {os.path.basename(args.output)}; "
                  f"exaggeration={scene3d.DEFAULT_EXAGGERATION:g}x, DEM terrain generator")

    # ---- Gate 1 proof renders --------------------------------------------
    if not args.no_proof:
        proof_dir = os.path.join(CODE_GIS_DIR, "proof")
        os.makedirs(proof_dir, exist_ok=True)

        def render_site(site, out_png, size=1400):
            ext = site_extents[site]
            # Top-to-bottom: slope (hazard overlay) / DEM / hillshade.
            names = [f"{site} Slope", f"{site} DEM", f"{site} Hillshade"]
            layers = []
            for nm in names:
                found = project.mapLayersByName(nm)
                if found:
                    layers.append(found[0])
            ms = QgsMapSettings()
            ms.setLayers(layers)
            ms.setDestinationCrs(crs)
            ms.setExtent(ext)
            ms.setOutputSize(QSize(size, size))
            ms.setBackgroundColor(QColor(0, 0, 0))
            job = QgsMapRendererParallelJob(ms)
            job.start()
            job.waitForFinished()
            img = job.renderedImage()
            img.save(out_png)
            return out_png

        for site in ("Site01", "Site04"):
            outp = os.path.join(proof_dir, f"{site.lower()}_render.png")
            render_site(site, outp)
            print(f"[proof] rendered {outp}")

        # P1.3/P1.4 proof: best available imagery drape (LROC NAC SP mosaic) +
        # Site01 hillshade + translucent DEM + site vectors (footprint + pin/label),
        # over Site01's extent, in the polar frame.
        def render_site01_with_imagery(out_png, size=1400):
            ext = site_extents["Site01"]
            names_top_to_bottom = ["Artemis site pins", "Artemis site footprints",
                                   "Site01 Slope", "Site01 DEM", "Site01 Hillshade",
                                   "LROC NAC South Pole mosaic (Lunaserv)"]
            layers = []
            for nm in names_top_to_bottom:
                found = project.mapLayersByName(nm)
                if found:
                    layers.append(found[0])
            ms = QgsMapSettings()
            ms.setLayers(layers)
            ms.setDestinationCrs(crs)
            ms.setExtent(ext)
            ms.setOutputSize(QSize(size, size))
            ms.setBackgroundColor(QColor(0, 0, 0))
            job = QgsMapRendererParallelJob(ms)
            job.start()
            job.waitForFinished()
            img = job.renderedImage()
            img.save(out_png)
            return out_png, _nonblank_frac(img)

        imagery_png = os.path.join(proof_dir, "site01_with_imagery.png")
        _, frac = render_site01_with_imagery(imagery_png)
        print(f"[proof] rendered {imagery_png} (non-black frac={frac})")

        # Whole-moon proof: the continuous LOLA basemap UNDER every site DEM +
        # hillshade + Haworth + the site pins/footprints, over the full 75-90S
        # extent. Shows the region is one continuous moon, not DEMs on black.
        def render_whole_moon(out_png, ext, size=1600):
            names_top_to_bottom = ["Artemis site pins", "Artemis site footprints"]
            for s in SITES:
                names_top_to_bottom += [f"{s} DEM", f"{s} Hillshade"]
            names_top_to_bottom += ["Haworth DEM (1 m)", "Haworth Hillshade", BASEMAP_NAME]
            layers = []
            for nm in names_top_to_bottom:
                found = project.mapLayersByName(nm)
                if found:
                    layers.append(found[0])
            ms = QgsMapSettings()
            ms.setLayers(layers)
            ms.setDestinationCrs(crs)
            ms.setExtent(ext)
            ms.setOutputSize(QSize(size, size))
            ms.setBackgroundColor(QColor(0, 0, 0))
            job = QgsMapRendererParallelJob(ms)
            job.start()
            job.waitForFinished()
            img = job.renderedImage()
            img.save(out_png)
            return out_png, _nonblank_frac(img)

        if basemap_added:
            bm_extent = project.mapLayersByName(BASEMAP_NAME)[0].extent()
            wm_png = os.path.join(proof_dir, "whole_moon.png")
            _, wmfrac = render_whole_moon(wm_png, bm_extent)
            print(f"[proof] rendered {wm_png} (non-black frac={wmfrac})")

    qgs.exitQgis()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
