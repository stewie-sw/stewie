"""FS-07: the Navigation operational loop as ONE connected, auditable run.

Drive a single traverse through the wired seams -- planner-scheduled relocalization stop -> observation ->
pose-graph factor -> residual/accept-reject gate -> covariance reduce (accept) / untouched (reject) ->
operator evidence view -- and assert the loop is actually closed: an accepted stop reduces the covariance
and enters the graph, a rejected stop leaves the covariance untouched with a stated reason, and every stop
is on the evidence trail. Real parallax geometry (dart.articulated_parallax); no fabricated covariance.
"""
from __future__ import annotations

import numpy as np

from dart import nav_operational_loop as NL

DH_M = 0.1743      # commanded chassis-lift parallax baseline (MEERKAT), as in test_relocalization
FX_PX = 679.57
PRIOR_XY = (0.0, 0.0)
PRIOR_COV = [[4.0, 0.0], [0.0, 4.0]]                       # 2 m-sigma drifted standstill prior
_GOOD = [(5.0, 5.0), (-5.0, 6.0), (6.0, -4.0)]            # near, non-collinear -> resolvable (ACCEPT)
_COLLINEAR = [(2.0, 2.0), (4.0, 4.0), (6.0, 6.0)]        # mirror-ambiguous (REJECT)


def _mixed_observe(i, dist):
    # even stops see a well-spread landmark set (accepted); odd stops see collinear landmarks (rejected).
    return _GOOD if i % 2 == 0 else _COLLINEAR


def test_loop_is_one_connected_run_with_accept_and_reject_branches():  # [REQ:FS-07]
    run = NL.run_nav_operational_loop(50.0, PRIOR_XY, PRIOR_COV, _mixed_observe, dh_m=DH_M, fx_px=FX_PX)
    # the planner scheduled multiple relocalization stops along the traverse
    assert run["n_stops"] >= 2, run["schedule"]
    assert len(run["evidence"]) == run["n_stops"], "the evidence trail must cover every scheduled stop"
    # BOTH branches were exercised in the one connected run
    assert run["n_accepted"] >= 1 and run["n_rejected"] >= 1, (run["n_accepted"], run["n_rejected"])

    accepts = [e for e in run["evidence"] if e["accepted"]]
    rejects = [e for e in run["evidence"] if not e["accepted"]]
    # ACCEPT branch: covariance REDUCED (information addition) + fused into the pose graph
    for e in accepts:
        assert e["det_post"] < e["det_prior"], "an accepted fix must reduce the covariance"
        assert e["cov_reduced"] is True and e["inserted"] is True
        assert e["reasons"] == []
    # REJECT branch: covariance UNTOUCHED + NOT inserted + a human-readable reason surfaced to the view
    for e in rejects:
        assert e["det_post"] == e["det_prior"], "a rejected fix must leave the covariance unchanged"
        assert e["cov_reduced"] is False and e["inserted"] is False
        assert e["reasons"] and any("collinear" in r for r in e["reasons"])
    # end-to-end: the connected run drove the covariance strictly down vs the prior (>=1 accept did work)
    assert run["final_det"] < run["prior_det"]


def test_covariance_is_monotone_nonincreasing_across_the_run():  # [REQ:FS-07]
    run = NL.run_nav_operational_loop(50.0, PRIOR_XY, PRIOR_COV, _mixed_observe, dh_m=DH_M, fx_px=FX_PX)
    dets = [run["prior_det"]] + [e["det_post"] for e in run["evidence"]]
    for a, b in zip(dets, dets[1:]):
        assert b <= a + 1e-12, "a stop must never inflate the covariance (accept reduces, reject holds)"


def test_all_stops_rejected_leaves_the_prior_untouched():  # [REQ:FS-07]
    # every stop sees collinear landmarks -> every fix rejected -> the graph gains no absolute factor and the
    # covariance equals the prior (the loop is honest: no evidence means no covariance reduction).
    run = NL.run_nav_operational_loop(50.0, PRIOR_XY, PRIOR_COV,
                                      lambda i, d: _COLLINEAR, dh_m=DH_M, fx_px=FX_PX)
    assert run["n_accepted"] == 0 and run["n_rejected"] == run["n_stops"]
    assert np.isclose(run["final_det"], run["prior_det"])
    assert all(not e["accepted"] and not e["inserted"] for e in run["evidence"])
