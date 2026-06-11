"""SN-10: articulation-parallax triangulation (range + position fix from a commanded pose change).

A commanded posture change moves the camera by a KNOWN vertical baseline dh (forward kinematics,
posture_a3 / SN-08). A ground landmark at horizontal range R is seen at depression angle
theta = atan(h / R); raising the camera by dh increases that angle by a measurable d_theta. With dh
known, the range follows in closed form (no stereo pair, no drive baseline):

    tan(d_theta) (R^2 + h(h+dh)) = dh * R  ->  R = [dh + sqrt(dh^2 - 4 tan^2(d_theta) h(h+dh))] / (2 tan d_theta).

Shadow tips are the landmarks: high-contrast ground points, abundant at the pole. Ranges to >=2
known map landmarks then fix the rover (x, y) by trilateration -- from a STANDSTILL and HEADING-FREE,
where a static monocular camera gets only a bearing. The fix feeds the pose graph as an absolute
(x, y) factor. Pure geometry on the conserved articulation; no fabricated measurement.
"""
from __future__ import annotations

import math

import numpy as np


def depression_angle(h_m: float, range_m: float) -> float:
    """Depression angle [rad] of a ground landmark at horizontal range R seen from camera height h."""
    return math.atan2(float(h_m), float(range_m))


def range_from_vertical_parallax(h_m: float, dh_m: float, d_depression_rad: float) -> float:
    """Horizontal range to a ground landmark from a KNOWN vertical baseline dh and the observed
    depression-angle change d_depression (theta(h+dh) - theta(h) > 0). Exact closed form."""
    t = math.tan(float(d_depression_rad))
    if t <= 1e-12:
        return math.inf                                  # no parallax -> unbounded range
    a = h_m * (h_m + dh_m)
    disc = dh_m * dh_m - 4.0 * t * t * a
    if disc < 0.0:
        disc = 0.0                                       # grazing numerical edge
    return float((dh_m + math.sqrt(disc)) / (2.0 * t))   # the far (physical) root


def parallax_range_sigma(range_m: float, dh_m: float, sigma_theta_rad: float) -> float:
    """Range uncertainty from depression-angle measurement noise. From R ~ dh / d_theta the small-angle
    sensitivity is dR/d(theta) ~ -R^2/dh, so sigma_R ~ (R^2 / dh) * sigma_theta. Range error grows as
    R^2 and shrinks with a larger articulation baseline -- the honest geometry (far landmarks + small
    dh = poor range)."""
    return float((range_m ** 2 / max(1e-9, dh_m)) * sigma_theta_rad)


def position_fix_covariance(landmarks_xy, rover_xy, range_sigmas):
    """Trilateration position covariance (2x2) from per-landmark range sigmas: the inverse of the
    information sum over unit-bearing outer products, sum_i (u_i u_i^T) / sigma_Ri^2 (the GDOP form).
    More, closer, well-spread landmarks -> smaller covariance."""
    L = np.asarray(landmarks_xy, float)
    p = np.asarray(rover_xy, float)
    info = np.zeros((2, 2))
    for Li, s in zip(L, range_sigmas):
        d = p - Li
        n = np.hypot(d[0], d[1])
        if n < 1e-9:
            continue
        u = d / n                                        # unit bearing rover<-landmark
        info += np.outer(u, u) / max(1e-12, s * s)
    return np.linalg.inv(info + 1e-12 * np.eye(2))


def position_fix_sigma(landmarks_xy, rover_xy, *, dh_m, sigma_theta_rad) -> float:
    """The 1-sigma position-fix accuracy (RMS over x,y) for an articulation-parallax fix: derives each
    landmark range sigma from the geometry, then combines by trilateration. This is the sigma to feed
    the pose graph as an absolute-fix factor -- mechanistically grounded, not assumed."""
    L = np.asarray(landmarks_xy, float)
    p = np.asarray(rover_xy, float)
    ranges = np.hypot(*(p - L).T)
    sig = [parallax_range_sigma(r, dh_m, sigma_theta_rad) for r in ranges]
    cov = position_fix_covariance(L, p, sig)
    return float(np.sqrt(0.5 * np.trace(cov)))


def position_fix_from_ranges(landmarks_xy, ranges_m, *, guess=(0.0, 0.0), iters: int = 50) -> tuple:
    """Trilaterate the rover (x, y) from ranges to known landmarks (Gauss-Newton). Heading-free:
    ranges alone fix position, no orientation needed. Needs >= 2 landmarks (3 disambiguates)."""
    L = np.asarray(landmarks_xy, float)
    r = np.asarray(ranges_m, float)
    p = np.array(guess, float)
    for _ in range(iters):
        d = p - L                                        # (N,2)
        dist = np.hypot(d[:, 0], d[:, 1])
        dist = np.where(dist < 1e-9, 1e-9, dist)
        res = dist - r                                   # (N,)
        J = d / dist[:, None]                            # d(dist)/d(x,y)
        H = J.T @ J + 1e-9 * np.eye(2)
        step = np.linalg.solve(H, J.T @ res)
        p = p - step
        if np.linalg.norm(step) < 1e-10:
            break
    return float(p[0]), float(p[1])
