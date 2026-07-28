"""[C3] Effective independent support from an action history, by the conservative route.

The acceptance rule's third branch asks how much *independent* evidence a candidate really has. Where
two agents have modified the same cells in overlapping windows, their later observations are not
independent, and counting them as if they were overstates confidence. The quantity that expresses
this is

    m_eff = Phi(action history)  <=  m

and deriving Phi is the dissertation's core technical problem. Three routes were proposed. This
module implements the third, **C3**, which is the only one that cannot fail: it assumes the worst
admissible correlation rather than modelling the true one, so it is valid by construction and needs
no correlation model at all.

**The derivation.** For m observations whose errors are equicorrelated at rho on a given cell, the
variance of their mean is ``sigma^2 (1 + (m-1) rho) / m``. The number of independent observations
that would produce that same variance is

    m_eff(cell) = m / (1 + (m-1) rho)

Aggregating over a region by mean squared error (cells with less support contribute more error, so
the aggregate is harmonic rather than arithmetic), with a fraction ``d = |D|/n`` of cells correlated:

    m_eff = m / (1 + d (m-1) rho)

Setting ``rho = 1`` -- perfect correlation on every shared cell, the worst case admissible -- gives
the assumption-free bound. Nothing about the true correlation structure need be known.

**Why this is not throwaway work.** C1, the variance-inflation route, is *the same formula* with rho
derived from the overlap structure instead of pinned at 1. C3 is the rho=1 instance of a
one-parameter family, so building it also builds the frame C1 slots into, and the gap between them
is exactly the cost of refusing to model the correlation -- a reportable quantity rather than an
apology.

**What this replaces, and why it is worse than crude.** The implemented placeholder discounted
linearly in overlap area, ``m_eff = m (1 - d)``. Two defects, and the second is the serious one.

At ``d = 1`` it returns **zero** independent support. Two perfectly correlated observations are still
one observation, not none.

More importantly, the two forms cross at ``d = (m-2)/(m-1)``, and **below that crossover, for
m >= 3, the placeholder reports MORE support than is soundly available**. At m=10 with half the
region shared it claims 5.0 against a sound bound of 1.82. An optimistic support estimate is what
makes a rule accept on inflated confidence, which is the exact failure this work exists to prevent.
So in the many-agent, partial-overlap regime that motivates the problem, the placeholder commits the
error under study.

This went unnoticed because the crossover sits at ``d = 0`` when ``m = 2``, and every existing test
uses one or two observations. See ``test_effective_support.py`` for both pinned comparisons.
"""

from __future__ import annotations

import numpy as np


def per_cell_effective_count(m: int, rho: float) -> float:
    """Independent-observation equivalent for one cell whose m errors are equicorrelated at ``rho``.

    ``rho = 0`` gives ``m`` (fully independent); ``rho = 1`` gives 1 (all m are one observation).
    """
    if m < 1:
        raise ValueError(f"m must be >= 1 (got {m})")
    if not (0.0 <= rho <= 1.0):
        raise ValueError(f"rho must be in [0, 1] (got {rho})")
    return m / (1.0 + (m - 1) * rho)


def conservative_effective_support(m: int, correlated_fraction: float, rho: float = 1.0) -> float:
    """[C3] Region-level effective independent support. ``rho=1`` is the assumption-free bound.

    ``correlated_fraction`` is ``|D| / n``: the share of cells modified by two or more agents within
    overlapping action windows, as produced by ``shared_terrain.correlation_mask``.

    Never returns less than 1 when ``m >= 1``: however much ground the agents shared, an observation
    of it is still an observation. That floor is the property the linear placeholder lacked.
    """
    if m < 1:
        raise ValueError(f"m must be >= 1 (got {m})")
    d = float(correlated_fraction)
    if not (0.0 <= d <= 1.0):
        raise ValueError(f"correlated_fraction must be in [0, 1] (got {d})")
    if not (0.0 <= rho <= 1.0):
        raise ValueError(f"rho must be in [0, 1] (got {rho})")
    return m / (1.0 + d * (m - 1) * rho)


def effective_support_from_mask(m: int, correlation_mask: np.ndarray, rho: float = 1.0) -> float:
    """``conservative_effective_support`` taking the cell mask directly."""
    mask = np.asarray(correlation_mask, dtype=bool)
    if mask.size == 0:
        raise ValueError("correlation_mask is empty")
    return conservative_effective_support(m, float(mask.sum()) / mask.size, rho)


def linear_placeholder_support(m: int, correlated_fraction: float) -> float:
    """The superseded discount, retained only so the comparison can be tested rather than asserted.

    Do not use it to decide anything. It reports zero independent support when every cell is shared,
    which is false: correlated observations are worth less, not nothing.
    """
    d = float(correlated_fraction)
    if not (0.0 <= d <= 1.0):
        raise ValueError(f"correlated_fraction must be in [0, 1] (got {d})")
    return m * (1.0 - d)


def measured_effective_support(errors: np.ndarray) -> float:
    """Effective support actually exhibited by a realised error ensemble, for validating the bound.

    ``errors`` is ``(m, n)``: one row per observation, one column per cell. Returns the independent-
    observation equivalent implied by the variance of the ensemble mean, namely
    ``mean per-observation variance / variance of the mean``. This is the empirical quantity the C3
    bound must not exceed.
    """
    e = np.asarray(errors, dtype=float)
    if e.ndim != 2 or e.shape[0] < 1:
        raise ValueError(f"errors must be (m, n) with m >= 1 (got shape {e.shape})")
    per_obs_var = float(np.mean(np.var(e, axis=1)))
    mean_var = float(np.var(e.mean(axis=0)))
    if mean_var <= 0.0:
        return float(e.shape[0])
    return per_obs_var / mean_var

def log_error_tolerance(m: int, min_effective_support: float) -> float:
    """The exact fraction of mis-reported ground the support test tolerates, in EITHER direction.

    Solving ``m / (1 + d(m-1)) = threshold`` for the dependency fraction gives

        d_crit = (m / threshold - 1) / (m - 1)

    and the decision flips there exactly, verified per-trial to within one cell across
    ``m`` from 2 to 8. The quantity has two opposed readings and that is the point:

    * an action log that **fabricates** overlap drives the rule to abstain on genuinely
      independent evidence once the fabricated fraction exceeds ``d_crit``;
    * an action log that **omits** overlap drives the rule to accept genuinely dependent
      evidence once the reported fraction falls below ``d_crit``.

    **One constant governs both, so they are not independent knobs.** Raising the support
    threshold to buy safety against an omitting log lowers ``d_crit`` and buys fragility
    against a fabricating one, in exact proportion. There is no setting that is robust to
    both; there is only a choice about which way to fail.

    Returns 0.0 when the threshold is at or above ``m`` (nothing is acceptable) and is
    capped at 1.0, since a dependency fraction cannot exceed the region.
    """
    if m <= 1:
        raise ValueError("log error tolerance is undefined for a single observation")
    if min_effective_support <= 0.0:
        raise ValueError("support threshold must be positive")
    if min_effective_support >= m:
        return 0.0
    return min(1.0, (m / min_effective_support - 1.0) / (m - 1.0))

def observed_dependency_fraction(correlation_mask, observed_mask) -> float:
    """The dependency fraction among the cells a sensor actually saw.

    The rule divides the correlated-cell count by the size of the whole candidate array. That is
    correct only when the observation covers the whole array. Real readings do not: the perception
    path computes ``valid = np.isfinite(z).mean()`` precisely because parts of the field are
    unobserved, and carries it forward as ``coverage_fraction``.

    The denominator that matters is the number of cells actually observed, because those are the
    only cells the corroboration was computed over:

        d_observed = |D and observed| / |observed|

    **Coverage and dependency are not independent in this setting, and that is what makes the
    difference bite.** Both are driven by where the machines are: they churn the ground they stand
    on and they see the ground they stand on. So a sensor preferentially observes exactly the cells
    its own vehicle disturbed, the full-grid fraction understates the dependency among the cells
    that were actually compared, and the rule believes the readings are more independent than they
    are. That is the optimistic direction, the one this design exists to prevent.

    Measured at 50% coverage with a true dependency of 15% of the grid: the full-grid denominator
    gives ``m_eff = 2.31`` and accepts, while the observed-cell denominator gives 1.88 and would
    refuse. Under coverage uncorrelated with dependency the two agree, so this is a statement about
    the correlation, not about partial coverage as such.

    Returns 0.0 when nothing was observed, which is the conservative reading only in the sense that
    no support can be claimed from an empty set; callers must treat zero coverage as abstention
    rather than as independence.
    """
    corr = np.asarray(correlation_mask, dtype=bool)
    seen = np.asarray(observed_mask, dtype=bool)
    if corr.shape != seen.shape:
        raise ValueError(f"mask shapes differ: {corr.shape} vs {seen.shape}")
    n_seen = int(seen.sum())
    if n_seen == 0:
        return 0.0
    return float((corr & seen).sum()) / float(n_seen)


def coverage_aware_support(m: int, correlation_mask, observed_mask, rho: float = 1.0) -> float:
    """``conservative_effective_support`` over the observed cells rather than the whole array.

    Not wired into the decision rule. Doing so requires admitting observations with unobserved
    cells, which the ``Evidence`` guard currently refuses outright, and that is a change to what
    inputs the rule accepts rather than to how it weighs them.
    """
    return conservative_effective_support(
        m, observed_dependency_fraction(correlation_mask, observed_mask), rho)

