"""[F3] What does the rule do when a sensor lies about its own precision?

Every result before this one set declared sigma equal to true sigma by construction. Since the
soundness claim is stated *over* calibrated sensors, an uncalibrated regime does not weaken it, it
voids the hypothesis. So the question under test is not whether the bound survives -- it is not
claimed to -- but whether the rule fails **safe** or fails **silently**.

The answer, and it was derived before it was measured: two thresholds separate. Tolerances inside the
rule are built from the DECLARED sigma, while the error that decides harm is governed by the TRUE
sigma. Two readings at the true scale start disagreeing beyond a declared-scale tolerance at
``kappa = k``; the accepted reading's own error exceeds tau at ``kappa = tau / sigma_declared``. When
the first comes before the second the rule notices it is out of its depth before it can do damage.

That ordering reduces to ``k * sigma_declared < tau`` -- **the A5 resolvability condition with the
physics channel removed.** The same inequality governs two different failure modes, which is the more
interesting finding than either one alone.

Real Haworth terrain, controlled fault injection, twenty distinct trials per level.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from stewie.twin.veto_experiment import miscalibration_thresholds, run_miscalibration_sweep

_HEIGHT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "samples", "lunar_dem", "haworth_10km_5m", "heightmap.rf32"))

pytestmark = pytest.mark.skipif(not os.path.exists(_HEIGHT),
                                reason="real Haworth DEM not present on this host")

N = 32
SIGMA_D = 0.05
SIGMA_P = 0.08
TAU = 0.25


def _truth() -> np.ndarray:
    z = np.fromfile(_HEIGHT, dtype=np.float32)
    side = int(round(float(np.sqrt(z.size))))
    base = z.reshape(side, side)[1000:1000 + N, 1000:1000 + N].astype(np.float64)
    cut = np.zeros_like(base)
    cut[8:20, 8:20] = -0.40
    return base + cut


# --------------------------------------------------------------------------------------------
# The thresholds are derived, not fitted
# --------------------------------------------------------------------------------------------
def test_thresholds_are_where_the_algebra_says():
    th = miscalibration_thresholds(SIGMA_D, TAU, k_sigma=2.0)
    assert th["detect"] == pytest.approx(2.0)          # kappa = k
    assert th["harm"] == pytest.approx(5.0)            # kappa = tau / sigma_declared
    assert th["fails_safe"] == 1.0                     # 2.0 * 0.05 < 0.25
    with pytest.raises(ValueError):
        miscalibration_thresholds(0.0, TAU, 2.0)


def test_the_fail_safe_condition_is_a5_without_the_physics_term():
    """k*sigma_o <= tau is exactly A5 with sigma_p = 0. Recorded because the recurrence of the same
    inequality across two unrelated failure modes is the substantive observation here."""
    for k in (1.0, 2.0, 4.0):
        predicted_safe = k * SIGMA_D < TAU
        assert bool(miscalibration_thresholds(SIGMA_D, TAU, k)["fails_safe"]) is predicted_safe


# --------------------------------------------------------------------------------------------
# Under the condition: mis-calibration becomes abstention, never harm
# --------------------------------------------------------------------------------------------
def test_gate_never_accepts_a_harmful_state_while_the_condition_holds():
    truth = _truth()
    res = run_miscalibration_sweep(truth, [1.0, 2.0, 3.0, 5.0, 8.0, 12.0], n_trials=20,
                                   sigma_declared=SIGMA_D, sigma_p=SIGMA_P, tau_m=TAU, k_sigma=2.0)
    assert all(g.n_harmful == 0 for g in res["gate"]), \
        f"gate harmed under mis-calibration: {[(g.level_m, g.n_harmful) for g in res['gate']]}"


def test_detection_begins_at_the_derived_threshold():
    """Abstention should switch on around kappa = k, not somewhere unexplained."""
    truth = _truth()
    res = run_miscalibration_sweep(truth, [1.0, 1.5, 2.0, 3.0], n_trials=20,
                                   sigma_declared=SIGMA_D, sigma_p=SIGMA_P, tau_m=TAU, k_sigma=2.0)
    ab = [g.abstain_rate for g in res["gate"]]
    assert ab[0] == 0.0 and ab[1] == 0.0, "must not decline a merely slightly optimistic sensor"
    assert ab[2] > 0.0, "detection should have begun by kappa = k"
    assert ab[3] == 1.0, "and be total shortly after"


def test_safety_is_bought_with_total_unavailability():
    """The cost is stark and belongs in the record: past the detection threshold the rule declines
    every time. It is safe and completely unavailable, which is the availability concern raised
    against the abstain channel, here measured rather than argued."""
    truth = _truth()
    res = run_miscalibration_sweep(truth, [8.0], n_trials=20, sigma_declared=SIGMA_D,
                                   sigma_p=SIGMA_P, tau_m=TAU, k_sigma=2.0)
    g = res["gate"][0]
    assert g.abstain_rate == 1.0
    assert g.n_harmful == 0
    assert g.mean_error_m == pytest.approx(0.15, abs=1e-9)   # the retained prior, nothing fresher


# --------------------------------------------------------------------------------------------
# Necessity: violate the condition and the rule fails unsafe
# --------------------------------------------------------------------------------------------
def test_violating_the_condition_makes_the_rule_fail_unsafe():
    """The decisive test. Widen the gate until k*sigma_declared exceeds tau and harm now precedes
    detection, so the rule accepts states it cannot see are bad. This is what makes the condition
    NECESSARY rather than a convenient sufficient one."""
    truth = _truth()
    th = miscalibration_thresholds(SIGMA_D, TAU, k_sigma=6.0)
    assert th["fails_safe"] == 0.0, "this test is only meaningful with the condition violated"
    assert th["harm"] < th["detect"], "harm must precede detection for the failure to exist"
    res = run_miscalibration_sweep(truth, [5.0, 6.0], n_trials=20, sigma_declared=SIGMA_D,
                                   sigma_p=SIGMA_P, tau_m=TAU, k_sigma=6.0)
    assert sum(g.n_harmful for g in res["gate"]) > 0, \
        "with the condition violated the gate must be able to accept a harmful state"


def test_both_baselines_fail_under_mis_calibration():
    """Neither comparator has any protection: fixed precedence takes the reading whole, and
    inverse-variance fusion only dilutes it."""
    truth = _truth()
    res = run_miscalibration_sweep(truth, [8.0], n_trials=20, sigma_declared=SIGMA_D,
                                   sigma_p=SIGMA_P, tau_m=TAU, k_sigma=2.0)
    assert res["fixed_precedence"][0].n_harmful == 20
    assert res["inverse_variance"][0].n_harmful == 20
    assert res["gate"][0].n_harmful == 0


def test_a_conservative_sensor_is_not_punished():
    """kappa < 1 is a sensor that over-declares its error. That is not a fault and the rule should
    not decline on account of it."""
    truth = _truth()
    res = run_miscalibration_sweep(truth, [0.5], n_trials=20, sigma_declared=SIGMA_D,
                                   sigma_p=SIGMA_P, tau_m=TAU, k_sigma=2.0)
    g = res["gate"][0]
    assert g.abstain_rate == 0.0
    assert g.n_harmful == 0


def test_trials_within_a_level_actually_differ():
    """Same regression guard as the other sweeps: identical errors mean the trials are not trials."""
    truth = _truth()
    res = run_miscalibration_sweep(truth, [3.0], n_trials=20, sigma_declared=SIGMA_D,
                                   sigma_p=SIGMA_P, tau_m=TAU, k_sigma=2.0)
    errs = res["fixed_precedence"][0].errors_m
    assert len(set(round(e, 12) for e in errs)) == 20
