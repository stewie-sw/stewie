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
