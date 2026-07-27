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

That ordering reduces to ``k * sigma_declared < tau`` -- the A5 resolvability condition with the
physics channel removed -- **in the symmetric case, where every source is equally over-confident.**

**Corrected 2026-07-27.** That is not the binding case. When only the candidate is over-confident and
its corroborator is honest, disagreement grows as ``sqrt(kappa^2+1)`` rather than as ``kappa``, so
detection is deferred to ``kappa = sqrt(2k^2-1)`` while the harm threshold does not move. The honest
condition is therefore ``sqrt(2k^2-1) * sigma_declared < tau``, and the symmetric form certifies
configurations that are in fact unsafe -- at ``k=4`` it says safe while the gate is harmed 12/20.
The A5 resemblance survives as an observation about the symmetric case, not as the condition.

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
    assert th["detect"] == pytest.approx(2.0)          # kappa = k
    assert th["harm"] == pytest.approx(5.0)            # kappa = tau / sigma_declared
    assert th["fails_safe"] == 1.0                     # 2.0 * 0.05 < 0.25
    with pytest.raises(ValueError):
        miscalibration_thresholds(0.0, TAU, 2.0)


def test_the_symmetric_condition_is_a5_without_the_physics_term_but_is_not_binding():
    """The A5 resemblance is real and was the first thing noticed; it is also not the whole story.

    ``k * sigma_o < tau`` is exactly A5 with ``sigma_p = 0``, and it governs the SYMMETRIC case. It
    does not govern the asymmetric one, where detection is deferred to ``sqrt(2k^2-1)``. Keeping the
    resemblance as an observation while denying it the status of the condition is the correction this
    file records."""
    for k in (1.0, 2.0, 4.0):
        th = miscalibration_thresholds(SIGMA_D, TAU, k)
        assert bool(th["fails_safe_symmetric_only"]) is bool(k * SIGMA_D < TAU)
        assert th["detect_symmetric"] == pytest.approx(k)
    # and the two verdicts diverge exactly where the correction bites
    assert miscalibration_thresholds(SIGMA_D, TAU, 4.0)["fails_safe_symmetric_only"] == 1.0
    assert miscalibration_thresholds(SIGMA_D, TAU, 4.0)["fails_safe"] == 0.0


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


# --------------------------------------------------------------------------------------------
# CORRECTION 2026-07-27. The symmetric condition alone is unsound.
#
# The first version of this family reported only the symmetric case and gave the fail-safe condition
# as k*sigma_declared < tau. Checking a doubt recorded in the previous iteration's journal -- that
# the thresholds were derived under equal declared sigmas and might move under unequal ones -- showed
# the condition is incomplete, and that certifying safety on it lets an unsafe configuration through.
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


def test_symmetric_condition_alone_certifies_an_unsafe_configuration():
    """The reason the condition had to be corrected, pinned as a regression.

    At k=4 the symmetric condition k*sigma_declared < tau holds (0.20 < 0.25) and would certify the
    configuration safe. The asymmetric detection threshold sqrt(2k^2-1)*sigma_declared = 0.279
    exceeds tau, so harm precedes detection, and the gate does accept harmful states."""
    th = miscalibration_thresholds(SIGMA_D, TAU, k_sigma=4.0)
    assert th["fails_safe_symmetric_only"] == 1.0, "the old condition must still say safe here"
    assert th["fails_safe"] == 0.0, "the corrected condition must say unsafe"
    truth = _truth()
    res = run_asymmetric_miscalibration_sweep(truth, [5.0], n_trials=20, sigma_declared=SIGMA_D,
                                              sigma_p=SIGMA_P, tau_m=TAU, k_sigma=4.0)
    assert res["gate"][0].n_harmful > 0, \
        "a configuration the old condition certified as safe must be shown to be unsafe"


def test_corrected_condition_is_the_asymmetric_one():
    """fails_safe now tracks the LATER detection threshold, since that is the binding case."""
    for k in (2.0, 3.0, 4.0, 5.0):
        th = miscalibration_thresholds(SIGMA_D, TAU, k)
        assert th["detect_asymmetric"] >= th["detect_symmetric"]
        assert th["fails_safe"] == float(th["detect_asymmetric"] < th["harm"])


def test_the_margin_narrows_and_then_inverts_with_gate_width():
    """Documents why a wide gate is not merely conservative: it defers detection faster than it
    defers harm, so past a point the ordering the whole fail-safe argument rests on reverses."""
    margins = [miscalibration_thresholds(SIGMA_D, TAU, k)["margin"] for k in (1.5, 2.0, 3.0, 4.0)]
    assert all(a > b for a, b in zip(margins, margins[1:])), "margin must shrink as k grows"
    assert margins[-1] < 1.0, "and invert before k=4"
