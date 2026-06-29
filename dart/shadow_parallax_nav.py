"""Shadow-parallax navigation: range + position fix from the LATERAL (two-viewpoint) parallax of cast
shadow-tip landmarks observed across a rover DRIVE baseline.

This is the driving-while-localizing sibling of :mod:`dart.articulated_parallax` (SN-10), which triangulates
from a known VERTICAL camera lift ``dh`` at a STANDSTILL. Here the baseline is the rover's own lateral
motion ``B`` between two viewpoints (from the VO odometry), so the fix is obtained WITHOUT a special
articulation maneuver -- continuously, while driving. The landmarks are CAST SHADOW TIPS: high-contrast
ground points that are abundant and sharp under the grazing polar sun. A tip is a fixed ground point only
within a SUN-STATIC window (the anti-solar azimuth drifts ~0.5 deg/hr at the pole, negligible over a
seconds-long drive baseline; longer baselines must re-anchor the tip -- the honest validity bound).

Geometry (pinhole-exact, identical algebra to the vertical form with ``dh -> B``): a ground landmark at
horizontal range ``R`` projects to image column ``u = fx * (X/Z)``; translating the camera laterally by
``B`` shifts that column by a disparity ``d = fx * B / R`` (the range-independent baseline ``B`` plays the
role of the stereo baseline), so ``R = fx * B / d``. Ranges to >= 2 mapped shadow tips then fix the rover
``(x, y)`` by trilateration -- the SAME GDOP / mirror-ambiguity machinery as articulation parallax, reused
verbatim (do not duplicate).

TRUTH FIREWALL (invariant I3). Inputs are image-derived (shadow-tip pixel disparities), the VO drive
baseline, the camera ``fx``, and the mapped landmark positions; no ground-truth pose is an argument. The
fix is injected into the pose graph as an absolute :class:`~dart.factors.FactorType.PARALLAX_XY` factor
(the unblocked parallax path; metric shadow LENGTH / BOUNDARY factors remain guardrail-blocked).
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey).
from __future__ import annotations

import math

import numpy as np

from dart.articulated_parallax import (
    _landmarks_are_collinear,
    _reflect_across_baseline,
    position_fix_covariance,
    position_fix_from_ranges,
    range_sigma_from_pixel_noise,
)


def range_from_lateral_parallax(baseline_m: float, disparity_px: float, fx_px: float) -> float:
    """Cross-baseline DEPTH [m] to a shadow-tip landmark from its LATERAL parallax disparity [px] across a
    known drive baseline ``B`` (pinhole-exact, ``Z = fx * B / d`` -- the stereo relation with ``B`` the
    inter-viewpoint baseline). A non-positive disparity carries no parallax -> unbounded depth (H-13: not
    a measurement, handled by the caller).

    VALIDITY BOUND (depth vs range). ``Z`` is the depth ALONG the optical axis; it equals the Euclidean
    horizontal range only for a near-ABEAM tip (small off-axis angle ``alpha``, ``range = Z / cos(alpha)``).
    The polar grazing-sun geometry favours that regime (long shadows abeam of the drive), and the
    trilateration's GDOP covariance already down-weights ill-conditioned bearings; a large-``alpha`` tip
    must convert depth->range with its measured bearing before it is fed as a range. This idealisation is
    explicit because the perception front-end that supplies real bearings is the next integration step."""
    if disparity_px <= 0.0:
        return math.inf
    return float(fx_px) * float(baseline_m) / float(disparity_px)


def disparity_for_range(baseline_m: float, range_m: float, fx_px: float) -> float:
    """Forward model: the shadow-tip disparity [px] a landmark at range ``R`` undergoes for a lateral
    drive baseline ``B`` (the inverse of :func:`range_from_lateral_parallax`)."""
    return float(fx_px) * float(baseline_m) / max(1e-9, float(range_m))


def resolvable_range_m(baseline_m: float, fx_px: float, min_disparity_px: float = 1.0) -> float:
    """Max shadow-tip range whose disparity still exceeds ``min_disparity_px`` for a baseline ``B`` (the
    camera-capability envelope; use < 1 for sub-pixel shadow-edge localization). Range grows with the
    baseline -- the navigation payoff of accumulating a longer drive baseline before fixing."""
    return float(fx_px) * float(baseline_m) / max(1e-9, float(min_disparity_px))


def lateral_parallax_range_sigma(range_m: float, baseline_m: float, fx_px: float,
                                 sigma_px: float) -> float:
    """Range 1-sigma from shadow-tip localization noise [px]: ``sigma_R = R^2 / (fx * B) * sigma_px``
    (range error grows as R^2 and shrinks with a longer drive baseline). Reuses the vertical-parallax
    pixel-noise model with ``dh -> B``."""
    return range_sigma_from_pixel_noise(range_m, baseline_m, fx_px, sigma_px)


def shadow_parallax_localize(graph, node_id, landmarks_xy, disparities_px, *, baseline_m, fx_px,
                             sigma_px: float = 0.685):
    """Fix the rover ``(x, y)`` from the LATERAL parallax of mapped shadow tips and inject it into the
    live :class:`~dart.pose_graph_se2.PoseGraphSE2` as an absolute (PARALLAX_XY) factor with the
    geometry-DERIVED covariance. The driving-while-localizing analog of
    :func:`dart.articulated_parallax.articulation_localize`; the trilateration, GDOP covariance, and
    mirror-ambiguity guards (H-13/H-14/M-02/H-30) are reused verbatim.

    ``sigma_px`` defaults to the measured CE-3 shadow-edge localization sigma (~0.685 px). Firewall I3:
    image disparities + VO baseline + mapped landmarks only; no GT. Returns the fix + the re-optimized
    estimate; an AMBIGUOUS fix (< 3 non-collinear tips) is surfaced with both hypotheses and NOT fused."""
    cur = graph.optimize()
    guess = cur[node_id][:2] if node_id in cur else (0.0, 0.0)
    ranges = [range_from_lateral_parallax(baseline_m, d, fx_px) for d in disparities_px]
    # H-13: a non-positive disparity (inf range) is not a measurement -> drop it and its landmark.
    keep = [(Lxy, r) for Lxy, r in zip(landmarks_xy, ranges) if math.isfinite(r) and r > 0.0]
    if len(keep) < 2:
        raise ValueError(
            f"shadow parallax: only {len(keep)} finite range(s) from {len(ranges)} tip(s); need >= 2 "
            "for a heading-free fix")
    vL = [Lxy for Lxy, _ in keep]
    rr = [r for _, r in keep]
    fix_xy = position_fix_from_ranges(vL, rr, guess=guess)
    ambiguous = _landmarks_are_collinear(vL)                            # H-14: mirror pair if collinear
    hypotheses = [fix_xy, _reflect_across_baseline(fix_xy, vL[0], vL[1])] if ambiguous else [fix_xy]
    sig = [lateral_parallax_range_sigma(r, baseline_m, fx_px, sigma_px) for r in rr]
    cov = position_fix_covariance(vL, fix_xy, sig)
    pos_sigma = float(np.sqrt(0.5 * np.trace(cov)))
    fused = not ambiguous                                              # M-02: never fuse an ambiguous fix
    if fused:
        graph.add_absolute_cov(node_id, fix_xy, cov)                   # H-30: full 2x2 cov keeps the GDOP
    out = graph.optimize_with_cov()
    return {"fix_xy": fix_xy, "fix_sigma_m": pos_sigma, "ambiguous": bool(ambiguous),
            "fused": bool(fused), "hypotheses": hypotheses, **out}
