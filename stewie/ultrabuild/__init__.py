"""Persistent, bitemporal world-state runtime for the STEWIE research artifact.

The package deliberately exposes a small authority surface. Producers submit records without
transaction metadata; :class:`AuthoritativeStore` assigns ordering, validates the completed record,
hashes it, and commits it durably.
"""

from stewie.ultrabuild.store import (
    AuthoritativeStore,
    IdempotencyConflict,
    PromotionConflict,
    StoreContractError,
)

__all__ = [
    "AuthoritativeStore",
    "IdempotencyConflict",
    "PromotionConflict",
    "StoreContractError",
]
