"""Durable content-addressed storage for immutable spatial payload bytes."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
from typing import Any

from stewie.ultrabuild.canonical import utc_now_text
from stewie.ultrabuild.contracts import json_schema_errors


class PayloadIntegrityError(IOError):
    """Payload bytes are missing or do not match their content identity."""


class ContentAddressedPayloadStore:
    """A filesystem CAS with atomic replace and file/directory fsync."""

    def __init__(
        self,
        root: str | Path,
        *,
        store_id: str = "payload-store.ultrabuild.local",
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.store_id = store_id

    @staticmethod
    def digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _validate_digest(content_hash: str) -> None:
        if (
            len(content_hash) != 64
            or any(character not in "0123456789abcdef" for character in content_hash)
        ):
            raise ValueError("content_hash must be a lowercase SHA-256 digest")

    def relative_path(self, content_hash: str) -> Path:
        self._validate_digest(content_hash)
        return Path("sha256") / content_hash[:2] / content_hash

    def path(self, content_hash: str) -> Path:
        return self.root / self.relative_path(content_hash)

    def put(
        self,
        data: bytes,
        *,
        media_type: str,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        content_hash = self.digest(data)
        target = self.path(content_hash)
        target.parent.mkdir(parents=True, exist_ok=True)
        duplicate = target.exists()
        if duplicate:
            self.verify(content_hash, expected_size=len(data))
        else:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{content_hash}.",
                dir=target.parent,
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
                directory_descriptor = os.open(
                    target.parent,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                )
                try:
                    os.fsync(directory_descriptor)
                finally:
                    os.close(directory_descriptor)
            finally:
                if temporary.exists():
                    temporary.unlink()
        receipt = {
            "schema_version": "stewie.payload_receipt/1.0",
            "receipt_id": f"receipt.payload.{content_hash[:24]}",
            "store_id": self.store_id,
            "content_hash": content_hash,
            "media_type": media_type,
            "byte_size": len(data),
            "relative_path": self.relative_path(content_hash).as_posix(),
            "durability": {
                "committed": True,
                "file_fsync": True,
                "directory_fsync": True,
            },
            "duplicate": duplicate,
            "generated_at": generated_at or utc_now_text(),
        }
        errors = json_schema_errors("payload_receipt.schema.json", receipt)
        if errors:
            raise RuntimeError(
                "internal payload receipt invalid: " + "; ".join(errors)
            )
        return receipt

    def verify(
        self,
        content_hash: str,
        *,
        expected_size: int | None = None,
    ) -> int:
        target = self.path(content_hash)
        try:
            data = target.read_bytes()
        except FileNotFoundError as exc:
            raise PayloadIntegrityError(
                f"payload {content_hash} is missing"
            ) from exc
        if self.digest(data) != content_hash:
            raise PayloadIntegrityError(
                f"payload {content_hash} fails digest verification"
            )
        if expected_size is not None and len(data) != expected_size:
            raise PayloadIntegrityError(
                f"payload {content_hash} has {len(data)} bytes; "
                f"expected {expected_size}"
            )
        return len(data)

    def get(self, content_hash: str) -> bytes:
        self.verify(content_hash)
        return self.path(content_hash).read_bytes()

    def has(self, content_hash: str) -> bool:
        try:
            self.verify(content_hash)
        except PayloadIntegrityError:
            return False
        return True
