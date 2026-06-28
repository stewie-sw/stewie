"""TDD for dart.s3li_dem: the INDEPENDENT Copernicus GLO-30 DEM anchoring prior for the S3LI
``s3li_crater`` traverse (Mt Etna / Cisternazza), reproducing arXiv:2603.17229.

Data-gated: skips cleanly where either the real DEM tile or the real GT track is absent (mirrors the
_have_lusnar / _have_katwijk pattern). Nothing here is synthetic -- the registration assertions sample
the REAL Copernicus tile at the REAL D-GNSS ground-truth lat/lon of the traverse.

WHAT THESE TESTS PIN (numbers measured on the real data, 2026-06-28):
  * the DEM tile (N37/E015, EGM2008-orthometric, ~30 m) COVERS the traverse bbox;
  * registration is judged on RELIEF SHAPE, not the datum offset. GT is WGS84-ELLIPSOIDAL, the DEM is
    EGM2008-ORTHOMETRIC, so a near-constant tens-of-metres offset is EXPECTED (the geoid). Measured:
      - de-meaned relief RMSE   = 2.19 m  (asserted < 4.0 m; well inside one 30 m cell)
      - along-track correlation = 0.9956 (asserted > 0.95)
      - raw mean offset         = 33.46 m, std 2.19 m (the datum: EGM2008 geoid +43.46 m minus a
        near-constant vertical bias from antenna height / GNSS-base reference / decadal terrain change
        on an active volcano; a CONSTANT, NOT a horizontal misregistration, which the 0.9956
        correlation rules out).
  * the sampler returns a finite height and a UNIT outward (Up>0) ENU normal at real traverse points;
  * ENU<->LLE round-trips (geodetic ECEF frame) to sub-micrometre.

Truth firewall (invariant I3): the sampler reads ONLY the independent DEM + the declared origin
constant -- never the GT trajectory. These tests load GT to SCORE the registration (the test is the
scoring layer, like dart.lusnar_reader's GT use); the firewall is enforced downstream at the estimator
input, never by feeding the GT track into the sampler.
"""
import os

import numpy as np
import pytest

from dart import s3li_dem
from dart.s3li_dem import S3liDem

_GT_POS = "/mnt/projects/datasets/argus_dem_nav/s3li/data/GT/s3li_crater/global_lle.pos"
_have_dem = os.path.isfile(s3li_dem.DEFAULT_DEM_PATH)
_have_gt = os.path.isfile(_GT_POS)
_have_all = _have_dem and _have_gt


def _load_gt() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Parse global_lle.pos (RTKLIB) -> (lat_deg, lon_deg, height_ellipsoidal_m), past the % header."""
    lat: list[float] = []
    lon: list[float] = []
    h: list[float] = []
    with open(_GT_POS) as f:
        for line in f:
            if line.startswith("%") or not line.strip():
                continue
            q = line.split()
            lat.append(float(q[2]))
            lon.append(float(q[3]))
            h.append(float(q[4]))
    return np.array(lat), np.array(lon), np.array(h)


# ---- pure / numeric (no external assets) ---------------------------------------------------------
def test_origin_datum_constants_self_consistent():
    """The declared origin's orthometric height is its ellipsoidal height minus the EGM2008 geoid
    undulation (a genuine arithmetic check on the datum bookkeeping, not a tautology)."""
    expected = s3li_dem.ORIGIN_HEIGHT_ELLIPSOIDAL_M - s3li_dem.EGM2008_GEOID_UNDULATION_M
    assert s3li_dem.ORIGIN_HEIGHT_ORTHOMETRIC_M == pytest.approx(expected, abs=1e-6)
    # the geoid undulation at Sicily/Etna is the documented +43..+47 m band
    assert 40.0 < s3li_dem.EGM2008_GEOID_UNDULATION_M < 48.0


# ---- real-data-gated ------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def dem() -> S3liDem:
    if not _have_dem:
        pytest.skip(f"independent DEM tile not present: {s3li_dem.DEFAULT_DEM_PATH}")
    return S3liDem()


@pytest.mark.skipif(not _have_all, reason="needs the real DEM tile + GT track")
def test_dem_covers_gt_bbox(dem: S3liDem):
    """The loaded DEM window covers the full traverse bounding box (all four corners + the endpoints)."""
    lat, lon, _ = _load_gt()
    w, s, e, n = lon.min(), lat.min(), lon.max(), lat.max()
    for la, lo in [(s, w), (s, e), (n, w), (n, e)]:
        assert dem.covers_lle(la, lo), f"bbox corner ({la:.6f},{lo:.6f}) not covered"
    # every real traverse point must be inside the bilinear-valid interior
    assert all(dem.covers_lle(la, lo) for la, lo in zip(lat, lon))


@pytest.mark.skipif(not _have_all, reason="needs the real DEM tile + GT track")
def test_registration_relief_shape(dem: S3liDem):
    """Correct geo-referencing is proven by the RELIEF: a small de-meaned RMSE and a high along-track
    correlation between the DEM profile and the GT height profile. The raw mean offset (the datum) is
    reported separately and is NOT treated as an error."""
    lat, lon, h_gt = _load_gt()
    h_dem = dem.heights_lle(lat, lon)              # EGM2008-orthometric
    assert np.isfinite(h_dem).all()

    offset = float(np.mean(h_gt - h_dem))          # GT ellipsoidal - DEM orthometric ~ geoid datum
    resid = (h_gt - h_dem) - offset
    rmse = float(np.sqrt(np.mean(resid**2)))
    corr = float(np.corrcoef(h_dem, h_gt)[0, 1])

    # relief shape: the registration validators
    assert rmse < 4.0, f"de-meaned relief RMSE {rmse:.3f} m too large for a 30 m DEM"
    assert corr > 0.95, f"along-track correlation {corr:.4f} too low -- DEM not over the traverse"
    # the offset is a near-constant datum (the geoid), not a tilt/misregistration
    assert 20.0 < offset < 50.0, f"raw offset {offset:.3f} m outside the expected geoid datum band"
    assert float(np.std(h_gt - h_dem)) < 4.0, "offset is not spatially constant -> a real misregistration"


@pytest.mark.skipif(not _have_all, reason="needs the real DEM tile + GT track")
def test_sampler_finite_height_and_unit_normal(dem: S3liDem):
    """At several REAL traverse points the sampler returns a finite orthometric height and a unit
    outward (Up>0) ENU surface normal."""
    lat, lon, _ = _load_gt()
    idx = np.linspace(0, len(lat) - 1, 8).astype(int)
    for i in idx:
        smp = dem.sample_lle(float(lat[i]), float(lon[i]))
        assert np.isfinite(smp.height_m)
        assert 2400.0 < smp.height_m < 2800.0      # Etna upper flank, EGM2008-orthometric
        n = smp.normal_enu
        assert n.shape == (3,)
        assert np.isfinite(n).all()
        assert np.linalg.norm(n) == pytest.approx(1.0, abs=1e-9)
        assert n[2] > 0.0                          # a terrain normal points out of the ground


@pytest.mark.skipif(not _have_all, reason="needs the real DEM tile + GT track")
def test_enu_lle_roundtrip(dem: S3liDem):
    """The geodetic ENU frame round-trips lat/lon <-> ENU to sub-micrometre over the traverse."""
    lat, lon, _ = _load_gt()
    idx = np.linspace(0, len(lat) - 1, 200).astype(int)
    enu = dem.lle_to_enu(lat[idx], lon[idx])
    lat2, lon2, _ = dem.enu_to_lle(enu[0], enu[1])
    err_m = max(float(np.abs(lat2 - lat[idx]).max()), float(np.abs(lon2 - lon[idx]).max())) * 111000.0
    assert err_m < 1e-3, f"ENU round-trip error {err_m:.2e} m"


@pytest.mark.skipif(not _have_all, reason="needs the real DEM tile + GT track")
def test_enu_and_lle_samplers_agree(dem: S3liDem):
    """sample_enu and sample_lle return the same height + normal for the same physical point."""
    lat, lon, _ = _load_gt()
    i = len(lat) // 2
    enu = dem.lle_to_enu(float(lat[i]), float(lon[i]))
    a = dem.sample_lle(float(lat[i]), float(lon[i]))
    b = dem.sample_enu(float(enu[0]), float(enu[1]))
    assert a.height_m == pytest.approx(b.height_m, abs=1e-6)
    assert np.abs(a.normal_enu - b.normal_enu).max() < 1e-9


@pytest.mark.skipif(not _have_dem, reason="needs the real DEM tile")
def test_bilinear_exact_at_pixel_centre(dem: S3liDem):
    """Sampling exactly at a DEM pixel CENTRE returns that pixel's stored value -- proves the pixel-
    centre (half-pixel) referencing of the bilinear interpolator is correct."""
    nrow, ncol = dem._z.shape
    r, c = nrow // 2, ncol // 2
    lon = dem._left + (c + 0.5) * dem._resx
    lat = dem._top - (r + 0.5) * dem._resy
    assert dem.height_lle(lat, lon) == pytest.approx(float(dem._z[r, c]), abs=1e-6)
