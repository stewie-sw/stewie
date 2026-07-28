"""The promoted value is constructed from the evidence the verdict actually used.

The old API accepted an arbitrary candidate and later tried to bind it by exact
array equality to one offered observation. That both rejected legitimate
transforms and still permitted a stale candidate: binding ran before the stale
observation was removed.

The repaired API accepts no caller-supplied candidate. It filters metadata,
constructs the plain observation mean internally, compares physics with that
mean, and returns the accepted patch explicitly.
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from stewie.twin.promotion import (
    Decision,
    Evidence,
    chi_square_rms_multiplier,
    evaluate,
)

SIGMA_O = 0.05
SIGMA_P = 0.08


@pytest.fixture(scope="module")
def truth() -> np.ndarray:
    dem = np.fromfile(
        "samples/lunar_dem/haworth_10km_5m/heightmap.rf32",
        dtype=np.float32,
    )
    side = int(np.sqrt(dem.size))
    return dem.reshape(side, side)[1000:1032, 1000:1032].astype(float)


def _independent(shape: tuple[int, int]) -> np.ndarray:
    return np.zeros(shape, dtype=bool)


def test_the_api_has_no_external_candidate_slot(truth):
    observation = Evidence("stereo", "observation", truth.copy(), SIGMA_O)
    with pytest.raises(TypeError):
        evaluate(truth + 50.0, [observation])  # type: ignore[call-arg]


def test_promoted_state_is_the_plain_observation_mean(truth):
    rng = np.random.default_rng(1)
    observations = [
        Evidence(
            f"agent_{index}",
            "observation",
            truth + rng.normal(0.0, SIGMA_O, truth.shape),
            SIGMA_O,
        )
        for index in range(3)
    ]
    physics = Evidence(
        "terramech",
        "physics",
        truth + rng.normal(0.0, SIGMA_P, truth.shape),
        SIGMA_P,
    )
    result = evaluate(
        [*observations, physics],
        correlation_mask=_independent(truth.shape),
        min_effective_support=2.0,
    )

    assert result.decision is Decision.PROMOTE
    assert result.accepted_state is not None
    expected = np.mean(
        np.stack([np.asarray(item.values, dtype=float) for item in observations]),
        axis=0,
    )
    assert np.array_equal(result.accepted_state, expected)
    assert not any(
        np.array_equal(result.accepted_state, item.values)
        for item in observations
    ), "the repair must actually aggregate rather than silently retain o_1"


def test_noisy_largest_clique_selection_is_worse_than_the_plain_mean(truth):
    """Reproduce the controlled fault that rejects A-prime.

    One source receives a 0.03 m alternating-sign offset, so its trial-average
    offset is zero but it lies near the pairwise agreement boundary. A-prime is
    instantiated as the lexicographically first largest pairwise-agreeing
    clique. Its realised RMS is worse than the plain mean and is not recovered
    by substituting the selected subset size into ``sigma/sqrt(m)``.
    """
    plain_squared_error = []
    selected_squared_error = []
    subset_variance_prediction = []
    multiplier = chi_square_rms_multiplier(truth.size, 1e-3)

    for trial in range(400):
        rng = np.random.default_rng(90000 + trial)
        values = np.stack(
            [
                truth + rng.normal(0.0, SIGMA_O, truth.shape)
                for _ in range(3)
            ]
        )
        values[0] += 0.03 if trial % 2 == 0 else -0.03

        agrees = {
            (a, b): float(
                np.sqrt(
                    np.mean(
                        (values[a] - values[b]) ** 2
                        / (2.0 * SIGMA_O**2)
                    )
                )
            )
            <= multiplier
            for a, b in itertools.combinations(range(3), 2)
        }
        selected = None
        for size in (3, 2, 1):
            for subset in itertools.combinations(range(3), size):
                if all(
                    agrees[tuple(sorted((a, b)))]
                    for a, b in itertools.combinations(subset, 2)
                ):
                    selected = subset
                    break
            if selected is not None:
                break
        assert selected is not None

        plain = values.mean(axis=0)
        selected_mean = values[list(selected)].mean(axis=0)
        plain_squared_error.append(float(np.mean((plain - truth) ** 2)))
        selected_squared_error.append(
            float(np.mean((selected_mean - truth) ** 2))
        )
        subset_variance_prediction.append(SIGMA_O**2 / len(selected))

    plain_rms = float(np.sqrt(np.mean(plain_squared_error)))
    selected_rms = float(np.sqrt(np.mean(selected_squared_error)))
    predicted_rms = float(np.sqrt(np.mean(subset_variance_prediction)))

    assert plain_rms == pytest.approx(0.0305, abs=2e-4)
    assert selected_rms == pytest.approx(0.0362, abs=2e-4)
    assert predicted_rms == pytest.approx(0.0350, abs=2e-4)
    assert selected_rms > plain_rms * 1.15
    assert selected_rms > predicted_rms + 1e-3


def test_stale_observation_cannot_remain_the_accepted_candidate(truth):
    stale = Evidence(
        "stale",
        "observation",
        truth + 0.90,
        SIGMA_O,
        observed_at=0.0,
    )
    current = Evidence(
        "current",
        "observation",
        truth.copy(),
        SIGMA_O,
        observed_at=2.0,
    )
    physics = Evidence(
        "terramech",
        "physics",
        truth.copy(),
        SIGMA_P,
        observed_at=2.0,
    )
    result = evaluate(
        [stale, current, physics],
        last_modified_at=1.0,
        min_effective_support=1.0,
    )

    assert result.decision is Decision.PROMOTE
    assert result.accepted_state is not None
    assert np.array_equal(result.accepted_state, current.values)
    assert float(np.sqrt(np.mean((result.accepted_state - truth) ** 2))) == 0.0


def test_dependency_edges_are_filtered_with_their_stale_sources(truth):
    stale = Evidence(
        "stale",
        "observation",
        truth + 0.90,
        SIGMA_O,
        observed_at=0.0,
    )
    current = Evidence(
        "current",
        "observation",
        truth.copy(),
        SIGMA_O,
        observed_at=2.0,
    )
    result = evaluate(
        [stale, current],
        dependency_edges={
            ("stale", "current"): np.ones(truth.shape, dtype=bool)
        },
        last_modified_at=1.0,
    )

    assert result.decision is Decision.PROMOTE
    assert result.accepted_state is not None
    assert np.array_equal(result.accepted_state, truth)


def test_unknown_validity_time_cannot_cross_a_known_modification(truth):
    observation = Evidence("undated", "observation", truth.copy(), SIGMA_O)
    result = evaluate(
        [observation],
        last_modified_at=1.0,
        min_effective_support=1.0,
    )

    assert result.decision is Decision.ABSTAIN
    assert "validity time is unknown" in result.reason


def test_nonfinite_validity_metadata_and_support_thresholds_are_rejected(truth):
    for invalid_time in (np.nan, np.inf, -np.inf):
        with pytest.raises(ValueError, match="observed_at"):
            Evidence(
                "invalid-time",
                "observation",
                truth,
                SIGMA_O,
                observed_at=invalid_time,
            )

    observation = Evidence("current", "observation", truth, SIGMA_O)
    with pytest.raises(ValueError, match="last_modified_at"):
        evaluate([observation], last_modified_at=np.nan)
    with pytest.raises(ValueError, match="min_effective_support"):
        evaluate([observation], min_effective_support=np.nan)


def test_decision_and_accepted_bytes_are_order_invariant(truth):
    rng = np.random.default_rng(2)
    observations = [
        Evidence(
            source,
            "observation",
            truth + rng.normal(0.0, SIGMA_O * 0.1, truth.shape),
            SIGMA_O,
        )
        for source in ("a", "b", "c")
    ]
    physics = Evidence("terramech", "physics", truth.copy(), SIGMA_P)
    outputs = []
    for order in itertools.permutations(observations):
        result = evaluate(
            [*order, physics],
            correlation_mask=_independent(truth.shape),
            min_effective_support=2.0,
        )
        assert result.accepted_state is not None
        outputs.append((result.decision, result.accepted_state.tobytes()))

    assert len(set(outputs)) == 1


def test_every_physics_model_is_compared_with_the_actual_aggregate(truth):
    observations = [
        Evidence("a", "observation", truth + 0.04, SIGMA_O),
        Evidence("b", "observation", truth + 0.04, SIGMA_O),
    ]
    agreeing = Evidence("agreeing", "physics", truth + 0.04, SIGMA_P)
    objecting = Evidence("objecting", "physics", truth + 0.50, SIGMA_P)

    for order in ([agreeing, objecting], [objecting, agreeing]):
        result = evaluate(
            [*observations, *order],
            correlation_mask=_independent(truth.shape),
            min_effective_support=2.0,
        )
        assert result.detail["physics_disagrees"]
        assert result.decision is Decision.PROMOTE
        assert result.accepted_state is not None
        assert np.allclose(result.accepted_state, truth + 0.04)
