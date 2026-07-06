"""Traffic Memory (TW-11) -- STEWIE's per-cell traversal-hardening accumulator.

The conserved drive loop (`rover.four_wheel_pass(physical=True)`) already compacts a driven cell TOWARD the
load-determined equilibrium density and no further, so *repeated identical passes at the same load are
IDEMPOTENT* (audit H-09: progression comes from INCREASING load, not a per-roll / pass-count ratchet, which
reintroduced a dt-dependence bug). What the drive loop does NOT model is the *sub-equilibrium approach* a soil
that needs many load cycles to firm makes across a whole mission -- so a repeatedly driven haul road never
"remembers" that it should be a firmer future pad.

Traffic Memory closes that gap WITHOUT inventing new physics and WITHOUT touching the conserved solver: it is a
persistent, per-site, versioned + hash-chained accumulator (mirroring `terrain_memory.TerrainMemory` exactly)
that folds real drive telemetry -- which cells the wheels crossed, at what per-wheel normal load -- into three
per-cell fields: cumulative load `Sigma` [N], peak load `L_peak` [N], and pass count `N`. From those it derives
a densification that:

  * uses the EXISTING conserved equilibrium `terramechanics.physical_compaction_target_density(mass_areal,
    L_peak)` as the asymptote (the SAME function the drive loop uses -- not a re-invented law), capped at
    RHO_DEEP, so a cell can never firm past what the conserved model would produce;
  * approaches that asymptote EXPONENTIALLY in CUMULATIVE LOAD (not a naive pass count):
        rho_N = rho_eq - (rho_eq - RHO_SURFACE) * exp(-Sigma / Sigma_c)
    so more total traffic -> closer to the equilibrium, and a HEAVIER pass (bigger L_peak) raises the ceiling
    (consistent with H-09: increasing load firms further);
  * is MASS-CONSERVING in spirit (a per-cell density read; it does not move mass and does not mutate the
    conserved solver) and MONOTONE (Dr never decreases, never exceeds the equilibrium).

H-09-safety: `apply` is IDEMPOTENT on the telemetry event id -- re-folding the SAME batch is a no-op (no
double-count, no version bump, no chain link). Only a genuinely NEW event (new cumulative load) hardens
further and advances the hash chain. So re-committing the same SIM run cannot double-harden a road.

Honesty tags (surfaced, never silently defaulted): `Sigma_c` (characteristic cumulative load) and the
near-surface compactable-layer thickness are [CALIB] -- to be fit against a lunar multipass-rut densification
study / the Chrono oracle, exactly like the SLIP_C1/C2 [UNKNOWN] and Lyasko [CALIB] tags the rest of the
terramechanics carries.

Persistence + provenance follow `terrain_memory` verbatim: `.npz` under `<data_dir>/traffic_memory/<site>.npz`,
a `{version, mission, event_id, added_load_n, cells}` hash-chained record per NEW event (`verify_chain`), atomic
save (.part -> os.replace), and per-site load/save/snapshot/restore for the DT-03 compensating rollback. It
takes telemetry IN and never imports `lode` (the clean layering the terrain twin already uses).
"""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import cast

import numpy as np

from stewie.physics import material
from stewie.physics import terramechanics as tm
from stewie.specs import constants as K

# [CALIB] the near-surface layer a rover wheel actually compacts (the disturbed depth under the contact patch),
# used to derive the reference areal mass for the conserved equilibrium. Tagged like Lyasko/SLIP_C1-C2: a
# nominal value pending a lunar multipass-rut fit, never presented as measured.
_ROAD_LAYER_M = 0.10                                      # [CALIB] ~2/3 wheel radius disturbed depth
_NOMINAL_MASS_AREAL = float(K.RHO_SURFACE) * _ROAD_LAYER_M  # kg/m^2 reference road-layer areal mass

# [CALIB] characteristic CUMULATIVE per-cell load [N] over which the road firms to ~63% of the way to the
# equilibrium. ~5 dry IPEx wheel loads (5 * ~12.15 N ~ 61 N) -> substantial firming in a handful of haul
# passes, the multipass-rut regime; tagged [CALIB] pending the densification-vs-cycles fit.
_SIGMA_C_N = 60.0

_CHAIN_FIELDS = ("version", "mission", "event_id", "added_load_n", "cells")
_UNSET: np.ndarray = cast(np.ndarray, None)


def _record_hash(prev_hash: str, meta: dict) -> str:
    """sha256 over the prior record's hash + this record's metadata (sorted) -- the provenance link."""
    h = hashlib.sha256()
    h.update(prev_hash.encode())
    h.update(json.dumps(meta, sort_keys=True).encode())
    return h.hexdigest()


@dataclass
class TrafficMemory:
    """Authoritative per-site traversal-hardening state on a fixed grid + order frame (matching the site DEM,
    so it co-registers with TerrainMemory and the slope/DEM COGs). Holds cumulative load, peak load, and pass
    count per cell, plus the hash-chained provenance of the telemetry events folded in."""

    site: str
    rows: int
    cols: int
    cell_m: float
    origin: tuple[float, float] = (0.0, 0.0)              # order-frame (x0, y0) the grid covers [m]
    mass_areal: float = _NOMINAL_MASS_AREAL               # reference near-surface areal mass [kg/m^2] ([CALIB])
    sigma_c_n: float = _SIGMA_C_N                         # characteristic cumulative load [N] ([CALIB])
    contact_width_m: float = 0.18                         # IPEx wheel contact width [m] (ipex geometry)
    _load_cycles: np.ndarray = field(default=_UNSET, repr=False)   # (rows, cols) cumulative load Sigma [N]
    _peak_load: np.ndarray = field(default=_UNSET, repr=False)     # (rows, cols) peak per-cell load L_peak [N]
    _passes: np.ndarray = field(default=_UNSET, repr=False)        # (rows, cols) pass count N (uint32)
    version: int = 0
    chain: list = field(default_factory=list)
    _applied: list = field(default_factory=list)          # folded telemetry event-ids (H-09 idempotence)

    def __post_init__(self) -> None:
        if self.rows <= 0 or self.cols <= 0:
            raise ValueError(f"TrafficMemory grid must be positive (got rows={self.rows}, cols={self.cols})")
        if self.cell_m <= 0:
            raise ValueError(f"TrafficMemory cell_m must be > 0 (got {self.cell_m})")
        if self.sigma_c_n <= 0:
            raise ValueError(f"TrafficMemory sigma_c_n must be > 0 (got {self.sigma_c_n})")
        shape = (self.rows, self.cols)
        self._load_cycles = (np.zeros(shape, dtype=np.float64) if self._load_cycles is None
                             else np.asarray(self._load_cycles, dtype=np.float64))
        self._peak_load = (np.zeros(shape, dtype=np.float64) if self._peak_load is None
                           else np.asarray(self._peak_load, dtype=np.float64))
        self._passes = (np.zeros(shape, dtype=np.uint32) if self._passes is None
                        else np.asarray(self._passes, dtype=np.uint32))
        for name, arr in (("_load_cycles", self._load_cycles), ("_peak_load", self._peak_load),
                          ("_passes", self._passes)):
            if arr.shape != shape:
                raise ValueError(f"{name} shape {arr.shape} != grid {shape}")

    # ---- accumulation --------------------------------------------------------------------------------
    def apply(self, load_field: np.ndarray, *, mission: str, event_id: str) -> int:
        """Fold one telemetry event -- a per-cell wheel-load field [N] (0 where the wheels did not cross) --
        into the accumulator as a new versioned, hash-chained transaction; return the resulting version.

        H-09 idempotence: if this ``event_id`` was already folded, this is a NO-OP (no double-count, no
        version bump, no chain link) -- re-committing the same telemetry cannot double-harden the road. Only a
        NEW event advances the cumulative load, the peak load, the pass count, the version, and the chain."""
        if event_id in self._applied:
            return self.version                              # already folded -> idempotent
        d = np.asarray(load_field, dtype=np.float64)
        if d.shape != (self.rows, self.cols):
            raise ValueError(f"load_field shape {d.shape} != grid {(self.rows, self.cols)}")
        if not np.all(np.isfinite(d)):
            raise ValueError("load_field must be finite (got NaN/Inf)")
        d = np.maximum(d, 0.0)                               # a load is non-negative; a negative reading is a bug
        touched = d > 0.0
        self._load_cycles = self._load_cycles + d           # cumulative load Sigma += this event's load
        self._peak_load = np.maximum(self._peak_load, d)     # peak load = heaviest pass (hysteresis floor)
        self._passes = self._passes + touched.astype(np.uint32)
        self.version += 1
        self._applied.append(str(event_id))
        meta = {
            "version": self.version,
            "mission": str(mission),
            "event_id": str(event_id),
            "added_load_n": round(float(d.sum()), 6),
            "cells": int(np.count_nonzero(touched)),
        }
        prev = self.chain[-1]["hash"] if self.chain else ""
        self.chain.append({**meta, "hash": _record_hash(prev, meta)})
        return self.version

    def apply_path(self, cells: Iterable[tuple[int, int]], load_n: float, *,
                   mission: str, event_id: str) -> int:
        """Convenience: fold a driven CORRIDOR -- an iterable of (row, col) cells the wheels crossed, all at
        the same per-wheel normal load ``load_n`` [N] -- as one telemetry event. Cells outside the grid are
        dropped (surfaced only via the placed-cell count in the chain record). Idempotent on ``event_id``."""
        field_grid = np.zeros((self.rows, self.cols), dtype=np.float64)
        for (r, c) in cells:
            if 0 <= int(r) < self.rows and 0 <= int(c) < self.cols:
                field_grid[int(r), int(c)] = max(field_grid[int(r), int(c)], float(load_n))
        return self.apply(field_grid, mission=mission, event_id=event_id)

    # ---- derived fields (the SAME conserved equilibrium the drive loop uses) --------------------------
    def equilibrium_density(self) -> np.ndarray:
        """Per-cell asymptotic density [kg/m^3] the CONSERVED model reaches at the peak load seen -- exactly
        `terramechanics.physical_compaction_target_density(mass_areal, L_peak)` capped at RHO_DEEP. Unvisited
        cells (L_peak = 0) stay at RHO_SURFACE."""
        ma = np.full((self.rows, self.cols), float(self.mass_areal), dtype=np.float64)
        rho_eq = tm.physical_compaction_target_density(ma, self._peak_load,
                                                       contact_width_m=self.contact_width_m)
        return np.minimum(rho_eq, K.RHO_DEEP)

    def densified_density(self) -> np.ndarray:
        """Per-cell hardened density [kg/m^3] = an EXPONENTIAL approach to the equilibrium in CUMULATIVE LOAD:
        rho_N = rho_eq - (rho_eq - RHO_SURFACE) * exp(-Sigma / Sigma_c). Monotone in Sigma, asymptotes AT the
        equilibrium, never exceeds it. Sigma = 0 -> RHO_SURFACE (pristine)."""
        rho_eq = self.equilibrium_density()
        approach = 1.0 - np.exp(-self._load_cycles / float(self.sigma_c_n))
        return float(K.RHO_SURFACE) + (rho_eq - float(K.RHO_SURFACE)) * approach

    def relative_density(self) -> np.ndarray:
        """Per-cell relative density Dr in [0,1] of the hardened road (0 = loose RHO_SURFACE, 1 = paved
        RHO_DEEP), the traffic.compaction map field."""
        return material.relative_density(self.densified_density())

    def bearing_uplift_pa(self, *, width_m: float = 0.30, g: float = float(K.g),
                          factor_of_safety: float = 3.0) -> np.ndarray:
        """Per-cell allowable-bearing UPLIFT [Pa] the traffic produced: q_allow(rho_N) - q_allow(RHO_SURFACE),
        via `material.cell_strength` -> `bearing.allowable_bearing_pa` (the SAME bearing solver the release
        gate uses). A firmer haul road bears more -> a compacted road is a firmer future pad. ``width_m`` is
        the footprint width for the readout (a rover contact patch / a small pad); default 0.30 m."""
        from stewie_forge.bearing import allowable_bearing_pa

        def _q(rho: float) -> float:
            phi, c = material.cell_strength(rho)
            return allowable_bearing_pa(c, phi, rho * float(g), float(width_m),
                                        factor_of_safety=factor_of_safety)

        rho_n = self.densified_density()
        q_base = _q(float(K.RHO_SURFACE))
        q_field = np.vectorize(_q)(rho_n)
        return np.maximum(q_field - q_base, 0.0)

    # ---- reporting + provenance ----------------------------------------------------------------------
    def summary(self) -> dict:
        """A compact traffic-memory report: how much of the site has been trafficked and the peak hardening."""
        dr = self.relative_density()
        touched = self._passes > 0
        return {
            "site": self.site,
            "version": self.version,
            "cells_trafficked": int(np.count_nonzero(touched)),
            "max_passes": int(self._passes.max()) if self._passes.size else 0,
            "max_load_cycles_n": round(float(self._load_cycles.max()) if self._load_cycles.size else 0.0, 3),
            "peak_relative_density": round(float(dr.max()) if dr.size else 0.0, 4),
            "cells_firm_dr_gt_0p5": int(np.count_nonzero(dr > 0.5)),
            "peak_bearing_uplift_pa": round(float(self.bearing_uplift_pa().max()) if dr.size else 0.0, 3),
            "missions": [c["mission"] for c in self.chain],
        }

    def verify_chain(self) -> bool:
        """True iff the provenance hash chain is intact -- any tampering (reorder, edited mission/event) shows."""
        prev = ""
        for rec in self.chain:
            meta = {k: rec[k] for k in _CHAIN_FIELDS}
            if _record_hash(prev, meta) != rec.get("hash"):
                return False
            prev = rec["hash"]
        return True

    # ---- persistence (mirrors terrain_memory.save/load exactly) --------------------------------------
    def save(self, path: str) -> None:
        """Persist the accumulator grids + metadata + provenance chain to ``path`` (a .npz), ATOMICALLY
        (.part temp, fsync, os.replace) so a crash / concurrent writer never leaves a torn file."""
        meta = {
            "site": self.site, "rows": self.rows, "cols": self.cols, "cell_m": self.cell_m,
            "origin": list(self.origin), "mass_areal": self.mass_areal, "sigma_c_n": self.sigma_c_n,
            "contact_width_m": self.contact_width_m, "version": self.version,
            "chain": self.chain, "applied": list(self._applied),
        }
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            np.savez(f, load_cycles=self._load_cycles, peak_load=self._peak_load,
                     passes=self._passes, meta=json.dumps(meta))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: str) -> "TrafficMemory":
        """Restore a TrafficMemory persisted by :meth:`save` (verify_chain() should hold on the result)."""
        z = np.load(path, allow_pickle=False)
        m = json.loads(str(z["meta"]))
        return cls(site=m["site"], rows=int(m["rows"]), cols=int(m["cols"]), cell_m=float(m["cell_m"]),
                   origin=tuple(m["origin"]), mass_areal=float(m["mass_areal"]),
                   sigma_c_n=float(m["sigma_c_n"]), contact_width_m=float(m["contact_width_m"]),
                   _load_cycles=z["load_cycles"], _peak_load=z["peak_load"], _passes=z["passes"],
                   version=int(m["version"]), chain=list(m["chain"]), _applied=list(m["applied"]))


# -- per-site persistence store (mirrors terrain_memory) -----------------------------------------------

def _safe_site(site: str) -> str:
    """A path-safe filename component for a site name (no traversal, no separators)."""
    return "".join(c for c in str(site) if c.isalnum() or c in ("-", "_")) or "site"


def traffic_path(data_dir: str, site: str) -> str:
    """The persisted Traffic-Memory file for a site: ``<data_dir>/traffic_memory/<site>.npz``."""
    return os.path.join(data_dir, "traffic_memory", _safe_site(site) + ".npz")


def load_site(data_dir: str, site: str) -> "TrafficMemory | None":
    """Load a site's persisted Traffic Memory, or None if nothing has been recorded for it yet."""
    p = traffic_path(data_dir, site)
    return TrafficMemory.load(p) if os.path.exists(p) else None


def save_site(data_dir: str, memory: "TrafficMemory") -> str:
    """Persist a site's Traffic Memory under the data dir (creating the directory). Returns the path."""
    p = traffic_path(data_dir, memory.site)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    memory.save(p)
    return p


def snapshot_site(data_dir: str, site: str) -> bytes | None:
    """Capture the raw persisted Traffic-Memory bytes for a site (or None), so a world-log commit failure that
    FOLLOWS a :func:`save_site` can be COMPENSATED (:func:`restore_site`) -- DT-03, mirroring terrain_memory."""
    p = traffic_path(data_dir, site)
    if not os.path.exists(p):
        return None
    with open(p, "rb") as f:
        return f.read()


def restore_site(data_dir: str, site: str, snapshot: bytes | None) -> None:
    """Restore a site's persisted Traffic Memory to a prior ``snapshot`` (the compensating rollback of a
    :func:`save_site` whose world-log commit then failed). A None snapshot removes the file. Atomic write."""
    p = traffic_path(data_dir, site)
    if snapshot is None:
        if os.path.exists(p):
            os.remove(p)
        return
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".part"
    with open(tmp, "wb") as f:
        f.write(snapshot)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
