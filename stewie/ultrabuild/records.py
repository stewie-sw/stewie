"""Deterministic record builders used by scenarios, tests, and replay tools."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from stewie.ultrabuild.canonical import (
    sha256_json,
    state_contract_hash,
    submitted_record_hash,
)
from stewie.ultrabuild.contracts import PRIMARY_KEY_BY_SCHEMA
from stewie.ultrabuild.identity import build_identity


ZERO_HASH = "0" * 64
ACTIVITY_TIME = "2026-07-29T00:00:00Z"


def submission(
    schema_name: str,
    record: Mapping[str, Any],
    *,
    token: str,
    agent_id: str = "software.ultrabuild",
    process_id: str = "process.ultrabuild",
) -> dict[str, Any]:
    return {
        "schema_version": "stewie.record_submission/1.0",
        "submission_id": f"submission.{token}",
        "idempotency_key": f"idempotency.{token}",
        "record_schema": schema_name,
        "producer": {"agent_id": agent_id, "process_id": process_id},
        "record": deepcopy(dict(record)),
    }


def branch_record(
    *,
    branch_id: str,
    branch_kind: str,
    policy_id: str,
    permitted_state_kinds: list[str],
    world_id: str = "world.lunar",
    site_id: str = "site.haworth",
    environment_mode: str = "rehearsal",
    evaluation_visibility: str = "system_visible",
) -> dict[str, Any]:
    return {
        "schema_version": "stewie.branch/1.0",
        "branch_id": branch_id,
        "world_id": world_id,
        "site_id": site_id,
        "branch_kind": branch_kind,
        "environment_mode": environment_mode,
        "evaluation_visibility": evaluation_visibility,
        "base_revision_id": None,
        "head_revision_id": None,
        "head_sequence": 0,
        "policy_id": policy_id,
        "permitted_state_kinds": permitted_state_kinds,
    }


def evidence_spatial() -> dict[str, Any]:
    return {
        "representation": "raster_2_5d",
        "crs": "IAU_2015:30135",
        "frame_id": "frame.site.haworth",
        "transform_chain_id": "transform.haworth.identity",
        "axis_order": ["x", "y", "z"],
        "value_unit": "m",
        "bounds": [0.0, 0.0, 10.0, 10.0],
        "shape": [2, 2],
        "resolution": [5.0, 5.0],
    }


def revision_spatial() -> dict[str, Any]:
    source = evidence_spatial()
    return {
        "region_id": "region.haworth.golden",
        "representation": source["representation"],
        "resolution": source["resolution"],
        "crs": source["crs"],
        "frame_id": source["frame_id"],
        "transform_chain_id": source["transform_chain_id"],
        "axis_order": source["axis_order"],
        "bounds": source["bounds"],
        "shape": source["shape"],
        "units": {"axis": "m", "value": source["value_unit"]},
        "extent_hash": ZERO_HASH,
    }


def revision_spatial_from_evidence(
    spatial: Mapping[str, Any],
    *,
    region_id: str,
) -> dict[str, Any]:
    return {
        "region_id": region_id,
        "representation": spatial["representation"],
        "resolution": deepcopy(spatial["resolution"]),
        "crs": spatial["crs"],
        "frame_id": spatial["frame_id"],
        "transform_chain_id": spatial["transform_chain_id"],
        "axis_order": deepcopy(spatial["axis_order"]),
        "bounds": deepcopy(spatial["bounds"]),
        "shape": deepcopy(spatial["shape"]),
        "units": {"axis": "m", "value": spatial["value_unit"]},
        "extent_hash": ZERO_HASH,
    }


def valid_time(start: float = 10.0, end: float | None = 11.0) -> dict[str, Any]:
    return {
        "start": start,
        "end": end,
        "clock_id": "clock.mission",
        "uncertainty_s": 0.01,
    }


def candidate_uncertainty() -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    for kind in (
        "sensor",
        "localization",
        "geometric",
        "material",
        "temporal",
        "change_attribution",
        "model",
        "inter_robot",
    ):
        if kind in {"sensor", "localization", "geometric", "temporal"}:
            components.append(
                {
                    "kind": kind,
                    "status": "known",
                    "unit": "s" if kind == "temporal" else "m",
                    "value": 0.01 if kind == "temporal" else 0.1,
                    "calibration_id": f"calibration.{kind}.golden",
                }
            )
        else:
            components.append(
                {
                    "kind": kind,
                    "status": "unknown",
                    "unit": "m",
                    "reason_code": f"unknown.{kind}",
                }
            )
    return {
        "model": "independent-components-v1",
        "components": components,
        "aggregate_variance_hash": ZERO_HASH,
        "mask_hash": ZERO_HASH,
        "calibration_status": "assumed",
    }


def observation_record(
    *,
    claim_id: str = "claim.observation.golden",
    provenance_bundle_id: str = "provenance.observation.golden",
    payload_hash: str = ZERO_HASH,
    coverage_hash: str = ZERO_HASH,
    valid_start: float = 10.0,
    valid_end: float = 11.0,
    robot_id: str = "robot.golden",
    source_id: str = "source.stereo.golden",
    pipeline_id: str = "pipeline.stereo.golden",
    spatial: Mapping[str, Any] | None = None,
    byte_size: int = 32,
    sensor_variance_m2: float = 0.0025,
) -> dict[str, Any]:
    sensor_standard_deviation = sensor_variance_m2**0.5
    return {
        "schema_version": "stewie.evidence_claim/1.0",
        "claim_id": claim_id,
        "world_id": "world.lunar",
        "site_id": "site.haworth",
        "branch_id": "branch.evidence",
        "branch_kind": "evidence",
        "evaluation_visibility": "system_visible",
        "source_kind": "observation",
        "state_kind": "observed",
        "source": {
            "source_id": source_id,
            "agent_id": robot_id,
            "instrument_id": {"status": "known", "id": "stereo.golden"},
            "pipeline_id": pipeline_id,
            "algorithm_version": "stereo.v1",
            "calibration_id": {
                "status": "known",
                "id": "calibration.stereo.golden",
            },
            "attestation_key_id": {"status": "known", "id": "key.robot.golden"},
            "hardware_version": {"status": "known", "id": "stereo.hw.v1"},
            "firmware_version": {"status": "known", "id": "stereo.fw.v1"},
        },
        "spatial": deepcopy(evidence_spatial() if spatial is None else dict(spatial)),
        "valid_time": valid_time(valid_start, valid_end),
        "payload": {
            "content_hash": payload_hash,
            "coverage_hash": coverage_hash,
            "media_type": "application/x-stewie-raster",
            "byte_size": byte_size,
            "uri": None,
        },
        "uncertainty": {
            "model": "independent-components-v1",
            "components": [
                {
                    "kind": "sensor",
                    "status": "known",
                    "unit": "m",
                    "value": sensor_standard_deviation,
                    "calibration_id": {
                        "status": "known",
                        "id": "calibration.stereo.golden",
                    },
                },
                {
                    "kind": "localization",
                    "status": "known",
                    "unit": "m",
                    "value": 0.1,
                    "calibration_id": {
                        "status": "known",
                        "id": "calibration.localization.golden",
                    },
                },
                {
                    "kind": "time",
                    "status": "known",
                    "unit": "s",
                    "value": 0.01,
                    "calibration_id": {
                        "status": "known",
                        "id": "calibration.clock.golden",
                    },
                },
            ],
            "calibration_status": "calibrated",
        },
        "provenance_bundle_id": provenance_bundle_id,
        "predecessor_claim_ids": [],
        "dependency_edge_ids": [],
    }


def physics_prediction_record(
    *,
    claim_id: str,
    provenance_bundle_id: str,
    payload_hash: str,
    coverage_hash: str,
    spatial: Mapping[str, Any],
    byte_size: int,
    valid_start: float = 10.0,
    valid_end: float = 11.0,
) -> dict[str, Any]:
    record = observation_record(
        claim_id=claim_id,
        provenance_bundle_id=provenance_bundle_id,
        payload_hash=payload_hash,
        coverage_hash=coverage_hash,
        valid_start=valid_start,
        valid_end=valid_end,
        robot_id="software.terrain-physics",
        source_id="source.terrain-physics",
        pipeline_id="pipeline.terrain-physics.v1",
        spatial=spatial,
        byte_size=byte_size,
        sensor_variance_m2=0.01,
    )
    record.update(
        branch_id="branch.prediction",
        branch_kind="prediction",
        source_kind="physics_prediction",
        state_kind="predicted",
    )
    record["source"].update(
        instrument_id={
            "status": "unknown",
            "reason_code": "software.model.no_instrument",
        },
        calibration_id={
            "status": "known",
            "id": "calibration.terrain-physics.v1",
        },
        hardware_version={
            "status": "unknown",
            "reason_code": "software.model.no_hardware",
        },
        firmware_version={
            "status": "unknown",
            "reason_code": "software.model.no_firmware",
        },
        algorithm_version="terrain-physics.v1",
    )
    return record


def dependency_edge_record(
    *,
    edge_id: str,
    left_claim_id: str,
    right_claim_id: str,
    coverage_hash: str,
    basis: str = "shared_pipeline",
) -> dict[str, Any]:
    return {
        "schema_version": "stewie.dependency_edge/1.0",
        "edge_id": edge_id,
        "world_id": "world.lunar",
        "site_id": "site.haworth",
        "left_claim_id": left_claim_id,
        "right_claim_id": right_claim_id,
        "evaluation_visibility": "system_visible",
        "basis": basis,
        "coverage_hash": coverage_hash,
        "valid_time": valid_time(),
        "derivation_activity_id": f"activity.derive.{edge_id}",
        "uncertainty": {
            "status": "unknown",
            "model": "possible-dependence",
            "unit": "correlation",
            "reason_code": "correlation.not_measured",
        },
        "status": "possible",
    }


def external_action_record(
    *,
    event_id: str = "event.excavation.golden",
    provenance_bundle_id: str = "provenance.action.golden",
    observed_claim_id: str = "claim.observation.golden",
) -> dict[str, Any]:
    return {
        "schema_version": "stewie.action_event/1.0",
        "event_id": event_id,
        "world_id": "world.lunar",
        "site_id": "site.haworth",
        "origin": "external_actor",
        "decision_record_id": None,
        "action_id": "action.excavate.golden",
        "actor_id": "robot.golden",
        "tool_id": "tool.bucket.golden",
        "command_id": "command.excavate.golden",
        "execution_id": "execution.excavate.golden",
        "planned_effect_claim_ids": [],
        "execution_status": "reported",
        "reported_execution_claim_ids": [observed_claim_id],
        "observed_effect_claim_ids": [observed_claim_id],
        "planned_valid_time": valid_time(9.0, 10.0),
        "executed_valid_time": valid_time(9.0, 10.0),
        "spatial_extent_hash": ZERO_HASH,
        "planned_material_transfer": {
            "model_id": "model.bucket.v1",
            "removed_volume_m3": 1.0,
            "deposited_volume_m3": 1.0,
            "uncertainty_m3": 0.1,
        },
        "reported_material_transfer": {
            "model_id": "model.bucket.v1",
            "removed_volume_m3": 1.0,
            "deposited_volume_m3": 1.0,
            "uncertainty_m3": 0.1,
        },
        "status_reason_code": "reported.not_verified",
        "provenance_bundle_id": provenance_bundle_id,
        "evaluation_visibility": "system_visible",
    }


def candidate_record(
    observation: Mapping[str, Any],
    *,
    candidate_id: str = "candidate.golden",
    provenance_bundle_id: str = "provenance.candidate.golden",
    prior_revision_id: str | None = None,
    admitted_observation_ids: list[str] | None = None,
    excluded_evidence: list[dict[str, str]] | None = None,
    payload_hash: str | None = None,
    coverage_hash: str | None = None,
    payload_byte_size: int | None = None,
    construction: str = "plain_mean_of_admissible_observations",
    dependency_edge_ids: list[str] | None = None,
    physics_comparison_ids: list[str] | None = None,
    spatial: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    observation_payload = observation["payload"]
    record = {
        "schema_version": "stewie.state_candidate/1.0",
        "candidate_id": candidate_id,
        "world_id": observation["world_id"],
        "site_id": observation["site_id"],
        "branch_id": "branch.accepted",
        "prior_revision_id": prior_revision_id,
        "admitted_observation_ids": (
            [observation["claim_id"]] if admitted_observation_ids is None else list(admitted_observation_ids)
        ),
        "excluded_evidence": ([] if excluded_evidence is None else deepcopy(excluded_evidence)),
        "spatial": deepcopy(revision_spatial() if spatial is None else dict(spatial)),
        "valid_time": deepcopy(observation["valid_time"]),
        "uncertainty": candidate_uncertainty(),
        "payload": {
            "content_hash": (observation_payload["content_hash"] if payload_hash is None else payload_hash),
            "coverage_hash": (observation_payload["coverage_hash"] if coverage_hash is None else coverage_hash),
            "media_type": observation_payload["media_type"],
            "byte_size": (observation_payload["byte_size"] if payload_byte_size is None else payload_byte_size),
        },
        "state_contract_hash": "",
        "construction": construction,
        "policy": {
            "policy_id": "policy.promotion",
            "version": "v1",
            "config_hash": ZERO_HASH,
        },
        "dependency_edge_ids": ([] if dependency_edge_ids is None else list(dependency_edge_ids)),
        "physics_comparison_ids": ([] if physics_comparison_ids is None else list(physics_comparison_ids)),
        "provenance_bundle_id": provenance_bundle_id,
    }
    record["state_contract_hash"] = state_contract_hash(record)
    return record


def promotion_decision_record(
    stored_candidate: Mapping[str, Any],
    *,
    revision_id: str = "revision.accepted.golden",
    decision_id: str = "decision.promote.golden",
    provenance_bundle_id: str = "provenance.decision.golden",
) -> dict[str, Any]:
    payload = stored_candidate["payload"]
    return {
        "schema_version": "stewie.reconciliation_decision/1.0",
        "decision_id": decision_id,
        "world_id": stored_candidate["world_id"],
        "site_id": stored_candidate["site_id"],
        "branch_id": stored_candidate["branch_id"],
        "prior_revision_id": stored_candidate["prior_revision_id"],
        "policy": deepcopy(stored_candidate["policy"]),
        "admitted_observation_ids": list(stored_candidate["admitted_observation_ids"]),
        "excluded_evidence": deepcopy(stored_candidate["excluded_evidence"]),
        "dependency_edge_ids": list(stored_candidate["dependency_edge_ids"]),
        "physics_evidence_ids": list(stored_candidate["physics_comparison_ids"]),
        "decision": "PROMOTE",
        "reason_codes": ["admissible.observation"],
        "candidate": {
            "candidate_id": stored_candidate["candidate_id"],
            "candidate_record_hash": stored_candidate["content_hash"],
            "payload_hash": payload["content_hash"],
            "coverage_hash": payload["coverage_hash"],
            "state_contract_hash": stored_candidate["state_contract_hash"],
            "construction": stored_candidate["construction"],
        },
        "resulting_revision_id": revision_id,
        "retained_hypothesis_ids": [],
        "valid_time": deepcopy(stored_candidate["valid_time"]),
        "provenance_bundle_id": provenance_bundle_id,
        "review": {"status": "not_required", "reviewer_id": "policy.auto"},
        "metrics": {
            "effective_support": 1.0,
            "observed_cells": 4,
            "residual_rms_m": 0.0,
            "variance_bound_m2_hash": ZERO_HASH,
        },
    }


def promoted_revision_record(
    stored_candidate: Mapping[str, Any],
    decision: Mapping[str, Any],
    *,
    event_id: str = "event.excavation.golden",
    provenance_bundle_id: str = "provenance.revision.golden",
    branch_revision_sequence: int = 1,
) -> dict[str, Any]:
    payload = stored_candidate["payload"]
    record = {
        "schema_version": "stewie.world_revision/1.0",
        "revision_id": decision["resulting_revision_id"],
        "world_id": stored_candidate["world_id"],
        "site_id": stored_candidate["site_id"],
        "branch_id": stored_candidate["branch_id"],
        "parent_revision_ids": (
            [stored_candidate["prior_revision_id"]] if stored_candidate["prior_revision_id"] is not None else []
        ),
        "state_kind": "reconciled",
        "authority_scope": {
            "environment_mode": "rehearsal",
            "branch_kind": "accepted",
            "policy_id": decision["policy"]["policy_id"],
            "evaluation_visibility": "system_visible",
        },
        "spatial": deepcopy(stored_candidate["spatial"]),
        "valid_time": deepcopy(stored_candidate["valid_time"]),
        "uncertainty": deepcopy(stored_candidate["uncertainty"]),
        "state_contract_hash": stored_candidate["state_contract_hash"],
        "payload_hash": payload["content_hash"],
        "coverage_hash": payload["coverage_hash"],
        "payload_media_type": payload["media_type"],
        "payload_byte_size": payload["byte_size"],
        "claim_ids": list(stored_candidate["admitted_observation_ids"]),
        "event_ids": [event_id],
        "provenance_bundle_id": provenance_bundle_id,
        "reconciliation_decision_id": decision["decision_id"],
        "candidate_id": stored_candidate["candidate_id"],
        "candidate_record_hash": stored_candidate["content_hash"],
        "prior_head_revision_id": stored_candidate["prior_revision_id"],
        "branch_revision_sequence": branch_revision_sequence,
        "supersedes_revision_ids": [],
        "invalidated_artifact_ids": [],
    }
    record["state_contract_hash"] = state_contract_hash(record)
    return record


def query_request_record(
    stored_revision: Mapping[str, Any],
    *,
    request_id: str = "query.golden",
    known_at_sequence: int | None = None,
) -> dict[str, Any]:
    """Build an immutable bitemporal query against an exact revision contract."""

    spatial = stored_revision["spatial"]
    transaction = stored_revision["transaction_time"]
    return {
        "schema_version": "stewie.query_request/1.0",
        "request_id": request_id,
        "world_id": stored_revision["world_id"],
        "site_id": stored_revision["site_id"],
        "branch_id": stored_revision["branch_id"],
        "policy_id": stored_revision["authority_scope"]["policy_id"],
        "region_id": spatial["region_id"],
        "requested_state_kinds": [stored_revision["state_kind"]],
        "valid_at": {
            "instant": stored_revision["valid_time"]["start"],
            "clock_id": stored_revision["valid_time"]["clock_id"],
            "uncertainty_s": stored_revision["valid_time"]["uncertainty_s"],
        },
        "known_at": {
            "sequence": (transaction["sequence"] if known_at_sequence is None else known_at_sequence),
            "recorded_at": transaction["recorded_at"],
        },
        "representation": spatial["representation"],
        "resolution": deepcopy(spatial["resolution"]),
        "frame_id": spatial["frame_id"],
        "units": deepcopy(spatial["units"]),
        "requesting_agent_id": "planner.golden",
    }


def resolved_query_lens_record(
    stored_request: Mapping[str, Any],
    stored_revision: Mapping[str, Any],
    *,
    lens_id: str = "lens.golden",
    projection_transaction_sequence: int,
) -> dict[str, Any]:
    """Bind a query result to the request and exact durable revision."""

    copied_fields = (
        "world_id",
        "site_id",
        "branch_id",
        "policy_id",
        "region_id",
        "requested_state_kinds",
        "valid_at",
        "known_at",
        "representation",
        "resolution",
        "frame_id",
        "units",
        "requesting_agent_id",
    )
    record: dict[str, Any] = {
        "schema_version": "stewie.query_lens/1.0",
        "lens_id": lens_id,
        "query_request_id": stored_request["request_id"],
        **{field: deepcopy(stored_request[field]) for field in copied_fields},
        "status": "resolved",
        "reason_codes": [],
        "available_claim_ids": list(stored_revision["claim_ids"]),
        "resolved_revision_id": stored_revision["revision_id"],
        "resolved_state_kind": stored_revision["state_kind"],
        "projection_transaction_sequence": projection_transaction_sequence,
        "result_coverage_hash": stored_revision["coverage_hash"],
        "result_payload_hash": stored_revision["payload_hash"],
    }
    return record


def planning_decision_record(
    stored_lens: Mapping[str, Any],
    stored_revision: Mapping[str, Any],
    *,
    decision_record_id: str = "planner.decision.golden",
    provenance_bundle_id: str = "provenance.planner.decision.golden",
) -> dict[str, Any]:
    """Build a planner choice that discloses the world-state lens it consumed."""

    return {
        "schema_version": "stewie.decision_record/1.0",
        "decision_record_id": decision_record_id,
        "world_id": stored_revision["world_id"],
        "site_id": stored_revision["site_id"],
        "mission_id": "mission.golden",
        "task_id": "task.verify.golden",
        "robot_id": "robot.golden",
        "query_lens_id": stored_lens["lens_id"],
        "world_revision_id": stored_revision["revision_id"],
        "alternatives": [
            {
                "action_id": "action.rescan.golden",
                "cost_components": {
                    "energy_j": 250.0,
                    "duration_s": 30.0,
                    "risk": 0.02,
                },
                "feasible": True,
                "reason_codes": ["uncertainty.bounded"],
            },
            {
                "action_id": "action.defer.golden",
                "cost_components": {
                    "energy_j": 0.0,
                    "duration_s": 120.0,
                    "risk": 0.1,
                },
                "feasible": True,
                "reason_codes": ["latency.penalty"],
            },
        ],
        "constraint_set_hash": ZERO_HASH,
        "selected_action_id": "action.rescan.golden",
        "expected_outcome_claim_ids": [],
        "value_of_information": {
            "decision": "act",
            "expected_decision_change_probability": 0.05,
            "expected_cost": 250.0,
        },
        "approval": {
            "status": "not_required",
            "actor_id": "policy.autonomy.rehearsal",
            "reason_code": "rehearsal.autonomy.allowed",
        },
        "provenance_bundle_id": provenance_bundle_id,
    }


def autonomous_action_record(
    stored_decision: Mapping[str, Any],
    *,
    event_id: str = "event.rescan.golden",
    provenance_bundle_id: str = "provenance.event.rescan.golden",
) -> dict[str, Any]:
    """Build a planned action whose authority traces to a planner decision."""

    return {
        "schema_version": "stewie.action_event/1.0",
        "event_id": event_id,
        "world_id": stored_decision["world_id"],
        "site_id": stored_decision["site_id"],
        "origin": "autonomous_decision",
        "decision_record_id": stored_decision["decision_record_id"],
        "action_id": stored_decision["selected_action_id"],
        "actor_id": stored_decision["robot_id"],
        "tool_id": "sensor.stereo.golden",
        "command_id": "command.rescan.golden",
        "execution_id": None,
        "planned_effect_claim_ids": list(stored_decision["expected_outcome_claim_ids"]),
        "execution_status": "planned",
        "reported_execution_claim_ids": [],
        "observed_effect_claim_ids": [],
        "planned_valid_time": valid_time(12.0, 13.0),
        "executed_valid_time": None,
        "spatial_extent_hash": ZERO_HASH,
        "planned_material_transfer": {
            "model_id": "model.no_material_transfer.v1",
            "removed_volume_m3": 0.0,
            "deposited_volume_m3": 0.0,
            "uncertainty_m3": 0.0,
        },
        "reported_material_transfer": None,
        "status_reason_code": "awaiting.execution",
        "provenance_bundle_id": provenance_bundle_id,
        "evaluation_visibility": "system_visible",
    }


def invalidation_event_record(
    stored_revision: Mapping[str, Any],
    *,
    evidence_id: str,
    event_id: str = "supersession.invalidate.golden",
    provenance_bundle_id: str = "provenance.supersession.invalidate.golden",
) -> dict[str, Any]:
    """Invalidate a revision without erasing it from historical query space."""

    return {
        "schema_version": "stewie.supersession_event/1.0",
        "event_id": event_id,
        "world_id": stored_revision["world_id"],
        "site_id": stored_revision["site_id"],
        "branch_id": stored_revision["branch_id"],
        "event_kind": "invalidate",
        "target_record_id": stored_revision["revision_id"],
        "reason_codes": ["verification.failed"],
        "evidence_ids": [evidence_id],
        "provenance_bundle_id": provenance_bundle_id,
    }


def conflict_record(
    left_claim: Mapping[str, Any],
    right_claim: Mapping[str, Any],
    *,
    conflict_id: str = "conflict.multi-robot",
    hypothesis_set_id: str = "hypothesis-set.multi-robot",
    provenance_bundle_id: str = "provenance.conflict.multi-robot",
) -> dict[str, Any]:
    claim_ids = sorted([left_claim["claim_id"], right_claim["claim_id"]])
    left_bounds = left_claim["spatial"]["bounds"]
    right_bounds = right_claim["spatial"]["bounds"]
    dimensions = len(left_bounds) // 2
    bounds = [
        *[max(left_bounds[index], right_bounds[index]) for index in range(dimensions)],
        *[
            min(
                left_bounds[index + dimensions],
                right_bounds[index + dimensions],
            )
            for index in range(dimensions)
        ],
    ]
    left_valid = left_claim["valid_time"]
    right_valid = right_claim["valid_time"]
    ends = [value for value in (left_valid["end"], right_valid["end"]) if value is not None]
    overlap = {
        "start": max(left_valid["start"], right_valid["start"]),
        "end": min(ends) if ends else None,
        "clock_id": left_valid["clock_id"],
        "uncertainty_s": max(
            left_valid["uncertainty_s"],
            right_valid["uncertainty_s"],
        ),
    }
    overlap_hash = sha256_json(
        {
            "claim_ids": claim_ids,
            "bounds": bounds,
            "valid_time": {
                "start": overlap["start"],
                "end": overlap["end"],
                "clock_id": overlap["clock_id"],
            },
        }
    )
    return {
        "schema_version": "stewie.conflict_record/1.0",
        "conflict_id": conflict_id,
        "world_id": left_claim["world_id"],
        "site_id": left_claim["site_id"],
        "branch_id": "branch.accepted",
        "claim_ids": claim_ids,
        "reason_codes": ["geometric.disagreement"],
        "spatial_overlap_hash": overlap_hash,
        "valid_time": overlap,
        "hypothesis_set_id": hypothesis_set_id,
        "status": "open",
        "provenance_bundle_id": provenance_bundle_id,
    }


def hypothesis_set_record(
    conflict: Mapping[str, Any],
    *,
    provenance_bundle_id: str = "provenance.hypothesis-set.multi-robot",
) -> dict[str, Any]:
    hypotheses = [
        {
            "hypothesis_id": f"hypothesis.{claim_id}",
            "claim_ids": [claim_id],
            "supporting_evidence_ids": [claim_id],
        }
        for claim_id in conflict["claim_ids"]
    ]
    return {
        "schema_version": "stewie.hypothesis_set/1.0",
        "hypothesis_set_id": conflict["hypothesis_set_id"],
        "world_id": conflict["world_id"],
        "site_id": conflict["site_id"],
        "branch_id": conflict["branch_id"],
        "conflict_id": conflict["conflict_id"],
        "hypotheses": hypotheses,
        "status": "open",
        "provenance_bundle_id": provenance_bundle_id,
    }


def retention_decision_record(
    hypothesis_set: Mapping[str, Any],
    *,
    decision_id: str = "decision.retain.multi-robot",
    provenance_bundle_id: str = "provenance.decision.retain.multi-robot",
) -> dict[str, Any]:
    claim_ids = sorted(
        {claim_id for hypothesis in hypothesis_set["hypotheses"] for claim_id in hypothesis["claim_ids"]}
    )
    return {
        "schema_version": "stewie.reconciliation_decision/1.0",
        "decision_id": decision_id,
        "world_id": hypothesis_set["world_id"],
        "site_id": hypothesis_set["site_id"],
        "branch_id": hypothesis_set["branch_id"],
        "prior_revision_id": None,
        "policy": {
            "policy_id": "policy.promotion",
            "version": "v1",
            "config_hash": ZERO_HASH,
        },
        "admitted_observation_ids": claim_ids,
        "excluded_evidence": [],
        "physics_evidence_ids": [],
        "dependency_edge_ids": [],
        "decision": "RETAIN_HYPOTHESES",
        "reason_codes": ["support.not_decisive"],
        "retained_hypothesis_ids": [hypothesis["hypothesis_id"] for hypothesis in hypothesis_set["hypotheses"]],
        "hypothesis_set_id": hypothesis_set["hypothesis_set_id"],
        "valid_time": valid_time(),
        "provenance_bundle_id": provenance_bundle_id,
        "review": {
            "status": "not_required",
            "reviewer_id": "policy.auto",
        },
        "metrics": {
            "effective_support": float(len(claim_ids)),
            "observed_cells": 4,
            "residual_rms_m": 0.5,
            "variance_bound_m2_hash": ZERO_HASH,
        },
    }


def provenance_record(
    schema_name: str,
    record: Mapping[str, Any],
    *,
    bundle_id: str,
) -> dict[str, Any]:
    primary_key = PRIMARY_KEY_BY_SCHEMA[schema_name]
    owner_id = str(record[primary_key])
    source = record.get("source", {})
    responsible_agent = (
        str(source.get("agent_id")) if isinstance(source, Mapping) and source.get("agent_id") else "software.ultrabuild"
    )
    activity_id = (
        str(source.get("pipeline_id"))
        if isinstance(source, Mapping) and source.get("pipeline_id")
        else f"activity.generate.{owner_id}"
    )
    algorithm_version = (
        str(source.get("algorithm_version"))
        if isinstance(source, Mapping) and source.get("algorithm_version")
        else "ultrabuild.v1"
    )
    pipeline_id = (
        str(source.get("pipeline_id"))
        if isinstance(source, Mapping) and source.get("pipeline_id")
        else f"pipeline.ultrabuild.{schema_name.removesuffix('.schema.json')}"
    )
    record_entity_id = f"entity.record.{owner_id}"
    payload = record.get("payload", {})
    payload_hash = payload.get("content_hash") if isinstance(payload, Mapping) else record.get("payload_hash")
    coverage_hash = payload.get("coverage_hash") if isinstance(payload, Mapping) else record.get("coverage_hash")
    payload_entity_id = f"entity.payload.{owner_id}" if isinstance(payload_hash, str) else None
    coverage_entity_id = f"entity.coverage.{owner_id}" if isinstance(coverage_hash, str) else None
    kind_by_schema = {
        "evidence_claim.schema.json": "claim",
        "world_revision.schema.json": "revision",
        "reconciliation_decision.schema.json": "decision",
        "decision_record.schema.json": "decision",
    }
    entities = [
        {
            "entity_id": record_entity_id,
            "kind": kind_by_schema.get(schema_name, "artifact"),
            "content_hash": submitted_record_hash(record),
            "media_type": f"application/vnd.stewie.{schema_name[:-12]}",
        }
    ]
    relations = [
        {
            "kind": "wasGeneratedBy",
            "subject_id": record_entity_id,
            "object_id": activity_id,
        },
        {
            "kind": "wasAttributedTo",
            "subject_id": record_entity_id,
            "object_id": responsible_agent,
        },
    ]
    if payload_entity_id is not None:
        entities.append(
            {
                "entity_id": payload_entity_id,
                "kind": "payload",
                "content_hash": str(payload_hash),
                "media_type": (
                    payload.get("media_type", "application/octet-stream")
                    if isinstance(payload, Mapping)
                    else str(record.get("payload_media_type", "application/octet-stream"))
                ),
            }
        )
        relations.append(
            {
                "kind": "used",
                "subject_id": activity_id,
                "object_id": payload_entity_id,
            }
        )
    if coverage_entity_id is not None:
        entities.append(
            {
                "entity_id": coverage_entity_id,
                "kind": "payload",
                "content_hash": str(coverage_hash),
                "media_type": "application/x-stewie-coverage-mask",
            }
        )

    spatial = record.get("spatial", {})
    transform_ids = []
    transforms = []
    transform_id = spatial.get("transform_chain_id") if isinstance(spatial, Mapping) else None
    if isinstance(transform_id, str):
        transform_ids.append(transform_id)
        transforms.append(
            {
                "transform_id": transform_id,
                "source_frame": "frame.raw",
                "target_frame": spatial["frame_id"],
                "payload_hash": ZERO_HASH,
                "valid_time": deepcopy(record.get("valid_time", valid_time())),
            }
        )

    calibration_ids: set[str] = set()
    if isinstance(source, Mapping):
        calibration = source.get("calibration_id")
        if isinstance(calibration, Mapping) and calibration.get("status") == "known":
            calibration_ids.add(str(calibration["id"]))
    uncertainty = record.get("uncertainty", {})
    if isinstance(uncertainty, Mapping):
        for component in uncertainty.get("components", []):
            if not isinstance(component, Mapping):
                continue
            calibration = component.get("calibration_id")
            if isinstance(calibration, Mapping) and calibration.get("status") == "known":
                calibration_ids.add(str(calibration["id"]))
            elif isinstance(calibration, str):
                calibration_ids.add(calibration)
    instrument = source.get("instrument_id", {}) if isinstance(source, Mapping) else {}
    instrument_id = (
        str(instrument.get("id"))
        if isinstance(instrument, Mapping) and instrument.get("status") == "known"
        else "instrument.ultrabuild"
    )
    calibrations = [
        {
            "calibration_id": calibration_id,
            "instrument_id": instrument_id,
            "payload_hash": ZERO_HASH,
            "valid_time": deepcopy(record.get("valid_time", valid_time())),
            "status": "calibrated",
        }
        for calibration_id in sorted(calibration_ids)
    ]
    activity_kind = {
        "action_event.schema.json": "execute",
        "decision_record.schema.json": "plan",
        "evidence_claim.schema.json": "observe",
        "reconciliation_decision.schema.json": "reconcile",
        "world_revision.schema.json": "reconcile",
    }.get(schema_name, "transform")
    identity = build_identity()
    code_commit = str(identity["code_commit"])
    code_commit_status = (
        "verified"
        if len(code_commit) == 40 and all(character in "0123456789abcdef" for character in code_commit)
        else "unavailable"
    )
    if code_commit_status == "unavailable":
        code_commit = "unavailable"

    def provenance_qualified(
        field: str,
        fallback: str,
    ) -> dict[str, Any]:
        value = source.get(field) if isinstance(source, Mapping) else None
        if isinstance(value, Mapping):
            if value.get("status") == "known" and isinstance(value.get("id"), str):
                return {"status": "known", "value": value["id"]}
            if value.get("status") == "unknown" and isinstance(
                value.get("reason_code"),
                str,
            ):
                return {
                    "status": "unknown",
                    "reason_code": value["reason_code"],
                }
        return {"status": "known", "value": fallback}

    subject: dict[str, Any] = {
        "record_id": owner_id,
        "record_schema": schema_name,
        "record_entity_id": record_entity_id,
        "submitted_record_hash": submitted_record_hash(record),
        "generating_activity_id": activity_id,
        "responsible_agent_id": responsible_agent,
        "transform_ids": transform_ids,
        "calibration_ids": sorted(calibration_ids),
    }
    if payload_entity_id is not None:
        subject["payload_entity_id"] = payload_entity_id
        subject["payload_hash"] = payload_hash
    if coverage_entity_id is not None:
        subject["coverage_entity_id"] = coverage_entity_id
        subject["coverage_hash"] = coverage_hash
    return {
        "schema_version": "stewie.provenance_bundle/1.0",
        "bundle_id": bundle_id,
        "world_id": record["world_id"],
        "site_id": record["site_id"],
        "subject": subject,
        "agents": [
            {
                "agent_id": responsible_agent,
                "kind": "robot" if responsible_agent.startswith("robot.") else "software",
                "attestation_key_id": provenance_qualified(
                    "attestation_key_id",
                    f"key.{responsible_agent}",
                ),
                "hardware_version": provenance_qualified(
                    "hardware_version",
                    "hardware.v1",
                ),
                "firmware_version": provenance_qualified(
                    "firmware_version",
                    "firmware.v1",
                ),
            }
        ],
        "activities": [
            {
                "activity_id": activity_id,
                "kind": activity_kind,
                "agent_id": responsible_agent,
                "pipeline_id": pipeline_id,
                "algorithm_version": algorithm_version,
                "code_commit": code_commit,
                "code_commit_status": code_commit_status,
                "package_version": str(identity["package_version"]),
                "source_dirty": identity["source_dirty"],
                "configuration_hash": ZERO_HASH,
                "seed": 1,
                "started_at": ACTIVITY_TIME,
                "ended_at": ACTIVITY_TIME,
            }
        ],
        "entities": entities,
        "relations": relations,
        "transforms": transforms,
        "calibrations": calibrations,
    }
