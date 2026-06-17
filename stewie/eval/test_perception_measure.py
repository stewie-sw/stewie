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
    # the per-pair band is the objective TRL5 band, not the full sensor range
    lo, hi = r["per_pair"][0]["band_m"]
    assert 0.0 < lo < hi < 12.0


def test_measure_pair_skips_a_pose_dir_without_renders(tmp_path):
    """A pose dir lacking the rendered run / truth raises FileNotFoundError (caller skips) -- never a
    silent fabricated measurement."""
    from stewie.eval.perception_measure import measure_pair
    with pytest.raises((FileNotFoundError, KeyError)):
        measure_pair(str(tmp_path), _SCENE)
