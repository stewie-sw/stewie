from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np

from stewie.ultrabuild.experiment import (
    METHODS,
    evaluate_candidate,
    generate_trial,
    run_candidate,
    run_controlled_evaluation,
)
from stewie.ultrabuild.reconciliation import (
    ActionContext,
    RasterEvidence,
    ReconciliationPolicy,
    reconcile_rasters,
)


def test_candidate_cannot_observe_reference_poison() -> None:
    scenario, reference = generate_trial(
        window_index=0,
        action_kind="nominal",
        seed=3001,
    )
    before = run_candidate(scenario, "stewie")
    poisoned = replace(
        reference,
        terrain=np.full_like(reference.terrain, 999.0),
        content_hash="f" * 64,
    )
    after = run_candidate(scenario, "stewie")
    assert before["candidate_summary_hash"] == after["candidate_summary_hash"]
    assert before["state_hash"] == after["state_hash"]
    assert evaluate_candidate(before, reference) != evaluate_candidate(
        before, poisoned
    )


def test_stale_latest_and_timestamp_baselines_commit_harmful_plan() -> None:
    scenario, reference = generate_trial(
        window_index=2,
        action_kind="nominal",
        seed=3003,
    )
    stewie = run_candidate(scenario, "stewie")
    latest = run_candidate(scenario, "latest_overwrite")
    timestamp = run_candidate(scenario, "timestamp_only")
    assert evaluate_candidate(stewie, reference)["harmful_plan"] is False
    assert evaluate_candidate(latest, reference)["harmful_plan"] is True
    assert evaluate_candidate(timestamp, reference)["harmful_plan"] is True
    assert any(
        reason == "stale_before_action"
        for _, reason in stewie["excluded"]
    )


def test_physics_changes_admissibility_but_does_not_override_observation() -> None:
    scenario, _ = generate_trial(
        window_index=1,
        action_kind="partial",
        seed=3002,
    )
    gated = run_candidate(scenario, "stewie")
    ungated = run_candidate(scenario, "no_physics")
    physics_exclusions = {
        claim_id
        for claim_id, reason in gated["excluded"]
        if reason == "physics_inconsistent"
    }
    assert physics_exclusions
    assert physics_exclusions.issubset(set(ungated["admitted_claim_ids"]))
    assert gated["state_hash"] != ungated["state_hash"]

    failed_scenario, failed_reference = generate_trial(
        window_index=1,
        action_kind="failed",
        seed=3002,
    )
    failed = run_candidate(failed_scenario, "stewie")
    evaluation = evaluate_candidate(failed, failed_reference)
    assert evaluation["rmse_m"] < 0.05
    assert np.max(np.abs(failed["state"])) < 0.1


def test_physics_gate_is_noninterfering_when_all_evidence_is_plausible() -> None:
    scenario, _ = generate_trial(
        window_index=3,
        action_kind="nominal",
        seed=3001,
    )
    plausible_only = tuple(scenario.evidence[:2])
    scenario = type(scenario)(
        unit_id=scenario.unit_id,
        seed=scenario.seed,
        action_kind=scenario.action_kind,
        prior=scenario.prior,
        planned_change=scenario.planned_change,
        action=scenario.action,
        evidence=plausible_only,
    )
    gated = run_candidate(scenario, "stewie")
    ungated = run_candidate(scenario, "no_physics")
    assert gated["state_hash"] == ungated["state_hash"]
    assert gated["admitted_claim_ids"] == ungated["admitted_claim_ids"]


def test_competing_physical_hypotheses_are_retained() -> None:
    prior = np.zeros((4, 4), dtype=np.float64)
    envelope = np.ones((4, 4), dtype=bool)
    action = ActionContext(
        action_id="action.conflict",
        start=1.0,
        end=2.0,
        operational_envelope=envelope,
        volume_tolerance_cells=0.01,
        outside_envelope_tolerance_m=0.01,
    )
    first = prior.copy()
    first[:, :2] = -1.0
    first[:, 2:] = 1.0
    second = prior.copy()
    second[:, :2] = -0.5
    second[:, 2:] = 0.5
    coverage = np.ones((4, 4), dtype=bool)
    evidence = [
        RasterEvidence(
            claim_id="claim.full",
            robot_id="robot.a",
            values=first,
            coverage=coverage,
            valid_start=2.0,
            valid_end=3.0,
            received_sequence=1,
            source_time=2.0,
            variance_m2=0.01,
            provenance_complete=True,
            dependency_group="source.a",
        ),
        RasterEvidence(
            claim_id="claim.partial",
            robot_id="robot.b",
            values=second,
            coverage=coverage,
            valid_start=2.0,
            valid_end=3.0,
            received_sequence=2,
            source_time=2.0,
            variance_m2=0.01,
            provenance_complete=True,
            dependency_group="source.b",
        ),
    ]
    result = reconcile_rasters(
        evidence,
        prior=prior,
        action=action,
        known_at_sequence=2,
        policy=ReconciliationPolicy(),
    )
    assert result.decision == "RETAIN_HYPOTHESES"
    assert result.state is None
    assert result.hypotheses == (("claim.full",), ("claim.partial",))


def test_dependency_group_does_not_gain_support_from_exact_duplicate() -> None:
    scenario, _ = generate_trial(
        window_index=4,
        action_kind="nominal",
        seed=3001,
    )
    first = scenario.evidence[0]
    duplicate = RasterEvidence(
        claim_id="claim.duplicate",
        robot_id=first.robot_id,
        values=first.values.copy(),
        coverage=first.coverage.copy(),
        valid_start=first.valid_start,
        valid_end=first.valid_end,
        received_sequence=5,
        source_time=first.source_time,
        variance_m2=first.variance_m2,
        provenance_complete=True,
        dependency_group=first.dependency_group,
    )
    with_duplicate = reconcile_rasters(
        [first, duplicate],
        prior=scenario.prior,
        action=scenario.action,
        known_at_sequence=5,
    )
    without_duplicate = reconcile_rasters(
        [first],
        prior=scenario.prior,
        action=scenario.action,
        known_at_sequence=5,
    )
    assert with_duplicate.state_hash() == without_duplicate.state_hash()
    assert (
        with_duplicate.diagnostics["effective_support"]
        == without_duplicate.diagnostics["effective_support"]
    )


def test_controlled_evaluation_is_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    report_a = run_controlled_evaluation(first)
    report_b = run_controlled_evaluation(second)
    assert report_a == report_b
    assert (first / "trials.jsonl").read_bytes() == (
        second / "trials.jsonl"
    ).read_bytes()
    assert report_a["trial_count"] == 24 * 8 * len(METHODS)
    assert report_a["aggregates"]["stewie"]["harmful_plan_count"] == 0
    assert (
        report_a["aggregates"]["latest_overwrite"]["harmful_plan_count"]
        > 0
    )
