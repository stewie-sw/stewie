"""[F3] What does the rule do when a sensor lies about its precision?

The theorem assumes calibrated marginal error bounds. This controlled fault
family deliberately violates that assumption and measures the resulting
availability and harm.

The accepted-state repair invalidates the earlier threshold derivation. The
rule now accepts the mean of two observations, not one selected reading. For
two equally mis-calibrated sources, the square root of expected MSE reaches
``tau`` at ``kappa = sqrt(2) tau / sigma``. With one bad and one honest source it reaches
``tau`` at ``sqrt((2 tau / sigma)^2 - 1)``. The disagreement effect-size
crossovers remain ``k`` and ``sqrt(2 k^2 - 1)``. In both cases, detection
precedes the root-expected-MSE crossing exactly when
``k sigma < sqrt(2) tau``.

These are large-field root-expected-MSE crossovers for a controlled
effect-size knob, not ``E[RMS]``, deterministic safety thresholds, or
false-alarm probabilities. Their interpretation as overconfidence onsets uses
``k >= 1`` and an honest operating point at ``kappa = 1``; if
``tau <= sigma/sqrt(2)``, that honest two-source mean is already harmful in
root expected MSE.

Real Haworth terrain, controlled fault injection, twenty distinct trials per level.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from stewie.twin.veto_experiment import (
    miscalibration_thresholds,
    run_asymmetric_miscalibration_sweep,
    run_miscalibration_sweep,
)

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
    assert th["detect_symmetric"] == pytest.approx(2.0)
    assert th["detect_asymmetric"] == pytest.approx(np.sqrt(7.0))
    assert th["harm_symmetric"] == pytest.approx(np.sqrt(2.0) * TAU / SIGMA_D)
    assert th["harm_asymmetric"] == pytest.approx(
        np.sqrt((2.0 * TAU / SIGMA_D) ** 2 - 1.0)
    )
    assert th["honest_expected_safe"] == 1.0
    assert th["crossings_in_overconfidence_regime"] == 1.0
    assert th["expected_order_both"] == 1.0
    with pytest.raises(ValueError):
        miscalibration_thresholds(0.0, TAU, 2.0)
    with pytest.raises(ValueError, match="k_sigma"):
        miscalibration_thresholds(SIGMA_D, TAU, 0.9)


def test_no_positive_margin_is_reported_when_honest_expected_mse_is_harmful():
    th = miscalibration_thresholds(
        sigma_declared=0.50,
        tau_m=0.25,
        k_sigma=1.1,
    )

    assert th["honest_expected_safe"] == 0.0
    assert th["crossings_in_overconfidence_regime"] == 0.0
    assert th["expected_order_both"] == 0.0


def test_averaging_makes_the_two_expected_order_conditions_equivalent():
    """Squaring either crossover inequality gives ``k sigma < sqrt(2) tau``."""
    for k in (1.0, 2.0, 4.0, 8.0):
        th = miscalibration_thresholds(SIGMA_D, TAU, k)
        expected = bool(k * SIGMA_D < np.sqrt(2.0) * TAU)
        assert bool(th["expected_order_symmetric"]) is expected
        assert bool(th["expected_order_asymmetric"]) is expected


# --------------------------------------------------------------------------------------------
# Registered sweep when the detection-effect crossover comes first
# --------------------------------------------------------------------------------------------
def test_registered_sweep_has_no_harm_when_expected_order_is_detection_first():
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


def test_registered_zero_harm_is_bought_with_total_unavailability():
    """Past the measured threshold this sweep declines every trial."""
    truth = _truth()
    res = run_miscalibration_sweep(truth, [8.0], n_trials=20, sigma_declared=SIGMA_D,
                                   sigma_p=SIGMA_P, tau_m=TAU, k_sigma=2.0)
    g = res["gate"][0]
    assert g.abstain_rate == 1.0
    assert g.n_harmful == 0
    assert g.mean_error_m == pytest.approx(0.15, abs=1e-9)   # the retained prior, nothing fresher


# --------------------------------------------------------------------------------------------
# Reversing the expected crossover order exposes harm in this sweep
# --------------------------------------------------------------------------------------------
def test_reversing_the_expected_crossing_order_exposes_harmful_acceptance():
    """A wide effect-size gate admits harmful trials before disagreement dominates."""
    truth = _truth()
    th = miscalibration_thresholds(SIGMA_D, TAU, k_sigma=8.0)
    assert th["expected_order_both"] == 0.0
    symmetric = run_miscalibration_sweep(
        truth, [7.0], n_trials=20, sigma_declared=SIGMA_D,
        sigma_p=SIGMA_P, tau_m=TAU, k_sigma=8.0,
    )
    asymmetric = run_asymmetric_miscalibration_sweep(
        truth, [10.0], n_trials=20, sigma_declared=SIGMA_D,
        sigma_p=SIGMA_P, tau_m=TAU, k_sigma=8.0,
    )
    assert symmetric["gate"][0].n_harmful > 0
    assert asymmetric["gate"][0].n_harmful > 0


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


# --------------------------------------------------------------------------------------------
# CORRECTION 2026-07-28. The accepted-state mean moves both harm crossovers.
# --------------------------------------------------------------------------------------------
def test_asymmetric_detection_is_deferred_relative_to_symmetric():
    """One bad source among honest ones is HARDER to detect than all sources being equally bad,
    because the disagreement grows as sqrt(kappa^2+1) rather than as kappa."""
    truth = _truth()
    ks = [2.0, 2.5, 3.0]
    sym = run_miscalibration_sweep(truth, ks, n_trials=20, sigma_declared=SIGMA_D,
                                   sigma_p=SIGMA_P, tau_m=TAU, k_sigma=2.0)
    asym = run_asymmetric_miscalibration_sweep(truth, ks, n_trials=20, sigma_declared=SIGMA_D,
                                               sigma_p=SIGMA_P, tau_m=TAU, k_sigma=2.0)
    # symmetric is already declining at kappa = k; asymmetric is not
    assert sym["gate"][0].abstain_rate > 0.0
    assert asym["gate"][0].abstain_rate == 0.0
    assert sym["gate"][1].abstain_rate == 1.0
    assert asym["gate"][1].abstain_rate == 0.0
    # both have caught up by kappa = 3, which brackets the predicted sqrt(2k^2-1) = 2.65
    assert asym["gate"][2].abstain_rate == 1.0


def test_the_old_k4_asymmetric_counterexample_disappears_after_averaging():
    """The earlier unsafe-window claim depended on accepting the bad source whole."""
    th = miscalibration_thresholds(SIGMA_D, TAU, k_sigma=4.0)
    assert th["expected_order_symmetric"] == 1.0
    assert th["expected_order_asymmetric"] == 1.0
    truth = _truth()
    res = run_asymmetric_miscalibration_sweep(truth, [5.0], n_trials=20, sigma_declared=SIGMA_D,
                                              sigma_p=SIGMA_P, tau_m=TAU, k_sigma=4.0)
    assert res["gate"][0].n_harmful == 0


def test_both_regimes_change_order_at_the_same_gate_width():
    for k in (2.0, 4.0, 7.0, 8.0):
        th = miscalibration_thresholds(SIGMA_D, TAU, k)
        assert th["detect_asymmetric"] >= th["detect_symmetric"]
        assert th["expected_order_symmetric"] == th["expected_order_asymmetric"]


def test_the_margin_narrows_and_then_inverts_with_gate_width():
    """A wider effect-size gate eventually puts expected harm before detection."""
    margins = [
        miscalibration_thresholds(SIGMA_D, TAU, k)["margin"]
        for k in (1.5, 2.0, 4.0, 8.0)
    ]
    assert all(a > b for a, b in zip(margins, margins[1:])), "margin must shrink as k grows"
    assert margins[-1] < 1.0
