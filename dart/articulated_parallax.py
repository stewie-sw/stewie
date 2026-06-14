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
    if disc < -1e-9:
        return math.nan                                  # H-13: inconsistent geometry (d_theta too large for h,dh)
        #                                                  -> NOT a range; do not clamp to 0 and fabricate a root
    disc = max(0.0, disc)                                # a tiny grazing numerical edge clamps to 0
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


# --- pixel-domain parallax (what the camera actually measures) -----------------------------------
# A pinhole projects a ground point at depression theta to image row v = fx * tan(theta) = fx * h / R.
# A commanded camera lift dh therefore shifts that row by EXACTLY  dv = fx * dh / R  (the baseline h
# cancels), so the range is R = fx * dh / dv. fx is the documented lens focal length in pixels
# (ipex_specs.flight_fx_px). This is the camera-true form: we measure a PIXEL shift and convert.

def pixel_shift_for_range(dh_m: float, range_m: float, fx_px: float) -> float:
    """Forward model: the shadow-tip row shift [px] a landmark at range R undergoes for a camera lift dh."""
    return float(fx_px) * float(dh_m) / max(1e-9, float(range_m))


def range_from_pixel_parallax(dh_m: float, pixel_shift: float, fx_px: float) -> float:
    """Range [m] from a measured shadow-tip PIXEL shift and the known camera lift dh (pinhole-exact)."""
    if pixel_shift <= 0.0:
        return math.inf
    return float(fx_px) * float(dh_m) / float(pixel_shift)


def camera_resolvable_range_m(dh_m: float, fx_px: float, min_pixel_shift: float = 1.0) -> float:
    """The maximum landmark range whose shadow-tip shift still exceeds ``min_pixel_shift`` for a lift
    dh -- the camera-capability envelope (use min_pixel_shift<1 for sub-pixel edge localization)."""
    return float(fx_px) * float(dh_m) / max(1e-9, float(min_pixel_shift))


def range_sigma_from_pixel_noise(range_m: float, dh_m: float, fx_px: float, sigma_px: float) -> float:
    """Range uncertainty from shadow-tip localization noise [px]: sigma_R = R^2 / (fx * dh) * sigma_px
    (the pixel-domain form of parallax_range_sigma, with sigma_theta = sigma_px / fx)."""
    return float(range_m ** 2 / max(1e-9, fx_px * dh_m) * sigma_px)


def _landmarks_are_collinear(pts, tol: float = 1e-6) -> bool:
    """H-14: True if the landmarks span (essentially) a line -- their range trilateration is mirror-
    ambiguous (two reflected solutions). Fewer than 3 landmarks is inherently ambiguous."""
    P = np.asarray(pts, float)
    if len(P) < 3:
        return True
    C = P - P.mean(axis=0)
    return float(np.linalg.svd(C, compute_uv=False)[-1]) < tol   # smallest singular value ~ 0 -> on a line


def _reflect_across_baseline(p, a, b) -> tuple:
    """H-14: reflect point p across the line through landmarks a, b -- the SECOND (mirror) trilateration
    root that a near-prior Gauss-Newton solve silently discards."""
    a = np.asarray(a, float); b = np.asarray(b, float); p = np.asarray(p, float)
    d = b - a; dd = float(d @ d)
    if dd < 1e-18:
        return (float(p[0]), float(p[1]))
    foot = a + (float((p - a) @ d) / dd) * d
    r = 2.0 * foot - p
    return (float(r[0]), float(r[1]))


def articulation_localize(graph, node_id, landmarks_xy, pixel_shifts, *, dh_m, fx_px, sigma_px=0.3):
    """Tie SN-10 into the estimator: from the shadow-tip PIXEL shifts observed under a commanded lift
    dh, triangulate landmark ranges, fix the rover (x,y), and inject it into the live PoseGraphSE2 as
    an ABSOLUTE factor with the geometry-DERIVED covariance (not assumed). Returns the re-optimized
    estimate. This is how a standstill parallax maneuver becomes a live localization update. H-14: the
    result carries `ambiguous` + both `hypotheses` when < 3 non-collinear landmarks survive (a mirror
    pair); a >= 3 non-collinear fix is unique (ambiguous False)."""
    cur = graph.optimize()
    guess = cur[node_id][:2] if node_id in cur else (0.0, 0.0)
    ranges = [range_from_pixel_parallax(dh_m, s, fx_px) for s in pixel_shifts]
    # H-13: a non-positive pixel shift (inf range) or inconsistent geometry (nan) is NOT a measurement --
    # reject it and its landmark; never inject a fabricated/non-finite range into the graph.
    keep = [(Lxy, r) for Lxy, r in zip(landmarks_xy, ranges) if math.isfinite(r) and r > 0.0]
    if len(keep) < 2:
        raise ValueError(
            f"articulation parallax: only {len(keep)} finite range(s) from {len(ranges)} landmark(s) "
            "(non-positive pixel shift or inconsistent geometry); need >= 2 for a heading-free fix")
    vL = [Lxy for Lxy, _ in keep]
    ranges = [r for _, r in keep]
    fix_xy = position_fix_from_ranges(vL, ranges, guess=guess)
    # H-14: with < 3 non-collinear landmarks the two range circles give TWO mirror solutions and the
    # near-prior Gauss-Newton silently returns one. Flag the ambiguity and surface BOTH hypotheses
    # (reflected across the landmark baseline) instead of presenting a unique fix; >= 3 non-collinear -> unique.
    ambiguous = _landmarks_are_collinear(vL)
    hypotheses = [fix_xy, _reflect_across_baseline(fix_xy, vL[0], vL[1])] if ambiguous else [fix_xy]
    sig = [range_sigma_from_pixel_noise(r, dh_m, fx_px, sigma_px) for r in ranges]
    cov = position_fix_covariance(vL, fix_xy, sig)
    pos_sigma = float(np.sqrt(0.5 * np.trace(cov)))
    # H-30: inject the FULL 2x2 covariance (keeping the GDOP direction), not a collapsed scalar sigma -- an
    # elongated fix (far/poorly-spread landmarks) is uncertain ALONG the weak axis, not equally in all
    # directions. The graph weights the fix by the anisotropic information matrix.
    graph.add_absolute_cov(node_id, fix_xy, cov)
    out = graph.optimize_with_cov()
    return {"fix_xy": fix_xy, "fix_sigma_m": pos_sigma, "ambiguous": bool(ambiguous),
            "hypotheses": hypotheses, **out}


def should_relocalize(xy_sigma_m, *, threshold_m=2.0, moving=False) -> bool:
    """The active-sensing trigger: spend an articulation parallax maneuver only when the estimator's
    position uncertainty exceeds the tolerance AND the rover is stopped (the maneuver needs a
    standstill). Keeps the cue evidence-gated -- no maneuver when localization is already good."""
    return (not moving) and float(xy_sigma_m) > float(threshold_m)


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
