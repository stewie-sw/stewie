"""A deterministic Barrier-3 world-state graph used by tests and demonstrations."""

from __future__ import annotations

from pathlib import Path
import struct
from typing import Any

from stewie.ultrabuild.payloads import ContentAddressedPayloadStore
from stewie.ultrabuild.records import (
    autonomous_action_record,
    branch_record,
    candidate_record,
    external_action_record,
    observation_record,
    planning_decision_record,
    promoted_revision_record,
    promotion_decision_record,
    provenance_record,
    query_request_record,
    resolved_query_lens_record,
    submission,
)
from stewie.ultrabuild.store import AuthoritativeStore


def append_with_provenance(
    store: AuthoritativeStore,
    schema_name: str,
    record: dict[str, Any],
    *,
    token: str,
) -> dict[str, Any]:
    """Append provenance immediately before the record it closes."""

    bundle_id = str(record["provenance_bundle_id"])
    provenance = provenance_record(
        schema_name,
        record,
        bundle_id=bundle_id,
    )
    store.append_batch(
        [
            submission(
                "provenance_bundle.schema.json",
                provenance,
                token=f"{token}.provenance",
            ),
            submission(schema_name, record, token=token),
        ]
    )
    stored = store.get(str(next(
        record[key]
        for key in (
            "claim_id",
            "event_id",
            "candidate_id",
            "decision_record_id",
        )
        if key in record
    )))
    assert stored is not None
    return stored


def build_golden_world(path: str | Path) -> tuple[AuthoritativeStore, dict[str, str]]:
    """Create the smallest complete persistent world-state/autonomy vertical slice."""

    database_path = Path(path)
    payload_store = ContentAddressedPayloadStore(
        database_path.parent / "payloads"
    )
    raster_receipt = payload_store.put(
        struct.pack("<4d", 0.0, -0.5, 0.25, -0.25),
        media_type="application/x-stewie-raster",
        generated_at="2026-07-29T00:00:00Z",
    )
    coverage_receipt = payload_store.put(
        bytes((1, 1, 1, 1)),
        media_type="application/x-stewie-coverage-mask",
        generated_at="2026-07-29T00:00:00Z",
    )
    store = AuthoritativeStore(
        database_path,
        clock=lambda: "2026-07-29T00:00:00Z",
        payload_store=payload_store,
        require_local_payloads=True,
    )
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

    observation = append_with_provenance(
        store,
        "evidence_claim.schema.json",
        observation_record(
            payload_hash=raster_receipt["content_hash"],
            coverage_hash=coverage_receipt["content_hash"],
        ),
        token="observation.golden",
    )
    action = append_with_provenance(
        store,
        "action_event.schema.json",
        external_action_record(),
        token="external.action.golden",
    )
    candidate = append_with_provenance(
        store,
        "state_candidate.schema.json",
        candidate_record(observation),
        token="candidate.golden",
    )

    decision = promotion_decision_record(candidate)
    revision = promoted_revision_record(
        candidate,
        decision,
        event_id=action["event_id"],
    )
    store.append_batch(
        [
            submission(
                "provenance_bundle.schema.json",
                provenance_record(
                    "reconciliation_decision.schema.json",
                    decision,
                    bundle_id=decision["provenance_bundle_id"],
                ),
                token="decision.promote.provenance",
            ),
            submission(
                "provenance_bundle.schema.json",
                provenance_record(
                    "world_revision.schema.json",
                    revision,
                    bundle_id=revision["provenance_bundle_id"],
                ),
                token="revision.accepted.provenance",
            ),
        ]
    )
    promotion_receipt = store.commit_promotion(
        operation_id="operation.promote.golden",
        expected_head_revision_id=None,
        expected_head_sequence=0,
        decision_submission=submission(
            "reconciliation_decision.schema.json",
            decision,
            token="decision.promote",
        ),
        revision_submission=submission(
            "world_revision.schema.json",
            revision,
            token="revision.accepted",
        ),
    )
    assert promotion_receipt["applied"] is True
    stored_revision = store.get(revision["revision_id"])
    assert stored_revision is not None

    request = query_request_record(stored_revision)
    request_receipt = store.append(
        submission(
            "query_request.schema.json",
            request,
            token="query.golden",
        )
    )
    stored_request = store.get(request["request_id"])
    assert stored_request is not None
    resolved_revision = store.query_revision(
        world_id=request["world_id"],
        site_id=request["site_id"],
        branch_id=request["branch_id"],
        valid_at=request["valid_at"]["instant"],
        known_at_sequence=request["known_at"]["sequence"],
        state_kinds=request["requested_state_kinds"],
    )
    assert resolved_revision is not None
    lens = resolved_query_lens_record(
        stored_request,
        resolved_revision,
        projection_transaction_sequence=request_receipt["transaction_time"][
            "sequence"
        ],
    )
    store.append(
        submission(
            "query_lens.schema.json",
            lens,
            token="lens.golden",
        )
    )
    stored_lens = store.get(lens["lens_id"])
    assert stored_lens is not None

    planner_decision = append_with_provenance(
        store,
        "decision_record.schema.json",
        planning_decision_record(stored_lens, stored_revision),
        token="planner.decision.golden",
    )
    planned_action = append_with_provenance(
        store,
        "action_event.schema.json",
        autonomous_action_record(planner_decision),
        token="planned.action.golden",
    )

    return store, {
        "observation_id": observation["claim_id"],
        "external_action_id": action["event_id"],
        "candidate_id": candidate["candidate_id"],
        "promotion_decision_id": decision["decision_id"],
        "revision_id": revision["revision_id"],
        "query_request_id": request["request_id"],
        "query_lens_id": lens["lens_id"],
        "planner_decision_id": planner_decision["decision_record_id"],
        "planned_action_id": planned_action["event_id"],
    }
