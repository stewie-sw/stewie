"""Tests for the two-Sun NAC sparse-mare helpers, run on TINY REAL fixtures.

The fixtures are small georeferenced crops of the actual downloaded LROC NAC stereo-DTM orthos
(Messier1/Messier3 over Mare Fecunditatis at Sun elev 45/21 deg; Reiner5/Reinerphot over Reiner Gamma
at 15/47 deg) -- real PDS data subsampled to ~180 m windows, not synthetic. benchmarks/ is outside
testpaths, so the default suite does not collect this; run explicitly:
    .venv/bin/python -m pytest benchmarks/nac_shadow/test_nac_twosun.py
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np
import rasterio

sys.path.insert(0, os.path.dirname(__file__))
import nac_twosun as nt  # noqa: E402

FX = os.path.join(os.path.dirname(__file__), "fixtures")
M3 = os.path.join(FX, "messier_m3_e21_M165530748.tif")     # low Sun  e21, 0.6 m
M1 = os.path.join(FX, "messier_m1_e45_M1098530546.tif")    # high Sun e45, 1.3 m
R5 = os.path.join(FX, "reiner_r5_e15_M102536848.tif")      # low Sun  e15, 1.3 m
RP = os.path.join(FX, "reiner_rp_e47_M1167547085.tif")     # high Sun e47, 1.2 m
# the shared world box the Messier fixtures were cropped to (Equirectangular_Moon metres)
MESSIER_BOX = (-4006772.0, -60361.0, -4006592.0, -60181.0)
MESSIER_CENTER = (-4006682.0, -60271.0)


def test_fixtures_exist():
    for p in (M3, M1, R5, RP):
        assert os.path.exists(p), p


def test_products_table_is_real_and_two_sun():
    assert set(nt.PRODUCTS_TWOSUN) >= {"messier", "reiner", "a12_control"}
    for name in ("messier", "reiner"):
        site = nt.PRODUCTS_TWOSUN[name]
        lo, hi = site["low_sun"], site["high_sun"]
        # a genuine two-Sun pair: distinct frames at distinct elevations, real PDS URLs
        assert lo["frame"] != hi["frame"]
        assert abs(lo["sun_elevation_deg"] - hi["sun_elevation_deg"]) > 10.0
        for spec in (lo, hi):
            assert spec["url"].startswith("https://pds.lroc.im-ldi.com/")
            assert math.isclose(spec["sun_elevation_deg"], 90.0 - spec["incidence_deg"], abs_tol=0.05)


def test_gate_threshold_is_spec():
    assert nt.GATE_R == 0.30


def test_gate_on_crop_returns_triple():
    with rasterio.open(R5) as ds:
        crop = ds.read(1)
    r, n, az = nt.gate_on_crop(crop)
    assert -1.0 <= r <= 1.0
    assert isinstance(n, int) and n >= 0
    assert math.isnan(az) or (0.0 <= az < 360.0)


def test_scan_gate_windows_on_fixture():
    with rasterio.open(M3) as ds:
        arr = ds.read(1)
        tf = ds.transform
    hits = nt.scan_gate_windows(arr, tf, win=128, step=64, min_std=1.0)
    assert isinstance(hits, list)
    for h in hits:
        assert -1.0 <= h.confidence_R <= 1.0
        assert isinstance(h, nt.GateHit)
    # sorted by R descending
    rs = [h.confidence_R for h in hits]
    assert rs == sorted(rs, reverse=True)


def test_detect_isolated_boulders_on_fixture():
    with rasterio.open(M3) as ds:
        arr = ds.read(1)
        tf = ds.transform
    cands = nt.detect_isolated_boulders(arr, tf, crop=40, smooth_max=30.0, max_eval=50)
    assert isinstance(cands, list)
    for c in cands:
        assert isinstance(c, nt.GateHit)
        assert -1.0 <= c.confidence_R <= 1.0


def test_measure_two_sun_structure_and_no_fabrication():
    with rasterio.open(M3) as dlo, rasterio.open(M1) as dhi:
        res = nt.measure_two_sun(dlo, 21.89, dhi, 45.23, MESSIER_CENTER, half_px=40)
    assert res["world_xy"] == [MESSIER_CENTER[0], MESSIER_CENTER[1]]
    for k in ("low_sun", "high_sun"):
        sub = res[k]
        assert sub["shadow_len_m"] >= 0.0
        # H is recovered ONLY from a measured shadow: L=0 must give H=0 (never a fabricated height)
        if sub["shadow_len_m"] == 0.0:
            assert sub["H_m"] == 0.0
        else:
            assert math.isclose(sub["H_m"], sub["shadow_len_m"] * math.tan(math.radians(sub["sun_elevation_deg"])),
                                rel_tol=1e-6)
    assert "two_sun" in res


def test_measure_two_sun_matches_dart_height():
    # the recovered height wraps the tested DART H = L*tan(e)
    import nac_shadow as ns
    from dart.rock_taxonomy import shadow_height_m
    assert math.isclose(ns.recover_height_m(12.5, 21.89), shadow_height_m(12.5, 21.89), rel_tol=1e-12)


def test_coreg_corr_finite_on_messier_fixtures():
    cc = nt.coreg_corr(M3, M1, MESSIER_BOX, shape=(120, 120))
    assert np.isfinite(cc)
