"""Persistent single-/multi-robot closed-loop demonstration runner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from stewie.ultrabuild.experiment import generate_trial, run_candidate
from stewie.ultrabuild.golden import append_with_provenance
from stewie.ultrabuild.identity import build_identity
from stewie.ultrabuild.payloads import ContentAddressedPayloadStore
from stewie.ultrabuild.records import (
    autonomous_action_record,
    branch_record,
    candidate_record,
    conflict_record,
    dependency_edge_record,
    external_action_record,
    hypothesis_set_record,
    observation_record,
    physics_prediction_record,
    planning_decision_record,
    promoted_revision_record,
    promotion_decision_record,
    provenance_record,
    query_request_record,
    retention_decision_record,
    resolved_query_lens_record,
    revision_spatial_from_evidence,
    submission,
)
from stewie.ultrabuild.reconciliation import (
    ActionContext,
    RasterEvidence,
    ReconciliationPolicy,
    reconcile_rasters,
)
from stewie.ultrabuild.store import AuthoritativeStore


def _raster_bytes(values: np.ndarray) -> bytes:
    return np.asarray(values, dtype="<f8").tobytes(order="C")


def _spatial_contract(shape: tuple[int, int]) -> dict[str, Any]:
    return {
        "representation": "raster_2_5d",
        "crs": "IAU_2015:30135",
        "frame_id": "frame.site.haworth",
        "transform_chain_id": "transform.haworth.identity",
        "axis_order": ["x", "y", "z"],
        "value_unit": "m",
        "bounds": [0.0, 0.0, float(shape[1]), float(shape[0])],
        "shape": list(shape),
        "resolution": [1.0, 1.0],
    }


def run_multi_robot_closed_loop(
    path: str | Path,
    *,
    window_index: int = 1,
    action_kind: str = "nominal",
    seed: int = 3002,
) -> tuple[AuthoritativeStore, dict[str, Any]]:
    """Persist a multi-robot reconciliation through query, plan, and action."""

    database_path = Path(path)
    payloads = ContentAddressedPayloadStore(database_path.parent / "payloads")
    store = AuthoritativeStore(
        database_path,
        clock=lambda: "2026-07-29T00:00:00Z",
        payload_store=payloads,
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
            submission(
                "branch.schema.json",
                branch_record(
                    branch_id="branch.prediction",
                    branch_kind="prediction",
                    policy_id="policy.physics",
                    permitted_state_kinds=["predicted"],
                ),
                token="branch.prediction",
            ),
        ]
    )
    scenario, reference = generate_trial(
        window_index=window_index,
        action_kind=action_kind,
        seed=seed,
    )
    candidate_result = run_candidate(scenario, "stewie")
    if candidate_result["decision"] != "PROMOTE":
        store.close()
        raise RuntimeError(
            "closed-loop scenario did not produce a promotable candidate"
        )

    spatial = _spatial_contract(scenario.prior.shape)
    coverage_receipt = payloads.put(
        np.ones(scenario.prior.shape, dtype=np.uint8).tobytes(order="C"),
        media_type="application/x-stewie-coverage-mask",
        generated_at="2026-07-29T00:00:00Z",
    )
    stored_claims: dict[str, dict[str, Any]] = {}
    evidence_by_id = {item.claim_id: item for item in scenario.evidence}
    for item in scenario.evidence:
        payload = _raster_bytes(item.values)
        payload_receipt = payloads.put(
            payload,
            media_type="application/x-stewie-raster",
            generated_at="2026-07-29T00:00:00Z",
        )
        claim = observation_record(
            claim_id=item.claim_id,
            provenance_bundle_id=f"provenance.{item.claim_id}",
            payload_hash=payload_receipt["content_hash"],
            coverage_hash=coverage_receipt["content_hash"],
            valid_start=item.valid_start,
            valid_end=item.valid_end,
            robot_id=item.robot_id,
            source_id=f"source.{item.robot_id}",
            pipeline_id=item.dependency_group,
            spatial=spatial,
            byte_size=len(payload),
            sensor_variance_m2=item.variance_m2,
        )
        if not item.provenance_complete:
            claim["source"]["calibration_id"] = {
                "status": "unknown",
                "reason_code": "calibration.metadata_missing",
            }
        stored_claims[item.claim_id] = append_with_provenance(
            store,
            "evidence_claim.schema.json",
            claim,
            token=item.claim_id,
        )

    physics_payload = _raster_bytes(scenario.planned_change)
    physics_payload_receipt = payloads.put(
        physics_payload,
        media_type="application/x-stewie-raster",
        generated_at="2026-07-29T00:00:00Z",
    )
    physics_claim = physics_prediction_record(
        claim_id="claim.physics.action-envelope",
        provenance_bundle_id="provenance.physics.action-envelope",
        payload_hash=physics_payload_receipt["content_hash"],
        coverage_hash=coverage_receipt["content_hash"],
        spatial=spatial,
        byte_size=len(physics_payload),
    )
    stored_physics_claim = append_with_provenance(
        store,
        "evidence_claim.schema.json",
        physics_claim,
        token="physics.action-envelope",
    )

    dependency_edges = [
        dependency_edge_record(
            edge_id="dependency.robot-a.shared-pipeline",
            left_claim_id=scenario.evidence[0].claim_id,
            right_claim_id=scenario.evidence[1].claim_id,
            coverage_hash=coverage_receipt["content_hash"],
        ),
        dependency_edge_record(
            edge_id="dependency.robot-c.shared-pipeline",
            left_claim_id=scenario.evidence[2].claim_id,
            right_claim_id=scenario.evidence[3].claim_id,
            coverage_hash=coverage_receipt["content_hash"],
        ),
    ]
    store.append_batch(
        [
            submission(
                "dependency_edge.schema.json",
                edge,
                token=edge["edge_id"],
            )
            for edge in dependency_edges
        ]
    )

    first_admitted_id = candidate_result["admitted_claim_ids"][0]
    action = append_with_provenance(
        store,
        "action_event.schema.json",
        external_action_record(
            event_id="event.excavation.multi-robot",
            provenance_bundle_id="provenance.event.excavation.multi-robot",
            observed_claim_id=first_admitted_id,
        ),
        token="event.excavation.multi-robot",
    )

    fused_state = np.asarray(candidate_result["state"], dtype="<f8")
    fused_payload = _raster_bytes(fused_state)
    fused_receipt = payloads.put(
        fused_payload,
        media_type="application/x-stewie-raster",
        generated_at="2026-07-29T00:00:00Z",
    )
    excluded = [
        {"claim_id": claim_id, "reason_code": reason}
        for claim_id, reason in candidate_result["excluded"]
    ]
    candidate = candidate_record(
        stored_claims[first_admitted_id],
        candidate_id="candidate.multi-robot",
        provenance_bundle_id="provenance.candidate.multi-robot",
        admitted_observation_ids=list(candidate_result["admitted_claim_ids"]),
        excluded_evidence=excluded,
        payload_hash=fused_receipt["content_hash"],
        coverage_hash=coverage_receipt["content_hash"],
        payload_byte_size=len(fused_payload),
        construction="dependency_aware_inverse_variance_mean",
        dependency_edge_ids=[edge["edge_id"] for edge in dependency_edges],
        physics_comparison_ids=[stored_physics_claim["claim_id"]],
        spatial=revision_spatial_from_evidence(
            spatial,
            region_id="region.haworth.multi-robot",
        ),
    )
    stored_candidate = append_with_provenance(
        store,
        "state_candidate.schema.json",
        candidate,
        token="candidate.multi-robot",
    )

    decision = promotion_decision_record(
        stored_candidate,
        revision_id="revision.accepted.multi-robot",
        decision_id="decision.promote.multi-robot",
        provenance_bundle_id="provenance.decision.promote.multi-robot",
    )
    decision["metrics"].update(
        effective_support=float(
            candidate_result["diagnostics"]["effective_support"]
        ),
        observed_cells=int(np.isfinite(fused_state).sum()),
        residual_rms_m=float(
            np.sqrt(
                np.mean(
                    np.square(
                        fused_state
                        - np.asarray(
                            evidence_by_id[first_admitted_id].values
                        )
                    )
                )
            )
        ),
    )
    revision = promoted_revision_record(
        stored_candidate,
        decision,
        event_id=action["event_id"],
        provenance_bundle_id="provenance.revision.accepted.multi-robot",
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
                token="decision.promote.multi-robot.provenance",
            ),
            submission(
                "provenance_bundle.schema.json",
                provenance_record(
                    "world_revision.schema.json",
                    revision,
                    bundle_id=revision["provenance_bundle_id"],
                ),
                token="revision.accepted.multi-robot.provenance",
            ),
        ]
    )
    cas_receipt = store.commit_promotion(
        operation_id="operation.promote.multi-robot",
        expected_head_revision_id=None,
        expected_head_sequence=0,
        decision_submission=submission(
            "reconciliation_decision.schema.json",
            decision,
            token="decision.promote.multi-robot",
        ),
        revision_submission=submission(
            "world_revision.schema.json",
            revision,
            token="revision.accepted.multi-robot",
        ),
    )
    if not cas_receipt["applied"]:
        store.close()
        raise RuntimeError(f"promotion failed: {cas_receipt['reason_code']}")
    stored_revision = store.get(revision["revision_id"])
    assert stored_revision is not None

    request = query_request_record(
        stored_revision,
        request_id="query.multi-robot",
    )
    request_receipt = store.append(
        submission(
            "query_request.schema.json",
            request,
            token="query.multi-robot",
        )
    )
    stored_request = store.get(request["request_id"])
    assert stored_request is not None
    resolved = store.query_revision(
        world_id=request["world_id"],
        site_id=request["site_id"],
        branch_id=request["branch_id"],
        valid_at=request["valid_at"]["instant"],
        known_at_sequence=request["known_at"]["sequence"],
        state_kinds=request["requested_state_kinds"],
    )
    assert resolved is not None
    lens = resolved_query_lens_record(
        stored_request,
        resolved,
        lens_id="lens.multi-robot",
        projection_transaction_sequence=request_receipt["transaction_time"][
            "sequence"
        ],
    )
    store.append(
        submission(
            "query_lens.schema.json",
            lens,
            token="lens.multi-robot",
        )
    )
    stored_lens = store.get(lens["lens_id"])
    assert stored_lens is not None
    planner_decision = append_with_provenance(
        store,
        "decision_record.schema.json",
        planning_decision_record(
            stored_lens,
            stored_revision,
            decision_record_id="planner.decision.multi-robot",
            provenance_bundle_id="provenance.planner.decision.multi-robot",
        ),
        token="planner.decision.multi-robot",
    )
    planned_action = append_with_provenance(
        store,
        "action_event.schema.json",
        autonomous_action_record(
            planner_decision,
            event_id="event.rescan.multi-robot",
            provenance_bundle_id="provenance.event.rescan.multi-robot",
        ),
        token="event.rescan.multi-robot",
    )
    report = {
        "schema_version": "stewie.multi_robot_closed_loop/1.0",
        "status": "complete",
        "evidence_level": "controlled_synthetic_demonstration",
        "unit_id": scenario.unit_id,
        "seed": seed,
        "reference_hash": reference.content_hash,
        "candidate_summary_hash": candidate_result[
            "candidate_summary_hash"
        ],
        "admitted_claim_ids": candidate_result["admitted_claim_ids"],
        "excluded_evidence": candidate_result["excluded"],
        "physics_evidence_ids": [stored_physics_claim["claim_id"]],
        "dependency_edge_ids": [edge["edge_id"] for edge in dependency_edges],
        "cas_receipt": cas_receipt,
        "revision_id": stored_revision["revision_id"],
        "query_lens_id": stored_lens["lens_id"],
        "planner_decision_id": planner_decision["decision_record_id"],
        "planned_action_id": planned_action["event_id"],
        "integrity": store.verify_integrity(),
        "build_identity": build_identity(),
    }
    return store, report


def run_conflict_retention_demo(
    path: str | Path,
) -> tuple[AuthoritativeStore, dict[str, Any]]:
    """Persist two physically plausible hypotheses without forcing a merge."""

    database_path = Path(path)
    payloads = ContentAddressedPayloadStore(database_path.parent / "payloads")
    store = AuthoritativeStore(
        database_path,
        clock=lambda: "2026-07-29T00:00:00Z",
        payload_store=payloads,
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
    prior = np.zeros((4, 4), dtype=np.float64)
    full = prior.copy()
    full[:, :2] = -1.0
    full[:, 2:] = 1.0
    partial = prior.copy()
    partial[:, :2] = -0.5
    partial[:, 2:] = 0.5
    coverage = np.ones((4, 4), dtype=bool)
    action = ActionContext(
        action_id="action.excavate.conflict",
        start=9.0,
        end=10.0,
        operational_envelope=coverage,
        volume_tolerance_cells=0.01,
        outside_envelope_tolerance_m=0.01,
    )
    evidence = [
        RasterEvidence(
            claim_id="claim.robot-a.full-excavation",
            robot_id="robot.a",
            values=full,
            coverage=coverage,
            valid_start=10.0,
            valid_end=11.0,
            received_sequence=1,
            source_time=10.1,
            variance_m2=0.01,
            provenance_complete=True,
            dependency_group="pipeline.robot-a",
        ),
        RasterEvidence(
            claim_id="claim.robot-b.partial-excavation",
            robot_id="robot.b",
            values=partial,
            coverage=coverage,
            valid_start=10.0,
            valid_end=11.0,
            received_sequence=2,
            source_time=10.1,
            variance_m2=0.01,
            provenance_complete=True,
            dependency_group="pipeline.robot-b",
        ),
    ]
    reconciliation = reconcile_rasters(
        evidence,
        prior=prior,
        action=action,
        known_at_sequence=2,
        policy=ReconciliationPolicy(),
    )
    if reconciliation.decision != "RETAIN_HYPOTHESES":
        store.close()
        raise RuntimeError("conflict scenario was incorrectly collapsed")

    spatial = _spatial_contract(prior.shape)
    coverage_receipt = payloads.put(
        coverage.astype(np.uint8).tobytes(order="C"),
        media_type="application/x-stewie-coverage-mask",
        generated_at="2026-07-29T00:00:00Z",
    )
    stored_claims = []
    for item in evidence:
        payload = _raster_bytes(item.values)
        payload_receipt = payloads.put(
            payload,
            media_type="application/x-stewie-raster",
            generated_at="2026-07-29T00:00:00Z",
        )
        claim = observation_record(
            claim_id=item.claim_id,
            provenance_bundle_id=f"provenance.{item.claim_id}",
            payload_hash=payload_receipt["content_hash"],
            coverage_hash=coverage_receipt["content_hash"],
            robot_id=item.robot_id,
            source_id=f"source.{item.robot_id}",
            pipeline_id=item.dependency_group,
            spatial=spatial,
            byte_size=len(payload),
            sensor_variance_m2=item.variance_m2,
        )
        stored_claims.append(
            append_with_provenance(
                store,
                "evidence_claim.schema.json",
                claim,
                token=item.claim_id,
            )
        )

    conflict = conflict_record(stored_claims[0], stored_claims[1])
    hypotheses = hypothesis_set_record(conflict)
    store.append_batch(
        [
            submission(
                "provenance_bundle.schema.json",
                provenance_record(
                    "conflict_record.schema.json",
                    conflict,
                    bundle_id=conflict["provenance_bundle_id"],
                ),
                token="conflict.multi-robot.provenance",
            ),
            submission(
                "provenance_bundle.schema.json",
                provenance_record(
                    "hypothesis_set.schema.json",
                    hypotheses,
                    bundle_id=hypotheses["provenance_bundle_id"],
                ),
                token="hypothesis-set.multi-robot.provenance",
            ),
            submission(
                "conflict_record.schema.json",
                conflict,
                token="conflict.multi-robot",
            ),
            submission(
                "hypothesis_set.schema.json",
                hypotheses,
                token="hypothesis-set.multi-robot",
            ),
        ]
    )
    decision = retention_decision_record(hypotheses)
    store.append_batch(
        [
            submission(
                "provenance_bundle.schema.json",
                provenance_record(
                    "reconciliation_decision.schema.json",
                    decision,
                    bundle_id=decision["provenance_bundle_id"],
                ),
                token="decision.retain.multi-robot.provenance",
            ),
            submission(
                "reconciliation_decision.schema.json",
                decision,
                token="decision.retain.multi-robot",
            ),
        ]
    )
    stored_decision = store.get(decision["decision_id"])
    assert stored_decision is not None
    report = {
        "schema_version": "stewie.conflict_retention_demo/1.0",
        "status": "complete",
        "evidence_level": "controlled_synthetic_demonstration",
        "conflict_id": conflict["conflict_id"],
        "hypothesis_set_id": hypotheses["hypothesis_set_id"],
        "hypothesis_ids": stored_decision["retained_hypothesis_ids"],
        "decision_id": stored_decision["decision_id"],
        "decision": stored_decision["decision"],
        "accepted_head": store.branch_head("branch.accepted"),
        "integrity": store.verify_integrity(),
        "build_identity": build_identity(),
    }
    return store, report
