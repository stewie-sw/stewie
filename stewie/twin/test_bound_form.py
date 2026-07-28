"""Does the soundness bound's stated FORM survive contact with the measurements?

The conjecture is written

    Pr[accept AND ||x_hat - x*|| > tau]  <=  alpha(k, m_eff, sigma_o)

with alpha independent of the model bias b. This file tests something more basic than whether alpha
exists: whether a function of those three arguments *could* bound harm at all.

It cannot. Holding ``m_eff`` fixed and varying only the magnitude of the common error moves harmful
acceptance from 0 to 18 in 20 trials. A function of ``(k, m_eff, sigma_o)`` takes the same value in
every one of those runs, so no such function is an upper bound on all of them.

**Why the derivation looked sound and was not.** ``m_eff`` is derived as an effective sample size:
the number of independent observations whose MEAN would have the variance the correlated ensemble's
mean has. The acceptance rule never computes that mean. It accepts a single reading, whose error is
governed by its own noise plus whatever common component the shared digging introduced. The quantity
was derived for an estimator the rule does not use.

**What this does not overturn.** ``m_eff`` still does the job the licensing finding identified: it
gates the branch on which corroborating observations are allowed to overrule a disagreeing physical
model. That role is about *authority to override*, not about bounding an error, and nothing here
touches it. What fails is the claim that harm is a function of it.

**The missing quantity** is the magnitude of the common error, which is the same quantity the derived
support threshold needs and which a deployed system cannot observe. Two gaps that were recorded
separately are one gap.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from stewie.twin.effective_support import conservative_effective_support
from stewie.twin.veto_experiment import run_shared_ground_sweep

_HEIGHT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "samples", "lunar_dem", "haworth_10km_5m", "heightmap.rf32"))

pytestmark = pytest.mark.skipif(not os.path.exists(_HEIGHT),
                                reason="real Haworth DEM not present on this host")

N = 32


def _truth() -> np.ndarray:
    z = np.fromfile(_HEIGHT, dtype=np.float32)
    side = int(round(float(np.sqrt(z.size))))
    base = z.reshape(side, side)[1000:1000 + N, 1000:1000 + N].astype(np.float64)
    cut = np.zeros_like(base)
    cut[8:20, 8:20] = -0.40
    return base + cut


def test_harm_varies_widely_at_constant_m_eff():
    """The decisive measurement. Same m, same d, therefore the same m_eff to every decimal place;
    only the common-error magnitude changes. Harmful acceptance spans nearly the whole range.

    ``min_support=1.0`` keeps the support test from ever firing, so this isolates the question of
    what harm depends on rather than measuring the rule's response to it."""
    truth = _truth()
    d, m = 0.30, 3
    fixed = conservative_effective_support(m, d)
    harms = []
    for shared in (0.2, 0.6, 1.0):
        r = run_shared_ground_sweep(truth, [d], n_trials=20, shared_error_m=shared,
                                    min_support=1.0)["c3"][0]
        harms.append(r.n_harmful)
    assert fixed == pytest.approx(1.875, abs=1e-3)
    assert harms[0] < harms[-1], "harm must move while m_eff does not"
    assert harms[-1] - harms[0] >= 10, f"expected a wide spread at fixed m_eff, got {harms}"


def test_no_function_of_m_eff_alone_can_bound_these():
    """Stated as the implication rather than left to the reader. Two runs share every argument the
    conjectured alpha takes, and differ in outcome, so alpha cannot be an upper bound on both."""
    truth = _truth()
    d, m = 0.30, 3
    low = run_shared_ground_sweep(truth, [d], n_trials=20, shared_error_m=0.2,
                                  min_support=1.0)["c3"][0]
    high = run_shared_ground_sweep(truth, [d], n_trials=20, shared_error_m=1.0,
                                   min_support=1.0)["c3"][0]
    # identical (k, m_eff, sigma_o) in both runs
    assert conservative_effective_support(m, d) == conservative_effective_support(m, d)
    assert low.n_harmful < high.n_harmful
    assert high.n_harmful >= 15, "the high-common-error case must be badly harmful"


def test_the_accepted_state_is_one_reading_not_a_mean():
    """The root of the mismatch, as a property rather than a comment. The effective-sample-size
    derivation is about the variance of a mean of m readings; the rule accepts a single reading."""
    truth = _truth()
    # with no common error the accepted state's error is its own noise, whatever m_eff says
    quiet = run_shared_ground_sweep(truth, [0.0], n_trials=20, shared_error_m=0.6,
                                    min_support=1.0)["c3"][0]
    shared = run_shared_ground_sweep(truth, [1.0], n_trials=20, shared_error_m=0.6,
                                     min_support=1.0)["c3"][0]
    assert conservative_effective_support(3, 0.0) == pytest.approx(3.0)
    assert conservative_effective_support(3, 1.0) == pytest.approx(1.0)
    # a threefold change in m_eff, and the accepted error is driven by the common term instead
    assert quiet.mean_error_m < shared.mean_error_m


def test_the_licensing_role_of_m_eff_is_untouched_by_this():
    """Scope of the correction, pinned so it is not over-read. m_eff still gates the branch where
    corroboration overrules a disagreeing model, and that role is about authority rather than about
    bounding an error. Disabling the correction still lets counterfeit corroboration through."""
    truth = _truth()
    thr = 2.25
    with_corr = run_shared_ground_sweep(truth, [0.60], n_trials=20, min_support=thr,
                                        physics_sees_truth=True)
    assert with_corr["c3"][0].n_harmful == 0
    assert with_corr["none"][0].n_harmful > 0
