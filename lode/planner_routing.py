"""Terrain-aware haul routing for the mission planner (ARCH-2: extracted from lode.mission_planner).

I10: a straight cut<->fill line ignores craters and steep walls. These route hauls over a slope
costmap -- steeper ground costs more (slip), ground past the traverse limit or overlooking a drop-off
is impassable -- so a route bends around hazards instead of plowing through. Planning logic (lode
layer); reads slope from the conserved terrain via stewie.terrain.site_dem.
"""
from __future__ import annotations

import heapq
import math

import numpy as np

from stewie.terrain.site_dem import slope_deg_map


# ---- I10: hazard + slope/slip-aware haul routing on a DEM costmap -------------------------------
# A straight cut<->fill line ignores craters and steep walls. I10 routes hauls over a slope costmap:
# steeper ground costs more (slip -> more energy/time per meter) and ground past the traverse limit is
# an impassable hazard, so the route bends around craters instead of plowing through them.
_ROUTE_NB = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
             (-1, -1, math.sqrt(2)), (-1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)), (1, 1, math.sqrt(2))]


MAX_DROP_M = 2.0   # [ASSUMPTION] a per-cell downward step the rover must not drive off (cliff / crater-rim / pit edge)


def negative_obstacle_mask(Z, *, max_drop_m=MAX_DROP_M):
    """The "don't fall in a hole" hazard: cells overlooking a DROP-OFF — a 3x3-neighbourhood downward step
    greater than ``max_drop_m`` (a cliff / crater-rim / pit edge). OR'd into the costmap as impassable so
    routes keep OFF the edge. The distinct value over the slope cap is the **flat lip** at the top of a drop:
    that cell can be gentle (passable by slope) yet sit at the edge of a fall — this flags it. (On a coarse
    DEM a steep wall is also a drop, so the two overlap there; the sensor / sub-cell + enclosed-sink versions
    are PRD P16/P17.) Returns a boolean mask the size of ``Z``."""
    from scipy.ndimage import minimum_filter
    if max_drop_m is None or max_drop_m <= 0:
        return np.zeros(Z.shape, dtype=bool)
    nbr_min = minimum_filter(Z, size=3, mode="nearest")   # lowest height in the 3x3 neighbourhood
    return (Z - nbr_min) > float(max_drop_m)


def slope_costmap(Z, cell_m, *, max_slope_deg=25.0, slip_alpha=2.0, max_drop_m=None):
    """I10: per-cell traversal cost from terrain slope. cost = 1 + slip_alpha*tan(slope) (a slip-weighted
    per-meter multiplier — slope drives wheel slip, which costs energy/time); cells steeper than
    max_slope_deg are impassable hazards a rover can't safely traverse. When ``max_drop_m`` is set, cells
    overlooking a drop-off (negative_obstacle_mask) are ALSO impassable (the don't-fall-in-a-hole hazard,
    incl. the flat lip a slope cap misses). Returns (cost[H,W], passable bool)."""
    smap = slope_deg_map(Z, cell_m)
    passable = smap <= max_slope_deg
    if max_drop_m is not None:
        passable = passable & ~negative_obstacle_mask(Z, max_drop_m=max_drop_m)
    cost = 1.0 + slip_alpha * np.tan(np.radians(np.minimum(smap, 89.0)))
    return cost, passable


def keepout_is_rect(k):
    """#178: a keep-out is an axis-aligned RECTANGLE if it carries corner bounds (x0,y0,x1,y1);
    otherwise it is the {x,y,r} CIRCLE. One predicate so the router raster and the build-on-obstacle
    conflict check classify shapes identically (they cannot diverge)."""
    return all(key in k for key in ("x0", "y0", "x1", "y1"))


def point_in_keepout(x, y, k):
    """#178: True if the LOCAL-frame point (x, y) [m] lies inside keep-out k -- a {x0,y0,x1,y1}
    rectangle (the box barrier) or the {x,y,r} circle. Single source for the conflict check."""
    if keepout_is_rect(k):
        return (min(k["x0"], k["x1"]) <= x <= max(k["x0"], k["x1"]) and
                min(k["y0"], k["y1"]) <= y <= max(k["y0"], k["y1"]))
    return (x - k["x"]) ** 2 + (y - k["y"]) ** 2 <= k["r"] ** 2


def _apply_keepouts(passable, cell_m, r0, c0, dem_origin, keepouts):
    """Mark cells inside any keep-out impassable, in-place, on a cropped costmap. keepouts are {x,y,r}
    circles or {x0,y0,x1,y1} rectangles (#178) in the LOCAL order frame (metres); dem_origin maps that
    frame to DEM world metres. The crop starts at row r0/col c0. Reuses route_least_cost's existing
    impassable-avoidance -> hauls bend around either shape (the raster, not the Dijkstra, knows the shape)."""
    if not keepouts:
        return passable
    ox, oy = dem_origin
    H, W = passable.shape
    for k in keepouts:
        if keepout_is_rect(k):                             # #178 axis-aligned rectangular barrier
            x0, x1 = sorted((float(k["x0"]), float(k["x1"])))
            y0, y1 = sorted((float(k["y0"]), float(k["y1"])))
            c_lo, c_hi = max(0, int((ox + x0) / cell_m - c0)), min(W, int((ox + x1) / cell_m - c0) + 1)
            r_lo, r_hi = max(0, int((oy + y0) / cell_m - r0)), min(H, int((oy + y1) / cell_m - r0) + 1)
            if c_hi > c_lo and r_hi > r_lo:
                passable[r_lo:r_hi, c_lo:c_hi] = False
            continue
        kc = (ox + k["x"]) / cell_m - c0                   # keep-out centre in crop-cell coords
        kr = (oy + k["y"]) / cell_m - r0
        rad = k["r"] / cell_m
        c_lo, c_hi = max(0, int(kc - rad)), min(W, int(kc + rad) + 1)
        r_lo, r_hi = max(0, int(kr - rad)), min(H, int(kr + rad) + 1)
        for r in range(r_lo, r_hi):
            for c in range(c_lo, c_hi):
                if (r - kr) ** 2 + (c - kc) ** 2 <= rad * rad:
                    passable[r, c] = False
    return passable


def route_least_cost(cost, passable, cell_m, start_rc, goal_rc):
    """I10: least-(slip-weighted-)cost 8-connected path over a costmap, avoiding impassable cells (Dijkstra).
    Returns (path[list of (r,c)], geometric_length_m, reached). The slip-weighted cost drives the routing
    CHOICE (detour around hazards); the returned length is the geometric path distance used for the haul."""
    H, W = cost.shape
    sr, sc = int(start_rc[0]), int(start_rc[1])
    gr, gc = int(goal_rc[0]), int(goal_rc[1])
    if not (0 <= sr < H and 0 <= sc < W and 0 <= gr < H and 0 <= gc < W):
        return [], math.inf, False
    if not (passable[sr, sc] and passable[gr, gc]):
        return [], math.inf, False
    dist = np.full((H, W), math.inf)
    glen = np.full((H, W), math.inf)
    dist[sr, sc] = 0.0
    glen[sr, sc] = 0.0
    prev = {}
    pq = [(0.0, sr, sc)]
    while pq:
        d, r, c = heapq.heappop(pq)
        if d > dist[r, c]:
            continue
        if (r, c) == (gr, gc):
            break
        for dr, dc, seg in _ROUTE_NB:
            nr, nc = r + dr, c + dc
            if 0 <= nr < H and 0 <= nc < W and passable[nr, nc]:
                if dr != 0 and dc != 0 and not (passable[r + dr, c] and passable[r, c + dc]):
                    continue                              # H-04: no diagonal corner-cut between blocked orthogonals
                nd = d + seg * cell_m * 0.5 * (cost[r, c] + cost[nr, nc])
                if nd < dist[nr, nc]:
                    dist[nr, nc] = nd
                    glen[nr, nc] = glen[r, c] + seg * cell_m
                    prev[(nr, nc)] = (r, c)
                    heapq.heappush(pq, (nd, nr, nc))
    if not math.isfinite(dist[gr, gc]):
        return [], math.inf, False
    path = [(gr, gc)]
    while path[-1] != (sr, sc):
        path.append(prev[path[-1]])
    path.reverse()
    return path, float(glen[gr, gc]), True


def route_leg(dem, dem_origin, a_xy, b_xy, *, max_slope_deg=25.0, slip_alpha=2.0, margin_m=20.0,
              keepouts=()):
    """I10: terrain-aware route between two LOCAL sites on the real DEM (anchored via dem_origin, M11).
    Crops the DEM to the two sites' bounding box + margin, builds a slope costmap, and routes a
    least-cost hazard-avoiding Dijkstra path. Returns (routed_m, grid_straight_m, reached, waypoints):
    routed_m is the path length, grid_straight_m the straight-line distance between the same DEM cells,
    and WAYPOINTS the terrain-following polyline as LOCAL (x, y) coords (preserved for Plan IR / 2D / 3D
    / playback -- NOT discarded). reached=False (waypoints []) when no safe corridor exists; the caller
    marks the plan infeasible rather than driving a straight line through the hazard."""
    Z, cell = dem
    ox, oy = dem_origin
    ax, ay = ox + a_xy[0], oy + a_xy[1]
    bx, by = ox + b_xy[0], oy + b_xy[1]
    H, W = Z.shape
    straight = math.hypot(bx - ax, by - ay)
    # H-05: adaptive search window. A valid corridor can leave the endpoint bounding box by far more
    # than the initial margin, so when no route is found we DOUBLE the crop margin and retry, up to the
    # full DEM. Only when the window already spans the whole DEM and still finds nothing is the leg
    # unreachable -- the old fixed 20 m margin wrongly declared such detours unreachable.
    m = float(margin_m)
    while True:
        c0 = max(0, int((min(ax, bx) - m) / cell))
        c1 = min(W, int((max(ax, bx) + m) / cell) + 1)
        r0 = max(0, int((min(ay, by) - m) / cell))
        r1 = min(H, int((max(ay, by) + m) / cell) + 1)
        if c1 - c0 < 2 or r1 - r0 < 2:                   # sites off the DEM -> can't route
            return straight, straight, False, []
        crop = Z[r0:r1, c0:c1]
        cost, passable = slope_costmap(crop, cell, max_slope_deg=max_slope_deg, slip_alpha=slip_alpha,
                                       max_drop_m=MAX_DROP_M)   # routes also keep off drop-offs (don't fall in a hole)
        _apply_keepouts(passable, cell, r0, c0, dem_origin, keepouts)   # discrete obstacles -> impassable cells
        hc, wc = crop.shape
        start = (min(max(int(ay / cell) - r0, 0), hc - 1), min(max(int(ax / cell) - c0, 0), wc - 1))
        goal = (min(max(int(by / cell) - r0, 0), hc - 1), min(max(int(bx / cell) - c0, 0), wc - 1))
        grid_straight = math.hypot((goal[1] - start[1]) * cell, (goal[0] - start[0]) * cell)
        path, length_m, reached = route_least_cost(cost, passable, cell, start, goal)
        if reached:
            # crop cell (r, c) -> world metres -> LOCAL (x, y) waypoint (local = world - origin)
            waypoints = [(((c0 + c) * cell) - ox, ((r0 + r) * cell) - oy) for (r, c) in path]
            return length_m, grid_straight, True, waypoints
        if c0 == 0 and c1 == W and r0 == 0 and r1 == H:  # already searched the whole DEM -> truly unreachable
            return straight, straight, False, []
        m *= 2.0                                          # widen the window and retry (H-05 adaptive expansion)


def routed_distance(dem, dem_origin, a_xy, b_xy, *, max_slope_deg=25.0, slip_alpha=2.0, margin_m=20.0,
                    keepouts=()):
    """Backward-compatible distance-only view of route_leg (returns (routed_m, grid_straight_m, reached))."""
    routed_m, grid_straight_m, reached, _ = route_leg(
        dem, dem_origin, a_xy, b_xy, max_slope_deg=max_slope_deg, slip_alpha=slip_alpha,
        margin_m=margin_m, keepouts=keepouts)
    return routed_m, grid_straight_m, reached


def haul_elevation_gain_m(dem, dem_origin, a_xy, b_xy):
    """Net elevation change z(b) - z(a) [m] along a haul, read from the real DEM (anchored via dem_origin,
    M11). Positive = hauling uphill, which costs exact gravity work m*g*dh; <= 0 = downhill (no positive
    lift, and the rover does not regenerate going down). Returns 0.0 with no DEM or if a site is off-grid."""
    if dem is None:
        return 0.0
    Z, cell = dem
    ox, oy = dem_origin
    H, W = Z.shape

    def _z(x, y):
        c, r = int(round((ox + x) / cell)), int(round((oy + y) / cell))
        return float(Z[r, c]) if (0 <= r < H and 0 <= c < W) else None

    za, zb = _z(*a_xy), _z(*b_xy)
    return 0.0 if (za is None or zb is None) else (zb - za)


def haul_cumulative_ascent_m(dem, dem_origin, waypoints):
    """H-06: total POSITIVE elevation gain [m] summed along a routed haul polyline (LOCAL (x, y)
    waypoints), read from the real DEM (anchored via dem_origin, M11). A route that descends into a dip
    and climbs back to the same elevation still does gravity work on every climb -- m*g times THIS
    cumulative ascent -- where the net endpoint gain (haul_elevation_gain_m) would read 0. Descents do not
    regenerate (per the haul model). For a straight/monotonic leg this equals max(0, net gain). Returns
    0.0 with no DEM or fewer than two on-grid samples."""
    if dem is None or waypoints is None or len(waypoints) < 2:
        return 0.0
    Z, cell = dem
    ox, oy = dem_origin
    H, W = Z.shape
    zs = []
    for (x, y) in waypoints:
        c, r = int(round((ox + x) / cell)), int(round((oy + y) / cell))
        if 0 <= r < H and 0 <= c < W:
            zs.append(float(Z[r, c]))
    if len(zs) < 2:
        return 0.0
    return float(sum(max(0.0, zs[i + 1] - zs[i]) for i in range(len(zs) - 1)))
