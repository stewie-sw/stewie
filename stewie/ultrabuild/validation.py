"""Validate UltraBuild JSON contracts beyond JSON Schema's cross-field limits.

JSON Schema checks shape and local conditionals. This module adds interval ordering,
canonical content hashes, branch/authority compatibility, reference-firewall isolation,
and cross-record identity/type checks. It is a specification validator for Barrier 2;
it is not yet the authoritative event store required by Barrier 3.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sysconfig
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from stewie.ultrabuild.canonical import (
    sha256_json,
    state_contract_hash,
    submitted_record_hash,
)


SOURCE_ROOT = Path(__file__).resolve().parents[2]
SOURCE_SCHEMA_ROOT = SOURCE_ROOT / "schemas" / "ultrabuild"
INSTALLED_SCHEMA_ROOT = Path(sysconfig.get_path("data")) / "share" / "stewie" / "schemas" / "ultrabuild"
TARGET_INSTALL_SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "share" / "stewie" / "schemas" / "ultrabuild"
SCHEMA_ROOT = (
    SOURCE_SCHEMA_ROOT
    if SOURCE_SCHEMA_ROOT.is_dir()
    else (TARGET_INSTALL_SCHEMA_ROOT if TARGET_INSTALL_SCHEMA_ROOT.is_dir() else INSTALLED_SCHEMA_ROOT)
)
FORMAT_CHECKER = FormatChecker()


def canonical_content_hash(record: Mapping[str, Any]) -> str:
    """Hash the canonical complete record, excluding only its self-referential hash."""

    canonical = deepcopy(dict(record))
    canonical.pop("content_hash", None)
    payload = json.dumps(
        canonical,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def canonical_scenario_id(record: Mapping[str, Any]) -> str:
    """Hash canonical scenario content, excluding only the self-referential ID."""

    canonical = deepcopy(dict(record))
    canonical.pop("scenario_id", None)
    payload = json.dumps(
        canonical,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_schema(schema_name: str) -> dict[str, Any]:
    path = SCHEMA_ROOT / schema_name
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{schema_name}: schema root must be an object")
    return value


def schema_errors(schema_name: str, record: Mapping[str, Any]) -> list[str]:
    schema = load_schema(schema_name)
    validator = Draft202012Validator(schema, format_checker=FORMAT_CHECKER)
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(record), key=lambda item: list(item.absolute_path))
    ]


def _walk(value: Any, path: tuple[str | int, ...] = ()) -> Iterable[tuple[tuple[str | int, ...], Any]]:
    yield path, value
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield from _walk(child, (*path, str(key)))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            yield from _walk(child, (*path, index))


def _path_text(path: tuple[str | int, ...]) -> str:
    return ".".join(str(part) for part in path) or "<root>"


def semantic_errors(schema_name: str, record: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []

    for path, value in _walk(record):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if isinstance(value, int) and not -(2**63) <= value <= 2**63 - 1:
                errors.append(
                    f"{_path_text(path)}: integer must fit the signed 64-bit "
                    "authority-storage profile"
                )
            elif isinstance(value, float) and not math.isfinite(value):
                errors.append(
                    f"{_path_text(path)}: numeric value must be finite"
                )
        if path and path[-1] in {"valid_time", "planned_valid_time", "executed_valid_time"}:
            if isinstance(value, Mapping) and value.get("end") is not None:
                start = value.get("start")
                end = value.get("end")
                if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end < start:
                    errors.append(f"{_path_text(path)}: interval end precedes start")

    expected_hash = record.get("content_hash")
    if isinstance(expected_hash, str) and expected_hash != canonical_content_hash(record):
        errors.append("content_hash: does not commit the canonical complete record")

    transaction = record.get("transaction_time")
    recorded_at = record.get("recorded_at")
    if isinstance(transaction, Mapping) and isinstance(recorded_at, str):
        if transaction.get("recorded_at") != recorded_at:
            errors.append("recorded_at: must equal transaction_time.recorded_at")

    if schema_name == "dependency_edge.schema.json":
        if record.get("left_claim_id") == record.get("right_claim_id"):
            errors.append("left_claim_id/right_claim_id: self-dependency is forbidden")

    if schema_name == "evidence_claim.schema.json":
        source_kind = record.get("source_kind")
        branch_kind = record.get("branch_kind")
        required_branch = {
            "observation": "evidence",
            "physics_prediction": "prediction",
            "plan": "plan",
            "simulation_result": "simulation",
            "human_assertion": "plan",
        }.get(source_kind if isinstance(source_kind, str) else "")
        if record.get("evaluation_visibility") != "withheld_reference" and branch_kind != required_branch:
            errors.append(f"branch_kind: {source_kind} claims require the {required_branch} branch kind")
        spatial = record.get("spatial", {})
        if isinstance(spatial, Mapping):
            shape = spatial.get("shape", [])
            resolution = spatial.get("resolution", [])
            bounds = spatial.get("bounds", [])
            axes = spatial.get("axis_order", [])
            if len(shape) != len(resolution):
                errors.append("spatial: shape and resolution dimensions differ")
            if len(bounds) != 2 * len(shape):
                errors.append("spatial: bounds must contain a lower/upper pair per grid dimension")
            if len(axes) not in {len(shape), len(shape) + 1} or len(axes) != len(set(axes)):
                errors.append("spatial.axis_order: axes must be unique and match dimensions/value axis")

    if schema_name == "provenance_bundle.schema.json":
        local_ids: set[str] = set()
        id_kinds: dict[str, str] = {}
        for collection in ("agents", "activities", "entities", "transforms", "calibrations"):
            values = record.get(collection, [])
            ids = [
                next((value for key, value in item.items() if key.endswith("_id")), None)
                for item in values
                if isinstance(item, Mapping)
            ]
            if len(ids) != len(set(ids)):
                errors.append(f"{collection}: identifiers must be unique within the bundle")
            for value in ids:
                if not isinstance(value, str):
                    continue
                if value in local_ids:
                    errors.append(f"{collection}: identifier {value} is reused across bundle node classes")
                local_ids.add(value)
                id_kinds[value] = collection
        for index, activity in enumerate(record.get("activities", [])):
            if not isinstance(activity, Mapping):
                continue
            start = activity.get("started_at")
            end = activity.get("ended_at")
            if isinstance(start, str) and isinstance(end, str):
                try:
                    if datetime.fromisoformat(end.replace("Z", "+00:00")) < datetime.fromisoformat(
                        start.replace("Z", "+00:00")
                    ):
                        errors.append(f"activities.{index}: ended_at precedes started_at")
                except ValueError:
                    pass
            if activity.get("agent_id") not in local_ids:
                errors.append(f"activities.{index}.agent_id: unresolved within provenance bundle")
        for index, relation in enumerate(record.get("relations", [])):
            if not isinstance(relation, Mapping):
                continue
            for field in ("subject_id", "object_id"):
                if relation.get(field) not in local_ids:
                    errors.append(f"relations.{index}.{field}: unresolved within provenance bundle")
            relation_kind = relation.get("kind")
            subject_kind = id_kinds.get(str(relation.get("subject_id")))
            object_kind = id_kinds.get(str(relation.get("object_id")))
            permitted_endpoint_kinds = {
                "wasGeneratedBy": ("entities", "activities"),
                "wasAttributedTo": ("entities", "agents"),
                "used": ("activities", "entities"),
                "wasDerivedFrom": ("entities", "entities"),
                "supersedes": ("entities", "entities"),
                "invalidates": ("entities", "entities"),
            }
            expected = permitted_endpoint_kinds.get(str(relation_kind))
            if expected is not None and (subject_kind, object_kind) != expected:
                errors.append(f"relations.{index}: {relation_kind} requires {expected[0]} -> {expected[1]}")
        subject = record.get("subject", {})
        if isinstance(subject, Mapping):
            entity_by_id = {
                entity.get("entity_id"): entity for entity in record.get("entities", []) if isinstance(entity, Mapping)
            }
            activity_by_id = {
                activity.get("activity_id"): activity
                for activity in record.get("activities", [])
                if isinstance(activity, Mapping)
            }
            agent_ids = {agent.get("agent_id") for agent in record.get("agents", []) if isinstance(agent, Mapping)}
            record_entity = entity_by_id.get(subject.get("record_entity_id"))
            if not isinstance(record_entity, Mapping):
                errors.append("subject.record_entity_id: matching entity is absent")
            elif record_entity.get("content_hash") != subject.get("submitted_record_hash"):
                errors.append("subject.record_entity_id: entity hash differs from submitted record hash")
            payload_entity_id = subject.get("payload_entity_id")
            if isinstance(payload_entity_id, str):
                payload_entity = entity_by_id.get(payload_entity_id)
                if (
                    not isinstance(payload_entity, Mapping)
                    or payload_entity.get("kind") != "payload"
                    or payload_entity.get("content_hash") != subject.get("payload_hash")
                ):
                    errors.append("subject.payload_entity_id: payload entity/hash is absent or mismatched")
            coverage_entity_id = subject.get("coverage_entity_id")
            if isinstance(coverage_entity_id, str):
                coverage_entity = entity_by_id.get(coverage_entity_id)
                if (
                    not isinstance(coverage_entity, Mapping)
                    or coverage_entity.get("kind") != "payload"
                    or coverage_entity.get("content_hash") != subject.get("coverage_hash")
                ):
                    errors.append("subject.coverage_entity_id: coverage entity/hash is absent or mismatched")
            activity_id = subject.get("generating_activity_id")
            agent_id = subject.get("responsible_agent_id")
            activity = activity_by_id.get(activity_id)
            if not isinstance(activity, Mapping):
                errors.append("subject.generating_activity_id: activity is absent")
            elif activity.get("agent_id") != agent_id:
                errors.append("subject.generating_activity_id: activity uses another responsible agent")
            if agent_id not in agent_ids:
                errors.append("subject.responsible_agent_id: agent is absent")
            relation_triples = {
                (
                    relation.get("kind"),
                    relation.get("subject_id"),
                    relation.get("object_id"),
                )
                for relation in record.get("relations", [])
                if isinstance(relation, Mapping)
            }
            required_relations = {
                ("wasGeneratedBy", subject.get("record_entity_id"), activity_id),
                ("wasAttributedTo", subject.get("record_entity_id"), agent_id),
            }
            if isinstance(payload_entity_id, str):
                required_relations.add(("used", activity_id, payload_entity_id))
            missing_relations = required_relations - relation_triples
            if missing_relations:
                errors.append(f"relations: missing subject closure edges {sorted(missing_relations)}")
            transform_ids = {
                transform.get("transform_id")
                for transform in record.get("transforms", [])
                if isinstance(transform, Mapping)
            }
            if not set(subject.get("transform_ids", [])).issubset(transform_ids):
                errors.append("subject.transform_ids: transform nodes are missing")
            calibration_ids = {
                calibration.get("calibration_id")
                for calibration in record.get("calibrations", [])
                if isinstance(calibration, Mapping)
            }
            if not set(subject.get("calibration_ids", [])).issubset(calibration_ids):
                errors.append("subject.calibration_ids: calibration nodes are missing")

    if schema_name == "world_revision.schema.json":
        parents = record.get("parent_revision_ids", [])
        if record.get("revision_id") in parents:
            errors.append("parent_revision_ids: a revision cannot parent itself")
        state_kind = record.get("state_kind")
        authority = record.get("authority_scope", {})
        if isinstance(authority, Mapping):
            branch_kind = authority.get("branch_kind")
            if state_kind in {"reconciled", "verified", "authoritative"} and branch_kind not in {
                "belief",
                "accepted",
            }:
                errors.append("authority_scope.branch_kind: accepted state requires belief/accepted branch")
            if state_kind == "simulated" and (
                branch_kind != "simulation" or authority.get("environment_mode") == "live"
            ):
                errors.append("state_kind: simulated state cannot target a live/non-simulation branch")
        prior_head = record.get("prior_head_revision_id")
        if prior_head is not None and prior_head not in parents:
            errors.append("prior_head_revision_id: must be one of parent_revision_ids")

    if schema_name in {"state_candidate.schema.json", "reconciliation_decision.schema.json"}:
        admitted = record.get("admitted_observation_ids", [])
        excluded = [item.get("claim_id") for item in record.get("excluded_evidence", []) if isinstance(item, Mapping)]
        if len(excluded) != len(set(excluded)):
            errors.append("excluded_evidence: a claim may be excluded only once")
        overlap = sorted(set(admitted) & set(excluded))
        if overlap:
            errors.append(f"evidence partition: claims both admitted and excluded: {overlap}")

    if schema_name in {"state_candidate.schema.json", "world_revision.schema.json"}:
        if record.get("state_contract_hash") != state_contract_hash(record):
            errors.append("state_contract_hash: does not bind spatial, valid-time, uncertainty, payload, and coverage")
        uncertainty = record.get("uncertainty", {})
        if isinstance(uncertainty, Mapping):
            components = uncertainty.get("components", [])
            kinds = [item.get("kind") for item in components if isinstance(item, Mapping)]
            required_kinds = {
                "sensor",
                "localization",
                "geometric",
                "material",
                "temporal",
                "change_attribution",
                "model",
                "inter_robot",
            }
            if len(kinds) != len(set(kinds)) or set(kinds) != required_kinds:
                errors.append("uncertainty.components: every uncertainty class must appear exactly once")

    if schema_name == "barrier_decision.schema.json":
        findings = [finding for finding in record.get("findings", []) if isinstance(finding, Mapping)]
        derived_open_critical = {
            finding.get("finding_id")
            for finding in findings
            if finding.get("severity") == "critical" and finding.get("disposition") == "open"
        }
        declared_open_critical = set(record.get("open_critical_defect_ids", []))
        if declared_open_critical != derived_open_critical:
            errors.append("open_critical_defect_ids: differs from open critical findings")
        top_evidence = {
            item.get("artifact_id") for item in record.get("evidence_artifacts", []) if isinstance(item, Mapping)
        }
        for finding in findings:
            missing = set(finding.get("evidence_artifact_ids", [])) - top_evidence
            if missing:
                errors.append(f"findings.{finding.get('finding_id')}: evidence absent from hashed evidence_artifacts")
        if record.get("decision") == "ACCEPT" and derived_open_critical:
            errors.append("decision: ACCEPT is forbidden with open critical findings")

    if schema_name == "scenario.schema.json":
        if record.get("scenario_id") != canonical_scenario_id(record):
            errors.append("scenario_id: does not hash the canonical complete scenario")
        firewall = record.get("reference_firewall", {})
        if isinstance(firewall, Mapping):
            if firewall.get("candidate_process") == firewall.get("evaluator_process"):
                errors.append("reference_firewall: candidate and evaluator processes must be distinct")
            if firewall.get("candidate_identity") == firewall.get("evaluator_identity"):
                errors.append("reference_firewall: candidate and evaluator identities must be distinct")
        candidate = record.get("candidate_visible_actions", {})
        reference = record.get("withheld_execution_truth", {})
        if isinstance(candidate, Mapping) and isinstance(reference, Mapping):
            if candidate.get("mount") == reference.get("evaluator_mount"):
                errors.append("reference_firewall: candidate and reference mounts must be distinct")
        evidence_sequence = record.get("evidence_sequence", [])
        evidence_claims = [item.get("claim_id") for item in evidence_sequence if isinstance(item, Mapping)]
        evidence_orders = [item.get("sequence") for item in evidence_sequence if isinstance(item, Mapping)]
        if len(evidence_claims) != len(set(evidence_claims)):
            errors.append("evidence_sequence: claim IDs must be unique")
        if len(evidence_orders) != len(set(evidence_orders)):
            errors.append("evidence_sequence: sequence values must be unique")
        units = record.get("experimental_units", {})
        sample_plan = record.get("sample_size_plan", {})
        stopping = record.get("stopping_rule", {})
        seeds = record.get("seeds", [])
        if isinstance(units, Mapping) and isinstance(sample_plan, Mapping):
            unit_ids = units.get("unit_ids", [])
            independent_units = sample_plan.get("independent_units")
            seeds_per_unit = sample_plan.get("seeds_per_unit")
            if independent_units != len(unit_ids):
                errors.append("sample_size_plan.independent_units: differs from experimental unit count")
            if seeds_per_unit != len(seeds):
                errors.append("sample_size_plan.seeds_per_unit: differs from seed count")
            if (
                isinstance(independent_units, int)
                and isinstance(seeds_per_unit, int)
                and isinstance(stopping, Mapping)
                and stopping.get("planned_trial_count") != independent_units * seeds_per_unit
            ):
                errors.append("stopping_rule.planned_trial_count: differs from units multiplied by seeds")

    return errors


def validate_record(schema_name: str, record: Mapping[str, Any]) -> list[str]:
    return schema_errors(schema_name, record) + semantic_errors(schema_name, record)


PRIMARY_KEY_BY_SCHEMA = {
    "action_event.schema.json": "event_id",
    "barrier_decision.schema.json": "decision_id",
    "branch.schema.json": "branch_id",
    "conflict_record.schema.json": "conflict_id",
    "dependency_edge.schema.json": "edge_id",
    "decision_record.schema.json": "decision_record_id",
    "evidence_claim.schema.json": "claim_id",
    "hypothesis_set.schema.json": "hypothesis_set_id",
    "provenance_bundle.schema.json": "bundle_id",
    "query_lens.schema.json": "lens_id",
    "query_request.schema.json": "request_id",
    "reconciliation_decision.schema.json": "decision_id",
    "state_candidate.schema.json": "candidate_id",
    "supersession_event.schema.json": "event_id",
    "world_revision.schema.json": "revision_id",
}


def _record_id(schema_name: str, record: Mapping[str, Any]) -> str | None:
    key = PRIMARY_KEY_BY_SCHEMA.get(schema_name)
    if key is None:
        return None
    value = record.get(key)
    return value if isinstance(value, str) else None


def cross_record_errors(records: Sequence[tuple[str, Mapping[str, Any]]]) -> list[str]:
    """Validate references that must preserve world/site and authority semantics."""

    errors: list[str] = []
    by_id: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for schema_name, record in records:
        record_id = _record_id(schema_name, record)
        if record_id is None:
            continue
        if record_id in by_id:
            errors.append(f"{record_id}: duplicate record identity")
        by_id[record_id] = (schema_name, record)

    sequence_owners: dict[int, str] = {}
    ordered_transactions: list[tuple[int, str, str]] = []
    for schema_name, record in records:
        transaction = record.get("transaction_time")
        if not isinstance(transaction, Mapping):
            continue
        sequence = transaction.get("sequence")
        recorded_at = transaction.get("recorded_at")
        identity = _record_id(schema_name, record) or schema_name
        if isinstance(sequence, int):
            if sequence in sequence_owners:
                errors.append(
                    f"transaction_time.sequence: {sequence} reused by {sequence_owners[sequence]} and {identity}"
                )
            sequence_owners[sequence] = identity
            if isinstance(recorded_at, str):
                ordered_transactions.append((sequence, recorded_at, identity))
    prior_time: datetime | None = None
    for _sequence, recorded_at, identity in sorted(ordered_transactions):
        try:
            instant = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if prior_time is not None and instant < prior_time:
            errors.append(f"transaction_time.recorded_at: decreases at {identity}")
        prior_time = instant

    def resolve(
        owner: Mapping[str, Any],
        reference_id: str,
        expected_schemas: set[str],
        field: str,
    ) -> Mapping[str, Any] | None:
        target = by_id.get(reference_id)
        if target is None:
            errors.append(f"{field}: unresolved reference {reference_id}")
            return None
        schema_name, target_record = target
        if schema_name not in expected_schemas:
            errors.append(f"{field}: {reference_id} has wrong record type {schema_name}")
        for identity_field in ("world_id", "site_id"):
            if owner.get(identity_field) != target_record.get(identity_field):
                errors.append(f"{field}: {reference_id} crosses {identity_field}")
        return target_record

    def transaction_sequence(record: Mapping[str, Any]) -> int | None:
        transaction = record.get("transaction_time")
        if not isinstance(transaction, Mapping):
            return None
        sequence = transaction.get("sequence")
        return sequence if isinstance(sequence, int) else None

    def require_earlier(
        earlier: Mapping[str, Any],
        later: Mapping[str, Any],
        field: str,
    ) -> None:
        earlier_sequence = transaction_sequence(earlier)
        later_sequence = transaction_sequence(later)
        if earlier_sequence is not None and later_sequence is not None and earlier_sequence >= later_sequence:
            errors.append(f"{field}: referenced record is not transactionally earlier")

    def valid_at(record: Mapping[str, Any], instant: float, clock_id: str) -> bool:
        interval = record.get("valid_time")
        if not isinstance(interval, Mapping) or interval.get("clock_id") != clock_id:
            return False
        start = interval.get("start")
        end = interval.get("end")
        return (
            isinstance(start, (int, float))
            and start <= instant
            and (end is None or (isinstance(end, (int, float)) and instant < end))
        )

    immutable_record_schemas = set(PRIMARY_KEY_BY_SCHEMA)

    for schema_name, record in records:
        provenance_bundle_id = record.get("provenance_bundle_id")
        if isinstance(provenance_bundle_id, str):
            bundle = resolve(
                record,
                provenance_bundle_id,
                {"provenance_bundle.schema.json"},
                "provenance_bundle_id",
            )
            if bundle is not None:
                require_earlier(bundle, record, "provenance_bundle_id")
                subject = bundle.get("subject", {})
                if isinstance(subject, Mapping):
                    owner_id = _record_id(schema_name, record)
                    if subject.get("record_id") != owner_id:
                        errors.append("provenance_bundle_id: bundle subject names another record")
                    if subject.get("record_schema") != schema_name:
                        errors.append("provenance_bundle_id: bundle subject names another schema")
                    if subject.get("submitted_record_hash") != submitted_record_hash(record):
                        errors.append("provenance_bundle_id: submitted record hash does not close")
                    payload = record.get("payload", {})
                    payload_hash = (
                        payload.get("content_hash") if isinstance(payload, Mapping) else record.get("payload_hash")
                    )
                    coverage_hash = (
                        payload.get("coverage_hash") if isinstance(payload, Mapping) else record.get("coverage_hash")
                    )
                    if payload_hash is not None and subject.get("payload_hash") != payload_hash:
                        errors.append("provenance_bundle_id: payload hash does not close")
                    if coverage_hash is not None and subject.get("coverage_hash") != coverage_hash:
                        errors.append("provenance_bundle_id: coverage hash does not close")
                    if schema_name == "evidence_claim.schema.json":
                        source = record.get("source", {})
                        if isinstance(source, Mapping):
                            if subject.get("responsible_agent_id") != source.get("agent_id"):
                                errors.append("provenance_bundle_id: source agent does not close")
                            activity = next(
                                (
                                    item
                                    for item in bundle.get("activities", [])
                                    if isinstance(item, Mapping)
                                    and item.get("activity_id") == subject.get("generating_activity_id")
                                ),
                                None,
                            )
                            if (
                                not isinstance(activity, Mapping)
                                or activity.get("algorithm_version") != source.get("algorithm_version")
                                or activity.get("pipeline_id") != source.get("pipeline_id")
                                or activity.get("kind") != "observe"
                            ):
                                errors.append(
                                    "provenance_bundle_id: processing activity/version does not close "
                                    "(pipeline identity included)"
                                )
                            required_transforms = {record.get("spatial", {}).get("transform_chain_id")}
                            if not required_transforms.issubset(set(subject.get("transform_ids", []))):
                                errors.append("provenance_bundle_id: transform chain does not close")
                            transform_by_id = {
                                item.get("transform_id"): item
                                for item in bundle.get("transforms", [])
                                if isinstance(item, Mapping)
                            }
                            spatial = record.get("spatial", {})
                            transform_id = spatial.get("transform_chain_id") if isinstance(spatial, Mapping) else None
                            transform = transform_by_id.get(transform_id)
                            if not isinstance(transform, Mapping) or transform.get("target_frame") != (
                                spatial.get("frame_id") if isinstance(spatial, Mapping) else None
                            ):
                                errors.append("provenance_bundle_id: transform target frame does not close")
                            required_calibrations = {
                                value.get("id")
                                for value in (
                                    source.get("calibration_id"),
                                    *[
                                        component.get("calibration_id")
                                        for component in record.get("uncertainty", {}).get("components", [])
                                        if isinstance(component, Mapping)
                                    ],
                                )
                                if isinstance(value, Mapping) and value.get("status") == "known"
                            }
                            if not required_calibrations.issubset(set(subject.get("calibration_ids", []))):
                                errors.append("provenance_bundle_id: calibration chain does not close")
                            source_instrument = source.get("instrument_id")
                            known_instrument = (
                                source_instrument.get("id")
                                if isinstance(source_instrument, Mapping) and source_instrument.get("status") == "known"
                                else None
                            )
                            calibration_by_id = {
                                item.get("calibration_id"): item
                                for item in bundle.get("calibrations", [])
                                if isinstance(item, Mapping)
                            }
                            if known_instrument is not None and any(
                                not isinstance(
                                    calibration_by_id.get(calibration_id),
                                    Mapping,
                                )
                                or calibration_by_id[calibration_id].get("instrument_id") != known_instrument
                                for calibration_id in required_calibrations
                            ):
                                errors.append("provenance_bundle_id: calibration instrument does not close")
                            agents = {
                                item.get("agent_id"): item
                                for item in bundle.get("agents", [])
                                if isinstance(item, Mapping)
                            }
                            responsible_agent = agents.get(source.get("agent_id"))

                            def qualified_matches(
                                source_value: Any,
                                provenance_value: Any,
                            ) -> bool:
                                if not isinstance(source_value, Mapping) or not isinstance(provenance_value, Mapping):
                                    return False
                                if source_value.get("status") != provenance_value.get("status"):
                                    return False
                                if source_value.get("status") == "known":
                                    return source_value.get("id") == provenance_value.get("value")
                                return source_value.get("reason_code") == provenance_value.get("reason_code")

                            if not isinstance(responsible_agent, Mapping) or any(
                                not qualified_matches(
                                    source.get(source_field),
                                    responsible_agent.get(agent_field),
                                )
                                for source_field, agent_field in (
                                    ("attestation_key_id", "attestation_key_id"),
                                    ("hardware_version", "hardware_version"),
                                    ("firmware_version", "firmware_version"),
                                )
                            ):
                                errors.append(
                                    "provenance_bundle_id: source hardware/firmware/attestation does not close"
                                )
        if schema_name == "provenance_bundle.schema.json":
            subject = record.get("subject", {})
            if isinstance(subject, Mapping):
                subject_record_id = subject.get("record_id")
                subject_schema = subject.get("record_schema")
                if isinstance(subject_record_id, str) and isinstance(
                    subject_schema,
                    str,
                ):
                    target = resolve(
                        record,
                        subject_record_id,
                        {subject_schema},
                        "subject.record_id",
                    )
                    if target is not None:
                        if target.get("provenance_bundle_id") != record.get("bundle_id"):
                            errors.append("subject.record_id: subject does not link back to bundle")
                        require_earlier(record, target, "subject.record_id")
        if schema_name == "branch.schema.json":
            parent_branch = None
            parent_branch_id = record.get("parent_branch_id")
            if isinstance(parent_branch_id, str):
                parent_branch = resolve(
                    record,
                    parent_branch_id,
                    {"branch.schema.json"},
                    "parent_branch_id",
                )
            base_revision_id = record.get("base_revision_id")
            if isinstance(base_revision_id, str):
                base_revision = resolve(
                    record,
                    base_revision_id,
                    {"world_revision.schema.json"},
                    "base_revision_id",
                )
                if base_revision is not None:
                    permitted_base_branches = {record.get("branch_id")}
                    if parent_branch is not None:
                        permitted_base_branches.add(parent_branch.get("branch_id"))
                    if base_revision.get("branch_id") not in permitted_base_branches:
                        errors.append("base_revision_id: is neither on this branch nor its parent")
            head_revision_id = record.get("head_revision_id")
            if isinstance(head_revision_id, str):
                head_revision = resolve(
                    record,
                    head_revision_id,
                    {"world_revision.schema.json"},
                    "head_revision_id",
                )
                if head_revision is not None:
                    if head_revision.get("branch_id") != record.get("branch_id"):
                        errors.append("head_revision_id: revision is on another branch")
                    if head_revision.get("branch_revision_sequence") != record.get("head_sequence"):
                        errors.append("head_sequence: differs from head revision sequence")
        elif schema_name == "state_candidate.schema.json":
            branch = None
            branch_id = record.get("branch_id")
            if isinstance(branch_id, str):
                branch = resolve(record, branch_id, {"branch.schema.json"}, "branch_id")
            prior = None
            prior_revision_id = record.get("prior_revision_id")
            if isinstance(prior_revision_id, str):
                prior = resolve(
                    record,
                    prior_revision_id,
                    {"world_revision.schema.json"},
                    "prior_revision_id",
                )
                if prior is not None:
                    if prior.get("branch_id") != record.get("branch_id"):
                        errors.append("prior_revision_id: belongs to another branch")
                    require_earlier(prior, record, "prior_revision_id")
            if branch is not None:
                policy = record.get("policy")
                if isinstance(policy, Mapping) and policy.get("policy_id") != branch.get("policy_id"):
                    errors.append("policy.policy_id: differs from target branch policy")
            for claim_id in record.get("admitted_observation_ids", []):
                claim = resolve(record, claim_id, {"evidence_claim.schema.json"}, "admitted_observation_ids")
                if claim is not None and (
                    claim.get("source_kind") != "observation" or claim.get("state_kind") != "observed"
                ):
                    errors.append(f"admitted_observation_ids: {claim_id} is not an observation")
                if claim is not None:
                    require_earlier(claim, record, "admitted_observation_ids")
                    candidate_valid = record.get("valid_time", {})
                    claim_valid = claim.get("valid_time", {})
                    if isinstance(candidate_valid, Mapping) and isinstance(claim_valid, Mapping):
                        candidate_start = candidate_valid.get("start")
                        candidate_end = candidate_valid.get("end")
                        claim_start = claim_valid.get("start")
                        claim_end = claim_valid.get("end")
                        if candidate_valid.get("clock_id") != claim_valid.get("clock_id"):
                            errors.append(f"admitted_observation_ids: {claim_id} uses another valid-time clock")
                        if (
                            isinstance(candidate_start, (int, float))
                            and isinstance(claim_start, (int, float))
                            and candidate_start < claim_start
                        ):
                            errors.append(f"valid_time: candidate begins before admitted claim {claim_id}")
                        if claim_end is not None and (
                            candidate_end is None
                            or (
                                isinstance(candidate_end, (int, float))
                                and isinstance(claim_end, (int, float))
                                and candidate_end > claim_end
                            )
                        ):
                            errors.append(f"valid_time: candidate extends beyond admitted claim {claim_id}")
                    candidate_spatial = record.get("spatial", {})
                    claim_spatial = claim.get("spatial", {})
                    if isinstance(candidate_spatial, Mapping) and isinstance(claim_spatial, Mapping):
                        exact_pairs = {
                            "representation": "representation",
                            "crs": "crs",
                            "frame_id": "frame_id",
                            "transform_chain_id": "transform_chain_id",
                            "axis_order": "axis_order",
                            "bounds": "bounds",
                            "shape": "shape",
                            "resolution": "resolution",
                        }
                        for candidate_field, claim_field in exact_pairs.items():
                            if candidate_spatial.get(candidate_field) != claim_spatial.get(claim_field):
                                errors.append(f"spatial.{candidate_field}: differs from admitted claim {claim_id}")
                        units = candidate_spatial.get("units", {})
                        if not isinstance(units, Mapping) or units.get("value") != claim_spatial.get("value_unit"):
                            errors.append(f"spatial.units.value: differs from admitted claim {claim_id}")
            for excluded in record.get("excluded_evidence", []):
                if isinstance(excluded, Mapping) and isinstance(excluded.get("claim_id"), str):
                    excluded_claim = resolve(
                        record,
                        excluded["claim_id"],
                        {"evidence_claim.schema.json"},
                        "excluded_evidence.claim_id",
                    )
                    if excluded_claim is not None:
                        require_earlier(excluded_claim, record, "excluded_evidence.claim_id")
            admitted_and_excluded = set(record.get("admitted_observation_ids", [])) | {
                item.get("claim_id") for item in record.get("excluded_evidence", []) if isinstance(item, Mapping)
            }
            for edge_id in record.get("dependency_edge_ids", []):
                edge = resolve(
                    record,
                    edge_id,
                    {"dependency_edge.schema.json"},
                    "dependency_edge_ids",
                )
                if edge is not None and not {
                    edge.get("left_claim_id"),
                    edge.get("right_claim_id"),
                }.issubset(admitted_and_excluded):
                    errors.append(f"dependency_edge_ids: {edge_id} refers outside the evidence partition")
                if edge is not None and edge.get("evaluation_visibility") != "system_visible":
                    errors.append(f"dependency_edge_ids: {edge_id} is evaluator-only evidence")
                if edge is not None:
                    require_earlier(edge, record, "dependency_edge_ids")
            for claim_id in record.get("physics_comparison_ids", []):
                claim = resolve(
                    record,
                    claim_id,
                    {"evidence_claim.schema.json"},
                    "physics_comparison_ids",
                )
                if claim is not None and claim.get("source_kind") != "physics_prediction":
                    errors.append(f"physics_comparison_ids: {claim_id} is not physics evidence")
                if claim is not None:
                    require_earlier(claim, record, "physics_comparison_ids")
        elif schema_name == "reconciliation_decision.schema.json":
            for claim_id in record.get("admitted_observation_ids", []):
                claim = resolve(record, claim_id, {"evidence_claim.schema.json"}, "admitted_observation_ids")
                if claim is not None and claim.get("source_kind") != "observation":
                    errors.append(f"admitted_observation_ids: {claim_id} is not observation evidence")
                if claim is not None:
                    require_earlier(claim, record, "admitted_observation_ids")
            for claim_id in record.get("physics_evidence_ids", []):
                claim = resolve(record, claim_id, {"evidence_claim.schema.json"}, "physics_evidence_ids")
                if claim is not None and claim.get("source_kind") != "physics_prediction":
                    errors.append(f"physics_evidence_ids: {claim_id} is not physics evidence")
                if claim is not None:
                    require_earlier(claim, record, "physics_evidence_ids")
            for edge_id in record.get("dependency_edge_ids", []):
                edge = resolve(
                    record,
                    edge_id,
                    {"dependency_edge.schema.json"},
                    "dependency_edge_ids",
                )
                if edge is not None:
                    require_earlier(edge, record, "dependency_edge_ids")
            for excluded in record.get("excluded_evidence", []):
                if isinstance(excluded, Mapping) and isinstance(excluded.get("claim_id"), str):
                    excluded_claim = resolve(
                        record,
                        excluded["claim_id"],
                        {"evidence_claim.schema.json"},
                        "excluded_evidence.claim_id",
                    )
                    if excluded_claim is not None:
                        require_earlier(excluded_claim, record, "excluded_evidence.claim_id")
            candidate_summary = record.get("candidate")
            if isinstance(candidate_summary, Mapping):
                candidate_id = candidate_summary.get("candidate_id")
                if isinstance(candidate_id, str):
                    candidate = resolve(
                        record,
                        candidate_id,
                        {"state_candidate.schema.json"},
                        "candidate.candidate_id",
                    )
                    if candidate is not None:
                        if set(candidate.get("admitted_observation_ids", [])) != set(
                            record.get("admitted_observation_ids", [])
                        ):
                            errors.append("candidate: admitted observations differ from durable candidate")
                        if candidate.get("prior_revision_id") != record.get("prior_revision_id"):
                            errors.append("candidate: prior revision differs from decision")
                        if candidate.get("policy") != record.get("policy"):
                            errors.append("candidate: policy/config differs from decision")
                        if candidate.get("valid_time") != record.get("valid_time"):
                            errors.append("candidate: valid-time contract differs from decision")
                        if candidate.get("excluded_evidence") != record.get("excluded_evidence"):
                            errors.append("candidate: evidence exclusions differ from decision")
                        if set(candidate.get("dependency_edge_ids", [])) != set(record.get("dependency_edge_ids", [])):
                            errors.append("candidate: dependency edges differ from decision")
                        if set(candidate.get("physics_comparison_ids", [])) != set(
                            record.get("physics_evidence_ids", [])
                        ):
                            errors.append("candidate: physics comparisons differ from decision")
                        payload = candidate.get("payload", {})
                        if isinstance(payload, Mapping) and (
                            candidate_summary.get("candidate_record_hash") != candidate.get("content_hash")
                            or candidate_summary.get("payload_hash") != payload.get("content_hash")
                            or candidate_summary.get("coverage_hash") != payload.get("coverage_hash")
                            or candidate_summary.get("state_contract_hash") != candidate.get("state_contract_hash")
                            or candidate_summary.get("construction") != candidate.get("construction")
                        ):
                            errors.append("candidate: bound summary differs from durable candidate")
                        require_earlier(candidate, record, "candidate.candidate_id")
            if record.get("decision") == "PROMOTE":
                review = record.get("review", {})
                if not isinstance(review, Mapping) or review.get("status") not in {
                    "approved",
                    "not_required",
                }:
                    errors.append("review.status: pending/rejected review cannot promote")
            prior_revision_id = record.get("prior_revision_id")
            if isinstance(prior_revision_id, str):
                prior = resolve(
                    record,
                    prior_revision_id,
                    {"world_revision.schema.json"},
                    "prior_revision_id",
                )
                if prior is not None:
                    if prior.get("branch_id") != record.get("branch_id"):
                        errors.append("prior_revision_id: belongs to another branch")
                    require_earlier(prior, record, "prior_revision_id")
            decision_branch_id = record.get("branch_id")
            if isinstance(decision_branch_id, str):
                decision_branch = resolve(
                    record,
                    decision_branch_id,
                    {"branch.schema.json"},
                    "branch_id",
                )
                if decision_branch is not None:
                    policy = record.get("policy", {})
                    if isinstance(policy, Mapping) and policy.get("policy_id") != decision_branch.get("policy_id"):
                        errors.append("policy.policy_id: differs from target branch policy")
            hypothesis_set_id = record.get("hypothesis_set_id")
            if isinstance(hypothesis_set_id, str):
                hypothesis_set = resolve(
                    record,
                    hypothesis_set_id,
                    {"hypothesis_set.schema.json"},
                    "hypothesis_set_id",
                )
                if hypothesis_set is not None:
                    durable_hypothesis_ids = {
                        hypothesis.get("hypothesis_id")
                        for hypothesis in hypothesis_set.get("hypotheses", [])
                        if isinstance(hypothesis, Mapping)
                    }
                    if not set(record.get("retained_hypothesis_ids", [])).issubset(durable_hypothesis_ids):
                        errors.append("retained_hypothesis_ids: absent from the durable hypothesis set")
                    require_earlier(hypothesis_set, record, "hypothesis_set_id")
            resulting_revision_id = record.get("resulting_revision_id")
            if isinstance(resulting_revision_id, str):
                resulting_revision = resolve(
                    record,
                    resulting_revision_id,
                    {"world_revision.schema.json"},
                    "resulting_revision_id",
                )
                if resulting_revision is not None and (
                    resulting_revision.get("reconciliation_decision_id") != record.get("decision_id")
                ):
                    errors.append("resulting_revision_id: revision does not link back to decision")
        elif schema_name == "world_revision.schema.json":
            decision = None
            decision_id = record.get("reconciliation_decision_id")
            if isinstance(decision_id, str):
                decision = resolve(
                    record,
                    decision_id,
                    {"reconciliation_decision.schema.json"},
                    "reconciliation_decision_id",
                )
                if decision is not None and (
                    decision.get("decision") != "PROMOTE"
                    or decision.get("resulting_revision_id") != record.get("revision_id")
                ):
                    errors.append("reconciliation_decision_id: decision is not the matching PROMOTE")
                if decision is not None:
                    require_earlier(decision, record, "reconciliation_decision_id")
            candidate = None
            if isinstance(decision, Mapping):
                candidate_summary = decision.get("candidate", {})
                if isinstance(candidate_summary, Mapping) and isinstance(candidate_summary.get("candidate_id"), str):
                    candidate = resolve(
                        record,
                        candidate_summary["candidate_id"],
                        {"state_candidate.schema.json"},
                        "reconciliation_decision.candidate_id",
                    )
            if isinstance(candidate, Mapping):
                payload = candidate.get("payload", {})
                if isinstance(payload, Mapping) and (
                    record.get("payload_hash") != payload.get("content_hash")
                    or record.get("coverage_hash") != payload.get("coverage_hash")
                    or record.get("payload_media_type") != payload.get("media_type")
                    or record.get("payload_byte_size") != payload.get("byte_size")
                ):
                    errors.append("payload contract: differs from promoted candidate")
                if set(candidate.get("admitted_observation_ids", [])) != set(record.get("claim_ids", [])):
                    errors.append("claim_ids: differ from exact promoted observations")
                if record.get("candidate_id") != candidate.get("candidate_id"):
                    errors.append("candidate_id: differs from promoted candidate")
                if record.get("candidate_record_hash") != candidate.get("content_hash"):
                    errors.append("candidate_record_hash: differs from promoted candidate")
                if record.get("state_contract_hash") != candidate.get("state_contract_hash"):
                    errors.append("state_contract_hash: differs from promoted candidate")
                for field in ("spatial", "valid_time", "uncertainty"):
                    if record.get(field) != candidate.get(field):
                        errors.append(f"{field}: differs from promoted candidate")
                require_earlier(candidate, record, "candidate_id")
            if isinstance(decision, Mapping):
                if decision.get("branch_id") != record.get("branch_id"):
                    errors.append("reconciliation_decision_id: decision targets another branch")
                if decision.get("prior_revision_id") != record.get("prior_head_revision_id"):
                    errors.append("prior_head_revision_id: differs from promotion decision prior")
                candidate_summary = decision.get("candidate", {})
                if isinstance(candidate_summary, Mapping):
                    if record.get("candidate_id") != candidate_summary.get("candidate_id"):
                        errors.append("candidate_id: differs from promotion decision")
                    if record.get("candidate_record_hash") != candidate_summary.get("candidate_record_hash"):
                        errors.append("candidate_record_hash: differs from promotion decision")
                    if record.get("state_contract_hash") != candidate_summary.get("state_contract_hash"):
                        errors.append("state_contract_hash: differs from promotion decision")
                authority = record.get("authority_scope", {})
                decision_policy = decision.get("policy", {})
                if (
                    isinstance(authority, Mapping)
                    and isinstance(decision_policy, Mapping)
                    and authority.get("policy_id") != decision_policy.get("policy_id")
                ):
                    errors.append("authority_scope.policy_id: differs from promotion decision")
            branch_id = record.get("branch_id")
            if isinstance(branch_id, str):
                branch = resolve(record, branch_id, {"branch.schema.json"}, "branch_id")
                if branch is not None:
                    if record.get("state_kind") not in branch.get("permitted_state_kinds", []):
                        errors.append("branch_id: revision state_kind is not permitted on the target branch")
                    authority = record.get("authority_scope", {})
                    if isinstance(authority, Mapping):
                        for field in (
                            "branch_kind",
                            "environment_mode",
                            "policy_id",
                            "evaluation_visibility",
                        ):
                            if authority.get(field) != branch.get(field):
                                errors.append(f"authority_scope.{field}: differs from target branch")
            promoted_state = record.get("state_kind") in {
                "reconciled",
                "verified",
                "authoritative",
            }
            natural_claim_roles = {
                "planned": {("plan", "planned", "system_visible")},
                "predicted": {("physics_prediction", "predicted", "system_visible")},
                "simulated": {("simulation_result", "simulated", "system_visible")},
                "observed": {("observation", "observed", "system_visible")},
                "proposed": {
                    ("human_assertion", "proposed", "system_visible"),
                    ("observation", "observed", "system_visible"),
                },
                "reference": {
                    ("observation", "reference", "withheld_reference"),
                    ("simulation_result", "reference", "withheld_reference"),
                },
            }
            for claim_id in record.get("claim_ids", []):
                claim = resolve(record, claim_id, {"evidence_claim.schema.json"}, "claim_ids")
                if claim is None:
                    continue
                require_earlier(claim, record, "claim_ids")
                claim_role = (
                    claim.get("source_kind"),
                    claim.get("state_kind"),
                    claim.get("evaluation_visibility"),
                )
                if promoted_state and claim_role != ("observation", "observed", "system_visible"):
                    errors.append(f"claim_ids: {claim_id} is not system-visible observation evidence")
                elif not promoted_state and record.get("state_kind") in natural_claim_roles:
                    if claim_role not in natural_claim_roles[record["state_kind"]]:
                        errors.append(f"claim_ids: {claim_id} is incompatible with {record['state_kind']} revision")
            for event_id in record.get("event_ids", []):
                event = resolve(
                    record,
                    event_id,
                    {"action_event.schema.json", "supersession_event.schema.json"},
                    "event_ids",
                )
                if event is not None:
                    require_earlier(event, record, "event_ids")
            for parent_id in record.get("parent_revision_ids", []):
                parent = resolve(
                    record,
                    parent_id,
                    {"world_revision.schema.json"},
                    "parent_revision_ids",
                )
                if parent is not None:
                    if parent.get("branch_id") != record.get("branch_id"):
                        errors.append(f"parent_revision_ids: {parent_id} belongs to another branch")
                    require_earlier(parent, record, "parent_revision_ids")
                    if (
                        parent_id == record.get("prior_head_revision_id")
                        and isinstance(parent.get("branch_revision_sequence"), int)
                        and record.get("branch_revision_sequence") != parent["branch_revision_sequence"] + 1
                    ):
                        errors.append("branch_revision_sequence: is not contiguous from prior head")
            for superseded_id in record.get("supersedes_revision_ids", []):
                superseded = resolve(
                    record,
                    superseded_id,
                    {"world_revision.schema.json"},
                    "supersedes_revision_ids",
                )
                if superseded is not None:
                    require_earlier(superseded, record, "supersedes_revision_ids")
        elif schema_name == "evidence_claim.schema.json":
            branch_id = record.get("branch_id")
            if isinstance(branch_id, str):
                branch = resolve(record, branch_id, {"branch.schema.json"}, "branch_id")
                if branch is not None:
                    if record.get("state_kind") not in branch.get("permitted_state_kinds", []):
                        errors.append("branch_id: evidence state_kind is not permitted on the target branch")
                    if record.get("branch_kind") != branch.get("branch_kind"):
                        errors.append("branch_kind: differs from referenced branch")
                    if record.get("evaluation_visibility") != branch.get("evaluation_visibility"):
                        errors.append("evaluation_visibility: differs from referenced branch")
            for predecessor_id in record.get("predecessor_claim_ids", []):
                predecessor = resolve(
                    record,
                    predecessor_id,
                    {"evidence_claim.schema.json"},
                    "predecessor_claim_ids",
                )
                if predecessor is not None:
                    require_earlier(predecessor, record, "predecessor_claim_ids")
            for edge_id in record.get("dependency_edge_ids", []):
                edge = resolve(
                    record,
                    edge_id,
                    {"dependency_edge.schema.json"},
                    "dependency_edge_ids",
                )
                if edge is not None and record.get("claim_id") not in {
                    edge.get("left_claim_id"),
                    edge.get("right_claim_id"),
                }:
                    errors.append(f"dependency_edge_ids: {edge_id} does not name this claim")
        elif schema_name == "dependency_edge.schema.json":
            left = resolve(
                record,
                str(record.get("left_claim_id")),
                {"evidence_claim.schema.json"},
                "left_claim_id",
            )
            right = resolve(
                record,
                str(record.get("right_claim_id")),
                {"evidence_claim.schema.json"},
                "right_claim_id",
            )
            if left is not None and right is not None:
                require_earlier(left, record, "left_claim_id")
                require_earlier(right, record, "right_claim_id")
                left_visibility = left.get("evaluation_visibility")
                right_visibility = right.get("evaluation_visibility")
                if left_visibility != right_visibility:
                    errors.append("left_claim_id/right_claim_id: dependency crosses evaluation visibility")
                if record.get("evaluation_visibility") != left_visibility:
                    errors.append("evaluation_visibility: differs from dependency endpoints")
        elif schema_name == "action_event.schema.json":
            decision_record_id = record.get("decision_record_id")
            if isinstance(decision_record_id, str):
                decision_record = resolve(
                    record,
                    decision_record_id,
                    {"decision_record.schema.json"},
                    "decision_record_id",
                )
                if decision_record is not None:
                    if record.get("action_id") != decision_record.get("selected_action_id"):
                        errors.append("action_id: differs from planning decision selected action")
                    if set(record.get("planned_effect_claim_ids", [])) != set(
                        decision_record.get("expected_outcome_claim_ids", [])
                    ):
                        errors.append("planned_effect_claim_ids: differ from planning decision")
                    require_earlier(decision_record, record, "decision_record_id")
            for field in (
                "planned_effect_claim_ids",
                "reported_execution_claim_ids",
                "observed_effect_claim_ids",
            ):
                for claim_id in record.get(field, []):
                    claim = resolve(
                        record,
                        claim_id,
                        {"evidence_claim.schema.json"},
                        field,
                    )
                    if claim is None:
                        continue
                    require_earlier(claim, record, field)
                    if claim.get("evaluation_visibility") != "system_visible":
                        errors.append(f"{field}: {claim_id} is withheld reference evidence")
                    if field == "observed_effect_claim_ids" and (
                        claim.get("source_kind") != "observation" or claim.get("state_kind") != "observed"
                    ):
                        errors.append(f"{field}: {claim_id} is not observed evidence")
        elif schema_name == "supersession_event.schema.json":
            branch_id = record.get("branch_id")
            if isinstance(branch_id, str):
                resolve(record, branch_id, {"branch.schema.json"}, "branch_id")
            target = None
            target_record_id = record.get("target_record_id")
            if isinstance(target_record_id, str):
                target = resolve(
                    record,
                    target_record_id,
                    immutable_record_schemas,
                    "target_record_id",
                )
                if target is not None:
                    require_earlier(target, record, "target_record_id")
                    if target.get("branch_id") != record.get("branch_id"):
                        errors.append("target_record_id: target is on another branch")
            successor_record_id = record.get("successor_record_id")
            if isinstance(successor_record_id, str):
                if successor_record_id == target_record_id:
                    errors.append("successor_record_id: target cannot supersede itself")
                expected = immutable_record_schemas
                if target_record_id in by_id:
                    expected = {by_id[target_record_id][0]}
                successor = resolve(
                    record,
                    successor_record_id,
                    expected,
                    "successor_record_id",
                )
                if successor is not None:
                    require_earlier(successor, record, "successor_record_id")
                    if target is not None and (successor.get("branch_id") != target.get("branch_id")):
                        errors.append("successor_record_id: successor is on another branch")
            for evidence_id in record.get("evidence_ids", []):
                evidence = resolve(
                    record,
                    evidence_id,
                    {"evidence_claim.schema.json", "action_event.schema.json"},
                    "evidence_ids",
                )
                if evidence is not None:
                    require_earlier(evidence, record, "evidence_ids")
        elif schema_name == "conflict_record.schema.json":
            branch_id = record.get("branch_id")
            if isinstance(branch_id, str):
                resolve(record, branch_id, {"branch.schema.json"}, "branch_id")
            conflict_claims: list[Mapping[str, Any]] = []
            for claim_id in record.get("claim_ids", []):
                claim = resolve(
                    record,
                    claim_id,
                    {"evidence_claim.schema.json"},
                    "claim_ids",
                )
                if claim is not None:
                    require_earlier(claim, record, "claim_ids")
                    conflict_claims.append(claim)
            if len(conflict_claims) >= 2:
                spatial_values = [
                    claim.get("spatial", {}) for claim in conflict_claims if isinstance(claim.get("spatial"), Mapping)
                ]
                spatial_identity_fields = (
                    "representation",
                    "crs",
                    "frame_id",
                    "transform_chain_id",
                    "axis_order",
                    "value_unit",
                )
                for field in spatial_identity_fields:
                    if len({json.dumps(value.get(field), sort_keys=True) for value in spatial_values}) != 1:
                        errors.append(f"claim_ids: conflict claims differ in spatial {field}")
                bounds_values = [value.get("bounds", []) for value in spatial_values]
                common_bounds: list[float] = []
                if bounds_values and all(
                    isinstance(bounds, Sequence) and len(bounds) == len(bounds_values[0]) and len(bounds) % 2 == 0
                    for bounds in bounds_values
                ):
                    dimensions = len(bounds_values[0]) // 2
                    lowers = [max(float(bounds[index]) for bounds in bounds_values) for index in range(dimensions)]
                    uppers = [
                        min(float(bounds[index + dimensions]) for bounds in bounds_values)
                        for index in range(dimensions)
                    ]
                    if any(lower >= upper for lower, upper in zip(lowers, uppers)):
                        errors.append("claim_ids: conflict claims have no common spatial overlap")
                    common_bounds = [*lowers, *uppers]
                valid_values = [
                    claim.get("valid_time", {})
                    for claim in conflict_claims
                    if isinstance(claim.get("valid_time"), Mapping)
                ]
                clock_ids = {value.get("clock_id") for value in valid_values}
                if len(clock_ids) != 1:
                    errors.append("claim_ids: conflict claims use different valid-time clocks")
                overlap_start = max(float(value.get("start")) for value in valid_values)
                finite_ends = [float(value.get("end")) for value in valid_values if value.get("end") is not None]
                overlap_end = min(finite_ends) if finite_ends else None
                if overlap_end is not None and overlap_start >= overlap_end:
                    errors.append("claim_ids: conflict claims have no common valid-time overlap")
                declared_valid = record.get("valid_time", {})
                if isinstance(declared_valid, Mapping) and (
                    declared_valid.get("start") != overlap_start
                    or declared_valid.get("end") != overlap_end
                    or declared_valid.get("clock_id") != next(iter(clock_ids), None)
                ):
                    errors.append("valid_time: does not equal the conflict overlap interval")
                expected_overlap_hash = sha256_json(
                    {
                        "claim_ids": sorted(record.get("claim_ids", [])),
                        "bounds": common_bounds,
                        "valid_time": {
                            "start": overlap_start,
                            "end": overlap_end,
                            "clock_id": next(iter(clock_ids), None),
                        },
                    }
                )
                if record.get("spatial_overlap_hash") != expected_overlap_hash:
                    errors.append("spatial_overlap_hash: does not bind the computed overlap")
            hypothesis_set_id = record.get("hypothesis_set_id")
            if isinstance(hypothesis_set_id, str):
                hypothesis_set = resolve(
                    record,
                    hypothesis_set_id,
                    {"hypothesis_set.schema.json"},
                    "hypothesis_set_id",
                )
                if hypothesis_set is not None and hypothesis_set.get("conflict_id") != record.get("conflict_id"):
                    errors.append("hypothesis_set_id: does not link back to conflict")
            resolution_decision_id = record.get("resolution_decision_id")
            if isinstance(resolution_decision_id, str):
                resolution = resolve(
                    record,
                    resolution_decision_id,
                    {"reconciliation_decision.schema.json"},
                    "resolution_decision_id",
                )
                if resolution is not None:
                    require_earlier(resolution, record, "resolution_decision_id")
                    if resolution.get("decision") not in {"PROMOTE", "REJECT"}:
                        errors.append("resolution_decision_id: ABSTAIN/retention cannot resolve a conflict")
        elif schema_name == "hypothesis_set.schema.json":
            branch_id = record.get("branch_id")
            if isinstance(branch_id, str):
                resolve(record, branch_id, {"branch.schema.json"}, "branch_id")
            conflict = None
            conflict_id = record.get("conflict_id")
            if isinstance(conflict_id, str):
                conflict = resolve(
                    record,
                    conflict_id,
                    {"conflict_record.schema.json"},
                    "conflict_id",
                )
                if conflict is not None and conflict.get("hypothesis_set_id") != record.get("hypothesis_set_id"):
                    errors.append("conflict_id: does not link back to hypothesis set")
            hypotheses = [hypothesis for hypothesis in record.get("hypotheses", []) if isinstance(hypothesis, Mapping)]
            hypothesis_ids = [hypothesis.get("hypothesis_id") for hypothesis in hypotheses]
            if len(hypothesis_ids) != len(set(hypothesis_ids)):
                errors.append("hypotheses: hypothesis IDs must be unique")
            hypothesis_claim_sets = [frozenset(hypothesis.get("claim_ids", [])) for hypothesis in hypotheses]
            if len(hypothesis_claim_sets) != len(set(hypothesis_claim_sets)):
                errors.append("hypotheses: duplicate claim assignments are forbidden")
            claim_assignment_counts: dict[str, int] = {}
            for claim_set in hypothesis_claim_sets:
                for claim_id in claim_set:
                    claim_assignment_counts[str(claim_id)] = claim_assignment_counts.get(str(claim_id), 0) + 1
            overlapping_claims = sorted(claim_id for claim_id, count in claim_assignment_counts.items() if count > 1)
            if overlapping_claims:
                errors.append(f"hypotheses.claim_ids: assignments must be disjoint; overlap={overlapping_claims}")
            conflict_claim_ids = set(conflict.get("claim_ids", [])) if isinstance(conflict, Mapping) else set()
            covered_claim_ids = set().union(*hypothesis_claim_sets) if hypothesis_claim_sets else set()
            if conflict_claim_ids and covered_claim_ids != conflict_claim_ids:
                errors.append("hypotheses.claim_ids: do not cover exactly all conflicted claims")
            for hypothesis in hypotheses:
                if not isinstance(hypothesis, Mapping):
                    continue
                for claim_id in hypothesis.get("claim_ids", []):
                    claim = resolve(
                        record,
                        claim_id,
                        {"evidence_claim.schema.json"},
                        "hypotheses.claim_ids",
                    )
                    if claim is not None:
                        require_earlier(claim, record, "hypotheses.claim_ids")
                for evidence_id in hypothesis.get("supporting_evidence_ids", []):
                    evidence = resolve(
                        record,
                        evidence_id,
                        {
                            "evidence_claim.schema.json",
                            "dependency_edge.schema.json",
                            "action_event.schema.json",
                        },
                        "hypotheses.supporting_evidence_ids",
                    )
                    if evidence is not None:
                        require_earlier(evidence, record, "hypotheses.supporting_evidence_ids")
            resolution_decision_id = record.get("resolution_decision_id")
            if isinstance(resolution_decision_id, str):
                resolution = resolve(
                    record,
                    resolution_decision_id,
                    {"reconciliation_decision.schema.json"},
                    "resolution_decision_id",
                )
                if resolution is not None and resolution.get("decision") not in {
                    "PROMOTE",
                    "REJECT",
                }:
                    errors.append("resolution_decision_id: ABSTAIN/retention cannot resolve hypotheses")
        elif schema_name == "query_lens.schema.json":
            query_request = None
            query_request_id = record.get("query_request_id")
            if isinstance(query_request_id, str):
                query_request = resolve(
                    record,
                    query_request_id,
                    {"query_request.schema.json"},
                    "query_request_id",
                )
                if query_request is not None:
                    require_earlier(query_request, record, "query_request_id")
            if query_request is not None:
                for field in (
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
                ):
                    if record.get(field) != query_request.get(field):
                        errors.append(f"{field}: query result differs from immutable request")
            branch = None
            revision = None
            branch_id = record.get("branch_id")
            revision_id = record.get("resolved_revision_id")
            if isinstance(branch_id, str):
                branch = resolve(record, branch_id, {"branch.schema.json"}, "branch_id")
            if isinstance(revision_id, str):
                revision = resolve(
                    record,
                    revision_id,
                    {"world_revision.schema.json"},
                    "resolved_revision_id",
                )
                if revision is not None:
                    require_earlier(revision, record, "resolved_revision_id")
            if branch is not None and record.get("policy_id") != branch.get("policy_id"):
                errors.append("policy_id: lens policy differs from branch policy")
            if record.get("status") == "resolved" and revision is not None and branch is not None:
                if revision.get("branch_id") != branch.get("branch_id"):
                    errors.append("resolved_revision_id: revision is not on the lens branch")
                if record.get("resolved_state_kind") != revision.get("state_kind"):
                    errors.append("resolved_state_kind: differs from resolved revision")
                if record.get("resolved_state_kind") not in record.get("requested_state_kinds", []):
                    errors.append("resolved_state_kind: was not requested")
                if record.get("result_payload_hash") != revision.get("payload_hash"):
                    errors.append("result_payload_hash: differs from resolved revision")
                if record.get("result_coverage_hash") != revision.get("coverage_hash"):
                    errors.append("result_coverage_hash: differs from resolved revision")
                known_at = record.get("known_at", {})
                valid_at_request = record.get("valid_at", {})
                revision_transaction = revision.get("transaction_time", {})
                if (
                    isinstance(known_at, Mapping)
                    and isinstance(revision_transaction, Mapping)
                    and isinstance(known_at.get("sequence"), int)
                    and isinstance(revision_transaction.get("sequence"), int)
                    and revision_transaction["sequence"] > known_at["sequence"]
                ):
                    errors.append("known_at: resolved revision was not yet known")
                for event_schema, supersession in records:
                    if event_schema != "supersession_event.schema.json":
                        continue
                    supersession_sequence = transaction_sequence(supersession)
                    if (
                        supersession.get("target_record_id") == revision.get("revision_id")
                        and supersession.get("event_kind") in {"supersede", "invalidate"}
                        and isinstance(supersession_sequence, int)
                        and isinstance(known_at, Mapping)
                        and isinstance(known_at.get("sequence"), int)
                        and supersession_sequence <= known_at["sequence"]
                    ):
                        errors.append("resolved_revision_id: revision was superseded at known_at")
                if (
                    isinstance(known_at, Mapping)
                    and isinstance(record.get("projection_transaction_sequence"), int)
                    and isinstance(known_at.get("sequence"), int)
                    and record["projection_transaction_sequence"] < known_at["sequence"]
                ):
                    errors.append("projection_transaction_sequence: projection is stale at known_at")
                instant = valid_at_request.get("instant")
                clock_id = valid_at_request.get("clock_id")
                if (
                    not isinstance(instant, (int, float))
                    or not isinstance(clock_id, str)
                    or not valid_at(revision, instant, clock_id)
                ):
                    errors.append("valid_at: resolved revision is not valid at the requested instant")
                revision_spatial = revision.get("spatial", {})
                if isinstance(revision_spatial, Mapping):
                    spatial_pairs = {
                        "region_id": "region_id",
                        "representation": "representation",
                        "resolution": "resolution",
                        "frame_id": "frame_id",
                        "units": "units",
                    }
                    for lens_field, revision_field in spatial_pairs.items():
                        if record.get(lens_field) != revision_spatial.get(revision_field):
                            errors.append(f"{lens_field}: differs from resolved revision spatial contract")
                revision_claim_ids = set(revision.get("claim_ids", []))
                if set(record.get("available_claim_ids", [])) != revision_claim_ids:
                    errors.append("available_claim_ids: differ from resolved revision evidence")
            for claim_id in record.get("available_claim_ids", []):
                claim = resolve(
                    record,
                    claim_id,
                    {"evidence_claim.schema.json"},
                    "available_claim_ids",
                )
                if claim is not None:
                    require_earlier(claim, record, "available_claim_ids")
                    if claim.get("evaluation_visibility") != "system_visible":
                        errors.append(f"available_claim_ids: {claim_id} is a withheld reference")
                    known_at = record.get("known_at", {})
                    claim_sequence = transaction_sequence(claim)
                    if (
                        isinstance(known_at, Mapping)
                        and isinstance(known_at.get("sequence"), int)
                        and claim_sequence is not None
                        and claim_sequence > known_at["sequence"]
                    ):
                        errors.append(f"available_claim_ids: {claim_id} was not known at known_at")
                    requested_valid_at = record.get("valid_at", {})
                    instant = requested_valid_at.get("instant")
                    clock_id = requested_valid_at.get("clock_id")
                    if (
                        isinstance(instant, (int, float))
                        and isinstance(clock_id, str)
                        and not valid_at(claim, instant, clock_id)
                    ):
                        errors.append(f"available_claim_ids: {claim_id} is not valid at valid_at")
        elif schema_name == "decision_record.schema.json":
            lens = None
            revision = None
            lens_id = record.get("query_lens_id")
            revision_id = record.get("world_revision_id")
            if isinstance(lens_id, str):
                lens = resolve(record, lens_id, {"query_lens.schema.json"}, "query_lens_id")
                if lens is not None:
                    require_earlier(lens, record, "query_lens_id")
            if isinstance(revision_id, str):
                revision = resolve(
                    record,
                    revision_id,
                    {"world_revision.schema.json"},
                    "world_revision_id",
                )
                if revision is not None:
                    require_earlier(revision, record, "world_revision_id")
            if lens is not None and revision is not None:
                if lens.get("status") != "resolved":
                    errors.append("query_lens_id: planning requires a resolved query lens")
                if lens.get("resolved_revision_id") != revision.get("revision_id"):
                    errors.append("world_revision_id: differs from query lens result")
                if lens.get("resolved_state_kind") == "reference":
                    errors.append("query_lens_id: autonomy decisions cannot consume withheld reference state")
            alternatives = {
                item.get("action_id") for item in record.get("alternatives", []) if isinstance(item, Mapping)
            }
            if record.get("selected_action_id") not in alternatives:
                errors.append("selected_action_id: absent from alternatives")
            for claim_id in record.get("expected_outcome_claim_ids", []):
                claim = resolve(
                    record,
                    claim_id,
                    {"evidence_claim.schema.json"},
                    "expected_outcome_claim_ids",
                )
                if claim is not None:
                    require_earlier(claim, record, "expected_outcome_claim_ids")

    effective_successors: dict[tuple[str, str], str] = {}
    successor_graph: dict[str, str] = {}
    for event_schema, event in records:
        if event_schema != "supersession_event.schema.json":
            continue
        target_id = event.get("target_record_id")
        successor_id = event.get("successor_record_id")
        if not isinstance(target_id, str) or not isinstance(successor_id, str):
            continue
        branch_id = str(event.get("branch_id"))
        key = (branch_id, target_id)
        previous = effective_successors.get(key)
        if previous is not None and previous != successor_id:
            errors.append(f"target_record_id: {target_id} has multiple effective successors")
        effective_successors[key] = successor_id
        successor_graph[target_id] = successor_id
        target_entry = by_id.get(target_id)
        successor_entry = by_id.get(successor_id)
        if target_entry is not None and successor_entry is not None:
            target_schema, target = target_entry
            successor_schema, successor = successor_entry
            if target_schema != successor_schema:
                errors.append(f"successor_record_id: {successor_id} changes record type")
            if target.get("world_id") != successor.get("world_id"):
                errors.append(f"successor_record_id: {successor_id} crosses world_id")
            if target.get("site_id") != successor.get("site_id"):
                errors.append(f"successor_record_id: {successor_id} crosses site_id")
            if target_schema == "world_revision.schema.json" and target.get("spatial") != successor.get("spatial"):
                errors.append(f"successor_record_id: {successor_id} changes spatial contract")
    for start in successor_graph:
        visited: set[str] = set()
        current = start
        while current in successor_graph:
            if current in visited:
                errors.append(f"supersession chain: cycle reachable from {start}")
                break
            visited.add(current)
            current = successor_graph[current]

    return errors


def validate_record_set(records: Sequence[tuple[str, Mapping[str, Any]]]) -> list[str]:
    errors: list[str] = []
    for schema_name, record in records:
        record_errors = validate_record(schema_name, record)
        errors.extend(f"{schema_name}: {error}" for error in record_errors)
    try:
        errors.extend(cross_record_errors(records))
    except (IndexError, KeyError, OverflowError, TypeError, ValueError) as exc:
        errors.append(f"cross-record validation failed closed on malformed input: {type(exc).__name__}: {exc}")
    return errors
