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
