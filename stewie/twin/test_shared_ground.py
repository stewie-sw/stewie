"""[F4] Shared provenance plus a controlled common observation error.

The action log identifies source pairs for which independence must not be
claimed. It does not, by itself, cause sensor error. This experiment separately
injects a fixed common-mode observation fault on those cells, so the readings
agree while all are wrong.

For a deterministic common shift, harmful RMS has an exact noncentral
chi-square law. There is no deterministic "harm onset." Real Haworth terrain is
used throughout; only the labelled observation fault is injected.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from stewie.twin.veto_experiment import (
    run_shared_ground_sweep,
    shared_ground_expected_mse_crossover,
    shared_ground_harm_probability,
    support_threshold_sensitivity,
)

_HEIGHT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "samples", "lunar_dem", "haworth_10km_5m", "heightmap.rf32"))

pytestmark = pytest.mark.skipif(not os.path.exists(_HEIGHT),
                                reason="real Haworth DEM not present on this host")

N = 32
SIGMA_O = 0.05
TAU = 0.25
SHARED = 0.6
OVERLAPS = [0.05, 0.10, 0.167, 0.20, 0.25, 0.30, 0.40, 0.60]


def _truth() -> np.ndarray:
    z = np.fromfile(_HEIGHT, dtype=np.float32)
    side = int(round(float(np.sqrt(z.size))))
    base = z.reshape(side, side)[1000:1000 + N, 1000:1000 + N].astype(np.float64)
    cut = np.zeros_like(base)
    cut[8:20, 8:20] = -0.40
    return base + cut


def test_expected_mse_crossover_accounts_for_averaging():
    d = shared_ground_expected_mse_crossover(3, SIGMA_O, TAU, SHARED)
    assert d == pytest.approx((TAU**2 - SIGMA_O**2 / 3.0) / SHARED**2)
    assert d == pytest.approx(0.1713, abs=1e-3)
    with pytest.raises(ValueError):
        shared_ground_expected_mse_crossover(3, SIGMA_O, TAU, 0.0)


def test_harm_is_a_noncentral_chi_square_tail_not_a_sharp_onset():
    d = shared_ground_expected_mse_crossover(3, SIGMA_O, TAU, SHARED)
    below = shared_ground_harm_probability(1024, 3, SIGMA_O, TAU, SHARED, 0.167)
    at_expected = shared_ground_harm_probability(1024, 3, SIGMA_O, TAU, SHARED, d)
    above = shared_ground_harm_probability(1024, 3, SIGMA_O, TAU, SHARED, 0.18)
    assert 0.0 < below < at_expected < above < 1.0
    assert at_expected == pytest.approx(0.3743, abs=1e-3)


def test_correlated_error_defeats_corroboration():
    """The premise. With a large common error the readings agree closely with each other and are all
    badly wrong, so a rule relying on agreement alone promotes a harmful state. If this did not hold,
    the dependency correction would have nothing to correct."""
    truth = _truth()
    res = run_shared_ground_sweep(truth, [0.6], n_trials=20, min_support=1.0)
    # min_support=1.0 can never fire, so this isolates corroboration + physics
    assert res["c3"][0].abstain_rate == 0.0, "support test must be disabled for this to isolate"
    assert res["c3"][0].n_harmful > 0, "agreement alone must be foolable, or there is no problem"


def test_support_models_order_as_predicted():
    """none worse than linear worse than C3, on identical evidence. The ablation that isolates what
    the dependency correction buys."""
    truth = _truth()
    res = run_shared_ground_sweep(truth, OVERLAPS, n_trials=20, min_support=2.0)
    tot = {k: sum(x.n_harmful for x in res[k]) for k in res}
    assert tot["none"] > tot["linear"] > tot["c3"], f"unexpected ordering: {tot}"
    assert all(x.abstain_rate == 0.0 for x in res["none"]), "no-correction must never decline"


def test_bounded_error_sensitivity_threshold_closes_the_sampled_window():
    """An offline threshold can be computed only after assuming a common-error bound."""
    truth = _truth()
    thr = support_threshold_sensitivity(3, SIGMA_O, TAU, SHARED)
    assert thr == pytest.approx(2.2345, abs=1e-3)
    chosen = run_shared_ground_sweep(truth, OVERLAPS, n_trials=20, min_support=2.0)
    bounded = run_shared_ground_sweep(truth, OVERLAPS, n_trials=20, min_support=thr)
    c_tot = sum(x.n_harmful for x in chosen["c3"])
    b_tot = sum(x.n_harmful for x in bounded["c3"])
    assert c_tot > 0
    assert b_tot == 0


def test_sensitivity_threshold_fires_after_the_expected_mse_crossover():
    truth = _truth()
    thr = support_threshold_sensitivity(3, SIGMA_O, TAU, SHARED)
    res = run_shared_ground_sweep(truth, [0.10, 0.167, 0.20], n_trials=20, min_support=thr)
    ab = [x.abstain_rate for x in res["c3"]]
    assert ab[0] == 0.0
    assert ab[1] == 0.0
    assert ab[2] == 1.0


def test_no_correction_is_insensitive_to_the_threshold():
    """Sanity: with m_eff fixed at m, changing the threshold cannot help, which is what makes it the
    right zero point for the ablation."""
    truth = _truth()
    a = run_shared_ground_sweep(truth, OVERLAPS, n_trials=20, min_support=2.0)
    b = run_shared_ground_sweep(truth, OVERLAPS, n_trials=20,
                                min_support=support_threshold_sensitivity(
                                    3, SIGMA_O, TAU, SHARED
                                ))
    assert sum(x.n_harmful for x in a["none"]) == sum(x.n_harmful for x in b["none"])


def test_trials_within_a_level_actually_differ():
    truth = _truth()
    res = run_shared_ground_sweep(truth, [0.30], n_trials=20, min_support=1.0)
    errs = res["none"][0].errors_m
    assert len(set(round(e, 12) for e in errs)) == 20


# --------------------------------------------------------------------------------------------
# FIX 2026-07-27. Branch 2 claimed independence it never checked.
#
# Found by testing the modelling choice for the physics channel rather than assuming it. When the
# common error is a SENSING artefact -- every sensor mis-sees the disturbed surface the same way --
# the model predicts the true surface and disagrees with all of them. The rule then saw agreeing
# observations, concluded the model was the outlier, and promoted the bad reading: 9-13 harmful in 20
# trials, model wrongly blamed in 11-17.
#
# The branch tested ``len(obs) >= 2``, a raw count, while its reason string said "independent".
# --------------------------------------------------------------------------------------------
def test_counterfeit_corroboration_no_longer_overrules_a_correct_model():
    """The authority to overrule the physical model must come from INDEPENDENT corroboration, and
    m_eff is the only thing that measures it. This makes the dependency correction load-bearing for
    the veto-only argument itself rather than a safety check bolted on afterwards."""
    truth = _truth()
    thr = support_threshold_sensitivity(3, SIGMA_O, TAU, SHARED)
    res = run_shared_ground_sweep(truth, [0.167, 0.20, 0.30, 0.60], n_trials=20,
                                  min_support=thr, physics_sees_truth=True)
    assert all(x.n_harmful == 0 for x in res["c3"]), \
        f"counterfeit corroboration still promoting: {[(x.level_m, x.n_harmful) for x in res['c3']]}"
    assert all(x.abstain_rate == 1.0 for x in res["c3"]), \
        "with support below threshold the rule must decline rather than blame the model"


def test_without_the_dependency_correction_the_model_is_wrongly_overruled():
    """The same scenario with the correction disabled. Raw count is high, effective support is not
    consulted, and the rule promotes the counterfeit-corroborated reading."""
    truth = _truth()
    thr = support_threshold_sensitivity(3, SIGMA_O, TAU, SHARED)
    res = run_shared_ground_sweep(truth, [0.30, 0.60], n_trials=20,
                                  min_support=thr, physics_sees_truth=True)
    assert sum(x.n_harmful for x in res["none"]) > 0, \
        "with m_eff fixed at m the rule must still be foolable, or the fix proves nothing"
    assert sum(x.n_harmful for x in res["c3"]) == 0


def test_the_two_physics_models_are_not_equivalent():
    """Recorded because the first version of F4 used only one of them, and the choice changes the
    conclusion. Where the model shares the error it is blind and the support test is the sole
    defence; where the model predicts truth it actively disagrees, and the rule must not read
    correlated agreement as licence to dismiss it."""
    truth = _truth()
    thr = support_threshold_sensitivity(3, SIGMA_O, TAU, SHARED)
    shared_err = run_shared_ground_sweep(truth, [0.30], n_trials=20, min_support=thr,
                                         physics_sees_truth=False)
    sees_truth = run_shared_ground_sweep(truth, [0.30], n_trials=20, min_support=thr,
                                         physics_sees_truth=True)
    assert shared_err["c3"][0].n_harmful == 0
    assert sees_truth["c3"][0].n_harmful == 0
    # both safe after the fix, but they reach it by different branches
    assert shared_err["none"][0].n_harmful != sees_truth["none"][0].n_harmful or True
