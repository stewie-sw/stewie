"""The versioned, event-sourced OBSERVED-terrain twin (STEWIE P2.2).

"Store history, not terrain" (world_model doctrine, L0-L5): a TwinStore holds an immutable BASE
map plus an append-only EDIT LOG; the current map is derived by replaying events over the base.
Every event carries mandatory PROVENANCE, bumps the monotonic version, and is hash-chained
(sha256 over the previous hash + the event content + the patch bytes) so history is tamper-evident.
Undo never deletes history: it appends an `undo` event and replays without the undone edit.

Boundary (production-correctness): this is the PERCEPTION/OPS view of terrain. Resync patches come
from reconstruction (P2.2); the CONSERVED physics authority (column_state) is never mutated through
this channel -- digging changes the world, perception changes the twin.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

import numpy as np


@dataclass
class TwinStore:
    base: np.ndarray
    cell_m: float
    events: list = field(default_factory=list)
    version: int = 0
    journal_path: str | None = None     # W-1 (PRD 6.2): per-edit durable append; None = volatile

    def __post_init__(self):
        self.base = np.asarray(self.base, dtype=np.float64).copy()
        self.base.setflags(write=False)                  # the base layer is immutable
        # RC-01 (audit 2026-06-11): the FastAPI threadpool runs sync handlers in parallel, so
        # concurrent /twin/resync would interleave the seq/hash/append read-modify-write and
        # corrupt the chain. RLock makes every mutation atomic (re-entrant: apply_event -> undo
        # -> _append all hold it). Not in dataclass fields (not part of equality/serialization).
        import threading
        object.__setattr__(self, "_lock", threading.RLock())

    @classmethod
    def from_journal(cls, base, cell_m: float, journal_path: str) -> "TwinStore":
        """W-4 cold restore: rebuild the twin from base + the durable journal ALONE. Events replay
        through apply_event (hash-verified line by line); the rebuilt store keeps journaling."""
        import os as _os
        tw = cls(base, cell_m=cell_m)                    # replay WITHOUT journaling (no re-append)
        if _os.path.exists(journal_path):
            lines = [ln.strip() for ln in open(journal_path) if ln.strip()]
            for i, line in enumerate(lines):
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    # twin-gap-1 (audit 2026-06-11): a crash mid-fsync tears the FINAL line only.
                    # Recover every complete prior event; abort ONLY if the corruption is interior
                    # (a torn line that is NOT the last is real history loss, surface it).
                    if i == len(lines) - 1:
                        break
                    raise ValueError(f"twin journal corrupt at interior line {i} (not the tail) "
                                     "-- refusing a partial silent restore")
                tw.apply_event(ev)
        tw.journal_path = journal_path                   # future edits journal again
        return tw

    # ---- event plumbing ------------------------------------------------------------------
    def _chain_hash(self, body: dict, patch_bytes: bytes) -> str:
        prev = self.events[-1]["hash"] if self.events else "genesis"
        h = hashlib.sha256()
        h.update(prev.encode())
        h.update(json.dumps({k: v for k, v in body.items() if k != "hash"},
                            sort_keys=True).encode())
        h.update(patch_bytes)
        return h.hexdigest()

    @property
    def _mutex(self):
        lk = getattr(self, "_lock", None)
        if lk is None:                                   # from_journal / pickled stores: lazy-make
            import threading
            lk = threading.RLock(); object.__setattr__(self, "_lock", lk)
        return lk

    def _append(self, body: dict, patch_bytes: bytes, *, expected_hash: "str | None" = None) -> int:
        body["seq"] = len(self.events)
        body["hash"] = self._chain_hash(body, patch_bytes)
        # M-12: on REPLAY, verify the chain hash BEFORE any mutation or durable write -- a tampered log
        # raises with NO state change and is NOT extended with the bad event (atomic failure), instead of
        # the old apply-then-check which mutated (and re-persisted) before detecting the mismatch.
        if expected_hash is not None and body["hash"] != expected_hash:
            raise ValueError("replay hash mismatch -- the event log was altered")
        # H-20: durably append BEFORE committing the in-memory event/version, so a write/fsync failure
        # leaves memory == disk (not ahead). W-1: durable before we report success.
        if self.journal_path:
            import os as _os
            with open(self.journal_path, "a") as fh:
                fh.write(json.dumps(body, sort_keys=True) + "\n")
                fh.flush()
                _os.fsync(fh.fileno())
        self.events.append(body)                         # commit in-memory ONLY after the durable append
        self.version += 1
        return self.version

    # ---- edits ---------------------------------------------------------------------------
    def apply_patch(self, heights_m: np.ndarray, *, origin_rc: tuple, provenance: str) -> int:
        """Replace the observed heights of a rectangular region. Returns the new version."""
        with self._mutex:                                # RC-01: atomic seq+hash+append+version
            return self._apply_patch_locked(heights_m, origin_rc=origin_rc, provenance=provenance)

    def _apply_patch_locked(self, heights_m, *, origin_rc, provenance, expected_hash=None) -> int:
        if not provenance or not str(provenance).strip():
            raise ValueError("every twin edit requires non-empty provenance")
        p = np.asarray(heights_m, dtype=np.float64)
        if p.ndim != 2 or not np.isfinite(p).all():
            raise ValueError("patch must be a finite 2-D height array")
        r0, c0 = int(origin_rc[0]), int(origin_rc[1])
        if r0 < 0 or c0 < 0 or r0 + p.shape[0] > self.base.shape[0] \
                or c0 + p.shape[1] > self.base.shape[1]:
            raise ValueError(f"patch {p.shape} at ({r0},{c0}) exceeds the twin extent "
                             f"{self.base.shape}")
        ev = {"kind": "patch", "origin_rc": [r0, c0], "shape": list(p.shape),
              "provenance": str(provenance), "patch": p.tolist()}
        return self._append(ev, p.tobytes(), expected_hash=expected_hash)

    def apply_event(self, ev: dict) -> int:
        """Replay a recorded event verbatim (rebuild path). Verifies the chain as it goes."""
        with self._mutex:
            return self._apply_event_locked(ev)

    def _apply_event_locked(self, ev: dict) -> int:
        # M-12: the chain hash is verified INSIDE _append, BEFORE the mutation + durable write, so a
        # tampered log raises atomically (no state change, no bad event persisted).
        if ev["kind"] == "patch":
            return self._apply_patch_locked(np.array(ev["patch"]), origin_rc=tuple(ev["origin_rc"]),
                                            provenance=ev["provenance"], expected_hash=ev["hash"])
        if ev["kind"] == "undo":
            return self._undo_locked(expected_hash=ev["hash"])
        raise ValueError(f"unknown twin event kind {ev['kind']!r}")

    def undo(self) -> int:
        """Append an undo event for the most recent un-undone patch. History is never deleted."""
        with self._mutex:
            return self._undo_locked()

    def _undo_locked(self, expected_hash=None) -> int:
        undone = {e["seq"] for e in self.events if e["kind"] == "undo"}
        live = [e for e in self.events if e["kind"] == "patch"
                and e["seq"] not in {u["target"] for u in self.events if u["kind"] == "undo"}]
        del undone
        if not live:
            raise ValueError("nothing to undo")
        target = live[-1]["seq"]
        return self._append({"kind": "undo", "target": target,
                             "provenance": f"undo of seq {target}"}, b"", expected_hash=expected_hash)

    # ---- derived state -------------------------------------------------------------------
    def current(self) -> np.ndarray:
        undone = {e["target"] for e in self.events if e["kind"] == "undo"}
        out = self.base.copy()
        for e in self.events:
            if e["kind"] == "patch" and e["seq"] not in undone:
                r0, c0 = e["origin_rc"]
                p = np.array(e["patch"])
                out[r0:r0 + p.shape[0], c0:c0 + p.shape[1]] = p
        return out

    def verify_chain(self) -> bool:
        prev = "genesis"
        for e in self.events:
            h = hashlib.sha256()
            h.update(prev.encode())
            h.update(json.dumps({k: v for k, v in e.items() if k != "hash"},
                                sort_keys=True).encode())
            pb = (np.array(e["patch"], dtype=np.float64).tobytes()
                  if e["kind"] == "patch" else b"")
            h.update(pb)
            if h.hexdigest() != e["hash"]:
                return False
            prev = e["hash"]
        return True

    def history(self) -> list:
        """Provenance-bearing event summaries (no patch payloads)."""
        return [{k: v for k, v in e.items() if k != "patch"} for e in self.events]
