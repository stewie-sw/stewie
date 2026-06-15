"""SLAM-loop: a place-recognition / revisit detector + loop-closure factors on the SE(2) pose graph.

detect_revisits flags keyframe pairs that are spatially close but temporally distant (the rover came
back); add_loop_closures injects the corresponding loop-closure between-factors so a confirmed revisit
bounds the accumulated odometry drift. The detector is the GEOMETRIC revisit gate (proximity in the
position stream); the appearance-based place recognition that confirms a true revisit DESPITE drift,
and supplies the relative relocalization measurement, is the gated sensor-side input.
"""
from __future__ import annotations

import math
import os

import numpy as np
import pytest

from dart import loop_closure as LC
from dart.pose_graph_se2 import PoseGraphSE2

_PART = "/mnt/projects/datasets/katwijk/Part1"


def test_detect_revisits_finds_the_start_return():
    # out-and-back along x: node 6 returns to the origin (node 0), node 5 to node 1, ...
    pos = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0), (2.0, 0.0), (1.0, 0.0), (0.0, 0.0)]
    rev = LC.detect_revisits(pos, radius_m=0.5, min_index_gap=4)
    assert (0, 6) in rev                              # the start revisit is detected
    for i, j in rev:
        assert j - i >= 4                             # temporally distant only
        assert np.hypot(pos[j][0] - pos[i][0], pos[j][1] - pos[i][1]) <= 0.5


def test_detect_revisits_ignores_a_straight_traverse():
    pos = [(float(k), 0.0) for k in range(10)]        # never returns -> no revisit
    assert LC.detect_revisits(pos, radius_m=0.5, min_index_gap=4) == []


def test_detect_revisits_excludes_consecutive_neighbours():
    # a tight cluster of consecutive frames must NOT count as a revisit (within the index gap)
    pos = [(0.0, 0.0), (0.1, 0.0), (0.2, 0.0), (0.1, 0.0), (0.0, 0.0)]
    assert LC.detect_revisits(pos, radius_m=0.5, min_index_gap=4) == [(0, 4)]


def test_relative_se2_round_trips_a_pose_pair():
    # j expressed in i's frame, then re-composed, recovers j
    pi, pj = (1.0, 2.0, math.radians(30)), (3.0, 5.0, math.radians(80))
    dx, dy, dth = LC.relative_se2(pi, pj)
    c, s = math.cos(pi[2]), math.sin(pi[2])
    xj = pi[0] + c * dx - s * dy
    yj = pi[1] + s * dx + c * dy
    assert xj == pytest.approx(pj[0]) and yj == pytest.approx(pj[1])
    assert (pi[2] + dth) == pytest.approx(pj[2])


def test_loop_closure_bounds_drift_on_a_closed_square():
    # truth: a 2 m square loop returning to the origin (node 4 == node 0)
    truth = {0: (0.0, 0.0), 1: (2.0, 0.0), 2: (2.0, 2.0), 3: (0.0, 2.0), 4: (0.0, 0.0)}
    # odometry over-rotates each 90 deg turn by 6 deg -> the dead-reckoned chain does NOT close
    drift = math.radians(6.0)

    def build(close_loop):
        g = PoseGraphSE2()
        g.add_prior(0, (0.0, 0.0, 0.0), sigma_xy=0.02, sigma_yaw=0.02)
        for k in range(4):
            g.add_between(k, k + 1, (2.0, 0.0, math.pi / 2 + drift), sigma_xy=0.1, sigma_yaw=0.1)
        if close_loop:
            # place recognition confirmed node 4 is back at node 0: the relative pose of 0 seen from 4
            LC.add_loop_closures(g, [(4, 0, (0.0, 0.0, 0.0))], sigma_xy=0.05, sigma_yaw=0.05)
        return g.optimize()

    open_est, closed_est = build(False), build(True)
    worst_open = max(np.hypot(open_est[k][0] - tx, open_est[k][1] - ty) for k, (tx, ty) in truth.items())
    worst_closed = max(np.hypot(closed_est[k][0] - tx, closed_est[k][1] - ty) for k, (tx, ty) in truth.items())
    assert worst_closed < worst_open, f"loop closure did not reduce drift ({worst_closed} >= {worst_open})"
    assert worst_closed < 0.5                          # the closed loop tracks the true square


def test_add_loop_closures_returns_count_and_adds_between_factors():
    g = PoseGraphSE2()
    g.add_prior(0, (0.0, 0.0, 0.0), sigma_xy=0.1, sigma_yaw=0.1)
    n = LC.add_loop_closures(g, [(0, 5, (0.0, 0.0, 0.0)), (1, 6, (0.1, 0.0, 0.0))],
                             sigma_xy=0.1, sigma_yaw=0.1)
    assert n == 2
    assert {0, 5, 6, 1}.issubset(g._ids)               # the loop-closure endpoints are now graph nodes


@pytest.mark.skipif(not os.path.isdir(_PART), reason="Katwijk not present")
def test_detect_revisits_on_real_katwijk_is_wellformed():
    from dart.integrated_slam import load_katwijk_arrays
    truth, _dr, _ty, _gy = load_katwijk_arrays(_PART)
    idx = np.linspace(0, len(truth) - 1, 60).astype(int)
    rev = LC.detect_revisits([tuple(truth[i]) for i in idx], radius_m=3.0, min_index_gap=8)
    assert isinstance(rev, list)                       # real-data smoke: runs + well-formed
    for i, j in rev:
        assert 0 <= i < j < 60 and j - i >= 8
