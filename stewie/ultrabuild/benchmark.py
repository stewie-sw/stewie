"""Repeatable microbenchmarks for implemented UltraBuild authority paths."""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import resource
import sys
import time
from typing import Any, Callable

import numpy as np

from stewie.ultrabuild.canonical import canonical_bytes, sha256_json
from stewie.ultrabuild.contracts import (
    finalize_record,
    stored_record_errors,
    submission_errors,
)
from stewie.ultrabuild.experiment import generate_trial
from stewie.ultrabuild.identity import build_identity
from stewie.ultrabuild.records import branch_record, submission
from stewie.ultrabuild.reconciliation import (
    ReconciliationPolicy,
    reconcile_rasters,
)
from stewie.ultrabuild.scenario_runner import run_multi_robot_closed_loop
from stewie.ultrabuild.store import AuthoritativeStore


def _measure(
    operation: Callable[[], object],
    *,
    warmup_runs: int,
    measured_runs: int,
) -> dict[str, Any]:
    for _ in range(warmup_runs):
        operation()
    durations = np.empty(measured_runs, dtype=np.float64)
    for index in range(measured_runs):
        started = time.perf_counter_ns()
        operation()
        durations[index] = (time.perf_counter_ns() - started) / 1_000_000.0
    return {
        "runs": measured_runs,
        "p50_ms": float(np.percentile(durations, 50)),
        "p95_ms": float(np.percentile(durations, 95)),
        "p99_ms": float(np.percentile(durations, 99)),
        "minimum_ms": float(np.min(durations)),
        "maximum_ms": float(np.max(durations)),
    }


def run_benchmarks(
    output_directory: str | Path,
    *,
    measured_runs: int = 200,
) -> dict[str, Any]:
    if measured_runs < 20:
        raise ValueError("measured_runs must be at least 20")
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    owned_artifacts = (
        "append-benchmark.sqlite3",
        "query-benchmark.sqlite3",
        "performance-report.json",
        "environment.json",
    )
    existing = [name for name in owned_artifacts if (output / name).exists()]
    if existing:
        raise FileExistsError("benchmark output must be fresh; existing artifacts: " + ", ".join(existing))
    warmup = 5

    validation_counter = 0

    def validate_one() -> None:
        nonlocal validation_counter
        validation_counter += 1
        record = branch_record(
            branch_id=f"branch.validation.{validation_counter}",
            branch_kind="accepted",
            policy_id="policy.benchmark",
            permitted_state_kinds=["reconciled"],
        )
        source = submission(
            "branch.schema.json",
            record,
            token=f"validation.{validation_counter}",
        )
        errors = submission_errors(source)
        completed = finalize_record(
            "branch.schema.json",
            record,
            sequence=validation_counter,
            recorded_at="2026-07-29T00:00:00Z",
        )
        errors.extend(stored_record_errors("branch.schema.json", completed))
        if errors:
            raise RuntimeError("; ".join(errors))

    validation = _measure(
        validate_one,
        warmup_runs=warmup,
        measured_runs=measured_runs,
    )

    append_store = AuthoritativeStore(output / "append-benchmark.sqlite3")
    append_counter = 0

    def append_one() -> None:
        nonlocal append_counter
        append_counter += 1
        append_store.append(
            submission(
                "branch.schema.json",
                branch_record(
                    branch_id=f"branch.append.{append_counter}",
                    branch_kind="accepted",
                    policy_id="policy.benchmark",
                    permitted_state_kinds=["reconciled"],
                ),
                token=f"append.{append_counter}",
            )
        )

    append = _measure(
        append_one,
        warmup_runs=warmup,
        measured_runs=measured_runs,
    )
    append_integrity = append_store.verify_integrity()
    append_store.close()

    small_scenario, _ = generate_trial(
        window_index=0,
        action_kind="nominal",
        seed=3001,
    )
    tile_count = 256 * 256
    repeats = int(np.ceil(tile_count / small_scenario.prior.size))
    prior = np.tile(small_scenario.prior.ravel(), repeats)[:tile_count].reshape((256, 256))
    envelope = np.tile(small_scenario.action.operational_envelope.ravel(), repeats)[:tile_count].reshape((256, 256))
    large_evidence = []
    for item in small_scenario.evidence[:4]:
        values = np.tile(item.values.ravel(), repeats)[:tile_count].reshape((256, 256))
        coverage = np.ones((256, 256), dtype=bool)
        large_evidence.append(
            type(item)(
                claim_id=item.claim_id,
                robot_id=item.robot_id,
                values=values,
                coverage=coverage,
                valid_start=item.valid_start,
                valid_end=item.valid_end,
                received_sequence=item.received_sequence,
                source_time=item.source_time,
                variance_m2=item.variance_m2,
                provenance_complete=item.provenance_complete,
                dependency_group=item.dependency_group,
            )
        )
    large_action = type(small_scenario.action)(
        action_id=small_scenario.action.action_id,
        start=small_scenario.action.start,
        end=small_scenario.action.end,
        operational_envelope=envelope,
        volume_tolerance_cells=200.0,
        outside_envelope_tolerance_m=(small_scenario.action.outside_envelope_tolerance_m),
    )
    replay_hashes: set[str | None] = set()

    def reconcile_one() -> None:
        result = reconcile_rasters(
            large_evidence,
            prior=prior,
            action=large_action,
            known_at_sequence=4,
            policy=ReconciliationPolicy(),
        )
        replay_hashes.add(result.state_hash())

    reconcile = _measure(
        reconcile_one,
        warmup_runs=warmup,
        measured_runs=measured_runs,
    )

    query_store, multi_report = run_multi_robot_closed_loop(output / "query-benchmark.sqlite3")
    revision = query_store.get(multi_report["revision_id"])
    if revision is None:
        query_store.close()
        raise RuntimeError("benchmark revision was not durable")

    def query_one() -> None:
        result = query_store.query_revision(
            world_id="world.lunar",
            site_id="site.haworth",
            branch_id="branch.accepted",
            valid_at=10.0,
            known_at_sequence=revision["transaction_time"]["sequence"],
            state_kinds=["reconciled"],
        )
        if result is None:
            raise RuntimeError("benchmark query unexpectedly returned no state")

    current_query = _measure(
        query_one,
        warmup_runs=warmup,
        measured_runs=measured_runs,
    )
    query_integrity = query_store.verify_integrity()
    query_store.close()

    targets = {
        "evidence_validate_p95_ms": 100.0,
        "durable_event_append_p95_ms": 100.0,
        "reconcile_p95_ms": 500.0,
        "reconcile_p99_ms": 1000.0,
        "current_state_query_p95_ms": 100.0,
        "deterministic_replay_mismatch_count": 0,
    }
    observations = {
        "evidence_validate_p95_ms": validation["p95_ms"],
        "durable_event_append_p95_ms": append["p95_ms"],
        "reconcile_p95_ms": reconcile["p95_ms"],
        "reconcile_p99_ms": reconcile["p99_ms"],
        "current_state_query_p95_ms": current_query["p95_ms"],
        "deterministic_replay_mismatch_count": max(0, len(replay_hashes) - 1),
    }
    budget_results = {
        name: {
            "target": target,
            "observed": observations[name],
            "pass": (
                observations[name] <= target
                if name != "deterministic_replay_mismatch_count"
                else observations[name] == target
            ),
        }
        for name, target in targets.items()
    }
    report: dict[str, Any] = {
        "schema_version": "stewie.performance_report/1.0",
        "status": "measured_partial_budget",
        "claim_limit": (
            "Microbenchmarks cover implemented in-process paths on this host. "
            "Cold-cache, 1000-version replay, distributed sync, and scaling "
            "levels remain unmeasured."
        ),
        "protocol": {
            "warmup_runs": warmup,
            "measured_runs": measured_runs,
            "clock": "time.perf_counter_ns",
            "append_journal_mode": "wal",
            "append_synchronous": "full",
            "terrain_shape": [256, 256],
            "observation_sources": len(large_evidence),
        },
        "environment": {
            "platform": platform.platform(),
            "python": sys.version,
            "numpy": np.__version__,
            "cpu_count": os.cpu_count(),
            "peak_rss_raw": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
        "build_identity": build_identity(),
        "measurements": {
            "evidence_validation": validation,
            "durable_append": append,
            "reconciliation": reconcile,
            "current_bitemporal_query": current_query,
        },
        "budget_results": budget_results,
        "all_measured_targets_pass": all(item["pass"] for item in budget_results.values()),
        "integrity": {
            "append_store": append_integrity,
            "query_store": query_integrity,
        },
        "unmeasured_budget_items": [
            "bitemporal_query_p95_ms_as_distinct_workload",
            "provenance_trace_p95_ms",
            "replay_1000_versions_s",
            "authoritative_metadata_per_claim_kib",
            "cold_cache_latency",
            "concurrency_levels_2_and_4",
            "scaling_workload",
            "distributed_sync",
        ],
    }
    report["report_content_hash"] = sha256_json(report)
    (output / "performance-report.json").write_bytes(canonical_bytes(report) + b"\n")
    (output / "environment.json").write_text(
        json.dumps(report["environment"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report
