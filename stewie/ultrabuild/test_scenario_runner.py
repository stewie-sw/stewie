from __future__ import annotations

from pathlib import Path

from stewie.ultrabuild.canonical import canonical_bytes
from stewie.ultrabuild.payloads import ContentAddressedPayloadStore
from stewie.ultrabuild.scenario_runner import (
    run_conflict_retention_demo,
    run_multi_robot_closed_loop,
)
from stewie.ultrabuild.store import AuthoritativeStore


def test_multi_robot_closed_loop_is_persistent_and_reference_isolated(
    tmp_path: Path,
) -> None:
    database = tmp_path / "world-state.sqlite3"
    store, report = run_multi_robot_closed_loop(database)
    try:
        assert report["status"] == "complete"
        assert report["integrity"]["ok"] is True
        assert report["integrity"]["record_count"] == 31
        assert report["cas_receipt"]["applied"] is True
        assert len(report["admitted_claim_ids"]) == 2
        reasons = {
            reason for _, reason in report["excluded_evidence"]
        }
        assert reasons == {"physics_inconsistent", "stale_before_action"}
        durable_bytes = b"\n".join(
            canonical_bytes(record) for record in store.records()
        )
        assert report["reference_hash"].encode("ascii") not in durable_bytes
        head = store.branch_head("branch.accepted")
        assert head is not None
        assert head["revision_id"] == report["revision_id"]
    finally:
        store.close()

    with AuthoritativeStore(
        database,
        payload_store=ContentAddressedPayloadStore(tmp_path / "payloads"),
        require_local_payloads=True,
    ) as restored:
        assert restored.verify_integrity()["ok"] is True
        revision = restored.query_revision(
            world_id="world.lunar",
            site_id="site.haworth",
            branch_id="branch.accepted",
            valid_at=10.0,
            known_at_sequence=25,
            state_kinds=["reconciled"],
        )
        assert revision is not None
        assert revision["revision_id"] == report["revision_id"]


def test_conflict_demo_preserves_hypotheses_without_advancing_head(
    tmp_path: Path,
) -> None:
    database = tmp_path / "conflict.sqlite3"
    store, report = run_conflict_retention_demo(database)
    try:
        assert report["decision"] == "RETAIN_HYPOTHESES"
        assert len(report["hypothesis_ids"]) == 2
        assert report["integrity"]["ok"] is True
        assert report["accepted_head"]["revision_id"] is None
        assert store.records(
            record_schema="world_revision.schema.json"
        ) == []
    finally:
        store.close()

    with AuthoritativeStore(
        database,
        payload_store=ContentAddressedPayloadStore(tmp_path / "payloads"),
        require_local_payloads=True,
    ) as restored:
        assert restored.verify_integrity()["ok"] is True
        decision = restored.get(report["decision_id"])
        assert decision is not None
        assert decision["retained_hypothesis_ids"] == report["hypothesis_ids"]
