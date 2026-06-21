"""PM-08/09 [REQ:PM-08] [REQ:PM-09]: map-uncertainty route cost wired into the LIVE planner route path.

SN-05 added a separable, severity-weighted ILLUMINATION term to ``lode.planner_routing.slope_costmap`` /
``route_leg`` (OFF by default -> byte-identical). PM-08/09 adds the MAP-UNCERTAINTY term THE SAME WAY: a
separable, severity-weighted soft cost that, when enabled, makes a route prefer well-observed / low-residual-
uncertainty cells over poorly-mapped ones. ``map_unc=None`` / ``map_unc_cost=None`` (default) leaves the
costmap and route BYTE-IDENTICAL to the pre-PM-08/09 slope-only path.

The uncertainty is sourced from the REAL onboard-observability map field, not fabricated: a real
``dart.mapping.ElevationMap`` whose per-cell observation count comes from ``dart.map_channel.coverage_mask``
(which worksite cells a survey traverse's stations actually brought within sensor range), whose
``cell_uncertainty()`` gives the per-cell residual height sigma, with unobserved cells carrying the published
prior ``map_channel.PRIOR_SIGMA_M``. This is exactly the residual map uncertainty the LAC map channel scores.
The test traverse covers the worksite on a station grid but leaves a small COVERAGE GAP (a region the rover
never drove past) -> a real unobserved, high-uncertainty blob the planner can be biased to route around.

Grounded on the REAL Haworth LOLA 5 m DEM (samples/lunar_dem/haworth_10km_5m) -- no synthetic terrain. The
window r0=340,c0=220 is fully passable; the straight slope-only line between the two endpoints crosses the
unobserved coverage gap, while a short detour through observed cells avoids it.
"""
import numpy as np

from dart.map_channel import PRIOR_SIGMA_M, coverage_mask
from dart.mapping import ElevationMap
from lode.planner_routing import route_least_cost, slope_costmap
from stewie.terrain.site_dem import load_haworth_dem

# REAL-DEM window, fully passable on this tile
_R0, _C0, _N = 340, 220, 40
_ER = _N // 2                          # endpoint row (the straight line runs along it)


def _real_crop():
    Z, cell = load_haworth_dem()
    crop = Z[_R0:_R0 + _N, _C0:_C0 + _N]
    return crop, cell


def _real_map_uncertainty(crop, cell):
    """Per-cell residual map uncertainty [m] from the REAL onboard-observability field.

    A survey traverse covers the worksite on a station grid but skips a small central rectangle straddling
    the endpoint row -- a real COVERAGE GAP the rover never drove past. ``map_channel.coverage_mask`` marks
    which cells the visited stations observed; ``ElevationMap.cell_uncertainty`` gives the observed-cell
    height sigma, and the unobserved gap cells take the published prior sigma (``map_channel.PRIOR_SIGMA_M``).
    Returns (mu, observed) -- mu a finite (H, W) uncertainty field, observed the boolean coverage mask.
    """
    N = crop.shape[0]
    bbox = (0.0, 0.0, N * cell, N * cell)
    xs = np.linspace(0.0, N * cell, N)
    ys = np.linspace(0.0, N * cell, N)
    gx0, gx1 = (N // 2 - 4) * cell, (N // 2 + 4) * cell   # the coverage gap: central columns ...
    gy0, gy1 = _ER * cell, (_ER + 2) * cell               # ... over a 2-row band straddling the endpoint row
    stations = [(x, y) for y in ys for x in xs if not (gx0 <= x <= gx1 and gy0 <= y <= gy1)]
    observed = coverage_mask(bbox, cell, stations, sensor_radius_m=1.0 * cell)
    count = np.where(observed, 10, 0)
    em = ElevationMap(elevation=np.where(observed, float(np.nanmean(crop)), np.nan),
                      count=count, cell_m=cell, n_points=int(count.sum()), n_frames=len(stations))
    sigma, _n_eff = em.cell_uncertainty()                 # NaN on unobserved cells
    mu = np.where(np.isfinite(sigma), sigma, PRIOR_SIGMA_M)   # unobserved -> published prior uncertainty
    return mu, observed


def test_slope_costmap_map_unc_off_is_byte_identical():
    crop, cell = _real_crop()
    base_cost, base_pass = slope_costmap(crop, cell, max_drop_m=2.0)
    off_cost, off_pass = slope_costmap(crop, cell, max_drop_m=2.0, map_unc=None)
    assert np.array_equal(base_cost, off_cost)
    assert np.array_equal(base_pass, off_pass)


def test_slope_costmap_map_unc_on_raises_uncertain_cell_cost_only():
    crop, cell = _real_crop()
    mu, observed = _real_map_uncertainty(crop, cell)
    base_cost, base_pass = slope_costmap(crop, cell, max_drop_m=2.0)
    on_cost, on_pass = slope_costmap(crop, cell, max_drop_m=2.0, map_unc=mu, map_unc_weight=20.0)
    # ADDITIVE + SEPARABLE: cost rises exactly by map_unc_weight*mu, nowhere else
    assert np.allclose(on_cost, base_cost + 20.0 * mu)
    # passability untouched (a soft cost, not a hard hazard)
    assert np.array_equal(on_pass, base_pass)
    # the unobserved (high-uncertainty) gap cells cost strictly more than the well-observed cells
    assert observed.any() and (~observed).any()
    assert on_cost[~observed].mean() > on_cost[observed].mean()


def test_slope_costmap_map_unc_shape_mismatch_raises():
    crop, cell = _real_crop()
    bad = np.zeros((crop.shape[0] + 1, crop.shape[1]))
    try:
        slope_costmap(crop, cell, map_unc=bad)
    except ValueError:
        return
    raise AssertionError("map_unc with a mismatched shape must raise ValueError")


def test_route_prefers_low_uncertainty_cells_when_enabled():
    crop, cell = _real_crop()
    mu, observed = _real_map_uncertainty(crop, cell)
    H, W = crop.shape
    # endpoints in observed cells either side of the coverage gap; the slope-only straight line crosses
    # the gap, while a short detour through observed cells avoids it
    start, goal = (_ER, 2), (_ER, W - 3)

    base_cost, passable = slope_costmap(crop, cell, max_drop_m=2.0)
    p_off, _l_off, r_off = route_least_cost(base_cost, passable, cell, start, goal)

    on_cost, on_pass = slope_costmap(crop, cell, max_drop_m=2.0, map_unc=mu, map_unc_weight=50.0)
    p_on, _l_on, r_on = route_least_cost(on_cost, on_pass, cell, start, goal)

    assert r_off and r_on, "both routes must reach the goal on this passable window"

    def uncertain_cells(path):
        return sum(1 for (rr, cc) in path if not observed[rr, cc])

    # with the map-uncertainty term enabled the route crosses STRICTLY fewer poorly-mapped cells
    assert uncertain_cells(p_on) < uncertain_cells(p_off)


def test_route_leg_map_unc_off_is_byte_identical_on_real_dem():
    from lode.planner_routing import route_leg

    Z, cell = load_haworth_dem()
    dem = (Z, cell)
    dem_origin = (0.0, 0.0)
    a_xy = ((_C0 + 4) * cell, (_R0 + 4) * cell)
    b_xy = ((_C0 + _N - 4) * cell, (_R0 + _N - 4) * cell)

    base = route_leg(dem, dem_origin, a_xy, b_xy)
    off = route_leg(dem, dem_origin, a_xy, b_xy, map_unc_cost=None)
    assert base[0] == off[0]            # routed_m identical
    assert base[2] == off[2]            # reached identical
    assert base[3] == off[3]            # waypoints byte-identical


def test_route_leg_map_unc_on_prefers_low_uncertainty_cells_on_real_dem():
    from lode.planner_routing import route_leg

    Z, cell = load_haworth_dem()
    dem = (Z, cell)
    dem_origin = (0.0, 0.0)
    crop = Z[_R0:_R0 + _N, _C0:_C0 + _N]
    mu, observed = _real_map_uncertainty(crop, cell)

    # DEM-aligned uncertainty: the worksite window carries the real coverage field; the rest of the DEM is
    # genuinely unobserved too, so it carries the same prior uncertainty (honest, not zero-padded)
    mu_full = np.full_like(Z, PRIOR_SIGMA_M)
    mu_full[_R0:_R0 + _N, _C0:_C0 + _N] = mu
    observed_full = np.zeros(Z.shape, bool)
    observed_full[_R0:_R0 + _N, _C0:_C0 + _N] = observed

    # endpoints on the endpoint row either side of the gap; the straight line crosses the unobserved gap
    a_xy = ((_C0 + 2) * cell, (_R0 + _ER) * cell)
    b_xy = ((_C0 + _N - 3) * cell, (_R0 + _ER) * cell)

    off_m, _g, off_reached, off_wp = route_leg(dem, dem_origin, a_xy, b_xy)
    on_m, _g2, on_reached, on_wp = route_leg(
        dem, dem_origin, a_xy, b_xy, map_unc_cost=mu_full, map_unc_weight=50.0)
    assert off_reached and on_reached

    def uncertain_wps(wp):
        n = 0
        for (x, y) in wp:
            c, r = int(round((dem_origin[0] + x) / cell)), int(round((dem_origin[1] + y) / cell))
            if 0 <= r < Z.shape[0] and 0 <= c < Z.shape[1] and not observed_full[r, c]:
                n += 1
        return n

    assert uncertain_wps(on_wp) < uncertain_wps(off_wp)
    assert np.isfinite(on_m) and np.isfinite(off_m)


def test_mission_planner_route_leg_threads_map_unc_through_inflated_router():
    # PM-08/09 must also reach the FINITE-SIZE (footprint-inflated) live router used by the mission planner /
    # multi-vehicle path -- not only the point router. map_unc_cost=None stays byte-identical; with the field
    # fed in, the inflated route prefers low-uncertainty cells too.
    from lode.mission_planner import route_leg as mp_route_leg

    Z, cell = load_haworth_dem()
    dem = (Z, cell)
    dem_origin = (0.0, 0.0)
    crop = Z[_R0:_R0 + _N, _C0:_C0 + _N]
    mu, observed = _real_map_uncertainty(crop, cell)
    fr = 1.0  # a real swept footprint radius (m) -> exercises the inflated branch

    mu_full = np.full_like(Z, PRIOR_SIGMA_M)
    mu_full[_R0:_R0 + _N, _C0:_C0 + _N] = mu
    observed_full = np.zeros(Z.shape, bool)
    observed_full[_R0:_R0 + _N, _C0:_C0 + _N] = observed

    a_xy = ((_C0 + 2) * cell, (_R0 + _ER) * cell)
    b_xy = ((_C0 + _N - 3) * cell, (_R0 + _ER) * cell)

    base = mp_route_leg(dem, dem_origin, a_xy, b_xy, footprint_radius_m=fr)
    off = mp_route_leg(dem, dem_origin, a_xy, b_xy, footprint_radius_m=fr, map_unc_cost=None)
    assert base[0] == off[0] and base[3] == off[3]   # OFF byte-identical on the inflated router

    off_m, _g, off_reached, off_wp = base
    on_m, _g2, on_reached, on_wp = mp_route_leg(
        dem, dem_origin, a_xy, b_xy, footprint_radius_m=fr, map_unc_cost=mu_full, map_unc_weight=50.0)
    assert off_reached and on_reached

    def uncertain_wps(wp):
        n = 0
        for (x, y) in wp:
            c, r = int(round((dem_origin[0] + x) / cell)), int(round((dem_origin[1] + y) / cell))
            if 0 <= r < Z.shape[0] and 0 <= c < Z.shape[1] and not observed_full[r, c]:
                n += 1
        return n

    assert uncertain_wps(on_wp) < uncertain_wps(off_wp)


def test_map_unc_and_illum_compose_separably():
    # PM-08/09 stacks ON TOP OF SN-05: both terms are independent additive layers. Feeding both adds
    # exactly map_unc_weight*map_unc + illum_weight*illum to the slope cost, neither shadowing the other.
    from dart.illumination_cost import illumination_cost

    crop, cell = _real_crop()
    mu, _observed = _real_map_uncertainty(crop, cell)
    ic = illumination_cost(crop, cell_m=cell, sun_az_deg=45.0, sun_el_deg=15.0)
    illum = ic["total"]
    base_cost, _ = slope_costmap(crop, cell, max_drop_m=2.0)
    both, _ = slope_costmap(crop, cell, max_drop_m=2.0,
                            illum=illum, illum_weight=10.0, map_unc=mu, map_unc_weight=20.0)
    assert np.allclose(both, base_cost + 10.0 * illum + 20.0 * mu)
