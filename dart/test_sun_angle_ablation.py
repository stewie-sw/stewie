"""[REQ:AS-08] sun-angle ShadowNav ablation acceptance (§25 Phase 6): shadow factors help under
supported (grazing) geometry and are rejected under high-sun (short-shadow / false-shadow) geometry."""
import os

import numpy as np
import pytest

from dart import sun_angle_ablation as saa
from stewie.specs import ipex_specs

_PART = "/mnt/projects/datasets/katwijk/Part1"


def test_shadow_length_decreases_with_elevation_and_crosses_at_45():
    elevs = [5, 15, 30, 45, 60, 80]
    lens = [saa.shadow_length_m(e) for e in elevs]
    assert all(lens[i] > lens[i + 1] for i in range(len(lens) - 1)), "shadow shortens as the sun rises"
    # at 45 deg the cast shadow length equals the obstacle height (the support crossover)
    assert abs(saa.shadow_length_m(45.0) - ipex_specs.OBSTACLE_HEIGHT_M) < 1e-6


def test_grazing_geometry_supported_high_sun_rejected():
    for grazing in (5, 15, 30, 44):
        assert saa.geometry_supported(grazing), f"{grazing} deg should support a shadow factor"
    for high in (46, 60, 80):
        assert not saa.geometry_supported(high), f"{high} deg should reject (shadow too short)"


@pytest.mark.skipif(not os.path.isdir(_PART), reason="raw Katwijk not present")
def test_sun_angle_ablation_helps_at_grazing_and_rejects_at_high_sun():
    from stewie.eval import katwijk_baseline as KB
    _t, truth = KB.load_rtk_track(_PART)
    _td, dr, _yaw = KB._dead_reckon(_PART, r_wheel=0.123025)
    dr_rs = dr[np.linspace(0, len(dr) - 1, len(truth)).astype(int)]

    out = saa.sun_angle_ablation(truth, dr_rs, [10, 25, 40, 60, 80],
                                 n_keyframes=30, fix_interval=4, seed=0)
    rows = {r["sun_elev_deg"]: r for r in out["rows"]}
    base = out["baseline_abs_max_err_m"]

    # supported geometry (grazing): factor ACCEPTED and HELPS (bounds the real dead-reckoning drift)
    for e in (10, 25, 40):
        assert rows[e]["accepted"] and rows[e]["helped"], rows[e]
        assert rows[e]["abs_max_err_m"] < base, rows[e]
    # unsupported geometry (high sun): factor REJECTED -> estimate stays at the DR baseline (not helped)
    for e in (60, 80):
        assert not rows[e]["accepted"] and not rows[e]["helped"], rows[e]
        assert rows[e]["abs_max_err_m"] == base, rows[e]
    # the real reduction is large (an absolute channel bounds unbounded DR drift)
    assert base > 10.0 and out["with_shadow_abs_max_err_m"] < 0.5 * base
