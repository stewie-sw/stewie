"""TDD for the latent VO-scale-bias state on the SE(2) pose graph (dart.pose_graph_se2).

A stereo-VO traverse has a per-traverse FORWARD-scale bias (the de-oracled a6 run measured the VO
UNDER-reading forward motion by ~10.8%). ``add_vo_between`` + ``estimate_vo_scale=True`` adds ONE shared
latent scalar ``s`` that multiplies every VO forward step, estimated jointly with the poses, so the bias
can be ABSORBED -- but only when the graph carries an independent absolute scale reference. These tests
pin three properties that bound the de-oracle experiment:

  1. OFF (the default), a vo_between is byte-identical to a plain between-factor (no behavior change).
  2. ON + an independent absolute (x,y) reference makes the scale OBSERVABLE: the solver recovers a known
     injected forward-scale error and the aligned ATE collapses.
  3. ON + only a single start anchor + relative VO (the truth-firewalled de-oracle condition) leaves the
     scale UNOBSERVABLE: the posterior collapses to the prior (s ~= 1.0). A latent scale state cannot
     manufacture an absolute scale the data does not carry -- the honest boundary.

Constructed straight-traverse geometry verifies the estimator MATH (no rover truth is fed to the VO; this
is the same controlled-characterization pattern dart.ablation / test_pose_graph_se2 use). The real-render
adjudication lives in the de-oracle artifact, not here.
"""
import math

import numpy as np

from dart import pose_graph_se2 as PG2


def _ate(est_xy, truth_xy):
    e = np.asarray(est_xy, float); g = np.asarray(truth_xy, float)
    return float(np.sqrt(np.mean(np.sum((e - g) ** 2, axis=1))))


def _straight_truth(n, step):
    """Truth: a straight body-forward traverse of n nodes, `step` m apart along +x (yaw 0)."""
    return np.column_stack([np.arange(n) * step, np.zeros(n)])


def test_vo_scale_off_is_identical_to_plain_between():
    """OFF (default): add_vo_between == add_between. Two graphs over the same straight VO chain --
    one built with add_vo_between (scale OFF), one with add_between -- optimize to the same poses."""
    n, vo_step = 8, 0.27
    ga = PG2.PoseGraphSE2()                                  # vo_between, estimate_vo_scale OFF
    gb = PG2.PoseGraphSE2()                                  # plain between
    ga.add_prior(0, (0.0, 0.0, 0.0), sigma_xy=0.02, sigma_yaw=0.02)
    gb.add_prior(0, (0.0, 0.0, 0.0), sigma_xy=0.02, sigma_yaw=0.02)
    for k in range(1, n):
        ga.add_vo_between(k - 1, k, (vo_step, 0.0, 0.0), sigma_xy=0.1, sigma_yaw=0.1)
        gb.add_between(k - 1, k, (vo_step, 0.0, 0.0), sigma_xy=0.1, sigma_yaw=0.1)
    ea, eb = ga.optimize(), gb.optimize()
    for k in range(n):
        assert ea[k] == eb[k] or np.allclose(ea[k], eb[k], atol=1e-9)
    # OFF -> the reported scale stays exactly 1.0 (the no-op invariant)
    res = ga.optimize_with_scale()
    assert res["vo_scale"] == 1.0 and res["scale_observable"] is False


def test_vo_scale_recovered_when_an_absolute_reference_makes_it_observable():
    """ON + an absolute (x,y) fix at the traverse end (the independent scale reference): the solver
    recovers a known injected forward-scale error and the ATE collapses vs the scale-OFF estimate.

    Inject a 10% UNDER-read: truth step 0.30 m, VO measures 0.27 m. The correcting scale is 0.30/0.27 =
    1.111. The end fix pins the true scale; the loose scale prior barely tugs."""
    n, truth_step, scale_true = 12, 0.30, 0.30 / 0.27
    vo_step = truth_step / scale_true                        # = 0.27, the VO's under-read forward step
    truth = _straight_truth(n, truth_step)

    # scale-OFF estimate (s fixed at 1.0): the under-read chain falls short -> large ATE
    g_off = PG2.PoseGraphSE2()
    g_off.add_prior(0, (truth[0, 0], truth[0, 1], 0.0), sigma_xy=0.02, sigma_yaw=0.02)
    for k in range(1, n):
        g_off.add_vo_between(k - 1, k, (vo_step, 0.0, 0.0), sigma_xy=0.1, sigma_yaw=0.1)
    g_off.add_absolute(n - 1, (truth[n - 1, 0], truth[n - 1, 1]), sigma=0.02)   # same reference, but s frozen
    e_off = g_off.optimize()
    ate_off = _ate([e_off[k][:2] for k in range(n)], truth)

    # scale-ON: the same graph, scale free, with the end fix as the absolute scale reference
    g_on = PG2.PoseGraphSE2(estimate_vo_scale=True)
    g_on.set_vo_scale_prior(mean=1.0, sigma=1.0)             # weak prior: let the data set the scale
    g_on.add_prior(0, (truth[0, 0], truth[0, 1], 0.0), sigma_xy=0.02, sigma_yaw=0.02)
    for k in range(1, n):
        g_on.add_vo_between(k - 1, k, (vo_step, 0.0, 0.0), sigma_xy=0.1, sigma_yaw=0.1)
    g_on.add_absolute(n - 1, (truth[n - 1, 0], truth[n - 1, 1]), sigma=0.02)
    res = g_on.optimize_with_scale()
    e_on = res["pose"]
    ate_on = _ate([e_on[k][:2] for k in range(n)], truth)

    assert res["scale_observable"] is True
    assert abs(res["vo_scale"] - scale_true) < 0.02         # recovered the injected 1.111 scale
    assert res["vo_scale_sigma"] is not None and res["vo_scale_sigma"] < 0.5   # tightened far below prior 1.0
    assert ate_on < 0.25 * ate_off                          # scale state collapses the residual drift
    assert ate_on < 0.02


def test_vo_scale_unobservable_from_single_anchor_and_relative_vo():
    """ON but ONLY a start anchor + relative VO (the truth-firewalled de-oracle condition): the scale is
    UNOBSERVABLE -- nothing in the graph carries an absolute metric scale -- so the posterior collapses to
    the prior (s ~= 1.0) and the under-read is NOT absorbed. This is the honest boundary the de-oracle long
    run is expected to hit."""
    n, truth_step, scale_true = 12, 0.30, 0.30 / 0.27
    vo_step = truth_step / scale_true                        # 0.27, a real 10% under-read

    g = PG2.PoseGraphSE2(estimate_vo_scale=True)
    g.set_vo_scale_prior(mean=1.0, sigma=0.2)
    g.add_prior(0, (0.0, 0.0, 0.0), sigma_xy=0.02, sigma_yaw=0.02)   # the ONLY absolute info (gauge)
    for k in range(1, n):
        g.add_vo_between(k - 1, k, (vo_step, 0.0, 0.0), sigma_xy=0.1, sigma_yaw=0.1)
    res = g.optimize_with_scale()

    assert res["scale_observable"] is False
    assert abs(res["vo_scale"] - 1.0) < 1e-3                 # collapses to the prior mean; no absorption
    # its 1-sigma stays at the prior sigma (the data did not tighten it)
    assert res["vo_scale_sigma"] is not None
    assert res["vo_scale_sigma"] > 0.18                      # ~ the 0.2 prior sigma, not tightened
