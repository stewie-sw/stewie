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


#: SN-05: the separable illumination SUB-terms a route-cost breakdown reports, in `illumination_cost` order.
_ILLUM_SUBTERMS = ("shadow_hazard", "saturation", "map_uncertainty", "visibility")


def slope_costmap(Z, cell_m, *, max_slope_deg=25.0, slip_alpha=2.0, max_drop_m=None,
                  illum=None, illum_weight=1.0, map_unc=None, map_unc_weight=1.0, return_terms=False):
    """I10: per-cell traversal cost from terrain slope. cost = 1 + slip_alpha*tan(slope) (a slip-weighted
    per-meter multiplier — slope drives wheel slip, which costs energy/time); cells steeper than
    max_slope_deg are impassable hazards a rover can't safely traverse. When ``max_drop_m`` is set, cells
    overlooking a drop-off (negative_obstacle_mask) are ALSO impassable (the don't-fall-in-a-hole hazard,
    incl. the flat lip a slope cap misses). Returns (cost[H,W], passable bool).

    SN-05: ``illum`` is an OPTIONAL, SEPARABLE illumination route-cost layer (a crop-aligned (H, W)
    array, e.g. ``dart.illumination_cost.illumination_cost(...)['total']`` — itself a severity/weighted
    sum of inspectable shadow-hazard / saturation / map-uncertainty / visibility terms). When supplied it
    is ADDED to the slope cost as ``illum_weight*illum`` (the covariance/severity gain scaling its
    influence vs slip), so a route prefers lit, well-observed corridors. It is a SOFT cost, never a hard
    hazard — passability is untouched. ``illum=None`` (the default) leaves the costmap BYTE-IDENTICAL to
    the pre-SN-05 slope-only costmap, so illumination-aware routing is strictly opt-in.

    PM-08/09: ``map_unc`` is a second OPTIONAL, SEPARABLE layer — the per-cell RESIDUAL MAP UNCERTAINTY
    (a crop-aligned (H, W) field [m], e.g. the onboard-observability sigma where observed cells carry the
    onboard-stereo height sigma and unobserved cells the prior, the same residual the LAC map channel in
    ``dart.map_channel`` scores). When supplied it is ADDED as ``map_unc_weight*map_unc`` (the severity gain
    scaling its influence vs slip/illumination), so a route prefers WELL-OBSERVED, low-uncertainty cells. It
    is INDEPENDENT of ``illum`` (both layers compose additively, neither shadows the other) and, like
    ``illum``, a SOFT cost that never touches passability. ``map_unc=None`` (the default) leaves the costmap
    BYTE-IDENTICAL to the pre-PM-08/09 costmap, so map-uncertainty-aware routing is strictly opt-in."""
    smap = slope_deg_map(Z, cell_m)
    passable = smap <= max_slope_deg
    if max_drop_m is not None:
        passable = passable & ~negative_obstacle_mask(Z, max_drop_m=max_drop_m)
    slope_term = 1.0 + slip_alpha * np.tan(np.radians(np.minimum(smap, 89.0)))   # SN-05: slope/slip is its own term
    cost = slope_term
    # SN-05 inspectability: keep every route-cost layer as its OWN term so the route never fuses into a
    # black box. ``terms`` mirrors the fused cost: the weighted contributions SUM EXACTLY to ``cost``.
    terms = {"slope": slope_term}
    if illum is not None:                                  # SN-05: add the separable illumination term(s)
        if isinstance(illum, dict):
            # the FULL illumination_cost dict -> each SUB-term (shadow_hazard/saturation/map_uncertainty/
            # visibility) stays separately inspectable through the route; their weighted sum equals
            # illum_weight*total (so the fused cost is byte-identical to feeding the bare 'total' array).
            for name in _ILLUM_SUBTERMS:
                if name not in illum:
                    raise ValueError(f"illum dict missing the '{name}' sub-term")
            w = illum["weights"] if isinstance(illum.get("weights"), dict) else {}
            illum_total = np.zeros(cost.shape)
            for name in _ILLUM_SUBTERMS:
                layer = np.asarray(illum[name], float)
                if layer.shape != cost.shape:
                    raise ValueError(f"illum['{name}'] shape {layer.shape} must match the costmap shape {cost.shape}")
                wkey = "shadow" if name == "shadow_hazard" else name
                contrib = float(illum_weight) * float(w.get(wkey, 1.0)) * layer
                terms[name] = contrib
                illum_total = illum_total + contrib
            cost = cost + illum_total
        else:
            illum = np.asarray(illum, float)
            if illum.shape != cost.shape:
                raise ValueError(f"illum shape {illum.shape} must match the costmap shape {cost.shape}")
            illum_contrib = float(illum_weight) * illum
            terms["illum"] = illum_contrib
            cost = cost + illum_contrib
    if map_unc is not None:                                # PM-08/09: add the separable map-uncertainty term
        map_unc = np.asarray(map_unc, float)
        if map_unc.shape != cost.shape:
            raise ValueError(f"map_unc shape {map_unc.shape} must match the costmap shape {cost.shape}")
        map_unc_contrib = float(map_unc_weight) * map_unc
        terms["map_unc"] = map_unc_contrib
        cost = cost + map_unc_contrib
    if return_terms:
        return cost, passable, terms
    return cost, passable


def keepout_is_rect(k):
    """#178: a keep-out is an axis-aligned RECTANGLE if it carries corner bounds (x0,y0,x1,y1);
    otherwise it is the {x,y,r} CIRCLE. One predicate so the router raster and the build-on-obstacle
    conflict check classify shapes identically (they cannot diverge)."""
    return all(key in k for key in ("x0", "y0", "x1", "y1"))


def keepout_is_poly(k):
    """#178: a keep-out is a POLYGON if it carries a 'points' vertex list ([[x,y],...], >= 3); else
    a rectangle (x0,y0,x1,y1) or a circle (x,y,r)."""
    pts = k.get("points") if isinstance(k, dict) else None
    return isinstance(pts, (list, tuple)) and len(pts) >= 3


def _point_in_poly(x, y, pts):
    """Ray-casting (even-odd) point-in-polygon. pts = [[x,y],...] in the local order frame (or any
    affine image of it -- crop-cell coords work too, since point-in-polygon is affine-invariant)."""
    inside = False
    n = len(pts)
    j = n - 1
    for i in range(n):
        xi, yi = pts[i][0], pts[i][1]
        xj, yj = pts[j][0], pts[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def point_in_keepout(x, y, k):
    """#178: True if the LOCAL-frame point (x, y) [m] lies inside keep-out k -- a {points} polygon, a
    {x0,y0,x1,y1} rectangle, or the {x,y,r} circle. Single source for the build-on-obstacle check."""
    if keepout_is_poly(k):
        return _point_in_poly(x, y, k["points"])
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
        if keepout_is_poly(k):                             # #178 arbitrary polygon barrier
            # map vertices to crop-cell coords once, then rasterize via point-in-polygon over the bbox
            cells = [((ox + px) / cell_m - c0, (oy + py) / cell_m - r0) for px, py in k["points"]]
            cs = [c for c, _ in cells]; rs = [r for _, r in cells]
            c_lo, c_hi = max(0, int(min(cs))), min(W, int(max(cs)) + 1)
            r_lo, r_hi = max(0, int(min(rs))), min(H, int(max(rs)) + 1)
            for r in range(r_lo, r_hi):
                for c in range(c_lo, c_hi):
                    if _point_in_poly(c + 0.5, r + 0.5, cells):   # cell centre inside the polygon
                        passable[r, c] = False
            continue
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


def _crop_illum(illum_cost, r0, r1, c0, c1):
    """SN-05: crop the illumination route-cost layer(s) to the planner window. ``illum_cost`` is either a
    bare (H, W) ``total`` array OR the FULL ``illumination_cost`` dict (each sub-term a (H, W) array); a dict
    is cropped term-by-term so the per-term breakdown stays separately inspectable on the routed corridor."""
    if illum_cost is None:
        return None
    if isinstance(illum_cost, dict):
        out = {k: np.asarray(v, float)[r0:r1, c0:c1] for k, v in illum_cost.items() if k != "weights"}
        if "weights" in illum_cost:
            out["weights"] = illum_cost["weights"]
        return out
    return illum_cost[r0:r1, c0:c1]


def route_leg(dem, dem_origin, a_xy, b_xy, *, max_slope_deg=25.0, slip_alpha=2.0, margin_m=20.0,
              keepouts=(), illum_cost=None, illum_weight=1.0, map_unc_cost=None, map_unc_weight=1.0,
              return_terms=False):
    """I10: terrain-aware route between two LOCAL sites on the real DEM (anchored via dem_origin, M11).
    Crops the DEM to the two sites' bounding box + margin, builds a slope costmap, and routes a
    least-cost hazard-avoiding Dijkstra path. Returns (routed_m, grid_straight_m, reached, waypoints):
    routed_m is the path length, grid_straight_m the straight-line distance between the same DEM cells,
    and WAYPOINTS the terrain-following polyline as LOCAL (x, y) coords (preserved for Plan IR / 2D / 3D
    / playback -- NOT discarded). reached=False (waypoints []) when no safe corridor exists; the caller
    marks the plan infeasible rather than driving a straight line through the hazard.

    SN-05: ``illum_cost`` is an OPTIONAL DEM-aligned (same H, W as ``Z``) illumination route-cost field
    (e.g. ``dart.illumination_cost.illumination_cost(...)['total']`` rasterized onto the DEM grid). When
    supplied it is cropped to the same window as the slope costmap and ADDED as ``illum_weight*illum`` so
    the route prefers lit, well-observed corridors over shadowed ones. ``illum_cost=None`` (the default)
    leaves the route BYTE-IDENTICAL to the pre-SN-05 slope-only route -- illumination routing is opt-in.

    PM-08/09: ``map_unc_cost`` is a second OPTIONAL DEM-aligned (same H, W as ``Z``) field — the per-cell
    RESIDUAL MAP UNCERTAINTY [m] (e.g. the onboard-observability sigma the LAC map channel scores, observed
    cells low / unobserved cells the prior). Cropped to the same window and ADDED as
    ``map_unc_weight*map_unc`` so the route prefers WELL-OBSERVED, low-uncertainty corridors. Independent of
    ``illum_cost`` (both compose additively). ``map_unc_cost=None`` (the default) leaves the route
    BYTE-IDENTICAL to the pre-PM-08/09 route -- map-uncertainty routing is opt-in.

    SN-05 inspectability: ``illum_cost`` may be EITHER the bare ``total`` (H, W) array OR the FULL
    ``illumination_cost`` dict (the separable shadow_hazard / saturation / map_uncertainty / visibility
    sub-terms). Both produce the SAME route (the fused cost is identical). With ``return_terms=True`` the
    call returns a 5th element -- a per-term breakdown of the routed corridor: a dict mapping each cost
    term (``slope`` + each illumination sub-term + ``map_unc``) to a list of its per-waypoint cost, so the
    cockpit / mission report can show WHY the route costs what it does, term by term, never a fused number.
    ``return_terms=False`` (the default) keeps the original 4-tuple contract (no caller breakage)."""
    Z, cell = dem
    ox, oy = dem_origin
    ax, ay = ox + a_xy[0], oy + a_xy[1]
    bx, by = ox + b_xy[0], oy + b_xy[1]
    H, W = Z.shape
    if illum_cost is not None and not isinstance(illum_cost, dict):
        illum_cost = np.asarray(illum_cost, float)
        if illum_cost.shape != Z.shape:
            raise ValueError(f"illum_cost shape {illum_cost.shape} must match the DEM shape {Z.shape}")
    elif isinstance(illum_cost, dict):
        for k, v in illum_cost.items():
            if k == "weights":
                continue
            if np.asarray(v).shape != Z.shape:
                raise ValueError(f"illum_cost['{k}'] shape {np.asarray(v).shape} must match the DEM shape {Z.shape}")
    if map_unc_cost is not None:
        map_unc_cost = np.asarray(map_unc_cost, float)
        if map_unc_cost.shape != Z.shape:
            raise ValueError(f"map_unc_cost shape {map_unc_cost.shape} must match the DEM shape {Z.shape}")
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
            if return_terms:
                return straight, straight, False, [], {}
            return straight, straight, False, []
        crop = Z[r0:r1, c0:c1]
        illum_crop = _crop_illum(illum_cost, r0, r1, c0, c1)                   # SN-05: same window as the costmap
        map_unc_crop = None if map_unc_cost is None else map_unc_cost[r0:r1, c0:c1]   # PM-08/09: same window
        cost, passable, terms = slope_costmap(crop, cell, max_slope_deg=max_slope_deg, slip_alpha=slip_alpha,
                                              max_drop_m=MAX_DROP_M,   # routes also keep off drop-offs (don't fall in a hole)
                                              illum=illum_crop, illum_weight=illum_weight,
                                              map_unc=map_unc_crop, map_unc_weight=map_unc_weight,
                                              return_terms=True)
        _apply_keepouts(passable, cell, r0, c0, dem_origin, keepouts)   # discrete obstacles -> impassable cells
        hc, wc = crop.shape
        start = (min(max(int(ay / cell) - r0, 0), hc - 1), min(max(int(ax / cell) - c0, 0), wc - 1))
        goal = (min(max(int(by / cell) - r0, 0), hc - 1), min(max(int(bx / cell) - c0, 0), wc - 1))
        grid_straight = math.hypot((goal[1] - start[1]) * cell, (goal[0] - start[0]) * cell)
        path, length_m, reached = route_least_cost(cost, passable, cell, start, goal)
        if reached:
            # crop cell (r, c) -> world metres -> LOCAL (x, y) waypoint (local = world - origin)
            waypoints = [(((c0 + c) * cell) - ox, ((r0 + r) * cell) - oy) for (r, c) in path]
            if return_terms:
                # SN-05: per-term cost along the ACTUAL routed corridor, each term separately inspectable.
                breakdown = {name: [float(layer[r, c]) for (r, c) in path] for name, layer in terms.items()}
                return length_m, grid_straight, True, waypoints, breakdown
            return length_m, grid_straight, True, waypoints
        if c0 == 0 and c1 == W and r0 == 0 and r1 == H:  # already searched the whole DEM -> truly unreachable
            if return_terms:
                return straight, straight, False, [], {}
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


# FS-05: each navigation stage maps to a real seam (module.attr). keepouts ride route_leg's keepouts=
# arg (same module); the live Autoware/Nav2 planner binary is the external (gated) tier.
_NAV_STAGES = (
    ("global_route", "lode.planner_routing", "route_leg"),
    ("local_trajectory", "lode.local_planner", "plan_local"),
    ("tracker", "lode.local_planner", "track_plan"),
    ("recovery", "lode.recovery", "recovery_needed"),
    ("keepouts", "lode.planner_routing", "route_leg"),
    ("negative_obstacles", "lode.planner_routing", "negative_obstacle_mask"),
    ("illumination_risk", "dart.illumination", "incidence_angle_deg"),
    ("slip_energy_budget", "lode.mission_planner", "_simulate"),
    ("ros_action_lowering", "stewie.bridge.plan_lowering", "lower_plan_ir"),
)


def navigation_contract() -> dict:
    """FS-05: ONE auditable navigation contract -- the navigation stack's stages connected through a
    single descriptor, each naming its implementing seam and SELF-REPORTING whether that seam is
    importable on this host (no hard-coded presence: remove a stage and the contract flips it to
    present=False). Connects global route planning, local trajectory sampling, the tracker, recovery,
    keep-outs, negative obstacles, illumination risk, slip/energy budgets, and the NV-11 ROS2/Autoware
    action lowering. The live Autoware/Nav2 planner BINARY is the gated tier (present=False -- needs a
    ROS / Space ROS host); `on_host_complete` is true when every on-host stage is wired."""
    import importlib

    def _has(mod: str, attr: str) -> bool:
        try:                                               # the seam must resolve to a real CALLABLE entry
            return callable(getattr(importlib.import_module(mod), attr, None))   # point, not merely be importable
        except Exception:                                  # noqa: BLE001 -- a missing seam is reported, not raised
            return False

    stages = [{"stage": s, "seam": f"{m}.{a}", "present": _has(m, a)} for s, m, a in _NAV_STAGES]
    stages.append({"stage": "live_planner_binary", "seam": "Autoware/Nav2 (external ROS host)",
                   "present": False, "note": "gated: needs the live planner binary on a ROS / Space ROS host"})
    return {"version": "1.0", "stages": stages,
            "on_host_complete": all(s["present"] for s in stages if "note" not in s)}
