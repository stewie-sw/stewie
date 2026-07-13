"""[REQ:] viz2 plan v4 Phase F — rock-hazard costmap + routes-around proof (F1/F2).

The 4-clause routes-around acceptance, on REAL data (the real 1 m Haworth SfS DEM + the real
spatial-k Golombek rockfield producer), gated on the pytest exit code:

  (a) the rock_hazard layer keys traversability on rock HEIGHT: a cell under an exposed-height-0.30 m
      rock is IMPASSABLE with reason ``rock_hazard``; a 0.05 m rock COSTS but PASSES (both below and
      above the IPEx traversable-rock limit OBSTACLE_HEIGHT_M = 0.075 m [SCHULER24]).
  (b) a rock CLUSTER placed across the straight cut->fill corridor makes ``mission_planner.plan()``
      DETOUR: the routed haul is LONGER with the rocks than without.
  (c) no cell of the planned route violates the rock_hazard IMPASSABLE mask (compose over the same
      clasts) -- the route bends around, never through, the blocked rock cells.
  (d) CONTROL: remove the cluster and the short (near-straight) route is restored -- the detour was
      caused by the rocks, not the terrain.
  (e) the REAL rockfield producer (stewie.terrain.rockfield over the real bundle) feeds the planner
      bridge: rock_keepouts extracts the impassable clasts as keep-out circles.

The flat real window (r0=1560, c0=0, 60x60: p98 slope 2.19 deg, max 5.55 deg, no >2 m drop-offs) is a
genuinely flat patch of the real LRO NAC SfS Haworth tile, so WITHOUT rocks the cut->fill route is
near-straight and the ONLY thing that can force a detour is the rock cluster (isolation by controlled
placement of REAL-height boulders on REAL terrain, the same controlled-fixture method
test_costmap_layers.py uses). No synthetic terrain.

Run: pytest lode/test_rock_hazard_routing.py  (gate on exit code).
"""
from __future__ import annotations

import math
import os

import numpy as np
import pytest

from lode import costmap_layers as cl
from lode import mission_planner as MP
from stewie.specs.ipex_specs import OBSTACLE_HEIGHT_M

_BUNDLE = os.path.join(os.path.dirname(__file__), "..", "samples", "lunar_dem", "haworth_sfs_2km_1m")
_FLAT = dict(r0=1560, c0=0, n=60)   # the flattest 60x60 window of the real 1 m Haworth tile


def _flat_window():
    """The real, flat Haworth SfS window (streamed from the on-disk bundle) + its cell size."""
    from stewie.terrain.site_dem import read_dem_window
    win, cell = read_dem_window(_FLAT["r0"], _FLAT["c0"], _FLAT["n"], _FLAT["n"], _BUNDLE)
    return np.asarray(win, dtype=float), float(cell)


def _clast(cx, cz, *, exposed_h, radius_m=0.6):
    """A clast at window-cell (row=cz, col=cx) whose EXPOSED height is exactly ``exposed_h`` [m].
    exposed_h = 2*radius*(1-buried_frac) -> buried_frac solves it for the given radius."""
    buried = 1.0 - exposed_h / (2.0 * radius_m)
    return {"id": 0, "center_m": [float(cx), 0.0, float(cz)], "radius_m": radius_m,
            "buried_frac": float(buried)}


def _leg_length(routes, a_xy, b_xy):
    """Sum the routed polyline length [m] of the cut->fill leg between local sites a_xy and b_xy."""
    for leg in routes:
        if (tuple(leg["from_xy"]) in (a_xy, b_xy)) and (tuple(leg["to_xy"]) in (a_xy, b_xy)):
            wp = leg["waypoints"]
            assert leg["reached"] and len(wp) >= 2, "leg not reached / no waypoints"
            return sum(math.hypot(wp[i + 1][0] - wp[i][0], wp[i + 1][1] - wp[i][1])
                       for i in range(len(wp) - 1)), wp
    raise AssertionError(f"no cut->fill leg between {a_xy} and {b_xy} in {[l['from_xy'] for l in routes]}")


def _plan_leg(Z, cell, keepouts, a_xy, b_xy):
    """Run mission_planner.plan() for a single cut->fill haul on the real DEM window, returning
    (leg_length_m, waypoints, haul_detour_frac). Balanced cut and fill masses -> one routed haul leg."""
    mission = MP.Mission(
        name="F2 rock-detour", body="moon", charger=(float(a_xy[0]), float(a_xy[1])),
        orders=[
            MP.BuildOrder("Excavate borrow", "cut", a_xy[0], a_xy[1], 16.0, 0.3, "4x4 m"),
            MP.BuildOrder("Build fill pad", "fill", b_xy[0], b_xy[1], 16.0, 0.3, "4x4 m"),
        ],
        keepouts=tuple(keepouts))
    res = MP.plan(mission, dem=(Z, cell), dem_origin=(0.0, 0.0), max_traverse_slope_deg=25.0)
    totals = res.totals
    length, wp = _leg_length(totals["routes"], tuple(a_xy), tuple(b_xy))
    return length, wp, float(totals["haul_detour_frac"])


@pytest.mark.skipif(not os.path.isdir(_BUNDLE), reason="Haworth 1 m bundle not present")
def test_a_rock_height_blocks_or_passes_by_obstacle_limit():
    """(a) rock HEIGHT drives traversability: 0.30 m rock blocks (reason rock_hazard), 0.05 m passes."""
    Z, cell = _flat_window()
    tall = _clast(20, 20, exposed_h=0.30)     # 0.30 m > 0.075 m -> impassable
    short = _clast(40, 40, exposed_h=0.05)    # 0.05 m < 0.075 m -> costs but passes
    out = cl.compose(cl.CostmapContext(Z=Z, cell_m=cell, sun_el_deg=80.0, rock_clasts=[tall, short]))
    # the tall rock's cell blocks and NAMES rock_hazard
    assert not out.passable[20, 20], "0.30 m rock cell should be impassable"
    assert cl.blocking_reason(out, (20, 20)) == "rock_hazard"
    assert "rock_hazard" in out.reason[~out.passable].tolist()
    # the short rock's cell is passable but costs more than the base per-metre cost
    assert out.passable[40, 40], "0.05 m rock cell should remain passable"
    assert float(out.cost[40, 40]) > 1.0, "a sub-limit rock still costs to cross"
    assert out.per_layer_cost["rock_hazard"] > 0.0


@pytest.mark.skipif(not os.path.isdir(_BUNDLE), reason="Haworth 1 m bundle not present")
def test_b_c_d_cluster_forces_detour_without_violation_and_control_restores():
    """(b) cluster forces a longer route, (c) no route cell violates the impassable mask, (d) removing
    the cluster restores the short route."""
    Z, cell = _flat_window()
    a_xy, b_xy = (10.0, 30.0), (50.0, 30.0)   # a horizontal corridor across the flat window

    # WITHOUT rocks: the near-straight baseline route on the real flat terrain.
    len0, wp0, detour0 = _plan_leg(Z, cell, (), a_xy, b_xy)

    # A wall of impassable boulders at col 30, rows 20..40 -> straddles the corridor (row 30).
    cluster = [_clast(30, row, exposed_h=1.2, radius_m=0.6) for row in range(20, 41)]
    keepouts = cl.rock_keepouts(cluster)
    assert len(keepouts) == len(cluster), "every 1.2 m boulder is impassable"

    # WITH rocks: the route must bend around the wall.
    len1, wp1, detour1 = _plan_leg(Z, cell, keepouts, a_xy, b_xy)

    # (b) the routed haul is longer WITH the rock cluster than without, and detours off the straight line.
    assert len1 > len0 + 1.0, f"cluster did not force a detour: with={len1:.2f} without={len0:.2f}"
    assert detour1 > detour0, f"haul_detour_frac did not rise with rocks: {detour1} vs {detour0}"

    # (c) no cell of the WITH-rocks route violates the rock_hazard impassable mask (compose, same clasts).
    mask = cl.compose(cl.CostmapContext(Z=Z, cell_m=cell, sun_el_deg=80.0, rock_clasts=cluster))
    impassable = ~mask.passable
    for (x, y) in wp1:
        r = min(max(int(round(y / cell)), 0), Z.shape[0] - 1)
        c = min(max(int(round(x / cell)), 0), Z.shape[1] - 1)
        assert not impassable[r, c], f"route cell (r={r}, c={c}) sits on an impassable rock cell"
        assert mask.reason[r, c] != "rock_hazard", f"route cell (r={r}, c={c}) is a rock_hazard block"

    # (d) CONTROL: remove the cluster -> the short route returns (== the no-rocks baseline).
    len_ctrl, _wpc, _dc = _plan_leg(Z, cell, (), a_xy, b_xy)
    assert len_ctrl == pytest.approx(len0), "removing the cluster must restore the baseline route"
    assert len1 > len_ctrl + 1.0, "the detour was caused by the rocks, not the terrain"


@pytest.mark.skipif(not os.path.isdir(_BUNDLE), reason="Haworth 1 m bundle not present")
def test_e_real_rockfield_feeds_the_planner_bridge():
    """(e) the REAL spatial-k Golombek rockfield producer over the real bundle feeds rock_keepouts:
    every extracted keep-out corresponds to a clast whose exposed height exceeds the obstacle limit."""
    from stewie.terrain import rockfield
    rf = rockfield.rock_field_for_dem_window(_BUNDLE, r0=800, c0=800, n=120, world_seed=0)
    clasts = rf["clasts"]
    assert len(clasts) > 0, "the real rockfield produced no clasts over the real window"
    kos = cl.rock_keepouts(clasts)
    assert 0 < len(kos) <= len(clasts), "rock_keepouts should extract the impassable subset"
    # every keep-out is a clast taller than the obstacle limit (the bridge's contract)
    impassable = [c for c in clasts if 2.0 * c["radius_m"] * (1.0 - c["buried_frac"]) > OBSTACLE_HEIGHT_M]
    assert len(kos) == len(impassable)
