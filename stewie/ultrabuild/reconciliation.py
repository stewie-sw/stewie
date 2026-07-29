"""Deterministic raster reconciliation for the UltraBuild research slice."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Literal

import numpy as np


Method = Literal[
    "stewie",
    "latest_overwrite",
    "timestamp_only",
    "map_replacement",
    "provenance_free_fusion",
    "single_authoritative_map",
    "no_physics",
    "no_uncertainty",
    "no_dependency",
]


@dataclass(frozen=True)
class RasterEvidence:
    claim_id: str
    robot_id: str
    values: np.ndarray
    coverage: np.ndarray
    valid_start: float
    valid_end: float
    received_sequence: int
    source_time: float
    variance_m2: float
    provenance_complete: bool
    dependency_group: str


@dataclass(frozen=True)
class ActionContext:
    action_id: str
    start: float
    end: float
    operational_envelope: np.ndarray
    volume_tolerance_cells: float
    outside_envelope_tolerance_m: float


@dataclass(frozen=True)
class ReconciliationPolicy:
    method: Method = "stewie"
    conflict_rmse_m: float = 0.2
    decisive_support_ratio: float = 2.0
    minimum_variance_m2: float = 1.0e-6


@dataclass(frozen=True)
class ReconciliationResult:
    decision: Literal["PROMOTE", "RETAIN_HYPOTHESES", "ABSTAIN"]
    state: np.ndarray | None
    admitted_claim_ids: tuple[str, ...]
    excluded: tuple[tuple[str, str], ...]
    hypotheses: tuple[tuple[str, ...], ...]
    diagnostics: dict[str, float | int | str]

    def state_hash(self) -> str | None:
        if self.state is None:
            return None
        return hashlib.sha256(
            np.asarray(self.state, dtype="<f8").tobytes(order="C")
        ).hexdigest()

    def canonical_summary(self) -> bytes:
        value: dict[str, Any] = {
            "decision": self.decision,
            "state_hash": self.state_hash(),
            "admitted_claim_ids": list(self.admitted_claim_ids),
            "excluded": [list(item) for item in self.excluded],
            "hypotheses": [list(item) for item in self.hypotheses],
            "diagnostics": self.diagnostics,
        }
        return json.dumps(
            value,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")


def _covered_rmse(left: RasterEvidence, right: RasterEvidence) -> float:
    mask = np.asarray(left.coverage, dtype=bool) & np.asarray(
        right.coverage, dtype=bool
    )
    if not np.any(mask):
        return math.inf
    difference = np.asarray(left.values) - np.asarray(right.values)
    return float(np.sqrt(np.mean(np.square(difference[mask]))))


def _physics_diagnostics(
    evidence: RasterEvidence,
    prior: np.ndarray,
    action: ActionContext,
) -> tuple[bool, float, float]:
    covered = np.asarray(evidence.coverage, dtype=bool)
    delta = np.where(covered, np.asarray(evidence.values) - prior, 0.0)
    operational = covered & np.asarray(action.operational_envelope, dtype=bool)
    removed = float(np.maximum(-delta[operational], 0.0).sum())
    deposited = float(np.maximum(delta[operational], 0.0).sum())
    volume_imbalance = abs(removed - deposited)
    outside = covered & ~np.asarray(action.operational_envelope, dtype=bool)
    outside_peak = (
        float(np.max(np.abs(delta[outside]))) if np.any(outside) else 0.0
    )
    plausible = (
        volume_imbalance <= action.volume_tolerance_cells
        and outside_peak <= action.outside_envelope_tolerance_m
    )
    return plausible, volume_imbalance, outside_peak


def _cluster(
    evidence: list[RasterEvidence],
    threshold: float,
) -> list[list[RasterEvidence]]:
    """Deterministic connected components under pairwise covered RMSE."""

    clusters: list[list[RasterEvidence]] = []
    for item in sorted(evidence, key=lambda value: value.claim_id):
        matching = [
            cluster
            for cluster in clusters
            if any(_covered_rmse(item, member) <= threshold for member in cluster)
        ]
        if not matching:
            clusters.append([item])
            continue
        target = matching[0]
        target.append(item)
        for other in matching[1:]:
            target.extend(other)
            clusters.remove(other)
    return clusters


def _weights(
    evidence: list[RasterEvidence],
    policy: ReconciliationPolicy,
    *,
    uncertainty_aware: bool,
    dependency_aware: bool,
) -> dict[str, float]:
    base = {
        item.claim_id: (
            1.0
            if not uncertainty_aware
            else 1.0 / max(policy.minimum_variance_m2, item.variance_m2)
        )
        for item in evidence
    }
    if not dependency_aware:
        return base
    groups: dict[str, list[RasterEvidence]] = {}
    for item in evidence:
        groups.setdefault(item.dependency_group, []).append(item)
    adjusted: dict[str, float] = {}
    for members in groups.values():
        group_total = sum(base[item.claim_id] for item in members)
        group_cap = max(base[item.claim_id] for item in members)
        scale = group_cap / group_total
        for item in members:
            adjusted[item.claim_id] = base[item.claim_id] * scale
    return adjusted


def _fuse(
    evidence: list[RasterEvidence],
    weights: dict[str, float],
) -> np.ndarray:
    shape = np.asarray(evidence[0].values).shape
    numerator = np.zeros(shape, dtype=np.float64)
    denominator = np.zeros(shape, dtype=np.float64)
    for item in evidence:
        coverage = np.asarray(item.coverage, dtype=bool)
        weight = weights[item.claim_id]
        numerator[coverage] += np.asarray(item.values, dtype=np.float64)[
            coverage
        ] * weight
        denominator[coverage] += weight
    result = np.full(shape, np.nan, dtype=np.float64)
    observed = denominator > 0.0
    result[observed] = numerator[observed] / denominator[observed]
    return result


def reconcile_rasters(
    evidence: list[RasterEvidence],
    *,
    prior: np.ndarray,
    action: ActionContext,
    known_at_sequence: int,
    policy: ReconciliationPolicy = ReconciliationPolicy(),
) -> ReconciliationResult:
    """Reconcile evidence without exposing an evaluator reference state."""

    if not evidence:
        return ReconciliationResult(
            decision="ABSTAIN",
            state=None,
            admitted_claim_ids=(),
            excluded=(),
            hypotheses=(),
            diagnostics={"reason": "no_evidence"},
        )
    expected_shape = np.asarray(prior).shape
    for item in evidence:
        if (
            np.asarray(item.values).shape != expected_shape
            or np.asarray(item.coverage).shape != expected_shape
        ):
            raise ValueError(
                f"{item.claim_id}: evidence shape differs from prior state"
            )
        if item.valid_end < item.valid_start:
            raise ValueError(f"{item.claim_id}: inverted valid-time interval")
        if item.variance_m2 <= 0.0:
            raise ValueError(f"{item.claim_id}: variance must be positive")

    visible = [
        item for item in evidence if item.received_sequence <= known_at_sequence
    ]
    excluded: list[tuple[str, str]] = [
        (item.claim_id, "future_transaction")
        for item in evidence
        if item.received_sequence > known_at_sequence
    ]
    if not visible:
        return ReconciliationResult(
            decision="ABSTAIN",
            state=None,
            admitted_claim_ids=(),
            excluded=tuple(sorted(excluded)),
            hypotheses=(),
            diagnostics={"reason": "no_known_evidence"},
        )

    if policy.method in {"latest_overwrite", "map_replacement"}:
        selected = max(
            visible,
            key=lambda item: (item.received_sequence, item.claim_id),
        )
        return ReconciliationResult(
            decision="PROMOTE",
            state=np.asarray(selected.values, dtype=np.float64).copy(),
            admitted_claim_ids=(selected.claim_id,),
            excluded=tuple(sorted(excluded)),
            hypotheses=((selected.claim_id,),),
            diagnostics={"selection": "latest_transaction"},
        )
    if policy.method == "timestamp_only":
        selected = max(
            visible,
            key=lambda item: (item.source_time, item.claim_id),
        )
        return ReconciliationResult(
            decision="PROMOTE",
            state=np.asarray(selected.values, dtype=np.float64).copy(),
            admitted_claim_ids=(selected.claim_id,),
            excluded=tuple(sorted(excluded)),
            hypotheses=((selected.claim_id,),),
            diagnostics={"selection": "source_timestamp"},
        )
    if policy.method == "single_authoritative_map":
        selected = min(visible, key=lambda item: (item.robot_id, item.claim_id))
        return ReconciliationResult(
            decision="PROMOTE",
            state=np.asarray(selected.values, dtype=np.float64).copy(),
            admitted_claim_ids=(selected.claim_id,),
            excluded=tuple(sorted(excluded)),
            hypotheses=((selected.claim_id,),),
            diagnostics={"selection": "lexical_authority"},
        )

    provenance_gated = policy.method not in {"provenance_free_fusion"}
    physics_gated = policy.method not in {
        "provenance_free_fusion",
        "no_physics",
    }
    uncertainty_aware = policy.method not in {"no_uncertainty"}
    dependency_aware = policy.method not in {"no_dependency"}

    admitted: list[RasterEvidence] = []
    max_imbalance = 0.0
    max_outside = 0.0
    for item in visible:
        if item.valid_end <= action.end:
            excluded.append((item.claim_id, "stale_before_action"))
            continue
        if provenance_gated and not item.provenance_complete:
            excluded.append((item.claim_id, "incomplete_provenance"))
            continue
        plausible, imbalance, outside = _physics_diagnostics(
            item, np.asarray(prior), action
        )
        max_imbalance = max(max_imbalance, imbalance)
        max_outside = max(max_outside, outside)
        if physics_gated and not plausible:
            excluded.append((item.claim_id, "physics_inconsistent"))
            continue
        admitted.append(item)

    if not admitted:
        return ReconciliationResult(
            decision="ABSTAIN",
            state=None,
            admitted_claim_ids=(),
            excluded=tuple(sorted(excluded)),
            hypotheses=(),
            diagnostics={
                "reason": "all_evidence_excluded",
                "maximum_volume_imbalance_cells": max_imbalance,
                "maximum_outside_envelope_change_m": max_outside,
            },
        )

    clusters = _cluster(admitted, policy.conflict_rmse_m)
    weights = _weights(
        admitted,
        policy,
        uncertainty_aware=uncertainty_aware,
        dependency_aware=dependency_aware,
    )
    cluster_support = [
        sum(weights[item.claim_id] for item in cluster)
        for cluster in clusters
    ]
    ordered_clusters = sorted(
        zip(clusters, cluster_support, strict=True),
        key=lambda item: (-item[1], tuple(value.claim_id for value in item[0])),
    )
    hypotheses = tuple(
        tuple(sorted(item.claim_id for item in cluster))
        for cluster, _ in ordered_clusters
    )
    if len(ordered_clusters) > 1:
        top_support = ordered_clusters[0][1]
        second_support = ordered_clusters[1][1]
        if top_support < policy.decisive_support_ratio * second_support:
            return ReconciliationResult(
                decision="RETAIN_HYPOTHESES",
                state=None,
                admitted_claim_ids=tuple(
                    sorted(item.claim_id for item in admitted)
                ),
                excluded=tuple(sorted(excluded)),
                hypotheses=hypotheses,
                diagnostics={
                    "cluster_count": len(clusters),
                    "top_support_ratio": top_support / second_support,
                    "maximum_volume_imbalance_cells": max_imbalance,
                    "maximum_outside_envelope_change_m": max_outside,
                },
            )
    selected_cluster = ordered_clusters[0][0]
    state = _fuse(selected_cluster, weights)
    return ReconciliationResult(
        decision="PROMOTE",
        state=state,
        admitted_claim_ids=tuple(
            sorted(item.claim_id for item in selected_cluster)
        ),
        excluded=tuple(sorted(excluded)),
        hypotheses=hypotheses,
        diagnostics={
            "cluster_count": len(clusters),
            "effective_support": float(
                sum(weights[item.claim_id] for item in selected_cluster)
            ),
            "maximum_volume_imbalance_cells": max_imbalance,
            "maximum_outside_envelope_change_m": max_outside,
        },
    )
