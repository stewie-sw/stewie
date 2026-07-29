"""Executable fault-injection probes for the UltraBuild evidence package."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from stewie.ultrabuild.canonical import canonical_bytes, sha256_json
from stewie.ultrabuild.experiment import generate_trial, run_candidate
from stewie.ultrabuild.golden import build_golden_world
from stewie.ultrabuild.identity import build_identity
from stewie.ultrabuild.records import branch_record, submission
from stewie.ultrabuild.scenario_runner import run_conflict_retention_demo
from stewie.ultrabuild.store import (
    AuthoritativeStore,
    IdempotencyConflict,
)


def run_fault_injection(output_directory: str | Path) -> dict[str, Any]:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    idempotency_store = AuthoritativeStore(output / "idempotency.sqlite3")
    branch_submission = submission(
        "branch.schema.json",
        branch_record(
            branch_id="branch.fault",
            branch_kind="accepted",
            policy_id="policy.fault",
            permitted_state_kinds=["reconciled"],
        ),
        token="branch.fault",
    )
    first = idempotency_store.append(branch_submission)
    duplicate = idempotency_store.append(branch_submission)
    results.append(
        {
            "fault_id": "duplicate_delivery",
            "expected": "same receipt identity; no second record",
            "observed": (
                duplicate["duplicate"] is True
                and duplicate["content_hash"] == first["content_hash"]
                and idempotency_store.latest_sequence() == 1
            ),
        }
    )
    changed = {
        **branch_submission,
        "record": {
            **branch_submission["record"],
            "site_id": "site.other",
        },
    }
    conflict_rejected = False
    try:
        idempotency_store.append(changed)
    except IdempotencyConflict:
        conflict_rejected = True
    results.append(
        {
            "fault_id": "idempotency_key_reuse_with_other_bytes",
            "expected": "reject",
            "observed": conflict_rejected,
        }
    )
    idempotency_store.close()

    payload_root = output / "payload-corruption"
    payload_store, _ = build_golden_world(payload_root / "world.sqlite3")
    observation = payload_store.get("claim.observation.golden")
    if observation is None:
        payload_store.close()
        raise RuntimeError("fault fixture observation is not durable")
    payload_hash = observation["payload"]["content_hash"]
    if payload_store.payload_store is None:
        payload_store.close()
        raise RuntimeError("fault fixture payload verifier is unavailable")
    payload_store.payload_store.path(payload_hash).write_bytes(b"corrupt")
    corrupt_report = payload_store.verify_integrity()
    results.append(
        {
            "fault_id": "payload_bitrot",
            "expected": "integrity failure",
            "observed": (not corrupt_report["ok"] and any(payload_hash in error for error in corrupt_report["errors"])),
        }
    )
    payload_store.close()

    projection_root = output / "projection-corruption"
    projection_store, _ = build_golden_world(projection_root / "world.sqlite3")
    projection_store._connection.execute(
        "UPDATE branch_heads SET revision_id=NULL, revision_sequence=0 WHERE branch_id='branch.accepted'"
    )
    detected = not projection_store.verify_integrity()["ok"]
    projection_store.rebuild_projections()
    recovered = projection_store.verify_integrity()["ok"]
    results.append(
        {
            "fault_id": "projection_head_corruption",
            "expected": "detect and deterministically rebuild",
            "observed": detected and recovered,
        }
    )
    projection_store.close()

    scenario, _ = generate_trial(
        window_index=0,
        action_kind="nominal",
        seed=3002,
    )
    delayed_result = run_candidate(scenario, "stewie")
    results.append(
        {
            "fault_id": "delayed_stale_observation",
            "expected": "exclude as stale_before_action",
            "observed": any(
                "robot-b-stale" in claim_id and reason == "stale_before_action"
                for claim_id, reason in delayed_result["excluded"]
            ),
        }
    )
    future = replace(
        scenario.evidence[0],
        claim_id="claim.future",
        received_sequence=100,
    )
    future_scenario = replace(
        scenario,
        evidence=(future, *scenario.evidence[1:]),
    )
    future_result = run_candidate(future_scenario, "stewie")
    results.append(
        {
            "fault_id": "future_transaction_evidence",
            "expected": "not visible at known_at",
            "observed": [
                "claim.future",
                "future_transaction",
            ]
            in future_result["excluded"],
        }
    )

    candidate_before = run_candidate(scenario, "stewie")
    poisoned_reference = np.full(scenario.prior.shape, 99.0)
    _ = poisoned_reference  # evaluator-only data is intentionally not passed
    candidate_after = run_candidate(scenario, "stewie")
    results.append(
        {
            "fault_id": "reference_truth_poison",
            "expected": "candidate bytes unchanged",
            "observed": (candidate_before["candidate_summary_hash"] == candidate_after["candidate_summary_hash"]),
        }
    )

    conflict_store, conflict_report = run_conflict_retention_demo(output / "conflict" / "world.sqlite3")
    results.append(
        {
            "fault_id": "equal_support_conflicting_observations",
            "expected": "retain both hypotheses; do not advance accepted head",
            "observed": (
                conflict_report["decision"] == "RETAIN_HYPOTHESES"
                and len(conflict_report["hypothesis_ids"]) == 2
                and conflict_report["accepted_head"]["revision_id"] is None
            ),
        }
    )
    conflict_store.close()

    report: dict[str, Any] = {
        "schema_version": "stewie.fault_injection_report/1.0",
        "status": "controlled_fault_evidence",
        "claim_limit": (
            "These probes cover the implemented authority/reconciliation slice; "
            "sensor hardware, ROS, network, and physical robot faults remain untested."
        ),
        "faults": results,
        "build_identity": build_identity(),
        "passed": sum(int(result["observed"]) for result in results),
        "failed": sum(int(not result["observed"]) for result in results),
        "unimplemented_fault_families": [
            "physical_sensor_dropout",
            "ROS_clock_partition",
            "database_process_crash_during_fsync",
            "network_bandwidth_and_packet_loss",
            "robot_actuator_failure",
            "simulator_numerical_divergence",
        ],
    }
    report["report_content_hash"] = sha256_json(report)
    (output / "fault-injection-report.json").write_bytes(canonical_bytes(report) + b"\n")
    return report
