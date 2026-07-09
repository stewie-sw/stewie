"""Council #52 DERIVE KEEP-OUTS FROM HAZARD: auto-derive keep-out POLYGONS from the real terrain-hazard
NOGO mask over a site's framed work-area crop, as a GeoJSON FeatureCollection of Polygons in selenographic
lon/lat (OGC:CRS84). The hazard mask is the OR of the SAME FORGE costmap layers the planner routes on
(`lode.costmap_layers`), scoped to physical terrain barriers (slope / sinkage / tip-over / negative-obstacle)
and EXCLUDING the PSR-shadow veto + operator keepout + fleet reservation layers. Every vertex is a boundary
of the real NOGO mask on the real LOLA Haworth DEM -- no synthetic geometry.

These are the backend + geometry-correctness invariants: a NOGO (hazardous) cell centre falls INSIDE a
derived polygon; a clear cell falls OUTSIDE; and the public GET /world/keepouts-from-hazard returns valid
GeoJSON in the site's lon/lat footprint. The Mission-Plan panel's client-side wiring (adding the derived
polygons to the current mission keep-outs so the planner routes around them + they render like drawn
keep-outs) is verified LIVE via Playwright by the main thread + node-tested in hazardKeepouts.test.js.

Run: PYTHONPATH=. <venv>/bin/python -m pytest stewie/server/test_hazard_keepouts.py -q
"""
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pyproj import Transformer

from lode import mission_planner as mp
from stewie.server import gis_layers as GL
from stewie.server.server import app

SITE = "haworth"   # the canonical bundled work site (samples/lunar_dem/haworth_10km_5m); always imported


def _ring_contains(ring, px, py):
    """Even-odd point-in-ring test; ``ring`` = list of [x, y] (closed or open)."""
    n = len(ring)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _poly_contains(coords, px, py):
    """A GeoJSON Polygon (exterior + holes) contains (px, py): inside the exterior, outside every hole."""
    if not _ring_contains(coords[0], px, py):
        return False
    return not any(_ring_contains(hole, px, py) for hole in coords[1:])


def _fc_contains(fc, px, py):
    return any(_poly_contains(f["geometry"]["coordinates"], px, py) for f in fc["features"])


@pytest.fixture(scope="module")
def real_derivation():
    """The derived hazard keep-outs on the REAL Haworth crop + the SAME NOGO mask + geo mapping the
    producer uses, so the geometry invariants are checked against the identical source data."""
    fc = GL.hazard_keepouts_geojson(SITE)
    dem, (r0, c0), cell_m = GL._work_area(mp, mp.bundle_for_site(SITE))
    demf = np.asarray(dem, dtype=float)
    nogo, _per = GL._hazard_nogo_mask(demf, cell_m)
    dem_full, _cm, b, _fwd, tile_crs = GL._tile_geo(mp, mp.bundle_for_site(SITE))
    Hf, Wf = np.asarray(dem_full).shape
    H, W = demf.shape
    x0, y0, x1, y1 = b["x0"], b["y0"], b["x1"], b["y1"]
    xs = x0 + (x1 - x0) * (c0 + np.arange(W)) / max(1, Wf - 1)
    ys = y1 - (y1 - y0) * (r0 + np.arange(H)) / max(1, Hf - 1)
    inv = Transformer.from_crs(tile_crs, tile_crs.geodetic_crs, always_xy=True)
    return fc, nogo, xs, ys, inv


def test_haworth_derives_real_hazard_keepout_polygons(real_derivation):  # council #52
    """The real Haworth crop carries physical terrain hazard, so the derivation yields >=1 keep-out
    Polygon, each a valid closed GeoJSON ring whose vertices land in the real Haworth lon/lat footprint."""
    fc, nogo, _xs, _ys, _inv = real_derivation
    assert fc["type"] == "FeatureCollection"
    props = fc["properties"]
    # the mask is real terrain hazard (a genuine fraction of the crop), not empty and not everything
    assert 0.0 < props["nogo_fraction"] < 1.0
    assert props["n_features"] >= 1, "haworth's real hazard terrain must derive at least one keep-out"
    bbox = GL.geographic_bbox(SITE)
    pad = 0.5   # a small lon/lat pad: the boundary can sit a hair outside the interior-cell bbox
    for f in fc["features"]:
        assert f["type"] == "Feature" and f["properties"]["kind"] == "hazard_keepout"
        geom = f["geometry"]
        assert geom["type"] == "Polygon"
        for ring in geom["coordinates"]:
            assert len(ring) >= 4, "a polygon ring needs >= 4 positions (>= 3 distinct + closing)"
            assert ring[0] == ring[-1], "the ring must be explicitly closed"
            for lon, lat in ring:
                assert bbox["west"] - pad <= lon <= bbox["east"] + pad
                assert bbox["south"] - pad <= lat <= bbox["north"] + pad


def test_nogo_cells_inside_and_clear_cells_outside(real_derivation):  # council #52
    """The geometry invariant: a CORE hazardous (NOGO) cell centre falls INSIDE a derived polygon, and a
    CORE clear cell centre falls OUTSIDE every polygon. 'Core' = the cell and its 4-neighbours share the
    class, so the centre is safely off the 0.5-contour boundary (a boundary tie is not a correctness bug)."""
    fc, nogo, xs, ys, inv = real_derivation
    up = np.roll(nogo, 1, 0); dn = np.roll(nogo, -1, 0)
    lf = np.roll(nogo, 1, 1); rt = np.roll(nogo, -1, 1)
    interior = np.zeros_like(nogo)
    interior[1:-1, 1:-1] = True                                  # ignore the wrapped edge from np.roll
    core_nogo = nogo & up & dn & lf & rt & interior             # a NOGO cell fully surrounded by NOGO
    core_clear = (~nogo) & (~up) & (~dn) & (~lf) & (~rt) & interior
    assert core_nogo.any() and core_clear.any(), "the real crop must have both hazard and clear cores"

    rng = np.random.default_rng(0)

    def _sample(mask, n=250):
        rows, cols = np.where(mask)
        k = min(n, len(rows))
        idx = rng.choice(len(rows), size=k, replace=False)
        return list(zip(rows[idx], cols[idx]))

    for rr, cc in _sample(core_nogo):
        lon, lat = inv.transform(float(xs[cc]), float(ys[rr]))
        assert _fc_contains(fc, float(lon), float(lat)), \
            f"core hazard cell ({rr},{cc}) must fall inside a derived keep-out"
    for rr, cc in _sample(core_clear):
        lon, lat = inv.transform(float(xs[cc]), float(ys[rr]))
        assert not _fc_contains(fc, float(lon), float(lat)), \
            f"core clear cell ({rr},{cc}) must fall outside every keep-out"


def test_hazard_gate_excludes_shadow_and_keepout_layers():  # council #52
    """The gate is the PHYSICAL terrain-hazard subset (slope/sinkage/tip_risk/negative_obstacle) -- the
    PSR-shadow veto + operator keepout + fleet reservation layers are DELIBERATELY excluded (shadow is a
    lit/unlit condition, not a terrain barrier; deriving keep-outs from keep-outs would be circular). At a
    low-sun polar site PSR alone vetoes ~99% of the crop, so excluding it is what makes the product useful."""
    fc = GL.hazard_keepouts_geojson(SITE)
    props = fc["properties"]
    assert props["hazard_gate"] == ["slope", "sinkage", "tip_risk", "negative_obstacle"]
    assert set(props["per_layer_block"]) == set(props["hazard_gate"])   # only the terrain layers were composed
    assert "psr" not in props["per_layer_block"] and "keepout" not in props["per_layer_block"]
    # the hazard NOGO fraction is far below the full costmap veto (which PSR shadow dominates at Haworth).
    dem, _rc, cell_m = GL._work_area(mp, mp.bundle_for_site(SITE))
    full = GL._costmap_compose(np.asarray(dem, dtype=float), cell_m, GL._POINT_SUN_AZ, GL._POINT_SUN_EL)
    full_frac = float((~np.asarray(full.passable, bool)).mean())
    assert props["nogo_fraction"] < full_frac, "the hazard gate must be a strict subset of the full veto"


def test_min_area_gate_drops_specks():  # council #52
    """The min-area gate is real: a huge ``min_area_m2`` drops every region as a speck, returning a valid
    (empty-features) FeatureCollection -- never an error, never a fabricated polygon."""
    fc = GL.hazard_keepouts_geojson(SITE, min_area_m2=1e12)
    assert fc["type"] == "FeatureCollection"
    assert fc["properties"]["n_features"] == 0
    assert fc["properties"]["n_specks_dropped"] >= 1
    assert fc["features"] == []


def test_route_serves_geojson_and_404s_unknown_site():  # council #52
    """The PUBLIC GET /world/keepouts-from-hazard is a keyless non-destructive read (like site-suitability):
    it returns application/geo+json with the real FeatureCollection, and 404s an unimported site (no
    fabricated geometry). The keyless client here mirrors the public /ide binding."""
    c = TestClient(app, base_url="http://127.0.0.1")
    r = c.get("/world/keepouts-from-hazard", params={"site": SITE})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/geo+json")
    fc = r.json()
    assert fc["type"] == "FeatureCollection" and fc["properties"]["site"] == SITE
    assert fc["properties"]["n_features"] >= 1
    # the direct producer and the route agree (the route is a thin wrapper, no recompute drift)
    assert fc["properties"]["n_features"] == GL.hazard_keepouts_geojson(SITE)["properties"]["n_features"]
    # unknown site -> 404 (the DEM bundle resolve raises)
    assert c.get("/world/keepouts-from-hazard", params={"site": "nope_not_a_site"}).status_code == 404


def test_route_clamps_thresholds():  # council #52
    """The route clamps the query knobs so a pathological value cannot explode the trace: max_slope_deg to
    [1, 45], min_area_m2 to [0, 1e9]. A 1e12 min-area (over-cap) still returns a valid empty FC."""
    c = TestClient(app, base_url="http://127.0.0.1")
    r = c.get("/world/keepouts-from-hazard",
              params={"site": SITE, "min_area_m2": 1e12, "max_slope_deg": 999})
    assert r.status_code == 200, r.text
    props = r.json()["properties"]
    assert props["thresholds"]["max_slope_deg"] == 45.0
    assert props["thresholds"]["min_area_m2"] == 1e9
