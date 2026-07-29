"""Adversarial referential-integrity tests for the UltraBuild world-state graph.

These tests intentionally mutate completed records after constructing a valid graph.
They assert the semantic rejection reason, not merely a stale content hash, and keep
validator crash-freedom part of every negative-test contract.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from stewie.ultrabuild.canonical import record_content_hash, sha256_json
from stewie.ultrabuild.contracts import (
    PRIMARY_KEY_BY_SCHEMA,
    finalize_record,
    load_schema,
    record_set_errors,
)
from stewie.ultrabuild.golden import append_with_provenance, build_golden_world
from stewie.ultrabuild.records import (
    candidate_record,
    observation_record,
    promoted_revision_record,
    promotion_decision_record,
    provenance_record,
    submission,
)


RECORDED_AT = "2026-07-29T00:00:00Z"
SCHEMA_BY_VERSION = {
    str(load_schema(schema_name)["properties"]["schema_version"]["const"]): schema_name
    for schema_name in PRIMARY_KEY_BY_SCHEMA
}


def _reseal(record: dict[str, Any]) -> None:
    record["content_hash"] = record_content_hash(record)


def _safe_errors(
    graph: list[tuple[str, dict[str, Any]]],
) -> list[str]:
    """Make an exception from adversarial input an explicit test failure."""

    try:
        errors = record_set_errors(graph)
    except Exception as exc:  # pragma: no cover - the failure message is the contract
        pytest.fail(f"validator crashed on adversarial graph: {exc!r}")
    assert isinstance(errors, list)
    assert all(isinstance(error, str) for error in errors)
    return errors


def _assert_error(
    graph: list[tuple[str, dict[str, Any]]],
    expected_fragment: str,
) -> None:
    errors = _safe_errors(graph)
    assert any(expected_fragment in error for error in errors), (
        f"missing semantic error fragment {expected_fragment!r}; validator returned {errors!r}"
    )


def _golden_graph(
    tmp_path: Path,
) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, str]]:
    store, ids = build_golden_world(tmp_path / "authority.sqlite3")
    try:
        graph = [(SCHEMA_BY_VERSION[str(record["schema_version"])], deepcopy(record)) for record in store.records()]
    finally:
        store.close()
    assert _safe_errors(graph) == []
    return graph, ids


def _record(
    graph: list[tuple[str, dict[str, Any]]],
    record_id: str,
) -> dict[str, Any]:
    for schema_name, record in graph:
        key = PRIMARY_KEY_BY_SCHEMA[schema_name]
        if record.get(key) == record_id:
            return record
    raise AssertionError(f"record absent from fixture: {record_id}")


def _latest_sequence(graph: list[tuple[str, dict[str, Any]]]) -> int:
    return max(
        int(record["transaction_time"]["sequence"])
        for _, record in graph
        if isinstance(record.get("transaction_time"), dict)
    )


def _append_completed(
    graph: list[tuple[str, dict[str, Any]]],
    schema_name: str,
    submitted_record: dict[str, Any],
) -> dict[str, Any]:
    """Append test-local provenance and a completed record to an in-memory graph."""

    record = deepcopy(submitted_record)
    record.pop("transaction_time", None)
    record.pop("content_hash", None)
    record.pop("recorded_at", None)
    bundle = provenance_record(
        schema_name,
        record,
        bundle_id=str(record["provenance_bundle_id"]),
    )
    sequence = _latest_sequence(graph) + 1
    stored_bundle = finalize_record(
        "provenance_bundle.schema.json",
        bundle,
        sequence=sequence,
        recorded_at=RECORDED_AT,
    )
    stored_record = finalize_record(
        schema_name,
        record,
        sequence=sequence + 1,
        recorded_at=RECORDED_AT,
    )
    graph.extend(
        [
            ("provenance_bundle.schema.json", stored_bundle),
            (schema_name, stored_record),
        ]
    )
    return stored_record


def _supersession_record(
    *,
    event_id: str,
    target_record_id: str,
    successor_record_id: str,
    provenance_bundle_id: str,
    evidence_id: str,
    branch_id: str = "branch.accepted",
) -> dict[str, Any]:
    return {
        "schema_version": "stewie.supersession_event/1.0",
        "event_id": event_id,
        "world_id": "world.lunar",
        "site_id": "site.haworth",
        "branch_id": branch_id,
        "event_kind": "supersede",
        "target_record_id": target_record_id,
        "successor_record_id": successor_record_id,
        "reason_codes": ["state.corrected"],
        "evidence_ids": [evidence_id],
        "provenance_bundle_id": provenance_bundle_id,
    }


def _conflict_graph(
    tmp_path: Path,
) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, str]]:
    graph, ids = _golden_graph(tmp_path)
    first = _record(graph, ids["observation_id"])
    payload = first["payload"]
    assert isinstance(payload, dict)

    second = _append_completed(
        graph,
        "evidence_claim.schema.json",
        observation_record(
            claim_id="claim.observation.peer",
            provenance_bundle_id="provenance.observation.peer",
            payload_hash=str(payload["content_hash"]),
            coverage_hash=str(payload["coverage_hash"]),
        ),
    )
    unrelated = _append_completed(
        graph,
        "evidence_claim.schema.json",
        observation_record(
            claim_id="claim.observation.unrelated",
            provenance_bundle_id="provenance.observation.unrelated",
            payload_hash=str(payload["content_hash"]),
            coverage_hash=str(payload["coverage_hash"]),
        ),
    )
    claim_ids = [ids["observation_id"], str(second["claim_id"])]
    overlap_valid_time = {
        "start": 10.0,
        "end": 11.0,
        "clock_id": "clock.mission",
    }
    conflict = {
        "schema_version": "stewie.conflict_record/1.0",
        "conflict_id": "conflict.observation.pair",
        "world_id": "world.lunar",
        "site_id": "site.haworth",
        "branch_id": "branch.evidence",
        "claim_ids": claim_ids,
        "reason_codes": ["observations.disagree"],
        "spatial_overlap_hash": sha256_json(
            {
                "claim_ids": sorted(claim_ids),
                "bounds": [0.0, 0.0, 10.0, 10.0],
                "valid_time": overlap_valid_time,
            }
        ),
        "valid_time": {
            **overlap_valid_time,
            "uncertainty_s": 0.01,
        },
        "hypothesis_set_id": "hypotheses.observation.pair",
        "status": "open",
        "provenance_bundle_id": "provenance.conflict.observation.pair",
    }
    hypotheses = {
        "schema_version": "stewie.hypothesis_set/1.0",
        "hypothesis_set_id": "hypotheses.observation.pair",
        "world_id": "world.lunar",
        "site_id": "site.haworth",
        "branch_id": "branch.evidence",
        "conflict_id": "conflict.observation.pair",
        "hypotheses": [
            {
                "hypothesis_id": "hypothesis.observation.primary",
                "claim_ids": [claim_ids[0]],
                "supporting_evidence_ids": [],
            },
            {
                "hypothesis_id": "hypothesis.observation.peer",
                "claim_ids": [claim_ids[1]],
                "supporting_evidence_ids": [],
            },
        ],
        "status": "open",
        "provenance_bundle_id": "provenance.hypotheses.observation.pair",
    }
    _append_completed(graph, "conflict_record.schema.json", conflict)
    _append_completed(graph, "hypothesis_set.schema.json", hypotheses)
    assert _safe_errors(graph) == []
    return graph, {
        **ids,
        "second_observation_id": str(second["claim_id"]),
        "unrelated_observation_id": str(unrelated["claim_id"]),
        "conflict_id": str(conflict["conflict_id"]),
        "hypothesis_set_id": str(hypotheses["hypothesis_set_id"]),
    }


@pytest.mark.parametrize(
    ("owner_id", "field", "future_id", "expected_fragment"),
    [
        (
            "candidate.golden",
            "prior_revision_id",
            "revision.accepted.golden",
            "prior_revision_id: referenced record is not transactionally earlier",
        ),
        (
            "revision.accepted.golden",
            "event_ids",
            "event.rescan.golden",
            "event_ids: referenced record is not transactionally earlier",
        ),
    ],
)
def test_future_references_are_rejected_without_validator_crash(
    tmp_path: Path,
    owner_id: str,
    field: str,
    future_id: str,
    expected_fragment: str,
) -> None:
    graph, _ = _golden_graph(tmp_path)
    owner = _record(graph, owner_id)
    owner[field] = [future_id] if field.endswith("_ids") else future_id
    _reseal(owner)
    _assert_error(graph, expected_fragment)


@pytest.mark.parametrize(
    ("mutation", "expected_fragment"),
    [
        (
            "subject_record_mismatch",
            "provenance_bundle_id: bundle subject names another record",
        ),
        (
            "source_agent_mismatch",
            "provenance_bundle_id: source agent does not close",
        ),
        (
            "activity_version_mismatch",
            "provenance_bundle_id: processing activity/version does not close",
        ),
        (
            "activity_removed",
            "subject.generating_activity_id: activity is absent",
        ),
        (
            "calibration_reference_removed",
            "provenance_bundle_id: calibration chain does not close",
        ),
        (
            "transform_reference_removed",
            "provenance_bundle_id: transform chain does not close",
        ),
    ],
)
def test_observation_provenance_mismatch_or_removal_is_rejected(
    tmp_path: Path,
    mutation: str,
    expected_fragment: str,
) -> None:
    graph, ids = _golden_graph(tmp_path)
    observation = _record(graph, ids["observation_id"])
    bundle = _record(graph, str(observation["provenance_bundle_id"]))
    subject = bundle["subject"]
    assert isinstance(subject, dict)

    if mutation == "subject_record_mismatch":
        subject["record_id"] = "claim.observation.other"
        _reseal(bundle)
    elif mutation == "source_agent_mismatch":
        source = observation["source"]
        assert isinstance(source, dict)
        source["agent_id"] = "robot.other"
        _reseal(observation)
    elif mutation == "activity_version_mismatch":
        activities = bundle["activities"]
        assert isinstance(activities, list) and activities
        activities[0]["algorithm_version"] = "stereo.v999"
        _reseal(bundle)
    elif mutation == "activity_removed":
        bundle["activities"] = []
        _reseal(bundle)
    elif mutation == "calibration_reference_removed":
        calibration_ids = subject["calibration_ids"]
        assert isinstance(calibration_ids, list) and calibration_ids
        calibration_ids.pop()
        _reseal(bundle)
    elif mutation == "transform_reference_removed":
        transform_ids = subject["transform_ids"]
        assert isinstance(transform_ids, list) and transform_ids
        transform_ids.clear()
        _reseal(bundle)
    else:  # pragma: no cover - parametrization exhausts this branch
        raise AssertionError(f"unknown mutation {mutation}")

    _assert_error(graph, expected_fragment)


def test_rejected_review_is_a_semantic_promotion_error(
    tmp_path: Path,
) -> None:
    graph, ids = _golden_graph(tmp_path)
    decision = _record(graph, ids["promotion_decision_id"])
    review = decision["review"]
    assert isinstance(review, dict)
    review["status"] = "rejected"
    _reseal(decision)
    _assert_error(
        graph,
        "review.status: pending/rejected review cannot promote",
    )


def test_rejected_review_cannot_leave_partial_promotion_records(
    tmp_path: Path,
) -> None:
    store, ids = build_golden_world(tmp_path / "authority.sqlite3")
    try:
        observation = store.get(ids["observation_id"])
        prior = store.get(ids["revision_id"])
        assert observation is not None and prior is not None
        candidate = append_with_provenance(
            store,
            "state_candidate.schema.json",
            candidate_record(
                observation,
                candidate_id="candidate.rejected-review",
                provenance_bundle_id="provenance.candidate.rejected-review",
                prior_revision_id=str(prior["revision_id"]),
            ),
            token="candidate.rejected-review",
        )
        decision = promotion_decision_record(
            candidate,
            revision_id="revision.rejected-review",
            decision_id="decision.rejected-review",
            provenance_bundle_id="provenance.decision.rejected-review",
        )
        review = decision["review"]
        assert isinstance(review, dict)
        review["status"] = "rejected"
        revision = promoted_revision_record(
            candidate,
            decision,
            event_id=ids["external_action_id"],
            provenance_bundle_id="provenance.revision.rejected-review",
            branch_revision_sequence=2,
        )
        provenance_submissions = [
            submission(
                "provenance_bundle.schema.json",
                provenance_record(
                    "reconciliation_decision.schema.json",
                    decision,
                    bundle_id=str(decision["provenance_bundle_id"]),
                ),
                token="decision.rejected-review.provenance",
            ),
            submission(
                "provenance_bundle.schema.json",
                provenance_record(
                    "world_revision.schema.json",
                    revision,
                    bundle_id=str(revision["provenance_bundle_id"]),
                ),
                token="revision.rejected-review.provenance",
            ),
        ]
        before = store.latest_sequence()
        receipt = store.commit_promotion(
            operation_id="operation.rejected-review",
            expected_head_revision_id=ids["revision_id"],
            expected_head_sequence=1,
            provenance_submissions=provenance_submissions,
            decision_submission=submission(
                "reconciliation_decision.schema.json",
                decision,
                token="decision.rejected-review",
            ),
            revision_submission=submission(
                "world_revision.schema.json",
                revision,
                token="revision.rejected-review",
            ),
        )
        assert receipt["applied"] is False
        assert receipt["reason_code"] == "invalid_promotion"
        assert receipt["append_receipt_ids"] == []
        assert store.latest_sequence() == before
        assert store.get(str(decision["decision_id"])) is None
        assert store.get(str(revision["revision_id"])) is None
    finally:
        store.close()


def test_self_supersession_is_rejected(
    tmp_path: Path,
) -> None:
    graph, ids = _golden_graph(tmp_path)
    _append_completed(
        graph,
        "supersession_event.schema.json",
        _supersession_record(
            event_id="supersession.self",
            target_record_id=ids["revision_id"],
            successor_record_id=ids["revision_id"],
            provenance_bundle_id="provenance.supersession.self",
            evidence_id=ids["observation_id"],
        ),
    )
    _assert_error(
        graph,
        "successor_record_id: target cannot supersede itself",
    )


def test_supersession_cycle_is_rejected(
    tmp_path: Path,
) -> None:
    graph, ids = _golden_graph(tmp_path)
    _append_completed(
        graph,
        "supersession_event.schema.json",
        _supersession_record(
            event_id="supersession.cycle.a",
            target_record_id=ids["external_action_id"],
            successor_record_id=ids["planned_action_id"],
            provenance_bundle_id="provenance.supersession.cycle.a",
            evidence_id=ids["observation_id"],
        ),
    )
    _append_completed(
        graph,
        "supersession_event.schema.json",
        _supersession_record(
            event_id="supersession.cycle.b",
            target_record_id=ids["planned_action_id"],
            successor_record_id=ids["external_action_id"],
            provenance_bundle_id="provenance.supersession.cycle.b",
            evidence_id=ids["observation_id"],
        ),
    )
    _assert_error(
        graph,
        f"supersession chain: cycle reachable from {ids['external_action_id']}",
    )


def test_cross_branch_successor_is_rejected(
    tmp_path: Path,
) -> None:
    graph, ids = _golden_graph(tmp_path)
    _append_completed(
        graph,
        "supersession_event.schema.json",
        _supersession_record(
            event_id="supersession.cross-branch",
            target_record_id="branch.accepted",
            successor_record_id="branch.evidence",
            provenance_bundle_id="provenance.supersession.cross-branch",
            evidence_id=ids["observation_id"],
        ),
    )
    _assert_error(
        graph,
        "successor_record_id: successor is on another branch",
    )


def test_target_cannot_have_two_effective_successors(
    tmp_path: Path,
) -> None:
    graph, ids = _golden_graph(tmp_path)
    alternate = deepcopy(_record(graph, ids["planned_action_id"]))
    alternate["event_id"] = "event.rescan.alternate"
    alternate["provenance_bundle_id"] = "provenance.event.rescan.alternate"
    alternate = _append_completed(
        graph,
        "action_event.schema.json",
        alternate,
    )
    _append_completed(
        graph,
        "supersession_event.schema.json",
        _supersession_record(
            event_id="supersession.double.a",
            target_record_id=ids["external_action_id"],
            successor_record_id=ids["planned_action_id"],
            provenance_bundle_id="provenance.supersession.double.a",
            evidence_id=ids["observation_id"],
        ),
    )
    _append_completed(
        graph,
        "supersession_event.schema.json",
        _supersession_record(
            event_id="supersession.double.b",
            target_record_id=ids["external_action_id"],
            successor_record_id=str(alternate["event_id"]),
            provenance_bundle_id="provenance.supersession.double.b",
            evidence_id=ids["observation_id"],
        ),
    )
    _assert_error(
        graph,
        f"target_record_id: {ids['external_action_id']} has multiple effective successors",
    )


@pytest.mark.parametrize(
    ("dimension", "expected_fragment"),
    [
        (
            "spatial",
            "claim_ids: conflict claims have no common spatial overlap",
        ),
        (
            "valid_time",
            "claim_ids: conflict claims have no common valid-time overlap",
        ),
    ],
)
def test_non_overlapping_claims_cannot_form_a_conflict(
    tmp_path: Path,
    dimension: str,
    expected_fragment: str,
) -> None:
    graph, ids = _conflict_graph(tmp_path)
    second = _record(graph, ids["second_observation_id"])
    if dimension == "spatial":
        spatial = second["spatial"]
        assert isinstance(spatial, dict)
        spatial["bounds"] = [20.0, 20.0, 30.0, 30.0]
    else:
        valid = second["valid_time"]
        assert isinstance(valid, dict)
        valid["start"] = 20.0
        valid["end"] = 21.0
    _reseal(second)
    _assert_error(graph, expected_fragment)


def test_duplicate_hypothesis_ids_are_rejected(
    tmp_path: Path,
) -> None:
    graph, ids = _conflict_graph(tmp_path)
    hypothesis_set = _record(graph, ids["hypothesis_set_id"])
    hypotheses = hypothesis_set["hypotheses"]
    assert isinstance(hypotheses, list) and len(hypotheses) == 2
    hypotheses[1]["hypothesis_id"] = hypotheses[0]["hypothesis_id"]
    _reseal(hypothesis_set)
    _assert_error(
        graph,
        "hypotheses: hypothesis IDs must be unique",
    )


def test_duplicate_hypothesis_claim_assignments_are_rejected(
    tmp_path: Path,
) -> None:
    graph, ids = _conflict_graph(tmp_path)
    hypothesis_set = _record(graph, ids["hypothesis_set_id"])
    hypotheses = hypothesis_set["hypotheses"]
    assert isinstance(hypotheses, list) and len(hypotheses) == 2
    hypotheses[1]["claim_ids"] = list(hypotheses[0]["claim_ids"])
    _reseal(hypothesis_set)
    _assert_error(
        graph,
        "hypotheses: duplicate claim assignments are forbidden",
    )


def test_hypotheses_cannot_omit_a_conflicted_claim(
    tmp_path: Path,
) -> None:
    graph, ids = _conflict_graph(tmp_path)
    hypothesis_set = _record(graph, ids["hypothesis_set_id"])
    hypotheses = hypothesis_set["hypotheses"]
    assert isinstance(hypotheses, list) and len(hypotheses) == 2
    hypotheses[1]["claim_ids"] = [ids["unrelated_observation_id"]]
    _reseal(hypothesis_set)
    _assert_error(
        graph,
        "hypotheses.claim_ids: do not cover exactly all conflicted claims",
    )
