"""Observation-aggregate promotion with contestable, veto-only physics.

The deployed control in :mod:`stewie.twin.terrain_view` overwrites the current
state with an observation. This module instead returns PROMOTE, REJECT, or
ABSTAIN and may consult a physical prediction before accepting a patch.

The accepted value is constructed here as the plain mean of all
metadata-admissible observations. Physics may suppress that value but cannot
construct it, choose an observation subset, set its weights, or fill missing
cells. This is the implementation invariant behind the model-bias theorem.

Dependency is represented by pairwise source edges per cell. Component sizes
``q_l`` give ``m_eff,j = m_j^2 / sum_l q_l^2`` for the observation mean. The
legacy union mask remains only as a conservative compatibility input: it places
every source in one component on every masked cell.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from itertools import combinations
from typing import Mapping

import numpy as np

from stewie.twin.effective_support import (
    component_support_from_graph,
    global_mask_dependency_edges,
)


class Decision(str, Enum):
    PROMOTE = "promote"
    REJECT = "reject"
    ABSTAIN = "abstain"


@dataclass(frozen=True)
class Evidence:
    """One typed, uncertain, source-tagged claim over a terrain region.

    NaN denotes an unobserved cell. Infinity is never admissible. ``sigma_m`` is
    the declared per-cell 1-sigma height uncertainty in metres. ``observed_at``
    is validity time, not ingestion time.
    """

    source: str
    kind: str
    values: np.ndarray
    sigma_m: float
    reliability: float = 1.0
    observed_at: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("observation", "physics", "action"):
            raise ValueError(f"unknown evidence kind {self.kind!r}")
        if not (self.sigma_m > 0.0 and np.isfinite(self.sigma_m)):
            raise ValueError(f"{self.source}: sigma_m must be finite and > 0")
        if not (0.0 < self.reliability <= 1.0):
            raise ValueError(
                f"{self.source}: reliability must be in (0, 1] "
                f"(got {self.reliability})"
            )
        if self.observed_at is not None and not np.isfinite(self.observed_at):
            raise ValueError(
                f"{self.source}: observed_at must be finite when supplied"
            )
        values = np.asarray(self.values, dtype=float)
        if values.ndim != 2 or values.size == 0:
            raise ValueError(f"{self.source}: values must be a non-empty 2-D field")
        if np.any(np.isinf(values)):
            raise ValueError(f"{self.source}: values must not contain infinity")
        if not np.any(np.isfinite(values)):
            raise ValueError(f"{self.source}: values contain no observed cell")


@dataclass
class PromotionResult:
    decision: Decision
    reason: str
    residual_rms_m: float = 0.0
    tolerance_m: float = 0.0
    n_correlated: int = 0
    effective_n: float = 0.0
    detail: dict = field(default_factory=dict)
    accepted_state: np.ndarray | None = None
    accepted_mask: np.ndarray | None = None
    variance_bound_m2: np.ndarray | None = None


def chi_square_rms_multiplier(
    n_cells: int,
    false_alarm_probability: float,
) -> float:
    """Calibrate a standardised-RMS threshold from a chi-square tail.

    For ``n_cells`` independent standard-normal residuals, the standardised RMS
    exceeds this multiplier with the requested probability. The multiplier is
    not an ordinary univariate "number of sigmas".
    """
    if n_cells < 1:
        raise ValueError("n_cells must be >= 1")
    alpha = float(false_alarm_probability)
    if not (0.0 < alpha < 1.0):
        raise ValueError("false_alarm_probability must be in (0, 1)")
    from scipy.stats import chi2

    return float(np.sqrt(chi2.ppf(1.0 - alpha, n_cells) / n_cells))


def _comparison_multiplier(
    n_cells: int,
    *,
    effect_size_multiplier: float | None,
    family_false_alarm_probability: float,
    n_comparisons: int,
) -> float:
    if effect_size_multiplier is not None:
        value = float(effect_size_multiplier)
        if not (value > 0.0 and np.isfinite(value)):
            raise ValueError("effect_size_multiplier must be finite and > 0")
        return value
    per_comparison = family_false_alarm_probability / max(1, n_comparisons)
    return chi_square_rms_multiplier(n_cells, per_comparison)


def stale_sources(
    evidence: list[Evidence],
    last_modified_at: float | None,
) -> list[str]:
    """Sources whose observation predates the last action on this ground."""
    if last_modified_at is None:
        return []
    return [
        item.source
        for item in evidence
        if item.observed_at is not None and item.observed_at < last_modified_at
    ]


def _same_shape(evidence: list[Evidence], prior: np.ndarray | None) -> tuple[int, int]:
    shape = np.asarray(evidence[0].values, dtype=float).shape
    for item in evidence:
        item_shape = np.asarray(item.values, dtype=float).shape
        if item_shape != shape:
            raise ValueError(
                f"{item.source}: evidence shape {item_shape} != candidate region {shape}"
            )
    if prior is not None and np.asarray(prior, dtype=float).shape != shape:
        raise ValueError(f"prior shape {np.asarray(prior).shape} != evidence shape {shape}")
    return shape


def _observation_aggregate(
    observations: list[Evidence],
) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    stack = np.stack(
        [np.asarray(item.values, dtype=float) for item in observations]
    )
    finite = np.isfinite(stack)
    count = finite.sum(axis=0)
    observed = count > 0
    aggregate = np.full(stack.shape[1:], np.nan, dtype=float)
    aggregate[observed] = (
        np.where(finite, stack, 0.0).sum(axis=0)[observed] / count[observed]
    )
    masks = {
        item.source: finite[index].copy()
        for index, item in enumerate(observations)
    }
    return aggregate, observed, masks


def evaluate(
    evidence: list[Evidence],
    *,
    prior: np.ndarray | None = None,
    dependency_edges: Mapping[tuple[str, str], np.ndarray] | None = None,
    correlation_mask: np.ndarray | None = None,
    last_modified_at: float | None = None,
    effect_size_multiplier: float | None = None,
    false_alarm_probability: float = 1e-3,
    min_effective_support: float = 1.0,
    min_override_components: int = 2,
    support_model: str = "c3",
) -> PromotionResult:
    """Construct and gate a plain observation-only aggregate.

    ``dependency_edges`` carries a boolean mask for each source pair. Its
    connected components define per-cell support. ``correlation_mask`` is a
    legacy compatibility path that treats all sources as one component on
    masked cells. Supplying neither for multiple observations means dependency
    is unknown, not absent, and produces ABSTAIN.

    The default residual threshold uses a chi-square multiplier with a
    Bonferroni family-wise correction. Its false-alarm interpretation requires
    independent Gaussian standardised residual cells and, for observation to
    physics comparisons, zero observation--model cross-covariance. Otherwise
    it is only a scale comparison. ``effect_size_multiplier`` is available for
    controlled fault sweeps; it has no false-alarm interpretation.
    """
    if not evidence:
        return PromotionResult(Decision.ABSTAIN, "no evidence offered")
    if not (
        min_effective_support > 0.0
        and np.isfinite(min_effective_support)
    ):
        raise ValueError("min_effective_support must be finite and > 0")
    if (
        not np.isfinite(min_override_components)
        or min_override_components != int(min_override_components)
        or min_override_components < 2
    ):
        raise ValueError(
            "min_override_components must be a finite integer >= 2 "
            f"(got {min_override_components!r})"
        )
    if not (0.0 < false_alarm_probability < 1.0):
        raise ValueError("false_alarm_probability must be in (0, 1)")
    if dependency_edges is not None and correlation_mask is not None:
        raise ValueError("supply dependency_edges or correlation_mask, not both")
    if last_modified_at is not None and not np.isfinite(last_modified_at):
        raise ValueError("last_modified_at must be finite when supplied")

    offered_observation_sources = {
        item.source
        for item in evidence
        if item.kind == "observation"
    }
    if dependency_edges is not None:
        for pair in dependency_edges:
            if len(pair) != 2:
                raise ValueError(
                    f"dependency edge must contain two sources (got {pair!r})"
                )
            if pair[0] == pair[1]:
                raise ValueError(
                    f"dependency self-edge is invalid ({pair[0]!r})"
                )
            if any(
                source not in offered_observation_sources
                for source in pair
            ):
                raise ValueError(
                    "dependency edge references a source that was not offered "
                    f"as an observation ({pair!r})"
                )

    # Filter before constructing the accepted value. The superseded ordering
    # permitted a stale candidate after removing its supporting observation.
    if last_modified_at is not None:
        unknown_validity = [
            item.source
            for item in evidence
            if item.kind in ("observation", "physics")
            and item.observed_at is None
        ]
        if unknown_validity:
            return PromotionResult(
                Decision.ABSTAIN,
                "evidence validity time is unknown after a terrain modification",
                detail={"unknown_validity_sources": sorted(unknown_validity)},
            )
        evidence = [
            item
            for item in evidence
            if not (
                item.observed_at is not None
                and item.observed_at < last_modified_at
            )
        ]
    if not evidence:
        return PromotionResult(
            Decision.ABSTAIN,
            "all evidence predates the last action on this ground",
        )

    observations = sorted(
        (item for item in evidence if item.kind == "observation"),
        key=lambda item: item.source,
    )
    physics = sorted(
        (item for item in evidence if item.kind == "physics"),
        key=lambda item: item.source,
    )
    if not observations:
        return PromotionResult(Decision.ABSTAIN, "no observation among the evidence")
    if len({item.source for item in observations}) != len(observations):
        return PromotionResult(
            Decision.REJECT,
            "duplicate observation source identity: deduplicate before promotion",
        )
    if len({item.source for item in physics}) != len(physics):
        return PromotionResult(
            Decision.REJECT,
            "duplicate physics source identity: deduplicate before promotion",
        )

    shape = _same_shape(evidence, prior)
    candidate, candidate_mask, observed_masks = _observation_aggregate(observations)
    source_ids = [item.source for item in observations]
    sigmas = {item.source: item.sigma_m for item in observations}

    dependency_known = (
        dependency_edges is not None
        or correlation_mask is not None
        or len(observations) == 1
    )
    if correlation_mask is not None:
        legacy_mask = np.asarray(correlation_mask, dtype=bool)
        if legacy_mask.shape != shape:
            raise ValueError(
                f"correlation_mask shape {legacy_mask.shape} "
                f"!= evidence shape {shape}"
            )
        edges = global_mask_dependency_edges(source_ids, legacy_mask)
    else:
        current_sources = set(source_ids)
        edges = {
            pair: mask
            for pair, mask in (dependency_edges or {}).items()
            if pair[0] in current_sources and pair[1] in current_sources
        }

    support = component_support_from_graph(
        source_ids,
        observed_masks,
        sigmas,
        edges,
    )
    # An edge asserts that two sources may share an error. That assertion can only bite on cells
    # where BOTH of them actually observed: where only one saw the ground, there is no second
    # reading for a common error to correlate with, and counting the cell as dependent discounts
    # support that was never claimed. Restricting to the pairwise overlap is what makes the
    # dependency fraction agree with the coverage the corroboration was computed over.
    edge_union = np.zeros(shape, dtype=bool)
    for (left, right), edge_mask in edges.items():
        both_observed = observed_masks[left] & observed_masks[right]
        edge_union |= np.asarray(edge_mask, dtype=bool) & both_observed
    n_correlated = int((edge_union & candidate_mask).sum())
    n_observed = int(candidate_mask.sum())
    d = n_correlated / n_observed if n_observed else 0.0

    if support_model == "c3":
        effective_n = support.region_effective_n
    elif support_model == "linear":
        effective_n = len(observations) * (1.0 - d)
    elif support_model == "none":
        effective_n = float(len(observations))
    else:
        raise ValueError(f"unknown support_model {support_model!r}")

    pair_overlaps = []
    for a, b in combinations(observations, 2):
        overlap = observed_masks[a.source] & observed_masks[b.source]
        if np.any(overlap):
            pair_overlaps.append((a, b, overlap))
    physics_overlaps = []
    for model in physics:
        overlap = candidate_mask & np.isfinite(np.asarray(model.values, dtype=float))
        if np.any(overlap):
            physics_overlaps.append((model, overlap))
    n_comparisons = len(pair_overlaps) + len(physics_overlaps)

    obs_disagrees = False
    worst_obs_standardised_rms = 0.0
    for a, b, overlap in pair_overlaps:
        multiplier = _comparison_multiplier(
            int(overlap.sum()),
            effect_size_multiplier=effect_size_multiplier,
            family_false_alarm_probability=false_alarm_probability,
            n_comparisons=n_comparisons,
        )
        same_component = (
            support.component_labels[a.source][overlap]
            == support.component_labels[b.source][overlap]
        )
        variance = np.where(
            same_component,
            (a.sigma_m + b.sigma_m) ** 2,
            a.sigma_m**2 + b.sigma_m**2,
        )
        delta = (
            np.asarray(a.values, dtype=float)[overlap]
            - np.asarray(b.values, dtype=float)[overlap]
        )
        standardised_rms = float(np.sqrt(np.mean(delta**2 / variance)))
        worst_obs_standardised_rms = max(
            worst_obs_standardised_rms,
            standardised_rms,
        )
        if standardised_rms > multiplier:
            obs_disagrees = True

    residual_rms = 0.0
    tolerance = 0.0
    worst_physics_excess = -np.inf
    physics_disagrees = False
    for model, overlap in physics_overlaps:
        multiplier = _comparison_multiplier(
            int(overlap.sum()),
            effect_size_multiplier=effect_size_multiplier,
            family_false_alarm_probability=false_alarm_probability,
            n_comparisons=n_comparisons,
        )
        residual = (
            candidate[overlap]
            - np.asarray(model.values, dtype=float)[overlap]
        )
        residual_variance = (
            support.variance_bound_m2[overlap] + model.sigma_m**2
        )
        standardised_rms = float(
            np.sqrt(np.mean(residual**2 / residual_variance))
        )
        raw_rms = float(np.sqrt(np.mean(residual**2)))
        raw_tolerance = multiplier * float(
            np.sqrt(np.mean(residual_variance))
        )
        excess = standardised_rms - multiplier
        if excess > 0.0:
            physics_disagrees = True
        if excess > worst_physics_excess:
            worst_physics_excess = excess
            residual_rms = raw_rms
            tolerance = raw_tolerance

    min_components = int(np.min(support.n_components[candidate_mask]))
    veto_available = bool(physics_overlaps)
    detail = {
        "n_obs": len(observations),
        "n_physics": len(physics),
        "coverage_fraction": n_observed / candidate.size,
        "dependency_known": dependency_known,
        "physics_disagrees": physics_disagrees,
        "obs_disagrees": obs_disagrees,
        "veto_available": veto_available,
        "min_components": min_components,
        "mean_reliability": (
            sum(item.reliability for item in observations) / len(observations)
        ),
        "worst_obs_standardised_rms": worst_obs_standardised_rms,
        "worst_physics_standardised_excess": (
            0.0 if not np.isfinite(worst_physics_excess)
            else worst_physics_excess
        ),
        "threshold_mode": (
            "effect_size"
            if effect_size_multiplier is not None
            else "chi_square"
        ),
        "family_false_alarm_probability": (
            None
            if effect_size_multiplier is not None
            else false_alarm_probability
        ),
    }
    common = {
        "residual_rms_m": residual_rms,
        "tolerance_m": tolerance,
        "n_correlated": n_correlated,
        "effective_n": effective_n,
        "detail": detail,
        "variance_bound_m2": support.variance_bound_m2.copy(),
    }

    if obs_disagrees:
        return PromotionResult(
            Decision.ABSTAIN,
            "observations contradict each other beyond the calibrated "
            "residual threshold",
            **common,
        )
    if not dependency_known:
        return PromotionResult(
            Decision.ABSTAIN,
            "source-dependency relation was not supplied; absence is not "
            "evidence of independence",
            **common,
        )
    component_override_fails = (
        support_model == "c3"
        and min_components < min_override_components
    )
    if physics_disagrees and (
        effective_n < min_effective_support or component_override_fails
    ):
        return PromotionResult(
            Decision.ABSTAIN,
            "physics disagrees and the observation aggregate lacks support "
            "from distinct dependency components",
            **common,
        )
    if effective_n < min_effective_support:
        return PromotionResult(
            Decision.ABSTAIN,
            f"effective independent support {effective_n:.2f} below required "
            f"{min_effective_support:.2f}",
            **common,
        )

    if physics_disagrees:
        reason = (
            "physics disagrees, but the observation-only aggregate is "
            "supported by distinct dependency components"
        )
    elif veto_available:
        reason = (
            "the observation-only aggregate passed every observation and "
            "physics check"
        )
    else:
        reason = (
            "the observation-only aggregate has sufficient graph support; "
            "no physical model was available to veto it"
        )
    return PromotionResult(
        Decision.PROMOTE,
        reason,
        accepted_state=candidate.copy(),
        accepted_mask=candidate_mask.copy(),
        **common,
    )


def baseline_fixed_precedence(
    prior: np.ndarray,
    observation: np.ndarray,
    mask: np.ndarray | None = None,
) -> np.ndarray:
    """The fixed-precedence control: an observation overwrites unconditionally."""
    state = np.array(prior, dtype=float, copy=True)
    observed = np.asarray(observation, dtype=float)
    write_mask = (
        np.ones(state.shape, dtype=bool)
        if mask is None
        else np.asarray(mask, dtype=bool)
    )
    if observed.shape != state.shape or write_mask.shape != state.shape:
        raise ValueError("prior, observation, and mask shapes must match")
    state[write_mask] = observed[write_mask]
    return state
