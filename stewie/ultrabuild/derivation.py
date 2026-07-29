"""Trusted reconstruction of observation-only candidate payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import prod
from typing import Any

import numpy as np

from stewie.ultrabuild.payloads import (
    ContentAddressedPayloadStore,
    PayloadIntegrityError,
)


def _record_identity(
    schema_name: str,
    record: Mapping[str, Any],
) -> str | None:
    fields = {
        "dependency_edge.schema.json": "edge_id",
        "evidence_claim.schema.json": "claim_id",
        "state_candidate.schema.json": "candidate_id",
    }
    field = fields.get(schema_name)
    value = record.get(field) if field is not None else None
    return value if isinstance(value, str) else None


def _sensor_variance(claim: Mapping[str, Any]) -> float | None:
    uncertainty = claim.get("uncertainty")
    if not isinstance(uncertainty, Mapping):
        return None
    for component in uncertainty.get("components", []):
        if isinstance(component, Mapping) and component.get("kind") == "sensor" and component.get("status") == "known":
            standard_deviation = component.get("value")
            if isinstance(standard_deviation, (int, float)) and standard_deviation > 0.0:
                return float(standard_deviation) ** 2
    return None


def _dependency_groups(
    claim_ids: list[str],
    edges: list[Mapping[str, Any]],
) -> list[list[str]]:
    parent = {claim_id: claim_id for claim_id in claim_ids}

    def find(claim_id: str) -> str:
        root = claim_id
        while parent[root] != root:
            root = parent[root]
        while parent[claim_id] != claim_id:
            next_id = parent[claim_id]
            parent[claim_id] = root
            claim_id = next_id
        return root

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    admitted = set(claim_ids)
    for edge in edges:
        left = edge.get("left_claim_id")
        right = edge.get("right_claim_id")
        if isinstance(left, str) and isinstance(right, str):
            if left in admitted and right in admitted:
                union(left, right)

    grouped: dict[str, list[str]] = {}
    for claim_id in claim_ids:
        grouped.setdefault(find(claim_id), []).append(claim_id)
    return [sorted(group) for _, group in sorted(grouped.items())]


def candidate_derivation_errors(
    records: Sequence[tuple[str, Mapping[str, Any]]],
    candidate: Mapping[str, Any],
    payload_store: ContentAddressedPayloadStore | None,
) -> list[str]:
    """Prove candidate bytes are deterministically derived from admitted observations.

    Physics predictions and other comparison evidence can affect admission, but their
    payload bytes never enter this reconstruction.
    """

    prefix = f"candidate {candidate.get('candidate_id', '<unknown>')}"
    if payload_store is None:
        return [f"{prefix}: observation-only derivation requires a payload verifier"]

    by_id: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for schema_name, record in records:
        identity = _record_identity(schema_name, record)
        if identity is not None:
            by_id[identity] = (schema_name, record)

    spatial = candidate.get("spatial")
    shape_value = spatial.get("shape") if isinstance(spatial, Mapping) else None
    if (
        not isinstance(shape_value, Sequence)
        or isinstance(shape_value, (str, bytes))
        or not shape_value
        or not all(isinstance(item, int) and item > 0 for item in shape_value)
    ):
        return [f"{prefix}: candidate shape is not reconstructable"]
    shape = tuple(int(item) for item in shape_value)
    cell_count = prod(shape)

    admitted_ids = candidate.get("admitted_observation_ids")
    if not isinstance(admitted_ids, list) or not admitted_ids:
        return [f"{prefix}: no admitted observations"]

    claims: list[Mapping[str, Any]] = []
    errors: list[str] = []
    for claim_id in admitted_ids:
        target = by_id.get(str(claim_id))
        if target is None or target[0] != "evidence_claim.schema.json":
            errors.append(f"{prefix}: admitted claim {claim_id} is unavailable")
            continue
        claim = target[1]
        if claim.get("source_kind") != "observation" or claim.get("state_kind") != "observed":
            errors.append(f"{prefix}: admitted claim {claim_id} is not observed evidence")
            continue
        claims.append(claim)
    if errors:
        return errors

    values_by_id: dict[str, np.ndarray] = {}
    coverage_by_id: dict[str, np.ndarray] = {}
    try:
        for claim in claims:
            claim_id = str(claim["claim_id"])
            payload = claim.get("payload")
            if not isinstance(payload, Mapping):
                errors.append(f"{prefix}: claim {claim_id} has no payload contract")
                continue
            if payload.get("media_type") != "application/x-stewie-raster":
                errors.append(f"{prefix}: claim {claim_id} is not a supported raster")
                continue
            value_bytes = payload_store.get(str(payload.get("content_hash")))
            coverage_bytes = payload_store.get(str(payload.get("coverage_hash")))
            if len(value_bytes) != cell_count * 8:
                errors.append(f"{prefix}: claim {claim_id} raster byte size differs from shape")
                continue
            if len(coverage_bytes) != cell_count:
                errors.append(f"{prefix}: claim {claim_id} coverage byte size differs from shape")
                continue
            values_by_id[claim_id] = np.frombuffer(
                value_bytes,
                dtype="<f8",
            ).reshape(shape)
            raw_coverage = np.frombuffer(coverage_bytes, dtype=np.uint8)
            if not np.all((raw_coverage == 0) | (raw_coverage == 1)):
                errors.append(f"{prefix}: claim {claim_id} coverage is not binary")
                continue
            coverage_by_id[claim_id] = raw_coverage.astype(bool).reshape(shape)

        candidate_payload = candidate.get("payload")
        if not isinstance(candidate_payload, Mapping):
            errors.append(f"{prefix}: candidate has no payload contract")
            return errors
        if candidate_payload.get("media_type") != "application/x-stewie-raster":
            errors.append(f"{prefix}: candidate is not a supported raster")
            return errors
        candidate_bytes = payload_store.get(str(candidate_payload.get("content_hash")))
        candidate_coverage_bytes = payload_store.get(str(candidate_payload.get("coverage_hash")))
    except (PayloadIntegrityError, ValueError) as exc:
        errors.append(f"{prefix}: payload verification failed: {exc}")
        return errors

    if errors:
        return errors
    if len(candidate_bytes) != cell_count * 8:
        errors.append(f"{prefix}: candidate raster byte size differs from shape")
    if len(candidate_coverage_bytes) != cell_count:
        errors.append(f"{prefix}: candidate coverage byte size differs from shape")
    if errors:
        return errors

    claim_ids = [str(claim["claim_id"]) for claim in claims]
    construction = candidate.get("construction")
    weights = {claim_id: 1.0 for claim_id in claim_ids}
    if construction == "dependency_aware_inverse_variance_mean":
        for claim in claims:
            claim_id = str(claim["claim_id"])
            variance = _sensor_variance(claim)
            if variance is None:
                errors.append(f"{prefix}: claim {claim_id} lacks a positive sensor variance")
            else:
                weights[claim_id] = 1.0 / max(1.0e-6, variance)
        edges: list[Mapping[str, Any]] = []
        for edge_id in candidate.get("dependency_edge_ids", []):
            target = by_id.get(str(edge_id))
            if target is not None and target[0] == "dependency_edge.schema.json":
                edges.append(target[1])
        for group in _dependency_groups(claim_ids, edges):
            group_total = sum(weights[claim_id] for claim_id in group)
            group_cap = max(weights[claim_id] for claim_id in group)
            scale = group_cap / group_total
            for claim_id in group:
                weights[claim_id] *= scale
    elif construction != "plain_mean_of_admissible_observations":
        errors.append(f"{prefix}: unsupported construction {construction!r}")
    if errors:
        return errors

    numerator = np.zeros(shape, dtype=np.float64)
    denominator = np.zeros(shape, dtype=np.float64)
    expected_coverage = np.zeros(shape, dtype=bool)
    for claim_id in claim_ids:
        coverage = coverage_by_id[claim_id]
        values = values_by_id[claim_id]
        if not np.all(np.isfinite(values[coverage])):
            errors.append(f"{prefix}: claim {claim_id} has non-finite covered values")
            continue
        weight = weights[claim_id]
        numerator[coverage] += values[coverage] * weight
        denominator[coverage] += weight
        expected_coverage |= coverage
    if errors:
        return errors

    expected = np.full(shape, np.nan, dtype=np.float64)
    expected[expected_coverage] = numerator[expected_coverage] / denominator[expected_coverage]
    expected_bytes = np.asarray(expected, dtype="<f8").tobytes(order="C")
    expected_coverage_bytes = expected_coverage.astype(np.uint8).tobytes(order="C")
    if candidate_bytes != expected_bytes:
        errors.append(f"{prefix}: payload bytes are not the declared observation-only derivation")
    if candidate_coverage_bytes != expected_coverage_bytes:
        errors.append(f"{prefix}: coverage bytes are not the union of admitted observations")
    if candidate_payload.get("byte_size") != len(expected_bytes):
        errors.append(f"{prefix}: declared payload byte size differs from derivation")
    return errors
