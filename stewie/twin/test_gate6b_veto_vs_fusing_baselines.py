"""[GATE6B] Does the veto-only channel actually buy anything a fusing baseline does not?

The earlier gate-6 comparison could not answer this, because its only comparator ignored the physics
channel entirely and was therefore immune to model bias for a trivial reason. These tests add the
comparator that uses the model, and check the claim that motivates the whole design:

    a system may be immune to model bias by ignoring the model, or it may exploit the model and
    inherit its bias -- and vetoing with the model without ever constructing from it gets both.

The headline is ``test_neither_baseline_is_safe_in_both_conditions``. Everything else supports it.

Real Haworth LOLA terrain; injected faults under control; every trial seeded differently, which the
regression guard at the bottom enforces.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from stewie.twin.baselines import (
    confidence_weighted,
    covariance_intersection,
    inverse_variance_fusion,
    last_write_wins,
    prediction_weight,
)
from stewie.twin.veto_experiment import (
    analytic_bias_crossing_m,
    detection_band_m,
    analytic_fault_crossing_m,
    run_model_bias_sweep,
    run_sensor_fault_sweep,
)

_HEIGHT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "samples", "lunar_dem", "haworth_10km_5m", "heightmap.rf32"))

pytestmark = pytest.mark.skipif(not os.path.exists(_HEIGHT),
                                reason="real Haworth DEM not present on this host")

N = 32
SIGMA_O = 0.05
SIGMA_P = 0.08
TAU_M = 0.25


def _truth() -> np.ndarray:
    z = np.fromfile(_HEIGHT, dtype=np.float32)
    side = int(round(float(np.sqrt(z.size))))
    base = z.reshape(side, side)[1000:1000 + N, 1000:1000 + N].astype(np.float64)
    cut = np.zeros_like(base)
    cut[8:20, 8:20] = -0.40
    return base + cut


# --------------------------------------------------------------------------------------------
# The comparators behave as their theory says. Without this the sweep proves nothing.
# --------------------------------------------------------------------------------------------
def test_prediction_weight_matches_closed_form():
    w = prediction_weight(SIGMA_O, SIGMA_P)
    expected = (1 / SIGMA_P ** 2) / (1 / SIGMA_O ** 2 + 1 / SIGMA_P ** 2)
    assert abs(w - expected) < 1e-12
    assert 0.0 < w < 1.0


def test_inverse_variance_absorbs_exactly_prediction_weight_of_a_bias():
    """A pure bias with no noise must pass through at exactly the analytic weight."""
    truth = _truth()
    b = 1.0
    fused = inverse_variance_fusion(truth, SIGMA_O, truth + b, SIGMA_P).values
    err = float(np.sqrt(np.mean((fused - truth) ** 2)))
    assert abs(err - prediction_weight(SIGMA_O, SIGMA_P) * b) < 1e-9


def test_trace_optimal_covariance_intersection_degenerates_to_the_observation():
    """Documented caveat, not a bug: with a scalar variance the trace objective is linear in omega,
    so CI puts all weight on the lower-variance source and cannot use the model at all."""
    truth = _truth()
    ci = covariance_intersection(truth, SIGMA_O, truth + 5.0, SIGMA_P).values
    assert np.allclose(ci, truth)


def test_covariance_intersection_at_half_omega_coincides_with_inverse_variance():
    """At omega=0.5 the weights cancel to the inverse-variance weights exactly. Recorded so the two
    comparators are not mistaken for independent evidence about the same claim."""
    truth = _truth()
    p = truth + 0.6
    a = covariance_intersection(truth, SIGMA_O, p, SIGMA_P, omega=0.5).values
    b = inverse_variance_fusion(truth, SIGMA_O, p, SIGMA_P).values
    assert np.allclose(a, b)


def test_last_write_wins_and_confidence_weighted():
    truth = _truth()
    late = truth + 1.0
    assert np.allclose(last_write_wins(truth, [(1.0, truth - 1.0), (2.0, late)]), late)
    cw = confidence_weighted([(truth, 3.0), (truth + 1.0, 1.0)])
    assert np.allclose(cw, truth + 0.25)
    with pytest.raises(ValueError):
        confidence_weighted([])


# --------------------------------------------------------------------------------------------
# Condition A: model bias. The fusing baseline degrades; the gate does not.
# --------------------------------------------------------------------------------------------
def test_condition_a_inverse_variance_degrades_with_bias_and_the_gate_does_not():
    truth = _truth()
    biases = [0.0, 0.5, 1.0, 2.0, 4.0]
    res = run_model_bias_sweep(truth, biases, n_trials=20, sigma_o=SIGMA_O, sigma_p=SIGMA_P, tau_m=TAU_M)

    iv = res["inverse_variance"]
    assert iv[0].n_harmful == 0, "no bias should be safe for the fusing baseline"
    assert iv[-1].n_harmful == 20, "a 4 m bias must break the fusing baseline in every trial"
    assert all(a.mean_error_m <= b.mean_error_m + 1e-9 for a, b in zip(iv, iv[1:])), \
        "fusing error must be monotone in the bias"

    gate = res["gate"]
    assert all(g.n_harmful == 0 for g in gate), \
        f"gate accepted a harmful state under bias: {[(g.level_m, g.n_harmful) for g in gate]}"
    assert max(g.mean_error_m for g in gate) - min(g.mean_error_m for g in gate) < 0.01, \
        "gate error must be flat in the model bias -- this is the veto-only claim"


def test_condition_a_sweep_crossing_matches_the_closed_form():
    """The measured crossing must agree with tau / prediction_weight. Agreement is what shows the
    sweep measures the mechanism rather than a seeding artefact."""
    truth = _truth()
    crossing = analytic_bias_crossing_m(SIGMA_O, SIGMA_P, TAU_M)
    below, above = crossing - 0.15, crossing + 0.15
    res = run_model_bias_sweep(truth, [below, above], n_trials=20,
                               sigma_o=SIGMA_O, sigma_p=SIGMA_P, tau_m=TAU_M)
    assert res["inverse_variance"][0].n_harmful == 0, f"should be safe below {crossing:.3f} m"
    assert res["inverse_variance"][1].n_harmful == 20, f"should be harmful above {crossing:.3f} m"


# --------------------------------------------------------------------------------------------
# Condition B: sensor fault. Fixed precedence degrades; the gate abstains.
# --------------------------------------------------------------------------------------------
def test_condition_b_fixed_precedence_degrades_with_fault_and_the_gate_abstains():
    truth = _truth()
    offsets = [0.0, 0.3, 0.6, 1.2]
    res = run_sensor_fault_sweep(truth, offsets, n_trials=20,
                                 sigma_o=SIGMA_O, sigma_p=SIGMA_P, tau_m=TAU_M)

    fp = res["fixed_precedence"]
    assert fp[0].n_harmful == 0
    assert fp[-1].n_harmful == 20, "a 1.2 m sensor fault must break fixed precedence every time"

    gate = res["gate"]
    assert all(g.n_harmful == 0 for g in gate), \
        f"gate accepted a faulty observation: {[(g.level_m, g.n_harmful) for g in gate]}"
    assert gate[-1].n_abstained == 20, "the gate must decline the large fault, not guess"
    assert gate[0].n_abstained == 0, "the gate must not decline clean evidence"


def test_condition_b_fusing_baseline_also_fails_just_later():
    """Partial trust in the model buys partial protection from a sensor fault, and no more."""
    truth = _truth()
    crossing = analytic_fault_crossing_m(SIGMA_O, SIGMA_P, TAU_M)
    assert crossing > TAU_M, "fusing must tolerate a larger fault than fixed precedence"
    res = run_sensor_fault_sweep(truth, [crossing + 0.2], n_trials=20,
                                 sigma_o=SIGMA_O, sigma_p=SIGMA_P, tau_m=TAU_M)
    assert res["inverse_variance"][0].n_harmful == 20


# --------------------------------------------------------------------------------------------
# The headline.
# --------------------------------------------------------------------------------------------
def test_neither_baseline_is_safe_in_both_conditions():
    """Each baseline is safe in exactly one condition and unsafe in the other; the gate is safe in
    both. This is the claim the veto-only channel exists to support, and the reason a comparator
    that ignores physics could never have tested it."""
    truth = _truth()
    a = run_model_bias_sweep(truth, [4.0], n_trials=20, sigma_o=SIGMA_O, sigma_p=SIGMA_P, tau_m=TAU_M)
    b = run_sensor_fault_sweep(truth, [1.2], n_trials=20, sigma_o=SIGMA_O, sigma_p=SIGMA_P, tau_m=TAU_M)

    # fixed precedence: survives model bias only because it never reads the model
    assert a["fixed_precedence"][0].n_harmful == 0
    assert b["fixed_precedence"][0].n_harmful == 20
    # inverse-variance fusion: reads the model, and inherits its bias
    assert a["inverse_variance"][0].n_harmful == 20
    assert b["inverse_variance"][0].n_harmful == 20
    # the gate: reads the model, and does not inherit its bias
    assert a["gate"][0].n_harmful == 0
    assert b["gate"][0].n_harmful == 0


def test_abstention_is_not_free():
    """The gate's safety in condition B is bought with abstention, and the cost is visible: the
    retained prior is worse than a good observation would have been. Reported so the result is not
    read as safety at no price."""
    truth = _truth()
    b = run_sensor_fault_sweep(truth, [1.2], n_trials=20, sigma_o=SIGMA_O, sigma_p=SIGMA_P,
                               tau_m=TAU_M, prior_offset_m=0.15)
    gate = b["gate"][0]
    assert gate.abstain_rate == 1.0
    assert gate.mean_error_m > SIGMA_O, "abstaining keeps a staler state than a clean observation"
    assert gate.mean_error_m < TAU_M, "but the retained state is still inside tolerance"


# --------------------------------------------------------------------------------------------
# Regression guard for the defect that motivated this module.
# --------------------------------------------------------------------------------------------
def test_trials_within_a_sweep_level_are_actually_different():
    """The earlier comparison injected a constant offset and varied only a channel the baseline never
    read, so its baseline was evaluated 20 times on identical input. Guard against that returning."""
    truth = _truth()
    res = run_sensor_fault_sweep(truth, [0.6], n_trials=20, sigma_o=SIGMA_O, sigma_p=SIGMA_P, tau_m=TAU_M)
    errs = res["fixed_precedence"][0].errors_m
    assert len(errs) == 20
    assert len(set(round(e, 12) for e in errs)) == 20, \
        "every trial must differ; identical errors mean the trials are not trials"


# --------------------------------------------------------------------------------------------
# The side condition the proof sketch did not state. Found by sweeping, not by inspection.
# --------------------------------------------------------------------------------------------
def test_detection_band_above_harm_threshold_opens_a_blind_window():
    """The gate is NOT unconditionally safe. When the combined declared uncertainty is wide enough
    that k*sigma_comb exceeds tau, a fault can be harmful and still sit inside the band the gate uses
    to detect it. At k=3 the band is 0.283 m against a 0.250 m threshold, and the gate accepts a
    0.255 m fault every time. Recorded as a failing regime, not hidden."""
    truth = _truth()
    band = detection_band_m(SIGMA_O, SIGMA_P, 3.0)
    assert band > TAU_M, "this test is only meaningful when the band exceeds the threshold"
    res = run_sensor_fault_sweep(truth, [0.255], n_trials=20, sigma_o=SIGMA_O, sigma_p=SIGMA_P,
                                 tau_m=TAU_M, k_sigma=3.0)
    assert res["gate"][0].n_harmful == 20, "the blind window is real and must stay documented"
    assert res["gate"][0].abstain_rate == 0.0, "the gate cannot see the fault, so it does not decline"


def test_satisfying_the_band_condition_closes_the_window():
    """k*sqrt(sigma_o^2 + sigma_p^2) <= tau is the side condition. Under it the gate is safe across
    the whole fault sweep including the window that broke it at k=3."""
    truth = _truth()
    band = detection_band_m(SIGMA_O, SIGMA_P, 2.0)
    assert band <= TAU_M
    offsets = [0.24, 0.255, 0.265, 0.275, 0.30, 0.40, 0.60]
    res = run_sensor_fault_sweep(truth, offsets, n_trials=20, sigma_o=SIGMA_O, sigma_p=SIGMA_P,
                                 tau_m=TAU_M, k_sigma=2.0)
    assert sum(g.n_harmful for g in res["gate"]) == 0, \
        f"window not closed: {[(g.level_m, g.n_harmful) for g in res['gate']]}"


def test_tightening_k_to_satisfy_the_condition_costs_nothing_on_clean_evidence():
    """The condition is not bought with false rejections in this regime: at k=2 the gate still
    promotes clean evidence every time. That the fix is free here does not mean it is free in
    general, and the proposal states it as a regime-dependent finding."""
    truth = _truth()
    for k in (3.0, 2.0):
        res = run_model_bias_sweep(truth, [0.0], n_trials=20, sigma_o=SIGMA_O, sigma_p=SIGMA_P,
                                   tau_m=TAU_M, k_sigma=k)
        assert res["gate"][0].abstain_rate == 0.0, f"k={k} refused clean evidence"
        assert res["gate"][0].n_harmful == 0
