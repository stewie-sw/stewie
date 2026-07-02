"""NV-02 acceptance: the coverage-route generator (overlapping-loop / outward-spiral).

The point router (``planner_routing.route_leg``) drives the SHORTEST corridor between two sites -- it sweeps
a narrow band and never re-observes ground it already passed. A COVERAGE route instead promotes map coverage
and deliberate re-observation / loop closure: the NAVLAB26 outward-spiral / nested-grid-perimeter pattern the
Stanford LAC entry earns its accuracy with (dart.comparison.coverage_pattern_cost). These tests are the
V-column evidence for NV-02: on the REAL LOLA Haworth tile, the generated spiral's swept coverage EXCEEDS a
point-to-point route over the same region (scored with the map-channel coverage mask, dart.map_channel), and
its waypoints REVISIT at least one earlier region -- a loop-closure candidate the SLAM revisit gate
(dart.loop_closure.detect_revisits) picks up. No fabricated terrain: the DEM is the real Haworth bundle and
the worksite region is a mission INPUT (the flattest buildable anchor).
"""
from __future__ import annotations

import math

from dart.loop_closure import detect_revisits
from dart.map_channel import coverage_mask
from lode import mission_planner as MP
from lode.planner_routing import coverage_route_feasible, coverage_spiral_route


def _haworth_region(half_m=20.0):
    """A square worksite region centred on the flattest buildable anchor of the real Haworth tile."""
    dem = MP.load_haworth_dem()
    cx, cy = MP.flattest_anchor(dem)
    bbox = (cx - half_m, cy - half_m, cx + half_m, cy + half_m)
    return dem, bbox


def _straight_route(bbox, spacing_m):
    """The point-to-point baseline: the diagonal straight line across the region, sampled at ``spacing_m``."""
    x0, y0, x1, y1 = bbox
    dist = math.hypot(x1 - x0, y1 - y0)
    n = max(1, int(math.ceil(dist / spacing_m)))
    return [(x0 + (x1 - x0) * t / n, y0 + (y1 - y0) * t / n) for t in range(n + 1)]


def test_coverage_route_beats_point_to_point_and_closes_loops():  # [REQ:NV-02]
    swath = 5.0
    sensor_r = 5.0
    cell = 1.0
    dem, bbox = _haworth_region(half_m=20.0)

    spiral = coverage_spiral_route(bbox, swath_m=swath)
    straight = _straight_route(bbox, spacing_m=swath)

    # the spiral is an ORDERED route over the region, denser than the point-to-point baseline.
    assert len(spiral) > len(straight) >= 2

    # ---- (1) swept COVERAGE exceeds the point-to-point route (map-channel coverage mask) ----
    cov_spiral = float(coverage_mask(bbox, cell, spiral, sensor_r).mean())
    cov_straight = float(coverage_mask(bbox, cell, straight, sensor_r).mean())
    assert cov_spiral > cov_straight
    assert cov_spiral - cov_straight > 0.2         # a real coverage gain, not a rounding-edge difference
    assert cov_spiral > 0.9                         # the overlapping loops map essentially the whole region

    # ---- (2) the route REVISITS >= 1 earlier region (a loop-closure candidate) ----
    revisits = detect_revisits(spiral, radius_m=1.0, min_index_gap=5)
    assert len(revisits) >= 1
    # every revisit is a genuine return: temporally distant (>= the gap) yet spatially back within radius.
    for i, j in revisits:
        assert j - i >= 5
        pi, pj = spiral[i], spiral[j]
        assert math.hypot(pj[0] - pi[0], pj[1] - pi[1]) <= 1.0
    # the point-to-point route re-observes NOTHING (monotone, never returns) -> zero loop closures.
    assert detect_revisits(straight, radius_m=1.0, min_index_gap=5) == []


def test_coverage_route_feasibility_scored_on_real_haworth():  # [REQ:NV-02]
    # the route is scored on REAL Haworth terrain: feasibility comes from the SAME slope/drop-off costmap
    # the point router (route_leg) routes against, not a fabricated pass/fail.
    dem, bbox = _haworth_region(half_m=20.0)
    spiral = coverage_spiral_route(bbox, swath_m=5.0)
    frac, flags = coverage_route_feasible(spiral, dem, (0.0, 0.0))
    assert len(flags) == len(spiral)
    assert all(isinstance(f, bool) for f in flags)
    assert 0.0 < frac <= 1.0                         # a real passable fraction on the flattest buildable anchor


def test_loops_are_closed_and_overlap_by_the_swath():  # [REQ:NV-02]
    # the generator's contract: each nested loop is CLOSED (start == end -> a loop-closure candidate) and the
    # loops are spaced by the mapping swath so their sensor footprints OVERLAP (deliberate re-observation).
    bbox = (0.0, 0.0, 30.0, 30.0)
    swath = 5.0
    spiral = coverage_spiral_route(bbox, swath_m=swath)
    revisits = detect_revisits(spiral, radius_m=0.5, min_index_gap=4)
    assert len(revisits) >= 1                         # at least one closed loop is re-observed
    # a finer swath (more, tighter loops) is a strictly longer route than a coarse swath over the same region.
    fine = coverage_spiral_route(bbox, swath_m=2.5)
    assert len(fine) > len(spiral)
