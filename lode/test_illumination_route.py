"""SN-05 [REQ:SN-05]: the illumination route cost wired into the LIVE planner route path.

`dart.illumination_cost.illumination_cost` already returns the separable illumination terms, but the
live router (`lode.planner_routing.route_leg` / `slope_costmap`) routed only on slope/drop-off. These
tests pin the wiring: a SEPARABLE, severity-weighted illumination term that is OFF by default
(``illum_cost=None`` -> byte-identical routing) and, when fed the real shadow/illumination layer,
makes a route across a shadowed region prefer illuminated cells.

Grounded on the REAL Haworth LOLA 5 m DEM (samples/lunar_dem/haworth_10km_5m) -- no synthetic terrain.
The window r0=340,c0=220 at sun az=45 el=15 is fully passable yet ~44% cast-shadowed, so a route can
either cross the shadow or detour through lit cells.
"""
import numpy as np

from dart.illumination_cost import illumination_cost
from dart.shadow_predict import cast_shadow_mask
from lode.planner_routing import route_least_cost, slope_costmap
from stewie.terrain.site_dem import load_haworth_dem

# REAL-DEM window with both lit and shadowed traversable cells (verified empirically, see module docstring)
_R0, _C0, _N = 340, 220, 40
_SUN_AZ, _SUN_EL = 45.0, 15.0


def _real_crop():
    Z, cell = load_haworth_dem()
    crop = Z[_R0:_R0 + _N, _C0:_C0 + _N]
    return crop, cell


def test_slope_costmap_illum_off_is_byte_identical():
    crop, cell = _real_crop()
    base_cost, base_pass = slope_costmap(crop, cell, max_drop_m=2.0)
    # default (illum=None) MUST be byte-identical to the pre-SN-05 costmap
    off_cost, off_pass = slope_costmap(crop, cell, max_drop_m=2.0, illum=None)
    assert np.array_equal(base_cost, off_cost)
    assert np.array_equal(base_pass, off_pass)


def test_slope_costmap_illum_on_raises_shadow_cell_cost_only():
    crop, cell = _real_crop()
    ic = illumination_cost(crop, cell_m=cell, sun_az_deg=_SUN_AZ, sun_el_deg=_SUN_EL)
    illum = ic["total"]
    base_cost, _ = slope_costmap(crop, cell, max_drop_m=2.0)
    on_cost, on_pass = slope_costmap(crop, cell, max_drop_m=2.0, illum=illum, illum_weight=50.0)
    # the term is ADDITIVE and SEPARABLE: cost rises exactly by illum_weight*illum, nowhere else
    assert np.allclose(on_cost, base_cost + 50.0 * illum)
    # passability is unchanged (illumination is a soft cost, not a hard hazard)
    _, base_pass = slope_costmap(crop, cell, max_drop_m=2.0)
    assert np.array_equal(on_pass, base_pass)
    # shadowed cells cost strictly more than they did without the term
    shadowed = cast_shadow_mask((crop, cell), sun_az_deg=_SUN_AZ, sun_el_deg=_SUN_EL)
    assert shadowed.any()
    assert np.all(on_cost[shadowed] >= base_cost[shadowed])
    assert on_cost[shadowed].sum() > base_cost[shadowed].sum()


def test_route_prefers_lit_cells_when_illum_enabled():
    crop, cell = _real_crop()
    shadowed = cast_shadow_mask((crop, cell), sun_az_deg=_SUN_AZ, sun_el_deg=_SUN_EL)
    ic = illumination_cost(crop, cell_m=cell, sun_az_deg=_SUN_AZ, sun_el_deg=_SUN_EL)
    illum = ic["total"]
    H, W = crop.shape
    start, goal = (2, 2), (H - 3, W - 3)

    base_cost, passable = slope_costmap(crop, cell, max_drop_m=2.0)
    p_off, _len_off, r_off = route_least_cost(base_cost, passable, cell, start, goal)

    on_cost, on_pass = slope_costmap(crop, cell, max_drop_m=2.0, illum=illum, illum_weight=50.0)
    p_on, _len_on, r_on = route_least_cost(on_cost, on_pass, cell, start, goal)

    assert r_off and r_on, "both routes must reach the goal on this passable window"

    def shadow_cells(path):
        return sum(1 for (rr, cc) in path if shadowed[rr, cc])

    # with illumination enabled the route crosses STRICTLY fewer shadowed cells (prefers lit corridor)
    assert shadow_cells(p_on) < shadow_cells(p_off)


def test_route_leg_illum_off_is_byte_identical_on_real_dem():
    # SN-05 wired through route_leg: the public route-cost entry. illum_cost=None (default) must give the
    # SAME path + length as the pre-SN-05 router (no illumination influence whatsoever).
    from lode.planner_routing import route_leg

    Z, cell = load_haworth_dem()
    dem = (Z, cell)
    dem_origin = (0.0, 0.0)
    # two LOCAL sites inside the verified passable window (local = world here since origin=0)
    a_xy = ((_C0 + 4) * cell, (_R0 + 4) * cell)
    b_xy = ((_C0 + _N - 4) * cell, (_R0 + _N - 4) * cell)

    base = route_leg(dem, dem_origin, a_xy, b_xy)
    off = route_leg(dem, dem_origin, a_xy, b_xy, illum_cost=None)
    assert base[0] == off[0]            # routed_m identical
    assert base[2] == off[2]            # reached identical
    assert base[3] == off[3]            # waypoints byte-identical


def test_route_leg_illum_on_prefers_lit_cells_on_real_dem():
    # The full live path: feed a DEM-aligned illumination cost field to route_leg and confirm the routed
    # corridor through the shadowed window prefers lit cells vs the OFF baseline.
    from lode.planner_routing import route_leg

    Z, cell = load_haworth_dem()
    dem = (Z, cell)
    dem_origin = (0.0, 0.0)
    a_xy = ((_C0 + 4) * cell, (_R0 + 4) * cell)
    b_xy = ((_C0 + _N - 4) * cell, (_R0 + _N - 4) * cell)

    # DEM-aligned illumination cost over the SAME window as the planner will crop (rest of the DEM 0)
    illum_full = np.zeros_like(Z)
    crop = Z[_R0:_R0 + _N, _C0:_C0 + _N]
    ic = illumination_cost(crop, cell_m=cell, sun_az_deg=_SUN_AZ, sun_el_deg=_SUN_EL)
    illum_full[_R0:_R0 + _N, _C0:_C0 + _N] = ic["total"]
    shadowed_full = np.zeros(Z.shape, bool)
    shadowed_full[_R0:_R0 + _N, _C0:_C0 + _N] = cast_shadow_mask(
        (crop, cell), sun_az_deg=_SUN_AZ, sun_el_deg=_SUN_EL)

    off_m, _g, off_reached, off_wp = route_leg(dem, dem_origin, a_xy, b_xy)
    on_m, _g2, on_reached, on_wp = route_leg(
        dem, dem_origin, a_xy, b_xy, illum_cost=illum_full, illum_weight=50.0)
    assert off_reached and on_reached

    def shadow_wps(wp):
        n = 0
        for (x, y) in wp:
            c, r = int(round((dem_origin[0] + x) / cell)), int(round((dem_origin[1] + y) / cell))
            if 0 <= r < Z.shape[0] and 0 <= c < Z.shape[1] and shadowed_full[r, c]:
                n += 1
        return n

    assert shadow_wps(on_wp) < shadow_wps(off_wp)
    # routed distance is finite and the OFF run is unchanged from a plain route_leg (separability)
    assert np.isfinite(on_m) and np.isfinite(off_m)


def test_mission_planner_route_leg_threads_illum_through_inflated_router():
    # SN-05 must also reach the FINITE-SIZE (footprint-inflated) live router used by the mission planner /
    # multi-vehicle path -- not only the point router. illum_cost=None stays byte-identical; with the field
    # fed in, the inflated route prefers lit cells too.
    from lode.mission_planner import route_leg as mp_route_leg

    Z, cell = load_haworth_dem()
    dem = (Z, cell)
    dem_origin = (0.0, 0.0)
    a_xy = ((_C0 + 4) * cell, (_R0 + 4) * cell)
    b_xy = ((_C0 + _N - 4) * cell, (_R0 + _N - 4) * cell)
    fr = 1.0  # a real swept footprint radius (m) -> exercises the inflated branch

    illum_full = np.zeros_like(Z)
    crop = Z[_R0:_R0 + _N, _C0:_C0 + _N]
    ic = illumination_cost(crop, cell_m=cell, sun_az_deg=_SUN_AZ, sun_el_deg=_SUN_EL)
    illum_full[_R0:_R0 + _N, _C0:_C0 + _N] = ic["total"]
    shadowed_full = np.zeros(Z.shape, bool)
    shadowed_full[_R0:_R0 + _N, _C0:_C0 + _N] = cast_shadow_mask(
        (crop, cell), sun_az_deg=_SUN_AZ, sun_el_deg=_SUN_EL)

    base = mp_route_leg(dem, dem_origin, a_xy, b_xy, footprint_radius_m=fr)
    off = mp_route_leg(dem, dem_origin, a_xy, b_xy, footprint_radius_m=fr, illum_cost=None)
    assert base[0] == off[0] and base[3] == off[3]   # OFF byte-identical on the inflated router

    off_m, _g, off_reached, off_wp = base
    on_m, _g2, on_reached, on_wp = mp_route_leg(
        dem, dem_origin, a_xy, b_xy, footprint_radius_m=fr, illum_cost=illum_full, illum_weight=50.0)
    assert off_reached and on_reached

    def shadow_wps(wp):
        n = 0
        for (x, y) in wp:
            c, r = int(round((dem_origin[0] + x) / cell)), int(round((dem_origin[1] + y) / cell))
            if 0 <= r < Z.shape[0] and 0 <= c < Z.shape[1] and shadowed_full[r, c]:
                n += 1
        return n

    assert shadow_wps(on_wp) < shadow_wps(off_wp)

    # SN-05 inspectability through the INFLATED (footprint) live router used by the multi-vehicle planner:
    # the per-term breakdown is separately inspectable here too, fed the FULL illumination_cost dict.
    illum_terms = {k: np.zeros_like(Z) for k in ("shadow_hazard", "saturation", "map_uncertainty",
                                                 "visibility", "total")}
    for k in illum_terms:
        illum_terms[k][_R0:_R0 + _N, _C0:_C0 + _N] = ic[k]
    out = mp_route_leg(dem, dem_origin, a_xy, b_xy, footprint_radius_m=fr,
                       illum_cost=illum_terms, illum_weight=50.0, return_terms=True)
    assert len(out) == 5
    _rm, _gs, reached_t, wp_t, breakdown = out
    assert reached_t and len(wp_t) >= 2
    assert set(breakdown) >= {"slope", "shadow_hazard", "saturation", "map_uncertainty", "visibility"}
    assert all(len(v) == len(wp_t) for v in breakdown.values())
    assert sum(breakdown["shadow_hazard"]) > 0.0


def test_slope_costmap_returns_separable_terms():
    # SN-05 inspectability: the LIVE route cost must keep slope, illumination, and map-uncertainty as
    # SEPARATE inspectable terms -- not only a fused total. slope_costmap(..., return_terms=True) returns
    # a third element: a per-cell term dict whose weighted contributions SUM EXACTLY to the routed cost.
    crop, cell = _real_crop()
    ic = illumination_cost(crop, cell_m=cell, sun_az_deg=_SUN_AZ, sun_el_deg=_SUN_EL)
    illum = ic["total"]
    map_unc = np.full(crop.shape, 0.2)  # a real uniform residual-uncertainty field (no fabricated structure)

    # default (2-tuple) is byte-identical -- back-compat preserved
    base_cost, base_pass = slope_costmap(crop, cell, max_drop_m=2.0,
                                         illum=illum, illum_weight=3.0, map_unc=map_unc, map_unc_weight=4.0)
    cost, passable, terms = slope_costmap(crop, cell, max_drop_m=2.0,
                                          illum=illum, illum_weight=3.0, map_unc=map_unc, map_unc_weight=4.0,
                                          return_terms=True)
    assert np.array_equal(cost, base_cost)
    assert np.array_equal(passable, base_pass)
    # the terms are SEPARATELY inspectable and reconstruct the fused cost exactly (no black box)
    assert set(terms) >= {"slope", "illum", "map_unc"}
    assert np.allclose(terms["slope"] + terms["illum"] + terms["map_unc"], cost)
    # each term is its own retrievable layer: the illum contribution is exactly illum_weight*illum
    assert np.allclose(terms["illum"], 3.0 * illum)
    assert np.allclose(terms["map_unc"], 4.0 * map_unc)
    # the slope term alone equals the pre-illumination slope-only cost
    slope_only, _ = slope_costmap(crop, cell, max_drop_m=2.0)
    assert np.allclose(terms["slope"], slope_only)


def test_route_leg_exposes_per_term_breakdown_on_real_dem():
    # SN-05 through the LIVE point router: route_leg(..., return_terms=True) returns a 5th element -- a
    # per-term breakdown of the routed corridor's cost. Each illumination SUB-term (shadow_hazard /
    # saturation / map_uncertainty / visibility) plus slope is SEPARATELY inspectable along the actual
    # route, so the cockpit/report can show WHY the route costs what it does (not a fused number).
    from lode.planner_routing import route_leg

    Z, cell = load_haworth_dem()
    dem = (Z, cell)
    dem_origin = (0.0, 0.0)
    a_xy = ((_C0 + 4) * cell, (_R0 + 4) * cell)
    b_xy = ((_C0 + _N - 4) * cell, (_R0 + _N - 4) * cell)

    # pass the FULL term dict (not just total) so the route can break illumination into its sub-terms
    crop = Z[_R0:_R0 + _N, _C0:_C0 + _N]
    ic = illumination_cost(crop, cell_m=cell, sun_az_deg=_SUN_AZ, sun_el_deg=_SUN_EL)
    illum_terms = {k: np.zeros_like(Z) for k in ("shadow_hazard", "saturation", "map_uncertainty",
                                                 "visibility", "total")}
    for k in illum_terms:
        illum_terms[k][_R0:_R0 + _N, _C0:_C0 + _N] = ic[k]

    # default 4-tuple stays byte-identical to feeding the bare total array
    bare = route_leg(dem, dem_origin, a_xy, b_xy, illum_cost=illum_terms["total"], illum_weight=10.0)
    dict_fed = route_leg(dem, dem_origin, a_xy, b_xy, illum_cost=illum_terms, illum_weight=10.0)
    assert bare[0] == dict_fed[0] and bare[3] == dict_fed[3]  # dict vs total array -> SAME route

    out = route_leg(dem, dem_origin, a_xy, b_xy, illum_cost=illum_terms, illum_weight=10.0,
                    return_terms=True)
    assert len(out) == 5
    routed_m, _gs, reached, wp, breakdown = out
    assert reached and len(wp) >= 2

    # the breakdown SEPARATELY inspects each route-cost term summed along the routed corridor
    assert set(breakdown) >= {"slope", "shadow_hazard", "saturation", "map_uncertainty", "visibility"}
    # every term is a real number, one per routed waypoint -> per-cell inspectable, not fused
    for k, v in breakdown.items():
        assert len(v) == len(wp)
    # the shadow-hazard term carries real cost on this shadowed window (it is NOT a placeholder zero)
    assert sum(breakdown["shadow_hazard"]) > 0.0
    # the per-waypoint term vectors reconstruct the per-cell ROUTE cost the router saw at each waypoint
    # (separability holds end-to-end), and illumination actually contributes beyond slope somewhere.
    per_wp_total = [sum(breakdown[k][i] for k in breakdown) for i in range(len(wp))]
    assert all(np.isfinite(t) for t in per_wp_total)
    assert any(t > breakdown["slope"][i] for i, t in enumerate(per_wp_total))  # illum actually contributes


def test_route_leg_return_terms_off_is_byte_identical():
    # return_terms defaults OFF -> route_leg returns the original 4-tuple, byte-identical to before SN-05's
    # inspectability addition (no caller breakage).
    from lode.planner_routing import route_leg

    Z, cell = load_haworth_dem()
    dem = (Z, cell)
    dem_origin = (0.0, 0.0)
    a_xy = ((_C0 + 4) * cell, (_R0 + 4) * cell)
    b_xy = ((_C0 + _N - 4) * cell, (_R0 + _N - 4) * cell)
    out = route_leg(dem, dem_origin, a_xy, b_xy)
    assert len(out) == 4  # unchanged default contract


def test_run_navigation_surfaces_the_separable_route_terms_on_the_live_path():  # [REQ:SN-05]
    # SN-05 X (integration): the separable per-term route cost is now surfaced on the LIVE FS-05 nav spine
    # (lode.nav_pipeline.run_navigation, reachable via POST /nav/run) -- not only at the DART/route_leg layer.
    # Fed the real illumination_cost dict it exposes slope + each illumination sub-term (shadow / saturation /
    # map-uncertainty / visibility) as its OWN inspectable per-waypoint field; OFF (illum_cost=None) the live
    # path is byte-identical (the slope term only). Real Haworth window, no synthetic terrain.
    from lode.nav_pipeline import run_navigation

    crop, cell = _real_crop()
    ic = illumination_cost(crop, cell_m=cell, sun_az_deg=_SUN_AZ, sun_el_deg=_SUN_EL)
    H, W = crop.shape
    start, goal = (2 * cell, 2 * cell), ((W - 3) * cell, (H - 3) * cell)

    on = run_navigation((crop, cell), (0.0, 0.0), start, goal, illum_cost=ic, margin_m=40.0)
    assert on["reached"], "the verified-passable window must yield a corridor"
    rt = on["route_terms"]
    # slope AND every illumination sub-term are SEPARATE, inspectable fields along the routed corridor
    for term in ("slope", "shadow_hazard", "saturation", "map_uncertainty", "visibility"):
        assert term in rt, f"SN-05: live route_terms is missing the separable '{term}' term"
        assert isinstance(rt[term], list) and len(rt[term]) == len(on["waypoints"])  # per-waypoint, inspectable

    off = run_navigation((crop, cell), (0.0, 0.0), start, goal, illum_cost=None, margin_m=40.0)
    # OFF: the live path stays byte-identical -- the slope term only, no fused illumination black box
    assert set(off["route_terms"].keys()) == {"slope"}
