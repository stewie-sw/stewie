"""PM-13 (Convergence Phase B, rec #6): the dense stereo-depth-measurement producer, exercised on the
REAL g2cal rendered corpus. The dense reconstruction RMSE that map_channel reports as the gated tier
(`dense_rmse_available=False`) is now a measured number -- SGBM-observed depth vs geometric ray-cast
truth over real rendered frames, clast-masked, restricted to the TRL5-derived objective stereo band.

Skips cleanly when the rendered corpus is absent (CI without the on-disk bundle), so it never fabricates.
"""
import os
import warnings

import pytest

from stewie.eval.perception_measure import measure_corpus

_HERE = os.path.dirname(os.path.abspath(__file__))
_G2 = os.path.join(_HERE, "validation", "g2cal")
_SCENE = os.path.join(_HERE, "..", "..", "samples", "crater_boulders")


@pytest.mark.skipif(
    not os.path.isdir(_G2) or len([p for p in os.listdir(_G2) if p.startswith("pose_")]) < 4,
    reason="g2cal rendered corpus not present")
def test_dense_depth_rmse_on_real_rendered_corpus():
    warnings.filterwarnings("ignore")
    r = measure_corpus(_G2, _SCENE)
    assert r["n_pairs"] >= 1, "no rendered pair produced an in-band measurement"
    assert r["n_valid_total"] >= 1000, f"corpus too thin: {r['n_valid_total']} valid px"
    rmse = r["dense_depth_rmse_m"]
    # SGBM depth at the 0.37-1.89 m objective band -> cm-to-decimetre accuracy; reject NaN / implausible
    assert 0.0 < rmse < 0.5, f"dense depth RMSE {rmse} m outside plausibility for the objective band"
    assert r["dense_depth_mae_m"] <= rmse + 1e-9, "MAE must not exceed RMSE"          # math invariant
    # PM-15: the map-frame reconstruction (observed world-point height vs true terrain at its footprint)
    hrmse = r["dense_height_rmse_m"]
    assert r["n_height_total"] >= 1000 and 0.0 < hrmse < 0.5, f"dense height RMSE {hrmse} m implausible"
    # the per-pair band is the objective TRL5 band, not the full sensor range
    pp0 = r["per_pair"][0]
    lo, hi = pp0["band_m"]
    assert 0.0 < lo < hi < 12.0
    # PM-14: the observed point cloud has a real size + finite ground (x,z) footprint
    assert pp0["n_points"] > 0 and len(pp0["pointcloud_extent_xz_m"]) == 2
    assert all(e >= 0.0 for e in pp0["pointcloud_extent_xz_m"])


def test_measure_pair_skips_a_pose_dir_without_renders(tmp_path):
    """A pose dir lacking the rendered run / truth raises FileNotFoundError (caller skips) -- never a
    silent fabricated measurement."""
    from stewie.eval.perception_measure import measure_pair
    with pytest.raises((FileNotFoundError, KeyError)):
        measure_pair(str(tmp_path), _SCENE)


_BEFORE = os.path.join(_HERE, "..", "..", "samples", "crater_boulders")
_AFTER = os.path.join(_HERE, "..", "..", "samples", "crater_boulders_worked")


@pytest.mark.skipif(not (os.path.isdir(_BEFORE) and os.path.isdir(_AFTER)),
                    reason="before/after scene pair not present")
def test_pm16_excavation_volume_on_real_before_after():
    """PM-16: cut/fill/net excavation volume between the REAL crater_boulders (before) and
    crater_boulders_worked (after) conserved-authority scenes. The worked scene was excavated, so cut
    volume > 0; net = fill - cut (signed); volumes are physically scaled (sub-m^3 on a 5 m, 2 cm patch)."""
    from stewie.eval.perception_measure import volume_from_scenes
    v = volume_from_scenes(_BEFORE, _AFTER)
    assert v["cut_volume_m3"] > 0 and v["fill_volume_m3"] >= 0 and v["changed_cells"] > 100
    assert abs(v["net_volume_m3"] - (v["fill_volume_m3"] - v["cut_volume_m3"])) < 1e-6   # net = fill - cut
    assert 0 < v["cut_volume_m3"] < 10.0


def test_pm16_rejects_mismatched_grids():
    """A before/after grid mismatch is rejected, not silently broadcast into a wrong volume."""
    import numpy as np

    from stewie.eval.perception_measure import excavation_volume
    with pytest.raises(ValueError):
        excavation_volume(np.zeros((4, 4)), np.zeros((5, 5)), 0.02)
