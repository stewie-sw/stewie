from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import threading

import pytest

from stewie.ultrabuild.canonical import canonical_bytes, record_content_hash
from stewie.ultrabuild.contracts import record_set_errors
from stewie.ultrabuild.golden import append_with_provenance, build_golden_world
from stewie.ultrabuild.payloads import (
    ContentAddressedPayloadStore,
    PayloadIntegrityError,
)
from stewie.ultrabuild.records import (
    branch_record,
    candidate_record,
    invalidation_event_record,
    promoted_revision_record,
    promotion_decision_record,
    provenance_record,
    submission,
)
from stewie.ultrabuild.store import (
    AuthoritativeStore,
    IdempotencyConflict,
    StoreContractError,
)


def _reseal(record: dict[str, object]) -> None:
    record["content_hash"] = record_content_hash(record)


def _promotion_alternatives(
    store: AuthoritativeStore,
    ids: dict[str, str],
) -> list[tuple[dict[str, object], dict[str, object]]]:
    observation = store.get(ids["observation_id"])
    prior = store.get(ids["revision_id"])
    assert observation is not None and prior is not None
    candidate = append_with_provenance(
        store,
        "state_candidate.schema.json",
        candidate_record(
            observation,
            candidate_id="candidate.race",
            provenance_bundle_id="provenance.candidate.race",
            prior_revision_id=prior["revision_id"],
        ),
        token="candidate.race",
    )
    alternatives: list[tuple[dict[str, object], dict[str, object]]] = []
    provenance_submissions: list[dict[str, object]] = []
    for suffix in ("a", "b"):
        decision = promotion_decision_record(
            candidate,
            revision_id=f"revision.race.{suffix}",
            decision_id=f"decision.race.{suffix}",
            provenance_bundle_id=f"provenance.decision.race.{suffix}",
        )
        revision = promoted_revision_record(
            candidate,
            decision,
            event_id=ids["external_action_id"],
            provenance_bundle_id=f"provenance.revision.race.{suffix}",
            branch_revision_sequence=2,
        )
        alternatives.append((decision, revision))
        for schema_name, record, token in (
            (
                "reconciliation_decision.schema.json",
                decision,
                f"decision.race.{suffix}.provenance",
            ),
            (
                "world_revision.schema.json",
                revision,
                f"revision.race.{suffix}.provenance",
            ),
        ):
            provenance_submissions.append(
                submission(
                    "provenance_bundle.schema.json",
                    provenance_record(
                        schema_name,
                        record,
                        bundle_id=str(record["provenance_bundle_id"]),
                    ),
                    token=token,
                )
            )
    store.append_batch(provenance_submissions)
    return alternatives


def test_golden_world_is_integral_and_survives_cold_restore(
    tmp_path: Path,
) -> None:
    store, ids = build_golden_world(tmp_path / "authority.sqlite3")
    report = store.verify_integrity()
    assert report == {
        "ok": True,
        "record_count": 18,
        "latest_sequence": 18,
        "errors": [],
    }
    before = [canonical_bytes(record) for record in store.records()]
    head_before = store.branch_head("branch.accepted")
    snapshot = store.snapshot_to(tmp_path / "cold-restore.sqlite3")
    store.close()

    with AuthoritativeStore(
        snapshot,
        clock=lambda: "2026-07-29T00:00:01Z",
        payload_store=ContentAddressedPayloadStore(tmp_path / "payloads"),
        require_local_payloads=True,
    ) as restored:
        assert [canonical_bytes(record) for record in restored.records()] == before
        assert restored.branch_head("branch.accepted") == head_before
        assert restored.verify_integrity()["ok"] is True
        revision = restored.query_revision(
            world_id="world.lunar",
            site_id="site.haworth",
            branch_id="branch.accepted",
            valid_at=10.0,
            known_at_sequence=12,
            state_kinds=["reconciled"],
        )
        assert revision is not None
        assert revision["revision_id"] == ids["revision_id"]


def test_payload_store_is_content_addressed_and_detects_corruption(
    tmp_path: Path,
) -> None:
    payloads = ContentAddressedPayloadStore(tmp_path / "payloads")
    first = payloads.put(
        b"terrain-bytes",
        media_type="application/x-stewie-raster",
        generated_at="2026-07-29T00:00:00Z",
    )
    duplicate = payloads.put(
        b"terrain-bytes",
        media_type="application/x-stewie-raster",
        generated_at="2026-07-29T00:00:01Z",
    )
    assert duplicate["duplicate"] is True
    assert duplicate["content_hash"] == first["content_hash"]
    assert payloads.get(first["content_hash"]) == b"terrain-bytes"

    payloads.path(first["content_hash"]).write_bytes(b"corrupt")
    with pytest.raises(PayloadIntegrityError):
        payloads.get(first["content_hash"])


def test_store_owns_transaction_fields_and_exact_idempotency(
    tmp_path: Path,
) -> None:
    record = branch_record(
        branch_id="branch.test",
        branch_kind="accepted",
        policy_id="policy.test",
        permitted_state_kinds=["reconciled"],
    )
    submitted = submission("branch.schema.json", record, token="branch.test")
    with AuthoritativeStore(tmp_path / "authority.sqlite3") as store:
        first = store.append(submitted)
        duplicate = store.append(submitted)
        assert duplicate["duplicate"] is True
        assert duplicate["transaction_time"] == first["transaction_time"]
        assert store.latest_sequence() == 1

        changed = deepcopy(submitted)
        changed["record"]["site_id"] = "site.other"
        with pytest.raises(IdempotencyConflict):
            store.append(changed)

        caller_owned = deepcopy(submitted)
        caller_owned["idempotency_key"] = "idempotency.caller-owned"
        caller_owned["submission_id"] = "submission.caller-owned"
        caller_owned["record"]["transaction_time"] = {
            "sequence": 999,
            "recorded_at": "2026-07-29T00:00:00Z",
        }
        caller_owned["record"]["content_hash"] = "0" * 64
        with pytest.raises(StoreContractError):
            store.append(caller_owned)


def test_sequence_is_monotonic_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "authority.sqlite3"
    with AuthoritativeStore(path) as store:
        first = store.append(
            submission(
                "branch.schema.json",
                branch_record(
                    branch_id="branch.one",
                    branch_kind="accepted",
                    policy_id="policy.one",
                    permitted_state_kinds=["reconciled"],
                ),
                token="branch.one",
            )
        )
    with AuthoritativeStore(path) as store:
        second = store.append(
            submission(
                "branch.schema.json",
                branch_record(
                    branch_id="branch.two",
                    branch_kind="evidence",
                    policy_id="policy.two",
                    permitted_state_kinds=["observed"],
                ),
                token="branch.two",
            )
        )
        assert second["transaction_time"]["sequence"] == (
            first["transaction_time"]["sequence"] + 1
        )


def test_concurrent_promotions_have_exactly_one_winner(tmp_path: Path) -> None:
    path = tmp_path / "authority.sqlite3"
    store_a, ids = build_golden_world(path)
    alternatives = _promotion_alternatives(store_a, ids)
    store_b = AuthoritativeStore(path)
    barrier = threading.Barrier(2)
    receipts: list[dict[str, object]] = []
    failures: list[BaseException] = []

    def promote(
        store: AuthoritativeStore,
        suffix: str,
        decision: dict[str, object],
        revision: dict[str, object],
    ) -> None:
        try:
            barrier.wait()
            receipts.append(
                store.commit_promotion(
                    operation_id=f"operation.race.{suffix}",
                    expected_head_revision_id=ids["revision_id"],
                    expected_head_sequence=1,
                    decision_submission=submission(
                        "reconciliation_decision.schema.json",
                        decision,
                        token=f"decision.race.{suffix}",
                    ),
                    revision_submission=submission(
                        "world_revision.schema.json",
                        revision,
                        token=f"revision.race.{suffix}",
                    ),
                )
            )
        except BaseException as exc:
            failures.append(exc)

    threads = [
        threading.Thread(
            target=promote,
            args=(store_a, "a", *alternatives[0]),
        ),
        threading.Thread(
            target=promote,
            args=(store_b, "b", *alternatives[1]),
        ),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not failures
    assert sorted(receipt["applied"] for receipt in receipts) == [False, True]
    assert {receipt["reason_code"] for receipt in receipts} == {
        "applied",
        "stale_head",
    }
    durable_race_revisions = [
        record
        for record in store_a.records(
            record_schema="world_revision.schema.json"
        )
        if str(record["revision_id"]).startswith("revision.race.")
    ]
    durable_race_decisions = [
        record
        for record in store_a.records(
            record_schema="reconciliation_decision.schema.json"
        )
        if str(record["decision_id"]).startswith("decision.race.")
    ]
    assert len(durable_race_revisions) == 1
    assert len(durable_race_decisions) == 1
    assert store_a.verify_integrity()["ok"] is True
    store_b.close()
    store_a.close()


def test_pending_review_cannot_promote_or_leave_partial_records(
    tmp_path: Path,
) -> None:
    store, ids = build_golden_world(tmp_path / "authority.sqlite3")
    decision, revision = _promotion_alternatives(store, ids)[0]
    decision["review"] = {
        "status": "pending",
        "reviewer_id": "reviewer.independent",
    }
    before = store.latest_sequence()
    receipt = store.commit_promotion(
        operation_id="operation.pending-review",
        expected_head_revision_id=ids["revision_id"],
        expected_head_sequence=1,
        decision_submission=submission(
            "reconciliation_decision.schema.json",
            decision,
            token="decision.pending-review",
        ),
        revision_submission=submission(
            "world_revision.schema.json",
            revision,
            token="revision.pending-review",
        ),
    )
    assert receipt["applied"] is False
    assert receipt["reason_code"] == "invalid_promotion"
    assert store.latest_sequence() == before
    assert store.get(str(decision["decision_id"])) is None
    assert store.get(str(revision["revision_id"])) is None
    store.close()


def test_historical_query_changes_only_after_durable_invalidation(
    tmp_path: Path,
) -> None:
    store, ids = build_golden_world(tmp_path / "authority.sqlite3")
    revision = store.get(ids["revision_id"])
    assert revision is not None
    before_invalidation = store.latest_sequence()
    event = invalidation_event_record(
        revision,
        evidence_id=ids["observation_id"],
    )
    append_with_provenance(
        store,
        "supersession_event.schema.json",
        event,
        token="invalidation.golden",
    )
    after_invalidation = store.latest_sequence()

    historical = store.query_revision(
        world_id="world.lunar",
        site_id="site.haworth",
        branch_id="branch.accepted",
        valid_at=10.0,
        known_at_sequence=before_invalidation,
        state_kinds=["reconciled"],
    )
    current = store.query_revision(
        world_id="world.lunar",
        site_id="site.haworth",
        branch_id="branch.accepted",
        valid_at=10.0,
        known_at_sequence=after_invalidation,
        state_kinds=["reconciled"],
    )
    assert historical is not None
    assert historical["revision_id"] == ids["revision_id"]
    assert current is None
    assert store.get(ids["revision_id"]) is not None
    store.close()


def test_projection_can_be_rebuilt_from_immutable_history(tmp_path: Path) -> None:
    store, _ = build_golden_world(tmp_path / "authority.sqlite3")
    store._connection.execute(  # deliberate fault injection into a projection
        "UPDATE branch_heads SET revision_id=NULL, revision_sequence=0 "
        "WHERE branch_id='branch.accepted'"
    )
    assert store.verify_integrity()["ok"] is False
    receipt = store.rebuild_projections()
    assert receipt["status"] == "rebuilt"
    assert store.verify_integrity()["ok"] is True
    assert store.branch_head("branch.accepted")["revision_id"] == (
        "revision.accepted.golden"
    )
    store.close()


@pytest.mark.parametrize(
    ("mutation", "expected_fragment"),
    [
        (
            lambda candidate: candidate["spatial"].update(
                {"frame_id": "frame.wrong"}
            ),
            "state_contract_hash",
        ),
        (
            lambda candidate: candidate["uncertainty"]["components"].pop(),
            "uncertainty",
        ),
        (
            lambda candidate: candidate["valid_time"].update({"start": 99.0}),
            "valid_time",
        ),
    ],
)
def test_candidate_contract_mutations_are_rejected(
    tmp_path: Path,
    mutation: object,
    expected_fragment: str,
) -> None:
    store, ids = build_golden_world(tmp_path / "authority.sqlite3")
    graph: list[tuple[str, dict[str, object]]] = []
    schema_by_version = {
        "stewie.branch/1.0": "branch.schema.json",
        "stewie.provenance_bundle/1.0": "provenance_bundle.schema.json",
        "stewie.evidence_claim/1.0": "evidence_claim.schema.json",
        "stewie.action_event/1.0": "action_event.schema.json",
        "stewie.state_candidate/1.0": "state_candidate.schema.json",
        "stewie.reconciliation_decision/1.0": (
            "reconciliation_decision.schema.json"
        ),
        "stewie.world_revision/1.0": "world_revision.schema.json",
        "stewie.query_request/1.0": "query_request.schema.json",
        "stewie.query_lens/1.0": "query_lens.schema.json",
        "stewie.decision_record/1.0": "decision_record.schema.json",
    }
    for record in store.records():
        schema_name = schema_by_version[str(record["schema_version"])]
        graph.append((schema_name, record))
    candidate = next(
        record for _, record in graph if record.get("candidate_id") == ids["candidate_id"]
    )
    assert callable(mutation)
    mutation(candidate)
    _reseal(candidate)
    errors = record_set_errors(graph)
    assert any(expected_fragment in error for error in errors)
    store.close()
