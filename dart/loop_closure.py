"""SLAM-loop: place-recognition / revisit detection + loop-closure factors for the SE(2) pose graph.

A loop closure is the constraint that the rover has RETURNED to a previously-mapped place: tying the
revisited keyframe back to the earlier one cancels the odometry drift that accumulated around the loop
(the SE(2) graph already fuses an arbitrary between-factor; PoseGraphSE2.add_between under the robust
kernel keeps a single bad closure from corrupting the loop -- audit M-01).

  * detect_revisits  -- the GEOMETRIC revisit gate: keyframe pairs (i, j) that are spatially within a
                        radius yet temporally distant (j - i >= a minimum index gap), one best (closest)
                        earlier match per j. This is the candidate generator.
  * relative_se2     -- the relative SE(2) transform of pose j expressed in pose i's frame (the form a
                        loop-closure measurement takes).
  * add_loop_closures-- inject the confirmed loop-closure between-factors into the graph.

HONESTY / GATED: detecting a revisit from POSITION proximity works only when the drift is small enough
that the revisit is still geometrically near; the appearance-based place recognition that confirms a
true revisit DESPITE large drift -- and supplies the relative relocalization measurement from the
rendered frames -- is the gated sensor-side input. This module is the structural loop-closure layer
that such a recognizer plugs into; it never fabricates a closure.
"""
from __future__ import annotations

import math

import numpy as np


def detect_revisits(positions, *, radius_m: float = 2.0, min_index_gap: int = 5):
    """Candidate loop closures from a keyframe POSITION stream.

    Returns a sorted list of ``(i, j)`` with ``i < j``, ``j - i >= min_index_gap`` and
    ``||pos[j] - pos[i]|| <= radius_m`` -- at most one pair per ``j`` (the closest qualifying earlier
    keyframe), so a single revisit yields a single closure rather than a cluster of redundant edges.
    """
    P = np.asarray(positions, float)
    if P.ndim != 2 or P.shape[1] != 2:
        raise ValueError(f"positions must be (N,2); got {P.shape}")
    out = []
    for j in range(P.shape[0]):
        best_i, best_d = None, radius_m
        for i in range(0, j - min_index_gap + 1):
            d = float(np.hypot(P[j, 0] - P[i, 0], P[j, 1] - P[i, 1]))
            if d <= best_d:
                best_i, best_d = i, d
        if best_i is not None:
            out.append((best_i, j))
    return out


def relative_se2(pose_i, pose_j):
    """The relative SE(2) transform of ``pose_j`` expressed in ``pose_i``'s frame: the (dx, dy, dyaw)
    such that composing it onto ``pose_i`` recovers ``pose_j``. Poses are (x, y, yaw)."""
    xi, yi, ti = float(pose_i[0]), float(pose_i[1]), float(pose_i[2])
    xj, yj, tj = float(pose_j[0]), float(pose_j[1]), float(pose_j[2])
    c, s = math.cos(ti), math.sin(ti)
    ddx, ddy = xj - xi, yj - yi
    dx = c * ddx + s * ddy            # rotate the world displacement into i's frame
    dy = -s * ddx + c * ddy
    dth = (tj - ti + math.pi) % (2 * math.pi) - math.pi
    return (dx, dy, dth)


def add_loop_closures(graph, loop_factors, *, sigma_xy: float = 0.3, sigma_yaw: float = 0.3) -> int:
    """Inject confirmed loop-closure between-factors into a PoseGraphSE2.

    ``loop_factors`` is an iterable of ``(i, j, meas)`` where ``meas`` is the relative SE(2) transform
    (dx, dy, dyaw) of keyframe j in keyframe i's frame (the place-recognition relocalization result).
    Returns the number of closures added.
    """
    n = 0
    for i, j, meas in loop_factors:
        graph.add_between(int(i), int(j), np.asarray(meas, float), sigma_xy=sigma_xy, sigma_yaw=sigma_yaw)
        n += 1
    return n
