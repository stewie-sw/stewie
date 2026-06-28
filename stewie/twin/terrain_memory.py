"""Terrain Memory -- STEWIE's authoritative world model (the core paradigm: IPEx physically CHANGES the
terrain, and STEWIE maintains the authoritative terrain state, NOT a rover-centric SLAM snapshot).

A per-site store that starts from the base DEM and ACCUMULATES the mass-conserving per-cell height changes
of every applied mission, as a versioned, hash-chained sequence of transactions -- so the terrain
"remembers" what was built and a future mission can plan against the CURRENT surface rather than the
pristine DEM. This module owns accumulation + versioning + provenance + persistence + diff only; the
per-cell deltas it accumulates come from the conserved authority (stewie.physics.column_state, via the
lode mission-execution path). It deliberately does NOT recompute the physics -- a delta is whatever the
conserved authority produced for a mission (cut = surface drops = negative; fill = positive). This keeps
the layering clean (lode -> {physics, twin}; terrain_memory takes deltas IN, never imports lode).

Provenance follows the twin's hash-chain pattern (stewie.twin.versioned): each apply() appends a record
{version, mission, mass_moved_kg, net_volume_m3} whose hash chains the prior record's hash, so the
transaction log is tamper-evident (verify_chain). The net_volume in each record is derived from that
transaction's delta, so the chain also commits to how much terrain each mission moved.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import cast

import numpy as np

_CHAIN_FIELDS = ("version", "mission", "mass_moved_kg", "net_volume_m3")
# _delta is filled in __post_init__ (zeros, or the loaded grid); typed ndarray (not Optional) so the
# read sites need no None-narrowing -- the field default is None at runtime but typed for the annotation
# (the same pattern as stewie.physics.column_state._UNSET).
_UNSET: np.ndarray = cast(np.ndarray, None)


def _record_hash(prev_hash: str, meta: dict) -> str:
    """sha256 over the prior record's hash + this record's metadata (sorted) -- the provenance link."""
    h = hashlib.sha256()
    h.update(prev_hash.encode())
    h.update(json.dumps(meta, sort_keys=True).encode())
    return h.hexdigest()


@dataclass
class TerrainMemory:
    """Authoritative per-site terrain state: the order-frame origin/cell of the worked region plus an
    accumulated per-cell height-delta grid [m] (current surface minus the base DEM), with a hash-chained
    provenance log of the missions applied. The base DEM itself is held by the caller (it does not change);
    Terrain Memory holds the CHANGES, so ``current_height(base) = base + cumulative_delta``."""

    site: str
    rows: int
    cols: int
    cell_m: float
    origin: tuple[float, float] = (0.0, 0.0)              # order-frame (x0, y0) the delta grid covers [m]
    _delta: np.ndarray = field(default=_UNSET, repr=False)  # (rows, cols) accumulated height delta [m]
    version: int = 0
    chain: list = field(default_factory=list)             # provenance records (see module docstring)

    def __post_init__(self) -> None:
        if self.rows <= 0 or self.cols <= 0:
            raise ValueError(f"TerrainMemory grid must be positive (got rows={self.rows}, cols={self.cols})")
        if self.cell_m <= 0:
            raise ValueError(f"TerrainMemory cell_m must be > 0 (got {self.cell_m})")
        if self._delta is None:
            self._delta = np.zeros((self.rows, self.cols), dtype=np.float64)
        else:
            self._delta = np.asarray(self._delta, dtype=np.float64)
            if self._delta.shape != (self.rows, self.cols):
                raise ValueError(f"delta shape {self._delta.shape} != grid {(self.rows, self.cols)}")

    @property
    def cell_area(self) -> float:
        return self.cell_m * self.cell_m

    def apply(self, delta: np.ndarray, *, mission: str, mass_moved_kg: float = 0.0) -> int:
        """Fold a mission's per-cell height delta [m] (same grid + order frame) into the authoritative
        state as a new versioned, hash-chained transaction; return the new version. The delta is whatever
        the conserved authority produced for the mission; accumulation is additive (the terrain remembers
        prior missions). Rejects a shape mismatch or any NaN/Inf (a non-finite delta would poison the state)."""
        d = np.asarray(delta, dtype=np.float64)
        if d.shape != (self.rows, self.cols):
            raise ValueError(f"delta shape {d.shape} != grid {(self.rows, self.cols)}")
        if not np.all(np.isfinite(d)):
            raise ValueError("delta must be finite (got NaN/Inf)")
        self._delta = self._delta + d
        self.version += 1
        meta = {
            "version": self.version,
            "mission": str(mission),
            "mass_moved_kg": round(float(mass_moved_kg), 6),
            "net_volume_m3": round(float(d.sum()) * self.cell_area, 6),
        }
        prev = self.chain[-1]["hash"] if self.chain else ""
        self.chain.append({**meta, "hash": _record_hash(prev, meta)})
        return self.version

    def cumulative_delta(self) -> np.ndarray:
        """The accumulated per-cell height change [m] vs the base DEM (a fresh copy)."""
        return self._delta.copy()

    def current_height(self, base_height: np.ndarray) -> np.ndarray:
        """The current authoritative surface [m] = base DEM + accumulated delta (the world model's terrain)."""
        b = np.asarray(base_height, dtype=np.float64)
        if b.shape != (self.rows, self.cols):
            raise ValueError(f"base_height shape {b.shape} != grid {(self.rows, self.cols)}")
        return b + self._delta

    def summary(self) -> dict:
        """A compact terrain-memory report: how much the site has changed across all applied missions."""
        d = self._delta
        return {
            "site": self.site,
            "version": self.version,
            "cells_changed": int(np.count_nonzero(np.abs(d) > 1e-9)),
            "net_volume_m3": round(float(d.sum()) * self.cell_area, 6),   # net (cut negative, fill positive)
            "max_cut_m": round(float(-d.min()) if d.size else 0.0, 6),    # deepest drop (most-negative delta)
            "max_fill_m": round(float(d.max()) if d.size else 0.0, 6),    # highest build
            "missions": [c["mission"] for c in self.chain],
        }

    def verify_chain(self) -> bool:
        """True iff the provenance hash chain is intact -- each record's hash equals H(prev_hash, its meta),
        so any tampering with the transaction log (reordering, edited mission/volume) is detected."""
        prev = ""
        for rec in self.chain:
            meta = {k: rec[k] for k in _CHAIN_FIELDS}
            if _record_hash(prev, meta) != rec.get("hash"):
                return False
            prev = rec["hash"]
        return True

    def save(self, path: str) -> None:
        """Persist the accumulated delta grid + metadata + provenance chain to ``path`` (a .npz)."""
        meta = {
            "site": self.site, "rows": self.rows, "cols": self.cols, "cell_m": self.cell_m,
            "origin": list(self.origin), "version": self.version, "chain": self.chain,
        }
        np.savez(path, delta=self._delta, meta=json.dumps(meta))

    @classmethod
    def load(cls, path: str) -> "TerrainMemory":
        """Restore a TerrainMemory persisted by :meth:`save` (verify_chain() should hold on the result)."""
        z = np.load(path, allow_pickle=False)
        m = json.loads(str(z["meta"]))
        return cls(site=m["site"], rows=int(m["rows"]), cols=int(m["cols"]), cell_m=float(m["cell_m"]),
                   origin=tuple(m["origin"]), _delta=z["delta"], version=int(m["version"]), chain=list(m["chain"]))
