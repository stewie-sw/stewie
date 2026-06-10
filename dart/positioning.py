"""Multipoint triangulation and positioning (A4): fix a point from many rays, or fix the
rover from many known landmarks (by bearing = resection, or by distance = trilateration).

All least-squares, closed-form where possible; real geometry, no fabricated data.
"""
# PROVENANCE: SolNav dissertation (A. Storey) -- moved from solnav/slam/positioning.py, 2026-06-09 (M2)
from __future__ import annotations

import numpy as np


def multipoint_triangulate(centers, bearings_deg):
    """Least-squares 2D intersection of N rays (center p_i, world bearing b_i).
    Minimizes total squared perpendicular distance: (sum (I - d d^T)) x = sum (I - d d^T) p.
    Needs >= 2 non-parallel rays."""
    centers = np.asarray(centers, float)
    if len(centers) != len(np.atleast_1d(bearings_deg)):
        raise ValueError(f"centers ({len(centers)}) and bearings ({len(np.atleast_1d(bearings_deg))}) "
                         "must pair 1:1 -- refusing to silently drop measurements")
    A = np.zeros((2, 2)); b = np.zeros(2)
    for p, bd in zip(centers, np.radians(bearings_deg)):
        d = np.array([np.cos(bd), np.sin(bd)])
        P = np.eye(2) - np.outer(d, d)
        A += P; b += P @ p
    if abs(np.linalg.det(A)) < 1e-9:
        raise ValueError("degenerate (parallel) ray set; cannot triangulate")
    return np.linalg.solve(A, b)


def resect_position(known_points, world_bearings_deg):
    """Fix the rover's 2D position from world bearings to N known landmarks (resection):
    the rover lies on each back-bearing ray from the landmark, so triangulate those."""
    back = (np.asarray(world_bearings_deg, float) + 180.0)
    return multipoint_triangulate(known_points, back)


def trilaterate(known_points, ranges):
    """Fix the rover's 2D position from distances (ranges) to N>=3 known landmarks.
    Linear least-squares: 2 (P_i - P_0) . x = |P_i|^2 - |P_0|^2 - r_i^2 + r_0^2."""
    P = np.asarray(known_points, float); r = np.asarray(ranges, float)
    if len(P) < 3:
        raise ValueError("trilateration needs >= 3 landmarks")
    if len(P) != len(r):
        raise ValueError("known_points and ranges must have equal length")
    P0, r0 = P[0], r[0]
    A = 2.0 * (P[1:] - P0)
    if np.linalg.matrix_rank(A, tol=1e-9) < 2:
        raise ValueError("trilateration geometry is rank-deficient (collinear landmarks); "
                         "lstsq would return a min-norm (silently wrong) solution (HIGH-05)")
    bvec = (np.sum(P[1:]**2, axis=1) - np.sum(P0**2) - r[1:]**2 + r0**2)
    x, *_ = np.linalg.lstsq(A, bvec, rcond=None)
    return x


def triangulation_residual_m(estimate_xy, centers, bearings_deg):
    """RMS perpendicular distance of the estimate to the N rays (a consistency residual)."""
    centers = np.asarray(centers, float); x = np.asarray(estimate_xy, float)
    if len(centers) == 0:
        raise ValueError("residual of an empty ray set is undefined (was a silent NaN; audit L39)")
    if len(centers) != len(np.atleast_1d(bearings_deg)):
        raise ValueError("centers and bearings must pair 1:1 (audit L39)")
    d2 = []
    for p, bd in zip(centers, np.radians(bearings_deg)):
        d = np.array([np.cos(bd), np.sin(bd)])
        v = x - p
        perp = v - (v @ d) * d
        d2.append(perp @ perp)
    return float(np.sqrt(np.mean(d2)))
