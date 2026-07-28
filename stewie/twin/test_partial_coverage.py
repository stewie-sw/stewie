"""[F8] Partial coverage: the fault family the taxonomy omits, found from the real ingest path.

The previous iteration shipped a fix requiring the candidate to be one of the offered observations,
and flagged one worry: exact matching is brittle against any pipeline that transforms a reading
between sensor and proposal. Checking that turned up something larger.

**The perception path produces height fields with unobserved cells, by design.** ``replay_loop``
computes ``valid = np.isfinite(z).mean()`` and carries it forward as ``coverage_fraction`` precisely
because parts of the field are never seen. **The promotion rule cannot represent that at all**: the
``Evidence`` guard raises on any non-finite value, so a realistically partial reading cannot even be
constructed. The two subsystems cannot be connected.

That is the same shape as the A7 finding -- each component internally consistent, incompatible at
the seam -- and it has the same consequence: every measurement in this dissertation uses fully
covered observations, which no real sensor produces, and the coverage regime of the soundness claim
is "100%", unstated and untested.

**The failure is not merely availability.** The rule computes the dependency fraction as
``n_correlated / candidate.size`` -- over the whole array. The denominator that matters is the
number of cells actually observed, since those are the only cells the corroboration was computed
over. Where coverage is uncorrelated with dependency the two agree. Where it is correlated, the
full-grid fraction *understates* dependency among the compared cells and the rule believes the
readings are more independent than they are.

**And the correlation is the default case, not an adversarial one.** Both coverage and disturbance
are caused by the same thing: where the machines are. They churn the ground they stand on and they
see the ground they stand on, so a sensor preferentially observes exactly the cells its own vehicle
disturbed. Measured at 50% coverage with a true dependency of 15% of the grid, the full-grid
denominator gives ``m_eff = 2.31`` and accepts while the observed-cell denominator gives 1.88 and
would refuse.

Status: the rule currently **fails closed**, so this is latent rather than live. It becomes live the
moment the real perception path is connected. The corrected denominator is implemented and measured
in ``effective_support.coverage_aware_support`` but deliberately **not wired in**, because wiring it
requires admitting observations with unobserved cells, which changes what inputs the rule accepts.

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
from stewie.twin.promotion import Evidence

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


def test_the_rule_cannot_represent_a_realistically_partial_reading():
    """The seam. ``Evidence`` refuses to be constructed from what the perception path emits."""
    dem = np.fromfile("samples/lunar_dem/haworth_10km_5m/heightmap.rf32", dtype=np.float32)
    n = int(np.sqrt(dem.size))
    partial = dem.reshape(n, n)[1000:1032, 1000:1032].astype(float)
    partial[:4, :] = np.nan                      # 12.5% unobserved, as coverage_fraction implies

    with pytest.raises(ValueError, match="must be finite"):
        Evidence("stereo", "observation", partial, 0.05, 1.0)


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
