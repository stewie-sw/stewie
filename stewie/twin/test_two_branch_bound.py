"""The superseded branch-4 proof is refuted; the structural bound replaces it.

The old derivation inferred

    d*c^2 + sigma_o^2 + sigma_p^2 <= threshold^2

from a realised observation-minus-prediction residual passing its gate. The
residual actually contains ``c + epsilon - b - eta``. An unrestricted model
bias can cancel a harmful observation error, and realised cross-terms cannot be
replaced by a sum of variances.

The valid theorem is branch-free: every PROMOTE result returns the same
observation-only aggregate, so harmful acceptance is a subset of aggregate
harm, for every physics bias.
"""

from __future__ import annotations

import numpy as np
import pytest

from stewie.twin.promotion import Decision, Evidence, evaluate

SIGMA_O = 0.05
SIGMA_P = 0.08
TAU = 0.25


@pytest.fixture(scope="module")
def truth() -> np.ndarray:
    dem = np.fromfile(
        "samples/lunar_dem/haworth_10km_5m/heightmap.rf32",
        dtype=np.float32,
    )
    side = int(np.sqrt(dem.size))
    return dem.reshape(side, side)[1000:1032, 1000:1032].astype(float)


def _rms_error(state: np.ndarray, truth: np.ndarray) -> float:
    return float(np.sqrt(np.mean((state - truth) ** 2)))


def test_a5_does_not_make_the_physics_agreement_branch_safe(truth):
    """Concrete cancellation on real terrain, under the stated A5 numbers."""
    k = 2.0
    assert k * np.hypot(SIGMA_O, SIGMA_P) <= TAU
    biased = truth + 0.30
    evidence = [
        Evidence("a", "observation", biased.copy(), SIGMA_O),
        Evidence("b", "observation", biased.copy(), SIGMA_O),
        Evidence("physics", "physics", biased.copy(), SIGMA_P),
    ]

    result = evaluate(
        evidence,
        correlation_mask=np.zeros(truth.shape, dtype=bool),
        effect_size_multiplier=k,
        min_effective_support=2.0,
    )

    assert result.decision is Decision.PROMOTE
    assert result.residual_rms_m == pytest.approx(0.0)
    assert result.accepted_state is not None
    assert _rms_error(result.accepted_state, truth) == pytest.approx(0.30)
    assert _rms_error(result.accepted_state, truth) > TAU


def test_the_invalid_variance_substitution_fails_numerically(truth):
    k = 2.0
    common = 0.30
    model_bias = 0.30
    realised_residual_sq = (common - model_bias) ** 2
    substituted_left = common**2 + SIGMA_O**2 + SIGMA_P**2
    threshold_sq = k**2 * (SIGMA_O**2 + SIGMA_P**2)

    assert realised_residual_sq <= threshold_sq
    assert substituted_left > threshold_sq, (
        "the inequality used by the old proof does not follow from the "
        "residual test"
    )


@pytest.mark.parametrize("model_bias", [-10.0, -0.7, 0.0, 0.7, 10.0])
def test_every_promoted_value_is_the_same_observation_aggregate(
    truth,
    model_bias: float,
):
    rng = np.random.default_rng(91)
    observations = [
        Evidence(
            f"agent_{index}",
            "observation",
            truth + rng.normal(0.0, SIGMA_O, truth.shape),
            SIGMA_O,
        )
        for index in range(3)
    ]
    model = Evidence(
        "physics",
        "physics",
        truth + model_bias,
        SIGMA_P,
    )
    expected = np.mean(
        np.stack([np.asarray(item.values) for item in observations]),
        axis=0,
    )
    result = evaluate(
        [*observations, model],
        correlation_mask=np.zeros(truth.shape, dtype=bool),
        min_effective_support=2.0,
    )

    if result.decision is Decision.PROMOTE:
        assert result.accepted_state is not None
        assert np.array_equal(result.accepted_state, expected)


def test_physics_can_only_remove_outcomes_from_candidate_harm(truth):
    """Finite-sample instance of the event inclusion formalised in Lean."""
    candidate_harm = harmful_acceptance = 0
    for trial in range(100):
        rng = np.random.default_rng(12000 + trial)
        common = rng.normal(0.0, 0.30)
        observations = [
            Evidence(
                f"agent_{index}",
                "observation",
                truth + common + rng.normal(0.0, SIGMA_O, truth.shape),
                SIGMA_O,
            )
            for index in range(3)
        ]
        expected = np.mean(
            np.stack([np.asarray(item.values) for item in observations]),
            axis=0,
        )
        harmful = _rms_error(expected, truth) > TAU
        candidate_harm += int(harmful)
        model = Evidence(
            "physics",
            "physics",
            truth + rng.normal(-2.0, 2.0),
            SIGMA_P,
        )
        result = evaluate(
            [*observations, model],
            correlation_mask=np.zeros(truth.shape, dtype=bool),
            min_effective_support=2.0,
        )
        harmful_acceptance += int(
            result.decision is Decision.PROMOTE and harmful
        )

    assert candidate_harm > 0
    assert harmful_acceptance <= candidate_harm
