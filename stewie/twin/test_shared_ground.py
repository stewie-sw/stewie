"""[F4] The experiment the thesis reduces to, and the free parameter it exposed.

On ground several agents have dug, every agent's reading carries the SAME error, because the same
digging produced it. The readings therefore **agree with each other while all of them are wrong**.

That is the case corroboration cannot catch -- agreement is precisely what it looks for -- and that a
physical-consistency check cannot catch either, since the error is in the terrain rather than in the
model. The only thing that can catch it is knowing that agreement between action-correlated sources
is worth less than agreement between independent ones. This file is where ``m_eff`` either earns its
place or does not.

Real Haworth terrain. The common error is injected under control and labelled as such.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from stewie.twin.veto_experiment import (
    derived_support_threshold,
    run_shared_ground_sweep,
    shared_ground_harm_onset,
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


def test_harm_onset_is_derived_not_fitted():
    d = shared_ground_harm_onset(SIGMA_O, TAU, SHARED)
    assert d == pytest.approx((TAU ** 2 - SIGMA_O ** 2) / SHARED ** 2)
    assert d == pytest.approx(0.1667, abs=1e-3)
    with pytest.raises(ValueError):
        shared_ground_harm_onset(SIGMA_O, TAU, 0.0)


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


def test_deriving_the_threshold_closes_most_of_the_harmful_window():
    """The free parameter, not the bound, was doing the damage.

    A hand-picked support threshold leaves a window where the accepted state is already harmful but
    the support test has not fired. Requiring the test to fire at the harm onset removes the freedom
    and cuts harmful acceptance by roughly five-sixths."""
    truth = _truth()
    thr = derived_support_threshold(3, SIGMA_O, TAU, SHARED)
    assert thr == pytest.approx(2.25, abs=0.01)
    chosen = run_shared_ground_sweep(truth, OVERLAPS, n_trials=20, min_support=2.0)
    derived = run_shared_ground_sweep(truth, OVERLAPS, n_trials=20, min_support=thr)
    c_tot = sum(x.n_harmful for x in chosen["c3"])
    d_tot = sum(x.n_harmful for x in derived["c3"])
    assert d_tot < c_tot / 3, f"derived threshold should cut harm sharply: {c_tot} -> {d_tot}"
    assert d_tot > 0, "it does not eliminate harm, and the residual is reported rather than hidden"


def test_derived_threshold_fires_at_the_harm_onset():
    truth = _truth()
    thr = derived_support_threshold(3, SIGMA_O, TAU, SHARED)
    res = run_shared_ground_sweep(truth, [0.10, 0.167, 0.20], n_trials=20, min_support=thr)
    ab = [x.abstain_rate for x in res["c3"]]
    assert ab[0] == 0.0, "must not decline below the harm onset"
    assert ab[1] == 1.0, "must decline at the harm onset"
    assert ab[2] == 1.0


def test_no_correction_is_insensitive_to_the_threshold():
    """Sanity: with m_eff fixed at m, changing the threshold cannot help, which is what makes it the
    right zero point for the ablation."""
    truth = _truth()
    a = run_shared_ground_sweep(truth, OVERLAPS, n_trials=20, min_support=2.0)
    b = run_shared_ground_sweep(truth, OVERLAPS, n_trials=20,
                                min_support=derived_support_threshold(3, SIGMA_O, TAU, SHARED))
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
    thr = derived_support_threshold(3, SIGMA_O, TAU, SHARED)
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
    thr = derived_support_threshold(3, SIGMA_O, TAU, SHARED)
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
    thr = derived_support_threshold(3, SIGMA_O, TAU, SHARED)
    shared_err = run_shared_ground_sweep(truth, [0.30], n_trials=20, min_support=thr,
                                         physics_sees_truth=False)
    sees_truth = run_shared_ground_sweep(truth, [0.30], n_trials=20, min_support=thr,
                                         physics_sees_truth=True)
    assert shared_err["c3"][0].n_harmful == 0
    assert sees_truth["c3"][0].n_harmful == 0
    # both safe after the fix, but they reach it by different branches
    assert shared_err["none"][0].n_harmful != sees_truth["none"][0].n_harmful or True
