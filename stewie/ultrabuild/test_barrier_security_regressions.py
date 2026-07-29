"""Fail-closed regressions for the independent Barrier-2/3 review.

The tests in this module describe required authority-boundary behavior. They are
expected to fail until the corresponding findings from the review of commit
8f38832b are fixed. A fix may reject an operation at any earlier safe boundary,
but it must never leave the prohibited durable or query-visible state behind.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from stewie.ultrabuild.contracts import (
    PRIMARY_KEY_BY_SCHEMA,
    load_schema,
    record_set_errors,
)
from stewie.ultrabuild.golden import append_with_provenance, build_golden_world
from stewie.ultrabuild.payloads import (
    ContentAddressedPayloadStore,
    PayloadIntegrityError,
)
from stewie.ultrabuild.records import (
    branch_record,
    candidate_record,
    conflict_record,
    hypothesis_set_record,
    invalidation_event_record,
    observation_record,
    promoted_revision_record,
    promotion_decision_record,
    provenance_record,
    revision_spatial_from_evidence,
    submission,
)
from stewie.ultrabuild.scenario_runner import (
    run_conflict_retention_demo,
    run_multi_robot_closed_loop,
)
from stewie.ultrabuild.store import AuthoritativeStore, StoreContractError


RECORDED_AT = "2026-07-29T00:00:00Z"
SCHEMA_BY_VERSION = {
    str(load_schema(schema_name)["properties"]["schema_version"]["const"]): schema_name
    for schema_name in PRIMARY_KEY_BY_SCHEMA
}


def _append_world_branches(store: AuthoritativeStore) -> None:
    store.append_batch(
        [
            submission(
                "branch.schema.json",
                branch_record(
                    branch_id="branch.accepted",
                    branch_kind="accepted",
                    policy_id="policy.promotion",
                    permitted_state_kinds=[
                        "reconciled",
                        "verified",
                        "authoritative",
                    ],
                ),
                token="branch.accepted",
            ),
            submission(
                "branch.schema.json",
                branch_record(
                    branch_id="branch.evidence",
                    branch_kind="evidence",
                    policy_id="policy.evidence",
                    permitted_state_kinds=["observed"],
                ),
                token="branch.evidence",
            ),
        ]
    )


def _semantic_mismatch_bundle(
    claim: dict[str, Any],
) -> dict[str, Any]:
    bundle = provenance_record(
        "evidence_claim.schema.json",
        claim,
        bundle_id=str(claim["provenance_bundle_id"]),
    )
    subject = bundle["subject"]
    activities = bundle["activities"]
    relations = bundle["relations"]
    transforms = bundle["transforms"]
    calibrations = bundle["calibrations"]
    assert isinstance(subject, dict)
    assert isinstance(activities, list) and activities
    assert isinstance(relations, list)
    assert isinstance(transforms, list) and transforms
    assert isinstance(calibrations, list) and calibrations

    old_activity = str(subject["generating_activity_id"])
    new_activity = "pipeline.shadow.same-version"
    subject["generating_activity_id"] = new_activity
    activities[0]["activity_id"] = new_activity
    for relation in relations:
        if relation["subject_id"] == old_activity:
            relation["subject_id"] = new_activity
        if relation["object_id"] == old_activity:
            relation["object_id"] = new_activity
    transforms[0]["target_frame"] = "frame.unrelated"
    calibrations[0]["instrument_id"] = "instrument.unrelated"
    return bundle


def test_barrier_regression_01_physics_payload_cannot_write_accepted_state(
    tmp_path: Path,
) -> None:
    """Physics may gate observations but may never supply accepted state bytes."""

    store, report = run_multi_robot_closed_loop(tmp_path / "physics-write.sqlite3")
    try:
        prior = store.get(str(report["revision_id"]))
        observation = store.get(str(report["admitted_claim_ids"][0]))
        assert prior is not None and observation is not None
        physics_claim = next(
            record
            for record in store.records(record_schema="evidence_claim.schema.json")
            if record["source_kind"] == "physics_prediction"
        )
        observation_hashes = {
            str(record["payload"]["content_hash"])
            for record in store.records(record_schema="evidence_claim.schema.json")
            if record["source_kind"] == "observation"
        }
        physics_hash = str(physics_claim["payload"]["content_hash"])
        assert physics_hash not in observation_hashes

        try:
            candidate = candidate_record(
                observation,
                candidate_id="candidate.physics-bytes-as-state",
                provenance_bundle_id=("provenance.candidate.physics-bytes-as-state"),
                prior_revision_id=str(prior["revision_id"]),
                payload_hash=physics_hash,
                coverage_hash=str(physics_claim["payload"]["coverage_hash"]),
                payload_byte_size=int(physics_claim["payload"]["byte_size"]),
                construction="plain_mean_of_admissible_observations",
                physics_comparison_ids=[str(physics_claim["claim_id"])],
                spatial=revision_spatial_from_evidence(
                    observation["spatial"],
                    region_id="region.physics-bytes-as-state",
                ),
            )
            stored_candidate = append_with_provenance(
                store,
                "state_candidate.schema.json",
                candidate,
                token="candidate.physics-bytes-as-state",
            )
            decision = promotion_decision_record(
                stored_candidate,
                revision_id="revision.physics-bytes-as-state",
                decision_id="decision.physics-bytes-as-state",
                provenance_bundle_id=("provenance.decision.physics-bytes-as-state"),
            )
            revision = promoted_revision_record(
                stored_candidate,
                decision,
                event_id="event.excavation.multi-robot",
                provenance_bundle_id=("provenance.revision.physics-bytes-as-state"),
                branch_revision_sequence=2,
            )
            promotion_provenance = [
                submission(
                    "provenance_bundle.schema.json",
                    provenance_record(
                        "reconciliation_decision.schema.json",
                        decision,
                        bundle_id=str(decision["provenance_bundle_id"]),
                    ),
                    token=("decision.physics-bytes-as-state.provenance"),
                ),
                submission(
                    "provenance_bundle.schema.json",
                    provenance_record(
                        "world_revision.schema.json",
                        revision,
                        bundle_id=str(revision["provenance_bundle_id"]),
                    ),
                    token=("revision.physics-bytes-as-state.provenance"),
                ),
            ]
            receipt = store.commit_promotion(
                operation_id="operation.physics-bytes-as-state",
                expected_head_revision_id=str(prior["revision_id"]),
                expected_head_sequence=1,
                provenance_submissions=promotion_provenance,
                decision_submission=submission(
                    "reconciliation_decision.schema.json",
                    decision,
                    token="decision.physics-bytes-as-state",
                ),
                revision_submission=submission(
                    "world_revision.schema.json",
                    revision,
                    token="revision.physics-bytes-as-state",
                ),
            )
        except StoreContractError:
            return

        assert receipt["applied"] is False
        assert store.branch_head("branch.accepted")["revision_id"] == (prior["revision_id"])
    finally:
        store.close()


def test_barrier_regression_02_graph_validation_cannot_be_disabled(
    tmp_path: Path,
) -> None:
    """The public append gateway must always enforce graph integrity."""

    with AuthoritativeStore(
        tmp_path / "validation-disable.sqlite3",
        clock=lambda: RECORDED_AT,
    ) as store:
        _append_world_branches(store)
        claim = observation_record(
            claim_id="claim.unresolved.provenance",
            provenance_bundle_id="provenance.does-not-exist",
        )
        try:
            store.append_batch(
                [
                    submission(
                        "evidence_claim.schema.json",
                        claim,
                        token="claim.unresolved.provenance",
                    )
                ],
                validate_graph=False,
            )
        except (StoreContractError, TypeError):
            assert store.get(str(claim["claim_id"])) is None
            return

        pytest.fail("public append accepted an unresolved graph with validation disabled")


def test_barrier_regression_03_provenance_semantics_must_close(
    tmp_path: Path,
) -> None:
    """Pipeline, transform endpoint, and calibration instrument must match."""

    with AuthoritativeStore(
        tmp_path / "provenance-semantics.sqlite3",
        clock=lambda: RECORDED_AT,
    ) as store:
        _append_world_branches(store)
        claim = observation_record(
            claim_id="claim.provenance.semantic-mismatch",
            provenance_bundle_id="provenance.semantic-mismatch",
        )
        bundle = _semantic_mismatch_bundle(claim)
        with pytest.raises(StoreContractError):
            store.append_batch(
                [
                    submission(
                        "provenance_bundle.schema.json",
                        bundle,
                        token="provenance.semantic-mismatch",
                    ),
                    submission(
                        "evidence_claim.schema.json",
                        claim,
                        token="claim.provenance.semantic-mismatch",
                    ),
                ]
            )
        assert store.get(str(claim["claim_id"])) is None


def test_barrier_regression_04_provenance_must_precede_its_subject(
    tmp_path: Path,
) -> None:
    """Every known-at prefix containing a claim must contain its provenance."""

    with AuthoritativeStore(
        tmp_path / "future-provenance.sqlite3",
        clock=lambda: RECORDED_AT,
    ) as store:
        _append_world_branches(store)
        claim = observation_record(
            claim_id="claim.future.provenance",
            provenance_bundle_id="provenance.future",
        )
        bundle = provenance_record(
            "evidence_claim.schema.json",
            claim,
            bundle_id="provenance.future",
        )
        try:
            receipts = store.append_batch(
                [
                    submission(
                        "evidence_claim.schema.json",
                        claim,
                        token="claim.future.provenance",
                    ),
                    submission(
                        "provenance_bundle.schema.json",
                        bundle,
                        token="provenance.future",
                    ),
                ]
            )
        except StoreContractError:
            assert store.get(str(claim["claim_id"])) is None
            return

        claim_sequence = int(receipts[0]["transaction_time"]["sequence"])
        bundle_sequence = int(receipts[1]["transaction_time"]["sequence"])
        assert bundle_sequence < claim_sequence


def test_barrier_regression_05_snapshot_restores_payload_bytes(
    tmp_path: Path,
) -> None:
    """A cold snapshot must be independently reconstructable."""

    source = tmp_path / "source"
    destination = tmp_path / "destination"
    store, ids = build_golden_world(source / "authority.sqlite3")
    revision = store.get(ids["revision_id"])
    assert revision is not None
    payload_hash = str(revision["payload_hash"])
    snapshot = store.snapshot_to(destination / "authority.sqlite3")
    store.close()

    destination_payloads = ContentAddressedPayloadStore(destination / "payloads")
    with AuthoritativeStore(
        snapshot,
        payload_store=destination_payloads,
        require_local_payloads=True,
    ) as restored:
        report = restored.verify_integrity()
        assert report["ok"] is True, report["errors"]
        assert destination_payloads.get(payload_hash)


def test_barrier_regression_05_integrity_cannot_skip_required_payloads(
    tmp_path: Path,
) -> None:
    """Payload-bearing histories may not report integral without a verifier."""

    store, _ = build_golden_world(tmp_path / "source" / "authority.sqlite3")
    snapshot = store.snapshot_to(tmp_path / "cold" / "authority.sqlite3")
    store.close()

    with AuthoritativeStore(snapshot) as metadata_only:
        report = metadata_only.verify_integrity()
        assert report["ok"] is False
        assert any("payload" in error for error in report["errors"])


def test_barrier_regression_06_corrupt_payload_is_not_queryable(
    tmp_path: Path,
) -> None:
    """An authoritative query must fail closed after payload corruption."""

    store, ids = build_golden_world(tmp_path / "corrupt-query.sqlite3")
    try:
        revision = store.get(ids["revision_id"])
        assert revision is not None
        payload_hash = str(revision["payload_hash"])
        assert store.payload_store is not None
        store.payload_store.path(payload_hash).write_bytes(b"corrupt")
        try:
            result = store.query_revision(
                world_id="world.lunar",
                site_id="site.haworth",
                branch_id="branch.accepted",
                valid_at=10.0,
                known_at_sequence=12,
                state_kinds=["reconciled"],
            )
        except (PayloadIntegrityError, StoreContractError):
            return
        assert result is None
    finally:
        store.close()


def test_barrier_regression_07_cross_branch_invalidation_is_rejected(
    tmp_path: Path,
) -> None:
    """A supersession event must share the target record's branch."""

    store, ids = build_golden_world(tmp_path / "cross-branch-invalidation.sqlite3")
    try:
        revision = store.get(ids["revision_id"])
        assert revision is not None
        event = invalidation_event_record(
            revision,
            evidence_id=ids["observation_id"],
            event_id="supersession.cross-branch.invalidate",
            provenance_bundle_id=("provenance.cross-branch.invalidate"),
        )
        event["branch_id"] = "branch.evidence"
        with pytest.raises(StoreContractError):
            append_with_provenance(
                store,
                "supersession_event.schema.json",
                event,
                token="cross-branch.invalidate",
            )
        assert store.get(str(event["event_id"])) is None
    finally:
        store.close()


def test_barrier_regression_08_validator_never_crashes_on_bad_shape(
    tmp_path: Path,
) -> None:
    """Schema-invalid cross-record input must return errors, not throw."""

    store, _ = run_conflict_retention_demo(tmp_path / "validator-crash.sqlite3")
    try:
        graph = [
            (
                SCHEMA_BY_VERSION[str(record["schema_version"])],
                deepcopy(record),
            )
            for record in store.records()
        ]
    finally:
        store.close()
    claim = next(record for schema_name, record in graph if schema_name == "evidence_claim.schema.json")
    valid_time = claim["valid_time"]
    assert isinstance(valid_time, dict)
    valid_time.pop("start")

    try:
        errors = record_set_errors(graph)
    except Exception as exc:  # pragma: no cover - current defect reaches this
        pytest.fail(f"validator crashed instead of failing closed: {exc!r}")
    assert any("valid_time" in error and "start" in error for error in errors)


def test_barrier_regression_09_orphan_provenance_is_rejected(
    tmp_path: Path,
) -> None:
    """A provenance bundle may not outlive or precede an absent subject."""

    store, ids = build_golden_world(tmp_path / "orphan-provenance.sqlite3")
    try:
        observation = store.get(ids["observation_id"])
        prior = store.get(ids["revision_id"])
        assert observation is not None and prior is not None
        candidate = candidate_record(
            observation,
            candidate_id="candidate.never-submitted",
            provenance_bundle_id="provenance.candidate.never-submitted",
            prior_revision_id=str(prior["revision_id"]),
        )
        orphan = provenance_record(
            "state_candidate.schema.json",
            candidate,
            bundle_id=str(candidate["provenance_bundle_id"]),
        )
        with pytest.raises(StoreContractError):
            store.append(
                submission(
                    "provenance_bundle.schema.json",
                    orphan,
                    token="candidate.never-submitted.provenance",
                )
            )
        assert store.get(str(candidate["provenance_bundle_id"])) is None
    finally:
        store.close()


def test_barrier_regression_10_hypothesis_claim_assignments_are_disjoint(
    tmp_path: Path,
) -> None:
    """A conflicted claim may not be assigned to multiple hypotheses."""

    with AuthoritativeStore(
        tmp_path / "hypothesis-overlap.sqlite3",
        clock=lambda: RECORDED_AT,
    ) as store:
        _append_world_branches(store)
        left = append_with_provenance(
            store,
            "evidence_claim.schema.json",
            observation_record(
                claim_id="claim.left",
                provenance_bundle_id="provenance.left",
            ),
            token="claim.left",
        )
        right = append_with_provenance(
            store,
            "evidence_claim.schema.json",
            observation_record(
                claim_id="claim.right",
                provenance_bundle_id="provenance.right",
            ),
            token="claim.right",
        )
        conflict = conflict_record(
            left,
            right,
            conflict_id="conflict.overlap",
            hypothesis_set_id="hypotheses.overlap",
            provenance_bundle_id="provenance.conflict.overlap",
        )
        hypotheses = hypothesis_set_record(
            conflict,
            provenance_bundle_id="provenance.hypotheses.overlap",
        )
        hypothesis_items = hypotheses["hypotheses"]
        assert isinstance(hypothesis_items, list)
        hypothesis_items[0]["claim_ids"] = [left["claim_id"]]
        hypothesis_items[1]["claim_ids"] = [
            left["claim_id"],
            right["claim_id"],
        ]

        with pytest.raises(StoreContractError):
            store.append_batch(
                [
                    submission(
                        "provenance_bundle.schema.json",
                        provenance_record(
                            "conflict_record.schema.json",
                            conflict,
                            bundle_id=str(conflict["provenance_bundle_id"]),
                        ),
                        token="conflict.overlap.provenance",
                    ),
                    submission(
                        "provenance_bundle.schema.json",
                        provenance_record(
                            "hypothesis_set.schema.json",
                            hypotheses,
                            bundle_id=str(hypotheses["provenance_bundle_id"]),
                        ),
                        token="hypotheses.overlap.provenance",
                    ),
                    submission(
                        "conflict_record.schema.json",
                        conflict,
                        token="conflict.overlap",
                    ),
                    submission(
                        "hypothesis_set.schema.json",
                        hypotheses,
                        token="hypotheses.overlap",
                    ),
                ]
            )
        assert store.get(str(hypotheses["hypothesis_set_id"])) is None


def test_authoritative_query_rejects_broken_upstream_lineage(
    tmp_path: Path,
) -> None:
    """An intact revision is not authoritative when its admitted source is corrupt."""

    store, report = run_multi_robot_closed_loop(
        tmp_path / "lineage-query.sqlite3"
    )
    try:
        claim = store.get(str(report["admitted_claim_ids"][0]))
        assert claim is not None and store.payload_store is not None
        store.payload_store.path(
            str(claim["payload"]["content_hash"])
        ).write_bytes(b"corrupt-upstream-evidence")
        with pytest.raises(
            (PayloadIntegrityError, StoreContractError),
            match=r"(?i)(integr|payload|lineage|history)",
        ):
            store.query_revision(
                world_id="world.lunar",
                site_id="site.haworth",
                branch_id="branch.accepted",
                valid_at=10.0,
                known_at_sequence=store.latest_sequence(),
                state_kinds=["reconciled"],
            )
    finally:
        store.close()


def test_validator_fails_closed_on_numeric_time_overflow(
    tmp_path: Path,
) -> None:
    """Schema-valid but unbounded integers must not escape the contract boundary."""

    with AuthoritativeStore(
        tmp_path / "overflow.sqlite3",
        clock=lambda: RECORDED_AT,
    ) as store:
        _append_world_branches(store)
        claim = observation_record(
            claim_id="claim.time-overflow",
            provenance_bundle_id="provenance.time-overflow",
        )
        claim["valid_time"]["start"] = 10**400
        with pytest.raises(
            StoreContractError,
            match=r"(?i)(overflow|malformed|validation|graph)",
        ):
            append_with_provenance(
                store,
                "evidence_claim.schema.json",
                claim,
                token="time-overflow",
            )
        assert store.get(str(claim["claim_id"])) is None
