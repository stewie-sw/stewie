"""Schema-backed submission and stored-record contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import json
from pathlib import Path
import sysconfig
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from stewie.ultrabuild.canonical import record_content_hash


FORMAT_CHECKER = FormatChecker()

PRIMARY_KEY_BY_SCHEMA = {
    "action_event.schema.json": "event_id",
    "barrier_decision.schema.json": "decision_id",
    "branch.schema.json": "branch_id",
    "conflict_record.schema.json": "conflict_id",
    "decision_record.schema.json": "decision_record_id",
    "dependency_edge.schema.json": "edge_id",
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


def schema_root() -> Path:
    """Locate source-tree or installed UltraBuild schemas."""

    source = Path(__file__).resolve().parents[2] / "schemas" / "ultrabuild"
    if source.is_dir():
        return source
    target_install = (
        Path(__file__).resolve().parents[2]
        / "share"
        / "stewie"
        / "schemas"
        / "ultrabuild"
    )
    if target_install.is_dir():
        return target_install
    installed = (
        Path(sysconfig.get_path("data"))
        / "share"
        / "stewie"
        / "schemas"
        / "ultrabuild"
    )
    if installed.is_dir():
        return installed
    raise RuntimeError("UltraBuild schema directory is unavailable")


def load_schema(schema_name: str) -> dict[str, Any]:
    path = schema_root() / schema_name
    if path.parent != schema_root() or not path.is_file():
        raise ValueError(f"unknown UltraBuild schema: {schema_name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{schema_name}: schema root must be an object")
    return value


def json_schema_errors(schema_name: str, value: Mapping[str, Any]) -> list[str]:
    validator = Draft202012Validator(load_schema(schema_name), format_checker=FORMAT_CHECKER)
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(value), key=lambda item: list(item.absolute_path))
    ]


def record_id(schema_name: str, record: Mapping[str, Any]) -> str:
    key = PRIMARY_KEY_BY_SCHEMA.get(schema_name)
    if key is None:
        raise ValueError(f"{schema_name}: not an appendable record schema")
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{schema_name}: missing record identity {key}")
    return value


def submission_errors(submission: Mapping[str, Any]) -> list[str]:
    errors = json_schema_errors("record_submission.schema.json", submission)
    record = submission.get("record")
    schema_name = submission.get("record_schema")
    if isinstance(record, Mapping) and isinstance(schema_name, str):
        schema_version = record.get("schema_version")
        expected_schema = load_schema(schema_name).get("properties", {}).get(
            "schema_version", {}
        ).get("const")
        if schema_version != expected_schema:
            errors.append(
                f"record.schema_version: expected {expected_schema!r} for {schema_name}"
            )
        try:
            record_id(schema_name, record)
        except ValueError as exc:
            errors.append(str(exc))
    return errors


def finalize_record(
    schema_name: str,
    submitted_record: Mapping[str, Any],
    *,
    sequence: int,
    recorded_at: str,
) -> dict[str, Any]:
    """Assign store-owned transaction metadata and final content identity."""

    record = deepcopy(dict(submitted_record))
    forbidden = {"transaction_time", "content_hash", "recorded_at"} & record.keys()
    if forbidden:
        raise ValueError(
            "submission attempted to control store-owned fields: "
            + ", ".join(sorted(forbidden))
        )
    record["transaction_time"] = {
        "sequence": sequence,
        "recorded_at": recorded_at,
    }
    if schema_name == "reconciliation_decision.schema.json":
        record["recorded_at"] = recorded_at
    record["content_hash"] = record_content_hash(record)
    return record


def stored_record_errors(schema_name: str, record: Mapping[str, Any]) -> list[str]:
    """Apply shape plus repository semantic rules to one completed record."""

    errors = json_schema_errors(schema_name, record)
    if record.get("content_hash") != record_content_hash(record):
        errors.append("content_hash: does not commit the canonical complete record")
    transaction = record.get("transaction_time")
    if not isinstance(transaction, Mapping):
        errors.append("transaction_time: store metadata missing")
    else:
        sequence = transaction.get("sequence")
        if not isinstance(sequence, int) or sequence < 1:
            errors.append("transaction_time.sequence: must be a positive store sequence")
        if schema_name == "reconciliation_decision.schema.json":
            if record.get("recorded_at") != transaction.get("recorded_at"):
                errors.append("recorded_at: differs from transaction_time.recorded_at")
    return errors


def record_set_errors(
    records: Sequence[tuple[str, Mapping[str, Any]]],
) -> list[str]:
    """Run the full repository cross-record resolver.

    Keeping this call at the authority boundary makes the existing adversarial resolver part of the
    executable contract while the package remains source-compatible with the repository build.
    """

    from stewie.ultrabuild.validation import validate_record_set

    return validate_record_set(records)
