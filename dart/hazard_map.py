"""Local rock + height + slope HAZARD occupancy map for navigation -- the Stanford-LAC way.

The LAC-winning Stanford stack (Dai et al. 2025) drives over a 180x180 rock + height map: per-pixel
SEMANTIC rock segmentation projected into a local occupancy grid, fused with terrain height, planned over
with arc sampling + obstacle checks. This builds the equivalent navigation cost grid from the pieces we
have: the prior DEM (height + slope/roughness via dem_cross) fused with the perception's rock occupancy
(classified Rocks, or a dense semantic rock mask) into a per-cell TRAVERSAL COST. The planner routes over
it (the dense version of the discrete keep-outs in rock_costs). For navigation we want a rock MAP, not
per-boulder instance counts -- semantic occupancy is the right (LAC-validated) representation.
"""
# PROVENANCE: SolNav dissertation (A. Storey) -- moved from solnav/perception/hazard_map.py, 2026-06-09 (M2)
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

import numpy as np

from dart import dem_cross

from lode import rock_costs

_HARD = math.inf


@dataclass
class HazardMap:
    cost: np.ndarray            # (H, W) per-cell traversal cost; inf = no-go
    slope_deg: np.ndarray
    rock_cost: np.ndarray       # per-cell rock navigation penalty (inf where a hard D/E rock sits)
    cell_m: float
    origin: tuple = (0.0, 0.0)
    meta: dict = field(default_factory=dict)

    def world_to_rc(self, x, y):
        return (int(round((y - self.origin[1]) / self.cell_m)),
                int(round((x - self.origin[0]) / self.cell_m)))

    @property
    def traversable(self):
        return np.isfinite(self.cost)


def build_hazard_map(dem, dem_origin=(0.0, 0.0), *, rocks_world=(), rock_mask=None, zones=None,
                     max_slope_deg: float = 25.0, slope_hazard_deg: float = 15.0,
                     roughness_hazard_m: float = 0.10, hard_rock_inflate_cells: int = 1) -> HazardMap:
    """Build the navigation cost grid. cost = 1 (base) + slope penalty + roughness penalty + rock penalty;
    inf (no-go) where slope > max_slope OR a hard (D/E) rock sits. ``rocks_world`` = iterable of
    (x, y, Rock); ``rock_mask`` = optional dense semantic rock occupancy (same shape as the DEM, the
    Stanford per-pixel layer)."""
    rocks_world = list(rocks_world)
    layers = dem_cross.dem_layers(dem, dem_origin)
    slope = layers["slope_deg"]
    rough = layers["roughness_m"]
    h, w = slope.shape
    cost = np.ones((h, w), dtype=float)
    cost += np.clip((slope - slope_hazard_deg) / 10.0, 0, None)        # steeper -> costlier
    cost += np.clip((rough - roughness_hazard_m) / 0.1, 0, None) * 0.5
    cost[slope >= max_slope_deg] = _HARD                                # no-go: too steep
    cost[~np.isfinite(slope) | ~np.isfinite(rough)] = _HARD             # nodata = UNKNOWN -> no-go
    # (NaN comparisons are all False, so nodata cells previously scored as FLAT/traversable -- a
    # missed-obstacle false negative; audit M20)
    rock_cost = np.zeros((h, w), dtype=float)
    cell = layers["cell_m"]
    ox, oy = layers["origin"]
    for x, y, rk in rocks_world:
        c = int(round((x - ox) / cell)); r = int(round((y - oy) / cell))
        if 0 <= r < h and 0 <= c < w:
            pen = rock_costs.nav_cost(rk.nav_class)
            if rk.nav_class in rock_costs.HARD_CLASSES:                 # D/E -> hard no-go (+ inflate)
                r0, r1 = max(0, r - hard_rock_inflate_cells), min(h, r + hard_rock_inflate_cells + 1)
                c0, c1 = max(0, c - hard_rock_inflate_cells), min(w, c + hard_rock_inflate_cells + 1)
                rock_cost[r0:r1, c0:c1] = _HARD
            else:
                rock_cost[r, c] = max(rock_cost[r, c], pen)
    if rock_mask is not None:                                          # dense semantic occupancy (Stanford)
        rock_cost = np.where(np.asarray(rock_mask) > 0, np.maximum(rock_cost, 3.0), rock_cost)
    cost = np.where(np.isinf(rock_cost), _HARD, cost + rock_cost)
    n_zone = 0
    if zones is not None:                                              # HARD, non-overridable no-go zones
        rr = np.arange(h)[:, None]
        cc = np.arange(w)[None, :]
        for z in zones.zones:
            if not z.forbids_traverse:
                continue
            zr, zc = (z.y - oy) / cell, (z.x - ox) / cell
            cost[(rr - zr) ** 2 + (cc - zc) ** 2 <= (z.radius_m / cell) ** 2] = _HARD
            n_zone += 1
    return HazardMap(cost=cost, slope_deg=slope, rock_cost=rock_cost, cell_m=cell, origin=(ox, oy),
                     meta={"max_slope_deg": max_slope_deg, "n_rocks": len(rocks_world), "n_nogo_zones": n_zone})


def plan_route(hmap: HazardMap, start_xy, goal_xy):
    """Least-cost route over the hazard grid (8-connected Dijkstra). Returns world-xy waypoints
    (empty if no traversable corridor)."""
    cost = hmap.cost
    h, w = cost.shape
    s = hmap.world_to_rc(*start_xy)
    g = hmap.world_to_rc(*goal_xy)
    if not (0 <= s[0] < h and 0 <= s[1] < w and 0 <= g[0] < h and 0 <= g[1] < w):
        return []
    if not np.isfinite(cost[s]) or not np.isfinite(cost[g]):
        return []
    dist = np.full((h, w), math.inf)
    prev = {}
    dist[s] = 0.0
    pq = [(0.0, s)]
    nbrs = [(-1, 0, 1), (1, 0, 1), (0, -1, 1), (0, 1, 1),
            (-1, -1, 1.414), (-1, 1, 1.414), (1, -1, 1.414), (1, 1, 1.414)]
    while pq:
        d, (r, c) = heapq.heappop(pq)
        if (r, c) == g:
            break
        if d > dist[r, c]:
            continue
        for dr, dc, step in nbrs:
            nr, nc = r + dr, c + dc
            if 0 <= nr < h and 0 <= nc < w and np.isfinite(cost[nr, nc]):
                nd = d + step * 0.5 * (cost[r, c] + cost[nr, nc])
                if nd < dist[nr, nc]:
                    dist[nr, nc] = nd; prev[(nr, nc)] = (r, c); heapq.heappush(pq, (nd, (nr, nc)))
    if not np.isfinite(dist[g]):
        return []
    path = [g]
    while path[-1] != s:
        path.append(prev[path[-1]])
    path.reverse()
    return [((c * hmap.cell_m) + hmap.origin[0], (r * hmap.cell_m) + hmap.origin[1]) for r, c in path]
