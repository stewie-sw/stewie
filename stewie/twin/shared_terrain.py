"""[GATE3-P2] Concurrent multi-vehicle modification of ONE shared terrain region.

Why this exists. STEWIE's fleet planner allocates trips SITE-EXCLUSIVELY: trips are grouped by site
so no two vehicles ever work the same site, which makes ``lode.planner_multivehicle._vehicle_conflicts``
zero by construction and leaves ``lode.planner_sim`` with no terrain reference at all. Nothing in the
system has ever had two vehicles write the same ground.

That is the setting the world-state work requires, for a reason sharper than
"multi-robot support": later observations have shared provenance and must not
be declared independent without an observation-error model that justifies it.
The shared action changes the true post-action surface; it does not by itself
correlate conditionally independent sensor noise. This module therefore emits
a conservative *possible-dependency relation*, not an estimated correlation
coefficient.

Scope. This is the concurrency + dependency-detection primitive only. It records WHO changed WHICH
cells WHEN, detects cell-level space-time overlap, and hands the correlated set to a caller. It does
not decide what to do about the correlation; that is the promotion policy's job and is deliberately
not modelled here. Continuous haul-path collision avoidance is likewise out of scope.

Conservation. Concurrent application is additive per cell, which is what the conserved authority
already does for sequential missions: two vehicles each removing 0.1 m from a cell leave it 0.2 m
lower. Mass is therefore conserved across the concurrent apply exactly as it is sequentially, and the
tests assert that against the sum of the individual actions.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from stewie.twin.terrain_memory import TerrainMemory


@dataclass(frozen=True)
class VehicleAction:
    """One vehicle's terrain modification over a time window, on the shared site grid.

    ``delta`` is the per-cell height change [m] the conserved authority produced for this action
    (cut negative, fill positive), on the site grid. ``t_start``/``t_end`` are mission-elapsed
    seconds; they define the window used for space-TIME overlap, so two vehicles touching the same
    cells at disjoint times are correctly NOT reported as concurrent.
    """

    vehicle_id: str
    delta: np.ndarray
    t_start: float
    t_end: float
    mass_moved_kg: float = 0.0

    def __post_init__(self) -> None:
        if self.t_end < self.t_start:
            raise ValueError(f"{self.vehicle_id}: t_end {self.t_end} < t_start {self.t_start}")
        d = np.asarray(self.delta, dtype=np.float64)
        if d.ndim != 2:
            raise ValueError(f"{self.vehicle_id}: delta must be a 2-D grid")
        if not np.all(np.isfinite(d)):
            raise ValueError(f"{self.vehicle_id}: delta must be finite (got NaN/Inf)")

    def touched(self, eps: float = 1e-9) -> np.ndarray:
        """Flat indices of the cells this action actually changed."""
        return np.flatnonzero(np.abs(np.asarray(self.delta, dtype=np.float64)) > eps)


def _windows_overlap(a: VehicleAction, b: VehicleAction) -> bool:
    """Half-open [t_start, t_end) overlap: touching endpoints are sequential, not concurrent."""
    return a.t_start < b.t_end and b.t_start < a.t_end


def detect_shared_cells(actions: list[VehicleAction], *, eps: float = 1e-9) -> dict:
    """Cell-level space-time conflict detection across vehicles on one shared grid.

    Unlike the site-level detector in ``lode.planner_multivehicle``, this cannot return zero by
    construction: it compares the cells each action actually touched. Returns a dict with

      ``pairs``            one entry per pair of DIFFERENT vehicles whose windows overlap AND whose
                           touched cells intersect, each with the shared flat indices
      ``correlated_cells`` the union of all shared indices -- the possible-dependency set
      ``n_correlated``     its size
      ``concurrent``       True iff any pair conflicts

    Two actions by the SAME vehicle are never a conflict with each other; a vehicle is sequential
    with itself by definition.
    """
    pairs = []
    union: set[int] = set()
    for i in range(len(actions)):
        for j in range(i + 1, len(actions)):
            a, b = actions[i], actions[j]
            if a.vehicle_id == b.vehicle_id or not _windows_overlap(a, b):
                continue
            shared = np.intersect1d(a.touched(eps), b.touched(eps), assume_unique=False)
            if shared.size:
                pairs.append({"a": a.vehicle_id, "b": b.vehicle_id,
                              "shared_idx": shared,
                              "n_shared": int(shared.size),
                              "overlap_window": (max(a.t_start, b.t_start), min(a.t_end, b.t_end))})
                union.update(int(k) for k in shared)
    idx = np.array(sorted(union), dtype=np.int64)
    return {"pairs": pairs, "correlated_cells": idx, "n_correlated": int(idx.size),
            "concurrent": bool(pairs)}


def apply_concurrent(memory: TerrainMemory, actions: list[VehicleAction], *,
                     mission: str) -> dict:
    """Apply several vehicles' actions to ONE shared TerrainMemory and report the dependency set.

    Each action is committed as its own versioned, hash-chained transaction (so P1 retention keeps
    each vehicle's contribution separately recoverable via ``delta_at``), in ascending ``t_start`` order
    so the provenance log reads chronologically. The returned ``conflicts`` is the cell-level
    detection above, computed BEFORE application so it describes the intent, not the residue.

    Returns {versions: {vehicle_id: version}, conflicts: <detect_shared_cells>, net_delta}.
    """
    if not actions:
        raise ValueError("apply_concurrent requires at least one action")
    shape = (memory.rows, memory.cols)
    for a in actions:
        if np.asarray(a.delta).shape != shape:
            raise ValueError(f"{a.vehicle_id}: delta shape {np.asarray(a.delta).shape} != site grid {shape}")

    conflicts = detect_shared_cells(actions)
    versions = {}
    for a in sorted(actions, key=lambda x: (x.t_start, x.vehicle_id)):
        versions[a.vehicle_id] = memory.apply(
            np.asarray(a.delta, dtype=np.float64),
            mission=f"{mission}:{a.vehicle_id}",
            mass_moved_kg=a.mass_moved_kg,
        )
    net = np.zeros(shape, dtype=np.float64)
    for a in actions:
        net += np.asarray(a.delta, dtype=np.float64)
    return {"versions": versions, "conflicts": conflicts, "net_delta": net}


def correlation_mask(memory: TerrainMemory, conflicts: dict) -> np.ndarray:
    """Legacy union mask of the action-derived possible-dependency set."""
    mask = np.zeros(memory.rows * memory.cols, dtype=bool)
    idx = conflicts.get("correlated_cells")
    if idx is not None and len(idx):
        mask[np.asarray(idx, dtype=np.int64)] = True
    return mask.reshape(memory.rows, memory.cols)


def source_dependency_edges(
    memory: TerrainMemory,
    conflicts: dict,
) -> dict[tuple[str, str], np.ndarray]:
    """Pairwise source-dependency masks derived from the action conflicts.

    The legacy ``correlation_mask`` retains only the union ``D``. That cannot
    distinguish a single dependent pair from all sources being dependent. This
    representation preserves the pair identities so a caller can compute
    connected components per cell and obtain

        m_eff,j = m_j^2 / sum_l q_l^2.

    Observation source IDs must match the vehicle IDs carried by the action
    history. Identity binding is a caller/pipeline responsibility; this function
    does not guess aliases.
    """
    shape = (memory.rows, memory.cols)
    n_cells = memory.rows * memory.cols
    edges: dict[tuple[str, str], np.ndarray] = {}
    for record in conflicts.get("pairs", []):
        a, b = str(record["a"]), str(record["b"])
        if a == b:
            raise ValueError(f"dependency self-edge is invalid ({a!r})")
        pair: tuple[str, str] = (a, b) if a < b else (b, a)
        mask = edges.setdefault(pair, np.zeros(n_cells, dtype=bool))
        idx = np.asarray(record.get("shared_idx", []), dtype=np.int64)
        if idx.size and (int(idx.min()) < 0 or int(idx.max()) >= n_cells):
            raise ValueError(f"dependency edge {pair!r} contains an out-of-grid cell")
        mask[idx] = True
    return {pair: mask.reshape(shape) for pair, mask in edges.items()}
