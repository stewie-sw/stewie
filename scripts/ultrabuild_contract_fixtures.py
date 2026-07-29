"""Positive and adversarial fixtures for the UltraBuild Barrier-2 contracts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from stewie.ultrabuild.validation import (
    canonical_content_hash,
    canonical_scenario_id,
)


ZERO_HASH = "0" * 64
RECORDED_AT = "2026-07-28T12:00:00Z"


def _known(value: str) -> dict[str, str]:
    return {"status": "known", "id": value}


def _finish(record: dict[str, Any]) -> dict[str, Any]:
    record["content_hash"] = canonical_content_hash(record)
    return record


def observation(
    *,
    claim_id: str = "claim.obs.1",
    world_id: str = "world.lunar",
    site_id: str = "site.haworth",
) -> dict[str, Any]:
    return _finish(
        {
            "schema_version": "stewie.evidence_claim/1.0",
            "claim_id": claim_id,
            "world_id": world_id,
            "site_id": site_id,
            "branch_id": "branch.evidence",
            "branch_kind": "evidence",
            "evaluation_visibility": "system_visible",
            "source_kind": "observation",
            "state_kind": "observed",
            "source": {
                "source_id": "source.stereo.1",
                "agent_id": "robot.a",
                "instrument_id": _known("stereo.1"),
                "pipeline_id": "pipeline.stereo",
                "algorithm_version": "stereo.v1",
                "calibration_id": _known("calibration.stereo.1"),
                "attestation_key_id": _known("key.robot.a"),
                "hardware_version": _known("stereo.hw.1"),
                "firmware_version": _known("stereo.fw.1"),
            },
            "spatial": {
                "representation": "raster_2_5d",
                "crs": "IAU_2015:30135",
                "frame_id": "frame.site.haworth",
                "transform_chain_id": "transform.1",
                "axis_order": ["x", "y", "z"],
                "value_unit": "m",
                "bounds": [0.0, 0.0, 10.0, 10.0],
                "shape": [2, 2],
                "resolution": [5.0, 5.0],
            },
            "valid_time": {
                "start": 10.0,
                "end": 11.0,
                "clock_id": "clock.mission",
                "uncertainty_s": 0.01,
            },
            "transaction_time": {"sequence": 1, "recorded_at": RECORDED_AT},
            "payload": {
                "content_hash": ZERO_HASH,
                "coverage_hash": ZERO_HASH,
                "media_type": "application/x-stewie-raster",
                "byte_size": 32,
                "uri": None,
            },
            "uncertainty": {
                "model": "independent-components-v1",
                "components": [
                    {
                        "kind": "sensor",
                        "status": "known",
                        "unit": "m",
                        "value": 0.05,
                        "calibration_id": _known("calibration.stereo.1"),
                    },
                    {
                        "kind": "localization",
                        "status": "known",
                        "unit": "m",
                        "value": 0.1,
                        "calibration_id": _known("calibration.localization.1"),
                    },
                    {
                        "kind": "time",
                        "status": "known",
                        "unit": "s",
                        "value": 0.01,
                        "calibration_id": _known("calibration.clock.1"),
                    },
                ],
                "calibration_status": "calibrated",
            },
            "provenance_bundle_id": "provenance.1",
            "predecessor_claim_ids": [],
            "dependency_edge_ids": [],
        }
    )


def abstain_decision() -> dict[str, Any]:
    return _finish(
        {
            "schema_version": "stewie.reconciliation_decision/1.0",
            "decision_id": "decision.abstain.1",
            "world_id": "world.lunar",
            "site_id": "site.haworth",
            "branch_id": "branch.accepted",
            "prior_revision_id": "revision.0",
            "policy": {
                "policy_id": "policy.promotion",
                "version": "v1",
                "config_hash": ZERO_HASH,
            },
            "admitted_observation_ids": [],
            "excluded_evidence": [{"claim_id": "claim.stale.1", "reason_code": "stale"}],
            "dependency_edge_ids": [],
            "physics_evidence_ids": [],
            "decision": "ABSTAIN",
            "reason_codes": ["no_admissible_observation"],
            "retained_hypothesis_ids": [],
            "metrics": {"effective_support": 0.0, "observed_cells": 0},
            "valid_time": {
                "start": 10.0,
                "end": 11.0,
                "clock_id": "clock.mission",
                "uncertainty_s": 0.01,
            },
            "transaction_time": {"sequence": 3, "recorded_at": RECORDED_AT},
            "provenance_bundle_id": "provenance.1",
            "review": {"status": "not_required", "reviewer_id": "policy.auto"},
            "recorded_at": RECORDED_AT,
        }
    )


def scenario() -> dict[str, Any]:
    record = {
        "schema_version": "stewie.scenario/1.0",
        "site_id": "site.haworth",
        "domain": "lunar",
        "research_questions": ["RQ1"],
        "terrain": {
            "source_id": "terrain.haworth",
            "content_hash": ZERO_HASH,
            "crop": [0, 0, 100, 100],
            "crs": "IAU_2015:30135",
            "units": "m",
            "license_status": "verified",
        },
        "robots": ["robot.a"],
        "candidate_visible_actions": {
            "manifest_id": "candidate.actions.1",
            "content_hash": ZERO_HASH,
            "mount": "/candidate/actions",
        },
        "withheld_execution_truth": {
            "manifest_id": "reference.actions.1",
            "content_hash": ZERO_HASH,
            "evaluator_mount": "/reference/actions",
        },
        "evidence_sequence": [
            {
                "sequence": 0,
                "claim_id": "claim.obs.1",
                "available_to_candidate": True,
                "receipt_delay_s": 0.0,
            }
        ],
        "systems": ["stewie.full", "baseline.latest"],
        "ablations": ["without.bitemporal"],
        "perturbations": {
            "observation_delay_s": {
                "levels": [0, 10],
                "generation_process_id": "fault.delay.v1",
                "oracle_independent_of_estimator": True,
            }
        },
        "seeds": [1, 2],
        "experimental_units": {
            "unit_kind": "terrain_window",
            "unit_ids": ["unit.1", "unit.2"],
            "resampling_level": "terrain_window",
        },
        "primary_endpoint": {
            "metric": "harmful_acceptance_rate",
            "direction": "lower",
            "decision_threshold": 0.05,
            "aggregation": "mean_by_terrain_window",
        },
        "minimum_effect": {
            "metric": "harmful_acceptance_rate",
            "value": 0.01,
            "basis": "assumed",
        },
        "sample_size_plan": {
            "independent_units": 2,
            "seeds_per_unit": 2,
            "power": 0.8,
            "alpha": 0.05,
            "pilot_scenario_ids": [],
        },
        "exclusion_rules": ["exclude_only_schema-invalid_source_bundles_before_execution"],
        "stopping_rule": {"kind": "fixed_count", "planned_trial_count": 4},
        "statistical_model": {
            "model_id": "model.blocked_difference.v1",
            "estimand": "paired_mean_difference",
            "blocking_factors": ["terrain_action_pair"],
            "interval": "bootstrap",
        },
        "multiplicity_plan": {
            "family_id": "family.rq1.primary",
            "method": "none_single_primary",
            "ordered_endpoints": ["harmful_acceptance_rate"],
        },
        "harm_tolerance": {
            "metric": "harmful_acceptance_rate",
            "values": [0.01, 0.05],
            "basis": "assumed",
        },
        "metrics": ["harmful_acceptance_rate", "abstention_rate"],
        "reference_firewall": {
            "candidate_process": "candidate-container",
            "evaluator_process": "evaluator-container",
            "candidate_identity": "identity.candidate",
            "evaluator_identity": "identity.evaluator",
            "separate_credentials": True,
            "candidate_reference_access": False,
            "evaluator_reference_access": True,
            "isolation_mechanism": "separate_container_mounts",
            "reference_mount_after_candidate_freeze": True,
            "candidate_output_freeze_protocol": "hash_then_unmount_candidate_inputs",
            "poison_test_id": "test.reference.poison.v1",
            "poison_attestation_required": True,
        },
        "code_commit": "d1056d9deff4e540557b13c8cb78fc799330410e",
    }
    record["scenario_id"] = canonical_scenario_id(record)
    return record


def fixtures() -> list[dict[str, Any]]:
    valid_observation = observation()
    valid_abstain = abstain_decision()
    valid_scenario = scenario()

    physics_as_observation = deepcopy(valid_observation)
    physics_as_observation["source_kind"] = "physics_prediction"
    physics_as_observation["content_hash"] = canonical_content_hash(physics_as_observation)

    inverted_time = deepcopy(valid_observation)
    inverted_time["valid_time"]["end"] = 5.0
    inverted_time["content_hash"] = canonical_content_hash(inverted_time)

    altered_payload = deepcopy(valid_observation)
    altered_payload["payload"]["content_hash"] = "1" * 64

    retain_without_hypotheses = deepcopy(valid_abstain)
    retain_without_hypotheses["decision"] = "RETAIN_HYPOTHESES"
    retain_without_hypotheses["reason_codes"] = ["conflict"]
    retain_without_hypotheses["content_hash"] = canonical_content_hash(retain_without_hypotheses)

    abstain_with_revision = deepcopy(valid_abstain)
    abstain_with_revision["resulting_revision_id"] = "revision.illegal"
    abstain_with_revision["content_hash"] = canonical_content_hash(abstain_with_revision)

    same_process_firewall = deepcopy(valid_scenario)
    same_process_firewall["reference_firewall"]["evaluator_process"] = "candidate-container"
    same_process_firewall["scenario_id"] = canonical_scenario_id(same_process_firewall)

    return [
        {
            "id": "valid-observation",
            "schema": "evidence_claim.schema.json",
            "expect_valid": True,
            "record": valid_observation,
        },
        {
            "id": "valid-no-evidence-abstain",
            "schema": "reconciliation_decision.schema.json",
            "expect_valid": True,
            "record": valid_abstain,
        },
        {
            "id": "valid-separated-reference-firewall",
            "schema": "scenario.schema.json",
            "expect_valid": True,
            "record": valid_scenario,
        },
        {
            "id": "reject-physics-labelled-observed",
            "schema": "evidence_claim.schema.json",
            "expect_valid": False,
            "record": physics_as_observation,
        },
        {
            "id": "reject-inverted-valid-time",
            "schema": "evidence_claim.schema.json",
            "expect_valid": False,
            "record": inverted_time,
        },
        {
            "id": "reject-payload-tampering",
            "schema": "evidence_claim.schema.json",
            "expect_valid": False,
            "record": altered_payload,
        },
        {
            "id": "reject-retain-without-hypotheses",
            "schema": "reconciliation_decision.schema.json",
            "expect_valid": False,
            "record": retain_without_hypotheses,
        },
        {
            "id": "reject-abstain-with-resulting-revision",
            "schema": "reconciliation_decision.schema.json",
            "expect_valid": False,
            "record": abstain_with_revision,
        },
        {
            "id": "reject-vacuous-reference-firewall",
            "schema": "scenario.schema.json",
            "expect_valid": False,
            "record": same_process_firewall,
        },
    ]


def record_set_fixtures() -> list[dict[str, Any]]:
    claim = observation()
    candidate = _finish(
        {
            "schema_version": "stewie.state_candidate/1.0",
            "candidate_id": "candidate.cross-site",
            "world_id": "world.lunar",
            "site_id": "site.shackleton",
            "branch_id": "branch.proposed",
            "prior_revision_id": "revision.0",
            "admitted_observation_ids": [claim["claim_id"]],
            "excluded_evidence": [],
            "payload": {
                "content_hash": ZERO_HASH,
                "coverage_hash": ZERO_HASH,
                "media_type": "application/x-stewie-raster",
                "byte_size": 32,
            },
            "construction": "plain_mean_of_admissible_observations",
            "policy": {
                "policy_id": "policy.promotion",
                "version": "v1",
                "config_hash": ZERO_HASH,
            },
            "dependency_edge_ids": [],
            "physics_comparison_ids": [],
            "provenance_bundle_id": "provenance.1",
            "transaction_time": {"sequence": 2, "recorded_at": RECORDED_AT},
        }
    )
    revision_without_branch = _finish(
        {
            "schema_version": "stewie.world_revision/1.0",
            "revision_id": "revision.missing-branch",
            "world_id": "world.lunar",
            "site_id": "site.haworth",
            "branch_id": "branch.missing",
            "parent_revision_ids": [],
            "state_kind": "planned",
            "authority_scope": {
                "environment_mode": "dev",
                "branch_kind": "plan",
                "policy_id": "policy.plan",
                "evaluation_visibility": "system_visible",
            },
            "spatial": {
                "region_id": "region.test",
                "representation": "raster_2_5d",
                "resolution": [5.0, 5.0],
                "crs": "IAU_2015:30135",
                "frame_id": "frame.site.haworth",
                "units": {"axis": "m", "value": "m"},
                "extent_hash": ZERO_HASH,
            },
            "valid_time": {
                "start": 10.0,
                "end": 11.0,
                "clock_id": "clock.mission",
                "uncertainty_s": 0.01,
            },
            "transaction_time": {"sequence": 2, "recorded_at": RECORDED_AT},
            "payload_hash": ZERO_HASH,
            "coverage_hash": ZERO_HASH,
            "claim_ids": [],
            "event_ids": [],
            "provenance_bundle_id": "provenance.missing",
        }
    )
    lens_without_branch = _finish(
        {
            "schema_version": "stewie.query_lens/1.0",
            "lens_id": "lens.missing-branch",
            "query_request_id": "request.missing",
            "world_id": "world.lunar",
            "site_id": "site.haworth",
            "branch_id": "branch.missing",
            "policy_id": "policy.plan",
            "region_id": "region.test",
            "requested_state_kinds": ["planned"],
            "valid_at": {
                "instant": 10.5,
                "clock_id": "clock.mission",
                "uncertainty_s": 0.01,
            },
            "known_at": {"sequence": 2, "recorded_at": RECORDED_AT},
            "representation": "raster_2_5d",
            "resolution": [5.0, 5.0],
            "frame_id": "frame.site.haworth",
            "units": {"axis": "m", "value": "m"},
            "requesting_agent_id": "planner.1",
            "status": "resolved",
            "reason_codes": [],
            "available_claim_ids": [],
            "resolved_revision_id": revision_without_branch["revision_id"],
            "resolved_state_kind": "planned",
            "projection_transaction_sequence": 2,
            "result_coverage_hash": ZERO_HASH,
            "result_payload_hash": ZERO_HASH,
        }
    )
    return [
        {
            "id": "reject-cross-site-observation-reference",
            "expect_valid": False,
            "records": [
                ("evidence_claim.schema.json", claim),
                ("state_candidate.schema.json", candidate),
            ],
        },
        {
            "id": "reject-missing-query-branch-without-crash",
            "expect_valid": False,
            "records": [
                ("world_revision.schema.json", revision_without_branch),
                ("query_lens.schema.json", lens_without_branch),
            ],
        },
    ]
