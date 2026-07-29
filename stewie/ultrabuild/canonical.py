"""Canonical serialization and content identity helpers."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any


def canonical_bytes(value: Any) -> bytes:
    """Return strict, deterministic UTF-8 JSON bytes."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def record_content_hash(record: Mapping[str, Any]) -> str:
    """Hash a completed record, excluding only the self-referential hash."""

    canonical = deepcopy(dict(record))
    canonical.pop("content_hash", None)
    return sha256_json(canonical)


def submitted_record_hash(record: Mapping[str, Any]) -> str:
    """Hash the producer-controlled portion of a stored record."""

    submitted = deepcopy(dict(record))
    submitted.pop("transaction_time", None)
    submitted.pop("content_hash", None)
    submitted.pop("recorded_at", None)
    return sha256_json(submitted)


def state_contract_hash(record: Mapping[str, Any]) -> str:
    """Bind every value-defining spatial, temporal, uncertainty, and payload field."""

    return sha256_json(
        {
            "spatial": record.get("spatial"),
            "valid_time": record.get("valid_time"),
            "uncertainty": record.get("uncertainty"),
            "payload": record.get("payload")
            if "payload" in record
            else {
                "content_hash": record.get("payload_hash"),
                "coverage_hash": record.get("coverage_hash"),
                "media_type": record.get("payload_media_type"),
                "byte_size": record.get("payload_byte_size"),
            },
        }
    )


def submission_hash(submission: Mapping[str, Any]) -> str:
    return sha256_json(dict(submission))


def utc_now_text() -> str:
    """Return RFC-3339 UTC with microsecond resolution."""

    return datetime.now(tz=timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
