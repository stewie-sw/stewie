"""ARCH-2 (#123): order-INDEPENDENT TRIP construction + haul energy + routing memo + precedence +
mission-clock windows, extracted from lode.mission_planner.

_build_trips lowers a mission's cut/fill/sinter/goto orders into the per-trip dig/haul/lift energy the
simulator and sequencer consume; _segmented_haul_energy integrates per-segment slip along a routed
polyline; _make_routes memoizes routed inter-site distance; trip_precedence / _precedence_is_feasible
lift + check order precedence; _window_gate gates an action against the mission-clock windows.

Imports the leaves directly (planner_constants, planner_endurance.slip_alpha_to_slip,
planner_routing.haul_*, planner_balance.balance, planner_model body/context helpers). The footprint-
inflating route_leg WRAPPER stays in the facade (lode.mission_planner); _build_trips / _make_routes pull
it via a DEFERRED import (call-time, no import-scope cycle) -- the same pattern planner_balance uses for
_d / _make_routes. mission_planner re-exports every name here, so the staying sim/sequencer code's
unqualified _build_trips / trip_precedence / _make_routes / _window_gate calls stay byte-identical.
"""
# PROVENANCE: STEWIE LODE subsystem (A. Storey)
from __future__ import annotations

import math

from stewie.specs import ipex_specs as S            # sinter-head power [CALIB]
from stewie.specs import constants as C              # SINTER_ENERGY_J_PER_KG + the SINTER_ENABLED gate
from lode.planner_constants import DIG_RATE_KG_S
from lode.planner_endurance import slip_alpha_to_slip
from lode.planner_routing import haul_cumulative_ascent_m, haul_elevation_gain_m
from lode.planner_balance import balance
from lode.planner_model import body_gravity, mission_soil_params, plan_context

SINTER_J_PER_KG = C.SINTER_ENERGY_J_PER_KG              # 0.92 MJ/kg [CALIB]
SINTER_POWER_W  = S.SINTER_HEAD_POWER_W                  # 1000 W [CALIB]
# P-04: OFFLOAD/placement model for IMPORTED fill. Imported regolith arrives from an external supply
# (a separate logistics chain, not modelled here as a coordinate); the rover only DEPOSITS it. Depositing
# discharges the drum at its material-handling throughput (DIG_RATE_KG_S, the same drum rate used to
# collect/deposit), and the placement ENERGY is the drum-discharge handling at the drive/handling power --
# NOT the in-situ DIG energy (~4151 J/kg), because no bank material is cut. This keeps import comparable
# to in-situ construction with the RIGHT physical process. [DERIVED from grounded drive power + dig rate.]
OFFLOAD_RATE_KG_S = DIG_RATE_KG_S                        # drum deposit throughput == its collect throughput


def _density_at(density_field, dem_origin, cell, x, y):
    """Per-cell regolith density [kg/m^3] at local (x, y) from the optional per-cell density field
    (mirrors the elevation sampler), or None when there is no field or the point is off-grid -- in which
    case the slip solve falls back to the uniform surface density (density_stiffening == 1). #242 1b:
    lets the planner's per-leg slip/sinkage/energy respond to a spatially-varying regolith density
    (a compacted trail, a soil zone) instead of assuming uniform ground. No new physics: the density
    only feeds the grounded density_stiffening relation already used by the simulator drive loop."""
    if density_field is None:
        return None
    ox, oy = dem_origin
    H, W = density_field.shape
    c = int(round((ox + x) / cell)); r = int(round((oy + y) / cell))
    return float(density_field[r, c]) if (0 <= r < H and 0 <= c < W) else None


def _segmented_haul_energy(dem, dem_origin, waypoints, *, loads, drum_kg, g, soil, drive_j_per_m,
                           rover_mass_kg, density_field=None):
    """P-05: drive ENERGY of a shuttle haul, integrated SEGMENT-BY-SEGMENT along the routed polyline,
    separately for the LOADED outbound leg (cut->fill, carrying ~drum_kg) and the EMPTY return
    (fill->cut). Each segment pays seg_len * drive_j_per_m / (1 - slip), where slip is solved from THAT
    segment's grade and the rover's weight on that leg (loaded vs empty). A route that climbs a ridge and
    descends back to the same elevation therefore costs real per-segment grade work -- the prior code used
    only the endpoint slope abs(dh)/leg and read ~0 grade for such a roller-coaster. Returns the total
    round-trip haul energy [J] over all `loads` shuttle cycles."""
    Z, cell = dem
    ox, oy = dem_origin
    H, W = Z.shape

    def _z(x, y):
        c, r = int(round((ox + x) / cell)), int(round((oy + y) / cell))
        return float(Z[r, c]) if (0 <= r < H and 0 <= c < W) else None

    # sample elevation at each waypoint; drop off-grid points (keep order).
    pts = []
    for (x, y) in waypoints:
        z = _z(x, y)
        if z is not None:
            pts.append((x, y, z))
    if len(pts) < 2:
        return None                                   # not enough on-grid samples -> caller falls back

    def _dir_energy(seq, payload_kg):
        """Energy [J] for ONE traversal of the polyline `seq` carrying `payload_kg` (per-segment slip)."""
        e = 0.0
        for (x0, y0, z0), (x1, y1, z1) in zip(seq, seq[1:]):
            seg_len = math.hypot(x1 - x0, y1 - y0)
            if seg_len <= 1e-9:
                continue
            slope_deg = math.degrees(math.atan2(abs(z1 - z0), seg_len))
            # #242 1b: sample the REAL per-cell density at the segment midpoint -- a compacted trail
            # (density up) stiffens bearing -> less sinkage -> less slip -> cheaper haul. None (no
            # field / off-grid) -> uniform surface density (byte-identical to before).
            rho = _density_at(density_field, dem_origin, cell, 0.5 * (x0 + x1), 0.5 * (y0 + y1))
            slip = slip_alpha_to_slip(slope_deg, payload_kg=payload_kg, g=g, params=soil,
                                      rover_mass_kg=rover_mass_kg, density=rho)
            e += seg_len * drive_j_per_m / (1.0 - slip)
        return e

    out_e = _dir_energy(pts, drum_kg)                 # loaded outbound (cut -> fill)
    back_e = _dir_energy(list(reversed(pts)), 0.0)    # empty return (fill -> cut)
    return (out_e + back_e) * loads


def _build_trips(mission, dem, dem_origin, max_traverse_slope_deg, density_field=None):
    """Order-INDEPENDENT trip construction: cut->fill flows (I10-routed haul + exact gravity lift) and
    sinters. Returns (trips, flows, surplus_kg, meta). meta carries the routing summary; trips carry the
    per-trip dig/haul/lift energy so any visit order can be simulated/scored downstream."""
    from lode.mission_planner import route_leg   # deferred: the footprint-inflating router wrapper (facade); no cycle
    rho = mission.density
    g = body_gravity(mission.body)                          # for haul lift energy (exact m*g*dh)
    _soil = mission_soil_params(mission)                    # soil model for the haul slip (soil override)
    ctx = plan_context(mission)                             # H-01: the SELECTED vehicle's energy/mass/drum
    drum_kg = ctx.drum_kg                                   # RB-05: the selected vehicle's per-cycle drum
    # P-03: routed, feasibility-aware allocation when a DEM is present (min-cost transport over the routed
    # cost matrix); straight-line nearest-first with no DEM (byte-identical to the prior behavior).
    flows, surplus_kg = balance(mission, dem=dem, dem_origin=dem_origin,
                                max_traverse_slope_deg=max_traverse_slope_deg)
    sinters = [o for o in mission.orders if o.kind == "sinter"]
    if sinters and not C.SINTER_ENABLED:
        raise RuntimeError(
            f"{len(sinters)} sinter order(s) present but sinter is GATED OFF for the IPEx baseline "
            "(drum excavator, no sinter tool; sinter energy ~14-20x the pack per kg). Enable a "
            "sinter-equipped variant via stewie.physics.constants.SINTER_ENABLED.")
    trips = []
    # S-3 path-first: goto waypoints become zero-mass VISIT trips; the auto-precedence chain
    # (mission_from_dict) keeps them in authored sequence through the sequencer.
    for o in mission.orders:
        if o.kind == "goto":
            trips.append(dict(kind="goto", site=(o.x, o.y), label=f"Waypoint: {o.action}",
                              mass=0.0, dig_e=0.0, dig_t=0.0, haul_m=0.0, haul_e=0.0,
                              lift_e=0.0, dest=(o.x, o.y), actions=frozenset({o.action})))
    straight_haul_m = 0.0; routed_haul_m = 0.0; blocked_legs = 0; leg_routes = []
    # P-04: per-kg offload (deposit) energy/time for imported fill -- drum-discharge handling at the
    # drive/handling power and the drum's deposit throughput, NOT the in-situ dig energy.
    offload_e_per_kg = ctx.drive_power_w / OFFLOAD_RATE_KG_S
    charger_xy = (float(mission.charger[0]), float(mission.charger[1]))
    for co, fo, mass, dist in flows:
        if co is None:
            # P-04: IMPORTED fill -- NO local excavation. dig_e/dig_t are ZERO (no in-situ cut). The only
            # local cost is depositing the delivered material (offload), tracked as offload_e/offload_t so
            # the import strategy is compared with the right physical process. import_kg is accounted
            # separately (deficit_kg) and never folded into the excavated cut_kg.
            # FEASIBILITY: an import must still be DELIVERED to the fill, which requires REACHING it. The
            # P-03 min-cost transport reclassifies an UNREACHABLE (enclosed) fill as unmet demand -> import;
            # without this delivery check that import silently masked an enclosed fill as feasible, so the
            # totals path disagreed with plan_ir (which catches it via the GoTo route). Route the delivery
            # from the base (charger): an unreachable fill is a blocked leg, exactly like a blocked cut->fill.
            if dem is not None:
                _il, _ib, reached_imp, _iw = route_leg(
                    dem, dem_origin, charger_xy, (fo.x, fo.y),
                    max_slope_deg=max_traverse_slope_deg, keepouts=mission.keepouts)
                if not reached_imp:
                    blocked_legs += 1                   # enclosed/stranded fill -> plan INFEASIBLE
                    leg_routes.append(dict(from_xy=charger_xy, to_xy=(fo.x, fo.y),
                                           waypoints=[], reached=False))
            trips.append(dict(kind="import", site=(fo.x, fo.y), label=f"Import fill: {fo.action}",
                              mass=mass, dig_e=0.0, dig_t=0.0,
                              offload_e=mass*offload_e_per_kg, offload_t=mass/OFFLOAD_RATE_KG_S,
                              haul_m=0.0, haul_e=0.0, lift_e=0.0, dest=(fo.x, fo.y),
                              actions=frozenset({fo.action}), shape=fo.shape))
        elif fo is None:
            # surplus (un-routed) cut mass: it is still EXCAVATED -- the dominant dig cost (4151 J/kg) must
            # enter the plan. Dig in place; the spoil-disposal haul to a dump is a separate unmodeled term
            # (no spoil-site coordinate to fabricate one), so haul/lift = 0 here.
            trips.append(dict(kind="dig", site=(co.x, co.y), label=f"Excavate spoil: {co.action}",
                              mass=mass, dig_e=mass*ctx.dig_j_per_kg, dig_t=mass/DIG_RATE_KG_S,
                              haul_m=0.0, haul_e=0.0, lift_e=0.0, dest=(co.x, co.y),
                              actions=frozenset({co.action}), shape=co.shape))
        else:
            loads = max(1, math.ceil(mass / drum_kg))
            leg = base = dist                           # one-way cut<->fill distance (straight line)
            waypoints = [(co.x, co.y), (fo.x, fo.y)]; reached = True   # no-DEM: straight line, no hazard model
            if dem is not None:
                leg, base, reached, waypoints = route_leg(dem, dem_origin, (co.x, co.y), (fo.x, fo.y),
                                                          max_slope_deg=max_traverse_slope_deg,
                                                          keepouts=mission.keepouts)
                if not reached:
                    blocked_legs += 1                   # no safe corridor -> plan INFEASIBLE (item 2)
                    waypoints = []                      # do NOT fabricate a straight line through the hazard
            leg_routes.append(dict(from_xy=(co.x, co.y), to_xy=(fo.x, fo.y),
                                   waypoints=[list(p) for p in waypoints], reached=reached))
            straight_haul_m += base; routed_haul_m += leg
            haul_m = 2 * leg * loads                    # shuttle: cut<->fill, one round trip per drum load
            dh = haul_elevation_gain_m(dem, dem_origin, (co.x, co.y), (fo.x, fo.y))
            # H-06: lift energy is the CUMULATIVE positive ascent along the ROUTED polyline, not the net
            # endpoint gain -- a route that dips and climbs back still does gravity work on every climb. For
            # a straight/monotonic leg (incl. the no-DEM case) this equals max(0, dh), so behavior is unchanged.
            ascent = (haul_cumulative_ascent_m(dem, dem_origin, waypoints)
                      if (dem is not None and reached and len(waypoints) >= 2) else max(0.0, dh))
            # #1 slip-loss: the wheel travels 1/(1-slip) per metre of ground on a slope, so the haul costs
            # more than flat 135 J/m. P-05: integrate slip SEGMENT-BY-SEGMENT along the routed polyline,
            # separately for the loaded outbound and the empty return -- a route that climbs and descends
            # back to the same elevation still pays per-segment grade (the prior endpoint-slope estimate read
            # ~0 grade for such a roller-coaster). Fall back to the endpoint estimate only with no routed
            # polyline (no-DEM straight line / blocked leg).
            seg_e = None
            if dem is not None and reached and len(waypoints) >= 2:
                seg_e = _segmented_haul_energy(dem, dem_origin, waypoints, loads=loads, drum_kg=drum_kg,
                                               g=g, soil=_soil, drive_j_per_m=ctx.drive_j_per_m,
                                               rover_mass_kg=ctx.rover_mass_kg, density_field=density_field)
            if seg_e is not None:
                haul_e = seg_e
            else:
                # endpoint-slope fallback (no-DEM straight line, or too few on-grid samples).
                slope_haul = math.degrees(math.atan2(abs(dh), leg)) if leg > 1e-9 else 0.0
                out_m = back_m = leg * loads          # loaded out + empty back (haul_m = 2*leg*loads)
                # #242 1b: per-leg density at the leg midpoint (None -> uniform surface density).
                rho_leg = (_density_at(density_field, dem_origin, dem[1],
                                       0.5 * (co.x + fo.x), 0.5 * (co.y + fo.y))
                           if dem is not None else None)
                slip_loaded = slip_alpha_to_slip(slope_haul, payload_kg=drum_kg, g=g, params=_soil,
                                                 rover_mass_kg=ctx.rover_mass_kg, density=rho_leg)
                slip_empty = slip_alpha_to_slip(slope_haul, payload_kg=0.0, g=g, params=_soil,
                                                rover_mass_kg=ctx.rover_mass_kg, density=rho_leg)
                haul_e = (out_m * ctx.drive_j_per_m / (1.0 - slip_loaded)
                          + back_m * ctx.drive_j_per_m / (1.0 - slip_empty))
            trips.append(dict(kind="cutfill", site=(co.x, co.y), label=f"{co.action} → {fo.action}",
                              mass=mass, dig_e=mass*ctx.dig_j_per_kg, dig_t=mass/DIG_RATE_KG_S,
                              haul_m=haul_m, haul_e=haul_e, lift_e=mass * g * ascent, dest=(fo.x, fo.y),
                              actions=frozenset({co.action, fo.action}), shape=co.shape))
    for o in sinters:
        m = o.mass_kg(rho)
        trips.append(dict(kind="sinter", site=(o.x, o.y), label=o.action, mass=m, lift_e=0.0,
                          sinter_e=m*SINTER_J_PER_KG, sinter_t=m*SINTER_J_PER_KG/SINTER_POWER_W,
                          dest=(o.x, o.y), actions=frozenset({o.action}), shape=o.shape))
    meta = dict(straight_haul_m=straight_haul_m, routed_haul_m=routed_haul_m, blocked_legs=blocked_legs,
                routed=dem is not None, traverse_cap_deg=float(max_traverse_slope_deg),
                routes=leg_routes, feasible=(blocked_legs == 0))   # item 1: route geometry; item 2: feasibility
    return trips, flows, surplus_kg, meta


def trip_precedence(trips, mission):
    """I9: lift the mission's order-level precedence (before_action -> after_action) to TRIP-index
    constraints (i, j): trip i must precede trip j. A trip 'touches' the actions of the orders it serves
    (a cut->fill trip touches both). Self-edges are dropped. Returns a list of (i, j)."""
    pairs = []
    for before, after in (mission.precedence or []):
        for i, ti in enumerate(trips):
            if before in ti["actions"]:
                for j, tj in enumerate(trips):
                    if i != j and after in tj["actions"]:
                        pairs.append((i, j))
    return sorted(set(pairs))


def _precedence_is_feasible(n, pairs):
    """AL2 guard: do the (i, j) 'trip i before trip j' constraints admit ANY valid ordering, or do they
    form a cycle (no build sequence can satisfy them)? Kahn topological sort over all n trips -- feasible
    iff every trip can be emitted. Returns True (acyclic / satisfiable) or False (cyclic / unsatisfiable)."""
    indeg = [0] * n
    succ = [[] for _ in range(n)]
    for i, j in pairs:
        succ[i].append(j)
        indeg[j] += 1
    queue = [k for k in range(n) if indeg[k] == 0]
    emitted = 0
    while queue:
        u = queue.pop()
        emitted += 1
        for v in succ[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                queue.append(v)
    return emitted == n


def _make_routes(mission, dem, dem_origin, max_traverse_slope_deg):
    """H-02: ONE memoized routed inter-site distance over the DEM. route_leg is called once per unique
    (unordered) leg and reused by every candidate order the optimizer scores, the timeline, and the report,
    so sequencing is optimized against the SAME geometry the executable Plan IR drives -- not straight
    lines. No DEM -> None (the simulator falls back to straight-line _d, byte-identical). An unreachable
    leg caches inf so the reserve-aware sim flags it infeasible, consistent with the routed Plan IR."""
    from lode.mission_planner import route_leg   # deferred: the footprint-inflating router wrapper (facade); no cycle
    if dem is None:
        return None
    cache: dict = {}

    def rd(a, b):
        a = (round(float(a[0]), 6), round(float(a[1]), 6))
        b = (round(float(b[0]), 6), round(float(b[1]), 6))
        if a == b:
            return 0.0
        key = (a, b) if a <= b else (b, a)                  # symmetric (Dijkstra over an undirected costmap)
        if key not in cache:
            rm, _gs, reached, _wp = route_leg(dem, dem_origin, a, b,
                                              max_slope_deg=max_traverse_slope_deg, keepouts=mission.keepouts)
            cache[key] = rm if reached else math.inf
        return cache[key]
    return rd


def _window_gate(windows, action_class, t):
    """EP-04: gate an action of `action_class` against the mission-clock windows.

    `windows` is None or {class: [[open_s, close_s], ...]} in mission-clock seconds. Returns
    (start_t, wait_s, reason): the time the action may START, the idle wait it incurs, and an
    infeasibility reason (or None). Falsy `windows` or a missing class key -> UNCONSTRAINED,
    (t, 0.0, None) -> byte-identical to an un-windowed plan. Otherwise the action may only run inside
    an allowed interval: already inside one -> run now (no wait); before the next -> idle to its open;
    past the last interval's close -> cannot run this mission (reason set, caller skips the action)."""
    if not windows:
        return t, 0.0, None
    intervals = windows.get(action_class)
    if not intervals:
        return t, 0.0, None
    for open_s, close_s in sorted((float(a), float(b)) for a, b in intervals):
        if t <= close_s:                                   # first interval not yet ended
            if t < open_s:
                return open_s, open_s - t, None            # idle until the window opens
            return t, 0.0, None                            # already inside this window
    return t, 0.0, f"{action_class} window closed (no allowed interval at or after t={t:.0f}s)"
