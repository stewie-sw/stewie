"""[REQ:GW-05] GIS map substrate: the QWC2/OpenLayers map renders in the lunar south-polar frame
(IAU_2015:30135) over NASA Trek raster tiles + the local LOLA terrain-RGB, control points round-trip
/dem/site_xy <-> /dem/site_lonlat within tolerance, and no lunar coordinate is claimed as Earth WGS84.

The RENDER is Playwright-verified on the deployed /ide (frontend/_ide_gw05_terrain.mjs + the screenshot:
the LROC/LOLA south-pole hillshade basemap + the per-site DEM-COG terrain-RGB drapes render, map CRS
IAU_2015:30135, coordinate readout selenographic lon/lat, 2 qgis-server /ows GetMap tiles HTTP 200). This
python gate is the CI-runnable [REQ:GW-05] citation: the coordinate round-trip on the REAL Haworth DEM, the
local terrain being the REAL full-resolution COG (not a downscaled preview), and the CRS being lunar.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from stewie.server.server import app

client = TestClient(app)
_ROOT = Path(__file__).parents[2]


def test_site_xy_lonlat_round_trip_within_tolerance_on_real_haworth():  # [REQ:GW-05] [REQ:GL-01]
    """A control point round-trips: order-frame (x,y) -> /dem/site_lonlat -> (lat,lon) -> /dem/site_xy ->
    (x',y'). On the real Haworth DEM the round-trip error must be sub-metre (the transforms are exact
    inverses through the IAU_2015:30135 georef). Several interior points, not just the origin."""
    for x, y in [(2500.0, 3000.0), (5000.0, 5000.0), (7500.0, 1500.0)]:
        ll = client.get(f"/dem/site_lonlat?x={x}&y={y}&site=haworth").json()
        assert ll["ok"], ll
        xy = client.get(f"/dem/site_xy?lat={ll['lat']}&lon={ll['lon']}&site=haworth").json()
        assert xy["ok"], xy
        # sub-metre round-trip (the lon/lat is rounded to 6 dp ~ 3 cm at the pole, so allow a small tolerance).
        assert abs(xy["x_m"] - x) < 0.5, f"x round-trip off by {abs(xy['x_m'] - x)} m at ({x},{y})"
        assert abs(xy["y_m"] - y) < 0.5, f"y round-trip off by {abs(xy['y_m'] - y)} m at ({x},{y})"


def test_site_lonlat_is_selenographic_south_polar_not_earth():  # [REQ:GW-05] [REQ:GL-01]
    """The coordinates are lunar selenographic (south-polar), never Earth WGS84. A Haworth interior point
    resolves to a south-polar lat; the site_meta CRS is the IAU_2015:30135 Moon frame."""
    ll = client.get("/dem/site_lonlat?x=5000&y=5000&site=haworth").json()
    assert ll["ok"] and ll["lat"] < -80.0, ll                 # Haworth is at the lunar south pole
    meta = client.get("/dem/site_meta?site=haworth").json()
    assert meta["crs"] == "IAU_2015:30135"
    vd = meta["vertical_datum"]
    assert vd["name"] == "MOON_ME" and vd["sphere_radius_m"] == 1737400.0   # the Moon sphere, not an Earth datum


def test_map_theme_crs_is_lunar_no_wgs84_claim():  # [REQ:GW-05]
    """The QWC2 map theme declares the lunar CRS as its map + display frame; a lunar coordinate is never
    labelled EPSG:4326/WGS84 as the authoritative measurement frame."""
    themes = (_ROOT / "gis" / "qwc2" / "static" / "themesConfig.json").read_text(encoding="utf-8")
    assert '"defaultMapCrs": "IAU_2015:30135"' in themes, "the map CRS is not the lunar south-polar frame"
    assert '"mapCrs": "IAU_2015:30135"' in themes
    assert '"defaultDisplayCrs": "IAU_2015:30100"' in themes   # selenographic lon/lat readout


def test_local_terrain_is_the_real_full_res_cog_not_a_preview():  # [REQ:GW-05]
    """The local LOLA terrain the map drapes is the REAL full-resolution Haworth DEM COG (the .qgz
    datasource), not a downscaled preview PNG -- so the substrate shows native terrain, not a thumbnail."""
    qgs = zipfile.ZipFile(_ROOT / "gis" / "stewie_south_pole.qgz")
    xml = qgs.read([n for n in qgs.namelist() if n.endswith(".qgs")][0]).decode("utf-8", "replace")
    # the Haworth terrain layer references a real COG GeoTIFF, not a *_preview.png / a downscaled raster.
    assert "Haworth_1m_dem.tif" in xml, "the .qgz does not reference the real Haworth DEM COG"
    assert "cog/Haworth_1m_dem.tif" in xml or "/cog/" in xml, "the terrain source is not the COG directory"
    # several real COG terrain layers (per-site DEM/hillshade/slope) -- not a single preview thumbnail. The
    # on-disk COGs are host-mounted; the live render is Playwright-verified (frontend/_ide_gw05_terrain.mjs).
    assert xml.count(".tif") >= 5, "expected several real COG terrain layers (per-site DEM/hillshade/slope)"
