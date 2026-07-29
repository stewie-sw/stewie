"""One-factor perturbation study for the controlled reconciliation slice."""

from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path
from typing import Any, Callable

import numpy as np

from stewie.ultrabuild.canonical import canonical_bytes, sha256_json
from stewie.ultrabuild.experiment import (
    CandidateScenario,
    evaluate_candidate,
    generate_trial,
    run_candidate,
)
from stewie.ultrabuild.identity import build_identity
from stewie.ultrabuild.reconciliation import Method, RasterEvidence


METHODS: tuple[Method, ...] = (
    "stewie",
    "latest_overwrite",
    "timestamp_only",
    "no_physics",
)
SEEDS = tuple(range(3001, 3009))


def _map_evidence(
    scenario: CandidateScenario,
    transform: Callable[[RasterEvidence], RasterEvidence],
) -> CandidateScenario:
    return replace(
        scenario,
        evidence=tuple(transform(item) for item in scenario.evidence),
    )


def _localization(scenario: CandidateScenario, cells: int) -> CandidateScenario:
    return _map_evidence(
        scenario,
        lambda item: (
            replace(item, values=np.roll(item.values, cells, axis=1))
            if item.valid_start >= scenario.action.end and cells
            else item
        ),
    )


def _noise(scenario: CandidateScenario, standard_deviation_m: float) -> CandidateScenario:
    random = np.random.default_rng(scenario.seed + 991)

    def transform(item: RasterEvidence) -> RasterEvidence:
        if item.valid_start < scenario.action.end or standard_deviation_m == 0:
            return item
        return replace(
            item,
            values=item.values
            + random.normal(
                0.0,
                standard_deviation_m,
                item.values.shape,
            ),
            variance_m2=item.variance_m2 + standard_deviation_m**2,
        )

    return _map_evidence(scenario, transform)


def _delay(scenario: CandidateScenario, additional_sequences: int) -> CandidateScenario:
    return _map_evidence(
        scenario,
        lambda item: (
            replace(
                item,
                received_sequence=(item.received_sequence + additional_sequences),
            )
            if item.valid_start >= scenario.action.end
            else item
        ),
    )


def _dropout(scenario: CandidateScenario, fraction: float) -> CandidateScenario:
    if fraction == 0.0:
        return scenario
    random = np.random.default_rng(scenario.seed + 177)

    def transform(item: RasterEvidence) -> RasterEvidence:
        if item.valid_start < scenario.action.end:
            return item
        coverage = random.random(item.coverage.shape) >= fraction
        return replace(item, coverage=coverage)

    return _map_evidence(scenario, transform)


def _physics_mismatch(scenario: CandidateScenario, envelope_fraction: float) -> CandidateScenario:
    if envelope_fraction == 1.0:
        return scenario
    envelope = scenario.action.operational_envelope.copy()
    coordinates = np.argwhere(envelope)
    keep = int(round(len(coordinates) * envelope_fraction))
    envelope[:] = False
    for coordinate in coordinates[:keep]:
        envelope[tuple(coordinate)] = True
    return replace(
        scenario,
        action=replace(
            scenario.action,
            operational_envelope=envelope,
        ),
    )


def _robot_count(scenario: CandidateScenario, robots: int) -> CandidateScenario:
    permitted = {
        1: {"robot.a"},
        2: {"robot.a", "robot.b"},
        3: {"robot.a", "robot.b", "robot.c"},
    }[robots]
    return replace(
        scenario,
        evidence=tuple(item for item in scenario.evidence if item.robot_id in permitted),
    )


def _clock_error(scenario: CandidateScenario, seconds: float) -> CandidateScenario:
    return _map_evidence(
        scenario,
        lambda item: (replace(item, source_time=item.source_time + seconds) if item.robot_id == "robot.b" else item),
    )


FACTORS: dict[
    str,
    tuple[tuple[float | int, ...], Callable[[CandidateScenario, Any], CandidateScenario]],
] = {
    "localization_drift_cells": ((0, 1, 2), _localization),
    "sensor_noise_std_m": ((0.0, 0.05, 0.2), _noise),
    "observation_delay_sequences": ((0, 4, 10), _delay),
    "image_dropout_fraction": ((0.0, 0.25, 0.75), _dropout),
    "physics_envelope_fraction": ((1.0, 0.5, 0.0), _physics_mismatch),
    "robot_count": ((1, 2, 3), _robot_count),
    "clock_error_s": ((0.0, 5.0, 20.0), _clock_error),
}


def run_perturbation_study(output_directory: str | Path) -> dict[str, Any]:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    cells: list[dict[str, Any]] = []
    for factor, (levels, transform) in FACTORS.items():
        for level in levels:
            observations: dict[Method, list[dict[str, Any]]] = {method: [] for method in METHODS}
            for window_index in range(8):
                for seed in SEEDS:
                    scenario, reference = generate_trial(
                        window_index=window_index,
                        action_kind="nominal",
                        seed=seed,
                    )
                    perturbed = transform(scenario, level)
                    for method in METHODS:
                        candidate = run_candidate(perturbed, method)
                        observations[method].append(evaluate_candidate(candidate, reference))
            for method, results in observations.items():
                finite_rmses = [
                    float(result["rmse_m"])
                    for result in results
                    if result["rmse_m"] is not None and math.isfinite(float(result["rmse_m"]))
                ]
                available = sum(int(result["available"]) for result in results)
                cells.append(
                    {
                        "factor": factor,
                        "level": level,
                        "method": method,
                        "trials": len(results),
                        "availability_rate": available / len(results),
                        "harmful_plan_rate": sum(int(result["harmful_plan"]) for result in results) / len(results),
                        "finite_rmse_rate": len(finite_rmses) / len(results),
                        "mean_finite_rmse_m": (float(np.mean(finite_rmses)) if finite_rmses else None),
                    }
                )
    stewie_failures = [
        {
            "factor": cell["factor"],
            "level": cell["level"],
            "availability_rate": cell["availability_rate"],
            "harmful_plan_rate": cell["harmful_plan_rate"],
            "finite_rmse_rate": cell["finite_rmse_rate"],
            "mean_finite_rmse_m": cell["mean_finite_rmse_m"],
        }
        for cell in cells
        if cell["method"] == "stewie"
        and (
            cell["availability_rate"] < 0.95
            or cell["harmful_plan_rate"] > 0.0
            or cell["finite_rmse_rate"] < 0.95
            or (cell["mean_finite_rmse_m"] is not None and cell["mean_finite_rmse_m"] > 0.2)
        )
    ]
    report: dict[str, Any] = {
        "schema_version": "stewie.perturbation_report/1.0",
        "status": "exploratory_controlled_one_factor_diagnostic",
        "claim_limit": (
            "Factors are synthetic and varied one at a time. Interactions, "
            "physical sensor behavior, network partitions, and generalization "
            "outside the exposed development arrays are not established."
        ),
        "independent_units": "8 exposed synthetic development windows",
        "seeds_per_unit": len(SEEDS),
        "action_kind": "nominal",
        "methods": list(METHODS),
        "factor_levels": {factor: list(levels) for factor, (levels, _) in FACTORS.items()},
        "cells": cells,
        "build_identity": build_identity(),
        "registered_stewie_failure_cells": stewie_failures,
        "unmeasured_factors": [
            "wheel_slip",
            "communication_bandwidth",
            "partition_duration",
            "map_size",
            "clock_drift_during_run",
            "terrain_collapse",
            "physical_material_model_error",
        ],
    }
    report["report_content_hash"] = sha256_json(report)
    (output / "perturbation-report.json").write_bytes(canonical_bytes(report) + b"\n")
    return report
