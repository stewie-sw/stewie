"""TW-11 bridge: fold a completed SIM run's REAL drive telemetry into the per-site TrafficMemory.

This is the seam between the mission-execution output (`lode.autonomy.run_closed_loop`, which already
computes the true rover poses per leg) and the pure `stewie.twin.traffic_memory` accumulator. It lives in
the server layer (not in the twin) so the twin stays free of any lode/server import, exactly like the
terrain-memory fold in `routers/executive.py`.

The traffic grid is the FIXED per-site work-area crop (`gis_layers._work_area` -- the same 128x128 @ cell_m
frame every `/layers/raster` layer renders), so the traffic raster co-registers with the slope/hazard rasters
and every run accumulates into the ONE per-site TrafficMemory. Each driven leg becomes ONE idempotent
telemetry event keyed `mission_id:leg{i}`, so re-committing the same run cannot double-harden the road
(H-09). The per-wheel normal load is the REAL sourced IPEx static wheel load (dry 30 kg-class); CG/drum-fill
load transfer is a documented refinement, not a fabricated value.
"""
from __future__ import annotations

import hashlib

import numpy as np

from stewie.physics import terramechanics as tm
from stewie.twin import traffic_memory as TW
from stewie.twin.traffic_memory import TrafficMemory


def work_grid_frame(dem) -> tuple[int, int, int, int, float] | None:
    """The fixed per-site traffic grid frame from the site DEM: (r0, c0, rows, cols, cell_m) of the flattest-
    anchor work-area crop -- the SAME crop `gis_layers._work_area` renders, so the fold co-registers with the
    traffic raster. None if the DEM is absent."""
    from lode import mission_planner as MP
    base = dem[0] if isinstance(dem, tuple) else dem
    if base is None:
        return None
    base = np.asarray(base)
    cell_m = float(dem[1]) if (isinstance(dem, tuple) and len(dem) >= 2 and dem[1]) else 5.0
    ax, ay = MP.flattest_anchor((base, cell_m))
    half = 64                                            # 128x128 cells -> the work-area frame (matches _work_area)
    r0 = int(ay / cell_m); c0 = int(ax / cell_m)
    r0 = max(0, min(base.shape[0] - 2 * half, r0 - half))
    c0 = max(0, min(base.shape[1] - 2 * half, c0 - half))
    return r0, c0, 2 * half, 2 * half, cell_m


def _segment_cells(p0, p1, *, cell_m: float, r0: int, c0: int, rows: int, cols: int) -> set[tuple[int, int]]:
    """The crop-local (row, col) cells a straight drive from p0 to p1 (order-frame metres) crosses, sampled at
    half-cell spacing. Cells outside the crop are dropped (clipped, surfaced via the placed-cell count)."""
    x0, y0 = float(p0[0]), float(p0[1])
    x1, y1 = float(p1[0]), float(p1[1])
    dist = float(np.hypot(x1 - x0, y1 - y0))
    n = max(2, int(dist / (cell_m * 0.5)) + 1)
    cells: set[tuple[int, int]] = set()
    for t in np.linspace(0.0, 1.0, n):
        x = x0 + (x1 - x0) * t
        y = y0 + (y1 - y0) * t
        col = int(round(x / cell_m)) - c0                # x -> col, y -> row (the shared order-frame convention)
        row = int(round(y / cell_m)) - r0
        if 0 <= row < rows and 0 <= col < cols:
            cells.add((row, col))
    return cells


def traffic_from_run(out: dict, *, charger: tuple[float, float], dem, site: str,
                     data_dir: str, mission_id: str) -> TrafficMemory | None:
    """Fold a completed SIM run's executed drive path into the site's persistent TrafficMemory, and RETURN it
    (in memory, NOT yet saved) or None if nothing new hardened. The executed path is [charger] + each leg's
    TRUE pose (`out['legs'][i]['tx'/'ty']`), rasterized onto the fixed work-area crop; each leg is one
    idempotent event `mission_id:leg{i}`. Re-committing the same run advances no version (H-09 idempotence);
    a genuinely new mission accumulates. The per-wheel load is the real dry IPEx static wheel load."""
    legs = out.get("legs") if isinstance(out, dict) else None
    if not legs:
        return None
    frame = work_grid_frame(dem)
    if frame is None:
        return None
    r0, c0, rows, cols, cell_m = frame
    load = tm.static_wheel_load_n(payload_kg=0.0)         # REAL sourced dry IPEx per-wheel load [N]
    mem = TW.load_site(data_dir, site)
    if mem is None:
        mem = TrafficMemory(site=site, rows=rows, cols=cols, cell_m=cell_m,
                            origin=(c0 * cell_m, r0 * cell_m))
    before = mem.version
    path = [tuple(charger)] + [(float(l["tx"]), float(l["ty"])) for l in legs]
    for i in range(len(path) - 1):
        cells = _segment_cells(path[i], path[i + 1], cell_m=cell_m, r0=r0, c0=c0, rows=rows, cols=cols)
        if cells:
            mem.apply_path(cells, load, mission=str(mission_id), event_id=f"{mission_id}:leg{i}")
    if mem.version == before:
        return None                                       # idempotent re-commit or every pose off the crop
    return mem


def authority_sha(mem: TrafficMemory) -> str:
    """A content hash of the accumulator state -- the traffic authority id recorded into the DT-01 world log."""
    h = hashlib.sha256()
    h.update(np.asarray(mem._load_cycles, dtype=np.float64).tobytes())
    h.update(np.asarray(mem._peak_load, dtype=np.float64).tobytes())
    return h.hexdigest()
