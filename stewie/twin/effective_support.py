"""Effective support and variance bounds for an observation-only mean.

The current representation is a per-cell graph over observation sources.
Connected component sizes ``q_l`` give the equal-sigma worst-case support

    m_eff,j = m_j^2 / sum_l q_l^2.

The corresponding unequal-sigma variance bound is computed directly. It
requires calibrated marginal variances and zero cross-component covariance;
dependence inside a component is unrestricted. Negative covariance cannot
break the upper bound and can only reduce the variance of the mean.

An action log may justify placing sources in the same possible-dependency
component, but shared action does not mathematically cause sensor noise to be
correlated conditional on the true post-action surface. That causal link needs
a separate observation-error model. Missing graph edges therefore mean an
explicit independence assertion, not merely "no overlap was noticed."

Legacy scalar helpers remain for reproducing the older global-mask ablations.
For equal source sigma and a fraction ``d`` of cells in one complete component,
their harmonic region shorthand is ``m / (1 + d(m-1))``. It is not a
geometry-aware substitute for the per-cell graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Mapping

import numpy as np


@dataclass(frozen=True)
class ComponentSupport:
    """Per-cell support and variance bound for an observation-only mean.

    ``per_cell`` is ``m_j^2 / sum(q_l^2)`` over dependency-component sizes on
    each observed cell. ``variance_bound_m2`` is the unequal-sigma bound

        sum_l (sum_{i in C_l} sigma_i)^2 / m_j^2.

    Cross-component errors must be uncorrelated; dependence inside a component
    is unrestricted. Cells with no observation carry NaN support/variance and
    are false in ``observed_mask``.
    """

    per_cell: np.ndarray
    variance_bound_m2: np.ndarray
    n_components: np.ndarray
    n_sources: np.ndarray
    observed_mask: np.ndarray
    region_effective_n: float
    component_labels: dict[str, np.ndarray]


def global_mask_dependency_edges(
    source_ids: list[str] | tuple[str, ...],
    correlation_mask: np.ndarray,
) -> dict[tuple[str, str], np.ndarray]:
    """Translate the old global mask into a complete source graph.

    On every masked cell all sources are placed in one component. This is the
    conservative compatibility path for old experiments; it deliberately loses
    pair structure and should not be used when pairwise provenance is available.
    """
    sources = tuple(source_ids)
    if len(set(sources)) != len(sources):
        raise ValueError("source_ids must be unique")
    mask = np.asarray(correlation_mask, dtype=bool)
    if mask.size == 0:
        raise ValueError("correlation_mask is empty")
    return {(a, b): mask.copy() for a, b in combinations(sorted(sources), 2)}


def component_support_from_graph(
    source_ids: list[str] | tuple[str, ...],
    observed_masks: Mapping[str, np.ndarray],
    sigma_m: Mapping[str, float],
    dependency_edges: Mapping[tuple[str, str], np.ndarray],
) -> ComponentSupport:
    """Compute graph-component support for the mean, cell by cell.

    ``dependency_edges[(a, b)]`` is true on cells where source errors ``a`` and
    ``b`` must be treated as belonging to one dependency component. Connected
    components are computed independently per cell. The edge relation is
    undirected; keys are canonicalised, and self-edges are rejected.
    """
    sources = tuple(sorted(source_ids))
    if not sources:
        raise ValueError("at least one source is required")
    if len(set(sources)) != len(sources):
        raise ValueError("source_ids must be unique")
    if set(observed_masks) != set(sources):
        raise ValueError("observed_masks must contain exactly the source_ids")
    if set(sigma_m) != set(sources):
        raise ValueError("sigma_m must contain exactly the source_ids")

    masks = {s: np.asarray(observed_masks[s], dtype=bool) for s in sources}
    shape = masks[sources[0]].shape
    if not shape or any(mask.shape != shape for mask in masks.values()):
        raise ValueError("all observed masks must have the same non-empty shape")
    sigmas = {s: float(sigma_m[s]) for s in sources}
    if any(not (value > 0.0 and np.isfinite(value)) for value in sigmas.values()):
        raise ValueError("all source sigmas must be finite and > 0")

    edges: dict[tuple[str, str], np.ndarray] = {}
    for raw_pair, raw_mask in dependency_edges.items():
        if len(raw_pair) != 2:
            raise ValueError(f"dependency edge must contain two sources (got {raw_pair!r})")
        a, b = raw_pair
        if a == b:
            raise ValueError(f"dependency self-edge is invalid ({a!r})")
        if a not in masks or b not in masks:
            raise ValueError(f"dependency edge references unknown source {(a, b)!r}")
        pair: tuple[str, str] = (a, b) if a < b else (b, a)
        edge_mask = np.asarray(raw_mask, dtype=bool)
        if edge_mask.shape != shape:
            raise ValueError(
                f"dependency edge {pair!r} shape {edge_mask.shape} != evidence shape {shape}"
            )
        edges[pair] = edges.get(pair, np.zeros(shape, dtype=bool)) | edge_mask

    n_cells = int(np.prod(shape))
    per_cell = np.full(n_cells, np.nan, dtype=float)
    variance = np.full(n_cells, np.nan, dtype=float)
    n_components = np.zeros(n_cells, dtype=np.int32)
    n_sources = np.zeros(n_cells, dtype=np.int32)
    labels = {
        source: np.full(n_cells, -1, dtype=np.int32)
        for source in sources
    }
    mask_flat = {s: masks[s].reshape(-1) for s in sources}
    edge_flat = {pair: mask.reshape(-1) for pair, mask in edges.items()}

    for cell in range(n_cells):
        active = [s for s in sources if mask_flat[s][cell]]
        m = len(active)
        if not m:
            continue
        parent = {s: s for s in active}

        def find(source: str) -> str:
            root = source
            while parent[root] != root:
                root = parent[root]
            while parent[source] != source:
                nxt = parent[source]
                parent[source] = root
                source = nxt
            return root

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for (a, b), edge_mask in edge_flat.items():
            if edge_mask[cell] and a in parent and b in parent:
                union(a, b)

        components: dict[str, list[str]] = {}
        for source in active:
            components.setdefault(find(source), []).append(source)
        ordered_components = sorted(
            (sorted(component) for component in components.values()),
            key=tuple,
        )
        sizes = [len(component) for component in ordered_components]
        per_cell[cell] = float(m * m) / float(sum(q * q for q in sizes))
        variance[cell] = (
            sum(sum(sigmas[source] for source in component) ** 2
                for component in ordered_components)
            / float(m * m)
        )
        for label, component in enumerate(ordered_components):
            for source in component:
                labels[source][cell] = label
        n_components[cell] = len(ordered_components)
        n_sources[cell] = m

    observed = n_sources > 0
    if not observed.any():
        region_effective_n = 0.0
    else:
        region_effective_n = float(observed.sum()) / float(np.sum(1.0 / per_cell[observed]))
    return ComponentSupport(
        per_cell=per_cell.reshape(shape),
        variance_bound_m2=variance.reshape(shape),
        n_components=n_components.reshape(shape),
        n_sources=n_sources.reshape(shape),
        observed_mask=observed.reshape(shape),
        region_effective_n=region_effective_n,
        component_labels={
            source: values.reshape(shape)
            for source, values in labels.items()
        },
    )


def per_cell_effective_count(m: int, rho: float) -> float:
    """Independent-observation equivalent for one cell whose m errors are equicorrelated at ``rho``.

    A valid equicorrelation satisfies ``rho >= -1/(m-1)``. ``rho = 0``
    gives ``m`` and ``rho = 1`` gives one. Negative correlation gives more
    than ``m`` equivalents; at the singular lower endpoint the mean has zero
    variance and the equivalent count is infinite.
    """
    if m < 1:
        raise ValueError(f"m must be >= 1 (got {m})")
    lower = -1.0 / (m - 1) if m > 1 else -1.0
    if not (lower <= rho <= 1.0):
        raise ValueError(
            f"rho must be in [{lower}, 1] for a valid equicorrelation "
            f"matrix (got {rho})"
        )
    denominator = 1.0 + (m - 1) * rho
    return float("inf") if denominator == 0.0 else m / denominator


def conservative_effective_support(m: int, correlated_fraction: float, rho: float = 1.0) -> float:
    """Legacy equal-sigma region support under a global dependency mask.

    ``correlated_fraction`` is ``|D| / n``: the share of cells modified by two or more agents within
    overlapping action windows, as produced by ``shared_terrain.correlation_mask``.

    ``rho=1`` is worst-case within the declared mask and marginal-variance
    model; it is not assumption-free. The result never falls below one.
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
        return float("inf")
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
    """Legacy global-mask support over observed cells, not the whole array.

    The production rule now admits NaN as an unobserved cell and computes the
    more precise graph support directly. This helper remains for the scalar
    regression comparison.
    """
    return conservative_effective_support(
        m, observed_dependency_fraction(correlation_mask, observed_mask), rho)
