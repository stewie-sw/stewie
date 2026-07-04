"""[REQ:BA-06] DEM <-> Godot heightfield interop (part of the BA-06 converter set).

A real DEM (metres, `<f4` heightmap) converts to a Godot-consumable heightfield -- a normalized float32 grid
in [0, 1] (the form a Godot terrain shader samples) plus a bounds sidecar (min/max height, cell size, dims,
frame). The DEM<->heightfield round-trip preserves the BOUNDS exactly (min/max/rows/cols/cell) and recovers the
metre heights within float quantization. Pure numpy; runs on-host (no Godot needed to produce the artifact --
Godot only consumes it).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import numpy as np


@dataclass
class GodotHeightfield:
    """A Godot terrain heightfield: `normalized` in [0, 1] (row 0 = north), un-scaled to metres by
    ``min_height_m + normalized * (max_height_m - min_height_m)``. `cell_m` is the ground sample distance."""
    normalized: np.ndarray
    min_height_m: float
    max_height_m: float
    cell_m: float
    frame_id: str


def dem_to_godot_heightfield(dem_m: np.ndarray, cell_m: float, frame_id: str = "map") -> GodotHeightfield:
    """Normalize a metres DEM to a [0, 1] Godot heightfield + record the bounds needed to un-scale it. A flat
    DEM (zero span) maps to all-zeros with min==max (still round-trips)."""
    dem = np.asarray(dem_m, dtype=np.float64)
    lo, hi = float(dem.min()), float(dem.max())
    span = hi - lo
    norm = ((dem - lo) / span) if span > 0.0 else np.zeros_like(dem)
    return GodotHeightfield(norm.astype(np.float32), lo, hi, float(cell_m), frame_id)


def godot_heightfield_to_dem(hf: GodotHeightfield) -> tuple[np.ndarray, float]:
    """Un-scale a Godot heightfield back to a metres DEM (the inverse of dem_to_godot_heightfield)."""
    span = hf.max_height_m - hf.min_height_m
    dem = hf.min_height_m + hf.normalized.astype(np.float64) * span
    return dem.astype(np.float32), hf.cell_m


def write_godot_heightfield(hf: GodotHeightfield, path_stem: str) -> tuple[str, str]:
    """Write ``<stem>.r32`` (normalized float32, Godot-importable) + ``<stem>.json`` (the bounds sidecar)."""
    r32, meta = path_stem + ".r32", path_stem + ".json"
    hf.normalized.astype("<f4").tofile(r32)
    with open(meta, "w") as f:
        json.dump({"min_height_m": hf.min_height_m, "max_height_m": hf.max_height_m, "cell_m": hf.cell_m,
                   "rows": int(hf.normalized.shape[0]), "cols": int(hf.normalized.shape[1]),
                   "frame_id": hf.frame_id}, f)
    return r32, meta


def read_godot_heightfield(path_stem: str) -> GodotHeightfield:
    """Read back a ``<stem>.r32`` + ``<stem>.json`` heightfield."""
    with open(path_stem + ".json") as f:
        m = json.load(f)
    norm = np.fromfile(path_stem + ".r32", dtype="<f4").reshape(m["rows"], m["cols"])
    if not os.path.getsize(path_stem + ".r32") == m["rows"] * m["cols"] * 4:
        raise ValueError("heightfield .r32 size does not match the sidecar dimensions")
    return GodotHeightfield(norm, float(m["min_height_m"]), float(m["max_height_m"]),
                            float(m["cell_m"]), str(m["frame_id"]))
