"""The repaired bound attaches effective support to the accepted aggregate.

For a plain mean, graph-component support controls expected MSE. It does not by
itself determine an RMS tail; the basic theorem uses a variance proxy and
Markov, while a sharper tail needs spatial covariance.
"""

from __future__ import annotations

import numpy as np
import pytest

from stewie.twin.effective_support import (
    component_support_from_graph,
    global_mask_dependency_edges,
)
from stewie.twin.promotion import (
    Decision,
    Evidence,
    chi_square_rms_multiplier,
    evaluate,
)

SIGMA = 0.05
M = 3


@pytest.fixture(scope="module")
def truth() -> np.ndarray:
    dem = np.fromfile(
        "samples/lunar_dem/haworth_10km_5m/heightmap.rf32",
        dtype=np.float32,
    )
    side = int(np.sqrt(dem.size))
    return dem.reshape(side, side)[1000:1032, 1000:1032].astype(float)


@pytest.mark.parametrize("d", [0.0, 0.5, 1.0])
def test_variance_of_promoted_mean_matches_component_support(truth, d: float):
    """400 controlled error trials on the real Haworth surface."""
    mask = np.zeros(truth.shape, dtype=bool)
    mask.ravel()[: int(d * truth.size)] = True
    squared_errors = []
    predicted = M / (1.0 + d * (M - 1))

    for trial in range(400):
        rng = np.random.default_rng(50000 + trial)
        shared = rng.normal(0.0, SIGMA, truth.shape)
        observations = []
        for source in range(M):
            independent = rng.normal(0.0, SIGMA, truth.shape)
            error = np.where(mask, shared, independent)
            observations.append(
                Evidence(
                    f"agent_{source}",
                    "observation",
                    truth + error,
                    SIGMA,
                )
            )
        result = evaluate(
            observations,
            correlation_mask=mask,
            min_effective_support=1.0,
        )
        assert result.decision is Decision.PROMOTE
        assert result.accepted_state is not None
        squared_errors.append(
            float(np.mean((result.accepted_state - truth) ** 2))
        )
        assert result.effective_n == pytest.approx(predicted)

    measured_rms = float(np.sqrt(np.mean(squared_errors)))
    predicted_rms = SIGMA / np.sqrt(predicted)
    assert measured_rms == pytest.approx(predicted_rms, rel=0.025)


def test_component_sizes_two_one_give_nine_fifths(truth):
    sources = ("a", "b", "c")
    observed = {source: np.ones(truth.shape, dtype=bool) for source in sources}
    sigmas = {source: SIGMA for source in sources}
    edges = {("a", "b"): np.ones(truth.shape, dtype=bool)}
    support = component_support_from_graph(sources, observed, sigmas, edges)

    assert np.allclose(support.per_cell, 9.0 / 5.0)
    assert support.region_effective_n == pytest.approx(9.0 / 5.0)
    assert np.all(support.n_components == 2)
    assert np.array_equal(
        support.component_labels["a"],
        support.component_labels["b"],
    )
    assert not np.array_equal(
        support.component_labels["a"],
        support.component_labels["c"],
    )


def test_unequal_sigma_component_bound_is_the_sum_of_component_sums(truth):
    sources = ("a", "b", "c")
    observed = {source: np.ones(truth.shape, dtype=bool) for source in sources}
    sigmas = {"a": 0.05, "b": 0.10, "c": 0.20}
    edges = {("a", "b"): np.ones(truth.shape, dtype=bool)}
    support = component_support_from_graph(sources, observed, sigmas, edges)
    expected = ((0.05 + 0.10) ** 2 + 0.20**2) / 3.0**2

    assert np.allclose(support.variance_bound_m2, expected)


def test_partial_coverage_uses_the_sources_present_on_each_cell(truth):
    sources = ("a", "b", "c")
    left = np.zeros(truth.shape, dtype=bool)
    left[:, : truth.shape[1] // 2] = True
    observed = {
        "a": np.ones(truth.shape, dtype=bool),
        "b": np.ones(truth.shape, dtype=bool),
        "c": left,
    }
    sigmas = {source: SIGMA for source in sources}
    edges = {("a", "b"): np.ones(truth.shape, dtype=bool)}
    support = component_support_from_graph(sources, observed, sigmas, edges)

    assert np.allclose(support.per_cell[left], 9.0 / 5.0)
    assert np.allclose(support.per_cell[~left], 1.0)
    assert support.region_effective_n == pytest.approx(9.0 / 7.0)


def test_component_graph_rejects_ambiguous_or_misaligned_metadata(truth):
    full = np.ones(truth.shape, dtype=bool)
    with pytest.raises(ValueError, match="unique"):
        component_support_from_graph(
            ("a", "a"),
            {"a": full},
            {"a": SIGMA},
            {},
        )
    with pytest.raises(ValueError, match="shape"):
        component_support_from_graph(
            ("a", "b"),
            {"a": full, "b": full},
            {"a": SIGMA, "b": SIGMA},
            {("a", "b"): np.ones((2, 2), dtype=bool)},
        )
    with pytest.raises(ValueError, match="unknown source"):
        component_support_from_graph(
            ("a", "b"),
            {"a": full, "b": full},
            {"a": SIGMA, "b": SIGMA},
            {("a", "c"): full},
        )


def test_chi_square_rms_multiplier_is_calibrated_for_the_region_statistic():
    multiplier = chi_square_rms_multiplier(1024, 1e-3)
    assert multiplier == pytest.approx(1.0687, abs=1e-4)
    assert multiplier < 2.0


def test_old_global_mask_is_the_all_sources_one_component_special_case(truth):
    sources = ("a", "b", "c")
    observed = {source: np.ones(truth.shape, dtype=bool) for source in sources}
    sigmas = {source: SIGMA for source in sources}
    mask = np.zeros(truth.shape, dtype=bool)
    mask[:, : truth.shape[1] // 2] = True
    edges = global_mask_dependency_edges(sources, mask)
    support = component_support_from_graph(sources, observed, sigmas, edges)

    assert np.all(support.per_cell[mask] == 1.0)
    assert np.all(support.per_cell[~mask] == 3.0)
    assert support.region_effective_n == pytest.approx(1.5)


def test_support_without_a_common_error_scale_is_not_a_tail_bound(truth):
    """Same graph, different marginal scale: support is unchanged but MSE moves."""
    rms = []
    for scale in (0.05, 0.50):
        errors = []
        for trial in range(100):
            rng = np.random.default_rng(71000 + trial)
            common = rng.normal(0.0, scale, truth.shape)
            aggregate = np.mean(
                np.stack([truth + common for _ in range(M)]),
                axis=0,
            )
            errors.append(float(np.mean((aggregate - truth) ** 2)))
        rms.append(float(np.sqrt(np.mean(errors))))

    assert M / (1 + (M - 1)) == 1.0
    assert rms[1] > 8.0 * rms[0]
