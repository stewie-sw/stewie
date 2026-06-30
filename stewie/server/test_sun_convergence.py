"""#266 -- the TRUE selenographic sun azimuth must be re-expressed in the DEM GRID frame before the
dart.illumination horizon march, else shadow/illumination/incidence drape off the real bearing.

The DEM is IAU_2015:30135 south-polar stereographic kept NORTH-UP (load_haworth_dem: row 0 = max
stereo-Y, no flipud), while dart.illumination ASSUMES origin-lower-left (+row = north). The row-flip
plus the polar meridian convergence make the (row, col) grid LEFT-handed and ~180 deg turned vs true
compass -- so the map true_az -> grid_az is a REFLECTION, not a small rotation. These tests pin both
links of the chain on REAL Haworth data:

  T2  grid_north_bearing_deg measures, via the production georeferencing (dem_origin_to_latlon), that
      grid az=0 (+row) points at true bearing ~205.5 deg and grid az=90 (+col) at ~115.5 (= B-90, the
      left-handed signature) -- the actual grid->true map, independent of the formula.
  T1  grid_sun_az inverts it: to march at true bearing theta, pass (B - theta).
  T3  the corrected layer differs materially from the uncorrected one through the real render() path
      (guards that the correction is actually wired in, not dead code).

Together T1 x T2 fix the sign non-circularly; the pre-#266 code fed the true azimuth straight into the
grid march (error ~26 deg near az=90 -- what the cockpit council first reported -- up to ~180 deg
elsewhere).
"""
import math
import os

import pytest
from fastapi.testclient import TestClient

BUNDLE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "samples", "lunar_dem", "haworth_10km_5m")
_needs_dem = pytest.mark.skipif(not os.path.isdir(BUNDLE), reason="Haworth bundle absent")


def test_grid_sun_az_is_the_reflection_inverse():
    """T1: grid_sun_az(true_az, B) == (B - true_az) % 360 -- the inverse of the grid march's
    true_bearing = B - grid_az. Pins the exact formula (a rotation +/-C would NOT satisfy these)."""
    from stewie.server.gis_layers import grid_sun_az
    B = 205.5
    assert grid_sun_az(90.0, B) == pytest.approx(115.5)        # sun due east -> grid az 115.5
    assert grid_sun_az(B, B) == pytest.approx(0.0)             # sun along +row -> grid az 0
    assert grid_sun_az(B - 90.0, B) == pytest.approx(90.0)     # sun along +col -> grid az 90
    # it is a reflection, not a rotation: az and (2B - az) map to grid azimuths that are negatives mod 360
    a1, a2 = grid_sun_az(40.0, B), grid_sun_az(2 * B - 40.0, B)
    assert (a1 + a2) % 360.0 == pytest.approx(0.0, abs=1e-9)
    for az in (0.0, 37.0, 123.4, 290.0):                       # always wrapped into [0, 360)
        assert 0.0 <= grid_sun_az(az, B) < 360.0


@_needs_dem
def test_grid_north_bearing_is_left_handed_and_pole_convergent():
    """T2: on the REAL Haworth tile, the +row direction (grid az=0) does NOT point at true north -- it
    points at ~205.5 deg (roughly south + the ~26 deg meridian convergence), and +col (grid az=90) at
    that minus 90 (the left-handed signature from the north-up row-flip). Measured via the production
    georeferencing, so it is the independent ground truth the formula is inverted against."""
    from stewie.terrain.site_dem import dem_origin_to_latlon, grid_north_bearing_deg
    import json
    pytest.importorskip("pyproj")
    g = json.load(open(os.path.join(BUNDLE, "metadata.json")))["grid"]
    cell, W, H = float(g["cell_m"]), int(g["width"]), int(g["height"])
    cx, cy = (W / 2.0) * cell, (H / 2.0) * cell

    B = grid_north_bearing_deg(cx, cy, bundle_dir=BUNDLE)
    assert B == pytest.approx(205.5, abs=1.5)                  # NOT ~0: +row is not true north
    assert not (B < 10.0 or B > 350.0)                        # explicitly excludes "grid north == true north"

    # +col (grid az 90) true bearing, measured the same way -> must be B - 90 (left-handed)
    def bearing(p0, p1):
        (la0, lo0), (la1, lo1) = p0, p1
        dl = math.radians(lo1 - lo0)
        e = math.sin(dl) * math.cos(math.radians(la1))
        n = (math.cos(math.radians(la0)) * math.sin(math.radians(la1))
             - math.sin(math.radians(la0)) * math.cos(math.radians(la1)) * math.cos(dl))
        return math.degrees(math.atan2(e, n)) % 360.0
    c0 = dem_origin_to_latlon(cx, cy, bundle_dir=BUNDLE)
    bcol = bearing(c0, dem_origin_to_latlon(cx + cell, cy, bundle_dir=BUNDLE))   # +col = grid az 90
    assert ((B - 90.0) - bcol + 180.0) % 360.0 - 180.0 == pytest.approx(0.0, abs=1.0)


@_needs_dem
def test_correction_is_a_reflection_through_the_real_render_path():
    """T3: the correction is wired through _layer_rgba AND is a REFLECTION, not a uniform rotation.
    On the real tile the per-pixel change varies strongly with sun azimuth -- large where the corrected
    grid az swings ~180 deg from the uncorrected one (az~=0/180), tiny near the reflection's fixed axis
    (az~=B/2, where uncorrected ~= corrected). A constant-rotation 'fix' would change every azimuth by
    the same fraction, so this both proves wiring and rejects the wrong (rotation) fix."""
    pytest.importorskip("pyproj")
    from lode import mission_planner as mp
    from stewie.server import gis_layers as G

    bundle_dir = mp.bundle_for_site("haworth")
    dem, (r0, c0), cell_m = G._work_area(mp, bundle_dir)
    cx = (c0 + dem.shape[1] / 2.0) * cell_m
    cy = (r0 + dem.shape[0] / 2.0) * cell_m
    from stewie.terrain.site_dem import grid_north_bearing_deg
    gnb = grid_north_bearing_deg(cx, cy, bundle_dir=bundle_dir)

    def changed(kind, az):
        u = G._layer_rgba(dem, cell_m, kind, sun_az=az, sun_el=6.0)                     # old behaviour
        c = G._layer_rgba(dem, cell_m, kind, sun_az=az, sun_el=6.0, grid_north_bearing=gnb)
        assert u is not None and c is not None
        return float((u.astype(int) != c.astype(int)).any(axis=-1).mean())

    for kind in ("illumination", "incidence"):
        far = changed(kind, 180.0)       # corrected grid az swings ~180 deg from the true azimuth
        near = changed(kind, gnb / 2.0)  # the reflection fixed axis: corrected ~= uncorrected
        assert far > 0.20, f"{kind}: az=180 changed only {far:.1%} -- correction not applied?"
        assert far > near + 0.15, (f"{kind}: change is azimuth-INVARIANT ({near:.1%} vs {far:.1%}) -- "
                                    "that is a uniform rotation, not the meridian-convergence reflection")


@_needs_dem
def test_workarea_inset_threads_the_grid_convergence(monkeypatch, tmp_path):
    """#272 (#266 completion): the /dem/workarea.png inset was the 3rd _layer_rgba consumer and was passing
    the TRUE sun azimuth straight into the grid march (grid_north_bearing defaulting to None). It must now
    thread the per-tile grid-north bearing for illumination/incidence ONLY -- and never for the sun-agnostic
    kinds (slope/dem/psr). Spy on _layer_rgba to capture exactly what the route threads."""
    pytest.importorskip("pyproj")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")                # loopback dev-open -> require_auth passes
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)

    import numpy as np

    from stewie.server import gis_layers as G
    captured = {}

    def spy(patch, cell, kind, az=315.0, el=45.0, *, grid_north_bearing=None, **kw):
        captured[kind] = grid_north_bearing
        return np.zeros((4, 4, 4), dtype=np.uint8)        # a valid rgba so the route completes
    monkeypatch.setattr(G, "_layer_rgba", spy)

    import stewie.server.server as SRV
    from stewie.server.routers import dem as DEM
    DEM._WORKAREA_CACHE.clear()                            # avoid a cached PNG short-circuiting the spy
    c = TestClient(SRV.app)

    assert c.get("/dem/workarea.png?kind=illumination&sun_az=90&sun_el=6&site=haworth").status_code == 200
    assert c.get("/dem/workarea.png?kind=slope&site=haworth").status_code == 200
    assert captured.get("illumination") is not None, "illumination inset still uncorrected (#272)"
    assert 200.0 < captured["illumination"] < 212.0, (   # the real Haworth +row true bearing ~206 deg
        f"grid-north bearing off ({captured['illumination']:.1f}); expected ~206")
    assert captured.get("slope") is None, "slope must NOT get the sun-azimuth grid correction"
