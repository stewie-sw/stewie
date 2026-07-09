"""ARCH-2 #2: cut-fill MATERIAL BALANCE — route excavated regolith to fills, minimizing haul cost
(extracted from lode.mission_planner).

The solver pair that turns a set of CUT and FILL orders into mass flows:
  * ``_mincost_transport`` — a pure min-cost transportation solver (successive-cheapest-arc) over a
    bipartite cut->fill graph; no dependency on the planner core (only ``math``).
  * ``balance`` — wraps it with the bulking/swell density model and (with a DEM) a routed,
    feasibility-aware cost matrix; without a DEM it falls back to straight-line nearest-first.

``balance`` needs the planner core's routed-distance cache (``_make_routes``), the straight-line metric
(``_d``) and the ``Mission`` type. Those come from ``mission_planner`` via a DEFERRED (function-local)
import so this module imports first without a cycle (``mission_planner`` imports ``balance`` back, the
same lazy pattern used by ``mission_planner.run`` / ``__getattr__`` for ARCH-03). ``mission_planner``
re-exports ``balance`` / ``_mincost_transport`` / ``SWELL`` so ``MP.<name>`` call sites are unchanged.
"""
# PROVENANCE: STEWIE LODE subsystem (A. Storey)
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from stewie.specs import constants as C            # materials: bank/loose density for the swell ratio

if TYPE_CHECKING:                                    # static only -- never runs, so no runtime cycle
    from lode.mission_planner import Mission


# ---- cut-fill balance: route excavated material to fills, nearest-first ------------------------
# Bulking/swell (I7, planner side): a CUT excavates BANK (in-situ) material; a FILL places LOOSE spoil,
# which bulks. Mass is conserved: cut at rho_bank (the ACTUAL cut-cell in-situ density), fill at
# rho_loose = the body loose density (bodies.json). SWELL is the MAXIMUM bulking (deepest/compacted cut):
# rho_deep / rho_spoil ~1.477. Kept for the SWELL_FACTOR-tracking invariant + as the deep-cut bank ceiling.
SWELL = C.RHO_DEEP / C.RHO_SPOIL


def insitu_bank_density(depth_m, body_loose_density):
    """[task #78 Part C] Depth-averaged IN-SITU bank density [kg/m^3] of a cut column from the surface to
    ``depth_m``, on the loose-over-dense two-layer regolith profile (C.RHO_SURFACE over C.RHO_DEEP, transition
    at C.Z_T), scaled to the body's loose surface density ``body_loose_density``.

    A shallow cut (depth <= Z_T) excavates loose near-surface material (~body_loose_density, bulking ~1.0); a
    deep cut approaches the compacted ceiling (~body_loose_density * SWELL, bulking ~1.477). This replaces the
    flat ``body_loose_density * SWELL`` that costed EVERY cut at the deep RHO_DEEP density regardless of depth
    (so a shallow near-surface dig is no longer over-costed as deeply-buried, compacted regolith). For the
    Moon (body_loose_density == C.RHO_SURFACE) the scale factor is 1, so this returns the raw profile average.
    """
    d = max(0.0, float(depth_m))
    if d <= C.Z_T:
        avg = C.RHO_SURFACE                                      # entirely in the loose surface mantle
    else:
        avg = (C.RHO_SURFACE * C.Z_T + C.RHO_DEEP * (d - C.Z_T)) / d   # depth-averaged loose-over-dense
    return float(body_loose_density) * (avg / C.RHO_SURFACE)    # body-generic; == avg on the Moon


def cut_bank_density(order, body_loose_density):
    """The bank (in-situ) density [kg/m^3] to cost a CUT order at: the order's ACTUAL cut-cell density when
    the authority knows it (``order.insitu_density_kg_m3`` from the conserved column_state / a compacted cell
    / a DEM material sample), else the depth-averaged loose-over-dense profile (:func:`insitu_bank_density`)."""
    explicit = getattr(order, "insitu_density_kg_m3", None)
    if explicit is not None:
        return float(explicit)
    return insitu_bank_density(order.depth_m, body_loose_density)


def _mincost_transport(supplies, demands, cost):
    """P-03: min-cost transportation over a bipartite cut->fill graph by successive-cheapest-augmenting
    (SSP). `supplies[i]` = cut i bank mass, `demands[j]` = fill j loose mass, `cost[i][j]` = the per-unit
    haul cost (math.inf = UNREACHABLE, no arc). Returns flow[i][j] (mass cut i -> fill j) minimizing total
    cost while never routing over an unreachable arc. Demand left unmet (no feasible reachable supply) is
    returned as `unmet[j]`; supply left over as `leftover[i]`. Globally min-cost over the FEASIBLE arcs --
    it never prefers a cheaper-but-blocked donor (inf cost) over a feasible one, the P-03 fix."""
    nI, nJ = len(supplies), len(demands)
    flow = [[0.0] * nJ for _ in range(nI)]
    sup = list(supplies)
    dem = list(demands)
    # candidate arcs by increasing cost; SSP for a transportation problem with no negative costs reduces
    # to repeatedly pushing as much as possible along the globally cheapest residual arc (a min-cost flow
    # is optimal when augmenting along shortest residual paths; with a single bipartite layer + nonneg
    # costs the shortest residual path is the single cheapest remaining direct arc).
    arcs = sorted(((cost[i][j], i, j) for i in range(nI) for j in range(nJ)
                   if math.isfinite(cost[i][j])), key=lambda a: a[0])
    for c, i, j in arcs:
        if sup[i] <= 1e-9 or dem[j] <= 1e-9:
            continue
        push = min(sup[i], dem[j])
        flow[i][j] += push
        sup[i] -= push
        dem[j] -= push
    unmet = [d if d > 1e-9 else 0.0 for d in dem]
    leftover = [s if s > 1e-9 else 0.0 for s in sup]
    return flow, unmet, leftover


def balance(mission: "Mission", *, dem=None, dem_origin=(0.0, 0.0), max_traverse_slope_deg=25.0):
    """Cut-fill material balance: route excavated regolith to fills, minimizing haul cost.

    P-03: with a DEM, allocation solves a min-cost TRANSPORTATION problem over a ROUTED, FEASIBILITY-aware
    cost matrix (route_leg gives routed distance; an unreachable cut->fill pair is an infinite-cost arc with
    NO flow), so the planner never assigns a Euclidean-nearest donor that is actually blocked while a
    feasible donor exists. Without a DEM there is no terrain to route over, so it falls back to the
    straight-line nearest-first allocation (byte-identical to the prior behavior)."""
    # ARCH-2: the routed-distance cache + straight-line metric live in the planner core; pull them at call
    # time (deferred import) so this module imports without a cycle (mission_planner imports balance back).
    from lode.mission_planner import _d, _make_routes

    # task #78 Part C: cost each CUT at its ACTUAL in-situ bank density (per-cut, depth/authority-aware),
    # not a flat mission.density * SWELL that treats every cut as the deep RHO_DEEP density. Fills place LOOSE
    # spoil at the body loose density. Mass is conserved by the per-order densities.
    rho_loose = mission.density
    cuts = [(o, o.mass_kg(cut_bank_density(o, mission.density))) for o in mission.orders if o.kind == "cut"]
    fills = [(o, o.mass_kg(rho_loose)) for o in mission.orders if o.kind == "fill"]

    if dem is not None and cuts and fills:
        # P-03: routed, feasibility-aware min-cost allocation.
        rd = _make_routes(mission, dem, dem_origin, max_traverse_slope_deg)   # memoized routed inter-site dist
        cost = [[rd((co.x, co.y), (fo.x, fo.y)) for fo, _ in fills] for co, _ in cuts]
        flowm, unmet, leftover = _mincost_transport([m for _, m in cuts], [m for _, m in fills], cost)
        flows = []
        for i, (co, _) in enumerate(cuts):
            for j, (fo, _) in enumerate(fills):
                m = flowm[i][j]
                if m > 1e-6:
                    flows.append((co, fo, m, _d((co.x, co.y), (fo.x, fo.y))))
        for j, (fo, _) in enumerate(fills):
            if unmet[j] > 1e-6:
                flows.append((None, fo, unmet[j], 0.0))          # deficit: imported material (flagged)
        for i, (co, _) in enumerate(cuts):
            if leftover[i] > 1e-6:
                flows.append((co, None, leftover[i], 0.0))       # surplus spoil
        surplus_kg = sum(m for c, f, m, _ in flows if c is not None and f is None)
        return flows, surplus_kg

    # no DEM (or no cut/fill pair): straight-line nearest-first allocation (unchanged).
    supply = {id(o): m for o, m in cuts}
    flows = []                                          # (cut, fill, mass, dist)
    for fo, need in fills:
        rem = need
        for co, _ in sorted(cuts, key=lambda cm: _d((cm[0].x, cm[0].y), (fo.x, fo.y))):
            if rem <= 1e-6: break
            avail = supply[id(co)]
            if avail <= 1e-6: continue
            take = min(rem, avail)
            flows.append((co, fo, take, _d((co.x, co.y), (fo.x, fo.y))))
            supply[id(co)] -= take; rem -= take
        if rem > 1e-6:
            flows.append((None, fo, rem, 0.0))          # deficit: imported material (flagged)
    for co, _ in cuts:                                  # un-routed cut mass: excavated spoil (dug, then piled)
        rem = supply[id(co)]
        if rem > 1e-6:
            flows.append((co, None, rem, 0.0))          # surplus: (cut, None) spoil flow, symmetric to import
    surplus_kg = sum(m for c, f, m, _ in flows if c is not None and f is None)
    return flows, surplus_kg
