"""Controlled, reproducible experiments for the UltraBuild vertical slice."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from stewie.ultrabuild.canonical import canonical_bytes, sha256_json
from stewie.ultrabuild.identity import build_identity
from stewie.ultrabuild.reconciliation import (
    ActionContext,
    Method,
    RasterEvidence,
    ReconciliationPolicy,
    reconcile_rasters,
)


SHAPE = (12, 12)
EVALUATION_SEEDS = tuple(range(3001, 3009))
ACTION_KINDS = ("nominal", "partial", "failed")
METHODS: tuple[Method, ...] = (
    "stewie",
    "latest_overwrite",
    "timestamp_only",
    "map_replacement",
    "provenance_free_fusion",
    "single_authoritative_map",
    "no_physics",
    "no_uncertainty",
    "no_dependency",
)
WINDOW_ORIGINS = (
    (1, 1),
    (1, 5),
    (1, 9),
    (4, 2),
    (4, 7),
    (7, 1),
    (7, 5),
    (9, 8),
)


@dataclass(frozen=True)
class CandidateScenario:
    unit_id: str
    seed: int
    action_kind: str
    prior: np.ndarray
    planned_change: np.ndarray
    action: ActionContext
    evidence: tuple[RasterEvidence, ...]


@dataclass(frozen=True)
class EvaluationReference:
    reference_id: str
    terrain: np.ndarray
    cut_mask: np.ndarray
    content_hash: str


def _reference_hash(terrain: np.ndarray) -> str:
    return sha256_json(
        {
            "shape": list(terrain.shape),
            "dtype": "<f8",
            "bytes_sha256": hashlib.sha256(
                np.asarray(terrain, dtype="<f8").tobytes(order="C")
            ).hexdigest(),
        }
    )


def _window_masks(origin: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    row, column = origin
    cut = np.zeros(SHAPE, dtype=bool)
    fill = np.zeros(SHAPE, dtype=bool)
    cut[row : row + 2, column : column + 2] = True
    fill_row = row + 2 if row + 4 <= SHAPE[0] else row - 2
    fill_column = max(0, min(SHAPE[1] - 2, column - 1))
    fill[fill_row : fill_row + 2, fill_column : fill_column + 2] = True
    if np.any(cut & fill):
        raise RuntimeError("experimental cut/fill windows overlap")
    return cut, fill


def generate_trial(
    *,
    window_index: int,
    action_kind: str,
    seed: int,
) -> tuple[CandidateScenario, EvaluationReference]:
    """Generate candidate-visible evidence and evaluator-only truth."""

    if not 0 <= window_index < len(WINDOW_ORIGINS):
        raise ValueError("window_index is outside the frozen unit registry")
    if action_kind not in ACTION_KINDS:
        raise ValueError(f"unknown action kind: {action_kind}")
    random = np.random.default_rng(seed + 100 * window_index)
    cut, fill = _window_masks(WINDOW_ORIGINS[window_index])
    prior = np.zeros(SHAPE, dtype=np.float64)
    magnitude = {"nominal": 1.0, "partial": 0.5, "failed": 0.0}[action_kind]
    truth = prior.copy()
    truth[cut] -= magnitude
    truth[fill] += magnitude
    planned_change = prior.copy()
    planned_change[cut] -= 1.0
    planned_change[fill] += 1.0
    envelope = cut | fill
    action = ActionContext(
        action_id=f"action.{action_kind}.window-{window_index:02d}",
        start=9.0,
        end=10.0,
        operational_envelope=envelope,
        volume_tolerance_cells=0.35,
        outside_envelope_tolerance_m=0.15,
    )
    all_coverage = np.ones(SHAPE, dtype=bool)
    shared_noise = random.normal(0.0, 0.012, SHAPE)
    current_a = truth + shared_noise
    current_a2 = current_a + random.normal(0.0, 0.003, SHAPE)
    stale = prior + random.normal(0.0, 0.01, SHAPE)

    artifact = truth + random.normal(0.0, 0.015, SHAPE)
    outside_indices = np.argwhere(~envelope)
    chosen = outside_indices[
        (seed + window_index) % len(outside_indices)
    ]
    artifact[tuple(chosen)] += 0.30
    inside_indices = np.argwhere(envelope)
    compensation = inside_indices[
        (seed + 3 * window_index) % len(inside_indices)
    ]
    artifact[tuple(compensation)] -= 0.30
    artifact2 = artifact + random.normal(0.0, 0.004, SHAPE)
    artifact_provenance = seed % 2 == 0

    evidence = (
        RasterEvidence(
            claim_id=f"claim.robot-a.{window_index}.{seed}",
            robot_id="robot.a",
            values=current_a,
            coverage=all_coverage,
            valid_start=10.0,
            valid_end=11.0,
            received_sequence=1,
            source_time=10.1,
            variance_m2=0.0004,
            provenance_complete=True,
            dependency_group=f"pipeline.robot-a.{window_index}.{seed}",
        ),
        RasterEvidence(
            claim_id=f"claim.robot-a-derived.{window_index}.{seed}",
            robot_id="robot.a",
            values=current_a2,
            coverage=all_coverage,
            valid_start=10.0,
            valid_end=11.0,
            received_sequence=2,
            source_time=10.2,
            variance_m2=0.0005,
            provenance_complete=True,
            dependency_group=f"pipeline.robot-a.{window_index}.{seed}",
        ),
        RasterEvidence(
            claim_id=f"claim.robot-c-artifact.{window_index}.{seed}",
            robot_id="robot.c",
            values=artifact,
            coverage=all_coverage,
            valid_start=10.0,
            valid_end=11.0,
            received_sequence=3,
            source_time=10.3,
            variance_m2=0.01,
            provenance_complete=artifact_provenance,
            dependency_group=f"pipeline.robot-c.{window_index}.{seed}",
        ),
        RasterEvidence(
            claim_id=f"claim.robot-c-derived.{window_index}.{seed}",
            robot_id="robot.c",
            values=artifact2,
            coverage=all_coverage,
            valid_start=10.0,
            valid_end=11.0,
            received_sequence=4,
            source_time=10.4,
            variance_m2=0.012,
            provenance_complete=artifact_provenance,
            dependency_group=f"pipeline.robot-c.{window_index}.{seed}",
        ),
        RasterEvidence(
            claim_id=f"claim.robot-b-stale.{window_index}.{seed}",
            robot_id="robot.b",
            values=stale,
            coverage=all_coverage,
            valid_start=8.0,
            valid_end=9.5,
            received_sequence=5,
            source_time=11.5,
            variance_m2=0.0001,
            provenance_complete=True,
            dependency_group=f"pipeline.robot-b.{window_index}.{seed}",
        ),
    )
    unit_id = f"unit.window-{window_index:02d}.{action_kind}"
    reference = EvaluationReference(
        reference_id=f"reference.{unit_id}.{seed}",
        terrain=truth,
        cut_mask=cut,
        content_hash=_reference_hash(truth),
    )
    return (
        CandidateScenario(
            unit_id=unit_id,
            seed=seed,
            action_kind=action_kind,
            prior=prior,
            planned_change=planned_change,
            action=action,
            evidence=evidence,
        ),
        reference,
    )


def run_candidate(
    scenario: CandidateScenario,
    method: Method,
) -> dict[str, Any]:
    result = reconcile_rasters(
        list(scenario.evidence),
        prior=scenario.prior,
        action=scenario.action,
        known_at_sequence=5,
        policy=ReconciliationPolicy(method=method),
    )
    return {
        "unit_id": scenario.unit_id,
        "seed": scenario.seed,
        "action_kind": scenario.action_kind,
        "method": method,
        "decision": result.decision,
        "state": result.state,
        "state_hash": result.state_hash(),
        "admitted_claim_ids": list(result.admitted_claim_ids),
        "excluded": [list(item) for item in result.excluded],
        "hypotheses": [list(item) for item in result.hypotheses],
        "diagnostics": result.diagnostics,
        "candidate_summary_hash": hashlib.sha256(
            result.canonical_summary()
        ).hexdigest(),
    }


def evaluate_candidate(
    candidate: dict[str, Any],
    reference: EvaluationReference,
) -> dict[str, Any]:
    state = candidate["state"]
    available = state is not None
    if available:
        finite = np.isfinite(state)
        if not np.all(finite):
            rmse = float("inf")
        else:
            rmse = float(
                np.sqrt(
                    np.mean(
                        np.square(
                            np.asarray(state, dtype=np.float64)
                            - reference.terrain
                        )
                    )
                )
            )
        predicted_cut_min = float(np.min(np.asarray(state)[reference.cut_mask]))
    else:
        rmse = None
        predicted_cut_min = None
    true_cut_min = float(np.min(reference.terrain[reference.cut_mask]))
    committed_traverse = (
        predicted_cut_min is not None and predicted_cut_min > -0.4
    )
    true_hazard = true_cut_min < -0.4
    harmful_plan = bool(committed_traverse and true_hazard)
    stale_claim_fragment = "robot-b-stale"
    stale_rejected = any(
        stale_claim_fragment in claim_id and reason == "stale_before_action"
        for claim_id, reason in candidate["excluded"]
    )
    return {
        "reference_id": reference.reference_id,
        "reference_hash": reference.content_hash,
        "available": available,
        "rmse_m": rmse,
        "incorrect_state": bool(rmse is not None and rmse > 0.2),
        "committed_traverse": committed_traverse,
        "true_hazard": true_hazard,
        "harmful_plan": harmful_plan,
        "stale_rejected": stale_rejected,
    }


def trial_records(
    *,
    methods: Iterable[Method] = METHODS,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for window_index in range(len(WINDOW_ORIGINS)):
        for action_kind in ACTION_KINDS:
            for seed in EVALUATION_SEEDS:
                scenario, reference = generate_trial(
                    window_index=window_index,
                    action_kind=action_kind,
                    seed=seed,
                )
                for method in methods:
                    candidate = run_candidate(scenario, method)
                    evaluation = evaluate_candidate(candidate, reference)
                    candidate_without_state = dict(candidate)
                    candidate_without_state.pop("state")
                    records.append(
                        {
                            **candidate_without_state,
                            **evaluation,
                        }
                    )
    return records


def _aggregate(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    aggregates: dict[str, dict[str, Any]] = {}
    for method in METHODS:
        selected = [record for record in records if record["method"] == method]
        available = [record for record in selected if record["available"]]
        rmses = [record["rmse_m"] for record in available]
        aggregates[method] = {
            "trials": len(selected),
            "available_trials": len(available),
            "availability_rate": len(available) / len(selected),
            "harmful_plan_count": sum(
                int(record["harmful_plan"]) for record in selected
            ),
            "harmful_plan_rate": sum(
                int(record["harmful_plan"]) for record in selected
            )
            / len(selected),
            "incorrect_state_count": sum(
                int(record["incorrect_state"]) for record in selected
            ),
            "mean_rmse_m_available": (
                float(np.mean(rmses)) if rmses else None
            ),
            "stale_rejection_rate": sum(
                int(record["stale_rejected"]) for record in selected
            )
            / len(selected),
            "retained_hypothesis_count": sum(
                record["decision"] == "RETAIN_HYPOTHESES"
                for record in selected
            ),
        }
    return aggregates


def _paired_unit_bootstrap(
    records: list[dict[str, Any]],
    *,
    left: str,
    right: str,
    endpoint: str,
    samples: int = 4000,
) -> dict[str, Any]:
    unit_ids = sorted({record["unit_id"] for record in records})
    unit_differences = []
    for unit_id in unit_ids:
        left_values = [
            float(record[endpoint])
            for record in records
            if record["unit_id"] == unit_id and record["method"] == left
        ]
        right_values = [
            float(record[endpoint])
            for record in records
            if record["unit_id"] == unit_id and record["method"] == right
        ]
        unit_differences.append(float(np.mean(left_values) - np.mean(right_values)))
    random = np.random.default_rng(1729)
    values = np.asarray(unit_differences)
    bootstrap = np.empty(samples)
    for index in range(samples):
        draw = random.integers(0, len(values), len(values))
        bootstrap[index] = float(np.mean(values[draw]))
    return {
        "left": left,
        "right": right,
        "endpoint": endpoint,
        "estimand": "paired independent-unit mean difference",
        "independent_units": len(values),
        "estimate": float(np.mean(values)),
        "bootstrap_seed": 1729,
        "bootstrap_samples": samples,
        "confidence_interval_95": [
            float(np.quantile(bootstrap, 0.025)),
            float(np.quantile(bootstrap, 0.975)),
        ],
    }


def run_controlled_evaluation(output_directory: str | Path) -> dict[str, Any]:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    records = trial_records()
    trial_path = output / "trials.jsonl"
    with trial_path.open("wb") as stream:
        for record in records:
            stream.write(canonical_bytes(record) + b"\n")
    report: dict[str, Any] = {
        "schema_version": "stewie.controlled_evaluation/1.0",
        "status": "controlled_synthetic_evidence",
        "claim_limit": (
            "This validates executable mechanisms on frozen controlled arrays; "
            "it is not physical-mission validation."
        ),
        "independent_unit_definition": "terrain_window_x_action_kind",
        "independent_units": len(WINDOW_ORIGINS) * len(ACTION_KINDS),
        "seeds_per_unit": len(EVALUATION_SEEDS),
        "methods": list(METHODS),
        "trial_count": len(records),
        "build_identity": build_identity(),
        "aggregates": _aggregate(records),
        "contrasts": [
            _paired_unit_bootstrap(
                records,
                left="stewie",
                right="latest_overwrite",
                endpoint="harmful_plan",
            ),
            _paired_unit_bootstrap(
                records,
                left="stewie",
                right="no_physics",
                endpoint="harmful_plan",
            ),
        ],
    }
    report["trial_file_sha256"] = hashlib.sha256(
        trial_path.read_bytes()
    ).hexdigest()
    report["report_content_hash"] = sha256_json(report)
    report_path = output / "evaluation_report.json"
    report_path.write_bytes(canonical_bytes(report) + b"\n")
    return report
