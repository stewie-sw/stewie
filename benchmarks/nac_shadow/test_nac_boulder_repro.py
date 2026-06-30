"""Real-data tests for the NAC boulder shadow-height reproduction (Target A h/d, Target B Station 6).

Fixtures are SUBSAMPLED REAL LROC NAC orthoimages (no synthetic data):
  - messier_lowsun_M165530748_crop.tif   : 1600x1600 px window of the Messier low-Sun ortho (0.6 m/px,
                                            Sun elevation 21.89 deg), a boulder-rich fresh-crater ejecta patch.
  - station6_house_rock_M134991788_crop.tif: 320x320 px window of the Apollo 17 Station 6 ortho (0.6 m/px,
                                            Sun elevation 25.34 deg) centred on the House Rock fragment group.
Both carry the real GeoTIFF transform (GSD) and were cut from the same products the deliverable runs on.
"""
import math
import os
import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import nac_boulder_repro as M  # noqa: E402

FX = Path(__file__).parent / "fixtures"
MESSIER = FX / "messier_lowsun_M165530748_crop.tif"
STATION6 = FX / "station6_house_rock_M134991788_crop.tif"
# main House Rock fragment seed in the 320x320 fixture (global (4930,6585) - origin (4772,6434))
HOUSE_ROCK_SEED = (158, 151)

pytestmark = pytest.mark.skipif(not (MESSIER.exists() and STATION6.exists()),
                                reason="real NAC fixture crops not present")


def _messier_boulders():
    gray, gsd, _ = M.load_gray(str(MESSIER))
    fr = M.FRAMES["messier_low_sun"]
    return M.detect_boulders(gray, gsd, fr["sun_elevation_deg"], fr["anti_solar_image_az_deg"])


# ---- metadata provenance -------------------------------------------------------------------------------
def test_elevation_is_ninety_minus_incidence():
    for key in ("messier_low_sun", "station6"):
        fr = M.FRAMES[key]
        assert fr["sun_elevation_deg"] == pytest.approx(90.0 - fr["incidence_deg"], abs=1e-9)
    # the load-bearing low-Sun values, from the ODE CDRNAC4 geometry index
    assert M.FRAMES["messier_low_sun"]["sun_elevation_deg"] == pytest.approx(21.89, abs=0.01)
    assert M.FRAMES["station6"]["sun_elevation_deg"] == pytest.approx(25.34, abs=0.01)


# ---- TARGET A: population h/d on real boulders ----------------------------------------------------------
def test_messier_detects_isolated_boulders():
    bs = _messier_boulders()
    assert len(bs) >= 5, f"expected >=5 isolated boulders in the fixture, got {len(bs)}"


def test_messier_population_is_boulder_like_not_crater_like():
    bs = _messier_boulders()
    hd = sorted(b.h_over_d for b in bs)
    median = hd[len(hd) // 2]
    # craters (depth/diameter ~0.1-0.2) are excluded; lunar boulders cluster at h/d ~0.5-0.6
    assert median > 0.30, f"median h/d {median:.3f} looks crater-like, not boulder-like"
    assert 0.35 <= median <= 0.75, f"median h/d {median:.3f} outside the lunar-boulder aspect family"


def test_messier_heights_use_dart_shadow_formula():
    bs = _messier_boulders()
    tan_e = math.tan(math.radians(M.FRAMES["messier_low_sun"]["sun_elevation_deg"]))
    for b in bs[:10]:
        assert b.height_m == pytest.approx(b.shadow_len_m * tan_e, rel=0.02), "H must equal L*tan(e) [DART]"


def test_shadow_axis_crosscheck_matches_recorded_azimuth():
    gray, _, _ = M.load_gray(str(MESSIER))
    axis = M.estimate_shadow_axis_deg(gray)                 # mod 180, data-derived
    recorded = M.FRAMES["messier_low_sun"]["anti_solar_image_az_deg"] % 180.0
    diff = abs((axis - recorded + 90) % 180 - 90)
    assert diff < 25.0, f"data shadow axis {axis:.1f} disagrees with recorded {recorded:.1f}"


# ---- TARGET B: Station 6 House Rock --------------------------------------------------------------------
def test_station6_largest_fragment_height_consistent_with_6m():
    gray, gsd, _ = M.load_gray(str(STATION6))
    fr = M.FRAMES["station6"]
    res = M.measure_named_fragment(gray, gsd, fr["sun_elevation_deg"], fr["anti_solar_image_az_deg"],
                                   HOUSE_ROCK_SEED, cap_thr=200.0)
    assert res is not None, "House Rock main fragment not measurable in fixture"
    assert 4.0 <= res["height_m"] <= 8.0, f"H={res['height_m']} m not consistent with documented ~6 m"
    assert res["diameter_m"] >= 4.0


# ---- TRUTH FIREWALL: measurement must not depend on the published targets -------------------------------
def test_truth_isolation_population_unchanged_when_demidov_corrupted():
    before = [(b.col, b.row, b.height_m, b.diameter_m, b.h_over_d) for b in _messier_boulders()]
    saved = deepcopy(M.PUBLISHED["demidov_hd"])
    try:
        M.PUBLISHED["demidov_hd"]["h_over_d"] = 0.99
        M.PUBLISHED["demidov_hd"]["sigma"] = 0.0001
        M.PUBLISHED["demidov_hd"]["also"] = {"engineering": 9.9, "h_over_D_full": 9.9}
        after = [(b.col, b.row, b.height_m, b.diameter_m, b.h_over_d) for b in _messier_boulders()]
        assert after == before, "measurement changed when the published h/d target was corrupted"
    finally:
        M.PUBLISHED["demidov_hd"] = saved


def test_truth_isolation_station6_unchanged_when_target_corrupted():
    gray, gsd, _ = M.load_gray(str(STATION6))
    fr = M.FRAMES["station6"]

    def meas():
        return M.measure_named_fragment(gray, gsd, fr["sun_elevation_deg"], fr["anti_solar_image_az_deg"],
                                        HOUSE_ROCK_SEED, cap_thr=200.0)["height_m"]
    before = meas()
    saved = deepcopy(M.PUBLISHED["station6_house_rock"])
    try:
        M.PUBLISHED["station6_house_rock"]["height_m"] = 99.0
        M.PUBLISHED["station6_house_rock"]["block_dims_m"] = [999, 999, 999]
        assert meas() == before, "Station 6 measurement changed when its published target was corrupted"
    finally:
        M.PUBLISHED["station6_house_rock"] = saved


def test_compare_does_read_published_value():
    """Dual of the firewall test: the COMPARE step is exactly where the published value must enter."""
    stats = {"n": 50, "median": 0.60, "median_ci95": [0.55, 0.64]}
    base = M.compare_demidov(stats)["verdict"]
    saved = deepcopy(M.PUBLISHED["demidov_hd"])
    try:
        M.PUBLISHED["demidov_hd"]["h_over_d"] = 0.05
        M.PUBLISHED["demidov_hd"]["sigma"] = 0.001
        M.PUBLISHED["demidov_hd"]["also"] = {"engineering": 0.05, "h_over_D_full": 0.05}
        changed = M.compare_demidov(stats)["verdict"]
        assert changed != base, "compare_demidov ignored the published value -- firewall would be vacuous"
    finally:
        M.PUBLISHED["demidov_hd"] = saved
