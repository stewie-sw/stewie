"""[F8] Partial coverage is represented explicitly after the theorem repair.

The real ingest path emits unobserved cells. NaN now means unobserved, the
accepted object is a patch rather than a fabricated full field, and graph
support is computed from the sources present at each cell.

The scalar tests below retain the superseded full-grid calculation as an
ablation: when coverage and dependency are co-located, it overstates support.
The production graph path uses observed cells directly.

Real Haworth LOLA terrain. Coverage patterns are controlled fault injection.
"""

from __future__ import annotations

import numpy as np
import pytest

from stewie.twin.effective_support import (
    conservative_effective_support,
    coverage_aware_support,
    observed_dependency_fraction,
)
from stewie.twin.promotion import Decision, Evidence, evaluate

N_CELLS = 32 * 32
M_AGENTS = 3
THRESHOLD = 2.0
TRUE_DEPENDENCY = 0.15


def _masks(coverage: float, mode: str, seed: int = 0):
    """``mode='random'`` decorrelates coverage from dependency; ``'colocated'`` is the real case."""
    rng = np.random.default_rng(seed)
    corr = np.zeros(N_CELLS, dtype=bool)
    corr[rng.permutation(N_CELLS)[:int(TRUE_DEPENDENCY * N_CELLS)]] = True
    seen = np.zeros(N_CELLS, dtype=bool)
    if mode == "random":
        seen[rng.permutation(N_CELLS)[:int(coverage * N_CELLS)]] = True
    else:
        seen[np.argsort(~corr, kind="stable")[:int(coverage * N_CELLS)]] = True
    return corr, seen


def test_the_rule_represents_a_realistically_partial_reading_as_a_patch():
    dem = np.fromfile("samples/lunar_dem/haworth_10km_5m/heightmap.rf32", dtype=np.float32)
    n = int(np.sqrt(dem.size))
    partial = dem.reshape(n, n)[1000:1032, 1000:1032].astype(float)
    partial[:4, :] = np.nan                      # 12.5% unobserved, as coverage_fraction implies

    evidence = Evidence("stereo", "observation", partial, 0.05, 1.0)
    result = evaluate([evidence], min_effective_support=1.0)

    assert result.decision is Decision.PROMOTE
    assert result.accepted_state is not None and result.accepted_mask is not None
    assert result.detail["coverage_fraction"] == pytest.approx(0.875)
    assert not result.accepted_mask[:4, :].any()
    assert result.accepted_mask[4:, :].all()
    assert np.isnan(result.accepted_state[:4, :]).all()
    assert np.array_equal(result.accepted_state[4:, :], partial[4:, :])


def test_coverage_uncorrelated_with_dependency_is_harmless():
    """Establishes that partial coverage as such is not the problem."""
    for coverage in (1.0, 0.75, 0.5, 0.25):
        corr, seen = _masks(coverage, "random")
        full_grid = conservative_effective_support(M_AGENTS, corr.sum() / N_CELLS)
        observed = coverage_aware_support(M_AGENTS, corr, seen)
        assert abs(full_grid - observed) < 0.15, (
            f"at {coverage:.0%} random coverage the two denominators should broadly agree"
        )
        assert (full_grid >= THRESHOLD) == (observed >= THRESHOLD), "and agree on the verdict"


@pytest.mark.parametrize("coverage", [0.5, 0.35, 0.25])
def test_colocated_coverage_makes_the_rule_believe_evidence_is_independent(coverage: float):
    """The finding, in the direction the whole design exists to prevent."""
    corr, seen = _masks(coverage, "colocated")
    full_grid = conservative_effective_support(M_AGENTS, corr.sum() / N_CELLS)
    observed = coverage_aware_support(M_AGENTS, corr, seen)

    assert full_grid >= THRESHOLD, "the full-grid denominator accepts"
    assert observed < THRESHOLD, "while the cells actually compared do not support acceptance"
    assert observed < full_grid, (
        "and the error is optimistic: partial coverage understates dependency, it does not "
        "overstate it, which is the dangerous direction rather than the safe one"
    )


def test_the_gap_widens_as_coverage_falls():
    """Monotone, so the effect is a mechanism rather than an artefact of one coverage level."""
    gaps = []
    for coverage in (1.0, 0.75, 0.5, 0.35, 0.25):
        corr, seen = _masks(coverage, "colocated")
        gaps.append(conservative_effective_support(M_AGENTS, corr.sum() / N_CELLS)
                    - coverage_aware_support(M_AGENTS, corr, seen))
    assert gaps[0] == pytest.approx(0.0, abs=1e-9), "full coverage: the two denominators coincide"
    assert gaps == sorted(gaps), f"the gap must grow as coverage falls, got {gaps}"


def test_the_corrected_denominator_is_the_observed_cell_one():
    """Pins the definition, including the empty-coverage case callers must handle."""
    corr = np.array([True, True, False, False])
    assert observed_dependency_fraction(corr, np.array([True, True, True, True])) == 0.5
    assert observed_dependency_fraction(corr, np.array([True, True, False, False])) == 1.0
    assert observed_dependency_fraction(corr, np.array([False, False, True, True])) == 0.0
    assert observed_dependency_fraction(corr, np.zeros(4, dtype=bool)) == 0.0

    with pytest.raises(ValueError, match="shapes differ"):
        observed_dependency_fraction(corr, np.ones(5, dtype=bool))
