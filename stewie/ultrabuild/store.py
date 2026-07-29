"""SQLite authority boundary for immutable world-state records."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Iterator

from stewie.ultrabuild.canonical import (
    canonical_bytes,
    sha256_json,
    submission_hash,
    utc_now_text,
)
from stewie.ultrabuild.contracts import (
    finalize_record,
    json_schema_errors,
    record_id,
    record_set_errors,
    stored_record_errors,
    submission_errors,
)
from stewie.ultrabuild.derivation import candidate_derivation_errors
from stewie.ultrabuild.payloads import (
    ContentAddressedPayloadStore,
    PayloadIntegrityError,
)


SCHEMA_VERSION = 1


class StoreContractError(ValueError):
    """A submission or completed record violated the authority contract."""


class IdempotencyConflict(StoreContractError):
    """An idempotency key was reused with different canonical input."""


class PromotionConflict(StoreContractError):
    """Accepted-head compare-and-swap did not match the durable head."""


class AuthoritativeStore:
    """One durable append gateway and accepted-head projection.

    The store owns transaction sequence, transaction timestamp, final validation, content hashing,
    append, and accepted-head compare-and-swap. Callers cannot submit those fields.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        store_id: str = "store.ultrabuild.local",
        clock: Callable[[], str] = utc_now_text,
        payload_store: ContentAddressedPayloadStore | None = None,
        require_local_payloads: bool = False,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.store_id = store_id
        self._clock = clock
        self.payload_store = payload_store
        self.require_local_payloads = require_local_payloads
        if require_local_payloads and payload_store is None:
            raise ValueError("require_local_payloads needs a content-addressed payload store")
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.path,
            timeout=30.0,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._configure()
        self._migrate()

    def _configure(self) -> None:
        journal_mode = self._connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if str(journal_mode).lower() != "wal":
            raise RuntimeError(f"SQLite WAL unavailable: {journal_mode}")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA busy_timeout=30000")

    def _migrate(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS store_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS records (
                    sequence INTEGER PRIMARY KEY,
                    record_id TEXT NOT NULL UNIQUE,
                    record_schema TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    world_id TEXT,
                    site_id TEXT,
                    branch_id TEXT,
                    valid_start REAL,
                    valid_end REAL,
                    recorded_at TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE,
                    record_json BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS records_world_site_branch
                    ON records(world_id, site_id, branch_id, sequence);
                CREATE INDEX IF NOT EXISTS records_schema_sequence
                    ON records(record_schema, sequence);
                CREATE TABLE IF NOT EXISTS idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    submission_hash TEXT NOT NULL,
                    submission_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    receipt_json BLOB NOT NULL,
                    FOREIGN KEY(record_id) REFERENCES records(record_id)
                );
                CREATE TABLE IF NOT EXISTS branch_heads (
                    branch_id TEXT PRIMARY KEY,
                    world_id TEXT NOT NULL,
                    site_id TEXT NOT NULL,
                    policy_id TEXT NOT NULL,
                    revision_id TEXT,
                    revision_sequence INTEGER NOT NULL,
                    decision_id TEXT,
                    updated_transaction_sequence INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY,
                    operation_hash TEXT NOT NULL,
                    receipt_json BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS projection_watermarks (
                    projection_id TEXT PRIMARY KEY,
                    projected_sequence INTEGER NOT NULL
                );
                COMMIT;
                """
            )
        with self._transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO store_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            connection.execute("INSERT OR IGNORE INTO store_meta(key, value) VALUES('next_sequence', '1')")
            version = int(connection.execute("SELECT value FROM store_meta WHERE key='schema_version'").fetchone()[0])
            if version != SCHEMA_VERSION:
                raise RuntimeError(f"store schema {version} is unsupported; expected {SCHEMA_VERSION}")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield self._connection
        except BaseException:
            self._connection.execute("ROLLBACK")
            raise
        else:
            self._connection.execute("COMMIT")

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> AuthoritativeStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _next_sequence(self, connection: sqlite3.Connection) -> int:
        row = connection.execute("SELECT value FROM store_meta WHERE key='next_sequence'").fetchone()
        if row is None:
            raise RuntimeError("store_meta.next_sequence is missing")
        return int(row[0])

    def _set_next_sequence(self, connection: sqlite3.Connection, sequence: int) -> None:
        connection.execute(
            "UPDATE store_meta SET value=? WHERE key='next_sequence'",
            (str(sequence),),
        )

    def _all_records(self, connection: sqlite3.Connection) -> list[tuple[str, Mapping[str, Any]]]:
        rows = connection.execute("SELECT record_schema, record_json FROM records ORDER BY sequence").fetchall()
        return [(str(row["record_schema"]), json.loads(bytes(row["record_json"]))) for row in rows]

    def append(self, submission: Mapping[str, Any]) -> dict[str, Any]:
        return self.append_batch([submission])[0]

    def append_batch(
        self,
        submissions: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        if not submissions:
            return []
        canonical_submissions = [deepcopy(dict(item)) for item in submissions]
        with self._lock, self._transaction() as connection:
            return self._append_batch_in_transaction(
                connection,
                canonical_submissions,
                allow_promotion=False,
            )

    def _append_batch_in_transaction(
        self,
        connection: sqlite3.Connection,
        canonical_submissions: Sequence[dict[str, Any]],
        *,
        allow_promotion: bool,
    ) -> list[dict[str, Any]]:
        """The sole immutable append primitive; caller owns the SQLite transaction."""

        for index, submission in enumerate(canonical_submissions):
            errors = submission_errors(submission)
            if errors:
                raise StoreContractError(f"submission[{index}] invalid: " + "; ".join(errors))
        keys = [str(item["idempotency_key"]) for item in canonical_submissions]
        if len(keys) != len(set(keys)):
            raise StoreContractError("idempotency keys must be unique within one batch")
        if not allow_promotion:
            for submission in canonical_submissions:
                schema_name = submission["record_schema"]
                record = submission["record"]
                if (schema_name == "reconciliation_decision.schema.json" and record.get("decision") == "PROMOTE") or (
                    schema_name == "world_revision.schema.json"
                    and record.get("state_kind") in {"reconciled", "verified", "authoritative"}
                ):
                    raise StoreContractError("promotion decisions and accepted revisions require commit_promotion()")

        next_sequence = self._next_sequence(connection)
        returned: list[dict[str, Any] | None] = [None] * len(canonical_submissions)
        staged: list[tuple[int, str, dict[str, Any], dict[str, Any], str]] = []

        for index, submission in enumerate(canonical_submissions):
            digest = submission_hash(submission)
            existing = connection.execute(
                "SELECT submission_hash, receipt_json FROM idempotency WHERE idempotency_key=?",
                (submission["idempotency_key"],),
            ).fetchone()
            if existing is not None:
                if existing["submission_hash"] != digest:
                    raise IdempotencyConflict(
                        f"idempotency key {submission['idempotency_key']} was reused with different canonical input"
                    )
                receipt = json.loads(bytes(existing["receipt_json"]))
                receipt["duplicate"] = True
                returned[index] = receipt
                continue

            schema_name = str(submission["record_schema"])
            recorded_at = self._clock()
            completed = finalize_record(
                schema_name,
                submission["record"],
                sequence=next_sequence,
                recorded_at=recorded_at,
            )
            errors = stored_record_errors(schema_name, completed)
            if errors:
                raise StoreContractError(f"{schema_name} invalid after store normalization: " + "; ".join(errors))
            record_id(schema_name, completed)
            self._verify_payload_references(schema_name, completed)
            staged.append((index, schema_name, completed, submission, digest))
            next_sequence += 1

        if staged:
            graph = self._all_records(connection)
            graph.extend((schema, record) for _, schema, record, _, _ in staged)
            graph_errors = record_set_errors(graph)
            for _, schema_name, completed, _, _ in staged:
                if schema_name == "state_candidate.schema.json":
                    graph_errors.extend(
                        candidate_derivation_errors(
                            graph,
                            completed,
                            self.payload_store,
                        )
                    )
            if graph_errors:
                raise StoreContractError("record graph invalid: " + "; ".join(graph_errors))

        for index, schema_name, completed, submission, digest in staged:
            identity = record_id(schema_name, completed)
            transaction = completed["transaction_time"]
            valid = completed.get("valid_time")
            valid_start = valid.get("start") if isinstance(valid, Mapping) else None
            valid_end = valid.get("end") if isinstance(valid, Mapping) else None
            connection.execute(
                """
                INSERT INTO records(
                    sequence, record_id, record_schema, schema_version,
                    world_id, site_id, branch_id, valid_start, valid_end,
                    recorded_at, content_hash, record_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transaction["sequence"],
                    identity,
                    schema_name,
                    completed["schema_version"],
                    completed.get("world_id"),
                    completed.get("site_id"),
                    completed.get("branch_id"),
                    valid_start,
                    valid_end,
                    transaction["recorded_at"],
                    completed["content_hash"],
                    canonical_bytes(completed),
                ),
            )
            if schema_name == "branch.schema.json":
                connection.execute(
                    """
                    INSERT INTO branch_heads(
                        branch_id, world_id, site_id, policy_id, revision_id,
                        revision_sequence, decision_id, updated_transaction_sequence
                    ) VALUES(?, ?, ?, ?, ?, ?, NULL, ?)
                    """,
                    (
                        completed["branch_id"],
                        completed["world_id"],
                        completed["site_id"],
                        completed["policy_id"],
                        completed["head_revision_id"],
                        completed["head_sequence"],
                        transaction["sequence"],
                    ),
                )
            receipt = {
                "schema_version": "stewie.append_receipt/1.0",
                "receipt_id": f"receipt.append.{completed['content_hash'][:24]}",
                "store_id": self.store_id,
                "submission_id": submission["submission_id"],
                "idempotency_key": submission["idempotency_key"],
                "submission_hash": digest,
                "record_schema": schema_name,
                "record_id": identity,
                "transaction_time": transaction,
                "content_hash": completed["content_hash"],
                "durability": {
                    "committed": True,
                    "journal_mode": "wal",
                    "synchronous": "full",
                    "schema_version": SCHEMA_VERSION,
                },
                "duplicate": False,
            }
            receipt_errors = json_schema_errors("append_receipt.schema.json", receipt)
            if receipt_errors:
                raise RuntimeError("internal append receipt invalid: " + "; ".join(receipt_errors))
            connection.execute(
                """
                INSERT INTO idempotency(
                    idempotency_key, submission_hash, submission_id,
                    record_id, receipt_json
                ) VALUES(?, ?, ?, ?, ?)
                """,
                (
                    submission["idempotency_key"],
                    digest,
                    submission["submission_id"],
                    identity,
                    canonical_bytes(receipt),
                ),
            )
            returned[index] = receipt

        self._set_next_sequence(connection, next_sequence)
        if not all(receipt is not None for receipt in returned):
            raise RuntimeError("internal append receipt set is incomplete")
        return [dict(receipt) for receipt in returned if receipt is not None]

    @staticmethod
    def _payload_requirements(
        schema_name: str,
        record: Mapping[str, Any],
    ) -> list[tuple[str, int | None]]:
        requirements: list[tuple[str, int | None]] = []
        if schema_name in {
            "evidence_claim.schema.json",
            "state_candidate.schema.json",
        }:
            payload = record.get("payload", {})
            if isinstance(payload, Mapping):
                content_hash = payload.get("content_hash")
                coverage_hash = payload.get("coverage_hash")
                if isinstance(content_hash, str):
                    byte_size = payload.get("byte_size")
                    requirements.append(
                        (
                            content_hash,
                            byte_size if isinstance(byte_size, int) else None,
                        )
                    )
                if isinstance(coverage_hash, str):
                    requirements.append((coverage_hash, None))
        elif schema_name == "world_revision.schema.json":
            content_hash = record.get("payload_hash")
            coverage_hash = record.get("coverage_hash")
            if isinstance(content_hash, str):
                byte_size = record.get("payload_byte_size")
                requirements.append(
                    (
                        content_hash,
                        byte_size if isinstance(byte_size, int) else None,
                    )
                )
            if isinstance(coverage_hash, str):
                requirements.append((coverage_hash, None))
        elif schema_name == "provenance_bundle.schema.json":
            subject = record.get("subject", {})
            if isinstance(subject, Mapping):
                for field in ("payload_hash", "coverage_hash"):
                    content_hash = subject.get(field)
                    if isinstance(content_hash, str):
                        requirements.append((content_hash, None))
        return requirements

    def _verify_payload_references(
        self,
        schema_name: str,
        record: Mapping[str, Any],
    ) -> None:
        if not self.require_local_payloads:
            return
        if self.payload_store is None:
            raise RuntimeError("required payload verifier is unavailable")
        for content_hash, expected_size in self._payload_requirements(schema_name, record):
            try:
                self.payload_store.verify(
                    content_hash,
                    expected_size=expected_size,
                )
            except PayloadIntegrityError as exc:
                raise StoreContractError(f"{schema_name}: payload prerequisite failed: {exc}") from exc

    def get(self, record_id_value: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT record_json FROM records WHERE record_id=?",
                (record_id_value,),
            ).fetchone()
        if row is None:
            return None
        value = json.loads(bytes(row["record_json"]))
        if not isinstance(value, dict):
            raise RuntimeError("durable record JSON is not an object")
        return value

    def records(
        self,
        *,
        record_schema: str | None = None,
        known_at_sequence: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if record_schema is not None:
            clauses.append("record_schema=?")
            parameters.append(record_schema)
        if known_at_sequence is not None:
            clauses.append("sequence<=?")
            parameters.append(known_at_sequence)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._connection.execute(
                f"SELECT record_json FROM records {where} ORDER BY sequence",
                parameters,
            ).fetchall()
        return [json.loads(bytes(row["record_json"])) for row in rows]

    def latest_sequence(self) -> int:
        with self._lock:
            row = self._connection.execute("SELECT COALESCE(MAX(sequence), 0) FROM records").fetchone()
        if row is None:
            raise RuntimeError("latest-sequence query returned no row")
        return int(row[0])

    def verify_integrity(self) -> dict[str, Any]:
        """Re-validate durable bytes, graph semantics, receipts, and projections."""

        errors: list[str] = []
        payload_reference_count = 0
        with self._lock:
            rows = self._connection.execute("SELECT * FROM records ORDER BY sequence").fetchall()
            graph: list[tuple[str, Mapping[str, Any]]] = []
            for expected_sequence, row in enumerate(rows, start=1):
                schema_name = str(row["record_schema"])
                record = json.loads(bytes(row["record_json"]))
                graph.append((schema_name, record))
                prefix = f"sequence {row['sequence']} ({row['record_id']})"
                if int(row["sequence"]) != expected_sequence:
                    errors.append(
                        f"{prefix}: transaction sequence gap; expected {expected_sequence}"
                    )
                for error in stored_record_errors(schema_name, record):
                    errors.append(f"{prefix}: {error}")
                if record_id(schema_name, record) != row["record_id"]:
                    errors.append(f"{prefix}: row identity differs from record")
                transaction = record.get("transaction_time", {})
                if transaction.get("sequence") != row["sequence"]:
                    errors.append(f"{prefix}: row sequence differs from record")
                if transaction.get("recorded_at") != row["recorded_at"]:
                    errors.append(f"{prefix}: row timestamp differs from record")
                if record.get("content_hash") != row["content_hash"]:
                    errors.append(f"{prefix}: row hash differs from record")
                valid = record.get("valid_time")
                expected_shadow = {
                    "schema_version": record.get("schema_version"),
                    "world_id": record.get("world_id"),
                    "site_id": record.get("site_id"),
                    "branch_id": record.get("branch_id"),
                    "valid_start": valid.get("start") if isinstance(valid, Mapping) else None,
                    "valid_end": valid.get("end") if isinstance(valid, Mapping) else None,
                }
                for field, expected_value in expected_shadow.items():
                    if row[field] != expected_value:
                        errors.append(
                            f"{prefix}: row {field} differs from immutable record"
                        )
                payload_requirements = self._payload_requirements(
                    schema_name,
                    record,
                )
                payload_reference_count += len(payload_requirements)
                if self.payload_store is not None:
                    for content_hash, expected_size in payload_requirements:
                        try:
                            self.payload_store.verify(
                                content_hash,
                                expected_size=expected_size,
                            )
                        except PayloadIntegrityError as exc:
                            errors.append(f"{prefix}: {exc}")
            if payload_reference_count and self.payload_store is None:
                errors.append(f"payload verification unavailable for {payload_reference_count} durable references")
            errors.extend(f"graph: {error}" for error in record_set_errors(graph))
            for schema_name, record in graph:
                if schema_name == "state_candidate.schema.json":
                    errors.extend(
                        f"graph: {error}"
                        for error in candidate_derivation_errors(
                            graph,
                            record,
                            self.payload_store,
                        )
                    )

            expected_next = (int(rows[-1]["sequence"]) + 1) if rows else 1
            next_sequence = int(
                self._connection.execute("SELECT value FROM store_meta WHERE key='next_sequence'").fetchone()[0]
            )
            if next_sequence != expected_next:
                errors.append(f"store_meta.next_sequence: {next_sequence} != {expected_next}")

            record_rows = {str(row["record_id"]): row for row in rows}
            append_receipts_by_id: dict[str, Mapping[str, Any]] = {}
            append_receipt_counts: dict[str, int] = {}
            for row in self._connection.execute("SELECT * FROM idempotency").fetchall():
                receipt = json.loads(bytes(row["receipt_json"]))
                errors.extend(
                    f"append receipt: {error}" for error in json_schema_errors("append_receipt.schema.json", receipt)
                )
                for field in (
                    "idempotency_key",
                    "submission_hash",
                    "submission_id",
                    "record_id",
                ):
                    if row[field] != receipt.get(field):
                        errors.append(
                            f"append receipt {receipt.get('receipt_id', '<unknown>')}: "
                            f"registry {field} differs from receipt"
                        )
                receipt_id = receipt.get("receipt_id")
                if isinstance(receipt_id, str):
                    if receipt_id in append_receipts_by_id:
                        errors.append(f"append receipt {receipt_id}: duplicate receipt identity")
                    append_receipts_by_id[receipt_id] = receipt
                receipt_record_id = receipt.get("record_id")
                if isinstance(receipt_record_id, str):
                    append_receipt_counts[receipt_record_id] = (
                        append_receipt_counts.get(receipt_record_id, 0) + 1
                    )
                stored = record_rows.get(str(receipt_record_id))
                if stored is None or stored["content_hash"] != receipt.get("content_hash"):
                    errors.append(f"append receipt {receipt['receipt_id']}: durable record/hash is absent")
                    continue
                stored_record = json.loads(bytes(stored["record_json"]))
                if receipt.get("record_schema") != stored["record_schema"]:
                    errors.append(f"append receipt {receipt['receipt_id']}: record schema differs")
                if receipt.get("transaction_time") != stored_record.get("transaction_time"):
                    errors.append(f"append receipt {receipt['receipt_id']}: transaction time differs")
                if receipt.get("duplicate") is not False:
                    errors.append(f"append receipt {receipt['receipt_id']}: durable receipt must be original")

            for durable_record_id in record_rows:
                count = append_receipt_counts.get(durable_record_id, 0)
                if count != 1:
                    errors.append(
                        f"append receipt registry: record {durable_record_id} has "
                        f"{count} durable receipt rows; expected 1"
                    )
            unknown_receipt_records = sorted(set(append_receipt_counts) - set(record_rows))
            for unknown_record_id in unknown_receipt_records:
                errors.append(
                    f"append receipt registry: receipt targets absent record {unknown_record_id}"
                )

            applied_operations: dict[tuple[str, str], int] = {}
            for row in self._connection.execute("SELECT * FROM operations").fetchall():
                receipt = json.loads(bytes(row["receipt_json"]))
                errors.extend(
                    f"CAS receipt: {error}" for error in json_schema_errors("cas_receipt.schema.json", receipt)
                )
                if row["operation_id"] != receipt.get("operation_id"):
                    errors.append(
                        f"CAS receipt {receipt.get('receipt_id', '<unknown>')}: "
                        "registry operation_id differs from receipt"
                    )
                operation_hash = str(row["operation_hash"])
                if len(operation_hash) != 64 or any(
                    character not in "0123456789abcdef"
                    for character in operation_hash
                ):
                    errors.append(
                        f"CAS receipt {receipt.get('receipt_id', '<unknown>')}: "
                        "registry operation_hash is malformed"
                    )
                append_receipt_ids = receipt.get("append_receipt_ids", [])
                if isinstance(append_receipt_ids, list):
                    for append_receipt_id in append_receipt_ids:
                        if append_receipt_id not in append_receipts_by_id:
                            errors.append(
                                f"CAS receipt {receipt.get('receipt_id', '<unknown>')}: "
                                f"append receipt {append_receipt_id} is absent"
                            )
                if receipt.get("applied") is not True:
                    continue
                revision_id = receipt.get("proposed_revision_id")
                decision_id = receipt.get("decision_id")
                if not isinstance(revision_id, str) or not isinstance(decision_id, str):
                    continue
                promotion_key = (revision_id, decision_id)
                applied_operations[promotion_key] = (
                    applied_operations.get(promotion_key, 0) + 1
                )
                revision_row = record_rows.get(revision_id)
                decision_row = record_rows.get(decision_id)
                if (
                    revision_row is None
                    or revision_row["record_schema"] != "world_revision.schema.json"
                ):
                    errors.append(
                        f"CAS receipt {receipt['receipt_id']}: promoted revision is absent"
                    )
                if (
                    decision_row is None
                    or decision_row["record_schema"]
                    != "reconciliation_decision.schema.json"
                ):
                    errors.append(
                        f"CAS receipt {receipt['receipt_id']}: promotion decision is absent"
                    )
                required_receipt_ids = {
                    append_receipt_id
                    for record_row in (revision_row, decision_row)
                    if record_row is not None
                    for append_receipt_id, append_receipt in append_receipts_by_id.items()
                    if append_receipt.get("record_id") == record_row["record_id"]
                }
                if not required_receipt_ids.issubset(set(append_receipt_ids)):
                    errors.append(
                        f"CAS receipt {receipt['receipt_id']}: decision/revision append "
                        "receipt closure is incomplete"
                    )
                if revision_row is not None:
                    revision = json.loads(bytes(revision_row["record_json"]))
                    if receipt.get("transaction_time", {}).get("sequence") != revision.get(
                        "transaction_time", {}
                    ).get("sequence"):
                        errors.append(
                            f"CAS receipt {receipt['receipt_id']}: transaction sequence "
                            "differs from promoted revision"
                        )

            expected_promotions = {
                (
                    str(record["revision_id"]),
                    str(record["reconciliation_decision_id"]),
                )
                for schema_name, record in graph
                if schema_name == "world_revision.schema.json"
                and record.get("state_kind")
                in {"reconciled", "verified", "authoritative"}
            }
            for revision_id, decision_id in sorted(expected_promotions):
                count = applied_operations.get((revision_id, decision_id), 0)
                if count != 1:
                    errors.append(
                        f"CAS receipt registry: promotion {decision_id} -> {revision_id} "
                        f"has {count} applied operation rows; expected 1"
                    )
            for revision_id, decision_id in sorted(
                set(applied_operations) - expected_promotions
            ):
                errors.append(
                    f"CAS receipt registry: applied operation targets non-authoritative "
                    f"promotion {decision_id} -> {revision_id}"
                )

            expected_heads = self._derive_branch_heads(graph)
            actual_heads = {
                str(row["branch_id"]): dict(row)
                for row in self._connection.execute("SELECT * FROM branch_heads").fetchall()
            }
            if actual_heads != expected_heads:
                errors.append("branch_heads: projection differs from immutable history")

        return {
            "ok": not errors,
            "record_count": len(rows),
            "latest_sequence": len(rows) and int(rows[-1]["sequence"]) or 0,
            "errors": errors,
        }

    @staticmethod
    def _derive_branch_heads(
        graph: Sequence[tuple[str, Mapping[str, Any]]],
    ) -> dict[str, dict[str, Any]]:
        heads: dict[str, dict[str, Any]] = {}
        for schema_name, record in graph:
            if schema_name == "branch.schema.json":
                transaction = record["transaction_time"]
                heads[str(record["branch_id"])] = {
                    "branch_id": record["branch_id"],
                    "world_id": record["world_id"],
                    "site_id": record["site_id"],
                    "policy_id": record["policy_id"],
                    "revision_id": record["head_revision_id"],
                    "revision_sequence": record["head_sequence"],
                    "decision_id": None,
                    "updated_transaction_sequence": transaction["sequence"],
                }
            elif schema_name == "world_revision.schema.json" and record.get("state_kind") in {
                "reconciled",
                "verified",
                "authoritative",
            }:
                head = heads.get(str(record.get("branch_id")))
                if head is None:
                    continue
                branch_sequence = int(record["branch_revision_sequence"])
                if branch_sequence > int(head["revision_sequence"]):
                    head.update(
                        revision_id=record["revision_id"],
                        revision_sequence=branch_sequence,
                        decision_id=record["reconciliation_decision_id"],
                        updated_transaction_sequence=record["transaction_time"]["sequence"],
                    )
        return heads

    def rebuild_projections(self) -> dict[str, Any]:
        """Reconstruct mutable heads only after validating immutable history."""

        with self._lock, self._transaction() as connection:
            integrity = self.verify_integrity()
            history_errors = [
                error
                for error in integrity["errors"]
                if not error.startswith("branch_heads: projection differs")
            ]
            if history_errors:
                raise StoreContractError(
                    "projection rebuild refused non-integral immutable history: "
                    + "; ".join(history_errors)
                )
            graph = self._all_records(connection)
            heads = self._derive_branch_heads(graph)
            connection.execute("DELETE FROM branch_heads")
            for head in heads.values():
                connection.execute(
                    """
                    INSERT INTO branch_heads(
                        branch_id, world_id, site_id, policy_id, revision_id,
                        revision_sequence, decision_id,
                        updated_transaction_sequence
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        head["branch_id"],
                        head["world_id"],
                        head["site_id"],
                        head["policy_id"],
                        head["revision_id"],
                        head["revision_sequence"],
                        head["decision_id"],
                        head["updated_transaction_sequence"],
                    ),
                )
            connection.execute("DELETE FROM projection_watermarks")
        return {
            "schema_version": "stewie.projection_rebuild/1.0",
            "branch_count": len(heads),
            "source_sequence": self.latest_sequence(),
            "status": "rebuilt",
        }

    def snapshot_to(self, destination: str | Path) -> Path:
        """Back up SQLite first, then close payloads over that exact database cut."""

        target_path = Path(destination)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_payload_root = target_path.parent / "payloads"
        if target_path.exists():
            raise FileExistsError(f"snapshot database already exists: {target_path}")
        if target_payload_root.exists():
            raise FileExistsError(
                f"snapshot payload directory already exists: {target_payload_root}"
            )
        with self._lock:
            target = sqlite3.connect(target_path, isolation_level=None)
            target.row_factory = sqlite3.Row
            try:
                self._connection.backup(target)
                graph = self._all_records(target)
            finally:
                target.close()
        payload_hashes = {
            content_hash
            for schema_name, record in graph
            for content_hash, _ in self._payload_requirements(
                schema_name,
                record,
            )
        }
        if payload_hashes and self.payload_store is None:
            raise StoreContractError(
                "snapshot contains payload references but no payload verifier"
            )
        snapshot_payloads = ContentAddressedPayloadStore(target_payload_root)
        if self.payload_store is not None:
            snapshot_payloads = self.payload_store.snapshot_to(
                target_payload_root,
                payload_hashes,
            )
        with AuthoritativeStore(
            target_path,
            payload_store=snapshot_payloads,
            require_local_payloads=bool(payload_hashes),
        ) as restored:
            integrity = restored.verify_integrity()
        if not integrity["ok"]:
            raise StoreContractError(
                "snapshot failed exact-cut integrity verification: "
                + "; ".join(integrity["errors"])
            )
        return target_path

    def branch_head(self, branch_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM branch_heads WHERE branch_id=?", (branch_id,)).fetchone()
        return dict(row) if row is not None else None

    def commit_promotion(
        self,
        *,
        operation_id: str,
        expected_head_revision_id: str | None,
        expected_head_sequence: int,
        provenance_submissions: Sequence[Mapping[str, Any]],
        decision_submission: Mapping[str, Any],
        revision_submission: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Atomically append a reviewed promotion and compare-and-swap its branch head."""

        if self.payload_store is None:
            raise StoreContractError("promotion requires a configured payload verifier")
        provenance_submission_copies = [deepcopy(dict(item)) for item in provenance_submissions]
        decision_submission_copy = deepcopy(dict(decision_submission))
        revision_submission_copy = deepcopy(dict(revision_submission))
        operation_input = {
            "operation_id": operation_id,
            "expected_head_revision_id": expected_head_revision_id,
            "expected_head_sequence": expected_head_sequence,
            "provenance_submissions": provenance_submission_copies,
            "decision_submission": decision_submission_copy,
            "revision_submission": revision_submission_copy,
        }
        operation_hash = sha256_json(operation_input)

        with self._lock, self._transaction() as connection:
            existing_operation = connection.execute(
                "SELECT operation_hash, receipt_json FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if existing_operation is not None:
                if existing_operation["operation_hash"] != operation_hash:
                    raise IdempotencyConflict(f"operation {operation_id} was reused with different canonical input")
                receipt = json.loads(bytes(existing_operation["receipt_json"]))
                if receipt["applied"]:
                    receipt["reason_code"] = "idempotent_replay"
                return receipt

            if decision_submission_copy.get("record_schema") != ("reconciliation_decision.schema.json"):
                raise StoreContractError("promotion decision uses the wrong record schema")
            if revision_submission_copy.get("record_schema") != ("world_revision.schema.json"):
                raise StoreContractError("promotion revision uses the wrong record schema")
            if len(provenance_submission_copies) != 2 or any(
                item.get("record_schema") != "provenance_bundle.schema.json" for item in provenance_submission_copies
            ):
                raise StoreContractError("promotion requires exactly two provenance-bundle submissions")

            decision = decision_submission_copy.get("record", {})
            revision = revision_submission_copy.get("record", {})
            branch_id = revision.get("branch_id")
            if not isinstance(branch_id, str):
                raise StoreContractError("promotion revision has no branch_id")
            head = connection.execute("SELECT * FROM branch_heads WHERE branch_id=?", (branch_id,)).fetchone()
            if head is None:
                raise StoreContractError(f"accepted branch is not durable: {branch_id}")

            observed_revision_id = head["revision_id"]
            observed_sequence = int(head["revision_sequence"])
            current_transaction_sequence = self._next_sequence(connection) - 1

            preliminary_errors: list[str] = []
            review = decision.get("review", {})
            if decision.get("decision") != "PROMOTE":
                preliminary_errors.append("decision is not PROMOTE")
            if not isinstance(review, Mapping) or review.get("status") not in {
                "approved",
                "not_required",
            }:
                preliminary_errors.append("review is pending or rejected")
            if decision.get("resulting_revision_id") != revision.get("revision_id"):
                preliminary_errors.append("decision/revision cross-link differs")
            if decision.get("decision_id") != revision.get("reconciliation_decision_id"):
                preliminary_errors.append("revision/decision cross-link differs")
            if decision.get("prior_revision_id") != expected_head_revision_id:
                preliminary_errors.append("decision prior differs from expected head")
            if revision.get("prior_head_revision_id") != expected_head_revision_id:
                preliminary_errors.append("revision prior differs from expected head")
            if decision.get("branch_id") != branch_id:
                preliminary_errors.append("decision targets another branch")
            policy = decision.get("policy", {})
            if (
                not isinstance(policy, Mapping)
                or policy.get("policy_id") != head["policy_id"]
                or revision.get("authority_scope", {}).get("policy_id") != head["policy_id"]
            ):
                preliminary_errors.append("promotion policy differs from branch")
            if revision.get("world_id") != head["world_id"] or revision.get("site_id") != head["site_id"]:
                preliminary_errors.append("promotion crosses world/site")
            if revision.get("branch_revision_sequence") != expected_head_sequence + 1:
                preliminary_errors.append("branch revision sequence is not contiguous")

            if preliminary_errors:
                receipt = self._build_cas_receipt(
                    operation_id=operation_id,
                    head=head,
                    expected_head_revision_id=expected_head_revision_id,
                    observed_revision_id=observed_revision_id,
                    proposed_revision_id=str(revision.get("revision_id", "revision.invalid")),
                    decision_id=str(decision.get("decision_id", "decision.invalid")),
                    applied=False,
                    reason_code="invalid_promotion",
                    transaction_sequence=current_transaction_sequence,
                    append_receipt_ids=[],
                )
                connection.execute(
                    "INSERT INTO operations(operation_id, operation_hash, receipt_json) VALUES(?, ?, ?)",
                    (operation_id, operation_hash, canonical_bytes(receipt)),
                )
                return receipt

            if observed_revision_id != expected_head_revision_id or observed_sequence != expected_head_sequence:
                receipt = self._build_cas_receipt(
                    operation_id=operation_id,
                    head=head,
                    expected_head_revision_id=expected_head_revision_id,
                    observed_revision_id=observed_revision_id,
                    proposed_revision_id=revision["revision_id"],
                    decision_id=decision["decision_id"],
                    applied=False,
                    reason_code="stale_head",
                    transaction_sequence=current_transaction_sequence,
                    append_receipt_ids=[],
                )
                connection.execute(
                    "INSERT INTO operations(operation_id, operation_hash, receipt_json) VALUES(?, ?, ?)",
                    (operation_id, operation_hash, canonical_bytes(receipt)),
                )
                return receipt

            append_receipts = self._append_batch_in_transaction(
                connection,
                [
                    *provenance_submission_copies,
                    decision_submission_copy,
                    revision_submission_copy,
                ],
                allow_promotion=True,
            )
            if any(receipt["duplicate"] for receipt in append_receipts):
                raise StoreContractError("fresh promotion operation encountered independently appended records")
            revision_receipt = append_receipts[-1]
            connection.execute(
                """
                UPDATE branch_heads
                SET revision_id=?, revision_sequence=?, decision_id=?,
                    updated_transaction_sequence=?
                WHERE branch_id=? AND revision_id IS ? AND revision_sequence=?
                """,
                (
                    revision["revision_id"],
                    revision["branch_revision_sequence"],
                    decision["decision_id"],
                    revision_receipt["transaction_time"]["sequence"],
                    branch_id,
                    expected_head_revision_id,
                    expected_head_sequence,
                ),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise PromotionConflict("accepted-head compare-and-swap lost atomicity")
            receipt = self._build_cas_receipt(
                operation_id=operation_id,
                head=head,
                expected_head_revision_id=expected_head_revision_id,
                observed_revision_id=observed_revision_id,
                proposed_revision_id=revision["revision_id"],
                decision_id=decision["decision_id"],
                applied=True,
                reason_code="applied",
                transaction_sequence=revision_receipt["transaction_time"]["sequence"],
                append_receipt_ids=[append_receipt["receipt_id"] for append_receipt in append_receipts],
            )
            connection.execute(
                "INSERT INTO operations(operation_id, operation_hash, receipt_json) VALUES(?, ?, ?)",
                (operation_id, operation_hash, canonical_bytes(receipt)),
            )
            return receipt

    def _build_cas_receipt(
        self,
        *,
        operation_id: str,
        head: sqlite3.Row,
        expected_head_revision_id: str | None,
        observed_revision_id: str | None,
        proposed_revision_id: str,
        decision_id: str,
        applied: bool,
        reason_code: str,
        transaction_sequence: int,
        append_receipt_ids: Sequence[str],
    ) -> dict[str, Any]:
        receipt = {
            "schema_version": "stewie.cas_receipt/1.0",
            "receipt_id": f"receipt.cas.{sha256_json([operation_id, reason_code])[:24]}",
            "store_id": self.store_id,
            "operation_id": operation_id,
            "world_id": head["world_id"],
            "site_id": head["site_id"],
            "branch_id": head["branch_id"],
            "policy_id": head["policy_id"],
            "expected_revision_id": expected_head_revision_id,
            "observed_revision_id": observed_revision_id,
            "proposed_revision_id": proposed_revision_id,
            "decision_id": decision_id,
            "applied": applied,
            "reason_code": reason_code,
            "transaction_time": {
                "sequence": transaction_sequence,
                "recorded_at": self._clock(),
            },
            "append_receipt_ids": list(append_receipt_ids),
        }
        errors = json_schema_errors("cas_receipt.schema.json", receipt)
        if errors:
            raise RuntimeError("internal CAS receipt invalid: " + "; ".join(errors))
        return receipt

    def query_revision(
        self,
        *,
        world_id: str,
        site_id: str,
        branch_id: str,
        valid_at: float,
        known_at_sequence: int,
        state_kinds: Sequence[str],
    ) -> dict[str, Any] | None:
        integrity = self.verify_integrity()
        if not integrity["ok"]:
            raise StoreContractError(
                "authoritative query refused non-integral history: "
                + "; ".join(integrity["errors"])
            )
        placeholders = ",".join("?" for _ in state_kinds)
        if not placeholders:
            raise ValueError("state_kinds must not be empty")
        parameters: list[Any] = [
            world_id,
            site_id,
            branch_id,
            known_at_sequence,
            valid_at,
            valid_at,
            *state_kinds,
        ]
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT record_json
                FROM records
                WHERE record_schema='world_revision.schema.json'
                  AND world_id=? AND site_id=? AND branch_id=?
                  AND sequence<=?
                  AND valid_start<=?
                  AND (valid_end IS NULL OR ?<valid_end)
                  AND json_extract(record_json, '$.state_kind') IN ({placeholders})
                ORDER BY
                  COALESCE(
                    json_extract(record_json, '$.branch_revision_sequence'),
                    sequence
                  ) DESC,
                  sequence DESC
                """,
                parameters,
            ).fetchall()
            superseded = {
                row[0]
                for row in self._connection.execute(
                    """
                    SELECT json_extract(record_json, '$.target_record_id')
                    FROM records
                    WHERE record_schema='supersession_event.schema.json'
                      AND sequence<=?
                      AND world_id=? AND site_id=? AND branch_id=?
                      AND json_extract(record_json, '$.event_kind')
                          IN ('supersede', 'invalidate')
                    """,
                    (known_at_sequence, world_id, site_id, branch_id),
                ).fetchall()
            }
        for row in rows:
            record = json.loads(bytes(row["record_json"]))
            if record["revision_id"] not in superseded:
                if self.payload_store is None:
                    raise PayloadIntegrityError("authoritative query requires a configured payload verifier")
                for content_hash, expected_size in self._payload_requirements(
                    "world_revision.schema.json",
                    record,
                ):
                    self.payload_store.verify(
                        content_hash,
                        expected_size=expected_size,
                    )
                return record
        return None

    def projection_receipt(self, projection_id: str, *, requested_sequence: int) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT projected_sequence FROM projection_watermarks WHERE projection_id=?",
                (projection_id,),
            ).fetchone()
        projected = int(row[0]) if row is not None else 0
        lag = max(0, requested_sequence - projected)
        status = "fresh" if lag == 0 else ("partial" if projected > 0 else "stale")
        receipt = {
            "schema_version": "stewie.projection_receipt/1.0",
            "receipt_id": f"receipt.projection.{projection_id}.{requested_sequence}",
            "store_id": self.store_id,
            "projection_id": projection_id,
            "requested_sequence": requested_sequence,
            "projected_sequence": projected,
            "lag_records": lag,
            "status": status,
            "generated_at": self._clock(),
        }
        errors = json_schema_errors("projection_receipt.schema.json", receipt)
        if errors:
            raise RuntimeError("internal projection receipt invalid: " + "; ".join(errors))
        return receipt

    def set_projection_watermark(self, projection_id: str, projected_sequence: int) -> None:
        if projected_sequence < 0 or projected_sequence > self.latest_sequence():
            raise ValueError("projection watermark is outside durable record history")
        with self._lock, self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO projection_watermarks(projection_id, projected_sequence)
                VALUES(?, ?)
                ON CONFLICT(projection_id) DO UPDATE SET
                    projected_sequence=excluded.projected_sequence
                """,
                (projection_id, projected_sequence),
            )
