"""[REQ:AS-09] ARGUS standstill-relocalization acceptance (§25 Phase 7): an accepted articulation-
parallax factor reduces the position covariance; a rejected one (mirror-ambiguous collinear
landmarks, or beyond camera-resolvable range) is not inserted and leaves the covariance unchanged."""
import numpy as np

from dart import argus_relocalization as ar
from dart.pose_graph_se2 import PoseGraphSE2

DH_M = 0.1743      # commanded chassis-lift parallax baseline (MEERKAT)
FX_PX = 679.57     # rig intrinsic
PRIOR_XY = (0.0, 0.0)
PRIOR_COV = [[4.0, 0.0], [0.0, 4.0]]   # 2 m-sigma drifted standstill prior
NEAR_WELL_SPREAD = [(5.0, 5.0), (-5.0, 6.0), (6.0, -4.0)]   # near, non-collinear -> resolvable


def test_accepted_argus_fix_reduces_covariance():
    res = ar.argus_standstill_fix(PRIOR_XY, PRIOR_COV, NEAR_WELL_SPREAD, dh_m=DH_M, fx_px=FX_PX)
    assert res["accepted"], res["reasons"]
    # information addition: the fused posterior covariance is strictly smaller (det) than the prior
    assert res["det_post"] < res["det_prior"]
    # and it is no larger than the prior on every axis (PD, shrinking)
    shrink = np.linalg.eigvalsh(res["cov_prior"]) >= np.linalg.eigvalsh(res["cov_post"]) - 1e-12
    assert np.all(shrink)


def test_accepted_fix_is_inserted_into_the_graph():
    res = ar.argus_standstill_fix(PRIOR_XY, PRIOR_COV, NEAR_WELL_SPREAD, dh_m=DH_M, fx_px=FX_PX)
    g = PoseGraphSE2()
    g.add_prior(0, (0.0, 0.0, 0.0), sigma_xy=2.0, sigma_yaw=1.0)
    assert ar.insert_into_graph(g, 0, (0.1, -0.1), res) is True   # accepted -> a factor is added


def test_collinear_landmarks_rejected_not_inserted():
    collinear = [(2.0, 2.0), (4.0, 4.0), (6.0, 6.0)]             # mirror ambiguity (H-14)
    res = ar.argus_standstill_fix(PRIOR_XY, PRIOR_COV, collinear, dh_m=DH_M, fx_px=FX_PX)
    assert not res["accepted"]
    assert any("collinear" in r for r in res["reasons"])
    assert res["det_post"] == res["det_prior"]                   # covariance unchanged
    g = PoseGraphSE2()
    g.add_prior(0, (0.0, 0.0, 0.0), sigma_xy=2.0, sigma_yaw=1.0)
    assert ar.insert_into_graph(g, 0, (0.0, 0.0), res) is False  # rejected -> NOT inserted


def test_beyond_resolvable_range_rejected():
    # at dh=0.17 m, fx=680 px, parallax falls below 1 px past ~115 m -> these far landmarks are unusable
    far = [(150.0, 5.0), (-140.0, 6.0), (160.0, -4.0)]
    res = ar.argus_standstill_fix(PRIOR_XY, PRIOR_COV, far, dh_m=DH_M, fx_px=FX_PX)
    assert not res["accepted"]
    assert any("resolvable range" in r for r in res["reasons"])
    assert np.allclose(res["cov_post"], res["cov_prior"])
